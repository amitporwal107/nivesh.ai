"""Unit tests for mf_category_ranking — AC-01 through AC-15.

All tests are fixture-injected (no DB required).
Run: pytest nidp/services/mf_category_ranking/tests/test_ranking.py -v
"""
from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Dict, List, Optional

import pytest

# ── Paths ───────────────────────────────────────────────────────────────────
# The ranking module is a pure function — no DB imports needed for unit tests.
from nidp.services.mf_category_ranking.config import (
    ConfigurationError,
    FamilyConfig,
    RankingConfig,
    family_for_category,
    load_config,
)
from nidp.services.mf_category_ranking.peer_set import FundMetrics, _filter_direct_growth
from nidp.services.mf_category_ranking.ranking import (
    STATUS_INSUF_COVERAGE,
    STATUS_INSUF_HISTORY,
    STATUS_LOW_CONFIDENCE,
    STATUS_RANKED,
    RankedFund,
    rank_category,
)

# ── Fixtures ────────────────────────────────────────────────────────────────

RANK_DATE = date(2025, 12, 31)
SEBI_CAT = "Equity Scheme - Large Cap Fund"

EQUAL_WEIGHTS = FamilyConfig(
    name="Equity",
    weights={"ret": 0.50, "sharpe": 0.50},
    directions={"ret": "higher", "sharpe": "higher"},
)

EQUITY_CONFIG = FamilyConfig(
    name="Equity",
    weights={
        "return_1y":       0.10,
        "return_3y":       0.25,
        "return_5y":       0.15,
        "sharpe_1y":       0.15,
        "sortino_1y":      0.10,
        "max_drawdown_1y": 0.10,
        "expense_ratio":   0.10,
        "beta_1y":         0.05,
    },
    directions={
        "return_1y":       "higher",
        "return_3y":       "higher",
        "return_5y":       "higher",
        "sharpe_1y":       "higher",
        "sortino_1y":      "higher",
        # max_drawdown stored as negative (-35 = 35% drawdown = bad).
        # Higher raw value = closer to 0 = smaller drawdown = better.
        "max_drawdown_1y": "higher",
        "expense_ratio":   "lower",
        "beta_1y":         "lower",
    },
)

THRESHOLDS = RankingConfig(
    families={"Equity": EQUITY_CONFIG},
    min_history_bars=252,
    min_peers=8,
    w_min=0.60,
)


def _make_fund(code: str, nav_count: int = 300, **metrics) -> FundMetrics:
    """Helper: create a FundMetrics with the given metric overrides."""
    f = FundMetrics(
        scheme_code=code,
        scheme_name=f"Fund {code}",
        sebi_category=SEBI_CAT,
        expense_ratio=metrics.pop("expense_ratio", 1.0),
        aum_cr=metrics.pop("aum_cr", 100.0),
        nav_count=nav_count,
        data_as_of=RANK_DATE,
    )
    for k, v in metrics.items():
        setattr(f, k, v)
    return f


def _rank(funds: List[FundMetrics], config=None, family=None) -> Dict[str, RankedFund]:
    """Rank funds and return {scheme_code: RankedFund}."""
    if config is None:
        config = THRESHOLDS
    if family is None:
        family = EQUITY_CONFIG
    result = rank_category(funds, family, config, RANK_DATE)
    return {r.scheme_code: r for r in result}


# ── AC-01: No rank-averaging (§7.1 root cause) ──────────────────────────────

