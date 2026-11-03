"""GET /api/macro/regime-history: the desk regime (desk-regime-v1) of each stored session, recomputed from the stored
end-of-day inputs (routes/macro.py, services/macro_engine.desk_regime_inputs). Test cases:
test_reports/iv_history_TESTCASES.md (RG-n below).

No Postgres and no network: macro_engine.desk_regime_inputs and session_breadth, and the warehouse Nifty 50 read, are
fakes answering with fixture rows (MOCK — not real data). The route and the regime rule run for real.

The rule (macro_engine.DESK_REGIME_RULE): India VIX at or above 20 → high volatility; else the Nifty 50 trend (close vs
its 50-session average) against breadth (advances share ≥ 52% up, ≤ 48% down) → mixed when they disagree; else the
trend: above bullish, equal sideways, below bearish.
    2026-10-19  close 25,000 > average 24,000, VIX 14, 600 up / 400 down (60%)   → bullish
    2026-10-20  close 25,000 > average 24,000, VIX 22                           → high volatility
    2026-10-21  close 23,000 < average 24,000, VIX 14, 600 up / 400 down        → mixed (trend down, breadth up)
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from routes import macro as route
from services import macro_engine
from services.copilot_tools import daas_client


def _row(day: str, nifty: Optional[float], avg: Optional[float], vix: Optional[float]) -> Dict[str, Any]:
    return {"date": day, "nifty": nifty, "nifty_50dma": avg, "india_vix": vix}


def _breadth(day: str, adv: int, dec: int) -> Dict[str, Any]:
    return {"date": day, "advances": adv, "declines": dec, "unchanged": 5, "universe": adv + dec + 5,
            "source": "stock_ohlcv end-of-day bars (NSE bhavcopy)"}


ROWS = [
    _row("2026-10-19", 25000.0, 24000.0, 14.0),
    _row("2026-10-20", 25000.0, 24000.0, 22.0),
    _row("2026-10-21", 23000.0, 24000.0, 14.0),
]
BREADTH = {r["date"]: _breadth(r["date"], 600, 400) for r in ROWS}


def _client(monkeypatch, rows=ROWS, *, breadth=BREADTH, breadth_fail=(), warehouse=None, non_sessions=0,
            fail: Optional[Exception] = None, signed_in: bool = True):
    calls: Dict[str, List[Any]] = {"inputs": [], "breadth": [], "warehouse": []}

    async def inputs(limit):
        calls["inputs"].append(limit)
        if fail:
            raise fail
        return {"rows": [dict(r) for r in rows][-limit:], "non_session_rows": non_sessions}

    async def session_breadth(session: date):
        calls["breadth"].append(session.isoformat())
        if session.isoformat() in breadth_fail:
            raise RuntimeError("pool gone")
        return (breadth or {}).get(session.isoformat())

    async def index_history(name, start=None, end=None, **_k):
        calls["warehouse"].append((name, start, end))
        if isinstance(warehouse, Exception):
            raise warehouse
        return list(warehouse or [])

    monkeypatch.setattr(macro_engine, "desk_regime_inputs", inputs)
    monkeypatch.setattr(macro_engine, "session_breadth", session_breadth)
    monkeypatch.setattr(daas_client, "get_index_eod_history", index_history)
    route._BREADTH_CACHE.clear()
    if signed_in:
        async def fake_user(request: Request):
            return {"user_id": "u1"}
        monkeypatch.setattr(route, "get_current_user", fake_user)
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app), calls


def test_rg1_every_input_stored_gives_one_point_per_session_oldest_first(monkeypatch):
    c, calls = _client(monkeypatch)
    body = c.get("/api/macro/regime-history?days=3").json()
    assert calls["inputs"] == [3] and calls["warehouse"] == []                   # every average is stored: no warehouse read
    assert [p["date"] for p in body["points"]] == ["2026-10-19", "2026-10-20", "2026-10-21"]
    assert [p["key"] for p in body["points"]] == ["bullish", "high_volatility", "mixed"]
    assert all(p["rule_version"] == "desk-regime-v1" and p["skipped"] == [] and p["reason"] is None for p in body["points"])
    first = body["points"][0]["inputs"]
    assert (first["nifty_close"], first["nifty_average"], first["india_vix"], first["advancing_share_pct"], first["breadth"]) == (
        25000.0, 24000.0, 14.0, 60.0, "up")
    assert first["nifty_source"] == route.NIFTY_MACRO_SOURCE
    assert (body["sessions"], body["complete"], body["partial"], body["unclassified"], body["missing"]) == (3, 3, 0, 0, [])
    assert body["rule_version"] == "desk-regime-v1" and body["rule"]["vix_high"] == 20.0 and "not a record" in body["basis"]
    assert (body["first_session"], body["last_session"], body["read_only"]) == ("2026-10-19", "2026-10-21", True)


def test_rg2_a_session_without_india_vix_keeps_its_trend_and_names_the_skipped_check(monkeypatch):
    rows = [_row("2026-10-19", 25000.0, 24000.0, None)]
    c, _ = _client(monkeypatch, rows)
    body = c.get("/api/macro/regime-history").json()
    [p] = body["points"]
    assert p["key"] == "bullish" and [s["check"] for s in p["skipped"]] == ["high_volatility"]
    assert (body["complete"], body["partial"]) == (0, 1)
    assert any("India VIX" in m and "1 of 1" in m for m in body["missing"])


def _closes(end: str, n: int, value: float, last: float) -> List[Dict[str, Any]]:
    """`n` weekday Nifty 50 closes ending at `end` (MOCK — not real data): `value` each, `last` on `end`."""
    d, out = date.fromisoformat(end), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append({"as_of_date": d.isoformat(), "close_price": last if not out else value})
        d -= timedelta(days=1)
    return sorted(out, key=lambda r: r["as_of_date"])


def test_rg3_without_a_stored_average_the_warehouse_closes_are_used_as_on_today(monkeypatch):
    """macro_features has no average for two sessions: the warehouse is read ONCE for both. On 2026-10-21 the last 50
    warehouse sessions are 49 closes of 100 and the day's 110: average (49 × 100 + 110) / 50 = 100.2, close 110 above it."""
    rows = [_row("2026-10-20", 25000.0, None, 14.0), _row("2026-10-21", 25000.0, None, 14.0)]
    warehouse = _closes("2026-10-21", 70, 100.0, 110.0)
    c, calls = _client(monkeypatch, rows, warehouse=warehouse)
    body = c.get("/api/macro/regime-history").json()
    assert len(calls["warehouse"]) == 1
    name, start, end = calls["warehouse"][0]
    assert (name, start, end) == ("Nifty 50", (date(2026, 10, 20) - timedelta(days=route._NIFTY_LOOKBACK_DAYS)).isoformat(), "2026-10-21")
    last = body["points"][-1]
    assert last["inputs"]["nifty_source"] == route.NIFTY_WAREHOUSE_SOURCE
    assert (last["inputs"]["nifty_close"], last["inputs"]["nifty_average"]) == (110.0, pytest.approx(100.2))
    assert last["key"] == "bullish" and last["skipped"] == []
    assert any("warehouse" in m and "2 of 2" in m for m in body["missing"])


