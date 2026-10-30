"""StrategyPlan assembly (PRD §16.5, §16.9, §16.11, §17.5). Pure: inputs + source snapshots + a clock in, a JSON plan out.

The same inputs and the same snapshots always give the same plan (only `generated_at` differs): the plan id is a fingerprint of
the normalised inputs and of the snapshots' content. Nothing here reads a database or the network (`sources.py` does) and
nothing is sent to a broker (`sent_to_broker` is false everywhere).

Plan status (first-class, PRD §16.9):  plan | wait | no_trade | insufficient_data
    plan               at least one candidate is viable (preferred = highest net reward:risk at the conservative level;
                       a ranking, not a probability)
    wait               no viable candidate, but a candidate needs a confirmation or a fresher chain
    no_trade           every candidate is blocked by a rule (liquidity, event, reward:risk, conflicting evidence, ...)
    insufficient_data  nothing could be assessed (stale data, a failed required source, intraday horizon, no chain, unpriced legs)
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from . import candidates as cd
from . import evidence as ev
from .engine import CALCULATION_VERSION
from .rules import PLAN_SCHEMA, RULES, STRATEGY_RULES_VERSION

DIRECTIONS = ("bullish", "bearish", "neutral", "vol_expansion", "vol_contraction")
HORIZONS = ("intraday", "positional", "longer_term")
INSTRUMENTS = ("cash", "futures", "options", "combination", "all")
SYMBOL_RE = re.compile(r"^[A-Za-z0-9&\-]{1,20}$")

LIFECYCLE = {"status": "draft", "states": ["draft", "saved", "paper_traded", "reviewed", "expired", "invalidated", "closed"],
             "note": "A saved plan is a research record. No live order submission exists: sent_to_broker is false. The status a "
                     "reader sees is derived from the paper trades of its candidates' TradePlans (GET /api/desk/strategy/plans/{id})."}


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def digest(obj: Any, n: int = 16) -> str:
    return hashlib.sha256(canonical(obj).encode()).hexdigest()[:n]


# ── inputs (PRD §16.2) ───────────────────────────────────────────────────────

def _p(field: str, code: str, message: str) -> Dict[str, str]:
    return {"field": field, "code": code, "message": message}


def normalise_inputs(body: Any) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, str]]]:
    """(inputs, problems). Defaults are filled in and named in `defaults_applied` so they are disclosed and changeable."""
    probs: List[Dict[str, str]] = []
    if not isinstance(body, dict):
        return None, [_p("body", "bad_body", "The request must be a JSON object.")]
    D = RULES["defaults"]
    applied: List[str] = []
    sym = body.get("underlying")
    if not isinstance(sym, str) or not SYMBOL_RE.match(sym.strip()):
        probs.append(_p("underlying", "bad_underlying", "underlying must be an NSE symbol (letters, digits, & or -; at most 20)."))
    direction = body.get("direction")
    if direction not in DIRECTIONS:
        probs.append(_p("direction", "bad_direction", "direction must be one of " + ", ".join(DIRECTIONS) + "."))
    horizon = body.get("horizon", "positional")
    if "horizon" not in body:
        applied.append("horizon")
    if horizon not in HORIZONS:
        probs.append(_p("horizon", "bad_horizon", "horizon must be one of " + ", ".join(HORIZONS) + "."))
    instrument = body.get("instrument", "all")
    if "instrument" not in body:
        applied.append("instrument")
    if instrument not in INSTRUMENTS:
        probs.append(_p("instrument", "bad_instrument", "instrument must be one of " + ", ".join(INSTRUMENTS) + "."))

    def number(key: str, lo: float, hi: float, default: Optional[float] = None, inclusive_lo: bool = False) -> Optional[float]:
        if body.get(key) is None:
            if default is not None:
                applied.append(key)
            return default
        v = ev.num(body[key])
        if v is None or v > hi or (v < lo if inclusive_lo else v <= lo):
            probs.append(_p(key, "bad_" + key, f"{key} must be a number {'from' if inclusive_lo else 'above'} {lo:g} and at most {hi:g}."))
            return None
        return v

    hd = body.get("horizon_days")
    if hd is None:
        hdays = D["horizon_days"].get(horizon) if horizon in HORIZONS else None
        applied.append("horizon_days")
    else:
        hdays = ev.num(hd)
        if hdays is None or hdays != int(hdays) or not 1 <= hdays <= 250:
            probs.append(_p("horizon_days", "bad_horizon_days", "horizon_days must be a whole number from 1 to 250."))
            hdays = None
        else:
            hdays = int(hdays)
    capital = number("capital", 0, 1e12)
    risk_budget = number("risk_budget_inr", 0, 1e12)
    risk_pct = number("risk_pct", 0, 100)
    alloc = number("max_allocation_pct", 0, 100, D["max_allocation_pct"])
    min_rr = number("min_reward_risk", 0, 100, D["min_reward_risk"])
    flags = {}
    for key in ("avoid_events", "allow_multi_leg", "include_combinations"):
        if body.get(key) is None:
            flags[key] = D[key]
            applied.append(key)
        elif isinstance(body[key], bool):
            flags[key] = body[key]
        else:
            probs.append(_p(key, "bad_" + key, f"{key} must be true or false."))
            flags[key] = D[key]
    if body.get("include_chartink") is None:
        include_chartink = RULES["chartink"]["include_default"]
        applied.append("include_chartink")
    elif isinstance(body["include_chartink"], bool):
        include_chartink = body["include_chartink"]
    else:
        probs.append(_p("include_chartink", "bad_include_chartink", "include_chartink must be true or false."))
        include_chartink = RULES["chartink"]["include_default"]
    if body.get("live_broker_reads") is None:
        live_reads_on = False
        applied.append("live_broker_reads")
    elif isinstance(body["live_broker_reads"], bool):
        live_reads_on = body["live_broker_reads"]
    else:
        probs.append(_p("live_broker_reads", "bad_live_broker_reads", "live_broker_reads must be true or false."))
        live_reads_on = False
    expiry = body.get("expiry")
    if expiry is not None and ev.day10(expiry) is None:
        probs.append(_p("expiry", "bad_expiry", "expiry must be YYYY-MM-DD."))
        expiry = None
    costs = None
    if body.get("costs") is not None:
        c = body["costs"]
        if not isinstance(c, dict):
            probs.append(_p("costs", "bad_costs", "costs must be an object."))
        else:
            costs = {}
            for key, hi in (("slippage_pct", 5.0), ("brokerage_per_side", 100000.0)):
                if c.get(key) is not None:
                    v = ev.num(c[key])
                    if v is None or v < 0 or v > hi:
                        probs.append(_p("costs." + key, "bad_cost", f"{key} must be a number from 0 to {hi:g}."))
                    else:
                        costs[key] = v
    if probs:
        return None, probs
    return {"underlying": sym.strip().upper(), "direction": direction, "horizon": horizon, "horizon_days": hdays, "instrument": instrument,
            "capital": capital, "risk_budget_inr": risk_budget, "risk_pct": risk_pct, "max_allocation_pct": alloc,
            "min_reward_risk": min_rr, "avoid_events": flags["avoid_events"], "allow_multi_leg": flags["allow_multi_leg"],
            "include_combinations": flags["include_combinations"], "include_chartink": include_chartink, "live_broker_reads": live_reads_on, "expiry": expiry, "costs": costs, "defaults_applied": sorted(applied)}, []


# ── context ──────────────────────────────────────────────────────────────────

def build_ctx(inputs: Dict[str, Any], snaps: Dict[str, Any], today: date) -> Dict[str, Any]:
    ind = ev.snap(snaps, "indicators")
    vals = ((ind["data"] or {}).get("values") or {}) if ind["ok"] else {}
    hyp = ((ind["data"] or {}).get("hypothetical_levels") or None) if ind["ok"] else None
    dates = [ev.snap(snaps, k)["as_of"] for k in ("indicators", "scan_row", "buildup", "futures") if ev.snap(snaps, k)["ok"]]
    dates = [x for x in dates if x]
    sb, sr = ev.snap(snaps, "scanner_bucket"), ev.snap(snaps, "scan_row")
    as_of = ind["as_of"] if ind["ok"] else None
    return {"symbol": inputs["underlying"], "direction": inputs["direction"], "inputs": inputs, "snaps": snaps, "today": today,
            "as_of": as_of, "ref_session": max(dates) if dates else None,
            "spot": ev.num(vals.get("close")), "spot_source": f"nidp.prices_eod_adjusted close, {as_of}", "atr": ev.num(vals.get("atr14")),
            "support": ev.num(vals.get("support20")), "resistance": ev.num(vals.get("resistance20")), "ema20": ev.num(vals.get("ema20")),
            "hyp": hyp, "scan_rules_version": sb["version"] or sr["version"],
            "expiry_why": (ev.snap(snaps, "chain")["data"] or {}).get("expiry_why") if ev.snap(snaps, "chain")["ok"] else None}


# ── gates ────────────────────────────────────────────────────────────────────

def is_unknown_symbol(error: Any) -> bool:
    """The price source answered 404 no_bars_for_symbol: the symbol has no bars at all (a real outage is a 5xx or a timeout)."""
    e = str(error or "")
    return "HTTP 404" in e and "no_bars_for_symbol" in e


def global_reasons(inputs: Dict[str, Any], snaps: Dict[str, Any], ctx: Dict[str, Any], ledger: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Plan-level blockers. kind 'data' -> insufficient_data, 'rule' -> no_trade."""
    out: List[Dict[str, Any]] = []
    R = cd.reason
    if inputs["horizon"] == "intraday":
        out.append({**R("intraday_not_supported", "An intraday horizon needs intraday bars and order-book data; this system holds end-of-day data only (PRD §17.2 #2, #3)."), "kind": "data"})
    ind = ev.snap(snaps, "indicators")
    if not ind["ok"] and is_unknown_symbol(ind["error"]):
        out.append({**R("unknown_symbol", f"No price history for {inputs['underlying']}: the data platform holds no end-of-day bars under that symbol."), "kind": "data"})
    elif not ind["ok"]:
        out.append({**R("required_source_failed", f"The price history (required) could not be read: {ind['error']}"), "kind": "data"})
    elif ctx["as_of"]:
        age = (ctx["today"] - date.fromisoformat(ctx["as_of"])).days
        if age > RULES["stale_after_calendar_days"]:
            out.append({**R("stale_data", f"The latest price is from {ctx['as_of']}, {age} days before {ctx['today']}: stale (limit {RULES['stale_after_calendar_days']} days)."), "kind": "data"})
    sr = ev.snap(snaps, "scan_row")
    tv = ev.num((sr["data"] or {}).get("traded_value_cr_20d")) if sr["ok"] else None
    if tv is None and ind["ok"]:
        tv = ev.num(((ind["data"] or {}).get("values") or {}).get("avg_traded_value_cr20"))
    gate = RULES["liquidity_min_traded_value_cr"]
    if ind["ok"] and tv is None:
        out.append({**R("liquidity_unknown", "The 20-session average traded value could not be worked out, so the liquidity gate cannot be tested."), "kind": "data"})
    elif tv is not None and tv < gate:
        out.append({**R("liquidity_below_gate", f"Average traded value {tv:g} Cr a day is below the {gate:g} Cr liquidity gate.", traded_value_cr=tv, gate_cr=gate), "kind": "rule"})
    inside = ev.events_in_horizon(snaps, ctx["as_of"], inputs["horizon_days"])
    res = [e for e in inside if e.get("event_type") == "quarterly_results"]
    if res and inputs["avoid_events"]:
        out.append({**R("event_in_horizon", f"Results are scheduled on {ev.day10(res[0]['event_date'])}, inside the {inputs['horizon_days']}-day horizon, and the plan is set to avoid events."
                        + (" (avoid_events is on by default; change it in the inputs.)" if "avoid_events" in inputs["defaults_applied"] else "")), "kind": "rule"})
    C = RULES["conflict"]
    sm = ledger["summary"]
    conflicts = sum(sm[g]["conflicts"] for g in C["groups"])
    supports = sum(sm[g]["supports"] for g in C["groups"])
    if inputs["direction"] in ("bullish", "bearish") and conflicts >= C["min_conflicts"] and conflicts >= supports:
        out.append({**R("conflicting_evidence", f"{conflicts} items conflict with the {inputs['direction']} view against {supports} that support it (rule: at least {C['min_conflicts']} conflicts and at least as many as supports, in {', '.join(C['groups'])})."), "kind": "rule"})
    return out


