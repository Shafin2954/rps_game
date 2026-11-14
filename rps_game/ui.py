"""Everything the player sees and touches.

Two presentation levels share one class:

* rich mode  - full-screen layouts redrawn each time: menus, the round screen
  (ASCII hands + centred scoreboard) and the results screen.
* plain mode - linear text only, no animation, no colour, numbered line-based
  menus. Meant for screen readers, dumb terminals and pipes.

Results are always spelled out in words, never conveyed by colour alone.
"""
from __future__ import annotations

import getpass
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from typing import Callable, Optional, Sequence

import pyfiglet
from rich import box
from rich.align import Align
from rich.cells import cell_len, set_cell_size
from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from . import art, terminal
from .engine import Match, Move, Outcome, Round, Score
from .players import Seat, Side
from .stats import Stats

GAP = 10                                    # blank columns between the two hands
MIN_ART_COLUMNS = 2 * art.WIDTH + GAP + 4   # narrower terminals get a compact layout
MIN_ART_ROWS = 24                           # shorter terminals too
SCOREBOARD_BIG_MIN_ROWS = 27                 # below this the heading is one plain line
HOLD_REVEAL = 1.0                           # seconds the revealed hands stay up
HOLD_SCORE = 0.9                            # seconds the updated score stays up

PLAYER_STYLE = "bold cyan"
CPU_STYLE = "bold magenta"
QUIT_WORDS = {"q", "quit", "exit"}
BACK_WORDS = {"q", "b", "back", "quit", "exit"}
OUTCOME_STYLE = {
    Outcome.WIN: "bold green",
    Outcome.LOSS: "bold red",
    Outcome.DRAW: "bold yellow",
}
OUTCOME_TEXT = {
    Outcome.WIN: "You win!",
    Outcome.LOSS: "You lose!",
    Outcome.DRAW: "It's a draw!",
}


def _line(text: str = "", style: str = "") -> Text:
    """A single centred line (also the way to get a blank line in a Group)."""
    return Text(text, style=style, justify="center", no_wrap=True)


def center_cells(text: str, width: int) -> str:
    """Centre ``text`` in ``width`` terminal cells (wide characters count as 2)."""
    if cell_len(text) >= width:
        return set_cell_size(text, width)
    left = (width - cell_len(text)) // 2
    return " " * left + text + " " * (width - cell_len(text) - left)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def mode_text(best_of: Optional[int] = None, rounds: Optional[int] = None,
              first_to: Optional[int] = None) -> str:
    if first_to:
        return f"first to {first_to} wins"
    if best_of:
        return f"best of {best_of} (first to {best_of // 2 + 1})"
    if rounds:
        return f"{_plural(rounds, 'round')}, highest score wins"
    return "unlimited rounds"


def _match_summary(match: Match, opponent: str = "Computer") -> tuple[str, str]:
    """(message, style) describing how a finished match or game ended."""
    s = match.score
    w, l, d = s.wins, s.losses, s.draws
    if match.max_rounds is not None:
        extra = f" ({_plural(d, 'draw')})" if d else ""
        if match.winner is Outcome.WIN:
            return f"You won the game {w}-{l}{extra}!", OUTCOME_STYLE[Outcome.WIN]
        if match.winner is Outcome.LOSS:
            return f"{opponent} won the game {l}-{w}{extra}.", OUTCOME_STYLE[Outcome.LOSS]
        return f"The game ends in a tie, {w}-{l}{extra}.", OUTCOME_STYLE[Outcome.DRAW]
    if match.winner is Outcome.WIN:
        return f"You won the match {w}-{l}!", OUTCOME_STYLE[Outcome.WIN]
    return f"{opponent} won the match {l}-{w}.", OUTCOME_STYLE[Outcome.LOSS]


@dataclass(frozen=True)
class Option:
    """One selectable menu entry."""

    label: str
    value: str
    description: str = ""
    enabled: bool = True
    tag: str = ""          # shown after the label, e.g. "coming soon"


@dataclass(frozen=True)
class _Board:
    """What the scoreboard shows. A snapshot, so we can show the *old* score
    while the hands are revealed and only then flip to the new one."""

    session: Score
    match: Optional[Score]
    needed: Optional[int]
    played: int
    max_rounds: Optional[int]


@dataclass
class _View:
    title: str = ""
    left_art: Sequence[str] = art.FIST_RIGHT
    right_art: Sequence[str] = art.FIST_LEFT
    left_move: str = "?"
    right_move: str = "?"
    spread: int = 0
    lift: int = 0
    caption: Text = field(default_factory=_line)
    prompt: Text = field(default_factory=_line)
    notice: Text = field(default_factory=_line)
    board: Optional[_Board] = None


