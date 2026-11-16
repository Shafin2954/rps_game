"""Commit-reveal: how two players throw "at the same time" over a network.

Each round both players first send a *commitment*: a SHA-256 hash of their move
and a fresh random nonce. Only once both commitments have arrived does either
side reveal the move and nonce, and each side checks the other's reveal against
the commitment it holds. So nobody can see the opponent's move before locking in
their own, and nobody can change their move afterwards.

The hash covers the round number and the player's role, so a commitment can't be
replayed in another round or reflected back at its sender.

The *state* hash chains every finished round. It travels with each commitment,
so if the two games ever disagree about the past (a bug, or tampering) they find
out at the next round instead of silently showing different scores.
"""
from __future__ import annotations

import hashlib
import secrets

from ..engine import Move

INITIAL_STATE = hashlib.sha256(b"rps-state-v1").hexdigest()


def new_nonce() -> str:
    """128 bits of randomness, as 32 hex digits."""
    return secrets.token_hex(16)


def commitment(round_no: int, role: str, move: Move, nonce: str) -> str:
    """The digest a player sends before revealing. ``role`` is "host" or "join"."""
    return hashlib.sha256(f"rps-v1|{round_no}|{role}|{move.value}|{nonce}".encode()).hexdigest()


def next_state(previous: str, round_no: int, host_move: Move, join_move: Move) -> str:
    """Fold one finished round into the running state hash."""
    data = f"{previous}|{round_no}|{host_move.value}|{join_move.value}".encode()
    return hashlib.sha256(data).hexdigest()
