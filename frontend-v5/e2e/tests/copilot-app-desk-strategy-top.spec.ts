/**
 * Smart trading desk — Strategy Builder, "Top 5 by regime" (?tab=more&view=strategy&mode=top).
 *
 * The fixture `desk-strategy-top.json` is a REAL response captured from staging on 2026-10-21
 * (schema desk.strategy.top.v1, rules regime-fit-v1), trimmed to two ideas per class. Figures in it
 * are therefore real prices and a real measured regime, not invented numbers.
 *
 * What these cases defend is the honesty of the screen as much as its layout: the ranking caveat and
 * the gaps must be ON the page rather than behind a tooltip, the cash section must not claim a fit
 * ranking it does not have, and a theoretical reward:risk must never be presented as the ranking
 * number. Those are the properties that would quietly rot.
 *
 * The paper-trade cases are the browser half of a CONTRACT (Phase 0 release gate 7): the body the
 * "Paper trade" button sends must equal `contract-fno-idea-paper-trade.json`, the same file
 * backend/tests/test_fno_idea_paper_trade_contract.py sends through the real route and validator.
 * The POST itself is still answered by a mock here (MOCK — not the real route); what proves the
 * route accepts the body is that backend test, not this 201. The levels reply
 * `desk-strategy-levels-banknifty.json` is the real engine's answer for the contract idea (pinned by
 * the same backend test). Cases F-1 … F-6 of test_reports/fno_idea_paper_trade_TESTCASES.md.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { isDeepStrictEqual } from "util";
import { mockApi } from "../helpers/api-mock";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const fixture = (name: string) => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", name), "utf-8"));
const TOP = fixture("desk-strategy-top.json");
const CONTRACT = fixture("contract-fno-idea-paper-trade.json");
const LEVELS = fixture(CONTRACT.levels_reply_fixture);
const DESK = "/v5/app/trader/desk";
const URL = `${DESK}?tab=more&view=strategy&mode=top`;

/** A minimal valid payoff answer: enough for the chart to render, shaped like the real route's. */
const PAYOFF = {
  valid: true, problems: [], warnings: [], calculation_version: "payoff-v1",
  underlying: "BANKNIFTY", reference_price: 55000, as_of: "2026-10-21",
  expiry: {
    grid: [54000, 54500, 55000, 55500, 56000], gross: [900, 400, -100, -100, -100],
    net: [880, 380, -120, -120, -120], per_leg: [], breakevens: [54707.7],
    max_profit: 18231, max_loss: -8769, profit_unbounded: false, loss_unbounded: false,
    range_max_profit: 18231, range_max_loss: -8769, net_premium: -8769, scenarios: [],
    extremes_basis: "gross, all prices",
  },
  pre_expiry: null, costs: null, margin: null, margin_reason: "none", capital_at_risk: 8858,
  capital_at_risk_basis: "worst net loss", loss_can_exceed_margin: false, caveats: [], sent_to_broker: false,
};

async function openTop(page: Page, body: unknown = TOP) {
  await mockApi(page, "populated");
  await page.route("**/api/desk/strategy/top", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) }));
  await page.goto(URL);
  await expect(page.getByTestId("top-by-regime")).toBeVisible();
}