def _clock(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


class Waiter:
    """A "please wait" screen for something slow (the network): a spinner, the
    elapsed time, status lines you can change, Esc to cancel and, if a secret is
    supplied, ``p`` to show or hide it. In plain mode it just prints new lines.

    Poll ``tick()`` from the waiting loop: it redraws, reads keys and returns
    False once the player cancelled.
    """

    _ASCII = "|/-\\"
    _FANCY = "\u280b\u2819\u2839\u2838\u283c\u2834\u2826\u2827\u2807\u280f"

    def __init__(self, ui: "GameUI", title: str, crumbs: str, lines: Sequence[str],
                 secret: Optional[str]) -> None:
        self._ui = ui
        self.title, self.crumbs, self.lines = title, crumbs, list(lines)
        self.secret = secret
        self.show_secret = False
        self.cancelled = False
        self._live: Optional[Live] = None
        self._t0 = time.monotonic()
        self._last_draw = 0.0

    # -- lifecycle
    def __enter__(self) -> "Waiter":
        self._start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop()

    def _start(self) -> None:
        ui = self._ui
        if ui._interactive():
            ui._clear()
            self._live = Live(console=ui.console, auto_refresh=False)
            self._live.start()
            self._draw()
        else:
            ui._say()
            ui._say(self.title, "bold")
            for line in self.lines:
                ui._say(line)

    def _stop(self) -> None:
        if self._live is not None:
            self._live.stop()
            self._live = None

    @contextmanager
    def paused(self):
        """Hand the screen to a prompt (a name, a yes/no) and take it back after."""
        was_live = self._live is not None
        self._stop()
        try:
            yield
        finally:
            if was_live:
                self._start()

    # -- content
    def set_lines(self, lines: Sequence[str]) -> None:
        new = list(lines)
        changed, self.lines = new != self.lines, new
        if self._live is not None:
            self._draw()
        elif changed:
            for line in new:
                self._ui._say(line)

    def _draw(self) -> None:
        if self._live is None:
            return
        ui = self._ui
        frames = self._ASCII if ui.ascii_only else self._FANCY
        spinner = frames[int((time.monotonic() - self._t0) * 10) % len(frames)]
        parts: list[RenderableType] = ui._logo()
        if self.crumbs:
            parts.append(_line(self.crumbs, "dim"))
        parts += [_line(self.title, "bold"), _line(),
                  _line(f"{spinner}  {_clock(time.monotonic() - self._t0)}", "cyan"), _line()]
        parts += [_line(text) for text in self.lines]
        hint = "Esc cancel"
        if self.secret is not None:
            bullet = "*" if ui.ascii_only else "\u2022"
            shown = self.secret if self.show_secret else bullet * len(self.secret)
            parts += [_line(), _line(f"Passkey: {shown}", "bold")]
            hint += "   p " + ("hide" if self.show_secret else "show") + " passkey"
        parts += [_line(), _line(hint, "dim")]
        self._live.update(ui._vcenter(parts), refresh=True)
        self._last_draw = time.monotonic()

    # -- polling
    def tick(self) -> bool:
        if self.cancelled:
            return False
        if self._live is not None:
            key = terminal.read_key(timeout=0)
            if key == terminal.KEY_ESC:
                self.cancelled = True
                return False
            if key and key.lower() == "p" and self.secret is not None:
                self.show_secret = not self.show_secret
                self._draw()
            elif time.monotonic() - self._last_draw >= 0.1:
                self._draw()
        return True


class GameUI:
    def __init__(
        self,
        *,
        plain: bool = False,
        ascii_only: bool = False,
        animate: bool = True,
        console: Console | None = None,
    ) -> None:
        self.plain = plain
        self.ascii_only = plain or ascii_only
        self.console = console or Console(
            highlight=False, emoji=False, no_color=True if plain else None
        )
        self.animate = animate and not plain and self.console.is_terminal
        self._live: Optional[Live] = None
        self._view = _View()
        self._board = _Board(Score(), None, None, 0, None)
        self._logo_text: Optional[str] = None
        self._board_text: Optional[str] = None
        self.you = Seat("You", Side.LEFT)
        self.opponent = Seat("Computer", Side.RIGHT)

    def set_players(self, you: Seat, opponent: Seat) -> None:
        """Say who is playing and where each hand goes on *this* screen."""
        if opponent.side is you.side:                 # two hands can't share a side
            opponent = Seat(opponent.name, you.side.other)
        self.you, self.opponent = you, opponent

    # -- small helpers ---------------------------------------------------

    def _say(self, message: str = "", style: str = "") -> None:
        self.console.print(Text(message, style=style))

    def _art_on(self) -> bool:
        return (
            not self.plain
            and self.console.width >= MIN_ART_COLUMNS
            and self.console.height >= MIN_ART_ROWS
        )

    def _pause(self, seconds: float) -> None:
        if self.console.is_terminal:
            time.sleep(seconds)

    def _clear(self) -> None:
        if self.console.is_terminal:
            self.console.clear()

    def _box(self):
        return box.ASCII if self.ascii_only else box.ROUNDED

    def _vcenter(self, parts: Sequence[RenderableType]) -> Group:
        """Pad above so the block sits in the vertical middle of the screen."""
        height = len(self.console.render_lines(Group(*parts), pad=False))
        top = max(0, (self.console.height - height - 1) // 2)
        return Group(*[_line()] * top, *parts)

    def _interactive(self) -> bool:
        return not self.plain and terminal.is_interactive()

    def _logo(self) -> list[RenderableType]:
        """The RPS GAME banner, or a one-line title on small terminals."""
        if self.console.width >= 60 and self.console.height >= 22:
            if self._logo_text is None:
                self._logo_text = pyfiglet.figlet_format("RPS GAME", font="slant").rstrip()
            return [Align.center(Text(self._logo_text, style="bold cyan")), _line()]
        return [_line("ROCK PAPER SCISSORS", "bold cyan"), _line()]

    # -- menus -------------------------------------------------------------

    def choose(
        self,
        title: str,
        options: Sequence[Option],
        *,
        crumbs: str = "",
        back_label: str = "back",
        start: int = 0,
    ) -> Optional[str]:
        """Show a menu. Returns the chosen option's value, or None for back/exit.
        ``start`` is the index the cursor begins on (rich mode)."""
        if not self._interactive():
            return self._choose_plain(title, options, crumbs, back_label)
        return self._choose_rich(title, options, crumbs, back_label, start)

    def _choose_plain(self, title, options, crumbs, back_label) -> Optional[str]:
        self._say()
        if crumbs:
            self._say(crumbs, "dim")
        self._say(title, "bold")
        for i, o in enumerate(options, 1):
            tag = f" ({o.tag})" if o.tag else ""
            desc = f" - {o.description}" if o.description else ""
            self._say(f"  {i}. {o.label}{tag}{desc}")
        while True:
            raw = input(f"Choose 1-{len(options)}, or q to {back_label}: ").strip().lower()
            if raw in BACK_WORDS:
                return None
            if raw.isdigit() and 1 <= int(raw) <= len(options):
                option = options[int(raw) - 1]
                if option.enabled:
                    return option.value
                self._say(f"{option.label} is {option.tag or 'not available'}.")
            else:
                self._say(f"Please type a number from 1 to {len(options)}.")

    def _menu_screen(self, title, options, index, crumbs, notice, hint) -> Group:
        parts: list[RenderableType] = self._logo()
        if crumbs:
            parts.append(_line(crumbs, "dim"))
        parts += [_line(title, "bold"), _line()]
        rows = []
        for i, o in enumerate(options):
            selected = i == index
            label = o.label + (f"  ({o.tag})" if o.tag else "")
            if selected:
                style = "bold cyan" if o.enabled else "bold"
            else:
                style = "" if o.enabled else "dim"
            rows.append(Text(("> " if selected else "  ") + label, style=style, no_wrap=True))
        parts.append(Align.center(Group(*rows)))
        parts += [
            _line(),
            _line(options[index].description, "dim"),
            _line(notice, "yellow"),
            _line(),
            _line(hint, "dim"),
        ]
        return self._vcenter(parts)

    def _choose_rich(self, title, options, crumbs, back_label, start=0) -> Optional[str]:
        updown = "Up/Down" if self.ascii_only else "\u2191/\u2193"
        hint = f"{updown} move   Enter select   Esc {back_label}"
        index, notice = max(0, min(start, len(options) - 1)), ""
        terminal.flush_input()
        self._clear()
        live = Live(console=self.console, auto_refresh=False)
        live.start()
        try:
            while True:
                live.update(
                    self._menu_screen(title, options, index, crumbs, notice, hint), refresh=True
                )
                key = terminal.read_key()
                notice = ""
                select = key in (terminal.KEY_ENTER, terminal.KEY_RIGHT, " ")
                if key in (terminal.KEY_UP, "k"):
                    index = (index - 1) % len(options)
                elif key in (terminal.KEY_DOWN, "j"):
                    index = (index + 1) % len(options)
                elif len(key) == 1 and key.isdigit() and 1 <= int(key) <= len(options):
                    index, select = int(key) - 1, True
                elif key in (terminal.KEY_ESC, terminal.KEY_LEFT, terminal.KEY_BACKSPACE,
                             "q", "b"):
                    return None
                if select:
                    option = options[index]
                    if option.enabled:
                        return option.value
                    notice = f"{option.label} is {option.tag or 'not available yet'}."
        finally:
            live.stop()

    def ask_number(self, title: str, low: int, high: int, *, crumbs: str = "") -> Optional[int]:
        """Ask for an integer in [low, high]. None means the player went back."""
        if not self._interactive():
            return self._ask_number_plain(title, low, high)
        digits, notice = "", ""
        terminal.flush_input()
        self._clear()
        live = Live(console=self.console, auto_refresh=False)
        live.start()
        try:
            while True:
                parts: list[RenderableType] = self._logo()
                if crumbs:
                    parts.append(_line(crumbs, "dim"))
                parts += [
                    _line(title, "bold"),
                    _line(),
                    _line(f"> {digits}_", "bold cyan"),
                    _line(),
                    _line(notice, "yellow"),
                    _line(),
                    _line(f"Type a number from {low} to {high}   Enter confirm   Esc back", "dim"),
                ]
                live.update(self._vcenter(parts), refresh=True)
                key = terminal.read_key()
                notice = ""
                if len(key) == 1 and key.isdigit():
                    if len(digits) < len(str(high)):
                        digits += key
                elif key == terminal.KEY_BACKSPACE:
                    digits = digits[:-1]
                elif key == terminal.KEY_ESC:
                    return None
                elif key == terminal.KEY_ENTER:
                    if digits and low <= int(digits) <= high:
                        return int(digits)
                    notice = f"Please enter a number between {low} and {high}."
        finally:
            live.stop()

    def _ask_number_plain(self, title: str, low: int, high: int) -> Optional[int]:
        self._say()
        self._say(title, "bold")
        while True:
            raw = input(f"Number from {low} to {high}, or q to go back: ").strip().lower()
            if raw in BACK_WORDS:
                return None
            if raw.isdigit() and low <= int(raw) <= high:
                return int(raw)
            self._say(f"Please enter a number between {low} and {high}.")

    def ask_text(
        self,
        title: str,
        *,
        crumbs: str = "",
        validator: Optional[Callable[[str], Optional[str]]] = None,
        max_cells: int = 40,
        mask: bool = False,
        initial: str = "",
    ) -> Optional[str]:
        """Free-text entry (names, passkeys, codes).

        ``validator(text)`` returns an error message, or None when the text is
        fine; Enter is refused until it passes. With ``mask`` the text is shown
        as bullets and, in plain mode, read without echo. Returns the text, or
        None if the player went back (Esc, or ``/back`` in plain mode).
        """
        if not self._interactive():
            return self._ask_text_plain(title, validator, mask)
        bullet = "*" if self.ascii_only else "\u2022"
        text, notice = initial, ""
        terminal.flush_input()
        self._clear()
        live = Live(console=self.console, auto_refresh=False)
        live.start()
        try:
            while True:
                shown = bullet * len(text) if mask else text
                parts: list[RenderableType] = self._logo()
                if crumbs:
                    parts.append(_line(crumbs, "dim"))
                parts += [
                    _line(title, "bold"),
                    _line(),
                    _line(f"> {shown}_", "bold cyan"),
                    _line(),
                    _line(notice, "yellow"),
                    _line(),
                    _line(("Typing is hidden   " if mask else "") + "Enter confirm   Esc back",
                          "dim"),
                ]
                live.update(self._vcenter(parts), refresh=True)
                key = terminal.read_key()
                notice = ""
                if key == terminal.KEY_ESC:
                    return None
                if key == terminal.KEY_BACKSPACE:
                    text = text[:-1]
                elif key == "\x15":                         # Ctrl-U clears the line
                    text = ""
                elif key == terminal.KEY_ENTER:
                    error = validator(text) if validator else None
                    if error:
                        notice = error
                    else:
                        return text
                elif key and len(key) == 1 and (key.isprintable() or key in "\u200c\u200d"):
                    if cell_len(text + key) > max_cells:
                        notice = f"That is the maximum length ({max_cells})."
                    else:
                        text += key
        finally:
            live.stop()

    def _ask_text_plain(self, title, validator, mask) -> Optional[str]:
        self._say()
        self._say(title, "bold")
        prompt = "(type /back to go back) > "
        while True:
            raw = getpass.getpass(prompt) if mask else input(prompt)
            if raw.strip().lower() == "/back":
                return None
            error = validator(raw) if validator else None
            if error is None:
                return raw
            self._say(error)

    def waiting(self, title: str, *, crumbs: str = "", lines: Sequence[str] = (),
                secret: Optional[str] = None) -> Waiter:
        """Use as ``with ui.waiting("...") as w:`` and call ``w.tick()`` while waiting."""
        return Waiter(self, title, crumbs, lines, secret)

    def message(self, title: str, lines: Sequence[str], *, crumbs: str = "") -> None:
        """A centred message that waits for a key (plain mode just prints it)."""
        if not self._interactive():
            self._say()
            self._say(title, "bold")
            for line in lines:
                self._say(line)
            return
        parts: list[RenderableType] = self._logo()
        if crumbs:
            parts.append(_line(crumbs, "dim"))
        parts += [_line(title, "bold"), _line(), *[_line(l) for l in lines],
                  _line(), _line("Press any key to continue", "dim")]
        self._clear()
        self.console.print(self._vcenter(parts))
        terminal.flush_input()
        terminal.read_key()

    def confirm(self, question: str, *, crumbs: str = "") -> bool:
        """Yes/no question; anything but an explicit yes means no."""
        if not self._interactive():
            return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
        terminal.flush_input()
        self._clear()
        parts: list[RenderableType] = self._logo()
        if crumbs:
            parts.append(_line(crumbs, "dim"))
        parts += [_line(question, "bold"), _line(),
                  Text.assemble("[", ("y", "bold"), "] Yes     [", ("n", "bold"), "] No",
                                justify="center")]
        self.console.print(self._vcenter(parts))
        while True:
            key = terminal.read_key()
            if key and key.lower() == "y":
                return True
            if key and (key.lower() in ("n", "q") or key in (terminal.KEY_ESC, terminal.KEY_ENTER)):
                return False

    def farewell(self) -> None:
        if not self.plain:
            self._clear()
        self._say("Thanks for playing!", "bold")

    # -- game intro ----------------------------------------------------------

    def intro(self, *, best_of: Optional[int], rounds: Optional[int], difficulty: str,
              first_to: Optional[int] = None) -> None:
        """Plain mode prints a header; rich mode goes straight to the round screen."""
        if not self.plain:
            return
        self._say()
        self._say("ROCK PAPER SCISSORS", "bold")
        self._say(f"Mode: {mode_text(best_of, rounds, first_to)}   Computer: {difficulty}")
        self._say("Type r, p or s (or 1, 2, 3). Type q to quit.", "dim")

    # -- round lifecycle --------------------------------------------------

    @staticmethod
    def _snapshot(match: Match, session: Score) -> _Board:
        return _Board(
            session=replace(session),
            match=replace(match.score) if match.wins_needed is not None else None,
            needed=match.wins_needed,
            played=len(match.rounds),
            max_rounds=match.max_rounds,
        )

    def start_round(self, match: Match, session: Score, difficulty: str) -> None:
        """Begin a round: in rich mode, wipe the screen and draw it fresh."""
        number = len(match.rounds) + 1
        of = f" of {match.max_rounds}" if match.max_rounds else ""
        if self.plain:
            self._say()
            self._say(f"Round {number}{of}", "bold")
            return
        self._board = self._snapshot(match, session)
        self._view = _View(
            title="   |   ".join([
                "ROCK PAPER SCISSORS",
                f"{self.opponent.name}: {difficulty}" if difficulty else f"vs {self.opponent.name}",
                f"Round {number}{of}",
            ]),
            caption=_line("Your move!", "dim"),
            prompt=self._choices_prompt(),
            board=self._board,
        )
        self._clear()
        self._live = Live(console=self.console, auto_refresh=False)
        self._live.start()
        self._draw()

    def end_round(self) -> None:
        if self._live is not None:
            self._live.stop()
            self._live = None

    # -- move input ------------------------------------------------------

    def ask_move(self) -> Optional[Move]:
        """Return the chosen Move, or None if the player wants to quit."""
        if not self._interactive():
            return self._ask_line()
        return self._ask_key()

    def _ask_line(self) -> Optional[Move]:
        while True:
            raw = input("Your move (rock, paper, scissors, or quit): ")
            if raw.strip().lower() in QUIT_WORDS:
                return None
            move = Move.parse(raw)
            if move:
                return move
            self._say(
                f"'{raw.strip()}' is not a valid move. "
                "Use r, p, s, 1, 2, 3, a full word, or q to quit."
            )

    @staticmethod
    def _choices_prompt() -> Text:
        return Text.assemble(
            "Choose: ",
            "[", ("r", "bold"), "]ock   ",
            "[", ("p", "bold"), "]aper   ",
            "[", ("s", "bold"), "]cissors   ",
            "[", ("q", "bold"), "]uit",
            justify="center",
        )

    def _ask_key(self) -> Optional[Move]:
        terminal.flush_input()
        while True:
            key = terminal.read_key()
            if key.lower() == "q":
                return None
            move = Move.parse(key)
            if move:
                self._draw(prompt=_line(f"You chose {move}.", "bold"), notice=_line())
                return move
            if len(key) == 1 and key.strip() and key.isprintable():
                self._draw(
                    notice=_line(f"'{key}' is not a move. Use r, p, s (or 1-3), or q.", "yellow")
                )

    # -- rendering (round screen) ----------------------------------------

    def _draw(self, **changes) -> None:
        if self._live is None:
            return
        self._view = replace(self._view, **changes)
        self._live.update(self._render(self._view), refresh=True)

    def _render(self, v: _View) -> Group:
        parts: list[RenderableType] = [_line(v.title, "bold"), _line()]
        if self._art_on():
            parts += self._arena(v)
        else:
            left_seat, right_seat = self._seats_by_side()
            parts.append(
                Text.assemble(
                    (f"{left_seat.name.upper()}: ", "bold"), (v.left_move, PLAYER_STYLE), "      ",
                    (f"{right_seat.name.upper()}: ", "bold"), (v.right_move, CPU_STYLE),
                    justify="center",
                )
            )
        parts += [v.caption, _line()]
        if v.board is not None:
            parts += self._scoreboard_heading(SCOREBOARD_BIG_MIN_ROWS)
            parts.append(Align.center(self._board_table(v.board)))
        parts += [_line(), v.prompt, v.notice]
        return self._vcenter(parts)

    def _arena(self, v: _View) -> list[RenderableType]:
        w = art.WIDTH
        gap = GAP + 2 * v.spread
        pad = " " * max(0, (self.console.width - (2 * w + gap)) // 2)
        left_seat, right_seat = self._seats_by_side()
        header = Text.assemble(
            pad, (center_cells(left_seat.name.upper(), w), "bold"), " " * gap,
            (center_cells(right_seat.name.upper(), w), "bold"),
        )
        rows = [
            Text.assemble(pad, (l, PLAYER_STYLE), " " * gap, (r, CPU_STYLE))
            for l, r in zip(v.left_art, v.right_art)
        ]
        rows = [_line()] * v.lift + rows + [_line()] * (1 - v.lift)
        rule = Rule(characters="=", style="dim")
        return [header, rule, *rows, rule]

    def _seats_by_side(self) -> tuple[Seat, Seat]:
        """(left seat, right seat) as drawn on this screen."""
        if self.you.side is Side.LEFT:
            return self.you, self.opponent
        return self.opponent, self.you

    def _hands(self, you_move: Optional[Move], opp_move: Optional[Move]):
        """(left_art, right_art) for the two moves, honouring who sits where.

        The left seat always uses right-facing art and the right seat left-facing
        art, so the hands point at each other whichever side you chose. A None
        move means a closed fist.
        """
        def pick(move, facing_right: bool):
            if move is None:
                return art.FIST_RIGHT if facing_right else art.FIST_LEFT
            return (art.HANDS_RIGHT if facing_right else art.HANDS_LEFT)[move]

        if self.you.side is Side.LEFT:
            return pick(you_move, True), pick(opp_move, False)
        return pick(opp_move, True), pick(you_move, False)

    def _scoreboard_heading(self, big_min_rows: int) -> list[RenderableType]:
        """A medium-size SCOREBOARD banner when the screen is tall enough,
        otherwise a single bold line so nothing gets pushed off a small terminal."""
        if self.plain:
            return []
        if self.console.height >= big_min_rows and self.console.width >= 50:
            if self._board_text is None:
                self._board_text = pyfiglet.figlet_format(
                    "SCOREBOARD", font="cybermedium", width=200
                ).rstrip("\n")
            return [Align.center(Text(self._board_text, style="bold"))]
        return [_line("SCOREBOARD", "bold")]

    def _board_table(self, b: _Board) -> Table:
        table = Table(box=self._box(), header_style="bold", expand=False)
        table.add_column("Wins", style="green", justify="center", min_width=6)
        table.add_column("Losses", style="red", justify="center", min_width=6)
        table.add_column("Draws", style="yellow", justify="center", min_width=6)
        table.add_column("Win streak", justify="center", min_width=10)
        row = [str(b.session.wins), str(b.session.losses),
               str(b.session.draws), str(b.session.streak)]
        if b.match is not None:
            table.add_column(f"Match (first to {b.needed})", justify="center")
            row.append(f"{b.match.wins} - {b.match.losses}")
        if b.max_rounds is not None:
            table.add_column("Round", justify="center", min_width=7)
            row.append(f"{b.played} / {b.max_rounds}")
        table.add_row(*row)
        return table

    def _max_spread(self) -> int:
        room = (self.console.width - 2 * art.WIDTH - GAP) // 2 - 1
        return max(0, min(12, room))

    # -- showing a round ---------------------------------------------------

    def show_round(self, rnd: Round, match: Match, session: Score) -> None:
        if self.plain:
            self._show_round_plain(rnd, match, session)
            return

        verdict = OUTCOME_TEXT[rnd.outcome].upper()
        if rnd.outcome is Outcome.WIN and session.streak >= 2:
            verdict += f"   ({session.streak} wins in a row)"

        if self.animate:
            self._animate_countdown()
        left_art, right_art = self._hands(rnd.player, rnd.opponent)
        you_move, opp_move = str(rnd.player), str(rnd.opponent)
        left_move, right_move = (
            (you_move, opp_move) if self.you.side is Side.LEFT else (opp_move, you_move)
        )
        self._draw(
            left_art=left_art, right_art=right_art,
            left_move=left_move, right_move=right_move,
            spread=0, lift=0,
            caption=_line(verdict, OUTCOME_STYLE[rnd.outcome]),
            prompt=_line(f"You played {rnd.player}. {self.opponent.name} played {rnd.opponent}."),
            notice=_line(),
        )
        self._pause(HOLD_REVEAL)

        # Score updates here, then the next round wipes the hands away.
        self._board = self._snapshot(match, session)
        self._draw(board=self._board, notice=self._match_notice(match))
        self._pause(HOLD_SCORE)

    def _match_notice(self, match: Match) -> Text:
        if not match.is_over:
            return _line()
        text, style = _match_summary(match, self.opponent.name)
        if match.max_rounds is None:
            text += " A new match starts next round."
        return _line(text, style)

    def _animate_countdown(self) -> None:
        art_on = self._art_on()
        blank = dict(caption=_line(), prompt=_line(), notice=_line(), left_move="?", right_move="?")
        fist_l, fist_r = self._hands(None, None)
        if art_on:
            for spread in range(self._max_spread(), -1, -1):      # fists close in
                self._draw(left_art=fist_l, right_art=fist_r,
                           spread=spread, lift=0, **blank)
                time.sleep(0.015)
        for count in ("3", "2", "1"):                              # pump and count
            for lift in ((1, 0) if art_on else (0,)):
                self._draw(left_art=fist_l, right_art=fist_r,
                           spread=0, lift=lift,
                           **{**blank, "caption": _line(count, "bold yellow")})
                time.sleep(0.22 if art_on else 0.4)
        self._draw(left_art=fist_l, right_art=fist_r, spread=0, lift=0,
                   **{**blank, "caption": _line("SHOOT!", "bold yellow")})
        time.sleep(0.35)

    def _show_round_plain(self, rnd: Round, match: Match, session: Score) -> None:
        self._say(f"You played {rnd.player}. {self.opponent.name} played {rnd.opponent}.")
        result = OUTCOME_TEXT[rnd.outcome]
        if rnd.outcome is Outcome.WIN and session.streak >= 2:
            result += f" ({session.streak} wins in a row)"
        self._say(result)
        if match.wins_needed is not None:
            self._say(
                f"Match: You {match.score.wins} - {match.score.losses} {self.opponent.name} "
                f"(first to {match.wins_needed})"
            )
        if match.max_rounds:
            self._say(f"Round {len(match.rounds)} of {match.max_rounds} played.")
        if match.is_over:
            self._say(_match_summary(match, self.opponent.name)[0])
        self._say(
            f"Score: {session.wins} wins, {session.losses} losses, {session.draws} draws"
        )

    # -- statistics and results -------------------------------------------

    def _stats_table(self, rows: Sequence[tuple[str, Score | Stats]]) -> Table:
        table = Table(box=self._box(), header_style="bold", expand=False)
        table.add_column("")
        table.add_column("Wins", style="green", justify="right")
        table.add_column("Losses", style="red", justify="right")
        table.add_column("Draws", style="yellow", justify="right")
        table.add_column("Rounds", justify="right")
        table.add_column("Win rate", justify="right")
        table.add_column("Best streak", justify="right")
        for label, s in rows:
            table.add_row(label, str(s.wins), str(s.losses), str(s.draws),
                          str(s.rounds), f"{s.win_rate:.0%}", str(s.best_streak))
        return table

    @staticmethod
    def _stats_line(label: str, s: Score | Stats) -> str:
        return (f"{label}: Wins {s.wins}, Losses {s.losses}, Draws {s.draws}, "
                f"Rounds {s.rounds}, Win rate {s.win_rate:.0%}, Best streak {s.best_streak}")

    def goodbye(
        self,
        session: Score,
        matches: Optional[Score] = None,
        lifetime: Optional[Stats] = None,
        *,
        title: str = "Thanks for playing!",
        finished: Optional[Match] = None,
        pause: bool = False,
    ) -> None:
        """Results screen: a centred scoreboard. With ``pause`` it waits for a
        key (used when returning to the menu); otherwise it stays on screen."""
        self.end_round()
        match_line = None
        if matches is not None and matches.rounds:
            match_line = f"Matches won: {matches.wins}   Matches lost: {matches.losses}"
        summary = (_match_summary(finished, self.opponent.name)
                   if finished is not None and finished.is_over else None)

        if self.plain:
            self._say()
            self._say(title, "bold")
            if summary:
                self._say(summary[0])
            if session.rounds:
                self._say(self._stats_line("This session", session))
                if match_line:
                    self._say(match_line)
            if lifetime is not None and lifetime.rounds:
                self._say(self._stats_line("All time", lifetime))
            return

        parts: list[RenderableType] = [_line(title, "bold"), _line()]
        if summary:
            parts += [_line(summary[0], summary[1]), _line()]
        if session.rounds:
            rows: list[tuple[str, Score | Stats]] = [("This session", session)]
            if lifetime is not None and lifetime.rounds:
                rows.append(("All time", lifetime))
            parts += self._scoreboard_heading(22)
            parts.append(Align.center(self._stats_table(rows)))
            if match_line:
                parts += [_line(), _line(match_line)]
        else:
            parts.append(_line("No rounds played this time.", "dim"))
        parts.append(_line())
        if pause:
            parts.append(_line("Press any key to return to the menu", "bold"))
        self._clear()
        self.console.print(self._vcenter(parts))
        if pause and terminal.is_interactive():
            terminal.flush_input()
            terminal.read_key()

    def show_stats(self, stats: Stats, *, wait: bool = False) -> None:
        """Lifetime numbers. Inline for `rps --stats`; with ``wait`` a centred
        full screen that stays until a key is pressed (used from the Stats menu)."""
        screen = wait and self._interactive()
        if stats.rounds == 0:
            if screen:
                self._stats_screen([_line("No games recorded yet. Play a few rounds first!", "dim")])
            else:
                self._say("No games recorded yet. Play a few rounds first!")
            return
        fav = stats.favourite_move
        extras = [f"Sessions: {stats.sessions}",
                  f"Matches won: {stats.matches_won}   lost: {stats.matches_lost}"]
        if fav:
            extras.append(f"Favourite move: {fav[0]} ({fav[1]:.0%} of your throws)")
        if self.plain:
            self._say("Lifetime statistics", "bold")
            self._say(self._stats_line("All time", stats))
            for extra in extras:
                self._say(extra)
            return
        parts: list[RenderableType] = [
            _line("LIFETIME STATISTICS", "bold"),
            Align.center(self._stats_table([("All time", stats)])),
            *[_line(extra) for extra in extras],
        ]
        if screen:
            self._stats_screen(parts)
            return
        self._say()
        for part in parts:
            self.console.print(part)
        self._say()

    def _stats_screen(self, parts: list[RenderableType]) -> None:
        self._clear()
        self.console.print(self._vcenter([*parts, _line(),
                                          _line("Press any key to go back", "dim")]))
        terminal.flush_input()
        terminal.read_key()
