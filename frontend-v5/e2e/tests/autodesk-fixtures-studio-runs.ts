/**
 * Fixtures for the Simulation studio · Run history spec (autodesk-studio-runs.spec.ts).
 *
 * // MOCK — not real data. Bodies copy the real desk API's shapes: GET /simulations rows (store.list_simulations, with
 * // config.sessions and versions.policy as SimulationManager.create writes them), GET /simulations/{sid}/results
 * // (SimulationManager.results), GET /simulations/{sid}/workflows (autodesk.workflows rows; TRADE_PROPOSAL outcomes as
 * // orchestrator/engine.py writes them), GET /trade-plans and GET /signals rows filtered by simulation_id. Instruments
 * // follow the Phase 1 real-data replay of 2–3 Nov 2026 (test_reports/autodesk_phase1_20261105_1255.md); the decisions
 * // of runs A and B are crafted so that they differ in known ways.
 */
import { TENANT, reply, type Handler, type Req, type RouteValue } from "./autodesk-mock";
import { LIMITATIONS, VERSIONS } from "./autodesk-fixtures-simulator";

export const POL = "POL-1b7e93c4d05a4e2f9c61";
export const A = "SIM-5a1c3e7b9d0f2a4c6e8b";
export const B = "SIM-8f2d4b6a0c1e3f5a7b9d";
export const C = "SIM-1e3c5a7b9d2f4a6c8e0b";
export const D = "SIM-9c7e5a3b1d0f8e6c4a2b";

export const POLICIES = [
  { policy_id: POL, tenant_id: TENANT, name: "Desk default", scope_type: "TENANT", scope_ref: null, current_version: 2, created_at: "2026-11-02T04:10:00.000+00:00", updated_at: "2026-11-05T04:30:00.000+00:00" },
];

function sim(id: string, o: { created: string; sessions: string[]; seed: number; mode?: string; status?: string; policyVersion?: number; maxP?: number }) {
  const mode = o.mode ?? "HISTORICAL_REPLAY";
  const speed = mode === "ACCELERATED_REPLAY" ? "ACCELERATED" : "STEP";
  const status = o.status ?? "COMPLETED";
  const last = o.sessions[o.sessions.length - 1];
  return {
    simulation_id: id, tenant_id: TENANT, name: `Replay ${id.slice(4, 8)}`, mode, status,
    config: { name: `Replay ${id.slice(4, 8)}`, description: "", mode, start_date: o.sessions[0], end_date: last, universe: "FNO", include_fno: true, starting_capital_rs: "10000000", operating_mode: "AUTONOMOUS_PAPER", policy_id: null, max_proposals_per_session: o.maxP ?? 3, symbols: null, seed: o.seed, speed, sessions: o.sessions },
    account_id: `ACC-${id.slice(4)}`, clock_sim_time: status === "COMPLETED" ? `${last}T12:30:00+00:00` : `${o.sessions[0]}T03:30:00+00:00`, clock_session: status === "COMPLETED" ? last : o.sessions[0],
    clock_phase: status === "COMPLETED" ? "EOD" : "PROPOSALS", step_seq: status === "COMPLETED" ? o.sessions.length * 6 : 3,
    versions: { ...VERSIONS, policy: { ...VERSIONS.policy, policy_id: POL, version: o.policyVersion ?? 1 } },
    results: null, error: null, created_by: `user:${TENANT}`, created_at: o.created, started_at: o.created, ended_at: status === "COMPLETED" ? o.created : null, updated_at: o.created,
  };
}

