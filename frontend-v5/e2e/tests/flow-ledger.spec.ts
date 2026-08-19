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
