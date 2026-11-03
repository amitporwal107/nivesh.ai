"""Scan Builder engine and scan validation (services/scan_builder/engine.py, spec.py).

TC-U9..TC-U16 of test_reports/scan_builder_20261103_0431.md, on small hand-built panels whose answers can be worked out by
hand: expressions read left to right, comparison operators and crosses, all/any groups with their universes, three-valued
logic (missing data is unknown, never a pass), weekly candles and offsets, fundamentals, sorting with missing values last,
and every validation bound with the JSON path it reports.
"""
from __future__ import annotations

import copy
import json

import numpy as np
import pytest

from services.scan_builder import engine as E
from services.scan_builder import spec as S

NAN = float("nan")
M, N_, F, X, flt, grp = S.measure, S.number, S.fundamental, S.expr, S.flt, S.group


def _dates(n: int, first: str = "2026-09-01") -> np.ndarray:
    """n weekdays from `first`."""
    d = np.arange(np.datetime64(first), np.datetime64(first) + 3 * n)
    return d[np.isin((d.astype(np.int64) + 3) % 7, [0, 1, 2, 3, 4])][:n]


def _panel(closes: dict, days: int | None = None) -> E.Panel:
    """Panel from {symbol: [close, ...]} (None = no candle); open = close, high = close + 1, low = close - 1, volume 1000."""
    syms = list(closes)
    t = days or max(len(v) for v in closes.values())
    c = np.full((t, len(syms)), NAN)
    for j, s in enumerate(syms):
        vals = closes[s]
        for i, x in enumerate(vals[-t:]):
            c[t - len(vals[-t:]) + i, j] = NAN if x is None else x
    return E.Panel(symbols=syms, dates=_dates(t), open=c.copy(), high=c + 1, low=c - 1, close=c.copy(),
                   volume=np.where(np.isnan(c), NAN, 1000.0))


def _scan(children, universe="cash", columns=None, sort=None, limit=50, join="all"):
    s = S.default_spec()
    s["filters"] = grp("root", children, join=join, universe=universe)
    if columns is not None:
        s["columns"] = columns
    if sort is not None:
        s["sort"] = sort
    s["limit"] = limit
    return S.validate(s)


def _all(n):
    return {"cash": np.ones(n, dtype=bool)}


def _run(spec, panel, **kw):
    kw.setdefault("universes", _all(len(panel.symbols)))
    return E.evaluate(spec, panel, **kw)


def _matched(res, panel):
    return [panel.symbols[i] for i in res["order"]]


# ── TC-U9: expressions left to right; division by zero ──────────────────────────────────────────────────────────────

def test_percent_change_column_reads_left_to_right():
    p = _panel({"AAA": [100, 110], "BBB": [200, 190], "CCC": [50, 50]})
    res = _run(_scan([]), p)
    by = {p.symbols[i]: v for i, v in zip(res["order"], res["values"])}
    assert by["AAA"][0] == pytest.approx(10.0) and by["BBB"][0] == pytest.approx(-5.0) and by["CCC"][0] == 0.0
    assert by["AAA"][1] == 110 and by["AAA"][2] == 1000
    assert _matched(res, p) == ["AAA", "CCC", "BBB"]                        # by % change, high to low
    assert [c["alias"] for c in res["columns"]] == ["% Change", "Price", "Volume"]


def test_arithmetic_has_no_precedence_and_x_over_zero_is_missing():
    p = _panel({"AAA": [10], "BBB": [0]})
    # 2 + close * 3 read left to right is (2 + close) * 3
    col = [{"id": "c1", "alias": "v", "format": "number", "expr": X(N_(2), "+", M("close"), "*", N_(3))},
           {"id": "c2", "alias": "w", "format": "number", "expr": X(N_(1), "/", M("close"))}]
    res = _run(_scan([], columns=col, sort={"column": "c1", "dir": "desc"}), p)
    by = {p.symbols[i]: v for i, v in zip(res["order"], res["values"])}
    assert by["AAA"] == [36.0, 0.1]
    assert by["BBB"] == [6.0, None]                                         # 1 / 0 is missing, not inf
    res2 = _run(_scan([flt("f", X(N_(1), "/", M("close")), "gt", X(N_(0)))]), p)
    assert _matched(res2, p) == ["AAA"] and res2["counts"]["no_history"] == 1


