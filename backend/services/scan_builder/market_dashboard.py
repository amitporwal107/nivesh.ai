"""Realtime scan dashboards (docs/scan_builder/DESIGN.md §8, §9), on our data: "atlas" = the 17 widgets of Chartink dashboard
247498, "daytrade" = the 20 widgets of Chartink dashboard 503347 (the owner's public copy of his private 225969).

Only the widget DEFINITIONS come from Chartink (docs/scan_builder/chartink_247498/, chartink_503347/); every number is ours:
  * prices: NSE end-of-day bars (NIDP warehouse, split/bonus adjusted) with TODAY's candle from Kite — live in the session,
    the saved Kite close after it (data.ScanData.today, the owner's 29 Oct rule);
  * fundamentals: NIDP feature store (DaaS /stocks/screener), as of the last end-of-day;
  * company results: DaaS /financials/{symbol}, loaded once a day in the background (data.ScanData.results_fields);
  * 15-minute and 1-hour conditions: Kite intraday candles (intraday.intraday_values), cached and rate-limited;
  * index levels: Kite (indices.index_result).
One computation every CACHE_S seconds per worker is shared by every viewer (get_dashboard). Each widget's criteria are written
from its own definition (criteria_lines), so the text on screen is the rule that was run. Read-only: no order is ever placed.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import engine
from . import service as SV
from . import early_movers as EM
from . import signals as SIG
from . import signal_strength as SS
from . import spec as S
from .data import SOURCE_PRICES, SOURCE_TODAY, DataUnavailable, ScanData

logger = logging.getLogger(__name__)

CACHE_S = 8.0                 # one computation per worker per this many seconds, shared by every viewer
STALE_OK_S = 300.0            # a failed refresh keeps serving the last good answer this long, with a warning
REFRESH_SECONDS = SV.REFRESH_SECONDS
LIMIT = 500
UNIVERSE_LABEL = {"cash": "All NSE stocks", "fno": "F&O stocks", "nifty50": "Nifty 50"}
INDEX_NAMES = ("NIFTY 50", "NIFTY BANK")
MARKETCAP_BANDS = (("Largecap", 1, 100), ("Midcap", 101, 250), ("Smallcap", 251, None))
RESULTS_PENDING = "Company results are loading (the first load of the day takes about a minute)."

Need = Tuple[str, str, Dict[str, Any], int]


# ── Definitions ─────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class IntradayRule:
    """Conditions on intraday candles, applied to the stocks that pass the daily part. `test(values, close, prev_close)`
    decides a stock; None means the rule only fills a column (Today's strong movers' 15m pos %)."""
    interval: str                                   # "15minute" | "60minute"
    lookback_days: int
    needs: List[Need]
    lines: List[str]
    test: Optional[Callable[[Dict[str, Optional[float]], float, float], bool]] = None


@dataclass
class FlowRule:
    """A condition on today's trades by the side that initiated them (TrueData ticks with best bid/ask, tick_flow.py), applied
    to the stocks that pass everything else. `test(values)` decides a stock from {buy_trades, sell_trades, ...}."""
    lines: List[str]
    test: Callable[[Dict[str, Optional[float]]], bool]


@dataclass
class Widget:
    id: str
    chartink_id: str
    title: str
    kind: str                                       # scan | strong | groups_ad | groups_vol | indices | early | not_computed
    universe: str                                   # cash | fno | nifty50
    spec: Optional[Dict[str, Any]] = None
    intraday: Optional[IntradayRule] = None
    flow: Optional[FlowRule] = None
    lines: List[Tuple[str, int, bool, Optional[str]]] = field(default_factory=list)   # (text, level, applied, note)
    note: Optional[str] = None
    partial_note: Optional[str] = None              # a condition that cannot be applied on our data: always Partial, saying why
    universe_note: Optional[str] = None             # on the "Universe:" line (e.g. a Chartink segment that is not published)

    @property
    def uses_results(self) -> bool:
        return bool(self.spec and S.fundamentals_in(self.spec) & set(S.RESULT_FIELDS))


m, n, F, x = S.measure, S.number, S.fundamental, S.expr
CHG = x(m("close"), "-", m("close", 1), "/", m("close", 1), "*", n(100))
DEFAULT_COLUMNS = [
    {"id": "c_chg", "alias": "% Change", "enabled": True, "format": "pct", "expr": CHG},
    {"id": "c_price", "alias": "Price", "enabled": True, "format": "price", "expr": x(m("close"))},
    {"id": "c_vol", "alias": "Volume", "enabled": True, "format": "volume", "expr": x(m("volume"))},
]
STRONG_COLUMNS = DEFAULT_COLUMNS + [
    {"id": "c_cci", "alias": "CCI", "enabled": True, "format": "number", "expr": x(m("cci", period=20))},
    {"id": "c_adx", "alias": "ADX", "enabled": True, "format": "number", "expr": x(m("adx", period=14))},
    {"id": "c_rsi", "alias": "RSI", "enabled": True, "format": "number", "expr": x(m("rsi", period=14))},
    {"id": "c_smav", "alias": "SMA(volume, 20)", "enabled": True, "format": "volume", "expr": x(m("sma", source="volume", period=20))},
]


def _f(fid: str, left: Dict[str, Any], op: str, right: Dict[str, Any]) -> Dict[str, Any]:
    return S.flt(fid, left, op, right)


def _grp(gid: str, children: List[Dict[str, Any]], join: str = "all", comment: str = "") -> Dict[str, Any]:
    g = S.group(gid, children, join=join)
    g["comment"] = comment
    return g


def _spec(name: str, universe: str, children: List[Dict[str, Any]], columns=None) -> Dict[str, Any]:
    return S.validate({"version": 1, "name": name, "description": "", "filters": S.group("root", children, universe=universe),
                       "columns": columns or DEFAULT_COLUMNS, "sort": {"column": "c_chg", "dir": "desc"}, "limit": LIMIT})


def _n50_test(v: Dict[str, Optional[float]], close: float, prev: float) -> bool:
    return close > v["first_high"] and close > v["ema21"]


def _hourly_dmi_test(v: Dict[str, Optional[float]], close: float, prev: float) -> bool:
    return v["dip"] > v["dim"] and v["adx"] > v["dim"] and v["adx"] < v["dip"]


def _st15_test(v: Dict[str, Optional[float]], close: float, prev: float) -> bool:
    return v["st0"] < close and v["st1"] >= prev


def _first5_test(v: Dict[str, Optional[float]], close: float, prev: float) -> bool:
    return v["first_vol"] > 10 * v["sma1000"]


def _ask_side_test(v: Dict[str, Optional[float]]) -> bool:
    buy, sell = v.get("buy_trades"), v.get("sell_trades")
    return buy is not None and sell is not None and buy > sell          # ratio > 1, written without dividing by zero


def build_widgets() -> List[Widget]:
    """The 17 widgets in the dashboard's order (Chartink layout, row by row)."""
    W: List[Widget] = []
    W.append(Widget("mcap_ad", "3072994", "Marketcap Advances % / Declines", "groups_ad", "cash", lines=[
        ("Grouped by market cap: rank 1–100 Largecap, 101–250 Midcap, 251+ Smallcap (latest market cap)", 0, True, None),
        ("Advances = share of the group's stocks with Close > 1 day ago Close × 100", 0, True, None),
        ("Declines = share of the group's stocks with Close < 1 day ago Close × 100", 0, True, None)]))
    W.append(Widget("pos_neg_vol", "3072995", "Positive vs Negative volumes (in lacs)", "groups_vol", "cash", lines=[
        ("Grouped by market cap: rank 1–100 Largecap, 101–250 Midcap, 251+ Smallcap (latest market cap)", 0, True, None),
        ("Positive volume = sum of Volume where Close > 1 day ago Close ÷ 1,00,000", 0, True, None),
        ("Negative volume = sum of Volume where Close < 1 day ago Close ÷ 1,00,000", 0, True, None),
        ("+-VOL = Positive volume − Negative volume", 0, True, None)]))
    W.append(Widget("index_stats", "3073022", "Index stats", "indices", "cash", lines=[
        ("NIFTY 50 and NIFTY BANK: last price (Ltp) and % change against the previous close", 0, True, None)]))
    W.append(Widget("n50_gainers", "2556934", "Nifty 50 Top Gainers", "scan", "nifty50", spec=_spec("n50", "nifty50", [
        _f("a", x(m("open")), "gt", x(m("close", 1))),
        _f("b", x(m("volume")), "gt", x(n(200000))),
        _f("c", x(m("rsi", period=14)), "gt", x(n(55)))]),
        intraday=IntradayRule("15minute", 5, [("first_high", "first_high", {}, 0),
                                              ("ema21", "ema", {"source": "close", "period": 21}, 0)],
                              ["Close > today's first 15-minute candle High", "Close > 15-minute EMA(close, 21)"], _n50_test)))
    W.append(Widget("long_buildup", "2850641", "Long Build Up (fresh)", "scan", "fno", spec=_spec("lbu", "fno", []),
                    intraday=IntradayRule("60minute", 20, [("adx", "adx", {"period": 14}, 0), ("dip", "di_plus", {"period": 14}, 0),
                                                           ("dim", "di_minus", {"period": 14}, 0)],
                                          ["1-hour +DI(14) > 1-hour −DI(14)", "1-hour ADX(14) > 1-hour −DI(14)",
                                           "1-hour ADX(14) < 1-hour +DI(14)"], _hourly_dmi_test)))
    W.append(Widget("strong_movers", "3072992", "Today's strong movers", "strong", "cash", spec=_spec("strong", "cash", [
        _f("a", x(m("volume")), "gt", x(m("sma", source="volume", period=20), "*", n(2))),
        _f("b", x(F("market_cap_cr")), "gt", x(n(40))),
        _f("c", x(m("close")), "gt", x(n(10))),
        _f("d", x(m("close")), "lt", x(n(1000))),
        _f("e", x(m("volume")), "gt", x(n(50000))),
        _f("g", x(m("close")), "gt", x(m("sma", source="close", period=44))),
        _f("h", x(m("macd_line", slow=26, fast=12, signal=9)), "gt", x(m("macd_signal", slow=26, fast=12, signal=9))),
        _f("i", x(m("di_plus", period=14)), "gt", x(m("di_minus", period=14))),
        _f("j", x(m("cci", period=20)), "gt", x(n(100))),
        _f("k", x(m("cci", 1, period=20)), "lte", x(n(100))),
        _f("l", x(m("supertrend", period=7, multiplier=3)), "lt", x(m("close"))),
        _f("o", x(m("psar", start=0.02, increment=0.02, max=0.2)), "lt", x(m("close"))),
        _f("p", x(m("adx", period=14)), "gt", x(n(25)))], columns=STRONG_COLUMNS),
        intraday=IntradayRule("15minute", 2, [("pos15", "close_in_range", {}, 0)],
                              ["Column 15m pos % = (Close − Low) ÷ (High − Low) × 100 of the latest 15-minute candle; sorted by it"]),
        lines=[("Column Day pos % = (Close − Low) ÷ (High − Low) × 100 of today's candle; V% = (Volume − SMA(volume, 20)) ÷ "
                "SMA(volume, 20) × 100; Equity = Market cap ÷ Close", 0, True, None)]))
    W.append(Widget("good_results", "2737396", "Good quarter result stocks", "scan", "cash", spec=_spec("gq", "cash", [
        _f("a", x(F("q_pat")), "gt", x(F("q1_pat"))),
        _f("b", x(F("q_pat")), "gt", x(F("q4_pat"))),
        _f("c", x(m("close")), "gt", x(n(50))),
        _f("d", x(m("volume")), "gt", x(n(100000))),
        _f("e", x(F("market_cap_cr")), "gt", x(n(400))),
        _f("g", x(m("close")), "gt", x(m("ema", source="close", period=50))),
        _f("h", x(m("rsi", period=14)), "gt", x(n(50))),
        _f("i", x(m("close")), "gte", x(n(1.3), "*", m("min", tf="1w", source="low", period=52))),
        _f("j", x(F("roce_pct")), "gt", x(n(15))),
        _f("k", x(F("y_eps")), "gt", x(n(20))),
        _f("l", x(F("debt_to_equity")), "lt", x(n(1)))])))
    W.append(Widget("open_interest", "3044849", "Open interest", "scan", "fno", spec=_spec("oi", "fno", [
        _f("a", x(m("volume")), "gt", x(m("ema", source="close", period=10), "*", n(5))),
        _grp("or1", [_f("b", x(m("close")), "gt", x(m("close", 1), "*", n(1.05))),
                     _f("c", x(m("close")), "lt", x(m("close", 1), "*", n(0.95)))], join="any")])))
    W.append(Widget("vol_10x_5min", "2653943", "10x volume first 5 min", "scan", "cash", spec=_spec("v10", "cash", [
        _f("a", x(m("volume")), "gt", x(n(1000000))),
        _f("b", x(m("open")), "gte", x(n(50)))]),
        intraday=IntradayRule("5minute", 15, [("first_vol", "first_volume", {}, 0),
                                             ("sma1000", "sma", {"source": "volume", "period": 1000}, 1)],
                              ["Today's first 5-minute candle Volume > 10 × SMA(volume, 1000) of 5-minute candles, as of the "
                               "candle before the latest"], _first5_test),
        flow=FlowRule(["Trades initiated at the ask ÷ trades initiated at the bid > 1 (today's TrueData tick prints, about "
                       "one a second rather than every exchange trade: at or above the ask = initiated at the ask, at or below "
                       "the bid = initiated at the bid, inside the spread by the mid, at the mid by the tick test; while "
                       "TrueData is unavailable, Kite's live ticks sided the same way against the bid/ask before each trade)"],
                      _ask_side_test)))
    W.append(Widget("low_pe_roce", "2798275", "Low PE and High ROCE", "scan", "cash", spec=_spec("lowpe", "cash", [
        _f("a", x(F("pe_ttm")), "lt", x(n(15))),
        _f("b", x(F("roce_pct")), "gt", x(n(15))),
        _f("c", x(F("ttm_pat")), "gt", x(n(20))),
        _f("d", x(F("y_pat")), "gt", x(n(1000))),
        _f("e", x(F("market_cap_cr")), "gt", x(n(10000))),
        _f("g", x(F("q_pat")), "gt", x(n(100)))])))
    W.append(Widget("eps_growth", "2774840", "Eps growth", "scan", "fno", spec=_spec("eps", "fno", [
        _f("a", x(F("y_eps")), "gt", x(F("py_eps"))),
        _f("b", x(F("q_pat")), "gt", x(F("y_pat"))),
        _f("c", x(F("y_eps"), "/", F("py_eps")), "gt", x(n(1.5)))])))
    W.append(Widget("supertrend_rsi", "2750391", "Supertrend RSI scan", "scan", "cash", spec=_spec("st", "cash", [
        _f("c", x(m("rsi", period=14)), "gt", x(n(50))),
        _f("d", x(m("volume")), "gt", x(n(500000))),
        _f("e", x(F("market_cap_cr")), "gt", x(n(5000))),
        _f("g", x(F("y_eps"), "/", F("py_eps")), "gt", x(n(1.25))),
        _f("h", x(F("roce_pct")), "gt", x(n(15))),
        _f("i", x(F("market_cap_cr")), "gt", x(n(2000))),
        _f("j", x(F("q_pbdt")), "gt", x(n(100)))]),
        intraday=IntradayRule("15minute", 5, [("st0", "supertrend", {"period": 7, "multiplier": 3}, 0),
                                              ("st1", "supertrend", {"period": 7, "multiplier": 3}, 1)],
                              ["Latest 15-minute Supertrend(7, 3) < Close",
                               "Previous 15-minute Supertrend(7, 3) ≥ 1 day ago Close"], _st15_test)))
    W.append(Widget("triple_bottom", "2894893", "Triple bottom", "scan", "fno", spec=_spec("tb", "fno", [
        _f("a", x(m("close")), "gt", x(m("ema", 50, source="close", period=40))),
        _f("b", x(m("rsi", period=14)), "gt", x(n(50))),
        _f("c", x(m("macd_line", slow=26, fast=12, signal=9)), "gt", x(m("macd_signal", slow=26, fast=12, signal=9))),
        _f("d", x(m("adx", period=14)), "gt", x(n(20))),
        _f("e", x(m("volume")), "gt", x(n(1.5))),
        _grp("g57960", [_f("g1", x(m("volume")), "gt", x(m("sma", source="volume", period=50))),
                        _f("g2", x(F("q_pbdt")), "gt", x(n(100)))],
             comment="Chartink applies this group to its segment 57960, which is not published; applied to the same stocks")])))
    W.append(Widget("rsi_dwm", "2750384", "RSI ABOVE 50 - DAILY, WEEKLY AND MONTHLY", "scan", "cash", spec=_spec("rsi", "cash", [
        _f("a", x(m("rsi", period=14)), "gt", x(n(70))),
        _f("b", x(m("rsi", tf="1w", period=14)), "gt", x(n(50))),
        _f("c", x(F("market_cap_cr")), "gt", x(n(10000)))])))
    W.append(Widget("cup_handle", "2804704", "Cup & Handle Pattern", "scan", "cash", spec=_spec("cup", "cash", [
        _f("a", x(m("high", 7, tf="1M")), "lt", x(m("high", 6, tf="1M"))),
        _f("b", x(m("high", 7, tf="1M")), "lt", x(m("high", 5, tf="1M"))),
        _f("c", x(m("high", 5, tf="1M")), "lt", x(m("high", 4, tf="1M"))),
        _f("d", x(m("high", 5, tf="1M")), "lt", x(m("high", 3, tf="1M"))),
        _f("e", x(m("high", 3, tf="1M")), "gt", x(m("high", 2, tf="1M"))),
        _f("g", x(m("high")), "gt", x(m("high", 6, tf="1M"))),
        _f("h", x(m("volume")), "gt", x(n(100000)))])))
    W.append(Widget("tight_consolidation", "2807387", "Long tight consolidation stocks", "scan", "cash", spec=_spec("tight", "cash", [
        _f("a", x(m("close")), "gte", x(m("high", 1))),
        _f("b", x(m("close")), "gt", x(m("high"), "*", n(0.75))),
        _f("c", x(m("max", tf="1w", source="close", period=4)), "lt", x(m("close"), "*", n(1.03))),
        _f("d", x(m("min", tf="1w", source="close", period=4)), "gt", x(m("close"), "*", n(0.95))),
        _f("e", x(m("max", tf="1w", source="open", period=4)), "lt", x(m("close"), "*", n(1.03))),
        _f("g", x(m("min", tf="1w", source="open", period=4)), "gt", x(m("close"), "*", n(0.95))),
        _f("h", x(F("market_cap_cr")), "gt", x(n(10000)))])))
    W.append(Widget("oi_7", "2854924", "Open interest 7", "scan", "fno", spec=_spec("oi7", "fno", [
        _f("a", x(m("volume")), "gt", x(m("ema", source="close", period=8), "*", n(5))),
        _grp("or1", [
            _f("b", x(m("close")), "gt", x(m("close", 1), "*", n(1.012))),
            _grp("and2", [
                _f("c", x(m("close")), "lt", x(m("close", 1), "*", n(0.98))),
                _f("d", x(m("stoch_k", period=14)), "gt", x(n(30))),
                _f("e", x(m("stoch_k", 1, period=14)), "lte", x(n(30))),
                _f("g", x(m("volume")), "gt", x(n(400000))),
                _f("h", x(m("adx", period=14)), "gt", x(n(42)))])], join="any")])))
    return W


