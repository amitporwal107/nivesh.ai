/**
 * Fixtures for the Desk overview spec (AD-UI-20..29).
 *
 * // MOCK — not real data. Shapes copy the real desk API: approvals rows (store.list_approvals + ApprovalDecision body),
 * // trade plan detail (GET /trade-plans/{id}: plan head + version body + plan_hash + latest_risk_assessment + approvals),
 * // agent task rows (GET /agents/{key}/activity keeps task_id … latency_ms), risk assessment rows and the desk status
 * // pre-market outcome ({premarket: PremarketReport}). Instruments, max losses and summaries follow the Phase 1 real-data
 * // run of 5 Nov 2026 (test_reports/autodesk_phase1_20261105_1255.md); they are fixtures, never shown to a user.
 */
import { ACCOUNT_A, AGENTS_STATUS, TENANT, deskStatus, type MockState } from "./autodesk-mock";

export const ACC = ACCOUNT_A.account_id;
export const POL = ACCOUNT_A.policy_id;
export const MO = "MIDDLE_OFFICE@autodesk-mo-v1";

export const TRD = {
  petronet: "TRD-4f1c2a9e0b7d6c5a3e21",
  grasim: "TRD-9a8b7c6d5e4f3a2b1c0d",
  adani: "TRD-0c1d2e3f4a5b6c7d8e9f",
  reliance: "TRD-77aa66bb55cc44dd33ee",
  hdfc: "TRD-1234abcd5678ef901234",
};

export const PREMARKET_OUTCOME = {
  premarket: {
    status: "READY", session_date: "2026-11-05",
    checks: [
      { name: "desk_db", status: "READY", detail: "answers", as_of: null },
      { name: "cash_eod", status: "READY", detail: "2187 cash rows for 2026-11-04 (need 500)", as_of: "2026-11-04" },
      { name: "fno_eod", status: "READY", detail: "224 F&O underlyings for 2026-11-04 (need 100)", as_of: "2026-11-04" },
      { name: "vix", status: "READY", detail: "India VIX 15.19", as_of: null },
    ],
    data_as_of: { cash_eod: "2026-11-04", fno_eod: "2026-11-04" },
    allowed_segments: ["CASH", "FUTURES", "OPTIONS"],
  },
};

/** Desk status with the real pre-market outcome shape. */
export function status(state: MockState, over: Record<string, unknown> = {}) {
  return deskStatus(state, { last_premarket: { session_date: "2026-11-05", outcome: PREMARKET_OUTCOME }, open_workflows: 2, ...over });
}

export function approval(o: {
  id: string; trade: string; version?: number; status?: string; reasons: string[]; expires: string | null; created: string;
  sim?: string | null; scope?: Record<string, unknown> | null;
}) {
  const version = o.version ?? 1;
  const st = o.status ?? "NEEDS_HUMAN_APPROVAL";
  return {
    approval_id: o.id, trade_id: o.trade, plan_version: version, account_id: ACC, simulation_id: o.sim ?? null, status: st,
    decided_by: MO,
    body: {
      approval_id: o.id, trade_id: o.trade, plan_version: version, account_id: ACC, simulation_id: o.sim ?? null, status: st,
      decided_by: MO, reasons: o.reasons, scope: o.scope ?? null, risk_assessment_id: `RSK-${o.trade.slice(4, 14)}`,
      policy_id: POL, policy_version: 1, expires_at: o.expires, created_at: o.created,
    },
    risk_assessment_id: `RSK-${o.trade.slice(4, 14)}`, supersedes_id: null, expires_at: o.expires, created_at: o.created,
  };
}

/** Four desk requests for a person (12:10 is the first to expire) and one from a simulation. */
export const PENDING = [
  approval({ id: "APR-a1b2c3d4e5f6a7b8c9d0", trade: TRD.petronet, reasons: ["signal score 64.50 is below 70"], expires: "2026-11-05T09:55:00+00:00", created: "2026-11-05T03:52:08+00:00" }),
  approval({ id: "APR-b2c3d4e5f6a7b8c9d0e1", trade: TRD.grasim, version: 2, reasons: ["risk 0.52% of equity is above 0.5%"], expires: "2026-11-05T06:40:00+00:00", created: "2026-11-05T03:53:30+00:00" }),
  approval({ id: "APR-c3d4e5f6a7b8c9d0e1f2", trade: TRD.adani, reasons: ["LONG_CALL is not in the autonomy list"], expires: "2026-11-05T08:00:00+00:00", created: "2026-11-05T03:54:10+00:00" }),
  approval({ id: "APR-d4e5f6a7b8c9d0e1f2a3", trade: TRD.reliance, reasons: ["signal score 61.00 is below 70"], expires: "2026-11-05T09:00:00+00:00", created: "2026-11-05T03:54:40+00:00" }),
  approval({ id: "APR-e5f6a7b8c9d0e1f2a3b4", trade: TRD.hdfc, reasons: ["assisted mode: a person approves every plan"], expires: "2026-11-05T06:20:00+00:00", created: "2026-11-05T05:00:00+00:00", sim: "SIM-5d4c3b2a1f0e9d8c7b6a" }),
];

