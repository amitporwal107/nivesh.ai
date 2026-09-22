/**
 * Research → Charts (mocked layer). Covers TC-15..TC-21 and TC-23 from
 * test_reports/charting_v1_app_surface.md. TC-22 (bundle code-split) is a build-output check, not a Playwright
 * test — see the "Verify" section of the task and the `npx vite build` output pasted in the final report.
 *
 * MOCK — not real data: every /api/research/chart/* and /api/research/drawings response here is a fixture
 * (e2e/fixtures/research-chart-*.json, e2e/fixtures/user-profile-charting.json), shaped to
 * research/charting/SNAPSHOT_SCHEMA.md. The RELIANCE pattern in research-chart-patterns-RELIANCE.json is entirely
 * synthetic — the pattern detectors are not built yet (v1 batch 2 ships them empty) — invented ONLY to exercise
 * the pattern-overlay / score-meter / rule-drawer UI locally. auth/me is mocked too. Staging verification with a
 * real session is a separate, later step (see the final report).
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { mockAuthAs } from "../helpers/api-mock";

const FX = path.join(process.cwd(), "e2e", "fixtures");
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(FX, name), "utf-8"));

type Reply = { status: number; body: unknown };
const postedDrawings: Array<Record<string, unknown>> = [];
const deletedDrawingIds: string[] = [];

/** Per-symbol drawings state so a POST during the test is visible to a later GET (e.g. after reload). */
function makeDrawingsStore() {
  const bySymbol = new Map<string, Array<Record<string, unknown>>>();
  bySymbol.set("RELIANCE", []);
  bySymbol.set("TCS", []);
  return bySymbol;
}

async function mockCharts(page: Page, opts?: { run?: () => Reply; symbols?: () => Reply; ohlcv?: (sym: string) => Reply | undefined; drawingsStore?: Map<string, Array<Record<string, unknown>>> }) {
  const store = opts?.drawingsStore ?? makeDrawingsStore();

  await page.route("**/api/research/chart/run", (route) => {
    const r = opts?.run ? opts.run() : { status: 200, body: load("research-chart-run.json") };
    return route.fulfill({ status: r.status, contentType: "application/json", body: JSON.stringify(r.body) });
  });
  await page.route("**/api/research/chart/symbols", (route) => {
    const r = opts?.symbols ? opts.symbols() : { status: 200, body: load("research-chart-symbols.json") };
    return route.fulfill({ status: r.status, contentType: "application/json", body: JSON.stringify(r.body) });
  });
  await page.route("**/api/research/chart/*/ohlcv", (route) => {
    const sym = decodeURIComponent(new URL(route.request().url()).pathname.split("/").slice(-2, -1)[0]);
    const custom = opts?.ohlcv?.(sym);
    const r = custom ?? { status: 200, body: load(`research-chart-ohlcv-${sym}.json`) };
    return route.fulfill({ status: r.status, contentType: "application/json", body: JSON.stringify(r.body) });
  });
  await page.route("**/api/research/chart/*/indicators*", (route) => {
    const sym = decodeURIComponent(new URL(route.request().url()).pathname.split("/").slice(-2, -1)[0]);
    const body = load(`research-chart-indicators-${sym}.json`);
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.route("**/api/research/chart/*/patterns", (route) => {
    const sym = decodeURIComponent(new URL(route.request().url()).pathname.split("/").slice(-2, -1)[0]);
    const body = load(`research-chart-patterns-${sym}.json`);
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.route("**/api/research/drawings**", async (route: Route) => {
    const req = route.request();
    const url = new URL(req.url());
    if (req.method() === "GET") {
      const sym = url.searchParams.get("symbol") ?? "";
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(store.get(sym) ?? []) });
    }
    if (req.method() === "POST") {
      const payload = req.postDataJSON() as Record<string, unknown>;
      postedDrawings.push(payload);
      const now = new Date().toISOString();
      const created = {
        drawing_id: `drw_${postedDrawings.length}`,
        user_id: "user_ed05fb1daa45",
        symbol: payload.symbol, timeframe: payload.timeframe, drawing_type: payload.drawing_type,
        anchor_points: payload.anchor_points, style: payload.style ?? null,
        created_at: now, updated_at: now,
      };
      const list = store.get(String(payload.symbol)) ?? [];
      list.push(created);
      store.set(String(payload.symbol), list);
      return route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(created) });
    }
    if (req.method() === "DELETE") {
      const id = url.pathname.split("/").pop()!;
      deletedDrawingIds.push(id);
      for (const [sym, list] of store) store.set(sym, list.filter((d) => d.drawing_id !== id));
      return route.fulfill({ status: 204, contentType: "application/json", body: "" });
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
  });

  return store;
}

/**
 * The right sidebar has LEVELS / INDICATORS / PATTERNS tabs (W1b, §38.3 item 6 and the 1A design), so a test
 * opens the tab that owns the control it addresses. Patterns is the default open tab.
 */
async function openSidebarTab(page: Page, tab: "levels" | "indicators" | "patterns") {
  await page.getByTestId(`chart-sidebar-tab-${tab}`).click();
  await expect(page.getByTestId(`chart-sidebar-tab-${tab}`)).toHaveAttribute("aria-selected", "true");
}

async function openCharts(page: Page) {
  await page.goto("/v5/research");
  await page.getByTestId("rail-charts").click();
  await expect(page.getByTestId("charts-screen")).toBeVisible();
}

test.describe("Charts — access", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("without the charting feature the rail item is absent", async ({ page }) => {
    await mockAuthAs(page, "user-profile-onboarded.json");
    await mockCharts(page);
    await page.goto("/v5/research");
    await expect(page.getByTestId("rail-feed")).toBeVisible();
    await expect(page.getByTestId("rail-charts")).toHaveCount(0);
    await expect(page.getByTestId("charts-screen")).toHaveCount(0);
  });

  test("TC-20 a 403 from the API shows the explicit not-enabled state, no crash, no canvas", async ({ page }) => {
    await mockAuthAs(page, "user-profile-charting.json");
    await mockCharts(page, { run: () => ({ status: 403, body: { detail: "feature_not_enabled" } }) });
    await openCharts(page);
    const state = page.getByTestId("charts-state-no_access");
    await expect(state).toBeVisible();
    await expect(state).toContainText("Charts is not enabled for your account");
    await expect(page.getByTestId("chart-canvas")).toHaveCount(0);
  });

  test("a 503 from the API shows the unavailable state with a retry, no crash", async ({ page }) => {
    await mockAuthAs(page, "user-profile-charting.json");
    await mockCharts(page, { run: () => ({ status: 503, body: { detail: "snapshot_unavailable" } }) });
    await openCharts(page);
    await expect(page.getByTestId("charts-state-unavailable")).toContainText("Chart snapshot unavailable");
    await expect(page.getByTestId("charts-retry")).toBeVisible();
  });
});

