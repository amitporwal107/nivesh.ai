"""Scan Builder indicators (services/scan_builder/indicators.py) against plain per-stock Python loops.

TC-U1..TC-U8 of test_reports/scan_builder_20261103_0431.md. Every vectorised indicator is compared, column by column, with a
straightforward loop over one stock's own candles written here from the definitions in docs/scan_builder/DESIGN.md §3. The
panel is ragged (stocks start on different rows, as right-aligned history does), one stock is flat (no gains, no losses, no
range) and one has a gap after its start (the general, non-fast path of the smoothing).
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from services.scan_builder import indicators as ind

NAN = float("nan")
K = 140
STARTS = [0, 3, 25, 60, 100, 128, 0]          # leading rows without history, per stock; the last stock is flat
FLAT = 6


def _panel(seed: int = 7):
    rng = np.random.default_rng(seed)
    n = len(STARTS)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, (K, n)), axis=0))
    o = c * (1 + rng.normal(0, 0.006, (K, n)))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.01, (K, n))))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.01, (K, n))))
    v = rng.integers(1_000, 1_000_000, (K, n)).astype(float)
    c[:, FLAT] = o[:, FLAT] = h[:, FLAT] = l[:, FLAT] = 50.0
    for j, s in enumerate(STARTS):
        for a in (o, h, l, c, v):
            a[:s, j] = NAN
    return o, h, l, c, v


O, H, L, C, V = _panel()


def _seg(a: np.ndarray, j: int):
    """One stock's candles (its column without the leading rows)."""
    return [float(x) for x in a[STARTS[j]:, j]]


def _place(vals, j: int) -> np.ndarray:
    out = np.full(K, NAN)
    out[STARTS[j]:] = [NAN if x is None else x for x in vals]
    return out


def _close(got: np.ndarray, want_cols, tol: float = 1e-9) -> None:
    for j, want in enumerate(want_cols):
        g = got[:, j]
        assert np.array_equal(np.isnan(g), np.isnan(want)), f"stock {j}: missing rows differ"
        m = ~np.isnan(want)
        np.testing.assert_allclose(g[m], want[m], rtol=tol, atol=tol, err_msg=f"stock {j}")


# ── Reference loops (one stock, its own candles) ──────────────────────────────────────────────────────────────────────

def r_sma(xs, n):
    return [sum(xs[i - n + 1:i + 1]) / n if i >= n - 1 else None for i in range(len(xs))]


def r_seeded(xs, n, alpha):
    """Seed = mean of the first n numbers; then s = alpha x + (1 - alpha) s. A None after the start leaves s alone."""
    out, s, seen, acc = [], None, 0, 0.0
    for x in xs:
        if x is None or (isinstance(x, float) and math.isnan(x)):
            out.append(None)
            continue
        if s is None:
            seen += 1
            acc += x
            if seen == n:
                s = acc / n
                out.append(s)
            else:
                out.append(None)
        else:
            s = alpha * x + (1 - alpha) * s
            out.append(s)
    return out


def r_ema(xs, n):
    return r_seeded(xs, n, 2 / (n + 1))


def r_wilder(xs, n):
    return r_seeded(xs, n, 1 / n)


def r_rsi(c, n):
    d = [None] + [c[i] - c[i - 1] for i in range(1, len(c))]
    ag = r_wilder([None if x is None else max(x, 0.0) for x in d], n)
    al = r_wilder([None if x is None else max(-x, 0.0) for x in d], n)
    out = []
    for g, lo in zip(ag, al):
        if g is None or lo is None:
            out.append(None)
        elif lo == 0:
            out.append(50.0 if g == 0 else 100.0)
        else:
            out.append(100 - 100 / (1 + g / lo))
    return out


def r_tr(h, l, c):
    return [None] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]


def r_dmi(h, l, c, n):
    pdm, mdm = [None], [None]
    for i in range(1, len(c)):
        up, dn = h[i] - h[i - 1], l[i - 1] - l[i]
        pdm.append(up if (up > dn and up > 0) else 0.0)
        mdm.append(dn if (dn > up and dn > 0) else 0.0)
    trw, sp, sm = r_wilder(r_tr(h, l, c), n), r_wilder(pdm, n), r_wilder(mdm, n)
    dip, dim, dx = [], [], []
    for t, p, m in zip(trw, sp, sm):
        if t is None or p is None or m is None:
            dip.append(None), dim.append(None), dx.append(None)
            continue
        a = 0.0 if t == 0 else 100 * p / t
        b = 0.0 if t == 0 else 100 * m / t
        dip.append(a), dim.append(b)
        dx.append(0.0 if a + b == 0 else 100 * abs(a - b) / (a + b))
    return dip, dim, r_wilder(dx, n)


