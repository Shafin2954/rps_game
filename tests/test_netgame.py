"""NetworkOpponent: fair rounds, and every way a hostile or broken peer can misbehave."""
import random
import threading
import time

import pytest

from netutil import connected_pair, recv, send
from rps_game.engine import MOVES, Move, Round, judge
from rps_game.net import fairness
from rps_game.net import protocol as proto
from rps_game.net.errors import (Cancelled, CheatDetected, ConnectionLost, PeerLeft, ProtocolError,
                                 Timeout)
from rps_game.net.game import NetworkOpponent

R, P, S = Move.ROCK, Move.PAPER, Move.SCISSORS
SLOW_PING = dict(ping_interval=60, first_ping_delay=60, liveness_timeout=600)        # keep heartbeats out of the way


@pytest.fixture
def make():
    """make(**kw) -> (host_opponent, join_opponent, mailbox); everything is closed afterwards."""
    opened = []

    def factory(wrap=("host", "join"), **kw):
        options = {**SLOW_PING, **kw}
        if "ping_interval" in kw and "first_ping_delay" not in kw:
            options["first_ping_delay"] = kw["ping_interval"]       # asking for fast pings means *now*
        host, join, box = connected_pair()
        h = NetworkOpponent(host, **options) if "host" in wrap else host
        j = NetworkOpponent(join, **options) if "join" in wrap else join
        opened.extend(x for x in (h, j) if isinstance(x, NetworkOpponent))
        return h, j, box

    yield factory
    for opp in opened:
        opp.close()