test.describe("Charts — chart surface", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test.beforeEach(async ({ page }) => {
    await mockAuthAs(page, "user-profile-charting.json");
    await mockCharts(page);
    await openCharts(page);
    await expect(page.getByTestId("chart-symbol-RELIANCE")).toBeVisible();
  });

  test("TC-15 picking a symbol renders candles + volume from the API (non-empty canvas)", async ({ page }) => {
    await page.getByTestId("chart-symbol-RELIANCE").click();
    const canvasHost = page.getByTestId("chart-canvas");
    await expect(canvasHost).toBeVisible();
    const canvases = canvasHost.locator("canvas");
    await expect(canvases.first()).toBeVisible();
    expect(await canvases.count()).toBeGreaterThan(0);
    const box = await canvasHost.boundingBox();
    expect(box?.width).toBeGreaterThan(100);
    expect(box?.height).toBeGreaterThan(100);
    // a real draw happened — the offscreen bitmap isn't fully transparent
    const nonEmpty = await canvases.first().evaluate((el: HTMLCanvasElement) => {
      const ctx = el.getContext("2d");
      if (!ctx) return false;
      const data = ctx.getImageData(0, 0, el.width, el.height).data;
      for (let i = 3; i < data.length; i += 4 * 37) if (data[i] !== 0) return true;
      return false;
    });
    expect(nonEmpty).toBe(true);
  });

  test("TC-16 fixture:true shows the loud synthetic-data banner", async ({ page }) => {
    const banner = page.getByTestId("chart-banner-fixture");
    await expect(banner).toBeVisible();
    await expect(banner).toContainText("SYNTHETIC DEVELOPMENT DATA");
    await expect(banner).toContainText("not real market data");
  });

  test("TC-21 TradingView attribution is visible in the chart area", async ({ page }) => {
    const attr = page.getByTestId("chart-tv-attribution");
    await expect(attr).toBeVisible();
    await expect(attr).toHaveAttribute("href", /tradingview\.com/);
  });

  // Replaces the former "weekly/monthly are disabled (spec G-6)" test. §38.7 resamples weekly and monthly bars
  // into the snapshot and §38.11 serves them, so the intervals are enabled for DISPLAY now (§38.19.2
  // "corrections carried into W1"); only detection on those intervals stays daily-only. The older-backend
  // behaviour is covered by its own degrade test below.
  test("TC-18 the interval group switches between daily, weekly and monthly", async ({ page }) => {
    const daily = page.getByTestId("chart-timeframe-daily");
    const weekly = page.getByTestId("chart-timeframe-weekly");
    const monthly = page.getByTestId("chart-timeframe-monthly");
    await expect(daily).toHaveAttribute("aria-pressed", "true");
    await expect(weekly).toBeEnabled();
    await expect(monthly).toBeEnabled();

    const requests: string[] = [];
    page.on("request", (r) => { if (r.url().includes("/ohlcv")) requests.push(r.url()); });

    await weekly.click();
    await expect(weekly).toHaveAttribute("aria-pressed", "true");
    await expect(daily).toHaveAttribute("aria-pressed", "false");
    await expect.poll(() => requests.some((u) => u.includes("timeframe=1W"))).toBe(true);
    // Detection is daily-only, and the Patterns panel says so instead of leaving an unexplained empty chart.
    await expect(page.getByTestId("chart-patterns-daily-only")).toBeVisible();

    await daily.click();
    await expect(daily).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("chart-patterns-daily-only")).toHaveCount(0);
  });

  test("TC-18b an older backend without weekly/monthly degrades to daily with the reason, not an error", async ({ page }) => {
    // A backend deployed before the §38.7 export answers 400 `unknown_timeframe: 1W`.
    await page.route("**/api/research/chart/*/ohlcv**", async (route) => {
      const url = new URL(route.request().url());
      if (url.searchParams.get("timeframe")) {
        return route.fulfill({ status: 400, contentType: "application/json", body: JSON.stringify({ detail: `unknown_timeframe: ${url.searchParams.get("timeframe")}` }) });
      }
      const sym = decodeURIComponent(url.pathname.split("/").slice(-2, -1)[0]);
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(load(`research-chart-ohlcv-${sym}.json`)) });
    });
    await page.getByTestId("chart-timeframe-weekly").click();
    await expect(page.getByTestId("chart-timeframe-weekly")).toBeDisabled();
    await expect(page.getByTestId("chart-timeframe-monthly")).toBeDisabled();
    await expect(page.getByTestId("chart-timeframe-reason")).toContainText("coming with W2");
    await expect(page.getByTestId("chart-timeframe-daily")).toHaveAttribute("aria-pressed", "true");
    // the daily chart is still there — this is a capability gap, not a failure
    await expect(page.getByTestId("charts-state-error")).toHaveCount(0);
    await expect(page.getByTestId("chart-canvas").locator("canvas").first()).toBeVisible();
  });

  test("empty patterns render cleanly (TCS — detectors not built yet)", async ({ page }) => {
    await page.getByTestId("chart-symbol-TCS").click();
    await expect(page.getByTestId("chart-patterns-empty")).toBeVisible();
    await expect(page.getByTestId("chart-canvas").locator("canvas").first()).toBeVisible();
  });

  test("a pattern's levels, rules and scores render, with the 'not a probability' label", async ({ page }) => {
    const row = page.getByTestId("chart-pattern-row-RELIANCE:RECTANGLE:2026-08-24");
    await expect(row).toBeVisible();
    await row.getByRole("button").click();
    await expect(page.getByTestId("chart-pattern-rule-RECT_MIN_TOUCHES")).toBeVisible();
    const scores = page.getByTestId("chart-scores");
    await expect(scores).toBeVisible();
    for (const k of ["formation", "readiness", "confirmation", "failure_risk"]) {
      await expect(page.getByTestId(`chart-score-${k}`)).toBeVisible();
    }
    await expect(scores).toContainText("score, not a probability");
    // clicking a rule opens the provenance drawer with that rule's result
    await page.getByTestId("chart-pattern-rule-RECT_MIN_TOUCHES").click();
    await expect(page.getByTestId("chart-provenance-drawer")).toBeVisible();
    await expect(page.getByTestId("chart-provenance-drawer")).toContainText("PASS");
  });
});

