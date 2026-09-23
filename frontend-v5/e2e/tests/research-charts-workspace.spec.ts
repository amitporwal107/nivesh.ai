/**
 * Research → Charts, W1b: the 1A chart workspace (§38.3–§38.8, §38.12 AC 1–6, 8, 11, 12 and
 * `.claude/workspace/charting-pattern-engine/design-1a-reference.md`). Covers what the wiring added on top of
 * W0/W1a: the top bar, the drawing rail's modifiers, the legend and crosshair tooltip, stacked panes, the bottom
 * bar, the sidebar tabs and the watchlist column.
 *
 * MOCK — not real data: every /api/research/chart/* and /api/research/drawings response here is a fixture
 * (e2e/fixtures/research-chart-*.json), shaped to research/charting/SNAPSHOT_SCHEMA.md, exactly as
 * research-charts.spec.ts does. auth/me is mocked too. Staging verification is a separate, later step.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { mockAuthAs } from "../helpers/api-mock";

const FX = path.join(process.cwd(), "e2e", "fixtures");
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(FX, name), "utf-8"));

const posted: Array<Record<string, unknown>> = [];
const deleted: string[] = [];

async function mockCharts(page: Page, opts?: { ohlcvStatus?: (tf: string | null) => number }) {
  const store = new Map<string, Array<Record<string, unknown>>>([["RELIANCE", []], ["TCS", []]]);

  await page.route("**/api/research/chart/run", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(load("research-chart-run.json")) }));
  await page.route("**/api/research/chart/catalogue", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(load("research-chart-catalogue.json")) }));
  await page.route("**/api/research/chart/symbols", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(load("research-chart-symbols.json")) }));
  await page.route("**/api/research/chart/*/ohlcv**", (route) => {
    const url = new URL(route.request().url());
    const tf = url.searchParams.get("timeframe");
    const status = opts?.ohlcvStatus?.(tf) ?? 200;
    if (status !== 200) {
      return route.fulfill({ status, contentType: "application/json", body: JSON.stringify({ detail: `unknown_timeframe: ${tf}` }) });
    }
    const sym = decodeURIComponent(url.pathname.split("/").slice(-2, -1)[0]);
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(load(`research-chart-ohlcv-${sym}.json`)) });
  });
  await page.route("**/api/research/chart/*/indicators**", (route) => {
    const sym = decodeURIComponent(new URL(route.request().url()).pathname.split("/").slice(-2, -1)[0]);
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(load(`research-chart-indicators-${sym}.json`)) });
  });
  await page.route("**/api/research/chart/*/patterns", (route) => {
    const sym = decodeURIComponent(new URL(route.request().url()).pathname.split("/").slice(-2, -1)[0]);
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(load(`research-chart-patterns-${sym}.json`)) });
  });
  await page.route("**/api/research/drawings**", async (route: Route) => {
    const req = route.request();
    const url = new URL(req.url());
    if (req.method() === "GET") {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(store.get(url.searchParams.get("symbol") ?? "") ?? []) });
    }
    if (req.method() === "POST") {
      const payload = req.postDataJSON() as Record<string, unknown>;
      posted.push(payload);
      const now = new Date().toISOString();
      const created = {
        drawing_id: `drw_${posted.length}`, user_id: "user_ed05fb1daa45",
        symbol: payload.symbol, timeframe: payload.timeframe, drawing_type: payload.drawing_type,
        anchor_points: payload.anchor_points, style: payload.style ?? null, created_at: now, updated_at: now,
      };
      const list = store.get(String(payload.symbol)) ?? [];
      list.push(created);
      store.set(String(payload.symbol), list);
      return route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(created) });
    }
    if (req.method() === "DELETE") {
      const id = url.pathname.split("/").pop()!;
      deleted.push(id);
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
  await expect(page.getByTestId("chart-canvas").locator("canvas").first()).toBeVisible();
}

/** The middle of the PRICE pane in page coordinates — see the note in research-charts.spec.ts TC-74. */
async function pricePanePoint(page: Page, fx: number, fy: number) {
  const canvas = page.getByTestId("chart-canvas");
  const box = (await canvas.boundingBox())!;
  const priceH = Number(await canvas.getAttribute("data-price-pane-height"));
  expect(priceH).toBeGreaterThan(100);
  return { x: box.x + box.width * fx, y: box.y + priceH * fy };
}

