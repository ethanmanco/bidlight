from dataclasses import replace
from datetime import datetime, timezone

import pytest

from bidlight.match import Matcher, find_matches, keyword_pattern

from .conftest import NOW


@pytest.mark.parametrize(
    "term, text, hit",
    [
        ("website", "Agency Website Redesign", True),
        ("website", "redesign of two websites", True),
        ("website", "see websiteaccess.gov", False),
        ("web application", "a web-application refresh", True),
        ("web-based", "a web based tool", True),
        ("Section 508", "meets SECTION  508 standards", True),
        ("UX", "UX research", True),
        ("UX", "Luxembourg", False),
        ("WCAG", "WCAG 2.2 AA", True),
    ],
)
def test_keyword_pattern(term, text, hit):
    assert bool(keyword_pattern(term).search(text)) is hit


def matcher(profile, now=NOW):
    return Matcher(profile, now)


def test_naics_match_with_description_keywords(profile, by_id):
    m = matcher(profile).evaluate(by_id("8c1636c4"))
    assert m is not None
    assert m.title_keywords == []
    assert m.description_keywords == ["website", "accessibility"]
    # 25 NAICS + 16 keywords + 5 no set-aside + 5 no place + 5 roomy deadline
    assert m.score == 56


def test_naics_only_score(profile, by_id):
    m = matcher(profile).evaluate(by_id("73f1f0e3"))
    assert m.reasons == [
        "NAICS 541511",
        "SBA set-aside",
        "no place of performance listed",
        "more than 14 days to respond",
    ]
    assert m.score == 50


def test_keyword_points_are_capped(profile, by_id):
    capped = replace(profile, scoring=replace(profile.scoring, keyword_points_max=10))
    m = matcher(capped).evaluate(by_id("b4402688"))
    assert m.description_keywords == ["Section 508", "web-based", "user experience"]
    assert m.score == 25 + 10 + 5


def test_title_keyword_matches_without_naics(profile, by_id):
    # A real 2019 notice, evaluated as of its own time.
    m = matcher(profile, datetime(2019, 4, 1, tzinfo=timezone.utc)).evaluate(by_id("3b9ad550"))
    assert m is not None
    assert m.title_keywords == ["website"]
    assert "NAICS 519130" not in m.reasons


def test_preferred_state_scores(profile, by_id):
    louisiana = replace(by_id("0a5afd71"), naics="541511")
    m = matcher(profile).evaluate(louisiana)
    assert "performed in LA" in m.reasons


@pytest.mark.parametrize(
    "prefix, reason",
    [
        ("6061b69e", "skipped: outside the US"),
        ("11e3d5a8", "skipped: deadline too soon or past"),
        ("7d87b348", "skipped: old notice with no deadline"),
        ("f63850b5", "skipped: notice type"),
        ("51629cc9", "skipped: excluded title word"),
        ("36d97c4e", "skipped: excluded title word"),
        ("0a5afd71", "skipped: no NAICS or title keyword"),
    ],
)
def test_skips(profile, by_id, prefix, reason):
    m = matcher(profile)
    assert m.evaluate(by_id(prefix)) is None
    assert m.stats[reason] == 1


def test_deadline_cutoff_is_exactly_five_days(profile, by_id):
    n = by_id("73f1f0e3")  # deadline 2026-12-01 00:00 UTC
    just_inside = datetime(2026, 11, 26, 0, 0, tzinfo=timezone.utc)
    just_outside = datetime(2026, 11, 26, 0, 1, tzinfo=timezone.utc)
    assert matcher(profile, just_inside).evaluate(n) is not None
    assert matcher(profile, just_outside).evaluate(n) is None


def test_full_fixture_run(profile, notices):
    matches, stats = find_matches(notices, profile, NOW)
    assert [m.notice.notice_id[:8] for m in matches] == [
        "8c1636c4",  # 56
        "b4402688",  # 54
        "f8200861",  # 53
        "73f1f0e3",  # 50
        "100ae619",  # 45
        "4883121a",  # 43
    ]
    assert stats["scanned"] == 59
    assert stats["opportunities matched"] == 6


def test_amendments_collapse_to_newest(profile, notices):
    matches, _ = find_matches(notices, profile, NOW)
    by_title = {m.notice.title[:10]: m for m in matches}
    pqc = by_title["Post Quantu"[:10]]
    assert pqc.versions == 8
    assert pqc.notice.notice_id.startswith("4883121a")  # posted 2026-11-12, the newest
    ptt = by_title["Pilot Trai"]
    assert ptt.versions == 2
    assert ptt.notice.notice_id.startswith("100ae619")


def test_copies_under_other_naics_do_not_hide_a_match(profile, notices):
    # The VA event was posted many times under one solicitation number (18 copies here), each
    # with a different NAICS code. The 541519 copy is not the newest row.
    no_excludes = replace(profile, exclude_title_words=())
    matches, _ = find_matches(notices, no_excludes, NOW)
    event = [m for m in matches if "Small Business Event" in m.notice.title]
    assert len(event) == 1
    assert event[0].notice.notice_id.startswith("36d97c4e")
    assert event[0].versions == 18


def test_award_after_solicitation_drops_it(profile, notices):
    # 36C10B27R0001: combined synopses on 10/07 and 10/09, award on 10/23.
    no_excludes = replace(profile, exclude_title_words=())
    early = datetime(2026, 10, 1, tzinfo=timezone.utc)
    m = Matcher(no_excludes, early)
    solicitation = next(n for n in notices if n.notice_id.startswith("146a68e9"))
    assert m.evaluate(solicitation) is not None
    matches, _ = find_matches(notices, no_excludes, early)
    assert not any(x.notice.solicitation_number == "36C10B27R0001" for x in matches)


def test_ranking_breaks_ties_by_deadline(profile, notices):
    early = datetime(2026, 10, 1, tzinfo=timezone.utc)
    matches, _ = find_matches(notices, profile, early)
    tied = [m for m in matches if m.score == 50]
    assert [m.notice.notice_id[:8] for m in tied] == ["100ae619", "73f1f0e3"]
