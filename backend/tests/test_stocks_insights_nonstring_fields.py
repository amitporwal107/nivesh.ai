"""Regression: the stocks_insights copilot tool must never raise on a non-string
DAAS field.

Root cause of the `/research` copilot "Something went wrong answering that."
failure: `StocksInsightsResult.as_llm_context()` sliced `filed_at` / `headline`
directly ( `(e.get("filed_at") or "")[:10]` ). The per-ticker /announcements feed
returns ISO-string dates, but the THEMATIC market-pulse / events-search feed can
return `filed_at` as a numeric epoch — and `int[:10]` raises
`TypeError: 'int' object is not subscriptable`. That throw is UNGUARDED inside
`stocks_insights_node` (after intent routing — hence the UI showed "ROUTE 1.00"
then errored), so it propagated to the /chat/stream handler and became an SSE
`error` frame → the generic client error, with no answer.

These tests exercise the pure builders with the awkward shapes DAAS can emit and
assert they degrade to a string instead of raising. Pure functions, no network —
they import only the tool module (no langchain), so they run anywhere.
"""
from __future__ import annotations

import datetime

import pytest

from services.copilot_tools.stocks_insights import (
    StocksInsightsResult,
    build_widget_data,
)


# Each case is a single DAAS row whose fields are typed the way a real feed
# *can* serialise them (JSON numbers, or a stray non-string). Pre-fix, the first
# three raised TypeError in as_llm_context().
_EVENT_CASES = [
    ("filed_at as epoch int", {"headline": "Bags ₹1200cr order", "filed_at": 1719878400, "category": "order_win"}),
    ("filed_at as datetime", {"headline": "New plant", "filed_at": datetime.datetime(2026, 7, 1), "category": "capex"}),
    ("headline as int", {"headline": 12345, "filed_at": "2026-07-01", "category": "order_win"}),
    ("all strings (happy path)", {"headline": "PSU order", "filed_at": "2026-07-01", "category": "order_win", "summary": "x"}),
]

_COMMENTARY_CASES = [
    ("company/doc_type None, page str", {"text": "margins improved", "company": None, "doc_type": None, "page": "7"}),
    ("company as int", {"text": "guidance raised", "company": 500325, "doc_type": "concall_transcript", "page": 3}),
]


@pytest.mark.parametrize("label,event", _EVENT_CASES)
def test_as_llm_context_events_never_raises(label, event):
    r = StocksInsightsResult(ok=True, summary="s", mode="thematic", events=[event])
    ctx = r.as_llm_context()  # must not raise
    assert isinstance(ctx, str) and ctx, label


@pytest.mark.parametrize("label,comm", _COMMENTARY_CASES)
def test_as_llm_context_commentary_never_raises(label, comm):
    r = StocksInsightsResult(ok=True, summary="s", mode="thematic", commentary=[comm])
    ctx = r.as_llm_context()  # must not raise
    assert isinstance(ctx, str) and ctx, label


@pytest.mark.parametrize("label,event", _EVENT_CASES)
def test_build_widget_data_events_never_raises(label, event):
    r = StocksInsightsResult(ok=True, summary="s", mode="thematic", events=[event])
    w = build_widget_data(r, "answer")  # must not raise
    assert w["mode"] == "thematic" and isinstance(w["sources"], list), label


def test_thematic_epoch_row_renders_date_prefix():
    """The 10-char slice still yields a sensible token from a coerced value."""
    r = StocksInsightsResult(
        ok=True, summary="s", mode="thematic",
        events=[{"headline": "Order win", "filed_at": 1719878400, "category": "order_win"}],
    )
    ctx = r.as_llm_context()
    # str(1719878400)[:10] -> "1719878400"; the point is it is a STRING and present.
    assert "1719878400" in ctx
