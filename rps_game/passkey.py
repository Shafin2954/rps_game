"""Passkeys: the shared secret two players agree on out-of-band.

Security notes:
* A passkey is never stored on disk or sent in the clear; it only feeds the
  password-authenticated key exchange (Magic Wormhole's SPAKE2).
* Guessing is limited to a few *live* attempts, so a short passkey is acceptable,
  but trivially weak ones are still refused.
* ``Passkey`` hides its value from repr/str/format, so it cannot leak through a
  log line or a traceback by accident. Call ``reveal()`` only to hand it to the
  key exchange.
"""
from __future__ import annotations

import hmac
import math
import secrets
from dataclasses import dataclass, field
from typing import Optional

MIN_LENGTH = 6
MAX_LENGTH = 64
GENERATED_WORDS = 3

_TOO_COMMON = frozenset({
    "123456", "1234567", "12345678", "123456789", "654321", "password", "passw0rd",
    "qwerty", "qwerty123", "abcdef", "abc123", "letmein", "iloveyou", "111111",
    "000000", "secret", "welcome", "admin1", "rockpaper", "scissors",
})

WORDS: tuple[str, ...] = tuple("""
anchor apple arrow atlas badge baker banjo basil beach berry bishop blaze blossom boat bonus
book boots brave bread brick bridge brook brush bubble cabin cactus camel candle canoe canyon
carpet castle cedar chair chalk cherry chess cider cliff clock cloud clover coast cobra comet
coral cotton crane crown daisy dancer delta desert diary dingo dolphin dragon drum eagle earth
ember engine falcon feather fern ferry fiddle field finch flame flute forest fossil fox frost
garden gecko ginger glacier globe goat gold grape grove guitar harbor hawk hazel heron hill
honey horizon island ivory jacket jade jaguar jelly jungle kayak kettle kite koala ladder
lagoon lake lantern lemon lily lizard lotus magnet mango maple marble meadow melon mint mirror
monkey moon moss mountain mouse nectar needle nest noodle north oasis ocean olive onion orange
orbit otter owl paddle palm panda pearl pebble pepper piano pilot pine planet plum pony poppy
pretzel puffin pumpkin puzzle quartz rabbit radar rain raven reef ribbon ring river robin
rocket rose sailor salmon sand saturn scarf shadow shell silver sketch slate snow spark spice
spider spoon spring squid star stone storm sugar summer sunset swan tablet tango teapot
thunder tiger timber tomato tower trail tulip tunnel turtle umbrella valley velvet violin
walnut wave whale willow window winter wolf wonder yacht yarrow zebra zephyr
acorn amber aspen bamboo beacon birch breeze buffalo canary caramel cheetah cinder cobalt
copper cricket dahlia dune ferret fig gazelle glimmer granite harvest hickory iris jasmine
juniper kiwi lava lilac lynx magpie marlin nutmeg orchid osprey pelican quail sparrow thistle
""".split())


def passkey_error(text: str) -> Optional[str]:
    """A message fit to show the player, or None if the passkey is acceptable."""
    if len(text) < MIN_LENGTH:
        return f"A passkey needs at least {MIN_LENGTH} characters."
    if len(text) > MAX_LENGTH:
        return f"A passkey can be at most {MAX_LENGTH} characters."
    if any(ch.isspace() or not ch.isprintable() for ch in text):
        return "A passkey can't contain spaces or control characters."
    if len(set(text)) == 1 or text.casefold() in _TOO_COMMON:
        return "That passkey is too easy to guess. Please choose another."
    return None


def generate_passphrase(words: int = GENERATED_WORDS) -> str:
    """e.g. ``lamp-river-ocean``: easy to read out over a call."""
    return "-".join(secrets.choice(WORDS) for _ in range(words))


def passphrase_bits(words: int = GENERATED_WORDS) -> float:
    """Entropy of a generated passphrase, in bits."""
    return words * math.log2(len(WORDS))


@dataclass(frozen=True, repr=False)
class Passkey:
    _value: str = field(repr=False)

    def reveal(self) -> str:
        return self._value

    def matches(self, other: str) -> bool:
        """Constant-time comparison."""
        return hmac.compare_digest(self._value.encode(), other.encode())

    def __repr__(self) -> str:
        return "Passkey(<hidden>)"

    __str__ = __repr__

    def __format__(self, spec: str) -> str:
        return "<hidden>"