WOULD_CHANGE = {
    "stale_data": "A price from the last completed session.",
    "required_source_failed": "The price history source answering.",
    "unknown_symbol": "An NSE symbol with price history on record: use one of the suggestions, or check the ticker.",
    "intraday_not_supported": "A positional horizon, or intraday data being added to the platform.",
    "liquidity_below_gate": "Average traded value rising to at least the gate.",
    "liquidity_unknown": "20 sessions of price and volume on record.",
    "event_in_horizon": "The results date passing, a shorter horizon, or switching avoid_events off (accepting event risk).",
    "conflicting_evidence": "The conflicting items (see the ledger) turning, or a different view.",
    "reward_risk_below_minimum": "A nearer stop, a farther conservative level, or a lower minimum reward : risk.",
    "setup_not_triggered": "A close above the trigger on volume (the scanner moving it to breakout confirmed).",
    "no_setup": "The scanner listing the stock in one of its buckets.",
    "no_fresh_buildup": "A fresh build-up (price and open interest rising together for a long view).",
    "cash_not_confirming": "The cash market moving the same way as the futures.",
    "buildup_opposes_view": "A build-up in the direction of the view.",
    "stale_chain": "The F&O data for the last completed session being loaded.",
    "no_valid_chain": "An option chain for a listed expiry being available.",
    "legs_unpriced": "Every leg having a closing price.",
    "illiquid_leg": "The legs having open interest and trading volume.",
    "condor_rule_fails": "The price sitting inside both walls with each at least one expected move away.",
    "sizing_zero": "A larger risk budget or allocation cap.",
    "risk_not_calculable": "A valid stop and payoff being derivable.",
    "payoff_invalid": "A valid payoff calculation.",
    "scanner_unavailable": "The scanner source answering.",
    "buildup_unavailable": "The F&O build-up source answering.",
    "futures_unavailable": "The futures source answering.",
    "lot_size_unknown": "The lot size being in the data.",
    "future_unpriced": "A futures contract with a settle price.",
    "no_short_strike": "A wall or an expected move giving a short strike.",
    "no_atm_strike": "The chain having a spot.",
}


