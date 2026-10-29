/**
 * One-screen Copilot app (/v5/app) — the trade idea card (`trade_plan`, src/components/chat/TradePlanChatCard.tsx) on an
 * answer about a stock: TI-13 … TI-17 of test_reports/copilot_trade_idea_20261029.md.
 *
 * The card carries only plan ids; every level on it is the desk's DecisionCard reading GET /api/desk/trade-plans/{id}.
 * Those answers come from `contract-decision-card.json` (backend/tests/test_decision_card_contract.py builds it from the
 * REAL routes on a MOCK world), so the chat shows exactly what the desk shows. The chat stream and everything else is an
 * inline MOCK — not real data — in the real route's shape (backend/routes/chat.py stream_chat, services/
 * copilot_trade_idea.py widget_for). Mocked APIs, production build (pw.copilot-app.config.ts).
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CARD = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", "contract-decision-card.json"), "utf-8"));
const CASH_ID: string = CARD.cash.trade_plan_response.plan.plan_id;
const FNO_ID: string = CARD.fno.trade_plan_response.plan.plan_id;
const APP = "/v5/app";
const DESK = `${APP}/trader/desk`;
const SLOW = { timeout: 15_000 };

const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
type Frame = Record<string, unknown>;
const sse = (frames: Frame[]) => frames.map((f) => `data: ${JSON.stringify(f)}\n\n`).join("");

/** `data` of the trade_plan widget as services/copilot_trade_idea.py widget_for builds it (MOCK figures). */
function ideaData(status: "plan" | "wait", stated = false) {
  return {
    symbol: "FIXCO", status, direction: "bullish", direction_stated: stated, horizon: "positional", horizon_days: 10,
    status_reasons: status === "wait" ? [{ code: "needs_confirmation", message: "MOCK: the close has not cleared the 20-session high yet." }] : [],
    would_change_if: status === "wait" ? ["needs_confirmation: a close above the trigger with volume"] : [],
    plans: [{ plan_id: CASH_ID, label: "Cash long", segment: "cash", family: "cash_long", status: "candidate", preferred: true },
            { plan_id: FNO_ID, label: "Bull call spread", segment: "options", family: "bull_call_spread", status: "candidate", preferred: false }],
    preferred_plan_id: CASH_ID, strategy_plan_id: "plan_mock", data_as_of: { price: "2026-10-28", fno: "2026-10-28" },
    defaults_applied: ["horizon", "instrument"], sizing: "risk_profile",
  };
}
const ANSWER = "**How to trade it (an idea, not a recommendation)** — MOCK answer text quoting the plan.";
const widget = (status: "plan" | "wait") => ({ widget_type: "trade_plan", title: "Trade idea · FIXCO", data: ideaData(status),
  freshness: { state: "end_of_day", last_updated: "2026-10-29T04:30:00+00:00", source: ["NIDP"] }, agent: { id: "stock_analyst", confidence: null } });

interface Seen { streams: Array<{ message: string; persona?: string; surface?: string }> }

