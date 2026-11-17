"""The player's profile: experience, rank, achievements, Gauntlet records, rivals.

Statistics (``stats.py``) count what happened; the profile is what it added up
to. It lives in ``profile.json`` next to the statistics file (override with
RPS_PROFILE_FILE). Like the other saved files, reading is forgiving and saving
never raises.

The ``record_*`` functions are the only way anything gets in: each takes what
just happened (a classic game, a Gauntlet run, an online game), updates the
profile and returns the ``Gains`` to show the player.
"""
from __future__ import annotations

import datetime
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Sequence

from .engine import Outcome, Score
from .identity import valid_install_id
from .stats import stats_path

if TYPE_CHECKING:                                   # the Gauntlet imports nothing from here
    from .gauntlet.run import Run
    from .insight import Insight

RANKS = (
    (0, "Novice"),
    (100, "Apprentice"),
    (300, "Scrapper"),
    (700, "Duelist"),
    (1500, "Tactician"),
    (3000, "Mind Reader"),
    (6000, "Master"),
    (12000, "Grandmaster"),
    (25000, "Legend"),
)
DIFFICULTY_XP = {"easy": 1, "normal": 2, "hard": 3, "oracle": 5}
MAX_RIVALS = 50
BESTIARY_SIZE = 18                  # every foe in the Gauntlet, gatekeepers included


@dataclass(frozen=True)
class Achievement:
    key: str
    name: str
    text: str


ACHIEVEMENTS = (
    Achievement("first_win", "First Blood", "Win a round."),
    Achievement("streak5", "On a Roll", "Win 5 rounds in a row."),
    Achievement("streak10", "Unstoppable", "Win 10 rounds in a row."),
    Achievement("hundred", "Centurion", "Play 100 rounds, in any mode."),
    Achievement("hard", "Pattern Breaker", "Out-win Hard over a game of 10 rounds or more."),
    Achievement("oracle", "Unreadable", "Out-win the Oracle over a game of 15 rounds or more."),
    Achievement("poker_face", "Poker Face",
                "Be rated Unreadable by the mind reader over 15+ rounds."),
    Achievement("gauntlet_first", "Into the Gauntlet", "Win a fight in the Gauntlet."),
    Achievement("warden", "Gatecrasher", "Defeat the Warden."),
    Achievement("summit", "Top of the Tower", "Defeat the Oracle and conquer the Gauntlet."),
    Achievement("flawless", "Untouchable", "Win a Gauntlet fight without taking damage."),
    Achievement("thread", "By a Thread", "Win a Gauntlet fight with 1 HP left."),
    Achievement("collector", "Collector", "Hold 6 relics in a single run."),
    Achievement("bare_hands", "Bare Hands",
                "Clear the first five floors without using a technique."),
    Achievement("bestiary", "Know Thy Enemy", "Defeat every foe in the Gauntlet at least once."),
    Achievement("daily", "Daily Ritual", "See a Daily Run through to its end."),
    Achievement("friend", "Friendly Fire", "Finish an online game against another player."),
)
_BY_KEY = {a.key: a for a in ACHIEVEMENTS}


@dataclass
class Rival:
    """Head-to-head results against one other player (by their install ID)."""

    name: str = ""
    games_won: int = 0
    games_lost: int = 0
    games_tied: int = 0
    rounds_won: int = 0
    rounds_lost: int = 0
    rounds_drawn: int = 0
    last_played: str = ""

    @property
    def games(self) -> int:
        return self.games_won + self.games_lost + self.games_tied


