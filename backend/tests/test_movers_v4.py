"""Top Movers v4 — pure-function and route-wiring tests for the movers logic (TC-V01..V04, V09, V20 in
test_reports/TESTCASES_movers_v4.md), which lives in the DaaS router nidp/services/daas_api/routers/movers.py.
No database, no app: the pg pool and the internal-plan dependency are stubbed in sys.modules for the import only,
so these tests prove the maths and the routing, not auth or data. The app-side proxy is tested in test_movers_proxy.py."""
import importlib.util
import re
import sys
import types
from pathlib import Path

import pytest

MOVERS_PATH = Path(__file__).resolve().parent.parent / "nidp" / "services" / "daas_api" / "routers" / "movers.py"
COST = 0.00628


@pytest.fixture(scope="module")
def mv():
    """Import the DaaS movers router with its two nidp imports stubbed. MOCK — not real data: the stubs exist only
    so the module can load; nothing here exercises auth or a database."""
    mp = pytest.MonkeyPatch()

    def _mod(name):
        m = types.ModuleType(name)
        mp.setitem(sys.modules, name, m)
        return m

    for pkg in ("nidp", "nidp.shared", "nidp.shared.storage", "nidp.services", "nidp.services.daas_api",
                "nidp.services.daas_api.routers"):
        _mod(pkg)
    pg = _mod("nidp.shared.storage.pg")
    sys.modules["nidp.shared.storage"].pg = pg
    mo = _mod("nidp.services.daas_api.routers.move_odds")
    mo.require_internal_plan = lambda: None
    spec = importlib.util.spec_from_file_location("movers_v4_under_test", MOVERS_PATH)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        yield mod
    finally:
        mp.undo()


def bar(o, h, l, c, prev_c=None, t="d"):
    return {"t": t, "o": o, "h": h, "l": l, "c": c, "v": 1000, "prev_c": prev_c}


def flat(n, px=100.0):
    return [bar(px, px, px, px, px, t=f"d{k}") for k in range(n)]


def with_next(**nb):
    """bars: [0]=prev 100, [1]=event day 100 (i=1), [2]=next session built from nb, then padding."""
    base = flat(2)
    return base, nb


# ── 1. identity ─────────────────────────────────────────────────────────────
def test_exec_identity_matches_design_formulas(mv):
    bars = flat(2) + [bar(102.0, 103.0, 101.0, 104.0, 100.0)]
    r = mv._exec_of(bars, 1, 3)
    assert r["gap"] == pytest.approx(102.0 / 100.0 - 1, abs=1e-12)
    assert r["intra"] == pytest.approx(104.0 / 102.0 - 1, abs=1e-12)
    assert r["re"] == pytest.approx(104.0 / 100.0 - 1, abs=1e-12)
    assert r["net"] == pytest.approx(r["intra"] - COST, abs=1e-12)
    assert mv.COST == COST


def test_exec_net_is_derived_from_intra_not_stored(mv):
    """net must track intra whatever intra is; if it were stored separately it could drift."""
    for nc in (95.0, 100.0, 108.0):
        r = mv._exec_of(flat(2) + [bar(100.0, 100.0, 100.0, nc, 100.0)], 1, 3)
        assert r["net"] == pytest.approx(r["intra"] - mv.COST, abs=1e-12), f"net != intra - COST at close {nc}"
    # monkeypatching COST must move net, proving it is computed at call time
    old = mv.COST
    try:
        mv.COST = 0.01
        r = mv._exec_of(flat(2) + [bar(100.0, 100.0, 100.0, 103.0, 100.0)], 1, 3)
        assert r["net"] == pytest.approx(0.03 - 0.01, abs=1e-12)
    finally:
        mv.COST = old


# ── 2. outcome states ───────────────────────────────────────────────────────
def _scenario(nb_bar, extra=0, i=1):
    """Event day i, next bar nb_bar (open 100), then `extra` flat bars at 100."""
    return flat(2) + [nb_bar] + flat(extra)


def test_outcome_up(mv):
    bars = _scenario(bar(100.0, 105.0, 99.0, 101.0, 100.0), extra=3)
    assert mv._exec_of(bars, 1, 3)["out"] == "UP"


