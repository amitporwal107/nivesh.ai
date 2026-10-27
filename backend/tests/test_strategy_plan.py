"""Strategy plan builder (services/strategy_plan evidence, candidates, plan) and its routes: PRD §16.2 to §16.5, §16.7 to §16.9, §17.3 to §17.5.

No network and no real database. Everything below the plan builder is MOCK — not real data: round numbers chosen so the
arithmetic can be done by hand (worked in the comments). The source snapshots are built the way services/strategy_plan/sources.py
builds them; the builder under test is pure, the payoff is the real compute_payoff.

Fixture world (RELIANCE-like, price day 2026-10-19, "today" 2026-10-20):
    close 1200, ATR14 20, EMA20 1190 / EMA50 1150 / EMA200 1100, support20 1130, resistance20 1290 (90 away: not a cap, see below)
    cash: scanner bucket breakout_confirmed, scanner stop 1160 (risk 40 a share); base target 1200 + 2 x 40 = 1280
    chain 2026-11-24 (36 days), lot 250, strikes 1100..1300 step 50, put wall 1150 (OI 25000), call wall 1250 (OI 30000), expected move 96
Costs in every plan input: slippage 0.05% of traded value + Rs 20 a side.
"""
from __future__ import annotations

import copy
import json
import math
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

import routes.strategy_plan as route
from services.strategy_plan import candidates as cd
from services.strategy_plan import compute_payoff, explain_plan_context, normalise_inputs
from services.strategy_plan import evidence as ev
from services.strategy_plan import live_reads as lr
from services.strategy_plan import plan as pl
from services.strategy_plan.evidence import src_fail, src_ok
from services.strategy_plan.rules import RULES, STRATEGY_RULES_VERSION

TODAY = date(2026, 10, 20)
ASOF = "2026-10-19"
NOW = datetime(2026, 10, 20, 4, 0, tzinfo=timezone.utc)
COSTS = {"slippage_pct": 0.05, "brokerage_per_side": 20.0}
EXPIRY = "2026-11-24"


# ── MOCK source snapshots ────────────────────────────────────────────────────

def values(**o):
    v = {"close": 1200.0, "ema20": 1190.0, "ema50": 1150.0, "ema200": 1100.0, "rsi14": 62.0, "atr14": 20.0, "atr_pct": 1.67,
         "macd_hist": 1.5, "roc20": 4.0, "rvol20": 1.8, "avg_traded_value_cr20": 500.0, "support20": 1130.0, "resistance20": 1290.0,
         "rs63": {"stock_return_pct": 8.0, "benchmark_return_pct": 5.0, "excess_pct": 3.0, "from": "2026-07-14", "to": ASOF}}
    v.update(o)
    return v


def indicators(**o):
    return src_ok({"symbol": "RELIANCE", "values": values(**o), "benchmark": {"name": "Nifty 50", "reason": None},
                   "hypothetical_levels": {"entry": 1200.0, "stop": 1160.0, "target": 1280.0}}, "MOCK nidp.prices_eod_adjusted", ASOF, "mock-indicators")


def regime(key="bullish"):
    return src_ok({"key": key, "label": key.title(), "date": ASOF, "reason": None,
                   "inputs": {"trend": {"bullish": "up", "bearish": "down", "sideways": "flat"}.get(key, "flat"), "nifty_vs_average_pct": 2.1,
                              "india_vix": 13.0, "volatility_high": False, "breadth": "up", "advancing_share_pct": 61.0, "advances": 1200, "declines": 760}},
                  "MOCK macro_engine.classify_desk_regime", ASOF)


def sectors(**ret1m):
    # MOCK — not real data: six sector indices; 1-month returns (rank, strongest first): Energy 3.0 (1), Oil & Gas 2.0 (2),
    # Auto 1.0 (3), Pharma -0.5 (4), Bank -2.0 (5), IT -3.0 (6). band_n = ceil(6 / 3) = 2: ranks 1-2 top, 5-6 bottom.
    r1m = {"Nifty Energy": 3.0, "Nifty Oil & Gas": 2.0, "Nifty Auto": 1.0, "Nifty Pharma": -0.5, "Nifty Bank": -2.0, "Nifty IT": -3.0}
    r1m.update(ret1m)
    rows = [{"index": n, "sector": n.replace("Nifty ", ""), "date": ASOF, "close": 40000.0, "ret_1d_pct": 0.4, "ret_1w_pct": 1.2, "ret_1m_pct": v}
            for n, v in r1m.items()]
    return src_ok({"as_of": ASOF, "sectors": rows}, "MOCK DaaS sector-returns", ASOF)


def sector_members(symbol="RELIANCE", member_of=("Nifty Energy", "Nifty Oil & Gas"), unreadable=None):
    return src_ok({"symbol": symbol, "member_of": list(member_of), "lists_read": 6 - len(unreadable or {}), "unreadable": unreadable or {}},
                  "MOCK DaaS /v1/indices/{index}/constituents", ASOF)


def scan_row(**o):
    r = {"symbol": "RELIANCE", "sector": "Energy", "industry": "Refineries", "eligible": True, "exclusion": None, "liquidity_class": "liquid",
         "risk_class": "low", "traded_value_cr_20d": 500.0}
    r.update(o)
    return src_ok(r, "MOCK DaaS scan-snapshot", ASOF, "scan-rules.mock")


def bucket(name="breakout_confirmed", stop=1160.0, trigger=1195.0):
    item = {"nse_symbol": "RELIANCE", "trigger_price": trigger, "stop_price": stop} if name else None
    return src_ok({"bucket": name, "item": item}, "MOCK positional watchlist", ASOF, "mock-classifier")


def features(**o):
    r = {"as_of_date": ASOF, "sector": "Energy", "pe_ttm": 24.0, "pb": 2.4, "roe_pct": 9.5, "roce_pct": 11.0, "debt_to_equity": 0.4,
         "market_cap_cr": 1600000.0, "fundamentals_source": "mock"}
    r.update(o)
    return src_ok(r, "MOCK DaaS features", ASOF)


def peers(n=6):
    pe = [10, 12, 14, 16, 18, 20, 22][:n]
    rows = [{"symbol": f"P{i}", "pe_ttm": pe[i], "pb": 1.0 + i * 0.5, "roe_pct": 8.0 + i} for i in range(n)]
    return src_ok({"industry": "Refineries", "peers": rows}, "MOCK peers", ASOF)


def financials():
    return src_ok({"latest_quarter": "Q1FY27", "growth_trend": "improving", "quarters_count": 8,
                   "rows": [{"revenue_yoy_pct": 7.0, "pat_cr": 17000.0, "ebitda_margin_pct": 17.5}]}, "MOCK financials", "2026-06-30")


def buildup(label="long_buildup", cc="confirms", **o):
    r = {"symbol": "RELIANCE", "label": label, "cash_confirmation": cc, "price_move": 1.0, "oi": 90000, "oi_chg": 4000, "oi_chg_pct": 4.6,
         "days_to_expiry": 8, "risk_flags": [], "cash_chg_pct": 0.9}
    r.update(o)
    return src_ok(r, "MOCK DaaS fno-buildup", ASOF, "mock-buildup")


def futures(lot=250, **o):
    near = {"expiry": "2026-10-27", "settle": 1203.0, "basis": 3.0, "oi": 90000, "change_in_oi": 4000, "volume": 70000, "change_pct": None}
    near.update(o)
    return src_ok({"as_of": ASOF, "lot_size": lot, "spot": 1200.0, "futures": [near, dict(near, expiry="2026-11-24", settle=1206.0)]},
                  "MOCK NSE F&O bhavcopy futures", ASOF)


def side(close, oi, vol, iv, delta=0.5):
    return {"close": close, "settle": close, "oi": oi, "change_in_oi": 100, "volume": vol, "iv": iv, "iv_price": "settle", "delta": delta}


STRIKES = [1100.0, 1150.0, 1200.0, 1250.0, 1300.0]
CALLS = {1100.0: (125.0, 5000, 3000, 24.0), 1150.0: (85.0, 8000, 5000, 23.0), 1200.0: (52.0, 20000, 9000, 22.0),
         1250.0: (38.0, 30000, 8000, 22.5), 1300.0: (20.0, 15000, 4000, 24.0)}
PUTS = {1100.0: (10.0, 12000, 2500, 25.0), 1150.0: (22.0, 25000, 6000, 24.0), 1200.0: (44.0, 22000, 9000, 22.0),
        1250.0: (80.0, 7000, 3500, 23.0), 1300.0: (118.0, 3000, 2000, 25.0)}


def chain_payload(calls=None, puts=None, em=96.0, walls=(1150.0, 1250.0), as_of=ASOF, lot=250):
    c, p = {**CALLS, **(calls or {})}, {**PUTS, **(puts or {})}
    rows = []
    for k in STRIKES:
        rows.append({"strike": k, "call": side(*c[k][:1], c[k][1], c[k][2], c[k][3]) if c.get(k) else None,
                     "put": side(*p[k][:1], p[k][1], p[k][2], p[k][3], -0.5) if p.get(k) else None})
    summary = {"as_of": as_of, "expiry": EXPIRY, "spot": 1200.0, "atm_strike": 1200.0, "days_to_expiry": 36, "pcr": 1.0, "max_pain": 1200.0,
               "max_put_oi": {"strike": walls[0], "oi": 25000}, "max_call_oi": {"strike": walls[1], "oi": 30000},
               "total_call_oi": 78000, "total_put_oi": 69000, "atm_iv": 22.0, "expected_move": em, "expected_move_pct": 8.0, "forward_basis": "future"}
    return {"symbol": "RELIANCE", "summary": summary, "lot_size": lot, "strikes": rows, "expiry_why": "MOCK nearest expiry with 11+ days"}


