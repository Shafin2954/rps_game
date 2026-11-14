"""The handshake, end to end, over the in-memory mailbox: both sides run for real, in
threads, and the tests inject the awkward and hostile cases."""
import threading
import time

import pytest

from rps_game.net import protocol as proto
from rps_game.net.errors import (Cancelled, Declined, Incompatible, PeerLeft, ProtocolError,
                                 RoomBurned, Timeout, TransportClosed, WrongPasskey)
from rps_game.net.session import Channel, Connection, GameTerms, HostSession, JoinSession
from rps_game.net.transport import MemoryMailbox
from rps_game.passkey import Passkey

ROOM = "482193756"
PASS = "hunter22"
HOST_ID, JOIN_ID = "a" * 32, "b" * 32
FAST = dict(lobby_timeout=3, step_timeout=2, human_timeout=2)
FAST_JOIN = dict(join_timeout=3, step_timeout=2, human_timeout=2)


def host_kwargs(box, **over):
    base = dict(factory=box.transport, name="Sohan", passkey=Passkey(PASS), room_code=ROOM,
                terms=GameTerms(first_to=3), install_id=HOST_ID, **FAST)
    base.update(over)
    return base


def join_kwargs(box, **over):
    base = dict(factory=box.transport, name="Bob", passkey=Passkey(PASS), room_code=ROOM,
                install_id=JOIN_ID, ask_name=lambda reason: None,
                confirm_terms=lambda host, terms: True, **FAST_JOIN)
    base.update(over)
    return base


def in_thread(session):
    box = {}

    def target():
        try:
            box["result"] = session.run()
        except BaseException as exc:                      # noqa: BLE001 - we report whatever happened
            box["result"] = exc

    t = threading.Thread(target=target, daemon=True)
    t.start()
    return t, box


def run_pair(box, host_over=None, join_over=None, join_delay=0.1):
    """Start the host, then the joiner; return (host_result, join_result)."""
    host = HostSession(**host_kwargs(box, **(host_over or {})))
    ht, hres = in_thread(host)
    time.sleep(join_delay)
    join = JoinSession(**join_kwargs(box, **(join_over or {})))
    jt, jres = in_thread(join)
    ht.join(15); jt.join(15)
    assert not ht.is_alive() and not jt.is_alive(), "a side hung"
    return hres["result"], jres["result"]


# ------------------------------------------------------------------ happy path

def test_happy_path():
    h, j = run_pair(MemoryMailbox())
    assert isinstance(h, Connection) and isinstance(j, Connection)
    assert (h.role, h.my_name, h.opponent_name, h.opponent_id) == ("host", "Sohan", "Bob", JOIN_ID)
    assert (j.role, j.my_name, j.opponent_name, j.opponent_id) == ("join", "Bob", "Sohan", HOST_ID)
    assert h.terms == j.terms == GameTerms(rounds=None, first_to=3)


def test_the_joiner_learns_fixed_round_terms():
    h, j = run_pair(MemoryMailbox(), host_over=dict(terms=GameTerms(rounds=7)))
    assert j.terms == GameTerms(rounds=7, first_to=None)


def test_closing_says_goodbye_to_the_other_side():
    h, j = run_pair(MemoryMailbox())
    h.close()
    with pytest.raises(PeerLeft):
        j.channel.recv(2)


def test_joiner_may_arrive_before_the_host():
    box = MemoryMailbox()
    join = JoinSession(**join_kwargs(box))
    jt, jres = in_thread(join)
    time.sleep(0.2)
    ht, hres = in_thread(HostSession(**host_kwargs(box)))
    ht.join(10); jt.join(10)
    assert isinstance(hres["result"], Connection) and isinstance(jres["result"], Connection)


def test_status_callbacks_report_progress():
    events = []
    run_pair(MemoryMailbox(), host_over=dict(on_status=lambda kind, **i: events.append(kind)))
    assert events[0] == "waiting" and events[-1] == "starting"
    assert "negotiating" in events and "awaiting_decision" in events


# ------------------------------------------------------------------ names

def test_a_clashing_name_makes_the_joiner_choose_again():
    asked = []

    def ask_name(reason):
        asked.append(reason)
        return "Robert"

    h, j = run_pair(MemoryMailbox(), join_over=dict(name="sohan", ask_name=ask_name))
    assert asked == ["taken"]
    assert h.opponent_name == "Robert" and j.my_name == "Robert"


@pytest.mark.parametrize("clash", ["SOHAN", " sohan ", "ＳＯＨＡＮ"])
def test_name_clashes_ignore_case_spacing_and_width(clash):
    from rps_game.names import check_name
    name = check_name(clash).name                         # the joiner's UI would tidy it first
    asked = []
    run_pair(MemoryMailbox(), join_over=dict(name=name, ask_name=lambda r: asked.append(r) or "Bob"))
    assert asked == ["taken"]


