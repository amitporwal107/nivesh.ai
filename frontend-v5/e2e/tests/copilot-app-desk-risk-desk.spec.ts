/**
 * One-screen Copilot app (/v5/app) — Smart trading desk, tab 04 Risk Desk (desk redesign step 4;
 * screens/tradingdesk/tabs/risk-desk). Cases: test_reports/desk_risk_desk_TESTCASES.md (RD-1 … RD-19).
 *
 * MOCK — not real data. Every /api answer below is written by hand in the shape the route returns on the shell branch
 * (backend/routes/risk_controls.py: profile, freshness, status, kill-switch, halt, audit, decisions, lineage, replay,
 * live-readiness, admin jobs). User ids, symbols, reasons, ids and numbers are INVENTED. Expected text is worked out
 * here from the payloads, not copied from the screen. Production build, every /api mocked — see pw.copilot-app.config.ts.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", name), "utf-8"));

const DESK = "/v5/app/trader/desk";
const LIMITS = `${DESK}?tab=risk&view=limits`;
const CONTROLS = `${DESK}?tab=risk&view=controls`;
const LOG = `${DESK}?tab=risk&view=log`;
const SLOW = { timeout: 15_000 };

const reply = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const inr = (n: number) => `₹${new Intl.NumberFormat("en-IN").format(Math.round(n))}`;
const p2 = (n: number) => `${n.toFixed(2)}%`;

// ── the MOCK payloads ────────────────────────────────────────────────────

const LIMITS_SET = {
  per_trade_risk_pct: 0.5, max_open_risk_pct: 3, max_position_pct: 10, max_sector_pct: 25,
  daily_loss_pct: 2, weekly_loss_pct: 4, max_drawdown_pct: 10, min_reward_risk: 1.5,
};
const FIELDS = Object.keys(LIMITS_SET);
const LABEL: Record<string, string> = {
  per_trade_risk_pct: "Risk per trade", max_open_risk_pct: "Total open risk", max_position_pct: "Position exposure",
  max_sector_pct: "Sector exposure", daily_loss_pct: "Daily loss halt", weekly_loss_pct: "Weekly loss halt",
  max_drawdown_pct: "Drawdown halt", min_reward_risk: "Minimum reward:risk",
};
const EQUITY = 1_000_000;
const OPEN_RISK = 24_600;
const SECTORS = { "Financial Services": 220_000, IT: 90_000 };
const DAY_PNL = -5_000;
const WEEK_PNL = -12_000;
const DRAWDOWN = 1.96;
const LIVE = {
  equity: { equity_rs: EQUITY, cash_rs: 590_000, net_unrealised_rs: -2_000, unknown_reasons: [], marks_as_of: "2026-10-24", fno_marks_as_of: null },
  peak: { peak_rs: 1_020_000 }, drawdown_pct: DRAWDOWN,
  day: { start: "2026-10-26T18:30:00+00:00", pnl_rs: DAY_PNL, start_equity_rs: EQUITY, unknown_reasons: [] },
  week: { start: "2026-10-25T18:30:00+00:00", pnl_rs: WEEK_PNL, start_equity_rs: EQUITY, unknown_reasons: [] },
  // risk_rs = reserved at entry (20,000 on 3 positions) + the estimate on 1 position opened before the profile (4,600).
  open: { positions: 4, reserved_positions: 3, legacy_positions: 1, risk_rs: OPEN_RISK, reserved_risk_rs: 20_000, legacy_risk_rs: 4_600, exposure_rs: 410_000, sector_rs: SECTORS },
  budgets_rs: { per_trade: 5_000, open_risk: 30_000, position: 100_000, sector: 250_000 },
  error: null,
};
const profileBody = (o: { limits?: Record<string, number>; version?: number; live?: unknown; changes?: unknown[] } = {}) => ({
  profile: {
    profile: "owner-default-2026-10-27", limits: o.limits ?? LIMITS_SET, version: o.version ?? 1, limits_version: `rp-${o.version ?? 1}-fixture`,
    capital_basis: "paper_equity", capital_basis_text: "paper equity (cash plus open positions at their marks)",
    starting_capital_rs: EQUITY, starting_capital_label: "SIMULATION DEFAULT", effective_from: null, set_by: null, set_at: null, reason: null, stored: false,
  },
  live: o.live ?? LIVE,
  changes: o.changes ?? [],
  can_loosen: false,
  catalogue: {
    fields: FIELDS,
    definitions: Object.fromEntries(FIELDS.map((f) => [f, { label: LABEL[f], basis: "MOCK basis", reset: null, breach: null }])),
    ranges: { per_trade_risk_pct: [0.1, 2], max_open_risk_pct: [0.5, 10], max_position_pct: [1, 25], max_sector_pct: [5, 50], daily_loss_pct: [0.5, 5], weekly_loss_pct: [1, 10], max_drawdown_pct: [2, 25], min_reward_risk: [1, 5] },
    named_profiles: {},
  },
  estimate: { gap_stress_pct: 1, gap_stress_text: "a 1% gap stress", version: "est-risk-v1", cost_model: "desk-cost-v2" },
  risk_policy_version: "universal-risk-v1",
  fno_additional_checks: { flag: "fno_risk_gate", enabled: false },
});

const MARKET = (o: Record<string, unknown> = {}) => ({
  source: "macro_daily", as_of: "2026-10-23", age_sessions: 2, budget: 2, ok: true, reason: null, version: "fresh-v1", status: "ok",
  regime: "BEAR", vix: 14.2, key: "nifty", ...o,
});
/** GET /api/risk/freshness: TATASTEEL's last close is stale, any other share is fresh; no symbol = not checked. */
function freshBody(symbol: string | null, market: Record<string, unknown> = {}) {
  const skipped = { status: "not_checked", ok: null, reason: "give ?symbol= to check a share's inputs" };
  const stale = symbol === "TATASTEEL";
  return {
    symbol,
    inputs: {
      market_state: MARKET(market),
      last_close: symbol
        ? { source: "bhavcopy", as_of: stale ? "2026-10-20" : "2026-10-24", age_sessions: stale ? 4 : 1, budget: 2, ok: !stale, version: "fresh-v1",
          reason: stale ? "as of 2026-10-20, 4 sessions before 2026-10-27; the budget is 2" : null, status: stale ? "stale" : "ok", value: stale ? 151.2 : 1642.5 }
        : skipped,
      sector: symbol ? { source: "index_constituents", as_of: null, age_sessions: null, budget: null, ok: true, reason: null, version: "fresh-v1", status: "ok", value: stale ? "Metals" : "Information Technology" } : skipped,
    },
    all_ok: !stale, reference_session: "2026-10-27", as_of: "2026-10-27T06:00:00+00:00",
    budgets: { last_close: 2, market_state: 2, sector: null }, calendar: "MOCK", freshness_version: "fresh-v1", risk_policy_version: "universal-risk-v1",
    rule: "a new paper entry is blocked when any of its inputs is not ok (risk service check 'inputs')",
  };
}

