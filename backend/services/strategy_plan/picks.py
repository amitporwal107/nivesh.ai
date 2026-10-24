"""Best picks from the user's Chartink scans (user requirement 2026-10-20: "not only scan the Chartink dashboard but give the best picks out of it and the
trading strategies"). Read-only; nothing here places, modifies or cancels an order, and nothing is written.

The candidates are the stocks the user's enabled Chartink scans listed (services/chartink_desk/hits.read_index). Each one that passes the scan-snapshot
eligibility gates is run through the same source collection and the same plan builder as the Strategy Builder (sources.collect_snapshots, plan.build_plan);
the evidence score is read off that plan's evidence ledger plus the stock's scan row and feature row, and the strategies are that plan's own
(ideas.strategies_of). Nothing is calculated twice and no second data path exists.

The score (rules.RULES["chartink_picks"]) is a deterministic rank of REAL evidence, 0 to 100: every factor earns weight x credit (supports 1, neutral
a fixed share, conflicts 0, unavailable 0); a figure that could not be read is listed as unavailable and is never neutral and never positive. It is not a
probability. Thin or conflicting evidence is a Wait / No trade outcome, not a pick.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Request

from services.positional_engine import setup_rules

from . import evidence as ev
from . import selection as sel
from .engine import CALCULATION_VERSION
from .ideas import fno_eligible, plan_body, strategies_of
from .plan import MARGIN_CAVEAT, build_plan, normalise_inputs
from .rules import RULES, STRATEGY_RULES_VERSION
from .sources import chartink_index, collect_snapshots, company_name, scanner_snapshot, shared_for_ideas

logger = logging.getLogger(__name__)

CFG = RULES["chartink_picks"]
FACTOR_ORDER = tuple(CFG["weights"])
LABELS = {"scan_confluence": "Scan confluence", "trend": "Trend (EMA)", "momentum": "Momentum (MACD, 20-day change, RSI)", "relative_volume": "Relative volume",
          "liquidity": "Liquidity", "oi_buildup": "F&O open-interest build-up", "fundamentals": "Fundamentals quality", "event_risk": "Event risk (results)",
          "range_position": "Distance from 52-week extremes", "atr_risk": "ATR risk"}
TONE = {"supports": "up", "neutral": "flat", "conflicts": "down", "unavailable": "na", "not_applicable": "na"}
CREDIT = {"supports": 1.0, "neutral": CFG["neutral_credit"], "conflicts": 0.0, "unavailable": 0.0}
ACTION = {"long": "Long idea: the long side of the plan below (cash, futures, defined-risk options, combinations).",
          "short": "Avoid new longs. Short side only through futures or defined-risk options (no naked short options); the plan below lists what the evidence supports."}
DIRECTIONS = ("all", "long", "short")
RANKING_NOTE = (CFG["rule"] + " The score ranks the evidence; it is not a probability, not a forecast and not a promise. Your Chartink scans are your own screens and have "
                "not been validated.")
CAVEATS = ["Conditional research ideas, not advice and not an instruction to trade.",
           "End-of-day data: nothing here is live. F&O data is one NSE bhavcopy per day.",
           "Payoff figures are calculations at the prices shown, not forecasts; taxes, statutory charges, dividends and funding are excluded.",
           MARGIN_CAVEAT, "Nothing is sent to a broker."]


# ── the score (pure) ─────────────────────────────────────────────────────────

def factor(key: str, state: str, text: str, value: Any = None, source: Optional[str] = None, as_of: Optional[str] = None, credit: Optional[float] = None) -> Dict[str, Any]:
    """One scored factor. `credit` overrides the state's usual credit (scan confluence is continuous; a stretched RSI halves the momentum credit)."""
    w = CFG["weights"][key]
    c = 0.0 if state in ("unavailable", "not_applicable") else (CREDIT[state] if credit is None else credit)
    return {"key": key, "label": LABELS[key], "weight": w, "points": round(w * c, 2), "state": state, "tone": TONE[state], "text": text, "value": value,
            "source": source, "as_of": as_of}


