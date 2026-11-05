/**
 * One-screen Copilot app (/v5/app) — Trade Desk › Paper Trading v2, builder A: the navigation and redirects, the shell
 * (status strip, account card, mode chooser), 01 Overview, 02 Scanner opportunities, 06 Strategy analytics (the owner's
 * six-view design of 5 Nov 2026; docs/scanner_paper_trading/UI_DESIGN_V2.md). Test cases PV2-A-01 … A-62 in
 * test_reports/paper_v2_ui_a_TESTCASES.md.
 *
 * Every /api/* answer below is an inline MOCK — not real data — in the shapes of UI_DESIGN_V2.md §7 (the new
 * /api/v1/paper/overview and /api/v1/analytics/account/{id}) and of the existing routes read from code (routes/spt_accounts.py
 * + services/paper_account.public, spt_signals.py, spt_risk.py with services/spt/risk.py checks[], outcomes/analytics.py,
 * routes/watchlists.py). Symbols, prices, ids and figures are made up. Mocked APIs, production build: these cases prove the
 * screens render what the bodies say and send the right requests, NOT that the backend answers these shapes.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
const DESK = "/v5/app/trader/desk";
const at = (sub: string) => `${DESK}?tab=trade&view=paper&sub=${sub}`;
const SLOW = { timeout: 15_000 };
const BANNED = /\bpick|recommend|suggest/i;
const UID = "user_ed05fb1daa45";            // the fixture user (e2e/fixtures/user-profile-onboarded.json)
type Row = Record<string, unknown>;

// ── MOCK — not real data: the paper account (GET /api/v1/paper/accounts; services/paper_account.public + policy.public) ──
const config = (o: Row = {}): Row => ({
  user_id: UID, account_id: UID, mode: "approval", version: 3,
  extras: { risk_pct: { positional: 0.5 }, max_positions: 10, allocation_buckets_pct: { equity_positional: 45, equity_intraday: 25, fno: 20, reserve: 10 } },
  updated_at: "2026-11-05T01:40:00+00:00", updated_by: UID, reason: null, stored: true, policy_version: "spt-config-v2", ...o,
});
const account = (cfg: Row) => ({
  account_id: UID, account: { user_id: UID, starting_capital_rs: 1000000, cash_rs: 692200, blocked_rs: 0, available_rs: 692200, stored: true, policy_version: "MOCK" },
  config: clone(cfg), modes: ["off", "tracking", "approval", "auto"], note: "MOCK: one paper account per user",
});

// ── MOCK — not real data: GET /api/v1/paper/overview (UI_DESIGN_V2.md §7) ─────────────────────────────────────────────────
const OVERVIEW = (o: { status?: Row; kpis?: Row | null; headline?: Row; pipeline?: Row[]; warnings?: Row[] } = {}): Row => ({
  account_id: UID, as_of: "2026-11-05T05:40:00+00:00",
  status: { feed_state: "live", last_tick_age_s: 1.2, session: "open", kill_switch: { state: "ACTIVE", entries_blocked: false, text: "MOCK: new entries allowed" }, policy_version: 7, mode: "approval", ...(o.status ?? {}) },
  kpis: o.kpis === null ? undefined : {
    equity_rs: 1004200, start_equity_rs: 1000000, day_pnl_rs: 4200, day_loss_limit_pct: 2, day_loss_used_pct: 0, deployed_rs: 312000, deployed_pct: 31.07, cash_rs: 692200,
    open_risk_pct: 2.6, open_risk_limit_pct: 3, drawdown_pct: 0.42, drawdown_warn_pct: 5, positions_open: 4, positions_max: 10, orders_pending: 1, ...(o.kpis ?? {}),
  },
  pipeline: o.pipeline ?? [
    { stage: "signals", label: "Scanner signals", count: 14 }, { stage: "opportunities", label: "Opportunities", count: 6 }, { stage: "qualified", label: "Qualified", count: 4 },
    { stage: "risk_approved", label: "Risk approved", count: 3 }, { stage: "orders_filled", label: "Orders filled", count: 2 }, { stage: "open_positions", label: "Open positions", count: 2 },
  ],
  warnings: o.warnings ?? [
    { level: "mint", title: "All feeds healthy", code: "feeds_ok", at: "2026-11-05T05:39:00+00:00" },
    { level: "amber", title: "Open planned risk is at 87% of its budget", code: "near_limit", at: "2026-11-05T05:20:00+00:00" },
    { level: "danger", title: "HDFCBANK refused: ten positions are open", code: "risk_rejected", at: "2026-11-05T05:32:00+00:00", symbol: "HDFCBANK" },
  ],
  headline: { setups_cleared: 3, worst_concentration: { name: "Banks", pct_of_open_risk: 42 }, signals: 14, opportunities: 6, blocked: 1, reduced: 1, ...(o.headline ?? {}) },
});

// ── MOCK — not real data: opportunities (routes/spt_signals.py) and proposals (services/spt/proposals.public) ────────────
const NOW = Date.now();
const iso = (ms: number) => new Date(ms).toISOString();
const sig = (id: string, scanner: string, name: string, px: number, score: number | null) => ({ signal_id: id, scanner_id: scanner, scanner_name: name,
  detected_at: "2026-11-05T04:05:00+00:00", detected_price: px, scanner_score: score, score_version: "MOCK", category: "breakout", family: "trend" });
const opp = (id: string, symbol: string, state: string, score: number, o: Row = {}): Row => ({
  _id: id, consolidation_key: `MOCK:${symbol}`, symbol, exchange: "NSE", direction: "long", family: "trend", category: "breakout", horizon: "positional",
  day: "2026-11-05", first_seen_at: "2026-11-05T04:05:00+00:00", window_until: iso(NOW + 5 * 86400e3), expires_at: iso(NOW + 5 * 86400e3), state, version: 2,
  signals: [sig(`sig:2026-11-05:w-breakout:${symbol}`, "w-breakout", "MOCK Breakout 52w", 1402, 81), sig(`sig:2026-11-05:strong:${symbol}`, "strong", "MOCK Strong signal", 1404, 77)],
  conflicts: [], strong: { signal_id: `sig:2026-11-05:strong:${symbol}`, plan: { rules: "scan-plan-v3", entry: 1410, stop_loss: 1374.9, target_1: 1480, target_2: 1550, atr: 17.55, sma20: 1380.1, plan_ok: true, plan_note: null } },
  validation: { at: "2026-11-05T04:10:00+00:00", version: "spt-validate-v1", decision: state, reason_codes: [], explanations: ["MOCK: every validation check passed"], opportunity_score: score },
  ...o,
});
const OPPS = (): Row[] => [
  opp("opp-1", "ICICIBANK", "QUALIFIED", 72),
  opp("opp-2", "TCS", "QUALIFIED", 80),
  opp("opp-3", "INFY", "CONDITIONAL", 65),
  opp("opp-4", "HDFCBANK", "QUALIFIED", 70),
  opp("opp-5", "SBIN", "WATCHLIST", 41, { validation: { at: "2026-11-05T04:10:00+00:00", decision: "WATCHLIST", reason_codes: ["below_trigger"], explanations: ["MOCK: the close is still under the trigger"], opportunity_score: 41 } }),
  opp("opp-6", "NIFTY", "QUALIFIED", 60, { instrument: "fno" }),
  opp("opp-7", "WIPRO", "EXPIRED", 55),
  opp("opp-8", "LT", "QUALIFIED", 75),
];
const PASSED = [
  { check: "controls", status: "pass", detail: null, source: "spt" }, { check: "account", status: "pass", detail: null, source: "spt" },
  { check: "ladder", status: "pass", detail: "band normal", source: "spt" }, { check: "positions", status: "pass", detail: null, source: "spt" },
  { check: "min_rr", status: "pass", detail: "T2 3.99 vs 1.5", source: "spt" }, { check: "quantity", status: "pass", detail: "35 shares", source: "spt" },
  { check: "stressed", status: "pass", detail: "₹1,749.70 vs room ₹17,000.00", source: "spt" }, { check: "price", status: "pass", detail: "age 2 s", source: "spt" },
  { check: "sector_exposure", status: "warn", detail: "MOCK: Banks at 18% of a 20% cap", source: "risk_service" },
];
const risk = (decision: string, o: Row = {}): Row => ({
  decision, stage: "risk", reason_codes: [], explanations: [], reasons: [], checks: clone(PASSED), requested_qty: 35, approved_qty: 35, planned_risk_rs: 1268.5, stressed_risk_rs: 1749.7,
  portfolio_risk_before_rs: 12000, portfolio_risk_after_rs: 13268.5, exposure_before_rs: 250000, exposure_after_rs: 299350, conditional: null, at: "2026-11-05T04:12:00+00:00", ...o,
});
const prop = (id: string, oppId: string, symbol: string, state: string, o: Row = {}): Row => ({
  proposal_id: id, user_id: UID, account_id: UID, opportunity_id: oppId, symbol, exchange: "NSE", direction: "long", horizon: "positional", instrument: "cash", state, version: 4,
  entry: { type: "MARKET", price: 1410, basis: "live ask", plan_entry: 1410, limit_price: null, time_in_force: "DAY", expires_at: iso(NOW + 5 * 3600e3), rule: "MOCK immediate" },
  stop_loss: 1374.9, target_1: 1480, target_2: 1550, rr: { t1: 1.99, t2: 3.99, min_rr: 1.5 },
  sizing: { quantity: 35, capital_required: 49350, planned_risk: 1268.5, stressed_risk: 1749.7, blocked: [], risk_pct: { pct: 0.5 } },
  allocation: { decision: "ALLOCATION_APPROVED", quantity: 35, requested_qty: 35, reasons: [] }, risk: risk("APPROVE"),
  approval: state === "AWAITING_USER_APPROVAL" ? { requested_at: iso(NOW), expires_at: iso(NOW + 20 * 60e3), decided_at: null, decision: null } : null,
  order: null, order_rejected: false, reason_codes: [], explanations: [], exit_plan: null, price: null, created_at: "2026-11-05T04:12:00+00:00", state_history: [], ...o,
});
const PROPS = (): Row[] => [
  prop("prop-1", "opp-1", "ICICIBANK", "AWAITING_USER_APPROVAL"),
  prop("prop-2", "opp-2", "TCS", "AWAITING_USER_APPROVAL", { risk: risk("APPROVE_REDUCED", { approved_qty: 20, planned_risk_rs: 702, explanations: ["MOCK: reduced from 35 to 20 shares to fit the open-risk budget"] }) }),
  prop("prop-3", "opp-3", "INFY", "AWAITING_USER_APPROVAL", { risk: risk("CONDITIONAL_APPROVAL", { conditional: { text: "MOCK: enter only above ₹1,600 on a 15-minute close" } }) }),
  prop("prop-4", "opp-4", "HDFCBANK", "BLOCKED_BY_RISK", { risk: risk("BLOCKED", {
    approved_qty: 0, requested_qty: 20, planned_risk_rs: null, explanations: ["MOCK: ten positions are open, the limit is ten."],
    reasons: [{ code: "max_positions", check: "positions", message: "Open positions (10) are at the limit of 10.", severity: "block" }],
    checks: clone(PASSED).map((c) => (c.check === "positions" ? { ...c, status: "fail" } : c)) }) }),
  prop("prop-6", "opp-6", "NIFTY", "NOT_TRADABLE", { instrument: "fno", risk: null, reason_codes: ["instrument_not_enabled"] }),
  prop("prop-8", "opp-8", "LT", "ORDER_CREATED", { order: { order_id: "ord-8", state: "FILLED", order_type: "MARKET", quantity: 35 } }),
];

// ── MOCK — not real data: analytics (§7 /api/v1/analytics/account; outcomes/analytics.py by_scanner) ─────────────────────
const ANALYTICS = (o: Row = {}): Row => ({
  days: 90, trades: 43, wins: 23, losses: 20, win_rate_pct: 53.5, avg_win_r: 1.42, avg_loss_r: -0.95, expectancy_r: 0.31, profit_factor: 1.62, max_drawdown_pct: 3.1,
  sharpe: 1.21, sortino: 1.87,
  by_setup: [{ setup: "breakout", trades: 34, expectancy_r: 0.42, profit_factor: 1.9, win_rate_pct: 58.8 }, { setup: "pullback", trades: 9, expectancy_r: -0.1, profit_factor: 0.8, win_rate_pct: 33.3 }],
  by_regime: [{ regime: "downtrend", trades: 6, expectancy_r: -0.35 }, { regime: "uptrend", trades: 30, expectancy_r: 0.52 }, { regime: "sideways", trades: 7, expectancy_r: 0.08 }],
  certification: [{ setup: "breakout", certified: false, criteria: [
    { key: "min_trades", label: "Minimum 50 completed trades", status: "fail", value: "34 of 50" },
    { key: "expectancy", label: "Positive net expectancy", status: "pass", value: "+0.42R" },
    { key: "profit_factor", label: "Profit factor ≥ 1.3", status: "pass", value: 1.9 },
    { key: "oos", label: "Out-of-sample validated", status: "not_measured", value: null },
    { key: "regimes", label: "Two or more market regimes", status: "warn", value: "1 of 2" },
  ] }],
  basis: "MOCK: closed SPT paper trades, net of modeled costs", notes: [], ...o,
});
const hz = (n: number, avg: number, mfe: number, mae: number) => ({ n, hit_rate_pct: 55, hit_rate_ci95_pct: [40, 70], avg_return_pct: avg, median_return_pct: avg, avg_mfe_pct: mfe, avg_mae_pct: mae, small_sample: n < 30 });
const SCANNERS = {
  ok: true, from: "2026-08-07", to: "2026-11-05", kind: null, version: "spt-outcome-v1", min_sample: 30, note: "MOCK: end-of-day closes.",
  totals: { signals: 60, horizons: {}, small_sample: false },
  by_scanner: [
    { key: "w-breakout", signals: 34, horizons: { t5: hz(30, 1.1, 2.4, -1.2), t20: hz(25, 2.4, 3.2, -1.6) }, small_sample: false },
    { key: "w-volume", signals: 20, horizons: { t5: hz(18, 0.4, 1.8, -1.1) }, small_sample: true },
    { key: "w-gap", signals: 6, horizons: { t5: hz(6, -0.8, 1.0, -2.2) }, small_sample: true },
  ],
  by_category: [], by_score_band: [],
};

// ── MOCK — not real data: the desk's watchlists (routes/watchlists.py) ─────────────────────────────────────────────────────
const LIST = { watchlist_id: "wl-1", name: "MOCK Core", symbol_count: 3, is_starter: false, seeded_from: null };

interface Seen { puts: Row[]; approves: string[]; rejects: Array<{ id: string; body: Row }>; adds: Array<{ id: string; body: Row }>; scannerQueries: URLSearchParams[]; analyticsQueries: URLSearchParams[] }
interface Opts {
  phone?: boolean; overview?: { status: number; body: unknown }; opps?: { status: number; body: unknown }; props?: { status: number; body: unknown } | (() => Row[]);
  analytics?: { status: number; body: unknown }; approve?: { status: number; body: unknown }; put?: { status: number; body: unknown }; lists?: Row[];
}

async function setup(page: Page, o: Opts = {}): Promise<Seen> {
  const seen: Seen = { puts: [], approves: [], rejects: [], adds: [], scannerQueries: [], analyticsQueries: [] };
  let cfg = config();
  if (o.phone) await page.setViewportSize({ width: 390, height: 844 });
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (r) => json(r, []));
  await page.route("**/api/move-odds/**", (r) => json(r, { detail: "feature_not_enabled" }, 403));
  await page.route("**/api/risk/status", (r) => json(r, { kill_switch: false, halted: false, policy_version: "MOCK" }));
  await page.route("**/api/live/**", (r) => json(r, { available: false, reason: "MOCK: feed off", quotes: {}, mode: "expired", session: "closed", stale: true }));
  await page.route("**/api/desk/alerts*", (r) => json(r, { as_of: "2026-11-05", alerts: [] }));
  await page.route("**/api/desk/paper-trades*", (r) => json(r, { as_of: "2026-11-05", checked_through: "2026-11-05", trades: [], summary: { open: 0, closed: 0 }, status: "all" }));

  await page.route(/\/api\/v1\/paper\/accounts(\?|$)/, (r) => json(r, { accounts: [account(cfg)], count: 1 }));
  await page.route(/\/api\/v1\/paper\/accounts\/[^/]+\/config(\?|$)/, (r) => {
    const body = r.request().postDataJSON() as Row;
    seen.puts.push(body);
    if (o.put) return json(r, o.put.body, o.put.status);
    cfg = { ...cfg, ...(body.mode ? { mode: body.mode } : {}), version: Number(cfg.version) + 1 };
    return json(r, { account_id: UID, config: clone(cfg) });
  });
  await page.route(/\/api\/v1\/paper\/overview(\?|$)/, (r) => (o.overview ? json(r, o.overview.body, o.overview.status) : json(r, OVERVIEW())));
  await page.route(/\/api\/v1\/opportunities(\?|$)/, (r) => (o.opps ? json(r, o.opps.body, o.opps.status) : json(r, { ok: true, count: 8, limit: 500, opportunities: OPPS(), score_label: "MOCK" })));
  await page.route(/\/api\/v1\/opportunities\/[^/]+\/(approve|reject)$/, (r) => {
    const [, id, what] = new URL(r.request().url()).pathname.match(/opportunities\/([^/]+)\/(approve|reject)$/) as RegExpMatchArray;
    if (what === "approve") {
      seen.approves.push(id);
      if (o.approve) return json(r, o.approve.body, o.approve.status);
      return json(r, { proposal: prop("prop-1", id, "ICICIBANK", "ORDER_CREATED"), idempotent: false,
        order: { _id: "ord-1", state: "PENDING", order_type: "MARKET", quantity: 35, limit_price: null, time_in_force: "DAY", expires_at: iso(NOW + 5 * 3600e3), reject_reason: null } });
    }
    seen.rejects.push({ id, body: r.request().postDataJSON() as Row });
    return json(r, { proposal: prop("prop-1", id, "ICICIBANK", "USER_REJECTED"), idempotent: false });
  });
  await page.route(/\/api\/v1\/proposals(\?|$)/, (r) => {
    if (o.props && typeof o.props !== "function") return json(r, o.props.body, o.props.status);
    const state = new URL(r.request().url()).searchParams.get("state");
    const items = (typeof o.props === "function" ? o.props : PROPS)().filter((x) => !state || x.state === state);
    return json(r, { items, count: items.length });
  });
  await page.route(/\/api\/v1\/analytics\/account\/[^/?]+(\?|$)/, (r) => {
    seen.analyticsQueries.push(new URL(r.request().url()).searchParams);
    return o.analytics ? json(r, o.analytics.body, o.analytics.status) : json(r, ANALYTICS());
  });
  await page.route(/\/api\/v1\/analytics\/scanners(\?|$)/, (r) => { seen.scannerQueries.push(new URL(r.request().url()).searchParams); return json(r, SCANNERS); });
  await page.route(/\/api\/watchlists(\?|$)/, (r) => json(r, { lists: o.lists ?? [LIST], limits: { max_lists: 10, max_symbols: 100 }, starter_pending: false }));
  await page.route(/\/api\/watchlists\/[^/]+\/symbols$/, (r) => {
    const id = new URL(r.request().url()).pathname.split("/").slice(-2)[0];
    const body = r.request().postDataJSON() as Row;
    seen.adds.push({ id, body });
    return json(r, { added: true, reason: null, stock: { symbol: body.symbol, company_name: null }, watchlist: { ...LIST, symbol_count: 4 } });
  });
  return seen;
}

