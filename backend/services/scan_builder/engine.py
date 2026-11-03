"""Evaluating a validated scan over a panel of stocks (docs/scan_builder/DESIGN.md §3).

The data layer (data.py / service.py) builds a Panel: daily candles on ONE common calendar, one column per stock, NaN where a
stock has no candle that day; the last row may be today's provisional candle from Kite. `evaluate` then:

  1. keeps the stocks that are `eligible` (a candle on the run day) and in the root group's universe;
  2. builds each timeframe the scan uses (daily as is, weekly and monthly resampled from the daily candles) and right-aligns
     every stock's own candles (indicators.Aligner), so offset 0 is a stock's latest candle and offset 1 the one before;
  3. computes each indicator series once per (timeframe, measure, parameters) on the LAST candles it needs (see Windows) and
     reads it at the offsets the scan asks for;
  4. combines filters with three-valued logic: a comparison with a missing value (too little history, no fundamental, a
     division by zero) is UNKNOWN. In an "all" group a failure beats unknown; in an "any" group a pass beats unknown. Only a
     definite pass matches, and the count of stocks whose result stayed unknown is reported (`no_history`);
  5. evaluates the enabled columns for the matches, sorts by the sort column (missing values last, then by symbol), cuts to
     the limit.

Expressions are read LEFT TO RIGHT as written (Chartink's rule): Close − 1 ago Close / 1 ago Close × 100 is
((C − C1) / C1) × 100. A disabled filter or group is ignored; an enabled group with no enabled children passes; the root group
is always evaluated.

Windows (speed without changing answers). A series is computed on each stock's last W candles, W = what the definition needs
plus the offsets read, never more than the stock has:
  * windowed measures (price fields, SMA, highest/lowest, CCI, stochastic, Bollinger) need exactly their period: the result
    is identical to the full history;
  * smoothed measures (EMA, RSI, ATR, ±DI, ADX, MACD) also need a burn-in after which the seed's influence is below 1e-9
    of the value (ceil(ln 1e-9 / ln(1 − alpha)) candles: 280 for Wilder 14, 519 for EMA 50), so they agree with the full
    history to that tolerance; a period that needs more than the stock has simply uses all of it;
  * path-dependent measures (Supertrend, Parabolic SAR) carry a trend state, so they get their ATR burn-in plus PATH_BURN_IN
    candles. A stock whose Supertrend has not flipped, or whose SAR has not reversed, within that many candles can differ from
    a full-history value; tests/test_scan_builder_engine.py checks the equality on a 600-candle ragged panel.
Every timeframe's candles are built from the FULL daily history (a long suspension never hides a stock's earlier candles);
only the indicator maths runs on the window. Pure numpy, no I/O.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional, Tuple

import numpy as np

from . import indicators as ind

PRICE_FIELDS = ("open", "high", "low", "close", "volume")
CONVERGE_EPS = 1e-9          # a smoothed series' seed influence left at the start of the window, relative
PATH_BURN_IN = 300           # extra candles for Supertrend / Parabolic SAR to settle into the same trend state
_FAMILY = {"macd_line": "macd", "macd_signal": "macd", "macd_hist": "macd", "adx": "dmi", "di_plus": "dmi",
           "di_minus": "dmi", "bb_upper": "bb", "bb_lower": "bb"}


@dataclass
class Panel:
    """Daily candles for N stocks on a common calendar (T days). NaN = no candle that day for that stock."""
    symbols: List[str]                  # N, the column order of every array
    dates: np.ndarray                   # (T,) datetime64[D], ascending, unique
    open: np.ndarray                    # (T, N) float64
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray

    def __post_init__(self) -> None:
        self.dates = np.asarray(self.dates).astype("datetime64[D]")
        shape = (len(self.dates), len(self.symbols))
        for f in PRICE_FIELDS:
            a = np.asarray(getattr(self, f), dtype=np.float64)
            if a.shape != shape:
                raise ValueError(f"panel.{f} has shape {a.shape}, expected {shape}")
            setattr(self, f, a)


# ── Windows ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def _burn(alpha: float) -> int:
    """Candles after which a seeded exponential smoothing's seed weighs less than CONVERGE_EPS."""
    if alpha >= 1.0:
        return 1
    return int(math.ceil(math.log(CONVERGE_EPS) / math.log(1.0 - alpha)))