def test_rg4_no_trend_inputs_anywhere_means_no_regime_never_a_default(monkeypatch):
    rows = [_row("2026-10-21", 25000.0, None, 14.0)]
    c, _ = _client(monkeypatch, rows, warehouse=[])
    body = c.get("/api/macro/regime-history").json()
    [p] = body["points"]
    assert p["key"] is None and p["label"] is None and "no Nifty 50 close or 50-session average" in p["reason"]
    trend = [s for s in p["skipped"] if s["check"] == "trend"]
    assert trend and "no rows" in trend[0]["reason"]
    assert (body["unclassified"], body["complete"]) == (1, 0) and any("have no regime" in m for m in body["missing"])
    # a warehouse read that raises is named the same way, never read as an empty history
    c, _ = _client(monkeypatch, rows, warehouse=RuntimeError("down"))
    [p] = c.get("/api/macro/regime-history").json()["points"]
    assert p["key"] is None and any("could not be read (RuntimeError)" in s["reason"] for s in p["skipped"])


def test_rg5_a_failed_breadth_read_skips_the_mixed_check_for_that_session_only(monkeypatch):
    c, _ = _client(monkeypatch, breadth_fail={"2026-10-21"})
    body = c.get("/api/macro/regime-history").json()
    last = body["points"][-1]
    assert last["key"] == "bearish"                          # trend down; the mixed check could not be made
    assert last["skipped"] == [{"check": "mixed", "reason": "breadth could not be read (RuntimeError: pool gone)"}]
    assert [p["key"] for p in body["points"][:2]] == ["bullish", "high_volatility"]
    assert any("Breadth" in m and "1 of 3" in m for m in body["missing"])


def test_rg6_rows_without_a_nifty_close_are_counted_not_sessions(monkeypatch):
    c, _ = _client(monkeypatch, non_sessions=2)
    body = c.get("/api/macro/regime-history").json()
    assert body["non_session_rows"] == 2 and body["sessions"] == 3


