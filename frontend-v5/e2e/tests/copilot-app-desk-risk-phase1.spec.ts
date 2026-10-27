/**
 * Phase 1 · universal risk enforcement — the screens' side (frontend-v5).
 *
 *   UI-1   a share paper trade answered 409 risk_reduce says the size the policy allows, how many were asked and why,
 *          that nothing was recorded; "Paper trade N shares instead" resubmits the same body at the approved quantity
 *          (a new submission, so a new Idempotency-Key). Top 10 stock ideas and the scanner list's action panel; a
 *          structure's reduce is said in lots per leg and offers no share button. The AI scanner watchlist and the
 *          chart's "Add to paper trades" use the same component (not driven here).
 *   UI-2   a 409 risk_blocked from the universal risk service lists the blocking reasons first, then the size cut, and
 *          drops an info note; no resubmit is offered.
 *   UI-3   More › Risk controls › 05 Risk profile: the eight limits with their rupee budgets and definitions, the equity
 *          basis (paper equity, peak, drawdown, day and week P&L, open risk; the starting capital labelled a simulation
 *          default), the profile's version and effective date, the change log; tightening sends PUT {changes, reason};
 *          a loosening answered 403 admin_required shows the admin-only rule; a 422 shows the server's words; unknown
 *          figures read "unknown", never 0; a body without profile.limits is a contract error.
 *
 * MOCK — not real data: every /api response here is an inline payload in the shape the real route returns
 * (backend/services/risk_gate/service.py `refusal`, backend/routes/risk_controls.py `_profile_view`,
 * services/risk_profile.py, services/risk_book.py); the reason sentences follow the service's own wording. The F&O board's
 * payload is `desk-strategy-top.json`, a real staging capture used unchanged only so the Scanner tab loads. Expected
 * values are worked out from the payloads here, not copied from the screen. Mocked APIs, production build — see
 * pw.copilot-app.config.ts.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", name), "utf-8"));
const DESK = "/v5/app/trader/desk";
const SCANNER = `${DESK}?tab=scanner`;
const RISK = `${DESK}?tab=more&view=risk`;
const SLOW = { timeout: 15_000 };
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

const reply = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

// ── the scanner tab (POST /api/desk/strategy/ideas, GET /api/positional/*) ──

const counts = { supports: 0, conflicts: 0, neutral: 0, unavailable: 0 };
const ICICI = {
  rank: 1, symbol: "ICICIBANK", name: "ICICI Bank Ltd", direction: "bullish", fno_eligible: true, plan_id: "p1", plan_status: "plan",
  scanner: { bucket: "breakout_confirmed", status: "confirmed", score: 86, close: 1200, close_date: "2026-10-19", entry: 1200, stop: 1160, target: 1280, reason: "MOCK", horizon_days: 10, liquidity_cr: 812.4, atr_pct: 1.67 },
  status_reasons: [], would_change_if: [], plan_inputs: { underlying: "ICICIBANK", direction: "bullish", instrument: "all", capital: 1000000, risk_budget_inr: 10000 },
  evidence_summary: { technical: counts }, oi_view: null, preferred: "cash:breakout_continuation",
  strategies: [{
    id: "cash:breakout_continuation", segment: "cash", family: "breakout_continuation", label: "Buy shares on the breakout", status: "candidate",
    legs_text: "Buy 208 shares at 1,200.00", max_loss: -8320, max_loss_basis: null, capital_at_risk: null, max_profit: null, profit_unbounded: false, breakeven: [],
    reward_risk_net: 1.9, reward_risk_gross: null, actionable: false, liquidity_flags: [], why: null, flags: [], reasons: [],
    sizing: { status: "complete", quantity: 208, lots: null, binding: "max_allocation", unit: "shares", risk_budget_inr: 10000, risk_at_stop_inr: 8320, deployed_inr: 249600, missing: [] },
  }],
};
const IDEAS = {
  generated_at: "2026-10-20T05:00:00+00:00", data_as_of: { mode: "end_of_day", scanner_watchlist: "2026-10-19", scanner_picks: "2026-10-19", scan_eligibility: "2026-10-19", price: "2026-10-19", fno: "2026-10-19" },
  caveats: [], rules_version: "strategy-rules-v2", calculation_version: "payoff-v1", sent_to_broker: false,
  ranking_note: "Ranked by the scanner's rules-based score. It is not a probability of profit.",
  selection: { source: "positional_watchlist", scan_date: "2026-10-19", rule: "MOCK", considered: 1, selected: 1, excluded: [], limit: 10, empty_reason: null, gate: null, source_failures: [] },
  inputs: { defaults_applied: [] }, ideas: [ICICI],
};
// TESTBRK: entry = the trigger 500, stop 477.5 (desk-data.ts reads a watchlist row's trigger as its entry).
const WATCHLIST = { as_of_date: "2026-10-19", buckets: {
  breakout_confirmed: [{ nse_symbol: "TESTBRK", sector: "Capital Goods", close_price: 510.0, trigger_price: 500.0, stop_price: 477.5, atr_pct: 2.94, why: "Fixture reason" }],
  pre_breakout: [], true_accumulation: [], trend_continuation: [] } };
const PICKS = { signal_date: "2026-10-19", count: 0, picks: [] };
const NOT_VALID = { valid: false, version: "strategy-levels-v2", problems: [{ code: "mock", message: "MOCK: not worked out in this test" }], sent_to_broker: false };

interface Post { body: Record<string, unknown>; key: string | undefined }

/** The Scanner tab; POST /api/desk/paper-trades answers `answers` in turn (the last one repeats). */
async function scannerDesk(page: Page, answers: Array<{ status: number; body: unknown }>): Promise<Post[]> {
  const posts: Post[] = [];
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (r) => reply(r, []));
  await page.route("**/api/positional/watchlist*", (r) => reply(r, WATCHLIST));
  await page.route("**/api/positional/picks*", (r) => reply(r, PICKS));
  await page.route("**/api/move-odds/**", (r) => reply(r, { detail: "feature_not_enabled" }, 403));
  await page.route("**/api/desk/alerts*", (r) => reply(r, { as_of: "2026-10-19", alerts: [] }));
  await page.route("**/api/desk/paper-trades*", (r) => {
    if (r.request().method() !== "POST") return reply(r, { as_of: "2026-10-19", trades: [], summary: null });
    posts.push({ body: r.request().postDataJSON(), key: r.request().headers()["idempotency-key"] });
    const a = answers[Math.min(posts.length, answers.length) - 1];
    return reply(r, a.body, a.status);
  });
  await page.route("**/api/desk/strategy/ideas", (r) => reply(r, IDEAS));
  await page.route("**/api/desk/strategy/top", (r) => reply(r, load("desk-strategy-top.json")));
  await page.route("**/api/desk/strategy/levels", (r) => reply(r, NOT_VALID));
  await page.route("**/api/filings/feed*", (r) => reply(r, { ok: true, total: 0, facets: {}, rows: [] }));
  await page.route("**/api/markets/fii-dii*", (r) => reply(r, { ok: true, as_of: "2026-10-13", monthly: [], daily: [] }));
  await page.route("**/api/markets/sector-returns", (r) => reply(r, { as_of: "2026-10-13", source: "MOCK", sessions: { "1d": 1, "1w": 5, "1m": 21 }, sectors: [] }));
  await page.route("**/api/markets/deals*", (r) => reply(r, { as_of: "2026-10-13", from: "2026-10-09", days: 5, kind: "all", symbol: null, source: "MOCK", count: 0, total: 0, rows: [] }));
  await page.route("**/api/markets/circulars*", (r) => reply(r, { as_of: "2026-10-14", source: "MOCK", count: 0, rows: [] }));
  return posts;
}

