/**
 * Research feed → "Candidates for the next session" link → Movers → Candidates mode.
 *
 * MOCK — not real data: every /api/movers* response here is a fixture shaped like
 * backend/nidp/services/daas_api/routers/movers.py's `candidates()` / `mover_detail()`.
 * These cases verify the SCREEN: the link exists and deep-links in, the rail/hero/chart/log
 * render from the candidates payload, the odds-model panels (sensitivity, Copilot attribution,
 * technical score, flag-lift, model panel) are absent, and the API's own rule/disclaimer text
 * is shown verbatim — never paraphrased into a stronger claim.
 */
import { test, expect, type Page } from "@playwright/test";
import { mockAuthAs } from "../helpers/api-mock";

const SESSION = "2026-10-02";
const N = 20;
const DATES = Array.from({ length: N }, (_, i) => {
  const d = new Date(Date.UTC(2026, 8, 14)); d.setUTCDate(d.getUTCDate() + i); return d.toISOString().slice(0, 10);
});
const T = DATES.indexOf(SESSION);
const bars = DATES.map((t, i) => {
  const base = 100 + i * 0.4;
  return { t, o: base * 0.995, h: base * 1.01, l: base * 0.99, c: base, prev_c: base * 0.998,
           v: 800000 + i * 9000, turnover: 6.2e6 };
});
const LANES = [{ key: "fil", label: "RESULTS / FILINGS" }, { key: "ca", label: "CORP ACTION" },
               { key: "deal", label: "BULK / BLOCK" }, { key: "ins", label: "INSIDER / SAST" },
               { key: "mdl", label: "ODDS MODEL" }];

const CANDIDATES = {
  session: SESSION, count: 2,
  rule: "Material filing (impact = high) or bulk/block deal dated this session.",
  disclaimer: "Not a prediction: this surfaces what was disclosed, not what will happen next.",
  candidates: [
    {
      symbol: "AAA", name: "Aaa Industries", session: SESSION, close: 152.0, prev_close: 148.0, pct: 2.7,
      signals: [
        { id: "ann:1", type: "fil", kind: "ORDER / CONTRACT", kind_note: "Business win.", title: "AAA bags Rs500cr order", sub: "From a US client" },
        { id: "deal:BULK:AAA:big fund:10000", type: "dealB", kind: "Bulk deal", kind_note: "Single party >0.5% of equity.", title: "Bulk deal", sub: "Big Fund · 10,000 sh @ ₹150.00" },
      ],
    },
    {
      symbol: "BBB", name: "Bbb Corp", session: SESSION, close: 80.0, prev_close: 80.5, pct: -0.6,
      signals: [
        { id: "ann:2", type: "fil", kind: "EARNINGS", kind_note: "Quarterly results.", title: "BBB board approves Q2 results", sub: "Net profit up 12%" },
      ],
    },
  ],
};

function detailFor(symbol: string) {
  const sig = CANDIDATES.candidates.find((c) => c.symbol === symbol)!.signals;
  return {
    symbol, session: SESSION, range: "T7", from: DATES[0], to: DATES[N - 1],
    header: { pct: 2.7, open: 150, high: 153, low: 149, close: 152, prev_close: 148, volume: 900000, turnover: 1.3e8 },
    bars, market: { name: "Nifty 50", label: "Nifty 50", is_proxy: false, series: bars.map((_, i) => 24000 + i * 10), available: true },
    sector: { name: "Nifty Industrials", series: bars.map((_, i) => 9000 + i * 5), available: true, reason: null, coverage: { mapped: 500, total: 1011 } },
    regression: { beta: 1.0, corr: 0.5, sbeta: 0.6, scorr: 0.4, sessions: 19, requested_sessions: 250, available: true, degraded: true, reason: "SHORT_INDEX_HISTORY" },
    rolling_beta: { before: null, after: null, available: false, reason: "INSUFFICIENT_SESSIONS" },
    windows: [], lanes: LANES,
    insider_lane: { available: false, reason: "NOT_BACKFILLED", note: "nidp.insider_sast not present", source: null },
    events: sig.map((s, i) => ({
      id: s.id, date: SESSION, type: s.type, title: s.title, sub: s.sub, sentiment: null, impact_score: "high",
      bar_index: T, kind: s.kind, kind_note: s.kind_note, lane: s.type === "fil" ? "fil" : "deal",
      type_label: s.type === "fil" ? "FILING" : "DEAL · BOUGHT", glyph: s.type === "fil" ? "F" : "▲",
      flags: [], metrics: null, exec: null,
    })),
    model: { state: "NO_MODEL_RUN", score: null, base_rate: null, head: null, run_session: null, runs_in_window: 0, cutoff: null },
    bar_index_of_session: T,
  };
}

