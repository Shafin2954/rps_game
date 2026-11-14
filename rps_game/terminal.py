"""Low-level, cross-platform keyboard helpers."""
from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from typing import Iterator

# Named keys. The angle brackets keep them from ever colliding with a typed letter.
KEY_UP = "<up>"
KEY_DOWN = "<down>"
KEY_LEFT = "<left>"
KEY_RIGHT = "<right>"
KEY_ENTER = "<enter>"
KEY_ESC = "<esc>"
KEY_BACKSPACE = "<backspace>"

_POSIX_ARROWS = {b"A": KEY_UP, b"B": KEY_DOWN, b"C": KEY_RIGHT, b"D": KEY_LEFT}
_WINDOWS_ARROWS = {"H": KEY_UP, "P": KEY_DOWN, "M": KEY_RIGHT, "K": KEY_LEFT}


def is_interactive() -> bool:
    """True when both stdin and stdout are a real terminal."""
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def flush_input() -> None:
    """Discard keys typed while the game was busy animating."""
    if not is_interactive():
        return
    if os.name == "nt":
        import msvcrt

        while msvcrt.kbhit():
            msvcrt.getwch()
        return
    import termios

    try:
        termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
    except termios.error:
        pass


_session_active = False


@contextmanager
def keyboard() -> Iterator[None]:
    """Hold the terminal in key-at-a-time, no-echo mode for a whole session.

    Without this, the terminal flips back to normal (echoing, line-buffered)
    mode between key reads, so keys typed while the screen redraws would echo
    onto it or be dropped. Restores the original mode on exit, even on errors.
    A no-op on Windows (msvcrt already reads raw) and when stdin isn't a tty.
    """
    global _session_active
    try:
        usable = os.name != "nt" and sys.stdin.isatty()
    except (AttributeError, ValueError):
        usable = False
    if not usable or _session_active:
        yield
        return
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    # TCSADRAIN, not the default TCSAFLUSH: never throw away typed-ahead keys.
    tty.setcbreak(fd, termios.TCSADRAIN)
    _session_active = True
    try:
        yield
    finally:
        _session_active = False
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def read_key(timeout: float | None = None) -> str | None:
    """Read one key press without waiting for Enter.

    Returns the typed character (any Unicode character, not just ASCII), one of
    the KEY_* names for arrows / Enter / Escape / Backspace, or "" for keys we
    don't care about (F-keys, Home...). With a ``timeout`` in seconds, returns
    None if nothing was pressed in time, so waiting screens can keep animating.
    Raises KeyboardInterrupt on Ctrl-C and EOFError on Ctrl-D / Ctrl-Z.
    """
    if os.name == "nt":
        key = _read_key_windows(timeout)
    else:
        key = _read_key_posix(timeout)
    if key is None:
        return None
    if key == "\x03":
        raise KeyboardInterrupt
    if key == "\x04":
        raise EOFError
    return key


def _read_key_windows(timeout: float | None = None) -> str | None:
    import msvcrt
    import time

    if timeout is not None:
        deadline = time.monotonic() + timeout
        while not msvcrt.kbhit():
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.01)
    ch = msvcrt.getwch()
    if ch in ("\x00", "\xe0"):  # prefix of a special key; the next code says which
        return _WINDOWS_ARROWS.get(msvcrt.getwch(), "")
    if ch == "\x1a":  # Ctrl-Z
        raise EOFError
    if ch == "\r":
        return KEY_ENTER
    if ch == "\x1b":
        return KEY_ESC
    if ch == "\x08":
        return KEY_BACKSPACE
    return ch


def _read_key_posix(timeout: float | None = None) -> str | None:
    import select
    import termios
    import tty

    fd = sys.stdin.fileno()
    # Inside keyboard() the terminal is already in the right mode; otherwise
    # switch for just this one key. cbreak (not raw) keeps Ctrl-C working and
    # output post-processing on, and TCSADRAIN keeps any typed-ahead input.
    old = None if _session_active else termios.tcgetattr(fd)
    try:
        if old is not None:
            tty.setcbreak(fd, termios.TCSADRAIN)
        if timeout is not None and not select.select([fd], [], [], timeout)[0]:
            return None
        data = os.read(fd, 1)
        if not data:
            raise EOFError
        if data[0] >= 0xC0:                 # lead byte of a multi-byte UTF-8 character
            data += _read_continuation(fd, 1 if data[0] < 0xE0 else 2 if data[0] < 0xF0 else 3)
        if data == b"\x1b":
            return _read_escape(fd)
        if data in (b"\r", b"\n"):
            return KEY_ENTER
        if data in (b"\x7f", b"\x08"):
            return KEY_BACKSPACE
        return data.decode("utf-8", errors="ignore")
    finally:
        if old is not None:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _read_escape(fd: int) -> str:
    """Decode what follows an ESC byte: a lone Escape key or an arrow sequence.

    Reads one byte at a time and stops exactly at the end of the sequence, so
    any keys typed right after it are left in the queue for the next read.
    """
    import select

    def next_byte() -> bytes:
        return os.read(fd, 1) if select.select([fd], [], [], 0.05)[0] else b""

    first = next_byte()
    if not first:
        return KEY_ESC                      # nothing followed: the Escape key itself
    if first not in (b"[", b"O"):
        return ""                           # Alt+key or something we don't use
    final = b""
    while True:                             # parameter bytes until the final byte (@..~)
        byte = next_byte()
        if not byte:
            return ""                       # truncated sequence
        if 0x40 <= byte[0] <= 0x7E:
            final = byte
            break
    return _POSIX_ARROWS.get(final, "")


def _read_continuation(fd: int, count: int) -> bytes:
    """Read the rest of a multi-byte UTF-8 character (they arrive together)."""
    import select

    out = b""
    while len(out) < count and select.select([fd], [], [], 0.05)[0]:
        chunk = os.read(fd, count - len(out))
        if not chunk:
            break
        out += chunk
    return out