// ── the refusals (backend/services/risk_gate/service.py `refusal`) ──

const RISK_EST = { gross: 9120.0, costs: 410.4, gap_stress: 1435.96, total: 10966.4, stop_based: 9120.0 };
const BUDGET = { per_trade_rs: 5000.0, open_risk_cap_rs: 30000.0, exposure_cap_rs: 100000.0, sector_cap_rs: 250000.0 };
const decision = (o: Record<string, unknown>) => ({
  decision_id: "dec-fixture-1", requested_lots: null, approved_lots: null, planned_entry_price: 1200, estimated_risk_rs: RISK_EST, budget: BUDGET,
  policy_version: "universal-risk-v1", limits_version: "rp-0-3f9a1c2e", correlation_id: "corr-fixture-1", reservation_id: null, freshness: null, inputs_hash: "h-fixture", ...o,
});
const PER_TRADE_REDUCE = { code: "per_trade_risk_exceeded", check: "per_trade_risk", severity: "reduce", value: 10966.4, limit: 5000.0,
  message: "Estimated risk Rs 10,966.40 exceeds the per-trade budget Rs 5,000.00; at most 95 shares fit." };
const INFO_NOTE = { code: "correlation_not_checked", check: "correlation", severity: "info", value: null, limit: null,
  message: "Correlation not checked: no reliable return-correlation source exists for paper positions." };
/** 208 asked, 95 allowed at entry 1200: Rs 1,14,000. */
const REDUCE_95 = { detail: { code: "risk_reduce", ...decision({ outcome: "reduce", requested_qty: 208, approved_qty: 95, approved_notional_rs: 114000.0, reasons: [INFO_NOTE, PER_TRADE_REDUCE] }),
  message: "The risk policy allows at most 95 shares. Nothing was recorded; submit again at that size." } };
const BLOCKED = { detail: { code: "risk_blocked", ...decision({
  outcome: "block", requested_qty: 208, approved_qty: 0, approved_notional_rs: null,
  // Sent with the size cut and an info note FIRST, so the screen's blocking-first order is what is checked.
  reasons: [
    PER_TRADE_REDUCE,
    INFO_NOTE,
    { code: "daily_loss_halt", check: "daily_loss", severity: "block", value: 2.1, limit: 2.0, message: "The day's loss is 2.10% of start-of-day equity; new entries are halted at 2%." },
    { code: "reward_risk_too_low", check: "reward_risk", severity: "block", value: 1.2, limit: 1.5, message: "Reward:risk after costs is 1.20; the minimum is 1.5." },
  ] }),
  message: "The day's loss is 2.10% of start-of-day equity; new entries are halted at 2%.; Reward:risk after costs is 1.20; the minimum is 1.5." } };
const CREATED = { trade: { id: "t-new" }, risk: { outcome: "allow" } };

