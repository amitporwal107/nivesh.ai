"""Reversal candidates near the 52-week low: every threshold, its version, and the pure functions that apply them.

Same contract as setup_rules.py (PRD §5.6): thresholds are configurable and versioned here, never in a screen. Change a
number and bump RULES_VERSION in the same commit.

What this is and is not
* Being near the 52-week low is NOT a signal. It only admits a stock to the candidate pool. A stock becomes a reversal
  candidate when enough independent stabilization evidence is true (CANDIDATE.min_core_true of the core signals).
* The 0-100 opportunity score is RULE-BASED, with hypothesis weights (WEIGHTS) that have not been tuned or proven. It is
  not a probability and not a calibrated model output (PRD §5.3).
* A component without data is None (unknown). It is left out of the total, the total is renormalised over the known
  weights, and `coverage_pct` says how much of the 100 points was actually scored. It is never counted as 0 or as neutral.
* Hard gates beat the score: a critical risk excludes the stock or raises a prominent warning however high the total is.
* Research / paper-trading only: entry, invalidation and target are hypothetical scenarios, never orders.

Input row (see `evaluate`): one dict per stock with `symbol`, `bars` (oldest first: d, o, h, l, c, v), optional
`index_closes` (the benchmark's closes on the same dates, oldest first), `traded_value_cr_20d`, `sector`, `sector_ctx`,
`fundamentals`, `announcements`, `next_results_date`, and the scanner's own `eligible` / `exclusion`.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

RULES_VERSION = "reversal-rules.v1 (2026-10-20)"

NEAR_LOW: Dict[str, Any] = {
    "window_sessions": 252,
    "default_pct": 15.0,          # owner decision 2026-10-20
    "research_pct": 20.0,         # configurable research threshold
    "sensitivity_pcts": [10.0, 15.0, 20.0],
    "formula": "distance_from_52w_low_pct = (close / lowest low of the last 252 sessions - 1) x 100",
}

# Hypothesis weights from the product brief; NOT tuned. Must sum to 100.
WEIGHTS: Dict[str, float] = {"sector": 20.0, "technical": 25.0, "momentum": 15.0, "fundamental": 20.0,
                             "catalyst": 10.0, "valuation_risk": 10.0}
STAGE1 = ("sector", "fundamental", "catalyst", "valuation_risk")   # is the business/sector worth investigating
STAGE2 = ("technical", "momentum")                                 # is there a defined setup now

# Stabilization evidence. Each signal is True / False / None (unknown) with the observed value shown.
SIGNALS: Dict[str, Any] = {
    "low_not_new_min_sessions": 5,        # the 52w low was made at least this many sessions ago
    "higher_low_recent": 10,              # lowest low of the last N sessions ...
    "higher_low_prior": [11, 30],         # ... above the lowest low of sessions N+1..30 back
    "rsi_min": 40.0,                      # RSI(14) recovering: at least this and above its value 5 sessions ago
    "rsi_lookback": 5,
    "ema_fast": 20, "ema_slow": 50,
    "rs_lookback": 20,                    # stock 20-session return minus benchmark's (RS > 0)
    "volume_sessions": 10,                # up-day volume exceeds down-day volume over the last N sessions
    "roc_short": 5, "roc_medium": 20,
}
CORE_SIGNALS = ("higher_low", "low_not_new", "rsi_recovery", "ema20_reclaim", "rs_vs_index", "volume_participation")

CANDIDATE: Dict[str, Any] = {"min_core_true": 3, "min_core_known": 4}

LEVELS: Dict[str, Any] = {
    "resistance_sessions": 20,            # highest high of the 20 sessions before the last
    "invalidation_prior_sessions": 10,    # lowest low of the 10 sessions before the last ...
    "invalidation_atr_buffer": 0.5,       # ... minus this many ATR(14)
    "target_sessions": 60,                # hypothetical target: the 60-session high
    "trigger_ready_within_pct": 3.0,      # close within this far below resistance
    "confirmed_rvol_min": 1.5,            # breakout day volume / mean of the 20 sessions before
    "min_reward_risk": 1.5,               # below this a setup cannot be trigger_ready or confirmed
}

GATES: Dict[str, Any] = {
    "min_traded_value_cr": 10.0,          # same liquidity gate as the desk (setup_rules.LIQUIDITY)
    "pledge_exclude_pct": 50.0, "pledge_warn_pct": 25.0,
    "distress_interest_cover_below": 1.5,
    "distress_debt_equity_above": 3.0,    # non-financials only, together with falling profit
    "results_window_days": 7,             # results due within this many days: event-risk warning
    "min_coverage_for_ranking_pct": 50.0, # below this the status is capped at `watchlist`
}

# corporate_announcements.impact_score holds the classifier's text label (low / medium / high), not a number.
CATALYST: Dict[str, Any] = {"lookback_days": 30, "impact_weights": {"medium": 1.0, "high": 2.0}, "max_items": 5,
                            "points_per_weight": 25.0}

FINANCIAL_WORDS = ("bank", "financ", "nbfc", "insurance", "capital market", "housing finance")

STATUSES = ("excluded", "near_low_no_evidence", "watchlist", "early_reversal", "trigger_ready", "confirmed")


def public_rules() -> Dict[str, Any]:
    return {"version": RULES_VERSION, "near_low": NEAR_LOW, "weights": WEIGHTS, "stage1": list(STAGE1),
            "stage2": list(STAGE2), "signals": SIGNALS, "core_signals": list(CORE_SIGNALS), "candidate": CANDIDATE,
            "levels": LEVELS, "gates": GATES, "catalyst": CATALYST,
            "note": ("Weights are hypotheses, not tuned. The score is rule-based, not a probability. Proximity to the "
                     "52-week low is not a signal. Unknown figures are left out of the score, never counted as neutral.")}


# ── helpers ───────────────────────────────────────────────────────────────────

def _f(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and x not in (float("inf"), float("-inf")) else None


def _d(v: Any) -> Optional[date]:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def _clip(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _ramp(x: Optional[float], bad: float, good: float) -> Optional[float]:
    """0 at `bad`, 100 at `good`, linear between (works for either direction); None when x is unknown."""
    if x is None:
        return None
    if good == bad:
        return None
    return _clip((x - bad) / (good - bad) * 100.0)


def ema(values: Sequence[float], n: int) -> List[Optional[float]]:
    """EMA with the first value seeded by the SMA of the first n values; None before that."""
    out: List[Optional[float]] = [None] * len(values)
    if len(values) < n:
        return out
    k = 2.0 / (n + 1)
    e = sum(values[:n]) / n
    out[n - 1] = e
    for i in range(n, len(values)):
        e = values[i] * k + e * (1 - k)
        out[i] = e
    return out


def rsi(closes: Sequence[float], n: int = 14) -> List[Optional[float]]:
    """Wilder RSI; None for the first n values."""
    out: List[Optional[float]] = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = [max(closes[i] - closes[i - 1], 0.0) for i in range(1, len(closes))]
    losses = [max(closes[i - 1] - closes[i], 0.0) for i in range(1, len(closes))]
    ag = sum(gains[:n]) / n
    al = sum(losses[:n]) / n

    def val(g: float, l: float) -> float:
        return 100.0 if l == 0 else 100.0 - 100.0 / (1.0 + g / l)
    out[n] = val(ag, al)
    for i in range(n, len(gains)):
        ag = (ag * (n - 1) + gains[i]) / n
        al = (al * (n - 1) + losses[i]) / n
        out[i + 1] = val(ag, al)
    return out


def atr(bars: Sequence[Mapping[str, Any]], n: int = 14) -> Optional[float]:
    """Wilder ATR over the whole series; None with fewer than n+1 bars."""
    if len(bars) < n + 1:
        return None
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["h"], bars[i]["l"], bars[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    a = sum(trs[:n]) / n
    for t in trs[n:]:
        a = (a * (n - 1) + t) / n
    return a


def distance_from_low(bars: Sequence[Mapping[str, Any]], window: int = 252) -> Dict[str, Any]:
    """The owner's formula over the last `window` sessions; low_price/low_date/sessions_since_low, or insufficient_history."""
    if len(bars) < window:
        return {"status": "insufficient_history", "sessions": len(bars), "needed": window}
    win = bars[-window:]
    low = min(b["l"] for b in win)
    idx = max(i for i, b in enumerate(win) if b["l"] == low)
    close = bars[-1]["c"]
    hi = max(b["h"] for b in win)
    return {"status": "ok", "close": close, "low_52w": low, "low_date": win[idx]["d"], "high_52w": hi,
            "sessions_since_low": len(win) - 1 - idx,
            "distance_from_52w_low_pct": round((close / low - 1.0) * 100.0, 2)}


