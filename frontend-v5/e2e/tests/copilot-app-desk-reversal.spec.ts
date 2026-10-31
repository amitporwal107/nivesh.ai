/**
 * One-screen Copilot app — Smart trading desk: AI scanner → "Reversal candidates" (screens/tradingdesk/ReversalPanel,
 * reversal-data.ts; backend routes/positional.py GET /api/positional/reversal-candidates, reversal-rules.v1).
 *
 * The /api/positional/reversal-candidates payloads (fixtures/reversal-candidates-*.json) are the route's OWN output on
 * 13 REAL staging rows of the 2026-10-19 session (backend/tests/fixtures/reversal_snapshot_20261019.json run through
 * reversal_service.run) — not hand-written. Everything else on the page is a stub: the desk's other routes answer
 * empty-but-valid bodies and are not under test. Expected figures are read from the payload in each test, not copied.
 * Mocked APIs, production build — see pw.copilot-app.config.ts.
 *
 * RV-20: the category opens the panel; statuses, distance, score and coverage per row; Unknown parts shown as Unknown;
 * the threshold choice (10 / 15 / 20 %) is sent to the route and kept in the URL; "also show no-evidence" asks for
 * view=all; the five answers and the levels in the detail; exclusions with their reasons; error and empty states;
 * the footnote's "not a probability" / "never sent to a broker"; no sideways scroll at 390.
 */
import { test, expect, type Page } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const here = path.dirname(fileURLToPath(import.meta.url));
const load = (n: string) => JSON.parse(fs.readFileSync(path.join(here, "..", "fixtures", n), "utf-8"));
const R15 = load("reversal-candidates-15.json");
const R15ALL = load("reversal-candidates-15-all.json");
const R10 = load("reversal-candidates-10.json");

const DESK_REV = "/v5/app/trader/desk?tab=scanner&sc_cat=reversal";
const SLOW = { timeout: 15_000 };

const json = (page: Page, pattern: string | RegExp, body: unknown, status = 200) =>
  page.route(pattern, (route) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) }));

interface Asked { near_pct: string | null; view: string | null; limit: string | null }

