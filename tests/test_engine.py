import itertools

import pytest

from rps_game.engine import MOVES, Match, Move, Outcome, Score, judge

R, P, S = Move.ROCK, Move.PAPER, Move.SCISSORS


@pytest.mark.parametrize(
    "a, b, expected",
    [
        (R, S, Outcome.WIN), (P, R, Outcome.WIN), (S, P, Outcome.WIN),
        (S, R, Outcome.LOSS), (R, P, Outcome.LOSS), (P, S, Outcome.LOSS),
        (R, R, Outcome.DRAW), (P, P, Outcome.DRAW), (S, S, Outcome.DRAW),
    ],
)
def test_judge_all_nine_cases(a, b, expected):
    assert judge(a, b) is expected


def test_judge_is_antisymmetric():
    flip = {Outcome.WIN: Outcome.LOSS, Outcome.LOSS: Outcome.WIN, Outcome.DRAW: Outcome.DRAW}
    for a, b in itertools.product(MOVES, repeat=2):
        assert judge(b, a) is flip[judge(a, b)]


def test_beats_and_beaten_by_are_inverse():
    for m in MOVES:
        assert m.beats.beaten_by is m
        assert m.beaten_by.beats is m


@pytest.mark.parametrize(
    "text, expected",
    [("r", R), (" Rock ", R), ("1", R), ("P", P), ("paper", P), ("2", P),
     ("s", S), ("SCISSORS", S), ("3", S), ("", None), ("x", None), ("rockk", None)],
)
def test_parse(text, expected):
    assert Move.parse(text) is expected


def test_score_tracks_outcomes():
    s = Score()
    for o in (Outcome.WIN, Outcome.WIN, Outcome.LOSS, Outcome.DRAW):
        s.record(o)
    assert (s.wins, s.losses, s.draws, s.rounds) == (2, 1, 1, 4)
    assert s.win_rate == 0.5


def test_empty_score_win_rate_is_zero():
    assert Score().win_rate == 0.0


def test_unlimited_match_never_ends():
    m = Match()
    for _ in range(50):
        m.play(R, S)
    assert not m.is_over and m.winner is None


def test_best_of_three_ends_at_two_wins_draws_ignored():
    m = Match(best_of=3)
    m.play(R, R)
    m.play(R, S)
    assert not m.is_over
    m.play(P, P)
    m.play(P, R)
    assert m.is_over and m.winner is Outcome.WIN
    with pytest.raises(ValueError):
        m.play(R, S)


def test_match_can_be_lost():
    m = Match(best_of=3)
    m.play(R, P)
    m.play(R, P)
    assert m.winner is Outcome.LOSS


@pytest.mark.parametrize("bad", [0, -1, 2, 4])
def test_best_of_must_be_odd_and_positive(bad):
    with pytest.raises(ValueError):
        Match(best_of=bad)


def test_streak_survives_draws_but_not_losses():
    s = Score()
    for o in (Outcome.WIN, Outcome.WIN, Outcome.DRAW, Outcome.WIN):
        s.record(o)
    assert (s.streak, s.best_streak) == (3, 3)
    s.record(Outcome.LOSS)
    assert (s.streak, s.best_streak) == (0, 3)
    s.record(Outcome.WIN)
    assert (s.streak, s.best_streak) == (1, 3)


def test_fixed_rounds_counts_draws_and_picks_highest_score():
    m = Match(max_rounds=3)
    m.play(R, R)                      # draw still uses up a round
    m.play(R, S)
    assert not m.is_over
    m.play(P, S)                      # loss
    assert m.is_over and m.winner is Outcome.DRAW   # 1 win, 1 loss, 1 draw
    with pytest.raises(ValueError):
        m.play(R, S)


def test_fixed_rounds_winner_and_loser():
    won = Match(max_rounds=2)
    won.play(R, S); won.play(R, R)
    assert won.winner is Outcome.WIN
    lost = Match(max_rounds=1)
    lost.play(R, P)
    assert lost.winner is Outcome.LOSS


def test_match_options_are_validated():
    with pytest.raises(ValueError):
        Match(best_of=3, max_rounds=3)
    with pytest.raises(ValueError):
        Match(max_rounds=0)


def test_first_to_ends_when_someone_reaches_n_and_ignores_draws():
    m = Match(first_to=3)
    for mv in [(R, S), (R, R), (R, S), (S, R), (R, R)]:
        m.play(*mv)
    assert not m.is_over and (m.score.wins, m.score.losses) == (2, 1)
    m.play(P, R)
    assert m.winner is Outcome.WIN and m.wins_needed == 3


def test_first_to_can_be_lost():
    m = Match(first_to=1)
    m.play(R, P)
    assert m.winner is Outcome.LOSS


def test_first_to_equals_best_of_majority():
    assert Match(first_to=3).wins_needed == Match(best_of=5).wins_needed == 3


def test_only_one_match_limit_allowed():
    with pytest.raises(ValueError):
        Match(first_to=2, best_of=3)
    with pytest.raises(ValueError):
        Match(first_to=2, max_rounds=3)
    with pytest.raises(ValueError):
        Match(first_to=0)