async function common(page: Page, status: "plan" | "wait"): Promise<Seen> {
  const seen: Seen = { streams: [] };
  const saved: unknown[] = [];
  await page.route("**/api/desk/trade-plans/*", (r) => {
    const id = decodeURIComponent(new URL(r.request().url()).pathname.split("/").pop() as string);
    if (id === CASH_ID) return json(r, CARD.cash.trade_plan_response);
    if (id === FNO_ID) return json(r, CARD.fno.trade_plan_response);
    return json(r, { detail: "plan_not_found" }, 404);
  });
  await page.route("**/api/desk/paper-account", (r) => json(r, { ...CARD.paper_account, stored: true }));
  await page.route("**/api/risk/profile", (r) => json(r, CARD.risk_profile_default));
  await page.route("**/api/chat/sessions", (r) => r.request().method() === "POST" ? json(r, { session_id: "new1", id: "new1" }) : json(r, []));
  await page.route("**/api/chat/messages*", (r) => json(r, saved));
  await page.route("**/api/chat/suggest-queries*", (r) => json(r, { suggestions: [] }));
  await page.route("**/api/chat/instrument-search*", (r) => json(r, { stocks: [], funds: [] }));
  await page.route("**/api/chat/stream", (r) => {
    const body = r.request().postDataJSON() as { message: string; persona?: string; surface?: string };
    seen.streams.push(body);
    const n = seen.streams.length;
    saved.push({ message_id: `u${n}`, session_id: "new1", role: "user", content: body.message, created_at: "2026-10-29T04:30:00+00:00" },
      { message_id: `a${n}`, session_id: "new1", role: "assistant", content: ANSWER, created_at: "2026-10-29T04:30:05+00:00", widget: widget(status) });
    return r.fulfill({ status: 200, contentType: "text/event-stream", body: sse([
      { type: "meta", session_id: "new1", ai_msg_id: `a${n}`, user_msg_id: `u${n}` },
      { type: "route", agent: "stock_analyst", confidence: 0.9 },
      { type: "widget", ...widget(status) },
      { type: "token", content: ANSWER },
      { type: "done", content: ANSWER, follow_ups: [] },
    ]) });
  });
  return seen;
}

async function inThread(page: Page, status: "plan" | "wait" = "plan") {
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  const seen = await common(page, status);
  await page.goto(APP);
  await page.getByTestId("composer-input").fill("Plan a breakout trade for FIXCO");
  await page.getByTestId("composer-input").press("Enter");
  await expect(page.getByTestId("thread-turn").first()).toHaveAttribute("data-state", "saved", SLOW);
  return seen;
}

