"""The opportunity scanner's rules in one place: every threshold, its version, and the pure functions that apply them.

PRD §5.6: "Thresholds must be configurable and versioned rather than hardcoded into UI components." The routes that use
these numbers (routes/positional.py: GET /api/positional/watchlist, /picks, /scan-universe) send them back with
RULES_VERSION, and the desk shows them from the response; no screen keeps its own copy. Change a number here and bump
RULES_VERSION in the same commit, so a row can always be traced to the rules that produced it.

Two lists are ruled here:

* Setup buckets (WATCHLIST) — the end-of-day positional scanner's watchlist (stock_technical_features + 60 daily bars
  from stock_ohlcv, app database). The values are the ones get_watchlist always used ("smart_v2"), moved here
  unchanged, plus the gap gate PRD §5.6 asks for ("not invalidated by a gap").
* Universe categories (CATEGORIES) — momentum, unusual volume, results-day momentum and F&O candidates, applied to the
  data platform's latest feature row per stock (DaaS GET /v1/features/scan-snapshot: nidp.stock_features_daily, the
  same day's NSE bhavcopy row from nidp.prices_eod, nidp.security_reference_daily and nidp.event_calendar), after the
  eligibility gates in UNIVERSE.

Missing data is never a neutral value: a stock without a figure a rule needs does not pass that rule and is counted
as missing, and a stock without a figure an eligibility gate needs is excluded under that gate's own reason.
"""
from __future__ import annotations

import bisect
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

RULES_VERSION = "scan-rules.v1 (2026-10-14)"

# ── setup buckets: GET /api/positional/watchlist ──────────────────────────────
WATCHLIST: Dict[str, Any] = {
    "classifier": "smart_v2",
    # First pass over stock_technical_features on the latest features date.
    "candidates": {"min_close": 5.0, "excluded_stages": ["WEAK", "EXTENDED"], "top_by_score": 80, "min_bars": 30},
    # Precedence: confirmed → pre-breakout → accumulation → continuation; the first bucket a stock passes wins.
    "breakout_confirmed": {"dist_breakout_pct_min": 0.0, "dist_breakout_pct_max": 3.0, "volume_spike_min": 1.5,
                           "stages": ["BREAKOUT", "EARLY_BREAKOUT"],
                           # PRD §5.6: a breakout made on a gap above the previous close by more than this is not
                           # confirmed (open of the scan session ÷ the previous close − 1, in %).
                           "max_gap_up_pct": 5.0},
    "pre_breakout": {"dist_breakout_pct_min": -2.0, "dist_breakout_pct_below": 0.0, "volume_spike_min": 1.2,
                     "volume_slope_above": -3.0},
    "true_accumulation": {"range_15d_below_pct": 8.0, "volume_slope_below": 0.0, "higher_lows_min": 1,
                          "upper_wick_below": 0.5, "close_vs_sma50_min": 0.97},
    "trend_continuation": {"dist_ema20_min_pct": 0.0, "dist_ema20_max_pct": 4.0, "upper_wick_below": 0.5},
    # volume_spike = mean volume of the last 3 sessions ÷ mean of the 20 before; stops sit this many ATR(14) below
    # the bucket's reference level (the breakout level, the close or the 20-day EMA).
    "volume_spike_sessions": [3, 20],
    "stop_atr_multiple": 1.5,
}

# ── liquidity, risk class, eligible universe ──────────────────────────────────
# The desk's liquidity gate (owner decision 2026-10-14: stays ₹10 Cr).
LIQUIDITY: Dict[str, Any] = {
    "min_traded_value_cr": 10.0,
    "sessions": 20,
    "definition": "Mean of close × volume over the last 20 sessions, ₹ crore a day; none with fewer than 20 sessions.",
}

# Risk class from ATR(14) as a percent of the close (owner default 2026-10-14).
RISK_BANDS: Dict[str, Any] = {"basis": "ATR(14) as a percent of the close", "low_below_pct": 2.0, "high_above_pct": 4.0}

