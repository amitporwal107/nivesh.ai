"""Historical Smart Money Movement — the derivation and the proxy route.

Two halves, neither of which touches a database or the network:

  * `classify_row` / `fii_trust` / `in_view` from nidp/services/daas_api/routers/ownership.py are
    pure, so the reaction label, the source-trust ladder and the view filters are tested directly.
    The INPUT FIGURES in these cases are REAL — queried from the staging warehouse on 2026-10-23
    and recorded in test_reports/ownership_reaction_20261023.md — so a drift in the thresholds or
    the labelling rule fails an assertion instead of quietly relabelling the screen.
  * routes/markets_ownership.py with the DaaS client stubbed, which checks that it forwards the
    filters and passes the body through, and that an upstream failure is 502 and never a quietly
    empty panel.

The thresholds are the ones the endpoint measured for Jul-Sep 2026 over the 488 Nifty-500 names
that clear the session floor on the SPLIT-ADJUSTED series:
ret_p20 = -13.54%, ret_p80 = +7.66%, vol_ratio median = 0.757.
"""
import asyncio
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nidp.services.daas_api.routers import ownership as own  # noqa: E402


@pytest.fixture
def route_mod(monkeypatch):
    """`routes.markets_ownership`, imported with `deps` stubbed — and the stub does NOT leak.

    Importing the real `deps` pulls in motor and the OpenAI SDK, neither of which this route
    touches. MOCK — not real data: only `get_current_user` is replaced, so the route's own work
    (parameter validation, what it forwards, the pass-through, the error mapping) runs for real.

    The stub is installed per-test via monkeypatch and the route module is dropped from the import
    cache afterwards. An earlier draft stubbed `deps` at module scope, which leaked into other test
    modules in the same session and silently made their "needs a signed-in user" tests pass — a
    stub that changes another module's result is worse than no stub.
    """
    import importlib

    stub = types.ModuleType("deps")

    async def _get_current_user(request):  # the route only needs "a signed-in user exists"
        return {"id": "u1"}

    stub.get_current_user = _get_current_user
    stub.db = None
    monkeypatch.setitem(sys.modules, "deps", stub)
    sys.modules.pop("routes.markets_ownership", None)
    mod = importlib.import_module("routes.markets_ownership")
    yield mod
    # Drop it so the next importer binds against the REAL deps, not the stub.
    sys.modules.pop("routes.markets_ownership", None)

# Real measured cut-points for the quarter under test.
CUTS = {"ret_p20": -13.54, "ret_p80": 7.66, "vol_p50": 0.757}


def row(**kw):
    """A measured row as the SQL returns it, before derivation."""
    base = {
        "symbol": "TEST", "industry": "Capital Goods",
        "delta_basis": "same_source", "delta_source": "screener_in",
        "fii_delta_pp": None, "dii_delta_pp": None, "inst_delta_pp": None,
        "fii_pct_now": None, "dii_pct_now": None, "delta_alt_pp": None,
        "fii_spread_pp": None, "mf_pct": None, "bank_fi_pct": None, "split_source": None,
        "ret_pct": None, "vol_ratio": None, "deliv_shift_pp": None,
        "sessions_cur": 65, "sessions_prev": 60, "ret_percentile": None,
    }
    base.update(kw)
    return base


# ── reaction: the price+volume conjunction ───────────────────────────────

def test_tc1_strong_positive_needs_both_legs():
    """TC-1: top-quintile return WITH volume at or above the peer median."""
    r = own.classify_row(row(ret_pct=18.0, vol_ratio=1.20), CUTS)
    assert r["price_band"] == "top_quintile"
    assert r["volume_band"] == "expanded"
    assert r["reaction"] == "strong_positive"
    assert r["reaction_corroborated"] is True
    assert r["reaction_note"] is None


