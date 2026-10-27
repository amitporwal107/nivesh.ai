/**
 * Phase 3 decision cards — UI-1 … UI-16 of test_reports/p3_decision_cards_TESTCASES.md.
 *
 * The plans, the stored AI watchlist day, the Strategy Builder's answer, GET /api/desk/trade-plans/{id} (with the
 * universal risk service's REAL allow / reduce / block decisions) and GET /api/risk/profile all come from
 * `contract-decision-card.json`, which backend/tests/test_decision_card_contract.py rebuilds from the REAL routes and
 * compares (cash: MOCK — not real data, the RELIANCE-like world of backend/tests/test_strategy_plan.py, sized with capital
 * 10,00,000 and risk 0.5%; F&O: the REAL 2026-10-21 staging capture desk-strategy-top.json). Anything else below is an
 * inline MOCK in the real route's shape, labelled where it is made. Expected figures are worked out from the payloads
 * here, never copied from the screen. Mocked APIs, production build (pw.copilot-app.config.ts).
 */
import { test, expect, type Locator, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", name), "utf-8"));
const CARD = load("contract-decision-card.json");
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
const DESK = "/v5/app/trader/desk";
const SCANNER = `${DESK}?tab=scanner`;
const WATCHLIST = "/v5/app/page/watchlist?wl=all";
const SLOW = { timeout: 15_000 };
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

// ── the plans, as the routes send them ───────────────────────────────────
const IDEA = CARD.cash.ideas_response.ideas[0];
const CASH = IDEA.trade_plan;
const SYM: string = IDEA.symbol;
const FNO_GET = CARD.fno.trade_plan_response;
const FNO = FNO_GET.plan;
const BANK_ON_BOARD = CARD.fno.top_response.classes.index_options.ideas.find((i: { underlying: string }) => i.underlying === "BANKNIFTY");
const EQUITY: number = CARD.risk_profile.live.equity.equity_rs;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

// ── what the card must show, worked out from the plan (en-IN, two decimals) ──
const n2 = (n: number) => new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n);
const rs = (n: number) => `₹${n2(n)}`;
const targets = (tp: { targets: Array<{ price: number; r_multiple: number }> }) => tp.targets.map((t) => `${rs(t.price)} (${n2(t.r_multiple)}R)`).join(" · ");
const int = (n: number) => new Intl.NumberFormat("en-IN").format(n);
/** The account's size, risk and costs: the route's `account_size` (the risk service's own sizing), never the plan's own. */
const sized = (a: { quantity: number | null; lots: number | null; lot_size: number | null; estimated_risk_rs: { total: number; costs: number }; risk_pct_of_equity: number }) => ({
  size: a.lots != null ? `Size ${a.lots} lot${a.lots === 1 ? "" : "s"} × ${a.lot_size}` : `Size ${int(a.quantity as number)} shares`,
  risk: `Risk ${rs(a.estimated_risk_rs.total)} (${n2(a.risk_pct_of_equity)}% of equity)`,
  costs: `Est. costs ${rs(a.estimated_risk_rs.costs)}`,
});
const EXPECT_CASH = {
  entry: `Entry ${rs(CASH.entry.price)} (at the close)`,
  stop: `Stop ${rs(CASH.stop.price)} (${CASH.stop.atr_multiple}×ATR below ${CASH.stop.measured_from})`,
  targets: `Targets ${targets(CASH)}`,
  ...sized(CARD.cash.trade_plan_response.account_size),
};
const EXPECT_FNO = {
  entry: `Entry net premium ${rs(Math.abs(FNO.entry.net_premium_rs))} debit (at the premiums)`,
  stop: `Stop ${rs(FNO.stop.price)} (underlying invalidation)`,
  targets: `Targets ${targets(FNO)}`,
  ...sized(FNO_GET.account_size),
};
const LINE = ["entry", "stop", "targets", "size", "risk", "costs"] as const;

/** Waits until the card has read its plan from GET /api/desk/trade-plans/{id} (status, sizing, risk decision). */
const ready = (card: Locator) => expect(card).toHaveAttribute("data-store", "read", SLOW);

async function lineOf(card: Locator) {
  await ready(card);
  const out: Record<string, string> = {};
  for (const k of LINE) out[k] = (await card.getByTestId(`dc-${k}`).innerText()).replace(/\s+/g, " ").trim();
  return out;
}

// ── the mocks ─────────────────────────────────────────────────────────────
interface Opts {
  ideas?: unknown; top?: unknown; builder?: unknown; day?: unknown; plans?: Record<string, { status: number; body: unknown }>;
  profile?: { status: number; body: unknown }; trades?: unknown; paperStatus?: number[]; phone?: boolean; killSwitch?: boolean;
}
interface Seen { paper: Array<Record<string, unknown>>; keys: Array<string | undefined>; planReads: string[] }

/** The plan route by id: the fixture's own answers, unless a case overrides one. */
function planAnswers(o: Opts): Record<string, { status: number; body: unknown }> {
  return { [CASH.plan_id]: { status: 200, body: CARD.cash.trade_plan_response }, [FNO.plan_id]: { status: 200, body: FNO_GET }, ...(o.plans ?? {}) };
}

