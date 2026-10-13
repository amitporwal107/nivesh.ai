/**
 * One-screen Copilot app (/v5/app) — Broker connections, Settings and Get
 * started: every block wired to an endpoint shows what the endpoint returned,
 * its empty state and its error state; every write is shown succeeding and
 * failing.
 *
 * MOCK — not real data: every response is a fixture (e2e/fixtures/copilot-account-*.json)
 * or an inline test payload in the real response shape (the backend handler is
 * named beside each). Values are synthetic; expected values are worked out
 * from the payload, not copied from the screen.
 *
 * Two backends are covered for the broker blocks:
 *   "today"    the responses the backend in this repository gives.
 *   "planned contract, not yet on staging"
 *              the broker backend being built on another branch. Those tests
 *              prove the screens light up when its fields arrive; they prove
 *              nothing about that backend, which does not exist on staging.
 *
 * Mocked APIs, production build — see pw.copilot-app.config.ts.
 */
import { test, expect, type Page, type Request } from "@playwright/test";
import fs from "fs";
import path from "path";
import { mockApi } from "../helpers/api-mock";

const APP = "/v5/app";
const FX = path.join(process.cwd(), "e2e", "fixtures");
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(FX, name), "utf-8"));

const json = (page: Page, pattern: string | RegExp, body: unknown, status = 200) =>
  page.route(pattern, (route) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) }));

const ACCOUNTS = load("copilot-account-broker-accounts.json");
const SUPPORTED = load("copilot-account-broker-supported.json");
const HOLDINGS = load("copilot-account-holdings.json");
const CONSENTS = load("copilot-account-consents.json");
const AUDIT = load("copilot-account-audit.json");
const PREFS = load("copilot-account-preferences.json");
const SNAPSHOT = load("copilot-account-snapshot.json");
const SESSIONS = load("copilot-account-chat-sessions.json");
const ME = load("user-profile-onboarded.json"); // is_admin: true
// Planned contract, not yet on staging.
const PLANNED_SUPPORTED = load("copilot-account-broker-supported-planned.json");
const PLANNED_ACCOUNTS = load("copilot-account-broker-accounts-planned.json");

/** Every endpoint the three screens read, answered from the fixtures. A test overrides what it is about. */
async function account(page: Page) {
  await mockApi(page, "populated");
  await json(page, "**/api/onboarding/state", load("copilot-account-onboarding-state.json")); // routes/onboarding_gmail.py :: onboarding_state
  await json(page, "**/api/gmail/status", load("copilot-account-gmail-status.json"));         // routes/gmail.py :: gmail_status
  await json(page, "**/api/gmail/history", { imports: [] });                                  // routes/gmail.py :: gmail_import_history
  await json(page, "**/api/broker/accounts", ACCOUNTS);                                       // routes/broker_connect.py :: list_accounts
  await json(page, "**/api/broker/native/supported", SUPPORTED);                              // routes/broker_native.py :: list_supported
  await json(page, "**/api/portfolio/holdings", HOLDINGS);                                    // routes/portfolio.py :: get_holdings
  await json(page, "**/api/compliance/consents", CONSENTS);                                   // routes/compliance.py :: list_consents
  await json(page, "**/api/compliance/audit*", AUDIT);                                        // routes/compliance.py :: my_audit_trail
  await json(page, "**/api/user/preferences", PREFS);                                         // routes/user.py :: get_user_preferences
  await json(page, "**/api/goals/snapshot", SNAPSHOT);                                        // routes/goals.py :: get_snapshot
  await json(page, "**/api/goals", { goals: [], total: 0, on_track: 0, at_risk: 0 });         // routes/goals.py :: list_goals
  await json(page, "**/api/chat/sessions", SESSIONS);                                         // routes/chat.py :: list_chat_sessions
}

/** A failed read is retried before the screen gives up, so error blocks take a few seconds. */
const SLOW = { timeout: 15_000 };

const brokerIcon = '[data-testid="entity-icon"][data-kind="broker"]';

/** The page and the shell's content area must not scroll sideways (same check as copilot-app-screens.spec.ts). */
async function expectNoSidewaysScroll(page: Page, where: string) {
  await page.waitForLoadState("networkidle");
  const over = await page.evaluate(() => {
    const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
    return {
      doc: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      scroll: sc ? sc.scrollWidth - sc.clientWidth : 0,
    };
  });
  expect(over.doc, `${where}: page scrolls sideways`).toBeLessThanOrEqual(1);
  expect(over.scroll, `${where}: content area scrolls sideways`).toBeLessThanOrEqual(1);
}

// ── Broker connections · today's backend ─────────────────────────────────

