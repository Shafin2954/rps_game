"""The Oracle: a council of predictors that learns how *you* play.

Rock Paper Scissors has no best move, only a best guess about the other
player. The Oracle keeps a panel of small models of its opponent:

* how often they throw each move lately,
* what they tend to throw after their own last one, two or three throws,
* what they throw after the Oracle's last throw, and after both together,
* how they react to winning, losing and drawing (stay / step up / step down),
* the longest stretch of earlier play that looks like the current moment.

Every model's guess is turned into three *experts*: counter the guess, counter
what a player who expected that would do, and one level deeper still. Each
expert is scored on how its advice would have fared so far (recent rounds
count most). The Oracle follows the best expert while one is ahead, and falls
back to pure chance when none is, so a truly random player holds it to a draw
while any habit, however subtle, is found and punished.

``Oracle`` is the model; ``OracleStrategy`` plugs it into the ``Strategy``
slot used by the computer opponent.
"""
from __future__ import annotations

import random
from collections import Counter
from typing import Callable, Optional, Sequence

from .engine import MOVES, Move, Outcome, judge

# Moves as 0, 1, 2 with (i + 1) % 3 beating i: rock < paper < scissors < rock.
_INDEX = {Move.ROCK: 0, Move.PAPER: 1, Move.SCISSORS: 2}
_MOVE = (Move.ROCK, Move.PAPER, Move.SCISSORS)

Predictor = Callable[["Oracle"], Optional[int]]


def _top(counts: Counter, order: Sequence[int]) -> Optional[int]:
    """The most common key; ties go to whichever was seen most recently."""
    if not counts:
        return None
    best = max(counts.values())
    for item in reversed(order):
        if counts.get(item) == best:
            return item
    return None


