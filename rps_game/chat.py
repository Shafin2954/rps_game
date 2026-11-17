"""Chat between the two players of an online game.

A message is typed by a stranger and drawn on your screen, so it gets the same
suspicion as a name: only visibly harmless characters (no control codes, no
bidi overrides that could garble a terminal), a single line, and short enough
to fit under the hands. ``tidy`` is what we send; ``valid`` is what we accept.

``ChatLog`` is the conversation as both screens see it. The network thread adds
to it and the screen reads from it, so it locks.
"""
from __future__ import annotations

import re
import threading
import unicodedata
from typing import Optional

from rich.cells import cell_len

MAX_CELLS = 60               # display width: fits on one line next to a name
MAX_CHARS = 120              # code points; bounds strings of zero-width combining marks
MIN_APP = (4, 1)             # the first version that understands chat messages

_JOINERS = {"‌", "‍"}          # needed inside words in some scripts
_SPACES = re.compile(" {2,}")
_VERSION = re.compile(r"(\d+)\.(\d+)")


def tidy(raw: str) -> str:
    """The form a message is sent in: normalised, single spaces, no edges."""
    text = unicodedata.normalize("NFC", raw)
    return _SPACES.sub(" ", text).strip(" ")


def chat_error(raw: str) -> Optional[str]:
    """Why this can't be sent, as a sentence for the player; None when it can."""
    text = tidy(raw)
    if not text:
        return "Type a message first."
    for ch in text:
        if ch == " " or ch in _JOINERS:
            continue
        if unicodedata.category(ch)[0] not in "LMNPS":
            return "Messages can only use letters, numbers, spaces and punctuation."
    if len(text) > MAX_CHARS or cell_len(text) > MAX_CELLS:
        return f"Messages can be at most {MAX_CELLS} characters wide."
    return None


def valid(text: object) -> bool:
    """Is this exactly what a well-behaved game would have sent?"""
    return isinstance(text, str) and chat_error(text) is None and tidy(text) == text


def supports_chat(app_version: str) -> bool:
    """Older games would treat a chat message as cheating, so they never get one."""
    match = _VERSION.match(app_version or "")
    return bool(match) and (int(match.group(1)), int(match.group(2))) >= MIN_APP


class ChatLog:
    """The messages of one online session, oldest first."""

    def __init__(self, them: str, limit: int = 50) -> None:
        self.them = them
        self._limit = limit
        self._lock = threading.Lock()
        self._lines: list[tuple[bool, str]] = []        # (mine?, text)
        self._total = 0
        self._printed = 0                               # how many a line-based screen has shown

    def add(self, text: str, *, mine: bool) -> None:
        with self._lock:
            self._lines.append((mine, text))
            del self._lines[:-self._limit]
            self._total += 1

    @property
    def count(self) -> int:
        """Messages ever added: changes whenever there is something new to draw."""
        with self._lock:
            return self._total

    def recent(self, n: int) -> list[tuple[str, str, bool]]:
        """The last ``n`` messages as (speaker, text, mine?)."""
        with self._lock:
            lines = self._lines[-n:] if n > 0 else []
        return [("You" if mine else self.them, text, mine) for mine, text in lines]

    def unread(self) -> list[str]:
        """Their messages not yet handed out by this method, as sentences
        (for screens that print lines instead of redrawing)."""
        with self._lock:
            fresh = min(self._total - self._printed, len(self._lines))
            self._printed = self._total
            lines = self._lines[-fresh:] if fresh > 0 else []
        return [f"{self.them} says: {text}" for mine, text in lines if not mine]

    def latest_from_them(self) -> Optional[str]:
        with self._lock:
            for mine, text in reversed(self._lines):
                if not mine:
                    return text
        return None