def test_tc2_negative_is_the_real_crompton_row():
    """TC-2: CROMPTON, real figures — -24.05% on a 0.771 volume ratio."""
    r = own.classify_row(row(symbol="CROMPTON", ret_pct=-24.05, vol_ratio=0.771,
                             deliv_shift_pp=3.66, fii_delta_pp=-0.69, dii_delta_pp=-0.66,
                             inst_delta_pp=-1.35, delta_basis="cross_source"), CUTS)
    assert r["price_band"] == "bottom_quintile"
    assert r["volume_band"] == "expanded"
    assert r["reaction"] == "negative"
    assert r["reaction_corroborated"] is True


@pytest.mark.parametrize("symbol,ret,vol", [("ANGELONE", -17.13, 0.606), ("TARIL", -23.13, 0.381)])
def test_tc3_sharp_fall_on_thin_volume_is_neutral_but_says_so(symbol, ret, vol):
    """TC-3: the two real rows where price fell hard and volume did NOT confirm.

    They must not be labelled `negative` (one leg only), and must not be silently `neutral`
    either: the note names the leg that failed to confirm.
    """
    r = own.classify_row(row(symbol=symbol, ret_pct=ret, vol_ratio=vol), CUTS)
    assert r["price_band"] == "bottom_quintile"
    assert r["volume_band"] == "contracted"
    assert r["reaction"] == "neutral"
    assert r["reaction_corroborated"] is False
    assert "volume contracted" in r["reaction_note"]
    assert "0.757" in r["reaction_note"]


def test_tc4_mid_band_is_plain_neutral():
    """TC-4: ICICIPRULI, real figures — a mid-band return carries no note."""
    r = own.classify_row(row(symbol="ICICIPRULI", ret_pct=-9.05, vol_ratio=0.942), CUTS)
    assert r["reaction"] == "neutral"
    assert r["price_band"] == "middle"
    assert r["reaction_corroborated"] is True
    assert r["reaction_note"] is None


def test_tc5_absent_price_legs_are_absent_not_neutral():
    """TC-5: below the session floor the tape is unmeasured — never `neutral`, never 0."""
    r = own.classify_row(row(symbol="VISL", ret_pct=None, vol_ratio=None, sessions_prev=11), CUTS)
    assert r["price_legs_present"] is False
    assert r["reaction"] is None
    assert r["price_band"] is None and r["volume_band"] is None
    assert r["reaction_corroborated"] is None
    assert "Fewer than 30 sessions" in r["reaction_note"]
    # And it must not be counted into a reaction bucket by accident.
    assert r["reaction"] != "neutral"


# ── source trust ─────────────────────────────────────────────────────────

def test_tc6_icicibank_the_whole_trap_closed_end_to_end():
    """TC-6: ICICIBANK, exactly as the endpoint serves it (verified against staging 2026-10-23).

    Two guards have to hold at once for this row to be honest:
      * the basis preference serves the SAME-SOURCE change, +0.89pp, not the +16.65pp that
        differencing NSE_SHP's Sep level against screener_in's Jun level produces;
      * the +16.65pp artifact is still visible as `delta_alt_pp`, and because the publishers
        disagree by 15.76pp on the level, the FII figure is `unusable` -- so the UI prints
        "sources differ" rather than any number at all.
    """
    r = own.classify_row(row(symbol="ICICIBANK", delta_basis="same_source",
                             delta_source="screener_in",
                             fii_delta_pp=0.89, dii_delta_pp=-0.55, inst_delta_pp=0.34,
                             delta_alt_pp=16.65, fii_spread_pp=15.76,
                             ret_pct=-3.89, vol_ratio=0.585), CUTS)
    assert r["fii_trust"] == "unusable"          # 15.76 >= abs(0.89)
    assert r["delta_alt_pp"] == 16.65            # the artifact stays visible, never silently dropped
    assert r["reaction"] == "neutral"            # mid-band return
    # Had the cross-source figure been served instead it would still be MARKED, never settled fact.
    assert own.fii_trust(16.65, 15.76, "cross_source") == "contested"