test.describe("MOCK — not real data: Phase 1 universal risk · paper-trade refusals", () => {
  test("UI-1 Top 10: a 409 risk_reduce names the size allowed and why; the offer resubmits the same trade at 95 shares", async ({ page }) => {
    const posts = await scannerDesk(page, [{ status: 409, body: REDUCE_95 }, { status: 201, body: CREATED }]);
    await page.goto(SCANNER);
    const icici = page.getByTestId("desk-top10-stock-ICICIBANK");
    await icici.getByTestId("desk-top10-stock-paper").click(SLOW);
    await expect(icici.getByTestId("desk-top10-paper-qty")).toHaveValue("208");
    await icici.getByTestId("desk-top10-paper-add").click();
    // The reduce reason only: the info note explains and is left out.
    await expect(icici.getByTestId("desk-top10-paper-error")).toHaveText(
      "Not added — The risk policy allows at most 95 shares (you asked 208): Estimated risk Rs 10,966.40 exceeds the per-trade budget Rs 5,000.00; at most 95 shares fit. Nothing was recorded. (risk_reduce)");
    const offer = icici.getByTestId("desk-top10-paper-reduce");
    await expect(offer).toHaveAttribute("data-approved", "95");
    await expect(offer.getByTestId("desk-top10-paper-reduce-accept")).toHaveText("Paper trade 95 shares instead");
    await expect(offer.getByTestId("desk-top10-paper-reduce-note")).toHaveText(
      "Same entry, stop and target; ₹1,14,000 at the planned entry. The risk policy checks it again. Simulated; nothing is sent to a broker.");
    expect(posts).toHaveLength(1);

    await offer.getByTestId("desk-top10-paper-reduce-accept").click();
    await expect(icici.getByTestId("desk-top10-paper-done")).toContainText("Paper trade added: 95 ICICIBANK");
    await expect(icici.getByTestId("desk-top10-paper-qty")).toHaveValue("95");
    await expect(icici.getByTestId("desk-top10-paper-error")).toHaveCount(0);
    await expect(icici.getByTestId("desk-top10-paper-reduce")).toHaveCount(0);
    expect(posts).toHaveLength(2);
    // The same trade, only the quantity changed; a different body is a new submission with its own key.
    expect(posts[0].body).toEqual({ symbol: "ICICIBANK", quantity: 208, entry_price: 1200, stop_price: 1160, target_price: 1280,
      source: { kind: "scanner", bucket: "breakout_confirmed", signal_date: "2026-10-19" }, entry_rule: "at_once" });
    expect(posts[1].body).toEqual({ ...posts[0].body, quantity: 95 });
    expect(posts[0].key).toMatch(UUID);
    expect(posts[1].key).toMatch(UUID);
    expect(posts[1].key).not.toBe(posts[0].key);
  });

  test("UI-1 scanner list: the action panel's paper trade takes the same offer and resubmits at the approved 20 shares", async ({ page }) => {
    const reduce = { detail: { code: "risk_reduce", ...decision({ outcome: "reduce", requested_qty: 50, approved_qty: 20, approved_notional_rs: 10000.0, planned_entry_price: 500,
      reasons: [{ code: "position_exceeded", check: "position", severity: "reduce", value: 25000.0, limit: 10000.0, message: "Position exposure Rs 25,000.00 is over the Rs 10,000.00 left; at most 20 shares fit." }] }),
      message: "The risk policy allows at most 20 shares. Nothing was recorded; submit again at that size." } };
    const posts = await scannerDesk(page, [{ status: 409, body: reduce }, { status: 201, body: CREATED }]);
    await page.goto(SCANNER);
    const row = page.getByTestId("desk-scan-row-TESTBRK");
    await row.getByTestId("desk-scan-act").click(SLOW);
    const panel = page.getByTestId("desk-scan-actions-TESTBRK");
    await panel.getByTestId("desk-scan-paper-qty").fill("50");
    await panel.getByTestId("desk-scan-paper-add").click();
    await expect(panel.getByTestId("desk-scan-paper-error")).toHaveText(
      "Not added — The risk policy allows at most 20 shares (you asked 50): Position exposure Rs 25,000.00 is over the Rs 10,000.00 left; at most 20 shares fit. Nothing was recorded. (risk_reduce)");
    await panel.getByTestId("desk-scan-paper-reduce-accept").click();
    await expect(panel.getByTestId("desk-scan-paper-done")).toContainText("Paper trade added: 20 TESTBRK");
    await expect(panel.getByTestId("desk-scan-paper-qty")).toHaveValue("20");
    expect(posts.map((p) => p.body.quantity)).toEqual([50, 20]);
    expect(posts[1].body).toEqual({ ...posts[0].body, quantity: 20 });
  });

  test("UI-1 a structure's reduce is said in lots per leg and offers no share button (the writeProblem the F&O flows use)", async ({ page }) => {
    // The structure path's body (approved_lots per leg, approved_qty null), answered here to the Top 10 share write only
    // to drive writeProblem: the F&O flows (FnoStrategies, PlanActions) render the same function.
    const lots = { detail: { code: "risk_reduce", ...decision({ outcome: "reduce", requested_qty: null, approved_qty: null, requested_lots: 5, approved_lots: 2,
      approved_notional_rs: null, planned_entry_price: null,
      reasons: [{ code: "per_trade_risk_exceeded", check: "per_trade_risk", severity: "reduce", value: 24500.0, limit: 5000.0, message: "Estimated risk Rs 24,500.00 exceeds the per-trade budget Rs 5,000.00; at most 2 lot(s) per leg fit." }] }),
      message: "The risk policy allows at most 2 lot(s) per leg. Nothing was recorded; submit again at that size." } };
    const posts = await scannerDesk(page, [{ status: 409, body: lots }]);
    await page.goto(SCANNER);
    const icici = page.getByTestId("desk-top10-stock-ICICIBANK");
    await icici.getByTestId("desk-top10-stock-paper").click(SLOW);
    await icici.getByTestId("desk-top10-paper-add").click();
    await expect(icici.getByTestId("desk-top10-paper-error")).toHaveText(
      "Not added — The risk policy allows at most 2 lots per leg (you asked 5): Estimated risk Rs 24,500.00 exceeds the per-trade budget Rs 5,000.00; at most 2 lot(s) per leg fit. Nothing was recorded. (risk_reduce)");
    await expect(icici.getByTestId("desk-top10-paper-reduce")).toHaveCount(0);
    expect(posts).toHaveLength(1);
  });

  test("UI-2 a 409 risk_blocked lists the blocking reasons first, then the size cut, drops the info note, and offers no resubmit", async ({ page }) => {
    const posts = await scannerDesk(page, [{ status: 409, body: BLOCKED }]);
    await page.goto(SCANNER);
    const icici = page.getByTestId("desk-top10-stock-ICICIBANK");
    await icici.getByTestId("desk-top10-stock-paper").click(SLOW);
    await icici.getByTestId("desk-top10-paper-add").click();
    await expect(icici.getByTestId("desk-top10-paper-error")).toHaveText(
      "Not added — Blocked by your risk controls: The day's loss is 2.10% of start-of-day equity; new entries are halted at 2%; Reward:risk after costs is 1.20; the minimum is 1.5; Estimated risk Rs 10,966.40 exceeds the per-trade budget Rs 5,000.00; at most 95 shares fit. See Desk › More › Risk controls. (risk_blocked)");
    await expect(icici.getByTestId("desk-top10-paper-error")).not.toContainText("Correlation not checked");
    await expect(icici.getByTestId("desk-top10-paper-reduce")).toHaveCount(0);
    await expect(icici.getByTestId("desk-top10-paper-done")).toHaveCount(0);
    expect(posts).toHaveLength(1);
  });
});

