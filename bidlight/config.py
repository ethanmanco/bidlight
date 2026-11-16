"""Load and validate profile.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


class ConfigError(ValueError):
    """The profile file is missing a field or has a bad value."""


@dataclass(frozen=True)
class Scoring:
    naics_match: int = 25
    keyword_in_title: int = 25
    keyword_in_description: int = 8
    keyword_points_max: int = 40
    preferred_set_aside: int = 15
    no_set_aside: int = 5
    preferred_state: int = 10
    no_place_listed: int = 5
    roomy_deadline_days: int = 14
    roomy_deadline: int = 5


@dataclass(frozen=True)
class AISettings:
    enabled: bool = True
    model: str = "claude-haiku-5-5"
    input_price_per_mtok: float = 0.10
    output_price_per_mtok: float = 0.50
    max_output_tokens: int = 500
    description_chars: int = 6000
    daily_cost_cap_usd: float = 0.05


@dataclass(frozen=True)
class SamApiSettings:
    enabled: bool = True
    max_requests_per_run: int = 5


@dataclass(frozen=True)
class Profile:
    business_name: str
    naics: tuple[str, ...]
    keywords: tuple[str, ...]
    notice_types: tuple[str, ...]
    exclude_title_words: tuple[str, ...] = ()
    preferred_set_asides: tuple[str, ...] = ()
    preferred_states: tuple[str, ...] = ()
    min_days_to_deadline: int = 5
    max_age_days_without_deadline: int = 60
    us_only: bool = True
    top_n: int = 10
    timezone: str = "America/Chicago"
    scoring: Scoring = field(default_factory=Scoring)
    ai: AISettings = field(default_factory=AISettings)
    sam_api: SamApiSettings = field(default_factory=SamApiSettings)


def _strings(raw: dict, key: str, required: bool = False) -> tuple[str, ...]:
    value = raw.get(key)
    if value is None:
        if required:
            raise ConfigError(f"profile is missing '{key}'")
        return ()
    if not isinstance(value, list) or not all(isinstance(v, (str, int)) for v in value):
        raise ConfigError(f"'{key}' must be a list of strings")
    return tuple(str(v).strip() for v in value if str(v).strip())


def _section(raw: dict, key: str, cls):
    value = raw.get(key) or {}
    if not isinstance(value, dict):
        raise ConfigError(f"'{key}' must be a mapping")
    known = set(cls.__dataclass_fields__)
    unknown = set(value) - known
    if unknown:
        raise ConfigError(f"unknown setting(s) in '{key}': {', '.join(sorted(unknown))}")
    return cls(**value)


def parse_profile(raw: dict) -> Profile:
    if not isinstance(raw, dict):
        raise ConfigError("profile must be a YAML mapping")
    naics = _strings(raw, "naics")
    keywords = _strings(raw, "keywords")
    if not naics and not keywords:
        raise ConfigError("profile needs at least one NAICS code or keyword")
    for code in naics:
        if not code.isdigit() or not 2 <= len(code) <= 6:
            raise ConfigError(f"NAICS code '{code}' should be 2 to 6 digits (quote it in YAML)")
    profile = Profile(
        business_name=str(raw.get("business_name", "")).strip() or "your business",
        naics=naics,
        keywords=keywords,
        notice_types=_strings(raw, "notice_types", required=True),
        exclude_title_words=_strings(raw, "exclude_title_words"),
        preferred_set_asides=tuple(s.upper() for s in _strings(raw, "preferred_set_asides")),
        preferred_states=tuple(s.upper() for s in _strings(raw, "preferred_states")),
        min_days_to_deadline=int(raw.get("min_days_to_deadline", 5)),
        max_age_days_without_deadline=int(raw.get("max_age_days_without_deadline", 60)),
        us_only=bool(raw.get("us_only", True)),
        top_n=int(raw.get("top_n", 10)),
        timezone=str(raw.get("timezone", "America/Chicago")),
        scoring=_section(raw, "scoring", Scoring),
        ai=_section(raw, "ai", AISettings),
        sam_api=_section(raw, "sam_api", SamApiSettings),
    )
    if profile.top_n < 1:
        raise ConfigError("top_n must be at least 1")
    if profile.ai.daily_cost_cap_usd < 0:
        raise ConfigError("ai.daily_cost_cap_usd cannot be negative")
    return profile


def load_profile(path: str | Path) -> Profile:
    with open(path, encoding="utf-8") as f:
        return parse_profile(yaml.safe_load(f))
