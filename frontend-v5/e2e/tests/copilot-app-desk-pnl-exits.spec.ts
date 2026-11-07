/**
 * One-screen Copilot app (/v5/app) — Trade Desk › Paper Trading › 05 Real-time P&L › Exit watch (docs/paper_pnl_dashboard/
 * EXIT_WATCH.md; test cases EW-33 … EW-37 in test_reports/exit_watch_TESTCASES.md), reworked for Paper Trading v2
 * (UI_DESIGN_V2.md §5: "Exit-watch alerts … go to Overview's Risk warnings and a row action in Real-time P&L"; the P&L dashboard
 * was replaced). The live broker positions' stop loss and exit alerts: the banner under the header (now on Paper as well, with
 * a link to the live book), the row's exit-watch chip and the section after the open positions on Live, Mark seen, Set my stop /
 * Use the rule, the phone cards.
 * Dropped with the old layout: the "All" mode and the account select (the new view has a Paper / Live switch only), the risk
 * monitor the section sat above (EW-33), and "the banner is hidden on Paper" (the banner now shows on both, by design here).
 *
 * Every /api/* answer below is an inline MOCK — not real data — in the shape EXIT_WATCH.md gives for GET /api/desk/pnl/exits,
 * POST /api/desk/pnl/exits/seen and PUT / DELETE /api/positions/{underlying}/levels, plus a minimal GET /api/desk/pnl body.
 * Symbols, prices, levels and alerts are made up. Mocked APIs, production build.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
const PNL = "/v5/app/trader/desk?tab=trade&view=paper&sub=pnl";
const SLOW = { timeout: 15_000 };
const BANNED = /\bpick|recommend|suggest/i;
const SHOTS = process.env.PNL_SHOTS || "";

/** Only when PNL_SHOTS names a folder: the Exit watch section (and the banner) as drawn. */
async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  fs.mkdirSync(SHOTS, { recursive: true });
  await page.getByTestId("pnl-exits").scrollIntoViewIfNeeded();
  await page.getByTestId("pnl-exits").screenshot({ path: path.join(SHOTS, name) });
  const b = page.getByTestId("pnl-exit-banner");
  if (await b.count()) await b.screenshot({ path: path.join(SHOTS, name.replace(".png", "-banner.png")) });
}

