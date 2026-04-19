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

# ══════════════════════════════════════════════════════════════════════════
# SCORING WEIGHTS & THRESHOLDS
# ══════════════════════════════════════════════════════════════════════════

# Mutual Fund EXIT Score Weights
MF_EXIT_WEIGHTS = {
    "overlap": 0.30,      # 30%
    "tax": 0.25,          # 25%
    "cost": 0.15,         # 15%
    "quality": 0.20,      # 20%
    "fit": 0.10,          # 10%
}

# Mutual Fund ADD Score Weights
MF_ADD_WEIGHTS = {
    "gap_fit": 0.30,      # 30%
    "low_overlap": 0.25,  # 25%
    "quality": 0.25,      # 25%
    "low_cost": 0.10,     # 10%
    "headroom": 0.10,     # 10%
}

# Stock EXIT Score Weights
STOCK_EXIT_WEIGHTS = {
    "concentration": 0.25,  # 25%
    "tax": 0.20,            # 20%
    "quality": 0.25,        # 25%
    "momentum": 0.15,       # 15%
    "sector": 0.10,         # 10%
    "role": 0.05,           # 5%
}

# Decision Thresholds
EXIT_THRESHOLD_HIGH = 7.0   # >= 7 = EXIT
EXIT_THRESHOLD_LOW = 4.0    # < 4 = KEEP
ADD_THRESHOLD_HIGH = 7.0    # >= 7 = ADD
ADD_THRESHOLD_LOW = 5.0     # < 5 = IGNORE


# ══════════════════════════════════════════════════════════════════════════
# INLINE QUALITY SCORING
# ══════════════════════════════════════════════════════════════════════════

class QualityScorer:
    """Inline quality scoring for MF and Stocks."""
    
    @staticmethod
    def calculate_mf_quality(
        fund_metadata: Dict[str, Any],
        performance_ratios: Dict[str, Any],
        category_avg: Optional[Dict[str, Any]] = None,
    ) -> float:
        """Calculate MF Quality Score (0-10).
        
        Lower is better: 1-3 = strong, 4-6 = average, 7-10 = weak
        
        Components (equal weight):
        - Performance consistency (25%)
        - Risk-adjusted return (25%)
        - Expense ratio (25%)
        - AUM stability (25%)
        """
        scores = []
        
        # 1. Performance consistency (vs category)
        ret_1y = performance_ratios.get("ret_1y")
        ret_3y = performance_ratios.get("ret_3y")
        if ret_1y is not None and ret_3y is not None:
            avg_ret = (float(ret_1y) + float(ret_3y)) / 2
            if avg_ret >= 12:
                scores.append(2.0)  # Strong
            elif avg_ret >= 8:
                scores.append(5.0)  # Average
            else:
                scores.append(8.0)  # Weak
        else:
            scores.append(5.0)  # Neutral if no data
        
        # 2. Risk-adjusted return (Sharpe/Sortino)
        sharpe = performance_ratios.get("sharpe")
        sortino = performance_ratios.get("sortino")
        if sharpe is not None:
            sharpe_val = float(sharpe)
            if sharpe_val >= 1.5:
                scores.append(2.0)  # Excellent
            elif sharpe_val >= 0.8:
                scores.append(5.0)  # Average
            else:
                scores.append(8.0)  # Poor
        elif sortino is not None:
            sortino_val = float(sortino)
            if sortino_val >= 1.5:
                scores.append(2.0)
            elif sortino_val >= 0.8:
                scores.append(5.0)
            else:
                scores.append(8.0)
        else:
            scores.append(5.0)
        
        # 3. Expense ratio (cost efficiency)
        expense_ratio = fund_metadata.get("expense_ratio")
        if expense_ratio is not None:
            exp_val = float(expense_ratio)
            if exp_val <= 0.5:
                scores.append(2.0)  # Very low cost
            elif exp_val <= 1.0:
                scores.append(5.0)  # Average
            else:
                scores.append(8.0)  # High cost
        else:
            scores.append(5.0)
        
        # 4. AUM stability (reliability)
        aum_cr = fund_metadata.get("aum_cr")
        if aum_cr is not None:
            aum_val = float(aum_cr)
            if aum_val >= 5000:  # >= ₹5000 Cr
                scores.append(2.0)  # Large, stable
            elif aum_val >= 1000:
                scores.append(5.0)  # Medium
            else:
                scores.append(7.0)  # Small
        else:
            scores.append(5.0)
        
        # Average score
        quality_score = sum(scores) / len(scores) if scores else 5.0
        return round(quality_score, 2)
    
    @staticmethod
    def calculate_stock_quality(
        stock_data: Dict[str, Any],
        fundamentals: Optional[Dict[str, Any]] = None,
    ) -> float:
        """Calculate Stock Quality Score (0-10).
        
        Lower is better: 1-3 = strong, 4-6 = average, 7-10 = weak
        
        For MVP: Simplified placeholder
        In production: Use ROCE, growth, valuation, debt
        """
        # MVP: Return neutral score
        # Future: Integrate fundamentals from Alpha Vantage / Groww
        return 5.0


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
            "instrument_id": mf_id,
            "instrument_name": mf_investment.get("scheme_name"),
            "instrument_type": "mutual_fund",
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
        
        # 5. Headroom (10%)
        # Check if category has room for more allocation
        # For MVP: neutral
        scores["headroom"] = 5.0
        
        # Calculate weighted ADD score
        add_score = (
            scores["gap_fit"] * MF_ADD_WEIGHTS["gap_fit"] +
            scores["low_overlap"] * MF_ADD_WEIGHTS["low_overlap"] +
            scores["quality"] * MF_ADD_WEIGHTS["quality"] +
            scores["low_cost"] * MF_ADD_WEIGHTS["low_cost"] +
            scores["headroom"] * MF_ADD_WEIGHTS["headroom"]
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