def test_rg7_a_store_that_cannot_be_read_is_502_never_an_empty_history(monkeypatch):
    c, calls = _client(monkeypatch, fail=RuntimeError("Postgres is not reachable"))
    r = c.get("/api/macro/regime-history")
    assert (r.status_code, r.json()) == (502, {"detail": "macro_unavailable"})
    assert calls["breadth"] == []


def test_rg8_unauthenticated_is_401_and_nothing_is_read(monkeypatch):
    c, calls = _client(monkeypatch, signed_in=False)            # the real deps.get_current_user
    r = c.get("/api/macro/regime-history")
    assert (r.status_code, r.json()) == (401, {"detail": "Not authenticated"})
    assert calls == {"inputs": [], "breadth": [], "warehouse": []}


@pytest.mark.parametrize("days", [0, route.REGIME_HISTORY_MAX_DAYS + 1])
def test_rg9_days_out_of_range_is_422(monkeypatch, days):
    c, calls = _client(monkeypatch)
    assert c.get(f"/api/macro/regime-history?days={days}").status_code == 422
    assert calls["inputs"] == []


def test_an_empty_store_is_200_with_zero_sessions_and_says_what_fills_it(monkeypatch):
    c, _ = _client(monkeypatch, rows=[])
    body = c.get("/api/macro/regime-history").json()
    assert (body["sessions"], body["points"]) == (0, []) and "macro_daily has no session" in body["reason"]


def test_rg10_the_warehouse_average_is_the_same_from_a_longer_read():
    """The history reads the warehouse once for many sessions; each session must get what /today's bounded read gives."""
    session = date(2026, 10, 21)
    long_read = _closes("2026-10-21", 400, 100.0, 110.0)
    bounded = [r for r in long_read if r["as_of_date"] >= (session - timedelta(days=route._NIFTY_LOOKBACK_DAYS)).isoformat()]
    assert route.nifty_from_warehouse_rows(long_read, session) == route.nifty_from_warehouse_rows(bounded, session)
    close, avg, note = route.nifty_from_warehouse_rows(bounded, session)
    assert (close, note) == (110.0, None) and avg == pytest.approx(100.2)
    assert route.nifty_from_warehouse_rows(bounded, date(2026, 10, 24))[2].endswith("has no close for 2026-10-24")
    few = _closes("2026-10-21", 10, 100.0, 110.0)
    assert route.nifty_from_warehouse_rows(few, session)[1] is None and "only 10 of the 50" in route.nifty_from_warehouse_rows(few, session)[2]


# ── desk_regime_inputs: the stored read ──────────────────────────────────────

class _Conn:
    def __init__(self, rows, non_sessions): self.rows, self.non_sessions, self.calls = rows, non_sessions, []
    async def fetch(self, sql, *args):
        self.calls.append((" ".join(sql.split()), args))
        return self.rows
    async def fetchval(self, sql, *args):
        self.calls.append((" ".join(sql.split()), args))
        return self.non_sessions


class _Pool:
    def __init__(self, conn): self.conn = conn
    def acquire(self):
        conn = self.conn

        class _Ctx:
            async def __aenter__(self): return conn
            async def __aexit__(self, *a): return False
        return _Ctx()


def test_stored_inputs_are_read_newest_first_and_returned_oldest_first(monkeypatch):
    from decimal import Decimal
    rows = [  # as Postgres returns them, newest first (MOCK — not real data)
        {"date": date(2026, 10, 21), "nifty": Decimal("25010.5"), "india_vix": None, "nifty_50dma": Decimal("24800")},
        {"date": date(2026, 10, 20), "nifty": Decimal("24990"), "india_vix": Decimal("13.2"), "nifty_50dma": None},
    ]
    conn = _Conn(rows, 1)

    async def pool():
        return _Pool(conn)
    monkeypatch.setattr(macro_engine.pg_client, "get_pool", pool)
    got = asyncio.run(macro_engine.desk_regime_inputs(2))
    assert got == {"rows": [{"date": "2026-10-20", "nifty": 24990.0, "india_vix": 13.2, "nifty_50dma": None},
                            {"date": "2026-10-21", "nifty": 25010.5, "india_vix": None, "nifty_50dma": 24800.0}],
                   "non_session_rows": 1}
    (sql, args), (count_sql, count_args) = conn.calls
    assert "WHERE d.nifty IS NOT NULL" in sql and "LEFT JOIN macro_features" in sql and args == (2,)
    assert "nifty IS NULL" in count_sql and count_args == (date(2026, 10, 20), date(2026, 10, 21))


def test_an_unreachable_postgres_raises_instead_of_answering_empty(monkeypatch):
    async def no_pool():
        return None
    monkeypatch.setattr(macro_engine.pg_client, "get_pool", no_pool)
    with pytest.raises(RuntimeError):
        asyncio.run(macro_engine.desk_regime_inputs(5))
