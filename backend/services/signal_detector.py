"""Signal Detector — Extensible plugin system for portfolio signals.

Architecture:
- Base SignalDetector class
- Plugin registry for easy extension
- Each signal detector is independent
- Priority-based signal ranking

Easy to add new signals:
1. Create new detector class inheriting from SignalDetector
2. Add to SIGNAL_DETECTORS list
3. Done!
"""
from typing import Dict, Any, List, Optional
from abc import ABC, abstractmethod
import logging

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════
# BASE SIGNAL DETECTOR CLASS
# ══════════════════════════════════════════════════════════════════════════

class SignalDetector(ABC):
    """Base class for all signal detectors."""
    
    @abstractmethod
    def detect(self, portfolio_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Detect signal from portfolio data.
        
        Returns None if signal not detected, or signal dict:
        {
            "signal_id": "overlap_1",
            "type": "OVERLAP_REDUNDANCY",
            "severity": "HIGH",  # HIGH | MEDIUM | LOW
            "title": "High overlap detected",
            "description": "2 of your funds hold 95% similar stocks",
            "impact": "₹4.8L locked in duplicates",
            "affected_assets": [...],
            "details": {...},
            "suggested_actions": [...]
        }
        """
        pass
    
    @property
    @abstractmethod
    def signal_type(self) -> str:
        """Signal type identifier."""
        pass
    
    @property
    def priority(self) -> int:
        """Priority for signal ranking (lower = higher priority)."""
        return 10


# ══════════════════════════════════════════════════════════════════════════
# SIGNAL 1: OVERLAP / REDUNDANCY DETECTOR
# ══════════════════════════════════════════════════════════════════════════

class OverlapSignalDetector(SignalDetector):
    """Detects high overlap between mutual funds."""
    
    @property
    def signal_type(self) -> str:
        return "OVERLAP_REDUNDANCY"
    
    @property
    def priority(self) -> int:
        return 1  # Highest priority
    
    def detect(self, portfolio_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Detect overlap signal from portfolio intelligence data."""
        intelligence = portfolio_data.get("portfolio_intelligence", {})
        pairs = intelligence.get("pairwise_overlap", [])
        compression = intelligence.get("compression", {})
        
        if not pairs:
            return None
        
        # Find max overlap
        max_overlap = max((p["overlap_pct"] for p in pairs), default=0)
        compression_score = compression.get("score", 50)
        
        # Thresholds
        if max_overlap >= 80 or compression_score < 30:
            severity = "HIGH"
        elif max_overlap >= 60 or compression_score < 40:
            severity = "MEDIUM"
        elif max_overlap >= 40:
            severity = "LOW"
        else:
            return None  # No significant overlap
        
        # Find top overlapping pair
        top_pair = max(pairs, key=lambda p: p["overlap_pct"])
        
        # Calculate impact (₹ locked in duplicates)
        # Use smaller fund's amount as the duplicate amount
        mf_investments = intelligence.get("mf_investments", [])
        fund_a = next((m for m in mf_investments if m.get("instrument_id") == top_pair["a"]), None)
        fund_b = next((m for m in mf_investments if m.get("instrument_id") == top_pair["b"]), None)
        
        if fund_a and fund_b:
            amount_a = fund_a.get("amount_rs", 0)
            amount_b = fund_b.get("amount_rs", 0)
            duplicate_amount = min(amount_a, amount_b) * (top_pair["overlap_pct"] / 100)
            impact_text = f"₹{duplicate_amount:,.0f} locked in duplicate holdings"
            affected_assets = [
                top_pair["a_name"],
                top_pair["b_name"]
            ]
        else:
            impact_text = f"{max_overlap:.0f}% overlap detected"
            affected_assets = []
        
        return {
            "signal_id": f"overlap_{len(pairs)}",
            "type": self.signal_type,
            "severity": severity,
            "title": "High overlap detected between your mutual funds",
            "description": f"{len(pairs)} overlapping fund pairs found",
            "impact": impact_text,
            "affected_assets": affected_assets,
            "details": {
                "max_overlap_pct": max_overlap,
                "overlap_pairs_count": len(pairs),
                "compression_score": compression_score,
                "top_pair": {
                    "fund_a": top_pair["a_name"],
                    "fund_b": top_pair["b_name"],
                    "overlap_pct": top_pair["overlap_pct"],
                    "shared_stocks": top_pair["shared_count"],
                }
            },
            "suggested_actions": [
                {
                    "type": "EXIT",
                    "target": top_pair["a"],  # instrument_id
                    "reason": "HIGH_OVERLAP",
                }
            ]
        }


# ══════════════════════════════════════════════════════════════════════════
# SIGNAL 2: OVEREXPOSURE / CONCENTRATION DETECTOR
# ══════════════════════════════════════════════════════════════════════════

class OverexposureSignalDetector(SignalDetector):
    """Detects overexposure to stocks or sectors."""
    
    @property
    def signal_type(self) -> str:
        return "OVEREXPOSURE"
    
    @property
    def priority(self) -> int:
        return 2
    
    def detect(self, portfolio_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Detect overexposure signal."""
        intelligence = portfolio_data.get("portfolio_intelligence", {})
        top_stocks = intelligence.get("top_stocks", [])
        sector_exposure = intelligence.get("sector_exposure", [])
        
        # Check stock concentration
        max_stock_pct = max((s["exposure_pct"] for s in top_stocks), default=0) if top_stocks else 0
        
        # Check sector concentration
        max_sector_pct = max((s["pct"] for s in sector_exposure), default=0) if sector_exposure else 0
        
        # Thresholds
        stock_threshold_high = 15
        stock_threshold_medium = 10
        sector_threshold_high = 40
        sector_threshold_medium = 30
        
        # Determine severity
        if max_stock_pct >= stock_threshold_high or max_sector_pct >= sector_threshold_high:
            severity = "HIGH"
            issue_type = "stock" if max_stock_pct >= stock_threshold_high else "sector"
        elif max_stock_pct >= stock_threshold_medium or max_sector_pct >= sector_threshold_medium:
            severity = "MEDIUM"
            issue_type = "stock" if max_stock_pct >= stock_threshold_medium else "sector"
        else:
            return None  # No significant overexposure
        
        # Build signal based on issue type
        if issue_type == "stock":
            top_stock = max(top_stocks, key=lambda s: s["exposure_pct"])
            title = f"Overexposed to {top_stock['name']}"
            description = f"{max_stock_pct:.1f}% of portfolio in one stock"
            impact = f"{max_stock_pct:.1f}% concentration (target: <10%)"
            affected_assets = [top_stock['name']]
            details = {
                "stock_name": top_stock['name'],
                "exposure_pct": max_stock_pct,
                "exposure_rs": top_stock['exposure_rs'],
                "target_pct": 10.0,
                "fund_count": top_stock.get('fund_count', 0),
            }
        else:  # sector
            top_sector = max(sector_exposure, key=lambda s: s["pct"])
            title = f"Overexposed to {top_sector['sector']} sector"
            description = f"{max_sector_pct:.1f}% of portfolio in one sector"
            impact = f"{max_sector_pct:.1f}% concentration (target: <25%)"
            affected_assets = []  # Could list top stocks in this sector
            details = {
                "sector": top_sector['sector'],
                "exposure_pct": max_sector_pct,
                "exposure_rs": top_sector['rs'],
                "target_pct": 25.0,
            }
        
        return {
            "signal_id": f"exposure_{issue_type}",
            "type": self.signal_type,
            "severity": severity,
            "title": title,
            "description": description,
            "impact": impact,
            "affected_assets": affected_assets,
            "details": details,
            "suggested_actions": [
                {
                    "type": "EXIT",
                    "reason": "OVEREXPOSURE",
                }
            ]
        }


# ══════════════════════════════════════════════════════════════════════════
# SIGNAL 3: QUALITY / PERFORMANCE DETECTOR
# ══════════════════════════════════════════════════════════════════════════

class QualitySignalDetector(SignalDetector):
    """Detects underperforming or low-quality funds."""
    
    @property
    def signal_type(self) -> str:
        return "QUALITY_ISSUES"
    
    @property
    def priority(self) -> int:
        return 3
    
    def detect(self, portfolio_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Detect quality/performance signal."""
        intelligence = portfolio_data.get("portfolio_intelligence", {})
        mf_investments = intelligence.get("mf_investments", [])
        catalog = intelligence.get("catalog", {})
        
        if not mf_investments:
            return None
        
        weak_funds = []
        
        # Check each fund for quality issues
        for mf in mf_investments:
            if not mf.get("resolved"):
                continue
            
            instrument_id = mf.get("instrument_id")
            fund_data = catalog.get(instrument_id, {})
            ratios = fund_data.get("ratios", {})
            
            # Check performance
            ret_1y = ratios.get("ret_1y")
            expense_ratio = mf.get("expense_ratio")
            
            # Criteria for weak fund
            is_weak = False
            reasons = []
            
            if ret_1y is not None and float(ret_1y) < 8:
                is_weak = True
                reasons.append(f"Low returns: {ret_1y}%")
            
            if expense_ratio is not None and float(expense_ratio) > 1.5:
                is_weak = True
                reasons.append(f"High cost: {expense_ratio}%")
            
            if is_weak:
                weak_funds.append({
                    "fund_id": instrument_id,
                    "fund_name": mf.get("scheme_name"),
                    "amount_rs": mf.get("amount_rs", 0),
                    "reasons": reasons,
                    "ret_1y": ret_1y,
                    "expense_ratio": expense_ratio,
                })
        
        if not weak_funds:
            return None
        
        # Calculate severity
        weak_count = len(weak_funds)
        total_weak_amount = sum(f["amount_rs"] for f in weak_funds)
        
        if weak_count >= 3 or total_weak_amount > 500000:
            severity = "HIGH"
        elif weak_count >= 2 or total_weak_amount > 200000:
            severity = "MEDIUM"
        else:
            severity = "LOW"
        
        # Build signal
        top_weak = weak_funds[0]  # Most problematic
        
        return {
            "signal_id": f"quality_{weak_count}",
            "type": self.signal_type,
            "severity": severity,
            "title": f"{weak_count} underperforming fund{'s' if weak_count > 1 else ''} detected",
            "description": "Funds not meeting performance benchmarks",
            "impact": f"₹{total_weak_amount:,.0f} in weak performers",
            "affected_assets": [f["fund_name"] for f in weak_funds],
            "details": {
                "weak_funds_count": weak_count,
                "total_amount": total_weak_amount,
                "top_weak_fund": {
                    "name": top_weak["fund_name"],
                    "amount": top_weak["amount_rs"],
                    "reasons": top_weak["reasons"],
                    "ret_1y": top_weak["ret_1y"],
                    "expense_ratio": top_weak["expense_ratio"],
                }
            },
            "suggested_actions": [
                {
                    "type": "EXIT",
                    "target": top_weak["fund_id"],
                    "reason": "WEAK_PERFORMANCE",
                }
            ]
        }


# ══════════════════════════════════════════════════════════════════════════
# SIGNAL REGISTRY & GENERATION
# ══════════════════════════════════════════════════════════════════════════

# Plugin registry - Add new detectors here!
SIGNAL_DETECTORS: List[SignalDetector] = [
    OverlapSignalDetector(),
    OverexposureSignalDetector(),
    QualitySignalDetector(),
    # Future signals - just add here:
    # CostSignalDetector(),
    # TaxSignalDetector(),
    # AllocationSignalDetector(),
]


def generate_signals(portfolio_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Generate all signals from portfolio data.
    
    Args:
        portfolio_data: {
            "portfolio_intelligence": {...},
            "holdings": [...],
            "total_value": 5200000,
        }
    
    Returns:
        List of detected signals, sorted by priority and severity
    """
    signals = []
    
    # Run all detectors
    for detector in SIGNAL_DETECTORS:
        try:
            signal = detector.detect(portfolio_data)
            if signal:
                # Add detector priority for sorting
                signal["_priority"] = detector.priority
                signals.append(signal)
                logger.info("Signal detected: %s - %s", signal['type'], signal['severity'])
        except Exception as e:
            logger.error("Error in %s detector: %s", detector.signal_type, e)
            continue
    
    # Sort by severity (HIGH > MEDIUM > LOW) then by priority
    severity_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    signals.sort(key=lambda s: (severity_order.get(s["severity"], 3), s["_priority"]))
    
    # Remove internal priority field
    for s in signals:
        s.pop("_priority", None)
    
    logger.info("Generated %s signals", len(signals))
    return signals


def get_signal_summary(signals: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Get a summary of detected signals.
    
    Returns:
        {
            "total_signals": 3,
            "high_severity": 1,
            "medium_severity": 1,
            "low_severity": 1,
            "types": ["OVERLAP_REDUNDANCY", "OVEREXPOSURE", "QUALITY_ISSUES"],
            "total_impact_rs": 730000,
        }
    """
    if not signals:
        return {
            "total_signals": 0,
            "high_severity": 0,
            "medium_severity": 0,
            "low_severity": 0,
            "types": [],
            "total_impact_rs": 0,
        }
    
    high_count = sum(1 for s in signals if s["severity"] == "HIGH")
    medium_count = sum(1 for s in signals if s["severity"] == "MEDIUM")
    low_count = sum(1 for s in signals if s["severity"] == "LOW")
    
    types = [s["type"] for s in signals]
    
    # Try to extract total impact in ₹
    total_impact_rs = 0
    for s in signals:
        impact_text = s.get("impact", "")
        # Simple extraction of ₹ amounts (rough estimate)
        if "₹" in impact_text:
            try:
                amount_str = impact_text.split("₹")[1].split()[0].replace(",", "").replace("L", "00000").replace("K", "000")
                total_impact_rs += float(amount_str)
            except (IndexError, ValueError):
                pass
    
    return {
        "total_signals": len(signals),
        "high_severity": high_count,
        "medium_severity": medium_count,
        "low_severity": low_count,
        "types": types,
        "total_impact_rs": round(total_impact_rs, 0),
    }
