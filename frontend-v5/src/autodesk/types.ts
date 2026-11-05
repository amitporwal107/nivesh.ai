/**
 * Shapes of the desk API (backend/autodesk/routers/api.py, rows of the autodesk.* tables in
 * backend/autodesk/db/migrations/001 + 002). The API serialises Decimal as a string and dates / timestamps as ISO
 * strings, so money and scores arrive as strings: convert with num() from ./format before doing arithmetic.
 */

export type Decimal = string;          // e.g. "48425.90" — numeric(18,2) serialised by the API
export type IsoTime = string;          // timestamptz, ISO 8601 with offset
export type IsoDate = string;          // date, YYYY-MM-DD

export type AccountKind = "PAPER" | "SIMULATION" | "SHADOW";
export type OperatingMode = "RESEARCH" | "ASSISTED" | "AUTONOMOUS_PAPER";
export type AgentKey = "AI_TRADER" | "TRADING_ASSISTANT" | "RISK_OPS" | "MIDDLE_OFFICE" | "TECH_SUPPORT";
export type AgentStatus = "IDLE" | "BUSY" | "SCALING" | "DEGRADED" | "MAINTENANCE" | "QUARANTINED" | "OFFLINE";

export interface Account {
  account_id: string;
  tenant_id?: string;
  name: string;
  kind: AccountKind;
  operating_mode: OperatingMode;
  starting_capital_rs: Decimal;
  currency?: string;
  simulation_id?: string | null;
  policy_id?: string | null;
  status: "ACTIVE" | "SUSPENDED" | "CLOSED";
  created_by?: string;
  created_at?: IsoTime;
  updated_at?: IsoTime;
}

export interface DeskControlRow {
  tenant_id: string;
  control: "STOP_NEW_ENTRIES";
  active: boolean;
  reason: string | null;
  changed_by: string | null;
  changed_at: IsoTime | null;
}

export interface DeskStatus {
  as_of: IsoTime;
  accounts: Pick<Account, "account_id" | "name" | "kind" | "operating_mode" | "status" | "starting_capital_rs">[];
  agents: { agent_key: AgentKey; version: string; kind: string; status: AgentStatus; last_heartbeat: IsoTime | null }[];
  pending_approvals: number;
  open_workflows: number;
  controls: DeskControlRow[];
  last_premarket: { session_date: IsoDate | null; outcome: Record<string, unknown> | null } | null;
  market_data: { latest_cash_session?: IsoDate; latest_fno_session?: IsoDate; error?: string };
  execution: string;
}

export interface AgentRow {
  agent_key: AgentKey;
  version: string;
  kind: "DETERMINISTIC" | "LLM_ASSISTED";
  model: string | null;
  prompt_version: string | null;
  descriptor: { task_types?: string[]; tools?: string[]; prohibited?: string[]; [k: string]: unknown };
  status: AgentStatus;
  last_heartbeat: IsoTime | null;
  registered_at: IsoTime;
}

export interface AgentTaskRow {
  task_id: string;
  workflow_id: string;
  simulation_id: string | null;
  task_type: string;
  step: string | null;
  entity_id: string | null;
  state: string;
  attempt: number;
  result_summary: string | null;
  result_ref: string | null;
  error: string | null;
  agent_version: string | null;
  created_at: IsoTime;
  completed_at: IsoTime | null;
  latency_ms: number | null;
}

export type WorkflowKind = "SESSION_CYCLE" | "PREMARKET_CHECK" | "MARKET_SCAN" | "TRADE_PROPOSAL";
export type WorkflowState = "CREATED" | "RUNNING" | "WAITING_HUMAN" | "COMPLETED" | "BLOCKED" | "FAILED" | "CANCELLED";

export interface WorkflowRow {
  workflow_id: string;
  tenant_id?: string;
  account_id: string | null;
  simulation_id: string | null;
  kind: WorkflowKind;
  state: WorkflowState;
  parent_workflow_id: string | null;
  correlation_id?: string | null;
  session_date: IsoDate | null;
  sim_time?: IsoTime | null;
  input?: Record<string, unknown> | null;
  outcome: Record<string, unknown> | null;
  error: string | null;
  created_at: IsoTime;
  updated_at?: IsoTime;
  completed_at: IsoTime | null;
}

export interface EventRow {
  seq: number;
  event_id: string;
  event_type: string;
  event_version?: number;
  occurred_at: IsoTime;
  recorded_at?: IsoTime;
  sim_time: IsoTime | null;
  tenant_id?: string;
  account_id: string | null;
  simulation_id: string | null;
  workflow_id: string | null;
  correlation_id?: string | null;
  causation_id?: string | null;
  producer: string;
  payload: Record<string, unknown>;
}

export interface ScoreDimension {
  dimension: string;
  weight: number | string;
  points: number | string;
  available: boolean;
  detail?: string | null;
}

export interface SignalBody {
  score_breakdown?: ScoreDimension[];
  entry_zone?: { low: number | string; high: number | string } | null;
  invalidation_price?: number | string | null;
  targets?: (number | string)[];
  evidence?: unknown[];
  missing_inputs?: string[];
  reference_price?: number | string | null;
  fno_eligible?: boolean;
  sector?: string | null;
  [k: string]: unknown;
}