def test_tc7_material_but_smaller_spread_is_contested():
    """TC-7: WIPRO — a real 2.63pp spread against a 0.61pp change is unusable; widen the change."""
    assert own.fii_trust(5.0, 2.63, "same_source") == "contested"
    assert own.fii_trust(0.61, 2.63, "same_source") == "unusable"


def test_tc8_trust_floor_and_absent_delta():
    """TC-8: rounding-level disagreement is `ok`; no change at all is `none`."""
    assert own.fii_trust(1.0, None, "same_source") == "ok"
    assert own.fii_trust(1.0, 0.0, "same_source") == "ok"
    assert own.fii_trust(1.0, 0.49, "same_source") == "ok"
    assert own.fii_trust(None, 5.0, "same_source") == "none"


def test_tc10_cross_source_is_never_better_than_contested():
    """TC-10: a cross-source change differences two publishers, so it is never plain `ok`."""
    assert own.fii_trust(1.0, None, "cross_source") == "contested"
    assert own.fii_trust(1.0, 0.1, "cross_source") == "contested"
    # Same figures on a same-source basis are fine.
    assert own.fii_trust(1.0, 0.1, "same_source") == "ok"


# ── divergence + absent-is-not-zero ──────────────────────────────────────

def test_tc9_divergence_has_exactly_one_definition():
    """TC-9: the `view=divergence` filter delegates to the STATUS, so the two can never disagree.

    An earlier draft had a looser view rule (13 names) beside the status rule (7). Two numbers for
    one word on one screen is a contradiction, so the view now reads the status.
    """
    diverged = own.classify_status(srow(symbol="NUVOCO", inst_delta_pp=-0.43, fii_delta_pp=-0.43,
                                        dii_delta_pp=0.0, ret_pct=11.47, vol_ratio=2.907,
                                        deliv_shift_pp=-2.37, dist_52w_high_pct=-23.20,
                                        dist_52w_low_pct=30.0), CC)
    assert diverged["status"] == "divergence"
    assert own.in_view(diverged, "divergence") is True

    # Opposite signs but a sub-median ownership move: not the status, so not the view either.
    weak = own.classify_status(srow(inst_delta_pp=-0.10, ret_pct=11.47, vol_ratio=0.8,
                                    deliv_shift_pp=0.0), CC)
    assert weak["status"] != "divergence"
    assert own.in_view(weak, "divergence") is False

    # An unmeasured tape cannot diverge from anything.
    none_tape = own.classify_status(srow(inst_delta_pp=6.66, ret_pct=None, vol_ratio=None), CC)
    assert own.in_view(none_tape, "divergence") is False


def test_tc11_absent_split_stays_absent_and_is_flagged_a_level():
    """TC-11: ANGELONE discloses no MF/Banks-FI split — it must stay null, never 0."""
    r = own.classify_row(row(symbol="ANGELONE", mf_pct=None, bank_fi_pct=None,
                             ret_pct=-17.13, vol_ratio=0.606), CUTS)
    assert r["mf_pct"] is None and r["bank_fi_pct"] is None
    assert r["split_is_level"] is True          # one quarter only: no delta is computable
    assert r["dii_components_complete"] is False  # insurance_pct/govt are empty: LIC invisible


def test_view_filters_use_the_published_materiality_floor():
    red = own.classify_row(row(inst_delta_pp=-1.35, ret_pct=-24.05, vol_ratio=0.771), CUTS)
    rai = own.classify_row(row(inst_delta_pp=2.35, ret_pct=-14.60, vol_ratio=0.528), CUTS)
    tiny = own.classify_row(row(inst_delta_pp=-0.3, ret_pct=-2.0, vol_ratio=1.0), CUTS)
    assert own.in_view(red, "reduced") and not own.in_view(red, "raised")
    assert own.in_view(rai, "raised") and not own.in_view(rai, "reduced")
    assert not own.in_view(tiny, "reduced") and not own.in_view(tiny, "raised")
    assert own.in_view(tiny, "all")
    # divergence is the STATUS's business, not this filter's: unclassified rows are not divergent.
    assert not own.in_view(rai, "divergence")
    assert not own.in_view(red, "divergence")