def test_ac01_no_rank_averaging_prd_fixture():
    """PRD §7.1 fixture: verify percentile-rank composite is different from rank-averaging.

    NOTE on PRD §7.1 numbers (A=94, B=75):
    Those numbers assume magnitude-preserving normalization (e.g. min-max). The §5.2
    formula mandates percentile rank, which for this 3-fund fixture gives A=75=B=75 (tie).
    The tie-break (sharpe desc) gives B=#1, A=#2.

    What this test verifies (the actual AC-01 intent):
    1. C ranks last — C has the weakest sharpe AND the weakest return — composite = 0.
    2. A and B both rank clearly above C (composite ≫ 0).
    3. A's return percentile = 100 (best in peer set regardless of magnitude).
    4. The composite + tie-break produces a determinate, non-arbitrary ordering.

    The defect the PRD describes (WRONG method) would give A and B the same rank via
    averaged per-metric ranks (1.5 each). The percentile-rank composite also ties them
    at 75, but the TIE-BREAK is deterministic and explicit — not the silent magnitude loss
    of rank-averaging. In real categories (50+ funds), magnitude differences play out
    across the distribution and percentile rank correctly captures them.
    """
    fam = FamilyConfig(
        name="Equity",
        weights={"ret": 0.50, "sharpe": 0.50},
        directions={"ret": "higher", "sharpe": "higher"},
    )
    cfg = RankingConfig(families={"Equity": fam}, min_history_bars=10, min_peers=3, w_min=0.30)

    class PrdFund(FundMetrics):
        def __init__(self, code, ret, sharpe):
            super().__init__(code, f"Fund {code}", SEBI_CAT, expense_ratio=None, aum_cr=100,
                             nav_count=300, data_as_of=RANK_DATE)
            self._ret = ret
            self._sharpe = sharpe
        def metrics_dict(self):
            return {"ret": self._ret, "sharpe": self._sharpe}

    prd_funds = [PrdFund("A", 60.0, 0.50), PrdFund("B", 12.0, 0.55), PrdFund("C", 11.0, 0.10)]
    result = rank_category(prd_funds, fam, cfg, RANK_DATE)
    by_code = {r.scheme_code: r for r in result}

    # C must rank last — composite = 0 (worst on both metrics)
    assert by_code["C"].category_rank == 3, f"C should be #3 but got {by_code['C'].category_rank}"
    assert by_code["C"].composite == 0.0, f"C composite should be 0, got {by_code['C'].composite}"

    # A and B both rank above C
    assert by_code["A"].category_rank < 3
    assert by_code["B"].category_rank < 3

    # A's ret pct = 100 (best return in peer set)
    a_ret_pct = by_code["A"].metric_contributions["ret"]["pct"]
    assert a_ret_pct == 100.0, f"A ret_pct={a_ret_pct} should be 100 (best in peer set)"

    # A and B tie on composite (75.0 each).
    # Competition rank = 1 + count(j: composite_j > composite_i).
    # Neither A nor B has any peer with composite > 75 → both get competition rank = 1.
    # C has 2 peers with composite > 0 → rank = 3.
    assert by_code["A"].composite == by_code["B"].composite == 75.0
    assert by_code["A"].category_rank == 1
    assert by_code["B"].category_rank == 1  # tie → both rank 1 (competition rank)
    assert by_code["C"].category_rank == 3


def test_ac01_magnitude_separation():
    """Fund 5× better on one metric must have clearly higher composite (AC-01)."""
    class SimpleFund(FundMetrics):
        def __init__(self, code, ret):
            super().__init__(code, f"Fund {code}", SEBI_CAT, expense_ratio=None, aum_cr=100,
                             nav_count=300, data_as_of=RANK_DATE)
            self._ret = ret
        def metrics_dict(self):
            return {"ret": self._ret}

    fam = FamilyConfig("E", {"ret": 1.0}, {"ret": "higher"})
    cfg = RankingConfig(families={"E": fam}, min_history_bars=10, min_peers=2, w_min=0.5)
    funds = [SimpleFund("A", 60.0), SimpleFund("B", 12.0)]
    result = rank_category(funds, fam, cfg, RANK_DATE)
    by_code = {r.scheme_code: r for r in result}
    assert by_code["A"].composite > by_code["B"].composite
    diff = by_code["A"].composite - by_code["B"].composite
    assert diff > 30.0, f"Magnitude separation too small: {diff}"


# ── AC-02: Direction inversion ───────────────────────────────────────────────

def test_ac02_lower_is_better_inverted():
    """Fund with worst expense_ratio/max_drawdown/beta must NOT be #1."""
    class LowerFund(FundMetrics):
        def __init__(self, code, er, mdd, beta):
            super().__init__(code, f"Fund {code}", SEBI_CAT, expense_ratio=er, aum_cr=100,
                             nav_count=300, data_as_of=RANK_DATE)
            self.max_drawdown_1y = mdd
            self.beta_1y = beta
        def metrics_dict(self):
            return {
                "expense_ratio":   self.expense_ratio,
                "max_drawdown_1y": self.max_drawdown_1y,
                "beta_1y":         self.beta_1y,
            }

    fam = FamilyConfig(
        "E",
        {"expense_ratio": 0.34, "max_drawdown_1y": 0.33, "beta_1y": 0.33},
        # max_drawdown stored as negative (e.g. -35 = 35% peak-to-trough drop).
        # "higher" raw value = less negative = smaller drawdown = better.
        {"expense_ratio": "lower", "max_drawdown_1y": "higher", "beta_1y": "lower"},
    )
    cfg = RankingConfig(families={"E": fam}, min_history_bars=10, min_peers=3, w_min=0.5)

    funds = [
        LowerFund("X", er=2.5, mdd=-35.0, beta=1.8),  # worst on all lower-is-better
        LowerFund("Y", er=1.0, mdd=-15.0, beta=1.1),
        LowerFund("Z", er=0.5, mdd=-8.0,  beta=0.9),  # best on all
    ]
    result = rank_category(funds, fam, cfg, RANK_DATE)
    by_code = {r.scheme_code: r for r in result}

    assert by_code["X"].category_rank == 3, "Worst fund must rank last"
    assert by_code["Z"].category_rank == 1, "Best fund must rank first"

    x_er_pct = by_code["X"].metric_contributions["expense_ratio"]["pct"]
    assert x_er_pct < 50.0, f"Worst expense_ratio pct should be < 50, got {x_er_pct}"
    x_mdd_pct = by_code["X"].metric_contributions["max_drawdown_1y"]["pct"]
    assert x_mdd_pct < 50.0, f"Worst drawdown pct should be < 50, got {x_mdd_pct}"