const SCOPE = "blocks new positions on the AI-trader ticket, desk paper-trade and journal paths";
const NOT_IN_SCOPE = "no order is placed anywhere in this system, and open positions are untouched";
type Status = Record<string, unknown>;
const status = (o: Status = {}): Status => ({
  user_id: "u_fixture", kill_switch: false, halted: false, reason: null, set_by: null, set_at: null, policy_version: "risk-controls-v1",
  stored: false, scope: SCOPE, not_in_scope: NOT_IN_SCOPE, can_reset: false,
  live_authorization: { granted: false, granted_by: null, granted_at: null, reason: null },
  modes: ["paper", "shadow", "assisted", "live"], live_execution_available: false, gate: { enabled: false, policy_version: "fno-risk-v1" }, ...o,
});

/** GET /api/risk/decisions (decision_rows: `event_id`, no snapshot), sent OLDEST first so the newest-first order is checked. */
const BUDGET_HDFC = {
  per_trade_pct: 0.5, per_trade_budget_rs: 5000, open_risk_before_rs: 19600, open_risk_cap_rs: 30000, open_risk_pct_limit: 3, open_risk_after_rs: 24592.7,
  exposure_before_rs: 300000, exposure_cap_rs: 800000, position_cap_rs: 100000, position_pct_limit: 10, sector: "Financial Services",
  sector_before_rs: 120000, sector_cap_rs: 250000, sector_pct_limit: 25, open_positions_before: 3, max_open_positions: 10, reward_risk: 1.82,
  day_pnl_rs: -5000, day_start_equity_rs: EQUITY, day_loss_pct: 0.5, day_loss_pct_limit: 2, week_pnl_rs: -12000, week_start_equity_rs: EQUITY,
  week_loss_pct: 1.2, week_loss_pct_limit: 4, drawdown_pct: 1.96, drawdown_pct_limit: 10, peak_rs: 1020000, funding_rs: 101835, available_rs: 600000,
};
const row = (o: Record<string, unknown>) => ({
  user_id: "u_fixture", action: "desk_paper_trade", path: "desk_paper_trade", mode: "paper", requested_lots: null, approved_lots: null, checks: [],
  freshness: null, policy_version: "universal-risk-v1", limits_version: "rp-1-fixture", estimate_version: "est-risk-v1", inputs_hash: "h-fixture",
  actor_id: "u_fixture", source: "risk_service", trade_id: null, store: "desk_paper_trades", reservation_id: null, snapshot_version: "decision-snapshot-v1",
  detail: { instrument: "cash", action: "open", legs: 0, sector: null, fno_additional: false }, ...o,
});
const DECISIONS = {
  count: 3, append_only: true, policy_version: "risk-controls-v1",
  decisions: [
    row({ event_id: "dec-0001", at: "2026-10-27T03:50:00+00:00", outcome: "allowed", symbol: "INFY", requested_qty: 30, approved_qty: 30, correlation_id: "corr-0001",
      reasons: [], estimated_risk_rs: { gross: 1500, costs: 80, gap_stress: 140, total: 1720, stop_based: 1580 }, budget: { per_trade_pct: 0.5, per_trade_budget_rs: 5000 } }),
    row({ event_id: "dec-0002", at: "2026-10-27T05:00:00+00:00", outcome: "reduced", symbol: "HDFCBANK", requested_qty: 80, approved_qty: 62, correlation_id: "corr-0002",
      reasons: [{ code: "per_trade_risk_exceeded", check: "per_trade_risk", severity: "reduce", value: 6440.1, limit: 5000, message: "Estimated risk Rs 6,440.10 exceeds the per-trade budget Rs 5,000.00; at most 62 shares fit." }],
      estimated_risk_rs: { gross: 4495, costs: 190.2, gap_stress: 307.5, total: 4992.7, stop_based: 4685.2 }, budget: BUDGET_HDFC,
      detail: { instrument: "cash", action: "open", legs: 0, sector: "Financial Services", fno_additional: false } }),
    row({ event_id: "dec-0003", at: "2026-10-27T05:12:00+00:00", outcome: "blocked", symbol: "TATASTEEL", requested_qty: 300, approved_qty: 0, correlation_id: "corr-0003",
      reasons: [{ code: "inputs_stale", check: "inputs", severity: "block", value: null, limit: null, message: "The last close is stale: as of 2026-10-20, 4 sessions before 2026-10-27; the budget is 2." }],
      estimated_risk_rs: null, budget: { per_trade_pct: 0.5, per_trade_budget_rs: 5000 } }),
  ],
};
const ORDER = ["TATASTEEL", "HDFCBANK", "INFY"];

