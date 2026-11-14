"""The Dual Player set-up screens: who you are, your secret, your side, game length.

Host:   name -> passkey (typed twice, or generated) -> side -> game length
Joiner: room code -> name -> passkey -> side

Esc steps back one screen at a time; from the first screen it returns to the
Create / Join menu. Nothing here touches the network: the result is a plain
``DualSetup`` that the connection code (next phase) consumes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from . import settings as settings_store
from .names import MAX_NAME_CELLS, check_name, name_error
from .passkey import MAX_LENGTH, Passkey, generate_passphrase, passkey_error
from .players import Side
from .roomcode import format_room_code, generate_room_code, parse_room_code, room_code_error
from .ui import GameUI, Option, mode_text

MAX_COUNT = 99

ROLES = [
    Option("Create game", "host", "Host a game and invite a friend"),
    Option("Join game", "join", "Enter the room code a friend gave you"),
]
SIDES = [
    Option("Left", "left", "Your hand on the left, your opponent's on the right"),
    Option("Right", "right", "Your hand on the right, your opponent's on the left"),
]
LENGTHS = [
    Option("Choose number of rounds", "rounds",
           "Play exactly N rounds; highest score wins, a tie is a draw"),
    Option("First to N", "first_to",
           "The first player to win N rounds takes the game; draws don't count"),
]
PASSKEY_CHOICES = [
    Option("Type my own", "own", "At least 6 characters, hidden as you type"),
    Option("Generate one for me", "generate", "Three random words, easy to say aloud"),
]


@dataclass(frozen=True)
class DualSetup:
    role: str                       # "host" or "join"
    name: str
    passkey: Passkey                # never printed; see passkey.py
    side: Side                      # where *your* hand sits on *your* screen
    room_code: str                  # nine digits (generated for a host, typed by a joiner)
    rounds: Optional[int] = None    # host only: exactly N rounds ...
    first_to: Optional[int] = None  # ... or first to N wins (a joiner learns it on connecting)

    def summary_lines(self) -> list[str]:
        """Human-readable recap. Deliberately excludes the passkey."""
        lines = [f"Name: {self.name}", f"Your hand: {self.side} side"]
        if self.role == "host":
            lines.append(f"Game: {mode_text(rounds=self.rounds, first_to=self.first_to)}")
            lines.append(f"Room code: {format_room_code(self.room_code)}")
            lines.append("Share the room code and your passkey with your friend.")
        else:
            lines.append(f"Joining room: {format_room_code(self.room_code)}")
        return lines


# A step takes (ui, crumbs, data) and returns True once it has stored its value,
# or False if the player pressed Esc to go back.
Step = Callable[[GameUI, str, dict], bool]


def _step_room(ui: GameUI, crumbs: str, data: dict) -> bool:
    initial = format_room_code(data["room"]) if "room" in data else ""
    text = ui.ask_text("Enter the room code", crumbs=crumbs, validator=room_code_error,
                       max_cells=11, initial=initial)
    if text is None:
        return False
    data["room"] = parse_room_code(text)
    return True


def _step_name(ui: GameUI, crumbs: str, data: dict) -> bool:
    text = ui.ask_text("What's your name?", crumbs=crumbs, validator=name_error,
                       max_cells=MAX_NAME_CELLS, initial=data.get("name", ""))
    if text is None:
        return False
    data["name"] = check_name(text).name
    return True


def _type_own_passkey(ui: GameUI, crumbs: str) -> Optional[str]:
    while True:
        first = ui.ask_text("Choose a passkey", crumbs=crumbs, validator=passkey_error,
                            max_cells=MAX_LENGTH, mask=True)
        if first is None:
            return None
        expected = Passkey(first)
        second = ui.ask_text(
            "Type it again to confirm", crumbs=crumbs, max_cells=MAX_LENGTH, mask=True,
            validator=lambda t: None if expected.matches(t) else "Passkeys don't match. Try again.",
        )
        if second is not None:
            return first                    # Esc here re-asks the first entry


def _step_passkey_host(ui: GameUI, crumbs: str, data: dict) -> bool:
    while True:
        choice = ui.choose("How do you want to set your passkey?", PASSKEY_CHOICES,
                           crumbs=crumbs)
        if choice is None:
            return False
        if choice == "generate":
            while True:
                phrase = generate_passphrase()
                pick = ui.choose(
                    f"Your passkey: {phrase}",
                    [Option("Use this passkey", "use",
                            "Tell your friend along with the room code"),
                     Option("Generate another", "again")],
                    crumbs=crumbs,
                )
                if pick == "use":
                    data["passkey"] = Passkey(phrase)
                    return True
                if pick is None:
                    break                   # back to the type-or-generate menu
        else:
            typed = _type_own_passkey(ui, crumbs)
            if typed is not None:
                data["passkey"] = Passkey(typed)
                return True


def _step_passkey_join(ui: GameUI, crumbs: str, data: dict) -> bool:
    text = ui.ask_text("Enter the passkey", crumbs=crumbs, validator=passkey_error,
                       max_cells=MAX_LENGTH, mask=True)
    if text is None:
        return False
    data["passkey"] = Passkey(text)
    return True


def _step_side(ui: GameUI, crumbs: str, data: dict) -> bool:
    prefs = settings_store.load()
    pick = ui.choose("Where should your hand appear on your screen?", SIDES, crumbs=crumbs,
                     start=0 if prefs.preferred_side == "left" else 1)
    if pick is None:
        return False
    data["side"] = Side(pick)
    if prefs.preferred_side != pick:
        prefs.preferred_side = pick
        settings_store.save(prefs)
    return True


def _step_length(ui: GameUI, crumbs: str, data: dict) -> bool:
    while True:
        mode = ui.choose("How long should the game be?", LENGTHS, crumbs=crumbs)
        if mode is None:
            return False
        title = ("How many rounds?" if mode == "rounds"
                 else "How many wins does a player need?")
        count = ui.ask_number(title, 1, MAX_COUNT, crumbs=crumbs)
        if count is not None:                # Esc on the number returns to the mode menu
            data["rounds"], data["first_to"] = (count, None) if mode == "rounds" else (None, count)
            return True


HOST_STEPS: list[Step] = [_step_name, _step_passkey_host, _step_side, _step_length]
JOIN_STEPS: list[Step] = [_step_room, _step_name, _step_passkey_join, _step_side]


def _run_steps(ui: GameUI, role: str) -> Optional[DualSetup]:
    steps = HOST_STEPS if role == "host" else JOIN_STEPS
    crumbs = "Start Game > Dual Player > " + ("Create game" if role == "host" else "Join game")
    data: dict = {}
    i = 0
    while i < len(steps):
        if steps[i](ui, crumbs, data):
            i += 1
        elif i == 0:
            return None
        else:
            i -= 1
    return DualSetup(
        role=role,
        name=data["name"],
        passkey=data["passkey"],
        side=data["side"],
        room_code=generate_room_code() if role == "host" else data["room"],
        rounds=data.get("rounds"),
        first_to=data.get("first_to"),
    )


def setup_dual(ui: GameUI) -> Optional[DualSetup]:
    """Run the Create / Join screens. None means the player backed out."""
    while True:
        role = ui.choose("Dual Player", ROLES, crumbs="Start Game")
        if role is None:
            return None
        setup = _run_steps(ui, role)
        if setup is not None:
            return setup
