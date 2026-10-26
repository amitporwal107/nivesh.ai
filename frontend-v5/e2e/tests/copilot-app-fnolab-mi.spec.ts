/**
 * One-screen Copilot app (/v5/app/tool/fnolab) — the F&O lab shell (screens/fnolab/FnoLab.tsx, parts.tsx) and
 * 01 Market Intelligence (MarketIntel.tsx, market-intel.ts).
 *
 * MOCK — not real data. Every /api answer below is written by hand to the shapes the routes send:
 * GET /api/macro/today (routes/macro.py), /api/fno/{sym}/expiries|chain|futures (routes/fno.py) and
 * GET /api/live/option-chain (routes/live_quotes.py). Prices, OI, IVs and quotes are INVENTED. Expected text is worked
 * out here from the payloads, not copied from the screen. Production build, every /api mocked — see
 * pw.copilot-app.config.ts.
 *
 * Cases (test_reports/fno_lab_screens_TESTCASES.md): S-1 tabs · S-2 ?screen= and tab clicks · S-3 mode strip per screen ·
 * S-5 phone width · S-6 SEBI note · S-7 no illustrative text · MI-1 underlying switch · MI-2 regime and its absence ·
 * MI-3 build-up per expiry · MI-4 options from the chain · MI-5 quote quality and an empty cache · MI-6 stocks off the
 * feed · MI-7 Greeks source.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const LAB = "/v5/app/tool/fnolab";
const reply = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

// ── the MOCK payloads ────────────────────────────────────────────────────

const MACRO = {
  market: "NEUTRAL", risk: "MEDIUM", insight: "Fixture insight", date: "2026-10-23", days_stale: 2,
  regime: {
    key: "sideways", date: "2026-10-23",
    rule: { version: "desk-regime-v1", vix_high: 20, trend_average_sessions: 50, breadth_up_pct: 60, breadth_down_pct: 40 },
    inputs: {
      nifty_close: 25000.5, nifty_average: 24800, nifty_vs_average_pct: 0.81, trend: "flat", india_vix: 12.3, volatility_high: false,
      advances: 240, declines: 250, unchanged: 10, breadth_universe: 500, advancing_share_pct: 48.98, breadth: "even",
    },
    skipped: [],
    invalidation: [{ input: "india_vix", condition: "at_or_above", level: 20, then: "high_volatility" }],
  },
};
const MACRO_NONE = { _uninitialised: true, _reason: "Fixture: the macro state is not computed yet." };

/**
 * Three NIFTY futures, sent out of order so the screen's expiry order is checked.
 * OI change % = change_in_oi ÷ (oi − change_in_oi), worked per row below.
 */
const FUT = (sym: string) => ({
  symbol: sym, as_of: "2026-10-23", spot: 25010,
  futures: [
    // Dec: 1,000 ÷ (51,000 − 1,000) = +2.0%; price change missing → "—".
    { expiry: "2026-12-29", close: 25300, settle: 25300, oi: 51000, change_in_oi: 1000, volume: 900, basis: 290, prev_close: null, change: null, change_pct: null, oi_buildup: "long unwinding" },
    // Oct: 100,000 ÷ (1,100,000 − 100,000) = +10.0%.
    { expiry: "2026-10-27", close: 25050, settle: 25050, oi: 1100000, change_in_oi: 100000, volume: 50000, basis: 40, prev_close: 25155, change: -105, change_pct: -0.42, oi_buildup: "short build-up" },
    // Nov: 12,000 ÷ (212,000 − 12,000) = +6.0%.
    { expiry: "2026-11-24", close: 25180, settle: 25180, oi: 212000, change_in_oi: 12000, volume: 8000, basis: 170, prev_close: 25275, change: -95, change_pct: -0.38, oi_buildup: "short build-up" },
  ],
});

const EXPIRIES = (sym: string) => ({
  symbol: sym, as_of: "2026-10-23",
  expiries: [{ expiry: "2026-10-27", days_to_expiry: 4 }, { expiry: "2026-11-24", days_to_expiry: 32 }, { expiry: "2026-12-29", days_to_expiry: 67 }],
});