const params = (page: Page) => new URL(page.url()).searchParams;
const row = (page: Page, id: string) => page.locator(`[data-testid="pv2-opp-row"][data-id="${id}"]`);

async function noSideScroll(page: Page) {
  const o = await page.evaluate(() => {
    const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
    const right = sc ? sc.getBoundingClientRect().right : window.innerWidth;
    const wide = (Array.from(document.querySelectorAll("*")) as HTMLElement[]).filter((el) => {
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.right > right + 1 && !(el.parentElement && el.parentElement.getBoundingClientRect().right > right + 1);
    }).slice(0, 6).map((el) => `${el.tagName.toLowerCase()}[${el.getAttribute("data-testid") ?? ""}] right=${Math.round(el.getBoundingClientRect().right)}`);
    return { doc: document.documentElement.scrollWidth - window.innerWidth, scroll: sc ? sc.scrollWidth - sc.clientWidth : 0, wide: wide.join(", ") };
  });
  expect(o.doc, o.wide).toBeLessThanOrEqual(1);
  expect(o.scroll, o.wide).toBeLessThanOrEqual(1);
}

/** The visible words of a region plus its titles and aria-labels (the compliance lint reads all three). */
async function wordsOf(page: Page, testId: string): Promise<string> {
  return page.getByTestId(testId).first().evaluate((el) => {
    const attrs = Array.from(el.querySelectorAll("[title],[aria-label],[placeholder]")).map((x) => [x.getAttribute("title"), x.getAttribute("aria-label"), x.getAttribute("placeholder")].filter(Boolean).join(" "));
    return `${(el as HTMLElement).innerText}\n${attrs.join("\n")}`;
  });
}