def r_cci(h, l, c, n):
    tp = [(a + b + d) / 3 for a, b, d in zip(h, l, c)]
    out = []
    for i in range(len(tp)):
        if i < n - 1:
            out.append(None)
            continue
        w = tp[i - n + 1:i + 1]
        m = sum(w) / n
        mad = sum(abs(x - m) for x in w) / n
        out.append(0.0 if mad == 0 else (tp[i] - m) / (0.015 * mad))
    return out


def r_stoch_k(h, l, c, n):
    out = []
    for i in range(len(c)):
        if i < n - 1:
            out.append(None)
            continue
        hh, ll = max(h[i - n + 1:i + 1]), min(l[i - n + 1:i + 1])
        out.append(50.0 if hh == ll else 100 * (c[i] - ll) / (hh - ll))
    return out


def r_bollinger(c, n, dev):
    up, lo = [], []
    for i in range(len(c)):
        if i < n - 1:
            up.append(None), lo.append(None)
            continue
        w = c[i - n + 1:i + 1]
        m = sum(w) / n
        sd = math.sqrt(sum((x - m) ** 2 for x in w) / n)
        up.append(m + dev * sd), lo.append(m - dev * sd)
    return up, lo


def r_supertrend(h, l, c, n, mult):
    """Pine Script ta.supertrend, line by line."""
    a = r_wilder(r_tr(h, l, c), n)
    out, fu, fl, st = [], None, None, None
    for i in range(len(c)):
        if a[i] is None:
            out.append(None)
            continue
        bu = (h[i] + l[i]) / 2 + mult * a[i]
        bl = (h[i] + l[i]) / 2 - mult * a[i]
        if fu is None:
            nfu, nfl, upper = bu, bl, True
        else:
            nfu = bu if (bu < fu or c[i - 1] > fu) else fu
            nfl = bl if (bl > fl or c[i - 1] < fl) else fl
            upper = (not c[i] > nfu) if st == fu else (c[i] < nfl)
        st = nfu if upper else nfl
        fu, fl = nfu, nfl
        out.append(st)
    return out


def r_psar(h, l, c, start, inc, mx):
    """Pine Script ta.sar, line by line."""
    out = [None]
    res = mm = acc = None
    below = False
    for i in range(1, len(c)):
        first = False
        if i == 1:
            if c[i] > c[i - 1]:
                below, mm, res = True, h[i], l[i - 1]
            else:
                below, mm, res = False, l[i], h[i - 1]
            first, acc = True, start
        res = res + acc * (mm - res)
        if below:
            if res > l[i]:
                first, below, res, mm, acc = True, False, max(h[i], mm), l[i], start
        else:
            if res < h[i]:
                first, below, res, mm, acc = True, True, min(l[i], mm), h[i], start
        if not first:
            if below and h[i] > mm:
                mm, acc = h[i], min(acc + inc, mx)
            elif not below and l[i] < mm:
                mm, acc = l[i], min(acc + inc, mx)
        if below:
            res = min(res, l[i - 1])
            if i > 1:
                res = min(res, l[i - 2])
        else:
            res = max(res, h[i - 1])
            if i > 1:
                res = max(res, h[i - 2])
        out.append(res)
    return out


def _ref(fn, *arrays, **kw):
    return [_place(fn(*[_seg(a, j) for a in arrays], **kw), j) for j in range(len(STARTS))]


# ── TC-U1: SMA, EMA, Wilder, rolling max/min ────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("n", [1, 5, 14, 20])
def test_sma_matches_reference(n):
    _close(ind.sma(C, n), _ref(r_sma, C, n=n))


@pytest.mark.parametrize("n", [1, 9, 12, 26, 50])
def test_ema_matches_reference(n):
    _close(ind.ema(C, n), _ref(r_ema, C, n=n))


@pytest.mark.parametrize("n", [3, 14])
def test_wilder_matches_reference(n):
    _close(ind.wilder(V, n), _ref(r_wilder, V, n=n), tol=1e-8)


