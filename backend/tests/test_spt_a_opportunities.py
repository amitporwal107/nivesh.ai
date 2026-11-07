"""SPT slice A — consolidation, the opportunity store, validation, expiry and the loop (test cases
test_reports/spt_a_TESTCASES.md SPT-A-15 … SPT-A-31).

Covers services/spt/opportunities/{store,consolidate,validate,inputs,runner}.py. No network and no real database: Mongo is
tests/spt_a_fakes.DB, the market data is spt_a_fakes.Inputs (bars and regime from dicts), the scan's Redis is
scan_builder.signals.LocalSignalStore.

MOCK — not real data: every symbol, price, bar and regime below is made up. Expected figures are worked out in the tests.
"""
from __future__ import annotations

import asyncio
import copy
from datetime import date, datetime, timedelta, timezone

import pytest

from services.scan_builder import signals as SIG
from services.spt import constants as C
from services.spt.opportunities import consolidate as cons
from services.spt.opportunities import runner
from services.spt.opportunities import store
from services.spt.opportunities import validate as val
from services.spt.signals import clock, ingest
from tests.spt_a_fakes import (DAY, DB, D, REGIME_BULL, Inputs, bars_from, events_of, ist, mark, reset_module_state,
                               rising, strong)

NOW = ist(10, 0, 30)
PREV = date(2026, 11, 3)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    reset_module_state()
    runner._mem.update(first_round=True, received_since=None)
    for k in ("SPT_POSITIONAL_WINDOW_SESSIONS", "SPT_MIN_ADV_RS", "SPT_A_ENABLED", "APP_ENV"):
        monkeypatch.delenv(k, raising=False)
    yield


async def load(db, marks=(), strongs=(), now=NOW, day=DAY):
    await ingest.ingest(db, day=day, marks=list(marks), strong=list(strongs), now=now)
    return await cons.consolidate(db, days=[day], now=now)


def opps(db):
    return db["spt_opportunities"].docs


def only(db):
    assert len(opps(db)) == 1, [o["consolidation_key"] for o in opps(db)]
    return opps(db)[0]


# ── SPT-A-15 … 20: consolidation ─────────────────────────────────────────────────────────────────────────────────────

def test_SPT_A_15_four_scanners_one_stock_one_opportunity_attribution_kept():
    db = DB()
    marks = [mark("dt_52w_high", "AAA", ist(9, 30), 100.0), mark("dt_vol_price_breakout", "AAA", ist(9, 35), 101.0),
             mark("dt_delivery_volume", "AAA", ist(9, 40), 101.5), mark("long_buildup", "AAA", ist(9, 50), 102.0)]
    scores = {"as_of": ist(9, 50, 5).isoformat(), "scores": {"AAA": {"score": 66}}}
    run(ingest.ingest(db, day=DAY, marks=marks, scores_doc=scores, now=NOW))
    c = run(cons.consolidate(db, days=[DAY], now=NOW))
    assert (c["created"], c["attached"]) == (1, 3)
    o = only(db)
    assert o["consolidation_key"] == "AAA|long|positional|2026-11-04"
    assert [s["scanner_id"] for s in o["signals"]] == ["dt_52w_high", "dt_vol_price_breakout", "dt_delivery_volume",
                                                       "long_buildup"]
    assert [s["detected_at"][11:19] for s in o["signals"]] == ["04:00:00", "04:05:00", "04:10:00", "04:20:00"]
    assert [s["detected_price"] for s in o["signals"]] == [100.0, 101.0, 101.5, 102.0]
    assert o["families"] == ["high_52w_breakout", "volume_price_breakout", "volume_expansion_weekly_rsi", "fno_long_buildup"]
    assert set(o["categories"]) == {"breakout", "volume", "derivatives"}
    assert o["state"] == C.OPP_CREATED and o["signal_count"] == 4 and o["strong"] is None
    assert o["window_until"] == "2026-11-11T10:01:00+00:00"
    # scores kept per signal, never added together
    only_long_buildup_scored = [s["scanner_score"] for s in o["signals"]]
    assert only_long_buildup_scored == [None, None, None, 66]
    assert 66 * 4 not in [v for v in o.values() if isinstance(v, (int, float))]
    assert len(events_of(db, "OPPORTUNITY_CREATED")) == 1 and len(events_of(db, "OPPORTUNITY_UPDATED")) == 3