# The eligible universe for the universe categories and the model rank. Gates are applied in this order and a stock
# is counted under the first one it fails.
UNIVERSE: Dict[str, Any] = {
    "series": ["EQ", "BE"],
    "exclude_etf": True,
    # A 2% or 5% band is NSE's tight circuit limit (surveillance or thin trading); F&O stocks carry no band.
    "min_price_band_pct": 10.0,
    # Closed within this fraction of its band limit (up or down): the price was capped, so the move is not tradable.
    "band_limit_tolerance_pct": 0.1,
    "exclusion_order": ["missing_price", "no_traded_value", "no_reference", "series", "etf", "price_band",
                        "at_band_limit", "illiquid"],
}

CATEGORIES: Dict[str, Dict[str, Any]] = {
    "momentum": {"return_20d_min_pct": 5.0, "close_above_sma50": True, "sma50_slope_above": 0.0,
                 "rank_by": "return_20d_pct"},
    "unusual_volume": {"vol_z20_min": 2.0, "rank_by": "vol_z20"},
    "results_day": {"event_type": "quarterly_results", "window_calendar_days": 7, "return_5d_min_pct": 3.0,
                    "vol_z20_min": 1.0, "rank_by": "return_5d_pct"},
    # F&O-eligible (NSE lot-size file, nidp.security_reference_daily.fno_eligible) and in another category or a
    # scanner setup.
    "fno": {"requires_fno_eligible": True, "rank_by": "traded_value_cr_20d"},
}
MAX_ROWS_PER_CATEGORY = 50

# What a rule reads, for the "missing" count.
_NEEDS: Dict[str, Sequence[str]] = {
    "momentum": ("return_20d_pct", "close", "sma50", "sma50_slope"),
    "unusual_volume": ("vol_z20",),
    "results_day": ("return_5d_pct", "vol_z20"),
}


def public_rules() -> Dict[str, Any]:
    """Everything a screen may show about the rules, with the version."""
    return {"version": RULES_VERSION, "watchlist": WATCHLIST, "liquidity": LIQUIDITY, "risk_bands": RISK_BANDS,
            "universe": UNIVERSE, "categories": CATEGORIES, "max_rows_per_category": MAX_ROWS_PER_CATEGORY}


# ── small helpers ─────────────────────────────────────────────────────────────

def _f(v: Any) -> Optional[float]:
    """A finite float, or None (never 0 for a missing figure)."""
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and x not in (float("inf"), float("-inf")) else None


def _d(v: Any) -> Optional[date]:
    if isinstance(v, date):
        return v
    if isinstance(v, str) and len(v) >= 10:
        try:
            return date.fromisoformat(v[:10])
        except ValueError:
            return None
    return None


def risk_class(atr_pct: Any) -> Optional[str]:
    """low / medium / high from ATR% with RISK_BANDS; None when ATR% is missing."""
    a = _f(atr_pct)
    if a is None or a < 0:
        return None
    if a < RISK_BANDS["low_below_pct"]:
        return "low"
    if a > RISK_BANDS["high_above_pct"]:
        return "high"
    return "medium"


def liquidity_class(traded_value_cr: Any) -> Optional[str]:
    """liquid (≥ the gate) / thin; None when there is no traded-value figure."""
    v = _f(traded_value_cr)
    if v is None:
        return None
    return "liquid" if v >= LIQUIDITY["min_traded_value_cr"] else "thin"


def gap_up_pct(open_price: Any, prev_close: Any) -> Optional[float]:
    o, p = _f(open_price), _f(prev_close)
    if o is None or p is None or p <= 0 or o <= 0:
        return None
    return (o / p - 1.0) * 100.0


# ── setup buckets ─────────────────────────────────────────────────────────────