const SUBS: Array<[string, string, string]> = [
  ["overview", "01", "Overview"], ["opportunities", "02", "Scanner opportunities"], ["allocation", "03", "Capital allocation"],
  ["risk", "04", "Portfolio risk"], ["pnl", "05", "Real-time P&L"], ["analytics", "06", "Strategy analytics"],
];

// ── navigation ───────────────────────────────────────────────────────────

test.describe("MOCK — not real data: Paper Trading v2 · navigation and redirects", () => {
  test("PV2-A-01 / A-02 six numbered sub-views in the owner's order; the default is Overview", async ({ page }) => {
    await setup(page);
    await page.goto(`${DESK}?tab=trade&view=paper`);
    await expect.poll(() => params(page).get("sub")).toBe("overview");
    const chips = page.getByTestId("desk-subviews").getByRole("button");
    await expect(chips).toHaveCount(6, SLOW);
    const ids = await chips.evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")));
    expect(ids).toEqual(SUBS.map(([k]) => `desk-sub-${k}`));
    for (const [k, n, label] of SUBS) {
      await expect(page.getByTestId(`desk-sub-${k}-num`)).toHaveText(n);
      await expect(page.getByTestId(`desk-sub-${k}`)).toContainText(label);
    }
    await expect(page.getByTestId("desk-sub-overview")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("desk-trail")).toHaveText(/Paper Trading›Overview$/);
    await expect(page.getByTestId("pv2-overview")).toBeVisible(SLOW);
  });

  test("PV2-A-03 / A-13 each chip sets ?sub= and mounts its view under the shell", async ({ page }) => {
    await setup(page);
    await page.goto(at("overview"));
    const own: Record<string, string> = { overview: "pv2-overview", opportunities: "pv2-opps", analytics: "pv2-analytics" };
    for (const [k] of SUBS) {
      await page.getByTestId(`desk-sub-${k}`).click();
      await expect.poll(() => params(page).get("sub")).toBe(k);
      await expect(page.getByTestId("td-tab")).toHaveAttribute("data-sub", k, SLOW);
      await expect(page.getByTestId("pv2-shell"), k).toBeVisible();
      await expect(page.getByTestId("pv2-status"), k).toHaveAttribute("data-state", "ok", SLOW);
      await expect(page.getByTestId("pv2-account"), k).toBeVisible();
      if (own[k]) await expect(page.getByTestId(own[k])).toBeVisible(SLOW);
    }
  });

  test("PV2-A-04 / A-05 / A-06 old Paper Trading, Trade Desk and Risk Desk URLs open their v2 places", async ({ page }) => {
    await setup(page);
    const cases: Array<[string, string, string, Record<string, string>?]> = [
      ["?tab=trade&view=paper&sub=live", "paper", "pnl"],
      ["?tab=trade&view=paper&sub=journal&trade=pt-1", "paper", "pnl", { trade: "pt-1" }],
      ["?tab=trade&view=paper&sub=settings", "paper", "allocation"],
      ["?tab=trade&view=paper&sub=opportunities", "paper", "opportunities"],
      ["?tab=trade&view=paper&sub=analytics", "paper", "analytics"],
      ["?tab=trade&view=paper&sub=zzz", "paper", "overview"],
      ["?tab=trade&view=open", "paper", "pnl"],
      ["?tab=trade&view=closed", "paper", "pnl"],
      ["?tab=risk&view=overview", "paper", "overview"],
      ["?tab=risk&view=allocation", "paper", "allocation"],
      ["?tab=risk&view=portfolio", "paper", "risk"],
    ];
    for (const [from, view, sub, extra] of cases) {
      await page.goto(`${DESK}${from}`);
      await expect.poll(() => params(page).get("tab"), from).toBe("trade");
      await expect.poll(() => params(page).get("view"), from).toBe(view);
      await expect.poll(() => params(page).get("sub"), from).toBe(sub);
      for (const [k, v] of Object.entries(extra ?? {})) expect(params(page).get(k), `${from} ${k}`).toBe(v);
      await expect(page.getByTestId("td-tab"), from).toHaveAttribute("data-sub", sub, SLOW);
    }
  });

  test("PV2-A-07 the Risk Desk no longer lists Trading overview, Capital allocation or Portfolio risk", async ({ page }) => {
    await setup(page);
    await page.goto(`${DESK}?tab=risk&view=limits`);
    const views = page.getByTestId("desk-views");
    await expect(views.getByTestId("desk-view-limits")).toBeVisible(SLOW);
    const keys = await views.getByRole("button").evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")));
    expect(keys.slice(0, 3)).toEqual(["desk-view-limits", "desk-view-controls", "desk-view-log"]);
    for (const gone of ["overview", "allocation", "portfolio"]) expect(keys).not.toContain(`desk-view-${gone}`);
    await expect(views).not.toContainText(/Trading overview|Capital allocation|Portfolio risk/);
  });

  test("PV2-A-08 the 02 chip shows the count awaiting approval; hidden at 0", async ({ page }) => {
    await setup(page);
    await page.goto(at("overview"));
    await expect(page.getByTestId("desk-sub-opportunities-badge")).toHaveText("3", SLOW);
    await page.unroute(/\/api\/v1\/proposals(\?|$)/);
    await page.route(/\/api\/v1\/proposals(\?|$)/, (r) => json(r, { items: [], count: 0 }));
    await page.reload();
    await expect(page.getByTestId("pv2-overview")).toBeVisible(SLOW);
    await page.waitForTimeout(800);
    await expect(page.getByTestId("desk-sub-opportunities-badge")).toHaveCount(0);
  });
});