test.describe("MOCK — not real data: the Copilot's trade idea card", () => {
  test("TI-13 the answer starts with the card: the stock, 'Setup found', the assumed view, the desk's own plan read by id", async ({ page }) => {
    await inThread(page);
    const card = page.getByTestId("tpc");
    await expect(card).toBeVisible();
    await expect(card).toHaveAttribute("data-status", "plan");
    await expect(page.getByTestId("tpc-symbol")).toHaveText("FIXCO");
    await expect(page.getByTestId("tpc-status")).toHaveText("Setup found");
    await expect(page.getByTestId("tpc-view")).toHaveText("Long view · assumed (you did not say) · positional, about 10 sessions");
    // The levels are the desk's DecisionCard, read from GET /api/desk/trade-plans/{id}: the same plan id, entry and stop.
    const plan = page.getByTestId("tpc-plan");
    await expect(plan).toHaveAttribute("data-plan-id", CASH_ID, SLOW);
    await expect(plan.getByTestId("dc-entry")).not.toHaveText(/unavailable/);
    await expect(plan.getByTestId("dc-stop")).not.toHaveText(/unavailable/);
    await expect(page.getByTestId("tpc-other")).toHaveText(["Bull call spread (options) ›"]);
    await expect(page.getByTestId("tpc-foot")).toContainText("Built by the desk’s rules from end-of-day prices");
    await expect(page.getByTestId("tpc-foot")).toContainText("An idea to review, not a recommendation; nothing is sent to a broker.");
    await expect(page.getByTestId("tpc")).not.toContainText(/\b(pick|recommended|suggested trade|buy now)\b/i);
    await expect(page.getByTestId("answer-text")).toContainText("How to trade it (an idea, not a recommendation)");
  });

  test("TI-13b compact, like the AI recommendations, in plain words; 'Full card ›' opens the whole card", async ({ page }) => {
    await inThread(page);
    const plan = page.getByTestId("tpc-plan");
    await expect(plan).toHaveAttribute("data-variant", "row", SLOW);
    await expect(plan.getByTestId("dc-entry")).toContainText("Enter ");
    await expect(plan.getByTestId("dc-stop")).toContainText("Exit if wrong");
    await expect(plan.getByTestId("dc-sections")).toHaveCount(0);
    await expect(plan).not.toContainText(/×ATR|\(\d+\.\d+R\)|of equity|sessions\b|risk service|Provisional|tp_[0-9a-f]{6}/);
    await page.getByTestId("tpc-full").click();
    const full = page.getByTestId("tpc-plan");
    await expect(full).toHaveAttribute("data-variant", "full", SLOW);
    for (const s of ["setup", "entry", "stop", "targets", "size", "costs", "evidence", "warnings", "exit"]) await expect(full.getByTestId(`dc-sec-${s}`)).toBeVisible();
    // The technical record is kept, closed, under "Technical details".
    await expect(full.getByTestId("dc-sec-audit")).not.toHaveAttribute("open", /.*/);
    const shown = (await full.innerText()).replace(/\s+/g, " ");
    expect(shown).not.toMatch(/×ATR|\(\d+\.\d+R\)|of equity|sessions\b|risk service/);
    await page.getByTestId("tpc-full").click();
    await expect(page.getByTestId("tpc-plan")).toHaveAttribute("data-variant", "row");
  });

  test("TI-14 'Paper trade ›' and 'Also fits' open Chart Analysis on the stock with that plan (Strategy Lab removed, owner 29 Oct)", async ({ page }) => {
    await inThread(page);
    await expect(page.getByTestId("tpc-open-lab")).toHaveAttribute("href", `${APP}/trader/desk?tab=trade&view=chart&sub=live&sym=FIXCO&tp=${CASH_ID}`);
    await expect(page.getByTestId("tpc-other")).toHaveAttribute("href", `${APP}/trader/desk?tab=trade&view=chart&sub=live&sym=FIXCO&tp=${FNO_ID}`);
  });

  test("TI-15 'Plan a bearish trade instead' asks the Copilot again in words", async ({ page }) => {
    const seen = await inThread(page);
    await page.getByTestId("tpc-flip").click();
    await expect.poll(() => seen.streams.map((s) => s.message)).toEqual(["Plan a breakout trade for FIXCO", "Plan a bearish trade for FIXCO instead"]);
  });

  test("TI-16 a setup waiting for confirmation says so, with the reasons and what would change", async ({ page }) => {
    await inThread(page, "wait");
    await expect(page.getByTestId("tpc-status")).toHaveText("Waiting for confirmation");
    await expect(page.getByTestId("tpc-reason")).toHaveText(["MOCK: the close has not cleared the 20-session high yet."]);
    await expect(page.getByTestId("tpc-would-change")).toHaveText(["Would change if a close above the trigger with volume"]);
    await expect(page.getByTestId("tpc-plan")).toHaveAttribute("data-plan-id", CASH_ID, SLOW);
  });

  test("TI-17 on the trading desk the Copilot panel shows the card itself, not only a link to the thread", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });                       // the Copilot docks from 1400px
    await mockApi(page, "populated");
    await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
    await page.route("**/api/move-odds/**", (r) => json(r, { detail: "feature_not_enabled" }, 403));
    await page.route("**/api/desk/paper-trades*", (r) => json(r, { as_of: null, checked_through: null, marks_error: null, trades: [], summary: { open: 0, closed: 0, wins: 0, losses: 0, realized_pnl_rs: null, unrealized_pnl_rs: null, unmarked_open: 0, partial: false } }));
    await page.route("**/api/desk/alerts*", (r) => json(r, { as_of: null, checked_through: null, marks_error: null, alerts: [] }));
    const seen = await common(page, "plan");
    await page.goto(DESK);
    await page.getByTestId("dock-input").fill("Plan a breakout trade for FIXCO");
    await page.getByTestId("dock-send").click();
    const dock = page.getByTestId("dock-turn").first();
    await expect(dock.getByTestId("tpc")).toBeVisible(SLOW);
    await expect(dock.getByTestId("tpc-plan")).toHaveAttribute("data-plan-id", CASH_ID, SLOW);
    await expect(dock).not.toContainText("This answer has a result card");
    expect(seen.streams[0].surface).toBe("trading_desk");
    await dock.getByTestId("tpc-flip").click();
    await expect.poll(() => seen.streams.map((s) => s.message)).toEqual(["Plan a breakout trade for FIXCO", "Plan a bearish trade for FIXCO instead"]);
  });
});
