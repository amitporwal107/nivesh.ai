/**
 * Research → Move odds (mocked layer). Test cases TC-20..TC-27 in test_reports/move_odds_research_20260916_2351.md;
 * TC-42..TC-45 (entry-setup diagnostics) in test_reports/move_odds_diagnostics_20260917_1221.md.
 *
 * MOCK — not real data: every /api/move-odds response here is a fixture (e2e/fixtures/move-odds-*.json, shaped like
 * backend/routes/move_odds.py, values copied from the 2026-09-17 v4 snapshot). auth/me is mocked too. The staging run
 * against real data is TC-28..TC-30.
 */
import { test, expect, type Page } from "@playwright/test";
import fs from "fs";
import path from "path";
import { mockAuthAs } from "../helpers/api-mock";

const FX = path.join(process.cwd(), "e2e", "fixtures");
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(FX, name), "utf-8"));
const HEADS = ["p_up5_1d", "p_down5_1d", "p_up10_1d", "p_down10_1d"] as const;
// "entry signal" is allowed on this page by the owner's decision of 2026-09-17 (decisions-log.md); everything else stays banned.
const BANNED = /\b(buy|sell|invest|hold|stop|target[_ ]price|conviction|position[_ ]size|multibagger|best|top pick)\b/i;
// MOCK — not real data: an extra media event so the withheld-headline path renders (the real PNCINFRA media report is de-duplicated).
const MOCK_MEDIA_EVENT = {
  ord: 2, event_time: "2026-09-15T10:13:00+05:30", source_label: "Economic Times", is_media: true, event_type: "REGULATORY",
  event_subtype: "order_win", direction: "negative", title: null, url: "https://example.com/mock-media", method: "rules",
};

