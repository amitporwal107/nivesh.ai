/**
 * One-screen Copilot app (/v5/app) — the Markets screen and the filings feed.
 *
 * Each block is checked against the endpoint that feeds it: the data it shows,
 * its empty state and its error state, plus one phone-width pass.
 *
 * MOCK — not real data: every response below is a fixture
 * (e2e/fixtures/copilot-markets-*.json) or an inline payload shaped like the
 * real contract, with synthetic values. Expected values are worked out from
 * the payload, not copied from the screen. Shapes:
 *   backend/routes/markets.py, routes/market_events.py, routes/filings.py,
 *   backend/nidp/services/daas_api/routers/market_pulse.py
 *
 * Mocked APIs, production build — see pw.copilot-app.config.ts.
 */
import { test, expect, type Page } from "@playwright/test";
import fs from "fs";
import path from "path";
import { mockApi } from "../helpers/api-mock";

// Stamps in the fixtures are IST; rendering them in IST keeps the dates fixed.
test.use({ timezoneId: "Asia/Kolkata" });

const APP = "/v5/app";
const FX = path.join(process.cwd(), "e2e", "fixtures");
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(FX, name), "utf-8"));

const json = (page: Page, pattern: string | RegExp, body: unknown, status = 200) =>
  page.route(pattern, (route) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) }));

/** A failed read is retried once by the http client and once by the query before the error shows. */
const SLOW = { timeout: 15_000 };

/**
 * With SHOT_DIR set, saves the screen as <SHOT_DIR>/markets-<name>-<n>.png, one file per
 * 1,300 px of height, for a look by eye. The shell scrolls inside its own pane, so the
 * window is first made tall enough to hold the whole screen.
 */
async function shot(page: Page, name: string) {
  const dir = process.env.SHOT_DIR;
  const size = page.viewportSize();
  if (!dir || !size) return;
  await page.setViewportSize({ width: size.width, height: 6500 });
  const bottom = await page.evaluate(() => {
    const screen = document.querySelector('[data-testid^="screen-"]');
    return screen ? Math.ceil(screen.getBoundingClientRect().bottom) : 0;
  });
  for (let top = 0, n = 1; top < Math.min(bottom, 6500); top += 1300, n += 1) {
    await page.screenshot({ path: path.join(dir, `markets-${name}-${n}.png`), clip: { x: 0, y: top, width: size.width, height: Math.min(1300, bottom - top) } });
  }
  await page.setViewportSize(size);
}

/** Captures what a screen hands to the Copilot. Returns the sent messages. */
async function mockAsk(page: Page): Promise<string[]> {
  const sent: string[] = [];
  await page.route("**/api/chat/sessions", (route) =>
    route.request().method() === "POST"
      ? route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ session_id: "asked1" }) })
      : route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route("**/api/chat/messages*", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route("**/api/chat/stream", (route) => {
    sent.push((route.request().postDataJSON() as { message: string }).message);
    return route.fulfill({ status: 200, contentType: "text/event-stream", body: `data: ${JSON.stringify({ type: "done", content: "ok" })}\n\n` });
  });
  return sent;
}

// ── payloads ─────────────────────────────────────────────────────────────

const HOME = load("copilot-markets-home.json");
const HOLDINGS = load("copilot-markets-holdings.json");
const EARNINGS = load("copilot-markets-earnings.json");
const EARNINGS_COMPANIES = load("copilot-markets-earnings-companies.json") as Record<string, unknown>;
const SECTORS = load("copilot-markets-sectors.json");
const SECTOR_DETAIL = load("copilot-markets-sector-detail.json");
const ARTICLES = load("copilot-markets-articles.json");

const EXPLORE = {
  ok: true, universe: "Fixture 50", fetched_at: "2026-01-09T10:00:05+05:30",
  high_52w: [{ symbol: "FIXTUREUP", name: "Fixture Gainer Ltd", price: 101.5, change_pct: 4.2, from_high_pct: -2.5 }],
  low_52w: [{ symbol: "FIXTUREDN", name: "Fixture Loser Ltd", price: 88.25, change_pct: -3.1, from_low_pct: 1.5 }],
  most_active: [{ symbol: "FIXTUREUP", name: "Fixture Gainer Ltd", price: 101.5, change_pct: 4.2, volume: 12_500_000 }],
};

/** 12 sessions, newest first. Session i: FII net −(1000+10i) on even i, +(1000+10i) on odd i; DII net 500+5i. */
const FLOWS = {
  ok: true, as_of: "2026-01-20",
  daily: Array.from({ length: 12 }, (_, i) => {
    const fii = (i % 2 ? 1 : -1) * (1000 + i * 10);
    const dii = 500 + i * 5;
    return { date: `2026-01-${String(20 - i).padStart(2, "0")}`, fii_buy: 9000, fii_sell: 9000 - fii, fii_net: fii, dii_buy: 7000 + dii, dii_sell: 7000, dii_net: dii };
  }),
  monthly: [
    { month: "2026-01-01", fii_buy: 50000, fii_sell: 56000, fii_net: -6000, dii_buy: 60000, dii_sell: 52000, dii_net: 8000 },
    { month: "2025-12-01", fii_buy: 48000, fii_sell: 45500, fii_net: 2500, dii_buy: 40000, dii_sell: 41000, dii_net: -1000 },
  ],
};

const POSITIONING = {
  ok: true, period_end: "2025-12-31", universe: "Fixture 500",
  sectors: [
    { sector: "Fixture Sector A", fii_cr: 1000, dii_cr: 5000, n: 3 },
    { sector: "Fixture Sector B", fii_cr: 4000, dii_cr: 1500, n: 5 },
    { sector: "Fixture Sector C", fii_cr: 2000, dii_cr: 2000, n: 2 },
  ],
};

const ACTIONS = {
  ok: true, types: ["DIVIDEND", "BONUS", "RIGHTS", "SPLIT", "MERGER", "DEMERGER", "BUYBACK"],
  from: "2026-01-01", to: "2026-03-02",
  actions: [
    { symbol: "FIXTUREUP", name: "Fixture Gainer Ltd.", action_type: "DIVIDEND", subtype: "INTERIM", ex_date: "2026-01-20", record_date: "2026-01-21", value_label: "₹12", dividend_amount: 12, ratio: null, purpose: "Fixture interim dividend" },
    { symbol: "FIXTUREOTHER", name: "Fixture Other Ltd.", action_type: "BONUS", subtype: null, ex_date: "2026-02-02", record_date: "2026-02-03", value_label: "1:1", dividend_amount: null, ratio: "1:1", purpose: "Fixture bonus" },
    { symbol: "FIXNAME", name: "Fixture Nameonly Ltd.", action_type: "SPLIT", subtype: null, ex_date: "2026-02-10", record_date: null, value_label: "FV ₹10 → ₹2", dividend_amount: null, ratio: "5:1", purpose: "Fixture split" },
  ],
  type_counts: { DIVIDEND: 1, BONUS: 1, SPLIT: 1 },
};

