import pytest

from rps_game.net.errors import TransportClosed, WrongPasskey
from rps_game.net.transport import MemoryMailbox


def pair(box, code="123456789-hunter22", other=None):
    a, b = box.transport(), box.transport()
    a.open(code)
    b.open(other or code)
    return a, b


def test_messages_flow_both_ways():
    a, b = pair(MemoryMailbox())
    a.send(b"hi")
    b.send(b"yo")
    assert b.recv(1) == b"hi" and a.recv(1) == b"yo"


def test_messages_sent_before_the_peer_arrives_are_delivered_after():
    box = MemoryMailbox()
    a = box.transport(); a.open("123456789-hunter22")
    a.send(b"one"); a.send(b"two")
    b = box.transport(); b.open("123456789-hunter22")
    assert (b.recv(1), b.recv(1)) == (b"one", b"two")


def test_recv_times_out_with_none():
    a, _ = pair(MemoryMailbox())
    assert a.recv(0.05) is None


def test_a_wrong_passkey_fails_both_ends_and_frees_the_room():
    box = MemoryMailbox()
    a, b = pair(box, other="123456789-wrongpass")
    for end in (a, b):
        with pytest.raises(WrongPasskey):
            end.recv(1)
    c, d = pair(box)                                  # the room can be used again
    c.send(b"x")
    assert d.recv(1) == b"x"


def test_a_third_party_in_a_full_room_is_ignored_and_harmless():
    box = MemoryMailbox()
    a, b = pair(box)
    intruder = box.transport(); intruder.open("123456789-guess-guess")
    intruder.send(b"let me in")
    assert intruder.recv(0.05) is None and a.recv(0.05) is None and b.recv(0.05) is None
    a.send(b"still fine")
    assert b.recv(1) == b"still fine"


def test_closing_tells_the_peer():
    a, b = pair(MemoryMailbox())
    a.close()
    with pytest.raises(TransportClosed):
        b.recv(1)


def test_sending_after_close_fails():
    a, _ = pair(MemoryMailbox())
    a.close()
    with pytest.raises(TransportClosed):
        a.send(b"x")


def test_tamper_hook_can_rewrite_and_drop():
    box = MemoryMailbox()
    box.tamper = lambda role, data: None if data == b"drop" else data.upper()
    a, b = pair(box)
    a.send(b"drop"); a.send(b"keep")
    assert b.recv(1) == b"KEEP" and b.recv(0.05) is None


def test_attempts_are_recorded_in_order():
    box = MemoryMailbox()
    pair(box, other="123456789-nope-nope")
    assert box.attempts == [("123456789", "hunter22"), ("123456789", "nope-nope")]
