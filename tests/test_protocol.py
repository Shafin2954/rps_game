import json

import pytest

from rps_game.net import protocol as p
from rps_game.net.config import MAX_MESSAGE_BYTES
from rps_game.net.errors import ProtocolError

ID = "a" * 32
GOOD = [
    p.Hello(1, "Sohan", ID, "3.4.0"), p.Hello(1, "সোহান", ID, "3.4.0"),
    p.RejectName("taken"), p.RejectName("invalid"),
    p.Settings(5, None), p.Settings(None, 3),
    p.Accept(), p.Decline(), p.Start(),
    p.Bye("quit"), p.Bye("declined"), p.Bye("cancelled"), p.Bye("incompatible"),
    p.Ping(0), p.Pong(2**31 - 1),
]


@pytest.mark.parametrize("message", GOOD)
def test_every_message_round_trips(message):
    assert p.decode(p.encode(message)) == message


def raw(**fields):
    return json.dumps(fields).encode()


HELLO = dict(t="hello", v=1, name="Bob", id=ID, app="3.4.0")


@pytest.mark.parametrize("data", [
    "a string, not bytes", None, 5, [], b"",
    b"\xff\xfe\x00", b"not json", b"[]", b'"hello"', b"null", b"123",
    raw(),                                              # no type
    raw(t=5), raw(t="nonsense"), raw(t="HELLO"),
    raw(t="accept", extra=1),                           # extra field
    raw(t="bye"),                                       # missing field
    b'{"t":"accept","t":"accept"}',                     # duplicate key
    b"[" * 4000 + b"]" * 4000,                          # nesting bomb
    b"x" * (MAX_MESSAGE_BYTES + 1),                     # too large
])
def test_garbage_is_a_protocol_error_and_nothing_else(data):
    with pytest.raises(ProtocolError):
        p.decode(data)


@pytest.mark.parametrize("change", [
    dict(name=5), dict(name=""), dict(name="you"), dict(name=" Bob"), dict(name="Bo\x1bb"),
    dict(name="\u202eBob"), dict(name="A" * 40), dict(name="-Bob"),
    dict(id="A" * 32), dict(id="a" * 31), dict(id=5),
    dict(app=""), dict(app="x" * 33), dict(app="bad app!"), dict(app=5),
    dict(v=True), dict(v="1"), dict(v=-1), dict(v=1.5),
])
def test_bad_hello_fields_are_rejected(change):
    with pytest.raises(ProtocolError):
        p.decode(raw(**{**HELLO, **change}))


@pytest.mark.parametrize("settings", [
    dict(rounds=None, first_to=None), dict(rounds=3, first_to=3),     # exactly one must be set
    dict(rounds=0, first_to=None), dict(rounds=100, first_to=None), dict(rounds=-1, first_to=None),
    dict(rounds=1.5, first_to=None), dict(rounds="5", first_to=None), dict(rounds=True, first_to=None),
    dict(rounds=None, first_to=0), dict(rounds=None, first_to=100),
])
def test_bad_settings_are_rejected(settings):
    with pytest.raises(ProtocolError):
        p.decode(raw(t="settings", **settings))


@pytest.mark.parametrize("data", [
    raw(t="reject_name", reason="rude free text"), raw(t="reject_name", reason=5),
    raw(t="bye", reason="because"), raw(t="ping", n=-1), raw(t="ping", n=2**31),
    raw(t="pong", n="1"), raw(t="ping", n=True), raw(t="ping", n=1.5),
])
def test_bad_small_messages_are_rejected(data):
    with pytest.raises(ProtocolError):
        p.decode(data)


def test_the_peer_cannot_make_us_display_arbitrary_text():
    """Reasons are codes from a fixed set, so we only ever show our own wording."""
    assert set(p.NAME_REJECT_REASONS) == {"taken", "invalid"}
    assert set(p.BYE_REASONS) == {"quit", "declined", "cancelled", "incompatible"}


def test_encoding_refuses_oversized_messages():
    with pytest.raises(ValueError):
        p.encode(p.Hello(1, "x" * (MAX_MESSAGE_BYTES + 1), ID, "1.0"))


def test_encoding_a_non_message_is_a_programming_error():
    with pytest.raises(TypeError):
        p.encode("hello")


def test_fuzzing_never_leaks_anything_but_protocol_errors():
    hypothesis = pytest.importorskip("hypothesis")
    st = pytest.importorskip("hypothesis.strategies")

    @hypothesis.settings(max_examples=400, deadline=None)
    @hypothesis.given(st.one_of(
        st.binary(max_size=300),
        st.dictionaries(st.text(max_size=6), st.one_of(st.none(), st.booleans(), st.integers(),
                                                       st.text(max_size=12)), max_size=6)
          .map(lambda d: json.dumps(d).encode()),
    ))
    def run(data):
        try:
            result = p.decode(data)
        except ProtocolError:
            return
        assert isinstance(result, tuple(GOOD_TYPES))

    GOOD_TYPES = {type(m) for m in GOOD}
    run()