def test_cohort_percentile_is_carried_through_untouched():
    """`ret_percentile` is a POSITION IN THE COHORT, not excess return over an index.

    The derivation must pass it through without reinterpreting it, and the label must never claim a
    benchmark comparison: nidp.index_eod's 'Nifty 500' covers 25.4% of 2025's sessions, so no index
    series is read anywhere in this feature.
    """
    r = own.classify_row(row(symbol="CROMPTON", ret_pct=-24.05, vol_ratio=0.771,
                             ret_percentile=1.6), CUTS)
    assert r["ret_percentile"] == 1.6
    src = Path(own.__file__).read_text()
    assert "prices_eod_adjusted" in src              # split-safe price leg
    assert "adj_close" in src and "adj_volume" in src
    # index_eod may be DISCUSSED in prose (it is, to record why it is unfit), but never QUERIED.
    for read in ("FROM nidp.index_eod", "JOIN nidp.index_eod", "from nidp.index_eod"):
        assert read not in src, read
    assert "vs Nifty 500" in src                     # named as the thing it must NOT be called


# ── the desk status taxonomy ─────────────────────────────────────────────

# This quarter's real cohort percentiles, as the shipped cohort_cuts() measured them over the 89
# eligible names (verified against staging 2026-10-23).
CC = {
    "n": 89,
    "inst_p25": -0.05, "inst_p50": 0.15, "inst_p75": 0.77,
    "ret_p25": -13.75, "ret_p50": -6.77, "ret_p75": 3.42,
    "vol_p25": 0.59, "vol_p50": 0.761, "vol_p75": 0.972,
    "deliv_p25": 1.32, "deliv_p50": 3.66, "deliv_p75": 5.94,
    "high_p50": -22.17, "low_p25": 6.508,
    "abs_inst_p50": 0.42, "abs_ret_p50": 11.05,
    "near_52w_high_pct": -10.0,
}


def srow(**kw):
    """A row that has already been through classify_row, ready for classify_status."""
    base = row(**kw)
    base.setdefault("dist_52w_high_pct", None)
    base.setdefault("dist_52w_low_pct", None)
    base.setdefault("filed_at", None)
    base.setdefault("quarters_available", 12)
    return own.classify_row(base, CUTS)


def test_percentile_matches_postgres_percentile_cont():
    """TC-23: the Python percentile must equal percentile_cont, or the published cut-points lie."""
    assert own._pct([1.0, 2.0, 3.0, 4.0], 0.50) == 2.5
    assert own._pct([1.0, 2.0, 3.0, 4.0], 0.25) == 1.75
    assert own._pct([1.0, 2.0, 3.0, 4.0], 0.75) == 3.25
    assert own._pct([5.0], 0.75) == 5.0
    assert own._pct([], 0.5) is None
    # Real check: the cohort's own numbers reproduce the figures the envelope publishes.
    rows = [srow(inst_delta_pp=v, ret_pct=-5.0, vol_ratio=0.8) for v in (-0.05, 0.15, 0.77, 2.0)]
    c = own.cohort_cuts(rows)
    assert c["n"] == 4
    assert round(c["inst_p50"], 3) == 0.46


def test_tc24_distribution_risk_is_the_only_red_status():
    """TC-24: CANFINHOME, real figures — ownership down, price down, volume UP."""
    r = own.classify_status(srow(symbol="CANFINHOME", inst_delta_pp=-1.79, fii_delta_pp=-0.72,
                                 dii_delta_pp=-1.07, ret_pct=-17.14, vol_ratio=1.137,
                                 deliv_shift_pp=6.60, dist_52w_high_pct=-25.97,
                                 dist_52w_low_pct=20.0), CC)
    assert r["status"] == "distribution_risk"
    # The reason has to name the legs AND their cut-points, so the label is checkable.
    for frag in ("-1.79pp", "-17.14%", "-6.77%", "1.137", "0.972"):
        assert frag in r["status_reason"], frag


