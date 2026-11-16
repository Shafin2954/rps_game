"""A remote human as an ``Opponent``: fair rounds over the connection.

Threading model
---------------
A background *reader* thread owns everything arriving from the other player:
it answers pings, measures round-trip time, enforces the protocol (see the
rules in ``_on_commit`` / ``_on_reveal``), and wakes the game thread through a
condition variable. The game thread never blocks the network and the network
never waits on the screen, so a player who thinks for a minute, or types slowly
in plain mode, is not mistaken for a dropped connection.

Fairness
--------
Each round: send a commitment, wait for the other commitment, only then reveal,
then check the other reveal against their commitment (see ``fairness``). A
revealed move that doesn't match, a reveal sent before we had committed, a
commitment for the wrong round, duplicates, or any unexpected message aborts the
game with a clear error.

Any ``NetError`` raised here means the game is over; the caller treats the
opponent leaving, losing contact, timing out or cheating alike as a forfeit.
"""
from __future__ import annotations

import hmac
import threading
import time
from typing import Callable, Optional

from ..engine import Move, Round
from . import fairness
from . import protocol as proto
from .config import (COMMIT_TIMEOUT, LIVENESS_TIMEOUT, PING_INTERVAL, REMATCH_TIMEOUT,
                     REVEAL_TIMEOUT)
from .errors import (Cancelled, CheatDetected, ConnectionLost, NetError, PeerLeft, ProtocolError,
                     Timeout, TransportError)
from .session import Connection

# Called every fraction of a second while waiting; return False to stop waiting.
WaitHook = Callable[[str], bool]
RECV_SLICE = 0.25


