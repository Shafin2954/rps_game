"""The 4.0 additions as seen from the command line and the menus: the Oracle
difficulty, the mind reader, experience and achievements, the profile pages."""
import io

from rich.console import Console

from rps_game import cli, menu, stats, terminal
from rps_game import profile as profile_store
from rps_game.engine import Move
from rps_game.profile import Profile, Rival
from rps_game.ui import GameUI

K = terminal


def feed(monkeypatch, items):
    it = iter(items)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(it))


def keys(monkeypatch, items):
    it = iter(items)
    monkeypatch.setattr(terminal, "is_interactive", lambda: True)
    monkeypatch.setattr(terminal, "flush_input", lambda: None)
    monkeypatch.setattr(terminal, "read_key", lambda timeout=None: next(it))


def rich_ui(width=100, height=30):
    out = io.StringIO()
    return GameUI(animate=False, console=Console(file=out, width=width, height=height,
                                                 force_terminal=False)), out


# -- the Oracle difficulty ----------------------------------------------------------------

def test_oracle_is_selectable_from_the_command_line(monkeypatch, capsys):
    feed(monkeypatch, ["r"] * 12 + ["q"])
    assert cli.main(["--plain", "-d", "oracle"]) == 0
    out = capsys.readouterr().out
    assert "Computer: oracle" in out and "Rounds 12" in out
    assert out.count("You lose!") >= 6                      # twelve rocks in a row get read


def test_oracle_is_in_the_difficulty_menu(monkeypatch):
    ui, out = rich_ui()
    keys(monkeypatch, [K.KEY_ENTER, K.KEY_ENTER,             # Start Game > Single Player
                       K.KEY_UP, K.KEY_ENTER,                # wraps up to the last entry: Oracle
                       K.KEY_ENTER])                         # unlimited
    assert menu.select_game(ui) == menu.GameConfig(difficulty="oracle")
    assert "council of predictors" in out.getvalue()


# -- the mind reader on the results screen ----------------------------------------------------

def test_a_long_enough_game_gets_a_reading(monkeypatch, capsys):
    feed(monkeypatch, ["r"] * 10 + ["q"])
    cli.main(["--plain", "-d", "easy"])
    out = capsys.readouterr().out
    assert "Mind reader: An open book." in out and "(chance is 33%)" in out
    assert "You threw rock 100% of the time." in out


def test_a_short_game_gets_none(monkeypatch, capsys):
    feed(monkeypatch, ["r", "p", "s", "q"])
    cli.main(["--plain", "-d", "easy"])
    assert "Mind reader" not in capsys.readouterr().out


def test_the_reading_is_on_the_rich_results_screen_too(monkeypatch):
    ui, out = rich_ui()
    feed(monkeypatch, ["r"] * 9 + ["q"])
    result = cli.run_game(ui, menu.GameConfig(difficulty="easy"))
    ui.goodbye(result.session, None, None, extra=result.extra)
    text = out.getvalue()
    assert "Mind reader: An open book." in text and "XP. Rank: Novice" in text
    assert len(result.rounds) == 9 and all(r.player is Move.ROCK for r in result.rounds)


def test_habits_are_remembered_for_the_stats_screen(monkeypatch, capsys):
    class AlwaysScissors:
        def choose(self, history):
            return Move.SCISSORS

    monkeypatch.setattr(cli, "create_strategy", lambda d: AlwaysScissors())
    feed(monkeypatch, ["r"] * 14 + ["q"])          # thirteen times: won with rock, threw it again
    cli.main(["--plain", "-d", "easy"])
    assert stats.load().habits["win"] == {"stay": 13, "up": 0, "down": 0}
    capsys.readouterr()
    cli.main(["--plain", "--stats"])
    out = capsys.readouterr().out
    assert "Your tell: After a win you repeat the winning throw (13 of 13)." in out


def test_old_stats_files_without_habits_still_load():
    stats.stats_path().write_text('{"version": 1, "wins": 4, "moves": {"rock": 4}}')
    loaded = stats.load()
    assert loaded.wins == 4 and loaded.habits == {}
    loaded.merge(stats.Score(wins=1), stats.Score(), [Move.ROCK])     # no rounds given: still fine
    assert loaded.wins == 5 and loaded.habits == {}


# -- experience and achievements ------------------------------------------------------------

def test_a_game_earns_experience_and_achievements(monkeypatch, capsys):
    class AlwaysScissors:
        def choose(self, history):
            return Move.SCISSORS

    monkeypatch.setattr(cli, "create_strategy", lambda d: AlwaysScissors())
    feed(monkeypatch, ["r"] * 5 + ["q"])
    cli.main(["--plain", "-d", "hard"])
    out = capsys.readouterr().out
    assert "+30 XP. Rank: Novice (30 XP, 70 XP to Apprentice)" in out
    assert "Achievement unlocked: First Blood - Win a round." in out
    assert "Achievement unlocked: On a Roll - Win 5 rounds in a row." in out
    saved = profile_store.load()
    assert saved.xp == 30 and saved.rounds == 5
    assert set(saved.achievements) == {"first_win", "streak5"}

    feed(monkeypatch, ["r", "q"])                           # nothing new to unlock the second time
    cli.main(["--plain", "-d", "hard"])
    assert "Achievement unlocked" not in capsys.readouterr().out


