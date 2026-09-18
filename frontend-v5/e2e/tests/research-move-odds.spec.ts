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
async function mockOdds(page: Page, latest?: (head: string) => Reply, diagnostics?: () => Reply, history?: () => Reply, profile?: () => Reply) {
  await page.route("**/api/move-odds/profile**", (route) => {
    const r = profile ? profile() : { status: 200, body: load("move-odds-profile.json") };   // MOCK — see the fixture's _note
    return route.fulfill({ status: r.status, contentType: "application/json", body: JSON.stringify(r.body) });
  });
  await page.route("**/api/move-odds/history**", (route) => {
    const r = history ? history() : { status: 200, body: load("move-odds-history.json") };
    return route.fulfill({ status: r.status, contentType: "application/json", body: JSON.stringify(r.body) });
  });
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
    await expect(page.locator('[data-testid^="mo-big-"]')).toHaveCount(0);
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

  test("TC-21 disclaimer above the numbers, provenance, size tabs with both base rates", async ({ page }) => {
    const disc = await page.getByTestId("mo-disclaimer").boundingBox();
    const table = await page.locator(".mo-table").boundingBox();
    expect(disc && table && disc.y + disc.height <= table.y).toBeTruthy();
    await expect(page.getByTestId("mo-disclaimer")).toContainText("does not constitute investment advice");
    const prov = page.getByTestId("mo-provenance");
    await expect(prov).toContainText("Wed 16 Sep");
    await expect(prov).toContainText("Thu 17 Sep");
    await expect(prov).toContainText("994 of 1,000 stocks scored");
    // v6: two size tabs, each carrying the base rate for BOTH directions
    for (const [key, up, down] of [["5", "p_up5_1d", "p_down5_1d"], ["10", "p_up10_1d", "p_down10_1d"]] as const) {
      const tab = page.getByTestId(`mo-tab-${key}`);
      await expect(tab).toContainText(`base rate up ${pct(load(`move-odds-latest-${up}.json`).data.base_rate)}`);
      await expect(tab).toContainText(`down ${pct(load(`move-odds-latest-${down}.json`).data.base_rate)}`);
    }
  });

  test("TC-22 sorted by estimate, no rank column, 50 per page, search filters", async ({ page }) => {
    const headers = (await page.locator(".mo-table thead th").allInnerTexts()).map((t) => t.trim());
    expect(headers.join("|")).not.toMatch(/#|rank/i);
    const rows = page.locator('tbody tr[data-testid^="mo-row-"]');
    await expect(rows).toHaveCount(50);
    // v6/v2: rows rank by the LARGER of the two published estimates, and v2 shows that larger figure as the big number
    const shown = await page.locator('[data-testid^="mo-big-"]').allInnerTexts();
    const rowsFx = load("move-odds-latest-p_up5_1d.json").data.rows as Array<{ p: number; p_opposite: number | null }>;
    const ranked = [...rowsFx].sort((a, b) => Math.max(b.p, b.p_opposite ?? -Infinity) - Math.max(a.p, a.p_opposite ?? -Infinity));
    expect(shown).toEqual(ranked.slice(0, 50).map((r) => pct(Math.max(r.p, r.p_opposite ?? -Infinity))));
    await page.getByTestId("mo-page-next").click();
    await expect(rows).toHaveCount(10);
    await page.getByTestId("mo-search").fill("antelopus");
    await expect(page.getByTestId("mo-count")).toHaveText("1 stocks");
    await expect(page.getByTestId("mo-row-ANTELOPUS")).toBeVisible();
    await page.getByTestId("mo-tab-10").click();
    await expect(page.getByTestId("mo-tab-10")).toHaveAttribute("aria-selected", "true");
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
    await page.keyboard.press("Escape");                                                   // v7: details are a dialog
    await expect(page.getByTestId("mo-detail-PNCINFRA")).toHaveCount(0);
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
    // v6: the first page is the 50 highest by the LARGER of the two estimates, so rank the fixture the same way
    const data = load("move-odds-latest-p_up5_1d.json").data;
    const ranked = [...data.rows as Array<{ symbol: string; p: number; p_opposite: number | null }>]
      .sort((a, b) => Math.max(b.p, b.p_opposite ?? -Infinity) - Math.max(a.p, a.p_opposite ?? -Infinity));
    for (const r of ranked.slice(0, 50)) {
      const up = r.p_opposite == null || r.p >= r.p_opposite;           // v2: the larger leads, the smaller is "Other way"
      await expect(page.getByTestId(`mo-big-${r.symbol}`)).toHaveText(pct(up ? r.p : r.p_opposite));
      await expect(page.getByTestId(`mo-other-${r.symbol}`)).toHaveText(pct(up ? r.p_opposite : r.p));
    }
  });
});