// ── MOCK — not real data: a minimal P&L snapshot (one live row) ──────────────────────────────────────────────────────────
const LIVE_ROW = {
  position_id: "ic-1:TATASTEEL", trade_id: null, leg_index: null, strategy_id: null, strategy_name: null, mode: "LIVE", account: "ICICI Direct", account_id: "ic-1",
  instrument: "TATASTEEL", symbol: "TATASTEEL", underlying: "TATASTEEL", segment: "EQUITY", side: "LONG", net_quantity: 500, lots: null, lot_size: null, avg_price: 200.0,
  ltp: 172.4, prev_close: 179.65, price_status: "LIVE", price_source: "Kite live", price_at: "2026-11-05T10:42:00+05:30", price_age_seconds: 1, price_day: "2026-11-05",
  invested_value: 100000, unrealized_pnl: -13800, gross_pnl: -13800, charges_estimated: 210, net_pnl: -14010, day_pnl: -3625, return_pct: null,
  realized_pnl: null, stop_loss: null, target: null, distance_to_stop_pct: null, risk_used_pct: null, status: "ACTIVE", exposure_rs: 86200, broker_pnl: -13800,
  broker_read_at: "2026-11-05T10:41:30+05:30", product: "margin", expiry: null, opened_at: null, editable_levels: false, pending_levels: null,
  executions_note: "MOCK: today's fills only.", contract_problem: null, executions: [],
};
const ACCOUNTS = [
  { account_id: "paper", name: "Paper account", mode: "PAPER", broker: null, state: "OK", state_note: null, read_at: "2026-11-05T10:42:00+05:30", capital: 10000000, capital_basis: "MOCK", open_positions: 0, net_pnl: 0 },
  { account_id: "ic-1", name: "ICICI Direct", mode: "LIVE", broker: "icicidirect", state: "OK", state_note: null, read_at: "2026-11-05T10:41:30+05:30", capital: null, capital_basis: "MOCK", open_positions: 1, net_pnl: -14010 },
];
function snapshot(q: URLSearchParams) {
  const mode = q.get("mode") ?? "ALL";
  const account = q.get("account") ?? "ALL";
  const rows = mode === "PAPER" || account === "paper" ? [] : [clone(LIVE_ROW)];
  return {
    mode, currency: "INR", as_of: "2026-11-05T10:42:00+05:30", sequence: 1762319520000,
    filters: { segment: q.get("segment") ?? "ALL", period: "TODAY", from: "2026-11-05", to: "2026-11-05", mode, account },
    market: { session: "open", feed: "live", feed_age_seconds: 1, stale_after_seconds: 75, day: "2026-11-05", price_rule: "MOCK price rule", notes: [] },
    accounts: clone(ACCOUNTS),
    modes: {
      PAPER: { realized_pnl: 0, unrealized_pnl: 0, gross_pnl: 0, charges: 0, net_pnl: 0, capital: 10000000, return_pct: 0, open_positions: 0, complete: true, available: true, note: null },
      LIVE: { realized_pnl: null, unrealized_pnl: -13800, gross_pnl: -13800, charges: 210, net_pnl: -14010, capital: null, return_pct: null, open_positions: 1, complete: true, available: true, note: null },
    },
    summary: { realized_pnl: null, unrealized_pnl: rows.length ? -13800 : 0, gross_pnl: rows.length ? -13800 : 0, charges_booked: 0, charges_estimated: rows.length ? 210 : 0,
      net_pnl: rows.length ? -14010 : 0, day_pnl: null, allocated_capital: null, return_pct: null, open_positions: rows.length, open_legs: rows.length, winning_positions: 0,
      losing_positions: rows.length, closed_trades: 0, pending_entries: 0, unpriced_positions: 0, stale_positions: 0, complete: true, exposure_rs: rows.length ? 86200 : 0, capital_basis: "MOCK" },
    by_segment: [], positions: rows, strategies: [], pending_entries: [], closed: [], closed_total: 0, closed_partial: false, marks_error: null,
    risk: { capital: { starting: 10000000, cash: 10000000, blocked: 0, available: 10000000, utilisation_pct: 0, basis: "MOCK" }, open_risk_rs: 0, open_risk_limit_rs: 300000,
      strategies_capital_at_risk_rs: 0, near_stop_pct: 1, daily_loss_limit_rs: null, daily_loss_used_pct: null, alerts: [], margin: { used_pct: null, basis: "MOCK" }, exposure_rs: 86200 },
    analytics: null, reconciliation: { checked: 0, mismatches: [] }, notes: {},
  };
}

