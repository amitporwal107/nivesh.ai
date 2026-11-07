/**
 * Fixtures for the Agent command centre spec (autodesk-agents.spec.ts).
 *
 * // MOCK — not real data. Shapes copy the real desk API: rows of autodesk.agent_registry (descriptor = the
 * // AgentDescriptor of each agent in backend/autodesk/agents/*.py), the activity rows GET /agents/{key}/activity keeps,
 * // full autodesk.agent_tasks / autodesk.agent_handoffs rows in GET /desk/workflows/{id}, and TRADE_PROPOSAL workflows
 * // with the outcomes orchestrator/engine.py writes. result_summary texts follow the agents' own formats. The session is
 * // the same as the scanner fixtures (PETRONET, GRASIM, ADANIPORTS, HINDALCO on 5 Nov 2026).
 */
import { TENANT, reply, type Req, type RouteValue } from "./autodesk-mock";
import { ACC, APR, CYCLE_ID, PLANS, SCAN_TASK, SCAN_TASK_ROW, SCAN_WF, SESSION, SIG, SIM_ID, TRD, WFP, signalById } from "./autodesk-fixtures-scanner";

const REG_AT = "2026-11-05T05:20:02.114000+00:00";
const reg = (agent_key: string, version: string, status: string, hb: string | null, task_types: string[], tools: string[], prohibited: string[], registered_at = REG_AT) => ({
  agent_key, version, kind: "DETERMINISTIC", model: null, prompt_version: null,
  descriptor: { agent_key, version, kind: "DETERMINISTIC", model: null, prompt_version: null, task_types, tools, prohibited },
  status, last_heartbeat: hb, registered_at,
});

/** GET /agents (agent_key, registered_at DESC) — RISK_OPS has an older registered version that is not current. */
export function registry(over: Record<string, string> = {}) {
  const st = (k: string) => over[k] ?? "IDLE";
  return [
    reg("AI_TRADER", "autodesk-ait-v1", st("AI_TRADER"), "2026-11-05T05:31:11.540000+00:00", ["SCAN_MARKET"],
      ["market.daily_bars", "market.index_bars", "market.fno_universe", "market.fno_buildup", "market.vix", "market.sector", "market.sessions_between"], ["size positions", "approve", "execute"]),
    reg("MIDDLE_OFFICE", "autodesk-mo-v1", st("MIDDLE_OFFICE"), "2026-11-05T05:31:18.240000+00:00", ["REVIEW_FOR_APPROVAL"], [], ["alter fills", "bypass the gateway", "change risk limits"]),
    reg("RISK_OPS", "autodesk-risk-ops-v1", st("RISK_OPS"), "2026-11-05T05:31:18.150000+00:00", ["ASSESS_RISK"],
      ["market.daily_bars", "market.lot_size", "market.sector", "market.sessions_between", "market.futures"], ["weaken hard policies", "approve", "execute"]),
    reg("RISK_OPS", "autodesk-risk-ops-v0", "OFFLINE", "2026-11-03T12:02:40.000000+00:00", ["ASSESS_RISK"], ["market.daily_bars"], ["approve", "execute"], "2026-11-03T11:58:00.000000+00:00"),
    reg("TECH_SUPPORT", "autodesk-ts-v1", st("TECH_SUPPORT"), "2026-11-05T05:31:02.520000+00:00", ["PREMARKET_HEALTH_CHECK"],
      ["market.day_snapshot", "market.fno_universe", "market.vix"], ["create trading signals", "approve", "execute"]),
    reg("TRADING_ASSISTANT", "autodesk-ta-v1", st("TRADING_ASSISTANT"), "2026-11-05T05:31:17.020000+00:00", ["GENERATE_STRATEGY", "REVISE_STRATEGY"],
      ["market.daily_bars", "market.futures", "market.options", "market.expiries", "market.lot_size", "market.vix", "market.sector"], ["approve own proposal", "execute"]),
  ];
}

// ── activity rows (GET /agents/{key}/activity keeps these fields) ───────────────────────────────────────────────────

const TS = (s: string) => `2026-11-05T05:31:${s}+00:00`;
const act = (task_id: string, workflow_id: string, task_type: string, step: string, entity_id: string | null, summary: string | null,
  created: string, completed: string | null, latency: number | null, o: { state?: string; attempt?: number; error?: string | null; ref?: string | null; sim?: string | null; version?: string } = {}) => ({
  task_id, workflow_id, simulation_id: o.sim ?? null, task_type, step, entity_id, state: o.state ?? "COMPLETED", attempt: o.attempt ?? 1,
  result_summary: summary, result_ref: o.ref ?? null, error: o.error ?? null, agent_version: o.version ?? null, created_at: created, completed_at: completed, latency_ms: latency,
});