WIDGETS = build_widgets()


def _rsi_vwap_test(v: Dict[str, Optional[float]], close: float, prev: float) -> bool:
    return v["rsi30"] > 60 and v["vwap"] < v["c15"]


def _breakout15_test(v: Dict[str, Optional[float]], close: float, prev: float) -> bool:
    return v["c0"] > v["mx20"] and v["v0"] > v["smav20"]


HISTORY_NOTE = "our NSE daily history starts in April 2024 (about 640 sessions)"


def build_daytrade_widgets() -> List[Widget]:
    """The 20 widgets of Chartink dashboard 503347 in its layout order (row by row). Definitions only:
    docs/scan_builder/chartink_503347/widgets.md has each Chartink query verbatim."""
    W: List[Widget] = []
    W.append(Widget("dt_rsi_vwap", "5518231", "RSI VWAP intraday", "scan", "fno", spec=_spec("dt_rsivwap", "fno", [
        _f("a", x(m("close")), "gt", x(m("high", 1)))]),
        intraday=IntradayRule("15minute", 5, [("rsi30", "rsi", {"period": 14, "bucket": 30}, 0),
                                              ("vwap", "vwap", {}, 0), ("c15", "close", {}, 0)],
                              ["30-minute RSI(14) > 60 (30-minute candles made from pairs of 15-minute candles)",
                               "Today's VWAP < latest 5-minute Close (VWAP = Σ(typical price × volume) ÷ Σ volume over today's "
                               "15-minute candles; the latest Close is the live price)"], _rsi_vwap_test)))
    W.append(Widget("dt_explosive", "5518232", "Explosive movement", "scan", "cash", spec=_spec("dt_explosive", "cash", [
        _f("a", x(m("max", source="close", period=5)), "gt", x(m("min", source="close", period=5), "*", n(1.15))),
        _f("b", x(m("close")), "gt", x(n(20))),
        _f("c", x(m("sma", source="volume", period=100)), "gt", x(n(100000))),
        _f("d", x(m("max", source="volume", period=5)), "gt", x(m("sma", source="volume", period=40), "*", n(2))),
        _f("e", x(F("market_cap_cr")), "gt", x(n(10000)))])))
    W.append(Widget("dt_strong", "5518234", "Strong stocks", "scan", "cash", spec=_spec("dt_strong", "cash", [
        _f("a", x(m("close")), "gt", x(m("close", 1))),
        _f("b", x(m("close", 1)), "gt", x(m("close", 2))),
        _f("c", x(m("close", 2)), "gt", x(m("close", 3))),
        _f("d", x(m("close", 3)), "gt", x(m("close", 4))),
        _f("e", x(m("close", 4)), "gt", x(m("close", 5)))])))
    W.append(Widget("dt_high_growth", "5518233", "High growth stocks", "scan", "cash", spec=_spec("dt_growth", "cash", [
        _f("a", x(m("close", 1, tf="1w")), "gte", x(m("close", 12, tf="1M"), "*", n(1.75))),
        _f("b", x(F("market_cap_cr")), "gte", x(n(1000))),
        _f("c", x(m("close")), "gt", x(n(50))),
        _f("d", x(F("y_eps")), "gt", x(n(5))),
        _f("e", x(m("volume")), "gt", x(n(100000)))])))
    W.append(Widget("dt_short_breakouts", "5518236", "Short term breakouts", "scan", "cash", spec=_spec("dt_short", "cash", [
        _f("a", x(m("max", source="close", period=5)), "gt", x(m("max", 6, source="close", period=120), "*", n(1.05))),
        _f("b", x(m("volume")), "gt", x(m("sma", source="volume", period=5))),
        _f("c", x(m("close")), "gt", x(m("close", 1))),
        _f("d", x(F("market_cap_cr")), "gt", x(n(20)))])))
    W.append(Widget("dt_multiyear", "5518237", "Multiyear breakout", "scan", "cash", spec=_spec("dt_multi", "cash", [
        _grp("any", [_f("a", x(m("high")), "eq", x(m("max", source="high", period=520))),
                     _f("b", x(F("market_cap_cr")), "gt", x(n(10000))),
                     _f("c", x(m("volume")), "gt", x(n(1000000)))], join="any",
             comment=("Chartink also lists 3- to 10-year highs (780–2,600 sessions): our history starts April 2024, and such "
                      "a high is also a 520-session high, so they add no stock"))])))
    W.append(Widget("dt_uptrend_52w", "5518240", "Uptrend - 52 Week High", "scan", "cash", spec=_spec("dt_up52", "cash", [
        _f("a", x(m("close", tf="1w")), "gte", x(m("max", tf="1w", source="close", period=52))),
        _f("b", x(m("sma", tf="1w", source="close", period=10)), "gte", x(m("sma", tf="1w", source="close", period=30))),
        _f("c", x(m("sma", tf="1w", source="close", period=30)), "gte", x(m("sma", tf="1w", source="close", period=40))),
        _f("d", x(F("market_cap_cr")), "gt", x(n(10000)))])))
    W.append(Widget("dt_below_dma", "5518241", "Stocks below 50 DMA & 200 DMA", "scan", "cash", spec=_spec("dt_below", "cash", [
        _f("a", x(m("close")), "gt", x(n(5))),
        _f("b", x(m("close")), "lt", x(m("sma", source="close", period=50))),
        _f("c", x(m("sma", source="close", period=50)), "lt", x(m("sma", source="close", period=200))),
        _f("d", x(m("volume")), "gt", x(n(100000))),
        _f("e", x(F("market_cap_cr")), "gt", x(n(10000))),
        _f("g", x(F("y_eps")), "gt", x(n(20))),
        _f("h", x(m("close"), "/", F("y_eps")), "gt", x(n(5))),
        _f("i", x(m("close"), "/", F("y_eps")), "lt", x(n(25)))])))
    W.append(Widget("dt_12y_high", "5518230", "12 Year High Breakout", "not_computed", "cash", lines=[
        ("High ≥ Highest high of 3,000 (about 12 years of daily candles)", 0, False,
         f"not computed — needs 3,000 sessions of history; {HISTORY_NOTE}")],
        note=f"Not computed: this widget needs about 12 years of daily highs and {HISTORY_NOTE}."))
    W.append(Widget("dt_52w_breakout", "5518228", "52 week high breakout", "scan", "cash", spec=_spec("dt_52wb", "cash", [
        _f("a", x(m("close")), "gt", x(m("max", 1, source="high", period=240)))])))
    W.append(Widget("dt_vol_price_breakout", "5518242", "High volume and price breakout stocks", "scan", "cash",
                    spec=_spec("dt_vpb", "cash", [
                        _f("a", x(m("volume")), "gt", x(m("sma", source="volume", period=20), "*", n(3))),
                        _f("b", x(m("volume")), "gt", x(m("sma", source="volume", period=5), "*", n(3))),
                        _f("c", x(m("close"), "-", m("close", 1), "/", m("close", 1)), "gt", x(n(0.01)))])))
    W.append(Widget("dt_under_300", "5518245", "Stocks under 300", "scan", "cash", spec=_spec("dt_u300", "cash", [
        _f("a", x(m("close")), "lt", x(n(300))),
        _f("b", x(m("close")), "gt", x(n(30))),
        _f("d", x(m("sma", source="close", period=50)), "gt", x(m("sma", source="close", period=200))),
        _f("e", x(F("y_eps")), "gt", x(F("py_eps"))),
        _f("g", x(F("y_eps")), "gt", x(n(50))),
        _f("h", x(F("roce_pct")), "gt", x(n(20))),
        _f("i", x(F("market_cap_cr")), "gt", x(n(1000)))]),
        lines=[("Weekly SMA(close, 200) > 52 weeks ago Weekly SMA(close, 200)", 0, False,
                f"not applied — needs 252 weeks of history; {HISTORY_NOTE}")],
        partial_note=("The 200-week moving-average condition cannot be checked on our history (from April 2024); the list "
                      "below passes the other conditions only.")))
    W.append(Widget("dt_down10_large", "5518238", "10% down stock (market cap > ₹10,000 cr)", "scan", "fno",
                    spec=_spec("dt_down10a", "fno", [
                        _f("a", x(m("close")), "lt", x(m("close", 1, tf="1M"), "*", n(0.9))),
                        _f("b", x(F("market_cap_cr")), "gt", x(n(10000))),
                        _f("c", x(m("volume")), "gt", x(n(100000)))])))
    W.append(Widget("dt_52w_high", "5518239", "52 week high stocks", "scan", "cash", spec=_spec("dt_52wh", "cash", [
        _f("a", x(m("high")), "eq", x(m("max", source="high", period=260)))])))
    W.append(Widget("dt_delivery_volume", "5518243", "Delivery % + Volume", "scan", "cash", spec=_spec("dt_delv", "cash", [
        _f("a", x(m("volume")), "gt", x(m("volume", 1), "+", n(50000))),
        _f("b", x(m("rsi", tf="1w", period=14)), "gte", x(n(69)))]),
        note="Chartink's own conditions use no delivery figure; they are run as written."))
    W.append(Widget("dt_high_momentum", "5518229", "High momentum stocks", "always_empty", "cash", lines=[
        ("RSI(14) > 50", 0, True, None),
        ("MACD line(26, 12, 9) > MACD signal(26, 12, 9)", 0, True, None),
        ("CCI(20) > 0", 0, True, None),
        ("Close > SMA(close, 200)", 0, True, None),
        ("Close > EMA(close, 200)", 0, True, None),
        ("RSI(14) > Highest RSI(14) of 3", 0, True,
         "can never hold: the highest of the last 3 values includes today's, so RSI cannot be above it"),
        ("Money flow index(14) > 60", 0, True, None),
        ("Dividend > 0", 0, True, None),
        ("Market cap (₹ cr) > 1,000", 0, True, None)],
        note=("Always empty, on Chartink too: 'RSI(14) > highest RSI(14) of the last 3 days' can never hold because those "
              "3 days include today.")))
    W.append(Widget("dt_down10_all", "5518235", "10% down stock (all F&O)", "scan", "fno", spec=_spec("dt_down10b", "fno", [
        _f("a", x(m("close")), "lt", x(m("close", 1, tf="1M"), "*", n(0.9)))])))
    W.append(Widget("dt_swing_breakout", "5518244", "Swing trade breakout", "scan", "cash", spec=_spec("dt_swing", "cash", [
        _f("a", x(m("close")), "gte", x(m("sma", source="close", period=30))),
        _f("b", x(m("close")), "gte", x(m("sma", source="close", period=50))),
        _f("c", x(m("close")), "gte", x(m("sma", source="close", period=100))),
        _f("d", x(m("close")), "gte", x(m("sma", source="close", period=200))),
        _f("e", x(F("y_eps")), "gt", x(F("py_eps"))),
        _f("g", x(F("q_pat")), "gte", x(F("y_pat"))),
        _f("h", x(F("market_cap_cr")), "gt", x(n(10000)))])))
    atlas_10x = next(w for w in WIDGETS if w.id == "vol_10x_5min")
    W.append(Widget("dt_vol_10x_5min", "5518247", atlas_10x.title, "scan", "cash", spec=atlas_10x.spec,
                    intraday=atlas_10x.intraday, flow=atlas_10x.flow))
    W.append(Widget("dt_breakout_15m", "5518246", "15 minute stock breakouts", "scan", "fno", spec=_spec("dt_b15", "fno", []),
                    intraday=IntradayRule("15minute", 5, [("c0", "close", {}, 0),
                                                          ("mx20", "max", {"source": "close", "period": 20}, 1),
                                                          ("v0", "volume", {}, 0),
                                                          ("smav20", "sma", {"source": "volume", "period": 20}, 0)],
                                          ["Latest 15-minute Close > Highest 15-minute close of 20, as of the candle before",
                                           "Latest 15-minute Volume > 15-minute SMA(volume, 20)"], _breakout15_test),
                    universe_note=("Chartink runs this on its segment 57960, which is not published; here on F&O stocks "
                                   "(owner, 3 Nov 2026)")))
    return W