test.describe("Broker connections — today's backend", () => {
  test.beforeEach(async ({ page }) => { await account(page); });

  test("connected accounts: broker icon, last synced, what is on file, and the read-only statement", async ({ page }) => {
    await page.goto(`${APP}/page/brokers`);
    const cards = page.getByTestId("broker-account");
    await expect(cards).toHaveCount(2);

    // Account 1: three stored rows carry its id; two have a price → 10×100 + 4×250.5 = 2,002.
    const first = cards.nth(0);
    await expect(first.getByTestId("broker-account-name")).toHaveText("Fixture Zerodha");
    await expect(first.locator(brokerIcon)).toHaveAttribute("data-key", "zerodha");
    await expect(first.getByTestId("broker-account-status")).toHaveText("Connected");
    await expect(first.getByTestId("broker-account-meta")).toContainText("Last synced");
    await expect(first.getByTestId("broker-account-meta")).toContainText("3 holdings");
    await expect(first.getByTestId("broker-fetched-count")).toHaveText("3");
    await expect(first.getByTestId("broker-fetched-value")).toHaveText("₹2,002");
    await expect(first.getByTestId("broker-account-fetched")).toContainText("1 without a price");
    // No route reads positions today, and the card says so.
    await expect(first.getByTestId("broker-account-fetched")).toContainText("Open positions are not read yet.");

    // Account 2: never read, nothing stored.
    const second = cards.nth(1);
    await expect(second.locator(brokerIcon)).toHaveAttribute("data-key", "upstox");
    await expect(second.getByTestId("broker-account-meta")).toContainText("Never synced");
    await expect(second.getByTestId("broker-account-fetched")).toContainText("Nothing read from this account is on file.");
    // Today's accounts carry no session fields: nothing about a session is shown, no reconnect.
    await expect(page.getByTestId("broker-account-session")).toHaveCount(0);
    await expect(page.getByTestId("broker-reconnect")).toHaveCount(0);

    // 2 broker accounts + the statement + Gmail.
    await expect(page.getByTestId("brokers-connected-count")).toHaveText("4");
    // The statement and Gmail sources carry an icon too, not a letter tile.
    await expect(page.getByTestId("statement-source").locator(brokerIcon)).toHaveAttribute("data-key", "cas statement");
    await expect(page.getByTestId("gmail-source").locator(brokerIcon)).toHaveAttribute("data-key", "gmail");

    await expect(page.getByTestId("broker-readonly-note")).toContainText("never places, changes or cancels an order");
    await expect(page.getByRole("cell", { name: "Open positions, funds and margins" })).toBeVisible();
    // Nothing on the screen offers to trade.
    await expect(page.getByTestId("screen-page-brokers").getByRole("button", { name: /\b(buy|sell|trade|place (an )?order|square off)\b/i })).toHaveCount(0);
  });

  test("the broker list is shown, and no sign-in is offered because the server marks no broker connectable", async ({ page }) => {
    await page.goto(`${APP}/page/brokers`);
    // Fixture: 4 with a reader (2 oauth, 1 form, 1 apikey) and 3 placeholders; none has `connectable`.
    await expect(page.getByTestId("broker-adapters-built")).toHaveText("4");
    await expect(page.getByTestId("broker-adapters-reader")).toHaveText("4");
    await expect(page.getByTestId("broker-adapters-pending")).toHaveText("3");
    await expect(page.getByTestId("broker-tile")).toHaveCount(7);
    // Every listed broker has its icon.
    await expect(page.getByTestId("screen-page-brokers").locator(`section ${brokerIcon}`)).toHaveCount(7);
    // A broker's name is never taken to mean it can be connected.
    await expect(page.locator('[data-testid^="broker-connect-"]')).toHaveCount(0);
    await expect(page.getByTestId("broker-option")).toHaveCount(0);
    // The screen says so plainly; the engineering list is for admins.
    const missing = page.getByTestId("broker-signin-missing");
    await expect(missing).toContainText("You can’t connect a broker from this app today");
    await expect(missing.getByTestId("not-connected-needs")).toBeVisible();
    await expect(page.getByTestId("screen-page-brokers")).toContainText("Signing in to a broker directly is not available yet");
  });

  test("empty: no account and no broker listed; holdings are not requested", async ({ page }) => {
    let holdingsCalls = 0;
    await json(page, "**/api/broker/accounts", { accounts: [] });
    await json(page, "**/api/broker/native/supported", { brokers: [] });
    await page.route("**/api/portfolio/holdings", (route) => { holdingsCalls += 1; return route.fulfill({ status: 200, contentType: "application/json", body: "[]" }); });
    await page.goto(`${APP}/page/brokers`);
    await expect(page.getByTestId("broker-accounts-empty")).toContainText("No broker account connected");
    await expect(page.getByTestId("broker-adapters-empty")).toContainText("The server lists no brokers");
    await expect(page.getByTestId("broker-signin-missing")).toBeVisible();
    await expect(page.getByTestId("brokers-connected-count")).toHaveText("2"); // statement + Gmail
    await page.waitForLoadState("networkidle");
    expect(holdingsCalls).toBe(0);
  });

  test("errors: accounts, broker list and stored holdings each say they did not load, and retry", async ({ page }) => {
    const down = { accounts: true, holdings: true };
    await page.route("**/api/broker/accounts", (route) => route.fulfill(down.accounts
      ? { status: 500, contentType: "application/json", body: JSON.stringify({ detail: "boom" }) }
      : { status: 200, contentType: "application/json", body: JSON.stringify(ACCOUNTS) }));
    await json(page, "**/api/broker/native/supported", { detail: "boom" }, 500);
    await page.route("**/api/portfolio/holdings", (route) => route.fulfill(down.holdings
      ? { status: 500, contentType: "application/json", body: JSON.stringify({ detail: "boom" }) }
      : { status: 200, contentType: "application/json", body: JSON.stringify(HOLDINGS) }));

    await page.goto(`${APP}/page/brokers`);
    const screen = page.getByTestId("screen-page-brokers");
    await expect(screen.getByText("Broker accounts didn’t load")).toBeVisible(SLOW);
    await expect(screen.getByText("The broker list didn’t load")).toBeVisible(SLOW);
    await expect(page.getByTestId("broker-account")).toHaveCount(0);
    await expect(page.locator('[data-testid^="broker-connect-"]')).toHaveCount(0);

    down.accounts = false;
    await screen.getByRole("alert").filter({ hasText: "Broker accounts didn’t load" }).getByRole("button", { name: /Retry/ }).click();
    const first = page.getByTestId("broker-account").nth(0);
    await expect(first.getByTestId("broker-account-fetched")).toContainText("didn’t load", SLOW);
    await expect(first.getByTestId("broker-fetched-count")).toHaveCount(0);

    down.holdings = false;
    await first.getByTestId("broker-account-fetched").getByRole("button", { name: /Retry/ }).click();
    await expect(first.getByTestId("broker-fetched-count")).toHaveText("3");
  });

  test("a body that is not the documented shape is an error, not an empty list", async ({ page }) => {
    await json(page, "**/api/broker/accounts", {});
    await json(page, "**/api/broker/native/supported", {});
    await page.goto(`${APP}/page/brokers`);
    const screen = page.getByTestId("screen-page-brokers");
    await expect(screen.getByText(/Broker accounts didn’t load/)).toBeVisible();
    await expect(screen.getByText(/The broker list didn’t load/)).toBeVisible();
    await expect(page.getByTestId("broker-accounts-empty")).toHaveCount(0);
  });

  test("Sync now: the read succeeds and the account shows the new count", async ({ page }) => {
    const calls: Request[] = [];
    let synced = false;
    await page.route("**/api/broker/accounts", (route) => {
      const body = synced
        ? { accounts: [{ ...ACCOUNTS.accounts[0], last_sync_count: 4, last_sync_at: new Date().toISOString() }, ACCOUNTS.accounts[1]] }
        : ACCOUNTS;
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    });
    // routes/broker_connect.py :: sync_broker_account
    await page.route("**/api/broker/accounts/ba_fixture00001/sync", (route) => {
      calls.push(route.request());
      synced = true;
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, count: 4, holdings: [] }) });
    });
    await page.goto(`${APP}/page/brokers`);
    const first = page.getByTestId("broker-account").nth(0);
    await first.getByTestId("broker-sync").click();
    await expect(first.getByTestId("broker-sync-result")).toHaveText("4 holdings read just now.");
    await expect(first.getByTestId("broker-account-meta")).toContainText("4 holdings");
    expect(calls.map((r) => r.method())).toEqual(["POST"]);
  });

  test("Sync now: a failed read is shown in plain words; the server's wording goes to admins only", async ({ page }) => {
    let posts = 0;
    // What today's server answers for an account signed in on the broker's page.
    await page.route("**/api/broker/accounts/ba_fixture00002/sync", (route) => {
      posts += 1;
      return route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "Stored OpenAlgo URL is missing" }) });
    });
    await page.goto(`${APP}/page/brokers`);
    const second = page.getByTestId("broker-account").nth(1);
    await second.getByTestId("broker-sync").click();
    await expect(second.getByTestId("broker-sync-error")).toContainText("Nivesh couldn’t read this account.");
    await expect(second.getByTestId("broker-admin-detail")).toContainText("Stored OpenAlgo URL is missing"); // fixture user is an admin
    await expect(second.getByTestId("broker-sync-result")).toHaveCount(0);
    expect(posts).toBe(1); // a write is not retried

    // The same failure for someone who is not an admin: plain words only, on the card and nowhere else.
    await json(page, "**/api/auth/me", { ...ME, is_admin: false });
    await page.reload();
    const again = page.getByTestId("broker-account").nth(1);
    await again.getByTestId("broker-sync").click();
    await expect(again.getByTestId("broker-sync-error")).toContainText("Nivesh couldn’t read this account.");
    await expect(page.getByTestId("broker-admin-detail")).toHaveCount(0);
    await expect(page.getByText("OpenAlgo")).toHaveCount(0);       // not in a toast either
    await expect(page.getByText("Server hiccup")).toHaveCount(0);
    await expect(page.getByTestId("not-connected-needs")).toHaveCount(0);
  });

  test("Disconnect: asks first, then the account is gone", async ({ page }) => {
    const calls: string[] = [];
    let gone = false;
    await page.route("**/api/broker/accounts", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(gone ? { accounts: [ACCOUNTS.accounts[1]] } : ACCOUNTS) }));
    // routes/broker_connect.py :: disconnect_broker
    await page.route("**/api/broker/accounts/ba_fixture00001", (route) => {
      calls.push(route.request().method());
      gone = true;
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) });
    });
    await page.goto(`${APP}/page/brokers`);
    const first = page.getByTestId("broker-account").nth(0);
    await first.getByTestId("broker-disconnect").click();
    await expect(first).toContainText("The holdings read from it are removed.");
    expect(calls).toEqual([]); // nothing sent until confirmed
    await first.getByTestId("broker-disconnect-confirm").click();
    await expect(page.getByTestId("broker-account")).toHaveCount(1);
    await expect(page.getByTestId("broker-account-name")).toHaveText("Upstox");
    await expect(page.getByTestId("brokers-connected-count")).toHaveText("3");
    expect(calls).toEqual(["DELETE"]);
  });

  test("Disconnect: a failure is shown and the account stays", async ({ page }) => {
    await json(page, "**/api/broker/accounts/ba_fixture00001", { detail: "boom" }, 500);
    await page.goto(`${APP}/page/brokers`);
    const first = page.getByTestId("broker-account").nth(0);
    await first.getByTestId("broker-disconnect").click();
    await first.getByTestId("broker-disconnect-confirm").click();
    await expect(first.getByTestId("broker-disconnect-error")).toContainText("Couldn’t disconnect this account. It is still connected.");
    await expect(page.getByTestId("broker-account")).toHaveCount(2);
    await expect(page.getByText("Server hiccup")).toHaveCount(0);
  });
});