test.describe("Move odds — movement vs direction (TC-70..TC-76, test_reports/move_odds_ui_v6_20260918_0907.md)", () => {
  test.use({ viewport: { width: 1280, height: 800 } });
  const upFx = () => load("move-odds-latest-p_up5_1d.json").data;
  const downFx = () => load("move-odds-latest-p_down5_1d.json").data;

  test.beforeEach(async ({ page }) => {
    await mockAuthAs(page, "user-profile-move-odds.json");
    await mockOdds(page);
    await openOdds(page);
  });

  test("TC-70 two size tabs, each showing both base rates", async ({ page }) => {
    const tabs = page.locator('[role="tablist"] [data-testid^="mo-tab-"]');
    await expect(tabs).toHaveCount(2);
    expect(await tabs.evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")))).toEqual(["mo-tab-5", "mo-tab-10"]);
    await expect(page.getByTestId("mo-tab-5")).toContainText("5% move");
    await expect(page.getByTestId("mo-tab-5")).toContainText(`base rate up ${pct(upFx().base_rate)}`);
    await expect(page.getByTestId("mo-tab-5")).toContainText(`down ${pct(downFx().base_rate)}`);
  });

  test("TC-71 every row shows both directions, each equal to the API, and names the side of the larger", async ({ page }) => {
    // v2 design (owner, 2026-09-18): the larger estimate leads and the smaller sits under "Other way" — so the equal-size
    // check of v6 is replaced by: both numbers present, each equal to the API, and the lead names its side.
    const rows = upFx().rows.slice(0, 8) as Array<{ symbol: string; p: number; p_opposite: number }>;
    let checked = 0;
    for (const r of rows) {
      const big = page.getByTestId(`mo-big-${r.symbol}`);
      if (await big.count() === 0) continue;                      // not on the first page
      const up = r.p >= r.p_opposite;
      await expect(big).toHaveText(pct(up ? r.p : r.p_opposite));
      await expect(big).toHaveAttribute("data-side", up ? "up" : "down");
      await expect(page.getByTestId(`mo-other-${r.symbol}`)).toHaveText(pct(up ? r.p_opposite : r.p));
      await expect(page.getByTestId(`mo-side-${r.symbol}`)).toContainText(up ? "upside" : "downside");
      checked++;
    }
    expect(checked).toBeGreaterThan(3);
  });

  test("TC-72 rows rank by the larger of the two estimates, and the table says so", async ({ page }) => {
    const larger = (await page.locator('[data-testid^="mo-row-"] [data-testid^="mo-big-"]').allInnerTexts()).map(parseFloat);
    for (let i = 1; i < larger.length; i++) expect(larger[i]).toBeLessThanOrEqual(larger[i - 1] + 0.05);
    await expect(page.locator("table caption").first()).toContainText("the larger of the two estimates");
    await expect(page.locator("table caption").first()).toContainText("It is not a forecast");
  });

  test("TC-73 the direction reading follows the stated rule and never claims a forecast", async ({ page }) => {
    const rows = upFx().rows as Array<{ symbol: string; p: number; p_opposite: number }>;
    let checked = 0;
    for (const r of rows.slice(0, 12)) {
      const cell = page.getByTestId(`mo-dir-${r.symbol}`);
      if (await cell.count() === 0) continue;
      const smaller = Math.min(r.p, r.p_opposite), bigger = Math.max(r.p, r.p_opposite);
      const expected = smaller >= 0.6 * bigger ? "two-way" : r.p > r.p_opposite ? "up-leaning" : "down-leaning";
      await expect(cell, r.symbol).toHaveText(expected);
      checked++;
    }
    expect(checked).toBeGreaterThan(3);
    const text = await page.getByTestId("move-odds-screen").innerText();
    expect(text).not.toMatch(/will rise|will fall|forecast of direction|expected to rise/i);
  });

  test("TC-74 the four questions are stated with their honest status", async ({ page }) => {
    await expect(page.getByTestId("mo-answers")).toHaveCount(0);                  // v2: folded by default
    await expect(page.getByTestId("mo-hero")).toContainText("Direction is not predicted");   // the status is still stated up front
    await page.getByTestId("mo-honesty-toggle").click();
    await expect(page.getByTestId("mo-honesty-toggle")).toHaveAttribute("aria-expanded", "true");
    const panel = page.getByTestId("mo-answers");
    await expect(panel).toContainText("Is it likely to move 5% or 10%?");
    await expect(page.getByTestId("mo-answer-1")).toContainText("Yes");
    await expect(page.getByTestId("mo-answer-2")).toContainText("Up or down?");
    await expect(page.getByTestId("mo-answer-2")).toContainText("Not predicted");
    await expect(page.getByTestId("mo-answer-3")).toContainText("Not modelled yet");
    await expect(page.getByTestId("mo-answer-4")).toContainText("No");
    await expect(page.getByTestId("mo-answer-2")).toContainText("19%");        // the evidence, not just the claim
  });

  test("TC-75 switching size keeps both directions and never becomes a one-way list", async ({ page }) => {
    await page.getByTestId("mo-tab-10").click();
    await expect(page.getByTestId("mo-tab-10")).toHaveAttribute("aria-selected", "true");
    const headers = await page.locator("table thead th").allInnerTexts();
    const joined = headers.join("|").toLowerCase();                 // the header row is uppercased by CSS
    expect(joined).toContain("chance of a 10% touch");
    expect(joined).toContain("other way");
    const firstRow = page.locator('tbody tr[data-testid^="mo-row-"]').first();
    await expect(firstRow.locator('[data-testid^="mo-other-"]')).toHaveCount(1);
    await expect(firstRow.locator('[data-testid^="mo-dir-"]')).toHaveCount(1);
    const text = await page.getByTestId("move-odds-screen").innerText();
    expect(text.match(BANNED), "banned vocabulary").toBeNull();
  });
});

test.describe("Move odds — movement vs direction on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("TC-76 both directions stay reachable and the page does not scroll sideways", async ({ page }) => {
    await mockAuthAs(page, "user-profile-move-odds.json");
    await mockOdds(page);
    await page.goto("/v5/research");
    await page.getByTestId("mnav-odds").click();
    await expect(page.locator('tbody tr[data-testid^="mo-row-"]').first()).toBeVisible();
    await expect(page.locator('[data-testid^="mo-other-"]').first()).toHaveCount(1);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
  });
});

