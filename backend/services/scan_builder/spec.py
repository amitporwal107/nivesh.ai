"""What a scan may say, and the check every scan passes before it runs or is saved (docs/scan_builder/DESIGN.md §3).

The catalog (measures, fundamentals, operators, universes, timeframes) is static: the editor draws its pickers from it and the
engine reads the same keys, so a scan that validates here is one the engine can evaluate. `validate` returns a clean,
normalised copy (defaults filled, unknown keys dropped) or raises SpecError naming the JSON path of the FIRST problem, so the
editor can point at the row.

Nothing here does I/O.
"""
from __future__ import annotations

import copy
import json
import math
import re
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Set

# ── Catalog ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

UNIVERSES: "OrderedDict[str, str]" = OrderedDict([
    ("cash", "All NSE stocks"),
    ("fno", "F&O stocks"),
    ("nifty50", "Nifty 50"),
    ("nifty100", "Nifty 100"),
    ("nifty200", "Nifty 200"),
    ("nifty500", "Nifty 500"),
    ("midcap150", "Nifty Midcap 150"),
    ("smallcap250", "Nifty Smallcap 250"),
    ("niftybank", "Nifty Bank"),
])

SOURCES = ("open", "high", "low", "close", "volume")
DAILY_WEEKLY_MONTHLY = ["1d", "1w", "1M"]
TIMEFRAME_KEYS = tuple(DAILY_WEEKLY_MONTHLY)
INTRADAY_REASON = "Intraday candles are the next step"

TIMEFRAMES: List[Dict[str, Any]] = [
    {"key": "1d", "label": "Daily", "available": True, "reason": None},
    {"key": "1w", "label": "Weekly", "available": True, "reason": None},
    {"key": "1M", "label": "Monthly", "available": True, "reason": None},
    {"key": "5m", "label": "5 minute", "available": False, "reason": INTRADAY_REASON},
    {"key": "15m", "label": "15 minute", "available": False, "reason": INTRADAY_REASON},
    {"key": "1h", "label": "1 hour", "available": False, "reason": INTRADAY_REASON},
]
_INTRADAY_KEYS = {t["key"] for t in TIMEFRAMES if not t["available"]}


def _p_int(name: str, label: str, default: int, lo: int, hi: int) -> Dict[str, Any]:
    return {"name": name, "label": label, "type": "int", "default": default, "min": lo, "max": hi}


def _p_float(name: str, label: str, default: float, lo: float, hi: float) -> Dict[str, Any]:
    return {"name": name, "label": label, "type": "float", "default": default, "min": lo, "max": hi}


def _p_source(default: str = "close") -> Dict[str, Any]:
    return {"name": "source", "label": "Source", "type": "source", "default": default, "min": None, "max": None,
            "options": list(SOURCES)}


def _m(label: str, group: str, params: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"label": label, "group": group, "params": params, "timeframes": list(DAILY_WEEKLY_MONTHLY)}


_MACD = [_p_int("slow", "Slow period", 26, 1, 100), _p_int("fast", "Fast period", 12, 1, 100),
         _p_int("signal", "Signal period", 9, 1, 100)]
_BB = [_p_int("period", "Period", 20, 2, 100), _p_float("dev", "Standard deviations", 2.0, 0.1, 5.0)]

