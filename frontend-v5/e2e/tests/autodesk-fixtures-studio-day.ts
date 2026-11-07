/**
 * Simulation studio · Trading day fixtures for autodesk-studio-day.spec.ts.
 *
 * // MOCK — not real data. Bodies copy the shapes of the real simulation API (GET /simulations, /simulations/{sid},
 * // /results, /timeline {clock, events} and the lifecycle POSTs; backend/autodesk/routers/api.py, simulator/manager.py,
 * // store.py). The run has the shape of the Phase 1 real-data replay (two sessions, PREMARKET 08:30 → SCAN → PROPOSALS →
 * // OPEN → CLOSE → EOD 18:00 IST; signals at the scan, plan → risk → approval per chosen signal at 09:00, unused signals
 * // and unanswered approvals expired by SESSION_CLOSE at 18:00) with a handful of events per phase instead of hundreds.
 * // Events without their own sim_time are followed by the CLOCK_ADVANCED of the phase they ran in, as the real stream is.
 */
import { NOW, TENANT, reply, type Handler, type MockState, type Req, type RouteValue } from "./autodesk-mock";

export const SID = "SIM-4c1e8a2f6b3d4e5f7a9c";
export const OTHER_SID = "SIM-0d9e8f7a6b5c4d3e2f1a";
export const NEW_SID = "SIM-9a8b7c6d5e4f3a2b1c0d";
const ACC = "ACC-8e7d6c5b4a3f2e1d0c9b";
export const SESSIONS = ["2026-11-02", "2026-11-03"];
const PH: [string, string][] = [["PREMARKET", "03:00"], ["SCAN", "03:15"], ["PROPOSALS", "03:30"], ["OPEN", "03:45"], ["CLOSE", "10:00"], ["EOD", "12:30"]];
export const simTime = (day: string, i: number) => `${day}T${PH[i][1]}:00+00:00`;

export const POLICY = { policy_id: "POL-1b7e93c4d05a4e2f9c61", version: 1, sha256: "e3a1f09c7b5d2e4f6a8c0b1d3e5f7a9c2b4d6e8f0a1c3e5f7b9d1f3a5c7e9b0d" };
export const VERSIONS = {
  app: "0.1.0",
  agents: { AI_TRADER: "autodesk-ait-v1", TRADING_ASSISTANT: "autodesk-ta-v1", RISK_OPS: "autodesk-risk-v1", MIDDLE_OFFICE: "autodesk-mo-v1", TECH_SUPPORT: "autodesk-ts-v1" },
  market_view: "point-in-time; cash EOD visible 19:30 IST, F&O EOD 22:45 IST", risk_engine: "autodesk-risk-v1", scan_rules: "ait-rules-v1", policy: POLICY,
};

const config = (name: string, sessions: string[]) => ({
  name, description: "", mode: "HISTORICAL_REPLAY", start_date: sessions[0], end_date: sessions[sessions.length - 1], universe: "FNO", include_fno: true,
  starting_capital_rs: "10000000", operating_mode: "AUTONOMOUS_PAPER", policy_id: null, max_proposals_per_session: 3, symbols: null, seed: 42, speed: "STEP", sessions,
});

export const SIM_DONE: Record<string, unknown> = {
  simulation_id: SID, tenant_id: TENANT, name: "Replay 2–3 Nov", mode: "HISTORICAL_REPLAY", status: "COMPLETED", config: config("Replay 2–3 Nov", SESSIONS), account_id: ACC,
  clock_sim_time: simTime("2026-11-03", 5), clock_session: "2026-11-03", clock_phase: "EOD", step_seq: 12, versions: VERSIONS, results: null, error: null,
  created_by: `user:${TENANT}`, created_at: "2026-11-05T05:40:02.000+00:00", started_at: "2026-11-05T05:40:05.000+00:00", ended_at: "2026-11-05T05:44:51.000+00:00",
  updated_at: "2026-11-05T05:44:51.000+00:00", background_run: false,
};

