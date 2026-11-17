"""How bytes get between two games.

``Transport`` is a small *blocking*, thread-safe interface so the rest of the
game (which is synchronous) never sees Twisted. Two implementations:

* ``WormholeTransport`` - the real thing, over a Magic Wormhole mailbox. Twisted
  runs in one background thread; every call hops onto it and back.
* ``MemoryMailbox`` - an in-process stand-in with the same observable behaviour
  (pairing, wrong-passkey on both ends, a full room ignoring a third party),
  used by tests so the handshake logic can be exercised quickly and
  deterministically, including with hostile messages injected.
"""
from __future__ import annotations

import queue
import threading
import time
from typing import Callable, Optional, Protocol

from .config import APPID
from .errors import ServerUnreachable, TransportClosed, TransportError, WrongPasskey


class Transport(Protocol):
    def open(self, code: str) -> None:
        """Join (or create) the room named by ``code`` = "<digits>-<passkey>"."""

    def send(self, data: bytes) -> None: ...

    def recv(self, timeout: float) -> Optional[bytes]:
        """Next message, or None if nothing arrived within ``timeout`` seconds.
        Raises a ``TransportError`` subclass if the connection failed."""

    def close(self) -> None: ...


TransportFactory = Callable[[], Transport]


# ======================================================================
#  Real transport: Magic Wormhole
# ======================================================================

_reactor_lock = threading.Lock()
_reactor_started = threading.Event()


def _ensure_reactor() -> None:
    """Start Twisted's (single, non-restartable) reactor once per process."""
    from twisted.internet import reactor

    with _reactor_lock:
        if _reactor_started.is_set():
            return
        thread = threading.Thread(
            target=lambda: reactor.run(installSignalHandlers=False),
            name="twisted-reactor", daemon=True,
        )
        thread.start()
        deadline = time.monotonic() + 10
        while not reactor.running:
            if time.monotonic() > deadline:
                raise TransportError("Could not start the networking engine.")
            time.sleep(0.01)
        _reactor_started.set()


class _Closed(Exception):
    """Internal marker pushed into the inbox when the wormhole ends."""

    def __init__(self, reason: Optional[BaseException]):
        super().__init__(repr(reason))
        self.reason = reason


def _translate(reason: Optional[BaseException], url: str) -> TransportError:
    """Map a Wormhole/Twisted failure onto our own, player-friendly errors."""
    name = type(reason).__name__ if reason is not None else ""
    if name == "WrongPasswordError":
        return WrongPasskey()
    if name in ("ServerConnectionError", "ConnectionRefusedError", "DNSLookupError",
                "TimeoutError", "ConnectError", "NoRouteError"):
        return ServerUnreachable(url)
    return TransportClosed(name)


class WormholeTransport:
    """One end of one wormhole. Create a new instance per attempt."""

    def __init__(self, relay_url: str, appid: str = APPID) -> None:
        self._url = relay_url
        self._appid = appid
        self._inbox: "queue.Queue[object]" = queue.Queue()
        self._w = None
        self._closed = False

    def open(self, code: str) -> None:
        import wormhole                                    # heavy: only loaded when playing online
        from twisted.internet import reactor
        from twisted.internet.threads import blockingCallFromThread

        _ensure_reactor()

        def start():
            self._w = wormhole.create(self._appid, self._url, reactor)
            self._w.set_code(code)
            self._pump()

        blockingCallFromThread(reactor, start)

    def _pump(self) -> None:
        from twisted.internet import defer

        @defer.inlineCallbacks
        def loop():
            try:
                while True:
                    message = yield self._w.get_message()
                    self._inbox.put(message)
            except Exception as exc:                       # noqa: BLE001 - anything ends the wormhole
                self._inbox.put(_Closed(exc))

        loop()

    def send(self, data: bytes) -> None:
        from twisted.internet import reactor
        from twisted.internet.threads import blockingCallFromThread

        if self._w is None or self._closed:
            raise TransportClosed()
        try:
            blockingCallFromThread(reactor, lambda: self._w.send_message(data))
        except Exception as exc:                           # noqa: BLE001
            raise _translate(exc, self._url) from None

    def recv(self, timeout: float) -> Optional[bytes]:
        try:
            item = self._inbox.get(timeout=max(0.0, timeout))
        except queue.Empty:
            return None
        if isinstance(item, _Closed):
            self._inbox.put(item)                          # keep reporting it
            raise _translate(item.reason, self._url)
        return item  # type: ignore[return-value]

    def close(self) -> None:
        if self._closed or self._w is None:
            self._closed = True
            return
        self._closed = True
        from twisted.internet import defer, reactor
        from twisted.internet.threads import blockingCallFromThread

        @defer.inlineCallbacks
        def shut():
            try:
                yield self._w.close()
            except Exception:                              # noqa: BLE001
                pass

        try:
            blockingCallFromThread(reactor, shut)
        except Exception:                                  # noqa: BLE001
            pass


