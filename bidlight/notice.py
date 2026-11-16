"""One contract notice, normalized from either the CSV extract or the API."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

# SAM.gov deadlines without a time zone (date only, or date and time) are
# read as US Eastern, the federal default.
EASTERN = ZoneInfo("America/New_York")

PUBLIC_NOTICE_URL = "https://sam.gov/opp/{notice_id}/view"


@dataclass
class Notice:
    notice_id: str
    title: str
    solicitation_number: str
    agency: str
    sub_tier: str
    office: str
    posted: datetime | None
    notice_type: str
    set_aside_code: str
    set_aside: str
    deadline: datetime | None
    naics: str
    pop_city: str
    pop_state: str
    pop_country: str
    description: str
    source: str = "extract"

    @property
    def url(self) -> str:
        return PUBLIC_NOTICE_URL.format(notice_id=self.notice_id)

    @property
    def group_key(self) -> str:
        """Stable key for one opportunity across its amendments.

        Each amendment is a new row with a new NoticeId, but keeps the
        solicitation number. Notices without one are keyed by their own id.
        """
        sol = re.sub(r"\s+", "", self.solicitation_number).upper()
        if not sol:
            return f"id:{self.notice_id}"
        return f"sol:{sol}|{self.agency.strip().upper()}"


def normalize_set_aside(code: str) -> str:
    """'SBA', '["SBA"]', '[""]', 'NONE', '' -> 'SBA' or ''."""
    cleaned = re.sub(r'[\[\]"\s]', "", code or "").upper()
    return "" if cleaned in ("", "NONE") else cleaned


def parse_deadline(value: str) -> datetime | None:
    """Parse a SAM.gov response deadline into an aware UTC datetime.

    Seen formats: '2027-01-15T15:00:00-05:00', '2026-11-27',
    '2026-12-04T17:00:00', and ''. A date alone means the end of that day.
    """
    value = (value or "").strip()
    if not value:
        return None
    try:
        if len(value) == 10:
            day = date.fromisoformat(value)
            parsed = datetime.combine(day, time(23, 59), tzinfo=EASTERN)
        else:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=EASTERN)
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc)


def parse_posted(value: str) -> datetime | None:
    """Parse '2026-11-15 02:49:58' (or ISO with offset) into UTC."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=EASTERN)
    return parsed.astimezone(timezone.utc)
