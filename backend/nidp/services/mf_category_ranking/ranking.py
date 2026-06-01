"""Core ranking engine for mf_category_ranking.

Implements the canonical algorithm from docs/prd/MF_COMPOSITE_SCORING.prd:
  1. Percentile-normalise each metric within the category peer set
  2. Compute weighted composite with re-normalised denominator for null metrics
  3. Apply coverage gate (W_i < W_min → insufficient_coverage)
  4. Rank the composite once with deterministic tie-breaks
  5. Flag tiny categories (N < min_peers → low_confidence)
  6. Build metric_contributions JSONB for auditability

Correctness rules (§7):
  AC-01 — Never average per-metric ranks  (§7.1)
  AC-02 — Invert lower-is-better metrics  (§7.2)
  AC-04 — Re-normalise denominator for nulls, never zero-fill  (§7.4)
  AC-05 — Coverage gate  (§5.3)
  AC-06 — Deterministic tie-breaks  (§2 goal)
  AC-07 — Boundary correctness (best=100, worst=0, N=1 handled)  (§10.7)
  AC-08 — metric_contributions sums to composite ±0.01  (§10.8)
  AC-10 — low_confidence flag  (§7.6)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from .config import FamilyConfig, RankingConfig
from .peer_set import FundMetrics


# Status enum values (string to match DB CHECK constraint)
STATUS_RANKED             = "ranked"
STATUS_LOW_CONFIDENCE     = "low_confidence"
STATUS_INSUF_HISTORY      = "insufficient_history"
STATUS_INSUF_COVERAGE     = "insufficient_coverage"


@dataclass
class RankedFund:
    scheme_code: str
    scheme_name: str
    sebi_category: str
    composite: Optional[float]
    category_rank: Optional[int]
    category_pct: Optional[float]
    category_size: int
    metric_contributions: Dict[str, Any]
    status: str
    last_ranked_at: datetime
    data_as_of: date
    # Internal tie-break helpers (not persisted)
    _sharpe: Optional[float] = field(default=None, repr=False)
    _return_3y: Optional[float] = field(default=None, repr=False)
    _aum_cr: Optional[float] = field(default=None, repr=False)


def rank_category(
    funds: List[FundMetrics],
    family_config: Optional[FamilyConfig],
    config: RankingConfig,
    rank_date: date,
) -> List[RankedFund]:
    """Rank all funds in one sebi_category peer set.

    Args:
        funds:         List of FundMetrics for a single sebi_category.
        family_config: Weight/direction config for this family, or None if
                       no config exists (all funds → insufficient_coverage).
        config:        Global thresholds.
        rank_date:     The ranking date (for last_ranked_at, data_as_of fallback).

    Returns:
        List of RankedFund, one per input fund.  All input funds appear in
        the output — insufficient_history and insufficient_coverage funds
        are emitted with null composite/rank.
    """
    now = datetime.now(tz=timezone.utc)
    sebi_category = funds[0].sebi_category if funds else "Unknown"

    # ── Separate rankable from history-excluded ─────────────────────────
    rankable: List[FundMetrics] = []
    history_excluded: List[FundMetrics] = []

    for f in funds:
        if f.nav_count < config.min_history_bars:
            history_excluded.append(f)
        else:
            rankable.append(f)

    N = len(rankable)

    # ── Build output for history-excluded funds ─────────────────────────
    result: List[RankedFund] = []
    for f in history_excluded:
        result.append(RankedFund(
            scheme_code=f.scheme_code,
            scheme_name=f.scheme_name,
            sebi_category=sebi_category,
            composite=None,
            category_rank=None,
            category_pct=None,
            category_size=N,
            metric_contributions={},
            status=STATUS_INSUF_HISTORY,
            last_ranked_at=now,
            data_as_of=f.data_as_of or rank_date,
        ))

    if N == 0 or family_config is None:
        # No rankable funds or no weight config for this family
        for f in rankable:
            result.append(RankedFund(
                scheme_code=f.scheme_code,
                scheme_name=f.scheme_name,
                sebi_category=sebi_category,
                composite=None,
                category_rank=None,
                category_pct=None,
                category_size=0,
                metric_contributions={},
                status=STATUS_INSUF_COVERAGE,
                last_ranked_at=now,
                data_as_of=f.data_as_of or rank_date,
            ))
        return result

    weights = family_config.weights

    # ── Step 1: compute per-metric percentile scores within peer set ─────
    # For each metric, collect non-null values and assign average-rank percentiles.
    #
    # higher-is-better: pct = (rank_i - 1) / (N_m - 1) * 100   (best = 100)
    # lower-is-better:  pct = 100 - (rank_i - 1) / (N_m - 1) * 100
    #
    # Ties → average rank (scipy-style 'average').
    # NaN values are treated as None (excluded from percentile computation).

    # Collect metric values per fund, treating NaN as None
    fund_metric_values: List[Dict[str, Optional[float]]] = []
    for f in rankable:
        raw = f.metrics_dict()
        clean = {}
        for k, v in raw.items():
            if v is None or (isinstance(v, float) and math.isnan(v)):
                clean[k] = None
            else:
                clean[k] = v
        fund_metric_values.append(clean)

    # Per-metric percentile scores: {metric: [pct_for_fund_0, pct_for_fund_1, ...]}
    metric_pcts: Dict[str, List[Optional[float]]] = {}

    for metric in weights:
        values: List[Optional[float]] = [fmv.get(metric) for fmv in fund_metric_values]
        non_null_indexed = [(i, v) for i, v in enumerate(values) if v is not None]
        N_m = len(non_null_indexed)

        pcts: List[Optional[float]] = [None] * N

        if N_m == 0:
            metric_pcts[metric] = pcts
            continue

        if N_m == 1:
            # Only one fund with this metric — assign 100 (it's the best and worst)
            idx = non_null_indexed[0][0]
            pcts[idx] = 100.0
            metric_pcts[metric] = pcts
            continue

        # Sort by value ascending, compute average rank (ties → average rank)
        sorted_pairs = sorted(non_null_indexed, key=lambda p: p[1])

        # Build value → average_rank mapping
        # Group consecutive ties
        i = 0
        rank_map: Dict[int, float] = {}  # fund index → rank (1-based, fractional for ties)
        while i < len(sorted_pairs):
            j = i
            # Find all ties at sorted_pairs[i][1]
            while j < len(sorted_pairs) and sorted_pairs[j][1] == sorted_pairs[i][1]:
                j += 1
            # Ranks from i+1 to j, average = (i+1 + j) / 2
            avg_rank = (i + 1 + j) / 2.0
            for k in range(i, j):
                rank_map[sorted_pairs[k][0]] = avg_rank
            i = j

        lower_is_better = family_config.lower_is_better(metric)
        denom = N_m - 1  # always >= 1 since N_m >= 2

        for fund_idx, rank_1based in rank_map.items():
            raw_pct = (rank_1based - 1) / denom * 100.0
            if lower_is_better:
                pcts[fund_idx] = 100.0 - raw_pct
            else:
                pcts[fund_idx] = raw_pct

        metric_pcts[metric] = pcts

    # ── Step 2: Weighted composite with re-normalised denominator ────────
    composites: List[Optional[float]] = []
    w_is: List[float] = []
    contributions_list: List[Dict[str, Any]] = []

    for fund_idx in range(N):
        contrib: Dict[str, Any] = {}
        w_i = 0.0
        weighted_sum = 0.0

        for metric, weight in weights.items():
            pct = metric_pcts[metric][fund_idx]
            raw_value = fund_metric_values[fund_idx].get(metric)
            contribution = None
            if pct is not None:
                contribution = weight * pct
                w_i += weight
                weighted_sum += contribution
            contrib[metric] = {
                "value": raw_value,
                "pct": round(pct, 4) if pct is not None else None,
                "weight": weight,
                "contribution": round(contribution, 4) if contribution is not None else None,
            }

        w_is.append(w_i)
        contributions_list.append(contrib)

        if w_i < 1e-9:
            composites.append(None)
        else:
            composites.append(round(weighted_sum / w_i, 2))

    # ── Step 3: Coverage gate  (AC-05) ──────────────────────────────────
    # Funds with W_i < W_min are not rankable
    coverage_ok = [w >= config.w_min for w in w_is]
    rankable_composites = [
        (fund_idx, composites[fund_idx])
        for fund_idx in range(N)
        if coverage_ok[fund_idx] and composites[fund_idx] is not None
    ]

    N_ranked = len(rankable_composites)

    # ── Step 4: Sort and assign ranks  (AC-01, AC-06, AC-07) ────────────
    # Deterministic tie-break: composite desc → sharpe desc → return_3y desc →
    #                          aum_cr desc → scheme_code asc
    def _tie_key(item: tuple) -> tuple:
        fund_idx, comp = item
        f = rankable[fund_idx]
        sharpe  = f.sharpe_1y  if f.sharpe_1y  is not None and not math.isnan(f.sharpe_1y)  else -1e18
        ret_3y  = f.return_3y  if f.return_3y  is not None and not math.isnan(f.return_3y)  else -1e18
        aum     = f.aum_cr     if f.aum_cr     is not None and not math.isnan(f.aum_cr)     else -1e18
        code    = f.scheme_code
        return (-comp, -sharpe, -ret_3y, -aum, code)

    sorted_rankable = sorted(rankable_composites, key=_tie_key)

    # Competition rank: 1 + count(funds with strictly higher composite)
    rank_map_final: Dict[int, int] = {}
    for pos, (fund_idx, comp) in enumerate(sorted_rankable):
        # Count how many funds have strictly higher composite
        higher_count = sum(
            1 for _, c in rankable_composites
            if c is not None and comp is not None and c > comp
        )
        rank_map_final[fund_idx] = higher_count + 1

    low_confidence = N_ranked < config.min_peers

    # ── Step 5: Build output  (AC-07, AC-08, AC-10, AC-13) ──────────────
    # Build ranked funds first so we can set category_size correctly
    ranked_output: List[RankedFund] = []

    for fund_idx in range(N):
        f = rankable[fund_idx]
        comp = composites[fund_idx]
        w_i = w_is[fund_idx]
        contrib = contributions_list[fund_idx]
        data_as_of = f.data_as_of or rank_date

        if not coverage_ok[fund_idx]:
            ranked_output.append(RankedFund(
                scheme_code=f.scheme_code,
                scheme_name=f.scheme_name,
                sebi_category=sebi_category,
                composite=None,
                category_rank=None,
                category_pct=None,
                category_size=N_ranked,
                metric_contributions=contrib,
                status=STATUS_INSUF_COVERAGE,
                last_ranked_at=now,
                data_as_of=data_as_of,
                _sharpe=f.sharpe_1y,
                _return_3y=f.return_3y,
                _aum_cr=f.aum_cr,
            ))
            continue

        cat_rank = rank_map_final.get(fund_idx)

        # category_pct = (N_ranked − rank) / (N_ranked − 1) × 100
        # Special case N_ranked == 1: pct = 100.0 (only fund → best and worst)
        if cat_rank is not None and N_ranked > 0:
            if N_ranked == 1:
                cat_pct = 100.0
            else:
                cat_pct = round((N_ranked - cat_rank) / (N_ranked - 1) * 100.0, 2)
        else:
            cat_pct = None

        status = STATUS_LOW_CONFIDENCE if low_confidence else STATUS_RANKED

        ranked_output.append(RankedFund(
            scheme_code=f.scheme_code,
            scheme_name=f.scheme_name,
            sebi_category=sebi_category,
            composite=comp,
            category_rank=cat_rank,
            category_pct=cat_pct,
            category_size=N_ranked,
            metric_contributions=contrib,
            status=status,
            last_ranked_at=now,
            data_as_of=data_as_of,
            _sharpe=f.sharpe_1y,
            _return_3y=f.return_3y,
            _aum_cr=f.aum_cr,
        ))

    result.extend(ranked_output)
    return result