def chain(**kw):
    p = chain_payload(**kw)
    return src_ok(p, "MOCK NSE F&O bhavcopy chain", p["summary"]["as_of"], "mock-black76")


def expiries():
    return src_ok({"as_of": ASOF, "expiries": [{"expiry": "2026-10-27", "days_to_expiry": 8}, {"expiry": EXPIRY, "days_to_expiry": 36}]}, "MOCK expiries", ASOF)


def events(days_ahead_results: Optional[str] = None):
    rows = [{"event_type": "agm", "event_date": "2027-01-10", "purpose": "AGM"}]
    if days_ahead_results:
        rows.append({"event_type": "quarterly_results", "event_date": days_ahead_results, "purpose": "Q2 results"})
    return src_ok(rows, "MOCK DaaS events", ASOF)


def world(**over) -> Dict[str, Any]:
    s = {"regime": regime(), "sectors": sectors(), "sector_members": sector_members(), "indicators": indicators(), "patterns": src_ok({"patterns": [
            {"pattern_type": "flag", "label": "Bull flag", "direction": "bullish", "state": "confirmed", "state_reason": "closed beyond the level", "detected_on": "2026-10-16", "levels": {}}]},
            "MOCK patterns", ASOF, "engine-mock"),
         "scan_row": scan_row(), "scanner_bucket": bucket(), "features": features(), "peers": peers(), "financials": financials(),
         "announcements": src_ok([{"subject": "Order win", "filed_at": "2026-10-10", "event_category": "orders", "impact_score": "high", "sentiment": "positive"}], "MOCK filings", "2026-09-20"),
         "events": events(), "corporate_actions": src_ok([], "MOCK corporate actions", ASOF),
         "buildup": buildup(), "futures": futures(), "expiries": expiries(), "chain": chain(),
         "calibration": src_ok({"buckets": [{"metric": "broke_high", "horizon_days": 10, "sample_count": 400, "moves_count": 180, "probability": 0.45, "ci95_lo": 0.4, "ci95_hi": 0.5, "matched": True,
                                             "avg_fwd_return": 1.2, "avg_fwd_drawdown": -2.0}], "sample": {"last_scan_date": "2026-09-30"}, "symbol_score": {"accumulation_score": 55}, "source": "MOCK accumulation_calibration"},
                               "MOCK accumulation_calibration", "2026-09-30"),
         "portfolio": src_ok([{"nse_symbol": "RELIANCE", "asset_type": "equity", "value_rs": 100000.0, "sector": "Energy"},
                              {"nse_symbol": "TCS", "asset_type": "equity", "value_rs": 300000.0, "sector": "IT"}], "MOCK holdings", ASOF)}
    s.update(over)
    return s


def bearish_world(**over):
    w = world(regime=regime("bearish"), buildup=buildup("short_buildup"), scanner_bucket=bucket(None),
              indicators=indicators(close=1200.0, ema20=1210.0, ema50=1250.0, macd_hist=-1.0, roc20=-3.0, support20=1100.0, resistance20=1300.0,
                                    rs63={"excess_pct": -4.0}))
    w.update(over)
    return w


def inputs(**o) -> Dict[str, Any]:
    body = {"underlying": "RELIANCE", "direction": "bullish", "horizon": "positional", "instrument": "all", "capital": 1000000, "risk_budget_inr": 10000,
            "costs": COSTS}
    body.update(o)
    i, probs = normalise_inputs(body)
    assert not probs, probs
    return i


def build(snaps=None, **o):
    return pl.build_plan(inputs(**o), snaps or world(), NOW, TODAY)


def cand(plan, cid):
    return next(c for c in plan["candidates"] if c["id"] == cid)


def codes(c):
    return [r["code"] for r in c["reasons"]]


# ── inputs ───────────────────────────────────────────────────────────────────

def test_inputs_defaults_are_disclosed_and_bad_values_have_codes():
    i, probs = normalise_inputs({"underlying": "reliance", "direction": "bullish"})
    assert not probs and i["underlying"] == "RELIANCE" and i["horizon_days"] == 10 and i["min_reward_risk"] == 1.5
    assert {"horizon", "instrument", "horizon_days", "max_allocation_pct", "min_reward_risk", "avoid_events", "allow_multi_leg"} <= set(i["defaults_applied"])
    _, probs = normalise_inputs({"underlying": "A B", "direction": "sideways", "capital": -1, "horizon": "weekly", "expiry": "x", "avoid_events": "yes"})
    assert {p["code"] for p in probs} == {"bad_underlying", "bad_direction", "bad_capital", "bad_horizon", "bad_expiry", "bad_avoid_events"}
    assert normalise_inputs([])[1][0]["code"] == "bad_body"


# ── evidence: unavailable is never neutral ───────────────────────────────────

def test_missing_sources_are_unavailable_never_neutral():
    led = ev.build_ledger({}, inputs(), None, None)
    assert {i["group"] for i in led["items"]} == set(ev.GROUPS)
    assert all(i["direction"] == "unavailable" for i in led["items"] if i["value"] is None and i["key"] != "validation_status")
    sources_down = [i for i in led["items"] if i["group"] in ("market_context", "technical", "derivatives")]
    assert sources_down and all(i["direction"] == "unavailable" and i["interpretation"] for i in sources_down)
    assert not any(i["direction"] == "neutral" and i["value"] is None for i in led["items"])


def test_item_shape_carries_source_asof_and_version():
    led = ev.build_ledger(world(), inputs(), ASOF, ASOF)
    for i in led["items"]:
        assert set(i) == {"group", "key", "value", "interpretation", "direction", "source", "source_as_of", "version"}
        assert i["direction"] in ev.DIRECTIONS
    trend = next(i for i in led["items"] if i["key"] == "trend_structure")
    assert trend["direction"] == "supports" and trend["source_as_of"] == ASOF and trend["version"] == "mock-indicators"


def test_market_context_direction_is_relative_to_the_view():
    bull = {i["key"]: i["direction"] for i in ev.market_context(world(), "bullish")}
    bear = {i["key"]: i["direction"] for i in ev.market_context(world(), "bearish")}
    assert bull["desk_regime"] == "supports" and bear["desk_regime"] == "conflicts"
    assert bull["breadth"] == "supports" and bull["sector_strength"] == "supports" and bear["sector_strength"] == "conflicts"
    assert next(i for i in ev.market_context(world(), "bullish") if i["key"] == "india_vix")["direction"] == "neutral"
    mixed = {i["key"]: i["direction"] for i in ev.market_context(world(regime=regime("mixed")), "bullish")}
    assert mixed["desk_regime"] == "neutral"


def test_market_context_failed_regime_is_unavailable():
    items = ev.market_context(world(regime=src_fail("macro_state is empty", "x"), sectors=sectors()), "bullish")
    assert [i["direction"] for i in items if i["key"] in ("desk_regime", "breadth", "nifty_trend", "india_vix")] == ["unavailable"] * 4


def _sector_item(view="bullish", **over):
    return next(i for i in ev.market_context(world(**over), view) if i["key"] == "sector_strength")


def test_sector_strength_stock_in_two_sector_indices_lists_both_with_returns_and_ranks():
    it = _sector_item()
    v = it["value"]
    assert [m["index"] for m in v["matches"]] == ["Nifty Energy", "Nifty Oil & Gas"]
    assert [(m["rank_1m"], m["of"], m["band"]) for m in v["matches"]] == [(1, 6, "top"), (2, 6, "top")]
    assert [(m["ret_1d_pct"], m["ret_1w_pct"], m["ret_1m_pct"], m["date"]) for m in v["matches"]] == [(0.4, 1.2, 3.0, ASOF), (0.4, 1.2, 2.0, ASOF)]
    assert v["as_of"] == ASOF and v["rule"] == RULES["sector_strength"]
    assert it["direction"] == "supports" and "Nifty Energy" in it["interpretation"] and "Nifty Oil & Gas" in it["interpretation"]
    assert _sector_item("bearish")["direction"] == "conflicts"


def test_sector_strength_bands_bottom_middle_and_the_view():
    bank = sector_members("HDFCBANK", ["Nifty Bank"])
    assert _sector_item(sector_members=bank)["direction"] == "conflicts"
    assert _sector_item("bearish", sector_members=bank)["direction"] == "supports"
    pharma = _sector_item(sector_members=sector_members("SUNPHARMA", ["Nifty Pharma"]))
    assert pharma["direction"] == "neutral" and pharma["value"]["matches"][0]["band"] == "middle"
    assert _sector_item("vol_expansion", sector_members=bank)["direction"] == "neutral"


