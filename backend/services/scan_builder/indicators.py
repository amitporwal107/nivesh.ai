"""Technical indicators for a whole universe at once (docs/scan_builder/DESIGN.md §3 "Definitions").

Arrays are RIGHT-ALIGNED (K, N) float64: column j is one stock, row K-1 is its latest candle, row K-2 the one before, and the
rows above its first candle are NaN. `compress` builds that layout from the common calendar, so "1 candle ago" always means
the stock's own previous candle (a suspension leaves no hole). Every function returns the full (K, N) series, causal (row i
uses rows <= i only), NaN until the stock has the candles its definition needs. Nothing raises on short history.

Recursive indicators (EMA, Wilder smoothing, Supertrend, Parabolic SAR) loop over ROWS with N-wide numpy operations, never over
stocks, so ~2,700 stocks x ~650 rows stays well under a second for a scan.

Conventions where textbooks differ (tests/test_scan_builder_indicators.py pins each against a plain per-stock loop):
  * EMA: seeded with the SMA of the first `period` values, then alpha 2/(period+1). Wilder smoothing (RSI, ATR, DI, ADX): the
    same seed, alpha 1/period. Once started, a missing input gives NaN on that row and leaves the state as it was.
  * True range needs the previous close, so a stock's first candle has none: ATR(n), +DI and −DI start on candle n+1, ADX on
    candle 2n.
  * RSI with no losses is 100, and 50 when there were neither gains nor losses (a flat series): never a division by zero.
  * Fast stochastic %K is 50 and CCI is 0 when the window has no range; Bollinger uses the population standard deviation.
  * Supertrend follows Pine Script's ta.supertrend: bands HL2 ± mult·ATR carried while the previous close stays inside them,
    the close compared with the CURRENT band to flip, and the first candle with an ATR starting on the upper band.
  * Parabolic SAR follows Pine Script's ta.sar: the first trend comes from the stock's first two closes (up if the 2nd close
    is higher), acceleration starts at `start`, grows by `increment` at each new extreme up to `max`, and on a reversal the
    SAR jumps to the old extreme.
  * Weekly candles run Monday to Sunday and monthly candles by calendar month; the latest one is the period in progress.
"""
from __future__ import annotations

from typing import Dict, Tuple

import numpy as np

Array = np.ndarray
NAN = np.nan


def _nan(shape: Tuple[int, ...]) -> Array:
    return np.full(shape, NAN)


def _cumsum0(x: Array) -> Array:
    """Cumulative sum down the rows. A loop over rows is several times faster than np.cumsum(axis=0) on (K, N) arrays
    (the column-wise walk is cache-unfriendly): ~1.4 ms against ~6.4 ms at 650 x 2,700."""
    out = np.empty(x.shape, dtype=np.float64)
    acc = np.zeros(x.shape[1:], dtype=np.float64)
    for i in range(x.shape[0]):
        acc += x[i]
        out[i] = acc
    return out


def _starts(valid: Array) -> Tuple[Array, Array, bool]:
    """(first row with a number, count of numbers, True when every column is gap-free from its first number on)."""
    cnt = valid.sum(axis=0)
    start = np.argmax(valid, axis=0)
    return start, cnt, bool(np.all((cnt == 0) | (cnt == valid.shape[0] - start)))


# ── Layout ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def shift(x: Array, s: int) -> Array:
    """out[i] = x[i - s] for s >= 0; the first s rows are NaN."""
    out = _nan(x.shape)
    if s <= 0:
        out[:] = x
    elif s < x.shape[0]:
        out[s:] = x[: x.shape[0] - s]
    return out


class Aligner:
    """Right-aligns the fields of one common-calendar panel, one field at a time and only when asked (a scan that reads close
    and volume never pays for open, high and low).

    A candle exists where `close` is a number. Each stock's candles keep their date order and move to the bottom rows; every
    field is NaN where there is no candle. Most stocks trade every day up to the last row, so their bottom k rows already
    are right-aligned; only the others (a gap, or no candle on the last day) are sorted, once, here."""

    def __init__(self, close: Array):
        valid = ~np.isnan(close)
        self.t, self.n = close.shape
        start, self.counts, _ = _starts(valid)
        self.k = int(self.counts.max()) if self.t and self.n else 0
        k, t = self.k, self.t
        self.gapped = np.flatnonzero((self.counts > 0) & (self.counts != t - start))
        self.keep = valid[t - k:]
        self.order = self.kb = None
        if self.k and self.gapped.size:
            vb = valid[:, self.gapped]
            self.order = np.argsort(vb, axis=0, kind="stable")[t - k:]   # stable: missing rows first, candles in date order
            self.kb = np.take_along_axis(vb, self.order, axis=0)

    def align(self, a: Array) -> Array:
        """One field, (K, N), right-aligned. A new array (the panel is never written to)."""
        if self.k == 0:
            return _nan((0, self.n))
        a = np.asarray(a, dtype=np.float64)
        out = np.where(self.keep, a[self.t - self.k:], NAN)
        if self.order is not None:
            out[:, self.gapped] = np.where(self.kb, np.take_along_axis(a[:, self.gapped], self.order, axis=0), NAN)
        return out


