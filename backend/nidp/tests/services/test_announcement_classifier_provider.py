"""Provider/model/tool-spec selection for announcement_classifier.

Covers the 2026-08 switch off the credit-exhausted OpenAI account onto Groq.
No network: the OpenAI SDK client is stubbed, so these assert the REQUEST we
would send and how we parse the response — not Groq's behaviour, which is
verified live (see test_reports/announcement_classifier_groq.md).
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from nidp.services.announcement_classifier import classifier as C  # noqa: E402


_PROVIDER_ENV = (
    "ANNOUNCEMENT_CLASSIFIER_PROVIDER",
    "ANNOUNCEMENT_CLASSIFIER_MODEL",
    "ANNOUNCEMENT_CLASSIFIER_GROQ_MODEL",
    "GROQ_API_KEY",
    "OPENAI_API_KEY",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Every test starts from a known-empty provider environment."""
    for k in _PROVIDER_ENV:
        monkeypatch.delenv(k, raising=False)
    # Neutralise the GSM/helpers layer so only env decides.
    monkeypatch.setattr(C, "get_groq_api_key", lambda: "")
    monkeypatch.setattr(C, "get_openai_api_key", lambda: "")
    yield


class _FakeCompletions:
    def __init__(self, outer):
        self._outer = outer

    def create(self, **kwargs):
        self._outer.last_request = kwargs
        return self._outer.response


class _FakeClient:
    """Stands in for openai.OpenAI — records init args + the request.

    **kwargs absorbs whatever else the installed SDK version's constructor is called with
    (e.g. max_retries=... — HaikuClassifier passes it explicitly); the real SDK accepts it,
    a hand-written fake must not choke on it."""

    def __init__(self, api_key=None, base_url=None, **kwargs):
        self.api_key = api_key
        self.base_url = base_url
        self.last_request = None
        self.response = _tool_response()
        self.chat = types.SimpleNamespace(completions=_FakeCompletions(self))


def _tool_response(args: dict | None = None, name="classify_announcement",
                   finish_reason="tool_calls"):
    payload = args if args is not None else {
        "event_category": "earnings",
        "impact_score": "high",
        "sentiment": "positive",
        "rationale": "Q1 profit beat.",
    }
    fn = types.SimpleNamespace(name=name, arguments=json.dumps(payload))
    tc = types.SimpleNamespace(function=fn)
    msg = types.SimpleNamespace(tool_calls=[tc])
    choice = types.SimpleNamespace(message=msg, finish_reason=finish_reason)
    return types.SimpleNamespace(choices=[choice])


@pytest.fixture
def fake_openai(monkeypatch):
    created: list[_FakeClient] = []

    def _factory(**kwargs):
        c = _FakeClient(**kwargs)
        created.append(c)
        return c

    monkeypatch.setattr(C, "OpenAI", _factory)
    return created


ROW = {
    "announcement_id": "abc123",
    "source": "NSE_ANN",
    "company_name": "Acme Ltd",
    "ticker_symbol": "ACME",
    "subject": "Q1 FY27 results",
    "description": "Consolidated PAT up 42% YoY.",
}


# ── TC-8..TC-10: filing text from the parsed attachment (2026-09-17) ────

def test_build_user_message_omits_filing_text_when_absent():
    """TC-8 — no regression: a row with no parsed document reads exactly as before."""
    msg = C._build_user_message(ROW)
    assert "Filing text" not in msg
    assert msg.startswith("Company: Acme Ltd")


def test_build_user_message_includes_filing_text_when_present():
    """TC-9 — the real gap this closes: Tega's preferential-issue price sat in the parsed PDF
    while the exchange subject was generic. The filing text must reach the prompt."""
    row = {**ROW, "subject": "General Updates", "description": "Tega Industries Limited has informed the Exchange about General Updates",
           "filing_text": "The Board has fixed the issue price at Rs. 1,994 per equity share, raising approximately Rs. 95.40 Crores."}
    msg = C._build_user_message(row)
    assert "Filing text (from the attached document" in msg
    assert "Rs. 1,994 per equity share" in msg
    assert msg.index("Subject: General Updates") < msg.index("Filing text")   # subject still present, filing text is additional


def test_build_user_message_truncates_filing_text_to_4000_chars():
    """TC-10 — an annual report or a long attachment must not blow the prompt open-ended."""
    row = {**ROW, "filing_text": "X" * 10_000}
    msg = C._build_user_message(row)
    tail = msg.split("Filing text (from the attached document, read this for the real content):\n", 1)[1]
    assert len(tail) == 4000


def test_forced_tool_call_uses_filing_text_in_the_actual_request(monkeypatch, fake_openai):
    """TC-11 — end to end through classify(): the filing text reaches the wire request, not just the helper."""
    monkeypatch.setattr(C, "get_groq_api_key", lambda: "gsk_test")
    clf = C.HaikuClassifier()
    row = {**ROW, "subject": "Announcement Pursuant To Reg. 30", "description": "", "filing_text": "Appointment of Mr. X as Chief Financial Officer with effect from 1 October 2026."}
    clf.classify(row)
    sent = fake_openai[0].last_request["messages"][1]["content"]
    assert "Chief Financial Officer" in sent


# ── TC-1 / TC-2 / TC-3: provider selection ──────────────────────────────

def test_defaults_to_openai_without_groq_key():
    """TC-1 — no Groq key anywhere → OpenAI + gpt-4o-mini."""
    assert C.resolve_provider() == "openai"
    assert C.resolve_model("openai") == "gpt-4o-mini"


def test_groq_auto_selected_when_key_resolves(monkeypatch):
    """TC-2 — a resolvable GROQ_API_KEY flips the provider with no code change."""
    monkeypatch.setattr(C, "get_groq_api_key", lambda: "gsk_test")
    assert C.resolve_provider() == "groq"
    assert C.resolve_model("groq") == "openai/gpt-oss-120b"


