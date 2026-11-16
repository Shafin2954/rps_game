import itertools

from rps_game.engine import MOVES, Move
from rps_game.net import fairness as f


def test_commitments_are_deterministic_and_look_like_sha256():
    d = f.commitment(1, "host", Move.ROCK, "a" * 32)
    assert d == f.commitment(1, "host", Move.ROCK, "a" * 32)
    assert len(d) == 64 and set(d) <= set("0123456789abcdef")


def test_any_change_to_any_input_changes_the_commitment():
    base = f.commitment(1, "host", Move.ROCK, "a" * 32)
    assert f.commitment(2, "host", Move.ROCK, "a" * 32) != base          # another round
    assert f.commitment(1, "join", Move.ROCK, "a" * 32) != base          # reflected at its sender
    assert f.commitment(1, "host", Move.PAPER, "a" * 32) != base         # another move
    assert f.commitment(1, "host", Move.ROCK, "b" * 32) != base          # another nonce


def test_a_commitment_does_not_reveal_the_move():
    """Without the nonce, all three possible moves are equally consistent with a commitment
    (each move has a different digest, none obviously related to the move)."""
    nonce = f.new_nonce()
    digests = {m: f.commitment(1, "host", m, nonce) for m in MOVES}
    assert len(set(digests.values())) == 3
    # a guesser who doesn't know the nonce can't test a guess against the digest
    other = f.new_nonce()
    assert all(f.commitment(1, "host", m, other) != digests[Move.ROCK] for m in MOVES)


def test_nonces_are_32_hex_digits_and_not_repeated():
    nonces = {f.new_nonce() for _ in range(500)}
    assert len(nonces) == 500
    assert all(len(n) == 32 and set(n) <= set("0123456789abcdef") for n in nonces)


def test_known_answer_vectors():
    """Pinned so an accidental change to the wire format (which would silently break
    compatibility between versions) fails loudly. Each value was also re-derived by hand
    from the documented format with hashlib, independently of the code under test."""
    assert f.commitment(3, "join", Move.SCISSORS, "0123456789abcdef0123456789abcdef") == (
        "9a13ff8321c44441ddc2765236e28ba4e0f622a89e859b84c034f17a731dec86")
    assert f.INITIAL_STATE == "8bdaa5d2acfbd77e02caedaaad974caa40df721b0a1377943d2d02f30d23b665"
    assert f.next_state(f.INITIAL_STATE, 1, Move.ROCK, Move.PAPER) == (
        "b0d5c20467432b97e529092180cbf8b7db5c7a98e304f3bf6555e2384c47f1f6")


def test_the_documented_format_is_what_the_code_does():
    import hashlib
    assert f.commitment(9, "host", Move.PAPER, "f" * 32) == hashlib.sha256(
        b"rps-v1|9|host|paper|" + b"f" * 32).hexdigest()
    prev = "e" * 64
    assert f.next_state(prev, 4, Move.ROCK, Move.ROCK) == hashlib.sha256(
        (prev + "|4|rock|rock").encode()).hexdigest()


def test_state_chain_depends_on_every_round_in_order():
    s = f.INITIAL_STATE
    a = f.next_state(f.next_state(s, 1, Move.ROCK, Move.PAPER), 2, Move.PAPER, Move.PAPER)
    swapped = f.next_state(f.next_state(s, 1, Move.PAPER, Move.PAPER), 2, Move.ROCK, Move.PAPER)
    assert a != swapped
    assert a == f.next_state(f.next_state(s, 1, Move.ROCK, Move.PAPER), 2, Move.PAPER, Move.PAPER)


def test_state_depends_on_who_threw_what():
    s = f.INITIAL_STATE
    assert f.next_state(s, 1, Move.ROCK, Move.PAPER) != f.next_state(s, 1, Move.PAPER, Move.ROCK)


def test_all_distinct_commitments_over_a_small_space():
    seen = {f.commitment(r, role, m, "c" * 32)
            for r, role, m in itertools.product(range(1, 6), ("host", "join"), MOVES)}
    assert len(seen) == 5 * 2 * 3