test.describe("Move odds — history (TC-57..TC-60, test_reports/move_odds_history_20260918_0820.md)", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("TC-57 the History view lists sessions newest-first and shows the selected one's outcomes", async ({ page }) => {
    await mockAuthAs(page, "user-profile-move-odds.json");
    await mockOdds(page);
    await openOdds(page);
    await page.getByTestId("mo-view-history").click();
    const h = load("move-odds-history.json").data;
    await expect(page.getByTestId("mo-history")).toBeVisible();
    const dates = await page.locator('[data-testid^="mo-hist-date-"]').evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")));
    expect(dates).toEqual(["mo-hist-date-2026-09-18", "mo-hist-date-2026-09-17"]);   // newest first
    await page.getByTestId("mo-hist-date-2026-09-17").click();
    const graded = h.sessions[1];
    await expect(page.getByTestId("mo-hist-summary")).toContainText("2 of the top 3 reached it");
    await expect(page.getByTestId("mo-hist-summary")).toContainText("86");
    for (const r of graded.rows) {
      await expect(page.getByTestId(`mo-hist-p-${r.symbol}`)).toHaveText(pct(r.p));
      await expect(page.getByTestId(`mo-hist-outcome-${r.symbol}`)).toHaveText(r.outcome.touched ? "reached" : "did not");
    }
    await expect(page.getByTestId("mo-hist-row-PNCINFRA")).toContainText("+5.5%");
  });

  test("TC-58 new entries are marked and explained, and returning stocks are not", async ({ page }) => {
    await mockAuthAs(page, "user-profile-move-odds.json");
    await mockOdds(page);
    await openOdds(page);
    await page.getByTestId("mo-view-history").click();
    await page.getByTestId("mo-hist-date-2026-09-18").click();
    await expect(page.getByTestId("mo-hist-new-SHAREINDIA")).toBeVisible();          // is_new true
    await expect(page.getByTestId("mo-hist-new-RATNAVEER")).toHaveCount(0);          // is_new false
    await expect(page.getByTestId("mo-hist-legend")).toContainText("new to the top 3 this session");
    await page.getByTestId("mo-hist-date-2026-09-17").click();
    await expect(page.locator('[data-testid^="mo-hist-new-"]')).toHaveCount(0);      // is_new null on the earliest session: never marked
  });

  test("TC-59 a pending session says so and shows no outcome, with no banned vocabulary", async ({ page }) => {
    await mockAuthAs(page, "user-profile-move-odds.json");
    await mockOdds(page);
    await openOdds(page);
    await page.getByTestId("mo-view-history").click();
    await page.getByTestId("mo-hist-date-2026-09-18").click();
    await expect(page.getByTestId("mo-hist-pending")).toContainText("graded after its closing file lands");
    await expect(page.getByTestId("mo-hist-outcome-SHAREINDIA")).toHaveText("pending");
    const text = await page.getByTestId("move-odds-screen").innerText();
    expect(text.match(BANNED), "banned vocabulary").toBeNull();
  });
});

test.describe("Move odds — history on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("TC-60 the history table fits the screen", async ({ page }) => {
    await mockAuthAs(page, "user-profile-move-odds.json");
    await mockOdds(page);
    await page.goto("/v5/research");
    await page.getByTestId("mnav-odds").click();
    await page.getByTestId("mo-view-history").click();
    await expect(page.getByTestId("mo-history")).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
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
    await expect(page.locator('[data-testid^="mo-big-"]')).toHaveCount(0);
    await expect(page.getByTestId("mo-provenance")).toHaveCount(0);
  });

  test("TC-24 withheld", async ({ page }) => {
    await mockAuthAs(page, "user-profile-move-odds.json");
    await mockOdds(page, () => ({ status: 503, body: { detail: "withheld: stale_data", data: { status: "withheld", reason: "stale_data", detail: { rows: 812 }, target_session: "2026-09-18" } } }));
    await openOdds(page);
    await expect(page.getByTestId("mo-state-withheld")).toContainText("stale_data");
    await expect(page.locator('[data-testid^="mo-big-"]')).toHaveCount(0);
  });

  test("an upstream failure offers a retry and shows no numbers", async ({ page }) => {
    await mockAuthAs(page, "user-profile-move-odds.json");
    await mockOdds(page, () => ({ status: 502, body: { detail: "upstream_unavailable" } }));
    await openOdds(page);
    await expect(page.getByTestId("mo-state-error")).toBeVisible();
    await expect(page.getByTestId("mo-retry")).toBeVisible();
    await expect(page.locator('[data-testid^="mo-big-"]')).toHaveCount(0);
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
    // v7: the nine-column table must fit its region at laptop width (no horizontal scroll), and opening a stock — now a
    // dialog — must not scroll or reflow it
    const fit = await page.locator(".mo-tablewrap").first().evaluate((el) => ({ over: el.scrollWidth - el.clientWidth, left: el.scrollLeft }));
    expect(fit.over).toBeLessThanOrEqual(1);
    expect(fit.left).toBe(0);
    await page.getByTestId("mo-details-PNCINFRA").click();
    await expect(page.getByTestId("mo-detail-PNCINFRA")).toBeVisible();
    const after = await page.locator(".mo-tablewrap").first().evaluate((el) => ({ over: el.scrollWidth - el.clientWidth, left: el.scrollLeft }));
    expect(after).toEqual(fit);
  });
});

