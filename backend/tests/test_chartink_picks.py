"""Best picks from the user's Chartink scans: services/strategy_plan/picks.py and GET /api/desk/chartink/picks.

No network and no real database. Everything below is MOCK — not real data: invented symbols (AAA, BBB ...) and invented scan names ("Mock Alpha Scan"), in the
RELIANCE-like fixture world of tests/test_strategy_plan.py. The plan builder (build_plan) and the evidence ledger are the real ones; only the sources are fixtures.

Expected scores are worked out from RULES["chartink_picks"]["weights"] and the credit each fixture figure earns (1 supports, 0.5 neutral, 0 conflicts or unavailable):

    AAA, 3 bullish scans, the default long world, 52-week high 4% away:  every factor supports except fundamentals (ROE 9.5 fails, D/E 0.4 passes, cash
        conversion unreadable: 1 of 2 readable tests = neutral, credit 0.5):  25+12+10+8+8+10+(10x0.5)+8+5+4 = 95 of 100
    BBB, 2 bullish scans, relative volume 1.2 (neutral), not F&O (the OI factor does not apply: 90 of weight):
        scan 25x2/3 + trend 12 + momentum 10 + rvol 8x0.5 + liquidity 8 + fundamentals 5 + event 8 + range 5 + atr 4 = 16.667+12+10+4+8+5+8+5+4 = 72.667 of 90
        -> 100 x 72.667 / 90 = 80.7
    CCC, 3 bullish and 1 bearish scan: scan credit (3 - 1 x 1.0) / 3 = 2/3, everything else as AAA: 95 - 25 x (1 - 2/3) = 86.667
"""
from __future__ import annotations

import asyncio
import inspect
import re
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

import routes.desk_chartink as route
from services.strategy_plan import ideas as ideas_mod
from services.strategy_plan import picks as pk
from services.strategy_plan import plan as pl
from services.strategy_plan import selection as sel
from services.strategy_plan import sources
from services.strategy_plan.evidence import src_fail, src_ok
from services.strategy_plan.rules import RULES, STRATEGY_RULES_VERSION
from tests.test_chartink_strategy import B1, B2, B3, hit, index
from tests.test_strategy_ideas import gate_row, merged
from tests.test_strategy_plan import (ASOF, NOW, TODAY, bearish_world, bucket, buildup, events, features, indicators, scan_row, world)

W = RULES["chartink_picks"]["weights"]
BEAR1 = [hit(7, "Mock Delta Scan", "bearish")]
BEAR2 = BEAR1 + [hit(8, "Mock Epsilon Scan", "bearish")]


def run(coro):
    return asyncio.run(coro)


def feat(**o):
    return features(**{"dist_52w_high_pct": -4.0, "dist_52w_low_pct": 60.0, **o})


def aaa(**over):
    """The default long world with the 52-week figures present: score 95 (module docstring)."""
    return world(features=feat(), **over)


def bbb():
    return world(features=feat(), indicators=indicators(rvol20=1.2), scan_row=scan_row(fno_eligible=False, traded_value_cr_20d=500.0),
                 buildup=src_fail("not an F&O stock", "x"), futures=src_fail("none", "x"), expiries=src_fail("none", "x"), chain=src_fail("none", "x"))


def thin():
    f = src_fail("DaaS feature row unavailable", "DaaS features")
    return world(indicators=src_fail("price history unavailable", "prices"), features=f, buildup=src_fail("none", "x"), financials=src_fail("none", "x"),
                 events=src_fail("calendar down", "events"), scan_row=src_fail("not in the snapshot", "snapshot"), expiries=src_fail("none", "x"),
                 futures=src_fail("none", "x"), chain=src_fail("none", "x"))


def conflicted():
    return world(features=feat(), indicators=indicators(close=1100.0, ema20=1120.0, ema50=1150.0, macd_hist=-1.0, roc20=-3.0, rvol20=0.7, atr_pct=5.5),
                 buildup=buildup("short_buildup"))


