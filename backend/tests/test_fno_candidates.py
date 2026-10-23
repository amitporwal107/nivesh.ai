"""Top candidates per F&O build-up category, v2 (services/fno_candidates + GET /api/fno/scan/candidates).

Three separate scores (Signal Strength, Tradeability, Strategy Quality); a missing input is never redistributed (the score keeps its 100-point
denominator and reports coverage); fundamentals are a context panel, not an input; every setting is a research setting that has not been
validated. MOCK — not real data: the scan body and the feature rows are invented, in the shape the data platform sends
(nidp/services/daas_api/routers/desk_market.py fno_buildup and features.py features_bulk). No network and no Mongo.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from routes import fno as route
from services.fno_candidates import engine
from services.fno_candidates.rules import RULES

DAY = "2026-10-22"


def row(symbol: str, label: str, price: float, oi: float, **extra: Any) -> Dict[str, Any]:
    base = {"symbol": symbol, "label": label, "price_chg_pct": price, "oi_chg_pct": oi, "oi": 1_000_000, "close": 100.0, "near_expiry": "2026-10-27",
            "days_to_expiry": 5, "fut_turnover_cr": 500.0, "cash_close": 99.0, "cash_chg_pct": price, "cash_confirmation": "confirms",
            "cash_volume": 4_000_000, "vol_z20": 2.0, "fno_eligible": True, "risk_flags": [], "sector": "IT"}
    return {**base, **extra}


BUILDUP = {
    "as_of": DAY, "source": "NSE F&O bhavcopy (fixture)", "universe": 20,
    "rows": [
        row("LB1", "long_buildup", 2.5, 12.0),
        row("LB2", "long_buildup", 1.0, 15.0, cash_confirmation="diverges", cash_chg_pct=-0.4, vol_z20=0.2),
        row("LBTHIN", "long_buildup", 2.0, 30.0, fut_turnover_cr=10.0),
        row("LBSMALL", "long_buildup", 0.2, 9.0),
        row("LBNOTURN", "long_buildup", 3.0, 9.0, fut_turnover_cr=None),
        row("LBNOFNO", "long_buildup", 3.0, 9.0, fno_eligible=False),
        row("SB1", "short_buildup", -3.1, 14.0, cash_chg_pct=-2.8),
        row("SB2", "short_buildup", -1.2, 9.0),
        row("SC1", "short_covering", 1.8, -6.0),
        row("LU1", "long_unwinding", -1.5, -8.0),
        row("NEUT", "neutral", 0.0, 0.0),
        {"symbol": "NOLABEL", "label": None, "price_chg_pct": None, "oi_chg_pct": None},
    ],
    "indices": [
        {"symbol": "NIFTY", "index_name": "Nifty 50", "label": "short_buildup", "price_chg_pct": -0.14, "oi_chg_pct": 4.62, "cash_close": 22687.65,
         "cash_chg_pct": -0.31, "cash_confirmation": "confirms", "near_expiry": "2026-10-27", "days_to_expiry": 5, "risk_flags": ["expiry_week"]},
        {"symbol": "BANKNIFTY", "index_name": "Nifty Bank", "label": "neutral", "price_chg_pct": 0.0, "oi_chg_pct": 0.0},
        {"symbol": "FINNIFTY", "index_name": "Nifty Fin", "label": "long_buildup", "price_chg_pct": 1.0, "oi_chg_pct": 5.0},
    ],
    "risk_flag_text": {"expiry_week": "The nearest contract expires within 7 calendar days."},
}


def bull_features(**over: Any) -> Dict[str, Any]:
    f = {"as_of_date": DAY, "sector": "IT", "close": 110.0, "sma20": 100.0, "sma50": 95.0, "rsi14": 62.0, "macd_hist": 0.5, "deliv_trend10": 1.2,
         "deliv_pct_avg_20": 48.0, "vol_z20": 1.4, "avg_volume_20": 2_000_000, "accumulation_score": 60.0, "dist_200dma_pct": 8.0, "return_5d_pct": 3.0,
         "return_20d_pct": 6.0, "atr_pct": 2.1, "roe_pct": 20.0, "roce_pct": 22.0, "debt_to_equity": 0.3, "pat_growth_yoy_pct": 15.0,
         "eps_growth_3y_cagr_pct": 18.0, "promoter_pledged_pct": 0.0, "pe_ttm": 24.0, "pe_vs_sector_pct": -5.0, "market_cap_cr": 120000.0, "promoter_pct": 55.0}
    f.update(over)
    return f


def bear_features(**over: Any) -> Dict[str, Any]:
    return bull_features(**{"close": 90.0, "rsi14": 38.0, "macd_hist": -0.6, "deliv_trend10": 0.4, "return_5d_pct": -4.0, "roe_pct": 4.0, "roce_pct": 6.0,
                            "debt_to_equity": 2.5, "pat_growth_yoy_pct": -12.0, "eps_growth_3y_cagr_pct": -3.0, "promoter_pledged_pct": 35.0, **over})


FEATURES: Dict[str, List[Dict[str, Any]]] = {
    "LB1": [bull_features(as_of_date="2026-10-21"), bull_features()],
    "LB2": [bear_features()],                 # a stock on the wrong side for a long: it ranks below LB1 despite its bigger OI change
    "SB1": [bear_features()],
    "SB2": [bull_features()],
    "SC1": [bull_features(rsi14=80.0)],       # RSI stretched
    "LU1": [bear_features(rsi14=None)],       # RSI missing
}


def pools(rules=RULES):
    return engine.select_pools(BUILDUP, rules)


def build(per: int = 5, features: Any = None, rules=RULES):
    return engine.assemble(BUILDUP, pools(rules), FEATURES if features is None else features, per, rules)


def cat(out, name):
    return {c["symbol"]: c for c in out["categories"][name]["candidates"]}


def sig(c):
    return c["scores"]["signal_strength"]


def inp(block, key):
    return next(x for x in block["inputs"] if x["key"] == key)


def states(checks):
    return {c["key"]: c["state"] for c in checks}


# ── pools ────────────────────────────────────────────────────────────────

def test_rows_are_grouped_by_the_scans_label_and_neutral_or_unlabelled_rows_never_appear():
    p = pools()
    assert {c: p[c]["in_scan"] for c in p} == {"long_buildup": 6, "short_buildup": 2, "short_covering": 1, "long_unwinding": 1}
    out = build()
    every = [c["symbol"] for k in out["categories"].values() for c in k["candidates"]] + [u["symbol"] for k in out["categories"].values() for u in k["unranked"]]
    assert "NEUT" not in every and "NOLABEL" not in every


def test_floors_exclude_and_count_thin_small_unknown_turnover_and_non_fno_rows():
    ex = pools()["long_buildup"]["excluded"]
    assert ex == {"not_fno_eligible": 1, "no_turnover": 1, "thin_futures": 1, "small_move": 1}
    assert [r["symbol"] for r in pools()["long_buildup"]["pool"]] == ["LB2", "LB1"]          # largest |OI change| first


# ── the score model: three separate scores, no redistribution ────────────

def test_the_signal_strength_weights_are_the_prds_and_come_from_the_rules():
    assert RULES["signal_weights"] == {"oi_signal": 30, "price_behavior": 20, "volume": 15, "options_confirmation": 15, "cash_delivery": 10, "technical": 10}
    assert sum(RULES["signal_weights"].values()) == 100
    assert RULES["research_status"] == "research_setting_not_validated"


def test_a_missing_input_is_never_redistributed_worked_example():
    b = engine.score_block({"a": 50, "b": 50}, {"a": "A", "b": "B"}, {"a": (80.0, "seen", None), "b": (None, None, "no data")})
    # a earns 50 x 80 / 100 = 40 points of the 100; b's 50 points stay unearned: the score is 40, not 80
    assert (b["points"], b["max_points"], b["coverage"], b["complete"]) == (40.0, 100.0, 0.5, False)
    assert b["missing"] == [{"key": "b", "label": "B", "weight": 50, "reason": "no data"}]


def test_signal_strength_worked_by_hand_for_the_best_candidate_and_it_is_incomplete_without_the_options_input():
    s = sig(cat(build(), "long_buildup")["LB1"])
    # OI +12% -> 0.8 x 100 = 80 -> 24.0 of 30 | futures +2.5% -> 83.3 -> 16.7 of 20 | cash volume 2.0x its average -> 100 -> 15.0 of 15
    # options-chain confirmation: not computed for stocks yet -> 0 of 15, listed as missing | cash/delivery 2 of 2 -> 100 -> 10.0 | technical 2 of 2 -> 100 -> 10.0
    assert [inp(s, k)["points"] for k in ("oi_signal", "price_behavior", "volume", "cash_delivery", "technical")] == [24.0, 16.7, 15.0, 10.0, 10.0]
    assert inp(s, "options_confirmation")["score"] is None
    assert s["points"] == 75.7 and s["max_points"] == 100.0           # 24 + 16.667 + 15 + 10 + 10, out of 100: NOT scaled up by the missing 15
    assert (s["coverage"], s["complete"]) == (0.85, False)
    assert [m["key"] for m in s["missing"]] == ["options_confirmation"] and s["missing"][0]["weight"] == 15


def test_a_second_missing_input_lowers_coverage_and_the_score_never_rises_because_something_went_missing():
    full = engine._candidate("long_buildup", row("FULL", "long_buildup", 2.5, 12.0), bull_features(), RULES)
    gap = engine._candidate("long_buildup", row("MISS", "long_buildup", 2.5, 12.0, cash_volume=None), bull_features(), RULES)
    assert sig(full)["points"] == 75.7 and sig(gap)["points"] == 60.7  # 75.667 - the volume input's 15 points
    assert sig(gap)["coverage"] == 0.70 and [m["key"] for m in sig(gap)["missing"]] == ["volume", "options_confirmation"]
    assert sig(gap)["points"] <= sig(full)["points"]


def test_relative_volume_is_cash_volume_over_its_20_day_average_zero_at_1x_and_full_at_2x():
    def vol(cash, avg):
        r = row("V", "long_buildup", 2.0, 8.0, cash_volume=cash)
        return inp(sig(engine._candidate("long_buildup", r, bull_features(avg_volume_20=avg), RULES)), "volume")
    assert [vol(c, 2_000_000)["score"] for c in (2_000_000, 3_000_000, 4_000_000, 6_000_000)] == [0.0, 50.0, 100.0, 100.0]
    assert vol(3_000_000, 2_000_000)["observed"] == "1.50x its 20-day average"
    assert vol(3_000_000, None)["score"] is None and vol(None, 2_000_000)["score"] is None      # unknown, not 0
    assert vol(3_000_000, 0)["score"] is None


# ── minimum coverage gate ────────────────────────────────────────────────

def test_a_candidate_below_the_minimum_coverage_is_not_ranked_and_is_listed_with_why():
    body = {"as_of": DAY, "rows": [row("OK1", "long_buildup", 2.0, 9.0), row("GAP", "long_buildup", 2.0, 10.0, cash_volume=None)], "indices": []}
    out = engine.assemble(body, engine.select_pools(body), {"OK1": [bull_features()], "GAP": [bull_features()]}, 5)
    k = out["categories"]["long_buildup"]
    assert [c["symbol"] for c in k["candidates"]] == ["OK1"]                    # GAP has the bigger OI change but only 70% coverage
    assert [u["symbol"] for u in k["unranked"]] == ["GAP"] and k["excluded"]["insufficient_coverage"] == 1
    assert "70%" in k["unranked"][0]["reason"] and "below the 80% minimum" in k["unranked"][0]["reason"] and "Volume / relative volume" in k["unranked"][0]["reason"]


def test_the_minimum_coverage_is_configurable():
    rules = copy.deepcopy(RULES)
    rules["min_coverage"]["signal_strength"] = 0.95
    out = build(rules=rules)
    assert all(not v["candidates"] for v in out["categories"].values())         # no stock can reach 95%: options-chain is never available yet
    assert sum(len(v["unranked"]) for v in out["categories"].values()) > 0


# ── tradeability is its own score ────────────────────────────────────────

def test_tradeability_is_a_separate_score_with_its_own_weights_and_coverage():
    t = cat(build(), "long_buildup")["LB1"]["scores"]["tradeability"]
    # turnover 500 cr = 10 x the 50 cr floor -> 100 -> 50.0 of 50 | 5 days to expiry -> (5 - 1) / (7 - 1) = 66.7 -> 16.7 of 25 | spread and depth: none in end-of-day data
    assert (inp(t, "liquidity")["points"], inp(t, "expiry_distance")["points"]) == (50.0, 16.7)
    assert (t["points"], t["coverage"], t["complete"]) == (66.7, 0.75, False)
    assert [m["key"] for m in t["missing"]] == ["spread_depth"]


def test_a_strong_signal_on_a_thin_contract_shows_high_strength_and_low_tradeability_never_one_blended_number():
    c = engine._candidate("long_buildup", row("THIN", "long_buildup", 2.5, 12.0, fut_turnover_cr=55.0), bull_features(), RULES)
    assert sig(c)["points"] == 75.7 and c["scores"]["tradeability"]["points"] < 25.0
    assert not {"score", "rank_score", "total", "overall"} & set(c) and not {"score", "rank_score", "total"} & set(c["scores"])


def test_strategy_quality_is_unavailable_with_reasons_never_a_number():
    sq = cat(build(), "long_buildup")["LB1"]["scores"]["strategy_quality"]
    assert sq["state"] == "unavailable" and "points" not in sq and len(sq["reasons"]) == 2
    assert any("STT" in r for r in sq["reasons"]) and any("probability-of-profit" in r for r in sq["reasons"])


# ── fundamentals are context, not an input ───────────────────────────────

def test_fundamentals_change_no_score_and_never_remove_a_candidate():
    r = row("ZZZ", "long_buildup", 2.5, 12.0)
    weak_f = bull_features(roe_pct=2.0, roce_pct=2.0, debt_to_equity=4.0, pat_growth_yoy_pct=-20.0, eps_growth_3y_cagr_pct=-5.0, promoter_pledged_pct=60.0)
    strong, weak = engine._candidate("long_buildup", r, bull_features(), RULES), engine._candidate("long_buildup", r, weak_f, RULES)
    assert strong["fundamental_context"]["rating"] == "strong" and weak["fundamental_context"]["rating"] == "weak"
    assert strong["scores"]["signal_strength"] == weak["scores"]["signal_strength"] and strong["scores"]["tradeability"] == weak["scores"]["tradeability"]
    assert "fundamental" not in " ".join(RULES["signal_weights"]) and weak["ranked"] is True
    assert "fundamentals" not in strong                                            # the old in-score key is gone


def test_fundamental_rating_and_whether_it_agrees_with_the_direction():
    cands = {c["symbol"]: c for k in build()["categories"].values() for c in k["candidates"]}
    lb1 = cands["LB1"]["fundamental_context"]
    assert (lb1["rating"], lb1["agrees_with_direction"], lb1["holds"], lb1["known"]) == ("strong", True, 6, 6)
    sb1 = cands["SB1"]["fundamental_context"]
    assert (sb1["rating"], sb1["agrees_with_direction"]) == ("weak", True)
    sb2 = cands["SB2"]["fundamental_context"]
    assert (sb2["rating"], sb2["agrees_with_direction"]) == ("strong", False)
    lb2 = cands["LB2"]["fundamental_context"]
    assert (lb2["rating"], lb2["agrees_with_direction"]) == ("weak", False)


def test_mixed_and_unavailable_fundamentals():
    mixed = engine.fundamentals("bullish", bull_features(roe_pct=5.0, roce_pct=5.0, debt_to_equity=3.0))
    assert mixed["rating"] == "mixed" and mixed["agrees_with_direction"] is None
    none = engine.fundamentals("bullish", {"roe_pct": 20.0, "roce_pct": 20.0})
    assert none["rating"] == "unavailable" and none["agrees_with_direction"] is None and none["known"] == 2


# ── ranking ──────────────────────────────────────────────────────────────

def test_ranking_is_by_signal_strength_points_even_against_a_larger_oi_change_and_per_limits_the_list():
    # LB2: OI +15% -> 30.0 | futures +1.0% -> 6.7 | volume 100 -> 15.0 | cash/delivery 1 of 2 -> 50 -> 5.0 | technical 0 of 2 -> 0.0 = 56.7, below LB1's 75.7
    lb = build()["categories"]["long_buildup"]["candidates"]
    assert [(c["symbol"], sig(c)["points"]) for c in lb] == [("LB1", 75.7), ("LB2", 56.7)]
    assert [c["symbol"] for c in build(per=1)["categories"]["long_buildup"]["candidates"]] == ["LB1"]


def test_ties_fall_back_to_the_absolute_oi_change_then_the_symbol():
    body = {"as_of": DAY, "rows": [row("AAA", "long_buildup", 2.0, 11.0), row("BBB", "long_buildup", 2.0, 11.0), row("CCC", "long_buildup", 2.0, 14.0)], "indices": []}
    feats = {s: [bull_features()] for s in ("AAA", "BBB", "CCC")}
    out = engine.assemble(body, engine.select_pools(body), feats, 5)
    # CCC's larger OI change scores higher on the OI input, so it leads; AAA and BBB tie exactly and fall back to the symbol
    assert [c["symbol"] for c in out["categories"]["long_buildup"]["candidates"]] == ["CCC", "AAA", "BBB"]


def test_short_covering_and_long_unwinding_score_a_weaker_oi_signal_than_a_fresh_build_up():
    a = engine._candidate("long_buildup", row("BU", "long_buildup", 2.0, 10.0), bull_features(), RULES)
    b = engine._candidate("short_covering", row("CV", "short_covering", 2.0, -10.0), bull_features(), RULES)
    assert inp(sig(a), "oi_signal")["score"] == 66.7 and inp(sig(b), "oi_signal")["score"] == 53.3      # 66.67 x 0.8
    assert inp(sig(a), "price_behavior")["score"] == inp(sig(b), "price_behavior")["score"]              # the factor applies to the OI input only


def test_the_weights_come_from_the_rules_and_changing_them_changes_the_order():
    rules = copy.deepcopy(RULES)
    rules["signal_weights"] = {"oi_signal": 100, "price_behavior": 0, "volume": 0, "options_confirmation": 0, "cash_delivery": 0, "technical": 0}
    rules["min_coverage"]["signal_strength"] = 0.0           # only the OI input is weighted; coverage of the other zero-weight inputs is moot
    out = build(rules=rules)
    assert [c["symbol"] for c in out["categories"]["long_buildup"]["candidates"]] == ["LB2", "LB1"]         # OI alone: LB2's 15% beats LB1's 12%


# ── the research status travels with the response ────────────────────────

def test_every_response_carries_the_research_status_and_nothing_claims_validation():
    out = build()
    r = out["research"]
    assert (r["status"], r["experiment_id"], r["data_window"], r["last_updated"]) == ("research_setting_not_validated", None, None, None)
    assert r["threshold_version"] == "fno-candidates-v2" == out["threshold_version"] and "validated" in r["statuses"]
    assert out["rules"]["research_status"] == "research_setting_not_validated"
    assert "no out-of-sample test" in out["disclosure"] and "most profitable" not in str(out).lower()
    assert any("No threshold or weight here has been validated" in g for g in out["gaps"])


# ── checks, entry viability and the state (descriptive, not scores) ───────

def test_a_bullish_candidate_that_meets_every_check_holds_six_of_six_and_a_bearish_one_mirrors_it():
    c = cat(build(), "long_buildup")["LB1"]
    assert set(states(c["checks"]).values()) == {True} and c["confirmations"] == {"holds": 6, "known": 6, "total": 6}
    assert "RSI 62.0" in next(x for x in c["checks"] if x["key"] == "momentum_aligned")["observed"]
    s = cat(build(), "short_buildup")["SB1"]
    assert s["direction"] == "bearish" and set(states(s["checks"]).values()) == {True}


def test_checks_fail_on_the_wrong_side_and_stay_unknown_when_an_input_is_missing():
    lb2 = cat(build(), "long_buildup")["LB2"]
    assert states(lb2["checks"]) == {"cash_confirms": False, "volume_elevated": False, "delivery_rising": True, "trend_aligned": False, "momentum_aligned": False, "entry_not_extended": True}
    lu1 = cat(build(), "long_unwinding")["LU1"]
    assert states(lu1["checks"])["momentum_aligned"] is None and lu1["confirmations"] == {"holds": 5, "known": 5, "total": 6}
    sc1 = cat(build(), "short_covering")["SC1"]
    mom = next(x for x in sc1["checks"] if x["key"] == "momentum_aligned")
    assert mom["state"] is False and "stretched" in mom["observed"]


def test_a_stock_that_has_already_moved_too_far_fails_the_entry_check_and_is_never_called_confirmed():
    r = row("ZZZ", "long_buildup", 2.5, 12.0)
    ext = engine._candidate("long_buildup", r, bull_features(return_5d_pct=12.0, atr_pct=2.0), RULES)
    chk = next(x for x in ext["checks"] if x["key"] == "entry_not_extended")
    assert chk["state"] is False and "limit 6.0%" in chk["observed"] and ext["entry_viable"] is False and ext["signal_state"] == "candidate"
    ok = engine._candidate("long_buildup", r, bull_features(return_5d_pct=5.0, atr_pct=2.0), RULES)
    assert ok["entry_viable"] is True and ok["signal_state"] == "confirmed"
    short = engine._candidate("short_buildup", row("YYY", "short_buildup", -2.5, 12.0), bear_features(return_5d_pct=-12.0, atr_pct=2.0), RULES)
    assert short["entry_viable"] is False
    assert sig(ext)["points"] == sig(ok)["points"]                    # entry viability is a separate field, not a signal input


def test_signal_state_candidate_confirmed_invalidated_unavailable():
    cands = {c["symbol"]: c for k in build()["categories"].values() for c in k["candidates"]}
    assert cands["LB1"]["signal_state"] == "confirmed" and cands["LB2"]["signal_state"] == "invalidated"
    weak = engine._candidate("long_buildup", row("MID", "long_buildup", 2.0, 9.0, vol_z20=0.1), bull_features(deliv_trend10=-1.0, rsi14=40.0, macd_hist=-0.2), RULES)
    assert weak["signal_state"] == "candidate"
    nofeat = engine._candidate("long_buildup", row("NOF", "long_buildup", 2.0, 9.0), None, RULES)
    assert nofeat["signal_state"] == "unavailable"


def test_missing_features_leave_the_candidate_unranked_with_unknown_inputs_never_zero():
    out = build(features={})
    k = out["categories"]["long_buildup"]
    assert k["candidates"] == [] and {u["symbol"] for u in k["unranked"]} == {"LB1", "LB2"}
    c = engine._candidate("long_buildup", BUILDUP["rows"][0], None, RULES)
    st = states(c["checks"])
    assert st["delivery_rising"] is None and st["trend_aligned"] is None and st["momentum_aligned"] is None and st["entry_not_extended"] is None
    assert inp(sig(c), "technical")["score"] is None and inp(sig(c), "volume")["score"] is None and c["ranked"] is False
    assert c["fundamental_context"]["rating"] == "unavailable" and c["delivery"] == {"avg20_pct": None, "trend10": None} and c["technical"]["rsi14"] is None
    assert any("could not be read" in g for g in out["gaps"])


# ── plan inputs and indices ──────────────────────────────────────────────

def test_plan_inputs_ask_for_bullish_after_long_side_readings_and_bearish_after_short_side_ones():
    want = {"long_buildup": "bullish", "short_covering": "bullish", "short_buildup": "bearish", "long_unwinding": "bearish"}
    out = build()
    for name, direction in want.items():
        for c in out["categories"][name]["candidates"]:
            assert c["plan_inputs"] == {"underlying": c["symbol"], "direction": direction, "horizon": "positional"}


def test_nifty_and_banknifty_are_listed_with_the_cash_check_and_no_stock_only_analysis():
    idx = {i["symbol"]: i for i in build()["indices"]}
    assert set(idx) == {"NIFTY", "BANKNIFTY"}
    n = idx["NIFTY"]
    assert (n["label"], n["direction"], n["cash_confirms"], n["risk_flags"]) == ("short_buildup", "bearish", True, ["expiry_week"])
    assert n["plan_inputs"] == {"underlying": "NIFTY", "direction": "bearish", "horizon": "positional"} and "no delivery or fundamentals" in n["note"]
    b = idx["BANKNIFTY"]
    assert b["direction"] is None and b["plan_inputs"] is None and "no direction is suggested" in b["note"]
    assert [i["symbol"] for i in build()["indices"]] == ["NIFTY", "BANKNIFTY"]


# ── the route ────────────────────────────────────────────────────────────

def client(monkeypatch, *, buildup=None, features=None, features_error=None, buildup_error=None, signed_in=True):
    calls: Dict[str, Any] = {"features": []}

    async def fake_daas(path, params, sym):
        if buildup_error:
            raise buildup_error
        return copy.deepcopy(buildup if buildup is not None else BUILDUP)

    async def fake_features(symbols, start=None, end=None, timeout=30.0):
        calls["features"].append((list(symbols), start, end))
        if features_error:
            raise features_error
        return copy.deepcopy(FEATURES if features is None else features)

    async def fake_user(request: Request):
        if not signed_in:
            raise HTTPException(status_code=401, detail="unauthenticated")
        return {"user_id": "u1"}

    monkeypatch.setattr(route, "_daas", fake_daas)
    monkeypatch.setattr(route.daas_client, "get_features_bulk", fake_features)
    monkeypatch.setattr(route, "get_current_user", fake_user)
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app), calls


def test_route_answers_the_four_categories_with_the_v2_shape_and_reads_features_once_for_the_pool(monkeypatch):
    c, calls = client(monkeypatch)
    r = c.get("/api/fno/scan/candidates")
    assert r.status_code == 200
    b = r.json()
    assert list(b["categories"]) == ["long_buildup", "short_buildup", "short_covering", "long_unwinding"]
    top = b["categories"]["long_buildup"]["candidates"][0]
    assert top["symbol"] == "LB1" and set(top["scores"]) == {"signal_strength", "tradeability", "strategy_quality"} and b["features_as_of"] == DAY
    assert b["research"]["status"] == "research_setting_not_validated" and b["threshold_version"] == "fno-candidates-v2"
    assert len(calls["features"]) == 1
    symbols, start, end = calls["features"][0]
    assert sorted(symbols) == ["LB1", "LB2", "LU1", "SB1", "SB2", "SC1"] and (start, end) == ("2026-10-08", DAY)


def test_route_degrades_when_the_features_cannot_be_read_candidates_are_unranked_and_it_says_so(monkeypatch):
    c, _ = client(monkeypatch, features_error=RuntimeError("daas down"))
    r = c.get("/api/fno/scan/candidates")
    assert r.status_code == 200
    k = r.json()["categories"]["long_buildup"]
    assert k["candidates"] == [] and len(k["unranked"]) == 2 and "below the 80% minimum" in k["unranked"][0]["reason"]
    assert any("could not be read" in g for g in r.json()["gaps"])


def test_route_is_502_when_the_build_up_scan_is_unreachable_or_has_no_rows_list(monkeypatch):
    c, _ = client(monkeypatch, buildup_error=HTTPException(status_code=502, detail="upstream_unavailable"))
    assert c.get("/api/fno/scan/candidates").status_code == 502
    c, _ = client(monkeypatch, buildup={"as_of": DAY})
    assert c.get("/api/fno/scan/candidates").status_code == 502


def test_route_needs_sign_in_and_validates_per_and_date(monkeypatch):
    c, _ = client(monkeypatch, signed_in=False)
    assert c.get("/api/fno/scan/candidates").status_code == 401
    c, _ = client(monkeypatch)
    for bad in ({"per": 0}, {"per": 11}, {"date": "nope"}):
        assert c.get("/api/fno/scan/candidates", params=bad).status_code == 422
    assert c.get("/api/fno/scan/candidates", params={"per": 2}).json()["per_category"] == 2


def test_an_empty_day_is_an_empty_board_not_an_error(monkeypatch):
    c, calls = client(monkeypatch, buildup={"as_of": DAY, "rows": [], "indices": []})
    r = c.get("/api/fno/scan/candidates")
    assert r.status_code == 200 and all(v["candidates"] == [] and v["unranked"] == [] for v in r.json()["categories"].values())
    assert calls["features"] == []
