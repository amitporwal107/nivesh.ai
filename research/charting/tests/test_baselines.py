"""The B0-B5 ladder — `research/charting/baselines`.

These pin the properties that make an INCREMENT interpretable. The ladder's whole purpose is to
stop a model being credited for information it did not add, so the tests are about the apparatus
being honest rather than about any result.
"""
from __future__ import annotations

import math
import random

import pytest

from research.charting.baselines import features as F, ladder as L, pattern_rung as P


# ── the rungs are nested, which is what makes an increment mean anything ────────────────────────

def test_each_rung_is_a_strict_superset_of_the_one_above():
    """If B3 were not a superset of B2, 'the B3 increment' would be the difference between two
    unrelated models — which a richer model wins on capacity, not information."""
    names = [n for n, _ in F.RUNGS]
    prev: set = set()
    for n in names:
        cur = set(F.cumulative_features(n))
        assert prev <= cur, f"{n} dropped features present in the rung above it"
        prev = cur
    assert len(prev) > 20, "B5 is suspiciously small"


def test_b0_has_no_features_at_all():
    """B0 is the base rate. Any feature here and the floor stops being a floor."""
    assert F.cumulative_features("B0") == {}


def test_an_unknown_rung_raises_rather_than_returning_something_plausible():
    with pytest.raises(ValueError, match="unknown rung"):
        F.cumulative_features("B9")


# ── the canary ──────────────────────────────────────────────────────────────────────────────────

def test_b0_scores_exactly_half_which_is_how_the_pooling_bug_was_caught():
    """An intercept-only model gives every row the same score, so its AUC is 0.5 BY CONSTRUCTION.

    This is the ladder's canary. It caught a real defect: pooling out-of-fold predictions across
    folds gave B0 an AUC of 0.3821, because each fold has its own intercept fitted to its own base
    rate, so a row's score depended on WHICH FOLD it landed in. That contaminated every rung. B0 is
    the only model with a known correct answer, which is why it earns its place despite being
    trivial.
    """
    rng = random.Random(0)
    n = 400
    feats = [{} for _ in range(n)]
    labels = [1 if rng.random() < 0.7 else 0 for _ in range(n)]
    syms = [f"S{i % 20:02d}" for i in range(n)]
    dates = ["2021-01-01"] * n

    res = L.cross_val_auc(feats, [], labels, syms, dates, k=5)
    assert res["auc"] == pytest.approx(0.5, abs=1e-9), (
        f"B0 scored {res['auc']} — an intercept-only model cannot discriminate; "
        f"this is the fold-pooling bug returning")
    assert all(a == pytest.approx(0.5, abs=1e-9) for a in res["fold_aucs"])


def test_a_pure_signal_is_recovered_and_pure_noise_is_not():
    """The canary proves the floor. This proves the ceiling is reachable — without it, a ladder
    that always returned 0.5 would pass the test above and be useless."""
    rng = random.Random(1)
    n = 600
    labels, feats = [], []
    for i in range(n):
        y = 1 if rng.random() < 0.5 else 0
        feats.append({"signal": y + rng.gauss(0, 0.25), "noise": rng.gauss(0, 1)})
        labels.append(y)
    syms = [f"S{i % 30:02d}" for i in range(n)]
    dates = ["2021-01-01"] * n

    strong = L.cross_val_auc(feats, ["signal"], labels, syms, dates, k=5)
    weak = L.cross_val_auc(feats, ["noise"], labels, syms, dates, k=5)
    assert strong["auc"] > 0.9, f"a near-perfect feature only reached {strong['auc']}"
    assert 0.35 < weak["auc"] < 0.65, f"pure noise scored {weak['auc']}"


# ── folds must hold out symbols, not rows ───────────────────────────────────────────────────────

def test_folds_hold_out_whole_symbols():
    """Rows are not independent — overlapping windows on one symbol, and symbols co-moving on one
    day. A row-level split leaks symbol identity into the test fold and inflates every number."""
    syms = [f"S{i % 10:02d}" for i in range(200)]
    dates = ["2021-01-01"] * 200
    train, test = L.symbol_time_folds(syms, dates, k=5)
    for tr, te in zip(train, test):
        tr_syms = {syms[i] for i in tr}
        te_syms = {syms[i] for i in te}
        assert not (tr_syms & te_syms), "a symbol appeared in both train and test"
    covered = set()
    for te in test:
        covered |= {syms[i] for i in te}
    assert covered == set(syms), "some symbol was never in a test fold"


def test_symbol_clustered_intervals_are_wider_than_row_level_ones():
    """§A3: the row-level CI on ATR's AUC looks decisive; the symbol-clustered one barely excludes
    0.5. If clustering did not widen the interval it would not be doing anything."""
    rng = random.Random(2)
    scores, labels, syms = [], [], []
    for s in range(25):                       # strong WITHIN-symbol structure, weak across
        base = rng.random()
        for _ in range(40):
            y = 1 if rng.random() < base else 0
            scores.append(base + rng.gauss(0, 0.05)); labels.append(y); syms.append(f"S{s:02d}")

    lo, hi = L.symbol_cluster_ci(scores, labels, syms, draws=200)
    distinct = [f"R{i}" for i in range(len(scores))]          # every row its own "symbol"
    rlo, rhi = L.symbol_cluster_ci(scores, labels, distinct, draws=200)
    assert (hi - lo) > (rhi - rlo), (
        "clustering by symbol did not widen the interval — it is not clustering")


# ── missing values, and what a raw zero would mean ──────────────────────────────────────────────

