/**
 * FLOW LEDGER — auto-fill and scoring.
 *
 * The mocked payloads below are the REAL responses from
 * /v1/flows/ledger/{company,sector} on nidp_staging (2026-08-19), not invented
 * fixtures — RELIANCE's -147/-42/44/-56 bps come from the exchange filings, and
 * the two unavailable reasons are the ones the API actually returns.
 *
 * What matters here is not that the page renders. It is that:
 *   • auto-fill puts real values into the tracker's own fields;
 *   • the composite is computed IN THE PAGE from those fields, renormalised over
 *     filled weights only;
 *   • a stream NIDP cannot source shows its reason and is excluded — never
 *     silently scored as neutral, which would dilute the streams that are real;
 *   • a transport failure reads as a transport failure, not as "no data".
 */
import { test, expect } from "@playwright/test";

const COMPANY_FILL = {
  mode: "company",
  name: "RELIANCE",
  inputs: {
    fiiQ: ["-147", "-42", "44", "-56"],
    diiQ: ["64", "45", "-15", "53"],
    delivBase: "56.4", delivDown: "56.58", fo: "lu",
    deal: "", repeatSeller: false, mf: "",
  },
  streams: [
    { tag: "S1", weight: 30, title: "FII stake, quarterly", filled: true,
      evidence: "4 QoQ change(s) from 5 filings (2026-06-30, 2026-03-31, 2025-12-31, 2025-09-30, 2025-06-30)",
      unavailable_reason: null, source_dataset: "nidp.shareholding_pattern" },
    { tag: "S2", weight: 15, title: "DII stake, quarterly", filled: true,
      evidence: "4 QoQ change(s). DII only — mf_pct is NULL in every row",
      unavailable_reason: null, source_dataset: "nidp.shareholding_pattern" },
    { tag: "S3", weight: 20, title: "Bulk / block deals, 30 sessions", filled: false,
      evidence: null,
      unavailable_reason: "Exchange deal lists name the trading member, not the beneficial owner — of 4,137 bulk deals in the last 90 days only 10 identify as foreign, so FII direction cannot be derived from them",
      source_dataset: null },
    { tag: "S5", weight: 10, title: "MF monthly portfolios", filled: false,
      evidence: null,
      unavailable_reason: "The monthly AMC feed is incomplete — 10 of 14 fund houses are missing",
      source_dataset: null },
    { tag: "S4", weight: 15, title: "Delivery % on down days", filled: true,
      evidence: "56.58% on 13 down days vs 56.4% across 28 sessions",
      unavailable_reason: null, source_dataset: "nidp.prices_eod" },
    { tag: "S6", weight: 10, title: "Stock F&O positioning", filled: true,
      evidence: "near-month future over 6 sessions: close 1336.1 to 1320.5, OI 108,008,000 to 102,734,500",
      unavailable_reason: null, source_dataset: "nidp.fno_bhavcopy" },
  ],
  filled_weight: 70, total_weight: 100,
};

const SECTOR_FILL = {
  mode: "sector", name: "Automobile", index_used: "Nifty Auto",
  inputs: { ftDir: "in", ftN: "1", auc: "4.61", idx: "8.54", breadth: "8", rs: "11.61" },
  streams: [
    { tag: "S1", weight: 35, title: "NSDL fortnightly FPI flows", filled: true,
      evidence: "1 consecutive fortnight(s) of inflow to 2026-07-31 (latest net +2,372 cr, 8 fortnights on record)",
      unavailable_reason: null, source_dataset: "nidp.fpi_sector_auc" },
    { tag: "S2", weight: 25, title: "AUC change vs index change", filled: true,
      evidence: "FPI custody in Automobile +4.61% vs Nifty Auto +8.54% between 2026-04-15 and 2026-07-31",
      unavailable_reason: null, source_dataset: "nidp.fpi_sector_auc + nidp.index_eod" },
    { tag: "S3", weight: 25, title: "Constituent breadth", filled: true,
      evidence: "8 of the top 10 by market cap saw FII stake fall QoQ",
      unavailable_reason: null, source_dataset: "nidp.shareholding_pattern + nidp.sector_master" },
    { tag: "S4", weight: 15, title: "Relative strength vs Nifty, 3M", filled: true,
      evidence: "Nifty Auto +13.88% vs Nifty 50 +2.27% over ~3 months",
      unavailable_reason: null, source_dataset: "nidp.index_eod" },
  ],
  filled_weight: 100, total_weight: 100,
};

