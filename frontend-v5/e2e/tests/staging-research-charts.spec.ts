/**
 * Research → Charts on REAL staging (TC-15..TC-19, TC-21, TC-23 in test_reports/charting_v1_app_surface.md). No mocks:
 * the page runs against the staging API, and every checked value is compared with the payload the page itself received.
 *
 * Needs an allowlisted owner session: STAGING_SESSION_FILE=<file holding the session_token>. Skipped without it.
 * The drawing test creates one horizontal line on the owner's account and deletes it again.
 */
import { test, expect, type Page, type Response } from "@playwright/test";
import fs from "fs";

const UI = "https://staging.niveshcopilot.com:8443";
const FILE = process.env.STAGING_SESSION_FILE;

test.skip(!FILE, "STAGING_SESSION_FILE not set");
test.describe.configure({ mode: "serial" });

async function login(page: Page) {
  const token = fs.readFileSync(FILE as string, "utf-8").trim();
  await page.context().addCookies([{ name: "session_token", value: token, domain: "staging.niveshcopilot.com", path: "/", secure: true, httpOnly: true }]);
}
const is = (r: Response, path: string) => r.url().includes(path) && r.status() === 200;

/** Open Research → Charts and return the symbols, ohlcv and patterns payloads the page received. */
async function openCharts(page: Page) {
  await login(page);
  await page.goto(`${UI}/v5/research`);
  const symbolsP = page.waitForResponse((r) => is(r, "/api/research/chart/symbols"));
  const ohlcvP = page.waitForResponse((r) => r.url().includes("/api/research/chart/") && r.url().includes("/ohlcv") && r.status() === 200);
  const patternsP = page.waitForResponse((r) => r.url().includes("/api/research/chart/") && r.url().includes("/patterns") && r.status() === 200);
  const indicatorsP = page.waitForResponse((r) => r.url().includes("/api/research/chart/") && r.url().includes("/indicators") && r.status() === 200);
  await page.getByTestId("rail-charts").click();
  const symbols = await (await symbolsP).json();
  const ohlcv = await (await ohlcvP).json();
  const patterns = await (await patternsP).json();
  const indicators = await (await indicatorsP).json();
  await expect(page.getByTestId("charts-screen")).toBeVisible();
  return { symbols, ohlcv, patterns, indicators };
}

/** Same chain-grouping the app uses (contract.ts `groupSrBands`, §38.15 item 8) — reimplemented locally rather than
 *  imported, since this spec runs through Playwright's own module loader (no `@/...` alias resolution configured
 *  for e2e/, and this file must still fail closed with `test.skip` rather than an import error when no staging
 *  session is configured). Keep in sync with contract.ts if the tolerance or grouping rule changes. */
function expectedSrBandCount(levels: Array<{ levels?: { level?: number | null; kind?: string | null } }>, atr14: number | null): number {
  const rows = levels
    .map((p) => ({ price: p.levels?.level, kind: String(p.levels?.kind ?? "").toUpperCase() }))
    .filter((r): r is { price: number; kind: string } => typeof r.price === "number" && (r.kind === "SUPPORT" || r.kind === "RESISTANCE"))
    .sort((a, b) => a.price - b.price);
  const tolerance = atr14 != null && atr14 > 0 ? 0.35 * atr14 : 0;
  let bands = 0, prevPrice: number | null = null;
  for (const r of rows) {
    if (prevPrice == null || r.price - prevPrice > tolerance) bands++;
    prevPrice = r.price;
  }
  return bands;
}