test.describe("Charts — W1b workspace (§38.3–§38.8, AC 1–6, 8, 11, 12)", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test.beforeEach(async ({ page }) => {
    posted.length = 0; deleted.length = 0;
    await mockAuthAs(page, "user-profile-charting.json");
    await mockCharts(page);
    await openCharts(page);
  });

  test("TC-160 AC1: the workspace regions render at their spec sizes and nothing scrolls sideways", async ({ page }) => {
    const toolbar = page.getByTestId("chart-toolbar");
    const rail = page.getByTestId("chart-rail");
    const watchlist = page.getByTestId("chart-symbol-list");
    const sidebar = page.getByTestId("chart-sidebar");
    await expect(toolbar).toBeVisible();
    await expect(rail).toBeVisible();
    await expect(watchlist).toBeVisible();
    await expect(sidebar).toBeVisible();
    await expect(page.getByTestId("chart-bottombar")).toBeVisible();

    expect(Math.round((await toolbar.boundingBox())!.height)).toBe(56);
    expect(Math.round((await rail.boundingBox())!.width)).toBe(44);
    expect(Math.round((await watchlist.boundingBox())!.width)).toBe(216);
    expect(Math.round((await sidebar.boundingBox())!.width)).toBe(300);

    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
    // the chart itself still gets a usable area
    const canvas = (await page.getByTestId("chart-canvas").boundingBox())!;
    expect(canvas.height).toBeGreaterThan(250);
  });

  test("TC-161 top bar: symbol, exchange and the last close with its change come from the served bars", async ({ page }) => {
    const bars = load("research-chart-ohlcv-RELIANCE.json").bars as Array<[string, number, number, number, number, number]>;
    const last = bars[bars.length - 1][4];
    const prev = bars[bars.length - 2][4];
    const change = last - prev;
    const pct = (change / prev) * 100;

    await expect(page.getByTestId("chart-toolbar-symbol")).toContainText("RELIANCE");
    await expect(page.getByTestId("chart-toolbar-symbol")).toContainText("NSE");
    await expect(page.getByTestId("chart-toolbar-price")).toHaveText(last.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
    await expect(page.getByTestId("chart-toolbar-change")).toContainText(`${change >= 0 ? "+" : ""}${change.toFixed(2)}`);
    await expect(page.getByTestId("chart-toolbar-change")).toContainText(`${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`);
  });

  test("TC-162 AC11: the status pill sits in the top bar and opens the provenance drawer", async ({ page }) => {
    const chip = page.getByTestId("chart-status-chip");
    await expect(chip).toBeVisible();
    const toolbarBox = (await page.getByTestId("chart-toolbar").boundingBox())!;
    const chipBox = (await chip.boundingBox())!;
    expect(chipBox.y).toBeGreaterThanOrEqual(toolbarBox.y - 1);
    expect(chipBox.y + chipBox.height).toBeLessThanOrEqual(toolbarBox.y + toolbarBox.height + 1);
    await chip.click();
    await expect(page.getByTestId("chart-provenance-drawer")).toBeVisible();
    await expect(page.getByTestId("chart-provenance-dq")).toBeVisible();
    await expect(page.getByTestId("chart-provenance-pit")).toBeVisible();
  });

  test("TC-163 Alert and Compare are present and disabled, each saying why", async ({ page }) => {
    for (const id of ["chart-toolbar-alert", "chart-toolbar-compare"]) {
      const b = page.getByTestId(id);
      await expect(b).toBeVisible();
      await expect(b).toBeDisabled();
      const title = await b.getAttribute("title");
      expect(title && title.length > 12).toBe(true);
    }
  });

  test("TC-164 chart types: every type draws, and Heikin-Ashi is labelled a transform", async ({ page }) => {
    const canvas = page.getByTestId("chart-canvas");
    const seriesType = () => canvas.getAttribute("data-series-type");
    await expect.poll(seriesType).toBe("candles");

    for (const type of ["hollow_candles", "bars", "line", "area", "heikin_ashi"]) {
      await page.getByTestId("chart-toolbar-charttype").click();
      await page.getByTestId(`chart-toolbar-charttype-${type}`).click();
      await expect.poll(seriesType).toBe(type);
      // the chart still paints after the switch
      const painted = await canvas.locator("canvas").first().evaluate((el: HTMLCanvasElement) => {
        const ctx = el.getContext("2d");
        if (!ctx) return false;
        const data = ctx.getImageData(0, 0, el.width, el.height).data;
        for (let i = 3; i < data.length; i += 4 * 37) if (data[i] !== 0) return true;
        return false;
      });
      expect(painted, `${type} painted nothing`).toBe(true);
    }
    await expect(page.getByTestId("chart-transform-badge")).toContainText("TRANSFORM");

    // and the overlays survive every switch — the primitives stay attached to the same primary series
    await expect.poll(async () => Number(await canvas.getAttribute("data-rendered-patterns"))).toBeGreaterThan(0);
    await page.getByTestId("chart-toolbar-charttype").click();
    await page.getByTestId("chart-toolbar-charttype-candles").click();
    await expect.poll(seriesType).toBe("candles");
  });

  test("TC-165 AC2: the legend shows the last bar, and follows the crosshair with a tooltip", async ({ page }) => {
    const bars = load("research-chart-ohlcv-RELIANCE.json").bars as Array<[string, number, number, number, number, number]>;
    const last = bars[bars.length - 1];
    const legend = page.getByTestId("chart-legend");
    await expect(legend).toBeVisible();
    await expect(page.getByTestId("chart-legend-symbol")).toHaveText("RELIANCE");
    await expect(page.getByTestId("chart-legend-timeframe")).toHaveText("1D");
    // The legend uses the screen's en-IN price formatter (contract.ts `price`), so the expected text is
    // formatted the same way rather than with toFixed — "2,985.40", not "2985.40".
    const asPrice = (v: number) => v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    await expect(page.getByTestId("chart-legend-ohlc")).toContainText(asPrice(last[4]));

    const pt = await pricePanePoint(page, 0.5, 0.5);
    await page.mouse.move(pt.x, pt.y);
    const tooltip = page.getByTestId("chart-crosshair-tooltip");
    await expect(tooltip).toBeVisible();
    for (const id of ["chart-crosshair-o", "chart-crosshair-h", "chart-crosshair-l", "chart-crosshair-c", "chart-crosshair-vol"]) {
      await expect(page.getByTestId(id)).not.toHaveText("—");
    }
    // the legend's O/H/L/C now describes the hovered bar, not the last one
    const hoveredC = await page.getByTestId("chart-crosshair-c").textContent();
    await expect(page.getByTestId("chart-legend-ohlc")).toContainText(hoveredC!.trim());
  });

  test("TC-166 legend indicator rows carry the value, and hide/remove behave differently", async ({ page }) => {
    await page.getByTestId("chart-sidebar-tab-indicators").click();
    await page.getByTestId("chart-indicator-toggle-sma_20").check();
    const row = page.getByTestId("chart-legend-indicator-sma_20");
    await expect(row).toBeVisible();
    const canvas = page.getByTestId("chart-canvas");
    await expect.poll(async () => (await canvas.getAttribute("data-rendered-series")) ?? "").toContain("sma_20");

    // hide: the series stops being drawn, the row stays (§38.4)
    await row.hover();
    await page.getByTestId("chart-legend-indicator-sma_20-hide").click();
    await expect.poll(async () => (await canvas.getAttribute("data-rendered-series")) ?? "").not.toContain("sma_20");
    await expect(row).toBeVisible();

    // remove: the row goes too, and the sidebar checkbox unticks with it
    await row.hover();
    await page.getByTestId("chart-legend-indicator-sma_20-remove").click();
    await expect(page.getByTestId("chart-legend-indicator-sma_20")).toHaveCount(0);
    await expect(page.getByTestId("chart-indicator-toggle-sma_20")).not.toBeChecked();
  });

  test("TC-167 AC6: magnet snaps a new anchor to one of that bar's O/H/L/C", async ({ page }) => {
    await page.getByTestId("chart-rail-magnet").click();
    await expect(page.getByTestId("chart-rail-magnet")).toHaveAttribute("aria-pressed", "true");
    await page.getByTestId("chart-tool-horizontal").click();
    const pt = await pricePanePoint(page, 0.5, 0.45);
    await page.mouse.click(pt.x, pt.y);
    await expect.poll(() => posted.length).toBe(1);

    const anchor = (posted[0].anchor_points as Array<{ date: string; price: number }>)[0];
    const bars = load("research-chart-ohlcv-RELIANCE.json").bars as Array<[string, number, number, number, number, number]>;
    const bar = bars.find((b) => b[0] === anchor.date)!;
    expect(bar, `no bar for ${anchor.date}`).toBeTruthy();
    expect([bar[1], bar[2], bar[3], bar[4]]).toContain(anchor.price);
  });

  test("TC-168 AC6: lock blocks new drawings; hide hides them without deleting anything", async ({ page }) => {
    await page.getByTestId("chart-tool-horizontal").click();
    let pt = await pricePanePoint(page, 0.45, 0.4);
    await page.mouse.click(pt.x, pt.y);
    await expect.poll(() => posted.length).toBe(1);
    await expect(page.locator('[data-testid^="chart-drawing-row-"]')).toHaveCount(1);

    // lock: a further click creates nothing
    await page.getByTestId("chart-rail-lock-all").click();
    await page.getByTestId("chart-tool-horizontal").click();
    pt = await pricePanePoint(page, 0.6, 0.5);
    await page.mouse.click(pt.x, pt.y);
    await page.waitForTimeout(400);
    expect(posted.length).toBe(1);

    // hide: the row and the server copy are untouched
    await page.getByTestId("chart-rail-hide-all").click();
    await expect(page.getByTestId("chart-rail-hide-all")).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator('[data-testid^="chart-drawing-row-"]')).toHaveCount(1);
    expect(deleted.length).toBe(0);
  });

  test("TC-169 AC5: undo deletes the drawing, redo re-creates it, both through the API", async ({ page }) => {
    await page.getByTestId("chart-tool-horizontal").click();
    const pt = await pricePanePoint(page, 0.5, 0.45);
    await page.mouse.click(pt.x, pt.y);
    await expect.poll(() => posted.length).toBe(1);
    await expect(page.locator('[data-testid^="chart-drawing-row-"]')).toHaveCount(1);

    await expect(page.getByTestId("chart-toolbar-undo")).toBeEnabled();
    await page.getByTestId("chart-toolbar-undo").click();
    await expect.poll(() => deleted.length).toBe(1);
    await expect(page.locator('[data-testid^="chart-drawing-row-"]')).toHaveCount(0);

    await expect(page.getByTestId("chart-toolbar-redo")).toBeEnabled();
    await page.getByTestId("chart-toolbar-redo").click();
    await expect.poll(() => posted.length).toBe(2);
    await expect(page.locator('[data-testid^="chart-drawing-row-"]')).toHaveCount(1);
  });

  test("TC-170 AC5: a save that fails rolls back and says so", async ({ page }) => {
    await page.route("**/api/research/drawings", (route) => {
      if (route.request().method() === "POST") {
        return route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "drawing_store_unavailable" }) });
      }
      return route.fallback();
    });
    await page.getByTestId("chart-tool-horizontal").click();
    const pt = await pricePanePoint(page, 0.5, 0.45);
    await page.mouse.click(pt.x, pt.y);
    await expect(page.getByTestId("chart-drawing-error")).toBeVisible();
    await expect(page.locator('[data-testid^="chart-drawing-row-"]')).toHaveCount(0);
    await expect(page.getByTestId("chart-toolbar-undo")).toBeDisabled();
  });

  test("TC-171 AC4: volume and an oscillator get their own panes; collapse leaves a sparkline strip", async ({ page }) => {
    const canvas = page.getByTestId("chart-canvas");
    const paneIds = async () => ((await canvas.getAttribute("data-pane-ids")) ?? "").split(",").filter(Boolean);
    await expect.poll(paneIds).toEqual(["price", "volume"]);

    await page.getByTestId("chart-sidebar-tab-indicators").click();
    await page.getByTestId("chart-indicator-toggle-rsi_14").check();
    await expect.poll(paneIds).toEqual(["price", "volume", "ind:rsi"]);

    // collapse volume: it leaves the chart and becomes a strip with a sparkline
    await page.getByTestId("chart-pane-volume-collapse").click();
    await expect.poll(paneIds).toEqual(["price", "ind:rsi"]);
    await expect(page.getByTestId("chart-pane-sparkline-volume")).toBeVisible();
    await expect(page.getByTestId("chart-pane-row-volume")).toBeVisible();

    await page.getByTestId("chart-pane-volume-collapse").click();
    await expect.poll(paneIds).toEqual(["price", "volume", "ind:rsi"]);
  });

  test("TC-172 AC4: panes reorder and an indicator pane can be removed; price stays pinned first", async ({ page }) => {
    const canvas = page.getByTestId("chart-canvas");
    const paneIds = async () => ((await canvas.getAttribute("data-pane-ids")) ?? "").split(",").filter(Boolean);
    await page.getByTestId("chart-sidebar-tab-indicators").click();
    await page.getByTestId("chart-indicator-toggle-rsi_14").check();
    await expect.poll(paneIds).toEqual(["price", "volume", "ind:rsi"]);

    await page.getByTestId("chart-pane-ind:rsi-up").click();
    await expect.poll(paneIds).toEqual(["price", "ind:rsi", "volume"]);

    // the price pane is pinned: it offers neither a move nor a collapse
    await expect(page.getByTestId("chart-pane-price-up")).toBeDisabled();
    await expect(page.getByTestId("chart-pane-price-down")).toBeDisabled();
    await expect(page.getByTestId("chart-pane-price-collapse")).toHaveCount(0);
    await expect(page.getByTestId("chart-pane-price-remove")).toHaveCount(0);

    await page.getByTestId("chart-pane-ind:rsi-remove").click();
    await expect.poll(paneIds).toEqual(["price", "volume"]);
    await expect(page.getByTestId("chart-indicator-toggle-rsi_14")).not.toBeChecked();
  });

  test("TC-173 AC4: a pane resizes with the keyboard", async ({ page }) => {
    const divider = page.getByTestId("chart-pane-divider-volume");
    await expect(divider).toBeVisible();
    const before = Number(await divider.getAttribute("aria-valuenow"));
    await divider.focus();
    await divider.press("ArrowDown");
    await divider.press("ArrowDown");
    await expect.poll(async () => Number(await divider.getAttribute("aria-valuenow"))).toBe(before + 20);
  });

  test("TC-174 AC8: a range preset sets the visible range; 1D and 5D are disabled with a reason", async ({ page }) => {
    const canvas = page.getByTestId("chart-canvas");
    const bars = load("research-chart-ohlcv-RELIANCE.json").bars as Array<[string, ...number[]]>;
    const firstDate = bars[0][0];

    for (const id of ["chart-range-1D", "chart-range-5D"]) {
      await expect(page.getByTestId(id)).toBeDisabled();
      await expect(page.getByTestId(id)).toHaveAttribute("title", /intraday/i);
    }

    await page.getByTestId("chart-range-ALL").click();
    await expect.poll(async () => await canvas.getAttribute("data-visible-from")).toBe(firstDate);

    await page.getByTestId("chart-range-1M").click();
    await expect.poll(async () => (await canvas.getAttribute("data-visible-from")) ?? "").not.toBe(firstDate);
  });

  test("TC-175 the bottom bar switches the price-scale mode and shows an IST clock", async ({ page }) => {
    const canvas = page.getByTestId("chart-canvas");
    await expect.poll(async () => canvas.getAttribute("data-scale-mode")).toBe("auto");
    await page.getByTestId("chart-scale-log").click();
    await expect.poll(async () => canvas.getAttribute("data-scale-mode")).toBe("log");
    await page.getByTestId("chart-scale-percent").click();
    await expect.poll(async () => canvas.getAttribute("data-scale-mode")).toBe("percent");
    await expect(page.getByTestId("chart-ist-clock")).toContainText("IST");
    await expect(page.getByTestId("chart-adj-toggle")).toBeDisabled();
  });

  test("TC-176 the sidebar tabs swap panels and the drawings list stays on every tab", async ({ page }) => {
    await expect(page.getByTestId("chart-patterns-panel")).toBeVisible();
    await expect(page.getByTestId("chart-drawings-list")).toBeVisible();

    await page.getByTestId("chart-sidebar-tab-levels").click();
    await expect(page.getByTestId("chart-levels-panel")).toBeVisible();
    await expect(page.getByTestId("chart-patterns-panel")).toHaveCount(0);
    await expect(page.getByTestId("chart-drawings-list")).toBeVisible();

    await page.getByTestId("chart-sidebar-tab-indicators").click();
    await expect(page.getByTestId("chart-indicators-panel")).toBeVisible();
    await expect(page.getByTestId("chart-drawings-list")).toBeVisible();

    // The toolbar's Indicators button opens the §38.5 catalogue dialog. It used to switch to this
    // tab; the tab remains the quick on/off list for what this symbol carries.
    await page.getByTestId("chart-sidebar-tab-patterns").click();
    await page.getByTestId("chart-toolbar-indicators").click();
    await expect(page.getByTestId("chart-indicator-dialog")).toBeVisible();
    await page.getByTestId("chart-indicator-dialog-close").click();
    await expect(page.getByTestId("chart-indicator-dialog")).toHaveCount(0);
  });

  test("TC-177 level cards show touches, distance and HOLDING/BROKEN — and never a 1–5 strength score", async ({ page }) => {
    await page.getByTestId("chart-sidebar-tab-levels").click();
    const cards = page.locator('button[data-testid^="chart-sr-band-"]');
    await expect(cards).toHaveCount(2);
    const first = cards.first();
    const id = (await first.getAttribute("data-testid"))!.replace("chart-sr-band-", "");
    await expect(page.getByTestId(`chart-sr-band-touches-${id}`)).toContainText("touch");
    await expect(page.getByTestId(`chart-sr-band-distance-${id}`)).toContainText("₹");
    await expect(page.getByTestId(`chart-sr-band-state-${id}`)).toHaveText(/HOLDING|BROKEN/);
    await expect(page.getByTestId("chart-sidebar")).not.toContainText(/strength/i);
  });

  test("TC-178 the watchlist column lists the snapshot's symbols and switches symbol", async ({ page }) => {
    const symbols = (load("research-chart-symbols.json").symbols as Array<{ symbol: string }>).map((s) => s.symbol);
    const list = page.getByTestId("chart-symbol-list");
    for (const s of symbols) await expect(list.getByTestId(`chart-symbol-${s}`)).toBeVisible();
    await expect(list.getByTestId("chart-symbol-RELIANCE")).toHaveAttribute("aria-current", "true");
    // only the open symbol shows a price — the manifest carries no price for the others
    await expect(page.getByTestId("chart-watchlist-active-price")).toHaveCount(1);

    await list.getByTestId("chart-symbol-TCS").click();
    await expect(list.getByTestId("chart-symbol-TCS")).toHaveAttribute("aria-current", "true");
    await expect(page.getByTestId("chart-toolbar-symbol")).toContainText("TCS");
  });

  test("TC-179 keyboard: Alt+T / Alt+H pick a tool, Escape cancels, Ctrl+Z undoes", async ({ page }) => {
    await page.keyboard.press("Alt+t");
    await expect(page.getByTestId("chart-tool-trendline")).toHaveAttribute("aria-pressed", "true");
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("chart-tool-select")).toHaveAttribute("aria-pressed", "true");

    await page.keyboard.press("Alt+h");
    await expect(page.getByTestId("chart-tool-horizontal")).toHaveAttribute("aria-pressed", "true");
    const pt = await pricePanePoint(page, 0.5, 0.45);
    await page.mouse.click(pt.x, pt.y);
    await expect.poll(() => posted.length).toBe(1);

    await page.keyboard.press("Control+z");
    await expect.poll(() => deleted.length).toBe(1);
    await expect(page.locator('[data-testid^="chart-drawing-row-"]')).toHaveCount(0);
  });

  test("TC-180 AC12: changing the app theme re-themes the open chart without a reload", async ({ page }) => {
    const canvas = page.getByTestId("chart-canvas");
    const bg = async () => canvas.getAttribute("data-chart-bg");
    const before = await bg();
    expect(before).toBeTruthy();

    const beforeHandle = await canvas.locator("canvas").first().elementHandle();
    await page.evaluate(() => document.documentElement.setAttribute("data-theme", "light"));
    await expect.poll(bg).not.toBe(before);
    // AC11: the badge, the data view and the attribution are all still there in the other theme
    await expect(page.getByTestId("chart-status-chip")).toBeVisible();
    await expect(page.getByTestId("chart-tv-attribution")).toBeVisible();
    await page.getByTestId("chart-dataview-toggle").click();
    await expect(page.getByTestId("chart-data-view")).toBeVisible();
    // and the chart was re-themed in place, not remounted
    const afterHandle = await canvas.locator("canvas").first().elementHandle();
    expect(await beforeHandle!.evaluate((a, b) => a === b, afterHandle)).toBe(true);
  });

  test("TC-181 rule: no buy/sell/target wording anywhere on the screen", async ({ page }) => {
    const text = (await page.getByTestId("charts-screen").innerText()).toLowerCase();
    for (const word of [" buy ", " sell ", "target price", "entry price", "stop loss", "illustrative"]) {
      expect(text.includes(word), `found forbidden wording: ${word}`).toBe(false);
    }
  });
});

