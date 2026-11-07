/**
 * Fixtures for the Opportunity scanner spec (autodesk-scanner.spec.ts) and the agents spec.
 *
 * // MOCK — not real data. Shapes copy the real desk API: rows of autodesk.signals (body = the Signal model of
 * // backend/autodesk/contracts.py with the eight ait-rules-v1 dimensions and their weights), autodesk.trade_plans,
 * // autodesk.approvals, autodesk.workflows (SESSION_CYCLE outcome as orchestrator/engine.py writes it) and a policy
 * // version. Figures follow the Phase 1 real-data run of 5 Nov 2026 (174 signals from 224 F&O instruments; PETRONET,
 * // GRASIM and ADANIPORTS bull call spreads) but every row here is made up for the tests.
 */
import { ACCOUNT_A, NOW, TENANT, reply, type Req, type RouteValue } from "./autodesk-mock";

export { NOW };
export const ACC = ACCOUNT_A.account_id;
export const SESSION = "2026-11-05";
export const POLICY_ID = ACCOUNT_A.policy_id;
export const CYCLE_ID = "WF-0c5d2e8a41f94b7d9e31";
export const PREMARKET_WF = "WF-5e19c04a7b2d4e8f9a10";
export const SCAN_WF = "WF-3a8f61c0d2e74b59a6f2";
export const SCAN_TASK = "TASK-9e4b2a71c3d84f05b6e1";
export const SIM_ID = "SIM-7d2c9b0e1f3a48d6c5b4";

const EXPIRES = "2026-11-05T10:00:00+00:00";        // 15:30 IST, session close
const CASH_ASOF = "2026-11-04T14:00:00+00:00";      // 19:30 IST, cash EOD published
const FNO_ASOF = "2026-11-04T17:15:00+00:00";       // 22:45 IST, F&O EOD published
const SIG_CREATED = "2026-11-05T05:31:11.402000+00:00";
const VERSION = "autodesk-ait-v1/ait-rules-v1";

const W = { trend: 15, momentum: 15, volume_delivery: 15, relative_strength: 10, structure: 15, derivatives: 15, regime: 5, liquidity: 10 };
type DimKey = keyof typeof W;
const KEYS = Object.keys(W) as DimKey[];

interface SigSpec {
  id: string; instrument: string; segment: "CASH" | "FUTURES" | "OPTIONS" | "INDEX"; direction: "BULLISH" | "BEARISH" | "NEUTRAL";
  category: string; dims: [number | null, string][]; zone: [string, string]; inv: string | null; targets: string[]; ref: string;
  evidence: string[]; missing?: string[]; sector: string | null; fno: boolean; status: "DETECTED" | "CONSUMED" | "SUPPRESSED" | "EXPIRED";
  asof: string;
}

function signal(s: SigSpec) {
  const breakdown = s.dims.map(([p, detail], i) => ({ dimension: KEYS[i], weight: String(W[KEYS[i]]), points: String(p ?? 0), available: p != null, detail }));
  const score = s.dims.reduce((n, [p]) => n + (p ?? 0), 0);
  const scoreS = `${score}.00`;
  const body = {
    signal_id: s.id, tenant_id: TENANT, account_id: ACC, simulation_id: null, instrument: s.instrument, exchange: "NSE",
    segment: s.segment, direction: s.direction, timeframe: "POSITIONAL", category: s.category, signal_score: String(score),
    calibrated_probability: null, score_breakdown: breakdown, entry_zone: { low: s.zone[0], high: s.zone[1] },
    invalidation_price: s.inv, targets: s.targets, evidence: s.evidence,
    missing_inputs: s.missing ?? s.dims.flatMap(([p], i) => (p == null ? [KEYS[i]] : [])), reference_price: s.ref,
    fno_eligible: s.fno, sector: s.sector, data_as_of: s.asof, session_date: SESSION, model_version: VERSION,
    rule_version: "ait-rules-v1", expires_at: EXPIRES, status: "DETECTED",
  };
  return {
    signal_id: s.id, tenant_id: TENANT, account_id: ACC, simulation_id: null, workflow_id: SCAN_WF, task_id: SCAN_TASK,
    instrument: s.instrument, exchange: "NSE", segment: s.segment, direction: s.direction, timeframe: "POSITIONAL",
    category: s.category, signal_score: scoreS, calibrated_probability: null, body, session_date: SESSION, data_as_of: s.asof,
    rule_version: "ait-rules-v1", model_version: VERSION, expires_at: EXPIRES, status: s.status, dedupe_key: `${ACC}|${SESSION}|${s.instrument}|${s.segment}|${s.direction}|${s.category}`,
    created_at: SIG_CREATED, updated_at: SIG_CREATED,
  };
}

