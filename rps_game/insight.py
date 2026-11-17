"""The mind reader: what your throws give away.

After a game the player is shown how predictable they were, measured the only
honest way: by replaying their throws to the Oracle and counting how often it
would have won. On top of that sit the classic human tells: a favourite throw,
repeating (or never repeating) yourself, and how you react to a win, a loss
and a draw.

Reactions are filed under three steps relative to your own previous throw:

* ``stay`` - the same throw again,
* ``up``   - the throw that beats your previous one,
* ``down`` - the throw your previous one beats.

Pure functions only; the screens decide where the sentences go.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import Iterable, Optional, Sequence

from .engine import MOVES, Move, Outcome, Round
from .oracle import predictability

MIN_ROUNDS = 8            # fewer than this says nothing about anyone
STEPS = ("stay", "up", "down")
CHANCE = 1 / 3

# What each step means in plain words, by the result that came before it.
_PHRASES = {
    Outcome.WIN: {
        "stay": "repeat the winning throw",
        "down": "copy the throw you just beat",
        "up": "switch to the one throw neither of you used",
    },
    Outcome.LOSS: {
        "stay": "stick with the throw that just lost",
        "up": "copy the throw that just beat you",
        "down": "switch to the one throw neither of you used",
    },
    Outcome.DRAW: {
        "stay": "throw the same thing again",
        "up": "switch to what beats the tied throw",
        "down": "switch to what the tied throw beats",
    },
}
_AFTER = {Outcome.WIN: "After a win", Outcome.LOSS: "After a loss", Outcome.DRAW: "After a draw"}


def step_between(previous: Move, current: Move) -> str:
    if current is previous:
        return "stay"
    return "up" if current is previous.beaten_by else "down"


def count_reactions(rounds: Sequence[Round]) -> dict[str, dict[str, int]]:
    """``{"win": {"stay": 3, "up": 1, "down": 0}, "loss": ..., "draw": ...}``."""
    counts = {outcome.value: dict.fromkeys(STEPS, 0) for outcome in Outcome}
    for before, after in pairwise(rounds):
        counts[before.outcome.value][step_between(before.player, after.player)] += 1
    return counts


def merge_reactions(total: dict[str, dict[str, int]],
                    extra: dict[str, dict[str, int]]) -> None:
    """Add ``extra`` into ``total`` in place."""
    for outcome, steps in extra.items():
        bucket = total.setdefault(outcome, {})
        for step, n in steps.items():
            bucket[step] = bucket.get(step, 0) + n


def _verdict(score: float) -> str:
    if score < 0.38:
        return "Unreadable"
    if score < 0.46:
        return "Hard to read"
    if score < 0.56:
        return "Readable"
    return "An open book"


def reaction_tells(reactions: dict[str, dict[str, int]], *, min_samples: int = 4,
                   min_share: float = 0.6) -> list[tuple[float, str]]:
    """(strength, sentence) for each result you react to in a lopsided way."""
    found = []
    for outcome in (Outcome.LOSS, Outcome.WIN, Outcome.DRAW):
        steps = reactions.get(outcome.value) or {}
        total = sum(steps.get(step, 0) for step in STEPS)
        if total < min_samples:
            continue
        step = max(STEPS, key=lambda s: steps.get(s, 0))
        count = steps.get(step, 0)
        share = count / total
        if share >= min_share:
            habit = f"{_AFTER[outcome]} you {_PHRASES[outcome][step]} ({count} of {total})."
            found.append((share, habit))
    return found


@dataclass(frozen=True)
class Insight:
    rounds: int
    shares: dict[Move, float]          # how often you threw each move
    repeat_rate: float                 # how often you repeated your previous throw
    reactions: dict[str, dict[str, int]]
    predictability: float              # the Oracle's win rate against your throws
    verdict: str
    tells: tuple[str, ...]             # the strongest habits, as sentences

    def lines(self) -> list[str]:
        """The report as short lines of plain text."""
        would_win = (f"A pattern reader would have won {self.predictability:.0%} of these "
                     "rounds (chance is 33%).")
        out = [f"Mind reader: {self.verdict}.", would_win]
        out += list(self.tells)
        if not self.tells:
            out.append("No obvious habits this time. Keep it that way.")
        return out


def analyse(rounds: Iterable[Round]) -> Optional[Insight]:
    """Study one game. None when it was too short to say anything."""
    rounds = list(rounds)
    n = len(rounds)
    if n < MIN_ROUNDS:
        return None
    shares = {move: sum(r.player is move for r in rounds) / n for move in MOVES}
    repeats = sum(a.player is b.player for a, b in pairwise(rounds)) / (n - 1)
    reactions = count_reactions(rounds)
    score = predictability([(r.player, r.opponent) for r in rounds])

    ranked: list[tuple[float, str]] = []
    favourite = max(MOVES, key=lambda m: shares[m])
    if shares[favourite] >= 0.45:
        ranked.append((shares[favourite] + 0.15,
                       f"You threw {favourite} {shares[favourite]:.0%} of the time."))
    if repeats >= 0.55:
        ranked.append((repeats, f"You repeated your previous throw {repeats:.0%} of the time."))
    elif repeats <= 0.15:
        ranked.append((1 - repeats - 0.2,
                       f"You almost never throw the same thing twice in a row ({repeats:.0%})."))
    ranked += reaction_tells(reactions)
    ranked.sort(key=lambda item: item[0], reverse=True)

    return Insight(
        rounds=n,
        shares=shares,
        repeat_rate=repeats,
        reactions=reactions,
        predictability=score,
        verdict=_verdict(score),
        tells=tuple(text for _, text in ranked[:2]),
    )