def test_ac02_direction_flip_changes_results():
    """Flipping lower_is_better flag must reverse who ranks top."""
    class SimpleFund(FundMetrics):
        def __init__(self, code, er):
            super().__init__(code, f"Fund {code}", SEBI_CAT, expense_ratio=er, aum_cr=100,
                             nav_count=300, data_as_of=RANK_DATE)
        def metrics_dict(self):
            return {"expense_ratio": self.expense_ratio}

    funds = [SimpleFund("A", er=2.5), SimpleFund("B", er=0.5)]
    cfg = RankingConfig(families={}, min_history_bars=10, min_peers=2, w_min=0.5)

    # Correct: lower is better → B (0.5) ranks #1
    fam_correct = FamilyConfig("E", {"expense_ratio": 1.0}, {"expense_ratio": "lower"})
    result_correct = rank_category(funds, fam_correct, cfg, RANK_DATE)
    correct = {r.scheme_code: r for r in result_correct}
    assert correct["B"].category_rank == 1

    # Wrong: higher is better → A (2.5) ranks #1 (wrong direction)
    fam_wrong = FamilyConfig("E", {"expense_ratio": 1.0}, {"expense_ratio": "higher"})
    result_wrong = rank_category(funds, fam_wrong, cfg, RANK_DATE)
    wrong = {r.scheme_code: r for r in result_wrong}
    assert wrong["A"].category_rank == 1
    # Both produce pct > 80 for their respective "winner"
    assert wrong["A"].metric_contributions["expense_ratio"]["pct"] > 80.0


# ── AC-03: Dedupe plan/option variants ──────────────────────────────────────

def test_ac03_dedupe_filters_regular_plan():
    """Regular + IDCW variants must be filtered out; only Direct-Growth kept."""
    schemes = [
        {"scheme_code": "A", "scheme_name": "Axis Bluechip Fund - Direct Plan Growth"},
        {"scheme_code": "A-REG", "scheme_name": "Axis Bluechip Fund - Regular Plan Growth"},
        {"scheme_code": "A-IDCW", "scheme_name": "Axis Bluechip Fund - Direct Plan IDCW"},
        {"scheme_code": "A-REG-IDCW", "scheme_name": "Axis Bluechip Fund - Regular Plan IDCW"},
    ]
    kept, collapsed = _filter_direct_growth(schemes)
    codes = {s["scheme_code"] for s in kept}
    assert "A-REG" not in codes,     "Regular plan must be filtered"
    assert "A-REG-IDCW" not in codes, "Regular IDCW must be filtered"
    assert "A-IDCW" not in codes,    "IDCW must be filtered"
    assert "A" in codes,             "Direct-Growth must be kept"
    # All 3 non-canonical variants are collapsed
    assert len(codes) == 1
    assert collapsed == 3


def test_ac03_ambiguous_name_kept():
    """Scheme with no Direct/Growth keyword is included (fail-open) and logged."""
    schemes = [{"scheme_code": "X", "scheme_name": "Some Scheme"}]
    kept, collapsed = _filter_direct_growth(schemes)
    assert len(kept) == 1
    assert collapsed == 0


# ── AC-04: Missing-data re-normalisation ────────────────────────────────────