def need(measure: str, params: Dict[str, Any]) -> int:
    """Candles a measure needs for its latest value to equal the full-history value (to CONVERGE_EPS for smoothed ones)."""
    p = params
    if measure in PRICE_FIELDS:
        return 1
    if measure in ("sma", "max", "min", "cci", "stoch_k", "bb_upper", "bb_lower"):
        return int(p["period"])
    if measure == "stoch_d":
        return int(p["period"]) + int(p["smooth"]) - 1
    if measure == "ema":
        n = int(p["period"])
        return n + _burn(2.0 / (n + 1.0))
    if measure in ("rsi", "atr", "di_plus", "di_minus"):
        n = int(p["period"])
        return 1 + n + _burn(1.0 / n)
    if measure == "adx":                                                # two Wilder stages in a row
        n = int(p["period"])
        return 1 + 2 * n + int(math.ceil(1.3 * _burn(1.0 / n)))
    if measure in ("macd_line", "macd_signal", "macd_hist"):
        s, sig = max(int(p["slow"]), int(p["fast"])), int(p["signal"])
        return s + _burn(2.0 / (s + 1.0)) + sig + _burn(2.0 / (sig + 1.0))
    if measure == "supertrend":
        n = int(p["period"])
        return 1 + n + _burn(1.0 / n) + PATH_BURN_IN
    if measure == "psar":
        return PATH_BURN_IN
    raise ValueError(f"measure {measure!r} is not supported by the engine")


def _pkey(params: Dict[str, Any]) -> Tuple[Tuple[str, Any], ...]:
    return tuple(sorted((params or {}).items()))


def _operands(spec: Dict[str, Any]) -> Iterator[Tuple[Dict[str, Any], int]]:
    """Every measure operand the run will read, with the extra candles a cross reads (enabled nodes, shown columns, the
    sort column)."""
    def exprs_of_group(g: Dict[str, Any]) -> Iterator[Tuple[Dict[str, Any], int]]:
        for c in g.get("children", []):
            if not c.get("enabled", True):
                continue
            if c["kind"] == "group":
                yield from exprs_of_group(c)
            else:
                extra = 1 if c["op"] in ("crosses_above", "crosses_below") else 0
                yield c["left"], extra
                yield c["right"], extra

    sort_id = spec["sort"]["column"]
    seen = list(exprs_of_group(spec["filters"]))
    seen += [(c["expr"], 0) for c in spec["columns"] if c.get("enabled", True) or c["id"] == sort_id]
    for e, extra in seen:
        for t in e["terms"]:
            if t["operand"]["kind"] == "measure":
                yield t["operand"], extra


def windows(spec: Dict[str, Any]) -> Dict[Tuple[Any, ...], int]:
    """(timeframe, family, params) → candles to compute; a family (MACD, DMI, Bollinger) shares one computation."""
    out: Dict[Tuple[Any, ...], int] = {}
    for op, extra in _operands(spec):
        name, params = op["measure"], op.get("params") or {}
        key = (op["tf"], _FAMILY.get(name, name), _pkey(params))
        w = need(name, params) + int(op.get("offset", 0)) + extra + 1
        out[key] = max(out.get(key, 0), w)
    return out


# ── Evaluation ──────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class _Tri:
    """A three-valued result per stock: passed, failed, or neither (unknown)."""
    passed: np.ndarray
    failed: np.ndarray

    @property
    def unknown(self) -> np.ndarray:
        return ~(self.passed | self.failed)


class _Frame:
    """One timeframe's candles, right-aligned per stock, each field built on first use."""

    def __init__(self, fields: Dict[str, np.ndarray]):
        self._raw = fields
        self._al = ind.Aligner(fields["close"])
        self._done: Dict[str, np.ndarray] = {}
        self.k = self._al.k

    def __getitem__(self, f: str) -> np.ndarray:
        got = self._done.get(f)
        if got is None:
            got = self._done[f] = self._al.align(self._raw[f])
        return got