class NetworkOpponent:
    def __init__(
        self,
        connection: Connection,
        *,
        commit_timeout: float = COMMIT_TIMEOUT,
        reveal_timeout: float = REVEAL_TIMEOUT,
        rematch_timeout: float = REMATCH_TIMEOUT,
        ping_interval: float = PING_INTERVAL,
        first_ping_delay: float = 0.5,
        liveness_timeout: float = LIVENESS_TIMEOUT,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.name = connection.opponent_name
        self.opponent_id = connection.opponent_id
        self.on_wait: Optional[WaitHook] = None
        self.rtt_ms: Optional[float] = None

        self._conn = connection
        self._transport = connection.transport
        self._role = connection.role                       # "host" or "join"
        self._their_role = "join" if self._role == "host" else "host"
        self._commit_timeout, self._reveal_timeout = commit_timeout, reveal_timeout
        self._rematch_timeout = rematch_timeout
        self._ping_interval, self._liveness = ping_interval, liveness_timeout
        self._first_ping_delay = first_ping_delay
        self._clock = clock

        self._cv = threading.Condition()                   # guards everything below
        self._send_lock = threading.Lock()
        self._stop = threading.Event()
        self._closed = False
        self._error: Optional[NetError] = None
        self.crash: Optional[BaseException] = None         # an unexpected bug, for diagnosis

        self._round = 1
        self._state = fairness.INITIAL_STATE
        self._my_secret: dict[int, tuple[Move, str]] = {}
        self._sent_commit_round = 0
        self._their_commit: dict[int, tuple[str, str]] = {}   # round -> (digest, their state)
        self._their_reveal: dict[int, Move] = {}
        self._pings: dict[int, float] = {}
        self._ping_n = 0
        self._rematch_sent = self._rematch_recv = False
        self._generation = 0                               # bumps whenever a rematch starts

        self._thread = threading.Thread(target=self._run, name="rps-net", daemon=True)
        self._thread.start()

    # ================================================================ reader thread

    def _run(self) -> None:
        clock = self._clock
        last_heard = clock()
        next_ping = clock() + self._first_ping_delay    # measure the latency early
        try:
            while not self._stop.is_set():
                now = clock()
                if now - last_heard > self._liveness:
                    raise ConnectionLost(self.name)
                if now >= next_ping:
                    with self._cv:
                        self._ping_n += 1
                        n = self._ping_n
                        self._pings[n] = now
                    self._send(proto.Ping(n))
                    next_ping = now + self._ping_interval
                try:
                    raw = self._transport.recv(RECV_SLICE)
                except TransportError:
                    raise ConnectionLost(self.name) from None
                if raw is None:
                    continue
                last_heard = clock()
                self._handle(proto.decode(raw))
        except NetError as exc:
            self._fail(exc)
        except Exception as exc:                           # noqa: BLE001 - a bug; never hang the game
            self.crash = exc
            self._fail(ConnectionLost(self.name))

    def _fail(self, error: NetError) -> None:
        with self._cv:
            if self._error is None:
                self._error = error
            self._stop.set()
            self._cv.notify_all()

    def _handle(self, message: proto.Message) -> None:
        if isinstance(message, proto.Ping):
            self._send(proto.Pong(message.n))
            return
        with self._cv:
            if isinstance(message, proto.Pong):
                sent = self._pings.pop(message.n, None)
                if sent is not None:
                    self.rtt_ms = (self._clock() - sent) * 1000.0
                return
            if isinstance(message, proto.Bye):
                raise PeerLeft(self.name)
            if isinstance(message, proto.Commit):
                self._on_commit(message)
            elif isinstance(message, proto.Reveal):
                self._on_reveal(message)
            elif isinstance(message, proto.Rematch):
                self._rematch_recv = True
                self._maybe_restart()
            else:
                raise ProtocolError("unexpected message during the game")
            self._cv.notify_all()

    # -- protocol rules (called with the lock held) --------------------------------

    def _on_commit(self, msg: proto.Commit) -> None:
        if msg.round not in (self._round, self._round + 1):
            raise ProtocolError("commitment for the wrong round")
        if msg.round in self._their_commit:
            raise ProtocolError("duplicate commitment")
        if msg.round == self._round + 1 and self._round not in self._their_reveal:
            raise ProtocolError("commitment before finishing the previous round")
        self._their_commit[msg.round] = (msg.digest, msg.state)

    def _on_reveal(self, msg: proto.Reveal) -> None:
        r = msg.round
        if r != self._round:
            raise ProtocolError("reveal for the wrong round")
        if r not in self._their_commit:
            raise ProtocolError("reveal without a commitment")
        if r in self._their_reveal:
            raise ProtocolError("duplicate reveal")
        if self._sent_commit_round != r:
            raise ProtocolError("revealed before we had locked in")
        move = Move(msg.move)                              # decode() already limited it to 3 values
        expected = fairness.commitment(r, self._their_role, move, msg.nonce)
        if not hmac.compare_digest(expected, self._their_commit[r][0]):
            raise CheatDetected(self.name)
        self._their_reveal[r] = move

    def _maybe_restart(self) -> None:
        """A rematch starts once *both* sides have asked for one (lock held)."""
        if self._rematch_sent and self._rematch_recv:
            self._round = 1
            self._state = fairness.INITIAL_STATE
            self._my_secret.clear()
            self._their_commit.clear()
            self._their_reveal.clear()
            self._sent_commit_round = 0
            self._rematch_sent = self._rematch_recv = False
            self._generation += 1

    # ================================================================ sending

    def _send(self, message: proto.Message) -> None:
        try:
            with self._send_lock:
                self._transport.send(proto.encode(message))
        except TransportError:
            error = ConnectionLost(self.name)
            self._fail(error)
            raise error from None

    # ================================================================ waiting

    def _wait(self, done: Callable[[], bool], timeout: float, what: str, text: str) -> None:
        deadline = self._clock() + timeout
        while True:
            with self._cv:
                if done():
                    return
                if self._error is not None:
                    raise self._error
                if self._clock() >= deadline:
                    raise Timeout(what)
                self._cv.wait(0.2)
            hook = self.on_wait
            if hook is not None and not hook(text):
                raise Cancelled()

    def _check(self) -> None:
        with self._cv:
            if self._error is not None:
                raise self._error
            if self._closed:
                raise ConnectionLost(self.name)

    # ================================================================ Opponent interface

    def play(self, own: Move) -> Move:
        """One round: commit, wait for their commitment, reveal, verify theirs."""
        self._check()
        nonce = fairness.new_nonce()
        with self._cv:
            r, prev = self._round, self._state
            self._my_secret[r] = (own, nonce)
            self._sent_commit_round = r                    # set *before* sending: no reveal can precede it
        self._send(proto.Commit(r, fairness.commitment(r, self._role, own, nonce), prev))

        self._wait(lambda: r in self._their_commit, self._commit_timeout,
                   f"{self.name} to lock in", f"Waiting for {self.name} to lock in...")
        with self._cv:
            _, their_state = self._their_commit[r]
        if their_state != prev:
            raise ProtocolError("the two games disagree about earlier rounds")

        self._send(proto.Reveal(r, own.value, nonce))
        self._wait(lambda: r in self._their_reveal, self._reveal_timeout,
                   f"{self.name} to reveal", f"Revealing with {self.name}...")
        with self._cv:
            return self._their_reveal[r]

    def record(self, rnd: Round) -> None:
        """Fold the finished round into the shared state and move on."""
        with self._cv:
            r = self._round
            host, join = (rnd.player, rnd.opponent) if self._role == "host" else (
                rnd.opponent, rnd.player)
            self._state = fairness.next_state(self._state, r, host, join)
            self._their_commit.pop(r, None)
            self._their_reveal.pop(r, None)
            self._my_secret.pop(r, None)
            self._round = r + 1
            self._cv.notify_all()

    # ================================================================ for the screens

    def poll_status(self) -> str:
        """What to show while the local player is still choosing. Raises if the game is over."""
        with self._cv:
            if self._error is not None:
                raise self._error
            locked = self._round in self._their_commit
        return f"{self.name} has locked in" if locked else f"{self.name} is choosing..."

    def results_status(self) -> str:
        """For the game-over screen; never raises."""
        with self._cv:
            if self._error is not None:
                return f"{self.name} has left."
            if self._rematch_recv:
                return f"{self.name} wants to play again."
        return ""

    @property
    def error(self) -> Optional[NetError]:
        with self._cv:
            return self._error

    @property
    def state(self) -> str:
        with self._cv:
            return self._state

    @property
    def round(self) -> int:
        with self._cv:
            return self._round

    # ================================================================ rematch / leaving

    def rematch(self) -> None:
        """Ask to play again and wait for the other player to agree."""
        self._check()
        with self._cv:
            generation = self._generation
            self._rematch_sent = True
            self._maybe_restart()
        self._send(proto.Rematch())
        self._wait(lambda: self._generation != generation, self._rematch_timeout,
                   f"{self.name} to agree to play again",
                   f"Waiting for {self.name} to agree to play again...")

    def close(self, reason: str = "quit") -> None:
        """Say goodbye (best effort) and shut down. Safe to call repeatedly."""
        with self._cv:
            if self._closed:
                return
            self._closed = True
            self._stop.set()
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=2.0)
        try:
            self._send(proto.Bye(reason))
        except NetError:
            pass
        self._transport.close()
