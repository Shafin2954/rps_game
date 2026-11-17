"""The duel: one fight between the hero and a foe.

Classic Rock Paper Scissors decides who wins each round; this module decides
what a win is *worth*. Winners deal damage, both fighters have hit points, and
the hero has Focus to spend on one technique per round:

* Foresight - learn one throw the foe will not make this round,
* Guard     - take no damage this round,
* Charge    - a win this round deals double damage.

Focus comes back by losing or drawing a round, so falling behind is what
powers a comeback. Relics (the hero's) and traits (the foe's) bend these rules;
every such effect is applied here and nowhere else.

No printing, no input. Randomness comes only from the generators passed in, so
a seeded run replays exactly.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Protocol, Sequence

from ..engine import MOVES, Move, Outcome, Round, judge

BASE_DAMAGE = 2
START_HP = 14
START_FOCUS = 1
MAX_FOCUS = 4


class Technique(Enum):
    FORESIGHT = "foresight"
    GUARD = "guard"
    CHARGE = "charge"

    def __str__(self) -> str:
        return self.value


COSTS = {Technique.FORESIGHT: 2, Technique.GUARD: 1, Technique.CHARGE: 2}
TECHNIQUE_TEXT = {
    Technique.FORESIGHT: "Rules out one throw the foe will not make this round.",
    Technique.GUARD: "You take no damage this round.",
    Technique.CHARGE: "If you win this round, you deal double damage.",
}

# Foe traits: key -> (name, what it does).
TRAITS = {
    "armor": ("Armour", "Takes 1 less damage from every hit (at least 1)."),
    "vampire": ("Leech", "Heals 1 HP whenever it wins a round."),
    "enrage": ("Enrage", "Deals +1 damage at half health or less."),
    "thorns": ("Thorns", "Every draw deals 1 damage to you."),
    "heavy_rock": ("Heavy Rock", "Its rock wins deal +2 damage."),
    "study": ("Studied", "Has watched every throw of your climb."),
}


@dataclass(frozen=True)
class Sight:
    """Everything a foe's mind may look at: the past, never the present round."""

    mine: tuple[Move, ...]          # the foe's own throws this fight
    theirs: tuple[Move, ...]        # the hero's throws this fight
    results: tuple[Outcome, ...]    # each round from the foe's point of view
    climb: tuple[Move, ...]         # every throw the hero made on earlier floors
    hurt: bool                      # the foe is at half health or less


class Mind(Protocol):
    def choose(self, sight: Sight) -> Move: ...


@dataclass
class Hero:
    hp: int = START_HP
    max_hp: int = START_HP
    focus: int = START_FOCUS
    max_focus: int = MAX_FOCUS
    shield: int = 0
    relics: list[str] = field(default_factory=list)

    def has(self, relic: str) -> bool:
        return relic in self.relics

    def gain_focus(self, amount: int = 1) -> None:
        self.focus = min(self.max_focus, self.focus + amount)

    def heal(self, amount: int) -> int:
        """Heal up to ``amount``; returns how much was actually restored."""
        healed = max(0, min(amount, self.max_hp - self.hp))
        self.hp += healed
        return healed


@dataclass
class Foe:
    name: str
    hp: int
    damage: int
    mind: Mind
    traits: tuple[str, ...] = ()
    max_hp: int = 0

    def __post_init__(self) -> None:
        self.max_hp = self.max_hp or self.hp

    def has(self, trait: str) -> bool:
        return trait in self.traits

    @property
    def hurt(self) -> bool:
        return self.hp * 2 <= self.max_hp


@dataclass(frozen=True)
class Exchange:
    """One finished round and everything it did."""

    number: int
    round: Round                    # the hero is ``player``; the outcome is the hero's
    technique: Optional[Technique]
    dealt: int                      # damage the foe took
    taken: int                      # damage the hero took, after blocks
    blocked: int                    # damage stopped by Guard or Shield
    foe_healed: int
    notes: tuple[str, ...]          # relic and trait effects that fired, in words