# ── stabilization evidence ────────────────────────────────────────────────────

def _sig(value: Optional[bool], observed: Any, rule: str) -> Dict[str, Any]:
    return {"state": "unknown" if value is None else ("true" if value else "false"), "observed": observed, "rule": rule}


def signals(bars: Sequence[Mapping[str, Any]], dist: Mapping[str, Any],
            index_closes: Optional[Sequence[float]] = None) -> Dict[str, Dict[str, Any]]:
    """Each stabilization signal as {state: true|false|unknown, observed, rule}. Unknown when an input is missing."""
    S = SIGNALS
    out: Dict[str, Dict[str, Any]] = {}
    closes = [b["c"] for b in bars]

    # low not new
    since = dist.get("sessions_since_low")
    out["low_not_new"] = _sig(None if since is None else since >= S["low_not_new_min_sessions"], since,
                              f"52w low made at least {S['low_not_new_min_sessions']} sessions ago")

    # higher low
    r, (p0, p1) = S["higher_low_recent"], S["higher_low_prior"]
    if len(bars) >= p1 + 1:
        recent = min(b["l"] for b in bars[-r:])
        prior = min(b["l"] for b in bars[-p1:-(p0 - 1)])
        out["higher_low"] = _sig(recent > prior, {"recent_low": round(recent, 2), "prior_low": round(prior, 2)},
                                 f"lowest low of last {r} sessions above lowest low of sessions {p0}-{p1} back")
    else:
        out["higher_low"] = _sig(None, None, "needs 31 sessions")

    # RSI recovery
    rs = rsi(closes)
    lb = S["rsi_lookback"]
    if len(rs) > lb and rs[-1] is not None and rs[-1 - lb] is not None:
        out["rsi_recovery"] = _sig(rs[-1] >= S["rsi_min"] and rs[-1] > rs[-1 - lb],
                                   {"rsi14": round(rs[-1], 1), f"rsi14_{lb}d_ago": round(rs[-1 - lb], 1)},
                                   f"RSI(14) at least {S['rsi_min']:g} and above its value {lb} sessions ago")
    else:
        out["rsi_recovery"] = _sig(None, None, "needs 20 sessions")

    # EMA20 reclaim (close above a rising EMA20); EMA50 recorded as confirmation, not a core signal
    e20, e50 = ema(closes, S["ema_fast"]), ema(closes, S["ema_slow"])
    if e20[-1] is not None and len(e20) > 5 and e20[-6] is not None:
        out["ema20_reclaim"] = _sig(closes[-1] > e20[-1] and e20[-1] > e20[-6],
                                    {"close": round(closes[-1], 2), "ema20": round(e20[-1], 2)},
                                    "close above EMA20 and EMA20 above its value 5 sessions ago")
    else:
        out["ema20_reclaim"] = _sig(None, None, "needs 25 sessions")
    out["above_ema50"] = _sig(None if e50[-1] is None else closes[-1] > e50[-1],
                              None if e50[-1] is None else {"close": round(closes[-1], 2), "ema50": round(e50[-1], 2)},
                              "close above EMA50 (medium-term confirmation, not a core signal)")

    # relative strength vs the benchmark
    n = S["rs_lookback"]
    if index_closes is not None and len(index_closes) == len(closes) and len(closes) > n and index_closes[-1 - n]:
        sr = (closes[-1] / closes[-1 - n] - 1) * 100
        ir = (index_closes[-1] / index_closes[-1 - n] - 1) * 100
        out["rs_vs_index"] = _sig(sr - ir > 0, {"stock_20d_pct": round(sr, 2), "index_20d_pct": round(ir, 2)},
                                  "stock's 20-session return above the benchmark's")
    else:
        out["rs_vs_index"] = _sig(None, None, "needs benchmark closes on the same dates")

    # volume participation: volume on up days vs down days
    v = S["volume_sessions"]
    if len(bars) > v and all(b.get("v") is not None for b in bars[-v:]):
        up = sum(b["v"] for i, b in enumerate(bars[-v:], len(bars) - v) if b["c"] > bars[i - 1]["c"])
        dn = sum(b["v"] for i, b in enumerate(bars[-v:], len(bars) - v) if b["c"] < bars[i - 1]["c"])
        out["volume_participation"] = _sig(up > dn, {"up_day_volume": up, "down_day_volume": dn},
                                           f"volume on up days above volume on down days over {v} sessions")
    else:
        out["volume_participation"] = _sig(None, None, "needs volume")

    # momentum context (not core): ROC5, ROC20
    for key, k in (("roc5", S["roc_short"]), ("roc20", S["roc_medium"])):
        if len(closes) > k:
            roc = (closes[-1] / closes[-1 - k] - 1) * 100
            out[key] = _sig(roc > 0, round(roc, 2), f"{k}-session return above 0")
        else:
            out[key] = _sig(None, None, f"needs {k + 1} sessions")
    return out