test.describe("Charts — W1b workspace on a narrow viewport", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("TC-182 AC1: at 390 px the columns fold and nothing scrolls sideways", async ({ page }) => {
    await mockAuthAs(page, "user-profile-charting.json");
    await mockCharts(page);
    await page.goto("/v5/research");
    await page.getByTestId("mnav-charts").click();
    await expect(page.getByTestId("charts-screen")).toBeVisible();
    await expect(page.getByTestId("chart-canvas").locator("canvas").first()).toBeVisible();

    // the rail folds into a Draw menu and the sidebar into a sheet
    await expect(page.getByTestId("chart-rail-compact")).toBeVisible();
    await expect(page.getByTestId("chart-rail")).toHaveCount(0);
    await expect(page.getByTestId("chart-sidebar-sheet")).toBeVisible();

    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });
});

/**
 * W1b-L: the saved-layout menu (§38.8, AC 9). The API and its tests already exist
 * (test_reports/charting_w2_layouts.md); this covers the screen wiring: save, save as, rename, delete, reopen,
 * and the debounced autosave.
 *
 * MOCK — not real data: `/api/research/chart-layouts` is backed by an in-test store here, exactly as the
 * drawings API is above.
 */
test.describe("Charts — saved layouts (§38.8, AC 9)", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  type StoredLayout = Record<string, unknown> & { layout_id: string };

  async function mockLayouts(page: Page, seed: StoredLayout[] = []) {
    const store: StoredLayout[] = [...seed];
    const posted: Array<Record<string, unknown>> = [];
    const patched: Array<{ id: string; body: Record<string, unknown> }> = [];
    const removed: string[] = [];
    await page.route("**/api/research/chart-layouts**", async (route: Route) => {
      const req = route.request();
      const url = new URL(req.url());
      const id = url.pathname.split("/").pop()!;
      const json = (status: number, body: unknown) =>
        route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

      if (req.method() === "GET") return json(200, store);
      if (req.method() === "POST") {
        const body = req.postDataJSON() as Record<string, unknown>;
        posted.push(body);
        const now = new Date().toISOString();
        const created = { ...body, layout_id: `lay_${store.length + 1}`, user_id: "u1", created_at: now, updated_at: now } as StoredLayout;
        store.unshift(created);
        return json(201, created);
      }
      if (req.method() === "PATCH") {
        const body = req.postDataJSON() as Record<string, unknown>;
        patched.push({ id, body });
        const i = store.findIndex((l) => l.layout_id === id);
        if (i < 0) return json(404, { detail: "not_found" });
        store[i] = { ...store[i], ...body, updated_at: new Date().toISOString() };
        return json(200, store[i]);
      }
      if (req.method() === "DELETE") {
        removed.push(id);
        const i = store.findIndex((l) => l.layout_id === id);
        if (i < 0) return json(404, { detail: "not_found" });
        store.splice(i, 1);
        return json(200, { status: "deleted", layout_id: id });
      }
      return json(200, {});
    });
    return { store, posted, patched, removed };
  }

  test("TC-190 a chart is Unnamed until saved, and Save captures the workspace", async ({ page }) => {
    await mockAuthAs(page, "user-profile-charting.json");
    await mockCharts(page);
    const layouts = await mockLayouts(page);
    await openCharts(page);

    await expect(page.getByTestId("chart-toolbar-layout-name")).toHaveText("Unnamed");

    // make the workspace distinctive first: an indicator in its own pane, and a chart type
    await page.getByTestId("chart-sidebar-tab-indicators").click();
    await page.getByTestId("chart-indicator-toggle-rsi_14").check();
    await page.getByTestId("chart-toolbar-charttype").click();
    await page.getByTestId("chart-toolbar-charttype-line").click();

    page.once("dialog", (d) => d.accept("Desk A"));
    await page.getByTestId("chart-toolbar-layouts").click();
    await page.getByTestId("chart-layout-save").click();

    await expect.poll(() => layouts.posted.length).toBe(1);
    const body = layouts.posted[0];
    expect(body.name).toBe("Desk A");
    expect(body.symbol).toBe("RELIANCE");
    expect(body.chart_type).toBe("line");
    expect((body.indicators as Array<{ indicator_id: string }>).map((i) => i.indicator_id)).toContain("rsi_14");
    // the price pane is not stored: it is always first and the API requires a height above zero
    expect((body.panes as Array<{ pane_id: string }>).map((p) => p.pane_id)).not.toContain("price");
    expect((body.panes as Array<{ pane_id: string }>).map((p) => p.pane_id)).toContain("ind:rsi");
    await expect(page.getByTestId("chart-toolbar-layout-name")).toHaveText("Desk A");
  });

  test("TC-191 reopening a layout restores symbol, chart type, indicators and panes", async ({ page }) => {
    await mockAuthAs(page, "user-profile-charting.json");
    await mockCharts(page);
    await mockLayouts(page, [{
      layout_id: "lay_seed", user_id: "u1", name: "TCS area", symbol: "TCS", timeframe: "1D",
      chart_type: "area",
      indicators: [{ instance_id: "rsi_14", indicator_id: "rsi_14", preset_id: "default", pane_index: 2, visible: true, style: {} }],
      panes: [{ pane_id: "ind:rsi", order: 0, height: 120, collapsed: false }, { pane_id: "volume", order: 1, height: 70, collapsed: true }],
      visible_range: null, drawing_visibility: {}, sidebar_state: { collapsed: false, active_tab: "levels" },
      created_at: "2026-09-23T00:00:00Z", updated_at: "2026-09-23T00:00:00Z",
    }]);
    await openCharts(page);

    await page.getByTestId("chart-toolbar-layouts").click();
    await page.getByTestId("chart-layout-open-lay_seed").click();

    await expect(page.getByTestId("chart-toolbar-layout-name")).toHaveText("TCS area");
    await expect(page.getByTestId("chart-toolbar-symbol")).toContainText("TCS");
    const canvas = page.getByTestId("chart-canvas");
    await expect.poll(async () => canvas.getAttribute("data-series-type")).toBe("area");
    // the RSI pane is restored ahead of volume, and volume comes back collapsed
    await expect.poll(async () => ((await canvas.getAttribute("data-pane-ids")) ?? "").split(",").filter(Boolean))
      .toEqual(["price", "ind:rsi"]);
    await expect(page.getByTestId("chart-pane-sparkline-volume")).toBeVisible();
    await expect(page.getByTestId("chart-sidebar-tab-levels")).toHaveAttribute("aria-selected", "true");
  });

  test("TC-192 a change after saving autosaves the open layout", async ({ page }) => {
    await mockAuthAs(page, "user-profile-charting.json");
    await mockCharts(page);
    const layouts = await mockLayouts(page, [{
      layout_id: "lay_seed", user_id: "u1", name: "Desk A", symbol: "RELIANCE", timeframe: "1D",
      chart_type: "candles", indicators: [], panes: [{ pane_id: "volume", order: 0, height: 70, collapsed: false }],
      visible_range: null, drawing_visibility: {}, sidebar_state: { collapsed: false, active_tab: "patterns" },
      created_at: "2026-09-23T00:00:00Z", updated_at: "2026-09-23T00:00:00Z",
    }]);
    await openCharts(page);
    await page.getByTestId("chart-toolbar-layouts").click();
    await page.getByTestId("chart-layout-open-lay_seed").click();
    await expect(page.getByTestId("chart-toolbar-layout-name")).toHaveText("Desk A");
    // applying the layout must not itself count as an edit
    await page.waitForTimeout(2200);
    expect(layouts.patched.length, "applying a layout wrote it back").toBe(0);

    await page.getByTestId("chart-toolbar-charttype").click();
    await page.getByTestId("chart-toolbar-charttype-line").click();
    await expect(page.getByTestId("chart-toolbar-layout-dirty")).toBeVisible();
    await expect.poll(() => layouts.patched.length, { timeout: 8000 }).toBe(1);
    expect(layouts.patched[0].body.chart_type).toBe("line");
    await expect(page.getByTestId("chart-toolbar-layout-dirty")).toHaveCount(0);
  });

  test("TC-193 rename and delete act on the open layout; both are disabled before the first save", async ({ page }) => {
    await mockAuthAs(page, "user-profile-charting.json");
    await mockCharts(page);
    const layouts = await mockLayouts(page, [{
      layout_id: "lay_seed", user_id: "u1", name: "Desk A", symbol: "RELIANCE", timeframe: "1D",
      chart_type: "candles", indicators: [], panes: [], visible_range: null, drawing_visibility: {},
      sidebar_state: null, created_at: "2026-09-23T00:00:00Z", updated_at: "2026-09-23T00:00:00Z",
    }]);
    await openCharts(page);

    await page.getByTestId("chart-toolbar-layouts").click();
    await expect(page.getByTestId("chart-layout-rename")).toBeDisabled();
    await expect(page.getByTestId("chart-layout-delete")).toBeDisabled();
    await page.getByTestId("chart-layout-open-lay_seed").click();

    page.once("dialog", (d) => d.accept("Desk B"));
    await page.getByTestId("chart-toolbar-layouts").click();
    await page.getByTestId("chart-layout-rename").click();
    await expect(page.getByTestId("chart-toolbar-layout-name")).toHaveText("Desk B");
    expect(layouts.patched.at(-1)!.body.name).toBe("Desk B");

    page.once("dialog", (d) => d.accept());
    await page.getByTestId("chart-toolbar-layouts").click();
    await page.getByTestId("chart-layout-delete").click();
    await expect.poll(() => layouts.removed.length).toBe(1);
    await expect(page.getByTestId("chart-toolbar-layout-name")).toHaveText("Unnamed");
  });

  test("TC-194 a failed save is shown and the layout stays dirty", async ({ page }) => {
    await mockAuthAs(page, "user-profile-charting.json");
    await mockCharts(page);
    await page.route("**/api/research/chart-layouts**", (route) => {
      if (route.request().method() === "GET") {
        return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
      }
      return route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({ detail: "chart_type: must be one of ['candles']" }) });
    });
    await openCharts(page);

    page.once("dialog", (d) => d.accept("Doomed"));
    await page.getByTestId("chart-toolbar-layouts").click();
    await page.getByTestId("chart-layout-save").click();

    await expect(page.getByTestId("chart-layout-error")).toContainText("chart_type");
    await expect(page.getByTestId("chart-toolbar-layout-name")).toHaveText("Unnamed");
  });
});

