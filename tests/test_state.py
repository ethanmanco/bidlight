import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from bidlight.match import find_matches
from bidlight.state import SentLog

from .conftest import NOW


@pytest.fixture
def matches(profile, notices):
    return find_matches(notices, profile, NOW)[0]


def test_first_run_everything_is_new(matches):
    log = SentLog()
    assert log.is_first_run
    sorted_ = log.sort(matches)
    assert len(sorted_.new) == 6
    assert sorted_.amended == []


def test_sent_notices_do_not_repeat(matches):
    log = SentLog()
    for m in matches:
        log.record(m, NOW)
    sorted_ = log.sort(matches)
    assert sorted_.new == []
    assert sorted_.amended == []
    assert sorted_.unchanged == 6


def test_new_version_is_flagged_as_amended(profile, notices):
    # Record the PTT notice as it looked before its second version was posted.
    before = [n for n in notices if not n.notice_id.startswith("100ae619")]
    log = SentLog()
    for m in find_matches(before, profile, NOW)[0]:
        log.record(m, NOW)
    sorted_ = log.sort(find_matches(notices, profile, NOW)[0])
    assert sorted_.new == []
    assert len(sorted_.amended) == 1
    m, changed = sorted_.amended[0]
    assert m.notice.notice_id.startswith("100ae619")
    assert changed == ["new version posted"]


def test_deadline_change_is_flagged(matches):
    log = SentLog()
    for m in matches:
        log.record(m, NOW)
    moved = matches[0]
    moved.notice = replace(moved.notice, deadline=moved.notice.deadline + timedelta(days=7))
    sorted_ = log.sort(matches)
    assert [(m.notice.notice_id, c) for m, c in sorted_.amended] == [
        (moved.notice.notice_id, ["deadline changed"])
    ]


def test_amended_then_recorded_is_quiet(profile, notices):
    log = SentLog()
    before = [n for n in notices if not n.notice_id.startswith("100ae619")]
    for m in find_matches(before, profile, NOW)[0]:
        log.record(m, NOW)
    after = find_matches(notices, profile, NOW)[0]
    for m, _ in log.sort(after).amended:
        log.record(m, NOW)
    assert log.sort(after).amended == []


def test_save_and_load_round_trip(tmp_path, matches):
    log = SentLog()
    for m in matches:
        log.record(m, NOW)
    path = tmp_path / "state" / "sent.json"
    log.save(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert len(data["sent"]) == 6
    again = SentLog.load(path)
    assert again.entries == log.entries
    assert again.sort(matches).unchanged == 6


def test_missing_file_is_first_run(tmp_path):
    assert SentLog.load(tmp_path / "nope.json").is_first_run


def test_unknown_version_refused(tmp_path):
    path = tmp_path / "sent.json"
    path.write_text('{"version": 99, "sent": {}}', encoding="utf-8")
    with pytest.raises(ValueError):
        SentLog.load(path)


def test_first_sent_date_is_kept(matches):
    log = SentLog()
    m = matches[0]
    log.record(m, NOW)
    log.record(m, NOW + timedelta(days=3))
    entry = log.entries[m.notice.group_key]
    assert entry["first_sent"] == "2026-11-16"
    assert entry["last_sent"] == "2026-11-19"


def test_prune_forgets_old_entries(matches):
    log = SentLog()
    for m in matches:
        log.record(m, NOW)
    log.entries["id:undated"] = {"notice_id": "x", "deadline": None, "last_sent": "2026-01-01"}
    assert log.prune(NOW) == 1  # only the undated one is old enough
    later = datetime(2027, 3, 1, tzinfo=timezone.utc)
    assert log.prune(later) == 6
    assert log.entries == {}