async function setup(page: Page, o: Opts = {}): Promise<Seen> {
  const seen: Seen = { paper: [], keys: [], planReads: [] };
  if (o.phone) await page.setViewportSize({ width: 390, height: 844 });
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (r) => json(r, []));
  await page.route("**/api/positional/watchlist*", (r) => json(r, { as_of_date: "2026-10-19", buckets: { breakout_confirmed: [], pre_breakout: [], true_accumulation: [], trend_continuation: [] } }));
  await page.route("**/api/positional/picks*", (r) => json(r, { signal_date: "2026-10-19", count: 0, picks: [] }));
  await page.route("**/api/move-odds/**", (r) => json(r, { detail: "feature_not_enabled" }, 403));
  await page.route("**/api/desk/alerts*", (r) => json(r, { as_of: "2026-10-19", alerts: [] }));
  await page.route("**/api/desk/strategy/ideas", (r) => json(r, o.ideas ?? CARD.cash.ideas_response));
  await page.route("**/api/desk/strategy/top", (r) => json(r, o.top ?? CARD.fno.top_response));
  await page.route("**/api/desk/strategy/plan", (r) => json(r, o.builder ?? CARD.cash.builder_response));
  // MOCK: the levels engine is not asked here (the rows' plans carry the levels); a not-valid answer keeps the rows quiet.
  await page.route("**/api/desk/strategy/levels", (r) => json(r, { valid: false, version: "strategy-levels-v2", problems: [{ code: "mock", message: "MOCK" }] }));
  await page.route("**/api/desk/strategy/payoff", (r) => json(r, { valid: false, problems: [{ code: "mock", message: "MOCK" }], warnings: [] }));
  await page.route("**/api/desk/trade-plans/*", (r) => {
    const id = decodeURIComponent(new URL(r.request().url()).pathname.split("/").pop() as string);
    seen.planReads.push(id);
    const a = planAnswers(o)[id];
    return a ? json(r, a.body, a.status) : json(r, { detail: "plan_not_found" }, 404);
  });
  await page.route("**/api/risk/profile", (r) => (o.profile ? json(r, o.profile.body, o.profile.status) : json(r, CARD.risk_profile)));
  // MOCK: the controls as GET /api/risk/status reports them (off unless a case turns the kill switch on)
  await page.route("**/api/risk/status", (r) => json(r, { kill_switch: !!o.killSwitch, halted: false, policy_version: "MOCK" }));
  await page.route("**/api/desk/paper-account", (r) => json(r, CARD.paper_account));
  await page.route("**/api/desk/ai-watchlist*", (r) => json(r, o.day ?? CARD.ai_watchlist_day));
  await page.route("**/api/live/**", (r) => json(r, { available: false, reason: "MOCK: feed off", quotes: {}, mode: "expired", session: "closed", stale: true }));
  await page.route("**/api/fno/scan/buildup*", (r) => json(r, { as_of: "2026-10-19", indices: [], counts: {}, sources: {}, master: {}, risk_flag_text: {}, rows: [] }));
  const statuses = [...(o.paperStatus ?? [])];
  await page.route("**/api/desk/paper-trades*", (r) => {
    if (r.request().method() === "POST") {
      seen.paper.push(r.request().postDataJSON());
      seen.keys.push(r.request().headers()["idempotency-key"]);
      const st = statuses.length ? (statuses.shift() as number) : 201;
      return st === 201 ? json(r, { trade: { id: `t${seen.paper.length}` } }, 201) : json(r, { detail: "MOCK: upstream timeout" }, st);
    }
    return json(r, o.trades ?? { as_of: "2026-10-19", trades: [], summary: null });
  });
  return seen;
}

const stockRow = (page: Page) => page.getByTestId(`desk-top10-stock-${SYM}`);
const bankRow = (page: Page) => page.getByTestId("desk-top10-fno-BANKNIFTY");

// ── UI-1 … UI-6: every surface shows the card ─────────────────────────────