def ready(monkeypatch, hits, worlds, rows=None, scanner=None, index_over=None, state="ok", names=None):
    """Patch the sources picks.py reads. `worlds` maps symbol -> snapshot dict (collect_snapshots), `rows` the scan-snapshot gate rows."""
    ix = index(hits, state=state, **(index_over or {}))
    calls: Dict[str, Any] = {"collect": [], "plan": [], "index": 0}
    rows = rows if rows is not None else {s: gate_row(s, traded_value_cr_20d=100.0, name=f"Mock {s} Ltd") for s in hits}

    async def fake_index(user_id, today):
        calls["index"] += 1
        return ix

    async def fake_read(request):
        w, p = scanner if scanner is not None else (None, None)
        return w, p, []

    async def fake_gate():
        return (None, None, "upstream_unavailable") if rows == "down" else (rows, ASOF, None)

    async def fake_shared(user_id, chartink=None):
        return {"regime": src_ok({}, "x"), "sectors": src_ok({}, "x"), "portfolio": src_ok([], "x"), "sector_lists": {}, "chartink_index": chartink}

    async def fake_collect(request, user_id, inp, today, shared=None):
        calls["collect"].append((inp["underlying"], inp["direction"], bool(inp.get("live_broker_reads"))))
        if worlds.get(inp["underlying"]) == "boom":
            raise RuntimeError("source exploded")
        return {**worlds[inp["underlying"]], "chartink": sources.chartink_snapshot((shared or {}).get("chartink_index"), inp["underlying"])}

    real_build = pl.build_plan

    def counting_build(inputs, snaps, now, today):
        calls["plan"].append(inputs["underlying"])
        calls.setdefault("built", {})[inputs["underlying"]] = (inputs, snaps)
        return real_build(inputs, snaps, now, today)

    async def fake_name(symbol):
        return (names or {}).get(symbol)

    monkeypatch.setattr(pk, "chartink_index", fake_index)
    monkeypatch.setattr(pk.sel, "read_scanner", fake_read)
    monkeypatch.setattr(pk.sel, "_gate_rows", fake_gate)
    monkeypatch.setattr(pk, "shared_for_ideas", fake_shared)
    monkeypatch.setattr(pk, "collect_snapshots", fake_collect)
    monkeypatch.setattr(pk, "build_plan", counting_build)
    monkeypatch.setattr(pk, "company_name", fake_name)
    return calls


BIG = dict(capital=5_000_000, risk_budget_inr=50_000)          # sizing inputs: without them one share is sized and the fixed brokerage swamps the reward : risk


def picks(limit=5, direction="all", passed=None):
    return run(pk.build_picks(None, "user_a", limit, direction, BIG if passed is None else passed, NOW, TODAY))


def cand_of(plan, cid):
    return next(c for c in plan["candidates"] if c["id"] == cid)


def factor(p, key):
    return next(f for f in p["factors"] if f["key"] == key)


def expected(credits: Dict[str, float], applicable=None) -> float:
    """100 x points earned / weight of the applicable factors, from RULES weights and the credits worked out in the docstring."""
    keys = applicable or list(W)
    return round(100 * sum(W[k] * credits.get(k, 0.0) for k in keys) / sum(W[k] for k in keys), 1)


FULL = {k: 1.0 for k in W}
AAA_CREDITS = {**FULL, "fundamentals": 0.5}


# ── ranking ──────────────────────────────────────────────────────────────────

