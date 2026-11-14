"""connect_dual: the screens and prompts around the handshake, driven like a player drives them."""
import getpass
import io
import threading
import time

from rich.console import Console

from rps_game import terminal
from rps_game.dualsetup import DualSetup
from rps_game.net.config import mailbox_url
from rps_game.net.connect import connect_dual
from rps_game.net.errors import Declined
from rps_game.net.session import Connection, GameTerms, HostSession, JoinSession
from rps_game.net.transport import MemoryMailbox
from rps_game.passkey import Passkey
from rps_game.players import Side
from rps_game.ui import GameUI

ROOM = "482193756"
PASS = "hunter22"
FAST = dict(lobby_timeout=3, step_timeout=2, human_timeout=2)
FAST_JOIN = dict(join_timeout=3, step_timeout=2, human_timeout=2)
ESC = terminal.KEY_ESC


def host_setup(**over):
    base = dict(role="host", name="Sohan", passkey=Passkey(PASS), side=Side.LEFT,
                room_code=ROOM, rounds=None, first_to=3)
    base.update(over)
    return DualSetup(**base)


def join_setup(**over):
    base = dict(role="join", name="Bob", passkey=Passkey(PASS), side=Side.LEFT, room_code=ROOM)
    base.update(over)
    return DualSetup(**base)


def start(session):
    out = {}

    def target():
        try:
            out["result"] = session.run()
        except BaseException as exc:                      # noqa: BLE001
            out["result"] = exc

    t = threading.Thread(target=target, daemon=True)
    t.start()
    return t, out


def raw_joiner(box, **over):
    kw = dict(factory=box.transport, name="Bob", passkey=Passkey(PASS), room_code=ROOM,
              install_id="b" * 32, ask_name=lambda r: None,
              confirm_terms=lambda h, t: True, **FAST_JOIN)
    kw.update(over)
    return JoinSession(**kw)


def raw_host(box, **over):
    kw = dict(factory=box.transport, name="Sohan", passkey=Passkey(PASS), room_code=ROOM,
              terms=GameTerms(first_to=3), install_id="a" * 32, **FAST)
    kw.update(over)
    return HostSession(**kw)


def plain_ui():
    return GameUI(plain=True)


def rich_ui():
    out = io.StringIO()
    ui = GameUI(animate=False, console=Console(file=out, width=100, height=30, force_terminal=False))
    return ui, out


def fake_keys(monkeypatch, keys, *, polled=()):
    """Pretend to be a terminal. ``polled`` keys come back from non-blocking polls
    (the waiting screen's Esc / p check); ``keys`` come back from blocking reads."""
    blocking, polling = iter(keys), iter(polled)

    def read_key(timeout=None):
        if timeout is not None:
            return next(polling, None)
        return next(blocking)

    monkeypatch.setattr(terminal, "is_interactive", lambda: True)
    monkeypatch.setattr(terminal, "flush_input", lambda: None)
    monkeypatch.setattr(terminal, "read_key", read_key)


# ------------------------------------------------------------------------- host

def test_host_waits_shows_the_room_code_and_connects(capsys):
    box = MemoryMailbox()
    ui = plain_ui()
    result = {}

    def host():
        result["c"] = connect_dual(ui, host_setup(), mailbox="x", factory=box.transport,
                                   session_options=FAST)

    ht = threading.Thread(target=host, daemon=True); ht.start()
    time.sleep(0.2)
    jt, jres = start(raw_joiner(box))
    ht.join(10); jt.join(10)
    out = capsys.readouterr().out
    assert isinstance(result["c"], Connection) and result["c"].opponent_name == "Bob"
    assert "Waiting for your friend" in out and "482-193-756" in out
    assert "first to 3 wins" in out
    assert PASS not in out                                  # the plain screen never prints it


def test_host_screen_reports_wrong_passkey_attempts(capsys):
    box = MemoryMailbox()
    ui = plain_ui()
    result = {}
    ht = threading.Thread(target=lambda: result.update(
        c=connect_dual(ui, host_setup(), mailbox="x", factory=box.transport, session_options=FAST)),
        daemon=True)
    ht.start(); time.sleep(0.2)
    bt, bres = start(raw_joiner(box, passkey=Passkey("wrong-pass")))
    bt.join(5); time.sleep(0.3)
    gt, _ = start(raw_joiner(box))
    ht.join(10); gt.join(10)
    assert "wrong passkey (1 of 3)" in capsys.readouterr().out
    assert isinstance(result["c"], Connection)


def test_host_is_told_when_the_room_is_burned(capsys):
    box = MemoryMailbox()
    ui = plain_ui()
    result = {}
    ht = threading.Thread(target=lambda: result.update(
        c=connect_dual(ui, host_setup(), mailbox="x", factory=box.transport, session_options=FAST)),
        daemon=True)
    ht.start(); time.sleep(0.2)
    for i in range(3):
        bt, _ = start(raw_joiner(box, passkey=Passkey(f"guess-{i}-zz")))
        bt.join(5); time.sleep(0.2)
    ht.join(10)
    assert result["c"] is None
    assert "closed for safety" in capsys.readouterr().out


