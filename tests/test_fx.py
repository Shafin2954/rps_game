"""The ASCII effects, as data: every frame must keep the canvas the same size,
and the animated paths of both screens must end in a sensible resting frame."""
import io
import random

import pytest
from rich.console import Console

from rps_game import art, cli, fx, terminal
from rps_game.engine import MOVES, Match, Move, Score
from rps_game.gauntlet import play
from rps_game.gauntlet.play import GauntletConfig, play_gauntlet
from rps_game.ui import TAGLINE, GameUI

R, P, S = Move.ROCK, Move.PAPER, Move.SCISSORS
ALL_HANDS = [art.FIST_LEFT, art.FIST_RIGHT, *art.HANDS_LEFT.values(), *art.HANDS_RIGHT.values()]


def shape(a):
    return len(a), {len(row) for row in a}


def ink(a):
    return sum(ch != " " for row in a for ch in row)


# ================================================================ single effects

@pytest.mark.parametrize("hand", ALL_HANDS)
def test_every_effect_keeps_the_canvas_size(hand):
    for step in range(0, 5):
        for effect in (fx.crush(hand, step),
                       fx.cover(hand, step, from_left=True), fx.cover(hand, step, from_left=False),
                       fx.cut(hand, step, from_left=True), fx.cut(hand, step, from_left=False)):
            assert shape(effect) == shape(hand)
    for frame in fx.dissolve(hand, 6, random.Random(0)):
        assert shape(frame) == shape(hand)


def test_step_zero_changes_nothing():
    hand = art.HANDS_LEFT[S]
    assert fx.crush(hand, 0) == fx.cut(hand, 0, from_left=True) == tuple(hand)
    assert fx.cover(hand, 0, from_left=True) == tuple(hand)


def test_crush_drives_the_hand_down_and_leaves_rubble():
    hand = art.HANDS_LEFT[S]
    once, twice = fx.crush(hand, 1), fx.crush(hand, 2)
    assert once[0].strip() == "" and once[1:] == tuple(hand[:-1])
    assert twice[:2] == (" " * art.WIDTH,) * 2
    assert set(twice[-1]) & set("._,'")                     # the bottom row has broken up
    flat = fx.crush(hand, 99)                               # all the way: only rubble is left
    assert flat[:-1] == (" " * art.WIDTH,) * (art.HEIGHT - 1) and set(flat[-1]) <= set(" ._,'")