const ATM_IV: Record<string, number> = { "2026-10-27": 13.8, "2026-11-24": 14.6, "2026-12-29": 15.1 };

const side = (o: Record<string, number | null>) => ({
  close: 100, settle: 100, oi: 1000, change_in_oi: 0, volume: 10, iv: 13, iv_price: "settle", delta: 0.5, gamma: 0, theta: 0, vega: 0,
  change: null, change_pct: null, oi_buildup: null, ...o,
});
/**
 * Seven strikes around ATM 25,000. 25Δ picks: put 24,800 (delta −0.24, IV 14.5) and call 25,200 (delta 0.26, IV 12.0)
 * → skew 14.5 − 12.0 = +2.5 pts. The other strikes sit outside the 0.15–0.35 delta band.
 */
const CHAIN = (sym: string, expiry: string, atm = 25000, step = 100) => {
  const strikes = [-3, -2, -1, 0, 1, 2, 3].map((i) => {
    const k = atm + i * step;
    const putDelta = i === -2 ? -0.24 : i < -2 ? -0.1 : -0.45 - i * 0.01;
    const callDelta = i === 2 ? 0.26 : i > 2 ? 0.1 : 0.45 - i * 0.01;
    return {
      strike: k,
      call: side({ oi: 40000 + i * 10000, delta: callDelta, iv: i === 2 ? 12.0 : 13 }),
      put: side({ oi: 90000 - i * 10000, delta: putDelta, iv: i === -2 ? 14.5 : 13 }),
    };
  });
  return {
    symbol: sym,
    summary: {
      as_of: "2026-10-23", expiry, spot: 25010, atm_strike: atm, total_call_oi: 280000, total_put_oi: 630000, total_call_oi_change: 0, total_put_oi_change: 0,
      pcr: 0.9, max_pain: 25000, max_call_oi: { strike: 25300, oi: 70000 }, max_put_oi: { strike: 24700, oi: 120000 },
      put_wall: { strike: 24700, oi: 120000 }, call_wall: { strike: 25300, oi: 70000 }, days_to_expiry: 4,
      forward: 25040, forward_basis: "future", rate_pct: 6.5, atm_iv: ATM_IV[expiry] ?? 13.8, expected_move: 300, expected_move_pct: 1.2,
    },
    strikes, strike_count: 60, lot_size: 65,
  };
};

const q = (bid: number, ask: number, age: number, stale = false) => ({ ltp: (bid + ask) / 2, bid, ask, oi: 1000, volume: 10, age_seconds: age, stale });
/**
 * Live cache, NIFTY near expiry. Fresh two-sided quotes near ATM: spreads 1%, 2%, 3%, 4% → median 2.50%.
 * One stale quote (age 30 s, excluded from the spread) and one crossed quote (bid 105 > ask 100, excluded, counted).
 * Ages [1, 2, 3, 4, 30, 2] → p95 by nearest rank = the 6th of 6 sorted = 30.0 s. stale_count 1, count 6.
 */
const LIVE_OK = {
  underlying: "NIFTY", expiry: "2026-10-27", cache: "ok", as_of: "2026-10-26T05:00:00+00:00", session: "open", cadence_seconds: 1, stale_after_seconds: 2,
  strikes: 3, count: 6, stale_count: 1, lot_size: 65,
  rows: [
    { strike: 24900, CE: q(99.5, 100.5, 1), PE: q(99, 101, 2) },
    { strike: 25000, CE: q(98.5, 101.5, 3), PE: q(98, 102, 4) },
    { strike: 25100, CE: q(50, 80, 30, true), PE: q(105, 100, 2) },
  ],
};
const LIVE_EMPTY = { ...LIVE_OK, cache: "empty", count: 0, stale_count: 0, strikes: 0, rows: [] };

interface Seen { live: string[]; futures: string[]; chains: string[] }