test.describe("Charts — support & resistance layer; patterns panel = chart patterns only (TC-25..TC-28)", () => {
  // Owner feedback 2026-09-22 (ADANIENT on staging): six identical "SUPPORT_RESISTANCE confirmed" rows. Levels are not chart
  // patterns — they are a layer, ticked by default; the Patterns panel lists only chart patterns and is blank when there are none.
  test.use({ viewport: { width: 1280, height: 800 } });
  test.beforeEach(async ({ page }) => {
    await mockAuthAs(page, "user-profile-charting.json");
    await mockCharts(page);
    await openCharts(page);
    await expect(page.getByTestId("chart-canvas").locator("canvas").first()).toBeVisible();
  });
  const drawnLevels = async (page: Page) => Number((await page.getByTestId("chart-canvas").getAttribute("data-rendered-levels")) ?? "-1");

  test("TC-25 the Patterns panel lists chart patterns only — no support/resistance rows", async ({ page }) => {
    const rows = page.locator('[data-testid^="chart-pattern-row-"]');
    await expect(rows).toHaveCount(2); // RELIANCE fixture: rectangle + HH_HL (+ 2 levels that must NOT be rows)
    await expect(page.locator('[data-testid^="chart-pattern-row-RELIANCE:SUPPORT_RESISTANCE"]')).toHaveCount(0);
    await expect(page.getByTestId("chart-patterns-panel")).not.toContainText("SUPPORT_RESISTANCE");
  });

  test("TC-26 a symbol with only levels shows an empty Patterns panel", async ({ page }) => {
    await page.getByTestId("chart-symbol-TCS").click();
    await expect(page.getByTestId("chart-patterns-empty")).toBeVisible();
    await expect(page.locator('[data-testid^="chart-pattern-row-"]')).toHaveCount(0);
    await openSidebarTab(page, "levels");
    await expect(page.getByTestId("chart-sr-count")).toHaveText("2 levels");
  });

  test("TC-27 Support & resistance is ticked by default, draws every level (both kinds), and untick removes them", async ({ page }) => {
    await openSidebarTab(page, "levels");
    await expect(page.getByTestId("chart-sr-toggle")).toBeChecked();
    await expect.poll(() => drawnLevels(page)).toBe(2); // one SUPPORT + one RESISTANCE
    await page.getByTestId("chart-sr-toggle").uncheck();
    await expect.poll(() => drawnLevels(page)).toBe(0);
    await page.getByTestId("chart-sr-toggle").check();
    await expect.poll(() => drawnLevels(page)).toBe(2);
    // switching symbol keeps the default: ticked, and TCS draws its own two levels
    await page.getByTestId("chart-sr-toggle").uncheck();
    await page.getByTestId("chart-symbol-TCS").click();
    await expect(page.getByTestId("chart-sr-toggle")).toBeChecked();
    await expect.poll(() => drawnLevels(page)).toBe(2);
  });

  test("TC-28 labels come from status: formed is not confirmed", async ({ page }) => {
    const hh = page.getByTestId("chart-pattern-status-RELIANCE:HH_HL:2026-08-20");
    await expect(hh).toHaveText("formed");
    await expect(hh).toHaveAttribute("data-category", "forming");
    const rect = page.getByTestId("chart-pattern-status-RELIANCE:RECTANGLE:2026-08-24");
    await expect(rect).toHaveText("confirmed");
    await expect(rect).toHaveAttribute("data-category", "confirmed");
  });
});