// ── shell ────────────────────────────────────────────────────────────────

test.describe("MOCK — not real data: Paper Trading v2 · shell", () => {
  test("PV2-A-10 / A-14 the status strip and the account card", async ({ page }) => {
    await setup(page);
    await page.goto(at("overview"));
    await expect(page.getByTestId("pv2-status")).toHaveAttribute("data-state", "ok", SLOW);
    await expect(page.getByTestId("pv2-status-live")).toHaveText("Live · paper");
    await expect(page.getByTestId("pv2-status-live")).toHaveAttribute("data-tone", "mint");
    await expect(page.getByTestId("pv2-status-session")).toHaveText(/^Market open · \d\d:\d\d IST$/);
    await expect(page.getByTestId("pv2-status-fresh")).toHaveText("Data fresh · 1.2s");
    await expect(page.getByTestId("pv2-status-fresh")).toHaveAttribute("data-tone", "mint");
    await expect(page.getByTestId("pv2-status-policy")).toHaveText("Policy v7");
    await expect(page.getByTestId("pv2-status-ks")).toHaveText("Kill switch · ACTIVE");
    await expect(page.getByTestId("pv2-status-ks")).toHaveAttribute("data-tone", "mint");
    const acct = page.getByTestId("pv2-account");
    await expect(acct).toContainText("Account · Mode");
    await expect(acct).toContainText("Paper account");
    await expect(page.getByTestId("pv2-account-capital")).toHaveText("₹10.00 L");
    await expect(page.getByTestId("pv2-mode-pill")).toHaveAttribute("data-mode", "approval");
    await expect(page.getByTestId("pv2-mode-pill")).toHaveText("Approval mode");
  });

  test("PV2-A-11 stale data is amber, a down feed and a halt are danger", async ({ page }) => {
    await setup(page, { overview: { status: 200, body: OVERVIEW({ status: { last_tick_age_s: 42 } }) } });
    await page.goto(at("overview"));
    await expect(page.getByTestId("pv2-status-fresh")).toHaveText("Data stale · 42s", SLOW);
    await expect(page.getByTestId("pv2-status-fresh")).toHaveAttribute("data-tone", "amber");
    await page.unroute(/\/api\/v1\/paper\/overview(\?|$)/);
    await page.route(/\/api\/v1\/paper\/overview(\?|$)/, (r) => json(r, OVERVIEW({ status: { feed_state: "down", last_tick_age_s: 400,
      kill_switch: { state: "TRIGGERED", entries_blocked: true, text: "MOCK: daily loss limit reached" } } })));
    await page.reload();
    await expect(page.getByTestId("pv2-status-fresh")).toHaveText("Feed down", SLOW);
    await expect(page.getByTestId("pv2-status-fresh")).toHaveAttribute("data-tone", "danger");
    await expect(page.getByTestId("pv2-status-live")).toHaveText("Paper");
    await expect(page.getByTestId("pv2-status-ks")).toHaveText("Trading halted");
    await expect(page.getByTestId("pv2-status-ks")).toHaveAttribute("data-tone", "danger");
    await expect(page.getByTestId("pv2-status-ks")).toHaveAttribute("title", "MOCK: daily loss limit reached");
    await page.unroute(/\/api\/v1\/paper\/overview(\?|$)/);
    await page.route(/\/api\/v1\/paper\/overview(\?|$)/, (r) => json(r, OVERVIEW({ status: { feed_state: "closed", session: "closed", last_tick_age_s: 4000 } })));
    await page.reload();
    await expect(page.getByTestId("pv2-status-fresh")).toHaveText("Feed closed · last tick 1h 06m ago", SLOW);
    await expect(page.getByTestId("pv2-status-fresh")).toHaveAttribute("data-tone", "plain");
    await expect(page.getByTestId("pv2-status-session")).toHaveText(/^Market closed · \d\d:\d\d IST$/);
  });

  test("PV2-A-12 an unreadable overview: the strip says so, no state is invented", async ({ page }) => {
    await setup(page, { overview: { status: 500, body: { detail: "MOCK: overview failed" } } });
    await page.goto(at("opportunities"));
    await expect(page.getByTestId("pv2-status")).toHaveAttribute("data-state", "error", SLOW);
    await expect(page.getByTestId("pv2-status-unknown")).toHaveText("Status unknown");
    await expect(page.getByTestId("pv2-status")).toContainText("could not be read");
    for (const id of ["pv2-status-live", "pv2-status-fresh", "pv2-status-policy", "pv2-status-ks"]) await expect(page.getByTestId(id)).toHaveCount(0);
  });

  test("PV2-A-15 / A-16 the mode chooser: Tracking PUTs; Auto asks first", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(at("analytics"));
    await page.getByTestId("pv2-mode-pill").click();
    const ch = page.getByTestId("pv2-mode-chooser");
    await expect(ch).toBeVisible();
    for (const m of ["off", "tracking", "approval", "auto"]) await expect(page.getByTestId(`pv2-mode-${m}`)).toBeVisible();
    await expect(page.getByTestId("pv2-mode-approval")).toHaveAttribute("aria-pressed", "true");
    await page.getByTestId("pv2-mode-tracking").click();
    await expect.poll(() => seen.puts.length).toBe(1);
    expect(seen.puts[0]).toEqual({ mode: "tracking", expected_version: 3 });
    await expect(page.getByTestId("pv2-mode-pill")).toHaveAttribute("data-mode", "tracking", SLOW);
    await page.getByTestId("pv2-mode-auto").click();
    await expect(page.getByTestId("pv2-mode-confirm")).toBeVisible();
    await page.getByTestId("pv2-mode-confirm-no").click();
    await expect(page.getByTestId("pv2-mode-confirm")).toHaveCount(0);
    expect(seen.puts.length).toBe(1);
    await page.getByTestId("pv2-mode-auto").click();
    await page.getByTestId("pv2-mode-confirm-yes").click();
    await expect.poll(() => seen.puts.length).toBe(2);
    expect(seen.puts[1]).toEqual({ mode: "auto", expected_version: 4 });
    await expect(page.getByTestId("pv2-mode-pill")).toHaveAttribute("data-mode", "auto", SLOW);
  });

  test("PV2-A-17 a refused mode change is said, not claimed as saved", async ({ page }) => {
    await setup(page, { put: { status: 409, body: { detail: { code: "concurrent_change", message: "MOCK: the config changed" } } } });
    await page.goto(at("overview"));
    await page.getByTestId("pv2-mode-pill").click();
    await page.getByTestId("pv2-mode-off").click();
    await expect(page.getByTestId("pv2-mode-error")).toContainText("changed elsewhere", SLOW);
    await expect(page.getByTestId("pv2-mode-saved")).toHaveCount(0);
    await expect(page.getByTestId("pv2-mode-pill")).toHaveAttribute("data-mode", "approval");
  });
});

