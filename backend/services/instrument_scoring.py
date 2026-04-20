"""Instrument Scoring Engine — Centralized scoring for MF and Stock decisions.

Implements scoring algorithms for:
1. Mutual Fund EXIT scoring
2. Mutual Fund ADD scoring
3. Stock EXIT scoring
4. Stock ADD scoring (future)

Architecture:
- Modular scoring components
- Configurable weights
- Inline quality calculations
- Decision thresholds
"""
from typing import Dict, Any, Optional, List
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _as_float(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

# ══════════════════════════════════════════════════════════════════════════
# SCORING WEIGHTS & THRESHOLDS — V2.5
# ══════════════════════════════════════════════════════════════════════════

# Mutual Fund EXIT Score Weights (V2.5 — equal tilt 25/25/25/15/10)
MF_EXIT_WEIGHTS = {
    "overlap": 0.25,      # 25%
    "tax":     0.25,      # 25%
    "quality": 0.25,      # 25% (inverse — weak fund gets high EXIT score)
    "cost":    0.15,      # 15%
    "fit":     0.10,      # 10%
}

# Mutual Fund ADD Score Weights (V2.5 — adds Need component)
MF_ADD_WEIGHTS = {
    "gap_fit":     0.30,  # 30%
    "low_overlap": 0.25,  # 25%
    "quality":     0.20,  # 20%
    "need":        0.15,  # 15% NEW
    "low_cost":    0.10,  # 10%
}

# Mutual Fund QUALITY v2 weights (6 components, category-normalized)
MF_QUALITY_WEIGHTS = {
    "performance":    0.25,  # 1/3/5Y weighted returns vs category
    "risk_adjusted":  0.20,  # Sharpe + Sortino
    "consistency":    0.20,  # Rolling-return hit ratio (proxy via alpha stability)
    "drawdown":       0.15,  # Downside protection (beta+std_dev proxy)
    "expense":        0.10,  # Penalty for high ER
    "aum_stability":  0.10,  # AUM size proxy
}

# HOLD Score weights — "do no harm first"
MF_HOLD_WEIGHTS = {
    "quality":         0.40,
    "low_overlap":     0.30,
    "tax_penalty":     0.30,
}

# SWITCH Score constants — per-component contribution (0–10 scale, summed then clamped)
SWITCH_QUALITY_WEIGHT  = 4.0   # Max contribution from quality improvement
SWITCH_OVERLAP_WEIGHT  = 3.0   # Max contribution from overlap reduction
SWITCH_COST_WEIGHT     = 2.0   # Max contribution from cost saving
SWITCH_TAX_PENALTY_CAP = 4.0   # Max deduction for high tax cost

# Stock EXIT Score Weights
STOCK_EXIT_WEIGHTS = {
    "concentration": 0.20,
    "tax": 0.05,
    "quality": 0.45,
    "momentum": 0.20,
    "sector": 0.05,
    "role": 0.05,
}

# Decision Thresholds
EXIT_THRESHOLD_HIGH = 7.0   # >= 7 = EXIT
EXIT_THRESHOLD_LOW = 4.0    # < 4 = KEEP
ADD_THRESHOLD_HIGH = 7.0    # >= 7 = ADD
ADD_THRESHOLD_LOW = 5.0     # < 5 = IGNORE
SWITCH_THRESHOLD = 2.0      # Min positive net for a SWITCH to be worth it
HOLD_THRESHOLD_HIGH = 6.5   # >= 6.5 ⇒ strong HOLD (blocks EXIT unless forced)

# EXIT Guardrails (V2.5 — "do no harm first")
QUALITY_FLOOR_FOR_EXIT = 7.5        # Quality ≥7.5 ⇒ block EXIT
EXTREME_OVERLAP_OVERRIDE = 80.0     # …unless overlap > 80%

# Portfolio Health thresholds
PORTFOLIO_HEALTHY_SCORE = 75        # ≥75 ⇒ Rule 7 Do-Nothing kicks in
MAX_ACTIONS_PER_PLAN    = 6         # Hard cap


# ══════════════════════════════════════════════════════════════════════════
# INLINE QUALITY SCORING
# ══════════════════════════════════════════════════════════════════════════

class QualityScorer:
    """V2.5 quality scoring — 6 components, category-percentile normalized where possible.

    Note: we still return scale 0-10 where LOWER is better (1-3 strong, 4-6 avg, 7-10 weak)
    to preserve compatibility with downstream EXIT scorer which reads this directly.
    The V2.5 PRD description is in a "higher is better" frame; callers that need
    "higher=better" should use `10 - quality_score`.
    """

    @staticmethod
    def calculate_mf_quality(
        fund_metadata: Dict[str, Any],
        performance_ratios: Dict[str, Any],
        category_avg: Optional[Dict[str, Any]] = None,
    ) -> float:
        """V2.5 Quality Score with 6 weighted components."""
        components: Dict[str, float] = {}

        # 1. Performance — weighted 1Y (20%) / 3Y (40%) / 5Y (40%) vs category_avg
        ret_1y = _as_float(performance_ratios.get("ret_1y"))
        ret_3y = _as_float(performance_ratios.get("ret_3y"))
        ret_5y = _as_float(performance_ratios.get("ret_5y"))
        cat = category_avg or {}
        cat_1y = _as_float(cat.get("ret_1y")) if cat else None
        cat_3y = _as_float(cat.get("ret_3y")) if cat else None
        cat_5y = _as_float(cat.get("ret_5y")) if cat else None
        perf_scores = []
        for r, c, w in ((ret_1y, cat_1y, 0.2), (ret_3y, cat_3y, 0.4), (ret_5y, cat_5y, 0.4)):
            if r is None:
                continue
            if c is not None:
                # vs category: +3% over cat → 2 (strong), 0-3% → 4, -3%-0 → 6, <-3% → 8
                diff = r - c
                if diff >= 3:   s = 2.0
                elif diff >= 0: s = 4.0
                elif diff >= -3: s = 6.0
                else:           s = 8.0
            else:
                # Absolute ladder when no category data
                if r >= 15: s = 2.0
                elif r >= 10: s = 4.0
                elif r >= 6: s = 6.0
                else: s = 8.0
            perf_scores.append((s, w))
        if perf_scores:
            total_w = sum(w for _, w in perf_scores)
            components["performance"] = sum(s * w for s, w in perf_scores) / total_w
        else:
            components["performance"] = 5.0

        # 2. Risk-adjusted — Sharpe primary, Sortino fallback
        sharpe = _as_float(performance_ratios.get("sharpe"))
        sortino = _as_float(performance_ratios.get("sortino"))
        metric = sharpe if sharpe is not None else sortino
        if metric is not None:
            if metric >= 1.5:   components["risk_adjusted"] = 2.0
            elif metric >= 1.0: components["risk_adjusted"] = 4.0
            elif metric >= 0.5: components["risk_adjusted"] = 6.0
            else:               components["risk_adjusted"] = 8.0
        else:
            components["risk_adjusted"] = 5.0

        # 3. Consistency — alpha + beta stability proxy (NEW in V2.5)
        alpha = _as_float(performance_ratios.get("alpha"))
        beta = _as_float(performance_ratios.get("beta"))
        if alpha is not None:
            # Positive, stable alpha → consistent
            if alpha >= 2: components["consistency"] = 2.5
            elif alpha >= 0: components["consistency"] = 4.5
            elif alpha >= -2: components["consistency"] = 6.5
            else: components["consistency"] = 8.5
        elif beta is not None:
            # Beta close to 1 → market-like, less dispersion
            dist = abs(beta - 1)
            if dist <= 0.2:   components["consistency"] = 4.0
            elif dist <= 0.5: components["consistency"] = 5.5
            else:             components["consistency"] = 7.0
        else:
            components["consistency"] = 5.0

        # 4. Drawdown protection — std_dev proxy
        std_dev = _as_float(performance_ratios.get("std_dev"))
        if std_dev is not None:
            if std_dev <= 10: components["drawdown"] = 2.5
            elif std_dev <= 15: components["drawdown"] = 4.5
            elif std_dev <= 22: components["drawdown"] = 6.0
            else: components["drawdown"] = 8.0
        else:
            components["drawdown"] = 5.0

        # 5. Expense ratio
        er = _as_float(fund_metadata.get("expense_ratio"))
        if er is not None:
            if er <= 0.5: components["expense"] = 2.0
            elif er <= 1.0: components["expense"] = 4.5
            elif er <= 1.5: components["expense"] = 6.5
            else:           components["expense"] = 8.5
        else:
            components["expense"] = 5.0

        # 6. AUM stability
        aum = _as_float(fund_metadata.get("aum_cr"))
        if aum is not None:
            if aum >= 5000: components["aum_stability"] = 2.0
            elif aum >= 1000: components["aum_stability"] = 4.0
            elif aum >= 300:  components["aum_stability"] = 6.0
            else:             components["aum_stability"] = 7.5
        else:
            components["aum_stability"] = 5.0

        # Weighted aggregate
        score = sum(components[k] * MF_QUALITY_WEIGHTS[k] for k in MF_QUALITY_WEIGHTS)
        return round(score, 2)
    
    @staticmethod
    def calculate_stock_quality(
        stock_data: Dict[str, Any],
        fundamentals: Optional[Dict[str, Any]] = None,
    ) -> float:
        """Calculate Stock Quality Score (0-10) based on available fundamentals.
        
        Lower is better: 1-3 = strong, 4-6 = average, 7-10 = weak
        
        Factors (if available):
        - P/E Ratio (valuation)
        - ROE (profitability)
        - Debt/Equity (financial health)
        - Price vs Buy Price (return performance)
        
        If no fundamental data available: Returns neutral 5.0
        """
        scores = []
        has_fundamental_data = False
        
        # 1. P/E Ratio (25%) - Compare to industry average
        pe_ratio = stock_data.get("pe_ratio")
        if pe_ratio:
            has_fundamental_data = True
            try:
                pe_val = float(pe_ratio)
                if pe_val < 15:  # Undervalued
                    scores.append(3.0)
                elif pe_val < 25:  # Fair value
                    scores.append(5.0)
                elif pe_val < 40:  # Overvalued
                    scores.append(7.0)
                else:  # Highly overvalued
                    scores.append(9.0)
            except:
                scores.append(5.0)
        
        # 2. ROE - Return on Equity (profitability) (30%)
        roe = stock_data.get("roe")
        if roe:
            has_fundamental_data = True
            try:
                roe_val = float(roe)
                if roe_val >= 20:  # Excellent
                    scores.append(2.0)
                elif roe_val >= 15:  # Good
                    scores.append(3.0)
                elif roe_val >= 10:  # Average
                    scores.append(5.0)
                elif roe_val >= 5:  # Weak
                    scores.append(7.0)
                else:  # Poor
                    scores.append(9.0)
            except:
                scores.append(5.0)
        
        # 3. Debt to Equity (25%) - Financial health
        debt_to_equity = stock_data.get("debt_to_equity")
        if debt_to_equity is not None:
            has_fundamental_data = True
            try:
                de_val = float(debt_to_equity)
                if de_val < 0.5:  # Very low debt (healthy)
                    scores.append(2.0)
                elif de_val < 1.0:  # Moderate
                    scores.append(4.0)
                elif de_val < 2.0:  # High debt
                    scores.append(7.0)
                else:  # Very high debt (risky)
                    scores.append(9.0)
            except:
                scores.append(5.0)
        
        # 4. Return Performance (20%) - Buy price vs current price
        buy_price = stock_data.get("buy_price")
        current_price = stock_data.get("current_price")
        if buy_price and current_price:
            try:
                buy_val = float(buy_price)
                curr_val = float(current_price)
                if buy_val > 0:
                    return_pct = ((curr_val - buy_val) / buy_val) * 100
                    if return_pct >= 50:  # Excellent return
                        scores.append(2.0)
                    elif return_pct >= 20:  # Good
                        scores.append(3.0)
                    elif return_pct >= 0:  # Positive
                        scores.append(5.0)
                    elif return_pct >= -15:  # Small loss
                        scores.append(7.0)
                    else:  # Significant loss
                        scores.append(9.0)
            except:
                pass
        
        # If we have fundamental data, calculate average
        if scores:
            quality_score = sum(scores) / len(scores)
            return round(quality_score, 2)
        
        # No fundamental data available - return neutral
        # This means stock won't be flagged for EXIT based on quality alone
        logger.warning(f"No fundamental data for stock: {stock_data.get('name', 'Unknown')}")
        return 5.0  # Neutral - neither good nor bad


# ══════════════════════════════════════════════════════════════════════════
# INSTRUMENT SCORING ENGINE
# ══════════════════════════════════════════════════════════════════════════

class InstrumentScoringEngine:
    """Centralized scoring engine for all instruments."""
    
    def __init__(self):
        self.quality_scorer = QualityScorer()
    
    # ──────────────────────────────────────────────────────────────────────
    # MUTUAL FUND EXIT SCORING
    # ──────────────────────────────────────────────────────────────────────
    
    def score_mf_exit(
        self,
        mf_investment: Dict[str, Any],
        portfolio_intelligence: Dict[str, Any],
        tax_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Calculate EXIT score for a mutual fund.
        
        Formula:
        MF Exit Score = 
            (0.30 × Overlap)
            + (0.25 × Tax)
            + (0.15 × Cost)
            + (0.20 × MF Quality)
            + (0.10 × Portfolio Fit)
        
        Returns:
            {
                "exit_score": 7.8,
                "action": "EXIT",
                "priority": "high",
                "confidence": "HIGH",
                "score_breakdown": {...},
                "reasons": ["HIGH_OVERLAP", "HIGH_COST"]
            }
        """
        scores = {}
        reasons = []
        
        # 1. Overlap Score (30%)
        pairs = portfolio_intelligence.get("pairwise_overlap", [])
        mf_id = mf_investment.get("instrument_id")
        
        max_overlap = 0
        for pair in pairs:
            if pair["a"] == mf_id or pair["b"] == mf_id:
                max_overlap = max(max_overlap, pair["overlap_pct"])
        
        # Scale: 0% = 0, 100% = 10
        overlap_score = min(10, max_overlap / 10)
        scores["overlap"] = round(overlap_score, 2)
        
        if overlap_score >= 7:
            reasons.append("HIGH_OVERLAP")
        
        # 2. Tax Score (25%)
        scores["tax"] = tax_result.get("tax_score", 5.0)
        
        if scores["tax"] >= 7:
            reasons.append("HIGH_TAX_IMPACT")
        
        # 3. Cost Score (15%)
        expense_ratio = mf_investment.get("expense_ratio")
        if expense_ratio is not None:
            # Scale: 0% = 0, 2%+ = 10
            cost_score = min(10, float(expense_ratio) * 5)
        else:
            cost_score = 5.0
        scores["cost"] = round(cost_score, 2)
        
        if cost_score >= 7:
            reasons.append("HIGH_COST")
        
        # 4. MF Quality Score (20%)
        catalog = portfolio_intelligence.get("catalog", {})
        fund_data = catalog.get(mf_id, {})
        
        quality_score = self.quality_scorer.calculate_mf_quality(
            fund_metadata={
                "expense_ratio": expense_ratio,
                "aum_cr": mf_investment.get("aum_cr"),
            },
            performance_ratios=fund_data.get("ratios", {}),
        )
        scores["quality"] = quality_score
        
        if quality_score >= 7:
            reasons.append("WEAK_PERFORMANCE")
        
        # 5. Portfolio Fit Score (10%)
        # Simple: if category is overweight → high score
        # For MVP: neutral score
        scores["fit"] = 5.0
        
        # Calculate weighted EXIT score
        exit_score = (
            scores["overlap"] * MF_EXIT_WEIGHTS["overlap"] +
            scores["tax"] * MF_EXIT_WEIGHTS["tax"] +
            scores["cost"] * MF_EXIT_WEIGHTS["cost"] +
            scores["quality"] * MF_EXIT_WEIGHTS["quality"] +
            scores["fit"] * MF_EXIT_WEIGHTS["fit"]
        )
        
        # Determine action and priority
        # V2.5 Guardrails — "do no harm first"
        # 1. Strong quality floor: quality ≥ 7.5 (where quality is "lower=better", so
        #    quality_score <= 2.5) blocks EXIT unless overlap is extreme (>80%).
        #    The quality component here is RAW 0-10 (lower=better), so use `<= 2.5`.
        guardrail_blocked = False
        if quality_score <= (10 - QUALITY_FLOOR_FOR_EXIT) and max_overlap < EXTREME_OVERLAP_OVERRIDE:
            guardrail_blocked = True
            reasons.append("BLOCKED_HIGH_QUALITY_FLOOR")
        # 2. Tax > benefit block — if tax_efficiency_score < 1.0 we block
        tax_eff = tax_result.get("tax_efficiency_score")
        if tax_eff is not None and tax_eff < 1.0:
            guardrail_blocked = True
            reasons.append("BLOCKED_TAX_EXCEEDS_BENEFIT")

        if guardrail_blocked:
            action = "HOLD"
            priority = "low"
            confidence = "HIGH"  # high confidence the exit is a bad idea
        elif exit_score >= EXIT_THRESHOLD_HIGH:
            action = "EXIT"
            priority = "high"
            confidence = "HIGH"
        elif exit_score >= EXIT_THRESHOLD_LOW:
            action = "HOLD"
            priority = "medium"
            confidence = "MEDIUM"
        else:
            action = "KEEP"
            priority = "low"
            confidence = "LOW"

        return {
            "exit_score": round(exit_score, 2),
            "action": action,
            "priority": priority,
            "confidence": confidence,
            "guardrail_blocked": guardrail_blocked,
            "score_breakdown": scores,
            "reasons": reasons,
            "instrument_id": mf_id,
            "instrument_name": mf_investment.get("scheme_name"),
            "instrument_type": "mutual_fund",
        }

    # ──────────────────────────────────────────────────────────────────────
    # MUTUAL FUND HOLD SCORING (V2.5 — prevents over-optimization)
    # ──────────────────────────────────────────────────────────────────────
    def score_mf_hold(
        self,
        mf_investment: Dict[str, Any],
        portfolio_intelligence: Dict[str, Any],
        tax_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Calculate HOLD score (0-10) — higher = stronger case to NOT touch this fund.

        hold_score = 0.4·high_quality + 0.3·low_overlap + 0.3·high_tax_penalty_if_exit
        """
        # Quality (higher = better). Raw quality_score is lower=better, so invert.
        mf_id = mf_investment.get("instrument_id")
        catalog = portfolio_intelligence.get("catalog", {}) or {}
        raw_q = self.quality_scorer.calculate_mf_quality(
            fund_metadata={
                "expense_ratio": mf_investment.get("expense_ratio"),
                "aum_cr": mf_investment.get("aum_cr"),
            },
            performance_ratios=(catalog.get(mf_id) or {}).get("ratios", {}),
        )
        high_quality = 10 - raw_q

        # Low-overlap (higher = lower overlap)
        pairs = portfolio_intelligence.get("pairwise_overlap") or []
        max_overlap = max(
            (p.get("overlap_pct", 0) for p in pairs if p.get("a") == mf_id or p.get("b") == mf_id),
            default=0,
        )
        low_overlap = max(0, 10 - max_overlap / 10)

        # Tax-penalty-if-exit (higher = more painful to exit)
        tax_pen = float(tax_result.get("tax_score") or 0)

        hold_score = (
            high_quality * MF_HOLD_WEIGHTS["quality"]
            + low_overlap * MF_HOLD_WEIGHTS["low_overlap"]
            + tax_pen     * MF_HOLD_WEIGHTS["tax_penalty"]
        )
        return {
            "hold_score": round(hold_score, 2),
            "high_quality": round(high_quality, 2),
            "low_overlap": round(low_overlap, 2),
            "tax_penalty": round(tax_pen, 2),
            "strong_hold": hold_score >= HOLD_THRESHOLD_HIGH,
        }

    # ──────────────────────────────────────────────────────────────────────
    # MUTUAL FUND SWITCH SCORING (V2.5 — primary replacement primitive)
    # ──────────────────────────────────────────────────────────────────────
    def score_mf_switch(
        self,
        from_fund: Dict[str, Any],
        to_fund: Dict[str, Any],
        tax_result_from: Dict[str, Any],
        portfolio_intelligence: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Calculate SWITCH score (from_fund → to_fund).

        switch_score = quality_improvement + overlap_reduction + cost_saving − tax_cost

        All components normalized to 0–max-weight bands; final result clamped to [-10, 10].
        """
        cat_from = (portfolio_intelligence.get("catalog") or {}).get(from_fund.get("instrument_id"), {})
        cat_to = (portfolio_intelligence.get("catalog") or {}).get(to_fund.get("instrument_id"), {})

        q_from = self.quality_scorer.calculate_mf_quality(
            fund_metadata={"expense_ratio": from_fund.get("expense_ratio"), "aum_cr": from_fund.get("aum_cr")},
            performance_ratios=cat_from.get("ratios", {}),
        )
        q_to = self.quality_scorer.calculate_mf_quality(
            fund_metadata={"expense_ratio": to_fund.get("expense_ratio"), "aum_cr": to_fund.get("aum_cr")},
            performance_ratios=cat_to.get("ratios", {}),
        )
        # quality is "lower = better", so improvement = (q_from - q_to). Clamp to [0, 10].
        q_improvement_raw = max(0, q_from - q_to)
        quality_improvement = min(SWITCH_QUALITY_WEIGHT, q_improvement_raw * (SWITCH_QUALITY_WEIGHT / 10))

        # Overlap reduction — from_fund's max overlap with portfolio minus to_fund's expected
        pairs = portfolio_intelligence.get("pairwise_overlap") or []
        from_id = from_fund.get("instrument_id")
        max_from_overlap = max(
            (p.get("overlap_pct", 0) for p in pairs if p.get("a") == from_id or p.get("b") == from_id),
            default=0,
        )
        # Assume SWITCH target has low overlap initially (5% baseline)
        overlap_delta_pct = max(0, max_from_overlap - 5)
        overlap_reduction = min(SWITCH_OVERLAP_WEIGHT, overlap_delta_pct * (SWITCH_OVERLAP_WEIGHT / 100))

        # Cost saving — expense ratio delta
        er_from = _as_float(from_fund.get("expense_ratio")) or 1.0
        er_to = _as_float(to_fund.get("expense_ratio")) or 1.0
        er_delta = max(0, er_from - er_to)
        cost_saving = min(SWITCH_COST_WEIGHT, er_delta * (SWITCH_COST_WEIGHT / 1.5))

        # Tax cost penalty — based on tax_liability as % of exit_amount
        liab = float(tax_result_from.get("tax_liability") or 0)
        exit_amt = float(tax_result_from.get("exit_amount_rs") or 0) or 1
        tax_pct = (liab / exit_amt) * 100
        tax_penalty = min(SWITCH_TAX_PENALTY_CAP, tax_pct * (SWITCH_TAX_PENALTY_CAP / 10))

        switch_score = quality_improvement + overlap_reduction + cost_saving - tax_penalty
        switch_score = max(-10.0, min(10.0, switch_score))

        # Tax efficiency score — estimated annual benefit ÷ tax cost
        # Benefit ≈ (ER saving × corpus) + (quality improvement heuristic ₹500 per quality point × corpus/1L)
        corpus = exit_amt
        annual_cost_save = (er_delta / 100) * corpus
        quality_bonus_yr = q_improvement_raw * (corpus / 100000) * 500
        annual_benefit = annual_cost_save + quality_bonus_yr
        tax_efficiency = (annual_benefit / liab) if liab > 0 else (float("inf") if annual_benefit > 0 else 0)

        return {
            "switch_score": round(switch_score, 2),
            "recommended": switch_score >= SWITCH_THRESHOLD,
            "quality_improvement": round(quality_improvement, 2),
            "overlap_reduction": round(overlap_reduction, 2),
            "cost_saving": round(cost_saving, 2),
            "tax_penalty": round(tax_penalty, 2),
            "annual_benefit_rs": round(annual_benefit, 2),
            "tax_cost_rs": round(liab, 2),
            "tax_efficiency_score": round(tax_efficiency, 2) if tax_efficiency != float("inf") else 99.0,
            "from_quality": round(q_from, 2),
            "to_quality": round(q_to, 2),
        }
    
    # ──────────────────────────────────────────────────────────────────────
    # MUTUAL FUND ADD SCORING
    # ──────────────────────────────────────────────────────────────────────
    
    def score_mf_add(
        self,
        candidate_fund: Dict[str, Any],
        portfolio_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Calculate ADD score for a potential MF investment.
        
        Formula:
        MF Add Score = 
            (0.30 × Gap Fit)
            + (0.25 × (10 - Overlap))
            + (0.25 × (10 - MF Quality))
            + (0.10 × (10 - Cost))
            + (0.10 × Headroom)
        
        Returns:
            {
                "add_score": 7.5,
                "action": "ADD",
                "priority": "high",
                "confidence": "HIGH",
                "score_breakdown": {...},
                "reasons": ["FILLS_GAP", "LOW_OVERLAP"]
            }
        """
        scores = {}
        reasons = []
        
        # 1. Gap Fit (30%)
        category = candidate_fund.get("category", "").lower()
        current_allocation = portfolio_context.get("asset_allocation", {})
        
        if "debt" in category and current_allocation.get("debt_pct", 0) < 20:
            gap_fit_score = 8.0  # Strong fit
            reasons.append("FILLS_DEBT_GAP")
        elif "equity" in category and current_allocation.get("equity_pct", 0) < 60:
            gap_fit_score = 7.0
            reasons.append("FILLS_EQUITY_GAP")
        else:
            gap_fit_score = 5.0  # Neutral
        scores["gap_fit"] = gap_fit_score
        
        # 2. Low Overlap (25%)
        # For new fund, assume low overlap with existing portfolio
        # In production: calculate actual overlap with existing funds
        overlap_score = 2.0  # Low overlap assumed
        scores["low_overlap"] = 10 - overlap_score
        
        if overlap_score <= 3:
            reasons.append("LOW_OVERLAP")
        
        # 3. Quality (25%)
        quality_score = self.quality_scorer.calculate_mf_quality(
            fund_metadata=candidate_fund,
            performance_ratios=candidate_fund.get("ratios", {}),
        )
        scores["quality"] = 10 - quality_score
        
        if quality_score <= 3:
            reasons.append("HIGH_QUALITY")
        
        # 4. Low Cost (10%)
        expense_ratio = candidate_fund.get("expense_ratio")
        if expense_ratio is not None:
            cost_score = min(10, float(expense_ratio) * 5)
            scores["low_cost"] = 10 - cost_score
        else:
            scores["low_cost"] = 5.0
        
        if expense_ratio is not None and float(expense_ratio) < 0.5:
            reasons.append("LOW_COST")
        
        # 5. Need score (NEW in V2.5) — category-level gap pressure
        # Higher when the category has <target allocation OR the portfolio lacks this bucket entirely
        if "debt" in category:
            debt_pct = current_allocation.get("debt_pct", 0) or 0
            # target: 10-30% based on risk (rule 5 dynamic target)
            target = portfolio_context.get("debt_target_pct", 20)
            gap = max(0, target - debt_pct)
            scores["need"] = min(10, gap * 0.5)  # 20% gap → 10
        elif "gold" in category:
            gold_pct = current_allocation.get("gold_pct", 0) or 0
            scores["need"] = min(10, max(0, 5 - gold_pct))
        else:
            scores["need"] = 4.0  # neutral for equity

        # Calculate weighted ADD score
        add_score = (
            scores["gap_fit"]     * MF_ADD_WEIGHTS["gap_fit"] +
            scores["low_overlap"] * MF_ADD_WEIGHTS["low_overlap"] +
            scores["quality"]     * MF_ADD_WEIGHTS["quality"] +
            scores["need"]        * MF_ADD_WEIGHTS["need"] +
            scores["low_cost"]    * MF_ADD_WEIGHTS["low_cost"]
        )
        
        # Determine action and priority
        if add_score >= ADD_THRESHOLD_HIGH:
            action = "ADD"
            priority = "high"
            confidence = "HIGH"
        elif add_score >= ADD_THRESHOLD_LOW:
            action = "CONSIDER"
            priority = "medium"
            confidence = "MEDIUM"
        else:
            action = "IGNORE"
            priority = "low"
            confidence = "LOW"
        
        return {
            "add_score": round(add_score, 2),
            "action": action,
            "priority": priority,
            "confidence": confidence,
            "score_breakdown": scores,
            "reasons": reasons,
            "instrument_id": candidate_fund.get("instrument_id"),
            "instrument_name": candidate_fund.get("scheme_name") or candidate_fund.get("name"),
            "instrument_type": "mutual_fund",
        }
    
    # ──────────────────────────────────────────────────────────────────────
    # STOCK EXIT SCORING
    # ──────────────────────────────────────────────────────────────────────
    
    def score_stock_exit(
        self,
        stock_holding: Dict[str, Any],
        portfolio_context: Dict[str, Any],
        tax_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Calculate EXIT score for a stock.
        
        Formula:
        Stock Exit Score = 
            (0.25 × Concentration)
            + (0.20 × Tax)
            + (0.25 × Quality)
            + (0.15 × Momentum)
            + (0.10 × Sector Exposure)
            + (0.05 × Portfolio Role)
        
        Returns:
            {
                "exit_score": 6.8,
                "action": "HOLD",
                "priority": "medium",
                "confidence": "MEDIUM",
                "score_breakdown": {...},
                "reasons": ["OVEREXPOSURE"]
            }
        """
        scores = {}
        reasons = []
        
        # 1. Concentration (25%)
        total_value = portfolio_context.get("total_value", 1)
        stock_value = stock_holding["quantity"] * stock_holding["current_price"]
        concentration_pct = (stock_value / total_value * 100) if total_value > 0 else 0
        
        # Scale: 0% = 0, 10%+ = 10
        concentration_score = min(10, concentration_pct)
        scores["concentration"] = round(concentration_score, 2)
        
        if concentration_score >= 7:
            reasons.append("OVEREXPOSURE")
        
        # 2. Tax Score (20%)
        scores["tax"] = tax_result.get("tax_score", 5.0)
        
        if scores["tax"] >= 7:
            reasons.append("HIGH_TAX_IMPACT")
        
        # 3. Quality Score (25%)
        quality_score = self.quality_scorer.calculate_stock_quality(stock_holding)
        scores["quality"] = quality_score
        
        if quality_score >= 7:
            reasons.append("WEAK_FUNDAMENTALS")
        
        # 4. Momentum (15%)
        buy_price = stock_holding.get("buy_price", 0)
        current_price = stock_holding.get("current_price", 0)
        if buy_price > 0:
            return_pct = (current_price - buy_price) / buy_price * 100
            # Negative return = high exit score
            if return_pct < -20:
                momentum_score = 9.0  # Strong sell signal
                reasons.append("NEGATIVE_MOMENTUM")
            elif return_pct < 0:
                momentum_score = 7.0
            elif return_pct < 10:
                momentum_score = 5.0
            else:
                momentum_score = 3.0  # Positive momentum, keep
        else:
            momentum_score = 5.0
        scores["momentum"] = momentum_score
        
        # 5. Sector Exposure (10%)
        # If sector is overweight → high score
        # For MVP: neutral
        scores["sector"] = 5.0
        
        # 6. Portfolio Role (5%)
        # Core vs redundant
        # For MVP: neutral
        scores["role"] = 5.0
        
        # Calculate weighted EXIT score
        exit_score = (
            scores["concentration"] * STOCK_EXIT_WEIGHTS["concentration"] +
            scores["tax"] * STOCK_EXIT_WEIGHTS["tax"] +
            scores["quality"] * STOCK_EXIT_WEIGHTS["quality"] +
            scores["momentum"] * STOCK_EXIT_WEIGHTS["momentum"] +
            scores["sector"] * STOCK_EXIT_WEIGHTS["sector"] +
            scores["role"] * STOCK_EXIT_WEIGHTS["role"]
        )
        
        # Determine action and priority
        if exit_score >= EXIT_THRESHOLD_HIGH:
            action = "EXIT"
            priority = "high"
            confidence = "HIGH"
        elif exit_score >= EXIT_THRESHOLD_LOW:
            action = "HOLD"
            priority = "medium"
            confidence = "MEDIUM"
        else:
            action = "KEEP"
            priority = "low"
            confidence = "LOW"
        
        return {
            "exit_score": round(exit_score, 2),
            "action": action,
            "priority": priority,
            "confidence": confidence,
            "score_breakdown": scores,
            "reasons": reasons,
            "instrument_id": stock_holding.get("holding_id") or stock_holding.get("name"),
            "instrument_name": stock_holding.get("name"),
            "instrument_type": "equity",
        }
    
    # ──────────────────────────────────────────────────────────────────────
    # STOCK ADD SCORING (Future)
    # ──────────────────────────────────────────────────────────────────────
    
    def score_stock_add(
        self,
        candidate_stock: Dict[str, Any],
        portfolio_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Calculate ADD score for a potential stock investment.
        
        For MVP: Placeholder
        In production: Similar to MF ADD scoring with stock-specific factors
        """
        # MVP: Return neutral score
        return {
            "add_score": 5.0,
            "action": "CONSIDER",
            "priority": "medium",
            "confidence": "MEDIUM",
            "score_breakdown": {},
            "reasons": ["MVP_PLACEHOLDER"],
            "instrument_id": candidate_stock.get("symbol"),
            "instrument_name": candidate_stock.get("name"),
            "instrument_type": "equity",
        }


# ══════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════

def get_scoring_engine() -> InstrumentScoringEngine:
    """Get singleton scoring engine instance."""
    return InstrumentScoringEngine()
