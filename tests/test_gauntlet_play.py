"""Whole Gauntlet runs through the real screens: plain text, rich frames and real keys."""
import datetime
import io

import pytest
from rich.console import Console

from rps_game import cli, menu, terminal
from rps_game import profile as profile_store
from rps_game.gauntlet import play
from rps_game.gauntlet.play import GauntletConfig, play_gauntlet, seed_error, tidy_seed
from rps_game.engine import Move, Outcome, Round
from rps_game.gauntlet.rules import Exchange, Technique
from rps_game.gauntlet.screens import headline
from rps_game.ui import GameUI

K = terminal
R, P, S = Move.ROCK, Move.PAPER, Move.SCISSORS


@pytest.fixture
def spy(monkeypatch):
    """Lets a test see the run in progress (and so read the foe's mind)."""
    box = {}
    real = play.new_run

    def make(config):
        box["run"] = real(config)
        return box["run"]

    monkeypatch.setattr(play, "new_run", make)
    return box


def autoplay(monkeypatch, spy, script=(), *, win=True, reward="1"):
    """Answer input(): ``script`` first, then throws that win (or lose) every round."""
    queue = list(script)
    prompts = []

    def answer(prompt=""):
        prompts.append(prompt)
        if queue:
            item = queue.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item
        if prompt.startswith("Your move"):
            intent = spy["run"].duel.intent
            return str(intent.beaten_by if win else intent.beats)
        if prompt.startswith("Choose"):
            return reward
        if "[y/N]" in prompt:
            return "y"
        raise AssertionError(f"unexpected prompt {prompt!r}")

    monkeypatch.setattr("builtins.input", answer)
    return prompts


def rich_ui(width=100, height=30, **options):
    out = io.StringIO()
    console = Console(file=out, width=width, height=height, force_terminal=False)
    return GameUI(animate=False, console=console, **options), out


def keys(monkeypatch, source):
    """Pretend to be a real terminal whose keys come from ``source`` (an iterator)."""
    monkeypatch.setattr(terminal, "is_interactive", lambda: True)
    monkeypatch.setattr(terminal, "flush_input", lambda: None)
    monkeypatch.setattr(terminal, "read_key", lambda timeout=None: next(source))


# ================================================================ plain mode

def test_a_whole_run_in_plain_mode(monkeypatch, spy, capsys):
    autoplay(monkeypatch, spy)
    result = play_gauntlet(GameUI(plain=True), GauntletConfig(seed="abc"))
    out = capsys.readouterr().out
    assert result.run.victory and not result.interrupted
    assert "THE GAUNTLET" in out and "Seed ABC" in out
    assert "FLOOR 1 OF 10" in out and "FLOOR 10 OF 10" in out
    assert "THE WARDEN" in out and "THE ORACLE" in out
    assert out.count("is defeated!") == 9                  # the tenth win ends the run instead
    assert out.count("Choose a reward") == 9 and "You take " in out
    assert "YOU CONQUERED THE GAUNTLET!" in out
    assert "Floors cleared 10 of 10" in out and "Win rate 100%" in out
    assert "Achievement unlocked: Top of the Tower" in out and "New best score!" in out
    saved = profile_store.load()
    assert (saved.runs, saved.victories, saved.best_score) == (1, 1, result.run.score)
    assert result.gains.xp == result.run.score // 8


def test_round_by_round_text_spells_everything_out(monkeypatch, spy, capsys):
    autoplay(monkeypatch, spy, win=False)
    result = play_gauntlet(GameUI(plain=True), GauntletConfig(seed="abc"))
    out = capsys.readouterr().out
    foe = result.run.ladder[0]
    assert "Round 1" in out
    assert f"You: 14/14 HP, Focus 1/4. {foe.name}: {foe.hp}/{foe.hp} HP." in out
    assert f"{foe.name} played " in out and "You lose!" in out and "you take 2 damage." in out
    assert "THE GAUNTLET CLAIMS YOU" in out
    assert f"You fell on floor 1 to {foe.full_name}." in out
    assert result.run.fallen_to == foe.key and result.run.hero.hp == 0
    assert profile_store.load().runs == 1


