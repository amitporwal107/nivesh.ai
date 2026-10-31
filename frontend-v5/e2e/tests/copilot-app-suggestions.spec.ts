/**
 * One-screen Copilot app (/v5/app) — the Home suggestion tabs (components/SuggestionsPanel.tsx, GET /api/suggestions):
 * SG-U1 … SG-U18 of test_reports/dtc_r3_suggestions_20261031.md.
 *
 * Market and F&O Lab tabs: `e2e/fixtures/contract-suggestions.json`, the REAL staging capture of those tabs (market
 * data, the same for every user). For you and My trades read one user's own portfolio and trades, so their cards below
 * are MOCK — not real data, shaped like the same route's response. Every other route is an inline MOCK in the real
 * route's shape; the feedback, refresh and why routes check the request body the backend's pydantic models accept
 * (backend/tests/test_suggestions.py SG-R3 / SG-R4). Mocked APIs, production build (pw.copilot-app.config.ts).
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REAL = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", "contract-suggestions.json"), "utf-8"));
type View = Record<string, any>;
const APP = "/v5/app";
const SLOW = { timeout: 15_000 };
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const sse = (frames: Array<Record<string, unknown>>) => frames.map((f) => `data: ${JSON.stringify(f)}\n\n`).join("");
const BANNED = /\b(buy now|strong buy|recommend\w*|pick\w*)\b/i;

const WINDOW = { today: "2026-10-31", previous_session: "2026-10-30" };
const TABS = (counts: Record<string, number>) => ["for_you", "market", "my_trades", "fno_lab"].map((key) => ({
  key, label: { for_you: "For you", market: "Market", my_trades: "My trades", fno_lab: "F&O Lab" }[key], count: counts[key] ?? 0 }));

// MOCK — not real data: one user's own cards.
const card = (o: Record<string, any>) => ({
  tab: "for_you", class: "informational", class_label: "To explore", footer: "A question to explore with the latest data. Not advice.",
  intent: null, template_id: "t_x", symbol: null, as_of: "2026-10-30", state: "active",
  inputs: [{ name: "holdings", label: "Your holdings", as_of: "2026-10-30T12:00:00+00:00", status: "fresh" }], ...o });
const MOCK_FOR_YOU = [
  card({ id: "sg_mock_pnb", rule_id: "watchlist_on_scanner", class: "validated_signal", class_label: "Rule-based signal", symbol: "PNB", intent: "stock_decision",
    title: "PNB from your watchlist is on today's scanner list", why: "Rank 1 of the AI scanner's list of 30 Oct 2026; desk status: setup ready.",
    query: "What's the setup for PNB?", footer: "Met a scanner rule on 30 Oct 2026. An idea to review with its evidence, not advice." }),
  card({ id: "sg_mock_sector", rule_id: "sector_concentration", title: "Analyse sector exposure",
    why: "Information Technology is 32.1% of your holdings, above the 25% ceiling the portfolio checks use.",
    query: "Show the sector concentration and overlapping holdings in my portfolio" }),
];
const MOCK_MY_TRADES = [
  card({ id: "sg_mock_stop", tab: "my_trades", rule_id: "near_stop", class: "risk_alert", class_label: "Risk check", symbol: "SONACOMS", intent: "exit_options",
    title: "SONACOMS is near its stop-loss", why: "Last close ₹834.00 on 30 Oct 2026; stop ₹824.60, 1.13% away.", query: "Should I book profits or hold SONACOMS?",
    footer: "About your own trade's levels and limits. It does not tell you to exit or hold." }),
];

function view(tab: string, suggestions: any[], notices: any[] = [], mode = "investor", counts?: Record<string, number>): View {
  return { schema: "suggestions-v1", tab, mode, generated_at: "2026-10-31T00:20:00+00:00", window: WINDOW,
    tabs: TABS(counts ?? { for_you: MOCK_FOR_YOU.length, market: REAL.tabs.market.suggestions.length, my_trades: MOCK_MY_TRADES.length, fno_lab: REAL.tabs.fno_lab.suggestions.length, [tab]: suggestions.length }),
    suggestions, notices };
}
const DEFAULT: Record<string, View> = {
  for_you: view("for_you", MOCK_FOR_YOU), market: { ...REAL.tabs.market, mode: "investor", tabs: view("market", []).tabs.map((t) => ({ ...t, count: t.key === "market" ? 5 : t.key === "fno_lab" ? 5 : t.count })) },
  my_trades: view("my_trades", MOCK_MY_TRADES), fno_lab: { ...REAL.tabs.fno_lab, mode: "investor" },
};

interface Seen { lists: string[]; refresh: any[]; feedback: Array<{ id: string; body: any }>; why: string[]; streams: any[] }

async function setup(page: Page, opts: { mode?: "trader" | "investor"; width?: number; views?: Record<string, View>; failList?: boolean; failFeedback?: boolean;
  why?: any } = {}): Promise<Seen> {
  const seen: Seen = { lists: [], refresh: [], feedback: [], why: [], streams: [] };
  await page.setViewportSize({ width: opts.width ?? 1280, height: 900 });
  if (opts.mode) {
    await page.addInitScript((m) => {
      try { localStorage.setItem("nivesh.copilot", JSON.stringify({ state: { mode: m, evidenceOpen: false }, version: 0 })); } catch { /* storage blocked */ }
    }, opts.mode);
  }
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  const views = { ...DEFAULT, ...(opts.views ?? {}) };
  await page.route(/\/api\/suggestions(\?.*)?$/, (r) => {
    const u = new URL(r.request().url());
    const tab = u.searchParams.get("tab") ?? "for_you";
    seen.lists.push(`${tab}|${u.searchParams.get("mode")}`);
    if (opts.failList) return json(r, { detail: "boom" }, 500);
    return json(r, { ...views[tab], mode: u.searchParams.get("mode") });
  });
  await page.route("**/api/suggestions/refresh", (r) => {
    const body = r.request().postDataJSON();
    seen.refresh.push(body);
    const fresh = JSON.parse(JSON.stringify(views[body.tab]));
    fresh.generated_at = "2026-10-31T00:25:00+00:00";
    fresh.suggestions = [{ ...fresh.suggestions[0], id: "sg_refreshed", title: "Refreshed card (MOCK)" }, ...fresh.suggestions.slice(1)];
    return json(r, fresh);
  });
  await page.route(/\/api\/suggestions\/[^/]+\/feedback$/, (r) => {
    const id = decodeURIComponent(new URL(r.request().url()).pathname.split("/").slice(-2)[0]);
    seen.feedback.push({ id, body: r.request().postDataJSON() });
    if (opts.failFeedback) return json(r, { detail: "boom" }, 500);
    return json(r, { id, action: r.request().postDataJSON().action, state: "dismissed", at: "2026-10-31T00:30:00+00:00" });
  });
  await page.route(/\/api\/suggestions\/[^/]+\/why$/, (r) => {
    const id = decodeURIComponent(new URL(r.request().url()).pathname.split("/").slice(-2)[0]);
    seen.why.push(id);
    return json(r, opts.why ?? { id, title: "Where smart money is moving", why: "x", class: "informational", class_label: "To explore", footer: null,
      query: "Where is smart money moving?", intent: "smart_money", template_id: "t_smart_money",
      rule: { id: "smart_money_daily", name: "Daily smart-money flows", description: "Shown when NSE's FII/DII cash figures are today's or the previous session's.",
        trigger: "source_current", params: {}, freshness: { kind: "session" }, cooldown_hours: 20 },
      inputs: [{ name: "fii_dii", label: "NSE FII/DII cash flows", as_of: "2026-10-30", status: "fresh" }], as_of: "2026-10-30",
      evaluated_at: "2026-10-31T00:20:00+00:00", first_seen_at: "2026-10-31T00:20:00+00:00", state: "active" });
  });
  await page.route("**/api/chat/sessions", (r) => (r.request().method() === "POST" ? json(r, { session_id: "sg1", id: "sg1" }) : json(r, [])));
  await page.route("**/api/chat/messages*", (r) => json(r, []));
  await page.route("**/api/chat/suggest-queries*", (r) => json(r, { suggestions: [] }));
  await page.route("**/api/chat/stream", (r) => {
    seen.streams.push(r.request().postDataJSON());
    return r.fulfill({ status: 200, contentType: "text/event-stream", body: sse([
      { type: "meta", session_id: "sg1", ai_msg_id: "a1", user_msg_id: "u1" }, { type: "token", content: "MOCK answer." }, { type: "done", content: "MOCK answer.", follow_ups: [] }]) });
  });
  await page.goto(APP);
  return seen;
}