async function mockCompany(page, body = COMPANY_FILL, status = 200) {
  await page.route("**/api/flows/ledger/company/**", (route) =>
    route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) }));
}

test.describe("FLOW LEDGER — company auto-fill", () => {
  test.beforeEach(async ({ page }) => {
    await mockCompany(page);
    await page.goto("/v5/flows");
    await page.waitForLoadState("networkidle");
  });

  test("renders without an error boundary", async ({ page }) => {
    await expect(page.locator("text=Something went wrong")).not.toBeVisible();
    await expect(page.getByText("FLOW LEDGER").first()).toBeVisible();
  });

  test("starts with nothing scored — an empty ledger must not read as neutral", async ({ page }) => {
    await expect(page.getByTestId("verdict-label")).toHaveText("AWAITING DATA");
    await expect(page.getByTestId("coverage")).toContainText("coverage 0%");
  });

  test("auto-fill puts the real QoQ values into the tracker's own fields", async ({ page }) => {
    await page.getByTestId("ledger-name").fill("RELIANCE");
    await page.getByTestId("autofill").click();
    await expect(page.getByTestId("fiiQ-0")).toHaveValue("-147");
    await expect(page.getByTestId("fiiQ-1")).toHaveValue("-42");
    await expect(page.getByTestId("fiiQ-2")).toHaveValue("44");
    await expect(page.getByTestId("fiiQ-3")).toHaveValue("-56");
    await expect(page.getByTestId("delivBase")).toHaveValue("56.4");
    await expect(page.getByTestId("fo")).toHaveValue("lu");
  });

  test("the composite is computed in the page and excludes unfilled streams", async ({ page }) => {
    await page.getByTestId("ledger-name").fill("RELIANCE");
    await page.getByTestId("autofill").click();
    // 70 of 100 weight filled — the API reports it, the page derives it independently
    await expect(page.getByTestId("coverage")).toContainText("coverage 70%");
    await expect(page.getByTestId("verdict-label")).not.toHaveText("AWAITING DATA");
  });

  test("an unsourceable stream shows its reason instead of a score", async ({ page }) => {
    await page.getByTestId("ledger-name").fill("RELIANCE");
    await page.getByTestId("autofill").click();
    await expect(page.getByTestId("gap-S3")).toContainText("trading member, not the beneficial owner");
    await expect(page.getByTestId("gap-S5")).toContainText("10 of 14 fund houses");
    // and it is genuinely unscored, not quietly zeroed
    await expect(page.getByTestId("stream-S3")).toContainText("unfilled");
  });

  test("a filled stream shows the evidence behind its number", async ({ page }) => {
    await page.getByTestId("ledger-name").fill("RELIANCE");
    await page.getByTestId("autofill").click();
    await expect(page.getByTestId("evidence-S1")).toContainText("4 QoQ change(s) from 5 filings");
    await expect(page.getByTestId("evidence-S4")).toContainText("13 down days");
    await expect(page.getByTestId("evidence-S6")).toContainText("108,008,000");
  });

  test("auto-fill without a name does not call the API", async ({ page }) => {
    let called = false;
    await page.route("**/api/flows/ledger/**", (route) => { called = true; route.abort(); });
    await page.getByTestId("autofill").click();
    await expect(page.getByTestId("notice")).toContainText("Enter a symbol or sector");
    expect(called).toBe(false);
  });
});

test.describe("FLOW LEDGER — failure is reported as failure", () => {
  test("a 502 reads as a data-service problem, not as an empty company", async ({ page }) => {
    await page.route("**/api/flows/ledger/company/**", (route) =>
      route.fulfill({ status: 502, contentType: "application/json",
                      body: JSON.stringify({ detail: "Could not reach the NIDP data service" }) }));
    await page.goto("/v5/flows");
    await page.getByTestId("ledger-name").fill("RELIANCE");
    await page.getByTestId("autofill").click();
    await expect(page.getByTestId("fill-error")).toBeVisible();
    await expect(page.getByTestId("fill-error")).toContainText("not a finding about RELIANCE");
    // the verdict must NOT have moved
    await expect(page.getByTestId("verdict-label")).toHaveText("AWAITING DATA");
  });
});