def test_sector_strength_several_indices_disagree_is_a_tie_neutral():
    it = _sector_item(sector_members=sector_members("X", ["Nifty Energy", "Nifty Bank"]))
    assert [m["band"] for m in it["value"]["matches"]] == ["top", "bottom"] and it["direction"] == "neutral"


def test_sector_strength_stock_in_no_sector_list_is_unavailable_with_that_reason():
    it = _sector_item(sector_members=sector_members("ZOMATO", []))
    assert it["direction"] == "unavailable" and it["value"] is None
    assert it["interpretation"] == "ZOMATO is in none of the desk's sector index lists (nidp.index_constituents), so no sector reading is made."


def test_sector_strength_unreadable_lists_do_not_pass_as_no_membership():
    it = _sector_item(sector_members=sector_members("X", [], {"Nifty Bank": "HTTP 500"}))
    assert it["direction"] == "unavailable" and "could not be read" in it["interpretation"] and "Nifty Bank" in it["interpretation"]
    failed = _sector_item(sector_members=src_fail("DaaS down", "x"))
    assert failed["direction"] == "unavailable" and "DaaS down" in failed["interpretation"]


def test_sector_strength_missing_return_is_listed_but_not_ranked():
    it = _sector_item(sectors=sectors(**{"Nifty Energy": None}))
    ms = {m["index"]: m for m in it["value"]["matches"]}
    assert ms["Nifty Energy"]["ret_1m_pct"] is None and ms["Nifty Energy"]["rank_1m"] is None and ms["Nifty Energy"]["band"] is None
    assert (ms["Nifty Oil & Gas"]["rank_1m"], ms["Nifty Oil & Gas"]["of"]) == (1, 5)         # ranks among the 5 that have a return
    assert it["direction"] == "supports"
    only = _sector_item(sectors=sectors(**{"Nifty Energy": None, "Nifty Oil & Gas": None}))
    assert only["direction"] == "unavailable" and "1-month return" in only["interpretation"]


def test_sector_strength_member_index_absent_from_sector_returns():
    it = _sector_item(sector_members=sector_members("X", ["Nifty Realty"]))
    assert it["direction"] == "unavailable" and "Nifty Realty" in it["interpretation"]


def test_technical_group_each_item():
    items = {i["key"]: i for i in ev.technical(world(), "bullish")}
    assert items["trend_structure"]["direction"] == "supports"
    assert items["momentum"]["direction"] == "supports" and items["relative_strength"]["direction"] == "supports"
    assert items["scanner_setup"]["direction"] == "supports" and items["chart_pattern:flag"]["direction"] == "supports"
    assert items["atr"]["direction"] == "neutral" and items["levels"]["value"] == {"support20": 1130.0, "resistance20": 1290.0}
    down = {i["key"]: i for i in ev.technical(world(indicators=indicators(close=1100.0, ema20=1120.0, ema50=1150.0, macd_hist=-1.0, roc20=-3.0)), "bullish")}
    assert down["trend_structure"]["direction"] == "conflicts" and down["momentum"]["direction"] == "conflicts"
    no_rs = {i["key"]: i for i in ev.technical(world(indicators=indicators(rs63=None)), "bullish")}
    assert no_rs["relative_strength"]["direction"] == "unavailable"
    awaiting = world(patterns=src_ok({"patterns": [{"pattern_type": "flag", "label": "Bull flag", "direction": "bullish", "state": "awaiting_confirmation", "state_reason": "x", "detected_on": ASOF, "levels": {}}]}, "m", ASOF))
    assert {i["key"]: i for i in ev.technical(awaiting, "bullish")}["chart_pattern:flag"]["direction"] == "neutral"
    failed = {i["key"]: i["direction"] for i in ev.technical(world(indicators=src_fail("boom", "x"), patterns=src_fail("boom", "x"), scanner_bucket=src_fail("boom", "x")), "bullish")}
    assert failed["trend_structure"] == failed["chart_patterns"] == failed["scanner_setup"] == "unavailable"


def test_fundamental_group_values_and_peer_valuation_context():
    # peers P/E 10,12,14,16,18,20 -> median (14+16)/2 = 15; P/B 1.0..3.5 step .5 -> median (2.0+2.5)/2 = 2.25; ROE 8..13 -> median 10.5
    items = {i["key"]: i for i in ev.fundamental(world(), "bullish")}
    ctx = items["valuation_vs_peers"]["value"]
    assert (ctx["median_pe"], ctx["median_pb"], ctx["median_roe_pct"], ctx["peer_count"]) == (15.0, 2.25, 10.5, 6)
    assert ctx["pe_vs_median_pct"] == 60.0               # 24 / 15 - 1
    assert items["pe_ttm"]["value"] == 24.0 and items["pe_ttm"]["direction"] == "neutral"
    assert items["analyst_estimates"]["direction"] == "unavailable" and "PRD §17.2" in items["analyst_estimates"]["interpretation"]
    assert items["cash_flow_quality"]["direction"] == "unavailable"
    few = {i["key"]: i for i in ev.fundamental(world(peers=peers(4)), "bullish")}
    assert few["valuation_vs_peers"]["direction"] == "unavailable" and "needs 5" in few["valuation_vs_peers"]["interpretation"]
    missing = {i["key"]: i for i in ev.fundamental(world(features=features(pb=None)), "bullish")}
    assert missing["pb"]["direction"] == "unavailable" and missing["pb"]["value"] is None
    down = {i["key"]: i for i in ev.fundamental(world(features=src_fail("no row", "x"), financials=src_fail("none", "x"), peers=src_fail("none", "x")), "bullish")}
    assert all(down[k]["direction"] == "unavailable" for k in ("pe_ttm", "quarterly_trend", "valuation_vs_peers"))


def test_catalysts_results_inside_and_outside_the_horizon():
    # as of 2026-10-19 + 10 days = 2026-10-29
    inside = {i["key"]: i for i in ev.catalysts(world(events=events("2026-10-27")), "bullish", ASOF, 10)}
    assert inside["results_and_events"]["direction"] == "conflicts" and "2026-10-27" in inside["results_and_events"]["interpretation"]
    outside = {i["key"]: i for i in ev.catalysts(world(events=events("2026-11-10")), "bullish", ASOF, 10)}
    assert outside["results_and_events"]["direction"] == "neutral"
    ca = world(corporate_actions=src_ok([{"action_type": "DIVIDEND", "ex_date": "2026-10-25", "purpose": "Dividend"}], "m", ASOF))
    assert {i["key"]: i for i in ev.catalysts(ca, "bullish", ASOF, 10)}["corporate_actions"]["direction"] == "conflicts"
    filings = {i["key"]: i for i in ev.catalysts(world(), "bullish", ASOF, 10)}["recent_filings"]
    assert filings["direction"] == "supports" and filings["value"]["positive"] == 1 and filings["value"]["high_impact"] == 1
    down = {i["key"]: i["direction"] for i in ev.catalysts(world(events=src_fail("x", "x"), announcements=src_fail("x", "x"), corporate_actions=src_fail("x", "x")), "bullish", ASOF, 10)}
    assert set(down.values()) == {"unavailable"}


def test_derivatives_group_and_stale_chain_and_no_bid_ask():
    items = {i["key"]: i for i in ev.derivatives(world(), "bullish", ASOF)}
    assert items["oi_buildup"]["direction"] == "supports" and items["cash_confirmation"]["value"]["cash_confirmation"] == "confirms"
    assert items["future_day_change"]["direction"] == "unavailable" and "feat/strategy-hardening" in items["future_day_change"]["interpretation"]
    assert items["bid_ask"]["direction"] == "unavailable" and "no bid or ask" in items["bid_ask"]["interpretation"]
    assert items["chain_positioning"]["value"]["pcr"] == 1.0 and items["liquidity_proxy"]["value"]["call"] == {"oi": 20000, "volume": 9000}
    assert items["chain_freshness"]["value"]["stale"] is False
    stale = {i["key"]: i for i in ev.derivatives(world(chain=chain(as_of="2026-10-16")), "bullish", ASOF)}
    assert stale["chain_freshness"]["value"]["stale"] is True and "delayed/historical" in stale["chain_freshness"]["interpretation"]
    short = {i["key"]: i for i in ev.derivatives(world(buildup=buildup("short_buildup")), "bullish", ASOF)}
    assert short["oi_buildup"]["direction"] == "conflicts"
    cov = {i["key"]: i for i in ev.derivatives(world(buildup=buildup("short_covering")), "bullish", ASOF)}
    assert cov["oi_buildup"]["direction"] == "neutral"
    flat = {i["key"]: i for i in ev.derivatives(world(buildup=buildup(cc=None)), "bullish", ASOF)}
    assert flat["cash_confirmation"]["direction"] == "unavailable"
    nochain = {i["key"]: i["direction"] for i in ev.derivatives(world(chain=src_fail("no chain", "x")), "bullish", ASOF)}
    assert nochain["option_chain"] == "unavailable"


