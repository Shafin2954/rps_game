"""The connection handshake between a host and a joiner.

    joiner                                host
      |-- hello(name) -------------------->|   host checks the name (valid, not a clash)
      |<-- reject_name(taken|invalid) -----|   ...joiner picks another, up to a few times
      |<-- hello(name) + settings ---------|
      |-- accept | decline --------------->|   joiner agrees to the host's game settings
      |<-- start --------------------------|   both are now connected

Security rules enforced here:
* A message only ever arrives from someone who knew the passkey: the Wormhole
  channel authenticates, and a wrong passkey fails on *both* ends.
* The host counts those failures. After ``max_wrong`` the room is burned
  (``RoomBurned``) so a guesser gets a handful of live attempts, no more.
* Every message is decoded strictly (see ``protocol``). Anything unexpected or out
  of order aborts the handshake.

These classes know nothing about screens. They poll ``tick()`` while waiting
(returning False cancels) and report progress through ``on_status``.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

from .. import __version__
from ..names import check_name, same_name
from ..passkey import Passkey
from . import protocol as proto
from .config import (HOST_LOBBY_TIMEOUT, HUMAN_TIMEOUT, JOIN_TIMEOUT, MAX_NAME_TRIES,
                     MAX_RECONNECTS, MAX_WRONG_PASSKEYS, POLL_SLICE, PROTOCOL_VERSION,
                     STEP_TIMEOUT)
from .errors import (Cancelled, Declined, Incompatible, PeerLeft, ProtocolError, RoomBurned,
                     ServerUnreachable, Timeout, TransportClosed, WrongPasskey)
from .transport import Transport, TransportFactory

Tick = Callable[[], bool]
OnStatus = Callable[..., None]


def _always() -> bool:
    return True


def _ignore(*_args, **_kwargs) -> None:
    return None


@dataclass(frozen=True)
class GameTerms:
    """What the host proposed: exactly N rounds, or first to N wins."""

    rounds: Optional[int] = None
    first_to: Optional[int] = None


class Channel:
    """A Transport plus decoding, deadlines and cancellation."""

    def __init__(self, transport: Transport, tick: Tick = _always) -> None:
        self.transport = transport
        self._tick = tick

    def send(self, message: proto.Message) -> None:
        self.transport.send(proto.encode(message))

    def recv(self, timeout: float, what: str = "the other player") -> proto.Message:
        """The next message. Raises Timeout, Cancelled, PeerLeft, ProtocolError or a
        TransportError. A ``bye`` from the peer is turned into the matching error."""
        deadline = time.monotonic() + timeout
        while True:
            if not self._tick():
                raise Cancelled()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise Timeout(what)
            raw = self.transport.recv(min(POLL_SLICE, remaining))
            if raw is None:
                continue
            message = proto.decode(raw)
            if isinstance(message, proto.Bye):
                if message.reason == "incompatible":
                    raise Incompatible()
                if message.reason == "declined":
                    raise Declined()
                raise PeerLeft()
            return message

    def pause(self, seconds: float) -> None:
        """Sleep, but stay cancellable."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if not self._tick():
                raise Cancelled()
            time.sleep(min(POLL_SLICE, max(0.0, end - time.monotonic())))


@dataclass
class Connection:
    """A finished, agreed handshake. Later phases play the game over ``channel``."""

    transport: Transport
    channel: Channel
    role: str                      # "host" or "join"
    my_name: str
    opponent_name: str
    opponent_id: str
    terms: GameTerms

    def close(self, reason: str = "quit") -> None:
        try:
            self.channel.send(proto.Bye(reason))
        except Exception:                                   # noqa: BLE001 - best effort
            pass
        self.transport.close()


def _terms_from(settings: proto.Settings) -> GameTerms:
    return GameTerms(rounds=settings.rounds, first_to=settings.first_to)


# =====================================================================================
#  Host
# =====================================================================================

