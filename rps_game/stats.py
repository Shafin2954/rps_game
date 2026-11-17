"""Lifetime statistics, saved between sessions as a small JSON file.

Location: %APPDATA% on Windows, ~/Library/Application Support on macOS,
$XDG_DATA_HOME (or ~/.local/share) elsewhere. Override with RPS_STATS_FILE.
Reading is forgiving (a corrupt file just means a fresh start) and saving never
raises, so stats can never crash or block the game.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from .engine import Move, Outcome, Round, Score
from .insight import count_reactions, merge_reactions

APP_DIR = "rps-game-cli"
FILE_VERSION = 1


def stats_path() -> Path:
    override = os.environ.get("RPS_STATS_FILE")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / APP_DIR / "stats.json"


def _count(value: object) -> int:
    ok = isinstance(value, int) and not isinstance(value, bool) and value >= 0
    return value if ok else 0  # type: ignore[return-value]


@dataclass
class Stats:
    wins: int = 0
    losses: int = 0
    draws: int = 0
    matches_won: int = 0
    matches_lost: int = 0
    best_streak: int = 0
    sessions: int = 0
    moves: dict[str, int] = field(default_factory=dict)
    # How you react to each result: {"win": {"stay": n, "up": n, "down": n}, ...}.
    # See insight.py for what the steps mean.
    habits: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def rounds(self) -> int:
        return self.wins + self.losses + self.draws

    @property
    def win_rate(self) -> float:
        return self.wins / self.rounds if self.rounds else 0.0

    @property
    def favourite_move(self) -> tuple[str, float] | None:
        total = sum(self.moves.values())
        if not total:
            return None
        name, count = max(self.moves.items(), key=lambda item: item[1])
        return name, count / total

    def merge(self, session: Score, matches: Score, picks: Iterable[Move],
              rounds: Sequence[Round] = ()) -> None:
        """Fold one finished session into the lifetime totals.

        ``rounds`` (optional) are the session's rounds in order; they feed the
        lifetime record of how the player reacts to wins, losses and draws."""
        if session.rounds == 0:
            return
        if rounds:
            merge_reactions(self.habits, count_reactions(rounds))
        self.wins += session.wins
        self.losses += session.losses
        self.draws += session.draws
        self.matches_won += matches.wins
        self.matches_lost += matches.losses
        self.best_streak = max(self.best_streak, session.best_streak)
        self.sessions += 1
        for move in picks:
            self.moves[move.value] = self.moves.get(move.value, 0) + 1

    def to_dict(self) -> dict:
        return {"version": FILE_VERSION, **self.__dict__}

    @classmethod
    def from_dict(cls, data: object) -> "Stats":
        if not isinstance(data, dict):
            return cls()
        known = {m.value for m in Move}
        raw_moves = data.get("moves")
        moves = (
            {k: _count(v) for k, v in raw_moves.items() if k in known}
            if isinstance(raw_moves, dict) else {}
        )
        raw_habits = data.get("habits")
        habits = {}
        if isinstance(raw_habits, dict):
            for outcome in (o.value for o in Outcome):
                steps = raw_habits.get(outcome)
                if isinstance(steps, dict):
                    habits[outcome] = {s: _count(steps.get(s)) for s in ("stay", "up", "down")}
        return cls(
            wins=_count(data.get("wins")),
            losses=_count(data.get("losses")),
            draws=_count(data.get("draws")),
            matches_won=_count(data.get("matches_won")),
            matches_lost=_count(data.get("matches_lost")),
            best_streak=_count(data.get("best_streak")),
            sessions=_count(data.get("sessions")),
            moves=moves,
            habits=habits,
        )


def load(path: Path | None = None) -> Stats:
    try:
        return Stats.from_dict(json.loads((path or stats_path()).read_text("utf-8")))
    except (OSError, ValueError):
        return Stats()


def save(stats: Stats, path: Path | None = None) -> bool:
    """Atomically write stats. Returns False (never raises) on failure."""
    target = path or stats_path()
    tmp = target.with_name(target.name + ".tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(stats.to_dict(), indent=2), "utf-8")
        os.replace(tmp, target)
        return True
    except OSError:
        return False


def reset(path: Path | None = None) -> bool:
    try:
        (path or stats_path()).unlink()
    except FileNotFoundError:
        pass
    except OSError:
        return False
    return True
