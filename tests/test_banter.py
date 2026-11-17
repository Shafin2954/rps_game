"""Opponents that talk: the Gauntlet's foes and the Oracle explaining itself."""
import random

from rps_game import cli
from rps_game.engine import MOVES, Move, Outcome, Round, judge
from rps_game.gauntlet import banter
from rps_game.gauntlet.banter import VOICES, last_words, quip
from rps_game.gauntlet.foes import FOES
from rps_game.gauntlet.rules import Duel, Foe, Hero
from rps_game.oracle import OracleStrategy
from rps_game.players import CpuOpponent
from rps_game.strategies import RandomStrategy

R, P, S = Move.ROCK, Move.PAPER, Move.SCISSORS


class Always:
    def __init__(self, move):
        self._move = move

    def choose(self, sight):
        return self._move


def fight(foe_move, hp=500):
    return Duel(Hero(hp=500, max_hp=500), Foe("Dummy", hp, 2, Always(foe_move)))


# ================================================================ the foes

def test_every_foe_has_a_full_voice():
    assert set(VOICES) == set(FOES)
    for key, voice in VOICES.items():
        assert len(voice.win) >= 2 and len(voice.lose) >= 2, key
        for line in (*voice.win, *voice.lose, voice.fall, voice.gloat):
            assert line and len(line) <= 60, (key, line)     # fits under the hands


def test_a_foe_comments_on_some_decisive_rounds_and_in_character():
    duel, rng = fight(S), random.Random(1)
    said = [quip("pebble", duel, duel.resolve(R), rng) for _ in range(20)]     # it keeps losing
    spoken = [line for line in said if line]
    assert 3 <= len(spoken) <= 14                           # sometimes, not always
    assert set(spoken) <= set(VOICES["pebble"].lose)

    duel = fight(P)
    said = [quip("pebble", duel, duel.resolve(R), rng) for _ in range(20)]     # now it wins
    assert {line for line in said if line} <= set(VOICES["pebble"].win)


def test_draws_and_the_final_blow_get_no_small_talk():
    duel, rng = fight(R), random.Random(0)
    assert all(quip("loop", duel, duel.resolve(R), rng) is None for _ in range(20))
    duel = fight(S, hp=2)
    assert quip("loop", duel, duel.resolve(R), random.Random(0)) is None       # the knockout
    assert last_words("loop", hero_won=True) == VOICES["loop"].fall
    assert last_words("loop", hero_won=False) == VOICES["loop"].gloat


def test_the_same_line_is_not_said_twice_running():
    duel, rng = fight(S), random.Random(5)
    previous = ""
    for _ in range(60):
        line = quip("blitz", duel, duel.resolve(R), rng, avoid=previous)
        if line:
            assert line != previous
            previous = line


def test_banter_is_seeded():
    def talk(seed):
        duel, rng = fight(S), random.Random(seed)
        return [quip("vex", duel, duel.resolve(R), rng) for _ in range(15)]

    assert talk(3) == talk(3)


def test_a_mind_that_can_explain_itself_speaks_first():
    class Explainer(Always):
        def __init__(self):
            super().__init__(P)
            self.heard = []

        def explain(self, theirs, won):
            self.heard.append((theirs, won))
            return "I saw it." if won else None

    duel = Duel(Hero(hp=50, max_hp=50), Foe("Dummy", 50, 2, Explainer()))
    rng = random.Random(0)
    assert quip("oracle", duel, duel.resolve(R), rng) == "I saw it."           # it won
    duel.foe.mind._move = S
    line = quip("oracle", duel, duel.resolve(R), rng)                          # it lost
    assert line is None or line in VOICES["oracle"].lose
    assert duel.foe.mind.heard == [(R, True), (R, False)]                      # told every time


# ================================================================ the Oracle explains

def play_oracle(throws, seed=0):
    """Feed the Oracle a list of throws; returns [(round result for it, what it said)]."""
    bot = OracleStrategy(rng=random.Random(seed))
    history, out = [], []
    for throw in throws:
        answer = bot.choose(history)
        won = judge(answer, throw) is Outcome.WIN
        out.append((won, bot.explain(throw, won)))
        history.append(throw)
    return out


def test_the_oracle_says_how_it_read_a_one_move_player():
    said = [line for _, line in play_oracle([R] * 30) if line]
    assert said and all("rock" in line.lower() for line in said)
    assert len(said) <= 10                                  # every third round at most