def test_cover_sweeps_in_from_the_winners_side_and_keeps_the_silhouette():
    hand = art.HANDS_RIGHT[R]
    part = fx.cover(hand, 1, from_left=False, shade="#")
    full = fx.cover(hand, 3, from_left=False, shade="#")
    assert all((a == " ") == (b == " ") for x, y in zip(hand, full) for a, b in zip(x, y))
    assert ink(full) == sum(row.count("#") for row in full)          # all of it is covered
    covered = [i for row in part for i, ch in enumerate(row) if ch == "#"]
    assert covered and min(covered) >= art.WIDTH - -(-art.WIDTH // 3)   # only the right third
    mirrored = fx.cover(hand, 1, from_left=True, shade="#")
    assert max(i for row in mirrored for i, ch in enumerate(row) if ch == "#") < art.WIDTH / 3 + 1


def test_cut_slashes_then_parts_the_halves():
    hand = art.HANDS_LEFT[P]
    slashed = fx.cut(hand, 1, from_left=True)
    marks = [row.index("/") for row in slashed if "/" in row]
    assert len(marks) == art.HEIGHT and marks == sorted(marks, reverse=True)   # a clean diagonal
    assert fx.cut(hand, 1, from_left=False)[0].startswith("\\")
    apart, further = fx.cut(hand, 2, from_left=True), fx.cut(hand, 3, from_left=True)
    assert apart != slashed and further != apart
    assert 0 < ink(further) <= ink(apart) <= ink(hand)      # the halves drift; nothing is added
    middle = art.HEIGHT // 2
    column = marks[middle]
    assert apart[middle][column - 1:column + 1] == "  "     # a gap has opened along the cut


def test_dissolve_only_ever_loses_ink_and_ends_empty():
    hand = art.HANDS_LEFT[R]
    frames = fx.dissolve(hand, 6, random.Random(3))
    assert len(frames) == 6 and ink(frames[-1]) == 0
    solid = [sum(ch not in " ." for row in f for ch in row) for f in frames]
    assert solid == sorted(solid, reverse=True) and solid[0] < ink(hand)
    assert frames == fx.dissolve(hand, 6, random.Random(3))            # seeded


# ================================================================ the clash

@pytest.mark.parametrize("move", MOVES)
@pytest.mark.parametrize("winner", [0, 1])
def test_a_decisive_clash_lunges_hits_and_rests_on_the_beaten_hand(move, winner):
    left, right = art.HANDS_RIGHT[move if winner == 0 else move.beats], \
        art.HANDS_LEFT[move if winner == 1 else move.beats]
    beats = fx.clash(left, right, winner=winner, move=move, reach=4, shade="#")
    loser = 1 - winner
    assert max(b.close for b in beats) == 4 and beats[0].close < 4      # in, then...
    assert any(fx.WORDS[move] in "".join(b.burst) for b in beats)       # ...the word...
    assert {b.shake for b in beats} >= {1, -1}                          # ...and a jolt
    rest = beats[-1]
    assert rest.close == 0 and rest.burst == () and rest.shake == 0
    assert rest.beaten == (loser == 0, loser == 1) and rest.back[loser] == 2
    assert rest.back[winner] == 0
    assert (rest.left, rest.right)[winner] == (tuple(left), tuple(right))[winner]   # untouched
    assert (rest.left, rest.right)[loser] != (tuple(left), tuple(right))[loser]     # wrecked
    for b in beats:
        assert shape(b.left) == shape(left) and shape(b.right) == shape(right)
        assert b.hold >= 0


def test_each_winning_throw_has_its_own_effect():
    paper = art.HANDS_LEFT[P]
    rest = fx.clash(art.HANDS_RIGHT[S], paper, winner=0, move=S)[-1]
    assert rest.right == fx.cut(paper, 3, from_left=True)
    scissors = art.HANDS_LEFT[S]
    rest = fx.clash(art.HANDS_RIGHT[R], scissors, winner=0, move=R)[-1]
    assert rest.right == fx.crush(scissors, 3)
    rock = art.HANDS_RIGHT[R]
    rest = fx.clash(rock, art.HANDS_LEFT[P], winner=1, move=P, shade="#")[-1]
    assert rest.left == fx.cover(rock, 3, from_left=False, shade="#")   # from the winner's side


def test_a_draw_clangs_and_leaves_both_hands_alone():
    left, right = art.HANDS_RIGHT[R], art.HANDS_LEFT[R]
    beats = fx.clash(left, right, winner=None)
    assert any(fx.DRAW_WORD in "".join(b.burst) for b in beats)
    assert all(b.left == tuple(left) and b.right == tuple(right) for b in beats)
    assert beats[-1] == fx.Beat(tuple(left), tuple(right))


# ================================================================ composing a row

def test_compose_places_both_hands_and_centres_the_burst():
    left, right = art.HANDS_RIGHT[R], art.HANDS_LEFT[S]
    rows = fx.compose(left, right, 4, 4 + art.WIDTH + 10, fx.BURST)
    assert len(rows) == art.HEIGHT
    for (text, spans), left_row, right_row in zip(rows, left, right):
        assert len(text) == 4 + 2 * art.WIDTH + 10
        assert text[4:4 + art.WIDTH] == left_row            # the burst stays in the gap
        assert text[4 + art.WIDTH + 10:] == right_row
        assert spans[0] == (4, 4 + art.WIDTH, "left")
        assert spans[1] == (4 + art.WIDTH + 10, 4 + 2 * art.WIDTH + 10, "right")
    star = next(text for text, _ in rows if "*" in text)
    assert abs(star.index("*") - (4 + art.WIDTH + 5)) <= 1               # the middle of the gap
    assert sum(1 for _, spans in rows if any(role == "burst" for *_, role in spans)) == 3
    assert fx.compose(left, right, 4, 40) == fx.compose(left, right, 4, 40, ())


def test_compose_never_goes_negative_and_survives_overlap():
    left, right = art.HANDS_RIGHT[P], art.HANDS_LEFT[P]
    rows = fx.compose(left, right, -3, 6, fx.CLANG)
    assert all(len(text) == 6 + art.WIDTH for text, _ in rows)
    assert all(start >= 0 for _, spans in rows for start, _, _ in spans)


# ================================================================ fireworks

def test_fireworks_stay_on_the_canvas_and_are_seeded():
    def show(seed):
        return list(fx.fireworks(80, 24, frames=40, rng=random.Random(seed)))

    frames = show(1)
    assert len(frames) == 40 and frames == show(1) and frames != show(2)
    cells = [cell for frame in frames for cell in frame]
    assert cells and all(0 <= x < 80 and 0 <= y < 24 for x, y, _, _ in cells)
    assert {ch for _, _, ch, _ in cells} <= set("|*+.")
    assert any(ch == "*" for _, _, ch, _ in cells)                      # something burst
    assert len(frames[-1]) < max(len(f) for f in frames)                # and it dies away


# ================================================================ on the real screens

def animated_ui(monkeypatch, width=100, height=30, keys=None):
    """A UI that believes it is on a real terminal, with time standing still."""
    out = io.StringIO()
    console = Console(file=out, width=width, height=height, force_terminal=True,
                      color_system=None)
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    monkeypatch.setattr(terminal, "is_interactive", lambda: True)
    monkeypatch.setattr(terminal, "flush_input", lambda: None)
    calls = []
    source = iter(keys or [])

    def read_key(timeout=None):
        calls.append(timeout)
        return next(source, None)

    monkeypatch.setattr(terminal, "read_key", read_key)
    ui = GameUI(console=console)
    assert ui.animate
    return ui, out, calls


def test_classic_round_plays_the_clash_and_rests_on_it(monkeypatch):
    ui, out, _ = animated_ui(monkeypatch)
    match, session = Match(), Score()
    ui.start_round(match, session, "normal")
    rnd = match.play(R, S)
    session.record(rnd.outcome)
    ui.show_round(rnd, match, session)
    assert ui._view.beaten == (False, True) and ui._view.back == (0, 2) and ui._view.close == 0
    assert ui._view.right_art == fx.crush(art.HANDS_LEFT[S], 3)
    assert ui._view.left_art == art.HANDS_RIGHT[R]
    ui.end_round()
    assert "CRUNCH!" in out.getvalue() and "YOU WIN!" in out.getvalue()

    ui.start_round(match, session, "normal")                # the next round starts clean
    assert ui._view.beaten == (False, False) and ui._view.back == (0, 0)
    ui.end_round()


def test_the_beaten_hand_follows_the_side_you_sit_on(monkeypatch):
    from rps_game.players import Seat, Side
    ui, _, _ = animated_ui(monkeypatch)
    ui.set_players(Seat("Alice", Side.RIGHT), Seat("Bob", Side.LEFT))
    match, session = Match(), Score()
    ui.start_round(match, session, "")
    rnd = match.play(P, R)                                  # Alice (right) wraps Bob's rock (left)
    ui.show_round(rnd, match, session)
    assert ui._view.beaten == (True, False)
    assert ui._view.left_art == fx.cover(art.HANDS_RIGHT[R], 3, from_left=False)
    ui.end_round()


def test_no_clash_without_room_for_the_art(monkeypatch):
    ui, out, _ = animated_ui(monkeypatch, width=60, height=20)
    match, session = Match(), Score()
    ui.start_round(match, session, "normal")
    ui.show_round(match.play(R, S), match, session)
    ui.end_round()
    assert "CRUNCH!" not in out.getvalue() and ui._view.beaten == (False, False)


def test_gauntlet_fight_plays_clash_and_knock_out(monkeypatch):
    box = {}
    real = play.new_run
    monkeypatch.setattr(play, "new_run", lambda config: box.setdefault("run", real(config)))

    def typist():
        yield " "                                           # briefing
        yield " "                                           # foe card
        while box["run"].duel is not None:
            yield str(box["run"].duel.intent.beaten_by)[0]
        yield terminal.KEY_ESC                              # reward menu: walk away
        yield "y"

    ui, out, _ = animated_ui(monkeypatch, keys=typist())
    result = play_gauntlet(ui, GauntletConfig(seed="abc"))
    text = out.getvalue()
    assert result.run.floors_cleared == 1
    assert any(word in text for word in fx.WORDS.values())
    assert "K.O." in text
    assert f'{result.run.ladder[0].name}: "' in text        # and the foe had something to say


def test_splash_wipes_the_logo_in_and_ends_on_the_tagline(monkeypatch):
    ui, out, calls = animated_ui(monkeypatch)
    ui.splash()
    text = out.getvalue()
    assert TAGLINE in text and "/ __ \\" in text
    assert any(word in text for word in fx.WORDS.values())  # two hands threw down
    assert len(calls) > 20 and all(t is not None for t in calls)


def test_any_key_skips_the_splash(monkeypatch):
    ui, out, calls = animated_ui(monkeypatch, keys=["x"])
    ui.splash()
    assert len(calls) == 1 and TAGLINE not in out.getvalue()


def test_splash_and_fireworks_stay_out_of_plain_and_unanimated_sessions(monkeypatch):
    for options in ({"plain": True}, {"animate": False}):
        out = io.StringIO()
        ui = GameUI(console=Console(file=out, width=100, height=30, force_terminal=False),
                    **options)
        monkeypatch.setattr(terminal, "is_interactive", lambda: True)
        ui.splash()
        ui.celebrate("YOU WIN!")
        assert out.getvalue() == ""


def test_fireworks_show_the_title_and_can_be_skipped(monkeypatch):
    ui, out, calls = animated_ui(monkeypatch)
    ui.celebrate("YOU WIN!", seconds=1.0)
    assert len(calls) == 20                                 # one frame per 50 ms
    assert "__  ______  __" in out.getvalue()               # the banner, in big letters

    ui, out, calls = animated_ui(monkeypatch, keys=[None, None, "x"])
    ui.celebrate("YOU WIN!", seconds=5.0)
    assert len(calls) == 3


def test_a_title_too_wide_for_the_screen_falls_back_to_plain_text(monkeypatch):
    ui, out, _ = animated_ui(monkeypatch, width=40, height=12)
    ui.celebrate("CONQUERED!", seconds=0.2)
    assert "CONQUERED!" in out.getvalue()


def test_winning_a_game_sets_off_the_fireworks_once(monkeypatch):
    ui, _, _ = animated_ui(monkeypatch)
    shows = []
    monkeypatch.setattr(ui, "celebrate", lambda title, seconds=2.2: shows.append(title))
    won, lost = Match(first_to=1), Match(first_to=1)
    won.play(R, S)
    lost.play(R, P)
    ui.goodbye(won.score, finished=won)
    ui.goodbye(lost.score, finished=lost)
    ui.goodbye(Score())
    assert shows == ["YOU WIN!"]


def test_menu_mode_opens_with_the_splash(monkeypatch):
    seen = []
    monkeypatch.setattr(GameUI, "splash", lambda self: seen.append("splash"))
    monkeypatch.setattr(cli, "select_game", lambda ui: None)
    assert cli.main(["--plain"]) == 0
    assert seen == ["splash"]                               # called; plain mode makes it a no-op