def test_SPT_A_16_horizons_and_windows_split_opportunities(monkeypatch):
    db = DB()
    run(load(db, [mark("cup_handle", "AAA", ist(9, 30)), mark("dt_breakout_15m", "AAA", ist(9, 45))]))
    assert sorted(o["horizon"] for o in opps(db)) == ["intraday", "positional"]
    intra = next(o for o in opps(db) if o["horizon"] == "intraday")
    assert intra["window_until"] == "2026-11-04T10:01:00+00:00"            # 15:31 IST the same day
    # next day: an intraday mark opens a new intraday opportunity; a positional one joins the window
    d2 = D + timedelta(days=1)
    n2 = ist(10, 0, day=d2)
    run(load(db, [mark("dt_breakout_15m", "AAA", ist(9, 50, day=d2)), mark("dt_52w_high", "AAA", ist(9, 55, day=d2))],
             now=n2, day="2026-11-05"))
    assert len([o for o in opps(db) if o["horizon"] == "intraday"]) == 2
    pos = [o for o in opps(db) if o["horizon"] == "positional"]
    assert len(pos) == 1 and pos[0]["signal_count"] == 2
    # 6 sessions after the first signal (Thu 12 Nov): past the window → a new positional opportunity
    d6 = date(2026, 11, 12)
    run(load(db, [mark("cup_handle", "AAA", ist(10, 0, day=d6))], now=ist(10, 1, day=d6), day="2026-11-12"))
    pos = sorted((o for o in opps(db) if o["horizon"] == "positional"), key=lambda o: o["day"])
    assert [o["consolidation_key"] for o in pos] == ["AAA|long|positional|2026-11-04", "AAA|long|positional|2026-11-12"]


def test_SPT_A_17_opposite_directions_are_kept_as_conflicts_on_both_sides():
    db = DB()
    run(load(db, [mark("open_interest", "MCX", ist(9, 20), 3313.6, direction="short"),
                  mark("cup_handle", "MCX", ist(9, 40), 3320.0)]))
    short = next(o for o in opps(db) if o["direction"] == "short")
    long_ = next(o for o in opps(db) if o["direction"] == "long")
    assert [c["signal_id"] for c in short["conflicts"]] == ["sig:2026-11-04:cup_handle:MCX"]
    assert [c["signal_id"] for c in long_["conflicts"]] == ["sig:2026-11-04:open_interest:MCX"]
    assert long_["conflicts"][0]["direction"] == "short" and long_["conflicts"][0]["opportunity_id"] == short["_id"]
    ev = events_of(db, "SIGNAL_CONFLICT_DETECTED")
    assert len(ev) == 1 and ev[0]["payload"]["against_opportunities"] == [short["_id"]]
    # a second pass and a third long signal: no duplicate conflict rows, one more event (for the new signal)
    run(cons.consolidate(db, days=[DAY], now=NOW))
    run(load(db, [mark("dt_52w_high", "MCX", ist(9, 50), 3330.0)]))
    short = next(o for o in opps(db) if o["direction"] == "short")
    long_ = next(o for o in opps(db) if o["direction"] == "long")
    assert len(short["conflicts"]) == 2 and len(long_["conflicts"]) == 1
    assert len(events_of(db, "SIGNAL_CONFLICT_DETECTED")) == 2


def test_SPT_A_18_strong_signal_attaches_its_frozen_plan_once():
    db = DB()
    run(load(db, [mark("dt_52w_high", "AAA", ist(9, 30))], [strong("AAA", ist(9, 45), entry=100.0, atr=2.0)]))
    o = only(db)
    assert o["strong"]["signal_id"] == "sig:2026-11-04:strong:AAA"
    assert o["strong"]["plan"] == {"rules": "scan-plan-v3", "entry": 100.0, "stop_loss": 96.0, "target_1": 108.0,
                                   "target_2": 116.0, "risk_per_share": 4.0, "rr_1": 2.0, "rr_2": 4.0, "atr": 2.0,
                                   "sma20": 97.0, "trend_exit": "A daily close below the 20-day average", "plan_ok": True,
                                   "plan_note": None}
    assert o["strong"]["score_at"] == 75 and o["strong"]["parts_at"]["quality"] == 25
    assert o["window_until"] == "2026-11-11T10:01:00+00:00"              # its own day: the window is unchanged
    d2 = D + timedelta(days=1)
    run(load(db, [], [strong("AAA", ist(10, 0, day=d2), entry=110.0, score=90)], now=ist(10, 1, day=d2), day="2026-11-05"))
    o = only(db)
    assert o["signal_count"] == 3 and o["strong"]["plan"]["entry"] == 100.0 and o["strong"]["score_at"] == 75
    assert o["window_until"] == "2026-11-11T10:01:00+00:00"              # only the FIRST strong signal extends it


def test_SPT_A_18_a_strong_signal_joining_an_old_window_gets_its_own_sessions():
    db = DB()
    run(load(db, [mark("dt_52w_high", "AAA", ist(9, 30))]))                          # Wed 4 Nov: until Wed 11 Nov
    mon = date(2026, 11, 9)
    run(load(db, [], [strong("AAA", ist(10, 0, day=mon))], now=ist(10, 1, day=mon), day="2026-11-09"))
    o = only(db)
    assert o["strong"] is not None and o["consolidation_key"] == "AAA|long|positional|2026-11-04"
    assert o["window_until"] == o["expires_at"] == "2026-11-16T10:01:00+00:00"     # Mon 9 Nov + 5 sessions, 15:31 IST


