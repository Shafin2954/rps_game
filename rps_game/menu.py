"""The start-up menu flow.

    Main menu -> Start Game -> Mode -> (Single Player) -> Difficulty -> Rounds

``select_game`` walks that tree as a small state machine, so Esc steps back one
level at a time and picking "Exit" (or Esc on the main menu) returns None.
Dual Player and Multiplayer are listed but not playable yet.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import settings as settings_store
from . import stats as stats_store
from .dualsetup import DualSetup, setup_dual
from .ui import GameUI, Option

MAX_ROUNDS = 99

MAIN = [
    Option("Start Game", "start", "Pick a mode and play"),
    Option("Stats", "stats", "Your results and preferences"),
    Option("Exit", "exit", "Quit RPS"),
]
MODES = [
    Option("Single Player", "single", "Play against the computer"),
    Option("Dual Player", "dual", "Play a friend online, on two devices"),
    Option("Multiplayer", "multi", "Play friends over the network", enabled=False,
           tag="coming soon"),
]
DIFFICULTIES = [
    Option("Easy", "easy", "The computer throws completely at random"),
    Option("Normal", "normal", "The computer counters your favourite moves"),
    Option("Hard", "hard", "The computer reads your patterns"),
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


def stats_menu(ui: GameUI) -> None:
    """Statistics and the preference for showing them after each game."""
    index = 0
    while True:
        prefs = settings_store.load()
        state = "On" if prefs.show_stats_after_game else "Off"
        options = [
            Option("Your statistics", "view", "Lifetime results against the computer"),
            Option("Head-to-head", "h2h", "Results against other players", enabled=False,
                   tag="coming soon"),
            Option(f"Show stats after each game: {state}", "toggle",
                   "Also show your all-time totals on the results screen"),
            Option("Reset statistics", "reset", "Delete all saved results"),
        ]
        pick = ui.choose("Statistics", options, crumbs="Main menu", start=index)
        if pick is None:
            return
        index = next(i for i, o in enumerate(options) if o.value == pick)
        if pick == "view":
            ui.show_stats(stats_store.load(), wait=True)
        elif pick == "toggle":
            prefs.show_stats_after_game = not prefs.show_stats_after_game
            settings_store.save(prefs)
        elif pick == "reset" and ui.confirm("Delete all saved statistics?", crumbs="Statistics"):
            stats_store.reset()


def select_game(ui: GameUI) -> Optional[GameConfig | DualSetup]:
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
