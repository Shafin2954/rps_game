"""Glue between the connection handshake and the screens.

``connect_dual`` takes the result of the set-up screens and returns a live
``Connection`` (or None if the player backed out or it failed, after telling
them why).
"""
from __future__ import annotations

from dataclasses import replace
from typing import Callable, Optional

from ..dualsetup import DualSetup
from ..identity import install_id
from ..names import MAX_NAME_CELLS, check_name, name_error
from ..passkey import MAX_LENGTH, Passkey, passkey_error
from ..roomcode import format_room_code
from ..ui import GameUI, Waiter, mode_text
from .config import MAX_WRONG_PASSKEYS
from .errors import Cancelled, NetError, RoomBurned, Timeout, WrongPasskey
from .session import Connection, GameTerms, HostSession, JoinSession
from .transport import Transport, create_transport

CRUMBS = "Start Game > Dual Player"
NAME_REJECTED = {
    "taken": "That name is already taken by the host.",
    "invalid": "The host couldn't accept that name.",
}


def terms_text(terms: GameTerms) -> str:
    return mode_text(rounds=terms.rounds, first_to=terms.first_to)


def connect_dual(
    ui: GameUI,
    setup: DualSetup,
    *,
    mailbox: str,
    factory: Optional[Callable[[], Transport]] = None,
    session_options: Optional[dict] = None,
) -> Optional[Connection]:
    """``factory`` and ``session_options`` (timeouts) exist so tests can run offline and fast."""
    factory = factory or (lambda: create_transport(mailbox))
    options = session_options or {}
    if setup.role == "host":
        return _host(ui, setup, factory, options)
    return _join(ui, setup, factory, options)


def _problem(ui: GameUI, error: NetError, extra: tuple[str, ...] = ()) -> None:
    ui.message("Couldn't start the game", [str(error), *extra], crumbs=CRUMBS)


# ------------------------------------------------------------------ host

class HostScreen:
    """What the host's waiting screen says, as a pure function of the events so far.

    The wrong-passkey count is *remembered*: the host re-listens within
    milliseconds of a failed attempt, and an ordinary "waiting" line must not
    wipe the warning before anyone has seen it.
    """

    def __init__(self, head: list[str]) -> None:
        self._head = head
        self._wrong = 0
        self._limit = MAX_WRONG_PASSKEYS

    def lines(self, kind: str, **info) -> list[str]:
        if kind == "wrong_passkey":
            self._wrong, self._limit = info["count"], info["limit"]
        lines = [*self._head, _host_status_text(kind, info)]
        if self._wrong:
            lines += ["", f"Wrong passkey attempts so far: {self._wrong} of {self._limit}. "
                          "The room closes at the limit."]
        return lines


def _host_status_text(kind: str, info: dict) -> str:
    return {
        "waiting": "Waiting for your friend to join...",
        "wrong_passkey": (f"Someone used a wrong passkey ({info.get('count')} of "
                          f"{info.get('limit')}). Still waiting..."),
        "reconnecting": "Connection hiccup, reconnecting...",
        "negotiating": "Someone is joining...",
        "name_rejected": "Asking them to choose a different name...",
        "awaiting_decision": f"Waiting for {info.get('name')} to accept the game...",
        "starting": f"Starting the game with {info.get('name')}...",
    }.get(kind, "")


def _host(ui: GameUI, setup: DualSetup, factory, options: dict) -> Optional[Connection]:
    terms = GameTerms(rounds=setup.rounds, first_to=setup.first_to)
    code = format_room_code(setup.room_code)
    head = [f"Game: {terms_text(terms)}", "", f"Room code:  {code}",
            "Share the room code and your passkey with your friend.", ""]
    connection: Optional[Connection] = None
    error: Optional[NetError] = None
    screen = HostScreen(head)
    with ui.waiting("Waiting for your friend", crumbs=CRUMBS, lines=head,
                    secret=setup.passkey.reveal()) as w:
        def on_status(kind: str, **info) -> None:
            w.set_lines(screen.lines(kind, **info))

        session = HostSession(factory, name=setup.name, passkey=setup.passkey,
                              room_code=setup.room_code, terms=terms, install_id=install_id(),
                              tick=w.tick, on_status=on_status, **options)
        try:
            connection = session.run()
        except Cancelled:
            return None
        except NetError as exc:
            error = exc
    if error is not None:
        _problem(ui, error, _hints(error, host=True))
        return None
    return connection


# ------------------------------------------------------------------ joiner

def _join(ui: GameUI, setup: DualSetup, factory, options: dict) -> Optional[Connection]:
    code = format_room_code(setup.room_code)
    for attempt in range(1, MAX_WRONG_PASSKEYS + 1):
        connection: Optional[Connection] = None
        error: Optional[NetError] = None
        with ui.waiting(f"Joining room {code}", crumbs=CRUMBS,
                        lines=["Connecting..."]) as w:
            def on_status(kind: str, **info) -> None:
                text = {
                    "connecting": "Connecting...",
                    "waiting_for_host": "Waiting for the host to answer...",
                    "awaiting_start": f"Waiting for {info.get('name', 'the host')} to start...",
                }.get(kind)
                if text:
                    w.set_lines([text])

            session = JoinSession(
                factory, name=setup.name, passkey=setup.passkey, room_code=setup.room_code,
                install_id=install_id(),
                ask_name=lambda reason: _ask_new_name(ui, w, reason),
                confirm_terms=lambda host, terms: _confirm_terms(ui, w, host, terms),
                tick=w.tick, on_status=on_status, **options,
            )
            try:
                connection = session.run()
            except Cancelled:
                return None
            except WrongPasskey as exc:
                error = exc
            except NetError as exc:
                error = exc
        if connection is not None:
            return connection
        if isinstance(error, WrongPasskey):
            if attempt >= MAX_WRONG_PASSKEYS:
                ui.message("Too many wrong passkeys", [
                    "Please check the passkey with your friend.",
                    "The host may need to create a new game.",
                ], crumbs=CRUMBS)
                return None
            retry = ui.ask_text(
                "That passkey didn't match. Enter it again", crumbs=CRUMBS,
                validator=passkey_error, max_cells=MAX_LENGTH, mask=True)
            if retry is None:
                return None
            setup = replace(setup, passkey=Passkey(retry))
            continue
        _problem(ui, error, _hints(error, host=False))
        return None
    return None


def _ask_new_name(ui: GameUI, waiter: Waiter, reason: str) -> Optional[str]:
    with waiter.paused():
        text = ui.ask_text(
            f"{NAME_REJECTED.get(reason, 'That name was refused.')} Choose another",
            crumbs=CRUMBS, validator=name_error, max_cells=MAX_NAME_CELLS)
    return None if text is None else check_name(text).name


def _confirm_terms(ui: GameUI, waiter: Waiter, host: str, terms: GameTerms) -> bool:
    with waiter.paused():
        return ui.confirm(f"{host} invites you to play: {terms_text(terms)}. Accept?",
                          crumbs=CRUMBS)


def _hints(error: Optional[NetError], *, host: bool) -> tuple[str, ...]:
    if isinstance(error, Timeout) and not host:
        return ("Check the room code, and that your friend has already created the game.",)
    if isinstance(error, RoomBurned):
        return ()
    return ()