def test_SPT_A_19_reruns_and_a_lost_race_never_duplicate(monkeypatch):
    db = DB()
    run(load(db, [mark("cup_handle", "AAA", ist(9, 30))]))
    writes = db.writes
    again = run(cons.consolidate(db, days=[DAY], now=NOW))
    cons._handled.clear()                                                  # a restarted worker
    third = run(cons.consolidate(db, days=[DAY], now=NOW))
    assert again["created"] == again["attached"] == third["created"] == third["attached"] == 0
    assert third["already"] == 1 and db.writes == writes
    # the race: an open opportunity with the same key appears between the read and the insert
    run(ingest.ingest(db, day=DAY, marks=[mark("dt_52w_high", "AAA", ist(9, 35))], now=NOW))
    real = store.candidates
    calls = {"n": 0}

    async def blind_once(*a, **k):
        calls["n"] += 1
        return [] if calls["n"] == 1 else await real(*a, **k)

    monkeypatch.setattr(store, "candidates", blind_once)
    ev = next(d for d in db["spt_signal_events"].docs if d["scanner_id"] == "dt_52w_high")
    r = run(cons.place(db, ev, now=NOW))
    assert r["action"] == "attached" and len(opps(db)) == 1 and only(db)["signal_count"] == 2


def test_SPT_A_17_a_conflict_on_a_qualified_opportunity_is_flagged_not_hidden():
    db = DB()
    o = qualified_setup(db)
    run(val.validate(db, o["_id"], inputs=Inputs(market()), now=NOW))
    run(load(db, [mark("oi_7", "AAA", ist(10, 5), direction="short")], now=ist(10, 6)))
    q = next(x for x in opps(db) if x["direction"] == "long")
    assert q["state"] == C.OPP_QUALIFIED and q["conflict_after_qualified"] is True
    assert [c["signal_id"] for c in q["conflicts"]] == ["sig:2026-11-04:oi_7:AAA"]


def test_SPT_A_19_a_placing_that_fails_after_the_attach_is_retried_with_its_conflicts(monkeypatch):
    db = DB()
    run(load(db, [mark("open_interest", "MCX", ist(9, 20), direction="short")]))
    run(ingest.ingest(db, day=DAY, marks=[mark("cup_handle", "MCX", ist(9, 40))], now=NOW))
    real = cons._conflicts
    calls = {"n": 0}

    async def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("mongo blip")
        return await real(*a, **k)

    monkeypatch.setattr(cons, "_conflicts", flaky)
    first = run(cons.consolidate(db, days=[DAY], now=NOW, received_since="2026-11-04T04:00:00+00:00"))
    assert first["failed"] == 1
    long_ = next(o for o in opps(db) if o["direction"] == "long")
    assert long_["conflicts"] == [] and long_["signal_count"] == 1      # attached, conflict not written yet
    # the next pass reads nothing new (received_since moved on) but places the failed event again first
    second = run(cons.consolidate(db, days=[DAY], now=NOW, received_since="2026-11-04T23:00:00+00:00"))
    assert (second["retried"], second["already"], second["failed"]) == (1, 1, 0)
    long_ = next(o for o in opps(db) if o["direction"] == "long")
    short = next(o for o in opps(db) if o["direction"] == "short")
    assert [c["signal_id"] for c in long_["conflicts"]] == ["sig:2026-11-04:open_interest:MCX"]
    assert [c["signal_id"] for c in short["conflicts"]] == ["sig:2026-11-04:cup_handle:MCX"]
    assert long_["signal_count"] == 1 and not cons._retry


def test_SPT_A_20_quarantined_events_are_never_consolidated():
    db = DB()
    c = run(load(db, [mark("no_such_list", "AAA", ist(9, 30)), mark("cup_handle", "BBB", ist(9, 5)),
                      mark("dt_breakout_15m", "CCC", ist(9, 30))], now=ist(9, 30, day=D + timedelta(days=1))))
    assert opps(db) == [] and c["events"] == 0
    assert {d["status"] for d in db["spt_signal_events"].docs} == {"quarantined"}


# ── SPT-A-21: the store interface slice B reads ──────────────────────────────────────────────────────────────────────