def classify_setup(*, stage: Optional[str], close: float, sma50: Optional[float], ema20: Optional[float],
                   dist_breakout_pct: Optional[float], dist_ema20_pct: Optional[float], volume_spike: Optional[float],
                   volume_slope: Optional[float], range_15d: Optional[float], higher_lows: int,
                   upper_wick: Optional[float], gap_pct: Optional[float]) -> Optional[str]:
    """The watchlist bucket a stock falls in, or None. Same precedence and thresholds as WATCHLIST."""
    bc, pb = WATCHLIST["breakout_confirmed"], WATCHLIST["pre_breakout"]
    ta, tc = WATCHLIST["true_accumulation"], WATCHLIST["trend_continuation"]
    if (dist_breakout_pct is not None and bc["dist_breakout_pct_min"] <= dist_breakout_pct <= bc["dist_breakout_pct_max"]
            and volume_spike is not None and volume_spike >= bc["volume_spike_min"]
            and stage in bc["stages"]
            and (gap_pct is None or gap_pct <= bc["max_gap_up_pct"])):
        return "breakout_confirmed"
    if (dist_breakout_pct is not None and pb["dist_breakout_pct_min"] <= dist_breakout_pct < pb["dist_breakout_pct_below"]
            and volume_spike is not None and volume_spike >= pb["volume_spike_min"]
            and (volume_slope is None or volume_slope > pb["volume_slope_above"])):
        return "pre_breakout"
    if (range_15d is not None and range_15d < ta["range_15d_below_pct"]
            and volume_slope is not None and volume_slope < ta["volume_slope_below"]
            and higher_lows >= ta["higher_lows_min"]
            and (upper_wick is None or upper_wick < ta["upper_wick_below"])
            and (sma50 is None or close > sma50 * ta["close_vs_sma50_min"])):
        return "true_accumulation"
    if (sma50 is not None and ema20 is not None and close > ema20 > sma50
            and dist_ema20_pct is not None and tc["dist_ema20_min_pct"] <= dist_ema20_pct <= tc["dist_ema20_max_pct"]
            and (upper_wick is None or upper_wick < tc["upper_wick_below"])):
        return "trend_continuation"
    return None


# ── eligible universe and categories ──────────────────────────────────────────

def exclusion(row: Mapping[str, Any]) -> Optional[str]:
    """The first eligibility gate the snapshot row fails (UNIVERSE["exclusion_order"]), or None when eligible."""
    close, prev = _f(row.get("close")), _f(row.get("prev_close"))
    if close is None or close <= 0 or prev is None or prev <= 0:
        return "missing_price"
    tv = _f(row.get("traded_value_cr_20d"))
    if tv is None:
        return "no_traded_value"
    if not row.get("has_reference"):
        return "no_reference"
    if (row.get("series") or "") not in UNIVERSE["series"]:
        return "series"
    if UNIVERSE["exclude_etf"] and row.get("is_etf") is True:
        return "etf"
    band = _f(row.get("price_band_pct"))
    if band is not None and band < UNIVERSE["min_price_band_pct"]:
        return "price_band"
    if band is not None and at_band_limit(close, prev, band):
        return "at_band_limit"
    if tv < LIQUIDITY["min_traded_value_cr"]:
        return "illiquid"
    return None


def at_band_limit(close: float, prev_close: float, band_pct: float) -> bool:
    """True when the close sits at the upper or lower band limit (within the tolerance)."""
    move = abs(close / prev_close - 1.0) * 100.0
    return move >= band_pct - UNIVERSE["band_limit_tolerance_pct"]


def _missing(row: Mapping[str, Any], fields: Iterable[str]) -> bool:
    return any(_f(row.get(k)) is None for k in fields)


def in_momentum(row: Mapping[str, Any]) -> bool:
    c = CATEGORIES["momentum"]
    r20, close, sma50, slope = (_f(row.get(k)) for k in ("return_20d_pct", "close", "sma50", "sma50_slope"))
    if r20 is None or close is None or sma50 is None or slope is None:
        return False
    return r20 >= c["return_20d_min_pct"] and (close > sma50 if c["close_above_sma50"] else True) and slope > c["sma50_slope_above"]


def in_unusual_volume(row: Mapping[str, Any]) -> bool:
    z = _f(row.get("vol_z20"))
    return z is not None and z >= CATEGORIES["unusual_volume"]["vol_z20_min"]


def results_window(as_of: date) -> Dict[str, str]:
    days = CATEGORIES["results_day"]["window_calendar_days"]
    return {"from": (as_of - timedelta(days=days - 1)).isoformat(), "to": as_of.isoformat()}


def _in_window(results_date: Any, as_of: date) -> bool:
    """A results date on one of the window's calendar days, the scan date included."""
    when = _d(results_date)
    return when is not None and when <= as_of and (as_of - when).days < CATEGORIES["results_day"]["window_calendar_days"]


