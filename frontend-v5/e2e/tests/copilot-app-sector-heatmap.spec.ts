/**
 * One-screen Copilot app (/v5/app) — Sector rotation heatmap (view tool/sector-heatmap).
 *
 * MOCK — not real data: GET /api/markets/sector-heatmap is answered by a fixture built below from 19 real-looking
 * Nifty 50 symbols with INVENTED weights and returns (test data only). Sector returns, contributions and the
 * weighted change are computed from those stocks in this file; the expected verdict is worked out here from the
 * same payload, not copied from the screen. Production build, every /api call route-mocked
 * (pw.copilot-app.config.ts).
 *
 * Covers screens/SectorHeatmap.tsx, screens/heatmap/*: the verdict and its rewrite per period, the weighted
 * change card and breadth, the legend clamp per period, size-by (Volume off with its reason), zoom by header,
 * breadcrumb and matrix row, tile selection and the auto-selected mover, "—" for a missing return, error and
 * retry, empty, stale, the trust line, the ask button, the phone layout (sectors first, leading / lagging, no
 * sideways scroll, 44px targets), the Screener and desk entry points, and squarify's geometry.
 */
import { test, expect, type Page } from "@playwright/test";
import { mockApi } from "../helpers/api-mock";
import { squarify } from "../../src/pages/CopilotApp/screens/heatmap/squarify";

const APP = "/v5/app";
const HEATMAP = `${APP}/tool/sector-heatmap`;

type R = [d: number, w: number, m: number | null];
// symbol, name, sector, weight %, close, [1D, 1W, 1M] %, traded value Cr, relative volume
const ROWS: Array<[string, string, string, number, number, R, number, number | null]> = [
  ["HDFCBANK", "HDFC Bank", "Financial Services", 13.0, 1650.5, [1.2, 2.5, 3.0], 2400, 1.1],
  ["ICICIBANK", "ICICI Bank", "Financial Services", 9.0, 1210.0, [0.8, 1.9, 4.0], 1900, 0.9],
  ["KOTAKBANK", "Kotak Mahindra Bank", "Financial Services", 3.5, 1795.0, [-0.4, 0.5, -1.0], 600, 1.0],
  ["AXISBANK", "Axis Bank", "Financial Services", 3.0, 1105.0, [0.6, 1.0, 2.0], 800, 1.3],
  ["TCS", "Tata Consultancy Services", "Information Technology", 4.0, 3980.0, [-2.1, -4.0, -1.5], 900, 1.6],
  ["INFY", "Infosys", "Information Technology", 5.5, 1620.0, [-1.8, -3.2, 0.5], 1100, 1.4],
  ["HCLTECH", "HCL Technologies", "Information Technology", 1.8, 1530.0, [-1.2, -2.0, -0.5], 400, 1.2],
  ["WIPRO", "Wipro", "Information Technology", 0.9, 262.0, [-0.01, -1.0, -0.8], 250, 0.8],
  ["RELIANCE", "Reliance Industries", "Oil Gas & Consumable Fuels", 9.5, 2910.0, [2.4, 3.0, 5.0], 2600, 1.8],
  ["ONGC", "Oil & Natural Gas Corp", "Oil Gas & Consumable Fuels", 1.0, 268.0, [1.1, 2.0, 6.0], 500, 1.1],
  ["NTPC", "NTPC", "Oil Gas & Consumable Fuels", 1.4, 372.0, [0.3, -0.5, 1.0], 450, 1.0],
  ["MARUTI", "Maruti Suzuki India", "Automobile and Auto Components", 1.8, 12400.0, [-0.6, 1.5, 2.5], 700, 0.9],
  ["EICHERMOT", "Eicher Motors", "Automobile and Auto Components", 1.0, 4900.0, [0.2, 0.8, 1.2], 300, 1.0],
  ["TATAMOTORS", "Tata Motors", "Automobile and Auto Components", 1.6, 910.0, [-1.0, 2.2, null], 1200, 1.5],
  ["ITC", "ITC", "Fast Moving Consumer Goods", 3.9, 468.0, [0.1, -0.7, -2.0], 800, 0.9],
  ["HINDUNILVR", "Hindustan Unilever", "Fast Moving Consumer Goods", 2.3, 2480.0, [-0.3, -1.1, -3.0], 500, 1.0],
  ["TATASTEEL", "Tata Steel", "Metals & Mining", 1.2, 158.0, [-2.6, -3.5, -6.0], 650, 1.7],
  ["JSWSTEEL", "JSW Steel", "Metals & Mining", 1.0, 1002.0, [-1.8, -2.8, -4.5], 380, 1.3],
  ["HINDALCO", "Hindalco Industries", "Metals & Mining", 1.0, 655.0, [-2.2, -4.5, -7.0], 420, 1.4],
];
const SECTORS = [...new Set(ROWS.map((r) => r[2]))];
const P = ["d", "w", "m"] as const;
type PK = (typeof P)[number];
const LABEL: Record<PK, string> = { d: "1D", w: "1W", m: "1M" };

