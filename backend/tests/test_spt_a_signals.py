"""SPT slice A — normalizer, ingest and the scan hook (test cases test_reports/spt_a_TESTCASES.md SPT-A-01 … SPT-A-14).

Covers services/spt/signals/{normalize,clock,ingest,store,hook}.py and the hand-off in services/scan_builder/signals.py.
No network and no real database: Mongo is tests/spt_a_fakes.DB, the scan's Redis is scan_builder.signals.LocalSignalStore.

MOCK — not real data: every symbol and price built with spt_a_fakes.mark / strong. The records in
tests/fixtures/spt_a_signals_20261104.json are copied from the 4 Nov 2026 Redis dump (market-wide scanner output).
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from services.scan_builder import market_dashboard as MD
from services.scan_builder import signal_strength as SS
from services.scan_builder import signals as SIG
from services.spt import constants as C
from services.spt.signals import clock, hook, ingest, normalize
from services.spt.signals import store as sig_store
from tests.spt_a_fakes import DAY, DB, D, events_of, ist, mark, reset_module_state, strong

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "spt_a_signals_20261104.json").read_text())
NOW = ist(10, 0, 30)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    reset_module_state()
    SIG._seen.clear()
    SIG._seen_strong.clear()
    for k in ("SPT_INGEST_ENABLED", "APP_ENV", "SPT_POSITIONAL_WINDOW_SESSIONS", "SPT_INGEST_DELAY_S"):
        monkeypatch.delenv(k, raising=False)
    yield
    SIG._seen.clear()
    SIG._seen_strong.clear()


# ── SPT-A-01 … 04: the normalizer ────────────────────────────────────────────────────────────────────────────────────

def recordable_ids():
    """Every widget id whose rows are stocks, on every dashboard (what signals.record can ever store)."""
    out = set()
    for key, board in MD.DASHBOARDS.items():
        for w in board.widgets:
            if MD.ROW_KIND[w.kind] == "symbol":
                out.add(w.id)
    return out


def test_SPT_A_01_every_recordable_list_on_every_dashboard_is_mapped():
    ids = recordable_ids()
    assert {"n50_gainers", "dt_breakout_15m", "early_movers"} <= ids and len(ids) >= 35
    missing = sorted(ids - set(normalize.LIST_MAP))
    assert not missing, f"widget ids the dashboards can record but LIST_MAP does not map: {missing}"
    for wid, spec in normalize.LIST_MAP.items():
        assert spec["category"] in normalize.CATEGORIES, wid
        assert spec["timeframe"] in normalize.TIMEFRAMES, wid
        assert spec["horizon"] in normalize.HORIZONS, wid
        assert spec["direction"] in normalize.DIRECTIONS, wid
        assert spec["family"] and spec["family"] != normalize.STRONG_FAMILY, wid


def test_SPT_A_02_horizons_positional_lists_and_intraday_only_lists():
    for wid in SS.POSITIONAL_LISTS:
        assert normalize.LIST_MAP[wid]["horizon"] == "positional", wid
    for wid in ("dt_breakout_15m", "dt_rsi_vwap", "vol_10x_5min", "dt_vol_10x_5min", "early_movers", "strong_movers",
                "n50_gainers", "dt_explosive"):
        assert normalize.LIST_MAP[wid]["horizon"] == "intraday", wid
    # the same test, two copies: one family (a stock in both is ONE confirmation)
    assert normalize.LIST_MAP["vol_10x_5min"]["family"] == normalize.LIST_MAP["dt_vol_10x_5min"]["family"]
    assert normalize.families_of(["dt_52w_high", "dt_52w_breakout", "cup_handle", "nope"]) == ["high_52w_breakout",
                                                                                                "cup_and_handle"]


def test_SPT_A_03_direction_rules():
    assert SIG.SHORT_WIDGETS == {"open_interest", "oi_7"}
    for wid in SIG.SHORT_WIDGETS:
        assert normalize.for_list(wid, "short")["direction"] == "short"
        assert normalize.for_list(wid, "short")["bias"] == "bearish"
        assert normalize.for_list(wid, "long")["direction"] == "long"
    for wid in ("dt_below_dma", "dt_down10_large", "dt_down10_all"):
        n = normalize.for_list(wid, "long")                       # the scan records these as long; they are bearish lists
        assert (n["direction"], n["bias"], n["category"]) == ("short", "bearish", "breakdown"), wid
    assert normalize.for_list("dt_52w_high", "short")["direction"] == "long"      # only SHORT_WIDGETS take the mark's side
    assert normalize.for_list("no_such_list")["mapped"] is False


def test_SPT_A_04_strong_signal_is_its_own_scanner_with_the_category_of_its_lists():
    rec = strong("AAA", ist(11, 0), lists=["dt_rsi_vwap", "long_buildup", "dt_52w_high"])
    n = normalize.for_strong(rec)
    assert (n["mapped"], n["family"], n["horizon"], n["direction"], n["timeframe"]) == (True, "signal_strength",
                                                                                         "positional", "long", "1D")
    assert n["category"] == "derivatives"                    # long_buildup: the first POSITIONAL list wins over dt_rsi_vwap
    assert normalize.for_strong(strong("AAA", ist(11, 0), lists=["dt_rsi_vwap"]))["category"] == "momentum"
    assert normalize.for_strong(strong("AAA", ist(11, 0), lists=["unknown"]))["mapped"] is False
    assert normalize.SCORE_VERSION == "signal-strength:t70:q30-t25-r20-s15-p10"


# ── SPT-A-05 … 12: ingest ────────────────────────────────────────────────────────────────────────────────────────────

def test_SPT_A_05_a_list_mark_becomes_the_prd_event_with_its_original_identity():
    db = DB()
    m = mark("dt_52w_high", "AAA", ist(9, 40, 5), 512.35, title="52 week high stocks")
    c = run(ingest.ingest(db, day=DAY, marks=[m], now=NOW))
    assert (c["inserted"], c["normalized"], c["quarantined"]) == (1, 1, 0)
    doc = db["spt_signal_events"].docs[0]
    assert doc["_id"] == doc["signal_id"] == "sig:2026-11-04:dt_52w_high:AAA"
    want = {"scanner_id": "dt_52w_high", "scanner_name": "52 week high stocks", "instrument_id": "AAA", "symbol": "AAA",
            "exchange": "NSE", "segment": "Equity", "direction": "long", "bias": "bullish", "timeframe": "1D",
            "horizon": "positional", "category": "breakout", "signal_type": "breakout", "family": "high_52w_breakout",
            "detected_at": "2026-11-04T04:10:05+00:00", "detected_price": 512.35, "market_regime": None,
            "status": "normalized", "quarantine_reasons": [], "normalizer_version": C.NORMALIZER_VERSION, "kind": "list",
            "day": DAY, "outcome_eligible": True, "received_at": NOW.astimezone(timezone.utc).isoformat()}
    assert {k: doc[k] for k in want} == want
    assert doc["supporting_metrics"] == m                               # the raw mark, untouched
    assert doc["expiry_at"] == "2026-11-11T10:01:00+00:00"              # Wed + 5 sessions = next Wed, 15:31 IST
    assert doc["source"]["key"] == "nivesh:sb:signals:2026-11-04:s:dt_52w_high:AAA"
    assert doc["market_regime_note"]


def test_SPT_A_06_scanner_score_only_when_the_scores_doc_is_at_the_detection():
    det = ist(9, 40, 5)
    m = mark("dt_52w_high", "AAA", det, 512.35)
    near = {"as_of": (det + timedelta(seconds=20)).isoformat(), "scores": {"AAA": {"score": 64}}}
    late = {"as_of": ist(22, 45).isoformat(), "scores": {"AAA": {"score": 81}}}
    e1 = ingest.list_event(m, day=DAY, scores_doc=near, now=NOW)
    assert (e1["scanner_score"], e1["score_version"], e1["scanner_score_note"]) == (64, normalize.SCORE_VERSION, None)
    assert e1["score_as_of"] == "2026-11-04T04:10:25+00:00"
    e2 = ingest.list_event(m, day=DAY, scores_doc=late, now=NOW)
    assert e2["scanner_score"] is None and e2["score_version"] is None and "not the score at detection" in e2["scanner_score_note"]
    e3 = ingest.list_event(m, day=DAY, scores_doc={"as_of": near["as_of"], "scores": {"AAA": {"score": None,
                                                                                               "note": "Not scored: an ETF"}}},
                           now=NOW)
    assert e3["scanner_score"] is None and "an ETF" in e3["scanner_score_note"]
    assert ingest.list_event(m, day=DAY, scores_doc=None, now=NOW)["scanner_score"] is None
    s = ingest.strong_event(strong("AAA", ist(11, 0), score=77), day=DAY, now=NOW)
    assert (s["scanner_score"], s["scanner_id"], s["_id"]) == (77, "strength_70", "sig:2026-11-04:strong:AAA")


def test_SPT_A_07_duplicate_delivery_is_a_no_op():
    db = DB()
    m = mark("cup_handle", "AAA", ist(9, 40), 100.0)
    first = run(ingest.ingest(db, day=DAY, marks=[m], strong=[strong("AAA", ist(9, 45))], now=NOW))
    writes = db.writes
    again = run(ingest.ingest(db, day=DAY, marks=[m], strong=[strong("AAA", ist(9, 45))], now=NOW + timedelta(seconds=30),
                              via="catch_up"))
    assert (first["inserted"], again["inserted"], again["duplicate"]) == (2, 0, 2)
    assert len(db["spt_signal_events"].docs) == 2 and db.writes == writes
    assert len(events_of(db, "SCANNER_SIGNAL_RECEIVED")) == 2 and len(events_of(db, "SCANNER_SIGNAL_NORMALIZED")) == 2


@pytest.mark.parametrize("make, reason", [
    (lambda: mark("not_a_list", "AAA", ist(10, 0)), "missing_mapping"),
    (lambda: mark("cup_handle", "aaa bad", ist(10, 0)), "invalid_symbol"),
    (lambda: mark("cup_handle", "AAA", ist(10, 0), None), "missing_price"),
    (lambda: mark("cup_handle", "AAA", ist(10, 0), -3), "missing_price"),
    (lambda: {**mark("cup_handle", "AAA", ist(10, 0)), "first_seen": "2026-11-04T10:00:00"}, "invalid_timestamp"),
    (lambda: {**mark("cup_handle", "AAA", ist(10, 0)), "first_seen": "yesterday"}, "invalid_timestamp"),
    (lambda: mark("cup_handle", "AAA", ist(10, 0, day=D - timedelta(days=1))), "invalid_timestamp"),   # not the record's day
    (lambda: mark("cup_handle", "AAA", ist(9, 5)), "outside_session"),
    (lambda: mark("cup_handle", "AAA", ist(15, 45)), "outside_session"),
])
def test_SPT_A_08_quarantined_events_are_stored_with_their_reason(make, reason):
    db = DB()
    c = run(ingest.ingest(db, day=DAY, marks=[make()], now=NOW))
    assert (c["inserted"], c["quarantined"], c["normalized"]) == (1, 1, 0)
    doc = db["spt_signal_events"].docs[0]
    assert doc["status"] == "quarantined" and reason in doc["quarantine_reasons"] and doc["explanations"]
    assert len(events_of(db, "SCANNER_SIGNAL_RECEIVED")) == 1 and not events_of(db, "SCANNER_SIGNAL_NORMALIZED")
    assert events_of(db, "SCANNER_SIGNAL_RECEIVED")[0]["payload"]["quarantine_reasons"] == doc["quarantine_reasons"]
    assert doc["outcome_eligible"] is (reason not in ("invalid_symbol", "missing_price", "invalid_timestamp"))


def test_SPT_A_08b_a_mark_in_the_last_session_minute_is_in_session():
    db = DB()
    run(ingest.ingest(db, day=DAY, marks=[mark("dt_breakout_15m", "AAA", ist(15, 30, 40))], now=ist(15, 30, 41)))
    assert db["spt_signal_events"].docs[0]["status"] == "normalized"


def test_SPT_A_09_an_expired_signal_received_late_is_quarantined_stale():
    db = DB()
    late_intraday = mark("dt_breakout_15m", "AAA", ist(10, 0))            # window: that day until 15:31 IST
    on_time_positional = mark("cup_handle", "BBB", ist(10, 0))            # window: until next Wednesday
    next_day = ist(9, 30, day=D + timedelta(days=1))
    c = run(ingest.ingest(db, day=DAY, marks=[late_intraday, on_time_positional], now=next_day, via="backfill"))
    by = {d["symbol"]: d for d in db["spt_signal_events"].docs}
    assert by["AAA"]["status"] == "quarantined" and by["AAA"]["quarantine_reasons"] == ["stale"]
    assert by["AAA"]["outcome_eligible"] is True                          # a late signal is still a real observation
    assert by["BBB"]["status"] == "normalized"
    assert c["reasons"] == {"stale": 1}
    much_later = ist(9, 30, day=D + timedelta(days=8))
    assert ingest.list_event(on_time_positional, day=DAY, scores_doc=None, now=much_later)["quarantine_reasons"] == ["stale"]


def test_SPT_A_10_original_score_and_timestamp_are_never_overwritten():
    db = DB()
    det = ist(9, 40)
    m = mark("cup_handle", "AAA", det, 100.0)
    run(ingest.ingest(db, day=DAY, marks=[m], scores_doc={"as_of": det.isoformat(), "scores": {"AAA": {"score": 61}}},
                      now=NOW))
    before = json.dumps(db["spt_signal_events"].docs[0], sort_keys=True, default=str)
    changed = {**m, "first_seen": ist(11, 0).isoformat(), "entry": 120.0}
    run(ingest.ingest(db, day=DAY, marks=[changed], scores_doc={"as_of": ist(11, 0).isoformat(),
                                                                 "scores": {"AAA": {"score": 90}}}, now=ist(11, 1)))
    assert json.dumps(db["spt_signal_events"].docs[0], sort_keys=True, default=str) == before
    assert db["spt_signal_events"].docs[0]["scanner_score"] == 61


def test_SPT_A_11_events_carry_the_envelope_and_stable_keys():
    db = DB()
    run(ingest.ingest(db, day=DAY, marks=[mark("cup_handle", "AAA", ist(9, 40))], now=NOW))
    rec, norm = events_of(db, "SCANNER_SIGNAL_RECEIVED")[0], events_of(db, "SCANNER_SIGNAL_NORMALIZED")[0]
    sid = "sig:2026-11-04:cup_handle:AAA"
    assert rec["idempotency_key"] == f"sig:{sid}:received" and norm["idempotency_key"] == f"sig:{sid}:normalized"
    for e in (rec, norm):
        assert set(e) >= {"event_id", "event_type", "event_version", "occurred_at", "ingested_at", "correlation_id",
                          "account_id", "instrument_id", "source_service", "idempotency_key", "payload"}
        assert e["instrument_id"] == "AAA" and e["account_id"] is None and e["correlation_id"] == sid
    assert norm["payload"]["horizon"] == "positional" and norm["payload"]["normalizer_version"] == C.NORMALIZER_VERSION


def test_SPT_A_12_real_4_nov_marks_normalize():
    """Records copied from the 4 Nov dump: list marks of 9 widgets and the HDFCAMC / VINCOFE strong signals."""
    db = DB()
    on_the_day = ist(15, 35)
    c = run(ingest.ingest(db, day=FIXTURE["day"], marks=FIXTURE["marks"], strong=FIXTURE["strong"],
                          scores_doc=FIXTURE["scores_doc"], now=on_the_day, via="backfill"))
    assert c["inserted"] == len(FIXTURE["marks"]) + len(FIXTURE["strong"]) == 16
    by = {d["_id"]: d for d in db["spt_signal_events"].docs}
    mcx = by["sig:2026-11-04:open_interest:MCX"]
    assert (mcx["direction"], mcx["category"], mcx["detected_price"]) == ("short", "derivatives", 3313.6)
    tata = by["sig:2026-11-04:dt_breakout_15m:TATAELXSI"]
    assert (tata["horizon"], tata["timeframe"], tata["status"]) == ("intraday", "15m", "quarantined")
    assert tata["quarantine_reasons"] == ["stale"]                      # an intraday mark read after the close
    hd = by["sig:2026-11-04:strong:HDFCAMC"]
    assert (hd["scanner_score"], hd["category"], hd["detected_at"]) == (78, "derivatives", "2026-11-04T09:32:49+00:00")
    assert hd["supporting_metrics"]["stop_loss"] == 2376.28
    # the day's final scores doc is as of 22:45 IST: no list mark gets it as its score at detection
    assert all(d["scanner_score"] is None for d in by.values() if d["kind"] == "list")
    ofss = by["sig:2026-11-04:long_buildup:OFSS"]
    assert ofss["supporting_metrics"]["rules"] == "scan-plan-v2" and ofss["supporting_metrics"]["stop_basis"] == "Entry − 1 %"
    assert ofss["status"] == "normalized" and ofss["timeframe"] == "1h"


# ── SPT-A-13 … 14: the hook and the catch-up ─────────────────────────────────────────────────────────────────────────

def W(wid, syms):
    return {"id": wid, "title": wid, "row_kind": "symbol", "status": "ok", "rows": [[s, 1.0, 100.0, 1000] for s in syms],
            "criteria": [{"applied": True}]}


def inputs_for(syms):
    return {s: {"close": 100.0, "low": 99.0, "high": 101.0, "atr": 2.0, "chg": 1.0} for s in syms}


def test_SPT_A_13_flag():
    assert hook.enabled({"APP_ENV": "staging"}) and not hook.enabled({"APP_ENV": "staging", "SPT_INGEST_ENABLED": "0"})
    assert hook.enabled({"SPT_INGEST_ENABLED": "1"}) and not hook.enabled({}) and not hook.enabled({"APP_ENV": "prod"})


def test_SPT_A_13_record_hands_new_marks_to_ingest_without_blocking(monkeypatch):
    monkeypatch.setenv("SPT_INGEST_ENABLED", "1")
    monkeypatch.setenv("SPT_INGEST_DELAY_S", "0")
    db = DB()
    monkeypatch.setattr(hook, "_db", lambda: db)
    store = SIG.LocalSignalStore()

    async def go():
        got = await SIG.record([W("cup_handle", ["AAA", "BBB"])], inputs_for, ist(10, 0), store=store)
        assert [g["symbol"] for g in got] == ["AAA", "BBB"]
        assert not db["spt_signal_events"].docs                     # scheduled, not awaited by the scan loop
        await asyncio.gather(*list(hook._tasks))
        again = await SIG.record([W("cup_handle", ["AAA"])], inputs_for, ist(10, 1), store=store)
        assert again == [] and not hook._tasks                       # nothing new → nothing scheduled
        st = await SIG.record_strong([strong("AAA", ist(10, 2))], ist(10, 2), store=store)
        assert len(st) == 1
        await asyncio.gather(*list(hook._tasks))
        return got

    run(go())
    ids = sorted(d["_id"] for d in db["spt_signal_events"].docs)
    assert ids == ["sig:2026-11-04:cup_handle:AAA", "sig:2026-11-04:cup_handle:BBB", "sig:2026-11-04:strong:AAA"]
    assert {d["source"]["via"] for d in db["spt_signal_events"].docs} == {"hook"}


def test_SPT_A_13_an_ingest_failure_is_logged_and_never_reaches_the_scan_loop(monkeypatch, caplog):
    monkeypatch.setenv("SPT_INGEST_ENABLED", "1")
    monkeypatch.setenv("SPT_INGEST_DELAY_S", "0")

    class Broken:
        def __getitem__(self, name):
            raise RuntimeError("mongo down")

    monkeypatch.setattr(hook, "_db", lambda: Broken())
    store = SIG.LocalSignalStore()

    async def go():
        got = await SIG.record([W("cup_handle", ["AAA"])], inputs_for, ist(10, 0), store=store)
        await asyncio.gather(*list(hook._tasks), return_exceptions=True)
        await asyncio.sleep(0)
        return got

    with caplog.at_level(logging.WARNING):
        got = run(go())
    assert [g["symbol"] for g in got] == ["AAA"]
    assert "spt ingest" in caplog.text


def test_SPT_A_13_the_hook_is_off_by_default(monkeypatch):
    called = []
    monkeypatch.setattr(hook, "_run", lambda *a, **k: called.append(a))
    store = SIG.LocalSignalStore()
    run(SIG.record([W("cup_handle", ["AAA"])], inputs_for, ist(10, 0), store=store))
    assert called == [] and not hook._tasks


def test_SPT_A_14_catch_up_ingests_what_the_hook_missed_and_is_idempotent():
    db = DB()
    store = SIG.LocalSignalStore()

    async def go():
        await SIG.record([W("cup_handle", ["AAA", "BBB"]), W("dt_52w_high", ["AAA"])], inputs_for, ist(10, 0), store=store)
        await SIG.record_strong([strong("AAA", ist(10, 0))], ist(10, 0), store=store)
        await SIG.save_scores(DAY, {"AAA": {"score": 72}, "BBB": {"score": 40}}, ist(10, 0, 10), store=store)
        await ingest.ingest(db, day=DAY, marks=[mark("cup_handle", "AAA", ist(10, 0))], now=NOW)      # the hook got one
        first = await hook.catch_up(db, DAY, scan_store=store, now=NOW)
        second = await hook.catch_up(db, DAY, scan_store=store, now=NOW + timedelta(seconds=30))
        hook._known.clear()                                           # a restarted worker knows nothing
        third = await hook.catch_up(db, DAY, scan_store=store, now=NOW + timedelta(seconds=60))
        return first, second, third

    first, second, third = run(go())
    assert first["read"] == 4 and first["inserted"] == 3
    assert second["inserted"] == 0 and second["seen"] == 0              # known ids are not rebuilt
    assert third["inserted"] == 0 and third["seen"] == 0
    by = {d["_id"]: d for d in db["spt_signal_events"].docs}
    assert by["sig:2026-11-04:dt_52w_high:AAA"]["scanner_score"] == 72   # scores doc 10 s after the detection
    assert by["sig:2026-11-04:dt_52w_high:AAA"]["source"]["via"] == "catch_up"
    assert len(by) == 4


def test_clock_windows():
    assert clock.add_sessions(D, 5).isoformat() == "2026-11-11"
    assert clock.add_sessions(D + timedelta(days=2), 1).isoformat() == "2026-11-09"     # Fri → Mon
    assert clock.sessions_between(D, D + timedelta(days=7)) == 5
    assert clock.window_until(D, "intraday", 5) == datetime(2026, 11, 4, 15, 31, tzinfo=clock.IST)
    assert clock.window_sessions({"SPT_POSITIONAL_WINDOW_SESSIONS": "3"}) == 3
    assert clock.window_sessions({"SPT_POSITIONAL_WINDOW_SESSIONS": "x"}) == 5
