/**
 * Filings Intelligence (/research) — the completed design.
 *
 * Covers the increment that brought the screen up to the approved designs in
 * docs/ai_research/designs/: the desktop icon rail + header, the mobile bottom
 * tab bar, sectioned AI insights with page citations, the doc-type-aware annual
 * report tab set, SOURCES chips on a copilot answer, and the Alerts screen.
 *
 * Runs against the local Vite dev server with mocked APIs, so no session token
 * is needed. NOTE: mocked UI tests prove the RENDERING contract only — they
 * cannot prove the endpoints behave this way. The staging API evidence in
 * test_reports/filings_intelligence_design_completion.md is what proves that
 * (a prior session shipped this feature broken while mocked tests passed twice).
 */
import { test, expect, type Page } from "@playwright/test";
import { mockApi } from "../helpers/api-mock";

const FEED = {
  ok: true,
  total: 2,
  facets: { earnings: 1, orders: 1 },
  rows: [
    {
      id: "ANN-1", ticker: "HDFCAMC", code: "HDFCAMC", name: "HDFC Asset Management Co",
      date: "2026-07-17T09:30:00Z", category: "earnings", impact: "high", sentiment: "neutral",
      docLabel: "Concall Transcript", url: "https://example.test/hdfcamc.pdf",
      one: "PAT up 12% as equity AUM crossed ₹47tn.", period: "Q1 FY27",
      metric: "PAT: 8.4 ₹bn", hasInsights: true,
    },
    {
      id: "ANN-2", ticker: "BRITANNIA", code: "BRITANNIA", name: "Britannia Industries Ltd",
      date: "2026-07-16T11:00:00Z", category: "orders", impact: "medium", sentiment: "positive",
      docLabel: "Annual Report", url: "https://example.test/britannia.pdf",
      one: null, period: null, metric: null, hasInsights: false,
    },
  ],
};

const SIGNALS = {
  ok: true,
  signals: [{
    rank: 1, ticker: "HDFCAMC", type: "earnings",
    one: "PAT up 12% as equity AUM crossed ₹47tn.",
    metric: "PAT: 8.4 ₹bn", date: "2026-07-17T09:30:00Z", sentiment: "neutral",
  }],
};

/** A generic-doc-type insight WITH sections and a real page citation. */
const INSIGHT_TRANSCRIPT = {
  ok: true, id: "ANN-1",
  one: "PAT up 12% as equity AUM crossed ₹47tn.",
  period: "Q1 FY27", metric: "PAT: 8.4 ₹bn", metricRaw: { label: "PAT", value: "8.4", unit: "₹bn" },
  sentiment: "neutral", confidence: 82,
  docType: "concall_transcript", docLabel: "Concall Transcript",
  model: "gpt-4o-mini", generatedAt: "2026-07-18T04:00:00Z",
  sourceUrl: "https://example.test/hdfcamc.pdf",
  tabs: [
    { key: "quick_summary", label: "Quick Summary" },
    { key: "potential_risks", label: "Potential Risks" },
  ],
  sections: [
    {
      tab: "Quick Summary", h: "Financial results",
      items: ["Revenue grew 14% YoY to ₹11bn.", "PAT ₹8.4bn (+12% YoY)."],
      cite: "[transcript · pp. 6-8]",
      cite_url: "https://example.test/hdfcamc.pdf#page=6",
    },
    {
      tab: "Potential Risks", h: "Watch items",
      items: ["Sustained debt outflows if rates stay volatile."],
      cite: null, cite_url: null,
    },
  ],
  grounded: true,
  disclaimer: "AI-generated summary · refer to the source document for complete detail.",
};

