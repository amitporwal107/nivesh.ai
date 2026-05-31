"""
GoalAlignmentEngine — Goal-aware portfolio signals (GA-1..GA-4).

GA-1: Equity allocation > horizon-based ceiling → TRIM signal.
      Ceilings: <2y=20%, 2-5y=50%, 5-10y=75%, >10y=90%.
GA-2: Horizon < 5y AND smallcap > 20% → TRIM/EXIT smallcap exposure.
GA-3: RETIREMENT goal with horizon < 10y → glide-path rebalance signal.
GA-4: Goal is critical/at_risk → EXIT worst candidate + ADD missing asset class.

These signals carry goal_impact=1.0 for critical goals, so ArbitrationEngine
(AR-1) will prefer them over competing signals for the same holding.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from services.recommendation_engine.base_engine import BaseEngine
from services.recommendation_engine.context import EngineSignal, RecommendationContext

logger = logging.getLogger(__name__)

# Equity ceiling by horizon bucket (rule book §10.8 GA-1)
# Bands: <3y / 3-5y / 5-10y / >10y
_EQUITY_CEILING: List[tuple[float, float]] = [
    (3.0,   20.0),   # horizon < 3y  → max 20% equity
    (5.0,   50.0),   # horizon < 5y  → max 50%
    (10.0,  75.0),   # horizon < 10y → max 75%
    (999.0, 90.0),   # otherwise     → max 90%
]

_GOAL_DEBT_FUND = "HDFC Corporate Bond Fund - Direct Plan - Growth"
_GOAL_EQUITY_FUND = "Parag Parikh Flexi Cap Fund - Direct Growth"


def _equity_ceiling(horizon_years: float) -> float:
    for h, ceiling in _EQUITY_CEILING:
        if horizon_years < h:
            return ceiling
    return 90.0


def _portfolio_equity_pct(ctx: RecommendationContext) -> float:
    """Portfolio-level equity % from PI asset_allocation, falling back to holding count heuristic."""
    alloc = (ctx.portfolio_intelligence.get("asset_allocation") or {})
    if alloc.get("equity_pct") is not None:
        return float(alloc["equity_pct"])
    # Heuristic: equity value / total
    equity_rs = sum(
        float(h.get("quantity", 0)) * float(h.get("current_price", 0))
        for h in ctx.holdings
        if (h.get("asset_type") or "").lower() in ("equity", "stock", "mutual_fund", "etf")
    )
    return (equity_rs / ctx.total_value_rs * 100.0) if ctx.total_value_rs > 0 else 0.0


def _smallcap_pct(ctx: RecommendationContext) -> float:
    """Smallcap % of MF portfolio from category breakdown."""
    mf_investments = ctx.portfolio_intelligence.get("mf_investments") or []
    total_mf = sum(float(m.get("amount_rs", 0)) for m in mf_investments) or 1.0
    sc_rs = sum(
        float(m.get("amount_rs", 0)) for m in mf_investments
        if "small cap" in (m.get("category") or "").lower()
    )
    return sc_rs / total_mf * 100.0


class GoalAlignmentEngine(BaseEngine):
    """Emit goal-driven signals; critical-goal signals win arbitration (AR-1)."""

    engine_name = "GoalAlignmentEngine"

    def generate(self, ctx: RecommendationContext) -> List[EngineSignal]:
        if not ctx.goal_evaluations:
            return []

        signals: List[EngineSignal] = []
        local_exited_ids: set = set()

        equity_pct = _portfolio_equity_pct(ctx)
        smallcap_pct_val = _smallcap_pct(ctx)

        for eval_ in ctx.goal_evaluations:
            # Resolve fields — support both GoalEvaluation dataclass and plain dict wrappers
            if isinstance(eval_, dict):
                health        = eval_.get("goal_health") or eval_.get("health_status") or ""
                on_track_pct  = float(eval_.get("on_track_pct") or eval_.get("on_track_probability_pct") or 50.0)
                goal_name     = eval_.get("goal_name") or eval_.get("name") or "Goal"
                goal_gap_rs   = float(eval_.get("shortfall_rs") or eval_.get("gap_rs") or 0)
                horizon_years = float(eval_.get("horizon_years") or 10.0)
                goal_type     = (eval_.get("goal_type") or eval_.get("type") or "").upper()
            else:
                health        = getattr(eval_, "goal_health", None) or ""
                on_track_pct  = float(getattr(eval_, "on_track_pct", None) or
                                      getattr(eval_, "on_track_probability_pct", 50.0) or 50.0)
                goal_name     = (getattr(eval_, "goal_name", "") or
                                 getattr(eval_, "name", "") or "Goal")
                goal_gap_rs   = float(getattr(eval_, "shortfall_rs", None) or
                                      getattr(eval_, "gap_rs", 0) or 0)
                horizon_years = float(getattr(eval_, "horizon_years", None) or 10.0)
                goal_type     = (getattr(eval_, "goal_type", "") or
                                 getattr(eval_, "type", "") or "").upper()

            goal_impact_val = max(0.0, 1.0 - on_track_pct / 100.0)
            urgency_val = 1.0 if health == "critical" else 0.7
            confidence_val = 0.8 if health == "critical" else 0.6

            # Severity: short-horizon goal in high-risk assets = always severe (PRD §8)
            short_horizon_high_risk = horizon_years < 5.0 and equity_pct > 50.0
            goal_severity = "severe" if (health == "critical" or short_horizon_high_risk) else "mismatch"

            # ── GA-1: Equity ceiling check ────────────────────────────────
            eq_ceiling = _equity_ceiling(horizon_years)
            if equity_pct > eq_ceiling + 1.0:  # 1pp tolerance
                excess_pct = round(equity_pct - eq_ceiling, 1)
                signals.append(EngineSignal(
                    signal_id=f"goal_alignment::ga1::{goal_name[:20]}::eq_trim",
                    engine_name=self.engine_name,
                    rule_label="GA-1",
                    action_type="TRIM",
                    instrument_id=None,
                    instrument_name="Equity Funds (portfolio-level)",
                    amount_rs=ctx.total_value_rs * (excess_pct / 100.0),
                    base_score=6.0,
                    confidence=0.7,
                    risk_reduction=0.7,
                    goal_impact=goal_impact_val,
                    urgency=urgency_val * 0.8,
                    implementation_ease=0.4,
                    reason_codes=["GOAL_ALIGNMENT", "EQUITY_CEILING_BREACH"],
                    reason_text=(
                        f"Goal '{goal_name}' has a {horizon_years:.0f}y horizon — "
                        f"equity ({equity_pct:.0f}%) exceeds the safe ceiling ({eq_ceiling:.0f}%) "
                        f"by {excess_pct:.0f}pp. More downside than this goal's timeline allows."
                    ),
                    dedup_key="TRIM::equity_ceiling",
                    severity=goal_severity,
                    execution_path="redirect",
                    requires_confirmation=ctx.behavioural_confidence < 0.7,
                ))

            # ── GA-2: Smallcap cap for short-horizon goals ────────────────
            if horizon_years < 5.0 and smallcap_pct_val > 20.0:
                # Find the smallcap fund with highest exit score
                sc_cand: Optional[Dict[str, Any]] = None
                for cand in ctx.exit_candidates:
                    iid = cand.get("instrument_id")
                    if iid in ctx.exited_ids or iid in local_exited_ids:
                        continue
                    mf = next((m for m in (ctx.portfolio_intelligence.get("mf_investments") or [])
                                if m.get("instrument_id") == iid), {})
                    if "small cap" in (mf.get("category") or "").lower():
                        if sc_cand is None or cand.get("exit_score", 0) > sc_cand.get("exit_score", 0):
                            sc_cand = cand
                if sc_cand:
                    iid = sc_cand.get("instrument_id")
                    from services.recommendation_engine.helpers import fuzzy_match_holding
                    h = fuzzy_match_holding(sc_cand.get("instrument_name", ""), ctx.mf_holdings)
                    amt = float(h.get("quantity", 0)) * float(h.get("current_price", 0)) if h else 0.0
                    signals.append(EngineSignal(
                        signal_id=f"goal_alignment::ga2::{goal_name[:20]}::sc_trim",
                        engine_name=self.engine_name,
                        rule_label="GA-2",
                        action_type="EXIT",
                        instrument_id=iid,
                        instrument_name=sc_cand.get("instrument_name", "Small Cap Fund"),
                        amount_rs=amt,
                        base_score=float(sc_cand.get("exit_score", 5.0)),
                        confidence=0.75,
                        risk_reduction=0.8,
                        goal_impact=goal_impact_val,
                        urgency=urgency_val,
                        implementation_ease=0.5,
                        estimated_tax_rs=float((sc_cand.get("tax_impact") or {}).get("tax_liability") or 0),
                        reason_codes=["GOAL_ALIGNMENT", "GA2_SMALLCAP_SHORT_HORIZON"],
                        reason_text=(
                            f"Goal '{goal_name}' is {horizon_years:.1f}y away — "
                            f"small-cap ({smallcap_pct_val:.0f}%) is too volatile for this timeline. "
                            f"Exit to protect what you've already built."
                        ),
                        dedup_key=f"EXIT::{iid or 'sc_trim'}",
                        severity="severe",
                        execution_path="stagger",
                        requires_confirmation=True,
                    ))
                    if iid:
                        local_exited_ids.add(iid)

            # ── GA-3: Retirement glide-path for < 10y horizon ────────────
            if "RETIREMENT" in goal_type and horizon_years < 10.0:
                target_equity = _equity_ceiling(horizon_years)
                if equity_pct > target_equity + 2.0:
                    signals.append(EngineSignal(
                        signal_id=f"goal_alignment::ga3::{goal_name[:20]}::glide",
                        engine_name=self.engine_name,
                        rule_label="GA-3",
                        action_type="TRIM",
                        instrument_id=None,
                        instrument_name="Equity Funds (retirement glide path)",
                        amount_rs=ctx.total_value_rs * ((equity_pct - target_equity) / 100.0),
                        base_score=7.0,
                        confidence=0.8,
                        risk_reduction=0.8,
                        goal_impact=goal_impact_val,
                        urgency=0.8,
                        implementation_ease=0.4,
                        reason_codes=["GOAL_ALIGNMENT", "GA3_RETIREMENT_GLIDE_PATH"],
                        reason_text=(
                            f"Retirement is {horizon_years:.0f} years away. "
                            f"Gradually reduce equity ({equity_pct:.0f}% → {target_equity:.0f}%) "
                            f"to protect your corpus from sequence-of-returns risk."
                        ),
                        dedup_key="TRIM::retirement_glide",
                        severity="mismatch" if horizon_years > 5 else "severe",
                        execution_path="stagger",
                        requires_confirmation=horizon_years < 5,
                    ))

            # ── GA-4: Goal shortfall — exit underperformer + add missing class ──
            if health not in ("critical", "at_risk"):
                continue

            best_candidate: Optional[Dict[str, Any]] = None
            for cand in ctx.exit_candidates:
                iid = cand.get("instrument_id")
                if iid in ctx.exited_ids or iid in local_exited_ids:
                    continue
                if best_candidate is None or cand.get("exit_score", 0) > best_candidate.get("exit_score", 0):
                    best_candidate = cand

            if best_candidate:
                iid = best_candidate.get("instrument_id")
                fund_name = (
                    best_candidate.get("instrument_name")
                    or (best_candidate.get("mf_investment") or {}).get("scheme_name", "")
                    or ""
                )
                from services.recommendation_engine.helpers import fuzzy_match_holding
                h = fuzzy_match_holding(fund_name, ctx.mf_holdings)
                amount_rs = (
                    float(h.get("quantity", 0)) * float(h.get("current_price", 0)) if h else 0.0
                )
                exit_sig = EngineSignal(
                    signal_id=f"goal_alignment::ga4::exit::{goal_name[:20]}::{iid or fund_name[:20]}",
                    engine_name=self.engine_name,
                    rule_label="GA-4",
                    action_type="EXIT",
                    instrument_id=iid,
                    instrument_name=fund_name,
                    amount_rs=amount_rs,
                    base_score=float(best_candidate.get("exit_score") or 5.0),
                    confidence=confidence_val,
                    risk_reduction=0.3,
                    diversification_gain=0.2,
                    goal_impact=goal_impact_val,
                    urgency=urgency_val,
                    implementation_ease=0.6,
                    estimated_tax_rs=float(
                        (best_candidate.get("tax_impact") or {}).get("tax_liability") or 0
                    ),
                    reason_codes=["GOAL_ALIGNMENT", "GA4_SHORTFALL", health.upper()],
                    reason_text=(
                        f"Goal '{goal_name}' is {health} — {on_track_pct:.0f}% on-track. "
                        f"Exit this underperformer and redirect ₹{amount_rs:,.0f} toward your goal."
                    ),
                    dedup_key=f"EXIT::{iid or fund_name[:30]}",
                    severity="severe" if health == "critical" else "mismatch",
                    execution_path="harvest",
                    requires_confirmation=health == "critical" or ctx.behavioural_confidence < 0.7,
                )
                exit_sig.__dict__["_holding"] = h
                exit_sig.__dict__["_candidate"] = best_candidate
                signals.append(exit_sig)
                if iid:
                    local_exited_ids.add(iid)

            # ADD: suggest a fund aligned with the goal's missing asset class
            if goal_gap_rs > 0 and ctx.deviation_result:
                try:
                    dev_rows = getattr(ctx.deviation_result, "rows", [])
                    largest_dev = max(
                        dev_rows, key=lambda r: abs(getattr(r, "hard_pp", 0) or 0), default=None
                    )
                    if largest_dev:
                        missing_class = getattr(largest_dev, "asset_class", "")
                        fund_name = (
                            _GOAL_DEBT_FUND if "debt" in missing_class.lower() else _GOAL_EQUITY_FUND
                        )
                        add_sig = EngineSignal(
                            signal_id=f"goal_alignment::ga4::add::{goal_name[:20]}::{missing_class}",
                            engine_name=self.engine_name,
                            rule_label="GA-4",
                            action_type="ADD",
                            instrument_id=None,
                            instrument_name=fund_name,
                            amount_rs=min(goal_gap_rs, ctx.total_value_rs * 0.15),
                            base_score=8.0,
                            confidence=confidence_val,
                            goal_impact=goal_impact_val,
                            urgency=urgency_val,
                            diversification_gain=0.3,
                            implementation_ease=0.7,
                            reason_codes=["GOAL_ALIGNMENT", "ALLOCATION_GAP", health.upper()],
                            reason_text=(
                                f"Goal '{goal_name}' needs ₹{goal_gap_rs:,.0f} more to stay on track. "
                                f"Direct new money to {fund_name} — aligns with your missing {missing_class} target."
                            ),
                            dedup_key=f"ADD::{missing_class}::goal",
                            severity="mismatch",
                            execution_path="redirect",
                        )
                        signals.append(add_sig)
                except Exception as e:
                    logger.debug("[GoalAlignmentEngine] deviation traversal failed: %s", e)

        return signals
