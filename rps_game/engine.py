"""Pure game logic: no printing, no input, no randomness.

Everything here is deterministic and trivially testable. The UI, the CPU
strategies and (later) network players all build on top of these types.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Move(Enum):
    ROCK = "rock"
    PAPER = "paper"
    SCISSORS = "scissors"

    def __str__(self) -> str:
        return self.value

    @property
    def beats(self) -> "Move":
        """The move this one defeats."""
        return _BEATS[self]

    @property
    def beaten_by(self) -> "Move":
        """The move that defeats this one."""
        return _BEATEN_BY[self]

    @classmethod
    def parse(cls, text: str) -> "Move | None":
        """Turn user input ('r', 'Rock', '1', ...) into a Move, or None."""
        return _ALIASES.get(text.strip().lower())


_BEATS = {
    Move.ROCK: Move.SCISSORS,
    Move.PAPER: Move.ROCK,
    Move.SCISSORS: Move.PAPER,
}
_BEATEN_BY = {loser: winner for winner, loser in _BEATS.items()}

_ALIASES = {
    "r": Move.ROCK, "rock": Move.ROCK, "1": Move.ROCK,
    "p": Move.PAPER, "paper": Move.PAPER, "2": Move.PAPER,
    "s": Move.SCISSORS, "scissors": Move.SCISSORS, "scissor": Move.SCISSORS,
    "3": Move.SCISSORS,
}

MOVES: tuple[Move, ...] = tuple(Move)


class Outcome(Enum):
    """Result of a round from the first player's point of view."""

    WIN = "win"
    LOSS = "loss"
    DRAW = "draw"


def judge(player: Move, opponent: Move) -> Outcome:
    """Decide a single round from ``player``'s point of view."""
    if player is opponent:
        return Outcome.DRAW
    return Outcome.WIN if player.beats is opponent else Outcome.LOSS


@dataclass(frozen=True)
class Round:
    player: Move
    opponent: Move
    outcome: Outcome


@dataclass
class Score:
    """Running tally. A win streak survives draws but not losses."""

    wins: int = 0
    losses: int = 0
    draws: int = 0
    streak: int = 0
    best_streak: int = 0

    def record(self, outcome: Outcome) -> None:
        if outcome is Outcome.WIN:
            self.wins += 1
            self.streak += 1
            self.best_streak = max(self.best_streak, self.streak)
        elif outcome is Outcome.LOSS:
            self.losses += 1
            self.streak = 0
        else:
            self.draws += 1

    @property
    def rounds(self) -> int:
        return self.wins + self.losses + self.draws

    @property
    def win_rate(self) -> float:
        return self.wins / self.rounds if self.rounds else 0.0


@dataclass
class Match:
    """A series of rounds.

    * ``Match()``              - unlimited, never ends.
    * ``Match(first_to=3)``    - first to 3 wins; draws don't count.
    * ``Match(best_of=5)``     - same as first_to=3 (majority of 5).
    * ``Match(max_rounds=10)`` - exactly 10 rounds (draws count as rounds);
      most wins takes it, and equal wins is a DRAW.

    At most one of the three limits may be set.
    """

    best_of: int | None = None
    max_rounds: int | None = None
    first_to: int | None = None
    rounds: list[Round] = field(default_factory=list)
    score: Score = field(default_factory=Score)

    def __post_init__(self) -> None:
        limits = [x for x in (self.best_of, self.max_rounds, self.first_to) if x is not None]
        if len(limits) > 1:
            raise ValueError("choose only one of best_of, max_rounds, first_to")
        if self.best_of is not None and (self.best_of < 1 or self.best_of % 2 == 0):
            raise ValueError("best_of must be an odd positive integer")
        if self.max_rounds is not None and self.max_rounds < 1:
            raise ValueError("max_rounds must be a positive integer")
        if self.first_to is not None and self.first_to < 1:
            raise ValueError("first_to must be a positive integer")

    @property
    def wins_needed(self) -> int | None:
        """Wins that end a race-style match (first_to / best_of), else None."""
        if self.first_to is not None:
            return self.first_to
        return None if self.best_of is None else self.best_of // 2 + 1

    @property
    def winner(self) -> Outcome | None:
        """WIN / LOSS (or DRAW for a tied fixed-length game) once decided."""
        if self.max_rounds is not None:
            if len(self.rounds) < self.max_rounds:
                return None
            if self.score.wins != self.score.losses:
                return Outcome.WIN if self.score.wins > self.score.losses else Outcome.LOSS
            return Outcome.DRAW
        needed = self.wins_needed
        if needed is None:
            return None
        if self.score.wins >= needed:
            return Outcome.WIN
        if self.score.losses >= needed:
            return Outcome.LOSS
        return None

    @property
    def is_over(self) -> bool:
        return self.winner is not None

    def play(self, player: Move, opponent: Move) -> Round:
        if self.is_over:
            raise ValueError("match is already over")
        rnd = Round(player, opponent, judge(player, opponent))
        self.rounds.append(rnd)
        self.score.record(rnd.outcome)
        return rnd
