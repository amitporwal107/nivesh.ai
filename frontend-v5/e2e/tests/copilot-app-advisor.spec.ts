/**
 * One-screen Copilot app (/v5/app) — Advisor mode: the Client book, Client 360,
 * the advisor workspace mount and the SIP board.
 *
 * Mocked APIs, production build — see pw.copilot-app.config.ts.
 *
 * MOCK — not real data: every response is a fixture (e2e/fixtures/copilot-advisor-*.json)
 * or an inline payload in the real response shape, with synthetic values. The
 * source handler is named beside each. Expected values are worked out from the
 * payload, not copied from the screen.
 *
 * The SIP board is a new screen. Its tests run only once "advisor/sip-board" is
 * in the screen registry (src/pages/CopilotApp/screens/index.ts); until then
 * they are reported as skipped.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const APP = "/v5/app";
const FX = path.join(process.cwd(), "e2e", "fixtures");
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(FX, name), "utf-8"));

const REGISTRY = fs.readFileSync(path.join(process.cwd(), "src", "pages", "CopilotApp", "screens", "index.ts"), "utf-8");
const NAV = fs.readFileSync(path.join(process.cwd(), "src", "pages", "CopilotApp", "lib", "views.ts"), "utf-8");
const SIP_BOARD_REGISTERED = /["']advisor\/sip-board["']\s*:/.test(REGISTRY);
const SIP_BOARD_IN_NAV = /view:\s*["']advisor\/sip-board["']/.test(NAV);

const ADVISOR_ME = { user_id: "u_adv", email: "advisor@example.test", name: "Fixture Advisor", is_admin: false, onboarding_completed: true, workspace_type: "ADVISORY" };

const BOOK = load("copilot-advisor-book.json");
const CLIENT = load("copilot-advisor-client.json");
const CLIENT_EMPTY = load("copilot-advisor-client-empty.json");
const SIPS = load("copilot-advisor-sips.json");

interface ClientData {
  attention: unknown;
  trend: unknown;
  tax: unknown;
  notes: unknown;
  snapshots: unknown;
  uploads: unknown;
  invites: unknown;
}

const fulfil = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

const json = (page: Page, pattern: string | RegExp, body: unknown, status = 200) =>
  page.route(pattern, (route) => fulfil(route, body, status));

/** The per-client endpoints Client 360 reads, keyed as in the fixture. */
const CLIENT_ROUTES: Array<[keyof ClientData, RegExp]> = [
  ["attention", /\/api\/mfd\/profiles\/[^/]+\/needs-attention/],
  ["trend", /\/api\/mfd\/profiles\/[^/]+\/portfolio-trend/],
  ["tax", /\/api\/mfd\/profiles\/[^/]+\/tax-summary/],
  ["notes", /\/api\/mfd\/profiles\/[^/]+\/notes/],
  ["snapshots", /\/api\/portfolio\/cas-snapshots/],
  ["uploads", /\/api\/mfd\/profiles\/[^/]+\/cas-uploads/],
  ["invites", /\/api\/mfd\/profiles\/[^/]+\/cas-invites/],
];

/** Answers every per-client read from `data`. Returns the request URLs it saw. */
async function mockClient(page: Page, data: ClientData): Promise<string[]> {
  const seen: string[] = [];
  for (const [key, re] of CLIENT_ROUTES) {
    await page.route(re, (route) => {
      seen.push(route.request().url());
      return fulfil(route, data[key]);
    });
  }
  return seen;
}

/** An advisory workspace with the fixture book. Shapes: backend/routes/mfd.py, advisor_v4.py. */
async function advisor(page: Page, opts: { me?: Record<string, unknown>; book?: unknown } = {}) {
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (route) => fulfil(route, []));
  await json(page, "**/api/auth/me", opts.me ?? ADVISOR_ME);
  await json(page, /\/api\/mfd\/profiles(\?[^/]*)?$/, opts.book ?? BOOK);
  await json(page, /\/api\/advisor\/sip-board\/summary/, SIPS.summary);
  await json(page, /\/api\/advisor\/sip-board(\?[^/]*)?$/, SIPS.board);
}

/** The four insight cards on the original advisor workspace. Shapes: backend/routes/advisor.py. */
async function mockWorkspaceCards(page: Page) {
  await json(page, /\/api\/advisor\/today/, { rows: [], total_clients: 3, shown: 0, buckets: { high: 0, medium: 0, low: 0 }, headline: "Fixture headline: calls" });
  await json(page, /\/api\/advisor\/aum/, { rows: [], total_aum_rs: 0, aggregate_mom_pct: null, headline: "Fixture headline: AUM" });
  await json(page, /\/api\/advisor\/underperformers/, { rows: [], benchmark: "nifty_50", benchmark_return_pct: 12.5, gap_threshold_pct: 5, headline: "Fixture headline: benchmark" });
  await json(page, /\/api\/advisor\/rebalance/, { rows: [], gap_threshold_pp: 10, headline: "Fixture headline: drift" });
}

