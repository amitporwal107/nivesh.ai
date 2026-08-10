"""run_once() outcome semantics — the silent-failure fix.

Between 2026-07-25 and 2026-08-10 every classify call 429'd on an exhausted
OpenAI balance, yet each tick recorded `status=OK, inserted=0` and
`nidp.v_feed_status` stayed green. These pin the distinction between
"nothing to do", "partial progress", and "total outage".
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from nidp.services.announcement_classifier import service as S  # noqa: E402
from nidp.services.announcement_classifier.classifier import Classification  # noqa: E402


def _row(i: int) -> dict:
    return {
        "announcement_id": f"id{i}", "source": "NSE_ANN",
        "company_name": f"Co {i}", "ticker_symbol": f"T{i}",
        "subject": f"Subject {i}", "description": "body",
    }


def _classification() -> Classification:
    return Classification(
        event_category="earnings", impact_score="high", sentiment="positive",
        rationale="r", classifier_version="testver",
    )


@pytest.fixture
def wiring(monkeypatch):
    """Stub the DB + classifier so run_once is exercised in isolation."""
    state = {"rows": [], "stored": [], "behaviour": None}

    async def _fetch(limit):
        return state["rows"][:limit]

    async def _store(announcement_id, source, **kw):
        state["stored"].append((announcement_id, kw["event_category"]))

    class _Clf:
        def __init__(self, *a, **k):
            pass

        def classify(self, row):
            b = state["behaviour"]
            if b == "all_fail":
                raise RuntimeError("429 credit_balance_exhausted")
            if b == "fail_first" and row["announcement_id"] == "id0":
                raise RuntimeError("429 credit_balance_exhausted")
            return _classification()

    monkeypatch.setattr(S, "fetch_unclassified", _fetch)
    monkeypatch.setattr(S, "store_classification", _store)
    monkeypatch.setattr(S, "HaikuClassifier", _Clf)
    return state


@pytest.mark.asyncio
async def test_no_rows_is_a_quiet_ok(wiring):
    """An empty queue is genuinely nothing to do — must NOT raise."""
    wiring["rows"] = []
    out = await S.run_once()
    assert out == {"processed": 0, "errors": 0}


@pytest.mark.asyncio
async def test_all_rows_failing_raises(wiring):
    """THE REGRESSION: 100% failure must surface as FAILED, not a green OK."""
    wiring["rows"] = [_row(i) for i in range(3)]
    wiring["behaviour"] = "all_fail"
    with pytest.raises(RuntimeError, match="all 3 row"):
        await S.run_once()
    assert wiring["stored"] == []


@pytest.mark.asyncio
async def test_partial_failure_still_returns(wiring):
    """Partial progress is not an outage — the batch advanced and the failed
    row stays NULL for the next tick. Must not raise (no false alarms)."""
    wiring["rows"] = [_row(i) for i in range(3)]
    wiring["behaviour"] = "fail_first"
    out = await S.run_once()
    assert out["processed"] == 2
    assert out["errors"] == 1
    assert len(wiring["stored"]) == 2


@pytest.mark.asyncio
async def test_happy_path_writes_all(wiring):
    wiring["rows"] = [_row(i) for i in range(3)]
    out = await S.run_once()
    assert out["processed"] == 3
    assert out["errors"] == 0
    assert len(wiring["stored"]) == 3
    assert out["categories"] == {"earnings": 3}


@pytest.mark.asyncio
async def test_dry_run_does_not_write(wiring):
    wiring["rows"] = [_row(i) for i in range(2)]
    out = await S.run_once(dry_run=True)
    assert out["processed"] == 2
    assert wiring["stored"] == []
