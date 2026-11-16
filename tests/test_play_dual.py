"""Whole online games, driven from the screen side: one real play_dual() on the host,
a scripted opponent on the other end, real commit-reveal in between."""
import io
import threading
import time

from rich.console import Console

from netutil import connected_pair, recv, send, PASS, ROOM
from rps_game import cli, terminal
from rps_game.dualsetup import DualSetup
from rps_game.engine import Move, Round, judge
from rps_game.net import fairness
from rps_game.net import protocol as proto
from rps_game.net.errors import NetError
from rps_game.net.game import NetworkOpponent
from rps_game.net.play import play_dual
from rps_game.net.session import GameTerms
from rps_game.passkey import Passkey
from rps_game.players import Side
from rps_game.ui import GameUI

R, P, S = Move.ROCK, Move.PAPER, Move.SCISSORS
SLOW = dict(ping_interval=60, first_ping_delay=60, liveness_timeout=600)


def bot_playing(*moves, then="wait", rematch=0):
    """An opponent that throws ``moves`` in order, then waits (or leaves)."""
    def run(opp):
        try:
            for move in moves:
                theirs = opp.play(move)
                opp.record(Round(move, theirs, judge(move, theirs)))
            for _ in range(rematch):                       # agree to that many rematches
                opp.rematch()
                for move in moves:
                    theirs = opp.play(move)
                    opp.record(Round(move, theirs, judge(move, theirs)))
            if then == "leave":
                opp.close("quit")
            else:
                deadline = time.monotonic() + 5
                while opp.error is None and time.monotonic() < deadline:
                    time.sleep(0.02)
        except NetError:
            pass
        finally:
            opp.close()
    return run


def pair(terms=GameTerms(first_to=2)):
    """A connected host/joiner pair playing first-to-2 unless told otherwise."""
    return connected_pair(terms=terms)


def host_setup(side=Side.LEFT, terms=GameTerms(first_to=2)):
    return DualSetup("host", "Sohan", Passkey(PASS), side, ROOM,
                     rounds=terms.rounds, first_to=terms.first_to)


def drive(monkeypatch, inputs, bot, *, terms=GameTerms(first_to=2), ui=None, side=Side.LEFT,
          bot_options=None, **options):
    """Run play_dual on the host with scripted ``inputs``; return (ui, bot thread)."""
    host, join, _ = connected_pair(terms=terms)
    it = iter(inputs)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(it))
    ui = ui or GameUI(plain=True)
    t = threading.Thread(target=lambda: bot(NetworkOpponent(join, **{**SLOW, **(bot_options or {})})),
                         daemon=True)
    t.start()
    play_dual(ui, host_setup(side, terms), host, run_game=cli.run_game, **{**SLOW, **options})
    t.join(10)
    assert not t.is_alive()
    return ui


# ================================================================ a normal game

def test_winning_a_game_over_the_network(monkeypatch, capsys):
    drive(monkeypatch, ["r", "r", "2"], bot_playing(S, S))                # 2 = back to the menu
    out = capsys.readouterr().out
    assert out.count("You win!") == 2
    assert "You won the match 2-0!" in out
    assert "Game over" in out and "Play again" in out
    assert "forfeit" not in out


def test_losing_and_drawing_are_reported_from_your_side(monkeypatch, capsys):
    drive(monkeypatch, ["r", "r", "r", "2"], bot_playing(P, R, P))        # lose, draw, lose
    out = capsys.readouterr().out
    assert "You lose!" in out and "It's a draw!" in out
    assert "Bob won the match 2-0." in out                                # the opponent is named; winner first


def test_the_opponents_name_is_used_in_the_texts(monkeypatch, capsys):
    drive(monkeypatch, ["r", "r", "2"], bot_playing(S, S))
    out = capsys.readouterr().out
    assert "You played rock. Bob played scissors." in out


def test_fixed_round_games_end_after_exactly_n_rounds(monkeypatch, capsys):
    drive(monkeypatch, ["r", "p", "s", "2"], bot_playing(S, S, S), terms=GameTerms(rounds=3))
    out = capsys.readouterr().out
    assert "Round 3 of 3 played." in out
    assert "won the game" in out or "tie" in out


def test_ui_goes_back_to_single_player_seats_afterwards(monkeypatch):
    ui = drive(monkeypatch, ["r", "r", "2"], bot_playing(S, S))
    assert (ui.you.name, ui.opponent.name) == ("You", "Computer")


# ================================================================ leaving and forfeits

def test_the_opponent_leaving_mid_game_is_a_win_by_forfeit(monkeypatch, capsys):
    drive(monkeypatch, ["r", "r"], bot_playing(S, then="leave"))          # leaves after round 1
    out = capsys.readouterr().out
    assert "Bob left the game." in out and "You win by forfeit." in out


def test_leaving_yourself_needs_confirmation_and_forfeits(monkeypatch, capsys):
    drive(monkeypatch, ["q", "y"], bot_playing(S))
    out = capsys.readouterr().out
    assert "forfeit" not in out.replace("Leave the game? You forfeit", "")   # no "you win" message for the leaver


