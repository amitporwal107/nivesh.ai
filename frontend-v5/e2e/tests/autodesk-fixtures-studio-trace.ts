/**
 * Fixtures for the Simulation studio · Agent trace spec (autodesk-studio-trace.spec.ts).
 *
 * // MOCK — not real data. Bodies copy the real desk API's shapes: GET /simulations rows, GET /simulations/{sid}/workflows
 * // (autodesk.workflows rows with the TRADE_PROPOSAL outcomes orchestrator/engine.py writes), GET /desk/workflows/{id}
 * // ({workflow, tasks: full autodesk.agent_tasks rows, handoffs: autodesk.agent_handoffs rows, children}), GET /trade-plans
 * // and GET /signals/{id}. result_summary texts follow the agents' own formats (see autodesk-fixtures-agents.ts); the
 * // instruments follow the Phase 1 real-data replay of 2–3 Nov 2026. The chains are crafted to cover: a revised plan that
 * // ends waiting on a person, a plain approval, no plan at the strategy stage, and a risk task that failed.
 */
import { TENANT, reply, type Handler, type Req, type RouteValue } from "./autodesk-mock";
import { VERSIONS } from "./autodesk-fixtures-simulator";

export const SID = "SIM-3d5f7a9c1e2b4d6f8a0c";
export const EMPTY_SID = "SIM-6b8d0f2a4c6e8a0b2d4f";
const ACC = "ACC-3d5f7a9c1e2b4d6f8a0c";
const POL = "POL-1b7e93c4d05a4e2f9c61";

const run = (id: string, created: string) => ({
  simulation_id: id, tenant_id: TENANT, name: `Replay ${id.slice(4, 8)}`, mode: "HISTORICAL_REPLAY", status: "COMPLETED",
  config: { name: `Replay ${id.slice(4, 8)}`, description: "", mode: "HISTORICAL_REPLAY", start_date: "2026-11-02", end_date: "2026-11-03", universe: "FNO", include_fno: true, starting_capital_rs: "10000000", operating_mode: "AUTONOMOUS_PAPER", policy_id: null, max_proposals_per_session: 4, symbols: null, seed: 42, speed: "STEP", sessions: ["2026-11-02", "2026-11-03"] },
  account_id: `ACC-${id.slice(4)}`, clock_sim_time: "2026-11-03T12:30:00+00:00", clock_session: "2026-11-03", clock_phase: "EOD", step_seq: 12, versions: VERSIONS, results: null, error: null,
  created_by: `user:${TENANT}`, created_at: created, started_at: created, ended_at: created, updated_at: created,
});
export const RUN = run(SID, "2026-11-05T05:20:00.000+00:00");
export const EMPTY_RUN = run(EMPTY_SID, "2026-11-05T04:10:00.000+00:00");

type Kind = "approved" | "revised_human" | "no_trade" | "risk_failed" | "human";
interface P { inst: string; day: string; kind: Kind; strat: string; cat: string; score: string }
const PROPS: P[] = [
  { inst: "PETRONET", day: "2026-11-02", kind: "approved", strat: "BULL_CALL_SPREAD", cat: "LONG_BUILDUP", score: "74.50" },
  { inst: "GRASIM", day: "2026-11-02", kind: "human", strat: "BULL_CALL_SPREAD", cat: "LONG_BUILDUP", score: "69.00" },
  { inst: "ADANIPORTS", day: "2026-11-02", kind: "revised_human", strat: "BULL_CALL_SPREAD", cat: "SHORT_COVERING", score: "68.00" },
  { inst: "HINDALCO", day: "2026-11-02", kind: "no_trade", strat: "BULL_CALL_SPREAD", cat: "LONG_BUILDUP", score: "66.50" },
  { inst: "DLF", day: "2026-11-03", kind: "risk_failed", strat: "BEAR_PUT_SPREAD", cat: "SHORT_BUILDUP", score: "71.00" },
  { inst: "TATASTEEL", day: "2026-11-03", kind: "approved", strat: "BEAR_PUT_SPREAD", cat: "SHORT_BUILDUP", score: "72.25" },
  { inst: "ONGC", day: "2026-11-03", kind: "approved", strat: "BEAR_CALL_SPREAD", cat: "LONG_UNWINDING", score: "70.75" },
];

const low = (s: string) => s.toLowerCase();
export const wfId = (p: P) => `WF-${low(p.inst)}-${p.day.slice(8)}a1b2c3d4`;
export const sigId = (p: P) => `SIG-${low(p.inst)}${p.day.slice(8)}e5f6a7b8c9`;
export const trdId = (p: P) => `TRD-${low(p.inst)}${p.day.slice(8)}0d1e2f3a4b`;
const simAt = (day: string) => `${day}T03:30:00+00:00`;     // 09:00 IST, the PROPOSALS phase
export const BY_INST = Object.fromEntries(PROPS.map((p) => [p.inst, p])) as Record<string, P>;

