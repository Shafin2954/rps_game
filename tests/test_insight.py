import random

from rps_game.engine import MOVES, Move, Outcome, Round, judge
from rps_game.insight import (MIN_ROUNDS, analyse, count_reactions, merge_reactions,
                              reaction_tells, step_between)

R, P, S = Move.ROCK, Move.PAPER, Move.SCISSORS


def _rounds(pairs):
    return [Round(a, b, judge(a, b)) for a, b in pairs]


def test_steps_are_relative_to_your_own_previous_throw():
    assert step_between(R, R) == "stay"
    assert step_between(R, P) == "up"          # paper beats rock
    assert step_between(R, S) == "down"        # rock beats scissors


def test_too_short_a_game_says_nothing():
    assert analyse(_rounds([(R, S)] * (MIN_ROUNDS - 1))) is None
    assert analyse(_rounds([(R, S)] * MIN_ROUNDS)) is not None


def test_a_one_move_player_is_an_open_book():
    report = analyse(_rounds([(R, S)] * 20))
    assert report.shares[R] == 1.0 and report.repeat_rate == 1.0
    assert report.verdict == "An open book" and report.predictability > 0.8
    assert any("rock 100% of the time" in tell for tell in report.tells)
    assert "An open book" in report.lines()[0]


def test_random_play_is_hard_to_read():
    rng = random.Random(11)
    report = analyse(_rounds([(rng.choice(MOVES), rng.choice(MOVES)) for _ in range(300)]))
    assert report.verdict in ("Unreadable", "Hard to read")
    assert abs(sum(report.shares.values()) - 1.0) < 1e-9
    assert "Keep it that way" in " ".join(report.lines()) or report.tells


def test_reactions_are_counted_by_the_result_before_them():
    # win(R v S) -> stay R ; win -> up to P (loses to S) ; loss -> down to R ; draw (R v R)
    rounds = _rounds([(R, S), (R, S), (P, S), (R, R)])
    counts = count_reactions(rounds)
    assert counts["win"] == {"stay": 1, "up": 1, "down": 0}
    assert counts["loss"] == {"stay": 0, "up": 0, "down": 1}
    assert counts["draw"] == {"stay": 0, "up": 0, "down": 0}


def test_win_stay_is_spotted_and_put_into_words():
    # Always repeats after a win, always moves on after a loss.
    pairs, mine = [], R
    rng = random.Random(2)
    for _ in range(40):
        theirs = rng.choice(MOVES)
        pairs.append((mine, theirs))
        if judge(mine, theirs) is not Outcome.WIN:
            mine = mine.beaten_by
    report = analyse(_rounds(pairs))
    assert any(tell.startswith("After a win you repeat the winning throw") for tell in report.tells)
    assert len(report.tells) <= 2


def test_reaction_tells_need_enough_evidence():
    assert reaction_tells({"loss": {"stay": 0, "up": 0, "down": 3}}) == []
    found = reaction_tells({"loss": {"stay": 1, "up": 0, "down": 7}})
    assert found[0][0] == 7 / 8
    assert found[0][1] == "After a loss you switch to the one throw neither of you used (7 of 8)."
    assert reaction_tells({"loss": {"stay": 3, "up": 3, "down": 3}}) == []      # no lopsided habit
    assert reaction_tells({"nonsense": {"stay": 99}}) == []


def test_merging_reactions_adds_up():
    total = {"win": {"stay": 1, "up": 0, "down": 0}}
    merge_reactions(total, {"win": {"stay": 2, "up": 1, "down": 0}, "loss": {"stay": 4}})
    assert total == {"win": {"stay": 3, "up": 1, "down": 0}, "loss": {"stay": 4}}