def test_outcome_down(mv):
    bars = _scenario(bar(100.0, 101.0, 95.0, 99.0, 100.0), extra=3)
    assert mv._exec_of(bars, 1, 3)["out"] == "DOWN"


def test_outcome_both(mv):
    bars = _scenario(bar(100.0, 106.0, 94.0, 100.0, 100.0), extra=3)
    assert mv._exec_of(bars, 1, 3)["out"] == "BOTH"


def test_outcome_none_when_window_fully_observed(mv):
    bars = _scenario(bar(100.0, 102.0, 98.0, 101.0, 100.0), extra=3)  # i+H = 4 <= n = 5
    r = mv._exec_of(bars, 1, 3)
    assert r["out"] == "NONE"


def test_pending_not_none_when_horizon_runs_past_bars(mv):
    """Quiet window, but H=3 from i=1 needs bars up to index 4 and only index 2 exists. Calling that NONE
    would claim 'reached neither' for days that have not happened, which flatters the model."""
    bars = _scenario(bar(100.0, 102.0, 98.0, 101.0, 100.0), extra=0)  # n = 2, i + H = 4 > 2
    r = mv._exec_of(bars, 1, 3)
    assert r["out"] == "PENDING", "unobserved horizon was reported as NONE (conflates PENDING with NONE)"
    assert r["out"] != "NONE"


def test_pending_when_no_next_session_returns_no_figures(mv):
    r = mv._exec_of(flat(2), 1, 3)
    assert r["out"] == "PENDING"
    assert r["gap"] is r["intra"] is r["re"] is r["net"] is None


def test_up_already_hit_inside_partial_window_is_up_not_pending(mv):
    """A hit is a hit even if the window is still open."""
    bars = _scenario(bar(100.0, 106.0, 99.0, 101.0, 100.0), extra=0)
    assert mv._exec_of(bars, 1, 3)["out"] == "UP"


def test_none_carries_real_returns_not_zeros(mv):
    bars = _scenario(bar(101.0, 102.0, 100.0, 100.5, 100.0), extra=3)
    r = mv._exec_of(bars, 1, 3)
    assert r["out"] == "NONE"
    for k in ("gap", "intra", "re", "net"):
        assert r[k] is not None, f"{k} missing on a NONE outcome"
    assert r["gap"] == pytest.approx(0.01, abs=1e-12)
    assert r["intra"] == pytest.approx(100.5 / 101.0 - 1, abs=1e-12)
    assert r["re"] == pytest.approx(0.005, abs=1e-12)
    assert r["net"] == pytest.approx(r["intra"] - COST, abs=1e-12)
    assert r["intra"] != 0.0 and r["gap"] != 0.0, "NONE masquerading as a 0% return"


# ── 3. horizon ──────────────────────────────────────────────────────────────
def test_move_on_day_8_is_none_at_h3_and_up_at_h20(mv):
    # i=1, next session idx 2 (open 100), quiet until idx 9 (= i + 8) which spikes +6%, then padding to 25 bars.
    bars = flat(2) + [bar(100.0, 101.0, 99.0, 100.0, 100.0)]
    bars += [bar(100.0, 101.0, 99.0, 100.0, 100.0) for _ in range(6)]       # idx 3..8
    bars += [bar(100.0, 106.0, 99.0, 105.0, 100.0)]                          # idx 9 = i + 8
    bars += flat(20)                                                         # idx 10..29, so H=20 is fully observed
    assert mv._exec_of(bars, 1, 3)["out"] == "NONE"
    assert mv._exec_of(bars, 1, 20)["out"] == "UP"
    assert mv._exec_of(bars, 1, 3)["H"] == 3 and mv._exec_of(bars, 1, 20)["H"] == 20


# ── 4. _head_hit ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("head,h,l,expected", [
    ("p_up5_1d", 105.0, 100.0, True), ("p_up5_1d", 104.99, 100.0, False),
    ("p_up10_1d", 110.01, 100.0, True), ("p_up10_1d", 109.0, 100.0, False),
    ("p_down5_1d", 100.0, 95.0, True), ("p_down5_1d", 100.0, 95.01, False),
    ("p_down10_1d", 100.0, 90.0, True), ("p_down10_1d", 100.0, 91.0, False),
])
def test_head_hit_threshold_and_side(mv, head, h, l, expected):
    assert mv._head_hit(bar(100.0, h, l, 100.0, 100.0), head) is expected