const AUDIT_EVENTS = [
  { _id: "a-1", at: "2026-10-22T06:00:00+00:00", actor: "u_fixture", action: "set_halted", field: "halted", before: false, after: true, reason: "Results week", policy_version: "risk-controls-v1" },
  { _id: "a-2", at: "2026-10-23T06:00:00+00:00", actor: "admin_fixture", action: "set_halted", field: "halted", before: true, after: false, reason: "Reviewed", policy_version: "risk-controls-v1" },
];

const COND = (id: string, label: string, evidence: string, backlog: string) => ({ id, label, status: "fail", evidence, backlog });
const READINESS = {
  conditions: [
    COND("order_adapter", "A broker order adapter exists", "The broker adapters are read-only by construction", "P3.2"),
    COND("certification", "The strategy is certified", "No certification records", "P3.1"),
    COND("kill_switch", "The kill switch can flatten", "The kill switch blocks new entries only", "P3.3"),
  ],
  count: 3, live_execution_available: false, policy_version: "fno-risk-v1", read_at: "2026-10-27T06:00:00+00:00", readiness_version: "live-readiness-v1",
};

const step = (s: string, label: string, st: string, detail: string) => ({ step: s, label, status: st, detail, ref: null, backlog: null });
const LINEAGE = (id: string) => ({
  decision_id: id, replayable: true,
  steps: [step("signal", "Signal", "not_applicable", "A manual paper trade."), step("risk_decision", "Risk decision", "recorded", "reduced under universal-risk-v1."),
    step("audit_record", "Audit record", "recorded", `risk_decisions/${id}`)],
});
const REPLAY = {
  decision_id: "dec-0002", replayable: true, match: true, outcome_then: "reduced", outcome_now: "reduced", reasons_then: ["per_trade_risk_exceeded"],
  reasons_now: ["per_trade_risk_exceeded"], checks_then: [], checks_now: [], capital_at_risk_then: null, capital_at_risk_now: null, inputs_hash_match: true,
  snapshot_hash_match: true, policy_version_then: "universal-risk-v1", policy_version_now: "universal-risk-v1", differences: [], replayed_on: "2026-10-27T06:00:00+00:00",
};

const JOBS: Record<string, unknown> = {
  check_desk_alerts: { job: "check_desk_alerts", state: "ok", healthy: true, reason: null, schedule: "Mon–Fri 20:45 IST, retry 22:45 IST", expected_since: "2026-10-26T17:15:00+00:00",
    grace_minutes: 60, last_success_at: "2026-10-26T15:17:00+00:00", age_hours: 14.7, last_run: { status: "ok", session: "2026-10-26", started_at: "2026-10-26T15:17:00+00:00" }, last_success: { status: "ok" } },
  positional_engine: { job: "positional_engine", state: "missed", healthy: false, reason: "No run recorded since the Mon 26 Oct 21:45 IST slot.", schedule: "Mon–Fri 19:45 IST, retry 21:45 IST",
    expected_since: "2026-10-26T16:15:00+00:00", grace_minutes: 60, last_success_at: "2026-10-23T14:16:00+00:00", age_hours: 88, last_run: null, last_success: null },
};

// ── the routes ───────────────────────────────────────────────────────────

interface Calls { puts: Array<{ path: string; body: Record<string, unknown> }>; freshness: string[]; replays: string[]; jobs: string[] }
interface Opts {
  status?: Status; profile?: unknown; decisions?: unknown; decisionsReply?: { status: number; body: unknown }; audit?: unknown[];
  market?: Record<string, unknown>; admin?: boolean;
}