def test_techniques_in_plain_mode(monkeypatch, spy, capsys):
    autoplay(monkeypatch, spy, ["g", "g",                   # arm Guard, think better of it
                                "c", "foresight",           # neither is affordable on 1 Focus
                                "guard"],                   # words work as well as letters
             win=False)
    play_gauntlet(GameUI(plain=True), GauntletConfig(seed="abc"))
    out = capsys.readouterr().out
    assert "Guard ready: You take no damage this round." in out and "Guard cancelled." in out
    assert "Charge needs 2 Focus and you have 1." in out
    assert "Foresight needs 2 Focus and you have 1." in out
    assert "but you take no damage." in out and "Guard blocks 2" in out


def test_foresight_names_a_throw_the_foe_then_does_not_make(monkeypatch, spy, capsys):
    script = iter(["lose", "f", "g", "c", "f", "safe"])

    def answer(prompt=""):
        if not prompt.startswith("Your move"):
            raise EOFError
        step = next(script, None)
        duel = spy["run"].duel
        if step == "lose":
            return str(duel.intent.beats)                   # earns the second Focus
        if step == "safe":
            return str(duel.intent)                         # a draw
        if step is None:
            raise EOFError
        return step

    monkeypatch.setattr("builtins.input", answer)
    play_gauntlet(GameUI(plain=True), GauntletConfig(seed="abc"))
    out = capsys.readouterr().out
    line = next(text for text in out.splitlines() if text.startswith("Foresight:"))
    ruled_out = line.rsplit(" ", 1)[1].rstrip(".")
    foe = spy["run"].ladder[0].name
    assert line == f"Foresight: {foe} will not throw {ruled_out}."
    assert f"{foe} played {ruled_out}." not in out.split(line, 1)[1].split("Round 3")[0]
    assert out.count("One technique per round, and Foresight is already spent.") == 2
    assert out.count(line) == 2                             # asking again repeats, for free


def test_info_and_nonsense_in_plain_mode(monkeypatch, spy, capsys):
    autoplay(monkeypatch, spy, ["i", "lizard", EOFError()])
    play_gauntlet(GameUI(plain=True), GauntletConfig(seed="abc"))
    out = capsys.readouterr().out
    foe = spy["run"].ladder[0]
    assert foe.full_name in out and "You hold no relics yet." in out
    assert "g = Guard (1 Focus): You take no damage this round." in out
    assert "'lizard' is not a valid move." in out


def test_quitting_needs_confirmation_and_scores_the_run(monkeypatch, spy, capsys):
    prompts = autoplay(monkeypatch, spy, ["q", "n", "paper", "quit", "y"])
    result = play_gauntlet(GameUI(plain=True), GauntletConfig(seed="abc"))
    out = capsys.readouterr().out
    assert result.run.abandoned and not result.interrupted and result.run.tally.rounds == 1
    assert "RUN ABANDONED" in out and "You walked away on floor 1." in out
    assert sum("Abandon the run?" in p for p in prompts) == 2
    assert profile_store.load().runs == 1


def test_resting_and_walking_away_from_the_reward_screen(monkeypatch, spy, capsys):
    def reward(prompt=""):
        run = spy["run"]
        if prompt.startswith("Your move"):
            return str(run.duel.intent.beaten_by)
        if prompt.startswith("Choose"):
            return "4" if run.floor == 2 else "q"           # floor 2: Rest. floor 3: back out
        return "y"

    monkeypatch.setattr("builtins.input", reward)
    result = play_gauntlet(GameUI(plain=True), GauntletConfig(seed="abc"))
    out = capsys.readouterr().out
    assert "4. Rest - Take no relic. Heal 5 HP instead." in out
    assert "You rest and heal 0 HP." in out                 # unhurt: nothing to heal
    assert result.run.abandoned and result.run.floors_cleared == 2 and result.run.hero.relics == []
    assert "Floors cleared 2 of 10" in out