def test_validation_is_never_validated_and_the_record_is_labelled_in_sample():
    items, block = ev.validation(world(), 10)
    assert block["status"] == "not_validated" and "out-of-sample" in " ".join(block["reasons"])
    assert block["in_sample_record"]["rows"][0]["sample_count"] == 400 and "in-sample" in block["in_sample_record"]["label"]
    assert next(i for i in items if i["key"] == "validation_status")["value"] == "not_validated"
    _, none = ev.validation(world(calibration=src_fail("x", "y")), 10)
    assert none["status"] == "not_validated" and none["in_sample_record"] is None


def test_portfolio_fit():
    items = {i["key"]: i for i in ev.portfolio_fit(world(), "RELIANCE", "Energy")}
    assert items["existing_exposure"]["value"]["weight_pct"] == 25.0         # 100000 / 400000
    assert items["sector_exposure"]["value"]["weight_pct"] == 25.0
    assert ev.portfolio_fit(world(portfolio=src_fail("holdings_unavailable", "x")), "RELIANCE", "Energy")[0]["direction"] == "unavailable"
    assert ev.portfolio_fit(world(portfolio=src_ok([], "x", ASOF)), "RELIANCE", "Energy")[0]["direction"] == "unavailable"


# ── candidate rules: cash ────────────────────────────────────────────────────

def test_cash_breakout_continuation_sizing_and_net_ratio_by_hand():
    p = build(instrument="cash")
    c = cand(p, "cash:breakout_continuation")
    assert c["status"] == "candidate" and p["status"] == "plan" and p["preferred"] == c["id"]
    # entry 1200, scanner stop 1160: risk 40/share. Sized after the desk cost card's costs at the stop (paper_fills_pnl
    # TESTCASES C-1; 250 on the gross distance, 241 under the flat model): the most shares with 40 x q + costs(q) <= 10000
    # is 227. The allocation cap floor(1,000,000 x 25% / 1200) = 208 still binds -> 208 shares.
    s = c["sizing"]
    assert (s["status"], s["quantity"], s["by_risk_budget"], s["by_allocation_cap"], s["binding"]) == ("complete", 208, 227, 208, "allocation_cap")
    # 208 x 40 = 8320 gross; costs at the stop, by hand: buy 2,49,600 = 20 + 249.60 STT + 7.66 exch + 0.25 SEBI + 37.44 stamp
    # + 5.02 GST + 124.80 slippage = 444.77; sell 2,41,280 = 20 + 241.28 + 7.41 + 0.24 + 4.98 + 120.64 = 394.55; 839.32.
    assert (s["risk_at_stop_inr"], s["costs_at_stop_inr"], s["risk_at_stop_net_inr"], s["costs_included"]) == (8320.0, 839.32, 9159.32, True)
    assert s["costs_breakdown_at_stop"] == {"brokerage": 40.0, "stt": 490.88, "exchange": 15.07, "sebi": 0.49, "stamp": 37.44,
                                            "gst": 10.0, "slippage": 245.44, "total": 839.32}
    assert c["legs"][0]["quantity"] == 208 and c["legs"][0]["entry_price"] == 1200.0
    # levels: base 1200 + 2 x 40 = 1280, optimistic 1200 + 3 x 40 = 1320, conservative 1 x ATR = 1220 (resistance 1290 is farther than the base)
    t = {x["name"]: x["price"] for x in c["targets"]}
    assert t == {"conservative": 1220.0, "base": 1280.0, "optimistic": 1320.0}
    # gross at base 80 x 208 = 16640 ; gross loss at stop 40 x 208 = 8320 -> 2.0
    # costs: entry 249600 x .0005 + 20 = 144.8; exit at 1280 266240 x .0005 + 20 = 153.12; exit at 1160 241280 x .0005 + 20 = 140.64
    # net reward 16640 - 144.8 - 153.12 = 16342.08 ; net risk 8320 + 144.8 + 140.64 = 8605.44 -> 1.90
    rr = c["risk_reward"]
    assert rr["gross"] == 2.0 and rr["net"] == round(16342.08 / 8605.44, 2) and rr["level"] == "base"
    assert c["invalidation"]["technical"]["price"] == 1160.0 and "does not guarantee" in c["invalidation"]["execution_stop"]["note"]
    assert c["payoff"]["valid"] and c["payoff"]["sent_to_broker"] is False and c["sent_to_broker"] is False


def test_cash_bearish_is_avoid_and_neutral_has_no_cash_strategy():
    c = cand(build(instrument="cash", direction="bearish"), "cash:avoid")
    assert c["status"] == "avoid" and c["legs"] == [] and codes(c) == ["long_only"]
    n = build(instrument="cash", direction="neutral")
    assert cand(n, "cash:none")["status"] == "no_trade" and n["status"] == "no_trade"


def test_cash_without_a_scanner_setup_or_before_the_trigger():
    none = build(world(scanner_bucket=bucket(None)), instrument="cash")
    assert codes(cand(none, "cash:scanner")) == ["no_setup"] and none["status"] == "no_trade"
    wait = build(world(scanner_bucket=bucket("pre_breakout")), instrument="cash")
    c = cand(wait, "cash:breakout_watch")
    assert c["status"] == "wait" and wait["status"] == "wait" and "1195" in c["entry"]["logic"] and c["legs"] == []
    down = build(world(scanner_bucket=src_fail("db down", "x")), instrument="cash")
    assert down["status"] == "insufficient_data" and codes(cand(down, "cash:scanner")) == ["scanner_unavailable"]


def test_cash_pullback_family_and_a_nearby_resistance_that_fails_reward_risk():
    pb = build(world(scanner_bucket=bucket("trend_continuation", stop=1160.0)), instrument="cash")
    assert cand(pb, "cash:pullback_in_uptrend")["status"] == "candidate"
    # resistance 1235 is 35 away (>= 0.5 ATR, nearer than the base 1280): the conservative level and the gate. 35 / 40 = 0.875 < 1.5
    capped = build(world(indicators=indicators(resistance20=1235.0)), instrument="cash")
    c = cand(capped, "cash:breakout_continuation")
    assert c["status"] == "no_trade" and codes(c) == ["reward_risk_below_minimum"] and c["risk_reward"]["level"] == "conservative"
    assert c["risk_reward"]["gross"] == 0.88 and capped["status"] == "no_trade"
    lowered = build(world(indicators=indicators(resistance20=1235.0)), instrument="cash", min_reward_risk=0.5)
    assert cand(lowered, "cash:breakout_continuation")["status"] == "candidate"


def test_cash_incomplete_sizing_shows_formula_and_missing_inputs_never_a_guess():
    p = pl.build_plan(inputs(instrument="cash", capital=None, risk_budget_inr=None), world(), NOW, TODAY)
    s = cand(p, "cash:breakout_continuation")["sizing"]
    assert s["status"] == "incomplete" and s["quantity"] is None and "capital" in s["missing"]
    # The formula now names the costs it sizes with (paper_fills_pnl TESTCASES C-1).
    assert any("risk_budget_inr" in m for m in s["missing"]) and "estimated round-trip costs at the stop" in s["formula"]
    c = cand(p, "cash:breakout_continuation")
    assert c["legs"][0]["quantity"] == 1 and any("Sizing is incomplete" in w for w in c["warnings"])


def test_sizing_too_small_is_no_trade():
    p = build(instrument="cash", risk_budget_inr=30)             # 30 / 40 = 0 shares
    c = cand(p, "cash:breakout_continuation")
    assert c["sizing"]["status"] == "too_small" and c["status"] == "no_trade" and "sizing_zero" in codes(c)


def test_sizing_risk_pct_and_risk_budget_binding():
    s = cd.size_position({"risk_budget_inr": None, "risk_pct": 1.0, "capital": 1000000, "max_allocation_pct": 100.0}, risk_per_unit=40.0, value_per_unit=1200.0,
                         unit="shares", per_unit_label="x")
    # budget 1% x 1,000,000 = 10000 -> floor(10000/40) = 250 ; cap floor(1,000,000 / 1200) = 833 -> 250, bound by the risk budget
    assert (s["quantity"], s["binding"], s["risk_at_stop_inr"], s["deployed_inr"]) == (250, "risk_budget", 10000.0, 300000.0)
    lots = cd.size_position({"risk_budget_inr": 10000, "risk_pct": None, "capital": 1000000, "max_allocation_pct": 25.0}, risk_per_unit=40.0, value_per_unit=1200.0,
                            unit="lots", lot_units=250, per_unit_label="x")
    # one lot risks 40 x 250 = 10000 -> 1 lot ; cap floor(250000 / (1200 x 250)) = 0 -> 0 lots (one lot's notional exceeds the allocation)
    assert lots["quantity"] == 0 and lots["status"] == "too_small"


# ── candidate rules: futures ─────────────────────────────────────────────────

def test_futures_wall_target_closer_than_the_stop_fails_the_default_gate():
    # stop = put wall 1150 (53 below the 1203 settle), target = call wall 1250 (47 above): gross 47 / 53 = 0.89 < 1.5
    c = cand(build(instrument="futures", risk_budget_inr=20000, max_allocation_pct=100), "futures:long_buildup_continuation")
    assert c["status"] == "no_trade" and codes(c) == ["reward_risk_below_minimum"] and c["risk_reward"]["gross"] == 0.89


