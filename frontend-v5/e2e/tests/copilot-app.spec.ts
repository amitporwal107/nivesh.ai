/**
 * One-screen Copilot app (/v5/app) — the shell: rail, home, ask box, answer
 * thread, evidence panel, modes and access, at desktop and phone sizes.
 *
 * Test-case ids (TC-xx) match test_reports/copilot_one_screen_*.md.
 *
 * Runs against a production build with every /api/* call answered by route
 * mocks (see pw.copilot-app.config.ts). The chat stream is mocked as a
 * text/event-stream body carrying the same frames backend/routes/chat.py emits.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import { mockApi, mockAuthAs, mockSingleRoute, mock401 } from "../helpers/api-mock";

const APP = "/v5/app";

type Frame = Record<string, unknown>;
type Msg = { message_id: string; session_id: string; role: "user" | "assistant"; content: string; created_at: string; widget?: unknown };

const sse = (frames: Frame[]) => frames.map((f) => `data: ${JSON.stringify(f)}\n\n`).join("");

const RISK_FRAMES: Frame[] = [
  { type: "meta", session_id: "new1", ai_msg_id: "ai1", user_msg_id: "u1" },
  { type: "route", agent: "risk_advisor", confidence: 0.92 },
  { type: "thinking", tool: "get_portfolio_holdings", status: "start" },
  { type: "thinking", tool: "get_portfolio_holdings", status: "end" },
  { type: "thinking", tool: "risk_overview", status: "start" },
  { type: "thinking", tool: "risk_overview", status: "end" },
  { type: "token", content: "Your portfolio is " },
  { type: "token", content: "moderately risky." },
  { type: "done", content: "Your portfolio is moderately risky.", follow_ups: ["What drives the risk?", "How do I reduce it?"] },
];

const BACKEND_ERROR = "I'm having trouble connecting right now. Please try again.";

interface ChatMock {
  /** Parsed JSON bodies of every POST /api/chat/stream. */
  streams: Array<{ message: string; session_id?: string }>;
  created: number;
}

/**
 * Stateful mock of the chat endpoints. A successful stream appends the
 * question and the answer to that session's saved messages — as the real
 * backend does — so the refetch after the stream returns them. An `error`
 * frame saves the question plus the backend's own error text.
 */
async function mockChat(page: Page, opts: {
  sessions?: Array<{ session_id: string; title: string; updated_at: string }>;
  messages?: Record<string, Msg[]>;
  frames?: Frame[];
  streamStatus?: number;
  widget?: Frame;
} = {}): Promise<ChatMock> {
  const state: ChatMock = { streams: [], created: 0 };
  const sessions = [...(opts.sessions ?? [])];
  const messages: Record<string, Msg[]> = { ...(opts.messages ?? {}) };
  const json = (route: Route, body: unknown, status = 200) =>
    route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

  await page.route("**/api/chat/sessions", async (route) => {
    if (route.request().method() === "POST") {
      state.created += 1;
      const id = state.created === 1 ? "new1" : `new${state.created}`;
      sessions.unshift({ session_id: id, title: "New conversation", updated_at: new Date().toISOString() });
      messages[id] = [];
      return json(route, { session_id: id, id });
    }
    return json(route, sessions);
  });
  await page.route("**/api/chat/messages*", (route) => {
    const sid = new URL(route.request().url()).searchParams.get("session_id") ?? "";
    return json(route, messages[sid] ?? []);
  });
  await page.route("**/api/chat/stream", async (route) => {
    const body = route.request().postDataJSON() as { message: string; session_id?: string };
    state.streams.push(body);
    if (opts.streamStatus && opts.streamStatus >= 400) return json(route, { detail: "boom" }, opts.streamStatus);
    const frames = opts.frames ?? RISK_FRAMES;
    const sid = body.session_id ?? "new1";
    const n = state.streams.length;
    const now = new Date().toISOString();
    const done = frames.find((f) => f.type === "done") as { content?: string } | undefined;
    const err = frames.find((f) => f.type === "error") as { content?: string } | undefined;
    const meta = frames.find((f) => f.type === "meta") as { ai_msg_id?: string } | undefined;
    const widget = frames.find((f) => f.type === "widget");
    const list = (messages[sid] ??= []);
    list.push({ message_id: `u${n}`, session_id: sid, role: "user", content: body.message, created_at: now });
    if (done || err) {
      const { type: _t, ...env } = (widget ?? {}) as Frame;
      list.push({
        message_id: n === 1 ? (meta?.ai_msg_id ?? `a${n}`) : `a${n}`,
        session_id: sid,
        role: "assistant",
        content: done?.content ?? err?.content ?? "",
        created_at: now,
        ...(widget ? { widget: env } : {}),
      });
    }
    return route.fulfill({ status: 200, contentType: "text/event-stream", body: sse(frames) });
  });
  await page.route("**/api/chat/suggest-queries*", (route) =>
    json(route, { suggestions: [{ query: "Which of my funds overlap the most?", section: "Portfolio", category: "Overlap", subcategory: "", has_placeholder: false }] }));
  await page.route("**/api/chat/instrument-search*", (route) => json(route, { stocks: [], funds: [] }));
  return state;
}

