import json

from rps_game import profile as store
from rps_game.engine import Outcome, Score
from rps_game.gauntlet.run import Run
from rps_game.profile import (ACHIEVEMENTS, BESTIARY_SIZE, MAX_RIVALS, RANKS, Gains, Profile, Rival,
                              record_classic, record_online, record_run)
from test_gauntlet_run import lose_fight, win_fight

ALICE, BOB = "a" * 32, "b" * 32


def names(gains):
    return {a.key for a in gains.unlocked}


def conquer(seed="top", daily=None):
    run = Run(seed=seed, daily=daily)
    while not run.over:
        win_fight(run)
        if not run.over:
            run.take(run.rewards()[0].key)
    return run


# -- rank ------------------------------------------------------------------------------

def test_ranks_rise_with_experience():
    p = Profile()
    assert p.rank == "Novice" and p.next_rank == ("Apprentice", 100)
    p.xp = 100
    assert p.rank == "Apprentice"
    p.xp = 2999
    assert p.rank == "Tactician" and p.next_rank == ("Mind Reader", 1)
    assert p.rank_line() == "Rank: Tactician (2999 XP, 1 XP to Mind Reader)"
    p.xp = 10 ** 6
    assert p.rank == RANKS[-1][1] == "Legend" and p.next_rank is None
    assert "the highest rank" in p.rank_line()


def test_an_achievement_unlocks_once():
    p = Profile()
    first = p.unlock("first_win")
    assert first.name == "First Blood" and p.achievements["first_win"]
    assert p.unlock("first_win") is None and p.unlock("no-such-thing") is None
    assert len({a.key for a in ACHIEVEMENTS}) == len(ACHIEVEMENTS)


# -- classic games -----------------------------------------------------------------------

def test_classic_games_earn_more_against_better_opponents():
    session = Score(wins=4, losses=3, draws=2, best_streak=2)
    easy = record_classic(Profile(), difficulty="easy", session=session)
    oracle = record_classic(Profile(), difficulty="oracle", session=session)
    assert easy.xp == 2 * 1 * 4 + 2 and oracle.xp == 2 * 5 * 4 + 2
    assert names(easy) == {"first_win"}


def test_streak_and_volume_achievements():
    p = Profile()
    gains = record_classic(p, difficulty="easy", session=Score(wins=10, losses=85, best_streak=10))
    assert {"streak5", "streak10"} <= names(gains) and "hundred" not in names(gains)
    gains = record_classic(p, difficulty="easy", session=Score(losses=5))
    assert names(gains) == {"hundred"} and p.rounds == 100 and gains.xp == 0


def test_beating_the_readers_needs_a_real_game():
    short = Score(wins=5, losses=1)
    assert "hard" not in names(record_classic(Profile(), difficulty="hard", session=short))
    long = Score(wins=6, losses=4)
    assert "hard" in names(record_classic(Profile(), difficulty="hard", session=long))
    assert "oracle" not in names(record_classic(Profile(), difficulty="oracle", session=long))
    longer = Score(wins=7, losses=5, draws=3)
    assert "oracle" in names(record_classic(Profile(), difficulty="oracle", session=longer))
    behind = Score(wins=5, losses=7, draws=3)
    assert "oracle" not in names(record_classic(Profile(), difficulty="oracle", session=behind))


def test_poker_face_comes_from_the_mind_reader():
    class Reading:
        rounds, verdict = 20, "Unreadable"

    gains = record_classic(Profile(), difficulty="easy", session=Score(draws=20),
                           insight=Reading())
    assert "poker_face" in names(gains)
    Reading.rounds = 10
    gains = record_classic(Profile(), difficulty="easy", session=Score(draws=10),
                           insight=Reading())
    assert "poker_face" not in names(gains)


def test_promotion_is_announced():
    p = Profile(xp=95)
    gains = record_classic(p, difficulty="normal", session=Score(wins=2))
    assert gains.promoted_to == "Apprentice" and p.xp == 103
    lines = gains.lines()
    assert lines[0] == "+8 XP. Rank: Apprentice (103 XP, 197 XP to Scrapper)"
    assert "Promoted to Apprentice!" in lines
    assert "Achievement unlocked: First Blood - Win a round." in lines
    assert Gains().lines() == []


# -- the Gauntlet -------------------------------------------------------------------------

def test_conquering_the_gauntlet_fills_the_trophy_cabinet():
    p = Profile()
    run = conquer()
    gains = record_run(p, run)
    assert {"gauntlet_first", "warden", "summit", "flawless", "collector", "bare_hands",
            "first_win", "streak5", "streak10"} <= names(gains)
    assert gains.new_best and gains.xp == run.score // 8 and "New best score!" in gains.lines()
    assert (p.runs, p.victories, p.best_floors, p.best_score) == (1, 1, 10, run.score)
    assert len(p.foes_beaten) == 10 and p.rounds == run.tally.rounds
    assert "daily" not in names(gains) and "bestiary" not in names(gains)


def test_a_short_run_still_counts():
    p = Profile(best_score=5000)
    run = Run(seed="short")
    win_fight(run)
    lose_fight(run)
    gains = record_run(p, run)
    assert not gains.new_best and p.best_score == 5000
    assert (p.runs, p.victories, p.best_floors) == (1, 0, 1)
    assert "gauntlet_first" in names(gains) and "summit" not in names(gains)


def test_by_a_thread():
    run = Run(seed="thread")
    run.hero.hp = 1
    win_fight(run)
    run.abandon()
    assert "thread" in names(record_run(Profile(), run))