test.describe("Charts — status chip precedence (TC-17)", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("PIT_UNVERIFIED outranks PARTIAL, and the drawer shows both raw fields", async ({ page }) => {
    await mockAuthAs(page, "user-profile-charting.json");
    await mockCharts(page);
    await openCharts(page);
    await page.getByTestId("chart-symbol-TCS").click();
    const chip = page.getByTestId("chart-status-chip");
    await expect(chip).toBeVisible();
    await expect(chip).toContainText("PIT_UNVERIFIED");
    await expect(chip).not.toContainText("PARTIAL");
    await chip.click();
    const drawer = page.getByTestId("chart-provenance-drawer");
    await expect(drawer).toBeVisible();
    await expect(page.getByTestId("chart-provenance-dq")).toContainText("PARTIAL");
    await expect(page.getByTestId("chart-provenance-pit")).toContainText("PIT_UNVERIFIED");
  });

  test("VALID shows when both fields are clean", async ({ page }) => {
    await mockAuthAs(page, "user-profile-charting.json");
    await mockCharts(page);
    await openCharts(page);
    await expect(page.getByTestId("chart-status-chip")).toContainText("VALID");
  });
});

test.describe("Charts — indicators (TC-19)", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("a price-pane overlay toggles without adding a pane; a dedicated-pane indicator adds/removes one", async ({ page }) => {
    await mockAuthAs(page, "user-profile-charting.json");
    await mockCharts(page);
    await openCharts(page);
    await expect(page.getByTestId("chart-canvas").locator("canvas").first()).toBeVisible();

    const countCanvases = () => page.getByTestId("chart-canvas").locator("canvas").count();
    await openSidebarTab(page, "indicators");
    const before = await countCanvases();

    // sma_20 is pane:"price" — overlays the existing pane, canvas count is unchanged
    await page.getByTestId("chart-indicator-toggle-sma_20").check();
    await expect(page.getByTestId("chart-indicator-toggle-sma_20")).toBeChecked();
    expect(await countCanvases()).toBe(before);
    await page.getByTestId("chart-indicator-toggle-sma_20").uncheck();
    expect(await countCanvases()).toBe(before);

    // rsi_14 is pane:"rsi" — gets its own pane via addPane(), which renders more <canvas> elements
    await page.getByTestId("chart-indicator-toggle-rsi_14").check();
    await expect.poll(countCanvases).toBeGreaterThan(before);
    await page.getByTestId("chart-indicator-toggle-rsi_14").uncheck();
    await expect.poll(countCanvases).toBe(before);
  });

  test("multi-output indicators draw every plotted field, and only those (bollinger bands, macd signal + hist)", async ({ page }) => {
    await mockAuthAs(page, "user-profile-charting.json");
    await mockCharts(page);
    await openCharts(page);
    const canvas = page.getByTestId("chart-canvas");
    await expect(canvas.locator("canvas").first()).toBeVisible();
    const drawn = async () => ((await canvas.getAttribute("data-rendered-series")) ?? "").split(",").filter(Boolean);

    await openSidebarTab(page, "indicators");
    await page.getByTestId("chart-indicator-toggle-bollinger").check();
    await expect.poll(drawn).toEqual(["bollinger:bb_mid", "bollinger:bb_upper", "bollinger:bb_lower"]);
    // width/pos are on a different scale from price — listed in output_fields but not in plot_fields
    expect((await drawn()).some((t) => t.includes("bb_width") || t.includes("bb_pos"))).toBe(false);
    await page.getByTestId("chart-indicator-toggle-bollinger").uncheck();
    await expect.poll(drawn).toEqual([]);

    await page.getByTestId("chart-indicator-toggle-macd").check();
    await expect.poll(drawn).toEqual(["macd:macd", "macd:signal", "macd:hist"]);
  });

  test("provenance drawers format nested values — no [object Object] (files list, multi-output warmup)", async ({ page }) => {
    // Regression for staging 2026-09-22: manifest source.files is a list of {name, sha256} objects and macd's warmup_period
    // is a per-output dict; both rendered as "[object Object]" because the drawer stringified them.
    await mockAuthAs(page, "user-profile-charting.json");
    await mockCharts(page);
    await openCharts(page);
    await page.getByTestId("chart-status-chip").click();
    const drawer = page.getByTestId("chart-provenance-drawer");
    await expect(drawer).toContainText("part-20260919T031049.csv.gz");
    await expect(drawer).not.toContainText("[object Object]");
    await drawer.getByRole("button", { name: "Close" }).click();
    await expect(drawer).toHaveCount(0);

    await openSidebarTab(page, "indicators");
    await page.getByTestId("chart-indicator-info-macd").click();
    await expect(drawer).toContainText("signal");
    await expect(drawer).not.toContainText("[object Object]");
  });

  test("an indicator's info button opens its provenance (warmup, calculation version)", async ({ page }) => {
    await mockAuthAs(page, "user-profile-charting.json");
    await mockCharts(page);
    await openCharts(page);
    await openSidebarTab(page, "indicators");
    await page.getByTestId("chart-indicator-info-sma_20").click();
    const drawer = page.getByTestId("chart-provenance-drawer");
    await expect(drawer).toBeVisible();
    await expect(drawer).toContainText("20");
    await expect(drawer).toContainText("omit_until_warmup");
  });
});