def test_head_hit_uses_the_right_side(mv):
    spike_up = bar(100.0, 112.0, 100.0, 110.0, 100.0)
    spike_dn = bar(100.0, 100.0, 88.0, 90.0, 100.0)
    assert mv._head_hit(spike_up, "p_down5_1d") is False and mv._head_hit(spike_up, "p_up10_1d") is True
    assert mv._head_hit(spike_dn, "p_up5_1d") is False and mv._head_hit(spike_dn, "p_down10_1d") is True


def test_head_hit_missing_prev_close_is_withheld(mv):
    for pc in (None, 0):
        assert mv._head_hit(bar(100.0, 110.0, 90.0, 100.0, pc), "p_up5_1d") is None, f"guessed with prev_c={pc!r}"


def test_head_hit_and_exec_outcome_answer_different_questions(mv):
    """Day i=2 closes at 100 with prev_c 100. High is only +2% that day, so p_up5_1d's own event did NOT happen.
    The next open is 100 and the following bar reaches +6% from THAT open, so execOf says UP. Same bars, two
    answers: that is why calibration scores with _head_hit."""
    bars = flat(2) + [bar(100.0, 102.0, 99.0, 100.0, 100.0)] + [bar(100.0, 106.0, 99.0, 101.0, 100.0)] + flat(3)
    assert mv._head_hit(bars[2], "p_up5_1d") is False
    assert mv._exec_of(bars, 2, 3)["out"] == "UP"
    assert (mv._head_hit(bars[2], "p_up5_1d") is True) != (mv._exec_of(bars, 2, 3)["out"] in ("UP", "BOTH"))


# ── 5. _leak ────────────────────────────────────────────────────────────────
def _leak_bars(a, b, c, prev_c, n=8):
    """i = 7. bars[1] = a (i-6), bars[6] = b (i-1), event bar close c vs prev_c."""
    bars = flat(n)
    bars[1] = bar(a, a, a, a, a)
    bars[6] = bar(b, b, b, b, b)
    bars[7] = bar(c, c, c, c, prev_c)
    return bars


def test_leak_fires_when_drift_and_move_agree_up(mv):
    assert mv._leak(_leak_bars(100.0, 102.0, 105.0, 102.0), 7) is True      # +2% drift, +2.9% move


def test_leak_fires_when_drift_and_move_agree_down(mv):
    assert mv._leak(_leak_bars(100.0, 98.0, 95.0, 98.0), 7) is True


def test_leak_silent_when_drift_below_threshold(mv):
    assert mv._leak(_leak_bars(100.0, 101.0, 105.0, 101.0), 7) is False     # +1% < 1.5%


def test_leak_silent_when_drift_opposes_move(mv):
    assert mv._leak(_leak_bars(100.0, 102.0, 95.0, 102.0), 7) is False      # drifted up, fell on the day


def test_leak_silent_on_short_series(mv):
    bars = _leak_bars(100.0, 102.0, 105.0, 102.0)
    assert mv._leak(bars, 5) is False, "i=5 has no i-6 bar"
    assert mv._leak(bars, 3) is False
    assert mv._leak(bars, len(bars)) is False


# ── 6. _verdict ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("lift,expected", [
    (2.0, "SURVIVES"), (1.5, "SURVIVES"), (1.4999, "WEAK"), (1.25, "WEAK"), (1.2499, "DECORATION"), (0.5, "DECORATION"),
])
def test_verdict_thresholds(mv, lift, expected):
    assert mv._verdict(lift, "gap2") == expected


def test_verdict_leak_maps_to_pre_priced(mv):
    assert mv._verdict(2.0, "leak") == "PRE-PRICED"
    assert mv._verdict(1.3, "leak") == "WEAK" and mv._verdict(1.0, "leak") == "DECORATION"


def test_verdict_none_in_none_out(mv):
    for key in ("gap2", "leak", "d1"):
        assert mv._verdict(None, key) is None, f"defaulted a verdict for an uncomputable lift ({key})"