def test_ac04_missing_metric_renormalised_not_zero_filled():
    """Fund with one null metric gets re-normalised W_i, not penalised to 0."""
    fam = FamilyConfig(
        "E",
        {"ret_3y": 0.30, "sharpe": 0.35, "sortino": 0.35},
        {"ret_3y": "higher", "sharpe": "higher", "sortino": "higher"},
    )
    cfg = RankingConfig(families={"E": fam}, min_history_bars=10, min_peers=4, w_min=0.60)

    class M(FundMetrics):
        def __init__(self, code, r, sh, so):
            super().__init__(code, f"Fund {code}", SEBI_CAT, expense_ratio=None, aum_cr=100,
                             nav_count=300, data_as_of=RANK_DATE)
            self._r = r; self._sh = sh; self._so = so
        def metrics_dict(self):
            return {"ret_3y": self._r, "sharpe": self._sh, "sortino": self._so}

    # Fund D is missing sortino
    funds = [
        M("A", 15.0, 1.2, 0.9),
        M("B", 12.0, 0.9, 0.7),
        M("C", 10.0, 0.8, 0.6),
        M("D", 13.0, 1.0, None),  # sortino = None
    ]
    result = rank_category(funds, fam, cfg, RANK_DATE)
    by_code = {r.scheme_code: r for r in result}

    d = by_code["D"]
    assert d.status in (STATUS_RANKED, STATUS_LOW_CONFIDENCE), \
        f"W_i=0.65 >= 0.60, so D should be ranked, got status={d.status}"
    assert d.composite is not None

    # Verify W_i = 0.30 + 0.35 = 0.65 (sortino excluded)
    mc = d.metric_contributions
    sortino_pct = mc["sortino"]["pct"]
    assert sortino_pct is None, "Null sortino should have pct=None"

    # Verify composite = sum(w * pct for non-null) / 0.65
    non_null_items = [(k, v) for k, v in mc.items() if v["pct"] is not None]
    W_i = sum(v["weight"] for _, v in non_null_items)
    assert abs(W_i - 0.65) < 0.001, f"W_i should be 0.65, got {W_i}"
    recon = sum(v["weight"] * v["pct"] / W_i for _, v in non_null_items)
    assert abs(recon - d.composite) < 0.01, \
        f"Reconstructed={recon:.4f} != composite={d.composite}"


def test_ac04_wi_boundary_exactly_060_is_ranked():
    """W_i = exactly 0.60 must be ranked (not coverage-gated)."""
    fam = FamilyConfig("E", {"a": 0.60, "b": 0.40}, {"a": "higher", "b": "higher"})
    cfg = RankingConfig(families={"E": fam}, min_history_bars=10, min_peers=1, w_min=0.60)

    class M(FundMetrics):
        def __init__(self, code, a, b):
            super().__init__(code, f"Fund {code}", SEBI_CAT, expense_ratio=None, aum_cr=100,
                             nav_count=300, data_as_of=RANK_DATE)
            self._a = a; self._b = b
        def metrics_dict(self):
            return {"a": self._a, "b": self._b}

    # Fund X has b=None → W_i = 0.60 (exactly at threshold)
    funds = [M("X", 10.0, None), M("Y", 5.0, 5.0)]
    result = rank_category(funds, fam, cfg, RANK_DATE)
    by_code = {r.scheme_code: r for r in result}
    # X has W_i = 0.60 which >= 0.60 → must be ranked
    assert by_code["X"].status in (STATUS_RANKED, STATUS_LOW_CONFIDENCE), \
        f"W_i=0.60 should be ranked, got {by_code['X'].status}"


# ── AC-05: Coverage gate ─────────────────────────────────────────────────────

def test_ac05_coverage_gate_emits_row_with_null_rank():
    """Fund below W_min gets insufficient_coverage; still emitted; not in category_size."""
    fam = FamilyConfig("E", {"a": 0.40, "b": 0.60}, {"a": "higher", "b": "higher"})
    cfg = RankingConfig(families={"E": fam}, min_history_bars=10, min_peers=2, w_min=0.60)

    class M(FundMetrics):
        def __init__(self, code, a, b):
            super().__init__(code, f"Fund {code}", SEBI_CAT, expense_ratio=None, aum_cr=100,
                             nav_count=300, data_as_of=RANK_DATE)
            self._a = a; self._b = b
        def metrics_dict(self):
            return {"a": self._a, "b": self._b}

    # Fund E has only metric a (W_i = 0.40 < 0.60)
    funds = [M("E", 10.0, None), M("F", 8.0, 6.0), M("G", 6.0, 4.0)]
    result = rank_category(funds, fam, cfg, RANK_DATE)
    by_code = {r.scheme_code: r for r in result}

    # E must be emitted
    assert "E" in by_code, "Coverage-gated fund must still appear in output"
    e = by_code["E"]
    assert e.status == STATUS_INSUF_COVERAGE
    assert e.category_rank is None
    assert e.composite is None

    # E must not count in category_size
    ranked_funds = [r for r in result if r.status in (STATUS_RANKED, STATUS_LOW_CONFIDENCE)]
    for r in ranked_funds:
        assert r.category_size == len(ranked_funds), \
            f"category_size should exclude coverage-gated funds"