// ── the risk profile (GET / PUT /api/risk/profile) ──

const OWNER = { per_trade_risk_pct: 0.5, max_open_risk_pct: 3, max_position_pct: 10, max_sector_pct: 25, daily_loss_pct: 2, weekly_loss_pct: 4, max_drawdown_pct: 10, min_reward_risk: 1.5 };
const DEFINITIONS = {
  per_trade_risk_pct: { label: "Risk per trade", basis: "estimated risk of the new entry = quantity x |entry - stop| + round-trip costs + gap stress, as % of paper equity", reset: "none: judged per entry", breach: "the size is REDUCED to the largest valid quantity within the budget; else BLOCKED" },
  max_open_risk_pct: { label: "Total open risk", basis: "estimated risk of every open position plus the new entry, as % of paper equity", reset: "falls as positions close", breach: "REDUCED to fit, else BLOCKED" },
  max_position_pct: { label: "Position exposure", basis: "market exposure of the new position, as % of paper equity", reset: "none: judged per entry", breach: "REDUCED to fit, else BLOCKED" },
  max_sector_pct: { label: "Sector exposure", basis: "market exposure of every open position in the sector plus the new one, as % of paper equity", reset: "falls as positions in the sector close", breach: "REDUCED to fit, else BLOCKED" },
  daily_loss_pct: { label: "Daily loss halt", basis: "loss since the start of the IST trading day, as % of start-of-day equity", reset: "the next IST trading day", breach: "new entries BLOCKED for the rest of the day" },
  weekly_loss_pct: { label: "Weekly loss halt", basis: "the same loss from the start of the ISO week, as % of start-of-week equity", reset: "Monday, IST", breach: "new entries BLOCKED until the week resets" },
  max_drawdown_pct: { label: "Drawdown halt", basis: "fall of paper equity from the configured equity peak", reset: "never resets daily; only an admin resets it", breach: "new entries BLOCKED; open positions are NOT liquidated" },
  min_reward_risk: { label: "Minimum reward:risk", basis: "(gain at the target - costs) / (loss at the stop + costs)", reset: "none: judged per entry", breach: "BLOCKED (reward_risk_too_low)" },
};
const FIELDS = Object.keys(OWNER);
const CATALOGUE = {
  definitions: DEFINITIONS, fields: FIELDS,
  named_profiles: {
    "owner-default-2026-10-27": { limits: OWNER, text: "The product owner's paper-risk defaults (2026-10-27). Research defaults, not validated optimal values." },
    "engineering-comparison": { limits: { ...OWNER, per_trade_risk_pct: 1 }, text: "The engineering proposal kept for comparison. Looser on every limit." },
  },
  ranges: { per_trade_risk_pct: [0.05, 5], max_open_risk_pct: [0.1, 50], max_position_pct: [0.5, 100], max_sector_pct: [1, 100], daily_loss_pct: [0.1, 20], weekly_loss_pct: [0.1, 40], max_drawdown_pct: [1, 50], min_reward_risk: [0, 10] },
  capital_basis: "paper_equity", policy_version: "risk-profile-v1",
};
const BASIS_TEXT = "paper equity = paper cash + net unrealised P&L of the open positions at their latest end-of-day marks (net of estimated round-trip costs); unknown when any open position cannot be marked";
const START_LABEL = "simulation default (Rs 10,00,000): the paper account's opening cash, not a real account's capital";
const SET_AT = "2026-10-26T04:30:00+00:00"; // 26 Oct, 10:00 IST
const PUT_AT = "2026-10-27T06:15:00+00:00"; // 27 Oct, 11:45 IST
const SECTOR_CHANGE = { user_id: "u_fixture", at: SET_AT, actor: "u_fixture", actor_is_admin: false, action: "set_limits", profile_before: "owner-default-2026-10-27", profile_after: "custom",
  changes: { max_sector_pct: { before: 25, after: 20 } }, loosened: [], reason: "Smaller sector bets while I learn the desk", version_before: 0, version_after: 1, limits_version_after: "rp-1-1a2b3c4d", effective_from: SET_AT, policy_version: "risk-profile-v1" };

