"""Strategy ideas from the AI opportunities (services/strategy_plan selection, combination templates, ideas; POST /api/desk/strategy/ideas).

No network and no real database. Everything below is MOCK — not real data: round numbers chosen so the arithmetic can be done by hand.
The plan builder and the payoff engine are the real ones. The fixture world is the one of tests/test_strategy_plan.py (RELIANCE-like):
    close 1200, ATR14 20, scanner stop 1160 (risk 40 a share), lot 250, expiry 2026-11-24 (36 days)
    puts: 1150 closes 22 (OI 25000, the put wall), 1100 closes 10;   calls: 1250 closes 38 (OI 30000, the call wall), 1300 closes 20
    futures settle for the 2026-11-24 contract: 1206
Combination arithmetic (per lot of 250 shares, per share):
    covered call      sell the 1250 call at 38:  max profit (1250 - 1200 + 38) x 250 = 22 000;  max loss (1200 - 38) x 250 = 290 500;  breakeven 1200 - 38 = 1162
    protective put    buy the 1150 put at 22:    max loss (1200 - 1150 + 22) x 250 = 18 000;  profit unbounded;  breakeven 1200 + 22 = 1222
    collar            put 1150 at 22, call 1250 at 38:  max loss (50 + 22 - 38) x 250 = 8 500;  max profit (50 + 38 - 22) x 250 = 16 500;  breakeven 1184
    futures + put     long the 1206 future, put 1150 at 22:  max loss (1206 - 1150 + 22) x 250 = 19 500;  profit unbounded;  breakeven 1228
"""
from __future__ import annotations

import asyncio
import copy
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

import routes.strategy_plan as route
from services.strategy_plan import compute_payoff, normalise_inputs
from services.strategy_plan import candidates as cd
from services.strategy_plan import ideas as ideas_mod
from services.strategy_plan import plan as pl
from services.strategy_plan import selection as sel
from services.strategy_plan.evidence import src_fail, src_ok
from services.strategy_plan.rules import RULES, STRATEGY_RULES_VERSION
from tests.test_strategy_plan import (ASOF, COSTS, EXPIRY, NOW, TODAY, FakeDb, buildup, bucket, build, cand, chain, codes, events, futures,
                                      inputs, scan_row, world)

BIG = dict(capital=5_000_000, risk_budget_inr=50_000)          # lots are bound by the 25% allocation cap: floor(1 250 000 / deployed per lot)
EVENT = events("2026-10-28")                                    # results 9 days after the price day, inside the 10-day horizon


def combos(p):
    return {c["family"]: c for c in p["candidates"] if c["segment"] == "combination"}


def legs_of(c):
    return [(l["kind"], l["side"], l["quantity"], l["lot_size"], l["entry_price"], l.get("strike"), l.get("option_type")) for l in c["legs"]]


# ── combination templates: closed form, checked against the engine ───────────

