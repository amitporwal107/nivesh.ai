/**
 * One-screen Copilot app (/v5/app) — Trade Desk › Strategy Lab › Build a trade as the owner's four-step wizard
 * (test cases WZ-1 … WZ-19 in test_reports/desk_strategy_wizard_TESTCASES.md).
 *
 * REAL fixtures from this branch's backend code: wizard-catalog.json (GET /api/desk/strategy/templates, templates.catalog()),
 * wizard-payoff-bcs.json and wizard-payoff-calendar.json (services/strategy_plan compute_payoff for a NIFTY 24500/24700 CE
 * bull call spread on 25 Nov, and the same legs on two expiries). Everything else is an inline MOCK — not real data — in
 * the real route's shape: the chain, futures, instances, saved plans, AI Trader strategies, the paper book, the risk check
 * and the paper-trade POST answers. The clock is fixed at 28 Oct 2026 10:00 IST. Mocked APIs, production build.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", name), "utf-8"));
const CATALOG = load("wizard-catalog.json");
const PAYOFF = load("wizard-payoff-bcs.json");
const PAYOFF_CAL = load("wizard-payoff-calendar.json");
const CARD = load("contract-decision-card.json");
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const BUILD = "/v5/app/trader/desk?tab=trade&view=lab&sub=build";
const SLOW = { timeout: 15_000 };
const NOV = "2026-11-25";
const DEC = "2026-12-30";

// ── MOCK chain (GET /api/fno/NIFTY/chain, trading/fno.ts ChainC) — made-up prices ─────────────────────────────────────
const STRIKES = [24000, 24100, 24200, 24300, 24400, 24500, 24600, 24700, 24800, 24900, 25000];
const CALLS: Record<number, number> = { 24000: 560, 24100: 480, 24200: 405, 24300: 335, 24400: 255, 24500: 180, 24600: 130, 24700: 95, 24800: 65, 24900: 42, 25000: 26 };
const PUTS: Record<number, number | null> = { 24000: 40, 24100: 52, 24200: 70, 24300: null, 24400: 128, 24500: 205, 24600: 260, 24700: 330, 24800: 400, 24900: 480, 25000: 560 };
const side = (close: number | null, delta: number) => ({ close, settle: close, oi: 120000, change_in_oi: -3500, volume: 9000, iv: 12.5, iv_price: "close", delta, gamma: 0.0004, theta: -6, vega: 18, change: null, change_pct: null, oi_buildup: null });
function chainFor(expiry: string, asOf = "2026-10-27") {
  const k = expiry === DEC ? 1.6 : 1;
  return {
    symbol: "NIFTY", strike_count: STRIKES.length, lot_size: 75,
    summary: { as_of: asOf, expiry, spot: 24480, atm_strike: 24500, total_call_oi: 1, total_put_oi: 1, total_call_oi_change: 0, total_put_oi_change: 0, pcr: 1, max_pain: 24500,
      max_call_oi: { strike: 25000, oi: 900000 }, max_put_oi: { strike: 24000, oi: 800000 }, put_wall: { strike: 24000, oi: 800000 }, call_wall: { strike: 25000, oi: 900000 },
      days_to_expiry: 29, forward: 24560, forward_basis: "future", rate_pct: 6.5, atm_iv: 12.5, expected_move: 385, expected_move_pct: 1.57 },
    strikes: STRIKES.map((s, i) => ({ strike: s, call: side(Math.round(CALLS[s] * k * 100) / 100, 0.85 - i * 0.07), put: side(PUTS[s] == null ? null : Math.round((PUTS[s] as number) * k * 100) / 100, -0.15 - i * 0.07) })),
  };
}
const EXPIRIES = { symbol: "NIFTY", as_of: "2026-10-27", expiries: [{ expiry: NOV, days_to_expiry: 29 }, { expiry: DEC, days_to_expiry: 64 }, { expiry: "2027-01-27", days_to_expiry: 92 }] };
const FUTURES = { symbol: "NIFTY", as_of: "2026-10-27", spot: 24480, futures: [{ expiry: NOV, close: 24560, settle: 24555, oi: 1, change_in_oi: 0, volume: 1, basis: 75, prev_close: null, change: null, change_pct: null, oi_buildup: null }] };

// ── MOCK instances, saved plan, AI Trader strategies, paper trades ───────────────────────────────────────────────────
const opt = (side: string, t: string, strike: number, expiry = NOV, entry = 100, lots = 1) => ({ kind: "option", side, lots, lot_size: 75, entry_price: entry, expiry, strike, option_type: t, price_source: "MOCK" });
const cashLeg = { kind: "cash", side: "buy", lots: 75, lot_size: 1, entry_price: 24480, expiry: null, price_source: "MOCK" };
const planSummary = (id: string, family: string) => ({ id, plan_id: `plan_${id}`, saved_at: "2026-10-25T10:00:00+00:00", underlying: "NIFTY", direction: "bullish", horizon: "swing", segment: "options", family, status: "plan", data_as_of: "2026-10-24", rules_version: "r", lifecycle: null });
const PLANS = { plans: [planSummary("sp-1", "bull_put_spread"), planSummary("sp-cc", "covered_call"), planSummary("sp-old", "bull_call_spread")], count: 3, limit: 100, max_saved: 200 };
const pleg = (side: string, t: string | null, strike: number | null, expiry: string | null, entry: number, kind = "option", quantity = 1) => ({ kind, side, quantity, lot_size: kind === "cash" ? 1 : 75, entry_price: entry, expiry, strike, option_type: t });
const planDetail = (id: string, family: string, legs: unknown[]) => ({ id, saved_at: "2026-10-25T10:00:00+00:00", plan: { summary: { family }, candidates: [{ family, legs }] } });
const PLAN_DETAILS: Record<string, unknown> = {
  "sp-1": planDetail("sp-1", "bull_put_spread", [pleg("buy", "put", 24300, NOV, 60), pleg("sell", "put", 24400, NOV, 110)]),
  "sp-cc": planDetail("sp-cc", "covered_call", [pleg("buy", null, null, null, 24480, "cash", 75), pleg("sell", "call", 24700, NOV, 95)]),
  "sp-old": planDetail("sp-old", "bull_call_spread", [pleg("buy", "call", 24500, "2026-10-20", 150), pleg("sell", "call", 24700, "2026-10-20", 60)]),
};
// GET /api/strategy-builder/strategies (routes/strategy_builder.py list_strategies): STOCK / MF rule sets, no legs.
const BUILDER = { strategies: [{ id: "sb-breakout1", owner_id: "u", name: "Breakout screen", description: null, asset_class: "STOCK", is_public_template: false, is_archived: false, created_at: "2026-10-01", updated_at: "2026-10-20" }], count: 1 };
const ai = (id: string, name: string, stage: string, o: Record<string, unknown> = {}) => ({ id, name, stage, version: 2, template: "momentum_breakout", regime: "BULL", created_by: "ai", spec: {}, config: {}, provenance: {}, runs: [], holdout_used: false, holdout_window: null, paper_stats: null, stage_history: [], created_at: "2026-10-20", updated_at: "2026-10-26", stages: [], orders: "none", ...o });
const AI = { orders: "none", strategies: [
  ai("ai-draft01", "AI momentum breakout", "draft"),
  ai("ai-pass001", "AI mean reversion", "backtested", { runs: [{}], stage_history: [{ stage: "draft", gates: [] }, { stage: "backtested", gates: [{ code: "a", passed: true }, { code: "b", passed: true }] }] }),
  ai("ai-runs001", "AI accumulation", "draft", { runs: [{}] }),
  ai("ai-paper01", "AI trend paper", "paper", { version: 3, paper_stats: { net_pnl_rs: -820 } }),
] };
const COST_V2 = { name: "desk cost card", version: "desk-cost-v2", slippage_pct_per_side: 0.05, brokerage_rs_per_side: 20 };
const strade = (id: string, legs: Array<ReturnType<typeof opt>>, o: Record<string, unknown> = {}) => ({
  id, kind: "strategy", symbol: "NIFTY", underlying: "NIFTY", direction: "bullish", family: "bull_call_spread", family_name: "Bull call spread", summary_text: "MOCK",
  strategy_plan_id: null, reference_price: 24480, stop_underlying: null, target_underlying: null, note: null, opened_at: "2026-10-24T10:00:00+00:00", status: "open",
  closed_at: null, exit_reason: null, exit_session: null, exit_note: null, entry_rule: "at_once", entry_status: "assumed", max_hold_sessions: null, rules_version: "desk-paper-v3",
  cost_model: COST_V2, risk: { defined_risk: true, futures_exposure: false, note: null },
  signal: { signal_at: "2026-10-24T10:00:00+00:00", rule_version: "r1", model_version: null, source_refs: [], evidence_summary: "MOCK" },
  entry_record_hash: "h", entry_record_intact: true,
  legs: legs.map((l, i) => ({ ...l, index: i, label: "MOCK", mark: l.entry_price, mark_date: "2026-10-27", mark_basis: "close", mark_basis_text: "close", mark_source: "bhavcopy", pnl_rs: 0 })),
  net_premium_rs: -6375, mark_premium_rs: -6000, gross_pnl_rs: 0, costs_rs: 77, costs_breakdown: null, costs_basis: "MOCK", net_pnl_rs: 0, unrealized_pnl_rs: 0, realized_pnl_rs: null,
  mfe_rs: 0, mae_rs: 0, observations: 1, held_sessions: 2, checked_through: "2026-10-27", last_mark_date: "2026-10-27", mark_error: null, flags: [], event_count: 0, events: [],
  premium_plan: null, structure_value_per_unit: 1, exit_basis: null, state: "POSITION_OPEN", transitions: [], plan_ref: null, rolled_from: null, rolled_to: null, ...o,
});
const PT_PLAN = strade("pt-plan", [opt("buy", "put", 24300, NOV, 60), opt("sell", "put", 24400, NOV, 110)],
  { family: "bull_put_spread", family_name: "Bull put spread", strategy_plan_id: "sp-1", net_pnl_rs: 1240.5 });
const PT_AI = strade("pt-ai0001", [opt("buy", "call", 24500, NOV, 180), opt("sell", "call", 24700, NOV, 95)],
  { net_pnl_rs: -310.2, signal: { signal_at: "2026-10-24T10:00:00+00:00", rule_version: "fno-rules-v1", model_version: "fno-cand-v2", source_refs: [{ kind: "fno_candidate", ref: "c1", as_of: null }], evidence_summary: "MOCK" } });
const book = (trades: unknown[]) => ({ as_of: "2026-10-27", checked_through: "2026-10-27", source: "nidp", price_basis: "raw", marks_error: null, exit_rule: "x", entry_rules: {}, rules_version: "desk-paper-v2",
  cost_model: COST_V2, orders: "Paper trades never create a broker order.", status: "all", trades, summary: { open: trades.length, closed: 0, wins: 0, losses: 0, realized_pnl_rs: 0, unrealized_pnl_rs: 0, unmarked_open: 0, partial: false } });
const ALLOW = { checked: true, recorded: false, outcome: "allow", reasons: [], requested_lots: 1, approved_lots: 1, requested_qty: null, approved_qty: null, estimated_risk_rs: { total: 6499.49 }, budget: {}, policy_version: "MOCK", limits_version: "MOCK", freshness: {}, duplicate: null, basis: "MOCK", sent_to_broker: false };
const BLOCK_REASON = "Open risk would reach 3.4% of equity; your profile allows 3.0%.";

interface Opts { empty?: boolean; check?: unknown; post?: Array<{ status: number; body: unknown }>; margin?: { status: number; body: unknown }; asOf?: string; phone?: boolean }
interface Seen { checks: Array<Record<string, unknown>>; posts: Array<Record<string, unknown>>; keys: Array<string | undefined>; payoffs: number; chains: string[] }

async function setup(page: Page, o: Opts = {}): Promise<Seen> {
  const seen: Seen = { checks: [], posts: [], keys: [], payoffs: 0, chains: [] };
  await page.clock.setFixedTime(new Date("2026-10-28T10:00:00+05:30"));
  if (o.phone) await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/api/**", (r) => json(r, { detail: "MOCK: not mocked in this spec" }, 404));
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (r) => json(r, []));
  await page.route("**/api/positional/**", (r) => json(r, { as_of_date: "2026-10-26", signal_date: "2026-10-26", count: 0, picks: [], buckets: {} }));
  await page.route("**/api/move-odds/**", (r) => json(r, { detail: "feature_not_enabled" }, 403));
  await page.route("**/api/desk/alerts*", (r) => json(r, { as_of: "2026-10-26", alerts: [] }));
  await page.route("**/api/risk/status", (r) => json(r, { kill_switch: false, halted: false, policy_version: "MOCK" }));
  await page.route("**/api/risk/profile", (r) => json(r, CARD.risk_profile_default));
  await page.route("**/api/desk/paper-account", (r) => json(r, { ...CARD.paper_account, stored: true }));
  await page.route("**/api/desk/exit-job-status", (r) => json(r, { job: "x", status: "ok", state: "ok", message: "MOCK", schedule: "MOCK" }));
  await page.route("**/api/desk/strategy/templates", (r) => json(r, CATALOG));
  await page.route("**/api/desk/strategy/plans*", (r) => json(r, o.empty ? { plans: [], count: 0, limit: 100, max_saved: 200 } : PLANS));
  await page.route("**/api/desk/strategy/plans/*", (r) => {
    const id = decodeURIComponent(new URL(r.request().url()).pathname.split("/").pop() as string);
    return PLAN_DETAILS[id] ? json(r, PLAN_DETAILS[id]) : json(r, { detail: "plan_not_found" }, 404);
  });
  await page.route("**/api/strategy-builder/strategies", (r) => json(r, o.empty ? { strategies: [], count: 0 } : BUILDER));
  await page.route("**/api/ai-trader/strategies", (r) => json(r, o.empty ? { strategies: [], orders: "none" } : AI));
  const trades: unknown[] = o.empty ? [] : [PT_PLAN, PT_AI];
  await page.route("**/api/desk/paper-trades*", (r) => {
    if (r.request().method() === "POST") {
      seen.posts.push(r.request().postDataJSON());
      seen.keys.push(r.request().headers()["idempotency-key"]);
      const a = o.post?.shift() ?? { status: 201, body: { trade: strade("pt-new", [opt("buy", "call", 24500, NOV, 180), opt("sell", "call", 24700, NOV, 95)], { signal: { ...PT_AI.signal, model_version: null, source_refs: [{ kind: "strategy_template", ref: "bull_call_spread", as_of: "2026-10-27" }] } }), risk: null } };
      if (a.status === 201) trades.push((a.body as { trade: unknown }).trade);
      return json(r, a.body, a.status);
    }
    return json(r, book(trades));
  });
  await page.route("**/api/desk/paper-trades/check", (r) => { seen.checks.push(r.request().postDataJSON()); return json(r, o.check ?? ALLOW); });
  await page.route("**/api/desk/strategy/payoff", (r) => {
    seen.payoffs += 1;
    const b = r.request().postDataJSON() as { legs: Array<{ expiry?: string | null }> };
    const exps = new Set(b.legs.map((l) => l.expiry).filter(Boolean));
    return json(r, exps.size > 1 ? PAYOFF_CAL : PAYOFF);
  });
  await page.route("**/api/fno/NIFTY/expiries", (r) => json(r, EXPIRIES));
  await page.route("**/api/fno/NIFTY/futures", (r) => json(r, FUTURES));
  await page.route("**/api/fno/NIFTY/chain*", (r) => {
    const e = new URL(r.request().url()).searchParams.get("expiry") ?? NOV;
    seen.chains.push(e);
    return json(r, chainFor(e, o.asOf));
  });
  await page.route("**/api/fno/margin", (r) => json(r, o.margin?.body ?? { detail: "kite_session_unavailable" }, o.margin?.status ?? 503));
  await page.route("**/api/fno/scan/buildup*", (r) => json(r, { as_of: "2026-10-27", indices: [], counts: {}, sources: {}, master: {}, risk_flag_text: {}, rows: [] }));
  await page.route("**/api/live/**", (r) => json(r, { available: false, reason: "MOCK", quotes: {}, mode: "expired", session: "closed", stale: true }));
  return seen;
}

