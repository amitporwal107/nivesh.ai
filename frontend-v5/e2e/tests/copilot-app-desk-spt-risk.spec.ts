/**
 * One-screen Copilot app (/v5/app) — Risk Desk › Scanner-to-Paper Trading views: Trading overview, Capital allocation,
 * Portfolio risk (owner, 5 Nov 2026; screens/tradingdesk/tabs/risk-desk/{TradingOverview,CapitalAllocation,PortfolioRisk}.tsx).
 * Cases: test_reports/spt_ui_risk_TESTCASES.md (SPT-UI-R-01 … SPT-UI-R-22).
 *
 * MOCK — not real data. Every /api answer below is written by hand in the shape the routes return on feat/spt-integration
 * (backend/routes/spt_risk.py, spt_accounts.py, spt_paper.py, spt_signals.py). Account ids, symbols, sectors, reasons and
 * numbers are INVENTED. Expected text is worked out here from the payloads, not copied from the screen. Production build,
 * every /api mocked — see pw.copilot-app.config.ts.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const DESK = "/v5/app/trader/desk";
const OVERVIEW = `${DESK}?tab=risk&view=overview`;
const ALLOCATION = `${DESK}?tab=risk&view=allocation`;
const PORTFOLIO = `${DESK}?tab=risk&view=portfolio`;
const SLOW = { timeout: 15_000 };

const reply = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
const inr = (n: number) => `${n < 0 ? "−" : ""}₹${new Intl.NumberFormat("en-IN").format(Math.round(Math.abs(n)))}`;

// ── the MOCK payloads (MOCK — not real data) ─────────────────────────────

// MOCK — not real data: the SPT account id is deliberately NOT the signed-in user's fixture id, so the spec proves the
// screens take it from GET /api/v1/paper/accounts.
const ACC = "u_spt_fixture";
const LADDER = { reduce_at_pct: 2, restrict_at_pct: 4, halt_at_pct: 6, reduce_factor: 0.5 };
const BUCKETS_PCT = { equity_positional: 45, equity_intraday: 25, fno: 20, reserve: 10 };

// MOCK — not real data
const accountsBody = (mode = "approval") => ({
  accounts: [{
    account_id: ACC, account: { cash_rs: 700_000 }, modes: ["off", "tracking", "approval", "auto"],
    config: { user_id: ACC, account_id: ACC, mode, version: 3, stored: true, extras: { drawdown_ladder: LADDER, allocation_buckets_pct: BUCKETS_PCT, stressed_gap_pct: 1 } },
    note: "MOCK note",
  }],
  count: 1,
});

const EQUITY = 1_012_500;
const LADDER_TEXT = "MOCK: Drawdown 2.50% is in the reduce band (2%–4%): new trade risk is multiplied by 0.5.";
const KS_TEXT = "MOCK: Armed — nothing is breached.";
// MOCK — not real data: GET /api/v1/risk/account/{id}
const riskAccount = (o: Record<string, unknown> = {}) => ({
  account_id: ACC, as_of: "2026-11-05T04:00:00+00:00", error: null,
  equity_rs: EQUITY, equity_basis: "MOCK basis: paper cash plus positions at their marks", equity_unknown_reasons: [],
  cash_rs: 700_000, available_rs: 640_000, blocked_rs: 360_000, deployed_rs: 300_000, reserved_rs: 60_000,
  pending_entries: [{ order_id: "ord-p1", symbol: "AXISBANK", reserved_rs: 60_000, order_state: "PENDING" }],
  reserve_bucket_rs: 101_250,
  open_risk: { rs: 18_400, basis: "MOCK open-risk basis", cap_rs: 30_375, limit_pct: 3, used_pct_of_equity: 1.8173 },
  spt_risk: { planned_rs: 12_340.5, stressed_rs: 15_890.25, entries: 3, unpriced: [], stressed_gap_pct: 1, basis: "MOCK SPT basis" },
  daily_loss: { pnl_rs: -4_200, start_equity_rs: 1_016_700, loss_pct: 0.4131, limit_pct: 2, breached: false },
  weekly_loss: { pnl_rs: 6_100, start_equity_rs: 1_006_400, loss_pct: 0, limit_pct: 4, breached: false },
  drawdown: { pct: 2.5, peak_rs: 1_038_461.54, profile_halt_pct: 10,
    ladder: { band: "reduce", drawdown_pct: 2.5, factor: 0.5, blocks_new_entries: false, thresholds: LADDER, text: LADDER_TEXT } },
  kill_switch: { state: "ACTIVE", entries_blocked: false, blocking: false, kill_switch: false, halted: false, code: null, reason: null, reasons: [], text: KS_TEXT, mode: "approval" },
  limits: { profile: { per_trade_risk_pct: 0.5, max_open_risk_pct: 3, max_position_pct: 10, max_sector_pct: 25, daily_loss_pct: 2, weekly_loss_pct: 4, max_drawdown_pct: 10, min_reward_risk: 1.5 },
    limits_version: "rp-1-fixture", spt: { allocation_buckets_pct: BUCKETS_PCT, drawdown_ladder: LADDER, stressed_gap_pct: 1 }, spt_config_version: 3 },
  utilisation: { positions: { open: 4, max: 10 }, new_today: { count: 1, max: 5 },
    buckets: { equity_positional: { used_rs: 360_000, cap_rs: 455_625 }, equity_intraday: { used_rs: 0, cap_rs: 253_125 }, fno: { used_rs: 0, cap_rs: 202_500 } },
    exposure_rs: 410_000, exposure_pct_of_equity: 40.4938 },
  mode: "approval",
  ...o,
});

// MOCK — not real data: GET /api/v1/risk/exposures/{id}
const EXPOSURES = {
  account_id: ACC, as_of: "2026-11-05T04:00:00+00:00", equity_rs: EQUITY,
  by_sector: [
    { sector: "Financial Services", exposure_rs: 220_000, pct_of_equity: 21.7284, limit_pct: 25 },
    { sector: "Information Technology", exposure_rs: 150_000, pct_of_equity: 14.8148, limit_pct: 25 },
  ],
  unclassified_exposure_rs: 40_000,
  by_instrument: [
    { symbol: "HDFCBANK", exposure_rs: 198_000, pct_of_equity: 19.5556, limit_pct: 10 },
    { symbol: "TCS", exposure_rs: 150_000, pct_of_equity: 14.8148, limit_pct: 10 },
    { symbol: "AXISBANK", exposure_rs: 60_000, pct_of_equity: 5.9259, limit_pct: 10 },
  ],
  by_category: [
    { category: "equity_positional", used_rs: 360_000, cap_rs: 455_625, bucket_pct: 45 },
    { category: "equity_intraday", used_rs: 0, cap_rs: 253_125, bucket_pct: 25 },
    { category: "fno", used_rs: 0, cap_rs: 202_500, bucket_pct: 20 },
  ],
  total_exposure_rs: 410_000, basis: "MOCK exposure basis",
};

// MOCK — not real data: GET /api/v1/risk/stress-test/{id}
const STRESS = {
  account_id: ACC, as_of: "2026-11-05T04:00:00+00:00", equity_rs: EQUITY, version: "spt-stress-v1",
  positions: [
    { order_id: "ord-1", symbol: "HDFCBANK", sector: "Financial Services", quantity: 120, entry: 1650, stop: 1600, source: "MOCK", planned_rs: 6_180.5, stressed_rs: 8_100.5, value_rs: 198_000 },
    { order_id: "ord-2", symbol: "TCS", sector: "Information Technology", quantity: 40, entry: 3750, stop: 3650, source: "MOCK", planned_rs: 4_160, stressed_rs: 5_620, value_rs: 150_000 },
    { order_id: "ord-3", symbol: "INFY", sector: "Information Technology", quantity: 10, entry: 1500, stop: 1300, source: "MOCK", planned_rs: 2_000, stressed_rs: 2_169.75, value_rs: 15_000 },
  ],
  unpriced: [],
  totals: { planned_rs: 12_340.5, stressed_rs: 15_890.25, value_rs: 363_000 },
  scenarios: [
    { name: "gap_through_stop", gap_pct: 1, planned_rs: 12_340.5, stressed_rs: 15_890.25, text: "MOCK gap text" },
    { name: "sector_shock", shock_pct: -5, by_sector_rs: { "Financial Services": 9_900, "Information Technology": 8_250 }, worst_sector: "Financial Services", worst_loss_rs: 9_900, text: "MOCK sector text" },
    { name: "market_shock", results: [{ shock_pct: -3, beta: 1, beta_assumed: true, loss_rs: 10_890 }, { shock_pct: -5, beta: 1, beta_assumed: true, loss_rs: 18_150 }], text: "MOCK market text." },
  ],
  basis: "MOCK stress basis",
};

const BUCKET_MSG = "MOCK: the equity_positional bucket is nearly full: at most 120 shares fit.";
const OPEN_RISK_MSG = "MOCK: No whole share fits: the open-risk limit is reached.";
const RR_MSG = "MOCK: Reward:risk at the reference price is 1.40; the minimum is 2.";
// MOCK — not real data: GET /api/v1/allocation/recommendations/{id}
const RANKED = {
  account_id: ACC, as_of: "2026-11-05T04:00:00+00:00", mode: "approval", writes: "none", price_source: "MOCK quotes",
  rank_basis: "opportunity_score, then reward:risk at the entry, then average daily traded value",
  items: [
    { rank: 1, opportunity_id: "opp-1", symbol: "LT", opportunity_score: 82.5, rr: { t1: 1.2, t2: 2.6, min_rr: 2 }, entry: { price: 3600 }, stop_loss: 3480, outcome: "ok",
      reason_codes: [], explanations: [], proposal: { proposal_id: "prop-1", state: "AWAITING_USER_APPROVAL" },
      sizing: { quantity: 40, capital_required: 144_000, planned_risk: 5_000, stressed_risk: 6_400, blocked: [] },
      allocation: { decision: "ALLOCATION_APPROVED", requested_qty: 40, quantity: 40, reasons: [], capital_rs: 144_000, stressed_risk_rs: 6_400 } },
    { rank: 2, opportunity_id: "opp-2", symbol: "SBIN", opportunity_score: 77.1, rr: { t1: 1.1, t2: 2.2, min_rr: 2 }, entry: { price: 800 }, stop_loss: 775, outcome: "ok",
      reason_codes: [], explanations: [], proposal: { proposal_id: "prop-2", state: "AWAITING_USER_APPROVAL" },
      sizing: { quantity: 200, capital_required: 160_000, planned_risk: 4_900, stressed_risk: 6_500, blocked: [] },
      allocation: { decision: "ALLOCATION_REDUCED", requested_qty: 200, quantity: 120, reasons: [{ code: "bucket_reduced", message: BUCKET_MSG }], capital_rs: 96_000, stressed_risk_rs: 3_900 } },
    { rank: 3, opportunity_id: "opp-3", symbol: "ITC", opportunity_score: 70, rr: { t1: 1.0, t2: 2.1, min_rr: 2 }, entry: { price: 420 }, stop_loss: 405, outcome: "ok",
      reason_codes: [], explanations: [], proposal: null,
      sizing: { quantity: 300, capital_required: 126_000, planned_risk: 4_700, stressed_risk: 5_960, blocked: [] },
      allocation: { decision: "ALLOCATION_REJECTED", requested_qty: 300, quantity: 0, reasons: [{ code: "open_risk_full", message: OPEN_RISK_MSG }] } },
    { rank: 4, opportunity_id: "opp-4", symbol: "TATAMOTORS", opportunity_score: 65, rr: { t1: 0.7, t2: 1.4, min_rr: 2 }, entry: { price: 700 }, stop_loss: 680, outcome: "rejected",
      reason_codes: ["rr_below_minimum"], explanations: [RR_MSG], proposal: null, sizing: null, allocation: null },
  ],
};

// MOCK — not real data: GET /api/v1/proposals?state=AWAITING_USER_APPROVAL
const AWAITING = {
  items: [
    { proposal_id: "prop-1", symbol: "LT", state: "AWAITING_USER_APPROVAL", sizing: { quantity: 40 }, allocation: { decision: "ALLOCATION_APPROVED", quantity: 40 } },
    { proposal_id: "prop-2", symbol: "SBIN", state: "AWAITING_USER_APPROVAL", sizing: { quantity: 200 }, allocation: { decision: "ALLOCATION_REDUCED", quantity: 120 } },
  ],
  count: 2,
};
// MOCK — not real data: POST /api/v1/allocation/recalculate/{id}
const RECALC = {
  account_id: ACC, as_of: "2026-11-05T04:05:00+00:00",
  recalculated: [
    { proposal_id: "prop-1", symbol: "LT", rank: 1, quantity: 40, allocation: "ALLOCATION_REDUCED", allocated_qty: 30, recorded: true },
    { proposal_id: "prop-2", symbol: "SBIN", rank: 2, quantity: 200, allocation: "ALLOCATION_REDUCED", allocated_qty: 120, recorded: true },
  ],
};

// MOCK — not real data: GET /api/v1/paper/positions
const pos = (o: Record<string, unknown>) => ({ direction: "long", is_open: true, realized_net_rs: 0, mark: null, ...o });
const OPEN_POSITIONS = [
  pos({ position_id: "pos-1", symbol: "HDFCBANK", state: "OPEN", quantity: 120, avg_entry_price: 1650, stop_loss: 1600, invested_rs: 198_000, risk_at_stop_rs: 6_000,
    mark: { price: 1662.4, basis: "bid", at: "2026-11-05T04:00:00+00:00", unrealized_net_rs: 1_210.8 } }),
  pos({ position_id: "pos-2", symbol: "TCS", state: "OPEN", quantity: 40, avg_entry_price: 3750, stop_loss: 3650, invested_rs: 150_000, risk_at_stop_rs: 4_000,
    mark: { price: 3712, basis: "bid", at: "2026-11-05T04:00:00+00:00", unrealized_net_rs: -1_690.4 } }),
  pos({ position_id: "pos-3", symbol: "INFY", state: "MONITORING", quantity: 10, avg_entry_price: 1500, stop_loss: 1300, invested_rs: 15_000, risk_at_stop_rs: 2_000, realized_net_rs: 350.25 }),
];
const CLOSED = pos({ position_id: "pos-4", symbol: "RELIANCE", state: "CLOSED", is_open: false, quantity: 0, avg_entry_price: 1400, stop_loss: 1360, realized_net_rs: 2_500.5 });
// MOCK — not real data: GET /api/v1/paper/orders?state=LIVE
const LIVE_ORDERS = [
  { order_id: "ord-p1", symbol: "AXISBANK", purpose: "ENTRY", state: "PENDING" },
  { order_id: "ord-x1", symbol: "INFY", purpose: "EXIT", state: "PENDING" },
];

// ── the routes ───────────────────────────────────────────────────────────

interface Opts {
  mode?: string;
  account?: Record<string, unknown>;
  accountReply?: { status: number; body: unknown };
  exposures?: unknown;
  stress?: unknown;
  ranked?: unknown;
  awaiting?: unknown;
  open?: unknown[];
  closed?: unknown[];
  orders?: unknown[];
  qualified?: number;
}
interface Seen { paths: string[]; posts: string[]; ranked: number }

async function spt(page: Page, o: Opts = {}): Promise<Seen> {
  const seen: Seen = { paths: [], posts: [], ranked: 0 };
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (r) => reply(r, []));
  await page.route("**/api/move-odds/**", (r) => reply(r, { detail: "feature_not_enabled" }, 403));
  await page.route("**/api/risk/status", (r) => reply(r, { user_id: "u_fixture", kill_switch: false, halted: false, reason: null, policy_version: "MOCK", scope: "MOCK scope", not_in_scope: null }));
  await page.route(/\/api\/v1\//, (r) => {
    const u = new URL(r.request().url());
    const p = u.pathname;
    seen.paths.push(`${r.request().method()} ${p}`);
    if (r.request().method() !== "GET") seen.posts.push(`${r.request().method()} ${p}`);
    if (p === "/api/v1/paper/accounts") return reply(r, accountsBody(o.mode));
    if (p.startsWith("/api/v1/risk/account/")) return o.accountReply ? reply(r, o.accountReply.body, o.accountReply.status) : reply(r, riskAccount(o.account));
    if (p.startsWith("/api/v1/risk/exposures/")) return reply(r, o.exposures ?? EXPOSURES);
    if (p.startsWith("/api/v1/risk/stress-test/")) return reply(r, o.stress ?? STRESS);
    if (p.startsWith("/api/v1/allocation/recommendations/")) {
      seen.ranked += 1;
      return reply(r, o.ranked ?? RANKED);
    }
    if (p.startsWith("/api/v1/allocation/recalculate/")) return reply(r, RECALC);
    if (p === "/api/v1/proposals") return reply(r, o.awaiting ?? AWAITING);
    if (p === "/api/v1/opportunities") {
      const n = o.qualified ?? 4;
      return reply(r, { ok: true, count: n, limit: 500, opportunities: Array.from({ length: n }, (_, i) => ({ _id: `opp-${i + 1}` })), score_label: "MOCK" });
    }
    if (p === "/api/v1/paper/positions") {
      const open = o.open ?? OPEN_POSITIONS;
      const rows = u.searchParams.get("status") === "all" ? [...open, ...(o.closed ?? [CLOSED])] : open;
      return reply(r, { positions: rows, count: rows.length });
    }
    if (p === "/api/v1/paper/orders") {
      const rows = o.orders ?? LIVE_ORDERS;
      return reply(r, { orders: rows, count: rows.length });
    }
    return reply(r, { detail: { code: "not_mocked", message: "MOCK: not mocked in this spec" } }, 404);
  });
  return seen;
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