# ── 7. _atr_pct ─────────────────────────────────────────────────────────────
def test_atr_none_without_history(mv):
    assert mv._atr_pct(flat(1), 0) is None


def test_atr_none_when_ranges_missing_rather_than_a_small_number(mv):
    bars = flat(6)
    for b in bars:
        b["h"] = b["l"] = None
    assert mv._atr_pct(bars, 5) is None


def test_atr_value_is_real_when_history_exists(mv):
    bars = [bar(100.0, 102.0, 98.0, 100.0, 100.0) for _ in range(20)]
    assert mv._atr_pct(bars, 19) == pytest.approx(0.04, abs=1e-12)


# ── 8. route order ──────────────────────────────────────────────────────────
def test_analytics_routes_registered_before_symbol_catchall(mv):
    paths = [r.path for r in mv.router.routes]
    sym = "/movers/{symbol}"
    assert sym in paths, f"{sym} not registered; routes: {paths}"
    for p in ("/movers/calibration", "/movers/flag-lift", "/movers/flagged"):
        assert p in paths, f"{p} is not registered; routes: {paths}"
        assert paths.index(p) < paths.index(sym), (
            f"{p} is registered AFTER {sym}: GET {p} would resolve as a stock named "
            f"{p.rsplit('/', 1)[1].upper()!r} and the analytics endpoints are dead. Register fixed paths first.")
        route = mv.router.routes[paths.index(p)]
        assert route.path_regex.match(p), f"{p} does not resolve to itself"
        first = next(r for r in mv.router.routes if r.path_regex.match(p))
        assert first.path == p, f"GET {p} resolves to {first.path} (first match), not itself: shadowed by a catch-all"


# ── 9. no synthetic constants ───────────────────────────────────────────────
V4_SAMPLE_LIFTS = ("2.1", "1.3", "2.6", "1.4", "2.4", "1.05", "2.9", "1.1", "1.2", "0.95", "2.2", "1.8",
                   "4.4", "4.0", "1.6", "1.15")


def test_no_v4_sample_lift_constants_assigned():
    src = MOVERS_PATH.read_text()
    code = "\n".join(re.sub(r"(?<!['\"])#.*$", "", ln) for ln in src.splitlines())  # ignore comments
    hits = []
    for v in V4_SAMPLE_LIFTS:
        num = re.escape(v)
        # assigned: `x = 2.1`, `"un": 2.1`, `un=2.1`, `(…, 2.1)` after a key, or `un:2.1`
        # (?<![<>=!]) so a COMPARISON like `ratio >= 1.6` is not read as an assignment.
        if re.search(rf"(?<![<>=!])(?:=|:)\s*{num}(?![\d.])", code):
            hits.append(v)
    assert not hits, f"v4 SAMPLE lift values appear as assigned constants in the DaaS movers router: {hits}. " \
                     f"Shipping them presents mock data as real; compute from nidp instead."
    for key in ("'un'", '"un"', "'in':", "liftAt", "LIFT ="):
        assert key not in code, f"v4 sample-table marker {key!r} present in the DaaS movers router"


# ── 10. event indices are relative to the plotted slice (live bug: markers at 234.. on a 10-bar chart) ──
def _bars_on(dates):
    return [{"t": d} for d in dates]


def test_chart_index_is_relative_to_the_plotted_slice(mv):
    from datetime import date
    bars = _bars_on([f"2026-08-{d:02d}" for d in range(1, 29)] + [f"2026-09-{d:02d}" for d in (1, 2, 3, 4, 5, 8, 9, 10)])
    lo, hi = mv._chart_span(bars, date(2026, 9, 2), date(2026, 9, 9))
    assert (lo, hi) == (29, 34)
    assert bars[lo]["t"] == "2026-09-02" and bars[hi]["t"] == "2026-09-09"
    assert mv._chart_index(29, lo, hi) == 0          # first plotted candle
    assert mv._chart_index(34, lo, hi) == 5          # last plotted candle
    assert mv._chart_index(28, lo, hi) is None       # before the window: not plotted
    assert mv._chart_index(35, lo, hi) is None       # after the window
    assert mv._chart_index(None, lo, hi) is None