/** Captures what a screen hands to the Copilot. Returns the sent messages. */
async function mockAsk(page: Page): Promise<string[]> {
  const sent: string[] = [];
  await page.route("**/api/chat/sessions", (route) =>
    route.request().method() === "POST" ? fulfil(route, { session_id: "asked1" }) : fulfil(route, []));
  await page.route("**/api/chat/messages*", (route) => fulfil(route, []));
  await page.route("**/api/chat/stream", (route) => {
    sent.push((route.request().postDataJSON() as { message: string }).message);
    return route.fulfill({ status: 200, contentType: "text/event-stream", body: `data: ${JSON.stringify({ type: "done", content: "ok" })}\n\n` });
  });
  return sent;
}

/** Sideways overflow of the page and of the shell's scroll area, in px. */
async function overflow(page: Page) {
  return page.evaluate(() => {
    const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
    return {
      doc: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      scroll: sc ? sc.scrollWidth - sc.clientWidth : 0,
    };
  });
}

const icon = '[data-testid="entity-icon"]';

// ─────────────────────────────────────────────────────────────────────────
// Client book
// ─────────────────────────────────────────────────────────────────────────

test.describe("Advisor · Client book", () => {
  test("AD-01 book figures, both ways into a client, and the two not-connected blocks", async ({ page }) => {
    await advisor(page);
    await page.goto(`${APP}/advisor`);
    await expect(page.getByTestId("advisor-firm")).toHaveText("Advisor · Fixture Advisory LLP · ARN-FIXTURE-0001");
    // Three clients; the SELF profile is not one. AUM 62,00,000 + 5,20,00,000 + 25,00,000 = 6,07,00,000.
    await expect(page.getByTestId("advisor-tile-clients")).toHaveText("3");
    await expect(page.getByTestId("advisor-tile-aum")).toHaveText("₹6.07 Cr");
    // Clients One (rebalance) and Three (pending recommendation) need action; Two is "All good".
    await expect(page.getByTestId("advisor-attention-count")).toHaveText("2");
    await expect(page.getByTestId("advisor-queue-name")).toHaveText(["Test Client One", "Test Client Three"]);
    // SIP tile ← sip-board/summary: 5 on record, 1 failed, 1 mandate.
    await expect(page.getByTestId("advisor-tile-sips")).toHaveText("5");
    await expect(page.getByTestId("advisor-tile-sips-sub")).toHaveText("1 failed · 1 mandates expiring in 90 days");
    // Roster, weakest health first. Health = round(0.6 × quality + 0.4 × (100 − risk)): 36, 59, 75.
    await expect(page.getByTestId("advisor-client-row")).toHaveText(["Test Client One", "Test Client Three", "Test Client Two"]);
    await expect(page.getByTestId("advisor-client-health")).toHaveText(["36", "59", "75"]);
    // People get no icon.
    await expect(page.getByTestId("screen-advisor").locator(icon)).toHaveCount(0);

    // Nothing stores model portfolios or report drafts: both blocks say so, and the build list is for admins only.
    await expect(page.getByTestId("advisor-models-not-connected")).toContainText("Not connected yet");
    await expect(page.getByTestId("advisor-reports-not-connected")).toContainText("Not connected yet");
    await expect(page.getByTestId("not-connected-needs")).toHaveCount(0);

    // A roster row's "Client 360" reads that client without switching to them.
    await page.getByTestId("advisor-client-360").nth(2).click();
    await expect(page).toHaveURL(/\/v5\/app\/advisor\/client-360\?client=p-2$/);
    await expect(page.getByTestId("client360-name")).toHaveText("Test Client Two");
    expect(await page.evaluate(() => localStorage.getItem("nivesh.impersonation") ?? "")).not.toContain("p-2");

    // The queue's "Client 360" does the same for the client at the top of the queue.
    await page.goto(`${APP}/advisor`);
    await page.getByTestId("advisor-queue-360").first().click();
    await expect(page).toHaveURL(/\/v5\/app\/advisor\/client-360\?client=p-1$/);
    await expect(page.getByTestId("client360-name")).toHaveText("Test Client One");
  });

  test("AD-02 an admin sees what each not-connected block needs", async ({ page }) => {
    await advisor(page, { me: { ...ADVISOR_ME, is_admin: true } });
    await page.goto(`${APP}/advisor`);
    await expect(page.getByTestId("advisor-models-not-connected").getByTestId("not-connected-needs")).toContainText("model portfolios");
    await expect(page.getByTestId("advisor-reports-not-connected").getByTestId("not-connected-needs")).toContainText("review-pack/generate");
  });

  test("AD-03 a book with no clients: the way to add one stays inside the shell", async ({ page }) => {
    // What staging returns for the test account: an advisory workspace with only its own SELF profile.
    const self = BOOK.profiles.filter((p: { type: string }) => p.type === "SELF");
    await advisor(page, { book: { ...BOOK, profiles: self, count: 1 } });
    await mockWorkspaceCards(page);
    await mockClient(page, CLIENT_EMPTY);
    await page.goto(`${APP}/advisor`);
    await expect(page.getByTestId("advisor-empty")).toContainText("No clients in your book yet");
    await expect(page.getByTestId("advisor-tile-clients")).toHaveCount(0);

    await page.getByTestId("advisor-empty-own-360").click();
    await expect(page).toHaveURL(/\/v5\/app\/advisor\/client-360\?client=p-self$/);
    await expect(page.getByTestId("client360-name")).toHaveText("Fixture Advisor");
    await expect(page.getByTestId("screen-advisor-client-360")).toContainText("Your own portfolio");

    await page.goto(`${APP}/advisor`);
    await page.getByTestId("advisor-empty-add").click();
    await expect(page).toHaveURL(/\/v5\/app\/advisor\/workspace$/);
    await expect(page.getByTestId("advisor-dashboard")).toBeVisible();
  });

  test("AD-04 the SIP tile prints no figure when its request fails or is not a SIP summary", async ({ page }) => {
    await advisor(page);
    let mode: "fail" | "empty-object" | "ok" = "fail";
    await page.route(/\/api\/advisor\/sip-board\/summary/, (route) =>
      mode === "fail" ? fulfil(route, { detail: "boom" }, 500) : mode === "empty-object" ? fulfil(route, {}) : fulfil(route, SIPS.summary));
    await page.goto(`${APP}/advisor`);
    const retry = page.getByTestId("advisor-tile-sips-retry");
    await expect(retry).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("advisor-tile-sips")).toHaveCount(0);
    // The rest of the book is unaffected.
    await expect(page.getByTestId("advisor-tile-clients")).toHaveText("3");

    mode = "empty-object"; // 200 {} must not read as "0 SIPs"
    await page.reload();
    await expect(retry).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("advisor-tile-sips")).toHaveCount(0);

    mode = "ok";
    await retry.click();
    await expect(page.getByTestId("advisor-tile-sips")).toHaveText("5");
  });

  test("AD-05 an account that is not an advisor is told so, and is offered the workspace inside the shell", async ({ page }) => {
    await mockApi(page, "populated"); // user-profile-onboarded.json: not an advisory workspace
    await page.route("**/api/chat/sessions", (route) => fulfil(route, []));
    await json(page, /\/api\/mfd\/profiles(\?[^/]*)?$/, { workspace: { workspace_id: "ws-ind", type: "INDIVIDUAL" }, profiles: [], count: 0 });
    for (const view of ["advisor", "advisor/client-360"]) {
      await page.goto(`${APP}/${view}`);
      await expect(page.getByTestId("advisor-not-advisor"), view).toBeVisible();
    }
    await page.getByTestId("advisor-open-workspace").click();
    await expect(page).toHaveURL(/\/v5\/app\/advisor\/workspace$/);
    // The original page's own "Switch to Advisor mode" card, mounted as it is.
    await expect(page.getByTestId("advisor-upgrade-card")).toBeVisible();
  });
});