def compress(arrays: Dict[str, Array]) -> Tuple[Dict[str, Array], Array]:
    """Common-calendar (T, N) arrays → right-aligned (K, N) arrays, K = the most candles any stock has (see Aligner).
    Returns (arrays, candles per stock)."""
    al = Aligner(arrays["close"])
    return {f: al.align(a) for f, a in arrays.items()}, al.counts


def period_keys(dates: Array, tf: str) -> Array:
    """An integer per day naming its period: the Monday of its week ("1w") or its calendar month ("1M")."""
    d = np.asarray(dates).astype("datetime64[D]")
    if tf == "1w":
        days = d.astype(np.int64)
        return days - ((days + 3) % 7)                                  # 1970-01-01 was a Thursday
    if tf == "1M":
        return d.astype("datetime64[M]").astype(np.int64)
    raise ValueError(f"unknown period {tf!r}")


def resample(dates: Array, o: Array, h: Array, l: Array, c: Array, v: Array,
             tf: str) -> Tuple[Array, Array, Array, Array, Array, Array]:
    """Daily candles on the common calendar → weekly ("1w") or monthly ("1M") candles on a common period calendar.

    Open = the period's first candle's open, close = its last candle's close, high / low = the extremes, volume = the sum; a
    stock with no candle in a period has NaN there. Returns (period start dates, open, high, low, close, volume)."""
    t, n = c.shape
    if t == 0:
        return (np.asarray(dates).astype("datetime64[D]")[:0], _nan((0, n)), _nan((0, n)), _nan((0, n)), _nan((0, n)),
                _nan((0, n)))
    keys = period_keys(dates, tf)
    starts = np.flatnonzero(np.r_[True, keys[1:] != keys[:-1]])
    valid = ~np.isnan(c)
    rows = np.arange(t)[:, None]
    first = np.minimum.reduceat(np.where(valid, rows, t), starts, axis=0)
    last = np.maximum.reduceat(np.where(valid, rows, -1), starts, axis=0)
    has = last >= 0
    cols = np.arange(n)[None, :]
    fi, li = np.where(has, first, 0), np.where(has, last, 0)
    po = np.where(has, o[fi, cols], NAN)
    pc = np.where(has, c[li, cols], NAN)
    ph = np.where(has, np.fmax.reduceat(np.where(valid, h, NAN), starts, axis=0), NAN)
    pl = np.where(has, np.fmin.reduceat(np.where(valid, l, NAN), starts, axis=0), NAN)
    pv = np.where(has, np.add.reduceat(np.where(valid & ~np.isnan(v), v, 0.0), starts, axis=0), NAN)
    if tf == "1w":
        pdates = keys[starts].astype("datetime64[D]")
    else:
        pdates = keys[starts].astype("datetime64[M]").astype("datetime64[D]")
    return pdates, po, ph, pl, pc, pv


# ── Windows and smoothing ───────────────────────────────────────────────────────────────────────────────────────────

def flat_windows(x: Array, n: int) -> Array:
    """True where the last n values are all present and equal (highest == lowest, an exact comparison)."""
    with np.errstate(invalid="ignore"):
        return rolling_max(x, n) == rolling_min(x, n)


def sma(x: Array, n: int) -> Array:
    """Mean of the last n values; NaN unless all n are numbers. A flat window gives its value exactly: a summed mean of
    999.99 taken n times can be off by a unit in the last place, and a scan comparing a flat ETF's close with its average
    must not flip on that noise."""
    k = x.shape[0]
    out = _nan(x.shape)
    if n < 1 or n > k:
        return out
    valid = ~np.isnan(x)
    zeros = np.zeros((1,) + x.shape[1:])
    cs = np.vstack([zeros, _cumsum0(np.where(valid, x, 0.0))])
    cv = np.vstack([zeros, _cumsum0(valid.astype(np.float64))])
    out[n - 1:] = np.where((cv[n:] - cv[:-n]) == n, (cs[n:] - cs[:-n]) / n, NAN)
    flat = flat_windows(x, n)                                           # n = 1 is always "flat": the value itself
    if flat.any():
        out = np.where(flat, x, out)
    return out