/** Paper equity Rs 10,12,345.67; budgets are the limits' % of it (rounded to paise as the route does). */
const EQUITY = 1012345.67;
const budgets = (l: Record<string, number>) => ({
  per_trade: Math.round(EQUITY * l.per_trade_risk_pct) / 100, open_risk: Math.round(EQUITY * l.max_open_risk_pct) / 100,
  position: Math.round(EQUITY * l.max_position_pct) / 100, sector: Math.round(EQUITY * l.max_sector_pct) / 100,
});
const LIVE = (l: Record<string, number>) => ({
  equity: { equity_rs: EQUITY, cash_rs: 1000000, net_unrealised_rs: 12345.67, unknown_reasons: [], basis: BASIS_TEXT, marks_as_of: "2026-10-26", fno_marks_as_of: null },
  peak: { peak_rs: 1020000, starting_capital_rs: 1000000, stored: true },
  drawdown_pct: 0.75,
  day: { start: "2026-10-26T10:00:00+00:00", pnl_rs: -2345.5, unknown_reasons: [], start_equity_rs: 1014691.17 },
  week: { start: "2026-10-23T10:00:00+00:00", pnl_rs: null, unknown_reasons: ["RELIANCE: no end-of-day mark for 2026-10-24"], start_equity_rs: null },
  open: { positions: 3, reserved_positions: 2, legacy_positions: 1, risk_rs: 14200, reserved_risk_rs: 9200, legacy_risk_rs: 5000, exposure_rs: 245000,
    reserved_exposure_rs: 145000, legacy_exposure_rs: 100000, sector_rs: { IT: 100000, Banks: 145000 }, unclassified_exposure_rs: 0, held_symbols: ["ICICIBANK", "TCS", "HDFCBANK"] },
  budgets_rs: budgets(l),
  error: null,
});
const profileBody = (o: { limits?: Record<string, number>; version?: number; effective?: string; reason?: string; changes?: unknown[]; live?: unknown; canLoosen?: boolean } = {}) => {
  const limits = o.limits ?? { ...OWNER, max_sector_pct: 20 };
  return {
    profile: { user_id: "u_fixture", profile: "custom", limits, version: o.version ?? 1, limits_version: `rp-${o.version ?? 1}-1a2b3c4d`, capital_basis: "paper_equity",
      capital_basis_text: BASIS_TEXT, starting_capital_rs: 1000000, starting_capital_label: START_LABEL, effective_from: o.effective ?? SET_AT, set_by: "u_fixture",
      set_at: o.effective ?? SET_AT, reason: o.reason ?? SECTOR_CHANGE.reason, stored: true, policy_version: "risk-profile-v1" },
    live: o.live ?? LIVE(limits),
    changes: o.changes ?? [SECTOR_CHANGE],
    can_loosen: o.canLoosen ?? false,
    catalogue: CATALOGUE,
    estimate: { version: "est-risk-v1", gap_stress_pct: 1.0, gap_stress_text: "a gap of 1% of the stop price through the stop (research constant, not calibrated; est-risk-v1)", cost_model: "desk-cost-v2" },
    risk_policy_version: "universal-risk-v1",
    fno_additional_checks: { flag: "fno_risk_gate", enabled: false },
  };
};

interface ProfileCalls { puts: Array<Record<string, unknown>>; gets: number }