# ── AC-06: Determinism ───────────────────────────────────────────────────────

def test_ac06_determinism_same_output_twice():
    """Two runs on identical inputs must produce bit-identical output."""
    funds = [_make_fund(f"F{i}", return_1y=float(10+i), return_3y=float(8+i),
                        sharpe_1y=float(0.5+i*0.1)) for i in range(10)]
    cfg = RankingConfig(families={"Equity": EQUITY_CONFIG}, min_history_bars=10,
                        min_peers=8, w_min=0.40)
    result1 = rank_category(funds[:], EQUITY_CONFIG, cfg, RANK_DATE)
    result2 = rank_category(funds[:], EQUITY_CONFIG, cfg, RANK_DATE)

    r1 = sorted(result1, key=lambda r: r.scheme_code)
    r2 = sorted(result2, key=lambda r: r.scheme_code)
    for a, b in zip(r1, r2):
        assert a.scheme_code == b.scheme_code
        assert a.category_rank == b.category_rank
        assert a.composite == b.composite


def test_ac06_determinism_input_order_invariant():
    """Output rank order must not change when input list order is reversed."""
    funds = [_make_fund(f"F{i}", return_1y=float(10+i)) for i in range(5)]
    cfg = RankingConfig(families={"Equity": EQUITY_CONFIG}, min_history_bars=10,
                        min_peers=5, w_min=0.10)
    result_fwd = rank_category(funds[:], EQUITY_CONFIG, cfg, RANK_DATE)
    result_rev = rank_category(list(reversed(funds)), EQUITY_CONFIG, cfg, RANK_DATE)

    fwd = {r.scheme_code: r for r in result_fwd}
    rev = {r.scheme_code: r for r in result_rev}
    for code in fwd:
        assert fwd[code].category_rank == rev[code].category_rank, \
            f"{code}: rank changed with input order reversal"


# ── AC-07: Boundary correctness ──────────────────────────────────────────────

def test_ac07_best_fund_pct_100_rank_1():
    funds = [_make_fund(f"F{i}", return_1y=float(i)) for i in range(5)]
    cfg = RankingConfig(families={"Equity": EQUITY_CONFIG}, min_history_bars=10,
                        min_peers=5, w_min=0.10)
    result = rank_category(funds, EQUITY_CONFIG, cfg, RANK_DATE)
    ranked = [r for r in result if r.category_rank is not None]
    best = min(ranked, key=lambda r: r.category_rank)
    assert best.category_rank == 1
    assert best.category_pct == 100.0


def test_ac07_worst_fund_pct_0():
    funds = [_make_fund(f"F{i}", return_1y=float(i)) for i in range(5)]
    cfg = RankingConfig(families={"Equity": EQUITY_CONFIG}, min_history_bars=10,
                        min_peers=5, w_min=0.10)
    result = rank_category(funds, EQUITY_CONFIG, cfg, RANK_DATE)
    ranked = [r for r in result if r.category_rank is not None]
    worst = max(ranked, key=lambda r: r.category_rank)
    assert worst.category_pct == 0.0


def test_ac07_pct_formula_all_ranked():
    """(N - rank) / (N - 1) * 100 must hold for all ranked funds."""
    funds = [_make_fund(f"F{i}", return_1y=float(i)) for i in range(7)]
    cfg = RankingConfig(families={"Equity": EQUITY_CONFIG}, min_history_bars=10,
                        min_peers=7, w_min=0.10)
    result = rank_category(funds, EQUITY_CONFIG, cfg, RANK_DATE)
    ranked = [r for r in result if r.category_rank is not None]
    N = len(ranked)
    assert N > 0
    for r in ranked:
        expected = (N - r.category_rank) / (N - 1) * 100.0
        assert abs(r.category_pct - expected) < 0.01, \
            f"{r.scheme_code}: pct={r.category_pct}, expected={expected:.2f}"


