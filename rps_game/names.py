"""Player-name rules for Dual Player.

A name is shown on the opponent's screen, so it is untrusted input: it must be
visibly harmless (no control or bidi-override characters that could garble a
terminal) and fit the space above a hand. Two names *collide* when they look
the same after Unicode normalisation, so "Alice", "alice " and a full-width
"Ａlice" cannot sit in the same game.

Known limit: look-alikes from different scripts (a Cyrillic "а" vs a Latin "a")
are not detected.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

from rich.cells import cell_len

MAX_NAME_CELLS = 14          # display width, fits the 19-cell column above a hand
MAX_NAME_CHARS = 32          # code points; bounds strings of zero-width combining marks
RESERVED = frozenset({"you", "computer", "cpu", "bot", "draw", "tie", "opponent"})

# Joiners some scripts (Bengali, Persian, ...) need inside words. Every other
# format character (bidi overrides, zero-width space, ...) is rejected.
_JOINERS = {"\u200c", "\u200d"}
# Removed when comparing, so a hidden joiner can't make a duplicate look unique.
_INVISIBLE = {"\u200b", "\u200c", "\u200d", "\u2060", "\ufeff"}
_SPACES = re.compile(" {2,}")


@dataclass(frozen=True)
class NameCheck:
    name: str                 # the tidied display form ("" when invalid)
    error: Optional[str]      # a message fit to show the player, or None

    @property
    def ok(self) -> bool:
        return self.error is None


def name_key(name: str) -> str:
    """Comparison form: two names are 'the same' when their keys are equal."""
    text = unicodedata.normalize("NFKC", name)
    text = "".join(ch for ch in text if ch not in _INVISIBLE)
    return _SPACES.sub(" ", text).strip().casefold()


def same_name(a: str, b: str) -> bool:
    return name_key(a) == name_key(b)


def check_name(raw: str, *, other: Optional[str] = None) -> NameCheck:
    """Validate and tidy a name. ``other`` is the opponent's name, once known."""
    text = unicodedata.normalize("NFC", raw)
    if any(ch.isspace() and ch != " " for ch in text):
        return NameCheck("", "Names can't contain tabs, line breaks or special spaces.")
    text = _SPACES.sub(" ", text).strip(" ")
    if not text:
        return NameCheck("", "Please enter a name.")

    for ch in text:
        cat = unicodedata.category(ch)
        if ch == " " or ch in _JOINERS:
            continue
        if cat[0] in "LMNPS":
            continue
        return NameCheck("", "Names can only use letters, numbers, spaces and simple punctuation.")
    if unicodedata.category(text[0])[0] not in "LN":
        return NameCheck("", "A name must start with a letter or a number.")

    if len(text) > MAX_NAME_CHARS or cell_len(text) > MAX_NAME_CELLS:
        return NameCheck("", f"Names can be at most {MAX_NAME_CELLS} characters wide.")
    if name_key(text) in RESERVED:
        return NameCheck("", "That name is reserved. Please choose another.")
    if other is not None and same_name(text, other):
        return NameCheck("", "That name is already taken by the other player. "
                             "Please choose another.")
    return NameCheck(text, None)


def name_error(raw: str, other: Optional[str] = None) -> Optional[str]:
    """Just the error message (None when the name is fine); handy as a validator."""
    return check_name(raw, other=other).error