// ─────────────────────────────────────────────────────────────────────────
// Client 360
// ─────────────────────────────────────────────────────────────────────────

test.describe("Advisor · Client 360", () => {
  test("AD-06 shows the chosen client's data in every block, with fund house and company icons", async ({ page }) => {
    await advisor(page);
    const seen = await mockClient(page, CLIENT);
    await page.goto(`${APP}/advisor/client-360?client=p-2`);
    const screen = page.getByTestId("screen-advisor-client-360");

    // Who: scores from the book (quality 78, risk 30 → health 75); AUM is the entered figure (no holdings value).
    await expect(page.getByTestId("client360-name")).toHaveText("Test Client Two");
    await expect(page.getByTestId("client360-health")).toHaveText("75");
    await expect(page.getByTestId("client360-quality")).toHaveText("78");
    await expect(page.getByTestId("client360-risk")).toHaveText("30");
    await expect(page.getByTestId("client360-aum")).toHaveText("₹25.00 L");
    await expect(screen).toContainText("The AUM you entered");
    await expect(page.getByTestId("client360-issue")).toHaveText("Healthy");
    await expect(page.getByTestId("client360-reason")).toHaveText(["Stable portfolio, no urgent action"]);

    // Needs attention ← needs-attention: two items; a scheme name gets its fund house icon, "Action needed" none.
    const attention = page.getByTestId("client360-attention-row");
    await expect(attention).toHaveCount(2);
    await expect(attention.nth(0)).toContainText("HDFC Flexi Cap Fund - Direct Growth");
    await expect(attention.nth(0)).toContainText("Concentration · More than 30% of the portfolio is in one fund");
    await expect(attention.nth(0)).toContainText("To discuss");
    await expect(attention.nth(0).locator(icon)).toHaveAttribute("data-kind", "fund-house");
    await expect(attention.nth(0).locator(icon)).toHaveAttribute("data-key", "HDFC");
    await expect(attention.nth(1)).toContainText("Action needed");
    await expect(attention.nth(1)).toContainText("Portfolio");
    await expect(attention.nth(1)).toContainText("Discussed");
    await expect(attention.nth(1).locator(icon)).toHaveCount(0);

    // Value ← portfolio-trend: 40,00,000 invested, 46,00,000 now, +6,00,000 (+15%).
    await expect(page.getByTestId("client360-invested")).toHaveText("₹40.00 L");
    await expect(page.getByTestId("client360-current")).toHaveText("₹46.00 L");
    await expect(page.getByTestId("client360-change")).toHaveText("+₹6.00 L");
    await expect(page.getByTestId("client360-value")).toContainText("+15.0% on the amount invested");
    const buys = page.getByTestId("client360-buy-name");
    await expect(buys).toHaveCount(3);
    await expect(buys.nth(0).locator(icon)).toHaveAttribute("data-kind", "fund-house"); // a mutual fund
    await expect(buys.nth(0).locator(icon)).toHaveAttribute("data-key", "Parag Parikh");
    await expect(buys.nth(1).locator(icon)).toHaveAttribute("data-kind", "stock"); // a stock
    await expect(buys.nth(2).locator(icon)).toHaveCount(0); // gold: neither

    // Unrealised gains ← tax-summary: +6,00,000; short-term 1,50,000; long-term 4,00,000; 1 undated lot 50,000; tax 70,070.
    await expect(page.getByTestId("client360-unrealised")).toHaveText("+₹6.00 L");
    await expect(page.getByTestId("client360-stcg")).toHaveText("+₹1.50 L");
    await expect(page.getByTestId("client360-ltcg")).toHaveText("+₹4.00 L");
    await expect(page.getByTestId("client360-undated")).toHaveText("+₹50.0k");
    await expect(page.getByTestId("client360-est-tax")).toHaveText("₹70.1k");
    await expect(page.getByTestId("client360-tax-coverage")).toHaveCount(0); // lot coverage is "good"
    await expect(page.getByTestId("client360-tax")).toContainText("equity short-term 20% (no indexation)");
    await expect(page.getByTestId("client360-tax")).toContainText("debt at an assumed 30% slab");
    const positions = page.getByTestId("client360-position-name");
    await expect(positions).toHaveCount(3);
    await expect(positions.nth(0).locator(icon)).toHaveAttribute("data-key", "HDFC");
    await expect(positions.nth(1).locator(icon)).toHaveAttribute("data-kind", "stock");
    await expect(page.getByTestId("client360-tax")).toContainText("Long-term · equity");
    await expect(page.getByTestId("client360-tax")).toContainText("No purchase date");

    // Portfolio history ← cas-snapshots: 7 on file, the latest 6 listed until "Show all".
    await expect(page.getByTestId("client360-history-date")).toHaveCount(6);
    await expect(page.getByTestId("client360-history")).toContainText("Statement upload");
    await expect(page.getByTestId("client360-history")).toContainText("Daily snapshot");
    await page.getByRole("button", { name: "Show all 7" }).click();
    await expect(page.getByTestId("client360-history-date")).toHaveCount(7);
    await expect(page.getByTestId("client360-history")).toContainText("−2.5%");

    // Statement requests ← cas-invites; the link's token is never printed.
    const requests = page.getByTestId("client360-request-row");
    await expect(requests).toHaveCount(2);
    await expect(requests.nth(0)).toContainText("Waiting for the client");
    await expect(requests.nth(1)).toContainText("Statements received");
    await expect(requests.nth(1)).toContainText("1 file received");
    await expect(screen).not.toContainText("tok_fixture");
    await expect(screen).not.toContainText("cas-connect");

    // Statements they shared ← cas-uploads: one readable and downloadable, one that failed.
    const shared = page.getByTestId("client360-shared-row");
    await expect(shared).toHaveCount(2);
    await expect(shared.nth(0)).toContainText("fixture_statement_detailed.pdf");
    await expect(shared.nth(0)).toContainText("Detailed · with transactions");
    await expect(shared.nth(0)).toContainText("14 holdings read");
    await expect(shared.nth(0).getByRole("button", { name: "Open fixture_statement_detailed.pdf" })).toBeVisible();
    await expect(shared.nth(1)).toContainText("Could not be read: Wrong password");
    await expect(shared.nth(1).getByRole("button")).toHaveCount(0);

    // Notes ← notes.
    await expect(page.getByTestId("client360-note")).toHaveText("Synthetic note: prefers a call before any switch.");
    await expect(page.getByTestId("client360-note-facts")).toContainText("SIP ₹25,000 · monthly");
    await expect(page.getByTestId("client360-note-facts")).toContainText("Prefers whatsapp");

    // What cannot be done here yet is said, not hidden.
    await expect(page.getByTestId("client360-actions-not-connected")).toContainText("Not connected yet");

    // Every per-client read named the chosen client.
    expect(seen.length).toBeGreaterThanOrEqual(7);
    for (const url of seen) expect(url, url).toMatch(/\/profiles\/p-2\/|profile_id=p-2/);

    // The picker moves to another client and the address follows. Client Three: ₹5.20 Cr → UHNI.
    await page.getByTestId("client360-picker").selectOption("p-3");
    await expect(page).toHaveURL(/client=p-3$/);
    await expect(page.getByTestId("client360-name")).toHaveText("Test Client Three");
    await expect(page.getByTestId("client360-health")).toHaveText("59");
    await expect(page.getByTestId("client360-aum")).toHaveText("₹5.20 Cr");
    await expect(screen).toContainText("UHNI");
    await expect.poll(() => seen.some((u) => /\/profiles\/p-3\//.test(u))).toBe(true);
  });

  test("AD-07 with no client named in the address, the first client in the book is shown", async ({ page }) => {
    await advisor(page);
    await mockClient(page, CLIENT);
    await page.goto(`${APP}/advisor/client-360`);
    await expect(page.getByTestId("client360-name")).toHaveText("Test Client One"); // highest priority
    await expect(page.getByTestId("client360-picker")).toHaveValue("p-1");
    await expect(page.getByTestId("client360-health")).toHaveText("36");
  });

  test("AD-08 a client with nothing on file: every block has its own empty state", async ({ page }) => {
    await advisor(page);
    await mockClient(page, CLIENT_EMPTY);
    await page.goto(`${APP}/advisor/client-360?client=p-2`);
    await expect(page.getByTestId("client360-attention-empty")).toBeVisible();
    await expect(page.getByTestId("client360-value-empty")).toHaveText("No holdings are on file for this client.");
    await expect(page.getByTestId("client360-tax-empty")).toHaveText("No holdings are on file for this client.");
    await expect(page.getByTestId("client360-history-empty")).toBeVisible();
    await expect(page.getByTestId("client360-requests-empty")).toBeVisible();
    await expect(page.getByTestId("client360-shared-empty")).toBeVisible();
    await expect(page.getByTestId("client360-notes-empty")).toHaveText("No note is saved for this client.");
    // No figure is invented for an empty client.
    for (const id of ["client360-invested", "client360-unrealised", "client360-est-tax", "client360-buy-name", "client360-history-date"]) {
      await expect(page.getByTestId(id), id).toHaveCount(0);
    }
  });

  test("AD-09 holdings without purchase dates: no short/long split and no tax figure are made up", async ({ page }) => {
    // What staging returns for a statement with no transaction history: every lot undated, coverage 0.
    await advisor(page);
    await mockClient(page, {
      ...CLIENT,
      trend: { ...CLIENT.trend, recent_buys: [] },
      tax: {
        ...CLIENT.tax, coverage_pct: 0, stcg_rs: 0, ltcg_rs: 0, undated_gain_rs: 600000, undated_count: 9, est_tax_if_realized_rs: 0,
        lot_coverage: { ...CLIENT.tax.lot_coverage, cas_quality: "no_data" },
      },
    });
    await page.goto(`${APP}/advisor/client-360?client=p-2`);
    await expect(page.getByTestId("client360-buys-empty")).toBeVisible();
    await expect(page.getByTestId("client360-unrealised")).toHaveText("+₹6.00 L");
    await expect(page.getByTestId("client360-stcg")).toHaveText("—");
    await expect(page.getByTestId("client360-ltcg")).toHaveText("—");
    await expect(page.getByTestId("client360-est-tax")).toHaveText("—");
    await expect(page.getByTestId("client360-undated")).toHaveText("+₹6.00 L");
    await expect(page.getByTestId("client360-tax-coverage")).toContainText("no transaction history");
  });

  test("AD-10 each block says when its request failed; the page and the other blocks stay", async ({ page }) => {
    test.setTimeout(60_000);
    await advisor(page);
    await mockClient(page, CLIENT);
    // needs-attention answers HTTP 500 on staging today; a 200 that is not the contract must fail the same way.
    let attention: "fail" | "ok" = "fail";
    await page.route(/\/api\/mfd\/profiles\/[^/]+\/needs-attention/, (route) =>
      attention === "fail" ? fulfil(route, { status: 500, error: "SYSTEM_ERROR", message: "An unexpected error occurred." }, 500) : fulfil(route, CLIENT.attention));
    await json(page, /\/api\/mfd\/profiles\/[^/]+\/portfolio-trend/, { detail: "boom" }, 500);
    await json(page, /\/api\/mfd\/profiles\/[^/]+\/tax-summary/, {}); // 200 {} — not a tax summary
    await json(page, /\/api\/portfolio\/cas-snapshots/, { detail: "forbidden" }, 403);
    await json(page, /\/api\/mfd\/profiles\/[^/]+\/cas-uploads/, { detail: "boom" }, 500);
    await json(page, /\/api\/mfd\/profiles\/[^/]+\/cas-invites/, { detail: "boom" }, 500);
    await json(page, /\/api\/mfd\/profiles\/[^/]+\/notes/, { detail: "boom" }, 500);
    await page.goto(`${APP}/advisor/client-360?client=p-2`);

    const wait = { timeout: 20_000 };
    await expect(page.getByTestId("client360-attention").getByRole("alert")).toContainText("This client’s open items didn’t load", wait);
    await expect(page.getByTestId("client360-attention-empty")).toHaveCount(0); // a failure is not "nothing flagged"
    await expect(page.getByTestId("client360-value").getByRole("alert")).toContainText("This client’s portfolio value didn’t load", wait);
    await expect(page.getByTestId("client360-tax").getByRole("alert")).toContainText("the response was not in the expected shape", wait);
    await expect(page.getByTestId("client360-history").getByRole("alert")).toContainText("this account does not have access", wait);
    await expect(page.getByTestId("client360-shared").getByRole("alert")).toContainText("didn’t load", wait);
    await expect(page.getByTestId("client360-requests").getByRole("alert")).toContainText("didn’t load", wait);
    await expect(page.getByTestId("client360-notes").getByRole("alert")).toContainText("This client’s notes didn’t load", wait);
    // The client and the scores from the book are still there, as is the shell.
    await expect(page.getByTestId("client360-name")).toHaveText("Test Client Two");
    await expect(page.getByTestId("client360-health")).toHaveText("75");
    await expect(page.getByTestId("composer-input")).toBeVisible();
    await expect(page.getByText(/^Copilot · /)).toHaveCount(0);

    // Retry on one block reloads that block.
    attention = "ok";
    await page.getByTestId("client360-attention").getByRole("button", { name: /Retry/ }).click();
    await expect(page.getByTestId("client360-attention-row")).toHaveCount(2);
  });

  test("AD-11 an address that names someone outside the book says so and offers the book's clients", async ({ page }) => {
    await advisor(page);
    await mockClient(page, CLIENT);
    await page.goto(`${APP}/advisor/client-360?client=not-in-this-book`);
    await expect(page.getByTestId("client360-unknown-client")).toContainText("That client is not in your book");
    await expect(page.getByTestId("client360-name")).toHaveCount(0);
    await page.getByTestId("client360-picker").selectOption("p-2");
    await expect(page.getByTestId("client360-name")).toHaveText("Test Client Two");
  });

  test("AD-12 Open in Copilot switches to the client and stays in the shell", async ({ page }) => {
    await advisor(page);
    await mockClient(page, CLIENT);
    await page.goto(`${APP}/advisor/client-360?client=p-2`);
    // Once open, every request carries the client's profile.
    const asClient = page.waitForRequest((r) => r.url().includes("/api/") && r.headers()["x-active-profile"] === "p-2");
    await page.getByTestId("client360-open").click();
    await asClient;
    await expect(page).toHaveURL(/\/v5\/app$/);
    await expect(page.getByTestId("home-headline")).toBeVisible();
    await expect(page.getByTestId("copilot-rail")).toBeVisible();

    // Coming back to an advisor screen while the client is open says so, and offers the way back.
    await page.goto(`${APP}/advisor/client-360?client=p-2`);
    await expect(page.getByTestId("advisor-viewing-name")).toHaveText("Test Client Two");
    await page.getByTestId("advisor-back-to-book").click();
    await expect(page.getByTestId("client360-name")).toHaveText("Test Client Two");
    expect(await page.evaluate(() => localStorage.getItem("nivesh.impersonation") ?? "")).not.toContain("p-2");
  });

  test("AD-13 the action plan button opens the client on the shell's plan screen", async ({ page }) => {
    await advisor(page);
    await mockClient(page, CLIENT);
    await page.goto(`${APP}/advisor/client-360?client=p-1`);
    await page.getByTestId("client360-open-plan").click();
    await expect(page).toHaveURL(/\/v5\/app\/page\/plan$/);
    await expect(page.getByTestId("screen-page-plan")).toBeVisible();
    expect(await page.evaluate(() => localStorage.getItem("nivesh.impersonation") ?? "")).toContain("p-1");
  });

  test("AD-14 holdings download: the file is saved; a client with no holdings is told so", async ({ page }) => {
    await advisor(page);
    await mockClient(page, CLIENT);
    // Shape: backend/routes/portfolio_export.py _stream_export (attachment) and its 404.
    const asked: string[] = [];
    await page.route(/\/api\/mfd\/profiles\/[^/]+\/holdings\/export/, (route) => {
      const url = route.request().url();
      asked.push(url);
      return url.includes("format=csv")
        ? route.fulfill({ status: 200, contentType: "text/csv; charset=utf-8", headers: { "content-disposition": 'attachment; filename="Test_Client_Two_holdings_20261013.csv"' }, body: "name,units\nSynthetic Fund,1\n" })
        : fulfil(route, { detail: "No holdings to export for this client" }, 404);
    });
    await page.goto(`${APP}/advisor/client-360?client=p-2`);
    const [download] = await Promise.all([page.waitForEvent("download"), page.getByTestId("client360-export-csv").click()]);
    expect(download.suggestedFilename()).toBe("Test_Client_Two_holdings_20261013.csv");
    expect(asked[0]).toMatch(/\/api\/mfd\/profiles\/p-2\/holdings\/export\?format=csv$/);
    await expect(page.getByTestId("client360-export-error")).toHaveCount(0);

    await page.getByTestId("client360-export-xlsx").click();
    await expect(page.getByTestId("client360-export-error")).toHaveText("This client has no holdings to download.");
    expect(asked[1]).toMatch(/format=xlsx$/);
  });

  test("AD-15 the review prompt goes to the Copilot with the client's name", async ({ page }) => {
    await advisor(page);
    await mockClient(page, CLIENT);
    const sent = await mockAsk(page);
    await page.goto(`${APP}/advisor/client-360?client=p-2`);
    await page.getByRole("button", { name: "Draft a review for Test Client Two" }).click();
    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]).toContain("my client Test Client Two");
  });
});