def _rolling_extreme(x: Array, n: int, fn) -> Array:
    """fn (np.maximum / np.minimum, which keep NaN) over the last n values, by doubling windows: O(K·N·log n)."""
    k = x.shape[0]
    out = _nan(x.shape)
    if n < 1 or n > k:
        return out
    m, span = np.asarray(x, dtype=np.float64).copy(), 1
    while span * 2 <= n:
        m = fn(m, shift(m, span))                                       # m[i] = extreme over [i - 2·span + 1, i]
        span *= 2
    res = fn(m, shift(m, n - span)) if n > span else m
    out[n - 1:] = res[n - 1:]
    return out


def rolling_max(x: Array, n: int) -> Array:
    return _rolling_extreme(x, n, np.maximum)


def rolling_min(x: Array, n: int) -> Array:
    return _rolling_extreme(x, n, np.minimum)


def _seeded(x: Array, n: int, alpha: float) -> Array:
    """Seed = the mean of each column's first n numbers (on the row the n-th arrives), then s = alpha·x + (1 − alpha)·s."""
    k = x.shape[0]
    cols = x.shape[1:]
    out = _nan(x.shape)
    if n < 1 or k == 0:
        return out
    valid = ~np.isnan(x)
    beta = 1.0 - alpha
    start, cnt, gap_free = _starts(valid)
    if gap_free:
        # The usual case (no gap once a column has started): seed each column on its n-th row, then update whole rows in
        # place. Before a column's seed its state is scratch (NaN or garbage) and is never written out.
        ready = cnt >= n
        if not ready.any():
            return out
        seed_row = np.where(ready, start + n - 1, k)                    # k = never
        rows = np.minimum(start[None, :] + np.arange(n)[:, None], k - 1)
        seed_val = np.take_along_axis(x, rows, axis=0).sum(axis=0) / n
        order = np.argsort(seed_row, kind="stable")
        first = int(seed_row[order[0]])
        bounds = np.searchsorted(seed_row[order], np.arange(first, k + 1))
        state = np.zeros(cols)
        started = np.zeros(cols, dtype=bool)
        with np.errstate(invalid="ignore"):
            for i in range(first, k):
                state *= beta
                state += alpha * x[i]
                lo, hi = bounds[i - first], bounds[i - first + 1]
                if hi > lo:
                    js = order[lo:hi]
                    state[js] = seed_val[js]
                    started[js] = True
                out[i] = np.where(started, state, NAN)
        return out
    # General case (a column with a gap after its start): the plain recursion, a missing value leaving the state alone.
    cv = np.cumsum(valid, axis=0)
    seed = valid & (cv == n)
    if not seed.any():
        return out
    seed_val = np.cumsum(np.where(valid, x, 0.0), axis=0) / n
    xz = np.where(valid, x, 0.0)
    first = int(np.argmax(seed.any(axis=1)))
    state = np.full(cols, NAN)
    started = np.zeros(cols, dtype=bool)
    for i in range(first, k):
        upd = started & valid[i]
        state = np.where(seed[i], seed_val[i], np.where(upd, alpha * xz[i] + beta * state, state))
        started |= seed[i]
        out[i] = np.where(started & valid[i], state, NAN)
    return out


def ema(x: Array, n: int) -> Array:
    return _seeded(x, n, 2.0 / (n + 1.0))


def wilder(x: Array, n: int) -> Array:
    return _seeded(x, n, 1.0 / n)


# ── Momentum ────────────────────────────────────────────────────────────────────────────────────────────────────────