test.describe("Strategy Builder — Top by regime", () => {
  test("TC-28 the mode chip exists and opens the board", async ({ page }) => {
    await mockApi(page, "populated");
    await page.route("**/api/desk/strategy/top", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(TOP) }));
    await page.goto(`${DESK}?tab=more&view=strategy`);
    const chip = page.getByTestId("builder-mode-top");
    await expect(chip).toBeVisible();
    await chip.click();
    await expect(page.getByTestId("top-by-regime")).toBeVisible();
  });

  test("TC-28 all three asset classes render with their own sections", async ({ page }) => {
    await openTop(page);
    await expect(page.getByTestId("top-class-index_options")).toBeVisible();
    await expect(page.getByTestId("top-class-stock_fno")).toBeVisible();
    await expect(page.getByTestId("top-class-cash")).toBeVisible();
    await expect(page.getByText("Index options — NIFTY and BANKNIFTY")).toBeVisible();
    await expect(page.getByText("Stock F&O", { exact: true })).toBeVisible();
    await expect(page.getByText("Cash stocks", { exact: true })).toBeVisible();
  });

  test("TC-29 the regime strip shows trend, VIX against its threshold, breadth and the measured date", async ({ page }) => {
    await openTop(page);
    const strip = page.getByTestId("top-regime");
    await expect(strip).toContainText("down");                 // regime.trend
    await expect(strip).toContainText("14.77");                // india_vix
    await expect(strip).toContainText("20");                   // vix_high_threshold
    await expect(strip).toContainText("below");                // judged against the threshold
    await expect(strip).toContainText("19");                   // advancing_share_pct
  });

  test("TC-29 the regime/chain date gap is shown, not hidden", async ({ page }) => {
    await openTop(page);
    await expect(page.getByTestId("top-staleness")).toContainText("regime was last classified");
  });

  test("TC-30 an idea card carries max loss, capital at risk, breakeven and reward : risk", async ({ page }) => {
    await openTop(page);
    const first = page.getByTestId("top-class-index_options").locator("article").first();
    await expect(first).toContainText("Max loss");
    await expect(first).toContainText("Capital at risk");
    await expect(first).toContainText("Breakeven");
    await expect(first).toContainText("Reward : risk");
    await expect(first.getByTestId("idea-fit")).toContainText("fit");
  });

  test("TC-30 each idea states why it fits, from the route's own factors", async ({ page }) => {
    await openTop(page);
    const why = page.getByTestId("top-class-index_options").locator("article").first().getByTestId("idea-why");
    await expect(why).toContainText("India VIX");
    await expect(why).toContainText("50-session average");
  });

  test("TC-31 the ranking caveat is visible on the page, not behind a tooltip", async ({ page }) => {
    await openTop(page);
    const note = page.getByTestId("top-ranking-note");
    await expect(note).toBeVisible();
    await expect(note).toContainText("not a forecast");
    await expect(note).toContainText("not a probability");
    await expect(note).toContainText("not a ranking by past performance");
  });

  test("TC-31 the gaps the engine cannot close are listed on screen", async ({ page }) => {
    await openTop(page);
    const gaps = page.getByTestId("top-gaps");
    await expect(gaps).toBeVisible();
    await expect(gaps).toContainText("IV percentile");
    await expect(gaps).toContainText("performance");
  });

  test("the cash section does not claim a regime-fit ranking", async ({ page }) => {
    await openTop(page);
    const cash = page.getByTestId("top-class-cash");
    await expect(cash).toBeVisible();
    // No fit chip anywhere in the cash section: those ideas carry the scanner's evidence rank.
    await expect(cash.getByTestId("idea-fit")).toHaveCount(0);
    await expect(page.getByText("NOT ranked by regime fit", { exact: false })).toBeVisible();
  });

  test("a theoretical reward : risk is labelled as not the ranking number", async ({ page }) => {
    await openTop(page);
    const first = page.getByTestId("top-class-index_options").locator("article").first();
    await expect(first).toContainText("is not what this is ranked on");
  });

  test("TC-32 a class with no ideas shows the reason instead of an empty box", async ({ page }) => {
    const body = JSON.parse(JSON.stringify(TOP));
    body.classes.index_options.ideas = [];
    body.classes.index_options.unavailable = [{ underlying: "NIFTY", reason: "no chain today" }];
    await openTop(page, body);
    const cls = page.getByTestId("top-class-index_options");
    await expect(cls).toContainText("No idea fits here");
    await cls.getByTestId("top-unavailable").click();
    await expect(cls).toContainText("no chain today");
  });

  test("an unavailable regime is stated and nothing is invented", async ({ page }) => {
    const body = JSON.parse(JSON.stringify(TOP));
    body.regime = { available: false, reason: "macro_state is empty" };
    body.classes.index_options.ideas = [];
    body.classes.stock_fno.ideas = [];
    await openTop(page, body);
    await expect(page.getByTestId("top-regime")).toContainText("macro_state is empty");
    await expect(page.getByTestId("top-class-index_options")).toContainText("No idea fits here");
  });

  test("a failed request offers a retry rather than a blank screen", async ({ page }) => {
    await mockApi(page, "populated");
    await page.route("**/api/desk/strategy/top", (route) =>
      route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "upstream" }) }));
    await page.goto(URL);
    await expect(page.getByRole("alert")).toBeVisible();
  });
});