test.describe("Decision cards — the surfaces", () => {
  test("UI-1 a Top 10 stock row: one line from the plan, provisional, and every 3.1 field behind the expander", async ({ page }) => {
    await setup(page);
    await page.goto(SCANNER);
    const card = stockRow(page).getByTestId("desk-top10-card");
    await expect(card).toBeVisible(SLOW);
    await expect(card).toHaveAttribute("data-plan-id", CASH.plan_id);
    expect(await lineOf(card)).toEqual(EXPECT_CASH);
    await expect(card.getByTestId("dc-horizon")).toHaveText(`Horizon ≤ ${CASH.exit_plan.time.max_sessions} sessions`);
    await expect(card.getByTestId("dc-status")).toHaveText("Eligible");
    await expect(card.getByTestId("dc-approval")).toHaveAttribute("data-approval", "provisional");
    await expect(card.getByTestId("dc-approval")).toHaveText("Provisional · no risk decision yet");
    await expect(card.getByTestId("dc-sections")).toHaveCount(0);
    await card.getByTestId("dc-toggle").click();
    for (const s of ["setup", "entry", "stop", "targets", "size", "costs", "evidence", "warnings", "exit", "audit"]) await expect(card.getByTestId(`dc-sec-${s}`)).toBeVisible();
    await expect(card.getByTestId("dc-risk-check")).toHaveAttribute("data-state", "none");
    await expect(card.getByTestId("dc-risk-check")).toContainText("no decision yet");
    await expect(card.getByTestId("dc-equity")).toContainText(`${rs(EQUITY)} paper equity`);
    for (const e of CASH.evidence.items) await expect(card.getByTestId(`dc-ev-${e.key}`)).toContainText(e.status === "ok" ? e.text.slice(0, 30) : "Unavailable");
    for (const w of CASH.warnings) await expect(card.getByTestId(`dc-warn-${w.key}`).locator("[data-status]")).toHaveAttribute("data-status", w.status);
    await expect(card.getByTestId("dc-gap")).toContainText(CASH.costs.gap_risk.slice(0, 40));
    await expect(card.getByTestId("dc-data-asof")).toContainText("price 19 Oct 2026");
    await expect(card.getByTestId("dc-sec-audit")).toContainText(CASH.rules_version);
    await expect(card.getByTestId("dc-action")).toHaveAttribute("data-enabled", "true");
  });

  test("UI-2 a Top 10 F&O row (options): lots, rupee risk, the premium stop, and the provisional badge", async ({ page }) => {
    await setup(page);
    await page.goto(SCANNER);
    // Market Overview (step 2): one board at a time, so the F&O board is always one click away.
    await page.getByTestId("desk-top10-switch-fno").click(SLOW);
    const card = bankRow(page).getByTestId("desk-top10-fno-card");
    await expect(card).toHaveAttribute("data-plan-id", FNO.plan_id, SLOW);
    expect(await lineOf(card)).toEqual(EXPECT_FNO);
    await card.getByTestId("dc-toggle").click();
    await expect(card.getByTestId("dc-sec-exit")).toContainText(`stop ${rs(FNO.exit_plan.options.planned_stop)}`);
    await expect(card.getByTestId("dc-ev-regime")).toContainText("Desk regime Bearish");
    await expect(card.getByTestId("dc-ev-momentum")).toContainText("Unavailable");
    await expect(card.getByTestId("dc-approval")).toHaveAttribute("data-approval", "provisional");
  });

  test("UI-3 the AI watchlist's cash and F&O rows show the stored plans' cards", async ({ page }) => {
    await setup(page);
    await page.goto(WATCHLIST);
    const cash = page.getByTestId(`aiw-cash-${SYM}`).getByTestId("aiw-cash-card");
    await expect(cash).toHaveAttribute("data-plan-id", CASH.plan_id, SLOW);
    expect(await lineOf(cash)).toEqual(EXPECT_CASH);
    await page.getByTestId("aiw-seg-fno").click();
    const fno = page.getByTestId("aiw-fno-BANKNIFTY").getByTestId("aiw-fno-card");
    await expect(fno).toHaveAttribute("data-plan-id", FNO.plan_id);
    expect(await lineOf(fno)).toEqual(EXPECT_FNO);
  });

  test("UI-4 the lab's focus panel shows the FULL card, every section open", async ({ page }) => {
    await setup(page);
    await page.goto(`${DESK}?tab=fno&lab=indices&lab_sym=BANKNIFTY&lab_focus=BANKNIFTY`);
    const card = page.getByTestId("desk-lab-focus").getByTestId("idea-card-plan");
    await expect(card).toHaveAttribute("data-variant", "full", SLOW);
    await expect(card.getByTestId("dc-toggle")).toHaveCount(0);
    for (const s of ["setup", "entry", "stop", "targets", "size", "costs", "evidence", "warnings", "exit", "audit"]) await expect(card.getByTestId(`dc-sec-${s}`)).toBeVisible();
    expect(await lineOf(card)).toEqual(EXPECT_FNO);
  });

  test("UI-5 the Strategy Builder: the full card of the cash candidate, and a futures plan with lots and its rejection", async ({ page }) => {
    await setup(page);
    await page.goto(`${DESK}?tab=more&view=strategy&mode=stock&build=1&sym=${SYM}&direction=bullish&cand=cash:breakout_continuation`);
    const card = page.getByTestId("cand-decision-card");
    await expect(card).toHaveAttribute("data-plan-id", CASH.plan_id, SLOW);
    await expect(card).toHaveAttribute("data-variant", "full");
    expect(await lineOf(card)).toEqual(EXPECT_CASH);
    // the futures candidate of the same world: its plan is rejected by its own rules, says why, and cannot be traded
    const fut = CARD.futures.builder_response.candidates.find((c: { segment: string }) => c.segment === "futures");
    await setup(page, { builder: CARD.futures.builder_response, plans: { [fut.trade_plan.plan_id]: { status: 200, body: { plan: fut.trade_plan, lifecycle: { status: "proposed", trades: [], rejections: [] }, versions: [], risk_decision: null, risk_decision_basis: "MOCK" } } } });
    await page.goto(`${DESK}?tab=more&view=strategy&mode=stock&build=1&sym=${SYM}&direction=bullish&instrument=futures&cand=${encodeURIComponent(fut.id)}`);
    const fc = page.getByTestId("cand-decision-card");
    await expect(fc).toHaveAttribute("data-plan-id", fut.trade_plan.plan_id, SLOW);
    await expect(fc.getByTestId("dc-status")).toHaveText("Rejected");
    await expect(fc.getByTestId("dc-size")).toContainText("unavailable: the plan was not sized for your account");     // MOCK answer without account_size
    await expect(fc.getByTestId("dc-sec-setup")).toContainText(`lot ${new Intl.NumberFormat("en-IN").format(fut.trade_plan.instrument.lot_size)}`);
    await expect(fc.getByTestId("dc-rejection")).toContainText(fut.trade_plan.eligibility.reasons[0].message.slice(0, 30));
    await expect(fc.getByTestId("dc-action")).toHaveAttribute("data-enabled", "false");
  });

  test("UI-6 the paper-trade record shows the plan it records, read by id, with its lifecycle status", async ({ page }) => {
    const allowed = CARD.cash.allowed.trade_plan_response;
    const trade = { id: "t-plan", symbol: SYM, status: "open", quantity: CARD.cash.body.quantity, entry_price: CASH.entry.price, stop_price: CASH.stop.price,
      target_price: 1280, entry_rule: "at_once", opened_at: "2026-10-20T05:00:00+00:00", plan_ref: { plan_id: CASH.plan_id }, state: "POSITION_OPEN" };
    await setup(page, { trades: { as_of: "2026-10-19", trades: [trade], summary: null }, plans: { [CASH.plan_id]: { status: 200, body: allowed } } });
    // Desk redesign step 3 (2026-10-27): the record is the Trade Desk journal drawer, and the plan opens from it.
    await page.goto(`${DESK}?tab=trade&view=paper&sub=live`);
    await page.getByTestId("td-positions").getByRole("row").filter({ hasText: SYM }).click(SLOW);
    await page.getByTestId("td-journal-plan").click();
    const card = page.getByTestId("td-journal-dc");
    await expect(card).toHaveAttribute("data-plan-id", CASH.plan_id, SLOW);
    await expect(card.getByTestId("dc-status")).toHaveText("Open");
    await expect(card.getByTestId("dc-status-text")).toContainText("from your paper trades");
  });
});

// ── UI-7: one plan, identical everywhere ───────────────────────────────────