class _Context:
    """One evaluation: the stocks under test, their timeframes and indicator series, memoised."""

    def __init__(self, panel: Panel, idx: np.ndarray, fundamentals: Dict[str, np.ndarray],
                 wins: Dict[Tuple[Any, ...], int]):
        self.panel, self.idx = panel, idx
        self.n = len(idx)
        n_all = len(panel.symbols)
        # When most stocks are under test, compute on every column (no copy) and pick the rows at read time.
        self.all_cols = self.n * 2 >= n_all
        self.fundamentals = fundamentals
        self.wins = wins
        self.frames: Dict[str, _Frame] = {}
        self.series: Dict[Tuple[Any, ...], np.ndarray] = {}

    def frame(self, tf: str) -> _Frame:
        got = self.frames.get(tf)
        if got is not None:
            return got
        p = self.panel
        # Always the FULL daily history: a stock suspended for months must still get its own previous candles, whatever
        # the gap. Only the indicator maths is windowed (measure_series), on each stock's own right-aligned candles.
        if self.all_cols:
            sub = {f: getattr(p, f) for f in PRICE_FIELDS}
        else:
            sub = {f: getattr(p, f)[:, self.idx] for f in PRICE_FIELDS}
        if tf == "1d":
            src = sub
        elif tf in ("1w", "1M"):
            _, o, h, l, c, v = ind.resample(p.dates, sub["open"], sub["high"], sub["low"], sub["close"], sub["volume"], tf)
            src = {"open": o, "high": h, "low": l, "close": c, "volume": v}
        else:
            raise ValueError(f"timeframe {tf!r} is not supported by the engine")
        got = self.frames[tf] = _Frame(src)
        return got

    def measure_series(self, tf: str, name: str, params: Dict[str, Any]) -> np.ndarray:
        pk = _pkey(params)
        key = (tf, name, pk)
        got = self.series.get(key)
        if got is not None:
            return got
        fr = self.frame(tf)
        k = fr.k
        w = min(k, self.wins.get((tf, _FAMILY.get(name, name), pk), k))

        def f(field: str) -> np.ndarray:
            return fr[field][k - w:]                                    # each stock's last w candles (a view)

        if name in PRICE_FIELDS:
            out = f(name)
        elif name in ("sma", "ema", "max", "min"):
            fn = {"sma": ind.sma, "ema": ind.ema, "max": ind.rolling_max, "min": ind.rolling_min}[name]
            out = fn(f(params["source"]), int(params["period"]))
        elif name == "rsi":
            out = ind.rsi(f("close"), int(params["period"]))
        elif name in ("macd_line", "macd_signal", "macd_hist"):
            line, sig, hist = ind.macd(f("close"), int(params["slow"]), int(params["fast"]), int(params["signal"]))
            self.series[(tf, "macd_line", pk)], self.series[(tf, "macd_signal", pk)] = line, sig
            self.series[(tf, "macd_hist", pk)] = hist
            out = {"macd_line": line, "macd_signal": sig, "macd_hist": hist}[name]
        elif name in ("adx", "di_plus", "di_minus"):
            dip, dim, adx = ind.dmi(f("high"), f("low"), f("close"), int(params["period"]))
            self.series[(tf, "di_plus", pk)], self.series[(tf, "di_minus", pk)], self.series[(tf, "adx", pk)] = dip, dim, adx
            out = {"di_plus": dip, "di_minus": dim, "adx": adx}[name]
        elif name == "atr":
            out = ind.atr(f("high"), f("low"), f("close"), int(params["period"]))
        elif name == "supertrend":
            out = ind.supertrend(f("high"), f("low"), f("close"), int(params["period"]), float(params["multiplier"]))
        elif name == "psar":
            out = ind.psar(f("high"), f("low"), f("close"), float(params["start"]), float(params["increment"]),
                           float(params["max"]))
        elif name == "cci":
            out = ind.cci(f("high"), f("low"), f("close"), int(params["period"]))
        elif name == "stoch_k":
            out = ind.stoch_k(f("high"), f("low"), f("close"), int(params["period"]))
        elif name == "stoch_d":
            out = ind.stoch_d(f("high"), f("low"), f("close"), int(params["period"]), int(params["smooth"]))
        elif name in ("bb_upper", "bb_lower"):
            up, lo = ind.bollinger(f("close"), int(params["period"]), float(params["dev"]))
            self.series[(tf, "bb_upper", pk)], self.series[(tf, "bb_lower", pk)] = up, lo
            out = up if name == "bb_upper" else lo
        else:
            raise ValueError(f"measure {name!r} is not supported by the engine")
        self.series[key] = out
        return out

    def _pick(self, row: np.ndarray) -> np.ndarray:
        return row[self.idx] if self.all_cols else row.copy()

    def operand(self, op: Dict[str, Any], extra: int) -> np.ndarray:
        kind = op["kind"]
        if kind == "number":
            return np.full(self.n, float(op["value"]))
        if kind == "fundamental":
            arr = self.fundamentals.get(op["field"])
            if arr is None:
                return np.full(self.n, np.nan)
            return np.asarray(arr, dtype=np.float64)[self.idx]
        s = self.measure_series(op["tf"], op["measure"], op.get("params") or {})
        row = s.shape[0] - 1 - (int(op.get("offset", 0)) + extra)
        if row < 0:
            return np.full(self.n, np.nan)
        return self._pick(s[row])

    def expr(self, e: Dict[str, Any], extra: int = 0) -> np.ndarray:
        terms = e["terms"]
        acc = self.operand(terms[0]["operand"], extra)
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            for t in terms[1:]:
                v = self.operand(t["operand"], extra)
                op = t["op"]
                if op == "+":
                    acc = acc + v
                elif op == "-":
                    acc = acc - v
                elif op == "*":
                    acc = acc * v
                else:
                    acc = np.where(v == 0, np.nan, acc / np.where(v == 0, 1.0, v))
        return np.where(np.isfinite(acc), acc, np.nan)