def test_rank_order_and_scores_follow_the_weights(monkeypatch):
    ready(monkeypatch, {"AAA": B3, "BBB": B2, "CCC": B3 + BEAR1}, {"AAA": aaa(), "BBB": bbb(), "CCC": aaa()})
    out = picks(limit=3)
    assert out["state"] == "ok" and out["label"] == "evidence score — not a probability" and out["sent_to_broker"] is False
    by = {p["symbol"]: p for p in out["picks"]}
    assert sum(W.values()) == 100
    assert by["AAA"]["score"] == expected(AAA_CREDITS) == 95.0
    assert by["CCC"]["score"] == expected({**AAA_CREDITS, "scan_confluence": 2 / 3}) == pytest.approx(86.7, abs=0.05)
    no_oi = [k for k in W if k != "oi_buildup"]
    assert by["BBB"]["score"] == expected({**AAA_CREDITS, "scan_confluence": 2 / 3, "relative_volume": 0.5}, no_oi) == pytest.approx(80.7, abs=0.05)
    assert [p["symbol"] for p in out["picks"]] == ["AAA", "CCC", "BBB"] and [p["rank"] for p in out["picks"]] == [1, 2, 3]
    assert out["considered"] == 3 and out["evaluated"] == 3 and out["returned"] == 3 and out["shortfall_reason"] is None
    # the OI factor does not apply to a stock outside F&O: it is listed as not applicable and does not lower the score
    assert factor(by["BBB"], "oi_buildup")["state"] == "not_applicable" and factor(by["BBB"], "oi_buildup")["points"] == 0
    assert by["BBB"]["available_weight_pct"] == 100.0


def test_every_factor_carries_tone_text_source_and_as_of(monkeypatch):
    ready(monkeypatch, {"AAA": B3}, {"AAA": aaa()})
    p = picks()["picks"][0]
    assert [f["key"] for f in p["factors"]] == list(W)
    for f in p["factors"]:
        assert set(f) >= {"key", "label", "weight", "points", "state", "tone", "text", "value", "source", "as_of"}
        assert f["state"] in ("supports", "neutral", "conflicts", "unavailable", "not_applicable")
        assert f["tone"] == {"supports": "up", "neutral": "flat", "conflicts": "down", "unavailable": "na", "not_applicable": "na"}[f["state"]]
        assert f["text"] and f["source"] and f["as_of"], f["key"]
    assert factor(p, "trend")["points"] == W["trend"] and factor(p, "fundamentals")["points"] == W["fundamentals"] * 0.5
    assert factor(p, "scan_confluence")["source"].startswith("Chartink scans") and factor(p, "scan_confluence")["as_of"] == "2026-10-20"
    assert factor(p, "liquidity")["value"] == 500.0 and factor(p, "range_position")["value"]["dist_52w_high_pct"] == -4.0


def test_reasons_for_and_against_are_ordered_by_weight(monkeypatch):
    w = world(features=feat(), events=events("2026-10-28"), indicators=indicators(rvol20=0.7))
    ready(monkeypatch, {"AAA": B3}, {"AAA": w})
    out = picks()
    p = (out["picks"] + out["wait"])[0]
    assert p["symbol"] == "AAA"
    fors = [r["key"] for r in p["reasons_for"]]
    assert fors[0] == "scan_confluence" and fors == sorted(fors, key=lambda k: -factor(p, k)["points"])
    against = [r["key"] for r in p["reasons_against"]]
    assert against == ["relative_volume", "event_risk"] or against == ["event_risk", "relative_volume"]
    assert against == sorted(against, key=lambda k: -W[k]) and all(r["text"] for r in p["reasons_against"])


def test_chartink_only_stocks_are_rankable_and_the_scanner_listing_is_labelled(monkeypatch):
    wb, pb = merged()                                                   # the scanner lists TCS, INFY, ICICIBANK, HDFCBANK
    rows = {s: gate_row(s, traded_value_cr_20d=100.0) for s in ("AAA", "TCS")}
    ready(monkeypatch, {"AAA": B3, "TCS": B2}, {"AAA": aaa(), "TCS": aaa()}, rows=rows, scanner=(wb, pb))
    by = {p["symbol"]: p for p in picks()["picks"]}
    assert by["AAA"]["source"] == "chartink" and by["AAA"]["in_ai_scanner"] is False
    assert by["TCS"]["source"] == "both" and by["TCS"]["in_ai_scanner"] is True and by["TCS"]["ai_score"] == pytest.approx(72.0)


# ── missing evidence ─────────────────────────────────────────────────────────

