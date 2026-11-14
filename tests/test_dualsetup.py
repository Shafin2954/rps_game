"""The Dual Player set-up flow, driven the way a player drives it: keys in, setup out."""
import getpass
import io

import pytest
from rich.console import Console

from rps_game import cli, dualsetup, settings, terminal
from rps_game.dualsetup import DualSetup
from rps_game.names import MAX_NAME_CELLS
from rps_game.players import Side
from rps_game.ui import GameUI

K = terminal
ENTER, ESC, UP, DOWN, CLEAR = K.KEY_ENTER, K.KEY_ESC, K.KEY_UP, K.KEY_DOWN, "\x15"


def typed(text):
    return list(text)                      # one key per code point, like a real keyboard


def _keys(monkeypatch, keys):
    it = iter(keys)
    monkeypatch.setattr(terminal, "is_interactive", lambda: True)
    monkeypatch.setattr(terminal, "flush_input", lambda: None)
    monkeypatch.setattr(terminal, "read_key", lambda: next(it))


def _ui():
    out = io.StringIO()
    return GameUI(animate=False, console=Console(file=out, width=100, height=30,
                                                 force_terminal=False)), out


def _host_keys(name="Sohan", passkey="hunter22", side=(), length=(ENTER, *typed("5"), ENTER)):
    return [ENTER,                                   # Create game
            *typed(name), ENTER,                      # name
            ENTER, *typed(passkey), ENTER, *typed(passkey), ENTER,   # type my own, twice
            *side, ENTER,                             # side (default Left unless moved)
            *length]                                  # game length


# ------------------------------------------------------------------ host flow

def test_host_flow_produces_a_complete_setup(monkeypatch):
    ui, _ = _ui()
    _keys(monkeypatch, _host_keys(side=(DOWN,)))      # choose the Right side
    setup = dualsetup.setup_dual(ui)
    assert isinstance(setup, DualSetup) and setup.role == "host"
    assert (setup.name, setup.side, setup.rounds, setup.first_to) == ("Sohan", Side.RIGHT, 5, None)
    assert setup.passkey.matches("hunter22")
    assert len(setup.room_code) == 9 and setup.room_code[0] != "0"


def test_host_can_choose_first_to_n(monkeypatch):
    ui, _ = _ui()
    _keys(monkeypatch, _host_keys(length=(DOWN, ENTER, *typed("3"), ENTER)))
    setup = dualsetup.setup_dual(ui)
    assert (setup.rounds, setup.first_to) == (None, 3)


def test_host_can_generate_a_passkey(monkeypatch):
    ui, out = _ui()
    _keys(monkeypatch, [ENTER, *typed("Sohan"), ENTER,
                        DOWN, ENTER,                 # Generate one for me
                        ENTER,                       # Use this passkey
                        ENTER, ENTER, *typed("4"), ENTER])
    setup = dualsetup.setup_dual(ui)
    phrase = setup.passkey.reveal()
    assert phrase.count("-") == 2 and all(p.isalpha() and p.islower() for p in phrase.split("-"))
    assert f"Your passkey: {phrase}" in out.getvalue()        # shown to the host on purpose


def test_generate_another_really_offers_a_new_phrase(monkeypatch):
    import re

    ui, out = _ui()
    _keys(monkeypatch, [ENTER, *typed("Sohan"), ENTER, DOWN, ENTER,
                        DOWN, ENTER,                 # Generate another
                        ENTER,                       # Use the second one
                        ENTER, ENTER, *typed("4"), ENTER])
    setup = dualsetup.setup_dual(ui)
    shown = re.findall(r"Your passkey: ([a-z]+-[a-z]+-[a-z]+)", out.getvalue())
    assert len(shown) == 2 and shown[0] != shown[1]
    assert setup.passkey.reveal() == shown[1]        # the one actually chosen was the second


def test_passkey_confirmation_must_match(monkeypatch):
    ui, out = _ui()
    _keys(monkeypatch, [*typed("hunter22"), ENTER,           # first entry
                        *typed("hunter23"), ENTER,           # does not match
                        ESC])                                # leave while the warning is up
    # _type_own_passkey re-asks the first entry after Esc; run it to the point we assert on.
    with pytest.raises(StopIteration):
        dualsetup._type_own_passkey(ui, "crumbs")
    assert "Passkeys don't match" in out.getvalue()


