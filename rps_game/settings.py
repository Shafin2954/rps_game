"""Small user preferences, stored next to the statistics file.

Reading is forgiving (a corrupt file means defaults) and saving never raises.
Override the location with RPS_SETTINGS_FILE.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from .stats import stats_path


def settings_path() -> Path:
    override = os.environ.get("RPS_SETTINGS_FILE")
    return Path(override) if override else stats_path().with_name("settings.json")


@dataclass
class Settings:
    # Off by default: the results screen shows only the game just played.
    show_stats_after_game: bool = False
    # Which side of your own screen your hand appears on in Dual Player.
    preferred_side: str = "left"

    @classmethod
    def from_dict(cls, data: object) -> "Settings":
        if not isinstance(data, dict):
            return cls()
        flag = data.get("show_stats_after_game")
        side = data.get("preferred_side")
        return cls(
            show_stats_after_game=flag if isinstance(flag, bool) else False,
            preferred_side=side if side in ("left", "right") else "left",
        )


def load(path: Path | None = None) -> Settings:
    try:
        return Settings.from_dict(json.loads((path or settings_path()).read_text("utf-8")))
    except (OSError, ValueError):
        return Settings()


def save(settings: Settings, path: Path | None = None) -> bool:
    target = path or settings_path()
    tmp = target.with_name(target.name + ".tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(asdict(settings), indent=2), "utf-8")
        os.replace(tmp, target)
        return True
    except OSError:
        return False