/**
 * The indicator preset catalogue and its dialog (§38.5, decision D-3). TC-213..TC-218 in
 * test_reports/charting_w2_indicator_catalogue.md — the catalogue's own shape is covered by the
 * research and backend suites; these cover what the screen does with it.
 *
 * MOCK — not real data: `/api/research/chart/catalogue` is served from
 * e2e/fixtures/research-chart-catalogue.json, which is generated from the real catalogue module.
 */
test.describe("Charts — indicator dialog (§38.5, D-3)", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test.beforeEach(async ({ page }) => {
    await mockAuthAs(page, "user-profile-charting.json");
    await mockCharts(page);
    await openCharts(page);
  });

  test("TC-213 the toolbar opens a dialog listing the catalogue grouped by category", async ({ page }) => {
    await page.getByTestId("chart-toolbar-indicators").click();
    const dialog = page.getByTestId("chart-indicator-dialog");
    await expect(dialog).toBeVisible();
    await expect(page.getByTestId("chart-indicator-dialog-version")).toContainText("CATALOGUE");

    for (const cat of ["trend", "momentum", "volatility", "volume"]) {
      await expect(page.getByTestId(`chart-indicator-group-${cat}`)).toBeVisible();
    }
    // every §38.5 preset is offered
    await expect(page.locator('[data-testid^="chart-indicator-preset-"]:not([data-testid*="-info-"])')).toHaveCount(17);
    for (const id of ["sma_200", "ema_10", "rsi_7", "rsi_21", "macd_12_26_9", "bollinger_20_2", "atr_14"]) {
      await expect(page.getByTestId(`chart-indicator-preset-${id}`)).toBeVisible();
    }
  });

  test("TC-214 search narrows the list across name, id and category", async ({ page }) => {
    await page.getByTestId("chart-toolbar-indicators").click();
    const rows = page.locator('[data-testid^="chart-indicator-preset-"]:not([data-testid*="-info-"])');

    await page.getByTestId("chart-indicator-search").fill("200");
    await expect(rows).toHaveCount(2);                       // SMA 200, EMA 200
    await page.getByTestId("chart-indicator-search").fill("momentum");
    await expect(rows).toHaveCount(4);                       // RSI ×3 + MACD
    await page.getByTestId("chart-indicator-search").fill("zzz");
    await expect(page.getByTestId("chart-indicator-dialog-empty")).toBeVisible();
  });

  test("TC-215 adding a preset draws it and marks it added; adding again removes it", async ({ page }) => {
    const canvas = page.getByTestId("chart-canvas");
    await page.getByTestId("chart-toolbar-indicators").click();
    await page.getByTestId("chart-indicator-add-sma_20").click();

    await expect(page.getByTestId("chart-indicator-added-sma_20")).toBeVisible();
    await expect.poll(async () => (await canvas.getAttribute("data-rendered-series")) ?? "").toContain("sma_20");

    await page.getByTestId("chart-indicator-add-sma_20").click();
    await expect(page.getByTestId("chart-indicator-added-sma_20")).toHaveCount(0);
    await expect.poll(async () => (await canvas.getAttribute("data-rendered-series")) ?? "").not.toContain("sma_20");
  });

  test("TC-216 two presets of the same indicator coexist on the price pane", async ({ page }) => {
    const canvas = page.getByTestId("chart-canvas");
    await page.getByTestId("chart-toolbar-indicators").click();
    await page.getByTestId("chart-indicator-add-sma_20").click();
    await page.getByTestId("chart-indicator-add-sma_50").click();
    const drawn = async () => ((await canvas.getAttribute("data-rendered-series")) ?? "").split(",").filter(Boolean);
    await expect.poll(drawn).toEqual(["sma_20", "sma_50"]);
    // SMA 200 is in the catalogue but not in this snapshot, so it is offered disabled with the
    // reason rather than as a click that silently does nothing.
    await expect(page.getByTestId("chart-indicator-add-sma_200")).toBeDisabled();
    await expect(page.getByTestId("chart-indicator-unavailable-sma_200")).toHaveText("NOT IN THIS SNAPSHOT");
    // both are overlays, so no extra pane appears
    await expect.poll(async () => ((await canvas.getAttribute("data-pane-ids")) ?? "").split(",").filter(Boolean))
      .toEqual(["price", "volume"]);
  });

  test("TC-217 an oscillator draws the reference bands its catalogue entry defines", async ({ page }) => {
    const canvas = page.getByTestId("chart-canvas");
    await page.getByTestId("chart-toolbar-indicators").click();
    await page.getByTestId("chart-indicator-add-rsi_14").click();
    await page.getByTestId("chart-indicator-dialog-close").click();

    await expect.poll(async () => JSON.parse((await canvas.getAttribute("data-band-levels")) ?? "[]"))
      .toEqual([["rsi_14", [30, 70]]]);
    // and a preset with no bands defined draws none
    await page.getByTestId("chart-toolbar-indicators").click();
    await page.getByTestId("chart-indicator-add-rsi_14").click();
    await page.getByTestId("chart-indicator-add-atr_14").click();
    await expect.poll(async () => JSON.parse((await canvas.getAttribute("data-band-levels")) ?? "[]")).toEqual([]);
  });

  test("TC-218 a catalogue that cannot be read shows the reason, and the chart still works", async ({ page }) => {
    await page.route("**/api/research/chart/catalogue", (route) =>
      route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "catalogue_unavailable" }) }));
    await page.reload();
    await page.getByTestId("rail-charts").click();
    await expect(page.getByTestId("chart-canvas").locator("canvas").first()).toBeVisible();

    await page.getByTestId("chart-toolbar-indicators").click();
    await expect(page.getByTestId("chart-indicator-dialog-error")).toContainText("could not be loaded");
    await expect(page.getByTestId("charts-state-error")).toHaveCount(0);
  });
});