const BRIEF = {
  ok: true,
  brief: {
    date: "2026-01-08", generated_at: "2026-01-09T02:00:00+00:00", headline: "Fixture brief headline.",
    bullets: ["Fixture bullet one", "Fixture bullet two"], market_state: "closed",
    stats: { nifty_close: 20000, nifty_change_pct: 1.0, vix: 15, vix_change_pct: -3.85, advances: 1500, declines: 900, fii_net_cr: -1500.4, dii_net_cr: 2200.25, verdict: "CAUTIOUS" },
    top_sectors: [{ name: "Fixture Sector A", change_pct: 1.5 }, { name: "Fixture Sector C", change_pct: 0.25 }],
    movers: {
      gainers: [{ symbol: "FIXTUREUP", name: "Fixture Gainer Ltd", price: 101.5, change_pct: 4.2 }],
      losers: [{ symbol: "FIXTUREDN", name: "Fixture Loser Ltd", price: 88.25, change_pct: -3.1 }],
    },
    news: [
      { title: "Fixture Gainer Ltd — Fixture brief news", symbol: "FIXTUREUP", category: "Earnings" },
      { title: "Fixture news without a company", symbol: null, category: "Orders" },
    ],
    sources: ["NIDP", "NSE", "Yahoo Finance"],
  },
};
const BRIEF_DAYS = { ok: true, items: [{ date: "2026-01-08", headline: "Fixture brief headline.", generated_at: "2026-01-09T02:00:00+00:00" }, { date: "2026-01-07", headline: "Fixture older headline." }] };

const FEED = {
  ok: true, total: 2, facets: { earnings: 1, orders: 1 },
  rows: [
    { id: "fix-1", ticker: "FIXTUREUP", code: "FIXTUREUP", name: "Fixture Gainer Ltd", date: "2026-01-08T10:00:00+00:00", category: "earnings", impact: "high", sentiment: "positive", docLabel: "Press Release", url: "https://example.test/f1.pdf", one: "Fixture one-line read.", period: "Q3 FY26", metric: "Fixture metric: 10 ₹ cr", hasInsights: true },
    { id: "fix-2", ticker: null, code: null, name: "Fixture Nameless Co", date: "2026-01-07T10:00:00+00:00", category: "orders", impact: "medium", sentiment: "neutral", docLabel: "Outcome of Board Meeting", url: null, one: null, period: null, metric: null, hasInsights: false },
  ],
};
const INSIGHT = {
  ok: true, id: "fix-1", one: "Fixture one-line read, in full.", period: "Q3 FY26", metric: "Fixture metric: 10 ₹ cr", sentiment: "positive", confidence: 0.85,
  docType: null, docLabel: null, model: "fixture-model", generatedAt: "2026-01-08T12:00:00+00:00",
  tabs: [{ key: "quick_summary", label: "Quick Summary" }, { key: "potential_risks", label: "Potential Risks" }],
  sections: [
    { tab: "Quick Summary", h: "Fixture section heading", items: ["Fixture item one", "Fixture item two"], cite: "pp. 2-3", cite_url: "https://example.test/f1.pdf#page=2" },
    { tab: "Potential Risks", h: "Fixture risks heading", items: ["Fixture risk"], cite: null, cite_url: null },
  ],
  sourceUrl: "https://example.test/f1.pdf", grounded: true, disclaimer: "Fixture disclaimer.",
};

/** Calendar rows keyed by days from today; `event_date` is filled in from the requested day. */
const CALENDAR: Record<number, Array<Record<string, unknown>>> = {
  2: [
    { symbol: "FIXTUREUP", company_name: "Fixture Gainer Ltd.", event_type: "quarterly_results", period: "Q3 FY26", purpose: "Fixture board meeting to consider results", calendar_source: "nse" },
    { symbol: "FIXTUREOTHER", company_name: "Fixture Other Ltd.", event_type: "quarterly_results", period: "Q3 FY26", purpose: "Fixture results, not held", calendar_source: "nse" },
  ],
  5: [
    { symbol: "FIXNAME", company_name: "Fixture Nameonly Ltd.", event_type: "quarterly_results", period: null, purpose: "Fixture results matched by name", calendar_source: "nse" },
    { symbol: "FIXTUREDN", company_name: "Fixture Loser Ltd.", event_type: "dividend", period: null, purpose: "Fixture dividend, not a results date", calendar_source: "nse" },
  ],
};

// ── route setup ──────────────────────────────────────────────────────────

/** The event calendar, one day per request. Returns the days that were asked for. */
async function mockCalendar(page: Page, byOffset: Record<number, Array<Record<string, unknown>>>): Promise<string[]> {
  const asked: string[] = [];
  await page.route("**/api/market/events*", (route) => {
    const day = new URL(route.request().url()).searchParams.get("date_str") ?? "";
    asked.push(day);
    const offset = Math.round((Date.parse(day) - Date.parse(asked[0])) / 86_400_000);
    const events = (byOffset[offset] ?? []).map((e) => ({ ...e, event_date: day }));
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ events, date: day, count: events.length }) });
  });
  return asked;
}

async function mockEarningsCompanies(page: Page) {
  await page.route("**/api/markets/earnings/companies*", (route) => {
    const sector = new URL(route.request().url()).searchParams.get("sector") ?? "";
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(EARNINGS_COMPANIES[sector] ?? {}) });
  });
}

/** Every Markets endpoint answered with its populated payload. A test overrides what it studies. */
async function setup(page: Page) {
  await mockApi(page, "populated");
  await json(page, "**/api/chat/sessions", []);
  await json(page, "**/api/markets/home", HOME);
  await json(page, "**/api/markets/explore", EXPLORE);
  await json(page, "**/api/markets/sectors", SECTORS);
  await json(page, "**/api/markets/sectors/*", SECTOR_DETAIL);
  await json(page, "**/api/markets/earnings*", EARNINGS);
  await mockEarningsCompanies(page);
  await json(page, "**/api/markets/fii-dii*", FLOWS);
  await json(page, "**/api/markets/institutional-positioning", POSITIONING);
  await json(page, "**/api/markets/corporate-actions*", ACTIONS);
  await json(page, "**/api/markets/articles*", ARTICLES);
  await json(page, "**/api/markets/daily-brief*", BRIEF);
  await json(page, "**/api/markets/daily-brief/history*", BRIEF_DAYS);
  await json(page, "**/api/portfolio/holdings-enriched*", HOLDINGS);
  await json(page, "**/api/filings/portfolio-held", { ok: true, names: ["fixturegainer"], isins: [], symbols: ["FIXTUREUP"] });
}

async function openTab(page: Page, tab: string) {
  await page.goto(`${APP}/tool/markets`);
  await expect(page.getByTestId("screen-tool-markets")).toBeVisible();
  if (tab !== "market") await page.getByTestId(`markets-tab-${tab}`).click();
}

const stockIcons = (scope: ReturnType<Page["getByTestId"]>) => scope.locator('[data-testid="entity-icon"][data-kind="stock"]');

// ─────────────────────────────────────────────────────────────────────────

