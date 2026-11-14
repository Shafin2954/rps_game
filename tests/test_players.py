from rps_game.engine import Move, Outcome, Round
from rps_game.players import CpuOpponent, Seat, Side


def test_side_other_and_str():
    assert Side.LEFT.other is Side.RIGHT and Side.RIGHT.other is Side.LEFT
    assert str(Side.LEFT) == "left"


def test_seat_defaults():
    assert Seat("Alice") == Seat("Alice", Side.LEFT)


def test_cpu_opponent_never_sees_the_current_move_and_learns_afterwards():
    seen = []

    class Spy:
        def choose(self, history):
            seen.append(list(history))
            return Move.PAPER

    cpu = CpuOpponent(Spy())
    assert cpu.play(Move.ROCK) is Move.PAPER
    assert seen == [[]]                                   # own move was not leaked
    cpu.record(Round(Move.ROCK, Move.PAPER, Outcome.LOSS))
    cpu.play(Move.SCISSORS)
    assert seen[1] == [Move.ROCK]                         # only the past round


def test_cpu_history_is_read_only():
    cpu = CpuOpponent(type("S", (), {"choose": lambda self, h: Move.ROCK})())
    cpu.record(Round(Move.PAPER, Move.ROCK, Outcome.WIN))
    assert cpu.history == (Move.PAPER,)