def test_tc25_reversal_watch_is_accumulation_into_weakness_not_a_risk():
    """TC-25: adding while the price falls to near the 52-week low is a WATCH, never red.

    No real row hit this in Jul-Sep 2026 (the status count is 0), so the legs are exercised with
    figures built from the real cut-points — the rule still has to be right for the quarter it fires.
    """
    r = own.classify_status(srow(symbol="TESTREV", inst_delta_pp=1.50, fii_delta_pp=1.5,
                                 dii_delta_pp=0.0, ret_pct=-20.0, vol_ratio=0.80,
                                 deliv_shift_pp=1.0, dist_52w_high_pct=-45.0,
                                 dist_52w_low_pct=3.0), CC)
    assert r["status"] == "reversal_watch"
    assert "added into weakness" in r["status_reason"]
    # The taxonomy must not classify it as the red one.
    assert r["status"] != "distribution_risk"


def test_tc26_breakout_watch_is_the_real_karurvysya_row():
    """TC-26: KARURVYSYA, the single real breakout_watch — and it is a DESCRIPTION, not a call."""
    r = own.classify_status(srow(symbol="KARURVYSYA", inst_delta_pp=1.06, fii_delta_pp=0.5,
                                 dii_delta_pp=0.56, ret_pct=9.69, vol_ratio=1.063,
                                 deliv_shift_pp=1.57, dist_52w_high_pct=-9.44,
                                 dist_52w_low_pct=40.0), CC)
    assert r["status"] == "breakout_watch"
    assert "52-week high" in r["status_reason"]


def test_tc27_accumulation_needs_all_four_legs():
    """TC-27: KARURVYSYA fails accumulation ONLY on delivery (+1.57pp vs a +3.66pp median).

    Zero of the 89 names passed the four-leg test this quarter. That zero is a real answer, so the
    rule must not be quietly relaxed into firing.
    """
    legs = dict(symbol="KARURVYSYA", inst_delta_pp=1.06, fii_delta_pp=0.5, dii_delta_pp=0.56,
                ret_pct=9.69, vol_ratio=1.063, dist_52w_high_pct=-40.0, dist_52w_low_pct=40.0)
    assert own.classify_status(srow(deliv_shift_pp=1.57, **legs), CC)["status"] != "accumulation"
    # Lift only the delivery leg over the median and it qualifies.
    ok = own.classify_status(srow(deliv_shift_pp=4.0, **legs), CC)
    assert ok["status"] == "accumulation"
    assert "all four legs agree" in ok["status_reason"]


def test_tc28_divergence_needs_both_legs_beyond_median_magnitude():
    """TC-28: NUVOCO, real figures — ownership DOWN while the price rose 11.47%."""
    r = own.classify_status(srow(symbol="NUVOCO", inst_delta_pp=-0.43, fii_delta_pp=-0.43,
                                 dii_delta_pp=0.0, ret_pct=11.47, vol_ratio=2.907,
                                 deliv_shift_pp=-2.37, dist_52w_high_pct=-23.20,
                                 dist_52w_low_pct=30.0), CC)
    assert r["status"] == "divergence"
    # Opposite signs but a sub-median ownership move is not divergence.
    small = own.classify_status(srow(inst_delta_pp=-0.10, ret_pct=11.47, vol_ratio=0.8,
                                     deliv_shift_pp=0.0), CC)
    assert small["status"] != "divergence"
    # Opposite signs but a sub-median price move is not divergence either.
    flat = own.classify_status(srow(inst_delta_pp=-2.0, ret_pct=1.0, vol_ratio=0.8,
                                    deliv_shift_pp=0.0), CC)
    assert flat["status"] != "divergence"


