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
from . import insight as insight_reader
from . import profile as profile_store
from .engine import Match, Move, Round, Score
from . import settings as settings_store
from .dualsetup import DualSetup
from .gauntlet.play import MAX_SEED_CELLS, GauntletConfig, play_gauntlet, seed_error
from .net.config import mailbox_url
from .net.connect import connect_dual
from .net.errors import Cancelled, NetError
from .net.play import LEAVE_PROMPT, play_dual
from .menu import (MAX_ROUNDS, GameConfig, reset_everything, select_game, show_achievements,
                   show_profile)
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


def _seed(value: str) -> str:
    error = seed_error(value)
    if error is None and len(value.strip()) > MAX_SEED_CELLS:
        error = f"a seed is at most {MAX_SEED_CELLS} characters"
    if error:
        raise argparse.ArgumentTypeError(error)
    return value


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
        "-g", "--gauntlet", action="store_true",
        help="skip the menu: climb the Gauntlet, ten foes with tells, relics and a boss",
    )
    parser.add_argument(
        "--daily", action="store_true",
        help="skip the menu: today's Daily Run, the same Gauntlet for everyone",
    )
    parser.add_argument(
        "--seed", type=_seed, metavar="SEED",
        help="skip the menu: the Gauntlet built from SEED (share one to race a friend)",
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
        "--profile", action="store_true", help="show your rank and achievements and exit"
    )
    parser.add_argument(
        "--reset-stats", action="store_true",
        help="delete saved statistics, rank and achievements and exit",
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


def show_profile_and_exit(args: argparse.Namespace) -> int:
    ui, profile = _make_ui(args), profile_store.load()
    show_profile(ui, profile, wait=False)
    show_achievements(ui, profile, wait=False)
    return 0


def reset_stats() -> int:
    try:
        answer = input("Delete all saved statistics, your rank and your achievements? [y/N] ")
    except EOFError:
        answer = ""
    if answer.strip().lower() not in ("y", "yes"):
        print("Nothing deleted.")
        return 0
    if reset_everything():
        print("Statistics deleted.")
        return 0
    print("Could not delete the saved files.")
    return 1


@dataclass
class GameResult:
    session: Score
    matches: Score
    lifetime: Optional[Stats]
    finished: Optional[Match]     # the completed fixed-length game, if it got that far
    interrupted: bool             # Ctrl-C / closed input: the player wants out entirely
    opponent_left: bool = False   # the opponent quit, disconnected or cheated mid-game
    quit_by_player: bool = False  # the local player chose to leave
    end_reason: str = ""          # why an online game ended early, in words
    rounds: tuple[Round, ...] = ()   # every round of the session, in order
    extra: tuple[str, ...] = ()   # lines for the results screen: mind reader, XP, unlocks


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
    played: list[Round] = []          # every finished round
    match = _new_match(config)
    finished: Optional[Match] = None
    interrupted = opponent_left = quit_by_player = False
    end_reason = ""
    online = hasattr(opponent, "poll_status")      # a network opponent can report on itself
    if online:
        opponent.on_wait = lambda text: ui.opponent_wait(text, LEAVE_PROMPT)

    ui.intro(best_of=config.best_of, rounds=config.rounds, difficulty=config.difficulty,
             first_to=config.first_to)
    try:
        while True:
            if online:
                rtt = getattr(opponent, "rtt_ms", None)
                ui.start_round(match, session, config.difficulty,
                               note=f"{rtt:.0f} ms" if rtt is not None else "")
            else:
                ui.start_round(match, session, config.difficulty)
            try:
                if online:
                    move = ui.ask_move(idle=opponent.poll_status, leave_prompt=LEAVE_PROMPT)
                else:
                    move = ui.ask_move()
                if move is None:
                    quit_by_player = True
                    break
                theirs = opponent.play(move)          # a computer sees only *past* moves
                if theirs is None:
                    opponent_left = True
                    break
                history.append(move)

                rnd = match.play(move, theirs)
                played.append(rnd)
                opponent.record(rnd)
                session.record(rnd.outcome)
                ui.show_round(rnd, match, session)
            except Cancelled:                              # left while waiting on the opponent
                quit_by_player = True
                break
            except NetError as exc:                        # they left, vanished or cheated
                opponent_left, end_reason = True, str(exc)
                break
            finally:
                ui.end_round()

            if match.is_over:
                matches.record(match.winner)
                if config.rounds or config.one_game:       # a single game is done
                    finished = match
                    break
                match = _new_match(config)             # race-style match: start the next one
    except (KeyboardInterrupt, EOFError):
        interrupted = True

    lifetime = None
    extra: list[str] = []
    reading = None if online else insight_reader.analyse(played)
    if reading is not None:                            # what the player's throws gave away
        extra += reading.lines()
    if save:
        lifetime = stats_store.load()
        lifetime.merge(session, matches, history, played)
        if session.rounds:
            stats_store.save(lifetime)
            if not online:
                profile = profile_store.load()
                extra += profile_store.record_classic(
                    profile, difficulty=config.difficulty, session=session,
                    insight=reading).lines()
                profile_store.save(profile)
    return GameResult(session, matches, lifetime, finished, interrupted, opponent_left,
                      quit_by_player, end_reason, tuple(played), tuple(extra))


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
               _shown_lifetime(result), finished=result.finished, extra=result.extra)
    return 0


def play_gauntlet_direct(args: argparse.Namespace) -> int:
    """`rps --gauntlet`, `--daily` or `--seed X`: straight into a run, then exit."""
    ui = _make_ui(args)
    config = GauntletConfig(seed=args.seed, daily=args.daily)
    with _keys(ui):
        play_gauntlet(ui, config, save=not args.no_save)
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
                    if connection is not None and play_dual(
                            ui, config, connection, run_game=run_game, save=not args.no_save):
                        ui.farewell()                      # Ctrl-C mid-game: quit, like single player
                        return 0
                    continue
                if isinstance(config, GauntletConfig):
                    if play_gauntlet(ui, config, save=not args.no_save, pause=True).interrupted:
                        return 0
                    continue
                result = run_game(ui, config, save=not args.no_save)
                if result.interrupted:
                    ui.goodbye(result.session, None, _shown_lifetime(result),
                               finished=result.finished, extra=result.extra)
                    return 0
                ui.goodbye(result.session, None, _shown_lifetime(result), finished=result.finished,
                           title="Game over", pause=True, extra=result.extra)
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
    if args.profile:
        return show_profile_and_exit(args)
    if args.reset_stats:
        return reset_stats()
    if args.gauntlet or args.daily or args.seed:
        return play_gauntlet_direct(args)
    if args.difficulty or args.best_of or args.rounds or args.first_to:
        return play_direct(args)
    return run_menu(args)


if __name__ == "__main__":
    raise SystemExit(main())