def from_item(key: str, it: Optional[Dict[str, Any]], missing: str, value: Any = None, credit: Optional[float] = None, state: Optional[str] = None,
              text: Optional[str] = None) -> Dict[str, Any]:
    """A factor read from a ledger item (its direction is already relative to the pick's direction)."""
    if it is None:
        return factor(key, "unavailable", missing)
    st = state or ("supports" if it["direction"] == "supports" else "conflicts" if it["direction"] == "conflicts" else
                   "unavailable" if it["direction"] == "unavailable" else "neutral")
    return factor(key, st, text or it["interpretation"], it["value"] if value is None else value, it.get("source"), it.get("source_as_of"), credit)


def scan_factor(d: str, entry: Optional[Dict[str, Any]], ck: Dict[str, Any]) -> Dict[str, Any]:
    c = CFG["scan_confluence"]
    want = "bullish" if d == "bullish" else "bearish"
    scans = (entry or {}).get("scans") or []
    aligned, opposed = [s for s in scans if s.get("direction") == want], [s for s in scans if s.get("direction") not in (want, "neutral", None)]
    credit = max(0.0, min(1.0, (len(aligned) - c["opposed_scan_penalty"] * len(opposed)) / c["full_at_aligned_scans"]))
    state = "unavailable" if not ck["ok"] else "supports" if not opposed and aligned else "neutral" if credit >= 0.5 else "conflicts"
    if not ck["ok"]:
        return factor("scan_confluence", "unavailable", f"Chartink scans unavailable: {ck['error']}")
    text = (f"{len(aligned)} of your enabled {want} Chartink scans listed it: {', '.join(str(s.get('name')) for s in aligned)}."
            + (f" {len(opposed)} opposing scan(s) also listed it ({', '.join(str(s.get('name')) for s in opposed)}) and each takes {c['opposed_scan_penalty']:g} of "
               f"{c['full_at_aligned_scans']} off the credit." if opposed else "")
            + " A scan is a rule match you chose, not validated and not a probability.")
    return factor("scan_confluence", state, text, {"aligned": len(aligned), "opposed": len(opposed), "full_at_aligned_scans": c["full_at_aligned_scans"]},
                  ck.get("source"), ck.get("as_of"), credit)