export const APPROVED_HDFC = approval({
  id: "APR-f6a7b8c9d0e1f2a3b4c5", trade: TRD.hdfc, status: "APPROVED", reasons: ["within the autonomy rules of the policy", "risk 0.31% of equity"],
  expires: "2026-11-05T10:00:00+00:00", created: "2026-11-05T03:55:00+00:00",
  scope: {
    tenant_id: TENANT, account_id: ACC, trade_id: TRD.hdfc, plan_version: 1, instrument: "HDFCBANK", strategy_type: "BULL_CALL_SPREAD",
    max_lots: 4, max_notional_rs: "61240.00", max_risk_rs: "31015.20", execution_mode: "PAPER",
    allowed_actions: ["ENTER", "EXIT_AT_INVALIDATION", "EXIT_AT_TARGET", "TRAIL_TIGHTEN", "TIME_EXIT"],
    plan_hash: "3b7f0c1e9d2a4b6c8e0f1a3c5e7d9b1f2a4c6e8d0b2f4a6c8e0d2b4f6a8c0e2d",
  },
});

const PLAN_INFO: Record<string, [string, string, string, string]> = {
  // trade_id: instrument, strategy_type, max_loss_rs, signal_id
  [TRD.petronet]: ["PETRONET", "BULL_CALL_SPREAD", "48425.90", "SIG-0a1b2c3d4e5f6a7b8c9d"],
  [TRD.grasim]: ["GRASIM", "BULL_CALL_SPREAD", "41683.00", "SIG-1b2c3d4e5f6a7b8c9d0e"],
  [TRD.adani]: ["ADANIPORTS", "LONG_CALL", "36244.39", "SIG-2c3d4e5f6a7b8c9d0e1f"],
  [TRD.reliance]: ["RELIANCE", "LONG_EQUITY", "12000.00", "SIG-3d4e5f6a7b8c9d0e1f2a"],
  [TRD.hdfc]: ["HDFCBANK", "BULL_CALL_SPREAD", "31015.20", "SIG-4e5f6a7b8c9d0e1f2a3b"],
};

/** GET /trade-plans/{id}?version=n — plan head + the version body (subset of TradePlanBody fields) + hash. */
export function planDetail(tradeId: string, version = 1) {
  const [instrument, strategy, loss, signal] = PLAN_INFO[tradeId];
  return {
    trade_id: tradeId, account_id: ACC, simulation_id: null, workflow_id: "WF-7e6d5c4b3a2f1e0d9c8b", signal_id: signal,
    instrument, strategy_type: strategy, current_version: version, status: "AWAITING_APPROVAL",
    created_at: "2026-11-05T03:52:00+00:00", updated_at: "2026-11-05T03:52:08+00:00", version,
    body: {
      thesis: `${instrument}: long build-up with price above the 20-session high`, rationale: ["OI up 9.4% with price up 2.1%"],
      signal_id: signal, account_id: ACC, instrument, segment: strategy === "LONG_EQUITY" ? "CASH" : "OPTIONS", strategy_type: strategy,
      legs: [], max_loss_rs: loss, max_profit_rs: null, loss_defined: true, capital_required_rs: loss,
      plan_expires_at: "2026-11-05T10:00:00+00:00",
    },
    body_sha256: "9f".repeat(32), version_created_by: "TRADING_ASSISTANT", change_reason: null,
    plan_hash: "1a".repeat(32), latest_risk_assessment: null, approvals: [],
  };
}

export function task(o: {
  id: string; type: string; entity?: string | null; state?: string; created: string; completed?: string | null;
  summary?: string | null; ref?: string | null; error?: string | null; sim?: string | null; version: string;
}) {
  return {
    task_id: o.id, workflow_id: "WF-7e6d5c4b3a2f1e0d9c8b", simulation_id: o.sim ?? null, task_type: o.type, step: null,
    entity_id: o.entity ?? null, state: o.state ?? "COMPLETED", attempt: 1, result_summary: o.summary ?? null, result_ref: o.ref ?? null,
    error: o.error ?? null, agent_version: o.version, created_at: o.created, completed_at: o.completed === undefined ? o.created : o.completed,
    latency_ms: o.completed === null ? null : 1840,
  };
}