test("TC-15/16/17/21 real staging: symbols, candles, status chip and patterns equal the payloads", async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1440, height: 1000 });
  const { symbols, ohlcv, patterns, indicators } = await openCharts(page);

  // TC-15: every served symbol is listed, and the candles render on a real canvas
  // chart-symbol-<SYM> rows only — the prefix also matches the list container and the search box
  const symbolRows = page.locator('[data-testid^="chart-symbol-"]:not([data-testid="chart-symbol-list"]):not([data-testid="chart-symbol-search"])');
  await expect(symbolRows).toHaveCount(symbols.symbols.length);
  await expect(page.getByTestId("chart-canvas").locator("canvas").first()).toBeVisible();
  expect(ohlcv.bars.length).toBeGreaterThan(250);

  // TC-16: real snapshot → no synthetic-data banner
  await expect(page.getByTestId("chart-banner-fixture")).toHaveCount(0);

  // TC-17: one status chip, and the drawer shows both raw fields the API sent
  await expect(page.getByTestId("chart-status-chip")).toHaveCount(1);
  await page.getByTestId("chart-status-chip").click();
  const drawer = page.getByTestId("chart-provenance-drawer");
  await expect(drawer).toContainText(ohlcv.data_quality_status);
  await expect(drawer).toContainText(ohlcv.pit_status);

  // TC-29: the Patterns panel lists chart patterns only; support/resistance levels are a layer, ticked by default,
  // drawing one line per served level (both kinds). With no chart patterns the panel shows its empty state.
  type P = { pattern_type: string; levels?: { level?: number | null; kind?: string | null } };
  const served = patterns.patterns as P[];
  const chartPatterns = served.filter((p) => p.pattern_type !== "SUPPORT_RESISTANCE");
  const levelRecords = served.filter((p) => p.pattern_type === "SUPPORT_RESISTANCE"
    && typeof p.levels?.level === "number" && ["SUPPORT", "RESISTANCE"].includes(String(p.levels?.kind).toUpperCase()));
  await expect(page.locator('[data-testid^="chart-pattern-row-"]')).toHaveCount(chartPatterns.length);
  if (chartPatterns.length === 0) await expect(page.getByTestId("chart-patterns-empty")).toBeVisible();
  await expect(page.getByTestId("chart-patterns-panel")).not.toContainText("SUPPORT_RESISTANCE");
  await expect(page.getByTestId("chart-sr-toggle")).toBeChecked();
  // §38.15 item 8: the drawn line count is the GROUPED band count, not the raw record count — near-duplicate
  // levels within 0.35*ATR(14) collapse into one band (contract.ts groupSrBands / expectedSrBandCount above).
  type IndRow = [string, ...number[]];
  const atr14Rows = (indicators?.indicators?.atr_14?.values ?? []) as IndRow[];
  const atr14 = atr14Rows.length ? (atr14Rows[atr14Rows.length - 1][1] as number) : null;
  await expect.poll(async () => Number(await page.getByTestId("chart-canvas").getAttribute("data-rendered-levels")))
    .toBe(expectedSrBandCount(levelRecords, atr14 ?? null));

  // TC-21: licence attribution
  await expect(page.getByTestId("chart-tv-attribution")).toBeVisible();

  const text = await page.getByTestId("charts-screen").innerText();
  expect(text).not.toMatch(/NaN|undefined|\[object Object\]|Infinity/);
});

test("TC-18 real staging: weekly and monthly are disabled with a reason; daily is active", async ({ page }) => {
  await openCharts(page);
  await expect(page.getByTestId("chart-timeframe-weekly")).toBeDisabled();
  await expect(page.getByTestId("chart-timeframe-monthly")).toBeDisabled();
  await expect(page.getByTestId("chart-timeframe-reason")).toBeVisible();
  await expect(page.getByTestId("chart-timeframe-daily")).toBeEnabled();
});

test("TC-19 real staging: bollinger draws exactly its three plotted fields from the real payload", async ({ page }) => {
  await openCharts(page);
  const canvas = page.getByTestId("chart-canvas");
  const drawn = async () => ((await canvas.getAttribute("data-rendered-series")) ?? "").split(",").filter(Boolean);
  await page.getByTestId("chart-indicator-toggle-bollinger").check();
  await expect.poll(drawn).toEqual(["bollinger:bb_mid", "bollinger:bb_upper", "bollinger:bb_lower"]);
});

test("TC-23 real staging: a horizontal line persists through reload and is deleted again", async ({ page }) => {
  test.setTimeout(120_000);
  await openCharts(page);
  const postP = page.waitForResponse((r) => r.url().endsWith("/api/research/drawings") && r.request().method() === "POST");
  await page.getByTestId("chart-tool-horizontal").click();
  const box = await page.getByTestId("chart-canvas").boundingBox();
  if (!box) throw new Error("chart canvas has no bounding box");
  await page.mouse.click(box.x + box.width * 0.5, box.y + box.height * 0.4);
  const post = await postP;
  expect(post.status()).toBe(201);
  const created = await post.json();
  await expect(page.getByTestId(`chart-drawing-row-${created.drawing_id}`)).toBeVisible();

  // Persists: a fresh page load lists it from the real API
  await page.reload();
  await page.getByTestId("rail-charts").click();
  await expect(page.getByTestId(`chart-drawing-row-${created.drawing_id}`)).toBeVisible({ timeout: 20_000 });

  // Clean up through the UI; the API must confirm the delete
  const delP = page.waitForResponse((r) => r.url().includes(`/api/research/drawings/${created.drawing_id}`) && r.request().method() === "DELETE");
  await page.getByTestId(`chart-drawing-delete-${created.drawing_id}`).click();
  expect((await delP).status()).toBe(200);
  await expect(page.getByTestId(`chart-drawing-row-${created.drawing_id}`)).toHaveCount(0);
});
