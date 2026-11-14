"""Room codes: the public, non-secret part of an invite (the passkey is the secret).

Magic Wormhole requires the room ("nameplate") to be numeric, so a code is nine
digits, shown as 482-193-756. Spaces and hyphens are ignored when typing.
"""
from __future__ import annotations

import secrets
from typing import Optional

DIGITS = 9


def generate_room_code() -> str:
    """Nine random digits, never starting with 0."""
    return str(10 ** (DIGITS - 1) + secrets.randbelow(9 * 10 ** (DIGITS - 1)))


def format_room_code(code: str) -> str:
    return "-".join(code[i:i + 3] for i in range(0, len(code), 3))


def parse_room_code(text: str) -> Optional[str]:
    """Canonical digits for a typed code, or None if it isn't a valid code."""
    digits = text.replace("-", "").replace(" ", "")
    if len(digits) == DIGITS and digits.isascii() and digits.isdigit() and digits[0] != "0":
        return digits
    return None


def room_code_error(text: str) -> Optional[str]:
    if parse_room_code(text) is None:
        return f"A room code is {DIGITS} digits, like 482-193-756."
    return None
