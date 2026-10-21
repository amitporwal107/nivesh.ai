"""No personal detail reaches a model provider, from any call site.

The rule (user, 2026-10-22): PAN, Aadhaar, mobile, address and date of birth are not sent to an LLM
"in any case", and not "in plain text or encrypted form" — so not as a hash of the value either.

These tests exercise the real SDK classes: the guard patches
`openai.resources.chat.completions.(Async)Completions.create` and
`anthropic.resources.messages.(Async)Messages.create`, so a test that calls a stubbed transport
through a real client proves the interception point is the one the app actually uses.
"""
from __future__ import annotations

import pytest

from services import llm_guard, llm_safety

SAMPLE = ("Investor ABCDE1234F, Aadhaar 1234 5678 9012, mobile 9876543210, "
          "mail a.b@example.com\nDOB: 01/01/1980\nAddress: 12 MG Road, Pune 411001")


# ── the redactor ────────────────────────────────────────────────────────────

def test_every_declared_kind_is_found_and_then_removed():
    assert set(llm_safety.scan(SAMPLE)) == set(llm_safety.PII_KINDS)
    assert llm_safety.scan(llm_safety.redact_pii(SAMPLE)) == {}


def test_tokens_carry_nothing_derived_from_the_value():
    """The module used to emit a truncated SHA-256 of the value. Anyone holding a candidate PAN
    could hash it and confirm a match, and the token followed the person across requests. The user
    ruled out plain text AND encrypted form, so the token must be an ordinal."""
    import hashlib

    out = llm_safety.redact_pii(SAMPLE)
    for secret in ("ABCDE1234F", "123456789012", "9876543210", "a.b@example.com"):
        assert secret not in out
        assert hashlib.sha256(secret.encode()).hexdigest()[:8] not in out
    assert "[PAN_1]" in out


def test_the_same_value_keeps_one_token_within_a_text():
    out = llm_safety.redact_pii("ABCDE1234F and again ABCDE1234F and ZYXWV9876K")
    assert out.count("[PAN_1]") == 2 and "[PAN_2]" in out


def test_a_date_that_is_not_a_date_of_birth_survives():
    """DOB is label-anchored on purpose: redacting every date would destroy the transaction and NAV
    dates the model needs to answer about a portfolio."""
    kept = "Bought on 12/03/2024 at NAV dated 2024-03-12"
    assert llm_safety.redact_pii(kept) == kept


def test_known_values_are_masked_even_without_a_label():
    """Pattern matching cannot recognise an address written as prose; exact-value masking can."""
    out = llm_safety.redact_values("I live at Flat 9 Rose Villa, born March 1980",
                                   ["Flat 9 Rose Villa", "March 1980"])
    assert "Flat 9 Rose Villa" not in out and "March 1980" not in out


def test_extract_pan_lets_a_caller_keep_the_pan_without_sending_it():
    """The CAS parsers ask the model to read `pan` out of the statement. Under the rule they must
    take it locally instead."""
    assert llm_safety.extract_pan(SAMPLE) == "ABCDE1234F"
    assert llm_safety.extract_pan("no pan here") is None


# ── the guard ───────────────────────────────────────────────────────────────

def test_install_wraps_every_expected_sdk_target():
    llm_guard.install()
    live = llm_guard.installed_targets()
    assert "openai.resources.chat.completions.Completions.create" in live
    assert "openai.resources.chat.completions.AsyncCompletions.create" in live
    assert "anthropic.resources.messages.Messages.create" in live
    assert "anthropic.resources.messages.AsyncMessages.create" in live


def test_install_is_idempotent():
    llm_guard.install()
    first = llm_guard.installed_targets()
    llm_guard.install()
    assert llm_guard.installed_targets() == first


def test_sanitize_redacts_message_content():
    out = llm_guard.sanitize({"messages": [{"role": "user", "content": SAMPLE}]})
    body = out["messages"][0]["content"]
    assert "ABCDE1234F" not in body and "9876543210" not in body
    assert llm_safety.scan(body) == {}


