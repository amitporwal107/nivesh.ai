/**
 * One-screen Copilot app (/v5/app) — F&O lab (/app/tool/fnolab), the six governance screens: 05 Strategy Programs,
 * 06 Replay Lab, 08 Shadow Mode, 09 Live Desk, 11 Certification, 12 Audit (screens/fnolab/*.tsx, governance-data.ts).
 *
 * MOCK — not real data. The template catalog mirrors backend/services/strategy_plan/templates.py CATALOG; the chain is
 * the synthetic copilot-options-chain.json fixture (NIFTY, data day 12 Oct 2026, expiry 27 Oct, lot 65); the payoff,
 * forward-test and risk answers are written by hand in the routes' shapes, with INVENTED ids, symbols and numbers.
 * Expected text is worked out here from the payloads. Production build, every /api mocked — see pw.copilot-app.config.ts.
 *
 * Cases (test_reports/fno_lab_screens_TESTCASES.md): P-1..P-3 · R-1 · SH-1 · L-1, L-2 · C-1 · A-1..A-5 · S-3, S-5 for
 * these screens.
 */
import fs from "node:fs";
import path from "node:path";
import { test, expect, type Page } from "@playwright/test";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const LAB = "/v5/app/tool/fnolab";
const FX = path.join(process.cwd(), "e2e", "fixtures");
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(FX, name), "utf-8"));
const json = (page: Page, pattern: string | RegExp, body: unknown, status = 200) =>
  page.route(pattern, (route) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) }));

// ── MOCK payloads ────────────────────────────────────────────────────────

const leg = (side: string, option_type: string | null, strike_param: string | null) => ({ side, option_type, strike_param });
const TEMPLATES = {
  count: 8, status: "template", calculation_version: "payoff-v1", read_only: true,
  templates: [
    { name: "long_call", label: "Long call", kind: "option", legs: [leg("buy", "call", "strike")], params: ["strike", "lots"], calculation_version: "payoff-v1" },
    { name: "long_put", label: "Long put", kind: "option", legs: [leg("buy", "put", "strike")], params: ["strike", "lots"], calculation_version: "payoff-v1" },
    { name: "bull_call_spread", label: "Bull call spread", kind: "option", legs: [leg("buy", "call", "long_strike"), leg("sell", "call", "short_strike")], params: ["long_strike", "short_strike", "lots"], calculation_version: "payoff-v1" },
    { name: "bear_put_spread", label: "Bear put spread", kind: "option", legs: [leg("buy", "put", "long_strike"), leg("sell", "put", "short_strike")], params: ["long_strike", "short_strike", "lots"], calculation_version: "payoff-v1" },
    { name: "iron_condor", label: "Iron condor", kind: "option", legs: [leg("buy", "put", "long_put_strike"), leg("sell", "put", "short_put_strike"), leg("sell", "call", "short_call_strike"), leg("buy", "call", "long_call_strike")], params: ["long_put_strike", "short_put_strike", "short_call_strike", "long_call_strike", "lots"], calculation_version: "payoff-v1" },
    { name: "long_future", label: "Long future", kind: "future", legs: [leg("buy", null, null)], params: ["entry_price", "lots"], calculation_version: "payoff-v1" },
    { name: "short_future", label: "Short future", kind: "future", legs: [leg("sell", null, null)], params: ["entry_price", "lots"], calculation_version: "payoff-v1" },
    { name: "cash_long", label: "Cash long", kind: "cash", legs: [leg("buy", null, null)], params: ["shares", "entry_price"], calculation_version: "payoff-v1" },
  ],
};

/** The fixture chain's closes for the bear put spread the dry run builds: buy the ATM 25000 PE, sell two steps down (24800 PE). */
const CHAIN = load("copilot-options-chain.json");
const putClose = (k: number) => CHAIN.strikes.find((s: { strike: number }) => s.strike === k).put.close as number;
const LONG_PE = 25000;
const SHORT_PE = 24800;

