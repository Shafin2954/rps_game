import io

import pytest
from rich.console import Console

from rps_game import art, cli, stats
from rps_game.engine import Match, Move, Score
from rps_game.ui import GameUI


def _rich_ui(width=100, height=30):
    out = io.StringIO()
    console = Console(file=out, width=width, height=height, force_terminal=False)
    return GameUI(animate=False, console=console), out


def _play_one(ui, player, opponent):
    match, session = Match(), Score()
    ui.start_round(match, session, "normal")
    rnd = match.play(player, opponent)
    session.record(rnd.outcome)
    ui.show_round(rnd, match, session)
    ui.end_round()
    return rnd


def test_art_is_uniform_width():
    every = [art.FIST_RIGHT, art.FIST_LEFT, *art.HANDS_RIGHT.values(), *art.HANDS_LEFT.values()]
    for hand in every:
        assert len(hand) == art.HEIGHT
        assert {len(line) for line in hand} == {art.WIDTH}


def test_parser_validation():
    p = cli.build_parser()
    assert p.parse_args(["-b", "5"]).best_of == 5
    for bad in (["-b", "4"], ["-b", "x"], ["-d", "nightmare"]):
        with pytest.raises(SystemExit):
            p.parse_args(bad)


def test_rich_screen_shows_hands_result_and_updated_scoreboard():
    ui, out = _rich_ui()
    _play_one(ui, Move.ROCK, Move.SCISSORS)
    text = out.getvalue()
    assert "YOU" in text and "COMPUTER" in text
    assert "Wins" in text and "Win streak" in text
    # Only the final frame of the round remains: it holds the *updated* score.
    wins_row = [l for l in text.splitlines() if "│" in l and l.split("│")[1].strip().isdigit()]
    assert wins_row and wins_row[-1].split("│")[1].strip() == "1"


def test_scoreboard_is_horizontally_centred_and_below_hands():
    ui, out = _rich_ui(width=100)
    _play_one(ui, Move.PAPER, Move.ROCK)
    lines = out.getvalue().splitlines()
    top_border = next(l for l in lines if l.strip().startswith("╭"))
    left_margin = len(top_border) - len(top_border.lstrip())
    right_margin = 100 - len(top_border.rstrip())
    assert abs(left_margin - right_margin) <= 1
    hands_row = max(i for i, l in enumerate(lines) if "COMPUTER" in l)
    board_row = lines.index(top_border)
    assert board_row > hands_row + art.HEIGHT


def test_best_of_board_shows_match_score_and_winner_message():
    ui, out = _rich_ui()
    match, session = Match(best_of=1), Score()
    ui.start_round(match, session, "easy")
    rnd = match.play(Move.ROCK, Move.SCISSORS)
    session.record(rnd.outcome)
    ui.show_round(rnd, match, session)
    ui.end_round()
    text = out.getvalue()
    assert "Match (first to 1)" in text and "1 - 0" in text
    assert "You won the match 1-0!" in text


def test_small_terminal_uses_compact_layout_without_art():
    ui, out = _rich_ui(width=60, height=20)
    _play_one(ui, Move.PAPER, Move.PAPER)
    text = out.getvalue()
    assert "YOU: paper" in text and "COMPUTER: paper" in text
    assert "It's a draw!".upper() in text


def test_ascii_flag_uses_ascii_table_borders():
    out = io.StringIO()
    console = Console(file=out, width=100, height=30, force_terminal=False)
    ui = GameUI(animate=False, ascii_only=True, console=console)
    _play_one(ui, Move.ROCK, Move.PAPER)
    assert "╭" not in out.getvalue() and "+--" in out.getvalue()