def test_chart_span_handles_a_window_edge_that_is_not_a_session(mv):
    from datetime import date
    bars = _bars_on(["2026-09-04", "2026-09-07", "2026-09-08", "2026-09-09"])   # 5-6 Sep is a weekend
    assert mv._chart_span(bars, date(2026, 9, 5), date(2026, 9, 8)) == (1, 2)    # edge on a non-session
    assert mv._chart_span(bars, date(2026, 10, 1), date(2026, 10, 9)) == (None, None)
    assert mv._chart_index(1, None, None) is None


# ── v5: technical state, round trips ─────────────────────────────────────────────────────────────────────
def _synth(n=120, drift=0.004, vol=1000):
    """MOCK — synthetic bars for arithmetic checks only: a steady uptrend with a constant range."""
    bars, c = [], 100.0
    for k in range(n):
        o, c = c, c * (1 + drift)
        bars.append({"t": f"2026-01-{(k % 28) + 1:02d}", "o": o, "h": c * 1.01, "l": o * 0.99, "c": c, "prev_c": o, "v": vol + k})
    return bars


def test_tech_series_warmup_is_none_not_zero(mv):
    ts = mv._tech_series(_synth())
    assert ts["ema20"][19] is None and ts["ema20"][20] is not None
    assert ts["ema50"][49] is None and ts["ema50"][50] is not None
    assert ts["adx"][27] is None and ts["adx"][28] is not None


def test_tech_uptrend_scores_bullish_and_rsi_saturates(mv):
    bars = _synth()
    ts = mv._tech_series(bars)
    mk = [100.0 * (1 + 0.001) ** k for k in range(len(bars))]
    t = mv._tech_at(bars, ts, mk, [None] * len(bars), 100)
    assert t["score"] >= 7 and t["rsi"] > 95
    # a steady drift beats a flatter index, so relative strength passes; RVOL ~1 does not
    pts = {p["k"]: p["on"] for p in t["pts"]}
    assert pts["20D RS > NIFTY"] is True and pts["RVOL20 > 1.5"] is False
    assert len(t["families"]) == 6


def test_tech_needs_history_and_missing_index_is_not_counted(mv):
    bars = _synth()
    ts = mv._tech_series(bars)
    assert mv._tech_at(bars, ts, [None] * len(bars), [None] * len(bars), 30) is None
    t = mv._tech_at(bars, ts, [None] * len(bars), [None] * len(bars), 100)
    assert {p["k"]: p["on"] for p in t["pts"]}["20D RS > NIFTY"] is None
    assert t["max"] == 9                      # an unevaluable point leaves the denominator, it is not a failure


def test_delivery_row_unevaluable_without_feed(mv):
    bars = _synth()
    ts = mv._tech_series(bars)
    t = mv._tech_at(bars, ts, [None] * len(bars), [None] * len(bars), 100)
    row = next(r for f in t["families"] for r in f["rows"] if r["k"].startswith("DELIVERY"))
    assert row["on"] is None and "NOT IN THE DELIVERY FEED" in row["v"]
    dl = [40.0] * 80 + [60.0] * 20 + [90.0] + [60.0] * 19
    t2 = mv._tech_at(bars, ts, [None] * len(bars), dl, 100)
    row2 = next(r for f in t2["families"] for r in f["rows"] if r["k"].startswith("DELIVERY"))
    assert row2["on"] is True and row2["v"] == "90% / 60%"


def test_round_trip_flag_window_and_bucket(mv):
    on = mv._rt_on([{"b": 3, "s": 6}], 20)
    assert [k for k, v in enumerate(on) if v] == [6, 7, 8, 9, 10]      # sell day + 4 more = 5 sessions
    assert [mv._tech_bucket(s) for s in (0, 2, 3, 4, 5, 6, 7, 8, 9, 10)] == ["WEAK", "WEAK", "MODERATE", "MODERATE", "STRONG", "STRONG", "VERY STRONG", "VERY STRONG", "EXTREME", "EXTREME"]


def test_inr_indian_grouping(mv):
    assert mv._inr(1234567.891) == "12,34,567.89" and mv._inr(-950.5) == "-950.50" and mv._inr(99.5) == "99.50"


class _FakeConn:
    def __init__(self, rows):
        self.rows = rows

    async def fetch(self, *a, **k):
        return self.rows