class HostSession:
    def __init__(
        self,
        factory: TransportFactory,
        *,
        name: str,
        passkey: Passkey,
        room_code: str,
        terms: GameTerms,
        install_id: str,
        tick: Tick = _always,
        on_status: OnStatus = _ignore,
        lobby_timeout: float = HOST_LOBBY_TIMEOUT,
        step_timeout: float = STEP_TIMEOUT,
        human_timeout: float = HUMAN_TIMEOUT,
        max_wrong: int = MAX_WRONG_PASSKEYS,
    ) -> None:
        self._factory = factory
        self._name, self._passkey, self._room = name, passkey, room_code
        self._terms, self._id = terms, install_id
        self._tick, self._status = tick, on_status
        self._lobby_timeout, self._step_timeout = lobby_timeout, step_timeout
        self._human_timeout, self._max_wrong = human_timeout, max_wrong

    def run(self) -> Connection:
        deadline = time.monotonic() + self._lobby_timeout
        wrong = reconnects = 0
        while True:
            transport = self._factory()
            chan = Channel(transport, self._tick)
            try:
                transport.open(f"{self._room}-{self._passkey.reveal()}")
                self._status("waiting")
                first = chan.recv(max(0.1, deadline - time.monotonic()), "a friend to join")
            except WrongPasskey:
                transport.close()
                wrong += 1
                self._status("wrong_passkey", count=wrong, limit=self._max_wrong)
                if wrong >= self._max_wrong:
                    raise RoomBurned() from None
                continue
            except (TransportClosed, ServerUnreachable):
                transport.close()
                reconnects += 1
                if reconnects > MAX_RECONNECTS:
                    raise
                self._status("reconnecting", count=reconnects)
                chan.pause(1.0)
                continue
            except BaseException:
                transport.close()
                raise
            try:
                return self._handshake(chan, transport, first)
            except BaseException:
                transport.close()
                raise

    def _handshake(self, chan: Channel, transport: Transport, first: proto.Message) -> Connection:
        self._status("negotiating")
        message = first
        for _ in range(MAX_NAME_TRIES):
            if not isinstance(message, proto.Hello):
                raise ProtocolError("expected hello")
            if message.protocol != PROTOCOL_VERSION:
                self._goodbye(chan, "incompatible")
                raise Incompatible()
            verdict = check_name(message.name, other=self._name)
            if verdict.ok:
                break
            reason = "taken" if same_name(message.name, self._name) else "invalid"
            chan.send(proto.RejectName(reason))
            self._status("name_rejected", reason=reason)
            message = chan.recv(self._human_timeout, "a new name")
        else:
            self._goodbye(chan, "quit")
            raise ProtocolError("too many name attempts")
        joiner: proto.Hello = message                      # type: ignore[assignment]

        chan.send(proto.Hello(PROTOCOL_VERSION, self._name, self._id, __version__))
        chan.send(proto.Settings(self._terms.rounds, self._terms.first_to))
        self._status("awaiting_decision", name=joiner.name)
        reply = chan.recv(self._human_timeout, f"{joiner.name} to accept the game")
        if isinstance(reply, proto.Decline):
            raise Declined(joiner.name)
        if not isinstance(reply, proto.Accept):
            raise ProtocolError("expected accept or decline")
        chan.send(proto.Start())
        self._status("starting", name=joiner.name)
        return Connection(transport, chan, "host", self._name, joiner.name, joiner.install_id,
                          self._terms)

    @staticmethod
    def _goodbye(chan: Channel, reason: str) -> None:
        try:
            chan.send(proto.Bye(reason))
        except Exception:                                   # noqa: BLE001
            pass


# =====================================================================================
#  Joiner
# =====================================================================================

class JoinSession:
    def __init__(
        self,
        factory: TransportFactory,
        *,
        name: str,
        passkey: Passkey,
        room_code: str,
        install_id: str,
        ask_name: Callable[[str], Optional[str]],
        confirm_terms: Callable[[str, GameTerms], bool],
        tick: Tick = _always,
        on_status: OnStatus = _ignore,
        join_timeout: float = JOIN_TIMEOUT,
        step_timeout: float = STEP_TIMEOUT,
        human_timeout: float = HUMAN_TIMEOUT,
    ) -> None:
        self._factory = factory
        self._name, self._passkey, self._room, self._id = name, passkey, room_code, install_id
        self._ask_name, self._confirm = ask_name, confirm_terms
        self._tick, self._status = tick, on_status
        self._join_timeout, self._step_timeout = join_timeout, step_timeout
        self._human_timeout = human_timeout

    def run(self) -> Connection:
        transport = self._factory()
        chan = Channel(transport, self._tick)
        try:
            return self._run(chan, transport)
        except BaseException:
            transport.close()
            raise

    def _run(self, chan: Channel, transport: Transport) -> Connection:
        self._status("connecting")
        transport.open(f"{self._room}-{self._passkey.reveal()}")
        name = self._name
        chan.send(proto.Hello(PROTOCOL_VERSION, name, self._id, __version__))
        self._status("waiting_for_host")

        for _ in range(MAX_NAME_TRIES + 1):
            message = chan.recv(self._join_timeout, "the host to answer")
            if isinstance(message, proto.RejectName):
                new = self._ask_name(message.reason)
                if new is None:
                    HostSession._goodbye(chan, "cancelled")
                    raise Cancelled()
                name = new
                chan.send(proto.Hello(PROTOCOL_VERSION, name, self._id, __version__))
                continue
            break
        else:
            raise ProtocolError("too many name attempts")

        if not isinstance(message, proto.Hello):
            raise ProtocolError("expected hello")
        if message.protocol != PROTOCOL_VERSION:
            HostSession._goodbye(chan, "incompatible")
            raise Incompatible()
        if same_name(message.name, name):
            raise ProtocolError("names clash")
        host = message

        settings = chan.recv(self._step_timeout, "the game settings")
        if not isinstance(settings, proto.Settings):
            raise ProtocolError("expected settings")
        terms = _terms_from(settings)

        self._status("deciding", name=host.name)
        if not self._confirm(host.name, terms):
            chan.send(proto.Decline())
            raise Declined("You")
        chan.send(proto.Accept())
        self._status("awaiting_start")
        start = chan.recv(self._step_timeout, f"{host.name} to start the game")
        if not isinstance(start, proto.Start):
            raise ProtocolError("expected start")
        return Connection(transport, chan, "join", name, host.name, host.install_id, terms)
