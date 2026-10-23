"""The Stage A backtest of the F&O ranking and thresholds (services/fno_backtest).

MOCK — not real data: invented sessions, scans, features and prices with PLANTED effects, so the selection logic has something real to find and
something to reject. No network and no Mongo. A real run on the staging data platform is a separate step (scripts/run_fno_backtest.py).
"""
from __future__ import annotations

import copy
from datetime import date, timedelta
from typing import Any, Dict, List

from services.fno_backtest import outcomes, stats, study
from services.fno_backtest.outcomes import COSTS


def days(n: int, start: date = date(2026, 1, 5)) -> List[str]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def rnd(a: int, b: int) -> float:
    """A deterministic pseudo-random number in [0, 1)."""
    return ((a * 1103515245 + b * 12345 + 6789) % 100003) / 100003.0


# ── outcomes ─────────────────────────────────────────────────────────────

S = days(8)
PX = {"AAA": {S[1]: (100.0, 103.0), S[2]: (103.0, 104.0), S[3]: (104.0, 110.0), S[5]: (110.0, 99.0)}}


def test_forward_return_enters_at_the_next_open_and_exits_at_the_close_h_sessions_later():
    assert round(outcomes.forward_return(PX, "AAA", S, 0, 1), 4) == 3.0           # open S1 100 -> close S1 103
    assert round(outcomes.forward_return(PX, "AAA", S, 0, 3), 4) == 10.0          # open S1 100 -> close S3 110
    assert round(outcomes.forward_return(PX, "aaa", S, 0, 3), 4) == 10.0          # the symbol is case-insensitive


def test_a_missing_price_or_a_window_past_the_data_is_none_never_zero():
    assert outcomes.forward_return(PX, "AAA", S, 0, 4) is None                    # no price on S4
    assert outcomes.forward_return(PX, "AAA", S, 5, 3) is None                    # the window runs past the last session
    assert outcomes.forward_return(PX, "AAA", S, 7, 1) is None
    assert outcomes.forward_return(PX, "ZZZ", S, 0, 1) is None                    # unknown symbol
    assert outcomes.forward_return(PX, "AAA", S, 0, 0) is None


def test_price_index_drops_rows_with_missing_or_non_positive_prices():
    idx = outcomes.price_index({"a": [{"as_of_date": "2026-01-05", "adj_open": 10, "adj_close": 11}, {"as_of_date": "2026-01-06", "adj_open": None, "adj_close": 12},
                                      {"as_of_date": "2026-01-07", "adj_open": 0, "adj_close": 5}]})
    assert idx == {"A": {"2026-01-05": (10.0, 11.0)}}


def test_point_in_time_row_is_the_newest_row_on_or_before_the_day_never_a_later_one():
    rows = [{"as_of_date": "2026-01-06", "v": 1}, {"as_of_date": "2026-01-08", "v": 2}, {"as_of_date": "2026-01-12", "v": 3}]
    assert outcomes.point_in_time_row(rows, "2026-01-09")["v"] == 2
    assert outcomes.point_in_time_row(rows, "2026-01-08")["v"] == 2
    assert outcomes.point_in_time_row(rows, "2026-01-05") is None
    assert outcomes.point_in_time_row(rows, "2026-02-01")["v"] == 3


def test_splits_are_60_20_20_in_time_order_and_a_forward_window_never_crosses_a_boundary():
    b = outcomes.split_bounds(0, 99)
    assert b == {"discovery": (0, 60), "validation": (60, 80), "test": (80, 100)}
    last = 104                                                                    # the data runs 5 sessions past the last signal session
    assert outcomes.split_of(50, 5, b, last) == "discovery" and outcomes.split_of(54, 5, b, last) == "discovery"      # exits at session 59, the last discovery session
    assert outcomes.split_of(55, 5, b, last) is None                              # exits at session 60's close: that session belongs to validation
    assert outcomes.split_of(60, 5, b, last) == "validation" and outcomes.split_of(74, 5, b, last) == "validation" and outcomes.split_of(75, 5, b, last) is None
    assert outcomes.split_of(95, 5, b, last) == "test" and outcomes.split_of(99, 10, b, last) is None                # the test window may run to the end of the data only


# ── statistics ───────────────────────────────────────────────────────────

