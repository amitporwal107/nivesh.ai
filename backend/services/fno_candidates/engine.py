"""Pure rules for the F&O build-up candidates: no network, no clock, no database.

Input: the build-up scan body (DaaS /desk/fno-buildup, passed through by routes/fno.py) and, per symbol, its engineered
feature rows (DaaS /features/bulk, date ascending). Output: per category the top candidates with five confirmations, a
fundamental context rating and the figures behind them.

A missing input is `None` ("unknown"), never a pass and never a fail, and never 0. Nothing here is a probability or a score.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from .rules import CATEGORIES, CATEGORY_TEXT, DIRECTION, DISCLOSURE, PER_DEFAULT, PER_MAX, RULES, RULES_VERSION, research_block

INDEX_SYMBOLS = ("NIFTY", "BANKNIFTY")
HORIZON = "positional"


def num(v: Any) -> Optional[float]:
    """A finite number, or None. Booleans and unparseable text are not numbers."""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _f(v: Optional[float], d: int = 1) -> str:
    return "—" if v is None else f"{v:,.{d}f}"


def _pct(v: Optional[float], d: int = 2) -> str:
    return "—" if v is None else f"{v:+.{d}f}%"


def plan_inputs(symbol: str, direction: str) -> Dict[str, str]:
    """The body that asks POST /api/desk/strategy/plan for this candidate's strategies (the engine's own defaults for the rest)."""
    return {"underlying": symbol, "direction": direction, "horizon": HORIZON}


# ── pools ────────────────────────────────────────────────────────────────

def select_pools(body: Dict[str, Any], rules: Dict[str, Any] = RULES) -> Dict[str, Dict[str, Any]]:
    """Per category: how many stocks the scan labelled so, the pool that passes the floors (largest |OI change| first, at most
    `pool_per_category`), and how many were left out and why."""
    out: Dict[str, Dict[str, Any]] = {
        c: {"in_scan": 0, "pool": [], "excluded": {"not_fno_eligible": 0, "no_turnover": 0, "thin_futures": 0, "small_move": 0}}
        for c in CATEGORIES
    }
    for row in body.get("rows") or []:
        if not isinstance(row, dict):
            continue
        g = out.get(row.get("label"))
        if g is None:
            continue
        g["in_scan"] += 1
        ex = g["excluded"]
        if row.get("fno_eligible") is False:
            ex["not_fno_eligible"] += 1
            continue
        turnover = num(row.get("fut_turnover_cr"))
        if turnover is None:
            ex["no_turnover"] += 1
            continue
        if turnover < rules["min_futures_turnover_cr"]:
            ex["thin_futures"] += 1
            continue
        price, oi = num(row.get("price_chg_pct")), num(row.get("oi_chg_pct"))
        if price is None or oi is None or abs(price) < rules["min_abs_price_chg_pct"] or abs(oi) < rules["min_abs_oi_chg_pct"]:
            ex["small_move"] += 1
            continue
        g["pool"].append(row)
    for g in out.values():
        g["pool"].sort(key=lambda r: (-abs(num(r.get("oi_chg_pct")) or 0.0), str(r.get("symbol") or "")))
        g["pool"] = g["pool"][: rules["pool_per_category"]]
    return out


def pool_symbols(pools: Dict[str, Dict[str, Any]]) -> List[str]:
    seen: List[str] = []
    for c in CATEGORIES:
        for r in pools[c]["pool"]:
            s = str(r.get("symbol") or "").upper()
            if s and s not in seen:
                seen.append(s)
    return seen


# ── the five confirmations ───────────────────────────────────────────────

def _check(key: str, state: Optional[bool], observed: str, rules: Dict[str, Any]) -> Dict[str, Any]:
    return {"key": key, "label": rules["checks"][key], "state": state, "observed": observed}


def run_checks(direction: str, row: Dict[str, Any], feat: Optional[Dict[str, Any]], rules: Dict[str, Any] = RULES) -> List[Dict[str, Any]]:
    bull = direction == "bullish"
    f = feat or {}
    out: List[Dict[str, Any]] = []

    conf = row.get("cash_confirmation")
    cash_state = True if conf == "confirms" else False if conf == "diverges" else None
    out.append(_check("cash_confirms", cash_state,
                      f"futures {_pct(num(row.get('price_chg_pct')))}, cash {_pct(num(row.get('cash_chg_pct')))}" if cash_state is not None else "no cash move to compare", rules))

    vz = num(row.get("vol_z20"))
    vz = vz if vz is not None else num(f.get("vol_z20"))
    out.append(_check("volume_elevated", None if vz is None else vz >= rules["vol_z_min"], "vol_z20 —" if vz is None else f"vol_z20 {vz:+.2f}", rules))

    dt = num(f.get("deliv_trend10"))
    avg = num(f.get("deliv_pct_avg_20"))
    out.append(_check("delivery_rising", None if dt is None else dt > 0,
                      "no delivery data" if dt is None else f"10-session trend {dt:+.2f}" + (f", 20-day average {avg:.0f}%" if avg is not None else ""), rules))

    close, s20, s50 = num(f.get("close")), num(f.get("sma20")), num(f.get("sma50"))
    if close is None or s20 is None or s50 is None:
        trend: Optional[bool] = None
        obs = "no average to compare"
    else:
        trend = (close > s20 and close > s50) if bull else (close < s20 and close < s50)
        obs = f"close {_f(close, 2)}, 20-day {_f(s20, 2)}, 50-day {_f(s50, 2)}"
    out.append(_check("trend_aligned", trend, obs, rules))

    rsi, mh = num(f.get("rsi14")), num(f.get("macd_hist"))
    if rsi is None or mh is None:
        mom: Optional[bool] = None
        obs = "RSI or MACD missing"
    else:
        lo, hi = rules["rsi_bullish_band"] if bull else rules["rsi_bearish_band"]
        mom = lo <= rsi <= hi and (mh > 0 if bull else mh < 0)
        stretched = " (stretched)" if (rsi > hi if bull else rsi < lo) else ""
        obs = f"RSI {rsi:.1f}{stretched}, MACD histogram {mh:+.2f}"
    out.append(_check("momentum_aligned", mom, obs, rules))

    ret5, atr = num(f.get("return_5d_pct")), num(f.get("atr_pct"))
    if ret5 is None or atr is None or atr <= 0:
        viable: Optional[bool] = None
        obs = "no 5-day move or daily range"
    else:
        moved = ret5 if bull else -ret5
        limit = rules["extended_atr_multiple"] * atr
        viable = moved <= limit
        obs = f"5-day move {ret5:+.1f}% vs a normal daily range of {atr:.1f}% (limit {limit:.1f}% in the trade's direction)"
    out.append(_check("entry_not_extended", viable, obs, rules))
    return out


# ── fundamental context ──────────────────────────────────────────────────

def fundamentals(direction: str, feat: Optional[Dict[str, Any]], rules: Dict[str, Any] = RULES) -> Dict[str, Any]:
    cfg, f = rules["fundamentals"], feat or {}
    spec: List[Tuple[str, str, str, str, float, str]] = [
        ("roe_pct", "ROE", "%", ">=", cfg["roe_pct_min"], "roe_pct_min"),
        ("roce_pct", "ROCE", "%", ">=", cfg["roce_pct_min"], "roce_pct_min"),
        ("debt_to_equity", "Debt / equity", "×", "<=", cfg["debt_to_equity_max"], "debt_to_equity_max"),
        ("pat_growth_yoy_pct", "Profit growth YoY", "%", ">", cfg["pat_growth_yoy_pct_min"], "pat_growth_yoy_pct_min"),
        ("eps_growth_3y_cagr_pct", "EPS growth 3Y", "%", ">=", cfg["eps_growth_3y_cagr_pct_min"], "eps_growth_3y_cagr_pct_min"),
        ("promoter_pledged_pct", "Promoter pledge", "%", "<=", cfg["promoter_pledged_pct_max"], "promoter_pledged_pct_max"),
    ]
    facts: List[Dict[str, Any]] = []
    for key, label, unit, op, bound, _rule in spec:
        v = num(f.get(key))
        ok: Optional[bool] = None
        if v is not None:
            ok = {">=": v >= bound, "<=": v <= bound, ">": v > bound}[op]
        facts.append({"key": key, "label": label, "value": v, "unit": unit, "rule": f"{op} {bound:g}{unit}", "ok": ok})
    known = sum(1 for x in facts if x["ok"] is not None)
    pos = sum(1 for x in facts if x["ok"] is True)
    if known < cfg["min_known"]:
        rating, agrees = "unavailable", None
    else:
        share = pos / known
        rating = "strong" if share >= cfg["strong_share"] else "weak" if share <= cfg["weak_share"] else "mixed"
        bull = direction == "bullish"
        agrees = (True if rating == "strong" else False if rating == "weak" else None) if bull else (True if rating == "weak" else False if rating == "strong" else None)
    context = [{"key": k, "label": lab, "value": num(f.get(k)), "unit": u} for k, lab, u in
               (("pe_ttm", "P/E", "×"), ("pe_vs_sector_pct", "P/E vs sector", "%"), ("market_cap_cr", "Market cap", "₹ cr"), ("promoter_pct", "Promoter holding", "%"))]
    return {"rating": rating, "agrees_with_direction": agrees, "holds": pos, "known": known, "total": len(facts), "facts": facts, "context": context,
            "note": "Reported figures, updated quarterly; a view on the business, not on this week's move."}


# ── candidates ───────────────────────────────────────────────────────────

def _latest(features: Dict[str, List[Dict[str, Any]]], symbol: str) -> Optional[Dict[str, Any]]:
    rows = features.get(symbol) or features.get(symbol.upper())
    return rows[-1] if isinstance(rows, list) and rows else None


def _mean_of_states(checks: List[Dict[str, Any]], keys: List[str]) -> Optional[float]:
    states = [c["state"] for c in checks if c["key"] in keys and c["state"] is not None]
    return None if not states else 100.0 * sum(1 for s in states if s) / len(states)


def _ramp(x: float, zero_at: float, full_at: float) -> float:
    """0 at `zero_at`, 100 at `full_at`, linear between, clamped."""
    return 100.0 * min(max((x - zero_at) / (full_at - zero_at), 0.0), 1.0)


def score_block(weights: Dict[str, int], labels: Dict[str, str], values: Dict[str, Tuple[Optional[float], Optional[str], Optional[str]]]) -> Dict[str, Any]:
    """One score from weighted inputs. `values[key]` is (score 0-100 or None, what was observed, why it is missing).

    A missing input is NOT redistributed: the denominator stays the full weight (100 points), the input's points go unearned, and the
    block reports `coverage` (the share of the weight that was available), `complete` and the missing inputs with their weights."""
    total = float(sum(weights.values()))
    inputs, missing, earned, known_w = [], [], 0.0, 0.0
    for k, w in weights.items():
        score, observed, why = values.get(k, (None, None, "not provided"))
        if score is None:
            missing.append({"key": k, "label": labels[k], "weight": w, "reason": why})
            inputs.append({"key": k, "label": labels[k], "weight": w, "score": None, "points": None, "observed": None})
        else:
            pts = w * score / 100.0
            earned += pts
            known_w += w
            inputs.append({"key": k, "label": labels[k], "weight": w, "score": round(score, 1), "points": round(pts, 1), "observed": observed})
    return {"points": round(earned, 1), "max_points": total, "coverage": round(known_w / total, 2), "complete": not missing, "inputs": inputs, "missing": missing}


def signal_strength(label: str, row: Dict[str, Any], feat: Optional[Dict[str, Any]], checks: List[Dict[str, Any]], rules: Dict[str, Any] = RULES) -> Dict[str, Any]:
    sat, f = rules["saturation"], feat or {}
    oi, price = num(row.get("oi_chg_pct")), num(row.get("price_chg_pct"))
    vals: Dict[str, Tuple[Optional[float], Optional[str], Optional[str]]] = {}
    vals["oi_signal"] = (None, None, "no OI change in the scan") if oi is None else (
        min(abs(oi) / sat["oi_chg_pct"], 1.0) * 100.0 * rules["oi_weaker_reading_factor"][label], f"OI {oi:+.1f}% (full marks at {sat['oi_chg_pct']:g}%)", None)
    vals["price_behavior"] = (None, None, "no futures price change in the scan") if price is None else (
        min(abs(price) / sat["price_chg_pct"], 1.0) * 100.0, f"futures {price:+.2f}% (full marks at {sat['price_chg_pct']:g}%)", None)
    vol, avg = num(row.get("cash_volume")), num(f.get("avg_volume_20"))
    if vol is None or avg is None or avg <= 0:
        vals["volume"] = (None, None, "cash volume or its 20-day average is missing")
    else:
        rv = vol / avg
        vals["volume"] = (_ramp(rv, rules["rvol"]["zero_score_at"], rules["rvol"]["full_score_at"]), f"{rv:.2f}x its 20-day average", None)
    vals["options_confirmation"] = (None, None, "Options-chain confirmation is not computed for stocks yet.")
    cd = _mean_of_states(checks, rules["groups"]["cash_delivery"])
    vals["cash_delivery"] = (None, None, "no cash-confirmation or delivery data") if cd is None else (cd, "; ".join(c["observed"] for c in checks if c["key"] in rules["groups"]["cash_delivery"] and c["state"] is not None), None)
    tech = _mean_of_states(checks, rules["groups"]["technical"])
    vals["technical"] = (None, None, "no average, RSI or MACD to read") if tech is None else (tech, "; ".join(c["observed"] for c in checks if c["key"] in rules["groups"]["technical"] and c["state"] is not None), None)
    return score_block(rules["signal_weights"], rules["signal_labels"], vals)


def tradeability(row: Dict[str, Any], rules: Dict[str, Any] = RULES) -> Dict[str, Any]:
    turnover, days = num(row.get("fut_turnover_cr")), num(row.get("days_to_expiry"))
    ed = rules["expiry_distance_days"]
    vals: Dict[str, Tuple[Optional[float], Optional[str], Optional[str]]] = {
        "liquidity": (None, None, "no futures turnover in the scan") if turnover is None else (
            100.0 * min(turnover / (rules["liquidity_full_multiple"] * rules["min_futures_turnover_cr"]), 1.0), f"futures turnover ₹{turnover:,.0f} cr", None),
        "expiry_distance": (None, None, "no days to expiry in the scan") if days is None else (_ramp(days, ed["zero_score_at"], ed["full_score_at"]), f"{days:g} days to expiry", None),
        "spread_depth": (None, None, "no bid-ask or depth in end-of-day data"),
    }
    return score_block(rules["tradeability_weights"], rules["tradeability_labels"], vals)


STRATEGY_QUALITY_UNAVAILABLE = {
    "state": "unavailable",
    "reasons": [
        "Strategy quality is a property of one structure: it needs its payoff, risk, Greeks and costs, which the plan engine computes per candidate on request.",
        "The cost model still omits STT, exchange charges, GST and stamp duty, and no probability-of-profit method exists yet.",
    ],
}


def signal_state(checks: List[Dict[str, Any]], rules: Dict[str, Any] = RULES) -> str:
    """PRD 10.5: candidate, confirmed, invalidated or unavailable. One price-and-OI move alone is never "confirmed"."""
    st = {c["key"]: c["state"] for c in checks}
    cfg = rules["state"]
    if sum(1 for v in st.values() if v is not None) < cfg["unavailable_below_known"]:
        return "unavailable"
    if st["cash_confirms"] is False and st["trend_aligned"] is False:
        return "invalidated"
    others = sum(1 for k in ("volume_elevated", "delivery_rising", "trend_aligned", "momentum_aligned") if st[k] is True)
    if st["cash_confirms"] is True and st["entry_not_extended"] is not False and others >= cfg["confirmed_min_other_checks"]:
        return "confirmed"
    return "candidate"


def _ranked(sig: Dict[str, Any], trade: Dict[str, Any], rules: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    mc = rules["min_coverage"]
    if sig["coverage"] < mc["signal_strength"]:
        names = ", ".join(m["label"] for m in sig["missing"])
        return False, f"Signal Strength coverage {sig['coverage']:.0%} is below the {mc['signal_strength']:.0%} minimum (missing: {names})"
    if trade["coverage"] < mc["tradeability"]:
        names = ", ".join(m["label"] for m in trade["missing"])
        return False, f"Tradeability coverage {trade['coverage']:.0%} is below the {mc['tradeability']:.0%} minimum (missing: {names})"
    return True, None


def _candidate(label: str, row: Dict[str, Any], feat: Optional[Dict[str, Any]], rules: Dict[str, Any]) -> Dict[str, Any]:
    direction = DIRECTION[label]
    symbol = str(row.get("symbol") or "").upper()
    checks = run_checks(direction, row, feat, rules)
    f = feat or {}
    holds = sum(1 for c in checks if c["state"] is True)
    known = sum(1 for c in checks if c["state"] is not None)
    sig, trade = signal_strength(label, row, feat, checks, rules), tradeability(row, rules)
    ranked, why = _ranked(sig, trade, rules)
    return {
        "symbol": symbol, "sector": row.get("sector") or f.get("sector"), "label": label, "direction": direction,
        "price_chg_pct": num(row.get("price_chg_pct")), "oi_chg_pct": num(row.get("oi_chg_pct")), "oi": num(row.get("oi")),
        "close": num(row.get("close")), "cash_close": num(row.get("cash_close")), "cash_chg_pct": num(row.get("cash_chg_pct")),
        "near_expiry": row.get("near_expiry"), "days_to_expiry": num(row.get("days_to_expiry")),
        "fut_turnover_cr": num(row.get("fut_turnover_cr")), "risk_flags": [x for x in (row.get("risk_flags") or []) if isinstance(x, str)],
        "scores": {"signal_strength": sig, "tradeability": trade, "strategy_quality": STRATEGY_QUALITY_UNAVAILABLE},
        "ranked": ranked, "unranked_reason": why,
        "signal_state": signal_state(checks, rules), "entry_viable": next(c["state"] for c in checks if c["key"] == "entry_not_extended"),
        "checks": checks, "confirmations": {"holds": holds, "known": known, "total": len(checks)},
        "fundamental_context": fundamentals(direction, feat, rules),
        "delivery": {"avg20_pct": num(f.get("deliv_pct_avg_20")), "trend10": num(f.get("deliv_trend10"))},
        "technical": {k: num(f.get(k)) for k in ("rsi14", "macd_hist", "dist_200dma_pct", "return_5d_pct", "return_20d_pct", "atr_pct", "accumulation_score")},
        "features_as_of": f.get("as_of_date"),
        "plan_inputs": plan_inputs(symbol, direction),
    }


def _rank(c: Dict[str, Any]) -> Tuple[float, float, str]:
    return (-c["scores"]["signal_strength"]["points"], -abs(c["oi_chg_pct"] or 0.0), c["symbol"])


def _index_block(body: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in body.get("indices") or []:
        sym = str((row or {}).get("symbol") or "").upper()
        if sym not in INDEX_SYMBOLS:
            continue
        label = row.get("label") if row.get("label") in CATEGORIES else None
        direction = DIRECTION.get(label) if label else None
        conf = row.get("cash_confirmation")
        out.append({
            "symbol": sym, "index_name": row.get("index_name"), "label": row.get("label"), "direction": direction,
            "price_chg_pct": num(row.get("price_chg_pct")), "oi_chg_pct": num(row.get("oi_chg_pct")),
            "cash_close": num(row.get("cash_close")), "cash_chg_pct": num(row.get("cash_chg_pct")),
            "cash_confirms": True if conf == "confirms" else False if conf == "diverges" else None,
            "near_expiry": row.get("near_expiry"), "days_to_expiry": num(row.get("days_to_expiry")),
            "risk_flags": [x for x in (row.get("risk_flags") or []) if isinstance(x, str)],
            "plan_inputs": plan_inputs(sym, direction) if direction else None,
            "note": "An index has no delivery or fundamentals: the reading is the futures build-up and the cash check only."
                    + ("" if direction else " The build-up is neutral or unavailable, so no direction is suggested."),
        })
    out.sort(key=lambda r: INDEX_SYMBOLS.index(r["symbol"]))
    return out


def build_all(body: Dict[str, Any], pools: Dict[str, Dict[str, Any]], features: Dict[str, List[Dict[str, Any]]], rules: Dict[str, Any] = RULES) -> Dict[str, List[Dict[str, Any]]]:
    """Every pool candidate of every category, ranked or not, with all its scores: the research code ranks and evaluates them itself."""
    return {c: [_candidate(c, row, _latest(features, str(row.get("symbol") or "")), rules) for row in pools[c]["pool"]] for c in CATEGORIES}


def assemble(body: Dict[str, Any], pools: Dict[str, Dict[str, Any]], features: Dict[str, List[Dict[str, Any]]], per: int = PER_DEFAULT,
             rules: Dict[str, Any] = RULES) -> Dict[str, Any]:
    per = max(1, min(PER_MAX, int(per)))
    categories: Dict[str, Any] = {}
    feat_days: List[str] = []
    used_features = 0
    for c in CATEGORIES:
        g = pools[c]
        built = []
        for row in g["pool"]:
            feat = _latest(features, str(row.get("symbol") or ""))
            if feat:
                used_features += 1
                if feat.get("as_of_date"):
                    feat_days.append(str(feat["as_of_date"])[:10])
            built.append(_candidate(c, row, feat, rules))
        ranked = sorted((x for x in built if x["ranked"]), key=_rank)
        unranked = [{"symbol": x["symbol"], "reason": x["unranked_reason"], "signal_coverage": x["scores"]["signal_strength"]["coverage"],
                     "tradeability_coverage": x["scores"]["tradeability"]["coverage"]} for x in built if not x["ranked"]]
        excluded = dict(g["excluded"])
        excluded["insufficient_coverage"] = len(unranked)
        categories[c] = {
            "label": c, "direction": DIRECTION[c], "meaning": CATEGORY_TEXT[c], "in_scan": g["in_scan"], "pool": len(g["pool"]),
            "excluded": excluded, "candidates": ranked[:per], "unranked": unranked[:10],
        }
    gaps = [
        "End of day: the build-up is the NSE bhavcopy. Intraday confirmation is not available because no intraday OI was stored before 23 Oct 2026.",
        "Options-chain confirmation is not computed for stocks yet, so Signal Strength coverage is capped at 85%.",
        "OI persistence, acceleration and OI percentile need OI history this scan does not carry; they are not scored.",
        "No threshold or weight here has been validated out of sample.",
    ]
    if not features:
        gaps.append("The engineered features could not be read, so the volume, delivery and technical inputs are missing and candidates may be unranked.")
    elif used_features == 0:
        gaps.append("No candidate had a feature row, so the volume, delivery and technical inputs are missing and candidates may be unranked.")
    return {
        "as_of": body.get("as_of"), "source": body.get("source"), "rules_version": RULES_VERSION, "threshold_version": RULES_VERSION, "rules": rules,
        "research": research_block(), "per_category": per, "universe": body.get("universe"), "categories": categories, "indices": _index_block(body),
        "features_as_of": max(feat_days) if feat_days else None, "disclosure": DISCLOSURE, "gaps": gaps,
        "risk_flag_text": body.get("risk_flag_text") or {}, "read_only": True, "sent_to_broker": False,
    }