def levels(bars: Sequence[Mapping[str, Any]], dist: Mapping[str, Any]) -> Dict[str, Any]:
    """Hypothetical entry trigger, invalidation, target and reward/risk. None where the bars are too few."""
    L = LEVELS
    close = bars[-1]["c"]
    a = atr(bars)
    out: Dict[str, Any] = {"close": close, "atr14": None if a is None else round(a, 2), "hypothetical": True}
    if len(bars) < L["resistance_sessions"] + 1:
        return {**out, "resistance": None, "invalidation": None, "target": None, "reward_risk": None}
    resistance = max(b["h"] for b in bars[-1 - L["resistance_sessions"]:-1])
    prior = bars[-1 - L["invalidation_prior_sessions"]:-1]
    swing_low = min(b["l"] for b in prior)
    invalidation = None if a is None else swing_low - L["invalidation_atr_buffer"] * a
    target = max(b["h"] for b in bars[-L["target_sessions"]:])
    rr = None
    if invalidation is not None and close > invalidation:
        # reward from the entry trigger (resistance, or the close if already through it) to the target
        entry = max(close, resistance)
        rr = round((target - entry) / (entry - invalidation), 2) if entry > invalidation else None
    out.update(resistance=round(resistance, 2), swing_low=round(swing_low, 2),
               invalidation=None if invalidation is None else round(invalidation, 2),
               target=round(target, 2), reward_risk=rr,
               dist_to_resistance_pct=round((resistance / close - 1) * 100, 2),
               risk_to_invalidation_pct=None if invalidation is None else round((close / invalidation - 1) * 100, 2))
    return out