/** The Risk controls page with a stateful /api/risk/profile; `put` overrides the PUT's answer. */
async function riskPage(page: Page, o: { get?: { status: number; body: unknown }; put?: { status: number; body: unknown } } = {}): Promise<ProfileCalls> {
  const calls: ProfileCalls = { puts: [], gets: 0 };
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (r) => reply(r, []));
  await page.route("**/api/move-odds/**", (r) => reply(r, { detail: "feature_not_enabled" }, 403));
  await page.route("**/api/risk/status", (r) => reply(r, { user_id: "u_fixture", kill_switch: false, halted: false, reason: null, set_by: null, set_at: null, policy_version: "risk-controls-v1",
    stored: false, scope: "MOCK scope", not_in_scope: "MOCK not in scope", can_reset: false, live_authorization: { granted: false }, modes: ["paper"], live_execution_available: false, gate: { enabled: false, policy_version: "fno-gate-v1" } }));
  await page.route("**/api/risk/policy", (r) => reply(r, { policy_version: "fno-gate-v1", limits: { max_legs: 4, max_lots_per_leg: 10, max_open_structures: 5, max_capital_at_risk_rs: 200000, require_defined_risk: true } }));
  await page.route("**/api/risk/decisions*", (r) => reply(r, { decisions: [], count: 0, policy_version: "universal-risk-v1" }));
  await page.route("**/api/risk/audit*", (r) => reply(r, { events: [], count: 0, append_only: true, policy_version: "risk-controls-v1" }));
  let state = profileBody();
  await page.route("**/api/risk/profile", (r) => {
    if (r.request().method() === "GET") {
      calls.gets += 1;
      return o.get ? reply(r, o.get.body, o.get.status) : reply(r, state);
    }
    const body = r.request().postDataJSON() as { changes: Record<string, number>; reason: string };
    calls.puts.push(body);
    if (o.put) return reply(r, o.put.body, o.put.status);
    // As services/risk_profile.set_limits does: the change, a new version, effective now, the audit row first in the log.
    const before = state.profile.limits as Record<string, number>;
    const limits = { ...before, ...body.changes };
    const row = { ...SECTOR_CHANGE, at: PUT_AT, changes: Object.fromEntries(Object.entries(body.changes).map(([k, v]) => [k, { before: before[k], after: v }])),
      reason: body.reason, version_before: 1, version_after: 2, effective_from: PUT_AT };
    state = profileBody({ limits, version: 2, effective: PUT_AT, reason: body.reason, changes: [row, SECTOR_CHANGE] });
    return reply(r, state);
  });
  return calls;
}

async function noSideScroll(page: Page) {
  const o = await page.evaluate(() => {
    const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
    return { doc: document.documentElement.scrollWidth - window.innerWidth, scroll: sc ? sc.scrollWidth - sc.clientWidth : 0 };
  });
  expect(o.doc).toBeLessThanOrEqual(1);
  expect(o.scroll).toBeLessThanOrEqual(1);
}