export const T = {
  TS: "TASK-0a1b2c3d4e5f40617283", SCAN: SCAN_TASK,
  TA_PET: "TASK-1b2c3d4e5f6a41728394", TA_GRA: "TASK-2c3d4e5f6a7b42839405", TA_HIN: "TASK-3d4e5f6a7b8c43940516", TA_ADA: "TASK-4e5f6a7b8c9d44051627", TA_ADA_REV: "TASK-5f6a7b8c9d0e45162738",
  RK_PET: "TASK-6a7b8c9d0e1f46273849", RK_GRA: "TASK-7b8c9d0e1f2a47384950", RK_ADA1: "TASK-8c9d0e1f2a3b48495061", RK_ADA2: "TASK-9d0e1f2a3b4c49506172",
  MO_PET: "TASK-ae1f2a3b4c5d40617283", MO_GRA: "TASK-bf2a3b4c5d6e41728394", MO_ADA: "TASK-c03b4c5d6e7f42839405",
  SIM_SCAN: "TASK-d14c5d6e7f8a43940516",
};
const RSK = { PET: "RSK-1a3c5e7b9d0f42a4c6e8", GRA: "RSK-2b4d6f8a0c1e43b5d7f9", ADA1: "RSK-3c5e7a9b1d2f44c6e8a0", ADA2: "RSK-4d6f8b0c2e3a45d7f9b1" };
const PREMARKET_WF = "WF-5e19c04a7b2d4e8f9a10";

export const ACTIVITY: Record<string, ReturnType<typeof act>[]> = {
  TECH_SUPPORT: [
    act(T.TS, PREMARKET_WF, "PREMARKET_HEALTH_CHECK", "premarket", null, "pre-market READY: new risk allowed in CASH, FUTURES, OPTIONS", TS("02.104000"), TS("02.516000"), 412, { version: "autodesk-ts-v1" }),
  ],
  AI_TRADER: [
    act(T.SIM_SCAN, "WF-e25d6e7f8a9b44051627", "SCAN_MARKET", "scan", null, "238 signals from 224 instruments (101 suppressed or skipped)", "2026-11-05T06:00:04.000000+00:00", "2026-11-05T06:00:12.000000+00:00", 8012, { sim: SIM_ID, ref: "scan://WF-e25d6e7f8a9b44051627?signals=238" }),
    { ...SCAN_TASK_ROW },
  ],
  TRADING_ASSISTANT: [
    act(T.TA_ADA_REV, WFP.ADANIPORTS, "REVISE_STRATEGY", "revise", TRD.ADANIPORTS, "bull call spread on ADANIPORTS, size 3, loss 41210.25", TS("16.402000"), TS("16.981000"), 579, { version: "autodesk-ta-v1" }),
    act(T.TA_ADA, WFP.ADANIPORTS, "GENERATE_STRATEGY", "plan", SIG.ADANIPORTS, "bull call spread on ADANIPORTS, size 4, loss 54947.00", TS("15.330000"), TS("15.902000"), 572, { version: "autodesk-ta-v1" }),
    act(T.TA_HIN, WFP.HINDALCO, "GENERATE_STRATEGY", "plan", SIG.HINDALCO, "no plan for HINDALCO: BULL_CALL_SPREAD: the 760 CE did not trade on 2026-11-04", TS("14.880000"), TS("15.290000"), 410, { version: "autodesk-ta-v1" }),
    act(T.TA_GRA, WFP.GRASIM, "GENERATE_STRATEGY", "plan", SIG.GRASIM, "bull call spread on GRASIM, size 2, loss 61840.50", TS("13.401000"), TS("14.102000"), 701, { attempt: 2, error: "TimeoutError: market.options read timed out", version: "autodesk-ta-v1" }),
    act(T.TA_PET, WFP.PETRONET, "GENERATE_STRATEGY", "plan", SIG.PETRONET, "bull call spread on PETRONET, size 4, loss 48425.90", TS("12.310000"), TS("12.871000"), 561, { version: "autodesk-ta-v1" }),
  ],
  RISK_OPS: [
    act(T.RK_ADA2, WFP.ADANIPORTS, "ASSESS_RISK", "risk", TRD.ADANIPORTS, "PASS: failed checks none", TS("17.010000"), TS("17.890000"), 880, { ref: `assessment://${RSK.ADA2}`, version: "autodesk-risk-ops-v1" }),
    act(T.RK_ADA1, WFP.ADANIPORTS, "ASSESS_RISK", "risk", TRD.ADANIPORTS, "REDUCE: failed checks per_trade_risk; passes at 3 lots", TS("15.930000"), TS("16.380000"), 450, { ref: `assessment://${RSK.ADA1}`, version: "autodesk-risk-ops-v1" }),
    act(T.RK_GRA, WFP.GRASIM, "ASSESS_RISK", "risk", TRD.GRASIM, "PASS: failed checks none", TS("14.130000"), TS("14.560000"), 430, { ref: `assessment://${RSK.GRA}`, version: "autodesk-risk-ops-v1" }),
    act(T.RK_PET, WFP.PETRONET, "ASSESS_RISK", "risk", TRD.PETRONET, "PASS: failed checks none", TS("12.900000"), TS("13.240000"), 340, { ref: `assessment://${RSK.PET}`, version: "autodesk-risk-ops-v1" }),
  ],
  MIDDLE_OFFICE: [
    act(T.MO_ADA, WFP.ADANIPORTS, "REVIEW_FOR_APPROVAL", "approval", TRD.ADANIPORTS, "NEEDS_HUMAN_APPROVAL: signal score 68.00 is below 70", TS("18.160000"), TS("18.198000"), 38, { ref: `approval://${APR.ADANIPORTS_MO}`, version: "autodesk-mo-v1" }),
    act(T.MO_GRA, WFP.GRASIM, "REVIEW_FOR_APPROVAL", "approval", TRD.GRASIM, "NEEDS_HUMAN_APPROVAL: signal score 69.00 is below 70", TS("14.580000"), TS("14.612000"), 32, { ref: `approval://${APR.GRASIM}`, version: "autodesk-mo-v1" }),
    act(T.MO_PET, WFP.PETRONET, "REVIEW_FOR_APPROVAL", "approval", TRD.PETRONET, "APPROVED: within the autonomy rules of the policy; risk 0.48% of equity", TS("13.260000"), TS("13.298000"), 38, { ref: `approval://${APR.PETRONET}`, version: "autodesk-mo-v1" }),
  ],
};

