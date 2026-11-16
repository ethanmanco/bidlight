"""SAM.gov API adapter, GitHub posting, and the end-to-end runner."""

import json
from datetime import datetime, timezone

import pytest

from bidlight import cli
from bidlight.github import GitHubError, post_issue
from bidlight.sam_api import fetch_recent, record_to_notice

from .conftest import FIXTURE, ROOT

# Shaped like the response documented at open.gsa.gov (Get Opportunities v2).
# Hand-written: Bidlight has no API key to record a live response with.
API_RECORD = {
    "noticeId": "abc123def456abc123def456abc12345",
    "title": "Agency Website Redesign and WCAG Remediation",
    "solicitationNumber": "TEST-27-Q-0001",
    "fullParentPathName": "GENERAL SERVICES ADMINISTRATION.FEDERAL ACQUISITION SERVICE.GSA/FAS ADMIN SUPPORT",
    "postedDate": "2026-11-16",
    "type": "Combined Synopsis/Solicitation",
    "typeOfSetAsideDescription": "Total Small Business Set-Aside (FAR 19.5)",
    "typeOfSetAside": "SBA",
    "responseDeadLine": "2026-12-10T14:00:00-06:00",
    "naicsCode": "541511",
    "placeOfPerformance": {
        "city": {"code": "55000", "name": "New Orleans"},
        "state": {"code": "LA", "name": "Louisiana"},
        "country": {"code": "USA", "name": "UNITED STATES"},
    },
    "active": "Yes",
}

NOW = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def _next(self, method, url, **kw):
        self.requests.append((method, url, kw))
        return self.responses.pop(0)

    def get(self, url, **kw):
        return self._next("GET", url, **kw)

    def post(self, url, **kw):
        return self._next("POST", url, **kw)


def test_api_record_maps_to_notice():
    n = record_to_notice(API_RECORD)
    assert n.agency == "GENERAL SERVICES ADMINISTRATION"
    assert n.sub_tier == "FEDERAL ACQUISITION SERVICE"
    assert n.set_aside_code == "SBA"
    assert n.pop_state == "LA" and n.pop_city == "New Orleans"
    assert n.deadline == datetime(2026, 12, 10, 20, tzinfo=timezone.utc)
    assert n.source == "api"


def test_api_accepts_documented_spelling():
    record = dict(API_RECORD)
    record["reponseDeadLine"] = record.pop("responseDeadLine")
    assert record_to_notice(record).deadline is not None


def test_api_one_request_per_naics():
    page = {"totalRecords": 1, "opportunitiesData": [API_RECORD]}
    session = FakeSession([FakeResponse(200, page), FakeResponse(404), FakeResponse(200, {"totalRecords": 0})])
    result = fetch_recent("KEY", ("541511", "541512", "541519"), NOW, 5, session)
    assert result.requests_made == 3
    assert [n.notice_id for n in result.notices] == [API_RECORD["noticeId"]]
    params = session.requests[0][2]["params"]
    assert params["postedFrom"] == "11/15/2026" and params["postedTo"] == "11/16/2026"
    assert params["ncode"] == "541511" and params["limit"] == 1000


def test_api_respects_request_cap():
    session = FakeSession([FakeResponse(200, {"totalRecords": 0})] * 5)
    result = fetch_recent("KEY", ("541511", "541512", "541519"), NOW, 2, session)
    assert result.requests_made == 2
    assert "2-request limit" in result.note


def test_api_stops_on_rate_limit():
    session = FakeSession([FakeResponse(429)])
    result = fetch_recent("KEY", ("541511", "541512"), NOW, 5, session)
    assert result.requests_made == 1
    assert "daily limit" in result.note


def test_api_errors_never_include_the_key():
    session = FakeSession([FakeResponse(500, text="secret KEY echoed")])
    result = fetch_recent("KEY", ("541511",), NOW, 5, session)
    assert "KEY" not in result.note


def test_post_issue():
    session = FakeSession([FakeResponse(422), FakeResponse(201, {"html_url": "https://github.com/o/r/issues/1"})])
    url = post_issue("o/r", "TOKEN", "Title", "Body", session)
    assert url == "https://github.com/o/r/issues/1"
    issue = session.requests[1][2]["json"]
    assert issue == {"title": "Title", "body": "Body", "labels": ["digest"]}
    assert session.requests[1][2]["headers"]["Authorization"] == "Bearer TOKEN"


def test_post_issue_failure_raises():
    session = FakeSession([FakeResponse(201), FakeResponse(403, text="forbidden")])
    with pytest.raises(GitHubError):
        post_issue("o/r", "TOKEN", "T", "B", session)


def run(tmp_path, *extra):
    state = tmp_path / "sent.json"
    out = tmp_path / "digest.md"
    code = cli.main([
        "--profile", str(ROOT / "profile.yaml"),
        "--capability", str(ROOT / "capability.md"),
        "--file", str(FIXTURE),
        "--state", str(state),
        "--out", str(out),
        "--now", "2026-11-16T12:00:00+00:00",
        *extra,
    ])
    return code, state, out


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "SAM_API_KEY", "GITHUB_TOKEN", "GITHUB_REPOSITORY"):
        monkeypatch.delenv(name, raising=False)


def test_end_to_end_then_quiet_next_day(tmp_path):
    code, state, out = run(tmp_path)
    assert code == 0
    body = out.read_text(encoding="utf-8")
    assert "6 new matches" in body
    assert "First run" in body
    assert "no ANTHROPIC_API_KEY" in body
    assert len(json.loads(state.read_text(encoding="utf-8"))["sent"]) == 6

    code, _, out = run(tmp_path)
    assert code == 0
    assert not out.exists()  # nothing new: no digest, nothing to post


def test_dry_run_leaves_state_alone(tmp_path):
    _, state, out = run(tmp_path, "--dry-run")
    assert out.exists()
    assert not state.exists()


def test_failed_post_keeps_state(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_TOKEN", "TOKEN")

    def fail(*a, **k):
        raise GitHubError("nope")

    monkeypatch.setattr(cli, "post_issue", fail)
    code, state, _ = run(tmp_path, "--post")
    assert code == 1
    assert not state.exists()


def test_successful_post_saves_state(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_TOKEN", "TOKEN")
    posted = []
    monkeypatch.setattr(cli, "post_issue", lambda repo, token, title, body: posted.append(title) or "url")
    code, state, _ = run(tmp_path, "--post")
    assert code == 0
    assert posted == ["Bidlight: 6 new matches, Mon Nov 16, 2026"]
    assert state.exists()


def test_post_without_github_env_fails(tmp_path):
    code, state, _ = run(tmp_path, "--post")
    assert code == 1
    assert not state.exists()
