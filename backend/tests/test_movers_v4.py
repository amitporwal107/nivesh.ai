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