function outcome(p: P): Record<string, unknown> {
  switch (p.kind) {
    case "approved": return { result: "APPROVED_NO_EXECUTION", trade_id: trdId(p), plan_version: 1, approval_id: `APR-${low(p.inst)}`, note: "Phase 1 has no execution; Phase 2 adds paper orders" };
    case "human": return { result: "WAITING_HUMAN", trade_id: trdId(p), plan_version: 1, approval_id: `APR-${low(p.inst)}` };
    case "revised_human": return { result: "WAITING_HUMAN", trade_id: trdId(p), plan_version: 2, approval_id: `APR-${low(p.inst)}` };
    case "no_trade": return { result: "NO_TRADE", reasons: [`BULL_CALL_SPREAD: the 760 CE did not trade on ${p.day}`], stage: "strategy" };
    case "risk_failed": return { result: "FAILED", reason: "risk task: TimeoutError: market.daily_bars read timed out (deadline 30 s)", trade_id: trdId(p) };
  }
}

export function wfRow(p: P, i: number) {
  const st = p.kind === "human" || p.kind === "revised_human" ? "WAITING_HUMAN" : p.kind === "risk_failed" ? "FAILED" : "COMPLETED";
  return {
    workflow_id: wfId(p), tenant_id: TENANT, account_id: ACC, simulation_id: SID, kind: "TRADE_PROPOSAL", state: st, parent_workflow_id: `WF-cycle-${p.day}`,
    correlation_id: `${SID}:${p.day}`, session_date: p.day, sim_time: simAt(p.day),
    input: { session_date: p.day, policy_id: POL, policy_version: 1, universe: "FNO", symbols: null, max_proposals: 4, operating_mode: "AUTONOMOUS_PAPER", signal_id: sigId(p) },
    outcome: outcome(p), error: p.kind === "risk_failed" ? "risk task: TimeoutError: market.daily_bars read timed out (deadline 30 s)" : null,
    created_at: `2026-11-05T05:2${p.day === "2026-11-02" ? 1 : 3}:${String(10 + i).padStart(2, "0")}.000+00:00`, updated_at: "2026-11-05T05:25:00.000+00:00", completed_at: "2026-11-05T05:25:00.000+00:00",
  };
}

export const WORKFLOWS = [
  { workflow_id: "WF-cycle-2026-11-02", tenant_id: TENANT, account_id: ACC, simulation_id: SID, kind: "SESSION_CYCLE", state: "COMPLETED", parent_workflow_id: null, correlation_id: `${SID}:2026-11-02`, session_date: "2026-11-02", sim_time: "2026-11-02T03:00:00+00:00", input: {}, outcome: { result: "CYCLE_COMPLETED" }, error: null, created_at: "2026-11-05T05:21:00.000+00:00", updated_at: "2026-11-05T05:25:00.000+00:00", completed_at: "2026-11-05T05:25:00.000+00:00" },
  ...PROPS.map(wfRow),
];

export function signalRow(p: P) {
  return {
    signal_id: sigId(p), account_id: ACC, simulation_id: SID, workflow_id: `WF-scan-${p.day}`, task_id: `TASK-scan-${p.day}`, instrument: p.inst, exchange: "NSE", segment: "FUTURES",
    direction: p.strat.startsWith("BULL") ? "BULLISH" : "BEARISH", timeframe: "POSITIONAL", category: p.cat, signal_score: p.score, calibrated_probability: null,
    body: { score_breakdown: [], evidence: [], missing_inputs: [], fno_eligible: true }, session_date: p.day, data_as_of: `${p.day}T00:00:00+00:00`,
    rule_version: "ait-rules-v1", model_version: null, expires_at: `${p.day}T12:30:00+00:00`, status: "CONSUMED", created_at: "2026-11-05T05:21:05.000+00:00",
  };
}

export const PLANS = PROPS.filter((p) => p.kind !== "no_trade").map((p) => ({
  trade_id: trdId(p), account_id: ACC, simulation_id: SID, workflow_id: wfId(p), signal_id: sigId(p), instrument: p.inst, strategy_type: p.strat,
  current_version: p.kind === "revised_human" ? 2 : 1, status: p.kind === "approved" ? "EXPIRED" : p.kind === "risk_failed" ? "REJECTED" : "AWAITING_APPROVAL",
  created_at: "2026-11-05T05:21:20.000+00:00", updated_at: "2026-11-05T05:25:00.000+00:00",
}));