export const SIM_OTHER: Record<string, unknown> = {
  ...SIM_DONE, simulation_id: OTHER_SID, name: "Replay 30 Oct", config: config("Replay 30 Oct", ["2026-10-30"]), clock_sim_time: simTime("2026-10-30", 5), clock_session: "2026-10-30",
  step_seq: 6, created_at: "2026-11-04T12:10:00.000+00:00", started_at: "2026-11-04T12:10:03.000+00:00", ended_at: "2026-11-04T12:12:40.000+00:00", updated_at: "2026-11-04T12:12:40.000+00:00",
};

export const resultsOf = (sid: string, status: string, violations = 0) => ({
  simulation_id: sid, status, mode: "HISTORICAL_REPLAY", sessions_total: 2, phases_run: 12, premarket: { READY: 2 },
  signals: { total: 11, by_category: { LONG_BUILDUP: 6, SHORT_BUILDUP: 5 }, by_status: { CONSUMED: 5, EXPIRED: 6 }, by_segment: { FUTURES: 11 } },
  plans: { total: 5, by_status: { EXPIRED: 5 }, by_strategy: { BULL_CALL_SPREAD: 2, BEAR_PUT_SPREAD: 3 } },
  approvals: { by_status: { APPROVED: 4, NEEDS_HUMAN_APPROVAL: 1, REJECTED: 1 }, by_decider: { MIDDLE_OFFICE: 5, SYSTEM: 1 } },
  agents: {}, handoffs: 15, policy_violation_attempts: violations, versions: VERSIONS,
  data: { first_session: "2026-11-02", last_session: "2026-11-03", universe: "FNO", symbols: null },
  limitations: ["Phase 1 has no execution: approved plans are not filled, so there is no P&L, no capital reservation and the daily-loss / weekly-loss / drawdown checks are skipped."],
  execution: "none in Phase 1 (no orders, fills or P&L)",
});

// ── the event stream of a 2-session run ──────────────────────────────────────────────────────────────────────────────

const DAYS: { signals: string[]; dir: string; cat: string; plans: [string, string, string, string, "GRANTED" | "NEEDS_HUMAN"][] }[] = [
  {
    signals: ["PETRONET", "GRASIM", "ADANIPORTS", "COALINDIA", "BEL", "IRCTC"], dir: "BULLISH", cat: "LONG_BUILDUP",
    plans: [["PETRONET", "BULL_CALL_SPREAD", "48425.90", "0.48", "GRANTED"], ["GRASIM", "BULL_CALL_SPREAD", "41683.00", "0.42", "GRANTED"]],
  },
  {
    signals: ["TATASTEEL", "HINDALCO", "DLF", "VEDL", "SAIL"], dir: "BEARISH", cat: "SHORT_BUILDUP",
    plans: [["TATASTEEL", "BEAR_PUT_SPREAD", "32118.40", "0.32", "GRANTED"], ["HINDALCO", "BEAR_PUT_SPREAD", "28904.75", "0.29", "GRANTED"], ["DLF", "BEAR_PUT_SPREAD", "44310.20", "0.44", "NEEDS_HUMAN"]],
  },
];

export interface Ev extends Record<string, unknown> { seq: number; step: number; event_type: string }
export interface Run { events: Ev[]; clock: Record<string, unknown>[] }