async function setup(page: Page, preset: "populated" | "empty" = "populated") {
  await mockApi(page, preset);
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
}

function trackPageErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

async function askFromBox(page: Page, question: string) {
  const input = page.getByTestId("composer-input");
  await input.fill(question);
  await input.press("Enter");
}

test.describe("Copilot app — desktop", () => {
  test("TC-01 shell renders: rail, greeting, ask box", async ({ page }) => {
    const errors = trackPageErrors(page);
    await setup(page);
    await mockChat(page);
    await page.goto(APP);
    const rail = page.getByTestId("copilot-rail");
    await expect(rail).toBeVisible();
    await expect(rail.getByText("Nivesh", { exact: true })).toBeVisible();
    await expect(page.getByTestId("new-question")).toBeVisible();
    for (const label of ["Threads", "Tools", "Workspace"]) {
      await expect(rail.getByText(label, { exact: true })).toBeVisible();
    }
    // user-profile-onboarded.json → name "Test Onboarded User"
    await expect(page.getByTestId("home-headline")).toHaveText("What would you like to know, Test?");
    await expect(page.getByTestId("composer-input")).toBeVisible();
    await expect(page.getByTestId("rail-user")).toContainText("Test Onboarded User");
    expect(errors).toEqual([]);
  });

  test("TC-02 rail lists saved threads and opens one", async ({ page }) => {
    await setup(page);
    const now = new Date().toISOString();
    await mockChat(page, {
      sessions: [
        { session_id: "s1", title: "Why is my score 74?", updated_at: now },
        { session_id: "s2", title: "Fund overlap check", updated_at: now },
      ],
      messages: {
        s1: [
          { message_id: "m1", session_id: "s1", role: "user", content: "Why is my score 74?", created_at: now },
          { message_id: "m2", session_id: "s1", role: "assistant", content: "Your score reflects **overlap** between two funds.", created_at: now },
        ],
      },
    });
    await page.goto(APP);
    const rows = page.getByTestId("thread-row");
    await expect(rows).toHaveCount(2);
    await expect(rows.nth(0)).toContainText("Why is my score 74?");
    await expect(rows.nth(1)).toContainText("Fund overlap check");
    await rows.nth(0).click();
    await expect(page).toHaveURL(/\/v5\/app\/t\/s1$/);
    await expect(page.getByTestId("turn-question")).toHaveText("Why is my score 74?");
    await expect(page.getByTestId("answer-text")).toContainText("Your score reflects overlap between two funds.");
    // History carries no tool steps — the card is absent rather than invented.
    await expect(page.getByTestId("answer-trace")).toHaveCount(0);
  });

  test("TC-03 market strip shows /api/markets/home values, and nothing when it is empty", async ({ page }) => {
    await setup(page);
    await mockChat(page);
    await page.goto(APP);
    const strip = page.getByTestId("home-market-strip");
    await expect(strip).toContainText("NIFTY 50 24,568 −0.49%");
    await expect(strip).toContainText("BREADTH 60% ADVANCING");
    await expect(strip).toContainText("INDIA VIX 13.42 +3.9%");
    await expect(strip).toContainText("FII CASH −₹1,234 CR");
    await expect(strip).toContainText("DII CASH +₹2,345 CR");
    await expect(page.getByTestId("home-eyebrow")).toContainText("Market closed");

    // Endpoint returns nothing usable → no strip at all.
    await page.route("**/api/markets/home", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "{}" }));
    await page.reload();
    await expect(page.getByTestId("home-headline")).toBeVisible();
    await expect(page.getByTestId("home-market-strip")).toHaveCount(0);
    await expect(page.getByTestId("home-eyebrow")).not.toContainText("Market");
  });

  test("TC-04 'for your portfolio today' cards: health, plan and ranked prompts, each from its endpoint", async ({ page }) => {
    await setup(page);
    const chat = await mockChat(page);
    await page.goto(APP);
    await expect(page.getByTestId("home-today-title")).toHaveText("For your portfolio today");
    const cards = page.getByTestId("home-today-card");
    await expect(cards).toHaveCount(6);
    // insights-analysis.json: health_score 68.56, grade B → the dashboard's 55–70 band.
    await expect(cards.nth(0)).toContainText("Your portfolio is in need of some work");
    await expect(cards.nth(0)).toContainText("Health score 69 of 100 · grade B");
    // plans-active.json: six PENDING actions.
    await expect(cards.nth(1)).toContainText("6 actions identified");
    // holdings-enriched.json equity 69.4% vs the 65% target for "Moderately Aggressive"
    // (risk-profile.json) — the dashboard's drift signal, same wording.
    await expect(cards.nth(2)).toContainText("Portfolio drift: equity 69% vs target 65%");
    // suggested-prompts.json: the prompts that carry a computed badge.
    await expect(cards.nth(3)).toContainText("Fix overlap in my funds");
    await expect(cards.nth(3)).toContainText("Top pair 97% overlap");
    await expect(cards.nth(3)).toContainText("Find duplicate funds and which to exit with lowest tax hit");
    await expect(cards.nth(4)).toContainText("Equity 93% · Debt 0%");
    await cards.nth(3).click();
    await expect(page).toHaveURL(/\/v5\/app\/t\/new1$/);
    await expect.poll(() => chat.streams.length).toBe(1);
    expect(chat.streams[0].message).toBe("Which funds or stocks in my portfolio are overlapping the most, and which ones should I remove with minimal tax impact?");
    expect(chat.streams[0].session_id).toBe("new1");

    // The health and plan cards open their screens instead of asking.
    await page.goto(APP);
    await cards.nth(0).click();
    await expect(page).toHaveURL(/\/v5\/app\/tool\/analysis$/);
    await page.goto(APP);
    await cards.nth(1).click();
    await expect(page).toHaveURL(/\/v5\/app\/tool\/recommend$/);
  });

  test("TC-04b the statement bar shows the last CAS and offers Gmail sync and upload, as the dashboard does", async ({ page }) => {
    await setup(page);
    await mockChat(page);
    // Real shape of GET /api/onboarding/state (backend/routes/onboarding_gmail.py).
    await page.route("**/api/onboarding/state", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ onboarding_completed: true, pan_on_file: true, gmail_connected: true, cas_statement_period: "Mar/2025", cas_portfolio_value_rs: 1234567.5, cas_statement_date: "31-Mar-2025", persona: "hni_investor", persona_confidence: 55 }) }));
    await page.goto(APP);
    await expect(page.getByTestId("home-statement-period")).toHaveText("Mar/2025");
    await expect(page.getByTestId("home-statement-sync")).toHaveText("Sync Gmail");
    // Persona and health as the dashboard shows them (labels from its persona card).
    const ctx = page.getByTestId("evidence-context");
    await expect(ctx).toContainText("HNI / UHNI Investor · 55% low confidence");
    await expect(page.getByTestId("context-health-score")).toHaveText("69");
    await expect(ctx).toContainText("Last statement");
    // Sync opens the existing Gmail import flow; nothing is imported until the user confirms there.
    await page.getByTestId("home-statement-sync").click();
    await expect(page.getByText("Import latest CAS", { exact: false }).first()).toBeVisible();
    await page.keyboard.press("Escape");
    await page.reload();
    await page.getByTestId("home-statement-upload").click();
    await expect(page).toHaveURL(/\/v5\/app\/page\/brokers$/);
  });

  test("TC-08b a statement on file with no holdings rows yet is not shown as 'no portfolio'", async ({ page }) => {
    await setup(page, "empty"); // holdings-enriched answers with no rows
    await mockChat(page);
    await page.route("**/api/onboarding/state", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ onboarding_completed: true, pan_on_file: true, gmail_connected: false, cas_statement_period: "Mar/2025", cas_portfolio_value_rs: 1234567.5, cas_statement_date: "31-Mar-2025" }) }));
    await page.goto(APP);
    await expect(page.getByTestId("context-portfolio-value")).toHaveText("₹12,34,568"); // the statement's own figure
    await expect(page.getByTestId("context-from-statement")).toContainText("As printed on your Mar/2025 statement");
    await expect(page.getByTestId("context-no-portfolio")).toHaveCount(0);
    await expect(page.getByTestId("home-connect-banner")).toHaveCount(0);
    await expect(page.getByTestId("home-statement-sync")).toHaveText("Connect Gmail");
    await expect(page.getByTestId("rail-user")).toContainText("Portfolio ₹12.35 L");
  });

  test("TC-05 asking a question streams an answer with class, tool steps and follow-ups", async ({ page }) => {
    const errors = trackPageErrors(page);
    await setup(page);
    const chat = await mockChat(page);
    await page.goto(APP);
    await askFromBox(page, "How risky is my portfolio?");
    await expect(page).toHaveURL(/\/v5\/app\/t\/new1$/);
    expect(chat.created).toBe(1);
    await expect.poll(() => chat.streams.length).toBe(1);
    expect(chat.streams[0]).toMatchObject({ message: "How risky is my portfolio?", session_id: "new1" });

    const turn = page.getByTestId("thread-turn");
    await expect(turn).toHaveCount(1);
    await expect(turn).toHaveAttribute("data-state", "saved");
    await expect(page.getByTestId("turn-question")).toHaveText("How risky is my portfolio?");
    await expect(page.getByTestId("answer-class")).toHaveText("Personalised research");
    await expect(page.getByTestId("answer-routed")).toHaveText("Routed to Risk Advisor · 92%");
    await expect(page.getByTestId("answer-trace-label")).toContainText("Done · 2 tools");
    await expect(page.getByTestId("answer-text")).toHaveText("Your portfolio is moderately risky.");
    // The ask box keeps focus, but its suggestion list must not reopen over the answer.
    await expect(page.getByTestId("composer-suggest")).toHaveCount(0);

    // Steps are collapsed once done; opening shows the two tools the stream named.
    await page.getByTestId("answer-trace").getByRole("button").click();
    const steps = page.getByTestId("answer-step");
    await expect(steps).toHaveCount(2);
    await expect(steps.nth(0)).toContainText("get_portfolio_holdings");
    await expect(steps.nth(1)).toContainText("risk_overview");

    const followUps = page.getByTestId("answer-followups").getByRole("button");
    await expect(followUps).toHaveText(["What drives the risk?", "How do I reduce it?"]);
    await followUps.nth(0).click();
    await expect.poll(() => chat.streams.length).toBe(2);
    expect(chat.streams[1]).toMatchObject({ message: "What drives the risk?", session_id: "new1" });
    expect(chat.created).toBe(1); // same thread, no new session
    await expect(page.getByTestId("thread-turn")).toHaveCount(2);
    // The thread bar names the latest question.
    await expect(page.getByTestId("thread-bar")).toContainText("What drives the risk?");
    expect(errors).toEqual([]);
  });

  test("TC-06 an error frame shows a partial-result banner with a working retry", async ({ page }) => {
    await setup(page);
    const chat = await mockChat(page, { frames: [{ type: "meta", session_id: "new1", ai_msg_id: "ai1" }, { type: "error", content: BACKEND_ERROR }] });
    await page.goto(APP);
    await askFromBox(page, "How risky is my portfolio?");
    const banner = page.getByTestId("answer-banner-danger");
    await expect(banner).toContainText("Partial result");
    await expect(banner).toContainText(BACKEND_ERROR);
    // The backend also saved its error text as an answer; it is not shown twice.
    await expect(page.getByTestId("thread-turn")).toHaveCount(1);
    await expect(page.getByTestId("thread-turn")).toHaveAttribute("data-state", "error");
    await expect(page.getByTestId("answer-trace-label")).toHaveText("Did not finish");
    await page.getByTestId("answer-retry").click();
    await expect.poll(() => chat.streams.length).toBe(2);
    expect(chat.streams[1]).toMatchObject({ message: "How risky is my portfolio?", session_id: "new1" });
  });

  test("TC-07 a failed stream request shows an error and leaves the ask box usable", async ({ page }) => {
    await setup(page);
    await mockChat(page, { streamStatus: 500 });
    await page.goto(APP);
    await askFromBox(page, "How risky is my portfolio?");
    await expect(page.getByTestId("answer-banner-danger")).toContainText("Couldn't start the response stream.");
    // Exactly one copy of the failed turn — never the failed and the live one together.
    await expect(page.getByTestId("thread-turn")).toHaveCount(1);
    await expect(page.getByTestId("turn-question")).toHaveText("How risky is my portfolio?");
    await expect(page.getByTestId("composer-send")).toBeVisible();
    await expect(page.getByTestId("composer-stop")).toHaveCount(0);
    await page.getByTestId("composer-input").fill("another question");
    await expect(page.getByTestId("composer-send")).toBeEnabled();
  });

  test("TC-07c a thread that cannot be started says so, and Retry sends the question", async ({ page }) => {
    await setup(page);
    const chat = await mockChat(page);
    // First create call is refused (what staging answers to a cross-site write), the next succeeds.
    let refused = 0;
    await page.route("**/api/chat/sessions", async (route) => {
      if (route.request().method() === "POST" && refused === 0) {
        refused += 1;
        return route.fulfill({ status: 403, contentType: "application/json", body: JSON.stringify({ error: "CSRF_BLOCKED", message: "Cross-origin request rejected." }) });
      }
      return route.fallback();
    });
    await page.goto(APP);
    await askFromBox(page, "How risky is my portfolio?");
    const failed = page.getByTestId("ask-failed");
    await expect(failed).toContainText("“How risky is my portfolio?” could not be sent");
    await expect(page).toHaveURL(/\/v5\/app$/); // still on home, with the reason in view
    expect(chat.streams.length).toBe(0);
    await expect(page.getByTestId("composer-send")).toBeVisible(); // not stuck in a busy state
    await page.getByTestId("ask-failed-retry").click();
    await expect(page).toHaveURL(/\/v5\/app\/t\/new1$/);
    await expect.poll(() => chat.streams.length).toBe(1);
    expect(chat.streams[0].message).toBe("How risky is my portfolio?");
    await expect(page.getByTestId("ask-failed")).toHaveCount(0);
  });

  test("TC-07b stopping an answer in flight keeps the question and offers a retry", async ({ page }) => {
    await setup(page);
    await mockChat(page);
    // Hold the stream open so the answer is still in flight when Stop is pressed.
    let release: () => void = () => {};
    await page.route("**/api/chat/stream", async (route) => {
      await new Promise<void>((r) => { release = r; });
      await route.abort().catch(() => {});
    });
    await page.goto(APP);
    await askFromBox(page, "How risky is my portfolio?");
    await expect(page.getByTestId("thread-turn")).toHaveAttribute("data-state", "streaming");
    await expect(page.getByTestId("answer-trace-label")).toContainText("Working");
    await page.getByTestId("composer-stop").click();
    await expect(page.getByTestId("thread-turn")).toHaveAttribute("data-state", "stopped");
    await expect(page.getByTestId("answer-banner-amber")).toContainText("You stopped this answer.");
    await expect(page.getByTestId("answer-trace-label")).toHaveText("Stopped");
    await expect(page.getByTestId("thread-turn")).toHaveCount(1);
    await expect(page.getByTestId("turn-question")).toHaveText("How risky is my portfolio?");
    await expect(page.getByTestId("answer-retry")).toBeVisible();
    await expect(page.getByTestId("composer-send")).toBeVisible();
    release();
  });

  test("TC-08 an account with no holdings gets the connect banner and no zero values", async ({ page }) => {
    await setup(page, "empty");
    await mockChat(page);
    await page.goto(APP);
    await expect(page.getByTestId("home-connect-banner")).toContainText("Connect a portfolio and every answer is about your money.");
    await expect(page.getByTestId("home-today-title")).toHaveText("Worth knowing today");
    await expect(page.getByTestId("home-today-card").first()).toContainText("Fixture headline one for the test suite");
    const ctx = page.getByTestId("evidence-context");
    await expect(page.getByTestId("context-no-portfolio")).toContainText("No portfolio connected yet.");
    await expect(page.getByTestId("context-portfolio-value")).toHaveCount(0);
    await expect(ctx).not.toContainText("₹0");
    await expect(page.getByTestId("rail-user")).toContainText("No portfolio connected");
    await page.getByTestId("home-connect-banner").getByRole("button", { name: "Connect" }).click();
    await expect(page).toHaveURL(/\/v5\/app\/onboarding$/);
    // The ask box's "+" goes to where a statement is imported.
    await page.getByTestId("composer-attach").click();
    await expect(page).toHaveURL(/\/v5\/app\/page\/brokers$/);
    await expect(page.getByTestId("screen-page-brokers")).toBeVisible();
  });

  test("TC-09 evidence panel: context on home, tools and sources in a thread, and the toggle", async ({ page }) => {
    await setup(page);
    const withWidget: Frame[] = [
      ...RISK_FRAMES.slice(0, 6),
      { type: "widget", widget_type: "insight_card", data: {}, title: "Insight", freshness: { state: "cached", last_updated: new Date().toISOString(), source: ["NIDP", "portfolio_holdings"] }, agent: { id: "risk_advisor", confidence: 85 } },
      ...RISK_FRAMES.slice(6),
    ];
    await mockChat(page, { frames: withWidget });
    await page.goto(APP);

    // Home — holdings-enriched.json totals: value_rs 10306772.4, pnl_rs 1899275.8, pnl_pct 22.59, 111 holdings.
    await expect(page.getByTestId("context-portfolio-value")).toHaveText("₹1,03,06,772");
    await expect(page.getByTestId("context-portfolio-gain")).toContainText("+₹18,99,276 (+22.6%)");
    await expect(page.getByTestId("evidence-context")).toContainText("111 holdings");
    // Allocation by type, worked out from the fixture's holdings (value by asset_type):
    // mutual funds 80.4%, equity 17.1% — the split the dashboard's portfolio view shows.
    await expect(page.getByTestId("context-mix")).toContainText("Mutual funds 80%");
    await expect(page.getByTestId("context-mix")).toContainText("Equity (stocks) 17%");
    await expect(page.getByTestId("evidence-context")).toContainText("Moderately Aggressive"); // risk-profile.json

    await page.getByTestId("evidence-toggle").click();
    await expect(page.getByTestId("copilot-evidence")).toHaveCount(0);
    await page.getByTestId("evidence-toggle").click();
    await expect(page.getByTestId("copilot-evidence")).toBeVisible();

    // Thread — the same tools the stream reported, and the widget's source tags.
    await askFromBox(page, "How risky is my portfolio?");
    await expect(page.getByTestId("thread-turn")).toHaveAttribute("data-state", "saved");
    const tools = page.getByTestId("evidence-tool");
    await expect(tools).toHaveCount(2);
    await expect(tools.nth(0)).toContainText("get_portfolio_holdings");
    await page.getByTestId("evidence-tab-sources").click();
    await expect(page.getByTestId("evidence-source")).toHaveCount(2);
    await expect(page.getByTestId("evidence-source").nth(1)).toContainText("Portfolio holdings");
    await page.getByTestId("evidence-tab-method").click();
    await expect(page.getByTestId("evidence-thread")).toContainText("Risk Advisor");
    await expect(page.getByTestId("evidence-thread")).toContainText("92%");
  });

  test("TC-10 ask-box suggestions: ranked prompts, completions, keyboard", async ({ page }) => {
    await setup(page);
    const chat = await mockChat(page);
    await page.goto(APP);
    const input = page.getByTestId("composer-input");
    await input.click();
    const list = page.getByTestId("composer-suggest");
    await expect(list).toBeVisible();
    await expect(list).toContainText("Suggested for you");
    await expect(page.getByTestId("composer-persona")).toContainText("Mutual fund investor"); // suggested-prompts.json persona
    await expect(page.getByTestId("composer-persona")).toContainText("Equity 93%");
    const items = page.getByTestId("composer-suggest-item");
    await expect(items).toHaveCount(5);
    await expect(items.nth(0)).toContainText("Do I have too many mutual funds?");

    await input.press("Escape");
    await expect(list).toHaveCount(0);

    await input.fill("over");
    await expect(list).toContainText("Completions");
    await expect(items).toHaveCount(1);
    await expect(items.nth(0)).toContainText("Which of my funds overlap the most?");
    await input.press("ArrowDown");
    await expect(items.nth(0)).toHaveAttribute("aria-selected", "true");
    await input.press("Enter");
    await expect.poll(() => chat.streams.length).toBe(1);
    expect(chat.streams[0].message).toBe("Which of my funds overlap the most?");
  });

  test("TC-11 mode pill swaps the tools; Advisor only for an advisory workspace", async ({ page }) => {
    await setup(page);
    await mockChat(page);
    await page.goto(APP);
    const rail = page.getByTestId("copilot-rail");
    const pill = page.getByTestId("mode-pill");
    await expect(pill).toContainText("Investor");
    await expect(rail.getByRole("button", { name: "Portfolio analysis" })).toBeVisible();
    // The original v5 dashboards are tools in Investor mode.
    for (const name of ["Risk", "Goals", "Tax"]) await expect(rail.getByRole("button", { name, exact: true })).toBeVisible();
    await pill.click();
    await expect(pill).toContainText("Trader");
    await expect(page).toHaveURL(/\/v5\/app\/trader$/);
    await expect(rail.getByRole("button", { name: /Trader desk/ })).toBeVisible();
    await expect(rail.getByRole("button", { name: /Options lab/ })).toBeVisible();
    await expect(rail.getByRole("button", { name: "Portfolio analysis" })).toHaveCount(0);
    await pill.click(); // not an advisory workspace → back to Investor
    await expect(pill).toContainText("Investor");
    await expect(page).toHaveURL(/\/v5\/app$/);

    // Advisory workspace → Advisor becomes the third mode.
    await page.route("**/api/auth/me", (route) => route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({ user_id: "u_adv", email: "advisor@example.test", name: "Fixture Advisor", is_admin: false, onboarding_completed: true, workspace_type: "ADVISORY" }),
    }));
    await page.reload();
    await expect(pill).toContainText("Investor");
    await pill.click();
    await pill.click();
    await expect(pill).toContainText("Advisor");
    await expect(page).toHaveURL(/\/v5\/app\/advisor$/);
    // Advisor mode lists the original v5 advisor tools.
    await expect(rail.getByRole("button", { name: "Advisor workspace" })).toBeVisible();
    await rail.getByRole("button", { name: "Client 360" }).click();
    await expect(page).toHaveURL(/\/v5\/app\/advisor\/client-360$/);
    await expect(page.getByTestId("screen-advisor-client-360")).toBeVisible();
  });

  test("TC-12 internal pages are for admins only", async ({ page }) => {
    await setup(page); // user-profile-onboarded.json is an admin
    await mockChat(page);
    await page.goto(APP);
    await expect(page.getByTestId("rail-internal")).toContainText("Feed health");
    await page.getByTestId("rail-internal").getByRole("button", { name: "Feed health" }).click();
    await expect(page).toHaveURL(/\/v5\/app\/ops\/feeds$/);
    await expect(page.getByTestId("screen-ops-feeds")).toBeVisible();

    await page.route("**/api/auth/me", (route) => route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({ user_id: "u_plain", email: "user@example.test", name: "Fixture User", is_admin: false, onboarding_completed: true }),
    }));
    await page.goto(`${APP}/ops/feeds`);
    await expect(page).toHaveURL(/\/v5\/app$/);
    await expect(page.getByTestId("copilot-rail")).toBeVisible();
    await expect(page.getByTestId("rail-internal")).toHaveCount(0);
    await page.goto(`${APP}/builder`);
    await expect(page).toHaveURL(/\/v5\/app$/);
  });

  test("TC-13 a signed-out visitor is sent to login", async ({ page }) => {
    await mockAuthAs(page, "user-profile-onboarded.json");
    await mock401(page, "**/api/auth/me");
    await page.goto(APP);
    await expect(page).toHaveURL(/\/v5\/login$/);
  });

  test("a user who has not finished onboarding lands on the onboarding screen", async ({ page }) => {
    await setup(page);
    await mockChat(page);
    await mockSingleRoute(page, "**/api/auth/me", "user-profile.json"); // onboarding_completed: false
    await page.goto(APP);
    await expect(page).toHaveURL(/\/v5\/app\/onboarding$/);
    await expect(page.getByTestId("screen-onboarding")).toBeVisible();
  });

  test("an unknown view falls back to home", async ({ page }) => {
    await setup(page);
    await mockChat(page);
    await page.goto(`${APP}/no-such-view`);
    await expect(page).toHaveURL(/\/v5\/app$/);
    await expect(page.getByTestId("home-headline")).toBeVisible();
  });
});