def test_matching_confirmation_after_a_retry_succeeds(monkeypatch):
    ui, _ = _ui()
    _keys(monkeypatch, [*typed("hunter22"), ENTER, *typed("nope-nope"), ENTER, ESC,
                        *typed("hunter22"), ENTER, *typed("hunter22"), ENTER])
    assert dualsetup._type_own_passkey(ui, "crumbs") == "hunter22"


# ------------------------------------------------------------------ names

def test_reserved_name_is_refused_then_corrected(monkeypatch):
    ui, out = _ui()
    _keys(monkeypatch, [ENTER, *typed("you"), ENTER, CLEAR, *typed("Bob"), ENTER,
                        ENTER, *typed("hunter22"), ENTER, *typed("hunter22"), ENTER,
                        ENTER, ENTER, *typed("5"), ENTER])
    assert dualsetup.setup_dual(ui).name == "Bob"


def test_bengali_name_survives_the_whole_flow(monkeypatch):
    ui, _ = _ui()
    _keys(monkeypatch, _host_keys(name="সোহান"))
    assert dualsetup.setup_dual(ui).name == "সোহান"


def test_typing_past_the_width_limit_is_ignored(monkeypatch):
    ui, _ = _ui()
    _keys(monkeypatch, _host_keys(name="A" * 30))
    assert dualsetup.setup_dual(ui).name == "A" * MAX_NAME_CELLS


def test_names_are_tidied_in_the_result(monkeypatch):
    ui, _ = _ui()
    _keys(monkeypatch, _host_keys(name="  Anna   Maria "))
    assert dualsetup.setup_dual(ui).name == "Anna Maria"


# ------------------------------------------------------------------ navigation

def test_esc_steps_back_and_prefills_the_name(monkeypatch):
    ui, _ = _ui()
    _keys(monkeypatch, [ENTER, *typed("Al"), ENTER,          # name
                        ESC,                                  # back out of the passkey menu
                        ENTER,                                # name screen is prefilled: accept
                        ENTER, *typed("hunter22"), ENTER, *typed("hunter22"), ENTER,
                        ENTER, ENTER, *typed("2"), ENTER])
    assert dualsetup.setup_dual(ui).name == "Al"


def test_esc_from_the_first_screen_returns_to_the_role_menu_then_exits(monkeypatch):
    ui, out = _ui()
    _keys(monkeypatch, [ENTER, ESC, ESC])                    # Create, back, back out of Dual Player
    assert dualsetup.setup_dual(ui) is None
    assert "Create game" in out.getvalue()


def test_number_screen_esc_returns_to_the_length_menu(monkeypatch):
    ui, _ = _ui()
    _keys(monkeypatch, _host_keys(length=(ENTER, ESC,            # rounds ... Esc on the number
                                          DOWN, ENTER, *typed("2"), ENTER)))   # then First to 2
    assert dualsetup.setup_dual(ui).first_to == 2


# ------------------------------------------------------------------ join flow

def test_join_flow(monkeypatch):
    ui, _ = _ui()
    _keys(monkeypatch, [DOWN, ENTER,                         # Join game
                        *typed("482-193-756"), ENTER,
                        *typed("Bob"), ENTER,
                        *typed("lamp-river-ocean"), ENTER,
                        ENTER])                              # side: Left
    setup = dualsetup.setup_dual(ui)
    assert (setup.role, setup.name, setup.room_code, setup.side) == ("join", "Bob", "482193756", Side.LEFT)
    assert (setup.rounds, setup.first_to) == (None, None)    # the host decides; learned on connecting
    assert setup.passkey.matches("lamp-river-ocean")


def test_join_refuses_a_bad_room_code_until_corrected(monkeypatch):
    ui, _ = _ui()
    _keys(monkeypatch, [DOWN, ENTER, *typed("12-34"), ENTER, CLEAR, *typed("482193756"), ENTER,
                        *typed("Bob"), ENTER, *typed("hunter22"), ENTER, ENTER])
    assert dualsetup.setup_dual(ui).room_code == "482193756"


# ------------------------------------------------------------------ sides

def test_chosen_side_is_remembered_and_preselected(monkeypatch):
    ui, _ = _ui()
    _keys(monkeypatch, _host_keys(side=(DOWN,)))
    dualsetup.setup_dual(ui)
    assert settings.load().preferred_side == "right"
    _keys(monkeypatch, _host_keys(side=()))                  # just press Enter on the side screen
    assert dualsetup.setup_dual(ui).side is Side.RIGHT


# ------------------------------------------------------------------ secrecy

SECRET = "s3cr3t-Pass9"