/** The full stream; `step` = the clock step an event belongs to (events of step k come before its CLOCK_ADVANCED). */
export function buildRun(sid: string, name: string, firstSeq = 7000): Run {
  let seq = firstSeq;
  let step = 1;
  const events: Ev[] = [];
  const clock: Record<string, unknown>[] = [];
  const push = (event_type: string, producer: string, payload: Record<string, unknown>, sim_time: string | null = null) =>
    events.push({ step, seq: ++seq, event_id: `EVT-${sid.slice(4, 10)}-${seq}`, event_type, event_version: 1, occurred_at: "2026-11-05T05:41:00.000+00:00", recorded_at: "2026-11-05T05:41:00.000+00:00", sim_time, tenant_id: TENANT, account_id: ACC, simulation_id: sid, workflow_id: null, correlation_id: null, causation_id: null, producer, payload });
  const task = (agent: string, type: string, to: string, summary: string | null, at: string | null, id: string, error: string | null = null) =>
    push("TASK_STATE_CHANGED", agent, { task_id: id, task_type: type, agent, from: to === "COMPLETED" ? "VALIDATED" : "RUNNING", to, error, summary }, at);
  const adv = (day: string, i: number) => {
    push("CLOCK_ADVANCED", "SIMULATION_CLOCK", { seq: step, session_date: day, phase: PH[i][0], workflows: [] }, simTime(day, i));
    clock.push({ simulation_id: sid, seq: step, session_date: day, phase: PH[i][0], sim_time: simTime(day, i), wall_time: "2026-11-05T05:41:00.000+00:00", workflows: [] });
    step += 1;
  };
  SESSIONS.forEach((day, d) => {
    const D = DAYS[d];
    if (d === 0) {
      push("SIMULATION_CREATED", `user:${TENANT}`, { name, mode: "HISTORICAL_REPLAY", start_date: SESSIONS[0], end_date: SESSIONS[1], versions: VERSIONS });
      push("SIMULATION_STATE_CHANGED", `user:${TENANT}`, { from: "CREATED", to: "RUNNING", error: null });
    }
    task("TECH_SUPPORT", "PREMARKET_HEALTH_CHECK", "COMPLETED", `READY: data for ${day} published (cash and F&O)`, simTime(day, 0), `TSK-pm-${d}`);
    push("PREMARKET_READY", "ORCHESTRATOR", { session_date: day, status: "READY", allowed_segments: ["CASH", "FUTURES", "OPTIONS"] }, simTime(day, 0));
    adv(day, 0);
    D.signals.forEach((sym, k) => push("SIGNAL_DETECTED", "AI_TRADER@autodesk-ait-v1", { signal_id: `SIG-${sym.toLowerCase()}${d}`, instrument: sym, segment: "FUTURES", direction: D.dir, category: D.cat, signal_score: (74.5 - k * 1.5).toFixed(2), data_as_of: `${day}T00:00:00+00:00` }));
    task("AI_TRADER", "SCAN_MARKET", "COMPLETED", `${D.signals.length} signals from 212 instruments (31 suppressed or skipped)`, simTime(day, 1), `TSK-scan-${d}`);
    adv(day, 1);
    D.plans.forEach(([sym, strat, loss, pct, verdict], k) => {
      const tr = `TRD-${sym.toLowerCase()}${d}`;
      const at = simTime(day, 2);
      push("HANDOFF_RECORDED", "ORCHESTRATOR", { handoff_id: `HND-${d}${k}a`, from_task_id: `TSK-scan-${d}`, to_task_id: `TSK-ta-${d}${k}`, from_agent: "AI_TRADER", to_agent: "TRADING_ASSISTANT", entity_id: `SIG-${sym.toLowerCase()}${d}` });
      push("TRADE_PLAN_CREATED", "TRADING_ASSISTANT@autodesk-ta-v1", { trade_id: tr, version: 1, strategy_type: strat, instrument: sym, max_loss_rs: loss });
      task("TRADING_ASSISTANT", "GENERATE_STRATEGY", "COMPLETED", `PLAN: ${sym} ${strat} max loss ${loss}`, at, `TSK-ta-${d}${k}`);
      push("HANDOFF_RECORDED", "ORCHESTRATOR", { handoff_id: `HND-${d}${k}b`, from_task_id: `TSK-ta-${d}${k}`, to_task_id: `TSK-risk-${d}${k}`, from_agent: "TRADING_ASSISTANT", to_agent: "RISK_OPS", entity_id: tr });
      if (d === 1 && k === 0) task("RISK_OPS", "ASSESS_RISK", "RETRY_PENDING", null, at, `TSK-risk-${d}${k}`, "TimeoutError: the option chain read took 31 s (deadline 30 s)");
      push("RISK_ASSESSMENT_COMPLETED", "RISK_OPS@autodesk-risk-v1", { assessment_id: `RSK-${sym.toLowerCase()}${d}`, trade_id: tr, plan_version: 1, verdict: "PASS", violations: [] });
      task("RISK_OPS", "ASSESS_RISK", "COMPLETED", "PASS: 0 violations, 0 warnings", at, `TSK-risk-${d}${k}`);
      push("HANDOFF_RECORDED", "ORCHESTRATOR", { handoff_id: `HND-${d}${k}c`, from_task_id: `TSK-risk-${d}${k}`, to_task_id: `TSK-mo-${d}${k}`, from_agent: "RISK_OPS", to_agent: "MIDDLE_OFFICE", entity_id: tr });
      if (verdict === "GRANTED") {
        push("APPROVAL_GRANTED", "MIDDLE_OFFICE@autodesk-mo-v1", { approval_id: `APR-${sym.toLowerCase()}${d}`, trade_id: tr, plan_version: 1, status: "APPROVED", decided_by: "MIDDLE_OFFICE@autodesk-mo-v1", reasons: ["within the autonomy rules of the policy", `risk ${pct}% of equity`], supersedes_id: null });
        task("MIDDLE_OFFICE", "REVIEW_FOR_APPROVAL", "COMPLETED", `APPROVED: within the autonomy rules of the policy; risk ${pct}% of equity`, at, `TSK-mo-${d}${k}`);
      } else {
        push("APPROVAL_NEEDS_HUMAN", "MIDDLE_OFFICE@autodesk-mo-v1", { approval_id: `APR-${sym.toLowerCase()}${d}`, trade_id: tr, plan_version: 1, status: "NEEDS_HUMAN_APPROVAL", decided_by: "MIDDLE_OFFICE@autodesk-mo-v1", reasons: ["notional above the autonomous threshold of the policy"], supersedes_id: null });
        task("MIDDLE_OFFICE", "REVIEW_FOR_APPROVAL", "COMPLETED", "NEEDS_HUMAN_APPROVAL: notional above the autonomous threshold of the policy", at, `TSK-mo-${d}${k}`);
      }
    });
    adv(day, 2);
    adv(day, 3);
    adv(day, 4);
    for (const sym of D.signals.filter((x) => !D.plans.some((p) => p[0] === x))) push("SIGNAL_EXPIRED", "SESSION_CLOSE", { signal_id: `SIG-${sym.toLowerCase()}${d}`, reason: "session closed" });
    for (const [sym] of D.plans.filter((p) => p[4] === "NEEDS_HUMAN")) {
      push("APPROVAL_EXPIRED", "SESSION_CLOSE", { approval_id: `APR-${sym.toLowerCase()}${d}x`, trade_id: `TRD-${sym.toLowerCase()}${d}`, plan_version: 1, status: "REJECTED", decided_by: "SYSTEM:session_close", reasons: ["the approval window closed at the session close"], supersedes_id: `APR-${sym.toLowerCase()}${d}` });
    }
    adv(day, 5);
  });
  step = 12;
  push("SIMULATION_STATE_CHANGED", "SIMULATION_CLOCK", { from: "RUNNING", to: "COMPLETED", error: null }, simTime("2026-11-03", 5));
  return { events, clock };
}