DAYTRADE_WIDGETS = build_daytrade_widgets()


@dataclass(frozen=True)
class Dashboard:
    key: str
    title: str
    chartink_id: str
    attr: str                                       # the module-level widget list, read at run time (tests replace it)

    @property
    def widgets(self) -> List[Widget]:
        return list(globals()[self.attr])

    def meta(self) -> Dict[str, str]:
        return {"key": self.key, "title": self.title, "chartink_id": self.chartink_id}


# The study's top early indicator as a list of its own (early_movers.py; owner 3 Nov ~20:50 IST), not a Chartink widget.
EARLY_WIDGETS = [Widget("early_movers", "", "Early movers: volume ≥ 5× usual and ≥ 2 % over the open", "early", "cash",
                        note=None)]

DASHBOARDS: Dict[str, Dashboard] = {
    "atlas": Dashboard("atlas", "Atlas fresh", "247498", "WIDGETS"),
    "daytrade": Dashboard("daytrade", "Day trade", "503347", "DAYTRADE_WIDGETS"),
    "early": Dashboard("early", "Early movers", "", "EARLY_WIDGETS"),
}
DEFAULT_DASHBOARD = "atlas"


# ── Criteria text, written from the definitions ─────────────────────────────────────────────────────────────────────

_OP = {"gt": ">", "gte": "≥", "lt": "<", "lte": "≤", "eq": "=", "crosses_above": "crosses above", "crosses_below": "crosses below"}
_AR = {"+": "+", "-": "−", "*": "×", "/": "÷"}
_UNIT = {"1d": "day", "1w": "week", "1M": "month"}
_TF = {"1d": "", "1w": "Weekly ", "1M": "Monthly "}
_PRICE = {"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}


def _num(v: Any) -> str:
    f = float(v)
    if f.is_integer():
        i = int(f)
        if abs(i) < 1000:
            return str(i)
        s = str(abs(i))
        head, tail = s[:-3], s[-3:]
        parts: List[str] = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        return ("-" if i < 0 else "") + ",".join(parts + [tail])
    return f"{f:g}"


def _measure_core(name: str, p: Dict[str, Any]) -> str:
    if name in _PRICE:
        return _PRICE[name]
    if name in ("sma", "ema"):
        return f"{name.upper()}({p.get('source', 'close')}, {_num(p['period'])})"
    if name in ("max", "min"):
        return f"{'Highest' if name == 'max' else 'Lowest'} {p.get('source', 'close')} of {_num(p['period'])}"
    if name.startswith("macd_"):
        return f"MACD {name[5:]}({_num(p['slow'])}, {_num(p['fast'])}, {_num(p['signal'])})"
    simple = {"rsi": "RSI", "adx": "ADX", "di_plus": "+DI", "di_minus": "−DI", "cci": "CCI", "atr": "ATR",
              "stoch_k": "Fast stochastic %K"}
    if name in simple:
        return f"{simple[name]}({_num(p['period'])})"
    if name == "supertrend":
        return f"Supertrend({_num(p['period'])}, {_num(p['multiplier'])})"
    if name == "psar":
        return f"Parabolic SAR({_num(p['start'])}, {_num(p['increment'])}, {_num(p['max'])})"
    return str(S.MEASURES.get(name, {}).get("label", name))


def operand_text(o: Dict[str, Any]) -> str:
    if o["kind"] == "number":
        return _num(o["value"])
    if o["kind"] == "fundamental":
        meta = S.FUNDAMENTALS.get(o["field"], {})
        unit = meta.get("unit")
        return f"{meta.get('label', o['field'])}" + (f" ({unit})" if unit in ("₹ cr", "₹") else "")
    tf, off = o["tf"], int(o.get("offset", 0))
    core = _measure_core(o["measure"], o.get("params") or {})
    if off:
        unit = _UNIT.get(tf, "candle")
        return f"{off} {unit}{'s' if off > 1 else ''} ago {core}"
    return f"{_TF.get(tf, '')}{core}"


def expr_text(e: Dict[str, Any]) -> str:
    out = ""
    for i, t in enumerate(e["terms"]):
        out += operand_text(t["operand"]) if i == 0 else f" {_AR[t['op']]} {operand_text(t['operand'])}"
    return out


def filter_text(f: Dict[str, Any]) -> str:
    return f"{expr_text(f['left'])} {_OP[f['op']]} {expr_text(f['right'])}"


def _group_lines(g: Dict[str, Any], level: int, out: List[Dict[str, Any]]) -> None:
    for c in g.get("children", []):
        if not c.get("enabled", True):
            continue
        if c["kind"] == "group":
            out.append({"text": "All of:" if c["join"] == "all" else "Any of:", "level": level, "applied": True,
                        "note": c.get("comment") or None})
            _group_lines(c, level + 1, out)
        else:
            out.append({"text": filter_text(c), "level": level, "applied": True, "note": None})


def criteria_lines(w: Widget, intraday_applied: Optional[bool] = None, intraday_note: Optional[str] = None,
                   flow_applied: Optional[bool] = None, flow_note: Optional[str] = None) -> List[Dict[str, Any]]:
    """Every condition of `w`, one line each. Intraday lines carry applied/note from the run (None = not run yet)."""
    out: List[Dict[str, Any]] = [{"text": f"Universe: {UNIVERSE_LABEL[w.universe]}", "level": 0, "applied": True,
                                  "note": w.universe_note}]
    if w.spec is not None:
        _group_lines(w.spec["filters"], 0, out)
    if w.intraday is not None:
        applied = bool(intraday_applied)
        for line in w.intraday.lines:
            out.append({"text": line, "level": 0, "applied": applied,
                        "note": None if applied else (intraday_note or "not applied — intraday candles unavailable")})
    if w.flow is not None:
        applied = bool(flow_applied)
        for line in w.flow.lines:
            out.append({"text": line, "level": 0, "applied": applied,
                        "note": flow_note if applied else (flow_note or "not applied — trade-side ticks unavailable")})
    for text, level, applied, note in w.lines:
        out.append({"text": text, "level": level, "applied": applied, "note": note})
    if w.spec is not None and len(out) == 1 and w.intraday is None:
        out.append({"text": "(no conditions)", "level": 0, "applied": True, "note": None})
    return out


# ── Columns ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def _col(key: str, label: str, fmt: str) -> Dict[str, str]:
    return {"key": key, "label": label, "format": fmt}


COLUMNS = {
    "scan": [_col("symbol", "Symbol", "text"), _col("chg", "% Change", "pct"), _col("price", "Price", "price"),
             _col("volume", "Volume", "volume")],
    "strong": [_col("symbol", "Symbol", "text"), _col("chg", "%", "pct"), _col("price", "Price", "price"),
               _col("pos15", "15m pos %", "number"), _col("daypos", "Day pos %", "number"), _col("vpct", "V%", "number"),
               _col("cci", "CCI", "number"), _col("adx", "ADX", "number"), _col("rsi", "RSI", "number"),
               _col("volume", "Volume", "volume"), _col("equity", "Equity", "number")],
    "groups_ad": [_col("group", "Marketcap", "text"), _col("adv", "Advances", "pct"), _col("dec", "Declines", "number")],
    "groups_vol": [_col("group", "Marketcap", "text"), _col("net", "+-VOL", "number"), _col("pos", "Positive volume", "number"),
                   _col("neg", "Negative volume", "number")],
    "indices": [_col("symbol", "Symbol", "text"), _col("ltp", "Ltp", "price"), _col("chg", "% chg", "pct")],
    "early": [_col("symbol", "Symbol", "text"), _col("over_open", "% over open", "pct"), _col("price", "Price", "price"),
              _col("volume", "Volume", "volume"), _col("rvol", "Vol × usual", "number")],
    "not_computed": [],
}
COLUMNS["always_empty"] = COLUMNS["scan"]
ROW_KIND = {"early": "symbol", "scan": "symbol", "strong": "symbol", "groups_ad": "group", "groups_vol": "group", "indices": "index",
            "not_computed": "symbol", "always_empty": "symbol"}


def _r(v: Any, dp: int = 2) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, dp) if np.isfinite(f) else None