// ── v7: ratings, filters and the stock view (TC-89..TC-98, test_reports/move_odds_v7_ratings_filters_20260918_1130.md) ──
// MOCK — not real data: move-odds-profile.json is cut from the real 2026-09-18 profile payload; its _note lists the edits.
type ProfRow = { cap: string | null; sector: string | null; quality: { score: number; grade: string; partial: boolean; fundamental: number | null; technical: number | null } | null;
  ratios: Array<number | null>; events: { n: number; material: number; latest: string | null; categories: string[] } };
const prof = () => load("move-odds-profile.json").data as { rows: Record<string, ProfRow>; ratio_keys: string[]; sectors: Record<string, { median: number | null; grade: string | null }>;
  catalogue: Array<{ key: string; label: string; available: boolean; reason: string | null; group: string }>; groups: string[] };
const upRows = () => load("move-odds-latest-p_up5_1d.json").data.rows as Array<{ symbol: string; p: number; p_opposite: number | null; events_on_record: number }>;
const larger = (r: { p: number; p_opposite: number | null }) => Math.max(r.p, r.p_opposite ?? -Infinity);
const ratio = (sym: string, key: string) => { const P = prof(); const v = P.rows[sym]?.ratios[P.ratio_keys.indexOf(key)]; return v == null ? null : v; };
const visibleSyms = (page: Page) => page.locator('tbody tr[data-testid^="mo-row-"]').evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")!.slice(7)));

