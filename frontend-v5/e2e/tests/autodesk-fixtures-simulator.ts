/**
 * Simulator fixtures for autodesk-simulator.spec.ts.
 *
 * // MOCK — not real data. Bodies copy the shapes of the real simulation API (GET /simulations, /simulations/{sid},
 * // /results, /agents, /workflows, /timeline, GET /desk/workflows/{id} and the lifecycle POSTs;
 * // backend/autodesk/routers/api.py + simulator/manager.py). The completed run follows the Phase 1 real-data replay
 * // (test_reports/autodesk_phase1_20261105_1255.md): 2 sessions, 12 phases, pre-market READY ×2, 476 signals,
 * // plans BULL_CALL_SPREAD 3 + BEAR_PUT_SPREAD 3, approvals APPROVED 6 by MIDDLE_OFFICE, 0 policy violations. The
 * // timeline below is a shortened event stream of that shape (a few signals per session, not 476).
 */
import { NOW, TENANT, reply, type Handler, type Req, type RouteValue } from "./autodesk-mock";

export const SID = "SIM-2b9d7f1e0a3c4b5d6e7f";
export const SIM_ACC = "ACC-5d4c3b2a1f0e9d8c7b6a";
const SESSIONS = ["2026-11-02", "2026-11-03"];
const PH: [string, string][] = [["PREMARKET", "03:00"], ["SCAN", "03:15"], ["PROPOSALS", "03:30"], ["OPEN", "03:45"], ["CLOSE", "10:00"], ["EOD", "12:30"]];
export const simTime = (day: string, i: number) => `${day}T${PH[i][1]}:00+00:00`;

export const VERSIONS = {
  app: "0.1.0",
  agents: { AI_TRADER: "autodesk-ait-v1", TRADING_ASSISTANT: "autodesk-ta-v1", RISK_OPS: "autodesk-risk-v1", MIDDLE_OFFICE: "autodesk-mo-v1", TECH_SUPPORT: "autodesk-ts-v1" },
  market_view: "point-in-time; cash EOD visible 19:30 IST, F&O EOD 22:45 IST",
  risk_engine: "autodesk-risk-v1",
  scan_rules: "ait-rules-v1",
  policy: { policy_id: "POL-1b7e93c4d05a4e2f9c61", version: 1, sha256: "e3a1f09c7b5d2e4f6a8c0b1d3e5f7a9c2b4d6e8f0a1c3e5f7b9d1f3a5c7e9b0d" },
};

export const LIMITATIONS = [
  "Decisions are made before the open on the previous session's end-of-day data; there is no intraday replay (stored intraday history is about ten days and has no cash stocks).",
  "Phase 1 has no execution: approved plans are not filled, so there is no P&L, no capital reservation and the daily-loss / weekly-loss / drawdown checks are skipped.",
  "Option premiums are the previous session's bhavcopy closes of contracts that traded; untraded strikes are skipped.",
  "Futures margin is an estimate (policy futures_margin_pct), not exchange SPAN.",
  "Sector is the latest index-constituent industry, not point-in-time.",
];

export const CONFIG = {
  name: "Replay 2–3 Nov", description: "", mode: "HISTORICAL_REPLAY", start_date: "2026-11-02", end_date: "2026-11-03", universe: "FNO", include_fno: true,
  starting_capital_rs: "10000000", operating_mode: "AUTONOMOUS_PAPER", policy_id: null, max_proposals_per_session: 3, symbols: null, seed: 42, speed: "STEP", sessions: SESSIONS,
};