// ── MOCK — not real data: GET /api/desk/pnl/exits (EXIT_WATCH.md "API") ──────────────────────────────────────────────────
type Row = Record<string, unknown>;
const pos = (o: Row): Row => ({
  account_id: "ic-1", account: "ICICI Direct", kind: "shares", side: "long", legs: [], price_source: "kite_live", price_as_of: "2026-11-05T10:42:00+05:30",
  stop_day: "2026-11-04", stored: true, rule_stop: null, atr: null, atr_pct: null, why: null, loss_basis: "MOCK: (average − stop) × quantity, gross.",
  support: null, note: null, history: [], ...o,
});
const POSITIONS = [
  pos({ key: "ic-1|TATASTEEL|long", underlying: "TATASTEEL", label: "TATASTEEL shares", legs: [{ instrument: "TATASTEEL", type: "EQ", quantity: 500, avg: 200.0, expiry: null, strike: null }],
    price: 172.4, stop: 174.2, method: "atr_trail", rule_stop: 174.2, atr: 9.47, atr_pct: 5.27, distance_pct: -1.04, distance_atr: -0.19, status: "HIT",
    loss_at_stop: 12900, support: 174.2, own: { stop: null, target: 300, trail_pct: null },
    history: [{ day: "2026-11-03", stop: 170.1, candidate: 170.1, close: 176.72, atr: 9.3, moved: true, reason: "MOCK first stop" },
      { day: "2026-11-04", stop: 174.2, candidate: 174.2, close: 179.65, atr: 9.47, moved: true, reason: "MOCK trail" }] }),
  pos({ key: "ic-1|ITC|long", underlying: "ITC", label: "ITC shares", price: 349, stop: 344, method: "yours", rule_stop: 341.75, atr: 13.38, atr_pct: 3.63,
    distance_pct: 1.43, distance_atr: 0.37, status: "NEAR", loss_at_stop: 9000, support: 328.65, own: { stop: 344, target: null, trail_pct: null } }),
  pos({ key: "ic-1|BEL|long", underlying: "BEL", label: "BEL shares", price: 41.2, stop: 39.5, method: "atr_trail", rule_stop: 39.5, atr: 1.26, atr_pct: 3.1,
    distance_pct: 4.13, distance_atr: 1.35, status: "OK", loss_at_stop: -1040, support: 36.1 }),
  pos({ key: "ic-1|DLF|long", underlying: "DLF", label: "DLF future + 980 put", kind: "hedged", price: 975, stop: 980, method: "put_floor",
    legs: [{ instrument: "DLF26NOVFUT", type: "FUT", quantity: 300, avg: 1000.0, expiry: "2026-11-23", strike: null },
      { instrument: "DLF26NOV980PE", type: "PE", quantity: 300, avg: 20.0, expiry: "2026-11-23", strike: 980 }],
    rule_stop: 945.0, atr: 20.0, atr_pct: 2.05, distance_pct: -0.51, distance_atr: -0.25, status: "FLOOR", loss_at_stop: 12000,
    loss_basis: "MOCK: floor loss at expiry = (future average − strike + put average) × quantity." }),
  pos({ key: "ic-1|COALINDIA|long", underlying: "COALINDIA", label: "COALINDIA shares", price: 63.35, stop: null, method: "none", stop_day: null, stored: false,
    distance_pct: null, distance_atr: null, status: "NO_STOP", loss_at_stop: null, why: "MOCK: 12 sessions after a price series break; ATR needs 15." }),
];
const ALERTS = [
  { id: "a1", at: "2026-11-05T10:42:05+05:30", day: "2026-11-05", kind: "STOP_HIT", severity: "CRITICAL", key: "ic-1|TATASTEEL|long", underlying: "TATASTEEL", account: "ICICI Direct",
    text: "MOCK: TATASTEEL (ICICI Direct) is at ₹172.40, through its stop loss ₹174.20 (2 × ATR trail). Nothing has been sold: the broker is read-only here.",
    price: 172.4, level: 174.2, source: "kite_live", seen: false },
  { id: "a2", at: "2026-11-05T10:30:00+05:30", day: "2026-11-05", kind: "NEAR_STOP", severity: "WARNING", key: "ic-1|ITC|long", underlying: "ITC", account: "ICICI Direct",
    text: "MOCK: ITC is within 0.5 ATR of your stop loss ₹344.00.", price: 349, level: 344, source: "kite_live", seen: false },
  { id: "a3", at: "2026-11-04T19:20:00+05:30", day: "2026-11-04", kind: "STOP_RAISED", severity: "INFO", key: "ic-1|BEL|long", underlying: "BEL", account: "ICICI Direct",
    text: "MOCK: BEL's stop loss moved up to ₹39.50 on the 4 Nov close.", price: 41.2, level: 39.5, source: "eod", seen: true },
];
function exitsBody() {
  return {
    as_of: "2026-11-05T10:42:10+05:30", session: "open",
    rule: { id: "exit-atr-trail-v1", text: "MOCK rule: today's close minus 2 × ATR(14), moved up only, after NSE's end-of-day file." },
    watcher: { enabled: true, live_round_at: "2026-11-05T10:42:05+05:30", eod_day: "2026-11-04", feed_why: null },
    positions: clone(POSITIONS),
    not_watched: [{ label: "SGBX01 (ICICI Direct)", why: "MOCK: no NSE symbol for this broker code" }],
    alerts: clone(ALERTS), unseen: 2,
    accounts: [{ account_id: "ic-1", name: "ICICI Direct", state: "OK" }],
  };
}