const iso = (daysAgo: number) => new Date(Date.now() - daysAgo * 86_400_000).toISOString().slice(0, 10);

function build(opts: { asOf?: string; volume?: boolean; relVol?: boolean } = {}) {
  const volume = opts.volume ?? true;
  const stocks = ROWS.map(([symbol, name, sector, weight, close, r, tv, rel]) => ({
    symbol, name, sector, close, weight_pct: weight, traded_value_cr: volume ? tv : null,
    returns: { d: r[0], w: r[1], m: r[2] }, index_impact_pct: { d: Number(((weight * r[0]) / 100).toFixed(4)) },
    rel_volume: opts.relVol === false ? null : rel,
  }));
  const sectors = SECTORS.map((name) => {
    const ss = stocks.filter((s) => s.sector === name);
    const wsum = ss.reduce((a, s) => a + s.weight_pct, 0);
    const ret = (k: PK) => {
      const have = ss.filter((s) => s.returns[k] != null);
      const w = have.reduce((a, s) => a + s.weight_pct, 0);
      return have.reduce((a, s) => a + s.weight_pct * (s.returns[k] as number), 0) / w;
    };
    const con = (k: PK) => ss.reduce((a, s) => a + (s.returns[k] == null ? 0 : (s.weight_pct * (s.returns[k] as number)) / 100), 0);
    return {
      name, stocks: ss.length, weight_pct: wsum,
      returns: { d: ret("d"), w: ret("w"), m: ret("m") }, contribution_pct: { d: con("d"), w: con("w"), m: con("m") },
      breadth: { advances: 0, declines: 0, unchanged: 0, no_price: 0 },
    };
  });
  const wc = (k: PK) => {
    const have = stocks.filter((s) => s.returns[k] != null);
    return have.reduce((a, s) => a + s.weight_pct * (s.returns[k] as number), 0) / have.reduce((a, s) => a + s.weight_pct, 0);
  };
  const tone = (v: number | null) => (v == null ? null : Math.abs(v) < 0.05 ? "f" : v > 0 ? "u" : "d");
  const cnt = (t: string) => stocks.filter((s) => tone(s.returns.d) === t).length;
  return {
    as_of: opts.asOf ?? iso(0), index: "NIFTY50", source: "nidp.warehouse", sessions: { d: 1, w: 5, m: 21 }, mode: "end_of_day",
    weight_basis: "market_cap", weight_note: "Weights are market-cap shares of the list, not NSE's own, so the weighted change differs slightly from the published index move.",
    sectors, stocks, breadth: { advances: cnt("u"), declines: cnt("d"), unchanged: cnt("f") },
    weighted_change: { d: wc("d"), w: wc("w"), m: wc("m") },
    unavailable: [
      ...(volume ? [] : [{ field: "traded_value_cr", reason: "volume feed not loaded for this session" }]),
      ...(opts.relVol === false ? [{ field: "rel_volume", reason: "needs 20 sessions of volume" }] : []),
    ],
  };
}
type Payload = ReturnType<typeof build>;

/** The headline the screen should write, worked out here from the payload. */
function expectedVerdict(p: Payload, k: PK): string {
  const rows = p.sectors.map((s) => ({ name: s.name, c: s.contribution_pct[k] as number }));
  const pos = rows.filter((r) => r.c > 0).sort((a, b) => b.c - a.c);
  const neg = rows.filter((r) => r.c < 0).sort((a, b) => a.c - b.c);
  const have = p.stocks.filter((s) => s.returns[k] != null);
  const up = have.filter((s) => (s.returns[k] as number) >= 0.05).length;
  const down = have.filter((s) => (s.returns[k] as number) <= -0.05).length;
  const first = `${pos.slice(0, 2).map((r) => r.name).join(" and ")} led while ${neg[0].name} dragged the index.`;
  const phrase = k === "d" ? "on the day" : k === "w" ? "over the week" : "over the month";
  return `${first} ${up > down ? up : down} of ${have.length} stocks ${up > down ? "rose" : "fell"} ${phrase}.`;
}

const fmt = (v: number | null, d = 2) => (v == null ? "—" : `${v < 0 ? "−" : v > 0 ? "+" : ""}${Math.abs(v).toFixed(d)}%`);

interface Opened { sent: string[]; errors: string[]; urls: string[]; payload: Payload; ctl: { failing: boolean } }