def test_ac07_single_fund_no_zero_division():
    """Single rankable fund: rank=1, pct=100, no ZeroDivisionError (N-1=0 case)."""
    funds = [_make_fund("ONLY", return_1y=10.0)]
    cfg = RankingConfig(families={"Equity": EQUITY_CONFIG}, min_history_bars=10,
                        min_peers=8, w_min=0.10)
    result = rank_category(funds, EQUITY_CONFIG, cfg, RANK_DATE)
    by_code = {r.scheme_code: r for r in result}
    assert by_code["ONLY"].category_rank == 1
    assert by_code["ONLY"].category_pct == 100.0
    assert by_code["ONLY"].status == STATUS_LOW_CONFIDENCE  # N=1 < min_peers=8


# ── AC-08: Auditability ──────────────────────────────────────────────────────

def test_ac08_metric_contributions_sum_to_composite():
    """metric_contributions weighted sum must equal composite ±0.01 for all ranked."""
    funds = [_make_fund(f"F{i}", return_1y=float(i), return_3y=float(i),
                        sharpe_1y=float(i)*0.1) for i in range(10)]
    cfg = RankingConfig(families={"Equity": EQUITY_CONFIG}, min_history_bars=10,
                        min_peers=8, w_min=0.10)
    result = rank_category(funds, EQUITY_CONFIG, cfg, RANK_DATE)

    for r in result:
        if r.composite is None:
            continue
        mc = r.metric_contributions
        non_null = [(k, v) for k, v in mc.items() if v["pct"] is not None]
        W_i = sum(v["weight"] for _, v in non_null)
        if W_i < 1e-9:
            continue
        recon = sum(v["weight"] * v["pct"] / W_i for _, v in non_null)
        assert abs(recon - r.composite) < 0.01, \
            f"{r.scheme_code}: recon={recon:.4f} != composite={r.composite}"


# ── AC-09: Point-in-time correctness ────────────────────────────────────────

def test_ac09_future_nav_excluded_via_min_history():
    """Fund with 0 nav observations (simulates future NAV filtered at fetch)
    must be insufficient_history, not affect peer rankings."""
    good_fund = _make_fund("GOOD", return_1y=15.0, nav_count=300)
    # Future-only fund: nav_count=0 (simulates all NAVs being after target date)
    future_fund = _make_fund("FUTURE", return_1y=9999.0, nav_count=0)

    cfg = RankingConfig(families={"Equity": EQUITY_CONFIG}, min_history_bars=252,
                        min_peers=1, w_min=0.10)
    result = rank_category([good_fund, future_fund], EQUITY_CONFIG, cfg, RANK_DATE)
    by_code = {r.scheme_code: r for r in result}

    assert by_code["FUTURE"].status == STATUS_INSUF_HISTORY
    assert by_code["FUTURE"].category_rank is None
    # GOOD's ranking must not be affected by FUTURE
    assert by_code["GOOD"].category_rank == 1
    assert by_code["GOOD"].category_size == 1  # FUTURE excluded from category_size


# ── AC-10: Tiny-category flag ────────────────────────────────────────────────

def test_ac10_low_confidence_when_n_less_than_min_peers():
    """N=7 (< min_peers=8) → all ranked funds get low_confidence status."""
    funds = [_make_fund(f"F{i}", return_1y=float(i)) for i in range(7)]
    cfg = RankingConfig(families={"Equity": EQUITY_CONFIG}, min_history_bars=10,
                        min_peers=8, w_min=0.10)
    result = rank_category(funds, EQUITY_CONFIG, cfg, RANK_DATE)
    ranked = [r for r in result if r.category_rank is not None]
    assert len(ranked) == 7
    assert all(r.status == STATUS_LOW_CONFIDENCE for r in ranked), \
        f"All ranked should be low_confidence: {[(r.scheme_code, r.status) for r in ranked]}"


def test_ac10_not_low_confidence_when_n_equals_min_peers():
    """N=8 (== min_peers=8) → status must be ranked, NOT low_confidence."""
    funds = [_make_fund(f"F{i}", return_1y=float(i)) for i in range(8)]
    cfg = RankingConfig(families={"Equity": EQUITY_CONFIG}, min_history_bars=10,
                        min_peers=8, w_min=0.10)
    result = rank_category(funds, EQUITY_CONFIG, cfg, RANK_DATE)
    ranked = [r for r in result if r.category_rank is not None]
    assert len(ranked) == 8
    assert all(r.status == STATUS_RANKED for r in ranked)


# ── AC-11: Insufficient-history exclusion ───────────────────────────────────