const strip = ({ step: _s, ...e }: Ev) => e;
const nf = (id: string) => reply(404, { error: "NOT_FOUND", message: `not found: ${id}` });

/** GET /simulations/{sid}/timeline over the clock steps reached so far; records the after_seq of every read. */
export function timelineHandler(run: Run, reached: () => number, afterSeqs: number[] = []): Handler {
  return (r: Req) => {
    const after = Number(r.query.get("after_seq") ?? 0);
    const limit = Number(r.query.get("limit") ?? 1000);
    afterSeqs.push(after);
    const n = reached();
    return {
      clock: run.clock.filter((c) => (c.seq as number) <= n),
      events: run.events.filter((e) => (e.step <= n || e.event_type === "SIMULATION_CREATED") && e.seq > after).slice(0, limit).map(strip),
    };
  };
}

/** Read-only routes of the completed run (and an older one-session run in the list). */
export function doneRoutes(over: Record<string, RouteValue> = {}, list: Record<string, unknown>[] = [SIM_DONE, SIM_OTHER]): Record<string, RouteValue> {
  const run = buildRun(SID, "Replay 2–3 Nov");
  return {
    "GET /simulations": list,
    "GET /simulations/:sid": ((r: Req) => (r.params.sid === SID ? SIM_DONE : r.params.sid === OTHER_SID ? SIM_OTHER : nf(r.params.sid))) as Handler,
    "GET /simulations/:sid/results": ((r: Req) => (r.params.sid === SID ? resultsOf(SID, "COMPLETED") : resultsOf(r.params.sid, "COMPLETED"))) as Handler,
    "GET /simulations/:sid/timeline": ((r: Req, s: MockState) => (r.params.sid === SID ? timelineHandler(run, () => 12)(r, s) : { clock: [], events: [] })) as Handler,
    ...over,
  };
}