async function open(page: Page, opts: Parameters<typeof build>[0] & { fail?: boolean; status?: number; body?: unknown; empty?: boolean; width?: number; height?: number; url?: string } = {}): Promise<Opened> {
  const errors: string[] = [];
  const sent: string[] = [];
  const urls: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.setViewportSize({ width: opts.width ?? 1440, height: opts.height ?? 1000 });
  await mockApi(page, "populated");
  await page.route("**/api/chat/sessions", (route) =>
    route.request().method() === "POST"
      ? route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ session_id: "asked1" }) })
      : route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route("**/api/chat/messages*", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route("**/api/chat/stream", (route) => {
    sent.push((route.request().postDataJSON() as { message: string }).message);
    return route.fulfill({ status: 200, contentType: "text/event-stream", body: `data: ${JSON.stringify({ type: "done", content: "ok" })}\n\n` });
  });
  const payload = build(opts);
  const ctl = { failing: !!opts.fail };
  await page.route("**/api/markets/sector-heatmap*", (route) => {
    urls.push(route.request().url());
    if (ctl.failing) return route.fulfill({ status: opts.status ?? 500, contentType: "application/json", body: JSON.stringify(opts.body ?? { detail: "fixture failure" }) });
    const body = opts.empty ? { ...payload, sectors: [], stocks: [], unavailable: [{ field: "stocks", reason: "no constituents loaded for NIFTY50" }] } : payload;
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.goto(opts.url ?? HEATMAP);
  return { sent, errors, urls, payload, ctl };
}

const box = async (page: Page, id: string) => {
  const b = await page.getByTestId(id).boundingBox();
  if (!b) throw new Error(`no box for ${id}`);
  return b;
};

test.describe("Sector heatmap — desktop", () => {
  test("headline is written from the data; weighted change, breadth and trust line agree", async ({ page }) => {
    const { payload, errors, urls } = await open(page);
    await expect(page.getByTestId("hm-verdict")).toHaveText(expectedVerdict(payload, "d"));
    // Lead sectors green, the drag red (the words carry the meaning too).
    await expect(page.getByTestId("hm-verdict").locator("[data-tone=up]").first()).toBeVisible();
    await expect(page.getByTestId("hm-verdict").locator("[data-tone=down]")).toHaveCount(1);
    await expect(page.getByTestId("hm-weighted")).toHaveText(fmt(payload.weighted_change.d));
    await expect(page.getByTestId("hm-breadth-counts")).toContainText(`${payload.breadth.advances} advancing`);
    await expect(page.getByTestId("hm-breadth-counts")).toContainText(`${payload.breadth.declines} declining`);
    await expect(page.getByTestId("hm-breadth-counts")).toContainText(`${payload.breadth.unchanged} flat`);
    for (const id of ["hm-trust-weighted", "hm-trust-map", "hm-trust-matrix", "hm-trust-stock"]) {
      const t = page.getByTestId(id);
      await expect(t).toContainText("End of day");
      await expect(t).toContainText("weights from index constituents");
      await expect(t).toContainText("returns on adjusted closes");
      await expect(t).not.toContainText(/\blive\b/i);
    }
    await expect(page.getByTestId("hm-index")).toHaveValue("NIFTY50");
    await expect(page.getByTestId("hm-index")).toContainText("Nifty 50");
    expect(urls[0]).toContain("index=NIFTY50");
    expect(errors).toEqual([]);
  });

  test("the index picker offers the broad and size indices and asks the route for the one picked", async ({ page }) => {
    const { urls } = await open(page);
    const sel = page.getByTestId("hm-index");
    await expect(sel.locator("option")).toHaveText(["Nifty 50", "Nifty 100", "Nifty 200", "Nifty 500", "Nifty Midcap 150", "Nifty Smallcap 250", "Nifty Total Market"]);
    await sel.selectOption("NIFTY500");
    await expect.poll(() => urls.some((u) => u.includes("index=NIFTY500"))).toBe(true);
    await sel.selectOption("NIFTY100");
    await expect.poll(() => urls.some((u) => u.includes("index=NIFTY100"))).toBe(true);
    await sel.selectOption("NIFTYMIDCAP150");
    await expect.poll(() => urls.some((u) => u.includes("index=NIFTYMIDCAP150"))).toBe(true);
    await sel.selectOption("NIFTYTOTALMARKET");
    await expect.poll(() => urls.some((u) => u.includes("index=NIFTYTOTALMARKET"))).toBe(true);
  });

  test("changing the period recolours the tiles, rewrites the headline and the weighted change", async ({ page }) => {
    const { payload } = await open(page);
    const d = await page.getByTestId("hm-verdict").innerText();
    // MARUTI: down on the day, up on the week.
    await expect(page.getByTestId("hm-tile-MARUTI")).toHaveAttribute("data-tone", "down");
    const bgDay = await page.getByTestId("hm-tile-MARUTI").evaluate((e) => (e as HTMLElement).style.background);
    for (const k of ["w", "m"] as const) {
      await page.getByTestId(`hm-period-${k}`).click();
      await expect(page.getByTestId(`hm-period-${k}`)).toHaveAttribute("aria-pressed", "true");
      await expect(page.getByTestId("hm-verdict")).toHaveText(expectedVerdict(payload, k));
      await expect(page.getByTestId("hm-weighted")).toHaveText(fmt(payload.weighted_change[k]));
    }
    await page.getByTestId("hm-period-w").click();
    await expect(page.getByTestId("hm-verdict")).not.toHaveText(d);
    await expect(page.getByTestId("hm-tile-MARUTI")).toHaveAttribute("data-tone", "up");
    const bgWeek = await page.getByTestId("hm-tile-MARUTI").evaluate((e) => (e as HTMLElement).style.background);
    expect(bgWeek).not.toBe(bgDay);
    expect(bgWeek).toContain("var(--mint)");
    expect(bgDay).toContain("var(--cp-danger)");
  });

  test("the legend names the clamp for each period and has seven swatches; a flat move is neutral", async ({ page }) => {
    await open(page);
    for (const [k, clamp] of [["d", 3], ["w", 6], ["m", 10]] as const) {
      await page.getByTestId(`hm-period-${k}`).click();
      await expect(page.getByTestId("hm-legend-text")).toContainText(`±${clamp}%`);
      await expect(page.getByTestId("hm-legend")).toHaveAttribute("data-clamp", String(clamp));
      await expect(page.getByTestId("hm-legend").locator("span[aria-hidden] > span")).toHaveCount(7);
    }
    await page.getByTestId("hm-period-d").click();
    // WIPRO is -0.01% on the day: under 0.05%, so neutral, not red.
    await expect(page.getByTestId("hm-tile-WIPRO")).toHaveAttribute("data-tone", "flat");
    // The same stock is tinted against each period's own clamp.
    const strength = async () => (await page.getByTestId("hm-tile-HINDALCO").evaluate((e) => (e as HTMLElement).style.background)).match(/danger\) (\d+)%/)?.[1];
    // tint = 18 + 44 × min(1, |move| ÷ clamp): -2.2 of 3 on the day, -7.0 of 10 on the month.
    expect(Number(await strength())).toBe(Math.round(18 + 44 * (2.2 / 3)));
    await page.getByTestId("hm-period-m").click();
    expect(Number(await strength())).toBe(Math.round(18 + 44 * 0.7));
  });

  test("size by: weight and equal re-lay the tiles; Volume is off, with the reason, when traded value is missing", async ({ page }) => {
    await open(page);
    const ratio = async () => (await box(page, "hm-tile-HDFCBANK")).width * (await box(page, "hm-tile-HDFCBANK")).height / ((await box(page, "hm-tile-KOTAKBANK")).width * (await box(page, "hm-tile-KOTAKBANK")).height);
    // Weight: HDFCBANK 13.0 vs KOTAKBANK 3.5.
    expect(await ratio()).toBeGreaterThan(3.2);
    expect(await ratio()).toBeLessThan(4.3);
    await page.getByTestId("hm-size-volume").click();
    // Traded value: 2400 vs 600 Cr.
    expect(await ratio()).toBeGreaterThan(3.5);
    expect(await ratio()).toBeLessThan(4.5);
    await page.getByTestId("hm-size-equal").click();
    expect(await ratio()).toBeGreaterThan(0.9);
    expect(await ratio()).toBeLessThan(1.1);
    await expect(page.getByTestId("hm-size-equal")).toHaveAttribute("aria-pressed", "true");
  });

  test("Volume is disabled and says why when traded value is null", async ({ page }) => {
    await open(page, { volume: false });
    await expect(page.getByTestId("hm-size-volume")).toBeDisabled();
    await expect(page.getByTestId("hm-size-note")).toContainText("traded value is missing for 19 of 19 stocks");
    await expect(page.getByTestId("hm-size-note")).toContainText("volume feed not loaded for this session");
    await expect(page.getByTestId("hm-size-weight")).toHaveAttribute("aria-pressed", "true");
  });

  test("a sector header zooms in, the tiles fill the box, and the header, the breadcrumb and the matrix zoom out or across", async ({ page }) => {
    await open(page);
    const before = await box(page, "hm-tile-RELIANCE");
    await expect(page.getByTestId("hm-tile-TCS")).toBeVisible();
    await page.getByTestId("hm-sector-oil-gas-consumable-fuels").click();
    await expect(page.getByTestId("hm-treemap")).toHaveAttribute("data-zoom", "Oil Gas & Consumable Fuels");
    await expect(page.getByTestId("hm-crumb-sector")).toHaveText("Oil Gas & Consumable Fuels");
    await expect(page.getByTestId("hm-tile-TCS")).toHaveCount(0);
    await expect(page.getByTestId("hm-tile-RELIANCE")).toBeVisible();
    const after = await box(page, "hm-tile-RELIANCE");
    expect(after.width * after.height).toBeGreaterThan(before.width * before.height * 2);
    // Click the header again to zoom out.
    await page.getByTestId("hm-sector-oil-gas-consumable-fuels").click();
    await expect(page.getByTestId("hm-treemap")).toHaveAttribute("data-zoom", "");
    await expect(page.getByTestId("hm-tile-TCS")).toBeVisible();
    // Breadcrumb.
    await page.getByTestId("hm-sector-information-technology").click();
    await expect(page.getByTestId("hm-tile-RELIANCE")).toHaveCount(0);
    await page.getByTestId("hm-crumb-all").click();
    await expect(page.getByTestId("hm-crumb-sector")).toHaveCount(0);
    await expect(page.getByTestId("hm-tile-RELIANCE")).toBeVisible();
  });

  test("the rotation matrix ranks sectors by the chosen period and a row click zooms to that sector", async ({ page }) => {
    const { payload } = await open(page);
    const order = (k: PK) => [...payload.sectors].sort((a, b) => (b.returns[k] as number) - (a.returns[k] as number)).map((s) => s.name);
    const ranks = async () => page.locator("[data-testid^=hm-row-]").evaluateAll((els) => els.map((e) => [(e as HTMLElement).dataset.testid, (e as HTMLElement).dataset.rank]));
    for (const k of ["d", "w"] as const) {
      await page.getByTestId(`hm-period-${k}`).click();
      const got = (await ranks()).sort((a, b) => Number(a[1]) - Number(b[1])).map((r) => r[0]);
      expect(got).toEqual(order(k).map((n) => `hm-row-${n.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`));
    }
    const s = payload.sectors.find((x) => x.name === "Information Technology")!;
    for (const k of P) await expect(page.getByTestId(`hm-cell-information-technology-${k}`)).toHaveText(fmt(s.returns[k]));
    await page.getByTestId("hm-row-metals-mining").click();
    await expect(page.getByTestId("hm-treemap")).toHaveAttribute("data-zoom", "Metals & Mining");
    await expect(page.getByTestId("hm-crumb-sector")).toHaveText("Metals & Mining");
  });

  test("the biggest mover is selected first; a tile click selects another and the card follows", async ({ page }) => {
    const { payload } = await open(page);
    // 1D biggest absolute move: TATASTEEL -2.6.
    await expect(page.getByTestId("hm-tile-TATASTEEL")).toHaveAttribute("data-selected", "true");
    await expect(page.getByTestId("hm-stock-name")).toContainText("Tata Steel");
    await page.getByTestId("hm-tile-RELIANCE").click();
    await expect(page.getByTestId("hm-tile-RELIANCE")).toHaveAttribute("data-selected", "true");
    await expect(page.getByTestId("hm-tile-TATASTEEL")).toHaveAttribute("data-selected", "false");
    const s = payload.stocks.find((x) => x.symbol === "RELIANCE")!;
    await expect(page.getByTestId("hm-stock-name")).toContainText("Reliance Industries");
    await expect(page.getByTestId("hm-stock-name")).toContainText("RELIANCE");
    await expect(page.getByTestId("hm-stock-sector")).toContainText("Oil Gas & Consumable Fuels");
    await expect(page.getByTestId("hm-stock-sector")).toContainText("9.50%");
    await expect(page.getByTestId("hm-stock-price")).toContainText("2,910.00");
    await expect(page.getByTestId("hm-stock-pill")).toContainText(fmt(s.returns.d));
    for (const k of P) await expect(page.getByTestId(`hm-stock-${k}`)).toHaveText(fmt(s.returns[k]));
    await expect(page.getByTestId("hm-stock-impact")).toHaveText(fmt(s.index_impact_pct.d, 3));
    await expect(page.getByTestId("hm-stock-relvol")).toHaveText("1.80×");
    // The icon sits beside the name (the monogram tile), and tiles show no logos.
    await expect(page.getByTestId("hm-stock-name").locator("img, [data-entity-icon], span").first()).toBeVisible();
    await expect(page.getByTestId("hm-tile-RELIANCE").locator("img")).toHaveCount(0);
    // A sparkline is not drawn: the route sends no series.
    await expect(page.getByTestId("hm-stock-card").locator("svg")).toHaveCount(0);
  });

  test("tiles never clip their text: large shows ticker, %, price; small shows the ticker only", async ({ page }) => {
    await open(page);
    await expect(page.getByTestId("hm-tile-HDFCBANK")).toHaveAttribute("data-zone", "large");
    await expect(page.getByTestId("hm-tile-HDFCBANK")).toContainText("₹1,650.50");
    const zones = await page.locator("[data-testid^=hm-tile-]").evaluateAll((els) => els.map((e) => {
      const el = e as HTMLElement;
      return { z: el.dataset.zone, over: el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1, text: el.innerText };
    }));
    expect(zones.filter((z) => z.over)).toEqual([]);
    for (const z of zones.filter((x) => x.z === "small")) expect(z.text.includes("%")).toBe(false);
    for (const z of zones.filter((x) => x.z === "medium")) expect(z.text).toContain("%");
  });

  test("a missing return shows a dash on a neutral tile, never 0", async ({ page }) => {
    await open(page);
    await page.getByTestId("hm-period-m").click();
    await expect(page.getByTestId("hm-tile-TATAMOTORS")).toHaveAttribute("data-tone", "none");
    await page.getByTestId("hm-tile-TATAMOTORS").click();
    await expect(page.getByTestId("hm-stock-pill")).toHaveText("—");
    await expect(page.getByTestId("hm-stock-m")).toHaveText("—");
    await expect(page.getByTestId("hm-stock-m")).toHaveAttribute("data-tone", "none");
    await expect(page.getByTestId("hm-stock-d")).toHaveText(fmt(-1.0));
    await expect(page.getByTestId("hm-tile-TATAMOTORS")).not.toContainText("0.00%");
    await expect(page.getByTestId("hm-ask")).toHaveText("Ask about TATAMOTORS ›");
  });

  test("relative volume missing shows a dash with the route's reason", async ({ page }) => {
    await open(page, { relVol: false });
    await expect(page.getByTestId("hm-stock-relvol")).toContainText("—");
    await expect(page.getByTestId("hm-stock-relvol")).toContainText("needs 20 sessions of volume");
  });

  test("Ask why opens the Copilot with the question", async ({ page }) => {
    const { sent } = await open(page);
    await page.getByTestId("hm-tile-RELIANCE").click();
    await expect(page.getByTestId("hm-ask")).toHaveText("Ask why RELIANCE rose 2.40% ›");
    await page.getByTestId("hm-ask").click();
    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]).toBe("Why did RELIANCE rise 2.40% on the day?");
    await expect(page).toHaveURL(/\/app\/t\/asked1/);
    // On the month, a fall reads as a fall.
    await page.goto(HEATMAP);
    await page.getByTestId("hm-period-m").click();
    await page.getByTestId("hm-tile-HINDALCO").click();
    await expect(page.getByTestId("hm-ask")).toHaveText("Ask why HINDALCO fell 7.00% ›");
  });

  test("a failed read shows an error with Retry, and Retry loads the map", async ({ page }) => {
    const { ctl } = await open(page, { fail: true, status: 502, body: { detail: { code: "upstream_unavailable" } } });
    await expect(page.getByTestId("hm-error")).toHaveAttribute("data-code", "upstream_unavailable", { timeout: 15000 });
    await expect(page.getByTestId("hm-error")).toContainText("didn’t answer");
    ctl.failing = false;
    await page.getByTestId("hm-error").getByRole("button", { name: /retry/i }).click();
    await expect(page.getByTestId("hm-verdict")).toBeVisible();
    await expect(page.getByTestId("hm-stale")).toHaveCount(0);
  });

  test("an unknown index is said plainly, with no Retry", async ({ page }) => {
    await open(page, { fail: true, status: 404, body: { detail: { code: "unknown_index", message: "unknown_index: Nifty Foo" } } });
    await expect(page.getByTestId("hm-error")).toHaveAttribute("data-code", "unknown_index", { timeout: 15000 });
    await expect(page.getByTestId("hm-error")).toContainText("does not hold this index");
    await expect(page.getByTestId("hm-error").getByRole("button", { name: /retry/i })).toHaveCount(0);
  });

  test("signed out is said, not shown as a broken map", async ({ page }) => {
    await open(page, { fail: true, status: 401, body: { detail: "Not authenticated" } });
    await expect(page.getByTestId("hm-error").or(page.getByText("Sign in")).first()).toBeVisible({ timeout: 15000 });
  });

  test("the weights note is shown and the headline card says market-cap basis", async ({ page }) => {
    await open(page);
    await expect(page.getByTestId("hm-weight-note")).toContainText("market-cap shares");
    await expect(page.getByTestId("hm-weighted-title")).toContainText("Weighted change (market-cap basis)");
  });

  test("an empty answer says why", async ({ page }) => {
    await open(page, { empty: true });
    await expect(page.getByTestId("hm-empty")).toContainText("No sector heatmap for this index yet");
    await expect(page.getByTestId("hm-empty")).toContainText("no constituents loaded for NIFTY50");
  });

  test("data older than four days says it is stale, in words", async ({ page }) => {
    await open(page, { asOf: iso(10) });
    await expect(page.getByTestId("hm-stale")).toContainText("Stale");
    await expect(page.getByTestId("hm-stale")).toContainText("10 days ago");
    await expect(page.getByTestId("hm-trust-map")).toContainText("Stale");
    await expect(page.getByTestId("hm-trust-map")).toHaveAttribute("data-status", "stale");
  });

  test("a three-day-old close is not stale", async ({ page }) => {
    await open(page, { asOf: iso(3) });
    await expect(page.getByTestId("hm-verdict")).toBeVisible();
    await expect(page.getByTestId("hm-stale")).toHaveCount(0);
  });
});

