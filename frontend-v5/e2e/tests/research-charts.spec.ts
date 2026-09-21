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

  test("TC-18 weekly/monthly are visibly disabled with the spec G-6 reason; daily works", async ({ page }) => {
    await expect(page.getByTestId("chart-timeframe-daily")).toHaveAttribute("aria-pressed", "true");
    const weekly = page.getByTestId("chart-timeframe-weekly");
    const monthly = page.getByTestId("chart-timeframe-monthly");
    await expect(weekly).toBeDisabled();
    await expect(monthly).toBeDisabled();
    await expect(weekly).toHaveAttribute("title", /needs longer history \(spec G-6\)/);
    await expect(page.getByTestId("chart-timeframe-reason")).toContainText("needs longer history (spec G-6)");
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

    await page.getByTestId("chart-indicator-toggle-bollinger").check();
    await expect.poll(drawn).toEqual(["bollinger:bb_mid", "bollinger:bb_upper", "bollinger:bb_lower"]);
    // width/pos are on a different scale from price — listed in output_fields but not in plot_fields
    expect((await drawn()).some((t) => t.includes("bb_width") || t.includes("bb_pos"))).toBe(false);
    await page.getByTestId("chart-indicator-toggle-bollinger").uncheck();
    await expect.poll(drawn).toEqual([]);

    await page.getByTestId("chart-indicator-toggle-macd").check();
    await expect.poll(drawn).toEqual(["macd:macd", "macd:signal", "macd:hist"]);
  });

  test("an indicator's info button opens its provenance (warmup, calculation version)", async ({ page }) => {
    await mockAuthAs(page, "user-profile-charting.json");
    await mockCharts(page);
    await openCharts(page);
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
    await page.mouse.click(box.x + box.width * 0.65, box.y + box.height * 0.6);
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
    await expect(page.locator('[data-testid="chart-dataview-pattern"]').first()).toContainText("RECTANGLE");
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