def test_full_plain_game_via_piped_input(monkeypatch, capsys):
    answers = iter(["rock", "bogus", "p", "3", "quit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert cli.main(["--plain", "-d", "easy"]) == 0
    out = capsys.readouterr().out
    assert "not a valid move" in out
    assert "Rounds 3" in out
    assert "Thanks for playing!" in out


def test_best_of_match_runs_and_restarts(monkeypatch, capsys):
    class AlwaysScissors:
        def choose(self, history):
            return Move.SCISSORS

    monkeypatch.setattr(cli, "create_strategy", lambda d: AlwaysScissors())
    answers = iter(["r", "r", "r", "q"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    cli.main(["--plain", "-b", "3"])
    out = capsys.readouterr().out
    assert "You won the match 2-0!" in out
    assert "Matches won: 1" in out
    assert "(2 wins in a row)" in out


def test_eof_exits_cleanly(monkeypatch, capsys):
    def boom(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", boom)
    assert cli.main(["--plain", "-d", "easy"]) == 0
    assert "Thanks for playing!" in capsys.readouterr().out
    assert cli.main(["--plain"]) == 0          # EOF at the menu is fine too


def test_session_is_saved_and_shown_via_stats_flag(monkeypatch, capsys):
    answers = iter(["r", "p", "q"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    cli.main(["--plain", "-d", "easy"])
    saved = stats.load()
    assert saved.rounds == 2 and saved.sessions == 1
    capsys.readouterr()
    assert cli.main(["--plain", "--stats"]) == 0
    out = capsys.readouterr().out
    assert "Rounds 2" in out and "Sessions: 1" in out


def test_no_save_flag_leaves_stats_alone(monkeypatch):
    answers = iter(["r", "q"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    cli.main(["--plain", "--no-save"])
    assert stats.load().rounds == 0


def test_reset_stats_asks_for_confirmation(monkeypatch, capsys):
    stats.save(stats.Stats(wins=4))
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    cli.main(["--reset-stats"])
    assert stats.load().wins == 4
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    cli.main(["--reset-stats"])
    assert stats.load().wins == 0


# -- results screen respects the preference ------------------------------------------

def _play_plain_session(monkeypatch, capsys, extra=()):
    answers = iter(["r", "q"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    cli.main(["--plain", "-d", "easy", *extra])
    return capsys.readouterr().out


def test_results_hide_all_time_totals_by_default(monkeypatch, capsys):
    stats.save(stats.Stats(wins=10, sessions=2))
    out = _play_plain_session(monkeypatch, capsys)
    assert "This session" in out and "All time" not in out


def test_results_show_all_time_totals_when_enabled(monkeypatch, capsys):
    from rps_game import settings

    settings.save(settings.Settings(show_stats_after_game=True))
    stats.save(stats.Stats(wins=10, sessions=2))
    out = _play_plain_session(monkeypatch, capsys)
    assert "This session" in out and "All time" in out


def test_stats_are_still_saved_when_not_shown(monkeypatch, capsys):
    stats.save(stats.Stats(wins=10, sessions=2))
    _play_plain_session(monkeypatch, capsys)
    assert stats.load().sessions == 3


# -- first-to-N, opponents, sides, names, scoreboard heading ------------------------

def test_first_to_flag_plays_a_race_and_restarts(monkeypatch, capsys):
    class AlwaysScissors:
        def choose(self, history):
            return Move.SCISSORS

    monkeypatch.setattr(cli, "create_strategy", lambda d: AlwaysScissors())
    answers = iter(["r", "r", "q"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    cli.main(["--plain", "-f", "2"])
    out = capsys.readouterr().out
    assert "first to 2 wins" in out and "You won the match 2-0!" in out and "Matches won: 1" in out


def test_first_to_is_mutually_exclusive_with_other_limits():
    for combo in (["-f", "2", "-b", "3"], ["-f", "2", "-r", "3"], ["-f", "0"], ["-f", "100"]):
        with pytest.raises(SystemExit):
            cli.build_parser().parse_args(combo)


def test_run_game_accepts_any_opponent_and_reports_when_they_leave():
    from rps_game.menu import GameConfig

    class Leaver:
        name = "Bob"

        def __init__(self):
            self.calls = 0
            self.recorded = []

        def play(self, own):
            self.calls += 1
            return Move.SCISSORS if self.calls == 1 else None

        def record(self, rnd):
            self.recorded.append(rnd)

    class Keys:                      # a UI whose player always throws rock
        plain = True

        def intro(self, **_): ...
        def start_round(self, *_): ...
        def end_round(self): ...
        def ask_move(self): return Move.ROCK
        def show_round(self, *_): ...

    opp = Leaver()
    result = cli.run_game(Keys(), GameConfig(), save=False, opponent=opp)
    assert result.opponent_left and not result.interrupted
    assert result.session.wins == 1 and len(opp.recorded) == 1


def _strip(text):
    return "\n".join(line.rstrip() for line in text.splitlines())


def test_hands_follow_the_chosen_side():
    out = io.StringIO()
    ui = GameUI(animate=False, console=Console(file=out, width=100, height=30, force_terminal=False))
    from rps_game.players import Seat, Side
    ui.set_players(Seat("Alice", Side.RIGHT), Seat("Bob", Side.LEFT))
    _play_one(ui, Move.ROCK, Move.PAPER)         # Alice (right) throws rock, Bob (left) paper
    lines = out.getvalue().splitlines()
    header = next(l for l in lines if "ALICE" in l)
    assert header.index("BOB") < header.index("ALICE")
    paper_left_seat = art.HANDS_RIGHT[Move.PAPER][1].rstrip()      # left seat faces right
    rock_right_seat = art.HANDS_LEFT[Move.ROCK][1].rstrip()        # right seat faces left
    row = next(l for l in lines if paper_left_seat in l and rock_right_seat in l)
    assert row.index(paper_left_seat) < row.index(rock_right_seat)


def test_both_players_cannot_claim_the_same_side():
    from rps_game.players import Seat, Side
    ui, _ = _rich_ui_for_sides()
    ui.set_players(Seat("A", Side.LEFT), Seat("B", Side.LEFT))
    assert ui.opponent.side is Side.RIGHT


def _rich_ui_for_sides():
    out = io.StringIO()
    return GameUI(animate=False, console=Console(file=out, width=100, height=30, force_terminal=False)), out


@pytest.mark.parametrize("name", ["Alice", "সোহান", "李雷李雷", "Zoë", "Ünïcödé"])
def test_names_centre_by_cell_width(name):
    from rich.cells import cell_len
    from rps_game.ui import center_cells
    assert cell_len(center_cells(name, art.WIDTH)) == art.WIDTH


def test_overlong_names_are_trimmed_not_overflowing():
    from rich.cells import cell_len
    from rps_game.ui import center_cells
    assert cell_len(center_cells("A" * 40, art.WIDTH)) == art.WIDTH
    assert cell_len(center_cells("李" * 30, art.WIDTH)) == art.WIDTH


def test_wide_name_keeps_the_right_hand_column_fixed():
    """The right-hand name must start at the same screen column no matter how
    wide the left-hand name's characters are."""
    from rich.cells import cell_len
    from rps_game.players import Seat, Side

    def right_name_column(left_name):
        out = io.StringIO()
        ui = GameUI(animate=False,
                    console=Console(file=out, width=100, height=30, force_terminal=False))
        ui.set_players(Seat(left_name, Side.LEFT), Seat("Bob", Side.RIGHT))
        _play_one(ui, Move.ROCK, Move.ROCK)
        header = next(l for l in out.getvalue().splitlines() if "BOB" in l)
        return cell_len(header[:header.index("BOB")])

    assert right_name_column("Alice") == right_name_column("李雷李雷") == right_name_column("সোহান")


def _figlet_first_row():
    import pyfiglet
    return pyfiglet.figlet_format("SCOREBOARD", font="cybermedium", width=200).splitlines()[0].strip()


def test_scoreboard_heading_is_big_on_tall_terminals():
    ui, out = _rich_ui(width=100, height=30)
    _play_one(ui, Move.ROCK, Move.SCISSORS)
    assert _figlet_first_row() in out.getvalue()


def test_scoreboard_heading_falls_back_to_one_line_on_short_terminals():
    ui, out = _rich_ui(width=100, height=24)
    _play_one(ui, Move.ROCK, Move.SCISSORS)
    text = out.getvalue()
    assert _figlet_first_row() not in text
    assert any(line.strip() == "SCOREBOARD" for line in text.splitlines())


def test_scoreboard_heading_sits_above_the_table():
    ui, out = _rich_ui(width=100, height=30)
    _play_one(ui, Move.ROCK, Move.SCISSORS)
    lines = out.getvalue().splitlines()
    heading = next(i for i, l in enumerate(lines) if _figlet_first_row() in l)
    table_top = next(i for i, l in enumerate(lines) if l.strip().startswith("╭"))
    assert heading < table_top


def test_plain_mode_has_no_art_heading(monkeypatch, capsys):
    out = _play_plain_session(monkeypatch, capsys)
    assert _figlet_first_row() not in out