test.describe("Markets → Market", () => {
  test("shows every block of the overview response, with icons and the as-of the response carried", async ({ page }) => {
    await setup(page);
    await openTab(page, "market");

    // Tape: Nifty +1.0%, 1500 advances / 900 declines, breadth tone POSITIVE, VIX −3.85% FALLING, FII net −1500.5.
    await expect(page.getByTestId("markets-read")).toContainText("Markets closed higher, with breadth positive. The Nifty 50 is +1.00%, on 1,500 advances against 900 declines.");
    await expect(page.getByTestId("markets-read")).toContainText("India VIX −3.85%, cooling");
    await expect(page.getByTestId("markets-read")).toContainText("FIIs were net sellers in the cash market on 8 Jan");
    await expect(page.getByTestId("markets-read")).toContainText("Fixture Sector A is the strongest sector at +1.50%");
    // The backend's verdict text is printed as sent.
    await expect(page.getByTestId("markets-verdict")).toHaveText("Rules-based read · normal: FIXTURE verdict reason, shown exactly as sent");

    // Index tape: points change and a sparkline where the response has closes (Nifty and Sensex; the VIX has none).
    await expect(page.locator('[data-testid="markets-index-points"][data-index="Nifty 50"]')).toHaveText("+200.00");
    await expect(page.locator('[data-testid="markets-index-points"][data-index="Sensex"]')).toHaveText("−330.00");
    await expect(page.locator('[data-testid="markets-index-points"][data-index="India VIX"]')).toHaveCount(0);
    await expect(page.getByTestId("markets-index-spark")).toHaveCount(2);
    await expect(page.getByTestId("markets-eyebrow")).toHaveText(/^Markets · updated 9 Jan 2026, 10:00\s?am · market closed$/i);
    // No source in the response: nothing is claimed; the signed-in admin is told so.
    const overview = page.getByTestId("markets-overview-source");
    await expect(overview.getByTestId("source-asof")).toHaveText(/^updated 9 Jan 2026, 10:00\s?am$/i);
    await expect(overview.getByTestId("source-name")).toHaveCount(0);
    await expect(overview.getByTestId("source-unstated")).toBeVisible();

    // Sector moves, strongest first.
    const bars = page.getByTestId("markets-sector-bar");
    await expect(bars).toHaveCount(3);
    await expect(bars.nth(0)).toContainText("Fixture Sector A");
    await expect(bars.nth(0)).toContainText("+1.50%");
    await expect(bars.nth(2)).toContainText("Fixture Sector B");
    await expect(bars.nth(2)).toContainText("−0.75%");

    // Breadth: counts plus the four structural figures.
    await expect(page.getByTestId("markets-breadth")).toHaveText("1,500 advances · 900 declines");
    await expect(page.getByTestId("markets-breadth-unchanged")).toHaveText("100");
    await expect(page.getByTestId("markets-breadth-above20")).toHaveText("62%");
    await expect(page.getByTestId("markets-breadth-above50")).toHaveText("48%");
    await expect(page.getByTestId("markets-breadth-highs")).toHaveText("34");
    await expect(page.getByTestId("markets-breadth-lows")).toHaveText("12");

    // Latest institutional flows: −1500.5 and +2200.25 ₹ crore, as of 2026-01-08.
    await expect(page.getByTestId("markets-snapshot-fii")).toHaveText("−₹1,501 Cr");
    await expect(page.getByTestId("markets-snapshot-dii")).toHaveText("+₹2,200 Cr");
    await expect(page.getByTestId("markets-snapshot-asof")).toHaveText("as of 8 Jan 2026");

    // Movers: a company icon per row; the held company is badged.
    const movers = page.getByTestId("markets-movers");
    await expect(stockIcons(movers)).toHaveCount(2);
    await expect(movers.locator('[data-testid="entity-icon"][data-key="FIXTUREUP"]')).toHaveCount(1);
    await expect(movers.getByText("You hold")).toHaveCount(1);
    await expect(page.getByTestId("markets-movers-asof")).toContainText("prices as of 8 Jan 2026");

    // World indices, commodities, headlines.
    for (const name of ["Fixture US Index", "Fixture EU Index", "Fixture Asia Index"]) {
      await expect(page.getByTestId("markets-world-indices")).toContainText(name);
    }
    await expect(page.getByTestId("markets-commodities")).toContainText("Fixture Crude · $/bbl");
    await expect(page.getByTestId("markets-commodities")).toContainText("80.50");
    const news = page.getByTestId("markets-news-item");
    await expect(news).toHaveCount(2);
    await expect(stockIcons(news.nth(0))).toHaveCount(1); // names FIXTUREUP
    await expect(stockIcons(news.nth(1))).toHaveCount(0); // names no company

    await shot(page, "market");
    await page.getByTestId("markets-open-flows").click();
    await expect(page.getByTestId("markets-tab-flows")).toHaveAttribute("aria-selected", "true");
  });

  test("market lists are read when first opened", async ({ page }) => {
    await setup(page);
    let reads = 0;
    await page.route("**/api/markets/explore", (route) => {
      reads += 1;
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(EXPLORE) });
    });
    await openTab(page, "market");
    await expect(page.getByTestId("markets-movers")).toBeVisible();
    expect(reads).toBe(0);

    await page.getByTestId("markets-list-high_52w").click();
    const table = page.getByTestId("markets-list-table");
    await expect(table).toContainText("Fixture Gainer Ltd");
    await expect(table).toContainText("From the high");
    await expect(table).toContainText("−2.5%");
    await expect(stockIcons(table)).toHaveCount(1);
    await expect(page.getByTestId("markets-list-source")).toContainText(/updated 9 Jan 2026, 10:00\s?am/i);
    await expect(page.getByTestId("markets-list-source")).toContainText("Stocks of the Fixture 50");

    await page.getByTestId("markets-list-most_active").click();
    await expect(table).toContainText("Shares traded");
    await expect(table).toContainText("1.25 Cr"); // 12,500,000 shares
    expect(reads).toBe(1);
  });

  test("empty and error states", async ({ page }) => {
    await setup(page);
    // The overview with nothing but an index: every other block says it has no figures.
    await json(page, "**/api/markets/home", {
      ...HOME, verdict: null, verdict_reason: null, gainers: [], losers: [], sectors: [], fii_dii: null, news: [],
      global_cues: [], global_indices: { us: [], europe: [], asia: [] }, commodities: [],
      breadth: { advances: null, declines: null, unchanged: null, universe: null, tone: "NEUTRAL", pct_above_20ema: null, pct_above_50ema: null, new_52w_highs: null, new_52w_lows: null },
    });
    await json(page, "**/api/markets/explore", { ok: false, high_52w: [], low_52w: [], most_active: [], universe: "Fixture 50" });
    await openTab(page, "market");
    await expect(page.getByTestId("markets-verdict")).toHaveCount(0);
    await expect(page.getByTestId("markets-sector-bars-empty")).toBeVisible();
    await expect(page.getByTestId("markets-breadth-empty")).toBeVisible();
    await expect(page.getByTestId("markets-breadth")).toHaveCount(0);
    await expect(page.getByTestId("markets-flows-snapshot-empty")).toBeVisible();
    await expect(page.getByTestId("markets-movers")).toContainText("No movers are available for this segment right now.");
    await expect(page.getByTestId("markets-global-cues")).toContainText("Global quotes are not available right now.");
    await expect(page.getByTestId("markets-world-indices")).toHaveCount(0);
    await expect(page.getByTestId("markets-news")).toHaveCount(0);
    await page.getByTestId("markets-list-low_52w").click();
    await expect(page.getByTestId("markets-list-table")).toContainText("This list is empty right now.");

    // A failed list read, then a failed overview read.
    await json(page, "**/api/markets/explore", { detail: "boom" }, 500);
    await json(page, "**/api/markets/home", { detail: "boom" }, 500);
    await page.goto(`${APP}/tool/markets`);
    await expect(page.getByText("The market dashboard didn’t load")).toBeVisible(SLOW);
    await expect(page.getByTestId("markets-indices")).toHaveCount(0);
  });

  test("a failed market-list read says so", async ({ page }) => {
    await setup(page);
    await json(page, "**/api/markets/explore", { detail: "boom" }, 500);
    await openTab(page, "market");
    await page.getByTestId("markets-list-high_52w").click();
    await expect(page.getByText("This list didn’t load")).toBeVisible(SLOW);
  });

  test("a non-admin is not shown the source remark or the engineering notes", async ({ page }) => {
    await setup(page);
    await json(page, "**/api/auth/me", { user_id: "u_fixture_investor", email: "investor@example.test", name: "Fixture Investor", is_admin: false, onboarding_completed: true });
    await openTab(page, "market");
    await expect(page.getByTestId("markets-overview-source").getByTestId("source-asof")).toBeVisible();
    await expect(page.getByTestId("source-unstated")).toHaveCount(0);
    await expect(page.getByTestId("markets-sector-bars-period")).toHaveCount(0);
  });
});