def test_missing_evidence_is_unavailable_and_never_neutral_or_positive(monkeypatch):
    # the same stock with and without its feature row: fundamentals and the 52-week range become unavailable and earn nothing
    ready(monkeypatch, {"AAA": B3, "BBB": B3}, {"AAA": aaa(), "BBB": world(features=src_fail("no feature row", "DaaS features"))})
    by = {p["symbol"]: p for p in picks()["picks"]}
    a, b = by["AAA"], by["BBB"]
    for k in ("fundamentals", "range_position"):
        f = factor(b, k)
        assert f["state"] == "unavailable" and f["tone"] == "na" and f["points"] == 0 and "no feature row" in f["text"]
    assert b["score"] == expected({**AAA_CREDITS, "fundamentals": 0, "range_position": 0}) == 85.0
    assert b["score"] < a["score"] and b["available_weight_pct"] == 100 - W["fundamentals"] - W["range_position"] == 85.0
    assert {u["key"] for u in b["unavailable"]} == {"fundamentals", "range_position"} and a["unavailable"] == []


def test_unreadable_cash_conversion_alone_does_not_hide_a_judgement_from_two_readable_tests(monkeypatch):
    ready(monkeypatch, {"AAA": B3}, {"AAA": world(features=feat(roe_pct=22.0, debt_to_equity=0.3))})
    f = factor(picks()["picks"][0], "fundamentals")
    assert f["state"] == "supports" and f["points"] == W["fundamentals"] and f["value"]["tests_readable"] == 2 and f["value"]["tests_passed"] == 2
    ready(monkeypatch, {"AAA": B3}, {"AAA": world(features=feat(roe_pct=22.0, debt_to_equity=None))})
    f = factor(picks()["picks"][0], "fundamentals")
    assert f["state"] == "unavailable" and f["points"] == 0 and "at least 2" in f["text"]


# ── conflicts ────────────────────────────────────────────────────────────────

def test_a_conflicting_scan_lowers_the_score_by_the_penalty(monkeypatch):
    ready(monkeypatch, {"AAA": B3, "BBB": B3 + BEAR1, "CCC": B3 + BEAR2}, {"AAA": aaa(), "BBB": aaa(), "CCC": aaa()})
    by = {p["symbol"]: p for p in picks()["picks"]}
    assert [by[s]["score"] for s in ("AAA", "BBB", "CCC")] == [expected({**AAA_CREDITS, "scan_confluence": c}) for c in (1.0, 2 / 3, 1 / 3)]
    f = factor(by["BBB"], "scan_confluence")
    assert f["state"] == "neutral" and f["value"]["aligned"] == 3 and f["value"]["opposed"] == 1 and "Mock Delta Scan" in f["text"]
    assert factor(by["CCC"], "scan_confluence")["state"] == "conflicts"
    assert any(r["key"] == "scan_confluence" for r in by["CCC"]["reasons_against"])


def test_equal_bullish_and_bearish_scans_is_wait_without_building_a_plan(monkeypatch):
    calls = ready(monkeypatch, {"AAA": B1 + BEAR1}, {})
    out = picks()
    assert out["picks"] == [] and calls["plan"] == [] and calls["collect"] == []
    w = out["wait"][0]
    assert w["symbol"] == "AAA" and w["outcome"] == "wait" and w["direction"] is None and w["score"] is None
    assert "bullish and bearish" in w["wait_reasons"][0] and out["shortfall_reason"]


# ── Wait / No trade ──────────────────────────────────────────────────────────

def test_thin_evidence_is_wait_with_the_unavailable_list(monkeypatch):
    ready(monkeypatch, {"AAA": B3, "BBB": B3}, {"AAA": thin(), "BBB": aaa()})
    out = picks()
    assert [p["symbol"] for p in out["picks"]] == ["BBB"]
    w = out["wait"][0]
    assert w["symbol"] == "AAA" and w["outcome"] == "wait" and w["rank"] is None and w["strategies"] == []
    need = RULES["chartink_picks"]["outcome"]["min_available_weight_pct"]
    assert w["available_weight_pct"] < need and f"{need:g}%" in w["wait_reasons"][0] and "thin" in w["wait_reasons"][0].lower()
    assert len(w["unavailable"]) >= 4 and w["score"] is not None          # the score is still shown, so the user sees why it did not qualify
    assert "1 of 2" in out["shortfall_reason"] or "AAA" in out["shortfall_reason"]


