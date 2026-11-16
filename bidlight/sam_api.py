"""Optional: same-day notices from the SAM.gov Get Opportunities Public API.

The nightly extract can miss notices posted after it was built. With a
SAM_API_KEY secret, Bidlight asks the API for notices posted since yesterday
under each profile NAICS code.

Limits (open.gsa.gov): a personal key for a non-federal user with no SAM.gov
role gets 10 requests a day; with a role, 1,000. Bidlight stops at
sam_api.max_requests_per_run and stops at once on HTTP 429.

The API returns a link to each description rather than the text (fetching
it costs another request), so API notices are matched on title, NAICS, and
the other fields only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

import requests

from .notice import Notice, normalize_set_aside, parse_deadline, parse_posted

log = logging.getLogger("bidlight")

API_URL = "https://api.sam.gov/opportunities/v2/search"
PAGE_LIMIT = 1000


@dataclass
class ApiResult:
    notices: list[Notice]
    requests_made: int
    note: str = ""


def _first(record: dict, *keys: str, default=""):
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return default


def _nested(record: dict, *path: str) -> str:
    value = record
    for key in path:
        if not isinstance(value, dict):
            return ""
        value = value.get(key)
    return value if isinstance(value, str) else ""


def record_to_notice(record: dict) -> Notice:
    path = _first(record, "fullParentPathName")
    parts = [p.strip() for p in path.split(".")] if path else []
    agency = parts[0] if parts else _first(record, "department")
    sub_tier = parts[1] if len(parts) > 1 else _first(record, "subtier", "subTier")
    office = parts[-1] if len(parts) > 2 else _first(record, "office")
    pop = record.get("placeOfPerformance") or {}
    return Notice(
        notice_id=str(_first(record, "noticeId")).strip(),
        title=str(_first(record, "title")).strip(),
        solicitation_number=str(_first(record, "solicitationNumber")).strip(),
        agency=agency,
        sub_tier=sub_tier,
        office=office,
        posted=parse_posted(str(_first(record, "postedDate"))),
        notice_type=str(_first(record, "type")).strip(),
        set_aside_code=normalize_set_aside(str(_first(record, "typeOfSetAside", "setAsideCode"))),
        set_aside=str(_first(record, "typeOfSetAsideDescription", "setAside")).strip(),
        # The docs spell it "reponseDeadLine"; live responses use "responseDeadLine".
        deadline=parse_deadline(str(_first(record, "responseDeadLine", "reponseDeadLine"))),
        naics=str(_first(record, "naicsCode")).strip(),
        pop_city=_nested(pop, "city", "name"),
        pop_state=_nested(pop, "state", "code").upper(),
        pop_country=_nested(pop, "country", "code").upper(),
        description="",
        source="api",
    )


def fetch_recent(
    api_key: str,
    naics_codes: tuple[str, ...],
    now: datetime,
    max_requests: int,
    session: requests.Session | None = None,
) -> ApiResult:
    session = session or requests.Session()
    posted_from = (now - timedelta(days=1)).strftime("%m/%d/%Y")
    posted_to = now.strftime("%m/%d/%Y")
    notices: list[Notice] = []
    made = 0
    for code in naics_codes:
        offset = 0
        while True:
            if made >= max_requests:
                return ApiResult(notices, made, f"SAM.gov API: stopped at the {max_requests}-request limit.")
            params = {
                "api_key": api_key,
                "postedFrom": posted_from,
                "postedTo": posted_to,
                "ncode": code,
                "limit": PAGE_LIMIT,
                "offset": offset,
            }
            try:
                response = session.get(API_URL, params=params, timeout=60)
            except requests.RequestException as exc:
                return ApiResult(notices, made, f"SAM.gov API unreachable ({type(exc).__name__}); used the extract only.")
            made += 1
            if response.status_code == 429:
                return ApiResult(notices, made, "SAM.gov API daily limit reached; used the extract only.")
            if response.status_code == 404:
                break  # documented as "no data found"
            if response.status_code != 200:
                return ApiResult(notices, made, f"SAM.gov API returned HTTP {response.status_code}; used the extract only.")
            data = response.json()
            page = data.get("opportunitiesData") or []
            notices.extend(record_to_notice(r) for r in page if r.get("noticeId"))
            total = int(data.get("totalRecords") or 0)
            offset += 1
            if offset * PAGE_LIMIT >= total or not page:
                break
    return ApiResult(notices, made, f"SAM.gov API: {len(notices)} recent notices in {made} request(s).")