def breakout_rvol(bars: Sequence[Mapping[str, Any]]) -> Optional[float]:
    if len(bars) < 21 or any(b.get("v") is None for b in bars[-21:]):
        return None
    base = sum(b["v"] for b in bars[-21:-1]) / 20.0
    return round(bars[-1]["v"] / base, 2) if base else None


# ── gates ─────────────────────────────────────────────────────────────────────

def is_financial(sector: Optional[str]) -> bool:
    s = (sector or "").lower()
    return any(w in s for w in FINANCIAL_WORDS)


def gates(row: Mapping[str, Any], dist: Mapping[str, Any]) -> Tuple[Optional[str], List[Dict[str, str]]]:
    """(exclusion, warnings). exclusion is the first gate the stock fails (None if it passes all)."""
    G = GATES
    warnings: List[Dict[str, str]] = []
    if dist.get("status") != "ok":
        return "insufficient_history", warnings
    if row.get("eligible") is False:
        return f"scanner_{row.get('exclusion') or 'ineligible'}", warnings
    tv = _f(row.get("traded_value_cr_20d"))
    if tv is None:
        return "no_traded_value", warnings
    if tv < G["min_traded_value_cr"]:
        return "illiquid", warnings
    fund = row.get("fundamentals") or {}
    pledge = _f(fund.get("promoter_pledged_pct"))
    if pledge is not None and pledge >= G["pledge_exclude_pct"]:
        return "high_pledge", warnings
    if pledge is not None and pledge >= G["pledge_warn_pct"]:
        warnings.append({"code": "elevated_pledge", "detail": f"Promoter pledge {pledge:g}% of holding"})
    ic = _f(fund.get("interest_cover"))
    if ic is not None and ic < G["distress_interest_cover_below"]:
        return "financial_distress", warnings
    de, pg = _f(fund.get("debt_to_equity")), _f(fund.get("pat_growth_yoy_pct"))
    if (not is_financial(row.get("sector") or row.get("industry")) and de is not None and pg is not None
            and de > G["distress_debt_equity_above"] and pg < 0):
        return "financial_distress", warnings
    nr = _d(row.get("next_results_date"))
    asof = _d(row.get("as_of"))
    if nr and asof and 0 <= (nr - asof).days <= G["results_window_days"]:
        warnings.append({"code": "results_due", "detail": f"Results due {nr.isoformat()} ({(nr - asof).days} days)"})
    return None, warnings


