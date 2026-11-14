"""Who is playing, and where their hand is drawn.

``Seat`` / ``Side`` describe presentation only (a name and which side of *this*
player's screen a hand appears on). ``Opponent`` is the one interface the game
loop talks to, so the same loop runs against the computer today and a remote
human later; only the implementation behind it changes.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Protocol, Sequence

from .engine import Move, Round
from .strategies import Strategy


class Side(Enum):
    LEFT = "left"
    RIGHT = "right"

    @property
    def other(self) -> "Side":
        return Side.RIGHT if self is Side.LEFT else Side.LEFT

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class Seat:
    """A participant as shown on screen."""

    name: str
    side: Side = Side.LEFT


class Opponent(Protocol):
    """The other player, from the local player's point of view."""

    name: str

    def play(self, own: Move) -> Optional[Move]:
        """Take part in one round.

        ``own`` is the local player's already-chosen move. A computer opponent
        must ignore it (it may not peek); a network opponent commits to and
        reveals moves here. Returns the opponent's move, or None if they left.
        """
        ...

    def record(self, rnd: Round) -> None:
        """Called after every completed round with the final result."""
        ...


class CpuOpponent:
    """The computer, driven by a Strategy that only ever sees *past* moves."""

    def __init__(self, strategy: Strategy, name: str = "Computer") -> None:
        self.name = name
        self._strategy = strategy
        self._history: list[Move] = []

    def play(self, own: Move) -> Optional[Move]:
        return self._strategy.choose(self.history)

    def record(self, rnd: Round) -> None:
        self._history.append(rnd.player)

    @property
    def history(self) -> Sequence[Move]:
        return tuple(self._history)