test.describe("Strategy Builder — Top by regime: payoff and paper trade", () => {
  test("the payoff chart is not calculated until it is opened", async ({ page }) => {
    let calls = 0;
    await mockApi(page, "populated");
    await page.route("**/api/desk/strategy/top", (r) =>
      r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(TOP) }));
    await page.route("**/api/desk/strategy/payoff", (r) => { calls += 1; return r.fulfill({ status: 200, contentType: "application/json", body: "{}" }); });
    await page.goto(URL);
    await expect(page.getByTestId("top-by-regime")).toBeVisible();
    await page.waitForTimeout(600);
    // Five cards must not fire five calculations nobody asked for.
    expect(calls).toBe(0);
  });

  test("opening the payoff sends the idea's own legs and renders the chart", async ({ page }) => {
    let body: any = null;
    await mockApi(page, "populated");
    await page.route("**/api/desk/strategy/top", (r) =>
      r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(TOP) }));
    await page.route("**/api/desk/strategy/payoff", async (r) => {
      body = JSON.parse(r.request().postData() || "{}");
      return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(PAYOFF) });
    });
    await page.goto(URL);
    const card = page.getByTestId("top-class-index_options").locator("article").first();
    // usePayoff debounces by 250ms, so wait for the request itself rather than racing it.
    const req = page.waitForRequest((r) => r.url().includes("/api/desk/strategy/payoff"));
    await card.getByTestId("idea-payoff-toggle").click();
    await req;
    await expect(card.getByTestId("idea-payoff")).toBeVisible();
    const idea = TOP.classes.index_options.ideas[0];
    expect(body.underlying).toBe(idea.underlying);
    expect(body.reference_price).toBe(idea.reference_price);
    expect(body.legs.length).toBe(idea.legs.length);
    // The legs are the route's own, including the strike it priced.
    expect(body.legs[0].strike).toBe(idea.legs[0].strike);
  });

  test("a refused paper trade says so and does not claim success", async ({ page }) => {
    await mockApi(page, "populated");
    await page.route("**/api/desk/strategy/top", (r) =>
      r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(TOP) }));
    await page.route("**/api/desk/paper-trades", (r) =>
      r.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ detail: "open_trade_limit" }) }));
    await page.goto(URL);
    const card = page.getByTestId("top-class-index_options").locator("article").first();
    await card.getByTestId("idea-paper-trade").click();
    await expect(card.getByTestId("idea-paper-error")).toBeVisible();
    await expect(card.getByTestId("idea-paper-trade")).not.toContainText("Added to paper trades");
  });
});

// ── the paper-trade contract (gate 7) and the provisional levels (D4) ─────

/** MOCK — POST /api/desk/strategy/levels: the real engine's answer for the contract idea's exact request, a not-valid
 *  answer for any other idea (or a 503 with `fail`). */
const NOT_VALID = { valid: false, version: "strategy-levels-v2", problems: [{ code: "mock", message: "MOCK: not worked out in this test" }], sent_to_broker: false };
const f2 = (n: number) => n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

interface Seen { levels: Array<Record<string, any>>; paper: Array<Record<string, unknown>> }

