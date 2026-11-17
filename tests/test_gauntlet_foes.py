import random
from collections import Counter
from itertools import pairwise

import pytest

from rps_game.engine import MOVES, Move, Outcome, judge
from rps_game.gauntlet.foes import FLOORS, FOES, ORACLE, ROSTER, WARDEN, build_ladder
from rps_game.gauntlet.rules import TRAITS, Sight

R, P, S = Move.ROCK, Move.PAPER, Move.SCISSORS


def spar(key, hero, rounds=60, seed=1, climb=(), hurt=False):
    """Let ``hero(mine, theirs, rng)`` throw at a foe's mind. Returns (hero throws, foe throws)."""
    rng = random.Random(seed)
    mind = FOES[key].mind(random.Random(seed + 100))
    mine, theirs = [], []
    for _ in range(rounds):
        sight = Sight(mine=tuple(theirs), theirs=tuple(mine),
                      results=tuple(judge(t, m) for t, m in zip(theirs, mine)),
                      climb=tuple(climb), hurt=hurt)
        answer = mind.choose(sight)
        mine.append(hero(mine, theirs, rng))
        theirs.append(answer)
    return mine, theirs


def randomly(mine, theirs, rng):
    return rng.choice(MOVES)


def wins(mine, theirs):
    return sum(judge(a, b) is Outcome.WIN for a, b in zip(mine, theirs))


# -- the ladder -------------------------------------------------------------------------

def test_the_ladder_climbs_through_the_tiers_to_the_oracle():
    for seed in range(30):
        ladder = build_ladder(random.Random(seed))
        assert len(ladder) == FLOORS == 10
        assert [spec.tier for spec in ladder] == [1, 1, 2, 2, 0, 3, 3, 4, 4, 0]
        assert ladder[4] is WARDEN and ladder[9] is ORACLE
        assert len({spec.key for spec in ladder}) == 10


def test_the_ladder_depends_only_on_the_seed():
    def names(seed):
        return [s.key for s in build_ladder(random.Random(seed))]

    assert names("abc") == names("abc")
    assert len({tuple(names(seed)) for seed in range(40)}) > 10


def test_every_foe_is_well_formed():
    assert len(FOES) == 18 and len(ROSTER) == 16
    for spec in FOES.values():
        assert spec.hp > 0 and spec.damage > 0 and spec.tell
        assert all(trait in TRAITS for trait in spec.traits)
        assert spec.full_name.startswith(spec.name)
        foe = spec.spawn(random.Random(0))
        assert foe.hp == foe.max_hp == spec.hp and foe.traits == spec.traits
    assert WARDEN.full_name == "The Warden"
    assert [len([s for s in ROSTER if s.tier == t]) for t in (1, 2, 3, 4)] == [4, 4, 4, 4]


@pytest.mark.parametrize("key", sorted(FOES))
def test_every_mind_throws_legal_moves_and_is_seeded(key):
    mine, theirs = spar(key, randomly, rounds=40, climb=(R, P, S) * 5)
    assert set(theirs) <= set(MOVES)
    assert spar(key, randomly, rounds=40, climb=(R, P, S) * 5) == (mine, theirs)


def test_later_tiers_are_tougher():
    hp = {tier: [s.hp for s in ROSTER if s.tier == tier] for tier in (1, 2, 3, 4)}
    assert max(hp[1]) <= min(hp[2]) <= min(hp[3])
    assert all(s.damage == 3 for s in ROSTER if s.tier == 4) and ORACLE.damage == 3
    assert ORACLE.hp > WARDEN.hp >= max(hp[3])


# -- each tell is the truth ---------------------------------------------------------------

def test_pebble_believes_in_rock():
    _, theirs = spar("pebble", randomly, rounds=200)
    assert Counter(theirs)[R] > 130