# ── components (each 0-100 or None) ───────────────────────────────────────────

def quadrant(rs: Optional[float], change: Optional[float]) -> str:
    """Rotation quadrant from the sector's relative strength vs the benchmark and its change over 10 sessions."""
    if rs is None or change is None:
        return "unknown"
    if rs > 0:
        return "leading" if change >= 0 else "weakening"
    return "improving" if change >= 0 else "lagging"


def sector_component(ctx: Optional[Mapping[str, Any]]) -> Tuple[Optional[float], Dict[str, Any]]:
    """Sector rotation: relative strength vs the benchmark, its change, breadth. None without a sector context."""
    if not ctx:
        return None, {"reason": "no sector context"}
    parts = [(_ramp(_f(ctx.get("rs_20d")), -5.0, 5.0), 0.4),
             (_ramp(_f(ctx.get("rs_change")), -3.0, 3.0), 0.3),
             (_ramp(_f(ctx.get("breadth_above_50dma_pct")), 20.0, 70.0), 0.3)]
    known = [(s, w) for s, w in parts if s is not None]
    if not known:
        return None, {"reason": "sector figures missing", "quadrant": ctx.get("quadrant")}
    tw = sum(w for _, w in known)
    return round(sum(s * w for s, w in known) / tw, 1), {"quadrant": ctx.get("quadrant"),
                                                          "known_parts": len(known), "of": 3}


def technical_component(sig: Mapping[str, Mapping[str, Any]], lv: Mapping[str, Any]) -> Tuple[Optional[float], Dict[str, Any]]:
    core = [sig[k]["state"] for k in CORE_SIGNALS]
    known = [s for s in core if s != "unknown"]
    if len(known) < CANDIDATE["min_core_known"]:
        return None, {"reason": f"only {len(known)} of {len(core)} core signals known"}
    base = 100.0 * sum(1 for s in known if s == "true") / len(known)
    bonus = 10.0 if sig["above_ema50"]["state"] == "true" else 0.0
    return round(_clip(base * 0.9 + bonus), 1), {"true": sum(1 for s in known if s == "true"), "known": len(known)}


def momentum_component(sig: Mapping[str, Mapping[str, Any]], rvol: Optional[float]) -> Tuple[Optional[float], Dict[str, Any]]:
    parts: List[float] = []
    for key in ("roc5", "roc20"):
        o = sig[key]["observed"]
        if isinstance(o, (int, float)):
            parts.append(_ramp(o, -10.0, 10.0))
    r = sig["rsi_recovery"]["observed"]
    if isinstance(r, dict):
        parts.append(_ramp(r["rsi14"], 30.0, 60.0))
    rs = sig["rs_vs_index"]["observed"]
    if isinstance(rs, dict):
        parts.append(_ramp(rs["stock_20d_pct"] - rs["index_20d_pct"], -10.0, 10.0))
    if rvol is not None:
        parts.append(_ramp(rvol, 0.7, 2.0))
    if not parts:
        return None, {"reason": "no momentum inputs"}
    return round(sum(parts) / len(parts), 1), {"inputs": len(parts)}


