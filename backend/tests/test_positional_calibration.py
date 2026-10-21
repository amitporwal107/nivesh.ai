"""Historical validation table — GET /api/positional/backtest/calibration (routes/positional.py, PRD §7.6, matrix B13).

The table is the accumulation detector's bucketed record (accumulation_calibration, written by
services/positional_engine/backtest.py::calibrate). The route now says exactly what each figure is:
  - every metric is a TOUCH outcome (an intraday high within the horizon), named per metric and never mixed;
  - avg_fwd_return is the mean maximum favourable excursion and avg_fwd_drawdown the mean maximum adverse
    excursion (highest high / lowest low over the horizon against the scan-day close) — not an average return;
  - a 95% Wilson interval for each hit rate;
  - the sample period (first / last labelled scan date) from positional_backtest_labels;
  - what is NOT measured (median return, costs, benchmark, out-of-sample), each with its reason;
  - with ?symbol=, the stock's latest accumulation score and the bucket rows it falls in.

No database: pg_client.get_pool is a recorder that answers each SQL with fixture rows — MOCK, not real data.
Worked Wilson example: 40 hits of 100, z = 1.96 → 0.3094 … 0.4980.
"""
from __future__ import annotations

import math
from datetime import date

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.positional as route


def _row(metric, lo, hi, h, n, k, ret=6.1, dd=-3.4):
    return {"metric": metric, "bucket_lo": lo, "bucket_hi": hi, "horizon_days": h, "sample_count": n, "moves_count": k,
            "probability": round(k / n, 4), "avg_fwd_return": ret, "avg_fwd_drawdown": dd, "refreshed_at": None}


ROWS = [
    _row("broke_high", 0.55, 0.65, 10, 100, 40),
    _row("broke_high", 0.65, 0.75, 10, 50, 30),
    _row("moved_scaled", 0.55, 0.65, 10, 100, 22),
    _row("moved_5pct", 0.55, 0.65, 10, 100, 31),
    _row("broke_high", 0.55, 0.65, 20, 80, 44),
]


class _Conn:
    def __init__(self, handler, calls):
        self.handler, self.calls = handler, calls

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        return self.handler(sql, args)

    async def fetchrow(self, sql, *args):
        rows = await self.fetch(sql, *args)
        return rows[0] if rows else None


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, handler, calls):
        self.conn = _Conn(handler, calls)

    def acquire(self):
        return _Acquire(self.conn)


def _handler(rows=ROWS, score=0.62, labels=True):
    def h(sql, args):
        if "FROM accumulation_calibration" in sql:
            out = list(rows)
            # the route filters in SQL: honour metric / horizon arguments the way Postgres would
            if "metric = $1" in sql:
                out = [r for r in out if r["metric"] == args[0]]
                if "horizon_days = $2" in sql:
                    out = [r for r in out if r["horizon_days"] == args[1]]
            elif "horizon_days = $1" in sql:
                out = [r for r in out if r["horizon_days"] == args[0]]
            return out
        if "FROM positional_backtest_labels" in sql:
            if not labels:
                raise RuntimeError('relation "positional_backtest_labels" does not exist')
            return [{"first_scan": date(2024, 1, 2), "last_scan": date(2026, 9, 30), "n": 41_250,
                     "versions": ["v2.1", "v2.2"]}]
        if "FROM stock_technical_features" in sql:
            return [] if score is None else [{"as_of_date": date(2026, 10, 13), "score": score}]
        raise AssertionError(f"unexpected SQL: {sql}")
    return h


def _client(monkeypatch, handler=None, pool=True):
    calls = []

    async def get_pool():
        return _Pool(handler or _handler(), calls) if pool else None

    async def fake_user(request: Request):
        return {"user_id": "u1", "email": "u1@example.com"}

    monkeypatch.setattr(route.pg_client, "get_pool", get_pool)
    monkeypatch.setattr(route, "get_current_user", fake_user)
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app), calls


def _wilson(k, n, z=1.96):
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - half, c + half


def test_wilson_worked_example():
    lo, hi = route._wilson_ci(40, 100)
    assert lo == pytest.approx(0.3094, abs=5e-5) and hi == pytest.approx(0.4980, abs=5e-5)
    assert route._wilson_ci(0, 0) == (None, None)            # no sample → no interval, never 0–0
    lo, hi = route._wilson_ci(0, 20)
    assert lo == 0.0 and 0 < hi < 0.2