test.describe("Sector heatmap — entry points", () => {
  test("the Screener has a Sector heatmap chip that opens it, and the Screener still works", async ({ page }) => {
    await open(page, { url: `${APP}/tool/screener` });
    await expect(page.getByTestId("screener-run")).toBeVisible();
    await page.getByTestId("screener-heatmap-link").click();
    await expect(page).toHaveURL(/\/app\/tool\/sector-heatmap$/);
    await expect(page.getByTestId("hm-verdict")).toBeVisible();
  });

  test("the desk's sector card links to the heatmap", async ({ page }) => {
    await open(page, { url: `${APP}/trader/desk` });
    await page.route("**/api/markets/sector-returns", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ as_of: iso(0), source: "NSE index close", sessions: { "1d": 1, "1w": 5, "1m": 21 }, sectors: [] }) }));
    await page.reload();
    await page.getByTestId("desk-sector-heatmap-link").click();
    await expect(page).toHaveURL(/\/app\/tool\/sector-heatmap$/);
    await expect(page.getByTestId("hm-verdict")).toBeVisible();
  });

  // Superseded by the desk redesign (2026-10-27): the Trader rail lists only the Smart trading desk; in Trader mode this route
  // opens Market Desk › Sector Rotation. Covered by copilot-app-desk-shell.spec.ts SH-10 / SH-17; rewritten in step 6.
  test.skip("it is a Trader rail item named Sector rotation and opens the heatmap; Investor mode does not list it", async ({ page }) => {
    await open(page, { url: `${APP}/trader/desk` });
    const rail = page.getByTestId("copilot-rail");
    await expect(rail).toContainText("Screener");
    await expect(rail).not.toContainText(/Sector rotation/);
    await page.getByTestId("mode-pill").click();
    await expect(rail).toContainText("Smart trading desk");
    await rail.getByRole("button", { name: "Sector rotation" }).click();
    await expect(page).toHaveURL(/\/app\/tool\/sector-heatmap$/);
    await expect(page.getByTestId("hm-verdict")).toBeVisible();
  });
});

