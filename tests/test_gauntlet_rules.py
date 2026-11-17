import random

import pytest

from rps_game.engine import MOVES, Move, Outcome
from rps_game.gauntlet.relics import RELICS, offer
from rps_game.gauntlet.rules import (BASE_DAMAGE, COSTS, START_FOCUS, START_HP, TRAITS, Duel, Foe,
                                     Hero, Technique)

R, P, S = Move.ROCK, Move.PAPER, Move.SCISSORS
F, G, C = Technique.FORESIGHT, Technique.GUARD, Technique.CHARGE


class Script:
    """A foe that throws a fixed sequence (the last throw repeats)."""

    def __init__(self, *moves):
        self._moves = moves
        self.sights = []

    def choose(self, sight):
        self.sights.append(sight)
        return self._moves[min(len(sight.mine), len(self._moves) - 1)]


def duel(*foe_moves, relics=(), traits=(), hp=20, damage=2, hero_hp=START_HP, focus=None,
         seed=0, climb=()):
    hero = Hero(hp=hero_hp, relics=list(relics))
    if "reservoir" in relics:
        hero.max_focus += 2
    d = Duel(hero, Foe("Dummy", hp, damage, Script(*foe_moves), tuple(traits)),
             rng=random.Random(seed), climb=climb)
    if focus is not None:
        hero.focus = focus
    return d


# -- the basics --------------------------------------------------------------------

def test_a_win_deals_damage_a_loss_takes_it_a_draw_gives_focus():
    d = duel(S, P, R)
    x = d.resolve(R)
    assert x.round.outcome is Outcome.WIN and x.dealt == BASE_DAMAGE and d.foe.hp == 18
    x = d.resolve(R)
    assert x.round.outcome is Outcome.LOSS and x.taken == 2 and d.hero.hp == START_HP - 2
    assert d.hero.focus == START_FOCUS + 1                 # losing earns Focus
    x = d.resolve(R)
    assert x.round.outcome is Outcome.DRAW and x.dealt == x.taken == 0
    assert d.hero.focus == START_FOCUS + 2
    assert [e.number for e in d.exchanges] == [1, 2, 3] and d.round_number == 4


def test_focus_is_capped():
    d = duel(R)
    for _ in range(10):
        d.resolve(R)
    assert d.hero.focus == d.hero.max_focus


def test_the_fight_ends_when_someone_drops_and_then_refuses_more_rounds():
    d = duel(S, hp=4)
    d.resolve(R)
    assert not d.over
    d.resolve(R)
    assert d.over and d.won and d.flawless
    with pytest.raises(ValueError):
        d.resolve(R)

    d = duel(P, hero_hp=2)
    d.resolve(R)
    assert d.over and not d.won and not d.flawless and d.hero.hp == 0


def test_the_foe_sees_only_the_past():
    d = duel(R, R, R, climb=(S, S))
    d.resolve(P)
    d.resolve(S)
    assert d.intent is R                                               # deciding round 3
    script = d.foe.mind
    assert script.sights[0].theirs == () and script.sights[0].climb == (S, S)
    assert script.sights[2].theirs == (P, S) and script.sights[2].mine == (R, R)
    assert script.sights[2].results == (Outcome.LOSS, Outcome.WIN)     # from the foe's side
    assert len(script.sights) == 3                                     # asked once per round


def test_hurt_is_half_health_or_less():
    foe = Foe("x", 9, 2, Script(R))
    assert not foe.hurt
    foe.hp = 4
    assert foe.hurt


# -- techniques ----------------------------------------------------------------------

def test_guard_blocks_the_hit_and_costs_focus():
    d = duel(P, focus=2)
    x = d.resolve(R, G)
    assert x.taken == 0 and x.blocked == 2 and d.hero.hp == START_HP
    assert d.hero.focus == 2 - COSTS[G] + 1 and "Guard blocks 2" in x.notes
    assert d.damage_taken == 0