def test_a_typed_passkey_never_appears_on_screen_or_in_the_setup_repr(monkeypatch):
    ui, out = _ui()
    _keys(monkeypatch, _host_keys(passkey=SECRET))
    setup = dualsetup.setup_dual(ui)
    assert setup.passkey.matches(SECRET)
    assert SECRET not in out.getvalue()
    assert SECRET not in repr(setup) and SECRET not in str(setup)
    assert not any(SECRET in line for line in setup.summary_lines())
    assert "\u2022" in out.getvalue() or "*" in out.getvalue()       # it was masked, not blank


def test_ascii_mode_masks_with_asterisks(monkeypatch):
    out = io.StringIO()
    ui = GameUI(animate=False, ascii_only=True,
                console=Console(file=out, width=100, height=30, force_terminal=False))
    _keys(monkeypatch, [*typed("hunter22"), ESC])
    assert ui.ask_text("Passkey", mask=True) is None
    assert "********" in out.getvalue() and "hunter22" not in out.getvalue()


# ------------------------------------------------------------------ summary text

def test_summary_for_a_host_has_room_code_but_no_passkey():
    setup = DualSetup("host", "Sohan", dualsetup.Passkey("hunter22"), Side.LEFT, "482193756",
                      first_to=3)
    text = "\n".join(setup.summary_lines())
    assert "482-193-756" in text and "first to 3 wins" in text and "hunter22" not in text


def test_summary_for_a_joiner():
    setup = DualSetup("join", "Bob", dualsetup.Passkey("hunter22"), Side.RIGHT, "482193756")
    text = "\n".join(setup.summary_lines())
    assert "Joining room: 482-193-756" in text and "right side" in text


# ------------------------------------------------------------------ plain (accessible) mode

def _plain_inputs(monkeypatch, typed_lines, hidden):
    lines, secrets_ = iter(typed_lines), iter(hidden)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(lines))
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": next(secrets_))


def test_plain_host_flow(monkeypatch):
    ui = GameUI(plain=True)
    _plain_inputs(monkeypatch,
                  ["1",              # Create game
                   "Sohan",          # name
                   "1",              # type my own passkey
                   "2",              # Right
                   "2", "3"],        # First to N, N = 3
                  hidden=["hunter22", "hunter22"])
    setup = dualsetup.setup_dual(ui)
    assert (setup.name, setup.side, setup.first_to) == ("Sohan", Side.RIGHT, 3)
    assert setup.passkey.matches("hunter22")


def test_plain_join_flow_and_error_messages(monkeypatch, capsys):
    ui = GameUI(plain=True)
    _plain_inputs(monkeypatch,
                  ["2", "12345", "482-193-756", "you", "Bob", "1"],
                  hidden=["short", "hunter22"])
    setup = dualsetup.setup_dual(ui)
    out = capsys.readouterr().out
    assert setup.room_code == "482193756" and setup.name == "Bob"
    assert "9 digits" in out and "reserved" in out and "at least 6" in out


def test_plain_back_command(monkeypatch):
    ui = GameUI(plain=True)
    _plain_inputs(monkeypatch, ["1", "/back", "q"], hidden=[])     # Create, /back at name, q at menu
    assert dualsetup.setup_dual(ui) is None


def test_plain_mode_never_echoes_the_passkey_through_input(monkeypatch):
    """Hidden input must go through getpass, never the echoing input()."""
    ui = GameUI(plain=True)
    used = []
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": used.append("getpass") or "hunter22")
    monkeypatch.setattr("builtins.input", lambda prompt="": used.append("input") or "x")
    assert ui.ask_text("Passkey", mask=True) == "hunter22"
    assert used == ["getpass"]


# ------------------------------------------------------------------ through the real menu / CLI

def test_full_cli_menu_path_hands_the_setup_to_the_connection_code(monkeypatch, capsys):
    # Start Game > Dual Player > Create game > name > passkey: type my own > side: Left
    # > length: rounds > 5 rounds > (connection attempt, stubbed) > back at the menu: Exit
    seen = []
    monkeypatch.setattr(cli, "connect_dual", lambda ui, setup, mailbox: seen.append((setup, mailbox)))
    inputs = iter(["1", "2", "1", "Sohan", "1", "1", "1", "5", "3"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "hunter22")
    assert cli.main(["--plain"]) == 0
    (setup, mailbox), = seen
    assert (setup.role, setup.name, setup.rounds) == ("host", "Sohan", 5)
    assert setup.passkey.matches("hunter22")
    assert mailbox.startswith("ws://")                       # the default mailbox
    assert "hunter22" not in capsys.readouterr().out