const VIX = "Nifty 50 above its SMA50; India VIX 15.19";
export const SIG = {
  PETRONET: "SIG-5b1e0c7d93a24f6e8a10",
  GRASIM: "SIG-8d2a6f1e04c94b37a5e2",
  ADANIPORTS: "SIG-c7e3a9b2d1f04e6a8b53",
  HINDALCO: "SIG-1f6b8e2a9c3d47e0b9a4",
  NIFTY: "SIG-a2c4e6f8b0d24c6e8a75",
  TATASTEEL: "SIG-e9d7c5b3a1f94e2c6b86",
  RELIANCE: "SIG-4a6c8e0b2d4f46a8c097",
  INFY: "SIG-b8f6d4a2c0e84b6d2fa8",
  SBIN: "SIG-6e8a0c2f4b6d48e0a2b9",
};

/** The session's desk signals, best score first (as GET /signals orders them). */
export const SIGNALS = [
  signal({ id: SIG.PETRONET, instrument: "PETRONET", segment: "FUTURES", direction: "BULLISH", category: "LONG_BUILDUP", asof: FNO_ASOF, fno: true, status: "CONSUMED",
    sector: "Oil Gas & Consumable Fuels", ref: "318.45", zone: ["316.40", "320.50"], inv: "306.15", targets: ["343.05", "355.35"],
    evidence: ["futures long buildup on 2026-11-04"],
    dims: [[15, "close 318.45, SMA20 305.12, SMA50 298.70 (10 sessions ago 296.10)"], [15, "RSI14 63.4"], [10, "volume 2.12× the 20-session average; delivery 41.3%"],
      [6, "20-session return 4.81% vs Nifty 50 1.92%"], [8, "20-session range 289.10–321.30"], [15, "futures long buildup: price 2.34% OI 6.18%"], [5, VIX],
      [6, "20-session average traded value ₹38.2 cr"]] }),
  signal({ id: SIG.GRASIM, instrument: "GRASIM", segment: "FUTURES", direction: "BULLISH", category: "SHORT_COVERING", asof: FNO_ASOF, fno: true, status: "CONSUMED",
    sector: "Construction Materials", ref: "2741.30", zone: ["2731.85", "2750.75"], inv: "2684.60", targets: ["2854.70", "2911.40"],
    evidence: ["futures short covering on 2026-11-04"],
    dims: [[15, "close 2741.30, SMA20 2688.40, SMA50 2652.95 (10 sessions ago 2640.10)"], [8, "RSI14 71.2"], [7, "volume 1.63× the 20-session average; delivery 38.0%"],
      [6, "20-session return 3.95% vs Nifty 50 1.92%"], [8, "20-session range 2610.00–2755.20"], [10, "futures short covering: price 1.12% OI −3.40%"], [5, VIX],
      [10, "20-session average traded value ₹412.7 cr"]] }),
  signal({ id: SIG.ADANIPORTS, instrument: "ADANIPORTS", segment: "FUTURES", direction: "BULLISH", category: "LONG_BUILDUP", asof: FNO_ASOF, fno: true, status: "CONSUMED",
    sector: "Services", ref: "1462.80", zone: ["1458.10", "1467.50"], inv: "1434.60", targets: ["1519.20", "1547.40"],
    evidence: ["futures long buildup on 2026-11-04"],
    dims: [[15, "close 1462.80, SMA20 1431.25, SMA50 1418.60 (10 sessions ago 1409.90)"], [8, "RSI14 54.6"], [4, "volume 1.27× the 20-session average; delivery 36.1%"],
      [3, "20-session return 2.41% vs Nifty 50 1.92%"], [8, "20-session range 1398.00–1471.40"], [15, "futures long buildup: price 1.06% OI 5.22%"], [5, VIX],
      [10, "20-session average traded value ₹624.3 cr"]] }),
  signal({ id: SIG.HINDALCO, instrument: "HINDALCO", segment: "FUTURES", direction: "BULLISH", category: "LONG_BUILDUP", asof: FNO_ASOF, fno: true, status: "CONSUMED",
    sector: "Metals & Mining", ref: "712.35", zone: ["709.60", "715.10"], inv: "695.85", targets: ["745.35", "761.85"],
    evidence: ["futures long buildup on 2026-11-04"],
    dims: [[10, "close 712.35, SMA20 698.10, SMA50 701.45 (10 sessions ago 699.30)"], [8, "RSI14 57.9"], [7, "volume 1.58× the 20-session average; delivery 33.4%"],
      [3, "20-session return 2.20% vs Nifty 50 1.92%"], [8, "20-session range 676.20–718.00"], [15, "futures long buildup: price 1.48% OI 4.71%"], [5, VIX],
      [10, "20-session average traded value ₹356.9 cr"]] }),
  signal({ id: SIG.NIFTY, instrument: "NIFTY", segment: "INDEX", direction: "BULLISH", category: "TREND_CONTINUATION", asof: FNO_ASOF, fno: true, status: "DETECTED",
    sector: null, ref: "23960.60", zone: ["23905.35", "24015.85"], inv: "23629.10", targets: ["24623.60", "24955.10"],
    evidence: ["index up-trend"],
    dims: [[15, "close 23960.60, SMA20 23810.15, SMA50 23705.40 (10 sessions ago 23640.20)"], [8, "RSI14 54.1"], [null, "not applicable to an index"],
      [null, "not applicable to the benchmark"], [8, "close on the trend side of SMA20 and SMA50"], [15, "futures long buildup: price 0.41% OI 3.06%"], [5, VIX],
      [10, "index derivatives"]] }),
  signal({ id: SIG.TATASTEEL, instrument: "TATASTEEL", segment: "FUTURES", direction: "BEARISH", category: "SHORT_BUILDUP", asof: FNO_ASOF, fno: true, status: "DETECTED",
    sector: "Metals & Mining", ref: "162.95", zone: ["162.20", "163.70"], inv: "167.45", targets: ["153.95", "149.45"],
    evidence: ["futures short buildup on 2026-11-04"],
    dims: [[10, "close 162.95, SMA20 165.40, SMA50 164.10 (10 sessions ago 163.20)"], [8, "RSI14 41.7"], [7, "volume 1.61× the 20-session average; delivery 29.8%"],
      [6, "20-session return −1.35% vs Nifty 50 1.92%"], [0, "20-session range 158.20–171.90"], [15, "futures short buildup: price −1.84% OI 7.42%"],
      [2, "Nifty 50 above its SMA50; India VIX 15.19"], [10, "20-session average traded value ₹981.0 cr"]] }),
  signal({ id: SIG.RELIANCE, instrument: "RELIANCE", segment: "CASH", direction: "BULLISH", category: "BREAKOUT", asof: CASH_ASOF, fno: true, status: "DETECTED",
    sector: "Oil Gas & Consumable Fuels", ref: "1311.00", zone: ["1306.10", "1315.90"], inv: "1281.60", targets: ["1369.80", "1399.20"],
    evidence: ["close 1311.0 above the prior 20-session high 1305.40 on 2.31× volume"], missing: ["delivery_pct"],
    dims: [[5, "close 1311.00, SMA20 1288.70, SMA50 1296.15 (10 sessions ago 1301.80)"], [8, "RSI14 69.0"], [10, "volume 2.31× the 20-session average"],
      [3, "20-session return 2.06% vs Nifty 50 1.92%"], [15, "20-session range 1262.00–1305.40"], [0, "futures long unwinding: price 0.62% OI −2.10%"], [5, VIX],
      [10, "20-session average traded value ₹1240.5 cr"]] }),
  signal({ id: SIG.INFY, instrument: "INFY", segment: "FUTURES", direction: "BEARISH", category: "BREAKDOWN", asof: CASH_ASOF, fno: true, status: "DETECTED",
    sector: "Information Technology", ref: "1514.30", zone: ["1508.40", "1520.20"], inv: "1549.70", targets: ["1443.50", "1408.10"],
    evidence: ["close 1514.3 below the prior 20-session low 1521.60 on 2.04× volume"],
    dims: [[5, "close 1514.30, SMA20 1538.20, SMA50 1530.75 (10 sessions ago 1526.40)"], [8, "RSI14 38.9"], [10, "volume 2.04× the 20-session average; delivery 44.7%"],
      [3, "20-session return 1.12% vs Nifty 50 1.92%"], [15, "20-session range 1521.60–1572.90"], [0, "futures short covering: price 0.21% OI −1.05%"],
      [2, "Nifty 50 above its SMA50; India VIX 15.19"], [10, "20-session average traded value ₹1188.2 cr"]] }),
  signal({ id: SIG.SBIN, instrument: "SBIN", segment: "FUTURES", direction: "BEARISH", category: "LONG_UNWINDING", asof: FNO_ASOF, fno: true, status: "DETECTED",
    sector: "Financial Services", ref: "812.40", zone: ["808.65", "816.15"], inv: "834.90", targets: ["767.40", "744.90"],
    evidence: ["futures long unwinding on 2026-11-04"],
    dims: [[10, "close 812.40, SMA20 819.85, SMA50 816.30 (10 sessions ago 815.10)"], [8, "RSI14 44.2"], [4, "volume 1.24× the 20-session average; delivery 47.5%"],
      [0, "20-session return 2.40% vs Nifty 50 1.92%"], [8, "20-session range 801.10–832.60"], [10, "futures long unwinding: price −0.92% OI −3.31%"],
      [2, "Nifty 50 above its SMA50; India VIX 15.19"], [10, "20-session average traded value ₹1452.8 cr"]] }),
];
export const signalById = (id: string) => SIGNALS.find((s) => s.signal_id === id);