/** An ANNUAL REPORT insight — must surface the AR tab set, not the generic one. */
const INSIGHT_ANNUAL = {
  ok: true, id: "ANN-2", one: "Pricing-led growth with a richer premium mix.",
  period: "FY 2026", metric: null, sentiment: "positive", confidence: 74,
  docType: "annual_report", docLabel: "Annual Report",
  sourceUrl: "https://example.test/britannia.pdf",
  tabs: [
    { key: "business_overview", label: "Business Overview" },
    { key: "accounting_notes", label: "Accounting Notes" },
  ],
  sections: [
    { tab: "Business Overview", h: "What the company does",
      items: ["Packaged foods with a premium mix."],
      cite: "[annual report · p. 12]", cite_url: "https://example.test/britannia.pdf#page=12" },
    { tab: "Accounting Notes", h: "Key policies",
      items: ["Revenue recognition per Ind AS 115."], cite: null, cite_url: null },
  ],
  grounded: true, disclaimer: "AI-generated summary · refer to the source document for complete detail.",
};

const ALERTS_DEFAULT = {
  ok: true,
  types: {
    concall_transcript: true, annual_report: true,
    investor_presentation: true, financial_results: true,
  },
  channels: { email: true, whatsapp: false },
  catalog: [
    { key: "concall_transcript", label: "Earnings transcripts" },
    { key: "annual_report", label: "Annual reports" },
    { key: "investor_presentation", label: "Investor presentations" },
    { key: "financial_results", label: "Quarterly results" },
  ],
  delivery: {
    active: false,
    note: "Preferences are saved. Scheduled delivery is not switched on yet — nothing is sent to you today.",
  },
  updatedAt: null,
};

const COMPANIES = {
  ok: true,
  companies: [
    { symbol: "INFY", name: "Infosys Limited", sector: "IT" },
    { symbol: "INFIBEAM", name: "Infibeam Avenues Limited", sector: "IT" },
  ],
};

const DOCS = {
  ok: true, symbol: "INFY", name: "Infosys Limited", total: 3,
  groups: [
    { key: "concall_transcript", label: "Earnings transcripts", documents: [
      { docId: "d1", url: "https://example.test/infy-call.pdf", filedAt: "2026-07-14T00:00:00Z",
        pages: 22, bytes: 2400000, parsed: true },
    ] },
    { key: "investor_presentation", label: "Investor presentations", documents: [
      { docId: "d2", url: "https://example.test/infy-ppt.pdf", filedAt: "2026-07-14T00:00:00Z",
        pages: 30, bytes: 5100000, parsed: true },
      { docId: "d3", url: null, filedAt: "2026-04-10T00:00:00Z", pages: null, bytes: null, parsed: false },
    ] },
  ],
};

/** Scoped feed: fewer rows AND a narrower taxonomy than the unscoped feed. */
const FEED_SCOPED = {
  ok: true, total: 1, facets: { earnings: 1 },
  rows: [{ ...FEED.rows[0], ticker: "INFY", code: "INFY", name: "Infosys Limited" }],
};

const json = (body: unknown, status = 200) => ({
  status, contentType: "application/json", body: JSON.stringify(body),
});

async function mockFilings(page: Page) {
  await mockApi(page, "populated");
  // Registered AFTER mockApi so these win (Playwright runs handlers LIFO).
  await page.route("**/api/filings/feed**", (r) => r.fulfill(json(FEED)));
  await page.route("**/api/filings/signals**", (r) => r.fulfill(json(SIGNALS)));
  await page.route("**/api/filings/ANN-1/insights**", (r) => r.fulfill(json(INSIGHT_TRANSCRIPT)));
  await page.route("**/api/filings/ANN-2/insights**", (r) => r.fulfill(json(INSIGHT_ANNUAL)));
  await page.route("**/api/filings/companies/search**", (r) => r.fulfill(json(COMPANIES)));
  await page.route("**/api/filings/companies/INFY/documents**", (r) => r.fulfill(json(DOCS)));
}

