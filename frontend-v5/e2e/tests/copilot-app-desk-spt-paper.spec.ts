/**
 * One-screen Copilot app (/v5/app) — Trade Desk › Paper Trading › Opportunities · Analytics · Settings: the Scanner-to-Paper
 * Trading screens (owner, 5 Nov 2026: "plain, functional screens on real data inside today's Trader workspace";
 * docs/scanner_paper_trading/DESIGN.md). Test cases SPT-UI-P-01 … P-27 in test_reports/spt_ui_paper_TESTCASES.md.
 *
 * Every /api/* answer below is an inline MOCK — not real data — in the shapes the backend code returns (routes/spt_signals.py,
 * spt_risk.py, spt_accounts.py with the 5 Nov config, spt_paper.py; services/spt/policy.py public(), settings.py public(),
 * outcomes/analytics.py). Symbols, prices, ids and figures are made up. Mocked APIs, production build: these cases prove the
 * screens render and send the right requests, NOT that the backend answers these shapes.
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

// ── MOCK — not real data: the SPT config (policy.public(), owner-default profile 0.5 / 10 / 1.5) ─────────────────────────
const DEFAULTS = {
  drawdown_ladder: { reduce_factor: 0.5, reduce_at_pct: 3.33, restrict_at_pct: 6.67, halt_at_pct: 10 },
  max_positions: 10, max_new_per_day: 5, stressed_gap_pct: 1, min_rr: { positional: 1.5 },
  risk_pct: { positional: 0.5, intraday: 0.35, fno: 0.35 },
  allocation_buckets_pct: { equity_positional: 45, equity_intraday: 25, fno: 20, reserve: 10 },
  min_adv_rs: 10000000, max_adv_participation_pct: 5, max_chase_pct: 1, approval_expiry_minutes: 30,
};
const OWNER = "spt-default (owner-approved 5 Nov 2026)";
const SOURCES: Record<string, string> = {
  "drawdown_ladder.reduce_at_pct": "risk profile max_drawdown_pct × 1/3", "drawdown_ladder.restrict_at_pct": "risk profile max_drawdown_pct × 2/3",
  "drawdown_ladder.halt_at_pct": "risk profile max_drawdown_pct", "drawdown_ladder.reduce_factor": OWNER, max_positions: OWNER, max_new_per_day: OWNER,
  "min_rr.positional": "risk profile min_reward_risk", "risk_pct.positional": "risk profile per_trade_risk_pct", "risk_pct.intraday": "risk profile per_trade_risk_pct × 0.7",
  "risk_pct.fno": "risk profile per_trade_risk_pct × 0.7", stressed_gap_pct: OWNER, "allocation_buckets_pct.equity_positional": OWNER,
  "allocation_buckets_pct.equity_intraday": OWNER, "allocation_buckets_pct.fno": OWNER, "allocation_buckets_pct.reserve": OWNER, min_adv_rs: OWNER,
  max_adv_participation_pct: OWNER, max_chase_pct: OWNER, approval_expiry_minutes: OWNER,
};
const config = (o: Row = {}): Row => {
  const extras = clone(DEFAULTS) as Row;
  (extras.risk_pct as Row).positional = 0.4;                                           // the one override below
  return {
    user_id: UID, account_id: UID, mode: "approval", version: 3, extras, overrides: { risk_pct: { positional: 0.4 } }, defaults: clone(DEFAULTS),
    defaults_source: SOURCES, profile: { profile: "moderate", limits_version: "MOCK-lim-v1", stored: true,
      limits: { per_trade_risk_pct: 0.5, max_drawdown_pct: 10, min_reward_risk: 1.5, max_open_risk_pct: 3, daily_loss_pct: 2 } },
    warnings: [], updated_at: "2026-11-05T01:40:00+00:00", updated_by: UID, reason: "MOCK: tighter positional risk", stored: true, policy_version: "spt-config-v2", ...o,
  };
};
const OLD_CONFIG = (): Row => ({ user_id: UID, account_id: UID, mode: "approval", version: 2, extras: clone(DEFAULTS),
  defaults_source: { drawdown_ladder: "PRD §9.7", max_positions: "PRD §9.4 / §26", risk_pct: "PRD §9.4 / §26" }, updated_at: null, updated_by: null, reason: null,
  stored: true, policy_version: "spt-config-v1" });
const VERSIONS = [{ version_id: "ver-3", user_id: UID, version: 3, version_before: 2, at: "2026-11-05T01:40:00+00:00", actor: UID, actor_is_admin: false,
  changed: ["risk_pct.positional"], loosened: [], reason: "MOCK: tighter positional risk", status: "applied" }];

// ── MOCK — not real data: opportunities (DESIGN.md §4) and proposals (services/spt/proposals.public) ───────────────────────
const NOW = Date.now();
const iso = (ms: number) => new Date(ms).toISOString();
const sig = (id: string, scanner: string, name: string, px: number, score: number | null) => ({ signal_id: id, scanner_id: scanner, scanner_name: name,
  detected_at: "2026-11-05T04:05:00+00:00", detected_price: px, scanner_score: score, score_version: "MOCK", category: "breakout", family: "trend" });
const validation = (decision: string, score: number, codes: string[] = []) => ({ at: "2026-11-05T04:10:00+00:00", version: "spt-validate-v1", decision,
  reason_codes: codes, explanations: codes.length ? codes.map((c) => `MOCK: ${c}`) : ["MOCK: every check passed"], opportunity_score: score,
  score_parts: { confirmations: { points: 18, max: 30, note: "MOCK two families" }, trend: { points: 19, max: 25, note: "MOCK above the averages" } },
  market: { regime: "bullish", as_of: "2026-11-04" }, stock: { close: 1405.2, ema20: 1380.1 }, liquidity: { adv_rs: 2500000000 }, derivatives: null, data_as_of: { bars: "2026-11-04" } });
const opp = (id: string, symbol: string, state: string, o: Row = {}): Row => ({
  _id: id, consolidation_key: `MOCK:${symbol}`, symbol, exchange: "NSE", direction: "long", family: "trend", category: "breakout", horizon: "positional",
  day: "2026-11-05", first_seen_at: "2026-11-05T04:05:00+00:00", window_until: iso(NOW + 5 * 86400e3), expires_at: iso(NOW + 5 * 86400e3), state, version: 2,
  signals: [sig(`sig:2026-11-05:w-breakout:${symbol}`, "w-breakout", "MOCK Breakout 52w", 1402, 81), sig(`sig:2026-11-05:strong:${symbol}`, "strong", "MOCK Strong signal", 1404, 77)],
  conflicts: [], strong: { signal_id: `sig:2026-11-05:strong:${symbol}`, plan: { rules: "scan-plan-v3", entry: 1410, stop_loss: 1374.9, target_1: 1480, target_2: 1550, atr: 17.55, sma20: 1380.1, plan_ok: true, plan_note: null } },
  validation: validation(state, 72), created_at: "2026-11-05T04:05:00+00:00", updated_at: "2026-11-05T04:10:00+00:00", ...o,
});
const OPPS = [
  opp("opp-1", "ICICIBANK", "QUALIFIED"),
  opp("opp-2", "TCS", "QUALIFIED"),
  opp("opp-3", "INFY", "WATCHLIST", { horizon: "intraday", signals: [sig("sig:2026-11-05:w-volume:INFY", "w-volume", "MOCK Volume surge", 1590, null)], strong: null,
    validation: validation("WATCHLIST", 41, ["horizon_intraday"]) }),
];
const prop = (id: string, oppId: string, symbol: string, state: string, o: Row = {}): Row => ({
  proposal_id: id, user_id: UID, account_id: UID, opportunity_id: oppId, symbol, exchange: "NSE", direction: "long", horizon: "positional", instrument: "cash", template: "cash_long_positional_v1",
  state, version: 4, entry: { type: "MARKET", price: 1410, basis: "live ask", chase_bound: 1424.1, plan_entry: 1410, limit_price: null, time_in_force: "DAY", expires_at: iso(NOW + 5 * 3600e3), rule: "MOCK immediate: live price within the chase bound" },
  stop_loss: 1374.9, target_1: 1480, target_2: 1550, rr: { t1: 1.99, t2: 3.99, min_rr: 1.5, measured_to: "target_2", basis: "MOCK" }, risk_per_share: 35.1,
  sizing: { quantity: 35, capital_required: 49350, planned_risk: 1268.5, stressed_risk: 1749.7, blocked: [], risk_pct: { pct: 0.4 } },
  allocation: { decision: "ALLOCATION_APPROVED", quantity: 35, requested_qty: 35, reasons: [] },
  risk: { decision: "APPROVE", stage: "risk", reason_codes: [], explanations: [], requested_qty: 35, approved_qty: 35, planned_risk_rs: 1268.5, stressed_risk_rs: 1749.7,
    portfolio_risk_before_rs: 12000, portfolio_risk_after_rs: 13268.5, exposure_before_rs: 250000, exposure_after_rs: 299350, conditional: null, at: "2026-11-05T04:12:00+00:00" },
  approval: null, order: null, order_id: null, order_rejected: false, reason_codes: [], explanations: [],
  exit_plan: { stop_loss: 1374.9, target_1: 1480, target_2: 1550, t1_exit_fraction: 0.5, move_stop_to_breakeven_at_t1: true, trail: { rule: "trail-atr-v1", k: 2 }, trend_exit: { rule: "close_below_sma20" }, max_hold_sessions: 20 },
  price: { ok: true, price: 1410, basis: "ask", received_at: "2026-11-05T04:11:58+00:00", age_s: 2 }, created_at: "2026-11-05T04:12:00+00:00",
  state_history: [{ from: null, to: "PROPOSAL_GENERATED", at: "2026-11-05T04:12:00+00:00", reason: "proposal generated" }, { from: "RISK_APPROVED", to: state, at: "2026-11-05T04:12:01+00:00", reason: "MOCK" }], ...o,
});
const PROPS = (): Row[] => [
  prop("prop-1", "opp-1", "ICICIBANK", "AWAITING_USER_APPROVAL", { approval: { requested_at: iso(NOW), expires_at: iso(NOW + 20 * 60e3), decided_at: null, decided_by: null, decision: null } }),
  prop("prop-2", "opp-2", "TCS", "ORDER_CREATED", { order: { order_id: "ord-2", state: "FILLED", order_type: "MARKET", quantity: 35, created_at: "2026-11-05T04:13:00+00:00", reject_reason: null, duplicate: false } }),
  prop("prop-9", "opp-9", "HDFCBANK", "BLOCKED_BY_RISK", { risk: { decision: "BLOCKED", stage: "risk", reason_codes: ["max_positions_reached"], explanations: ["MOCK: ten positions are open"],
    requested_qty: 20, approved_qty: 0, planned_risk_rs: null, stressed_risk_rs: 900, portfolio_risk_before_rs: 12000, portfolio_risk_after_rs: null, exposure_before_rs: 250000, exposure_after_rs: null } }),
];

// ── MOCK — not real data: analytics (outcomes/analytics.py) and closed trades (spt_paper._trade) ──────────────────────────
const hz = (n: number, hit: number, ci: [number, number], avg: number) => ({ n, hit_rate_pct: hit, hit_rate_ci95_pct: ci, avg_return_pct: avg, median_return_pct: avg, avg_mfe_pct: 2.1, avg_mae_pct: -1.3, small_sample: n < 30 });
const SMALL = "Fewer than 30 measured signals: too few to draw a conclusion.";
const ANALYTICS = (kind: string | null) => ({
  ok: true, from: "2026-10-06", to: "2026-11-05", kind, version: "spt-outcome-v1", min_sample: 30,
  note: "MOCK: signal outcomes on end-of-day closes. Counts of what happened, not probabilities; they say nothing about any paper trade.",
  totals: { signals: 40, horizons: { t1: hz(40, 55, [39.8, 69.3], 0.38) }, small_sample: false },
  by_scanner: [
    { key: "w-breakout", signals: 34, horizons: { t1: hz(34, 55.9, [39.5, 71.1], 0.42), t5: hz(20, 60, [38.7, 78.1], 1.1) }, small_sample: false },
    { key: "w-volume", signals: 6, horizons: { t1: hz(6, 50, [18.8, 81.2], -0.2) }, small_sample: true, note: SMALL },
  ],
  by_category: [{ key: "breakout", signals: 40, horizons: { t1: hz(40, 55, [39.8, 69.3], 0.38) }, small_sample: false }],
  by_score_band: [{ key: "80-89", signals: 12, horizons: { t1: hz(12, 58.3, [32, 80.7], 0.5) }, small_sample: true, note: SMALL,
    plan: { rules: "scan-plan-v3", decided: 8, stop_rate_pct: 37.5, target_1_rate_pct: 50, target_2_rate_pct: 12.5, trend_exit_rate_pct: 0, time_exit_rate_pct: 0, avg_r_multiple: 0.61, small_sample: true } }],
});
const trade = (id: string, sym: string, net: number, r: number, opened: string, closed: string, exit: string, sigs: string[]) => ({
  trade_id: id, position_id: id, symbol: sym, direction: "long", quantity: 10, avg_entry_price: 100, avg_exit_price: 100 + net / 10, realized_gross_rs: net + 40, realized_net_rs: net,
  costs_rs: 40, r_multiple: r, mfe_rs: null, mae_rs: null, mfe_r: null, mae_r: null, exit_reason: exit, exit_gap: null, opened_at: opened, closed_at: closed,
  proposal_id: `p-${id}`, opportunity_id: `o-${id}`, entry_order_id: `e-${id}`, release_state: "released", signal_ids: sigs,
});
// Hand calculation: 3 trades, 2 won (1,200 · 300), 1 lost (−500) → win rate 66.7 %, average win ₹750, average loss −₹500,
// expectancy ₹ = ⅔ × 750 − ⅓ × 500 = +₹333, expectancy R = (1.2 − 1.0 + 0.3) ÷ 3 = +0.17 R, profit factor 1,500 ÷ 500 = 3.00,
// net +₹1,000, holding (3.25 + 1 + 3) ÷ 3 = 2.4 days.
const TRADES = [
  trade("t-1", "ICICIBANK", 1200, 1.2, "2026-10-28T04:00:00+00:00", "2026-10-31T10:00:00+00:00", "target_2", ["sig:2026-10-28:w-breakout:ICICIBANK", "sig:2026-10-28:strong:ICICIBANK"]),
  trade("t-2", "TCS", -500, -1.0, "2026-10-29T04:00:00+00:00", "2026-10-30T04:00:00+00:00", "stop", ["sig:2026-10-29:w-breakout:TCS"]),
  trade("t-3", "INFY", 300, 0.3, "2026-11-01T04:00:00+00:00", "2026-11-04T04:00:00+00:00", "trend", ["sig:2026-11-01:w-volume:INFY"]),
];
const MARKET = { values: { min_adv_rs: 10000000, positional_window_sessions: 5, validate_max_per_round: 60, quote_max_age_s: 120 },
  sources: { min_adv_rs: "default", positional_window_sessions: "default", validate_max_per_round: "default", quote_max_age_s: "default" }, stored: {}, version: 0,
  updated_at: null, updated_by: null, reason: null, policy_version: "spt-settings-v1", versions: [],
  fields: { min_adv_rs: { env: "SPT_MIN_ADV_RS", default: 10000000, range: [0, 1e12], used_by: "MOCK slice A" }, positional_window_sessions: { env: "SPT_POSITIONAL_WINDOW_SESSIONS", default: 5, range: [1, 60], used_by: "MOCK slice A" },
    validate_max_per_round: { env: "SPT_VALIDATE_MAX_PER_ROUND", default: 60, range: [1, 1000], used_by: "MOCK slice A" }, quote_max_age_s: { env: "SPT_QUOTE_MAX_AGE_S", default: 120, range: [5, 600], used_by: "MOCK slices B and C" } } };

interface Seen {
  oppQueries: URLSearchParams[]; approves: string[]; rejects: Array<{ id: string; body: unknown }>; puts: unknown[]; adminPuts: Array<{ uid: string; body: unknown }>;
  settingsPuts: unknown[]; accountGets: number; analyticsQueries: URLSearchParams[];
}
interface Opts {
  phone?: boolean; admin?: boolean; mode?: string; cfg?: () => Row; opps?: { status: number; body: unknown }; props?: () => Row[]; trades?: Row[];
  approve?: { status: number; body: unknown }; put?: (body: Row, n: number) => { status: number; body: unknown };
}

async function setup(page: Page, o: Opts = {}): Promise<Seen> {
  const seen: Seen = { oppQueries: [], approves: [], rejects: [], puts: [], adminPuts: [], settingsPuts: [], accountGets: 0, analyticsQueries: [] };
  let cfg: Row = o.cfg ? o.cfg() : config(o.mode ? { mode: o.mode } : {});
  if (o.phone) await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/api/**", (r) => json(r, { detail: "MOCK: not mocked in this spec" }, 404));
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  // MOCK — not real data: the signed-in user (the fixture is an admin; `admin: false` turns that off).
  if (o.admin === false) await page.route("**/api/auth/me", (r) => json(r, { user_id: UID, email: "mock@example.com", name: "MOCK User", is_admin: false, onboarding_completed: true, copilot_enabled: true }));
  await page.route("**/api/chat/sessions", (r) => json(r, []));
  await page.route("**/api/move-odds/**", (r) => json(r, { detail: "feature_not_enabled" }, 403));
  await page.route("**/api/risk/status", (r) => json(r, { kill_switch: false, halted: false, policy_version: "MOCK" }));
  await page.route("**/api/live/**", (r) => json(r, { available: false, reason: "MOCK: feed off", quotes: {}, mode: "expired", session: "closed", stale: true }));
  await page.route("**/api/desk/alerts*", (r) => json(r, { as_of: "2026-11-03", alerts: [] }));
  await page.route("**/api/desk/paper-trades*", (r) => json(r, { as_of: "2026-11-03", checked_through: "2026-11-03", trades: [], summary: { open: 0, closed: 0 }, status: "all" }));

  const account = () => ({ account_id: UID, account: { capital_rs: 1000000, note: "MOCK" }, config: clone(cfg), modes: ["off", "tracking", "approval", "auto"], note: "MOCK: one paper account per user" });
  await page.route(/\/api\/v1\/paper\/accounts(\?|$)/, (r) => { seen.accountGets += 1; return json(r, { accounts: [account()], count: 1 }); });
  await page.route(/\/api\/v1\/paper\/accounts\/[^/?]+(\?|$)/, (r) => json(r, { ...account(), config_versions: clone(VERSIONS) }));
  await page.route(/\/api\/v1\/paper\/accounts\/[^/]+\/config(\?|$)/, (r) => {
    const body = r.request().postDataJSON() as Row;
    seen.puts.push(body);
    const a = o.put ? o.put(body, seen.puts.length) : null;
    if (a && a.status !== 200) return json(r, a.body, a.status);
    cfg = { ...cfg, ...(body.mode ? { mode: body.mode } : {}), version: Number(cfg.version) + 1 };
    return json(r, { account_id: UID, config: clone(cfg) });
  });
  await page.route(/\/api\/v1\/opportunities(\?|$)/, (r) => {
    const q = new URL(r.request().url()).searchParams;
    seen.oppQueries.push(q);
    if (o.opps) return json(r, o.opps.body, o.opps.status);
    const rows = OPPS.filter((x) => (!q.get("state") || x.state === q.get("state")) && (!q.get("horizon") || x.horizon === q.get("horizon")) && (!q.get("direction") || x.direction === q.get("direction")));
    return json(r, { ok: true, count: rows.length, limit: 500, opportunities: clone(rows), score_label: "MOCK: Opportunity score 0–100, a rule-based measure of how complete the evidence is. It is not a probability of profit." });
  });
  await page.route(/\/api\/v1\/opportunities\/[^/?]+(\?|$)/, (r) => {
    const id = decodeURIComponent(new URL(r.request().url()).pathname.split("/").pop() as string);
    const x = OPPS.find((y) => y._id === id);
    return x ? json(r, { ok: true, opportunity: clone(x), score_label: "MOCK" }) : json(r, { detail: "opportunity_not_found" }, 404);
  });
  await page.route(/\/api\/v1\/opportunities\/[^/]+\/(approve|reject|validate)$/, (r) => {
    const [, id, what] = new URL(r.request().url()).pathname.match(/opportunities\/([^/]+)\/(approve|reject|validate)$/) as RegExpMatchArray;
    if (what === "approve") {
      seen.approves.push(id);
      if (o.approve) return json(r, o.approve.body, o.approve.status);
      return json(r, { proposal: prop("prop-1", id, "ICICIBANK", "ORDER_CREATED"), idempotent: false,
        order: { _id: "ord-1", state: "PENDING", order_type: "MARKET", quantity: 35, limit_price: null, time_in_force: "DAY", expires_at: iso(NOW + 5 * 3600e3), reject_reason: null } });
    }
    if (what === "reject") {
      seen.rejects.push({ id, body: r.request().postDataJSON() });
      return json(r, { proposal: prop("prop-1", id, "ICICIBANK", "USER_REJECTED"), idempotent: false });
    }
    return json(r, { ok: true, opportunity_id: id, state: "QUALIFIED", validation: validation("QUALIFIED", 75) });
  });
  await page.route(/\/api\/v1\/proposals(\?|$)/, (r) => { const items = (o.props ?? PROPS)(); return json(r, { items, count: items.length }); });
  await page.route(/\/api\/v1\/analytics\/scanners(\?|$)/, (r) => {
    const q = new URL(r.request().url()).searchParams;
    seen.analyticsQueries.push(q);
    return json(r, ANALYTICS(q.get("kind")));
  });
  await page.route(/\/api\/v1\/paper\/trades(\?|$)/, (r) => { const t = o.trades ?? TRADES; return json(r, { trades: clone(t), count: t.length }); });
  await page.route(/\/api\/admin\/spt\/settings$/, (r) => {
    if (r.request().method() === "PUT") { seen.settingsPuts.push(r.request().postDataJSON()); return json(r, { ...clone(MARKET), version: 1 }); }
    return json(r, clone(MARKET));
  });
  await page.route(/\/api\/admin\/spt\/[^/]+\/config$/, (r) => {
    const uid = decodeURIComponent(new URL(r.request().url()).pathname.split("/").slice(-2)[0]);
    if (r.request().method() === "PUT") { seen.adminPuts.push({ uid, body: r.request().postDataJSON() }); return json(r, { account_id: uid, config: config({ user_id: uid, account_id: uid, mode: "off", version: 2 }) }); }
    return json(r, { account_id: uid, config: config({ user_id: uid, account_id: uid, mode: "off", version: 1, overrides: {}, extras: clone(DEFAULTS) }), versions: [] });
  });
  return seen;
}

