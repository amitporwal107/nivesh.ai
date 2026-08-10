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
    """Stands in for openai.OpenAI — records init args + the request."""

    def __init__(self, api_key=None, base_url=None):
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