export const RESULTS = {
  simulation_id: SID, status: "COMPLETED", mode: "HISTORICAL_REPLAY", sessions_total: 2, phases_run: 12, premarket: { READY: 2 },
  signals: { total: 476, by_category: { LONG_BUILDUP: 182, SHORT_COVERING: 176, SHORT_BUILDUP: 61, LONG_UNWINDING: 57 }, by_status: { CONSUMED: 6, EXPIRED: 470 }, by_segment: { FUTURES: 476 } },
  plans: { total: 6, by_status: { EXPIRED: 6 }, by_strategy: { BULL_CALL_SPREAD: 3, BEAR_PUT_SPREAD: 3 } },
  approvals: { by_status: { APPROVED: 6 }, by_decider: { MIDDLE_OFFICE: 6 } },
  agents: {
    TECH_SUPPORT: { tasks: 2, completed: 2, failed: 0, escalated: 0, rejected: 0, retried: 0, avg_latency_ms: 412 },
    AI_TRADER: { tasks: 2, completed: 2, failed: 0, escalated: 0, rejected: 0, retried: 0, avg_latency_ms: 9810 },
    TRADING_ASSISTANT: { tasks: 6, completed: 6, failed: 0, escalated: 0, rejected: 0, retried: 0, avg_latency_ms: 2240 },
    RISK_OPS: { tasks: 6, completed: 6, failed: 0, escalated: 0, rejected: 0, retried: 1, avg_latency_ms: 1840 },
    MIDDLE_OFFICE: { tasks: 6, completed: 6, failed: 0, escalated: 0, rejected: 0, retried: 0, avg_latency_ms: 35 },
  },
  handoffs: 18, policy_violation_attempts: 0, versions: VERSIONS,
  data: { first_session: "2026-11-02", last_session: "2026-11-03", universe: "FNO", symbols: null },
  limitations: LIMITATIONS, execution: "none in Phase 1 (no orders, fills or P&L)",
};

export const SIM_DONE = {
  simulation_id: SID, tenant_id: TENANT, name: "Replay 2–3 Nov", mode: "HISTORICAL_REPLAY", status: "COMPLETED", config: CONFIG, account_id: SIM_ACC,
  clock_sim_time: simTime("2026-11-03", 5), clock_session: "2026-11-03", clock_phase: "EOD", step_seq: 12, versions: VERSIONS, results: RESULTS, error: null,
  created_by: `user:${TENANT}`, created_at: "2026-11-05T05:40:02.000+00:00", started_at: "2026-11-05T05:40:05.000+00:00", ended_at: "2026-11-05T05:44:51.000+00:00",
  updated_at: "2026-11-05T05:44:51.000+00:00", background_run: false,
};

export const SIM_AGENTS = {
  simulation_id: SID, versions: VERSIONS,
  agents: {
    AI_TRADER: { tasks: 2, by_state: { COMPLETED: 2 } }, MIDDLE_OFFICE: { tasks: 6, by_state: { COMPLETED: 6 } }, RISK_OPS: { tasks: 6, by_state: { COMPLETED: 6 } },
    TECH_SUPPORT: { tasks: 2, by_state: { COMPLETED: 2 } }, TRADING_ASSISTANT: { tasks: 6, by_state: { COMPLETED: 6 } },
  },
};

const PROPOSALS: [string, string, string, string][][] = [
  [["PETRONET", "BULL_CALL_SPREAD", "48425.90", "0.48"], ["GRASIM", "BULL_CALL_SPREAD", "41683.00", "0.42"], ["ADANIPORTS", "BULL_CALL_SPREAD", "36244.39", "0.36"]],
  [["TATASTEEL", "BEAR_PUT_SPREAD", "32118.40", "0.32"], ["HINDALCO", "BEAR_PUT_SPREAD", "28904.75", "0.29"], ["DLF", "BEAR_PUT_SPREAD", "44310.20", "0.44"]],
];

const wfRow = (id: string, kind: string, day: string, i: number, state: string, outcome: Record<string, unknown> | null, input: Record<string, unknown> | null = null) => ({
  workflow_id: id, tenant_id: TENANT, account_id: SIM_ACC, simulation_id: SID, kind, state, parent_workflow_id: `WF-cycle-${day}`, correlation_id: `${SID}:${day}`,
  session_date: day, sim_time: simTime(day, Math.min(i, 2)), input, outcome, error: null, created_at: `2026-11-05T05:4${SESSIONS.indexOf(day) + 1}:${String(10 + i).padStart(2, "0")}.000+00:00`, updated_at: NOW, completed_at: NOW,
});