// ── full rows for GET /desk/workflows/{id} ─────────────────────────────────────────────────────────────────────────

const full = (a: ReturnType<typeof act>, to_agent: string, input_refs: string[], schema: string, result: Record<string, unknown> | null,
  o: { evidence?: string[]; tools?: Record<string, unknown>[]; validation?: Record<string, unknown> | null } = {}) => ({
  ...a, tenant_id: TENANT, account_id: ACC, from_agent: "ORCHESTRATOR", to_agent, input_refs, constraints: {}, required_output_schema: schema,
  max_attempts: 2, deadline_s: "30.000", sim_time: null, result, evidence_refs: o.evidence ?? [], tool_calls: o.tools ?? [],
  validation: o.validation === undefined ? { schema_ok: true, domain_ok: true, errors: [] } : o.validation,
  model: null, prompt_version: null, idempotency_key: `${a.workflow_id}:${a.step}`, assigned_at: a.created_at, accepted_at: a.created_at, started_at: a.created_at, updated_at: a.completed_at,
});
const tool = (t: string, ms: number, ok = true) => ({ tool: t, args: {}, as_of: "2026-11-05T05:31:00+00:00", ok, rows: ok ? 60 : null, error: ok ? null : "timed out", ms });
const handoff = (id: string, wf: string, from_task: string, to_task: string, from_agent: string, to_agent: string, entity: string, at: string) => ({
  handoff_id: id, workflow_id: wf, simulation_id: null, tenant_id: TENANT, from_task_id: from_task, to_task_id: to_task, from_agent, to_agent, entity_id: entity, created_at: at,
});
const BASE_WF = { tenant_id: TENANT, account_id: ACC, simulation_id: null, parent_workflow_id: CYCLE_ID, correlation_id: CYCLE_ID, session_date: SESSION, sim_time: null, error: null };
const PROP_INPUT = (signal_id: string) => ({ session_date: SESSION, policy_id: "POL-01JBX3K2M4N5P6Q7R8S9T0V1W3", policy_version: 1, universe: "FNO", symbols: null, max_proposals: 4, operating_mode: "AUTONOMOUS_PAPER", signal_id, policy_override: { session_allowed_segments: ["CASH", "FUTURES", "OPTIONS"] } });