test.describe("Copilot app — phone (390×844)", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  const noSidewaysScroll = async (page: Page) => {
    const m = await page.evaluate(() => {
      const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
      return {
        doc: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        scroll: sc ? sc.scrollWidth - sc.clientWidth : 0,
      };
    });
    expect(m.doc, "page scrolls sideways").toBeLessThanOrEqual(1);
    expect(m.scroll, "content area scrolls sideways").toBeLessThanOrEqual(1);
  };

  test("TC-14 no rail; the menu opens a drawer that navigates and closes", async ({ page }) => {
    const errors = trackPageErrors(page);
    await setup(page);
    await mockChat(page);
    await page.goto(APP);
    await expect(page.getByTestId("compact-bar")).toBeVisible();
    await expect(page.getByTestId("copilot-rail")).toHaveCount(0);
    await expect(page.getByTestId("home-headline")).toBeVisible();
    await expect(page.getByTestId("home-today-card")).toHaveCount(6);
    await noSidewaysScroll(page);

    await page.getByTestId("menu-button").click();
    const rail = page.getByTestId("copilot-rail");
    await expect(rail).toBeVisible();
    await rail.getByRole("button", { name: "Markets", exact: true }).click();
    await expect(page).toHaveURL(/\/v5\/app\/tool\/markets$/);
    await expect(page.getByTestId("copilot-rail")).toHaveCount(0);
    await expect(page.getByTestId("screen-tool-markets")).toBeVisible();

    // The scrim also closes it.
    await page.getByTestId("menu-button").click();
    await expect(page.getByTestId("copilot-rail")).toBeVisible();
    await page.getByTestId("rail-scrim").click({ position: { x: 370, y: 400 } });
    await expect(page.getByTestId("copilot-rail")).toHaveCount(0);
    expect(errors).toEqual([]);
  });

  test("TC-15 evidence opens as a bottom sheet and closes", async ({ page }) => {
    await setup(page);
    await mockChat(page);
    await page.goto(APP);
    await expect(page.getByTestId("copilot-evidence")).toHaveCount(0);
    await page.getByTestId("evidence-toggle").click();
    const sheet = page.getByTestId("copilot-evidence");
    await expect(sheet).toBeVisible();
    await expect(page.getByTestId("context-portfolio-value")).toHaveText("₹1,03,06,772");
    const box = await sheet.boundingBox();
    expect(box?.width).toBe(390);
    expect(box?.y ?? 0).toBeGreaterThan(150); // starts part-way down the screen
    await page.getByTestId("evidence-close").click();
    await expect(page.getByTestId("copilot-evidence")).toHaveCount(0);
  });

  test("TC-16 the ask flow works and the ask box stays on screen", async ({ page }) => {
    await setup(page);
    const chat = await mockChat(page);
    await page.goto(APP);
    await expect(page.getByTestId("composer-input")).toBeInViewport();
    await askFromBox(page, "How risky is my portfolio?");
    await expect(page).toHaveURL(/\/v5\/app\/t\/new1$/);
    await expect.poll(() => chat.streams.length).toBe(1);
    await expect(page.getByTestId("answer-class")).toHaveText("Personalised research");
    await expect(page.getByTestId("answer-trace-label")).toContainText("Done · 2 tools");
    await expect(page.getByTestId("answer-text")).toHaveText("Your portfolio is moderately risky.");
    await expect(page.getByTestId("answer-followups").getByRole("button")).toHaveCount(2);
    await expect(page.getByTestId("composer-input")).toBeInViewport();
    await expect(page.getByTestId("thread-bar")).toHaveCount(0); // phone has no thread bar
    await noSidewaysScroll(page);
  });
});
