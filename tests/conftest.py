import pytest


@pytest.fixture(autouse=True)
def isolated_stats(tmp_path, monkeypatch):
    """Never let a test read or write the real stats file."""
    path = tmp_path / "stats.json"
    monkeypatch.setenv("RPS_STATS_FILE", str(path))
    return path


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    """A test that reaches for the real mailbox is a bug: fail loudly instead."""
    def refuse(url):
        raise AssertionError(f"test tried to open a real network connection to {url}")

    monkeypatch.setattr("rps_game.net.connect.create_transport", refuse)
    monkeypatch.setenv("RPS_IDENTITY_FILE", str(__import__("pathlib").Path(
        __import__("tempfile").mkdtemp()) / "identity.json"))
    monkeypatch.delenv("RPS_MAILBOX", raising=False)