test.describe("Filings Intelligence — feed", () => {
  test.beforeEach(async ({ page }) => { await mockFilings(page); });

  test("TC-12 · renders real feed rows, facets and sort controls", async ({ page }) => {
    await page.goto("/v5/research");
    await page.waitForLoadState("networkidle");

    await expect(page.getByTestId("filing-row")).toHaveCount(2);
    await expect(page.getByText("HDFC Asset Management Co")).toBeVisible();
    await expect(page.getByText("All filings · 2 results")).toBeVisible();
    await expect(page.getByTestId("sort-material")).toBeVisible();
    await expect(page.getByTestId("sort-latest")).toBeVisible();
    // facet chips come from the response's real category counts
    await expect(page.getByRole("button", { name: "Earnings", exact: true })).toBeVisible();
  });

  test("TC-16 · desktop shows the icon rail", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/v5/research");
    await page.waitForLoadState("networkidle");

    await expect(page.getByTestId("rail-feed")).toBeVisible();
    await expect(page.getByTestId("rail-alerts")).toBeVisible();
    await expect(page.getByTestId("mnav-feed")).toBeHidden();
  });

  test("TC-17 · mobile shows the bottom tab bar and hides the rail", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/v5/research");
    await page.waitForLoadState("networkidle");

    await expect(page.getByTestId("mnav-feed")).toBeVisible();
    await expect(page.getByTestId("mnav-alerts")).toBeVisible();
    await expect(page.getByTestId("rail-feed")).toBeHidden();
  });
});

test.describe("Filings Intelligence — insight panel", () => {
  test.beforeEach(async ({ page }) => { await mockFilings(page); });

  test("TC-13 · expanding a filing shows tabs, sectioned bullets and a page citation", async ({ page }) => {
    await page.goto("/v5/research");
    await page.waitForLoadState("networkidle");

    await page.getByTestId("filing-row").first().getByTestId("toggle-insight").click();
    const panel = page.getByTestId("insight-panel");
    await expect(panel).toBeVisible();

    // tabs come from the response, not a hardcoded list
    await expect(panel.getByTestId("insight-tab")).toHaveCount(2);
    await expect(panel.getByRole("button", { name: "Quick Summary" })).toBeVisible();

    // sectioned bullets render as a real heading + list
    const section = panel.getByTestId("insight-section").first();
    await expect(section.getByRole("heading", { level: 4 })).toContainText("Financial results");
    await expect(section.locator("li")).toHaveCount(2);
    await expect(section.locator("li").first()).toContainText("Revenue grew 14% YoY");

    // the citation deep-links into the source PDF at the cited page
    const cite = section.getByRole("link", { name: /pp\. 6-8/ });
    await expect(cite).toBeVisible();
    await expect(cite).toHaveAttribute("href", "https://example.test/hdfcamc.pdf#page=6");
  });

  test("TC-13b · switching tabs swaps the sections", async ({ page }) => {
    await page.goto("/v5/research");
    await page.waitForLoadState("networkidle");
    await page.getByTestId("filing-row").first().getByTestId("toggle-insight").click();

    const panel = page.getByTestId("insight-panel");
    await panel.getByRole("button", { name: "Potential Risks" }).click();
    await expect(panel.getByTestId("insight-section")).toHaveCount(1);
    await expect(panel.getByTestId("insight-section")).toContainText("Sustained debt outflows");
    // a section with no citation shows none — it does not invent one
    await expect(panel.getByTestId("insight-section").getByRole("link")).toHaveCount(0);
  });

  test("TC-4 · an annual report gets the annual-report tab set", async ({ page }) => {
    await page.goto("/v5/research");
    await page.waitForLoadState("networkidle");

    await page.getByTestId("filing-row").nth(1).getByTestId("toggle-insight").click();
    const panel = page.getByTestId("insight-panel");
    await expect(panel.getByRole("button", { name: "Business Overview" })).toBeVisible();
    await expect(panel.getByRole("button", { name: "Accounting Notes" })).toBeVisible();
    // the generic tabs must NOT appear on an annual report
    await expect(panel.getByRole("button", { name: "Potential Risks" })).toHaveCount(0);
  });

  test("TC-14 · a filing with no generated insight degrades honestly", async ({ page }) => {
    await page.route("**/api/filings/ANN-2/insights**", (r) =>
      r.fulfill(json({ ok: false, reason: "no_insight_yet" }, 404)));

    await page.goto("/v5/research");
    await page.waitForLoadState("networkidle");
    await page.getByTestId("filing-row").nth(1).getByTestId("toggle-insight").click();

    await expect(page.getByTestId("no-insight")).toContainText("No AI insight has been generated");
    // and it must not fabricate sections or a metric
    await expect(page.getByTestId("insight-section")).toHaveCount(0);
  });
});

