import datetime
import random

import pytest

from rps_game.engine import MOVES, Move
from rps_game.gauntlet.foes import FLOORS
from rps_game.gauntlet.relics import RELICS
from rps_game.gauntlet.rules import START_HP, Technique
from rps_game.gauntlet.run import (FLAWLESS_POINTS, FLOOR_POINTS, HEAL_AFTER_FIGHT, HP_POINTS,
                                   REST_HEAL, VICTORY_POINTS, Run, daily_seed, random_seed)

R, P, S = Move.ROCK, Move.PAPER, Move.SCISSORS


def win_fight(run, technique=None):
    """Win the current fight by reading the foe's mind (tests are allowed to cheat)."""
    duel = run.begin_fight()
    first = True
    while not duel.over:
        use = technique if first and technique and duel.can_use(technique) else None
        duel.resolve(duel.intent.beaten_by, use)
        first = False
    return run.end_fight()


def lose_fight(run):
    duel = run.begin_fight()
    while not duel.over:
        duel.resolve(duel.intent.beats)
    return run.end_fight()


def test_a_perfect_run_conquers_the_tower():
    run = Run(seed="perfect")
    reports = []
    while not run.over:
        reports.append(win_fight(run))
        if not run.over:
            run.take(run.rewards()[0].key)
    assert run.victory and run.over and run.floors_cleared == FLOORS and run.fallen_to is None
    assert [r.floor for r in reports] == list(range(1, 11))
    assert all(r.won and r.flawless for r in reports)
    assert run.tally.flawless == 10 and run.tally.losses == 0 and run.tally.damage_taken == 0
    assert len(run.hero.relics) == 9
    floors = FLOOR_POINTS * sum(range(1, 11)) + FLAWLESS_POINTS * 10
    assert run.score == floors + VICTORY_POINTS + HP_POINTS * run.hero.hp
    assert run.bare_hands
    assert len(run.climb) == run.tally.rounds == run.tally.wins
    with pytest.raises(ValueError):
        run.begin_fight()


def test_the_same_seed_is_the_same_tower_and_the_same_rewards():
    def climb(seed):
        run, seen = Run(seed=seed), []
        for _ in range(3):
            win_fight(run)
            offers = [relic.key for relic in run.rewards()]
            seen.append((run.foe.key, offers))
            run.take(offers[0])
        return [s.key for s in run.ladder], seen

    assert climb("twin") == climb("twin")
    assert climb("twin") != climb("other")


def test_rewards_do_not_depend_on_how_the_fight_went():
    a, b = Run(seed="fair"), Run(seed="fair")
    win_fight(a)
    duel = b.begin_fight()                                 # the same fight, played badly first
    for _ in range(3):
        duel.resolve(duel.intent.beats)
    while not duel.over:
        duel.resolve(duel.intent.beaten_by)
    b.end_fight()
    assert [r.key for r in a.rewards()] == [r.key for r in b.rewards()]


def test_falling_ends_the_run_where_it_stands():
    run = Run(seed="fall")
    win_fight(run)
    report = lose_fight(run)
    assert not report.won and report.points == 0
    assert run.over and not run.victory and run.fallen_to == run.ladder[1].key
    assert run.floor == 2 and run.floors_cleared == 1
    assert run.score == FLOOR_POINTS + FLAWLESS_POINTS
    assert run.tally.losses > 0 and run.tally.damage_taken >= START_HP


def test_healing_after_a_fight_and_resting():
    run = Run(seed="heal")
    run.hero.hp = 5
    report = win_fight(run)
    assert report.healed == HEAL_AFTER_FIGHT and run.hero.hp == 8
    assert run.rest() == REST_HEAL and run.hero.hp == 13
    assert run.rest() == 1 and run.hero.hp == run.hero.max_hp          # never above the maximum
    run.hero.relics.append("medic")
    run.hero.hp = 4
    assert win_fight(run).healed == HEAL_AFTER_FIGHT + 2


def test_relics_that_change_the_hero_when_taken():
    run = Run(seed="relics")
    run.hero.hp = 6
    assert run.take("heart") is RELICS["heart"]
    assert (run.hero.max_hp, run.hero.hp) == (START_HP + 4, 10)
    run.take("reservoir")
    assert run.hero.max_focus == 6
    with pytest.raises(ValueError):
        run.take("heart")
    run.take("trophy")
    report = win_fight(run)
    assert run.hero.max_hp == START_HP + 5 and "Trophy Belt: +1 maximum HP" in report.notes


def test_a_technique_spoils_bare_hands_but_only_in_the_first_five_floors():
    run = Run(seed="hands")
    for _ in range(5):
        win_fight(run)
        run.take(run.rewards()[0].key)
    assert run.bare_hands and run.clean_floors == 5
    win_fight(run, Technique.GUARD)
    assert run.bare_hands

    run = Run(seed="hands")
    win_fight(run, Technique.GUARD)
    for _ in range(5):
        run.take(run.rewards()[0].key)
        win_fight(run)
    assert not run.bare_hands and run.clean_floors == 0 and run.tally.techniques == 1


def test_abandoning_keeps_what_was_played():
    run = Run(seed="quit")
    win_fight(run)
    duel = run.begin_fight()
    duel.resolve(duel.intent.beaten_by)
    duel.resolve(duel.intent)
    before = run.tally.rounds
    run.abandon()
    assert run.over and run.abandoned and not run.victory and run.fallen_to is None
    assert run.tally.rounds == before + 2 and run.tally.draws == 1 and run.duel is None
    run.abandon()                                          # harmless twice
    assert run.tally.rounds == before + 2


def test_lowest_hp_win_is_remembered():
    run = Run(seed="thread")
    run.hero.hp = 1
    win_fight(run)
    assert run.tally.lowest_hp_win == 1
    win_fight(run)
    assert run.tally.lowest_hp_win == 1


def test_end_fight_needs_a_finished_fight():
    run = Run(seed="x")
    with pytest.raises(ValueError):
        run.end_fight()
    run.begin_fight()
    with pytest.raises(ValueError):
        run.end_fight()


def test_seeds():
    assert daily_seed(datetime.date(2026, 11, 17)) == "2026-11-17"
    assert daily_seed() == datetime.date.today().isoformat()
    seeds = {random_seed() for _ in range(50)}
    assert len(seeds) > 45 and all(len(s) == 6 and s == s.upper() for s in seeds)


def test_random_play_rarely_reaches_the_top_but_reading_the_foes_does():
    """A guard on the balance: the tower must be neither a coin flip nor a wall."""
    rng = random.Random(0)
    cleared = []
    for seed in range(150):
        run = Run(seed=f"balance-{seed}")
        while not run.over:
            duel = run.begin_fight()
            while not duel.over:
                duel.resolve(rng.choice(MOVES))
            if run.end_fight().won and not run.over:
                run.take(run.rewards()[0].key)
        cleared.append(run.floors_cleared)
    assert sum(c == FLOORS for c in cleared) <= 20          # blind luck rarely gets there
    assert 2.0 < sum(cleared) / len(cleared) < 5.5          # but it does get somewhere