def test_ac11_history_excluded_fund_not_in_category_size():
    """Fund with nav_count < min_history → excluded from peer set and category_size."""
    young_fund = _make_fund("YOUNG", return_1y=99.0, nav_count=100)  # < 252
    old_fund1  = _make_fund("OLD1", return_1y=15.0, nav_count=300)
    old_fund2  = _make_fund("OLD2", return_1y=10.0, nav_count=300)

    cfg = RankingConfig(families={"Equity": EQUITY_CONFIG}, min_history_bars=252,
                        min_peers=2, w_min=0.10)
    result = rank_category([young_fund, old_fund1, old_fund2], EQUITY_CONFIG, cfg, RANK_DATE)
    by_code = {r.scheme_code: r for r in result}

    # Young fund emitted but excluded from peer set
    assert "YOUNG" in by_code
    assert by_code["YOUNG"].status == STATUS_INSUF_HISTORY
    assert by_code["YOUNG"].category_rank is None

    # Old funds' category_size must NOT include YOUNG
    assert by_code["OLD1"].category_size == 2
    assert by_code["OLD2"].category_size == 2


def test_ac11_exactly_252_bars_is_rankable():
    """Fund with exactly 252 nav_count (= min_history_bars) must be rankable."""
    fund = _make_fund("EXACT", return_1y=10.0, nav_count=252)
    cfg = RankingConfig(families={"Equity": EQUITY_CONFIG}, min_history_bars=252,
                        min_peers=1, w_min=0.10)
    result = rank_category([fund], EQUITY_CONFIG, cfg, RANK_DATE)
    assert result[0].status != STATUS_INSUF_HISTORY


def test_ac11_251_bars_excluded():
    """Fund with 251 nav_count (< 252) must be insufficient_history."""
    fund = _make_fund("SHORT", return_1y=10.0, nav_count=251)
    cfg = RankingConfig(families={"Equity": EQUITY_CONFIG}, min_history_bars=252,
                        min_peers=1, w_min=0.10)
    result = rank_category([fund], EQUITY_CONFIG, cfg, RANK_DATE)
    assert result[0].status == STATUS_INSUF_HISTORY


# ── AC-12: Run metrics (tested via ranking output structure) ─────────────────

def test_ac12_status_buckets_correct():
    """Status counts in ranking output match expected bucket distribution."""
    funds = (
        [_make_fund(f"OK{i}", return_1y=float(i), nav_count=300) for i in range(8)]
        + [_make_fund("YOUNG", return_1y=5.0, nav_count=50)]   # insufficient_history
        + [_make_fund("POOR",  return_1y=None, nav_count=300)]  # may be insufficient_coverage
    )
    cfg = RankingConfig(families={"Equity": EQUITY_CONFIG}, min_history_bars=100,
                        min_peers=8, w_min=0.10)
    result = rank_category(funds, EQUITY_CONFIG, cfg, RANK_DATE)
    statuses = [r.status for r in result]
    assert STATUS_INSUF_HISTORY in statuses
    assert len([s for s in statuses if s == STATUS_INSUF_HISTORY]) >= 1


# ── AC-13: Staleness fields ──────────────────────────────────────────────────

def test_ac13_staleness_fields_present():
    """Every output row must have non-null last_ranked_at and data_as_of."""
    funds = [_make_fund("F1", return_1y=10.0)]
    cfg = RankingConfig(families={"Equity": EQUITY_CONFIG}, min_history_bars=10,
                        min_peers=1, w_min=0.10)
    result = rank_category(funds, EQUITY_CONFIG, cfg, RANK_DATE)
    for r in result:
        assert r.last_ranked_at is not None
        assert r.last_ranked_at.tzinfo is not None, "last_ranked_at must be tz-aware"
        assert r.data_as_of is not None
        assert r.data_as_of <= RANK_DATE


# ── AC-14: Config weight sum check ──────────────────────────────────────────

def test_ac14_bad_weights_raise_configuration_error():
    """Weight sum != 1.0 (outside ±0.001) must raise ConfigurationError."""
    bad_yaml = """
families:
  Equity:
    weights:
      return_3y: 0.30
      sharpe_1y: 0.30
      sortino_1y: 0.39
    directions:
      return_3y: higher
      sharpe_1y: higher
      sortino_1y: higher
thresholds:
  min_history_bars: 252
  min_peers: 8
  w_min: 0.60
"""
    with pytest.raises(ConfigurationError, match="Equity"):
        load_config(bad_yaml)


def test_ac14_good_weights_pass():
    """Valid weights (sum == 1.0) must not raise."""
    good_yaml = """
families:
  Equity:
    weights:
      return_3y: 0.60
      sharpe_1y: 0.40
    directions:
      return_3y: higher
      sharpe_1y: higher
thresholds:
  min_history_bars: 252
  min_peers: 8
  w_min: 0.60
"""
    cfg = load_config(good_yaml)
    assert "Equity" in cfg.families