def test_round_trips_pairs_same_client_within_five_sessions(mv):
    import asyncio
    from datetime import date
    bars = [{"t": f"2026-09-{d:02d}"} for d in range(1, 15)]
    D = lambda d, c, s, q: {"as_of_date": date(2026, 9, d), "client_name": c, "deal_type": s, "quantity": q}
    rows = [D(2, "alpha fincap", "BUY", 10), D(5, "alpha fincap", "SELL", 10),     # 3 sessions -> round trip
            D(2, "beta", "BUY", 5), D(12, "beta", "SELL", 5),                       # 10 sessions -> not one
            D(8, "gamma", "SELL", 7), D(9, "gamma", "BUY", 7),                      # sell first -> not one
            D(6, "delta", "BUY", 1), D(6, "delta", "SELL", 1),                      # same day -> not one
            D(7, "", "BUY", 1), D(8, "", "SELL", 1)]                                # no client name -> ignored
    out = asyncio.run(mv._round_trips(_FakeConn(rows), "X", bars))
    assert len(out) == 1 and out[0]["cp"] == "Alpha Fincap" and out[0]["days"] == 3 and (out[0]["b"], out[0]["s"]) == (1, 4)


# ── forward lists: official run beside a labelled preview ────────────────────────────────────────────────────
class _FwdConn:
    """MOCK — canned rows keyed by what the query reads; records every SQL so the test can prove what was (not) touched."""
    def __init__(self):
        self.sql = []

    async def fetchval(self, q, *a):
        self.sql.append(q)
        from datetime import date
        return date(2026, 10, 5)

    async def fetchrow(self, q, *a):
        self.sql.append(q)
        from datetime import date, datetime
        if "FROM nidp.tpd_runs" in q:
            return {"run_id": 13, "model": "v4", "data_as_of": date(2026, 10, 1), "target_session": date(2026, 10, 5), "frozen_at": datetime(2026, 10, 1), "input_count": 1000, "counts_toward_verdict": True}
        return {"preview_id": 1, "label": "NEW-UNIVERSE PREVIEW", "data_as_of": date(2026, 10, 1), "git_sha": "2ef4ecb8052c", "universe_size": 1449, "scored": 3, "note": "n", "created_at": None}

    async def fetch(self, q, key=None):
        self.sql.append(q)
        if "sector_master" in q or "company_name" in q.lower() and "tpd_run_estimates" not in q and "tpd_preview" not in q:
            return []
        R = lambda s, h, p: {"symbol": s, "head": h, "p": p}
        if "tpd_run_estimates" in q:
            return [R("AAA", "p_up5_1d", .3), R("AAA", "p_down5_1d", .2), R("BBB", "p_up5_1d", .1), R("BBB", "p_down5_1d", .1)]
        return [R("AAA", "p_up5_1d", .35), R("AAA", "p_down5_1d", .25), R("NEWCO", "p_up5_1d", .4), R("NEWCO", "p_down5_1d", .4), R("ONLYUP", "p_up5_1d", .9)]


class _Acq:
    def __init__(self, c): self.c = c
    async def __aenter__(self): return self.c
    async def __aexit__(self, *a): return False


def test_forward_list_beside_preview_never_counted(mv, monkeypatch):
    import asyncio
    conn = _FwdConn()
    pool = types.SimpleNamespace(acquire=lambda: _Acq(conn))

    async def _pool():
        return pool
    async def _names(c, syms):
        return {s: f"{s} Ltd" for s in syms}
    monkeypatch.setattr(mv, "_pool", _pool)
    monkeypatch.setattr(mv, "_names", _names)
    mv._CACHE.clear() if hasattr(mv, "_CACHE") else None
    r = asyncio.run(mv.forward_list(request=None, session=None, limit=10))
    assert r["session"] == "2026-10-05"                                  # default = newest session on record
    assert r["official"]["run_id"] == 13 and [x["symbol"] for x in r["official"]["rows"]] == ["AAA", "BBB"]
    pv = r["preview"]
    assert pv["graded"] is False and pv["counts_toward_verdict"] is False and pv["git_sha"] == "2ef4ecb8"
    # either = up + down; a name with only one head has no 'either' and is not ranked
    assert [x["symbol"] for x in pv["rows"]] == ["NEWCO", "AAA"] and abs(pv["rows"][0]["either"] - 0.8) < 1e-9
    assert {x["symbol"]: x["in_official_universe"] for x in pv["rows"]} == {"NEWCO": False, "AAA": True}
    assert pv["top_overlap"] == 1 and "recommend" not in r["disclaimer"].lower()
    # the preview is read from its own tables; nothing writes anywhere
    assert not any(w in q.upper() for q in conn.sql for w in ("INSERT", "UPDATE", "DELETE"))
    assert any("tpd_preview_estimates" in q for q in conn.sql)


