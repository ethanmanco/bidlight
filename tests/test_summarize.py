import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from bidlight.digest import EM_DASH
from bidlight.match import find_matches
from bidlight.summarize import CostMeter, SYSTEM_PROMPT, build_prompt, crosses_the_line, summarize

from .conftest import NOW

CAPABILITY = "We build websites and fix accessibility issues."


class FakeClient:
    """Stands in for anthropic.Anthropic; records calls, returns canned replies."""

    def __init__(self, replies=None, input_tokens=3000, output_tokens=200):
        self.calls = []
        self.replies = replies
        self.tokens = (input_tokens, output_tokens)
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        reply = (self.replies or {}).get(len(self.calls))
        if isinstance(reply, Exception):
            raise reply
        stop = "end_turn"
        if isinstance(reply, tuple):
            stop, reply = reply
        text = reply if reply is not None else json.dumps(
            {"summary": f"Summary {len(self.calls)} {EM_DASH} plain.", "fit": "Overlaps with web work."}
        )
        return SimpleNamespace(
            stop_reason=stop,
            content=[SimpleNamespace(type="text", text=text)],
            usage=SimpleNamespace(input_tokens=self.tokens[0], output_tokens=self.tokens[1]),
        )


@pytest.fixture
def matches(profile, notices):
    return find_matches(notices, profile, NOW)[0]


def test_summaries_for_each_match(profile, matches):
    client = FakeClient()
    run = summarize(matches, CAPABILITY, profile.ai, client)
    assert len(run.summaries) == 6
    first = run.summaries[matches[0].notice.notice_id]
    assert first.text == "Summary 1, plain."  # em dash removed
    assert first.fit == "Overlaps with web work."
    call = client.calls[0]
    assert call["model"] == "claude-haiku-5-5"
    assert call["max_tokens"] == 500
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert "FEMA" in call["messages"][0]["content"]
    assert CAPABILITY in call["messages"][0]["content"]
    # 6 calls x (3000 in x $0.10 + 200 out x $0.50) per million tokens
    assert run.spent_usd == pytest.approx(6 * 0.0004)


def test_missing_key_skips_summaries(profile, matches, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    run = summarize(matches, CAPABILITY, profile.ai)
    assert run.summaries == {}
    assert "no ANTHROPIC_API_KEY" in run.note


def test_turned_off_in_profile(profile, matches):
    off = replace(profile.ai, enabled=False)
    client = FakeClient()
    run = summarize(matches, CAPABILITY, off, client)
    assert client.calls == [] and run.summaries == {}


def test_cost_cap_stops_calls(profile, matches):
    # Worst-case estimates here run $0.0003 to $0.0005 per call and each fake
    # call really costs $0.0004, so a $0.0005 cap leaves room for exactly one.
    tight = replace(profile.ai, daily_cost_cap_usd=0.0005)
    client = FakeClient()
    run = summarize(matches, CAPABILITY, tight, client)
    assert len(client.calls) == 1
    assert len(run.summaries) == 1
    assert "5 skipped to stay under the cap" in run.note
    assert run.spent_usd <= 0.0005


def test_zero_cap_means_no_calls(profile, matches):
    client = FakeClient()
    run = summarize(matches, CAPABILITY, replace(profile.ai, daily_cost_cap_usd=0), client)
    assert client.calls == []
    assert run.summaries == {}


def test_worst_case_estimate_covers_real_cost(profile, matches):
    meter = CostMeter(profile.ai)
    prompt = build_prompt(matches[0], CAPABILITY, profile.ai.description_chars)
    # A real tokenizer averages about 4 characters per token for English.
    realistic = meter.cost(len(SYSTEM_PROMPT + prompt) // 4, profile.ai.max_output_tokens)
    assert meter.worst_case(SYSTEM_PROMPT, prompt) > realistic


def test_one_failure_does_not_stop_the_rest(profile, matches):
    client = FakeClient(replies={2: RuntimeError("boom"), 3: "not json", 4: ("refusal", "{}")})
    run = summarize(matches, CAPABILITY, profile.ai, client)
    assert len(client.calls) == 6
    assert len(run.summaries) == 3
    assert "3 could not be summarized" in run.note


def test_advice_is_dropped(profile, matches):
    bad = json.dumps({"summary": "The Navy wants support.", "fit": "Manco Labs is eligible and should bid."})
    client = FakeClient(replies={1: bad})
    run = summarize(matches, CAPABILITY, profile.ai, client)
    assert matches[0].notice.notice_id not in run.summaries
    assert len(run.summaries) == 5


@pytest.mark.parametrize(
    "text, bad",
    [
        ("You are eligible for this set-aside.", True),
        ("Your business is a good fit.", True),
        ("You should bid on this.", True),
        ("We recommend pursuing this one.", True),
        ("We recommend bidding.", True),
        ("This one is worth pursuing.", True),
        ("Only SeaPort-NxG holders are eligible to respond.", False),
        ("Overlaps with website maintenance in the capability statement.", False),
    ],
)
def test_no_advice_check(text, bad):
    assert crosses_the_line(text) is bad


def test_prompt_trims_long_descriptions(matches):
    m = matches[0]
    m.notice = replace(m.notice, description="word " * 10_000)
    prompt = build_prompt(m, CAPABILITY, 6000)
    assert len(prompt) < 6000 + 1000


def test_api_error_message_is_kept(profile, matches):
    class ApiError(Exception):
        message = "output_config.format: not supported"

    run = summarize(matches[:1], CAPABILITY, profile.ai, FakeClient(replies={1: ApiError()}))
    assert run.errors == ["ApiError: output_config.format: not supported"]