// ── 01 Overview ──────────────────────────────────────────────────────────

test.describe("MOCK — not real data: Paper Trading v2 · 01 Overview", () => {
  test("PV2-A-20 / A-22 the synthesis with its amber concentration, and the prose line", async ({ page }) => {
    await setup(page);
    await page.goto(at("overview"));
    const head = page.getByTestId("pv2-ov-head");
    await expect(page.getByTestId("pv2-ov-head-eyebrow")).toHaveText("Trading overview", SLOW);
    await expect(page.getByTestId("pv2-ov-head-synthesis")).toHaveText("3 setups cleared the risk engine today — but Banks already carry 42% of open risk.");
    await expect(page.getByTestId("pv2-ov-head-synthesis-hi")).toHaveText("Banks already carry 42% of open risk");
    await expect(page.getByTestId("pv2-ov-head-prose")).toHaveText("14 scanner signals consolidated into 6 opportunities. 1 is blocked by the risk engine and 1 is reduced to fit the risk budget.");
    await expect(head).toBeVisible();
  });

  test("PV2-A-21 no concentration warning: the short sentence, singular", async ({ page }) => {
    await setup(page, { overview: { status: 200, body: OVERVIEW({ headline: { setups_cleared: 1, worst_concentration: null, blocked: 0, reduced: 2 } }) } });
    await page.goto(at("overview"));
    await expect(page.getByTestId("pv2-ov-head-synthesis")).toHaveText("1 setup cleared the risk engine today.", SLOW);
    await expect(page.getByTestId("pv2-ov-head-synthesis-hi")).toHaveCount(0);
    await expect(page.getByTestId("pv2-ov-head-prose")).toHaveText("14 scanner signals consolidated into 6 opportunities. None is blocked by the risk engine and 2 are reduced to fit the risk budget.");
  });

  test("PV2-A-23 / A-24 six KPI tiles from the body; a null figure is a dash", async ({ page }) => {
    await setup(page);
    await page.goto(at("overview"));
    const k = (id: string) => page.getByTestId(`pv2-kpi-${id}`);
    await expect(k("equity").getByTestId("pv2-kpi-equity-value")).toHaveText("₹10.04 L", SLOW);
    await expect(k("equity").getByTestId("pv2-kpi-equity-sub")).toHaveText("start ₹10.00 L");
    await expect(page.getByTestId("pv2-kpi-day-value")).toHaveText("+₹4,200");
    await expect(k("day")).toHaveAttribute("data-tone", "mint");
    await expect(page.getByTestId("pv2-kpi-day-sub")).toHaveText("limit −2% · used 0%");
    await expect(page.getByTestId("pv2-kpi-deployed-value")).toHaveText("₹3.12 L");
    await expect(page.getByTestId("pv2-kpi-deployed-sub")).toHaveText("31.1% · cash ₹6.92 L");
    await expect(page.getByTestId("pv2-kpi-risk-value")).toHaveText("2.6%");
    await expect(k("risk")).toHaveAttribute("data-tone", "amber");                 // 2.6 of 3 = 87 % > 80 %
    await expect(page.getByTestId("pv2-kpi-risk-sub")).toHaveText("of 3% budget");
    await expect(page.getByTestId("pv2-kpi-drawdown-value")).toHaveText("0.42%");
    await expect(page.getByTestId("pv2-kpi-drawdown-sub")).toHaveText("warning at 5%");
    await expect(page.getByTestId("pv2-kpi-positions-value")).toHaveText("4 / 10");
    await expect(page.getByTestId("pv2-kpi-positions-sub")).toHaveText("1 pending order");
    await page.unroute(/\/api\/v1\/paper\/overview(\?|$)/);
    await page.route(/\/api\/v1\/paper\/overview(\?|$)/, (r) => json(r, OVERVIEW({ kpis: { equity_rs: null, day_pnl_rs: -1500, open_risk_pct: 1 } })));
    await page.reload();
    await expect(page.getByTestId("pv2-kpi-equity-value")).toHaveText("—", SLOW);
    await expect(page.getByTestId("pv2-kpi-day-value")).toHaveText("−₹1,500");
    await expect(k("day")).toHaveAttribute("data-tone", "danger");
    await expect(k("risk")).toHaveAttribute("data-tone", "");
  });

  test("PV2-A-25 the pipeline: six stages, counts and bars relative to the signals", async ({ page }) => {
    await setup(page);
    await page.goto(at("overview"));
    const rows = page.getByTestId("pv2-pipeline-row");
    await expect(rows).toHaveCount(6, SLOW);
    expect(await rows.evaluateAll((els) => els.map((e) => e.getAttribute("data-stage")))).toEqual(["signals", "opportunities", "qualified", "risk_approved", "orders_filled", "open_positions"]);
    await expect(page.getByTestId("pv2-pipeline-count")).toHaveText(["14", "6", "4", "3", "2", "2"]);
    await expect(page.getByTestId("pv2-pipeline-bar").nth(0)).toHaveAttribute("data-pct", "100.0");
    await expect(page.getByTestId("pv2-pipeline-bar").nth(1)).toHaveAttribute("data-pct", "42.9");
    await expect(page.getByTestId("pv2-pipeline")).toContainText("A scanner signal is not a trade. Each stage can reject, expire or reduce.");
  });

  test("PV2-A-26 risk warnings: danger first, mono code and IST time, the mint feed line last", async ({ page }) => {
    await setup(page);
    await page.goto(at("overview"));
    const w = page.getByTestId("pv2-warning");
    await expect(w).toHaveCount(3, SLOW);
    expect(await w.evaluateAll((els) => els.map((e) => e.getAttribute("data-level")))).toEqual(["danger", "amber", "mint"]);
    await expect(page.getByTestId("pv2-warning-title").first()).toHaveText("HDFCBANK refused: ten positions are open · HDFCBANK");
    await expect(page.getByTestId("pv2-warning-meta").first()).toHaveText("RISK_REJECTED · 11:02");
    await expect(page.getByTestId("pv2-warning-title").last()).toHaveText("All feeds healthy");
  });

  test("PV2-A-27 empty states and a failing read", async ({ page }) => {
    await setup(page, { overview: { status: 200, body: OVERVIEW({ warnings: [], pipeline: [] }) } });
    await page.goto(at("overview"));
    await expect(page.getByTestId("pv2-warnings-none")).toHaveText("No risk warning was raised today.", SLOW);
    await expect(page.getByTestId("pv2-pipeline-empty")).toContainText("sent no pipeline counts");
    await page.unroute(/\/api\/v1\/paper\/overview(\?|$)/);
    await page.route(/\/api\/v1\/paper\/overview(\?|$)/, (r) => json(r, { detail: "MOCK: down" }, 500));
    await page.reload();
    await expect(page.getByTestId("pv2-ov-error")).toBeVisible(SLOW);
    await expect(page.getByTestId("pv2-kpi-equity")).toHaveCount(0);
    await expect(page.getByTestId("pv2-pipeline")).toHaveCount(0);
  });
});