export const RUN_A = sim(A, { created: "2026-11-05T04:40:00.000+00:00", sessions: ["2026-11-02", "2026-11-03"], seed: 42, policyVersion: 1, maxP: 3 });
export const RUN_B = sim(B, { created: "2026-11-05T05:20:00.000+00:00", sessions: ["2026-11-02", "2026-11-03"], seed: 42, policyVersion: 2, maxP: 4 });
export const RUN_C = sim(C, { created: "2026-11-04T12:40:00.000+00:00", sessions: ["2026-10-29", "2026-10-30"], seed: 7, mode: "ACCELERATED_REPLAY", policyVersion: 1 });
export const RUN_D = sim(D, { created: "2026-11-05T06:05:00.000+00:00", sessions: ["2026-11-04"], seed: 42, status: "RUNNING", policyVersion: 2 });

// ── signals, plans, proposal workflows per run ─────────────────────────────────────────────────────────────────────

type Sig = [string, string, string, string];     // session, instrument, direction, category
const SIGS: Record<string, Sig[]> = {
  [A]: [
    ["2026-11-02", "PETRONET", "BULLISH", "LONG_BUILDUP"], ["2026-11-02", "GRASIM", "BULLISH", "LONG_BUILDUP"], ["2026-11-02", "ADANIPORTS", "BULLISH", "SHORT_COVERING"], ["2026-11-02", "HINDALCO", "BULLISH", "LONG_BUILDUP"],
    ["2026-11-03", "TATASTEEL", "BEARISH", "SHORT_BUILDUP"], ["2026-11-03", "DLF", "BEARISH", "SHORT_BUILDUP"], ["2026-11-03", "ONGC", "BEARISH", "LONG_UNWINDING"],
  ],
  [B]: [
    ["2026-11-02", "PETRONET", "BULLISH", "LONG_BUILDUP"], ["2026-11-02", "GRASIM", "BULLISH", "LONG_BUILDUP"], ["2026-11-02", "ADANIPORTS", "BULLISH", "SHORT_COVERING"], ["2026-11-02", "HINDALCO", "BULLISH", "LONG_BUILDUP"],
    ["2026-11-03", "TATASTEEL", "BEARISH", "SHORT_BUILDUP"], ["2026-11-03", "ONGC", "BEARISH", "LONG_UNWINDING"],
  ],
  [C]: [["2026-10-29", "RELIANCE", "BULLISH", "LONG_BUILDUP"], ["2026-10-30", "INFY", "BEARISH", "SHORT_BUILDUP"]],
  [D]: [["2026-11-04", "PETRONET", "BULLISH", "LONG_BUILDUP"], ["2026-11-04", "BEL", "BULLISH", "LONG_BUILDUP"], ["2026-11-04", "DLF", "BULLISH", "SHORT_COVERING"]],
};

const sigId = (sid: string, inst: string, day: string) => `SIG-${sid.slice(4, 10)}${inst.toLowerCase()}${day.slice(8)}`;

export function signals(sid: string) {
  return (SIGS[sid] ?? []).map(([day, inst, dir, cat], i) => ({
    signal_id: sigId(sid, inst, day), account_id: `ACC-${sid.slice(4)}`, simulation_id: sid, workflow_id: `WF-scan-${sid.slice(4, 10)}-${day}`, task_id: null,
    instrument: inst, exchange: "NSE", segment: "FUTURES", direction: dir, timeframe: "POSITIONAL", category: cat, signal_score: (74 - i).toFixed(2), calibrated_probability: null,
    body: { score_breakdown: [], evidence: [], missing_inputs: [], fno_eligible: true }, session_date: day, data_as_of: `${day}T00:00:00+00:00`,
    rule_version: "ait-rules-v1", model_version: null, expires_at: `${day}T12:30:00+00:00`, status: "EXPIRED", created_at: "2026-11-05T05:21:00.000+00:00",
  }));
}