const wf = (workflow_id: string, state: string, signal_id: string, outcome: Record<string, unknown>, created: string, extra: Record<string, unknown> = {}) => ({
  ...BASE_WF, workflow_id, kind: "TRADE_PROPOSAL", state, input: PROP_INPUT(signal_id), outcome, created_at: created, updated_at: created,
  completed_at: ["COMPLETED", "FAILED"].includes(state) ? created : null, ...extra,
});

/** GET /desk/workflows?account_id&kind=TRADE_PROPOSAL (created_at ascending, as the API lists) + one simulation row. */
export const PROPOSALS = [
  wf(WFP.PETRONET, "COMPLETED", SIG.PETRONET, { result: "APPROVED_NO_EXECUTION", trade_id: TRD.PETRONET, plan_version: 1, approval_id: APR.PETRONET, note: "Phase 1 has no execution; Phase 2 adds paper orders" }, TS("12.300000")),
  wf(WFP.GRASIM, "WAITING_HUMAN", SIG.GRASIM, { result: "WAITING_HUMAN", trade_id: TRD.GRASIM, plan_version: 1, approval_id: APR.GRASIM }, TS("13.390000")),
  wf(WFP.HINDALCO, "COMPLETED", SIG.HINDALCO, { result: "NO_TRADE", stage: "strategy", reasons: ["BULL_CALL_SPREAD: the 760 CE did not trade on 2026-11-04"] }, TS("14.870000")),
  wf(WFP.ADANIPORTS, "COMPLETED", SIG.ADANIPORTS, { result: "REJECTED_BY_PERSON", trade_id: TRD.ADANIPORTS, plan_version: 2, approval_id: APR.ADANIPORTS_PERSON }, TS("15.320000")),
  wf(WFP.SIM, "WAITING_HUMAN", "SIG-f36e7f8a9b0c45162738", { result: "WAITING_HUMAN", trade_id: "TRD-e6a8c0b2d4f64a7c9e1b", plan_version: 1 }, "2026-11-05T06:00:20.000000+00:00", { simulation_id: SIM_ID, account_id: "ACC-SIM01JBX3K2M4N5P6Q7R8" }),
];

const adaPlan = { strategy_type: "BULL_CALL_SPREAD", instrument: "ADANIPORTS", max_loss_rs: "54947.00" };
const OK = { schema_ok: true, domain_ok: true, errors: [] };
const byId = (id: string) => Object.values(ACTIVITY).flat().find((a) => a.task_id === id)!;

