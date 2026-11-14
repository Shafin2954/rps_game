import re

import pytest

from rps_game.passkey import (MAX_LENGTH, MIN_LENGTH, WORDS, Passkey, generate_passphrase,
                              passkey_error, passphrase_bits)


@pytest.mark.parametrize("good", ["hunter22", "lamp-river-ocean", "pässwörd9", "ab" * (MAX_LENGTH // 2),
                                  "a1b2c3", "Tr0ub4dor&3"])
def test_acceptable_passkeys(good):
    assert passkey_error(good) is None


@pytest.mark.parametrize("bad, fragment", [
    ("short", "at least"), ("", "at least"), ("x" * (MAX_LENGTH + 1), "at most"),
    ("has space1", "spaces"), ("tab\there1", "spaces"), ("bell\x07chars", "control"),
    ("aaaaaaaa", "too easy"), ("111111", "too easy"), ("PASSWORD", "too easy"),
    ("123456", "too easy"), ("QwErTy", "too easy"),
])
def test_unacceptable_passkeys(bad, fragment):
    assert fragment in (passkey_error(bad) or "")


def test_minimum_length_boundary():
    assert passkey_error("a1b2c" * 1) is not None
    assert passkey_error("a1b2c3") is None
    assert MIN_LENGTH == 6


def test_wordlist_is_clean_and_big_enough():
    assert len(WORDS) == len(set(WORDS)) >= 256
    assert all(re.fullmatch(r"[a-z]{3,8}", w) for w in WORDS)
    assert passphrase_bits() >= 24


def test_generated_passphrases_are_well_formed_acceptable_and_varied():
    seen = {generate_passphrase() for _ in range(60)}
    assert len(seen) > 55
    for phrase in seen:
        parts = phrase.split("-")
        assert len(parts) == 3 and all(p in WORDS for p in parts)
        assert passkey_error(phrase) is None


def test_passkey_never_reveals_itself_by_accident():
    secret = "s3cret-value"
    p = Passkey(secret)
    for text in (repr(p), str(p), f"{p}", f"{p!r}", "%s" % p, format(p, ">20")):
        assert secret not in text
    assert p.reveal() == secret


def test_passkey_comparison():
    p = Passkey("hunter22")
    assert p.matches("hunter22") and not p.matches("hunter23") and not p.matches("")


def test_passkey_is_hidden_inside_other_objects():
    from dataclasses import dataclass

    @dataclass
    class Holder:
        key: Passkey

    assert "hunter22" not in repr(Holder(Passkey("hunter22")))
