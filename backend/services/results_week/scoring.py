"""Results week — the scoring rules of docs/EARNINGS_SURPRISE_TRACKER.md §4 as pure functions (no I/O, no clock).

Every threshold and weight here is a provisional hypothesis the validation study (§7) tests; none is validated. The
verdict is "vs historical trend" (the company's own past quarters), never vs analyst consensus: no consensus is held.
Ideas are ordered for review; nothing here is a prediction or places an order.
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


IST = timezone(timedelta(hours=5, minutes=30))
MARKET_CLOSE_IST = time(15, 30)

BASIS = "historical_trend"
LABEL = "vs historical trend (the company's own past quarters), not analyst consensus"
IDEAS_NOTE = ("Ordered for review, not a prediction. Tested on past results seasons: this ordering showed no measurable skill so far.")
OUTLOOK_LABEL = "filing analysis, not a guidance tracker"

REASON_NO_BASELINE = "not rated: no reliable baseline"
REASON_TOO_UNCERTAIN = "not rated: baseline too uncertain"
REASON_NOT_FILED = "not rated: the filed figure is not in the stored results yet"
REASON_ZERO_BAND = "not rated: the baseline band has no width on this side"
REASON_PENDING = "not rated: figures pending (the outcome is filed; the figures are not in the stored results yet)"
REASON_UPCOMING = "not rated: results not declared yet"

# §4a. A metric is rated only with a reliable baseline AND an informative band. Relative half-width = (high − low) / (2·mid).
# Provisional (coordinator, 27 Oct 2026, from staging): bands such as BAJAJ-AUTO PAT 1848–3687–7200 (half-width 0.73) or
# ITCHOTELS PAT 110–172–281 (0.50) say almost nothing, so a result inside them is not "in line" in any useful sense.
# PAT is noisier than revenue, so its limit is wider. The validation study (§7) tests both limits.
MAX_HALF_WIDTH = {"pat": 0.35, "revenue": 0.20}
SURPRISE_WEIGHTS = {"pat": 0.6, "revenue": 0.4}
METRICS = ("pat", "revenue")

# §4b. Owner framework weights, renormalised over the components present.
COMPOSITE_WEIGHTS = {"surprise": 35, "trend": 25, "outlook": 25, "quality": 15}
BANDS = ((70.0, "above"), (45.0, "in_line"), (0.0, "below"))

# §4b operating trend (P1 provisional): each growth g % scores clamp(50 + g); the EBITDA-margin change (YoY, percentage
# points) scores clamp(50 + 10·pp). Year-on-year pieces weigh 2, quarter-on-quarter 1 (seasonality), the margin change 2.
TREND_WEIGHTS = {"yoy": 2.0, "qoq": 1.0, "margin": 2.0}
TREND_ITEMS = ("revenue", "ebitda", "pat")

# §4b earnings quality (P1 provisional): 100 minus 25 per flag, over the checks the stored figures allow.
QUALITY_PENALTY = 25.0
EXCEPTIONAL_SHARE = 0.20
OTHER_INCOME_SHARE = 0.30
TAX_RATE_LOW, TAX_RATE_HIGH = 0.10, 0.40

# §4c. Early-signal order. "earnings" = the Earnings Intelligence Score; "oi" is dropped from the All list (pro rata).
DECLARED_WEIGHTS = {"earnings": 40, "reaction": 20, "oi": 20, "technical": 20}
UPCOMING_WEIGHTS = {"technical": 40, "oi": 30, "past_reactions": 15, "trend": 15}
DECLARED_SESSIONS = 3            # filed in the last 3 sessions (the date's session included)
UPCOMING_SESSIONS = 5            # meeting on the date or in the next 5 sessions
MIN_PRESENT_WEIGHT_SHARE = 0.5   # a name is ordered only when parts carrying at least half its list's weight are present

# Reaction (first session after the filing): excess % vs Nifty scores clamp(50 + 10·excess·w), w = volume × clamped to
# [0.5, 2] (a move on thin volume counts half, on twice the usual volume double). Volume × = first-session volume ÷ the
# mean of up to 20 earlier sessions (at least 5 needed).
REACTION_PER_PCT = 10.0
VOLUME_WEIGHT_RANGE = (0.5, 2.0)
VOLUME_LOOKBACK, VOLUME_MIN_SESSIONS = 20, 5

# Past results reactions (upcoming): the mean two-session move (event day compounded with the next day) over the stock's
# past results, at least 2 occurrences; scores clamp(50 + 10·mean).
PAST_REACTION_PER_PCT = 10.0
PAST_REACTION_MIN_N = 2

# OI build-up across the coming months (owner, 27 Oct evening; coordinator's rules). The headline state reads TOTAL
# futures open interest across every expiry against the stock's spot move over the last session, so a roll from the
# expiring month into the next (near-month OI falling, next-month OI rising) does not read as fresh positions or as
# unwinding. A state is called only when |spot move| ≥ 0.5 % and |total OI change| ≥ 2 %; smaller moves read
# "no clear signal", never a state from the sign alone. Provisional thresholds, not validated.
FNO_MIN_PRICE_PCT = 0.5
FNO_MIN_OI_PCT = 2.0
FNO_TOTAL_SESSIONS = (1, 3)        # the total block's look-backs, in sessions
ROLLOVER_WINDOW_SESSIONS = 5       # rollover is read in the 5 sessions before a monthly expiry (and on expiry day)
# Expiry week (coordinator, 27 Oct): in the 5 sessions up to and including a monthly expiry, total futures OI falls
# routinely as contracts are closed instead of rolled, so falling OI is not evidence of short covering or long
# unwinding there. Those two states keep their text, gain EXPIRY_NOTE and score as no clear signal (50) in the ideas;
# long and short build-up (OI rising) keep their scores. The expiry is read from the data (the scan row's near_expiry).
EXPIRY_WINDOW_SESSIONS = 5
EXPIRY_NOTE = "expiry week: open interest falls as contracts close"
OI_FALLING_STATES = ("short_covering", "long_unwinding")
ROLLOVER_PAST_EXPIRIES = 5         # … against the stock's own last 5 expiries, the same number of sessions before each
OPTIONS_SKIP_EXPIRY_DAYS = 7       # options: the first expiry more than 7 calendar days after the date (DaaS's expiry-week flag)
OPTIONS_TOP_STRIKES = 3
OI_LABEL = "open interest cannot tell buyers from writers"
BUILDUP_STATES = ("long_buildup", "short_buildup", "short_covering", "long_unwinding")
NO_CLEAR = "no_clear_signal"
BUILDUP_SIGNAL = {"long_buildup": "positive", "short_covering": "mildly_positive", "short_buildup": "negative",
                  "long_unwinding": "negative", NO_CLEAR: "neutral"}
BUILDUP_SCORE = {"long_buildup": 100.0, "short_covering": 75.0, NO_CLEAR: 50.0, "long_unwinding": 25.0, "short_buildup": 0.0}
VERDICT_TEXT = {"above": "above historical trend", "in_line": "in line with historical trend", "below": "below historical trend"}
BUILDUP_TEXT = {"long_buildup": "long build-up", "short_covering": "short covering", "short_buildup": "short build-up",
                "long_unwinding": "long unwinding", NO_CLEAR: "no clear signal"}

# SEBI wording (§ header): these never appear in a response. Checked by TC-B9 and printed by the job's dry run.
FORBIDDEN_TERMS = ("beat the street", "beat expectations", "beats expectations", "beat estimates", "recommend",
                   "pick", "suggested")


# ── small helpers ─────────────────────────────────────────────────────────────────────────────────────────────────

def num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def r1(x: Optional[float]) -> Optional[float]:
    return None if x is None else round(x, 1)


def r2(x: Optional[float]) -> Optional[float]:
    return None if x is None else round(x, 2)


def band_of(score: Optional[float]) -> Optional[str]:
    if score is None:
        return None
    for floor, name in BANDS:
        if score >= floor:
            return name
    return "below"


def forbidden_terms(obj: Any) -> List[str]:
    """The forbidden terms found anywhere in a JSON-able object (keys and string values), lower-cased."""
    import json

    text = json.dumps(obj, default=str).lower()
    return [t for t in FORBIDDEN_TERMS if re.search(r"\b" + re.escape(t), text)]


# ── §4a surprise vs historical trend ──────────────────────────────────────────────────────────────────────────────

def z_score(filed: Optional[float], low: Optional[float], mid: Optional[float], high: Optional[float]) -> Optional[float]:
    """(filed − mid) / (high − mid) when filed ≥ mid, else (filed − mid) / (mid − low). None when a figure is missing
    or the band has no width on the filed side."""
    if None in (filed, low, mid, high):
        return None
    den = (high - mid) if filed >= mid else (mid - low)
    if den <= 0:
        return None
    return (filed - mid) / den


def metric_verdict(z: Optional[float]) -> Tuple[Optional[str], Optional[str]]:
    """(label, intensity): z > 1 above · −1 ≤ z ≤ 1 in line · z < −1 below; z ≥ 2 outstanding, z ≤ −2 well below."""
    if z is None:
        return None, None
    label = "above" if z > 1 else "below" if z < -1 else "in_line"
    intensity = "outstanding" if z >= 2 else "well_below" if z <= -2 else None
    return label, intensity


def component_score(z: float) -> float:
    return clamp(50.0 + 25.0 * z)


def half_width(low: Optional[float], mid: Optional[float], high: Optional[float]) -> Optional[float]:
    if None in (low, mid, high) or mid <= 0:
        return None
    return (high - low) / (2.0 * mid)


def rate_metric(key: str, m: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """One DaaS expectation metric (revenue / pat) rated against its baseline. `reason` says why it is not rated."""
    m = m or {}
    exp = m.get("expected") if isinstance(m.get("expected"), dict) else None
    low, mid, high = (num((exp or {}).get(k)) for k in ("low", "mid", "high"))
    filed = num((m.get("filed") or {}).get("value")) if isinstance(m.get("filed"), dict) else None
    hw = half_width(low, mid, high)
    out: Dict[str, Any] = {
        "key": key, "unit": m.get("unit"), "filed": filed,
        "expected": {"low": low, "mid": mid, "high": high} if exp else None,
        "vs_mid_pct": num(m.get("vs_mid_pct")), "within_band": m.get("within_band"), "reliable": bool(m.get("reliable")),
        "half_width": r2(hw),
        "z": None, "verdict": None, "intensity": None, "score": None, "reason": None, "note": m.get("note"),
    }
    if not m.get("reliable") or exp is None or None in (low, mid, high):
        out["reason"] = REASON_NO_BASELINE
        return out
    if hw is None or hw > MAX_HALF_WIDTH[key]:
        out["reason"] = REASON_TOO_UNCERTAIN
        return out
    if filed is None:
        out["reason"] = REASON_NOT_FILED
        return out
    z = z_score(filed, low, mid, high)
    if z is None:
        out["reason"] = REASON_ZERO_BAND
        return out
    out["z"] = r2(z)
    out["verdict"], out["intensity"] = metric_verdict(z)
    out["score"] = r1(component_score(z))
    out["_z"] = z
    return out


def surprise(metrics: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """The surprise component and the headline verdict from the DaaS metrics list (revenue, pat, eps).

    Rated metrics only: 0.6·S_pat + 0.4·S_revenue with both; PAT alone when revenue is not rated (e.g. banks, whose
    revenue has no baseline); revenue alone when PAT is not rated. The headline verdict applies the §4a thresholds to
    the same weighted z. Nothing rated → value and verdict null with the reason ("baseline too uncertain" when a band
    was too wide, else "no reliable baseline"); never "in line"."""
    by = {m.get("key"): m for m in metrics or [] if isinstance(m, dict)}
    rated = {k: rate_metric(k, by.get(k)) for k in METRICS}
    use = [k for k in METRICS if rated[k].get("_z") is not None]
    out: Dict[str, Any] = {"value": None, "metrics": {k: {x: v for x, v in rated[k].items() if x != "_z"} for k in METRICS},
                           "used": use, "weights": {}, "z": None}
    if not use:
        reasons = {rated[k]["reason"] for k in METRICS}
        reason = REASON_TOO_UNCERTAIN if REASON_TOO_UNCERTAIN in reasons else (
            REASON_NOT_FILED if reasons == {REASON_NOT_FILED} else REASON_NO_BASELINE)
        out["verdict"] = {"label": None, "intensity": None, "reason": reason}
        return out
    tot = sum(SURPRISE_WEIGHTS[k] for k in use)
    w = {k: SURPRISE_WEIGHTS[k] / tot for k in use}
    zh = sum(w[k] * rated[k]["_z"] for k in use)
    value = sum(w[k] * component_score(rated[k]["_z"]) for k in use)
    label, intensity = metric_verdict(zh)
    if len(use) == 2:
        reason = "PAT and revenue vs historical trend (weights 60 / 40)"
    else:
        other = "revenue" if use == ["pat"] else "pat"
        why = (rated[other]["reason"] or "").replace("not rated: ", "")
        reason = f"{'PAT' if use == ['pat'] else 'revenue'} only ({'PAT' if other == 'pat' else 'revenue'}: {why})"
    out.update(value=r1(value), weights={k: round(v, 2) for k, v in w.items()}, z=r2(zh),
               verdict={"label": label, "intensity": intensity, "reason": reason})
    return out


# ── quarters: trend and quality ───────────────────────────────────────────────────────────────────────────────────

_QUARTER_END = {1: (6, 30), 2: (9, 30), 3: (12, 31), 4: (3, 31)}


def period_end_of(label: Optional[str]) -> Optional[date]:
    """The quarter end of a DaaS period label such as "Q2 FY27 (Jul–Sep 2026)" → 2026-09-30 (Indian fiscal year)."""
    m = re.search(r"Q([1-4])\s*FY\s*(\d{2,4})", label or "")
    if not m:
        return None
    q, fy = int(m.group(1)), int(m.group(2))
    fy = fy + 2000 if fy < 100 else fy
    month, day = _QUARTER_END[q]
    return date(fy if q == 4 else fy - 1, month, day)


def shift_quarters(d: date, n: int) -> date:
    """The quarter end n quarters before `d` (a quarter end)."""
    idx = d.year * 4 + (d.month - 1) // 3 - n
    y, qi = divmod(idx, 4)
    month = qi * 3 + 3
    return date(y, month, 31 if month in (3, 12) else 30)


def _rows_by_end(rows: Iterable[Dict[str, Any]]) -> Dict[date, Dict[str, Any]]:
    out: Dict[date, Dict[str, Any]] = {}
    for r in rows or []:
        try:
            d = date.fromisoformat(str(r.get("period_end"))[:10])
        except ValueError:
            continue
        out.setdefault(d, r)              # newest-first input: the first row of a period wins
    return out


def growth_pct(cur: Optional[float], base: Optional[float]) -> Optional[float]:
    """Percent growth; None when either is missing or the base is not positive (growth off a loss is not a rate)."""
    if cur is None or base is None or base <= 0:
        return None
    return (cur / base - 1.0) * 100.0


def _margin(r: Optional[Dict[str, Any]]) -> Optional[float]:
    if not r:
        return None
    e, rev = num(r.get("ebitda_cr")), num(r.get("revenue_from_ops_cr"))
    return None if e is None or rev is None or rev <= 0 else e / rev * 100.0


def _fig(r: Optional[Dict[str, Any]], item: str) -> Optional[float]:
    if not r:
        return None
    return num(r.get({"revenue": "revenue_from_ops_cr", "ebitda": "ebitda_cr", "pat": "pat_cr"}[item]))


def pick_quarter(rows: Sequence[Dict[str, Any]], target: Optional[date], declared: bool) -> Tuple[Optional[date], Optional[str]]:
    """The quarter the trend is read on: the declared quarter itself, or (upcoming) the latest stored quarter before it.
    (quarter end, reason when there is none)."""
    by = _rows_by_end(rows)
    if not by:
        return None, "no stored quarterly results"
    if declared:
        if target is None:
            return None, "the result's quarter could not be read from its period label"
        if target not in by:
            return None, "the filed quarter is not in the stored quarterly results yet"
        return target, None
    before = sorted((d for d in by if target is None or d < target), reverse=True)
    return (before[0], None) if before else (None, "no stored quarter before the upcoming one")


def trend(rows: Sequence[Dict[str, Any]], quarter: Optional[date]) -> Dict[str, Any]:
    """YoY and QoQ growth of revenue, EBITDA and PAT on `quarter`, and the EBITDA-margin change YoY, with the score."""
    by = _rows_by_end(rows)
    t = by.get(quarter) if quarter else None
    out: Dict[str, Any] = {"value": None, "quarter": quarter.isoformat() if quarter else None, "yoy_pct": {}, "qoq_pct": {},
                           "ebitda_margin_pct": None, "ebitda_margin_change_pp": None, "present": [], "missing": []}
    if t is None:
        out["missing"] = ["quarter"]
        out.pop("present")
        return out
    t1, t4 = by.get(shift_quarters(quarter, 1)), by.get(shift_quarters(quarter, 4))
    parts: List[Tuple[float, float]] = []
    for item in TREND_ITEMS:
        for kind, base in (("yoy", t4), ("qoq", t1)):
            g = growth_pct(_fig(t, item), _fig(base, item))
            out[f"{kind}_pct"][item] = r1(g)
            name = f"{kind}_{item}"
            if g is None:
                out["missing"].append(name)
            else:
                out["present"].append(name)
                parts.append((TREND_WEIGHTS[kind], clamp(50.0 + g)))
    m, m4 = _margin(t), _margin(t4)
    out["ebitda_margin_pct"] = r1(m)
    if m is not None and m4 is not None:
        out["ebitda_margin_change_pp"] = r2(m - m4)
        out["present"].append("margin_change_yoy")
        parts.append((TREND_WEIGHTS["margin"], clamp(50.0 + 10.0 * (m - m4))))
    else:
        out["missing"].append("margin_change_yoy")
    if parts:
        out["value"] = r1(sum(w * s for w, s in parts) / sum(w for w, _ in parts))
    out.pop("present")
    return out


def quality(rows: Sequence[Dict[str, Any]], quarter: Optional[date]) -> Dict[str, Any]:
    """Earnings-quality flags on `quarter`: exceptional items > 20 % of PBT; other income > 30 % of PBT; tax rate < 10 %
    or > 40 % with PBT > 0; PAT growth > 2× revenue growth (PAT growing) with other income rising. Cash flow is never
    checked (not stored). A check whose figures are not stored is listed in `not_checked`, never passed."""
    by = _rows_by_end(rows)
    t = by.get(quarter) if quarter else None
    t4 = by.get(shift_quarters(quarter, 4)) if quarter else None
    flags: List[Dict[str, Any]] = []
    checked: List[str] = []
    not_checked: List[str] = []
    pbt = num((t or {}).get("pbt_cr"))
    pbt_pos = pbt is not None and pbt > 0

    def share_check(code: str, field: str, limit: float, text: str) -> None:
        v = num((t or {}).get(field))
        if v is None or not pbt_pos:
            not_checked.append(f"{code}: {'not stored' if v is None else 'PBT not positive'}")
            return
        checked.append(code)
        share = abs(v) / pbt
        if share > limit:
            flags.append({"code": code, "text": text.format(pct=share * 100), "value_pct": r1(share * 100)})

    share_check("exceptional_items", "exceptional_items_cr", EXCEPTIONAL_SHARE, "exceptional items are {pct:.0f} % of PBT (over 20 %)")
    share_check("other_income", "other_income_cr", OTHER_INCOME_SHARE, "other income is {pct:.0f} % of PBT (over 30 %)")
    tax = num((t or {}).get("tax_expense_cr"))
    if tax is None or not pbt_pos:
        not_checked.append(f"tax_rate: {'not stored' if tax is None else 'PBT not positive'}")
    else:
        checked.append("tax_rate")
        rate = tax / pbt
        if rate < TAX_RATE_LOW or rate > TAX_RATE_HIGH:
            flags.append({"code": "tax_rate", "text": f"tax rate {rate * 100:.0f} % (outside 10–40 %)", "value_pct": r1(rate * 100)})
    pat_g = growth_pct(_fig(t, "pat"), _fig(t4, "pat"))
    rev_g = growth_pct(_fig(t, "revenue"), _fig(t4, "revenue"))
    oi, oi4 = num((t or {}).get("other_income_cr")), num((t4 or {}).get("other_income_cr"))
    if None in (pat_g, rev_g, oi, oi4):
        not_checked.append("profit_vs_revenue: not stored")
    else:
        checked.append("profit_vs_revenue")
        if pat_g > 0 and pat_g > 2 * rev_g and oi > oi4:
            flags.append({"code": "profit_vs_revenue",
                          "text": f"PAT grew {pat_g:.0f} % YoY against revenue {rev_g:.0f} %, with other income rising"})
    not_checked.append("cash_flow: not stored")
    value = r1(clamp(100.0 - QUALITY_PENALTY * len(flags))) if checked else None
    return {"value": value, "flags": flags, "checked": checked, "not_checked": not_checked}


# ── outlook (filing analysis) ─────────────────────────────────────────────────────────────────────────────────────

def outlook(doc: Optional[Dict[str, Any]], *, read_failed: bool = False, declared: bool = True) -> Dict[str, Any]:
    """The filing analysis as the outlook proxy: (net_impact_score + 100) / 2. Missing = "not analysed", never neutral;
    a store that could not be read says so (not "not analysed")."""
    out: Dict[str, Any] = {"value": None, "label": OUTLOOK_LABEL, "analysed": False, "net_impact_score": None,
                           "net_band": None, "confidence_score": None, "materiality_score": None, "summary": None,
                           "event_ts": None, "analyzed_at": None, "reason": None}
    if read_failed:
        out.update(analysed=None, reason="the filing analysis store could not be read")
        return out
    if not declared:
        out["reason"] = "results not declared yet"
        return out
    net = num((doc or {}).get("net_impact_score"))
    if doc is None or net is None:
        out["reason"] = "not analysed"
        return out

    def iso(v: Any) -> Optional[str]:
        if isinstance(v, datetime):
            return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).isoformat()
        return str(v) if v else None

    out.update(value=r1((clamp(net, -100, 100) + 100.0) / 2.0), analysed=True, net_impact_score=net,
               net_band=doc.get("net_band"), confidence_score=num(doc.get("confidence_score")),
               materiality_score=num(doc.get("materiality_score")), summary=(doc.get("analysis") or {}).get("sum"),
               event_ts=iso(doc.get("event_ts")), analyzed_at=iso(doc.get("analyzed_at")))
    return out


# ── §4b composite ─────────────────────────────────────────────────────────────────────────────────────────────────

def composite(values: Dict[str, Optional[float]]) -> Dict[str, Any]:
    """The Earnings Intelligence Score: weights renormalised over the components present; null without both the surprise
    and the trend (an outlook or quality reading alone is not a results score)."""
    present = [k for k in COMPOSITE_WEIGHTS if values.get(k) is not None]
    missing = [k for k in COMPOSITE_WEIGHTS if k not in present]
    out: Dict[str, Any] = {"value": None, "band": None, "coverage": {"present": present, "missing": missing}, "weights": {}}
    if values.get("surprise") is None and values.get("trend") is None:
        return out
    tot = sum(COMPOSITE_WEIGHTS[k] for k in present)
    value = sum(COMPOSITE_WEIGHTS[k] * values[k] for k in present) / tot
    out.update(value=r1(value), band=band_of(value), weights={k: round(COMPOSITE_WEIGHTS[k] / tot, 3) for k in present})
    return out


# ── reaction vs Nifty ─────────────────────────────────────────────────────────────────────────────────────────────

def parse_ts(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if not v:
        return None
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def first_session(filed_at: datetime, sessions: Sequence[date]) -> Optional[date]:
    """The first session that can react to a filing: the filing day when filed before the 15:30 IST close on a session
    day, else the next session. None when the calendar does not reach it."""
    t = filed_at.astimezone(IST)
    d = t.date()
    ss = sorted(sessions)
    if d in ss and t.time() < MARKET_CLOSE_IST:
        return d
    return next((s for s in ss if s > d), None)


def reaction(filed_at: Optional[datetime], sessions: Sequence[date], bars: Dict[date, Tuple[Optional[float], Optional[float]]],
             nifty: Dict[date, float]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """(reaction block, gap). bars: session → (close, volume) for the stock; nifty: session → close.
    Excess = stock return − Nifty return on the first session, in percentage points."""
    if filed_at is None:
        return None, "reaction: the filing time is not known"
    fs = first_session(filed_at, sessions)
    if fs is None:
        return None, "reaction: the first session after the filing is beyond the known calendar"
    if fs not in bars or num(bars[fs][0]) is None:
        return None, f"reaction: no close for {fs.isoformat()} yet (the first session after the filing)"
    prev = max((d for d in bars if d < fs and num(bars[d][0]) is not None), default=None)
    if prev is None:
        return None, "reaction: no close before the first session"
    if fs not in nifty or prev not in nifty:
        return None, f"reaction: no Nifty 50 close for {fs.isoformat()} or {prev.isoformat()}"
    close, vol = num(bars[fs][0]), num(bars[fs][1])
    pclose = num(bars[prev][0])
    stock_ret = (close / pclose - 1.0) * 100.0
    nifty_ret = (nifty[fs] / nifty[prev] - 1.0) * 100.0
    excess = stock_ret - nifty_ret
    earlier = [num(bars[d][1]) for d in sorted((d for d in bars if d < fs), reverse=True)[:VOLUME_LOOKBACK]]
    earlier = [v for v in earlier if v is not None and v > 0]
    volume_x = vol / (sum(earlier) / len(earlier)) if vol is not None and len(earlier) >= VOLUME_MIN_SESSIONS else None
    w = clamp(volume_x, *VOLUME_WEIGHT_RANGE) if volume_x is not None else 1.0
    t = filed_at.astimezone(IST)
    return {
        "filed_at": filed_at.isoformat(), "filed_after_close": not (t.date() == fs and t.time() < MARKET_CLOSE_IST),
        "first_session": fs.isoformat(), "previous_session": prev.isoformat(), "close": close, "previous_close": pclose,
        "stock_return_pct": r2(stock_ret), "nifty_return_pct": r2(nifty_ret), "excess_pct": r2(excess),
        "volume_x": r2(volume_x), "score": r1(clamp(50.0 + REACTION_PER_PCT * excess * w)),
    }, None


# ── OI build-up ───────────────────────────────────────────────────────────────────────────────────────────────────

def oi_state(price_pct: Optional[float], oi_pct: Optional[float]) -> Optional[str]:
    """price ↑ OI ↑ long build-up · price ↓ OI ↑ short build-up · price ↑ OI ↓ short covering · price ↓ OI ↓ long
    unwinding — only when |price| ≥ 0.5 % and |OI| ≥ 2 %, else no clear signal. None when a figure is missing."""
    p, o = num(price_pct), num(oi_pct)
    if p is None or o is None:
        return None
    if abs(p) < FNO_MIN_PRICE_PCT or abs(o) < FNO_MIN_OI_PCT:
        return NO_CLEAR
    if o > 0:
        return "long_buildup" if p > 0 else "short_buildup"
    return "short_covering" if p > 0 else "long_unwinding"


def pct_change(cur: Optional[float], base: Optional[float]) -> Optional[float]:
    if cur is None or base is None or base == 0:
        return None
    return (cur / base - 1.0) * 100.0


def total_block(row: Optional[Dict[str, Any]], row_back: Optional[Dict[str, Any]], back_date: Optional[str]) -> Optional[Dict[str, Any]]:
    """Total futures OI (every expiry, DaaS /desk/fno-buildup `oi`) against the spot (cash close) over 1 session (the
    day's own change) and 3 sessions (vs the build-up row of `back_date`). The 1-session state is the headline."""
    if not row:
        return None
    oi, oi_chg = num(row.get("oi")), num(row.get("oi_chg"))
    oi1 = num(row.get("oi_chg_pct"))
    if oi1 is None and oi is not None and oi_chg is not None:
        oi1 = pct_change(oi, oi - oi_chg)
    spot1 = num(row.get("cash_chg_pct"))
    basis = "spot (cash close)"
    if spot1 is None:
        spot1, basis = num(row.get("price_chg_pct")), "near-month future (no cash close)"
    oi3 = pct_change(oi, num((row_back or {}).get("oi")))
    spot3 = pct_change(num(row.get("cash_close")), num((row_back or {}).get("cash_close")))
    st1, st3 = oi_state(spot1, oi1), oi_state(spot3, oi3)
    return {"oi": oi, "price_basis": basis,
            "oi_chg_pct_1s": r2(oi1), "price_chg_pct_1s": r2(spot1), "state_1s": st1,
            "oi_chg_pct_3s": r2(oi3), "price_chg_pct_3s": r2(spot3), "state_3s": st3, "since_3s": back_date,
            "state": st1}


def _contract_day(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Futures rows of one day, one per expiry, nearest first."""
    by: Dict[str, Dict[str, Any]] = {}
    for r in rows or []:
        e = str(r.get("expiry_date") or "")[:10]
        if e and e not in by:
            by[e] = r
    return [by[e] for e in sorted(by)]


def _spot_of(rows: Sequence[Dict[str, Any]], fallback: Optional[float] = None) -> Optional[float]:
    for r in rows or []:
        u = num(r.get("underlying_price"))
        if u is not None and u > 0:
            return u
    return fallback


def by_expiry(rows: Sequence[Dict[str, Any]], spot_fallback: Optional[float] = None) -> List[Dict[str, Any]]:
    """near / next / far futures on the day: price %, OI %, basis % vs spot, state (same thresholds)."""
    legs = _contract_day(rows)
    spot = _spot_of(legs, spot_fallback)
    out = []
    for name, r in zip(("near", "next", "far"), legs):
        close, prev = num(r.get("close_price")), num(r.get("prev_close_price"))
        oi, chg = num(r.get("open_interest")), num(r.get("change_in_oi"))
        price = pct_change(close, prev)
        oip = pct_change(oi, oi - chg) if oi is not None and chg is not None else None
        out.append({"leg": name, "expiry": str(r.get("expiry_date"))[:10], "close": close, "price_chg_pct": r2(price),
                    "oi": oi, "oi_chg_pct": r2(oip), "basis_pct": r2(pct_change(close, spot)), "state": oi_state(price, oip)})
    return out


def _roll_reading(rows: Sequence[Dict[str, Any]]) -> Tuple[Optional[float], Optional[float]]:
    """(% of futures OI in later months than the nearest, next-month premium % vs spot) for one day's futures rows."""
    legs = _contract_day(rows)
    ois = [num(r.get("open_interest")) for r in legs]
    if not legs or any(o is None for o in ois) or sum(ois) <= 0:
        pct = None
    else:
        pct = (sum(ois) - ois[0]) / sum(ois) * 100.0
    spot = _spot_of(legs)
    prem = pct_change(num(legs[1].get("close_price")), spot) if len(legs) > 1 else None
    return pct, prem


def _position(v: Optional[float], past: Sequence[float]) -> Optional[str]:
    if v is None or not past:
        return None
    return "below" if v < min(past) else "above" if v > max(past) else "within"


def rollover_block(rows: Sequence[Dict[str, Any]], day: date, sessions: Sequence[date],
                   past: Sequence[Tuple[str, str, Sequence[Dict[str, Any]]]]) -> Optional[Dict[str, Any]]:
    """In the ROLLOVER_WINDOW_SESSIONS sessions before the nearest expiry (and on expiry day): today's rollover % and
    next-month premium, beside the same readings on the stock's own past expiries at the same number of sessions before
    each. `past`: [(expiry, the day read, that day's futures rows)]. None outside the window."""
    legs = _contract_day(rows)
    if not legs:
        return None
    try:
        near = date.fromisoformat(str(legs[0].get("expiry_date"))[:10])
    except ValueError:
        return None
    n = sum(1 for s in sessions if day < s <= near)
    if near < day or n > ROLLOVER_WINDOW_SESSIONS:
        return None
    pct, prem = _roll_reading(rows)
    hist = []
    for exp, d, rws in past:
        p, pr = _roll_reading(rws)
        if p is not None or pr is not None:
            hist.append({"expiry": exp, "day": d, "pct": r1(p), "next_premium_pct": r2(pr)})
    pcts = [h["pct"] for h in hist if h["pct"] is not None]
    prems = [h["next_premium_pct"] for h in hist if h["next_premium_pct"] is not None]
    return {"near_expiry": near.isoformat(), "sessions_to_expiry": n, "pct": r1(pct),
            "past": hist, "past_range": {"min": min(pcts), "max": max(pcts)} if pcts else None, "position": _position(pct, pcts),
            "next_premium_pct": r2(prem), "past_premium_range": {"min": min(prems), "max": max(prems)} if prems else None,
            "premium_position": _position(prem, prems),
            "basis": f"% of futures OI in later months; past = the stock's last {ROLLOVER_PAST_EXPIRIES} expiries, "
                     f"{n} session(s) before each"}


def sessions_to_expiry(day: Optional[date], expiry: Any, sessions: Sequence[date]) -> Optional[int]:
    """Sessions after `day` up to and including the expiry (0 on expiry day). None when either is unknown or past."""
    if day is None or not expiry:
        return None
    try:
        e = date.fromisoformat(str(expiry)[:10])
    except ValueError:
        return None
    if e < day:
        return None
    return sum(1 for s in sessions if day < s <= e)


def options_expiry(rows: Sequence[Dict[str, Any]], day: date) -> Optional[str]:
    """The expiry the options block reads: the first futures expiry more than OPTIONS_SKIP_EXPIRY_DAYS after the date
    (a contract in its expiry week is distorted), read from the day's own rows, never computed."""
    for r in _contract_day(rows):
        try:
            e = date.fromisoformat(str(r.get("expiry_date"))[:10])
        except ValueError:
            continue
        if (e - day).days > OPTIONS_SKIP_EXPIRY_DAYS:
            return e.isoformat()
    return None


def options_block(rows: Sequence[Dict[str, Any]], expiry: Optional[str]) -> Optional[Dict[str, Any]]:
    """One expiry's options on the day: PCR (put OI ÷ call OI) and its change vs the previous session (from the day's
    own OI minus its change), OI added by side, the strikes with the most OI and the most OI added."""
    side: Dict[str, List[Tuple[float, float, float]]] = {"PE": [], "CE": []}
    for r in rows or []:
        k, oi, chg = num(r.get("strike_price")), num(r.get("open_interest")), num(r.get("change_in_oi"))
        if r.get("option_type") in side and k is not None and oi is not None:
            side[r["option_type"]].append((k, oi, chg or 0.0))
    if not side["PE"] or not side["CE"]:
        return None
    put, call = sum(x[1] for x in side["PE"]), sum(x[1] for x in side["CE"])
    put0, call0 = sum(x[1] - x[2] for x in side["PE"]), sum(x[1] - x[2] for x in side["CE"])
    pcr = put / call if call > 0 else None
    pcr0 = put0 / call0 if call0 > 0 else None

    def top(xs, idx):
        return [x[0] for x in sorted(xs, key=lambda x: (-x[idx], x[0]))[:OPTIONS_TOP_STRIKES] if x[idx] > 0]

    return {"expiry": expiry, "pcr": r2(pcr), "pcr_prev": r2(pcr0),
            "pcr_change": r2(pcr - pcr0) if pcr is not None and pcr0 is not None else None,
            "put_oi_added": sum(x[2] for x in side["PE"]), "call_oi_added": sum(x[2] for x in side["CE"]),
            "max_put_oi_strike": max(side["PE"], key=lambda x: (x[1], -x[0]))[0],
            "max_call_oi_strike": max(side["CE"], key=lambda x: (x[1], -x[0]))[0],
            "most_put_oi_added_strikes": top(side["PE"], 2), "most_call_oi_added_strikes": top(side["CE"], 2),
            "label": OI_LABEL}


def fno_block(is_fno: bool, *, as_of: Optional[str], scan_row: Optional[Dict[str, Any]], back_row: Optional[Dict[str, Any]],
              back_date: Optional[str], futures: Optional[Sequence[Dict[str, Any]]], options: Optional[Sequence[Dict[str, Any]]],
              options_exp: Optional[str], past: Sequence[Tuple[str, str, Sequence[Dict[str, Any]]]], day: Optional[date],
              sessions: Sequence[date]) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """(fno_buildup block, gaps). Non-F&O → (None, []). The headline state is total.state (1 session)."""
    if not is_fno:
        return None, []
    gaps: List[str] = []
    total = total_block(scan_row, back_row, back_date)
    if total is None:
        gaps.append(f"OI build-up: no futures row in the build-up scan on {as_of}" if as_of else "OI build-up: not available")
    elif total["state"] is None:
        gaps.append("OI build-up: the day's spot or total OI change is missing")
    legs = by_expiry(futures or [], num((scan_row or {}).get("cash_close"))) if futures else []
    if futures is None:
        gaps.append("OI build-up by expiry: the futures contracts could not be read")
    roll = rollover_block(futures or [], day, sessions, past) if futures and day else None
    opts = options_block(options or [], options_exp) if options else None
    if futures and options_exp and options is None:
        gaps.append(f"options {options_exp}: could not be read")
    if total is None and not legs:
        return None, gaps
    state = (total or {}).get("state")
    n_exp = sessions_to_expiry(day, (scan_row or {}).get("near_expiry") or (legs[0]["expiry"] if legs else None), sessions)
    in_window = n_exp is not None and n_exp < EXPIRY_WINDOW_SESSIONS
    damped = in_window and state in OI_FALLING_STATES
    text = BUILDUP_TEXT.get(state) if state else None
    out = {"as_of": as_of, "state": state, "text": f"{text} ({EXPIRY_NOTE})" if damped else text,
           "signal": "neutral" if damped else (BUILDUP_SIGNAL.get(state) if state else None),
           "score": BUILDUP_SCORE[NO_CLEAR] if damped else (BUILDUP_SCORE.get(state) if state else None),
           "expiry_window": in_window, "sessions_to_expiry": n_exp, "note": EXPIRY_NOTE if damped else None,
           "total": total, "by_expiry": legs, "rollover": roll, "options_next_expiry": opts,
           "scan": {k: (scan_row or {}).get(k) for k in ("label", "price_chg_pct", "oi_chg_pct", "cash_confirmation", "risk_flags",
                                                         "fut_turnover_cr", "near_expiry")} if scan_row else None}
    return out, gaps


# ── technical and past reactions ──────────────────────────────────────────────────────────────────────────────────

def technical_block(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    fs = num(row.get("final_score"))
    d = row.get("as_of_date")
    return {"as_of": d.isoformat() if isinstance(d, date) else (str(d) if d else None), "stage": row.get("stage"),
            "final_score": r2(fs), "score": r1(clamp(fs * 100.0)) if fs is not None else None}


def past_reactions(body: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The stock's past results reactions (DaaS /desk/events-calendar/history): mean two-session move and its score."""
    if not isinstance(body, dict):
        return None
    moves = []
    for o in body.get("occurrences") or []:
        e, d1 = num((o or {}).get("event_day_pct")), num((o or {}).get("d1_pct"))
        if e is not None and d1 is not None:
            moves.append(((1 + e / 100.0) * (1 + d1 / 100.0) - 1.0) * 100.0)
    mean = sum(moves) / len(moves) if moves else None
    score = r1(clamp(50.0 + PAST_REACTION_PER_PCT * mean)) if mean is not None and len(moves) >= PAST_REACTION_MIN_N else None
    return {"n": len(moves), "mean_two_session_pct": r2(mean), "score": score, "stats": body.get("stats")}


# ── §4c ideas ─────────────────────────────────────────────────────────────────────────────────────────────────────

def phase_of(row: Dict[str, Any], day: date, sessions: Sequence[date]) -> Optional[str]:
    """declared: figures filed with the meeting in the last 3 sessions up to the date; upcoming: meeting on the date
    (not yet declared) or in the next 5 sessions. Else None (not ordered)."""
    try:
        ev = date.fromisoformat(str(row.get("event_date"))[:10])
    except ValueError:
        return None
    ss = sorted(sessions)
    past = [s for s in ss if s <= day][-DECLARED_SESSIONS:]
    ahead = [s for s in ss if s > day][:UPCOMING_SESSIONS]
    if row.get("status") == "declared":
        return "declared" if past and past[0] <= ev <= day else None
    if row.get("status") == "upcoming":
        return "upcoming" if ahead and day <= ev <= ahead[-1] else None
    return None


def idea_parts(row: Dict[str, Any], phase: str) -> Dict[str, Optional[float]]:
    if phase == "declared":
        return {"earnings": (row.get("score") or {}).get("value"), "reaction": (row.get("reaction") or {}).get("score"),
                "oi": (row.get("fno_buildup") or {}).get("score"), "technical": (row.get("technical") or {}).get("score")}
    comps = row.get("components") or {}
    return {"technical": (row.get("technical") or {}).get("score"), "oi": (row.get("fno_buildup") or {}).get("score"),
            "past_reactions": (comps.get("past_reactions") or {}).get("score"), "trend": (comps.get("trend") or {}).get("value")}


def _fmt_day(s: Optional[str]) -> str:
    try:
        return date.fromisoformat(str(s)[:10]).strftime("%d %b").lstrip("0")
    except ValueError:
        return str(s)


def why_text(row: Dict[str, Any], phase: str) -> str:
    bits: List[str] = []
    comps = row.get("components") or {}
    if phase == "declared":
        v = row.get("verdict") or {}
        if v.get("label"):
            bits.append(VERDICT_TEXT[v["label"]] + (f" ({v['intensity'].replace('_', ' ')})" if v.get("intensity") else ""))
        else:
            bits.append(v.get("reason") or "not rated")
        sc = row.get("score") or {}
        if sc.get("value") is not None:
            bits.append(f"earnings score {sc['value']:.0f}")
        rx = row.get("reaction")
        if rx:
            vx = f" at {rx['volume_x']:.1f}× volume" if rx.get("volume_x") is not None else ""
            bits.append(f"{rx['excess_pct']:+.1f} % vs Nifty on {_fmt_day(rx['first_session'])}{vx}")
    else:
        bits.append(f"results on {_fmt_day(row.get('event_date'))}")
        pr = comps.get("past_reactions") or {}
        if pr.get("score") is not None:
            bits.append(f"past results: {pr['mean_two_session_pct']:+.1f} % over two sessions on average (n {pr['n']})")
        tr = comps.get("trend") or {}
        if tr.get("value") is not None:
            bits.append(f"operating trend {tr['value']:.0f}")
    fb = row.get("fno_buildup") or {}
    tot = fb.get("total") or {}
    if fb.get("state") and tot.get("price_chg_pct_1s") is not None and tot.get("oi_chg_pct_1s") is not None:
        bits.append(f"{fb['text']} (spot {tot['price_chg_pct_1s']:+.2f} %, total OI {tot['oi_chg_pct_1s']:+.2f} %)")
    tech = row.get("technical")
    if tech and tech.get("stage"):
        bits.append(f"AI scanner stage {tech['stage']}" + (f" ({tech['score']:.0f})" if tech.get("score") is not None else ""))
    return "; ".join(bits)


def order_ideas(rows: Sequence[Dict[str, Any]], day: date, sessions: Sequence[date], *, fno_list: bool) -> Dict[str, Any]:
    """One ideas list. F&O list: F&O names only, with the OI part. All list: every name, no OI part (its weight spread
    pro rata). A declared name needs its earnings score; any name needs at least half its list's weight present.
    Order: signal, then the higher earnings score, then the symbol."""
    items: List[Dict[str, Any]] = []
    left_out = {"pending": 0, "no_earnings_score": 0, "thin_evidence": 0}
    for row in rows:
        if fno_list and not row.get("fno"):
            continue
        if row.get("status") == "pending":
            left_out["pending"] += 1
            continue
        phase = phase_of(row, day, sessions)
        if phase is None:
            continue
        weights = dict(DECLARED_WEIGHTS if phase == "declared" else UPCOMING_WEIGHTS)
        if not fno_list:
            weights.pop("oi")
        vals = idea_parts(row, phase)
        present = {k: vals[k] for k in weights if vals.get(k) is not None}
        if phase == "declared" and "earnings" not in present:
            left_out["no_earnings_score"] += 1
            continue
        got = sum(weights[k] for k in present)
        if got < MIN_PRESENT_WEIGHT_SHARE * sum(weights.values()):
            left_out["thin_evidence"] += 1
            continue
        signal = sum(weights[k] * present[k] for k in present) / got
        parts = {k: {"value": present.get(k), "weight": round(weights[k] / got * 100.0, 1) if k in present else 0.0}
                 for k in weights}
        items.append({"symbol": row["symbol"], "name": row.get("name"), "phase": phase, "event_date": row.get("event_date"),
                      "signal": r1(signal), "parts": parts, "missing": [k for k in weights if k not in present],
                      "why": why_text(row, phase), "_earn": (row.get("score") or {}).get("value")})
    best: Dict[str, Dict[str, Any]] = {}
    for i in items:                       # one entry per symbol: declared over upcoming, then the later meeting, then the higher signal
        k = (i["phase"] == "declared", str(i["event_date"]), i["signal"])
        cur = best.get(i["symbol"])
        if cur is None or k > (cur["phase"] == "declared", str(cur["event_date"]), cur["signal"]):
            best[i["symbol"]] = i
    items = list(best.values())
    items.sort(key=lambda i: (-i["signal"], -(i["_earn"] if i["_earn"] is not None else -1.0), i["symbol"]))
    for n, i in enumerate(items, 1):
        i["rank"] = n
        i.pop("_earn")
    return {"items": [{"rank": i.pop("rank"), **i} for i in items], "left_out": left_out}