def fundamental_component(fund: Optional[Mapping[str, Any]], sector: Optional[str]) -> Tuple[Optional[float], Dict[str, Any]]:
    """Sector-aware quality: growth, profitability, leverage (non-financials only), cash generation, pledge."""
    if not fund:
        return None, {"reason": "no fundamentals"}
    fin = is_financial(sector)
    parts: Dict[str, Optional[float]] = {
        "revenue_growth": _ramp(_f(fund.get("revenue_growth_yoy_pct")), -10.0, 25.0),
        "profit_growth": _ramp(_f(fund.get("pat_growth_yoy_pct")), -20.0, 30.0),
        "roe": _ramp(_f(fund.get("roe_pct")), 5.0, 20.0),
        "pledge": _ramp(_f(fund.get("promoter_pledged_pct")), 50.0, 0.0),
    }
    if not fin:
        parts["operating_margin"] = _ramp(_f(fund.get("operating_margin_pct")), 3.0, 20.0)
        parts["leverage"] = _ramp(_f(fund.get("debt_to_equity")), 2.0, 0.2)
        cfo = _f(fund.get("cfo_cr"))
        parts["cash_generation"] = None if cfo is None else (100.0 if cfo > 0 else 0.0)
    known = {k: v for k, v in parts.items() if v is not None}
    unknown = sorted(k for k, v in parts.items() if v is None)
    if len(known) < 3:
        return None, {"reason": f"only {len(known)} fundamental figures known", "unknown": unknown}
    return round(sum(known.values()) / len(known), 1), {
        "profile": "financial (leverage and operating margin not scored)" if fin else "default",
        "known": sorted(known), "unknown": unknown}


def catalyst_component(items: Optional[Sequence[Mapping[str, Any]]], as_of: Optional[date]) -> Tuple[Optional[float], Dict[str, Any]]:
    """Net classified-announcement tone over the last 30 days; only items filed on or before as_of count (point in time).
    None when no announcement was classified in the window (absence of news is unknown, not neutral)."""
    if items is None or as_of is None:
        return None, {"reason": "no announcement data"}
    C = CATALYST
    material = []
    for it in items:
        fd = _d(it.get("filed_at"))
        if fd is None or fd > as_of or (as_of - fd).days > C["lookback_days"]:
            continue
        imp, sent = str(it.get("impact_score") or "").lower(), (it.get("sentiment") or "").lower()
        if imp not in C["impact_weights"] or sent not in ("positive", "negative", "neutral"):
            continue
        material.append({"filed_at": fd.isoformat(), "category": it.get("event_category"), "subject": it.get("subject"),
                         "impact": imp, "sentiment": sent})
    if not material:
        return None, {"reason": "no classified material (medium or high impact) announcement in the last 30 days",
                      "items": []}
    net = sum((1 if m["sentiment"] == "positive" else -1 if m["sentiment"] == "negative" else 0)
              * C["impact_weights"][m["impact"]] for m in material)
    return round(_clip(50.0 + C["points_per_weight"] * net), 1), {"items": material[:C["max_items"]], "net_weight": net}


def valuation_risk_component(fund: Optional[Mapping[str, Any]], lv: Mapping[str, Any], atr_pct: Optional[float]) -> Tuple[Optional[float], Dict[str, Any]]:
    """Reward/risk and distance to invalidation (always from price), plus P/E vs profit growth when both are known."""
    parts: Dict[str, Optional[float]] = {
        "reward_risk": _ramp(_f(lv.get("reward_risk")), 0.5, 3.0),
        "risk_distance": _ramp(_f(lv.get("risk_to_invalidation_pct")), 15.0, 3.0),
    }
    pe, pg = _f((fund or {}).get("pe_ttm")), _f((fund or {}).get("pat_growth_yoy_pct"))
    if pe is not None and pe > 0 and pg is not None and pg > 0:
        parts["peg"] = _ramp(pe / pg, 3.0, 0.5)
    known = {k: v for k, v in parts.items() if v is not None}
    if not known:
        return None, {"reason": "no price levels or valuation inputs"}
    return round(sum(known.values()) / len(known), 1), {"known": sorted(known),
                                                         "unknown": sorted(k for k, v in parts.items() if v is None)}


# ── score and status ──────────────────────────────────────────────────────────