def test_tc29_contested_sources_cannot_carry_a_status():
    """TC-29: the three real unusable rows must read `insufficient_data`, not a neutral status.

    An absence of evidence is reported as an absence, never as "nothing happened".
    """
    for sym, fii, spread in (("ICICIBANK", 0.89, 15.76), ("WIPRO", 0.61, 2.63), ("AXISBANK", -1.86, 3.11)):
        r = own.classify_status(srow(symbol=sym, fii_delta_pp=fii, fii_spread_pp=spread,
                                     dii_delta_pp=0.0, inst_delta_pp=fii, ret_pct=-6.0,
                                     vol_ratio=0.9, deliv_shift_pp=2.0), CC)
        assert r["fii_trust"] == "unusable", sym
        assert r["status"] == "insufficient_data", sym
        assert "disagree" in r["status_reason"]


def test_tc30_no_measurable_tape_is_insufficient_not_none():
    """TC-30: an unmeasurable quarter is `insufficient_data`, distinct from `none`."""
    r = own.classify_status(srow(symbol="VISL", inst_delta_pp=1.0, fii_delta_pp=1.0,
                                 dii_delta_pp=0.0, ret_pct=None, vol_ratio=None), CC)
    assert r["status"] == "insufficient_data"
    assert r["reaction"] is None
    # Whereas a measurable but unremarkable quarter is `none` — a real reading, not a gap.
    plain = own.classify_status(srow(inst_delta_pp=0.1, ret_pct=-5.0, vol_ratio=0.8,
                                     deliv_shift_pp=2.0), CC)
    assert plain["status"] == "none"


def test_tc39_status_buckets_reconcile_to_the_eligible_cohort():
    """TC-39: the buckets are exhaustive and mutually exclusive, so they MUST sum to the cohort.

    A sum that misses means a name was dropped or double-counted, which silently restates the
    denominator — the exact class of error this screen exists to avoid. Checked on the REAL
    distribution (0 + 1 + 0 + 4 + 7 + 3 + 74 = 89) and on a synthetic mixed cohort.
    """
    real = {"accumulation": 0, "breakout_watch": 1, "reversal_watch": 0, "distribution_risk": 4,
            "divergence": 7, "insufficient_data": 3, "none": 74}
    assert sum(real.values()) == 89
    assert set(real) == set(own._STATUSES)

    # Every row gets exactly one status, and no row is left unclassified.
    mixed = [
        srow(symbol="A", inst_delta_pp=-1.79, fii_delta_pp=-0.72, dii_delta_pp=-1.07,
             ret_pct=-17.14, vol_ratio=1.137, deliv_shift_pp=6.6, dist_52w_high_pct=-26.0,
             dist_52w_low_pct=0.6),
        srow(symbol="B", inst_delta_pp=1.06, fii_delta_pp=0.18, dii_delta_pp=0.88,
             ret_pct=9.69, vol_ratio=1.063, deliv_shift_pp=1.57, dist_52w_high_pct=-9.44,
             dist_52w_low_pct=56.0),
        srow(symbol="C", inst_delta_pp=-0.43, fii_delta_pp=-0.08, dii_delta_pp=-0.35,
             ret_pct=11.47, vol_ratio=2.907, deliv_shift_pp=-2.37, dist_52w_high_pct=-23.2,
             dist_52w_low_pct=22.3),
        srow(symbol="D", fii_delta_pp=0.89, dii_delta_pp=-0.55, inst_delta_pp=0.34,
             fii_spread_pp=15.76, ret_pct=-3.89, vol_ratio=0.585, deliv_shift_pp=4.89),
        srow(symbol="E", inst_delta_pp=0.1, fii_delta_pp=0.1, dii_delta_pp=0.0,
             ret_pct=-5.0, vol_ratio=0.8, deliv_shift_pp=2.0),
        srow(symbol="F", inst_delta_pp=1.0, fii_delta_pp=1.0, dii_delta_pp=0.0,
             ret_pct=None, vol_ratio=None),
    ]
    c = own.cohort_cuts(mixed)
    done = [own.classify_status(r, c) for r in mixed]
    assert all(r["status"] in own._STATUSES for r in done)
    buckets = {s: sum(1 for r in done if r["status"] == s) for s in own._STATUSES}
    assert sum(buckets.values()) == len(mixed), buckets
    # Exactly one status each: no row can land in two buckets.
    assert len({r["symbol"] for r in done}) == len(mixed)


