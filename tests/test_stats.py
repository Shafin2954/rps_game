import json

from rps_game import stats
from rps_game.engine import Move, Outcome, Score


def _session(*outcomes):
    s = Score()
    for o in outcomes:
        s.record(o)
    return s


def test_missing_file_gives_fresh_stats():
    assert stats.load().rounds == 0


def test_round_trip(isolated_stats):
    st = stats.Stats()
    st.merge(_session(Outcome.WIN, Outcome.WIN, Outcome.LOSS), _session(Outcome.WIN),
             [Move.ROCK, Move.ROCK, Move.PAPER])
    assert stats.save(st)
    loaded = stats.load()
    assert (loaded.wins, loaded.losses, loaded.sessions) == (2, 1, 1)
    assert loaded.moves == {"rock": 2, "paper": 1}
    assert loaded.best_streak == 2
    assert loaded.favourite_move[0] == "rock"


def test_merge_accumulates_and_keeps_best_streak():
    st = stats.Stats()
    st.merge(_session(*[Outcome.WIN] * 4), Score(), [])
    st.merge(_session(Outcome.WIN, Outcome.LOSS), Score(), [])
    assert (st.wins, st.sessions, st.best_streak) == (5, 2, 4)


def test_empty_session_is_not_counted():
    st = stats.Stats()
    st.merge(Score(), Score(), [])
    assert st.sessions == 0


def test_corrupt_files_are_ignored(isolated_stats):
    for junk in ("not json", "[]", '{"wins": "lots", "moves": 7}', ""):
        isolated_stats.write_text(junk)
        assert stats.load().wins == 0


def test_negative_and_unknown_values_are_sanitised(isolated_stats):
    isolated_stats.write_text(json.dumps(
        {"wins": -5, "losses": 3, "moves": {"rock": 2, "lizard": 9, "paper": -1}}))
    st = stats.load()
    assert (st.wins, st.losses, st.moves) == (0, 3, {"rock": 2, "paper": 0})


def test_save_failure_is_reported_not_raised(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert stats.save(stats.Stats(), blocker / "sub" / "stats.json") is False


def test_reset(isolated_stats):
    stats.save(stats.Stats(wins=3))
    assert stats.reset() and not isolated_stats.exists()
    assert stats.reset()   # already gone: still fine