/** POST /api/desk/strategy/payoff answer (invented numbers in the route's shape). */
const PAYOFF = {
  valid: true, problems: [], warnings: [], calculation_version: "payoff-v1", underlying: "NIFTY", reference_price: 25010, as_of: "2026-10-12",
  expiry: { grid: [24000, 25000, 26000], gross: [8996, -4004, -4004], net: [8900, -4100, -4100], per_leg: [], breakevens: [24938.4],
    max_profit: 8996, max_loss: -4004, profit_unbounded: false, loss_unbounded: false, net_premium: -4004, scenarios: [] },
  pre_expiry: null, costs: null, margin: null, margin_reason: "not estimated", capital_at_risk: 4196, caveats: ["Nothing is sent to a broker."], sent_to_broker: false,
};

const FORWARD = {
  version: "fno-forward-v1", hypothesis: "A stock whose near-month future shows price down and open interest up underperforms over the next 5 sessions.",
  horizon_sessions: 5, cost_pct: 0.15, min_sessions: 30, settings_recorded: ["production_floors", "no_threshold"], read_only: true,
  past_result: "Inconclusive in the one-year study; not validated.", not_recorded: "Five frozen settings are not recorded.",
  started: true, recorded_sessions: 9, last_recorded: "2026-10-23", prices_available: true,
  settings: {
    production_floors: { recorded_sessions: 9, signals_recorded: 41, judged_sessions: 4, judged_signals: 17, open_sessions: 5, sessions_needed: 26, mean_pct: null, t: null },
    no_threshold: { recorded_sessions: 9, signals_recorded: 63, judged_sessions: 4, judged_signals: 28, open_sessions: 5, sessions_needed: 26, mean_pct: null, t: null },
  },
};

const status = (o: Record<string, unknown> = {}) => ({
  user_id: "u_fixture", kill_switch: false, halted: false, reason: null, set_by: null, set_at: null, policy_version: "risk-controls-v1",
  can_reset: false, live_authorization: { granted: false, granted_by: null, granted_at: null, reason: null },
  modes: ["paper", "shadow", "assisted", "live"], live_execution_available: false, gate: { enabled: true, policy_version: "fno-risk-v1" }, ...o,
});

/** GET /api/risk/decisions, sent OLDEST first so the newest-first order is checked. */
const DECISIONS = {
  count: 3, append_only: true, policy_version: "risk-controls-v1",
  decisions: [
    { event_id: "dec-old-0001", at: "2026-10-23T05:00:00+00:00", action: "journal_trade", outcome: "denied", symbol: "FIXOLD", reasons: ["kill switch on"], correlation_id: null },
    { event_id: "dec-blk-0002", at: "2026-10-24T05:10:00+00:00", action: "desk_paper_trade", outcome: "blocked", path: "desk_paper_trade", mode: "paper", symbol: "FIXBLK",
      reasons: [{ code: "lot_size_mismatch", message: "Lot 50 is not the exchange lot 65.", check: "lot_size" }], correlation_id: "corr-aaaa-1111-blk",
      policy_version: "fno-risk-v1", inputs_hash: "sha256:fixturehash0002", checks: [{ check: "lot_size", status: "fail", detail: null }, { check: "mode", status: "pass", detail: null }],
      detail: { instrument: "option", action: "open", legs: 2, capital_at_risk_rs: null }, source: "risk_gate", actor_id: "u_fixture" },
    { event_id: "dec-ok-0003", at: "2026-10-24T06:00:00+00:00", action: "desk_paper_trade", outcome: "allowed", path: "desk_paper_trade", mode: "paper", symbol: "FIXOK",
      reasons: [], correlation_id: "corr-bbbb-2222-ok", policy_version: "fno-risk-v1", inputs_hash: "sha256:fixturehash0003",
      checks: [{ check: "lot_size", status: "pass", detail: null }], detail: { instrument: "option", action: "open", legs: 2, capital_at_risk_rs: 13000 }, source: "risk_gate", actor_id: "u_fixture" },
  ],
};
const AUDIT = { append_only: true, policy_version: "risk-controls-v1", count: 1, events: [
  { _id: "a-1", at: "2026-10-24T04:30:00+00:00", actor: "admin_fixture", action: "set_kill_switch", field: "kill_switch", before: true, after: false, reason: "Reviewed and cleared", policy_version: "risk-controls-v1" },
] };