class Duel:
    """A fight in progress. Ask ``intent``/``foresee``, then ``resolve`` each round."""

    def __init__(self, hero: Hero, foe: Foe, *, rng: random.Random | None = None,
                 climb: Sequence[Move] = ()) -> None:
        self.hero, self.foe = hero, foe
        self.exchanges: list[Exchange] = []
        self._rng = rng or random.Random()
        self._climb = tuple(climb)
        self._intent: Optional[Move] = None
        self._ruled_out: Optional[Move] = None
        self._chain = 0                 # hero wins in a row
        self._wins = 0
        self._stung = False             # lost a round since the last win (Counterpunch)
        self._second_wind_spent = False
        self.damage_taken = 0

        hero.shield = 0
        start = START_FOCUS + (2 if hero.has("breath") else 0) - (1 if hero.has("gloves") else 0)
        hero.focus = max(0, min(hero.max_focus, start))
        # Spyglass: the opening throw is known before the first round.
        self.scouted: Optional[Move] = self.intent if hero.has("spyglass") else None

    # ------------------------------------------------------------- state

    @property
    def over(self) -> bool:
        return self.hero.hp <= 0 or self.foe.hp <= 0

    @property
    def won(self) -> bool:
        return self.foe.hp <= 0 and self.hero.hp > 0

    @property
    def round_number(self) -> int:
        return len(self.exchanges) + 1

    @property
    def flawless(self) -> bool:
        return self.won and self.damage_taken == 0

    def _sight(self) -> Sight:
        mine = tuple(x.round.opponent for x in self.exchanges)
        theirs = tuple(x.round.player for x in self.exchanges)
        return Sight(
            mine=mine,
            theirs=theirs,
            results=tuple(judge(m, t) for m, t in zip(mine, theirs)),
            climb=self._climb,
            hurt=self.foe.hurt,
        )

    @property
    def intent(self) -> Move:
        """The foe's throw for the coming round, decided before the hero chooses."""
        if self._intent is None:
            self._intent = self.foe.mind.choose(self._sight())
        return self._intent

    # ------------------------------------------------------------- techniques

    def cost(self, technique: Technique) -> int:
        cost = COSTS[technique]
        if technique is Technique.FORESIGHT and self.hero.has("eye"):
            cost -= 1
        return cost

    def can_use(self, technique: Technique) -> bool:
        return not self.over and self.hero.focus >= self.cost(technique)

    def foresee(self) -> Move:
        """Spend Focus to learn one throw the foe will *not* make this round."""
        if self._ruled_out is None:
            if not self.can_use(Technique.FORESIGHT):
                raise ValueError("not enough Focus for Foresight")
            self.hero.focus -= self.cost(Technique.FORESIGHT)
            self._ruled_out = self._rng.choice([m for m in MOVES if m is not self.intent])
        return self._ruled_out

    # ------------------------------------------------------------- a round

    def resolve(self, move: Move, technique: Optional[Technique] = None) -> Exchange:
        if self.over:
            raise ValueError("the fight is already over")
        hero, foe = self.hero, self.foe
        if technique is Technique.FORESIGHT:
            if self._ruled_out is None:
                raise ValueError("call foresee() before resolving a Foresight round")
        elif technique is not None:
            if not self.can_use(technique):
                raise ValueError(f"not enough Focus for {technique}")
            hero.focus -= self.cost(technique)

        theirs = self.intent
        outcome = judge(move, theirs)
        notes: list[str] = []
        if outcome is Outcome.LOSS and hero.has("coin") and self._rng.random() < 0.25:
            outcome = Outcome.DRAW
            notes.append("Lucky Coin turns the loss into a draw")

        dealt = taken = blocked = foe_healed = 0
        guarded = technique is Technique.GUARD
        if outcome is Outcome.WIN:
            dealt = self._strike(move, technique, notes)
        elif outcome is Outcome.LOSS:
            taken, blocked = self._hurt_hero(self._foe_damage(theirs, notes), guarded, notes)
            if foe.has("vampire") and foe.hp < foe.max_hp:
                foe.hp += 1
                foe_healed = 1
                notes.append("Leech: the foe heals 1")
            hero.gain_focus(1)
            self._chain, self._stung = 0, True
        else:
            hero.gain_focus(2 if hero.has("meditation") else 1)
            if hero.has("static"):
                dealt = min(1, foe.hp)
                foe.hp -= dealt
                notes.append("Static Charge zaps for 1")
            if foe.has("thorns") and foe.hp > 0:
                taken, blocked = self._hurt_hero(1, guarded, notes)
                if taken:
                    notes.append("Thorns sting for 1")

        exchange = Exchange(
            number=self.round_number,
            round=Round(move, theirs, outcome),
            technique=technique,
            dealt=dealt,
            taken=taken,
            blocked=blocked,
            foe_healed=foe_healed,
            notes=tuple(notes),
        )
        self.exchanges.append(exchange)
        self._intent = self._ruled_out = None
        return exchange

    def _strike(self, move: Move, technique: Optional[Technique], notes: list[str]) -> int:
        hero, foe = self.hero, self.foe
        damage = BASE_DAMAGE
        if move is Move.ROCK and hero.has("granite"):
            damage += 2
            notes.append("Granite Knuckles +2")
        if move is Move.SCISSORS and hero.has("whetstone"):
            damage += 1
            hero.gain_focus(1)
            notes.append("Whetstone +1 and 1 Focus")
        if hero.has("momentum") and self._chain:
            bonus = min(3, self._chain)
            damage += bonus
            notes.append(f"Momentum +{bonus}")
        if hero.has("executioner") and foe.hurt:
            damage += 2
            notes.append("Executioner +2")
        if hero.has("counterpunch") and self._stung:
            damage += 2
            notes.append("Counterpunch +2")
        if hero.has("gloves"):
            damage += 1
        if hero.has("glass"):
            damage += 2
        if hero.has("gambit") and self._wins == 0:
            damage *= 2
            notes.append("Opening Gambit doubles it")
        if technique is Technique.CHARGE:
            damage *= 2
            notes.append("Charge doubles it")
        if foe.has("armor"):
            damage = max(1, damage - 1)
            notes.append("Armour soaks 1")
        damage = min(damage, foe.hp)
        foe.hp -= damage

        if move is Move.PAPER and hero.has("origami"):
            hero.shield += 2
            notes.append("Origami Armour: 2 Shield")
        if hero.has("adrenaline") and hero.hp * 2 <= hero.max_hp:
            hero.gain_focus(1)
            notes.append("Adrenaline: 1 Focus")
        self._chain += 1
        self._wins += 1
        self._stung = False
        return damage

    def _foe_damage(self, theirs: Move, notes: list[str]) -> int:
        foe = self.foe
        damage = foe.damage
        if theirs is Move.ROCK and foe.has("heavy_rock"):
            damage += 2
            notes.append("Heavy Rock +2")
        if foe.has("enrage") and foe.hurt:
            damage += 1
            notes.append("Enrage +1")
        return damage

    def _hurt_hero(self, damage: int, guarded: bool, notes: list[str]) -> tuple[int, int]:
        """Apply a hit to the hero. Returns (damage taken, damage blocked)."""
        hero = self.hero
        if hero.has("glass"):
            damage += 1
        if hero.has("skin"):
            damage = max(1, damage - 1)
        if guarded:
            notes.append(f"Guard blocks {damage}")
            return 0, damage
        absorbed = min(hero.shield, damage)
        if absorbed:
            hero.shield -= absorbed
            damage -= absorbed
            notes.append(f"Shield absorbs {absorbed}")
        if damage >= hero.hp and hero.has("wind") and not self._second_wind_spent:
            self._second_wind_spent = True
            damage = hero.hp - 1
            notes.append("Second Wind keeps you standing")
        damage = min(damage, hero.hp)
        hero.hp -= damage
        self.damage_taken += damage
        return damage, absorbed