def test_a_missing_feature_becomes_the_mean_not_a_raw_zero():
    """For a distance-from-SMA feature, 0.0 means 'exactly at the moving average' — a real and
    specific claim. Imputing it for a missing value invents data. The column mean is a standardised
    zero, which asserts nothing."""
    stats = L._standardise([[10.0, 20.0, 30.0]])
    X = L._design([{"f": None}], ["f"], stats)
    assert X[0][1] == 0.0                       # standardised mean
    X2 = L._design([{"f": 20.0}], ["f"], stats)
    assert X2[0][1] == pytest.approx(0.0)       # the actual mean standardises to the same place
    X3 = L._design([{"f": 30.0}], ["f"], stats)
    assert X3[0][1] > 0.5, "a real value above the mean must not standardise to zero"


# ── the pattern rung's honest limitation ────────────────────────────────────────────────────────

def test_the_pattern_block_carries_no_presence_flag():
    """Every row in the event dataset IS a pattern, so `pattern_present` would be a constant and
    carry no information. P1 vs B5 therefore tests WHICH pattern and in what state — not whether
    patterns matter, which needs non-pattern rows (§30's G0-G3). Pinned so a future reader cannot
    mistake this comparison for the other one."""
    feats = P.pattern_features({"pattern_type": "RECTANGLE", "direction": "BULLISH"})
    assert "pattern_present" not in feats
    assert sum(feats.get(f"is_{f.lower()}", 0) for f in P.PATTERN_FAMILIES) == 1.0


def test_pattern_family_is_one_hot_not_an_integer_code():
    """An integer code would tell a linear model that HH_HL sits numerically between RECTANGLE and
    SUPPORT_RESISTANCE, letting it fit a gradient across a nominal category."""
    for fam in P.PATTERN_FAMILIES:
        f = P.pattern_features({"pattern_type": fam})
        hot = [k for k in f if k.startswith("is_") and k != "is_bullish" and f[k] == 1.0]
        assert hot == [f"is_{fam.lower()}"], f"{fam} did not one-hot cleanly"
    unknown = P.pattern_features({"pattern_type": "NOT_A_FAMILY"})
    assert sum(unknown.get(f"is_{f.lower()}", 0) for f in P.PATTERN_FAMILIES) == 0.0


def test_missing_features_are_listed_not_silently_dropped():
    """A rung missing half its PRD specification is a WEAKER control than it looks, which biases
    the ladder toward crediting the pattern block with unmodelled baseline value."""
    for rung in ("B1", "B2", "B3", "B4", "B5"):
        assert F.MISSING.get(rung), f"{rung} claims nothing is missing — verify that"
    assert any("SECTOR" in m for m in F.MISSING["B4"]), "the absent sector rung must be recorded"


# ── breadth momentum: the derivative, and the hole it has to survive ────────────────────────────

def test_momentum_is_a_difference_not_a_level():
    """The owner's point: 42%→48%→57%→63% is a different market from 63% flat for weeks, and the
    level alone cannot tell them apart."""
    from research.charting.baselines import breadth_momentum as BM

    rising = [{"date": f"2021-01-{d:02d}", "pct_above_sma50": v, "pct_above_sma200": v,
               "advance_decline_ratio": 1.0}
              for d, v in zip(range(4, 20), [0.42 + 0.02 * i for i in range(16)])]
    flat = [{"date": f"2021-01-{d:02d}", "pct_above_sma50": 0.63, "pct_above_sma200": 0.63,
             "advance_decline_ratio": 1.0} for d in range(4, 20)]

    def momentum(series):
        import research.charting.baselines.breadth_momentum as m
        orig = m.load_series
        m.load_series = lambda path=None: series
        try:
            return m.build_index()
        finally:
            m.load_series = orig

    r = momentum(rising)["2021-01-19"]["pct_above_sma50_mom_10"]
    f = momentum(flat)["2021-01-19"]["pct_above_sma50_mom_10"]
    assert r > 0.15, f"a clearly rising series gave momentum {r}"
    assert f == pytest.approx(0.0), f"a flat series gave momentum {f}"


def test_a_lookback_across_the_sealed_hole_is_unavailable_not_a_number():
    """BREADTH_UNIVERSE.csv jumps 2022-12-30 -> 2024-08-01. A naive difference across that boundary
    computes a NINETEEN-MONTH change and calls it a 10-session move — the largest readings in the
    dataset, all landing at the start of the post-sealed segment, with nothing erroring. This is
    the guard, tested on the real file rather than a fixture."""
    from research.charting.baselines import breadth_momentum as BM

    idx = BM.build_index()
    dates = sorted(idx)
    post = [d for d in dates if d >= "2024-08-01"][:10]
    assert post, "no post-sealed dates in the breadth series"
    for d in post:
        assert idx[d]["pct_above_sma200_mom_10"] is None, (
            f"{d} produced a 10-session momentum across the sealed gap")
    pre = [d for d in dates if d <= "2022-12-30"][-1]
    assert idx[pre]["pct_above_sma200_mom_10"] is not None, (
        "the guard is too aggressive — it killed a legitimate pre-gap window")


def test_a_blank_source_cell_is_never_read_as_zero():
    """`breadth.py` leaves pct_above_sma200 blank until 200 names have a full trailing window.
    Reading that as 0% asserts 'no stock in the market is above its 200-day average'."""
    from research.charting.baselines import breadth_momentum as BM

    assert BM._f("") is None
    assert BM._f(None) is None
    assert BM._f("0") == 0.0, "a real zero must survive"


def test_missing_dates_yield_none_so_the_ladder_imputes_the_mean():
    from research.charting.baselines import breadth_momentum as BM

    feats = BM.features_for("1999-01-01", {})
    assert set(feats) == set(BM.feature_names())
    assert all(v is None for v in feats.values()), "a missing date must not fabricate zeros"