// ── Broker connections · planned contract, not yet on staging ────────────
//
// MOCK of the broker backend being built on another branch. These tests show
// that the screens act on its fields when they arrive. They say nothing about
// whether that backend works: it is not on dev or staging.

test.describe("Broker connections — planned contract, not yet on staging", () => {
  /** The start route as planned: the fetch pre-check gets the redirect, the browser gets a stand-in broker page. */
  async function startRoute(page: Page, slug: string) {
    const hits: string[] = [];
    await page.route(`**/api/broker/native/start/${slug}*`, (route) => {
      const req = route.request();
      hits.push(`${req.resourceType()} ${new URL(req.url()).searchParams.get("return_to")}`);
      if (req.resourceType() === "document") {
        return route.fulfill({ status: 200, contentType: "text/html", body: "<title>Fixture broker</title><h1>Fixture broker sign-in page</h1>" });
      }
      return route.fulfill({ status: 302, headers: { location: "https://broker.example.test/login" } });
    });
    return hits;
  }

  test.beforeEach(async ({ page }) => {
    await account(page);
    await json(page, "**/api/broker/native/supported", PLANNED_SUPPORTED);
    await json(page, "**/api/broker/accounts", PLANNED_ACCOUNTS);
    await json(page, "**/api/portfolio/holdings", [
      { ...HOLDINGS[0], broker_account_id: "ba_fixture00011" },
      { ...HOLDINGS[1], broker_account_id: "ba_fixture00011" },
      HOLDINGS[3],
    ]);
  });

  test("planned contract, not yet on staging — Connect is offered only where the server says connectable", async ({ page }) => {
    await page.goto(`${APP}/page/brokers`);
    // Fixture: Upstox and Zerodha connectable; Angel One (keys not set), Groww and ICICI Direct are not.
    await expect(page.getByTestId("broker-adapters-connectable")).toHaveText("2");
    await expect(page.getByTestId("broker-adapters-unavailable")).toHaveText("3");
    await expect(page.locator('[data-testid^="broker-connect-"]')).toHaveCount(2);
    await expect(page.getByTestId("broker-connect-zerodha")).toHaveText("Connect");
    await expect(page.getByTestId("broker-connect-upstox")).toBeVisible();
    for (const slug of ["angel", "groww", "icicidirect"]) await expect(page.getByTestId(`broker-connect-${slug}`)).toHaveCount(0);
    // The rest are listed as not available, each with the reason the server gives.
    const tiles = page.getByTestId("broker-tile");
    await expect(tiles).toHaveCount(3);
    const expected: Array<[string, string]> = [["Angel One", "Not set up on the server yet"], ["Groww", "Not available yet"], ["ICICI Direct", "Not built yet"]];
    for (const [i, [name, note]] of expected.entries()) {
      await expect(tiles.nth(i)).toContainText(name);
      await expect(tiles.nth(i)).toContainText(note);
      await expect(tiles.nth(i).locator(brokerIcon)).toHaveCount(1);
    }
    // The "not available yet" block and today's caveats are gone once the server offers a sign-in.
    await expect(page.getByTestId("broker-signin-missing")).toHaveCount(0);
    await expect(page.getByTestId("screen-page-brokers")).toContainText("from a broker account you connect");
    await expect(page.getByRole("cell", { name: "Open positions, funds and margins" })).toHaveCount(0);
    await expect(page.getByTestId("broker-readonly-note")).toBeVisible();
  });

  test("planned contract, not yet on staging — Connect leaves for the broker's own page with a path back to this screen", async ({ page }) => {
    const hits = await startRoute(page, "zerodha");
    await page.goto(`${APP}/page/brokers`);
    await page.getByTestId("broker-connect-zerodha").click();
    const confirm = page.getByTestId("broker-connect-confirm");
    await expect(confirm).toContainText("You sign in on Zerodha’s own site");
    await expect(confirm).toContainText("Nivesh never sees your Zerodha password or one-time code");
    await expect(confirm).toContainText("Nivesh never places, changes or cancels an order");
    // No broker password, PIN or one-time code is asked for in this app.
    await expect(page.getByTestId("screen-page-brokers").locator('input[type="password"]')).toHaveCount(1); // the CAS statement field only
    await expect(confirm.locator("input")).toHaveCount(0);
    expect(hits).toEqual([]); // nothing is started until the user continues
    await page.getByTestId("broker-connect-go").click();
    await expect(page.getByRole("heading", { name: "Fixture broker sign-in page" })).toBeVisible();
    expect(new URL(page.url()).pathname).toBe("/api/broker/native/start/zerodha");
    // Asked once with fetch, then the browser is sent; both carry the same-site path of this screen.
    expect(hits).toEqual(["fetch /v5/app/page/brokers", "document /v5/app/page/brokers"]);
  });

  test("planned contract, not yet on staging — “Not now” starts nothing", async ({ page }) => {
    let hits = 0;
    await page.route("**/api/broker/native/start/**", (route) => { hits += 1; return route.fulfill({ status: 500, body: "" }); });
    await page.goto(`${APP}/page/brokers`);
    await page.getByTestId("broker-connect-upstox").click();
    await expect(page.getByTestId("broker-connect-zerodha")).toBeDisabled();
    await page.getByRole("button", { name: "Not now" }).click();
    await expect(page.getByTestId("broker-connect-confirm")).toHaveCount(0);
    await expect(page.getByTestId("broker-connect-zerodha")).toBeEnabled();
    expect(hits).toBe(0);
  });

  test("planned contract, not yet on staging — a sign-in the server cannot start is said on the screen (503, 403, and today's 500)", async ({ page }) => {
    let reply = { status: 503, detail: "BROKER_ZERODHA_API_KEY is not configured" };
    let hits = 0;
    await page.route("**/api/broker/native/start/zerodha*", (route) => {
      hits += 1;
      return route.fulfill({ status: reply.status, contentType: "application/json", body: JSON.stringify({ detail: reply.detail }) });
    });
    await page.goto(`${APP}/page/brokers`);
    await page.getByTestId("broker-connect-zerodha").click();
    await page.getByTestId("broker-connect-go").click();
    const err = page.getByTestId("broker-connect-error");
    await expect(err).toContainText("Sign-in with Zerodha isn’t set up on the server yet.");
    await expect(err.getByTestId("broker-admin-detail")).toContainText("BROKER_ZERODHA_API_KEY is not configured");
    await expect(page).toHaveURL(/\/v5\/app\/page\/brokers$/);
    expect(hits).toBe(1); // asked once; the browser was not sent to an error page

    reply = { status: 500, detail: "kiteconnect SDK not installed" };
    await page.getByTestId("broker-connect-go").click();
    await expect(err).toContainText("Sign-in with Zerodha isn’t set up on the server yet.");
    await expect(err.getByTestId("broker-admin-detail")).toContainText("kiteconnect SDK not installed");

    reply = { status: 403, detail: "feature_not_enabled" };
    await page.getByTestId("broker-connect-go").click();
    await expect(err).toContainText("Broker connections are not switched on for this account.");
    await expect(page).toHaveURL(/\/v5\/app\/page\/brokers$/);
    await expect(page.getByText("Server hiccup")).toHaveCount(0);
  });

  test("planned contract, not yet on staging — coming back: success is shown, the address is cleared, accounts are read again", async ({ page }) => {
    let accountReads = 0;
    await page.route("**/api/broker/accounts", (route) => { accountReads += 1; return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(PLANNED_ACCOUNTS) }); });
    await page.goto(`${APP}/page/brokers?broker_connected=zerodha&account_id=ba_fixture00011`);
    await expect(page.getByTestId("broker-return-connected")).toContainText("Signed in to Zerodha");
    await expect(page.getByTestId("broker-return-connected")).toContainText("press “Sync now” to read its holdings");
    await expect(page).toHaveURL(/\/v5\/app\/page\/brokers$/); // broker_connected and account_id are gone
    await expect(page.getByTestId("broker-account")).toHaveCount(2);
    await page.waitForLoadState("networkidle");
    expect(accountReads).toBeGreaterThanOrEqual(1); // read after arriving, never served from an earlier visit
    await page.getByTestId("broker-return-connected").getByRole("button", { name: "Dismiss" }).click();
    await expect(page.getByTestId("broker-return-connected")).toHaveCount(0);
  });

  test("planned contract, not yet on staging — coming back: each failure code gets its own plain sentence", async ({ page }) => {
    const sentences: Record<string, string> = {
      denied: "the sign-in was cancelled or refused at the broker",
      missing_params: "the broker did not send back a sign-in code",
      invalid_state: "the sign-in could not be matched to this account",
      state_expired: "the sign-in took more than ten minutes",
      unknown_broker: "the server does not know that broker",
      token_exchange_failed: "the broker did not accept the sign-in",
    };
    for (const [code, sentence] of Object.entries(sentences)) {
      await page.goto(`${APP}/page/brokers?broker_error=${code}`);
      const notice = page.getByTestId("broker-return-error");
      await expect(notice, code).toContainText(sentence);
      await expect(notice, code).toContainText("No account was added");
      await expect(notice, code).not.toContainText(code); // the code itself is not shown
      await expect(page).toHaveURL(/\/v5\/app\/page\/brokers$/);
    }
    // A code this app has not seen before is still reported, in words.
    await page.goto(`${APP}/page/brokers?broker_error=some_new_reason`);
    await expect(page.getByTestId("broker-return-error")).toContainText("some new reason");
  });

  test("planned contract, not yet on staging — an account signed in on the broker's page: who, until when, and what was read", async ({ page }) => {
    await page.goto(`${APP}/page/brokers`);
    const live = page.getByTestId("broker-account").nth(0);
    await expect(live.getByTestId("broker-account-status")).toHaveText("Connected");
    await expect(live.getByTestId("broker-account-meta")).toContainText("ID FX••42"); // broker_user_masked
    await expect(live.getByTestId("broker-account-session")).toContainText("Signed in until"); // session_expires_at
    await expect(live.getByTestId("broker-fetched-count")).toHaveText("2");
    await expect(live.getByTestId("broker-fetched-value")).toHaveText("₹2,002"); // 10×100 + 4×250.5
    await expect(live.getByTestId("broker-reconnect")).toHaveCount(0);
    // Nothing is claimed about positions for the planned backend.
    await expect(live.getByTestId("broker-account-fetched")).not.toContainText("positions");
  });

  test("planned contract, not yet on staging — an expired session says so and offers Reconnect, which leaves for the broker", async ({ page }) => {
    const hits = await startRoute(page, "upstox");
    await page.goto(`${APP}/page/brokers`);
    const expired = page.getByTestId("broker-account").nth(1);
    await expect(expired.getByTestId("broker-account-status")).toHaveText("Session expired");
    await expect(expired.getByTestId("broker-account-session")).toContainText("The sign-in for this account has expired. Reconnect to keep reading it.");
    await expect(expired.getByTestId("broker-account-fetched")).toContainText("Nothing read from this account is on file.");
    await expired.getByTestId("broker-reconnect").click();
    await expect(page.getByRole("heading", { name: "Fixture broker sign-in page" })).toBeVisible();
    expect(hits).toEqual(["fetch /v5/app/page/brokers", "document /v5/app/page/brokers"]);
  });

  test("planned contract, not yet on staging — Sync now reads a signed-in account, and each error code gets its own sentence", async ({ page }) => {
    let reply: { status: number; body: unknown } = { status: 200, body: { ok: true, count: 2, holdings: [] } };
    await page.route("**/api/broker/accounts/ba_fixture00011/sync", (route) => route.fulfill({ status: reply.status, contentType: "application/json", body: JSON.stringify(reply.body) }));
    await page.goto(`${APP}/page/brokers`);
    const live = page.getByTestId("broker-account").nth(0);
    await live.getByTestId("broker-sync").click();
    await expect(live.getByTestId("broker-sync-result")).toHaveText("2 holdings read just now.");

    const detail = (code: string) => ({ detail: { code, message: `fixture message for ${code}`, broker: "zerodha", account_id: "ba_fixture00011" } });
    const cases: Array<[number, string, string]> = [
      [409, "BROKER_SESSION_EXPIRED", "Your Zerodha session has ended. Sign in again, then sync."],
      [400, "BROKER_READ_NOT_SUPPORTED", "Nivesh can’t read holdings from this kind of Zerodha account yet."],
      [502, "BROKER_READ_FAILED", "Zerodha did not return your holdings. Try again in a little while."],
    ];
    for (const [status, code, sentence] of cases) {
      reply = { status, body: detail(code) };
      await live.getByTestId("broker-sync").click();
      await expect(live.getByTestId("broker-sync-error"), code).toContainText(sentence);
      await expect(live.getByTestId("broker-admin-detail"), code).toContainText(`fixture message for ${code}`);
      await expect(live.getByTestId("broker-sync-result"), code).toHaveCount(0);
    }
    reply = { status: 403, body: { detail: "feature_not_enabled" } };
    await live.getByTestId("broker-sync").click();
    await expect(live.getByTestId("broker-sync-error")).toContainText("Broker connections are not switched on for this account.");
    await expect(page.getByText("Server hiccup")).toHaveCount(0);
  });

  test("planned contract, not yet on staging — broker_hub switched off for the account: no Connect, no Reconnect, accounts still listed", async ({ page }) => {
    await json(page, "**/api/auth/me", { ...ME, features: { ...ME.features, broker_hub: false } });
    await page.goto(`${APP}/page/brokers`);
    await expect(page.getByTestId("broker-hub-off")).toContainText("Broker connections are not switched on for this account.");
    await expect(page.locator('[data-testid^="broker-connect-"]')).toHaveCount(0);
    await expect(page.getByTestId("broker-reconnect")).toHaveCount(0);
    await expect(page.getByTestId("broker-adapters-listed")).toHaveText("5");
    await expect(page.getByTestId("broker-account")).toHaveCount(2);
    await expect(page.getByTestId("broker-account").nth(0).getByTestId("broker-disconnect")).toBeEnabled();

    // The flag switched on, or missing from the profile: Connect is offered as the list says.
    await json(page, "**/api/auth/me", { ...ME, features: { ...ME.features, broker_hub: true } });
    await page.reload();
    await expect(page.locator('[data-testid^="broker-connect-"]')).toHaveCount(2);
    await expect(page.getByTestId("broker-hub-off")).toHaveCount(0);
  });
});

