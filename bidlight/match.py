"""Decide which notices fit the profile, and score them with plain rules."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .config import Profile
from .notice import Notice

US_COUNTRY_CODES = {"", "USA", "US"}


def keyword_pattern(term: str) -> re.Pattern[str]:
    """Whole-word, case-insensitive; spaces and hyphens interchangeable; optional plural."""
    words = re.split(r"[\s-]+", term.strip())
    body = r"[\s\-]+".join(re.escape(w) for w in words if w)
    return re.compile(rf"(?<![A-Za-z0-9]){body}(?:s|es)?(?![A-Za-z0-9])", re.IGNORECASE)


@dataclass
class Match:
    notice: Notice
    score: int
    reasons: list[str]
    title_keywords: list[str]
    description_keywords: list[str]
    versions: int = 1


@dataclass
class Matcher:
    profile: Profile
    now: datetime
    stats: Counter = field(default_factory=Counter)

    def __post_init__(self) -> None:
        self._keywords = [(k, keyword_pattern(k)) for k in self.profile.keywords]
        self._excludes = [keyword_pattern(w) for w in self.profile.exclude_title_words]
        self._types = {t.lower() for t in self.profile.notice_types}
        self._naics = set(self.profile.naics)
        self._earliest_deadline = self.now + timedelta(days=self.profile.min_days_to_deadline)
        self._oldest_undated = self.now - timedelta(days=self.profile.max_age_days_without_deadline)

    def _naics_hit(self, code: str) -> bool:
        # Profile codes may be prefixes (e.g. "5415" covers 541511 to 541519).
        return any(code.startswith(c) for c in self._naics) if code else False

    def evaluate(self, notice: Notice) -> Match | None:
        """Return a Match if the notice passes every filter, else None."""
        stats = self.stats
        stats["scanned"] += 1
        if notice.notice_type.lower() not in self._types:
            stats["skipped: notice type"] += 1
            return None
        if self.profile.us_only and notice.pop_country not in US_COUNTRY_CODES:
            stats["skipped: outside the US"] += 1
            return None
        if notice.deadline is not None:
            if notice.deadline < self._earliest_deadline:
                stats["skipped: deadline too soon or past"] += 1
                return None
        elif notice.posted is None or notice.posted < self._oldest_undated:
            stats["skipped: old notice with no deadline"] += 1
            return None

        naics_hit = self._naics_hit(notice.naics)
        title_kw = [k for k, rx in self._keywords if rx.search(notice.title)]
        desc_kw = [
            k for k, rx in self._keywords if k not in title_kw and rx.search(notice.description)
        ]
        if not naics_hit and not title_kw:
            stats["skipped: no NAICS or title keyword"] += 1
            return None
        if not title_kw and len(desc_kw) < 2 and any(rx.search(notice.title) for rx in self._excludes):
            stats["skipped: excluded title word"] += 1
            return None

        score, reasons = self.score(notice, naics_hit, title_kw, desc_kw)
        stats["matched"] += 1
        return Match(notice, score, reasons, title_kw, desc_kw)

    def score(
        self, notice: Notice, naics_hit: bool, title_kw: list[str], desc_kw: list[str]
    ) -> tuple[int, list[str]]:
        s = self.profile.scoring
        points = 0
        reasons: list[str] = []
        if naics_hit:
            points += s.naics_match
            reasons.append(f"NAICS {notice.naics}")
        kw_points = s.keyword_in_title * len(title_kw) + s.keyword_in_description * len(desc_kw)
        points += min(s.keyword_points_max, kw_points)
        if title_kw:
            reasons.append("title mentions " + ", ".join(f'"{k}"' for k in title_kw))
        if desc_kw:
            reasons.append("description mentions " + ", ".join(f'"{k}"' for k in desc_kw))
        code = notice.set_aside_code
        if code and code in self.profile.preferred_set_asides:
            points += s.preferred_set_aside
            reasons.append(f"{code} set-aside")
        elif not code:
            points += s.no_set_aside
            reasons.append("no set-aside")
        if notice.pop_state and notice.pop_state in self.profile.preferred_states:
            points += s.preferred_state
            reasons.append(f"performed in {notice.pop_state}")
        elif not notice.pop_state and not notice.pop_city:
            points += s.no_place_listed
            reasons.append("no place of performance listed")
        roomy = self.now + timedelta(days=s.roomy_deadline_days)
        if notice.deadline is None or notice.deadline > roomy:
            points += s.roomy_deadline
            reasons.append(
                "no deadline listed" if notice.deadline is None
                else f"more than {s.roomy_deadline_days} days to respond"
            )
        return points, reasons


# Rows that can supersede a matching notice with the same solicitation number.
# If the newest row is an award or a cancellation, the opportunity is dropped.
SUPERSEDING_TYPES = {"award notice", "modification/amendment/cancel"}


def _version_key(notice: Notice) -> tuple[float, str]:
    return (notice.posted.timestamp() if notice.posted else 0.0, notice.notice_id)


@dataclass
class VersionTracker:
    """Per opportunity: how many rows, and the newest award or cancellation.

    Stores two small values per solicitation number, so memory stays small.
    """

    counts: Counter = field(default_factory=Counter)
    closed: dict[str, tuple[float, str]] = field(default_factory=dict)

    def see(self, notice: Notice) -> None:
        key = notice.group_key
        self.counts[key] += 1
        if notice.notice_type.lower() in SUPERSEDING_TYPES:
            version = _version_key(notice)
            if version > self.closed.get(key, (-1.0, "")):
                self.closed[key] = version

    def closed_after(self, notice: Notice) -> bool:
        closed = self.closed.get(notice.group_key)
        return closed is not None and closed > _version_key(notice)


def newest_versions(matches: Iterable[Match], tracker: VersionTracker) -> list[Match]:
    """One match per opportunity: its newest matching row.

    Agencies post amendments as new rows, and sometimes post copies of one
    notice under several NAICS codes, all with the same solicitation number.
    The newest row that matched the profile is kept. The opportunity is
    dropped if an award or cancellation was posted after that row.
    """
    best: dict[str, Match] = {}
    for m in matches:
        key = m.notice.group_key
        if key not in best or _version_key(m.notice) > _version_key(best[key].notice):
            best[key] = m
    result = []
    for key, m in best.items():
        if tracker.closed_after(m.notice):
            continue
        m.versions = tracker.counts[key]
        result.append(m)
    return rank(result)


def rank(matches: list[Match]) -> list[Match]:
    """Highest score first; ties go to the sooner deadline, then the newer post."""
    far = float("inf")
    return sorted(
        matches,
        key=lambda m: (
            -m.score,
            m.notice.deadline.timestamp() if m.notice.deadline else far,
            -(m.notice.posted.timestamp() if m.notice.posted else 0),
            m.notice.notice_id,
        ),
    )


def find_matches(notices: Iterable[Notice], profile: Profile, now: datetime) -> tuple[list[Match], Counter]:
    """Stream notices once; return ranked matches (newest version of each) and counts."""
    matcher = Matcher(profile, now)
    tracker = VersionTracker()
    raw: list[Match] = []
    for notice in notices:
        tracker.see(notice)
        if m := matcher.evaluate(notice):
            raw.append(m)
    grouped = newest_versions(raw, tracker)
    stats = matcher.stats
    stats["merged: older versions or awarded"] = len(raw) - len(grouped)
    stats["opportunities matched"] = len(grouped)
    return grouped, stats
