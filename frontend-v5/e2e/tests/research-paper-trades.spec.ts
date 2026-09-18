/**
 * Research → Paper (mocked layer). Test cases TC-P23..TC-P28 in test_reports/paper_trades_engine_20260918_1338.md.
 *
 * MOCK — not real data: every /api/paper-trades response here is a fixture (e2e/fixtures/paper-*.json). The portfolio,
 * trade and evaluation fixtures were captured from the staging DaaS on 2026-09-18 after the engine's forward and replay
 * runs; paper-live-P5-NEXT.json is constructed (one position per live state). auth/me is mocked too. The staging run
 * against real data is TC-P29/TC-P30.
 */
import { test, expect, type Page } from "@playwright/test";
import fs from "fs";
import path from "path";
import { mockAuthAs } from "../helpers/api-mock";

const FX = path.join(process.cwd(), "e2e", "fixtures");
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(FX, name), "utf-8"));
const has = (name: string) => fs.existsSync(path.join(FX, name));
// The page is a paper simulation of the owner's design, which names entry, target, stop and hold; advice words stay banned.
const BANNED = /\b(buy|sell|recommend(ed|ation)?|multibagger|top pick|sure[- ]shot|guaranteed)\b/i;

type Reply = { status: number; body: unknown };
const calls: string[] = [];

async function mockPaper(page: Page, over: { portfolio?: (u: URL) => Reply | null; evaluation?: (u: URL) => Reply | null; live?: () => Reply } = {}) {
  await page.route("**/api/paper-trades/**", (route) => {
    const u = new URL(route.request().url());
    calls.push(u.pathname + u.search);
    const reply = (r: Reply) => route.fulfill({ status: r.status, contentType: "application/json", body: JSON.stringify(r.body) });
    const q = (k: string) => u.searchParams.get(k);
    if (u.pathname.endsWith("/portfolio")) {
      const o = over.portfolio?.(u); if (o) return reply(o);
      const base = `paper-portfolio-${q("sample") ?? "forward"}-${q("portfolio") ?? "P5-NEXT"}`;
      const d = q("prediction_date");
      if (!d) return reply({ status: 200, body: load(`${base}.json`) });
      if (has(`${base}-${d}.json`)) return reply({ status: 200, body: load(`${base}-${d}.json`) });
      const latest = load(`${base}.json`);
      return latest.data.prediction_date === d ? reply({ status: 200, body: latest }) : reply({ status: 404, body: { detail: "not_found" } });
    }
    if (u.pathname.endsWith("/evaluation")) {
      const o = over.evaluation?.(u); if (o) return reply(o);
      const f = `paper-evaluation-${q("sample")}-${q("portfolio")}.json`;
      return reply({ status: 200, body: has(f) ? load(f) : { data: { status: "none", sample: q("sample"), portfolio: q("portfolio") } } });
    }
    if (u.pathname.endsWith("/live")) {
      if (over.live) return reply(over.live());
      const f = `paper-live-${q("portfolio")}.json`;
      return reply({ status: 200, body: has(f) ? load(f) : { data: { status: "empty", portfolio: q("portfolio"), positions: [] } } });
    }
    const m = u.pathname.match(/\/trades\/(\d+)$/);
    if (m) return has(`paper-trade-${m[1]}.json`) ? reply({ status: 200, body: load(`paper-trade-${m[1]}.json`) }) : reply({ status: 404, body: { detail: "not_found" } });
    return reply({ status: 404, body: { detail: "not_found" } });
  });
}

async function openPaper(page: Page) {
  await page.goto("/v5/research");
  await page.getByTestId("rail-paper").click();
  await expect(page.getByTestId("paper-screen")).toBeVisible();
}

const pct2 = (x: number) => { const t = Math.abs(x * 100).toFixed(2); return x > 0 ? `+${t}%` : x < 0 ? `−${t}%` : "0.00%"; };
const p1 = (x: number) => (x * 100 < 0.1 ? "<0.1%" : `${(x * 100).toFixed(1)}%`);
const rupees = (x: number) => "₹" + Math.round(x).toLocaleString("en-IN");

async function cleanText(page: Page) {
  const t = await page.getByTestId("paper-screen").innerText();
  expect(t).not.toMatch(/NaN|undefined|\[object Object\]|Infinity/);
  const disc = await page.getByTestId("pt-disclaimer").innerText();
  expect(t.replace(disc, "")).not.toMatch(BANNED);
}