def test_conflicting_evidence_is_no_trade(monkeypatch):
    ready(monkeypatch, {"AAA": B3}, {"AAA": conflicted()})
    out = picks()
    w = out["wait"][0]
    conflicts = [f for f in w["factors"] if f["state"] == "conflicts"]
    supports = [f for f in w["factors"] if f["state"] == "supports"]
    assert len(conflicts) >= RULES["chartink_picks"]["outcome"]["min_conflicts"] and len(conflicts) >= len(supports)
    assert w["outcome"] == "no_trade" and "conflict" in w["wait_reasons"][0].lower() and out["picks"] == []


def test_a_score_under_the_minimum_is_wait(monkeypatch):
    low = world(features=feat(dist_52w_high_pct=-55.0), indicators=indicators(close=1160.0, ema20=1150.0, ema50=1150.0, macd_hist=-1.0, roc20=-2.0, rvol20=1.1))
    ready(monkeypatch, {"AAA": B1}, {"AAA": low})
    out = picks()
    w = out["wait"][0]
    assert w["score"] < RULES["chartink_picks"]["outcome"]["min_score"] and w["outcome"] == "wait" and out["picks"] == []
    assert "minimum" in w["wait_reasons"][0]


def no_fno(**o):
    return world(features=feat(), scan_row=scan_row(fno_eligible=False), buildup=src_fail("n", "x"), futures=src_fail("n", "x"), expiries=src_fail("n", "x"),
                 chain=src_fail("n", "x"), **o)


def test_a_plan_that_says_no_trade_is_not_a_pick_and_offers_no_strategies(monkeypatch):
    # a cash-only stock with results inside the horizon: the plan builder gates its only candidate (event_in_horizon, avoid_events is on by default)
    ready(monkeypatch, {"AAA": B3}, {"AAA": no_fno(events=events("2026-10-28"))})
    out = picks()
    w = out["wait"][0]
    assert out["picks"] == [] and w["symbol"] == "AAA" and w["outcome"] == "no_trade" and w["plan_status"] == "no_trade" and w["strategies"] == []
    assert w["score"] >= RULES["chartink_picks"]["outcome"]["min_score"]                          # the evidence was strong: the plan is what said no
    assert "Results are scheduled on 2026-10-28" in w["wait_reasons"][0] and "strategy plan says no trade" in w["wait_reasons"][0]
    assert any(r["key"] == "event_risk" for r in w["reasons_against"])


def test_results_inside_the_horizon_cost_the_event_factor_and_leave_only_the_hedged_structure(monkeypatch):
    ready(monkeypatch, {"AAA": B3}, {"AAA": world(features=feat(), events=events("2026-10-28"))})
    p = picks()["picks"][0]
    assert [r["key"] for r in p["reasons_against"]] == ["event_risk"] and factor(p, "event_risk")["points"] == 0
    live = [s["id"] for s in p["strategies"] if s["status"] == "candidate"]
    assert live == ["combination:collar"]                                                  # the long put defines the downside, so the event does not block it
    assert all(s["status"] == "no_trade" for s in p["strategies"] if s["segment"] in ("cash", "futures", "options"))


def test_a_stock_whose_sources_blow_up_is_wait_and_the_others_survive(monkeypatch):
    ready(monkeypatch, {"AAA": B3, "BBB": B3}, {"AAA": "boom", "BBB": aaa()})
    out = picks()
    assert [p["symbol"] for p in out["picks"]] == ["BBB"]
    w = out["wait"][0]
    assert w["symbol"] == "AAA" and w["outcome"] == "wait" and "source exploded" in w["wait_reasons"][0]