async function contractBoard(page: Page, o: { board?: unknown; fail?: boolean; delayMs?: number } = {}): Promise<Seen> {
  const seen: Seen = { levels: [], paper: [] };
  await mockApi(page, "populated");
  await page.route("**/api/desk/strategy/top", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(o.board ?? TOP) }));
  await page.route("**/api/desk/strategy/levels", async (r: Route) => {
    const body = r.request().postDataJSON();
    seen.levels.push(body);
    if (o.delayMs) await new Promise((res) => setTimeout(res, o.delayMs));
    if (o.fail) return r.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "MOCK levels unavailable" }) });
    const answer = isDeepStrictEqual(body, CONTRACT.levels_request) ? LEVELS : NOT_VALID;
    return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(answer) });
  });
  await page.route("**/api/desk/paper-trades", (r) => {
    if (r.request().method() === "POST") seen.paper.push(r.request().postDataJSON());
    return r.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ trade: { id: "t1" } }) });
  });
  await page.goto(URL);
  return seen;
}

const bankCard = (page: Page) => page.getByTestId(`top-idea-${CONTRACT.idea.underlying}-${CONTRACT.idea.structure}`);

test.describe("Top by regime — the paper-trade contract and the provisional levels", () => {
  test("F-1 / F-2 the levels request and the paper-trade body are exactly the shared contract", async ({ page }) => {
    const seen = await contractBoard(page);
    const card = bankCard(page);
    await expect(card.getByTestId("idea-levels")).toHaveAttribute("data-state", "ok");
    expect(seen.levels.filter((b) => b.payoff?.underlying === CONTRACT.idea.underlying)).toEqual([CONTRACT.levels_request]);
    await card.getByTestId("idea-paper-trade").click();
    await expect(card.getByTestId("idea-paper-trade")).toHaveText("Added to paper trades");
    expect(seen.paper).toEqual([CONTRACT.body_with_levels]);
    await expect(card.getByTestId("idea-paper-done")).toContainText(`stop ${f2(LEVELS.underlying.stop)} and target ${f2(LEVELS.underlying.target)} on BANKNIFTY`);
  });

  test("F-3 when the levels do not load, the body is the contract's body without levels", async ({ page }) => {
    const seen = await contractBoard(page, { fail: true });
    const card = bankCard(page);
    await expect(card.getByTestId("idea-levels")).toHaveAttribute("data-state", "failed");
    await card.getByTestId("idea-paper-trade").click();
    await expect(card.getByTestId("idea-paper-trade")).toHaveText("Added to paper trades");
    expect(seen.paper).toEqual([CONTRACT.body_without_levels]);
    await expect(card.getByTestId("idea-paper-done")).toContainText("no stop or target");
  });

  test("F-4 the levels block: labelled provisional, dated, the engine's figures, the full plan, and no new entry control", async ({ page }) => {
    await contractBoard(page);
    const card = bankCard(page);
    const lv = card.getByTestId("idea-levels");
    await expect(lv).toHaveAttribute("data-state", "ok");
    await expect(lv.getByTestId("idea-levels-label")).toHaveText("Provisional · research levels");
    await expect(lv.getByTestId("idea-levels-asof")).toHaveText("end-of-day chain of 21 Oct 2026");
    await expect(lv.getByTestId("idea-levels-entry")).toHaveText(`Entry · net debit ${f2(LEVELS.premium.entry)}`);
    await expect(lv.getByTestId("idea-levels-stop")).toHaveText(`Stop ${f2(LEVELS.premium.planned_stop)} (BANKNIFTY ${f2(LEVELS.underlying.stop)})`);
    await expect(lv.getByTestId("idea-levels-t1")).toHaveText(`Target 1 ${f2(LEVELS.premium.target_1)} (BANKNIFTY ${f2(LEVELS.underlying.target)})`);
    await expect(lv.getByTestId("idea-levels-t2")).toHaveText(`Target 2 ${f2(LEVELS.premium.target_2)} (BANKNIFTY ${f2(LEVELS.underlying.target_2)})`);
    await expect(lv.getByTestId("idea-levels-maxloss")).toHaveText(`Max loss ₹${Math.abs(LEVELS.max_loss_total).toLocaleString("en-IN")} before costs`);
    // The only control in the block is the full plan's toggle; the card keeps one Paper trade and no order-like button.
    await expect(lv.locator("button")).toHaveCount(1);
    await lv.getByTestId("idea-levels-plan").click();
    await expect(lv.getByTestId("desk-levels")).toBeVisible();
    await expect(lv.getByTestId("desk-levels-underlying")).toContainText(f2(LEVELS.underlying.stop));
    await expect(lv.getByTestId("desk-levels")).not.toContainText("Zerodha");
    await expect(lv.locator("button")).toHaveCount(1);
    await expect(card.getByTestId("idea-paper-trade")).toHaveCount(1);
    const labels = await card.locator("button").allInnerTexts();
    expect(labels.filter((t) => /\b(buy|sell|order|place|execute|enter)\b/i.test(t))).toEqual([]);
    const text = await card.innerText();
    expect(text).not.toMatch(/\bpicks?\b/i);
    expect(text).not.toMatch(/\b(suggested|recommended)\b/i);
  });

  test("F-5 the button waits for the levels, so the body carries the levels the row then shows", async ({ page }) => {
    const seen = await contractBoard(page, { delayMs: 1500 });
    const card = bankCard(page);
    await expect(card.getByTestId("idea-levels")).toHaveAttribute("data-state", "pending");
    await expect(card.getByTestId("idea-paper-trade")).toBeDisabled();
    await expect(card.getByTestId("idea-levels")).toHaveAttribute("data-state", "ok");
    await card.getByTestId("idea-paper-trade").click();
    await expect(card.getByTestId("idea-paper-trade")).toHaveText("Added to paper trades");
    expect(seen.paper).toEqual([CONTRACT.body_with_levels]);
  });

  test("F-4b the engine's own warning (expiry week) is shown in the row's block, not only in the full plan", async ({ page }) => {
    const flagged = { ...LEVELS, flags: [{ code: "expiry_week", message: "1 days to expiry: gamma can change quickly, so the levels can be overtaken fast." }] }; // MOCK flag
    await mockApi(page, "populated");
    await page.route("**/api/desk/strategy/top", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(TOP) }));
    await page.route("**/api/desk/strategy/levels", (r) =>
      r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(isDeepStrictEqual(r.request().postDataJSON(), CONTRACT.levels_request) ? flagged : NOT_VALID) }));
    await page.goto(URL);
    const lv = bankCard(page).getByTestId("idea-levels");
    await expect(lv).toHaveAttribute("data-state", "ok");
    await expect(lv.getByTestId("idea-levels-flag")).toHaveText(flagged.flags[0].message);
  });

  test("F-6 a neutral idea records no stop or target even when the engine answered", async ({ page }) => {
    const board = JSON.parse(JSON.stringify(TOP));
    board.classes.index_options.ideas[0].view = "flat";             // MOCK: the same legs read as a neutral view
    const seen = await contractBoard(page, { board });
    const card = bankCard(page);
    await expect(card.getByTestId("idea-levels")).toHaveAttribute("data-state", "ok");
    await card.getByTestId("idea-paper-trade").click();
    await expect(card.getByTestId("idea-paper-trade")).toHaveText("Added to paper trades");
    const body = seen.paper[0] as Record<string, any>;
    expect(body.direction).toBe("neutral");
    expect(body).not.toHaveProperty("stop_underlying");
    expect(body).not.toHaveProperty("target_underlying");
    expect(body.signal).toEqual(CONTRACT.body_without_levels.signal);
  });
});

