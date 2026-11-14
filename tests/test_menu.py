import io

import pytest
from rich.console import Console

from rps_game import cli, menu, stats, terminal
from rps_game.menu import GameConfig
from rps_game.ui import GameUI, Option

K = terminal


def _feed(monkeypatch, items):
    it = iter(items)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(it))


def _keys(monkeypatch, keys):
    """Pretend we're on a real terminal and type `keys`."""
    it = iter(keys)
    monkeypatch.setattr(terminal, "is_interactive", lambda: True)
    monkeypatch.setattr(terminal, "flush_input", lambda: None)
    monkeypatch.setattr(terminal, "read_key", lambda: next(it))


def _rich_ui(width=100, height=30):
    out = io.StringIO()
    console = Console(file=out, width=width, height=height, force_terminal=False)
    return GameUI(animate=False, console=console), out


OPTS = [Option("One", "1"), Option("Two", "2"),
        Option("Three", "3", enabled=False, tag="coming soon")]


# -- rich (arrow-key) menus ---------------------------------------------------

def test_arrow_navigation_selects_and_wraps(monkeypatch):
    ui, _ = _rich_ui()
    _keys(monkeypatch, [K.KEY_DOWN, K.KEY_ENTER])
    assert ui.choose("t", OPTS) == "2"
    _keys(monkeypatch, [K.KEY_UP, K.KEY_UP, K.KEY_UP, K.KEY_ENTER])   # wraps: 1 -> 3 -> 2 -> 1
    assert ui.choose("t", OPTS) == "1"


def test_back_keys_return_none(monkeypatch):
    ui, _ = _rich_ui()
    for key in (K.KEY_ESC, K.KEY_LEFT, K.KEY_BACKSPACE, "q"):
        _keys(monkeypatch, [key])
        assert ui.choose("t", OPTS) is None


def test_disabled_option_shows_notice_and_is_not_returned(monkeypatch):
    ui, out = _rich_ui()
    _keys(monkeypatch, [K.KEY_UP, K.KEY_ENTER, K.KEY_ESC])   # up from first wraps to the disabled one
    assert ui.choose("t", OPTS) is None
    assert "Three is coming soon." in out.getvalue()


def test_number_keys_and_ignored_keys(monkeypatch):
    ui, _ = _rich_ui()
    _keys(monkeypatch, ["", "x", "2"])
    assert ui.choose("t", OPTS) == "2"


def test_menu_renders_cursor_logo_and_description(monkeypatch):
    ui, out = _rich_ui()
    opts = [Option("Start Game", "s", "Pick a mode and play"), Option("Exit", "e")]
    _keys(monkeypatch, [K.KEY_ENTER])
    ui.choose("Main menu", opts)
    text = out.getvalue()
    assert "> Start Game" in text and "  Exit" in text
    assert "Pick a mode and play" in text
    assert "/ __ \\" in text            # figlet logo present on a roomy terminal


def test_small_terminal_menu_drops_the_logo(monkeypatch):
    ui, out = _rich_ui(width=50, height=16)
    _keys(monkeypatch, [K.KEY_ENTER])
    ui.choose("Main menu", OPTS)
    assert "/ __ \\" not in out.getvalue() and "ROCK PAPER SCISSORS" in out.getvalue()


def test_ask_number_typing_backspace_validation_and_back(monkeypatch):
    ui, out = _rich_ui()
    _keys(monkeypatch, ["1", "2", K.KEY_BACKSPACE, "5", K.KEY_ENTER])
    assert ui.ask_number("n", 1, 99) == 15
    _keys(monkeypatch, ["0", K.KEY_ENTER, "7", K.KEY_ENTER])      # 0 rejected, then 7 accepted
    assert ui.ask_number("n", 1, 99) == 7
    ui2, out2 = _rich_ui()
    _keys(monkeypatch, ["0", K.KEY_ENTER, K.KEY_ESC])             # leave while the warning shows
    assert ui2.ask_number("n", 1, 99) is None
    assert "between 1 and 99" in out2.getvalue()
    _keys(monkeypatch, ["1", "2", "3", K.KEY_ENTER])    # a 3rd digit is ignored -> 12
    assert ui.ask_number("n", 1, 99) == 12