interface Seen { exitQueries: URLSearchParams[]; seenBodies: unknown[]; levels: Array<{ method: string; path: string; body: unknown }> }
interface Opts { phone?: boolean; exits?: { status: number; body: unknown } }

async function setup(page: Page, o: Opts = {}): Promise<Seen> {
  const seen: Seen = { exitQueries: [], seenBodies: [], levels: [] };
  let body = exitsBody();
  if (o.phone) await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/api/**", (r) => json(r, { detail: "MOCK: not mocked in this spec" }, 404));
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (r) => json(r, []));
  await page.route("**/api/move-odds/**", (r) => json(r, { detail: "feature_not_enabled" }, 403));
  await page.route("**/api/risk/status", (r) => json(r, { kill_switch: false, halted: false, policy_version: "MOCK" }));
  await page.route("**/api/live/**", (r) => json(r, { available: false, reason: "MOCK: feed off", quotes: {}, mode: "expired", session: "closed", stale: true }));
  await page.route("**/api/desk/alerts*", (r) => json(r, { as_of: "2026-11-04", alerts: [] }));
  await page.route("**/api/desk/paper-trades*", (r) => json(r, { as_of: "2026-11-04", checked_through: "2026-11-04", trades: [], summary: { open: 0, closed: 0 }, status: "all" }));
  await page.route(/\/api\/desk\/pnl(\?|$)/, (r) => json(r, snapshot(new URL(r.request().url()).searchParams)));
  await page.route(/\/api\/desk\/pnl\/stream(\?|$)/, (r) => json(r, { detail: "MOCK: stream unavailable" }, 503));
  await page.route(/\/api\/desk\/pnl\/timeseries(\?|$)/, (r) => json(r, { date: "2026-11-05", interval: "5m", points: [], missing: [], basis: "MOCK", partial: false }));
  await page.route(/\/api\/desk\/pnl\/exits(\?|$)/, (r) => {
    seen.exitQueries.push(new URL(r.request().url()).searchParams);
    if (o.exits) return json(r, o.exits.body, o.exits.status);
    return json(r, body);
  });
  await page.route(/\/api\/desk\/pnl\/exits\/seen$/, (r) => {
    const b = r.request().postDataJSON();
    seen.seenBodies.push(b);
    const ids: string[] | null = Array.isArray(b?.ids) ? b.ids : null;
    let marked = 0;
    body = { ...body, alerts: body.alerts.map((a) => { if (!a.seen && (!ids || ids.includes(a.id))) { marked += 1; return { ...a, seen: true }; } return a; }) };
    body.unseen = body.alerts.filter((a) => !a.seen).length;
    return json(r, { marked });
  });
  await page.route(/\/api\/positions\/[^/]+\/levels$/, (r) => {
    const req = r.request();
    const path = new URL(req.url()).pathname;
    seen.levels.push({ method: req.method(), path, body: req.method() === "PUT" ? req.postDataJSON() : null });
    const und = decodeURIComponent(path.split("/")[3]);
    if (req.method() === "PUT") return json(r, { underlying: und, stop: req.postDataJSON().stop, target: null, trail_pct: null, updated_at: "2026-11-05T10:43:00+00:00", set_by: "you" });
    return json(r, { underlying: und, deleted: true });
  });
  return seen;
}

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

const exitRow = (page: Page, key: string) => page.locator(`[data-testid="pnl-exit-row"][data-key="${key}"]`);
const top = (page: Page, id: string) => page.evaluate((t) => (document.querySelector(`[data-testid="${t}"]`) as HTMLElement).getBoundingClientRect().top, id);

const toLive = async (page: Page) => {
  await page.getByTestId("pv2-pnl-mode-live").click();
  await expect(page.getByTestId("pv2-pnl")).toHaveAttribute("data-mode", "LIVE", SLOW);
};