def test_SPT_A_21_get_list_by_state_and_conditional_transition():
    db = DB()
    run(load(db, [mark("cup_handle", "AAA", ist(9, 30)), mark("cup_handle", "BBB", ist(9, 31)),
                  mark("dt_breakout_15m", "CCC", ist(9, 32))]))
    a = copy.deepcopy(next(o for o in opps(db) if o["symbol"] == "AAA"))     # the fake hands out live documents
    assert run(store.get(db, a["_id"]))["symbol"] == "AAA" and run(store.get(db, "nope")) is None
    got = run(store.list_by_state(db, [C.OPP_CREATED], day=DAY))
    assert [o["symbol"] for o in got] == ["AAA", "BBB", "CCC"]
    assert [o["symbol"] for o in run(store.list_by_state(db, [C.OPP_CREATED], limit=2))] == ["AAA", "BBB"]
    assert run(store.list_by_state(db, [C.OPP_CREATED], day="2026-11-05")) == []
    writes = db.writes
    assert run(store.transition(db, a["_id"], expect_states=[C.OPP_QUALIFIED], to_state=C.OPP_EXPIRED, reason="x")) is None
    assert run(store.transition(db, a["_id"], expect_states=[C.OPP_CREATED], to_state=C.OPP_QUALIFIED, reason="x")) is None
    assert db.writes == writes                                              # refused moves write nothing
    with pytest.raises(ValueError):
        run(store.transition(db, a["_id"], expect_states=[C.OPP_CREATED], to_state="BOGUS", reason="x"))
    v = run(store.transition(db, a["_id"], expect_states=[C.OPP_CREATED], to_state=C.OPP_VALIDATING, reason="go"))
    assert (v["state"], v["version"], v["is_open"]) == (C.OPP_VALIDATING, a["version"] + 1, True)
    q = run(store.transition(db, a["_id"], expect_states=[C.OPP_VALIDATING], to_state=C.OPP_QUALIFIED, reason="passed",
                             extra={"validation": {"x": 1}, "state": "HACK", "version": 99}))
    assert (q["state"], q["version"], q["validation"]) == (C.OPP_QUALIFIED, a["version"] + 2, {"x": 1})
    # slice B's one write: QUALIFIED → EXPIRED when its proposal finds the plan stale
    e = run(store.transition(db, a["_id"], expect_states=[C.OPP_QUALIFIED], to_state=C.OPP_EXPIRED,
                             reason="plan_stale", extra={"expired_by": "spt-proposals"}))
    assert (e["state"], e["is_open"], e["expired_by"]) == (C.OPP_EXPIRED, False, "spt-proposals")
    assert [(h["from"], h["to"]) for h in e["state_history"]] == [(None, "CREATED"), ("CREATED", "VALIDATING"),
                                                                  ("VALIDATING", "QUALIFIED"), ("QUALIFIED", "EXPIRED")]
    assert [x["payload"]["to"] for x in events_of(db) if x["event_type"] in ("OPPORTUNITY_QUALIFIED",
                                                                             "OPPORTUNITY_EXPIRED")] == ["QUALIFIED",
                                                                                                         "EXPIRED"]
    assert run(store.transition(db, a["_id"], expect_states=[C.OPP_EXPIRED], to_state=C.OPP_VALIDATING, reason="x")) is None


# ── SPT-A-22 … 30: validation and expiry ─────────────────────────────────────────────────────────────────────────────

def market(**over):
    by = {"AAA": rising(260, start=50.0, step=0.2, end=PREV)}           # 50 → 101.8, volume 1e6: ADV ≈ ₹10 cr
    by.update(over)
    return by


def qualified_setup(db, now=NOW):
    run(load(db, [mark("dt_52w_high", "AAA", ist(9, 30), 102.0), mark("dt_vol_price_breakout", "AAA", ist(9, 35), 102.5)],
             [strong("AAA", ist(9, 45), entry=103.0, atr=2.0)], now=now))
    return only(db)


def test_SPT_A_22_strong_long_positional_fresh_liquid_bullish_is_qualified():
    db = DB()
    o = qualified_setup(db)
    r = run(val.validate(db, o["_id"], inputs=Inputs(market()), now=NOW))
    assert r["ok"] and r["state"] == C.OPP_QUALIFIED
    v = r["validation"]
    for k in ("at", "version", "decision", "reason_codes", "explanations", "opportunity_score", "score_parts", "market",
              "stock", "liquidity", "derivatives", "data_as_of", "revalidate_at"):
        assert k in v, k
    assert (v["decision"], v["reason_codes"], v["version"], v["derivatives"]) == (C.OPP_QUALIFIED, [], C.VALIDATION_VERSION, None)
    assert v["data_as_of"]["derivatives"]["reason"] == "not_checked"
    assert v["data_as_of"]["bars"]["ok"] and v["data_as_of"]["bars"]["as_of"] == "2026-11-03"
    assert v["market"]["key"] == "bullish" and v["liquidity"]["adv_rs"] > 9e7 and v["liquidity"]["ok"]
    assert v["stock"]["checks"]["trend_aligned"] is True and v["revalidate_at"] is None
    doc = only(db)
    assert doc["state"] == C.OPP_QUALIFIED and doc["validation"] == v and doc["opportunity_score"] == v["opportunity_score"]
    assert doc["validated_evidence_version"] == doc["evidence_version"]
    assert len(events_of(db, "OPPORTUNITY_VALIDATED")) == 1 and len(events_of(db, "OPPORTUNITY_QUALIFIED")) == 1
    assert events_of(db, "OPPORTUNITY_VALIDATED")[0]["payload"]["validation"] == v
    assert [h["to"] for h in doc["state_history"]] == ["CREATED", "VALIDATING", "QUALIFIED"]
    # QUALIFIED is not revalidated
    again = run(val.validate(db, o["_id"], inputs=Inputs(market()), now=NOW))
    assert again == {"ok": False, "error": "opportunity_not_revalidatable", "state": C.OPP_QUALIFIED}


