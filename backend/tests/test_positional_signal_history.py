"""AI scanner signals: the stop's method as data (N13) and versioned signals (N17). TP-3, TP-4, TP-13 and TP-14 of
test_reports/p2_trade_plan_lifecycle_TESTCASES.md.

TP-3 uses the REAL ICICIBANK 26 Oct 2026 features the guidelines gap study read from staging
(docs/ai_research/guidelines_gap_study_20261027/B_plan_lifecycle_exits.md §2b): the stored pick's stop is
1.5 x ATR below the entry, which the plan used to label "2 x ATR".

TP-13 runs the pipeline's own SQL against a REAL PostgreSQL when PG_TEST_DSN points at a throwaway database (the
report's run used postgres:16-alpine in a private docker network); without it that test is skipped, never faked.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date
from pathlib import Path

import pytest

from services.positional_engine import pipeline, trade_planner

ICICI = {"close": 1403.0, "atr_14": 25.36709576770533, "high_20d": 1411.8, "swing_low_20": 1291.0,
         "swing_high_20": 1411.8, "high_52w": 1480.0, "atr_pct": 1.81}


# ── TP-3 / TP-4: the stop's method ───────────────────────────────────────────
def test_icicibank_26_oct_stop_is_one_and_a_half_atr_and_says_so():
    p = trade_planner.plan("EARLY_BREAKOUT", ICICI)
    assert (p["entry"], p["stoploss"], p["target"]) == (1413.21, 1375.16, 1489.31)       # the stored row
    m = p["stop_method"]
    assert m["method"] == "atr" and m["atr_multiple"] == 1.5 and m["swing_ref"] == 1291.0
    assert m["distance_atr"] == 1.5 and m["measured_from"] == 1413.21
    assert "2 x" not in json.dumps(m)


def test_a_tighter_swing_low_stop_is_structural():
    f = {**ICICI, "swing_low_20": 1400.0}            # MOCK — not real data: a swing low just under the entry
    p = trade_planner.plan("EARLY_BREAKOUT", f)
    assert p["stoploss"] == round(1400.0 * 0.995, 2)
    assert p["stop_method"]["method"] == "structural" and p["stop_method"]["swing_ref"] == 1400.0
    assert p["stop_method"]["atr_multiple"] is None


def test_a_stop_from_neither_rule_is_unknown_never_guessed():
    m = trade_planner.stop_meta(1413.21, 1300.0, ICICI["atr_14"], ICICI["swing_low_20"])
    assert m["method"] == "unknown"


# ── TP-14: migration 025 not applied ─────────────────────────────────────────
class _NoHistoryConn:
    def __init__(self):
        self.sql = []

    async def fetchrow(self, sql, *a):
        return {"hist": False, "cols": 0}

    async def execute(self, sql, *args):
        self.sql.append((sql, args))
        return "INSERT 0 1"


def scored():
    p = trade_planner.plan("EARLY_BREAKOUT", ICICI)
    return {"nse_symbol": "ICICIBANK", "trade_plan": p, "reasons": ["r"],
            "scores": {"final_score": 0.71, "confidence": "MEDIUM", "stage": "EARLY_BREAKOUT", "scan_hits": []}}


def test_without_migration_025_the_old_upsert_runs_and_an_error_says_history_is_not_kept(monkeypatch, caplog):
    monkeypatch.setattr(pipeline, "_history_ready", {})
    conn = _NoHistoryConn()
    with caplog.at_level(logging.ERROR):
        asyncio.run(pipeline._write_signal(conn, date(2026, 10, 26), scored()))
    assert conn.sql[0][0] is pipeline.LEGACY_SIGNAL_SQL
    assert any("migration 025" in r.message and r.levelno == logging.ERROR for r in caplog.records)


# ── TP-13: a re-run is versioned (real PostgreSQL) ───────────────────────────
DSN = os.environ.get("PG_TEST_DSN")
MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def _ddl(table: str) -> str:
    text = (MIGRATIONS / "015_positional_engine.sql").read_text()
    start = text.index(f"CREATE TABLE IF NOT EXISTS {table} (")
    return text[start:text.index(");", start) + 2]


@pytest.mark.skipif(not DSN, reason="PG_TEST_DSN not set: needs a throwaway PostgreSQL")
def test_a_rerun_with_new_levels_keeps_the_old_row_and_an_identical_rerun_writes_nothing(monkeypatch):
    import asyncpg

    async def run():
        conn = await asyncpg.connect(DSN)
        try:
            await conn.execute("DROP TABLE IF EXISTS positional_signals_history; DROP TABLE IF EXISTS positional_signals; "
                               "DROP TABLE IF EXISTS stock_technical_features")
            await conn.execute(_ddl("positional_signals"))
            await conn.execute(_ddl("stock_technical_features"))
            await conn.execute((MIGRATIONS / "025_positional_signals_history.sql").read_text())
            monkeypatch.setattr(pipeline, "_history_ready", {})
            day = date(2026, 10, 26)
            first = scored()
            await pipeline._write_signal(conn, day, first)
            await pipeline._write_signal(conn, day, first)                      # identical re-run
            r1 = await conn.fetchrow("SELECT revision, stoploss, stop_method FROM positional_signals")
            n1 = await conn.fetchval("SELECT COUNT(*) FROM positional_signals_history")
            second = scored()
            second["trade_plan"] = {**second["trade_plan"], "stoploss": 1380.0}   # MOCK — a re-run that moved the stop
            await pipeline._write_signal(conn, day, second)
            r2 = await conn.fetchrow("SELECT revision, stoploss FROM positional_signals")
            hist = await conn.fetch("SELECT revision, stoploss, superseded_by FROM positional_signals_history")
            await pipeline.write_scored(conn, day, [], replace=True)          # a day rewrite keeps what it deletes
            after = await conn.fetch("SELECT revision, stoploss, superseded_by FROM positional_signals_history ORDER BY revision")
            return r1, n1, r2, hist, after
        finally:
            await conn.close()

    r1, n1, r2, hist, after = asyncio.run(run())
    assert r1["revision"] == 1 and float(r1["stoploss"]) == 1375.16 and json.loads(r1["stop_method"])["method"] == "atr"
    assert n1 == 0                                                              # the identical re-run kept nothing
    assert r2["revision"] == 2 and float(r2["stoploss"]) == 1380.0
    assert [(h["revision"], float(h["stoploss"]), h["superseded_by"]) for h in hist] == [(1, 1375.16, "rerun")]
    assert [(h["revision"], float(h["stoploss"]), h["superseded_by"]) for h in after] == [(1, 1375.16, "rerun"), (2, 1380.0, "replace")]