# ── gates, limit, shortfall ──────────────────────────────────────────────────

def test_stocks_failing_the_eligibility_gates_are_excluded_with_the_reason(monkeypatch):
    rows = {"AAA": gate_row("AAA", traded_value_cr_20d=100.0), "BBB": gate_row("BBB", traded_value_cr_20d=3.0), "CCC": gate_row("CCC", is_etf=True)}
    ready(monkeypatch, {"AAA": B3, "BBB": B3, "CCC": B3, "ZZZ": B3}, {"AAA": aaa()}, rows=rows)
    out = picks()
    assert [p["symbol"] for p in out["picks"]] == ["AAA"]
    assert {(x["symbol"], x["code"]) for x in out["excluded"]} == {("BBB", "illiquid"), ("CCC", "etf"), ("ZZZ", "not_in_snapshot")}
    assert out["considered"] == 4 and out["evaluated"] == 1


def test_unreadable_scan_snapshot_means_no_picks_with_the_reason(monkeypatch):
    calls = ready(monkeypatch, {"AAA": B3}, {}, rows="down")
    out = picks()
    assert out["picks"] == [] and "upstream_unavailable" in out["empty_reason"] and calls["collect"] == []


def test_limit_caps_the_picks_and_counts_the_rest(monkeypatch):
    hits = {s: B3 for s in ("AAA", "BBB", "CCC", "DDD")}
    ready(monkeypatch, hits, {s: aaa() for s in hits})
    out = picks(limit=2)
    assert len(out["picks"]) == 2 and out["qualified"] == 4 and out["returned"] == 2 and out["limit"] == 2
    assert [p["symbol"] for p in out["picks"]] == ["AAA", "BBB"]               # equal scores: more scans, then traded value, then symbol


def test_fewer_picks_than_asked_says_why(monkeypatch):
    ready(monkeypatch, {"AAA": B3, "BBB": B3, "CCC": B3}, {"AAA": aaa(), "BBB": thin(), "CCC": conflicted()})
    out = picks(limit=5)
    assert [p["symbol"] for p in out["picks"]] == ["AAA"] and out["returned"] == 1
    why = out["shortfall_reason"]
    assert "1 of the 5" in why and "Wait / No trade" in why and "BBB" in why and "CCC" in why


def test_only_the_evaluation_cap_is_evaluated(monkeypatch):
    cap = RULES["chartink_picks"]["evaluate_max"]
    syms = [f"S{i:02d}" for i in range(cap + 3)]
    calls = ready(monkeypatch, {s: B3 for s in syms}, {s: aaa() for s in syms})
    out = picks(limit=10)
    assert len(calls["collect"]) == cap == out["evaluated"] and out["not_evaluated"] == 3 and out["considered"] == cap + 3
    assert len(out["picks"]) == 10 and out["qualified"] == cap and out["shortfall_reason"] is None


# ── direction ────────────────────────────────────────────────────────────────

def test_a_stock_with_bearish_scans_is_a_short_side_pick_built_with_the_bearish_plan(monkeypatch):
    calls = ready(monkeypatch, {"AAA": B3, "BBB": BEAR2}, {"AAA": aaa(), "BBB": bearish_world(features=feat(dist_52w_high_pct=-30.0, dist_52w_low_pct=6.0))})
    out = picks()
    by = {p["symbol"]: p for p in out["picks"] + out["wait"]}
    assert by["AAA"]["direction"] == "long" and by["BBB"]["direction"] == "short"
    assert ("BBB", "bearish", False) in calls["collect"] and ("AAA", "bullish", False) in calls["collect"]
    b = by["BBB"]
    assert "no naked short options" in b["action"] and b["scans"]["aligned"][0]["direction"] == "bearish"
    assert factor(b, "scan_confluence")["value"]["aligned"] == 2 and factor(b, "range_position")["state"] == "supports"      # 6% above the 52-week low
    # a short never carries an undefined-risk option structure
    for s in b["strategies"]:
        assert s["segment"] != "combination" or s["family"] == "none"
    only_long = picks(direction="long")
    assert [p["symbol"] for p in only_long["picks"] + only_long["wait"]] == ["AAA"]
    only_short = picks(direction="short")
    assert [p["symbol"] for p in only_short["picks"] + only_short["wait"]] == ["BBB"]