@dataclass
class Profile:
    xp: int = 0
    rounds: int = 0                                   # every round played, in any mode
    achievements: dict[str, str] = field(default_factory=dict)    # key -> date unlocked
    runs: int = 0
    victories: int = 0
    best_floors: int = 0
    best_score: int = 0
    foes_beaten: list[str] = field(default_factory=list)          # distinct foe keys
    daily_date: str = ""
    daily_score: int = 0
    rivals: dict[str, Rival] = field(default_factory=dict)

    # ------------------------------------------------------------- rank

    @property
    def rank(self) -> str:
        return [name for need, name in RANKS if self.xp >= need][-1]

    @property
    def next_rank(self) -> Optional[tuple[str, int]]:
        """(the next rank, XP still needed), or None at the top."""
        for need, name in RANKS:
            if self.xp < need:
                return name, need - self.xp
        return None

    def rank_line(self) -> str:
        nxt = self.next_rank
        tail = f"{nxt[1]} XP to {nxt[0]}" if nxt else "the highest rank"
        return f"Rank: {self.rank} ({self.xp} XP, {tail})"

    def unlock(self, key: str) -> Optional[Achievement]:
        """Unlock an achievement. Returns it the first time, None if already held."""
        if key in self.achievements or key not in _BY_KEY:
            return None
        self.achievements[key] = datetime.date.today().isoformat()
        return _BY_KEY[key]

    # ------------------------------------------------------------- storage

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: object) -> "Profile":
        if not isinstance(data, dict):
            return cls()

        def count(key: str, source: dict = data) -> int:
            value = source.get(key)
            ok = isinstance(value, int) and not isinstance(value, bool) and value >= 0
            return value if ok else 0

        def text(key: str, source: dict = data) -> str:
            value = source.get(key)
            return value[:40] if isinstance(value, str) else ""

        raw = data.get("achievements")
        achievements = ({k: v for k, v in raw.items() if k in _BY_KEY and isinstance(v, str)}
                        if isinstance(raw, dict) else {})
        raw = data.get("foes_beaten")
        foes = ([k for k in dict.fromkeys(raw) if isinstance(k, str)][:BESTIARY_SIZE]
                if isinstance(raw, list) else [])
        raw = data.get("rivals")
        rivals = {}
        if isinstance(raw, dict):
            for rid, entry in raw.items():
                if valid_install_id(rid) and isinstance(entry, dict):
                    rivals[rid] = Rival(
                        name=text("name", entry),
                        games_won=count("games_won", entry), games_lost=count("games_lost", entry),
                        games_tied=count("games_tied", entry),
                        rounds_won=count("rounds_won", entry),
                        rounds_lost=count("rounds_lost", entry),
                        rounds_drawn=count("rounds_drawn", entry),
                        last_played=text("last_played", entry),
                    )
        return cls(
            xp=count("xp"), rounds=count("rounds"), achievements=achievements,
            runs=count("runs"), victories=count("victories"),
            best_floors=count("best_floors"), best_score=count("best_score"),
            foes_beaten=foes, daily_date=text("daily_date"), daily_score=count("daily_score"),
            rivals=rivals,
        )


@dataclass
class Gains:
    """What one game added to the profile, ready to show."""

    xp: int = 0
    unlocked: list[Achievement] = field(default_factory=list)
    promoted_to: str = ""                   # the new rank, if the XP crossed a threshold
    new_best: bool = False                  # a Gauntlet high score
    rank_line: str = ""

    def lines(self) -> list[str]:
        out = []
        if self.new_best:
            out.append("New best score!")
        if self.xp:
            out.append(f"+{self.xp} XP. {self.rank_line}")
        if self.promoted_to:
            out.append(f"Promoted to {self.promoted_to}!")
        out += [f"Achievement unlocked: {a.name} - {a.text}" for a in self.unlocked]
        return out


def _award(profile: Profile, xp: int, keys: Sequence[str], new_best: bool = False) -> Gains:
    before = profile.rank
    profile.xp += xp
    unlocked = [a for a in (profile.unlock(key) for key in keys) if a is not None]
    return Gains(xp=xp, unlocked=unlocked,
                 promoted_to=profile.rank if profile.rank != before else "",
                 new_best=new_best, rank_line=profile.rank_line())


def _round_keys(profile: Profile, session: Score) -> list[str]:
    """Achievements any mode can earn from a session's rounds."""
    profile.rounds += session.rounds
    keys = []
    if session.wins:
        keys.append("first_win")
    if session.best_streak >= 5:
        keys.append("streak5")
    if session.best_streak >= 10:
        keys.append("streak10")
    if profile.rounds >= 100:
        keys.append("hundred")
    return keys


# ---------------------------------------------------------------- recording