def test_loop_and_tempo_keep_time():
    _, theirs = spar("loop", randomly, rounds=12)
    assert all(b is a.beaten_by for a, b in pairwise(theirs))                 # R -> P -> S -> R
    _, theirs = spar("tempo", randomly, rounds=24)
    assert all(theirs[i] is theirs[i + 6] for i in range(18))
    assert Counter(theirs) == {R: 8, P: 8, S: 8}


def test_parrot_copies_and_is_beaten_by_stepping_up():
    mine, theirs = spar("parrot", randomly)
    assert theirs[1:] == mine[:-1]
    mine, theirs = spar("parrot", lambda mine, theirs, rng: mine[-1].beaten_by if mine else R)
    assert wins(mine, theirs) >= 59


def test_flip_never_repeats_itself():
    _, theirs = spar("flip", randomly, rounds=100)
    assert all(a is not b for a, b in pairwise(theirs))


def test_grudge_stays_on_a_win_and_counters_after_a_loss():
    mine, theirs = spar("grudge", randomly, rounds=100)
    for i in range(1, 100):
        before = judge(theirs[i - 1], mine[i - 1])
        if before is Outcome.WIN:
            assert theirs[i] is theirs[i - 1]
        elif before is Outcome.LOSS:
            assert theirs[i] is mine[i - 1].beaten_by


def test_echo_expects_a_repeat_and_is_beaten_by_stepping_down():
    mine, theirs = spar("echo", randomly)
    assert all(theirs[i] is mine[i - 1].beaten_by for i in range(1, 60))
    mine, theirs = spar("echo", lambda mine, theirs, rng: mine[-1].beats if mine else R)
    assert wins(mine, theirs) >= 59


def test_brick_hides_behind_paper():
    _, theirs = spar("brick", randomly, rounds=200)
    assert Counter(theirs)[P] > 115 and "armor" in FOES["brick"].traits


def test_fang_repeats_a_winner_otherwise_copies():
    mine, theirs = spar("fang", randomly, rounds=100)
    for i in range(1, 100):
        if judge(theirs[i - 1], mine[i - 1]) is Outcome.WIN:
            assert theirs[i] is theirs[i - 1]
        else:
            assert theirs[i] is mine[i - 1]


def test_blitz_reaches_for_rock_when_cornered():
    _, calm = spar("blitz", randomly, rounds=300)
    _, cornered = spar("blitz", randomly, rounds=300, hurt=True)
    assert Counter(cornered)[R] > Counter(calm)[R] + 40 and Counter(cornered)[R] > 220


def test_slick_usually_loses_to_a_repeat():
    mine, theirs = spar("slick", lambda *_: R, rounds=200)
    assert 150 < wins(mine, theirs) < 195                  # mostly, not always


def test_mirage_counters_your_most_used_throw():
    _, theirs = spar("mirage", lambda *_: S, rounds=30)
    assert theirs[1:] == [R] * 29


def test_vex_changes_face_every_third_throw():
    mine, theirs = spar("vex", randomly, rounds=90)
    for i in range(1, 90):
        last = mine[i - 1]
        expected = (last, last.beaten_by, last.beats)[(i // 3) % 3]
        assert theirs[i] is expected


def test_the_studious_foes_arrive_already_knowing_your_habits():
    climb = (R,) * 40
    for key in ("warden", "sage", "cipher"):
        _, theirs = spar(key, lambda *_: R, rounds=10, climb=climb)
        assert Counter(theirs)[P] >= 7, key                # countering rock from the first throw


def test_the_oracle_punishes_a_habit_carried_up_the_tower():
    climb = (R, P, S) * 12
    mine, theirs = spar("oracle", lambda mine, theirs, rng: MOVES[len(mine) % 3], rounds=30,
                        climb=climb)
    losses = sum(judge(a, b) is Outcome.LOSS for a, b in zip(mine, theirs))
    assert losses >= 24


def test_wraith_has_no_pattern_to_find():
    _, theirs = spar("wraith", randomly, rounds=600)
    assert all(150 < n < 250 for n in Counter(theirs).values())
