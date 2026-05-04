"""Smoke test: /chat/send and /chat/stream see the advisor's full client book
when the caller owns an ADVISORY workspace and is NOT impersonating.

Regression guard for the bug where the floating Nivesh Copilot in advisor
mode answered "I don't have your portfolio data" — the chat endpoints
were only loading the advisor's own user_id holdings instead of the
cross-client `_advisor_book_block`.
"""
from __future__ import annotations

import json
import os

import pytest
import requests

BASE_URL = os.environ.get("NIVESH_TEST_BASE_URL", "http://localhost:8001")
# aporwal107@gmail.com — owns ADVISORY workspace with 2 CLIENT profiles
# (Ahaan porwal, priyankamantri). Not impersonating.
ADVISOR_TOKEN = os.environ.get(
    "NIVESH_TEST_USER_TOKEN", "5770bebb-8a9a-41f7-a7b9-e8152ac25daa"
)

ADVISOR_HEADERS = {
    "Authorization": f"Bearer {ADVISOR_TOKEN}",
    "Content-Type": "application/json",
}

# A client name we expect to appear in the advisor book; matched
# case-insensitively because LLMs normalise capitalisation.
EXPECTED_CLIENT_NAMES = ("ahaan", "priyanka")


def _stream_chat_response(question: str) -> str:
    """POST to /chat/stream and concatenate the streamed token deltas
    into the full assistant reply. Returns the assembled string."""
    with requests.post(
        f"{BASE_URL}/api/chat/stream",
        headers=ADVISOR_HEADERS,
        json={"message": question},
        timeout=120,
        stream=True,
    ) as r:
        assert r.status_code == 200, f"stream failed: {r.status_code} {r.text[:300]}"
        full = ""
        done_payload = None
        for raw in r.iter_lines(decode_unicode=True):
            if not raw or not raw.startswith("data: "):
                continue
            try:
                evt = json.loads(raw[len("data: "):])
            except json.JSONDecodeError:
                continue
            if evt.get("type") == "token":
                full += evt.get("content", "")
            elif evt.get("type") == "done":
                done_payload = evt.get("content", "")
            elif evt.get("type") == "error":
                pytest.fail(f"stream returned error: {evt.get('content')}")
        # Prefer the `done` payload (full text) when present, else the
        # accumulated tokens.
        return done_payload or full


def test_chat_stream_advisor_sees_client_book():
    """Asking 'how many clients do I have' should produce a reply that
    references the real client names from the advisor book — proving
    /chat/stream now injects the cross-client context in advisor mode."""
    reply = _stream_chat_response("How many clients do I have, and who are they?")
    assert reply, "advisor chat returned empty reply"
    lower = reply.lower()
    matched = [name for name in EXPECTED_CLIENT_NAMES if name in lower]
    assert matched, (
        "advisor chat reply does not reference any known client name "
        f"({EXPECTED_CLIENT_NAMES}); got: {reply[:500]!r}"
    )


def test_chat_send_advisor_sees_client_book():
    """Non-streaming /chat/send mirrors the same advisor-mode behaviour."""
    r = requests.post(
        f"{BASE_URL}/api/chat/send",
        headers=ADVISOR_HEADERS,
        json={"message": "List my top clients by AUM. Use a Markdown table."},
        timeout=120,
    )
    assert r.status_code == 200, f"send failed: {r.status_code} {r.text[:300]}"
    payload = r.json()
    reply = (payload.get("ai_message") or {}).get("content") or ""
    assert reply, f"advisor chat returned empty content: {payload}"
    lower = reply.lower()
    matched = [name for name in EXPECTED_CLIENT_NAMES if name in lower]
    assert matched, (
        "advisor chat reply does not reference any known client name "
        f"({EXPECTED_CLIENT_NAMES}); got: {reply[:500]!r}"
    )