// ── plans and approvals ──────────────────────────────────────────────────────────────────────────────────────────

export const TRD = { PETRONET: "TRD-2b4d6f8a0c1e43a5b7c9", GRASIM: "TRD-9a7c5e3b1d0f42c4e6a8", ADANIPORTS: "TRD-d4f2b0a8c6e44f1a3c5e" };
export const WFP = {
  PETRONET: "WF-71a3c5e7f9b14d2e6a80", GRASIM: "WF-82b4d6f8a0c24e3f7b91", HINDALCO: "WF-93c5e7a9b1d34f408ca2",
  ADANIPORTS: "WF-a4d6f8b0c2e44a519db3", SIM: "WF-b5e7a9c1d3f54b62aec4",
};
export const APR = {
  PETRONET: "APR-0e2c4a6b8d1f45c7e9a1", GRASIM: "APR-3c5e7a9b1d2f46e8a0b2",
  ADANIPORTS_MO: "APR-6f8a0c2e4b3d47a9c1d3", ADANIPORTS_PERSON: "APR-9b1d3f5a7c4e48b0d2e4", SIM: "APR-c4e6a8b0d2f549c1e3f5",
};

const plan = (trade_id: string, sym: string, signal_id: string, workflow_id: string, status: string, version = 1, created = "2026-11-05T05:31:12.880000+00:00") => ({
  trade_id, tenant_id: TENANT, account_id: ACC, simulation_id: null, workflow_id, signal_id, instrument: sym, strategy_type: "BULL_CALL_SPREAD",
  current_version: version, status, created_at: created, updated_at: created,
});
/** GET /trade-plans (newest first). */
export const PLANS = [
  plan(TRD.ADANIPORTS, "ADANIPORTS", SIG.ADANIPORTS, WFP.ADANIPORTS, "REJECTED", 2, "2026-11-05T05:31:15.910000+00:00"),
  plan(TRD.GRASIM, "GRASIM", SIG.GRASIM, WFP.GRASIM, "AWAITING_APPROVAL", 1, "2026-11-05T05:31:14.120000+00:00"),
  plan(TRD.PETRONET, "PETRONET", SIG.PETRONET, WFP.PETRONET, "APPROVED", 1, "2026-11-05T05:31:12.880000+00:00"),
];

