"""Remember which opportunities were already sent, and spot amendments.

state/sent.json is committed back to the repo by the daily workflow, so the
history survives between runs and anyone can see what was sent and when.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .match import Match

STATE_VERSION = 1
KEEP_AFTER_DEADLINE = timedelta(days=30)
KEEP_UNDATED = timedelta(days=120)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


@dataclass
class Sorted:
    new: list[Match]
    amended: list[tuple[Match, list[str]]]
    unchanged: int


class SentLog:
    def __init__(self, entries: dict[str, dict] | None = None) -> None:
        self.entries: dict[str, dict] = entries or {}

    @property
    def is_first_run(self) -> bool:
        return not self.entries

    @classmethod
    def load(cls, path: str | Path) -> "SentLog":
        path = Path(path)
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
        if data and data.get("version") != STATE_VERSION:
            raise ValueError(f"{path} has unknown version {data.get('version')}")
        return cls(data.get("sent", {}))

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"version": STATE_VERSION, "sent": dict(sorted(self.entries.items()))}
        path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    def changes(self, match: Match) -> list[str]:
        """What changed since this opportunity was sent ([] if nothing)."""
        old = self.entries[match.notice.group_key]
        n = match.notice
        changed = []
        if old.get("notice_id") != n.notice_id:
            changed.append("new version posted")
        if old.get("deadline") != _iso(n.deadline):
            changed.append("deadline changed")
        if old.get("title") != n.title:
            changed.append("title changed")
        if old.get("set_aside") != n.set_aside_code:
            changed.append("set-aside changed")
        return changed

    def sort(self, matches: list[Match]) -> Sorted:
        new, amended, unchanged = [], [], 0
        for m in matches:
            if m.notice.group_key not in self.entries:
                new.append(m)
            elif changed := self.changes(m):
                amended.append((m, changed))
            else:
                unchanged += 1
        return Sorted(new, amended, unchanged)

    def record(self, match: Match, sent_on: datetime) -> None:
        n = match.notice
        previous = self.entries.get(n.group_key, {})
        self.entries[n.group_key] = {
            "notice_id": n.notice_id,
            "title": n.title,
            "deadline": _iso(n.deadline),
            "set_aside": n.set_aside_code,
            "first_sent": previous.get("first_sent", sent_on.date().isoformat()),
            "last_sent": sent_on.date().isoformat(),
        }

    def prune(self, now: datetime) -> int:
        """Forget opportunities well past their deadline. Returns how many."""
        drop = []
        for key, entry in self.entries.items():
            deadline = entry.get("deadline")
            if deadline:
                if datetime.fromisoformat(deadline) + KEEP_AFTER_DEADLINE < now:
                    drop.append(key)
            else:
                last = datetime.fromisoformat(entry["last_sent"]).replace(tzinfo=now.tzinfo)
                if last + KEEP_UNDATED < now:
                    drop.append(key)
        for key in drop:
            del self.entries[key]
        return len(drop)