def test_newey_west_with_no_lag_is_the_plain_standard_error_and_a_lag_widens_it_for_autocorrelated_data():
    x = [1.0, 2.0, 1.5, 2.5, 1.0, 3.0, 2.0, 2.5, 1.5, 2.0]
    m = sum(x) / len(x)
    plain = (sum((v - m) ** 2 for v in x) / len(x) / len(x)) ** 0.5
    assert abs(stats.nw_se(x, 0) - plain) < 1e-12
    trend = [float(i) for i in range(30)]                                          # strongly autocorrelated
    assert stats.nw_se(trend, 5) > stats.nw_se(trend, 0)
    assert stats.nw_se([1.0, 2.0, 3.0], 1) is None and stats.summarize([1.0, 2.0], 0)["t"] is None   # too short for a standard error


def test_spearman_worked_ties_and_the_cases_with_no_answer():
    assert round(stats.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 6) == 1.0
    assert round(stats.spearman([1, 2, 3, 4], [40, 30, 20, 10]), 6) == -1.0
    # ties get average ranks: [1,1,2,3] -> 1.5,1.5,3,4 ; [1,2,3,4] -> 1,2,3,4 : r = 0.948683...
    assert round(stats.spearman([1, 1, 2, 3], [1, 2, 3, 4]), 4) == 0.9487
    assert stats.spearman([1, 2, 3], [1, 2, 3]) is None                           # fewer than 4 pairs
    assert stats.spearman([5, 5, 5, 5], [1, 2, 3, 4]) is None                     # no spread on one side


# ── a synthetic world ────────────────────────────────────────────────────

N_SYMS = 40                    # ten per category per session, so a top five differs from the whole pool and a rank correlation has enough pairs


def world(n_sessions: int, planted: bool = True, seed: int = 0) -> Dict[str, Any]:
    """Sessions, a scan per session, feature rows and adjusted prices. With `planted`, stocks whose scan row shows a big OI change AND a big price move
    drift in the direction of their label over the next sessions, and the engine's Signal Strength points rise with exactly that."""
    sess = days(n_sessions + 25)
    syms = [f"S{k:02d}" for k in range(N_SYMS)]
    labels = ["long_buildup", "short_buildup", "short_covering", "long_unwinding"]
    scans: Dict[str, Dict[str, Any]] = {}
    drift: Dict[str, Dict[str, float]] = {s: {} for s in syms}
    for i, d in enumerate(sess[:n_sessions + 24]):
        rows = []
        for k, s in enumerate(syms):
            lab = labels[(i + k) % 4]
            strong = rnd(i + seed, k) > 0.5
            price = (2.5 if strong else 0.8) * (1 if lab in ("long_buildup", "short_covering") else -1)
            oi = (12.0 if strong else 4.0) * (1 if lab in ("long_buildup", "short_buildup") else -1)
            rows.append({"symbol": s, "label": lab, "price_chg_pct": price, "oi_chg_pct": oi, "oi": 1_000_000, "close": 100.0, "near_expiry": "2026-12-31", "days_to_expiry": 20,
                         "fut_turnover_cr": 500.0, "cash_close": 99.0, "cash_chg_pct": price, "cash_confirmation": "confirms", "cash_volume": 4_000_000 if strong else 2_500_000,
                         "vol_z20": 2.0, "fno_eligible": True, "risk_flags": [], "sector": "IT"})
            if planted and strong:
                drift[s][d] = 1.0 if lab in ("long_buildup", "short_covering") else -1.0
        scans[d] = {"as_of": d, "source": "synthetic", "universe": N_SYMS, "rows": rows, "indices": []}
    feats: Dict[str, List[Dict[str, Any]]] = {}
    adj: Dict[str, List[Dict[str, Any]]] = {}
    for k, s in enumerate(syms):
        feats[s], adj[s] = [], []
        price = 100.0
        for i, d in enumerate(sess):
            prev_signal = drift[s].get(sess[i - 1], 0.0) if i > 0 else 0.0
            ret = 0.9 * prev_signal + (rnd(i * 7 + seed, k + 99) - 0.5) * 1.0       # +-0.5% noise
            o = price
            price = max(1.0, price * (1.0 + ret / 100.0))
            adj.setdefault(s, []).append({"symbol": s, "as_of_date": d, "adj_open": round(o, 4), "adj_close": round(price, 4)})
            feats[s].append({"as_of_date": d, "close": price, "sma20": price * 0.95, "sma50": price * 0.9, "rsi14": 60.0, "macd_hist": 0.4, "deliv_trend10": 1.0,
                             "avg_volume_20": 2_000_000, "atr_pct": 2.0, "return_5d_pct": 1.0, "vol_z20": 1.5})
    return {"sessions": sess, "scans": scans, "features": feats, "adjusted": adj}


# ── point in time ────────────────────────────────────────────────────────

