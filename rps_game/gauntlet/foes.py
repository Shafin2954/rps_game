"""Who you meet in the Gauntlet, and how each of them thinks.

Every foe has a *mind* (how it picks a throw from what it has seen) and a
*tell* (a line shown to the player that hints at that mind). Early foes are
simple enough to be solved outright; later ones add noise, traits and real
pattern reading, until the Oracle at the top, which has studied the whole climb.

The ladder is drawn from four tiers with two fixed gatekeepers:

    floors 1-2  rookies     floor 5   the Warden
    floors 3-4  scrappers   floor 10  the Oracle
    floors 6-7  veterans
    floors 8-9  masters
"""
from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Sequence

from ..engine import MOVES, Move, Outcome
from ..oracle import Oracle, OracleStrategy
from ..strategies import AdaptiveStrategy, PatternStrategy, Strategy
from .rules import Foe, Mind, Sight

FLOORS = 10
R, P, S = Move.ROCK, Move.PAPER, Move.SCISSORS


# ---------------------------------------------------------------- minds

class Biased:
    """Leans on one throw; ``cornered`` replaces the share once it is hurt."""

    def __init__(self, rng: random.Random, move: Move, share: float,
                 cornered: float | None = None) -> None:
        self._rng, self._move, self._share = rng, move, share
        self._cornered = share if cornered is None else cornered

    def choose(self, sight: Sight) -> Move:
        share = self._cornered if sight.hurt else self._share
        return self._move if self._rng.random() < share else self._rng.choice(MOVES)


class Chaos:
    """No pattern at all."""

    def __init__(self, rng: random.Random) -> None:
        self._rng = rng

    def choose(self, sight: Sight) -> Move:
        return self._rng.choice(MOVES)


class Cycle:
    """Repeats a fixed sequence, starting at a random point in it."""

    def __init__(self, rng: random.Random, pattern: Sequence[Move]) -> None:
        self._pattern = tuple(pattern)
        self._offset = rng.randrange(len(self._pattern))

    def choose(self, sight: Sight) -> Move:
        return self._pattern[(self._offset + len(sight.mine)) % len(self._pattern)]


class Reactive:
    """Answers the hero's last throw: ``step`` 0 copies it, 1 beats it, 2 loses to it."""

    def __init__(self, rng: random.Random, step: int, noise: float = 0.0) -> None:
        self._rng, self._step, self._noise = rng, step, noise

    def choose(self, sight: Sight) -> Move:
        if not sight.theirs or self._rng.random() < self._noise:
            return self._rng.choice(MOVES)
        last = sight.theirs[-1]
        return (last, last.beaten_by, last.beats)[self._step]


class Restless:
    """Never throws the same thing twice in a row."""

    def __init__(self, rng: random.Random) -> None:
        self._rng = rng

    def choose(self, sight: Sight) -> Move:
        if not sight.mine:
            return self._rng.choice(MOVES)
        return self._rng.choice([m for m in MOVES if m is not sight.mine[-1]])


class SoreLoser:
    """Win-stay, lose-shift: repeats a winner, counters whatever just beat it."""

    def __init__(self, rng: random.Random) -> None:
        self._rng = rng

    def choose(self, sight: Sight) -> Move:
        if not sight.mine:
            return self._rng.choice(MOVES)
        if sight.results[-1] is Outcome.WIN:
            return sight.mine[-1]
        if sight.results[-1] is Outcome.LOSS:
            return sight.theirs[-1].beaten_by
        return self._rng.choice(MOVES)


class Opportunist:
    """Repeats whatever just worked; otherwise copies the hero."""

    def __init__(self, rng: random.Random) -> None:
        self._rng = rng

    def choose(self, sight: Sight) -> Move:
        if not sight.mine:
            return self._rng.choice(MOVES)
        return sight.mine[-1] if sight.results[-1] is Outcome.WIN else sight.theirs[-1]


class Contrarian:
    """Counters the throw the hero has used most in this fight."""

    def __init__(self, rng: random.Random) -> None:
        self._rng = rng

    def choose(self, sight: Sight) -> Move:
        if not sight.theirs:
            return self._rng.choice(MOVES)
        counts = Counter(sight.theirs)
        most = max(counts.values())
        return self._rng.choice([m for m, n in counts.items() if n == most]).beaten_by