def _vol(v: Any) -> Optional[int]:
    f = _r(v, 0)
    return int(f) if f is not None else None


# ── Computation ─────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class _Run:
    panel: engine.Panel
    eligible: np.ndarray
    universes: Dict[str, np.ndarray]
    funds: Dict[str, np.ndarray]
    pos: Dict[str, int]


def _evaluate_scans(widgets: Sequence[Widget], run: _Run) -> Dict[str, Dict[str, Any]]:
    """engine.evaluate for every scan widget (CPU; called in a thread)."""
    out: Dict[str, Dict[str, Any]] = {}
    for w in widgets:
        if w.spec is None:
            continue
        try:
            out[w.id] = engine.evaluate(w.spec, run.panel, eligible=run.eligible, universes=run.universes,
                                        fundamentals=run.funds)
        except Exception:  # noqa: BLE001 — one widget failing must not blank the dashboard; logged with its trace
            logger.exception("market dashboard: widget %s failed to evaluate", w.id)
    return out


def marketcap_groups(ref_caps: Dict[str, float], symbols: Sequence[str]) -> np.ndarray:
    """Band index per symbol (0 Largecap, 1 Midcap, 2 Smallcap, -1 no market cap): ranks over every stock with a market cap."""
    ranked = sorted((s for s, v in ref_caps.items() if v is not None and np.isfinite(v) and v > 0), key=lambda s: -ref_caps[s])
    rank = {s: i + 1 for i, s in enumerate(ranked)}
    out = np.full(len(symbols), -1, dtype=int)
    for j, s in enumerate(symbols):
        r = rank.get(s)
        if r is None:
            continue
        for b, (_, lo, hi) in enumerate(MARKETCAP_BANDS):
            if r >= lo and (hi is None or r <= hi):
                out[j] = b
                break
    return out


