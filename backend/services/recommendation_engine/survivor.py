"""Canonical keep_score — single source of truth for survivor designation.

Used by: overlap_engine, correlation_engine, same_category_engine,
         underperformer_engine, and the reconcile_bucket orchestrator pre-pass.

D-2 decisions (2026-06-03):
  - All signals normalised to [0,1] within the comparison set (min-max)
    before weighting, so weights express relative importance, not scale.
  - is_direct_plan removed from keep_score (plan type is a within-fund
    switch decision, not a between-fund keep/exit decision — avoids
    unfairly penalising strong regular-plan funds vs weak direct-plan ones).
  - AMC cap breach → hard constraint (−∞), not an additive penalty.
  - Weights: perf=35, cost=30, overlap=15, amc_quality=20. Sum=100.
  - When overlap data unavailable (scrapers down):
      w_overlap set to 0, remaining 15pp redistributed proportionally,
      AND a data_quality_warning is surfaced.

Signal definitions:
  risk_adj_perf     — Sharpe / Sortino-based risk-adjusted return vs benchmark,
                      measured over 3–5yr rolling windows. Higher = better.
  expense_ratio     — Actual plan's TER in %. Lower = better (inverted in score).
  overlap_contrib   — Pairwise overlap with other held funds. Lower = better (inverted).
  amc_quality       — NIDP quality_score (0–100). Higher = better.
  breaches_amc_cap  — Boolean. True → this fund cannot be a survivor regardless of score.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Canonical weights (sum = 100) — D-2 approved 2026-06-03
W_PERF    = 35
W_COST    = 30
W_OVERLAP = 15
W_AMC     = 20


# ── Raw signal extraction ────────────────────────────────────────────────────

def raw_signals(
    fund_id: Optional[str],
    v3_scores: Dict[str, Any],
    overlap_pct: Optional[float] = None,
    breaches_amc_cap: bool = False,
) -> Dict[str, Any]:
    """Extract raw (unnormalized) signals for one fund.

    Returns a dict with keys:
      risk_adj_perf, expense_ratio, overlap_contrib, amc_quality, breaches_amc_cap
    None values indicate missing data and are handled during normalisation.
    """
    v3 = v3_scores.get(fund_id or "", {}) if fund_id else {}
    prims = v3.get("v3_primitives") or {}

    # risk_adj_perf: Sharpe ratio if available, else derived from consistency + quality
    sharpe = prims.get("sharpe") or prims.get("sharpe_ratio")
    if sharpe is not None:
        risk_adj = float(sharpe)
    else:
        # Fallback: scale from quality_score (0-100) to a Sharpe-comparable range (-2 to +2)
        qs = v3.get("quality_score")
        risk_adj = ((float(qs) / 100.0) * 4.0 - 2.0) if qs is not None else None

    # expense_ratio: prefer actual TER; fall back to direct-plan TER
    er = (
        prims.get("expense_ratio")
        or prims.get("expense_ratio_actual")
        or prims.get("expense_ratio_direct")
    )
    expense_ratio = float(er) if er is not None else None

    # amc_quality: NIDP quality_score (0-100)
    qs = v3.get("quality_score")
    amc_quality = float(qs) if qs is not None else None

    return {
        "risk_adj_perf":   risk_adj,
        "expense_ratio":   expense_ratio,
        "overlap_contrib": float(overlap_pct) if overlap_pct is not None else None,
        "amc_quality":     amc_quality,
        "breaches_amc_cap": bool(breaches_amc_cap),
    }


# ── Batch normalization ──────────────────────────────────────────────────────

def _norm_column(
    values: List[Optional[float]],
    invert: bool = False,
) -> List[float]:
    """Min-max normalize a list to [0,1].

    None values receive 0.5 (neutral, not zero).
    All-equal or single-item lists return 0.5 for all entries.
    When invert=True the scale is flipped so lower raw = higher normalized score.
    """
    valid = [v for v in values if v is not None]
    if not valid or len(valid) == 1:
        # Can't normalize a single point — assign neutral
        return [0.5 if v is not None else 0.5 for v in values]
    mn, mx = min(valid), max(valid)
    if mx == mn:
        return [0.5 for _ in values]
    result = []
    for v in values:
        if v is None:
            result.append(0.5)
        else:
            normed = (v - mn) / (mx - mn)
            result.append(1.0 - normed if invert else normed)
    return result


def normalize_signals_batch(
    raw_list: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, float]], bool]:
    """Normalize a batch of raw signal dicts to [0,1] per signal column.

    Returns (normalized_list, overlap_available).
    overlap_available=False when all overlap values are None — caller should
    surface data_quality_warning and redistribute the overlap weight.
    """
    perfs    = [r["risk_adj_perf"] for r in raw_list]
    costs    = [r["expense_ratio"] for r in raw_list]
    overlaps = [r["overlap_contrib"] for r in raw_list]
    amcs     = [r["amc_quality"] for r in raw_list]

    perf_n    = _norm_column(perfs)
    cost_n    = _norm_column(costs,    invert=True)   # lower cost → higher score
    overlap_n = _norm_column(overlaps, invert=True)   # lower overlap → higher score
    amc_n     = _norm_column(amcs)

    overlap_available = any(v is not None for v in overlaps)

    normalized = []
    for i, r in enumerate(raw_list):
        normalized.append({
            "risk_adj_perf":   perf_n[i],
            "expense_ratio":   cost_n[i],
            "overlap_contrib": overlap_n[i],
            "amc_quality":     amc_n[i],
            "breaches_amc_cap": r["breaches_amc_cap"],
        })
    return normalized, overlap_available


# ── Score computation ────────────────────────────────────────────────────────

def keep_score_normalized(norm: Dict[str, float], overlap_available: bool = True) -> float:
    """Compute keep_score from a normalized signal dict.

    Returns -inf for AMC cap breaches (hard constraint — cannot be a survivor).
    Returns 0–100 otherwise.
    """
    if norm.get("breaches_amc_cap"):
        return float("-inf")

    if overlap_available:
        w_p, w_c, w_o, w_a = W_PERF, W_COST, W_OVERLAP, W_AMC
    else:
        # Overlap unavailable: redistribute w_overlap proportionally
        total_without = W_PERF + W_COST + W_AMC  # 85
        w_p = W_PERF  * 100 / total_without
        w_c = W_COST  * 100 / total_without
        w_o = 0.0
        w_a = W_AMC   * 100 / total_without

    return (
        w_p * norm["risk_adj_perf"]
      + w_c * norm["expense_ratio"]
      + w_o * norm["overlap_contrib"]
      + w_a * norm["amc_quality"]
    )


# ── sell_score (D-3, approved 2026-06-03) ────────────────────────────────────
# Separate from keep_score — "good fund to keep" and "cheap to sell now" are
# different questions.  A strong fund in a short-term lot should be kept;
# a mediocre fund with no exit friction should be sold first.
#
# Weights (approved):
#   a1 overlap_with_survivor  30  — most redundant → sell first
#   a2 expense_ratio          25  — cost drag is deterministic
#   a3 low_quality_score      25  — persistent underperformance proxy
#   a4 is_regular_plan        20  — switch to direct anyway
#   b1 exit_load_active      −20  — out-of-pocket cash cost
#   b2 is_short_term_lot     −30  — STCG at 15-20% is significant
#   b3 unrealized_gain_tax   −25  — scales with actual tax liability
#   b4 lock_in               hard block (−∞) — handled by ArbitrationEngine


def sell_signals(
    instrument_id: Optional[str],
    v3_scores: dict,
    holding: Optional[dict] = None,
    overlap_with_survivor_pct: Optional[float] = None,
    estimated_tax_rs: float = 0.0,
    total_value_rs: float = 0.0,
) -> dict:
    """Extract raw sell signals for one fund.

    Returns a dict with keys matching the sell_score formula.
    None values mean data is unavailable; handled during normalization.
    """
    v3 = v3_scores.get(instrument_id or "", {}) if instrument_id else {}
    prims = v3.get("v3_primitives") or {}
    h = holding or {}

    # a1: overlap with survivor (higher = more redundant = sell first)
    overlap = float(overlap_with_survivor_pct) if overlap_with_survivor_pct is not None else None

    # a2: expense ratio (higher cost = sell first)
    er = (
        prims.get("expense_ratio")
        or prims.get("expense_ratio_actual")
        or prims.get("expense_ratio_direct")
    )
    expense_ratio = float(er) if er is not None else None

    # a3: low quality (inverted quality_score — low quality = sell first)
    qs = v3.get("quality_score")
    low_quality = (100.0 - float(qs)) if qs is not None else None  # invert: low quality → high sell signal

    # a4: is_regular_plan (1 if regular, 0 if direct)
    plan = (h.get("plan_type") or "").lower()
    is_regular = 1.0 if "regular" in plan or "regular" in (h.get("scheme_name") or "").lower() else 0.0

    # b1: exit load active (1 if exit load > 0%)
    el = h.get("exit_load") or h.get("exit_load_pct") or 0.0
    exit_load = 1.0 if float(el or 0) > 0 else 0.0

    # b2: is_short_term_lot (bought < 12 months ago)
    is_short_term = 0.0
    try:
        from datetime import date as _date
        pd_str = h.get("purchase_date") or h.get("nav_date")
        if pd_str:
            pd = _date.fromisoformat(str(pd_str)[:10])
            days_held = (_date.today() - pd).days
            is_short_term = 1.0 if days_held < 365 else 0.0
    except Exception:
        pass

    # b3: unrealized gain tax — normalized by portfolio value if available
    tax_fraction = 0.0
    if estimated_tax_rs > 0 and total_value_rs > 0:
        tax_fraction = min(1.0, estimated_tax_rs / total_value_rs)  # 0-1 relative to portfolio

    return {
        "overlap_with_survivor": overlap,
        "expense_ratio":         expense_ratio,
        "low_quality":           low_quality,
        "is_regular_plan":       is_regular,
        "exit_load_active":      exit_load,
        "is_short_term_lot":     is_short_term,
        "unrealized_gain_tax":   tax_fraction,
    }


def sell_score(raw: dict) -> float:
    """Compute sell_score from raw (already-normalized or binary) signals.

    Returns higher = sell this first.
    Signals that are None contribute 0 (neutral, not zero).
    """
    def _v(key: str, default: float = 0.5) -> float:
        v = raw.get(key)
        return float(v) if v is not None else default

    # Binary signals (0/1) don't need normalization — they're already 0-1
    # Continuous signals (overlap, expense_ratio, low_quality) benefit from
    # cross-set normalization, but sell_score is typically applied to a small
    # exit candidate set (2-5 funds); use raw values scaled to [0,1].
    a1 = 30 * _v("overlap_with_survivor")
    a2 = 25 * _v("expense_ratio", 0.5)  # 0.5 neutral when unknown
    a3 = 25 * _v("low_quality",   0.5)
    a4 = 20 * _v("is_regular_plan", 0.0)  # default: assume direct (safer)

    b1 = 20 * _v("exit_load_active",    0.0)
    b2 = 30 * _v("is_short_term_lot",   0.0)
    b3 = 25 * _v("unrealized_gain_tax", 0.0)

    return (a1 + a2 + a3 + a4) - (b1 + b2 + b3)


def sort_exits_by_sell_score(
    exit_signals: list,
    v3_scores: dict,
    overlap_data: Optional[dict] = None,
    total_value_rs: float = 0.0,
) -> list:
    """Sort a list of EXIT EngineSignals by sell_score (highest = sell first).

    Returns the same list, sorted in place (also returns it for chaining).
    """
    overlaps = overlap_data or {}

    def _score(sig) -> float:
        holding = sig.__dict__.get("_holding") or {}
        raw = sell_signals(
            instrument_id=sig.instrument_id,
            v3_scores=v3_scores,
            holding=holding,
            overlap_with_survivor_pct=overlaps.get(sig.instrument_id),
            estimated_tax_rs=sig.estimated_tax_rs,
            total_value_rs=total_value_rs,
        )
        return sell_score(raw)

    exit_signals.sort(key=_score, reverse=True)
    return exit_signals


# ── High-level API ───────────────────────────────────────────────────────────

def select_survivors(
    fund_ids: List[str],
    n: int,
    v3_scores: Dict[str, Any],
    overlap_data: Optional[Dict[str, float]] = None,
    amc_cap_breaches: Optional[set] = None,
) -> Tuple[List[str], List[str], bool]:
    """Select the top-n survivor funds from a list.

    Args:
        fund_ids:         All fund IDs in this bucket.
        n:                Number of survivors to keep (FUNDS_PER_BUCKET value).
        v3_scores:        ctx.v3_scores dict from the orchestrator context.
        overlap_data:     Optional {fund_id: overlap_pct} for the portfolio.
        amc_cap_breaches: Set of fund_ids that breach the AMC concentration cap.

    Returns:
        (survivors, exits, overlap_available)
        survivors: fund_ids to keep (length ≤ n)
        exits:     fund_ids to exit (length ≥ 0)
        overlap_available: False when overlap data absent (data_quality_warning should fire)
    """
    if not fund_ids:
        return [], [], True
    if n >= len(fund_ids):
        return list(fund_ids), [], True

    breaches = amc_cap_breaches or set()
    overlaps = overlap_data or {}

    raw_list = [
        raw_signals(
            fid,
            v3_scores,
            overlap_pct=overlaps.get(fid),
            breaches_amc_cap=(fid in breaches),
        )
        for fid in fund_ids
    ]

    normalized, overlap_available = normalize_signals_batch(raw_list)

    scored = [
        (keep_score_normalized(norm, overlap_available), fid)
        for fid, norm in zip(fund_ids, normalized)
    ]
    scored.sort(key=lambda x: x[0], reverse=True)

    survivors = [fid for _, fid in scored[:n] if scored[scored.index((_, fid))][0] > float("-inf")]
    # If AMC cap constraints excluded some top funds, backfill from non-breaching tail
    if len(survivors) < n:
        extras = [fid for score, fid in scored[n:] if score > float("-inf")]
        survivors += extras[:n - len(survivors)]

    exits = [fid for fid in fund_ids if fid not in survivors]

    if not overlap_available:
        logger.info(
            "survivor.select_survivors: overlap data unavailable — using cost+perf+amc only. "
            "Surface data_quality_warning to user."
        )

    return survivors, exits, overlap_available