// ── 02 Scanner opportunities ─────────────────────────────────────────────

test.describe("MOCK — not real data: Paper Trading v2 · 02 Scanner opportunities", () => {
  test("PV2-A-30 / A-31 / A-32 header, table, decision pills and the ranking", async ({ page }) => {
    await setup(page);
    await page.goto(at("opportunities"));
    await expect(page.getByTestId("pv2-opps-head-eyebrow")).toHaveText("Scanner opportunities", SLOW);
    await expect(page.getByTestId("pv2-opps-head-title")).toHaveText("Consolidated setups, ranked after the risk engine has spoken.");
    const table = page.getByTestId("pv2-opps-table");
    await expect(table.getByRole("columnheader")).toHaveText(["Symbol", "Signals", "Opp score", "Entry", "R:R", "Risk ₹", "Decision"]);
    // Awaiting your approval first (by score: TCS 80, ICICIBANK 72, INFY 65), then by score; the expired WIPRO is not listed.
    const ids = await page.getByTestId("pv2-opp-row").evaluateAll((els) => els.map((e) => e.getAttribute("data-id")));
    expect(ids).toEqual(["opp-2", "opp-1", "opp-3", "opp-8", "opp-4", "opp-6", "opp-5"]);
    await expect(page.getByTestId("pv2-opps-hidden")).toHaveText("1 expired or validation-rejected opportunity is not listed.");
    const want: Record<string, [string, string]> = {
      "opp-1": ["APPROVE", "mint"], "opp-2": ["APPROVE REDUCED", "amber"], "opp-3": ["CONDITIONAL", "indigo"], "opp-4": ["BLOCKED", "danger"],
      "opp-5": ["WATCHLIST", "plain"], "opp-6": ["TRACKED", "plain"], "opp-8": ["ORDER CREATED", "mint"],
    };
    for (const [id, [label, tone]] of Object.entries(want)) {
      const d = row(page, id).getByTestId("pv2-opp-decision");
      await expect(d, id).toHaveText(label);
      await expect(d, id).toHaveAttribute("data-tone", tone);
    }
    const r1 = row(page, "opp-1");
    await expect(r1.getByTestId("pv2-opp-symbol")).toHaveText("ICICIBANK");
    await expect(r1).toContainText("LONG · EQ");
    await expect(row(page, "opp-6")).toContainText("LONG · F&O");
    await expect(r1.getByTestId("pv2-opp-signals")).toHaveText("2 sources");
    await expect(r1.getByTestId("pv2-opp-score")).toHaveText("72");
    await expect(r1.getByTestId("pv2-opp-entry")).toHaveText("₹1,410.00");
    await expect(r1.getByTestId("pv2-opp-rr")).toHaveText("4.0:1");
    await expect(r1.getByTestId("pv2-opp-risk")).toHaveText("₹1,269");
    await expect(page.getByTestId("pv2-opps-foot")).toHaveText("Opportunity score rates setup quality. It is not a probability of profit and scanner scores are never summed.");
  });

  test("PV2-A-33 the detail: id and status, reason, signals, plan, sizing and every risk check", async ({ page }) => {
    await setup(page);
    await page.goto(at("opportunities"));
    await expect(row(page, "opp-2")).toHaveAttribute("data-selected", "true", SLOW);        // the first row is selected
    await expect(page.getByTestId("pv2-size-qty")).toHaveText("20");
    await expect(page.getByTestId("pv2-size-note")).toHaveText("reduced from 35");
    await expect(page.getByTestId("pv2-detail-reason")).toHaveText("MOCK: reduced from 35 to 20 shares to fit the open-risk budget");
    await row(page, "opp-1").click();
    await expect(row(page, "opp-1")).toHaveAttribute("data-selected", "true");
    const d = page.getByTestId("pv2-opp-detail");
    await expect(page.getByTestId("pv2-detail-id")).toHaveText("opp-1 · AWAITING USER APPROVAL");
    await expect(page.getByTestId("pv2-detail-symbol")).toHaveText("ICICIBANK");
    await expect(page.getByTestId("pv2-detail-decision")).toHaveText("APPROVE");
    await expect(page.getByTestId("pv2-detail-reason")).toHaveText("Cleared every risk check at full size.");
    await expect(d).toContainText("Supporting signals · 2");
    await expect(page.getByTestId("pv2-detail-signal")).toHaveCount(2);
    await expect(page.getByTestId("pv2-detail-signal").first()).toContainText("MOCK Breakout 52w");
    await expect(page.getByTestId("pv2-detail-signal").first()).toContainText("09:35 · score 81");
    await expect(page.getByTestId("pv2-plan-entry-value")).toHaveText("₹1,410.00");
    await expect(page.getByTestId("pv2-plan-stop-value")).toHaveText("₹1,374.90");
    await expect(page.getByTestId("pv2-plan-stop")).toHaveAttribute("data-tone", "danger");
    await expect(page.getByTestId("pv2-plan-t1")).toHaveAttribute("data-tone", "mint");
    await expect(page.getByTestId("pv2-plan-t1-value")).toHaveText("₹1,480.00");
    await expect(page.getByTestId("pv2-plan-t2-value")).toHaveText("₹1,550.00");
    await expect(page.getByTestId("pv2-size-qty")).toHaveText("35");
    await expect(page.getByTestId("pv2-size-note")).toHaveText("full size");
    await expect(page.getByTestId("pv2-size-capital")).toHaveText("₹49,350");
    await expect(page.getByTestId("pv2-size-risk")).toHaveText("₹1,269");
    const checks = page.getByTestId("pv2-check");
    await expect(checks).toHaveCount(9);
    expect(await checks.evaluateAll((els) => els.map((e) => e.getAttribute("data-status")))).toEqual(["pass", "pass", "pass", "pass", "pass", "pass", "pass", "pass", "warn"]);
    await expect(checks.nth(4)).toContainText("Reward:risk to T2");
    await expect(checks.nth(4)).toContainText("T2 3.99 vs 1.5");
    await expect(checks.nth(8)).toContainText("MOCK: Banks at 18% of a 20% cap");
    await expect(checks.nth(8).locator('[data-kind="warn"]')).toHaveText("!");
    await expect(page.getByTestId("pv2-detail-foot")).toHaveText("Approval expires if price leaves the entry range, data goes stale or policy changes.");
    // A blocked one: quantity 0 "would be 20", the failed check with its reason, the hard-limit footnote.
    await row(page, "opp-4").click();
    await expect(page.getByTestId("pv2-detail-id")).toHaveText("opp-4 · NO ORDER");
    await expect(page.getByTestId("pv2-size-qty")).toHaveText("0");
    await expect(page.getByTestId("pv2-size-note")).toHaveText("would be 20");
    const failed = page.locator('[data-testid="pv2-check"][data-status="fail"]');
    await expect(failed).toHaveCount(1);
    await expect(failed).toContainText("Open positions (10) are at the limit of 10.");
    await expect(failed.locator('[data-kind="fail"]')).toHaveText("×");
    await expect(page.getByTestId("pv2-detail-foot")).toHaveText("The risk engine has the final say. User approval cannot override a hard limit.");
  });

  test("PV2-A-34 Approve paper trade POSTs and the row reads ORDER CREATED", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(at("opportunities"));
    await row(page, "opp-1").click();
    const ap = page.getByTestId("pv2-approve");
    await expect(ap).toHaveText("Approve paper trade", SLOW);
    await expect(ap).toBeEnabled();
    await ap.click();
    await expect.poll(() => seen.approves).toEqual(["opp-1"]);
    await expect(page.getByTestId("pv2-approve-result")).toContainText("Paper order MARKET for 35 shares · PENDING", SLOW);
    await expect(row(page, "opp-1").getByTestId("pv2-opp-decision")).toHaveText("ORDER CREATED");
    await expect(row(page, "opp-1").getByTestId("pv2-opp-decision")).toHaveAttribute("data-tone", "mint");
    await expect(page.getByTestId("pv2-detail-id")).toHaveText("opp-1 · ORDER CREATED");
    await expect(ap).toHaveText("Done · order created");
    await expect(ap).toBeDisabled();
  });

  test("PV2-A-35 a refused approval shows the code and message; no success", async ({ page }) => {
    await setup(page, { approve: { status: 409, body: { detail: { code: "approval_expired", message: "MOCK: the approval window passed", reason_codes: ["approval_expired"] } } } });
    await page.goto(at("opportunities"));
    await row(page, "opp-1").click();
    await page.getByTestId("pv2-approve").click();
    const e = page.getByTestId("pv2-approve-error");
    await expect(e).toHaveAttribute("data-code", "approval_expired", SLOW);
    await expect(e).toContainText("MOCK: the approval window passed");
    await expect(page.getByTestId("pv2-approve-result")).toHaveCount(0);
    await expect(row(page, "opp-1").getByTestId("pv2-opp-decision")).toHaveText("APPROVE");
  });

  test("PV2-A-36 a conditional proposal reads 'Arm conditional order' with its condition", async ({ page }) => {
    await setup(page);
    await page.goto(at("opportunities"));
    await row(page, "opp-3").click();
    await expect(page.getByTestId("pv2-approve")).toHaveText("Arm conditional order", SLOW);
    await expect(page.getByTestId("pv2-detail-reason")).toHaveText("MOCK: enter only above ₹1,600 on a 15-minute close");
  });

  test("PV2-A-37 Reject asks for a one-line reason, then POSTs it", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(at("opportunities"));
    await row(page, "opp-1").click();
    await page.getByTestId("pv2-reject").click();
    await page.getByTestId("pv2-reject-confirm").click();
    await expect(page.getByTestId("pv2-reject-need")).toHaveText("A one-line reason is needed to reject.");
    expect(seen.rejects).toEqual([]);
    await page.getByTestId("pv2-reject-reason").fill("MOCK: results on Friday");
    await page.getByTestId("pv2-reject-confirm").click();
    await expect.poll(() => seen.rejects).toEqual([{ id: "opp-1", body: { reason: "MOCK: results on Friday" } }]);
    await expect(row(page, "opp-1").getByTestId("pv2-opp-decision")).toHaveText("USER REJECTED", SLOW);
    await expect(page.getByTestId("pv2-approve")).toBeDisabled();
  });

  test("PV2-A-38 Add to watchlist adds to the first list; with no list it says where to make one", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(at("opportunities"));
    await row(page, "opp-5").click();
    await page.getByTestId("pv2-watchlist").click();
    await expect.poll(() => seen.adds).toEqual([{ id: "wl-1", body: { symbol: "SBIN" } }]);
    await expect(page.getByTestId("pv2-watchlist-done")).toHaveText("Added SBIN to MOCK Core.", SLOW);
    await expect(row(page, "opp-5").getByTestId("pv2-opp-decision")).toHaveText("WATCHLISTED");
    await expect(row(page, "opp-5").getByTestId("pv2-opp-decision")).toHaveAttribute("data-tone", "mint");
    await page.unroute(/\/api\/watchlists(\?|$)/);
    await page.route(/\/api\/watchlists(\?|$)/, (r) => json(r, { lists: [], limits: { max_lists: 10, max_symbols: 100 }, starter_pending: false }));
    await page.reload();
    await row(page, "opp-5").click();
    await expect(page.getByTestId("pv2-watchlist-none")).toContainText("You have no watchlist yet", SLOW);
    await expect(page.getByTestId("pv2-watchlist")).toBeDisabled();
  });

  test("PV2-A-39 Approve is disabled (opacity .35) for BLOCKED, WATCHLIST, TRACKED and after an action", async ({ page }) => {
    await setup(page);
    await page.goto(at("opportunities"));
    for (const id of ["opp-4", "opp-5", "opp-6", "opp-8"]) {
      await row(page, id).click();
      const ap = page.getByTestId("pv2-approve");
      await expect(ap, id).toBeDisabled(SLOW);
      await expect(ap, id).toHaveCSS("opacity", "0.35");
    }
    await row(page, "opp-6").click();
    await expect(page.getByTestId("pv2-detail-reason")).toContainText("cash longs for now");
    await expect(page.getByTestId("pv2-approve-why")).toHaveText("Tracked only: no paper order for this one.");
    await row(page, "opp-8").click();
    await expect(page.getByTestId("pv2-approve")).toHaveText("Done · order created");
  });

  test("PV2-A-40 nothing to list says so; both reads failing shows the problem", async ({ page }) => {
    await setup(page, { opps: { status: 200, body: { ok: true, count: 0, limit: 500, opportunities: [] } }, props: () => [] });
    await page.goto(at("opportunities"));
    await expect(page.getByTestId("pv2-opps-empty")).toContainText("No scanner opportunity is open", SLOW);
    await expect(page.getByTestId("pv2-opp-row")).toHaveCount(0);
    await page.unroute(/\/api\/v1\/opportunities(\?|$)/);
    await page.unroute(/\/api\/v1\/proposals(\?|$)/);
    await page.route(/\/api\/v1\/opportunities(\?|$)/, (r) => json(r, { detail: "MOCK: down" }, 500));
    await page.route(/\/api\/v1\/proposals(\?|$)/, (r) => json(r, { detail: "MOCK: down" }, 500));
    await page.reload();
    await expect(page.getByTestId("pv2-opps-error")).toBeVisible(SLOW);
  });
});