test.describe("Charts — drawing tools (TC-23)", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("a horizontal line is placed with one click and listed", async ({ page }) => {
    postedDrawings.length = 0;
    await mockAuthAs(page, "user-profile-charting.json");
    await mockCharts(page);
    await openCharts(page);
    await expect(page.getByTestId("chart-canvas").locator("canvas").first()).toBeVisible();

    await page.getByTestId("chart-tool-horizontal").click();
    const box = (await page.getByTestId("chart-canvas").boundingBox())!;
    await page.mouse.click(box.x + box.width * 0.5, box.y + box.height * 0.4);

    await expect.poll(() => postedDrawings.length).toBe(1);
    expect(postedDrawings[0].drawing_type).toBe("HORIZONTAL_LINE");
    expect((postedDrawings[0].anchor_points as unknown[]).length).toBe(1);
    await expect(page.getByTestId("chart-drawings-list")).toContainText("Horizontal line");
  });

  test("a trendline needs two clicks, persists through reload, and is visually distinct from pattern overlays", async ({ page }) => {
    postedDrawings.length = 0;
    await mockAuthAs(page, "user-profile-charting.json");
    const store = await mockCharts(page);
    await openCharts(page);
    await expect(page.getByTestId("chart-canvas").locator("canvas").first()).toBeVisible();

    await page.getByTestId("chart-tool-trendline").click();
    const box = (await page.getByTestId("chart-canvas").boundingBox())!;
    await page.mouse.click(box.x + box.width * 0.3, box.y + box.height * 0.35);
    // one click is not enough yet
    expect(postedDrawings.length).toBe(0);
    // Lightweight Charts buffers a click briefly to disambiguate it from a double-click; two mouse.click() calls
    // fired back-to-back land inside that window and the library drops the second one. A real user's two anchor
    // clicks are never this fast, so this wait matches realistic interaction rather than working around a bug.
    await page.waitForTimeout(600);
    // y=0.5, not 0.6: W0 added a "Nearest level" readout row above the canvas (§38.15 item 9), so at this
    // describe block's 1280x800 viewport the chart-canvas element now starts far enough down the page that a
    // point 60% into its height falls below the viewport fold and Playwright's click lands on <html> instead of
    // the chart's <canvas> (chart.subscribeClick never fires) — verified by inspecting getBoundingClientRect() of
    // chart-canvas and the click target element. 0.5 stays comfortably inside the fold and is still a distinct
    // second anchor from the first click's (0.3, 0.35).
    await page.mouse.click(box.x + box.width * 0.65, box.y + box.height * 0.5);
    await expect.poll(() => postedDrawings.length).toBe(1);
    expect(postedDrawings[0].drawing_type).toBe("TRENDLINE");
    expect((postedDrawings[0].anchor_points as unknown[]).length).toBe(2);

    const drawingsList = page.getByTestId("chart-drawings-list");
    await expect(drawingsList).toContainText("Trendline");
    // Drawings live in their own DOM list with their own testid convention (chart-drawing-row-*), separate and
    // distinct from system pattern overlays (chart-pattern-row-*) — the required visual/structural separation.
    expect(await page.locator('[data-testid^="chart-drawing-row-"]').count()).toBe(1);
    expect(await page.locator('[data-testid^="chart-pattern-row-"]').count()).toBeGreaterThan(0);

    // persists through a reload — the GET now returns what the POST created (store is shared across requests).
    // The Charts tab is client-side screen state (like the Lab/Odds tabs), not a URL, so a full reload lands back
    // on the Feed screen first — re-opening Charts is the real-world equivalent of a user returning to the tab.
    expect(store.get("RELIANCE")?.length).toBe(1);
    await page.reload();
    await page.getByTestId("rail-charts").click();
    await expect(page.getByTestId("charts-screen")).toBeVisible();
    await expect(page.locator('[data-testid^="chart-drawing-row-"]')).toHaveCount(1);
  });

  test("Escape cancels a pending trendline's first anchor", async ({ page }) => {
    postedDrawings.length = 0;
    await mockAuthAs(page, "user-profile-charting.json");
    await mockCharts(page);
    await openCharts(page);
    await expect(page.getByTestId("chart-canvas").locator("canvas").first()).toBeVisible();

    await page.getByTestId("chart-tool-trendline").click();
    const box = (await page.getByTestId("chart-canvas").boundingBox())!;
    await page.mouse.click(box.x + box.width * 0.3, box.y + box.height * 0.35);
    await page.waitForTimeout(600);   // see the timing note in the trendline test above
    await page.keyboard.press("Escape");
    // a second click after Escape starts a NEW trendline's first anchor — still no POST
    await page.mouse.click(box.x + box.width * 0.5, box.y + box.height * 0.45);
    expect(postedDrawings.length).toBe(0);
    await expect(page.getByTestId("chart-tool-select")).toHaveAttribute("aria-pressed", "true");
  });

  test("select + Delete removes a drawing via the API", async ({ page }) => {
    postedDrawings.length = 0; deletedDrawingIds.length = 0;
    await mockAuthAs(page, "user-profile-charting.json");
    await mockCharts(page);
    await openCharts(page);
    await expect(page.getByTestId("chart-canvas").locator("canvas").first()).toBeVisible();

    await page.getByTestId("chart-tool-horizontal").click();
    const box = (await page.getByTestId("chart-canvas").boundingBox())!;
    await page.mouse.click(box.x + box.width * 0.5, box.y + box.height * 0.4);
    await expect.poll(() => postedDrawings.length).toBe(1);

    const row = page.locator('[data-testid^="chart-drawing-row-"]').first();
    await expect(row).toBeVisible();
    const id = await row.getAttribute("data-testid");
    await row.locator(`[data-testid="chart-drawing-delete-${id!.replace("chart-drawing-row-", "")}"]`).click();
    await expect.poll(() => deletedDrawingIds.length).toBe(1);
    await expect(page.locator('[data-testid^="chart-drawing-row-"]')).toHaveCount(0);
  });
});

