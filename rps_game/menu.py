"""The start-up menu flow.

    Main menu -> Start Game -> Mode -> Single Player -> Difficulty -> Rounds
                                    -> Dual Player   -> Create / Join ...
                                    -> Gauntlet      -> New run / Daily Run / Enter a seed

``select_game`` walks that tree as a small state machine, so Esc steps back one
level at a time and picking "Exit" (or Esc on the main menu) returns None.
Multiplayer is listed but not playable yet.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Optional

from rich.align import Align
from rich.table import Table
from rich.text import Text

from . import profile as profile_store
from . import settings as settings_store
from . import stats as stats_store
from .dualsetup import DualSetup, setup_dual
from .gauntlet.foes import FLOORS
from .gauntlet.play import MAX_SEED_CELLS, GauntletConfig, seed_error
from .profile import ACHIEVEMENTS, BESTIARY_SIZE, Profile
from .ui import GameUI, Option

MAX_ROUNDS = 99

MAIN = [
    Option("Start Game", "start", "Pick a mode and play"),
    Option("Stats", "stats", "Your results, rank, achievements and preferences"),
    Option("Exit", "exit", "Quit RPS"),
]
MODES = [
    Option("Single Player", "single", "Play against the computer"),
    Option("Dual Player", "dual", "Play a friend online, on two devices"),
    Option("Gauntlet", "gauntlet", "Climb a tower of ten foes: read their tells, collect relics, "
                                   "face the Oracle"),
    Option("Multiplayer", "multi", "Play friends over the network", enabled=False,
           tag="coming soon"),
]
DIFFICULTIES = [
    Option("Easy", "easy", "The computer throws completely at random"),
    Option("Normal", "normal", "The computer counters your favourite moves"),
    Option("Hard", "hard", "The computer reads your patterns"),
    Option("Oracle", "oracle",
           "A council of predictors studies you. Only the unpredictable survive"),
]
ROUNDS = [
    Option("Unlimited rounds", "unlimited", "Keep playing until you quit"),
    Option("Choose number of rounds", "custom", f"Play 1-{MAX_ROUNDS} rounds; highest score wins"),
]


@dataclass(frozen=True)
class GameConfig:
    difficulty: str = "normal"
    best_of: Optional[int] = None      # first-to-majority match (CLI only)
    first_to: Optional[int] = None     # first to N wins (CLI; dual play later)
    rounds: Optional[int] = None       # fixed number of rounds; None = unlimited
    one_game: bool = False             # online play: one game, then the results screen


def profile_lines(profile: Profile) -> list[str]:
    """Rank, experience and Gauntlet records, as plain lines."""
    lines = [
        profile.rank_line(),
        f"Rounds played in all modes: {profile.rounds}",
        f"Achievements: {len(profile.achievements)} of {len(ACHIEVEMENTS)}",
        "",
        "The Gauntlet",
    ]
    if not profile.runs:
        lines.append("No runs yet. The tower is waiting.")
        return lines
    lines += [
        f"Runs: {profile.runs}   Conquered: {profile.victories}",
        f"Best climb: {profile.best_floors} of {FLOORS} floors   Best score: {profile.best_score}",
        f"Foes defeated at least once: {len(profile.foes_beaten)} of {BESTIARY_SIZE}",
    ]
    if profile.daily_date == datetime.date.today().isoformat():
        lines.append(f"Today's Daily Run: {profile.daily_score}")
    return lines


def show_profile(ui: GameUI, profile: Profile, *, wait: bool = True) -> None:
    ui.page("PROFILE", profile_lines(profile), wait=wait)


def show_achievements(ui: GameUI, profile: Profile, *, wait: bool = True) -> None:
    done = len(profile.achievements)
    title = f"ACHIEVEMENTS ({done} of {len(ACHIEVEMENTS)})"
    marked = [(f"[{'x' if a.key in profile.achievements else ' '}] {a.name}", a)
              for a in ACHIEVEMENTS]
    if ui.plain:
        ui.page(title, [f"{label}: {a.text}" for label, a in marked], wait=wait)
        return
    grid = Table.grid(padding=(0, 2))
    for label, a in marked:
        style = "green" if a.key in profile.achievements else "dim"
        grid.add_row(Text(label, style=style), Text(a.text, style=style))
    ui.page(title, [Align.center(grid)], wait=wait)


def show_head_to_head(ui: GameUI, profile: Profile, *, wait: bool = True) -> None:
    """Results against other players, most recent rival first."""
    rivals = list(reversed(profile.rivals.values()))
    if not rivals:
        ui.page("HEAD-TO-HEAD", ["No online games recorded yet.",
                                 "Play Dual Player with a friend to start a rivalry."], wait=wait)
        return
    if ui.plain:
        lines = []
        for r in rivals:
            lines.append(f"{r.name} (last played {r.last_played})")
            lines.append(f"Games: won {r.games_won}, lost {r.games_lost}, tied {r.games_tied}. "
                         f"Rounds: won {r.rounds_won}, lost {r.rounds_lost}, "
                         f"drawn {r.rounds_drawn}.")
        ui.page("HEAD-TO-HEAD", lines, wait=wait)
        return
    table = Table(box=ui._box(), header_style="bold", expand=False)
    table.add_column("Player")
    table.add_column("Games W-L-T", justify="center")
    table.add_column("Rounds W-L-D", justify="center")
    table.add_column("Last played", justify="center")
    for r in rivals[:12]:
        table.add_row(r.name, f"{r.games_won}-{r.games_lost}-{r.games_tied}",
                      f"{r.rounds_won}-{r.rounds_lost}-{r.rounds_drawn}", r.last_played)
    ui.page("HEAD-TO-HEAD", [Align.center(table)], wait=wait)


def reset_everything() -> bool:
    """Statistics, profile (rank, achievements, records) and head-to-head results."""
    return all([stats_store.reset(), profile_store.reset()])


def stats_menu(ui: GameUI) -> None:
    """Statistics, the profile, and the preference for showing stats after each game."""
    index = 0
    while True:
        prefs = settings_store.load()
        profile = profile_store.load()
        state = "On" if prefs.show_stats_after_game else "Off"
        options = [
            Option("Your statistics", "view", "Lifetime results against the computer"),
            Option("Profile", "profile", f"{profile.rank}: your rank and Gauntlet records"),
            Option("Achievements", "achievements",
                   f"{len(profile.achievements)} of {len(ACHIEVEMENTS)} unlocked"),
            Option("Head-to-head", "h2h", "Results against other players"),
            Option(f"Show stats after each game: {state}", "toggle",
                   "Also show your all-time totals on the results screen"),
            Option("Reset statistics", "reset",
                   "Delete all saved results, your rank and your achievements"),
        ]
        pick = ui.choose("Statistics", options, crumbs="Main menu", start=index)
        if pick is None:
            return
        index = next(i for i, o in enumerate(options) if o.value == pick)
        if pick == "view":
            ui.show_stats(stats_store.load(), wait=True)
        elif pick == "profile":
            show_profile(ui, profile)
        elif pick == "achievements":
            show_achievements(ui, profile)
        elif pick == "h2h":
            show_head_to_head(ui, profile)
        elif pick == "toggle":
            prefs.show_stats_after_game = not prefs.show_stats_after_game
            settings_store.save(prefs)
        elif pick == "reset" and ui.confirm(
                "Delete all saved statistics, your rank and your achievements?",
                crumbs="Statistics"):
            reset_everything()


def gauntlet_menu(ui: GameUI) -> Optional[GauntletConfig]:
    """New run / Daily Run / a seed. None means the player backed out."""
    crumbs = "Start Game > Gauntlet"
    while True:
        profile = profile_store.load()
        today = datetime.date.today().isoformat()
        daily = "Today's tower, the same for everyone"
        if profile.daily_date == today:
            daily += f" (your best today: {profile.daily_score})"
        best = f" Your best: {profile.best_score}." if profile.best_score else ""
        options = [
            Option("New run", "new", "A fresh tower of ten foes, drawn at random." + best),
            Option("Daily Run", "daily", daily),
            Option("Enter a seed", "seed", "Climb the very tower a friend told you about"),
        ]
        pick = ui.choose("The Gauntlet", options, crumbs="Start Game")
        if pick is None:
            return None
        if pick == "new":
            return GauntletConfig()
        if pick == "daily":
            return GauntletConfig(daily=True)
        seed = ui.ask_text("Enter the seed", crumbs=crumbs, validator=seed_error,
                           max_cells=MAX_SEED_CELLS)
        if seed is not None:
            return GauntletConfig(seed=seed)


def select_game(ui: GameUI) -> Optional[GameConfig | DualSetup | GauntletConfig]:
    """Run the menus. Returns the chosen setup, or None if the player exits."""
    state, difficulty = "main", "normal"
    while True:
        if state == "main":
            pick = ui.choose("Main menu", MAIN, back_label="exit")
            if pick in (None, "exit"):
                return None
            if pick == "stats":
                stats_menu(ui)
            else:
                state = "mode"
        elif state == "mode":
            pick = ui.choose("Select a mode", MODES, crumbs="Start Game")
            if pick is None:
                state = "main"
            elif pick == "single":
                state = "difficulty"
            elif pick == "dual":
                setup = setup_dual(ui)
                if setup is not None:
                    return setup
            elif pick == "gauntlet":
                run = gauntlet_menu(ui)
                if run is not None:
                    return run
        elif state == "difficulty":
            pick = ui.choose("Select difficulty", DIFFICULTIES,
                             crumbs="Start Game > Single Player")
            if pick is None:
                state = "mode"
            else:
                difficulty, state = pick, "rounds"
        elif state == "rounds":
            crumbs = "Start Game > Single Player > " + difficulty.capitalize()
            pick = ui.choose("How many rounds?", ROUNDS, crumbs=crumbs)
            if pick is None:
                state = "difficulty"
            elif pick == "unlimited":
                return GameConfig(difficulty=difficulty)
            else:
                count = ui.ask_number("Enter the number of rounds", 1, MAX_ROUNDS, crumbs=crumbs)
                if count is not None:
                    return GameConfig(difficulty=difficulty, rounds=count)
