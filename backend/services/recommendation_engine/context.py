"""
RecommendationContext and supporting dataclasses.

Built once in generate_plan() and passed immutably to every engine.
Engines are pure: they read context, emit EngineSignals, do no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from services.goal_engine import GoalEvaluation
    from services.deviation_engine import DeviationResult
    from services.recommendation_engine.persona_config import RiskPersonaProfile, BehaviouralPersonaType


@dataclass
class HoldingWeight:
    """Pre-computed allocation weight for one holding (PRD PI-1)."""
    instrument_id: Optional[str]
    instrument_name: str
    current_rs: float
    weight_pct: float
    # PRD PI-1 multipliers: <2%=0.4, 2-5%=0.7, 5-10%=1.0, 10-20%=1.3, >20%=1.7
    allocation_multiplier: float


@dataclass
class EngineSignal:
    """
    One recommendation signal emitted by a single engine.

    Engines emit raw base_score (0–10). PortfolioImpactEngine multiplies it
    in-place by allocation_multiplier × goal_multiplier × risk_multiplier.
    ArbitrationEngine then deduplicates by dedup_key.
    """
    signal_id: str                        # "<engine>::<isin>" or similar
    engine_name: str                      # e.g. "OverlapEngine"
    rule_label: str                       # e.g. "Rule 4"
    action_type: str                      # "EXIT"|"ADD"|"TRIM"|"HOLD"|"SWITCH"
    instrument_id: Optional[str]
    instrument_name: str
    amount_rs: float
    base_score: float                     # 0–10; multiplied in-place by PI engine
    confidence: float                     # 0–1; 0.9=HIGH, 0.6=MED, 0.3=LOW

    # AR-3 priority formula weights
    risk_reduction: float = 0.0           # weight 30%
    diversification_gain: float = 0.0    # weight 25%
    goal_impact: float = 0.0             # weight 20%
    urgency: float = 0.0                 # weight 15%
    implementation_ease: float = 0.0     # weight 10%

    estimated_tax_rs: float = 0.0
    is_tax_harvesting: bool = False

    reason_codes: List[str] = field(default_factory=list)
    reason_text: str = ""

    suppressed: bool = False
    suppression_reason: Optional[str] = None

    # Phase 5 (D-5): deferred action — signal is active but cannot execute now.
    # defer_reason is non-empty when a fund should be exited but is lock-in or
    # STCG-blocked. The action shows in the plan with a Clock icon and explanation.
    defer_reason: Optional[str] = None
    # execution_date: ISO date string (YYYY-MM-DD) for scheduled/staged exits
    execution_date: Optional[str] = None

    # Dedup key for AR-1: same key means same "slot"; highest base_score wins.
    # Default: "<action_type>::<instrument_id>"
    dedup_key: str = ""

    # ── PRD output contract fields (PRD §12) ─────────────────────────────────
    # severity: aligned | minor | mismatch | severe  (PRD §8)
    severity: str = "minor"
    # execution_path: redirect | harvest | stagger | sell-now  (PRD §9)
    execution_path: str = "sell-now"
    # requires_confirmation: True when persona confidence is medium + EXIT is large  (PRD §10)
    requires_confirmation: bool = False

    # Goal linkage — set by GoalAlignmentEngine so action cards can show "for [goal]"
    goal_id: Optional[str] = None
    goal_name: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.dedup_key:
            self.dedup_key = f"{self.action_type}::{self.instrument_id or self.instrument_name}"

    @property
    def ar3_priority(self) -> float:
        """AR-3 composite priority score (higher = act first)."""
        return (
            0.30 * self.risk_reduction
            + 0.25 * self.diversification_gain
            + 0.20 * self.goal_impact
            + 0.15 * self.urgency
            + 0.10 * self.implementation_ease
        ) * self.base_score


@dataclass
class RecommendationContext:
    """
    Immutable (by convention) snapshot of everything an engine needs.

    Built once in generate_plan() before any engine runs. All fields
    that require async I/O (DB, scoring) are resolved before construction.
    """
    user_id: str
    risk_profile: str
    total_value_rs: float

    holdings: List[Dict[str, Any]]
    mf_holdings: List[Dict[str, Any]]
    stock_holdings: List[Dict[str, Any]]

    # From portfolio_intelligence.compute_portfolio_intelligence()
    portfolio_intelligence: Dict[str, Any]

    # From decision_engine.calculate_mf_exit_score() — already guardrail-filtered
    exit_candidates: List[Dict[str, Any]]

    # From v3_integration.enrich_candidates_with_v3()
    v3_scores: Dict[str, Dict[str, Any]]

    # Pre-computed PI-1 multipliers (keyed by instrument_id or name-normalised key)
    holding_weights: Dict[str, HoldingWeight]

    # From goal_engine.evaluate_goal() for each active goal
    goal_evaluations: List[Any]   # List[GoalEvaluation] — avoid circular import

    # From deviation_engine.compute_deviation() — may be None if no targets set
    deviation_result: Optional[Any]  # Optional[DeviationResult]

    # Live admin-tunable rule thresholds (from rules_config.get_config())
    rules_cfg: Dict[str, Any]

    # From signal_detector.generate_signals()
    signals: List[Dict[str, Any]]

    # ── Pre-fetched look-up tables (async I/O done before engine run) ────
    # Populated by orchestrator.build_context(); engines read, never write.
    # List of rows from db.international_funds_cache — needed by InternationalEngine.
    international_funds_cache: List[Dict[str, Any]] = field(default_factory=list)

    # ── Data validation state (populated in build_context, read by engines) ──
    # instrument_ids whose EXIT/tax-aware signals should be suppressed (DV-3)
    tax_suppressed_instrument_ids: set = field(default_factory=set)
    # Fraction of portfolio value with a valid current_price (DV-1)
    portfolio_coverage_pct: float = 100.0
    # Pre-fetched pairwise correlation rows from graph.correlations (CR-1)
    # Each row: {left_security_id, right_security_id, correlation_value, abs_correlation, window_days}
    portfolio_correlations: List[Dict[str, Any]] = field(default_factory=list)

    # Pre-fetched live ADD candidates from NIDP DaaS, keyed by normalised category
    # (e.g. "debt", "large cap", "equity").  Populated by orchestrator; engines read only.
    # Falls back to static defaults inside each engine when empty.
    top_add_candidates: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)

    # ── Mutable dedup state (written by orchestrator only, never by engines) ──
    exited_ids: set = field(default_factory=set)
    exited_holding_keys: set = field(default_factory=set)
    added_buckets: set = field(default_factory=set)

    # ── Persona context (PRD §3) ───────────────────────────────────────────────
    # Resolved RiskPersonaProfile — carries all PRD §6.1/§6.2 thresholds.
    # None only when no risk profile has been set by the user (mandatory gate, PRD §4 Rule 1).
    persona_profile: Optional[Any] = None   # RiskPersonaProfile (avoid circular at runtime)

    # Numeric risk score (0-100) from the questionnaire (higher = more conservative)
    risk_score_numeric: Optional[float] = None

    # Behavioural persona string (e.g. "mutual_fund_investor") + detection confidence (0-1)
    behavioural_persona: str = "unknown"
    behavioural_confidence: float = 0.0

    # PRD §4.4: capacity vs tolerance split
    capacity_score: float = 50.0
    tolerance_score: float = 50.0
    # True when |capacity - tolerance| >= 15 — engines should flag this to user
    capacity_tolerance_diverged: bool = False

    # Pipeline telemetry — written by engines/orchestrator for observability.
    # Keys: "skipped:no_target", "ran:no_drift", "ran:actions_emitted"
    telemetry: dict = field(default_factory=dict)

    # Phase 4 confidence tier — set by orchestrator from TargetAllocation
    confidence_tier: str = "generic"
    confidence_label: str = "Generic plan — add your profile"
    # numeric confidence score (0-100) from the four-tier ladder
    plan_confidence_score: float = 40.0

    # D-4 user overrides (level 0 precedence): {instrument_id: {"reason": str, "timestamp": str}}
    # Set by the API layer from user_profile.recommendation_overrides.
    # An override suppresses EXIT/TRIM on that instrument regardless of engine verdict.
    # Must be per-fund and timestamped (no blanket "ignore suitability" toggle).
    user_overrides: dict = field(default_factory=dict)