test.describe("Charts — data view (a11y, B7)", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("a keyboard-reachable data-view table lists visible bars and patterns", async ({ page }) => {
    await mockAuthAs(page, "user-profile-charting.json");
    await mockCharts(page);
    await openCharts(page);
    await expect(page.getByTestId("chart-canvas").locator("canvas").first()).toBeVisible();
    const toggle = page.getByTestId("chart-dataview-toggle");
    await toggle.focus();
    await toggle.press("Enter");
    const view = page.getByTestId("chart-data-view");
    await expect(view).toBeVisible();
    expect(await page.locator('[data-testid="chart-dataview-bar"]').count()).toBeGreaterThan(0);
    // Pattern types are shown as readable labels ("Rectangle", not the raw RECTANGLE enum) since the 2026-09-22 relabel.
    await expect(page.locator('[data-testid="chart-dataview-pattern"]').first()).toContainText("Rectangle");
    // Chart patterns only — support/resistance levels have their own table (the layer is on by default).
    await expect(page.locator('[data-testid="chart-dataview-pattern"]')).toHaveCount(2);
    await expect(page.locator('[data-testid="chart-dataview-level"]')).toHaveCount(2);
  });
});

test.describe("Charts — mobile", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("the mobile tab bar carries Charts and the surface renders without horizontal scroll", async ({ page }) => {
    await mockAuthAs(page, "user-profile-charting.json");
    await mockCharts(page);
    await page.goto("/v5/research");
    await page.getByTestId("mnav-charts").click();
    await expect(page.getByTestId("charts-screen")).toBeVisible();
  });
});