def test_giving_up_on_the_name_cancels_cleanly_on_both_sides():
    h, j = run_pair(MemoryMailbox(), join_over=dict(name="Sohan", ask_name=lambda r: None))
    assert isinstance(j, Cancelled) and isinstance(h, PeerLeft)


def test_endlessly_clashing_names_end_the_handshake():
    h, j = run_pair(MemoryMailbox(), join_over=dict(name="Sohan", ask_name=lambda r: "SOHAN"))
    assert isinstance(h, ProtocolError) and isinstance(j, PeerLeft)


# ------------------------------------------------------------------ the host's settings

def test_declining_the_settings_ends_the_game_for_both():
    h, j = run_pair(MemoryMailbox(), join_over=dict(confirm_terms=lambda host, terms: False))
    assert isinstance(j, Declined) and isinstance(h, Declined)
    assert "Bob" in str(h)


def test_the_joiner_is_shown_who_invited_them_and_on_what_terms():
    seen = []
    run_pair(MemoryMailbox(), join_over=dict(confirm_terms=lambda h, t: seen.append((h, t)) or True))
    assert seen == [("Sohan", GameTerms(first_to=3))]


# ------------------------------------------------------------------ passkeys

def test_a_wrong_passkey_fails_the_joiner_but_the_host_keeps_waiting():
    box = MemoryMailbox()
    events = []
    host = HostSession(**host_kwargs(box, on_status=lambda kind, **i: events.append((kind, i))))
    ht, hres = in_thread(host)
    time.sleep(0.1)
    bad = JoinSession(**join_kwargs(box, passkey=Passkey("wrong-pass")))
    bt, bres = in_thread(bad)
    bt.join(5)
    assert isinstance(bres["result"], WrongPasskey)
    time.sleep(0.2)
    good = JoinSession(**join_kwargs(box))
    gt, gres = in_thread(good)
    ht.join(10); gt.join(10)
    assert isinstance(hres["result"], Connection) and isinstance(gres["result"], Connection)
    assert ("wrong_passkey", {"count": 1, "limit": 3}) in events


def test_three_wrong_passkeys_burn_the_room():
    box = MemoryMailbox()
    ht, hres = in_thread(HostSession(**host_kwargs(box)))
    time.sleep(0.1)
    for i in range(3):
        bt, bres = in_thread(JoinSession(**join_kwargs(box, passkey=Passkey(f"guess-{i}-xx"))))
        bt.join(5)
        assert isinstance(bres["result"], WrongPasskey)
        time.sleep(0.15)
    ht.join(10)
    assert isinstance(hres["result"], RoomBurned)
    assert "closed for safety" in str(hres["result"])


def test_a_burned_room_cannot_be_joined_even_with_the_right_passkey():
    box = MemoryMailbox()
    ht, hres = in_thread(HostSession(**host_kwargs(box, max_wrong=1)))
    time.sleep(0.1)
    bt, _ = in_thread(JoinSession(**join_kwargs(box, passkey=Passkey("guess-1-xx"))))
    bt.join(5); ht.join(5)
    assert isinstance(hres["result"], RoomBurned)
    jt, jres = in_thread(JoinSession(**join_kwargs(box, join_timeout=0.6)))
    jt.join(5)
    assert isinstance(jres["result"], Timeout)             # nobody is listening any more


def test_the_passkey_never_appears_in_any_message_on_the_wire():
    box = MemoryMailbox()
    wire = []
    box.tamper = lambda role, data: wire.append(data) or data
    run_pair(box)
    assert wire and not any(PASS.encode() in frame for frame in wire)
    assert box.attempts == [(ROOM, PASS), (ROOM, PASS)]     # only the room key carries it


# ------------------------------------------------------------------ waiting, timeouts, cancelling

def test_the_host_gives_up_when_nobody_joins():
    box = MemoryMailbox()
    res = HostSession(**host_kwargs(box, lobby_timeout=0.4))
    t, out = in_thread(res)
    t.join(5)
    assert isinstance(out["result"], Timeout)


def test_a_joiner_gives_up_when_nobody_answers():
    box = MemoryMailbox()
    t, out = in_thread(JoinSession(**join_kwargs(box, join_timeout=0.4)))
    t.join(5)
    assert isinstance(out["result"], Timeout)
    assert "host" in str(out["result"])


def test_cancelling_while_waiting_stops_the_host():
    box = MemoryMailbox()
    stop = threading.Event()
    t, out = in_thread(HostSession(**host_kwargs(box, tick=lambda: not stop.is_set())))
    time.sleep(0.3)
    stop.set()
    t.join(5)
    assert isinstance(out["result"], Cancelled)