def test_explicit_provider_overrides_present_groq_key(monkeypatch):
    """TC-3 — an explicit override wins over auto-selection (ops escape hatch)."""
    monkeypatch.setattr(C, "get_groq_api_key", lambda: "gsk_test")
    monkeypatch.setenv("ANNOUNCEMENT_CLASSIFIER_PROVIDER", "openai")
    assert C.resolve_provider() == "openai"


def test_stale_openai_model_pin_does_not_leak_to_groq(monkeypatch):
    """TC-4 — the regression that took the copilot down twice.

    A stale OpenAI id left in ANNOUNCEMENT_CLASSIFIER_MODEL must not be sent to
    Groq, which would reject it and fail every row.
    """
    monkeypatch.setenv("ANNOUNCEMENT_CLASSIFIER_MODEL", "gpt-5.5-nonexistent")
    assert C.resolve_model("groq") == "openai/gpt-oss-120b"
    assert C.resolve_model("openai") == "gpt-5.5-nonexistent"


# ── TC-5: wire shape ────────────────────────────────────────────────────

def test_strict_omitted_on_groq_present_on_openai():
    """TC-5 — `strict` is an OpenAI-only structured-outputs flag."""
    assert "strict" not in C.build_classify_tool("groq")["function"]
    assert C.build_classify_tool("openai")["function"]["strict"] is True
    # The enums must survive on both — they are what constrains Groq.
    for provider in ("groq", "openai"):
        props = C.build_classify_tool(provider)["function"]["parameters"]["properties"]
        assert props["event_category"]["enum"] == list(C.EVENT_CATEGORIES)


def test_groq_client_gets_groq_base_url(monkeypatch, fake_openai):
    """TC-5b — the Groq client is the OpenAI SDK pointed at Groq's base_url."""
    monkeypatch.setattr(C, "get_groq_api_key", lambda: "gsk_test")
    clf = C.HaikuClassifier()
    assert clf.provider == "groq"
    assert fake_openai[0].base_url == C.GROQ_BASE_URL
    assert fake_openai[0].api_key == "gsk_test"

    clf.classify(ROW)
    req = fake_openai[0].last_request
    assert req["model"] == "openai/gpt-oss-120b"
    assert req["tool_choice"]["function"]["name"] == "classify_announcement"
    assert "strict" not in req["tools"][0]["function"]


def test_openai_client_has_no_base_url_override(monkeypatch, fake_openai):
    monkeypatch.setattr(C, "get_openai_api_key", lambda: "sk_test")
    clf = C.HaikuClassifier()
    assert clf.provider == "openai"
    assert fake_openai[0].base_url is None


# ── TC-6 / TC-7: parsing ────────────────────────────────────────────────

def test_forced_tool_call_parsed(monkeypatch, fake_openai):
    """TC-6 — a well-formed tool call becomes a Classification."""
    monkeypatch.setattr(C, "get_groq_api_key", lambda: "gsk_test")
    clf = C.HaikuClassifier()
    out = clf.classify(ROW)
    assert out.event_category == "earnings"
    assert out.impact_score == "high"
    assert out.sentiment == "positive"
    assert out.classifier_version == clf.classifier_version
    assert out.classifier_version.startswith("openaigptoss120b-")


def test_missing_tool_call_raises(monkeypatch, fake_openai):
    """TC-7 — no tool call must raise, so the row stays unclassified and retries."""
    monkeypatch.setattr(C, "get_groq_api_key", lambda: "gsk_test")
    clf = C.HaikuClassifier()
    empty = types.SimpleNamespace(
        choices=[types.SimpleNamespace(
            message=types.SimpleNamespace(tool_calls=[]), finish_reason="stop")]
    )
    fake_openai[0].response = empty
    with pytest.raises(RuntimeError, match="no tool_call"):
        clf.classify(ROW)


@pytest.mark.parametrize("bad", [
    {"event_category": "acquisition", "impact_score": "high", "sentiment": "positive", "rationale": ""},
    {"event_category": "earnings", "impact_score": "critical", "sentiment": "positive", "rationale": ""},
    {"event_category": "earnings", "impact_score": "high", "sentiment": "bullish", "rationale": ""},
])
def test_out_of_taxonomy_value_raises(monkeypatch, fake_openai, bad):
    """TC-7b — without `strict`, Groq could invent a value. It must never reach
    the DB: event_category is the /v5/research facet key."""
    monkeypatch.setattr(C, "get_groq_api_key", lambda: "gsk_test")
    clf = C.HaikuClassifier()
    fake_openai[0].response = _tool_response(bad)
    with pytest.raises(RuntimeError, match="out-of-taxonomy"):
        clf.classify(ROW)


# ── TC-8: version ───────────────────────────────────────────────────────

def test_classifier_version_deterministic_and_provider_distinct():
    """TC-8 — stable per (model, prompt), and distinguishes Groq from OpenAI rows."""
    assert C._classifier_version("openai/gpt-oss-120b") == C._classifier_version("openai/gpt-oss-120b")
    assert C._classifier_version("openai/gpt-oss-120b") != C._classifier_version("gpt-4o-mini")
    # No '/' leaks into the version prefix (it is stored in a text column and
    # read back by ops queries).
    assert "/" not in C._classifier_version("openai/gpt-oss-120b")


def test_missing_groq_key_raises_actionable_error(monkeypatch, fake_openai):
    """Provider forced to groq with no key → a message naming the real fix."""
    monkeypatch.setenv("ANNOUNCEMENT_CLASSIFIER_PROVIDER", "groq")
    with pytest.raises(RuntimeError, match="GROQ_API_KEY not set"):
        C.HaikuClassifier()