async function setup(page: Page) {
  await mockAuthAs(page, "user-profile-move-odds.json");
  await page.route("**/api/movers/candidates**", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(CANDIDATES) }));
  await page.route("**/api/movers/AAA?**", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(detailFor("AAA")) }));
  await page.route("**/api/movers/BBB?**", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(detailFor("BBB")) }));
}

test.use({ viewport: { width: 1420, height: 1100 } });

test.describe("Research feed → Candidates link → Movers Candidates mode", () => {
  test("the feed screen shows a Candidates link that deep-links into Movers", async ({ page }) => {
    await setup(page);
    await page.goto("/v5/research");
    const link = page.getByTestId("feed-candidates-link");
    await expect(link).toBeVisible();
    await expect(link).toContainText("Candidates for the next session");
    await link.click();
    await expect(page.getByTestId("mv-view")).toBeVisible();
    await expect(page.getByTestId("mv-mode-candidates")).toHaveAttribute("aria-pressed", "true");
  });

  test("candidates render with a signal badge and no odds-model framing", async ({ page }) => {
    await setup(page);
    await page.goto("/v5/research?screen=odds&view=movers&mode=candidates");
    await expect(page.getByTestId("mv-rail-row-AAA")).toBeVisible();
    await expect(page.getByTestId("mv-rail-row-BBB")).toBeVisible();
    await expect(page.getByTestId("mv-rail-row-AAA")).toContainText("FILING + DEAL");
    await expect(page.getByTestId("mv-rail-row-BBB")).toContainText("FILING");

    // AAA auto-selected first (ranked by deal value): hero shows the signal count, not an odds badge.
    await expect(page.getByTestId("mv-hero-name")).toContainText("Aaa Industries");
    await expect(page.getByTestId("mv-hero-signals")).toHaveText("2");
    await expect(page.getByTestId("mv-chart")).toBeVisible();
    await expect(page.getByTestId("mv-log")).toBeVisible();

    // the odds-model-specific panels must not render in this mode
    await expect(page.getByTestId("mv-model-panel")).toHaveCount(0);
    await expect(page.getByTestId("mv-attr")).toHaveCount(0);
    await expect(page.getByTestId("mv-copilot")).toHaveCount(0);
    await expect(page.getByTestId("mv-tech")).toHaveCount(0);
    await expect(page.getByTestId("mv-lift")).toHaveCount(0);

    // the API's own wording is shown verbatim, not paraphrased into a stronger claim
    await expect(page.getByTestId("mv-cand-disclaimer")).toContainText("Material filing (impact = high) or bulk/block deal dated this session.");
    await expect(page.getByTestId("mv-cand-disclaimer")).toContainText("Not a prediction");
  });

  test("selecting BBB swaps the chart and timeline to its own event", async ({ page }) => {
    await setup(page);
    await page.goto("/v5/research?screen=odds&view=movers&mode=candidates");
    await page.getByTestId("mv-rail-row-BBB").click();
    await expect(page.getByTestId("mv-hero-name")).toContainText("Bbb Corp");
    await expect(page.getByTestId("mv-hero-synthesis")).toContainText("BBB board approves Q2 results");
    await expect(page.getByTestId("mv-log")).toContainText("BBB board approves Q2 results");
  });

  test("the FILING / DEAL filter narrows the rail", async ({ page }) => {
    await setup(page);
    await page.goto("/v5/research?screen=odds&view=movers&mode=candidates");
    await page.getByTestId("mv-filter-deal").click();
    await expect(page.getByTestId("mv-rail-row-AAA")).toBeVisible();
    await expect(page.getByTestId("mv-rail-row-BBB")).toHaveCount(0);
    await page.getByTestId("mv-filter-filing").click();
    await expect(page.getByTestId("mv-rail-row-AAA")).toBeVisible();   // AAA has a filing too
    await expect(page.getByTestId("mv-rail-row-BBB")).toBeVisible();
  });

  test("an empty day shows the honest empty state, not a blank list", async ({ page }) => {
    await mockAuthAs(page, "user-profile-move-odds.json");
    await page.route("**/api/movers/candidates**", (r) => r.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({ session: SESSION, count: 0, candidates: [], rule: CANDIDATES.rule, disclaimer: CANDIDATES.disclaimer }),
    }));
    await page.goto("/v5/research?screen=odds&view=movers&mode=candidates");
    await expect(page.getByTestId("mv-cand-empty")).toContainText("No material filing or bulk/block deal on record");
  });
});