def test_host_is_told_when_nobody_comes(capsys):
    box = MemoryMailbox()
    assert connect_dual(plain_ui(), host_setup(), mailbox="x", factory=box.transport,
                        session_options=dict(FAST, lobby_timeout=0.4)) is None
    assert "Timed out waiting for a friend to join" in capsys.readouterr().out


def test_host_is_told_when_the_joiner_declines(capsys):
    box = MemoryMailbox()
    result = {}
    ht = threading.Thread(target=lambda: result.update(
        c=connect_dual(plain_ui(), host_setup(), mailbox="x", factory=box.transport,
                       session_options=FAST)), daemon=True)
    ht.start(); time.sleep(0.2)
    jt, _ = start(raw_joiner(box, confirm_terms=lambda h, t: False))
    ht.join(10); jt.join(10)
    assert result["c"] is None
    assert "Bob declined the game" in capsys.readouterr().out


def test_esc_cancels_waiting_quietly(monkeypatch):
    ui, out = rich_ui()
    fake_keys(monkeypatch, [], polled=[ESC])
    assert connect_dual(ui, host_setup(), mailbox="x", factory=MemoryMailbox().transport,
                        session_options=FAST) is None
    text = out.getvalue()
    assert "Waiting for your friend" in text and "Couldn't start the game" not in text


def test_the_hosts_passkey_is_masked_until_they_ask_to_see_it(monkeypatch):
    ui, out = rich_ui()
    fake_keys(monkeypatch, [], polled=[None, ESC])            # no peeking
    connect_dual(ui, host_setup(), mailbox="x", factory=MemoryMailbox().transport,
                 session_options=FAST)
    assert PASS not in out.getvalue() and "\u2022" * len(PASS) in out.getvalue()

    ui, out = rich_ui()
    fake_keys(monkeypatch, [], polled=["p", ESC])             # press p to peek
    connect_dual(ui, host_setup(), mailbox="x", factory=MemoryMailbox().transport,
                 session_options=FAST)
    assert f"Passkey: {PASS}" in out.getvalue()


# ------------------------------------------------------------------------ joiner

def _inputs(monkeypatch, typed=(), hidden=()):
    """Script input()/getpass(); returns the list of prompts the player was shown."""
    lines, secrets_, prompts = iter(typed), iter(hidden), []
    monkeypatch.setattr("builtins.input", lambda prompt="": prompts.append(prompt) or next(lines))
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": prompts.append(prompt) or next(secrets_))
    return prompts


def test_joiner_connects_after_accepting_the_terms(monkeypatch, capsys):
    box = MemoryMailbox()
    ht, hres = start(raw_host(box))
    prompts = _inputs(monkeypatch, typed=["y"])
    conn = connect_dual(plain_ui(), join_setup(), mailbox="x", factory=box.transport,
                        session_options=FAST_JOIN)
    ht.join(10)
    assert isinstance(conn, Connection) and conn.opponent_name == "Sohan"
    assert conn.terms == GameTerms(first_to=3)
    assert any("Sohan invites you to play: first to 3 wins" in p for p in prompts)
    assert isinstance(hres["result"], Connection)


def test_declining_the_terms_returns_to_the_menu(monkeypatch):
    box = MemoryMailbox()
    ht, hres = start(raw_host(box))
    _inputs(monkeypatch, typed=["n"])
    assert connect_dual(plain_ui(), join_setup(), mailbox="x", factory=box.transport,
                        session_options=FAST_JOIN) is None
    ht.join(10)
    assert isinstance(hres["result"], Declined)


def test_a_taken_name_prompts_for_another(monkeypatch, capsys):
    box = MemoryMailbox()
    ht, hres = start(raw_host(box))
    _inputs(monkeypatch, typed=["Robert", "y"])               # new name, then accept
    conn = connect_dual(plain_ui(), join_setup(name="sohan"), mailbox="x",
                        factory=box.transport, session_options=FAST_JOIN)
    ht.join(10)
    assert conn.my_name == "Robert" and hres["result"].opponent_name == "Robert"
    assert "already taken by the host" in capsys.readouterr().out


def test_a_wrong_passkey_lets_the_joiner_try_again(monkeypatch, capsys):
    box = MemoryMailbox()
    ht, hres = start(raw_host(box, lobby_timeout=10))
    time.sleep(0.2)
    _inputs(monkeypatch, typed=["y"], hidden=[PASS])          # retry with the right one
    conn = connect_dual(plain_ui(), join_setup(passkey=Passkey("wrong-pass")), mailbox="x",
                        factory=box.transport, session_options=FAST_JOIN)
    ht.join(10)
    assert isinstance(conn, Connection)
    assert "didn't match" in capsys.readouterr().out