const params = (page: Page) => new URL(page.url()).searchParams;
const row = (page: Page, id: string) => page.locator(`[data-testid="spt-row"][data-id="${id}"]`);
const leaf = (page: Page, path: string, prefix = "spt-limits") => page.locator(`[data-testid="${prefix}-leaf"][data-path="${path}"]`);

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

test.describe("MOCK — not real data: Paper Trading › Scanner-to-Paper Trading screens", () => {
  test("SPT-UI-P-01 Paper Trading has the three new sub-views, each with its screen", async ({ page }) => {
    await setup(page);
    await page.goto(at("live"));
    await expect(page.getByTestId("desk-subviews").getByRole("button")).toHaveText(["Live desk", "Trade journal", "P&L dashboard", "Opportunities", "Analytics", "Settings"], SLOW);
    for (const [key, id, label] of [["opportunities", "spt-opps", "Opportunities"], ["analytics", "spt-analytics", "Analytics"], ["settings", "spt-settings", "Settings"]]) {
      await page.getByTestId(`desk-sub-${key}`).click();
      await expect.poll(() => params(page).get("sub")).toBe(key);
      await expect(page.getByTestId(id)).toBeVisible(SLOW);
      await expect(page.getByTestId("desk-trail")).toHaveText(new RegExp(`Paper Trading›${label}$`));
    }
  });

  test("SPT-UI-P-02 / P-03 / P-04 / P-05 the mode banner, the note, and one row per opportunity joined to the user's proposal", async ({ page }) => {
    await setup(page);
    await page.goto(at("opportunities"));
    const banner = page.getByTestId("spt-mode-banner");
    await expect(banner).toHaveAttribute("data-mode", "approval", SLOW);
    await expect(page.getByTestId("spt-mode-value")).toHaveText("Approval");
    await expect(banner).toContainText("A risk-approved proposal waits for you");
    await expect(page.getByTestId("spt-awaiting-count")).toHaveText("1 awaiting your approval");
    await expect(page.getByTestId("spt-opps-note")).toHaveText("Rule-based levels for your paper account. Not investment advice; no accuracy is claimed.");
    await expect(page.getByTestId("spt-opps-table")).toContainText("not a probability");
    await expect(page.getByTestId("spt-opps-table")).toContainText("sized by your limits");
    // 3 opportunities + 1 proposal whose opportunity is not in the list; the one awaiting approval first.
    await expect(page.getByTestId("spt-row")).toHaveCount(4);
    await expect(page.getByTestId("spt-row").first()).toHaveAttribute("data-id", "opp-1");
    const r1 = row(page, "opp-1");
    await expect(r1.getByTestId("spt-row-symbol")).toHaveText("ICICIBANK");
    await expect(r1.getByTestId("spt-row-state")).toHaveText("Qualified");
    await expect(r1.getByTestId("spt-row-sources")).toHaveText("2 · MOCK Breakout 52w, MOCK Strong signal");
    await expect(r1.getByTestId("spt-row-score")).toHaveText("72");
    await expect(r1.getByTestId("spt-row-levels")).toHaveText("₹1,410.00 / ₹1,374.90 / ₹1,480.00 / ₹1,550.00");
    await expect(r1.getByTestId("spt-row-rr")).toHaveText("1.99 / 3.99");
    await expect(r1.getByTestId("spt-row-qty")).toHaveText("35");
    await expect(r1.getByTestId("spt-row-capital")).toHaveText("₹49,350");
    await expect(r1.getByTestId("spt-row-planned")).toHaveText("₹1,269");
    await expect(r1.getByTestId("spt-row-risk")).toHaveText("Approved");
    await expect(r1.getByTestId("spt-row-proposal")).toHaveText("Awaiting your approval");
    await expect(r1.getByTestId("spt-row-countdown")).toHaveText(/^\d+m \d\ds left$/);
    await expect(row(page, "opp-2").getByTestId("spt-row-order")).toContainText("Filled");
    await expect(row(page, "opp-3").getByTestId("spt-row-noproposal")).toHaveText("No proposal · only qualified opportunities are proposed");
    const r9 = row(page, "opp-9");
    await expect(r9.getByTestId("spt-row-state")).toHaveText("not in list");
    await expect(r9.getByTestId("spt-row-risk")).toHaveText("Blocked");
    await expect(r9.getByTestId("spt-row-codes")).toHaveText("max_positions_reached");
    await page.getByTestId("spt-mode-change").click();
    await expect.poll(() => params(page).get("sub")).toBe("settings");
    await expect(page.getByTestId("spt-settings")).toBeVisible(SLOW);
  });

  test("SPT-UI-P-06 the filters go to the route; the symbol search narrows the rows", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(at("opportunities"));
    await expect(page.getByTestId("spt-row")).toHaveCount(4, SLOW);
    await page.getByTestId("spt-filter-state").selectOption("QUALIFIED");
    await expect.poll(() => seen.oppQueries.some((q) => q.get("state") === "QUALIFIED")).toBe(true);
    await expect(page.getByTestId("spt-row")).toHaveCount(2);              // the proposal-only row has no market-wide state
    await page.getByTestId("spt-filter-state").selectOption("");
    await page.getByTestId("spt-filter-horizon").selectOption("intraday");
    await expect.poll(() => seen.oppQueries.some((q) => q.get("horizon") === "intraday")).toBe(true);
    await expect(page.getByTestId("spt-row")).toHaveCount(1);
    await page.getByTestId("spt-filter-horizon").selectOption("");
    await page.getByTestId("spt-filter-direction").selectOption("long");
    await expect.poll(() => seen.oppQueries.some((q) => q.get("direction") === "long")).toBe(true);
    await page.getByTestId("spt-search").fill("tcs");
    await expect(page.getByTestId("spt-row")).toHaveCount(1);
    await expect(page.getByTestId("spt-row").first()).toHaveAttribute("data-symbol", "TCS");
    expect(seen.oppQueries.every((q) => q.get("limit") === "500")).toBe(true);
  });

  test("SPT-UI-P-07 / P-08 the drawer shows the evidence; Approve POSTs and shows the order", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(at("opportunities"));
    await row(page, "opp-1").click();
    const d = page.getByTestId("spt-drawer");
    await expect(d).toBeVisible(SLOW);
    await expect(d.getByTestId("spt-drawer-signal")).toHaveCount(2);
    await expect(d.getByTestId("spt-drawer-signal").first()).toContainText("MOCK Breakout 52w");
    await expect(d.getByTestId("spt-drawer-signal").first()).toContainText("scanner score 81");
    await expect(d.getByTestId("spt-validation-decision")).toHaveText("Qualified");
    await expect(d.getByTestId("spt-validation-score")).toHaveText("score 72 / 100 · not a probability");
    await expect(d.getByTestId("spt-prop-entry")).toContainText("MARKET at ₹1,410.00");
    await expect(d.getByTestId("spt-prop-exit")).toContainText("50% at target 1, then stop loss to breakeven");
    await expect(d.getByTestId("spt-risk-planned")).toHaveText("₹1,269 / ₹1,750");
    await expect(d.getByTestId("spt-risk-portfolio")).toHaveText("₹12,000 → ₹13,269");
    await expect(d.getByTestId("spt-countdown")).toHaveText(/^Approval window: \d+m \d\ds left$/);
    await d.getByTestId("spt-approve").click();
    await expect.poll(() => seen.approves).toEqual(["opp-1"]);
    await expect(d.getByTestId("spt-approve-result")).toHaveAttribute("data-order-state", "PENDING");
    await expect(d.getByTestId("spt-approve-result")).toContainText("Paper order MARKET for 35 shares");
    await expect(d.getByTestId("spt-approve-result")).toContainText("Pending");
    await expect(d).not.toContainText(BANNED);
  });

  test("SPT-UI-P-09 a refused approval shows the code, the message and the reason codes", async ({ page }) => {
    const seen = await setup(page, { approve: { status: 409, body: { detail: { code: "entry_no_longer_valid", message: "MOCK: The live price is above the chase bound. The proposal expired.", reason_codes: ["price_above_chase_bound"], decision: null } } } });
    await page.goto(at("opportunities"));
    await row(page, "opp-1").click();
    await page.getByTestId("spt-approve").click();
    await expect.poll(() => seen.approves.length).toBe(1);
    const e = page.getByTestId("spt-approve-error");
    await expect(e).toHaveAttribute("data-code", "entry_no_longer_valid");
    await expect(e).toContainText("MOCK: The live price is above the chase bound.");
    await expect(page.getByTestId("spt-approve-error-codes")).toHaveText("price_above_chase_bound");
    await expect(page.getByTestId("spt-approve-result")).toHaveCount(0);
  });

  test("SPT-UI-P-10 Reject needs a reason, then POSTs it", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(at("opportunities"));
    await row(page, "opp-1").click();
    await page.getByTestId("spt-reject").click();
    await page.getByTestId("spt-reject-confirm").click();
    await expect(page.getByTestId("spt-reject-need-reason")).toBeVisible();
    await page.waitForTimeout(300);
    expect(seen.rejects).toEqual([]);
    await page.getByTestId("spt-reject-reason").fill("MOCK: too extended after the gap");
    await page.getByTestId("spt-reject-confirm").click();
    await expect.poll(() => seen.rejects).toEqual([{ id: "opp-1", body: { reason: "MOCK: too extended after the gap" } }]);
    await expect(page.getByTestId("spt-reject-result")).toContainText("Rejected and recorded");
  });

  test("SPT-UI-P-11 Auto mode: no approval asked; the drawer says what happened", async ({ page }) => {
    await setup(page, { mode: "auto", props: () => PROPS().filter((p) => p.proposal_id !== "prop-1") });
    await page.goto(at("opportunities"));
    await expect(page.getByTestId("spt-mode-value")).toHaveText("Auto", SLOW);
    await expect(page.getByTestId("spt-mode-banner")).toContainText("without asking you");
    await row(page, "opp-2").click();
    await expect(page.getByTestId("spt-outcome-state")).toHaveText("Paper order created");
    await expect(page.getByTestId("spt-outcome-order")).toContainText("Filled");
    await expect(page.getByTestId("spt-approve")).toHaveCount(0);
  });

  test("SPT-UI-P-11b Tracking mode: a tracked proposal says no order was placed", async ({ page }) => {
    await setup(page, { mode: "tracking", props: () => [prop("prop-2", "opp-2", "TCS", "TRACKING_ONLY")] });
    await page.goto(at("opportunities"));
    await expect(page.getByTestId("spt-mode-value")).toHaveText("Tracking", SLOW);
    await expect(row(page, "opp-2").getByTestId("spt-row-proposal")).toHaveText("Tracked, no order");
    await row(page, "opp-2").click();
    await expect(page.getByTestId("spt-outcome-tracked")).toHaveText("Tracked only: no paper order was placed (tracking mode).");
    await expect(page.getByTestId("spt-approve")).toHaveCount(0);
  });

  test("SPT-UI-P-12 a failing read shows the problem; an empty list says so", async ({ page }) => {
    await setup(page, { opps: { status: 500, body: { detail: "MOCK: server error" } } });
    await page.goto(at("opportunities"));
    await expect(page.getByTestId("spt-opps-error")).toBeVisible(SLOW);
    await expect(page.getByTestId("spt-row")).toHaveCount(0);
  });

  test("SPT-UI-P-12b no opportunities and no proposals: the empty state", async ({ page }) => {
    await setup(page, { opps: { status: 200, body: { ok: true, count: 0, limit: 500, opportunities: [], score_label: "MOCK" } }, props: () => [] });
    await page.goto(at("opportunities"));
    await expect(page.getByTestId("spt-opps-empty")).toContainText("No opportunity matches yet", SLOW);
  });

  test("SPT-UI-P-13 scanner outcomes: sample sizes, intervals, small samples flagged, kind sent", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(at("analytics"));
    const s = page.getByTestId("spt-an-scanners");
    await expect(s.getByTestId("spt-an-row")).toHaveCount(2, SLOW);
    await expect(page.getByTestId("spt-an-not-prob")).toHaveText("Counts of what happened, not probabilities.");
    const b = s.locator('[data-testid="spt-an-row"][data-key="w-breakout"]');
    await expect(b).toHaveAttribute("data-small", "false");
    await expect(b.getByTestId("spt-an-signals")).toHaveText("34");
    await expect(b.getByTestId("spt-an-t1")).toContainText("n 34");
    await expect(b.getByTestId("spt-an-t1")).toContainText("hit 55.9% (39.5–71.1)");
    await expect(b.getByTestId("spt-an-t1")).toContainText("avg +0.42%");
    await expect(b.getByTestId("spt-an-t5").getByTestId("spt-an-small")).toBeVisible();
    const v = s.locator('[data-testid="spt-an-row"][data-key="w-volume"]');
    await expect(v).toHaveAttribute("data-small", "true");
    await expect(v.getByTestId("spt-an-small").first()).toHaveAttribute("title", SMALL);
    await expect(page.getByTestId("spt-an-notes")).toContainText("fewer than 30 measured signals");
    await page.getByTestId("spt-an-kind").selectOption("strong");
    await expect.poll(() => seen.analyticsQueries.some((q) => q.get("kind") === "strong")).toBe(true);
    await page.getByTestId("spt-an-group").selectOption("band");
    await expect(s.getByTestId("spt-an-row")).toHaveCount(1);
    await expect(s.getByTestId("spt-an-plan")).toContainText("target 1 50.0% · stop 37.5%");
    await expect(page.getByTestId("spt-analytics")).not.toContainText(BANNED);
  });

  test("SPT-UI-P-14 paper results are computed from the returned trades only, formulas shown", async ({ page }) => {
    await setup(page);
    await page.goto(at("analytics"));
    await expect(page.getByTestId("spt-an-trades")).toHaveText("3", SLOW);
    await expect(page.getByTestId("spt-an-winrate")).toHaveText("66.7%");
    await expect(page.getByTestId("spt-an-avgwin")).toHaveText("+₹750");
    await expect(page.getByTestId("spt-an-avgloss")).toHaveText("−₹500");
    await expect(page.getByTestId("spt-an-exp-r")).toHaveText("+0.17 R");
    await expect(page.getByTestId("spt-an-exp-rs")).toHaveText("+₹333");
    await expect(page.getByTestId("spt-an-pf")).toHaveText("3.00");
    await expect(page.getByTestId("spt-an-net")).toHaveText("+₹1,000");
    await expect(page.getByTestId("spt-an-hold")).toHaveText("2.4 days");
    await expect(page.getByTestId("spt-an-formulas")).toContainText("win rate × average win − loss rate × |average loss|");
    await expect(page.getByTestId("spt-an-formulas")).toContainText("gross profit ÷ |gross loss|");
    await expect(page.locator('[data-testid="spt-an-exit"][data-reason="target_2"]')).toHaveText("Target 2 · 1");
    await expect(page.locator('[data-testid="spt-an-exit"][data-reason="stop"]')).toHaveText("Stop loss · 1");
    const br = page.locator('[data-testid="spt-an-scanner-row"][data-key="w-breakout"]');
    await expect(br).toContainText("2 trades · win 50.0% · net +₹700");
    await expect(page.locator('[data-testid="spt-an-scanner-row"][data-key="w-volume"]')).toContainText("1 trade · win 100.0%");
  });

  test("SPT-UI-P-15 no closed SPT trade: the empty state, no figure invented", async ({ page }) => {
    await setup(page, { trades: [] });
    await page.goto(at("analytics"));
    await expect(page.getByTestId("spt-an-results-empty")).toContainText("No closed paper trade from scanner opportunities yet", SLOW);
    await expect(page.getByTestId("spt-an-kpis")).toHaveCount(0);
  });

  test("SPT-UI-P-16 mode change PUTs; Auto asks first", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(at("settings"));
    await expect(page.getByTestId("spt-mode")).toHaveAttribute("data-mode", "approval", SLOW);
    await expect(page.getByTestId("spt-mode-tracking")).toContainText("only tracked");
    await page.getByTestId("spt-mode-tracking").click();
    await expect.poll(() => seen.puts).toEqual([{ mode: "tracking", expected_version: 3 }]);
    await expect(page.getByTestId("spt-mode")).toHaveAttribute("data-mode", "tracking");
    await page.getByTestId("spt-mode-auto").click();
    await expect(page.getByTestId("spt-mode-confirm")).toContainText("without asking you");
    await page.waitForTimeout(300);
    expect(seen.puts.length).toBe(1);
    await page.getByTestId("spt-mode-confirm-no").click();
    await expect(page.getByTestId("spt-mode-confirm")).toHaveCount(0);
    await page.getByTestId("spt-mode-auto").click();
    await page.getByTestId("spt-mode-confirm-yes").click();
    await expect.poll(() => seen.puts.length).toBe(2);
    expect(seen.puts[1]).toEqual({ mode: "auto", expected_version: 4 });
  });

  test("SPT-UI-P-17 / P-21 each limit shows its value, default, source and override; Save sends only the changed leaf", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(at("settings"));
    await expect(page.getByTestId("spt-limits-leaf")).toHaveCount(19, SLOW);
    const rp = leaf(page, "risk_pct.positional");
    await expect(rp).toHaveAttribute("data-overridden", "true");
    await expect(rp.getByTestId("spt-limits-input")).toHaveValue("0.4");
    await expect(rp.getByTestId("spt-limits-default")).toHaveText("default 0.5%");
    await expect(rp.getByTestId("spt-limits-source")).toContainText("Risk profile: risk profile per_trade_risk_pct");
    const halt = leaf(page, "drawdown_ladder.halt_at_pct");
    await expect(halt).toHaveAttribute("data-overridden", "false");
    await expect(halt.getByTestId("spt-limits-default")).toHaveText("default 10%");
    await expect(leaf(page, "max_positions").getByTestId("spt-limits-source")).toContainText("SPT default: spt-default (owner-approved 5 Nov 2026)");
    await expect(page.getByTestId("spt-limits-profile")).toContainText("per_trade_risk_pct 0.5");
    await expect(page.getByTestId("spt-limits-save")).toBeDisabled();
    await leaf(page, "max_new_per_day").getByTestId("spt-limits-input").fill("3");
    await page.getByTestId("spt-limits-save").click();
    await expect.poll(() => seen.puts).toEqual([{ extras: { max_new_per_day: 3 }, expected_version: 3 }]);
    await expect(page.getByTestId("spt-limits-saved")).toBeVisible();
    // the version history (P-21)
    await expect(page.getByTestId("spt-versions-row")).toHaveCount(1);
    await expect(page.getByTestId("spt-versions-row").first()).toContainText("v3");
    await expect(page.getByTestId("spt-versions-row").first()).toContainText("risk_pct.positional");
    await expect(page.getByTestId("spt-versions-row").first()).toContainText("MOCK: tighter positional risk");
  });

  test("SPT-UI-P-18 reset to default sends that leaf as null", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(at("settings"));
    const rp = leaf(page, "risk_pct.positional");
    await rp.getByTestId("spt-limits-reset").click();
    await expect(rp.getByTestId("spt-limits-input")).toHaveValue("0.5");
    await page.getByTestId("spt-limits-save").click();
    await expect.poll(() => seen.puts).toEqual([{ extras: { risk_pct: { positional: null } }, expected_version: 3 }]);
  });

  test("SPT-UI-P-19 a loosening by a non-admin: 'Loosening needs an admin' with the field", async ({ page }) => {
    const seen = await setup(page, { admin: false, put: () => ({ status: 403, body: { detail: { code: "admin_required",
      message: "MOCK: Only an admin can loosen an SPT limit (max_new_per_day). You can tighten any limit yourself.", loosened: ["max_new_per_day"] } } }) });
    await page.goto(at("settings"));
    await leaf(page, "max_new_per_day").getByTestId("spt-limits-input").fill("8");
    await page.getByTestId("spt-limits-save").click();
    await expect.poll(() => seen.puts.length).toBe(1);
    await expect(page.getByTestId("spt-limits-error-admin")).toHaveText("Loosening needs an admin: New entries a day at most.");
    await expect(page.getByTestId("spt-limits-error-fields")).toHaveText("max_new_per_day");
  });

  test("SPT-UI-P-20 a concurrent change asks to reload, and Reload reads again", async ({ page }) => {
    const seen = await setup(page, { put: () => ({ status: 409, body: { detail: { code: "concurrent_change", message: "MOCK: another change landed first; reload and retry" } } }) });
    await page.goto(at("settings"));
    await leaf(page, "max_positions").getByTestId("spt-limits-input").fill("6");
    await page.getByTestId("spt-limits-save").click();
    await expect(page.getByTestId("spt-limits-error")).toHaveAttribute("data-code", "concurrent_change");
    const before = seen.accountGets;
    await page.getByTestId("spt-limits-error-reload").click();
    await expect.poll(() => seen.accountGets).toBeGreaterThan(before);
  });

  test("SPT-UI-P-22 the admin panel is not shown to a non-admin", async ({ page }) => {
    await setup(page, { admin: false });
    await page.goto(at("settings"));
    await expect(page.getByTestId("spt-limits")).toBeVisible(SLOW);
    await expect(page.getByTestId("spt-admin")).toHaveCount(0);
  });

  test("SPT-UI-P-22b / P-23 an admin loads a user's config; a reason is required, then the admin PUT", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(at("settings"));
    await expect(page.getByTestId("spt-admin")).toBeVisible(SLOW);
    await page.getByTestId("spt-admin-uid").fill("user_other");
    await page.getByTestId("spt-admin-load-btn").click();
    await expect(page.getByTestId("spt-admin-user")).toContainText("user_other");
    await leaf(page, "max_positions", "spt-admin-limits").getByTestId("spt-admin-limits-input").fill("8");
    await page.getByTestId("spt-admin-limits-save").click();
    await expect(page.getByTestId("spt-admin-limits-need-reason")).toBeVisible();
    await page.waitForTimeout(300);
    expect(seen.adminPuts).toEqual([]);
    await page.getByTestId("spt-admin-limits-reason").fill("MOCK: owner asked for fewer positions");
    await page.getByTestId("spt-admin-limits-save").click();
    await expect.poll(() => seen.adminPuts).toEqual([{ uid: "user_other", body: { extras: { max_positions: 8 }, reason: "MOCK: owner asked for fewer positions", expected_version: 1 } }]);
  });

  test("SPT-UI-P-24 market-wide settings: values with sources; Save PUTs only the change with a reason", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(at("settings"));
    const f = page.locator('[data-testid="spt-market-field"][data-field="quote_max_age_s"]');
    await expect(f.getByTestId("spt-market-input")).toHaveValue("120", SLOW);
    await expect(f).toContainText("default 120 · range 5–600");
    await f.getByTestId("spt-market-input").fill("90");
    await page.getByTestId("spt-market-save").click();
    await expect(page.getByTestId("spt-market-need-reason")).toBeVisible();
    await page.getByTestId("spt-market-reason").fill("MOCK: quotes arrive faster now");
    await page.getByTestId("spt-market-save").click();
    await expect.poll(() => seen.settingsPuts).toEqual([{ values: { quote_max_age_s: 90 }, reason: "MOCK: quotes arrive faster now", expected_version: 0 }]);
  });

  test("SPT-UI-P-25 the earlier config shape still renders; reset is not offered", async ({ page }) => {
    await setup(page, { cfg: OLD_CONFIG });
    await page.goto(at("settings"));
    await expect(page.getByTestId("spt-limits")).toHaveAttribute("data-shape", "v1", SLOW);
    await expect(page.getByTestId("spt-limits-old-shape")).toBeVisible();
    await expect(leaf(page, "max_positions").getByTestId("spt-limits-input")).toHaveValue("10");
    await expect(page.getByTestId("spt-limits-reset")).toHaveCount(0);
  });

  test("SPT-UI-P-26 / P-27 phone 390 px: cards, no sideways scroll, no banned word on any of the three screens", async ({ page }) => {
    await setup(page, { phone: true });
    await page.goto(at("opportunities"));
    await expect(page.getByTestId("spt-opps")).toHaveAttribute("data-narrow", "true", SLOW);
    await expect(page.getByTestId("spt-opps-cards")).toBeVisible();
    await expect(page.getByTestId("spt-opps-table")).toHaveCount(0);
    await expect(row(page, "opp-1").getByTestId("spt-card-qty")).toHaveText("35");
    await noSideScroll(page);
    await expect(page.getByTestId("spt-opps")).not.toContainText(BANNED);
    await row(page, "opp-1").click();
    await expect(page.getByTestId("spt-drawer")).toBeVisible();
    await noSideScroll(page);
    await expect(page.getByTestId("spt-drawer")).not.toContainText(BANNED);
    await page.getByTestId("spt-drawer-close").click();
    await page.goto(at("analytics"));
    await expect(page.getByTestId("spt-an-trades")).toHaveText("3", SLOW);
    await noSideScroll(page);
    await expect(page.getByTestId("spt-analytics")).not.toContainText(BANNED);
    await page.goto(at("settings"));
    await expect(page.getByTestId("spt-limits-leaf")).toHaveCount(19, SLOW);
    await noSideScroll(page);
    await expect(page.getByTestId("spt-settings")).not.toContainText(BANNED);
  });

  test("SPT-UI-P-27 desktop: no banned word on the three screens", async ({ page }) => {
    await setup(page);
    for (const [sub, id] of [["opportunities", "spt-opps"], ["analytics", "spt-analytics"], ["settings", "spt-settings"]]) {
      await page.goto(at(sub));
      await expect(page.getByTestId(id)).toBeVisible(SLOW);
      await page.waitForTimeout(500);
      await expect(page.getByTestId(id)).not.toContainText(BANNED);
    }
  });
});
