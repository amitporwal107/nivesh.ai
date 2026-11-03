/**
 * Compliance wording guard for the Trading Desk (owner, 3 Nov 2026: "Please check compliance and do not use words like
 * buy, stop loss, target"). Nivesh is not a SEBI-registered Research Analyst, so no text on the desk may read like a trading
 * call. Approved vocabulary: Buy / Sell → Long / Short; Stop loss / SL / stop → Risk level; Target / T1 / T2 → Reward level;
 * Entry → Reference price; never pick / recommend / suggested trade ("ideas", "fits", "ordered for review").
 * Test case TC-6 of test_reports/compliance_wording_TESTCASES.md.
 *
 * Every desk place (section / view / sub-view of screens/tradingdesk/desk-nav.ts) is rendered with mocked API data and its
 * visible text plus its aria-label / title / placeholder attributes are linted for the banned words. The mocks carry only
 * numbers, dates and codes (MOCK — not real data), so what is linted is the desk's OWN wording, not a captured backend
 * sentence; the backend's strings have their own lint (backend/tests/test_compliance_wording_lint.py).
 */
import { test, expect, type Page } from "@playwright/test";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const DESK = "/v5/app/trader/desk";

// The banned words (the backend lint's list). Bullish / bearish are the user's own chosen market view on the desk (an
// input, not a verdict) and are listed for the owner rather than linted here.
const LINT = new RegExp(
  "\\b(buy|buys|buying|bought|sell|sells|selling|sold|stop[- ]?loss(?:es)?|sl|stops?|targets?|t1|t2|entry|entries|exit|exits|" +
    "exited|book(?:ing)?\\s+profits?|profit[- ]booking|accumulate|trim|upside|downside|recommend\\w*|picks?|price\\s+targets?|" +
    "suggested\\s+(?:trade|trades|strateg(?:y|ies)))\\b",
  "gi",
);
// Non-trading senses, removed before the lint. Each is a fixed term or a UI control, not a call.
const ALLOW = [
  /\bexit\s+load\b/gi,                                   // a mutual-fund fee
  /\b(?:long|short)\s+build[- ]?ups?\b/gi,               // F&O open-interest categories
  /\bstop\s+(?:the\s+answer|generating)\b/gi,            // chat controls
  /\b(?:you\s+)?stopped\s+this\s+answer\b/gi,
  /\bupdates\s+stopped\b/gi,
];

function hits(text: string): string[] {
  let t = text;
  for (const a of ALLOW) t = t.replace(a, " ");
  return [...t.matchAll(LINT)].map((m) => m[0]);
}

/** Visible text and the attributes a screen reader or a tooltip shows. */
async function shownText(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const out = [document.body.innerText];
    for (const el of Array.from(document.querySelectorAll("[aria-label],[title],[placeholder]"))) {
      for (const a of ["aria-label", "title", "placeholder"]) {
        const v = el.getAttribute(a);
        if (v) out.push(v);
      }
    }
    return out.join("\n").split("\n").map((s) => s.trim()).filter(Boolean);
  });
}

async function lintPlace(page: Page, query: string): Promise<{ place: string; line: string; words: string[] }[]> {
  await page.goto(`${DESK}?${query}`);
  await expect(page.locator('[role="tabpanel"][data-testid^="desk-panel-"]').first()).toBeVisible({ timeout: 15000 });
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(400);                                       // lazy panels settle
  return (await shownText(page)).flatMap((line) => {
    const w = hits(line);
    return w.length ? [{ place: query, line: line.slice(0, 160), words: w }] : [];
  });
}

// MOCK — not real data: numbers and codes only, in the shapes of backend/routes/positional.py and research_chart_live.py.
const DAY = "2026-10-30";
const row = (sym: string, close: number, trigger: number | null, stop: number) => ({
  nse_symbol: sym, sector: "Capital Goods", stage: "BREAKOUT", confidence: "HIGH", final_score: 0.79, close_price: close,
  trigger_price: trigger, stop_price: stop, atr_pct: 2.9, rsi_14: 64.2, sma_50: close * 0.92, sma_200: close * 0.85, ema_20: close * 0.97,
  signals: { range_pct_15d: 9.1, volume_slope_10d_pct: 2.1, volume_spike_3v20: 1.8, higher_lows_count: 2, upper_wick_pct: 0.2,
    delivery_trend_pct: 4.0, dist_breakout_pct: 2.0, dist_ema20_pct: 3.6 },
  why: "MOCK", resistance_level: close * 1.04, support_level: close * 0.96, spark_closes: [], spark_end: null, avg_traded_value_cr_20d: 42.6,
});
const WATCHLIST = {
  as_of_date: DAY, is_weekend_mode: false, is_weekend: false, days_stale: 1, total_count: 2,
  bucket_counts: { breakout_confirmed: 1, pre_breakout: 1, true_accumulation: 0, trend_continuation: 0 },
  buckets: { breakout_confirmed: [row("FIXBRK", 510, 500, 477.5)], pre_breakout: [row("FIXPRE", 245, 250, 238)], true_accumulation: [], trend_continuation: [] },
};
const PICKS = {
  as_of_date: DAY, count: 1, picks: [{ nse_symbol: "FIXBRK", signal_date: DAY, final_score: 0.81, confidence: "HIGH", stage: "BREAKOUT",
    timeframe_days_min: 5, timeframe_days_max: 20, entry_price: 512, stoploss: 478, target_price: 580, risk_reward: 2.0, sector: "Capital Goods" }],
};
function bars(n = 140) {
  const out: [string, number, number, number, number, number][] = [];
  const t0 = Date.UTC(2026, 4, 1);
  for (let i = 0; i < n; i++) {
    const d = new Date(t0 + i * 86400000).toISOString().slice(0, 10);
    const c = 480 + 20 * Math.sin(i / 7) + 0.2 * i;
    out.push([d, c - 1, c + 3, c - 3, c, 100000 + i * 10]);
  }
  return out;
}
const json = (page: Page, url: string, body: unknown) =>
  page.route(url, (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) }));