def test_ask_number_esc_goes_back(monkeypatch):
    ui, _ = _rich_ui()
    _keys(monkeypatch, [K.KEY_ESC])
    assert ui.ask_number("n", 1, 99) is None


# -- the whole flow -------------------------------------------------------------

def test_full_menu_flow_single_player_unlimited(monkeypatch):
    ui, _ = _rich_ui()
    # Start Game > Single Player > Hard > Unlimited
    _keys(monkeypatch, [K.KEY_ENTER, K.KEY_ENTER, K.KEY_DOWN, K.KEY_DOWN, K.KEY_ENTER, K.KEY_ENTER])
    assert menu.select_game(ui) == GameConfig(difficulty="hard")


def test_full_menu_flow_custom_rounds(monkeypatch):
    ui, _ = _rich_ui()
    _keys(monkeypatch, [K.KEY_ENTER, K.KEY_ENTER, K.KEY_ENTER,      # start, single, easy
                        K.KEY_DOWN, K.KEY_ENTER, "7", K.KEY_ENTER])  # custom rounds -> 7
    assert menu.select_game(ui) == GameConfig(difficulty="easy", rounds=7)


def test_escape_steps_back_one_level_at_a_time(monkeypatch):
    ui, _ = _rich_ui()
    _keys(monkeypatch, [K.KEY_ENTER, K.KEY_ENTER, K.KEY_ENTER,      # -> rounds screen
                        K.KEY_ESC,                                   # back to difficulty
                        K.KEY_DOWN, K.KEY_ENTER, K.KEY_ENTER])       # normal, unlimited
    assert menu.select_game(ui) == GameConfig(difficulty="normal")


def test_dual_player_opens_the_create_join_menu(monkeypatch):
    ui, out = _rich_ui()
    _keys(monkeypatch, [K.KEY_ENTER, K.KEY_DOWN, K.KEY_ENTER,        # Start Game > Dual Player
                        K.KEY_ESC,                                   # back out of Create/Join
                        K.KEY_ESC,                                   # back out of the mode menu
                        K.KEY_DOWN, K.KEY_DOWN, K.KEY_ENTER])        # Exit
    assert menu.select_game(ui) is None
    assert "Create game" in out.getvalue()


def test_multiplayer_is_not_selectable_yet(monkeypatch):
    ui, out = _rich_ui()
    _keys(monkeypatch, [K.KEY_ENTER, K.KEY_DOWN, K.KEY_DOWN, K.KEY_ENTER,   # Multiplayer
                        K.KEY_ESC, K.KEY_ESC])
    assert menu.select_game(ui) is None
    assert "Multiplayer is coming soon." in out.getvalue()


def test_exit_from_main_menu(monkeypatch):
    ui, _ = _rich_ui()
    _keys(monkeypatch, [K.KEY_DOWN, K.KEY_DOWN, K.KEY_ENTER])
    assert menu.select_game(ui) is None


# -- plain (numbered) menus + the CLI loop -----------------------------------------

def test_plain_menu_flow_then_game_then_back_to_menu_then_exit(monkeypatch, capsys):
    _feed(monkeypatch, ["1", "1", "2", "1",     # Start, Single, Normal, Unlimited
                        "r", "q",               # play a round, quit the game
                        "3"])                   # main menu: Exit
    assert cli.main(["--plain"]) == 0
    out = capsys.readouterr().out
    assert "Main menu" in out and "Select difficulty" in out
    assert "Rounds 1" in out and "Thanks for playing!" in out
    assert stats.load().rounds == 1


def test_plain_menu_rejects_bad_input_and_coming_soon(monkeypatch, capsys):
    _feed(monkeypatch, ["9", "x", "1",     # junk, junk, then Start Game
                        "3",               # Multiplayer (notice)
                        "q",               # back to the main menu
                        "q"])              # main menu: q exits
    assert cli.main(["--plain"]) == 0
    out = capsys.readouterr().out
    assert "Please type a number from 1 to 3." in out
    assert "Multiplayer is coming soon." in out


def test_plain_custom_rounds_flow(monkeypatch, capsys):
    _feed(monkeypatch, ["1", "1", "1", "2",     # Start, Single, Easy, custom rounds
                        "x", "0", "2",          # bad, bad, then 2 rounds
                        "r", "p",               # the two rounds
                        "3"])                   # main menu: Exit
    assert cli.main(["--plain"]) == 0
    out = capsys.readouterr().out
    assert "Please enter a number between 1 and 99." in out
    assert "Round 2 of 2 played." in out
    assert any(t in out for t in ("You won the game", "Computer won the game", "tie"))