def test_no_save_earns_nothing(monkeypatch, capsys):
    feed(monkeypatch, ["r", "q"])
    cli.main(["--plain", "-d", "easy", "--no-save"])
    assert "XP" not in capsys.readouterr().out
    assert not profile_store.profile_path().exists()


def test_an_empty_session_earns_nothing(monkeypatch, capsys):
    feed(monkeypatch, ["q"])
    cli.main(["--plain", "-d", "easy"])
    assert "XP" not in capsys.readouterr().out
    assert not profile_store.profile_path().exists()


# -- profile pages ------------------------------------------------------------------------------

def test_profile_flag_prints_rank_records_and_achievements(capsys):
    p = Profile(xp=750, rounds=300, runs=4, victories=1, best_floors=10, best_score=6100,
                foes_beaten=["pebble", "loop", "oracle"])
    p.unlock("summit")
    profile_store.save(p)
    assert cli.main(["--plain", "--profile"]) == 0
    out = capsys.readouterr().out
    assert "Rank: Duelist (750 XP, 750 XP to Tactician)" in out
    assert "Runs: 4   Conquered: 1" in out and "Best score: 6100" in out
    assert "Foes defeated at least once: 3 of 18" in out
    assert "ACHIEVEMENTS (1 of 17)" in out
    assert "[x] Top of the Tower: Defeat the Oracle and conquer the Gauntlet." in out
    assert "[ ] First Blood: Win a round." in out


def test_a_fresh_profile_reads_sensibly(capsys):
    cli.main(["--plain", "--profile"])
    out = capsys.readouterr().out
    assert "Rank: Novice (0 XP, 100 XP to Apprentice)" in out
    assert "No runs yet. The tower is waiting." in out


def test_stats_menu_opens_the_profile_and_achievement_pages(monkeypatch):
    p = Profile(xp=120)
    p.unlock("first_win")
    profile_store.save(p)
    ui, out = rich_ui()
    keys(monkeypatch, [K.KEY_DOWN, K.KEY_ENTER, "x",         # Profile, any key
                       K.KEY_DOWN, K.KEY_ENTER, "x",         # Achievements, any key
                       K.KEY_ESC])
    menu.stats_menu(ui)
    text = out.getvalue()
    assert "PROFILE" in text and "Rank: Apprentice (120 XP" in text
    assert "ACHIEVEMENTS (1 of 17)" in text
    row = next(line for line in text.splitlines() if "[x] First Blood" in line)
    assert row.split("[x] First Blood")[1].strip() == "Win a round."
    locked = next(line for line in text.splitlines() if "[ ] On a Roll" in line)
    assert locked.index("Win 5 rounds") == row.index("Win a round.")   # one aligned column
    assert "1 of 17 unlocked" in text                       # the menu entry's description
    assert "Press any key to go back" in text


def test_head_to_head_page_lists_rivals_most_recent_first(monkeypatch, capsys):
    profile_store.save(Profile(rivals={
        "a" * 32: Rival("Alice", 1, 2, 0, 5, 7, 3, "2026-11-01"),
        "b" * 32: Rival("Bob", 3, 0, 1, 9, 2, 1, "2026-11-17"),
    }))
    ui, out = rich_ui()
    keys(monkeypatch, ["x"])
    menu.show_head_to_head(ui, profile_store.load())
    text = out.getvalue()
    assert "HEAD-TO-HEAD" in text and "Games W-L-T" in text
    assert "3-0-1" in text and "9-2-1" in text and "1-2-0" in text
    assert text.index("Bob") < text.index("Alice")

    menu.show_head_to_head(GameUI(plain=True), profile_store.load())
    plain = capsys.readouterr().out
    assert "Bob (last played 2026-11-17)" in plain
    assert "Games: won 3, lost 0, tied 1. Rounds: won 9, lost 2, drawn 1." in plain
    assert plain.index("Bob") < plain.index("Alice")


def test_reset_wipes_the_profile_as_well(monkeypatch):
    stats.save(stats.Stats(wins=3))
    profile_store.save(Profile(xp=500))
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    assert cli.main(["--reset-stats"]) == 0
    assert stats.load().wins == 0 and profile_store.load().xp == 0


def test_page_prints_tables_in_non_interactive_mode():
    ui, out = rich_ui()
    ui.page("TITLE", ["a line", "", menu.Text("styled", style="bold")])
    text = out.getvalue()
    assert "TITLE" in text and "a line" in text and "styled" in text
