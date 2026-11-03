"""Smart trading desk fields on GET /api/positional/picks and /api/positional/watchlist rows (routes/positional.py):
spark_closes, spark_end, avg_traded_value_cr_20d (both) and resistance_level / support_level (watchlist).

No database: `pg_client.get_pool` is replaced with a recorder that answers each SQL with fixture rows — MOCK, not
real data — and fails any read of stock_ohlcv that names a column the table does not have (the table's columns are
nse_symbol, bar_date, open_price, high_price, low_price, close_price, volume, delivery_qty, delivery_pct, source,
ingested_at — migrations/015_positional_engine.sql and the staging schema). The stock_ohlcv tables are empty on
staging, so the real figures cannot be shown there yet.

Worked example (FLAT): 40 daily bars, close_i = 90 + 0.25 i (i = 0..39), volume 1,000,000 except the last three at
5,000,000. Last 24 closes (i = 16..39): 94.00 … 99.75. Average traded value over the last 20 sessions (i = 20..39):
    Σ_{i=20}^{36} close_i = 17 × 90 + 0.25 × (20 + … + 36) = 1530 + 0.25 × 476 = 1649      → × 1e6 = 1,649,000,000
    last three closes 99.25 + 99.50 + 99.75 = 298.5                                       → × 5e6 = 1,492,500,000
    (1,649,000,000 + 1,492,500,000) / 20 = 157,075,000 ₹ = 15.7075 crore                   → 15.71
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.positional as route

OHLCV_COLUMNS = {"nse_symbol", "bar_date", "open_price", "high_price", "low_price", "close_price", "volume",
                 "delivery_qty", "delivery_pct", "source", "ingested_at"}
DAY = date(2026, 10, 13)


def _bars(n: int, last: date = DAY, close0: float = 90.0, step: float = 0.25, spike_last: int = 3):
    rows = []
    for i in range(n):
        rows.append({"bar_date": last - timedelta(days=n - 1 - i), "close_price": close0 + step * i,
                     "volume": 5_000_000 if i >= n - spike_last else 1_000_000})
    return rows


FLAT = _bars(40)
EXPECTED_ATV = 15.71   # hand-worked in the module docstring


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


def _check_ohlcv_columns(sql: str):
    """Fail like Postgres would if a stock_ohlcv read names a column the table does not have."""
    select = sql.split("FROM stock_ohlcv")[0]
    select = select[select.rfind("SELECT") + len("SELECT"):]
    for part in select.split(","):
        col = re.split(r"\s+AS\s+", part.strip(), flags=re.I)[0].strip()
        if re.fullmatch(r"[a-z_]+", col) and col not in OHLCV_COLUMNS:   # bare column names; expressions pass
            raise RuntimeError(f'column "{col}" does not exist')


def _client(monkeypatch, handler):
    calls: List[tuple] = []

    async def get_pool():
        return _Pool(handler, calls)

    async def fake_user(request: Request):
        return {"user_id": "u1", "email": "u1@example.com"}

    monkeypatch.setattr(route.pg_client, "get_pool", get_pool)
    monkeypatch.setattr(route, "get_current_user", fake_user)
    # §4d results signal: none in these route tests (its own tests are in tests/test_results_week.py)
    async def no_results_signal(*a, **kw):
        return {}, None
    monkeypatch.setattr(route.results_signal, "current", no_results_signal)
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app), calls


def _ohlcv_calls(calls):
    return [c for c in calls if "FROM stock_ohlcv" in c[0]]


# ── pure helper ──────────────────────────────────────────────────────────────

def test_bar_fields_worked_example():
    f = route._bar_fields([(b["bar_date"], b["close_price"], b["volume"]) for b in FLAT])
    assert f["spark_closes"] == [94.0 + 0.25 * i for i in range(24)]          # oldest first, 24 closes
    assert f["spark_end"] == "2026-10-13"
    assert f["avg_traded_value_cr_20d"] == EXPECTED_ATV


def test_bar_fields_short_or_missing_history():
    short = [(b["bar_date"], b["close_price"], b["volume"]) for b in FLAT[-10:]]
    f = route._bar_fields(short)
    assert len(f["spark_closes"]) == 10 and f["avg_traded_value_cr_20d"] is None   # < 20 sessions → null, not 0
    gap = [(d, c, None if i == 30 else v) for i, (d, c, v) in
           enumerate((b["bar_date"], b["close_price"], b["volume"]) for b in FLAT)]
    assert route._bar_fields(gap)["avg_traded_value_cr_20d"] is None               # a missing volume → null
    assert route._bar_fields([]) == {"spark_closes": [], "spark_end": None, "avg_traded_value_cr_20d": None}
    assert route._bar_fields(None) == {"spark_closes": None, "spark_end": None, "avg_traded_value_cr_20d": None}


# ── GET /api/positional/picks ────────────────────────────────────────────────

PICK_BARS = {"AAA": [dict(b, nse_symbol="AAA") for b in FLAT],
             "BBB": [dict(b, nse_symbol="BBB") for b in FLAT[-10:]]}


def _pick(sym):
    return {"nse_symbol": sym, "signal_date": DAY, "final_score": 0.8, "confidence": "HIGH", "stage": "BREAKOUT",
            "timeframe_days_min": 5, "timeframe_days_max": 20, "entry_price": 100.0, "stoploss": 95.0,
            "target_price": 110.0, "risk_reward": 2.0, "source_scans": [], "reasons": [],
            "pre_breakout": None, "features_raw": None}


def _picks_handler(fail_ohlcv=False):
    def handler(sql, args):
        if "MAX(signal_date)" in sql:
            return [{"d": DAY}]
        if "FROM positional_signals ps" in sql:
            return [_pick("AAA"), _pick("BBB"), _pick("CCC")]
        if "FROM stock_ohlcv" in sql:
            if fail_ohlcv:
                raise RuntimeError("connection reset")
            _check_ohlcv_columns(sql)
            symbols, through, n = args
            out = []
            for s in symbols:   # emulate: bars up to `through`, newest n per symbol, returned oldest first
                rows = [r for r in PICK_BARS.get(s, []) if r["bar_date"] <= through]
                out += rows[-n:]
            return out
        raise AssertionError(sql)
    return handler


def test_picks_rows_carry_spark_and_traded_value_from_one_batched_query(monkeypatch):
    c, calls = _client(monkeypatch, _picks_handler())
    r = c.get("/api/positional/picks")
    assert r.status_code == 200, r.text
    picks = {p["nse_symbol"]: p for p in r.json()["picks"]}
    ohlcv = _ohlcv_calls(calls)
    assert len(ohlcv) == 1                                         # one read for every row, not one per row
    assert ohlcv[0][1] == (["AAA", "BBB", "CCC"], DAY, 24)
    a, b, cc = picks["AAA"], picks["BBB"], picks["CCC"]
    assert a["spark_closes"] == [94.0 + 0.25 * i for i in range(24)] and a["spark_end"] == "2026-10-13"
    assert a["avg_traded_value_cr_20d"] == EXPECTED_ATV
    assert len(b["spark_closes"]) == 10 and b["avg_traded_value_cr_20d"] is None
    assert cc["spark_closes"] == [] and cc["spark_end"] is None and cc["avg_traded_value_cr_20d"] is None
    assert a["entry_price"] == 100.0 and a["stoploss"] == 95.0     # existing fields untouched


def test_picks_still_answer_when_the_bar_read_fails(monkeypatch):
    c, _ = _client(monkeypatch, _picks_handler(fail_ohlcv=True))
    r = c.get("/api/positional/picks")
    assert r.status_code == 200
    for p in r.json()["picks"]:
        assert p["spark_closes"] is None and p["avg_traded_value_cr_20d"] is None


# ── GET /api/positional/watchlist ────────────────────────────────────────────

def _candidate():
    # close 99.75 just above a 99.00 breakout on 3.1× volume (3-day 5e6 vs 20-day 1.6e6) → breakout_confirmed
    return {"nse_symbol": "AAA", "stage": "BREAKOUT", "confidence": "HIGH", "final_score": 0.9,
            "close_price": 99.75, "sma_50": 95.0, "sma_200": 90.0, "rsi_14": 62.0, "atr_14": 2.0,
            "breakout_level": 99.0, "support_level": 96.5, "resistance_level": 99.0, "sector": "IT"}


def _watch_handler(sql, args):
    if "MAX(as_of_date)" in sql:
        return [{"d": DAY}]
    if "FROM stock_technical_features stf" in sql:
        return [_candidate()]
    if "FROM stock_ohlcv" in sql:
        _check_ohlcv_columns(sql)
        out = []
        for b in FLAT:
            out.append({"nse_symbol": "AAA", "bar_date": b["bar_date"], "open": b["close_price"],
                        "high": b["close_price"] + 0.1, "low": b["close_price"] - 0.1, "close": b["close_price"],
                        "volume": b["volume"], "delivery_qty": None, "delivery_pct": None})
        return out
    raise AssertionError(sql)


def test_watchlist_rows_carry_levels_spark_and_traded_value(monkeypatch):
    c, calls = _client(monkeypatch, _watch_handler)
    r = c.get("/api/positional/watchlist")
    assert r.status_code == 200, r.text
    d = r.json()
    assert "_reason" not in d, d                                   # the stock_ohlcv read names real columns
    rows = [row for bucket in d["buckets"].values() for row in bucket]
    assert [row["nse_symbol"] for row in rows] == ["AAA"]
    row = rows[0]
    assert row in d["buckets"]["breakout_confirmed"]
    assert (row["resistance_level"], row["support_level"]) == (99.0, 96.5)
    assert row["spark_closes"] == [94.0 + 0.25 * i for i in range(24)] and row["spark_end"] == "2026-10-13"
    assert row["avg_traded_value_cr_20d"] == EXPECTED_ATV
    assert row["trigger_price"] == 99.0 and row["close_price"] == 99.75   # existing fields untouched
    assert len(_ohlcv_calls(calls)) == 1


def test_original_watchlist_columns_would_fail_on_the_real_table():
    """Guard for the column check itself: the pre-fix SELECT named open/high/low/close, which stock_ohlcv lacks."""
    with pytest.raises(RuntimeError, match='column "open" does not exist'):
        _check_ohlcv_columns("SELECT nse_symbol, bar_date, open, high, low, close, volume FROM stock_ohlcv")