test.describe("Paper — access", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("TC-P23 without move_odds the rail item is absent", async ({ page }) => {
    await mockAuthAs(page, "user-profile-onboarded.json");
    await mockPaper(page);
    await page.goto("/v5/research");
    await expect(page.getByTestId("rail-feed")).toBeVisible();
    await expect(page.getByTestId("rail-paper")).toHaveCount(0);
  });

  test("TC-P27 a 403 shows the not-enabled state and no numbers", async ({ page }) => {
    await mockAuthAs(page, "user-profile-move-odds.json");
    await mockPaper(page, { portfolio: () => ({ status: 403, body: { detail: "feature_not_enabled" } }) });
    await openPaper(page);
    await expect(page.getByTestId("pt-state-no_access")).toBeVisible();
    expect(await page.getByTestId("paper-screen").innerText()).not.toMatch(/\d+\.\d+%|₹\d/);
  });

  test("TC-P27 upstream error offers a retry and shows no numbers; empty sample says so", async ({ page }) => {
    await mockAuthAs(page, "user-profile-move-odds.json");
    let fail = true;
    await mockPaper(page, { portfolio: (u) => (u.searchParams.get("sample") === "replay" ? { status: 200, body: { data: { status: "empty", dates: [] } } }
                                                 : fail ? { status: 502, body: { detail: "upstream_unavailable" } } : null) });
    await openPaper(page);
    await expect(page.getByTestId("pt-state-error")).toBeVisible();
    expect(await page.getByTestId("paper-screen").innerText()).not.toMatch(/₹\d/);
    fail = false;
    await page.getByRole("button", { name: "Retry" }).click();
    await expect(page.getByTestId("pt-row-SHAREINDIA")).toBeVisible();
    await page.getByTestId("pt-sample-replay").click();
    await expect(page.getByTestId("pt-state-empty")).toBeVisible();
  });
});