def test_forward_route_registered_before_symbol(mv):
    paths = [r.path for r in mv.router.routes]
    assert "/movers/forward" in paths and paths.index("/movers/forward") < paths.index("/movers/{symbol}")


def test_candidates_route_registered_before_symbol(mv):
    paths = [r.path for r in mv.router.routes]
    assert "/movers/candidates" in paths and paths.index("/movers/candidates") < paths.index("/movers/{symbol}")


# ── candidates: material filing or bulk/block deal, no price-move filter, no odds-model score ───────────────
class _CandConn:
    """MOCK — canned rows keyed by what the query reads; records every SQL so the test can prove what was (not)
    touched. Mirrors _FwdConn's idiom for the sibling /forward endpoint."""
    def __init__(self, session, anns=None, deals=None, prices=None):
        self.sql = []
        self._session = session
        self._anns = anns or []
        self._deals = deals or []
        self._prices = prices or []

    async def fetchval(self, q, *a):
        self.sql.append(q)
        return self._session

    async def fetch(self, q, *a):
        self.sql.append(q)
        if "corporate_announcements" in q:
            return self._anns
        if "bulk_deals" in q:
            return self._deals
        if "nidp.prices_eod" in q:
            return self._prices
        return []


def test_candidates_merges_signals_and_ranks_by_deal_value(mv, monkeypatch):
    import asyncio
    from datetime import date
    anns = [
        {"symbol": "AAA", "announcement_id": 1, "subject": "AAA bags new order worth 500cr",
         "description": "Order from a US client", "event_category": "orders"},
        {"symbol": "BBB", "announcement_id": 2, "subject": "BBB board meeting",
         "description": "Approves results", "event_category": "earnings"},
    ]
    deals = [
        {"src": "BULK", "symbol": "AAA", "client_name": "big fund", "deal_type": "BUY", "quantity": 10000, "avg_price": 150.0},
        {"src": "BLOCK", "symbol": "CCC", "client_name": "promoter trust", "deal_type": "SELL", "quantity": 500000, "avg_price": 20.0},
    ]
    prices = [
        {"symbol": "AAA", "close_price": 152.0, "prev_close": 148.0, "turnover": 6e6},
        {"symbol": "BBB", "close_price": 80.0, "prev_close": 80.5, "turnover": 6e6},
        {"symbol": "CCC", "close_price": 21.0, "prev_close": 20.0, "turnover": 6e6},
    ]
    conn = _CandConn(date(2026, 10, 2), anns=anns, deals=deals, prices=prices)
    pool = types.SimpleNamespace(acquire=lambda: _Acq(conn))

    async def _pool():
        return pool
    async def _names(c, syms):
        return {s: f"{s} Ltd" for s in syms}
    monkeypatch.setattr(mv, "_pool", _pool)
    monkeypatch.setattr(mv, "_names", _names)
    mv._cache.clear()

    r = asyncio.run(mv.candidates(request=None, session=None, limit=40))
    assert r["session"] == "2026-10-02"
    syms = [c["symbol"] for c in r["candidates"]]
    # CCC's deal value (5,00,000 x 20 = 1,00,00,000) outranks AAA's (10,000 x 150 = 15,00,000) outranks
    # BBB, which has no deal at all (filing-only names rank last on this axis).
    assert syms == ["CCC", "AAA", "BBB"]
    aaa = r["candidates"][syms.index("AAA")]
    assert {s["type"] for s in aaa["signals"]} == {"fil", "dealB"}
    assert aaa["pct"] == pytest.approx(100 * (152.0 / 148.0 - 1), abs=1e-9)
    ccc = r["candidates"][syms.index("CCC")]
    assert [s["type"] for s in ccc["signals"]] == ["dealS"]
    assert all("_value" not in s for c in r["candidates"] for s in c["signals"])
    assert r["rule"] and r["disclaimer"] and "not a prediction" in r["disclaimer"].lower()
    # no write anywhere
    assert not any(w in q.upper() for q in conn.sql for w in ("INSERT", "UPDATE", "DELETE"))