const panel = (page: Page) => page.getByTestId("sg-panel");
const cards = (page: Page) => page.getByTestId("sg-card");

test.describe("Home suggestions (market and F&O tabs: REAL staging capture; personal cards: MOCK — not real data)", () => {
  for (const [hour, word] of [[9, "Good morning"], [14, "Good afternoon"], [20, "Good evening"]] as const) {
    test(`SG-U1 greeting at ${hour}:00 — "${word}! What would you like to explore?" and the owner's line`, async ({ page }) => {
      await page.clock.setFixedTime(new Date(2026, 9, 31, hour, 0, 0));
      await setup(page);
      await expect(page.getByTestId("sg-greeting")).toHaveText(`${word}! What would you like to explore?`, SLOW);
      await expect(panel(page)).toContainText("Your suggestions update based on your connected portfolio and the latest available market data.");
      await expect(page.getByTestId("home-headline")).toBeVisible();            // the screen's own headline is unchanged
    });
  }

  test("SG-U2 four tabs in the owner's order, For you first; each tab asks the backend for its own list", async ({ page }) => {
    const seen = await setup(page);
    const tabs = panel(page).getByRole("tab");
    await expect(tabs).toHaveText([/^For you\s*2$/, /^Market\s*5$/, /^My trades\s*1$/, /^F&O Lab\s*5$/], SLOW);
    await expect(page.getByTestId("sg-tab-for_you")).toHaveAttribute("aria-selected", "true");
    await expect(cards(page)).toHaveCount(2);
    for (const k of ["market", "my_trades", "fno_lab"]) {
      await page.getByTestId(`sg-tab-${k}`).click();
      await expect(page.getByTestId(`sg-tab-${k}`)).toHaveAttribute("aria-selected", "true");
      await expect(panel(page)).toHaveAttribute("data-tab", k);
    }
    expect(seen.lists).toEqual(["for_you|investor", "market|investor", "my_trades|investor", "fno_lab|investor"]);
  });

  test("SG-U3 the Market tab shows the real captured cards: title, the why line with its date, class, footer", async ({ page }) => {
    await setup(page);
    await page.getByTestId("sg-tab-market").click();
    const real = REAL.tabs.market.suggestions;
    await expect(cards(page)).toHaveCount(real.length, SLOW);
    for (let i = 0; i < real.length; i++) {
      const c = cards(page).nth(i);
      await expect(c.getByTestId("sg-title")).toHaveText(real[i].title);
      await expect(c.getByTestId("sg-why-line")).toHaveText(real[i].why);
      await expect(c.getByTestId("sg-class")).toHaveText(real[i].class_label);
      await expect(c.getByTestId("sg-footer")).toHaveText(real[i].footer);
      await expect(c).toHaveAttribute("data-class", real[i].class);
    }
    await expect(page.getByTestId("sg-asof")).toContainText("Latest market data: 30 Oct 2026 or today (31 Oct 2026)");
  });

  test("SG-U4 a click asks the card's question (the same one the visual answer opens)", async ({ page }) => {
    const seen = await setup(page);
    await page.getByTestId("sg-tab-market").click();
    const real = REAL.tabs.market.suggestions;
    const i = real.findIndex((s: any) => s.rule_id === "smart_money_daily");
    await cards(page).nth(i).getByTestId("sg-ask").click();
    await expect.poll(() => seen.streams.map((s) => s.message), SLOW).toEqual([real[i].query]);
    expect(real[i].query).toBe("Where is smart money moving?");
  });

  test("SG-U5 the three classes look different: validated signal, risk check, to explore", async ({ page }) => {
    await setup(page);
    const sig = cards(page).filter({ has: page.locator('[data-testid="sg-class"]', { hasText: "Rule-based signal" }) });
    await expect(sig).toHaveCount(1);
    await expect(sig).toHaveAttribute("data-class", "validated_signal");
    await expect(sig.getByTestId("sg-footer")).toHaveText("Met a scanner rule on 30 Oct 2026. An idea to review with its evidence, not advice.");
    await page.getByTestId("sg-tab-my_trades").click();
    const risk = cards(page).first();
    await expect(risk).toHaveAttribute("data-class", "risk_alert");
    await expect(risk.getByTestId("sg-class")).toHaveText("Risk check");
    await expect(risk.getByTestId("sg-footer")).toHaveText("About your own trade's levels and limits. It does not tell you to exit or hold.");
    const left = (el: any) => el.evaluate((n: HTMLElement) => getComputedStyle(n).borderLeftWidth);
    expect(await left(risk)).toBe("3px");
    await page.getByTestId("sg-tab-for_you").click();
    expect(await left(cards(page).filter({ hasText: "PNB from your watchlist" }))).toBe("3px");
    expect(await left(cards(page).filter({ hasText: "Analyse sector exposure" }))).toBe("1px");                        // the plain card border: no accent bar
  });

  test("SG-U6 a stock's card carries its icon beside the name", async ({ page }) => {
    await setup(page);
    const sig = cards(page).filter({ hasText: "PNB from your watchlist" });
    await expect(sig.getByTestId("entity-icon")).toHaveCount(1);
    await expect(cards(page).filter({ hasText: "Analyse sector exposure" }).getByTestId("entity-icon")).toHaveCount(0);
  });

  test("SG-U7 dismiss sends {action: dismissed}, removes the card and lowers the tab's count", async ({ page }) => {
    const seen = await setup(page);
    await expect(cards(page)).toHaveCount(2, SLOW);
    await cards(page).first().getByTestId("sg-dismiss").click();
    await expect(cards(page)).toHaveCount(1);
    await expect(page.getByTestId("sg-tab-for_you")).toHaveText(/^For you\s*1$/);
    expect(seen.feedback).toEqual([{ id: "sg_mock_pnb", body: { action: "dismissed" } }]);
  });

  test("SG-U8 Not relevant removes the card; Useful keeps it and says Noted", async ({ page }) => {
    const seen = await setup(page);
    await cards(page).nth(1).getByTestId("sg-useful").click();
    await expect(cards(page).nth(1).getByTestId("sg-thanks")).toHaveText("Noted");
    await expect(cards(page)).toHaveCount(2);
    await cards(page).first().getByTestId("sg-not-relevant").click();
    await expect(cards(page)).toHaveCount(1);
    expect(seen.feedback).toEqual([{ id: "sg_mock_sector", body: { action: "useful" } }, { id: "sg_mock_pnb", body: { action: "not_relevant" } }]);
  });

  test("SG-U9 a feedback call that fails says so and the card stays", async ({ page }) => {
    await setup(page, { failFeedback: true });
    await cards(page).first().getByTestId("sg-dismiss").click();
    await expect(page.getByTestId("sg-feedback-error")).toHaveText("That could not be saved just now. Try again.");
    await expect(cards(page)).toHaveCount(2);
  });

  test("SG-U10 Refresh posts {tab, mode} and shows the new list", async ({ page }) => {
    const seen = await setup(page, { mode: "trader" });
    await page.getByTestId("sg-tab-fno_lab").click();
    await page.getByTestId("sg-refresh").click();
    await expect(cards(page).first().getByTestId("sg-title")).toHaveText("Refreshed card (MOCK)", SLOW);
    expect(seen.refresh).toEqual([{ tab: "fno_lab", mode: "trader" }]);
  });

  test("SG-U11 'Why am I seeing this?' shows the rule, the data used with its date, and the cooldown", async ({ page }) => {
    const seen = await setup(page);
    await page.getByTestId("sg-tab-market").click();
    const c = cards(page).nth(REAL.tabs.market.suggestions.findIndex((s: any) => s.rule_id === "smart_money_daily"));
    await c.getByTestId("sg-why-toggle").click();
    await expect(c.getByTestId("sg-why-rule")).toHaveText("Daily smart-money flows", SLOW);
    await expect(c.getByTestId("sg-why-input")).toHaveText(["NSE FII/DII cash flows · as of 30 Oct 2026 · fresh"]);
    await expect(c.getByTestId("sg-why")).toContainText("Not shown again for 20 hours after you dismiss it.");
    expect(seen.why).toEqual([REAL.tabs.market.suggestions.find((s: any) => s.rule_id === "smart_money_daily").id]);
    await c.getByTestId("sg-why-toggle").click();
    await expect(c.getByTestId("sg-why")).toHaveCount(0);
  });

  test("SG-U12 a stale source: the notice says which source and why, and its tab has no card from it", async ({ page }) => {
    const text = "Prices stale: your paper trades are marked at the close of 27 Oct 2026, older than the previous session (30 Oct 2026). No trade alert is shown until the marks are current.";
    await setup(page, { views: { my_trades: view("my_trades", [], [{ kind: "stale", source: "Your paper trades", as_of: "2026-10-27", text }]) } });
    await page.getByTestId("sg-tab-my_trades").click();
    await expect(page.getByTestId("sg-notice")).toHaveText(text, SLOW);
    await expect(page.getByTestId("sg-notice")).toHaveAttribute("data-kind", "stale");
    await expect(cards(page)).toHaveCount(0);
    await expect(page.getByTestId("sg-empty")).toContainText("Nothing to suggest in My trades right now, for the reason above.");
  });

  test("SG-U13 no portfolio: a Connect notice that opens onboarding, and no personal figure", async ({ page }) => {
    const n = { kind: "no_portfolio", source: "Your holdings", as_of: null, text: "Connect or import a portfolio to get suggestions about your holdings.", action: "connect" };
    await setup(page, { views: { for_you: view("for_you", [card({ id: "sg_mock_opp", rule_id: "opportunities_daily", title: "Find today's opportunities",
      why: "The AI scanner's list of 30 Oct 2026: 3 of the top 5 have a setup with levels.", query: "Which are today's top 5 opportunities?", intent: "top_opportunities" })], [n]) } });
    await expect(page.getByTestId("sg-notice")).toContainText(n.text);
    await expect(cards(page)).toHaveCount(1);
    await expect(panel(page)).not.toContainText(/Equity \d+%|Debt \d+%/);
    await page.getByTestId("sg-notice-action").click();
    await expect(page).toHaveURL(/\/v5\/app\/onboarding$/);
  });

  test("SG-U14 a disconnected broker: said in words, with Reconnect to the brokers page", async ({ page }) => {
    const n = { kind: "disconnected", source: "Zerodha connection", as_of: "2026-10-28", action: "brokers",
      text: "Broker disconnected: your Zerodha connection has ended, so its holdings are as of the last sync on 28 Oct 2026. Reconnect to refresh them." };
    await setup(page, { views: { for_you: view("for_you", MOCK_FOR_YOU, [n]) } });
    await expect(page.getByTestId("sg-notice")).toContainText("Broker disconnected: your Zerodha connection has ended");
    await page.getByTestId("sg-notice-action").click();
    await expect(page).toHaveURL(/\/v5\/app\/page\/brokers$/);
  });

  test("SG-U15 the backend failing is an error with Try again, never an empty list that looks fine", async ({ page }) => {
    await setup(page, { failList: true });
    await expect(page.getByTestId("sg-error")).toContainText("Suggestions are not available just now.", SLOW);
    await expect(cards(page)).toHaveCount(0);
    await expect(page.getByTestId("home-headline")).toBeVisible();             // the rest of Home is unaffected
    await expect(page.getByTestId("sg-retry")).toBeVisible();
  });

  test("SG-U16 the mode goes with the request: Investor and Trader", async ({ page }) => {
    const a = await setup(page, { mode: "investor" });
    await expect(cards(page).first()).toBeVisible(SLOW);
    expect(a.lists[0]).toBe("for_you|investor");
  });

  test("SG-U16b Trader mode asks for the trader audience", async ({ page }) => {
    const b = await setup(page, { mode: "trader" });
    await expect(panel(page)).toBeVisible(SLOW);
    await expect(page.getByTestId("daily-trader")).toBeVisible();              // the trader panel is still there
    await expect.poll(() => b.lists[0]).toBe("for_you|trader");
  });

  test("SG-U17 390 px: no sideways scroll; the tabs and refresh fit; a card fits the screen", async ({ page }) => {
    await setup(page, { width: 390 });
    await expect(cards(page).first()).toBeVisible(SLOW);
    const { sw, cw } = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }));
    expect(sw).toBeLessThanOrEqual(cw);
    const box = await cards(page).first().boundingBox();
    expect(box!.x + box!.width).toBeLessThanOrEqual(390);
    await expect(page.getByTestId("sg-refresh")).toBeVisible();
    await page.getByTestId("sg-tab-fno_lab").scrollIntoViewIfNeeded();
    await page.getByTestId("sg-tab-fno_lab").click();
    await expect(cards(page).first()).toBeVisible();
    for (const c of await cards(page).all()) {
      const b = await c.boundingBox();
      expect(b!.x + b!.width).toBeLessThanOrEqual(390);
    }
  });

  test("SG-U18 the words on every real and mock card: no 'buy now', 'recommend' or 'pick'", async ({ page }) => {
    await setup(page);
    for (const k of ["for_you", "market", "my_trades", "fno_lab"]) {
      await page.getByTestId(`sg-tab-${k}`).click();
      await expect(cards(page).first()).toBeVisible(SLOW);
      expect(await panel(page).innerText()).not.toMatch(BANNED);
    }
  });
});