// ── full task rows ─────────────────────────────────────────────────────────────────────────────────────────────────

const tool = (t: string, ms: number, rows: number | null = 60, ok = true) => ({ tool: t, args: {}, as_of: "2026-11-01T13:00:00+00:00", ok, rows: ok ? rows : null, error: ok ? null : "timed out", ms });
const OK = { schema_ok: true, domain_ok: true, errors: [] };
const at = (k: number) => `2026-11-05T05:22:${String(10 + k * 2).padStart(2, "0")}.120000+00:00`;

function task(p: P, key: string, to: string, type: string, step: string, o: {
  entity?: string; inputs: string[]; schema: string; result: Record<string, unknown> | null; summary: string | null; latency: number | null; tools?: Record<string, unknown>[];
  state?: string; attempt?: number; error?: string | null; validation?: Record<string, unknown> | null; ref?: string | null; version: string; seq: number;
}) {
  const created = at(o.seq);
  return {
    task_id: `TASK-${low(p.inst)}-${key}`, workflow_id: wfId(p), simulation_id: SID, tenant_id: TENANT, account_id: ACC, from_agent: "ORCHESTRATOR", to_agent: to, task_type: type, step,
    entity_id: o.entity ?? trdId(p), input_refs: o.inputs, constraints: {}, required_output_schema: o.schema, state: o.state ?? "COMPLETED", attempt: o.attempt ?? 1, max_attempts: 2,
    deadline_s: "30.000", sim_time: simAt(p.day), result: o.result, result_summary: o.summary, result_ref: o.ref ?? null, evidence_refs: o.inputs, tool_calls: o.tools ?? [],
    validation: o.validation === undefined ? OK : o.validation, error: o.error ?? null, agent_version: o.version, model: null, prompt_version: null, idempotency_key: `${wfId(p)}:${key}`,
    created_at: created, assigned_at: created, accepted_at: created, started_at: created, completed_at: o.state === "FAILED" ? null : created, latency_ms: o.latency, updated_at: created,
  };
}

const leg = (side: string, sym: string, lots: number, lotSize: number, price: string) => ({ leg_id: `L${side[0]}`, kind: sym.endsWith("CE") ? "CE" : "PE", underlying: sym.replace(/26NOV.*/, ""), tradingsymbol: sym, expiry: "2026-11-24", strike: null, side, lots, lot_size: lotSize, quantity: lots * lotSize, ref_price: price, ref_price_source: "fno_bhavcopy.close 2026-10-30" });
const plan = (p: P, lots: number, loss: string) => ({
  instrument: p.inst, segment: "OPTIONS", strategy_type: p.strat, max_loss_rs: loss, max_profit_rs: "61053.00", capital_required_rs: loss,
  legs: [leg("BUY", `${p.inst}26NOV1400CE`, lots, 475, "32.10"), leg("SELL", `${p.inst}26NOV1440CE`, lots, 475, "17.20")],
});
const checks = (fail: string[] = []) => Array.from({ length: 14 }, (_, i) => ({ name: i === 0 && fail.length ? fail[0] : `check_${i}`, outcome: i === 0 && fail.length ? "FAIL" : "PASS", hard: true }));
const RISK_TOOLS = [tool("market.daily_bars", 92), tool("market.lot_size", 10, 1), tool("market.sector", 7, 1)];
const TA_TOOLS = [tool("market.options", 412, 214), tool("market.expiries", 35, 6), tool("market.lot_size", 12, 1), tool("market.vix", 9, 1), tool("market.daily_bars", 88)];