def _compare(ctx: _Context, f: Dict[str, Any]) -> _Tri:
    op = f["op"]
    if op in ("crosses_above", "crosses_below"):
        l0, r0 = ctx.expr(f["left"], 0), ctx.expr(f["right"], 0)
        l1, r1 = ctx.expr(f["left"], 1), ctx.expr(f["right"], 1)
        known = ~(np.isnan(l0) | np.isnan(r0) | np.isnan(l1) | np.isnan(r1))
        with np.errstate(invalid="ignore"):
            hit = (l0 > r0) & (l1 <= r1) if op == "crosses_above" else (l0 < r0) & (l1 >= r1)
    else:
        lv, rv = ctx.expr(f["left"]), ctx.expr(f["right"])
        known = ~(np.isnan(lv) | np.isnan(rv))
        with np.errstate(invalid="ignore"):
            hit = {"gt": lv > rv, "gte": lv >= rv, "lt": lv < rv, "lte": lv <= rv, "eq": lv == rv}[op]
    return _Tri(passed=known & hit, failed=known & ~hit)


def _group(ctx: _Context, g: Dict[str, Any], universes: Dict[str, np.ndarray], nodes: Dict[str, Dict[str, int]],
           root: bool = False) -> _Tri:
    results: List[_Tri] = []
    for child in g.get("children", []):
        if not child.get("enabled", True):
            continue
        if child["kind"] == "group":
            results.append(_group(ctx, child, universes, nodes))
        else:
            r = _compare(ctx, child)
            nodes[child["id"]] = {"passed": int(r.passed.sum()), "unknown": int(r.unknown.sum())}
            results.append(r)
    if not results:
        tri = _Tri(passed=np.ones(ctx.n, dtype=bool), failed=np.zeros(ctx.n, dtype=bool))
    else:
        p = np.vstack([r.passed for r in results])
        fl = np.vstack([r.failed for r in results])
        if g.get("join", "all") == "all":
            tri = _Tri(passed=p.all(axis=0), failed=fl.any(axis=0))
        else:
            tri = _Tri(passed=p.any(axis=0), failed=fl.all(axis=0))
    uni = g.get("universe")
    if uni and not root:
        inside = _universe_mask(universes, uni)[ctx.idx]
        tri = _Tri(passed=tri.passed & inside, failed=tri.failed | ~inside)
    nodes[g["id"]] = {"passed": int(tri.passed.sum()), "unknown": int(tri.unknown.sum())}
    return tri


