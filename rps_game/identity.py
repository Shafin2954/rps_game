"""A random, anonymous per-install ID.

It lets head-to-head statistics follow a *person* rather than a display name
(two different "Alice"s stay separate, a renamed friend keeps their history).
It is not a secret and proves nothing about who you are.
"""
from __future__ import annotations

import json
import os
import re
import secrets
from pathlib import Path

from .stats import stats_path

_ID = re.compile(r"[0-9a-f]{32}")


def identity_path() -> Path:
    override = os.environ.get("RPS_IDENTITY_FILE")
    return Path(override) if override else stats_path().with_name("identity.json")


def valid_install_id(value: object) -> bool:
    return isinstance(value, str) and _ID.fullmatch(value) is not None


def install_id(path: Path | None = None) -> str:
    """The saved ID, creating (and saving) one on first use.

    If the file can't be written the ID is simply not persisted this time.
    """
    target = path or identity_path()
    try:
        data = json.loads(target.read_text("utf-8"))
        if isinstance(data, dict) and valid_install_id(data.get("id")):
            return data["id"]
    except (OSError, ValueError):
        pass
    new = secrets.token_hex(16)
    tmp = target.with_name(target.name + ".tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps({"id": new}), "utf-8")
        os.replace(tmp, target)
    except OSError:
        pass
    return new