# ── TC-U10: operators and crosses ───────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("op,want", [("gt", ["CCC"]), ("gte", ["BBB", "CCC"]), ("lt", ["AAA"]), ("lte", ["AAA", "BBB"]),
                                     ("eq", ["BBB"])])
def test_comparison_operators(op, want):
    p = _panel({"AAA": [9], "BBB": [10], "CCC": [11]})
    res = _run(_scan([flt("f", X(M("close")), op, X(N_(10)))]), p)
    assert sorted(_matched(res, p)) == want


def test_crosses_above_and_below_at_offset_0_and_1():
    p = _panel({"UP": [8, 9, 11], "ALREADY": [11, 11, 12], "TOUCH": [9, 10, 11], "DOWN": [12, 11, 9], "OLDUP": [9, 11, 12]})
    above = _run(_scan([flt("f", X(M("close")), "crosses_above", X(N_(10)))]), p)
    assert sorted(_matched(above, p)) == ["TOUCH", "UP"]                    # 10 -> 11: was <= 10, now > 10
    below = _run(_scan([flt("f", X(M("close")), "crosses_below", X(N_(10)))]), p)
    assert _matched(below, p) == ["DOWN"]
    earlier = _run(_scan([flt("f", X(M("close", 1)), "crosses_above", X(N_(10)))]), p)   # the cross one candle ago
    assert _matched(earlier, p) == ["OLDUP"]


def test_crosses_need_the_previous_candle():
    p = _panel({"NEW": [None, None, 11], "OLD": [9, 9, 11]})
    res = _run(_scan([flt("f", X(M("close")), "crosses_above", X(N_(10)))]), p)
    assert _matched(res, p) == ["OLD"] and res["nodes"]["f"] == {"passed": 1, "unknown": 1}


# ── TC-U11 / TC-U12: groups, universes, disabled nodes, three-valued logic, node counts ─────────────────────────────

def test_all_any_nested_universe_disabled_and_empty_groups():
    p = _panel({"A": [5], "B": [15], "C": [25], "D": [35]})
    uni = {"cash": np.ones(4, bool), "nifty50": np.array([True, False, True, False])}
    any_group = grp("g1", [flt("lo", X(M("close")), "lt", X(N_(10))), flt("hi", X(M("close")), "gt", X(N_(30)))], join="any")
    res = _run(_scan([any_group]), p, universes=uni)
    assert sorted(_matched(res, p)) == ["A", "D"]
    in50 = grp("g2", [flt("x", X(M("close")), "gt", X(N_(0)))], universe="nifty50")
    res = _run(_scan([in50]), p, universes=uni)
    assert sorted(_matched(res, p)) == ["A", "C"]                           # a sub-group's universe narrows it
    off = flt("off", X(M("close")), "gt", X(N_(100)))
    off["enabled"] = False
    empty = grp("g3", [])
    res = _run(_scan([off, empty]), p, universes=uni)
    assert len(res["order"]) == 4 and "off" not in res["nodes"] and res["nodes"]["g3"]["passed"] == 4
    dis = grp("g4", [flt("never", X(M("close")), "gt", X(N_(100)))])
    dis["enabled"] = False
    res = _run(_scan([dis]), p, universes=uni)
    assert len(res["order"]) == 4 and "g4" not in res["nodes"]


def test_root_universe_and_eligibility_decide_who_is_evaluated():
    p = _panel({"A": [5], "B": [15], "C": [25]})
    uni = {"fno": np.array([True, True, False])}
    res = E.evaluate(_scan([], universe="fno"), p, universes=uni, eligible=np.array([True, False, True]))
    assert _matched(res, p) == ["A"] and res["counts"]["evaluated"] == 1


