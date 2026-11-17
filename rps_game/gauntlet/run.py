"""One climb of the Gauntlet, from floor 1 to the Oracle.

A ``Run`` owns the hero, the ladder of foes and the score, and hands out one
``Duel`` per floor. Between fights the hero heals a little and chooses a
reward: one of three relics, or a rest.

Everything random is drawn from generators derived from the run's seed, one
per purpose, so the ladder and the rewards on offer depend only on the seed
(that is what makes a Daily Run the same climb for everyone) while the fights
themselves still depend on what the player throws.
"""
from __future__ import annotations

import datetime
import random
import secrets
from dataclasses import dataclass, field
from typing import Optional

from ..engine import Move, Outcome
from .foes import FLOORS, FoeSpec, build_ladder
from .relics import RELICS, Relic, offer
from .rules import Duel, Hero

HEAL_AFTER_FIGHT = 3
REST_HEAL = 5
FLOOR_POINTS = 100          # times the floor number
FLAWLESS_POINTS = 100
VICTORY_POINTS = 500
HP_POINTS = 25              # per hit point left at the top


def daily_seed(today: datetime.date | None = None) -> str:
    return (today or datetime.date.today()).isoformat()


def random_seed() -> str:
    """A short seed that is easy to read out to a friend."""
    return secrets.token_hex(3).upper()


@dataclass
class Tally:
    rounds: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0
    damage_dealt: int = 0
    damage_taken: int = 0
    flawless: int = 0
    techniques: int = 0
    streak: int = 0                         # round wins in a row (a draw doesn't break it)
    best_streak: int = 0
    lowest_hp_win: Optional[int] = None     # the least HP a fight was won on


@dataclass
class FightReport:
    """What winning (or losing) a fight did to the run."""

    won: bool
    foe: FoeSpec
    floor: int
    flawless: bool
    healed: int = 0
    points: int = 0
    notes: tuple[str, ...] = ()


@dataclass
class Run:
    seed: str
    daily: Optional[str] = None                 # the date, when this is that day's Daily Run
    hero: Hero = field(default_factory=Hero)
    floor: int = 1
    score: int = 0
    tally: Tally = field(default_factory=Tally)
    climb: list[Move] = field(default_factory=list)    # every throw the hero has made
    beaten: list[str] = field(default_factory=list)    # keys of the foes defeated, in order
    fallen_to: Optional[str] = None
    abandoned: bool = False
    duel: Optional[Duel] = None
    clean_floors: int = 0           # floors cleared, counting from the first, with no technique

    def __post_init__(self) -> None:
        self.ladder: list[FoeSpec] = build_ladder(self._rng("ladder"))

    def _rng(self, purpose: str) -> random.Random:
        return random.Random(f"{self.seed}|{purpose}")

    # ------------------------------------------------------------- where we are

    @property
    def foe(self) -> FoeSpec:
        return self.ladder[min(self.floor, FLOORS) - 1]

    @property
    def victory(self) -> bool:
        return len(self.beaten) == FLOORS

    @property
    def over(self) -> bool:
        return self.victory or self.fallen_to is not None or self.abandoned

    @property
    def floors_cleared(self) -> int:
        return len(self.beaten)

    @property
    def bare_hands(self) -> bool:
        """The first five floors were cleared without a single technique."""
        return self.clean_floors >= 5

    # ------------------------------------------------------------- fights

    def begin_fight(self) -> Duel:
        if self.over:
            raise ValueError("the run is over")
        spec = self.foe
        self.duel = Duel(self.hero, spec.spawn(self._rng(f"mind|{self.floor}")),
                         rng=self._rng(f"luck|{self.floor}"), climb=self.climb)
        return self.duel

    def end_fight(self) -> FightReport:
        """Fold the finished duel into the run: tally, score, healing, the next floor."""
        duel = self.duel
        if duel is None or not duel.over:
            raise ValueError("no finished fight to record")
        spec, floor, tally = self.foe, self.floor, self.tally
        self._count(duel)

        if not duel.won:
            self.fallen_to = spec.key
            return FightReport(False, spec, floor, False)

        hero = self.hero
        if self.clean_floors == len(self.beaten) and not any(x.technique for x in duel.exchanges):
            self.clean_floors += 1
        self.beaten.append(spec.key)
        if tally.lowest_hp_win is None or hero.hp < tally.lowest_hp_win:
            tally.lowest_hp_win = hero.hp
        points = FLOOR_POINTS * floor
        notes: list[str] = []
        if duel.flawless:
            tally.flawless += 1
            points += FLAWLESS_POINTS
            notes.append(f"Flawless: +{FLAWLESS_POINTS} points")
        if hero.has("trophy"):
            hero.max_hp += 1
            notes.append("Trophy Belt: +1 maximum HP")
        healed = 0
        if self.victory:
            points += VICTORY_POINTS + HP_POINTS * hero.hp
        else:
            healed = hero.heal(HEAL_AFTER_FIGHT + (2 if hero.has("medic") else 0))
            self.floor += 1
        self.score += points
        return FightReport(True, spec, floor, duel.flawless, healed, points, tuple(notes))

    def _count(self, duel: Duel) -> None:
        """Add a duel's rounds to the tally and let go of it."""
        tally = self.tally
        for x in duel.exchanges:
            self.climb.append(x.round.player)
            tally.rounds += 1
            tally.wins += x.round.outcome is Outcome.WIN
            tally.losses += x.round.outcome is Outcome.LOSS
            tally.draws += x.round.outcome is Outcome.DRAW
            if x.round.outcome is Outcome.WIN:
                tally.streak += 1
                tally.best_streak = max(tally.best_streak, tally.streak)
            elif x.round.outcome is Outcome.LOSS:
                tally.streak = 0
            tally.damage_dealt += x.dealt
            tally.damage_taken += x.taken
            tally.techniques += x.technique is not None
        self.duel = None

    # ------------------------------------------------------------- rewards

    def rewards(self) -> list[Relic]:
        """The relics on offer after clearing the floor just below this one."""
        return offer(self._rng(f"reward|{self.floor}"), self.hero.relics)

    def take(self, key: str) -> Relic:
        relic = RELICS[key]
        hero = self.hero
        if hero.has(key):
            raise ValueError(f"already holding {relic.name}")
        hero.relics.append(key)
        if key == "heart":
            hero.max_hp += 4
            hero.heal(4)
        elif key == "reservoir":
            hero.max_focus += 2
        return relic

    def rest(self) -> int:
        return self.hero.heal(REST_HEAL)

    def abandon(self) -> None:
        """Walk away. Rounds already played in an unfinished fight still count."""
        if self.over:
            return
        self.abandoned = True
        if self.duel is not None:
            self._count(self.duel)