test.describe("Sector heatmap — phone (390px)", () => {
  test("opens on sectors, drills into one, lists leaders and laggards, and does not scroll sideways", async ({ page }) => {
    const { payload } = await open(page, { width: 390, height: 844 });
    await expect(page.getByTestId("hm-treemap")).toHaveAttribute("data-mode", "sectors");
    await expect(page.getByTestId("hm-verdict")).toHaveText(expectedVerdict(payload, "d"));
    // Leading / lagging: the top and bottom three sectors on the day.
    const sorted = [...payload.sectors].sort((a, b) => (b.returns.d as number) - (a.returns.d as number)).map((s) => s.name);
    const slug = (n: string) => n.toLowerCase().replace(/[^a-z0-9]+/g, "-");
    for (const n of sorted.slice(0, 3)) await expect(page.getByTestId(`hm-leading-${slug(n)}`)).toBeVisible();
    for (const n of sorted.slice(-3)) await expect(page.getByTestId(`hm-lagging-${slug(n)}`)).toBeVisible();
    await expect(page.getByTestId("hm-stock-card")).toHaveCount(0);
    // Touch targets.
    for (const id of ["hm-period-d", "hm-period-w", "hm-period-m", "hm-size-weight", `hm-leading-${slug(sorted[0])}`]) expect((await box(page, id)).height).toBeGreaterThanOrEqual(43.5);
    const noSideways = () => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1 && Array.from(document.querySelectorAll("*")).every((e) => e.getBoundingClientRect().right <= window.innerWidth + 1 || getComputedStyle(e).position === "absolute" || (e as HTMLElement).closest("[data-testid=copilot-scroll]") == null));
    expect(await noSideways()).toBe(true);
    // Period chips recolour the sector tiles.
    await page.getByTestId("hm-period-w").click();
    await expect(page.getByTestId("hm-verdict")).toHaveText(expectedVerdict(payload, "w"));
    // Tap a sector to drill in.
    await page.getByTestId("hm-sector-oil-gas-consumable-fuels").click();
    await expect(page.getByTestId("hm-treemap")).toHaveAttribute("data-mode", "stocks");
    await expect(page.getByTestId("hm-treemap")).toHaveAttribute("data-zoom", "Oil Gas & Consumable Fuels");
    await expect(page.getByTestId("hm-stock-card")).toBeVisible();
    await expect(page.getByTestId("hm-tile-RELIANCE")).toBeVisible();
    await page.getByTestId("hm-tile-ONGC").click();
    await expect(page.getByTestId("hm-stock-name")).toContainText("Oil & Natural Gas Corp");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
    await page.getByTestId("hm-crumb-all").click();
    await expect(page.getByTestId("hm-treemap")).toHaveAttribute("data-mode", "sectors");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  });
});

