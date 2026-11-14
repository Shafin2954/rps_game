import random

import pytest

from rps_game.engine import MOVES, Move
from rps_game.strategies import AdaptiveStrategy, RandomStrategy, create_strategy


def test_random_returns_valid_moves_and_is_seedable():
    a = RandomStrategy(random.Random(1))
    b = RandomStrategy(random.Random(1))
    seq_a = [a.choose([]) for _ in range(20)]
    assert seq_a == [b.choose([]) for _ in range(20)]
    assert set(seq_a) <= set(MOVES)


def test_adaptive_counters_a_predictable_player():
    bot = AdaptiveStrategy(randomness=0.0, rng=random.Random(0))
    history = [Move.ROCK] * 6
    assert all(bot.choose(history) is Move.PAPER for _ in range(20))


def test_adaptive_plays_random_until_enough_history():
    bot = AdaptiveStrategy(randomness=0.0, min_history=3, rng=random.Random(0))
    picks = {bot.choose([Move.ROCK]) for _ in range(60)}
    assert len(picks) > 1


def test_adaptive_only_looks_at_recent_window():
    bot = AdaptiveStrategy(randomness=0.0, window=4, rng=random.Random(0))
    history = [Move.ROCK] * 20 + [Move.SCISSORS] * 4
    assert bot.choose(history) is Move.ROCK  # counters scissors


@pytest.mark.parametrize("name", ["easy", "normal", "hard"])
def test_factory(name):
    assert create_strategy(name).choose([]) in MOVES


def test_factory_rejects_unknown():
    with pytest.raises(ValueError):
        create_strategy("impossible")


def test_pattern_strategy_punishes_a_cycle():
    from rps_game.strategies import PatternStrategy

    bot = PatternStrategy(randomness=0.0, rng=random.Random(0))
    history = [Move.ROCK, Move.PAPER, Move.SCISSORS] * 5   # ends on scissors
    # The human's next throw is rock, so the bot should answer with paper.
    assert all(bot.choose(history) is Move.PAPER for _ in range(10))


def test_pattern_strategy_learns_a_response_habit():
    from rps_game.strategies import PatternStrategy

    bot = PatternStrategy(randomness=0.0, rng=random.Random(0))
    R, P, S = Move.ROCK, Move.PAPER, Move.SCISSORS
    # After every paper this player throws scissors, whatever else happens.
    history = [R, P, S, R, R, P, S, R, P, S, R, R, P]    # ends on paper
    assert all(bot.choose(history) is R for _ in range(10))   # rock beats scissors


def test_pattern_strategy_falls_back_to_random_with_little_data():
    from rps_game.strategies import PatternStrategy

    bot = PatternStrategy(randomness=0.0, min_history=4, rng=random.Random(0))
    assert len({bot.choose([Move.ROCK]) for _ in range(60)}) > 1