// ── 06 Strategy analytics ────────────────────────────────────────────────

test.describe("MOCK — not real data: Paper Trading v2 · 06 Strategy analytics", () => {
  test("PV2-A-50 / A-51 the synthesis and the KPI tiles; the 90-day window is asked for", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(at("analytics"));
    await expect(page.getByTestId("pv2-an-head-eyebrow")).toHaveText("Strategy analytics · last 90 days", SLOW);
    await expect(page.getByTestId("pv2-an-head-synthesis")).toHaveText("Breakout setups earn the edge. Pullback setups lack sample size to scale.");
    expect(seen.analyticsQueries[0]?.get("days")).toBe("90");
    expect(seen.scannerQueries[0]?.get("from")).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    await expect(page.getByTestId("pv2-an-trades-value")).toHaveText("43");
    await expect(page.getByTestId("pv2-an-trades-sub")).toHaveText("closed");
    await expect(page.getByTestId("pv2-an-winrate-value")).toHaveText("53.5%");
    await expect(page.getByTestId("pv2-an-winrate-sub")).toHaveText("avg win +1.42R");
    await expect(page.getByTestId("pv2-an-expectancy-value")).toHaveText("+0.31R");
    await expect(page.getByTestId("pv2-an-expectancy-sub")).toHaveText("net of costs");
    await expect(page.getByTestId("pv2-an-pf-value")).toHaveText("1.62");
    await expect(page.getByTestId("pv2-an-dd-value")).toHaveText("3.10%");
    await expect(page.getByTestId("pv2-an-dd-sub")).toHaveText("peak to trough");
    await expect(page.getByTestId("pv2-an-ratios-value")).toHaveText("1.21 / 1.87");
  });

  test("PV2-A-52 Sharpe / Sortino null: a dash with the API's reason", async ({ page }) => {
    await setup(page, { analytics: { status: 200, body: ANALYTICS({ sharpe: null, sortino: null, ratio_reason: "MOCK: fewer than 20 days of P&L (12)" }) } });
    await page.goto(at("analytics"));
    await expect(page.getByTestId("pv2-an-ratios-value")).toHaveText("—", SLOW);
    await expect(page.getByTestId("pv2-an-ratios-sub")).toHaveText("MOCK: fewer than 20 days of P&L (12)");
  });

  test("PV2-A-53 scanner attribution with the evidence pills", async ({ page }) => {
    await setup(page);
    await page.goto(at("analytics"));
    const rows = page.getByTestId("pv2-an-attr-row");
    await expect(rows).toHaveCount(3, SLOW);
    await expect(page.getByTestId("pv2-an-attr").getByRole("columnheader")).toHaveText(["Scanner", "Signals", "T+5", "T+20", "MFE / MAE", "Evidence"]);
    await expect(rows.nth(0).getByTestId("pv2-an-attr-t5")).toHaveText("+1.10%");
    await expect(rows.nth(0).getByTestId("pv2-an-attr-t20")).toHaveText("+2.40%");
    await expect(rows.nth(0).getByTestId("pv2-an-attr-mfe")).toHaveText("+3.2% / −1.6%");
    await expect(rows.nth(1).getByTestId("pv2-an-attr-t20")).toHaveText("—");
    const ev = page.getByTestId("pv2-an-attr-evidence");
    await expect(ev).toHaveText(["Sufficient", "Building", "Low sample"]);
    expect(await ev.evaluateAll((els) => els.map((e) => e.getAttribute("data-tone")))).toEqual(["mint", "amber", "danger"]);
  });

  test("PV2-A-54 / A-55 certification criteria and expectancy by regime", async ({ page }) => {
    await setup(page);
    await page.goto(at("analytics"));
    const cert = page.getByTestId("pv2-an-cert");
    await expect(cert).toContainText("Certification · Breakout", SLOW);
    await expect(page.getByTestId("pv2-an-cert-state")).toHaveText("Not certified");
    const c = page.getByTestId("pv2-an-criterion");
    await expect(c).toHaveCount(5);
    expect(await c.evaluateAll((els) => els.map((e) => e.getAttribute("data-status")))).toEqual(["fail", "pass", "pass", "not_measured", "warn"]);
    await expect(page.getByTestId("pv2-an-criterion-value")).toHaveText(["34 of 50", "+0.42R", "1.9", "not measured", "1 of 2"]);
    await expect(c.nth(3).locator('[data-kind="not_measured"]')).toHaveText("!");
    await expect(cert).toContainText("Risk allocation increases only after every criterion passes. A winning streak alone does not qualify.");
    const reg = page.getByTestId("pv2-an-regime-row");
    expect(await reg.evaluateAll((els) => els.map((e) => e.getAttribute("data-regime")))).toEqual(["uptrend", "sideways", "downtrend"]);
    await expect(page.getByTestId("pv2-an-regime-value")).toHaveText(["+0.52R", "+0.08R", "−0.35R"]);
  });

  test("PV2-A-56 no closed trade: nothing to measure, no figure invented", async ({ page }) => {
    await setup(page, { analytics: { status: 200, body: { days: 90, trades: 0, wins: 0, losses: 0, win_rate_pct: null, avg_win_r: null, avg_loss_r: null, expectancy_r: null,
      profit_factor: null, max_drawdown_pct: null, sharpe: null, sortino: null, ratio_reason: "MOCK: no closed trade", by_setup: [], by_regime: [], certification: [], basis: "MOCK", notes: [] } } });
    await page.goto(at("analytics"));
    await expect(page.getByTestId("pv2-an-head-synthesis")).toHaveText("No closed paper trade in the last 90 days, so there is no edge to measure yet.", SLOW);
    await expect(page.getByTestId("pv2-an-trades-value")).toHaveText("0");
    for (const id of ["winrate", "expectancy", "pf", "dd", "ratios"]) await expect(page.getByTestId(`pv2-an-${id}-value`), id).toHaveText("—");
    await expect(page.getByTestId("pv2-an-cert-none")).toBeVisible();
    await expect(page.getByTestId("pv2-an-regime-none")).toBeVisible();
  });
});