def wait_until(predicate, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def concurrently(*calls):
    """Run callables in threads; return their results (or the exception each raised)."""
    results = [None] * len(calls)

    def runner(i, fn):
        try:
            results[i] = fn()
        except BaseException as exc:                      # noqa: BLE001
            results[i] = exc

    threads = [threading.Thread(target=runner, args=(i, fn), daemon=True) for i, fn in enumerate(calls)]
    [t.start() for t in threads]
    [t.join(15) for t in threads]
    assert not any(t.is_alive() for t in threads), "a call hung"
    return results


def play_round(h, j, hm, jm):
    return concurrently(lambda: h.play(hm), lambda: j.play(jm))


def finish(opp, mine, theirs):
    opp.record(Round(mine, theirs, judge(mine, theirs)))


def commit_for(round_no, role, move, nonce=None, state=fairness.INITIAL_STATE):
    nonce = nonce or fairness.new_nonce()
    return proto.Commit(round_no, fairness.commitment(round_no, role, move, nonce), state), nonce


# ============================================================ honest play

def test_each_side_learns_the_others_move(make):
    h, j, _ = make()
    got_h, got_j = play_round(h, j, R, S)
    assert (got_h, got_j) == (S, R)


@pytest.mark.parametrize("mine, theirs", [(a, b) for a in MOVES for b in MOVES])
def test_all_nine_move_pairs(make, mine, theirs):
    h, j, _ = make()
    assert play_round(h, j, mine, theirs) == [theirs, mine]


def test_forty_random_rounds_keep_both_sides_in_lockstep(make):
    h, j, _ = make()
    rng = random.Random(7)
    for n in range(1, 41):
        hm, jm = rng.choice(MOVES), rng.choice(MOVES)
        got_h, got_j = play_round(h, j, hm, jm)
        assert (got_h, got_j) == (jm, hm)
        finish(h, hm, jm)
        finish(j, jm, hm)
        assert h.round == j.round == n + 1
        assert h.state == j.state != fairness.INITIAL_STATE


def test_a_slow_player_is_not_mistaken_for_a_dropped_connection(make):
    """Heartbeats are answered by the reader thread, whatever the player is doing."""
    h, j, _ = make(ping_interval=0.05, liveness_timeout=0.5, commit_timeout=10)

    def slow_join():
        time.sleep(1.4)                                    # thinks for much longer than the liveness limit
        return j.play(P)

    got = concurrently(lambda: h.play(R), slow_join)
    assert got == [P, R]


def test_round_trip_time_is_measured(make):
    h, j, _ = make(ping_interval=0.05, liveness_timeout=5)
    assert wait_until(lambda: h.rtt_ms is not None and j.rtt_ms is not None)
    assert 0 <= h.rtt_ms < 500


def test_the_opponents_commitment_is_visible_while_choosing(make):
    h, j, _ = make()
    assert j.poll_status() == "Sohan is choosing..."
    t = threading.Thread(target=lambda: _safe(lambda: h.play(R)), daemon=True)
    t.start()
    assert wait_until(lambda: j.poll_status() == "Sohan has locked in")
    assert j.play(P) == R
    t.join(5)


# ============================================================ wire-level guarantees

def test_nothing_reveals_a_move_before_both_players_have_committed(make):
    frames = []
    h, j, box = make()
    box.tamper = lambda role, data: frames.append((role, data)) or data
    for _ in range(6):
        play_round(h, j, random.choice(MOVES), random.choice(MOVES))
        finish(h, R, R); finish(j, R, R)                   # state must match; moves irrelevant here
    messages = [(role, proto.decode(data)) for role, data in frames]
    kinds = [type(m).__name__ for _, m in messages]
    # per round: two Commits strictly before the two Reveals
    for i in range(0, len(kinds), 4):
        assert sorted(kinds[i:i + 2]) == ["Commit", "Commit"] and sorted(kinds[i + 2:i + 4]) == ["Reveal", "Reveal"]
    # a move name appears in no frame before the first Reveal
    first_reveal = kinds.index("Reveal")
    for _, data in frames[:first_reveal]:
        assert not any(name in data for name in (b"rock", b"paper", b"scissors"))


def test_a_players_reveal_never_precedes_their_view_of_the_other_commitment(make):
    """Each side sends its Reveal only after receiving the other's Commit."""
    log = []
    h, j, box = make()

    def tap(role, data):
        log.append((role, type(proto.decode(data)).__name__))
        return data

    box.tamper = tap
    play_round(h, j, R, P)
    for role in ("first", "second"):
        mine = [k for r, k in log if r == role]
        assert mine == ["Commit", "Reveal"]
    other = {"first": "second", "second": "first"}
    for i, (role, kind) in enumerate(log):
        if kind == "Reveal":
            assert ("Commit" in [k for r, k in log[:i] if r == other[role]]), "revealed before seeing their commit"


# ============================================================ cheating

def test_a_changed_move_is_caught(make):
    h, j, box = make()
    box.tamper = lambda role, data: data.replace(b'"rock"', b'"paper"') if role == "first" else data
    got_h, got_j = play_round(h, j, R, S)
    assert isinstance(got_j, CheatDetected) and "Sohan" in str(got_j)
    assert isinstance(j.error, CheatDetected)
    with pytest.raises(CheatDetected):
        j.poll_status()


def test_a_changed_nonce_is_caught(make):
    h, j, box = make()

    def tamper(role, data):                                # swap the host's nonce for another valid one
        msg = proto.decode(data)
        if role == "first" and isinstance(msg, proto.Reveal):
            return proto.encode(proto.Reveal(msg.round, msg.move, "0" * 32))
        return data
    box.tamper = tamper
    _, got_j = play_round(h, j, R, S)
    assert isinstance(got_j, CheatDetected)


def test_picking_the_move_after_seeing_the_others_is_impossible(make):
    """A cheater who waits to see our reveal still can't change what they committed to."""
    h, j, _ = make(wrap=("join",))                         # host is a hand-driven "cheater"
    cheat_commit, nonce = commit_for(1, "host", R)
    t = threading.Thread(target=lambda: _safe(lambda: j.play(S)), daemon=True)
    t.start()
    mine = recv(h)                                         # our commit
    assert isinstance(mine, proto.Commit)
    send(h, cheat_commit)                                  # they committed to rock...
    reveal = recv(h)                                       # we reveal scissors
    assert reveal.move == "scissors"
    send(h, proto.Reveal(1, "paper", nonce))               # ...saw it, and now claim paper to win
    t.join(5)
    assert isinstance(j.error, CheatDetected)


# ============================================================ protocol violations

def error_of(opp):
    assert wait_until(lambda: opp.error is not None), "no error was raised"
    return opp.error


def test_a_reveal_before_we_have_locked_in_is_refused(make):
    h, j, _ = make(wrap=("join",))
    commit, nonce = commit_for(1, "host", R)
    send(h, commit)
    send(h, proto.Reveal(1, "rock", nonce))                # honest peers wait for *our* commit
    assert "locked in" in error_of(j).detail
    with pytest.raises(ProtocolError):
        j.poll_status()


@pytest.mark.parametrize("name, build", [
    ("wrong round", lambda c, n: [proto.Commit(5, c.digest, c.state)]),
    ("duplicate commit", lambda c, n: [c, c]),
    ("reveal without commit", lambda c, n: [proto.Reveal(1, "rock", n)]),
    ("reveal for another round", lambda c, n: [c, proto.Reveal(2, "rock", n)]),
    ("commit for the next round too early", lambda c, n: [c, proto.Commit(2, c.digest, c.state)]),
    ("a hello mid-game", lambda c, n: [proto.Hello(1, "Mallory", "c" * 32, "9.9")]),
    ("a start mid-game", lambda c, n: [proto.Start()]),
    ("settings mid-game", lambda c, n: [proto.Settings(3, None)]),
])
def test_protocol_violations_end_the_game(make, name, build):
    h, j, _ = make(wrap=("join",))
    commit, nonce = commit_for(1, "host", R)
    for message in build(commit, nonce):
        send(h, message)
    assert isinstance(error_of(j), ProtocolError)


def test_malformed_bytes_end_the_game(make):
    h, j, _ = make(wrap=("join",))
    h.transport.send(b"\x00\xffnot json")
    assert isinstance(error_of(j), ProtocolError)


def test_the_state_hashes_must_agree(make):
    h, j, _ = make(wrap=("join",))
    t_result = []
    t = threading.Thread(target=lambda: t_result.append(_safe(lambda: j.play(S))), daemon=True)
    t.start()
    assert isinstance(recv(h), proto.Commit)
    bad, _ = commit_for(1, "host", R, state="f" * 64)      # claims a different history
    send(h, bad)
    t.join(5)
    assert isinstance(t_result[0], ProtocolError) and "disagree" in str(t_result[0])


def _safe(fn):
    try:
        return fn()
    except BaseException as exc:                           # noqa: BLE001
        return exc


# ============================================================ leaving, silence, time limits

def test_the_other_player_leaving_is_reported(make):
    h, j, _ = make()
    h.close("quit")
    assert isinstance(error_of(j), PeerLeft)
    with pytest.raises(PeerLeft):
        j.poll_status()
    with pytest.raises(PeerLeft):
        j.play(R)


def test_a_silent_peer_is_declared_gone_after_the_liveness_limit(make):
    h, j, _ = make(wrap=("join",), ping_interval=0.05, liveness_timeout=0.4)
    started = time.monotonic()
    assert isinstance(error_of(j), ConnectionLost)
    assert 0.3 < time.monotonic() - started < 3


def test_waiting_for_a_commit_times_out(make):
    h, j, _ = make(wrap=("join",), commit_timeout=0.3)
    with pytest.raises(Timeout, match="lock in"):
        j.play(R)


def test_waiting_for_a_reveal_times_out(make):
    h, j, _ = make(wrap=("join",), reveal_timeout=0.3)
    result = []
    t = threading.Thread(target=lambda: result.append(_safe(lambda: j.play(R))), daemon=True)
    t.start()
    assert isinstance(recv(h), proto.Commit)
    commit, _ = commit_for(1, "host", S)
    send(h, commit)                                        # commits... then never reveals
    t.join(5)
    assert isinstance(result[0], Timeout) and "reveal" in str(result[0])


def test_the_player_can_cancel_a_wait(make):
    h, j, _ = make(wrap=("join",))
    seen = []
    j.on_wait = lambda text: seen.append(text) or False
    with pytest.raises(Cancelled):
        j.play(R)
    assert seen == ["Waiting for Sohan to lock in..."]


def test_a_transport_failure_while_sending_is_a_lost_connection(make):
    h, j, _ = make(wrap=("join",))
    h.close()
    j._transport.close()
    with pytest.raises(Exception) as caught:
        j.play(R)
    assert isinstance(caught.value, (ConnectionLost, PeerLeft))


def test_an_internal_bug_never_hangs_the_game(make):
    h, j, _ = make(wrap=("join",))
    original = j._transport.recv
    j._transport.recv = lambda timeout: (_ for _ in ()).throw(RuntimeError("boom"))
    assert isinstance(error_of(j), ConnectionLost)
    assert isinstance(j.crash, RuntimeError)
    j._transport.recv = original


def test_close_is_idempotent_and_stops_the_reader(make):
    h, j, _ = make()
    j.close(); j.close()
    assert not j._thread.is_alive()
    with pytest.raises(Exception):
        j.play(R)


# ============================================================ rematch

def test_a_rematch_resets_the_game_for_both_sides(make):
    h, j, _ = make()
    for _ in range(3):
        play_round(h, j, R, P)
        finish(h, R, P); finish(j, P, R)
    assert h.round == 4
    results = concurrently(h.rematch, j.rematch)
    assert results == [None, None]
    assert h.round == j.round == 1 and h.state == j.state == fairness.INITIAL_STATE
    assert play_round(h, j, S, S) == [S, S]                # a fresh game works


def test_rematch_when_the_other_asked_first(make):
    h, j, _ = make()
    t = threading.Thread(target=h.rematch, daemon=True)
    t.start()
    assert wait_until(lambda: j.results_status() == "Sohan wants to play again.")
    j.rematch()
    t.join(5)
    assert h.round == j.round == 1


def test_rematch_is_refused_if_the_other_player_leaves(make):
    h, j, _ = make()
    t = threading.Thread(target=lambda: h.close("quit"), daemon=True)
    t.start()
    with pytest.raises((PeerLeft, ConnectionLost)):
        j.rematch()
    assert j.results_status() == "Sohan has left."


def test_rematch_times_out_without_an_answer(make):
    h, j, _ = make(rematch_timeout=0.3)
    with pytest.raises(Timeout, match="play again"):
        j.rematch()


def test_rematch_races_never_break_the_next_game(make):
    """Both sides ask for a rematch with random delays and start playing instantly."""
    h, j, _ = make()
    rng = random.Random(3)
    for game in range(15):
        play_round(h, j, R, S)
        finish(h, R, S); finish(j, S, R)

        def go(opp, delay, move):
            time.sleep(delay)
            opp.rematch()
            return opp.play(move)                          # no pause between rematch and first commit

        got = concurrently(lambda: go(h, rng.random() * 0.05, R), lambda: go(j, rng.random() * 0.05, P))
        assert got == [P, R], f"game {game}: {got}"
        finish(h, R, P); finish(j, P, R)


# ============================================================ fuzzing a peer

def test_no_sequence_of_hostile_messages_crashes_or_hangs_us(make):
    hypothesis = pytest.importorskip("hypothesis")
    st = pytest.importorskip("hypothesis.strategies")
    nonce = "d" * 32
    digest = fairness.commitment(1, "host", R, nonce)
    pool = [
        proto.Commit(1, digest, fairness.INITIAL_STATE), proto.Commit(2, digest, "e" * 64),
        proto.Commit(1, "0" * 64, fairness.INITIAL_STATE),
        proto.Reveal(1, "rock", nonce), proto.Reveal(1, "paper", nonce), proto.Reveal(2, "rock", nonce),
        proto.Rematch(), proto.Ping(1), proto.Pong(1), proto.Pong(99),
        proto.Hello(1, "Mallory", "c" * 32, "1.0"), proto.Start(), proto.Accept(),
        proto.Settings(3, None), proto.Bye("quit"), proto.RejectName("taken"),
    ]

    @hypothesis.settings(max_examples=60, deadline=None,
                         suppress_health_check=list(hypothesis.HealthCheck))
    @hypothesis.given(st.lists(st.sampled_from(pool), max_size=8))
    def run(messages):
        h, j, _ = make(wrap=("join",))
        for message in messages:
            try:
                send(h, message)
            except Exception:                              # noqa: BLE001 - peer already gone
                break
        time.sleep(0.02)
        j.close()
        assert not j._thread.is_alive()
        assert j.crash is None, repr(j.crash)              # only *clean* NetErrors, never a bug
    run()