def test_missing_data_is_unknown_fail_beats_unknown_in_all_and_pass_beats_it_in_any():
    p = _panel({"LONG": list(range(1, 31)), "SHORT": [None] * 25 + [1, 2, 3, 4, 5]})
    sma20 = flt("s", X(M("close")), "gt", X(M("sma", source="close", period=20)))
    fail = flt("f", X(M("close")), "gt", X(N_(1000)))
    ok = flt("o", X(M("close")), "gt", X(N_(0)))
    res = _run(_scan([sma20]), p)
    assert _matched(res, p) == ["LONG"]
    assert res["nodes"]["s"] == {"passed": 1, "unknown": 1} and res["counts"]["no_history"] == 1
    res = _run(_scan([sma20, fail]), p)                                     # all: the failure decides SHORT
    assert res["order"] == [] and res["counts"]["no_history"] == 0 and res["nodes"]["root"] == {"passed": 0, "unknown": 0}
    res = _run(_scan([sma20, ok], join="any"), p)                           # any: the pass decides SHORT
    assert sorted(_matched(res, p)) == ["LONG", "SHORT"]
    res = _run(_scan([sma20, fail], join="any"), p)                         # any: unknown stays unknown
    assert _matched(res, p) == ["LONG"] and res["nodes"]["root"]["unknown"] == 1


def test_universe_not_loaded_is_an_error():
    p = _panel({"A": [1]})
    with pytest.raises(ValueError):
        E.evaluate(_scan([], universe="nifty50"), p, universes={"cash": np.ones(1, bool)})


# ── TC-U13: weekly / monthly candles and offsets ────────────────────────────────────────────────────────────────────

def test_weekly_and_monthly_measures_with_offsets():
    # 10 weekdays from Mon 2026-09-07 (two full weeks) + Mon 2026-09-21 as today's provisional candle.
    closes = [10, 11, 12, 13, 14, 20, 21, 22, 23, 24, 30]
    p = E.Panel(symbols=["W"], dates=_dates(11, "2026-09-07"), open=np.array(closes, float)[:, None],
                high=np.array(closes, float)[:, None] + 1, low=np.array(closes, float)[:, None] - 1,
                close=np.array(closes, float)[:, None], volume=np.full((11, 1), 100.0))
    cols = [{"id": "w0", "alias": "w0", "format": "number", "expr": X(M("close", 0, tf="1w"))},
            {"id": "w1", "alias": "w1", "format": "number", "expr": X(M("close", 1, tf="1w"))},
            {"id": "w2", "alias": "w2", "format": "number", "expr": X(M("close", 2, tf="1w"))},
            {"id": "wh", "alias": "wh", "format": "number", "expr": X(M("high", 1, tf="1w"))},
            {"id": "wv", "alias": "wv", "format": "number", "expr": X(M("volume", 1, tf="1w"))},
            {"id": "wmax", "alias": "wmax", "format": "number", "expr": X(M("max", tf="1w", source="close", period=2))},
            {"id": "mo", "alias": "mo", "format": "number", "expr": X(M("open", 0, tf="1M"))},
            {"id": "w3", "alias": "w3", "format": "number", "expr": X(M("close", 3, tf="1w"))}]
    res = _run(_scan([], columns=cols, sort={"column": "w0", "dir": "desc"}), p)
    assert res["values"] == [[30.0, 24.0, 14.0, 25.0, 500.0, 30.0, 10.0, None]]


# ── TC-U14: fundamentals ────────────────────────────────────────────────────────────────────────────────────────────

def test_fundamentals_ignore_offsets_and_missing_is_unknown():
    p = _panel({"A": [1], "B": [1], "C": [1]})
    f = {"market_cap_cr": np.array([20000.0, 500.0, NAN])}
    res = _run(_scan([flt("m", X(F("market_cap_cr")), "gt", X(N_(10000)))]), p, fundamentals=f)
    assert _matched(res, p) == ["A"] and res["nodes"]["m"] == {"passed": 1, "unknown": 1}
    res = _run(_scan([flt("m", X(F("pe_ttm")), "lt", X(N_(15)))]), p, fundamentals=f)    # field not loaded
    assert res["order"] == [] and res["counts"]["no_history"] == 3


# ── TC-U15: columns, sort, limit ────────────────────────────────────────────────────────────────────────────────────

