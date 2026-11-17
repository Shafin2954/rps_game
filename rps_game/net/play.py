"""Playing Dual Player games over a finished connection.

Runs the ordinary game loop (``run_game``) with a ``NetworkOpponent``, then offers
the result screen with *Play again* / *Back to the menu*. A rematch needs both
players to agree and reuses the same secure connection, so nobody re-enters a
passkey. Leaving, disconnecting or cheating mid-game counts as a forfeit and the
other player wins.
"""
from __future__ import annotations

from typing import Callable, Optional

from .. import chat
from .. import profile as profile_store
from ..dualsetup import DualSetup
from ..engine import Outcome
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
SAY = Option("Send a message", "say", "Say something to your opponent")


def _game_outcome(result) -> Optional[Outcome]:
    """Who took the game: a forfeit counts as a win for whoever stayed."""
    if result.finished is not None and result.finished.winner is not None:
        return result.finished.winner
    if result.opponent_left:
        return Outcome.WIN
    if result.quit_by_player or result.interrupted:
        return Outcome.LOSS
    return None


def _record(opponent: NetworkOpponent, result) -> list[str]:
    """Save the game to the head-to-head record. Returns lines for the results screen."""
    profile = profile_store.load()
    gains = profile_store.record_online(
        profile, opponent_id=opponent.opponent_id, opponent_name=opponent.name,
        session=result.session, outcome=_game_outcome(result))
    profile_store.save(profile)
    return gains.lines()


def play_dual(ui: GameUI, setup: DualSetup, connection: Connection, *,
              run_game: Callable, save: bool = True, **options) -> bool:
    """Play games against ``connection``'s other end until someone leaves.

    Returns True if the player pressed Ctrl-C (or input closed), meaning "quit the
    whole program"; False for an ordinary return to the menu. Each game is added to
    the head-to-head record unless ``save`` is off. ``options`` (timeouts) go to the
    NetworkOpponent; tests use them to stay fast."""
    opponent = NetworkOpponent(connection, **options)
    ui.set_players(Seat(setup.name, setup.side), Seat(connection.opponent_name, setup.side.other))
    if opponent.can_chat:
        ui.set_chat(opponent.chat, opponent.say)
    terms = connection.terms
    config = GameConfig(difficulty="", rounds=terms.rounds, first_to=terms.first_to, one_game=True)
    try:
        while True:
            result = run_game(ui, config, save=False, opponent=opponent)
            earned = _record(opponent, result) if save else []
            if result.interrupted:
                return True
            if result.quit_by_player:
                return False                              # the finally block says goodbye
            if result.opponent_left:
                ui.message("Game over", [result.end_reason or f"{opponent.name} left the game.",
                                         "You win by forfeit.", *earned], crumbs=CRUMBS)
                return False
            choice = _after_game(ui, opponent, result, earned)
            if choice != "again":
                return False
            if not _rematch(ui, opponent):
                return False
    finally:
        opponent.close("quit")
        ui.set_chat()
        ui.set_players(Seat("You", Side.LEFT), Seat("Computer", Side.RIGHT))   # back to single-player


def _after_game(ui: GameUI, opponent: NetworkOpponent, result, earned: list[str]) -> Optional[str]:
    """The game-over menu. With chat, "Send a message" loops back to the same menu."""
    options = [*AFTER_GAME, SAY] if opponent.can_chat else AFTER_GAME
    first = True
    while True:
        talk = [f"{speaker}: {text}" for speaker, text, _ in opponent.chat.recent(3)]
        opponent.chat.unread()                              # they are on screen now
        choice = ui.results_menu("Game over", result.session, result.finished, options,
                                 idle=opponent.results_status, extra=[*earned, *talk],
                                 celebrate=first)
        first = False
        if choice != "say":
            return choice
        text = ui.ask_text(f"Message to {opponent.name}", crumbs=CRUMBS,
                           validator=chat.chat_error, max_cells=chat.MAX_CELLS)
        if text is not None:
            error = opponent.say(text)
            if error:
                ui.message("Not sent", [error], crumbs=CRUMBS)


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