def test_declining_to_leave_keeps_the_game_going(monkeypatch, capsys):
    drive(monkeypatch, ["q", "n", "r", "r", "2"], bot_playing(S, S))
    assert "You won the match 2-0!" in capsys.readouterr().out


def test_the_leave_prompt_warns_about_the_forfeit(monkeypatch):
    seen = []
    host, join, _ = pair()
    inputs = iter(["q", "y"])
    monkeypatch.setattr("builtins.input", lambda prompt="": seen.append(prompt) or next(inputs))
    t = threading.Thread(target=lambda: bot_playing(S)(NetworkOpponent(join, **SLOW)), daemon=True)
    t.start()
    play_dual(GameUI(plain=True), host_setup(), host, run_game=cli.run_game, **SLOW)
    assert any("forfeit" in p and "opponent wins" in p for p in seen)


# ================================================================ misbehaving opponents

def test_a_cheating_opponent_ends_the_game_and_you_win(monkeypatch, capsys):
    host, join, _ = pair()
    inputs = iter(["r"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

    def cheater():
        nonce = fairness.new_nonce()
        recv(join)                                                        # the host's commitment
        send(join, proto.Commit(1, fairness.commitment(1, "join", S, nonce), fairness.INITIAL_STATE))
        recv(join)                                                        # the host's reveal
        send(join, proto.Reveal(1, "paper", nonce))                       # changed their mind

    t = threading.Thread(target=cheater, daemon=True)
    t.start()
    play_dual(GameUI(plain=True), host_setup(), host, run_game=cli.run_game, **SLOW)
    t.join(5)
    out = capsys.readouterr().out
    assert "doesn't match what they locked in" in out and "You win by forfeit." in out


def test_a_silent_opponent_is_declared_gone(monkeypatch, capsys):
    host, join, _ = pair()                                      # nobody drives `join`
    inputs = iter(["r"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    play_dual(GameUI(plain=True), host_setup(), host, run_game=cli.run_game,
              ping_interval=0.05, liveness_timeout=0.4)
    out = capsys.readouterr().out
    assert "Lost contact with Bob." in out and "You win by forfeit." in out


def test_an_opponent_who_never_locks_in_times_out(monkeypatch, capsys):
    host, join, _ = pair()
    inputs = iter(["r"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    play_dual(GameUI(plain=True), host_setup(), host, run_game=cli.run_game,
              ping_interval=60, liveness_timeout=600, commit_timeout=0.4)
    out = capsys.readouterr().out
    assert "Timed out waiting for Bob to lock in." in out and "You win by forfeit." in out
    assert "Waiting for Bob to lock in..." in out                         # they were told what we waited for


# ================================================================ rematch

def test_a_rematch_starts_a_fresh_game_with_the_same_opponent(monkeypatch, capsys):
    # game 1, "Play again" (1), game 2, "Back to the menu" (2)
    drive(monkeypatch, ["r", "r", "1", "r", "r", "2"], bot_playing(S, S, rematch=1))
    out = capsys.readouterr().out
    # twice per game: once as the last round's verdict, once on the results screen
    assert out.count("You won the match 2-0!") == 4
    assert out.count("Round 1") >= 2                                      # a second game really started


def test_asking_for_a_rematch_when_the_opponent_left(monkeypatch, capsys):
    drive(monkeypatch, ["r", "r", "1"], bot_playing(S, S, then="leave"))
    out = capsys.readouterr().out
    assert "No rematch" in out


def test_asking_for_a_rematch_nobody_answers_times_out(monkeypatch, capsys):
    drive(monkeypatch, ["r", "r", "1"], bot_playing(S, S), rematch_timeout=0.4)
    assert "play again" in capsys.readouterr().out.lower()


# ================================================================ the rich screen

def _rich(monkeypatch, keys):
    out = io.StringIO()
    ui = GameUI(animate=False, console=Console(file=out, width=100, height=30, force_terminal=False))
    pending = iter(keys)

    def read_key(timeout=None):
        if timeout == 0:                                   # the wait screens' Esc/q poll
            return None
        return next(pending, None)

    monkeypatch.setattr(terminal, "is_interactive", lambda: True)
    monkeypatch.setattr(terminal, "flush_input", lambda: None)
    monkeypatch.setattr(terminal, "read_key", read_key)
    return ui, out


def test_the_rich_screen_shows_real_names_on_the_chosen_sides(monkeypatch):
    ui, out = _rich(monkeypatch, ["r", "r", terminal.KEY_DOWN, terminal.KEY_ENTER])
    host, join, _ = pair()
    t = threading.Thread(target=lambda: bot_playing(S, S)(NetworkOpponent(join, **SLOW)), daemon=True)
    t.start()
    play_dual(ui, host_setup(side=Side.RIGHT), host, run_game=cli.run_game, **SLOW)
    t.join(10)
    text = out.getvalue()
    header = next(line for line in text.splitlines() if "SOHAN" in line and "BOB" in line)
    assert header.index("BOB") < header.index("SOHAN")                    # I chose the right-hand side
    assert "YOU WIN!" in text
    assert "You won the match 2-0!" in text                               # the real results screen...
    assert "forfeit" not in text                                          # ...not the opponent-left path


def test_leaving_from_the_rich_screen_asks_first(monkeypatch):
    ui, out = _rich(monkeypatch, ["q", "n", "q", "y"])                    # decline once, then leave
    host, join, _ = pair()
    t = threading.Thread(target=lambda: bot_playing(S)(NetworkOpponent(join, **SLOW)), daemon=True)
    t.start()
    play_dual(ui, host_setup(), host, run_game=cli.run_game, **SLOW)
    t.join(10)
    assert out.getvalue().count("Leave the game?") >= 2                   # asked both times


def test_the_rich_screen_shows_the_opponent_locking_in(monkeypatch):
    """A non-terminal console keeps only each screen's last frame, so watch what the
    game *asks the screen to draw* instead."""
    ui, out = _rich(monkeypatch, [None, None, None, "r", terminal.KEY_DOWN, terminal.KEY_ENTER])
    notices = []
    real_draw = ui._draw

    def spy(**changes):
        if "notice" in changes:
            notices.append(changes["notice"].plain)
        return real_draw(**changes)

    ui._draw = spy
    host, join, _ = connected_pair(terms=GameTerms(first_to=1))
    t = threading.Thread(target=lambda: bot_playing(S)(NetworkOpponent(join, **SLOW)), daemon=True)
    t.start()
    play_dual(ui, host_setup(terms=GameTerms(first_to=1)), host, run_game=cli.run_game, **SLOW)
    t.join(10)
    assert "Bob is choosing..." in notices or "Bob has locked in" in notices
    assert "Bob has locked in" in notices                                 # the bot throws immediately


# ================================================================ latency and Ctrl-C

def test_the_round_trip_time_is_known_soon_after_connecting():
    host, join, _ = pair()
    a = NetworkOpponent(host, ping_interval=60, first_ping_delay=0.05, liveness_timeout=600)
    b = NetworkOpponent(join, ping_interval=60, first_ping_delay=0.05, liveness_timeout=600)
    try:
        deadline = time.monotonic() + 3
        while (a.rtt_ms is None or b.rtt_ms is None) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert a.rtt_ms is not None and b.rtt_ms is not None
    finally:
        a.close(); b.close()


def test_the_round_trip_time_reaches_the_round_screen(monkeypatch):
    """Round 1 starts before any heartbeat has come back; by round 2 the time is known."""
    notes = []

    class SpyUI(GameUI):
        def start_round(self, match, session, difficulty, *, note=""):
            notes.append(note)
            super().start_round(match, session, difficulty, note=note)

    host, join, _ = pair()
    fast = dict(ping_interval=60, first_ping_delay=0.05, liveness_timeout=600)
    t = threading.Thread(target=lambda: bot_playing(S, S)(NetworkOpponent(join, **fast)), daemon=True)
    t.start()
    inputs = iter(["r", "r", "2"])

    def thinking(prompt=""):
        time.sleep(0.4)                                        # a moment to think: heartbeats land
        return next(inputs)

    monkeypatch.setattr("builtins.input", thinking)
    play_dual(SpyUI(plain=True), host_setup(), host, run_game=cli.run_game, **fast)
    t.join(10)
    assert len(notes) == 2 and notes[1].endswith(" ms")


def test_ctrl_c_during_an_online_game_means_quit_the_program(monkeypatch):
    host, join, _ = pair()

    def raise_interrupt(prompt=""):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", raise_interrupt)
    t = threading.Thread(target=lambda: bot_playing(S)(NetworkOpponent(join, **SLOW)), daemon=True)
    t.start()
    assert play_dual(GameUI(plain=True), host_setup(), host, run_game=cli.run_game, **SLOW) is True
    t.join(10)


def test_an_ordinary_end_returns_false(monkeypatch, capsys):
    inputs = iter(["r", "r", "2"])
    host, join, _ = pair()
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    t = threading.Thread(target=lambda: bot_playing(S, S)(NetworkOpponent(join, **SLOW)), daemon=True)
    t.start()
    assert play_dual(GameUI(plain=True), host_setup(), host, run_game=cli.run_game, **SLOW) is False
    t.join(10)
    out = capsys.readouterr().out
    assert "You won the match 2-0!" in out and "forfeit" not in out       # a normal finish


def test_the_waiting_message_is_repeated_every_round_not_just_the_first(monkeypatch, capsys):
    def slow_bot(opp):
        try:
            for move in (S, S):
                time.sleep(0.5)                                # the host always has to wait for us
                theirs = opp.play(move)
                opp.record(Round(move, theirs, judge(move, theirs)))
            time.sleep(1.0)
        except NetError:
            pass
        finally:
            opp.close()

    drive(monkeypatch, ["r", "r", "2"], slow_bot)
    assert capsys.readouterr().out.count("Waiting for Bob to lock in...") == 2