def test_tc40_insufficient_data_is_its_own_bucket_not_folded_into_no_status():
    """TC-40: "we cannot tell" must stay distinct from "no rule fired".

    Folding them together would report an absence of evidence as a neutral reading, which is the
    thing this whole screen is built not to do.
    """
    cant_tell = own.classify_status(srow(symbol="ICICIBANK", fii_delta_pp=0.89, dii_delta_pp=-0.55,
                                        inst_delta_pp=0.34, fii_spread_pp=15.76, ret_pct=-3.89,
                                        vol_ratio=0.585, deliv_shift_pp=4.89), CC)
    nothing_fired = own.classify_status(srow(symbol="PLAIN", inst_delta_pp=0.1, fii_delta_pp=0.1,
                                             dii_delta_pp=0.0, ret_pct=-5.0, vol_ratio=0.8,
                                             deliv_shift_pp=2.0), CC)
    assert cant_tell["status"] == "insufficient_data"
    assert nothing_fired["status"] == "none"
    assert cant_tell["status"] != nothing_fired["status"]
    assert "insufficient_data" in own._STATUSES and "none" in own._STATUSES


def test_the_deps_stub_does_not_leak_into_other_test_modules(route_mod):
    """The `deps` stub must not survive the test that needed it.

    Regression guard: an earlier draft installed it at module scope, so every later test module in
    the same pytest session imported the permissive stub instead of the real `deps` — which made
    their "needs a signed-in user" tests pass without any auth. A stub that changes another
    module's result is worse than no stub at all.
    """
    # Inside the fixture the stub IS in place: a bare types.ModuleType, which has no __file__.
    assert getattr(sys.modules["deps"], "__file__", None) is None
    assert route_mod.__name__ == "routes.markets_ownership"


def test_deps_is_clean_outside_the_fixture():
    """Run after the fixture-using tests: nothing of ours is left behind in sys.modules."""
    dep = sys.modules.get("deps")
    if dep is not None:
        # If `deps` is present at all it must be the REAL module, not a types.ModuleType stub
        # we built: the real one has a __file__, ours never does.
        assert getattr(dep, "__file__", None) is not None, "a deps stub leaked out of a fixture"


def test_status_vocabulary_has_no_score_and_no_recommendation_words():
    """Nothing in the taxonomy may read as a call. Guarded as text, in both layers."""
    src = Path(own.__file__).read_text().lower()
    for banned in ("buy signal", "sell signal", "target price", "recommend", "should buy", "should sell"):
        assert banned not in src, banned
    assert set(own._STATUSES) == {
        "accumulation", "breakout_watch", "reversal_watch", "distribution_risk",
        "divergence", "insufficient_data", "none",
    }


def test_quarter_start_is_derived_not_hardcoded():
    from datetime import date
    assert own._quarter_start(date(2026, 9, 30)) == date(2026, 7, 1)
    assert own._quarter_start(date(2026, 6, 30)) == date(2026, 4, 1)
    assert own._quarter_start(date(2026, 3, 31)) == date(2026, 1, 1)
    assert own._quarter_start(date(2026, 12, 31)) == date(2026, 10, 1)


# ── the proxy route ──────────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def proxy(monkeypatch, route_mod):
    """routes/markets_ownership.py with the DaaS client and auth stubbed."""
    mo = route_mod
    from services.copilot_tools import daas_client

    state = {"status": 200, "body": {"rows": [], "count": 0}, "raise": None, "configured": True, "calls": []}

    async def get_raw(path, params=None):
        state["calls"].append((path, params))
        if state["raise"]:
            raise daas_client.DaasError(state["raise"])
        return state["status"], state["body"]

    monkeypatch.setattr(daas_client, "is_configured", lambda: state["configured"])
    monkeypatch.setattr(daas_client, "get_raw", get_raw)
    monkeypatch.setattr(mo, "get_current_user", lambda request: _noop())
    return mo, state


async def _noop():
    return {"id": "u1"}