test.describe("Move odds v7 — ratings, filters, stock view", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test.beforeEach(async ({ page }) => {
    await mockAuthAs(page, "user-profile-move-odds.json");
    await mockOdds(page);
    await openOdds(page);
    await expect(page.getByTestId("mo-row-PNCINFRA")).toBeVisible();
    await expect(page.getByTestId("mo-rating-PNCINFRA")).toHaveAttribute("data-grade", /[ABC]/);   // profile loaded
  });

  test("TC-89 each row shows its grade and score and its sector's, equal to the payload; partial is marked", async ({ page }) => {
    const P = prof();
    const first = [...upRows()].sort((a, b) => larger(b) - larger(a)).slice(0, 50);
    let partial = 0, none = 0;
    for (const r of first) {
      const pr = P.rows[r.symbol];
      const badge = page.getByTestId(`mo-rating-${r.symbol}`);
      if (!pr.quality) { await expect(badge).toHaveText(/—/); none++; }
      else {
        await expect(badge).toHaveAttribute("data-grade", pr.quality.grade);
        await expect(badge).toHaveAttribute("data-score", pr.quality.score.toFixed(1));
        await expect(badge).toContainText(`${pr.quality.score.toFixed(1)} of 100`);        // the accessible label carries the score
        const row = page.getByTestId(`mo-row-${r.symbol}`);
        if (pr.quality.partial) { await expect(row).toContainText("partial rating"); await expect(badge).toHaveClass(/partial/); partial++; }
        else await expect(row).not.toContainText("partial rating");
      }
      const sec = pr.sector ? P.sectors[pr.sector] : null;
      const sc = page.getByTestId(`mo-secrating-${r.symbol}`);
      if (!sec || sec.median == null) await expect(sc).toHaveText("sector —");
      else {
        await expect(sc).toHaveText(`sector ${sec.grade}`);
        await expect(sc).toHaveAttribute("title", new RegExp(`median ${sec.median.toFixed(1)} `));
      }
    }
    expect(partial).toBeGreaterThan(0);
    expect(none).toBe(1);                                                                   // IOLCP: quality nulled in the fixture
  });

  test("TC-90 the cap filter keeps only that bucket and the count follows", async ({ page }) => {
    const P = prof();
    const byCap = (c: string) => upRows().filter((r) => P.rows[r.symbol]?.cap === c).length;
    for (const c of ["Mid", "Micro", "Small"]) {
      await page.getByTestId(`mo-cap-${c}`).click();
      await expect(page.getByTestId(`mo-cap-${c}`)).toHaveAttribute("aria-pressed", "true");
      await expect(page.getByTestId("mo-count")).toHaveText(`${byCap(c)} stocks`);
      for (const s of (await visibleSyms(page)).slice(0, 10)) expect(P.rows[s].cap, s).toBe(c);
    }
    await expect(page.getByTestId("mo-cap-Mid")).toContainText(String(byCap("Mid")));
    await page.getByTestId("mo-cap-Large").click();
    await expect(page.getByTestId("mo-count")).toHaveText("0 stocks");
    await expect(page.getByTestId("mo-empty")).toBeVisible();
    await page.getByTestId("mo-cap-All").click();
    await expect(page.getByTestId("mo-count")).toHaveText(`${upRows().length} stocks`);
  });

  test("TC-91 the ratio panel lists groups and columns; live ratios can be picked, the rest say why not", async ({ page }) => {
    const P = prof();
    await page.getByTestId("mo-ratio-toggle").click();
    const panel = page.getByTestId("mo-ratio-panel");
    await expect(panel).toBeVisible();
    await expect(panel.locator(".mo-rgroups button")).toHaveCount(P.groups.length);
    for (const col of ["recent", "preceding", "historical"]) await expect(panel.locator(".mo-rcol h4", { hasText: col })).toHaveCount(1);
    const live = P.catalogue.find((d) => d.available && d.group === P.groups[0] && !["mcap", "roce", "pe"].includes(d.key))!;
    const dead = P.catalogue.find((d) => !d.available && d.group === P.groups[0])!;
    await expect(page.getByTestId(`mo-ratio-${live.key}`).locator("input")).toBeEnabled();
    await expect(page.getByTestId(`mo-ratio-${dead.key}`).locator("input")).toBeDisabled();
    await expect(page.getByTestId(`mo-ratio-${dead.key}`)).toContainText(dead.reason!);
    await page.getByTestId(`mo-ratio-${live.key}`).locator("input").check();
    await expect(page.getByTestId(`mo-cond-${live.key}`)).toBeVisible();
    await page.getByTestId("mo-ratio-search").fill("return on");
    const hits = P.catalogue.filter((d) => d.label.toLowerCase().includes("return on")).length;
    await expect(panel.locator(".mo-ritem")).toHaveCount(hits);
    await page.getByTestId("mo-ratio-done").click();
    await expect(panel).toHaveCount(0);
  });

  test("TC-92 conditions filter both ways, and rows without the value are left out and counted", async ({ page }) => {
    const all = upRows();
    await expect(page.getByTestId("mo-cond-roce")).toBeVisible();
    await expect(page.getByTestId("mo-count")).toHaveText(`${all.length} stocks`);          // no number typed: no filtering
    await page.getByTestId("mo-cond-val-roce").fill("15");
    const pass = all.filter((r) => { const v = ratio(r.symbol, "roce"); return v != null && v > 15; }).length;
    const missing = all.filter((r) => ratio(r.symbol, "roce") == null).length;
    await expect(page.getByTestId("mo-count")).toContainText(`${pass} stocks`);
    if (missing) await expect(page.getByTestId("mo-missing-excluded")).toContainText(`${missing} without a value`);
    for (const s of await visibleSyms(page)) expect(ratio(s, "roce")!, s).toBeGreaterThan(15);
    await page.getByTestId("mo-cond-op-roce").click();                                     // > → <
    const below = all.filter((r) => { const v = ratio(r.symbol, "roce"); return v != null && v < 15; }).length;
    await expect(page.getByTestId("mo-count")).toContainText(`${below} stocks`);
    await page.getByTestId("mo-cond-val-pe").fill("20");                                    // P/E < 20 on top
    const both = all.filter((r) => { const a = ratio(r.symbol, "roce"), b = ratio(r.symbol, "pe"); return a != null && b != null && a < 15 && b < 20; }).length;
    await expect(page.getByTestId("mo-count")).toContainText(`${both} stocks`);
    await page.getByTestId("mo-clear").click();
    await expect(page.getByTestId("mo-count")).toHaveText(`${all.length} stocks`);
  });

  test("TC-93 an event category keeps only stocks with it, states how many, and Material / Latest reorder", async ({ page }) => {
    const P = prof();
    const counts: Record<string, number> = {};
    for (const r of upRows()) for (const c of P.rows[r.symbol]?.events.categories ?? []) counts[c] = (counts[c] ?? 0) + 1;
    const cat = Object.entries(counts).filter(([k]) => k !== "other").sort((a, b) => b[1] - a[1])[0][0];
    await page.getByTestId("mo-evt-toggle").click();
    await expect(page.getByTestId("mo-evt-bar")).toBeVisible();
    await page.getByTestId(`mo-evt-${cat}`).click();
    await expect(page.getByTestId("mo-evt-head")).toContainText(`${counts[cat]} stocks on record`);
    await expect(page.getByTestId("mo-count")).toHaveText(`${counts[cat]} stocks`);
    const syms = await visibleSyms(page);
    for (const s of syms) expect(P.rows[s].events.categories, s).toContain(cat);
    const mat = (s: string) => P.rows[s].events.material;
    for (let i = 1; i < syms.length; i++) expect(mat(syms[i])).toBeLessThanOrEqual(mat(syms[i - 1]));
    await page.getByTestId("mo-evt-sort-latest").click();
    const syms2 = await visibleSyms(page);
    const t = (s: string) => Date.parse(P.rows[s].events.latest!);
    for (let i = 1; i < syms2.length; i++) expect(t(syms2[i])).toBeLessThanOrEqual(t(syms2[i - 1]));
    await expect(page.locator("table caption").first()).toContainText("latest event");
  });

  test("TC-94 headers sort both ways with aria-sort, blanks last", async ({ page }) => {
    const P = prof();
    const score = (s: string) => P.rows[s]?.quality?.score ?? null;
    const th = (id: string) => page.getByTestId(id).locator("xpath=ancestor::th");
    await page.getByTestId("mo-sort-rating").click();
    await expect(th("mo-sort-rating")).toHaveAttribute("aria-sort", "descending");
    let syms = await visibleSyms(page);
    const top = [...upRows()].map((r) => r.symbol).filter((s) => score(s) != null).sort((a, b) => score(b)! - score(a)!);
    expect(syms.slice(0, 5)).toEqual(top.slice(0, 5));
    await page.getByTestId("mo-sort-rating").click();
    await expect(th("mo-sort-rating")).toHaveAttribute("aria-sort", "ascending");
    syms = await visibleSyms(page);
    expect(score(syms[0])).toBe(Math.min(...top.map((s) => score(s)!)));
    await page.getByTestId("mo-page-next").click();                                        // the unscored stock sorts last either way
    const last = await visibleSyms(page);
    expect(last[last.length - 1]).toBe("IOLCP");
    await page.getByTestId("mo-sort-sym").click();
    await expect(th("mo-sort-sym")).toHaveAttribute("aria-sort", "ascending");
    syms = await visibleSyms(page);
    expect(syms).toEqual([...syms].sort((a, b) => a.localeCompare(b)));
    await page.getByTestId("mo-sort-other").click();                                       // v2: "Other way" = the smaller estimate
    await expect(th("mo-sort-other")).toHaveAttribute("aria-sort", "descending");
    const others = (await page.locator('[data-testid^="mo-other-"]').allInnerTexts()).map(parseFloat);
    for (let i = 1; i < others.length; i++) expect(others[i]).toBeLessThanOrEqual(others[i - 1]);
    await page.getByTestId("mo-sort-est").click();
    await expect(th("mo-sort-est")).toHaveAttribute("aria-sort", "descending");
    const bigs = (await page.locator('[data-testid^="mo-big-"]').allInnerTexts()).map(parseFloat);
    for (let i = 1; i < bigs.length; i++) expect(bigs[i]).toBeLessThanOrEqual(bigs[i - 1]);
  });

  test("TC-95 the stock view: score, grade, bars, six questions, kept sections, Escape closes and focus returns", async ({ page }) => {
    const pr = prof().rows.PNCINFRA;
    await page.getByTestId("mo-row-PNCINFRA").locator(".mo-co").click();                   // a click anywhere on the row opens it
    const dlg = page.getByTestId("mo-detail-PNCINFRA");
    await expect(dlg).toBeVisible();
    await expect(dlg).toHaveAttribute("role", "dialog");
    await expect(dlg).toHaveAttribute("aria-modal", "true");
    await expect(page.getByTestId("mo-modal-close")).toBeFocused();
    await expect(page.getByTestId("mo-modal-disclaimer")).toContainText("does not constitute investment advice");
    await expect(page.getByTestId("mo-qscore")).toHaveText(`${pr.quality!.score.toFixed(1)}/100`);
    await expect(page.getByTestId("mo-qbar-fundamentals")).toContainText(String(Math.round(pr.quality!.fundamental!)));
    await expect(page.getByTestId("mo-qbar-technicals")).toContainText(String(Math.round(pr.quality!.technical!)));
    const chips = dlg.locator('[data-testid^="mo-chip-"]');
    await expect(chips).toHaveCount(6);
    await expect(chips.first()).toHaveText("Quality in brief");
    await expect(page.getByTestId("mo-answer-panel")).toContainText(`Rated ${pr.quality!.grade} (${pr.quality!.score.toFixed(1)}/100)`);
    await page.getByTestId("mo-chip-2").click();
    await expect(page.getByTestId("mo-answer-panel")).toContainText(`P/E ${ratio("PNCINFRA", "pe")!.toFixed(1)}×`);
    await page.getByTestId("mo-chip-3").click();
    await expect(page.getByTestId("mo-answer-panel")).toContainText("chance of touching +10%");
    for (const id of ["mo-inputs", "mo-events", "mo-checks-PNCINFRA", "mo-stands"]) await expect(dlg.getByTestId(id)).toBeVisible();
    const text = await page.getByTestId("move-odds-screen").innerText();
    expect(text.match(BANNED), "banned vocabulary with the stock view open").toBeNull();
    expect(await dlg.innerText()).not.toMatch(/\b(BUY|HOLD|SELL|ACCUMULATE|AVOID)\b/);
    await page.keyboard.press("Escape");
    await expect(dlg).toHaveCount(0);
    await expect(page.getByTestId("mo-details-PNCINFRA")).toBeFocused();
    await page.getByTestId("mo-details-PNCINFRA").press("Enter");                          // keyboard opens it too
    await expect(dlg).toBeVisible();
    await page.getByTestId("mo-modal-close-btn").click();
    await expect(dlg).toHaveCount(0);
  });

  test("TC-96 history shows today's rating and sector rating, and its headers sort", async ({ page }) => {
    const P = prof();
    await page.getByTestId("mo-view-history").click();
    await page.getByTestId("mo-hist-date-2026-09-17").click();
    const rows = load("move-odds-history.json").data.sessions[1].rows as Array<{ symbol: string; p: number }>;
    for (const r of rows) {
      const q = P.rows[r.symbol]?.quality;
      const cell = page.getByTestId(`mo-hist-rating-${r.symbol}`);
      if (q) { await expect(page.getByTestId(`mo-hist-badge-${r.symbol}`)).toHaveAttribute("data-grade", q.grade); await expect(cell).toContainText(q.score.toFixed(1)); }
      else await expect(cell).toHaveText(/—/);
    }
    await expect(page.locator(".mo-hist-table caption")).toContainText("not as of that session");
    await page.getByTestId("mo-hsort-rating").click();
    await expect(page.getByTestId("mo-hsort-rating").locator("xpath=..")).toHaveAttribute("aria-sort", "descending");
    const order = await page.locator('[data-testid^="mo-hist-row-"]').evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")!.slice(12)));
    const sc = (s: string) => P.rows[s]?.quality?.score ?? -1;
    for (let i = 1; i < order.length; i++) expect(sc(order[i])).toBeLessThanOrEqual(sc(order[i - 1]));
    await page.getByTestId("mo-hist-open-PNCINFRA").click();
    await expect(page.getByTestId("mo-detail-PNCINFRA")).toBeVisible();
  });
});