export interface SignalRow {
  signal_id: string;
  account_id: string | null;
  simulation_id: string | null;
  workflow_id: string | null;
  task_id?: string | null;
  instrument: string;
  exchange: string;
  segment: "CASH" | "FUTURES" | "OPTIONS" | "INDEX";
  direction: "BULLISH" | "BEARISH" | "NEUTRAL";
  timeframe: "INTRADAY" | "POSITIONAL";
  category: string;
  signal_score: Decimal;
  calibrated_probability: Decimal | null;
  body: SignalBody;
  session_date: IsoDate;
  data_as_of: IsoTime;
  rule_version: string;
  model_version: string | null;
  expires_at: IsoTime | null;
  status: "DETECTED" | "CONSUMED" | "SUPPRESSED" | "EXPIRED";
  created_at: IsoTime;
  updated_at?: IsoTime;
}

export type PlanStatus = "DRAFT" | "RISK_REVIEW" | "NEEDS_REVISION" | "AWAITING_APPROVAL" | "APPROVED" | "REJECTED"
  | "RESEARCH_ONLY" | "EXPIRED";

export interface TradePlanRow {
  trade_id: string;
  account_id: string | null;
  simulation_id: string | null;
  workflow_id: string | null;
  signal_id: string | null;
  instrument: string;
  strategy_type: string;
  current_version: number;
  status: PlanStatus;
  created_at: IsoTime;
  updated_at: IsoTime;
}

export interface PlanLeg {
  leg_id: string;
  kind: "EQ" | "FUT" | "CE" | "PE";
  underlying: string;
  tradingsymbol?: string | null;
  expiry?: IsoDate | null;
  strike?: number | string | null;
  side: string;
  lots?: number | null;
  lot_size?: number | null;
  quantity: number;
  ref_price?: number | string | null;
  ref_price_source?: string | null;
  open_interest?: number | null;
  greeks?: Record<string, number | string | null> | null;
}

export interface RiskCheck {
  name: string;
  outcome: "PASS" | "WARN" | "FAIL" | "SKIPPED";
  value?: unknown;
  limit?: unknown;
  detail?: string | null;
  hard?: boolean;
}

export interface RiskAssessmentRow {
  assessment_id: string;
  trade_id: string;
  plan_version: number;
  account_id: string | null;
  simulation_id: string | null;
  verdict: "PASS" | "REDUCE" | "FAIL";
  body: {
    verdict?: string;
    checks?: RiskCheck[];
    sizing?: Record<string, unknown> | null;
    violations?: string[];
    warnings?: string[];
    inputs_snapshot?: Record<string, unknown>;
    [k: string]: unknown;
  };
  policy_id: string | null;
  policy_version: number | null;
  engine_version: string;
  created_at: IsoTime;
}

export type ApprovalStatus = "APPROVED" | "REJECTED" | "NEEDS_HUMAN_APPROVAL" | "NEEDS_REVISION" | "SUSPENDED";

export interface ApprovalRow {
  approval_id: string;
  trade_id: string;
  plan_version: number;
  account_id: string | null;
  simulation_id: string | null;
  status: ApprovalStatus;
  decided_by: string | null;
  body: {
    status?: string;
    decided_by?: string;
    reasons?: string[];
    scope?: Record<string, unknown> | null;
    expires_at?: IsoTime | null;
    [k: string]: unknown;
  };
  risk_assessment_id: string | null;
  supersedes_id: string | null;
  expires_at: IsoTime | null;
  created_at: IsoTime;
}

export interface TradePlanDetail extends TradePlanRow {
  version: number;
  body: Record<string, unknown> & { legs?: PlanLeg[]; thesis?: string; rationale?: string[] };
  body_sha256: string;
  version_created_by: string;
  change_reason: string | null;
  plan_hash: string;
  latest_risk_assessment: RiskAssessmentRow | null;
  approvals: ApprovalRow[];
}

export type SimulationStatus = "CREATED" | "RUNNING" | "PAUSED" | "STOPPED" | "COMPLETED" | "FAILED";

export interface SimulationRow {
  simulation_id: string;
  name: string;
  mode: string;
  status: SimulationStatus;
  config: Record<string, unknown>;
  account_id: string | null;
  clock_sim_time: IsoTime | null;
  clock_session: IsoDate | null;
  clock_phase: string | null;
  step_seq: number;
  versions: Record<string, unknown> | null;
  results: Record<string, unknown> | null;
  error: string | null;
  created_by: string;
  created_at: IsoTime;
  started_at: IsoTime | null;
  ended_at: IsoTime | null;
  updated_at: IsoTime;
  background_run?: unknown;
}

export interface PolicyDetail {
  policy_id: string;
  name: string;
  scope_type: string;
  version: number;
  current_version: number;
  body: Record<string, unknown>;
  body_sha256: string;
  created_at: IsoTime;
  created_by: string;
  reason: string | null;
}

/** GET /api/auth/me on the main app (same sign-in). Only the fields the desk shows. */
export interface Me {
  user_id: string;
  email?: string;
  name?: string;
  role?: string;
}