export const WORKFLOWS = SESSIONS.flatMap((day, d) => [
  wfRow(`WF-cycle-${day}`, "SESSION_CYCLE", day, 0, "COMPLETED", { result: "CYCLE_COMPLETED" }),
  wfRow(`WF-pm-${day}`, "PREMARKET_CHECK", day, 1, "COMPLETED", { premarket: { status: "READY", session_date: day, checks: [], data_as_of: { cash_eod: d === 0 ? "2026-10-30" : "2026-11-02", fno_eod: d === 0 ? "2026-10-30" : "2026-11-02" }, allowed_segments: ["CASH", "FUTURES", "OPTIONS"] } }),
  wfRow(`WF-scan-${day}`, "MARKET_SCAN", day, 2, "COMPLETED", { signals: 238 }),
  ...PROPOSALS[d].map(([sym], k) => wfRow(`WF-tp-${day}-${k}`, "TRADE_PROPOSAL", day, 3 + k, "COMPLETED", { result: "APPROVED_NO_EXECUTION", trade_id: `TRD-${sym.toLowerCase()}${d}`, plan_version: 1, approval_id: `APR-${sym.toLowerCase()}${d}` }, { signal_id: `SIG-${sym.toLowerCase()}${d}` })),
]);

export const LATEST_TP = `WF-tp-2026-11-03-2`;

export function workflowDetail(wid: string) {
  const wf = WORKFLOWS.find((w) => w.workflow_id === wid);
  if (!wf) return null;
  const t = (step: string, type: string, i: number) => ({ task_id: `TSK-${wid}-${step}`, task_type: type, step, state: "COMPLETED", entity_id: null, result_summary: null, error: null, created_at: `2026-11-05T05:42:3${i}.000+00:00` });
  return { workflow: wf, tasks: [t("plan", "GENERATE_STRATEGY", 1), t("risk", "ASSESS_RISK", 2), t("approval", "REVIEW_FOR_APPROVAL", 3)], handoffs: [], children: [] };
}