# ------------------------------------------------------------------ hostile or broken peers

def test_versions_that_differ_refuse_politely_on_both_sides():
    box = MemoryMailbox()
    box.tamper = lambda role, data: data.replace(b'"v":1', b'"v":2')
    h, j = run_pair(box)
    assert isinstance(h, Incompatible) and isinstance(j, Incompatible)
    assert "rps --update" in str(h)


def test_garbage_from_the_peer_aborts_the_handshake():
    box = MemoryMailbox()
    box.tamper = lambda role, data: b"definitely not json" if b'"hello"' in data and role != "first" else data
    h, j = run_pair(box)
    assert isinstance(h, ProtocolError)
    assert isinstance(j, TransportClosed)                   # the host hung up on us


def test_an_oversized_message_is_refused():
    box = MemoryMailbox()
    box.tamper = lambda role, data: b"x" * 10_000 if role != "first" else data
    h, j = run_pair(box)
    assert isinstance(h, ProtocolError)


def _raw_peer(box):
    t = box.transport()
    t.open(f"{ROOM}-{PASS}")
    return t


@pytest.mark.parametrize("first", [proto.Start(), proto.Accept(), proto.Settings(3, None),
                                   proto.Ping(1)])
def test_the_host_insists_on_hello_first(first):
    box = MemoryMailbox()
    ht, hres = in_thread(HostSession(**host_kwargs(box)))
    time.sleep(0.1)
    peer = _raw_peer(box)
    peer.send(proto.encode(first))
    ht.join(5)
    assert isinstance(hres["result"], ProtocolError)


def test_the_host_rejects_unexpected_replies_to_its_settings():
    box = MemoryMailbox()
    ht, hres = in_thread(HostSession(**host_kwargs(box)))
    time.sleep(0.1)
    peer = _raw_peer(box)
    peer.send(proto.encode(proto.Hello(1, "Bob", JOIN_ID, "3.4.0")))
    time.sleep(0.2)
    peer.send(proto.encode(proto.Ping(1)))                  # neither accept nor decline
    ht.join(5)
    assert isinstance(hres["result"], ProtocolError)


def test_a_malicious_host_cannot_claim_the_joiners_name():
    box = MemoryMailbox()
    jt, jres = in_thread(JoinSession(**join_kwargs(box)))
    host = _raw_peer(box)
    time.sleep(0.2)
    host.send(proto.encode(proto.Hello(1, "bob", HOST_ID, "3.4.0")))   # same name, different case
    jt.join(5)
    assert isinstance(jres["result"], ProtocolError)


def test_a_host_that_skips_the_settings_is_refused():
    box = MemoryMailbox()
    jt, jres = in_thread(JoinSession(**join_kwargs(box)))
    host = _raw_peer(box)
    time.sleep(0.2)
    host.send(proto.encode(proto.Hello(1, "Sohan", HOST_ID, "3.4.0")))
    host.send(proto.encode(proto.Start()))
    jt.join(5)
    assert isinstance(jres["result"], ProtocolError)


def test_a_host_that_never_starts_leaves_the_joiner_timing_out():
    box = MemoryMailbox()
    jt, jres = in_thread(JoinSession(**join_kwargs(box, step_timeout=0.5)))
    host = _raw_peer(box)
    time.sleep(0.2)
    host.send(proto.encode(proto.Hello(1, "Sohan", HOST_ID, "3.4.0")))
    host.send(proto.encode(proto.Settings(None, 3)))
    jt.join(5)
    assert isinstance(jres["result"], Timeout) and "start" in str(jres["result"])


def test_a_third_player_cannot_disturb_a_finished_handshake():
    box = MemoryMailbox()
    h, j = run_pair(box)
    intruder = box.transport(); intruder.open(f"{ROOM}-{PASS}")
    intruder.send(proto.encode(proto.Hello(1, "Mallory", "c" * 32, "3.4.0")))
    h.channel.send(proto.Ping(7))
    assert j.channel.transport.recv(1) is not None          # the real pair still talks


def test_channel_turns_a_bye_into_the_right_error():
    box = MemoryMailbox()
    a, b = box.transport(), box.transport()
    a.open(f"{ROOM}-{PASS}"); b.open(f"{ROOM}-{PASS}")
    chan = Channel(b)
    for reason, expected in (("incompatible", Incompatible), ("declined", Declined),
                             ("quit", PeerLeft), ("cancelled", PeerLeft)):
        a.send(proto.encode(proto.Bye(reason)))
        with pytest.raises(expected):
            chan.recv(1)
