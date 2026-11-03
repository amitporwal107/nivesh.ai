/**
 * Market Desk › Market Recovery (owner, 3 Nov 2026; docs/market_recovery/DESIGN.md test cases TC-E1..TC-E6).
 *
 * Every /api/* call is answered by route mocks. The answer below is MOCK — not real data: invented numbers, dates, symbols
 * (FIX*) and neutral sentences in the shape of GET /api/market-recovery, so what these cases check is the SCREEN (where each
 * figure goes, what opens, what each failure says), never a market reading. The real answer is checked against the warehouse
 * in the backend's own tests and the staging report.
 *
 * TC-E5 is the page's wording lint. The desk-wide lint (copilot-app-compliance-wording.spec.ts) bans trading-call words on
 * every desk place; on THIS view the owner chose the standard plan words (3 Nov, AskUserQuestion: "Entry zone · Stop loss ·
 * Target 1 / Target 2"), so the lint here removes exactly those four labels and nothing else, then expects no banned word.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", name), "utf-8"));

const DESK = "/v5/app/trader/desk";
const MARKET = `${DESK}?tab=market`;
const RECOVERY = `${DESK}?tab=market&view=recovery`;
const SLOW = { timeout: 15_000 };
const reply = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const params = (page: Page) => new URL(page.url()).searchParams;

// ── MOCK — not real data ─────────────────────────────────────────────────────────────────────────────────────────────

const AS_OF = "2026-10-30";
const series = Array.from({ length: 30 }, (_, i) => {
  const d = new Date(Date.UTC(2026, 8, 18) + i * 86_400_000).toISOString().slice(0, 10);
  return { date: d, above20_pct: 30 + i * 1.2, above50_pct: 38 + i * 0.6, advancers_pct: 45 + (i % 5) * 3, nifty_close: 24_800 + i * 30 };
});
const part = (label: string, points: number, max: number, value: string, ok: boolean | null = points > 0) => ({ label, points, max, value, ok });
const components = (k: number) => [
  { key: "relative_strength", label: "Relative strength", points: 20 * k, max: 25, rescaled: false,
    parts: [part("vs Nifty 500, 20 sessions", 10 * k, 12.5, "+8.0 pp"), part("vs own sector, 20 sessions", 10 * k, 12.5, "+6.0 pp")] },
  { key: "technical", label: "Technical recovery", points: 20 * k, max: 25, rescaled: false,
    parts: [part("Close above 20-day EMA", 5, 5, "+3.1%"), part("Close above 50-day EMA", 5, 5, "+6.0%"), part("EMA gap widening", 5, 5, "+0.4 pp"),
      part("RSI 14 in 50–70", 5 * k, 5, "61.2"), part("Higher lows", 0, 5, "no", false)] },
  { key: "volume_delivery", label: "Volume and delivery", points: 15 * k, max: 20, rescaled: false,
    parts: [part("Volume ratio 5D / 50D", 7, 7, "1.6×"), part("Up-day vs down-day volume", 6 * k, 6, "1.4×"), part("Delivery 5D vs 20D", 2, 7, "1.03×")] },
  { key: "fundamental", label: "Fundamental quality", points: 16 * k, max: 20, rescaled: true,
    parts: [part("ROCE", 5, 5, "24%"), part("Debt to equity", 5, 5, "0.1"), part("PAT growth", 5 * k, 5, "+14%"), part("CFO / PAT", 0, 5, "—", null)] },
  { key: "smart_money", label: "Smart money", points: 6 * k, max: 10, rescaled: false,
    parts: [part("FII stake change", 2, 4, "+0.5 pp"), part("Accumulation score", 2 * k, 3, "66"), part("Up days on high volume", 2, 3, "2 of 5")] },
];
const accel = [
  { key: "rs", label: "Relative strength vs Nifty 500 (20D)", unit: "pp", then: -3.0, now: 2.0, improving: true },
  { key: "rsi", label: "RSI 14", unit: "rsi", then: 39, now: 54, improving: true },
  { key: "ema20", label: "Distance from the 20-day EMA", unit: "pct", then: -7.0, now: 1.0, improving: true },
  { key: "volume", label: "Volume ratio", unit: "ratio", then: 0.7, now: 1.8, improving: true },
  { key: "delivery", label: "Delivery trend", unit: "pp", then: -0.4, now: 0.6, improving: true },
  { key: "sector", label: "Sector relative strength (20D)", unit: "pp", then: 1.0, now: 0.5, improving: false },
];
const candidate = (rank: number, symbol: string, sector: string, score: number, k: number, plan: boolean) => ({
  rank, symbol, name: `${symbol} Ltd`, sector, sector_rank: rank, sector_state: "leadership", close: 1000 + rank * 10,
  score, meets_priority: score >= 75,
  components: components(k),
  acceleration: { score: 78 - rank, improving: 5, of: 6, rows: accel },
  setup: { key: rank === 1 ? "breakout" : "pullback", label: rank === 1 ? "Early breakout" : "Pullback in an uptrend", why: "Closed above its 20-session high on 1.8× its usual volume." },
  plan: plan ? { entry_low: 990.5, entry_high: 1010, stop_loss: 951.25, target_1: 1105, target_2: 1186.25, rr_1: 1.6, rr_2: 3.0, risk_pct: 5.8,
    basis: "recovery-plan-v1 (MOCK basis text)" } : null,
  metrics: { rs_vs_index_20d: 8, rs_vs_sector_20d: 6, rsi14: 61.2, volume_ratio: 1.6, pct_vs_ema20: 3.1, deliv_5d: 52, deliv_20d: 47, atr14: 25,
    traded_value_cr_20d: 210, market_cap_cr: 112_000, roce: 24, roe: 19, de: 0.1, pat_growth: 14, cfo_pat: null, fii_change_qoq: 0.5 },
  reasons: ["Outperformed Nifty 500 by 8.0 pp over 20 sessions", "Sector ranked in the top five"],
  cautions: ["Results due in 6 days"],
  gaps: ["Cash flow (CFO/PAT) not available"],
});
const SECTOR_NAMES = ["Capital Goods", "Realty", "Financial Services", "Healthcare", "Automobile and Auto Components", "Information Technology"];
const ANSWER = {
  method: "recovery-radar-v1",
  as_of: AS_OF,
  computed_at: "2026-10-30T13:40:02Z",
  universe: { name: "Nifty 500", members: 501, members_as_of: "2026-10-28", scored: 470, left_out: { no_bar: 8, liquidity: 12, market_cap: 3, history: 2 } },
  regime: {
    status: "underway", label: "Recovery under way", line: "MOCK line: the index is above its 20-day average and breadth widened over 5 sessions.",
    passed: 4, total: 5,
    checks: [
      { id: "nifty_above_20dma", label: "Nifty 50 above its 20-day average", importance: "high", pass: true, value: "25,812 vs 25,410 (+1.6%)" },
      { id: "nifty_20dma_rising", label: "Nifty 50 20-day average rising", importance: "high", pass: true, value: "25,410 vs 25,301" },
      { id: "advancers_60", label: "60% or more of Nifty 500 advanced", importance: "high", pass: false, value: "54%" },
      { id: "breadth_expanding", label: "More Nifty 500 stocks above their 20-day average", importance: "very_high", pass: true, value: "64% vs 48%" },
      { id: "vix_falling", label: "India VIX falling", importance: "medium", pass: true, value: "12.1 vs 13.4" },
    ],
    nifty: { index: "Nifty 50", close: 25_812.4, sma20: 25_410.2, sma20_5ago: 25_301, pct_vs_sma20: 1.58 },
    breadth: { counted: 493, advancers_pct: 54, advancers_pct_5d_avg: 56, above20_pct: 64.2, above20_pct_5ago: 48.3, above50_pct: 51, above50_pct_5ago: 44.9 },
    vix: { close: 12.1, close_5ago: 13.4, change_pct: -9.7 },
    caps: [
      { key: "large", label: "Nifty 100", members: 100, above20_pct: 70, above20_pct_5ago: 52, above50_pct: 58 },
      { key: "mid", label: "Nifty Midcap 150", members: 150, above20_pct: 63, above20_pct_5ago: 47, above50_pct: 50 },
      { key: "small", label: "Nifty Smallcap 250", members: 250, above20_pct: 58, above20_pct_5ago: 44, above50_pct: 47 },
    ],
  },
  breadth_series: series,
  sectors: SECTOR_NAMES.map((s, i) => ({
    sector: s, members: 30 - i, ret_5d: 3 - i, ret_10d: 5 - i, ret_20d: 8 - i * 2, rs_5d: 1.2 - i * 0.5, rs_10d: 2 - i * 0.6, rs_20d: 3.4 - i * 1.4,
    rs_20d_5ago: 1.1 - i, rs_change: 2.3 - i * 0.4, above20_pct: 78 - i * 8, above50_pct: 66 - i * 7, delivery_up_pct: 55 - i * 4,
    state: ["leadership", "leadership", "recovery", "emerging", "neutral", "weak"][i], state_label: ["Leadership", "Leadership", "Recovery", "Emerging", "Neutral", "Weak — avoid for now"][i],
    rank: i + 1, leader: i < 5,
  })),
  leaders: SECTOR_NAMES.slice(0, 5),
  candidates: [candidate(1, "FIXA", "Capital Goods", 86.4, 1, true), candidate(2, "FIXB", "Realty", 71.0, 0.8, true)],
  others: [candidate(1, "FIXC", "Information Technology", 68.2, 0.7, false)],
  excluded: [
    { symbol: "FIXD", name: "FIXD Ltd", sector: "Realty", score: 81, trap: "dead_cat", label: "Dead-cat bounce", reason: "Up 6.2% in 5 sessions but below a falling 50-day and its 200-day average." },
    { symbol: "FIXE", name: "FIXE Ltd", sector: "Capital Goods", score: 79, trap: "short_covering", label: "Short covering", reason: "Futures price up 2.1% while open interest fell 6.0%." },
  ],
  thresholds: { priority_score: 75, min_traded_value_cr: 5, min_market_cap_cr: 1000 },
  sources: [
    { what: "Daily prices", source: "NSE end-of-day bars (split/bonus adjusted), NIDP warehouse", as_of: AS_OF },
    { what: "Index levels", source: "NSE index closes, NIDP warehouse", as_of: AS_OF },
  ],
  notes: ["MOCK note: weights are the proposal's; thresholds untuned."],
  warnings: ["MOCK warning: delivery data is one session behind prices."],
};

// ── the desk with the flag and the route under test ─────────────────────────────────────────────────────────────────

interface Backend { calls: number }

async function desk(page: Page, o: { flag?: boolean; answer?: () => { status: number; body: unknown } } = {}): Promise<Backend> {
  const be: Backend = { calls: 0 };
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (r) => reply(r, []));
  await page.route("**/api/move-odds/**", (r) => reply(r, { detail: "feature_not_enabled" }, 403));
  const base = load("user-profile-onboarded.json");
  await page.route("**/api/auth/me", (r) => reply(r, { ...base, features: { ...(base.features ?? {}), market_recovery: o.flag !== false } }));
  await page.route("**/api/market-recovery", (r) => {
    be.calls += 1;
    const a = o.answer ? o.answer() : { status: 200, body: ANSWER };
    return reply(r, a.body, a.status);
  });
  return be;
}