test.describe("Markets → Sector Analysis", () => {
  test("the table shows the endpoint's figures; a row opens the sector's companies and commentary", async ({ page }) => {
    await setup(page);
    await openTab(page, "sectors");
    const rows = page.getByTestId("markets-sectors").getByRole("row");
    // Header + two sectors, highest one-year return first (A +18.25%, B −6.5%).
    await expect(rows).toHaveCount(3);
    for (const text of ["Fixture Sector A", "Fixture blurb A", "12", "9 / 3", "+18.25%", "₹2.50 L Cr", "22.5×", "+0.60%"]) {
      await expect(rows.nth(1)).toContainText(text);
    }
    for (const text of ["Fixture Sector B", "8", "2 / 6", "−6.50%", "−0.40%"]) await expect(rows.nth(2)).toContainText(text);
    await expect(page.getByTestId("markets-sector-read")).toContainText("Fixture Sector A leads over the year with an average stock return of +18.3%; Fixture Sector B is weakest at −6.5%.");
    await expect(page.getByTestId("markets-sectors-source")).toContainText("as of 8 Jan 2026");

    await rows.nth(1).click();
    const detail = page.getByTestId("markets-sector-detail");
    await expect(page.getByTestId("markets-sector-detail-name")).toHaveText("Fixture Sector A");
    await expect(page.getByTestId("markets-sector-detail-headline")).toHaveText("Fixture Sector A: fixture headline.");
    const tiles = page.getByTestId("markets-sector-detail-tiles");
    for (const text of ["₹2.50 L Cr", "22.5×", "15.5%", "9 / 3 up / down over 1Y", "+18.25%", "Fixture Index A today", "+0.60%", "21.0× P/E"]) {
      await expect(tiles).toContainText(text);
    }
    const companies = page.getByTestId("markets-sector-companies");
    await expect(stockIcons(companies)).toHaveCount(2);
    for (const text of ["Fixture Gainer Ltd", "₹1.20 L Cr", "+32.50%", "28.4×", "Fixture Other Ltd", "₹45.0K Cr", "−4.50%"]) {
      await expect(companies).toContainText(text);
    }
    await expect(companies.getByText("You hold")).toHaveCount(1);
    await expect(page.getByTestId("markets-sector-commentary")).toContainText("Fixture commentary paragraph for the test suite.");
    await expect(page.getByTestId("markets-sector-commentary")).toContainText("Fixture disclaimer for the commentary.");
    // The detail response names its sources ("NIDP", "NSE"); they are printed in plain words.
    await expect(page.getByTestId("markets-sector-detail-source").getByTestId("source-name")).toHaveText("Source: Nivesh data platform · NSE");
    await expect(page.getByTestId("markets-sector-detail-source").getByTestId("source-asof")).toHaveText("as of 8 Jan 2026");
    await shot(page, "sectors");

    await page.getByTestId("markets-sector-detail-close").click();
    await expect(detail).toHaveCount(0);
  });

  test("empty and error states", async ({ page }) => {
    await setup(page);
    // A sector with no commentary and no companies.
    await json(page, "**/api/markets/sectors/*", { ok: true, sector: { ...SECTOR_DETAIL.sector, top_companies: [], commentary_md: null, commentary_error: "llm_not_configured" } });
    await openTab(page, "sectors");
    await page.getByTestId("markets-sectors").getByRole("row").nth(1).click();
    await expect(page.getByTestId("markets-sector-companies")).toContainText("The largest companies are not available for this sector right now.");
    await expect(page.getByTestId("markets-sector-commentary-empty")).toContainText("AI commentary is not switched on in this environment.");
    await page.getByTestId("markets-sector-detail-close").click();

    // The endpoint has no such sector.
    await json(page, "**/api/markets/sectors/*", { ok: false, error: "not_found", sector: null });
    await page.getByTestId("markets-sectors").getByRole("row").nth(2).click();
    await expect(page.getByTestId("markets-sector-detail-empty")).toBeVisible();

    // The detail read fails.
    await json(page, "**/api/markets/sectors/*", { detail: "boom" }, 500);
    await json(page, "**/api/markets/sectors", { ok: true, sectors: [{ ...SECTORS.sectors[0], slug: "fixture-fails" }], llm_enabled: true });
    await page.goto(`${APP}/tool/markets`);
    await page.getByTestId("markets-tab-sectors").click();
    await page.getByTestId("markets-sectors").getByRole("row").nth(1).click();
    await expect(page.getByText("This sector didn’t load")).toBeVisible(SLOW);

    // No sectors at all, then a failed list read.
    await json(page, "**/api/markets/sectors", { ok: true, sectors: [] });
    await page.goto(`${APP}/tool/markets`);
    await page.getByTestId("markets-tab-sectors").click();
    await expect(page.getByText("Sector figures are being prepared")).toBeVisible();
    await json(page, "**/api/markets/sectors", { detail: "boom" }, 500);
    await page.goto(`${APP}/tool/markets`);
    await page.getByTestId("markets-tab-sectors").click();
    await expect(page.getByText("Sectors didn’t load")).toBeVisible(SLOW);
  });
});

