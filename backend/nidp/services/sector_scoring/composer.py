"""Sector-aware score composer.

Assembles the final V3 score from:
  - Sector-specific fundamental sub-score
  - Cross-sector technical sub-score
  - Cycle position sub-score (CYCLICAL only)
  - Event overlay (time-decayed positive/negative events)
  - Red-flag penalties (binary hard penalties)

Final formula (PRD §9):
    Final = MIN(100, MAX(0,
        (Fundamental × Fund_Weight) +
        (Technical   × Tech_Weight) +
        (CyclePos    × Cycle_Weight) +
        Event_Overlay −
        Red_Flag_Penalty
    ))

Band assignment (PRD §9.2): sector-relative (absolute score combined with
sector rank percentile when peer data is available).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from .classifier import (
    BANK, NBFC, CYCLICAL, IT, FMCG, PHARMA, CAPGOODS, DEFAULT,
    classify,
)
from .coverage import check_coverage
from .governance import score_governance
from .normalizers import weighted
from .technical import score_technical

from .profiles.bank     import score_fundamental_bank
from .profiles.nbfc     import score_fundamental_nbfc
from .profiles.it       import score_fundamental_it
from .profiles.fmcg     import score_fundamental_fmcg
from .profiles.cyclical import score_fundamental_cyclical, score_cycle_position
from .profiles.pharma   import score_fundamental_pharma
from .profiles.capgoods import score_fundamental_capgoods
from .profiles.default  import score_fundamental_default


# ── Sector composite weights ──────────────────────────────────────────────────
# (fund_weight, tech_weight, cycle_weight) — must sum to 1.0
_WEIGHTS: Dict[str, tuple[float, float, float]] = {
    BANK:     (0.70, 0.30, 0.00),
    NBFC:     (0.70, 0.30, 0.00),
    IT:       (0.70, 0.30, 0.00),
    FMCG:     (0.75, 0.25, 0.00),
    PHARMA:   (0.70, 0.30, 0.00),
    CYCLICAL: (0.50, 0.30, 0.20),
    CAPGOODS: (0.60, 0.40, 0.00),
    DEFAULT:  (0.65, 0.35, 0.00),
}

# ── Band thresholds ───────────────────────────────────────────────────────────
STRONG_BUY = "STRONG_BUY"
BUY        = "BUY"
HOLD       = "HOLD"
REDUCE     = "REDUCE"
AVOID      = "AVOID"

# Hard triggers that immediately assign AVOID regardless of score
_AVOID_TRIGGERS = frozenset({
    "RBI_PCA_ACTION", "IMPORT_ALERT", "AUDITOR_RESIGNATION",
    "SEBI_ORDER", "CONSENT_DECREE",
})


@dataclass
class SectorScore:
    symbol:               str
    as_of_date:           date
    sector_profile:       str
    fundamental_score:    Optional[float]
    technical_score:      Optional[float]
    cycle_position_score: Optional[float]
    event_overlay:        float
    red_flag_penalty:     float
    final_score:          Optional[float]
    band:                 Optional[str]
    sub_scores:           Dict[str, Any] = field(default_factory=dict)
    coverage_pct:         float = 0.0
    # Data-quality diagnostics: which primitives are missing and which feed owns them
    missing_primitives:   List[str] = field(default_factory=list)
    missing_by_feed:      Dict[str, List[str]] = field(default_factory=dict)


def _assign_band(
    score: float,
    sector_rank_pct: Optional[float] = None,
    avoid_triggers: Optional[List[str]] = None,
) -> str:
    """Assign signal band per PRD §9.2.

    sector_rank_pct: percentile of this stock within its sector (0–100).
    Bands are sector-relative when rank available; fall back to absolute score.
    """
    if avoid_triggers:
        for trigger in avoid_triggers:
            if trigger in _AVOID_TRIGGERS:
                return AVOID

    if score < 35:
        return AVOID
    if score < 50:
        return REDUCE

    # Use sector-relative rank when available
    if sector_rank_pct is not None:
        if score >= 80 and sector_rank_pct >= 90:
            return STRONG_BUY
        if score >= 65 and sector_rank_pct >= 75:
            return BUY
        if score >= 50 and sector_rank_pct >= 25:
            return HOLD
        if sector_rank_pct < 25:
            return REDUCE
        return HOLD
    else:
        # Absolute fallback
        if score >= 80:
            return STRONG_BUY
        if score >= 65:
            return BUY
        return HOLD


def _compute_event_overlay(
    event_signals: List[Dict[str, Any]],
    as_of_date: date,
) -> tuple[float, float, List[Dict[str, Any]]]:
    """Compute net event_overlay and red_flag_penalty from corporate_event_signals.

    Returns (overlay, penalty, applied_events list).
    Overlay bounded: max +15, min -30 (before penalty separation).
    Penalty is non-decaying; overlay is time-decayed per PRD §8.3.
    """
    # Event boost/penalty table — (event_type, is_positive, magnitude, decay_days)
    _EVENT_TABLE: Dict[str, tuple[bool, float, int]] = {
        "EARNINGS_BEAT":             (True,  8.0,  30),
        "ACQUISITION_VALUE_ACCRETIVE": (True, 6.0,  60),
        "MAJOR_ORDER_WIN":           (True,  5.0,  45),
        "BUYBACK_ANNOUNCEMENT":      (True,  4.0,  90),
        "INSTITUTIONAL_BULK_BUY":    (True,  3.0,  14),
        "CREDIT_RATING_UPGRADE":     (True,  5.0,  90),
        "EARNINGS_MISS":             (False, -8.0,  30),
        "AUDITOR_RESIGNATION":       (False, -15.0, 180),
        "SEBI_ORDER":                (False, -20.0, 365),
        "KEY_MANAGEMENT_EXIT":       (False, -10.0, 90),
        "PROMOTER_PLEDGE_INCREASE":  (False, -10.0, 90),
        "INSTITUTIONAL_BULK_SELL":   (False, -5.0,  14),
        "CREDIT_RATING_DOWNGRADE":   (False, -10.0, 180),
        "RELATED_PARTY_TRANSACTION": (False, -8.0,  90),
    }

    overlay = 0.0
    penalty = 0.0
    applied: List[Dict[str, Any]] = []

    for ev in event_signals:
        event_type = ev.get("event_type", "")
        event_date_val = ev.get("event_date")
        if event_date_val is None:
            continue
        if isinstance(event_date_val, str):
            try:
                from datetime import date as _date
                event_date_val = _date.fromisoformat(event_date_val)
            except ValueError:
                continue

        config = _EVENT_TABLE.get(event_type)
        if not config:
            continue

        is_positive, magnitude, decay_days = config
        days_since = (as_of_date - event_date_val).days
        if days_since < 0 or days_since > decay_days:
            continue

        decay = max(0.0, 1.0 - days_since / decay_days)
        effective = magnitude * decay

        if is_positive:
            overlay += effective
        else:
            # Hard penalties go to penalty bucket (non-decaying for severe ones)
            if event_type in ("AUDITOR_RESIGNATION", "SEBI_ORDER"):
                penalty += abs(magnitude)  # full penalty regardless of age
            else:
                overlay += effective  # negative, decays

        applied.append({
            "event_type": event_type,
            "effective":  round(effective, 2),
            "days_since": days_since,
        })

    # Clamp overlay
    overlay = max(-30.0, min(15.0, overlay))
    return round(overlay, 2), round(penalty, 2), applied


def score_stock(
    symbol: str,
    as_of_date: date,
    prims: Dict[str, Any],
    tech_data: Optional[Dict[str, Any]] = None,
    bank_metrics: Optional[Dict[str, Any]] = None,
    event_signals: Optional[List[Dict[str, Any]]] = None,
    sector_rank_pct: Optional[float] = None,
) -> SectorScore:
    """Compute full sector-aware score for one stock.

    Args:
        prims:           v_v3_stock_primitives row (converted to dict).
        tech_data:       stock_features_daily row (sma50, sma200, deliv%, etc.)
        bank_metrics:    bank_metrics_daily row (for BANK sector only).
        event_signals:   List of corporate_event_signals rows (last 180 days).
        sector_rank_pct: Percentile within sector (computed by engine across peers).
    """
    tech_data   = tech_data or {}
    event_sigs  = event_signals or []

    # ── Classify sector ────────────────────────────────────────────────
    sector   = prims.get("sector")
    industry = prims.get("industry")
    profile  = classify(sector, industry)

    # ── Fundamental sub-score ──────────────────────────────────────────
    fund_sub: Dict[str, Any] = {}
    if profile == BANK:
        fund_score, fund_sub = score_fundamental_bank(prims, bank_metrics)
    elif profile == NBFC:
        fund_score, fund_sub = score_fundamental_nbfc(prims)
    elif profile == IT:
        fund_score, fund_sub = score_fundamental_it(prims)
    elif profile == FMCG:
        fund_score, fund_sub = score_fundamental_fmcg(prims)
    elif profile == CYCLICAL:
        fund_score, fund_sub = score_fundamental_cyclical(prims)
    elif profile == PHARMA:
        # Pass pharma-relevant event signals
        pharma_es = _extract_pharma_signals(event_sigs)
        fund_score, fund_sub = score_fundamental_pharma(prims, pharma_es)
    elif profile == CAPGOODS:
        capgoods_es = _extract_capgoods_signals(event_sigs)
        fund_score, fund_sub = score_fundamental_capgoods(prims, capgoods_es)
    else:
        fund_score, fund_sub = score_fundamental_default(prims)

    # ── Technical sub-score ────────────────────────────────────────────
    tech_score, tech_sub = score_technical(prims, tech_data)

    # ── Cycle position (CYCLICAL only) ─────────────────────────────────
    cycle_score: Optional[float] = None
    cycle_sub: Dict[str, Any] = {}
    if profile == CYCLICAL:
        cycle_score, cycle_sub = score_cycle_position(prims)

    # ── Event overlay ─────────────────────────────────────────────────
    event_overlay, red_flag_penalty, applied_events = _compute_event_overlay(
        event_sigs, as_of_date
    )

    # ── Composite final score ─────────────────────────────────────────
    fw, tw, cw = _WEIGHTS.get(profile, (0.65, 0.35, 0.0))

    if cycle_score is not None:
        raw = fund_score * fw + tech_score * tw + cycle_score * cw
    else:
        # Redistribute cycle weight proportionally to fund + tech
        total = fw + tw
        raw = fund_score * (fw / total) + tech_score * (tw / total)

    final = max(0.0, min(100.0, raw + event_overlay - red_flag_penalty))
    final = round(final, 2)

    # ── Band ──────────────────────────────────────────────────────────
    avoid_triggers = [e["event_type"] for e in event_sigs
                      if e.get("event_type") in _AVOID_TRIGGERS]
    band = _assign_band(final, sector_rank_pct, avoid_triggers)

    # ── Sub-scores JSON ───────────────────────────────────────────────
    sub_scores = {
        "sector_profile":  profile,
        "fundamental":     {"score": round(fund_score, 2), "pillars": fund_sub},
        "technical":       {"score": round(tech_score, 2), "pillars": tech_sub},
        "weights":         {"fundamental": fw, "technical": tw, "cycle": cw},
        "event_overlay":   event_overlay,
        "applied_events":  applied_events,
        "red_flag_penalty": red_flag_penalty,
    }
    if cycle_score is not None:
        sub_scores["cycle_position"] = {"score": round(cycle_score, 2), "pillars": cycle_sub}

    # ── Data quality: check which primitives are missing ─────────────
    cov = check_coverage(profile, prims, tech_data, bank_metrics)
    sub_scores["missing_primitives"] = cov.missing
    sub_scores["missing_by_feed"]    = cov.missing_by_feed

    return SectorScore(
        symbol=symbol,
        as_of_date=as_of_date,
        sector_profile=profile,
        fundamental_score=round(fund_score, 2),
        technical_score=round(tech_score, 2),
        cycle_position_score=round(cycle_score, 2) if cycle_score is not None else None,
        event_overlay=event_overlay,
        red_flag_penalty=red_flag_penalty,
        final_score=final,
        band=band,
        sub_scores=sub_scores,
        coverage_pct=cov.coverage_pct,
        missing_primitives=cov.missing,
        missing_by_feed=cov.missing_by_feed,
    )


def _extract_pharma_signals(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    types = {e.get("event_type") for e in events}
    return {
        "has_import_alert":           "IMPORT_ALERT" in types,
        "has_warning_letter_core":    "USFDA_WARNING_LETTER_CORE" in types,
        "has_warning_letter_noncore": "USFDA_WARNING_LETTER_NONCORE" in types,
    }


def _extract_capgoods_signals(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    types = {e.get("event_type") for e in events}
    return {
        "has_major_order_win":   "MAJOR_ORDER_WIN" in types,
        "has_large_project_delay": "LARGE_PROJECT_DELAY_DISCLOSED" in types,
        "has_receivables_spike": "RECEIVABLES_OVER_180_DAYS" in types,
    }