def _group_rows(kind: str, run: _Run, groups: np.ndarray) -> List[List[Any]]:
    c0, c1, v0 = run.panel.close[-1], run.panel.close[-2], run.panel.volume[-1]
    elig = run.eligible & run.universes["cash"]
    up = elig & (c0 > c1)
    dn = elig & (c0 < c1)
    rows = []
    for b, (label, _, _) in enumerate(MARKETCAP_BANDS):
        ing = elig & (groups == b)
        k = int(ing.sum())
        if kind == "groups_ad":
            rows.append([label, _r(100.0 * (up & ing).sum() / k) if k else None, _r(100.0 * (dn & ing).sum() / k) if k else None])
        else:
            pv = float(np.nansum(v0[up & ing])) / 1e5
            nv = float(np.nansum(v0[dn & ing])) / 1e5
            rows.append([label, _r(pv - nv), _r(pv), _r(nv)])
    key = 1 if kind == "groups_ad" else 2                       # Chartink: ORDER BY Advances / Positive volume, desc
    rows.sort(key=lambda r: -(r[key] if r[key] is not None else -1e18))
    return rows


def _ist(stamp: Optional[str]) -> Optional[str]:
    return SV._ist_clock(stamp)


async def _default_intraday(symbols, interval, needs, *, lookback_days, live_prices=None):
    from .intraday import intraday_values
    return await intraday_values(symbols, interval, needs, lookback_days=lookback_days, live_prices=live_prices)


async def _default_indices(names):
    from .indices import index_result
    return await index_result(names)