/** GET /desk/workflows/{id} for the ADANIPORTS proposal (plan → risk REDUCE → revision → risk PASS → Middle Office). */
export const ADA_DETAIL = {
  workflow: PROPOSALS[3],
  tasks: [
    full(byId(T.TA_ADA), "TRADING_ASSISTANT", [`signal://${SIG.ADANIPORTS}`], "strategy-proposal-v1", { decision: "PLAN", plan: adaPlan, reasons: [], alternatives: [] },
      { evidence: [`signal://${SIG.ADANIPORTS}`], tools: [tool("market.options", 412), tool("market.expiries", 35), tool("market.lot_size", 12), tool("market.vix", 9), tool("market.daily_bars", 88)], validation: OK }),
    full(byId(T.RK_ADA1), "RISK_OPS", [`plan://${TRD.ADANIPORTS}@1`, `book://${ACC}`], "risk-assessment-v1", { verdict: "REDUCE", checks: Array.from({ length: 14 }, (_, i) => ({ name: `c${i}` })), violations: ["per_trade_risk"] },
      { evidence: [`plan://${TRD.ADANIPORTS}@1`, `book://${ACC}`], tools: [tool("market.daily_bars", 92), tool("market.lot_size", 10), tool("market.sector", 7)] }),
    full(byId(T.TA_ADA_REV), "TRADING_ASSISTANT", [`plan://${TRD.ADANIPORTS}@1`, `assessment://${RSK.ADA1}`], "strategy-proposal-v1", { decision: "PLAN", plan: { ...adaPlan, max_loss_rs: "41210.25" } },
      { evidence: [`signal://${SIG.ADANIPORTS}`], tools: [tool("market.options", 398)] }),
    full(byId(T.RK_ADA2), "RISK_OPS", [`plan://${TRD.ADANIPORTS}@2`, `book://${ACC}`], "risk-assessment-v1", { verdict: "PASS", checks: Array.from({ length: 14 }, (_, i) => ({ name: `c${i}` })), violations: [] },
      { evidence: [`plan://${TRD.ADANIPORTS}@2`, `book://${ACC}`], tools: [tool("market.daily_bars", 90), tool("market.lot_size", 11), tool("market.sector", 6)] }),
    full(byId(T.MO_ADA), "MIDDLE_OFFICE", [`plan://${TRD.ADANIPORTS}@2`, `assessment://${RSK.ADA2}`], "approval-decision-v1",
      { status: "NEEDS_HUMAN_APPROVAL", reasons: ["signal score 68.00 is below 70"], scope: null, trade_id: TRD.ADANIPORTS, plan_version: 2 },
      { evidence: [`plan://${TRD.ADANIPORTS}@2`, `assessment://${RSK.ADA2}`], tools: [] }),
  ],
  handoffs: [
    handoff("HND-01a2b3c4d5e6f7a8b9c0", WFP.ADANIPORTS, SCAN_TASK, T.TA_ADA, "AI_TRADER", "TRADING_ASSISTANT", SIG.ADANIPORTS, TS("15.910000")),
    handoff("HND-12b3c4d5e6f7a8b9c0d1", WFP.ADANIPORTS, T.TA_ADA, T.RK_ADA1, "TRADING_ASSISTANT", "RISK_OPS", TRD.ADANIPORTS, TS("16.390000")),
    handoff("HND-23c4d5e6f7a8b9c0d1e2", WFP.ADANIPORTS, T.RK_ADA1, T.TA_ADA_REV, "RISK_OPS", "TRADING_ASSISTANT", TRD.ADANIPORTS, TS("16.990000")),
    handoff("HND-34d5e6f7a8b9c0d1e2f3", WFP.ADANIPORTS, T.TA_ADA_REV, T.RK_ADA2, "TRADING_ASSISTANT", "RISK_OPS", TRD.ADANIPORTS, TS("17.900000")),
    handoff("HND-45e6f7a8b9c0d1e2f3a4", WFP.ADANIPORTS, T.RK_ADA2, T.MO_ADA, "RISK_OPS", "MIDDLE_OFFICE", TRD.ADANIPORTS, TS("18.200000")),
  ],
  children: [],
};

/** The scan workflow: one AI Trader task with 444 market reads and the full scan report as its result. */
const SCAN_TOOLS = [
  ...Array.from({ length: 221 }, () => tool("market.daily_bars", 31)),
  ...Array.from({ length: 221 }, () => tool("market.sector", 4)),
  tool("market.index_bars", 40), tool("market.vix", 6),
];
export const SCAN_DETAIL = {
  workflow: { ...BASE_WF, workflow_id: SCAN_WF, kind: "MARKET_SCAN", state: "COMPLETED", input: {}, outcome: { universe: "FNO", universe_size: 224, scanned: 221, signals: 174 }, created_at: TS("02.600000"), updated_at: TS("11.600000"), completed_at: TS("11.600000") },
  tasks: [
    full({ ...SCAN_TASK_ROW } as ReturnType<typeof act>, "AI_TRADER", [], "scan-report-v1",
      { universe: "FNO", universe_size: 224, scanned: 221, signals: Array.from({ length: 174 }, (_, i) => ({ i })), suppressed: Array.from({ length: 128 }, (_, i) => ({ i })) },
      { tools: SCAN_TOOLS }),
  ],
  handoffs: [],
  children: [],
};

/** Routes the agents screen reads; override any key per test. */
export function agentRoutes(over: Record<string, RouteValue> = {}): Record<string, RouteValue> {
  return {
    "GET /agents": registry(),
    "GET /agents/:agent_key/activity": (r: Req) => ACTIVITY[r.params.agent_key] ?? [],
    "GET /desk/workflows": (r: Req) => (r.query.get("kind") === "TRADE_PROPOSAL" && r.query.get("account_id") === ACC ? PROPOSALS : []),
    "GET /desk/workflows/:id": (r: Req) => {
      if (r.params.id === WFP.ADANIPORTS) return ADA_DETAIL;
      if (r.params.id === SCAN_WF) return SCAN_DETAIL;
      return reply(404, { error: "NOT_FOUND", message: `not found: ${r.params.id}` });
    },
    "GET /trade-plans": PLANS,
    "GET /signals/:id": (r: Req) => signalById(r.params.id) ?? reply(404, { error: "NOT_FOUND", message: `not found: ${r.params.id}` }),
    ...over,
  };
}