# ── plan ─────────────────────────────────────────────────────────────────────

STATUS_RANK = {"candidate": 0, "wait": 1, "no_trade": 2, "avoid": 2, "insufficient_data": 3}


def _evidence_quality(ledger: Dict[str, Any], segment: str) -> Dict[str, Any]:
    groups = {"cash": ("technical", "fundamental"), "futures": ("technical", "derivatives"), "options": ("technical", "derivatives"),
              "combination": ("technical", "fundamental", "derivatives")}[segment]
    sm = ledger["summary"]
    tot = {k: sum(sm[g][k] for g in groups) for k in ev.DIRECTIONS}
    n = sum(tot.values()) or 1
    label = "thin" if tot["unavailable"] / n >= 0.5 else "partial" if tot["unavailable"] / n >= 0.2 else "complete"
    return {"groups": list(groups), **tot, "label": label}


def _unfloored(c: Dict[str, Any]) -> bool:
    """A combination that holds shares or a future long with no long put under them (the covered call): its expiry worst case is the
    price at zero, while the plan exits at its stop (sizing and reward : risk already use the loss there)."""
    legs = c.get("legs") or []
    holds = any(l.get("kind") in ("cash", "future") and l.get("side") == "buy" for l in legs)
    put = any(l.get("kind") == "option" and l.get("side") == "buy" and l.get("option_type") == "put" for l in legs)
    return c["segment"] == "combination" and holds and not put