def test_sort_ascending_descending_missing_last_ties_by_symbol_and_limit():
    p = _panel({"D": [1, 4], "B": [1, 2], "A": [1, 2], "C": [None, 3], "E": [1, 9]})
    chg = S.default_spec()["columns"][0]
    price = S.default_spec()["columns"][1]
    res = _run(_scan([], columns=[chg, price], sort={"column": "c_chg", "dir": "desc"}), p)
    assert _matched(res, p) == ["E", "D", "A", "B", "C"]                   # C has no previous close: missing, last
    res = _run(_scan([], columns=[chg, price], sort={"column": "c_chg", "dir": "asc"}), p)
    assert _matched(res, p) == ["A", "B", "D", "E", "C"]
    res = _run(_scan([], columns=[chg, price], sort={"column": "c_price", "dir": "asc"}, limit=2), p)
    assert _matched(res, p) == ["A", "B"] and res["counts"]["shown"] == 2 and res["counts"]["matched"] == 5


def test_disabled_column_is_hidden_but_can_still_sort():
    p = _panel({"A": [1, 2], "B": [1, 3]})
    cols = copy.deepcopy(S.default_spec()["columns"])
    cols[0]["enabled"] = False
    res = _run(_scan([], columns=cols, sort={"column": "c_chg", "dir": "desc"}), p)
    assert [c["id"] for c in res["columns"]] == ["c_price", "c_vol"] and _matched(res, p) == ["B", "A"]
    assert res["values"][0] == [3.0, 1000.0]


def test_output_has_no_nan_only_floats_or_none():
    p = _panel({"A": [1], "B": [None, 2]})
    res = _run(_scan([]), p)
    json.dumps(res["values"], allow_nan=False)


def test_templates_run_on_a_panel():
    rng = np.random.default_rng(3)
    t, n = 300, 12
    c = 100 * np.exp(np.cumsum(rng.normal(0.001, 0.02, (t, n)), axis=0))
    p = E.Panel(symbols=[f"S{j}" for j in range(n)], dates=_dates(t), open=c, high=c * 1.01, low=c * 0.99, close=c,
                volume=rng.integers(1000, 9000, (t, n)).astype(float))
    uni = {"cash": np.ones(n, bool), "fno": np.ones(n, bool)}
    for tpl in S.templates():
        res = E.evaluate(S.validate(tpl["spec"]), p, universes=uni, fundamentals={"market_cap_cr": np.full(n, 20000.0)})
        assert res["counts"]["evaluated"] == n
        assert set(res["nodes"]) >= {f["id"] for f in tpl["spec"]["filters"]["children"]}


# ── Windows: computing on each stock's last candles gives the full-history answer ───────────────────────────────────

_ALL_MEASURES = [
    ("close", {}), ("volume", {}), ("sma", {"source": "close", "period": 20}), ("ema", {"source": "close", "period": 50}),
    ("ema", {"source": "volume", "period": 10}), ("max", {"source": "high", "period": 52}),
    ("min", {"source": "low", "period": 30}), ("rsi", {"period": 14}), ("macd_line", {}), ("macd_signal", {}),
    ("macd_hist", {}), ("cci", {"period": 20}), ("stoch_k", {"period": 14}), ("stoch_d", {"period": 14, "smooth": 3}),
    ("adx", {"period": 14}), ("di_plus", {"period": 14}), ("di_minus", {"period": 14}), ("atr", {"period": 14}),
    ("supertrend", {"period": 7, "multiplier": 3}), ("supertrend", {"period": 10, "multiplier": 2}), ("psar", {}),
    ("bb_upper", {"period": 20, "dev": 2}), ("bb_lower", {"period": 20, "dev": 2}),
]


def _ragged_panel(t=600, n=40, seed=11):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.02, (t, n)), axis=0))
    o = c * (1 + rng.normal(0, 0.006, (t, n)))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.01, (t, n))))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.01, (t, n))))
    v = rng.integers(1_000, 1_000_000, (t, n)).astype(float)
    starts = rng.integers(0, 450, n)
    starts[:5] = 0
    for j, s in enumerate(starts):
        for a in (o, h, l, c, v):
            a[:s, j] = NAN
    for a in (o, h, l, c, v):                                               # a suspension: 15 days without candles
        a[300:315, 7] = NAN
    return E.Panel(symbols=[f"S{j:02d}" for j in range(n)], dates=_dates(t), open=o, high=h, low=l, close=c, volume=v)


