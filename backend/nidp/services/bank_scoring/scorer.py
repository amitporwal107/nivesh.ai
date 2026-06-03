"""Bank quality scorer — pure Python, no DB dependencies.

PSU vs Private design rationale
───────────────────────────────
PSU banks (promoter_pct > 40 %, government-owned):
  • Higher GNPA is structurally tolerable — they carry priority-sector mandates
    and have been through a massive NPA cleanup cycle (2015–2023).
  • The PRIMARY alpha signal is the TREND: GNPA falling from 10% → 5% unlocks
    massive earnings power as provisioning burden drops.
  • Government backstop means capital adequacy is less existential.
  • ROE benchmarks are lower (12% is excellent; private banks need 16%+).
  • GNPA trend gets equal weight to absolute level in the asset quality pillar.

Private banks (promoter_pct ≤ 40 % or known private):
  • Any GNPA above 3% is a serious warning — these banks lend at lower yields
    and lack the government backstop.
  • NII retention (proxy for CASA/cost-of-funds franchise) is the primary moat.
  • Absolute GNPA level dominates over trend in the asset quality pillar.
  • ROE expectations are higher (>15% separates great from average).

Pillars and weights
───────────────────
  | Pillar                 | Weight |
  |------------------------|--------|
  | Asset Quality          |  30 %  |  (null if GNPA data absent → rescaled)
  | Profitability          |  25 %  |
  | Liability Franchise    |  20 %  |
  | Earnings Quality       |  15 %  |
  | Growth                 |  10 %  |
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import List, Optional

# ─── Known PSU bank symbols (fallback when promoter_pct unavailable) ──────────
PSU_BANK_SYMBOLS: frozenset[str] = frozenset({
    "SBIN", "PNB", "BANKBARODA", "CANBK", "UNIONBANK",
    "BANKINDIA", "INDIANB", "IOB", "MAHABANK", "UCOBANK",
    "J&KBANK",   # J&K government majority stake
})


def classify_bank(symbol: str, promoter_pct: Optional[float]) -> str:
    """Return 'PSU' or 'PRIVATE'.

    Uses promoter_pct first (Government of India typically holds > 40 %).
    Falls back to the static symbol list for banks where shareholding is missing.
    """
    if promoter_pct is not None and promoter_pct > 40.0:
        return "PSU"
    if symbol in PSU_BANK_SYMBOLS:
        return "PSU"
    return "PRIVATE"


# ─── Band normaliser ──────────────────────────────────────────────────────────

def _band(value: Optional[float], low: float, high: float, good_is_high: bool = True) -> float:
    """Linearly map value onto 0–100.

    Returns 50.0 if value is None (neutral — scorer stays unaffected by missing data).
    'low' and 'high' are the worst/best endpoints depending on good_is_high.
    """
    if value is None or math.isnan(value):
        return 50.0
    if good_is_high:
        if value <= low:
            return 0.0
        if value >= high:
            return 100.0
        return round((value - low) / (high - low) * 100.0, 2)
    else:
        if value <= low:
            return 100.0
        if value >= high:
            return 0.0
        return round((high - value) / (high - low) * 100.0, 2)


def _weighted(scores: list[tuple[float, float]]) -> float:
    """Weighted average of (score, weight) pairs. Weights need not sum to 1."""
    total_w = sum(w for _, w in scores)
    if total_w <= 0:
        return 50.0
    return round(sum(s * w for s, w in scores) / total_w, 2)


# ─── Asset Quality ────────────────────────────────────────────────────────────

def _gnpa_trend_score(
    gnpa_series: List[Optional[float]],
    bank_type: str,
) -> Optional[float]:
    """Score the GNPA trend using last 8 quarters of the series.

    Returns 0–100 where 100 = strongly improving.
    Returns None if fewer than 5 non-null values available.
    """
    vals = [v for v in gnpa_series if v is not None]
    if len(vals) < 5:
        return None

    # Use last 8 non-null values (series is oldest-first)
    recent = vals[-8:]
    # Simple linear regression slope as fraction of mean GNPA
    n = len(recent)
    mean_val = statistics.mean(recent)
    if mean_val == 0:
        return 50.0
    xs = list(range(n))
    mean_x = statistics.mean(xs)
    try:
        cov = sum((xs[i] - mean_x) * (recent[i] - mean_val) for i in range(n))
        var_x = sum((x - mean_x) ** 2 for x in xs)
        slope = cov / var_x if var_x > 0 else 0.0
    except Exception:
        return 50.0

    # Normalised slope: positive = rising (bad), negative = falling (good)
    norm_slope = slope / mean_val  # fraction per quarter, relative to mean GNPA

    # PSU banks have larger swings; use wider bands for turnaround detection
    if bank_type == "PSU":
        # Strongly improving: slope < -0.03/qtr (falling >3% of mean per quarter)
        # Strongly worsening: slope > +0.05/qtr
        score = _band(-norm_slope, low=-0.05, high=0.03, good_is_high=True)
    else:
        # Private banks: tighter bands — any deterioration is significant
        score = _band(-norm_slope, low=-0.03, high=0.02, good_is_high=True)

    return score


def score_asset_quality(
    gnpa_pct: Optional[float],
    nnpa_pct: Optional[float],
    gnpa_series: Optional[List[Optional[float]]],
    bank_type: str,
) -> Optional[float]:
    """Score asset quality 0–100.

    Returns None if GNPA data is entirely absent (signals missing data to caller,
    which will exclude this pillar and rescale other pillar weights).
    """
    if gnpa_pct is None and nnpa_pct is None:
        return None

    if bank_type == "PSU":
        # PSU: Government-backstopped; higher absolute GNPA is structurally tolerable.
        # 3% or below = clean; 12%+ = very stressed.
        s_gnpa = _band(gnpa_pct, low=3.0, high=12.0, good_is_high=False)
        # NNPA: 1% or below = well-provisioned; 6%+ = severe uncovered stress.
        s_nnpa = _band(nnpa_pct, low=1.0, high=6.0, good_is_high=False)
    else:
        # Private: Any GNPA above 1.5% is notable; above 5% is a red flag.
        s_gnpa = _band(gnpa_pct, low=1.5, high=5.0, good_is_high=False)
        # NNPA: 0.5% or below = well-provisioned; 3%+ = serious uncovered stress.
        s_nnpa = _band(nnpa_pct, low=0.5, high=3.0, good_is_high=False)

    # Implied PCR = (1 - NNPA/GNPA) × 100 — same interpretation for both types.
    pcr: Optional[float] = None
    if gnpa_pct and gnpa_pct > 0 and nnpa_pct is not None:
        pcr = (1.0 - nnpa_pct / gnpa_pct) * 100.0
    s_pcr = _band(pcr, low=55.0, high=85.0, good_is_high=True)

    # Trend
    s_trend: float = 50.0  # neutral default if series unavailable
    if gnpa_series:
        t = _gnpa_trend_score(gnpa_series, bank_type)
        if t is not None:
            s_trend = t

    if bank_type == "PSU":
        # Trend equally important as absolute level for PSU turnaround thesis.
        # GNPA 8%→5% is a massive positive for a PSU bank.
        return _weighted([
            (s_gnpa,  25.0),
            (s_nnpa,  25.0),
            (s_pcr,   25.0),
            (s_trend, 25.0),
        ])
    else:
        # Private: current level dominates; any deterioration is alarming.
        return _weighted([
            (s_gnpa,  40.0),
            (s_nnpa,  30.0),
            (s_pcr,   20.0),
            (s_trend, 10.0),
        ])


# ─── Profitability ────────────────────────────────────────────────────────────

def score_profitability(
    roe_pct: Optional[float],
    pat_margin_pct: Optional[float],
    pat_yoy_growth_pct: Optional[float],
    bank_type: str,
) -> float:
    """Score profitability 0–100.

    Uses PAT margin (PAT / total_income × 100) instead of cost-to-income because
    Screener.in's 'expenses' row for banks includes provisions, making raw C2I
    unreliable. PAT margin captures both operational efficiency and credit quality:
    a bank with heavy provisioning shows a lower PAT margin.
    """
    if bank_type == "PSU":
        # PSU banks structurally earn lower ROE; 15%+ is excellent.
        s_roe = _band(roe_pct, low=4.0, high=15.0, good_is_high=True)
        # PAT margin for PSU: 12%+ is good (lower baseline due to credit costs + wage costs)
        s_pm = _band(pat_margin_pct, low=8.0, high=22.0, good_is_high=True)
    else:
        # Private: ROE < 12% is poor, > 18% is exceptional.
        s_roe = _band(roe_pct, low=8.0, high=18.0, good_is_high=True)
        # Private banks should have higher PAT margins; HDFC ~21%, ICICI ~27%
        s_pm = _band(pat_margin_pct, low=12.0, high=28.0, good_is_high=True)

    # PAT YoY growth — same expectations (positive growth is good).
    s_growth = _band(pat_yoy_growth_pct, low=-10.0, high=25.0, good_is_high=True)

    return _weighted([
        (s_roe,    40.0),
        (s_pm,     35.0),
        (s_growth, 25.0),
    ])


# ─── Liability Franchise ──────────────────────────────────────────────────────

def score_liability_franchise(
    nii_retention_pct: Optional[float],
    fee_income_mix_pct: Optional[float],
    revenue_yoy_growth_pct: Optional[float],
    bank_type: str,
) -> float:
    """Score liability franchise 0–100.

    NII retention = NII / Gross Interest Earned × 100.
    Higher = bank pays less for deposits = better liability franchise (CASA proxy).
    Fee income mix = other_income / total_income × 100.
    """
    if bank_type == "PSU":
        # PSU banks have lower cost-of-funds advantage; 45%+ retention is excellent.
        s_nii = _band(nii_retention_pct, low=30.0, high=50.0, good_is_high=True)
        # Fee income mix: 10%+ decent for PSU banks
        s_fee = _band(fee_income_mix_pct, low=5.0, high=18.0, good_is_high=True)
    else:
        # Private: strong CASA franchise should retain >50% of gross interest earned.
        s_nii = _band(nii_retention_pct, low=35.0, high=58.0, good_is_high=True)
        # Private banks should earn >15% fee income (diversified revenue).
        s_fee = _band(fee_income_mix_pct, low=8.0, high=22.0, good_is_high=True)

    # Revenue growth YoY — both types want business growth.
    s_rev = _band(revenue_yoy_growth_pct, low=0.0, high=20.0, good_is_high=True)

    return _weighted([
        (s_nii, 50.0),
        (s_fee, 30.0),
        (s_rev, 20.0),
    ])


# ─── Earnings Quality ─────────────────────────────────────────────────────────

def score_earnings_quality(
    earnings_consistency: Optional[float],  # 0–100 from CV of PAT
    fee_income_mix_pct: Optional[float],
    bank_type: str,
) -> float:
    """Score earnings quality 0–100.

    PSU banks have lumpier earnings (write-backs, one-time provisions) so
    consistency is graded more leniently.
    """
    if bank_type == "PSU":
        # PSU earnings are inherently lumpy — penalise less for inconsistency.
        s_cons = _band(earnings_consistency, low=30.0, high=80.0, good_is_high=True)
    else:
        # Private banks should have smooth, predictable earnings.
        s_cons = _band(earnings_consistency, low=40.0, high=85.0, good_is_high=True)

    # Fee income contribution as a diversification quality signal.
    s_fee = _band(fee_income_mix_pct, low=5.0, high=20.0, good_is_high=True)

    return _weighted([
        (s_cons, 65.0),
        (s_fee,  35.0),
    ])


# ─── Growth ───────────────────────────────────────────────────────────────────

def score_growth(
    revenue_yoy_growth_pct: Optional[float],
    pat_yoy_growth_pct: Optional[float],
) -> float:
    """Score growth quality 0–100."""
    s_rev = _band(revenue_yoy_growth_pct, low=-5.0, high=20.0, good_is_high=True)
    s_pat = _band(pat_yoy_growth_pct, low=-10.0, high=25.0, good_is_high=True)
    return _weighted([(s_rev, 40.0), (s_pat, 60.0)])


# ─── Composite ────────────────────────────────────────────────────────────────

@dataclass
class BankQualityScore:
    asset_quality_score:        Optional[float]   # None = GNPA data absent
    profitability_score:        float
    liability_franchise_score:  float
    earnings_quality_score:     float
    growth_score:               float
    bank_quality_score:         float
    has_npa_data:               bool
    coverage_pct:               float
    bank_type:                  str
    pillar_weights:             dict = field(default_factory=dict)


# Pillar weights — must sum to 1.0
_WEIGHTS_WITH_NPA    = {"asset_quality": 0.30, "profitability": 0.25,
                        "liability_franchise": 0.20, "earnings_quality": 0.15, "growth": 0.10}
_WEIGHTS_WITHOUT_NPA = {"profitability": 0.33, "liability_franchise": 0.27,
                        "earnings_quality": 0.20, "growth": 0.20}


def compute_bank_quality_score(
    *,
    bank_type: str,
    gnpa_pct: Optional[float],
    nnpa_pct: Optional[float],
    gnpa_series: Optional[List[Optional[float]]],
    roe_pct: Optional[float],
    pat_margin_pct: Optional[float],
    pat_yoy_growth_pct: Optional[float],
    nii_retention_pct: Optional[float],
    fee_income_mix_pct: Optional[float],
    revenue_yoy_growth_pct: Optional[float],
    earnings_consistency: Optional[float],
) -> BankQualityScore:
    """Compute the bank quality score.

    Pillar structure:
        If GNPA data is available: 5-pillar model (Asset Quality 30%).
        If GNPA data is absent:    4-pillar model (Asset Quality excluded,
                                   remaining pillars rescaled to 100%).
    """
    aq = score_asset_quality(gnpa_pct, nnpa_pct, gnpa_series, bank_type)
    prof = score_profitability(roe_pct, pat_margin_pct, pat_yoy_growth_pct, bank_type)
    liab = score_liability_franchise(nii_retention_pct, fee_income_mix_pct, revenue_yoy_growth_pct, bank_type)
    eq = score_earnings_quality(earnings_consistency, fee_income_mix_pct, bank_type)
    grw = score_growth(revenue_yoy_growth_pct, pat_yoy_growth_pct)

    has_npa = aq is not None

    if has_npa:
        w = _WEIGHTS_WITH_NPA
        composite = round(
            aq * w["asset_quality"]
            + prof * w["profitability"]
            + liab * w["liability_franchise"]
            + eq * w["earnings_quality"]
            + grw * w["growth"],
            2,
        )
        coverage = _compute_coverage(gnpa_pct, nnpa_pct, roe_pct, pat_margin_pct,
                                     nii_retention_pct, fee_income_mix_pct,
                                     revenue_yoy_growth_pct, pat_yoy_growth_pct, earnings_consistency)
    else:
        w = _WEIGHTS_WITHOUT_NPA
        composite = round(
            prof * w["profitability"]
            + liab * w["liability_franchise"]
            + eq * w["earnings_quality"]
            + grw * w["growth"],
            2,
        )
        coverage = _compute_coverage(None, None, roe_pct, pat_margin_pct,
                                     nii_retention_pct, fee_income_mix_pct,
                                     revenue_yoy_growth_pct, pat_yoy_growth_pct, earnings_consistency)

    return BankQualityScore(
        asset_quality_score=aq,
        profitability_score=prof,
        liability_franchise_score=liab,
        earnings_quality_score=eq,
        growth_score=grw,
        bank_quality_score=composite,
        has_npa_data=has_npa,
        coverage_pct=coverage,
        bank_type=bank_type,
        pillar_weights=w,
    )


def _compute_coverage(*values) -> float:
    """Fraction of metrics that are non-null → 0–100."""
    have = sum(1 for v in values if v is not None)
    total = len(values)
    return round(100.0 * have / total, 1) if total > 0 else 0.0
