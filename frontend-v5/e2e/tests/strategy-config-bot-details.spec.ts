/**
 * Strategy Builder — "Bot details", step 4 of the wizard
 * (docs/STRATEGY_BUILDER_CONFIG_SPEC.md §8, §8b; src/pages/StrategyBuilder/BotDetailsPanel.tsx).
 *
 * MOCK — not real data. Every /api/* response in this file is written here, in the shape
 * backend/routes/strategy_builder.py returns (the function is named beside each one). The spec
 * needs NO network and NO session token: it runs in the mocked `desktop-chrome` project of
 * playwright.config.ts (local Vite + route mocks), the way the other mocked specs in this
 * folder do — strategy-builder.config.ts is the LIVE config for this area (it targets staging
 * with a real cookie and matches only `strategy-builder-live`), so this spec is not for it.
 *
 * Case ids are test_reports/strategy_config_TESTCASES.md's: TC-24 … TC-29 and TC-31, TC-32.
 * TC-33 (error count on the stepper tab), TC-34 (the fetched schema owns the defaults) and
 * TC-35 (stored-only keys marked in the resolved panel) are asserted inside TC-25, TC-24 /
 * TC-29 and TC-27 respectively, where the state they need already exists.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import { mockApi } from "../helpers/api-mock";

// The Strategy Builder page inside the Copilot shell. The standalone /v5/strategy-builder URL was removed in the desk
// redesign's step 6 (2026-10-27); it now redirects to the desk's Trade Desk.
const PAGE_URL = "/v5/app/trader/strategy";
const STRATEGY_ID = "11111111-2222-3333-4444-555555555555";

const json = (page: Page, pattern: string | RegExp, body: unknown, status = 200) =>
  page.route(pattern, (route) =>
    route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) }));

// ── Payloads ────────────────────────────────────────────────────────
// Shape: list_templates()
const TEMPLATES = {
  templates: [{
    key: "fixture_trend",
    name: "Fixture trend",
    description: "MOCK template — RSI + 20d return, enough for the wizard to reach Bot details.",
    definition: {
      asset_class: "STOCK",
      entry: { all_of: [{ feature: "rsi14", op: ">", value: 55 }] },
      ranking: { by: "accumulation_score", order: "desc", limit: 3 },
    },
  }],
};

// Shape: universe_catalog() — one broad index card, so the universe is {type:"index", ref:"NIFTY500"}
const CATALOG = {
  as_of_date: "2026-10-20",
  return_window: "3M",
  count: 1,
  universes: [{
    kind: "broad", category: "Broad Market", ref: "NIFTY500", id: null,
    name: "Fixture Broad 500", description: "MOCK universe.",
    symbol_count: 500, return_3m_pct: 4.2, trend: "steady", trend_label: "Steady",
  }],
};

// Shape: screen_strategy() — these three symbols are the read-only chips in Bot details
const SYMBOLS = ["RELIANCE", "TCS", "INFY"];
const SCREEN = {
  candidates: SYMBOLS.map((symbol, i) => ({
    symbol, close: 1200 + i, rsi14: 60 + i, accumulation_score: 70 - i, return_20d_pct: 3 + i,
  })),
  count: SYMBOLS.length,
  as_of_date: "2026-10-20",
  ranked_by: "accumulation_score",
  score_basis: "MOCK accumulation score",
};

// Shape: config_schema() — derived in the real route from services/ai_trader/config.py
// (FIELD_RANGES + AI_DEFAULTS + _CONFIG_NOT_ENFORCED), reproduced here value for value
// with ONE deliberate difference: initial_capital.default is 500000, not the 1000000 of
// AI_DEFAULTS and of BOT_CONFIG_SCHEMA_FALLBACK. That is what lets this spec tell "the
// screen used the fetched schema" apart from "the screen ignored it and used its own
// fallback copy" — with identical numbers every assertion below would pass either way.
const CONFIG_SCHEMA = {
  $schema: "https://json-schema.org/draft/2020-12/schema",
  title: "Strategy config (Bot details)",
  schema_version: 1,
  type: "object",
  additionalProperties: false,
  required: [],
  properties: {
    symbols: {
      type: "array", items: { type: "string" }, minItems: 1, readOnly: true, owner: "platform",
      description: "Derived from the strategy's universe. Never written through this API.",
    },
    initial_capital: {
      type: "number", default: 500000, owner: "code", writable_in_code: true,
      enforced_by_engine: true, error_message: "initial_capital out of range",
      exclusiveMinimum: 0, maximum: 1e10,
    },
    commission_pct: {
      type: "number", default: 0.05, owner: "bot_details", writable_in_code: false,
      enforced_by_engine: true, error_message: "commission_pct out of range",
      minimum: 0, maximum: 5,
    },
    // Stored but inert: the backtester counts no same-direction entries.
    pyramiding: {
      type: "integer", default: 0, owner: "bot_details", writable_in_code: false,
      enforced_by_engine: false, error_message: "pyramiding must be >= 0", minimum: 0,
    },
    // Stored but inert: the backtester is long-only.
    short_margin_pct: {
      type: "number", default: 100, owner: "bot_details", writable_in_code: false,
      enforced_by_engine: false, error_message: "short_margin_pct out of range",
      exclusiveMinimum: 0, maximum: 100,
    },
  },
  writable: ["initial_capital", "commission_pct", "pyramiding", "short_margin_pct"],
  not_enforced_by_engine: ["pyramiding", "short_margin_pct"],
};

// Shape: _config_payload() with no stored row — the AI defaults, `stored: false`. An index
// universe has no enumerable symbol list, hence the empty list and "unavailable".
const STORED_CONFIG = {
  strategy_id: STRATEGY_ID, stored: false, schema_version: 1,
  initial_capital: 1000000, commission_pct: 0.05, pyramiding: 0, short_margin_pct: 100,
  symbols: [], symbols_source: "unavailable", updated_at: null,
  not_enforced_by_engine: ["pyramiding", "short_margin_pct"],
};

// Shape: run_backtest()
const BACKTEST = {
  metrics: { trade_count: 2, win_rate: 50, total_return_pct: 4.1, max_drawdown_pct: -2.3 },
  equity_curve: [{ date: "2026-04-20", equity: 1000000 }, { date: "2026-10-20", equity: 1041000 }],
  trades: [
    { symbol: "RELIANCE", entry_date: "2026-05-04", entry_price: 1200, exit_date: "2026-06-02", exit_price: 1260, exit_reason: "TARGET", pnl_pct: 5, holding_days: 29 },
    { symbol: "TCS", entry_date: "2026-07-01", entry_price: 3400, exit_date: "2026-07-20", exit_price: 3298, exit_reason: "STOP", pnl_pct: -3, holding_days: 19 },
  ],
};

/** One request the screen made to a strategy's config resource. */
type ConfigCall = { method: string; path: string; body: Record<string, unknown> | null };