test.describe("Charts — W0 patterns on the chart (§38.15, TC-70..87)", () => {
  // MOCK — not real data: symbol "PATTERNQA" is a purpose-built fixture (e2e/fixtures/research-chart-*-PATTERNQA.json),
  // isolated from RELIANCE/TCS via a per-test `symbols` override — the shared default fixtures are untouched by these
  // tests. 6 chart patterns (2 overlapping RECTANGLEs, 1 confirmed HH_HL, 1 forming RECTANGLE, 1 FAILED RECTANGLE,
  // 1 INVALIDATED HH_HL) + 4 SUPPORT_RESISTANCE records forming 2 near-duplicate bands (atr_14 last-bar = 8.0,
  // tolerance 0.35*8=2.8). Last close ₹505.00 is engineered to exactly equal one pattern's resistance level, giving
  // a deterministic, tie-free nearest-level case.
  test.use({ viewport: { width: 1280, height: 800 } });

  async function openPatternQA(page: Page) {
    await mockAuthAs(page, "user-profile-charting.json");
    await mockCharts(page, {
      symbols: () => ({
        status: 200,
        body: {
          symbols: [
            {
              symbol: "PATTERNQA", n_bars: 26, first_date: "2026-08-10", last_date: "2026-09-14",
              data_quality_status: "VALID", pit_status: "PIT_VALIDATED",
              file: "symbols/PATTERNQA.json.gz", sha256: "c".repeat(64), n_patterns: 6,
            },
          ],
        },
      }),
    });
    await page.goto("/v5/research");
    await page.getByTestId("rail-charts").click();
    await expect(page.getByTestId("charts-screen")).toBeVisible();
    await expect(page.getByTestId("chart-canvas").locator("canvas").first()).toBeVisible();
  }

  const renderedPatterns = async (page: Page) => Number((await page.getByTestId("chart-canvas").getAttribute("data-rendered-patterns")) ?? "-1");
  const renderedLevels = async (page: Page) => Number((await page.getByTestId("chart-canvas").getAttribute("data-rendered-levels")) ?? "-1");

  test("TC-70 AC18: every chart pattern is auto-drawn with no click; default filter is All", async ({ page }) => {
    await openPatternQA(page);
    await expect(page.getByTestId("chart-pattern-filter-all")).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator('[data-testid^="chart-pattern-row-"]')).toHaveCount(6);
    await expect.poll(() => renderedPatterns(page)).toBe(6);
  });

  test("TC-71 item 4: filter chips narrow both the list and the drawn count", async ({ page }) => {
    await openPatternQA(page);

    await page.getByTestId("chart-pattern-filter-confirmed").click();
    await expect(page.locator('[data-testid^="chart-pattern-row-"]')).toHaveCount(3);
    await expect.poll(() => renderedPatterns(page)).toBe(3);

    await page.getByTestId("chart-pattern-filter-failed").click();
    await expect(page.locator('[data-testid^="chart-pattern-row-"]')).toHaveCount(1);
    await expect.poll(() => renderedPatterns(page)).toBe(1);
    await expect(page.getByTestId("chart-pattern-row-PATTERNQA:RECTANGLE:2026-08-10")).toBeVisible();

    await page.getByTestId("chart-pattern-filter-invalidated").click();
    await expect(page.locator('[data-testid^="chart-pattern-row-"]')).toHaveCount(1);
    await expect(page.getByTestId("chart-pattern-row-PATTERNQA:HH_HL:2026-08-24")).toBeVisible();

    await page.getByTestId("chart-pattern-filter-active").click();
    await expect(page.locator('[data-testid^="chart-pattern-row-"]')).toHaveCount(4);
    await expect.poll(() => renderedPatterns(page)).toBe(4);

    await page.getByTestId("chart-pattern-filter-family-HH_HL").click();
    await expect(page.locator('[data-testid^="chart-pattern-row-"]')).toHaveCount(2);
    await expect.poll(() => renderedPatterns(page)).toBe(2);

    await page.getByTestId("chart-pattern-filter-all").click();
    await expect(page.locator('[data-testid^="chart-pattern-row-"]')).toHaveCount(6);
  });

  test("TC-72/84 AC20 + §20.3: selecting a row opens the details card, rules and event timeline", async ({ page }) => {
    await openPatternQA(page);
    await page.getByTestId("chart-pattern-row-PATTERNQA:RECTANGLE:2026-08-24").click();

    const fields = page.getByTestId("chart-pattern-fields");
    await expect(fields).toContainText("RECTANGLE");
    await expect(fields).toContainText("BULLISH");
    await expect(fields).toContainText("PRICE_CONFIRMED");
    await expect(fields).toContainText("2026-08-18");
    await expect(fields).toContainText("2026-09-01");
    await expect(fields).toContainText("490.00");
    await expect(fields).toContainText("510.00");
    await expect(fields).toContainText("511.00");
    await expect(fields).toContainText("488.00");
    await expect(fields).toContainText("8.00"); // ATR(14) at the last bar (contract.ts lastIndicatorValue convention)
    await expect(fields).toContainText("0.88"); // relative_volume at the last bar
    await expect(fields).toContainText("UNAVAILABLE"); // market_alignment / sector_alignment (components.market/sector)
    await expect(fields).toContainText("PIT_VALIDATED"); // point_in_time_validated
    await expect(fields).toContainText("0.1.0-fixture"); // pattern_version <- run.engine_version

    await expect(page.getByTestId("chart-pattern-rule-RECT_MIN_TOUCHES")).toBeVisible();
    await page.getByTestId("chart-pattern-rule-RECT_MIN_TOUCHES").click();
    await expect(page.getByTestId("chart-provenance-drawer")).toContainText("PASS");
    await page.getByTestId("chart-provenance-drawer").getByRole("button", { name: "Close" }).click();
    await expect(page.getByTestId("chart-provenance-drawer")).toHaveCount(0);

    const events = page.locator('[data-testid="chart-pattern-event-row"]');
    await expect(events).toHaveCount(1);
    await expect(events.first()).toContainText("2026-09-02");
    await expect(events.first()).toContainText("PRICE_CONFIRMED");

    // a different pattern's own fields replace the first, and one with no events shows the empty state
    await page.getByTestId("chart-pattern-row-PATTERNQA:HH_HL:2026-08-11").click();
    await expect(fields).toContainText("HH_HL");
    await expect(fields).toContainText("VOLUME_CONFIRMED");
    await expect(page.getByTestId("chart-pattern-events-empty")).toBeVisible();
  });

  test("TC-73 AC20: selecting a pattern zooms the visible range to its own window", async ({ page }) => {
    await openPatternQA(page);
    const visibleTo = () => page.getByTestId("chart-canvas").getAttribute("data-visible-to");
    const fullRangeTo = await visibleTo(); // fitContent() over all 26 bars -> should be at/near 2026-09-14

    // the FAILED pattern's window is formation_start 2026-08-10 -> its only event 2026-08-17 (+margin) --
    // far short of the full data range's end (2026-09-14).
    await page.getByTestId("chart-pattern-row-PATTERNQA:RECTANGLE:2026-08-10").click();
    await expect.poll(visibleTo).not.toBe(fullRangeTo);
    const zoomedTo = await visibleTo();
    expect(zoomedTo! < "2026-09-01").toBe(true);
    expect(zoomedTo! >= "2026-08-17").toBe(true);
  });

  test("TC-75 AC20: Esc and an empty-chart click clear the pattern selection", async ({ page }) => {
    await openPatternQA(page);
    await page.getByTestId("chart-pattern-row-PATTERNQA:RECTANGLE:2026-08-24").click();
    await expect(page.getByTestId("chart-pattern-details")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("chart-pattern-details")).toHaveCount(0);

    await page.getByTestId("chart-pattern-row-PATTERNQA:RECTANGLE:2026-08-24").click();
    await expect(page.getByTestId("chart-pattern-details")).toBeVisible();
    await page.getByTestId("chart-pattern-details-close").click();
    await expect(page.getByTestId("chart-pattern-details")).toHaveCount(0);
  });

  test("TC-77 AC21: forming, confirmed, failed and invalidated read as 4 distinct categories", async ({ page }) => {
    await openPatternQA(page);
    await expect(page.getByTestId("chart-pattern-status-PATTERNQA:RECTANGLE:2026-08-24")).toHaveAttribute("data-category", "confirmed");
    await expect(page.getByTestId("chart-pattern-status-PATTERNQA:RECTANGLE:2026-08-27")).toHaveAttribute("data-category", "forming");
    await expect(page.getByTestId("chart-pattern-status-PATTERNQA:RECTANGLE:2026-08-10")).toHaveAttribute("data-category", "failed");
    await expect(page.getByTestId("chart-pattern-status-PATTERNQA:HH_HL:2026-08-24")).toHaveAttribute("data-category", "invalidated");
    // manual drawings remain a structurally separate primitive/testid namespace (regression of the existing rule)
    await expect(page.locator('[data-testid^="chart-drawing-row-"]')).toHaveCount(0);
  });

  test("TC-78 AC22: a symbol with no chart patterns says so on the chart itself", async ({ page }) => {
    await mockAuthAs(page, "user-profile-charting.json");
    await mockCharts(page);
    await page.goto("/v5/research");
    await page.getByTestId("rail-charts").click();
    await expect(page.getByTestId("charts-screen")).toBeVisible();
    await page.getByTestId("chart-symbol-TCS").click(); // TCS fixture has 0 chart patterns (S/R only)
    await expect(page.getByTestId("chart-patterns-onchart-empty")).toContainText(
      "No chart patterns detected — checked: support/resistance, rectangle, higher-high/higher-low",
    );
  });

  test("TC-79 AC23: the 'Known' marker date is on/after every pivot's own confirmation date", async ({ page }) => {
    await openPatternQA(page);
    const known = JSON.parse((await page.getByTestId("chart-canvas").getAttribute("data-known-markers")) ?? "{}") as Record<string, string | null>;
    expect(known["PATTERNQA:RECTANGLE:2026-08-24"]).toBe("2026-09-01"); // max of 08-20, 08-26, 09-01
    expect(known["PATTERNQA:RECTANGLE:2026-08-20"]).toBe("2026-09-02"); // max of 08-24, 08-27, 09-02
    expect(known["PATTERNQA:HH_HL:2026-08-11"]).toBe("2026-08-24");    // max of 08-13, 08-14, 08-20, 08-24
  });

  test("TC-80/81 AC24 + item 8: near-duplicate S/R records group into bands, click lists every record", async ({ page }) => {
    await openPatternQA(page);
    // 4 raw records (490, 491.5 support; 512, 513 resistance) -> 2 bands at ATR(14)=8.0, tolerance 2.8
    await openSidebarTab(page, "levels");
    await expect(page.getByTestId("chart-sr-count")).toHaveText("4 levels");
    await expect.poll(() => renderedLevels(page)).toBe(2);

    const bandButtons = page.locator('button[data-testid^="chart-sr-band-"]'); // excludes the nested chart-sr-band-count-* <span>s
    await expect(bandButtons).toHaveCount(2);
    await bandButtons.first().click();
    const drawer = page.getByTestId("chart-srband-drawer");
    await expect(drawer).toBeVisible();
    await expect(page.locator('[data-testid^="chart-srband-record-"]')).toHaveCount(2);
    await page.getByTestId("chart-srband-close").click();
    await expect(drawer).toHaveCount(0);
  });

  test("TC-81b item 8 regression: RELIANCE/TCS S/R band counts are unaffected by the new atr_14 series", async ({ page }) => {
    await mockAuthAs(page, "user-profile-charting.json");
    await mockCharts(page);
    await page.goto("/v5/research");
    await page.getByTestId("rail-charts").click();
    await expect(page.getByTestId("charts-screen")).toBeVisible();
    await expect.poll(() => renderedLevels(page)).toBe(2); // RELIANCE: 2890/2940, tolerance 7 << 50 apart
    await page.getByTestId("chart-symbol-TCS").click();
    await expect.poll(() => renderedLevels(page)).toBe(2); // TCS: 4108/4113, tolerance 3.5 < 5 apart
  });

  test("TC-82 item 9: nearest-level readout — an exact-match case (distance ₹0.00 / 0.00 ATR)", async ({ page }) => {
    await openPatternQA(page);
    await expect(page.getByTestId("chart-nearest-level-role")).toHaveText("Resistance");
    await expect(page.getByTestId("chart-nearest-level-price")).toHaveText("505.00");
    await expect(page.getByTestId("chart-nearest-level-distance-rupees")).toHaveText("₹0.00");
    await expect(page.getByTestId("chart-nearest-level-distance-atr")).toHaveText("0.00");
  });

  test("TC-74/76/83 AC20 + item 5: click-on-chart selects, overlap Previous/Next, hover tooltip", async ({ page }) => {
    await openPatternQA(page);
    const canvas = page.getByTestId("chart-canvas");
    const box = (await canvas.boundingBox())!;
    // 2026-08-25 / ₹500 sits inside BOTH overlapping RECTANGLEs' boxes (08-18..09-01 & 08-20..09-04,
    // support/resistance 490-510 & 495-505) -- a generous, roughly-central point in the 26-bar / ~489-513 range.
    // Volume and oscillators now have their own panes (W1b, §38.5), so a fraction of the whole canvas host is no
    // longer a fraction of the PRICE pane — 0.5 of the host lands near the bottom of the price range (or in the
    // volume pane) and hits only one of the two rectangles. `data-price-pane-height` is the price pane's own
    // pixel height, straight from the chart, so this stays the same logical point it always was: the middle of
    // the price pane, where ₹500 on 2026-08-25 sits inside BOTH overlapping RECTANGLEs.
    const priceH = Number(await canvas.getAttribute("data-price-pane-height"));
    expect(priceH).toBeGreaterThan(100);
    const x = box.x + box.width * 0.45;
    const y = box.y + priceH * 0.5;

    await page.mouse.move(x, y);
    const tooltip = page.getByTestId("chart-pattern-hover-tooltip");
    await expect(tooltip).toBeVisible({ timeout: 5000 });

    await page.mouse.click(x, y);
    const details = page.getByTestId("chart-pattern-details");
    await expect(details).toBeVisible();
    // the click point was chosen to sit inside BOTH overlapping RECTANGLEs -- this must be a real overlap hit,
    // not a soft skip, or the test would pass without ever exercising Previous/Next.
    await expect(page.getByTestId("chart-pattern-next")).toBeVisible();
    const firstText = await details.getByTestId("chart-pattern-fields").textContent();
    await page.getByTestId("chart-pattern-next").click();
    const secondText = await details.getByTestId("chart-pattern-fields").textContent();
    expect(secondText).not.toBe(firstText);
    await page.getByTestId("chart-pattern-prev").click();
    const backText = await details.getByTestId("chart-pattern-fields").textContent();
    expect(backText).toBe(firstText);
  });
});