test.describe("Move odds v7 — profile failure", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("TC-97 the estimates still render, ratings read — with the reason, and the profile filters are off", async ({ page }) => {
    await mockAuthAs(page, "user-profile-move-odds.json");
    await mockOdds(page, undefined, undefined, undefined, () => ({ status: 502, body: { detail: "upstream_unavailable" } }));
    await openOdds(page);
    await expect(page.getByTestId("mo-row-PNCINFRA")).toBeVisible();
    const pn = upRows().find((r) => r.symbol === "PNCINFRA")!;
    await expect(page.getByTestId("mo-big-PNCINFRA")).toHaveText(pct(Math.max(pn.p, pn.p_opposite ?? -Infinity)));
    await expect(page.getByTestId("mo-profile-off")).toContainText("could not be loaded");
    await expect(page.getByTestId("mo-profile-off")).toContainText("The estimates are unaffected");
    await expect(page.getByTestId("mo-rating-PNCINFRA")).toHaveText("—");
    await expect(page.getByTestId("mo-rating-PNCINFRA")).toHaveAttribute("title", "Ratings could not be loaded");
    for (const id of ["mo-cap-Mid", "mo-ratio-toggle", "mo-evt-toggle"]) await expect(page.getByTestId(id)).toBeDisabled();
    await expect(page.getByTestId("mo-profile-retry")).toBeVisible();
    await page.getByTestId("mo-details-PNCINFRA").click();
    await expect(page.getByTestId("mo-modal-noprofile")).toBeVisible();
    await expect(page.getByTestId("mo-inputs")).toBeVisible();                             // the move-odds sections still work
  });

  test("TC-97 a 403 from the profile clears every estimate and shows the not-enabled state", async ({ page }) => {
    await mockAuthAs(page, "user-profile-move-odds.json");
    await mockOdds(page, undefined, undefined, undefined, () => ({ status: 403, body: { detail: "feature_not_enabled" } }));
    await openOdds(page);
    await expect(page.getByTestId("mo-state-no_access")).toBeVisible();
    await expect(page.locator('[data-testid^="mo-big-"]')).toHaveCount(0);
  });
});