def test_a_session_is_scored_from_what_was_known_that_day_future_data_cannot_change_it():
    w = world(40)
    px = outcomes.price_index(w["adjusted"])
    base = study.build_panel(w["sessions"], w["scans"], w["features"], px)
    # append, for every symbol, feature rows dated AFTER each session with wildly different values, and a later scan
    poisoned = copy.deepcopy(w["features"])
    for s, rows in poisoned.items():
        for r in rows[20:]:
            r.update({"rsi14": 99.0, "macd_hist": -9.0, "avg_volume_20": 1.0, "deliv_trend10": -5.0, "close": 1.0, "sma20": 1e6, "sma50": 1e6})
    again = study.build_panel(w["sessions"], w["scans"], poisoned, px)
    early = [sd for sd in base if sd["i"] < 20]
    early2 = [sd for sd in again if sd["i"] < 20]
    assert early and [sd["cands"] for sd in early] == [sd["cands"] for sd in early2]      # sessions before the change are identical
    late = [sd for sd in again if sd["i"] >= 20][0]
    assert any(c["inputs"].get("technical") != 100.0 for c in late["cands"])               # while the changed sessions do see their own data


def test_the_panel_never_scores_a_candidate_from_a_later_session_than_its_own():
    w = world(30)
    px = outcomes.price_index(w["adjusted"])
    panel = study.build_panel(w["sessions"], w["scans"], w["features"], px)
    assert panel and all(sd["date"] == w["sessions"][sd["i"]] for sd in panel)
    assert all(sd["i"] <= len(w["sessions"]) - 2 for sd in panel)


# ── the ranking study ────────────────────────────────────────────────────

def run(n: int, **kw):
    return study.run_backtest(world(n, **kw), code_version="test", generated_at="2026-10-23T00:00:00Z")


def test_with_a_planted_effect_the_production_ranking_beats_a_random_pick_and_costs_are_subtracted():
    rep = run(130)
    cell = rep["ranking_study"]["long_buildup"]["1"]["test"]
    prod, pool = cell["variants"]["production"], cell["variants"]["pool_average"]
    assert prod["n_sessions"] >= 15 and prod["n_trades"] > 0
    assert prod["mean_gross_pct"] > pool["mean_gross_pct"]                         # the strongest signals drift; the weak ones do not
    assert abs((prod["mean_gross_pct"] - prod["mean_net_pct_base"]) - COSTS["round_trip_pct_base"]) < 1e-3
    assert abs((prod["mean_gross_pct"] - prod["mean_net_pct_stress"]) - COSTS["round_trip_pct_stress"]) < 1e-3
    assert cell["ic_signal_strength"]["mean"] > 0                                  # points rank-correlate with the outcome


def test_without_a_planted_effect_the_ranking_shows_no_edge():
    rep = run(130, planted=False)
    c = rep["ranking_study"]["long_buildup"]["1"]["test"]
    assert abs(c["variants"]["production"]["mean_gross_pct"] - c["variants"]["pool_average"]["mean_gross_pct"]) < 0.3
    assert abs(c["ic_signal_strength"]["mean"]) < 0.25


def test_the_pool_average_is_the_mean_of_all_ranked_pool_outcomes():
    w = world(60)
    px = outcomes.price_index(w["adjusted"])
    panel = study.build_panel(w["sessions"], w["scans"], w["features"], px)
    sd = next(x for x in panel if x["i"] == 10)
    vals = [(x, x["ret"][1]) for x in sd["cands"] if x["cat"] == "long_buildup" and x["ranked"] and x["ret"].get(1) is not None]
    picks = study._variant_picks(vals)
    assert len(picks["pool_average"]) == len(vals) and len(picks["production"]) == min(5, len(vals))
    assert [t[0]["sym"] for t in picks["production"]] == [t[0]["sym"] for t in sorted(vals, key=lambda t: (-t[0]["points"], -t[0]["oi"], t[0]["sym"]))[:5]]


# ── the threshold study ──────────────────────────────────────────────────

def planted_panel(n: int = 150) -> List[Dict[str, Any]]:
    """Rows of one category over n sessions: a row with price >= 1.0 and OI >= 5 returns +2% on average, every other row 0, plus noise."""
    panel = []
    for i in range(n):
        thr = []
        for k in range(10):
            price = [0.2, 0.5, 0.8, 1.2, 1.8][k % 5]
            oi = [2.0, 4.0, 6.0, 9.0, 14.0][(k + i) % 5]
            good = price >= 1.0 and oi >= 5.0
            noise = (rnd(i, k) - 0.5) * 2.0
            thr.append({"cat": "long_buildup", "price": price, "oi": oi, "rvol": 1.0 + rnd(k, i) * 1.5,
                        "ret": {h: (2.0 if good else 0.0) + noise for h in outcomes.HORIZONS}})
        panel.append({"i": i, "date": f"d{i}", "universe": {h: 0.0 for h in outcomes.HORIZONS}, "cands": [], "thr": thr})
    return panel