test.describe("Markets → Earnings Tracker", () => {
  test("summary growth, quarter-on-quarter columns and the company drill-down", async ({ page }) => {
    await setup(page);
    await mockCalendar(page, {});
    await openTab(page, "earnings");
    // Summary: sales +12.5% / profit +9.5% YoY, sales +3.5% QoQ.
    await expect(page.getByTestId("markets-earnings-declared")).toHaveText("40 / 100");
    await expect(page.getByTestId("markets-earnings-sales-yoy")).toHaveText("+12.5%");
    await expect(page.getByTestId("markets-earnings-profit-yoy")).toHaveText("Profit +9.5% YoY");
    await expect(page.getByTestId("markets-earnings-sales-qoq")).toHaveText("+3.5%");
    const rows = page.getByTestId("markets-earnings-sectors").getByRole("row");
    await expect(rows).toHaveCount(3);
    for (const text of ["Fixture Sector A", "30 / 60", "20", "8", "2", "+14.1%", "+11.2%", "+4.0%", "+2.5%"]) await expect(rows.nth(1)).toContainText(text);
    for (const text of ["Fixture Sector B", "10 / 40", "−2.6%", "−3.4%"]) await expect(rows.nth(2)).toContainText(text);
    await expect(page.getByTestId("markets-earnings-source")).toContainText("quarter ended 31 Dec 2025");

    await rows.nth(1).click();
    const panel = page.getByTestId("markets-earnings-companies");
    await expect(page.getByTestId("markets-earnings-companies-sector")).toHaveText("Fixture Sector A");
    await expect(page.getByTestId("markets-earnings-companies-count")).toHaveText("2 of 3 companies have declared");
    const companies = panel.getByRole("row");
    await expect(companies).toHaveCount(4);
    for (const text of ["Fixture Gainer Ltd.", "FIXTUREUP", "You hold", "Profit grew", "+15.0%", "+20.0%", "+2.0%", "+5.0%", "₹1,200 Cr", "₹150 Cr"]) {
      await expect(companies.nth(1)).toContainText(text);
    }
    await expect(companies.nth(2)).toContainText("Profit shrank");
    await expect(companies.nth(3)).toContainText("Not yet reported");
    await expect(stockIcons(panel)).toHaveCount(3);

    await page.getByTestId("markets-earnings-companies-filter").fill("wait");
    await expect(panel.getByRole("row")).toHaveCount(2);
    await expect(panel).toContainText("Fixture Waiting Ltd.");
    await page.getByTestId("markets-earnings-companies-filter").fill("zzz");
    await expect(panel).toContainText("No company in this sector matches “zzz”.");
    await page.getByTestId("markets-earnings-companies-close").click();
    await expect(panel).toHaveCount(0);
  });

  test("your holdings: result dates from the calendar and this quarter's results, direct stocks only", async ({ page }) => {
    await setup(page);
    const asked = await mockCalendar(page, CALENDAR);
    await openTab(page, "earnings");
    const block = page.getByTestId("markets-earnings-holdings");
    await expect(page.getByTestId("markets-earnings-holdings-nc")).toHaveCount(0); // the old placeholder is gone

    // Result dates: of the four calendar rows, two are quarterly results of stocks held directly
    // (FIXTUREUP by symbol, "Fixture Nameonly" by name); one is not held, one is a dividend.
    await expect(page.getByTestId("markets-earnings-dates-line")).toHaveText("2 of your stocks report results in the next 14 days.");
    const dates = page.getByTestId("markets-earnings-dates").getByRole("row");
    await expect(dates).toHaveCount(3);
    await expect(dates.nth(1)).toContainText("Fixture Gainer Ltd.");
    await expect(dates.nth(1)).toContainText("Q3 FY26");
    await expect(dates.nth(1)).toContainText("Fixture board meeting to consider results");
    await expect(dates.nth(2)).toContainText("Fixture Nameonly Ltd.");
    expect(new Set(asked).size).toBe(14); // one request per day of the window
    const due = new Date(Date.parse(asked[0]) + 2 * 86_400_000);
    await expect(dates.nth(1).getByRole("cell").nth(1)).toHaveText(new RegExp(`^${due.getUTCDate()} \\S+ ${due.getUTCFullYear()}$`));
    await expect(page.getByTestId("markets-earnings-dates-source").getByTestId("source-name")).toHaveText("Source: NSE");
    await expect(stockIcons(page.getByTestId("markets-earnings-dates"))).toHaveCount(2);

    // This quarter: 3 of the 4 direct stocks are in the index (FIXOUT is not); Gainer and Nameonly
    // have reported, Loser has not. Reported rows come first.
    await expect(page.getByTestId("markets-earnings-holdings-line")).toHaveText(
      "3 of your 4 directly held stocks are in the Fixture Index 100: 2 have reported Q3 FY26 and 1 has not yet.",
    );
    const quarter = page.getByTestId("markets-earnings-holdings-quarter").getByRole("row");
    await expect(quarter).toHaveCount(4);
    for (const text of ["Fixture Gainer Ltd.", "Reported · profit grew", "+15.0%", "+20.0%", "₹150 Cr"]) await expect(quarter.nth(1)).toContainText(text);
    await expect(quarter.nth(2)).toContainText("Fixture Nameonly Ltd.");
    await expect(quarter.nth(2)).toContainText("Reported · no year-ago quarter");
    await expect(quarter.nth(3)).toContainText("Fixture Loser Ltd.");
    await expect(quarter.nth(3)).toContainText("Not yet reported");
    await expect(page.getByTestId("markets-earnings-holdings-outside")).toHaveText("1 of your stocks is not in the Fixture Index 100. Pick a wider index above to check it.");
    // The fixture portfolio also has two mutual funds and one ETF.
    await expect(page.getByTestId("markets-earnings-holdings-scope")).toHaveText(
      "Only stocks you hold directly are checked. Stocks held through your 3 mutual funds and ETFs are not included.",
    );
    await expect(block).not.toContainText("Fixture Flexi Cap Fund");
    // What the design also shows and no endpoint has.
    await expect(page.getByTestId("markets-earnings-move-nc")).toBeVisible();
    await shot(page, "earnings");
  });

  test("your holdings: a calendar that cannot be read is declared, after one request", async ({ page }) => {
    await setup(page);
    let reads = 0;
    await page.route("**/api/market/events*", (route) => {
      reads += 1;
      // What the route answers when its table is missing (HTTP 200 with an error note).
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ events: [], date: "2026-01-09", _error: "fixture: calendar table missing" }) });
    });
    await openTab(page, "earnings");
    await expect(page.getByTestId("markets-earnings-calendar-nc")).toContainText("The results calendar could not be read just now");
    await expect(page.getByTestId("markets-earnings-calendar-nc")).not.toContainText("fixture: calendar table missing");
    await expect(page.getByTestId("markets-earnings-dates")).toHaveCount(0);
    // The quarter join does not depend on the calendar.
    await expect(page.getByTestId("markets-earnings-holdings-quarter")).toBeVisible();
    await page.waitForLoadState("networkidle");
    expect(reads).toBe(1);
  });

  test("your holdings: empty and error states", async ({ page }) => {
    await setup(page);
    // A readable calendar with nothing for the user's stocks, and an index that holds none of them.
    await mockCalendar(page, {});
    await json(page, "**/api/markets/earnings/companies*", { ok: true, index: "Fixture Index 100", sector: "x", period_end: "2025-12-31", quarter: "Q3 FY26", declared: 0, members: 0, companies: [] });
    await openTab(page, "earnings");
    await expect(page.getByTestId("markets-earnings-dates-none")).toContainText("None of your 4 directly held stocks has a results date in the calendar for");
    await expect(page.getByTestId("markets-earnings-holdings-line")).toHaveText("None of your 4 directly held stocks is in the Fixture Index 100.");
    await expect(page.getByTestId("markets-earnings-holdings-quarter")).toHaveCount(0);

    // The calendar read fails; the sector lists fail.
    await json(page, "**/api/market/events*", { detail: "boom" }, 500);
    await json(page, "**/api/markets/earnings/companies*", { detail: "boom" }, 500);
    await page.goto(`${APP}/tool/markets`);
    await page.getByTestId("markets-tab-earnings").click();
    await expect(page.getByText("The results calendar didn’t load")).toBeVisible(SLOW);
    await expect(page.getByText("This quarter’s results could not be matched to your stocks")).toBeVisible(SLOW);

    // A portfolio with funds only: nothing to match, and it says why.
    await json(page, "**/api/portfolio/holdings-enriched*", load("copilot-markets-holdings-funds-only.json"));
    await page.goto(`${APP}/tool/markets`);
    await page.getByTestId("markets-tab-earnings").click();
    await expect(page.getByTestId("markets-earnings-holdings-none")).toBeVisible();
    await expect(page.getByTestId("markets-earnings-holdings-scope")).toContainText("Stocks held through your 3 mutual funds and ETFs are not included.");

    // The holdings read fails.
    await json(page, "**/api/portfolio/holdings-enriched*", { detail: "boom" }, 500);
    await page.goto(`${APP}/tool/markets`);
    await page.getByTestId("markets-tab-earnings").click();
    await expect(page.getByText("Your holdings didn’t load, so results could not be matched to them")).toBeVisible(SLOW);
    // The tracker itself is unaffected.
    await expect(page.getByTestId("markets-earnings-declared")).toHaveText("40 / 100");
  });

  test("empty and error states of the tracker", async ({ page }) => {
    await setup(page);
    await mockCalendar(page, {});
    await json(page, "**/api/markets/earnings*", { ok: true, index: "Fixture Index 100", period_end: null, quarter: null, summary: null, sectors: [], available_indices: [], available_quarters: [] });
    await openTab(page, "earnings");
    await expect(page.getByText("No declared results for this quarter in Fixture Index 100")).toBeVisible();
    await json(page, "**/api/markets/earnings*", { detail: "boom" }, 500);
    await page.goto(`${APP}/tool/markets`);
    await page.getByTestId("markets-tab-earnings").click();
    await expect(page.getByText("Earnings didn’t load")).toBeVisible(SLOW);
  });
});