def test_the_bestiary_fills_up_across_runs():
    p = Profile()
    seed = 0
    while len(p.foes_beaten) < BESTIARY_SIZE and seed < 200:
        gains = record_run(p, conquer(f"zoo-{seed}"))
        seed += 1
    assert len(p.foes_beaten) == BESTIARY_SIZE == len(set(p.foes_beaten))
    assert "bestiary" in names(gains)


def test_daily_runs_keep_the_best_score_of_the_day():
    p = Profile()
    run = conquer("2026-11-17", daily="2026-11-17")
    gains = record_run(p, run)
    assert "daily" in names(gains) and (p.daily_date, p.daily_score) == ("2026-11-17", run.score)
    worse = Run(seed="2026-11-17", daily="2026-11-17")
    win_fight(worse)
    lose_fight(worse)
    record_run(p, worse)
    assert p.daily_score == run.score                      # a worse attempt changes nothing
    tomorrow = Run(seed="2026-11-18", daily="2026-11-18")
    win_fight(tomorrow)
    lose_fight(tomorrow)
    record_run(p, tomorrow)
    assert (p.daily_date, p.daily_score) == ("2026-11-18", tomorrow.score)
    walked = Run(seed="2026-11-19", daily="2026-11-19")
    win_fight(walked)
    walked.abandon()
    record_run(p, walked)
    assert p.daily_date == "2026-11-18"                    # an abandoned Daily is not a result


# -- online games ----------------------------------------------------------------------------

def test_head_to_head_follows_the_person_not_the_name():
    p = Profile()
    gains = record_online(p, opponent_id=BOB, opponent_name="Bob", outcome=Outcome.WIN,
                          session=Score(wins=3, losses=1, draws=2))
    assert "friend" in names(gains) and gains.xp == 6 * 3 + 2 * 2 + 25
    record_online(p, opponent_id=BOB, opponent_name="Robert", outcome=Outcome.LOSS,
                  session=Score(wins=0, losses=2))
    record_online(p, opponent_id=BOB, opponent_name="Robert", outcome=Outcome.DRAW,
                  session=Score(wins=1, losses=1))
    rival = p.rivals[BOB]
    assert rival.name == "Robert" and rival.games == 3
    assert (rival.games_won, rival.games_lost, rival.games_tied) == (1, 1, 1)
    assert (rival.rounds_won, rival.rounds_lost, rival.rounds_drawn) == (4, 4, 2)
    assert rival.last_played


def test_an_unfinished_online_game_is_noted_but_is_not_a_result():
    p = Profile()
    gains = record_online(p, opponent_id=BOB, opponent_name="Bob", outcome=None,
                          session=Score(wins=1))
    assert "friend" not in names(gains) and p.rivals[BOB].games == 0
    assert p.rivals[BOB].rounds_won == 1


def test_rivals_are_capped_and_bad_ids_ignored():
    p = Profile()
    record_online(p, opponent_id="not-an-id", opponent_name="Eve", outcome=Outcome.WIN,
                  session=Score(wins=1))
    assert p.rivals == {}
    for i in range(MAX_RIVALS + 5):
        record_online(p, opponent_id=f"{i:032x}", opponent_name=f"P{i}", outcome=Outcome.WIN,
                      session=Score(wins=1))
    assert len(p.rivals) == MAX_RIVALS and f"{0:032x}" not in p.rivals
    record_online(p, opponent_id=f"{10:032x}", opponent_name="P10", outcome=Outcome.WIN,
                  session=Score(wins=1))
    assert list(p.rivals)[-1] == f"{10:032x}"              # most recent rival is kept last


# -- the file -----------------------------------------------------------------------------------

def test_roundtrip_and_reset():
    p = Profile(xp=321, rounds=12, runs=2, victories=1, best_floors=10, best_score=6000,
                foes_beaten=["pebble", "oracle"], daily_date="2026-11-17", daily_score=900,
                rivals={BOB: Rival(name="Bob", games_won=2, last_played="2026-11-17")})
    p.unlock("summit")
    assert store.save(p)
    assert store.load() == p
    assert store.profile_path().name == "profile.json"
    assert store.reset() and store.load() == Profile()
    assert store.reset()                                   # nothing to delete is fine


def test_a_damaged_file_is_read_as_far_as_it_makes_sense():
    store.profile_path().write_text("{ not json")
    assert store.load() == Profile()
    data = {
        "xp": -5, "rounds": "many", "runs": True, "best_score": 70,
        "achievements": {"summit": "2026-01-01", "made_up": "2026-01-01", "hard": 7},
        "foes_beaten": ["pebble", "pebble", 3, "loop"],
        "rivals": {BOB: {"name": "B" * 90, "games_won": 2, "games_lost": -1}, "bad": {}, ALICE: 5},
        "daily_date": 20261117,
    }
    p = Profile.from_dict(data)
    assert (p.xp, p.rounds, p.runs, p.best_score) == (0, 0, 0, 70)
    assert p.achievements == {"summit": "2026-01-01"}
    assert p.foes_beaten == ["pebble", "loop"] and p.daily_date == ""
    assert list(p.rivals) == [BOB] and len(p.rivals[BOB].name) == 40
    assert (p.rivals[BOB].games_won, p.rivals[BOB].games_lost) == (2, 0)
    assert Profile.from_dict([1, 2]) == Profile()
    json.dumps(p.to_dict())                                # always serialisable