class Shifter:
    """Several minds in one body, swapping every ``every`` rounds."""

    def __init__(self, minds: Sequence[Mind], every: int = 3) -> None:
        self._minds, self._every = tuple(minds), every

    def choose(self, sight: Sight) -> Move:
        return self._minds[(len(sight.mine) // self._every) % len(self._minds)].choose(sight)


class Student:
    """One of the classic computer strategies, fed the whole climb as well as this fight."""

    def __init__(self, strategy: Strategy) -> None:
        self._strategy = strategy

    def choose(self, sight: Sight) -> Move:
        return self._strategy.choose(sight.climb + sight.theirs)


class Seer:
    """The Oracle itself, primed with every throw of the climb."""

    def __init__(self, rng: random.Random) -> None:
        self._rng = rng
        self._strategy: OracleStrategy | None = None

    def choose(self, sight: Sight) -> Move:
        if self._strategy is None:
            oracle = Oracle()
            oracle.prime(sight.climb)
            self._strategy = OracleStrategy(rng=self._rng, oracle=oracle)
        return self._strategy.choose(sight.theirs)


# ---------------------------------------------------------------- the roster

@dataclass(frozen=True)
class FoeSpec:
    key: str
    name: str
    title: str
    tell: str                               # the hint the player is shown
    tier: int                               # 1-4, or 0 for a gatekeeper
    hp: int
    damage: int
    mind: Callable[[random.Random], Mind]
    traits: tuple[str, ...] = ()

    @property
    def full_name(self) -> str:
        return f"{self.name}, {self.title}" if self.title else self.name

    def spawn(self, rng: random.Random) -> Foe:
        return Foe(name=self.name, hp=self.hp, damage=self.damage, mind=self.mind(rng),
                   traits=self.traits)


ROSTER = (
    # -- tier 1: rookies. One idea each, and they never deviate.
    FoeSpec("pebble", "Pebble", "the Stubborn", "Believes in rock. Mostly.",
            1, 6, 2, lambda rng: Biased(rng, R, 0.7)),
    FoeSpec("loop", "Loop", "the Metronome", "Rock, paper, scissors, rock, paper, scissors...",
            1, 6, 2, lambda rng: Cycle(rng, (R, P, S))),
    FoeSpec("parrot", "Parrot", "the Copycat", "Whatever you threw last looked like a good idea.",
            1, 6, 2, lambda rng: Reactive(rng, 0)),
    FoeSpec("flip", "Flip", "the Restless", "Never throws the same thing twice in a row.",
            1, 6, 2, lambda rng: Restless(rng)),
    # -- tier 2: scrappers. Still solvable, but they react to you.
    FoeSpec("grudge", "Grudge", "the Sore Loser",
            "Sticks with a winner. After a loss, throws what would have beaten you.",
            2, 8, 2, lambda rng: SoreLoser(rng)),
    FoeSpec("echo", "Echo", "the Second-Guesser", "Certain you are about to repeat yourself.",
            2, 8, 2, lambda rng: Reactive(rng, 1)),
    FoeSpec("brick", "Brick", "the Wall", "Hides behind paper, and is hard to dent.",
            2, 8, 2, lambda rng: Biased(rng, P, 0.6), ("armor",)),
    FoeSpec("tempo", "Tempo", "the Drummer", "Two beats of everything: rock, rock, paper, paper...",
            2, 8, 2, lambda rng: Cycle(rng, (R, R, P, P, S, S))),
    # -- tier 3: veterans. A readable habit, some noise and a trait that hurts.
    FoeSpec("fang", "Fang", "the Leech", "Repeats whatever just worked; otherwise it copies you.",
            3, 10, 2, lambda rng: Opportunist(rng), ("vampire",)),
    FoeSpec("blitz", "Blitz", "the Berserker", "Loves rock, and loves it more when cornered.",
            3, 10, 2, lambda rng: Biased(rng, R, 0.4, cornered=0.75), ("heavy_rock",)),
    FoeSpec("slick", "Slick", "the Overthinker",
            "Three steps ahead of itself: usually throws what your last throw would have beaten.",
            3, 10, 2, lambda rng: Reactive(rng, 2, noise=0.2)),
    FoeSpec("mirage", "Mirage", "the Contrarian",
            "Counters whichever throw you have leaned on most this fight.",
            3, 10, 2, lambda rng: Contrarian(rng), ("thorns",)),
    # -- tier 4: masters. They hit harder and most of them are reading you.
    FoeSpec("vex", "Vex", "the Trickster",
            "Three faces, a new one every third throw: copies you, counters you, then gives way.",
            4, 12, 3, lambda rng: Shifter([Reactive(rng, 0), Reactive(rng, 1), Reactive(rng, 2)])),
    FoeSpec("cipher", "Cipher", "the Analyst", "Finds the rhythm in anything. Try not to have one.",
            4, 12, 3, lambda rng: Student(PatternStrategy(randomness=0.1, rng=rng)), ("study",)),
    FoeSpec("sage", "Sage", "the Statistician", "Keeps a tally of your last dozen throws.",
            4, 12, 3,
            lambda rng: Student(AdaptiveStrategy(randomness=0.2, window=12, min_history=1, rng=rng)),
            ("armor", "study")),
    FoeSpec("wraith", "Wraith", "the Unseen", "Throws without thought or pattern. Bring a plan.",
            4, 10, 3, lambda rng: Chaos(rng), ("thorns",)),
)

WARDEN = FoeSpec(
    "warden", "The Warden", "",
    "Has watched every throw you made on the way up, and counters your favourite.",
    0, 12, 2,
    lambda rng: Student(AdaptiveStrategy(randomness=0.1, window=14, min_history=1, rng=rng)),
    ("study", "enrage"),
)
ORACLE = FoeSpec(
    "oracle", "The Oracle", "",
    "A council of minds that has studied your whole climb. Habits are fatal here.",
    0, 18, 3, lambda rng: Seer(rng), ("study",),
)

FOES: dict[str, FoeSpec] = {spec.key: spec for spec in (*ROSTER, WARDEN, ORACLE)}


def build_ladder(rng: random.Random) -> list[FoeSpec]:
    """The ten foes of one run, weakest first."""
    def pick(tier: int) -> list[FoeSpec]:
        return rng.sample([spec for spec in ROSTER if spec.tier == tier], 2)

    return [*pick(1), *pick(2), WARDEN, *pick(3), *pick(4), ORACLE]