// ── wording and phone ────────────────────────────────────────────────────

test.describe("MOCK — not real data: Paper Trading v2 · wording and 390 px", () => {
  test("PV2-A-60 no recommend / pick / suggest in the shell, Overview, Scanner opportunities or Strategy analytics", async ({ page }) => {
    await setup(page);
    await page.goto(at("overview"));
    await expect(page.getByTestId("pv2-kpi-equity")).toBeVisible(SLOW);
    await page.getByTestId("pv2-mode-pill").click();
    for (const id of ["desk-subviews", "pv2-shell", "pv2-overview"]) expect(await wordsOf(page, id), id).not.toMatch(BANNED);
    await page.goto(at("opportunities"));
    for (const id of ["opp-2", "opp-4", "opp-6"]) {
      await row(page, id).click();
      expect(await wordsOf(page, "pv2-opps"), id).not.toMatch(BANNED);
    }
    await page.goto(at("analytics"));
    await expect(page.getByTestId("pv2-an-attr-row").first()).toBeVisible(SLOW);
    expect(await wordsOf(page, "pv2-analytics")).not.toMatch(BANNED);
  });

  test("PV2-A-61 390 px: no sideways scroll on the three views; the opportunities table scrolls in its card; 06 reads 'Analytics'", async ({ page }) => {
    await setup(page, { phone: true });
    await page.goto(at("analytics"));
    await expect(page.getByTestId("desk-sub-analytics")).toHaveText("06Analytics", SLOW);       // the row overflows at 390 px (§1)
    for (const sub of ["overview", "opportunities", "analytics"]) {
      await page.goto(at(sub));
      await expect(page.getByTestId("pv2-shell"), sub).toBeVisible(SLOW);
      await expect(page.getByTestId(sub === "overview" ? "pv2-kpi-equity" : sub === "opportunities" ? "pv2-opp-detail" : "pv2-an-attr-row").first(), sub).toBeVisible(SLOW);
      await page.waitForTimeout(400);
      await noSideScroll(page);
    }
    await page.goto(at("opportunities"));
    const t = page.getByTestId("pv2-opps-table");
    await expect(t).toBeVisible(SLOW);
    const s = await t.evaluate((el) => ({ sw: el.scrollWidth, cw: el.clientWidth }));
    expect(s.sw).toBeGreaterThan(s.cw);
    await page.getByTestId("pv2-mode-pill").click();
    await expect(page.getByTestId("pv2-mode-chooser")).toBeVisible();
    await noSideScroll(page);
  });
});