@pytest.mark.parametrize("tf", ["1d", "1w", "1M"])
def test_windows_give_the_full_history_answer(tf):
    p = _ragged_panel()
    uni = _all(len(p.symbols))
    ms = [(m, prm) for m, prm in _ALL_MEASURES if tf == "1d" or m not in ("supertrend", "psar")]
    checked = 0
    for chunk in range(0, len(ms), 6):
        cols = []
        for i, (m, prm) in enumerate(ms[chunk:chunk + 6]):
            for off in (0, 3):
                cols.append({"id": f"c{i}_{off}", "alias": f"{m}{off}", "format": "number",
                             "expr": X(M(m, off, tf=tf, **prm))})
        spec = _scan([], columns=cols, sort={"column": cols[0]["id"], "dir": "desc"}, limit=500)
        fast = E.evaluate(spec, p, universes=uni)
        full = E.evaluate(spec, p, universes=uni, full_history=True)
        assert fast["order"] == full["order"]
        for rf, rw in zip(fast["values"], full["values"]):
            for a, b in zip(rf, rw):
                assert (a is None) == (b is None)
                if a is not None:
                    assert abs(a - b) <= 1e-6 * max(1.0, abs(b)), (a, b)
                    checked += 1
    assert checked > 100


def test_a_long_suspension_never_hides_a_stocks_own_previous_candles():
    """Regression (staging, 3 Nov): SYSTMTXC traded to 17 Jun, was suspended, and traded again on 2 Nov; its 1-month-ago
    close must be June's, not missing. Weekly / monthly candles come from the full daily history; only maths is windowed."""
    t = 600
    p = _ragged_panel(t=t, n=30, seed=5)
    sus, last_before = 3, t - 112                                           # stock 3 trades from row 0 ...
    for a in (p.open, p.high, p.low, p.close, p.volume):
        a[last_before + 1:t - 1, sus] = NAN                                 # ... then ~5 months without a candle, back today
    uni = _all(len(p.symbols))
    cols = []
    for tf in ("1w", "1M"):
        for off in (0, 1, 2):
            cols.append({"id": f"{tf}c{off}", "alias": f"{tf} close {off}", "format": "number",
                         "expr": X(M("close", off, tf=tf))})
    cols.append({"id": "mrsi", "alias": "1M rsi 3", "format": "number", "expr": X(M("rsi", tf="1M", period=3))})
    cols.append({"id": "wsma", "alias": "1w sma 4", "format": "number",
                 "expr": X(M("sma", 1, tf="1w", source="close", period=4))})
    filters = [flt("m01", X(M("close", tf="1M")), "gt", X(M("close", 1, tf="1M"))),
               flt("w12", X(M("close", 1, tf="1w")), "gt", X(M("close", 2, tf="1w"))),
               flt("m2", X(M("close", 2, tf="1M")), "gt", X(N_(0))),
               flt("mr", X(M("rsi", tf="1M", period=3)), "gt", X(N_(0))),
               flt("any", X(M("close")), "gt", X(N_(0)))]
    spec = _scan([grp("g", filters, join="any")], columns=cols, sort={"column": "1Mc0", "dir": "desc"}, limit=500)
    fast = E.evaluate(spec, p, universes=uni)
    full = E.evaluate(spec, p, universes=uni, full_history=True)
    assert fast["order"] == full["order"] and fast["nodes"] == full["nodes"] and fast["counts"] == full["counts"]
    for rf, rw in zip(fast["values"], full["values"]):
        for a, b in zip(rf, rw):
            assert (a is None) == (b is None) and (a is None or abs(a - b) <= 1e-9 * max(1.0, abs(b))), (a, b)
    row = fast["values"][fast["order"].index(sus)]
    assert row[1] == p.close[last_before, sus]                             # 1w close, 1 ago: its last week before
    assert row[4] == p.close[last_before, sus]                             # 1M close, 1 ago: its last month before
    assert row[5] is not None and row[6] is not None and row[7] is not None
    assert fast["nodes"]["m01"]["unknown"] == 0 and fast["nodes"]["m2"]["unknown"] == 0