test.describe("Decision cards — 3.2 consistency", () => {
  test("UI-7 the same cash plan_id shows identical entry, stop, targets, size and risk on Top 10, the watchlist and the Builder", async ({ page }) => {
    await setup(page);
    await page.goto(SCANNER);
    const top = stockRow(page).getByTestId("desk-top10-card");
    await expect(top).toHaveAttribute("data-plan-id", CASH.plan_id, SLOW);
    const a = await lineOf(top);
    await page.goto(WATCHLIST);
    const wl = page.getByTestId(`aiw-cash-${SYM}`).getByTestId("aiw-cash-card");
    await expect(wl).toHaveAttribute("data-plan-id", CASH.plan_id, SLOW);
    const b = await lineOf(wl);
    await page.goto(`${DESK}?tab=more&view=strategy&mode=stock&build=1&sym=${SYM}&direction=bullish&cand=cash:breakout_continuation`);
    const bd = page.getByTestId("cand-decision-card");
    await expect(bd).toHaveAttribute("data-plan-id", CASH.plan_id, SLOW);
    const c = await lineOf(bd);
    expect([a, b, c]).toEqual([EXPECT_CASH, EXPECT_CASH, EXPECT_CASH]);
  });

  test("UI-7b the same F&O plan_id is identical on Top 10, the watchlist, the lab focus and Top by regime", async ({ page }) => {
    await setup(page);
    const lines: Array<Record<string, string>> = [];
    await page.goto(SCANNER);
    // Market Overview (step 2): one board at a time, so the F&O board is always one click away.
    await page.getByTestId("desk-top10-switch-fno").click(SLOW);
    const t = bankRow(page).getByTestId("desk-top10-fno-card");
    await expect(t).toHaveAttribute("data-plan-id", FNO.plan_id, SLOW);
    lines.push(await lineOf(t));
    await page.goto(WATCHLIST);
    await page.getByTestId("aiw-seg-fno").click(SLOW);
    const w = page.getByTestId("aiw-fno-BANKNIFTY").getByTestId("aiw-fno-card");
    await expect(w).toHaveAttribute("data-plan-id", FNO.plan_id, SLOW);
    lines.push(await lineOf(w));
    await page.goto(`${DESK}?tab=fno&lab=indices&lab_sym=BANKNIFTY&lab_focus=BANKNIFTY`);
    const l = page.getByTestId("desk-lab-focus").getByTestId("idea-card-plan");
    await expect(l).toHaveAttribute("data-plan-id", FNO.plan_id, SLOW);
    lines.push(await lineOf(l));
    await page.goto(`${DESK}?tab=more&view=strategy&mode=top`);
    const r = page.getByTestId(`top-idea-BANKNIFTY-${BANK_ON_BOARD.structure}`).getByTestId("idea-card-plan");
    await expect(r).toHaveAttribute("data-plan-id", FNO.plan_id, SLOW);
    lines.push(await lineOf(r));
    expect(lines).toEqual([EXPECT_FNO, EXPECT_FNO, EXPECT_FNO, EXPECT_FNO]);
  });
});

// ── UI-8: states ───────────────────────────────────────────────────────────

const withPlan = (mutate: (tp: Record<string, any>) => void) => {
  const ideas = clone(CARD.cash.ideas_response);
  mutate(ideas.ideas[0].trade_plan);
  return ideas;
};
const getOf = (tp: unknown, extra: Record<string, unknown> = {}) => ({ plan: tp, lifecycle: { status: "proposed", trades: [], rejections: [] }, versions: [], risk_decision: null, risk_decision_basis: "MOCK", ...extra });

