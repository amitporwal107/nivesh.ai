"""Stage A backtest: the candidate ranking and its thresholds, session by session, point in time.

For each session D the production engine (services/fno_candidates v2) runs on what was knowable at the close of D: the build-up scan dated D and,
per symbol, the newest feature row dated on or before D. The outcome is a long entered at the next session's open and exited at the close of D+h
(split/bonus-adjusted cash prices as a proxy for the near-month future), direction-adjusted, less an ASSUMED research cost.

Two studies, both counted:
- RANKING: does the production ranking (Signal Strength points) pick better than its alternatives (OI-only, price-only, the pool average = a random pick),
  and how does each score input rank-correlate with the outcome?
- THRESHOLDS: the PRD's grid (price move x OI change x relative volume). To avoid picking the best of 256 by luck: choose on the DISCOVERY split only, freeze a
  small set, then evaluate it on validation and the untouched test split, and compare the number of discovery winners with what chance alone would give.

Nothing here can be `validated`: it is Stage A. The strongest status is `research_result`."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from services.fno_candidates import engine
from services.fno_candidates.rules import CATEGORIES, DIRECTION, RULES

from . import stats
from .outcomes import COSTS, HORIZONS, forward_return, point_in_time_row, price_index, split_bounds, split_of

STUDY_VERSION = "fno-backtest-stage-a-v1"
PRIMARY_H = 5
PRICE_GRID = (0.10, 0.20, 0.30, 0.50, 0.75, 1.00, 1.50, 2.00)
OI_GRID = (1, 2, 3, 5, 8, 10, 15, 20)
RVOL_GRID = (1.0, 1.2, 1.5, 2.0)
PRODUCTION_FLOORS = (0.5, 3.0, None)        # the engine's current research settings (no relative-volume floor)
NO_THRESHOLD = (0.0, 0.0, None)
MIN_SIGNALS = 100                           # a configuration needs this many signals and sessions in discovery to be considered
MIN_SESSIONS = 30
TOP_K = 5
MIN_TEST_SESSIONS = 20
TOP_N = 5                                   # the candidates shown per category
SPLITS = ("discovery", "validation", "test")
Cfg = Tuple[float, float, Optional[float]]


def _sign(category: str) -> int:
    return 1 if DIRECTION[category] == "bullish" else -1


def _lag(h: int) -> int:
    return max(h - 1, 0)


def _rvol(row: Dict[str, Any], feat: Optional[Dict[str, Any]]) -> Optional[float]:
    cv, avg = engine.num(row.get("cash_volume")), engine.num((feat or {}).get("avg_volume_20"))
    return None if cv is None or avg is None or avg <= 0 else cv / avg


# ── the panel: what was knowable on each session, and what happened next ──

def build_panel(sessions: Sequence[str], scans: Dict[str, Dict[str, Any]], features: Dict[str, List[Dict[str, Any]]],
                px: Dict[str, Dict[str, Tuple[float, float]]], rules: Dict[str, Any] = RULES) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for i in range(0, len(sessions) - 1):
        day = sessions[i]
        body = scans.get(day)
        if not body or not isinstance(body.get("rows"), list):
            continue
        rows = [r for r in body["rows"] if isinstance(r, dict) and r.get("symbol")]
        pit: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            sym = str(r["symbol"]).upper()
            fr = point_in_time_row(features.get(sym, []), day)
            if fr is not None:
                pit[sym] = fr
        rets = {str(r["symbol"]).upper(): {h: forward_return(px, str(r["symbol"]), sessions, i, h) for h in HORIZONS} for r in rows}
        universe = {}
        for h in HORIZONS:
            vals = [v[h] for v in rets.values() if v[h] is not None]
            universe[h] = sum(vals) / len(vals) if vals else None
        pools = engine.select_pools(body, rules)
        built = engine.build_all(body, pools, {s: [f] for s, f in pit.items()}, rules)
        cands = []
        for c in CATEGORIES:
            for x in built[c]:
                sg = x["scores"]["signal_strength"]
                cands.append({"cat": c, "sym": x["symbol"], "ranked": x["ranked"], "points": sg["points"], "coverage": sg["coverage"],
                              "oi": abs(x["oi_chg_pct"] or 0.0), "price": abs(x["price_chg_pct"] or 0.0),
                              "inputs": {k["key"]: k["score"] for k in sg["inputs"]}, "ret": rets.get(x["symbol"], {})})
        thr = []
        for r in rows:
            label = r.get("label")
            p, o = engine.num(r.get("price_chg_pct")), engine.num(r.get("oi_chg_pct"))
            if label in CATEGORIES and p is not None and o is not None:
                sym = str(r["symbol"]).upper()
                thr.append({"cat": label, "price": abs(p), "oi": abs(o), "rvol": _rvol(r, pit.get(sym)), "ret": rets[sym]})
        out.append({"i": i, "date": day, "universe": universe, "cands": cands, "thr": thr})
    return out


# ── the ranking study ────────────────────────────────────────────────────

def _variant_picks(vals: List[Tuple[Dict[str, Any], float]]) -> Dict[str, List[Tuple[Dict[str, Any], float]]]:
    """The same ranked pool, four ways: the production ranking, OI only, price only, and the whole pool (the expectation of a random pick)."""
    return {
        "production": sorted(vals, key=lambda t: (-t[0]["points"], -t[0]["oi"], t[0]["sym"]))[:TOP_N],
        "oi_only": sorted(vals, key=lambda t: (-t[0]["oi"], t[0]["sym"]))[:TOP_N],
        "price_only": sorted(vals, key=lambda t: (-t[0]["price"], t[0]["sym"]))[:TOP_N],
        "pool_average": list(vals),
    }


VARIANTS = ("production", "oi_only", "price_only", "pool_average")


def ranking_study(panel: List[Dict[str, Any]], bounds: Dict[str, Tuple[int, int]], last_idx: int, input_keys: Sequence[str],
                  cost_base: float, cost_stress: float) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for c in CATEGORIES:
        sign = _sign(c)
        out[c] = {}
        for h in HORIZONS:
            out[c][str(h)] = {}
            for split in SPLITS:
                acc = {v: {"gross": [], "net": [], "trades": [], "excess": []} for v in VARIANTS}
                ic_pts: List[float] = []
                ic_in: Dict[str, List[float]] = {k: [] for k in input_keys}
                for sd in panel:
                    if split_of(sd["i"], h, bounds, last_idx) != split:
                        continue
                    vals = [(x, x["ret"].get(h)) for x in sd["cands"] if x["cat"] == c and x["ranked"] and x["ret"].get(h) is not None]
                    if not vals:
                        continue
                    u = sd["universe"].get(h)
                    for name, picks in _variant_picks(vals).items():
                        g = [sign * r for _, r in picks]
                        mg = sum(g) / len(g)
                        a = acc[name]
                        a["gross"].append(mg)
                        a["net"].append(mg - cost_base)
                        a["trades"].extend(x - cost_base for x in g)
                        if u is not None:
                            a["excess"].append(sum(sign * (r - u) for _, r in picks) / len(picks))
                    ic = stats.spearman([t[0]["points"] for t in vals], [sign * t[1] for t in vals])
                    if ic is not None:
                        ic_pts.append(ic)
                    for k in input_keys:
                        pairs = [(t[0]["inputs"].get(k), sign * t[1]) for t in vals if t[0]["inputs"].get(k) is not None]
                        icx = stats.spearman([p[0] for p in pairs], [p[1] for p in pairs]) if pairs else None
                        if icx is not None:
                            ic_in[k].append(icx)
                res: Dict[str, Any] = {"variants": {}}
                for name, a in acc.items():
                    ns = len(a["net"])
                    res["variants"][name] = {
                        "n_sessions": ns, "n_trades": len(a["trades"]),
                        "mean_gross_pct": None if not ns else round(sum(a["gross"]) / ns, 4),
                        "mean_net_pct_base": None if not ns else round(sum(a["net"]) / ns, 4),
                        "mean_net_pct_stress": None if not ns else round(sum(a["gross"]) / ns - cost_stress, 4),
                        "net_base": stats.summarize(a["net"], _lag(h)),
                        "hit_rate_net_base": None if not a["trades"] else round(sum(1 for x in a["trades"] if x > 0) / len(a["trades"]), 3),
                        "mean_excess_vs_universe_pct": None if not a["excess"] else round(sum(a["excess"]) / len(a["excess"]), 4),
                    }
                res["ic_signal_strength"] = stats.summarize(ic_pts, _lag(h))
                res["ic_inputs"] = {k: stats.summarize(v, _lag(h)) for k, v in ic_in.items()}
                out[c][str(h)][split] = res
    return out


# ── the threshold study ──────────────────────────────────────────────────

def _fired(rows: List[Dict[str, Any]], cfg: Cfg) -> List[Dict[str, Any]]:
    p, o, r = cfg
    return [x for x in rows if x["price"] >= p and x["oi"] >= o and (r is None or (x["rvol"] is not None and x["rvol"] >= r))]


def _eval(fired: List[Dict[str, Any]], sign: int, h: int, split: str, bounds, last_idx: int, cost: float) -> Dict[str, Any]:
    per: Dict[int, List[float]] = {}
    memo: Dict[int, Optional[str]] = {}
    for x in fired:
        r = x["ret"].get(h)
        if r is None:
            continue
        i = x["_i"]
        if i not in memo:
            memo[i] = split_of(i, h, bounds, last_idx)
        if memo[i] != split:
            continue
        per.setdefault(i, []).append(sign * r - cost)
    series = [sum(v) / len(v) for _, v in sorted(per.items())]
    s = stats.summarize(series, _lag(h))
    s["n_signals"] = sum(len(v) for v in per.values())
    s["n_sessions"] = len(series)
    return s


def threshold_study(panel: List[Dict[str, Any]], bounds, last_idx: int, cost_base: float, cost_stress: float) -> Dict[str, Any]:
    grid: List[Cfg] = [(p, float(o), r) for p in PRICE_GRID for o in OI_GRID for r in RVOL_GRID]
    out: Dict[str, Any] = {"grid": {"price_pct": list(PRICE_GRID), "oi_pct": list(OI_GRID), "rvol": list(RVOL_GRID), "configurations": len(grid)},
                           "protocol": {"primary_horizon": PRIMARY_H, "selected_on": "discovery split only, by net t-statistic",
                                        "min_signals": MIN_SIGNALS, "min_sessions": MIN_SESSIONS, "frozen_per_category": TOP_K}, "categories": {}}
    for c in CATEGORIES:
        sign = _sign(c)
        rows = [dict(x, _i=sd["i"]) for sd in panel for x in sd["thr"] if x["cat"] == c]
        fired = {cfg: _fired(rows, cfg) for cfg in grid}
        table = []
        for cfg in grid:
            d = _eval(fired[cfg], sign, PRIMARY_H, "discovery", bounds, last_idx, cost_base)
            table.append((cfg, d))
        eligible = [(cfg, d) for cfg, d in table if d["n_signals"] >= MIN_SIGNALS and d["n_sessions"] >= MIN_SESSIONS and d["t"] is not None]
        eligible.sort(key=lambda t: (-t[1]["t"], t[0][0], t[0][1], t[0][2] or 0))
        frozen = [cfg for cfg, _ in eligible[:TOP_K]]
        above = sum(1 for _, d in eligible if d["t"] > 1.645)
        positive = sum(1 for _, d in eligible if d["mean"] is not None and d["mean"] > 0)

        def full(cfg: Cfg) -> Dict[str, Any]:
            f = fired.get(cfg) or _fired(rows, cfg)
            return {"config": {"price_pct": cfg[0], "oi_pct": cfg[1], "rvol": cfg[2]},
                    "results": {str(h): {s: _eval(f, sign, h, s, bounds, last_idx, cost_base) for s in SPLITS} for h in HORIZONS},
                    "stress_cost_primary_test_mean_pct": None}

        frozen_out = []
        for cfg in frozen:
            e = full(cfg)
            v, t = e["results"][str(PRIMARY_H)]["validation"], e["results"][str(PRIMARY_H)]["test"]
            e["discovery_t"] = next(d["t"] for k, d in eligible if k == cfg)
            e["positive_net_in_validation_and_test"] = bool(v["mean"] is not None and t["mean"] is not None and v["mean"] > 0 and t["mean"] > 0
                                                            and t["n_sessions"] >= MIN_TEST_SESSIONS)
            # the same test mean under the stress cost: net_base mean - (stress - base)
            e["stress_cost_primary_test_mean_pct"] = None if t["mean"] is None else round(t["mean"] - (cost_stress - cost_base), 4)
            frozen_out.append(e)
        out["categories"][c] = {
            "eligible_in_discovery": len(eligible), "discovery_winners_t_above_1_645": above,
            "expected_by_chance_at_5pct": round(0.05 * len(eligible), 1), "discovery_positive_net": positive,
            "frozen": frozen_out,
            "baselines": {"no_threshold": full(NO_THRESHOLD), "production_floors": full(PRODUCTION_FLOORS)},
        }
    return out


# ── the report ───────────────────────────────────────────────────────────

def fingerprint(sessions: Sequence[str], scans: Dict[str, Dict[str, Any]], features: Dict[str, List[Dict[str, Any]]], px: Dict[str, Dict[str, Tuple[float, float]]]) -> Dict[str, str]:
    sc = {d: [[r.get("symbol"), r.get("label"), r.get("price_chg_pct"), r.get("oi_chg_pct"), r.get("cash_volume"), r.get("fut_turnover_cr"), r.get("cash_confirmation")]
              for r in (b.get("rows") or [])] for d, b in scans.items()}
    keys = ("close", "sma20", "sma50", "rsi14", "macd_hist", "deliv_trend10", "avg_volume_20", "atr_pct", "return_5d_pct", "vol_z20")
    ft = {s: [[r.get("as_of_date")] + [r.get(k) for k in keys] for r in rows] for s, rows in features.items()}
    return {"sessions": stats.canonical_hash(list(sessions)), "scans": stats.canonical_hash(sc), "features": stats.canonical_hash(ft), "prices": stats.canonical_hash(px)}


def run_backtest(inputs: Dict[str, Any], code_version: str = "", generated_at: Optional[str] = None, rules: Dict[str, Any] = RULES) -> Dict[str, Any]:
    sessions = list(inputs["sessions"])
    scans, features = inputs["scans"], inputs["features"]
    px = price_index(inputs["adjusted"])
    panel = build_panel(sessions, scans, features, px, rules)
    if not panel:
        return {"status": "insufficient_evidence", "validated": False, "reason": "no evaluable session", "experiment_id": None}
    first, last_signal = panel[0]["i"], panel[-1]["i"]
    bounds = split_bounds(first, last_signal)
    last_idx = len(sessions) - 1
    cost_base, cost_stress = COSTS["round_trip_pct_base"], COSTS["round_trip_pct_stress"]
    input_keys = list(rules["signal_weights"])
    ranking = ranking_study(panel, bounds, last_idx, input_keys, cost_base, cost_stress)
    thresholds = threshold_study(panel, bounds, last_idx, cost_base, cost_stress)
    n_test = ranking["long_buildup"][str(PRIMARY_H)]["test"]["variants"]["production"]["n_sessions"]
    n_test = max([ranking[c][str(PRIMARY_H)]["test"]["variants"]["production"]["n_sessions"] for c in CATEGORIES] + [n_test])
    status = "research_result" if n_test >= MIN_TEST_SESSIONS else "insufficient_evidence"
    assumptions = {
        "study_version": STUDY_VERSION, "engine_rules_version": rules["version"], "code_version": code_version,
        "entry": "open of the session after the signal session (the first executable price after an end-of-day signal)",
        "exit": "close of the session h sessions after the signal session",
        "price_basis": "split/bonus-adjusted cash prices as a proxy for the near-month future (basis and roll are not modelled)",
        "horizons_sessions": list(HORIZONS), "primary_horizon": PRIMARY_H, "costs": COSTS, "splits": "discovery 60% / validation 20% / test 20% by signal session, forward window kept inside the split",
        "engine_settings": {k: rules[k] for k in ("min_futures_turnover_cr", "min_abs_price_chg_pct", "min_abs_oi_chg_pct", "signal_weights", "min_coverage", "pool_per_category")},
    }
    window = {
        "first_signal_session": sessions[first], "last_signal_session": sessions[last_signal], "last_data_session": sessions[-1],
        "signal_sessions": len(panel), "split_sessions": {k: [sessions[a], sessions[min(b, len(sessions)) - 1]] for k, (a, b) in bounds.items()},
        "not_evaluable_before": sessions[first], "note": "The engineered features table starts on 2025-12-29; earlier sessions are not scored with missing inputs, they are not evaluated.",
    }
    fp = fingerprint(sessions, scans, features, px)
    tested = {
        "ranking_cells": len(VARIANTS) * len(CATEGORIES) * len(HORIZONS) * len(SPLITS),
        "ranking_variants": list(VARIANTS),
        "threshold_configurations": thresholds["grid"]["configurations"],
        "threshold_cells_discovery": thresholds["grid"]["configurations"] * len(CATEGORIES) * len(HORIZONS),
        "note": "Every variant, category, horizon and split evaluated is counted; the threshold winners were chosen on discovery only and frozen before validation and test.",
    }
    results = {"ranking_study": ranking, "threshold_study": thresholds}
    exp_id = "fo-bt-" + stats.canonical_hash({"assumptions": assumptions, "window": window, "fingerprint": fp})[:12]
    return {
        "experiment_id": exp_id, "status": status, "validated": False, "stage": "A (discovery on the bhavcopy-era sessions); not validated",
        "report_hash": stats.canonical_hash({"experiment_id": exp_id, "results": results, "tested": tested}),
        "generated_at": generated_at, "data_window": window, "data_fingerprint": fp, "assumptions": assumptions, "tested_configurations": tested,
        "limitations": [
            "Stage A only: nothing is validated. Stage B tests the frozen set on Kite's older daily history; Stage C is live shadow validation.",
            "About one year (the features table starts 2025-12-29): a few hundred independent sessions at best, and forward windows overlap (Newey-West errors are used).",
            "Outcomes use adjusted cash prices as a proxy for the near-month future; basis, roll and the lot size are not modelled.",
            "The cost is an assumed round-trip percentage, not a tax computation; the stress cost doubles it.",
            "OI change in the scan is summed over every expiry (the production definition), not the near-month contract alone.",
            "The candidate engine cannot score options-chain confirmation for stocks yet, so every candidate's Signal Strength coverage is at most 85%.",
            "F&O membership is the set of stocks the scan lists that day (point in time); historical NIFTY and BANKNIFTY constituents are not available, so no constituent-based analysis is made.",
            "OI percentile is not in the grid: it needs OI history that the first sessions do not have; it belongs to a second pass on the frozen set.",
        ],
        **results,
    }
