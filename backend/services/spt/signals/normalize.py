"""Signal normalizer `spt-normalize-v1` (constants.NORMALIZER_VERSION): what a Scan dashboard list mark or strong signal IS,
in the PRD's words (PRD §6.2–§6.3, §7.2; Workflow §5.2 steps 2–4).

LIST_MAP gives every stock list the dashboards record (services/scan_builder/market_dashboard.py DASHBOARDS: Atlas fresh,
Day trade, Early movers; a list is recordable when its rows are stocks) five things:

    category   one of CATEGORIES (PRD §7.2: breakout, reversal, momentum, volume, derivatives, fundamental, breakdown, plus
               pattern for chart patterns)
    family     a stable strategy-family id. Lists that test the same thing share one family (the 52-week-high lists of both
               dashboards; the two "10x volume first 5 min" copies; the two 10 %-down lists), so a stock in both is ONE
               confirmation when the opportunity score counts distinct families (PRD §6.4: "different strategy families must
               remain identifiable")
    timeframe  the finest bars the list's conditions read: "5m", "15m", "1h", "1D" or "1W"
    horizon    "positional" for signal_strength.POSITIONAL_LISTS and every other multi-day setup (daily or weekly structure,
               fundamentals); "intraday" for lists about today's session only: 15-minute breakouts, RSI VWAP, 10x volume in
               the first 5 minutes, early movers, today's strong movers, Nifty 50 top gainers, explosive movement
    direction  "long" by default. Breakdown lists (below the 50- and 200-day averages, 10 % down in a month) are "short"
               (bearish) whatever the mark says: the scan records every list mark as long except SHORT_WIDGETS. For
               SHORT_WIDGETS (open_interest, oi_7: their conditions also pass falling stocks) the recorded mark's own
               `direction` wins

A strong signal (signal_strength.THRESHOLD = 70; signals.record_strong) is its own scanner, STRONG_SCANNER_ID "strength_70":
family "signal_strength", horizon positional (scan-plan-v3 is a positional plan), direction long (the score is long only),
timeframe "1D", category = the category of its lists (`lists_at`): the first list that is a positional list, else the first
mapped list.

Pure: no I/O. A widget id missing from LIST_MAP is not guessed: `for_list` returns mapped False and ingest quarantines the
mark (reason missing_mapping).
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from services.scan_builder import signal_strength as SS
from services.scan_builder.signals import SHORT_WIDGETS

from .. import constants as C

VERSION = C.NORMALIZER_VERSION

CATEGORIES = ("breakout", "reversal", "momentum", "volume", "derivatives", "fundamental", "breakdown", "pattern")
TIMEFRAMES = ("5m", "15m", "1h", "1D", "1W")
POSITIONAL, INTRADAY = "positional", "intraday"
HORIZONS = (POSITIONAL, INTRADAY)
LONG, SHORT = "long", "short"
DIRECTIONS = (LONG, SHORT)
BIAS = {LONG: "bullish", SHORT: "bearish"}

STRONG_SCANNER_ID = "strength_70"
STRONG_SCANNER_NAME = f"Signal strength {SS.THRESHOLD}+ (positional, long)"
STRONG_FAMILY = "signal_strength"
#: The strength score has no version string of its own; this names its threshold and weights, so a change to either is a
#: new score version (services/scan_builder/signal_strength.py THRESHOLD, WEIGHTS).
SCORE_VERSION = ("signal-strength:t{t}:q{quality}-t{trend}-r{reason}-s{size}-p{participation}"
                 .format(t=SS.THRESHOLD, **SS.WEIGHTS))


def _m(category: str, family: str, timeframe: str, horizon: str, direction: str = LONG) -> Dict[str, str]:
    return {"category": category, "family": family, "timeframe": timeframe, "horizon": horizon, "direction": direction}


LIST_MAP: Dict[str, Dict[str, str]] = {
    # ── Atlas fresh (Chartink 247498) ──
    "n50_gainers": _m("momentum", "nifty50_gap_up_momentum", "15m", INTRADAY),
    "long_buildup": _m("derivatives", "fno_long_buildup", "1h", POSITIONAL),
    "strong_movers": _m("momentum", "strong_movers_today", "1D", INTRADAY),
    "good_results": _m("fundamental", "quarterly_results_growth", "1D", POSITIONAL),
    "open_interest": _m("derivatives", "fno_volume_price_move", "1D", POSITIONAL),          # SHORT_WIDGETS
    "vol_10x_5min": _m("volume", "volume_10x_first_5min", "5m", INTRADAY),
    "low_pe_roce": _m("fundamental", "value_low_pe_high_roce", "1D", POSITIONAL),
    "eps_growth": _m("fundamental", "eps_growth", "1D", POSITIONAL),
    "supertrend_rsi": _m("momentum", "supertrend_rsi", "15m", POSITIONAL),
    "triple_bottom": _m("reversal", "triple_bottom", "1D", POSITIONAL),
    "rsi_dwm": _m("momentum", "rsi_daily_weekly_monthly", "1D", POSITIONAL),
    "cup_handle": _m("pattern", "cup_and_handle", "1D", POSITIONAL),
    "tight_consolidation": _m("pattern", "tight_consolidation_breakout", "1D", POSITIONAL),
    "oi_7": _m("derivatives", "fno_volume_price_move", "1D", POSITIONAL),                   # SHORT_WIDGETS
    # ── Day trade (Chartink 503347) ──
    "dt_rsi_vwap": _m("momentum", "rsi_vwap_intraday", "15m", INTRADAY),
    "dt_explosive": _m("momentum", "explosive_move", "1D", INTRADAY),
    "dt_strong": _m("momentum", "five_session_up_streak", "1D", POSITIONAL),
    "dt_high_growth": _m("momentum", "long_term_growth_momentum", "1W", POSITIONAL),
    "dt_short_breakouts": _m("breakout", "short_term_breakout", "1D", POSITIONAL),
    "dt_multiyear": _m("breakout", "multiyear_high_breakout", "1D", POSITIONAL),
    "dt_uptrend_52w": _m("breakout", "high_52w_breakout", "1W", POSITIONAL),
    "dt_below_dma": _m("breakdown", "below_50_and_200_dma", "1D", POSITIONAL, SHORT),
    "dt_12y_high": _m("breakout", "multiyear_high_breakout", "1D", POSITIONAL),              # not computed (no history)
    "dt_52w_breakout": _m("breakout", "high_52w_breakout", "1D", POSITIONAL),
    "dt_vol_price_breakout": _m("volume", "volume_price_breakout", "1D", POSITIONAL),
    "dt_under_300": _m("fundamental", "quality_growth_under_300", "1D", POSITIONAL),
    "dt_down10_large": _m("breakdown", "down_10pct_in_a_month", "1D", POSITIONAL, SHORT),
    "dt_52w_high": _m("breakout", "high_52w_breakout", "1D", POSITIONAL),
    "dt_delivery_volume": _m("volume", "volume_expansion_weekly_rsi", "1D", POSITIONAL),     # no delivery figure is used
    "dt_high_momentum": _m("momentum", "high_momentum", "1D", POSITIONAL),                   # always empty (see its note)
    "dt_down10_all": _m("breakdown", "down_10pct_in_a_month", "1D", POSITIONAL, SHORT),
    "dt_swing_breakout": _m("breakout", "swing_breakout_above_averages", "1D", POSITIONAL),
    "dt_vol_10x_5min": _m("volume", "volume_10x_first_5min", "5m", INTRADAY),
    "dt_breakout_15m": _m("breakout", "intraday_15m_breakout", "15m", INTRADAY),
    # ── Early movers (early_movers.py) ──
    "early_movers": _m("volume", "early_movers", "5m", INTRADAY),
}


def for_list(widget_id: Any, entry_direction: Any = None) -> Dict[str, Any]:
    """The normalized fields of one list mark: {mapped, category, family, timeframe, horizon, direction, bias,
    normalizer_version}. Unmapped → mapped False and every field None (never guessed)."""
    spec = LIST_MAP.get(str(widget_id or ""))
    if spec is None:
        return {"mapped": False, "category": None, "family": None, "timeframe": None, "horizon": None, "direction": None,
                "bias": None, "normalizer_version": VERSION}
    direction = spec["direction"]
    if widget_id in SHORT_WIDGETS and entry_direction in DIRECTIONS:
        direction = entry_direction
    return {"mapped": True, **spec, "direction": direction, "bias": BIAS[direction], "normalizer_version": VERSION}


def strong_category(lists_at: Optional[Iterable[Dict[str, Any]]]) -> Optional[str]:
    """The category of a strong signal: its first positional list's, else its first mapped list's; None when no list maps."""
    ids = [str((x or {}).get("id") or "") for x in (lists_at or [])]
    for wid in ids:
        if wid in SS.POSITIONAL_LISTS and wid in LIST_MAP:
            return LIST_MAP[wid]["category"]
    for wid in ids:
        if wid in LIST_MAP:
            return LIST_MAP[wid]["category"]
    return None


def for_strong(rec: Dict[str, Any]) -> Dict[str, Any]:
    """The normalized fields of a strong signal (see the module docstring). mapped False when none of its lists maps."""
    cat = strong_category(rec.get("lists_at"))
    return {"mapped": cat is not None, "category": cat, "family": STRONG_FAMILY, "timeframe": "1D", "horizon": POSITIONAL,
            "direction": LONG, "bias": BIAS[LONG], "normalizer_version": VERSION}


def families_of(widget_ids: Iterable[str]) -> List[str]:
    """Distinct families of these lists, in first-seen order (unmapped ids are left out)."""
    out: List[str] = []
    for wid in widget_ids:
        fam = (LIST_MAP.get(wid) or {}).get("family")
        if fam and fam not in out:
            out.append(fam)
    return out