// ── a run that moves: CREATED → start + run (background) → pause → resume + run ──────────────────────────────────────

export interface Live { row: Record<string, unknown>; polls: number; afterSeqs: number[] }

export function liveRun(status = "CREATED", step = 0): Live {
  const s: Live = {
    polls: 0, afterSeqs: [],
    row: {
      ...SIM_DONE, simulation_id: NEW_SID, name: "Desk replay", status, config: config("Desk replay", SESSIONS), step_seq: 0, clock_sim_time: null, clock_session: null, clock_phase: null,
      started_at: null, ended_at: null, created_at: NOW, updated_at: NOW, background_run: false,
    },
  };
  if (step) moveTo(s, step);
  return s;
}

function moveTo(s: Live, n: number) {
  const k = Math.min(n, 12);
  const day = SESSIONS[Math.floor((k - 1) / 6)];
  const i = (k - 1) % 6;
  Object.assign(s.row, { step_seq: k, clock_session: day, clock_phase: PH[i][0], clock_sim_time: simTime(day, i) });
  if (k >= 12) Object.assign(s.row, { status: "COMPLETED", background_run: false, ended_at: NOW });
}

/** Stateful routes: every lifecycle POST changes what the next GET returns; a background run moves one phase per poll. */
export function liveRoutes(s: Live, over: Record<string, RouteValue> = {}): Record<string, RouteValue> {
  const run = buildRun(NEW_SID, "Desk replay", 9000);
  const conflict = (msg: string) => reply(409, { error: "CONFLICT", message: msg });
  const set = (from: string[], to: string, extra: Record<string, unknown> = {}) => {
    if (!from.includes(String(s.row.status))) return conflict(`simulation is ${s.row.status}; cannot move to ${to}`);
    Object.assign(s.row, { status: to, ...extra });
    return { ...s.row };
  };
  return {
    "GET /simulations": () => [{ ...s.row }],
    "GET /simulations/:sid": ((r: Req) => {
      if (r.params.sid !== NEW_SID) return nf(r.params.sid);
      if (s.row.status === "RUNNING" && s.row.background_run) { s.polls += 1; moveTo(s, (s.row.step_seq as number) + 1); }
      return { ...s.row };
    }) as Handler,
    "GET /simulations/:sid/results": () => resultsOf(NEW_SID, String(s.row.status)),
    "GET /simulations/:sid/timeline": timelineHandler(run, () => s.row.step_seq as number, s.afterSeqs),
    "POST /simulations/:sid/start": () => set(["CREATED"], "RUNNING", { started_at: NOW }),
    "POST /simulations/:sid/pause": () => set(["RUNNING"], "PAUSED", { background_run: false }),
    "POST /simulations/:sid/resume": () => set(["PAUSED"], "RUNNING"),
    "POST /simulations/:sid/run": () => {
      if (s.row.status !== "RUNNING") return reply(409, { detail: `simulation is ${s.row.status}; start or resume it first` });
      s.row.background_run = true;
      return reply(202, { simulation_id: NEW_SID, status: "RUNNING", background_run: true });
    },
    ...over,
  };
}