const approval = (approval_id: string, trade_id: string, status: string, decided_by: string, reasons: string[], created: string,
  o: { version?: number; supersedes?: string | null; sim?: string | null } = {}) => ({
  approval_id, tenant_id: TENANT, trade_id, plan_version: o.version ?? 1, account_id: o.sim ? "ACC-SIM01JBX3K2M4N5P6Q7R8" : ACC, simulation_id: o.sim ?? null,
  status, decided_by, body: { status, decided_by, reasons, scope: null, expires_at: EXPIRES }, risk_assessment_id: "RSK-5f7a9c1e3b0d42f4a6c8",
  supersedes_id: o.supersedes ?? null, expires_at: EXPIRES, created_at: created,
});
/** GET /approvals (newest first; one simulation row that the desk must leave out). */
export const APPROVALS = [
  approval(APR.ADANIPORTS_PERSON, TRD.ADANIPORTS, "REJECTED", `user:${TENANT}`, ["sector already carries two plans today"], "2026-11-05T06:05:41.000000+00:00", { version: 2, supersedes: APR.ADANIPORTS_MO }),
  approval(APR.SIM, "TRD-e6a8c0b2d4f64a7c9e1b", "NEEDS_HUMAN_APPROVAL", "MIDDLE_OFFICE@autodesk-mo-v1", ["assisted mode: a person approves every plan"], "2026-11-05T05:50:02.000000+00:00", { sim: SIM_ID }),
  approval(APR.ADANIPORTS_MO, TRD.ADANIPORTS, "NEEDS_HUMAN_APPROVAL", "MIDDLE_OFFICE@autodesk-mo-v1", ["signal score 68.00 is below 70"], "2026-11-05T05:31:18.205000+00:00", { version: 2 }),
  approval(APR.GRASIM, TRD.GRASIM, "NEEDS_HUMAN_APPROVAL", "MIDDLE_OFFICE@autodesk-mo-v1", ["signal score 69.00 is below 70"], "2026-11-05T05:31:14.610000+00:00"),
  approval(APR.PETRONET, TRD.PETRONET, "APPROVED", "MIDDLE_OFFICE@autodesk-mo-v1", ["within the autonomy rules of the policy", "risk 0.48% of equity"], "2026-11-05T05:31:13.300000+00:00"),
];