// ── Settings ─────────────────────────────────────────────────────────────

test.describe("Settings", () => {
  test.beforeEach(async ({ page }) => { await account(page); });

  test("Notifications: the saved choices, a change that saves, and what they do today", async ({ page }) => {
    const bodies: unknown[] = [];
    let prefs = PREFS.notifications as { push: boolean; email: boolean };
    // routes/user.py :: update_user_preferences answers with the merged preferences.
    await page.route("**/api/user/preferences", (route) => {
      if (route.request().method() === "PATCH") {
        const change = (route.request().postDataJSON() as { notifications: Partial<typeof prefs> }).notifications;
        bodies.push(route.request().postDataJSON());
        prefs = { ...prefs, ...change };
      }
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ notifications: prefs }) });
    });
    await page.goto(`${APP}/page/settings`);
    const push = page.getByTestId("settings-notify-push-switch");
    const email = page.getByTestId("settings-notify-email-switch");
    await expect(push).toHaveAttribute("aria-checked", "true");
    await expect(email).toHaveAttribute("aria-checked", "false");
    await expect(page.getByTestId("settings-notify-note")).toContainText("does not send push or email notifications yet");
    await email.click();
    await expect(email).toHaveAttribute("aria-checked", "true");
    await expect(push).toHaveAttribute("aria-checked", "true");
    expect(bodies).toEqual([{ notifications: { email: true } }]);
  });

  test("Notifications: a failed save is shown and the switch does not move", async ({ page }) => {
    await page.route("**/api/user/preferences", (route) => route.request().method() === "PATCH"
      ? route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "boom" }) })
      : route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(PREFS) }));
    await page.goto(`${APP}/page/settings`);
    await page.getByTestId("settings-notify-push-switch").click();
    await expect(page.getByTestId("settings-notify-error")).toContainText("That choice wasn’t saved");
    await expect(page.getByTestId("settings-notify-push-switch")).toHaveAttribute("aria-checked", "true");
  });

  test("About you: the stored details, and a save that sends the whole row back", async ({ page }) => {
    const puts: unknown[] = [];
    let stored = SNAPSHOT.snapshot as Record<string, unknown>;
    // routes/goals.py :: put_snapshot replaces the row and answers like get_snapshot.
    await page.route("**/api/goals/snapshot", (route) => {
      if (route.request().method() === "PUT") {
        puts.push(route.request().postDataJSON());
        stored = { ...stored, ...(route.request().postDataJSON() as Record<string, unknown>), updated_at: "2026-10-13T12:00:00+00:00" };
      }
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ snapshot: stored }) });
    });
    await page.goto(`${APP}/page/settings`);
    await expect(page.getByTestId("settings-snapshot-age")).toHaveValue("41");
    await expect(page.getByTestId("settings-snapshot-dependents")).toHaveValue("2");
    await expect(page.getByTestId("settings-snapshot-income")).toHaveValue("150000");
    await expect(page.getByTestId("settings-snapshot-expenses")).toHaveValue("90000");
    await expect(page.getByTestId("settings-snapshot-save")).toBeDisabled(); // nothing changed yet

    // An age that cannot be right is stopped before anything is sent.
    await page.getByTestId("settings-snapshot-age").fill("12");
    await page.getByTestId("settings-snapshot-save").click();
    await expect(page.getByTestId("settings-snapshot")).toContainText("Age must be a whole number between 18 and 100.");
    expect(puts).toEqual([]);

    await page.getByTestId("settings-snapshot-age").fill("41");
    await page.getByTestId("settings-snapshot-income").fill("160000");
    await page.getByTestId("settings-snapshot-save").click();
    await expect(page.getByTestId("settings-snapshot-saved")).toHaveText("Saved");
    await expect(page.getByTestId("settings-snapshot-income")).toHaveValue("160000");
    // The fields this form does not show are sent back unchanged, so the save does not reset them.
    expect(puts).toEqual([{
      dependents: 2, age: 41, monthly_income_rs: 160000, monthly_expenses_rs: 90000,
      marital_status: "married", income_growth_pct: 7.5, inflation_pct: 5.5,
      current_corpus_rs: 2500000, total_liabilities_rs: 400000, risk_profile: "aggressive",
    }]);
  });

  test("About you: nothing stored, a failed save, and a failed read", async ({ page }) => {
    const mode = { get: 200, put: 500 };
    await page.route("**/api/goals/snapshot", (route) => {
      const status = route.request().method() === "PUT" ? mode.put : mode.get;
      return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(status === 200 ? { snapshot: null } : { detail: "boom" }) });
    });
    await page.goto(`${APP}/page/settings`);
    await expect(page.getByTestId("settings-snapshot-age")).toHaveValue("");
    await expect(page.getByTestId("settings-snapshot-income")).toHaveValue("");
    await expect(page.getByTestId("settings-snapshot-dependents")).toHaveValue("0");
    await page.getByTestId("settings-snapshot-age").fill("35");
    await page.getByTestId("settings-snapshot-save").click();
    await expect(page.getByTestId("settings-snapshot-error")).toContainText("These details weren’t saved", SLOW);
    await expect(page.getByTestId("settings-snapshot-saved")).toHaveCount(0);

    mode.get = 500;
    await page.reload();
    await expect(page.getByTestId("screen-page-settings").getByText("Your details didn’t load")).toBeVisible(SLOW);
    await expect(page.getByTestId("settings-snapshot")).toHaveCount(0);
  });

  test("Privacy: consent choices on record are shown as recorded, with no switch", async ({ page }) => {
    await page.goto(`${APP}/page/settings`);
    await expect(page.getByTestId("settings-consent-title")).toHaveText(CONSENTS.consents.map((c: { title: string }) => c.title));
    // Fixture statuses: granted, pending, pending, withdrawn, pending.
    await expect(page.getByTestId("settings-consent-status")).toHaveText(["Agreed", "No choice recorded", "No choice recorded", "Withdrawn", "No choice recorded"]);
    await expect(page.getByTestId("settings-consent").nth(0)).toContainText("Required");
    await expect(page.getByTestId("settings-consent").nth(1)).toContainText("Optional");
    await expect(page.getByTestId("settings-consent").getByRole("switch")).toHaveCount(0);
    // Changing a consent, retention and account deletion are still not offered.
    await expect(page.getByTestId("settings-privacy-missing")).toContainText("Changing a consent choice");
  });

  test("Privacy: no consent purposes, and a failed read", async ({ page }) => {
    await json(page, "**/api/compliance/consents", { consents: [], version: "1.0" });
    await page.goto(`${APP}/page/settings`);
    await expect(page.getByTestId("settings-consents-empty")).toContainText("No consent purposes listed");

    await json(page, "**/api/compliance/consents", { detail: "boom" }, 500);
    await page.reload();
    await expect(page.getByTestId("screen-page-settings").getByText("Consent records didn’t load")).toBeVisible(SLOW);
  });

  test("Privacy: delete all conversations asks first, then deletes", async ({ page }) => {
    const calls: string[] = [];
    let cleared = false;
    await page.route("**/api/chat/sessions", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(cleared ? [] : SESSIONS) }));
    // routes/chat.py :: clear_chat
    await page.route("**/api/chat/clear", (route) => {
      calls.push(route.request().method());
      cleared = true;
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ message: "Chat cleared" }) });
    });
    await page.goto(`${APP}/page/settings`);
    await expect(page.getByTestId("settings-conversations-count")).toHaveText("2");
    await page.getByTestId("settings-conversations-clear").click();
    await expect(page.getByText("This deletes every saved conversation and cannot be undone.")).toBeVisible();
    expect(calls).toEqual([]);
    await page.getByTestId("settings-conversations-clear-confirm").click();
    await expect(page.getByTestId("settings-conversations-cleared")).toBeVisible();
    await expect(page.getByTestId("settings-conversations")).toContainText("None saved.");
    await expect(page.getByTestId("settings-conversations-clear")).toBeDisabled();
    expect(calls).toEqual(["DELETE"]);
  });

  test("Privacy: a failed delete is shown and the conversations stay", async ({ page }) => {
    await json(page, "**/api/chat/clear", { detail: "boom" }, 500);
    await page.goto(`${APP}/page/settings`);
    await page.getByTestId("settings-conversations-clear").click();
    await page.getByTestId("settings-conversations-clear-confirm").click();
    await expect(page.getByTestId("settings-conversations-error")).toContainText("Your conversations weren’t deleted");
    await expect(page.getByTestId("settings-conversations-count")).toHaveText("2");
    await expect(page.getByTestId("settings-conversations-cleared")).toHaveCount(0);
  });

  test("Account activity: the trail in plain words, newest first; empty; failed read", async ({ page }) => {
    await page.goto(`${APP}/page/settings`);
    // The first 8 of the 10 fixture rows, by action.
    await expect(page.getByTestId("settings-activity-what")).toHaveText([
      "Broker account read", "Broker account read", "Data downloaded", "Signed in",
      "Broker connected", "Consent withdrawn", "Signed in", "Consent given",
    ]);
    await expect(page.getByTestId("settings-activity-row").nth(0)).toContainText("Failed"); // outcome: error
    await expect(page.getByTestId("settings-activity-row").nth(1)).not.toContainText("Failed");
    await expect(page.getByTestId("settings-activity-count")).toHaveText("10");
    // The trail's addresses and browser strings are not put on screen.
    await expect(page.getByText("192.0.2.10")).toHaveCount(0);

    await json(page, "**/api/compliance/audit*", { rows: [], count: 0 });
    await page.reload();
    await expect(page.getByTestId("settings-activity-empty")).toContainText("Nothing recorded yet");

    await json(page, "**/api/compliance/audit*", { detail: "boom" }, 500);
    await page.reload();
    await expect(page.getByTestId("screen-page-settings").getByText("Account activity didn’t load")).toBeVisible(SLOW);
  });

  test("Diagnostics: recording switches on through the server, and says when the server could not", async ({ page }) => {
    const calls: string[] = [];
    let ok = true;
    // routes/session_logs.py :: enable / disable
    await page.route("**/api/session-logs/enable", (route) => {
      calls.push("enable");
      return ok
        ? route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ enabled: true, sid: "dbg_fixture0001", ttl_seconds: 3600 }) })
        : route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "boom" }) });
    });
    await page.route("**/api/session-logs/disable", (route) => { calls.push("disable"); return route.fulfill({ status: 200, contentType: "application/json", body: "{}" }); });
    await page.goto(`${APP}/page/settings`);
    const sw = page.getByTestId("settings-logging-switch");
    await expect(sw).toHaveAttribute("aria-checked", "false");
    await sw.click();
    await expect(sw).toHaveAttribute("aria-checked", "true");
    await sw.click();
    await expect(sw).toHaveAttribute("aria-checked", "false");
    expect(calls).toEqual(["enable", "disable"]);

    ok = false;
    await sw.click();
    await expect(page.getByTestId("settings-logging")).toBeVisible();
    await expect(page.getByText("Server logs unavailable — capturing client-side logs only.")).toBeVisible();
    await expect(page.getByTestId("settings-logs-link")).toHaveAttribute("href", "/v5/settings/logs");
  });

  test("what has no backend still says so", async ({ page }) => {
    await page.goto(`${APP}/page/settings`);
    for (const id of ["settings-answer-depth-missing", "settings-constraints-missing", "settings-memory-missing", "settings-privacy-missing"]) {
      await expect(page.getByTestId(id)).toBeVisible();
      await expect(page.getByTestId(id).getByTestId("not-connected-needs")).toBeVisible(); // admin fixture
    }
    // The download says what is in the file, and no delete-account control is offered.
    await expect(page.getByTestId("settings-export")).toContainText("the PAN saved for opening statements are not in it");
    await expect(page.getByTestId("screen-page-settings").getByRole("button", { name: /delete (my |your )?account/i })).toHaveCount(0);
  });
});