def test_closed_input_ends_the_run_cleanly_and_still_saves_it(monkeypatch, spy, capsys):
    autoplay(monkeypatch, spy, ["rock", EOFError()])
    result = play_gauntlet(GameUI(plain=True), GauntletConfig(seed="abc"))
    assert result.interrupted and result.run.abandoned and result.run.tally.rounds == 1
    assert "RUN ABANDONED" in capsys.readouterr().out
    assert profile_store.load().runs == 1


def test_a_run_that_never_threw_is_not_recorded(monkeypatch, spy, capsys):
    autoplay(monkeypatch, spy, [KeyboardInterrupt()])
    result = play_gauntlet(GameUI(plain=True), GauntletConfig(seed="abc"))
    assert result.interrupted and result.gains is None
    assert profile_store.load().runs == 0


def test_no_save_leaves_the_profile_alone(monkeypatch, spy, capsys):
    autoplay(monkeypatch, spy, win=False)
    result = play_gauntlet(GameUI(plain=True), GauntletConfig(seed="abc"), save=False)
    assert result.gains is None and not profile_store.profile_path().exists()
    assert "XP" not in capsys.readouterr().out


def test_relics_are_announced_and_named_in_the_summary(monkeypatch, spy, capsys):
    autoplay(monkeypatch, spy, reward="2")
    result = play_gauntlet(GameUI(plain=True), GauntletConfig(seed="relics"))
    out = capsys.readouterr().out
    held = result.run.hero.relics
    assert len(held) == 9
    from rps_game.gauntlet.relics import RELICS
    assert f"Relics: {RELICS[held[0]].name}" in out.replace("\n", " ")
    assert f"You take {RELICS[held[0]].name}:" in out


# ================================================================ seeds, flags, menus

def test_seeds_are_tidied_and_validated():
    assert tidy_seed("  ab  c ") == "AB C"
    assert seed_error("abc") is None and seed_error("   ") and seed_error("a\x07b")
    assert play.new_run(GauntletConfig(seed=" abc ")).seed == "ABC"
    today = datetime.date.today().isoformat()
    daily = play.new_run(GauntletConfig(daily=True))
    assert (daily.seed, daily.daily) == (today, today)
    assert len(play.new_run(GauntletConfig()).seed) == 6


def test_the_same_seed_gives_everyone_the_same_tower():
    a, b = play.new_run(GauntletConfig(seed="shared")), play.new_run(GauntletConfig(seed="SHARED "))
    assert [s.key for s in a.ladder] == [s.key for s in b.ladder]
    assert [r.key for r in a.rewards()] == [r.key for r in b.rewards()]


