"""ASCII art for the hands. Right-facing is the player, left-facing the computer."""
from __future__ import annotations

from .engine import Move

_FIST_RIGHT = (
    "      ____     ",
    "   ,-(____)-   ",
    " -'  (_____)   ",
    "    (_____)    ",
    "     (____)    ",
    "      (__)     ",
)
_FIST_LEFT = (
    "     ____      ",
    "   -(____)-,   ",
    "   (_____)  '- ",
    "    (_____)    ",
    "     (____)    ",
    "      (__)     ",
)
_RIGHT = {
    Move.ROCK: (
        "    _______    ",
        "---'   ____)   ",
        "      (_____)  ",
        "      (_____)  ",
        "      (____)   ",
        "---.__(___)    ",
    ),
    Move.PAPER: (
        "     _______     ",
        "---'    ____)____ ",
        "           ______)",
        "          _______)",
        "         _______) ",
        "---.__________)   ",
    ),
    Move.SCISSORS: (
        "    _______      ",
        "---'   ____)____ ",
        "          ______)",
        "       __________)",
        "      (____)     ",
        "---.__(___)      ",
    ),
}
_LEFT = {
    Move.ROCK: (
        "    _______    ",
        "   (____   '---",
        "  (_____)      ",
        "  (_____)      ",
        "   (____)      ",
        "    (___)__.---",
    ),
    Move.PAPER: (
        "     _______     ",
        " ____(____    '---",
        "(______           ",
        "(_______          ",
        " (_______         ",
        "   (__________.---",
    ),
    Move.SCISSORS: (
        "      _______    ",
        " ____(____   '---",
        "(______          ",
        "(__________       ",
        "     (____)      ",
        "      (___)__.---",
    ),
}

_ALL = [_FIST_RIGHT, _FIST_LEFT, *_RIGHT.values(), *_LEFT.values()]
WIDTH = max(len(line) for art in _ALL for line in art)
HEIGHT = len(_FIST_RIGHT)


def _pad(art: tuple[str, ...]) -> tuple[str, ...]:
    """Pad every line to the same width so hands line up in any combination."""
    return tuple(line.ljust(WIDTH) for line in art)


FIST_RIGHT = _pad(_FIST_RIGHT)
FIST_LEFT = _pad(_FIST_LEFT)
HANDS_RIGHT = {move: _pad(art) for move, art in _RIGHT.items()}
HANDS_LEFT = {move: _pad(art) for move, art in _LEFT.items()}