def test_futures_long_buildup_with_cash_confirmation():
    p = build(instrument="futures", risk_budget_inr=20000, max_allocation_pct=100, min_reward_risk=0.5)
    c = cand(p, "futures:long_buildup_continuation")
    assert c["status"] == "candidate" and c["legs"][0]["kind"] == "future" and c["legs"][0]["expiry"] == "2026-10-27" and c["legs"][0]["lot_size"] == 250
    assert c["legs"][0]["entry_price"] == 1203.0
    # levels_from: stop = put wall 1150 (below 1203), target = call wall 1250. risk 53 x 250 = 13250 a lot -> floor(20000 / 13250) = 1 lot
    assert c["invalidation"]["technical"]["price"] == 1150.0 and c["sizing"]["quantity"] == 1 and c["sizing"]["unit"] == "lots"
    assert {x["name"]: x["price"] for x in c["targets"]}["base"] == 1250.0
    assert any("exceed the initial margin" in w for w in c["warnings"]) and c["payoff"]["loss_can_exceed_margin"] is True
    assert c["payoff"]["margin"] is None
    # The live margin read swaps this exact warning when the calculator answers, so the two texts must stay identical; neither claims no source exists.
    assert lr.OLD_FUTURES_WARNING in c["warnings"] and "no margin estimate exists" not in lr.OLD_FUTURES_WARNING


def test_margin_caveat_names_the_calculator_and_is_shared_by_ideas_and_picks():
    import inspect
    from services.strategy_plan import ideas, picks
    assert "no source exists" not in pl.MARGIN_CAVEAT and "Zerodha's margin calculator" in pl.MARGIN_CAVEAT and "not the maximum loss" in pl.MARGIN_CAVEAT
    assert pl.MARGIN_CAVEAT in picks.CAVEATS
    # ideas builds its caveats inline: it must use the plan's constant (the live swap to MARGIN_LIVE_CAVEAT matches on equality), not a copy.
    assert "no source exists" not in inspect.getsource(ideas) and "MARGIN_CAVEAT" in inspect.getsource(ideas)


def test_futures_short_covering_and_long_unwinding_are_wait_not_trade():
    for lab in ("short_covering", "long_unwinding"):
        p = build(world(buildup=buildup(lab)), instrument="futures")
        c = cand(p, "futures:long_buildup_continuation")
        assert c["status"] == "wait" and codes(c) == ["no_fresh_buildup"] and c["legs"] == [] and p["status"] == "wait"


def test_futures_needs_cash_confirmation_and_the_right_build_up():
    div = build(world(buildup=buildup(cc="diverges")), instrument="futures")
    assert codes(cand(div, "futures:long_buildup_continuation")) == ["cash_not_confirming"] and div["status"] == "wait"
    flat = build(world(buildup=buildup(cc=None)), instrument="futures")
    assert cand(flat, "futures:long_buildup_continuation")["status"] == "wait"
    opp = build(world(buildup=buildup("short_buildup")), instrument="futures")
    assert cand(opp, "futures:long_buildup_continuation")["status"] == "no_trade" and opp["status"] == "no_trade"
    bear = build(bearish_world(), instrument="futures", direction="bearish", risk_budget_inr=20000, max_allocation_pct=100, min_reward_risk=0.5)
    s = cand(bear, "futures:short_buildup_continuation")
    assert s["status"] == "candidate" and s["legs"][0]["side"] == "sell" and s["invalidation"]["technical"]["price"] == 1250.0
    assert cand(build(instrument="futures", direction="neutral"), "futures:none")["status"] == "no_trade"


def test_futures_unpriced_or_unknown_lot_cannot_be_traded():
    noprice = build(world(futures=futures(settle=None)), instrument="futures")
    assert codes(cand(noprice, "futures:long_buildup_continuation")) == ["future_unpriced"] and noprice["status"] == "insufficient_data"
    nolot = build(world(futures=futures(lot=None), chain=src_fail("x", "y")), instrument="futures")
    assert codes(cand(nolot, "futures:long_buildup_continuation")) == ["lot_size_unknown"]
    down = build(world(buildup=src_fail("db", "x")), instrument="futures")
    assert codes(cand(down, "futures:long_buildup_continuation")) == ["buildup_unavailable"]


def test_futures_day_change_stays_unavailable_not_inferred():
    p = build(instrument="futures")
    item = next(i for i in p["evidence"] if i["key"] == "future_day_change")
    assert item["direction"] == "unavailable" and item["value"] is None


# ── candidate rules: options ─────────────────────────────────────────────────

def test_expiry_picker_is_a_rule_not_a_guess():
    ex = [{"expiry": "2026-10-27", "days_to_expiry": 8}, {"expiry": EXPIRY, "days_to_expiry": 36}, {"expiry": "2027-03-30", "days_to_expiry": 160}]
    assert cd.pick_expiry(ex, 10)[0] == EXPIRY                      # needs >= 11 days and <= 60
    assert cd.pick_expiry(ex, 1)[0] == "2026-10-27"                 # needs >= 5 days
    assert cd.pick_expiry(ex, 10, "2027-03-30")[0] == "2027-03-30"
    assert cd.pick_expiry(ex, 10, "2027-04-01")[0] is None
    assert cd.pick_expiry(ex, 100)[0] is None


def test_bull_call_spread_legs_strikes_sizing_and_alternative_compared():
    p = build(instrument="options")
    c = cand(p, "options:bull_call_spread")
    assert c["status"] == "candidate"
    legs = c["legs"]
    # rule 3: short strike at the call wall 1250 (inside the expected move edge 1200 + 96 = 1296); long the ATM 1200
    assert [(l["side"], l["option_type"], l["strike"], l["entry_price"]) for l in legs] == [("buy", "call", 1200.0, 52.0), ("sell", "call", 1250.0, 38.0)]
    assert all(l["expiry"] == EXPIRY and l["lot_size"] == 250 and "bhavcopy close" in l["price_source"] for l in legs)
    e, lots = c["payoff"]["expiry"], c["legs"][0]["quantity"]
    # debit 14, width 50: per lot max profit (50-14) x 250 = 9000, max loss 14 x 250 = 3500, breakeven 1214
    assert lots >= 1 and (e["max_profit"], e["max_loss"], e["breakevens"], e["net_premium"]) == (9000.0 * lots, -3500.0 * lots, [1214.0], -3500.0 * lots)
    one_lot = compute_payoff({"underlying": "RELIANCE", "reference_price": 1200.0, "as_of": ASOF, "grid": {"from_pct": -25, "to_pct": 25, "points": 121}, "costs": COSTS,
                              "legs": [dict(l, quantity=1) for l in legs]}, TODAY)
    s = c["sizing"]
    assert s["risk_per_unit"] == one_lot["capital_at_risk"] and s["quantity"] == min(math.floor(10000 / one_lot["capital_at_risk"]), s["by_allocation_cap"])
    assert c["risk_reward"]["gross"] == round(9000 / 3500, 2) and c["risk_reward"]["level"] == "base"
    sel = c["options_selection"]
    assert sel["expiry"] == EXPIRY and sel["eligible_strikes"] == STRIKES and "NSE F&O bhavcopy" in sel["strikes_source"]
    assert sel["chosen"] == {"long": 1200.0, "short": 1250.0} and "call wall" in sel["why"] and "cheap" in sel["rule"]
    assert sel["alternatives"] and sel["alternatives"][0]["plan"] == {"long": 1200.0, "short": 1300.0} and sel["alternatives"][0]["metrics"]["max_loss"] is not None
    assert not c["payoff"]["pre_expiry"] is None            # IV on every leg -> the pre-expiry block exists (horizon 10 days < expiry)
    assert any("Bid/ask is not in the end-of-day file" in w for w in c["warnings"])
    assert c["payoff"]["sent_to_broker"] is False and c["actionable"] is True


def test_long_call_with_no_reward_at_the_base_level_fails_the_gate():
    # ATM call costs 52; at the base level (call wall 1250) it is worth 50 at expiry: a loss, so reward : risk is negative -> No Trade
    c = cand(build(instrument="options", risk_budget_inr=50000), "options:long_call")
    assert c["status"] == "no_trade" and "reward_risk_below_minimum" in codes(c)
    assert c["options_selection"]["alternatives"][0]["plan"] == {"k": 1250.0}


def test_bearish_mirrors_with_puts():
    p = build(bearish_world(), instrument="options", direction="bearish", risk_budget_inr=50000)
    spread = cand(p, "options:bear_put_spread")
    # short put at the put wall 1150 (inside the edge 1200 - 96 = 1104? no: 1150 >= 1104 yes), long the ATM 1200 put 44, short 1150 put 22: debit 22
    assert [(l["side"], l["option_type"], l["strike"]) for l in spread["legs"]] == [("buy", "put", 1200.0), ("sell", "put", 1150.0)]
    e, lots = spread["payoff"]["expiry"], spread["legs"][0]["quantity"]
    assert (e["max_loss"], e["max_profit"], e["breakevens"]) == (-5500.0 * lots, 7000.0 * lots, [1178.0])       # 22 x 250 ; (50-22) x 250 ; 1200 - 22


