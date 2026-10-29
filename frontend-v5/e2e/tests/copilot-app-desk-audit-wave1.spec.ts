/**
 * Desk audit wave 1 (2026-10-28): W-1 … W-10 of test_reports/desk_audit_wave1_TESTCASES.md.
 * The audit of the live desk against the owner's design (docs/desk_redesign_20261027/AUDIT_live_vs_design_20261028.md, F1 and B3) found:
 * advice wording ("pick"), an "[object Object]" drawer subtitle, "— (—)" index changes, raw floats, routes and file paths, leftover section
 * numbers, doubled reason codes, a "strategy that fits" sized differently from the card, and a 0.19 : 1 strategy labelled VIABLE.
 *
 * The ideas, the cash plan and GET /api/desk/trade-plans/{id} come from `contract-decision-card.json` (backend/tests/
 * test_decision_card_contract.py builds it from the REAL routes on a MOCK world); the market tape is `markets-home.json` (a TEST FIXTURE).
 * Each case changes a clone of them to the shape staging showed (MOCK — not real data). Everything else is an inline MOCK in the
 * route's real shape. Mocked APIs, production build (pw.copilot-app.config.ts).
 */
import { test, expect, type Locator, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { mockApi } from "../helpers/api-mock";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", name), "utf-8"));
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
const CARD = load("contract-decision-card.json");
const HOME = load("markets-home.json");
const DESK = "/v5/app/trader/desk";
const RANKED = `${DESK}?tab=trade&view=scanner&sub=ranked`;
const LIBRARY = `${DESK}?tab=more&view=chartink`;
const LOG = `${DESK}?tab=risk&view=log`;
const SMART = `${DESK}?tab=market&view=smartmoney`;
const INTEL = `${DESK}?tab=market&view=intel`;
const SLOW = { timeout: 15_000 };
const NOW = new Date("2026-10-20T15:00:00+05:30");
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

const IDEA = CARD.cash.ideas_response.ideas[0];
const SYM: string = IDEA.symbol;
const CASH_ID: string = IDEA.trade_plan.plan_id;

/** Words a page must not show (owner rule, SEBI): "pick" / "picks" as advice. */
const PICK = /\bpicks?\b/i;
/** Raw routes, file paths and function names (audit: "GET /api/positional/…", "services/risk_gate/service.py", "…service.decide"). */
const RAW = /GET \/api|POST \/api|services\/|\.py\b|\.decide\b|macro_engine\./;
/** A leftover section number from the old desk ("06 · Smart Money Movement"). */
const SECTION_NO = /(^|\s)0[1-9] · /m;

// ── MOCK — not real data: the routes, as the audit saw them on staging ──

/** The ICICIBANK idea with its preferred strategy and that strategy's `account_size` (POST /ideas, ideas.size_fit). */
function ideasWith(preferred: string, accountSize: Record<string, unknown>, sizing?: Record<string, unknown>) {
  const body = clone(CARD.cash.ideas_response);
  const idea = body.ideas[0];
  idea.preferred = preferred;
  for (const s of idea.strategies) {
    if (s.id !== preferred) continue;
    s.status = "candidate";
    s.account_size = accountSize;
    if (sizing) s.sizing = { ...s.sizing, ...sizing };
  }
  return body;
}
const NOT_SIZABLE = {
  status: "not_sizable", quantity: null, lots: null, unit: "lots per leg", basis: "The universal risk service's own sizing (the same check a submission runs, on the same data).",
  blocking: [{ code: "per_trade_risk_exceeded", check: "per_trade_risk", severity: "block", message: "One lot's loss at the stop is above your per-trade budget of ₹4,908.98." }],
};
const UNSIZED = { status: "incomplete", quantity: null, lots: null, binding: null, missing: ["capital"] };
const SIZED_34 = { status: "sized", quantity: 34, lots: null, unit: "shares", blocking: [], binding: [], factors: [] };

/** GET /api/desk/trade-plans/{cash id}: sized for the account, with the plan builder's raw evidence and its "not sized" notes. */
function cashPlanGet() {
  const r = clone(CARD.cash.trade_plan_response);
  // The sizing basis as the fixed backend words it (plan_sizing.BASIS): the fixture was captured before.
  r.account_size.basis = "The universal risk service's own sizing (the same check a submission runs, on the same data), on your account with no open positions.";
  for (const e of r.plan.evidence.items) {
    if (e.key === "volume") e.text = "Relative volume 1.2966179010676246x; average traded value 1734.5622804300003 Cr a day.";
    if (e.key === "regime") e.text = "Desk regime is Mixed (macro_engine.classify_desk_regime, session 2026-10-19). Mixed or high-volatility regimes do not point one way.";
  }
  r.plan.risk_flags = [
    { code: "warning", message: "Sizing is incomplete (risk_budget_inr (or risk_pct together with capital), capital): the payoff is shown for 1 share." },
    { code: "warning", message: "Reward : risk is judged before costs here: with no capital and risk budget the position is not sized, and on a single share the desk's flat brokerage alone would decide the ratio." },
    { code: "sizing_incomplete", message: "Sizing needs risk_budget_inr (or risk_pct together with capital), capital." },
    { code: "warning", message: "MOCK: another flag that stays." },
  ];
  return r;
}

/** GET /api/markets/home with NIFTY's day change missing (what the live overlay sent before the backend fix). */
function homeNoNiftyChange() {
  const h = clone(HOME);
  const n = h.indices.find((i: { name: string }) => i.name === "Nifty 50");
  n.change = null;
  n.change_pct = null;
  return h;
}

const WATCHLIST = { as_of_date: "2026-10-19", buckets: {
  breakout_confirmed: [{ nse_symbol: SYM, sector: "Financial Services", close_price: 1200, trigger_price: 1190, stop_price: 1160, atr_pct: 1.7, why: "MOCK: closed above the 20-session high." }],
  pre_breakout: [], true_accumulation: [], trend_continuation: [] } };
/** GET /api/positional/picks: a stock only the target list has, read by its stage. */
const PICKS = { signal_date: "2026-10-19", count: 1, picks: [
  { nse_symbol: "ZZIDEA", signal_date: "2026-10-19", final_score: 0.81, confidence: "MEDIUM", stage: "EARLY_BREAKOUT", timeframe_days_min: 3, timeframe_days_max: 10,
    entry_price: 120.0, stoploss: 114.0, target_price: 138.0, risk_reward: 3.0, source_scans: [], reasons: ["MOCK: volume expansion near resistance."],
    spark_closes: [110, 112, 115, 118, 120], spark_end: "2026-10-19", avg_traded_value_cr_20d: 10.0 },
] };

/** The risk profile, status and freshness the desk frame reads (MOCK, the fixture's profile). */
const freshness = { symbol: null, inputs: { market_state: { source: "desk regime (MOCK)", as_of: "2026-10-19", age_sessions: 0, budget: 2, ok: true, reason: null, version: "freshness-v1", status: "ok", regime: "BEAR", vix: 14.2, key: "bearish" } },
  all_ok: true, reference_session: "2026-10-19", as_of: "2026-10-20T09:30:00+00:00", budgets: { market_state: 2 }, freshness_version: "freshness-v1", risk_policy_version: "universal-risk-v1" };

interface Opts { ideas?: unknown; home?: unknown; plan?: unknown; picks?: unknown; chartink?: unknown; decisions?: unknown }

async function setup(page: Page, o: Opts = {}) {
  await page.clock.setFixedTime(NOW);
  await mockApi(page, "populated");
  await page.route("**/api/markets/home", (r) => json(r, o.home ?? HOME));
  await page.route("**/api/chat/**", (r) => json(r, []));
  await page.route("**/api/positional/watchlist*", (r) => json(r, WATCHLIST));
  await page.route("**/api/positional/picks*", (r) => json(r, o.picks ?? { signal_date: "2026-10-19", count: 0, picks: [] }));
  await page.route("**/api/positional/scan-universe*", (r) => json(r, { detail: "MOCK: upstream" }, 500));
  await page.route("**/api/positional/reversal-candidates*", (r) => json(r, { detail: "MOCK: upstream" }, 500));
  await page.route("**/api/move-odds/**", (r) => json(r, { detail: "feature_not_enabled" }, 403));
  await page.route("**/api/live/**", (r) => json(r, { available: false, reason: "MOCK: feed off", quotes: {}, mode: "expired", session: "closed", stale: true }));
  await page.route("**/api/risk/freshness*", (r) => json(r, freshness));
  await page.route("**/api/risk/profile", (r) => json(r, CARD.risk_profile));
  await page.route("**/api/risk/status", (r) => json(r, { kill_switch: false, halted: false, policy_version: "MOCK", scope: "blocks new positions on the AI-trader ticket, desk paper-trade and journal paths (every entry path runs the universal risk service)", not_in_scope: "MOCK", can_reset: false, stored: false }));
  await page.route("**/api/risk/audit*", (r) => json(r, { events: [], count: 0, append_only: true, policy_version: "risk-controls-v1" }));
  await page.route("**/api/risk/live-readiness", (r) => json(r, { detail: "MOCK: not read here" }, 404));
  await page.route("**/api/risk/decisions*", (r) => json(r, o.decisions ?? { count: 0, append_only: true, policy_version: "risk-controls-v1", decisions: [] }));
  await page.route("**/api/admin/**", (r) => json(r, { detail: "MOCK: not admin" }, 403));
  await page.route("**/api/markets/sector-returns", (r) => json(r, { as_of: "2026-10-19", source: "MOCK", sessions: { "1d": 1, "1w": 5, "1m": 21 }, sectors: [] }));
  await page.route("**/api/markets/fii-dii*", (r) => json(r, { ok: true, as_of: "2026-10-19", daily: [], monthly: [] }));
  await page.route("**/api/markets/deals*", (r) => json(r, { ok: true, rows: [], total: 0 }));
  await page.route("**/api/markets/circulars*", (r) => json(r, { ok: true, rows: [], total: 0 }));
  await page.route("**/api/filings/feed*", (r) => json(r, { ok: true, total: 0, facets: {}, rows: [] }));
  await page.route("**/api/desk/strategy/ideas", (r) => json(r, o.ideas ?? CARD.cash.ideas_response));
  await page.route("**/api/desk/strategy/top", (r) => json(r, CARD.fno.top_response));
  await page.route("**/api/desk/strategy/levels", (r) => json(r, { valid: false, version: "strategy-levels-v2", problems: [{ code: "mock", message: "MOCK" }] }));
  await page.route("**/api/desk/strategy/payoff", (r) => json(r, { valid: false, problems: [{ code: "mock", message: "MOCK" }], warnings: [] }));
  await page.route("**/api/desk/strategy/plans*", (r) => json(r, { plans: [], count: 0, limit: 100, max_saved: 200 }));
  await page.route("**/api/desk/trade-plans/*", (r) => {
    const id = decodeURIComponent(new URL(r.request().url()).pathname.split("/").pop() as string);
    if (id === CASH_ID) return json(r, o.plan ?? CARD.cash.trade_plan_response);
    if (id === CARD.fno.trade_plan_response.plan.plan_id) return json(r, CARD.fno.trade_plan_response);
    return json(r, { detail: "plan_not_found" }, 404);
  });
  await page.route("**/api/desk/ai-watchlist*", (r) => json(r, CARD.ai_watchlist_day));
  await page.route("**/api/fno/**", (r) => json(r, { detail: "MOCK: not read here" }, 404));
  await page.route("**/api/desk/alerts*", (r) => json(r, { as_of: "2026-10-19", alerts: [] }));
  await page.route("**/api/desk/paper-account", (r) => json(r, CARD.paper_account));
  await page.route("**/api/desk/paper-trades*", (r) => json(r, { as_of: "2026-10-19", trades: [], summary: null }));
  await page.route("**/api/watchlists", (r) => json(r, { lists: [], limits: { max_lists: 20, max_symbols: 50 }, starter_pending: false }));
  await page.route("**/api/desk/chartink/source", (r) => json(r, { source: CK_SOURCE }));
  await page.route("**/api/desk/chartink/hits", (r) => json(r, CK_HITS));
  await page.route("**/api/desk/chartink/picks*", (r) => json(r, o.chartink ?? CK_BODY));
}

const stockRow = (page: Page) => page.getByTestId(`desk-top10-stock-${SYM}`);
const textOf = async (l: Locator) => (await l.innerText()).replace(/\s+/g, " ");

// ── MOCK — not real data: GET /api/desk/chartink/* (picks-contract.ts), invented names ──
const FETCHED = "2026-10-20T05:00:00+00:00";
const CK_SCAN = { id: "1001", name: "Volume Burst Sample", description: null, kind: "stock_scan", supported: true, unsupported_reason: null, uses_intraday_candles: false, enabled: true, direction: "bullish",
  last_run: { at: FETCHED, ok: true, hits: 1, error: null, seconds: 2.0 } };
const CK_SOURCE = { dashboard_id: "900001", url: "https://chartink.com/dashboard/900001", title: "Sample dashboard", fetched_at: FETCHED, scans: [CK_SCAN],
  summary: { scans: 1, stock_scans: 1, supported: 1, enabled: 1 }, refresh: { last_started_at: null, retry_after_s: null } };
const CK_HITS = { as_of_date: "2026-10-19", fetched_at: FETCHED, mode: "end_of_day_snapshot", scans: [{ id: "1001", name: "Volume Burst Sample", direction: "bullish", hits: 1, ok: true, error: null, uses_intraday_candles: false }],
  symbols: [], is_today: false, age_days: 1, dashboard_id: "900001", empty_reason: "MOCK: no symbols", unknown_symbols: [], source_failures: [] };
const ST = (o: Record<string, unknown>) => ({ segment: "cash", family: "", status: "candidate", reasons: [], legs_text: null, max_loss: null, max_loss_basis: null, capital_at_risk: null, max_profit: null,
  profit_unbounded: false, breakeven: [], reward_risk_net: null, reward_risk_gross: null, actionable: true, liquidity_flags: [], why: null, flags: [], payoff_request: null,
  sizing: { status: "incomplete", quantity: null, lots: null, binding: null, unit: null, risk_budget_inr: null, risk_at_stop_inr: null, deployed_inr: null, missing: ["capital"] }, ...o });
const LOW = ST({ id: "cash:breakout_continuation", label: "Breakout continuation (long)", legs_text: "Buy 1 shares ZEDCO", max_loss: -60, max_profit: 11.4, reward_risk_net: 0.19, reward_risk_gross: 2.0 });
const OK = ST({ id: "options:bull_call_spread", segment: "options", label: "Bull call spread", legs_text: "Buy 1 lot ZEDCO 260 call + Sell 1 lot ZEDCO 280 call, 24 Nov", max_loss: -4000, max_profit: 6560, reward_risk_net: 1.64, reward_risk_gross: 1.7 });
const CK_PICK = { rank: 1, symbol: "ZEDCO", name: "Zed Industries Ltd", source: "chartink", in_ai_scanner: false, ai_score: null, direction: "long", action: "Long idea: the long side of the plan below.",
  outcome: "pick", score: 80, score_label: "evidence score — not a probability", scans: { aligned: [{ id: "1001", name: "Volume Burst Sample", direction: "bullish" }], opposed: [], count: 1 }, factors: [],
  available_weight_pct: 100, reasons_for: [], reasons_against: [], unavailable: [], wait_reasons: [], plan_id: "plan_mock", plan_status: "plan", preferred: "options:bull_call_spread",
  strategies: [LOW, OK], data_as_of: { price: "2026-10-19", fno: "2026-10-19" }, fno_eligible: true, close: 250, plan_inputs: { underlying: "ZEDCO", direction: "bullish", instrument: "all" } };
const CK_BODY = { state: "ok", reason: null, label: "evidence score — not a probability", generated_at: FETCHED, limit: 5, direction_filter: "all", dashboard_id: "900001", rules_version: "strategy-rules.v1.5",
  ranking_note: "Each Chartink stock that passes the eligibility gates is scored on real evidence; the score ranks the evidence and is not a probability.",
  data_as_of: { mode: "end_of_day", chartink: { scan_date: "2026-10-19", fetched_at: FETCHED, mode: "end_of_day_snapshot" }, price: "2026-10-19", fno: "2026-10-19", scan_eligibility: "2026-10-19" },
  considered: 1, evaluated: 1, not_evaluated: 0, qualified: 1, returned: 1, coverage_note: "Scored 1 of the 1 Chartink stocks with a bullish or bearish scan hit.", picks: [CK_PICK],
  wait: [{ ...CK_PICK, symbol: "PLANETX", name: "Planet X Ltd", outcome: "wait", strategies: [], wait_reasons: ["Thin evidence: only 25% of the scoring weight could be read."] }], excluded: [],
  shortfall_reason: null, source_failures: [], caveats: ["Conditional research ideas, not advice and not an instruction to trade."], sent_to_broker: false };

// ── W-1 … W-10 ────────────────────────────────────────────────────────────

test.describe("MOCK — not real data: desk audit wave 1", () => {
  test("W-1 Ranked candidates: a stage-only stock is a 'Scanner idea', and the scanner list says 'pick' nowhere (W-6: no raw routes)", async ({ page }) => {
    await setup(page, { picks: PICKS });
    await page.goto(RANKED);
    const row = page.getByTestId("desk-scan-row-ZZIDEA");
    await expect(row.getByTestId("desk-scan-setup")).toHaveText("Scanner idea · early breakout", SLOW);
    const scanner = page.getByTestId("desk-scanner");
    await expect(scanner).toContainText("The scanner’s universe read did not answer");
    const t = await textOf(scanner);
    expect(t).not.toMatch(PICK);
    expect(t).not.toMatch(RAW);
    expect(t).toContain("Sources: NSE end-of-day scanner (setup watchlist and target list)");
    expect(t).not.toMatch(SECTION_NO);
  });

  test("W-2 / W-10 Signal library: candidates, never picks; a 0.19 : 1 strategy is 'Below your 1.5 minimum', not Viable", async ({ page }) => {
    await setup(page);
    await page.goto(LIBRARY);
    const sec = page.getByTestId("ck-picks");
    await expect(sec.getByTestId("ck-picks-title")).toHaveText("Top candidates from my Chartink scans", SLOW);
    await expect(sec.getByTestId("ck-picks-sub")).toHaveText("Ranked by an evidence score, not a probability. Each candidate comes with strategies.");
    await expect(sec.getByTestId("ck-picks-wait-toggle")).toContainText("evaluated, but not candidates");
    expect(await textOf(sec)).not.toMatch(PICK);

    const rows = sec.getByTestId("ck-pick-strategy");
    await expect(rows).toHaveCount(2);
    const low = sec.locator('[data-testid="ck-pick-strategy"][data-id="cash:breakout_continuation"]');
    const ok = sec.locator('[data-testid="ck-pick-strategy"][data-id="options:bull_call_spread"]');
    await expect(low.getByTestId("ck-pick-strategy-status")).toHaveText("⚠ Below your 1.5 minimum");
    await expect(low.getByTestId("ck-pick-strategy-status")).not.toContainText("Viable");
    await expect(low).toHaveAttribute("data-below-min", "true");
    await expect(low.getByTestId("ck-pick-strategy-summary")).toContainText("Reward : risk 0.19 : 1 net");
    await expect(ok.getByTestId("ck-pick-strategy-status")).toHaveText("✓ Viable");
    await expect(ok).toHaveAttribute("data-below-min", "false");
    await expect(sec.getByTestId("ck-pick-strategies-count")).toContainText("1 viable of 2");
  });

  test("W-10b the route's own verdict wins: meets_min_reward_risk false is below the minimum whatever the ratio", async ({ page }) => {
    const body = clone(CK_BODY);
    body.picks[0].strategies[1] = { ...body.picks[0].strategies[1], meets_min_reward_risk: false, min_reward_risk: 2 };
    await setup(page, { chartink: body });
    await page.goto(LIBRARY);
    const ok = page.locator('[data-testid="ck-pick-strategy"][data-id="options:bull_call_spread"]');
    await expect(ok.getByTestId("ck-pick-strategy-status")).toHaveText("⚠ Below your 2.0 minimum", SLOW);
    await expect(page.getByTestId("ck-pick-strategies-count")).toContainText("0 viable of 2");
  });

  test("W-3 / W-5 / W-9c the idea drawer: the setup's name in the subtitle (no [object Object]); readable evidence; no stale sizing flags on a sized plan", async ({ page }) => {
    await setup(page, { plan: cashPlanGet() });
    await page.goto(DESK);
    await stockRow(page).getByTestId("desk-top10-stock-open").click(SLOW);
    const drawer = page.getByTestId("desk-top10-drawer");
    await expect(drawer).toBeVisible(SLOW);
    await expect(drawer.getByTestId("dc-sec-evidence")).toBeVisible(SLOW);
    const t = await textOf(drawer);
    expect(t).not.toContain("[object Object]");
    expect(t).toMatch(/· Breakout confirmed · scan of /);
    // W-5: the volume evidence with two decimals, and no module name in the regime line.
    // The indicator text is in Technical details now (plain verdicts on the card, owner 29 Oct): readable there too.
    await expect(drawer.getByTestId("dc-ev-raw")).toContainText("Relative volume 1.30x; average traded value 1,734.56 Cr a day.");
    await expect(drawer.getByTestId("dc-ev-raw")).toContainText("Desk regime is Mixed (session 2026-10-19).");
    expect(t).not.toMatch(RAW);
    expect(t).not.toMatch(/\d\.\d{5,}/);
    // W-9c: the account sized the plan, so the plan's own "not sized" notes are gone; another flag stays.
    await expect(drawer.getByTestId("dc-size-text")).not.toContainText("1 share");
    const flags = drawer.getByTestId("dc-other-flags");
    await expect(flags).toContainText("MOCK: another flag that stays.");
    for (const gone of ["Sizing is incomplete", "Sizing needs", "Reward : risk is judged before costs here"]) await expect(flags).not.toContainText(gone);
  });

  test("W-4 the index strip: a missing day change gives the reason, never '— (—)'; a known one is shown", async ({ page }) => {
    await setup(page, { home: homeNoNiftyChange() });
    await page.goto(DESK);
    const nifty = page.locator('[data-testid="mo-index"][data-index="nifty"]');
    const bank = page.locator('[data-testid="mo-index"][data-index="banknifty"]');
    await expect(nifty.getByTestId("mo-index-change")).toHaveText("Day change not reported by the index feed", SLOW);
    await expect(bank.getByTestId("mo-index-change")).toHaveText("+80.20 (+0.15%)");
    expect(await textOf(page.getByTestId("mo-strip"))).not.toContain("— (—)");
  });

  test("W-9a the strategy that fits: a structure the risk service cannot size says '1 lot, not sized to your account' and why", async ({ page }) => {
    await setup(page, { ideas: ideasWith("options:bull_call_spread", NOT_SIZABLE, UNSIZED) });
    await page.goto(DESK);
    const line = stockRow(page).getByTestId("desk-top10-stock-strategy");
    await expect(line.getByTestId("desk-top10-fit-size")).toHaveText("1 lot, not sized to your account", SLOW);
    await expect(line.getByTestId("desk-top10-fit-size")).toHaveAttribute("data-sized", "false");
    await expect(line.getByTestId("desk-top10-fit-why")).toHaveText("Not sized: One lot's loss at the stop is above your per-trade budget of ₹4,908.98.");
  });

  test("W-9b the strategy that fits: a cash strategy sized by the risk service shows the account's shares, not the plan's 1-share legs", async ({ page }) => {
    await setup(page, { ideas: ideasWith("cash:breakout_continuation", SIZED_34, UNSIZED) });
    await page.goto(DESK);
    const line = stockRow(page).getByTestId("desk-top10-stock-strategy");
    await expect(line.getByTestId("desk-top10-fit-size")).toHaveText("34 shares, sized to your account", SLOW);
    await expect(line.getByTestId("desk-top10-fit-size")).toHaveAttribute("data-sized", "true");
    await expect(line).toContainText(`Buy 34 shares ${SYM}`);
    await expect(line.getByTestId("desk-top10-fit-why")).toHaveCount(0);
  });

  test("W-8 the decision log shows a reason once when its code comes in two cases", async ({ page }) => {
    const reason = "A target is needed to check reward against risk.";
    const decisions = { count: 1, append_only: true, policy_version: "risk-controls-v1", decisions: [{
      event_id: "dec-w8", at: "2026-10-20T06:28:00+00:00", outcome: "blocked", symbol: "TCS", user_id: "u_fixture", action: "desk_paper_trade", path: "desk_paper_trade", mode: "paper",
      requested_qty: 1, approved_qty: 0, requested_lots: null, approved_lots: null, correlation_id: "corr-w8", checks: [], freshness: null, policy_version: "universal-risk-v1",
      limits_version: "rp-1-fixture", estimate_version: "est-risk-v1", inputs_hash: "h", actor_id: "u_fixture", source: "risk_service", trade_id: null, store: "desk_paper_trades",
      reservation_id: null, snapshot_version: "decision-snapshot-v1", detail: { instrument: "cash", action: "open", legs: 0, sector: null, fno_additional: false },
      reasons: [
        { code: "target_required", check: "reward_risk", severity: "block", message: reason },
        { code: "TARGET_REQUIRED", check: "governor", severity: "block", message: reason },
        { code: "BEAR_REGIME", check: "governor", severity: "reduce", message: "The market regime is BEAR; size is cut." },
      ],
      estimated_risk_rs: { gross: 51, costs: 55, gap_stress: 25, total: 131, stop_based: 106 }, budget: { per_trade_pct: 0.5, per_trade_budget_rs: 5000 } }] };
    await setup(page, { decisions });
    await page.goto(LOG);
    const list = page.getByTestId("risk-decision-reasons").first();
    await expect(list).toBeVisible(SLOW);
    await expect(list.locator("li", { hasText: reason })).toHaveCount(1);
    await expect(list.locator("li", { hasText: "The market regime is BEAR" })).toHaveCount(1);
    const t = await textOf(page.getByTestId("risk-decisions"));
    expect(t).not.toMatch(SECTION_NO);
    expect(t).not.toMatch(RAW);
  });

  test("W-7 Smart Money and Market Intelligence: no leftover section numbers and no 'Options & futures lab' headline", async ({ page }) => {
    await setup(page);
    await page.goto(SMART);
    // The F&O section inside Smart Money keeps its pills, without the lab's own eyebrow and headline.
    const fno = page.getByTestId("desk-fno");
    await expect(fno).toBeVisible(SLOW);
    await expect(fno.locator(".cp-pill", { hasText: "Analysis only" }).first()).toBeVisible();
    await expect(page.getByTestId("desk-fno-title")).toHaveCount(0);
    // The Copilot dock: its name, without the old desk's "06 ·".
    const dock = page.getByTestId("dock-header");
    if (await dock.count()) {
      await expect(dock).toContainText("Conversational intelligence");
      await expect(dock).not.toContainText("06 ·");
    }
    const sm = await textOf(page.getByTestId("desk-panel-market"));
    expect(sm).not.toContain("06 · Smart Money Movement");
    expect(sm).not.toContain("Options & futures lab");
    expect(sm).not.toContain("Build, test and understand option trades.");
    expect(sm).not.toMatch(SECTION_NO);
    await page.goto(INTEL);
    await expect(page.getByTestId("desk-intel-title").first()).toBeVisible(SLOW);
    await expect(page.getByTestId("desk-intel-title").first()).not.toContainText("04 ·");
    expect(await textOf(page.getByTestId("desk-panel-market"))).not.toMatch(SECTION_NO);
  });
});