test.describe("MOCK — not real data: Real-time P&L › Exit watch", () => {
  test("EW-33 the banner shows on Paper and Live; on Live the row chip and the section, after the open positions and before Closed trades", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(PNL);
    await expect(page.getByTestId("pnl-exit-banner")).toBeVisible(SLOW);
    expect(seen.exitQueries[0].get("account")).toBe("ALL");
    await expect(page.getByTestId("pv2-pnl-kpis")).toBeVisible(SLOW);
    expect(await top(page, "pv2-pnl-head")).toBeLessThan(await top(page, "pnl-exit-banner"));
    expect(await top(page, "pnl-exit-banner")).toBeLessThan(await top(page, "pv2-pnl-kpis"));
    await expect(page.getByTestId("pnl-exits")).toHaveCount(0);

    await page.getByTestId("pv2-pnl-exit-golive").click();
    await expect(page.getByTestId("pv2-pnl")).toHaveAttribute("data-mode", "LIVE", SLOW);
    const section = page.getByTestId("pnl-exits");
    await expect(section).toBeVisible(SLOW);
    expect(await top(page, "pnl-positions")).toBeLessThan(await top(page, "pnl-exits"));
    expect(await top(page, "pnl-exits")).toBeLessThan(await top(page, "pnl-closed"));
    const chip = page.locator('[data-testid="pnl-row"][data-id="ic-1:TATASTEEL"]').getByTestId("pv2-pnl-row-exit");
    await expect(chip).toHaveText("Exit watch · Stop hit · 174.20");
    await expect(chip).toHaveAttribute("data-status", "HIT");

    await page.getByTestId("pv2-pnl-mode-paper").click();
    await expect(page.getByTestId("pv2-pnl")).toHaveAttribute("data-mode", "PAPER", SLOW);
    await expect(page.getByTestId("pnl-exits")).toHaveCount(0);
    await expect(page.getByTestId("pnl-exit-banner")).toBeVisible();
  });

  test("EW-34 rows: status and method chips in words, distance, loss at the stop, latest signal; not watched; the watcher line", async ({ page }) => {
    await setup(page);
    await page.goto(PNL);
    await toLive(page);
    await expect(page.getByTestId("pnl-exit-row")).toHaveCount(5, SLOW);
    await expect(page.getByTestId("pnl-exit-count")).toHaveText("5 watched");
    const expectRow = async (key: string, status: string, method: string, stop: string) => {
      const r = exitRow(page, key);
      await expect(r.getByTestId("pnl-exit-status")).toHaveText(status);
      await expect(r.getByTestId("pnl-exit-method")).toHaveText(method);
      await expect(r.getByTestId("pnl-exit-stop")).toContainText(stop);
    };
    await expectRow("ic-1|TATASTEEL|long", "Hit", "2 × ATR trail", "174.20");
    await expectRow("ic-1|ITC|long", "Near", "Yours", "344.00");
    await expectRow("ic-1|BEL|long", "OK", "2 × ATR trail", "39.50");
    await expectRow("ic-1|DLF|long", "At floor", "Put floor", "980.00");
    await expectRow("ic-1|COALINDIA|long", "No stop", "No stop", "—");
    const sw = exitRow(page, "ic-1|TATASTEEL|long");
    await expect(sw.getByTestId("pnl-exit-loss")).toHaveText("−₹12,900");
    await expect(sw.getByTestId("pnl-exit-distance")).toHaveText("−1.04% · −0.19 ATR");
    await expect(sw.getByTestId("pnl-exit-signal")).toContainText("Stop loss hit");
    await expect(sw.getByTestId("pnl-exit-source")).toContainText("Kite live");
    await expect(sw.getByTestId("pnl-exit-kind")).toHaveText("Shares");
    await expect(exitRow(page, "ic-1|DLF|long").getByTestId("pnl-exit-kind")).toHaveText("Hedged");
    await expect(exitRow(page, "ic-1|BEL|long").getByTestId("pnl-exit-loss")).toHaveText("locks in ₹1,040");
    await expect(exitRow(page, "ic-1|COALINDIA|long").getByTestId("pnl-exit-signal")).toHaveText("—");
    await expect(page.getByTestId("pnl-exit-notwatched-row")).toHaveText("SGBX01 (ICICI Direct) — MOCK: no NSE symbol for this broker code");
    await expect(page.getByTestId("pnl-exit-alert")).toHaveCount(3);
    await expect(page.locator('[data-testid="pnl-exit-alert"][data-seen="false"]')).toHaveCount(2);
    await expect(page.locator('[data-testid="pnl-exit-alert"][data-id="a1"]')).toContainText("Stop loss hit · TATASTEEL · ICICI Direct");
    await expect(page.getByTestId("pnl-exit-watcher")).toContainText("Checked live every 30 s in market hours · stops move after NSE's end-of-day file · in-app only · nothing is sent to your broker");
    await expect(page.getByTestId("pnl-exit-watcher-state")).toContainText("Stops last moved on the 2026-11-04 close.");
    // Detail: history, rule, the reason a stop is missing.
    await sw.click();
    const det = page.locator('[data-testid="pnl-exit-detail"][data-key="ic-1|TATASTEEL|long"]');
    await expect(det).toBeVisible();
    await expect(det.getByTestId("pnl-exit-history-row")).toHaveCount(2);
    await expect(det.getByTestId("pnl-exit-history-row").first()).toContainText("2026-11-04");
    await expect(det.getByTestId("pnl-exit-rule")).toContainText("MOCK rule");
    await expect(det.getByTestId("pnl-exit-userule")).toHaveCount(0);
    await exitRow(page, "ic-1|COALINDIA|long").click();
    const inox = page.locator('[data-testid="pnl-exit-detail"][data-key="ic-1|COALINDIA|long"]');
    await expect(inox).toContainText("MOCK: 12 sessions after a price series break; ATR needs 15.");
    await expect(inox.getByTestId("pnl-exit-unstored")).toBeVisible();
    expect(await page.getByTestId("pnl-exits").innerText()).not.toMatch(BANNED);
    await shot(page, "exits-1280.png");
  });

  test("EW-35 the banner names the newest unseen alert; Mark seen POSTs {} and the banner goes", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(PNL);
    const banner = page.getByTestId("pnl-exit-banner");
    await expect(banner).toBeVisible(SLOW);
    await expect(banner).toHaveAttribute("data-severity", "CRITICAL");
    await expect(banner).toHaveAttribute("role", "alert");
    await expect(page.getByTestId("pnl-exit-banner-count")).toHaveText("2 new exit alerts");
    await expect(page.getByTestId("pnl-exit-banner-text")).toContainText("Stop loss hit: MOCK: TATASTEEL (ICICI Direct) is at ₹172.40");
    await page.getByTestId("pnl-exit-seen").click();
    await expect.poll(() => seen.seenBodies.length, SLOW).toBe(1);
    expect(seen.seenBodies[0]).toEqual({});
    await expect(banner).toHaveCount(0, SLOW);
    await toLive(page);
    await expect(page.getByTestId("pnl-exit-alert")).toHaveCount(3, SLOW);
    await expect(page.locator('[data-testid="pnl-exit-alert"][data-seen="false"]')).toHaveCount(0);
    await expect(page.getByTestId("pnl-exit-seen-all")).toHaveCount(0);
  });

  test("EW-36 Set my stop PUTs {stop} for the underlying; a bad price is refused on screen; Use the rule DELETEs your own stop", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(PNL);
    await toLive(page);
    await exitRow(page, "ic-1|TATASTEEL|long").click(SLOW);
    const det = page.locator('[data-testid="pnl-exit-detail"][data-key="ic-1|TATASTEEL|long"]');
    await det.getByTestId("pnl-exit-setstop-input").fill("0");
    await det.getByTestId("pnl-exit-setstop-save").click();
    await expect(det.getByTestId("pnl-exit-setstop-msg")).toHaveText("Enter a price above zero.");
    expect(seen.levels).toHaveLength(0);
    await det.getByTestId("pnl-exit-setstop-input").fill("170");
    await det.getByTestId("pnl-exit-setstop-save").click();
    await expect(det.getByTestId("pnl-exit-setstop-msg")).toContainText("Saved: your stop loss 170.00 now replaces the rule for TATASTEEL in every account.", SLOW);
    // the PUT replaces the whole document: the target the user already has (MOCK 300) is sent back unchanged
    expect(seen.levels).toEqual([{ method: "PUT", path: "/api/positions/TATASTEEL/levels", body: { stop: 170, target: 300, trail_pct: null } }]);

    await exitRow(page, "ic-1|ITC|long").click();
    const ex = page.locator('[data-testid="pnl-exit-detail"][data-key="ic-1|ITC|long"]');
    await ex.getByTestId("pnl-exit-userule").click();
    await expect(ex.getByTestId("pnl-exit-setstop-msg")).toContainText("Your own stop loss for ITC is cleared: the rule applies again.", SLOW);
    expect(seen.levels[1]).toEqual({ method: "DELETE", path: "/api/positions/ITC/levels", body: null });
  });

  test("EW-36b Use the rule keeps a target the user set: the document is rewritten with only the target, not deleted", async ({ page }) => {
    const body = exitsBody();
    const ex = body.positions.find((p) => p.key === "ic-1|ITC|long") as Row;
    ex.own = { stop: 344, target: 420, trail_pct: 2 };                                  // MOCK — not real data
    const seen = await setup(page, { exits: { status: 200, body } });
    await page.goto(PNL);
    await toLive(page);
    await exitRow(page, "ic-1|ITC|long").click(SLOW);
    const det = page.locator('[data-testid="pnl-exit-detail"][data-key="ic-1|ITC|long"]');
    await det.getByTestId("pnl-exit-userule").click();
    await expect(det.getByTestId("pnl-exit-setstop-msg")).toContainText("Your own stop loss for ITC is cleared: the rule applies again.", SLOW);
    expect(seen.levels).toEqual([{ method: "PUT", path: "/api/positions/ITC/levels", body: { stop: null, target: 420, trail_pct: null } }]);
  });

  test("EW-37 390 px: cards that open to the same detail, no page-level sideways scroll", async ({ page }) => {
    await setup(page, { phone: true });
    await page.goto(PNL);
    await expect(page.getByTestId("pv2-pnl")).toHaveAttribute("data-narrow", "true", SLOW);
    await toLive(page);
    await expect(page.getByTestId("pnl-exit-card")).toHaveCount(5, SLOW);
    await expect(page.getByTestId("pnl-exit-table")).toHaveCount(0);
    const c = page.locator('[data-testid="pnl-exit-card"][data-key="ic-1|DLF|long"]');
    await expect(c.getByTestId("pnl-exit-status")).toHaveText("At floor");
    await c.getByTestId("pnl-exit-expand").click();
    await expect(c.getByTestId("pnl-exit-detail")).toBeVisible();
    await expect(c.getByTestId("pnl-exit-legs")).toContainText("DLF26NOV980PE");
    await expect(page.getByTestId("pnl-exit-banner")).toBeVisible();
    await noSideScroll(page);
    await shot(page, "exits-390.png");
  });

  test("EW-33b the route missing (404) leaves the section out; a server error shows a problem with Retry inside it", async ({ page }) => {
    await setup(page, { exits: { status: 404, body: { detail: "Not Found" } } });
    await page.goto(PNL);
    await toLive(page);
    await expect(page.getByTestId("pnl-positions")).toBeVisible(SLOW);
    await expect(page.getByTestId("pnl-closed")).toBeVisible();
    await expect(page.getByTestId("pnl-exits")).toHaveCount(0);
    await expect(page.getByTestId("pnl-exit-banner")).toHaveCount(0);

    await page.unrouteAll({ behavior: "ignoreErrors" });
    await setup(page, { exits: { status: 500, body: { detail: "MOCK: boom" } } });
    await page.goto(PNL);
    await toLive(page);
    const section = page.getByTestId("pnl-exits");
    await expect(section).toBeVisible(SLOW);
    await expect(section.getByRole("button", { name: /retry/i })).toBeVisible(SLOW);
  });
});