def _universe_mask(universes: Dict[str, np.ndarray], key: str) -> np.ndarray:
    m = universes.get(key)
    if m is None:
        raise ValueError(f"universe {key!r} was not loaded for this run")
    return np.asarray(m, dtype=bool)


def _value_or_none(x: float) -> Optional[float]:
    return float(x) if np.isfinite(x) else None


def evaluate(spec: Dict[str, Any], panel: Panel, *, eligible: Optional[np.ndarray] = None,
             universes: Optional[Dict[str, np.ndarray]] = None,
             fundamentals: Optional[Dict[str, np.ndarray]] = None,
             full_history: bool = False) -> Dict[str, Any]:
    """Run a VALIDATED spec (spec.validate) over `panel`. See the module docstring for the rules.

    eligible: (N,) bool, stocks with a candle on the run day (default: every stock).
    universes: universe key → (N,) bool membership, for every universe the spec names.
    fundamentals: field → (N,) float (NaN = missing); a field not given is missing for every stock.
    full_history: compute every series on all the candles (no windows); the tests compare the two.

    Returns {"order": panel column indices of the shown matches, in order; "columns": [{id, alias, format}] (enabled);
    "values": one list per shown row (float or None, column order); "counts": {evaluated, matched, shown, no_history};
    "nodes": {node id: {passed, unknown}} for every enabled filter and group, over the evaluated stocks}."""
    n = len(panel.symbols)
    universes = universes or {}
    fundamentals = fundamentals or {}
    elig = np.ones(n, dtype=bool) if eligible is None else np.asarray(eligible, dtype=bool)
    if elig.shape != (n,):
        raise ValueError(f"eligible has shape {elig.shape}, expected {(n,)}")
    root = spec["filters"]
    in_root = _universe_mask(universes, root["universe"])
    idx = np.flatnonzero(elig & in_root)
    ctx = _Context(panel, idx, fundamentals, {} if full_history else windows(spec))
    nodes: Dict[str, Dict[str, int]] = {}
    tri = _group(ctx, root, universes, nodes, root=True)
    matched = idx[tri.passed]
    pos = np.flatnonzero(tri.passed)                                    # positions within idx

    columns = spec["columns"]
    shown_cols = [c for c in columns if c.get("enabled", True)]
    sort_col = next(c for c in columns if c["id"] == spec["sort"]["column"])
    keyv = ctx.expr(sort_col["expr"])[pos] if len(pos) else np.zeros(0)
    missing = np.isnan(keyv)
    prim = np.where(missing, 0.0, -keyv if spec["sort"].get("dir", "desc") == "desc" else keyv)
    syms = np.array([panel.symbols[i] for i in matched], dtype=object)
    sym_rank = np.argsort(np.argsort(syms, kind="stable"), kind="stable") if len(syms) else np.zeros(0, dtype=int)
    order_local = np.lexsort((sym_rank, prim, missing)) if len(pos) else np.zeros(0, dtype=int)
    order_local = order_local[: int(spec.get("limit", 50))]

    col_vals = [ctx.expr(c["expr"])[pos][order_local] for c in shown_cols]
    values = [[_value_or_none(col_vals[j][r]) for j in range(len(shown_cols))] for r in range(len(order_local))]
    return {
        "order": [int(matched[i]) for i in order_local],
        "columns": [{"id": c["id"], "alias": c["alias"], "format": c.get("format", "number")} for c in shown_cols],
        "values": values,
        "counts": {"evaluated": int(len(idx)), "matched": int(len(matched)), "shown": int(len(order_local)),
                   "no_history": int(tri.unknown.sum())},
        "nodes": nodes,
    }