@pytest.mark.parametrize("key", ["bearish", "high_volatility"])
def test_SPT_A_23_risk_off_regime_is_conditional(key):
    db = DB()
    o = qualified_setup(db)
    r = run(val.validate(db, o["_id"], inputs=Inputs(market(), regime={**REGIME_BULL, "key": key, "label": key}), now=NOW))
    assert r["state"] == C.OPP_CONDITIONAL and r["validation"]["reason_codes"] == ["regime_risk_off"]
    assert r["validation"]["revalidate_at"] == "2026-11-05T03:30:00+00:00"       # next weekday 09:00 IST


def test_SPT_A_24_illiquid_is_rejected_and_keeps_its_window():
    db = DB()
    o = qualified_setup(db)
    thin = rising(260, start=50.0, step=0.2, end=PREV)
    for b in thin:
        b["volume"] = 1000.0                                                # ≈ ₹1 lakh a day
    r = run(val.validate(db, o["_id"], inputs=Inputs(market(AAA=thin)), now=NOW))
    assert r["state"] == C.OPP_REJECTED and r["validation"]["reason_codes"] == ["liquidity_too_low"]
    assert "below the minimum ₹1.00 cr" in r["validation"]["explanations"][0]
    assert len(events_of(db, "OPPORTUNITY_REJECTED")) == 1
    run(load(db, [mark("cup_handle", "AAA", ist(11, 0))]))               # the same window: attached, still REJECTED
    o = only(db)
    assert o["state"] == C.OPP_REJECTED and o["signal_count"] == 4


def test_SPT_A_25_data_provider_down_or_stale_is_data_insufficient_then_recovers():
    db = DB()
    o = qualified_setup(db)
    r = run(val.validate(db, o["_id"], inputs=Inputs(market(AAA=RuntimeError("daas timeout"))), now=NOW))
    assert r["state"] == C.OPP_DATA_INSUFFICIENT and r["validation"]["reason_codes"] == ["bars_unavailable"]
    assert "RuntimeError" in r["validation"]["explanations"][0]
    assert r["validation"]["revalidate_at"] == "2026-11-04T04:40:30+00:00"     # 10 minutes later
    assert r["validation"]["stock"]["last_close"] is None                         # nothing invented
    later = NOW + timedelta(minutes=11)
    stale = rising(260, start=50.0, step=0.2, end=date(2026, 10, 20))
    r = run(val.validate(db, o["_id"], inputs=Inputs(market(AAA=stale)), now=later))
    assert r["state"] == C.OPP_DATA_INSUFFICIENT and r["validation"]["reason_codes"] == ["bars_stale"]
    r = run(val.validate(db, o["_id"], inputs=Inputs(market(), regime={"available": False, "reason": "macro_state is empty"}),
                         now=later))
    assert r["state"] == C.OPP_DATA_INSUFFICIENT and r["validation"]["reason_codes"] == ["regime_unavailable"]
    r = run(val.validate(db, o["_id"], inputs=Inputs(market(), regime=RuntimeError("down")), now=later))
    assert r["validation"]["reason_codes"] == ["regime_unavailable"]
    old = {**REGIME_BULL, "as_of": "2026-10-20"}
    r = run(val.validate(db, o["_id"], inputs=Inputs(market(), regime=old), now=later))
    assert r["validation"]["reason_codes"] == ["regime_stale"]
    # the data is back: the loop's due query picks it up after revalidate_at and it qualifies
    c = run(val.validate_due(db, now=later + timedelta(minutes=11), inputs=Inputs(market())))
    assert c["validated"] == 1 and only(db)["state"] == C.OPP_QUALIFIED


def test_SPT_A_26_not_qualifiable_tonight_is_watchlist():
    db = DB()
    run(load(db, [mark("dt_52w_high", "BBB", ist(9, 30)), mark("dt_breakout_15m", "CCC", ist(9, 30)),
                  mark("dt_below_dma", "DDD", ist(9, 30))],
             [strong("EEE", ist(9, 30), plan_ok=False)]))
    inp = Inputs({s: rising(260, start=50.0, step=0.2, end=PREV) for s in ("BBB", "CCC", "DDD", "EEE")})
    got = {}
    for o in list(opps(db)):
        got[o["symbol"]] = run(val.validate(db, o["_id"], inputs=inp, now=NOW))
    assert {s: (r["state"], r["validation"]["reason_codes"]) for s, r in got.items()} == {
        "BBB": (C.OPP_WATCHLIST, ["no_strong_signal"]),
        "CCC": (C.OPP_WATCHLIST, ["no_strong_signal", "horizon_intraday"]),
        "DDD": (C.OPP_WATCHLIST, ["no_strong_signal", "direction_short"]),
        "EEE": (C.OPP_WATCHLIST, ["plan_not_ok"]),
    }
    assert not events_of(db, "OPPORTUNITY_QUALIFIED")
    # a strong signal arriving later is new evidence: the loop revalidates and it qualifies
    run(load(db, [], [strong("BBB", ist(11, 0), entry=102.0)], now=ist(11, 0, 30)))
    c = run(val.validate_due(db, now=ist(11, 1), inputs=inp))
    assert c["validated"] == 1 and next(o for o in opps(db) if o["symbol"] == "BBB")["state"] == C.OPP_QUALIFIED