test.describe("Decision cards — states", () => {
  test("UI-8a empty: an idea with no plan says so, and offers no card and no action", async ({ page }) => {
    const ideas = clone(CARD.cash.ideas_response);
    ideas.ideas[0].trade_plan = null;
    ideas.ideas[0].status_reasons = [{ code: "no_levels", message: "MOCK: the scanner gave no entry with a stop below it" }];
    await setup(page, { ideas });
    await page.goto(SCANNER);
    await expect(stockRow(page).getByTestId("desk-top10-noplan")).toContainText("No trade plan for this idea: MOCK: the scanner gave no entry", SLOW);
    await expect(stockRow(page).getByTestId("desk-top10-card")).toHaveCount(0);
  });

  test("UI-8b stale: price data before the last completed session and an older regime are marked with both dates", async ({ page }) => {
    // MOCK: the plan's own dates moved back, as a plan built on an older scan would carry them
    const ideas = withPlan((tp) => { tp.data_as_of = { ...tp.data_as_of, price: "2026-10-16", reference_session: "2026-10-19", regime: "2026-10-15" }; });
    await setup(page, { ideas, plans: { [CASH.plan_id]: { status: 200, body: getOf(ideas.ideas[0].trade_plan) } } });
    await page.goto(SCANNER);
    const card = stockRow(page).getByTestId("desk-top10-card");
    await expect(card.getByTestId("dc-stale")).toBeVisible(SLOW);
    await expect(card.getByTestId("dc-stale-text")).toContainText("price data of 16 Oct 2026, before the last completed session 19 Oct 2026");
    await expect(card.getByTestId("dc-stale-text")).toContainText("market regime measured 15 Oct 2026");
  });

  test("UI-8c rejected: status, the rejection explanation, and a disabled action that says why", async ({ page }) => {
    const ideas = withPlan((tp) => { tp.eligibility = { eligible: false, paper_eligible: false, state: "REJECTED", status: "no_trade", reasons: [{ code: "reward_risk_below_minimum", message: "MOCK: Reward : risk 0.9 is below the minimum 1.5." }] }; });
    await setup(page, { ideas, plans: { [CASH.plan_id]: { status: 200, body: getOf(ideas.ideas[0].trade_plan) } } });
    await page.goto(SCANNER);
    const card = stockRow(page).getByTestId("desk-top10-card");
    await expect(card.getByTestId("dc-status")).toHaveText("Rejected", SLOW);
    await expect(card.getByTestId("dc-action")).toContainText("Paper trade off: This plan is rejected: MOCK: Reward : risk 0.9");
    await card.getByTestId("dc-toggle").click();
    await expect(card.getByTestId("dc-rejection")).toContainText("MOCK: Reward : risk 0.9 is below the minimum 1.5.");
    await stockRow(page).getByTestId("desk-top10-stock-paper").click();
    await expect(stockRow(page).getByTestId("desk-top10-paper-blocked")).toContainText("This plan is rejected");
  });

  test("UI-8d/e provisional without a decision; Risk-approved only on the risk service's real ALLOW, and they look different", async ({ page }) => {
    await setup(page);
    await page.goto(SCANNER);
    const card = stockRow(page).getByTestId("desk-top10-card");
    await ready(card);
    await expect(card).toHaveAttribute("data-approval", "provisional");
    const provisional = await card.evaluate((el) => getComputedStyle(el).borderStyle);
    // the REAL allow decision on this plan (contract fixture: loosest profile, 113 shares written)
    await setup(page, { plans: { [CASH.plan_id]: { status: 200, body: CARD.cash.allowed.trade_plan_response } } });
    await page.goto(SCANNER);
    const ok = stockRow(page).getByTestId("desk-top10-card");
    await expect(ok.getByTestId("dc-approval")).toHaveText("✓ Risk-approved", SLOW);
    await expect(ok).toHaveAttribute("data-approval", "approved");
    await expect(ok.getByTestId("dc-status")).toHaveText("Open");
    expect([provisional, await ok.evaluate((el) => getComputedStyle(el).borderStyle)]).toEqual(["dashed", "solid"]);
    await ok.getByTestId("dc-toggle").click();
    const d = CARD.cash.allowed.trade_plan_response.risk_decision;
    await expect(ok.getByTestId("dc-risk-check")).toContainText(`Allowed ${d.approved_qty} shares · estimated risk ${rs(d.estimated_risk_rs.total)}`);
  });

  test("UI-8e2 an ALLOW made under other risk limits does not approve the plan: the profile changed since", async ({ page }) => {
    const profile = clone(CARD.risk_profile);
    profile.profile.limits_version = "rp-9-MOCKCHANGED";         // MOCK: the user tightened a limit after the decision
    await setup(page, { profile: { status: 200, body: profile }, plans: { [CASH.plan_id]: { status: 200, body: CARD.cash.allowed.trade_plan_response } } });
    await page.goto(SCANNER);
    const card = stockRow(page).getByTestId("desk-top10-card");
    await ready(card);
    await expect(card).toHaveAttribute("data-approval", "provisional");
    await card.getByTestId("dc-toggle").click();
    await expect(card.getByTestId("dc-risk-stale")).toContainText("your risk profile has changed since (now rp-9-MOCKCHANGED)");
  });

  test("UI-8f the risk service's real REDUCE says the size it allows; its real BLOCK turns the action off while it applies", async ({ page }) => {
    const reduced = CARD.cash.reduced.trade_plan_response;
    const profile = clone(CARD.risk_profile);
    profile.profile.limits_version = reduced.risk_decision.limits_version;   // the default profile the reduce was decided under
    await setup(page, { profile: { status: 200, body: profile }, plans: { [CASH.plan_id]: { status: 200, body: reduced } } });
    await page.goto(SCANNER);
    const card = stockRow(page).getByTestId("desk-top10-card");
    await expect(card).toHaveAttribute("data-approval", "reduce", SLOW);
    await card.getByTestId("dc-toggle").click();
    await expect(card.getByTestId("dc-risk-check")).toContainText(`Smaller size only: at most ${reduced.risk_decision.approved_qty} shares`);
    await expect(card.getByTestId("dc-action")).toHaveAttribute("data-enabled", "true");

    const blocked = CARD.cash.blocked.trade_plan_response;
    await page.clock.setFixedTime(new Date(blocked.risk_decision.at));       // the same session as the decision
    await setup(page, { killSwitch: true, plans: { [CASH.plan_id]: { status: 200, body: blocked } } });   // its kill switch is still on
    await page.goto(SCANNER);
    const b = stockRow(page).getByTestId("desk-top10-card");
    await ready(b);
    await expect(b).toHaveAttribute("data-approval", "block");
    // the switch is still on, so the account's sizing refuses it too (that reason is given first), and the action is off
    await expect(b.getByTestId("dc-action")).toContainText("Paper trade off: The risk service would refuse this plan for your account: The kill switch is on");
    await stockRow(page).getByTestId("desk-top10-stock-paper").click();
    await expect(stockRow(page).getByTestId("desk-top10-paper-blocked")).toContainText("The kill switch is on");
  });

/** MOCK combination: the REAL block decision of the kill-switch user, with the REAL sizing of an account whose switch is off
 *  (both from the contract fixture), as the plan route would answer once the switch was turned off. */
const blockedThenSwitchOff = () => ({ ...clone(CARD.cash.blocked.trade_plan_response), account_size: CARD.cash.trade_plan_response.account_size });

  test("UI-8f2 a block the kill switch caused stops applying once the switch is off", async ({ page }) => {
    const blocked = blockedThenSwitchOff();
    await page.clock.setFixedTime(new Date(blocked.risk_decision.at));
    await setup(page, { killSwitch: false, plans: { [CASH.plan_id]: { status: 200, body: blocked } } });
    await page.goto(SCANNER);
    const card = stockRow(page).getByTestId("desk-top10-card");
    await ready(card);
    await expect(card).toHaveAttribute("data-approval", "provisional");
    await expect(card.getByTestId("dc-action")).toHaveAttribute("data-enabled", "true");
    await card.getByTestId("dc-toggle").click();
    await expect(card.getByTestId("dc-risk-stale")).toContainText("the kill switch or halt that caused it is now off");
  });

  test("UI-8g a block from an earlier session no longer decides the plan: the next submission is decided again", async ({ page }) => {
    await setup(page, { plans: { [CASH.plan_id]: { status: 200, body: blockedThenSwitchOff() } } });
    await page.goto(SCANNER);
    const card = stockRow(page).getByTestId("desk-top10-card");
    await ready(card);
    await expect(card).toHaveAttribute("data-approval", "provisional");
    await expect(card.getByTestId("dc-action")).toHaveAttribute("data-enabled", "true");
    await card.getByTestId("dc-toggle").click();
    await expect(card.getByTestId("dc-risk-stale")).toContainText("decided in an earlier session");
  });
});

// ── UI-9: a changed plan refreshes every view ─────────────────────────────

/** MOCK: version 2 of the cash plan, as another view would have stored it (a moved stop; a made-up id). */
const V2_ID = "tp_mockversion2000";
const V2 = { ...clone(CASH), plan_id: V2_ID, version: 2, supersedes: CASH.plan_id, stop: { ...CASH.stop, price: 1162 } };
const versions = [{ plan_id: CASH.plan_id, version: 1, created_at: "2026-10-19T17:15:00+00:00", revalidation_ok: true, supersedes: null },
  { plan_id: V2_ID, version: 2, created_at: "2026-10-20T05:00:00+00:00", revalidation_ok: true, supersedes: CASH.plan_id }];

