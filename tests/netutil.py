"""Shared helpers for the network tests."""
import threading
import time

from rps_game.net import protocol as proto
from rps_game.net.session import GameTerms, HostSession, JoinSession
from rps_game.net.transport import MemoryMailbox
from rps_game.passkey import Passkey

ROOM, PASS = "482193756", "hunter22"


def connected_pair(box=None, terms=GameTerms(first_to=3)):
    """A host Connection and a joiner Connection, handshaken over the memory mailbox."""
    box = box or MemoryMailbox()
    out = {}

    def host():
        out["host"] = HostSession(box.transport, name="Sohan", passkey=Passkey(PASS), room_code=ROOM,
                                  terms=terms, install_id="a" * 32, lobby_timeout=5).run()

    def join():
        out["join"] = JoinSession(box.transport, name="Bob", passkey=Passkey(PASS), room_code=ROOM,
                                  install_id="b" * 32, ask_name=lambda r: None,
                                  confirm_terms=lambda h, t: True, join_timeout=5).run()

    ht = threading.Thread(target=host, daemon=True); ht.start()
    time.sleep(0.05)
    jt = threading.Thread(target=join, daemon=True); jt.start()
    ht.join(10); jt.join(10)
    return out["host"], out["join"], box


def send(conn, message):
    conn.transport.send(proto.encode(message))


def recv(conn, timeout=2.0):
    raw = conn.transport.recv(timeout)
    return None if raw is None else proto.decode(raw)
