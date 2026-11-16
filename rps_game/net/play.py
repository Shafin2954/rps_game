"""Playing Dual Player games over a finished connection.

Runs the ordinary game loop (``run_game``) with a ``NetworkOpponent``, then offers
the result screen with *Play again* / *Back to the menu*. A rematch needs both
players to agree and reuses the same secure connection, so nobody re-enters a
passkey. Leaving, disconnecting or cheating mid-game counts as a forfeit and the
other player wins.
"""
from __future__ import annotations

from typing import Callable

from ..dualsetup import DualSetup
from ..menu import GameConfig
from ..players import Seat, Side
from ..ui import GameUI, Option
from .errors import Cancelled, NetError
from .game import NetworkOpponent
from .session import Connection

LEAVE_PROMPT = "Leave the game? You forfeit and your opponent wins."
CRUMBS = "Dual Player"
AFTER_GAME = [
    Option("Play again", "again", "Ask your opponent for another game"),
    Option("Back to the menu", "menu", "Leave this match"),
]


def play_dual(ui: GameUI, setup: DualSetup, connection: Connection, *,
              run_game: Callable, **options) -> bool:
    """Play games against ``connection``'s other end until someone leaves.

    Returns True if the player pressed Ctrl-C (or input closed), meaning "quit the
    whole program"; False for an ordinary return to the menu. ``options`` (timeouts)
    go to the NetworkOpponent; tests use them to stay fast."""
    opponent = NetworkOpponent(connection, **options)
    ui.set_players(Seat(setup.name, setup.side), Seat(connection.opponent_name, setup.side.other))
    terms = connection.terms
    config = GameConfig(difficulty="", rounds=terms.rounds, first_to=terms.first_to, one_game=True)
    try:
        while True:
            result = run_game(ui, config, save=False, opponent=opponent)
            if result.interrupted:
                return True
            if result.quit_by_player:
                return False                              # the finally block says goodbye
            if result.opponent_left:
                ui.message("Game over", [result.end_reason or f"{opponent.name} left the game.",
                                         "You win by forfeit."], crumbs=CRUMBS)
                return False
            choice = ui.results_menu("Game over", result.session, result.finished, AFTER_GAME,
                                     idle=opponent.results_status)
            if choice != "again":
                return False
            if not _rematch(ui, opponent):
                return False
    finally:
        opponent.close("quit")
        ui.set_players(Seat("You", Side.LEFT), Seat("Computer", Side.RIGHT))   # back to single-player


def _rematch(ui: GameUI, opponent: NetworkOpponent) -> bool:
    """Ask for another game and wait for the answer. True if it starts."""
    error = None
    with ui.waiting(f"Waiting for {opponent.name}", crumbs=CRUMBS,
                    lines=[f"Asking {opponent.name} to play again..."]) as w:
        def hook(text: str) -> bool:
            w.set_lines([text])
            return w.tick()

        opponent.on_wait = hook
        try:
            opponent.rematch()
        except Cancelled:
            return False
        except NetError as exc:
            error = exc
    if error is not None:
        ui.message("No rematch", [str(error)], crumbs=CRUMBS)
        return False
    return True
