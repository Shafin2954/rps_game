
from rps_game import settings


def test_defaults_to_not_showing_stats_after_games():
    assert settings.load().show_stats_after_game is False


def test_round_trip(tmp_path):
    p = tmp_path / "s.json"
    assert settings.save(settings.Settings(show_stats_after_game=True), p)
    assert settings.load(p).show_stats_after_game is True


def test_junk_files_fall_back_to_defaults(tmp_path):
    p = tmp_path / "s.json"
    for junk in ("not json", "[]", '{"show_stats_after_game": "yes"}', ""):
        p.write_text(junk)
        assert settings.load(p).show_stats_after_game is False


def test_save_failure_is_reported_not_raised(tmp_path):
    blocker = tmp_path / "f"
    blocker.write_text("x")
    assert settings.save(settings.Settings(), blocker / "sub" / "s.json") is False


def test_default_location_sits_next_to_the_stats_file(isolated_stats):
    assert settings.settings_path().parent == isolated_stats.parent


def test_preferred_side_defaults_to_left_and_round_trips(tmp_path):
    assert settings.load(tmp_path / "none.json").preferred_side == "left"
    p = tmp_path / "s.json"
    settings.save(settings.Settings(preferred_side="right"), p)
    assert settings.load(p).preferred_side == "right"


def test_unknown_side_values_fall_back_to_left(tmp_path):
    p = tmp_path / "s.json"
    for junk in ('{"preferred_side": "middle"}', '{"preferred_side": 3}', '{"preferred_side": null}'):
        p.write_text(junk)
        assert settings.load(p).preferred_side == "left"