def _comparison(cands: List[Dict[str, Any]], ledger: Dict[str, Any], horizon_days: int) -> List[Dict[str, Any]]:
    rows = []
    for c in cands:
        res = c.get("payoff") or {}
        ex = res.get("expiry") or {}
        rr = c.get("risk_reward") or {}
        linear = c["segment"] in ("cash", "futures")
        unfloored = _unfloored(c)
        flags = (c.get("options_selection") or {}).get("preferred_flags") or []
        if linear:
            max_loss = rr.get("risk_net")
            basis = "loss at the stop (net); gaps can exceed it" + ("; futures losses can exceed margin" if c["segment"] == "futures" else "")
        elif unfloored:
            # A premium that covers the loss at the stop is a loss of 0 there, not a negative loss.
            max_loss = None if rr.get("risk_net") is None else max(rr["risk_net"], 0.0)
            to_zero = ex.get("max_loss")
            basis = ("loss at the stop (net), where the plan exits; gaps can exceed it, and below the stop nothing limits the loss"
                     + (f" (held to expiry, {abs(to_zero):,.2f} gross if the price falls to zero)" if to_zero is not None else ""))
        else:
            max_loss = ex.get("max_loss")
            basis = "defined max loss at expiry (gross)" + ("; for a structure that holds shares or a future this is the loss if the price falls to the long put's strike" if c["segment"] == "combination" else "")
        rows.append({
            "id": c["id"], "segment": c["segment"], "family": c["family"], "label": c["label"], "status": c["status"],
            "max_loss": max_loss, "max_loss_basis": basis, "max_loss_at": "stop" if linear or unfloored else "expiry",
            "capital_at_risk": res.get("capital_at_risk"),
            "breakeven": ex.get("breakevens"), "reward_risk_net": rr.get("net"), "reward_risk_gross": rr.get("gross"),
            "liquidity_flags": flags, "horizon_days": horizon_days, "evidence_quality": _evidence_quality(ledger, c["segment"]),
            "why_unsuitable": None if c["status"] == "candidate" else "; ".join(r["message"] for r in c["reasons"]) or c["status"],
        })
    return rows