/**
 * Mocks every /api the wizard touches on the way to Bot details, and records each
 * /strategies/{id}/config request (GET from the wizard, PUT from a save). The returned
 * array is live — read it after the interaction.
 */
async function mockBuilder(page: Page): Promise<ConfigCall[]> {
  const calls: ConfigCall[] = [];
  await mockApi(page, "populated");                       // shell + auth/me, and a 200 {} catch-all
  await json(page, "**/api/strategy-builder/templates", TEMPLATES);
  await json(page, "**/api/strategy-builder/universe-catalog", CATALOG);
  await json(page, "**/api/strategy-builder/universes*", { universes: [], count: 0 });
  await json(page, "**/api/strategy-builder/screen", SCREEN);
  await json(page, "**/api/strategy-builder/config-schema", CONFIG_SCHEMA);
  await json(page, "**/api/strategy-builder/strategies", { id: STRATEGY_ID, name: "Fixture trend" });
  await json(page, "**/api/strategy-builder/strategies/*/backtest", BACKTEST);
  await page.route("**/api/strategy-builder/strategies/*/config", (route: Route) => {
    const req = route.request();
    const body = req.method() === "PUT" ? (req.postDataJSON() as Record<string, unknown>) : null;
    calls.push({ method: req.method(), path: new URL(req.url()).pathname, body });
    return route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({ ...STORED_CONFIG, ...(body ?? {}), stored: body != null }),
    });
  });
  return calls;
}