def test_window_sizes_follow_the_definitions():
    assert E.need("sma", {"source": "close", "period": 20}) == 20
    assert E.need("rsi", {"period": 14}) == 1 + 14 + 280
    assert E.need("ema", {"source": "close", "period": 50}) == 50 + 519        # (49/51)^519 < 1e-9 <= (49/51)^518
    assert (49 / 51) ** 519 < E.CONVERGE_EPS <= (49 / 51) ** 518
    assert E.need("close", {}) == 1
    spec = _scan([flt("x", X(M("close")), "crosses_above", X(M("sma", 2, source="close", period=20)))])
    w = E.windows(spec)
    assert w[("1d", "sma", (("period", 20), ("source", "close")))] == 20 + 2 + 1 + 1    # need + offset + cross + 1
    assert w[("1d", "close", ())] == 3        # need 1, + offset 1 (the % change column) + 1; the cross reads offset 0 + 1 + 1


# ── TC-U16: validation ──────────────────────────────────────────────────────────────────────────────────────────────

def _bad(mutate):
    s = S.default_spec()
    s["filters"]["children"] = [flt("f1", X(M("rsi", period=14)), "gt", X(N_(50)))]
    mutate(s)
    with pytest.raises(S.SpecError) as e:
        S.validate(s)
    return e.value


@pytest.mark.parametrize("mutate,path", [
    (lambda s: s["filters"]["children"][0]["left"]["terms"][0]["operand"].update(measure="vwap"),
     "filters.children[0].left.terms[0].operand.measure"),
    (lambda s: s["filters"]["children"][0].update(op="between"), "filters.children[0].op"),
    (lambda s: s["filters"].update(universe="nasdaq"), "filters.universe"),
    (lambda s: s["filters"]["children"][0]["left"]["terms"][0]["operand"]["params"].update(period=500),
     "filters.children[0].left.terms[0].operand.params.period"),
    (lambda s: s["filters"]["children"][0]["left"]["terms"][0]["operand"]["params"].update(period=14.5),
     "filters.children[0].left.terms[0].operand.params.period"),
    (lambda s: s["filters"]["children"][0]["left"]["terms"][0]["operand"]["params"].update(length=14),
     "filters.children[0].left.terms[0].operand.params.length"),
    (lambda s: s["filters"]["children"][0]["left"]["terms"][0]["operand"].update(offset=251),
     "filters.children[0].left.terms[0].operand.offset"),
    (lambda s: s["filters"]["children"][0]["left"]["terms"][0]["operand"].update(tf="15m"),
     "filters.children[0].left.terms[0].operand.tf"),
    (lambda s: s["filters"]["children"][0]["left"]["terms"][0].update(op="+"), "filters.children[0].left.terms[0].op"),
    (lambda s: s["filters"]["children"][0]["right"]["terms"].append({"op": "^", "operand": N_(1)}),
     "filters.children[0].right.terms[1].op"),
    (lambda s: s["filters"]["children"][0]["right"]["terms"][0]["operand"].update(value=float("inf")), ""),
    (lambda s: s["filters"]["children"][0]["right"].update(terms=[{"op": None, "operand": N_(1)}] * 9),
     "filters.children[0].right.terms"),
    (lambda s: s["filters"]["children"][0].update(id="root"), "filters.children[0].id"),
    (lambda s: s["filters"]["children"][0].update(id="bad id!"), "filters.children[0].id"),
    (lambda s: s.update(sort={"column": "nope", "dir": "desc"}), "sort.column"),
    (lambda s: s.update(sort={"column": "c_chg", "dir": "up"}), "sort.dir"),
    (lambda s: s.update(limit=501), "limit"),
    (lambda s: s.update(limit=True), "limit"),
    (lambda s: s.update(name="  "), "name"),
    (lambda s: s.update(name="x" * 81), "name"),
    (lambda s: s.update(columns=[]), "columns"),
    (lambda s: s["columns"][0].update(format="money"), "columns[0].format"),
    (lambda s: s["columns"][0].update(alias=""), "columns[0].alias"),
    (lambda s: s["filters"]["children"][0].update(comment="c" * 201), "filters.children[0].comment"),
    (lambda s: s["filters"]["children"][0].update(enabled="yes"), "filters.children[0].enabled"),
    (lambda s: s["filters"]["children"][0]["left"]["terms"][0]["operand"].update(kind="formula"),
     "filters.children[0].left.terms[0].operand.kind"),
    (lambda s: s["filters"]["children"][0]["left"]["terms"][0].update(operand=F("pe")),
     "filters.children[0].left.terms[0].operand.field"),
    (lambda s: s["filters"]["children"][0]["left"]["terms"][0]["operand"]["params"].update(source="vwap"), ""),
    (lambda s: s.update(version=2), "version"),
])
def test_validation_points_at_the_first_problem(mutate, path):
    err = _bad(mutate)
    assert err.code == "invalid_spec" and err.message
    if path:
        assert err.path == path, err.message