// ── Get started ──────────────────────────────────────────────────────────

test.describe("Get started — portfolio step", () => {
  test.beforeEach(async ({ page }) => { await account(page); });

  async function toPortfolioStep(page: Page) {
    await page.goto(`${APP}/onboarding`);
    await page.getByTestId("onboarding-next").click();
    await expect(page.getByTestId("onboarding-rules-missing")).toBeVisible(); // portfolio rules: still no backend
    await page.getByTestId("onboarding-next").click();
    await expect(page.getByTestId("onboarding-step-portfolio")).toBeVisible();
  }

  const CSV = { name: "fixture-holdings.csv", mimeType: "text/csv", buffer: Buffer.from("Name,Symbol,Quantity,Buy price\nFixture One,FIXTUREONE,10,90\nFixture Two,FIXTURETWO,4,240\n") };

  test("CSV or Excel: the file is uploaded and the number of holdings added is shown", async ({ page }) => {
    const calls: Array<{ method: string; type: string }> = [];
    // routes/upload.py :: upload_portfolio
    await page.route("**/api/portfolio/upload", (route) => {
      calls.push({ method: route.request().method(), type: (route.request().headers()["content-type"] ?? "").split(";")[0] });
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        message: "2 holdings imported from CSV", count: 2,
        holdings: [
          { holding_id: "hold_fixture00011", name: "Fixture One", asset_type: "equity", quantity: 10 },
          { holding_id: "hold_fixture00012", name: "Fixture Two", asset_type: "equity", quantity: 4 },
        ],
      }) });
    });
    await toPortfolioStep(page);
    await page.getByTestId("onboarding-source-csv").click();
    const form = page.getByTestId("holdings-file-upload");
    await expect(form.getByTestId("holdings-file-warning")).toContainText("added to your holdings as soon as the file is read");
    await expect(form.getByTestId("holdings-file-warning")).toContainText("uploading the same file twice adds its rows twice");
    await expect(form.getByTestId("holdings-file-submit")).toBeDisabled(); // no file yet
    await form.getByTestId("holdings-file").setInputFiles(CSV);
    await expect(form.getByTestId("holdings-file-name")).toHaveText("fixture-holdings.csv");
    await form.getByTestId("holdings-file-submit").click();
    await expect(form.getByTestId("holdings-file-count")).toHaveText("2");
    await expect(form.getByTestId("holdings-file-result")).toContainText("2 holdings added to what was on file.");
    expect(calls).toEqual([{ method: "POST", type: "multipart/form-data" }]);
    // Mapping columns and previewing rows is still missing, and says so.
    await expect(page.getByTestId("onboarding-csv-missing")).toContainText("Column mapping and a preview aren’t available yet");

    await page.getByTestId("onboarding-next").click();
    await expect(page.getByTestId("onboarding-imported-count")).toHaveText("2");
  });

  test("CSV or Excel: a file with no holdings, a file the server refuses, and an .xls the server cannot open", async ({ page }) => {
    let reply: { status: number; body: unknown } = { status: 200, body: { message: "No holdings found in the uploaded file", count: 0, holdings: [] } };
    await page.route("**/api/portfolio/upload", (route) => route.fulfill({ status: reply.status, contentType: "application/json", body: JSON.stringify(reply.body) }));
    await toPortfolioStep(page);
    await page.getByTestId("onboarding-source-csv").click();
    const form = page.getByTestId("holdings-file-upload");
    await form.getByTestId("holdings-file").setInputFiles(CSV);
    await form.getByTestId("holdings-file-submit").click();
    await expect(form.getByTestId("holdings-file-result-empty")).toContainText("found no holdings in it");
    await expect(form.getByTestId("holdings-file-result")).toHaveCount(0);

    reply = { status: 400, body: { detail: "Unsupported file format. Please upload CSV, Excel (.xlsx), or CAS PDF." } };
    await form.getByTestId("holdings-file-submit").click();
    await expect(form.getByTestId("holdings-file-error")).toContainText("This file was not imported: Unsupported file format");
    await expect(form.getByTestId("holdings-file-error")).not.toContainText(".xls file");
    await expect(form.getByTestId("holdings-file-result-empty")).toHaveCount(0);

    // Today the server opens Excel files with a reader that takes .xlsx only: an .xls ends in a server error.
    reply = { status: 500, body: { detail: "Internal Server Error" } };
    await form.getByTestId("holdings-file").setInputFiles({ name: "fixture-old.xls", mimeType: "application/vnd.ms-excel", buffer: Buffer.from("not a real workbook") });
    await form.getByTestId("holdings-file-submit").click();
    await expect(form.getByTestId("holdings-file-error")).toContainText("This file was not imported");
    await expect(form.getByTestId("holdings-file-error")).toContainText("If it is an older .xls file, save it as .xlsx and try again.");
    await expect(page.getByText("Server hiccup")).toHaveCount(0);

    await page.getByTestId("onboarding-next").click();
    await expect(page.getByTestId("onboarding-imported-count")).toHaveCount(0);
  });

  test("Broker account, today's backend: the broker list and the read-only statement, with no sign-in offered", async ({ page }) => {
    await json(page, "**/api/broker/accounts", { accounts: [] });
    await toPortfolioStep(page);
    await page.getByTestId("onboarding-source-broker").click();
    await expect(page.getByTestId("broker-readonly-note")).toContainText("never places, changes or cancels an order");
    await expect(page.getByTestId("broker-signin-missing")).toContainText("You can’t connect a broker from this app today");
    await expect(page.locator('[data-testid^="broker-connect-"]')).toHaveCount(0);
    await expect(page.getByTestId("broker-account")).toHaveCount(0);
    await expect(page.getByTestId("broker-accounts-empty")).toHaveCount(0); // no empty card inside the step
    await expect(page.getByTestId("onboarding-step-portfolio").locator(brokerIcon)).toHaveCount(7);
  });

  test("planned contract, not yet on staging — Broker account: Connect goes out with a path back to Get started, and coming back reopens this step", async ({ page }) => {
    await json(page, "**/api/broker/native/supported", PLANNED_SUPPORTED);
    let connected = false;
    await page.route("**/api/broker/accounts", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ accounts: connected ? [PLANNED_ACCOUNTS.accounts[0]] : [] }) }));
    const hits: string[] = [];
    await page.route("**/api/broker/native/start/zerodha*", (route) => {
      const req = route.request();
      hits.push(`${req.resourceType()} ${new URL(req.url()).searchParams.get("return_to")}`);
      return req.resourceType() === "document"
        ? route.fulfill({ status: 200, contentType: "text/html", body: "<h1>Fixture broker sign-in page</h1>" })
        : route.fulfill({ status: 302, headers: { location: "https://broker.example.test/login" } });
    });
    await toPortfolioStep(page);
    await page.getByTestId("onboarding-source-broker").click();
    await page.getByTestId("broker-connect-zerodha").click();
    await page.getByTestId("broker-connect-go").click();
    await expect(page.getByRole("heading", { name: "Fixture broker sign-in page" })).toBeVisible();
    expect(hits).toEqual(["fetch /v5/app/onboarding", "document /v5/app/onboarding"]);

    // The broker sends the browser back the way the planned callback will.
    connected = true;
    await page.goto(`${APP}/onboarding?broker_connected=zerodha&account_id=ba_fixture00011`);
    await expect(page.getByTestId("onboarding-step-portfolio")).toBeVisible();
    await expect(page.getByTestId("onboarding-source-broker")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("broker-return-connected")).toContainText("Signed in to Zerodha");
    await expect(page.getByTestId("broker-account-name")).toHaveText("Zerodha");
    await expect(page).toHaveURL(/\/v5\/app\/onboarding$/);

    await page.goto(`${APP}/onboarding?broker_error=denied`);
    await expect(page.getByTestId("onboarding-step-portfolio")).toBeVisible();
    await expect(page.getByTestId("broker-return-error")).toContainText("cancelled or refused at the broker");
  });

  test("planned contract, not yet on staging — the last step shows the holdings and broker counts when the server sends them", async ({ page }) => {
    const state = load("copilot-account-onboarding-state.json");
    await toPortfolioStep(page);
    await page.getByTestId("onboarding-next").click();
    await expect(page.getByTestId("onboarding-statement-period")).toHaveText("Sep/2026");
    // Today's state has neither field, so neither tile is drawn.
    await expect(page.getByTestId("onboarding-holdings-count")).toHaveCount(0);
    await expect(page.getByTestId("onboarding-broker-accounts")).toHaveCount(0);

    await json(page, "**/api/onboarding/state", { ...state, holdings_count: 42, broker_accounts: 2, broker_accounts_live: 1 });
    await page.reload();
    await page.getByTestId("onboarding-next").click();
    await page.getByTestId("onboarding-next").click();
    await page.getByTestId("onboarding-next").click();
    await expect(page.getByTestId("onboarding-holdings-count")).toHaveText("42");
    await expect(page.getByTestId("onboarding-broker-accounts")).toHaveText("2");
  });
});

