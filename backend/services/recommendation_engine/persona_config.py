"""
Persona-calibrated threshold catalog for the recommendation engine.

PRD §3 — Two persona dimensions:
  - Risk persona (primary axis): sets target allocation + action thresholds
  - Behavioural persona (modifier): changes instruments + tone, not targets

PRD §6 — Per-persona rule sets (all values are tunable defaults).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


# ── Risk persona types (PRD §3.1) ────────────────────────────────────────────

class RiskPersonaType(str, Enum):
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    BALANCED = "balanced"
    GROWTH = "growth"
    AGGRESSIVE = "aggressive"


# ── Behavioural persona types (PRD §3.2) ─────────────────────────────────────

class BehaviouralPersonaType(str, Enum):
    MUTUAL_FUND_INVESTOR = "mutual_fund_investor"
    DIRECT_EQUITY_INVESTOR = "direct_equity_investor"
    ACTIVE_TRADER = "active_trader"
    INCOME_DIVIDEND_SEEKER = "income_dividend_seeker"
    NEW_FIRST_TIME = "new_first_time"
    UNKNOWN = "unknown"


# ── Category suitability sets (PRD §6.1) ─────────────────────────────────────
# Equity sub-categories allowed per risk persona.
# Funds NOT in the allowed set for a persona → suitability gate → EXIT trigger.
EQUITY_CATEGORIES_BY_PERSONA: Dict[RiskPersonaType, List[str]] = {
    RiskPersonaType.CONSERVATIVE: [
        "large cap", "index", "large & mid cap",
    ],
    RiskPersonaType.MODERATE: [
        "large cap", "index", "large & mid cap", "flexi cap", "multi cap",
        "mid cap",   # ≤25% of equity allowed
    ],
    RiskPersonaType.BALANCED: [
        "large cap", "index", "large & mid cap", "flexi cap", "multi cap",
        "mid cap", "small cap",  # capped — engine checks weight
    ],
    RiskPersonaType.GROWTH: [
        "large cap", "index", "large & mid cap", "flexi cap", "multi cap",
        "mid cap", "small cap", "sectoral", "thematic",
    ],
    RiskPersonaType.AGGRESSIVE: [
        "large cap", "index", "large & mid cap", "flexi cap", "multi cap",
        "mid cap", "small cap", "sectoral", "thematic", "elss",
    ],
}

# Sub-category weight caps within equity (PRD §6.1)
# {persona: {sub_category_keyword: max_pct_of_equity}}
EQUITY_SUB_CAPS: Dict[RiskPersonaType, Dict[str, float]] = {
    RiskPersonaType.CONSERVATIVE: {
        "mid cap": 5.0,
        "small cap": 0.0,
        "sectoral": 0.0,
        "thematic": 0.0,
    },
    RiskPersonaType.MODERATE: {
        "mid cap": 25.0,
        "small cap": 10.0,
        "sectoral": 5.0,
        "thematic": 5.0,
    },
    RiskPersonaType.BALANCED: {
        "mid cap": 30.0,
        "small cap": 15.0,
        "sectoral": 10.0,
        "thematic": 10.0,
    },
    RiskPersonaType.GROWTH: {
        "mid cap": 35.0,
        "small cap": 25.0,
        "sectoral": 15.0,
        "thematic": 15.0,
    },
    RiskPersonaType.AGGRESSIVE: {
        "mid cap": 40.0,
        "small cap": 35.0,
        "sectoral": 25.0,
        "thematic": 25.0,
    },
}


@dataclass
class RiskPersonaProfile:
    """
    All thresholds and targets for one risk persona tier.

    Engines read these from ctx.persona_profile instead of hardcoding.
    PRD §6.1 (target allocation) + §6.2 (action-trigger calibration).
    """
    persona_type: RiskPersonaType

    # ── Target allocation ranges (PRD §6.1) ──────────────────────────────────
    equity_target_pct: Tuple[float, float]   # (min%, max%) e.g. (40, 50)
    debt_target_pct: Tuple[float, float]
    gold_alt_target_pct: Tuple[float, float]

    # Large-cap minimum as % of equity allocation
    large_cap_min_of_equity_pct: float

    # ── Action-trigger calibration (PRD §6.2) ─────────────────────────────────
    # V3 quality_score thresholds (0–100 NIDP scale)
    exit_quality_threshold: float   # exit if quality_score < this
    add_quality_threshold: float    # add if quality_score >= this

    # Category rank thresholds (percentile, 0–100; lower rank = better)
    exit_rank_threshold: float      # exit if category_rank > this percentile
    add_rank_threshold: float       # add if category_rank <= this percentile

    # Concentration limits
    max_single_holding_pct: float   # max % of total portfolio in one fund/stock
    max_single_sector_pct: float    # max % of equity in one sector
    target_holdings_min: int        # recommended min number of holdings
    target_holdings_max: int        # recommended max number of holdings

    # ── Volatility & drawdown caps (used by RiskAlignmentEngine RA-2/RA-3) ───
    max_volatility_1y_pct: float
    max_drawdown_pct: float

    # ── Small/mid-cap concentration caps (RA-1) ───────────────────────────────
    smallcap_cap_pct: float         # max % of portfolio in small-cap funds
    sectoral_cap_pct: float         # max % of portfolio in sectoral/thematic funds

    # ── Confidence gating (PRD §10) ──────────────────────────────────────────
    # EXIT value (in ₹) above which medium-confidence persona triggers confirmation
    confirmation_threshold_rs: float = 500_000.0

    # ── Allowed equity categories (derived from global map) ──────────────────
    allowed_equity_categories: List[str] = field(default_factory=list)
    equity_sub_caps: Dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.allowed_equity_categories:
            self.allowed_equity_categories = EQUITY_CATEGORIES_BY_PERSONA.get(
                self.persona_type, []
            )
        if not self.equity_sub_caps:
            self.equity_sub_caps = EQUITY_SUB_CAPS.get(self.persona_type, {})

    def category_allowed(self, category_str: str) -> bool:
        """True if the fund category is permitted for this persona."""
        cat = (category_str or "").lower().strip()
        return any(allowed in cat or cat in allowed for allowed in self.allowed_equity_categories)

    def equity_subcap(self, sub_category_keyword: str) -> float:
        """Max % of equity for a sub-category keyword. Returns 100 if uncapped."""
        kw = sub_category_keyword.lower()
        for key, cap in self.equity_sub_caps.items():
            if key in kw or kw in key:
                return cap
        return 100.0

    @property
    def equity_mid_target(self) -> float:
        """Midpoint of equity target range."""
        return (self.equity_target_pct[0] + self.equity_target_pct[1]) / 2.0

    @property
    def debt_mid_target(self) -> float:
        return (self.debt_target_pct[0] + self.debt_target_pct[1]) / 2.0


# ── Canonical profile catalog (PRD §6.1 + §6.2) ──────────────────────────────
# Thresholds are tunable defaults. quality_score is on NIDP 0–100 scale.
PERSONA_PROFILES: Dict[RiskPersonaType, RiskPersonaProfile] = {

    RiskPersonaType.CONSERVATIVE: RiskPersonaProfile(
        persona_type=RiskPersonaType.CONSERVATIVE,
        equity_target_pct=(25.0, 35.0),
        debt_target_pct=(55.0, 65.0),
        gold_alt_target_pct=(5.0, 10.0),
        large_cap_min_of_equity_pct=100.0,   # large-cap/index only
        exit_quality_threshold=60.0,          # exit if quality_score < 60
        add_quality_threshold=75.0,           # add if quality_score >= 75
        exit_rank_threshold=65.0,             # exit if category_rank percentile > 65
        add_rank_threshold=25.0,              # add if category_rank percentile <= 25
        max_single_holding_pct=5.0,
        max_single_sector_pct=20.0,
        target_holdings_min=8,
        target_holdings_max=12,
        max_volatility_1y_pct=10.0,
        max_drawdown_pct=15.0,
        smallcap_cap_pct=0.0,
        sectoral_cap_pct=0.0,
        confirmation_threshold_rs=200_000.0,
    ),

    RiskPersonaType.MODERATE: RiskPersonaProfile(
        persona_type=RiskPersonaType.MODERATE,
        equity_target_pct=(40.0, 50.0),
        debt_target_pct=(40.0, 50.0),
        gold_alt_target_pct=(5.0, 10.0),
        large_cap_min_of_equity_pct=65.0,
        exit_quality_threshold=55.0,
        add_quality_threshold=70.0,
        exit_rank_threshold=70.0,
        add_rank_threshold=30.0,
        max_single_holding_pct=8.0,
        max_single_sector_pct=25.0,
        target_holdings_min=12,
        target_holdings_max=16,
        max_volatility_1y_pct=18.0,
        max_drawdown_pct=25.0,
        smallcap_cap_pct=10.0,
        sectoral_cap_pct=5.0,
        confirmation_threshold_rs=500_000.0,
    ),

    RiskPersonaType.BALANCED: RiskPersonaProfile(
        persona_type=RiskPersonaType.BALANCED,
        equity_target_pct=(55.0, 65.0),
        debt_target_pct=(25.0, 35.0),
        gold_alt_target_pct=(3.0, 8.0),
        large_cap_min_of_equity_pct=50.0,
        exit_quality_threshold=50.0,
        add_quality_threshold=65.0,
        exit_rank_threshold=75.0,
        add_rank_threshold=35.0,
        max_single_holding_pct=10.0,
        max_single_sector_pct=30.0,
        target_holdings_min=15,
        target_holdings_max=20,
        max_volatility_1y_pct=22.0,
        max_drawdown_pct=30.0,
        smallcap_cap_pct=15.0,
        sectoral_cap_pct=10.0,
        confirmation_threshold_rs=750_000.0,
    ),

    RiskPersonaType.GROWTH: RiskPersonaProfile(
        persona_type=RiskPersonaType.GROWTH,
        equity_target_pct=(70.0, 80.0),
        debt_target_pct=(15.0, 25.0),
        gold_alt_target_pct=(0.0, 5.0),
        large_cap_min_of_equity_pct=40.0,
        exit_quality_threshold=45.0,
        add_quality_threshold=60.0,
        exit_rank_threshold=80.0,
        add_rank_threshold=40.0,
        max_single_holding_pct=12.0,
        max_single_sector_pct=35.0,
        target_holdings_min=18,
        target_holdings_max=22,
        max_volatility_1y_pct=28.0,
        max_drawdown_pct=38.0,
        smallcap_cap_pct=25.0,
        sectoral_cap_pct=15.0,
        confirmation_threshold_rs=1_000_000.0,
    ),

    RiskPersonaType.AGGRESSIVE: RiskPersonaProfile(
        persona_type=RiskPersonaType.AGGRESSIVE,
        equity_target_pct=(80.0, 90.0),
        debt_target_pct=(5.0, 15.0),
        gold_alt_target_pct=(0.0, 5.0),
        large_cap_min_of_equity_pct=30.0,
        exit_quality_threshold=40.0,
        add_quality_threshold=55.0,
        exit_rank_threshold=85.0,
        add_rank_threshold=45.0,
        max_single_holding_pct=15.0,
        max_single_sector_pct=40.0,
        target_holdings_min=20,
        target_holdings_max=25,
        max_volatility_1y_pct=35.0,
        max_drawdown_pct=50.0,
        smallcap_cap_pct=35.0,
        sectoral_cap_pct=25.0,
        confirmation_threshold_rs=2_000_000.0,
    ),
}


def classify_risk_persona(
    risk_profile_str: Optional[str] = None,
    risk_score: Optional[float] = None,
) -> RiskPersonaType:
    """
    Map the stored risk profile to a 5-tier RiskPersonaType.

    Priority:
    1. If risk_score (0-100) is provided, use score ranges.
    2. Else, fall back to matching risk_profile_str.

    Our questionnaire scoring (routes/user.py):
      >75 → Conservative, 61-75 → Moderately Conservative,
      41-60 → Moderate, 26-45 → Moderately Aggressive, ≤25 → Aggressive
    (Note: higher score = more conservative on our current questionnaire)
    """
    if risk_score is not None:
        s = float(risk_score)
        if s >= 70:
            return RiskPersonaType.CONSERVATIVE
        if s >= 55:
            return RiskPersonaType.MODERATE
        if s >= 40:
            return RiskPersonaType.BALANCED
        if s >= 25:
            return RiskPersonaType.GROWTH
        return RiskPersonaType.AGGRESSIVE

    # String fallback
    if risk_profile_str:
        rp = risk_profile_str.lower().replace("-", " ").replace("_", " ")
        if "conservative" in rp:
            return RiskPersonaType.CONSERVATIVE
        if "moderate" in rp and "aggressive" not in rp:
            return RiskPersonaType.MODERATE
        if "balanced" in rp:
            return RiskPersonaType.BALANCED
        if "growth" in rp or "moderately aggressive" in rp:
            return RiskPersonaType.GROWTH
        if "aggressive" in rp:
            return RiskPersonaType.AGGRESSIVE
        # Legacy single-word mappings
        if rp in ("low", "safe"):
            return RiskPersonaType.CONSERVATIVE
        if rp in ("medium",):
            return RiskPersonaType.MODERATE
        if rp in ("high", "very high"):
            return RiskPersonaType.AGGRESSIVE

    return RiskPersonaType.MODERATE  # safe default


def get_persona_profile(
    risk_profile_str: Optional[str] = None,
    risk_score: Optional[float] = None,
) -> Optional[RiskPersonaProfile]:
    """Classify and return the matching RiskPersonaProfile.

    Returns None when neither a risk_score nor a meaningful risk_profile_str is
    present — this signals the orchestrator's mandatory-gate (AC-1) that the user
    has not yet completed their risk assessment.
    """
    has_score = risk_score is not None
    has_str = bool(risk_profile_str and risk_profile_str.strip())
    if not has_score and not has_str:
        return None  # no profile set → orchestrator emits requires_persona gate flag
    persona_type = classify_risk_persona(risk_profile_str, risk_score)
    return PERSONA_PROFILES[persona_type]


def map_behavioural_persona(persona_str: Optional[str]) -> BehaviouralPersonaType:
    """Map free-form persona string to BehaviouralPersonaType enum."""
    if not persona_str:
        return BehaviouralPersonaType.UNKNOWN
    p = persona_str.lower().replace("-", "_").replace(" ", "_")
    if "mutual" in p or "mf" in p:
        return BehaviouralPersonaType.MUTUAL_FUND_INVESTOR
    if "equity" in p or "stock" in p or "direct" in p:
        return BehaviouralPersonaType.DIRECT_EQUITY_INVESTOR
    if "trader" in p or "swing" in p or "intraday" in p:
        return BehaviouralPersonaType.ACTIVE_TRADER
    if "income" in p or "dividend" in p:
        return BehaviouralPersonaType.INCOME_DIVIDEND_SEEKER
    if "new" in p or "beginner" in p or "first" in p:
        return BehaviouralPersonaType.NEW_FIRST_TIME
    return BehaviouralPersonaType.UNKNOWN