test.describe("Filings Intelligence — alerts", () => {
  test("TC-8/TC-15 · alerts screen renders prefs and persists a toggle", async ({ page }) => {
    await mockFilings(page);

    let saved: Record<string, unknown> | null = null;
    await page.route("**/api/filings/alerts", async (route) => {
      if (route.request().method() === "PUT") {
        const body = route.request().postDataJSON() as Record<string, unknown>;
        saved = body;
        return route.fulfill(json({ ...ALERTS_DEFAULT, ...body, updatedAt: "2026-07-19T10:00:00Z" }));
      }
      return route.fulfill(json(saved ? { ...ALERTS_DEFAULT, ...saved } : ALERTS_DEFAULT));
    });

    await page.goto("/v5/research");
    await page.waitForLoadState("networkidle");
    await page.getByTestId("rail-alerts").click();

    const screen = page.getByTestId("alerts-screen");
    await expect(screen).toBeVisible();
    await expect(screen.getByText("Earnings transcripts")).toBeVisible();

    // defaults from the API, not hardcoded in the component
    const whatsapp = page.getByTestId("channel-whatsapp");
    await expect(whatsapp).toHaveAttribute("aria-checked", "false");

    await whatsapp.click();
    await expect(whatsapp).toHaveAttribute("aria-checked", "true");
    // proves it round-tripped through the API rather than living in local state
    await expect.poll(() => saved).not.toBeNull();
  });

  test("TC-15b · delivery is disclosed as not switched on", async ({ page }) => {
    await mockFilings(page);
    await page.route("**/api/filings/alerts", (r) => r.fulfill(json(ALERTS_DEFAULT)));

    await page.goto("/v5/research");
    await page.waitForLoadState("networkidle");
    await page.getByTestId("rail-alerts").click();

    await expect(page.getByTestId("delivery-notice"))
      .toContainText("delivery is not switched on yet");
  });

  test("a failed save reverts the toggle instead of showing a false state", async ({ page }) => {
    await mockFilings(page);
    await page.route("**/api/filings/alerts", (route) =>
      route.request().method() === "PUT"
        ? route.fulfill(json({ detail: "nope" }, 500))
        : route.fulfill(json(ALERTS_DEFAULT)));

    await page.goto("/v5/research");
    await page.waitForLoadState("networkidle");
    await page.getByTestId("rail-alerts").click();

    const whatsapp = page.getByTestId("channel-whatsapp");
    await whatsapp.click();
    await expect(whatsapp).toHaveAttribute("aria-checked", "false");
    await expect(page.getByText("Couldn't save that")).toBeVisible();
  });
});