def test_SPT_A_27_score_counts_distinct_families_and_is_not_a_probability():
    db = DB()
    run(load(db, [mark("dt_52w_high", "AAA", ist(9, 30)), mark("dt_52w_breakout", "AAA", ist(9, 31)),
                  mark("dt_uptrend_52w", "AAA", ist(9, 32))]))
    o = only(db)
    bars_read = {"bars": rising(260, start=50.0, step=0.2, end=PREV), "error": None, "source": "MOCK", "read_at": "x"}
    pol = val.policy({})
    v1 = val.assess(o, bars_read, REGIME_BULL, NOW, pol)
    assert v1["score_parts"]["confirmations"]["points"] == 10                # three 52-week lists = ONE family
    assert v1["families"] == ["high_52w_breakout"]
    run(load(db, [mark("cup_handle", "AAA", ist(9, 40))]))
    v2 = val.assess(only(db), bars_read, REGIME_BULL, NOW, pol)
    assert v2["score_parts"]["confirmations"]["points"] == 18
    p = v2["score_parts"]
    assert v2["opportunity_score"] == sum(x["points"] for x in p.values())
    # worked by hand: trend 7+6+6 + RSI (a steady rise: RSI 100 → 0) = 19; participation: rvol 1.0 → 4, no volume list;
    # liquidity: ADV = mean(close × 1e6) over the last 20 closes 98.0 … 101.8 = 99.9 × 1e6 = ₹9.99 cr: ≥ ₹5 cr → 9;
    # bullish → 15
    assert v2["liquidity"]["adv_rs"] == pytest.approx(99.9e6)
    assert (p["trend"]["points"], p["participation"]["points"], p["liquidity"]["points"], p["regime_fit"]["points"],
            p["conflicts"]["points"]) == (19, 4, 9, 15, 0)
    assert v2["opportunity_score"] == 18 + 19 + 4 + 9 + 15 == 65
    assert "not a probability" in v2["score_label"] and v2["version"] == C.VALIDATION_VERSION
    assert val.assess(only(db), bars_read, REGIME_BULL, NOW, pol) == v2       # same inputs → same record


def test_SPT_A_28_a_bonus_jump_does_not_corrupt_the_indicators():
    pre = [200.0 + i * 0.1 for i in range(200)]
    post = [100.0 + i * 0.05 for i in range(40)]                           # 1:1 bonus: the close halves, 40 sessions ago
    m = val.stock_metrics(bars_from(pre + post, end=PREV), "long")
    assert m["series_break_day"] is not None and m["bars_used"] == 40
    assert m["ema200"] is None and m["ema50"] is None and 100 < m["ema20"] < 102
    assert any("EMA200 needs 200 sessions" in n for n in m["notes"])
    older = [200.0 + i * 0.1 for i in range(100)] + [100.0 + i * 0.05 for i in range(150)]   # break 150 sessions ago
    m2 = val.stock_metrics(bars_from(older, end=PREV), "long")
    assert m2["bars_used"] == 150 and m2["ema50"] is not None and m2["ema50"] < 110          # beyond series_break's 60