def test_charge_doubles_a_win_and_is_wasted_otherwise():
    d = duel(S, R, focus=4)
    assert d.resolve(R, C).dealt == 2 * BASE_DAMAGE
    x = d.resolve(R, C)                                    # a draw: the Focus is gone anyway
    assert x.dealt == 0 and d.hero.focus == 0 + 1


def test_techniques_need_focus():
    d = duel(S, focus=1)
    assert d.can_use(G) and not d.can_use(C) and not d.can_use(F)
    with pytest.raises(ValueError):
        d.resolve(R, C)
    with pytest.raises(ValueError):
        d.foresee()
    with pytest.raises(ValueError):
        d.resolve(R, F)                                    # Foresight must be asked for first
    assert d.hero.focus == 1 and not d.exchanges


@pytest.mark.parametrize("seed", range(12))
def test_foresight_never_rules_out_the_real_throw(seed):
    d = duel(P, S, R, focus=4, seed=seed)
    for _ in range(2):
        ruled_out = d.foresee()
        assert ruled_out is not d.intent and ruled_out in MOVES
        assert d.foresee() is ruled_out                    # asking again is free and consistent
        d.resolve(R, F)
    assert d.hero.focus <= 4 - 2 * COSTS[F] + 2


def test_third_eye_makes_foresight_cheaper():
    d = duel(S, relics=["eye"], focus=1)
    assert d.cost(F) == 1 and d.can_use(F)
    d.foresee()
    assert d.hero.focus == 0


# -- relics --------------------------------------------------------------------------

def test_signature_throw_relics():
    d = duel(S, R, P, relics=["granite", "origami", "whetstone"], focus=0)
    assert d.resolve(R).dealt == BASE_DAMAGE + 2           # granite
    x = d.resolve(P)                                       # origami
    assert x.dealt == BASE_DAMAGE and d.hero.shield == 2
    x = d.resolve(S)                                       # whetstone
    assert x.dealt == BASE_DAMAGE + 1 and d.hero.focus == 1


def test_shield_soaks_damage_and_resets_between_fights():
    d = duel(R, S, relics=["origami"], damage=3)
    d.resolve(P)
    x = d.resolve(P)
    assert x.blocked == 2 and x.taken == 1 and d.hero.shield == 0
    hero = d.hero
    hero.shield = 5
    Duel(hero, Foe("next", 5, 2, Script(R)))
    assert hero.shield == 0


def test_momentum_builds_and_breaks():
    d = duel(S, S, S, S, S, P, S, relics=["momentum"], hp=99)
    assert [d.resolve(R).dealt for _ in range(5)] == [2, 3, 4, 5, 5]      # capped at +3
    d.resolve(R)                                                          # a loss
    assert d.resolve(R).dealt == 2


def test_opening_gambit_only_doubles_the_first_win():
    d = duel(R, S, S, relics=["gambit"], hp=99)
    d.resolve(R)                                           # a draw does not use it up
    assert [d.resolve(R).dealt, d.resolve(R).dealt] == [4, 2]


def test_executioner_and_counterpunch():
    d = duel(S, relics=["executioner"], hp=8)
    assert [d.resolve(R).dealt for _ in range(3)] == [2, 2, 4]            # 8 -> 6 -> 4 (hurt) -> 0
    d = duel(P, S, S, relics=["counterpunch"], hp=99)
    d.resolve(R)
    assert [d.resolve(R).dealt, d.resolve(R).dealt] == [4, 2]


def test_gloves_and_glass_cannon_cut_both_ways():
    d = duel(S, P, relics=["gloves", "glass"])
    assert d.hero.focus == 0                               # gloves: one Focus fewer
    assert d.resolve(R).dealt == BASE_DAMAGE + 1 + 2
    assert d.resolve(R).taken == 2 + 1                     # glass: hits hurt more


def test_thick_skin_never_reduces_a_hit_to_nothing():
    d = duel(P, relics=["skin"], damage=3)
    assert d.resolve(R).taken == 2
    d = duel(P, relics=["skin"], damage=1)
    assert d.resolve(R).taken == 1


