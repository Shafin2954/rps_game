import pytest

from rps_game.roomcode import (DIGITS, format_room_code, generate_room_code, parse_room_code,
                               room_code_error)


def test_generated_codes_are_nine_digits_and_never_start_with_zero():
    codes = {generate_room_code() for _ in range(300)}
    assert len(codes) > 290
    for code in codes:
        assert len(code) == DIGITS and code.isdigit() and code[0] != "0"


def test_formatting_round_trips():
    assert format_room_code("482193756") == "482-193-756"
    assert parse_room_code("482-193-756") == "482193756"


@pytest.mark.parametrize("typed", ["482-193-756", "482 193 756", "482193756", "4821-93756"])
def test_forgiving_about_separators(typed):
    assert parse_room_code(typed) == "482193756"


@pytest.mark.parametrize("typed", [
    "", "12345678", "1234567890", "012345678", "48a-193-756", "٤٨٢١٩٣٧٥٦",   # Arabic-Indic digits
    "482--193-75", "abc-def-ghi",
])
def test_bad_codes_are_refused_with_a_helpful_message(typed):
    assert parse_room_code(typed) is None
    assert "9 digits" in room_code_error(typed)


def test_generated_codes_always_parse():
    for _ in range(50):
        code = generate_room_code()
        assert parse_room_code(format_room_code(code)) == code