def rsi(c: Array, n: int) -> Array:
    d = c - shift(c, 1)
    ok = ~np.isnan(d)
    gain = np.where(ok, np.maximum(d, 0.0), NAN)
    loss = np.where(ok, np.maximum(-d, 0.0), NAN)
    ag, al = wilder(gain, n), wilder(loss, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = 100.0 - 100.0 / (1.0 + ag / al)
    r = np.where(al == 0, np.where(ag == 0, 50.0, 100.0), r)
    return np.where(np.isnan(ag) | np.isnan(al), NAN, r)


def macd(c: Array, slow: int, fast: int, signal: int) -> Tuple[Array, Array, Array]:
    """(line, signal, histogram): line = EMA(close, fast) − EMA(close, slow), signal = EMA(line, signal)."""
    line = ema(c, fast) - ema(c, slow)
    sig = ema(line, signal)
    return line, sig, line - sig


def stoch_k(h: Array, l: Array, c: Array, n: int) -> Array:
    hh, ll = rolling_max(h, n), rolling_min(l, n)
    rng = hh - ll
    with np.errstate(divide="ignore", invalid="ignore"):
        k = np.where(rng == 0, 50.0, 100.0 * (c - ll) / rng)
    return np.where(np.isnan(rng) | np.isnan(c), NAN, k)


def stoch_d(h: Array, l: Array, c: Array, n: int, smooth: int) -> Array:
    return sma(stoch_k(h, l, c, n), smooth)


def cci(h: Array, l: Array, c: Array, n: int) -> Array:
    tp = (h + l + c) / 3.0
    ma = sma(tp, n)
    k = tp.shape[0]
    if n < 1 or n > k:
        return _nan(tp.shape)
    dev = np.zeros(tp.shape)
    buf = np.empty(tp.shape)
    for j in range(n):                                                  # mean absolute deviation around this window's mean
        b = buf[j:]
        np.subtract(tp[: k - j], ma[j:], out=b)
        np.abs(b, out=b)
        dev[j:] += b
    dev[: n - 1] = NAN
    mad = dev / n
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(mad == 0, 0.0, (tp - ma) / (0.015 * mad))
    return np.where(np.isnan(ma) | np.isnan(mad), NAN, out)


# ── Volatility ──────────────────────────────────────────────────────────────────────────────────────────────────────

def true_range(h: Array, l: Array, c: Array) -> Array:
    """max(H − L, |H − previous close|, |L − previous close|); NaN without a previous close."""
    pc = shift(c, 1)
    return np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))


def atr(h: Array, l: Array, c: Array, n: int) -> Array:
    return wilder(true_range(h, l, c), n)


def bollinger(c: Array, n: int, dev: float) -> Tuple[Array, Array]:
    """(upper, lower) = SMA ± dev × population standard deviation of the same n closes. A flat window has both bands
    exactly on the close (SD 0, no float noise), so "close above the upper band" is false for a flat ETF."""
    k = c.shape[0]
    if n < 1 or n > k:
        return _nan(c.shape), _nan(c.shape)
    # Window sums of y and y² by cumulative sums, y = close minus each stock's latest close (centring keeps the variance
    # E[y²] − E[y]² free of cancellation at price scale).
    ref = np.where(np.isnan(c[-1]), 0.0, c[-1])
    y = c - ref
    valid = ~np.isnan(y)
    yz = np.where(valid, y, 0.0)
    zeros = np.zeros((1,) + c.shape[1:])
    s1 = np.vstack([zeros, _cumsum0(yz)])
    s2 = np.vstack([zeros, _cumsum0(yz * yz)])
    cv = np.vstack([zeros, _cumsum0(valid.astype(np.float64))])
    full = (cv[n:] - cv[:-n]) == n
    m = (s1[n:] - s1[:-n]) / n
    var = np.maximum((s2[n:] - s2[:-n]) / n - m * m, 0.0)
    sd = _nan(c.shape)
    sd[n - 1:] = np.where(full, np.sqrt(var), NAN)
    mid = sma(c, n)                                                     # exact on a flat window
    flat = flat_windows(c, n)
    sd = np.where(flat, 0.0, sd)
    return mid + dev * sd, mid - dev * sd