async function riskDesk(page: Page, o: Opts = {}): Promise<Calls> {
  const calls: Calls = { puts: [], freshness: [], replays: [], jobs: [] };
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (r) => reply(r, []));
  await page.route("**/api/move-odds/**", (r) => reply(r, { detail: "feature_not_enabled" }, 403));
  if (o.admin === false) {
    const me = { ...load("user-profile-onboarded.json"), is_admin: false };
    await page.route("**/api/auth/me", (r) => reply(r, me));
  }
  let st = o.status ?? status();
  let events = [...(o.audit ?? AUDIT_EVENTS)];
  let prof: Record<string, unknown> = (o.profile as Record<string, unknown>) ?? profileBody();
  await page.route("**/api/risk/status", (r) => reply(r, st));
  const put = (field: "kill_switch" | "halted") => (r: Route) => {
    const body = r.request().postDataJSON() as { enabled: boolean; reason: string };
    calls.puts.push({ path: new URL(r.request().url()).pathname, body });
    events = [...events, { _id: `a-${events.length + 1}`, at: "2026-10-27T06:30:00+00:00", actor: "u_fixture", action: `set_${field}`, field, before: Boolean(st[field]), after: body.enabled, reason: body.reason, policy_version: "risk-controls-v1" }];
    st = { ...st, [field]: body.enabled, reason: body.reason, set_by: "u_fixture", set_at: "2026-10-27T06:30:00+00:00", stored: true };
    return reply(r, st);
  };
  await page.route("**/api/risk/kill-switch", put("kill_switch"));
  await page.route("**/api/risk/halt", put("halted"));
  await page.route("**/api/risk/audit*", (r) => reply(r, { events, count: events.length, append_only: true, policy_version: "risk-controls-v1" }));
  await page.route("**/api/risk/policy", (r) => reply(r, { policy_version: "fno-risk-v1", limits: { max_legs: 4, max_lots_per_leg: 10, max_open_structures: 10, max_capital_at_risk_rs: 200000, require_defined_risk: true }, usage: { open_structures: 0, capital_at_risk_rs: 0 } }));
  await page.route("**/api/risk/profile", (r) => {
    if (r.request().method() === "PUT") {
      const body = r.request().postDataJSON() as { changes: Record<string, number>; reason: string };
      calls.puts.push({ path: "/api/risk/profile", body });
      const [field, after] = Object.entries(body.changes)[0];
      const before = (LIMITS_SET as Record<string, number>)[field];
      prof = profileBody({ limits: { ...LIMITS_SET, [field]: after }, version: 2,
        changes: [{ at: "2026-10-27T06:40:00+00:00", actor: "u_fixture", actor_is_admin: false, action: "set_limits", changes: { [field]: { before, after } }, loosened: [], reason: body.reason, version_after: 2, effective_from: "2026-10-27T06:40:00+00:00" }] });
      return reply(r, prof);
    }
    return reply(r, prof);
  });
  await page.route("**/api/risk/freshness*", (r) => {
    const sym = new URL(r.request().url()).searchParams.get("symbol");
    calls.freshness.push(sym ?? "");
    return reply(r, freshBody(sym, o.market));
  });
  await page.route("**/api/risk/live-readiness", (r) => reply(r, READINESS));
  await page.route("**/api/risk/decisions*", (r) => (o.decisionsReply ? reply(r, o.decisionsReply.body, o.decisionsReply.status) : reply(r, o.decisions ?? DECISIONS)));
  await page.route("**/api/risk/decisions/*/lineage", (r) => reply(r, LINEAGE(new URL(r.request().url()).pathname.split("/")[4])));
  await page.route("**/api/risk/decisions/*/replay", (r) => {
    calls.replays.push(new URL(r.request().url()).pathname);
    return reply(r, REPLAY);
  });
  await page.route("**/api/admin/risk/jobs/*", (r) => {
    const job = new URL(r.request().url()).pathname.split("/").pop() as string;
    calls.jobs.push(job);
    return reply(r, JOBS[job] ?? { detail: "unknown_job" }, JOBS[job] ? 200 : 404);
  });
  return calls;
}

