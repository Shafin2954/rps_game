"""The real thing: WormholeTransport against a real (local) mailbox server.

Skipped automatically if the optional dev dependencies aren't installed. No test
here ever contacts the public mailbox."""
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("wormhole")
pytest.importorskip("wormhole_mailbox_server")

from rps_game.net import protocol as proto                      # noqa: E402
from rps_game.net.errors import (Cancelled, Declined, RoomBurned, ServerUnreachable,  # noqa: E402
                                 WrongPasskey)
from rps_game.net.session import Connection, GameTerms, HostSession, JoinSession  # noqa: E402
from rps_game.net.transport import WormholeTransport            # noqa: E402
from rps_game.passkey import Passkey                            # noqa: E402

ROOM = "482193756"
PASS = "hunter22"
TIMEOUTS = dict(step_timeout=20, human_timeout=20)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def mailbox(tmp_path_factory):
    twist = Path(sys.executable).with_name("twist")
    if not twist.exists():
        pytest.skip("`twist` not found next to this Python")
    port = _free_port()
    db = tmp_path_factory.mktemp("mailbox") / "relay.sqlite"
    proc = subprocess.Popen(
        [str(twist), "wormhole-mailbox", "--port", f"tcp:{port}:interface=127.0.0.1",
         "--channel-db", str(db)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            break
        except OSError:
            time.sleep(0.2)
    else:
        proc.kill()
        pytest.skip("local mailbox server did not start")
    yield f"ws://127.0.0.1:{port}/v1"
    proc.terminate()
    try:
        proc.wait(5)
    except subprocess.TimeoutExpired:
        proc.kill()


def room_for(test_name: str) -> str:
    """A different numeric room per test so tests can't see each other's leftovers."""
    return str(100_000_000 + abs(hash(test_name)) % 800_000_000)


def run(session):
    out = {}

    def target():
        try:
            out["result"] = session.run()
        except BaseException as exc:                      # noqa: BLE001
            out["result"] = exc

    t = threading.Thread(target=target, daemon=True)
    t.start()
    return t, out


def host(url, room, **over):
    kw = dict(factory=lambda: WormholeTransport(url), name="Sohan", passkey=Passkey(PASS),
              room_code=room, terms=GameTerms(first_to=3), install_id="a" * 32,
              lobby_timeout=40, **TIMEOUTS)
    kw.update(over)
    return HostSession(**kw)


def joiner(url, room, **over):
    kw = dict(factory=lambda: WormholeTransport(url), name="Bob", passkey=Passkey(PASS),
              room_code=room, install_id="b" * 32, ask_name=lambda r: None,
              confirm_terms=lambda h, t: True, join_timeout=40, **TIMEOUTS)
    kw.update(over)
    return JoinSession(**kw)


def test_a_real_handshake_over_a_real_mailbox(mailbox):
    room = room_for("happy")
    ht, hres = run(host(mailbox, room))
    jt, jres = run(joiner(mailbox, room))
    ht.join(40); jt.join(40)
    h, j = hres["result"], jres["result"]
    assert isinstance(h, Connection) and isinstance(j, Connection), (h, j)
    assert (h.opponent_name, j.opponent_name) == ("Bob", "Sohan")
    assert h.terms == j.terms == GameTerms(first_to=3)
    h.close(); j.close()


def test_non_ascii_names_survive_real_encryption_and_transport(mailbox):
    room = room_for("unicode")
    ht, hres = run(host(mailbox, room, name="সোহান"))
    jt, jres = run(joiner(mailbox, room, name="李雷"))
    ht.join(40); jt.join(40)
    h, j = hres["result"], jres["result"]
    assert (h.opponent_name, j.opponent_name) == ("李雷", "সোহান")
    h.close(); j.close()


def test_the_pair_can_keep_talking_after_the_handshake(mailbox):
    room = room_for("talk")
    ht, hres = run(host(mailbox, room))
    jt, jres = run(joiner(mailbox, room))
    ht.join(40); jt.join(40)
    h, j = hres["result"], jres["result"]
    h.channel.send(proto.Ping(41))
    assert j.channel.recv(10) == proto.Ping(41)
    j.channel.send(proto.Pong(41))
    assert h.channel.recv(10) == proto.Pong(41)
    h.close(); j.close()


def test_a_wrong_passkey_fails_then_the_right_one_still_gets_in(mailbox):
    room = room_for("retry")
    events = []
    ht, hres = run(host(mailbox, room, on_status=lambda kind, **i: events.append(kind)))
    time.sleep(1.0)
    bt, bres = run(joiner(mailbox, room, passkey=Passkey("wrong-pass")))
    bt.join(40)
    assert isinstance(bres["result"], WrongPasskey)
    gt, gres = run(joiner(mailbox, room))                  # the host is re-listening
    ht.join(40); gt.join(40)
    assert isinstance(hres["result"], Connection), hres["result"]
    assert isinstance(gres["result"], Connection), gres["result"]
    assert "wrong_passkey" in events
    hres["result"].close(); gres["result"].close()


def test_three_wrong_passkeys_burn_a_real_room(mailbox):
    room = room_for("burn")
    ht, hres = run(host(mailbox, room, max_wrong=2))
    time.sleep(1.0)
    for i in range(2):
        bt, bres = run(joiner(mailbox, room, passkey=Passkey(f"guess-{i}-zzz")))
        bt.join(40)
        assert isinstance(bres["result"], WrongPasskey)
        time.sleep(0.5)
    ht.join(40)
    assert isinstance(hres["result"], RoomBurned)


def test_an_intruder_cannot_disturb_an_established_pair(mailbox):
    room = room_for("intruder")
    ht, hres = run(host(mailbox, room))
    jt, jres = run(joiner(mailbox, room))
    ht.join(40); jt.join(40)
    h, j = hres["result"], jres["result"]
    intruder = WormholeTransport(mailbox)
    intruder.open(f"{room}-guess-guess")
    assert intruder.recv(3) is None                        # told nothing
    h.channel.send(proto.Ping(1))
    assert j.channel.recv(10) == proto.Ping(1)
    intruder.close(); h.close(); j.close()


def test_the_joiner_cancelling_at_the_name_prompt_leaves_cleanly(mailbox):
    room = room_for("cancelname")
    ht, hres = run(host(mailbox, room))
    jt, jres = run(joiner(mailbox, room, name="sohan", ask_name=lambda r: None))
    ht.join(40); jt.join(40)
    assert isinstance(jres["result"], Cancelled)
    assert isinstance(hres["result"], Exception)           # told the joiner left


def test_declining_over_the_real_transport(mailbox):
    room = room_for("decline")
    ht, hres = run(host(mailbox, room))
    jt, jres = run(joiner(mailbox, room, confirm_terms=lambda h, t: False))
    ht.join(40); jt.join(40)
    assert isinstance(hres["result"], Declined) and isinstance(jres["result"], Declined)


def test_an_unreachable_server_gives_a_friendly_error():
    dead = f"ws://127.0.0.1:{_free_port()}/v1"            # nothing is listening there
    h = host(dead, room_for("dead"), lobby_timeout=30)
    t, out = run(h)
    t.join(60)
    assert isinstance(out["result"], ServerUnreachable), out["result"]
    assert "internet connection" in str(out["result"])
