"""Command-line entry point: argument parsing, the game loop and the menu loop."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Optional, Sequence

from . import __version__, stats as stats_store, terminal
from .engine import Match, Move, Score
from . import settings as settings_store
from .dualsetup import DualSetup
from .net.config import mailbox_url
from .net.connect import connect_dual, terms_text
from .menu import MAX_ROUNDS, GameConfig, select_game
from .players import CpuOpponent, Opponent
from .stats import Stats
from .strategies import DIFFICULTIES, create_strategy
from .ui import GameUI

REPO_URL = "git+https://github.com/SohanurRahmanSohan43/rps_game.git"


def _best_of(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a number") from None
    if number < 1 or number % 2 == 0:
        raise argparse.ArgumentTypeError("must be an odd positive number (3, 5, 7, ...)")
    return number


def _rounds(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a number") from None
    if not 1 <= number <= MAX_ROUNDS:
        raise argparse.ArgumentTypeError(f"must be between 1 and {MAX_ROUNDS}")
    return number


def _first_to(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a number") from None
    if not 1 <= number <= MAX_ROUNDS:
        raise argparse.ArgumentTypeError(f"must be between 1 and {MAX_ROUNDS}")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rps",
        description="Rock Paper Scissors in your terminal. "
                    "Run with no game options to open the menu.",
    )
    length = parser.add_mutually_exclusive_group()
    length.add_argument(
        "-r", "--rounds", type=_rounds, metavar="N",
        help=f"skip the menu: play exactly N rounds (1-{MAX_ROUNDS}), highest score wins",
    )
    length.add_argument(
        "-f", "--first-to", type=_first_to, metavar="N",
        help="skip the menu: first player to N wins takes the game (draws don't count)",
    )
    length.add_argument(
        "-b", "--best-of", type=_best_of, metavar="N",
        help="skip the menu: first-to-majority matches (odd N)",
    )
    parser.add_argument(
        "-d", "--difficulty", choices=DIFFICULTIES, default=None,
        help="skip the menu: computer opponent (default: normal)",
    )
    parser.add_argument(
        "--plain", action="store_true",
        help="screen-reader friendly: no art, colour or animation; line input",
    )
    parser.add_argument(
        "--ascii", action="store_true", help="use only ASCII characters for tables"
    )
    parser.add_argument(
        "--no-animation", action="store_true", help="skip the countdown animation"
    )
    parser.add_argument(
        "--mailbox", metavar="URL",
        help="connection server for Dual Player (default: the public Magic Wormhole mailbox; "
             "both players must use the same one; also settable with $RPS_MAILBOX)",
    )
    parser.add_argument("--stats", action="store_true", help="show lifetime statistics and exit")
    parser.add_argument(
        "--reset-stats", action="store_true", help="delete saved statistics and exit"
    )
    parser.add_argument(
        "--no-save", action="store_true", help="don't record this session in your statistics"
    )
    parser.add_argument(
        "-u", "--update", action="store_true", help="upgrade from GitHub and exit"
    )
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def update() -> int:
    print("Checking for updates from GitHub...")
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", REPO_URL]
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        print(f"\nUpdate failed (pip exit code {exc.returncode}).")
        print("If pip mentions an 'externally-managed environment', "
              "reinstall with pipx or inside a virtual environment.")
        return exc.returncode or 1
    except OSError as exc:
        print(f"\nCould not run pip: {exc}")
        return 1
    print("\nUpdate complete. Please restart the game.")
    return 0


def _wants_plain(args: argparse.Namespace) -> bool:
    def tty(stream) -> bool:
        try:
            return stream.isatty()
        except (AttributeError, ValueError):
            return False

    return (
        args.plain
        or not tty(sys.stdout)
        or not tty(sys.stdin)
        or os.environ.get("TERM", "").lower() == "dumb"
    )


def _keys(ui: GameUI):
    """Key-at-a-time input for rich mode; plain mode keeps normal line input."""
    return nullcontext() if ui.plain else terminal.keyboard()


def _make_ui(args: argparse.Namespace) -> GameUI:
    return GameUI(
        plain=_wants_plain(args),
        ascii_only=args.ascii,
        animate=not args.no_animation,
    )


def show_stats(args: argparse.Namespace) -> int:
    _make_ui(args).show_stats(stats_store.load())
    return 0


def reset_stats() -> int:
    try:
        answer = input("Delete all saved statistics? [y/N] ")
    except EOFError:
        answer = ""
    if answer.strip().lower() not in ("y", "yes"):
        print("Nothing deleted.")
        return 0
    if stats_store.reset():
        print("Statistics deleted.")
        return 0
    print("Could not delete the statistics file.")
    return 1


@dataclass
class GameResult:
    session: Score
    matches: Score
    lifetime: Optional[Stats]
    finished: Optional[Match]     # the completed fixed-length game, if it got that far
    interrupted: bool             # Ctrl-C / closed input: the player wants out entirely
    opponent_left: bool = False   # the opponent quit or disconnected mid-game


def _new_match(config: GameConfig) -> Match:
    return Match(best_of=config.best_of, first_to=config.first_to, max_rounds=config.rounds)


def run_game(ui: GameUI, config: GameConfig, *, save: bool = True,
             opponent: Optional[Opponent] = None) -> GameResult:
    """Play one game to its end (or until someone quits) and record the stats.

    ``opponent`` defaults to the computer at ``config.difficulty``; any object
    implementing the Opponent interface (e.g. a network player) can be passed.
    """
    if opponent is None:
        opponent = CpuOpponent(create_strategy(config.difficulty))
    session, matches = Score(), Score()
    history: list[Move] = []          # everything the player has thrown
    match = _new_match(config)
    finished: Optional[Match] = None
    interrupted = opponent_left = False

    ui.intro(best_of=config.best_of, rounds=config.rounds, difficulty=config.difficulty,
             first_to=config.first_to)
    try:
        while True:
            ui.start_round(match, session, config.difficulty)
            try:
                move = ui.ask_move()
                if move is None:
                    break
                theirs = opponent.play(move)          # a computer sees only *past* moves
                if theirs is None:
                    opponent_left = True
                    break
                history.append(move)

                rnd = match.play(move, theirs)
                opponent.record(rnd)
                session.record(rnd.outcome)
                ui.show_round(rnd, match, session)
            finally:
                ui.end_round()

            if match.is_over:
                matches.record(match.winner)
                if config.rounds:                      # a fixed-length game is done
                    finished = match
                    break
                match = _new_match(config)             # race-style match: start the next one
    except (KeyboardInterrupt, EOFError):
        interrupted = True

    lifetime = None
    if save:
        lifetime = stats_store.load()
        lifetime.merge(session, matches, history)
        if session.rounds:
            stats_store.save(lifetime)
    return GameResult(session, matches, lifetime, finished, interrupted, opponent_left)


def _shown_lifetime(result: GameResult):
    """All-time totals appear on the results screen only if the player opted in."""
    return result.lifetime if settings_store.load().show_stats_after_game else None


def play_direct(args: argparse.Namespace) -> int:
    """`rps -d hard -r 5` and friends: skip the menu, play, show results, exit."""
    ui = _make_ui(args)
    config = GameConfig(
        difficulty=args.difficulty or "normal", best_of=args.best_of,
        first_to=args.first_to, rounds=args.rounds,
    )
    with _keys(ui):
        result = run_game(ui, config, save=not args.no_save)
    ui.goodbye(result.session, result.matches if config.best_of or config.first_to else None,
               _shown_lifetime(result), finished=result.finished)
    return 0


def run_menu(args: argparse.Namespace) -> int:
    """`rps`: main menu -> game -> results -> back to the menu, until Exit."""
    ui = _make_ui(args)
    try:
        with _keys(ui):
            while True:
                config = select_game(ui)
                if config is None:
                    break
                if isinstance(config, DualSetup):
                    connection = connect_dual(ui, config, mailbox=mailbox_url(args.mailbox))
                    if connection is not None:
                        # Playing over the connection arrives in the next phase.
                        ui.message("Connected!", [
                            f"You are connected to {connection.opponent_name}.",
                            f"Game: {terms_text(connection.terms)}", "",
                            "Playing the game itself arrives in the next update.",
                        ], crumbs="Dual Player")
                        connection.close()
                    continue
                result = run_game(ui, config, save=not args.no_save)
                if result.interrupted:
                    ui.goodbye(result.session, None, _shown_lifetime(result), finished=result.finished)
                    return 0
                ui.goodbye(result.session, None, _shown_lifetime(result), finished=result.finished,
                           title="Game over", pause=True)
    except (KeyboardInterrupt, EOFError):
        print()
        return 0
    ui.farewell()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.update:
        return update()
    if args.stats:
        return show_stats(args)
    if args.reset_stats:
        return reset_stats()
    if args.difficulty or args.best_of or args.rounds or args.first_to:
        return play_direct(args)
    return run_menu(args)


if __name__ == "__main__":
    raise SystemExit(main())