def test_SPT_A_29_expiry_window_ended_and_close_below_stop():
    db = DB()
    o = qualified_setup(db)
    run(val.validate(db, o["_id"], inputs=Inputs(market()), now=NOW))
    assert only(db)["state"] == C.OPP_QUALIFIED
    # in the session the stop is checked once against the bars to 3 Nov (nothing after the signal yet)
    inp = Inputs(market())
    c = run(val.expire(db, now=ist(11, 0), inputs=inp))
    assert (c["checked"], c["expected_bar_day"]) == (1, "2026-11-03") and only(db)["stop_checked_through"] == "2026-11-03"
    calls = len(inp.bar_calls)
    assert run(val.expire(db, now=ist(11, 0, 30), inputs=inp))["checked"] == 0 and len(inp.bar_calls) == calls
    # 19:45: today's file is not in yet (the reference symbol's last bar is 3 Nov): wait, read nothing more
    w = run(val.expire(db, now=ist(19, 45), inputs=Inputs(market(RELIANCE=bars_from([100.0] * 30, end=PREV)))))
    assert w["stop_check"] == "waiting_for_nse_file" and only(db)["state"] == C.OPP_QUALIFIED
    # 20:00: the file is in; 4 Nov's close (95.0) is below the stop (103 − 4 = 99.0)
    evening = ist(20, 0)
    closes = [round(50.0 + i * 0.2, 2) for i in range(260)] + [95.0]
    today = bars_from(closes, end=D)
    c = run(val.expire(db, now=evening, inputs=Inputs(market(AAA=today, RELIANCE=today))))
    assert c["closed_below_stop"] == 1
    doc = only(db)
    assert (doc["state"], doc["state_reason"], doc["is_open"]) == (C.OPP_EXPIRED, "closed_below_stop", False)
    assert doc["expiry"]["below_stop_close"] == 95.0 and doc["expiry"]["below_stop_day"] == "2026-11-04"
    assert len(events_of(db, "OPPORTUNITY_EXPIRED")) == 1
    # window: a watchlist opportunity past 11 Nov 15:31 IST
    db2 = DB()
    run(load(db2, [mark("cup_handle", "BBB", ist(9, 30))]))
    after = datetime(2026, 11, 11, 10, 2, tzinfo=timezone.utc)
    c2 = run(val.expire(db2, now=after, inputs=Inputs({})))
    assert c2["window_ended"] == 1 and only(db2)["state"] == C.OPP_EXPIRED and only(db2)["state_reason"] == "window_ended"
    assert run(val.expire(db2, now=after, inputs=Inputs({})))["window_ended"] == 0          # once


def test_SPT_A_30_conflicting_signals_make_it_conditional():
    db = DB()
    o = qualified_setup(db)
    run(load(db, [mark("oi_7", "AAA", ist(9, 50), direction="short")]))
    r = run(val.validate(db, o["_id"], inputs=Inputs(market()), now=NOW))
    assert r["state"] == C.OPP_CONDITIONAL and r["validation"]["reason_codes"] == ["conflicting_signals"]
    assert r["validation"]["score_parts"]["conflicts"]["points"] == -10


def test_validation_never_left_in_validating(monkeypatch):
    db = DB()
    o = qualified_setup(db)

    def boom(*a, **k):
        raise ZeroDivisionError("bug")

    monkeypatch.setattr(val, "assess", boom)
    r = run(val.validate(db, o["_id"], inputs=Inputs(market()), now=NOW))
    assert r["state"] == C.OPP_DATA_INSUFFICIENT and r["validation"]["reason_codes"] == ["validation_error"]


# ── SPT-A-31: the loop ───────────────────────────────────────────────────────────────────────────────────────────────

def W(wid, syms):
    return {"id": wid, "title": wid, "row_kind": "symbol", "status": "ok", "rows": [[s, 1.0, 100.0, 1000] for s in syms],
            "criteria": [{"applied": True}]}


def test_SPT_A_31_flag_and_max_per_round():
    assert runner.enabled({"APP_ENV": "staging"}) and not runner.enabled({"APP_ENV": "staging", "SPT_A_ENABLED": "0"})
    assert runner.enabled({"SPT_A_ENABLED": "1"}) and not runner.enabled({})
    assert runner.max_per_round({"SPT_VALIDATE_MAX_PER_ROUND": "5"}) == 5 and runner.max_per_round({}) == val.MAX_PER_ROUND
    assert runner.active_days(NOW, 5) == ["2026-11-04", "2026-11-03", "2026-11-02", "2026-10-30", "2026-10-29",
                                          "2026-10-28"]


def test_SPT_A_31_a_round_runs_every_step_once_per_leader(monkeypatch):
    SIG._seen.clear()
    SIG._seen_strong.clear()
    db = DB()
    scan = SIG.LocalSignalStore()
    inputs_for = lambda syms: {s: {"close": 102.0, "low": 101.0, "high": 103.0, "atr": 2.0, "chg": 1.0} for s in syms}

    async def go():
        await SIG.record([W("dt_52w_high", ["AAA"]), W("dt_vol_price_breakout", ["AAA"])], inputs_for, ist(9, 30), store=scan)
        await SIG.record_strong([strong("AAA", ist(9, 45), entry=103.0)], ist(9, 45), store=scan)
        first = await runner.round_once(db, NOW, scan_store=scan, inputs=Inputs(market()), me="w1")
        other = await runner.round_once(db, NOW, scan_store=scan, inputs=Inputs(market()), me="w2")
        second = await runner.round_once(db, NOW + timedelta(seconds=30), scan_store=scan, inputs=Inputs(market()), me="w1")
        return first, other, second

    first, other, second = run(go())
    assert other is None                                                   # not the leader: does nothing
    assert first["errors"] == [] and first["counts"]["catch_up"]["2026-11-04"]["inserted"] == 3
    assert first["counts"]["consolidate"]["created"] == 1 and first["counts"]["validate"]["validated"] == 1
    assert only(db)["state"] == C.OPP_QUALIFIED
    assert second["counts"]["catch_up"]["2026-11-04"]["inserted"] == 0 and second["counts"]["validate"]["due"] == 0
    st = db["spt_state"].docs[0]
    assert st["_id"] == "spt_a" and st["leader"] == "w1" and st["errors"] == [] and st["last_ok_at"]
    assert set(st["counts"]) == {"catch_up", "consolidate", "validate", "expire"}
    SIG._seen.clear()
    SIG._seen_strong.clear()