async function openRecovery(page: Page) {
  await page.goto(RECOVERY);
  await expect(page.getByTestId("mr-ready")).toBeVisible(SLOW);
}

const price = (v: number) => v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// The desk-wide banned words (copilot-app-compliance-wording.spec.ts LINT), and the page's only exception.
const LINT = new RegExp(
  "\\b(buy|buys|buying|bought|sell|sells|selling|sold|stop[- ]?loss(?:es)?|sl|stops?|targets?|t1|t2|entry|entries|exit|exits|" +
    "exited|book(?:ing)?\\s+profits?|profit[- ]booking|accumulate|trim|upside|downside|recommend\\w*|picks?|price\\s+targets?|" +
    "suggested\\s+(?:trade|trades|strateg(?:y|ies)))\\b",
  "gi",
);
const ALLOW = [
  /\bexit\s+load\b/gi, /\b(?:long|short)\s+build[- ]?ups?\b/gi, /\bstop\s+(?:the\s+answer|generating)\b/gi, /\b(?:you\s+)?stopped\s+this\s+answer\b/gi,
  /\bupdates\s+stopped\b/gi,
];
/** The owner's plan words for this page (3 Nov) — exactly these four labels, nothing broader. Case-insensitive only because the
 *  table headers are upper-cased by CSS ("ENTRY ZONE" in innerText). */