test.describe("MOCK — not real data: Phase 1 universal risk · 05 Risk profile", () => {
  test("UI-3 the card shows the limits with budgets and definitions, the equity basis, version, effective date and the change log", async ({ page }) => {
    await riskPage(page);
    await page.goto(RISK);
    const card = page.getByTestId("risk-profile");
    await expect(card.getByTestId("risk-profile-title")).toContainText("Risk profile");
    await expect(card.getByTestId("risk-profile-name")).toHaveText("custom");
    await expect(card.getByTestId("risk-profile-version")).toHaveText("version 1 · rp-1-1a2b3c4d");
    await expect(card.getByTestId("risk-profile-effective")).toHaveText("In effect since 26 Oct, 10:00 IST. Set by u_fixture: “Smaller sector bets while I learn the desk”.");

    // The eight limits in the catalogue's order, labelled from its definitions; budgets are % of Rs 10,12,345.67.
    const rows = card.getByTestId("risk-profile-table").locator("tbody tr");
    await expect(rows).toHaveCount(8);
    const expected: Array<[string, string, string, string]> = [
      ["per_trade_risk_pct", "Risk per trade", "0.5%", "₹5,062"],
      ["max_open_risk_pct", "Total open risk", "3%", "₹30,370"],
      ["max_position_pct", "Position exposure", "10%", "₹1,01,235"],
      ["max_sector_pct", "Sector exposure", "20%", "₹2,02,469"],
      ["daily_loss_pct", "Daily loss halt", "2%", "—"],
      ["weekly_loss_pct", "Weekly loss halt", "4%", "—"],
      ["max_drawdown_pct", "Drawdown halt", "10%", "—"],
      ["min_reward_risk", "Minimum reward:risk", "1.5 : 1", "—"],
    ];
    for (const [f, label, value, budget] of expected) {
      await expect(card.getByTestId(`risk-profile-limit-${f}-label`)).toHaveText(label);
      await expect(card.getByTestId(`risk-profile-limit-${f}-value`)).toHaveText(value);
      await expect(card.getByTestId(`risk-profile-limit-${f}-budget`)).toHaveText(budget);
    }
    // A definition opens in place: how it is measured, when it resets, what a breach does.
    const def = card.getByTestId("risk-profile-def-max_drawdown_pct");
    await expect(def).not.toHaveAttribute("open", "");
    await card.getByTestId("risk-profile-limit-max_drawdown_pct-label").click();
    await expect(def).toHaveAttribute("open", "");
    await expect(def).toContainText("Measured as: fall of paper equity from the configured equity peak");
    await expect(def).toContainText("Resets: never resets daily; only an admin resets it");
    await expect(def).toContainText("On a breach: new entries BLOCKED; open positions are NOT liquidated");

    // The equity basis: known figures in rupees, the unknown week as unknown with its reason, never 0.
    await expect(card.getByTestId("risk-profile-equity-now-value")).toHaveText("₹10,12,346");
    await expect(card.getByTestId("risk-profile-peak-value")).toHaveText("₹10,20,000");
    await expect(card.getByTestId("risk-profile-drawdown-value")).toHaveText("0.75% below the peak");
    await expect(card.getByTestId("risk-profile-day-value")).toHaveText("−₹2,346");
    await expect(card.getByTestId("risk-profile-week-value")).toHaveText("unknown: RELIANCE: no end-of-day mark for 2026-10-24");
    await expect(card.getByTestId("risk-profile-open-value")).toHaveText("₹14,200");
    await expect(card.getByTestId("risk-profile-open")).toContainText("3 open positions (1 from before the risk profile); exposure ₹2,45,000");
    await expect(card.getByTestId("risk-profile-sectors")).toHaveText("Exposure by sector: Banks ₹1,45,000 · IT ₹1,00,000");
    await expect(card.getByTestId("risk-profile-starting")).toHaveText(`Starting capital ₹10,00,000, ${START_LABEL}.`);
    await expect(card.getByTestId("risk-profile-basis")).toHaveText(`Every percentage is of ${BASIS_TEXT}.`);

    // The change log: who, when, which limit from what to what, and why.
    const log = card.getByTestId("risk-profile-change");
    await expect(log).toHaveCount(1);
    await expect(log.getByTestId("risk-profile-change-field")).toHaveText("Sector exposure: 25% → 20%");
    await expect(log.getByTestId("risk-profile-change-actor")).toHaveText("u_fixture");
    await expect(log).toContainText("26 Oct, 10:00 IST");
    await expect(log.getByTestId("risk-profile-change-reason")).toHaveText("“Smaller sector bets while I learn the desk”");
    await expect(log).toContainText("version 1");

    await expect(card.getByTestId("risk-profile-admin-note")).toHaveText("Only an admin can loosen a limit; you can tighten any limit.");
    await expect(card.getByTestId("risk-profile-estimate")).toHaveText(
      "A share entry’s estimated risk is its loss at the stop plus round-trip costs (desk-cost-v2) and a gap of 1% of the stop price through the stop (research constant, not calibrated; est-risk-v1).");
    await expect(card.getByTestId("risk-trust-profile")).toContainText("universal-risk-v1");
  });

  test("UI-3 tightening sends PUT {changes, reason}; the card shows the new value, version, effective date and log row", async ({ page }) => {
    const calls = await riskPage(page);
    await page.goto(RISK);
    const card = page.getByTestId("risk-profile");
    const form = card.getByTestId("risk-profile-form");
    await expect(form).toContainText("Tighten a limit");
    await form.getByTestId("risk-profile-field").selectOption("per_trade_risk_pct");
    await form.getByTestId("risk-profile-value").fill("0.4");
    await expect(form.getByTestId("risk-profile-hint")).toHaveText("Now 0.5%; from 0.05 to 5 (lower is tighter). Tighter than now.");
    // A reason is required: nothing is sent without one.
    await form.getByTestId("risk-profile-submit").click();
    await expect(form.getByTestId("risk-profile-form-error")).toHaveText("Give a reason: it is recorded in the change log.");
    expect(calls.puts).toHaveLength(0);

    await form.getByLabel("Why (required; recorded in the change log)").fill("Halve the size this week");
    await form.getByTestId("risk-profile-submit").click();
    await expect(form.getByTestId("risk-profile-saved")).toHaveText("Saved, in effect from 27 Oct, 11:45 IST. The change is in the log above.");
    expect(calls.puts).toEqual([{ changes: { per_trade_risk_pct: 0.4 }, reason: "Halve the size this week" }]);
    await expect(card.getByTestId("risk-profile-limit-per_trade_risk_pct-value")).toHaveText("0.4%");
    await expect(card.getByTestId("risk-profile-limit-per_trade_risk_pct-budget")).toHaveText("₹4,049");
    await expect(card.getByTestId("risk-profile-version")).toHaveText("version 2 · rp-2-1a2b3c4d");
    await expect(card.getByTestId("risk-profile-effective")).toContainText("In effect since 27 Oct, 11:45 IST.");
    await expect(card.getByTestId("risk-profile-change-field")).toHaveText(["Risk per trade: 0.5% → 0.4%", "Sector exposure: 25% → 20%"]);
    await expect(card.getByTestId("risk-profile-change-reason").first()).toHaveText("“Halve the size this week”");
    await expect(form.getByTestId("risk-profile-value")).toHaveValue("");
  });

  test("UI-3 a loosening is sent and the server's 403 admin_required is shown as the admin-only rule; nothing changes", async ({ page }) => {
    const calls = await riskPage(page, { put: { status: 403, body: { detail: { code: "admin_required", message: "Only an admin can loosen a risk limit (Position exposure). You can tighten any limit yourself." } } } });
    await page.goto(RISK);
    const card = page.getByTestId("risk-profile");
    const form = card.getByTestId("risk-profile-form");
    await form.getByTestId("risk-profile-field").selectOption("max_position_pct");
    await form.getByTestId("risk-profile-value").fill("15");
    await expect(form.getByTestId("risk-profile-hint")).toHaveText(
      "Now 10%; from 0.5 to 100 (lower is tighter). Looser than now. Only an admin can loosen a limit; you can tighten any limit.");
    await form.getByTestId("risk-profile-reason").fill("Bigger positions");
    await form.getByTestId("risk-profile-submit").click();
    await expect(form.getByTestId("risk-profile-save-error")).toHaveText("Only an admin can loosen a limit; you can tighten any limit. (admin_required)");
    expect(calls.puts).toEqual([{ changes: { max_position_pct: 15 }, reason: "Bigger positions" }]);
    await expect(card.getByTestId("risk-profile-limit-max_position_pct-value")).toHaveText("10%");
    await expect(card.getByTestId("risk-profile-change")).toHaveCount(1);
    await expect(form.getByTestId("risk-profile-saved")).toHaveCount(0);
    // A higher minimum reward:risk is the tighter way for that one limit.
    await form.getByTestId("risk-profile-field").selectOption("min_reward_risk");
    await form.getByTestId("risk-profile-value").fill("2");
    await expect(form.getByTestId("risk-profile-hint")).toHaveText("Now 1.5 : 1; from 0 to 10 (higher is tighter). Tighter than now.");
  });

  test("UI-3 a 422 shows the server's words with the code; an out-of-range value is caught before sending", async ({ page }) => {
    const calls = await riskPage(page, { put: { status: 422, body: { detail: { code: "invalid_input", message: "total open risk cannot be below the risk per trade" } } } });
    await page.goto(RISK);
    const form = page.getByTestId("risk-profile-form");
    await form.getByTestId("risk-profile-field").selectOption("max_open_risk_pct");
    await form.getByTestId("risk-profile-reason").fill("Fewer open bets");
    await form.getByTestId("risk-profile-value").fill("60");
    await form.getByTestId("risk-profile-submit").click();
    await expect(form.getByTestId("risk-profile-form-error")).toHaveText("Enter a value from 0.1 to 50.");
    expect(calls.puts).toHaveLength(0);
    await form.getByTestId("risk-profile-value").fill("0.3");
    await form.getByTestId("risk-profile-submit").click();
    await expect(form.getByTestId("risk-profile-save-error")).toHaveText("total open risk cannot be below the risk per trade (invalid_input)");
    expect(calls.puts).toEqual([{ changes: { max_open_risk_pct: 0.3 }, reason: "Fewer open bets" }]);
  });

  test("UI-3 unknown equity reads unknown (never 0) with its reason; an unreadable account says so; phone 390px fits", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const unknownLive = {
      ...LIVE(OWNER), equity: { equity_rs: null, cash_rs: 1000000, net_unrealised_rs: null, unknown_reasons: ["TCS: no end-of-day mark for 2026-10-26"], marks_as_of: null, fno_marks_as_of: null },
      drawdown_pct: null, day: { start: "2026-10-26T10:00:00+00:00", pnl_rs: null, unknown_reasons: ["equity unknown"], start_equity_rs: null },
      budgets_rs: { per_trade: null, open_risk: null, position: null, sector: null },
    };
    await riskPage(page, { get: { status: 200, body: profileBody({ limits: OWNER, live: unknownLive }) } });
    await page.goto(RISK);
    const card = page.getByTestId("risk-profile");
    await expect(card.getByTestId("risk-profile-equity-now-value")).toHaveText("unknown: TCS: no end-of-day mark for 2026-10-26");
    await expect(card.getByTestId("risk-profile-drawdown-value")).toHaveText("unknown");
    await expect(card.getByTestId("risk-profile-day-value")).toHaveText("unknown: equity unknown");
    for (const f of ["per_trade_risk_pct", "max_open_risk_pct", "max_position_pct", "max_sector_pct"]) {
      await expect(card.getByTestId(`risk-profile-limit-${f}-budget`)).toHaveText("unknown");
    }
    await expect(card.getByTestId("risk-profile-table")).not.toContainText("₹0");
    await card.getByTestId("risk-profile-table").scrollIntoViewIfNeeded();
    await noSideScroll(page);

    // The route could not read the account: the live figures are said to be unknown, the limits still show.
    await page.unroute("**/api/risk/profile");
    await page.route("**/api/risk/profile", (r) => reply(r, profileBody({ limits: OWNER, live: { error: "the account could not be read (ServerSelectionTimeoutError)" } })));
    await page.reload();
    await expect(card.getByTestId("risk-profile-live-error")).toHaveText(
      "The live figures could not be read (the account could not be read (ServerSelectionTimeoutError)), so paper equity, P&L, open risk and the rupee budgets are unknown here.");
    await expect(card.getByTestId("risk-profile-limit-per_trade_risk_pct-value")).toHaveText("0.5%");
    await expect(card.getByTestId("risk-profile-limit-per_trade_risk_pct-budget")).toHaveText("unknown");
    await noSideScroll(page);
  });

  test("UI-3 a body without profile.limits is a contract error, not a profile of zeros", async ({ page }) => {
    await riskPage(page, { get: { status: 200, body: { profile: { profile: "custom" }, live: null } } });
    await page.goto(RISK);
    await expect(page.getByTestId("risk-profile-error").getByRole("alert")).toContainText("Your risk profile didn’t load — unexpected response shape", SLOW);
    await expect(page.getByTestId("risk-profile-table")).toHaveCount(0);
    await expect(page.getByTestId("risk-profile-form")).toHaveCount(0);
  });
});