function chain(p: P) {
  const t: ReturnType<typeof task>[] = [];
  let n = 0;
  const sig = sigId(p);
  const tr = trdId(p);
  const ta = (key: string, type: string, lots: number, loss: string, inputs: string[]) =>
    task(p, key, "TRADING_ASSISTANT", type, type === "GENERATE_STRATEGY" ? "plan" : "revise", {
      entity: type === "GENERATE_STRATEGY" ? sig : tr, inputs, schema: "strategy-proposal-v1", result: { decision: "PLAN", plan: plan(p, lots, loss), reasons: [], alternatives: [{ strategy_type: "BULL_PUT_SPREAD" }] },
      summary: `${p.strat.toLowerCase().replace(/_/g, " ")} on ${p.inst}, size ${lots}, loss ${loss}`, latency: type === "GENERATE_STRATEGY" ? 572 : 579, tools: type === "GENERATE_STRATEGY" ? TA_TOOLS : [tool("market.options", 398, 214)], version: "autodesk-ta-v1", seq: n++,
    });
  const risk = (key: string, v: number, verdict: string, summary: string, latency: number, viol: string[] = []) =>
    task(p, key, "RISK_OPS", "ASSESS_RISK", "risk", {
      inputs: [`plan://${tr}@${v}`, `book://${ACC}`], schema: "risk-assessment-v1", ref: `assessment://RSK-${low(p.inst)}${v}`,
      result: { assessment_id: `RSK-${low(p.inst)}${v}`, trade_id: tr, plan_version: v, verdict, checks: checks(viol), violations: viol, warnings: [], sizing: { proposed_lots: v === 1 ? 4 : 3, allowed_lots: 3, budget_rs: "50000.00" }, policy_id: POL, policy_version: 1, engine_version: "autodesk-risk-ops-v1" },
      summary, latency, tools: RISK_TOOLS, version: "autodesk-risk-ops-v1", seq: n++,
    });
  const mo = (key: string, v: number, status: string, reasons: string[], summary: string) =>
    task(p, key, "MIDDLE_OFFICE", "REVIEW_FOR_APPROVAL", "approval", {
      inputs: [`plan://${tr}@${v}`, `assessment://RSK-${low(p.inst)}${v}`], schema: "approval-decision-v1", ref: `approval://APR-${low(p.inst)}`,
      result: { approval_id: `APR-${low(p.inst)}`, trade_id: tr, plan_version: v, status, decided_by: "MIDDLE_OFFICE@autodesk-mo-v1", reasons, scope: null },
      summary, latency: 38, tools: [], version: "autodesk-mo-v1", seq: n++,
    });
  switch (p.kind) {
    case "approved":
      t.push(ta("ta0", "GENERATE_STRATEGY", 4, "48425.90", [`signal://${sig}`]), risk("risk1", 1, "PASS", "PASS: failed checks none", 340),
        mo("mo1", 1, "APPROVED", ["within the autonomy rules of the policy", "risk 0.48% of equity"], "APPROVED: within the autonomy rules of the policy; risk 0.48% of equity"));
      break;
    case "human":
      t.push(ta("ta0", "GENERATE_STRATEGY", 2, "41683.00", [`signal://${sig}`]), risk("risk1", 1, "PASS", "PASS: failed checks none", 430),
        mo("mo1", 1, "NEEDS_HUMAN_APPROVAL", ["signal score 69.00 is below 70"], "NEEDS_HUMAN_APPROVAL: signal score 69.00 is below 70"));
      break;
    case "revised_human":
      t.push(ta("ta0", "GENERATE_STRATEGY", 4, "54947.00", [`signal://${sig}`]),
        risk("risk1", 1, "REDUCE", "REDUCE: failed checks per_trade_risk; passes at 3 lots", 450, ["per_trade_risk"]),
        ta("ta1", "REVISE_STRATEGY", 3, "41210.25", [`plan://${tr}@1`, `assessment://RSK-${low(p.inst)}1`]),
        risk("risk2", 2, "PASS", "PASS: failed checks none", 880),
        mo("mo2", 2, "NEEDS_HUMAN_APPROVAL", ["signal score 68.00 is below 70"], "NEEDS_HUMAN_APPROVAL: signal score 68.00 is below 70"));
      break;
    case "no_trade":
      t.push(task(p, "ta0", "TRADING_ASSISTANT", "GENERATE_STRATEGY", "plan", {
        entity: sig, inputs: [`signal://${sig}`], schema: "strategy-proposal-v1", result: { decision: "NO_TRADE", plan: null, reasons: [`BULL_CALL_SPREAD: the 760 CE did not trade on ${p.day}`], alternatives: [] },
        summary: `no plan for ${p.inst}: BULL_CALL_SPREAD: the 760 CE did not trade on ${p.day}`, latency: 410, tools: [tool("market.options", 301, 188), tool("market.expiries", 30, 6)], version: "autodesk-ta-v1", seq: n++,
      }));
      break;
    case "risk_failed":
      t.push(ta("ta0", "GENERATE_STRATEGY", 3, "44310.20", [`signal://${sig}`]),
        task(p, "risk1", "RISK_OPS", "ASSESS_RISK", "risk", {
          inputs: [`plan://${tr}@1`, `book://${ACC}`], schema: "risk-assessment-v1", result: null, summary: null, latency: 30012, state: "FAILED", attempt: 2, validation: null,
          error: "TimeoutError: market.daily_bars read timed out (deadline 30 s)", tools: [tool("market.daily_bars", 30001, null, false)], version: "autodesk-risk-ops-v1", seq: n++,
        }));
      break;
  }
  return t;
}