@pytest.mark.parametrize("n", [1, 2, 3, 4, 7, 20, 52])
def test_rolling_max_min_match_reference(n):
    want_max = _ref(lambda xs, n: [max(xs[i - n + 1:i + 1]) if i >= n - 1 else None for i in range(len(xs))], H, n=n)
    want_min = _ref(lambda xs, n: [min(xs[i - n + 1:i + 1]) if i >= n - 1 else None for i in range(len(xs))], L, n=n)
    _close(ind.rolling_max(H, n), want_max, tol=0)
    _close(ind.rolling_min(L, n), want_min, tol=0)


def test_smoothing_with_a_gap_after_the_start_keeps_the_state():
    x = C[:, :3].copy()
    x[70, 0] = NAN                                   # a missing value after stock 0 has started: the general path
    for fn, ref in ((ind.ema, r_ema), (ind.wilder, r_wilder)):
        got = fn(x, 10)
        for j in range(3):
            seg = [None if math.isnan(v) else float(v) for v in x[STARTS[j]:, j]]
            want = _place(ref(seg, 10), j)
            g = got[:, j]
            assert np.array_equal(np.isnan(g), np.isnan(want))
            np.testing.assert_allclose(g[~np.isnan(want)], want[~np.isnan(want)], rtol=1e-9)
    assert np.isnan(ind.ema(x, 10)[70, 0]) and not np.isnan(ind.ema(x, 10)[71, 0])


# ── TC-U2 / TC-U3: RSI, MACD ────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("n", [2, 14])
def test_rsi_matches_reference(n):
    _close(ind.rsi(C, n), _ref(r_rsi, C, n=n), tol=1e-8)


def test_rsi_of_a_flat_series_is_50_and_of_a_rising_one_is_100():
    r = ind.rsi(C, 14)
    assert np.all(r[14:, FLAT] == 50.0)
    up = np.arange(1, 41, dtype=float)[:, None]
    assert ind.rsi(up, 14)[-1, 0] == 100.0


def test_macd_matches_reference():
    slow, fast, sig = 26, 12, 9
    line, signal, hist = ind.macd(C, slow, fast, sig)
    want_line = []
    for j in range(len(STARTS)):
        xs = _seg(C, j)
        ef, es = r_ema(xs, fast), r_ema(xs, slow)
        want_line.append([None if (a is None or b is None) else a - b for a, b in zip(ef, es)])
    want_sig = [r_ema(wl, sig) for wl in want_line]
    _close(line, [_place(w, j) for j, w in enumerate(want_line)], tol=1e-9)
    _close(signal, [_place(w, j) for j, w in enumerate(want_sig)], tol=1e-9)
    _close(hist, [_place([None if (a is None or b is None) else a - b for a, b in zip(wl, ws)], j)
                  for j, (wl, ws) in enumerate(zip(want_line, want_sig))], tol=1e-9)


# ── TC-U4: TR, ATR, +DI, −DI, ADX ───────────────────────────────────────────────────────────────────────────────────

def test_true_range_and_atr_match_reference():
    _close(ind.true_range(H, L, C), _ref(r_tr, H, L, C), tol=1e-12)
    _close(ind.atr(H, L, C, 14), _ref(lambda h, l, c: r_wilder(r_tr(h, l, c), 14), H, L, C), tol=1e-9)


@pytest.mark.parametrize("n", [5, 14])
def test_dmi_matches_reference(n):
    dip, dim, adx = ind.dmi(H, L, C, n)
    refs = [r_dmi(_seg(H, j), _seg(L, j), _seg(C, j), n) for j in range(len(STARTS))]
    _close(dip, [_place(r[0], j) for j, r in enumerate(refs)], tol=1e-8)
    _close(dim, [_place(r[1], j) for j, r in enumerate(refs)], tol=1e-8)
    _close(adx, [_place(r[2], j) for j, r in enumerate(refs)], tol=1e-8)


def test_adx_needs_2n_candles_and_di_n_plus_1():
    dip, _, adx = ind.dmi(H, L, C, 14)
    j = 0
    assert np.isnan(dip[13, j]) and not np.isnan(dip[14, j])       # first DI on candle n + 1 (row n)
    assert np.isnan(adx[26, j]) and not np.isnan(adx[27, j])       # first ADX on candle 2n (row 2n - 1)


# ── TC-U5 / TC-U6: Supertrend, Parabolic SAR ────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("n,mult", [(7, 3.0), (10, 1.0), (3, 0.5)])
def test_supertrend_matches_pine_reference(n, mult):
    _close(ind.supertrend(H, L, C, n, mult), _ref(r_supertrend, H, L, C, n=n, mult=mult), tol=1e-9)