test.describe("FLOW LEDGER — sector auto-fill", () => {
  test("fills all four sector streams and reports full coverage", async ({ page }) => {
    await page.route("**/api/flows/ledger/sector/**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(SECTOR_FILL) }));
    await page.goto("/v5/flows");
    await page.getByTestId("mode-sector").click();
    await page.getByTestId("ledger-name").fill("Automobile");
    await page.getByTestId("autofill").click();
    await expect(page.getByTestId("ftDir")).toHaveValue("in");
    await expect(page.getByTestId("breadth")).toHaveValue("8");
    await expect(page.getByTestId("rs")).toHaveValue("11.61");
    await expect(page.getByTestId("coverage")).toContainText("coverage 100%");
    await expect(page.getByTestId("evidence-S2")).toContainText("Nifty Auto +8.54%");
  });
});

/**
 * FLOW LEDGER — ticker type-ahead over the NIDP symbol master.
 *
 * The field used to be free text: a typo, a BSE scrip code, or a name NIDP simply
 * does not carry all produced the same shrug from AUTO-FILL. The dropdown reads
 * nidp.sector_master through /api/filings/companies/search — the same contract the
 * Research screen uses, so there is one to keep true, not two.
 *
 * SYMBOL_HITS below is the REAL response from that endpoint on staging for q=REL
 * (2026-08-20), not an invented fixture — including the null sectors, which are
 * genuine gaps in sector_master and must render as an absent chip, not "null".
 *
 * What matters here: a suggestion is only ever a row the master returned, a failed
 * search shows nothing rather than a guess, and a name the master does not carry is
 * still the user's to send.
 */
const SYMBOL_HITS = {
  ok: true,
  companies: [
    { symbol: "RELAXO",   name: "Relaxo Footwears Limited",           sector: null },
    { symbol: "RELCHEMQ", name: "Reliance Chemotex Industries Limited", sector: null },
    { symbol: "RELIABLE", name: "Reliable Data Services Limited",     sector: null },
    { symbol: "RELIANCE", name: "Reliance Industries Limited",        sector: "Oil Gas" },
    { symbol: "RELIGARE", name: "Religare Enterprises Limited",       sector: null },
    { symbol: "RELINFRA", name: "Reliance Infrastructure Limited",    sector: null },
    { symbol: "RELTD",    name: "Ravindra Energy Limited",            sector: null },
    { symbol: "RELTD-RE", name: "Ravindra Energy Ltd-RE",             sector: null },
  ],
};

/** Mocks the type-ahead and returns the list of queries it was actually asked. */
async function mockSymbolSearch(page, body = SYMBOL_HITS, status = 200) {
  const asked: string[] = [];
  await page.route("**/api/filings/companies/search**", (route) => {
    asked.push(new URL(route.request().url()).searchParams.get("q") ?? "");
    return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  });
  return asked;
}

test.describe("FLOW LEDGER — ticker type-ahead", () => {
  test.beforeEach(async ({ page }) => {
    await mockCompany(page);
  });

  test("suggests symbols from the NIDP master as you type", async ({ page }) => {
    await mockSymbolSearch(page);
    await page.goto("/v5/flows");
    await page.getByTestId("ledger-name").fill("REL");
    await expect(page.getByTestId("symbol-suggestions")).toBeVisible();
    const items = page.getByTestId("symbol-suggestion");
    await expect(items).toHaveCount(8);
    await expect(items.first()).toContainText("RELAXO");
    await expect(items.first()).toContainText("Relaxo Footwears Limited");
    // a real sector is shown; a sector_master gap shows nothing, never "null"
    await expect(items.nth(3)).toContainText("OIL GAS");
    await expect(items.first()).not.toContainText("null");
  });

  test("a single character asks nothing — a blank query is not a search", async ({ page }) => {
    const asked = await mockSymbolSearch(page);
    await page.goto("/v5/flows");
    await page.getByTestId("ledger-name").fill("R");
    await page.waitForTimeout(500);
    await expect(page.getByTestId("symbol-suggestions")).toHaveCount(0);
    expect(asked).toEqual([]);
  });

  test("keyboard: arrow to a symbol, Enter picks it and auto-fills that symbol", async ({ page }) => {
    await mockSymbolSearch(page);
    let filledFor = "";
    await page.route("**/api/flows/ledger/company/**", (route) => {
      filledFor = decodeURIComponent(route.request().url().split("/").pop() ?? "");
      return route.fulfill({ status: 200, contentType: "application/json",
                             body: JSON.stringify(COMPANY_FILL) });
    });
    await page.goto("/v5/flows");
    const field = page.getByTestId("ledger-name");
    await field.fill("REL");
    await expect(page.getByTestId("symbol-suggestions")).toBeVisible();
    for (let i = 0; i < 4; i++) await field.press("ArrowDown");   // → RELIANCE
    await field.press("Enter");
    await expect(field).toHaveValue("RELIANCE");
    await expect(page.getByTestId("symbol-suggestions")).toHaveCount(0);
    // the fill runs for the PICKED symbol, not the half-typed text it replaced
    expect(filledFor).toBe("RELIANCE");
    await expect(page.getByTestId("fiiQ-0")).toHaveValue("-147");
  });

  test("clicking a suggestion picks it — blur must not eat the press", async ({ page }) => {
    await mockSymbolSearch(page);
    await page.goto("/v5/flows");
    await page.getByTestId("ledger-name").fill("REL");
    await page.getByTestId("symbol-suggestion").nth(5).click();
    await expect(page.getByTestId("ledger-name")).toHaveValue("RELINFRA");
  });

  test("sector mode does not search the stock master", async ({ page }) => {
    const asked = await mockSymbolSearch(page);
    await page.goto("/v5/flows");
    await page.getByTestId("mode-sector").click();
    await page.getByTestId("ledger-name").fill("Automobile");
    await page.waitForTimeout(500);
    await expect(page.getByTestId("symbol-suggestions")).toHaveCount(0);
    expect(asked).toEqual([]);
  });

  test("a failed search suggests nothing — never a guess", async ({ page }) => {
    await mockSymbolSearch(page, { detail: "boom" }, 500);
    await page.goto("/v5/flows");
    await page.getByTestId("ledger-name").fill("REL");
    await page.waitForTimeout(600);
    await expect(page.getByTestId("symbol-suggestions")).toHaveCount(0);
    await expect(page.getByTestId("symbol-no-match")).toHaveCount(0);
    // and the field still works: what was typed is still sent
    await page.getByTestId("autofill").click();
    await expect(page.getByTestId("fiiQ-0")).toHaveValue("-147");
  });

  test("no match says so, and still lets the typed symbol through", async ({ page }) => {
    await mockSymbolSearch(page, { ok: true, companies: [] });
    await page.goto("/v5/flows");
    await page.getByTestId("ledger-name").fill("ZZQQ");
    await expect(page.getByTestId("symbol-no-match")).toContainText("No symbol in the NIDP master");
    await page.getByTestId("ledger-name").press("Enter");
    await expect(page.getByTestId("fiiQ-0")).toHaveValue("-147");
  });

  test("a fast typist fires one request, not one per keystroke", async ({ page }) => {
    const asked = await mockSymbolSearch(page);
    await page.goto("/v5/flows");
    await page.getByTestId("ledger-name").pressSequentially("RELIAN", { delay: 30 });
    await expect(page.getByTestId("symbol-suggestions")).toBeVisible();
    await page.waitForTimeout(400);
    expect(asked).toEqual(["RELIAN"]);
  });

  test("Escape closes the list", async ({ page }) => {
    await mockSymbolSearch(page);
    await page.goto("/v5/flows");
    await page.getByTestId("ledger-name").fill("REL");
    await expect(page.getByTestId("symbol-suggestions")).toBeVisible();
    await page.getByTestId("ledger-name").press("Escape");
    await expect(page.getByTestId("symbol-suggestions")).toHaveCount(0);
  });
});