def test_second_wind_saves_you_once_per_fight():
    d = duel(P, relics=["wind"], hero_hp=2, damage=5)
    x = d.resolve(R)
    assert d.hero.hp == 1 and x.taken == 1 and "Second Wind keeps you standing" in x.notes
    d.resolve(R)
    assert d.hero.hp == 0 and d.over and not d.won


def test_lucky_coin_turns_some_losses_into_draws():
    saved = 0
    for seed in range(200):
        d = duel(P, relics=["coin"], seed=seed)
        x = d.resolve(R)
        if x.round.outcome is Outcome.DRAW:
            saved += 1
            assert x.taken == 0 and d.hero.focus == START_FOCUS + 1
    assert 25 <= saved <= 75                               # about one in four


def test_draw_relics():
    d = duel(R, relics=["static", "meditation"], traits=["armor"], focus=0)
    x = d.resolve(R)
    assert x.dealt == 1 and d.foe.hp == 19 and d.hero.focus == 2          # armour does not stop it


def test_focus_relics():
    assert duel(R, relics=["breath"]).hero.focus == START_FOCUS + 2
    d = duel(R, relics=["reservoir", "breath"])
    assert d.hero.max_focus == 6 and d.hero.focus == 3
    d = duel(S, relics=["adrenaline"], hero_hp=7, focus=0)
    d.resolve(R)
    assert d.hero.focus == 1
    d = duel(S, relics=["adrenaline"], hero_hp=8, focus=0)                # above half: nothing
    d.resolve(R)
    assert d.hero.focus == 0


def test_spyglass_shows_the_opening_throw():
    assert duel(S).scouted is None
    d = duel(S, relics=["spyglass"])
    assert d.scouted is S and d.intent is S


# -- traits ----------------------------------------------------------------------------

def test_armour_soaks_one_but_a_hit_always_lands():
    d = duel(S, traits=["armor"])
    x = d.resolve(R)
    assert x.dealt == 1 and "Armour soaks 1" in x.notes
    d = duel(S, traits=["armor"], relics=["granite"], focus=2)
    assert d.resolve(R, C).dealt == (2 + 2) * 2 - 1


def test_leech_heals_only_when_wounded():
    d = duel(P, P, S, P, traits=["vampire"], hp=10)
    assert d.resolve(R).foe_healed == 0                    # already at full health
    d.resolve(S)                                           # hero wins: 10 -> 8
    d.resolve(S)                                           # draw
    x = d.resolve(R)
    assert x.foe_healed == 1 and d.foe.hp == 9


def test_enrage_and_heavy_rock_add_damage():
    d = duel(P, traits=["enrage"], hp=10)
    assert d.resolve(R).taken == 2
    d.foe.hp = 5
    assert d.resolve(R).taken == 3
    d = duel(R, P, traits=["heavy_rock"])
    assert d.resolve(S).taken == 4
    assert d.resolve(R).taken == 2


def test_thorns_sting_on_a_draw_unless_guarded():
    d = duel(R, traits=["thorns"], focus=1)
    assert d.resolve(R).taken == 1
    x = d.resolve(R, G)
    assert x.taken == 0 and x.blocked == 1


def test_overkill_is_not_counted():
    d = duel(S, hp=1, relics=["granite"])
    assert d.resolve(R).dealt == 1
    d = duel(P, hero_hp=1, damage=9)
    assert d.resolve(R).taken == 1 and d.damage_taken == 1


# -- the catalogue -----------------------------------------------------------------------

def test_every_trait_and_relic_is_described():
    assert all(name and text for name, text in TRAITS.values())
    assert all(r.name and r.text.endswith(".") for r in RELICS.values())
    assert len(RELICS) >= 20


def test_offers_are_distinct_unowned_and_seeded():
    first = offer(random.Random(1), ["granite"])
    assert len(first) == len({r.key for r in first}) == 3
    assert all(r.key != "granite" for r in first)
    assert first == offer(random.Random(1), ["granite"])
    nearly_all = [key for key in RELICS][:-2]
    assert len(offer(random.Random(1), nearly_all)) == 2
    assert offer(random.Random(1), list(RELICS)) == []