def combine(components: Mapping[str, Optional[float]]) -> Dict[str, Any]:
    """Weighted total over the KNOWN components, renormalised; coverage_pct is the weight actually scored."""
    known = {k: v for k, v in components.items() if v is not None}
    kw = sum(WEIGHTS[k] for k in known)
    total = round(sum(WEIGHTS[k] * v for k, v in known.items()) / kw, 1) if kw else None

    def stage(keys: Sequence[str]) -> Optional[float]:
        ks = [k for k in keys if components.get(k) is not None]
        w = sum(WEIGHTS[k] for k in ks)
        return round(sum(WEIGHTS[k] * components[k] for k in ks) / w, 1) if w else None
    return {"total": total, "coverage_pct": round(kw, 1), "unknown_components": sorted(k for k in WEIGHTS if k not in known),
            "stage1_opportunity_quality": stage(STAGE1), "stage2_trade_readiness": stage(STAGE2)}


def classify(dist: Mapping[str, Any], near_pct: float, sig: Mapping[str, Mapping[str, Any]], lv: Mapping[str, Any],
             rvol: Optional[float], coverage_pct: float) -> Tuple[str, Dict[str, Any]]:
    """Status of a stock that passed the gates, with the evidence counts."""
    core = [sig[k]["state"] for k in CORE_SIGNALS]
    t, u = core.count("true"), core.count("unknown")
    ev = {"core_true": t, "core_false": core.count("false"), "core_unknown": u, "core_total": len(core),
          "required_true": CANDIDATE["min_core_true"]}
    if dist["distance_from_52w_low_pct"] > near_pct:
        return "near_low_no_evidence", {**ev, "note": f"more than {near_pct:g}% above the 52-week low: not in the pool"}
    if lv.get("invalidation") is not None and lv["close"] < lv["invalidation"]:
        return "excluded", {**ev, "exclusion": "setup_invalidated"}
    if t < CANDIDATE["min_core_true"]:
        return "near_low_no_evidence", ev
    if coverage_pct < GATES["min_coverage_for_ranking_pct"]:
        return "watchlist", {**ev, "note": "too little of the score could be measured to rank above watchlist"}
    rr_ok = lv.get("reward_risk") is not None and lv["reward_risk"] >= LEVELS["min_reward_risk"]
    res = lv.get("resistance")
    if res is not None and lv["close"] > res and rr_ok and rvol is not None and rvol >= LEVELS["confirmed_rvol_min"] \
            and sig["ema20_reclaim"]["state"] == "true":
        return "confirmed", ev
    if res is not None and rr_ok and 0 <= (res / lv["close"] - 1) * 100 <= LEVELS["trigger_ready_within_pct"]:
        return "trigger_ready", ev
    return "early_reversal", ev


def _explain(status: str, dist: Mapping[str, Any], sig, lv, comps, score, warn, exclusion, sector_ctx) -> Dict[str, Any]:
    labels = {"higher_low": "a higher low", "low_not_new": "no new low for 5+ sessions", "rsi_recovery": "RSI recovering",
              "ema20_reclaim": "price back above a rising EMA20", "rs_vs_index": "outperforming the Nifty 500",
              "volume_participation": "buyers outweighing sellers on volume"}
    confirms = [labels[k] for k in CORE_SIGNALS if sig[k]["state"] == "true"]
    unconfirmed = [labels[k] for k in CORE_SIGNALS if sig[k]["state"] == "false"]
    unknown = [labels[k] for k in CORE_SIGNALS if sig[k]["state"] == "unknown"]
    uncertain = [f"{c.replace('_', ' ')} could not be measured" for c in score["unknown_components"]]
    uncertain += [f"not yet: {x}" for x in unconfirmed] + [f"unknown: {x}" for x in unknown]
    uncertain += [w["detail"] for w in warn]
    why = (f"{dist['distance_from_52w_low_pct']:g}% above its 52-week low of {dist['low_52w']:g} "
           f"(made {dist['low_date']}); near the low is a screen, not a signal")
    q = (sector_ctx or {}).get("quadrant")
    if q:
        why += f"; sector is {q}"
    why_now = ("; ".join(confirms) if confirms else "no stabilization evidence yet")
    inval = (f"close below {lv['invalidation']:g}" if lv.get("invalidation") is not None else "unknown (too little history)")
    trigger = (f"close above {lv['resistance']:g} on volume" if lv.get("resistance") is not None else "unknown")
    return {"why_this_stock": why, "why_now": why_now, "confirms": confirms, "uncertain": uncertain,
            "invalidates": inval, "entry_trigger": trigger}