test.describe("Markets → FII / DII", () => {
  test("daily and monthly flows, every session on request, and holdings ranked three ways", async ({ page }) => {
    await setup(page);
    await openTab(page, "flows");
    // Latest session: FII −1000, DII +500; FIIs sold on the even sessions → 5 of the latest 10.
    await expect(page.getByTestId("markets-flows-read")).toContainText(
      "FIIs sold a net ₹1,000 Cr in cash on 20 Jan, and were net sellers in 5 of the last 10 sessions; DIIs bought a net ₹500 Cr.",
    );
    await expect(page.getByTestId("markets-flows-bar")).toHaveCount(12);
    const table = page.getByTestId("markets-flows-table");
    await expect(table.getByRole("row")).toHaveCount(11); // header + the latest 10
    await expect(page.getByTestId("markets-fii-net").first()).toHaveText("−1,000");
    await expect(page.getByTestId("markets-dii-net").first()).toHaveText("+500");
    await expect(page.getByTestId("markets-combined-net").first()).toHaveText("−500");
    await expect(page.getByTestId("markets-flows-source").getByTestId("source-asof")).toHaveText("as of 20 Jan 2026");
    await shot(page, "flows");
    await page.getByTestId("markets-flows-all").click();
    await expect(table.getByRole("row")).toHaveCount(13);

    await page.getByTestId("markets-flows-gran-monthly").click();
    await expect(table.getByRole("row")).toHaveCount(3);
    await expect(table.getByRole("row").nth(1)).toContainText("Jan 2026");
    await expect(page.getByTestId("markets-fii-net").first()).toHaveText("−6,000");
    await expect(page.getByTestId("markets-combined-net").first()).toHaveText("+2,000");
    await expect(page.getByTestId("markets-flows-read")).toContainText(
      "FIIs sold a net ₹6,000 Cr in cash in Jan 2026, and were net sellers in 1 of the last 2 months; DIIs bought a net ₹8,000 Cr.",
    );

    // Holdings by sector: FII B 4000 > C 2000 > A 1000; DII A 5000 first; both A 6000 first.
    const holdings = page.getByTestId("markets-positioning").getByRole("row");
    await expect(holdings.nth(1)).toContainText("Fixture Sector B");
    await page.getByTestId("markets-positioning-lens-dii").click();
    await expect(holdings.nth(1)).toContainText("Fixture Sector A");
    await page.getByTestId("markets-positioning-lens-both").click();
    await expect(holdings.nth(1)).toContainText("Fixture Sector A");
    await expect(holdings.nth(1)).toContainText("₹6.0K Cr");
    await expect(page.getByTestId("markets-positioning-source").getByTestId("source-asof")).toHaveText("shareholding of 31 Dec 2025");
  });

  test("empty and error states", async ({ page }) => {
    await setup(page);
    await json(page, "**/api/markets/fii-dii*", { ok: true, as_of: null, daily: [], monthly: [] });
    await json(page, "**/api/markets/institutional-positioning", { ok: true, period_end: null, universe: "Fixture 500", sectors: [] });
    await openTab(page, "flows");
    await expect(page.getByText("No institutional-flow figures yet")).toBeVisible();
    await expect(page.getByTestId("markets-positioning")).toContainText("No shareholding data is available for this view.");
    await page.getByTestId("markets-flows-gran-monthly").click();
    await expect(page.getByText("No monthly totals yet")).toBeVisible();

    await json(page, "**/api/markets/fii-dii*", { detail: "boom" }, 500);
    await page.goto(`${APP}/tool/markets`);
    await page.getByTestId("markets-tab-flows").click();
    await expect(page.getByText("FII / DII flows didn’t load")).toBeVisible(SLOW);
  });
});