const BANNED = /\b(recommend\w*|picks?|suggested)\b/i;
async function bannedWords(page: Page): Promise<string[]> {
  const lines = await page.evaluate(() => {
    const panel = document.querySelector('[data-testid="risk-desk"]') as HTMLElement | null;
    const out = [panel?.innerText ?? ""];
    for (const el of Array.from(panel?.querySelectorAll("[aria-label],[title],[placeholder]") ?? [])) {
      for (const a of ["aria-label", "title", "placeholder"]) {
        const v = el.getAttribute(a);
        if (v) out.push(v);
      }
    }
    return out.join("\n").split("\n");
  });
  return lines.filter((l) => BANNED.test(l));
}

// ── the tests ────────────────────────────────────────────────────────────

test.describe("MOCK — not real data: Risk Desk · Scanner-to-Paper Trading views", () => {
  test("SPT-UI-R-20 the switcher lists the three views; each opens from the URL with one h1 and the paper-only line", async ({ page }) => {
    await spt(page);
    await page.goto(OVERVIEW);
    const panel = page.getByTestId("desk-panel-risk");
    for (const [key, label] of [["overview", "Trading overview"], ["allocation", "Capital allocation"], ["portfolio", "Portfolio risk"]]) {
      await expect(page.getByTestId(`desk-view-${key}`)).toHaveText(label);
      await page.getByTestId(`desk-view-${key}`).click();
      await expect(panel.getByTestId("risk-desk")).toHaveAttribute("data-view", key);
      await expect(page).toHaveURL(new RegExp(`[?&]view=${key}(&|$)`));
      await expect(panel.getByTestId("rd-title")).toBeVisible(SLOW);
      await expect(panel.locator("h1")).toHaveCount(1);
      await expect(panel).toContainText(`Risk Desk · ${label}`);
      await expect(panel.getByTestId("rd-paper-only")).toBeVisible();
    }
    // The existing views are still where they were.
    for (const key of ["limits", "controls", "log"]) await expect(page.getByTestId(`desk-view-${key}`)).toBeVisible();
  });

  test("SPT-UI-R-01 / R-02 / R-03 / R-17 overview: account figures, risk vs limits, ladder, kill switch, counts and links; calls use the account id", async ({ page }) => {
    const seen = await spt(page);
    await page.goto(OVERVIEW);
    const v = (id: string) => page.getByTestId(`${id}-value`);
    await expect(v("spt-kpi-equity")).toHaveText(inr(EQUITY), SLOW);
    await expect(v("spt-kpi-available")).toHaveText(inr(640_000));
    await expect(v("spt-kpi-deployed")).toHaveText(inr(300_000));
    await expect(v("spt-kpi-reserved")).toHaveText(inr(60_000));
    await expect(page.getByTestId("spt-kpi-reserved")).toContainText("1 pending entry order");
    // Unrealized: 1,210.80 − 1,690.40 = −479.60 over the two marked positions; INFY has no mark and is said, not guessed.
    await expect(v("spt-kpi-unrealized")).toHaveText(inr(1_210.8 - 1_690.4));
    await expect(page.getByTestId("spt-kpi-unrealized")).toContainText("1 open position has no live mark");
    // Realized: 0 + 0 + 350.25 + 2,500.50 = 2,850.75 over every SPT position.
    await expect(v("spt-kpi-realized")).toHaveText(inr(2_850.75));
    await expect(v("spt-kpi-day")).toHaveText(inr(-4_200));
    await expect(page.getByTestId("spt-ov-equity-basis")).toContainText("MOCK basis: paper cash plus positions at their marks");

    await expect(v("spt-ov-planned")).toHaveText(inr(12_340.5));
    await expect(v("spt-ov-stressed")).toHaveText(inr(15_890.25));
    await expect(page.getByTestId("spt-ov-stressed")).toContainText("1% gap through every stop");
    await expect(v("spt-ov-open-risk")).toHaveText(`${inr(18_400)} of ${inr(30_375)}`);
    await expect(page.getByTestId("spt-ov-open-risk")).toContainText("1.82% of equity; limit 3%");
    await expect(v("spt-ov-day-loss")).toHaveText("0.41% of 2% limit");
    await expect(v("spt-ov-week-loss")).toHaveText("0.00% of 4% limit");
    await expect(v("spt-ov-drawdown")).toHaveText("2.50%");

    await expect(page.getByTestId("spt-band")).toHaveAttribute("data-band", "reduce");
    await expect(page.getByTestId("spt-ov-ladder-reduce")).toHaveAttribute("data-current", "true");
    await expect(page.getByTestId("spt-ov-ladder-normal")).toHaveAttribute("data-current", "false");
    await expect(page.getByTestId("spt-ov-ladder-normal")).toContainText("below 2%");
    await expect(page.getByTestId("spt-ov-ladder-reduce")).toContainText("2–4%");
    await expect(page.getByTestId("spt-ov-ladder-reduce")).toContainText("new trade risk × 0.5");
    await expect(page.getByTestId("spt-ov-ladder-restricted")).toContainText("4–6%");
    await expect(page.getByTestId("spt-ov-ladder-halt")).toContainText("6% and above");
    await expect(page.getByTestId("spt-ov-ladder-text")).toHaveText(LADDER_TEXT);
    await expect(page.getByTestId("spt-ks-state")).toHaveAttribute("data-state", "ACTIVE");
    await expect(page.getByTestId("spt-ov-ks-text")).toHaveText(KS_TEXT);
    await expect(page.getByTestId("spt-mode")).toHaveAttribute("data-mode", "approval");

    await expect(v("spt-ov-qualified")).toHaveText("4");
    await expect(v("spt-ov-awaiting")).toHaveText("2");
    await expect(v("spt-ov-positions")).toHaveText("4 of 10");
    await expect(page.getByTestId("spt-ov-positions")).toContainText("3 of them are SPT paper positions");
    await expect(v("spt-ov-orders")).toHaveText("2");
    await expect(page.getByTestId("spt-ov-orders")).toContainText("1 entry, 1 exit");
    await expect(v("spt-ov-new-today")).toHaveText("1 of 5");
    await expect(page.getByTestId("spt-ov-warnings-none")).toBeVisible();

    // R-17: every account-scoped call carries the id from GET /api/v1/paper/accounts.
    const scoped = seen.paths.filter((p) => /\/api\/v1\/(risk|allocation)\//.test(p));
    expect(scoped.length).toBeGreaterThan(0);
    for (const p of scoped) expect(p).toMatch(new RegExp(`/${ACC}$`));

    await page.getByTestId("spt-ov-link-opps").click();
    await expect(page).toHaveURL(/[?&]tab=trade&view=paper&sub=opportunities(&|$)/);
    await page.goto(OVERVIEW);
    await page.getByTestId("spt-ov-link-pnl").click();
    await expect(page).toHaveURL(/[?&]tab=trade&view=paper&sub=pnl(&|$)/);
  });

  test("SPT-UI-R-04 overview: active risk warnings list the kill switch's reasons, unknown equity and unpriced entries", async ({ page }) => {
    const reasons = [
      { code: "kill_switch_on", text: "MOCK: The kill switch is on: results week." },
      { code: "daily_loss_halt", text: "MOCK: The day's loss 2.10% is at or past the 2% limit." },
    ];
    await spt(page, { account: {
      kill_switch: { state: "TRIGGERED", entries_blocked: true, kill_switch: true, halted: false, code: "kill_switch_on", reason: reasons.map((r) => r.text).join("; "), reasons, text: "MOCK: refused." },
      equity_unknown_reasons: ["MOCK: one mark is missing"],
      spt_risk: { planned_rs: 1000, stressed_rs: 1200, entries: 2, unpriced: ["ord-9"], stressed_gap_pct: 1, basis: "MOCK" },
    } });
    await page.goto(OVERVIEW);
    const items = page.getByTestId("spt-ov-warnings-item");
    await expect(items).toHaveCount(4, SLOW);
    await expect(items.nth(0)).toHaveText(reasons[0].text);
    await expect(items.nth(0)).toHaveAttribute("data-tone", "danger");
    await expect(items.nth(1)).toHaveText(reasons[1].text);
    await expect(items.nth(2)).toHaveText("Equity unknown: MOCK: one mark is missing");
    await expect(items.nth(3)).toContainText("1 SPT entry has no quantity, price or stop yet");
    await expect(page.getByTestId("spt-ks-state")).toHaveAttribute("data-state", "TRIGGERED");
    await expect(page.getByTestId("spt-ov-ks-state")).toHaveAttribute("data-state", "TRIGGERED");
    await expect(page.getByTestId("rd-title")).toContainText("new positions are blocked");
  });

  test("SPT-UI-R-05 overview: mode off and an empty account show the API's state, zeros and dashes, nothing invented", async ({ page }) => {
    await spt(page, {
      mode: "off", open: [], closed: [], orders: [], qualified: 0, awaiting: { items: [], count: 0 },
      account: {
        mode: "off", deployed_rs: 0, reserved_rs: 0, pending_entries: [],
        spt_risk: { planned_rs: 0, stressed_rs: 0, entries: 0, unpriced: [], stressed_gap_pct: 1, basis: "MOCK" },
        daily_loss: { pnl_rs: null, start_equity_rs: null, loss_pct: null, limit_pct: 2, breached: null },
        kill_switch: { state: "DISABLED", entries_blocked: false, kill_switch: false, halted: false, reasons: [], text: "MOCK: The SPT mode is off." },
        utilisation: { positions: { open: 0, max: 10 }, new_today: { count: 0, max: 5 }, buckets: {}, exposure_rs: 0, exposure_pct_of_equity: 0 },
      },
    });
    await page.goto(OVERVIEW);
    await expect(page.getByTestId("spt-ov-mode-off")).toBeVisible(SLOW);
    await expect(page.getByTestId("spt-ov-link-settings")).toBeVisible();
    await expect(page.getByTestId("spt-mode")).toHaveAttribute("data-mode", "off");
    await expect(page.getByTestId("spt-ks-state")).toHaveAttribute("data-state", "DISABLED");
    await expect(page.getByTestId("spt-kpi-day-value")).toHaveText("—");
    await expect(page.getByTestId("spt-kpi-day")).toContainText("unknown (fail closed)");
    await expect(page.getByTestId("spt-kpi-unrealized-value")).toHaveText("₹0");
    await expect(page.getByTestId("spt-kpi-realized-value")).toHaveText("₹0");
    await expect(page.getByTestId("spt-ov-qualified-value")).toHaveText("0");
    await expect(page.getByTestId("spt-ov-awaiting-value")).toHaveText("0");
    await expect(page.getByTestId("spt-ov-orders-value")).toHaveText("0");
    await expect(page.getByTestId("spt-ov-positions-value")).toHaveText("0 of 10");
    await expect(page.getByTestId("spt-ov-day-loss-value")).toHaveText("— of 2% limit");
  });

  test("SPT-UI-R-06 / R-07 allocation: capital and risk in two separate sections — buckets, reserve, sectors, instruments, risk budget and risk by sector", async ({ page }) => {
    await spt(page);
    await page.goto(ALLOCATION);
    const capital = page.getByTestId("spt-al-capital");
    const risk = page.getByTestId("spt-al-risk");
    await expect(capital).toBeVisible(SLOW);
    await expect(risk).toBeVisible();
    await expect(page.getByTestId("spt-al-capital-title")).toContainText("Capital allocation");
    await expect(page.getByTestId("spt-al-risk-title")).toContainText("Risk allocation");
    await expect(capital).toContainText("Capital — the rupees put to work");
    await expect(risk).toContainText("Risk — what the open positions could lose at their stops");

    await expect(page.getByTestId("spt-al-kpi-equity-value")).toHaveText(inr(EQUITY));
    await expect(page.getByTestId("spt-al-kpi-inuse-value")).toHaveText(inr(360_000));
    await expect(page.getByTestId("spt-al-kpi-reserve-value")).toHaveText(inr(101_250));
    await expect(page.getByTestId("spt-al-kpi-risk-left-value")).toHaveText(inr(30_375 - 18_400));

    const buckets = capital.getByTestId("spt-al-buckets-row");
    await expect(buckets).toHaveCount(3);
    await expect(buckets.nth(0).getByTestId("spt-al-buckets-bucket")).toHaveText("Equity positional");
    await expect(buckets.nth(0).getByTestId("spt-al-buckets-pct")).toHaveText("45%");
    await expect(buckets.nth(0).getByTestId("spt-al-buckets-cap")).toHaveText(inr(455_625));
    await expect(buckets.nth(0).getByTestId("spt-al-buckets-used")).toHaveText(inr(360_000));
    await expect(buckets.nth(0).getByTestId("spt-al-buckets-left")).toHaveText(inr(95_625));
    await expect(buckets.nth(2).getByTestId("spt-al-buckets-bucket")).toHaveText("F&O strategies");
    await expect(page.getByTestId("spt-al-reserve-value")).toHaveText(inr(101_250));
    await expect(page.getByTestId("spt-al-reserve")).toContainText("10% of equity, never allocated");

    const sectors = capital.getByTestId("spt-al-sectors-row");
    await expect(sectors).toHaveCount(2);
    await expect(sectors.nth(0).getByTestId("spt-al-sectors-name")).toHaveText("Financial Services");
    await expect(sectors.nth(0).getByTestId("spt-al-sectors-exposure")).toHaveText(inr(220_000));
    await expect(sectors.nth(0).getByTestId("spt-al-sectors-pct")).toHaveText("21.73%");
    await expect(sectors.nth(0).getByTestId("spt-al-sectors-limit")).toHaveText("25%");
    await expect(page.getByTestId("spt-al-unclassified")).toContainText(inr(40_000));
    await expect(capital.getByTestId("spt-al-instruments-row")).toHaveCount(3);

    await expect(page.getByTestId("spt-al-risk-budget-value")).toHaveText(`${inr(18_400)} of ${inr(30_375)}`);
    await expect(page.getByTestId("spt-al-risk-budget")).toContainText(`${inr(11_975)} of risk budget left`);
    await expect(page.getByTestId("spt-al-planned-value")).toHaveText(inr(12_340.5));
    await expect(page.getByTestId("spt-al-stressed-value")).toHaveText(inr(15_890.25));
    // Risk by sector from the stress test's positions: FS 6,180.50 / 8,100.50; IT 4,160 + 2,000 = 6,160 / 5,620 + 2,169.75 = 7,789.75.
    const rsec = risk.getByTestId("spt-al-risk-sectors-row");
    await expect(rsec).toHaveCount(2);
    await expect(rsec.nth(0).getByTestId("spt-al-risk-sectors-name")).toHaveText("Financial Services");
    await expect(rsec.nth(0).getByTestId("spt-al-risk-sectors-planned")).toHaveText(inr(6_180.5));
    await expect(rsec.nth(0).getByTestId("spt-al-risk-sectors-stressed")).toHaveText(inr(8_100.5));
    await expect(rsec.nth(0).getByTestId("spt-al-risk-sectors-share")).toHaveText(`${((8_100.5 / 15_890.25) * 100).toFixed(2)}%`);
    await expect(rsec.nth(1).getByTestId("spt-al-risk-sectors-planned")).toHaveText(inr(6_160));
    await expect(rsec.nth(1).getByTestId("spt-al-risk-sectors-stressed")).toHaveText(inr(7_789.75));
    await expect(risk.getByTestId("spt-al-risk-instruments-row")).toHaveCount(3);
  });

  test("SPT-UI-R-08 allocation: the ranked opportunities with score, R:R, quantity sized by your limits, capital, planned risk and why reduced or not fitting", async ({ page }) => {
    await spt(page);
    await page.goto(ALLOCATION);
    const rows = page.getByTestId("spt-al-ranked-row");
    await expect(rows).toHaveCount(4, SLOW);
    const cell = (i: number, k: string) => rows.nth(i).getByTestId(`spt-al-ranked-${k}`);
    await expect(cell(0, "rank")).toHaveText("1");
    await expect(cell(0, "symbol")).toHaveText("LT");
    await expect(cell(0, "score")).toHaveText("82.5");
    await expect(cell(0, "rr")).toHaveText("2.6 : 1");
    await expect(cell(0, "qty")).toHaveText("40");
    await expect(cell(0, "capital")).toHaveText(inr(144_000));
    await expect(cell(0, "planned")).toHaveText(inr(5_000));
    await expect(cell(0, "stressed")).toHaveText(inr(6_400));
    await expect(cell(0, "decision")).toHaveText("fits in full");
    await expect(cell(0, "proposal")).toHaveText("awaiting user approval");
    await expect(cell(1, "qty")).toHaveText("120 (sized 200)");
    await expect(cell(1, "capital")).toHaveText(inr(96_000));
    await expect(cell(1, "planned")).toHaveText(inr(4_900));               // as sized (200 shares), labelled so
    await expect(cell(1, "stressed")).toHaveText(inr(3_900));              // as allocated (120 shares)
    await expect(cell(1, "decision")).toHaveText("reduced");
    await expect(cell(1, "reason")).toHaveText(BUCKET_MSG);
    await expect(cell(2, "decision")).toHaveText("does not fit");
    await expect(cell(2, "qty")).toHaveText("0 (sized 300)");
    await expect(cell(2, "capital")).toHaveText("₹0");                     // nothing allocated, never the sized ₹1,26,000
    await expect(cell(2, "stressed")).toHaveText("₹0");
    await expect(cell(2, "reason")).toHaveText(OPEN_RISK_MSG);
    await expect(cell(2, "proposal")).toHaveText("none yet");
    await expect(cell(3, "decision")).toHaveText("fails the plan checks");
    await expect(cell(3, "reason")).toHaveText(RR_MSG);
    await expect(cell(3, "qty")).toHaveText("—");
    await expect(cell(3, "capital")).toHaveText("—");
    await expect(cell(3, "planned")).toHaveText("—");
    await expect(page.getByTestId("spt-al-ranked-basis")).toContainText("Ranked by opportunity_score, then reward:risk");
    await expect(page.getByTestId("spt-al-ranked-card-title")).toContainText("Ranked opportunities — sized by your limits");
  });

  test("SPT-UI-R-09 / R-22 allocation: opening is read-only; Recalculate POSTs once and shows each proposal's quantity before → now", async ({ page }) => {
    const writes = recordWrites(page);
    const seen = await spt(page);
    for (const url of [OVERVIEW, ALLOCATION, PORTFOLIO]) {
      await page.goto(url);
      await expect(page.getByTestId("rd-title")).toBeVisible(SLOW);
      await page.waitForTimeout(300);
    }
    expect(writes).toEqual([]);
    await page.goto(ALLOCATION);
    await expect(page.getByTestId("spt-al-ranked-row")).toHaveCount(4, SLOW);
    await expect(page.getByTestId("spt-al-recalc-card")).toContainText("(2 now)");
    const before = seen.ranked;
    await page.getByTestId("spt-al-recalc").click();
    const rows = page.getByTestId("spt-al-recalc-rows-row");
    await expect(rows).toHaveCount(2);
    expect(writes).toEqual([`POST /api/v1/allocation/recalculate/${ACC}`]);
    const cell = (i: number, k: string) => rows.nth(i).getByTestId(`spt-al-recalc-rows-${k}`);
    await expect(cell(0, "symbol")).toHaveText("LT");
    await expect(cell(0, "before")).toHaveText("40");
    await expect(cell(0, "after")).toHaveText("30");
    await expect(cell(0, "change")).toHaveText("−10");
    await expect(cell(0, "decision")).toHaveText("reduced");
    await expect(cell(0, "recorded")).toHaveText("yes");
    await expect(cell(1, "before")).toHaveText("120");
    await expect(cell(1, "after")).toHaveText("120");
    await expect(cell(1, "change")).toHaveText("unchanged");
    await expect.poll(() => seen.ranked).toBeGreaterThan(before);
  });

  test("SPT-UI-R-10 allocation: no qualified opportunities — an empty state, the capital and risk sections still drawn", async ({ page }) => {
    await spt(page, { ranked: { ...RANKED, items: [] } });
    await page.goto(ALLOCATION);
    await expect(page.getByTestId("spt-al-ranked-empty")).toHaveText("No qualified opportunities right now, so nothing is ranked.", SLOW);
    await expect(page.getByTestId("spt-al-ranked")).toHaveCount(0);
    await expect(page.getByTestId("spt-al-capital")).toBeVisible();
    await expect(page.getByTestId("spt-al-risk")).toBeVisible();
  });

  test("SPT-UI-R-11 / R-12 / R-13 / R-14 / R-15 portfolio: risk totals, loss use, ladder, sectors, stress scenarios, positions at risk, not-available panels", async ({ page }) => {
    await spt(page);
    await page.goto(PORTFOLIO);
    const v = (id: string) => page.getByTestId(`${id}-value`);
    await expect(v("spt-pr-kpi-planned")).toHaveText(inr(12_340.5), SLOW);
    await expect(v("spt-pr-kpi-stressed")).toHaveText(inr(15_890.25));
    await expect(page.getByTestId("spt-pr-kpi-stressed")).toContainText(`${((15_890.25 / EQUITY) * 100).toFixed(2)}% of equity`);
    await expect(v("spt-pr-kpi-open")).toHaveText("1.82%");
    await expect(v("spt-pr-kpi-day")).toHaveText("0.41%");
    await expect(v("spt-pr-kpi-week")).toHaveText("0.00%");
    await expect(v("spt-pr-kpi-drawdown")).toHaveText("2.50%");
    await expect(v("spt-pr-day-loss")).toHaveText("0.41% of 2% limit");
    await expect(v("spt-pr-week-loss")).toHaveText("0.00% of 4% limit");
    await expect(page.getByTestId("spt-pr-ladder-reduce")).toHaveAttribute("data-current", "true");
    await expect(page.getByTestId("spt-pr-ladder-text")).toHaveText(LADDER_TEXT);

    // R-12 sector concentration: exposure from /exposures, risk from the stress test.
    const sec = page.getByTestId("spt-pr-sectors-row");
    await expect(sec).toHaveCount(2);
    await expect(sec.nth(0).getByTestId("spt-pr-sectors-sector")).toHaveText("Financial Services");
    await expect(sec.nth(0).getByTestId("spt-pr-sectors-exposure")).toHaveText(inr(220_000));
    await expect(sec.nth(0).getByTestId("spt-pr-sectors-pct")).toHaveText("21.73%");
    await expect(sec.nth(0).getByTestId("spt-pr-sectors-limit")).toHaveText("25%");
    await expect(sec.nth(0).getByTestId("spt-pr-sectors-planned")).toHaveText(inr(6_180.5));
    await expect(sec.nth(0).getByTestId("spt-pr-sectors-stressed")).toHaveText(inr(8_100.5));
    await expect(sec.nth(1).getByTestId("spt-pr-sectors-stressed")).toHaveText(inr(7_789.75));

    // R-13 the stress scenarios.
    const sc = page.getByTestId("spt-pr-scenarios-row");
    await expect(sc).toHaveCount(4);
    const c = (i: number, k: string) => sc.nth(i).getByTestId(`spt-pr-scenarios-${k}`);
    await expect(c(0, "name")).toHaveText("Gap through stop (1%)");
    await expect(c(0, "planned")).toHaveText(inr(12_340.5));
    await expect(c(0, "loss")).toHaveText(inr(15_890.25));
    await expect(c(0, "pct")).toHaveText(`${((15_890.25 / EQUITY) * 100).toFixed(2)}%`);
    await expect(c(1, "name")).toHaveText("Sector shock (−5%)");
    await expect(c(1, "planned")).toHaveText("—");
    await expect(c(1, "loss")).toHaveText(inr(9_900));
    await expect(c(1, "worst")).toHaveText("Financial Services");
    await expect(c(2, "name")).toHaveText("Market −3%");
    await expect(c(2, "loss")).toHaveText(inr(10_890));
    await expect(c(2, "text")).toContainText("Beta 1 assumed.");
    await expect(c(3, "name")).toHaveText("Market −5%");
    await expect(c(3, "loss")).toHaveText(inr(18_150));
    await expect(page.getByTestId("spt-pr-sector-shock")).toContainText(`Financial Services ${inr(9_900)} · Information Technology ${inr(8_250)}`);

    // R-14 positions at risk, largest risk to the stop first: HDFCBANK (1,662.40 − 1,600) × 120 = 7,488; TCS (3,712 − 3,650) × 40 = 2,480.
    const p = page.getByTestId("spt-pr-positions-row");
    await expect(p).toHaveCount(3);
    const pc = (i: number, k: string) => p.nth(i).getByTestId(`spt-pr-positions-${k}`);
    await expect(pc(0, "symbol")).toHaveText("HDFCBANK");
    await expect(pc(0, "qty")).toHaveText("120");
    await expect(pc(0, "stop")).toHaveText("1,600");
    await expect(pc(0, "price")).toHaveText("1,662.4 · bid");
    await expect(pc(0, "risk")).toHaveText(inr(7_488));
    await expect(pc(1, "symbol")).toHaveText("TCS");
    await expect(pc(1, "risk")).toHaveText(inr(2_480));
    await expect(pc(2, "symbol")).toHaveText("INFY");
    await expect(pc(2, "price")).toHaveText("— (no live mark)");
    await expect(pc(2, "risk")).toHaveText("— (no live mark)");

    // R-15 the panels that say what this release does not compute — and draw no number.
    for (const id of ["spt-pr-na-correlation", "spt-pr-na-greeks", "spt-pr-na-margin"]) {
      await expect(page.getByTestId(id)).toContainText("not available in this release");
      expect(await page.getByTestId(id).innerText()).not.toMatch(/₹|\d+(\.\d+)?%/);
    }
  });

  test("SPT-UI-R-16 portfolio: no open positions — empty positions state, the scenarios still render with zero totals", async ({ page }) => {
    const zero = clone(STRESS);
    zero.positions = [];
    zero.totals = { planned_rs: 0, stressed_rs: 0, value_rs: 0 };
    zero.scenarios = [
      { name: "gap_through_stop", gap_pct: 1, planned_rs: 0, stressed_rs: 0, text: "MOCK gap text" },
      { name: "sector_shock", shock_pct: -5, by_sector_rs: {}, worst_sector: null, worst_loss_rs: 0, text: "MOCK sector text" },
      { name: "market_shock", results: [{ shock_pct: -3, beta: 1, beta_assumed: true, loss_rs: 0 }, { shock_pct: -5, beta: 1, beta_assumed: true, loss_rs: 0 }], text: "MOCK market text." },
    ] as typeof STRESS.scenarios;
    await spt(page, { open: [], closed: [], stress: zero, exposures: { ...EXPOSURES, by_sector: [], by_instrument: [], unclassified_exposure_rs: 0 } });
    await page.goto(PORTFOLIO);
    await expect(page.getByTestId("spt-pr-positions-empty")).toHaveText("No open SPT paper positions.", SLOW);
    await expect(page.getByTestId("spt-pr-sectors-empty")).toBeVisible();
    await expect(page.getByTestId("spt-pr-scenarios-row")).toHaveCount(4);
    await expect(page.getByTestId("spt-pr-scenarios-row").nth(0).getByTestId("spt-pr-scenarios-loss")).toHaveText("₹0");
    await expect(page.getByTestId("spt-pr-scenarios-row").nth(1).getByTestId("spt-pr-scenarios-worst")).toHaveText("—");
  });

  test("SPT-UI-R-18 an unreadable account (503) shows an error with retry on each view, and no invented figure", async ({ page }) => {
    await spt(page, { accountReply: { status: 503, body: { detail: { code: "account_unreadable", message: "MOCK: the book could not be read" } } } });
    for (const [url, id] of [[OVERVIEW, "spt-ov-error"], [ALLOCATION, "spt-al-error"], [PORTFOLIO, "spt-pr-error"]]) {
      await page.goto(url);
      await expect(page.getByTestId(id)).toBeVisible({ timeout: 20_000 });
      await expect(page.getByTestId(id).getByRole("button").first()).toBeVisible();
      await expect(page.getByTestId("rd-title")).toBeVisible();
      await expect(page.locator('[data-testid$="-kpi-equity"], [data-testid="spt-kpi-equity"]')).toHaveCount(0);
    }
  });

  test("SPT-UI-R-21 the three views use no 'recommend', 'pick' or 'suggested' (text, aria-labels, titles, placeholders)", async ({ page }) => {
    await spt(page);
    for (const url of [OVERVIEW, ALLOCATION, PORTFOLIO]) {
      await page.goto(url);
      await expect(page.getByTestId("rd-title")).toBeVisible(SLOW);
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(300);
      expect(await bannedWords(page), url).toEqual([]);
    }
    await page.goto(ALLOCATION);
    await expect(page.getByTestId("spt-al-ranked-row")).toHaveCount(4, SLOW);
    await page.getByTestId("spt-al-recalc").click();
    await expect(page.getByTestId("spt-al-recalc-rows-row")).toHaveCount(2);
    expect(await bannedWords(page), "after recalculate").toEqual([]);
  });
});

test.describe("MOCK — not real data: Risk Desk SPT views · phone 390px", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("SPT-UI-R-19 no sideways scroll on the three views, with long reasons, as cards", async ({ page }) => {
    const long = "A long reason that keeps going without a break ".repeat(10);
    const ranked = clone(RANKED);
    ranked.items[1].allocation!.reasons = [{ code: "x", message: long }];
    await spt(page, {
      ranked,
      account: { kill_switch: { state: "RESTRICTED", entries_blocked: true, reasons: [{ code: "x", text: long }], reason: long, text: long } },
    });
    for (const url of [OVERVIEW, ALLOCATION, PORTFOLIO]) {
      await page.goto(url);
      await expect(page.getByTestId("rd-title")).toBeVisible(SLOW);
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(400);
      await noSideScroll(page, url);
    }
    // Phone: tables become cards (a list, no <table>).
    await page.goto(PORTFOLIO);
    await expect(page.getByTestId("spt-pr-scenarios")).toBeVisible(SLOW);
    expect(await page.getByTestId("spt-pr-scenarios").evaluate((el) => el.tagName)).toBe("UL");
    await page.goto(ALLOCATION);
    await page.getByTestId("spt-al-recalc").click();
    await expect(page.getByTestId("spt-al-recalc-rows-row")).toHaveCount(2);
    await noSideScroll(page, "allocation after recalculate");
  });
});

// Opt-in screenshots for a visual check (SPT_SHOTS=<dir>); skipped in a normal run. MOCK — not real data.
test.describe("MOCK — not real data: Risk Desk SPT views · screenshots", () => {
  const SHOTS = process.env.SPT_SHOTS || "";
  test.skip(!SHOTS, "set SPT_SHOTS to a directory to capture");
  for (const [w, h, tag] of [[1280, 3400, "desktop"], [390, 7600, "phone"]] as const) {   // tall: the desk scrolls inside an element
    test(`screens at ${tag}`, async ({ page }) => {
      await page.setViewportSize({ width: w, height: h });
      await spt(page);
      for (const [url, name] of [[OVERVIEW, "overview"], [ALLOCATION, "allocation"], [PORTFOLIO, "portfolio"]]) {
        await page.goto(url);
        await expect(page.getByTestId("rd-title")).toBeVisible(SLOW);
        await page.waitForLoadState("networkidle");
        await page.waitForTimeout(500);
        await page.screenshot({ path: `${SHOTS}/spt-${name}-${tag}.png`, fullPage: true });
      }
    });
  }
});
