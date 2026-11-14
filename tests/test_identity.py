import json

from rps_game import identity


def test_creates_once_and_then_stays_stable(tmp_path):
    p = tmp_path / "id.json"
    first = identity.install_id(p)
    assert identity.valid_install_id(first)
    assert identity.install_id(p) == first == json.loads(p.read_text())["id"]


def test_ids_differ_between_installs(tmp_path):
    assert identity.install_id(tmp_path / "a.json") != identity.install_id(tmp_path / "b.json")


def test_corrupt_or_forged_files_are_replaced_not_trusted(tmp_path):
    p = tmp_path / "id.json"
    for junk in ("nope", "[]", '{"id": "short"}', '{"id": "ZZ' + "0" * 30 + '"}', '{"id": 5}'):
        p.write_text(junk)
        assert identity.valid_install_id(identity.install_id(p))


def test_unwritable_location_still_returns_a_valid_id(tmp_path):
    blocker = tmp_path / "f"
    blocker.write_text("x")
    assert identity.valid_install_id(identity.install_id(blocker / "sub" / "id.json"))


def test_validation():
    assert identity.valid_install_id("a" * 32)
    for bad in ("A" * 32, "a" * 31, "a" * 33, "g" * 32, 5, None):
        assert not identity.valid_install_id(bad)