def test_the_threshold_study_selects_on_discovery_only_freezes_a_small_set_and_finds_a_planted_effect_that_survives_the_test_split():
    panel = planted_panel()
    bounds = outcomes.split_bounds(0, 149)
    out = study.threshold_study(panel, bounds, 175, 0.15, 0.30)
    cat = out["categories"]["long_buildup"]
    assert len(cat["frozen"]) == study.TOP_K and out["grid"]["configurations"] == 256
    top = cat["frozen"][0]
    assert top["config"]["price_pct"] >= 1.0 - 1e-9 or top["config"]["oi_pct"] >= 5.0   # inside the planted region
    assert top["positive_net_in_validation_and_test"] is True
    assert top["results"]["5"]["test"]["n_sessions"] >= study.MIN_TEST_SESSIONS
    assert cat["baselines"]["no_threshold"]["results"]["5"]["test"]["mean"] < top["results"]["5"]["test"]["mean"]
    assert set(cat["baselines"]) == {"no_threshold", "production_floors"}


def test_a_category_with_no_signals_has_nothing_eligible_and_nothing_frozen():
    out = study.threshold_study(planted_panel(), outcomes.split_bounds(0, 149), 175, 0.15, 0.30)
    empty = out["categories"]["short_buildup"]
    assert empty["eligible_in_discovery"] == 0 and empty["frozen"] == [] and empty["discovery_winners_t_above_1_645"] == 0


def test_the_chance_check_counts_discovery_winners_against_the_5_percent_expectation():
    noise = planted_panel()
    for sd in noise:
        for x in sd["thr"]:
            x["ret"] = {h: (rnd(sd["i"], int(x["oi"] * 10 + x["price"] * 100)) - 0.5) * 2.0 for h in outcomes.HORIZONS}      # no effect anywhere
    cat = study.threshold_study(noise, outcomes.split_bounds(0, 149), 175, 0.15, 0.30)["categories"]["long_buildup"]
    assert cat["eligible_in_discovery"] > 0 and cat["expected_by_chance_at_5pct"] == round(0.05 * cat["eligible_in_discovery"], 1)
    assert all(f["positive_net_in_validation_and_test"] in (True, False) for f in cat["frozen"])
    # with no effect and a 0.15% cost, a frozen winner must not look like a survivor on both later splits for most of them
    assert sum(1 for f in cat["frozen"] if f["positive_net_in_validation_and_test"]) <= 2


# ── the report ───────────────────────────────────────────────────────────

def test_the_report_is_reproducible_and_changes_when_an_input_changes():
    a, b = run(130), run(130)
    assert a["experiment_id"] == b["experiment_id"] and a["report_hash"] == b["report_hash"]
    w = world(130)
    w["adjusted"]["S00"][40]["adj_close"] += 0.01
    c = study.run_backtest(w, code_version="test", generated_at="2026-10-23T00:00:00Z")
    assert c["experiment_id"] != a["experiment_id"] and c["report_hash"] != a["report_hash"]
    assert a["data_fingerprint"]["prices"] != c["data_fingerprint"]["prices"] and a["data_fingerprint"]["scans"] == c["data_fingerprint"]["scans"]


def test_every_variant_category_horizon_and_split_is_counted_and_the_report_is_never_validated():
    r = run(130)
    t = r["tested_configurations"]
    assert t["ranking_cells"] == 4 * 4 * 5 * 3 == 240 and t["threshold_configurations"] == 256 and t["threshold_cells_discovery"] == 256 * 4 * 5
    assert r["validated"] is False and r["status"] in ("research_result", "insufficient_evidence") and r["stage"].startswith("A")
    assert any("Stage A only" in x for x in r["limitations"]) and r["assumptions"]["costs"]["version"] == "research-cost-v0"
    assert r["data_window"]["first_signal_session"] == r["data_window"]["split_sessions"]["discovery"][0]


def test_too_few_test_sessions_is_insufficient_evidence_and_enough_is_a_research_result_never_validated():
    small, big = run(30), run(130)
    assert small["status"] == "insufficient_evidence" and big["status"] == "research_result"
    assert small["validated"] is False and big["validated"] is False


def test_no_evaluable_session_is_insufficient_evidence_not_an_error():
    r = study.run_backtest({"sessions": days(5), "scans": {}, "features": {}, "adjusted": {}})
    assert r["status"] == "insufficient_evidence" and r["validated"] is False and r["experiment_id"] is None