def record_classic(profile: Profile, *, difficulty: str, session: Score,
                   insight: Optional["Insight"] = None) -> Gains:
    """A finished single-player session against the computer."""
    keys = _round_keys(profile, session)
    ahead = session.wins > session.losses
    if difficulty == "hard" and session.rounds >= 10 and ahead:
        keys.append("hard")
    if difficulty == "oracle" and session.rounds >= 15 and ahead:
        keys.append("oracle")
    if insight is not None and insight.rounds >= 15 and insight.verdict == "Unreadable":
        keys.append("poker_face")
    weight = DIFFICULTY_XP.get(difficulty, 2)
    return _award(profile, 2 * weight * session.wins + session.draws, keys)


def record_run(profile: Profile, run: "Run") -> Gains:
    """A Gauntlet run that has ended (won, lost or abandoned)."""
    tally = run.tally
    keys = _round_keys(profile, Score(wins=tally.wins, losses=tally.losses, draws=tally.draws,
                                      best_streak=tally.best_streak))
    profile.runs += 1
    profile.victories += run.victory
    profile.best_floors = max(profile.best_floors, run.floors_cleared)
    new_best = run.score > profile.best_score
    profile.best_score = max(profile.best_score, run.score)
    for key in run.beaten:
        if key not in profile.foes_beaten:
            profile.foes_beaten.append(key)
    if run.daily and not run.abandoned:
        if run.daily != profile.daily_date:
            profile.daily_date, profile.daily_score = run.daily, 0
        profile.daily_score = max(profile.daily_score, run.score)
        keys.append("daily")

    if run.beaten:
        keys.append("gauntlet_first")
    if "warden" in run.beaten:
        keys.append("warden")
    if run.victory:
        keys.append("summit")
    if tally.flawless:
        keys.append("flawless")
    if tally.lowest_hp_win == 1:
        keys.append("thread")
    if len(run.hero.relics) >= 6:
        keys.append("collector")
    if run.bare_hands:
        keys.append("bare_hands")
    if len(profile.foes_beaten) >= BESTIARY_SIZE:
        keys.append("bestiary")
    return _award(profile, run.score // 8, keys, new_best=new_best and run.score > 0)


def record_online(profile: Profile, *, opponent_id: str, opponent_name: str, session: Score,
                  outcome: Optional[Outcome]) -> Gains:
    """An online game. ``outcome`` is WIN/LOSS/DRAW for the game, or None if it was
    cut short without a result."""
    keys = _round_keys(profile, session)
    if valid_install_id(opponent_id):
        rival = profile.rivals.pop(opponent_id, None) or Rival()
        rival.name = opponent_name[:40]
        rival.rounds_won += session.wins
        rival.rounds_lost += session.losses
        rival.rounds_drawn += session.draws
        rival.games_won += outcome is Outcome.WIN
        rival.games_lost += outcome is Outcome.LOSS
        rival.games_tied += outcome is Outcome.DRAW
        rival.last_played = datetime.date.today().isoformat()
        profile.rivals[opponent_id] = rival             # most recent last
        while len(profile.rivals) > MAX_RIVALS:
            profile.rivals.pop(next(iter(profile.rivals)))
    if outcome is not None:
        keys.append("friend")
    xp = 6 * session.wins + 2 * session.draws + (25 if outcome is Outcome.WIN else 0)
    return _award(profile, xp, keys)


# ---------------------------------------------------------------- files

def profile_path() -> Path:
    override = os.environ.get("RPS_PROFILE_FILE")
    return Path(override) if override else stats_path().with_name("profile.json")


def load(path: Path | None = None) -> Profile:
    try:
        return Profile.from_dict(json.loads((path or profile_path()).read_text("utf-8")))
    except (OSError, ValueError):
        return Profile()


def save(profile: Profile, path: Path | None = None) -> bool:
    target = path or profile_path()
    tmp = target.with_name(target.name + ".tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(profile.to_dict(), indent=2), "utf-8")
        os.replace(tmp, target)
        return True
    except OSError:
        return False


def reset(path: Path | None = None) -> bool:
    try:
        (path or profile_path()).unlink()
    except FileNotFoundError:
        pass
    except OSError:
        return False
    return True