test.describe("Move odds v7 — phone", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("TC-98 filters and the stock view fit a 390 px screen without sideways scroll", async ({ page }) => {
    await mockAuthAs(page, "user-profile-move-odds.json");
    await mockOdds(page);
    await page.goto("/v5/research");
    await page.getByTestId("mnav-odds").click();
    await expect(page.getByTestId("mo-row-PNCINFRA")).toBeVisible();
    await expect(page.getByTestId("mo-filterbar")).toBeVisible();
    await page.getByTestId("mo-ratio-toggle").click();
    await expect(page.getByTestId("mo-ratio-panel")).toBeVisible();
    const over = () => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(await over()).toBeLessThanOrEqual(1);
    // nothing is clipped either: an ancestor with overflow hidden can keep the document from scrolling while content
    // runs off the right edge, so check the screen's own column and the widest controls against the viewport
    const clipped = await page.evaluate(() => {
      const mo = document.querySelector(".mo") as HTMLElement;
      const out: string[] = [];
      if (mo.scrollWidth - mo.clientWidth > 1) out.push(`.mo scrolls by ${mo.scrollWidth - mo.clientWidth}px`);
      for (const sel of [".mo-hero", ".mo-hcard", ".mo-toolbar", ".mo-fbar", ".mo-rpanel", ".mo-tablewrap", ".mo-disc"]) {
        for (const el of Array.from(document.querySelectorAll(sel))) {
          const r = (el as HTMLElement).getBoundingClientRect();
          if (r.right > window.innerWidth + 1) out.push(`${sel} right edge ${Math.round(r.right)}`);
        }
      }
      return out;
    });
    expect(clipped).toEqual([]);
    await page.getByTestId("mo-ratio-done").click();
    await page.getByTestId("mo-details-PNCINFRA").click();
    const dlg = page.getByTestId("mo-detail-PNCINFRA");
    await expect(dlg).toBeVisible();
    const box = await dlg.boundingBox();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(391);
    expect(await over()).toBeLessThanOrEqual(1);
  });
});