def test_supertrend_flips_both_ways():
    st = ind.supertrend(H, L, C, 3, 0.5)
    j = 0
    m = ~np.isnan(st[:, j])
    above = (st[m, j] < C[m, j])                                     # line below price = up trend
    assert above.any() and (~above).any(), "the sample must contain both trends"
    assert np.any(np.diff(above.astype(int)) == 1) and np.any(np.diff(above.astype(int)) == -1)


@pytest.mark.parametrize("start,inc,mx", [(0.02, 0.02, 0.2), (0.01, 0.005, 0.1), (0.1, 0.1, 0.3)])
def test_psar_matches_pine_reference(start, inc, mx):
    _close(ind.psar(H, L, C, start, inc, mx), _ref(r_psar, H, L, C, start=start, inc=inc, mx=mx), tol=1e-9)


def test_psar_reverses():
    s = ind.psar(H, L, C, 0.02, 0.02, 0.2)[:, 0]
    m = ~np.isnan(s)
    below = s[m] < C[m, 0]
    assert below.any() and (~below).any()


# ── TC-U7: CCI, stochastic, Bollinger ───────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("n", [2, 20])
def test_cci_matches_reference(n):
    _close(ind.cci(H, L, C, n), _ref(r_cci, H, L, C, n=n), tol=1e-8)


def test_stochastic_matches_reference():
    _close(ind.stoch_k(H, L, C, 14), _ref(r_stoch_k, H, L, C, n=14), tol=1e-9)
    want_d = _ref(lambda h, l, c: r_sma_none(r_stoch_k(h, l, c, 14), 3), H, L, C)
    _close(ind.stoch_d(H, L, C, 14, 3), want_d, tol=1e-9)


def r_sma_none(xs, n):
    out = []
    for i in range(len(xs)):
        w = xs[i - n + 1:i + 1] if i >= n - 1 else []
        out.append(sum(w) / n if len(w) == n and all(x is not None for x in w) else None)
    return out


def test_flat_window_gives_neutral_values():
    assert np.all(ind.stoch_k(H, L, C, 14)[13:, FLAT] == 50.0)
    assert np.all(ind.cci(H, L, C, 20)[19:, FLAT] == 0.0)


def test_flat_window_puts_sma_and_both_bands_exactly_on_the_close():
    """Staging, 3 Nov: LIQUID / LIQUIDIETF sit at 999.99; SD 0 must give upper == lower == close with no float noise, so
    "close above the upper band" is false and "close >= the upper band" is true."""
    c = np.full((40, 3), 999.99)
    c[:15, 1] = np.linspace(900.0, 1000.0, 15)                       # moved, then flat at 999.99 from row 15
    c[:5, 2] = NAN
    c[5:, 2] = 0.1                                                   # 0.1 added 20 times is not exactly 2.0
    up, lo = ind.bollinger(c, 20, 2.0)
    s = ind.sma(c, 20)
    for j, first in ((0, 19), (1, 34), (2, 24)):
        assert np.array_equal(up[first:, j], c[first:, j]), j
        assert np.array_equal(lo[first:, j], c[first:, j]), j
        assert np.array_equal(s[first:, j], c[first:, j]), j
        assert not np.any(c[first:, j] > up[first:, j]) and np.all(c[first:, j] >= up[first:, j])
    assert ind.cci(c, c, c, 20)[39, 2] == 0.0                        # flat: no deviation, so CCI is 0, not noise
    assert up[33, 1] > c[33, 1]                                      # the last window that still holds a move is not flat
    assert np.array_equal(ind.sma(C, 1), C, equal_nan=True)          # SMA(1) is the value itself


def test_bollinger_matches_reference():
    up, lo = ind.bollinger(C, 20, 2.0)
    refs = [r_bollinger(_seg(C, j), 20, 2.0) for j in range(len(STARTS))]
    _close(up, [_place(r[0], j) for j, r in enumerate(refs)], tol=1e-9)
    _close(lo, [_place(r[1], j) for j, r in enumerate(refs)], tol=1e-9)


# ── TC-U8: too little history ───────────────────────────────────────────────────────────────────────────────────────

