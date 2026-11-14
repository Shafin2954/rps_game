import pytest
from rich.cells import cell_len

from rps_game.names import (MAX_NAME_CELLS, check_name, name_error, name_key, same_name)


@pytest.mark.parametrize("name", [
    "Alice", "Sohan Rahman", "সোহান", "李雷", "Zoë", "O'Brien", "Anne-Marie", "R2D2",
    "نام\u200cنویس",                      # Persian: the zero-width non-joiner is legitimate
    "Ünïcödé", "a",
])
def test_good_names_are_accepted(name):
    result = check_name(name)
    assert result.ok and result.name == name
    assert cell_len(result.name) <= MAX_NAME_CELLS


def test_names_are_tidied():
    assert check_name("  Alice  ").name == "Alice"
    assert check_name("Anna    Maria").name == "Anna Maria"


@pytest.mark.parametrize("raw", ["", "   ", "\t"])
def test_blank_names_are_refused(raw):
    assert not check_name(raw).ok


@pytest.mark.parametrize("raw", [
    "A" * (MAX_NAME_CELLS + 1),            # too wide
    "李" * 8,                               # 16 cells: short in characters, wide on screen
    "A" + "\u0301" * 40,                    # a pile of zero-width combining marks
])
def test_overlong_names_are_refused(raw):
    assert "at most" in (name_error(raw) or "")


@pytest.mark.parametrize("raw", [
    "Al\x1bice",            # terminal escape
    "Al\tice", "Al\nice",   # whitespace controls
    "Al\u00a0ice",          # no-break space
    "\u202eAlice",          # right-to-left override
    "Al\u200bice",          # zero-width space
    "Al\x00ice",
])
def test_names_that_could_garble_a_terminal_are_refused(raw):
    assert not check_name(raw).ok


@pytest.mark.parametrize("raw", ["-Alice", "_bob", "\u0301A", "😀 fun", ".hidden", "/back"])
def test_names_must_start_with_a_letter_or_number(raw):
    assert "start with" in (name_error(raw) or "")


@pytest.mark.parametrize("raw", ["You", "COMPUTER", " cpu ", "Draw", "tie", "Opponent", "ＹＯＵ"])
def test_reserved_names_are_refused_whatever_the_spelling(raw):
    assert "reserved" in (name_error(raw) or "")


@pytest.mark.parametrize("a, b", [
    ("Alice", "alice"), ("Alice", "  alice  "), ("Alice", "ＡＬＩＣＥ"),    # case, spaces, full-width
    ("Alice", "Al\u200cice"),                                               # hidden joiner
    ("Straße", "STRASSE"), ("Anna  Maria", "anna maria"),
])
def test_names_that_look_the_same_collide(a, b):
    assert same_name(a, b)
    assert "already taken" in (check_name(b, other=a).error or "")


def test_different_names_do_not_collide():
    assert not same_name("Alice", "Alicia")
    assert check_name("Bob", other="Alice").ok


def test_name_key_is_stable_and_symmetric():
    assert name_key("  ÀLICE ") == name_key("àlice")


def test_name_error_is_none_for_good_names():
    assert name_error("Bob") is None