// ─────────────────────────────────────────────────────────────────────────
// Advisor workspace — the original v5 page, inside the shell
// ─────────────────────────────────────────────────────────────────────────

test.describe("Advisor · workspace (original page)", () => {
  test("AD-16 opening a client from the original page lands on shell screens, never the original app", async ({ page }) => {
    await advisor(page);
    await mockWorkspaceCards(page);
    await page.goto(`${APP}/advisor/workspace`);
    // The original page's own markup and figures.
    await expect(page.getByTestId("advisor-dashboard")).toBeVisible();
    await expect(page.getByTestId("advisor-greeting")).toContainText("Fixture");
    await expect(page.getByTestId("advisor-header-action-sentence")).toContainText("2 clients need action today");
    await expect(page.getByTestId("advisor-card-today")).toContainText("Fixture headline: calls");
    await expect(page.getByTestId("health-score-p-2")).toContainText("75");

    // Client Two is "All good": the original sends it to /dashboard → the Copilot home here.
    await page.getByTestId("advisor-client-name-p-2").click();
    await expect(page).toHaveURL(/\/v5\/app$/);
    await expect(page.getByTestId("home-headline")).toBeVisible();
    expect(await page.evaluate(() => localStorage.getItem("nivesh.impersonation") ?? "")).toContain("p-2");

    // Back on the workspace with a client open: it says who, and returns to the book on request.
    await page.goto(`${APP}/advisor/workspace`);
    await expect(page.getByTestId("screen-advisor-workspace")).toBeVisible();
    await expect(page.getByTestId("advisor-viewing-name")).toHaveText("Test Client Two");
    await page.getByTestId("advisor-back-to-book").click();
    await expect(page.getByTestId("advisor-dashboard")).toBeVisible();

    // Client One's action is "Rebalance": the original sends it to /plan → the shell's action plan.
    await page.getByTestId("advisor-action-btn-p-1").click();
    await expect(page).toHaveURL(/\/v5\/app\/page\/plan$/);
    await expect(page.getByTestId("screen-page-plan")).toBeVisible();
    await expect(page.getByTestId("copilot-rail")).toBeVisible();
  });

  test("AD-17 the add-client dialog is the original one", async ({ page }) => {
    await advisor(page);
    await mockWorkspaceCards(page);
    await page.goto(`${APP}/advisor/workspace`);
    await page.getByTestId("advisor-add-client-btn").click();
    await expect(page.getByTestId("add-client-dialog")).toBeVisible();
    await expect(page.getByTestId("add-client-submit")).toBeDisabled(); // no name yet
    await page.getByTestId("add-client-name").fill("Synthetic Client");
    await expect(page.getByTestId("add-client-submit")).toBeEnabled();
    await expect(page).toHaveURL(/\/v5\/app\/advisor\/workspace$/);
  });
});

