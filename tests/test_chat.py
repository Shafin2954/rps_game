"""Chat: the rules for a message, the wire format, and whole conversations over a game."""
import io
import threading
import time

import pytest
from rich.console import Console

from netutil import connected_pair, send
from rps_game import chat, cli, terminal
from rps_game.chat import ChatLog, chat_error, supports_chat, tidy, valid
from rps_game.engine import Move
from rps_game.net import protocol as proto
from rps_game.net.errors import ProtocolError
from rps_game.net.game import NetworkOpponent
from rps_game.net.play import play_dual
from rps_game.net.session import GameTerms
from rps_game.ui import GameUI
from test_play_dual import SLOW, bot_playing, host_setup

K = terminal
R, P, S = Move.ROCK, Move.PAPER, Move.SCISSORS


# ================================================================ the rules

def test_messages_are_tidied():
    assert tidy("  good   luck  ") == "good luck"
    assert tidy("é") == "é"                       # normalised to one code point


@pytest.mark.parametrize("text", ["gg", "nice one!", "rock? really?", "ভালো খেলা", "加油 :)",
                                  "x" * 60])
def test_ordinary_messages_are_fine(text):
    assert chat_error(text) is None and valid(text)


@pytest.mark.parametrize("text", [
    "", "   ", "line\nbreak", "tab\there", "bell\x07", "esc\x1b[2J", "bidi‮evil",
    "zero​width", "x" * 61, "李" * 31,
])
def test_anything_that_could_garble_a_terminal_is_refused(text):
    assert chat_error(text) is not None and not valid(text)


def test_only_the_tidy_form_is_valid_on_the_wire():
    assert valid("hello there") and not valid(" hello there") and not valid("hello  there")
    assert not valid(None) and not valid(5) and not valid(["hi"])


def test_only_new_enough_games_get_chat():
    assert supports_chat("4.1.0") and supports_chat("4.2") and supports_chat("5.0.0rc1")
    assert not supports_chat("4.0.0") and not supports_chat("3.5.0")
    assert not supports_chat("") and not supports_chat("banana")


def test_chat_log_keeps_order_reads_once_and_forgets_old_lines():
    log = ChatLog("Bob", limit=3)
    assert log.recent(2) == [] and log.unread() == [] and log.latest_from_them() is None
    log.add("hi", mine=False)
    log.add("hello", mine=True)
    assert log.recent(5) == [("Bob", "hi", False), ("You", "hello", True)]
    assert log.unread() == ["Bob says: hi"] and log.unread() == []       # only theirs, only once
    for n in range(4):
        log.add(f"m{n}", mine=False)
    assert [text for _, text, _ in log.recent(9)] == ["m1", "m2", "m3"]  # capped at the limit
    assert log.unread() == ["Bob says: m1", "Bob says: m2", "Bob says: m3"]
    assert log.count == 6 and log.latest_from_them() == "m3" and log.recent(0) == []


# ================================================================ the wire

def test_chat_round_trips_and_is_checked_on_arrival():
    data = proto.encode(proto.Chat("nice one!"))
    assert proto.decode(data) == proto.Chat("nice one!")
    for bad in (b'{"t":"chat","text":"  spaced  "}', b'{"t":"chat","text":"a\\u001b[2J"}',
                b'{"t":"chat","text":""}', b'{"t":"chat","text":7}', b'{"t":"chat"}',
                b'{"t":"chat","text":"hi","extra":1}'):
        with pytest.raises(ProtocolError):
            proto.decode(bad)


# ================================================================ over a connection

def opponents(**options):
    host, join, _ = connected_pair(terms=GameTerms(first_to=2))
    return (NetworkOpponent(host, **{**SLOW, **options}), NetworkOpponent(join, **SLOW))