async function noSideScroll(page: Page) {
  const o = await page.evaluate(() => {
    const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
    const right = sc ? sc.getBoundingClientRect().right : window.innerWidth;
    const wide = (Array.from(document.querySelectorAll("*")) as HTMLElement[]).filter((el) => {
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.right > right + 1 && !(el.parentElement && el.parentElement.getBoundingClientRect().right > right + 1) && !el.closest(".cp-scroll");
    }).slice(0, 6).map((el) => `${el.tagName.toLowerCase()}[${el.getAttribute("data-testid") ?? ""}] right=${Math.round(el.getBoundingClientRect().right)}`);
    return { doc: document.documentElement.scrollWidth - window.innerWidth, scroll: sc ? sc.scrollWidth - sc.clientWidth : 0, wide: wide.join(", ") };
  });
  expect(o.doc, o.wide).toBeLessThanOrEqual(1);
  expect(o.scroll, o.wide).toBeLessThanOrEqual(1);
}

/** Step 1 → choose the bull call spread → step 2 (ATM legs from the chain). */
async function toConfigure(page: Page) {
  await page.goto(BUILD);
  await page.locator('[data-testid="wz-card"][data-name="bull_call_spread"]').click(SLOW);
  await expect(page.getByTestId("wz-step-2")).toBeVisible(SLOW);
  await expect(page.getByTestId("wz-preview-legs")).toHaveText(`B 24500 CE 25 Nov · S 24700 CE 25 Nov`, SLOW);
}
async function toReview(page: Page) {
  await toConfigure(page);
  await page.getByTestId("wz-to-review").click();
  await expect(page.getByTestId("wz-step-3")).toBeVisible(SLOW);
  await expect(page.getByTestId("wz-leg")).toHaveCount(2);
}
async function toValidate(page: Page) {
  await toReview(page);
  await expect(page.getByTestId("wz-checks-risk")).toHaveAttribute("data-tone", "ok", SLOW);
  await page.getByTestId("wz-to-validate").click();
  await expect(page.getByTestId("wz-step-4")).toBeVisible(SLOW);
}

