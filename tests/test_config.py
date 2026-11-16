import pytest
import yaml

from bidlight.config import ConfigError, parse_profile

from .conftest import ROOT


def base():
    return yaml.safe_load((ROOT / "profile.yaml").read_text(encoding="utf-8"))


def test_shipped_profile_loads(profile):
    assert profile.naics == ("541511", "541512", "541519")
    assert profile.min_days_to_deadline == 5
    assert profile.top_n == 10
    assert profile.ai.model == "claude-haiku-5-5"


def test_unquoted_naics_still_works():
    raw = base()
    raw["naics"] = [541511]
    assert parse_profile(raw).naics == ("541511",)


@pytest.mark.parametrize(
    "change, message",
    [
        ({"naics": [], "keywords": []}, "at least one"),
        ({"naics": ["54-15"]}, "2 to 6 digits"),
        ({"notice_types": None}, "notice_types"),
        ({"top_n": 0}, "top_n"),
        ({"scoring": {"bogus": 1}}, "unknown setting"),
        ({"ai": {"daily_cost_cap_usd": -1}}, "negative"),
    ],
)
def test_bad_profiles_are_rejected(change, message):
    raw = base()
    raw.update(change)
    with pytest.raises(ConfigError, match=message):
        parse_profile(raw)