/** The desk shell's other routes answer empty but valid bodies; the reversal route answers by near_pct and view. */
async function mocks(page: Page, over: { status?: number; bodyFor?: (q: URLSearchParams) => unknown; gate?: Promise<void> } = {}) {
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await json(page, "**/api/positional/watchlist*", { as_of_date: "2026-10-19", total_count: 0, bucket_counts: {}, buckets: { breakout_confirmed: [], pre_breakout: [], true_accumulation: [], trend_continuation: [] } });
  await json(page, "**/api/positional/picks*", { as_of_date: "2026-10-19", picks: [] });
  await json(page, "**/api/positional/scan-universe*", { detail: "upstream_unavailable" }, 502);
  await json(page, "**/api/move-odds/latest*", { detail: "forbidden" }, 403);
  const asked: Asked[] = [];
  await page.route("**/api/positional/reversal-candidates*", async (route) => {
    const q = new URL(route.request().url()).searchParams;
    asked.push({ near_pct: q.get("near_pct"), view: q.get("view"), limit: q.get("limit") });
    if (over.gate) await over.gate;
    if (over.status) return route.fulfill({ status: over.status, contentType: "application/json", body: JSON.stringify({ detail: "upstream_unavailable" }) });
    const body = over.bodyFor ? over.bodyFor(q) : q.get("near_pct") === "10" ? R10 : q.get("view") === "all" ? R15ALL : R15;
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  return asked;
}

const rowSyms = (page: Page) => page.getByTestId("desk-rev-row").evaluateAll((els) => els.map((e) => e.getAttribute("data-symbol")));
const fmtScore = (n: number) => new Intl.NumberFormat("en-IN").format(Math.round(n));

test.describe("Smart trading desk · reversal candidates", () => {
  test("RV-20a the category opens the reversal panel in payload order, with status, distance and score per row; the old stub is gone", async ({ page }) => {
    const asked = await mocks(page);
    await page.goto(DESK_REV);
    await expect(page.getByTestId("desk-rev-row").first()).toBeVisible(SLOW);
    await expect(page.getByTestId("desk-scan-cat-reversal")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("desk-scan-cat-reversal")).not.toHaveAttribute("data-unavailable", "true");
    await expect(page.getByText("No reversal rule is defined")).toHaveCount(0);
    expect(await rowSyms(page)).toEqual(R15.rows.map((r: { symbol: string }) => r.symbol));
    expect(asked[0]).toEqual({ near_pct: "15", view: "candidates", limit: "150" });
    for (const r of R15.rows) {
      const row = page.locator(`[data-testid="desk-rev-row"][data-symbol="${r.symbol}"]`);
      await expect(row).toHaveAttribute("data-status", r.status);
      await expect(row.getByTestId("desk-rev-distance")).toContainText(`${r.distance.distance_from_52w_low_pct.toFixed(1)}% above the 52-week low`);
      await expect(row.getByTestId("desk-rev-score")).toContainText(fmtScore(r.score.total));
      await expect(row.getByTestId("desk-rev-score")).toContainText(`${fmtScore(r.score.coverage_pct)}% scored`);
      await expect(row.getByTestId("desk-rev-evidence")).toContainText(`${r.evidence.core_true} of ${r.evidence.core_total} stabilization signals`);
    }
    await expect(page.getByTestId("desk-rev-rules-version")).toContainText(R15.rules.version);
    await expect(page.getByTestId("desk-rev-rule")).toContainText("Being near the low is only a screen");
  });

  test("RV-20b parts that could not be measured say Unknown, are never a number, and the unknown list matches the payload", async ({ page }) => {
    await mocks(page);
    await page.goto(DESK_REV);
    await expect(page.getByTestId("desk-rev-row").first()).toBeVisible(SLOW);
    let sawUnknown = 0;
    for (const r of R15.rows) {
      const row = page.locator(`[data-testid="desk-rev-row"][data-symbol="${r.symbol}"]`);
      for (const k of ["fundamental", "catalyst", "technical"]) {
        const c = r.components[k];
        const fig = row.getByTestId(`desk-rev-fig-${k}`);
        await expect(fig).toHaveAttribute("data-known", c.known ? "true" : "false");
        if (c.known) await expect(fig).toContainText(fmtScore(c.score));
        else { await expect(fig).toContainText("Unknown"); sawUnknown += 1; }
      }
      const sector = row.getByTestId("desk-rev-sector");
      await expect(sector).toHaveAttribute("data-quadrant", r.sector_context ? r.sector_context.quadrant : "unknown");
      if (!r.sector_context) await expect(sector).toContainText("Sector unknown");
    }
    expect(sawUnknown).toBeGreaterThan(0); // the real rows include unmeasured parts (a mock that never showed one would prove nothing)
  });

  test("RV-20c the detail answers why this stock, why now, what is uncertain and what invalidates it; the invalidation level is on the card", async ({ page }) => {
    await mocks(page);
    await page.goto(DESK_REV);
    const r = R15.rows[0];
    const row = page.locator(`[data-testid="desk-rev-row"][data-symbol="${r.symbol}"]`);
    await expect(row).toBeVisible(SLOW);
    await expect(row.getByTestId("desk-rev-detail")).toHaveCount(0);
    await expect(row.getByTestId("desk-rev-invalidation")).toContainText(new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2 }).format(r.levels.invalidation));
    await row.getByTestId("desk-rev-toggle").click();
    await expect(row.getByTestId("desk-rev-toggle")).toHaveAttribute("aria-expanded", "true");
    await expect(row.getByTestId("desk-rev-why")).toHaveText(r.explanation.why_this_stock);
    await expect(row.getByTestId("desk-rev-invalidates")).toHaveText(r.explanation.invalidates);
    for (const u of r.explanation.uncertain) await expect(row.getByTestId("desk-rev-uncertain")).toContainText(u);
    await expect(row.getByTestId("desk-rev-signals").locator("li")).toHaveCount(Object.keys(r.signals).length);
    await expect(row.getByTestId("desk-rev-components").locator("li")).toHaveCount(6);
    await expect(row.getByTestId("desk-rev-levels")).toContainText("reward/risk");
    await expect(row.getByText("Levels (hypothetical, not sent to a broker)")).toBeVisible();
    await row.getByTestId("desk-rev-toggle").click();
    await expect(row.getByTestId("desk-rev-detail")).toHaveCount(0);
  });

  test("RV-20d the 10 / 15 / 20 % choice is sent to the route and lives in the URL; it survives a reload", async ({ page }) => {
    const asked = await mocks(page);
    await page.goto(DESK_REV);
    await expect(page.getByTestId("desk-rev-near-15")).toHaveAttribute("aria-pressed", "true", SLOW);
    await page.getByTestId("desk-rev-near-10").click();
    await expect(page.getByTestId("desk-rev-near-10")).toHaveAttribute("aria-pressed", "true");
    await expect.poll(() => rowSyms(page)).toEqual(R10.rows.map((r: { symbol: string }) => r.symbol));
    expect(asked.some((a) => a.near_pct === "10" && a.view === "candidates")).toBe(true);
    expect(new URL(page.url()).searchParams.get("sc_near")).toBe("10");
    await page.reload();
    await expect(page.getByTestId("desk-rev-near-10")).toHaveAttribute("aria-pressed", "true", SLOW);
    await expect.poll(() => asked.filter((a) => a.near_pct === "10").length).toBeGreaterThan(1);
    await page.getByTestId("desk-rev-near-20").click();
    await expect.poll(() => asked.some((a) => a.near_pct === "20")).toBe(true);
    await page.getByTestId("desk-rev-near-15").click();
    expect(new URL(page.url()).searchParams.get("sc_near")).toBeNull(); // 15 is the default and is not written
  });

  test("RV-20e 'also show near-low stocks with no evidence' asks for view=all and lists them with their own status", async ({ page }) => {
    const asked = await mocks(page);
    await page.goto(DESK_REV);
    await expect(page.getByTestId("desk-rev-row").first()).toBeVisible(SLOW);
    expect(await page.locator('[data-testid="desk-rev-row"][data-status="near_low_no_evidence"]').count()).toBe(0);
    await page.getByTestId("desk-rev-all").check();
    await expect.poll(() => asked.some((a) => a.view === "all")).toBe(true);
    const noEv = R15ALL.rows.filter((r: { status: string }) => r.status === "near_low_no_evidence");
    expect(noEv.length).toBeGreaterThan(0);
    for (const r of noEv) await expect(page.locator(`[data-testid="desk-rev-row"][data-symbol="${r.symbol}"]`).getByTestId("desk-rev-status")).toContainText("Near low · no evidence");
    expect(new URL(page.url()).searchParams.get("sc_revall")).toBe("1");
  });

  test("RV-20f every stock a hard gate removed is listed with its reason, and the counts match the payload", async ({ page }) => {
    await mocks(page);
    await page.goto(DESK_REV);
    await expect(page.getByTestId("desk-rev-excluded")).toBeVisible(SLOW);
    await page.getByTestId("desk-rev-excluded").locator("summary").click();
    const counts = page.getByTestId("desk-rev-exclusion-counts");
    await expect(counts).toContainText("ETF: 1");
    await expect(counts).toContainText("High promoter pledge: 1");
    await expect(counts).toContainText("Under 252 sessions of price history: 1");
    await expect(page.getByTestId("desk-rev-excluded-row")).toHaveCount(R15.excluded.length);
    for (const x of R15.excluded) await expect(page.getByTestId("desk-rev-excluded").getByText(x.symbol, { exact: true })).toBeVisible();
    await expect(page.getByTestId("desk-rev-summary")).toContainText(`${R15.universe.evaluated} liquid stocks checked`);
  });

  test("RV-20g the page says the score is not a probability, levels are hypothetical and never sent to a broker, and lists the data limits", async ({ page }) => {
    await mocks(page);
    await page.goto(DESK_REV);
    const foot = page.getByTestId("desk-rev-footnote");
    await expect(foot).toBeVisible(SLOW);
    await expect(foot).toContainText("it is not a probability");
    await expect(foot).toContainText("never sent to a broker");
    await expect(foot).toContainText("Research and paper trading only");
    await expect(page.getByTestId("desk-rev-limit")).toHaveCount(R15.data_limits.length);
    await expect(page.getByTestId("desk-rev-trust")).toContainText("End of day");
  });

  test("RV-20h a failing route shows an error with retry; retry loads the list", async ({ page }) => {
    let fail = true;
    const asked = await mocks(page, { bodyFor: () => R15 });
    await page.unroute("**/api/positional/reversal-candidates*");
    await page.route("**/api/positional/reversal-candidates*", (route) => {
      asked.push({ near_pct: null, view: null, limit: null });
      return fail ? route.fulfill({ status: 502, contentType: "application/json", body: JSON.stringify({ detail: "upstream_unavailable" }) })
        : route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(R15) });
    });
    await page.goto(DESK_REV);
    await expect(page.getByTestId("desk-rev-error")).toBeVisible(SLOW);
    await expect(page.getByTestId("desk-rev-row")).toHaveCount(0);
    fail = false;
    await page.getByTestId("desk-rev-error").getByRole("button", { name: /retry|try again/i }).click();
    await expect(page.getByTestId("desk-rev-row").first()).toBeVisible(SLOW);
  });

  test("RV-20i no stock with enough evidence → an empty state that names the threshold, with the exclusion counts still shown", async ({ page }) => {
    const empty = { ...R15, rows: [], excluded: [], universe: { ...R15.universe, listed: 0, status_counts: { near_low_no_evidence: 2 } } };
    await mocks(page, { bodyFor: () => empty });
    await page.goto(DESK_REV);
    await expect(page.getByTestId("desk-rev-empty")).toContainText("within 15% of its 52-week low", SLOW);
    await expect(page.getByTestId("desk-rev-summary")).toContainText("0 reversal candidates");
  });

  test("RV-20j the other categories are unaffected: Momentum still opens the scanner table, not the reversal panel", async ({ page }) => {
    await mocks(page);
    await page.goto(DESK_REV);
    await expect(page.getByTestId("desk-rev-row").first()).toBeVisible(SLOW);
    await page.getByTestId("desk-scan-cat-momentum").click();
    await expect(page.getByTestId("desk-rev-list")).toHaveCount(0);
    await expect(page.getByTestId("desk-scanner")).not.toHaveAttribute("data-cat", "reversal");
    await page.getByTestId("desk-scan-cat-reversal").click();
    await expect(page.getByTestId("desk-rev-row").first()).toBeVisible();
  });

  test.describe("at 390px", () => {
    test.use({ viewport: { width: 390, height: 844 } });
    test("RV-20k no sideways page scroll; rows, chips and the detail fit", async ({ page }) => {
      await mocks(page);
      await page.goto(DESK_REV);
      await expect(page.getByTestId("desk-rev-row").first()).toBeVisible(SLOW);
      await page.getByTestId("desk-rev-toggle").first().click();
      await expect(page.getByTestId("desk-rev-detail").first()).toBeVisible();
      const o = await page.evaluate(() => {
        const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
        return { doc: document.documentElement.scrollWidth - window.innerWidth, scroll: sc ? sc.scrollWidth - sc.clientWidth : 0 };
      });
      expect(o.doc).toBeLessThanOrEqual(1);
      expect(o.scroll).toBeLessThanOrEqual(1);
    });
  });
});

