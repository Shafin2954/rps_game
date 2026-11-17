"""What the foes say.

Every foe has a few lines for winning a round, losing one, falling, and
finishing the hero off. They are flavour, but honest flavour: a foe's chatter
is in character, so it leaks the same habit its tell hints at.

A foe speaks on some decisive rounds, not all of them, and the choice comes
from a seeded generator, so a seeded run says the same things every time. A
mind that can explain itself (the Oracle) is given the floor first when it wins.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

from ..engine import Outcome
from .rules import Duel, Exchange

CHATTINESS = 0.4            # the chance a foe comments on a decisive round


@dataclass(frozen=True)
class Voice:
    win: tuple[str, ...]        # it took the round
    lose: tuple[str, ...]       # it lost the round
    fall: str                   # it has been defeated
    gloat: str                  # it has defeated the hero


VOICES = {
    "pebble": Voice(("Rock.", "Rock never lets me down."),
                    ("That was a fluke.", "Paper is not a real move."),
                    "Maybe... something other than rock...", "Told you. Rock."),
    "loop": Voice(("Right on the beat.", "One, two, three. One, two, three."),
                  ("You're... counting along?", "Tick. Tock. Ouch."),
                  "I lost count.", "Nobody keeps time like me."),
    "parrot": Voice(("Good idea, that last one of yours.", "I learned it from you."),
                    ("Hey! You changed it!", "Stop getting ahead of me."),
                    "Awk. Nothing left to copy.", "You beat yourself, really."),
    "flip": Voice(("Can't sit still. Works for me.", "Never the same thing twice!"),
                  ("You knew what I wouldn't throw...", "Fine. Something else, then."),
                  "Should have... stood still... once.", "Too quick for you."),
    "grudge": Voice(("It worked. I'm doing it again.", "Why change a winner?"),
                    ("Oh, I'll remember that one.", "I know exactly what beats that."),
                    "This isn't over. It is, but it isn't.", "Who's sore now?"),
    "echo": Voice(("You repeated yourself. They always do.", "Knew you'd throw that again."),
                  ("You... changed?", "Nobody changes. Nobody."),
                  "You were never going to repeat, were you.", "Same again? Same again."),
    "brick": Voice(("Flat. Like paper.", "Walls don't lose."),
                   ("That barely scratched.", "Chip away. See if I care."),
                   "...crumbling...", "Everybody breaks on the wall."),
    "tempo": Voice(("And again. And again.", "Two beats each. Keep up."),
                   ("You're on my off-beat.", "Don't rush me."),
                   "The drum... stops.", "You never found the rhythm."),
    "warden": Voice(("I watched you climb. You favour that.",
                     "Your favourite throw is no secret here."),
                    ("You changed your habits. Wise.", "Hm. Not what the stairs told me."),
                    "Go on up. It has been watching longer than I have.",
                    "Every throw on the way up was a confession."),
    "fang": Voice(("Delicious.", "That worked. More of the same."),
                  ("I'll take that back from you.", "Stop being different."),
                  "So... hungry...", "Drained."),
    "blitz": Voice(("ROCK!", "SMASH!"),
                   ("RRRAGH!", "That made me ANGRY."),
                   "...tired now.", "BLITZ WINS!"),
    "slick": Voice(("I knew you knew I knew.", "Three steps ahead. As planned."),
                   ("Wait. You just did the obvious thing?",
                    "Too simple. I never consider simple."),
                   "I think I overthought this.", "All according to a plan I had."),
    "mirage": Voice(("You lean on that one. I lean back.", "Your favourite, countered."),
                    ("You spread them out. Annoying.", "Stop being so balanced."),
                    "No favourites... no way in...", "You had a favourite. I had its answer."),
    "vex": Voice(("Which face was that? Guess.", "Three of us, one of you."),
                 ("You counted to three. Rude.", "That face was our least favourite anyway."),
                 "All three of us agree. You win.", "We took turns beating you."),
    "cipher": Voice(("A pattern. There is always a pattern.", "Sequence confirmed."),
                    ("Insufficient data.", "Noise. You are throwing noise."),
                    "No rhythm. Nothing to solve. Well played.",
                    "You were solved several rounds ago."),
    "sage": Voice(("The tally said so.", "Your last dozen throws were clear enough."),
                  ("An outlier.", "The numbers are shifting."),
                  "Statistically, this was unlikely.", "The count never lies."),
    "wraith": Voice(("...", "No reason. No pattern."),
                    ("...", "Luck. Yours, this time."),
                    "......", "Nothing to read. Nothing to beat."),
    "oracle": Voice(("I saw that throw before you made it.", "You are legible."),
                    ("Unforeseen.", "You are harder to read than your climb suggested."),
                    "I did not see this. How refreshing.",
                    "You were written down long before you arrived."),
}


def quip(key: str, duel: Duel, x: Exchange, rng: random.Random, *, avoid: str = ""
         ) -> Optional[str]:
    """What the foe says about a round, if anything. Call once per round.
    ``avoid`` is its previous line, so it doesn't say the same thing twice running."""
    foe_won = x.round.outcome is Outcome.LOSS
    explain = getattr(duel.foe.mind, "explain", None)
    if explain is not None:                             # always told, so it can keep count
        reading = explain(x.round.player, foe_won)
        if reading:
            return reading
    if x.round.outcome is Outcome.DRAW or duel.over or rng.random() >= CHATTINESS:
        return None
    voice = VOICES[key]
    lines = voice.win if foe_won else voice.lose
    return rng.choice([line for line in lines if line != avoid] or list(lines))


def last_words(key: str, *, hero_won: bool) -> str:
    """The line that closes a fight: the foe's fall, or its gloat over the hero."""
    voice = VOICES[key]
    return voice.fall if hero_won else voice.gloat