def test_validation_bounds_depth_filter_count_children_and_size():
    s = S.default_spec()
    g = s["filters"]
    for d in range(4):                                                      # root + 4 nested = 5 deep
        child = grp(f"g{d}", [])
        g["children"].append(child)
        g = child
    with pytest.raises(S.SpecError) as e:
        S.validate(s)
    assert e.value.path == "filters.children[0].children[0].children[0].children[0]"
    s = S.default_spec()
    s["filters"]["children"] = [grp(f"g{i}", [flt(f"f{i}_{k}", X(M("close")), "gt", X(N_(1))) for k in range(5)])
                                for i in range(9)]                          # 45 filters
    with pytest.raises(S.SpecError) as e:
        S.validate(s)
    assert "40" in e.value.message
    s = S.default_spec()
    s["filters"]["children"] = [flt(f"f{i}", X(M("close")), "gt", X(N_(1))) for i in range(31)]
    with pytest.raises(S.SpecError) as e:
        S.validate(s)
    assert e.value.path == "filters.children"
    s = S.default_spec()
    s["description"] = "x" * 70_000
    with pytest.raises(S.SpecError) as e:
        S.validate(s)
    assert "bytes" in e.value.message
    with pytest.raises(S.SpecError):
        S.validate([1, 2])


def test_validate_fills_defaults_and_drops_unknown_keys():
    raw = {"name": " My scan ", "filters": {"id": "root", "universe": "fno", "children": [
        {"id": "a", "kind": "filter", "op": "gt", "extra": 1,
         "left": {"terms": [{"operand": {"kind": "measure", "measure": "ema"}}]},
         "right": {"terms": [{"operand": {"kind": "number", "value": 5}}]}}]},
        "columns": [{"id": "c", "alias": "Close", "expr": {"terms": [{"operand": {"kind": "measure", "measure": "close"}}]}}]}
    out = S.validate(raw)
    f = out["filters"]["children"][0]
    assert out["name"] == "My scan" and out["version"] == 1 and out["limit"] == 50 and out["description"] == ""
    assert out["sort"] == {"column": "c", "dir": "desc"} and out["columns"][0]["format"] == "number"
    assert f["enabled"] is True and f["comment"] == "" and "extra" not in f
    assert f["left"]["terms"][0] == {"op": None, "operand": {"kind": "measure", "tf": "1d", "offset": 0, "measure": "ema",
                                                            "params": {"source": "close", "period": 20}}}
    assert out["filters"]["join"] == "all"
    assert raw["filters"]["children"][0]["extra"] == 1                     # the input is not modified


def test_catalog_default_spec_templates_and_readers():
    cat = S.catalog()
    assert [u["key"] for u in cat["universes"]] == list(S.UNIVERSES)
    assert len(cat["fundamentals"]) == 19 and len(cat["operators"]) == 7
    tfs = {t["key"]: t for t in cat["timeframes"]}
    assert all(tfs[k]["available"] for k in ("1d", "1w", "1M"))
    assert all(not tfs[k]["available"] and tfs[k]["reason"] for k in ("5m", "15m", "1h"))
    assert S.validate(cat["default_spec"]) == cat["default_spec"]
    assert len(cat["templates"]) == 3
    for t in cat["templates"]:
        assert S.validate(t["spec"]) == t["spec"]
    spec = S.validate(cat["templates"][0]["spec"])
    assert S.universes_in(spec) == {"cash"} and S.fundamentals_in(spec) == {"market_cap_cr"}
    words = json.dumps(cat).lower()
    for banned in ("buy", "sell", "target", "stop loss", "picks"):
        assert banned not in words, banned