// ─────────────────────────────────────────────────────────────────────────
// SIP board — runs once the screen is registered
// ─────────────────────────────────────────────────────────────────────────

test.describe("Advisor · SIP board", () => {
  test.skip(!SIP_BOARD_REGISTERED, 'add "advisor/sip-board" to SCREENS in src/pages/CopilotApp/screens/index.ts to run these');

  test("AD-18 tiles and the four queues show the board's data; a row opens that client's 360", async ({ page }) => {
    await advisor(page);
    await mockClient(page, CLIENT);
    await page.goto(`${APP}/advisor/sip-board`);
    await expect(page.getByTestId("screen-advisor-sip-board")).toContainText("October 2026");
    // sip-board/summary: 5 SIPs, ₹45,000 a month, 1 failed, 1 mandate ending.
    await expect(page.getByTestId("sip-tile-count")).toHaveText("5");
    await expect(page.getByTestId("sip-tile-inflow")).toHaveText("₹45.0k");
    await expect(page.getByTestId("sip-tile-failed")).toHaveText("1");
    await expect(page.getByTestId("sip-tile-mandates")).toHaveText("1");
    // sip-board queues: 1 failed, 1 expiring, 1 step-up, 2 on track.
    for (const [queue, n] of [["failed", "1"], ["expiring", "1"], ["step_up", "1"], ["healthy", "2"]]) {
      await expect(page.getByTestId(`sip-queue-${queue}-count`), queue).toHaveText(n);
    }
    const failed = page.getByTestId("sip-queue-failed");
    await expect(failed.getByTestId("sip-client")).toHaveText("Test Client One");
    await expect(failed.getByTestId("sip-fund")).toContainText("HDFC Flexi Cap Fund - Direct Growth");
    await expect(failed.getByTestId("sip-fund").locator(icon)).toHaveAttribute("data-kind", "fund-house");
    await expect(failed.getByTestId("sip-fund").locator(icon)).toHaveAttribute("data-key", "HDFC");
    await expect(failed.getByTestId("sip-amount")).toHaveText("₹10,000");
    // Why each SIP is in its queue: bounce reason and missed cycles, the proposed increase, the mandate's end.
    await expect(failed.getByTestId("sip-reason")).toHaveText("Insufficient balance");
    await expect(failed.getByTestId("sip-missed")).toHaveText("2");
    await expect(failed.getByTestId("sip-bounced")).toHaveText("5 Oct 2026");
    await expect(page.getByTestId("sip-queue-step_up").getByTestId("sip-detail")).toHaveText("10%");
    await expect(page.getByTestId("sip-queue-expiring").getByTestId("sip-detail")).toHaveText("30 Nov 2026");
    // Clients are people: the only icons are the funds'.
    await expect(page.getByTestId("screen-advisor-sip-board").locator(icon)).toHaveCount(5);

    await page.getByTestId("sip-queue-expiring").getByTestId("sip-client").click();
    await expect(page).toHaveURL(/\/v5\/app\/advisor\/client-360\?client=p-2$/);
    await expect(page.getByTestId("client360-name")).toHaveText("Test Client Two");
  });

  test("AD-19 an empty board says nothing is recorded; a failed or malformed answer is an error, not an empty board", async ({ page }) => {
    await advisor(page);
    let board: "empty" | "fail" | "empty-object" = "empty";
    await json(page, /\/api\/advisor\/sip-board\/summary/, SIPS.empty_summary);
    await page.route(/\/api\/advisor\/sip-board(\?[^/]*)?$/, (route) =>
      board === "empty" ? fulfil(route, SIPS.empty_board) : board === "fail" ? fulfil(route, { detail: "boom" }, 500) : fulfil(route, {}));
    await page.goto(`${APP}/advisor/sip-board`);
    // What staging returns today: four empty queues and zero totals.
    await expect(page.getByTestId("sip-empty")).toContainText("No SIPs on this board yet");
    await expect(page.getByTestId("sip-tile-count")).toHaveText("0");
    await expect(page.getByTestId("sip-queue-failed")).toHaveCount(0);

    board = "fail";
    await page.reload();
    await expect(page.getByRole("alert").filter({ hasText: "The SIP board didn’t load" })).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("sip-empty")).toHaveCount(0);

    board = "empty-object";
    await page.reload();
    await expect(page.getByRole("alert").filter({ hasText: "the response was not in the expected shape" })).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("sip-empty")).toHaveCount(0);
  });

  test("AD-20 the Client book's SIP tile links to the board", async ({ page }) => {
    await advisor(page);
    await page.goto(`${APP}/advisor`);
    await page.getByTestId("advisor-open-sip-board").click();
    await expect(page).toHaveURL(/\/v5\/app\/advisor\/sip-board$/);
    await expect(page.getByTestId("screen-advisor-sip-board")).toBeVisible();
  });

  test("AD-21 Advisor mode lists the SIP board in the rail", async ({ page }) => {
    test.skip(!SIP_BOARD_IN_NAV, 'add { view: "advisor/sip-board", label: "SIP board" } to ADVISOR_TOOLS in src/pages/CopilotApp/lib/views.ts');
    await advisor(page);
    await page.addInitScript(() => localStorage.setItem("nivesh.copilot", JSON.stringify({ state: { mode: "advisor", evidenceOpen: null }, version: 0 })));
    await page.goto(`${APP}/advisor`);
    await page.getByTestId("copilot-rail").getByRole("button", { name: "SIP board" }).click();
    await expect(page).toHaveURL(/\/v5\/app\/advisor\/sip-board$/);
    await expect(page.getByTestId("screen-advisor-sip-board")).toBeVisible();
  });
});