type Prop = [string, string, string | null, string, number | null];   // session, instrument, strategy, result, plan_version
const PROPS: Record<string, Prop[]> = {
  [A]: [
    ["2026-11-02", "PETRONET", "BULL_CALL_SPREAD", "APPROVED_NO_EXECUTION", 1], ["2026-11-02", "GRASIM", "BULL_CALL_SPREAD", "APPROVED_NO_EXECUTION", 1],
    ["2026-11-02", "ADANIPORTS", "BULL_CALL_SPREAD", "APPROVED_NO_EXECUTION", 1], ["2026-11-03", "TATASTEEL", "BEAR_PUT_SPREAD", "APPROVED_NO_EXECUTION", 1],
  ],
  [B]: [
    ["2026-11-02", "PETRONET", "BULL_CALL_SPREAD", "APPROVED_NO_EXECUTION", 1], ["2026-11-02", "GRASIM", "BULL_CALL_SPREAD", "WAITING_HUMAN", 1],
    ["2026-11-02", "ADANIPORTS", "BULL_PUT_SPREAD", "APPROVED_NO_EXECUTION", 1], ["2026-11-02", "HINDALCO", null, "NO_TRADE", null],
    ["2026-11-03", "TATASTEEL", "BEAR_PUT_SPREAD", "APPROVED_NO_EXECUTION", 2],
  ],
  [C]: [["2026-10-29", "RELIANCE", "BULL_CALL_SPREAD", "APPROVED_NO_EXECUTION", 1]],
  [D]: [["2026-11-04", "PETRONET", "BULL_CALL_SPREAD", "APPROVED_NO_EXECUTION", 1]],
};

const trd = (sid: string, inst: string, day: string) => `TRD-${sid.slice(4, 10)}${inst.toLowerCase()}${day.slice(8)}`;

export function plans(sid: string) {
  return (PROPS[sid] ?? []).filter(([, , strat]) => strat).map(([day, inst, strat, result, v]) => ({
    trade_id: trd(sid, inst, day), account_id: `ACC-${sid.slice(4)}`, simulation_id: sid, workflow_id: `WF-tp-${sid.slice(4, 10)}-${inst.toLowerCase()}-${day}`,
    signal_id: sigId(sid, inst, day), instrument: inst, strategy_type: strat, current_version: v ?? 1, status: result === "WAITING_HUMAN" ? "AWAITING_APPROVAL" : "EXPIRED",
    created_at: `${day}T03:30:0${PROPS[sid].findIndex((p) => p[1] === inst)}.000+00:00`, updated_at: "2026-11-05T05:25:00.000+00:00",
  }));
}

export function workflows(sid: string) {
  const s = RUN_ROWS.find((r) => r.simulation_id === sid);
  return (PROPS[sid] ?? []).map(([day, inst, strat, result, v], i) => ({
    workflow_id: `WF-tp-${sid.slice(4, 10)}-${inst.toLowerCase()}-${day}`, tenant_id: TENANT, account_id: `ACC-${sid.slice(4)}`, simulation_id: sid, kind: "TRADE_PROPOSAL",
    state: result === "WAITING_HUMAN" ? "WAITING_HUMAN" : "COMPLETED", parent_workflow_id: `WF-cycle-${sid.slice(4, 10)}-${day}`, correlation_id: `${sid}:${day}`,
    session_date: day, sim_time: `${day}T03:30:00+00:00`,
    input: { session_date: day, policy_id: POL, policy_version: s?.versions.policy.version ?? 1, universe: "FNO", symbols: null, max_proposals: 3, operating_mode: "AUTONOMOUS_PAPER", signal_id: sigId(sid, inst, day) },
    outcome: strat ? { result, trade_id: trd(sid, inst, day), plan_version: v, approval_id: `APR-${sid.slice(4, 10)}${inst.toLowerCase()}` } : { result, stage: "strategy", reasons: [`BULL_CALL_SPREAD: the 760 CE did not trade on ${day}`] },
    error: null, created_at: `2026-11-05T05:2${i}:00.000+00:00`, updated_at: "2026-11-05T05:25:00.000+00:00", completed_at: "2026-11-05T05:25:00.000+00:00",
  }));
}

