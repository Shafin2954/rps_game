"""Spike: run Magic Wormhole (Twisted) in a background thread behind a blocking API.

The game UI is synchronous. This shows the library can live in a daemon thread
with a tiny, thread-safe surface: open(code) / send(bytes) / recv(timeout) / close().
"""
from __future__ import annotations

import queue
import threading
import time
from typing import Optional

import wormhole
from twisted.internet import defer, reactor
from twisted.internet.threads import blockingCallFromThread

APPID = "rps-game-cli.spike/dual"
_started = threading.Event()
_lock = threading.Lock()


def ensure_reactor() -> None:
    """Start the (single, non-restartable) Twisted reactor once per process."""
    with _lock:
        if _started.is_set():
            return
        t = threading.Thread(
            target=lambda: reactor.run(installSignalHandlers=False),
            name="twisted-reactor", daemon=True,
        )
        t.start()
        while not reactor.running:
            time.sleep(0.01)
        _started.set()


class Closed(Exception):
    """The wormhole ended; ``reason`` is the original exception (or None)."""

    def __init__(self, reason: Optional[BaseException]):
        super().__init__(repr(reason))
        self.reason = reason


class Link:
    """One end of a wormhole, usable from any normal thread."""

    def __init__(self, relay_url: str, appid: str = APPID):
        ensure_reactor()
        self._inbox: "queue.Queue[object]" = queue.Queue()
        self._w = blockingCallFromThread(reactor, self._create, relay_url, appid)
        self._done = False

    def _create(self, relay_url, appid):
        return wormhole.create(appid, relay_url, reactor)

    # --- everything below hops onto the reactor thread ---
    def open(self, code: str) -> None:
        """Join/create the room named by ``code`` ("<digits>-<passkey>")."""
        blockingCallFromThread(reactor, self._open, code)

    def _open(self, code):
        self._w.set_code(code)
        self._pump()

    @defer.inlineCallbacks
    def _pump(self):
        try:
            while True:
                msg = yield self._w.get_message()
                self._inbox.put(msg)
        except Exception as exc:          # WrongPasswordError, ServerError, closed...
            self._inbox.put(Closed(exc))

    def send(self, data: bytes) -> None:
        blockingCallFromThread(reactor, lambda: self._w.send_message(data))

    def recv(self, timeout: float = 5.0) -> Optional[bytes]:
        """Next message; None on timeout; raises Closed when the wormhole died."""
        try:
            item = self._inbox.get(timeout=timeout)
        except queue.Empty:
            return None
        if isinstance(item, Closed):
            self._inbox.put(item)         # keep reporting it
            raise item
        return item  # type: ignore[return-value]

    def close(self) -> None:
        if self._done:
            return
        self._done = True
        try:
            blockingCallFromThread(reactor, self._close)
        except Exception:
            pass

    @defer.inlineCallbacks
    def _close(self):
        try:
            yield self._w.close()
        except Exception:
            pass