async function labMocks(page: Page, opts: { macro?: unknown; live?: unknown } = {}): Promise<Seen> {
  const seen: Seen = { live: [], futures: [], chains: [] };
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (route) => reply(route, []));
  await page.route("**/api/move-odds/**", (route) => reply(route, { detail: "feature_not_enabled" }, 403));
  await page.route("**/api/macro/today", (route) => reply(route, opts.macro ?? MACRO));
  await page.route(/\/api\/fno\/[A-Z&-]+\/futures/, (route) => {
    const sym = new URL(route.request().url()).pathname.split("/")[3];
    seen.futures.push(sym);
    return reply(route, FUT(sym));
  });
  await page.route(/\/api\/fno\/[A-Z&-]+\/expiries/, (route) => reply(route, EXPIRIES(new URL(route.request().url()).pathname.split("/")[3])));
  await page.route(/\/api\/fno\/[A-Z&-]+\/chain/, (route) => {
    const u = new URL(route.request().url());
    const sym = u.pathname.split("/")[3];
    const exp = u.searchParams.get("expiry") ?? "2026-10-27";
    seen.chains.push(`${sym}:${exp}`);
    return reply(route, sym === "NIFTY" ? CHAIN(sym, exp) : CHAIN(sym, exp, 2980, 20));
  });
  await page.route("**/api/live/option-chain**", (route) => {
    seen.live.push(new URL(route.request().url()).search);
    return reply(route, opts.live ?? LIVE_OK);
  });
  return seen;
}

async function noSideScroll(page: Page) {
  const o = await page.evaluate(() => {
    const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
    return { doc: document.documentElement.scrollWidth - window.innerWidth, scroll: sc ? sc.scrollWidth - sc.clientWidth : 0 };
  });
  expect(o.doc).toBeLessThanOrEqual(1);
  expect(o.scroll).toBeLessThanOrEqual(1);
}

const TABS = ["mi", "prog", "replay", "shadow", "live", "cert", "audit"] as const;
const TAB_LABELS = ["Market Intelligence", "Strategy Programs", "Historical Replay Lab", "Shadow Mode Monitor", "Live Trading Desk", "Agent Certification Center", "Audit & Decision Replay"];
const MODE: Record<(typeof TABS)[number], string> = { mi: "research", prog: "governance", replay: "research", shadow: "shadow", live: "live-disabled", cert: "governance", audit: "research" };