def _headline(ledger: Dict[str, Any], snaps: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    items, sm = ledger["items"], ledger["summary"]
    t = sm["technical"]
    n = sum(t.values())
    label = ("unavailable" if t["unavailable"] == n else "partial" if t["unavailable"] / max(n, 1) >= 0.5 else
             "supportive" if t["supports"] >= t["conflicts"] + 2 else "conflicting" if t["conflicts"] > t["supports"] else "mixed")
    sb = ev.snap(snaps, "scanner_bucket")
    fund = {i["key"]: i["value"] for i in items if i["group"] == "fundamental" and i["direction"] != "unavailable" and i["key"] != "valuation_vs_peers"}
    miss = [i["key"] for i in items if i["group"] == "fundamental" and i["direction"] == "unavailable"]
    unavailable_keys = [f"{i['group']}.{i['key']}" for i in items if i["direction"] == "unavailable"]
    total = len(items)
    ratio = len(unavailable_keys) / total if total else 1.0
    return {
        "technical_setup": {"label": label, "counts": t, "scanner_bucket": (sb["data"] or {}).get("bucket") if sb["ok"] else None,
                            "note": "A qualitative reading of the technical items for the chosen direction; not a score and not a probability."},
        "fundamental_context": {"role": "context only (valuation, quality, catalysts); not a trigger for a short-horizon trade",
                                "available": fund, "missing": miss, "valuation_vs_peers": next((i["value"] for i in items if i["key"] == "valuation_vs_peers" and i["direction"] != "unavailable"), None)},
        "model_estimate": {"status": "withheld", "reason": RULES["model_estimate"], "value": None},
        "data_quality": {"label": "poor" if ratio >= 0.5 else "partial" if ratio >= 0.2 else "complete", "unavailable_items": len(unavailable_keys),
                         "total_items": total, "unavailable": unavailable_keys, "mode": "end_of_day", "price_as_of": ctx["as_of"],
                         "reference_session": ctx["ref_session"]},
        "confidence": None,
        "confidence_note": "No single confidence number is produced: the four fields above are reported separately (PRD §16.9).",
    }


def _failure_conditions(cands: List[Dict[str, Any]], inputs: Dict[str, Any]) -> List[str]:
    out = [f"Stale data: a price older than {RULES['stale_after_calendar_days']} calendar days, or an F&O chain older than the last completed session, means wait.",
           f"Liquidity: average traded value below {RULES['liquidity_min_traded_value_cr']:g} Cr a day, or a leg with no open interest or volume, means no trade.",
           f"Event risk: results inside the horizon" + (" (the plan avoids them)." if inputs["avoid_events"] else " are accepted by the inputs; expect gap risk."),
           f"Reward : risk below {inputs['min_reward_risk']:g} (at the nearest resistance when one caps the move, else at the base level) means no trade.",
           "Failed confirmation: for a long idea, a close back below the trigger or the invalidation level cancels it."]
    for c in cands:
        inv = (c.get("invalidation") or {}).get("technical") or {}
        if inv.get("price"):
            out.append(f"{c['label']}: invalid on a close beyond {inv['price']:g} ({inv.get('basis')}).")
    return out


def _would_change(reasons: List[Dict[str, Any]]) -> List[str]:
    seen, out = set(), []
    for r in reasons:
        t = WOULD_CHANGE.get(r["code"])
        if t and t not in seen:
            seen.add(t)
            out.append(f"{r['code']}: {t}")
    return out


EOD_CAVEAT = "End-of-day data: nothing here is live. F&O data is one NSE bhavcopy per day."
LIVE_CAVEAT = ("Prices, the option chain and the F&O data are end of day (one NSE bhavcopy per day). Only the broker bid/ask quotes marked live or delayed "
               "are read from the user's own broker session, read-only.")
MARGIN_CAVEAT = ("Margin is not estimated by the plan: it comes only from Zerodha's margin calculator, which needs a live Kite session. "
                 "Margin is not the maximum loss.")
MARGIN_LIVE_CAVEAT = ("Margin shown is an estimate from Zerodha's margin calculator, read-only; no order is placed. It covers these legs alone "
                      "and is not the maximum loss.")


def caveats(snaps: Dict[str, Any]) -> List[str]:
    q = ev.snap(snaps, "broker_quotes")
    live = q["ok"] and bool((q["data"] or {}).get("quotes"))
    return ["Conditional research plan, not advice and not an instruction to trade.", LIVE_CAVEAT if live else EOD_CAVEAT,
            "Payoff figures are calculations at the prices shown, not forecasts; taxes, statutory charges, dividends and funding are excluded.",
            MARGIN_CAVEAT, "Nothing is sent to a broker."]


def _snapshot_refs(snaps: Dict[str, Any]) -> List[Dict[str, Any]]:
    refs = []
    for k in sorted(snaps):
        s = snaps[k]
        if not isinstance(s, dict) or "ok" not in s:
            continue
        refs.append({"key": k, "source": s.get("source"), "as_of": s.get("as_of"), "version": s.get("version"), "ok": s["ok"], "error": s.get("error"),
                     "content_hash": digest(s.get("data")) if s["ok"] else None})
    return refs


def plan_sources(snaps: Dict[str, Any]) -> List[str]:
    """Which opportunity sources list the stock: `ai_scanner` (a scanner bucket or pick) and/or `chartink` (an enabled scan of the user's dashboard)."""
    out: List[str] = []
    sb, ck = ev.snap(snaps, "scanner_bucket"), ev.snap(snaps, "chartink")
    if sb["ok"] and ((sb["data"] or {}).get("bucket") or (sb["data"] or {}).get("pick_stage")):
        out.append("ai_scanner")
    if ck["ok"] and (ck["data"] or {}).get("hits"):
        out.append("chartink")
    return out


def build_plan(inputs: Dict[str, Any], snaps: Dict[str, Any], now: datetime, today: date) -> Dict[str, Any]:
    ctx = build_ctx(inputs, snaps, today)
    ledger = ev.build_ledger(snaps, inputs, ctx["as_of"], ctx["ref_session"])
    gates = global_reasons(inputs, snaps, ctx, ledger)
    data_blocked = any(g["kind"] == "data" and g["code"] in ("required_source_failed", "unknown_symbol", "intraday_not_supported") for g in gates)
    cands = [] if data_blocked else cd.generate(ctx)
    # plan-level blockers override every candidate that was still alive
    for c in cands:
        for g in gates:
            r = {k: v for k, v in g.items() if k != "kind"}
            if g["kind"] == "data" and c["status"] != "insufficient_data":
                c["status"] = "insufficient_data"
                c["reasons"].append(r)
            elif g["kind"] == "rule" and g["code"] == "event_in_horizon" and c.get("event_hedged"):
                if c["status"] in ("candidate", "wait"):
                    c["warnings"].append("Results are scheduled inside the horizon. The long put defines the downside, so the event does not block this structure: "
                                         "the loss cannot exceed the max loss shown, and the put's premium already reflects the event.")
            elif g["kind"] == "rule" and c["status"] in ("candidate", "wait"):
                c["status"] = "no_trade"
                c["reasons"].append(r)
            elif g["kind"] == "rule" and g["code"] == "event_in_horizon":
                c["reasons"].append(r)
        if not inputs["avoid_events"] and c["status"] == "candidate":
            if ev.events_in_horizon(snaps, ctx["as_of"], inputs["horizon_days"]):
                c["warnings"].append("An event is scheduled inside the horizon and avoid_events is off: gap risk is accepted.")
        c["actionable"] = c["status"] == "candidate" and not (c.get("options_selection") or {}).get("stale")
    viable = [c for c in cands if c["status"] == "candidate"]
    viable.sort(key=lambda c: (-(c["risk_reward"].get("net") if c["risk_reward"].get("net") is not None else c["risk_reward"].get("gross") or -1e9), c["id"]))
    reasons_all: List[Dict[str, Any]] = [{k: v for k, v in g.items() if k != "kind"} for g in gates]
    for c in cands:
        reasons_all += c["reasons"]
    if viable:
        status = "plan"
    elif not cands or any(g["kind"] == "data" for g in gates):
        status = "insufficient_data"
    elif any(g["kind"] == "rule" for g in gates):
        status = "no_trade"
    else:
        sts = {c["status"] for c in cands}
        status = "wait" if "wait" in sts else "no_trade" if sts & {"no_trade", "avoid"} else "insufficient_data"
    status_reasons = [] if status == "plan" else _dedupe(reasons_all)
    preferred = viable[0] if viable else None
    sm = ledger["summary"]
    supports = [{"group": i["group"], "key": i["key"], "interpretation": i["interpretation"]} for i in ledger["items"] if i["direction"] == "supports"]
    conflicts = [{"group": i["group"], "key": i["key"], "interpretation": i["interpretation"]} for i in ledger["items"] if i["direction"] == "conflicts"]
    ref_target = preferred or next((c for c in cands if c["targets"]), None)
    scenarios = {"basis": "Scenario levels for the graph from documented rules (rules.targets); each is an underlying price, not a forecast.",
                 "horizon_days": inputs["horizon_days"], "origin": {"as_of": ctx["as_of"], "price": ctx["spot"], "source": ctx["spot_source"]},
                 "levels": ref_target["targets"] if ref_target else [], "from_candidate": ref_target["id"] if ref_target else None,
                 "model_path": {"status": "unavailable", "reason": "No validated price-path model exists, so no projected path or fan is drawn; only the scenario levels above."},
                 "label": "scenarios, not forecasts"}
    refs = _snapshot_refs(snaps)
    inputs_hash = digest(inputs, 32)
    plan_id = "plan_" + digest({"inputs": inputs, "snapshots": refs, "rules": STRATEGY_RULES_VERSION})
    fno_day = next((s["as_of"] for s in (ev.snap(snaps, "chain"), ev.snap(snaps, "buildup"), ev.snap(snaps, "futures")) if s["ok"] and s["as_of"]), None)
    data_as_of = {"price": ctx["as_of"], "fno": fno_day, "reference_session": ctx["ref_session"], "mode": "end_of_day",
                  "fundamentals": ev.snap(snaps, "features")["as_of"], "regime": ev.snap(snaps, "regime")["as_of"]}
    plan = {
        "plan_id": plan_id, "schema": PLAN_SCHEMA, "rules_version": STRATEGY_RULES_VERSION, "calculation_version": CALCULATION_VERSION,
        "generated_at": now.isoformat(), "data_as_of": data_as_of,
        "inputs": inputs, "inputs_hash": inputs_hash, "rules": RULES,
        "underlying": {"symbol": inputs["underlying"], "spot": ctx["spot"], "spot_as_of": ctx["as_of"], "spot_source": ctx["spot_source"]},
        "status": status, "status_reasons": status_reasons,
        "would_change_if": _would_change(status_reasons) if status != "plan" else _would_change([r for c in cands for r in c["reasons"]]),
        "summary": {"underlying": inputs["underlying"], "segment": inputs["instrument"], "direction": inputs["direction"], "horizon": inputs["horizon"],
                    "horizon_days": inputs["horizon_days"], "family": preferred["family"] if preferred else None,
                    "preferred_segment": preferred["segment"] if preferred else None, "status": status, "generated_at": now.isoformat(),
                    "data_as_of": ctx["as_of"], "end_of_day": True, "sources": plan_sources(snaps)},
        "thesis": {"direction": inputs["direction"], "supports": supports, "conflicts": conflicts,
                   "unavailable": [f"{i['group']}.{i['key']}" for i in ledger["items"] if i["direction"] == "unavailable"],
                   "note": "Only the evidence that applies to the chosen direction; fundamentals are context, not a short-horizon trigger (PRD §16.8)."},
        "evidence": ledger["items"], "evidence_summary": sm,
        "headline": _headline(ledger, snaps, ctx),
        "candidates": cands, "preferred": preferred["id"] if preferred else None,
        "ranking": "Viable candidates are ordered by net reward : risk at the conservative level. It is a ranking, not a probability.",
        "alternatives": _comparison(cands, ledger, inputs["horizon_days"]),
        "failure_conditions": _failure_conditions(cands, inputs),
        "validation": ledger["validation"], "scenarios": scenarios, "lifecycle": dict(LIFECYCLE),
        "source_snapshots": refs,
        "caveats": caveats(snaps),
        "sent_to_broker": False,
    }
    # Phase 2.1: every candidate with levels carries its canonical TradePlan (trade_plan.py), the one object every
    # surface and the paper-trade route read by id. Built from the candidate; nothing is recomputed.
    from . import trade_plan as tpm
    tps = tpm.from_plan(plan, today)
    for c in cands:
        c["trade_plan"] = tps.get(c["id"])
    plan["trade_plans"] = {cid: tp["plan_id"] for cid, tp in tps.items()}
    return plan


def _dedupe(rs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen, out = set(), []
    for r in rs:
        k = (r["code"], r["message"])
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


# ── Copilot grounding (PRD §6.9, §17.1) ──────────────────────────────────────

def explain_plan_context(plan: Dict[str, Any], saved_id: Optional[str] = None, saved_at: Optional[str] = None) -> str:
    """A compact text block of a saved plan for the Copilot to quote: the exact plan id, versions and data snapshot, then the
    status, the candidates' exact legs and figures. Read-only; nothing here is new analysis."""
    L: List[str] = []
    s = plan.get("summary", {})
    L.append(f"STRATEGY PLAN {plan.get('plan_id')}" + (f" (saved id {saved_id}, saved {saved_at})" if saved_id else ""))
    L.append(f"{s.get('underlying')} · view {s.get('direction')} · horizon {s.get('horizon')} ({s.get('horizon_days')} days) · instruments {s.get('segment')}")
    L.append(f"Status: {plan.get('status')}" + (f" · preferred {plan.get('preferred')}" if plan.get("preferred") else ""))
    L.append(f"Versions: rules {plan.get('rules_version')}, calculation {plan.get('calculation_version')}, schema {plan.get('schema')}")
    d = plan.get("data_as_of", {})
    L.append(f"Data: price as of {d.get('price')}, F&O as of {d.get('fno')} (end of day, not live). Generated {plan.get('generated_at')}. Inputs hash {plan.get('inputs_hash')}.")
    for r in plan.get("status_reasons", []):
        L.append(f"Reason [{r.get('code')}]: {r.get('message')}")
    h = plan.get("headline", {})
    L.append(f"Technical setup: {h.get('technical_setup', {}).get('label')} · model estimate: {h.get('model_estimate', {}).get('status')} · data quality: {h.get('data_quality', {}).get('label')}")
    for c in plan.get("candidates", []):
        L.append(f"- {c['id']} [{c['status']}] {c['label']}")
        for lg in c.get("legs", []):
            tail = f" {lg['option_type']} {lg['strike']:g}" if lg.get("option_type") else ""
            L.append(f"    leg: {lg['side']} {lg['quantity']} x {lg['kind']}{tail} @ {lg['entry_price']} (lot {lg['lot_size']}, {lg.get('expiry')}); source {lg.get('price_source')}")
        rr = c.get("risk_reward") or {}
        if rr.get("net") is not None or rr.get("gross") is not None:
            L.append(f"    reward:risk gross {rr.get('gross')} net {rr.get('net')}")
        ex = ((c.get("payoff") or {}).get("expiry")) or {}
        if ex:
            L.append(f"    max profit {ex.get('max_profit')} max loss {ex.get('max_loss')} breakevens {ex.get('breakevens')} (calculation {(c.get('payoff') or {}).get('calculation_version')})")
        for t in c.get("targets", []):
            L.append(f"    {t['name']} level {t['price']} ({t['rule']})")
        for r in c.get("reasons", []):
            L.append(f"    reason [{r.get('code')}]: {r.get('message')}")
    L.append("Validation: " + str(plan.get("validation", {}).get("status")) + " (" + "; ".join(plan.get("validation", {}).get("reasons", [])[:1]) + ")")
    L.append("Quote these figures exactly; do not invent strikes, prices or P&L. Nothing was sent to a broker.")
    return "\n".join(L)