class Oracle:
    """Watches a game one round at a time and advises what to throw next."""

    def __init__(self, *, decay: float = 0.9, threshold: float = 0.4) -> None:
        self._decay = decay
        self._threshold = threshold
        self._theirs: list[int] = []
        self._mine: list[Optional[int]] = []          # None: a throw we never saw (see prime())
        self._predictors: list[tuple[str, Predictor]] = [
            ("recent", lambda o: o._frequency(6)),
            ("favourite", lambda o: o._frequency(30)),
            ("habit-1", lambda o: o._after_theirs(1)),
            ("habit-2", lambda o: o._after_theirs(2)),
            ("habit-3", lambda o: o._after_theirs(3)),
            ("answer-1", lambda o: o._after_mine(1)),
            ("answer-2", lambda o: o._after_mine(2)),
            ("moment-1", lambda o: o._after_both(1)),
            ("moment-2", lambda o: o._after_both(2)),
            ("reaction", lambda o: o._reaction()),
            ("echo", lambda o: o._longest_match()),
        ]
        # One expert per (predictor, depth of second-guessing).
        self._scores: dict[tuple[str, int], float] = {
            (name, depth): 0.0 for name, _ in self._predictors for depth in range(3)
        }
        self._advice: dict[tuple[str, int], int] = {}
        self._fresh = False                            # is _advice for the upcoming round?
        self.last_read: Optional[tuple[str, int]] = None   # (predictor, depth) behind the advice

    # ------------------------------------------------------------- learning

    @property
    def rounds(self) -> int:
        return len(self._theirs)

    def prime(self, their_throws: Sequence[Move]) -> None:
        """Start with throws seen elsewhere (we don't know what they faced)."""
        for move in their_throws:
            self._theirs.append(_INDEX[move])
            self._mine.append(None)
        self._fresh = False

    def observe(self, theirs: Move, mine: Optional[Move]) -> None:
        """Record a finished round and grade every expert on it."""
        actual = _INDEX[theirs]
        if not self._fresh:
            self._consult()
        for key, throw in self._advice.items():
            if throw == (actual + 1) % 3:
                gain = 1.0
            elif actual == (throw + 1) % 3:
                gain = -1.0
            else:
                gain = 0.0
            self._scores[key] = self._scores[key] * self._decay + gain
        self._theirs.append(actual)
        self._mine.append(None if mine is None else _INDEX[mine])
        self._fresh = False

    # ------------------------------------------------------------- advising

    def _consult(self) -> None:
        advice: dict[tuple[str, int], int] = {}
        for name, predict in self._predictors:
            guess = predict(self)
            if guess is None:
                continue
            for depth in range(3):
                advice[(name, depth)] = (guess + 1 + 2 * depth) % 3
        self._advice, self._fresh = advice, True

    def advise(self) -> tuple[Optional[Move], float]:
        """(the throw to make, how far ahead the expert behind it is).

        The throw is None when no expert has earned any trust, in which case
        the only sound play is a random one.
        """
        if not self._fresh:
            self._consult()
        best_key, best = None, self._threshold
        for key in self._advice:
            score = self._scores[key]
            if score > best:
                best_key, best = key, score
        self.last_read = best_key
        if best_key is None:
            return None, 0.0
        return _MOVE[self._advice[best_key]], best

    def last_result(self) -> Optional[int]:
        """How the latest round went for them: 1 won, -1 lost, 0 drew, None unknown."""
        return self._result(len(self._theirs) - 1) if self._theirs else None

    # ------------------------------------------------------------- the panel

    def _frequency(self, window: int) -> Optional[int]:
        recent = self._theirs[-window:]
        if len(recent) < 3:
            return None
        return _top(Counter(recent), recent)

    def _followers(self, context: Callable[[int], Optional[tuple]], order: int) -> Optional[int]:
        """What they threw whenever the ``order`` rounds before looked like now."""
        n = len(self._theirs)
        if n <= order:
            return None
        now = context(n)
        if now is None:
            return None
        seen: list[int] = []
        for i in range(order, n):
            if context(i) == now:
                seen.append(self._theirs[i])
        if not seen:
            return None
        return _top(Counter(seen), seen)

    def _after_theirs(self, order: int) -> Optional[int]:
        return self._followers(lambda i: tuple(self._theirs[i - order:i]), order)

    def _after_mine(self, order: int) -> Optional[int]:
        def context(i: int) -> Optional[tuple]:
            window = tuple(self._mine[i - order:i])
            return None if None in window else window
        return self._followers(context, order)

    def _after_both(self, order: int) -> Optional[int]:
        def context(i: int) -> Optional[tuple]:
            mine = tuple(self._mine[i - order:i])
            return None if None in mine else (tuple(self._theirs[i - order:i]), mine)
        return self._followers(context, order)

    def _result(self, i: int) -> Optional[int]:
        """How round ``i`` went for them: 1 won, -1 lost, 0 drew, None unknown."""
        mine = self._mine[i]
        if mine is None:
            return None
        theirs = self._theirs[i]
        if theirs == mine:
            return 0
        return 1 if theirs == (mine + 1) % 3 else -1

    def _reaction(self) -> Optional[int]:
        """Win-stay / lose-shift and friends: their step after each kind of result."""
        n = len(self._theirs)
        if n < 2:
            return None
        last = self._result(n - 1)
        if last is None:
            return None
        steps: list[int] = []
        for i in range(1, n):
            if self._result(i - 1) == last:
                steps.append((self._theirs[i] - self._theirs[i - 1]) % 3)
        if len(steps) < 2:
            return None
        step = _top(Counter(steps), steps)
        return None if step is None else (self._theirs[-1] + step) % 3

    def _longest_match(self) -> Optional[int]:
        """Find the longest earlier stretch identical to the latest rounds."""
        n = len(self._theirs)
        pairs = list(zip(self._theirs, self._mine))
        for length in range(min(6, n - 1), 0, -1):
            tail = pairs[n - length:]
            if any(mine is None for _, mine in tail):
                continue
            for start in range(n - length - 1, -1, -1):
                if pairs[start:start + length] == tail:
                    return self._theirs[start + length]
        return None