const agents = (failed = 0) => ({
  TECH_SUPPORT: { tasks: 2, completed: 2, failed: 0, escalated: 0, rejected: 0, retried: 0, avg_latency_ms: 412 },
  AI_TRADER: { tasks: 2, completed: 2, failed: 0, escalated: 0, rejected: 0, retried: 0, avg_latency_ms: 9810 },
  TRADING_ASSISTANT: { tasks: 5, completed: 5, failed: 0, escalated: 0, rejected: 0, retried: 0, avg_latency_ms: 2240 },
  RISK_OPS: { tasks: 5, completed: 5 - failed, failed, escalated: 0, rejected: 0, retried: 0, avg_latency_ms: 1840 },
  MIDDLE_OFFICE: { tasks: 4, completed: 4, failed: 0, escalated: 0, rejected: 0, retried: 0, avg_latency_ms: 35 },
});

function results(sid: string, o: { signals: number; plans: number; byStatus: Record<string, number>; approvals: Record<string, number>; failed?: number; status?: string; violations?: number }) {
  const s = RUN_ROWS.find((r) => r.simulation_id === sid)!;
  return {
    simulation_id: sid, status: o.status ?? "COMPLETED", mode: s.mode, sessions_total: s.config.sessions.length, phases_run: s.step_seq, premarket: { READY: s.config.sessions.length },
    signals: { total: o.signals, by_category: {}, by_status: { EXPIRED: o.signals }, by_segment: { FUTURES: o.signals } },
    plans: { total: o.plans, by_status: o.byStatus, by_strategy: {} },
    approvals: { by_status: o.approvals, by_decider: { MIDDLE_OFFICE: Object.values(o.approvals).reduce((a, b) => a + b, 0) } },
    agents: agents(o.failed ?? 0), handoffs: 12, policy_violation_attempts: o.violations ?? 0, versions: s.versions,
    data: { first_session: s.config.sessions[0], last_session: s.config.sessions[s.config.sessions.length - 1], universe: "FNO", symbols: null },
    limitations: LIMITATIONS, execution: "none in Phase 1 (no orders, fills or P&L)",
  };
}

const RUN_ROWS = [RUN_D, RUN_B, RUN_A, RUN_C];

export const RESULTS: Record<string, unknown> = {
  [A]: results(A, { signals: 7, plans: 4, byStatus: { EXPIRED: 4 }, approvals: { APPROVED: 4 } }),
  [B]: results(B, { signals: 6, plans: 4, byStatus: { EXPIRED: 3, AWAITING_APPROVAL: 1 }, approvals: { APPROVED: 3, NEEDS_HUMAN_APPROVAL: 1 } }),
  [C]: results(C, { signals: 12, plans: 2, byStatus: { EXPIRED: 1, REJECTED: 1 }, approvals: { APPROVED: 1 }, failed: 1 }),
  [D]: results(D, { signals: 3, plans: 1, byStatus: { APPROVED: 1 }, approvals: { APPROVED: 1 }, status: "RUNNING" }),
};

const nf = (id: string) => reply(404, { error: "NOT_FOUND", message: `not found: ${id}` });

/** Routes of the Run history view; `runs` = what GET /simulations lists (newest first, as the API orders). */
export function runsRoutes(runs: Record<string, unknown>[] = [RUN_B, RUN_A, RUN_C], over: Record<string, RouteValue> = {}): Record<string, RouteValue> {
  return {
    "GET /simulations": runs,
    "GET /policies": POLICIES,
    "GET /simulations/:sid/results": ((r: Req) => RESULTS[r.params.sid] ?? nf(r.params.sid)) as Handler,
    "GET /simulations/:sid/workflows": ((r: Req) => (PROPS[r.params.sid] ? workflows(r.params.sid) : nf(r.params.sid))) as Handler,
    "GET /trade-plans": ((r: Req) => plans(r.query.get("simulation_id") ?? "")) as Handler,
    "GET /signals": ((r: Req) => signals(r.query.get("simulation_id") ?? "")) as Handler,
    ...over,
  };
}