test.describe("Decision cards — a changed plan", () => {
  test("UI-9 a row built on version 1 shows version 2's figures, says so, and a share trade records version 2", async ({ page }) => {
    const seen = await setup(page, { plans: {
      [CASH.plan_id]: { status: 200, body: getOf(CASH, { versions }) },
      [V2_ID]: { status: 200, body: getOf(V2, { versions }) },
    } });
    await page.goto(WATCHLIST);
    const row = page.getByTestId(`aiw-cash-${SYM}`);
    const card = row.getByTestId("aiw-cash-card");
    await expect(card).toHaveAttribute("data-plan-id", V2_ID, SLOW);
    await expect(card).toHaveAttribute("data-row-plan-id", CASH.plan_id);
    await expect(card.getByTestId("dc-changed")).toContainText("Plan changed: version 2");
    await expect(card.getByTestId("dc-stop")).toContainText(rs(1162));
    await row.getByTestId("aiw-cash-paper").click();
    await row.getByTestId("aiw-paper-add").click();
    await expect(row.getByTestId("aiw-paper-done")).toBeVisible();
    expect(seen.paper[0]).toMatchObject({ stop_price: 1162, plan_ref: { plan_id: V2_ID } });
  });

  test("UI-9b an F&O row cannot record a newer version with its own legs: the action is off and says why", async ({ page }) => {
    const v2 = { ...clone(FNO), plan_id: "tp_mockfnoversion2", version: 2 };
    const vs = [{ plan_id: FNO.plan_id, version: 1 }, { plan_id: v2.plan_id, version: 2, supersedes: FNO.plan_id }];
    await setup(page, { plans: { [FNO.plan_id]: { status: 200, body: getOf(FNO, { versions: vs }) }, [v2.plan_id]: { status: 200, body: getOf(v2, { versions: vs }) } } });
    await page.goto(WATCHLIST);
    await page.getByTestId("aiw-seg-fno").click(SLOW);
    const row = page.getByTestId("aiw-fno-BANKNIFTY");
    await expect(row.getByTestId("aiw-fno-card")).toHaveAttribute("data-plan-id", v2.plan_id, SLOW);
    await expect(row.getByTestId("idea-paper-trade")).toBeDisabled();
    await expect(row.getByTestId("idea-paper-trade")).toHaveAttribute("title", /This plan changed after the row was built \(version 2 replaces version 1\)/);
  });

  test("UI-9c a re-ranked Top 10 that supersedes the plan refreshes the Builder still holding the old one", async ({ page }) => {
    const stored = { v2: false };
    const seen = await setup(page);
    // the plan route as the store answers it: version 2 exists once the re-rank stored it
    await page.unroute("**/api/desk/trade-plans/*");
    await page.route("**/api/desk/trade-plans/*", (r) => {
      const id = decodeURIComponent(new URL(r.request().url()).pathname.split("/").pop() as string);
      seen.planReads.push(id);
      const vs = stored.v2 ? versions : versions.slice(0, 1);
      if (id === CASH.plan_id) return json(r, getOf(CASH, { versions: vs }));
      if (id === V2_ID && stored.v2) return json(r, getOf(V2, { versions: vs }));
      return json(r, { detail: "plan_not_found" }, 404);
    });
    await page.goto(`${DESK}?tab=more&view=strategy&mode=stock&build=1&sym=${SYM}&direction=bullish&cand=cash:breakout_continuation`);
    await expect(page.getByTestId("cand-decision-card")).toHaveAttribute("data-plan-id", CASH.plan_id, SLOW);
    // the Scanner's Top 10 is ranked again and its answer carries version 2, which names version 1 in `supersedes`
    const reranked = clone(CARD.cash.ideas_response);
    reranked.ideas[0].trade_plan = V2;
    reranked.ideas[0].trade_plan_id = V2_ID;
    reranked.ideas[0].preferred = "cash:breakout_continuation";           // MOCK: so "Strategy ›" reopens the cash candidate
    await page.unroute("**/api/desk/strategy/ideas");
    await page.route("**/api/desk/strategy/ideas", (r) => { stored.v2 = true; return json(r, reranked); });
    // Desk redesign (2026-10-27): the Top 10 is on Market Overview (was the AI Scanner tab).
    await page.getByTestId("desk-tab-overview").click();
    await expect(stockRow(page).getByTestId("desk-top10-card")).toHaveAttribute("data-plan-id", V2_ID, SLOW);
    // back to the Builder from the row (its links are in the row's drawer): it builds the same plan (version 1) again; its cached reading was refreshed
    await stockRow(page).getByTestId("desk-top10-stock-open").click();
    await stockRow(page).getByTestId("desk-top10-stock-plan").click();
    const card = page.getByTestId("cand-decision-card");
    await expect(card).toHaveAttribute("data-plan-id", V2_ID, SLOW);
    await expect(card.getByTestId("dc-changed")).toContainText("version 2");
    await expect(page.getByTestId("paper-blocked")).toContainText("This plan changed after the row was built");
  });
});

// ── UI-10 … UI-16 ─────────────────────────────────────────────────────────