test.describe("Markets → Corporate Actions", () => {
  test("the calendar, its filters, and the actions on stocks held directly", async ({ page }) => {
    await setup(page);
    const asked: URL[] = [];
    await page.route("**/api/markets/corporate-actions*", (route) => {
      asked.push(new URL(route.request().url()));
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(ACTIONS) });
    });
    await openTab(page, "actions");

    const rows = page.getByTestId("markets-actions").getByRole("row");
    await expect(rows).toHaveCount(4);
    await expect(page.getByTestId("markets-actions-count")).toHaveText("3 events");
    for (const text of ["Fixture Gainer Ltd.", "FIXTUREUP", "You hold", "20 Jan 2026", "21 Jan 2026", "Dividend", "₹12"]) await expect(rows.nth(1)).toContainText(text);
    await expect(stockIcons(page.getByTestId("markets-actions"))).toHaveCount(3);

    // Held directly: FIXTUREUP (by symbol, 100 shares × ₹12 = ₹1,200) and "Fixture Nameonly" (by name, 10 shares, a split).
    await expect(page.getByTestId("markets-actions-holdings-line")).toHaveText("2 corporate actions on your 4 directly held stocks, from 1 Jan to 2 Mar 2026.");
    const held = page.getByTestId("markets-actions-holdings-table").getByRole("row");
    await expect(held).toHaveCount(3);
    await expect(held.nth(1)).toContainText("Fixture Gainer Ltd.");
    await expect(held.nth(1)).toContainText("100");
    await expect(held.nth(1).getByTestId("markets-actions-holdings-amount")).toHaveText("₹1,200");
    await expect(held.nth(2)).toContainText("Fixture Nameonly Ltd.");
    await expect(held.nth(2)).toContainText("Split");
    await expect(held.nth(2).getByTestId("markets-actions-holdings-amount")).toHaveText("—");
    await expect(page.getByTestId("markets-actions-holdings-scope")).toContainText("Stocks held through your 3 mutual funds and ETFs are not included.");
    await expect(page.getByTestId("markets-actions-holdings-partial")).toHaveCount(0);
    await shot(page, "actions");

    // Filters reach the endpoint: type, search (after the typing pause) and dates.
    await page.getByTestId("markets-actions-type-DIVIDEND").click();
    await expect.poll(() => asked.some((u) => u.searchParams.get("action_type") === "DIVIDEND")).toBe(true);
    await page.getByTestId("markets-actions-search").fill("fixture gainer");
    await expect.poll(() => asked.some((u) => u.searchParams.get("q") === "fixture gainer")).toBe(true);
    await page.getByTestId("markets-actions-from").fill("2026-01-05");
    await expect.poll(() => asked.some((u) => u.searchParams.get("date_from") === "2026-01-05")).toBe(true);
    // The holdings check always reads every type for the dates.
    await expect.poll(() => asked.some((u) => u.searchParams.get("date_from") === "2026-01-05" && !u.searchParams.has("action_type") && !u.searchParams.has("q"))).toBe(true);
  });

  test("a calendar longer than one response says what was not checked", async ({ page }) => {
    await setup(page);
    await json(page, "**/api/markets/corporate-actions*", { ...ACTIONS, type_counts: { DIVIDEND: 200, BONUS: 30, SPLIT: 20 } });
    await openTab(page, "actions");
    await expect(page.getByTestId("markets-actions-holdings-partial")).toContainText("the first 3 of 250 actions");
    await expect(page.getByTestId("markets-actions-source")).toContainText("Showing the first 3 of 250");
  });

  test("empty and error states", async ({ page }) => {
    await setup(page);
    await json(page, "**/api/markets/corporate-actions*", { ...ACTIONS, actions: [], type_counts: {} });
    await openTab(page, "actions");
    await expect(page.getByTestId("markets-actions")).toContainText("No corporate actions fall between these dates.");
    await expect(page.getByTestId("markets-actions-holdings-line")).toHaveText("None of your 4 directly held stocks has a corporate action from 1 Jan to 2 Mar 2026.");
    await expect(page.getByTestId("markets-actions-holdings-table")).toHaveCount(0);

    await json(page, "**/api/markets/corporate-actions*", { detail: "boom" }, 500);
    await page.goto(`${APP}/tool/markets`);
    await page.getByTestId("markets-tab-actions").click();
    await expect(page.getByText("Corporate actions didn’t load")).toBeVisible(SLOW);
    // The date and search boxes stay usable while the calendar is failing.
    await expect(page.getByTestId("markets-actions-from")).toBeVisible();
  });
});

test.describe("Markets → Articles", () => {
  test("each card names its company with an icon and its feed; search reaches the endpoint", async ({ page }) => {
    await setup(page);
    const asked: URL[] = [];
    await page.route("**/api/markets/articles*", (route) => {
      const url = new URL(route.request().url());
      asked.push(url);
      const body = url.searchParams.get("q") === "nothing here" ? { ok: true, articles: [], total: 0, categories: {} } : ARTICLES;
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    });
    await openTab(page, "articles");
    const cards = page.getByTestId("markets-article");
    await expect(cards).toHaveCount(12); // 14 in the response, 12 per page
    await expect(cards.nth(0)).toContainText("Fixture Gainer Ltd");
    await expect(cards.nth(0)).toContainText("You hold");
    await expect(cards.nth(0)).toContainText("Earnings · High impact");
    await expect(cards.nth(0)).toContainText("NSE announcements · 2 min read"); // source NSE_ANN, read_min 2
    await expect(cards.nth(1)).toContainText("BSE announcements · 1 min read"); // source BSE_ANN
    await expect(cards.nth(0).locator('[data-testid="entity-icon"][data-key="FIXTUREUP"]')).toHaveCount(1);
    await expect(stockIcons(page.getByTestId("markets-articles"))).toHaveCount(12);
    await expect(page.getByTestId("markets-articles-source").getByTestId("source-name")).toHaveText("Source: NSE announcements · BSE announcements");
    await shot(page, "articles");
    await page.getByTestId("markets-articles-more").click();
    await expect(cards).toHaveCount(14);

    await page.getByTestId("markets-articles-search").fill("nothing here");
    await expect(page.getByText("Nothing in the last 7 days matches “nothing here”.")).toBeVisible();
    expect(asked.some((u) => u.searchParams.get("q") === "nothing here")).toBe(true);
    await expect(page.getByTestId("markets-articles-search")).toHaveValue("nothing here");
  });

  test("error state", async ({ page }) => {
    await setup(page);
    await json(page, "**/api/markets/articles*", { detail: "boom" }, 500);
    await openTab(page, "articles");
    await expect(page.getByText("Articles didn’t load")).toBeVisible(SLOW);
  });
});

test.describe("Markets → Daily Iris Update", () => {
  test("the stored brief: the backend's label as sent, sectors, movers, announcements and its stated sources", async ({ page }) => {
    await setup(page);
    await openTab(page, "brief");
    await expect(page.getByTestId("markets-brief-headline")).toHaveText("Fixture brief headline.");
    await expect(page.getByTestId("markets-brief-read")).toContainText("Iris read · rules-based · 8 Jan 2026 · market closed");
    await expect(page.getByTestId("markets-brief-read")).toContainText("Fixture bullet two");
    await expect(page.getByTestId("markets-brief-verdict")).toHaveText("Rules-based regime label · cautious"); // stats.verdict "CAUTIOUS"
    await expect(page.getByTestId("markets-brief-nifty")).toHaveText("20,000.00");
    await expect(page.getByTestId("markets-brief-fii")).toHaveText("−₹1,500 Cr");
    const sectors = page.getByTestId("markets-brief-sectors").getByRole("row");
    await expect(sectors).toHaveCount(3);
    await expect(sectors.nth(1)).toContainText("Fixture Sector A");
    await expect(sectors.nth(1)).toContainText("+1.50%");
    const movers = page.getByTestId("markets-brief-movers");
    await expect(movers.getByRole("row")).toHaveCount(3);
    await expect(stockIcons(movers)).toHaveCount(2);
    await expect(movers).toContainText("−3.10%");
    const news = page.getByTestId("markets-brief-news-item");
    await expect(news).toHaveCount(2);
    await expect(stockIcons(news.nth(0))).toHaveCount(1);
    await expect(stockIcons(news.nth(1))).toHaveCount(0);
    // sources: ["NIDP", "NSE", "Yahoo Finance"], generated 2026-01-09T02:00Z = 7:30 am IST.
    const source = page.getByTestId("markets-brief-source");
    await expect(source.getByTestId("source-name")).toHaveText("Source: Nivesh data platform · NSE · Yahoo Finance");
    await expect(source.getByTestId("source-asof")).toHaveText(/^generated 9 Jan 2026, 7:30\s?am$/i);
    await shot(page, "brief");
  });

  test("empty and error states", async ({ page }) => {
    await setup(page);
    await json(page, "**/api/markets/daily-brief*", { ok: false, brief: null });
    await json(page, "**/api/markets/daily-brief/history*", BRIEF_DAYS);
    await openTab(page, "brief");
    await expect(page.getByText("No brief for this day yet")).toBeVisible();
    await expect(page.getByTestId("markets-brief-date")).toBeVisible();
    await json(page, "**/api/markets/daily-brief*", { detail: "boom" }, 500);
    await page.goto(`${APP}/tool/markets`);
    await page.getByTestId("markets-tab-brief").click();
    await expect(page.getByText("The daily brief didn’t load")).toBeVisible(SLOW);
  });
});