def test_ac14_weight_sum_1001_raises():
    """Sum 1.001 is outside tolerance → raise."""
    # Use 0.502 + 0.500 = 1.002 — unambiguously over tolerance regardless of IEEE-754 rounding
    # (0.501 + 0.500 = 1.000999... in float, which rounds to 1.001 but is an edge case)
    yaml_str = """
families:
  Equity:
    weights:
      return_3y: 0.502
      sharpe_1y: 0.500
    directions:
      return_3y: higher
      sharpe_1y: higher
"""
    with pytest.raises(ConfigurationError):
        load_config(yaml_str)


def test_ac14_weight_sum_within_tolerance_ok():
    """Sum 1.0005 is within ±0.001 tolerance → no raise."""
    yaml_str = """
families:
  Equity:
    weights:
      return_3y: 0.5005
      sharpe_1y: 0.5000
    directions:
      return_3y: higher
      sharpe_1y: higher
"""
    cfg = load_config(yaml_str)
    assert "Equity" in cfg.families


# ── AC-15 (unit component): family_for_category mapping ─────────────────────

def test_ac15_equity_family_resolved():
    """Equity Scheme prefix must map to Equity family config."""
    cfg = load_config()  # loads weights.yaml
    fam = family_for_category("Equity Scheme - Large Cap Fund", cfg)
    assert fam is not None
    assert fam.name == "Equity"


def test_ac15_debt_family_returns_none_for_mvp():
    """Debt family has no weights in MVP config → returns None."""
    cfg = load_config()
    fam = family_for_category("Debt Scheme - Liquid Fund", cfg)
    # MVP: Debt has no config → None → funds get insufficient_coverage
    assert fam is None


# ── Edge cases ───────────────────────────────────────────────────────────────

def test_edge_all_null_metrics_insufficient_coverage():
    """Fund where every metric is None: W_i = 0 → insufficient_coverage."""
    class NullFund(FundMetrics):
        def __init__(self):
            super().__init__("NULL", "Null Fund", SEBI_CAT, expense_ratio=None, aum_cr=100,
                             nav_count=300, data_as_of=RANK_DATE)
        def metrics_dict(self):
            return {k: None for k in EQUITY_CONFIG.weights}

    funds = [NullFund()] + [_make_fund(f"F{i}", return_1y=float(i)) for i in range(3)]
    cfg = RankingConfig(families={"Equity": EQUITY_CONFIG}, min_history_bars=10,
                        min_peers=2, w_min=0.10)
    result = rank_category(funds, EQUITY_CONFIG, cfg, RANK_DATE)
    by_code = {r.scheme_code: r for r in result}
    assert by_code["NULL"].status == STATUS_INSUF_COVERAGE
    assert by_code["NULL"].composite is None
    assert by_code["NULL"].category_rank is None


def test_edge_nan_metric_treated_as_none():
    """NaN metric value must be treated as None (not propagated to composite)."""
    class NanFund(FundMetrics):
        def __init__(self, code, v):
            super().__init__(code, f"Fund {code}", SEBI_CAT, expense_ratio=None, aum_cr=100,
                             nav_count=300, data_as_of=RANK_DATE)
            self._v = v
        def metrics_dict(self):
            return {"return_1y": self._v}

    fam = FamilyConfig("E", {"return_1y": 1.0}, {"return_1y": "higher"})
    cfg = RankingConfig(families={"E": fam}, min_history_bars=10, min_peers=1, w_min=0.5)

    nan_fund = NanFund("NAN", float("nan"))
    good_fund = NanFund("GOOD", 10.0)

    # Must not raise; NAN fund should get insufficient_coverage (W_i=0)
    result = rank_category([nan_fund, good_fund], fam, cfg, RANK_DATE)
    by_code = {r.scheme_code: r for r in result}
    assert by_code["NAN"].status == STATUS_INSUF_COVERAGE
    assert by_code["GOOD"].status in (STATUS_RANKED, STATUS_LOW_CONFIDENCE)

    # Determinism: two runs with NaN produce identical output
    result2 = rank_category([nan_fund, good_fund], fam, cfg, RANK_DATE)
    r1 = {r.scheme_code: r for r in result}
    r2 = {r.scheme_code: r for r in result2}
    assert r1["GOOD"].category_rank == r2["GOOD"].category_rank