def test_iron_condor_rule_and_legs():
    # walls 1150 / 1250, spot 1200: each 50 away; expected move 40 -> both walls at least one move away -> condor
    default = cand(build(world(chain=chain(em=40.0)), instrument="options", direction="neutral", risk_budget_inr=20000), "options:iron_condor")
    # max profit 7500 / max loss 5000 = 1.5 gross: after costs it is below the default minimum of 1.5 -> No Trade (the rule has teeth)
    assert default["status"] == "no_trade" and default["risk_reward"]["gross"] == 1.5 and default["risk_reward"]["net"] < 1.5
    p = build(world(chain=chain(em=40.0)), instrument="options", direction="neutral", risk_budget_inr=20000, min_reward_risk=1.0)
    c = cand(p, "options:iron_condor")
    assert [(l["side"], l["option_type"], l["strike"]) for l in c["legs"]] == [("buy", "put", 1100.0), ("sell", "put", 1150.0), ("sell", "call", 1250.0), ("buy", "call", 1300.0)]
    # credit (22-10) + (38-20) = 30 a unit ; width 50 -> max profit 30 x 250 = 7500, max loss (50-30) x 250 = 5000, breakevens 1120 and 1280
    e, lots = c["payoff"]["expiry"], c["legs"][0]["quantity"]
    assert (e["max_profit"], e["max_loss"], e["breakevens"]) == (7500.0 * lots, -5000.0 * lots, [1120.0, 1280.0])
    assert c["payoff"]["loss_can_exceed_margin"] is False and c["status"] == "candidate" and c["options_selection"]["chosen"]["short_put"] == 1150.0


def test_iron_condor_refused_when_the_expected_move_reaches_a_wall_or_spot_outside():
    wide = build(world(chain=chain(em=96.0)), instrument="options", direction="neutral")
    c = cand(wide, "options:iron_condor")
    assert c["status"] == "no_trade" and codes(c) == ["condor_rule_fails"] and "expected move" in c["reasons"][0]["message"] and c["legs"] == []
    outside = build(world(chain=chain(em=40.0, walls=(1210.0, 1250.0))), instrument="options", direction="neutral")
    assert "not strictly between" in cand(outside, "options:iron_condor")["reasons"][0]["message"]
    noem = build(world(chain=chain(em=None)), instrument="options", direction="neutral")
    assert "expected move is unavailable" in cand(noem, "options:iron_condor")["reasons"][0]["message"]
    off = build(world(chain=chain(em=40.0)), instrument="options", direction="neutral", allow_multi_leg=False)
    assert codes(cand(off, "options:iron_condor")) == ["multi_leg_not_allowed"]


def test_missing_premium_means_no_leg_and_no_trade():
    p = build(world(chain=chain(calls={1250.0: (None, 30000, 8000, 22.5)})), instrument="options")
    c = cand(p, "options:bull_call_spread")
    assert c["status"] == "no_trade" and "legs_unpriced" in codes(c) and c["legs"] == []      # the leg without a close is not built, not priced at a guess
    assert "missing_premium@1250CE" in " ".join(c["reasons"][0]["message"].split())


def test_zero_volume_or_zero_oi_blocks_and_low_oi_is_flagged():
    p = build(world(chain=chain(calls={1250.0: (38.0, 30000, 0, 22.5)})), instrument="options")
    c = cand(p, "options:bull_call_spread")
    assert c["status"] == "no_trade" and "illiquid_leg" in codes(c)
    # 1200 call OI 20000 is not low; make the short leg's OI 1000: median of call OI {5000,8000,20000,1000,15000} = 8000 -> 25% = 2000 -> low
    low = build(world(chain=chain(calls={1250.0: (38.0, 1000, 8000, 22.5)})), instrument="options")
    lc = cand(low, "options:bull_call_spread")
    assert lc["status"] == "candidate" and "low_oi@1250CE" in lc["options_selection"]["preferred_flags"]
    assert any("low_oi" in w and "1250CE" in w for w in lc["warnings"])


def test_abnormal_iv_is_flagged_against_the_chains_own_fences():
    p = build(world(chain=chain(calls={1250.0: (38.0, 30000, 8000, 80.0)})), instrument="options")
    c = cand(p, "options:bull_call_spread")
    assert "abnormal_iv@1250CE" in c["options_selection"]["preferred_flags"] and c["options_selection"]["iv_fences"] is not None
    missing = build(world(chain=chain(calls={1250.0: (38.0, 30000, 8000, None)})), instrument="options")
    assert "missing_iv@1250CE" in cand(missing, "options:bull_call_spread")["options_selection"]["preferred_flags"]


def test_stale_chain_is_labelled_delayed_and_not_actionable():
    # price data is 2026-10-19 but the chain is 2026-10-16: older than the last completed session
    p = build(world(chain=chain(as_of="2026-10-16")), instrument="options")
    c = cand(p, "options:bull_call_spread")
    assert c["status"] == "wait" and "stale_chain" in codes(c) and c["actionable"] is False
    assert "Delayed/historical" in c["label_note"] and c["options_selection"]["stale"] is True
    assert p["status"] == "wait" and any("delayed/historical" in w.lower() for w in c["warnings"])


def test_no_valid_chain_and_unsupported_volatility_view():
    nochain = build(world(chain=src_fail("No option contracts", "x")), instrument="options")
    assert nochain["status"] == "insufficient_data" and set(codes(cand(nochain, "options:long_call"))) == {"no_valid_chain"}
    vol = build(instrument="options", direction="vol_expansion")
    assert cand(vol, "options:none")["status"] == "no_trade" and "volatility_long_not_supported" in codes(cand(vol, "options:none"))


def test_options_are_defined_risk_only():
    p = build(instrument="options")
    for c in p["candidates"]:
        if c["payoff"]:
            assert c["payoff"]["expiry"]["loss_unbounded"] is False


# ── No Trade / Wait / Insufficient data at the plan level ───────────────────

def reasons_of(p):
    return {r["code"] for r in p["status_reasons"]}


def test_stale_price_data_is_insufficient():
    p = pl.build_plan(inputs(), world(), NOW, date(2026, 10, 26))      # 7 days after the price day, limit 4
    assert p["status"] == "insufficient_data" and "stale_data" in reasons_of(p)
    assert all(c["status"] == "insufficient_data" for c in p["candidates"])


def test_failed_required_source_and_intraday_are_insufficient_with_no_candidates():
    p = build(world(indicators=src_fail("upstream_unavailable", "x")))
    assert p["status"] == "insufficient_data" and "required_source_failed" in reasons_of(p) and p["candidates"] == []
    q = build(horizon="intraday")
    assert q["status"] == "insufficient_data" and "intraday_not_supported" in reasons_of(q)


def test_liquidity_below_the_10_crore_gate_is_no_trade():
    low = build(world(scan_row=scan_row(traded_value_cr_20d=6.0)))
    assert low["status"] == "no_trade" and "liquidity_below_gate" in reasons_of(low)
    assert all(c["status"] in ("no_trade", "avoid") for c in low["candidates"])
    unknown = build(world(scan_row=scan_row(traded_value_cr_20d=None), indicators=indicators(avg_traded_value_cr20=None)))
    assert "liquidity_unknown" in reasons_of(unknown)


def test_event_inside_the_horizon_with_avoid_events_is_no_trade():
    p = build(world(events=events("2026-10-27")), instrument="cash")
    assert p["status"] == "no_trade" and "event_in_horizon" in reasons_of(p) and "avoid_events is on by default" in p["status_reasons"][0]["message"]
    accepted = build(world(events=events("2026-10-27")), instrument="cash", avoid_events=False)
    c = cand(accepted, "cash:breakout_continuation")
    assert c["status"] == "candidate" and any("gap risk is accepted" in w for w in c["warnings"])


def test_conflicting_evidence_beyond_the_rule_is_no_trade():
    bad = world(regime=regime("bearish"), indicators=indicators(close=1100.0, ema20=1120.0, ema50=1150.0, macd_hist=-1.0, roc20=-3.0, rs63={"excess_pct": -4.0}),
                buildup=buildup("short_buildup"))
    p = build(bad, instrument="cash")
    assert p["status"] == "no_trade" and "conflicting_evidence" in reasons_of(p)
    assert p["evidence_summary"]["technical"]["conflicts"] >= 2


def test_risk_that_cannot_be_calculated_is_insufficient():
    p = build(world(scanner_bucket=bucket("breakout_confirmed", stop=None), indicators=src_ok({"values": values(), "hypothetical_levels": {"stop": None}}, "m", ASOF)), instrument="cash")
    assert cand(p, "cash:breakout_continuation")["status"] == "insufficient_data" and "risk_not_calculable" in codes(cand(p, "cash:breakout_continuation"))


def test_every_non_plan_status_lists_what_would_change_it():
    for snaps in (world(scanner_bucket=bucket(None)), world(scanner_bucket=bucket("pre_breakout")), world(events=events("2026-10-27"))):
        p = build(snaps, instrument="cash")
        assert p["status"] in ("wait", "no_trade") and p["would_change_if"] and p["status_reasons"]


# ── plan object ──────────────────────────────────────────────────────────────