# ── Trend ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def dmi(h: Array, l: Array, c: Array, n: int) -> Tuple[Array, Array, Array]:
    """(+DI, −DI, ADX), Wilder: +DI = 100·W(+DM)/W(TR) (0 when W(TR) is 0), DX = 100·|+DI − −DI|/(+DI + −DI) (0 when both
    are 0), ADX = W(DX)."""
    up = h - shift(h, 1)
    dn = shift(l, 1) - l
    with np.errstate(invalid="ignore"):
        # up > dn and up > 0 -> up, else 0 (a NaN comparison is False, so the missing rows are restored below).
        pdm = np.where(up > dn, np.maximum(up, 0.0), 0.0)
        mdm = np.where(dn > up, np.maximum(dn, 0.0), 0.0)
    missing = np.isnan(up + dn)
    pdm[missing] = NAN
    mdm[missing] = NAN
    tr = wilder(true_range(h, l, c), n)
    sp, sm = wilder(pdm, n), wilder(mdm, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        inv = np.where(tr == 0, 0.0, 100.0 / tr)                        # NaN where TR is missing: it carries through
        dip, dim = sp * inv, sm * inv
        tot = dip + dim
        dx = np.where(tot == 0, 0.0, 100.0 * np.abs(dip - dim) / tot)
    return dip, dim, wilder(dx, n)


def supertrend(h: Array, l: Array, c: Array, n: int, mult: float) -> Array:
    """The Supertrend line (Pine ta.supertrend); see the module notes."""
    a = atr(h, l, c, n)
    hl2 = (h + l) / 2.0
    bu, bl = hl2 + mult * a, hl2 - mult * a
    k = c.shape[0]
    cols = c.shape[1:]
    out = _nan(c.shape)
    fu, fl, st = np.full(cols, NAN), np.full(cols, NAN), np.full(cols, NAN)
    started = np.zeros(cols, dtype=bool)
    with np.errstate(invalid="ignore"):
        for i in range(k):
            ok = ~np.isnan(bu[i]) & ~np.isnan(c[i])
            if not ok.any():
                continue
            first = ok & ~started
            cont = ok & started
            pc = c[i - 1] if i else np.full(cols, NAN)
            nfu = np.where(cont & ~((bu[i] < fu) | (pc > fu)), fu, bu[i])
            nfl = np.where(cont & ~((bl[i] > fl) | (pc < fl)), fl, bl[i])
            was_upper = st == fu                                        # Pine: prevSuperTrend == prevUpperBand
            on_upper = np.where(first, True, np.where(was_upper, ~(c[i] > nfu), c[i] < nfl))
            st = np.where(ok, np.where(on_upper, nfu, nfl), st)
            fu, fl = np.where(ok, nfu, fu), np.where(ok, nfl, fl)
            started |= ok
            out[i] = np.where(ok, st, NAN)
    return out


def psar(h: Array, l: Array, c: Array, start: float, inc: float, mx: float) -> Array:
    """Parabolic SAR (Pine ta.sar); see the module notes. NaN on a stock's first candle."""
    k = c.shape[0]
    cols = c.shape[1:]
    out = _nan(c.shape)
    valid = ~(np.isnan(c) | np.isnan(h) | np.isnan(l))
    bi = _cumsum0(valid.astype(np.float64)) - 1                         # the candle's index in the stock's own history
    res, mm, acc = np.full(cols, NAN), np.full(cols, NAN), np.full(cols, NAN)
    below = np.zeros(cols, dtype=bool)                                  # True: SAR below price (an up trend)
    with np.errstate(invalid="ignore"):
        for i in range(1, k):
            v = valid[i] & (bi[i] >= 1)
            if not v.any():
                continue
            init = v & (bi[i] == 1)
            hi, lo = h[i], l[i]
            h1, l1 = h[i - 1], l[i - 1]
            up0 = c[i] > c[i - 1]
            below = np.where(init, up0, below)
            mm = np.where(init, np.where(up0, hi, lo), mm)
            res = np.where(init, np.where(up0, l1, h1), res)
            acc = np.where(init, start, acc)
            r = res + acc * (mm - res)
            rev_dn = v & below & (r > lo)
            rev_up = v & ~below & (r < hi)
            r = np.where(rev_dn, np.maximum(hi, mm), np.where(rev_up, np.minimum(lo, mm), r))
            nmm = np.where(rev_dn, lo, np.where(rev_up, hi, mm))
            nbelow = np.where(rev_dn, False, np.where(rev_up, True, below))
            nacc = np.where(rev_dn | rev_up, start, acc)
            ext = v & ~(init | rev_dn | rev_up)
            ext_up = ext & nbelow & (hi > nmm)
            ext_dn = ext & ~nbelow & (lo < nmm)
            nmm = np.where(ext_up, hi, np.where(ext_dn, lo, nmm))
            nacc = np.where(ext_up | ext_dn, np.minimum(nacc + inc, mx), nacc)
            r = np.where(nbelow, np.minimum(r, l1), np.maximum(r, h1))
            if i >= 2:
                has2 = bi[i] > 1
                r = np.where(has2 & nbelow, np.minimum(r, l[i - 2]), np.where(has2 & ~nbelow, np.maximum(r, h[i - 2]), r))
            res, mm = np.where(v, r, res), np.where(v, nmm, mm)
            acc, below = np.where(v, nacc, acc), np.where(v, nbelow, below)
            out[i] = np.where(v, res, NAN)
    return out


__all__ = [
    "shift", "Aligner", "compress", "flat_windows", "period_keys", "resample", "sma", "ema", "wilder", "rolling_max", "rolling_min", "rsi", "macd",
    "stoch_k", "stoch_d", "cci", "true_range", "atr", "bollinger", "dmi", "supertrend", "psar",
]