/** Universe → Strategy → Screen → Bot details, the way a user reaches the step. */
async function openBotDetails(page: Page) {
  await page.goto(PAGE_URL);
  await expect(page.getByTestId("strategy-builder-page")).toBeVisible();
  await page.getByTestId("universe-card-NIFTY500").click();
  await page.getByRole("button", { name: "Strategy →" }).click();
  await page.getByTestId("template-fixture_trend").click();
  await page.getByRole("button", { name: "Screen →" }).click();
  await page.getByTestId("run-screen").click();
  await expect(page.getByTestId("screen-results")).toBeVisible();
  await page.getByRole("button", { name: "Bot details →" }).click();
  await expect(page.getByTestId("bot-details-panel")).toBeVisible();
}

/** One field's card. ConfigField carries no testid, so it is found by its own label. */
const fieldCard = (page: Page, label: string) =>
  page.locator('[data-testid="bot-details-panel"] div.rounded-xl').filter({ hasText: label });

test.describe("Strategy Builder — Bot details (config spec §8b)", () => {
  test("TC-24 the step renders the four fields and the read-only symbol chips", async ({ page }) => {
    await mockBuilder(page);
    await openBotDetails(page);

    const panel = page.getByTestId("bot-details-panel");
    await expect(panel).toContainText("The config the engine starts a run with. Set it before you backtest.");

    // The four Bot-details built-ins, at the FETCHED schema's defaults — capital opens
    // at 500000 (CONFIG_SCHEMA), not the 1000000 of BOT_CONFIG_SCHEMA_FALLBACK.
    await expect(page.getByTestId("bot-capital")).toHaveValue("500000");
    await expect(page.getByTestId("bot-commission")).toHaveValue("0.05");
    await expect(page.getByTestId("bot-pyramiding")).toHaveText("0");
    await expect(page.getByTestId("bot-short-margin")).toHaveValue("100");
    await expect(page.getByTestId("bot-error-count")).toHaveCount(0);
    await expect(page.getByTestId("step-tab-bot-details-errors")).toHaveCount(0);

    // §8b.1 ownership badges, one per field.
    await expect(fieldCard(page, "Symbols")).toContainText("Platform · read-only in code");
    await expect(fieldCard(page, "Initial capital (INR)")).toContainText("Overridable in code");
    await expect(fieldCard(page, "Commission (%)")).toContainText("Read-only in code");
    await expect(fieldCard(page, "Pyramiding")).toContainText("Read-only in code");
    await expect(fieldCard(page, "Short margin (%)")).toContainText("Read-only in code");

    // Symbols: the screen's candidates as chips, with nothing to type or press.
    const chips = page.getByTestId("bot-symbols");
    for (const s of SYMBOLS) await expect(chips).toContainText(s);
    await expect(chips.locator("input, textarea, button")).toHaveCount(0);
    await expect(page.getByTestId("bot-symbols-note"))
      .toContainText("Symbols come from the universe step (NIFTY500); the screen picks them per run. There's nothing to edit here.");

    // The two fields the engine does not act on yet say so (schema enforced_by_engine: false).
    await expect(page.getByTestId("bot-pyramiding-note"))
      .toHaveText("Stored only for now — the backtester counts no same-direction entries, so this value changes nothing in a run.");
    await expect(page.getByTestId("bot-short-margin-note"))
      .toHaveText("Stored only for now — the backtester is long-only, so this value changes nothing in a run.");
    // The schema was served, so the form is not on its fallback ranges.
    await expect(page.getByTestId("bot-schema-fallback")).toHaveCount(0);
  });

  test("TC-25 an invalid capital shows the §8b.2 message and the Run backtest control is disabled", async ({ page }) => {
    await mockBuilder(page);
    await openBotDetails(page);
    const capital = page.getByTestId("bot-capital");
    const save = page.getByTestId("bot-save");
    const run = page.getByTestId("run-backtest");
    const toBacktest = page.getByRole("button", { name: "Backtest →" });
    const tabBadge = page.getByTestId("step-tab-bot-details-errors");

    // > 0 (exclusive)
    await capital.fill("0");
    await expect(page.getByTestId("bot-capital-error")).toHaveText("Initial capital must be above ₹0.");
    await expect(page.getByTestId("bot-error-count")).toHaveText("1 field needs fixing before you can run a backtest.");
    await expect(page.getByTestId("bot-capital-help")).toHaveCount(0);
    await expect(toBacktest).toBeDisabled();

    // §8b.2: the count sits on the Bot details TAB, so leaving the step cannot hide
    // that the step is invalid — the in-panel banner unmounts with the panel.
    await expect(tabBadge).toHaveText("1");
    await page.getByTestId("step-tab-screen").click();
    await expect(page.getByTestId("bot-details-panel")).toHaveCount(0);
    await expect(page.getByTestId("bot-error-count")).toHaveCount(0);
    await expect(tabBadge).toHaveText("1");
    await page.getByTestId("step-tab-bot-details").click();
    await expect(capital).toHaveValue("0");

    // <= 1e10
    await capital.fill("10000000001");
    await expect(page.getByTestId("bot-capital-error")).toHaveText("Maximum is ₹1,000 Cr (10,000,000,000).");
    await expect(toBacktest).toBeDisabled();
    // the boundary itself is accepted
    await capital.fill("10000000000");
    await expect(page.getByTestId("bot-capital-error")).toHaveCount(0);
    await expect(tabBadge).toHaveCount(0);

    // parses as a number
    await capital.fill("ten lakh");
    await expect(page.getByTestId("bot-capital-error")).toHaveText("Enter an amount in rupees, like 1,00,000.");
    await expect(toBacktest).toBeDisabled();
    await expect(tabBadge).toHaveText("1");

    // Valid again → the step opens, and its own Run backtest is live.
    await capital.fill("900000");
    await expect(page.getByTestId("bot-error-count")).toHaveCount(0);
    await expect(toBacktest).toBeEnabled();
    await toBacktest.click();
    await expect(run).toBeEnabled();

    // That run creates the strategy, so the save control is no longer held off by a
    // missing id (its "no strategy yet" note is gone and it is enabled). Only now does
    // "invalid ⇒ save off" below actually test the §8b.2 gate.
    await run.click();
    await expect(page.getByTestId("backtest-results")).toBeVisible();
    await page.getByTestId("step-tab-bot-details").click();
    await expect(page.getByTestId("bot-save-note")).toHaveCount(0);
    await expect(save).toBeEnabled();
    await capital.fill("0");
    await expect(page.getByTestId("bot-capital-error")).toHaveText("Initial capital must be above ₹0.");
    await expect(save).toBeDisabled();

    // Break it again: Run backtest on the Backtest step is disabled, with §8b.2's tooltip.
    await page.getByTestId("step-tab-backtest").click();
    await expect(run).toBeDisabled();
    await expect(run).toHaveAttribute("title", "Fix the highlighted fields first");
  });

  test("TC-26 the pyramiding stepper shows the \"N allowed · next rejected\" copy and floors at 0", async ({ page }) => {
    await mockBuilder(page);
    await openBotDetails(page);
    const value = page.getByTestId("bot-pyramiding");
    const slots = page.getByTestId("bot-pyramiding-slots");
    const help = page.getByTestId("bot-pyramiding-help");
    const dec = page.getByTestId("bot-pyramiding-dec");
    const inc = page.getByTestId("bot-pyramiding-inc");

    await expect(value).toHaveText("0");
    await expect(slots).toContainText("1 allowed · next rejected");
    await expect(help).toHaveText("One entry per direction. The next same-direction signal is rejected with PYRAMIDING_LIMIT.");
    await expect(dec).toBeDisabled();                       // floor: 0 is the minimum

    await inc.click();
    await expect(value).toHaveText("1");
    await expect(slots).toContainText("2 allowed · next rejected");
    await expect(help).toHaveText("Up to 2 same-direction entries. The next signal is rejected with PYRAMIDING_LIMIT.");
    await expect(dec).toBeEnabled();

    await inc.click();
    await expect(value).toHaveText("2");
    await expect(slots).toContainText("3 allowed · next rejected");
    await expect(help).toHaveText("Up to 3 same-direction entries. The next signal is rejected with PYRAMIDING_LIMIT.");

    // Back down to the floor, where the control stops.
    await dec.click();
    await dec.click();
    await expect(value).toHaveText("0");
    await expect(dec).toBeDisabled();
    await expect(slots).toContainText("1 allowed · next rejected");
    await expect(page.getByTestId("bot-pyramiding-error")).toHaveCount(0);
  });

  test("TC-27 the resolved-config panel toggles Fields/JSON and shows a source pill per field", async ({ page }) => {
    await mockBuilder(page);
    await openBotDetails(page);
    const panel = page.getByTestId("resolved-config");

    // Fields view: key, value, source pill (§8b.4).
    await expect(panel.getByTestId("resolved-row-symbols")).toContainText("3 symbols");
    await expect(panel.getByTestId("resolved-row-symbols")).toContainText("RELIANCE, TCS, INFY");
    await expect(panel.getByTestId("resolved-row-initial_capital")).toContainText("₹5,00,000");
    await expect(panel.getByTestId("resolved-row-commission_pct")).toContainText("0.05%");
    await expect(panel.getByTestId("resolved-row-pyramiding")).toContainText("0");
    await expect(panel.getByTestId("resolved-row-short_margin_pct")).toContainText("100%");
    await expect(panel.getByTestId("resolved-source-symbols")).toHaveText("Platform");
    for (const key of ["initial_capital", "commission_pct", "pyramiding", "short_margin_pct"]) {
      await expect(panel.getByTestId(`resolved-source-${key}`), key).toHaveText("Bot details");
    }

    // The schema's not_enforced_by_engine keys carry that marker here too, so a
    // "Bot details" pill under "the values the next run starts from" can't read as
    // "this one reaches the run". The two enforced keys carry no marker.
    for (const key of ["pyramiding", "short_margin_pct"]) {
      await expect(panel.getByTestId(`resolved-not-live-${key}`), key)
        .toHaveText("Stored only — a run doesn't apply it.");
    }
    await expect(panel.getByTestId("resolved-not-live-initial_capital")).toHaveCount(0);
    await expect(panel.getByTestId("resolved-not-live-commission_pct")).toHaveCount(0);
    await expect(panel.getByTestId("resolved-footer"))
      .toHaveText("The values the next backtest run starts from — except the keys marked stored only, which a run ignores.");

    // JSON view: schema_version 1, the built-ins, user keys nested under `custom`, and
    // the same not_enforced_by_engine list the API returns.
    await panel.getByTestId("resolved-toggle-json").click();
    const dump = panel.getByTestId("resolved-json");
    await expect(dump).toBeVisible();
    expect(JSON.parse(await dump.innerText())).toEqual({
      schema_version: 1,
      symbols: SYMBOLS,
      initial_capital: 500000,
      commission_pct: 0.05,
      pyramiding: 0,
      short_margin_pct: 100,
      custom: {},
      not_enforced_by_engine: ["pyramiding", "short_margin_pct"],
    });
    await expect(panel.getByTestId("resolved-row-initial_capital")).toHaveCount(0);

    // Back to Fields, and the panel follows an edit.
    await panel.getByTestId("resolved-toggle-fields").click();
    await expect(dump).toHaveCount(0);
    await page.getByTestId("bot-capital").fill("250000");
    await expect(panel.getByTestId("resolved-row-initial_capital")).toContainText("₹2,50,000");
  });

  test("TC-28 with a strategyId the save control issues a PUT; with none it issues no request", async ({ page }) => {
    const calls = await mockBuilder(page);
    await openBotDetails(page);

    // No strategy row yet: the control is off, it says why, and nothing is sent.
    const save = page.getByTestId("bot-save");
    await expect(save).toBeDisabled();
    await expect(page.getByTestId("bot-save-note"))
      .toHaveText("No strategy yet — these values are held here and saved with the strategy when you run the first backtest.");
    await save.click({ force: true });

    // "It sent nothing" cannot be asserted the instant after the click — no route
    // handler could have run yet, so an implementation that DID PUT with a null id
    // would pass. Settle on a round trip instead: the first backtest creates the
    // strategy (POST /strategies) and legitimately sends exactly one PUT (the wizard
    // saving the config before the run) and one GET (reading the stored row back).
    // A PUT from that disabled control would make it two.
    await page.getByRole("button", { name: "Backtest →" }).click();
    await page.getByTestId("run-backtest").click();
    await expect(page.getByTestId("backtest-results")).toBeVisible();
    await expect.poll(() => calls.filter((c) => c.method === "GET").length).toBe(1);
    expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1);

    await page.getByTestId("step-tab-bot-details").click();
    await expect(save).toBeEnabled();
    await expect(page.getByTestId("bot-save-note")).toHaveCount(0);
    // The stored row (₹10,00,000) has landed and replaced the schema default the form
    // opened at (₹5,00,000), so the PUT below is built from settled values.
    await expect(page.getByTestId("bot-capital")).toHaveValue("1000000");

    calls.length = 0;
    await page.getByTestId("bot-commission").fill("0.1");
    await save.click();
    await expect(page.getByTestId("bot-save-status")).toContainText("Saved at");
    expect(calls).toEqual([{
      method: "PUT",
      path: `/api/strategy-builder/strategies/${STRATEGY_ID}/config`,
      // The four built-ins only — `symbols` is platform-owned and never written here.
      body: { initial_capital: 1000000, commission_pct: 0.1, pyramiding: 0, short_margin_pct: 100 },
    }]);
  });

  test("TC-29 help text under a field changes as the value changes", async ({ page }) => {
    await mockBuilder(page);
    await openBotDetails(page);

    // §8b.3: capital in lakh/crore, suffixed "· default" when it equals the default the
    // FETCHED schema carries (₹5,00,000 here, not the fallback's ₹10,00,000).
    const capHelp = page.getByTestId("bot-capital-help");
    await expect(capHelp).toHaveText("₹5.00 L · default");
    await page.getByTestId("bot-capital").fill("25,00,000");      // typed the Indian way
    await expect(capHelp).toHaveText("₹25.00 L");

    // §8b.3: ₹{pct × 1000} on every ₹1,00,000 traded.
    const comHelp = page.getByTestId("bot-commission-help");
    await expect(comHelp).toHaveText("₹50 on every ₹1,00,000 traded, charged on each buy, sell, short and close.");
    await page.getByTestId("bot-commission").fill("0.1");
    await expect(comHelp).toHaveText("₹100 on every ₹1,00,000 traded, charged on each buy, sell, short and close.");

    // §8b.3: ₹{pct × 1000} blocked per ₹1,00,000 short.
    const smHelp = page.getByTestId("bot-short-margin-help");
    await expect(smHelp).toHaveText("₹1,00,000 blocked per ₹1,00,000 short. The position force-closes if losses use up the block.");
    await page.getByTestId("bot-short-margin").fill("40");
    await expect(smHelp).toHaveText("₹40,000 blocked per ₹1,00,000 short. The position force-closes if losses use up the block.");

    // And the stepper's own line.
    await page.getByTestId("bot-pyramiding-inc").click();
    await expect(page.getByTestId("bot-pyramiding-help"))
      .toHaveText("Up to 2 same-direction entries. The next signal is rejected with PYRAMIDING_LIMIT.");
  });

  test("TC-31 a failed config save abandons the run — it is never run half-applied", async ({ page }) => {
    const calls = await mockBuilder(page);

    // Every backtest request is recorded, so "no run happened" is checkable.
    const runs: string[] = [];
    await page.route("**/api/strategy-builder/strategies/*/backtest", (route: Route) => {
      runs.push(route.request().method());
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(BACKTEST) });
    });
    // PUT /config fails (GET still works). Registered after mockBuilder's handler for the
    // same URL, so this one wins.
    await page.route("**/api/strategy-builder/strategies/*/config", (route: Route) => {
      const req = route.request();
      const isPut = req.method() === "PUT";
      calls.push({
        method: req.method(), path: new URL(req.url()).pathname,
        body: isPut ? (req.postDataJSON() as Record<string, unknown>) : null,
      });
      return isPut
        ? route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "MOCK — config store unavailable" }) })
        : route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(STORED_CONFIG) });
    });

    await openBotDetails(page);
    // Two edits, so a run that went ahead would carry the new capital on the request
    // and the OLD commission from the unchanged stored row — the mix §8b warns about.
    await page.getByTestId("bot-capital").fill("2500000");
    await page.getByTestId("bot-commission").fill("0.5");
    await page.getByRole("button", { name: "Backtest →" }).click();
    await page.getByTestId("run-backtest").click();

    // The save was attempted, failed, and stopped the run there.
    await expect.poll(() => calls.filter((c) => c.method === "PUT").length).toBe(1);
    await expect(page.getByText("Backtest not run — couldn't save Bot details")).toBeVisible();
    await expect(page.getByTestId("backtest-results")).toHaveCount(0);
    expect(runs).toEqual([]);
  });

  test("TC-32 Save with an invalid Bot-details field warns and writes nothing", async ({ page }) => {
    const calls = await mockBuilder(page);
    const strategyWrites: string[] = [];
    await page.route("**/api/strategy-builder/strategies", (route: Route) => {
      strategyWrites.push(route.request().method());
      return route.fulfill({
        status: 200, contentType: "application/json",
        body: JSON.stringify({ id: STRATEGY_ID, name: "Fixture trend" }),
      });
    });

    await openBotDetails(page);
    // Walk to the Save step while the config is valid, so the step stays reachable.
    await page.getByRole("button", { name: "Backtest →" }).click();
    await page.getByRole("button", { name: "Save →" }).click();
    await expect(page.getByTestId("save-strategy")).toBeEnabled();

    // Break a field, then save from the step that no longer shows the panel.
    await page.getByTestId("step-tab-bot-details").click();
    await page.getByTestId("bot-capital").fill("0");
    await expect(page.getByTestId("step-tab-bot-details-errors")).toHaveText("1");
    await page.getByTestId("step-tab-save").click();
    await page.getByTestId("save-strategy").click();

    // Warned, nothing written, and no success claimed over dropped edits.
    await expect(page.getByText("Fix the highlighted Bot details first")).toBeVisible();
    await expect(page.getByText("Strategy saved", { exact: true })).toHaveCount(0);
    expect(strategyWrites).toEqual([]);
    expect(calls.filter((c) => c.method === "PUT")).toEqual([]);

    // Fix it and the same click saves for real — the gate is the field, not the button.
    await page.getByTestId("step-tab-bot-details").click();
    await page.getByTestId("bot-capital").fill("1000000");
    await page.getByTestId("step-tab-save").click();
    await page.getByTestId("save-strategy").click();
    await expect(page.getByText("Strategy saved", { exact: true })).toBeVisible();
    expect(strategyWrites).toEqual(["POST"]);
    await expect.poll(() => calls.filter((c) => c.method === "PUT").length).toBe(1);
  });
});