def wait_for(condition, seconds=3.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_two_players_can_talk_and_it_never_disturbs_the_game():
    a, b = opponents()
    try:
        assert a.can_chat and b.can_chat
        assert a.say("  good   luck ") is None
        assert wait_for(lambda: b.chat.count == 1)
        assert b.chat.recent(1) == [("Sohan", "good luck", False)]
        assert a.chat.recent(1) == [("You", "good luck", True)]
        assert b.say("you too") is None
        assert wait_for(lambda: a.chat.latest_from_them() == "you too")
        assert "Bob: you too" in a.results_status()

        moves = {}
        t = threading.Thread(target=lambda: moves.update(b=b.play(S)), daemon=True)
        t.start()
        a.say("here it comes")                              # chatting mid-round is fine
        moves["a"] = a.play(R)
        t.join(5)
        assert moves == {"a": S, "b": R} and a.error is None and b.error is None
    finally:
        a.close()
        b.close()


def test_bad_messages_are_not_sent():
    a, b = opponents()
    try:
        assert a.say("   ") == "Type a message first."
        assert "at most 60" in a.say("x" * 61)
        assert "only use letters" in a.say("oops\x1b[2J")
        time.sleep(0.1)
        assert b.chat.count == 0 and a.chat.count == 0
    finally:
        a.close()
        b.close()


def test_an_older_game_is_never_sent_chat():
    host, join, _ = connected_pair()
    host.opponent_app = "3.5.0"                             # as if Bob had not updated
    a, b = NetworkOpponent(host, **SLOW), NetworkOpponent(join, **SLOW)
    try:
        assert not a.can_chat
        assert a.say("hello?") == "Bob's game is an older version without chat."
        time.sleep(0.1)
        assert b.chat.count == 0 and b.error is None
    finally:
        a.close()
        b.close()


def test_a_flood_is_dropped_not_punished():
    host, join, _ = connected_pair()
    a = NetworkOpponent(host, **SLOW)
    try:
        for n in range(30):
            send(join, proto.Chat(f"spam {n}"))
        assert wait_for(lambda: a.chat.count == 8)
        time.sleep(0.2)
        assert a.chat.count == 8 and a.error is None        # the rest vanished; the game goes on
    finally:
        a.close()
        join.close()


def test_a_malformed_chat_message_ends_the_game_like_any_other():
    host, join, _ = connected_pair()
    a = NetworkOpponent(host, **SLOW)
    try:
        join.transport.send(b'{"t":"chat","text":"\\u001b[31mred"}')
        assert wait_for(lambda: a.error is not None)
        assert a.chat.count == 0
    finally:
        a.close()
        join.close()


def test_saying_something_after_they_left_explains_why_not():
    a, b = opponents()
    b.close()
    assert wait_for(lambda: a.error is not None)
    assert a.say("still there?") == "Bob left the game."
    a.close()


# ================================================================ on the screens

def drive(monkeypatch, inputs, bot, ui=None, **options):
    host, join, _ = connected_pair(terms=GameTerms(first_to=2))
    it = iter(inputs)
    seen = []

    def answer(prompt=""):
        seen.append(prompt)
        item = next(it)
        if callable(item):
            return item()
        return item

    monkeypatch.setattr("builtins.input", answer)
    ui = ui or GameUI(plain=True)
    t = threading.Thread(target=lambda: bot(NetworkOpponent(join, **SLOW)), daemon=True)
    t.start()
    play_dual(ui, host_setup(), host, run_game=cli.run_game, **{**SLOW, **options})
    t.join(10)
    return ui, seen


def test_plain_mode_shows_their_words_and_sends_yours(monkeypatch, capsys):
    def pause_then(move):                                   # give the bot's words time to land
        def later():
            time.sleep(0.4)
            return move
        return later

    received = []

    def bot(opp):
        opp.say("good luck")
        try:
            deadline = time.monotonic() + 4
            while opp.chat.latest_from_them() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            received.extend(text for _, text, mine in opp.chat.recent(5) if not mine)
        finally:
            opp.close()

    _, prompts = drive(monkeypatch, [pause_then("say  thanks,  you too "), "say", "q", "y"], bot)
    out = capsys.readouterr().out
    assert any("say <message>" in p for p in prompts)
    assert "Bob says: good luck" in out
    assert "Sent." in out and "Type a message first." in out
    assert received == ["thanks, you too"]


def test_the_game_over_menu_can_send_a_message(monkeypatch, capsys):
    got = []

    def bot(opp):
        from rps_game.engine import Round, judge
        try:
            for move in (S, S):
                theirs = opp.play(move)
                opp.record(Round(move, theirs, judge(move, theirs)))
            deadline = time.monotonic() + 4
            while opp.chat.latest_from_them() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            got.append(opp.chat.latest_from_them())
            opp.say("gg indeed")
            time.sleep(0.3)
        finally:
            opp.close()

    def back_after_reply():
        time.sleep(0.5)
        return "2"

    drive(monkeypatch, ["r", "r", "3", "gg", back_after_reply], bot)     # 3 = Send a message
    out = capsys.readouterr().out
    assert "3. Send a message - Say something to your opponent" in out
    assert "Message to Bob" in out
    assert got == ["gg"]
    assert "You: gg" in out                                 # the conversation is on the menu


def test_no_chat_entry_in_the_menu_against_an_older_game(monkeypatch, capsys):
    host, join, _ = connected_pair(terms=GameTerms(first_to=2))
    host.opponent_app = "4.0.0"
    it = iter(["r", "r", "2"])
    prompts = []
    monkeypatch.setattr("builtins.input", lambda prompt="": prompts.append(prompt) or next(it))
    t = threading.Thread(target=lambda: bot_playing(S, S)(NetworkOpponent(join, **SLOW)),
                         daemon=True)
    t.start()
    play_dual(GameUI(plain=True), host_setup(), host, run_game=cli.run_game, **SLOW)
    t.join(10)
    out = capsys.readouterr().out
    assert "Send a message" not in out
    assert not any("say <message>" in p for p in prompts)


def test_the_ui_forgets_chat_when_the_game_ends(monkeypatch):
    ui, _ = drive(monkeypatch, ["r", "r", "2"], bot_playing(S, S))
    assert ui._chat is None and ui._send_chat is None


# ================================================================ rich screen

def rich_ui(height=30):
    out = io.StringIO()
    console = Console(file=out, width=100, height=height, force_terminal=False)
    return GameUI(animate=False, console=console), out


def test_round_screen_shows_the_latest_lines_and_a_talk_key():
    from rps_game.engine import Match, Score
    ui, out = rich_ui()
    log = ChatLog("Bob")
    log.add("ready?", mine=False)
    log.add("born ready", mine=True)
    log.add("we'll see", mine=False)
    ui.set_chat(log, lambda text: None)
    ui.start_round(Match(first_to=2), Score(), "")
    ui.end_round()
    text = out.getvalue()
    assert "[t]alk" in text
    assert "Bob: we'll see" in text and "You: born ready" in text and "ready?" not in text
    lines = text.splitlines()
    prompt = next(i for i, line in enumerate(lines) if "[t]alk" in line)
    said = next(i for i, line in enumerate(lines) if "Bob: we'll see" in line)
    assert prompt < said                                    # chat sits below the keys


def test_short_terminals_show_one_line_without_growing():
    from rps_game.engine import Match, Score

    def rows(with_chat):
        ui, out = rich_ui(height=24)
        if with_chat:
            log = ChatLog("Bob")
            log.add("one", mine=False)
            log.add("two", mine=False)
            ui.set_chat(log, lambda text: None)
        ui.start_round(Match(first_to=2), Score(), "")
        ui.end_round()
        return out.getvalue()

    quiet, talking = rows(False), rows(True)
    assert "Bob: two" in talking and "Bob: one" not in talking
    assert len(talking.splitlines()) == len(quiet.splitlines())


def test_offline_screens_have_no_talk_key():
    from rps_game.engine import Match, Score
    ui, out = rich_ui()
    ui.start_round(Match(), Score(), "normal")
    ui.end_round()
    assert "[t]alk" not in out.getvalue()


def test_typing_a_message_with_keys(monkeypatch):
    from rps_game.engine import Match, Score
    ui, out = rich_ui()
    sent = []

    def send_it(text):
        if text == "bad":
            return "Nope."
        sent.append(text)
        return None

    ui.set_chat(ChatLog("Bob"), send_it)
    typed = iter(["t", "h", "i", "x", K.KEY_BACKSPACE, K.KEY_ENTER,        # "hi", sent
                  "t", "o", "o", "p", "s", K.KEY_ESC,                       # cancelled
                  "t", "b", "a", "d", K.KEY_ENTER,                          # refused...
                  "\x15", "o", "k", K.KEY_ENTER,                            # ...retyped, sent
                  "t", K.KEY_ENTER,                                         # empty: just closes
                  "r"])
    monkeypatch.setattr(terminal, "is_interactive", lambda: True)
    monkeypatch.setattr(terminal, "flush_input", lambda: None)
    monkeypatch.setattr(terminal, "read_key", lambda timeout=None: next(typed))
    ui.start_round(Match(first_to=2), Score(), "")
    polls = []
    assert ui.ask_move(idle=lambda: polls.append(1) or "Bob is choosing...") is R
    ui.end_round()
    assert sent == ["hi", "ok"]
    assert "You chose rock." in out.getvalue()


def test_a_long_message_stops_at_the_limit(monkeypatch):
    from rps_game.engine import Match, Score
    ui, _ = rich_ui()
    sent = []
    ui.set_chat(ChatLog("Bob"), lambda text: sent.append(text))
    typed = iter(["t", *["z"] * 70, K.KEY_ENTER, "p"])
    monkeypatch.setattr(terminal, "is_interactive", lambda: True)
    monkeypatch.setattr(terminal, "flush_input", lambda: None)
    monkeypatch.setattr(terminal, "read_key", lambda timeout=None: next(typed))
    ui.start_round(Match(first_to=2), Score(), "")
    assert ui.ask_move(idle=lambda: "") is P
    ui.end_round()
    assert sent == ["z" * chat.MAX_CELLS]