function recordWrites(page: Page): string[] {
  const writes: string[] = [];
  page.on("request", (req) => {
    const p = new URL(req.url()).pathname;
    if (req.method() !== "GET" && /\/api\//.test(p) && !p.startsWith("/api/copilot/widgets/")) writes.push(`${req.method()} ${p}`);
  });
  return writes;
}

async function noSideScroll(page: Page, where: string) {
  const o = await page.evaluate(() => {
    const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
    return { doc: document.documentElement.scrollWidth - window.innerWidth, scroll: sc ? sc.scrollWidth - sc.clientWidth : 0 };
  });
  expect(o.doc, where).toBeLessThanOrEqual(1);
  expect(o.scroll, where).toBeLessThanOrEqual(1);
}

// ── the tests ────────────────────────────────────────────────────────────

test.describe("MOCK — not real data: Smart trading desk · 04 Risk Desk", () => {
  test("RD-1 / RD-17 three views from the switcher and the URL, one h1 each, paper-only wording, no Policy & runtime", async ({ page }) => {
    await riskDesk(page);
    await page.goto(LIMITS);
    const panel = page.getByTestId("desk-panel-risk");
    for (const [key, label] of [["controls", "Controls & profile"], ["log", "Decision log"], ["limits", "Limits & budgets"]]) {
      await page.getByTestId(`desk-view-${key}`).click();
      await expect(panel.getByTestId("risk-desk")).toHaveAttribute("data-view", key);
      await expect(page).toHaveURL(new RegExp(`[?&]view=${key}(&|$)`));
      await expect(panel.locator("h1")).toHaveCount(1);
      await expect(panel.getByTestId("rd-title")).toBeVisible();
      await expect(panel).toContainText(`Risk Desk · ${label}`);
      await expect(panel.getByTestId("rd-paper-only")).toHaveText("Paper risk only: these limits and controls govern paper entries. Nothing is sent to a broker.");
      await expect(panel.getByTestId("rd-paper-pill")).toHaveText("Paper only");
    }
    await expect(page.getByTestId("desk-view-limits")).toHaveText("Limits & budgets");
    await expect(page.getByText("Policy & runtime")).toHaveCount(0);
    await expect(page.getByText(/strategy variant|runtime control|autonomous agent/i)).toHaveCount(0);
  });

  test("RD-2 / RD-3 / RD-4 the eight limits with used and left, open risk reserved, positions n of 10, the KPI strip and the headline", async ({ page }) => {
    await riskDesk(page);
    await page.goto(LIMITS);
    const rows = page.getByTestId("rd-limits").locator("li");
    await expect(rows).toHaveCount(8, SLOW);
    for (const f of FIELDS) await expect(page.getByTestId(`rd-limit-${f}-label`)).toHaveText(LABEL[f]);
    const value = (f: string) => page.getByTestId(`rd-limit-${f}-value`);
    await expect(value("per_trade_risk_pct")).toHaveText("limit 0.5%");
    await expect(value("max_open_risk_pct")).toHaveText("limit 3%");
    await expect(value("max_position_pct")).toHaveText("limit 10%");
    await expect(value("max_sector_pct")).toHaveText("limit 25%");
    await expect(value("daily_loss_pct")).toHaveText("limit 2%");
    await expect(value("weekly_loss_pct")).toHaveText("limit 4%");
    await expect(value("max_drawdown_pct")).toHaveText("limit 10%");
    await expect(value("min_reward_risk")).toHaveText("limit 1.5 : 1");

    // Used and left, worked out from LIVE: open risk 24,600 / 10,00,000 = 2.46% (cap 30,000 → 5,400 left).
    const used = (f: string) => page.getByTestId(`rd-limit-${f}-used`);
    const left = (f: string) => page.getByTestId(`rd-limit-${f}-left`);
    const openPct = (OPEN_RISK / EQUITY) * 100;
    await expect(used("max_open_risk_pct")).toHaveText(`used ${p2(openPct)} · ${inr(OPEN_RISK)}`);
    await expect(left("max_open_risk_pct")).toHaveText(`${p2(3 - openPct)} left · ${inr(30_000 - OPEN_RISK)}`);
    // The largest sector: Financial Services 2,20,000 = 22% of 25% (cap 2,50,000).
    await expect(used("max_sector_pct")).toHaveText(`used ${p2(22)} · ${inr(220_000)} (Financial Services, the largest sector)`);
    await expect(left("max_sector_pct")).toHaveText(`${p2(3)} left · ${inr(30_000)}`);
    // The day's and the week's loss ÷ the period's starting equity.
    await expect(used("daily_loss_pct")).toHaveText(`used ${p2(0.5)} · ${inr(5_000)} (of the day's starting equity)`);
    await expect(left("daily_loss_pct")).toHaveText(`${p2(1.5)} left`);
    await expect(used("weekly_loss_pct")).toHaveText(`used ${p2(1.2)} · ${inr(12_000)} (of the week's starting equity)`);
    await expect(left("weekly_loss_pct")).toHaveText(`${p2(2.8)} left`);
    await expect(used("max_drawdown_pct")).toHaveText(`used ${p2(DRAWDOWN)} (below the peak)`);
    await expect(left("max_drawdown_pct")).toHaveText(`${p2(10 - DRAWDOWN)} left`);
    // Per-entry limits: their rule or rupee budget, no running use and no bar.
    await expect(used("per_trade_risk_pct")).toHaveText("judged per entry");
    await expect(left("per_trade_risk_pct")).toHaveText(`${inr(5_000)} risk per trade`);
    await expect(left("max_position_pct")).toHaveText(`${inr(100_000)} per position`);
    await expect(left("min_reward_risk")).toHaveText("each entry needs 1.5 : 1 after costs");
    await expect(page.getByTestId("rd-limit-min_reward_risk").getByRole("img")).toHaveCount(0);

    await expect(page.getByTestId("rd-reserved")).toHaveText(`Open risk reserved ${inr(20_000)} of ${inr(30_000)} (3%)`);
    await expect(page.getByTestId("rd-reserved-legacy")).toHaveText(
      `Plus ${inr(4_600)} estimated on positions opened before the risk profile (not reserved). The open-risk limit counts both: ${inr(OPEN_RISK)}.`);
    await expect(page.getByTestId("rd-positions")).toHaveText("Open positions 4 of 10 (fixed limit, not in your profile)");

    await expect(page.getByTestId("rd-kpi-open-value")).toHaveText(`${openPct.toFixed(1)}%`);
    await expect(page.getByTestId("rd-kpi-day-value")).toHaveText("0.5%");
    await expect(page.getByTestId("rd-kpi-drawdown-value")).toHaveText(`${DRAWDOWN.toFixed(1)}%`);
    await expect(page.getByTestId("rd-kpi-positions-value")).toHaveText("4 / 10");
    await expect(page.getByTestId("rd-kpi-entries-value")).toHaveText("Allowed");
    await expect(page.getByTestId("rd-title")).toHaveText(`Open risk is ${openPct.toFixed(1)}% of paper equity, inside every limit, and new entries are allowed.`);
    await expect(page.getByTestId("rd-limits-version")).toHaveText("owner-default-2026-10-27 · version 1 · rp-1-fixture");
  });

  test("RD-5 the regime factor: BEAR halves the size limits; BEAR with VIX ≥ 25 is ×0.25; BULL has no cut; unknown says the rule is skipped", async ({ page }) => {
    await riskDesk(page);
    await page.goto(LIMITS);
    await expect(page.getByTestId("rd-regime-words")).toHaveText("BEAR regime (as of 23 Oct): size limits ×0.5.", SLOW);
    await expect(page.getByTestId("rd-regime")).toHaveAttribute("data-factor", "0.5");
  });

  for (const [name, market, words, factor] of [
    ["BEAR and VIX 27", { regime: "BEAR", vix: 27 }, "BEAR regime and India VIX 27, at or above 25 (as of 23 Oct): size limits ×0.25.", "0.25"],
    ["BULL", { regime: "BULL", vix: 14.2 }, "BULL regime, India VIX 14.2 (as of 23 Oct): no size cut.", "1"],
    ["VIX 36", { regime: "BULL", vix: 36 }, "India VIX 36 (as of 23 Oct) is at or above 35: new entries are deferred.", "deferred"],
    ["unknown", { regime: null, vix: null, ok: false, status: "unknown", reason: "no value could be read" },
      "Market regime and India VIX are unknown: the regime rule is skipped, and new entries are blocked while the market state is not fresh.", "1"],
  ] as const) {
    test(`RD-5 regime ${name}`, async ({ page }) => {
      await riskDesk(page, { market: market as Record<string, unknown> });
      await page.goto(LIMITS);
      await expect(page.getByTestId("rd-regime-words")).toHaveText(words, SLOW);
      await expect(page.getByTestId("rd-regime")).toHaveAttribute("data-factor", factor);
    });
  }

  test("RD-6 input freshness: market state, and last close and sector for the newest share decision (stale); a typed share re-reads", async ({ page }) => {
    const calls = await riskDesk(page);
    await page.goto(LIMITS);
    // The newest cash decision is TATASTEEL (blocked, 05:12 UTC): its inputs are checked.
    await expect(page.getByTestId("rd-fresh-last_close")).toHaveAttribute("data-status", "stale", SLOW);
    expect(calls.freshness).toContain("TATASTEEL");
    await expect(page.getByTestId("rd-fresh-market-status")).toHaveText("ok");
    await expect(page.getByTestId("rd-fresh-market-words")).toHaveText("as of 23 Oct · 2 sessions old (budget 2)");
    await expect(page.getByTestId("rd-fresh-last_close")).toContainText("Last close · TATASTEEL");
    await expect(page.getByTestId("rd-fresh-last_close-status")).toHaveText("stale");
    await expect(page.getByTestId("rd-fresh-last_close-words")).toHaveText("as of 20 Oct · 4 sessions old (budget 2) · as of 2026-10-20, 4 sessions before 2026-10-27; the budget is 2");
    await expect(page.getByTestId("rd-fresh-sector")).toContainText("Metals");
    await expect(page.getByTestId("rd-fresh-sector-status")).toHaveText("ok");
    await expect(page.getByTestId("rd-fresh-rule")).toContainText("A new paper entry is blocked when any of its inputs is not ok.");
    await expect(page.getByTestId("rd-fresh-rule")).toContainText("TATASTEEL is your newest share decision.");

    await page.getByTestId("rd-fresh-symbol").fill("infy");
    await page.getByTestId("rd-fresh-check").click();
    await expect(page.getByTestId("rd-fresh-last_close")).toHaveAttribute("data-status", "ok");
    expect(calls.freshness).toContain("INFY");
    await expect(page.getByTestId("rd-fresh-last_close")).toContainText("Last close · INFY");
    await expect(page.getByTestId("rd-fresh-last_close")).toContainText(inr(1642.5));
    await expect(page.getByTestId("rd-fresh-sector")).toContainText("Information Technology");
  });

  test("RD-7 the correlation note and the paper-only footnote; My portfolio opens from it", async ({ page }) => {
    await riskDesk(page);
    await page.goto(LIMITS);
    await expect(page.getByTestId("rd-correlation")).toHaveText("Correlation is not checked; sector exposure is the concentration control.");
    await expect(page.getByTestId("rd-footnote")).toHaveText("These limits govern paper trades only. Your real holdings' risk checks are in My portfolio. Real holdings are not counted here.");
    await page.getByTestId("rd-footnote-portfolio").click();
    await expect(page).toHaveURL(/[?&]tab=portfolio(&|$)/);
  });

  test("RD-8 unreadable live figures read unknown, never ₹0 or 0%", async ({ page }) => {
    await riskDesk(page, { profile: profileBody({ live: { error: "the account could not be read (TimeoutError)" } }) });
    await page.goto(LIMITS);
    await expect(page.getByTestId("rd-limit-max_open_risk_pct-used")).toHaveText("used unknown", SLOW);
    await expect(page.getByTestId("rd-limit-max_open_risk_pct-left")).toHaveText("unknown");
    await expect(page.getByTestId("rd-limit-max_open_risk_pct-why")).toHaveText("Unknown: the account could not be read (TimeoutError).");
    await expect(page.getByTestId("rd-limit-per_trade_risk_pct-left")).toHaveText("unknown (paper equity unknown)");
    await expect(page.getByTestId("rd-live-error")).toContainText("the account could not be read (TimeoutError)");
    await expect(page.getByTestId("rd-reserved")).toHaveText("Open risk reserved unknown of unknown (3%)");
    await expect(page.getByTestId("rd-positions")).toHaveText("Open positions unknown of 10 (fixed limit, not in your profile)");
    await expect(page.getByTestId("rd-kpi-open-value")).toHaveText("unknown");
    await expect(page.getByTestId("rd-title")).toHaveText("Open risk is unknown, some figures are unknown, and new entries are allowed.");
    await expect(page.getByTestId("rd-limits-card")).not.toContainText("₹0");
  });

  test("RD-9 kill switch: the rule, on with a reason, one PUT; then only an admin can switch it off; the change is in the audit list", async ({ page }) => {
    const writes = recordWrites(page);
    const calls = await riskDesk(page);
    await page.goto(CONTROLS);
    await expect(page.getByTestId("rd-control-rule")).toHaveText(
      "Anyone can switch the kill switch or the halt on, with a reason. Either one blocks new paper entries only: open positions are untouched and nothing is cancelled. Only an admin can switch them off.");
    await expect(page.getByTestId("rd-title")).toHaveText("Kill switch and halt are off; your risk profile sets every limit.");
    await expect(page.getByTestId("risk-audit-event")).toHaveCount(2);
    const kill = page.getByTestId("risk-kill");
    await kill.getByTestId("risk-kill-on").click();
    await kill.getByTestId("risk-kill-continue").click();
    await expect(kill.getByTestId("risk-kill-reason-error")).toBeVisible();
    expect(calls.puts).toHaveLength(0);
    await kill.getByTestId("risk-kill-reason").fill("Three losers in a row");
    await kill.getByTestId("risk-kill-continue").click();
    await kill.getByTestId("risk-kill-confirm-yes").click();
    await expect(kill.getByTestId("risk-kill-pill")).toHaveText("On");
    expect(calls.puts).toEqual([{ path: "/api/risk/kill-switch", body: { enabled: true, reason: "Three losers in a row" } }]);
    await expect(kill.getByTestId("risk-kill-admin-only")).toHaveText("Only an admin can turn the kill switch off.");
    await expect(page.getByTestId("rd-title")).toHaveText("The kill switch is on: new paper entries are blocked.");
    await expect(page.getByTestId("risk-audit-event")).toHaveCount(3);
    await expect(page.getByTestId("risk-audit-change").first()).toHaveText("Kill switch: off → on");
    await expect(page.getByTestId("risk-audit-reason").first()).toHaveText("“Three losers in a row”");
    // Limits & budgets now says entries are blocked.
    await page.getByTestId("desk-view-limits").click();
    await expect(page.getByTestId("rd-kpi-entries-value")).toHaveText("Blocked");
    expect(writes).toEqual(["PUT /api/risk/kill-switch"]);
  });

  test("RD-10 the profile form: the rule; no PUT without a reason; a tightening is sent as {changes, reason} and logged", async ({ page }) => {
    const calls = await riskDesk(page);
    await page.goto(CONTROLS);
    await expect(page.getByTestId("rd-profile-rule")).toHaveText(
      "A reason is required for every change. Tightening a limit applies now; loosening one needs an admin. Your profile is the only risk setting: there are no sliders.");
    const form = page.getByTestId("risk-profile-form");
    await form.getByTestId("risk-profile-field").selectOption("weekly_loss_pct");
    await form.getByTestId("risk-profile-value").fill("3");
    await expect(form.getByTestId("risk-profile-hint")).toContainText("Tighter than now.");
    await form.getByTestId("risk-profile-submit").click();
    await expect(form.getByTestId("risk-profile-form-error")).toHaveText("Give a reason: it is recorded in the change log.");
    expect(calls.puts).toHaveLength(0);
    await form.getByTestId("risk-profile-reason").fill("A bad week; tighter");
    await form.getByTestId("risk-profile-submit").click();
    await expect(form.getByTestId("risk-profile-saved")).toBeVisible();
    expect(calls.puts).toEqual([{ path: "/api/risk/profile", body: { changes: { weekly_loss_pct: 3 }, reason: "A bad week; tighter" } }]);
    await expect(page.getByTestId("risk-profile-change-field")).toHaveText("Weekly loss halt: 4% → 3%");
    await expect(page.getByTestId("risk-profile-admin-note")).toHaveText("Only an admin can loosen a limit; you can tighten any limit.");
    // The new limit is what Limits & budgets now measures against.
    await page.getByTestId("desk-view-limits").click();
    await expect(page.getByTestId("rd-limit-weekly_loss_pct-value")).toHaveText("limit 3%");
  });

  test("RD-11 Live trading: not available, with each readiness condition and its evidence", async ({ page }) => {
    await riskDesk(page);
    await page.goto(CONTROLS);
    await expect(page.getByTestId("rd-live-headline")).toHaveText("Live trading: not available.", SLOW);
    await expect(page.getByTestId("rd-live-count")).toHaveText("0 of 3 conditions pass");
    const rows = page.getByTestId("rd-live-row");
    await expect(rows).toHaveCount(3);
    await expect(rows.nth(0)).toContainText("A broker order adapter exists");
    await expect(rows.nth(0)).toContainText("The broker adapters are read-only by construction");
    await expect(page.locator('[data-testid="rd-live-row"][data-status="fail"]')).toHaveCount(3);
  });

  test("RD-12 no risk slider anywhere on the Risk Desk", async ({ page }) => {
    await riskDesk(page);
    for (const url of [LIMITS, CONTROLS, LOG]) {
      await page.goto(url);
      await expect(page.getByTestId("rd-title")).toBeVisible(SLOW);
      await expect(page.getByTestId("desk-panel-risk").locator('input[type="range"], [role="slider"]')).toHaveCount(0);
    }
  });

  test("RD-13 / RD-14 the log: allow / reduce / block newest first with estimate and versions; Budgets, lineage & replay opens one", async ({ page }) => {
    const writes = recordWrites(page);
    const calls = await riskDesk(page);
    await page.goto(LOG);
    const rows = page.getByTestId("risk-decision");
    await expect(rows).toHaveCount(3, SLOW);
    await expect(rows.getByTestId("risk-decision-symbol")).toHaveText(ORDER);
    await expect(rows.getByTestId("risk-decision-outcome")).toHaveText(["Blocked", "Reduced", "Allowed"]);
    await expect(page.getByTestId("rd-title")).toHaveText("Every risk decision is recorded: 1 allowed, 1 reduced and 1 blocked in the last 3.");
    const hdfc = rows.nth(1);
    await expect(hdfc.getByTestId("risk-decision-reasons")).toContainText("at most 62 shares fit.");
    await expect(hdfc.getByTestId("risk-decision-estimate")).toHaveText(`80 → 62 shares · Estimated risk ${inr(4992.7)} (stop ${inr(4495)} + costs ${inr(190.2)} + gap ${inr(307.5)})`);
    await expect(hdfc.getByTestId("risk-decision-versions")).toHaveText("policy universal-risk-v1 · limits rp-1-fixture · est-risk-v1");
    await expect(rows.nth(0).getByTestId("risk-decision-estimate")).toHaveText("300 → 0 shares · Estimate: not sized");
    await expect(rows.nth(2).getByTestId("risk-decision-estimate")).toHaveText(`30 shares · Estimated risk ${inr(1720)} (stop ${inr(1500)} + costs ${inr(80)} + gap ${inr(140)})`);

    await hdfc.getByTestId("risk-decision-open").click();
    await expect(hdfc.getByTestId("risk-decision-open")).toHaveAttribute("aria-expanded", "true");
    const b = hdfc.getByTestId("risk-decision-budgets");
    await expect(b).toContainText(`Per-trade budget${inr(5000)} (0.50% of equity)`);
    await expect(b).toContainText(`Open risk${inr(19600)} before → ${inr(24592.7)} after, of ${inr(30000)}`);
    await expect(b).toContainText(`SectorFinancial Services ${inr(120000)} of ${inr(250000)}`);
    await expect(b).toContainText("Open positions3 of 10");
    await expect(b).toContainText("Reward:risk1.82 after costs");
    await expect(b).toContainText("Day's loss0.50% of 2%");
    await expect(b).toContainText("Week's loss1.20% of 4%");
    await expect(b).toContainText("Drawdown1.96% of 10%");
    await expect(b).toContainText(`Paper cash${inr(101835)} needed, ${inr(600000)} available`);
    await expect(hdfc.getByTestId("fnolab-audit-node")).toHaveCount(3);
    await expect(hdfc.locator('[data-testid="fnolab-audit-node"][data-node="risk_decision"]')).toHaveAttribute("data-status", "recorded");
    await hdfc.getByTestId("fnolab-audit-replay-run").click();
    await expect(hdfc.getByTestId("fnolab-audit-replay-result")).toHaveAttribute("data-match", "true");
    expect(calls.replays).toEqual(["/api/risk/decisions/dec-0002/replay"]);
    await hdfc.getByTestId("risk-decision-open").click();
    await expect(hdfc.getByTestId("risk-decision-detail")).toHaveCount(0);
    expect(writes).toEqual(["POST /api/risk/decisions/dec-0002/replay"]);
  });

  test("RD-15 no decisions is said", async ({ page }) => {
    await riskDesk(page, { decisions: { decisions: [], count: 0 } });
    await page.goto(LOG);
    await expect(page.getByTestId("risk-decisions-empty")).toContainText("No risk decisions yet", SLOW);
    await expect(page.getByTestId("rd-title")).toHaveText("Every risk decision is recorded; none yet on this account.");
  });

  test("RD-15b a failing decisions read shows an error with Retry, nothing invented", async ({ page }) => {
    await riskDesk(page, { decisionsReply: { status: 500, body: { detail: "fixture failure" } } });
    await page.goto(LOG);
    await expect(page.getByTestId("risk-decisions-error").getByRole("alert")).toContainText("Risk decisions didn’t load", SLOW);
    await expect(page.getByTestId("risk-decisions-error").getByRole("button", { name: /Retry/ })).toBeVisible();
    await expect(page.getByTestId("risk-decision")).toHaveCount(0);
  });

  test("RD-16 an admin sees the job-health strip on every view", async ({ page }) => {
    const calls = await riskDesk(page);
    await page.goto(LIMITS);
    const strip = page.getByTestId("rd-jobs");
    await expect(strip).toBeVisible(SLOW);
    await expect(strip.getByTestId("rd-job-check_desk_alerts-state")).toHaveText("ok");
    await expect(strip.getByTestId("rd-job-check_desk_alerts-words")).toHaveText("Last success 26 Oct, 20:47 IST · Mon–Fri 20:45 IST, retry 22:45 IST");
    await expect(strip.getByTestId("rd-job-positional_engine-state")).toHaveText("missed");
    await expect(strip.getByTestId("rd-job-positional_engine-words")).toHaveText("No run recorded since the Mon 26 Oct 21:45 IST slot. · Last success 23 Oct, 19:46 IST · Mon–Fri 19:45 IST, retry 21:45 IST");
    expect([...new Set(calls.jobs)].sort()).toEqual(["check_desk_alerts", "positional_engine"]);
    for (const url of [CONTROLS, LOG]) {
      await page.goto(url);
      await expect(page.getByTestId("rd-jobs")).toBeVisible(SLOW);
    }
  });

  test("RD-16b a non-admin sees no job-health strip, and the admin routes are not called", async ({ page }) => {
    const c2 = await riskDesk(page, { admin: false });
    for (const url of [LIMITS, CONTROLS, LOG]) {
      await page.goto(url);
      await expect(page.getByTestId("rd-title")).toBeVisible(SLOW);
      await expect(page.getByTestId("rd-jobs")).toHaveCount(0);
    }
    expect(c2.jobs).toEqual([]);
  });

  test("RD-19 reading every view writes nothing", async ({ page }) => {
    const writes = recordWrites(page);
    await riskDesk(page);
    for (const url of [LIMITS, CONTROLS, LOG]) {
      await page.goto(url);
      await expect(page.getByTestId("rd-title")).toBeVisible(SLOW);
      await page.waitForTimeout(300);
    }
    expect(writes).toEqual([]);
  });
});

test.describe("MOCK — not real data: Risk Desk · phone 390px", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("RD-18 no sideways scroll on any view, with long reasons and an open decision", async ({ page }) => {
    const long = "A long reason that keeps going ".repeat(16);
    const d = DECISIONS.decisions;
    await riskDesk(page, {
      status: status({ kill_switch: true, reason: long, set_by: "admin_fixture", set_at: "2026-10-27T05:00:00+00:00", stored: true }),
      audit: [{ ...AUDIT_EVENTS[0], reason: long }],
      decisions: { ...DECISIONS, decisions: [d[0], { ...d[1], correlation_id: `corr-${"9f".repeat(60)}`, reasons: [{ code: "x", severity: "reduce", message: long }] }, d[2]] },
    });
    for (const url of [LIMITS, CONTROLS, LOG]) {
      await page.goto(url);
      await expect(page.getByTestId("rd-title")).toBeVisible(SLOW);
      await page.waitForTimeout(400);
      await noSideScroll(page, url);
    }
    await page.getByTestId("risk-decision").nth(1).getByTestId("risk-decision-open").click();
    await expect(page.getByTestId("risk-decision-budgets")).toBeVisible();
    await page.waitForTimeout(300);
    await noSideScroll(page, "log, decision open");
  });
});
