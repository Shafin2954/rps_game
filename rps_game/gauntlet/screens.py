"""How the Gauntlet looks.

Like the classic screens there are two presentations behind one class: a
full-screen fight view (ASCII hands, health bars, Focus pips, a strip of recent
throws) and a plain, linear one for screen readers and pipes. Everything said
with colour or a bar is also said in words and numbers.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field, replace
from typing import Optional, Sequence

from rich.align import Align
from rich.cells import cell_len
from rich.console import Group, RenderableType
from rich.live import Live
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from .. import art, fx, terminal
from ..engine import Move, Outcome
from ..ui import (BEATEN_STYLE, BURST_STYLE, CPU_STYLE, OUTCOME_STYLE, OUTCOME_TEXT, PLAYER_STYLE,
                  QUIT_WORDS, GameUI, Option)
from . import banter
from .foes import FLOORS, FoeSpec
from .relics import RELICS, Relic
from .rules import TECHNIQUE_TEXT, TRAITS, Duel, Exchange, Technique
from .run import REST_HEAL, FightReport, Run

COLUMN = 34                         # each fighter's column of text, in cells
BLOCK = 2 * COLUMN
MARGIN = (COLUMN - art.WIDTH) // 2  # blank cells either side of a hand in its column
CLASH_REACH = MARGIN - 1            # how far a hand lunges before the two meet
MIN_ART_COLUMNS = BLOCK + 2
MIN_ART_ROWS = 24
BAR = 12                            # cells in a health bar
HISTORY = 14                        # recent rounds shown in the strip
HOLD_RESULT = 1.2                   # seconds a round's result stays up

ABANDON = "Abandon the run? It ends here and is scored as it stands."
TECHNIQUE_KEYS = {"f": Technique.FORESIGHT, "g": Technique.GUARD, "c": Technique.CHARGE}
TECHNIQUE_WORDS = {**TECHNIQUE_KEYS, **{t.value: t for t in Technique}}
VERBS = {
    Move.ROCK: "Rock crushes scissors",
    Move.PAPER: "Paper covers rock",
    Move.SCISSORS: "Scissors cut paper",
}
LETTER = {Move.ROCK: "R", Move.PAPER: "P", Move.SCISSORS: "S"}
RESULT_LETTER = {Outcome.WIN: "W", Outcome.LOSS: "L", Outcome.DRAW: "D"}

INTRO = (
    "Ten foes stand between you and the top. Each has a tell: read it.",
    "",
    "Win a round and you deal damage. Lose one and you take it.",
    "Losing or drawing a round earns 1 Focus. Spend it before you throw:",
)
TECHNIQUE_HELP = (
    ("f", "Foresight (2 Focus)", "rules out one throw the foe will not make"),
    ("g", "Guard (1 Focus)", "you take no damage this round"),
    ("c", "Charge (2 Focus)", "a win this round deals double damage"),
)
OUTRO = ("After every fight you heal a little and choose a relic, or rest.",)


def _line(text: str = "", style: str = "") -> Text:
    return Text(text, style=style, justify="center", no_wrap=True)


def _fit(text: Text, width: int) -> Text:
    """``text`` centred in exactly ``width`` cells (trimmed if it is too long)."""
    text = text.copy()
    text.truncate(width)
    spare = width - cell_len(text.plain)
    out = Text(" " * (spare // 2))
    out.append_text(text)
    out.append(" " * (spare - spare // 2))
    return out


def headline(x: Exchange, foe: str) -> str:
    """One sentence for a finished round: who won, how, and what it cost."""
    verdict = OUTCOME_TEXT[x.round.outcome]
    if x.round.outcome is Outcome.WIN:
        return f"{verdict} {VERBS[x.round.player]}: {x.dealt} damage to {foe}."
    if x.round.outcome is Outcome.LOSS:
        cost = f"you take {x.taken} damage" if x.taken else "but you take no damage"
        return f"{verdict} {VERBS[x.round.opponent]}: {cost}."
    if x.round.player is x.round.opponent:
        return f"{verdict} You both threw {x.round.player}."
    return f"{verdict} {VERBS[x.round.opponent]}, but luck was on your side."


def foe_facts(spec: FoeSpec) -> str:
    traits = [TRAITS[t][0] for t in spec.traits]
    return " · ".join([f"Hits for {spec.damage}", *traits])


@dataclass
class _View:
    title: str = ""
    foe_name: str = ""
    foe_facts: str = ""
    hero_hp: int = 0
    hero_max: int = 1
    focus: int = 0
    max_focus: int = 0
    shield: int = 0
    foe_hp: int = 0
    foe_max: int = 1
    left_art: Sequence[str] = art.FIST_RIGHT
    right_art: Sequence[str] = art.FIST_LEFT
    left_word: str = "?"
    right_word: str = "?"
    spread: int = 0
    lift: int = 0
    close: int = 0                              # the clash, as in fx.Beat
    back: tuple[int, int] = (0, 0)
    burst: Sequence[str] = ()
    shake: int = 0
    beaten: tuple[bool, bool] = (False, False)
    caption: Text = field(default_factory=_line)
    detail: Text = field(default_factory=_line)
    prompt: Text = field(default_factory=_line)
    notice: Text = field(default_factory=_line)
    history: Sequence[Exchange] = ()


class GauntletScreens:
    def __init__(self, ui: GameUI) -> None:
        self.ui = ui
        self.console = ui.console
        self._live: Optional[Live] = None
        self._view = _View()
        self._chatter = random.Random()             # reseeded per fight, so a seed replays
        self._said = ""                             # the foe's latest line, kept for the next round
        self._last_words = ""                       # what it said before that

    # ================================================================ small pieces

    def _say(self, message: str = "", style: str = "") -> None:
        self.ui._say(message, style)

    def _art_on(self) -> bool:
        return (not self.ui.plain and self.console.width >= MIN_ART_COLUMNS
                and self.console.height >= MIN_ART_ROWS)

    def _dot(self) -> str:
        return " - " if self.ui.ascii_only else " · "

    def _bar(self, value: int, maximum: int, width: int = BAR) -> Text:
        maximum = max(1, maximum)
        filled = 0 if value <= 0 else max(1, round(width * value / maximum))
        share = value / maximum
        style = "green" if share > 0.5 else "yellow" if share > 0.25 else "red"
        full, empty = ("#", "-") if self.ui.ascii_only else ("█", "░")
        bar = Text("HP " if self.ui.ascii_only else "♥ ", style=style)
        bar.append(full * filled, style=style)
        bar.append(empty * (width - filled), style="dim")
        bar.append(f" {value}/{maximum}", style="bold")
        return bar

    def _pips(self, focus: int, maximum: int, shield: int) -> Text:
        on, off = ("*", ".") if self.ui.ascii_only else ("●", "○")
        pips = Text(" ".join([on] * focus + [off] * (maximum - focus)), style="yellow")
        pips.append(f"  Focus {focus}/{maximum}", style="")
        if shield:
            pips.append(f"{self._dot()}Shield {shield}", style="bold")
        return pips

    def _ladder(self, run: Run) -> Text:
        """The ten floors on one line: cleared, [current], gatekeepers in red."""
        line = Text(justify="center", no_wrap=True)
        for number in range(1, FLOORS + 1):
            if number == run.floor and not run.victory:
                line.append(f"[{number}]", style="bold yellow")
            elif number <= run.floors_cleared:
                line.append(f" {number} ", style="green")
            else:
                line.append(f" {number} ", style="red" if number in (5, FLOORS) else "dim")
        return line

    def _seed_text(self, run: Run) -> str:
        if run.daily:
            return f"Daily Run {run.daily}"
        return f"Seed {run.seed}"

    def card(self, title: str, lines: Sequence[RenderableType | str], *,
             footer: str = "Press any key to continue", wait: bool = True) -> None:
        self.ui.page(title, lines, footer=footer, wait=wait)

    # ================================================================ before a fight

    def briefing(self, run: Run) -> None:
        what = (f"Daily Run {run.daily}: the same climb for everyone today." if run.daily
                else f"Seed {run.seed}: share it to race a friend up the same tower.")
        if self.ui.plain:
            techniques: list[RenderableType | str] = [
                f"{key} = {name}: {text}" for key, name, text in TECHNIQUE_HELP]
        else:
            grid = Table.grid(padding=(0, 2))
            for key, name, text in TECHNIQUE_HELP:
                grid.add_row(Text(key, style="bold"), Text(name, style="bold"), text)
            techniques = [Align.center(grid)]
        self.card("THE GAUNTLET",
                  [*INTRO, *techniques, "", *OUTRO, "", Text(what, style="dim", justify="center")],
                  footer="Press any key to begin")

    def foe_card(self, run: Run) -> None:
        spec, hero = run.foe, run.hero
        dot = self._dot()
        lines: list[RenderableType | str] = [
            self._ladder(run),
            "",
            _line(spec.full_name.upper(), CPU_STYLE),
            f"{spec.hp} HP{dot}hits for {spec.damage}",
            Text(f'"{spec.tell}"', style="italic", justify="center"),
        ]
        lines += [Text(f"{TRAITS[t][0]}: {TRAITS[t][1]}", style="yellow", justify="center")
                  for t in spec.traits]
        relics = len(hero.relics)
        held = f"{relics} relic{'' if relics == 1 else 's'}"
        lines += ["", f"You: {hero.hp}/{hero.max_hp} HP{dot}{held}{dot}Score {run.score}"]
        self.card(f"FLOOR {run.floor} OF {FLOORS}", lines, footer="Press any key to fight")

    def info_lines(self, run: Run) -> list[str]:
        spec, hero = run.foe, run.hero
        lines = [spec.full_name, f'"{spec.tell}"']
        lines += [f"{TRAITS[t][0]}: {TRAITS[t][1]}" for t in spec.traits]
        lines.append("")
        if hero.relics:
            lines += [f"{RELICS[key].name}: {RELICS[key].text}" for key in hero.relics]
        else:
            lines.append("You hold no relics yet.")
        lines.append("")
        duel = run.duel
        for key, technique in TECHNIQUE_KEYS.items():
            cost = duel.cost(technique) if duel else 0
            lines.append(f"{key} = {technique.value.capitalize()} ({cost} Focus): "
                         f"{TECHNIQUE_TEXT[technique]}")
        return lines

    # ================================================================ the fight

    def begin_fight(self, run: Run) -> None:
        duel, spec, hero = run.duel, run.foe, run.hero
        assert duel is not None
        self._chatter = random.Random(f"{run.seed}|banter|{run.floor}")
        self._said = self._last_words = ""
        self._view = _View(
            foe_name=spec.full_name.upper(), foe_facts=foe_facts(spec),
            hero_hp=hero.hp, hero_max=hero.max_hp, focus=hero.focus, max_focus=hero.max_focus,
            shield=hero.shield, foe_hp=duel.foe.hp, foe_max=duel.foe.max_hp,
        )
        if self.ui.plain:
            return
        self.ui._clear()
        self._live = Live(console=self.console, auto_refresh=False)
        self._live.start()

    def end_fight(self) -> None:
        if self._live is not None:
            self._live.stop()
            self._live = None

    def begin_round(self, run: Run) -> None:
        duel, spec, hero = run.duel, run.foe, run.hero
        assert duel is not None
        scouted = ""
        if duel.scouted is not None and duel.round_number == 1:
            scouted = f"Spyglass: {spec.name} opens with {duel.scouted}."
        if self._live is None:
            self._say()
            self._say(f"Round {duel.round_number}", "bold")
            self._say(f"You: {hero.hp}/{hero.max_hp} HP, Focus {hero.focus}/{hero.max_focus}"
                      + (f", Shield {hero.shield}" if hero.shield else "")
                      + f". {spec.name}: {duel.foe.hp}/{duel.foe.max_hp} HP.")
            if scouted:
                self._say(scouted)
            return
        self._draw(
            title="   |   ".join(["GAUNTLET", f"Floor {run.floor} of {FLOORS}",
                                  f"Round {duel.round_number}", self._seed_text(run)]),
            left_art=art.FIST_RIGHT, right_art=art.FIST_LEFT, left_word="?", right_word="?",
            spread=0, lift=0, close=0, back=(0, 0), burst=(), shake=0, beaten=(False, False),
            hero_hp=hero.hp, hero_max=hero.max_hp, focus=hero.focus, max_focus=hero.max_focus,
            shield=hero.shield, foe_hp=duel.foe.hp, foe_max=duel.foe.max_hp,
            caption=_line("Your move!", "dim"),
            detail=Text(f'"{spec.tell}"', style="dim italic", justify="center", no_wrap=True),
            prompt=self._prompt(duel, None),
            notice=_line(scouted, "bold") if scouted else _line(self._said, "italic magenta"),
            history=tuple(duel.exchanges),
        )
        self._said = ""

    def _prompt(self, duel: Duel, armed: Optional[Technique]) -> Text:
        """The keys on offer. Techniques are dimmed when there is no Focus for them
        and highlighted once armed. It may wrap on a narrow terminal."""
        prompt = Text(justify="center")
        for word in ("rock", "paper", "scissors"):
            prompt.append("[")
            prompt.append(word[0], style="bold")
            prompt.append(f"]{word[1:]} ")
        prompt.append(" ")
        for key, technique in TECHNIQUE_KEYS.items():
            usable = duel.can_use(technique) or armed is technique
            style = "reverse bold" if armed is technique else "" if usable else "dim"
            piece = Text(style=style)
            piece.append("[")
            piece.append(key, style="bold" if usable else "")
            piece.append(f"]{technique.value[1:]}({duel.cost(technique)})")
            prompt.append_text(piece)
            prompt.append(" ")
        prompt.append(" [")
        prompt.append("i", style="bold")
        prompt.append("]nfo [")
        prompt.append("q", style="bold")
        prompt.append("]uit")
        return prompt

    def ask_action(self, run: Run) -> Optional[tuple[Move, Optional[Technique]]]:
        """The hero's throw and the technique armed for it; None to abandon the run."""
        if not self.ui._interactive():
            return self._ask_action_line(run)
        return self._ask_action_key(run)

    def _arm(self, duel: Duel, armed: Optional[Technique], technique: Technique,
             foe: str) -> tuple[Optional[Technique], str]:
        """Handle a technique key. Returns (what is armed now, what to tell the player)."""
        name = technique.value.capitalize()
        if armed is Technique.FORESIGHT:
            if technique is Technique.FORESIGHT:
                return armed, f"Foresight: {foe} will not throw {duel.foresee()}."
            return armed, "One technique per round, and Foresight is already spent."
        if armed is technique:
            return None, f"{name} cancelled."
        if not duel.can_use(technique):
            return armed, (f"{name} needs {duel.cost(technique)} Focus "
                           f"and you have {duel.hero.focus}.")
        if technique is Technique.FORESIGHT:
            return technique, f"Foresight: {foe} will not throw {duel.foresee()}."
        return technique, f"{name} ready: {TECHNIQUE_TEXT[technique]}"

    def _ask_action_line(self, run: Run) -> Optional[tuple[Move, Optional[Technique]]]:
        duel = run.duel
        assert duel is not None
        armed: Optional[Technique] = None
        while True:
            raw = input("Your move (rock, paper, scissors; f, g or c for a technique; "
                        "i for info; q to quit): ").strip().lower()
            if raw in QUIT_WORDS:
                if self.ui.confirm(ABANDON):
                    return None
                continue
            if raw in ("i", "info"):
                for line in self.info_lines(run):
                    self._say(line)
                continue
            technique = TECHNIQUE_WORDS.get(raw)
            if technique is not None:
                armed, said = self._arm(duel, armed, technique, run.foe.name)
                self._say(said)
                continue
            move = Move.parse(raw)
            if move:
                return move, armed
            self._say(f"'{raw}' is not a valid move. Use r, p, s (or 1-3); f, g, c; i; or q.")

    def _ask_action_key(self, run: Run) -> Optional[tuple[Move, Optional[Technique]]]:
        duel = run.duel
        assert duel is not None
        armed: Optional[Technique] = None
        terminal.flush_input()
        while True:
            key = terminal.read_key()
            low = key.lower() if len(key) == 1 else key
            if low == "q" or key == terminal.KEY_ESC:
                self._pause_live()
                if self.ui.confirm(ABANDON):
                    return None
                self._resume_live()
                continue
            if low == "i":
                self._pause_live()
                self.card("FIELD NOTES", self.info_lines(run))
                self._resume_live()
                continue
            technique = TECHNIQUE_KEYS.get(low)
            if technique is not None:
                armed, said = self._arm(duel, armed, technique, run.foe.name)
                self._draw(focus=duel.hero.focus, prompt=self._prompt(duel, armed),
                           notice=_line(said, "bold"))
                continue
            move = Move.parse(key)
            if move:
                self._draw(prompt=_line(f"You chose {move}.", "bold"), notice=_line())
                return move, armed
            if len(key) == 1 and key.strip() and key.isprintable():
                self._draw(notice=_line(
                    f"'{key}' is not a move. Use r, p, s (or 1-3), f, g, c, i or q.", "yellow"))

    def show_exchange(self, run: Run, x: Exchange) -> None:
        duel, spec, hero = run.duel, run.foe, run.hero
        assert duel is not None
        text = headline(x, spec.name)
        notes = self._dot().join(x.notes)
        words = banter.quip(spec.key, duel, x, self._chatter, avoid=self._last_words)
        if duel.over:
            words = banter.last_words(spec.key, hero_won=duel.won)
        self._last_words = words or self._last_words
        self._said = f'{spec.name}: "{words}"' if words else ""
        if self._live is None:
            self._say(f"You played {x.round.player}. {spec.name} played {x.round.opponent}.")
            self._say(text)
            if notes:
                self._say(notes)
            if self._said:
                self._say(self._said)
            return

        if self.ui.animate:
            self._countdown()
        style = OUTCOME_STYLE[x.round.outcome]
        self._draw(
            left_art=art.HANDS_RIGHT[x.round.player], right_art=art.HANDS_LEFT[x.round.opponent],
            left_word=str(x.round.player), right_word=str(x.round.opponent), spread=0, lift=0,
            caption=_line(text.upper(), style), detail=_line(notes, "dim"),
            prompt=_line(), notice=_line(self._said, "italic magenta"),
            history=tuple(duel.exchanges),
            focus=hero.focus, max_focus=hero.max_focus, shield=hero.shield,
        )
        animated = self.ui.animate and self._art_on()
        if animated:
            self._clash(x)
        # Drain the bars a step at a time so the hit reads as a hit.
        before_hero, before_foe = self._view.hero_hp, self._view.foe_hp
        steps = 3 if self.ui.animate else 1
        for step in range(1, steps + 1):
            self._draw(
                hero_hp=before_hero + (hero.hp - before_hero) * step // steps,
                foe_hp=before_foe + (duel.foe.hp - before_foe) * step // steps,
                hero_max=hero.max_hp,
            )
            if self.ui.animate:
                time.sleep(0.07)
        if animated and duel.over:
            self._knock_out(hero_fell=not duel.won)
        self.ui._pause(HOLD_RESULT)

    def _clash(self, x: Exchange) -> None:
        """The hands meet: the loser's is crushed, wrapped or cut (see fx.clash)."""
        outcome = x.round.outcome
        shade = "#" if self.ui.ascii_only else fx.SHADE
        beats = fx.clash(
            art.HANDS_RIGHT[x.round.player], art.HANDS_LEFT[x.round.opponent],
            winner={Outcome.WIN: 0, Outcome.LOSS: 1}.get(outcome),
            move=x.round.player if outcome is Outcome.WIN else x.round.opponent,
            reach=CLASH_REACH, shade=shade,
        )
        for beat in beats:
            self._draw(left_art=beat.left, right_art=beat.right, close=beat.close,
                       back=beat.back, burst=beat.burst, shake=beat.shake, beaten=beat.beaten)
            time.sleep(beat.hold)

    def _knock_out(self, *, hero_fell: bool) -> None:
        """Whoever just hit 0 HP crumbles to dust under a K.O. burst."""
        fallen = self._view.left_art if hero_fell else self._view.right_art
        for frame in fx.dissolve(fallen, 6, random.Random()):
            change = {"left_art": frame} if hero_fell else {"right_art": frame}
            self._draw(burst=fx.KO, **change)
            time.sleep(0.07)

    def _countdown(self) -> None:
        blank = {"caption": _line(), "detail": _line(), "prompt": _line(), "notice": _line(),
                 "left_word": "?", "right_word": "?",
                 "left_art": art.FIST_RIGHT, "right_art": art.FIST_LEFT}
        art_on = self._art_on()
        if art_on:
            for spread in range(MARGIN, -1, -1):
                self._draw(spread=spread, lift=0, **blank)
                time.sleep(0.012)
        for count in ("3", "2", "1"):
            for lift in ((1, 0) if art_on else (0,)):
                self._draw(spread=0, lift=lift,
                           **{**blank, "caption": _line(count, "bold yellow")})
                time.sleep(0.11 if art_on else 0.22)
        self._draw(spread=0, lift=0, **{**blank, "caption": _line("SHOOT!", "bold yellow")})
        time.sleep(0.2)

    # -- drawing ------------------------------------------------------------

    def _pause_live(self) -> None:
        if self._live is not None:
            self._live.stop()

    def _resume_live(self) -> None:
        if self._live is not None:
            self.ui._clear()
            self._live = Live(console=self.console, auto_refresh=False)
            self._live.start()
            self._draw()

    def _draw(self, **changes) -> None:
        self._view = replace(self._view, **changes)
        if self._live is not None:
            self._live.update(self._render(self._view), refresh=True)

    def _columns(self, left: Text, right: Text) -> Text:
        """Two cells side by side, each centred over its own hand."""
        row = Text(" " * max(0, (self.console.width - BLOCK) // 2), no_wrap=True)
        row.append_text(_fit(left, COLUMN))
        row.append_text(_fit(right, COLUMN))
        return row

    def _history(self, v: _View) -> list[RenderableType]:
        recent = list(v.history)[-HISTORY:]
        if not recent:
            return [_line(), _line("No rounds played yet in this fight.", "dim"), _line()]
        rows = []
        for label, style, letters in (
            ("You", PLAYER_STYLE, [LETTER[x.round.player] for x in recent]),
            ("Foe", CPU_STYLE, [LETTER[x.round.opponent] for x in recent]),
        ):
            row = Text(f"{label}  ", style="dim", justify="center", no_wrap=True)
            row.append(" ".join(letters), style=style)
            rows.append(row)
        marks = Text("     ", justify="center", no_wrap=True)
        for i, x in enumerate(recent):
            marks.append(RESULT_LETTER[x.round.outcome], style=OUTCOME_STYLE[x.round.outcome])
            if i < len(recent) - 1:
                marks.append(" ")
        return [*rows, marks]

    def _render(self, v: _View) -> Group:
        hero_bar = self._bar(v.hero_hp, v.hero_max)
        foe_bar = self._bar(v.foe_hp, v.foe_max)
        pips = self._pips(v.focus, v.max_focus, v.shield)
        parts: list[RenderableType] = [_line(v.title, "bold"), _line()]
        if self._art_on():
            edge = max(0, (self.console.width - BLOCK) // 2)
            left_x = edge + MARGIN - v.spread + v.close - v.back[0] + v.shake
            right_x = (edge + COLUMN + MARGIN + v.spread - v.close + v.back[1] + v.shake)
            styles = {
                "left": BEATEN_STYLE[PLAYER_STYLE] if v.beaten[0] else PLAYER_STYLE,
                "right": BEATEN_STYLE[CPU_STYLE] if v.beaten[1] else CPU_STYLE,
                "burst": BURST_STYLE,
            }
            rows: list[RenderableType] = []
            for text, spans in fx.compose(v.left_art, v.right_art, left_x, right_x, v.burst):
                row = Text(text, no_wrap=True)
                for start, end, role in spans:
                    row.stylize(styles[role], start, end)
                rows.append(row)
            rows = [_line()] * v.lift + rows + [_line()] * (1 - v.lift)
            rule = Rule(characters="=", style="dim")
            parts += [
                self._columns(Text("YOU", style="bold"), Text(v.foe_name, style="bold")),
                self._columns(hero_bar, foe_bar),
                self._columns(pips, Text(v.foe_facts, style="dim")),
                rule, *rows, rule,
            ]
        else:
            hero_row = Text("YOU  ", style="bold", justify="center", no_wrap=True)
            hero_row.append_text(hero_bar)
            hero_row.append("  ")
            hero_row.append_text(pips)
            foe_row = Text(f"{v.foe_name}  ", style="bold", justify="center", no_wrap=True)
            foe_row.append_text(foe_bar)
            parts += [
                hero_row, foe_row, _line(v.foe_facts, "dim"), _line(),
                Text.assemble(("YOU: ", "bold"), (v.left_word, PLAYER_STYLE), "      ",
                              ("FOE: ", "bold"), (v.right_word, CPU_STYLE), justify="center"),
            ]
        parts += [v.caption, v.detail, _line(), *self._history(v), _line(), v.prompt, v.notice]
        return self.ui._vcenter(parts)

    # ================================================================ after a fight

    def fight_won(self, run: Run, report: FightReport) -> tuple[list[RenderableType], list[str]]:
        """(rich parts, plain lines) announcing a victory; shown above the reward menu."""
        hero = run.hero
        lines = [f"{report.foe.full_name} is defeated!"]
        gained = f"+{report.points} points"
        if report.healed:
            gained += f", and you heal {report.healed} HP"
        lines.append(gained + ".")
        lines += list(report.notes)
        lines.append(f"You: {hero.hp}/{hero.max_hp} HP{self._dot()}Score {run.score}")
        rich: list[RenderableType] = [_line(lines[0], OUTCOME_STYLE[Outcome.WIN])]
        rich += [_line(text) for text in lines[1:]]
        return rich, lines

    def choose_reward(self, run: Run, report: FightReport,
                      offers: Sequence[Relic]) -> Optional[str]:
        """A relic key, "rest", or None if the player abandons the run."""
        options = [Option(relic.name, relic.key, relic.text) for relic in offers]
        options.append(Option("Rest", "rest",
                              f"Take no relic. Heal {REST_HEAL} HP instead."))
        rich, plain = self.fight_won(run, report)
        while True:
            pick = self.ui.choose("Choose a reward", options, header=rich, plain_header=plain,
                                  back_label="abandon the run")
            if pick is not None:
                return pick
            if self.ui.confirm(ABANDON):
                return None

    def reward_taken(self, text: str) -> None:
        if not self.ui._interactive():
            self._say(text)

    def summary(self, run: Run, extra: Sequence[str] = (), *, pause: bool = False) -> None:
        """The end of a run: how far, how well, and what it earned."""
        tally, dot = run.tally, self._dot()
        if run.victory:
            title, style = "YOU CONQUERED THE GAUNTLET!", OUTCOME_STYLE[Outcome.WIN]
            fate = "The Oracle did not see that coming."
        elif run.fallen_to:
            spec = next(s for s in run.ladder if s.key == run.fallen_to)
            title, style = "THE GAUNTLET CLAIMS YOU", OUTCOME_STYLE[Outcome.LOSS]
            fate = f"You fell on floor {run.floor} to {spec.full_name}."
        else:
            title, style = "RUN ABANDONED", OUTCOME_STYLE[Outcome.DRAW]
            fate = f"You walked away on floor {run.floor}."
        decided = tally.wins + tally.losses
        rate = f"{tally.wins / decided:.0%}" if decided else "n/a"
        relics = ", ".join(RELICS[key].name for key in run.hero.relics) or "none"
        rounds = dot.join([f"Rounds {tally.rounds}", f"Won {tally.wins}", f"Lost {tally.losses}",
                           f"Drawn {tally.draws}", f"Win rate {rate}"])
        lines = [
            fate,
            f"Score {run.score}{dot}Floors cleared {run.floors_cleared} of {FLOORS}",
            rounds,
            f"Relics: {relics}",
            self._seed_text(run),
            *extra,
        ]
        self.end_fight()
        if run.victory:
            self.ui.celebrate("CONQUERED!", seconds=3.5)
        if self.ui.plain:
            self._say()
            self._say(title, "bold")
            for text in lines:
                self._say(text)
            return
        parts: list[RenderableType] = [_line(title, style), _line()]
        parts += [Text(text, justify="center") for text in lines]
        wait = pause and self.ui._interactive()
        if wait:
            parts += [_line(), _line("Press any key to return to the menu", "bold")]
        self.ui._clear()
        self.console.print(self.ui._vcenter(parts))
        if wait:
            terminal.flush_input()
            terminal.read_key()