/** A shortened event stream of the 2-session run, in seq order, plus the 12 clock rows. */
export function buildTimeline() {
  let seq = 5000;
  const events: Record<string, unknown>[] = [];
  const clock: Record<string, unknown>[] = [];
  const push = (event_type: string, producer: string, payload: Record<string, unknown>, sim_time: string | null = null, workflow_id: string | null = null) =>
    events.push({ seq: ++seq, event_id: `EVT-${seq}`, event_type, event_version: 1, occurred_at: "2026-11-05T05:41:00.000+00:00", recorded_at: "2026-11-05T05:41:00.000+00:00", sim_time, tenant_id: TENANT, account_id: SIM_ACC, simulation_id: SID, workflow_id, correlation_id: null, causation_id: null, producer, payload });
  const task = (agent: string, type: string, to: string, summary: string | null, at: string | null, id: string, error: string | null = null) =>
    push("TASK_STATE_CHANGED", agent, { task_id: id, task_type: type, agent, from: to === "COMPLETED" ? "VALIDATED" : "RUNNING", to, error, summary }, at);
  let step = 0;
  const adv = (day: string, i: number) => {
    step += 1;
    push("CLOCK_ADVANCED", "SIMULATION_CLOCK", { seq: step, session_date: day, phase: PH[i][0], workflows: [] }, simTime(day, i));
    clock.push({ simulation_id: SID, seq: step, session_date: day, phase: PH[i][0], sim_time: simTime(day, i), wall_time: "2026-11-05T05:41:00.000+00:00", workflows: [] });
  };
  push("SIMULATION_CREATED", `user:${TENANT}`, { name: "Replay 2–3 Nov", mode: "HISTORICAL_REPLAY", start_date: "2026-11-02", end_date: "2026-11-03", versions: VERSIONS });
  push("SIMULATION_STATE_CHANGED", `user:${TENANT}`, { from: "CREATED", to: "RUNNING", error: null });
  SESSIONS.forEach((day, d) => {
    task("TECH_SUPPORT", "PREMARKET_HEALTH_CHECK", "COMPLETED", `READY: data for ${day} published (cash and F&O)`, simTime(day, 0), `TSK-pm-${d}`);
    push("PREMARKET_READY", "ORCHESTRATOR", { session_date: day, status: "READY", allowed_segments: ["CASH", "FUTURES", "OPTIONS"] }, simTime(day, 0));
    adv(day, 0);
    for (const [sym] of PROPOSALS[d]) push("SIGNAL_DETECTED", "AI_TRADER", { signal_id: `SIG-${sym.toLowerCase()}${d}`, instrument: sym, segment: "FUTURES", direction: d === 0 ? "BULLISH" : "BEARISH", category: d === 0 ? "LONG_BUILDUP" : "SHORT_BUILDUP", signal_score: "72.50", data_as_of: `${day}T00:00:00+00:00` });
    task("AI_TRADER", "SCAN_MARKET", "COMPLETED", "238 signals from 224 instruments (101 suppressed or skipped)", simTime(day, 1), `TSK-scan-${d}`);
    adv(day, 1);
    PROPOSALS[d].forEach(([sym, strat, loss, pct], k) => {
      const tr = `TRD-${sym.toLowerCase()}${d}`;
      const at = simTime(day, 2);
      push("HANDOFF_RECORDED", "ORCHESTRATOR", { handoff_id: `HND-${d}${k}a`, from_task_id: `TSK-scan-${d}`, to_task_id: `TSK-ta-${d}${k}`, from_agent: "AI_TRADER", to_agent: "TRADING_ASSISTANT", entity_id: `SIG-${sym.toLowerCase()}${d}` });
      push("TRADE_PLAN_CREATED", "TRADING_ASSISTANT", { trade_id: tr, version: 1, strategy_type: strat, instrument: sym, max_loss_rs: loss });
      task("TRADING_ASSISTANT", "GENERATE_STRATEGY", "COMPLETED", `PLAN: ${sym} ${strat} max loss ${loss}`, at, `TSK-ta-${d}${k}`);
      push("HANDOFF_RECORDED", "ORCHESTRATOR", { handoff_id: `HND-${d}${k}b`, from_task_id: `TSK-ta-${d}${k}`, to_task_id: `TSK-risk-${d}${k}`, from_agent: "TRADING_ASSISTANT", to_agent: "RISK_OPS", entity_id: tr });
      if (d === 1 && k === 0) task("RISK_OPS", "ASSESS_RISK", "RETRY_PENDING", null, at, `TSK-risk-${d}${k}`, "TimeoutError: the option chain read took 31 s (deadline 30 s)");
      push("RISK_ASSESSMENT_COMPLETED", "RISK_OPS", { assessment_id: `RSK-${sym.toLowerCase()}${d}`, trade_id: tr, plan_version: 1, verdict: "PASS", violations: [] });
      task("RISK_OPS", "ASSESS_RISK", "COMPLETED", "PASS: 0 violations, 0 warnings", at, `TSK-risk-${d}${k}`);
      push("HANDOFF_RECORDED", "ORCHESTRATOR", { handoff_id: `HND-${d}${k}c`, from_task_id: `TSK-risk-${d}${k}`, to_task_id: `TSK-mo-${d}${k}`, from_agent: "RISK_OPS", to_agent: "MIDDLE_OFFICE", entity_id: tr });
      push("APPROVAL_GRANTED", "MIDDLE_OFFICE", { approval_id: `APR-${sym.toLowerCase()}${d}`, trade_id: tr, plan_version: 1, status: "APPROVED", decided_by: "MIDDLE_OFFICE@autodesk-mo-v1", reasons: ["within the autonomy rules of the policy", `risk ${pct}% of equity`], supersedes_id: null });
      task("MIDDLE_OFFICE", "REVIEW_FOR_APPROVAL", "COMPLETED", `APPROVED: within the autonomy rules of the policy; risk ${pct}% of equity`, at, `TSK-mo-${d}${k}`);
    });
    adv(day, 2);
    adv(day, 3);
    adv(day, 4);
    adv(day, 5);
  });
  push("SIMULATION_STATE_CHANGED", "SIMULATION_CLOCK", { from: "RUNNING", to: "COMPLETED", error: null }, simTime("2026-11-03", 5));
  return { clock, events };
}

