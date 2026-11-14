import os
import sys

import pytest

from rps_game import terminal

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX pty test")


@pytest.fixture
def pty_stdin(monkeypatch):
    import pty

    import tty

    master, slave = pty.openpty()
    tty.setcbreak(slave)      # a real terminal would deliver keys as typed, not line-buffered
    stream = os.fdopen(slave, "r", closefd=True)
    monkeypatch.setattr(sys, "stdin", stream)
    yield master
    stream.close()
    os.close(master)


@pytest.mark.parametrize(
    "sent, expected",
    [
        (b"\x1b[A", terminal.KEY_UP), (b"\x1b[B", terminal.KEY_DOWN),
        (b"\x1b[C", terminal.KEY_RIGHT), (b"\x1b[D", terminal.KEY_LEFT),
        (b"\x1bOA", terminal.KEY_UP),            # application-mode arrows
        (b"\x1b[1;5A", terminal.KEY_UP),         # Ctrl+Up still counts as up
        (b"\x1b[3~", ""),                        # Delete: ignored
        (b"\x1b", terminal.KEY_ESC),             # lone Escape
        (b"\r", terminal.KEY_ENTER), (b"\n", terminal.KEY_ENTER),
        (b"\x7f", terminal.KEY_BACKSPACE),
        (b"r", "r"), (b"5", "5"),
    ],
)
def test_read_key_posix(pty_stdin, sent, expected):
    os.write(pty_stdin, sent)
    assert terminal.read_key() == expected


def test_ctrl_d_raises_eof(pty_stdin):
    os.write(pty_stdin, b"\x04")
    with pytest.raises(EOFError):
        terminal.read_key()


def test_typed_ahead_keys_are_not_dropped_inside_a_keyboard_session(pty_stdin):
    with terminal.keyboard():
        os.write(pty_stdin, b"\x1b[B\x1b[Br")        # Down, Down, 'r' arrive together
        assert [terminal.read_key() for _ in range(3)] == [terminal.KEY_DOWN, terminal.KEY_DOWN, "r"]


def test_keyboard_session_restores_the_terminal(pty_stdin):
    import termios

    fd = sys.stdin.fileno()
    termios.tcsetattr(fd, termios.TCSANOW, [*termios.tcgetattr(fd)[:3],
                      termios.tcgetattr(fd)[3] | termios.ECHO | termios.ICANON,
                      *termios.tcgetattr(fd)[4:]])
    before = termios.tcgetattr(fd)
    with terminal.keyboard():
        inside = termios.tcgetattr(fd)
        assert not inside[3] & termios.ECHO and not inside[3] & termios.ICANON
    assert termios.tcgetattr(fd) == before


@pytest.mark.parametrize("text", ["স", "é", "李", "😀"])
def test_multibyte_characters_arrive_whole(pty_stdin, text):
    os.write(pty_stdin, text.encode())
    assert terminal.read_key() == text


def test_a_whole_bengali_name_can_be_typed(pty_stdin):
    os.write(pty_stdin, "সোহান".encode())
    typed = "".join(terminal.read_key() for _ in range(len("সোহান")))
    assert typed == "সোহান"


def test_timeout_returns_none_without_blocking(pty_stdin):
    import time

    start = time.monotonic()
    assert terminal.read_key(timeout=0.1) is None
    assert 0.08 <= time.monotonic() - start < 1.0


def test_timeout_still_returns_a_key_that_is_waiting(pty_stdin):
    os.write(pty_stdin, b"r")
    assert terminal.read_key(timeout=1.0) == "r"


def test_read_key_times_out_when_nothing_is_typed(pty_stdin):
    assert terminal.read_key(timeout=0.05) is None


def test_read_key_with_timeout_still_returns_a_waiting_key(pty_stdin):
    os.write(pty_stdin, b"r")
    assert terminal.read_key(timeout=1.0) == "r"


@pytest.mark.parametrize("char", ["é", "সোহান"[0], "李", "😀"])
def test_non_ascii_characters_arrive_whole(pty_stdin, char):
    os.write(pty_stdin, char.encode("utf-8"))
    assert terminal.read_key(timeout=1.0) == char


def test_a_whole_unicode_name_can_be_read_key_by_key(pty_stdin):
    name = "সোহান"
    os.write(pty_stdin, name.encode("utf-8"))
    assert "".join(terminal.read_key(timeout=1.0) for _ in name) == name