// ── v2 design (owner, 2026-09-18): hero, the larger estimate leading each row, leaner history (TC-101..TC-103) ──
test.describe("Move odds v2 — hero and row reading", () => {
  test.use({ viewport: { width: 1280, height: 800 } });
  const base = () => ({ up: load("move-odds-latest-p_up5_1d.json").data.base_rate as number, down: load("move-odds-latest-p_down5_1d.json").data.base_rate as number });

  test.beforeEach(async ({ page }) => {
    await mockAuthAs(page, "user-profile-move-odds.json");
    await mockOdds(page);
    await openOdds(page);
    await expect(page.getByTestId("mo-row-PNCINFRA")).toBeVisible();
  });

  test("TC-101 the hero names each stock by its stated rule, with the numbers from the API, and opens it", async ({ page }) => {
    const rows = upRows() as Array<{ symbol: string; p: number; p_opposite: number }>;
    const B = base();
    const top = [...rows].sort((a, b) => larger(b) - larger(a) || a.symbol.localeCompare(b.symbol))[0];
    const tUp = top.p >= top.p_opposite, tHi = Math.max(top.p, top.p_opposite);
    const lead = page.getByTestId("mo-hero-lead");
    await expect(lead).toContainText(`${top.symbol} carries the highest estimated chance of a 5% move on Thu 17 Sep — ${pct(tHi)} on the ${tUp ? "upside" : "downside"}`);
    await expect(lead).toContainText(`roughly ${Math.round(tHi / (tUp ? B.up : B.down))}× the base rate`);
    await expect(page.getByTestId("mo-hero-odds")).toContainText(top.symbol);
    await expect(page.getByTestId("mo-hero-odds")).toContainText(`about 1 session in ${Math.max(2, Math.round(1 / tHi))}`);
    const both = [...rows].sort((a, b) => Math.min(b.p, b.p_opposite) - Math.min(a.p, a.p_opposite) || a.symbol.localeCompare(b.symbol))[0];
    await expect(page.getByTestId("mo-hero-both")).toContainText(both.symbol);
    await expect(page.getByTestId("mo-hero-both")).toContainText(`${pct(both.p)} / ${pct(both.p_opposite)}`);
    const P = prof();
    const f = rows.filter((r) => P.rows[r.symbol].events.material > 0)
      .sort((a, b) => P.rows[b.symbol].events.material - P.rows[a.symbol].events.material || P.rows[b.symbol].events.n - P.rows[a.symbol].events.n
        || larger(b) - larger(a) || a.symbol.localeCompare(b.symbol))[0];
    await expect(page.getByTestId("mo-hero-filings")).toContainText(f.symbol);
    await expect(page.getByTestId("mo-hero-filings")).toContainText(`${P.rows[f.symbol].events.material} material`);
    const labels = load("move-odds-profile.json").data.event_categories as Array<{ key: string; label: string }>;
    const first = labels.find((l) => l.key === P.rows[f.symbol].events.categories[0])!.label;
    await expect(page.getByTestId("mo-hero-filings")).toContainText(first);             // labels keep their casing ("M&A", not "m&a")
    // the disclaimer still sits above every number, the hero included
    const disc = await page.getByTestId("mo-disclaimer").boundingBox();
    const hero = await page.getByTestId("mo-hero").boundingBox();
    expect(disc!.y + disc!.height).toBeLessThanOrEqual(hero!.y);
    await page.getByTestId("mo-hero-both").click();
    await expect(page.getByTestId(`mo-detail-${both.symbol}`)).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("mo-hero-both")).toBeFocused();
    const text = await page.getByTestId("move-odds-screen").innerText();
    expect(text.match(BANNED), "banned vocabulary").toBeNull();
  });

  test("TC-102 each row reads its side, its multiple of the base rate and a plain frequency, all from the API", async ({ page }) => {
    const B = base();
    const first = [...upRows()].sort((a, b) => larger(b) - larger(a)).slice(0, 10) as Array<{ symbol: string; p: number; p_opposite: number }>;
    for (const r of first) {
      const up = r.p >= r.p_opposite, hi = Math.max(r.p, r.p_opposite);
      const x = hi / (up ? B.up : B.down);
      const cell = page.getByTestId(`mo-row-${r.symbol}`).locator(".mo-bigcell");
      await expect(cell).toContainText(`${x.toFixed(x >= 10 ? 0 : 1)}× base`);
      await expect(page.getByTestId(`mo-side-${r.symbol}`)).toHaveText(`${up ? "upside" : "downside"} · about 1 session in ${Math.max(2, Math.round(1 / hi))}`);
      const colour = await page.getByTestId(`mo-big-${r.symbol}`).evaluate((el) => getComputedStyle(el).color);
      const ink = await page.getByTestId(`mo-other-${r.symbol}`).evaluate((el) => getComputedStyle(el.closest("tr")!.querySelector(".mo-sym")!).color);
      expect(colour, "the big number stays in ink, whatever its side").toBe(ink);
    }
    await expect(page.locator(".mo-table thead th")).toHaveCount(5);
  });

  test("TC-103 history is five columns plus open, and keeps 'within 3 / within 5' on the move line", async ({ page }) => {
    await page.getByTestId("mo-view-history").click();
    await page.getByTestId("mo-hist-date-2026-09-17").click();
    await expect(page.locator(".mo-hist-table thead th")).toHaveCount(6);
    const rows = load("move-odds-history.json").data.sessions[1].rows as Array<{ symbol: string; outcome: { within3: boolean | null; within5: boolean | null } }>;
    for (const r of rows) {
      const w = (v: boolean | null) => (v == null ? "—" : v ? "reached" : "no");
      await expect(page.getByTestId(`mo-hist-within-${r.symbol}`)).toHaveText(`within 3: ${w(r.outcome.within3)} · within 5: ${w(r.outcome.within5)}`);
    }
    await page.getByTestId("mo-hist-row-PNCINFRA").locator(".mo-coname").click();
    await expect(page.getByTestId("mo-detail-PNCINFRA")).toBeVisible();
  });
});
