"""Selection metrics — `research/charting/baselines/evaluate.py`.

`decile_lift` decides which comparator "wins" in the A1 table, so these are not decoration: the
first run of A1 showed rs_50 beating atr_pct on top-1% lift (1.89 vs 1.42) while LOSING on AUC
(0.5612 vs 0.6064). If the lift is wrong, that conclusion inverts.

The module was rebuilt on 2026-09-30 after the original was lost un-committed, so these anchors
re-establish its behaviour rather than assuming it.
"""
import math
import random

import pytest

from research.charting.baselines.evaluate import decile_lift


def _ranker(n=20_000, base=0.30, sep=1.0, seed=7):
    """Scores drawn sep apart for hits vs misses: sep=0 is pure noise, sep=1 a strong ranker."""
    rng = random.Random(seed)
    y, s = [], []
    for _ in range(n):
        hit = rng.random() < base
        y.append(1 if hit else 0)
        s.append(rng.gauss(sep if hit else 0.0, 1.0))
    return s, y


# ── the two anchors ────────────────────────────────────────────────────────────────

def test_pure_noise_lands_at_one():
    """A score unrelated to the outcome must not concentrate winners. If this drifts, every lift
    in the comparator table is inflated by the same amount and the ranking is still wrong."""
    s, y = _ranker(sep=0.0)
    assert decile_lift(s, y, top=0.10)["lift"] == pytest.approx(1.0, abs=0.10)


def test_a_real_signal_concentrates():
    s, y = _ranker(sep=1.0)
    assert decile_lift(s, y, top=0.10)["lift"] > 1.8


def test_lift_is_monotone_in_slice_width_for_a_real_signal():
    """A tighter slice must be at least as good; if top 1% < top 10% the ordering is broken."""
    s, y = _ranker(sep=1.0)
    l1 = decile_lift(s, y, top=0.01)["lift"]
    l5 = decile_lift(s, y, top=0.05)["lift"]
    l10 = decile_lift(s, y, top=0.10)["lift"]
    assert l1 >= l5 >= l10


def test_a_perfect_ranker_gives_exactly_one_over_the_base_rate():
    y = [1] * 300 + [0] * 700
    s = [1.0] * 300 + [0.0] * 700
    assert decile_lift(s, y, top=0.30)["lift"] == pytest.approx(1 / 0.30)


def test_an_inverted_ranker_gives_lift_below_one():
    """rvol scored 0.79 on top-1% in A1 — genuinely anti-predictive. That must be representable,
    not floored at 1.0."""
    y = [1] * 300 + [0] * 700
    s = [0.0] * 300 + [1.0] * 700          # every high score is a miss
    assert decile_lift(s, y, top=0.10)["lift"] == 0.0


# ── undefined is None, never zero ──────────────────────────────────────────────────

@pytest.mark.parametrize("s, y, why", [
    ([], [], "no rows"),
    ([1.0, 2.0, 3.0], [0, 0, 0], "no positives anywhere — nothing to concentrate"),
    ([1.0, 2.0, 3.0], [1, 1, 1], "all positives — the top slice cannot beat the base"),
])
def test_undefined_cases_return_none_not_zero(s, y, why):
    """0.0 reads as 'no edge'; None reads as 'not measurable'. Conflating them has already caused
    a false negative in this programme."""
    assert decile_lift(s, y, top=0.10)["lift"] is None, why


def test_top_equal_to_one_is_undefined_rather_than_trivially_one():
    s, y = _ranker(n=1000)
    assert decile_lift(s, y, top=1.0)["lift"] is None


# ── the tie flag ───────────────────────────────────────────────────────────────────

def test_a_tie_spanning_the_cutoff_is_flagged():
    """When the slice boundary lands inside a run of equal scores, membership is chosen by the
    tie-break, not the model. With a coarse score that silently drives the number."""
    y = [1, 0] * 50
    s = [5.0] * 10 + [1.0] * 80 + [0.0] * 10        # top=0.20 -> k=20, cutoff inside the 1.0 run
    assert decile_lift(s, y, top=0.20)["tied_at_cutoff"] is True


def test_a_cutoff_falling_between_two_blocks_is_not_a_tie():
    y = [1] * 300 + [0] * 700
    s = [1.0] * 300 + [0.0] * 700
    assert decile_lift(s, y, top=0.30)["tied_at_cutoff"] is False


# ── bookkeeping and guards ─────────────────────────────────────────────────────────

def test_the_reported_counts_reconcile_with_the_lift():
    s, y = _ranker(n=5000)
    r = decile_lift(s, y, top=0.10)
    assert r["n"] == 5000
    assert r["n_top"] == math.ceil(5000 * 0.10)
    assert r["rate_top"] == pytest.approx(r["hits_top"] / r["n_top"])
    assert r["lift"] == pytest.approx(r["rate_top"] / r["base_rate"])


def test_ordering_is_deterministic_across_calls():
    s, y = _ranker(n=2000)
    assert decile_lift(s, y, top=0.05) == decile_lift(s, y, top=0.05)


def test_mismatched_lengths_raise_rather_than_silently_truncate():
    with pytest.raises(ValueError, match="length mismatch"):
        decile_lift([1.0, 2.0], [1], top=0.1)


@pytest.mark.parametrize("bad", [0.0, -0.1, 1.5])
def test_an_out_of_range_top_raises(bad):
    with pytest.raises(ValueError, match="top must be"):
        decile_lift([1.0, 2.0], [1, 0], top=bad)


def test_a_single_row_slice_still_works():
    s, y = _ranker(n=100)
    r = decile_lift(s, y, top=0.001)       # k floors at 1
    assert r["n_top"] == 1