const handoff = (id: string, wf: string, from: string, to: string, fa: string, ta: string, entity: string, created: string) => ({
  handoff_id: id, workflow_id: wf, simulation_id: SID, tenant_id: TENANT, from_task_id: from, to_task_id: to, from_agent: fa, to_agent: ta, entity_id: entity, created_at: created,
});

/** GET /desk/workflows/{id}: the workflow, its tasks (created order) and handoffs (the scan task's first). */
export function detail(id: string) {
  const i = PROPS.findIndex((p) => wfId(p) === id);
  if (i < 0) return null;
  const p = PROPS[i];
  const tasks = chain(p);
  const hs = [handoff(`HND-${low(p.inst)}-0`, wfId(p), `TASK-scan-${p.day}`, tasks[0].task_id, "AI_TRADER", "TRADING_ASSISTANT", sigId(p), tasks[0].created_at)];
  for (let k = 1; k < tasks.length; k++) {
    if (tasks[k - 1].state !== "COMPLETED") break;
    hs.push(handoff(`HND-${low(p.inst)}-${k}`, wfId(p), tasks[k - 1].task_id, tasks[k].task_id, tasks[k - 1].to_agent, tasks[k].to_agent, trdId(p), tasks[k].created_at));
  }
  return { workflow: wfRow(p, i), tasks, handoffs: hs, children: [] };
}

const nf = (id: string) => reply(404, { error: "NOT_FOUND", message: `not found: ${id}` });

/** Approval id of a plan's n-th approval row (the studio links to the newest). */
export const aprId = (p: P, n: number) => `APR-${low(p.inst)}-r${n}`;

/**
 * GET /approvals?simulation_id=&trade_id= — the approval rows of one simulated plan, newest first, as the API lists them.
 * TATASTEEL has two (a request that waited on a person, then the person's approval); a plan whose risk task failed has none.
 */
export function approvalRows(tradeId: string | null) {
  const p = PROPS.find((x) => trdId(x) === tradeId);
  if (!p || p.kind === "no_trade" || p.kind === "risk_failed") return [];
  const version = p.kind === "revised_human" ? 2 : 1;
  const row = (n: number, status: string, decidedBy: string, at: string, supersedes: string | null) => ({
    approval_id: aprId(p, n), tenant_id: TENANT, trade_id: trdId(p), plan_version: version, account_id: ACC, simulation_id: SID, status, decided_by: decidedBy,
    body: { status, decided_by: decidedBy, reasons: ["within the autonomy rules of the policy"], scope: null, expires_at: `${p.day}T10:00:00+00:00` },
    risk_assessment_id: `RSK-${low(p.inst)}${version}`, supersedes_id: supersedes, expires_at: `${p.day}T10:00:00+00:00`, created_at: at,
  });
  if (p.inst === "TATASTEEL") return [row(2, "APPROVED", `user:${TENANT}`, "2026-11-05T05:24:30.000+00:00", aprId(p, 1)), row(1, "NEEDS_HUMAN_APPROVAL", "MIDDLE_OFFICE@autodesk-mo-v1", "2026-11-05T05:24:10.000+00:00", null)];
  const status = p.kind === "approved" ? "APPROVED" : "NEEDS_HUMAN_APPROVAL";
  return [row(1, status, "MIDDLE_OFFICE@autodesk-mo-v1", "2026-11-05T05:24:10.000+00:00", null)];
}

export function traceRoutes(over: Record<string, RouteValue> = {}): Record<string, RouteValue> {
  return {
    "GET /simulations": [RUN, EMPTY_RUN],
    "GET /simulations/:sid/workflows": ((r: Req) => (r.params.sid === SID ? WORKFLOWS : r.params.sid === EMPTY_SID ? [WORKFLOWS[0]].map((w) => ({ ...w, simulation_id: EMPTY_SID })) : nf(r.params.sid))) as Handler,
    "GET /trade-plans": ((r: Req) => (r.query.get("simulation_id") === SID ? PLANS : [])) as Handler,
    "GET /signals/:id": ((r: Req) => { const p = PROPS.find((x) => sigId(x) === r.params.id); return p ? signalRow(p) : nf(r.params.id); }) as Handler,
    "GET /desk/workflows/:id": ((r: Req) => detail(r.params.id) ?? nf(r.params.id)) as Handler,
    "GET /approvals": ((r: Req) => (r.query.get("simulation_id") === SID ? approvalRows(r.query.get("trade_id")) : [])) as Handler,
    ...over,
  };
}