const nf = (id: string) => reply(404, { error: "NOT_FOUND", message: `not found: ${id}` });

function timelineHandler(tl: { clock: Record<string, unknown>[]; events: Record<string, unknown>[] }): Handler {
  return (r: Req) => {
    const after = Number(r.query.get("after_seq") ?? 0);
    const limit = Number(r.query.get("limit") ?? 1000);
    return { clock: tl.clock, events: tl.events.filter((e) => (e.seq as number) > after).slice(0, limit) };
  };
}

/** Read-only routes of the completed run. */
export function doneRoutes(over: Record<string, RouteValue> = {}): Record<string, RouteValue> {
  const tl = buildTimeline();
  return {
    "GET /simulations": [SIM_DONE],
    "GET /simulations/:sid": ((r: Req) => (r.params.sid === SID ? SIM_DONE : nf(r.params.sid))) as Handler,
    "GET /simulations/:sid/results": RESULTS,
    "GET /simulations/:sid/agents": SIM_AGENTS,
    "GET /simulations/:sid/workflows": WORKFLOWS,
    "GET /simulations/:sid/timeline": timelineHandler(tl),
    "GET /desk/workflows/:wid": ((r: Req) => workflowDetail(r.params.wid) ?? nf(r.params.wid)) as Handler,
    ...over,
  };
}

// ── a run that moves: CREATED → start → step → run (background) → pause / resume / stop ───────────────────────────

export const NEW_SID = "SIM-7e6d5c4b3a2f1e0d9c8b";

const emptyResults = (status: string) => ({
  ...RESULTS, simulation_id: NEW_SID, status, phases_run: 0, premarket: {}, signals: { total: 0, by_category: {}, by_status: {}, by_segment: {} },
  plans: { total: 0, by_status: {}, by_strategy: {} }, approvals: { by_status: {}, by_decider: {} }, agents: {}, handoffs: 0,
});

export interface LiveSim { row: Record<string, unknown>; polls: number }

export function liveSim(mode = "HISTORICAL_REPLAY", status = "CREATED"): LiveSim {
  return {
    polls: 0,
    row: {
      ...SIM_DONE, simulation_id: NEW_SID, name: "Desk replay", mode, status, step_seq: 0, clock_sim_time: null, clock_session: null, clock_phase: null, results: null,
      started_at: null, ended_at: null, created_at: NOW, background_run: false,
      config: { ...CONFIG, name: "Desk replay", mode, start_date: "2026-11-03", end_date: "2026-11-04", max_proposals_per_session: 5, speed: mode === "ACCELERATED_REPLAY" ? "ACCELERATED" : "STEP", sessions: ["2026-11-03", "2026-11-04"] },
    },
  };
}

function moveTo(s: LiveSim, seq: number) {
  const sessions = (s.row.config as { sessions: string[] }).sessions;
  const total = sessions.length * 6;
  const n = Math.min(seq, total);
  const day = sessions[Math.floor((n - 1) / 6)];
  const i = (n - 1) % 6;
  Object.assign(s.row, { step_seq: n, clock_session: day, clock_phase: PH[i][0], clock_sim_time: simTime(day, i) });
  if (n >= total) Object.assign(s.row, { status: "COMPLETED", background_run: false, ended_at: NOW });
}