KITE_SIDE_SOURCE = ("Kite live ticks in full mode, each trade sided against the best bid/ask before it (TrueData "
                    "unavailable); counted from when the live feed began carrying the stock today")


@dataclass
class _SideResult:
    values: Dict[str, Dict[str, Optional[float]]]
    as_of: Optional[str]
    source: str
    warnings: List[str]
    missing: List[str]


async def _request_feed(symbols: Sequence[str]) -> None:
    """Ask the live feed's leader to carry these stocks (kite_live_feed: kept 30 min, throttled per stock), so their trades
    are counted from now on."""
    from services.kite_live_feed.feed import get_feed
    await get_feed().request_symbols(list(symbols))


async def kite_sides(symbols: Sequence[str], *, read_quotes=None, request=None) -> _SideResult:
    """Today's trade sides from the live feed's quote cache (kite_live_feed/trade_side.py writes ask_trades, bid_trades,
    ask_volume, bid_volume, sides_since on each cash-stock quote). A stock the feed does not carry yet is asked for."""
    if read_quotes is None:
        from services.kite_live_feed.quote_cache import read_quotes
    request = request or _request_feed
    rows = await read_quotes(list(symbols)) or {}
    values: Dict[str, Dict[str, Optional[float]]] = {}
    missing: List[str] = []
    as_of: Optional[str] = None
    for sym in symbols:
        r = rows.get(sym) or {}
        a, b = r.get("ask_trades"), r.get("bid_trades")
        if a is None or b is None:
            missing.append(sym)
            continue
        values[sym] = {"buy_trades": float(a), "sell_trades": float(b), "buy_volume": r.get("ask_volume"),
                       "sell_volume": r.get("bid_volume")}
        if r.get("received_at") and (as_of is None or str(r["received_at"]) > as_of):
            as_of = str(r["received_at"])
    warnings: List[str] = []
    if missing:
        try:
            await request(missing)
        except Exception as e:  # noqa: BLE001 — the counted stocks still stand; the rest are tried next refresh
            logger.warning("market dashboard: asking the live feed to carry %d stocks failed (%s)", len(missing),
                           type(e).__name__)
        warnings.append(f"Kite live trade sides are not counted yet for {len(missing)} stock(s); the live feed was asked to "
                        "carry them and counts from then on")
    return _SideResult(values=values, as_of=as_of, source=KITE_SIDE_SOURCE, warnings=warnings, missing=missing)


async def _default_side_reader(symbols: List[str]) -> Any:
    """Kite trade sides counted by the live feed (quote cache rows: ask_trades, bid_trades)."""
    from services.kite_live_feed.quote_cache import read_quotes
    return await read_quotes(list(symbols))


async def _default_tick_flow(symbols, *, truedata=None, kite=None):
    """Trade sides for `symbols`: TrueData's tick prints with best bid/ask when TrueData answers; when it gives nothing for any
    of them (login refused, no ticks), Kite's live ticks counted by the live feed (owner 4 Nov: "please fetch from kite if
    true data not working"). The source travels on the result, so the card says which was used."""
    if truedata is None:
        from .tick_flow import initiated_counts as truedata
    kite = kite or kite_sides
    res = await truedata(symbols)
    if any(v for v in (res.values or {}).values()):
        return res
    k = await kite(list(symbols))
    why = (res.warnings or ["TrueData gave no ticks"])[0]
    k.warnings = list(k.warnings) + [f"TrueData: {why}"]
    return k


def _clock_text(stamp: Optional[str]) -> Optional[str]:
    return _ist(stamp) or stamp


INTRADAY_LABEL = {"5minute": "5-minute", "15minute": "15-minute", "60minute": "1-hour"}


async def _apply_flow(w: Widget, order: List[int], symbols: Sequence[str], intraday_applied: Optional[bool],
                      item: Dict[str, Any], tick_flow: Callable[..., Awaitable[Any]],
                      sources: List[str]) -> Tuple[Optional[bool], Optional[str], List[int]]:
    """The trade-side condition (w.flow) on the stocks that passed everything else: (applied, note, the order kept).
    It runs only once the intraday part is applied, so TrueData is asked about the few survivors, never a daily-only list."""
    if not order:
        return True, None, order                                     # nothing passed the rest: nothing to test
    if w.intraday is not None and not intraday_applied:
        return False, "not applied — it runs on the stocks that pass the 5-minute condition, once those candles are in", order
    survivors = [symbols[i] for i in order]
    try:
        fres = await tick_flow(survivors)
    except Exception:  # noqa: BLE001 — the other conditions still stand; logged with its trace
        logger.exception("market dashboard: trade-side ticks failed for %s", w.id)
        fres = None
    if fres is not None and fres.source and fres.source not in sources:
        sources.append(fres.source)
    have = {s: v for s, v in ((fres.values if fres is not None else None) or {}).items()
            if v and v.get("buy_trades") is not None and v.get("sell_trades") is not None}
    if not have:
        why = ((fres.warnings if fres is not None else None) or ["trade-side ticks could not be read"])[0]
        item["status"] = "partial"
        item["note"] = (f"The trade-side condition is not applied yet ({why}); the list below passes the other conditions only.")
        return False, f"not applied — {why}", order
    kept = [i for i in order if symbols[i] in have and w.flow.test(have[symbols[i]])]
    from_kite = (fres.source or "").startswith("Kite")
    missing = len(survivors) - len(have)
    if missing:
        item["status"] = "partial"
        item["note"] = ((item.get("note") or "") + " " if item.get("note") else "") + (
            f"{missing} of {len(survivors)} stocks have no trade-side ticks yet and are left out until they arrive.")
    if fres.as_of:
        what = "Kite ticks" if from_kite else "ticks"
        item["as_of"] = f"{item['as_of']} · {what} to {_clock_text(fres.as_of)}"
    if from_kite:
        return True, ("from Kite live ticks (each trade against the bid/ask before it), while TrueData is unavailable; "
                      "counted from when the live feed began carrying the stock"), kept
    return True, None, kept


