"""Playing a Gauntlet run: the loop between the rules, the screens and the profile."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .. import profile as profile_store
from ..profile import Gains
from ..ui import GameUI
from .run import Run, daily_seed, random_seed
from .screens import GauntletScreens

MAX_SEED_CELLS = 16


@dataclass(frozen=True)
class GauntletConfig:
    """What kind of run to start: today's Daily, a given seed, or a fresh random one."""

    seed: Optional[str] = None
    daily: bool = False


@dataclass
class RunResult:
    run: Run
    gains: Optional[Gains]
    interrupted: bool               # Ctrl-C / closed input: the player wants out entirely


def tidy_seed(text: str) -> str:
    """Seeds ignore case and outer spaces, so they survive being read aloud."""
    return " ".join(text.split()).upper()


def seed_error(text: str) -> Optional[str]:
    seed = tidy_seed(text)
    if not seed:
        return "A seed needs at least one character."
    if not seed.isprintable():
        return "Use letters, digits and ordinary punctuation."
    return None


def new_run(config: GauntletConfig) -> Run:
    if config.daily:
        today = daily_seed()
        return Run(seed=today, daily=today)
    return Run(seed=tidy_seed(config.seed) if config.seed else random_seed())


def _fight(screens: GauntletScreens, run: Run) -> None:
    """One floor: the fight, then (if it was won and there is more to climb) the reward."""
    screens.foe_card(run)
    duel = run.begin_fight()
    screens.begin_fight(run)
    try:
        while not duel.over:
            screens.begin_round(run)
            action = screens.ask_action(run)
            if action is None:
                run.abandon()
                return
            move, technique = action
            screens.show_exchange(run, duel.resolve(move, technique))
    finally:
        screens.end_fight()

    report = run.end_fight()
    if not report.won or run.victory:
        return
    pick = screens.choose_reward(run, report, run.rewards())
    if pick is None:
        run.abandon()
    elif pick == "rest":
        screens.reward_taken(f"You rest and heal {run.rest()} HP.")
    else:
        relic = run.take(pick)
        screens.reward_taken(f"You take {relic.name}: {relic.text}")


def play_gauntlet(ui: GameUI, config: Optional[GauntletConfig] = None, *, save: bool = True,
                  pause: bool = False) -> RunResult:
    """Play one run to its end and record it. ``pause`` keeps the summary up until a
    key is pressed (used when the player will return to the menu)."""
    run = new_run(config or GauntletConfig())
    screens = GauntletScreens(ui)
    interrupted = False
    try:
        screens.briefing(run)
        while not run.over:
            _fight(screens, run)
    except (KeyboardInterrupt, EOFError):
        interrupted = True
        run.abandon()
    finally:
        screens.end_fight()

    gains = None
    if save and run.tally.rounds:
        profile = profile_store.load()
        gains = profile_store.record_run(profile, run)
        profile_store.save(profile)
    screens.summary(run, gains.lines() if gains else (), pause=pause and not interrupted)
    return RunResult(run, gains, interrupted)