/** What GET /approvals?pending=true answers: waiting on a person and not answered (the shell's badge reads it). */
export function approvalsHandler(rows = APPROVALS): RouteValue {
  return (r: Req) => {
    if (r.query.get("pending") !== "true") return rows;
    const answered = new Set(rows.map((a) => a.supersedes_id).filter(Boolean));
    return rows.filter((a) => a.status === "NEEDS_HUMAN_APPROVAL" && !answered.has(a.approval_id));
  };
}

// ── the session cycle ────────────────────────────────────────────────────────────────────────────────────────────

const CYCLE_INPUT = { session_date: SESSION, policy_id: POLICY_ID, policy_version: 1, universe: "FNO", symbols: null, max_proposals: 4, operating_mode: "AUTONOMOUS_PAPER" };

export const CYCLE_OUTCOME = {
  premarket: {
    status: "READY", session_date: SESSION, allowed_segments: ["CASH", "FUTURES", "OPTIONS"],
    data_as_of: { cash_eod: "2026-11-04", fno_eod: "2026-11-04" },
    checks: [{ name: "desk_db", status: "READY", detail: "answers", as_of: null }, { name: "cash_eod", status: "READY", detail: "2391 cash rows for 2026-11-04 (need 500)", as_of: "2026-11-04" },
      { name: "fno_eod", status: "READY", detail: "224 F&O underlyings for 2026-11-04 (need 50)", as_of: "2026-11-04" }, { name: "vix", status: "READY", detail: "India VIX 15.19", as_of: null }],
  },
  scan: { universe: "FNO", universe_size: 224, scanned: 221, signals: 174, suppressed: 128, scan_task_id: SCAN_TASK, data_as_of: FNO_ASOF, rule_version: "ait-rules-v1" },
  proposals: {
    candidates: 61, proposed: 4,
    results: [
      { workflow_id: WFP.PETRONET, instrument: "PETRONET", state: "COMPLETED", result: "APPROVED_NO_EXECUTION" },
      { workflow_id: WFP.GRASIM, instrument: "GRASIM", state: "WAITING_HUMAN", result: "WAITING_HUMAN" },
      { workflow_id: WFP.ADANIPORTS, instrument: "ADANIPORTS", state: "WAITING_HUMAN", result: "WAITING_HUMAN" },
      { workflow_id: WFP.HINDALCO, instrument: "HINDALCO", state: "COMPLETED", result: "NO_TRADE" },
    ],
  },
  result: "CYCLE_COMPLETED",
};

export const CYCLE = {
  workflow_id: CYCLE_ID, tenant_id: TENANT, account_id: ACC, simulation_id: null, kind: "SESSION_CYCLE", state: "COMPLETED",
  parent_workflow_id: null, correlation_id: CYCLE_ID, session_date: SESSION, sim_time: null, input: CYCLE_INPUT, outcome: CYCLE_OUTCOME,
  error: null, idempotency_key: `${ACC}:${SESSION}:cycle`, created_at: "2026-11-05T05:31:01.950000+00:00",
  updated_at: "2026-11-05T05:31:18.400000+00:00", completed_at: "2026-11-05T05:31:18.400000+00:00",
};
export const CYCLE_RUNNING = { ...CYCLE, state: "RUNNING", outcome: null, updated_at: CYCLE.created_at, completed_at: null };
/** An older cycle of a simulation that the desk must not pick (simulation_id set). */
export const SIM_CYCLE = { ...CYCLE, workflow_id: "WF-c6f8b0d2e4a64c73bfd5", simulation_id: SIM_ID, account_id: "ACC-SIM01JBX3K2M4N5P6Q7R8", created_at: "2026-11-05T06:00:00.000000+00:00" };

