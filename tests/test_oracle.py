import random

from rps_game.engine import MOVES, Move, Outcome, judge
from rps_game.oracle import Oracle, OracleStrategy, predictability
from rps_game.strategies import create_strategy

R, P, S = Move.ROCK, Move.PAPER, Move.SCISSORS


def _score(player, rounds=150, seed=0):
    """Play ``player(mine, theirs, results, rng)`` against the Oracle.
    Returns the Oracle's (wins, losses)."""
    rng = random.Random(seed)
    bot = OracleStrategy(rng=random.Random(seed + 1))
    mine, theirs, results = [], [], []
    wins = losses = 0
    for _ in range(rounds):
        throw = player(mine, theirs, results, rng)
        answer = bot.choose(mine)
        result = judge(throw, answer)
        mine.append(throw)
        theirs.append(answer)
        results.append(result)
        wins += result is Outcome.LOSS          # counted from the Oracle's side
        losses += result is Outcome.WIN
    return wins, losses


def test_has_no_opinion_before_it_has_seen_anything():
    assert Oracle().advise() == (None, 0.0)


def test_is_seedable_and_returns_valid_moves():
    def game(seed):
        bot = OracleStrategy(rng=random.Random(seed))
        rng, history, picks = random.Random(9), [], []
        for _ in range(40):
            picks.append(bot.choose(history))
            history.append(rng.choice(MOVES))
        return picks

    assert game(4) == game(4)
    assert set(game(4)) <= set(MOVES)


def test_crushes_a_metronome():
    wins, losses = _score(lambda mine, *_: MOVES[len(mine) % 3])
    assert wins > 130 and losses < 10


def test_crushes_someone_who_always_throws_the_same():
    wins, losses = _score(lambda *_: R)
    assert wins > 135 and losses < 5


def test_reads_win_stay_lose_shift():
    def player(mine, theirs, results, rng):
        if not mine:
            return rng.choice(MOVES)
        if results[-1] is Outcome.WIN:
            return mine[-1]
        return theirs[-1].beaten_by

    wins, losses = _score(player)
    assert wins > 120 and losses < 15


def test_reads_a_player_who_copies_its_last_throw():
    wins, losses = _score(lambda mine, theirs, results, rng: theirs[-1] if theirs else R)
    assert wins > 120 and losses < 15


def test_exploits_a_mere_bias():
    wins = losses = 0
    for seed in range(8):
        won, lost = _score(lambda m, t, r, rng: rng.choices(MOVES, [0.55, 0.25, 0.2])[0],
                           rounds=200, seed=seed)
        wins, losses = wins + won, losses + lost
    assert wins > losses * 1.25


def test_cannot_beat_true_randomness():
    wins = losses = 0
    for seed in range(10):
        won, lost = _score(lambda m, t, r, rng: rng.choice(MOVES), rounds=200, seed=seed)
        wins, losses = wins + won, losses + lost
    assert abs(wins - losses) < 0.08 * (wins + losses)


def test_priming_teaches_it_habits_seen_elsewhere():
    oracle = Oracle()
    oracle.prime([R, P, S] * 6)
    assert oracle.rounds == 18
    # It has never played this opponent, yet it knows rock follows scissors.
    for theirs in (R, P, S, R, P, S):
        oracle.observe(theirs, None)
    throw, confidence = oracle.advise()
    assert throw is P and confidence > 0


def test_strategy_copes_with_history_it_did_not_play():
    bot = OracleStrategy(rng=random.Random(1))
    assert bot.choose([R, R, R, R, R, R, R, R]) in MOVES      # joined mid-game
    assert bot.choose([R] * 9) is P


def test_noise_makes_it_fallible():
    strict = OracleStrategy(rng=random.Random(2))
    sloppy = OracleStrategy(rng=random.Random(2), noise=1.0)
    history = [R] * 30
    assert all(strict.choose(history[:n]) is P for n in range(10, 30))
    assert {sloppy.choose(history[:n]) for n in range(10, 30)} == set(MOVES)


def test_predictability_tells_a_metronome_from_noise():
    rng = random.Random(5)
    metronome = [(MOVES[i % 3], rng.choice(MOVES)) for i in range(60)]
    noise = [(rng.choice(MOVES), rng.choice(MOVES)) for _ in range(300)]
    assert predictability(metronome) > 0.85
    assert 0.25 < predictability(noise) < 0.42
    assert predictability([]) == 0.0


def test_oracle_is_a_difficulty():
    bot = create_strategy("oracle", random.Random(3))
    assert isinstance(bot, OracleStrategy)
    assert bot.choose([]) in MOVES