def test_it_only_speaks_after_winning_on_a_read():
    for won, line in play_oracle([MOVES[i % 3] for i in range(40)]):
        assert line is None or won


def test_it_keeps_quiet_about_luck():
    rng = random.Random(9)
    spoken = 0
    for seed in range(20):
        throws = [rng.choice(MOVES) for _ in range(40)]
        spoken += sum(1 for _, line in play_oracle(throws, seed) if line)
    assert spoken <= 20                                     # under one boast per 40 random rounds


def test_it_notices_being_second_guessed():
    # Throw whatever beats the Oracle's previous throw: a reaction to it, not a habit of ours.
    bot = OracleStrategy(rng=random.Random(2))
    history, said, last = [], [], R
    for _ in range(60):
        throw = last.beaten_by
        last = bot.choose(history)
        line = bot.explain(throw, judge(last, throw) is Outcome.WIN)
        if line:
            said.append(line)
        history.append(throw)
    assert said and all(line.endswith(".") and len(line) <= 70 for line in said)


def test_explaining_twice_for_one_round_says_nothing_new():
    bot = OracleStrategy(rng=random.Random(0))
    history = [R] * 20
    for n in range(8, 20):
        bot.choose(history[:n])
    first = bot.explain(R, True)
    assert bot.explain(R, True) is None and (first is None or "rock" in first.lower())


# ================================================================ in a classic game

def test_the_computer_quotes_the_oracle_and_other_strategies_stay_silent():
    oracle = CpuOpponent(OracleStrategy(rng=random.Random(0)))
    lines = []
    for _ in range(20):
        theirs = oracle.play(R)
        rnd = Round(R, theirs, judge(R, theirs))
        oracle.record(rnd)
        lines.append(oracle.quip(rnd))
    spoken = [line for line in lines if line]
    assert spoken
    assert all(line.startswith('The Oracle: "') and line.endswith('"') for line in spoken)

    quiet = CpuOpponent(RandomStrategy(random.Random(0)))
    quiet.record(Round(R, S, Outcome.WIN))
    assert quiet.quip(Round(R, S, Outcome.WIN)) is None


def test_oracle_lines_appear_in_a_plain_game(monkeypatch, capsys):
    answers = iter(["r"] * 15 + ["q"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    cli.main(["--plain", "-d", "oracle"])
    out = capsys.readouterr().out
    assert 'The Oracle: "' in out
    quoted = [line for line in out.splitlines() if line.startswith("The Oracle:")]
    assert all("rock" in line.lower() for line in quoted)


def test_other_difficulties_say_nothing(monkeypatch, capsys):
    answers = iter(["r"] * 15 + ["q"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    cli.main(["--plain", "-d", "hard"])
    assert "Oracle" not in capsys.readouterr().out


def test_a_rich_round_shows_what_was_said():
    import io

    from rich.console import Console

    from rps_game.engine import Match, Score
    from rps_game.ui import GameUI
    out = io.StringIO()
    ui = GameUI(animate=False, console=Console(file=out, width=100, height=30,
                                               force_terminal=False))
    match, session = Match(), Score()
    ui.start_round(match, session, "oracle")
    rnd = match.play(R, P)
    session.record(rnd.outcome)
    ui.show_round(rnd, match, session, said='The Oracle: "You are legible."')
    ui.end_round()
    assert 'The Oracle: "You are legible."' in out.getvalue()


# ================================================================ in the Gauntlet

def test_a_gauntlet_fight_ends_with_last_words(monkeypatch, capsys):
    from rps_game.gauntlet import play
    from rps_game.gauntlet.play import GauntletConfig, play_gauntlet
    from rps_game.ui import GameUI
    box = {}
    real = play.new_run
    monkeypatch.setattr(play, "new_run", lambda config: box.setdefault("run", real(config)))

    def answer(prompt=""):
        if prompt.startswith("Your move"):
            return str(box["run"].duel.intent.beats)        # lose every round
        raise AssertionError(prompt)

    monkeypatch.setattr("builtins.input", answer)
    play_gauntlet(GameUI(plain=True), GauntletConfig(seed="abc"))
    out = capsys.readouterr().out
    foe = box["run"].ladder[0]
    assert f'{foe.name}: "{VOICES[foe.key].gloat}"' in out
    said = [line for line in out.splitlines() if line.startswith(f'{foe.name}: "')]
    assert all(line.split('"')[1] in (*VOICES[foe.key].win, VOICES[foe.key].gloat) for line in said)
    assert banter.CHATTINESS < 1