def test_tc12_proxy_forwards_filters_and_passes_the_body_through(proxy):
    """TC-12: the route adds nothing and derives nothing."""
    mo, state = proxy
    payload = {
        "as_of": "2026-09-30", "previous_period": "2026-06-30",
        "thresholds": {"ret_p20_pct": -13.54, "ret_p80_pct": 7.66, "vol_ratio_median": 0.757,
                       "reference_cross_section": 488},
        "coverage": {"universe_total": 500, "computable_change": 89, "same_source": 65,
                     "cross_source": 24},
        "counts": {"reduced": 10, "divergence": 13, "negative": 9},
        "validated_study": False,
        "count": 1, "total": 1,
        "rows": [{"symbol": "CROMPTON", "inst_delta_pp": -1.35, "ret_pct": -24.05,
                  "reaction": "negative"}],
    }
    state["body"] = payload
    got = _run(mo.ownership_reaction(request=None, view="reduced", reaction="negative",
                                     status="distribution_risk", basis="any",
                                     sort="inst_delta", limit=50))
    assert got == payload                     # passed through unchanged
    path, params = state["calls"][-1]
    assert path == "/desk/ownership/reaction"
    assert params == {"view": "reduced", "reaction": "negative", "status": "distribution_risk",
                      "basis": "any", "sort": "inst_delta", "limit": 50}


def test_tc13_upstream_failure_is_502_never_an_empty_panel(proxy):
    """TC-13: a blank panel would read as "no institution moved" — a different, false claim."""
    from fastapi import HTTPException
    mo, state = proxy

    state["raise"] = "connect timeout"
    with pytest.raises(HTTPException) as e:
        _run(mo.ownership_reaction(request=None))
    assert e.value.status_code == 502 and e.value.detail == "upstream_unavailable"

    state["raise"] = None
    state["configured"] = False
    with pytest.raises(HTTPException) as e:
        _run(mo.ownership_reaction(request=None))
    assert e.value.status_code == 502


def test_tc14_a_body_without_a_rows_list_is_a_contract_failure(proxy):
    """TC-14: 200-with-the-wrong-shape must not reach the screen as "nothing happened"."""
    from fastapi import HTTPException
    mo, state = proxy
    for bad in ({"count": 0}, {"rows": None}, {"rows": {}}, [], None):
        state["body"] = bad
        with pytest.raises(HTTPException) as e:
            _run(mo.ownership_reaction(request=None))
        assert e.value.status_code == 502

    state["status"] = 500
    state["body"] = {"rows": []}
    with pytest.raises(HTTPException) as e:
        _run(mo.ownership_reaction(request=None))
    assert e.value.status_code == 502


def test_tc15_unknown_filter_values_are_rejected_over_http(monkeypatch, route_mod):
    """TC-15: the view/reaction/status/sort vocabularies are closed — as real requests.

    `sort=score` matters most: there is no score anywhere in this feature and asking for one must
    be a 422, not silently ignored and answered with some other ordering.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from services.copilot_tools import daas_client

    mo = route_mod

    async def get_raw(path, params=None):
        return 200, {"rows": [], "count": 0, "total": 0}

    monkeypatch.setattr(daas_client, "is_configured", lambda: True)
    monkeypatch.setattr(daas_client, "get_raw", get_raw)

    app = FastAPI()
    app.include_router(mo.router)
    c = TestClient(app)

    assert c.get("/api/markets/ownership/reaction").status_code == 200
    for ok in ("view=reduced", "view=divergence", "reaction=negative", "basis=same_source",
               "sort=ret", "limit=500", "status=distribution_risk", "status=insufficient_data"):
        assert c.get(f"/api/markets/ownership/reaction?{ok}").status_code == 200, ok
    for bad in ("view=momentum", "reaction=bullish", "basis=best", "sort=score",
                "sort=rank", "limit=0", "limit=501", "status=strong_buy", "status=bullish"):
        assert c.get(f"/api/markets/ownership/reaction?{bad}").status_code == 422, bad