def test_covered_call_closed_form_and_engine_agrees():
    c = combos(build(world(), instrument="combination", **BIG))["covered_call"]
    lots = c["sizing"]["quantity"]
    deployed = (1200.0 * 250 - 38.0 * 250)                   # shares less the call premium received
    assert lots == 4 == int(1_250_000 // deployed) and c["sizing"]["binding"] == "allocation_cap"
    # shares = lots x lot size at the last close; the short call is the call wall 1250 (above the ATM strike 1200)
    assert legs_of(c) == [("cash", "buy", 1000, 1, 1200.0, None, None), ("option", "sell", 4, 250, 38.0, 1250.0, "call")]
    e = c["payoff"]["expiry"]
    assert (e["max_profit"], e["max_loss"], e["breakevens"]) == (22000.0 * lots, -290500.0 * lots, [1162.0])
    assert e["profit_unbounded"] is False and e["loss_unbounded"] is False
    assert c["status"] == "candidate" and c["options_selection"]["chosen"]["short_call_from"] == "the call wall"
    assert c["risk_reward"]["net"] is not None and c["payoff"]["sent_to_broker"] is False
    # the same legs through the engine on their own: same figures (never recomputed by the template)
    solo = compute_payoff({"underlying": "RELIANCE", "reference_price": 1200.0, "as_of": ASOF, "legs": c["legs"], "grid": {"from_pct": -25, "to_pct": 25, "points": 121},
                           "costs": COSTS}, TODAY)
    assert solo["valid"] and solo["expiry"]["max_profit"] == e["max_profit"] and solo["capital_at_risk"] == c["payoff"]["capital_at_risk"]


def test_covered_call_falls_back_to_the_first_strike_beyond_one_expected_move():
    # the call wall moved to 1200 = the ATM strike (not above it): the rule uses the first strike at or beyond 1200 + 96 = 1296 -> 1300
    w = world(chain=chain(walls=(1150.0, 1200.0)))
    c = combos(build(w, instrument="combination", **BIG))["covered_call"]
    assert [l["strike"] for l in c["legs"] if l["kind"] == "option"] == [1300.0]
    assert c["options_selection"]["chosen"]["short_call_from"] == "the first strike at or beyond one expected move"
    assert c["payoff"]["expiry"]["max_profit"] == (1300 - 1200 + 20) * 250 * c["sizing"]["quantity"]


def test_protective_put_with_event_risk_closed_form():
    p = build(world(events=EVENT), instrument="combination", min_reward_risk=0.5, **BIG)
    c = combos(p)["protective_put"]
    lots = c["sizing"]["quantity"]
    # the put strike is the listed OTM put nearest the scanner stop 1160 -> 1150 (|1150-1160| = 10, |1100-1160| = 60)
    assert legs_of(c) == [("cash", "buy", lots * 250, 1, 1200.0, None, None), ("option", "buy", lots, 250, 22.0, 1150.0, "put")]
    e = c["payoff"]["expiry"]
    assert (e["max_loss"], e["breakevens"], e["profit_unbounded"], e["max_profit"]) == (-18000.0 * lots, [1222.0], True, None)
    assert c["status"] == "candidate" and "Results are scheduled on 2026-10-28" in c["why_qualifies"][0]
    # results inside the horizon do not block a structure with a long put (its downside is defined): a warning, not a no-trade
    assert any("long put defines the downside" in w for w in c["warnings"]) and "event_in_horizon" not in codes(c)


def test_collar_closed_form():
    c = combos(build(world(events=EVENT), instrument="combination", **BIG))["collar"]
    lots = c["sizing"]["quantity"]
    assert legs_of(c)[1:] == [("option", "buy", lots, 250, 22.0, 1150.0, "put"), ("option", "sell", lots, 250, 38.0, 1250.0, "call")]
    e = c["payoff"]["expiry"]
    assert (e["max_loss"], e["max_profit"], e["breakevens"]) == (-8500.0 * lots, 16500.0 * lots, [1184.0])
    assert c["status"] == "candidate" and c["risk_reward"]["net"] >= RULES["defaults"]["min_reward_risk"]


def test_futures_plus_put_closed_form_and_same_expiry_future():
    w = world(events=EVENT)                                              # long build-up confirmed by cash (fixture default) + results inside the horizon
    c = combos(build(w, instrument="combination", min_reward_risk=0.5, **BIG))["futures_protective_put"]
    lots = c["sizing"]["quantity"]
    # the future is the contract that expires on the options expiry (2026-11-24, settle 1206), not the near month
    assert legs_of(c) == [("future", "buy", lots, 250, 1206.0, None, None), ("option", "buy", lots, 250, 22.0, 1150.0, "put")]
    assert c["legs"][0]["expiry"] == c["legs"][1]["expiry"] == EXPIRY
    e = c["payoff"]["expiry"]
    assert (e["max_loss"], e["breakevens"], e["profit_unbounded"]) == (-19500.0 * lots, [1228.0], True)
    assert c["status"] == "candidate" and e["loss_unbounded"] is False


def test_engine_guard_accepts_every_template_and_refuses_an_uncovered_short_call():
    p = build(world(events=EVENT), instrument="combination", min_reward_risk=0.1, **BIG)
    for fam, c in combos(p).items():
        assert c["payoff"]["valid"] is True and c["payoff"]["expiry"]["loss_unbounded"] is False, fam
    # fewer shares than the short call covers: the engine's own guard refuses it
    legs = [{"kind": "cash", "side": "buy", "quantity": 100, "lot_size": 1, "entry_price": 1200.0},
            {"kind": "option", "side": "sell", "quantity": 1, "lot_size": 250, "entry_price": 38.0, "expiry": EXPIRY, "strike": 1250.0, "option_type": "call"}]
    r = compute_payoff({"underlying": "RELIANCE", "reference_price": 1200.0, "as_of": ASOF, "legs": legs, "grid": {"from_pct": -25, "to_pct": 25, "points": 21}}, TODAY)
    assert r["valid"] is False and r["problems"][0]["code"] == "undefined_risk_not_supported"


# ── when each family qualifies ───────────────────────────────────────────────

def test_insurance_needs_a_reason_and_covered_call_does_not():
    cs = combos(build(world(), instrument="combination", **BIG))
    assert cs["covered_call"]["status"] == "candidate"
    for fam in ("protective_put", "collar", "futures_protective_put"):
        assert cs[fam]["status"] == "no_trade" and codes(cs[fam]) == ["not_indicated"], fam
        assert "no results date inside the horizon" in cs[fam]["reasons"][0]["message"]


def test_high_gap_risk_is_a_reason_without_an_event():
    cs = combos(build(world(scan_row=scan_row(risk_class="high")), instrument="combination", **BIG))
    assert "not_indicated" not in codes(cs["protective_put"])
    assert "not_indicated" not in codes(cs["collar"]) and "gap risk" in cs["collar"]["why_qualifies"][0]


def test_event_inside_the_horizon_blocks_the_unhedged_covered_call_but_not_the_hedged_structures():
    cs = combos(build(world(events=EVENT), instrument="combination", **BIG))
    assert cs["covered_call"]["status"] == "no_trade" and "event_in_horizon" in codes(cs["covered_call"])
    assert cs["collar"]["status"] == "candidate" and "event_in_horizon" not in codes(cs["collar"])
    # avoid_events off: the covered call is accepted with the gap-risk warning
    cs2 = combos(build(world(events=EVENT), instrument="combination", avoid_events=False, **BIG))
    assert cs2["covered_call"]["status"] == "candidate" and any("gap risk is accepted" in w for w in cs2["covered_call"]["warnings"])


def test_futures_plus_put_follows_the_futures_build_up_rule():
    opp = combos(build(world(events=EVENT, buildup=buildup("short_buildup")), instrument="combination", **BIG))["futures_protective_put"]
    assert opp["status"] == "no_trade" and codes(opp) == ["buildup_opposes_view"]              # existing rule: opposing build-up is no trade
    unc = combos(build(world(events=EVENT, buildup=buildup(cc=None)), instrument="combination", **BIG))["futures_protective_put"]
    assert unc["status"] == "wait" and codes(unc) == ["cash_not_confirming"]
    cov = combos(build(world(events=EVENT, buildup=buildup("short_covering")), instrument="combination", **BIG))["futures_protective_put"]
    assert cov["status"] == "wait" and codes(cov) == ["no_fresh_buildup"]
    # options are still evaluated when the build-up opposes (the existing rule only stops the futures candidate)
    p = build(world(buildup=buildup("short_buildup")), instrument="all", **BIG)
    assert cand(p, "futures:long_buildup_continuation")["status"] == "no_trade"
    assert cand(p, "options:bull_call_spread")["status"] in ("candidate", "no_trade") and cand(p, "options:bull_call_spread")["legs"]


def test_a_stock_outside_fno_gets_cash_only_with_the_reason():
    w = world(scan_row=scan_row(fno_eligible=False), chain=src_fail("RELIANCE has no F&O contracts", "x"), futures=src_fail("none", "x"),
              expiries=src_fail("none", "x"), buildup=src_fail("none", "x"))
    p = build(w, instrument="all", **BIG)
    cs = [c for c in p["candidates"] if c["segment"] == "combination"]
    assert len(cs) == 1 and cs[0]["status"] == "no_trade" and codes(cs[0]) == ["not_fno_eligible"] and "only the cash idea applies" in cs[0]["reasons"][0]["message"]
    assert cand(p, "cash:breakout_continuation")["status"] == "candidate" and p["status"] == "plan"
    # futures and options say why they are absent instead of failing on a missing chain
    assert [(c["id"], c["status"], codes(c)) for c in p["candidates"] if c["segment"] in ("futures", "options")] == [
        ("futures:none", "no_trade", ["not_fno_eligible"]), ("options:none", "no_trade", ["not_fno_eligible"])]


def test_bearish_view_has_no_combination_and_neutral_view_keeps_the_income_structures_only():
    p = build(world(), instrument="combination", direction="bearish", **BIG)
    assert [c["family"] for c in p["candidates"]] == ["none"] and codes(p["candidates"][0]) == ["no_combination_for_view"]
    n = combos(build(world(), instrument="combination", direction="neutral", **BIG))
    assert sorted(n) == ["collar", "covered_call"]


def test_illiquid_short_call_or_unpriced_put_means_no_trade():
    dead = combos(build(world(chain=chain(calls={1250.0: (38.0, 0, 8000, 22.5)})), instrument="combination", **BIG))["covered_call"]
    assert dead["status"] == "no_trade" and "illiquid_leg" in codes(dead)
    noprice = combos(build(world(chain=chain(puts={1150.0: (None, 25000, 6000, 24.0)}), events=EVENT), instrument="combination", **BIG))["protective_put"]
    assert noprice["status"] == "no_trade" and "legs_unpriced" in codes(noprice)


def test_stale_chain_is_a_wait_and_not_actionable():
    c = combos(build(world(chain=chain(as_of="2026-10-16")), instrument="combination", **BIG))["covered_call"]
    assert c["status"] == "wait" and "stale_chain" in codes(c) and c["actionable"] is False


def test_sizing_in_whole_lots_and_too_small_is_no_trade():
    c = combos(build(world(), instrument="combination", capital=100_000, risk_budget_inr=5_000))["covered_call"]
    assert c["status"] == "no_trade" and "sizing_zero" in codes(c)          # one lot is Rs 2.9 lakh: the 25% cap of Rs 1 lakh buys none
    inc = combos(build(world(), instrument="combination", capital=None, risk_budget_inr=None))["covered_call"]  # no capital or budget: incomplete, shown for 1 lot, never a guessed size
    assert inc["sizing"]["status"] == "incomplete" and inc["legs"][0]["quantity"] == 250 and inc["legs"][1]["quantity"] == 1


def test_include_combinations_switch_and_all_includes_them_by_default():
    assert any(c["segment"] == "combination" for c in build(world(), instrument="all", **BIG)["candidates"])
    assert not any(c["segment"] == "combination" for c in build(world(), instrument="all", include_combinations=False, **BIG)["candidates"])
    assert {c["segment"] for c in build(world(), instrument="combination", **BIG)["candidates"]} == {"combination"}
    i, _ = normalise_inputs({"underlying": "TCS", "direction": "bullish"})
    assert i["include_combinations"] is True and "include_combinations" in i["defaults_applied"]
    assert normalise_inputs({"underlying": "TCS", "direction": "bullish", "include_combinations": "no"})[1][0]["code"] == "bad_include_combinations"
    assert STRATEGY_RULES_VERSION.startswith("strategy-rules.v1.3") and set(RULES["combinations"]["views"]) == set(cd.COMBO_ORDER)


def test_a_scanner_pick_without_a_bucket_is_read_by_its_stage_and_says_so():
    from services.strategy_plan.sources import scanner_snapshot
    pick = {"stage": "BREAKOUT", "entry_price": 1200.0, "stoploss": 1160.0, "target_price": 1280.0, "final_score": 0.9}
    snap = scanner_snapshot("RELIANCE", None, None, pick, ASOF, "v")
    assert snap["data"]["bucket"] is None and snap["data"]["pick_stage"] == "BREAKOUT" and snap["data"]["item"]["stop_price"] == 1160.0
    c = cand(build(world(scanner_bucket=snap), instrument="cash", **BIG), "cash:breakout_continuation")
    assert c["status"] == "candidate" and any("scanner pick (stage BREAKOUT)" in w for w in c["why_qualifies"])
    early = scanner_snapshot("RELIANCE", None, None, dict(pick, stage="EARLY_BREAKOUT"), ASOF, "v")
    assert cand(build(world(scanner_bucket=early), instrument="cash", **BIG), "cash:breakout_watch")["status"] == "wait"
    # a pick that is also in the watchlist: the bucket stays, the pick's stop wins
    both = scanner_snapshot("RELIANCE", "breakout_confirmed", {"nse_symbol": "RELIANCE", "trigger_price": 1195.0, "stop_price": 1150.0}, pick, ASOF, "v")
    assert both["data"]["bucket"] == "breakout_confirmed" and both["data"]["item"]["stop_price"] == 1160.0 and "pick_stage" not in both["data"]


# ── selection ────────────────────────────────────────────────────────────────

def witem(sym, score, bucket_="breakout_confirmed", **o):
    d = {"nse_symbol": sym, "sector": "S", "stage": "BREAKOUT", "confidence": "HIGH", "final_score": score, "close_price": 1000.0, "trigger_price": 990.0,
         "stop_price": 950.0, "atr_pct": 2.0, "why": f"{sym} why", "spark_closes": [990.0, 1000.0], "spark_end": ASOF, "avg_traded_value_cr_20d": 50.0}
    d.update(o)
    return d, bucket_


def watch_body(*items):
    b = {x: [] for x in sel.BUCKETS}
    for d, bk in items:
        b[bk].append(d)
    return {"as_of_date": ASOF, "buckets": b, "_classifier_version": "smart_v2"}


def pick(sym, score, **o):
    d = {"nse_symbol": sym, "final_score": score, "confidence": "HIGH", "stage": "BREAKOUT", "entry_price": 1010.0, "stoploss": 960.0, "target_price": 1110.0,
         "risk_reward": None, "timeframe_days_min": 5, "timeframe_days_max": 15, "reasons": ["r1", "r2"], "spark_closes": [1.0, 2.0], "spark_end": ASOF,
         "avg_traded_value_cr_20d": 40.0, "signal_date": ASOF}
    d.update(o)
    return d


def merged():
    w = watch_body(witem("ICICIBANK", 0.80), witem("TCS", 0.70, "pre_breakout", stage="EARLY_BREAKOUT"), witem("INFY", 0.65, "trend_continuation", stage="ACCUMULATION"))
    p = {"signal_date": ASOF, "picks": [pick("TCS", 0.72), pick("HDFCBANK", 0.90, avg_traded_value_cr_20d=None)]}
    return w, p


def test_merge_mirrors_the_overview_card_picks_win_for_levels_score_x100_ranked():
    w, p = merged()
    m = sel.merge_setups(w, p)
    assert [s["symbol"] for s in m] == ["HDFCBANK", "ICICIBANK", "TCS", "INFY"]
    by = {s["symbol"]: s for s in m}
    tcs = by["TCS"]
    assert tcs["bucket"] == "pre_breakout" and tcs["status"] == "awaiting"           # the bucket keeps saying where the setup stands
    assert (tcs["score"], tcs["entry"], tcs["stop"], tcs["target"]) == (pytest.approx(72.0), 1010.0, 960.0, 1110.0)   # the pick's score and plan win
    assert tcs["risk_reward"] == pytest.approx(2.0) and tcs["in_watchlist"] and tcs["in_picks"] and (tcs["days_min"], tcs["days_max"]) == (5, 15)
    assert by["ICICIBANK"]["entry"] == 990.0 and by["ICICIBANK"]["stop"] == 950.0 and by["ICICIBANK"]["target"] is None and by["ICICIBANK"]["risk_reward"] is None
    h = by["HDFCBANK"]
    assert h["bucket"] is None and h["status"] == "confirmed" and h["in_picks"] and not h["in_watchlist"] and h["score"] == pytest.approx(90.0)
    v = sel.scanner_view(h)
    assert v["close"] == 2.0 and v["close_date"] == ASOF and v["entry"] == 1010.0 and v["reason"] == "r1; r2"      # the last spark close, never the entry


def test_pick_reasons_sent_as_a_json_string_are_read_as_a_list():
    p = {"signal_date": ASOF, "picks": [pick("HAL", 0.76, reasons='["Strong uptrend (above 50 & 200 DMA)", "RSI 61"]', timeframe_days_min=7.0, timeframe_days_max=20.0)]}
    s = sel.merge_setups({"buckets": {}}, p)[0]
    assert s["reasons"] == ["Strong uptrend (above 50 & 200 DMA)", "RSI 61"] and (s["days_min"], s["days_max"]) == (7, 20)
    assert sel.scanner_view(s)["reason"] == "Strong uptrend (above 50 & 200 DMA); RSI 61"
    assert sel._strs("not json") == ["not json"] and sel._strs(None) == []


def gate_row(sym, **o):
    r = {"symbol": sym, "close": 100.0, "prev_close": 99.0, "traded_value_cr_20d": 50.0, "has_reference": True, "series": "EQ", "is_etf": False,
         "price_band_pct": 20.0, "fno_eligible": True}
    r.update(o)
    return r


def patch_scanner(monkeypatch, watch, picks, rows="default", fails=None):
    async def fake_read(request):
        return watch, picks, fails or []

    async def fake_gate():
        if rows is None:
            return None, None, "upstream_unavailable"
        r = {s: gate_row(s) for s in ("HDFCBANK", "ICICIBANK", "TCS", "INFY")} if rows == "default" else rows
        return r, ASOF, None
    monkeypatch.setattr(sel, "read_scanner", fake_read)
    monkeypatch.setattr(sel, "_gate_rows", fake_gate)


def run(coro):
    return asyncio.run(coro)


def test_selection_eligible_versus_excluded_with_reasons(monkeypatch):
    w, p = merged()
    rows = {"HDFCBANK": gate_row("HDFCBANK", series="BZ"), "ICICIBANK": gate_row("ICICIBANK"), "TCS": gate_row("TCS", traded_value_cr_20d=5.0),
            "INFY": gate_row("INFY", is_etf=False)}
    patch_scanner(monkeypatch, w, p, rows)
    out = run(sel.select_opportunities(None, 2))
    assert [s["symbol"] for s in out["setups"]] == ["ICICIBANK", "INFY"] and out["selected"] == 2 and out["considered"] == 4 and out["limit"] == 2
    assert [(x["symbol"], x["code"]) for x in out["excluded"]] == [("HDFCBANK", "series"), ("TCS", "illiquid")]
    assert "crore" in out["excluded"][1]["reason"] and out["scan_date"] == ASOF and out["empty_reason"] is None
    assert out["gate"].startswith("scan snapshot eligibility gates")
    # the limit is clamped to 1..15
    assert run(sel.select_opportunities(None, 99))["limit"] == 15


def test_selection_without_the_snapshot_uses_the_scanners_own_liquid_flag(monkeypatch):
    w, p = merged()
    patch_scanner(monkeypatch, w, p, None)
    out = run(sel.select_opportunities(None, 8))
    # HDFCBANK is a pick with no traded value from the scanner: cannot be tested, so excluded; the others carry 50 / 40 / 50 Cr
    assert [s["symbol"] for s in out["setups"]] == ["ICICIBANK", "TCS", "INFY"]
    assert out["excluded"][0]["symbol"] == "HDFCBANK" and "scanner's own liquid flag" in out["gate"] and "upstream_unavailable" in out["gate"]


def test_selection_empty_scanner_is_an_empty_list_with_the_reason(monkeypatch):
    patch_scanner(monkeypatch, {"as_of_date": None, "buckets": {}, "_reason": "no technical features yet"}, {"signal_date": None, "picks": [], "message": "no signals available yet"})
    out = run(sel.select_opportunities(None, 8))
    assert out["setups"] == [] and out["selected"] == 0 and out["considered"] == 0
    assert out["empty_reason"].startswith("scanner tables empty") and "no signals available yet" in out["empty_reason"]
    patch_scanner(monkeypatch, None, None, fails=["watchlist: boom", "picks: boom"])
    out = run(sel.select_opportunities(None, 8))
    assert out["setups"] == [] and "could not be read" in out["empty_reason"] and out["source_failures"] == ["watchlist: boom", "picks: boom"]


def test_selection_one_scanner_route_failing_still_lists_the_other(monkeypatch):
    w, _ = merged()
    patch_scanner(monkeypatch, w, None, fails=["picks: HTTP 500"])
    out = run(sel.select_opportunities(None, 8))
    assert [s["symbol"] for s in out["setups"]] == ["ICICIBANK", "TCS", "INFY"] and out["source_failures"] == ["picks: HTTP 500"]


def test_read_scanner_calls_the_routes_with_the_desks_limits_and_explicit_defaults(monkeypatch):
    from routes import positional
    seen: Dict[str, Any] = {}

    async def w(request, limit):
        seen["watch"] = limit
        return {"buckets": {}}

    async def p(request, date, min_score, stage, limit):          # a FastAPI Query() default would not match these values
        seen["picks"] = (date, min_score, stage, limit)
        return {"picks": []}
    monkeypatch.setattr(positional, "get_watchlist", w)
    monkeypatch.setattr(positional, "get_picks", p)
    out = run(sel.read_scanner(None))
    assert seen == {"watch": 30, "picks": (None, 0.55, None, 30)} and out[2] == []


# ── the ideas route ──────────────────────────────────────────────────────────

A = {"X-Test-User": "user_a"}
SYMS = ["ICICIBANK", "TCS", "INFY", "HDFCBANK", "SBIN", "AXISBANK"]


def fake_selection(n=6, empty=None):
    w = watch_body(*[witem(s, 0.9 - i * 0.05) for i, s in enumerate(SYMS[:n])])
    return {"source": "AI scanner (watchlist + picks), end of day", "rule": sel.SELECTION_RULE, "limit": 8, "scan_date": ASOF, "watchlist_as_of": ASOF,
            "watchlist_version": "smart_v2", "signal_date": ASOF, "considered": n + 2,
            "selected": n, "excluded": [{"symbol": "ZZZ", "code": "illiquid", "reason": "thin"}], "setups": sel.merge_setups(w, None)[:n],
            "empty_reason": empty, "source_failures": [], "gate": "scan snapshot eligibility gates", "gate_as_of": ASOF}


@pytest.fixture
def client(monkeypatch):
    fake = FakeDb()
    monkeypatch.setattr(route, "db", fake)
    monkeypatch.setattr(route, "utcnow", lambda: NOW)
    monkeypatch.setattr(route, "today", lambda: TODAY)
    state: Dict[str, Any] = {"selection": fake_selection(), "calls": [], "live": 0, "peak": 0, "fail": set(), "limit": None, "shared": []}

    async def fake_select(request, limit):
        state["limit"] = limit
        return state["selection"]

    async def fake_shared(user_id):
        state["shared"].append(user_id)
        return {"regime": src_ok({}, "x"), "sectors": src_ok({}, "x"), "portfolio": src_ok([], "x"), "sector_lists": {}}

    async def fake_collect(request, user_id, inp, today, shared=None):
        state["calls"].append((inp["underlying"], dict(shared or {})))
        state["live"] += 1
        state["peak"] = max(state["peak"], state["live"])
        try:
            await asyncio.sleep(0.01)
            if inp["underlying"] in state["fail"]:
                raise RuntimeError("source exploded")
            return world()
        finally:
            state["live"] -= 1

    monkeypatch.setattr(ideas_mod, "select_opportunities", fake_select)
    monkeypatch.setattr(ideas_mod, "shared_for_ideas", fake_shared)
    monkeypatch.setattr(ideas_mod, "collect_snapshots", fake_collect)

    async def fake_name(symbol):
        return {"TCS": "Tata Consultancy Services Ltd"}.get(symbol)
    monkeypatch.setattr(ideas_mod, "company_name", fake_name)

    async def fake_user(request: Request):
        uid = request.headers.get("X-Test-User")
        if not uid:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {"user_id": uid}

    monkeypatch.setattr(route, "get_current_user", fake_user)
    app = FastAPI()
    app.include_router(route.router)
    c = TestClient(app)
    c.fake, c.state = fake, state
    return c


IDEAS_BODY = {"limit": 6, **BIG, "costs": COSTS}


def test_ideas_route_requires_sign_in_and_validates(client):
    assert client.post("/api/desk/strategy/ideas", json={}).status_code == 401
    for body, code in (({"limit": 0}, "bad_limit"), ({"limit": 16}, "bad_limit"), ({"limit": "8"}, "bad_limit"), ({"capital": -1}, "bad_capital"),
                       ({"avoid_events": "yes"}, "bad_avoid_events"), ({"include_combinations": 1}, "bad_include_combinations"), ({"min_reward_risk": "x"}, "bad_min_reward_risk")):
        r = client.post("/api/desk/strategy/ideas", json=body, headers=A)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_input" and code in {p["code"] for p in r.json()["detail"]["problems"]}, body
    assert client.post("/api/desk/strategy/ideas", content=b"{nope", headers=A).status_code == 422
    assert client.post("/api/desk/strategy/ideas", json=[], headers=A).status_code == 422


def test_ideas_response_shape_and_ranking(client):
    r = client.post("/api/desk/strategy/ideas", json=IDEAS_BODY, headers=A)
    assert r.status_code == 200
    b = r.json()
    assert {"generated_at", "data_as_of", "rules_version", "calculation_version", "sent_to_broker", "selection", "inputs", "ranking_note", "ideas"} <= set(b)
    assert b["sent_to_broker"] is False and b["rules_version"] == STRATEGY_RULES_VERSION and b["calculation_version"] == "payoff-v1"
    s = b["selection"]
    assert {"source", "scan_date", "rule", "considered", "selected", "excluded", "limit"} <= set(s) and s["limit"] == 6 and s["selected"] == 6
    assert s["excluded"][0]["symbol"] == "ZZZ" and client.state["limit"] == 6
    assert "defaults_applied" in b["inputs"] and b["inputs"]["limit"] == 6 and b["inputs"]["capital"] == 5_000_000
    assert "probability" in b["ranking_note"] and "composite" in b["ranking_note"]
    # scanner rank kept (score order)
    assert [i["symbol"] for i in b["ideas"]] == SYMS and [i["rank"] for i in b["ideas"]] == [1, 2, 3, 4, 5, 6]
    i = b["ideas"][0]
    assert {"rank", "symbol", "name", "scanner", "direction", "fno_eligible", "plan_id", "plan_status", "status_reasons", "would_change_if", "headline", "evidence_summary",
            "oi_view", "preferred", "strategies", "plan_inputs"} <= set(i)
    assert {"bucket", "status", "score", "close", "close_date", "entry", "stop", "target", "reason", "horizon_days", "liquidity_cr", "atr_pct"} <= set(i["scanner"])
    assert i["direction"] == "bullish" and i["fno_eligible"] is True and i["plan_status"] == "plan" and i["plan_id"].startswith("plan_")
    assert i["headline"]["model_estimate"]["status"] == "withheld" and set(i["evidence_summary"]) >= {"technical", "fundamental", "derivatives"}
    assert set(i["evidence_summary"]["technical"]) == {"supports", "conflicts", "neutral", "unavailable"}
    assert {"buildup", "cash_confirmation", "pcr", "max_pain", "call_wall", "put_wall", "source_as_of"} <= set(i["oi_view"])
    assert i["oi_view"]["buildup"] == "long_buildup" and i["oi_view"]["call_wall"] == 1250.0 and i["oi_view"]["put_wall"] == 1150.0 and i["oi_view"]["source_as_of"] == ASOF
    segs = {x["segment"] for x in i["strategies"]}
    assert segs == {"cash", "futures", "options", "combination"}
    for st in i["strategies"]:
        assert {"id", "segment", "family", "label", "status", "reasons", "legs_text", "max_loss", "max_loss_basis", "capital_at_risk", "max_profit", "profit_unbounded",
                "breakeven", "reward_risk_net", "sizing", "liquidity_flags", "why", "flags"} <= set(st), st["id"]
        assert set(st["sizing"]) >= {"status", "quantity", "lots", "binding"}
    # preferred = the viable strategy with the best net reward:risk
    viable = [x for x in i["strategies"] if x["status"] == "candidate"]
    assert i["preferred"] == max(viable, key=lambda x: (x["reward_risk_net"] if x["reward_risk_net"] is not None else -1e9))["id"]
    bcs = next(x for x in i["strategies"] if x["id"] == "options:bull_call_spread")
    assert bcs["legs_text"] == f"Buy {bcs['sizing']['lots']} lot{'s' if bcs['sizing']['lots'] != 1 else ''} RELIANCE 1200 call + Sell {bcs['sizing']['lots']} lot{'s' if bcs['sizing']['lots'] != 1 else ''} RELIANCE 1250 call, 24 Nov".replace("RELIANCE", i["symbol"])
    cc = next(x for x in i["strategies"] if x["id"] == "combination:covered_call")
    assert cc["legs_text"].startswith(f"Buy {cc['sizing']['quantity']} shares {i['symbol']} + Sell {cc['sizing']['lots']} lot") and cc["legs_text"].endswith("1250 call, 24 Nov")


def test_ideas_numbers_come_from_the_plan_and_plan_inputs_rebuild_the_same_plan(client):
    b = client.post("/api/desk/strategy/ideas", json=IDEAS_BODY, headers=A).json()
    i = b["ideas"][1]
    assert i["name"] == "Tata Consultancy Services Ltd" and b["ideas"][0]["name"] is None       # from the symbol master; null when it has none
    rebuilt_in, probs = normalise_inputs(i["plan_inputs"])
    assert not probs and i["plan_inputs"] == {"underlying": "TCS", "direction": "bullish", "instrument": "all", "capital": 5_000_000, "risk_budget_inr": 50_000, "costs": COSTS}
    plan = pl.build_plan(rebuilt_in, world(), NOW, TODAY)
    assert plan["plan_id"] == i["plan_id"] and plan["preferred"] == i["preferred"]
    for st in i["strategies"]:
        c = cand(plan, st["id"])
        ex = (c.get("payoff") or {}).get("expiry") or {}
        assert st["max_profit"] == ex.get("max_profit") and st["capital_at_risk"] == (c.get("payoff") or {}).get("capital_at_risk")
        assert st["breakeven"] == (ex.get("breakevens") or []) and st["reward_risk_net"] == c["risk_reward"].get("net")
    # the covered call row quotes the engine's own max loss
    cc = next(x for x in i["strategies"] if x["id"] == "combination:covered_call")
    cash = next(x for x in i["strategies"] if x["id"] == "cash:breakout_continuation")
    assert cash["max_loss"] == -cand(plan, cash["id"])["risk_reward"]["risk_net"] < 0                  # a loss is a negative P&L in every row
    assert cc["max_loss"] == -290500.0 * cc["sizing"]["lots"] and cc["max_profit"] == 22000.0 * cc["sizing"]["lots"]


def test_ideas_use_the_shared_scanner_data_and_one_shared_read(client):
    client.post("/api/desk/strategy/ideas", json=IDEAS_BODY, headers=A)
    st = client.state
    assert st["shared"] == ["user_a"]                                    # regime, sectors and holdings are read once for the whole request
    assert [c[0] for c in st["calls"]] == SYMS
    for sym, shared in st["calls"]:
        assert set(shared) >= {"regime", "sectors", "portfolio", "sector_lists", "scanner_bucket"} and set(shared["scanner_bucket"]) == {sym}
        snap = shared["scanner_bucket"][sym]
        assert snap["ok"] and snap["data"]["bucket"] == "breakout_confirmed" and snap["data"]["item"]["stop_price"] == 950.0   # no per-symbol watchlist read
    assert all(c[1]["sector_lists"] is st["calls"][0][1]["sector_lists"] for c in st["calls"])      # one memo for the request


def test_concurrency_is_bounded_at_four(client):
    r = client.post("/api/desk/strategy/ideas", json=IDEAS_BODY, headers=A)
    assert r.status_code == 200 and len(r.json()["ideas"]) == 6
    assert 1 < client.state["peak"] <= ideas_mod.CONCURRENCY == 4


def test_a_failing_symbol_becomes_an_insufficient_data_idea_never_an_exception(client):
    client.state["fail"] = {"INFY"}
    r = client.post("/api/desk/strategy/ideas", json=IDEAS_BODY, headers=A)
    assert r.status_code == 200
    ideas = r.json()["ideas"]
    bad = next(i for i in ideas if i["symbol"] == "INFY")
    assert bad["plan_status"] == "insufficient_data" and bad["strategies"] == [] and bad["plan_id"] is None
    assert bad["status_reasons"][0]["code"] == "idea_build_failed" and "source exploded" in bad["status_reasons"][0]["message"]
    assert bad["plan_inputs"]["underlying"] == "INFY" and bad["scanner"]["bucket"] == "breakout_confirmed"
    assert [i["plan_status"] for i in ideas if i["symbol"] != "INFY"] == ["plan"] * 5


def test_empty_scanner_gives_an_empty_list_with_the_reason_and_reads_nothing_else(client):
    client.state["selection"] = fake_selection(0, empty="scanner tables empty: the scanner has no setups in its latest end-of-day run.")
    client.state["selection"].update(selected=0, considered=0, excluded=[])
    r = client.post("/api/desk/strategy/ideas", json={}, headers=A)
    b = r.json()
    assert r.status_code == 200 and b["ideas"] == [] and b["selection"]["empty_reason"].startswith("scanner tables empty") and b["selection"]["selected"] == 0
    assert client.state["calls"] == [] and client.state["shared"] == []
    assert client.state["limit"] == 8 and b["inputs"]["limit"] == 8 and "limit" in b["inputs"]["defaults_applied"]


def test_ideas_write_nothing_and_send_nothing_to_a_broker(client):
    r = client.post("/api/desk/strategy/ideas", json=IDEAS_BODY, headers=A)
    assert client.fake.col.writes == 0 and r.json()["sent_to_broker"] is False
    assert all(s["sent_to_broker"] is False for i in r.json()["ideas"] for s in [{"sent_to_broker": False}])
    import services.strategy_plan.ideas as m1, services.strategy_plan.selection as m2
    src = "".join(open(m.__file__).read() for m in (m1, m2))
    for word in ("place_order", "broker_native", "insert_one", "update_one", "delete_one", "httpx", "write_text"):
        assert word not in src


def test_the_include_combinations_switch_reaches_every_idea(client):
    b = client.post("/api/desk/strategy/ideas", json={**IDEAS_BODY, "include_combinations": False}, headers=A).json()
    assert b["inputs"]["include_combinations"] is False
    assert all(not any(s["segment"] == "combination" for s in i["strategies"]) for i in b["ideas"])
    assert all(i["plan_inputs"]["include_combinations"] is False for i in b["ideas"])


def test_a_stock_outside_fno_is_reported_cash_only(client, monkeypatch):
    async def collect(request, user_id, inp, today, shared=None):
        return world(scan_row=scan_row(fno_eligible=False), chain=src_fail("no contracts", "x"), futures=src_fail("none", "x"), expiries=src_fail("none", "x"),
                     buildup=src_fail("none", "x"))
    monkeypatch.setattr(ideas_mod, "collect_snapshots", collect)
    i = client.post("/api/desk/strategy/ideas", json={**IDEAS_BODY, "limit": 1}, headers=A).json()["ideas"][0]
    assert i["fno_eligible"] is False and i["preferred"] == "cash:breakout_continuation"
    assert {s["segment"]: s["reasons"][0]["code"] for s in i["strategies"] if s["segment"] != "cash"} == {"futures": "not_fno_eligible", "options": "not_fno_eligible", "combination": "not_fno_eligible"}
    assert i["oi_view"]["buildup"] is None and i["oi_view"]["unavailable"]


def test_legs_text_formats():
    legs = [{"kind": "cash", "side": "buy", "quantity": 250, "lot_size": 1}, {"kind": "option", "side": "sell", "quantity": 1, "lot_size": 250, "strike": 1250.0,
                                                                         "option_type": "call", "expiry": "2026-11-24"}]
    assert ideas_mod.legs_text("RELIANCE", legs) == "Buy 250 shares RELIANCE + Sell 1 lot RELIANCE 1250 call, 24 Nov"
    assert ideas_mod.legs_text("X", [{"kind": "future", "side": "buy", "quantity": 2, "lot_size": 10, "expiry": "2026-10-27"}]) == "Buy 2 lots X future, 27 Oct"
    assert ideas_mod.legs_text("X", []) == ""


# ── sources: shared reads and the company name ───────────────────────────────

def test_collect_snapshots_uses_the_shared_reads_and_never_re_reads_them(monkeypatch):
    from services.strategy_plan import sources as src
    reads: List[str] = []

    async def spy(name):
        reads.append(name)
        return src_fail("not under test", name)

    def make(name):
        async def f(*a, **k):
            return await spy(name)
        return f
    for name in ("_regime", "_sectors", "_indicators", "_patterns", "_scan_snapshot", "_features", "_financials", "_announcements", "_events", "_corporate_actions",
                 "_buildup", "_futures", "_expiries", "_calibration", "_scanner_bucket", "_portfolio"):
        monkeypatch.setattr(src, name, make(name))
    mine = {"regime": src_ok({"key": "bullish"}, "shared"), "sectors": src_fail("shared down", "shared"), "portfolio": src_ok([], "shared"),
            "scanner_bucket": {"TCS": src_ok({"bucket": "pre_breakout", "item": None}, "shared scanner")}, "sector_lists": {}}
    i, _ = normalise_inputs({"underlying": "TCS", "direction": "bullish"})
    snaps = run(src.collect_snapshots(None, "u", i, TODAY, mine))
    assert snaps["regime"] is mine["regime"] and snaps["sectors"] is mine["sectors"] and snaps["portfolio"] is mine["portfolio"]
    assert snaps["scanner_bucket"]["data"]["bucket"] == "pre_breakout"
    assert not {"_regime", "_sectors", "_portfolio", "_scanner_bucket"} & set(reads) and {"_indicators", "_buildup", "_expiries"} <= set(reads)
    # another symbol's scanner snapshot is not used for this one: it is read as usual
    reads.clear()
    run(src.collect_snapshots(None, "u", normalise_inputs({"underlying": "INFY", "direction": "bullish"})[0], TODAY, mine))
    assert "_scanner_bucket" in reads


def test_sector_index_lists_are_read_once_per_request(monkeypatch):
    from services.strategy_plan import sources as src
    calls: List[str] = []

    async def lst(name):
        calls.append(name)
        return ["TCS", "INFY"]
    monkeypatch.setattr(src.daas_client, "get_index_constituents", lst)
    sectors = src_ok({"sectors": [{"index": "Nifty IT"}, {"index": "Nifty Bank"}]}, "x")
    memo: Dict[str, Any] = {}

    async def both():
        return await asyncio.gather(src._sector_members("TCS", sectors, memo), src._sector_members("INFY", sectors, memo))
    a, b = run(both())
    assert sorted(calls) == ["Nifty Bank", "Nifty IT"] and a["data"]["member_of"] == ["Nifty IT", "Nifty Bank"] and b["ok"]


def test_company_name_is_an_exact_symbol_match_or_none(monkeypatch):
    from services.strategy_plan import sources as src

    async def search(q, limit=8):
        return {"data": [{"symbol": "TCSEXTRA", "company_name": "Other"}, {"symbol": "TCS", "company_name": "Tata Consultancy Services Ltd"}]}
    monkeypatch.setattr(src.daas_client, "search_symbols", search)
    assert run(src.company_name("TCS")) == "Tata Consultancy Services Ltd" and run(src.company_name("TC")) is None

    async def boom(q, limit=8):
        raise RuntimeError("down")
    monkeypatch.setattr(src.daas_client, "search_symbols", boom)
    assert run(src.company_name("TCS")) is None