def test_command_line_flags_start_a_run(monkeypatch, capsys):
    def closed(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", closed)
    assert cli.main(["--plain", "--gauntlet"]) == 0
    assert "THE GAUNTLET" in capsys.readouterr().out
    assert cli.main(["--plain", "--seed", "hello"]) == 0
    assert "Seed HELLO" in capsys.readouterr().out
    assert cli.main(["--plain", "--daily"]) == 0
    assert f"Daily Run {datetime.date.today().isoformat()}" in capsys.readouterr().out
    for bad in (["--seed", ""], ["--seed", "x" * 17]):
        with pytest.raises(SystemExit):
            cli.build_parser().parse_args(bad)


def test_plain_menu_into_the_gauntlet_and_back(monkeypatch, spy, capsys):
    autoplay(monkeypatch, spy, ["1", "3", "1"], win=False)   # Start Game > Gauntlet > New run
    monkeypatch.setattr(cli, "select_game", _once(cli.select_game))
    assert cli.main(["--plain"]) == 0
    out = capsys.readouterr().out
    assert "The Gauntlet" in out and "THE GAUNTLET CLAIMS YOU" in out
    assert "Thanks for playing!" in out


def _once(select):
    """The real menu the first time, then Exit."""
    calls = []

    def wrapped(ui):
        calls.append(1)
        return select(ui) if len(calls) == 1 else None
    return wrapped


def test_menu_choices_become_run_configs(monkeypatch):
    ui, out = rich_ui()
    to_gauntlet = [K.KEY_ENTER, K.KEY_DOWN, K.KEY_DOWN, K.KEY_ENTER]
    keys(monkeypatch, iter([*to_gauntlet, K.KEY_ENTER]))
    assert menu.select_game(ui) == GauntletConfig()
    keys(monkeypatch, iter([*to_gauntlet, K.KEY_DOWN, K.KEY_ENTER]))
    assert menu.select_game(ui) == GauntletConfig(daily=True)
    keys(monkeypatch, iter([*to_gauntlet, K.KEY_DOWN, K.KEY_DOWN, K.KEY_ENTER,
                            K.KEY_ESC,                               # back out of the seed box
                            K.KEY_DOWN, K.KEY_DOWN, K.KEY_ENTER, "c", "a", "t", K.KEY_ENTER]))
    assert menu.select_game(ui) == GauntletConfig(seed="cat")
    keys(monkeypatch, iter([*to_gauntlet, K.KEY_ESC, K.KEY_ESC, K.KEY_ESC]))
    assert menu.select_game(ui) is None
    assert "Today's tower, the same for everyone" in out.getvalue()


def test_the_daily_entry_shows_todays_best(monkeypatch):
    today = datetime.date.today().isoformat()
    profile_store.save(profile_store.Profile(daily_date=today, daily_score=1234, best_score=4321))
    ui, out = rich_ui()
    keys(monkeypatch, iter([K.KEY_DOWN, K.KEY_ESC]))
    assert menu.gauntlet_menu(ui) is None
    assert "(your best today: 1234)" in out.getvalue()


# ================================================================ rich frames

def play_one_fight(monkeypatch, spy, ui, script=()):
    """Win the first fight on a rich screen, then close the input at the reward menu."""
    def answer(prompt=""):
        if prompt.startswith("Your move"):
            return str(spy["run"].duel.intent.beaten_by)
        raise EOFError

    queue = list(script)
    monkeypatch.setattr("builtins.input",
                        lambda prompt="": queue.pop(0) if queue else answer(prompt))
    return play_gauntlet(ui, GauntletConfig(seed="abc"))


def test_rich_fight_screen_has_bars_pips_hands_and_history(monkeypatch, spy):
    ui, out = rich_ui()
    result = play_one_fight(monkeypatch, spy, ui)
    text = out.getvalue()
    foe = result.run.ladder[0]
    assert "GAUNTLET   |   Floor 1 of 10" in text and "Seed ABC" in text
    assert foe.full_name.upper() in text
    assert "♥ ████████████ 14/14" in text and f"0/{foe.hp}" in text
    assert "● ○ ○ ○  Focus 1/4" in text and "Hits for 2" in text
    assert "YOU WIN!" in text and f"DAMAGE TO {foe.name.upper()}." in text
    rows = [line.split() for line in text.splitlines()]
    assert ["You", "R", "P", "S"] in rows and ["Foe", "S", "R", "P"] in rows   # Parrot copies
    assert ["W", "W", "W"] in rows
    assert "RUN ABANDONED" in text


def test_narrow_terminals_get_the_compact_fight_screen(monkeypatch, spy):
    ui, out = rich_ui(width=60, height=20)
    play_one_fight(monkeypatch, spy, ui)
    text = out.getvalue()
    assert "YOU: " in text and "FOE: " in text
    assert "---'" not in text                              # no hand art
    assert "♥" in text and "Focus 1/4" in text


def test_ascii_mode_uses_no_fancy_characters(monkeypatch, spy):
    ui, out = rich_ui(ascii_only=True)
    play_one_fight(monkeypatch, spy, ui)
    text = out.getvalue()
    assert "HP ############ 14/14" in text and "* . . .  Focus 1/4" in text
    assert text.isascii()


def test_the_prompt_fits_an_80_column_terminal(monkeypatch, spy):
    ui, _ = rich_ui(width=80, height=24)
    run = play.new_run(GauntletConfig(seed="abc"))
    run.begin_fight()
    from rps_game.gauntlet.screens import GauntletScreens
    prompt = GauntletScreens(ui)._prompt(run.duel, None).plain
    assert len(prompt) <= 80
    assert "[f]oresight(2) [g]uard(1) [c]harge(2)" in prompt and prompt.endswith("[q]uit")


def test_headlines():
    def x(mine, theirs, outcome, dealt=0, taken=0):
        return Exchange(1, Round(mine, theirs, outcome), None, dealt, taken, 0, 0, ())

    assert headline(x(R, S, Outcome.WIN, dealt=4), "Pebble") == \
        "You win! Rock crushes scissors: 4 damage to Pebble."
    assert headline(x(R, P, Outcome.LOSS, taken=2), "Pebble") == \
        "You lose! Paper covers rock: you take 2 damage."
    assert headline(x(R, P, Outcome.LOSS), "Pebble") == \
        "You lose! Paper covers rock: but you take no damage."
    assert headline(x(S, S, Outcome.DRAW), "Pebble") == "It's a draw! You both threw scissors."
    assert "luck was on your side" in headline(x(R, P, Outcome.DRAW), "Pebble")   # Lucky Coin


# ================================================================ real keys

def test_playing_with_keys(monkeypatch, spy):
    ui, out = rich_ui()

    def typist():
        yield " "                                           # briefing
        yield " "                                           # foe card
        yield "g"                                           # arm Guard...
        yield "i"                                           # ...read the notes (prints the frame)
        yield " "
        yield "x"                                           # not a key
        yield "q"                                           # leave? no.
        yield "n"
        while True:
            run = spy["run"]
            if run.duel is None:                            # the reward menu: Esc, then confirm
                yield K.KEY_ESC
                yield "y"
                yield " "                                   # leave the summary
                return
            yield str(run.duel.intent.beaten_by)[0]

    keys(monkeypatch, typist())
    result = play_gauntlet(ui, GauntletConfig(seed="abc"), pause=True)
    text = out.getvalue()
    assert result.run.abandoned and result.run.floors_cleared == 1
    assert "Press any key to begin" in text and "Press any key to fight" in text
    assert "Guard ready: You take no damage this round." in text
    assert "FIELD NOTES" in text and "c = Charge (2 Focus)" in text
    assert "is not a move" in text
    assert "Abandon the run?" in text
    assert "Choose a reward" in text and "Rest" in text
    assert "Press any key to return to the menu" in text
    assert result.run.tally.techniques == 1                 # the Guard stayed armed through it all


def test_foresight_with_keys_spends_focus_and_blocks_other_techniques(monkeypatch, spy):
    ui, out = rich_ui()

    def typist():
        yield " "
        yield " "
        yield str(spy["run"].duel.intent.beats)[0]          # lose round 1: Focus 2
        yield "f"
        yield "c"                                           # refused: one technique per round
        yield "i"                                           # prints the frame
        yield " "
        yield str(spy["run"].duel.intent)[0]                # draw
        raise EOFError

    keys(monkeypatch, typist())
    result = play_gauntlet(ui, GauntletConfig(seed="abc"))
    text = out.getvalue()
    assert "One technique per round, and Foresight is already spent." in text
    assert "○ ○ ○ ○  Focus 0/4" in text                    # both points went into the Foresight
    assert result.interrupted and result.run.tally.techniques == 1
    assert result.run.tally.rounds == 2


def test_technique_enum_matches_the_keys():
    from rps_game.gauntlet.screens import TECHNIQUE_KEYS
    assert set(TECHNIQUE_KEYS.values()) == set(Technique)
    assert not set(TECHNIQUE_KEYS) & {"r", "p", "s", "q", "i"}