def momentum_factor(d: str, it: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    f = from_item("momentum", it, "Needs MACD histogram and 20-day rate of change.")
    rsi = ev.num(((it or {}).get("value") or {}).get("rsi14")) if it and it["direction"] != "unavailable" else None
    stretched = rsi is not None and ((d == "bullish" and rsi >= RULES["rsi"]["stretched_above"]) or (d == "bearish" and rsi <= RULES["rsi"]["weak_below"]))
    if stretched and f["state"] == "supports":
        h = CFG["rsi_haircut"]
        return {**f, "state": "neutral", "tone": TONE["neutral"], "points": round(f["weight"] * h, 2),
                "text": f["text"] + f" RSI {rsi:.0f} is already stretched in this direction, so the credit is cut to {h:g}."}
    return f


def volume_factor(it: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    rv = ev.num(((it or {}).get("value") or {}).get("rvol20")) if it and it["direction"] != "unavailable" else None
    if rv is None:
        return factor("relative_volume", "unavailable", (it or {}).get("interpretation") or "Needs 20 sessions of volume.", None, (it or {}).get("source"), (it or {}).get("source_as_of"))
    confirm, floor = RULES["rvol_confirm"], CFG["rvol"]["neutral_from"]
    state = "supports" if rv >= confirm else "neutral" if rv >= floor else "conflicts"
    note = {"supports": f"confirms (at or above {confirm:g}x)", "neutral": f"is ordinary (from {floor:g}x to {confirm:g}x)", "conflicts": f"is thin (under {floor:g}x)"}[state]
    return factor("relative_volume", state, f"Relative volume {rv:.2f}x the 20-session average {note}.", {"rvol20": rv}, it.get("source"), it.get("source_as_of"))


def liquidity_factor(snaps: Dict[str, Any], vol: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    sr = ev.snap(snaps, "scan_row")
    tv, src, asof = None, None, None
    if sr["ok"] and ev.num((sr["data"] or {}).get("traded_value_cr_20d")) is not None:
        tv, src, asof = ev.num(sr["data"]["traded_value_cr_20d"]), sr["source"], sr["as_of"]
    elif vol and vol["direction"] != "unavailable" and ev.num((vol["value"] or {}).get("avg_traded_value_cr20")) is not None:
        tv, src, asof = ev.num(vol["value"]["avg_traded_value_cr20"]), vol.get("source"), vol.get("source_as_of")
    if tv is None:
        return factor("liquidity", "unavailable", f"20-session traded value unavailable: {sr['error'] or 'no figure in the sources'}", None, sr.get("source"))
    floor, full = setup_rules.LIQUIDITY["min_traded_value_cr"], CFG["liquidity"]["full_at_cr"]
    state = "supports" if tv >= full else "neutral" if tv >= floor else "conflicts"
    return factor("liquidity", state, f"20-session traded value Rs {tv:g} crore a day (gate Rs {floor:g} crore; full credit from Rs {full:g} crore).", tv, src, asof)


def fundamentals_factor(d: str, snaps: Dict[str, Any]) -> Dict[str, Any]:
    f, c = ev.snap(snaps, "features"), CFG["fundamentals"]
    if not f["ok"] or not isinstance(f["data"], dict):
        return factor("fundamentals", "unavailable", f"Fundamental columns unavailable: {f['error'] or 'no feature row'}", None, f.get("source"))
    r = f["data"]
    roe, de, cfo = ev.num(r.get("roe_pct")), ev.num(r.get("debt_to_equity")), ev.num(r.get("cfo_pat_ratio"))
    tests = [("ROE", roe, roe is not None and roe >= c["roe_min_pct"], f"ROE {roe}% (needs {c['roe_min_pct']:g}% or more)"),
             ("debt-to-equity", de, de is not None and de <= c["debt_to_equity_max"], f"debt-to-equity {de} (needs {c['debt_to_equity_max']:g} or less)"),
             ("cash conversion", cfo, cfo is not None and cfo >= RULES["cash_flow"]["strong_at_or_above"],
              f"CFO / PAT {cfo} (needs {RULES['cash_flow']['strong_at_or_above']:g} or more)")]
    readable = [t for t in tests if t[1] is not None]
    passed = [t for t in readable if t[2]]
    value = {"tests_readable": len(readable), "tests_passed": len(passed), "roe_pct": roe, "debt_to_equity": de, "cfo_pat_ratio": cfo}
    missing = [t[0] for t in tests if t[1] is None]
    if len(readable) < c["min_tests"]:
        return factor("fundamentals", "unavailable", f"Only {len(readable)} of 3 quality figures are readable (at least {c['min_tests']} are needed; missing: {', '.join(missing)}).",
                      value, f["source"], f["as_of"])
    sg = "up" if len(passed) == len(readable) else "down" if not passed else "flat"
    state = {"supports": "supports", "conflicts": "conflicts"}.get(ev.rel(sg, d), "neutral")
    text = (f"{len(passed)} of {len(readable)} readable quality tests passed: " + "; ".join(t[3] + (" passed" if t[2] else " failed") for t in readable)
            + (f". Unreadable: {', '.join(missing)}." if missing else ".") + " Context for the horizon, not a short-term trigger.")
    return factor("fundamentals", state, text, value, f["source"], f["as_of"])


def range_factor(d: str, snaps: Dict[str, Any]) -> Dict[str, Any]:
    f, c = ev.snap(snaps, "features"), CFG["range_position"]
    row = f["data"] if f["ok"] and isinstance(f["data"], dict) else {}
    hi, lo = ev.num(row.get("dist_52w_high_pct")), ev.num(row.get("dist_52w_low_pct"))
    need = hi if d == "bullish" else lo
    if need is None or (d == "bearish" and hi is None):
        return factor("range_position", "unavailable", f"52-week distance unavailable: {f['error'] or 'dist_52w_high_pct / dist_52w_low_pct are empty in the feature row'}", None, f.get("source"))
    value = {"dist_52w_high_pct": hi, "dist_52w_low_pct": lo}
    if d == "bullish":
        state = "supports" if hi >= -c["near_pct"] else "conflicts" if hi < -c["far_pct"] else "neutral"
        text = f"{abs(hi):g}% below its 52-week high (within {c['near_pct']:g}% supports a long; more than {c['far_pct']:g}% below conflicts)."
    else:
        state = "supports" if lo <= c["near_pct"] else "conflicts" if hi >= -c["near_pct"] else "neutral"
        text = f"{lo:g}% above its 52-week low and {abs(hi):g}% below its high (within {c['near_pct']:g}% of the low supports a short; within {c['near_pct']:g}% of the high conflicts)."
    return factor("range_position", state, text, value, f["source"], f["as_of"])


def atr_factor(it: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    pct = ev.num(((it or {}).get("value") or {}).get("atr_pct")) if it and it["direction"] != "unavailable" else None
    if pct is None:
        return factor("atr_risk", "unavailable", (it or {}).get("interpretation") or "ATR(14) needs 15 usable sessions.", None, (it or {}).get("source"), (it or {}).get("source_as_of"))
    cls = setup_rules.risk_class(pct)
    state = {"low": "supports", "medium": "neutral", "high": "conflicts"}[cls]
    return factor("atr_risk", state, f"ATR(14) is {pct:.2f}% of the close: {cls} gap and stop risk (bands {setup_rules.RISK_BANDS['low_below_pct']:g}% and {setup_rules.RISK_BANDS['high_above_pct']:g}%).",
                  {"atr_pct": pct, "risk_class": cls}, it.get("source"), it.get("source_as_of"))


def event_factor(it: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    f = from_item("event_risk", it, "Event calendar unavailable.")
    if it and it["direction"] == "neutral":
        return {**f, "state": "supports", "tone": TONE["supports"], "points": float(CFG["weights"]["event_risk"])}
    return f


def oi_factor(snaps: Dict[str, Any], it: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if fno_eligible(snaps) is False:
        return factor("oi_buildup", "not_applicable", "Not an F&O stock: there is no futures open interest to read, so this factor does not apply and is left out of the score's weight.")
    return from_item("oi_buildup", it, "Futures open-interest build-up unavailable.")


def score_pick(d: str, entry: Optional[Dict[str, Any]], snaps: Dict[str, Any], items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The factor breakdown and the 0-100 evidence score of one stock for direction `d` (bullish | bearish), from its ledger items and source snapshots."""
    L = {i["key"]: i for i in items}
    ck = ev.snap(snaps, "chartink")
    factors = [scan_factor(d, entry, ck), from_item("trend", L.get("trend_structure"), "Needs the close and the 20- and 50-day EMAs."), momentum_factor(d, L.get("momentum")),
               volume_factor(L.get("volume")), liquidity_factor(snaps, L.get("volume")), oi_factor(snaps, L.get("oi_buildup")), fundamentals_factor(d, snaps),
               event_factor(L.get("results_and_events")), range_factor(d, snaps), atr_factor(L.get("atr"))]
    assert tuple(f["key"] for f in factors) == FACTOR_ORDER
    applicable = [f for f in factors if f["state"] != "not_applicable"]
    total = sum(f["weight"] for f in applicable)
    readable = sum(f["weight"] for f in applicable if f["state"] != "unavailable")
    score = round(100 * sum(f["points"] for f in applicable) / total, 1)
    return {"score": score, "factors": factors, "available_weight_pct": round(100 * readable / total, 1),
            "counts": {s: sum(1 for f in applicable if f["state"] == s) for s in ("supports", "neutral", "conflicts", "unavailable")}}


def reasons(factors: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(for, against, unavailable): supporting factors by points earned, conflicting ones by weight lost, and what could not be read."""
    def r(f):
        return {"key": f["key"], "label": f["label"], "text": f["text"], "points": f["points"], "weight": f["weight"], "source": f["source"], "as_of": f["as_of"]}
    fors = sorted((f for f in factors if f["state"] == "supports"), key=lambda f: (-f["points"], FACTOR_ORDER.index(f["key"])))
    against = sorted((f for f in factors if f["state"] == "conflicts"), key=lambda f: (-f["weight"], FACTOR_ORDER.index(f["key"])))
    na = [f for f in factors if f["state"] == "unavailable"]
    return [r(f) for f in fors], [r(f) for f in against], [r(f) for f in na]


def decide(sc: Dict[str, Any], plan: Dict[str, Any]) -> Tuple[str, List[str]]:
    """('pick' | 'wait' | 'no_trade', reasons). Thin or conflicting evidence, a score under the minimum, or a plan that says wait / no trade is not a pick."""
    o, why, no_trade = CFG["outcome"], [], False
    if sc["available_weight_pct"] < o["min_available_weight_pct"]:
        names = ", ".join(f["label"] for f in sc["factors"] if f["state"] == "unavailable")
        why.append(f"Thin evidence: only {sc['available_weight_pct']:g}% of the scoring weight could be read (at least {o['min_available_weight_pct']:g}% is needed). Unavailable: {names}.")
    n = sc["counts"]
    if n["conflicts"] >= o["min_conflicts"] and n["conflicts"] >= n["supports"]:
        no_trade = True
        why.append(f"Conflicting evidence: {n['conflicts']} factors conflict with the view and only {n['supports']} support it.")
    if sc["score"] < o["min_score"]:
        why.append(f"The evidence score {sc['score']:g} is under the minimum {o['min_score']:g}.")
    st = plan.get("status")
    if st != "plan":
        no_trade = no_trade or st == "no_trade"
        msgs = [r.get("message") for r in plan.get("status_reasons") or [] if r.get("message")][:3]
        why.append(f"The strategy plan says {st.replace('_', ' ')}" + (": " + " ".join(msgs) if msgs else "."))
    return ("no_trade" if no_trade else "wait" if why else "pick"), why


# ── building the response ────────────────────────────────────────────────────

def parse_passed(capital: Optional[str], risk_budget: Optional[str]) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    """({capital, risk_budget_inr} as numbers, problems): sizing inputs passed through to the plan builder, whose own validation decides the range."""
    passed: Dict[str, Any] = {}
    probs: List[Dict[str, str]] = []
    for key, raw in (("capital", capital), ("risk_budget_inr", risk_budget)):
        if raw is None:
            continue
        v = ev.num(raw)
        if v is None:
            probs.append({"field": key, "code": "bad_" + key, "message": f"{key} must be a number."})
        else:
            passed[key] = v
    if not probs:
        _, probs = normalise_inputs({"underlying": "TEMPLATE", "direction": "bullish", "instrument": "all", **passed})
    return passed, probs


def candidate_of(sym: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    scans = entry.get("scans") or []
    bull, bear = [s for s in scans if s.get("direction") == "bullish"], [s for s in scans if s.get("direction") == "bearish"]
    d = "long" if len(bull) > len(bear) else "short" if len(bear) > len(bull) else None
    return {"symbol": sym, "entry": entry, "direction": d, "aligned": len(bull) if d == "long" else len(bear) if d == "short" else len(bull),
            "directional": len(bull) + len(bear), "scans": scans}


def scans_view(c: Dict[str, Any]) -> Dict[str, Any]:
    want = {"long": "bullish", "short": "bearish"}.get(c["direction"])
    keep = lambda s: {k: s.get(k) for k in ("id", "name", "direction")}  # noqa: E731
    return {"aligned": [keep(s) for s in c["scans"] if want and s.get("direction") == want],
            "opposed": [keep(s) for s in c["scans"] if want and s.get("direction") in ("bullish", "bearish") and s.get("direction") != want],
            "count": len(c["scans"])}


def base_item(c: Dict[str, Any], setup: Optional[Dict[str, Any]], row: Dict[str, Any], name: Optional[str]) -> Dict[str, Any]:
    return {"rank": None, "symbol": c["symbol"], "name": name, "source": "both" if setup else "chartink", "in_ai_scanner": setup is not None,
            "ai_score": round(setup["score"], 1) if setup and setup.get("score") is not None else None, "direction": c["direction"], "action": ACTION.get(c["direction"]),
            "outcome": None, "score": None, "score_label": CFG["label"], "scans": scans_view(c), "factors": [], "available_weight_pct": None, "reasons_for": [],
            "reasons_against": [], "unavailable": [], "wait_reasons": [], "plan_id": None, "plan_status": None, "preferred": None, "strategies": [], "data_as_of": None,
            "fno_eligible": row.get("fno_eligible") if isinstance(row.get("fno_eligible"), bool) else None, "close": ev.num(row.get("close")), "plan_inputs": None}


async def evaluate(request: Request, user_id: str, c: Dict[str, Any], setup: Optional[Dict[str, Any]], row: Dict[str, Any], passed: Dict[str, Any], shared: Dict[str, Any],
                   sc_asof: Dict[str, Any], now: datetime, today: date) -> Dict[str, Any]:
    """The pick (or Wait / No trade) of one stock. Never raises: a stock whose sources fail is a Wait with the reason."""
    sym = c["symbol"]
    t0 = time.monotonic()
    out = base_item(c, setup, row, ev_text(row.get("name")) or ev_text(row.get("company_name")))
    d = "bullish" if c["direction"] == "long" else "bearish"
    out["plan_inputs"] = {**plan_body(sym, passed), "direction": d}
    try:
        plan_in, probs = normalise_inputs(out["plan_inputs"])
        if probs:
            raise ValueError("; ".join(p["code"] for p in probs))
        plan_in["live_broker_reads"] = False                        # picks never call a broker
        snap = (scanner_snapshot(sym, setup["bucket"], setup.get("watch_item"), setup.get("pick"), sc_asof["asof"], sc_asof["version"]) if setup else
                scanner_snapshot(sym, None, None, None, sc_asof["asof"], sc_asof["version"]))
        snaps, name = await asyncio.gather(collect_snapshots(request, user_id, plan_in, today, {**shared, "scanner_bucket": {sym: snap}}), company_name(sym))
        out["name"] = out["name"] or name
        plan = await asyncio.to_thread(build_plan, plan_in, snaps, now, today)
        sc = score_pick(d, c["entry"], snaps, plan["evidence"])
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001 — one stock failing must not lose the others: it becomes a Wait with the reason
        logger.warning("chartink picks: %s failed: %s", sym, e, exc_info=True)
        out.update(outcome="wait", wait_reasons=[f"The evidence for this stock could not be collected ({type(e).__name__}: {str(e)[:160]})."])
        return out
    fors, against, na = reasons(sc["factors"])
    outcome, why = decide(sc, plan)
    out.update(outcome=outcome, score=sc["score"], factors=sc["factors"], available_weight_pct=sc["available_weight_pct"], reasons_for=fors, reasons_against=against,
               unavailable=na, wait_reasons=why, plan_id=plan["plan_id"], plan_status=plan["status"], preferred=plan.get("preferred"), data_as_of=plan.get("data_as_of"),
               fno_eligible=fno_eligible(snaps), build_ms=int((time.monotonic() - t0) * 1000))
    if outcome == "pick":
        out["strategies"] = with_payoff_requests(strategies_of(plan, sym), plan)
    return out


PAYOFF_LEG_KEYS = ("kind", "side", "quantity", "lot_size", "entry_price", "expiry", "strike", "option_type", "price_source", "iv_pct")


def with_payoff_requests(strategies: List[Dict[str, Any]], plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Each strategy of the plan, plus `payoff_request`: the body that draws its payoff through POST /api/desk/strategy/payoff (the plan's own legs, its spot and
    its price grid; null for a strategy with no legs). The payoff itself is the payoff engine's, asked for by the screen when the row is opened."""
    cands = {c["id"]: c for c in plan.get("candidates") or []}
    spot, asof, costs = (plan.get("underlying") or {}).get("spot"), (plan.get("data_as_of") or {}).get("price"), (plan.get("inputs") or {}).get("costs")
    out = []
    for s in strategies:
        c = cands.get(s["id"]) or {}
        legs = [{k: l.get(k) for k in PAYOFF_LEG_KEYS} for l in c.get("legs") or []]
        grid = (((c.get("payoff") or {}).get("expiry")) or {}).get("grid") or []
        req = None
        if legs and spot is not None:
            req = {"underlying": plan["underlying"]["symbol"], "reference_price": spot, "legs": legs, **({"as_of": asof} if asof else {}),
                   **({"costs": costs} if costs else {}), **({"grid": {"min": grid[0], "max": grid[-1], "points": len(grid)}} if len(grid) > 1 else {})}
        out.append({**s, "payoff_request": req})
    return out


def ev_text(v: Any) -> Optional[str]:
    return v.strip() if isinstance(v, str) and v.strip() else None


def empty(limit: int, direction: str, now: datetime, index: Dict[str, Any]) -> Dict[str, Any]:
    ok = index.get("state") == "ok"
    return {"state": index.get("state"), "reason": index.get("reason"), "label": CFG["label"], "generated_at": now.isoformat(), "limit": limit, "direction_filter": direction,
            "dashboard_id": index.get("dashboard_id"), "rules_version": STRATEGY_RULES_VERSION, "calculation_version": CALCULATION_VERSION, "ranking_note": RANKING_NOTE,
            "data_as_of": {"mode": "end_of_day", "chartink": ({k: index.get(k) for k in ("scan_date", "fetched_at", "mode")} if ok else None), "price": None, "fno": None,
                           "scan_eligibility": None},
            "considered": 0, "evaluated": 0, "not_evaluated": 0, "qualified": 0, "returned": 0, "coverage_note": None, "picks": [], "wait": [], "excluded": [], "empty_reason": index.get("reason"),
            "shortfall_reason": None, "source_failures": [], "caveats": CAVEATS, "sent_to_broker": False}


def shortfall(out: Dict[str, Any], limit: int) -> Optional[str]:
    n = len(out["picks"])
    if n >= limit:
        return None
    parts = []
    if out["wait"]:
        parts.append(f"{len(out['wait'])} evaluated stock(s) are Wait / No trade: " + "; ".join(f"{w['symbol']} ({w['wait_reasons'][0].split(':')[0].rstrip('.')})" for w in out["wait"][:6]) + ".")
    if out["excluded"]:
        parts.append(f"{len(out['excluded'])} stock(s) failed the eligibility gates.")
    if out["not_evaluated"]:
        parts.append(f"{out['not_evaluated']} more were not evaluated (at most {CFG['evaluate_max']} per request, the most scans and the highest traded value first).")
    if not parts:
        parts.append("No other stock has a bullish or bearish Chartink scan hit.")
    return f"Only {n} of the {limit} asked qualified. " + " ".join(parts)


async def build_picks(request: Request, user_id: str, limit: int, direction: str, passed: Dict[str, Any], now: datetime, today: date) -> Dict[str, Any]:
    t0 = time.monotonic()
    index = await chartink_index(user_id, today)
    out = empty(limit, direction, now, index)
    if index.get("state") != "ok":
        return out
    symbols = index.get("symbols") or {}
    directional = [c for c in (candidate_of(sym, e) for sym, e in symbols.items()) if c["directional"]]
    cands = [c for c in directional if direction == "all" or c["direction"] == direction]
    out["considered"] = len(cands)
    if not cands:
        out["empty_reason"] = (f"Your enabled Chartink scans listed no stock on {index.get('scan_date')}." if not symbols else
                               "None of the listed stocks has a bullish or bearish scan hit (neutral-tagged scans give no direction)." if not directional else
                               f"No listed stock matches the direction filter ({direction}).")
        return out
    watch, picks_body, fails = await sel.read_scanner(request)
    rows, gate_as_of, gate_fail = await sel._gate_rows()
    out["source_failures"] = list(fails)
    out["data_as_of"]["scan_eligibility"] = gate_as_of
    if rows is None:
        out["empty_reason"] = f"The scan snapshot could not be read ({gate_fail}), so the eligibility gates cannot be tested and no stock is scored."
        out["source_failures"].append(f"scan snapshot: {gate_fail}")
        return out
    merged = {s["symbol"]: s for s in sel.merge_setups(watch, picks_body)} if (watch is not None or picks_body is not None) else {}
    ok, excluded = [], []
    for c in cands:
        row = rows.get(c["symbol"])
        code = "not_in_snapshot" if row is None else setup_rules.exclusion(row)
        if code:
            excluded.append({"symbol": c["symbol"], "code": code, "reason": "not in the scan snapshot, so the eligibility gates cannot be tested" if row is None else sel.EXCLUSION_TEXT.get(code, code)})
        else:
            ok.append((c, row))
    out["excluded"] = excluded

    def key(x):
        c, row = x
        return (-c["aligned"], -(sel._nonneg(row.get("traded_value_cr_20d")) or 0.0), c["symbol"])
    ok.sort(key=key)
    ties = [x for x in ok if x[0]["direction"] is None]
    todo = [x for x in ok if x[0]["direction"] is not None][:CFG["evaluate_max"]]
    out["not_evaluated"] = sum(1 for x in ok if x[0]["direction"] is not None) - len(todo)
    wait: List[Dict[str, Any]] = []
    for c, row in ties:
        w = base_item(c, merged.get(c["symbol"]), row, ev_text(row.get("name")) or ev_text(row.get("company_name")))
        w.update(outcome="wait", wait_reasons=["Both bullish and bearish scans listed it, as many each way: the scans conflict, so there is no direction to score."])
        wait.append(w)
    sc_asof = {"asof": (watch or {}).get("as_of_date") or (picks_body or {}).get("signal_date"), "version": (watch or {}).get("_classifier_version")}
    shared = await shared_for_ideas(user_id, index)
    sem = asyncio.Semaphore(CFG["concurrency"])

    async def one(c, row):
        async with sem:
            return await evaluate(request, user_id, c, merged.get(c["symbol"]), row, passed, shared, sc_asof, now, today)
    results = list(await asyncio.gather(*(one(c, row) for c, row in todo)))
    out["evaluated"] = len(results)
    order = lambda p: (-(p["score"] if p["score"] is not None else -1.0), -(len(p["scans"]["aligned"])), p["symbol"])  # noqa: E731
    qualified = sorted((p for p in results if p["outcome"] == "pick"), key=order)
    out["qualified"] = len(qualified)
    out["picks"] = qualified[:limit]
    for i, p in enumerate(out["picks"], 1):
        p["rank"] = i
    out["returned"] = len(out["picks"])
    out["wait"] = sorted(wait + [p for p in results if p["outcome"] != "pick"], key=order)
    prices = [p["data_as_of"]["price"] for p in results if p.get("data_as_of") and p["data_as_of"].get("price")]
    fnos = [p["data_as_of"]["fno"] for p in results if p.get("data_as_of") and p["data_as_of"].get("fno")]
    out["data_as_of"].update(price=max(prices) if prices else None, fno=max(fnos) if fnos else None)
    out["coverage_note"] = (f"Scored {out['evaluated']} of the {out['considered']} Chartink stocks with a bullish or bearish scan hit (the most scans first, then the highest traded value; "
                            f"at most {CFG['evaluate_max']} per request): {out['not_evaluated']} were not scored and {len(excluded)} failed the eligibility gates.")
    out["shortfall_reason"] = shortfall(out, limit)
    out["empty_reason"] = None if out["picks"] else (out["shortfall_reason"] or "No evaluated stock qualified.")
    out["elapsed_ms"] = int((time.monotonic() - t0) * 1000)
    return out
