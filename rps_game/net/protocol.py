"""The wire format between two games.

Everything arriving here comes from another person's computer, so it is
treated as hostile: strict size cap, strict JSON (no duplicate keys, no extra
fields), exact types, exact ranges, and names re-validated with the same rules
used locally. Anything off raises ``ProtocolError``; nothing else can escape.

Confidentiality, integrity and ordering of messages come from the Magic
Wormhole channel underneath (a PAKE-derived key and authenticated encryption);
this module only has to make sure that an authenticated-but-misbehaving peer
can't confuse us.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional, Union

from ..identity import valid_install_id
from ..names import check_name
from .config import MAX_MESSAGE_BYTES
from .errors import ProtocolError

MAX_COUNT = 99
_APP = re.compile(r"[0-9A-Za-z.+\-]{1,32}")
NAME_REJECT_REASONS = ("taken", "invalid")
BYE_REASONS = ("quit", "declined", "cancelled", "incompatible")


@dataclass(frozen=True)
class Hello:
    protocol: int
    name: str
    install_id: str
    app: str


@dataclass(frozen=True)
class RejectName:
    reason: str            # a code, never free text: we only ever show our own wording


@dataclass(frozen=True)
class Settings:
    rounds: Optional[int]
    first_to: Optional[int]


@dataclass(frozen=True)
class Accept:
    pass


@dataclass(frozen=True)
class Decline:
    pass


@dataclass(frozen=True)
class Start:
    pass


@dataclass(frozen=True)
class Bye:
    reason: str


@dataclass(frozen=True)
class Ping:
    n: int


@dataclass(frozen=True)
class Pong:
    n: int


Message = Union[Hello, RejectName, Settings, Accept, Decline, Start, Bye, Ping, Pong]


# ---------------------------------------------------------------- encoding

def encode(message: Message) -> bytes:
    if isinstance(message, Hello):
        body = {"t": "hello", "v": message.protocol, "name": message.name,
                "id": message.install_id, "app": message.app}
    elif isinstance(message, RejectName):
        body = {"t": "reject_name", "reason": message.reason}
    elif isinstance(message, Settings):
        body = {"t": "settings", "rounds": message.rounds, "first_to": message.first_to}
    elif isinstance(message, Accept):
        body = {"t": "accept"}
    elif isinstance(message, Decline):
        body = {"t": "decline"}
    elif isinstance(message, Start):
        body = {"t": "start"}
    elif isinstance(message, Bye):
        body = {"t": "bye", "reason": message.reason}
    elif isinstance(message, Ping):
        body = {"t": "ping", "n": message.n}
    elif isinstance(message, Pong):
        body = {"t": "pong", "n": message.n}
    else:                                              # a programming error, not peer input
        raise TypeError(f"cannot encode {message!r}")
    data = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(data) > MAX_MESSAGE_BYTES:
        raise ValueError("message too large")
    return data


# ---------------------------------------------------------------- decoding

def _no_duplicates(pairs):
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise ProtocolError("duplicate field")
        seen[key] = value
    return seen


def _fields(obj: dict, *expected: str) -> None:
    if set(obj) != {"t", *expected}:
        raise ProtocolError("unexpected fields")


def _int(value: object, low: int, high: int, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ProtocolError(f"bad {what}")
    return value


def _count_or_none(value: object, what: str) -> Optional[int]:
    return None if value is None else _int(value, 1, MAX_COUNT, what)


def decode(data: object) -> Message:
    """Parse one message. Raises ProtocolError (only) for anything not valid."""
    if not isinstance(data, (bytes, bytearray)):
        raise ProtocolError("not bytes")
    if len(data) > MAX_MESSAGE_BYTES:
        raise ProtocolError("too large")
    try:
        obj = json.loads(bytes(data).decode("utf-8"), object_pairs_hook=_no_duplicates)
    except ProtocolError:
        raise
    except (ValueError, RecursionError):
        raise ProtocolError("not valid JSON") from None
    if not isinstance(obj, dict) or not isinstance(obj.get("t"), str):
        raise ProtocolError("missing type")

    kind = obj["t"]
    if kind == "hello":
        _fields(obj, "v", "name", "id", "app")
        name = obj["name"]
        if not isinstance(name, str):
            raise ProtocolError("bad name")
        checked = check_name(name)
        if not checked.ok or checked.name != name:     # must already be in tidy form
            raise ProtocolError("bad name")
        if not valid_install_id(obj["id"]):
            raise ProtocolError("bad id")
        app = obj["app"]
        if not isinstance(app, str) or _APP.fullmatch(app) is None:
            raise ProtocolError("bad app")
        return Hello(_int(obj["v"], 0, 10_000, "version"), name, obj["id"], app)
    if kind == "reject_name":
        _fields(obj, "reason")
        if obj["reason"] not in NAME_REJECT_REASONS:
            raise ProtocolError("bad reason")
        return RejectName(obj["reason"])
    if kind == "settings":
        _fields(obj, "rounds", "first_to")
        rounds = _count_or_none(obj["rounds"], "rounds")
        first_to = _count_or_none(obj["first_to"], "first_to")
        if (rounds is None) == (first_to is None):     # exactly one must be set
            raise ProtocolError("bad settings")
        return Settings(rounds, first_to)
    if kind in ("accept", "decline", "start"):
        _fields(obj)
        return {"accept": Accept, "decline": Decline, "start": Start}[kind]()
    if kind == "bye":
        _fields(obj, "reason")
        if obj["reason"] not in BYE_REASONS:
            raise ProtocolError("bad reason")
        return Bye(obj["reason"])
    if kind in ("ping", "pong"):
        _fields(obj, "n")
        n = _int(obj["n"], 0, 2**31 - 1, "counter")
        return Ping(n) if kind == "ping" else Pong(n)
    raise ProtocolError("unknown message")