const PLAN_LABELS = [/\bEntry zone\b/gi, /\bStop loss\b/gi, /\bTarget 1\b/gi, /\bTarget 2\b/gi];
function hits(text: string): string[] {
  let t = text;
  for (const a of [...ALLOW, ...PLAN_LABELS]) t = t.replace(a, " ");
  return [...t.matchAll(LINT)].map((m) => m[0]);
}

test.describe("MOCK — not real data: Market Desk › Market Recovery", () => {
  test("TC-E1 with the flag on the switcher offers Market Recovery last; the view shows the check, breadth, sectors and candidates", async ({ page }) => {
    const be = await desk(page);
    await page.goto(MARKET);
    await expect(page.getByTestId("desk-views")).toBeVisible(SLOW);
    await expect(page.getByTestId("desk-views").getByRole("button")).toHaveText(
      ["Market Intelligence", "Smart Money", "Sector Rotation", "Stock Research", "Screener", "Market Recovery"]);
    expect(be.calls).toBe(0);                                                  // nothing is asked until the view opens
    await page.getByTestId("desk-view-recovery").click();
    await expect.poll(() => params(page).get("view")).toBe("recovery");
    await expect(page.getByTestId("desk-view-recovery")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("md-eyebrow")).toHaveText("Market Desk · Market Recovery");
    await expect(page.getByTestId("md-line")).not.toBeEmpty();
    await expect(page.getByTestId("mr-ready")).toBeVisible(SLOW);
    await expect(page.getByTestId("mr-ready")).toHaveAttribute("data-as-of", AS_OF);
    await expect(page.getByTestId("mr-asof")).toContainText("470 of 501 Nifty 500 stocks scored");
    await expect(page.getByTestId("mr-left-out")).toContainText("12 below ₹5 cr average traded value");
    await expect(page.getByTestId("mr-warnings")).toContainText("delivery data is one session behind");

    // 1. the recovery check
    await expect(page.getByTestId("mr-regime-status")).toHaveAttribute("data-status", "underway");
    await expect(page.getByTestId("mr-regime-status")).toContainText("Recovery under way");
    await expect(page.getByTestId("mr-regime-passed")).toHaveText("4 of 5 checks pass");
    await expect(page.getByTestId("mr-check")).toHaveCount(5);
    await expect(page.locator('[data-testid="mr-check"][data-pass="false"]')).toHaveAttribute("data-check", "advancers_60");
    await expect(page.locator('[data-testid="mr-check"][data-check="breadth_expanding"]')).toContainText("64% vs 48%");
    await expect(page.getByTestId("mr-figures")).toContainText("25,812.40");
    await expect(page.getByTestId("mr-cap-row")).toHaveCount(3);
    await expect(page.locator('[data-testid="mr-cap-row"][data-cap="small"]')).toContainText("Nifty Smallcap 250");
    await expect(page.getByTestId("mr-breadth-chart")).toBeVisible();
    await expect(page.getByTestId("mr-breadth-legend")).toContainText("Above 20-day avg");
    await expect(page.getByTestId("mr-breadth-legend")).toContainText("Above 50-day avg");

    // 2. sectors: six rows, the top five marked leading
    await expect(page.getByTestId("mr-sector-row")).toHaveCount(6);
    await expect(page.locator('[data-testid="mr-sector-row"][data-leader="true"]')).toHaveCount(5);
    await expect(page.locator('[data-testid="mr-sector-row"]').first()).toHaveAttribute("data-sector", "Capital Goods");
    await expect(page.locator('[data-testid="mr-sector-row"][data-sector="Information Technology"]')).toContainText("Weak — avoid for now");

    // 3. candidates and others; 4. excluded; the footer
    const lead = page.getByTestId("mr-candidates");
    await expect(lead.getByTestId("mr-cand-row")).toHaveCount(2);
    await expect(lead.locator('[data-testid="mr-cand-row"]').first()).toHaveAttribute("data-symbol", "FIXA");
    await expect(lead.locator('[data-testid="mr-cand-row"][data-symbol="FIXA"]').getByTestId("mr-priority")).toBeVisible();
    await expect(lead.locator('[data-testid="mr-cand-row"][data-symbol="FIXB"]').getByTestId("mr-priority")).toHaveCount(0);
    await expect(lead.locator('[data-testid="mr-cand-row"][data-symbol="FIXA"]').getByTestId("mr-stop")).toHaveText(price(951.25));
    await expect(lead.locator('[data-testid="mr-cand-row"][data-symbol="FIXA"]').getByTestId("mr-t1")).toHaveText(price(1105));
    await expect(page.getByTestId("mr-others").getByTestId("mr-cand-row")).toHaveCount(1);
    await expect(page.getByTestId("mr-others").getByTestId("mr-no-plan")).toHaveText("No plan for this stock");
    await expect(page.getByTestId("mr-excluded-row")).toHaveCount(2);
    await expect(page.locator('[data-testid="mr-excluded-row"][data-trap="dead_cat"]')).toContainText("Dead-cat bounce");
    await expect(page.getByTestId("mr-sources")).toContainText(`as of ${AS_OF}`);
    await expect(page.getByTestId("mr-disclaimer")).toContainText("not investment advice");
    await expect(page.getByTestId("mr-disclaimer")).toContainText("have not been back-tested yet");
    expect(be.calls).toBe(1);
  });

  test("TC-E2 a candidate opens its detail: five components, the 5-session table, the plan with its standard labels, reasons", async ({ page }) => {
    await desk(page);
    await openRecovery(page);
    const row = page.getByTestId("mr-candidates").locator('[data-testid="mr-cand-row"][data-symbol="FIXA"]');
    const toggle = row.getByTestId("mr-cand-toggle");
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    const detail = page.locator('[data-testid="mr-cand-detail"][data-symbol="FIXA"]');
    await expect(detail).toBeVisible();
    for (const label of ["Relative strength", "Technical recovery", "Volume and delivery", "Fundamental quality", "Smart money"]) {
      await expect(detail.getByTestId("mr-detail-components")).toContainText(label);
    }
    await expect(detail.getByTestId("mr-detail-components")).toContainText("rescaled over the parts with data");
    await expect(detail.getByTestId("mr-accel-row")).toHaveCount(6);
    await expect(detail.locator('[data-testid="mr-accel-row"][data-key="rsi"]')).toContainText("39.0");
    await expect(detail.locator('[data-testid="mr-accel-row"][data-key="rsi"]')).toContainText("54.0");
    await expect(detail.locator('[data-testid="mr-accel-row"][data-key="volume"]')).toContainText("1.80×");
    await expect(detail.locator('[data-testid="mr-accel-row"][data-key="sector"]')).toHaveAttribute("data-improving", "false");
    const plan = detail.getByTestId("mr-detail-plan");
    for (const label of ["Entry zone", "Stop loss", "Target 1", "Target 2"]) await expect(plan).toContainText(label);
    await expect(plan).toContainText(`${price(990.5)}–${price(1010)}`);
    await expect(plan).toContainText("5.8% below the close");
    await expect(detail.getByTestId("mr-plan-basis")).toContainText("recovery-plan-v1");
    await expect(detail.getByTestId("mr-detail-reasons")).toContainText("Outperformed Nifty 500 by 8.0 pp");
    await expect(detail.getByTestId("mr-detail-cautions")).toContainText("Results due in 6 days");
    const gaps = detail.getByTestId("mr-detail-gaps");
    await expect(gaps).toHaveAttribute("data-count", "1");
    await expect(gaps.locator("summary")).toHaveText("1 figure not available");
    await gaps.locator("summary").click();
    await expect(gaps).toContainText("Cash flow (CFO/PAT) not available");
    await expect(detail.getByTestId("mr-detail-setup")).toContainText("Early breakout");
    await toggle.click();
    await expect(detail).toHaveCount(0);

    // The chart's readout: hover finds a session, and so does the keyboard.
    const chart = page.getByTestId("mr-breadth-chart");
    await chart.hover({ position: { x: 60, y: 60 } });
    await expect(page.getByTestId("mr-breadth-hover")).toContainText("above 20-day");
    await page.mouse.move(0, 0);
    await chart.focus();
    await page.keyboard.press("ArrowLeft");
    await expect(page.getByTestId("mr-breadth-hover")).toContainText(series[28].date);
  });

  test("TC-E3 with the flag off the switcher has five views, and the URL says the view is not enabled without asking the API", async ({ page }) => {
    const be = await desk(page, { flag: false });
    await page.goto(MARKET);
    await expect(page.getByTestId("desk-views")).toBeVisible(SLOW);
    await expect(page.getByTestId("desk-views").getByRole("button")).toHaveText(["Market Intelligence", "Smart Money", "Sector Rotation", "Stock Research", "Screener"]);
    await expect(page.getByTestId("desk-view-recovery")).toHaveCount(0);
    await page.goto(RECOVERY);
    await expect(page.getByTestId("mr-off")).toContainText("not enabled for your account", SLOW);
    await expect(page.getByTestId("mr-ready")).toHaveCount(0);
    expect(be.calls).toBe(0);
  });

  test("TC-E4 a 503 shows the server's own message; a 403 reads as not enabled; no candidates shows the empty state", async ({ page }) => {
    let mode: "stale" | "forbidden" | "empty" = "stale";
    await desk(page, {
      answer: () => mode === "stale"
        ? { status: 503, body: { detail: { code: "stale_data", message: "MOCK: the newest end-of-day prices are from 2026-10-20." }, status: 503, code: "stale_data" } }
        : mode === "forbidden"
          ? { status: 403, body: { detail: "Feature not enabled" } }
          : { status: 200, body: { ...ANSWER, candidates: [], others: [], excluded: [] } },
    });
    await page.goto(RECOVERY);
    const err = page.getByTestId("mr-error");
    await expect(err).toBeVisible(SLOW);
    await expect(err).toHaveAttribute("data-code", "stale_data");
    await expect(err).toContainText("The latest prices are too old to score");
    await expect(err).toContainText("the newest end-of-day prices are from 2026-10-20");

    mode = "forbidden";
    await page.reload();
    await expect(page.getByTestId("mr-off")).toContainText("not enabled for your account", SLOW);

    mode = "empty";
    await page.reload();
    await expect(page.getByTestId("mr-ready")).toBeVisible(SLOW);
    await expect(page.getByTestId("mr-candidates-empty")).toContainText("No stock in the leading sectors passed the gates");
    await expect(page.getByTestId("mr-others-empty")).toBeVisible();
    await expect(page.getByTestId("mr-excluded-empty")).toBeVisible();
    await expect(page.getByTestId("mr-regime-status")).toBeVisible();
  });

  test("TC-E5 wording: with a detail open, the page shows no trading-call word beyond the owner's four plan labels", async ({ page }) => {
    await desk(page);
    await openRecovery(page);
    await page.getByTestId("mr-candidates").locator('[data-testid="mr-cand-row"][data-symbol="FIXA"]').getByTestId("mr-cand-toggle").click();
    await expect(page.locator('[data-testid="mr-cand-detail"][data-symbol="FIXA"]')).toBeVisible();
    const lines: string[] = await page.evaluate(() => {
      const out = [document.body.innerText];
      for (const el of Array.from(document.querySelectorAll("[aria-label],[title],[placeholder]"))) {
        for (const a of ["aria-label", "title", "placeholder"]) {
          const v = el.getAttribute(a);
          if (v) out.push(v);
        }
      }
      return out.join("\n").split("\n").map((s) => s.trim()).filter(Boolean);
    });
    // the exception is exercised: the four labels are on the page …
    const all = lines.join("\n");
    for (const label of ["Entry zone", "Stop loss", "Target 1", "Target 2"]) expect(all, label).toContain(label);
    // … and nothing else trips the lint
    const found = lines.flatMap((line) => { const w = hits(line); return w.length ? [{ line: line.slice(0, 160), words: w }] : []; });
    expect(found).toEqual([]);
    // the lint itself: a broader word still fails it
    expect(hits("Stop at 950")).not.toEqual([]);
    expect(hits("Buy above 1010")).not.toEqual([]);
    expect(hits("Target 3")).not.toEqual([]);
    expect(hits("Entry")).not.toEqual([]);
    expect(hits("STOP")).not.toEqual([]);
  });
});

test.describe("MOCK — not real data: Market Desk › Market Recovery · phone 390px", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("TC-E6 at 390 px the page does not scroll sideways; the tables scroll inside their own box", async ({ page }) => {
    await desk(page);
    await openRecovery(page);
    await page.getByTestId("mr-candidates").locator('[data-testid="mr-cand-row"][data-symbol="FIXA"]').getByTestId("mr-cand-toggle").click();
    await expect(page.locator('[data-testid="mr-cand-detail"][data-symbol="FIXA"]')).toBeVisible();
    const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(over).toBeLessThanOrEqual(1);
    for (const id of ["mr-regime", "mr-sectors", "mr-candidates", "mr-excluded"]) {
      const b = await page.getByTestId(id).boundingBox();
      expect(b, id).not.toBeNull();
      expect(b!.x + b!.width, id).toBeLessThanOrEqual(391);
    }
    const scrolls = await page.getByTestId("mr-candidates").locator(".cp-scroll").first().evaluate((el) => el.scrollWidth > el.clientWidth);
    expect(scrolls).toBe(true);
  });
});