def evaluate(rows: Sequence[Mapping[str, Any]], as_of: date, near_pct: Optional[float] = None) -> Dict[str, Any]:
    """Pure function of rows + as_of: every stock's status, score, evidence and explanation, best first.

    `rows` carry only data published on or before `as_of` (the caller guarantees this; announcements are re-checked)."""
    near = NEAR_LOW["default_pct"] if near_pct is None else float(near_pct)
    out: List[Dict[str, Any]] = []
    excluded: Dict[str, int] = {}
    for row in rows:
        sym = str(row.get("symbol") or "").upper()
        bars = list(row.get("bars") or [])
        dist = distance_from_low(bars, NEAR_LOW["window_sessions"]) if bars else {"status": "insufficient_history", "sessions": 0}
        r = dict(row, as_of=as_of)
        excl, warn = gates(r, dist)
        base = {"symbol": sym, "sector": row.get("sector"), "industry": row.get("industry"), "as_of": as_of.isoformat(),
                "warnings": warn}
        if excl is not None:
            excluded[excl] = excluded.get(excl, 0) + 1
            out.append({**base, "status": "excluded", "exclusion": excl,
                        "distance_from_52w_low_pct": dist.get("distance_from_52w_low_pct")})
            continue
        if dist["distance_from_52w_low_pct"] > near:
            # outside the pool the caller asked for: not listed, counted
            excluded["above_pool"] = excluded.get("above_pool", 0) + 1
            continue
        sig = signals(bars, dist, row.get("index_closes"))
        lv = levels(bars, dist)
        rvol = breakout_rvol(bars)
        a = lv.get("atr14")
        atr_pct = None if a is None else a / bars[-1]["c"] * 100
        fund = row.get("fundamentals")
        comps_detail = {
            "sector": sector_component(row.get("sector_ctx")),
            "technical": technical_component(sig, lv),
            "momentum": momentum_component(sig, rvol),
            "fundamental": fundamental_component(fund, row.get("sector") or row.get("industry")),
            "catalyst": catalyst_component(row.get("announcements"), as_of),
            "valuation_risk": valuation_risk_component(fund, lv, atr_pct),
        }
        comps = {k: v[0] for k, v in comps_detail.items()}
        score = combine(comps)
        status, evidence = classify(dist, near, sig, lv, rvol, score["coverage_pct"])
        if status == "excluded":
            excluded[evidence["exclusion"]] = excluded.get(evidence["exclusion"], 0) + 1
        speculative = (status in ("early_reversal", "trigger_ready", "confirmed") and comps["fundamental"] is not None
                       and comps["fundamental"] < 40)
        if speculative:
            warn = warn + [{"code": "speculative", "detail": "Chart is improving but fundamental quality is weak: speculative, not a quality investment"}]
        if status in ("early_reversal", "trigger_ready", "confirmed") and comps["fundamental"] is None:
            warn = warn + [{"code": "fundamentals_unverified", "detail": "Fundamental quality could not be measured"}]
        item = {**base, "warnings": warn, "status": status, "evidence": evidence,
                "distance": dist, "signals": sig, "levels": lv, "rvol": rvol,
                "components": {k: {"score": comps[k], "weight": WEIGHTS[k], "known": comps[k] is not None,
                                   "detail": comps_detail[k][1]} for k in WEIGHTS},
                "score": score, "sector_context": row.get("sector_ctx"),
                "explanation": _explain(status, dist, sig, lv, comps, score, warn, None, row.get("sector_ctx")),
                "traded_value_cr_20d": _f(row.get("traded_value_cr_20d")),
                "next_results_date": _d(row.get("next_results_date")).isoformat() if _d(row.get("next_results_date")) else None}
        if status == "excluded":
            item["exclusion"] = evidence["exclusion"]
        out.append(item)
    order = {s: i for i, s in enumerate(reversed(STATUSES))}
    out.sort(key=lambda x: (order.get(x["status"], 99), -(x.get("score", {}).get("total") or -1), x["symbol"]))
    counts: Dict[str, int] = {}
    for x in out:
        counts[x["status"]] = counts.get(x["status"], 0) + 1
    return {"rules_version": RULES_VERSION, "as_of": as_of.isoformat(), "near_low_pct": near,
            "universe": {"evaluated": len(rows), "listed": len(out), "status_counts": counts, "exclusions": excluded},
            "rows": out}