type Reply = { status: number; body: unknown };
const liveCalls: string[] = [];
async function mockOdds(page: Page, latest?: (head: string) => Reply, diagnostics?: () => Reply) {
  await page.route("**/api/move-odds/diagnostics**", (route) => {
    const r = diagnostics ? diagnostics() : { status: 200, body: load("move-odds-diagnostics.json") };
    return route.fulfill({ status: r.status, contentType: "application/json", body: JSON.stringify(r.body) });
  });
  await page.route("**/api/move-odds/live**", (route) => {
    const syms = (new URL(route.request().url()).searchParams.get("symbols") ?? "").split(",");
    liveCalls.push(syms.join(","));
    const body = load("move-odds-live.json");   // MOCK — a frozen Yahoo snapshot; only the requested symbols are answered
    body.quotes = body.quotes.filter((q: { symbol: string }) => syms.includes(q.symbol));
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.route("**/api/move-odds/latest**", (route) => {
    const head = new URL(route.request().url()).searchParams.get("head") ?? "p_up5_1d";
    const r = latest ? latest(head) : { status: 200, body: load(`move-odds-latest-${head}.json`) };
    return route.fulfill({ status: r.status, contentType: "application/json", body: JSON.stringify(r.body) });
  });
  await page.route("**/api/move-odds/stocks/**", (route) => {
    const sym = decodeURIComponent(route.request().url().split("/stocks/")[1].split("?")[0]);
    const file = path.join(FX, `move-odds-stock-${sym}.json`);
    if (!fs.existsSync(file)) return route.fulfill({ status: 404, contentType: "application/json", body: '{"detail":"not_found"}' });
    const body = load(`move-odds-stock-${sym}.json`);
    if (sym === "PNCINFRA") body.data.events = [...body.data.events, MOCK_MEDIA_EVENT];
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
}

function pct(p: number | null): string {
  if (p == null) return "—";
  const v = p * 100;
  return v < 0.1 ? "<0.1%" : `${v.toFixed(1)}%`;
}

async function openOdds(page: Page) {
  await page.goto("/v5/research");
  await page.getByTestId("rail-odds").click();
  await expect(page.getByTestId("move-odds-screen")).toBeVisible();
}

test.describe("Move odds — access", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("TC-20 without move_odds the rail item is absent", async ({ page }) => {
    await mockAuthAs(page, "user-profile-onboarded.json");
    await mockOdds(page);
    await page.goto("/v5/research");
    await expect(page.getByTestId("rail-feed")).toBeVisible();
    await expect(page.getByTestId("rail-odds")).toHaveCount(0);
    await expect(page.getByTestId("move-odds-screen")).toHaveCount(0);
  });

  test("TC-20 with move_odds the rail item opens the screen", async ({ page }) => {
    await mockAuthAs(page, "user-profile-move-odds.json");
    await mockOdds(page);
    await openOdds(page);
  });

  test("TC-25 a 403 shows the not-enabled state and no percentages", async ({ page }) => {
    await mockAuthAs(page, "user-profile-move-odds.json");
    await mockOdds(page, () => ({ status: 403, body: { detail: "feature_not_enabled" } }));
    await openOdds(page);
    await expect(page.getByTestId("mo-state-no_access")).toBeVisible();
    await expect(page.locator('[data-testid^="mo-pct-"]')).toHaveCount(0);
    expect(await page.getByTestId("move-odds-screen").innerText()).not.toMatch(/\d+\.\d%/);
  });
});

test.describe("Move odds — final estimates", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test.beforeEach(async ({ page }) => {
    await mockAuthAs(page, "user-profile-move-odds.json");
    await mockOdds(page);
    await openOdds(page);
    await expect(page.getByTestId("mo-row-PNCINFRA")).toBeVisible();
  });

  test("TC-21 disclaimer above the numbers, provenance, four tabs with base rates", async ({ page }) => {
    const disc = await page.getByTestId("mo-disclaimer").boundingBox();
    const table = await page.locator(".mo-table").boundingBox();
    expect(disc && table && disc.y + disc.height <= table.y).toBeTruthy();
    await expect(page.getByTestId("mo-disclaimer")).toContainText("does not constitute investment advice");
    const prov = page.getByTestId("mo-provenance");
    await expect(prov).toContainText("Wed 16 Sep");
    await expect(prov).toContainText("Thu 17 Sep");
    await expect(prov).toContainText("994 of 1,000 stocks scored");
    for (const h of HEADS) {
      const base = load(`move-odds-latest-${h}.json`).data.base_rate;
      await expect(page.getByTestId(`mo-tab-${h}`)).toContainText(`base rate ${pct(base)}`);
    }
  });

  test("TC-22 sorted by estimate, no rank column, 50 per page, search filters", async ({ page }) => {
    const headers = (await page.locator(".mo-table thead th").allInnerTexts()).map((t) => t.trim());
    expect(headers.join("|")).not.toMatch(/#|rank/i);
    const rows = page.locator('tbody tr[data-testid^="mo-row-"]');
    await expect(rows).toHaveCount(50);
    const shown = await page.locator('[data-testid^="mo-pct-"]').allInnerTexts();
    const values = load("move-odds-latest-p_up5_1d.json").data.rows.map((r: { p: number }) => r.p);
    const sorted = [...values].sort((a, b) => b - a);
    expect(shown).toEqual(sorted.slice(0, 50).map(pct));
    await page.getByTestId("mo-page-next").click();
    await expect(rows).toHaveCount(10);
    await page.getByTestId("mo-search").fill("antelopus");
    await expect(page.getByTestId("mo-count")).toHaveText("1 stocks");
    await expect(page.getByTestId("mo-row-ANTELOPUS")).toBeVisible();
    await page.getByTestId("mo-tab-p_down5_1d").click();
    await expect(page.getByTestId("mo-tab-p_down5_1d")).toHaveAttribute("aria-selected", "true");
  });

  test("TC-23 details show dated inputs, events, a withheld media headline and the stock's band", async ({ page }) => {
    await page.getByTestId("mo-details-PNCINFRA").click();
    const detail = page.getByTestId("mo-detail-PNCINFRA");
    await expect(detail).toBeVisible();
    const inputs = page.getByTestId("mo-inputs");
    await expect(inputs).toContainText("Close vs previous close");
    await expect(inputs).toContainText("Delivery");
    await expect(inputs).toContainText("Tue 15 Sep · published a day late");
    const events = page.getByTestId("mo-events");
    await expect(events).toContainText("PNCINFRA: Action(s) taken or orders passed");
    await expect(events).toContainText("Media report · headline not shown");
    await expect(page.locator(".mo-bands tr.here")).toContainText("30–40%");
  });

  test("TC-26 rendered text carries no recommendation vocabulary", async ({ page }) => {
    await page.getByTestId("mo-details-PNCINFRA").click();
    await expect(page.getByTestId("mo-detail-PNCINFRA")).toBeVisible();
    const text = await page.getByTestId("move-odds-screen").innerText();
    const hit = text.match(BANNED);
    expect(hit, `banned word: ${hit?.[0]}`).toBeNull();
  });

  test("TC-34/36 entry signal pill and state follow the five checks, with the failed test stated beside them", async ({ page }) => {
    await page.getByTestId("mo-details-PNCINFRA").click();
    await expect(page.getByTestId("mo-signal-PNCINFRA")).toHaveText("Entry signal · since 11:15");      // row pill
    await expect(page.getByTestId("mo-signal-ANTELOPUS")).toHaveCount(0);                                  // 1 of 5: no pill
    const checks = page.getByTestId("mo-checks-PNCINFRA");
    await expect(page.getByTestId("mo-signal-state-PNCINFRA")).toContainText("Entry signal ON since the 11:15-12:15 bar");
    await expect(checks.locator("li[data-met=\"yes\"]")).toHaveCount(5);
    await expect(checks).toContainText("All five first held at the 11:15-12:15 bar");
    await expect(page.getByTestId("mo-checks-record")).toContainText("failed that test");
    await expect(page.getByTestId("mo-checks-record")).toContainText("-0.61% per trade");
    const text = await page.getByTestId("move-odds-screen").innerText();
    const hit = text.match(BANNED);
    expect(hit, `banned word: ${hit?.[0]}`).toBeNull();
    await page.getByTestId("mo-details-PNCINFRA").click();
    await page.getByTestId("mo-details-ANTELOPUS").click();
    await expect(page.getByTestId("mo-checks-ANTELOPUS").locator("li[data-met=\"yes\"]")).toHaveCount(1);
    await expect(page.getByTestId("mo-checks-ANTELOPUS")).toContainText("have not held together yet today");
    await expect(page.getByTestId("mo-signal-state-ANTELOPUS")).toContainText("Entry signal OFF · 1 of 5 checks met");
    const detailText = await page.getByTestId("move-odds-screen").innerText();         // details open: the D2 scan covers the checks panel too
    expect(detailText.match(BANNED), "banned vocabulary with details open").toBeNull();
    await expect(page.getByTestId("mo-paper-ANTELOPUS")).toHaveCount(0);                                 // no early signal: no paper trade
  });

  test("TC-37 paper-trade P&L indicator on a signalled row, both exit rules in Details", async ({ page }) => {
    const live = load("move-odds-live.json");
    const p = live.quotes[0].paper;
    const rupees = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}₹${Math.abs(v).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
    await expect(page.getByTestId("mo-paper-PNCINFRA")).toHaveText(`Paper ${rupees(p.exits[0].net)} · +5% at ${p.exits[0].at}`);
    await expect(page.getByTestId("mo-paper-PNCINFRA")).toHaveClass(/up/);
    await page.getByTestId("mo-details-PNCINFRA").click();
    const box = page.getByTestId("mo-papertrade-PNCINFRA");
    await expect(box).toContainText(`1,000 shares from ₹${p.entry_price.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} at ${p.entry_time}`);
    await expect(box.locator("tbody tr")).toHaveCount(2);
    await expect(box.locator("tbody tr").nth(0)).toContainText(`reached ${p.exits[0].at}`);
    await expect(box.locator("tbody tr").nth(1)).toContainText(p.exits[1].state);
    await expect(box.locator("tbody tr").nth(1)).toContainText(rupees(p.exits[1].net));
    const text = await page.getByTestId("move-odds-screen").innerText();
    expect(text.match(BANNED), "banned vocabulary").toBeNull();
  });

  test("TC-27 every shown percentage equals the API value at one decimal", async ({ page }) => {
    const data = load("move-odds-latest-p_up5_1d.json").data;
    for (const r of data.rows.slice(0, 50)) {
      await expect(page.getByTestId(`mo-pct-${r.symbol}`)).toHaveText(pct(r.p));
    }
  });
});

test.describe("Move odds — research diagnostics (entry setups rejected 2026-09-17)", () => {
  test.use({ viewport: { width: 1280, height: 800 } });
  const pct2 = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v * 100).toFixed(2)}%`;

  test("TC-42 four cards in fixed order with their status, and every number equals the API", async ({ page }) => {
    await mockAuthAs(page, "user-profile-move-odds.json");
    await mockOdds(page);
    await openOdds(page);
    const d = load("move-odds-diagnostics.json").data;
    const section = page.getByTestId("mo-diagnostics");
    await expect(section.locator("article")).toHaveCount(4);
    expect(await section.locator("article").evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")))).toEqual(["mo-diag-A", "mo-diag-B", "mo-diag-C", "mo-diag-D"]);
    await expect(page.getByTestId("mo-diag-summary")).toContainText("Tested 24 Oct 2024 – 8 Sep 2026 · 0 of 8 validated");
    for (const s of d.setups) {
      const card = page.getByTestId(`mo-diag-${s.id}`);
      await expect(card.locator("h4")).toHaveText(s.name);
      await expect(page.getByTestId(`mo-diag-status-${s.id}`)).toHaveText(["A", "B"].includes(s.id) ? "Not validated" : "Research only; insufficient sample");
      await expect(page.getByTestId(`mo-diag-rs-${s.id}`)).toHaveText("Research status · Not a trading signal");
      if (["A", "B"].includes(s.id)) await expect(card).toContainText("Setup detected — not validated");
      await expect(card).toContainText(s.explanation);
      for (const t of s.trades) {
        const row = page.getByTestId(`mo-diag-${s.id}-${t.trade === "5%" ? "5" : "10"}`);
        await expect(row.locator("td").nth(0)).toHaveText(t.trades.toLocaleString("en-IN"));
        await expect(row.locator("td").nth(1)).toHaveText(pct2(t.mean_net));
        await expect(row.locator("td").nth(2)).toHaveText(pct2(t.baseline_mean_net));
        await expect(row.locator("td").nth(3)).toHaveText("Failed validation");
      }
    }
    expect(d.setups.find((s: { id: string }) => s.id === "A").trades[0].mean_net).toBeCloseTo(-0.0065, 4);   // the published −0.65%
  });

  test("TC-43 nothing in the section reads as a trade, and cards are never reordered by result", async ({ page }) => {
    await mockAuthAs(page, "user-profile-move-odds.json");
    const body = load("move-odds-diagnostics.json");
    body.data.setups = [...body.data.setups].reverse();                                       // MOCK — API order D, C, B, A
    body.data.setups[0].trades[0].mean_net = 0.05;                                            // MOCK — D given the "best" number
    await mockOdds(page, undefined, () => ({ status: 200, body }));
    await openOdds(page);
    const section = page.getByTestId("mo-diagnostics");
    await expect(section.locator("article")).toHaveCount(4);
    expect(await section.locator("article").evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")))).toEqual(["mo-diag-A", "mo-diag-B", "mo-diag-C", "mo-diag-D"]);
    const text = await section.innerText();
    expect(text.match(BANNED), "banned vocabulary").toBeNull();
    expect(text).not.toMatch(/₹|\brank\b|#\d|conviction|entry price|\blevel\b/i);
    await expect(section.locator(".mo-up, .mo-down, .mo-signal, .mo-paper")).toHaveCount(0);
    const inks = await section.locator("td").evaluateAll((els) => [...new Set(els.map((e) => getComputedStyle(e).color))]);
    expect(inks.length).toBe(1);                                                              // every number in one ink colour
  });

  test("TC-44 a diagnostics failure shows retry and no numbers, and the estimates still render", async ({ page }) => {
    await mockAuthAs(page, "user-profile-move-odds.json");
    let fail = true;
    await mockOdds(page, undefined, () => (fail ? { status: 503, body: { detail: "diagnostics_unavailable" } } : { status: 200, body: load("move-odds-diagnostics.json") }));
    await openOdds(page);
    await expect(page.getByTestId("mo-row-PNCINFRA")).toBeVisible();
    await expect(page.getByTestId("mo-diag-error")).toContainText("Research diagnostics could not be loaded");
    await expect(page.getByTestId("mo-diagnostics").locator("td")).toHaveCount(0);
    await expect(page.getByTestId("mo-diagnostics")).not.toContainText("%");
    fail = false;
    await page.getByTestId("mo-diag-retry").click();
    await expect(page.getByTestId("mo-diagnostics").locator("article")).toHaveCount(4);
  });
});

test.describe("Move odds — research diagnostics on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("TC-45 cards stack in one column and the page does not scroll sideways", async ({ page }) => {
    await mockAuthAs(page, "user-profile-move-odds.json");
    await mockOdds(page);
    await page.goto("/v5/research");
    await page.getByTestId("mnav-odds").click();
    const a = page.getByTestId("mo-diag-A"), b = page.getByTestId("mo-diag-B");
    await a.scrollIntoViewIfNeeded();
    await expect(a).toBeVisible();
    const [ba, bb] = [await a.boundingBox(), await b.boundingBox()];
    expect(bb!.y).toBeGreaterThan(ba!.y + ba!.height - 1);                                    // B below A, not beside it
    expect(Math.abs(bb!.x - ba!.x)).toBeLessThanOrEqual(1);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
  });
});

test.describe("Move odds — no numbers when there is nothing valid to show", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("TC-24 not published", async ({ page }) => {
    await mockAuthAs(page, "user-profile-move-odds.json");
    await mockOdds(page, (head) => ({ status: 200, body: { data: { status: "not_published", head, expected_session: "2026-09-18", last_published_for: "2026-09-17", rows: [] } } }));
    await openOdds(page);
    await expect(page.getByTestId("mo-state-not_published")).toContainText("Fri 18 Sep");
    await expect(page.locator('[data-testid^="mo-pct-"]')).toHaveCount(0);
    await expect(page.getByTestId("mo-provenance")).toHaveCount(0);
  });

  test("TC-24 withheld", async ({ page }) => {
    await mockAuthAs(page, "user-profile-move-odds.json");
    await mockOdds(page, () => ({ status: 503, body: { detail: "withheld: stale_data", data: { status: "withheld", reason: "stale_data", detail: { rows: 812 }, target_session: "2026-09-18" } } }));
    await openOdds(page);
    await expect(page.getByTestId("mo-state-withheld")).toContainText("stale_data");
    await expect(page.locator('[data-testid^="mo-pct-"]')).toHaveCount(0);
  });

  test("an upstream failure offers a retry and shows no numbers", async ({ page }) => {
    await mockAuthAs(page, "user-profile-move-odds.json");
    await mockOdds(page, () => ({ status: 502, body: { detail: "upstream_unavailable" } }));
    await openOdds(page);
    await expect(page.getByTestId("mo-state-error")).toBeVisible();
    await expect(page.getByTestId("mo-retry")).toBeVisible();
    await expect(page.locator('[data-testid^="mo-pct-"]')).toHaveCount(0);
  });
});

test.describe("Move odds — mobile", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("TC-20 the mobile tab bar carries Odds and the table fits the screen", async ({ page }) => {
    await mockAuthAs(page, "user-profile-move-odds.json");
    await mockOdds(page);
    await page.goto("/v5/research");
    await page.getByTestId("mnav-odds").click();
    await expect(page.getByTestId("mo-row-PNCINFRA")).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
  });
});

test.describe("Move odds — live prices", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("TC-33 live column equals the live API, unavailable shows a dash, and it refreshes every minute", async ({ page }) => {
    await page.clock.install();                          // before navigation, so the page's refresh interval runs on the fake clock
    await mockAuthAs(page, "user-profile-move-odds.json");
    await mockOdds(page);
    await openOdds(page);
    await expect(page.getByTestId("mo-row-PNCINFRA")).toBeVisible();
    const live = load("move-odds-live.json");
    const money = (v: number) => "₹" + v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const signed = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)}%`;
    await expect(page.getByTestId("mo-live-asof")).toContainText("Yahoo Finance");
    for (const q of live.quotes.slice(0, 6)) {
      const cell = page.getByTestId(`mo-livecell-${q.symbol}`);
      if (q.error) { await expect(cell).toHaveText("—"); continue; }
      await expect(cell).toContainText(money(q.last));
      await expect(cell).toContainText(signed(q.change_pct));
    }
    expect(live.quotes[3].error).toBe("unavailable");
    const before = liveCalls.length;
    await page.clock.runFor(61_000);
    await expect.poll(() => liveCalls.length, { timeout: 5_000 }).toBeGreaterThan(before);
    expect(liveCalls[liveCalls.length - 1].split(",").length).toBeLessThanOrEqual(50);
    // the seven-column table must fit its region at laptop width, also with a row open (no horizontal scroll, no jump)
    await page.getByTestId("mo-details-PNCINFRA").click();
    await expect(page.getByTestId("mo-detail-PNCINFRA")).toBeVisible();
    const fit = await page.locator(".mo-tablewrap").evaluate((el) => ({ over: el.scrollWidth - el.clientWidth, left: el.scrollLeft }));
    expect(fit.over).toBeLessThanOrEqual(1);
    expect(fit.left).toBe(0);
  });
});