async function deskMocks(page: Page) {
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await json(page, "**/api/chat/sessions", []);
  await json(page, "**/api/positional/watchlist*", WATCHLIST);
  await json(page, "**/api/positional/picks*", PICKS);
  const b = bars();
  await page.route("**/api/research/chart-live/*/ohlcv*", (r) => {
    const symbol = new URL(r.request().url()).pathname.split("/").slice(-2)[0];
    return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      symbol, timeframe: "1D", bars: b, data_quality_status: "VALID", pit_status: "PIT_UNVERIFIED", findings: [],
      provenance: { provider: "nidp.prices_eod_adjusted", series: "EQ", adjustment_status: "SPLIT_BONUS_ADJUSTED", last_bar_date: b[b.length - 1][0], source_mode: "live", last_event_type: null } }) });
  });
}

// Every place of desk-nav.ts SECTION_VIEWS / SUB_VIEWS, plus My portfolio.
// Not here: tab=market&view=recovery (Market Recovery, flag market_recovery). The owner chose the standard plan words for that
// view (3 Nov: "Entry zone · Stop loss · Target 1 / Target 2"), so copilot-app-market-recovery.spec.ts TC-E5 lints it with this
// same list, removing exactly those four labels and nothing else.
const PLACES = [
  "tab=overview",
  "tab=trade&view=scanner&sub=ranked", "tab=trade&view=scanner&sub=library", "tab=trade&view=scanner&sub=scorecard",
  "tab=trade&view=chart&sub=live&sym=FIXBRK", "tab=trade&view=chart&sub=record&sym=FIXBRK",
  "tab=trade&view=paper&sub=live", "tab=trade&view=paper&sub=journal", "tab=trade&view=watchlists",
  "tab=market&view=intel", "tab=market&view=smartmoney", "tab=market&view=sectors", "tab=market&view=research",
  "tab=risk&view=limits", "tab=risk&view=controls", "tab=risk&view=log", "tab=risk&view=hedge",
  "tab=portfolio",
];

test.describe("Compliance wording — the Trading Desk shows no trading-call words (owner, 3 Nov 2026)", () => {
  test.setTimeout(240000);

  test("CW-1 the lint itself: the old labels fail it and the approved vocabulary passes", () => {
    for (const old of ["Stop", "Target 1", "Entry", "LOSS AT STOP", "Buy 1 NIFTY 24000 CE", "Exit if wrong", "Book profits", "T1", "Top picks",
                       "not a recommendation", "Upside a share", "a sell signal"]) {
      expect(hits(old), old).not.toEqual([]);
    }
    for (const ok of ["Risk level", "Reward level 1", "Reference price", "LOSS AT RISK LEVEL", "Long 1 NIFTY 24000 CE", "Short 1 NIFTY 24200 PE",
                      "Close rule", "Top 10 ideas", "not advice", "Long build-up", "exit load", "Stop the answer", "Suggested questions"]) {
      expect(hits(ok), ok).toEqual([]);
    }
  });

  test("CW-2 every desk place, rendered with mocked data, has no banned word in its text, labels or tooltips", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await deskMocks(page);
    const found: { place: string; line: string; words: string[] }[] = [];
    for (const q of PLACES) found.push(...(await lintPlace(page, q)));
    expect(found, JSON.stringify(found, null, 1)).toEqual([]);
  });

  test("CW-3 the AI Scanner with ranked rows (levels, reward column) says reference price / risk level / reward level", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await deskMocks(page);
    await page.goto(`${DESK}?tab=trade&view=scanner&sub=ranked`);
    await expect(page.getByTestId("desk-scan-row-FIXBRK")).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId("desk-scan-row-FIXPRE")).toBeVisible();
    await expect(page.getByTestId("desk-scan-footnote")).toContainText("Reference price, risk level and reward level are hypothetical");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(400);
    const found = (await shownText(page)).flatMap((line) => (hits(line).length ? [{ line: line.slice(0, 160), words: hits(line) }] : []));
    expect(found, JSON.stringify(found, null, 1)).toEqual([]);
  });
});