async def compute(data: ScanData, *, dashboard: str = DEFAULT_DASHBOARD,
                  intraday_values: Optional[Callable[..., Awaitable[Any]]] = None,
                  index_result: Optional[Callable[..., Awaitable[Dict[str, Any]]]] = None,
                  tick_flow: Optional[Callable[..., Awaitable[Any]]] = None,
                  now: Optional[Callable[[], datetime]] = None,
                  feed_request: Optional[Callable[[Sequence[str]], Awaitable[Any]]] = _request_feed,
                  side_reader: Optional[Callable[[List[str]], Awaitable[Any]]] = None) -> Dict[str, Any]:
    """One dashboard (DASHBOARDS key) once. Raises DataUnavailable when prices cannot be read at all."""
    t0 = time.monotonic()
    at = (now or (lambda: datetime.now(timezone.utc)))()
    board = DASHBOARDS[dashboard]
    widgets = board.widgets
    intraday_values = intraday_values or _default_intraday
    index_result = index_result or _default_indices
    tick_flow = tick_flow or _default_tick_flow
    base = await data.panel()
    ref = await data.reference()
    syms = list(base.symbols)
    overlay = await data.today(base, syms)
    panel = SV.assemble(base, list(range(len(syms))), overlay)
    eligible = np.isfinite(panel.close[-1]) if panel.close.size else np.zeros(len(syms), dtype=bool)
    pos = {s: i for i, s in enumerate(panel.symbols)}
    universes: Dict[str, np.ndarray] = {}
    for key in UNIVERSE_LABEL:
        mask = np.zeros(len(panel.symbols), dtype=bool)
        for s in SV.universe_symbols(key, base, ref):
            mask[pos[s]] = True
        universes[key] = mask
    funds: Dict[str, np.ndarray] = {}
    for fld in ("pe_ttm", "roce_pct", "market_cap_cr", "debt_to_equity"):
        vals = ref.fundamentals.get(fld) or {}
        funds[fld] = np.array([vals.get(s, np.nan) for s in panel.symbols], dtype=float)
    results = await data.results_fields(wait=False)
    if results is not None:
        funds.update(SV.results_arrays(results, panel.symbols, overlay.day))
    run = _Run(panel, eligible, universes, funds, pos)
    scans = [w for w in widgets if w.spec is not None and not (w.uses_results and results is None)]
    evaluated = await asyncio.to_thread(_evaluate_scans, scans, run)

    c0, c1 = panel.close[-1], panel.close[-2]
    h0, l0, v0 = panel.high[-1], panel.low[-1], panel.volume[-1]
    mc = funds["market_cap_cr"]
    groups = marketcap_groups(ref.fundamentals.get("market_cap_cr") or {}, panel.symbols)
    basis_short = (f"Kite live {_ist(overlay.quote_as_of)}" if overlay.mode == "live" and overlay.quote_as_of
                   else f"Kite close {overlay.day.isoformat()}" if overlay.mode == "kite_close"
                   else f"NSE end of day {overlay.day.isoformat()}")
    warnings: List[str] = list(overlay.warnings)
    intraday_sources: List[str] = []
    out_widgets: List[Dict[str, Any]] = []

    # Every widget's intraday request starts at once, so a first-read wait (a stock new to a list) is paid once, not per widget.
    intra_tasks: Dict[str, "asyncio.Task[Any]"] = {}
    for w in widgets:
        res = evaluated.get(w.id)
        if w.intraday is None or res is None or not res["order"]:
            continue
        order = list(res["order"])
        live = ({panel.symbols[i]: float(c0[i]) for i in order} if overlay.mode == "live" else None)
        if w.flow is not None and overlay.mode == "live" and feed_request is not None:
            # The trade side needs ticks counted all session: ask the live feed to carry the daily-part candidates now.
            try:
                await feed_request([panel.symbols[i] for i in order])
            except Exception as e:  # noqa: BLE001 — counting starts later for them; logged
                logger.warning("market dashboard: asking the live feed for %s candidates failed (%s)", w.id, type(e).__name__)
        intra_tasks[w.id] = asyncio.ensure_future(intraday_values(
            [panel.symbols[i] for i in order], w.intraday.interval, w.intraday.needs,
            lookback_days=w.intraday.lookback_days, live_prices=live))

    for w in widgets:
        item: Dict[str, Any] = {"id": w.id, "chartink_id": w.chartink_id, "title": w.title, "universe": UNIVERSE_LABEL[w.universe],
                                "status": "ok", "note": w.note, "columns": COLUMNS[w.kind], "rows": [],
                                "row_kind": ROW_KIND[w.kind], "count": 0, "as_of": basis_short}
        intraday_applied: Optional[bool] = None
        intraday_note: Optional[str] = None
        flow_applied: Optional[bool] = None
        flow_note: Optional[str] = None
        early_crit: List[Dict[str, Any]] = EM.criteria(at.astimezone(SIG.IST), False, None) if w.kind == "early" else []
        try:
            if w.kind == "not_computed":
                item["status"] = "not_computed"
            elif w.kind == "always_empty":
                pass                                                     # no stock can pass (the note says why)
            elif w.kind in ("groups_ad", "groups_vol"):
                item["rows"] = _group_rows(w.kind, run, groups)
            elif w.kind == "early":
                live_now = overlay.mode == "live" and bool(overlay.session_open)
                share = EM.usual_share(at.astimezone(SIG.IST), live_now)
                early_crit = EM.criteria(at.astimezone(SIG.IST), live_now, share)
                if share is None:
                    item["note"] = "The list starts at 09:30, the study's first evaluation step."
                else:
                    item["rows"] = EM.rows(list(panel.symbols), panel.open[-1], c0, v0, panel.volume[:-1],
                                           eligible & universes["cash"], share)
            elif w.kind == "indices":
                ir = await index_result(list(INDEX_NAMES))
                rows = [[r.get("symbol"), _r((r.get("values") or [None])[0]), _r((r.get("values") or [None, None])[1])]
                        for r in ir.get("rows") or []]
                rows.sort(key=lambda r: -(r[1] or 0))                    # Chartink: ORDER BY Ltp desc
                item["rows"] = rows
                item["as_of"] = (ir.get("basis") or {}).get("text") or basis_short
                for wmsg in ir.get("warnings") or []:
                    warnings.append(f"Index stats: {wmsg}")
            elif w.uses_results and results is None:
                item.update(status="pending", note=RESULTS_PENDING)
            else:
                res = evaluated.get(w.id)
                if res is None:
                    raise RuntimeError("evaluation failed")
                order = list(res["order"])
                values = {i: v for i, v in zip(res["order"], res["values"])}
                intra: Dict[str, Dict[str, Optional[float]]] = {}
                if w.intraday is not None and order:
                    cands = [panel.symbols[i] for i in order]
                    try:
                        ires = await intra_tasks[w.id]
                        keys = [k for k, *_ in w.intraday.needs]
                        intra = {s: v for s, v in (ires.values or {}).items()
                                 if v and all(v.get(k) is not None and np.isfinite(v.get(k)) for k in keys)}
                        if ires.source and ires.source not in intraday_sources:
                            intraday_sources.append(ires.source)
                        if intra:
                            intraday_applied = True
                            # Still without candles (loading) vs candles read but too little history for the condition (a
                            # recent listing short of 1,000 five-minute candles): only the first can change, so only it is Partial.
                            no_candles = len(set(ires.missing or []) & set(cands))
                            short = len(cands) - len(intra) - no_candles
                            label = INTRADAY_LABEL[w.intraday.interval]
                            item["as_of"] = f"{basis_short} · {label} candles to {ires.as_of}" if ires.as_of else basis_short
                            notes = []
                            if no_candles and w.intraday.test is not None:
                                item["status"] = "partial"
                                notes.append(f"{no_candles} of {len(cands)} stocks have no {label} candles yet and are left out "
                                             "until they arrive.")
                            if short > 0 and w.intraday.test is not None:
                                notes.append(f"{short} stock(s) have too little {label} history for these conditions and "
                                             "cannot pass.")
                            if notes:
                                item["note"] = " ".join(notes)
                        else:
                            intraday_applied = False
                            intraday_note = "not applied — " + ((ires.warnings or ["intraday candles are loading"])[0])
                    except Exception:  # noqa: BLE001 — the daily part still stands; logged with its trace
                        logger.exception("market dashboard: intraday candles failed for %s", w.id)
                        intraday_applied, intraday_note = False, "not applied — intraday candles could not be read"
                    if w.intraday.test is not None and intraday_applied:
                        order = [i for i in order if panel.symbols[i] in intra
                                 and w.intraday.test(intra[panel.symbols[i]], float(c0[i]), float(c1[i]))]
                    elif w.intraday.test is not None:
                        item["status"] = "partial"
                        item["note"] = ("Intraday conditions are not applied yet (" + (intraday_note or "").replace("not applied — ", "")
                                        + "); the list below passes the daily conditions only.")
                elif w.intraday is not None and w.intraday.test is not None:
                    intraday_applied = True                                 # nothing passed the daily part: nothing to test
                if w.flow is not None:
                    flow_applied, flow_note, order = await _apply_flow(w, order, panel.symbols, intraday_applied, item,
                                                                       tick_flow, intraday_sources)
                if w.kind == "strong":
                    rows = []
                    for i in order:
                        chg, price, vol, cci, adx, rsi, smav = values[i]
                        rng = float(h0[i] - l0[i])
                        p15 = (intra.get(panel.symbols[i]) or {}).get("pos15")
                        rows.append([panel.symbols[i], _r(chg), _r(price), _r(p15),
                                     _r((c0[i] - l0[i]) / rng * 100) if rng > 0 else None,
                                     _r((v0[i] - smav) / smav * 100) if smav else None,
                                     _r(cci), _r(adx), _r(rsi), _vol(vol),
                                     _r(mc[i] / c0[i]) if np.isfinite(mc[i]) and c0[i] else None])
                    key = 3 if any(r[3] is not None for r in rows) else 4    # Chartink sorts by BUY% (15m pos %)
                    rows.sort(key=lambda r: -(r[key] if r[key] is not None else -1e18))
                    item["rows"] = rows
                else:
                    item["rows"] = [[panel.symbols[i], _r(values[i][0]), _r(values[i][1]), _vol(values[i][2])] for i in order]
                matched = int((res.get("counts") or {}).get("matched") or 0)
                if w.intraday is None and w.flow is None and matched > len(item["rows"]):
                    capped = f"{matched:,} stocks pass; the {len(item['rows'])} with the largest % change are shown."
                    item["note"] = f"{item['note']} {capped}" if item.get("note") else capped
                if w.partial_note:
                    item["status"] = "partial"
                    item["note"] = f"{w.partial_note} {item['note']}" if item.get("note") else w.partial_note
        except Exception:  # noqa: BLE001 — one widget failing must not blank the dashboard; logged with its trace
            logger.exception("market dashboard: widget %s failed", w.id)
            item.update(status="error", rows=[], note="This widget could not be computed just now; it retries on the next refresh.")
        item["criteria"] = (early_crit if w.kind == "early" else
                            criteria_lines(w, intraday_applied, intraday_note, flow_applied, flow_note))
        item["count"] = len(item["rows"])
        out_widgets.append(item)

    if intra_tasks:                      # a widget that failed before reading its task: collect it (its error is logged above)
        await asyncio.gather(*intra_tasks.values(), return_exceptions=True)

    # Early signals (signals.py): record the stocks newly in a fully applied list, only on live data in the session; then
    # today's list with each stock's price now.
    recording = overlay.mode == "live" and bool(overlay.session_open)
    if recording:
        try:
            await SIG.record(out_widgets, lambda syms: SIG.plan_inputs(panel, syms), at)
        except Exception:  # noqa: BLE001 — the dashboard stands without new signals this round; logged with its trace
            logger.exception("market dashboard: recording signals failed")
    prices = {s: float(c0[i]) for s, i in pos.items() if np.isfinite(c0[i])}
    sig_today = await SIG.today(at, prices)
    if sig_today["error"]:
        warnings.append(sig_today["error"])

    # Signal strength (signal_strength.py, DESIGN.md §11): every stock with a list entry today is scored; a long stock that
    # first reaches the threshold in the session becomes a strong signal with the positional plan frozen at the price then.
    scores: Dict[str, Dict[str, Any]] = {}
    scores_meta: Optional[Dict[str, Any]] = None
    strong: Dict[str, Any] = {"strong": [], "error": None}
    eod_day = base.eod_date.isoformat()
    try:
        scores, scores_meta = await SS.build_scores(data._get, panel, ref, sig_today["signals"], at,
                                                    live=overlay.mode == "live", eod_day=eod_day,
                                                    side_reader=side_reader or _default_side_reader)
        if recording:
            cands = [SS.strong_candidate(sym, r, prices.get(sym), eod_day) for sym, r in scores.items()
                     if r.get("score") is not None and r["score"] >= SS.THRESHOLD]
            if cands:
                await SIG.record_strong(cands, at)
        strong = await SIG.strong_today(at, prices, scores)
        if strong["error"]:
            warnings.append(strong["error"])
    except Exception:  # noqa: BLE001 — the dashboard stands without scores this round; logged with its trace
        logger.exception("market dashboard: signal strength failed")
        warnings.append("Signal strength could not be computed just now; it retries on the next refresh.")
    for sg in sig_today["signals"]:
        sg["score"] = (scores.get(sg.get("symbol")) or {}).get("score")
    public_scores = {sym: {k: v for k, v in r.items() if k not in ("atr", "sma20")} for sym, r in scores.items()}
    no_today = int(len(panel.symbols) - int(eligible.sum()))
    if overlay.mode == "eod" and no_today:
        warnings.append(f"{no_today} stock(s) have no candle on {overlay.day.isoformat()} (suspended, or not traded) and are left out.")
    if results is None:
        warnings.append(RESULTS_PENDING)
    seen: set = set()
    warnings = [wm for wm in warnings if not (wm in seen or seen.add(wm))]
    used_rest = bool(overlay.counts.get("rest_quotes"))
    return {
        "ok": True,
        "dashboard": board.meta(),
        "dashboards": [b.meta() for b in DASHBOARDS.values()],
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "elapsed_ms": int((time.monotonic() - t0) * 1000),
        "cached": False,
        "basis": {"mode": overlay.mode, "day": overlay.day.isoformat(), "eod_date": base.eod_date.isoformat(),
                  "quote_as_of": overlay.quote_as_of, "text": SV.basis_text(overlay, base, used_rest)},
        "market": {"open": overlay.session_open, "refresh_seconds": REFRESH_SECONDS},
        "counts": {"cash": int((eligible & universes["cash"]).sum()), "fno": int((eligible & universes["fno"]).sum()),
                   "nifty50": int((eligible & universes["nifty50"]).sum()), "no_today_bar": no_today},
        "sources": {"prices": SOURCE_PRICES, "today": SOURCE_TODAY.get(overlay.mode),
                    "fundamentals": (f"NIDP feature store, as of {ref.fundamentals_as_of}" if ref.fundamentals_as_of
                                     else "NIDP feature store"),
                    "results": (results.source if results is not None else "loading"),
                    "intraday": "; ".join(intraday_sources) or None,
                    "groups": ("Market-cap rank on the latest market cap from the NIDP feature store: 1–100 Largecap, "
                               "101–250 Midcap, 251+ Smallcap (AMFI ranks on a six-month average)")},
        "warnings": warnings,
        "widgets": out_widgets,
        "signals": sig_today["signals"],
        "signals_meta": {"day": at.astimezone(SIG.IST).date().isoformat(), "count": len(sig_today["signals"]),
                         "recording": recording, "rules": SIG.RULES_TEXT, "caveat": SS.CAVEAT},
        "scores": public_scores,
        "strong": strong["strong"],
        "scores_meta": scores_meta,
    }