def test_too_little_history_is_nan_never_an_error():
    short = C[-5:, :]
    hs, ls = H[-5:, :], L[-5:, :]
    for got in (ind.sma(short, 20), ind.ema(short, 20), ind.rsi(short, 14), ind.atr(hs, ls, short, 14),
                ind.dmi(hs, ls, short, 14)[2], ind.cci(hs, ls, short, 20), ind.stoch_k(hs, ls, short, 14),
                ind.bollinger(short, 20, 2)[0], ind.supertrend(hs, ls, short, 7, 3), ind.rolling_max(short, 52),
                ind.macd(short, 26, 12, 9)[0]):
        assert got.shape == short.shape and np.isnan(got).all()
    empty = np.zeros((0, 3))
    assert ind.sma(empty, 5).shape == (0, 3) and ind.ema(empty, 5).shape == (0, 3)
    assert ind.psar(empty, empty, empty, 0.02, 0.02, 0.2).shape == (0, 3)


def test_a_stock_with_fewer_candles_than_the_period_is_nan():
    got = ind.sma(C, 20)
    j = STARTS.index(128)                            # 12 candles
    assert np.isnan(got[:, j]).all()


# ── Layout: compress and resample ───────────────────────────────────────────────────────────────────────────────────

def test_compress_right_aligns_each_stock_and_skips_its_gaps():
    nan = NAN
    c = np.array([[1, nan, nan], [2, 10, nan], [3, nan, nan], [4, 11, 20], [5, 12, nan]], dtype=float)
    o = c + 0.5
    out, counts = ind.compress({"close": c, "open": o})
    assert counts.tolist() == [5, 3, 1]
    np.testing.assert_array_equal(out["close"][:, 0], [1, 2, 3, 4, 5])
    np.testing.assert_array_equal(out["close"][:, 1], [nan, nan, 10, 11, 12])      # the gap on day 3 is skipped
    np.testing.assert_array_equal(out["open"][:, 1], [nan, nan, 10.5, 11.5, 12.5])
    np.testing.assert_array_equal(out["close"][:, 2], [nan, nan, nan, nan, 20])    # its latest candle is day 4
    out2, _ = ind.compress({"close": np.full((3, 2), nan)})
    assert out2["close"].shape == (0, 2)


def test_resample_weekly_and_monthly_by_hand():
    nan = NAN
    dates = np.array(["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30",   # Mon..Fri, week 1
                      "2026-11-02", "2026-11-03"], dtype="datetime64[D]")                    # Mon, Tue (provisional)
    o = np.array([[10, 50], [11, 51], [12, nan], [13, 53], [14, 54], [15, nan], [16, nan]], dtype=float)
    c = o + 1
    h = o + 3
    l = o - 2
    v = np.array([[1, 5], [2, 5], [3, nan], [4, 5], [5, 5], [6, nan], [7, nan]], dtype=float)
    l[2, 0] = 1.0                                     # week 1's low for stock 0
    pd_, po, ph, pl, pc, pv = ind.resample(dates, o, h, l, c, v, "1w")
    assert pd_.tolist() == np.array(["2026-10-26", "2026-11-02"], dtype="datetime64[D]").tolist()
    np.testing.assert_array_equal(po, [[10, 50], [15, nan]])
    np.testing.assert_array_equal(pc, [[15, 55], [17, nan]])                       # Friday's / Tuesday's close
    np.testing.assert_array_equal(ph, [[17, 57], [19, nan]])
    np.testing.assert_array_equal(pl, [[1, 48], [13, nan]])
    np.testing.assert_array_equal(pv, [[15, 20], [13, nan]])                       # stock 1 has no candle in week 2
    md, mo, mh, ml, mc, mv = ind.resample(dates, o, h, l, c, v, "1M")
    assert md.tolist() == np.array(["2026-10-01", "2026-11-01"], dtype="datetime64[D]").tolist()
    np.testing.assert_array_equal(mo, [[10, 50], [15, nan]])
    np.testing.assert_array_equal(mc, [[15, 55], [17, nan]])
    np.testing.assert_array_equal(mv, [[15, 20], [13, nan]])


def test_week_keys_run_monday_to_sunday():
    d = np.array(["2026-11-01", "2026-11-02", "2026-11-08", "2026-11-09"], dtype="datetime64[D]")   # Sun, Mon, Sun, Mon
    k = ind.period_keys(d, "1w")
    assert k[1] == k[2] and k[0] != k[1] and k[2] != k[3]
    assert k[1] == np.datetime64("2026-11-02", "D").astype(np.int64)