MEASURES: "OrderedDict[str, Dict[str, Any]]" = OrderedDict([
    ("open", _m("Open", "Price", [])),
    ("high", _m("High", "Price", [])),
    ("low", _m("Low", "Price", [])),
    ("close", _m("Close", "Price", [])),
    ("volume", _m("Volume", "Price", [])),
    ("max", _m("Highest of last N", "Price", [_p_source(), _p_int("period", "Period", 20, 1, 1000)])),
    ("min", _m("Lowest of last N", "Price", [_p_source(), _p_int("period", "Period", 20, 1, 1000)])),
    ("sma", _m("Simple moving average", "Moving averages", [_p_source(), _p_int("period", "Period", 20, 1, 500)])),
    ("ema", _m("Exponential moving average", "Moving averages", [_p_source(), _p_int("period", "Period", 20, 1, 500)])),
    ("rsi", _m("RSI", "Momentum", [_p_int("period", "Period", 14, 2, 100)])),
    ("macd_line", _m("MACD line", "Momentum", copy.deepcopy(_MACD))),
    ("macd_signal", _m("MACD signal", "Momentum", copy.deepcopy(_MACD))),
    ("macd_hist", _m("MACD histogram", "Momentum", copy.deepcopy(_MACD))),
    ("cci", _m("Commodity channel index", "Momentum", [_p_int("period", "Period", 20, 2, 100)])),
    ("stoch_k", _m("Fast stochastic %K", "Momentum", [_p_int("period", "Period", 14, 2, 100)])),
    ("stoch_d", _m("Fast stochastic %D", "Momentum", [_p_int("period", "Period", 14, 2, 100),
                                                      _p_int("smooth", "Smoothing", 3, 1, 20)])),
    ("adx", _m("ADX", "Trend", [_p_int("period", "Period", 14, 2, 100)])),
    ("di_plus", _m("+DI", "Trend", [_p_int("period", "Period", 14, 2, 100)])),
    ("di_minus", _m("−DI", "Trend", [_p_int("period", "Period", 14, 2, 100)])),
    ("supertrend", _m("Supertrend", "Trend", [_p_int("period", "Period", 7, 1, 100),
                                              _p_float("multiplier", "Multiplier", 3.0, 0.1, 10.0)])),
    ("psar", _m("Parabolic SAR", "Trend", [_p_float("start", "Start", 0.02, 0.001, 1.0),
                                           _p_float("increment", "Increment", 0.02, 0.001, 1.0),
                                           _p_float("max", "Maximum", 0.2, 0.001, 1.0)])),
    ("atr", _m("Average true range", "Volatility", [_p_int("period", "Period", 14, 1, 100)])),
    ("bb_upper", _m("Bollinger upper band", "Volatility", copy.deepcopy(_BB))),
    ("bb_lower", _m("Bollinger lower band", "Volatility", copy.deepcopy(_BB))),
])

FUNDAMENTALS: "OrderedDict[str, Dict[str, str]]" = OrderedDict([
    ("market_cap_cr", {"label": "Market cap", "unit": "₹ cr"}),
    ("pe_ttm", {"label": "PE (TTM)", "unit": "x"}),
    ("pb", {"label": "Price to book", "unit": "x"}),
    ("roce_pct", {"label": "ROCE (latest year)", "unit": "%"}),
    ("roe_pct", {"label": "ROE", "unit": "%"}),
    ("debt_to_equity", {"label": "Debt to equity", "unit": "x"}),
    ("eps_growth_yoy_pct", {"label": "EPS growth YoY", "unit": "%"}),
    ("eps_growth_3y_cagr_pct", {"label": "EPS growth 3Y CAGR", "unit": "%"}),
    ("pat_growth_yoy_pct", {"label": "Net profit growth YoY", "unit": "%"}),
    ("revenue_growth_yoy_pct", {"label": "Revenue growth YoY", "unit": "%"}),
    ("revenue_growth_3y_cagr_pct", {"label": "Revenue growth 3Y CAGR", "unit": "%"}),
    ("profit_margin_pct", {"label": "Net profit margin", "unit": "%"}),
    ("ev_ebitda", {"label": "EV / EBITDA", "unit": "x"}),
    ("interest_coverage", {"label": "Interest coverage", "unit": "x"}),
    ("dividend_yield_pct", {"label": "Dividend yield", "unit": "%"}),
    ("promoter_pct", {"label": "Promoter holding", "unit": "%"}),
    ("promoter_pledged_pct", {"label": "Promoter pledge", "unit": "%"}),
    ("fii_pct", {"label": "FII holding", "unit": "%"}),
    ("dii_pct", {"label": "DII holding", "unit": "%"}),
    # Company results (nidp.nse_financials_quarterly via DaaS /financials/{symbol}, loaded once a day: data.results_fields).
    # Consolidated figures where the company files them, else standalone.
    ("q_pat", {"label": "Net profit, latest quarter", "unit": "₹ cr", "group": "Results"}),
    ("q1_pat", {"label": "Net profit, 1 quarter ago", "unit": "₹ cr", "group": "Results"}),
    ("q4_pat", {"label": "Net profit, 4 quarters ago", "unit": "₹ cr", "group": "Results"}),
    ("q_pbdt", {"label": "PBDT, latest quarter", "unit": "₹ cr", "group": "Results"}),
    ("ttm_pat", {"label": "Net profit, last 4 quarters", "unit": "₹ cr", "group": "Results"}),
    ("y_pat", {"label": "Net profit, latest year", "unit": "₹ cr", "group": "Results"}),
    ("y_eps", {"label": "EPS, latest year", "unit": "₹", "group": "Results"}),
    ("py_eps", {"label": "EPS, previous year", "unit": "₹", "group": "Results"}),
])
RESULT_FIELDS = ("q_pat", "q1_pat", "q4_pat", "q_pbdt", "ttm_pat", "y_pat", "y_eps", "py_eps")