def test_plan_object_has_every_required_block_and_no_opaque_confidence():
    p = build()
    for key in ("plan_id", "summary", "thesis", "evidence", "candidates", "alternatives", "failure_conditions", "validation", "lifecycle", "generated_at",
                "data_as_of", "source_snapshots", "rules_version", "calculation_version", "headline", "scenarios", "inputs_hash", "would_change_if"):
        assert key in p, key
    assert p["rules_version"] == STRATEGY_RULES_VERSION and p["calculation_version"] == "payoff-v1" and p["rules"]["version"] == STRATEGY_RULES_VERSION
    h = p["headline"]
    assert set(h) >= {"technical_setup", "fundamental_context", "model_estimate", "data_quality"}
    assert h["model_estimate"]["status"] == "withheld" and h["model_estimate"]["value"] is None and h["confidence"] is None
    assert p["validation"]["status"] == "not_validated" and "validated" not in json.dumps(p["status"])
    assert h["fundamental_context"]["role"].startswith("context only") and "analyst_estimates" in h["fundamental_context"]["missing"]
    assert p["scenarios"]["model_path"]["status"] == "unavailable" and p["scenarios"]["label"] == "scenarios, not forecasts"
    assert p["lifecycle"]["status"] == "draft" and p["sent_to_broker"] is False
    assert all(c["sent_to_broker"] is False for c in p["candidates"])
    assert {r["id"] for r in p["alternatives"]} == {c["id"] for c in p["candidates"]}
    row = next(r for r in p["alternatives"] if r["id"] == "options:bull_call_spread")
    assert set(row) >= {"max_loss", "capital_at_risk", "breakeven", "reward_risk_net", "liquidity_flags", "horizon_days", "evidence_quality", "why_unsuitable"}
    assert row["why_unsuitable"] is None and next(r for r in p["alternatives"] if r["id"] == "options:long_call")["why_unsuitable"]
    assert all(k in {r["key"] for r in p["source_snapshots"]} for k in ("indicators", "chain", "buildup"))


def test_compare_all_ranks_viable_by_net_reward_risk_and_picks_the_preferred():
    p = build(risk_budget_inr=20000, max_allocation_pct=100)
    viable = [c for c in p["candidates"] if c["status"] == "candidate"]
    assert len(viable) >= 2 and p["status"] == "plan"
    best = max(viable, key=lambda c: c["risk_reward"]["net"])
    assert p["preferred"] == best["id"] and "not a probability" in p["ranking"]


def test_reproducibility_same_inputs_same_snapshots_same_plan():
    a = build()
    b = pl.build_plan(inputs(), copy.deepcopy(world()), datetime(2026, 10, 20, 9, 30, tzinfo=timezone.utc), TODAY)
    a2, b2 = dict(a), dict(b)
    a2.pop("generated_at"), b2.pop("generated_at")
    a2["summary"] = {k: v for k, v in a["summary"].items() if k != "generated_at"}
    b2["summary"] = {k: v for k, v in b["summary"].items() if k != "generated_at"}
    assert json.dumps(a2, sort_keys=True, default=str) == json.dumps(b2, sort_keys=True, default=str)
    assert a["plan_id"] == b["plan_id"]
    other = build(world(chain=chain(calls={1250.0: (39.0, 30000, 8000, 22.5)})))
    assert other["plan_id"] != a["plan_id"]                      # a changed source changes the fingerprint


def test_explain_plan_context_quotes_exact_ids_versions_and_legs():
    p = build(instrument="options")
    text = explain_plan_context(p, "abc123", "2026-10-20T04:00:00+00:00")
    assert p["plan_id"] in text and "abc123" in text and STRATEGY_RULES_VERSION in text and "payoff-v1" in text
    leg = cand(p, "options:bull_call_spread")["legs"][0]
    assert f"@ {leg['entry_price']}" in text and "call 1200" in text and "price as of 2026-10-19" in text and "sent to a broker" in text


def test_nothing_in_the_builder_imports_a_broker_or_writes():
    import services.strategy_plan.plan as plan_mod, services.strategy_plan.candidates as cand_mod, services.strategy_plan.evidence as ev_mod
    src = "".join(open(m.__file__).read() for m in (plan_mod, cand_mod, ev_mod))
    for word in ("place_order", "broker_native", "insert_one", "update_one", "delete_one", "httpx"):
        assert word not in src


# ── routes ───────────────────────────────────────────────────────────────────

class FakeCollection:
    def __init__(self):
        self.docs: List[Dict[str, Any]] = []
        self.writes = 0

    @staticmethod
    def _m(d, q):
        return all(d.get(k) == v for k, v in q.items())

    def find(self, q):
        outer = self

        class Cur:
            def __init__(s):
                s.docs = [copy.deepcopy(d) for d in outer.docs if outer._m(d, q)]

            def sort(s, key, direction):
                s.docs.sort(key=lambda d: str(d.get(key)), reverse=direction < 0)
                return s

            async def to_list(s, n):
                return s.docs[:n]
        return Cur()

    async def find_one(self, q):
        return next((copy.deepcopy(d) for d in self.docs if self._m(d, q)), None)

    async def count_documents(self, q):
        return sum(1 for d in self.docs if self._m(d, q))

    async def insert_one(self, doc):
        self.writes += 1
        self.docs.append(copy.deepcopy(doc))

    async def delete_one(self, q):
        for i, d in enumerate(self.docs):
            if self._m(d, q):
                self.writes += 1
                del self.docs[i]
                return type("R", (), {"deleted_count": 1})()
        return type("R", (), {"deleted_count": 0})()


class FakeDb:
    def __init__(self):
        self.col = FakeCollection()

    def __getitem__(self, name):
        assert name == route.PLANS == "desk_strategy_plans", name
        return self.col


A, B = {"X-Test-User": "user_a"}, {"X-Test-User": "user_b"}


@pytest.fixture
def client(monkeypatch):
    fake = FakeDb()
    monkeypatch.setattr(route, "db", fake)
    monkeypatch.setattr(route, "utcnow", lambda: NOW)
    monkeypatch.setattr(route, "today", lambda: TODAY)
    calls: List[Any] = []

    async def fake_collect(request, user_id, inp, today):
        calls.append((user_id, inp["underlying"]))
        return world()

    monkeypatch.setattr(route, "collect_snapshots", fake_collect)

    async def fake_user(request: Request):
        uid = request.headers.get("X-Test-User")
        if not uid:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {"user_id": uid}

    monkeypatch.setattr(route, "get_current_user", fake_user)
    app = FastAPI()
    app.include_router(route.router)
    c = TestClient(app)
    c.fake, c.calls = fake, calls
    return c


BODY = {"underlying": "RELIANCE", "direction": "bullish", "horizon": "positional", "instrument": "all", "capital": 1000000, "risk_budget_inr": 10000, "costs": COSTS}


def test_routes_require_sign_in(client):
    for method, url in (("post", "/api/desk/strategy/plan"), ("post", "/api/desk/strategy/plans"), ("get", "/api/desk/strategy/plans"),
                        ("get", "/api/desk/strategy/plans/x"), ("get", "/api/desk/strategy/plans/x/context"), ("delete", "/api/desk/strategy/plans/x")):
        r = getattr(client, method)(url, json=BODY) if method == "post" else getattr(client, method)(url)
        assert r.status_code == 401, (method, url)


def test_build_route_returns_a_plan_and_writes_nothing(client):
    r = client.post("/api/desk/strategy/plan", json=BODY, headers=A)
    assert r.status_code == 200
    p = r.json()
    assert p["status"] == "plan" and p["sent_to_broker"] is False and p["inputs"]["underlying"] == "RELIANCE"
    assert client.fake.col.writes == 0 and client.calls == [("user_a", "RELIANCE")]


def test_build_route_validation_codes_and_bad_json(client):
    r = client.post("/api/desk/strategy/plan", json={"underlying": "RELIANCE", "direction": "up"}, headers=A)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_input" and r.json()["detail"]["problems"][0]["code"] == "bad_direction"
    r = client.post("/api/desk/strategy/plan", content=b"{nope", headers=A)
    assert r.status_code == 422 and r.json()["detail"] == "invalid_body"
    assert client.calls == []


def test_save_list_get_context_delete_roundtrip(client):
    plan = client.post("/api/desk/strategy/plan", json=BODY, headers=A).json()
    s = client.post("/api/desk/strategy/plans", json={"plan": plan}, headers=A)
    assert s.status_code == 201 and s.json()["plan"] == plan and s.json()["sent_to_broker"] is False
    sid = s.json()["id"]
    doc = client.fake.col.docs[0]
    assert doc["user_id"] == "user_a" and doc["inputs_hash"] == plan["inputs_hash"] and doc["source_snapshots"] == plan["source_snapshots"] and doc["_id"] == sid
    lst = client.get("/api/desk/strategy/plans", headers=A).json()
    assert lst["count"] == 1 and lst["plans"][0]["id"] == sid and lst["plans"][0]["status"] == "plan" and lst["plans"][0]["underlying"] == "RELIANCE"
    got = client.get(f"/api/desk/strategy/plans/{sid}", headers=A).json()
    assert got["plan"] == plan
    ctx = client.get(f"/api/desk/strategy/plans/{sid}/context", headers=A).json()
    assert plan["plan_id"] in ctx["context"] and sid in ctx["context"] and ctx["plan_id"] == plan["plan_id"]
    d = client.delete(f"/api/desk/strategy/plans/{sid}", headers=A)
    assert d.status_code == 200 and d.json()["deleted"] is True and "only your saved copy" in d.json()["note"]
    assert client.get(f"/api/desk/strategy/plans/{sid}", headers=A).status_code == 404
    assert client.fake.col.writes == 2                       # one insert, one delete: nothing else was written