def test_direct_fixed_rounds_flag_skips_menu(monkeypatch, capsys):
    _feed(monkeypatch, ["r", "r", "r"])
    assert cli.main(["--plain", "-d", "easy", "-r", "3"]) == 0
    out = capsys.readouterr().out
    assert "Main menu" not in out
    assert "Rounds 3" in out and "Round 3 of 3 played." in out


def test_rounds_and_best_of_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["-r", "3", "-b", "3"])
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["-r", "100"])


# -- stats menu & settings -----------------------------------------------------------

def test_stats_menu_toggle_persists_and_keeps_the_cursor(monkeypatch):
    from rps_game import settings

    assert settings.load().show_stats_after_game is False        # off by default
    ui, out = _rich_ui()
    _keys(monkeypatch, [K.KEY_DOWN, K.KEY_DOWN, K.KEY_ENTER,     # toggle (3rd entry)
                        K.KEY_ENTER,                             # cursor stayed on it: toggle back on...
                        K.KEY_ESC])
    menu.stats_menu(ui)
    assert settings.load().show_stats_after_game is False        # toggled twice
    _keys(monkeypatch, [K.KEY_DOWN, K.KEY_DOWN, K.KEY_ENTER, K.KEY_ESC])
    menu.stats_menu(ui)
    assert settings.load().show_stats_after_game is True
    assert "Show stats after each game: On" in out.getvalue()


def test_stats_menu_head_to_head_is_coming_soon(monkeypatch):
    ui, out = _rich_ui()
    _keys(monkeypatch, [K.KEY_DOWN, K.KEY_ENTER, K.KEY_ESC])
    menu.stats_menu(ui)
    assert "Head-to-head is coming soon." in out.getvalue()


def test_stats_menu_view_shows_lifetime_screen(monkeypatch):
    stats.save(stats.Stats(wins=3, losses=1, draws=1, sessions=1, moves={"rock": 5}))
    ui, out = _rich_ui()
    _keys(monkeypatch, [K.KEY_ENTER, "x", K.KEY_ESC])            # view, any key, back
    menu.stats_menu(ui)
    text = out.getvalue()
    assert "LIFETIME STATISTICS" in text and "Favourite move: rock" in text


def test_stats_menu_reset_needs_confirmation(monkeypatch):
    stats.save(stats.Stats(wins=3))
    ui, _ = _rich_ui()
    _keys(monkeypatch, [K.KEY_DOWN, K.KEY_DOWN, K.KEY_DOWN, K.KEY_ENTER, "n", K.KEY_ESC])
    menu.stats_menu(ui)
    assert stats.load().wins == 3                                # declined
    _keys(monkeypatch, [K.KEY_DOWN, K.KEY_DOWN, K.KEY_DOWN, K.KEY_ENTER, "y", K.KEY_ESC])
    menu.stats_menu(ui)
    assert stats.load().wins == 0


def test_main_menu_stats_entry_opens_the_stats_menu(monkeypatch):
    ui, out = _rich_ui()
    _keys(monkeypatch, [K.KEY_DOWN, K.KEY_ENTER,                 # Stats
                        K.KEY_ESC,                               # leave stats menu
                        K.KEY_DOWN, K.KEY_DOWN, K.KEY_ENTER])    # then Exit
    assert menu.select_game(ui) is None
    assert "Show stats after each game" in out.getvalue()


def test_plain_stats_menu_flow(monkeypatch, capsys):
    from rps_game import settings

    _feed(monkeypatch, ["2", "3", "q", "3"])    # Stats > toggle > back > Exit
    assert cli.main(["--plain"]) == 0
    assert settings.load().show_stats_after_game is True
    assert "Show stats after each game: Off" in capsys.readouterr().out


def test_confirm_plain(monkeypatch):
    ui = GameUI(plain=True)
    _feed(monkeypatch, ["y"])
    assert ui.confirm("Sure?") is True
    _feed(monkeypatch, [""])
    assert ui.confirm("Sure?") is False