test.describe("Paper — today's portfolio", () => {
  test.use({ viewport: { width: 1280, height: 800 } });
  test.beforeEach(async ({ page }) => {
    calls.length = 0;
    await mockAuthAs(page, "user-profile-move-odds.json");
    await mockPaper(page);
    await openPaper(page);
    await expect(page.getByTestId("pt-row-SHAREINDIA")).toBeVisible();
  });

  test("TC-P23 latest forward selection renders the frozen values, marked not counted, with live status", async ({ page }) => {
    const fx = load("paper-portfolio-forward-P5-NEXT.json").data;
    const disc = await page.getByTestId("pt-disclaimer").boundingBox();
    const table = await page.getByTestId("pt-table").boundingBox();
    expect(disc && table && disc.y + disc.height <= table.y).toBeTruthy();
    await expect(page.getByTestId("pt-disclaimer")).toContainText("does not constitute investment advice");
    await expect(page.getByTestId("pt-notcounted-banner")).toBeVisible();
    await expect(page.getByTestId("pt-provenance")).toContainText(fx.provenance.model_version);
    const rows = page.locator('[data-testid^="pt-row-"]');
    await expect(rows).toHaveCount(5);
    for (const p of fx.positions) {
      const row = page.getByTestId(`pt-row-${p.symbol}`);
      await expect(row).toContainText(p1(p.movement_probability));
      await expect(page.getByTestId(`pt-entry-${p.symbol}`)).toContainText("open of");       // pending: no price is invented
      await expect(page.getByTestId(`pt-ret-${p.symbol}`)).toHaveText("—");
    }
    await expect(page.getByTestId("pt-pnl")).toHaveText("—");
    await expect(page.getByTestId("pt-live-RATNAVEER")).toHaveText("Exit · target");
    await expect(page.getByTestId("pt-live-TEGA")).toHaveText("Await entry");
    await expect(page.getByTestId("pt-live")).toContainText("provisional");
    // signals never appear without the measured record beside them (owner decision 2026-09-18)
    const ev = page.getByTestId("pt-live-evidence");
    await expect(ev).toContainText("lost money in testing");
    await expect(ev).toContainText("402 sessions");
    await expect(ev).toContainText("FAIL");
    // and the session chart draws the pre-registered levels on the candles
    await expect(page.getByTestId("pt-chart-SHAREINDIA")).toBeVisible();
    await expect(page.getByTestId("pt-chart-SHAREINDIA")).toContainText("target");
    await expect(page.getByTestId("pt-chart-SHAREINDIA")).toContainText("stop");
    await expect(page.locator('[data-testid^="pt-chart-"]')).toHaveCount(4);   // the no-entry position has no bars
    await cleanText(page);
  });

  test("TC-P23 portfolio switch and an older date: official entries, levels and EOD-1 from the record", async ({ page }) => {
    await page.getByTestId("pt-portfolio-P10-NEXT").click();
    await expect(page.getByTestId("pt-row-ALOKINDS")).toBeVisible();
    await page.getByTestId("pt-date").selectOption("2026-09-16");
    await expect(page.getByTestId("pt-row-PNCINFRA")).toBeVisible();
    const fx = load("paper-portfolio-forward-P10-NEXT-2026-09-16.json").data;
    for (const p of fx.positions) {
      await expect(page.getByTestId(`pt-entry-${p.symbol}`)).toHaveText(`₹${p.entry_price.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);
      await expect(page.getByTestId(`pt-ret-${p.symbol}`)).toContainText(pct2(p.exits["EOD-1"].net_return));
      await expect(page.getByTestId(`pt-ret-${p.symbol}`)).toContainText("record");
    }
    await expect(page.getByTestId("pt-row-DELTACORP")).toContainText("stop at 10-day support");
    await expect(page.getByTestId("pt-row-PNCINFRA")).toContainText("stop capped at 8%");
    await expect(page.getByTestId("pt-live")).toHaveCount(0);                                      // live only for the latest selection
    expect(calls.some((c) => c.includes("prediction_date=2026-09-16") && c.includes("portfolio=P10-NEXT"))).toBeTruthy();
    await cleanText(page);
  });

  test("TC-P24 sizing: the loss limit binds at the pre-registered stops, then equal legs; custom basket; fixed stop", async ({ page }) => {
    await page.getByTestId("pt-portfolio-P10-NEXT").click();
    await page.getByTestId("pt-date").selectOption("2026-09-16");
    await expect(page.getByTestId("pt-row-PNCINFRA")).toBeVisible();
    // ₹1,00,000, equal, limit 5%: each leg may lose 1% of capital at its stop → notional = 1% / stop distance, capped at 20%
    await expect(page.getByTestId("pt-alloc-PNCINFRA")).toHaveText(rupees(100000 * 0.01 / 0.08));              // 8% cap → ₹12,500
    await expect(page.getByTestId("pt-alloc-DELTACORP")).toHaveText(rupees(100000 * 0.01 / ((55.56 - 51.66) / 55.56)));   // support stop
    await expect(page.getByTestId("pt-binding")).toContainText("This limit binds");
    // at-risk = Σ whole units × entry × stop distance
    const legs = [[132.48, 0.08, 12500], [55.56, (55.56 - 51.66) / 55.56, 100000 * 0.01 / ((55.56 - 51.66) / 55.56)], [1549, 0.08, 12500], [209.6, 0.08, 12500], [113.35, 0.08, 12500]];
    const risk = legs.reduce((a, [px, sd, alloc]) => a + Math.floor(alloc / px) * px * sd, 0);
    await expect(page.getByTestId("pt-atrisk")).toHaveText(rupees(risk));
    await page.getByTestId("pt-limit-8").click();
    for (const s of ["PNCINFRA", "RPEL", "KPEL", "AEROENTER", "DELTACORP"]) await expect(page.getByTestId(`pt-alloc-${s}`)).toHaveText("₹20,000");
    await expect(page.getByTestId("pt-binding")).toContainText("set by the allocation rule");
    await page.getByTestId("pt-capital-500000").click();
    await expect(page.getByTestId("pt-alloc-PNCINFRA")).toHaveText("₹1,00,000");
    // a fixed 3% what-if stop: returns switch from the record to the what-if path
    await page.getByTestId("pt-stop-3").click();
    await expect(page.getByTestId("pt-ret-PNCINFRA")).toContainText("what-if");
    await page.getByTestId("pt-stop-prereg").click();
    // custom basket of two: 8% limit over two legs at an 8% stop → 50% each
    await page.getByTestId("pt-capital-100000").click();
    await page.getByTestId("pt-basket-custom").click();
    await expect(page.getByTestId("pt-empty-basket")).toBeVisible();
    await page.getByTestId("pt-pick-PNCINFRA").click();
    await page.getByTestId("pt-pick-RPEL").click();
    await expect(page.locator('[data-testid^="pt-row-"]')).toHaveCount(2);
    await expect(page.getByTestId("pt-alloc-PNCINFRA")).toHaveText("₹50,000");
    await expect(page.getByTestId("pt-alloc-RPEL")).toHaveText("₹50,000");
    await cleanText(page);
  });

  test("TC-P25 trade path: six-session table, lifecycle log and every exit mode, from the trade record", async ({ page }) => {
    await page.getByTestId("pt-sample-replay").click();
    await page.getByTestId("pt-date").selectOption("2025-03-10");
    await expect(page.getByTestId("pt-replay-banner")).toBeVisible();
    await page.getByTestId("pt-open-POCL").click();
    await expect(page.getByTestId("pt-trade-symbol")).toHaveText("POCL");
    const t = load("paper-trade-531.json").data;
    await expect(page.locator('[data-testid^="pt-path-"]')).toHaveCount(t.observations.length);
    await expect(page.getByTestId("pt-path-5")).toContainText(pct2(t.observations[5].return_from_entry));
    for (const m of ["EOD-1", "EOD-3", "EOD-5", "FIXED", "TARGET_STOP"]) {
      await expect(page.getByTestId(`pt-exit-${m}`)).toContainText(pct2(t.exits[m].net_return));
    }
    await expect(page.getByTestId("pt-log").locator("li")).toHaveCount(t.events.length);
    await expect(page.getByTestId("pt-log").locator("li").first()).toContainText("PREDICTED");
    await expect(page.getByTestId("pt-log").locator("li").last()).toContainText("EVALUATED");
    await page.getByTestId("pt-trade-pick-MPSLTD").click();
    await expect(page.getByTestId("pt-trade-symbol")).toHaveText("MPSLTD");
    await cleanText(page);
  });
});

test.describe("Paper — evaluation", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("TC-P26 forward and replay are separate payloads; not established below 60 sessions", async ({ page }) => {
    calls.length = 0;
    await mockAuthAs(page, "user-profile-move-odds.json");
    await mockPaper(page);
    await openPaper(page);
    await page.getByTestId("pt-view-eval").click();
    await expect(page.getByTestId("pt-statement")).toContainText("Not established");
    await expect(page.getByTestId("pt-statement")).toContainText("0 counted sessions");
    await page.getByTestId("pt-sample-replay").click();
    const ev = load("paper-evaluation-replay-P5-NEXT.json").data.evaluation;
    await expect(page.getByTestId("pt-statement")).toContainText(ev.statement.text);
    const head = ev.modes.find((m: { mode: string }) => m.mode === "EOD-1");
    await expect(page.getByTestId("pt-eval-net")).toHaveText(pct2(head.net_mean));
    await expect(page.getByTestId("pt-eval-edge")).toHaveText(pct2(head.edge_vs_a_all.mean));
    await expect(page.locator('[data-testid^="pt-eval-mode-"]')).toHaveCount(5);
    await expect(page.getByTestId("pt-bench-A_ALL")).toBeVisible();
    await expect(page.getByTestId("pt-bench-D_NIFTY50")).toBeVisible();
    await page.getByTestId("pt-buckets-universe").click();
    await expect(page.locator('[data-testid^="pt-bucket-"]')).toHaveCount(ev.buckets.universe.length);
    const evalCalls = calls.filter((c) => c.includes("/evaluation"));
    expect(evalCalls.every((c) => /sample=(forward|replay)/.test(c) && !/sample=.*sample=/.test(c))).toBeTruthy();
    await cleanText(page);
  });
});

test.describe("Paper — phone width", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("TC-P28 no horizontal page scroll on any of the three screens", async ({ page }) => {
    await mockAuthAs(page, "user-profile-move-odds.json");
    await mockPaper(page);
    await page.goto("/v5/research");
    await page.getByTestId("mnav-paper").click();
    await expect(page.getByTestId("paper-screen")).toBeVisible();
    await expect(page.getByTestId("pt-row-SHAREINDIA")).toBeVisible();
    // neither the document nor the screen's own scroll region may scroll sideways (wide tables scroll inside their wrappers)
    const noScroll = async () => page.evaluate(() => {
      const doc = document.documentElement;
      const region = (document.querySelector('[data-testid="paper-screen"]') as HTMLElement).parentElement as HTMLElement;
      return doc.scrollWidth <= doc.clientWidth + 1 && region.scrollWidth <= region.clientWidth + 1;
    });
    expect(await noScroll()).toBeTruthy();
    await page.getByTestId("pt-view-trade").click();
    await expect(page.getByTestId("pt-trade")).toBeVisible();
    expect(await noScroll()).toBeTruthy();
    await page.getByTestId("pt-view-eval").click();
    await expect(page.getByTestId("pt-statement")).toBeVisible();
    expect(await noScroll()).toBeTruthy();
  });
});