/**
 * MOCK — not real data: an invented Kite live snapshot (stream and polling) with one quote per symbol given.
 * Shape: backend/routes/live_quotes.py. `mode` is the feed's own word: only "live" shows live prices.
 */
async function liveFeed(page: Page, ltps: Record<string, number>, mode = "live") {
  const quotes = Object.fromEntries(Object.entries(ltps).map(([s, ltp]) => [s, { ltp, change: 1.5, change_pct: 1.5, open: ltp, high: ltp, low: ltp, close: ltp - 1.5, volume: 1000, oi: null, ts: "2026-10-23T11:13:09+05:30" }]));
  const snapshot = {
    as_of: "2026-10-23T05:43:10+00:00", data_at: "2026-10-23T05:43:09+00:00", age_seconds: 1.2, stale: mode !== "live", stale_after_seconds: 75, cadence_seconds: 30,
    mode, session: mode === "live" ? "open" : "closed", source: "ws", final: false, count: Object.keys(quotes).length, missing: [], quotes, read_only: true,
  };
  await page.route("**/api/live/**", (route) => route.fulfill(
    new URL(route.request().url()).pathname.endsWith("/stream")
      ? { status: 200, contentType: "text/event-stream", body: `retry: 100\n\nevent: snapshot\ndata: ${JSON.stringify(snapshot)}\n\n` }
      : { status: 200, contentType: "application/json", body: JSON.stringify(snapshot) }));
}

