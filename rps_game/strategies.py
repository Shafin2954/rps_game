"""Computer opponents.

A strategy only needs ``choose(opponent_history)``. Anything that satisfies
that protocol (a network player, a replay bot, ...) can sit in the same slot.
"""
from __future__ import annotations

import random
from collections import Counter
from typing import Protocol, Sequence

from .engine import MOVES, Move
from .oracle import OracleStrategy

DIFFICULTIES = ("easy", "normal", "hard", "oracle")


class Strategy(Protocol):
    def choose(self, opponent_history: Sequence[Move]) -> Move: ...


class RandomStrategy:
    """Uniformly random. Unbeatable in the long run, and a bit boring."""

    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng or random.Random()

    def choose(self, opponent_history: Sequence[Move]) -> Move:
        return self._rng.choice(MOVES)


class AdaptiveStrategy:
    """Counters the opponent's most frequent recent move.

    ``randomness`` is the chance of ignoring the pattern and playing randomly,
    so the bot is beatable and not obviously mechanical.
    """

    def __init__(
        self,
        *,
        randomness: float = 0.4,
        window: int = 10,
        min_history: int = 3,
        rng: random.Random | None = None,
    ) -> None:
        self._randomness = randomness
        self._window = window
        self._min_history = min_history
        self._rng = rng or random.Random()

    def choose(self, opponent_history: Sequence[Move]) -> Move:
        recent = list(opponent_history)[-self._window:]
        if len(recent) < self._min_history or self._rng.random() < self._randomness:
            return self._rng.choice(MOVES)
        counts = Counter(recent)
        top = max(counts.values())
        likely = self._rng.choice([m for m, n in counts.items() if n == top])
        return likely.beaten_by


class PatternStrategy:
    """Looks for sequences in the opponent's play (a small Markov model).

    It asks "what did this player throw the last times they threw these same
    1-3 moves in a row?", prefers the longest context it has seen at least
    twice, falls back to overall frequency, then plays whatever beats the
    prediction. Cycles like R-P-S-R-P-S are punished quickly.
    """

    def __init__(
        self,
        *,
        randomness: float = 0.15,
        max_order: int = 3,
        window: int = 200,
        min_history: int = 4,
        rng: random.Random | None = None,
    ) -> None:
        self._randomness = randomness
        self._max_order = max_order
        self._window = window
        self._min_history = min_history
        self._rng = rng or random.Random()

    def choose(self, opponent_history: Sequence[Move]) -> Move:
        history = list(opponent_history)[-self._window:]
        if len(history) < self._min_history or self._rng.random() < self._randomness:
            return self._rng.choice(MOVES)
        return self._predict(history).beaten_by

    def _predict(self, history: list[Move]) -> Move:
        for order in range(min(self._max_order, len(history) - 1), 0, -1):
            context = tuple(history[-order:])
            followers = Counter(
                history[i + order]
                for i in range(len(history) - order)
                if tuple(history[i:i + order]) == context
            )
            if sum(followers.values()) >= 2:
                return self._top(followers)
        return self._top(Counter(history[-12:]))

    def _top(self, counts: Counter) -> Move:
        best = max(counts.values())
        return self._rng.choice([m for m, n in counts.items() if n == best])


def create_strategy(difficulty: str, rng: random.Random | None = None) -> Strategy:
    """easy: pure chance. normal: counters your favourite. hard: reads sequences.
    oracle: a council of predictors (see oracle.py) with no mercy built in."""
    if difficulty == "easy":
        return RandomStrategy(rng)
    if difficulty == "normal":
        return AdaptiveStrategy(randomness=0.4, window=12, rng=rng)
    if difficulty == "hard":
        return PatternStrategy(randomness=0.15, rng=rng)
    if difficulty == "oracle":
        return OracleStrategy(rng=rng)
    raise ValueError(f"unknown difficulty: {difficulty!r}")