ONLINE_MISSING = [
    "Dual Player needs the online add-on, which is not installed.",
    "Install it with:  pip install magic-wormhole",
    "Everything else (Single Player, the Gauntlet, stats) works without it.",
]


def online_available() -> bool:
    """Is the optional online add-on (Magic Wormhole) installed?"""
    import importlib.util

    try:
        return importlib.util.find_spec("wormhole") is not None
    except (ImportError, ValueError):
        return False


def create_transport(relay_url: str) -> WormholeTransport:
    return WormholeTransport(relay_url)


# ======================================================================
#  Test double: an in-memory mailbox
# ======================================================================

class MemoryMailbox:
    """Pairs ``MemoryTransport`` ends by room, like the real mailbox does.

    * The first end in a room creates it; the second must use the same passkey,
      otherwise *both* ends fail with ``WrongPasskey`` and the room is gone.
    * Messages sent before the peer arrives are delivered once it does.
    * A third end into a full room is silently ignored (it just never hears anything).
    * ``tamper`` (optional) can rewrite or drop messages in flight:
      ``tamper(sender_role, data) -> bytes | None``.
    """

    def __init__(self) -> None:
        self._rooms: dict[str, dict] = {}
        self._lock = threading.Lock()
        self.tamper: Optional[Callable[[str, bytes], Optional[bytes]]] = None
        self.attempts: list[tuple[str, str]] = []          # (room, passkey) in arrival order

    def transport(self) -> "MemoryTransport":
        return MemoryTransport(self)

    # -- called by MemoryTransport
    def _join(self, end: "MemoryTransport", code: str) -> None:
        room_id, _, passkey = code.partition("-")
        with self._lock:
            self.attempts.append((room_id, passkey))
            room = self._rooms.get(room_id)
            if room is None:
                self._rooms[room_id] = {"passkey": passkey, "ends": [end]}
                end._role = "first"
                return
            if len(room["ends"]) >= 2:
                end._role = "extra"                         # crowded: ignored
                return
            first = room["ends"][0]
            if passkey != room["passkey"]:
                del self._rooms[room_id]
                first._inbox.put(_Closed(WrongPasskey()))
                end._inbox.put(_Closed(WrongPasskey()))
                end._role = "second"
                return
            room["ends"].append(end)
            end._role = "second"
            end._peer, first._peer = first, end
            for data in first._pending:                     # flush what was sent early
                self._deliver(first, data)
            for data in end._pending:
                self._deliver(end, data)
            first._pending.clear()
            end._pending.clear()

    def _deliver(self, sender: "MemoryTransport", data: bytes) -> None:
        if self.tamper is not None:
            data = self.tamper(sender._role, data)
            if data is None:
                return
        sender._peer._inbox.put(data)

    def _leave(self, end: "MemoryTransport") -> None:
        with self._lock:
            for room_id, room in list(self._rooms.items()):
                if end in room["ends"]:
                    for other in room["ends"]:
                        if other is not end:
                            other._inbox.put(_Closed(None))
                    del self._rooms[room_id]


class MemoryTransport:
    def __init__(self, mailbox: MemoryMailbox) -> None:
        self._mailbox = mailbox
        self._inbox: "queue.Queue[object]" = queue.Queue()
        self._pending: list[bytes] = []
        self._peer: Optional[MemoryTransport] = None
        self._role = ""
        self._closed = False

    def open(self, code: str) -> None:
        self._mailbox._join(self, code)

    def send(self, data: bytes) -> None:
        if self._closed:
            raise TransportClosed()
        if self._role == "extra":
            return
        with self._mailbox._lock:
            if self._peer is None:
                self._pending.append(data)
                return
            self._mailbox._deliver(self, data)

    def recv(self, timeout: float) -> Optional[bytes]:
        try:
            item = self._inbox.get(timeout=max(0.0, timeout))
        except queue.Empty:
            return None
        if isinstance(item, _Closed):
            self._inbox.put(item)
            raise item.reason if isinstance(item.reason, TransportError) else TransportClosed()
        return item  # type: ignore[return-value]

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._mailbox._leave(self)