test.describe("MOCK — not real data: F&O lab shell and Market Intelligence", () => {
  test("S-1 seven tabs in order; Market Intelligence is selected by default", async ({ page }) => {
    await labMocks(page);
    await page.goto(LAB);
    await expect(page.getByTestId("screen-tool-fnolab")).toBeVisible();
    const tabs = page.getByRole("tab");
    await expect(tabs).toHaveText(TAB_LABELS);
    await expect(page.getByTestId("fnolab-tab-mi")).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("fnolab-screen-mi")).toBeVisible();
  });

  test("S-2 ?screen=audit opens Audit; a tab click moves the URL to screen=shadow", async ({ page }) => {
    await labMocks(page);
    await page.goto(`${LAB}?screen=audit`);
    await expect(page.getByTestId("fnolab-tab-audit")).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("fnolab-screen-audit")).toBeVisible();
    await page.getByTestId("fnolab-tab-shadow").click();
    await expect(page).toHaveURL(/[?&]screen=shadow/);
    await expect(page.getByTestId("fnolab-screen-shadow")).toBeVisible();
  });

  test("S-3 S-6 S-7 every screen: its mode strip, source cards, the SEBI note and no illustrative numbers", async ({ page }) => {
    await labMocks(page);
    for (const id of TABS) {
      await page.goto(`${LAB}?screen=${id}`);
      await expect(page.getByTestId("fnolab-mode")).toHaveAttribute("data-mode", MODE[id]);
      await expect(page.getByTestId("fnolab-sources").first()).toBeVisible();
      await expect(page.getByTestId("fnolab-sebi")).toContainText("9 out of 10 individual traders");
      await expect(page.getByTestId("fnolab-sebi")).toContainText("Nivesh places no orders");
      await expect(page.getByText(/illustrative/i)).toHaveCount(0);
    }
    await page.goto(`${LAB}?screen=live`);
    await expect(page.getByTestId("fnolab-mode")).toContainText("No order path exists in this build");
  });

  test("S-5 at 390 px the page does not scroll sideways and every tab stays reachable", async ({ page }) => {
    await labMocks(page);
    await page.setViewportSize({ width: 390, height: 844 });
    for (const id of TABS) {
      await page.goto(`${LAB}?screen=${id}`);
      await expect(page.getByTestId(`fnolab-screen-${id}`)).toBeVisible();
      await noSideScroll(page);
    }
    await page.goto(LAB);
    await page.getByTestId("fnolab-tab-audit").scrollIntoViewIfNeeded();
    await page.getByTestId("fnolab-tab-audit").click();
    await expect(page.getByTestId("fnolab-screen-audit")).toBeVisible();
  });

  test("MI-2 the regime: label, rule version, inputs in words, what would change it; not VIX alone", async ({ page }) => {
    await labMocks(page);
    await page.goto(LAB);
    const r = page.getByTestId("fnolab-mi-regime");
    await expect(r).toHaveAttribute("data-key", "sideways");
    await expect(r).toContainText("Sideways");
    await expect(r).toContainText("same for every underlying");
    await expect(r).toContainText("checks India VIX first, then whether trend and breadth disagree");
    const f = page.getByTestId("fnolab-mi-factors");
    await expect(f).toContainText("India VIX 12.30 against the 20 threshold");
    await expect(f).toContainText("49.0% advancing (240 up, 250 down of 500)");
    await expect(f).toContainText("Not computed: there is no IV history (P0.2)");
    await expect(page.getByTestId("fnolab-mi-flips")).toContainText("India VIX at or above 20.0 → High volatility");
    await expect(page.getByTestId("fnolab-mi-regime-trust")).toContainText("desk-regime-v1");
    // Source card: regime is real and dated.
    await expect(page.getByTestId("fnolab-source").filter({ hasText: "Regime" })).toHaveAttribute("data-tone", "mint");
  });

  test("MI-2 no regime from the route → 'Regime not available' with the route's reason, nothing invented", async ({ page }) => {
    await labMocks(page, { macro: MACRO_NONE });
    await page.goto(LAB);
    const none = page.getByTestId("fnolab-mi-regime-none");
    await expect(none).toContainText("Regime not available");
    await expect(none).toContainText("the macro state is not computed yet");
    await expect(page.getByTestId("fnolab-mi-regime")).toHaveCount(0);
    await expect(page.getByTestId("fnolab-source").filter({ hasText: "Regime" })).toHaveAttribute("data-tone", "danger");
  });

  test("MI-3 build-up: one row per expiry in date order, OI change worked from the contract, '—' for a missing change, disagreement said", async ({ page }) => {
    await labMocks(page);
    await page.goto(LAB);
    const rows = page.getByTestId("fnolab-mi-buildup-row");
    await expect(rows).toHaveCount(3);
    await expect(rows.nth(0)).toContainText("27 Oct 2026");
    await expect(rows.nth(0)).toContainText("−0.42%");
    await expect(rows.nth(0)).toContainText("+10.0%");
    await expect(rows.nth(0)).toHaveAttribute("data-label", "short build-up");
    await expect(rows.nth(1)).toContainText("+6.0%");
    await expect(rows.nth(2)).toContainText("+2.0%");
    await expect(rows.nth(2)).toHaveAttribute("data-label", "long unwinding");
    // The Dec contract has no price change: a dash, never 0.
    await expect(rows.nth(2).locator("td").nth(2)).toHaveText("—");
    await expect(page.getByTestId("screen-tool-fnolab")).toContainText("The expiries disagree");
  });

  test("MI-4 MI-7 options: OI by strike, PCR, max pain, skew, term structure per expiry, IV rank unavailable, the model's own rate", async ({ page }) => {
    const seen = await labMocks(page);
    await page.goto(LAB);
    await expect(page.getByTestId("fnolab-mi-strikes")).toContainText("25,000");
    await expect(page.getByTestId("fnolab-mi-strikes")).toContainText("Max pain 25,000");
    await expect(page.getByTestId("screen-tool-fnolab")).toContainText("PCR 0.90");
    const vol = page.getByTestId("fnolab-mi-vol");
    await expect(vol).toContainText("24,700 · 25,300");
    await expect(vol).toContainText("+2.5 pts · put 24,800 vs call 25,200");
    await expect(page.getByTestId("fnolab-mi-ivrank")).toHaveText("Unavailable · no IV history (P0.2)");
    const term = page.getByTestId("fnolab-mi-term-row");
    await expect(term).toHaveCount(3);
    await expect(term.nth(0)).toContainText("13.8%");
    await expect(term.nth(1)).toContainText("14.6%");
    await expect(term.nth(2)).toContainText("15.1%");
    expect(seen.chains).toEqual(expect.arrayContaining(["NIFTY:2026-11-24", "NIFTY:2026-12-29"]));
    // The rate comes from the response (6.5), not a constant in the screen.
    await expect(page.getByTestId("fnolab-mi-greeks-src")).toContainText("at a 6.50% rate");
    await expect(page.getByTestId("fnolab-mi-greeks-src")).toContainText("end-of-day settle prices");
  });

  test("MI-5 quote quality from the live cache: median spread, p95 age, stale, crossed, count", async ({ page }) => {
    const seen = await labMocks(page);
    await page.goto(LAB);
    const qp = page.getByTestId("fnolab-mi-quotes");
    await expect(qp).toContainText("2.50%");
    await expect(qp).toContainText("4 fresh two-sided quotes");
    await expect(qp).toContainText("30.0 s");
    await expect(qp).toContainText("1 of 6");
    await expect(qp).toContainText("Older than 2 s");
    expect(seen.live.some((s) => s.includes("underlying=NIFTY") && s.includes("expiry=2026-10-27"))).toBe(true);
    await expect(page.getByTestId("fnolab-source").filter({ hasText: "Bid / ask quotes" })).toContainText("Kite feed · 6 contracts · 1 stale");
  });

  test("MI-5 an empty cache says so and shows no tiles", async ({ page }) => {
    await labMocks(page, { live: LIVE_EMPTY });
    await page.goto(LAB);
    await expect(page.getByTestId("fnolab-mi-quotes-empty")).toHaveAttribute("data-cache", "empty");
    await expect(page.getByTestId("fnolab-mi-quotes-empty")).toContainText("No live option quotes cached");
    await expect(page.getByTestId("fnolab-mi-quotes")).toHaveCount(0);
  });

  test("MI-1 MI-6 RELIANCE: its own futures and chain, no live-cache request, and the off-feed gap note", async ({ page }) => {
    const seen = await labMocks(page);
    await page.goto(LAB);
    await expect(page.getByTestId("fnolab-mi-quotes")).toBeVisible();
    const liveBefore = seen.live.length;
    await page.getByTestId("fnolab-mi-u-RELIANCE").click();
    await expect(page.getByTestId("fnolab-mi-u-RELIANCE")).toHaveAttribute("aria-checked", "true");
    await expect(page.getByTestId("fnolab-mi-quotes-gap")).toHaveAttribute("data-tag", "P0.1");
    await expect(page.getByTestId("fnolab-mi-quotes-gap")).toContainText("Stock options are not on the live feed");
    await expect(page.getByTestId("fnolab-mi-strikes")).toContainText("2,980");
    expect(seen.futures).toContain("RELIANCE");
    expect(seen.chains.some((c) => c.startsWith("RELIANCE:"))).toBe(true);
    expect(seen.live.slice(liveBefore).some((s) => s.includes("RELIANCE"))).toBe(false);
    await expect(page.getByTestId("fnolab-source").filter({ hasText: "Bid / ask quotes" })).toHaveAttribute("data-tone", "danger");
  });
});