# What the Oracle says after winning on a confident read, by which model saw it coming.
# ``{move}`` is what the player threw; ``{after}`` is "a win", "a loss" or "a draw".
_SAYINGS = {
    "recent": "You have been leaning on {move}. I leaned back.",
    "favourite": "{Move} is your favourite. It shows.",
    "habit": "After throws like your last ones, you always reach for {move}.",
    "answer": "That is how you answer my last throw. Every time.",
    "moment": "We have stood exactly here before. You threw {move} then, too.",
    "reaction": "After {after} you always make the same step. I was already there.",
    "echo": "This whole stretch has happened before. So had your {move}.",
}
_SECOND_GUESS = {
    1: "You tried to step one ahead of me. I was waiting there.",
    2: "A double bluff. I had counted on it.",
}
_AFTER = {1: "a win", -1: "a loss", 0: "a draw"}
# An expert's score after about seven right answers running. Against a random
# player some expert is always on a short lucky streak; this is the level a
# real habit reaches and luck rarely does.
SURE = 5.0


class OracleStrategy:
    """The Oracle as a computer opponent.

    ``noise`` is the chance of ignoring the council and throwing at random,
    which keeps a lesser version beatable by something other than chaos.
    After a round, ``explain`` may say how it saw the player's throw coming.
    """

    voice = "The Oracle"

    def __init__(self, *, noise: float = 0.0, rng: random.Random | None = None,
                 oracle: Oracle | None = None) -> None:
        self._rng = rng or random.Random()
        self._noise = noise
        self._oracle = oracle or Oracle()
        self._seen = 0                                 # opponent throws already learned from
        self._pending: Optional[Move] = None           # our throw for the round in flight
        self.confidence = 0.0
        self._read: Optional[tuple[str, int]] = None   # the model behind the throw in flight
        self._after: Optional[int] = None              # how the round before it went for them
        self._quiet = 3                                # rounds since it last spoke

    def choose(self, opponent_history: Sequence[Move]) -> Move:
        new = list(opponent_history)[self._seen:]
        for i, theirs in enumerate(new):
            # Only the newest throw can be paired with our own last one.
            mine = self._pending if i == len(new) - 1 else None
            self._oracle.observe(theirs, mine)
        self._seen = len(opponent_history)

        throw, self.confidence = self._oracle.advise()
        self._read, self._after = self._oracle.last_read, self._oracle.last_result()
        if throw is None or self._rng.random() < self._noise:
            throw, self._read = self._rng.choice(MOVES), None
        self._pending = throw
        return throw

    def explain(self, theirs: Move, won: bool) -> Optional[str]:
        """After a round: if the Oracle won it on a read it was sure of, how it knew.

        It speaks at most every third round, and only when the model behind the
        throw had been right many times running, so it rarely brags about luck."""
        read, self._read = self._read, None
        self._quiet += 1
        if not won or read is None or self.confidence < SURE or self._quiet < 3:
            return None
        self._quiet = 0
        name, depth = read
        if depth:
            return _SECOND_GUESS[depth]
        family = name.split("-")[0]
        if family == "reaction" and self._after is None:
            family = "habit"
        return _SAYINGS[family].format(move=theirs.value, Move=theirs.value.capitalize(),
                                       after=_AFTER.get(self._after, ""))


def predictability(pairs: Sequence[tuple[Move, Optional[Move]]]) -> float:
    """How often the Oracle would have beaten the first player of each pair.

    Replays the game round by round, asking the Oracle for its throw before
    showing it what happened. Rounds where it had no opinion count as the one
    in three a blind guess would win, so a perfectly random player scores about
    0.33 and a metronome close to 1.0.
    """
    if not pairs:
        return 0.0
    oracle = Oracle()
    won = 0.0
    for theirs, mine in pairs:
        throw, _ = oracle.advise()
        if throw is None:
            won += 1 / 3
        elif judge(throw, theirs) is Outcome.WIN:
            won += 1.0
        oracle.observe(theirs, mine)
    return won / len(pairs)