test.describe("MOCK — not real data: Strategy Lab › Build a trade · the four-step wizard", () => {
  test("WZ-1 the frame: breadcrumb, eyebrow, headline, stepper, provenance strip and its in-app links", async ({ page }) => {
    await setup(page);
    await page.goto(BUILD);
    await expect(page.getByTestId("desk-trail")).toContainText("Trade Desk", SLOW);
    await expect(page.getByTestId("desk-trail")).toContainText("Strategy Lab");
    await expect(page.getByTestId("desk-trail-here")).toHaveText(/Build a trade/);
    await expect(page.getByTestId("wz-eyebrow")).toHaveText(/strategy lab · cash, futures and options/i);
    await expect(page.getByTestId("wz-headline")).toHaveText("Pick a template or open an existing strategy to build a trade.");
    for (const [n, label] of [[1, "Choose template"], [2, "Configure"], [3, "Review & adjust"], [4, "Validate & paper-trade"]] as const) {
      await expect(page.getByTestId(`wz-step-btn-${n}`)).toContainText(label);
    }
    await expect(page.getByTestId("wz-step-btn-1")).toHaveAttribute("data-state", "current");
    await expect(page.getByTestId("wz-prov-template")).toHaveText("not chosen");
    await expect(page.getByTestId("wz-prov-instance")).toHaveText("—");
    await expect(page.getByTestId("wz-prov-paper")).toHaveText("not started");
    await expect(page.getByTestId("wz-link-chart")).not.toContainText("↗");
    await page.getByTestId("wz-link-live").click();
    await expect(page).toHaveURL(/tab=trade&view=paper/);
    await page.goto(BUILD);
    await page.getByTestId("wz-link-chart").click(SLOW);
    await expect(page).toHaveURL(/tab=trade&view=chart/);
  });

  test("WZ-2 thirteen cards from the catalog, each mini payoff drawn from the template's own illustration", async ({ page }) => {
    await setup(page);
    await page.goto(BUILD);
    const cards = page.getByTestId("wz-card");
    await expect(cards).toHaveCount(13, SLOW);
    for (const t of CATALOG.templates as Array<{ name: string; label: string; intent: string; illustration: { points: unknown[] } }>) {
      const c = page.locator(`[data-testid="wz-card"][data-name="${t.name}"]`);
      await expect(c, t.name).toContainText(t.label);
      await expect(c.getByTestId("wz-card-intent")).toHaveText(t.intent);
      await expect(c.getByTestId("wz-card-payoff")).toHaveAttribute("data-points", String(t.illustration.points.length));
    }
    await expect(page.locator('[data-testid="wz-card"][data-name="bull_call_spread"]').getByTestId("wz-card-risk")).toHaveText("2 legs · Defined risk");
    await expect(page.locator('[data-testid="wz-card"][data-name="covered_call"]').getByTestId("wz-card-risk")).toHaveText("2 legs · Loss runs to a price of zero");
    await expect(page.locator('[data-testid="wz-card"][data-name="short_future"]').getByTestId("wz-card-risk")).toHaveText("1 leg · Unbounded loss");
    await expect(page.locator('[data-testid="wz-card"][data-name="collar"]').getByTestId("wz-card-tag")).toHaveText(["Neutral", "Hedging"]);
  });

  test("WZ-3 the intent filter shows exactly the catalog's tagged templates", async ({ page }) => {
    await setup(page);
    await page.goto(BUILD);
    await expect(page.getByTestId("wz-card")).toHaveCount(13, SLOW);
    for (const intent of ["bullish", "bearish", "neutral", "income", "hedging"]) {
      await page.getByTestId(`wz-intent-${intent}`).click();
      const want = (CATALOG.templates as Array<{ name: string; tags: string[] }>).filter((t) => t.tags.includes(intent)).map((t) => t.name);
      await expect(page.getByTestId("wz-card"), intent).toHaveCount(want.length);
      const got = await page.getByTestId("wz-card").evaluateAll((els) => els.map((e) => e.getAttribute("data-name")));
      expect(got, intent).toEqual(want);
    }
    await page.getByTestId("wz-intent-volatility").click();
    await expect(page.getByTestId("wz-templates-none")).toContainText("No template in the catalog for this intent yet");
    await page.getByTestId("wz-intent-all").click();
    await expect(page.getByTestId("wz-card")).toHaveCount(13);
  });

  test("WZ-4 existing strategies: real count, sources, statuses derived from state, legs lines, versions, P/L colours, expired flag", async ({ page }) => {
    await setup(page);
    await page.goto(BUILD);
    const rows = page.getByTestId("wz-row");
    await expect(rows).toHaveCount(9, SLOW);
    await expect(page.getByTestId("wz-existing-count")).toHaveText("9 strategies · open one to review and edit");
    const row = (key: string) => page.locator(`[data-testid="wz-row"][data-key="${key}"]`);
    // A saved plan an open desk paper trade cites (strategy_plan_id): PAPER LIVE, with that trade's net P/L.
    await expect(row("plan:sp-1").getByTestId("wz-row-status")).toHaveText("PAPER LIVE");
    await expect(row("plan:sp-1").getByTestId("wz-row-pnl")).toHaveText("+₹1,241");
    await expect(row("plan:sp-1").getByTestId("wz-row-pnl")).toHaveAttribute("data-sign", "pos");
    await expect(row("plan:sp-1").getByTestId("wz-row-legs")).toHaveText("B 24300 PE 25 Nov · S 24400 PE 25 Nov", SLOW);
    await expect(row("plan:sp-1").getByTestId("wz-row-source")).toHaveText("YOU");
    await expect(row("plan:sp-cc").getByTestId("wz-row-status")).toHaveText("SAVED");
    await expect(row("plan:sp-cc").getByTestId("wz-row-ver")).toHaveText("v1");
    await expect(row("plan:sp-cc").getByTestId("wz-row-legs")).toHaveText("B CASH · S 24700 CE 25 Nov");
    await expect(row("plan:sp-cc").getByTestId("wz-row-pnl")).toHaveText("—");
    await expect(row("plan:sp-old").getByTestId("wz-row-expired")).toContainText("Expired contracts (20 Oct)");
    await expect(row("ai:ai-draft01").getByTestId("wz-row-status")).toHaveText("DRAFT");
    await expect(row("ai:ai-pass001").getByTestId("wz-row-status")).toHaveText("BACKTEST PASSED");
    await expect(row("ai:ai-runs001").getByTestId("wz-row-status")).toHaveText("BACKTESTED");
    await expect(row("ai:ai-paper01").getByTestId("wz-row-status")).toHaveText("PAPER LIVE");
    await expect(row("ai:ai-paper01").getByTestId("wz-row-ver")).toHaveText("v3");
    await expect(row("ai:ai-paper01").getByTestId("wz-row-pnl")).toHaveText("−₹820");
    await expect(row("ai:ai-paper01").getByTestId("wz-row-pnl")).toHaveAttribute("data-sign", "neg");
    await expect(row("ai:ai-paper01").getByTestId("wz-row-source")).toHaveText("AI");
    await expect(row("ai:ai-paper01").getByTestId("wz-row-legs")).toHaveText("Rule set · no legs");
    await expect(row("sb:sb-breakout1").getByTestId("wz-row-name")).toContainText("Breakout screen");
    await expect(row("sb:sb-breakout1").getByTestId("wz-row-status")).toHaveText("SAVED");
    await expect(row("sb:sb-breakout1").getByTestId("wz-row-source")).toHaveText("YOU");
    await expect(row("trade:pt-ai0001").getByTestId("wz-row-source")).toHaveText("AI");
    await expect(row("trade:pt-ai0001").getByTestId("wz-row-name")).toContainText("AI Bull call spread");
    await expect(row("trade:pt-ai0001").getByTestId("wz-row-legs")).toHaveText("B 24500 CE 25 Nov · S 24700 CE 25 Nov");
    await expect(row("trade:pt-ai0001").getByTestId("wz-row-pnl")).toHaveText("−₹310");
    // Tones: PAPER LIVE green, BACKTEST PASSED blue, BACKTESTED blue outline, DRAFT amber, SAVED grey; AI blue, YOU green.
    await expect(row("ai:ai-pass001").getByTestId("wz-row-status")).toHaveAttribute("data-tone", "blue");
    await expect(row("ai:ai-runs001").getByTestId("wz-row-status")).toHaveAttribute("data-tone", "blue-outline");
    await expect(row("ai:ai-draft01").getByTestId("wz-row-status")).toHaveAttribute("data-tone", "amber");
    await expect(row("plan:sp-cc").getByTestId("wz-row-status")).toHaveAttribute("data-tone", "grey");
    await expect(row("plan:sp-1").getByTestId("wz-row-status")).toHaveAttribute("data-tone", "mint");
    await expect(row("plan:sp-1").getByTestId("wz-row-source")).toHaveAttribute("data-tone", "mint");
    await expect(row("ai:ai-draft01").getByTestId("wz-row-source")).toHaveAttribute("data-tone", "blue");
    await expect(row("plan:sp-1").getByTestId("wz-row-open")).toHaveText("Open ↗");
  });

  test("WZ-5 with nothing saved: the empty line", async ({ page }) => {
    await setup(page, { empty: true });
    await page.goto(BUILD);
    await expect(page.getByTestId("wz-existing-none")).toHaveText("No saved or AI strategies yet. Pick a template above.", SLOW);
    await expect(page.getByTestId("wz-existing-count")).toHaveText("0 strategies · open one to review and edit");
  });

  test("WZ-6 configure: chain strikes by rule, anchor and width; quick stats from payoff-v2; entry choices; build limits", async ({ page }) => {
    await setup(page);
    await toConfigure(page);
    await expect(page.getByTestId("wz-step-btn-1")).toHaveAttribute("data-state", "done");
    await expect(page.getByTestId("wz-step-btn-2")).toHaveAttribute("data-state", "current");
    await expect(page.getByTestId("wz-prov-template")).toHaveText("Bull call spread");
    await expect(page.getByTestId("wz-prov-instance")).toHaveText("unsaved");
    await expect(page.getByTestId("wz-spot")).toContainText("NIFTY 24,480");
    await expect(page.getByTestId("wz-spot")).toContainText("last close, NSE bhavcopy of 27 Oct");
    await expect(page.getByTestId(`wz-expiry-${NOV}`)).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("wz-quick-maxprofit")).toHaveText("₹8,625", SLOW);
    await expect(page.getByTestId("wz-quick-maxloss")).toHaveText("−₹6,375");
    await expect(page.getByTestId("wz-quick-be")).toHaveText("24,585");
    await expect(page.getByTestId("wz-quick-rr")).toHaveText("1.35 : 1");
    await expect(page.getByTestId("wz-quick-pop")).toHaveText(/^\d{1,3}% \(model\)$/);
    await page.getByTestId("wz-rule-otm").click();
    await expect(page.getByTestId("wz-preview-legs")).toHaveText("B 24600 CE 25 Nov · S 24800 CE 25 Nov");
    await page.getByTestId("wz-width-plus").click();
    await expect(page.getByTestId("wz-preview-legs")).toHaveText("B 24600 CE 25 Nov · S 24900 CE 25 Nov");
    // By delta: the call nearest |Δ| 0.30 in the chain (24800, Δ 0.29), the short call the width (2) above it.
    await page.getByTestId("wz-width-minus").click();
    await page.getByTestId("wz-rule-delta").click();
    await expect(page.getByTestId("wz-preview-legs")).toHaveText("B 24800 CE 25 Nov · S 25000 CE 25 Nov");
    await expect(page.getByTestId("wz-entry-mid")).toBeDisabled();
    await expect(page.getByTestId("wz-entry-open")).toBeDisabled();
    await expect(page.getByTestId("wz-entry-market")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("wz-slippage")).toContainText("0.05% a side");
    await expect(page.getByTestId("wz-limits-note")).toHaveText("Build constraints for this structure, not risk policy: the risk service still decides with your profile.");
    await page.getByTestId("wz-max-loss").fill("5000");
    await expect(page.getByTestId("wz-limits").locator("li").first()).toHaveAttribute("data-ok", "false");
    await expect(page.getByTestId("wz-limits")).toContainText("is over your build limit ₹5,000");
    await page.getByTestId("wz-max-loss").fill("10000");
    await expect(page.getByTestId("wz-limits").locator("li").first()).toHaveAttribute("data-ok", "true");
  });

  test("WZ-7 the leg editor: strike stepper, per-leg expiry, lots, cash flow, side, add and clear", async ({ page }) => {
    const seen = await setup(page);
    await toReview(page);
    const legs = page.getByTestId("wz-leg");
    await expect(legs.nth(0)).toHaveAttribute("data-strike", "24500");
    await expect(legs.nth(0).getByTestId("wz-leg-price")).toHaveText("180");
    await expect(legs.nth(0).getByTestId("wz-leg-cashflow")).toHaveText("−₹13,500");
    await expect(legs.nth(1).getByTestId("wz-leg-cashflow")).toHaveText("+₹7,125");
    await legs.nth(1).getByTestId("wz-leg-strike-plus").click();
    await expect(legs.nth(1)).toHaveAttribute("data-strike", "24800");
    await expect(legs.nth(1).getByTestId("wz-leg-price")).toHaveText("65");
    await legs.nth(1).getByTestId("wz-leg-strike-minus").click();
    await expect(legs.nth(1)).toHaveAttribute("data-strike", "24700");
    await legs.nth(0).getByTestId("wz-leg-lots-plus").click();
    await expect(legs.nth(0)).toHaveAttribute("data-lots", "2");
    await expect(legs.nth(0).getByTestId("wz-leg-cashflow")).toHaveText("−₹27,000");
    await legs.nth(0).getByTestId("wz-leg-side").click();
    await expect(legs.nth(0)).toHaveAttribute("data-side", "sell");
    await expect(legs.nth(0).getByTestId("wz-leg-cashflow")).toHaveText("+₹27,000");
    await legs.nth(0).getByTestId("wz-leg-side").click();
    // Per-leg expiry: the 30 Dec chip reprices that leg from the 30 Dec chain; the engine refuses a calendar, said plainly.
    await expect(legs.nth(1).getByTestId(`wz-leg-expiry-${NOV}`)).toHaveAttribute("aria-pressed", "true");
    await legs.nth(1).getByTestId(`wz-leg-expiry-${DEC}`).click();
    await expect(legs.nth(1)).toHaveAttribute("data-expiry", DEC, SLOW);
    await expect(legs.nth(1).getByTestId("wz-leg-price")).toHaveText("152");
    expect(seen.chains).toContain(DEC);
    await expect(page.getByTestId("wz-payoff-invalid")).toContainText("calendar structures are not supported", SLOW);
    await expect(page.getByTestId("wz-sum-legs")).toHaveText("2 · 25 Nov, 30 Dec");
    await expect(page.getByTestId("wz-legs-line")).toHaveText("B 24500 CE 25 Nov · S 24700 CE 30 Dec");
    await legs.nth(1).getByTestId(`wz-leg-expiry-${NOV}`).click();
    await expect(legs.nth(1)).toHaveAttribute("data-expiry", NOV);
    await page.getByTestId("wz-add-cash").click();
    await expect(legs).toHaveCount(3);
    await expect(legs.nth(2)).toHaveAttribute("data-kind", "cash");
    await expect(legs.nth(2).getByTestId("wz-leg-price")).toHaveText("24,480");
    await page.getByTestId("wz-add-future").click();
    await expect(legs.nth(3)).toHaveAttribute("data-kind", "future");
    await expect(legs.nth(3).getByTestId("wz-leg-price")).toHaveText("24,560");
    await legs.nth(3).getByTestId("wz-leg-more").click();
    await page.getByTestId("wz-leg-details").getByTestId("wz-leg-remove").click();
    await expect(legs).toHaveCount(3);
    await expect(page.getByTestId("wz-legs-note")).toContainText("One lot is 75 shares.");
    await expect(page.getByTestId("wz-legs-note")).toContainText("Option prices are the chain prices: the NSE close of 27 Oct");
    await page.getByTestId("wz-clear-legs").click();
    await expect(legs).toHaveCount(0);
    await expect(page.getByTestId("wz-legs-empty")).toBeVisible();
  });

  test("WZ-8 the payoff card: title, spot, BE, both curves; the scenario slider moves both P/L tiles; it is the only slider", async ({ page }) => {
    await setup(page);
    await toReview(page);
    const card = page.getByTestId("wz-payoff");
    await expect(card).toContainText(/payoff · nearest expiry 25 Nov — at expiry ·· today/i);
    await expect(page.getByTestId("wz-payoff-spot")).toHaveText("Spot 24,480");
    await expect(page.getByTestId("wz-payoff-expiry")).toBeVisible(SLOW);
    await expect(page.getByTestId("wz-payoff-today")).toBeVisible();
    await expect(page.getByTestId("wz-payoff-be")).toHaveCount(1);
    const exp0 = Number(await page.getByTestId("wz-pl-expiry").getAttribute("data-value"));
    const today0 = Number(await page.getByTestId("wz-pl-today").getAttribute("data-value"));
    expect(exp0).toBeLessThan(0);
    await page.getByTestId("wz-scenario").fill("5");
    await expect(page.getByTestId("wz-scenario-label")).toHaveText("+5.0% → 25,704");
    await expect(page.getByTestId("wz-pl-expiry")).not.toHaveAttribute("data-value", String(exp0));
    await expect(page.getByTestId("wz-pl-today")).not.toHaveAttribute("data-value", String(today0));
    expect(Number(await page.getByTestId("wz-pl-expiry").getAttribute("data-value"))).toBeGreaterThan(0);
    await expect(page.getByTestId("wz-payoff-scenario")).toHaveCount(1);
    await expect(page.getByTestId("wz").locator('input[type="range"]')).toHaveCount(1);
    await expect(page.getByTestId("wz-scenario")).toHaveAttribute("aria-label", /scenario tool, not a risk setting/);
  });

  test("WZ-9 summary and Greeks from the route; margin: Kite login needed, then the calculator's figure", async ({ page }) => {
    await setup(page);
    await toReview(page);
    await expect(page.getByTestId("wz-sum-premium")).toHaveText("Debit ₹6,375", SLOW);
    await expect(page.getByTestId("wz-sum-cash")).toHaveText("—");
    await expect(page.getByTestId("wz-sum-maxprofit")).toHaveText("₹8,625");
    await expect(page.getByTestId("wz-sum-maxloss")).toHaveText("−₹6,375");
    await expect(page.getByTestId("wz-sum-be")).toHaveText("24,585");
    await expect(page.getByTestId("wz-sum-pop")).toHaveText(/^\d{1,3}% \(model\)$/);
    await expect(page.getByTestId("wz-sum-rr")).toHaveText("1.35 : 1");
    await expect(page.getByTestId("wz-sum-costs")).toHaveText("₹77 round trip");
    await expect(page.getByTestId("wz-sum-legs")).toHaveText("2 · 25 Nov");
    await expect(page.getByTestId("wz-sum-margin")).toHaveText("₹6,499 capital at risk", SLOW);
    await expect(page.getByTestId("wz-summary-notes")).toContainText("Kite login needed");
    await expect(page.getByTestId("wz-greek-delta")).toHaveText("+17 sh");
    await expect(page.getByTestId("wz-greek-theta")).toHaveText("−₹51");
    await expect(page.getByTestId("wz-greek-vega")).toHaveText("+₹2");
    await expect(page.getByTestId("wz-greek-iv")).toHaveText("4.7–5.2% per leg");
  });

  test("WZ-9b margin from Zerodha's calculator when the Kite session exists", async ({ page }) => {
    await setup(page, { margin: { status: 200, body: { required_margin: 41250.5, initial_margin: 40000, charges: { total: { total: 59.4 } }, source: "Zerodha margin calculator", note: "Nothing is placed." } } });
    await toReview(page);
    await expect(page.getByTestId("wz-sum-margin")).toHaveText("₹41,251 margin", SLOW);
  });

  test("WZ-10 checks: the risk service allows; the check carries the structure", async ({ page }) => {
    const seen = await setup(page);
    await toReview(page);
    await expect(page.getByTestId("wz-checks-risk")).toContainText("Within your risk limits. Paper only, no broker order is created.", SLOW);
    await expect(page.getByTestId("wz-checks-risk")).toHaveAttribute("data-tone", "ok");
    await expect(page.getByTestId("wz-checks-snapshot")).toContainText("Chain snapshot is the NSE close of 27 Oct (1 day old). Premiums are end-of-day closes, not quotes.");
    const b = seen.checks[seen.checks.length - 1] as { kind: string; family: string; direction: string; underlying: string; legs: Array<Record<string, unknown>> };
    expect(b.kind).toBe("strategy");
    expect(b.family).toBe("bull_call_spread");
    expect(b.direction).toBe("bullish");
    expect(b.underlying).toBe("NIFTY");
    expect(b.legs.map((l) => [l.side, l.option_type, l.strike, l.expiry, l.lots, l.lot_size, l.entry_price])).toEqual([["buy", "call", 24500, NOV, 1, 75, 180], ["sell", "call", 24700, NOV, 1, 75, 95]]);
  });

  test("WZ-11 checks: reduce with the size, block with the reasons, a 422 in words", async ({ page }) => {
    await setup(page, { check: { ...ALLOW, outcome: "reduce", requested_lots: 2, approved_lots: 1, reasons: [{ code: "per_trade_risk", message: "Per-trade risk caps it at 1 lot per leg.", severity: "reduce" }] } });
    await toReview(page);
    await expect(page.getByTestId("wz-checks-risk")).toContainText("allows 1 lot per leg (you asked 2)", SLOW);
    await expect(page.getByTestId("wz-checks-risk")).toHaveAttribute("data-tone", "warn");
    await page.unroute("**/api/desk/paper-trades/check");
    await page.route("**/api/desk/paper-trades/check", (r) => json(r, { ...ALLOW, outcome: "block", reasons: [{ code: "open_risk", message: BLOCK_REASON, severity: "block" }] }));
    await page.getByTestId("wz-leg").nth(0).getByTestId("wz-leg-lots-plus").click();
    await expect(page.getByTestId("wz-checks-risk")).toHaveAttribute("data-tone", "bad", SLOW);
    await expect(page.getByTestId("wz-risk-reason")).toHaveText([BLOCK_REASON]);
    await page.unroute("**/api/desk/paper-trades/check");
    await page.route("**/api/desk/paper-trades/check", (r) => json(r, { detail: { code: "naked_short_option", message: "A short option with no cover is not allowed." } }, 422));
    await page.getByTestId("wz-leg").nth(0).getByTestId("wz-leg-side").click();
    await expect(page.getByTestId("wz-checks-risk")).toContainText("Not accepted as a paper trade: A short option with no cover is not allowed.", SLOW);
  });

  test("WZ-12 the chain picker: + Call opens it on the leg's expiry; B / S add legs; again adds a lot; walls, spot, missing quote, expiry switch", async ({ page }) => {
    await setup(page);
    await toReview(page);
    await page.getByTestId("wz-add-call").click();
    const ch = page.getByTestId("wz-chain");
    await expect(ch).toBeVisible();
    await expect(ch).toHaveAttribute("role", "dialog");
    await expect(page.getByTestId(`wz-chain-expiry-${NOV}`)).toHaveAttribute("aria-pressed", "true", SLOW);
    await expect(page.locator('[data-testid="wz-chain-row"][data-atm="true"]')).toHaveAttribute("data-strike", "24500");
    await expect(page.getByTestId("wz-chain-spot")).toHaveText("Spot 24,480");
    await expect(page.locator('[data-testid="wz-chain-row"][data-strike="25000"]').getByTestId("wz-chain-tag-R")).toBeVisible();
    await expect(page.locator('[data-testid="wz-chain-row"][data-strike="24000"]').getByTestId("wz-chain-tag-S")).toBeVisible();
    await expect(page.getByTestId("wz-chain-age")).toContainText("NSE close of 27 Oct · 1 day old");
    await expect(page.getByTestId("wz-chain-age")).toHaveAttribute("data-stale", "false");
    // The legs already in the editor are highlighted.
    await expect(page.getByTestId("wz-chain-call-buy-24500")).toHaveAttribute("data-added", "true");
    await expect(page.getByTestId("wz-chain-call-sell-24700")).toHaveAttribute("data-added", "true");
    await page.getByTestId("wz-chain-call-buy-24600").click();
    await expect(page.getByTestId("wz-chain-call-buy-24600")).toHaveAttribute("data-added", "true");
    await page.getByTestId("wz-chain-call-buy-24600").click();
    await page.getByTestId("wz-chain-put-sell-24400").click();
    await expect(page.getByTestId("wz-chain-put-px-24300")).toHaveText("—");
    await expect(page.getByTestId("wz-chain-put-buy-24300")).toBeDisabled();
    await page.getByTestId(`wz-chain-expiry-${DEC}`).click();
    await expect(page.getByTestId(`wz-chain-expiry-${DEC}`)).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("wz-chain-call-px-24500")).toHaveText("288", SLOW);
    await expect(page.getByTestId("wz-chain-call-buy-24500")).toHaveAttribute("data-added", "false");
    await page.getByTestId("wz-chain-close").click();
    const legs = page.getByTestId("wz-leg");
    await expect(legs).toHaveCount(4);
    await expect(legs.nth(2)).toHaveAttribute("data-strike", "24600");
    await expect(legs.nth(2)).toHaveAttribute("data-lots", "2");
    await expect(legs.nth(2)).toHaveAttribute("data-side", "buy");
    await expect(legs.nth(2).getByTestId("wz-leg-price")).toHaveText("130");
    await expect(legs.nth(3)).toHaveAttribute("data-type", "put");
    await expect(legs.nth(3)).toHaveAttribute("data-side", "sell");
    await expect(legs.nth(3)).toHaveAttribute("data-strike", "24400");
    await page.getByTestId("wz-add-put").click();
    await expect(page.getByTestId("wz-chain")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("wz-chain")).toHaveCount(0);
  });

  test("WZ-12b an old chain is labelled stale and its prices are estimates", async ({ page }) => {
    await setup(page, { asOf: "2026-10-20" });
    await toReview(page);
    await expect(page.getByTestId("wz-legs-note")).toContainText("8 days old), so option prices are estimates, not quotes", SLOW);
    await page.getByTestId("wz-from-chain").click();
    await expect(page.getByTestId("wz-chain-age")).toHaveAttribute("data-stale", "true", SLOW);
    await expect(page.getByTestId("wz-chain-age")).toContainText("stale: prices are estimates, not quotes");
  });

  test("WZ-13 Save version and Clone are disabled with the reason (one store, not yet); the legs stay in the page's state", async ({ page }) => {
    await setup(page);
    await toValidate(page);
    await expect(page.getByTestId("wz-save")).toBeDisabled();
    await expect(page.getByTestId("wz-clone")).toBeDisabled();
    await expect(page.getByTestId("wz-save-note")).toHaveText("Saving arrives with the shared strategy store.");
    await expect(page.getByTestId("wz-prov-instance")).toHaveText("unsaved");
    await expect(page.getByTestId("wz-instance-legs")).toHaveText("B 24500 CE 25 Nov · S 24700 CE 25 Nov");
    // Edited legs survive every step change: back to 3, to 1, to 2 (no setting changed, so no rebuild), to 3 and 4.
    await page.getByTestId("wz-adjust").click();
    await page.getByTestId("wz-leg").nth(1).getByTestId("wz-leg-strike-plus").click();
    await expect(page.getByTestId("wz-leg").nth(1)).toHaveAttribute("data-strike", "24800");
    await page.getByTestId("wz-step-btn-1").click();
    await expect(page.getByTestId("wz-step-1")).toBeVisible();
    await page.getByTestId("wz-step-btn-2").click();
    await expect(page.getByTestId("wz-preview-legs")).toHaveText("B 24500 CE 25 Nov · S 24800 CE 25 Nov");
    await page.getByTestId("wz-step-btn-3").click();
    await expect(page.getByTestId("wz-leg").nth(1)).toHaveAttribute("data-strike", "24800");
    await page.getByTestId("wz-step-btn-4").click();
    await expect(page.getByTestId("wz-instance-legs")).toHaveText("B 24500 CE 25 Nov · S 24800 CE 25 Nov");
    // A setting changed in step 2 does rebuild, by the user's own action.
    await page.getByTestId("wz-step-btn-2").click();
    await page.getByTestId("wz-rule-otm").click();
    await expect(page.getByTestId("wz-preview-legs")).toHaveText("B 24600 CE 25 Nov · S 24800 CE 25 Nov");
  });

  test("WZ-14 start the simulated trade: Idempotency-Key, the template cited; allow opens it on the strip and the monitor", async ({ page }) => {
    const seen = await setup(page);
    await toValidate(page);
    await expect(page.getByTestId("wz-gate-payoff")).toHaveAttribute("data-ok", "true", SLOW);
    await expect(page.getByTestId("wz-gate-risk")).toHaveAttribute("data-ok", "true", SLOW);
    await expect(page.getByTestId("wz-start")).toBeEnabled();
    await page.getByTestId("wz-start").click();
    await expect(page.getByTestId("wz-answer")).toHaveAttribute("data-outcome", "allow", SLOW);
    expect(seen.keys[0]).toBeTruthy();
    const body = seen.posts[0] as { kind: string; signal: { source_refs: Array<{ kind: string; ref: string }> }; family: string };
    expect(body.kind).toBe("strategy");
    expect(body.family).toBe("bull_call_spread");
    expect(body.signal.source_refs[0]).toMatchObject({ kind: "strategy_template", ref: "bull_call_spread" });
    await expect(page.getByTestId("wz-prov-paper")).toHaveText("open · pt-new", SLOW);
    await expect(page.getByTestId("wz-monitor-id")).toHaveText("pt-new");
    await expect(page.getByTestId("wz-monitor-dte")).toHaveText("28");
    await page.getByTestId("wz-monitor-live").click();
    await expect(page).toHaveURL(/view=paper/);
  });

  test("WZ-14b the POST answers reduce (Accept N lots per leg?) and block (the reasons); nothing recorded", async ({ page }) => {
    const reduce = { status: 409, body: { detail: { code: "risk_reduce", outcome: "reduce", requested_lots: 2, approved_lots: 1, reasons: [{ code: "per_trade_risk", message: "Per-trade risk caps it at 1 lot per leg.", severity: "reduce" }], message: "MOCK" } } };
    const block = { status: 409, body: { detail: { code: "risk_blocked", outcome: "block", reasons: [{ code: "open_risk", message: BLOCK_REASON, severity: "block" }], message: BLOCK_REASON } } };
    const seen = await setup(page, { post: [reduce, block] });
    await toReview(page);
    for (let i = 0; i < 2; i++) await page.getByTestId("wz-leg").nth(i).getByTestId("wz-leg-lots-plus").click();
    await page.getByTestId("wz-to-validate").click();
    await expect(page.getByTestId("wz-start")).toBeEnabled(SLOW);
    await page.getByTestId("wz-start").click();
    await expect(page.getByTestId("wz-answer")).toHaveAttribute("data-outcome", "reduce", SLOW);
    await expect(page.getByTestId("wz-answer-text")).toContainText("allows 1 lot(s) per leg (you asked 2). Nothing was recorded.");
    await page.getByTestId("wz-accept-reduce").click();
    await expect(page.getByTestId("wz-instance-legs")).toHaveText("B 24500 CE 25 Nov · S 24700 CE 25 Nov");
    await expect(page.getByTestId("wz-start")).toBeEnabled(SLOW);
    await page.getByTestId("wz-start").click();
    await expect(page.getByTestId("wz-answer")).toHaveAttribute("data-outcome", "block", SLOW);
    await expect(page.getByTestId("wz-answer-reason")).toHaveText([BLOCK_REASON]);
    expect(seen.keys[0]).toBeTruthy();
    expect(seen.keys[1]).toBeTruthy();
    expect((seen.posts[1] as { legs: Array<{ lots: number }> }).legs.map((l) => l.lots)).toEqual([1, 1]);
    await expect(page.getByTestId("wz-prov-paper")).toHaveText("not started");
  });

  test("WZ-15 Open on an existing strategy lands on step 3 with its legs; steps 1 and 2 done; provenance from its source", async ({ page }) => {
    await setup(page);
    await page.goto(BUILD);
    await page.locator('[data-testid="wz-row"][data-key="trade:pt-ai0001"]').getByTestId("wz-row-open").click(SLOW);
    await expect(page.getByTestId("wz-step-3")).toBeVisible(SLOW);
    await expect(page.getByTestId("wz-step-btn-1")).toHaveAttribute("data-state", "done");
    await expect(page.getByTestId("wz-step-btn-2")).toHaveAttribute("data-state", "done");
    await expect(page.getByTestId("wz-step-btn-3")).toHaveAttribute("data-state", "current");
    const legs = page.getByTestId("wz-leg");
    await expect(legs).toHaveCount(2);
    await expect(legs.nth(0)).toHaveAttribute("data-strike", "24500");
    await expect(legs.nth(1)).toHaveAttribute("data-strike", "24700");
    await expect(page.getByTestId("wz-prov-template")).toHaveText("AI-generated / Bull call spread");
    await expect(page.getByTestId("wz-prov-paper")).toHaveText("open · pt-ai0001");
    await page.getByTestId("wz-step-btn-1").click();
    await page.locator('[data-testid="wz-row"][data-key="plan:sp-cc"]').getByTestId("wz-row-open").click(SLOW);
    await expect(page.getByTestId("wz-prov-instance")).toHaveText("saved plan v1");
    await expect(page.getByTestId("wz-prov-template")).toHaveText("Covered call");
    await expect(page.getByTestId("wz-leg").nth(0)).toHaveAttribute("data-kind", "cash");
    await page.getByTestId("wz-step-btn-1").click();
    await page.locator('[data-testid="wz-row"][data-key="ai:ai-draft01"]').getByTestId("wz-row-open").click(SLOW);
    await expect(page.getByTestId("wz-no-legs")).toContainText("rule set");
    await expect(page.getByTestId("wz-leg")).toHaveCount(0);
    await page.getByTestId("wz-step-btn-1").click();
    await page.locator('[data-testid="wz-row"][data-key="sb:sb-breakout1"]').getByTestId("wz-row-open").click(SLOW);
    await expect(page.getByTestId("wz-no-legs")).toContainText("A Strategy Builder strategy is a rule set over shares");
  });

  test("WZ-16 expired legs: said on step 3; the same strikes on the nearest expiry only by an explicit button", async ({ page }) => {
    await setup(page);
    await page.goto(BUILD);
    await page.locator('[data-testid="wz-row"][data-key="plan:sp-old"]').getByTestId("wz-row-open").click(SLOW);
    await expect(page.getByTestId("wz-expired")).toContainText("expired (20 Oct)", SLOW);
    await expect(page.getByTestId("wz-leg").nth(0)).toHaveAttribute("data-expiry", "2026-10-20");
    await page.getByTestId("wz-expired-move").click();
    await expect(page.getByTestId("wz-leg").nth(0)).toHaveAttribute("data-expiry", NOV);
    await expect(page.getByTestId("wz-leg").nth(0).getByTestId("wz-leg-price")).toHaveText("180");
    await expect(page.getByTestId("wz-leg").nth(1).getByTestId("wz-leg-price")).toHaveText("95");
    await expect(page.getByTestId("wz-expired")).toHaveCount(0);
  });

  test("WZ-17 wording: no picks, suggested or recommended in the wizard's own words", async ({ page }) => {
    await setup(page);
    await page.goto(BUILD);
    await expect(page.getByTestId("wz-card")).toHaveCount(13, SLOW);
    const BANNED = /\bpicks\b|suggest|recommend/i;
    expect(await page.getByTestId("wz").innerText()).not.toMatch(BANNED);
    await page.locator('[data-testid="wz-card"][data-name="bull_call_spread"]').click();
    await expect(page.getByTestId("wz-quick-maxprofit")).toHaveText("₹8,625", SLOW);
    expect(await page.getByTestId("wz").innerText()).not.toMatch(BANNED);
    await page.getByTestId("wz-to-review").click();
    await expect(page.getByTestId("wz-checks-risk")).toHaveAttribute("data-tone", "ok", SLOW);
    expect(await page.getByTestId("wz").innerText()).not.toMatch(BANNED);
    await page.getByTestId("wz-to-validate").click();
    expect(await page.getByTestId("wz").innerText()).not.toMatch(BANNED);
  });

  test("WZ-18 390 px: no horizontal page scroll on any step; the chain picker is full screen", async ({ page }) => {
    await setup(page, { phone: true });
    await page.goto(BUILD);
    await expect(page.getByTestId("wz-row")).toHaveCount(9, SLOW);
    await noSideScroll(page);
    await page.locator('[data-testid="wz-card"][data-name="bull_call_spread"]').click();
    await expect(page.getByTestId("wz-quick-maxprofit")).toHaveText("₹8,625", SLOW);
    await noSideScroll(page);
    await page.getByTestId("wz-to-review").click();
    await expect(page.getByTestId("wz-checks-risk")).toHaveAttribute("data-tone", "ok", SLOW);
    await noSideScroll(page);
    await page.getByTestId("wz-add-call").click();
    await expect(page.getByTestId("wz-chain")).toHaveAttribute("data-mobile", "true");
    const box = await page.getByTestId("wz-chain").boundingBox();
    expect(box?.width).toBeGreaterThanOrEqual(389);
    await page.getByTestId("wz-chain-close").click();
    await page.getByTestId("wz-to-validate").click();
    await expect(page.getByTestId("wz-step-4")).toBeVisible();
    await noSideScroll(page);
  });

  test("WZ-19 kept flows: an idea's ticket above the wizard; From an idea folded, opened by the builder's params", async ({ page }) => {
    await setup(page);
    await page.goto(BUILD);
    await expect(page.getByTestId("wz")).toBeVisible(SLOW);
    await expect(page.getByTestId("td-ticket")).toHaveCount(0);
    await expect(page.getByTestId("td-from-idea")).toHaveAttribute("aria-expanded", "false");
    await expect(page.getByTestId("desk-panel-strategy")).toHaveCount(0);
    await page.getByTestId("td-from-idea").click();
    await expect(page.getByTestId("desk-panel-strategy")).toBeVisible();
    await page.goto(`${BUILD}&tp=tp_missing01`);
    await expect(page.getByTestId("td-ticket")).toBeVisible(SLOW);
    await expect(page.getByTestId("wz")).toBeVisible();
    await page.goto(`${BUILD}&sym=NIFTY&direction=bullish&instrument=options`);
    await expect(page.getByTestId("td-from-idea")).toHaveAttribute("aria-expanded", "true", SLOW);
    await expect(page.getByTestId("desk-panel-strategy")).toBeVisible();
    // The F&O lab's structures (rules-based cards, compare, levels) are folded below; the lab's old link opens them.
    await page.goto(BUILD);
    await expect(page.getByTestId("td-fno-structures")).toHaveAttribute("aria-expanded", "false", SLOW);
    await expect(page.getByTestId("desk-panel-fno")).toHaveCount(0);
    await page.goto("/v5/app/trader/desk?tab=fno&lab=strategies");
    await expect(page).toHaveURL(/section=fno/);
    await expect(page.getByTestId("td-fno-structures")).toHaveAttribute("aria-expanded", "true", SLOW);
    await expect(page.getByTestId("desk-panel-fno")).toBeVisible();
  });
});