def test_three_wrong_passkeys_stop_the_joiner(monkeypatch, capsys):
    box = MemoryMailbox()
    ht, _ = start(raw_host(box, lobby_timeout=10, max_wrong=9))
    time.sleep(0.2)
    _inputs(monkeypatch, hidden=["guess-1-zz", "guess-2-zz"])
    assert connect_dual(plain_ui(), join_setup(passkey=Passkey("guess-0-zz")), mailbox="x",
                        factory=box.transport, session_options=FAST_JOIN) is None
    assert "Too many wrong passkeys" in capsys.readouterr().out


def test_giving_up_at_the_passkey_retry_prompt(monkeypatch):
    box = MemoryMailbox()
    ht, _ = start(raw_host(box, lobby_timeout=10))
    time.sleep(0.2)
    _inputs(monkeypatch, hidden=["/back"])
    assert connect_dual(plain_ui(), join_setup(passkey=Passkey("wrong-pass")), mailbox="x",
                        factory=box.transport, session_options=FAST_JOIN) is None


def test_joiner_is_told_when_nobody_answers(capsys):
    box = MemoryMailbox()
    assert connect_dual(plain_ui(), join_setup(), mailbox="x", factory=box.transport,
                        session_options=dict(FAST_JOIN, join_timeout=0.4)) is None
    out = capsys.readouterr().out
    assert "Timed out waiting for the host to answer" in out and "Check the room code" in out


def test_esc_cancels_a_join_quietly(monkeypatch):
    ui, out = rich_ui()
    fake_keys(monkeypatch, [], polled=[ESC])
    assert connect_dual(ui, join_setup(), mailbox="x", factory=MemoryMailbox().transport,
                        session_options=FAST_JOIN) is None
    assert "Couldn't start the game" not in out.getvalue()


def test_rich_joiner_name_and_accept_prompts_take_over_the_screen_and_return(monkeypatch):
    box = MemoryMailbox()
    ht, hres = start(raw_host(box))
    ui, out = rich_ui()
    enter = terminal.KEY_ENTER
    fake_keys(monkeypatch, [*"Robert", enter,                 # new name
                            "y"])                              # accept
    conn = connect_dual(ui, join_setup(name="SOHAN"), mailbox="x", factory=box.transport,
                        session_options=FAST_JOIN)
    ht.join(10)
    assert isinstance(conn, Connection) and conn.my_name == "Robert"


def test_incompatible_versions_tell_the_player_what_to_do(capsys):
    box = MemoryMailbox()
    box.tamper = lambda role, data: data.replace(b'"v":1', b'"v":9')
    ht, _ = start(raw_host(box))
    assert connect_dual(plain_ui(), join_setup(), mailbox="x", factory=box.transport,
                        session_options=FAST_JOIN) is None
    assert "rps --update" in capsys.readouterr().out


# --------------------------------------------------------------------------- config

def test_mailbox_url_precedence(monkeypatch):
    assert mailbox_url().startswith("ws://relay.magic-wormhole.io")
    monkeypatch.setenv("RPS_MAILBOX", "ws://from-env/v1")
    assert mailbox_url() == "ws://from-env/v1"
    assert mailbox_url("ws://from-flag/v1") == "ws://from-flag/v1"


def test_importing_the_game_does_not_load_the_networking_stack():
    import subprocess
    import sys
    code = ("import rps_game.cli, sys; "
            "bad = [m for m in ('twisted', 'wormhole') if m in sys.modules]; "
            "sys.exit(1 if bad else 0)")
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


# ------------------------------------------------- the host keeps seeing wrong attempts

def test_wrong_attempts_stay_on_the_hosts_screen_after_it_starts_listening_again():
    from rps_game.net.connect import HostScreen

    screen = HostScreen(["Room code:  482-193-756"])
    assert not any("Wrong passkey" in line for line in screen.lines("waiting"))
    screen.lines("wrong_passkey", count=1, limit=3)
    again = screen.lines("waiting")                         # what the host posts a moment later
    assert "Waiting for your friend to join..." in again
    assert any("Wrong passkey attempts so far: 1 of 3" in line for line in again)
    screen.lines("wrong_passkey", count=2, limit=3)
    assert any("2 of 3" in line for line in screen.lines("negotiating"))


def test_the_warning_survives_until_the_end_of_the_real_host_screen(monkeypatch):
    """Rich mode: only the *last* frame is left on screen, and it must still warn."""
    box = MemoryMailbox()
    ui, out = rich_ui()
    fake_keys(monkeypatch, [], polled=[])
    stop = threading.Event()

    def polled(timeout=None):
        if timeout is None:
            raise AssertionError("no blocking reads expected")
        return ESC if stop.is_set() else None

    monkeypatch.setattr(terminal, "read_key", polled)
    result = {}
    ht = threading.Thread(target=lambda: result.update(c=connect_dual(
        ui, host_setup(), mailbox="x", factory=box.transport, session_options=FAST)), daemon=True)
    ht.start()
    time.sleep(0.3)
    bt, _ = start(raw_joiner(box, passkey=Passkey("wrong-pass")))
    bt.join(5)
    time.sleep(0.6)                                          # host is back to plain "waiting"
    stop.set()
    ht.join(5)
    assert result["c"] is None
    assert "Wrong passkey attempts so far: 1 of 3" in out.getvalue()
