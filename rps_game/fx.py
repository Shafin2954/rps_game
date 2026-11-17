"""ASCII effects: what happens between "SHOOT!" and the score.

Everything here is pure. Hand art goes in (a tuple of equal-length strings),
new art or a list of frames comes out; no terminal, no clock. The screens
decide how fast to play the frames and what colours to use, so the effects can
be tested as data and reused by the classic arena and the Gauntlet alike.

* ``crush`` / ``cover`` / ``cut`` - what a winning rock, paper or scissors does
  to the hand it beat.
* ``clash``    - the whole exchange as a list of ``Beat``s: lunge, impact, recoil.
* ``dissolve`` - a beaten fighter's hand falling to dust.
* ``compose``  - two hands and a burst laid onto one canvas, with the spans to colour.
* ``fireworks`` - a particle show for the big wins.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Iterator, Optional, Sequence

from .engine import Move

Art = Sequence[str]

SHADE = "▒"            # what paper covers a hand with (``#`` in ASCII mode)
BURST = (
    r" \ | / ",
    r"-- * --",
    r" / | \ ",
)
SPARK = (
    "       ",
    "   *   ",
    "       ",
)
CLANG = (
    "   |   ",
    " >-+-< ",
    "   |   ",
)
WORDS = {Move.ROCK: "CRUNCH!", Move.PAPER: "WRAP!", Move.SCISSORS: "SNIP!"}
DRAW_WORD = "CLANG!"
KO = ("  \\ | /  ", "-- K.O. --", "  / | \\  ")
_RUBBLE = "._,.'_."
_FIREWORK_COLOURS = ("red", "yellow", "green", "cyan", "magenta", "bright_white", "bright_blue")


# ---------------------------------------------------------------- what a win does

def crush(art: Art, step: int) -> tuple[str, ...]:
    """Rock lands: the hand is driven ``step`` rows into the floor, leaving rubble."""
    rows, height, width = list(art), len(art), len(art[0])
    step = max(0, min(step, height))
    if step == 0:
        return tuple(rows)
    sunk = [" " * width] * step + rows[:height - step]
    if step >= 2:                                    # the bottom row breaks up
        gone = rows[height - step:]
        sunk[-1] = "".join(
            _RUBBLE[col % len(_RUBBLE)] if any(row[col] != " " for row in gone) else sunk[-1][col]
            for col in range(width)
        )
    return tuple(sunk)


def cover(art: Art, step: int, *, from_left: bool, shade: str = SHADE, steps: int = 3
          ) -> tuple[str, ...]:
    """Paper wraps the hand: its ink turns to ``shade``, sweeping in from one side."""
    width = len(art[0])
    reach = math.ceil(width * max(0, min(step, steps)) / steps)
    covered = range(reach) if from_left else range(width - reach, width)
    return tuple(
        "".join(shade if col in covered and ch != " " else ch for col, ch in enumerate(row))
        for row in art
    )


def cut(art: Art, step: int, *, from_left: bool) -> tuple[str, ...]:
    """Scissors go through: a diagonal slash, then the two halves drift apart."""
    height, width = len(art), len(art[0])
    if step <= 0:
        return tuple(art)
    out = []
    for r, row in enumerate(art):
        across = (height - 1 - r) / max(1, height - 1)          # 1.0 at the top row
        col = round((width - 1) * (across if from_left else 1 - across))
        slash = "/" if from_left else "\\"
        if step == 1:
            out.append(row[:col] + slash + row[col + 1:])
            continue
        drift = min(step - 1, col, width - col)                 # never push ink off the canvas
        out.append(row[drift:col] + " " * (2 * drift) + row[col:width - drift])
    return tuple(out)


def dissolve(art: Art, steps: int, rng: random.Random) -> list[tuple[str, ...]]:
    """``steps`` frames of the hand crumbling away; the last one is empty."""
    cells = [(r, c) for r, row in enumerate(art) for c, ch in enumerate(row) if ch != " "]
    rng.shuffle(cells)
    order = {cell: i for i, cell in enumerate(cells)}
    frames = []
    for step in range(1, steps + 1):
        gone = len(cells) * step / steps
        dust = gone + len(cells) * 0.2                          # the next to go flicker first
        frame = []
        for r, row in enumerate(art):
            line = ""
            for c, ch in enumerate(row):
                rank = order.get((r, c))
                if rank is None or rank >= dust:
                    line += ch
                else:
                    line += " " if rank < gone else "."
            frame.append(line)
        frames.append(tuple(frame))
    return frames


# ---------------------------------------------------------------- the exchange

@dataclass(frozen=True)
class Beat:
    """One frame of a clash. Distances are in columns."""

    left: tuple[str, ...]
    right: tuple[str, ...]
    close: int = 0                              # how far each hand has moved toward the middle
    back: tuple[int, int] = (0, 0)              # how far each hand has been knocked outward
    burst: tuple[str, ...] = ()                 # drawn over the middle
    shake: int = 0                              # the whole arena nudged sideways
    beaten: tuple[bool, bool] = (False, False)  # which hands are drawn as beaten
    hold: float = 0.05                          # seconds on screen


def _with_word(burst: Sequence[str], word: str) -> tuple[str, ...]:
    return (*burst, word.center(len(burst[0])))


def clash(left: Art, right: Art, *, winner: Optional[int], move: Optional[Move] = None,
          reach: int = 4, shade: str = SHADE) -> list[Beat]:
    """The hands lunge, meet and recoil. ``winner`` is 0 (left hand), 1 (right) or
    None for a draw; ``move`` is the winning throw; ``reach`` is how far a hand can
    travel before they touch. The last beat is the frame to rest on."""
    left, right = tuple(left), tuple(right)
    half = max(1, reach // 2)
    if winner is None or move is None:
        clang = _with_word(CLANG, DRAW_WORD)
        return [
            Beat(left, right, close=half, hold=0.03),
            Beat(left, right, close=reach, burst=CLANG, hold=0.05),
            Beat(left, right, close=reach, burst=clang, shake=1, hold=0.06),
            Beat(left, right, close=half, burst=clang, shake=-1, back=(1, 1), hold=0.07),
            Beat(left, right, burst=("", DRAW_WORD), hold=0.10),
            Beat(left, right),
        ]

    loser = 1 - winner
    word = WORDS[move]

    def hurt(step: int) -> tuple[tuple[str, ...], tuple[str, ...]]:
        art = (left, right)[loser]
        facing = loser == 1                      # the blow arrives from the winner's side
        if move is Move.ROCK:
            art = crush(art, step)
        elif move is Move.PAPER:
            art = cover(art, step, from_left=facing, shade=shade)
        else:
            art = cut(art, step, from_left=facing)
        return (left, art) if loser == 1 else (art, right)

    def knock(columns: int) -> tuple[int, int]:
        return (0, columns) if loser == 1 else (columns, 0)

    flag = (loser == 0, loser == 1)
    full = _with_word(BURST, word)
    return [
        Beat(left, right, close=half, hold=0.03),
        Beat(left, right, close=reach, burst=SPARK, hold=0.03),
        Beat(*hurt(1), close=reach, burst=BURST, shake=1, hold=0.06),
        Beat(*hurt(1), close=reach, burst=full, shake=-1, back=knock(1), hold=0.06),
        Beat(*hurt(2), close=half, burst=full, back=knock(2), beaten=flag, hold=0.08),
        Beat(*hurt(3), burst=("", "", "", word), back=knock(2), beaten=flag, hold=0.12),
        Beat(*hurt(3), back=knock(2), beaten=flag),
    ]


# ---------------------------------------------------------------- drawing

Span = tuple[int, int, str]         # (start column, end column, "left" | "right" | "burst")


def compose(left: Art, right: Art, left_x: int, right_x: int, burst: Sequence[str] = ()
            ) -> list[tuple[str, list[Span]]]:
    """Lay two hands and an optional burst onto one canvas.

    Returns one ``(text, spans)`` per row; the spans say which columns belong to
    which hand (and to the burst, which is drawn last and centred between them),
    so the caller can colour them. The right hand wins any overlap.
    """
    width = len(left[0])
    left_x = max(0, left_x)
    right_x = max(0, right_x)
    total = max(left_x, right_x) + width
    middle = (left_x + width + right_x) // 2
    top = max(0, (len(left) - len(burst)) // 2)
    rows = []
    for r, (left_row, right_row) in enumerate(zip(left, right)):
        canvas = [" "] * total
        canvas[left_x:left_x + width] = left_row
        for i, ch in enumerate(right_row):               # ink only: never erase the left hand
            if ch != " ":
                canvas[right_x + i] = ch
        spans: list[Span] = [(left_x, left_x + width, "left"), (right_x, right_x + width, "right")]
        if top <= r < top + len(burst):
            piece = burst[r - top]
            start = middle - len(piece) // 2
            for i, ch in enumerate(piece):
                if ch != " " and 0 <= start + i < total:
                    canvas[start + i] = ch
            if piece.strip():
                spans.append((max(0, start), min(total, start + len(piece)), "burst"))
        rows.append(("".join(canvas), spans))
    return rows


# ---------------------------------------------------------------- celebration

Cell = tuple[int, int, str, str]                # (column, row, character, colour)


def fireworks(width: int, height: int, *, frames: int, rng: random.Random
              ) -> Iterator[list[Cell]]:
    """Rockets climb and burst. Yields, per frame, the cells to light up."""
    rockets: list[list] = []                    # [x, y, apex, colour]
    sparks: list[list] = []                     # [x, y, vx, vy, life, colour]
    for tick in range(frames):
        if tick % 5 == 0 and tick < frames - 12:
            rockets.append([rng.uniform(0.12, 0.88) * width, float(height - 1),
                            rng.uniform(0.12, 0.5) * height, rng.choice(_FIREWORK_COLOURS)])
        cells: list[Cell] = []
        for rocket in list(rockets):
            rocket[1] -= 1.7
            if rocket[1] <= rocket[2]:
                rockets.remove(rocket)
                count = rng.randint(18, 26)
                for i in range(count):
                    angle = 2 * math.pi * (i + rng.random() * 0.6) / count
                    speed = rng.uniform(0.45, 1.05)
                    # Characters are about twice as tall as wide: stretch sideways to stay round.
                    sparks.append([rocket[0], rocket[1], math.cos(angle) * speed * 2.1,
                                   math.sin(angle) * speed, rng.randint(8, 14), rocket[3]])
            else:
                cells.append((int(rocket[0]), int(rocket[1]), "|", "bright_white"))
        for spark in list(sparks):
            spark[0] += spark[2]
            spark[1] += spark[3]
            spark[2] *= 0.93
            spark[3] += 0.07                                     # gravity
            spark[4] -= 1
            if spark[4] <= 0:
                sparks.remove(spark)
                continue
            char = "*" if spark[4] > 8 else "+" if spark[4] > 4 else "."
            cells.append((int(spark[0]), int(spark[1]), char, spark[5]))
        yield [(x, y, ch, colour) for x, y, ch, colour in cells
               if 0 <= x < width and 0 <= y < height]