export const detailOf = (wf: Record<string, unknown>) => ({ workflow: wf, tasks: [], handoffs: [], children: [] });

export const POLICY = {
  policy_id: POLICY_ID, tenant_id: TENANT, name: "Default", scope_type: "TENANT", scope_ref: null, version: 1, current_version: 1,
  body: {
    policy_schema: "autodesk-policy-v1", source: "risk-profile owner-default-2026-10-27", per_trade_risk_pct: "0.5", open_risk_pct: "3",
    position_pct: "10", sector_pct: "25", daily_loss_pct: "2", weekly_loss_pct: "4", max_drawdown_pct: "10", min_reward_risk: "1.5",
    credit_min_width_fraction: "0.3333", max_margin_utilization_pct: "25", futures_margin_pct: "15", allowed_segments: ["CASH", "FUTURES", "OPTIONS"],
    allowed_strategies: ["LONG_EQUITY", "LONG_FUTURES", "LONG_CALL", "LONG_PUT", "BULL_CALL_SPREAD", "BEAR_PUT_SPREAD", "BULL_PUT_SPREAD", "BEAR_CALL_SPREAD", "IRON_CONDOR"],
    min_signal_score: "60", max_proposals_per_session: 5, min_days_to_expiry: 7, max_legs: 4, max_lots_per_leg: 10, min_adv_rs: "10000000",
    require_traded_legs: true, max_data_age_sessions: 1,
    autonomy: { auto_approve: true, max_risk_pct: "0.5", min_signal_score: "70", strategies: ["LONG_EQUITY", "BULL_CALL_SPREAD", "BEAR_PUT_SPREAD", "BULL_PUT_SPREAD", "BEAR_CALL_SPREAD", "IRON_CONDOR"] },
  },
  body_sha256: "4c1f0e8a2b6d93c7e5f1a0b2c4d6e8f0a1b3c5d7e9f1a2b4c6d8e0f2a4b6c8d0", created_at: "2026-11-05T05:20:11.120000+00:00", created_by: `user:${TENANT}`, reason: "default policy",
};

/** The AI Trader's scan task as GET /agents/AI_TRADER/activity lists it; result_ref says 172 of 174 were new rows. */
export const SCAN_TASK_ROW = {
  task_id: SCAN_TASK, workflow_id: SCAN_WF, simulation_id: null, task_type: "SCAN_MARKET", step: "scan", entity_id: null, state: "COMPLETED", attempt: 1,
  result_summary: "174 signals from 224 instruments (128 suppressed or skipped)", result_ref: `scan://${SCAN_WF}?signals=172`, error: null,
  agent_version: "autodesk-ait-v1", created_at: "2026-11-05T05:31:02.610000+00:00", completed_at: "2026-11-05T05:31:11.540000+00:00", latency_ms: 8930,
};

/** Routes the scanner reads, answering from the fixtures above; override any key per test. */
export function scannerRoutes(over: Record<string, RouteValue> = {}): Record<string, RouteValue> {
  return {
    "GET /desk/workflows": (r: Req) => (r.query.get("kind") === "SESSION_CYCLE" && r.query.get("account_id") === ACC ? [SIM_CYCLE, CYCLE] : []),
    "GET /desk/workflows/:id": (r: Req) => (r.params.id === CYCLE_ID ? detailOf(CYCLE) : reply(404, { error: "NOT_FOUND", message: `not found: ${r.params.id}` })),
    "GET /signals": (r: Req) => (r.query.get("session_date") === SESSION && r.query.get("account_id") === ACC ? SIGNALS : []),
    "GET /trade-plans": PLANS,
    "GET /approvals": approvalsHandler(),
    "GET /policies/:id": (r: Req) => (r.params.id === POLICY_ID ? POLICY : reply(404, { error: "NOT_FOUND", message: `not found: ${r.params.id}` })),
    "GET /agents/:agent_key/activity": (r: Req) => (r.params.agent_key === "AI_TRADER" ? [SCAN_TASK_ROW] : []),
    ...over,
  };
}