OPERATORS: List[Dict[str, str]] = [
    {"key": "gt", "label": "Greater than"},
    {"key": "gte", "label": "Greater than equal to"},
    {"key": "lt", "label": "Less than"},
    {"key": "lte", "label": "Less than equal to"},
    {"key": "eq", "label": "Equals"},
    {"key": "crosses_above", "label": "Crossed above"},
    {"key": "crosses_below", "label": "Crossed below"},
]
OPERATOR_KEYS = tuple(o["key"] for o in OPERATORS)
ARITH_OPS = ("+", "-", "*", "/")
JOINS = ("all", "any")
FORMATS = ("number", "pct", "price", "volume")
SORT_DIRS = ("asc", "desc")

LIMITS: Dict[str, int] = {
    "max_depth": 4,             # groups nested, the root group counting as 1
    "max_filters": 40,          # filters in the whole scan
    "max_children": 30,         # direct children of one group
    "max_terms": 8,             # terms in one expression
    "max_offset": 250,          # candles back
    "max_columns": 12,
    "max_limit": 500,           # number of symbols shown
    "default_limit": 50,
    "max_spec_bytes": 65_536,
    "name_max": 80,
    "description_max": 400,
    "comment_max": 200,
    "alias_max": 40,
}

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,24}$")


class SpecError(Exception):
    """A scan that cannot run: `path` is the JSON path of the first problem, `message` says what is wrong in plain English."""

    code = "invalid_spec"

    def __init__(self, path: str, message: str):
        super().__init__(f"{path or 'spec'}: {message}")
        self.path, self.message = path, message


# ── Builders (default scan and templates) ───────────────────────────────────────────────────────────────────────────

def measure(name: str, offset: int = 0, tf: str = "1d", **params: Any) -> Dict[str, Any]:
    return {"kind": "measure", "tf": tf, "offset": offset, "measure": name, "params": dict(params)}


def number(value: float) -> Dict[str, Any]:
    return {"kind": "number", "value": value}


def fundamental(field: str) -> Dict[str, Any]:
    return {"kind": "fundamental", "field": field}


def expr(first: Dict[str, Any], *rest: Any) -> Dict[str, Any]:
    """expr(a, "-", b, "/", c) → {"terms": [...]}: operands with the operation before each, read left to right."""
    terms = [{"op": None, "operand": first}]
    if len(rest) % 2:
        raise ValueError("expr needs (op, operand) pairs after the first operand")
    for i in range(0, len(rest), 2):
        terms.append({"op": rest[i], "operand": rest[i + 1]})
    return {"terms": terms}