IDEA_FIELDS = ("structure", "family", "horizon", "reward_risk", "max_loss_inr", "capital_at_risk_inr", "legs_text", "data_as_of")


async def _default_ideas(symbols, user_id):
    from .strategy_ideas import ideas_for
    return await ideas_for(symbols, user_id=user_id)


async def attach_ideas(dash: Dict[str, Any], user_id: str, *,
                       ideas_for: Optional[Callable[..., Awaitable[Any]]] = None) -> Dict[str, Any]:
    """The dashboard plus this user's strategy ideas for every stock it shows (symbol rows only), from the strategy builder's
    cache (strategy_ideas.py): never waits for a build. ideas[SYMBOL] = a compact idea, or None when no structure has a
    favorable reward : risk; a symbol still being built is absent. Per user, so it is added after the shared computation."""
    ideas_for = ideas_for or _default_ideas
    syms = list(dict.fromkeys([r[0] for w in dash.get("widgets") or [] if w.get("row_kind") == "symbol"
                               for r in w.get("rows") or [] if r and isinstance(r[0], str)]
                              + [g["symbol"] for g in dash.get("signals") or [] if isinstance(g.get("symbol"), str)]))
    out = dict(dash)
    if not syms:
        out["ideas"], out["ideas_meta"] = {}, None
        return out
    try:
        res = await ideas_for(syms, user_id)
    except Exception:  # noqa: BLE001 — the dashboard stands without ideas; logged with its trace
        logger.exception("market dashboard: strategy ideas could not be read")
        out["ideas"] = {}
        out["ideas_meta"] = {"built": 0, "pending": len(syms), "note": "Strategy ideas could not be read just now.",
                             "source": None, "as_of": None}
        return out
    values, pending = (res.values or {}), set(res.pending or [])
    ideas: Dict[str, Any] = {}
    for sym in syms:
        if sym in pending or sym not in values:
            continue                                                     # absent: still being built
        v = values[sym]
        ideas[sym] = None if v is None else {k: v.get(k) for k in IDEA_FIELDS}
    out["ideas"] = ideas
    out["ideas_meta"] = {"built": len(ideas), "pending": len(syms) - len(ideas), "note": res.note, "source": res.source,
                         "as_of": res.as_of}
    return out


_caches: Dict[str, Dict[str, Any]] = {k: {"at": float("-inf"), "value": None} for k in DASHBOARDS}
_cache = _caches[DEFAULT_DASHBOARD]                  # the atlas dashboard's entry (kept under its old name)
_locks: Dict[str, asyncio.Lock] = {}


def reset_caches() -> None:
    for c in _caches.values():
        c.update(at=float("-inf"), value=None)


async def get_dashboard(data: ScanData, *, dashboard: str = DEFAULT_DASHBOARD, clock: Callable[[], float] = time.monotonic,
                        **kw: Any) -> Dict[str, Any]:
    """One dashboard (DASHBOARDS key; KeyError for another), computed at most once per CACHE_S per worker (single flight, per
    dashboard); a failed refresh serves the last good answer for up to STALE_OK_S with a warning, else raises DataUnavailable."""
    if dashboard not in DASHBOARDS:
        raise KeyError(dashboard)
    _cache = _caches[dashboard]
    _lock = _locks.setdefault(dashboard, asyncio.Lock())
    v = _cache["value"]
    if v is not None and clock() - _cache["at"] < CACHE_S:
        return {**v, "cached": True}
    async with _lock:
        v = _cache["value"]
        if v is not None and clock() - _cache["at"] < CACHE_S:
            return {**v, "cached": True}
        try:
            fresh = await compute(data, dashboard=dashboard, **kw)
        except DataUnavailable as e:
            if v is not None and clock() - _cache["at"] < STALE_OK_S:
                logger.warning("market dashboard: refresh failed (%s); serving the answer from %.0f s ago", e.message,
                               clock() - _cache["at"])
                return {**v, "cached": True, "warnings": list(v.get("warnings") or []) + [
                    f"Prices could not be refreshed just now ({e.message}); this is the answer from {_ist(v['run_at'])}."]}
            raise
        _cache.update(at=clock(), value=fresh)
        return fresh