// ── phone ────────────────────────────────────────────────────────────────

test.describe("Account screens — phone (390×844)", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("no sideways page scroll on Broker connections, Settings or the import step", async ({ page }) => {
    await account(page);

    // Today's backend.
    await page.goto(`${APP}/page/brokers`);
    await expect(page.getByTestId("broker-account")).toHaveCount(2);
    await expect(page.getByTestId("broker-tile")).toHaveCount(7);
    await page.getByTestId("broker-account").nth(0).getByTestId("broker-disconnect").click(); // the widest card state
    await expectNoSidewaysScroll(page, "Broker connections");

    await page.goto(`${APP}/page/settings`);
    await expect(page.getByTestId("settings-consent")).toHaveCount(5);
    await expect(page.getByTestId("settings-activity-row")).toHaveCount(8);
    await expect(page.getByTestId("settings-snapshot-age")).toHaveValue("41");
    await expectNoSidewaysScroll(page, "Settings");

    await page.goto(`${APP}/onboarding`);
    await page.getByTestId("onboarding-next").click();
    await page.getByTestId("onboarding-next").click();
    for (const source of ["csv", "broker"]) {
      await page.getByTestId(`onboarding-source-${source}`).click();
      await expectNoSidewaysScroll(page, `Get started · ${source}`);
    }

    // Planned contract, not yet on staging: the Connect rows, the confirm panel and an expired account.
    await json(page, "**/api/broker/native/supported", PLANNED_SUPPORTED);
    await json(page, "**/api/broker/accounts", PLANNED_ACCOUNTS);
    await page.goto(`${APP}/page/brokers`);
    await expect(page.getByTestId("broker-reconnect")).toBeVisible();
    await page.getByTestId("broker-connect-zerodha").click();
    await expect(page.getByTestId("broker-connect-confirm")).toBeVisible();
    await expectNoSidewaysScroll(page, "Broker connections · planned contract");
  });
});