def test_sanitize_redacts_the_anthropic_system_field():
    out = llm_guard.sanitize({"system": SAMPLE, "messages": []})
    assert "ABCDE1234F" not in out["system"]


def test_sanitize_redacts_text_blocks_and_leaves_images_alone():
    kwargs = {"messages": [{"role": "user", "content": [
        {"type": "text", "text": SAMPLE},
        {"type": "image", "source": {"type": "base64", "data": "AAAA"}},
    ]}]}
    out = llm_guard.sanitize(kwargs)
    blocks = out["messages"][0]["content"]
    assert "ABCDE1234F" not in blocks[0]["text"]
    assert blocks[1]["source"]["data"] == "AAAA"
    assert llm_guard.describe_unscannable(kwargs) == ["image"]


def test_it_fails_closed_when_something_survives(monkeypatch):
    """If redaction ever misses, the call must raise instead of being sent. A false positive costs
    one request; a false negative sends a PAN to a third party."""
    monkeypatch.setattr(llm_safety, "redact_pii", lambda t: t)
    with pytest.raises(llm_guard.PiiWouldLeak):
        llm_guard.sanitize({"messages": [{"role": "user", "content": SAMPLE}]})


def test_the_exception_does_not_put_the_secret_in_the_log():
    import re as _re

    bad = {"messages": [{"role": "user", "content": "x"}]}
    try:
        # force the failure path with a text the stub redactor leaves alone
        import unittest.mock as mock
        with mock.patch.object(llm_safety, "redact_pii", lambda t: t):
            llm_guard.sanitize({"messages": [{"role": "user", "content": SAMPLE}]})
        pytest.fail("expected PiiWouldLeak")
    except llm_guard.PiiWouldLeak as e:
        msg = str(e)
        assert "ABCDE1234F" not in msg and "9876543210" not in msg
        assert _re.search(r"\bPAN\b", msg)


def test_a_real_async_openai_client_is_intercepted():
    """End to end through the real SDK class the app constructs, with the transport stubbed. This is
    the test that proves the patch point is the one that matters. Run with asyncio directly because
    this suite has no pytest-asyncio plugin."""
    import asyncio
    import unittest.mock as mock

    import openai

    llm_guard.install()
    captured = {}

    async def fake_post(self, path, *, body=None, **kw):
        captured["body"] = body
        raise RuntimeError("stop-before-network")

    async def go():
        client = openai.AsyncOpenAI(api_key="test-key-not-real")
        with mock.patch.object(type(client), "post", fake_post, create=True):
            with pytest.raises(RuntimeError):
                await client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": SAMPLE}],
                )

    asyncio.run(go())
    blob = str(captured.get("body") or {})
    assert blob, "the transport was never reached; the test proves nothing"
    assert "ABCDE1234F" not in blob, "a PAN reached the transport layer"
    assert "9876543210" not in blob and "a.b@example.com" not in blob
    assert "[PAN_1]" in blob, "the redacted token should be what was sent"


def test_a_real_sync_anthropic_client_is_intercepted():
    """The other provider, through its own SDK class."""
    import unittest.mock as mock

    import anthropic

    llm_guard.install()
    captured = {}

    def fake_post(self, path, *, body=None, **kw):
        captured["body"] = body
        raise RuntimeError("stop-before-network")

    client = anthropic.Anthropic(api_key="test-key-not-real")
    with mock.patch.object(type(client), "post", fake_post, create=True):
        with pytest.raises(RuntimeError):
            client.messages.create(
                model="claude-3-5-haiku-latest",
                max_tokens=16,
                system=SAMPLE,
                messages=[{"role": "user", "content": SAMPLE}],
            )

    blob = str(captured.get("body") or {})
    assert blob, "the transport was never reached; the test proves nothing"
    assert "ABCDE1234F" not in blob and "9876543210" not in blob