test.describe("Filings feed (Research → Filings)", () => {
  test("each row has its company icon; AI insights opens the generated read under the row", async ({ page }) => {
    await setup(page);
    const sent = await mockAsk(page);
    await json(page, "**/api/filings/feed*", FEED);
    await page.route("**/api/filings/*/insights", (route) =>
      route.request().url().includes("/fix-1/")
        ? route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(INSIGHT) })
        : route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ ok: false, reason: "no_insight_yet" }) }));
    await page.goto(`${APP}/tool/research`);
    const feed = page.getByTestId("filings-feed");
    const rows = feed.getByTestId("filing-row");
    await expect(rows).toHaveCount(2);
    await expect(rows.nth(0).locator('[data-testid="entity-icon"][data-key="FIXTUREUP"]')).toHaveCount(1);
    await expect(stockIcons(rows.nth(1))).toHaveCount(1); // no ticker: the icon is keyed by the company name
    await expect(rows.nth(0)).toContainText("You hold");
    await expect(rows.nth(0)).toContainText("Q3 FY26");

    await rows.nth(0).getByTestId("filing-insight-toggle").click();
    const insight = rows.nth(0).getByTestId("filing-insight");
    await expect(insight.getByTestId("filing-insight-one")).toHaveText("Fixture one-line read, in full.");
    await expect(insight).toContainText("Confidence 85%"); // 0.85 in the response
    await expect(insight.getByTestId("filing-insight-section")).toHaveCount(1);
    await expect(insight).toContainText("Fixture item two");
    await expect(insight.getByRole("link", { name: "pp. 2-3" })).toHaveAttribute("href", "https://example.test/f1.pdf#page=2");
    await shot(page, "filings");
    await insight.getByTestId("filing-insight-tab-Potential Risks").click();
    await expect(insight).toContainText("Fixture risk");
    await expect(insight).not.toContainText("Fixture item two");
    await expect(insight).toContainText("Fixture disclaimer.");
    await rows.nth(0).getByTestId("filing-insight-toggle").click();
    await expect(insight).toHaveCount(0);

    // A filing with no generated read says so.
    await rows.nth(1).getByTestId("filing-insight-toggle").click();
    await expect(rows.nth(1).getByTestId("filing-insight-none")).toBeVisible();

    await rows.nth(0).getByTestId("filing-ask").click();
    await expect.poll(() => sent).toEqual(["What does the latest Fixture Gainer Ltd filing mean for shareholders?"]);
  });

  test("empty and error states", async ({ page }) => {
    await setup(page);
    await json(page, "**/api/filings/feed*", { ok: true, total: 0, facets: {}, rows: [] });
    await page.goto(`${APP}/tool/research`);
    await expect(page.getByTestId("filings-feed")).toContainText("No filings match");
    await json(page, "**/api/filings/feed*", { detail: "boom" }, 500);
    await page.goto(`${APP}/tool/research`);
    await expect(page.getByText("Filings didn’t load")).toBeVisible(SLOW);
  });
});

test.describe("Markets — phone (390×844)", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("no tab makes the page scroll sideways, with every block populated", async ({ page }) => {
    test.setTimeout(90_000);
    await setup(page);
    await mockCalendar(page, CALENDAR);
    await json(page, "**/api/filings/feed*", FEED);
    await json(page, "**/api/filings/*/insights", INSIGHT);

    const sideways = async (where: string) => {
      await page.waitForLoadState("networkidle");
      const over = await page.evaluate(() => {
        const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
        return {
          doc: document.documentElement.scrollWidth - document.documentElement.clientWidth,
          scroll: sc ? sc.scrollWidth - sc.clientWidth : 0,
        };
      });
      expect.soft(over.doc, `${where}: page scrolls sideways`).toBeLessThanOrEqual(1);
      expect.soft(over.scroll, `${where}: content area scrolls sideways`).toBeLessThanOrEqual(1);
    };

    await page.goto(`${APP}/tool/markets`);
    await expect(page.getByTestId("markets-movers")).toBeVisible();
    await page.getByTestId("markets-list-most_active").click();
    await expect(page.getByTestId("markets-list-table")).toBeVisible();
    await sideways("market");
    await shot(page, "phone-market");

    await page.getByTestId("markets-tab-sectors").click();
    await page.getByTestId("markets-sectors").getByRole("row").nth(1).click();
    await expect(page.getByTestId("markets-sector-companies")).toBeVisible();
    await sideways("sectors");
    await shot(page, "phone-sectors");

    await page.getByTestId("markets-tab-earnings").click();
    await expect(page.getByTestId("markets-earnings-holdings-quarter")).toBeVisible();
    await page.getByTestId("markets-earnings-sectors").getByRole("row").nth(1).click();
    await expect(page.getByTestId("markets-earnings-companies")).toBeVisible();
    await sideways("earnings");
    await shot(page, "phone-earnings");

    await page.getByTestId("markets-tab-flows").click();
    await expect(page.getByTestId("markets-flows-chart")).toBeVisible();
    await expect(page.getByTestId("markets-flows-bar")).toHaveCount(10); // a phone draws the latest 10 of the 12 sessions
    await sideways("flows");
    await shot(page, "phone-flows");

    await page.getByTestId("markets-tab-actions").click();
    await expect(page.getByTestId("markets-actions-holdings-table")).toBeVisible();
    await sideways("actions");
    await shot(page, "phone-actions");

    await page.getByTestId("markets-tab-articles").click();
    await expect(page.getByTestId("markets-article").first()).toBeVisible();
    await sideways("articles");
    await shot(page, "phone-articles");

    await page.getByTestId("markets-tab-brief").click();
    await expect(page.getByTestId("markets-brief-movers")).toBeVisible();
    await sideways("brief");
    await shot(page, "phone-brief");

    await page.goto(`${APP}/tool/research`);
    await page.getByTestId("filing-row").first().getByTestId("filing-insight-toggle").click();
    await expect(page.getByTestId("filing-insight-one")).toBeVisible();
    await sideways("filings feed");
    await shot(page, "phone-filings");
  });
});