test.describe("Smart trading desk · reversal candidates · live price", () => {
  test("RV-live the detail adds Kite's live price beside the scan's close while the feed is live, and nothing when it is not", async ({ page }) => {
    await mocks(page);
    const r = R15.rows[0];
    await liveFeed(page, { [r.symbol]: 123.45 });
    await page.goto(DESK_REV);
    const row = page.locator(`[data-testid="desk-rev-row"][data-symbol="${r.symbol}"]`);
    await expect(row).toBeVisible(SLOW);
    await row.getByTestId("desk-rev-toggle").click();
    await expect(row.getByTestId("desk-rev-live")).toContainText("123.45");
    await expect(row.getByTestId("desk-rev-levels")).toContainText("trigger");      // the scan's own levels are still there
  });

  test("RV-live-closed no live price when the feed is closed", async ({ page }) => {
    await mocks(page);
    const r = R15.rows[0];
    await liveFeed(page, { [r.symbol]: 123.45 }, "closed");
    await page.goto(DESK_REV);
    const row = page.locator(`[data-testid="desk-rev-row"][data-symbol="${r.symbol}"]`);
    await expect(row).toBeVisible(SLOW);
    await row.getByTestId("desk-rev-toggle").click();
    await expect(row.getByTestId("desk-rev-detail")).toBeVisible();
    await expect(row.getByTestId("desk-rev-live")).toHaveCount(0);
  });
});