/** Routes over a moving simulation. Every lifecycle POST changes what the next GET returns. */
export function liveRoutes(s: LiveSim, over: Record<string, RouteValue> = {}): Record<string, RouteValue> {
  const conflict = (msg: string) => reply(409, { error: "CONFLICT", message: msg });
  const set = (from: string[], to: string, extra: Record<string, unknown> = {}) => {
    if (!from.includes(String(s.row.status))) return conflict(`simulation is ${s.row.status}; cannot move to ${to}`);
    Object.assign(s.row, { status: to, ...extra });
    return { ...s.row };
  };
  return {
    "GET /simulations": () => [{ ...s.row }],
    "POST /simulations": ((r: Req) => {
      const b = r.body as Record<string, unknown>;
      Object.assign(s.row, { name: b.name, mode: b.mode, status: "CREATED", step_seq: 0, config: { ...(s.row.config as object), ...b, sessions: [b.start_date, b.end_date] } });
      return reply(201, { ...s.row });
    }) as Handler,
    "GET /simulations/:sid": ((r: Req) => {
      if (r.params.sid !== NEW_SID) return nf(r.params.sid);
      if (s.row.status === "RUNNING" && s.row.background_run) { s.polls += 1; moveTo(s, (s.row.step_seq as number) + 6); }
      return { ...s.row };
    }) as Handler,
    "GET /simulations/:sid/results": () => emptyResults(String(s.row.status)),
    "GET /simulations/:sid/agents": { simulation_id: NEW_SID, versions: VERSIONS, agents: {} },
    "GET /simulations/:sid/workflows": [],
    "GET /simulations/:sid/timeline": () => ({ clock: [], events: [] }),
    "POST /simulations/:sid/start": () => set(["CREATED"], "RUNNING", { started_at: NOW }),
    "POST /simulations/:sid/pause": () => set(["RUNNING"], "PAUSED", { background_run: false }),
    "POST /simulations/:sid/resume": () => set(["PAUSED"], "RUNNING"),
    "POST /simulations/:sid/stop": () => set(["CREATED", "RUNNING", "PAUSED"], "STOPPED", { ended_at: NOW, background_run: false }),
    "POST /simulations/:sid/step": ((r: Req) => {
      if (s.row.status !== "RUNNING") return conflict(`simulation is ${s.row.status}; it does not step`);
      const unit = (r.body as { unit?: string } | null)?.unit ?? "PHASE";
      const cur = s.row.step_seq as number;
      moveTo(s, unit === "SESSION" ? (Math.floor(cur / 6) + 1) * 6 : cur + 1);
      return { simulation_id: NEW_SID, status: s.row.status, steps: [], step_seq: s.row.step_seq, clock_sim_time: s.row.clock_sim_time, clock_phase: s.row.clock_phase };
    }) as Handler,
    "POST /simulations/:sid/run": () => {
      if (s.row.status !== "RUNNING") return conflict(`simulation is ${s.row.status}; start or resume it first`);
      s.row.background_run = true;
      return reply(202, { simulation_id: NEW_SID, status: "RUNNING", background_run: true });
    },
    ...over,
  };
}

/** The completed run plus a new one created from the screen (GET /simulations lists the new run first once created). */
export function mixedRoutes(s: LiveSim, over: Record<string, RouteValue> = {}): Record<string, RouteValue> {
  const live = liveRoutes(s);
  const done = doneRoutes();
  let created = false;
  const call = (v: RouteValue, r: Req, st: unknown) => (typeof v === "function" ? (v as Handler)(r, st as never) : v);
  const routes: Record<string, RouteValue> = { ...done };
  for (const k of Object.keys(live)) {
    if (!k.includes(":sid")) continue;
    routes[k] = ((r: Req, st: unknown) => (r.params.sid === NEW_SID ? call(live[k], r, st) : done[k] !== undefined ? call(done[k], r, st) : nf(r.params.sid))) as Handler;
  }
  routes["POST /simulations"] = ((r: Req, st: unknown) => { created = true; return call(live["POST /simulations"], r, st); }) as Handler;
  routes["GET /simulations"] = (() => (created ? [{ ...s.row }, SIM_DONE] : [SIM_DONE])) as Handler;
  return { ...routes, ...over };
}
