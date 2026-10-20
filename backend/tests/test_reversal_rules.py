"""reversal-rules.v1 (services/positional_engine/reversal_rules.py): near-52-week-low reversal candidates.

No database and no network. Every series built here is MOCK — not real data. Cases follow
test_reports/reversal_engine_20261020.md (RV-1 .. RV-16).

Worked example (RV-1): 252 sessions whose lowest low is 90 and a last close of 103.5 give
  (103.5 / 90 - 1) x 100 = 15.0  -> exactly on the default threshold (in); 15.01 is out.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from services.positional_engine import reversal_rules as rr

DAY = date(2026, 10, 19)


def _bars(closes, vols=None, start=date(2025, 1, 1), spread=0.01):
    """MOCK bars: high/low are close +/- spread; one bar a day (calendar days are fine for pure-function tests)."""
    out = []
    for i, c in enumerate(closes):
        out.append({"d": (start + timedelta(days=i)).isoformat(), "o": c, "h": c * (1 + spread), "l": c * (1 - spread),
                    "c": c, "v": (vols[i] if vols else 100000)})
    return out


def _reversal_closes():
    """MOCK: a 270-session fall from 200 to 100, a new low at ~92, then a rising base: higher low, recovery to ~106."""
    fall = [200 - (100 * i / 269) for i in range(270)]
    dip = [100 - 8 * (i + 1) / 10 for i in range(10)]                    # 99.2 .. 92.0 (the 52w low area)
    base = [92 + 0.4 * (i + 1) for i in range(15)]                       # slow recovery to 98
    wobble = [98, 97.2, 96.5, 96.0, 96.2, 96.8, 97.5, 98.4, 99.5, 100.0, 100.6, 101.2, 101.8, 102.2, 102.6]
    return fall + dip + base + wobble


def _index_for(closes, drift=-0.001):
    return [1000 * (1 + drift) ** i for i in range(len(closes))]


def _vols_up(n):
    """MOCK: volume heavier on up days."""
    return [150000 if i % 2 == 0 else 80000 for i in range(n)]


def _row(sym="AAA", closes=None, **over):
    closes = closes or _reversal_closes()
    r = {"symbol": sym, "bars": _bars(closes, _vols_up(len(closes))), "index_closes": _index_for(closes),
         "traded_value_cr_20d": 25.0, "sector": "Information Technology", "eligible": True, "next_results_date": None,
         "sector_ctx": {"rs_20d": 2.0, "rs_change": 1.5, "breadth_above_50dma_pct": 55.0, "quadrant": "improving"},
         "fundamentals": {"revenue_growth_yoy_pct": 12.0, "pat_growth_yoy_pct": 15.0, "roe_pct": 18.0,
                          "operating_margin_pct": 18.0, "debt_to_equity": 0.3, "cfo_cr": 120.0,
                          "promoter_pledged_pct": 0.0, "pe_ttm": 20.0},
         "announcements": []}
    r.update(over)
    return r


# ── RV-1 distance ─────────────────────────────────────────────────────────────

def test_distance_formula_and_window():
    closes = [100.0] * 300
    bars = _bars(closes)
    for b in bars[:48]:                       # older than the 252-session window: must be ignored
        b["l"] = 10.0
    bars[100]["l"] = 90.0                     # lowest low INSIDE the window (bars 48..299)
    bars[-1]["c"] = 103.5
    d = rr.distance_from_low(bars)
    assert d["status"] == "ok" and d["low_52w"] == 90.0 and d["low_date"] == bars[100]["d"]
    assert d["distance_from_52w_low_pct"] == 15.0
    assert d["sessions_since_low"] == 299 - 100


def test_insufficient_history_is_not_a_distance():
    d = rr.distance_from_low(_bars([100.0] * 251))
    assert d == {"status": "insufficient_history", "sessions": 251, "needed": 252}
    ev = rr.evaluate([_row(closes=[100.0] * 251)], DAY)
    assert ev["rows"][0]["status"] == "excluded" and ev["rows"][0]["exclusion"] == "insufficient_history"


# ── RV-2 threshold ────────────────────────────────────────────────────────────

def _flat_at(dist_pct, n=300):
    closes = [100.0] * n
    bars = _bars(closes, spread=0.0)
    bars[150]["l"] = 100.0                    # low = 100
    bars[-1]["c"] = round(100.0 * (1 + dist_pct / 100), 4)
    bars[-1]["h"] = max(bars[-1]["h"], bars[-1]["c"])
    return bars


def test_threshold_boundary_is_configurable():
    ctrl = {"symbol": "T", "traded_value_cr_20d": 25.0, "eligible": True}
    inside = rr.evaluate([dict(ctrl, bars=_flat_at(15.0))], DAY)
    outside = rr.evaluate([dict(ctrl, bars=_flat_at(15.01))], DAY)
    assert inside["universe"]["listed"] == 1 and outside["universe"]["listed"] == 0
    assert outside["universe"]["exclusions"] == {"above_pool": 1}
    wide = rr.evaluate([dict(ctrl, bars=_flat_at(15.01))], DAY, near_pct=20.0)
    assert wide["universe"]["listed"] == 1 and wide["near_low_pct"] == 20.0
    narrow = rr.evaluate([dict(ctrl, bars=_flat_at(10.01))], DAY, near_pct=10.0)
    assert narrow["universe"]["listed"] == 0
    assert rr.NEAR_LOW["default_pct"] == 15.0 and rr.NEAR_LOW["sensitivity_pcts"] == [10.0, 15.0, 20.0]


# ── RV-3 not a signal ─────────────────────────────────────────────────────────

def test_near_low_alone_is_not_a_candidate():
    # a stock still sliding: new low on the last bar, below its EMA20, falling RSI, losing to the index
    closes = [200 - (100 * i / 299) for i in range(300)]
    r = _row(closes=closes, index_closes=_index_for(closes, drift=0.002))
    row = rr.evaluate([r], DAY)["rows"][0]
    assert row["distance"]["distance_from_52w_low_pct"] <= 15.0
    assert row["status"] == "near_low_no_evidence"
    assert row["evidence"]["core_true"] < rr.CANDIDATE["min_core_true"]


# ── RV-4 / RV-5 signals and the candidate gate ────────────────────────────────

def test_reversal_series_has_core_signals_and_is_a_candidate():
    row = rr.evaluate([_row()], DAY)["rows"][0]
    sig = row["signals"]
    assert {k: sig[k]["state"] for k in rr.CORE_SIGNALS} == {k: "true" for k in rr.CORE_SIGNALS}
    assert row["status"] in ("early_reversal", "trigger_ready", "confirmed")
    assert row["evidence"]["core_true"] == 6 and row["evidence"]["required_true"] == 3
    assert sig["higher_low"]["observed"]["recent_low"] > sig["higher_low"]["observed"]["prior_low"]


def test_missing_inputs_are_unknown_not_false():
    r = _row(index_closes=None, bars=_bars(_reversal_closes(), vols=None))
    for b in r["bars"]:
        b["v"] = None
    sig = rr.evaluate([r], DAY)["rows"][0]["signals"]
    assert sig["rs_vs_index"]["state"] == "unknown" and sig["volume_participation"]["state"] == "unknown"
    assert sig["higher_low"]["state"] == "true"


def test_two_true_and_three_unknown_is_not_a_candidate():
    sig = {k: {"state": "unknown"} for k in rr.CORE_SIGNALS}
    sig["higher_low"]["state"] = sig["low_not_new"]["state"] = "true"
    sig["rsi_recovery"]["state"] = "false"
    sig["ema20_reclaim"]["state"] = "unknown"
    lv = {"close": 100.0, "invalidation": 90.0, "resistance": 101.0, "reward_risk": 3.0}
    status, ev = rr.classify({"distance_from_52w_low_pct": 5.0}, 15.0, sig, lv, 2.0, 100.0)
    assert status == "near_low_no_evidence"
    assert (ev["core_true"], ev["core_false"], ev["core_unknown"]) == (2, 1, 3)
    sig["rs_vs_index"]["state"] = "true"
    assert rr.classify({"distance_from_52w_low_pct": 5.0}, 15.0, sig, lv, 2.0, 100.0)[0] != "near_low_no_evidence"


# ── RV-6 / RV-7 levels, status, reward/risk ───────────────────────────────────

def test_levels_trigger_invalidation_target():
    bars = _bars(_reversal_closes())
    d = rr.distance_from_low(bars)
    lv = rr.levels(bars, d)
    assert lv["hypothetical"] is True
    assert lv["resistance"] == round(max(b["h"] for b in bars[-21:-1]), 2)
    swing = min(b["l"] for b in bars[-11:-1])
    assert lv["swing_low"] == round(swing, 2)
    assert lv["invalidation"] == round(swing - 0.5 * lv["atr14"], 2)
    assert lv["target"] == round(max(b["h"] for b in bars[-60:]), 2)
    assert lv["invalidation"] < lv["close"] < lv["target"]
    entry = max(lv["close"], lv["resistance"])
    assert lv["reward_risk"] == round((lv["target"] - entry) / (entry - lv["invalidation"]), 2)


def test_close_below_invalidation_is_setup_invalidated():
    closes = _reversal_closes()
    closes[-1] = closes[-2] * 0.80            # gaps through the prior 10-session swing low
    row = rr.evaluate([_row(closes=closes)], DAY, near_pct=20.0)["rows"][0]
    assert row["status"] == "excluded" and row["exclusion"] == "setup_invalidated"


def test_low_reward_risk_blocks_trigger_ready():
    bars = _bars(_reversal_closes())
    d = rr.distance_from_low(bars)
    sig = rr.signals(bars, d, _index_for(_reversal_closes()))
    lv = dict(rr.levels(bars, d), reward_risk=1.0, resistance=bars[-1]["c"] * 1.01)
    status, _ = rr.classify(d, 15.0, sig, lv, 1.0, 100.0)
    assert status == "early_reversal"
    lv_ok = dict(lv, reward_risk=2.0)
    assert rr.classify(d, 15.0, sig, lv_ok, 1.0, 100.0)[0] == "trigger_ready"


def test_confirmed_needs_close_through_resistance_with_volume():
    bars = _bars(_reversal_closes())
    d = rr.distance_from_low(bars)
    sig = rr.signals(bars, d, _index_for(_reversal_closes()))
    lv = dict(rr.levels(bars, d), reward_risk=2.0, resistance=bars[-1]["c"] * 0.99)
    assert rr.classify(d, 15.0, sig, lv, 1.6, 100.0)[0] == "confirmed"
    assert rr.classify(d, 15.0, sig, lv, 1.2, 100.0)[0] != "confirmed"
    assert rr.classify(d, 15.0, sig, lv, None, 100.0)[0] != "confirmed"


# ── RV-8 gates ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("over,reason", [
    ({"traded_value_cr_20d": 9.99}, "illiquid"),
    ({"traded_value_cr_20d": None}, "no_traded_value"),
    ({"eligible": False, "exclusion": "etf"}, "scanner_etf"),
    ({"fundamentals": {"promoter_pledged_pct": 50.0}}, "high_pledge"),
    ({"fundamentals": {"interest_cover": 1.2}}, "financial_distress"),
    ({"fundamentals": {"debt_to_equity": 3.5, "pat_growth_yoy_pct": -10.0}}, "financial_distress"),
])
def test_gates_exclude_with_reason(over, reason):
    row = rr.evaluate([_row(**over)], DAY)["rows"][0]
    assert row["status"] == "excluded" and row["exclusion"] == reason


def test_pledge_warning_and_financial_leverage_exception():
    row = rr.evaluate([_row(fundamentals={"promoter_pledged_pct": 30.0})], DAY)["rows"][0]
    assert row["status"] != "excluded" and "elevated_pledge" in [w["code"] for w in row["warnings"]]
    bank = rr.evaluate([_row(sector="Banks", fundamentals={"debt_to_equity": 9.0, "pat_growth_yoy_pct": -5.0,
                                                           "roe_pct": 14.0, "revenue_growth_yoy_pct": 9.0,
                                                           "pat_growth_yoy_pct_": 1})], DAY)["rows"][0]
    assert bank["status"] != "excluded"


def test_results_due_is_a_warning_not_a_score():
    row = rr.evaluate([_row(next_results_date=(DAY + timedelta(days=3)).isoformat())], DAY)["rows"][0]
    assert any(w["code"] == "results_due" for w in row["warnings"])
    base = rr.evaluate([_row()], DAY)["rows"][0]
    assert row["score"]["total"] == base["score"]["total"]


# ── RV-9 / RV-10 / RV-11 score ────────────────────────────────────────────────

def test_weights_sum_to_100_and_total_is_weighted_sum():
    assert sum(rr.WEIGHTS.values()) == 100.0
    comps = {"sector": 80.0, "technical": 60.0, "momentum": 40.0, "fundamental": 70.0, "catalyst": 50.0,
             "valuation_risk": 30.0}
    s = rr.combine(comps)
    assert s["total"] == round(0.20 * 80 + 0.25 * 60 + 0.15 * 40 + 0.20 * 70 + 0.10 * 50 + 0.10 * 30, 1)
    assert s["coverage_pct"] == 100.0 and s["unknown_components"] == []


def test_unknown_component_is_left_out_and_total_renormalised():
    comps = {"sector": None, "technical": 60.0, "momentum": 40.0, "fundamental": None, "catalyst": None,
             "valuation_risk": 30.0}
    s = rr.combine(comps)
    assert s["total"] == round((25 * 60 + 15 * 40 + 10 * 30) / 50, 1)
    assert s["coverage_pct"] == 50.0
    assert s["unknown_components"] == ["catalyst", "fundamental", "sector"]
    assert rr.combine({k: None for k in rr.WEIGHTS})["total"] is None


def test_real_row_with_no_catalyst_and_no_sector_reports_unknown_not_neutral():
    row = rr.evaluate([_row(sector_ctx=None, announcements=[], fundamentals=None)], DAY)["rows"][0]
    assert row["components"]["sector"]["score"] is None and row["components"]["sector"]["known"] is False
    assert row["components"]["catalyst"]["score"] is None
    assert row["components"]["fundamental"]["score"] is None
    assert {"sector", "catalyst", "fundamental"} <= set(row["score"]["unknown_components"])
    assert any("fundamental" in u for u in row["explanation"]["uncertain"])
    assert any(w["code"] == "fundamentals_unverified" for w in row["warnings"])


def test_low_coverage_caps_status_at_watchlist():
    s = rr.classify({"distance_from_52w_low_pct": 5.0}, 15.0,
                    {k: {"state": "true"} for k in list(rr.CORE_SIGNALS) + ["ema20_reclaim"]},
                    {"close": 100.0, "invalidation": 90.0, "resistance": 101.0, "reward_risk": 3.0}, 2.0, 40.0)
    assert s[0] == "watchlist"


def test_gate_beats_a_high_score():
    row = rr.evaluate([_row(fundamentals={"promoter_pledged_pct": 60.0, "revenue_growth_yoy_pct": 40.0,
                                          "pat_growth_yoy_pct": 40.0, "roe_pct": 30.0})], DAY)["rows"][0]
    assert row["status"] == "excluded" and row["exclusion"] == "high_pledge" and "score" not in row


def test_weak_fundamentals_flag_speculative():
    weak = {"revenue_growth_yoy_pct": -10.0, "pat_growth_yoy_pct": -20.0, "roe_pct": 4.0, "operating_margin_pct": 3.0,
            "debt_to_equity": 2.0, "cfo_cr": -5.0, "promoter_pledged_pct": 20.0}
    row = rr.evaluate([_row(fundamentals=weak)], DAY)["rows"][0]
    assert row["status"] in ("early_reversal", "trigger_ready", "confirmed")
    assert row["components"]["fundamental"]["score"] < 40
    assert any(w["code"] == "speculative" for w in row["warnings"])


# ── RV-12 sector-aware fundamentals, RV-13 sector, RV-14 catalyst ─────────────

def test_financials_do_not_score_leverage():
    f = {"revenue_growth_yoy_pct": 10.0, "pat_growth_yoy_pct": 10.0, "roe_pct": 15.0, "debt_to_equity": 9.0,
         "promoter_pledged_pct": 0.0, "operating_margin_pct": 1.0, "cfo_cr": -50.0}
    bank, d_bank = rr.fundamental_component(f, "Financial Services")
    plain, d_plain = rr.fundamental_component(f, "Capital Goods")
    assert "leverage" not in d_bank["known"] and "leverage" in d_plain["known"]
    assert bank > plain


def test_fundamentals_with_too_few_figures_are_unknown():
    s, d = rr.fundamental_component({"roe_pct": 15.0}, "Capital Goods")
    assert s is None and "reason" in d


def test_sector_component_unknown_without_context_and_scores_with_it():
    assert rr.sector_component(None)[0] is None
    assert rr.sector_component({"quadrant": "lagging"})[0] is None
    good = rr.sector_component({"rs_20d": 5.0, "rs_change": 3.0, "breadth_above_50dma_pct": 70.0})[0]
    bad = rr.sector_component({"rs_20d": -5.0, "rs_change": -3.0, "breadth_above_50dma_pct": 20.0})[0]
    assert good == 100.0 and bad == 0.0


def test_catalyst_is_point_in_time():
    ann = [{"filed_at": "2026-10-10T09:00:00+00:00", "impact_score": "high", "sentiment": "positive", "subject": "order"},
           {"filed_at": "2026-10-20T09:00:00+00:00", "impact_score": "high", "sentiment": "negative", "subject": "after as_of"},
           {"filed_at": "2026-08-01T09:00:00+00:00", "impact_score": "high", "sentiment": "negative", "subject": "too old"},
           {"filed_at": "2026-10-12T09:00:00+00:00", "impact_score": "low", "sentiment": "negative", "subject": "low impact is ignored"}]
    s, d = rr.catalyst_component(ann, DAY)
    assert s == 100.0 and [i["subject"] for i in d["items"]] == ["order"]
    assert rr.catalyst_component([], DAY)[0] is None                       # no news = unknown, not neutral
    assert rr.catalyst_component(None, DAY)[0] is None


# ── RV-15 explanation, RV-16 purity ───────────────────────────────────────────

def test_every_row_explains_itself():
    row = rr.evaluate([_row(sector_ctx=None)], DAY)["rows"][0]
    ex = row["explanation"]
    assert set(ex) == {"why_this_stock", "why_now", "confirms", "uncertain", "invalidates", "entry_trigger"}
    assert "not a signal" in ex["why_this_stock"] and ex["confirms"] and ex["uncertain"]
    assert ex["invalidates"].startswith("close below")


def test_evaluate_is_pure_and_sorted():
    rows = [_row("AAA"), _row("BBB", fundamentals={"revenue_growth_yoy_pct": 30.0, "pat_growth_yoy_pct": 40.0,
                                                   "roe_pct": 25.0, "operating_margin_pct": 22.0,
                                                   "debt_to_equity": 0.1, "cfo_cr": 10.0, "promoter_pledged_pct": 0.0})]
    a = rr.evaluate(rows, DAY)
    b = rr.evaluate(rows, DAY)
    assert a == b
    totals = [r["score"]["total"] for r in a["rows"]]
    assert totals == sorted(totals, reverse=True) and a["rows"][0]["symbol"] == "BBB"
    assert a["rules_version"] == rr.RULES_VERSION


def test_indicators_match_known_values():
    e = rr.ema([1, 2, 3, 4, 5], 3)
    assert e[:2] == [None, None] and e[2] == 2.0 and e[3] == 3.0 and e[4] == 4.0
    r = rr.rsi([float(i) for i in range(1, 30)])
    assert r[-1] == 100.0 and r[0] is None