test.describe("Filings Intelligence — company search & documents", () => {
  test.beforeEach(async ({ page }) => { await mockFilings(page); });

  test("TC-22 · typing suggests companies and selecting one scopes the feed", async ({ page }) => {
    // The scoped feed must be served only when ?symbol= is present, so this
    // asserts the request is actually parameterised — not just that the UI changed.
    await page.route("**/api/filings/feed**", (route) => {
      const url = new URL(route.request().url());
      return route.fulfill(json(url.searchParams.get("symbol") === "INFY" ? FEED_SCOPED : FEED));
    });

    await page.goto("/v5/research");
    await page.waitForLoadState("networkidle");
    await expect(page.getByTestId("filing-row")).toHaveCount(2);

    await page.getByTestId("filings-search").fill("infy");
    const list = page.getByTestId("company-suggestions");
    await expect(list).toBeVisible();
    await expect(page.getByTestId("company-suggestion")).toHaveCount(2);

    await page.getByTestId("company-suggestion").first().click();

    // scoped: chip replaces the box, feed narrows, taxonomy narrows with it
    await expect(page.getByTestId("company-scope")).toContainText("INFY");
    await expect(page.getByTestId("filing-row")).toHaveCount(1);
    await expect(page.getByText("INFY filings · 1 results")).toBeVisible();
    await expect(page.getByRole("button", { name: "Earnings", exact: true })).toBeVisible();
    // ORDERS belonged to the whole-tape taxonomy (FEED.facets) and is absent from
    // FEED_SCOPED.facets — it must disappear, proving facets follow the scope.
    await expect(page.getByRole("button", { name: "Orders", exact: true })).toHaveCount(0);
  });

  test("TC-23 · clearing the company resets to ALL", async ({ page }) => {
    await page.route("**/api/filings/feed**", (route) => {
      const url = new URL(route.request().url());
      return route.fulfill(json(url.searchParams.get("symbol") === "INFY" ? FEED_SCOPED : FEED));
    });

    await page.goto("/v5/research");
    await page.waitForLoadState("networkidle");
    await page.getByTestId("filings-search").fill("infy");
    // The type-ahead is debounced (220ms) + async; wait for the list rather than
    // racing it — under parallel workers this is the difference between a stable
    // test and an intermittent one.
    await expect(page.getByTestId("company-suggestions")).toBeVisible();
    await page.getByTestId("company-suggestion").first().click();
    await expect(page.getByTestId("filing-row")).toHaveCount(1);

    await page.getByTestId("clear-company").click();
    await expect(page.getByTestId("company-scope")).toHaveCount(0);
    await expect(page.getByTestId("filing-row")).toHaveCount(2);
    // the whole-tape taxonomy is back
    await expect(page.getByRole("button", { name: "Orders", exact: true })).toBeVisible();
  });

  test("TC-24 · the document library lists downloadable filings by type", async ({ page }) => {
    await page.goto("/v5/research");
    await page.waitForLoadState("networkidle");
    await page.getByTestId("filings-search").fill("infy");
    // The type-ahead is debounced (220ms) + async; wait for the list rather than
    // racing it — under parallel workers this is the difference between a stable
    // test and an intermittent one.
    await expect(page.getByTestId("company-suggestions")).toBeVisible();
    await page.getByTestId("company-suggestion").first().click();

    const panel = page.getByTestId("documents-panel");
    await expect(panel).toBeVisible();
    await expect(panel.getByTestId("doc-group-tab")).toHaveCount(2);
    await expect(panel.getByTestId("doc-group-tab").first()).toContainText("Earnings transcripts · 1");

    const dl = panel.getByTestId("doc-download").first();
    await expect(dl).toHaveAttribute("href", "https://example.test/infy-call.pdf");
    await expect(panel.getByTestId("doc-row").first()).toContainText("read by Nivesh");

    // switch group — the second one carries a document with no URL
    await panel.getByTestId("doc-group-tab").nth(1).click();
    await expect(panel.getByTestId("doc-row")).toHaveCount(2);
    await expect(panel.getByText("no file")).toBeVisible();
    await expect(panel.getByText("not parsed")).toBeVisible();
  });

  test("TC-25 · a company with no documents says so instead of showing an empty shell", async ({ page }) => {
    await page.route("**/api/filings/companies/INFY/documents**", (r) =>
      r.fulfill(json({ ok: true, symbol: "INFY", name: "Infosys Limited", total: 0, groups: [] })));

    await page.goto("/v5/research");
    await page.waitForLoadState("networkidle");
    await page.getByTestId("filings-search").fill("infy");
    // The type-ahead is debounced (220ms) + async; wait for the list rather than
    // racing it — under parallel workers this is the difference between a stable
    // test and an intermittent one.
    await expect(page.getByTestId("company-suggestions")).toBeVisible();
    await page.getByTestId("company-suggestion").first().click();

    await expect(page.getByTestId("no-documents")).toContainText("No source documents on file");
    await expect(page.getByTestId("doc-row")).toHaveCount(0);
  });

  test("TC-26 · keyboard: ArrowDown + Enter selects a suggestion", async ({ page }) => {
    await page.goto("/v5/research");
    await page.waitForLoadState("networkidle");
    const box = page.getByTestId("filings-search");
    await box.fill("inf");
    await expect(page.getByTestId("company-suggestions")).toBeVisible();
    await box.press("ArrowDown");
    await box.press("ArrowDown");
    await box.press("Enter");
    await expect(page.getByTestId("company-scope")).toContainText("INFIBEAM");
  });
});