test.describe("Strategy Builder — Top by regime: live premiums", () => {
  test("no live read happens until it is asked for", async ({ page }) => {
    let calls = 0;
    await mockApi(page, "populated");
    await page.route("**/api/desk/strategy/top", (r) =>
      r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(TOP) }));
    await page.route("**/api/live/fno-quotes", (r) => { calls += 1; return r.fulfill({ status: 200, contentType: "application/json", body: "{}" }); });
    await page.goto(URL);
    await expect(page.getByTestId("top-by-regime")).toBeVisible();
    await page.waitForTimeout(600);
    expect(calls).toBe(0);
  });

  test("asking for live premiums sends every leg on the board, once", async ({ page }) => {
    let body: any = null;
    let calls = 0;
    await mockApi(page, "populated");
    await page.route("**/api/desk/strategy/top", (r) =>
      r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(TOP) }));
    await page.route("**/api/live/fno-quotes", async (r) => {
      calls += 1;
      body = JSON.parse(r.request().postData() || "{}");
      return r.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ available: false, reason: "no Kite access token is stored for the platform feed", quotes: {}, unresolved: [] }) });
    });
    await page.goto(URL);
    const req = page.waitForRequest((r) => r.url().includes("/api/live/fno-quotes"));
    await page.getByTestId("top-live-toggle").click();
    await req;
    expect(calls).toBe(1);                       // one request for the whole board, not one per card
    const expected = [...TOP.classes.index_options.ideas, ...TOP.classes.stock_fno.ideas]
      .reduce((n: number, i: any) => n + i.legs.length, 0);
    expect(body.legs.length).toBe(expected);
    expect(body.legs[0]).toHaveProperty("underlying");
    expect(body.legs[0]).toHaveProperty("strike");
  });

  test("an unavailable live read says so and keeps the end-of-day figures", async ({ page }) => {
    await mockApi(page, "populated");
    await page.route("**/api/desk/strategy/top", (r) =>
      r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(TOP) }));
    await page.route("**/api/live/fno-quotes", (r) =>
      r.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ available: false, reason: "no Kite access token is stored for the platform feed", quotes: {}, unresolved: [] }) }));
    await page.goto(URL);
    await page.getByTestId("top-live-toggle").click();
    const card = page.getByTestId("top-class-index_options").locator("article").first();
    await expect(card.getByTestId("idea-live-off")).toContainText("Live premium unavailable");
    await expect(card.getByTestId("idea-live-off")).toContainText("no Kite access token");
    await expect(card.getByTestId("idea-live")).toHaveCount(0);
  });

  test("a live read shows the live net premium beside the end-of-day one, and says the ranking is still EOD", async ({ page }) => {
    const idea = TOP.classes.index_options.ideas[0];
    // Price every leg of every board idea; the first card's legs are indexes 0..n-1.
    const quotes: Record<string, unknown> = {};
    const all = [...TOP.classes.index_options.ideas, ...TOP.classes.stock_fno.ideas];
    let n = 0;
    all.forEach((i: any) => i.legs.forEach(() => { quotes[String(n)] = { key: `NFO:X${n}`, last_price: 100 + n }; n += 1; }));
    await mockApi(page, "populated");
    await page.route("**/api/desk/strategy/top", (r) =>
      r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(TOP) }));
    await page.route("**/api/live/fno-quotes", (r) =>
      r.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ available: true, reason: null, quotes, unresolved: [], as_of: "2026-10-22T04:30:00Z", source: "kite" }) }));
    await page.goto(URL);
    await page.getByTestId("top-live-toggle").click();
    const card = page.getByTestId("top-class-index_options").locator("article").first();
    await expect(card.getByTestId("idea-live")).toBeVisible();
    await expect(card.getByTestId("idea-live")).toContainText("Live net premium");
    await expect(card.getByTestId("idea-live")).toContainText("the ranking above is still the end-of-day one");
  });

  test("a part-priced idea shows no live total rather than a number belonging to no moment", async ({ page }) => {
    await mockApi(page, "populated");
    await page.route("**/api/desk/strategy/top", (r) =>
      r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(TOP) }));
    await page.route("**/api/live/fno-quotes", (r) =>
      r.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ available: true, reason: null, quotes: { "0": { key: "NFO:X0", last_price: 101 } }, unresolved: [{ index: 1, reason: "no listed contract" }] }) }));
    await page.goto(URL);
    await page.getByTestId("top-live-toggle").click();
    const card = page.getByTestId("top-class-index_options").locator("article").first();
    // The first idea is a two-leg spread; only one leg priced, so no live total is claimed.
    await expect(card.getByTestId("idea-live")).toHaveCount(0);
    await expect(card.getByTestId("idea-live-off")).toBeVisible();
  });
});