// ─────────────────────────────────────────────────────────────────────────
// Phone
// ─────────────────────────────────────────────────────────────────────────

test.describe("Advisor screens — phone (390×844)", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("AD-22 with a full book, no advisor screen scrolls the page sideways", async ({ page }) => {
    test.setTimeout(60_000);
    await advisor(page);
    await mockWorkspaceCards(page);
    await mockClient(page, CLIENT);
    const views: Array<[string, string, string]> = [
      ["advisor", "screen-advisor", "advisor-client-row"],
      ["advisor/client-360?client=p-2", "screen-advisor-client-360", "client360-note"],
      ["advisor/workspace", "screen-advisor-workspace", "advisor-client-table"],
    ];
    if (SIP_BOARD_REGISTERED) views.push(["advisor/sip-board", "screen-advisor-sip-board", "sip-fund"]);
    for (const [view, screenId, loadedId] of views) {
      await page.goto(`${APP}/${view}`);
      await expect(page.getByTestId(screenId), view).toBeVisible();
      await expect(page.getByTestId(loadedId).first(), `${view}: data did not render`).toBeVisible();
      await page.waitForLoadState("networkidle");
      const over = await overflow(page);
      expect.soft(over.doc, `${view}: page scrolls sideways`).toBeLessThanOrEqual(1);
      expect.soft(over.scroll, `${view}: content area scrolls sideways`).toBeLessThanOrEqual(1);
    }
    // A wide table scrolls inside its own container instead.
    await page.goto(`${APP}/advisor`);
    const table = page.getByTestId("screen-advisor").getByRole("table");
    await expect(table).toBeVisible();
    expect(await table.evaluate((el) => el.scrollWidth > el.clientWidth)).toBe(true);
  });
});