def test_list_is_newest_first_and_user_scoped(client, monkeypatch):
    times = iter(datetime(2026, 10, 20, h, 0, tzinfo=timezone.utc) for h in (5, 6, 7, 8))
    monkeypatch.setattr(route, "utcnow", lambda: next(times))
    ids = []
    for sym in ("RELIANCE", "TCS"):
        p = client.post("/api/desk/strategy/plan", json=dict(BODY, underlying=sym), headers=A).json()
        ids.append(client.post("/api/desk/strategy/plans", json={"plan": p}, headers=A).json()["id"])
    lst = client.get("/api/desk/strategy/plans", headers=A).json()
    assert [x["id"] for x in lst["plans"]] == ids[::-1]
    assert client.get("/api/desk/strategy/plans", headers=B).json()["count"] == 0


def test_another_users_plan_is_404_everywhere(client):
    plan = client.post("/api/desk/strategy/plan", json=BODY, headers=A).json()
    sid = client.post("/api/desk/strategy/plans", json={"plan": plan}, headers=A).json()["id"]
    for method, url in (("get", f"/api/desk/strategy/plans/{sid}"), ("get", f"/api/desk/strategy/plans/{sid}/context"), ("delete", f"/api/desk/strategy/plans/{sid}")):
        assert getattr(client, method)(url, headers=B).status_code == 404
    assert client.get(f"/api/desk/strategy/plans/{sid}", headers=A).status_code == 200      # still there
    assert client.get("/api/desk/strategy/plans/" + "x" * 200, headers=A).status_code == 404


def test_saved_plans_are_immutable_no_update_route(client):
    plan = client.post("/api/desk/strategy/plan", json=BODY, headers=A).json()
    sid = client.post("/api/desk/strategy/plans", json={"plan": plan}, headers=A).json()["id"]
    for method in ("put", "patch"):
        assert getattr(client, method)(f"/api/desk/strategy/plans/{sid}", json={"plan": plan}, headers=A).status_code == 405
    assert client.post(f"/api/desk/strategy/plans/{sid}", json={"plan": plan}, headers=A).status_code == 405
    methods = {m for r in route.router.routes for m in getattr(r, "methods", set())}
    assert "PUT" not in methods and "PATCH" not in methods


def test_save_rejects_a_changed_plan_a_non_plan_and_a_duplicate(client):
    plan = client.post("/api/desk/strategy/plan", json=BODY, headers=A).json()
    tampered = copy.deepcopy(plan)
    tampered["inputs"]["capital"] = 5
    r = client.post("/api/desk/strategy/plans", json={"plan": tampered}, headers=A)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "plan_id_mismatch"
    assert client.post("/api/desk/strategy/plans", json={"plan": {"x": 1}}, headers=A).json()["detail"]["code"] == "not_a_plan"
    live = dict(plan, sent_to_broker=True)
    assert client.post("/api/desk/strategy/plans", json={"plan": live}, headers=A).json()["detail"]["code"] == "sent_to_broker"
    assert client.post("/api/desk/strategy/plans", json={"plan": plan}, headers=A).status_code == 201
    dup = client.post("/api/desk/strategy/plans", json={"plan": plan}, headers=A)
    assert dup.status_code == 409 and dup.json()["detail"]["code"] == "already_saved"
    assert client.post("/api/desk/strategy/plans", json={"plan": plan}, headers=B).status_code == 201     # each user keeps their own copy


def test_saved_plan_limit(client, monkeypatch):
    monkeypatch.setattr(route, "MAX_SAVED_PLANS", 2)
    saved = []
    for sym in ("RELIANCE", "TCS", "INFY"):
        p = client.post("/api/desk/strategy/plan", json=dict(BODY, underlying=sym), headers=A).json()
        saved.append(client.post("/api/desk/strategy/plans", json={"plan": p}, headers=A))
    assert [s.status_code for s in saved] == [201, 201, 409] and saved[2].json()["detail"]["code"] == "plan_limit"
    assert client.get("/api/desk/strategy/plans", headers=A).json()["count"] == 2


def test_payoff_route_still_works(client):
    r = client.post("/api/desk/strategy/payoff", json={"underlying": "RELIANCE", "reference_price": 1200.0,
                                                       "legs": [{"kind": "cash", "side": "buy", "quantity": 10, "lot_size": 1, "entry_price": 1200.0}]}, headers=A)
    assert r.status_code == 200 and r.json()["valid"] is True and r.json()["sent_to_broker"] is False


# ── sources: a failing source becomes unavailable evidence, never a failed plan ──

def test_collect_snapshots_turns_every_failure_into_a_labelled_unavailable_source(monkeypatch):
    import asyncio
    from services.strategy_plan import sources as src

    async def boom(*a, **k):
        raise HTTPException(status_code=502, detail="upstream_unavailable")

    for name in ("_regime", "_sectors", "_indicators", "_patterns", "_scan_snapshot", "_features", "_financials", "_announcements", "_events",
                 "_corporate_actions", "_buildup", "_futures", "_expiries", "_calibration", "_scanner_bucket", "_portfolio"):
        monkeypatch.setattr(src, name, boom)

    async def no_hits(user_id, today):                      # the real reader never raises: a storage failure is the "failed" state
        return {"state": "failed", "reason": "MOCK: storage down", "symbols": {}, "scans": []}
    monkeypatch.setattr(src, "chartink_index", no_hits)
    i = inputs()
    snaps = asyncio.run(src.collect_snapshots(None, "user_a", i, TODAY))
    assert snaps and all(s["ok"] is False for s in snaps.values()) and "502" in snaps["indicators"]["error"]
    assert snaps["chain"]["error"].startswith("no expiry list") and snaps["peers"]["ok"] is False
    p = pl.build_plan(i, snaps, NOW, TODAY)
    assert p["status"] == "insufficient_data" and "required_source_failed" in {r["code"] for r in p["status_reasons"]}
    assert all(e["direction"] in ("unavailable",) or e["key"] == "validation_status" for e in p["evidence"] if e["value"] is None)


def test_collect_snapshots_picks_the_chain_expiry_by_rule(monkeypatch):
    import asyncio
    from services.strategy_plan import sources as src
    seen = []

    async def ok_expiries(request, sym):
        return expiries()

    async def ok_chain(request, sym, expiry):
        seen.append(expiry)
        return chain()

    async def other(*a, **k):
        return src_fail("not under test", "x")

    for name in ("_regime", "_sectors", "_indicators", "_patterns", "_scan_snapshot", "_features", "_financials", "_announcements", "_events",
                 "_corporate_actions", "_buildup", "_futures", "_calibration", "_scanner_bucket", "_portfolio"):
        monkeypatch.setattr(src, name, other)
    monkeypatch.setattr(src, "_expiries", ok_expiries)
    monkeypatch.setattr(src, "_chain", ok_chain)

    async def no_hits(user_id, today):
        return {"state": "no_source", "reason": "MOCK: no dashboard", "symbols": {}, "scans": []}
    monkeypatch.setattr(src, "chartink_index", no_hits)
    snaps = asyncio.run(src.collect_snapshots(None, "u", inputs(), TODAY))
    assert seen == [EXPIRY] and snaps["chain"]["ok"] and "nearest listed expiry" in snaps["chain"]["data"]["expiry_why"]


def test_sector_members_reads_each_list_once_names_unreadable_ones_and_matches_by_symbol(monkeypatch):
    import asyncio
    from services.copilot_tools import daas_client
    from services.strategy_plan import sources as src
    seen = []
    lists = {"Nifty Energy": ["RELIANCE", "ONGC"], "Nifty Oil & Gas": ["reliance"], "Nifty Auto": ["MARUTI"], "Nifty Pharma": [], "Nifty Bank": ["HDFCBANK"]}

    async def constituents(name, **k):
        seen.append(name)
        if name == "Nifty IT":
            raise RuntimeError("DaaS timeout")
        return lists[name]

    monkeypatch.setattr(daas_client, "get_index_constituents", constituents)
    out = asyncio.run(src._sector_members("RELIANCE", sectors()))
    assert sorted(seen) == sorted(r["index"] for r in sectors()["data"]["sectors"]) and len(seen) == 6        # one read per index
    d = out["data"]
    assert out["ok"] and d["member_of"] == ["Nifty Energy", "Nifty Oil & Gas"] and d["lists_read"] == 4
    assert d["unreadable"] == {"Nifty Pharma": "no constituent list on record", "Nifty IT": "RuntimeError: DaaS timeout"}
    failed = asyncio.run(src._sector_members("RELIANCE", src_fail("HTTP 500", "x")))
    assert failed["ok"] is False and "HTTP 500" in failed["error"]