# ── strategies ───────────────────────────────────────────────────────────────

def test_strategies_come_from_build_plan_exactly(monkeypatch):
    calls = ready(monkeypatch, {"AAA": B3}, {"AAA": aaa()})
    passed = {"capital": 1000000, "risk_budget_inr": 10000}
    p = picks(passed=passed)["picks"][0]
    inp, probs = pl.normalise_inputs({"underlying": "AAA", "direction": "bullish", "instrument": "all", **passed})
    inp["live_broker_reads"] = False
    built_inp, built_snaps = calls["built"]["AAA"]
    assert built_inp == inp and not probs                                 # the plan was built from exactly the inputs the pick reports
    ref = pl.build_plan(inp, built_snaps, NOW, TODAY)
    assert calls["plan"] == ["AAA"]                                       # one plan build per stock, nothing else makes strategies
    assert p["plan_id"] == ref["plan_id"] and p["plan_status"] == ref["status"] == "plan" and p["preferred"] == ref["preferred"]
    assert [{k: v for k, v in s.items() if k != "payoff_request"} for s in p["strategies"]] == ideas_mod.strategies_of(ref, "AAA") and len(p["strategies"]) >= 3
    segments = {s["segment"] for s in p["strategies"]}
    assert {"cash", "futures", "options"} <= segments
    assert all(s["id"] and "max_loss" in s and "sizing" in s and "breakeven" in s and (s["legs_text"] or s["status"] != "candidate") for s in p["strategies"])
    # each strategy carries the body that draws its payoff through the payoff engine: the plan's own legs and spot, nothing recalculated here
    for s in p["strategies"]:
        c = cand_of(ref, s["id"])
        if not c["legs"]:
            assert s["payoff_request"] is None
            continue
        r = s["payoff_request"]
        assert r["underlying"] == "AAA" and r["reference_price"] == ref["underlying"]["spot"] == 1200.0 and r["as_of"] == ref["data_as_of"]["price"]
        assert [(l["kind"], l["side"], l["quantity"], l["lot_size"], l["entry_price"], l["strike"], l["option_type"]) for l in r["legs"]] == [
            (l["kind"], l["side"], l["quantity"], l["lot_size"], l["entry_price"], l.get("strike"), l.get("option_type")) for l in c["legs"]]
        g = c["payoff"]["expiry"]["grid"]
        assert r["grid"] == {"min": g[0], "max": g[-1], "points": len(g)}
    assert p["plan_inputs"] == {"underlying": "AAA", "direction": "bullish", "instrument": "all", **passed}
    assert p["data_as_of"] == ref["data_as_of"]


def test_margin_is_not_invented_and_no_order_is_sent(monkeypatch):
    ready(monkeypatch, {"AAA": B3}, {"AAA": aaa()})
    out = picks()
    assert out["sent_to_broker"] is False and "margin" not in out["picks"][0]       # no margin source exists: the field is absent, never a number
    src = inspect.getsource(pk)
    assert not re.search(r"place_order|submit_order|cancel_order|modify_order|kite\.|\.order\(", src)
    assert not [n for n in dir(pk) if re.search(r"(place|submit|cancel|modify|send)_?order", n, re.I)]
    # the route is a GET, and the module imports no broker client
    assert [m for r in route.router.routes if r.path.endswith("/picks") for m in r.methods] == ["GET"]
    assert "broker" not in " ".join(re.findall(r"^(?:from|import) .*$", src, re.M)).lower()