def test_candidates_drops_illiquid_and_priceless_symbols(mv, monkeypatch):
    import asyncio
    from datetime import date
    anns = [
        {"symbol": "THIN", "announcement_id": 9, "subject": "THIN wins order", "description": "d", "event_category": "orders"},
        {"symbol": "NOPX", "announcement_id": 10, "subject": "NOPX bags order", "description": "d", "event_category": "orders"},
    ]
    prices = [{"symbol": "THIN", "close_price": 10.0, "prev_close": 10.0, "turnover": 1e6}]  # below MIN_TURNOVER
    # NOPX has no EQ price row at all on this session (suspended / BE-BZ / untraded) -> excluded, not a dash
    conn = _CandConn(date(2026, 10, 2), anns=anns, deals=[], prices=prices)
    pool = types.SimpleNamespace(acquire=lambda: _Acq(conn))

    async def _pool():
        return pool
    monkeypatch.setattr(mv, "_pool", _pool)
    mv._cache.clear()

    r = asyncio.run(mv.candidates(request=None, session=None, limit=40))
    assert r["candidates"] == [] and r["count"] == 0


def test_candidates_empty_day_still_carries_rule_and_disclaimer(mv, monkeypatch):
    import asyncio
    from datetime import date
    conn = _CandConn(date(2026, 10, 2), anns=[], deals=[], prices=[])
    pool = types.SimpleNamespace(acquire=lambda: _Acq(conn))

    async def _pool():
        return pool
    monkeypatch.setattr(mv, "_pool", _pool)
    mv._cache.clear()

    r = asyncio.run(mv.candidates(request=None, session=None, limit=40))
    assert r == {"session": "2026-10-02", "count": 0, "candidates": [], "rule": r["rule"], "disclaimer": r["disclaimer"]}
    assert "high" in r["rule"] and "not a prediction" in r["disclaimer"].lower()


def test_candidates_404_when_no_session_on_record(mv, monkeypatch):
    import asyncio
    from fastapi import HTTPException
    conn = _CandConn(None)
    pool = types.SimpleNamespace(acquire=lambda: _Acq(conn))

    async def _pool():
        return pool
    monkeypatch.setattr(mv, "_pool", _pool)
    mv._cache.clear()
    with pytest.raises(HTTPException) as e:
        asyncio.run(mv.candidates(request=None, session=None, limit=40))
    assert e.value.status_code == 404


def test_preview_loader_refuses_a_counted_snapshot(tmp_path):
    """The loader must be incapable of writing a counted-looking run: it takes only preview snapshots that do not count."""
    import json as _json
    spec = importlib.util.spec_from_file_location("tpd_preview_loader_t", MOVERS_PATH.parent.parent / "tpd_preview_loader.py")
    ld = importlib.util.module_from_spec(spec); spec.loader.exec_module(ld)
    (tmp_path / "manifest.json").write_text(_json.dumps({"preview": False, "counts_toward_verdict": True, "target_session": "2026-10-05", "data_as_of": "2026-10-01", "git_sha": "x", "universe_size": 1}))
    (tmp_path / "tpd3_predictions.csv").write_text("symbol,head,p_tpd3\nAAA,p_up5_1d,0.1\n")
    with pytest.raises(SystemExit):
        ld.build_sql(tmp_path, "L", "n")
    (tmp_path / "manifest.json").write_text(_json.dumps({"preview": True, "counts_toward_verdict": False, "target_session": "2026-10-05", "data_as_of": "2026-10-01", "git_sha": "x", "universe_size": 1}))
    sql = ld.build_sql(tmp_path, "L", "n")
    assert "tpd_preview_runs" in sql and "tpd_runs " not in sql.replace("tpd_preview_runs", "")