def flt(fid: str, left: Dict[str, Any], op: str, right: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": fid, "kind": "filter", "left": left, "op": op, "right": right, "enabled": True, "comment": ""}


def group(gid: str, children: List[Dict[str, Any]], join: str = "all", universe: Optional[str] = None) -> Dict[str, Any]:
    return {"id": gid, "kind": "group", "join": join, "universe": universe, "enabled": True, "comment": "", "children": children}


def _default_columns() -> List[Dict[str, Any]]:
    return [
        {"id": "c_chg", "alias": "% Change", "enabled": True, "format": "pct",
         "expr": expr(measure("close"), "-", measure("close", 1), "/", measure("close", 1), "*", number(100))},
        {"id": "c_price", "alias": "Price", "enabled": True, "format": "price", "expr": expr(measure("close"))},
        {"id": "c_vol", "alias": "Volume", "enabled": True, "format": "volume", "expr": expr(measure("volume"))},
    ]


def _scan(name: str, description: str, root: Dict[str, Any]) -> Dict[str, Any]:
    return {"version": 1, "name": name, "description": description, "filters": root, "columns": _default_columns(),
            "sort": {"column": "c_chg", "dir": "desc"}, "limit": LIMITS["default_limit"]}


def default_spec() -> Dict[str, Any]:
    """A new scan: every NSE stock, no filters, % Change · Price · Volume, by % Change high to low, 50 stocks."""
    return _scan("New scan", "", group("root", [], universe="cash"))


def templates() -> List[Dict[str, Any]]:
    """Ready scans to start from. Each name says what the scan tests, nothing more."""
    rsi_strong = _scan(
        "RSI strong on daily and weekly",
        "Daily RSI(14) above 70 with weekly RSI(14) above 50, for companies above ₹10,000 cr market cap.",
        group("root", [
            flt("f_rsi_d", expr(measure("rsi", period=14)), "gt", expr(number(70))),
            flt("f_rsi_w", expr(measure("rsi", tf="1w", period=14)), "gt", expr(number(50))),
            flt("f_mcap", expr(fundamental("market_cap_cr")), "gt", expr(number(10000))),
        ], universe="cash"))
    tight = _scan(
        "Tight weekly range near the high",
        "Closes at or above yesterday's high while the last four weekly closes sit within 3% above and 5% below today's close; "
        "market cap above ₹10,000 cr.",
        group("root", [
            flt("f_hi", expr(measure("close")), "gte", expr(measure("high", 1))),
            flt("f_wmax", expr(measure("max", tf="1w", source="close", period=4)), "lt",
                expr(measure("close"), "*", number(1.03))),
            flt("f_wmin", expr(measure("min", tf="1w", source="close", period=4)), "gt",
                expr(measure("close"), "*", number(0.95))),
            flt("f_mcap", expr(fundamental("market_cap_cr")), "gt", expr(number(10000))),
        ], universe="cash"))
    surge = _scan(
        "Volume surge in an uptrend",
        "F&O stocks trading more than twice their 20-day average volume, above the 44-day average, with MACD above its signal "
        "line and ADX above 25 led by +DI.",
        group("root", [
            flt("f_vol", expr(measure("volume")), "gt", expr(measure("sma", source="volume", period=20), "*", number(2))),
            flt("f_sma", expr(measure("close")), "gt", expr(measure("sma", source="close", period=44))),
            flt("f_macd", expr(measure("macd_line", slow=26, fast=12, signal=9)), "gt",
                expr(measure("macd_signal", slow=26, fast=12, signal=9))),
            flt("f_adx", expr(measure("adx", period=14)), "gt", expr(number(25))),
            flt("f_di", expr(measure("di_plus", period=14)), "gt", expr(measure("di_minus", period=14))),
        ], universe="fno"))
    return [
        {"key": "rsi_strong_daily_weekly", "name": rsi_strong["name"], "description": rsi_strong["description"], "spec": rsi_strong},
        {"key": "tight_weekly_range", "name": tight["name"], "description": tight["description"], "spec": tight},
        {"key": "volume_surge_uptrend", "name": surge["name"], "description": surge["description"], "spec": surge},
    ]


def catalog() -> Dict[str, Any]:
    """Everything the editor's pickers need (the route adds universe sizes and the refresh interval)."""
    return {
        "measures": [{"key": k, **copy.deepcopy(v)} for k, v in MEASURES.items()],
        "fundamentals": [{"key": k, **v} for k, v in FUNDAMENTALS.items()],
        "operators": copy.deepcopy(OPERATORS),
        "universes": [{"key": k, "label": v} for k, v in UNIVERSES.items()],
        "timeframes": copy.deepcopy(TIMEFRAMES),
        "templates": templates(),
        "limits": dict(LIMITS),
        "default_spec": default_spec(),
    }


# ── Validation ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))


def _is_int(v: Any) -> bool:
    return _is_num(v) and float(v) == int(v)


def _text(v: Any, path: str, lo: int, hi: int, default: Optional[str] = None) -> str:
    if v is None and default is not None:
        return default
    if not isinstance(v, str):
        raise SpecError(path, "must be text")
    s = v.strip()
    if len(s) < lo:
        raise SpecError(path, "must not be empty" if lo == 1 else f"must be at least {lo} characters")
    if len(s) > hi:
        raise SpecError(path, f"must be at most {hi} characters")
    return s


def _bool(v: Any, path: str, default: bool = True) -> bool:
    if v is None:
        return default
    if not isinstance(v, bool):
        raise SpecError(path, "must be true or false")
    return v


def _choice(v: Any, path: str, options: Any, what: str, default: Optional[str] = None) -> str:
    if v is None and default is not None:
        return default
    if not isinstance(v, str) or v not in options:
        raise SpecError(path, f"unknown {what} {v!r}; expected one of {', '.join(options)}")
    return v


class _Checker:
    """One validation pass: tracks ids (unique across the scan) and the filter count."""

    def __init__(self) -> None:
        self.ids: Set[str] = set()
        self.filters = 0

    def ident(self, v: Any, path: str) -> str:
        if not isinstance(v, str) or not _ID_RE.match(v):
            raise SpecError(path, "must be 1-24 letters, digits, '_' or '-'")
        if v in self.ids:
            raise SpecError(path, f"id {v!r} is used twice")
        self.ids.add(v)
        return v

    def params(self, mkey: str, raw: Any, path: str) -> Dict[str, Any]:
        defs = MEASURES[mkey]["params"]
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise SpecError(path, "must be an object of parameter values")
        names = {d["name"] for d in defs}
        for k in raw:
            if k not in names:
                allowed = ", ".join(sorted(names)) or "none"
                raise SpecError(f"{path}.{k}", f"{MEASURES[mkey]['label']} has no parameter {k!r} (parameters: {allowed})")
        out: Dict[str, Any] = {}
        for d in defs:
            name, p = d["name"], f"{path}.{d['name']}"
            v = raw.get(name)
            if v is None:
                out[name] = d["default"]
                continue
            if d["type"] == "source":
                out[name] = _choice(v, p, SOURCES, "source")
            elif d["type"] == "int":
                if not _is_int(v):
                    raise SpecError(p, "must be a whole number")
                iv = int(v)
                if not d["min"] <= iv <= d["max"]:
                    raise SpecError(p, f"must be between {d['min']} and {d['max']}")
                out[name] = iv
            else:
                if not _is_num(v):
                    raise SpecError(p, "must be a number")
                fv = float(v)
                if not d["min"] <= fv <= d["max"]:
                    raise SpecError(p, f"must be between {d['min']} and {d['max']}")
                out[name] = fv
        return out

    def operand(self, raw: Any, path: str) -> Dict[str, Any]:
        if not isinstance(raw, dict):
            raise SpecError(path, "must be an operand object")
        kind = _choice(raw.get("kind"), f"{path}.kind", ("number", "measure", "fundamental"), "operand kind")
        if kind == "number":
            v = raw.get("value")
            if not _is_num(v):
                raise SpecError(f"{path}.value", "must be a finite number")
            return {"kind": "number", "value": float(v)}
        if kind == "fundamental":
            return {"kind": "fundamental", "field": _choice(raw.get("field"), f"{path}.field", list(FUNDAMENTALS), "fundamental")}
        tf = raw.get("tf", "1d")
        if isinstance(tf, str) and tf in _INTRADAY_KEYS:
            raise SpecError(f"{path}.tf", f"{INTRADAY_REASON}; use daily, weekly or monthly for now")
        tf = _choice(tf, f"{path}.tf", TIMEFRAME_KEYS, "timeframe")
        off = raw.get("offset", 0)
        if not _is_int(off) or not 0 <= int(off) <= LIMITS["max_offset"]:
            raise SpecError(f"{path}.offset", f"must be a whole number from 0 to {LIMITS['max_offset']}")
        mkey = _choice(raw.get("measure"), f"{path}.measure", list(MEASURES), "measure")
        if tf not in MEASURES[mkey]["timeframes"]:
            raise SpecError(f"{path}.tf", f"{MEASURES[mkey]['label']} is not available on {tf}")
        return {"kind": "measure", "tf": tf, "offset": int(off), "measure": mkey,
                "params": self.params(mkey, raw.get("params"), f"{path}.params")}

    def expr(self, raw: Any, path: str) -> Dict[str, Any]:
        if not isinstance(raw, dict):
            raise SpecError(path, "must be an expression object")
        terms = raw.get("terms")
        if not isinstance(terms, list) or not 1 <= len(terms) <= LIMITS["max_terms"]:
            raise SpecError(f"{path}.terms", f"must be a list of 1 to {LIMITS['max_terms']} terms")
        out = []
        for i, t in enumerate(terms):
            tp = f"{path}.terms[{i}]"
            if not isinstance(t, dict):
                raise SpecError(tp, "must be a term object")
            op = t.get("op")
            if i == 0:
                if op is not None:
                    raise SpecError(f"{tp}.op", "the first term has no operation")
            elif op not in ARITH_OPS:
                raise SpecError(f"{tp}.op", f"must be one of {' '.join(ARITH_OPS)}")
            out.append({"op": op, "operand": self.operand(t.get("operand"), f"{tp}.operand")})
        return {"terms": out}

    def filter(self, raw: Dict[str, Any], path: str) -> Dict[str, Any]:
        self.filters += 1
        if self.filters > LIMITS["max_filters"]:
            raise SpecError(path, f"a scan may have at most {LIMITS['max_filters']} filters")
        return {
            "id": self.ident(raw.get("id"), f"{path}.id"),
            "kind": "filter",
            "left": self.expr(raw.get("left"), f"{path}.left"),
            "op": _choice(raw.get("op"), f"{path}.op", OPERATOR_KEYS, "operator"),
            "right": self.expr(raw.get("right"), f"{path}.right"),
            "enabled": _bool(raw.get("enabled"), f"{path}.enabled"),
            "comment": _text(raw.get("comment"), f"{path}.comment", 0, LIMITS["comment_max"], default=""),
        }

    def group(self, raw: Any, path: str, depth: int) -> Dict[str, Any]:
        if not isinstance(raw, dict):
            raise SpecError(path, "must be a group object")
        if depth > LIMITS["max_depth"]:
            raise SpecError(path, f"groups may be nested at most {LIMITS['max_depth']} deep")
        if raw.get("kind", "group") != "group":
            raise SpecError(f"{path}.kind", "must be 'group'")
        gid = self.ident(raw.get("id"), f"{path}.id")
        uni = raw.get("universe")
        if depth == 1:
            uni = _choice(uni, f"{path}.universe", list(UNIVERSES), "universe")
        elif uni is not None:
            uni = _choice(uni, f"{path}.universe", list(UNIVERSES), "universe")
        kids = raw.get("children", [])
        if not isinstance(kids, list):
            raise SpecError(f"{path}.children", "must be a list")
        if len(kids) > LIMITS["max_children"]:
            raise SpecError(f"{path}.children", f"a group may hold at most {LIMITS['max_children']} filters and groups")
        children = []
        for i, c in enumerate(kids):
            cp = f"{path}.children[{i}]"
            if not isinstance(c, dict):
                raise SpecError(cp, "must be a filter or a group")
            kind = c.get("kind")
            if kind == "group":
                children.append(self.group(c, cp, depth + 1))
            elif kind == "filter":
                children.append(self.filter(c, cp))
            else:
                raise SpecError(f"{cp}.kind", "must be 'filter' or 'group'")
        return {
            "id": gid,
            "kind": "group",
            "join": _choice(raw.get("join"), f"{path}.join", JOINS, "join", default="all"),
            "universe": uni,
            "enabled": _bool(raw.get("enabled"), f"{path}.enabled"),
            "comment": _text(raw.get("comment"), f"{path}.comment", 0, LIMITS["comment_max"], default=""),
            "children": children,
        }

    def columns(self, raw: Any) -> List[Dict[str, Any]]:
        if not isinstance(raw, list) or not 1 <= len(raw) <= LIMITS["max_columns"]:
            raise SpecError("columns", f"must be a list of 1 to {LIMITS['max_columns']} columns")
        out = []
        for i, c in enumerate(raw):
            p = f"columns[{i}]"
            if not isinstance(c, dict):
                raise SpecError(p, "must be a column object")
            out.append({
                "id": self.ident(c.get("id"), f"{p}.id"),
                "alias": _text(c.get("alias"), f"{p}.alias", 1, LIMITS["alias_max"]),
                "expr": self.expr(c.get("expr"), f"{p}.expr"),
                "enabled": _bool(c.get("enabled"), f"{p}.enabled"),
                "format": _choice(c.get("format"), f"{p}.format", FORMATS, "format", default="number"),
            })
        return out


def validate(spec: Any) -> Dict[str, Any]:
    """A clean copy of `spec` with defaults filled, or SpecError at the first problem (DESIGN.md §3 bounds)."""
    if not isinstance(spec, dict):
        raise SpecError("", "a scan must be a JSON object")
    try:
        size = len(json.dumps(spec, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    except (TypeError, ValueError):
        raise SpecError("", "a scan must be plain JSON (text, numbers, true/false, lists, objects; no NaN or infinity)")
    if size > LIMITS["max_spec_bytes"]:
        raise SpecError("", f"the scan is {size} bytes; at most {LIMITS['max_spec_bytes']} are allowed")
    version = spec.get("version", 1)
    if version != 1 or isinstance(version, bool):
        raise SpecError("version", "must be 1")
    ck = _Checker()
    out: Dict[str, Any] = {
        "version": 1,
        "name": _text(spec.get("name"), "name", 1, LIMITS["name_max"]),
        "description": _text(spec.get("description"), "description", 0, LIMITS["description_max"], default=""),
    }
    if "filters" not in spec:
        raise SpecError("filters", "is required (the root group with its universe)")
    out["filters"] = ck.group(spec.get("filters"), "filters", 1)
    out["columns"] = ck.columns(spec.get("columns"))
    col_ids = [c["id"] for c in out["columns"]]
    sort = spec.get("sort")
    if sort is None:
        out["sort"] = {"column": col_ids[0], "dir": "desc"}
    else:
        if not isinstance(sort, dict):
            raise SpecError("sort", "must be an object {column, dir}")
        col = sort.get("column")
        if col not in col_ids:
            raise SpecError("sort.column", f"must be the id of one of the columns ({', '.join(col_ids)})")
        out["sort"] = {"column": col, "dir": _choice(sort.get("dir"), "sort.dir", SORT_DIRS, "direction", default="desc")}
    limit = spec.get("limit", LIMITS["default_limit"])
    if not _is_int(limit) or not 1 <= int(limit) <= LIMITS["max_limit"]:
        raise SpecError("limit", f"must be a whole number from 1 to {LIMITS['max_limit']}")
    out["limit"] = int(limit)
    return out


# ── Reading a validated scan ────────────────────────────────────────────────────────────────────────────────────────

def _walk_groups(g: Dict[str, Any]):
    yield g
    for c in g.get("children", []):
        if c.get("kind") == "group":
            yield from _walk_groups(c)


def _walk_exprs(spec: Dict[str, Any]):
    for g in _walk_groups(spec["filters"]):
        for c in g.get("children", []):
            if c.get("kind") == "filter":
                yield c["left"]
                yield c["right"]
    for col in spec.get("columns", []):
        yield col["expr"]


def universes_in(spec: Dict[str, Any]) -> Set[str]:
    """Every universe the scan names (root and sub-groups); the data layer loads these memberships."""
    return {g["universe"] for g in _walk_groups(spec["filters"]) if g.get("universe")}


def fundamentals_in(spec: Dict[str, Any]) -> Set[str]:
    """Every fundamental field the scan reads (filters and columns)."""
    return {t["operand"]["field"] for e in _walk_exprs(spec) for t in e["terms"] if t["operand"]["kind"] == "fundamental"}


def timeframes_in(spec: Dict[str, Any]) -> Set[str]:
    return {t["operand"]["tf"] for e in _walk_exprs(spec) for t in e["terms"] if t["operand"]["kind"] == "measure"}