/** GET /agents/{key}/activity, newest first (desk tasks + one simulation task + one from yesterday). */
export const ACTIVITY: Record<string, unknown[]> = {
  TECH_SUPPORT: [
    task({ id: "TSK-ts-2", type: "PREMARKET_HEALTH_CHECK", created: "2026-11-05T03:31:00+00:00", completed: "2026-11-05T03:31:02+00:00", summary: "pre-market READY: new risk allowed in CASH, FUTURES, OPTIONS", version: "autodesk-ts-v1" }),
    task({ id: "TSK-ts-1", type: "PREMARKET_HEALTH_CHECK", created: "2026-11-04T03:31:00+00:00", completed: "2026-11-04T03:31:02+00:00", summary: "pre-market READY: new risk allowed in CASH, FUTURES, OPTIONS", version: "autodesk-ts-v1" }),
  ],
  AI_TRADER: [
    task({ id: "TSK-ait-sim", type: "SCAN_MARKET", created: "2026-11-05T06:00:00+00:00", summary: "238 signals from 224 instruments (61 suppressed or skipped)", sim: "SIM-5d4c3b2a1f0e9d8c7b6a", version: "autodesk-ait-v1" }),
    task({ id: "TSK-ait-1", type: "SCAN_MARKET", created: "2026-11-05T03:48:00+00:00", completed: "2026-11-05T03:50:10+00:00", summary: "174 signals from 224 instruments (125 suppressed or skipped)", ref: "scan://WF-7e6d5c4b3a2f1e0d9c8b?signals=174", version: "autodesk-ait-v1" }),
  ],
  TRADING_ASSISTANT: [
    task({ id: "TSK-ta-2", type: "GENERATE_STRATEGY", entity: PLAN_INFO[TRD.grasim][3], state: "RUNNING", created: "2026-11-05T06:12:00+00:00", completed: null, version: "autodesk-ta-v1" }),
    task({ id: "TSK-ta-1", type: "GENERATE_STRATEGY", entity: PLAN_INFO[TRD.petronet][3], created: "2026-11-05T03:51:58+00:00", completed: "2026-11-05T03:52:00+00:00", summary: "Bull call spread on PETRONET, size 4 lots, loss 48425.90", version: "autodesk-ta-v1" }),
  ],
  RISK_OPS: [
    task({ id: "TSK-risk-2", type: "ASSESS_RISK", entity: TRD.hdfc, created: "2026-11-05T03:54:49+00:00", completed: "2026-11-05T03:54:50+00:00", summary: "PASS: failed checks none", ref: "assessment://RSK-hdfc00000000000000", version: "autodesk-risk-v1" }),
    task({ id: "TSK-risk-1", type: "ASSESS_RISK", entity: TRD.petronet, created: "2026-11-05T03:52:04+00:00", completed: "2026-11-05T03:52:05+00:00", summary: "PASS: failed checks none", ref: "assessment://RSK-petro0000000000000", version: "autodesk-risk-v1" }),
  ],
  MIDDLE_OFFICE: [
    task({ id: "TSK-mo-2", type: "REVIEW_FOR_APPROVAL", entity: TRD.hdfc, created: "2026-11-05T03:54:59+00:00", completed: "2026-11-05T03:55:00+00:00", summary: "APPROVED: within the autonomy rules of the policy; risk 0.31% of equity", ref: `approval://${APPROVED_HDFC.approval_id}`, version: "autodesk-mo-v1" }),
    task({ id: "TSK-mo-1", type: "REVIEW_FOR_APPROVAL", entity: TRD.petronet, created: "2026-11-05T03:52:07+00:00", completed: "2026-11-05T03:52:08+00:00", summary: "NEEDS_HUMAN_APPROVAL: signal score 64.50 is below 70", ref: `approval://${PENDING[0].approval_id}`, version: "autodesk-mo-v1" }),
  ],
};

export function assessment(id: string, trade: string, proposed: number, allowed: number) {
  return {
    assessment_id: id, trade_id: trade, plan_version: 1, account_id: ACC, simulation_id: null, verdict: "PASS",
    body: {
      assessment_id: id, trade_id: trade, plan_version: 1, account_id: ACC, simulation_id: null, verdict: "PASS", checks: [],
      sizing: { proposed_size: proposed, allowed_size: allowed, unit: "lots per leg" }, violations: [], inputs_snapshot: {},
      policy_id: POL, policy_version: 1, engine_version: "autodesk-risk-engine-v1", warnings: [], created_at: "2026-11-05T03:52:05+00:00",
    },
    policy_id: POL, policy_version: 1, engine_version: "autodesk-risk-engine-v1", created_at: "2026-11-05T03:52:05+00:00",
  };
}

export const ASSESSMENTS: Record<string, unknown> = {
  "RSK-hdfc00000000000000": assessment("RSK-hdfc00000000000000", TRD.hdfc, 4, 4),
  "RSK-petro0000000000000": assessment("RSK-petro0000000000000", TRD.petronet, 4, 4),
};

/** Registry with a busy Trading Assistant and a degraded Tech Support. */
export const AGENTS_MIXED = AGENTS_STATUS.map((a) =>
  a.agent_key === "TRADING_ASSISTANT" ? { ...a, status: "BUSY" } : a.agent_key === "TECH_SUPPORT" ? { ...a, status: "DEGRADED" } : a);