test.describe("squarify", () => {
  const rect = { x: 10, y: 20, w: 640, h: 400 };
  const items = [13, 9.5, 9, 5.5, 4, 3.9, 3.5, 3, 2.3, 1.8, 1.8, 1.6, 1.4, 1.2, 1, 1, 1, 0.9].map((value, i) => ({ item: i, value }));

  test("areas are proportional to the values and add up to the rectangle", () => {
    const out = squarify(items, rect);
    expect(out).toHaveLength(items.length);
    const total = items.reduce((a, i) => a + i.value, 0);
    let sum = 0;
    for (const o of out) {
      const v = items[o.item].value;
      expect((o.w * o.h) / (rect.w * rect.h)).toBeCloseTo(v / total, 9);
      sum += o.w * o.h;
    }
    expect(sum).toBeCloseTo(rect.w * rect.h, 6);
  });

  test("no two rectangles overlap and all lie inside", () => {
    const out = squarify(items, rect);
    const eps = 1e-6;
    for (const o of out) {
      expect(o.x).toBeGreaterThanOrEqual(rect.x - eps);
      expect(o.y).toBeGreaterThanOrEqual(rect.y - eps);
      expect(o.x + o.w).toBeLessThanOrEqual(rect.x + rect.w + eps);
      expect(o.y + o.h).toBeLessThanOrEqual(rect.y + rect.h + eps);
    }
    for (let i = 0; i < out.length; i += 1) {
      for (let j = i + 1; j < out.length; j += 1) {
        const a = out[i]; const b = out[j];
        const ox = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
        const oy = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
        expect(ox > eps && oy > eps).toBe(false);
      }
    }
  });

  test("tiles are reasonably square and non-positive values are left out", () => {
    const out = squarify([...items, { item: 99, value: 0 }, { item: 98, value: -3 }, { item: 97, value: NaN }], rect);
    expect(out.map((o) => o.item).sort((a, b) => a - b)).toEqual(items.map((i) => i.item));
    for (const o of out) expect(Math.max(o.w / o.h, o.h / o.w)).toBeLessThan(6);
    expect(squarify([], rect)).toEqual([]);
    expect(squarify(items, { x: 0, y: 0, w: 0, h: 10 })).toEqual([]);
  });
});

test.describe("Sector heatmap — screenshots", () => {
  test.skip(!process.env.SHOTS_DIR, "set SHOTS_DIR to write screenshots");
  test("desktop 1440, zoomed, and phone 390", async ({ page }) => {
    const dir = process.env.SHOTS_DIR as string;
    await open(page, { width: 1440, height: 1900 });
    await expect(page.getByTestId("hm-verdict")).toBeVisible();
    await page.screenshot({ path: `${dir}/heatmap-1440.png`, fullPage: true });
    await page.getByTestId("hm-sector-oil-gas-consumable-fuels").click();
    await page.screenshot({ path: `${dir}/heatmap-1440-zoom.png`, fullPage: true });
    await page.setViewportSize({ width: 390, height: 2300 });
    await page.goto(HEATMAP);
    await expect(page.getByTestId("hm-verdict")).toBeVisible();
    await page.screenshot({ path: `${dir}/heatmap-390.png`, fullPage: true });
    await page.getByTestId("hm-sector-oil-gas-consumable-fuels").click();
    await page.screenshot({ path: `${dir}/heatmap-390-zoom.png`, fullPage: true });
  });
});
