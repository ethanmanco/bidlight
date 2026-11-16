"""Render the daily digest as Markdown (the body of a GitHub issue)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import Profile
from .match import Match

# GitHub rejects issue bodies over 65,536 characters; leave room.
MAX_BODY_CHARS = 60_000

DISCLAIMER = (
    "> Bidlight describes public notices. It does not decide whether your business is "
    "eligible for a notice or whether to respond. Always read the official notice."
)


@dataclass
class Summary:
    text: str
    fit: str


@dataclass
class Digest:
    title: str
    body: str
    new_count: int
    amended_count: int


@dataclass
class DigestInput:
    profile: Profile
    now: datetime
    new: list[Match]
    amended: list[tuple[Match, list[str]]]
    summaries: dict[str, Summary] = field(default_factory=dict)
    stats: Counter = field(default_factory=Counter)
    source_note: str = ""
    ai_note: str = ""
    first_run: bool = False


def _when(dt: datetime | None, tz: ZoneInfo) -> str:
    if dt is None:
        return "no deadline listed"
    local = dt.astimezone(tz)
    hour = local.strftime("%I").lstrip("0") or "12"
    return f"{local:%a %b} {local.day}, {hour}:{local:%M %p} {local.tzname()}"


def _days_left(dt: datetime | None, now: datetime) -> str:
    if dt is None:
        return ""
    days = (dt - now).days
    return f" ({days} day{'s' if days != 1 else ''})"


def _set_aside(m: Match) -> str:
    n = m.notice
    if not n.set_aside_code:
        return "No set-aside"
    return _clean(n.set_aside) or n.set_aside_code


def _place(m: Match) -> str:
    n = m.notice
    parts = [p for p in (n.pop_city.title() if n.pop_city else "", n.pop_state) if p]
    return ", ".join(parts) or "not specified"


def _agency(m: Match) -> str:
    n = m.notice
    parts = [p.title() for p in (n.agency, n.sub_tier) if p]
    return ", ".join(dict.fromkeys(parts)) or "Unknown agency"


EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)


def no_dashes(text: str) -> str:
    """House style: no em or en dashes anywhere in the digest."""
    return text.replace(f" {EM_DASH} ", ", ").replace(EM_DASH, ", ").replace(EN_DASH, "-")


def _clean(text: str) -> str:
    """Keep notice text from breaking the Markdown layout."""
    return no_dashes(" ".join(text.replace("|", "/").split()))


def render_entry(i: int, m: Match, d: DigestInput, tz: ZoneInfo) -> str:
    n = m.notice
    lines = [
        f"### {i}. {_clean(n.title) or '(untitled notice)'}",
        f"**Score {m.score}** | {n.notice_type} | NAICS {n.naics or 'none listed'} | {_set_aside(m)}",
        f"**Agency:** {_agency(m)} | **Place:** {_place(m)}",
        f"**Respond by:** {_when(n.deadline, tz)}{_days_left(n.deadline, d.now)}"
        + (f" | {m.versions} versions posted" if m.versions > 1 else ""),
        f"**Why it matched:** {', '.join(m.reasons)}",
    ]
    summary = d.summaries.get(n.notice_id)
    if summary:
        lines.append("")
        lines.append(f"{summary.text}")
        lines.append("")
        lines.append(f"**Fit note:** {summary.fit}")
    sol = f" | Sol# {_clean(n.solicitation_number)}" if n.solicitation_number else ""
    lines.append("")
    lines.append(f"[Official notice on SAM.gov]({n.url}){sol}")
    return "\n".join(lines)


def render_line(m: Match, tz: ZoneInfo) -> str:
    n = m.notice
    due = _when(n.deadline, tz)
    return f"- [{_clean(n.title)}]({n.url}) | score {m.score} | {n.notice_type} | {_set_aside(m)} | due {due}"


def render(d: DigestInput) -> Digest | None:
    """Return the digest, or None when there is nothing new or amended."""
    if not d.new and not d.amended:
        return None
    tz = ZoneInfo(d.profile.timezone)
    local_date = d.now.astimezone(tz)
    top = d.new[: d.profile.top_n]
    rest = d.new[d.profile.top_n :]

    count = len(d.new)
    parts_title = []
    if count:
        parts_title.append(f"{count} new match{'es' if count != 1 else ''}")
    if d.amended:
        parts_title.append(f"{len(d.amended)} amended")
    title = f"Bidlight: {', '.join(parts_title)}, {local_date:%a %b} {local_date.day}, {local_date.year}"

    out = [
        f"# {', '.join(parts_title).capitalize()} for {d.profile.business_name}",
        "",
        d.source_note,
        "",
        DISCLAIMER,
    ]
    if d.first_run:
        out += [
            "",
            "_First run: every current match counts as new. From tomorrow on, digests show only "
            "notices that are new or changed since the last digest._",
        ]
    if d.ai_note:
        out += ["", f"_{d.ai_note}_"]
    for i, m in enumerate(top, 1):
        out += ["", "---", "", render_entry(i, m, d, tz)]

    tail: list[str] = []
    if rest:
        tail += ["", "---", "", f"### Also matched ({len(rest)}, lower scores)", ""]
        tail += [render_line(m, tz) for m in rest]
    if d.amended:
        tail += ["", "---", "", "### Amended since we sent them", ""]
        for m, changed in d.amended:
            tail.append(f"{render_line(m, tz)} | **{', '.join(changed)}**")
    if d.stats:
        scanned = d.stats.get("scanned", 0)
        tail += [
            "",
            "---",
            "",
            f"<details><summary>Run details: {scanned:,} notices scanned</summary>",
            "",
            *[f"- {k}: {v:,}" for k, v in d.stats.items() if k != "scanned"],
            "",
            "</details>",
        ]
    tail += ["", "_Sent by [Bidlight](https://github.com/ethanmanco/bidlight). Edit `profile.yaml` to change what matches._"]

    body = "\n".join(out + tail)
    if len(body) > MAX_BODY_CHARS:
        body = body[: MAX_BODY_CHARS - 200].rsplit("\n", 1)[0] + "\n\n_Digest cut short to fit GitHub's size limit._"
    return Digest(title=title, body=body, new_count=count, amended_count=len(d.amended))