def test_the_data_as_of_block_names_the_chartink_scan_date_and_the_price_day(monkeypatch):
    ready(monkeypatch, {"AAA": B3}, {"AAA": aaa()})
    d = picks()["data_as_of"]
    assert d["mode"] == "end_of_day" and d["chartink"]["scan_date"] == "2026-10-20" and d["price"] == ASOF and d["fno"] == ASOF and d["scan_eligibility"] == ASOF


# ── states ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("state", ["no_source", "not_refreshed", "stale", "failed"])
def test_a_chartink_state_other_than_ok_returns_no_picks_and_reads_no_other_source(monkeypatch, state):
    calls = ready(monkeypatch, {"AAA": B3}, {"AAA": aaa()}, state=state)
    out = picks()
    assert out["state"] == state and out["reason"] == f"MOCK reason for {state}" and out["picks"] == [] and out["wait"] == [] and out["data_as_of"]["chartink"] is None
    assert calls["collect"] == [] and calls["plan"] == [] and out["empty_reason"] == out["reason"]


def test_an_ok_index_with_no_hits_is_an_honest_empty(monkeypatch):
    ready(monkeypatch, {}, {})
    out = picks()
    assert out["state"] == "ok" and out["picks"] == [] and "listed no stock" in out["empty_reason"] and out["data_as_of"]["chartink"]["scan_date"] == "2026-10-20"


def test_neutral_only_scans_make_no_candidate(monkeypatch):
    ready(monkeypatch, {"AAA": [hit(9, "Mock Zeta Scan", "neutral")]}, {})
    out = picks()
    assert out["picks"] == [] and out["wait"] == [] and out["considered"] == 0 and "neutral" in out["empty_reason"]


# ── the rules ────────────────────────────────────────────────────────────────

def test_thresholds_live_in_rules_and_the_version_moved():
    c = RULES["chartink_picks"]
    assert STRATEGY_RULES_VERSION.startswith("strategy-rules.v1.5") and RULES["version"] == STRATEGY_RULES_VERSION
    assert (c["limit_default"], c["limit_max"]) == (5, 10) and c["label"] == "evidence score — not a probability"
    assert set(c["weights"]) == set(pk.FACTOR_ORDER)


# ── the route ────────────────────────────────────────────────────────────────

A = {"X-Test-User": "user_a"}


@pytest.fixture
def client(monkeypatch):
    seen: List[Any] = []

    async def fake_user(request: Request):
        uid = request.headers.get("X-Test-User")
        if not uid:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {"user_id": uid}

    async def fake_build(request, user_id, limit, direction, passed, now, today):
        seen.append((user_id, limit, direction, dict(passed)))
        return {"state": "ok", "picks": [], "limit": limit, "direction_filter": direction}

    monkeypatch.setattr(route, "get_current_user", fake_user)
    monkeypatch.setattr(route.picks_mod, "build_picks", fake_build)
    app = FastAPI()
    app.include_router(route.router)
    c = TestClient(app)
    c.seen = seen
    return c


def test_route_requires_sign_in(client):
    assert client.get("/api/desk/chartink/picks").status_code == 401 and client.seen == []


def test_route_defaults_and_validation(client):
    r = client.get("/api/desk/chartink/picks", headers=A)
    assert r.status_code == 200 and client.seen[-1] == ("user_a", 5, "all", {})
    r = client.get("/api/desk/chartink/picks?limit=10&direction=short&capital=1000000&risk_budget_inr=10000", headers=A)
    assert r.status_code == 200 and client.seen[-1] == ("user_a", 10, "short", {"capital": 1000000.0, "risk_budget_inr": 10000.0})
    for q, code in (("limit=11", "invalid_limit"), ("limit=0", "invalid_limit"), ("limit=abc", "invalid_limit"), ("direction=sideways", "invalid_direction"),
                    ("capital=-5", "invalid_input"), ("risk_budget_inr=abc", "invalid_input")):
        r = client.get("/api/desk/chartink/picks?" + q, headers=A)
        assert r.status_code == 422 and r.json()["detail"]["code"] == code, (q, r.text)
    assert len(client.seen) == 2
    assert client.post("/api/desk/chartink/picks", headers=A).status_code == 405