async function base(page: Page, o: { status?: unknown; forward?: { status: number; body: unknown }; templates?: { status: number; body: unknown } } = {}) {
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await json(page, "**/api/desk/strategy/templates", o.templates?.body ?? TEMPLATES, o.templates?.status ?? 200);
  await json(page, "**/api/fno/NIFTY/expiries", load("copilot-options-expiries.json"));
  await json(page, "**/api/fno/NIFTY/chain*", CHAIN);
  await json(page, "**/api/fno/forward-test", o.forward?.body ?? FORWARD, o.forward?.status ?? 200);
  await json(page, "**/api/risk/status", o.status ?? status());
  await json(page, "**/api/risk/decisions*", DECISIONS);
  await json(page, "**/api/risk/audit*", AUDIT);
}

function recordWrites(page: Page): string[] {
  const writes: string[] = [];
  page.on("request", (req) => {
    const p = new URL(req.url()).pathname;
    if (req.method() !== "GET" && /\/api\//.test(p) && !p.startsWith("/api/copilot/widgets/")) writes.push(`${req.method()} ${p}`);
  });
  return writes;
}

async function noSideScroll(page: Page) {
  const o = await page.evaluate(() => {
    const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
    return { doc: document.documentElement.scrollWidth - window.innerWidth, scroll: sc ? sc.scrollWidth - sc.clientWidth : 0 };
  });
  expect(o.doc).toBeLessThanOrEqual(1);
  expect(o.scroll).toBeLessThanOrEqual(1);
}

test.describe("MOCK — not real data: F&O lab · governance screens", () => {
  test("P-1 Programs: the library comes from the templates route, each marked a template and not a certified program", async ({ page }) => {
    await base(page);
    await page.goto(`${LAB}?screen=prog`);
    await expect(page.getByTestId("fnolab-mode")).toHaveAttribute("data-mode", "governance");
    const rows = page.getByTestId("fnolab-prog-template");
    await expect(rows).toHaveCount(8);
    await expect(rows.first()).toContainText("Long call");
    for (const t of TEMPLATES.templates) {
      const row = page.locator(`[data-testid="fnolab-prog-template"][data-name="${t.name}"]`);
      await expect(row).toContainText(t.label);
      await expect(row).toContainText("Template · not a certified program");
      await expect(row).toContainText(t.params.join(", "));
    }
    // Only option templates offer a dry run.
    await expect(page.getByTestId("fnolab-prog-pick-long_future")).toHaveCount(0);
    const sources = page.getByTestId("fnolab-source");
    await expect(sources.filter({ hasText: "Program compiler" })).toContainText("Not built · P3.2");
    await expect(sources.filter({ hasText: "Payoff engine" })).toContainText("payoff-v1");
  });

  test("P-2 Programs: the dry run builds the bear put spread from the chain closes, prices it and sends nothing", async ({ page }) => {
    await base(page);
    const writes = recordWrites(page);
    let sent: Record<string, unknown> | null = null;
    await page.route("**/api/desk/strategy/payoff", async (route) => {
      sent = route.request().postDataJSON();
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(PAYOFF) });
    });
    await page.goto(`${LAB}?screen=prog`);
    await expect(page.getByText("Dry run · Bear put spread")).toBeVisible();
    await page.getByTestId("fnolab-prog-run").click();
    await expect(page.getByTestId("fnolab-prog-children")).toBeVisible();
    expect(sent).toMatchObject({
      underlying: "NIFTY", reference_price: 25010, as_of: "2026-10-12",
      legs: [
        { kind: "option", side: "buy", option_type: "put", strike: LONG_PE, entry_price: putClose(LONG_PE), lot_size: 65, quantity: 1, expiry: "2026-10-27" },
        { kind: "option", side: "sell", option_type: "put", strike: SHORT_PE, entry_price: putClose(SHORT_PE), lot_size: 65, quantity: 1, expiry: "2026-10-27" },
      ],
    });
    const children = page.getByTestId("fnolab-prog-children");
    await expect(children).toContainText("Child orders it would produce · nothing sent");
    await expect(children).toContainText(`L1 BUY NIFTY 2026-10-27 ${LONG_PE} PE qty 65 · price ${putClose(LONG_PE).toFixed(2)} (close)`);
    await expect(children).toContainText(`L2 SELL NIFTY 2026-10-27 ${SHORT_PE} PE qty 65 · price ${putClose(SHORT_PE).toFixed(2)} (close)`);
    await expect(page.getByTestId("fnolab-prog-not-sent")).toContainText("nothing was sent to a broker");
    await expect(page.getByTestId("fnolab-prog-dryrun")).toContainText("−₹4,004");   // net premium and max loss
    await expect(page.getByTestId("fnolab-prog-dryrun")).toContainText("₹8,996");    // max profit
    await expect(page.getByTestId("fnolab-prog-dryrun")).toContainText("24,938.40"); // breakeven
    const checks = page.getByTestId("fnolab-prog-check");
    await expect(checks.filter({ hasText: "Risk pre-check" })).toContainText("No dry-run risk check exists");
    await expect(checks.filter({ hasText: "Executor route" })).toHaveAttribute("data-kind", "fail");
    expect(writes).toEqual(["POST /api/desk/strategy/payoff"]);
  });

  test("P-3 Programs: a template the chain cannot build says why and cannot run; the gaps are named", async ({ page }) => {
    await base(page);
    await page.goto(`${LAB}?screen=prog`);
    await page.getByTestId("fnolab-prog-pick-iron_condor").click();
    // The fixture chain has 3 strikes either side of the money; the condor's wings are 4 steps out.
    await expect(page.getByTestId("fnolab-prog-build-problem")).toContainText("no strike -4 steps from the money");
    await expect(page.getByTestId("fnolab-prog-run")).toBeDisabled();
    await expect(page.getByTestId("fnolab-prog-gap-exec")).toHaveAttribute("data-tag", "P3.2");
    await expect(page.getByTestId("fnolab-prog-gap-cert")).toHaveAttribute("data-tag", "P3.1");
  });

  test("P-1b Programs: a failed library read is said, not shown as an empty library", async ({ page }) => {
    await base(page, { templates: { status: 500, body: { detail: "boom" } } });
    await page.goto(`${LAB}?screen=prog`);
    await expect(page.getByText("The template library didn’t load")).toBeVisible();
    await expect(page.getByTestId("fnolab-prog-template")).toHaveCount(0);
  });

  test("R-1 Replay: not built (P2.1); the futures-signal research is described with no metric", async ({ page }) => {
    await base(page);
    await page.goto(`${LAB}?screen=replay`);
    await expect(page.getByTestId("fnolab-mode")).toHaveAttribute("data-mode", "research");
    await expect(page.getByTestId("fnolab-replay-gap")).toHaveAttribute("data-tag", "P2.1");
    const today = page.getByTestId("fnolab-replay-today");
    await expect(today).toContainText("services/fno_backtest");
    await expect(today).toContainText("Stage B2 supported none of its hypotheses");
    await expect(today).toContainText("None of this is an options replay");
    await expect(page.getByTestId("fnolab-screen-replay")).not.toContainText("Sharpe");
  });

  test("SH-1 Shadow: not built (P2.2); the forward test is labelled a forward test of a futures signal", async ({ page }) => {
    await base(page);
    await page.goto(`${LAB}?screen=shadow`);
    await expect(page.getByTestId("fnolab-mode")).toHaveAttribute("data-mode", "shadow");
    await expect(page.getByTestId("fnolab-shadow-gap")).toHaveAttribute("data-tag", "P2.2");
    await expect(page.getByText("Forward test of a futures signal — not shadow mode")).toBeVisible();
    const fwd = page.getByTestId("fnolab-shadow-forward");
    await expect(fwd).toHaveAttribute("data-started", "true");
    const table = page.getByTestId("fnolab-shadow-settings");
    await expect(table.locator("tbody tr")).toHaveCount(2);
    await expect(table.locator("tbody tr").filter({ hasText: "production_floors" })).toContainText("41");
    await expect(table.locator("tbody tr").filter({ hasText: "no_threshold" })).toContainText("63");
    await expect(page.getByTestId("fnolab-source").filter({ hasText: "Forward test" })).toContainText("9 sessions");
  });

  test("SH-1b Shadow: a failed forward-test read stays in its card and does not hide the gap", async ({ page }) => {
    await base(page, { forward: { status: 502, body: { detail: "unavailable" } } });
    await page.goto(`${LAB}?screen=shadow`);
    await expect(page.getByTestId("fnolab-shadow-gap")).toBeVisible();
    await expect(page.getByText("The forward test didn’t load")).toBeVisible();
    await expect(page.getByTestId("fnolab-source").filter({ hasText: "Forward test" })).toContainText("Did not load");
  });

  test("L-1 L-2 Live: twelve conditions, none enforceable; live state rows read the risk status; no order path", async ({ page }) => {
    await base(page);
    await page.goto(`${LAB}?screen=live`);
    await expect(page.getByTestId("fnolab-mode")).toHaveAttribute("data-mode", "live-disabled");
    const rowsL = page.getByTestId("fnolab-live-row");
    await expect(rowsL).toHaveCount(12);
    await expect(page.getByTestId("fnolab-screen-live")).toContainText("0 of 12 enforceable");
    await expect(page.getByTestId("fnolab-live-headline")).toHaveAttribute("data-live", "false");
    await expect(page.getByTestId("fnolab-live-headline")).toContainText("Live orders are off");
    await expect(rowsL.nth(4)).toContainText("fno-risk-v1 gate exists (on for your account)");
    await expect(rowsL.nth(8)).toContainText("(not granted)");
    await expect(rowsL.nth(10)).toContainText("Kill switch off");
    await expect(rowsL.nth(11)).toHaveAttribute("data-tag", "P0.3");
    await expect(page.getByRole("button", { name: /authori[sz]e/i })).toHaveCount(0);
  });

  test("L-1b Live: a kill switch that is on and a gate that is off read as such", async ({ page }) => {
    await base(page, { status: status({ kill_switch: true, gate: { enabled: false, policy_version: "fno-risk-v1" } }) });
    await page.goto(`${LAB}?screen=live`);
    const rowsL = page.getByTestId("fnolab-live-row");
    await expect(rowsL.nth(10)).toContainText("Kill switch ON");
    await expect(rowsL.nth(4)).toContainText("(off for your account)");
    await expect(page.getByTestId("fnolab-source").filter({ hasText: "Kill switch" })).toHaveAttribute("data-tone", "danger");
  });

  test("C-1 Certification: no records, the seven-status ladder, and the data-lake note", async ({ page }) => {
    await base(page);
    await page.goto(`${LAB}?screen=cert`);
    await expect(page.getByTestId("fnolab-mode")).toHaveAttribute("data-mode", "governance");
    await expect(page.getByTestId("fnolab-cert-empty")).toContainText("No agent, strategy or broker context is certified yet.");
    const ladder = page.getByTestId("fnolab-cert-status");
    await expect(ladder).toHaveCount(7);
    for (const [i, k] of ["NOT_CERTIFIED", "RESEARCH_CERTIFIED", "PAPER_CERTIFIED", "SHADOW_CERTIFIED", "RESTRICTED_LIVE_CERTIFIED", "SUSPENDED", "RETIRED"].entries()) {
      await expect(ladder.nth(i)).toContainText(k);
    }
    await expect(page.getByTestId("fnolab-cert-datalake")).toContainText("certifies data-lake dates only");
    await expect(page.getByTestId("fnolab-cert-gap")).toHaveAttribute("data-tag", "P3.1");
  });

  test("A-1 A-2 A-4 A-5 Audit: decisions newest first; the lineage marks only the recorded steps; control changes; no replay", async ({ page }) => {
    await base(page);
    await page.goto(`${LAB}?screen=audit`);
    const list = page.getByTestId("fnolab-audit-decision");
    await expect(list).toHaveCount(3);
    await expect(list.nth(0)).toHaveAttribute("data-id", "dec-ok-0003");
    await expect(list.nth(1)).toHaveAttribute("data-id", "dec-blk-0002");
    await expect(list.nth(2)).toHaveAttribute("data-id", "dec-old-0001");
    await expect(list.nth(2)).toContainText("no correlation id");

    await list.nth(1).click();
    const nodes = page.getByTestId("fnolab-audit-node");
    await expect(nodes).toHaveCount(10);
    await expect(page.locator('[data-testid="fnolab-audit-node"][data-recorded="true"]')).toHaveCount(2);
    await expect(page.locator('[data-testid="fnolab-audit-node"][data-node="snapshot"]')).toContainText("Not recorded · P0.3");
    const risk = page.getByTestId("fnolab-audit-risk");
    await expect(risk).toContainText("blocked");
    await expect(risk).toContainText("Lot 50 is not the exchange lot 65. (lot_size_mismatch)");
    await expect(risk).toContainText("sha256:fixturehash0002");
    await expect(risk).toContainText("corr-aaaa-1111-blk");
    await expect(risk).toContainText("fno-risk-v1");

    await page.locator('[data-testid="fnolab-audit-node"][data-node="snapshot"]').click();
    await expect(page.getByTestId("fnolab-audit-gap")).toContainText("Not recorded today (P0.3)");
    await expect(page.getByTestId("fnolab-audit-replay")).toContainText("Replay needs the snapshot store (P0.3)");
    await expect(page.getByRole("button", { name: /replay/i })).toHaveCount(0);

    const controls = page.getByTestId("fnolab-audit-control");
    await expect(controls).toHaveCount(1);
    await expect(controls.first()).toContainText("kill_switch: on → off");
    await expect(controls.first()).toContainText("admin_fixture · “Reviewed and cleared”");
  });

  test("A-3 Audit: search filters by correlation id or decision id, and says when nothing matches", async ({ page }) => {
    await base(page);
    await page.goto(`${LAB}?screen=audit`);
    await page.getByTestId("fnolab-audit-search").fill("2222");
    await expect(page.getByTestId("fnolab-audit-decision")).toHaveCount(1);
    await expect(page.getByTestId("fnolab-audit-decision").first()).toHaveAttribute("data-id", "dec-ok-0003");
    await page.getByTestId("fnolab-audit-search").fill("DEC-OLD");
    await expect(page.getByTestId("fnolab-audit-decision")).toHaveCount(1);
    await expect(page.getByTestId("fnolab-audit-decision").first()).toHaveAttribute("data-id", "dec-old-0001");
    await page.getByTestId("fnolab-audit-search").fill("zzz-none");
    await expect(page.getByTestId("fnolab-audit-nomatch")).toContainText("No decision matches “zzz-none”");
  });

  test("S-5 Phone (390px): each governance screen has no horizontal page scroll", async ({ page }) => {
    await base(page);
    await page.route("**/api/desk/strategy/payoff", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(PAYOFF) }));
    await page.setViewportSize({ width: 390, height: 844 });
    for (const s of ["prog", "replay", "shadow", "live", "cert", "audit"]) {
      await page.goto(`${LAB}?screen=${s}`);
      await expect(page.getByTestId(`fnolab-screen-${s}`)).toBeVisible();
      if (s === "prog") {
        await page.getByTestId("fnolab-prog-run").click();
        await expect(page.getByTestId("fnolab-prog-children")).toBeVisible();
      }
      if (s === "audit") await expect(page.getByTestId("fnolab-audit-lineage")).toBeVisible();
      await noSideScroll(page);
    }
  });
});