def in_results_day(row: Mapping[str, Any], as_of: date) -> bool:
    c = CATEGORIES["results_day"]
    if not _in_window(row.get("last_results_date"), as_of):
        return False
    r5, z = _f(row.get("return_5d_pct")), _f(row.get("vol_z20"))
    return r5 is not None and z is not None and r5 >= c["return_5d_min_pct"] and z >= c["vol_z20_min"]


def evaluate(rows: Sequence[Mapping[str, Any]], as_of: date, setup_symbols: Iterable[str] = ()) -> Dict[str, Any]:
    """Apply the gates and the categories to the snapshot rows.

    Returns {"rows": {symbol: annotated row}, "universe": counts, "categories": {key: {total, shown, symbols,
    missing}}}. Every row (eligible or not) is annotated with eligible, exclusion, risk_class, liquidity_class and the
    categories it is in; only eligible rows can be in a category. `setup_symbols` are the scanner's own setups, which
    count toward F&O candidates.
    """
    setups = {s.upper() for s in setup_symbols}
    out: Dict[str, Dict[str, Any]] = {}
    excluded = {k: 0 for k in UNIVERSE["exclusion_order"]}
    members: Dict[str, List[str]] = {k: [] for k in CATEGORIES}
    missing = {k: 0 for k in _NEEDS}
    fno_eligible = 0
    for raw in rows:
        sym = str(raw.get("symbol") or "").upper()
        if not sym or sym in out:
            continue
        r = dict(raw)
        why = exclusion(r)
        r["eligible"] = why is None
        r["exclusion"] = why
        r["risk_class"] = risk_class(r.get("atr_pct"))
        r["liquidity_class"] = liquidity_class(r.get("traded_value_cr_20d"))
        r["categories"] = []
        if why is not None:
            excluded[why] += 1
        else:
            if r.get("fno_eligible") is True:
                fno_eligible += 1
            for key, test in (("momentum", in_momentum), ("unusual_volume", in_unusual_volume),
                              ("results_day", lambda x: in_results_day(x, as_of))):
                if test(r):
                    r["categories"].append(key)
                    members[key].append(sym)
                    continue
                # Results-day only reads its figures for a stock with results in the window.
                if key == "results_day" and not _in_window(r.get("last_results_date"), as_of):
                    continue
                if _missing(r, _NEEDS[key]):
                    missing[key] += 1
            if r.get("fno_eligible") is True and (r["categories"] or sym in setups):
                r["categories"].append("fno")
                members["fno"].append(sym)
        out[sym] = r

    categories: Dict[str, Any] = {}
    for key, syms in members.items():
        rank_by = CATEGORIES[key]["rank_by"]
        ordered = sorted(syms, key=lambda s: (-(_f(out[s].get(rank_by)) if _f(out[s].get(rank_by)) is not None else float("-inf")), s))
        categories[key] = {"total": len(ordered), "shown": min(len(ordered), MAX_ROWS_PER_CATEGORY),
                           "symbols": ordered[:MAX_ROWS_PER_CATEGORY], "rank_by": rank_by,
                           "missing": missing.get(key)}
    total = len(out)
    eligible = sum(1 for r in out.values() if r["eligible"])
    return {"rows": out,
            "universe": {"total": total, "eligible": eligible, "excluded": excluded, "fno_eligible": fno_eligible},
            "categories": categories}


def rank_percentiles(values: Mapping[str, Optional[float]]) -> Dict[str, Optional[float]]:
    """Percentile of each value among the others: 100 × (others below + ½ × others equal) ÷ (n − 1), one decimal.

    The highest of n distinct values is 100.0, the lowest 0.0; a lone value has no rank (None). Symbols whose value is
    None are not ranked and do not count in n.
    """
    known = {s: v for s, v in values.items() if v is not None}
    n = len(known)
    out: Dict[str, Optional[float]] = {s: None for s in values}
    if n < 2:
        return out
    ordered = sorted(known.values())
    for s, v in known.items():
        below = bisect.bisect_left(ordered, v)
        equal_others = bisect.bisect_right(ordered, v) - below - 1
        out[s] = round(100.0 * (below + 0.5 * equal_others) / (n - 1), 1)
    return out
