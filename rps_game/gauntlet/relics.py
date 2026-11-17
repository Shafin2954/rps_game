"""Relics: the rewards picked up between fights.

A relic is only a name and a sentence here; what it *does* lives in
``rules.Duel`` (during a fight) and ``run.Run`` (between fights), looked up by
key. Keeping the catalogue separate means the screens can describe a relic
without knowing any rules.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class Relic:
    key: str
    name: str
    text: str


_ALL = (
    # -- signature throws
    Relic("granite", "Granite Knuckles", "Rock wins deal +2 damage."),
    Relic("origami", "Origami Armour", "Paper wins give you 2 Shield for this fight."),
    Relic("whetstone", "Whetstone", "Scissors wins deal +1 damage and give 1 Focus."),
    # -- offence
    Relic("momentum", "Momentum", "Each win in a row deals +1 more damage (up to +3)."),
    Relic("gambit", "Opening Gambit", "Your first win in every fight deals double damage."),
    Relic("executioner", "Executioner", "+2 damage against a foe at half health or less."),
    Relic("counterpunch", "Counterpunch", "After losing a round, your next win deals +2 damage."),
    Relic("gloves", "Heavy Gloves", "All wins deal +1 damage, but you start fights with 1 less Focus."),
    Relic("glass", "Glass Cannon", "Your wins deal +2 damage. Every hit on you deals +1."),
    # -- defence
    Relic("skin", "Thick Skin", "Every hit on you deals 1 less damage (at least 1)."),
    Relic("wind", "Second Wind", "Once per fight, a hit that would finish you leaves you on 1 HP."),
    Relic("medic", "Field Medic", "Heal 2 more HP after every fight."),
    Relic("heart", "Iron Heart", "+4 maximum HP, and heal 4 HP now."),
    Relic("coin", "Lucky Coin", "One loss in four is turned into a draw."),
    Relic("trophy", "Trophy Belt", "+1 maximum HP after every fight you win."),
    # -- draws
    Relic("static", "Static Charge", "Draws deal 1 damage to the foe, straight through armour."),
    Relic("meditation", "Meditation", "Draws give 2 Focus instead of 1."),
    # -- focus
    Relic("breath", "Deep Breath", "Start every fight with 2 more Focus."),
    Relic("eye", "Third Eye", "Foresight costs 1 less Focus."),
    Relic("reservoir", "Reservoir", "+2 maximum Focus."),
    Relic("adrenaline", "Adrenaline", "Winning a round at half health or less gives 1 Focus."),
    # -- knowledge
    Relic("spyglass", "Spyglass", "See the foe's opening throw in every fight."),
)

RELICS: dict[str, Relic] = {relic.key: relic for relic in _ALL}


def offer(rng: random.Random, owned: Iterable[str], count: int = 3) -> list[Relic]:
    """``count`` different relics the player doesn't have yet (fewer if they own most)."""
    have = set(owned)
    pool = [relic for relic in _ALL if relic.key not in have]
    return rng.sample(pool, min(count, len(pool)))