def test_SPT_A_31_a_failing_step_is_recorded_and_the_round_goes_on(monkeypatch):
    db = DB()
    scan = SIG.LocalSignalStore()

    async def broken(*a, **k):
        raise ConnectionError("mongo unreachable")

    monkeypatch.setattr(cons, "consolidate", broken)
    r = run(runner.round_once(db, NOW, scan_store=scan, inputs=Inputs({}), me="w1"))
    assert r["errors"] == ["consolidate: ConnectionError"]
    assert {"catch_up", "validate", "expire"} <= set(r["counts"])
    st = db["spt_state"].docs[0]
    assert st["errors"] == ["consolidate: ConnectionError"] and "last_ok_at" not in st


def test_SPT_A_31_the_evening_round_runs_the_outcomes_step():
    db = DB()
    scan = SIG.LocalSignalStore()
    run(load(db, [mark("dt_52w_high", "AAA", ist(9, 30), 100.0)]))
    bars = rising(260, start=50.0, step=0.2, end=D)                       # 4 Nov's file is in
    r = run(runner.round_once(db, ist(20, 15), scan_store=scan, inputs=Inputs({"AAA": bars, "RELIANCE": bars}), me="w1",
                              outcomes=runner.outcomes_step))
    assert r["errors"] == [] and r["counts"]["outcomes"]["computed"] == 1
    assert db["spt_signal_outcomes"].docs[0]["_id"] == "sig:2026-11-04:dt_52w_high:AAA"
    r = run(runner.round_once(db, ist(10, 0, day=D + timedelta(days=1)), scan_store=scan, inputs=Inputs({}), me="w1",
                              outcomes=runner.outcomes_step))
    assert r["counts"]["outcomes"] == {"skipped": "not_evening"}


def test_a_validation_stuck_in_validating_is_resumed_after_five_minutes():
    db = DB()
    o = qualified_setup(db)
    run(store.transition(db, o["_id"], expect_states=[C.OPP_CREATED], to_state=C.OPP_VALIDATING,
                         reason="validation_started", extra={"validating_since": clock.utc_iso(NOW)}))
    # the worker died here; a signal still attaches (it moves updated_at, not validating_since)
    run(load(db, [mark("cup_handle", "AAA", ist(10, 2))], now=ist(10, 2, 30)))
    soon = NOW + timedelta(minutes=2)
    assert run(val.validate(db, o["_id"], inputs=Inputs(market()), now=soon))["error"] == "validation_in_progress"
    assert run(val.validate_due(db, now=soon, inputs=Inputs(market())))["due"] == 0
    c = run(val.validate_due(db, now=NOW + timedelta(minutes=6), inputs=Inputs(market())))
    assert c["validated"] == 1 and only(db)["state"] == C.OPP_QUALIFIED
    assert only(db)["validated_evidence_version"] == only(db)["evidence_version"]


def test_evidence_that_arrives_during_a_validation_is_not_lost():
    db = DB()
    run(load(db, [mark("dt_52w_high", "AAA", ist(9, 30), 102.0)]))
    o = only(db)

    class Racing(Inputs):
        async def regime(self):
            await load(db, [], [strong("AAA", ist(9, 45), entry=103.0)])     # attaches while the record is built
            return await super().regime()

    r = run(val.validate(db, o["_id"], inputs=Racing(market()), now=NOW))
    assert r["state"] == C.OPP_WATCHLIST and r["validation"]["reason_codes"] == ["no_strong_signal"]
    doc = only(db)
    assert doc["strong"] is not None and doc["evidence_version"] > doc["validated_evidence_version"]
    c = run(val.validate_due(db, now=NOW + timedelta(seconds=30), inputs=Inputs(market())))
    assert c["validated"] == 1 and only(db)["state"] == C.OPP_QUALIFIED


def test_SPT_A_31_a_worker_that_loses_the_lock_mid_round_stops():
    db = DB()

    class Fickle(SIG.LocalSignalStore):
        def __init__(self):
            super().__init__()
            self.n = 0

        async def lead(self, key, me, ttl, now):
            self.n += 1
            return self.n <= 3                    # the round's check, catch_up's, consolidate's; lost before validate

    r = run(runner.round_once(db, NOW, scan_store=Fickle(), inputs=Inputs({}), me="w1"))
    assert set(r["counts"]) == {"catch_up", "consolidate"} and r["errors"] == ["validate: leader_lost"]