test.describe("Decision cards — equity, mobile, carry-forward, Phase 0", () => {
  test("UI-10 a plan the route could not size for the account shows no size, never the plan's own number", async ({ page }) => {
    // MOCK: the route's answer when the account's book cannot be read (plan_sizing status "unavailable"), and no profile
    const body = { ...clone(CARD.cash.trade_plan_response), account_size: { status: "unavailable", reason: "MOCK: your paper equity could not be read", version: "plan-sizing-v1" } };
    await setup(page, { profile: { status: 500, body: { detail: "MOCK: profile store down" } }, plans: { [CASH.plan_id]: { status: 200, body } } });
    await page.goto(SCANNER);
    const card = stockRow(page).getByTestId("desk-top10-card");
    await expect(card.getByTestId("dc-size")).toHaveText("Size unavailable: MOCK: your paper equity could not be read", SLOW);
    await expect(card.getByTestId("dc-risk")).toHaveText("Risk unavailable");
    await expect(card.getByTestId("dc-costs")).toHaveText("Est. costs unavailable");
    expect(await card.getByTestId("dc-line").innerText()).not.toContain(int(CASH.size.quantity));
    await card.getByTestId("dc-toggle").click();
    await expect(card.getByTestId("dc-equity")).toContainText("Unavailable: the risk profile could not be read");
  });

  test("UI-17 the card's size is the risk service's for this account; the paper trade sends exactly it", async ({ page }) => {
    // the REAL answer for a default-profile user (contract fixture: user_c, before submitting): 83, where the plan's own is 113
    const before = CARD.cash.reduced.trade_plan_response_before;
    const a = before.account_size;
    const profile = clone(CARD.risk_profile_default);
    const seen = await setup(page, { profile: { status: 200, body: profile }, plans: { [CASH.plan_id]: { status: 200, body: before } } });
    await page.goto(SCANNER);
    const card = stockRow(page).getByTestId("desk-top10-card");
    expect(a.quantity).toBeLessThan(CASH.size.quantity);
    await expect(card.getByTestId("dc-size")).toHaveText(sized(a).size, SLOW);
    await expect(card.getByTestId("dc-risk")).toHaveText(sized(a).risk);
    await card.getByTestId("dc-toggle").click();
    await expect(card.getByTestId("dc-binding")).toContainText(a.binding[0].message);
    await expect(card.getByTestId("dc-own-size")).toContainText(`${int(CASH.size.quantity)} shares`);
    await expect(card.getByTestId("dc-own-size")).toContainText("a what-if, not what the risk service approves");
    await stockRow(page).getByTestId("desk-top10-stock-paper").click();
    await expect(stockRow(page).getByTestId("desk-top10-paper-qty")).toHaveValue(String(a.quantity));
    await stockRow(page).getByTestId("desk-top10-paper-add").click();
    await expect(stockRow(page).getByTestId("desk-top10-paper-done")).toBeVisible();
    // the body the backend contract test sends through the real route, where it is ALLOWED at exactly this size
    expect(seen.paper[0]).toMatchObject({ quantity: a.quantity, plan_ref: { plan_id: CASH.plan_id } });
  });

  test("UI-18 portfolio limits: 'may be reduced at submission', with the budgets left in the risk profile", async ({ page }) => {
    await setup(page);
    await page.goto(SCANNER);
    const card = stockRow(page).getByTestId("desk-top10-card");
    await card.getByTestId("dc-toggle").click(SLOW);
    const pf = CARD.cash.trade_plan_response.account_size.portfolio;
    await expect(card.getByTestId("dc-portfolio")).toContainText("May be reduced by portfolio limits at submission");
    await expect(card.getByTestId("dc-budgets-left")).toContainText(`open risk ${rs(pf.remaining.open_risk_rs)}`);
    await expect(card.getByTestId("dc-budgets-left")).toContainText(`${pf.remaining.positions} more positions`);
  });

  test("UI-19 BEAR regime: the size carries the factor once, and that size is sent as is", async ({ page }) => {
    // REAL answer: default profile, BEAR regime (contract fixture). Until #365 the service halved any submitted size
    // again, so this card said "(not allowed as is)" and the action was off; now the halved size is allowed.
    const bear = CARD.cash.bear_default_response;
    const a = bear.account_size;
    expect(a.status).toBe("sized");
    const seen = await setup(page, { profile: { status: 200, body: CARD.risk_profile_default }, plans: { [CASH.plan_id]: { status: 200, body: bear } } });
    await page.goto(SCANNER);
    const card = stockRow(page).getByTestId("desk-top10-card");
    await expect(card.getByTestId("dc-size")).toHaveText(sized(a).size, SLOW);
    await expect(card.getByTestId("dc-size")).not.toContainText("not allowed as is");
    await expect(card.getByTestId("dc-action")).not.toContainText("Paper trade off");
    await card.getByTestId("dc-toggle").click();
    await expect(card.getByTestId("dc-factors")).toContainText("The market regime is BEAR; size is cut.");
    await stockRow(page).getByTestId("desk-top10-stock-paper").click();
    await expect(stockRow(page).getByTestId("desk-top10-paper-qty")).toHaveValue(String(a.quantity));
    await stockRow(page).getByTestId("desk-top10-paper-add").click();
    await expect(stockRow(page).getByTestId("desk-top10-paper-done")).toBeVisible();
    expect(seen.paper[0]).toMatchObject({ quantity: a.quantity, plan_ref: { plan_id: CASH.plan_id } });
  });

  test("UI-20 an F&O row whose one lot is over the per-trade budget shows no size and cannot be submitted", async ({ page }) => {
    const def = CARD.fno.trade_plan_response_default;      // REAL answer: default profile (contract fixture)
    await setup(page, { profile: { status: 200, body: CARD.risk_profile_default }, plans: { [FNO.plan_id]: { status: 200, body: def } } });
    await page.goto(WATCHLIST);
    await page.getByTestId("aiw-seg-fno").click(SLOW);
    const row = page.getByTestId("aiw-fno-BANKNIFTY");
    await expect(row.getByTestId("aiw-fno-card").getByTestId("dc-size")).toHaveText(`Size unavailable: the risk service would refuse it (${def.account_size.blocking[0].message})`, SLOW);
    await expect(row.getByTestId("idea-paper-trade")).toBeDisabled();
    await expect(row.getByTestId("idea-paper-trade")).toHaveAttribute("title", /The risk service would refuse this plan for your account: The smallest valid size/);
  });

  test("UI-11 390px: the row card and its expanded sections fit, on the Top 10 and the watchlist", async ({ page }) => {
    await setup(page, { phone: true });
    const overflow = () => page.evaluate(() => {
      const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
      return Math.max(document.documentElement.scrollWidth - window.innerWidth, sc ? sc.scrollWidth - sc.clientWidth : 0);
    });
    await page.goto(SCANNER);
    const card = stockRow(page).getByTestId("desk-top10-card");
    await card.getByTestId("dc-toggle").click(SLOW);
    await expect(card.getByTestId("dc-sec-evidence")).toBeVisible();
    expect(await overflow()).toBeLessThanOrEqual(0);
    const box = await card.boundingBox();
    expect(box!.width).toBeLessThanOrEqual(390);
    await page.goto(WATCHLIST);
    const w = page.getByTestId(`aiw-cash-${SYM}`).getByTestId("aiw-cash-card");
    await w.getByTestId("dc-toggle").click(SLOW);
    await expect(w.getByTestId("dc-sec-warnings")).toBeVisible();
    expect(await overflow()).toBeLessThanOrEqual(0);
  });

  test("UI-12 carry-forward: the watchlist row and the Top 10 row say since when, with the first day's levels", async ({ page }) => {
    // MOCK: the route's `carried` for an idea on 3 list days in a row (shape: backend routes/ai_watchlist.carry_forward)
    const day = clone(CARD.ai_watchlist_day);
    const e = day.cash[0];
    e.days_on_list = 3;
    e.carried = { sessions: 3, from: "2026-10-15", first: { list_date: "2026-10-15", entry: 1190, entry_kind: "price", stop: 1150, target: 1270, plan_id: "tp_mockfirst", basis: "trade_plan" }, today: e.levels_on_list };
    await setup(page, { day });
    await page.goto(WATCHLIST);
    const tag = page.getByTestId(`aiw-cash-${SYM}`).getByTestId("aiw-carried");
    await expect(tag).toContainText("On the list 3 sessions · carried from 15 Oct 2026", SLOW);
    await expect(tag.getByTestId("aiw-carried-levels")).toContainText(`First day (15 Oct 2026): entry ${rs(1190)} · stop ${rs(1150)} · target ${rs(1270)} → this list: entry ${rs(1200)}`);
    await page.getByTestId("aiw-seg-fno").click();
    await expect(page.getByTestId("aiw-fno-BANKNIFTY").getByTestId("aiw-carried")).toHaveCount(0);       // new on the list
    // the Top 10: the newest stored list is an earlier session's, so the live idea was on it before
    const earlier = clone(day);
    earlier.list_date = "2026-10-16";
    earlier.cash[0].carried = null;
    earlier.cash[0].days_on_list = 1;
    earlier.cash[0].levels_on_list = { ...e.levels_on_list, list_date: "2026-10-16", stop: 1155 };
    await setup(page, { day: earlier });
    await page.goto(SCANNER);
    const t = stockRow(page).getByTestId("desk-top10-carried");
    await expect(t).toContainText("On the list 1 session · carried from 16 Oct 2026", SLOW);
    await expect(t).toContainText(`stop ${rs(1155)}`);
    await expect(t).toContainText(`this row's plan: entry ${rs(CASH.entry.price)} · stop ${rs(CASH.stop.price)}`);
  });

  test("UI-13 the F&O idea's paper trade sends an Idempotency-Key; a retry after a failure reuses it, a new submission gets a new one", async ({ page }) => {
    const seen = await setup(page, { paperStatus: [502, 201, 201] });
    await page.goto(SCANNER);
    // Market Overview (step 2): one board at a time, so the F&O board is always one click away.
    await page.getByTestId("desk-top10-switch-fno").click(SLOW);
    const bank = bankRow(page);
    await expect(bank.getByTestId("desk-top10-fno-card")).toBeVisible(SLOW);
    await bank.getByTestId("desk-top10-fno-paper").click();                // the paper trade is in the row's drawer
    const btn = bank.getByTestId("idea-paper-trade").first();
    await btn.click();
    await expect(bank.getByTestId("idea-paper-error").first()).toBeVisible();
    await btn.click();                                                     // the user retries the same idea
    await expect(btn).toHaveText("Added to paper trades");
    await page.keyboard.press("Escape");                                   // close BANKNIFTY's drawer, open NIFTY's
    await page.getByTestId("desk-top10-fno-NIFTY").getByTestId("desk-top10-fno-paper").click();
    const nifty = page.getByTestId("desk-top10-fno-NIFTY").getByTestId("idea-paper-trade").first();
    await nifty.click();
    await expect(nifty).toHaveText("Added to paper trades");
    expect(seen.keys.length).toBe(3);
    expect(seen.keys.every((k) => UUID.test(k ?? ""))).toBe(true);
    expect(seen.keys[0]).toBe(seen.keys[1]);
    expect(seen.keys[2]).not.toBe(seen.keys[0]);
  });

  test("UI-15 the day block names the scan's basis, or says it was not recorded", async ({ page }) => {
    await setup(page);
    await page.goto(WATCHLIST);
    await expect(page.getByTestId("aiw-scan-basis")).toHaveText("Scan basis: not recorded for this day (stored before the job kept it).", SLOW);
    const day = clone(CARD.ai_watchlist_day);
    // MOCK: the basis the scanner publishes (backend positional_engine/scan_meta.basis_for_date shape)
    day.notes.scan_basis = { date: "2026-10-19", engine_versions: ["v1.1"], price_basis: "corp_action_adjusted", exceptions: { raw_prices: [{ symbol: "X" }], truncated: [], not_scored_after_truncation: [] },
      data_quality: { status: "clean", warnings: 0, problems: [], checked_at: "2026-10-19T14:15:25+00:00" } };
    await setup(page, { day });
    await page.goto(WATCHLIST);
    await expect(page.getByTestId("aiw-scan-basis")).toHaveText("Scan basis (Mon, 19 Oct): engine v1.1 · prices adjusted for corporate actions · data quality clean · exceptions: 1 on raw prices, 0 with history cut", SLOW);
  });

  test("UI-16 the card says ideas and not a prediction, never picks or suggestions, and no confidence for the rank", async ({ page }) => {
    await setup(page);
    await page.goto(SCANNER);
    const card = stockRow(page).getByTestId("desk-top10-card");
    await card.getByTestId("dc-toggle").click(SLOW);
    const text = await card.innerText();
    expect(text).toContain("not a prediction, a probability or an edge");
    expect(text).not.toMatch(/\bpicks?\b|recommended|suggest|confidence/i);
  });
});
