"""Shared contracts for the Autonomous Trading Desk: enums, the event envelope, the agent task, and the domain records
(signal, trade plan, risk assessment, approval, simulation).

Every module codes against these models. Money, prices and quantities are Decimal (PRD §16.7, architecture §8.4);
they serialise to strings in JSON. Timestamps are timezone-aware UTC datetimes; IST is only for display.

Words: identifiers follow the PRD (stop, target, entry). Generated narrative text uses neutral words (see DESIGN.md §9).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    """Opaque ids with a readable prefix, e.g. SIG-3f2a…  (uuid4 hex, 20 chars kept)."""
    return f"{prefix}-{uuid4().hex[:20]}"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False, use_enum_values=False)


# ── Enums ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

class AccountKind(str, Enum):
    PAPER = "PAPER"            # the desk's own paper account (real-time sessions)
    SIMULATION = "SIMULATION"  # one per simulation run; carries simulation_id
    SHADOW = "SHADOW"          # live-shadow hypothetical book (Phase 4)
    # There is deliberately no LIVE kind: brokers are read-only for this product (owner rule).


class OperatingMode(str, Enum):
    RESEARCH = "RESEARCH"                  # signals + plans + risk reports; never approves
    ASSISTED = "ASSISTED"                  # a human approves every plan
    AUTONOMOUS_PAPER = "AUTONOMOUS_PAPER"  # policy may auto-approve within its thresholds; paper engine only


class SimulationMode(str, Enum):
    HISTORICAL_REPLAY = "HISTORICAL_REPLAY"
    ACCELERATED_REPLAY = "ACCELERATED_REPLAY"
    SCENARIO = "SCENARIO"
    LIVE_SHADOW = "LIVE_SHADOW"


class SimulationStatus(str, Enum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AgentKey(str, Enum):
    AI_TRADER = "AI_TRADER"
    TRADING_ASSISTANT = "TRADING_ASSISTANT"
    RISK_OPS = "RISK_OPS"
    MIDDLE_OFFICE = "MIDDLE_OFFICE"
    TECH_SUPPORT = "TECH_SUPPORT"


ORCHESTRATOR = "ORCHESTRATOR"  # the requesting side of every task; not an agent


class AgentStatus(str, Enum):
    IDLE = "IDLE"
    BUSY = "BUSY"
    SCALING = "SCALING"
    DEGRADED = "DEGRADED"
    MAINTENANCE = "MAINTENANCE"
    QUARANTINED = "QUARANTINED"
    OFFLINE = "OFFLINE"


class TaskState(str, Enum):
    CREATED = "CREATED"
    ASSIGNED = "ASSIGNED"
    ACCEPTED = "ACCEPTED"
    RUNNING = "RUNNING"
    RESULT_READY = "RESULT_READY"
    VALIDATED = "VALIDATED"
    COMPLETED = "COMPLETED"
    # exception states
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"
    TIMED_OUT = "TIMED_OUT"
    RETRY_PENDING = "RETRY_PENDING"
    FAILED = "FAILED"
    ESCALATED = "ESCALATED"
    CANCELLED = "CANCELLED"


TASK_TERMINAL = {TaskState.COMPLETED, TaskState.REJECTED, TaskState.FAILED, TaskState.ESCALATED, TaskState.CANCELLED}

# Allowed task transitions (architecture §11.1). Anything else is refused by the store.
TASK_TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.CREATED: {TaskState.ASSIGNED, TaskState.CANCELLED},
    TaskState.ASSIGNED: {TaskState.ACCEPTED, TaskState.REJECTED, TaskState.ESCALATED, TaskState.TIMED_OUT,
                         TaskState.CANCELLED},
    TaskState.ACCEPTED: {TaskState.RUNNING, TaskState.CANCELLED, TaskState.RETRY_PENDING},
    TaskState.RUNNING: {TaskState.RESULT_READY, TaskState.BLOCKED, TaskState.TIMED_OUT, TaskState.FAILED,
                        TaskState.RETRY_PENDING, TaskState.ESCALATED, TaskState.CANCELLED},
    TaskState.RESULT_READY: {TaskState.VALIDATED, TaskState.FAILED, TaskState.RETRY_PENDING},
    TaskState.VALIDATED: {TaskState.COMPLETED},
    TaskState.BLOCKED: {TaskState.ESCALATED, TaskState.CANCELLED, TaskState.RETRY_PENDING},
    TaskState.TIMED_OUT: {TaskState.RETRY_PENDING, TaskState.ESCALATED, TaskState.FAILED},
    TaskState.RETRY_PENDING: {TaskState.ASSIGNED, TaskState.ESCALATED, TaskState.CANCELLED},
    TaskState.FAILED: set(),
    TaskState.COMPLETED: set(),
    TaskState.REJECTED: set(),
    TaskState.ESCALATED: set(),
    TaskState.CANCELLED: set(),
}


class TaskType(str, Enum):
    PREMARKET_HEALTH_CHECK = "PREMARKET_HEALTH_CHECK"   # TECH_SUPPORT
    SCAN_MARKET = "SCAN_MARKET"                         # AI_TRADER
    GENERATE_STRATEGY = "GENERATE_STRATEGY"             # TRADING_ASSISTANT
    REVISE_STRATEGY = "REVISE_STRATEGY"                 # TRADING_ASSISTANT
    ASSESS_RISK = "ASSESS_RISK"                         # RISK_OPS
    REVIEW_FOR_APPROVAL = "REVIEW_FOR_APPROVAL"         # MIDDLE_OFFICE


# Which agent may receive which task type (agent permissions, PRD §29.5).
TASK_OWNER: dict[TaskType, AgentKey] = {
    TaskType.PREMARKET_HEALTH_CHECK: AgentKey.TECH_SUPPORT,
    TaskType.SCAN_MARKET: AgentKey.AI_TRADER,
    TaskType.GENERATE_STRATEGY: AgentKey.TRADING_ASSISTANT,
    TaskType.REVISE_STRATEGY: AgentKey.TRADING_ASSISTANT,
    TaskType.ASSESS_RISK: AgentKey.RISK_OPS,
    TaskType.REVIEW_FOR_APPROVAL: AgentKey.MIDDLE_OFFICE,
}


class WorkflowKind(str, Enum):
    SESSION_CYCLE = "SESSION_CYCLE"        # one trading session: pre-market check → scan → proposals (Phase 1)
    PREMARKET_CHECK = "PREMARKET_CHECK"
    MARKET_SCAN = "MARKET_SCAN"
    TRADE_PROPOSAL = "TRADE_PROPOSAL"      # one signal → plan → risk (→ revise) → approval decision


class WorkflowState(str, Enum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    WAITING_HUMAN = "WAITING_HUMAN"   # an approval waits for a person
    COMPLETED = "COMPLETED"           # reached its defined end (see outcome)
    BLOCKED = "BLOCKED"               # pre-market blocked / stale data: no new risk
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


WORKFLOW_TERMINAL = {WorkflowState.COMPLETED, WorkflowState.BLOCKED, WorkflowState.FAILED, WorkflowState.CANCELLED}


class Segment(str, Enum):
    CASH = "CASH"
    FUTURES = "FUTURES"
    OPTIONS = "OPTIONS"
    INDEX = "INDEX"


class Direction(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class Timeframe(str, Enum):
    INTRADAY = "INTRADAY"
    POSITIONAL = "POSITIONAL"


class SignalCategory(str, Enum):
    TREND_CONTINUATION = "TREND_CONTINUATION"
    BREAKOUT = "BREAKOUT"
    BREAKDOWN = "BREAKDOWN"
    MOMENTUM_EXPANSION = "MOMENTUM_EXPANSION"
    REVERSAL = "REVERSAL"
    RELATIVE_STRENGTH = "RELATIVE_STRENGTH"
    LONG_BUILDUP = "LONG_BUILDUP"
    SHORT_BUILDUP = "SHORT_BUILDUP"
    SHORT_COVERING = "SHORT_COVERING"
    LONG_UNWINDING = "LONG_UNWINDING"
    UNUSUAL_VOLUME = "UNUSUAL_VOLUME"
    OPTIONS_POSITIONING = "OPTIONS_POSITIONING"
    RANGE_BOUND = "RANGE_BOUND"


class SignalStatus(str, Enum):
    DETECTED = "DETECTED"
    CONSUMED = "CONSUMED"      # a TRADE_PROPOSAL workflow took it
    SUPPRESSED = "SUPPRESSED"  # duplicate / below threshold / stale
    EXPIRED = "EXPIRED"


class StrategyType(str, Enum):
    LONG_EQUITY = "LONG_EQUITY"
    SHORT_EQUITY = "SHORT_EQUITY"          # intraday only, where permitted; not generated in Phase 1
    LONG_FUTURES = "LONG_FUTURES"
    SHORT_FUTURES = "SHORT_FUTURES"
    LONG_CALL = "LONG_CALL"
    LONG_PUT = "LONG_PUT"
    BULL_CALL_SPREAD = "BULL_CALL_SPREAD"
    BEAR_PUT_SPREAD = "BEAR_PUT_SPREAD"
    BULL_PUT_SPREAD = "BULL_PUT_SPREAD"
    BEAR_CALL_SPREAD = "BEAR_CALL_SPREAD"
    COVERED_CALL = "COVERED_CALL"
    CASH_SECURED_PUT = "CASH_SECURED_PUT"
    PROTECTIVE_PUT = "PROTECTIVE_PUT"
    COLLAR = "COLLAR"
    IRON_CONDOR = "IRON_CONDOR"
    IRON_BUTTERFLY = "IRON_BUTTERFLY"
    CALENDAR_SPREAD = "CALENDAR_SPREAD"
    DIAGONAL_SPREAD = "DIAGONAL_SPREAD"


CREDIT_STRATEGIES = {StrategyType.BULL_PUT_SPREAD, StrategyType.BEAR_CALL_SPREAD, StrategyType.IRON_CONDOR,
                     StrategyType.IRON_BUTTERFLY}


class InstrumentKind(str, Enum):
    EQ = "EQ"     # cash equity
    FUT = "FUT"
    CE = "CE"
    PE = "PE"


class LegSide(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    RISK_REVIEW = "RISK_REVIEW"
    NEEDS_REVISION = "NEEDS_REVISION"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"            # Phase 1 ends here: no execution yet
    REJECTED = "REJECTED"
    RESEARCH_ONLY = "RESEARCH_ONLY"  # RESEARCH mode: assessed, never approved
    EXPIRED = "EXPIRED"


class RiskVerdict(str, Enum):
    PASS = "PASS"
    REDUCE = "REDUCE"   # passes at a smaller size than proposed (the assessment carries the size)
    FAIL = "FAIL"


class CheckOutcome(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"   # not applicable or input missing (missing inputs never count as passing evidence)


class ApprovalStatus(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NEEDS_HUMAN_APPROVAL = "NEEDS_HUMAN_APPROVAL"
    NEEDS_REVISION = "NEEDS_REVISION"
    SUSPENDED = "SUSPENDED"


class HealthStatus(str, Enum):
    READY = "READY"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"


# ── Event envelope (architecture §6.2) ────────────────────────────────────────────────────────────────────────────────

class EventType(str, Enum):
    # market / signal
    MARKET_DATA_STALE = "MARKET_DATA_STALE"
    SIGNAL_DETECTED = "SIGNAL_DETECTED"
    SIGNAL_SUPPRESSED = "SIGNAL_SUPPRESSED"
    SIGNAL_EXPIRED = "SIGNAL_EXPIRED"
    # strategy / approval
    TRADE_PLAN_CREATED = "TRADE_PLAN_CREATED"
    TRADE_PLAN_REVISED = "TRADE_PLAN_REVISED"
    RISK_ASSESSMENT_COMPLETED = "RISK_ASSESSMENT_COMPLETED"
    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
    APPROVAL_GRANTED = "APPROVAL_GRANTED"
    APPROVAL_REJECTED = "APPROVAL_REJECTED"
    APPROVAL_NEEDS_HUMAN = "APPROVAL_NEEDS_HUMAN"
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
    # agents / workflow
    TASK_CREATED = "TASK_CREATED"
    TASK_STATE_CHANGED = "TASK_STATE_CHANGED"
    HANDOFF_RECORDED = "HANDOFF_RECORDED"
    WORKFLOW_STARTED = "WORKFLOW_STARTED"
    WORKFLOW_STATE_CHANGED = "WORKFLOW_STATE_CHANGED"
    WORKFLOW_FAILED = "WORKFLOW_FAILED"
    PREMARKET_READY = "PREMARKET_READY"
    PREMARKET_BLOCKED = "PREMARKET_BLOCKED"
    AGENT_UNHEALTHY = "AGENT_UNHEALTHY"
    # simulation
    SIMULATION_CREATED = "SIMULATION_CREATED"
    SIMULATION_STATE_CHANGED = "SIMULATION_STATE_CHANGED"
    CLOCK_ADVANCED = "CLOCK_ADVANCED"
    # account / policy
    ACCOUNT_CREATED = "ACCOUNT_CREATED"
    ACCOUNT_MODE_CHANGED = "ACCOUNT_MODE_CHANGED"
    POLICY_VERSION_CREATED = "POLICY_VERSION_CREATED"


class EventEnvelope(_Model):
    event_id: str = Field(default_factory=lambda: new_id("EVT"))
    event_type: EventType
    event_version: int = 1
    occurred_at: datetime = Field(default_factory=utcnow)    # wall clock
    sim_time: Optional[datetime] = None                      # simulation clock, when simulated
    tenant_id: str
    account_id: Optional[str] = None
    simulation_id: Optional[str] = None                      # null ONLY for non-simulated desk events
    workflow_id: Optional[str] = None
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None
    producer: str
    payload: dict[str, Any] = Field(default_factory=dict)


# ── Agent task (PRD §29.2–29.3, architecture §11) ─────────────────────────────────────────────────────────────────────

class ToolCall(_Model):
    tool: str                               # e.g. "market.daily_bars"
    args: dict[str, Any] = Field(default_factory=dict)
    as_of: Optional[datetime] = None        # point-in-time bound used for the read
    ok: bool = True
    rows: Optional[int] = None
    error: Optional[str] = None
    ms: Optional[int] = None


class TaskSpec(_Model):
    """What the orchestrator asks an agent to do. Persisted BEFORE dispatch."""
    task_id: str = Field(default_factory=lambda: new_id("TASK"))
    workflow_id: str
    simulation_id: Optional[str] = None
    tenant_id: str
    account_id: Optional[str] = None
    from_agent: str = ORCHESTRATOR
    to_agent: AgentKey
    task_type: TaskType
    entity_id: Optional[str] = None
    input_refs: list[str] = Field(default_factory=list)      # e.g. "signal://SIG-…", "plan://TRD-…@2"
    constraints: dict[str, Any] = Field(default_factory=dict)
    required_output_schema: str
    deadline_s: float = 30.0
    max_attempts: int = 2
    sim_time: Optional[datetime] = None                      # the point in time the agent may see data up to
    idempotency_key: Optional[str] = None

    @model_validator(mode="after")
    def _owner(self) -> "TaskSpec":
        if TASK_OWNER[self.task_type] != self.to_agent:
            raise ValueError(f"{self.to_agent.value} may not receive {self.task_type.value}")
        return self


class AgentResult(_Model):
    """What an agent returns. Untrusted until schema + domain validation pass."""
    outcome: Literal["COMPLETED", "REJECTED", "ESCALATED", "BLOCKED"] = "COMPLETED"
    output_schema: str
    output: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""                                        # one-line decision explanation (no chain of thought)
    evidence_refs: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    reason: Optional[str] = None                             # for REJECTED / ESCALATED / BLOCKED


class AgentDescriptor(_Model):
    agent_key: AgentKey
    version: str
    kind: Literal["DETERMINISTIC", "LLM_ASSISTED"]
    model: Optional[str] = None
    prompt_version: Optional[str] = None
    task_types: list[TaskType]
    tools: list[str]
    prohibited: list[str]                                    # human-readable authority limits (PRD §29.5)


# ── Signal (PRD §6.1) ─────────────────────────────────────────────────────────────────────────────────────────────────

class ScoreComponent(_Model):
    dimension: str            # trend / momentum / volume_delivery / relative_strength / structure / derivatives / regime / liquidity
    weight: Decimal
    points: Decimal           # 0..weight
    available: bool           # False → input missing; earns 0 points (never positive evidence)
    detail: str = ""


class Signal(_Model):
    signal_id: str = Field(default_factory=lambda: new_id("SIG"))
    tenant_id: str
    account_id: Optional[str] = None
    simulation_id: Optional[str] = None
    instrument: str                       # underlying symbol, e.g. RELIANCE, NIFTY
    exchange: str = "NSE"
    segment: Segment
    direction: Direction
    timeframe: Timeframe = Timeframe.POSITIONAL
    category: SignalCategory
    signal_score: Decimal                 # 0..100; NOT a probability
    calibrated_probability: Optional[Decimal] = None
    score_breakdown: list[ScoreComponent] = Field(default_factory=list)
    entry_zone: Optional[dict[str, Decimal]] = None      # {"low": .., "high": ..}
    invalidation_price: Optional[Decimal] = None
    targets: list[Decimal] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    reference_price: Optional[Decimal] = None            # last close used
    fno_eligible: bool = False
    sector: Optional[str] = None
    data_as_of: datetime                  # the latest data the signal used (UTC)
    session_date: date                    # the session the signal is for
    model_version: str
    rule_version: str
    expires_at: datetime
    status: SignalStatus = SignalStatus.DETECTED

    @field_validator("signal_score")
    @classmethod
    def _score_range(cls, v: Decimal) -> Decimal:
        if v < 0 or v > 100:
            raise ValueError("signal_score must be within 0..100")
        return v

    def dedupe_key(self) -> str:
        scope = self.simulation_id or self.account_id or self.tenant_id
        return f"{scope}|{self.session_date.isoformat()}|{self.instrument}|{self.segment.value}|{self.direction.value}|{self.category.value}"


# ── Trade plan (PRD §6.2 mandatory fields) ────────────────────────────────────────────────────────────────────────────

class Greeks(_Model):
    delta: Optional[Decimal] = None
    gamma: Optional[Decimal] = None
    theta: Optional[Decimal] = None   # per day, in rupees for the position when on a plan/leg total
    vega: Optional[Decimal] = None
    iv: Optional[Decimal] = None      # decimal (0.18 = 18%)
    model: Optional[str] = None       # e.g. "bs-v1 (model)"


class PlanLeg(_Model):
    leg_id: str
    kind: InstrumentKind
    underlying: str
    tradingsymbol: Optional[str] = None
    expiry: Optional[date] = None
    strike: Optional[Decimal] = None
    side: LegSide
    lots: int = Field(ge=0)
    lot_size: int = Field(ge=1)
    quantity: int = Field(ge=0)            # lots × lot_size (cash: shares, lot_size 1)
    ref_price: Decimal                     # price/premium the plan was built on
    ref_price_source: str                  # e.g. "fno_bhavcopy.close 2026-11-04"
    open_interest: Optional[int] = None
    greeks: Optional[Greeks] = None

    @model_validator(mode="after")
    def _qty(self) -> "PlanLeg":
        if self.quantity != self.lots * self.lot_size:
            raise ValueError(f"leg {self.leg_id}: quantity {self.quantity} != lots {self.lots} × lot_size {self.lot_size}")
        if self.kind in (InstrumentKind.CE, InstrumentKind.PE) and (self.strike is None or self.expiry is None):
            raise ValueError(f"leg {self.leg_id}: an option leg needs strike and expiry")
        if self.kind == InstrumentKind.FUT and self.expiry is None:
            raise ValueError(f"leg {self.leg_id}: a futures leg needs expiry")
        return self


class TargetLevel(_Model):
    level: Decimal                 # underlying price (cash/futures) or structure value, see basis
    basis: Literal["UNDERLYING", "PREMIUM", "PNL_RS"] = "UNDERLYING"
    exit_fraction: Decimal = Decimal("1")   # share of the remaining quantity to exit there


class TradePlanBody(_Model):
    """One immutable plan version. Field numbers refer to PRD §6.2 'Trade Plan mandatory fields'."""
    thesis: str                                           # 1
    rationale: list[str]                                  # 1
    signal_id: Optional[str]                              # 2
    market_context: dict[str, Any]                        # 2 (regime, index trend, VIX, data_as_of)
    account_id: str                                       # 3
    instrument: str                                       # 3 (underlying)
    segment: Segment                                      # 3
    strategy_type: StrategyType                           # 4
    legs: list[PlanLeg] = Field(min_length=1, max_length=4)  # 5 (initial builder limit: 4 legs)
    entry: dict[str, Any]                                 # 6 {order_type, zone_low, zone_high, valid_until, max_slippage_pct}
    invalidation: dict[str, Any]                          # 7 {underlying_level, rule, max_loss_exit_rs}
    targets: list[TargetLevel]                            # 8
    max_loss_rs: Decimal                                  # 9 (per the sized quantity, incl. estimated costs)
    max_profit_rs: Optional[Decimal]                      # 9 (None = unlimited / undefined)
    loss_defined: bool                                    # 9
    breakevens: list[Decimal]                             # 10
    expected_payoff: dict[str, Any]                       # 11 {reward_risk, assumptions[]}
    capital_required_rs: Decimal                          # 12
    margin_estimate: dict[str, Any]                       # 12 {amount_rs, method, source}
    net_greeks: Optional[Greeks] = None                   # 13
    volatility: dict[str, Any] = Field(default_factory=dict)  # 13 {iv_source, atm_iv, vix}
    liquidity: dict[str, Any]                             # 14 {adv_rs, oi, verdict}
    holding: dict[str, Any]                               # 15 {timeframe, max_holding_days, expiry, exit_days_before_expiry}
    exit_rules: dict[str, Any]                            # 16 {trailing, time_exit, emergency}
    risk_warnings: list[str]                              # 17
    plan_expires_at: datetime                             # 18
    provenance: dict[str, Any]                            # 19 {agent, agent_version, rule_version, data_as_of, inputs}
    costs_estimate: dict[str, Any] = Field(default_factory=dict)   # round-trip cost breakdown used in max_loss
    alternatives_considered: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("max_loss_rs")
    @classmethod
    def _positive_loss(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("max_loss_rs must be > 0 (a plan always carries a loss figure)")
        return v


class TradePlanVersion(_Model):
    trade_id: str
    version: int = Field(ge=1)
    body: TradePlanBody
    created_by: str                       # agent key or user:<id>
    change_reason: Optional[str] = None
    supersedes_version: Optional[int] = None
    created_at: datetime = Field(default_factory=utcnow)


# ── Risk assessment (PRD §6.3, architecture §8.3) ─────────────────────────────────────────────────────────────────────

class RiskCheck(_Model):
    name: str
    outcome: CheckOutcome
    value: Optional[Decimal] = None
    limit: Optional[Decimal] = None
    detail: str = ""
    hard: bool = True      # a hard FAIL cannot be overridden by any agent


class RiskAssessment(_Model):
    assessment_id: str = Field(default_factory=lambda: new_id("RSK"))
    trade_id: str
    plan_version: int
    account_id: str
    simulation_id: Optional[str] = None
    verdict: RiskVerdict
    checks: list[RiskCheck]
    sizing: dict[str, Any]                # {proposed_lots, allowed_lots, risk_per_lot_rs, budget_rs, method}
    violations: list[str] = Field(default_factory=list)   # names of FAILed hard checks
    inputs_snapshot: dict[str, Any]       # equity, open risk, exposure, prices + data_as_of …
    policy_id: str
    policy_version: int
    engine_version: str
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


# ── Approval (PRD §6.4, §10.3) ────────────────────────────────────────────────────────────────────────────────────────

class ApprovalScope(_Model):
    tenant_id: str
    account_id: str
    trade_id: str
    plan_version: int
    instrument: str
    strategy_type: StrategyType
    max_lots: int
    max_notional_rs: Decimal
    max_risk_rs: Decimal
    execution_mode: Literal["PAPER", "SIMULATION", "SHADOW"]
    allowed_actions: list[str]            # e.g. ["ENTER", "EXIT_AT_STOP", "EXIT_AT_TARGET", "TRAIL_TIGHTEN"]


class ApprovalDecision(_Model):
    approval_id: str = Field(default_factory=lambda: new_id("APR"))
    trade_id: str
    plan_version: int
    account_id: str
    simulation_id: Optional[str] = None
    status: ApprovalStatus
    decided_by: str                       # "MIDDLE_OFFICE@<version>" or "user:<user_id>"
    reasons: list[str]
    scope: Optional[ApprovalScope] = None   # set only when APPROVED
    risk_assessment_id: Optional[str] = None
    policy_id: Optional[str] = None
    policy_version: Optional[int] = None
    expires_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _scope(self) -> "ApprovalDecision":
        if self.status == ApprovalStatus.APPROVED:
            if self.scope is None or self.expires_at is None:
                raise ValueError("an APPROVED decision must carry its scope and expiry")
            if self.scope.trade_id != self.trade_id or self.scope.plan_version != self.plan_version:
                raise ValueError("approval scope must bind the exact trade and plan version")
        return self


# ── Simulation (PRD §28, §32–34) ──────────────────────────────────────────────────────────────────────────────────────

class SimulationConfig(_Model):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    mode: SimulationMode = SimulationMode.HISTORICAL_REPLAY
    start_date: date
    end_date: date
    # FNO = the stock futures traded on the previous session (point-in-time, no survivorship bias). Index lists
    # (NIFTY50…) use today's members because index membership has no history: survivorship caveat in the results.
    universe: str = "FNO"
    include_fno: bool = True
    starting_capital_rs: Decimal = Decimal("1000000")
    operating_mode: OperatingMode = OperatingMode.AUTONOMOUS_PAPER
    policy_id: Optional[str] = None       # default: the tenant's default policy at create time
    max_proposals_per_session: int = Field(default=5, ge=0, le=50)
    symbols: Optional[list[str]] = None   # optional explicit list (overrides universe), max 50
    seed: int = 42
    speed: Literal["STEP", "ACCELERATED"] = "STEP"

    @model_validator(mode="after")
    def _dates(self) -> "SimulationConfig":
        if self.end_date < self.start_date:
            raise ValueError("end_date is before start_date")
        if self.mode == SimulationMode.LIVE_SHADOW:
            raise ValueError("LIVE_SHADOW is Phase 4 and not available yet")
        if self.mode == SimulationMode.SCENARIO:
            raise ValueError("SCENARIO simulations are Phase 3 and not available yet")
        return self


class ClockPhase(str, Enum):
    """Scheduled points in one simulated session (IST). Phase 1 does work at PREMARKET, SCAN and PROPOSALS."""
    PREMARKET = "PREMARKET"   # 08:30 Tech Support checks data for the session
    SCAN = "SCAN"             # 08:45 AI Trader scans on data published up to then
    PROPOSALS = "PROPOSALS"   # 09:00 Trading Assistant → Risk & Ops → Middle Office per signal
    OPEN = "OPEN"             # 09:15 (Phase 2: entries)
    CLOSE = "CLOSE"           # 15:30
    EOD = "EOD"               # 18:00 expire signals, day summary (Phase 2: reconcile)


CLOCK_SCHEDULE_IST: list[tuple[ClockPhase, str]] = [
    (ClockPhase.PREMARKET, "08:30"),
    (ClockPhase.SCAN, "08:45"),
    (ClockPhase.PROPOSALS, "09:00"),
    (ClockPhase.OPEN, "09:15"),
    (ClockPhase.CLOSE, "15:30"),
    (ClockPhase.EOD, "18:00"),
]


# ── Agent output schemas (validated before any downstream use, PRD §29.5 rule 10) ─────────────────────────────────────

class HealthCheck(_Model):
    name: str
    status: HealthStatus
    detail: str = ""
    as_of: Optional[str] = None


class PremarketReport(_Model):
    status: HealthStatus
    session_date: date
    checks: list[HealthCheck]
    data_as_of: dict[str, Optional[str]] = Field(default_factory=dict)   # {"cash_eod": "2026-11-04", "fno_eod": …}
    allowed_segments: list[Segment] = Field(default_factory=list)       # what may take new risk this session


class ScanReport(_Model):
    session_date: date
    universe: str
    universe_size: int
    scanned: int
    signals: list[Signal]
    suppressed: list[dict[str, Any]] = Field(default_factory=list)      # {instrument, category, reason}
    regime: Optional[dict[str, Any]] = None
    data_as_of: datetime
    rule_version: str


class StrategyProposal(_Model):
    decision: Literal["PLAN", "NO_TRADE"]
    plan: Optional[TradePlanBody] = None
    reasons: list[str] = Field(default_factory=list)
    alternatives: list[dict[str, Any]] = Field(default_factory=list)    # ranked candidates with their key numbers

    @model_validator(mode="after")
    def _plan(self) -> "StrategyProposal":
        if (self.decision == "PLAN") != (self.plan is not None):
            raise ValueError("decision PLAN needs a plan; NO_TRADE must not carry one")
        return self


OUTPUT_SCHEMAS: dict[str, type[BaseModel]] = {
    "premarket-report-v1": PremarketReport,
    "scan-report-v1": ScanReport,
    "strategy-proposal-v1": StrategyProposal,
    "risk-assessment-v1": RiskAssessment,
    "approval-decision-v1": ApprovalDecision,
}

TASK_OUTPUT_SCHEMA: dict[TaskType, str] = {
    TaskType.PREMARKET_HEALTH_CHECK: "premarket-report-v1",
    TaskType.SCAN_MARKET: "scan-report-v1",
    TaskType.GENERATE_STRATEGY: "strategy-proposal-v1",
    TaskType.REVISE_STRATEGY: "strategy-proposal-v1",
    TaskType.ASSESS_RISK: "risk-assessment-v1",
    TaskType.REVIEW_FOR_APPROVAL: "approval-decision-v1",
}


# ── Policy (PRD §10.1; defaults from services.risk_profile OWNER_DEFAULT, owner 27 Oct / 5 Nov decisions) ─────────────

class AutonomyRules(_Model):
    auto_approve: bool = True                       # AUTONOMOUS_PAPER may approve without a person within these rules
    max_risk_pct: Decimal = Decimal("0.5")          # a plan above this share of equity needs a person
    min_signal_score: Decimal = Decimal("70")
    strategies: list[StrategyType] = Field(default_factory=lambda: [
        StrategyType.LONG_EQUITY, StrategyType.BULL_CALL_SPREAD, StrategyType.BEAR_PUT_SPREAD,
        StrategyType.BULL_PUT_SPREAD, StrategyType.BEAR_CALL_SPREAD, StrategyType.IRON_CONDOR])


class PolicyBody(_Model):
    """One policy version. Percentages are of account equity. The effective policy for an action is the most
    restrictive of the applicable policies (PRD §5.1): see autodesk.control.policy.effective()."""
    policy_schema: Literal["autodesk-policy-v1"] = "autodesk-policy-v1"
    source: str = "risk-profile owner-default-2026-10-27"
    per_trade_risk_pct: Decimal = Decimal("0.5")
    open_risk_pct: Decimal = Decimal("3")
    position_pct: Decimal = Decimal("10")
    sector_pct: Decimal = Decimal("25")
    daily_loss_pct: Decimal = Decimal("2")
    weekly_loss_pct: Decimal = Decimal("4")
    max_drawdown_pct: Decimal = Decimal("10")
    min_reward_risk: Decimal = Decimal("1.5")
    credit_min_width_fraction: Decimal = Decimal("0.3333")   # owner 28 Oct: net credit ≥ width/3 after costs
    max_margin_utilization_pct: Decimal = Decimal("25")      # owner 27 Oct: 25% at L2 (50% at L3)
    futures_margin_pct: Decimal = Decimal("15")              # estimate when no exchange SPAN is available (labelled)
    allowed_segments: list[Segment] = Field(default_factory=lambda: [Segment.CASH, Segment.FUTURES, Segment.OPTIONS])
    allowed_strategies: list[StrategyType] = Field(default_factory=lambda: [
        StrategyType.LONG_EQUITY, StrategyType.LONG_FUTURES, StrategyType.LONG_CALL, StrategyType.LONG_PUT,
        StrategyType.BULL_CALL_SPREAD, StrategyType.BEAR_PUT_SPREAD, StrategyType.BULL_PUT_SPREAD,
        StrategyType.BEAR_CALL_SPREAD, StrategyType.IRON_CONDOR])
    # SHORT_FUTURES is off by default, as in the existing risk gate (short_futures_not_supported); naked short
    # options are never allowed (not a strategy type). Covered call / collar / protective put need holdings.
    min_signal_score: Decimal = Decimal("60")
    max_proposals_per_session: int = 5
    min_days_to_expiry: int = 7          # never the series expiring that session (owner 4 Nov)
    max_legs: int = 4
    max_lots_per_leg: int = 10
    min_adv_rs: Decimal = Decimal("10000000")      # ₹1 crore 20-session average traded value (SPT builder default)
    require_traded_legs: bool = True               # every option leg must have traded (bhavcopy close is carried forward)
    max_data_age_sessions: int = 1
    autonomy: AutonomyRules = Field(default_factory=AutonomyRules)

    @model_validator(mode="after")
    def _ranges(self) -> "PolicyBody":
        for f in ("per_trade_risk_pct", "open_risk_pct", "position_pct", "sector_pct", "daily_loss_pct",
                  "weekly_loss_pct", "max_drawdown_pct", "max_margin_utilization_pct", "futures_margin_pct"):
            v = getattr(self, f)
            if not (Decimal("0") < v <= Decimal("100")):
                raise ValueError(f"{f} must be in (0, 100]")
        if self.min_reward_risk <= 0 or not (Decimal("0") < self.credit_min_width_fraction < Decimal("1")):
            raise ValueError("min_reward_risk > 0 and 0 < credit_min_width_fraction < 1")
        if not (1 <= self.max_legs <= 4):
            raise ValueError("max_legs must be 1..4 (initial builder limit)")
        return self