def test_rows_carry_intervals_and_keep_the_old_shape(monkeypatch):
    c, _ = _client(monkeypatch)
    body = c.get("/api/positional/backtest/calibration").json()
    assert body["count"] == len(ROWS) and len(body["buckets"]) == len(ROWS)
    first = body["buckets"][0]
    for k in ("metric", "bucket_lo", "bucket_hi", "horizon_days", "sample_count", "moves_count", "probability",
              "avg_fwd_return", "avg_fwd_drawdown"):
        assert k in first                                      # the ops page reads these
    lo, hi = _wilson(40, 100)
    assert first["ci95_lo"] == pytest.approx(lo, abs=1e-4) and first["ci95_hi"] == pytest.approx(hi, abs=1e-4)


def test_outcomes_are_defined_and_never_mixed(monkeypatch):
    c, _ = _client(monkeypatch)
    body = c.get("/api/positional/backtest/calibration").json()
    m = body["metrics"]
    assert set(m) == {"broke_high", "moved_scaled", "moved_5pct"}
    for key, d in m.items():
        assert d["outcome_type"] == "touch", key               # an intraday high, not a close, not a trade
        assert d["label"] and d["rule"]
    assert "favourable" in body["measures"]["avg_fwd_return"]
    assert "adverse" in body["measures"]["avg_fwd_drawdown"]
    nm = body["not_measured"]
    for k in ("median_return", "costs", "benchmark", "out_of_sample"):
        assert nm[k]                                           # a reason, not a number
    assert body["sample"] == {"first_scan_date": "2024-01-02", "last_scan_date": "2026-09-30", "labelled_rows": 41_250,
                              "engine_versions": ["v2.1", "v2.2"]}


def test_filters(monkeypatch):
    c, calls = _client(monkeypatch)
    body = c.get("/api/positional/backtest/calibration", params={"metric": "broke_high", "horizon_days": 10}).json()
    assert {(r["metric"], r["horizon_days"]) for r in body["buckets"]} == {("broke_high", 10)}
    assert body["count"] == 2
    assert c.get("/api/positional/backtest/calibration", params={"metric": "nonsense"}).status_code == 422
    assert c.get("/api/positional/backtest/calibration", params={"horizon_days": 7}).status_code == 422


def test_symbol_finds_its_bucket(monkeypatch):
    c, calls = _client(monkeypatch, _handler(score=0.62))
    body = c.get("/api/positional/backtest/calibration", params={"symbol": "fixbrk", "horizon_days": 10}).json()
    assert body["symbol_score"] == {"symbol": "FIXBRK", "as_of_date": "2026-10-13", "accumulation_score": 0.62}
    matched = [r for r in body["buckets"] if r["matched"]]
    assert {(r["metric"], r["bucket_lo"]) for r in matched} == {("broke_high", 0.55), ("moved_scaled", 0.55), ("moved_5pct", 0.55)}
    stf = [a for s, a in calls if "FROM stock_technical_features" in s]
    assert stf and stf[0][0] == "FIXBRK"


def test_symbol_without_a_score(monkeypatch):
    c, _ = _client(monkeypatch, _handler(score=None))
    body = c.get("/api/positional/backtest/calibration", params={"symbol": "NOSCORE"}).json()
    assert body["symbol_score"] is None and body["symbol_reason"]
    assert "scripts.run_positional_engine" in body["symbol_reason"]      # names the step that fills it
    assert not any(r["matched"] for r in body["buckets"])


def test_empty_table_says_so(monkeypatch):
    c, _ = _client(monkeypatch, _handler(rows=[], labels=False))
    body = c.get("/api/positional/backtest/calibration").json()
    assert body["buckets"] == [] and body["count"] == 0
    assert body["sample"] is None and body["sample_reason"]
    assert body["empty_reason"]
    assert "stock_ohlcv" in body["empty_reason"] and "backtest/label" in body["empty_reason"]


def test_no_pool(monkeypatch):
    c, _ = _client(monkeypatch, pool=False)
    body = c.get("/api/positional/backtest/calibration").json()
    assert body["buckets"] == [] and body["_reason"] == "no_pg_pool"