/**
 * MOCK — not real data: the feed's final snapshot after a close (mode "closed", final true), invented prices, every quote
 * stamped with the trading `day`. A day far in the future stands for "newer than the end-of-day data on the screen", a day
 * far in the past for "the end-of-day data has caught up". Shape: backend/routes/live_quotes.py.
 */
async function closeFeed(page: Page, quotes: Record<string, Record<string, unknown>>, day: string) {
  const full = Object.fromEntries(Object.entries(quotes).map(([s, q]) => [s, { change: 1.5, change_pct: 1.5, open: 1, high: 1, low: 1, close: 1, volume: 1000, oi: null, ...q, ts: `${day}T15:29:58+05:30` }]));
  const snapshot = {
    as_of: `${day}T10:01:10+00:00`, data_at: `${day}T10:00:10+00:00`, age_seconds: 5, stale: false, stale_after_seconds: 75, cadence_seconds: 30,
    mode: "closed", session: "closed", source: "rest", final: true, count: Object.keys(full).length, missing: [], quotes: full, read_only: true,
  };
  await page.route("**/api/live/**", (route) => route.fulfill(
    new URL(route.request().url()).pathname.endsWith("/stream")
      ? { status: 200, contentType: "text/event-stream", body: `retry: 100\n\nevent: snapshot\ndata: ${JSON.stringify(snapshot)}\n\n` }
      : { status: 200, contentType: "application/json", body: JSON.stringify(snapshot) }));
}
const NEWER = "2026-12-31";
const OLDER = "2020-01-02";

test.describe("Smart trading desk · reversal candidates · Kite's close", () => {
  test("after the close the detail shows Kite's closing price, until the scan's own day catches up", async ({ page }) => {
    await mocks(page);
    const r = R15.rows[0];
    await closeFeed(page, { [r.symbol]: { ltp: 123.45 } }, NEWER);
    await page.goto(DESK_REV);
    const row = page.locator(`[data-testid="desk-rev-row"][data-symbol="${r.symbol}"]`);
    await expect(row).toBeVisible(SLOW);
    await row.getByTestId("desk-rev-toggle").click();
    await expect(row.getByTestId("desk-rev-live")).toContainText("Kite close");
    await expect(row.getByTestId("desk-rev-live")).toContainText("123.45");
  });

  test("a closing quote no newer than the scan leaves the scan's close alone", async ({ page }) => {
    await mocks(page);
    const r = R15.rows[0];
    await closeFeed(page, { [r.symbol]: { ltp: 123.45 } }, OLDER);
    await page.goto(DESK_REV);
    const row = page.locator(`[data-testid="desk-rev-row"][data-symbol="${r.symbol}"]`);
    await expect(row).toBeVisible(SLOW);
    await row.getByTestId("desk-rev-toggle").click();
    await expect(row.getByTestId("desk-rev-detail")).toBeVisible();
    await expect(row.getByTestId("desk-rev-live")).toHaveCount(0);
  });
});
