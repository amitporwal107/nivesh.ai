/**
 * One-screen Copilot app (/v5/app) — the broker hub (in Settings, in Get
 * started and on Broker connections), Settings and Get started: every block
 * wired to an endpoint shows what the endpoint returned, its empty state and
 * its error state; every write is shown succeeding and failing.
 *
 * MOCK — not real data: every response is a fixture (e2e/fixtures/copilot-account-*.json)
 * or an inline test payload in the real response shape (the backend handler is
 * named beside each). Values are synthetic; expected values are worked out
 * from the payload, not copied from the screen.
 *
 * These tests prove the screens against the broker-hub contract as the backend
 * handlers state it (docs/API_DOCUMENTATION.md, "Broker hub"). They say nothing
 * about the live backend or a live broker: no request leaves the browser.
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

// Two accounts linked through the hosted middleware (native: false).
const ACCOUNTS = load("copilot-account-broker-accounts.json");
// The server's 21 brokers with no app keys set: nothing is connectable.
const SUPPORTED = load("copilot-account-broker-supported.json");
// The same list with app keys set for Zerodha and Upstox.
const CONNECTABLE = load("copilot-account-broker-supported-connectable.json");
// Two accounts signed in on the broker's own page: one live, one whose session has expired.
const NATIVE_ACCOUNTS = load("copilot-account-broker-accounts-native.json");
const HOLDINGS = load("copilot-account-holdings.json");
const STATE = load("copilot-account-onboarding-state.json");
const CONSENTS = load("copilot-account-consents.json");
const AUDIT = load("copilot-account-audit.json");
const PREFS = load("copilot-account-preferences.json");
const SNAPSHOT = load("copilot-account-snapshot.json");
const SESSIONS = load("copilot-account-chat-sessions.json");
// is_admin: true. The feature map on /api/auth/me carries every flag (feature_flags.user_feature_map).
const ME = { ...load("user-profile-onboarded.json"), features: { research: true, research_only: false, broker_hub: true } };

/** Every endpoint the three screens read, answered from the fixtures. A test overrides what it is about. */
async function account(page: Page) {
  await mockApi(page, "populated");
  await json(page, "**/api/auth/me", ME);                                                     // routes/auth.py :: me
  await json(page, "**/api/onboarding/state", STATE);                                         // routes/onboarding_gmail.py :: onboarding_state
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

/** The connectable broker list and the two accounts signed in on the broker's page, with two holdings read from the live one. */
async function nativeAccounts(page: Page) {
  await json(page, "**/api/broker/native/supported", CONNECTABLE);
  await json(page, "**/api/broker/accounts", NATIVE_ACCOUNTS);
  await json(page, "**/api/portfolio/holdings", [
    { ...HOLDINGS[0], broker_account_id: "ba_fixture00011" },
    { ...HOLDINGS[1], broker_account_id: "ba_fixture00011" },
    HOLDINGS[3],
  ]);
  await positionsRoute(page, [positionsOf("ba_fixture00011", 5, 2), { account_id: "ba_fixture00012", ok: false, error: { code: "BROKER_SESSION_EXPIRED", message: "Your Upstox session has ended. Reconnect the account to continue." }, as_of: NOW, positions: [] }]);
}

const NOW = new Date().toISOString();

/** GET /api/broker/positions (routes/broker_connect.py :: get_all_positions) in the real shape. MOCK — not real data. */
const positionsOf = (accountId: string, total: number, fno: number) => ({
  account_id: accountId, broker: "zerodha", broker_display: "Zerodha", label: null, ok: true, error: null, as_of: NOW,
  positions: Array.from({ length: total }, (_, i) => i < fno
    ? { symbol: i === 0 ? "ADANIPORTS" : "SWIGGY", exchange: "NFO", quantity: i === 0 ? 475 : -1825, avg_price: 100, last_price: 101, pnl: 10, product: null, product_raw: i === 0 ? "Futures" : "Options",
        segment: "fno", is_intraday: false, instrument_type: i === 0 ? "FUT" : "PE", expiry: "2026-11-23", strike: i === 0 ? null : 170, kind: "net", name: null }
    : { symbol: `EQ${i}`, exchange: "NSE", quantity: 10, avg_price: 100, last_price: 101, pnl: 10, product: "delivery", product_raw: "BTST",
        segment: "equity", is_intraday: false, instrument_type: null, expiry: null, strike: null, kind: "net", name: null }),
});
async function positionsRoute(page: Page, accounts: unknown[], status = 200): Promise<{ calls: number }> {
  const seen = { calls: 0 };
  await page.route("**/api/broker/positions*", (route) => {
    seen.calls += 1;
    return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(status === 200 ? { as_of: NOW, kind: "net", segment: "all", accounts } : { detail: "boom" }) });
  });
  return seen;
}

/**
 * GET /api/broker/native/start/{slug} (routes/broker_native.py :: start_oauth):
 * the fetch pre-check gets the redirect, the browser gets a stand-in broker
 * page. Returns what was asked, as "<resource type> <return_to>".
 */
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

/** The app's error envelope (backend/core/error_handlers.py :: _envelope). */
const envelope = (status: number, code: string, message: string, details: unknown[] = []) => ({
  timestamp: "2026-10-13T10:00:00Z", status, error: "fixture", code, message, details, correlationId: "fixture-correlation", path: "/fixture",
});

/** POST /api/portfolio/upload (routes/upload.py :: upload_portfolio), for a file with `count` holdings. */
const uploaded = (count: number, broker: string | null, brokerName: string | null, format: string | null) => ({
  message: count ? `${count} holdings imported from Excel` : "No holdings found in the uploaded file",
  count,
  holdings: Array.from({ length: count }, (_, i) => ({ holding_id: `hold_fixture1${i}`, name: `Fixture ${i + 1}`, asset_type: "equity", quantity: 10 })),
  broker, broker_name: brokerName, format,
});

const CSV = { name: "fixture-holdings.csv", mimeType: "text/csv", buffer: Buffer.from("Name,Symbol,Quantity,Buy price\nFixture One,FIXTUREONE,10,90\nFixture Two,FIXTURETWO,4,240\n") };
const XLSX = { name: "holdings-fixture.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer: Buffer.from("PK\u0003\u0004 not a real workbook") };
const XLS = { name: "fixture-old.xls", mimeType: "application/vnd.ms-excel", buffer: Buffer.from("not a real workbook") };

/** A failed read is retried before the screen gives up, so error blocks take a few seconds. */
const SLOW = { timeout: 15_000 };

const brokerIcon = '[data-testid="entity-icon"][data-kind="broker"]';
/** The Connect buttons, one per connectable broker ("broker-connect-<slug>"), and nothing else. */
const connectButtons = '[data-testid="broker-option"] [data-testid^="broker-connect-"]';
/** No control anywhere offers to trade. */
const TRADE = /\b(buy|sell|trade|place (an )?order|square off)\b/i;
/**
 * The titles the app's toast gives a REJECTED mutation (stores/toast.store.ts :: toastFromError),
 * which quotes the server's own text under them. A broker write resolves with its outcome instead,
 * so none of these may appear after one fails.
 */
const TOAST = /^(Server hiccup|Check your input|Something went wrong|Network error|Not allowed|Not found|Already exists|Please sign in again)$/;

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

// ── Broker connections · accounts and the broker list ────────────────────

test.describe("Broker connections — accounts and the broker list", () => {
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
    // The holdings line claims nothing about positions; these two hosted accounts are not read live, so there is no positions line.
    await expect(first.getByTestId("broker-positions-line")).toHaveCount(0);
    await expect(first.getByTestId("broker-account-fetched")).not.toContainText("positions");

    // Account 2: never read, nothing stored.
    const second = cards.nth(1);
    await expect(second.locator(brokerIcon)).toHaveAttribute("data-key", "upstox");
    await expect(second.getByTestId("broker-account-meta")).toContainText("Never synced");
    await expect(second.getByTestId("broker-account-fetched")).toContainText("Nothing read from this account is on file.");
    // These accounts have no broker session of their own: nothing about a session is shown, no client id, no reconnect.
    await expect(page.getByTestId("broker-account-session")).toHaveCount(0);
    await expect(page.getByTestId("broker-account-id")).toHaveCount(0);
    await expect(page.getByTestId("broker-reconnect")).toHaveCount(0);

    // 2 broker accounts + the statement + Gmail.
    await expect(page.getByTestId("brokers-connected-count")).toHaveText("4");
    // The statement and Gmail sources carry an icon too, not a letter tile.
    await expect(page.getByTestId("statement-source").locator(brokerIcon)).toHaveAttribute("data-key", "cas statement");
    await expect(page.getByTestId("gmail-source").locator(brokerIcon)).toHaveAttribute("data-key", "gmail");

    await expect(page.getByTestId("broker-readonly-note")).toContainText("never places, changes or cancels an order");
    // Positions: the page says they are read live, not stored, and are shown.
    const posRow = page.getByRole("row").filter({ hasText: "Open positions in a connected broker account" });
    await expect(posRow).toContainText("not stored");
    await expect(posRow).not.toContainText("Not shown");
    // Nothing on the screen offers to trade.
    await expect(page.getByTestId("screen-page-brokers").getByRole("button", { name: TRADE })).toHaveCount(0);
  });

  test("nothing connectable: the page says so, shows each first broker as not connectable with its file route, and never calls it planned", async ({ page }) => {
    await page.goto(`${APP}/page/brokers`);
    const screen = page.getByTestId("screen-page-brokers");
    // Fixture: the server's 21 brokers, no app keys set, so none has connectable: true.
    await expect(page.getByTestId("broker-none-connectable")).toContainText("No broker can be connected right now. Upload your broker’s holdings file instead.");
    // A broker's name is never taken to mean it can be connected.
    await expect(page.locator(connectButtons)).toHaveCount(0);

    // The product's first brokers, in the order named, each with its icon, why not, and the file route.
    const rows = page.getByTestId("broker-options").getByTestId("broker-option");
    const expected: Array<[string, string, string]> = [
      ["zerodha", "Zerodha", "Sign-in isn’t set up yet"],
      ["groww", "Groww", "Can’t be connected"],
      ["angel", "Angel One", "Sign-in isn’t set up yet"],
      ["upstox", "Upstox", "Sign-in isn’t set up yet"],
      ["icicidirect", "ICICI Direct", "Can’t be connected"],
    ];
    await expect(rows).toHaveCount(expected.length);
    for (const [i, [slug, name, note]] of expected.entries()) {
      await expect(rows.nth(i)).toHaveAttribute("data-slug", slug);
      await expect(rows.nth(i)).toContainText(name);
      await expect(rows.nth(i).getByTestId("broker-option-note")).toHaveText(note);
      await expect(rows.nth(i).locator(brokerIcon)).toHaveCount(1);
      await expect(rows.nth(i).getByRole("button", { name: `Upload a holdings file from ${name}` })).toBeVisible();
    }

    // The other 16 are one tap away. "Upload file" only where the server recognises the export: 5paisa, Dhan, Kotak.
    await expect(page.getByTestId("broker-more-count")).toHaveText("16");
    await expect(page.getByTestId("broker-options-more")).toHaveCount(0);
    await page.getByTestId("broker-more-toggle").click();
    const more = page.getByTestId("broker-options-more");
    await expect(more.getByTestId("broker-option")).toHaveCount(16);
    await expect(more.locator(brokerIcon)).toHaveCount(16);
    await expect(more.getByRole("button")).toHaveCount(3);
    for (const slug of ["fivepaisa", "dhan", "kotak"]) await expect(more.getByTestId(`broker-file-${slug}`)).toBeVisible();

    // The old "not available yet" block is gone, and nothing calls the backend planned.
    await expect(page.getByTestId("broker-signin-missing")).toHaveCount(0);
    await expect(page.getByTestId("not-connected")).toHaveCount(0);
    await expect(screen).not.toContainText(/planned|not available yet|isn’t available yet/i);
    await expect(screen).toContainText("from a broker account you connect");

    // Admins are told which brokers wait on app keys, by broker name. No setting is named.
    await expect(page.getByTestId("broker-admin-keys")).toContainText("AliceBlue, Angel One, Fyers, Upstox, Zerodha");
    await expect(screen).not.toContainText(/API_KEY|API_SECRET|BROKER_[A-Z]/);

    // The file route for one broker: the upload form on this page is named for it.
    await rows.nth(1).getByTestId("broker-file-groww").click();
    await expect(page.getByTestId("holdings-file-for")).toHaveText("Download your holdings from Groww as an Excel or CSV file, then choose it here.");
    await expect(page.getByTestId("holdings-file-upload")).toBeInViewport();

    // Someone who is not an admin gets the same plain statement, without the admin line.
    await json(page, "**/api/auth/me", { ...ME, is_admin: false });
    await page.reload();
    await expect(page.getByTestId("broker-none-connectable")).toBeVisible();
    await expect(page.getByTestId("broker-admin-keys")).toHaveCount(0);
  });

  test("empty: no account and no broker listed; holdings are not requested", async ({ page }) => {
    let holdingsCalls = 0;
    await json(page, "**/api/broker/accounts", { accounts: [] });
    await json(page, "**/api/broker/native/supported", { brokers: [] });
    await page.route("**/api/portfolio/holdings", (route) => { holdingsCalls += 1; return route.fulfill({ status: 200, contentType: "application/json", body: "[]" }); });
    await page.goto(`${APP}/page/brokers`);
    await expect(page.getByTestId("broker-accounts-empty")).toContainText("No broker account connected");
    await expect(page.getByTestId("broker-adapters-empty")).toContainText("No broker is listed");
    await expect(page.getByTestId("broker-adapters-empty").getByTestId("broker-use-file")).toBeVisible();
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
    await expect(page.locator(connectButtons)).toHaveCount(0);

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

    // An account or a broker without the fields the server always sends is a mismatch too, not a guess.
    const { needs_reconnect: _n, ...noSession } = NATIVE_ACCOUNTS.accounts[0];
    await json(page, "**/api/broker/accounts", { accounts: [noSession] });
    await json(page, "**/api/broker/native/supported", { brokers: [{ slug: "zerodha", name: "Zerodha", auth_style: "oauth", implemented: true }] });
    await page.reload();
    await expect(screen.getByText(/Broker accounts didn’t load/)).toBeVisible();
    await expect(screen.getByText(/The broker list didn’t load/)).toBeVisible();
    await expect(page.locator(connectButtons)).toHaveCount(0);
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

  test("Sync now: a failed read is shown in plain words, is sent once, and the server's wording goes to admins only", async ({ page }) => {
    let posts = 0;
    // A 5xx from the hosted-middleware path, in the app's error envelope.
    await page.route("**/api/broker/accounts/ba_fixture00002/sync", (route) => {
      posts += 1;
      return route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify(envelope(500, "SYS-001", "Stored OpenAlgo URL is missing")) });
    });
    await page.goto(`${APP}/page/brokers`);
    const second = page.getByTestId("broker-account").nth(1);
    await second.getByTestId("broker-sync").click();
    await expect(second.getByTestId("broker-sync-error")).toContainText("Nivesh couldn’t read this account.");
    await expect(second.getByTestId("broker-admin-detail")).toContainText("Stored OpenAlgo URL is missing"); // fixture user is an admin
    await expect(second.getByTestId("broker-sync-result")).toHaveCount(0);
    await page.waitForLoadState("networkidle");
    expect(posts).toBe(1); // a write is never re-sent, even after a 5xx

    // The same failure for someone who is not an admin: plain words only, on the card and nowhere else.
    await json(page, "**/api/auth/me", { ...ME, is_admin: false });
    await page.reload();
    const again = page.getByTestId("broker-account").nth(1);
    await again.getByTestId("broker-sync").click();
    await expect(again.getByTestId("broker-sync-error")).toContainText("Nivesh couldn’t read this account.");
    await expect(page.getByTestId("broker-admin-detail")).toHaveCount(0);
    await expect(page.getByText("OpenAlgo")).toHaveCount(0);       // not in a toast either
    await expect(page.getByText(TOAST)).toHaveCount(0);
    await expect(page.getByTestId("not-connected-needs")).toHaveCount(0);
    expect(posts).toBe(2); // one per press
  });

  test("Remove: asks first, then the account is gone", async ({ page }) => {
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
    await expect(first.getByTestId("broker-disconnect")).toHaveText("Remove");
    await first.getByTestId("broker-disconnect").click();
    await expect(first).toContainText("Remove Fixture Zerodha? The holdings read from it are removed.");
    expect(calls).toEqual([]); // nothing sent until confirmed
    await first.getByTestId("broker-disconnect-confirm").click();
    await expect(page.getByTestId("broker-account")).toHaveCount(1);
    await expect(page.getByTestId("broker-account-name")).toHaveText("Upstox");
    await expect(page.getByTestId("brokers-connected-count")).toHaveText("3");
    expect(calls).toEqual(["DELETE"]);
  });

  test("Remove: a failure is shown and the account stays", async ({ page }) => {
    await json(page, "**/api/broker/accounts/ba_fixture00001", { detail: "boom" }, 500);
    await page.goto(`${APP}/page/brokers`);
    const first = page.getByTestId("broker-account").nth(0);
    await first.getByTestId("broker-disconnect").click();
    await first.getByTestId("broker-disconnect-confirm").click();
    await expect(first.getByTestId("broker-disconnect-error")).toContainText("Couldn’t remove this account. It is still connected.");
    await expect(page.getByTestId("broker-account")).toHaveCount(2);
    await expect(page.getByText(TOAST)).toHaveCount(0);
  });

  test("the import log says why a broker event failed without repeating the trail's own reason", async ({ page }) => {
    // services/audit.py rows as routes/broker_native.py and routes/broker_connect.py write them.
    await json(page, "**/api/compliance/audit*", { count: 3, rows: [
      { audit_id: "aud_f1", action: "broker_connect", outcome: "error", details: { broker: "zerodha", stage: "auth_url", reason: "app keys not configured: BROKER_ZERODHA_API_KEY, BROKER_ZERODHA_API_SECRET" }, ts: "2026-10-13T09:00:00+00:00" },
      { audit_id: "aud_f2", action: "broker_sync", outcome: "error", details: { broker: "upstox", native: true, code: "BROKER_SESSION_EXPIRED", reason: "Your Upstox session has ended. Reconnect the account to continue." }, ts: "2026-10-13T08:00:00+00:00" },
      { audit_id: "aud_f3", action: "broker_connect", outcome: "error", details: { broker: "upstox", stage: "exchange_code", reason: "HTTPStatusError" }, ts: "2026-10-13T07:00:00+00:00" },
    ] });
    await page.goto(`${APP}/page/brokers`);
    await expect(page.getByTestId("import-log-event")).toHaveText(["Broker connect failed", "Broker sync failed", "Broker connect failed"]);
    await expect(page.getByTestId("import-log-detail")).toHaveText([
      "zerodha · the sign-in could not be started",
      "upstox · the broker session had ended",
      "upstox · the broker did not accept the sign-in",
    ]);
    await expect(page.getByTestId("screen-page-brokers")).not.toContainText(/BROKER_ZERODHA|API_KEY|HTTPStatusError/);
  });
});

// ── Broker connections · sign-in, sessions and coming back ───────────────

test.describe("Broker connections — sign-in, sessions and coming back", () => {
  test.beforeEach(async ({ page }) => {
    await account(page);
    await nativeAccounts(page);
  });

  test("Connect is offered only where the server says connectable", async ({ page }) => {
    await page.goto(`${APP}/page/brokers`);
    // Fixture: Zerodha and Upstox connectable; Angel One (keys not set), Groww (no redirect) and ICICI Direct (switched off) are not.
    const rows = page.getByTestId("broker-options").getByTestId("broker-option");
    const expected: Array<[string, boolean, string]> = [
      ["zerodha", true, "Sign in on the broker’s own site"],
      ["upstox", true, "Sign in on the broker’s own site"],
      ["groww", false, "Can’t be connected"],
      ["angel", false, "Sign-in isn’t set up yet"],
      ["icicidirect", false, "Can’t be connected"],
    ];
    await expect(rows).toHaveCount(expected.length);
    for (const [i, [slug, connectable, note]] of expected.entries()) {
      await expect(rows.nth(i)).toHaveAttribute("data-slug", slug);
      await expect(rows.nth(i)).toHaveAttribute("data-connectable", String(connectable));
      await expect(rows.nth(i).getByTestId("broker-option-note")).toHaveText(note);
      await expect(rows.nth(i).locator(brokerIcon)).toHaveCount(1);
      await expect(rows.nth(i).getByTestId(`broker-connect-${slug}`)).toHaveCount(connectable ? 1 : 0);
      await expect(rows.nth(i).getByTestId(`broker-file-${slug}`)).toHaveCount(connectable ? 0 : 1);
    }
    await expect(page.locator(connectButtons)).toHaveCount(2);
    await expect(page.getByTestId("broker-connect-zerodha")).toHaveText("Connect");
    await expect(page.getByRole("button", { name: "Connect Upstox" })).toBeVisible();
    // Connecting is offered, so the file route is the quiet alternative, not a warning.
    await expect(page.getByTestId("broker-none-connectable")).toHaveCount(0);
    await expect(page.getByTestId("broker-file-route")).toContainText("Prefer not to connect?");
    await expect(page.getByTestId("broker-signin-missing")).toHaveCount(0);
    await expect(page.getByTestId("screen-page-brokers")).toContainText("from a broker account you connect");
    await expect(page.getByTestId("broker-readonly-note")).toBeVisible();
  });

  test("Connect leaves for the broker's own page with a path back to this screen", async ({ page }) => {
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

  test("“Not now” starts nothing", async ({ page }) => {
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

  test("a sign-in the server cannot start is said on the screen (503, 400, 404, 403, 500, no answer) and names no server setting", async ({ page }) => {
    // What routes/broker_native.py :: start_oauth answers, in the app's error envelope.
    let reply: { status: number; code: string; message: string } | "abort" =
      { status: 503, code: "INT-001", message: "Zerodha sign-in is not available yet — Nivesh's Zerodha app keys are not configured." };
    let hits = 0;
    await page.route("**/api/broker/native/start/zerodha*", (route) => {
      hits += 1;
      if (reply === "abort") return route.abort();
      return route.fulfill({ status: reply.status, contentType: "application/json", body: JSON.stringify(envelope(reply.status, reply.code, reply.message)) });
    });
    await page.goto(`${APP}/page/brokers`);
    await page.getByTestId("broker-connect-zerodha").click();
    await page.getByTestId("broker-connect-go").click();
    const err = page.getByTestId("broker-connect-error");
    await expect(err).toContainText("Sign-in with Zerodha isn’t set up on Nivesh yet.");
    await expect(err.getByTestId("broker-admin-detail")).toContainText("Nivesh's Zerodha app keys are not configured"); // admin fixture; the server's own message
    await expect(page).toHaveURL(/\/v5\/app\/page\/brokers$/);
    expect(hits).toBe(1); // asked once; the browser was not sent to an error page

    reply = { status: 400, code: "VAL-001", message: "Zerodha cannot be connected from Nivesh yet." };
    await page.getByTestId("broker-connect-go").click();
    await expect(err).toContainText("Zerodha can’t be connected from Nivesh yet. Upload its holdings file instead.");

    reply = { status: 404, code: "RES-001", message: "Unknown broker 'zerodha'" };
    await page.getByTestId("broker-connect-go").click();
    await expect(err).toContainText("Nivesh does not offer Zerodha.");

    reply = { status: 403, code: "AUTHZ-001", message: "feature_not_enabled" };
    await page.getByTestId("broker-connect-go").click();
    await expect(err).toContainText("Broker connections are not switched on for this account.");

    // A message that names a server setting is not put on screen, not even for an admin.
    reply = { status: 500, code: "SYS-001", message: "BROKER_ZERODHA_API_KEY is not configured" };
    await page.getByTestId("broker-connect-go").click();
    await expect(err).toContainText("Sign-in with Zerodha couldn’t be started. Try again in a little while.");
    await expect(err.getByTestId("broker-admin-detail")).toHaveCount(0);
    await expect(page.getByText(/BROKER_ZERODHA|API_KEY/)).toHaveCount(0);

    reply = "abort";
    await page.getByTestId("broker-connect-go").click();
    await expect(err).toContainText("The request didn’t reach the server.");

    await expect(page).toHaveURL(/\/v5\/app\/page\/brokers$/);
    await expect(page.getByText(TOAST)).toHaveCount(0);
    expect(hits).toBe(6); // one request per press, never a second by navigation
  });

  test("coming back: success is confirmed against the account list, the address is cleared, accounts are read again", async ({ page }) => {
    let accountReads = 0;
    await page.route("**/api/broker/accounts", (route) => { accountReads += 1; return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(NATIVE_ACCOUNTS) }); });
    await page.goto(`${APP}/page/brokers?broker_connected=zerodha&account_id=ba_fixture00011`);
    // The account is in the list the server returned, with what the first read stored (last_sync_count: 3).
    await expect(page.getByTestId("broker-return-connected")).toHaveText(/Signed in to Zerodha\. 3 holdings were read from it\./);
    await expect(page).toHaveURL(/\/v5\/app\/page\/brokers$/); // broker_connected and account_id are gone
    await expect(page.getByTestId("broker-account")).toHaveCount(2);
    await page.waitForLoadState("networkidle");
    expect(accountReads).toBeGreaterThanOrEqual(1); // read after arriving, never served from an earlier visit
    await page.getByTestId("broker-return-connected").getByRole("button", { name: "Dismiss" }).click();
    await expect(page.getByTestId("broker-return-connected")).toHaveCount(0);

    // Connected, but the first read did not finish: the notice says so instead of claiming holdings.
    await json(page, "**/api/broker/accounts", { accounts: [{ ...NATIVE_ACCOUNTS.accounts[0], last_sync_at: null, last_sync_count: 0, last_error: "First holdings sync timed out." }] });
    await page.goto(`${APP}/page/brokers?broker_connected=zerodha&account_id=ba_fixture00011`);
    await expect(page.getByTestId("broker-return-connected")).toContainText("Its holdings have not been read yet: press “Sync now” on the account.");

    // An address that claims a connection the server does not list is not believed.
    await page.goto(`${APP}/page/brokers?broker_connected=zerodha&account_id=ba_not_in_the_list`);
    await expect(page.getByTestId("broker-return-unconfirmed")).toContainText("the new account is not in your list");
    await expect(page.getByTestId("broker-return-connected")).toHaveCount(0);
  });

  test("coming back: each failure code gets its own plain sentence", async ({ page }) => {
    const sentences: Record<string, string> = {
      denied: "the sign-in was cancelled or refused at the broker",
      missing_params: "the broker did not send back a sign-in code",
      invalid_state: "the sign-in could not be matched to this account",
      state_expired: "the sign-in took more than ten minutes",
      unknown_broker: "Nivesh does not know that broker",
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
    // A code this app does not know is still reported, but the address is never echoed onto the page.
    await page.goto(`${APP}/page/brokers?broker_error=call_this_number_now`);
    await expect(page.getByTestId("broker-return-error")).toContainText("the reason was not one Nivesh knows");
    await expect(page.getByText(/call this number/i)).toHaveCount(0);
  });

  test("an account signed in on the broker's page: who, until when, and what was read", async ({ page }) => {
    await page.goto(`${APP}/page/brokers`);
    const live = page.getByTestId("broker-account").nth(0);
    await expect(live.getByTestId("broker-account-status")).toHaveText("Connected");
    await expect(live.getByTestId("broker-account-id")).toHaveText("••••42"); // broker_user_masked
    await expect(live.getByTestId("broker-account-session")).toContainText("Signed in until"); // session_expires_at
    await expect(live.getByTestId("broker-account-meta")).toContainText("Last synced");
    await expect(live.getByTestId("broker-fetched-count")).toHaveText("2");
    await expect(live.getByTestId("broker-fetched-value")).toHaveText("₹2,002"); // 10×100 + 4×250.5
    await expect(live.getByTestId("broker-reconnect")).toHaveCount(0);
    await expect(live.getByTestId("broker-account-fetched")).not.toContainText("positions");
  });

  test("an account signed in on the broker's page also says how many open positions it holds, with the way to them", async ({ page }) => {
    await page.goto(`${APP}/page/brokers`);
    const live = page.getByTestId("broker-account").nth(0);
    const line = live.getByTestId("broker-positions-line");
    await expect(line).toContainText("open positions", { timeout: 15_000 });
    await expect(live.getByTestId("broker-positions-count")).toHaveText("5");
    await expect(live.getByTestId("broker-positions-fno")).toHaveText("2");
    await expect(line).toContainText("read ");
    // The expired account is not read: it has no positions line, only its Reconnect.
    await expect(page.getByTestId("broker-account").nth(1).getByTestId("broker-positions-line")).toHaveCount(0);
    await live.getByTestId("broker-positions-open").click();
    await expect(page).toHaveURL(/\/page\/positions$/);
  });

  test("open positions: one account with none says so; a read that failed says it could not be read, never 'none', and retries", async ({ page }) => {
    const seen = await positionsRoute(page, [positionsOf("ba_fixture00011", 0, 0)]);
    await page.goto(`${APP}/page/brokers`);
    const live = page.getByTestId("broker-account").nth(0);
    await expect(live.getByTestId("broker-positions-line")).toHaveText("No open positions at this broker right now.", { timeout: 15_000 });
    expect(seen.calls).toBe(1);                                                    // one shared read, not one per card

    await page.unroute("**/api/broker/positions*");
    const failed = await positionsRoute(page, [], 500);
    await page.reload();
    const again = page.getByTestId("broker-account").nth(0).getByTestId("broker-positions-line");
    await expect(again).toContainText("couldn’t be read from this account just now", { timeout: 15_000 });
    await expect(again).not.toContainText("No open positions");
    await again.getByTestId("broker-positions-retry").click();
    await expect.poll(() => failed.calls, { timeout: 15_000 }).toBeGreaterThan(1);
  });

  test("an expired session says so and offers Reconnect, which leaves for the broker", async ({ page }) => {
    const hits = await startRoute(page, "upstox");
    await page.goto(`${APP}/page/brokers`);
    const expired = page.getByTestId("broker-account").nth(1);
    await expect(expired.getByTestId("broker-account-status")).toHaveText("Reconnect needed");
    await expect(expired.getByTestId("broker-account-session")).toContainText("The sign-in for this account has expired. Reconnect to keep reading it.");
    await expect(expired.getByTestId("broker-account-fetched")).toContainText("Nothing read from this account is on file.");
    // An ended session cannot be read: Reconnect is the action, not Sync.
    await expect(expired.getByTestId("broker-sync")).toHaveCount(0);
    await expired.getByTestId("broker-reconnect").click();
    await expect(page.getByRole("heading", { name: "Fixture broker sign-in page" })).toBeVisible();
    expect(hits).toEqual(["fetch /v5/app/page/brokers", "document /v5/app/page/brokers"]);
  });

  test("why a session ended is said in words: expired, signed out of Nivesh, refused by the broker", async ({ page }) => {
    const ended = NATIVE_ACCOUNTS.accounts[1];
    const cases: Array<[string | null, string]> = [
      ["expired", "The sign-in for this account has expired."],
      ["logout", "Signing out of Nivesh ended the sign-in for this account."],
      ["broker_rejected", "The broker no longer accepts the saved sign-in."],
      [null, "The sign-in for this account has ended."],
    ];
    for (const [reason, sentence] of cases) {
      await json(page, "**/api/broker/accounts", { accounts: [{ ...ended, session_ended_reason: reason }] });
      await page.goto(`${APP}/page/brokers`);
      const card = page.getByTestId("broker-account");
      await expect(card.getByTestId("broker-account-status"), String(reason)).toHaveText("Reconnect needed");
      await expect(card.getByTestId("broker-account-session"), String(reason)).toHaveText(`${sentence} Reconnect to keep reading it.`);
      await expect(card.getByTestId("broker-reconnect"), String(reason)).toBeVisible();
    }
    // The broker cannot be signed in to right now (its keys are not set): no Reconnect, and the card says why.
    await json(page, "**/api/broker/native/supported", SUPPORTED);
    await page.reload();
    await expect(page.getByTestId("broker-account-session")).toContainText("Sign-in with Upstox isn’t available right now, so it can’t be reconnected here.");
    await expect(page.getByTestId("broker-reconnect")).toHaveCount(0);
    await expect(page.getByTestId("broker-disconnect")).toBeEnabled();
  });

  test("Sync now reads a signed-in account, and each error code gets its own sentence", async ({ page }) => {
    let reply: { status: number; body: unknown } = { status: 200, body: { ok: true, count: 2, holdings: [] } };
    let posts = 0;
    await page.route("**/api/broker/accounts/ba_fixture00011/sync", (route) => { posts += 1; return route.fulfill({ status: reply.status, contentType: "application/json", body: JSON.stringify(reply.body) }); });
    await page.goto(`${APP}/page/brokers`);
    const live = page.getByTestId("broker-account").nth(0);
    await live.getByTestId("broker-sync").click();
    await expect(live.getByTestId("broker-sync-result")).toHaveText("2 holdings read just now.");

    // The app's error envelope, keyed on `code` (routes/broker_connect.py :: _read_error), with the
    // message services/brokers/hub_reads.py :: describe_failure writes for each.
    const who = [{ broker: "zerodha", account_id: "ba_fixture00011" }];
    const cases: Array<[number, string, string, string]> = [
      [409, "BROKER_SESSION_EXPIRED", "Your Zerodha session has ended. Reconnect the account to continue.", "Your Zerodha session has ended. Sign in again, then sync."],
      [400, "BROKER_READ_NOT_SUPPORTED", "Reading holdings is not available for Zerodha.", "Nivesh can’t read holdings from this kind of Zerodha account yet."],
      [424, "BROKER_READ_FAILED", "Could not read holdings from Zerodha. Please try again.", "Zerodha did not return your holdings. Try again in a little while."],
    ];
    for (const [status, code, message, sentence] of cases) {
      reply = { status, body: envelope(status, code, message, who) };
      await live.getByTestId("broker-sync").click();
      await expect(live.getByTestId("broker-sync-error"), code).toContainText(sentence);
      await expect(live.getByTestId("broker-admin-detail"), code).toContainText(message); // admin fixture
      await expect(live.getByTestId("broker-sync-result"), code).toHaveCount(0);
    }
    // The same code under `detail` (a body that is not the envelope) is still understood.
    reply = { status: 409, body: { detail: { code: "BROKER_SESSION_EXPIRED", message: "fixture message", broker: "zerodha", account_id: "ba_fixture00011" } } };
    await live.getByTestId("broker-sync").click();
    await expect(live.getByTestId("broker-sync-error")).toContainText("Your Zerodha session has ended. Sign in again, then sync.");
    // Switched off for the account: the envelope's message, or a bare detail string.
    for (const body of [envelope(403, "AUTHZ-001", "feature_not_enabled"), { detail: "feature_not_enabled" }]) {
      reply = { status: 403, body };
      await live.getByTestId("broker-sync").click();
      await expect(live.getByTestId("broker-sync-error")).toContainText("Broker connections are not switched on for this account.");
    }
    await expect(page.getByText(TOAST)).toHaveCount(0);
    await page.waitForLoadState("networkidle");
    expect(posts).toBe(7); // one request per press: a 502 is not re-sent
  });

  test("broker_hub switched off for the account: no Connect, Reconnect or Sync; accounts still listed and removable; the file route is offered", async ({ page }) => {
    await json(page, "**/api/auth/me", { ...ME, features: { ...ME.features, broker_hub: false } });
    await page.goto(`${APP}/page/brokers`);
    const off = page.getByTestId("broker-hub-off");
    await expect(off).toContainText("Broker connections are not switched on for this account.");
    await expect(off).toContainText("you can still upload a holdings file");
    await expect(off.getByTestId("broker-use-file")).toBeVisible();
    await expect(page.locator(connectButtons)).toHaveCount(0);
    await expect(page.getByTestId("broker-reconnect")).toHaveCount(0);
    await expect(page.getByTestId("broker-sync")).toHaveCount(0); // the server refuses to read these accounts while it is off
    // Brokers the server would otherwise connect are shown as off for this account, not as connectable.
    const zerodha = page.getByTestId("broker-options").getByTestId("broker-option").nth(0);
    await expect(zerodha).toHaveAttribute("data-slug", "zerodha");
    await expect(zerodha.getByTestId("broker-option-note")).toHaveText("Sign-in is off for this account");
    await expect(zerodha.getByTestId("broker-file-zerodha")).toBeVisible();
    await expect(page.getByTestId("broker-account")).toHaveCount(2);
    await expect(page.getByTestId("broker-account").nth(1).getByTestId("broker-account-session")).toContainText("Broker sign-in is off for this account.");
    await expect(page.getByTestId("broker-account").nth(0).getByTestId("broker-disconnect")).toBeEnabled();

    // The flag switched on: Connect is offered as the list says.
    await json(page, "**/api/auth/me", ME);
    await page.reload();
    await expect(page.locator(connectButtons)).toHaveCount(2);
    await expect(page.getByTestId("broker-hub-off")).toHaveCount(0);
    await expect(page.getByTestId("broker-account").nth(0).getByTestId("broker-sync")).toBeVisible();
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

// ── Settings · the broker hub ────────────────────────────────────────────

test.describe("Settings — broker hub", () => {
  test.beforeEach(async ({ page }) => {
    await account(page);
    await nativeAccounts(page);
  });

  test("the hub is in Settings: each account with its icon, client id, status, last sync and session expiry", async ({ page }) => {
    await page.goto(`${APP}/page/settings`);
    const hub = page.getByTestId("settings-broker-hub");
    await expect(hub.getByTestId("broker-accounts-count")).toHaveText("2");
    const cards = hub.getByTestId("broker-account");
    await expect(cards).toHaveCount(2);

    const live = cards.nth(0);
    await expect(live.locator(brokerIcon)).toHaveAttribute("data-key", "zerodha");
    await expect(live.getByTestId("broker-account-name")).toHaveText("Zerodha");
    await expect(live.getByTestId("broker-account-id")).toHaveText("••••42");
    await expect(live.getByTestId("broker-account-status")).toHaveText("Connected");
    await expect(live.getByTestId("broker-account-meta")).toContainText("Last synced");
    await expect(live.getByTestId("broker-account-meta")).toContainText("3 holdings");
    await expect(live.getByTestId("broker-account-session")).toContainText("Signed in until");
    await expect(live.getByTestId("broker-fetched-count")).toHaveText("2");
    for (const id of ["broker-sync", "broker-disconnect"]) await expect(live.getByTestId(id)).toBeEnabled();
    await expect(live.getByTestId("broker-reconnect")).toHaveCount(0);

    // The account whose session has ended: a clear Reconnect state.
    const ended = cards.nth(1);
    await expect(ended.locator(brokerIcon)).toHaveAttribute("data-key", "upstox");
    await expect(ended.getByTestId("broker-account-id")).toHaveText("••••07");
    await expect(ended.getByTestId("broker-account-status")).toHaveText("Reconnect needed");
    await expect(ended.getByTestId("broker-account-session")).toHaveText("The sign-in for this account has expired. Reconnect to keep reading it.");
    await expect(ended.getByTestId("broker-reconnect")).toHaveText("Reconnect");
    await expect(ended.getByTestId("broker-sync")).toHaveCount(0);

    // Add a broker: Connect for the two the server marks connectable. Read-only, and nothing offers to trade.
    await expect(hub.locator(connectButtons)).toHaveCount(2);
    await expect(hub.getByTestId("broker-readonly-note")).toContainText("never places, changes or cancels an order");
    await expect(page.getByTestId("screen-page-settings").getByRole("button", { name: TRADE })).toHaveCount(0);

    // The old count row is gone. Statements and Gmail keep their card and a way to their page.
    await expect(page.getByTestId("settings-broker-count")).toHaveCount(0);
    await expect(page.getByTestId("settings-gmail-status")).toHaveText("Connected");
    await expect(page.getByTestId("settings-statement-status")).toHaveText("On file");
    await page.getByTestId("settings-manage-connections").click();
    await expect(page).toHaveURL(/\/v5\/app\/page\/brokers$/);
    // The standalone page shows the same accounts through the same components.
    await expect(page.getByTestId("screen-page-brokers").getByTestId("broker-account-id")).toHaveText(["••••42", "••••07"]);
  });

  test("Sync now from Settings: one request, the count read; a failed read in the hub's own words with no server text and no toast", async ({ page }) => {
    await json(page, "**/api/auth/me", { ...ME, is_admin: false });
    let reply: { status: number; body: unknown } = { status: 200, body: { ok: true, count: 5, holdings: [] } };
    const calls: string[] = [];
    // routes/broker_connect.py :: sync_broker_account
    await page.route("**/api/broker/accounts/ba_fixture00011/sync", (route) => {
      calls.push(route.request().method());
      return route.fulfill({ status: reply.status, contentType: "application/json", body: JSON.stringify(reply.body) });
    });
    await page.goto(`${APP}/page/settings`);
    const live = page.getByTestId("settings-broker-hub").getByTestId("broker-account").nth(0);
    await live.getByTestId("broker-sync").click();
    await expect(live.getByTestId("broker-sync-result")).toHaveText("5 holdings read just now.");
    expect(calls).toEqual(["POST"]);

    reply = { status: 424, body: envelope(424, "BROKER_READ_FAILED", "upstream kite.trade timed out after 12s", [{ broker: "zerodha", account_id: "ba_fixture00011" }]) };
    await live.getByTestId("broker-sync").click();
    await expect(live.getByTestId("broker-sync-error")).toHaveText("Zerodha did not return your holdings. Try again in a little while.");
    await expect(live.getByTestId("broker-sync-result")).toHaveCount(0);
    await expect(page.getByText(/kite\.trade|upstream|timed out/)).toHaveCount(0);
    await expect(page.getByText(TOAST)).toHaveCount(0);
    await page.waitForLoadState("networkidle");
    expect(calls).toEqual(["POST", "POST"]); // the failed read was not sent again
  });

  test("Reconnect from Settings leaves for the broker with a path back to Settings", async ({ page }) => {
    const hits = await startRoute(page, "upstox");
    await page.goto(`${APP}/page/settings`);
    await page.getByTestId("settings-broker-hub").getByTestId("broker-reconnect").click();
    await expect(page.getByRole("heading", { name: "Fixture broker sign-in page" })).toBeVisible();
    expect(hits).toEqual(["fetch /v5/app/page/settings", "document /v5/app/page/settings"]);
  });

  test("Remove from Settings asks first; “Keep” sends nothing; confirming removes the account from the hub", async ({ page }) => {
    const calls: string[] = [];
    let gone = false;
    await page.route("**/api/broker/accounts", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(gone ? { accounts: [NATIVE_ACCOUNTS.accounts[0]] } : NATIVE_ACCOUNTS) }));
    // routes/broker_connect.py :: disconnect_broker
    await page.route("**/api/broker/accounts/ba_fixture00012", (route) => {
      calls.push(route.request().method());
      gone = true;
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) });
    });
    await page.goto(`${APP}/page/settings`);
    const hub = page.getByTestId("settings-broker-hub");
    const ended = hub.getByTestId("broker-account").nth(1);
    await ended.getByTestId("broker-disconnect").click();
    await expect(ended).toContainText("Remove Upstox? The holdings read from it are removed.");
    await ended.getByRole("button", { name: "Keep" }).click();
    await expect(ended.getByTestId("broker-disconnect-confirm")).toHaveCount(0);
    expect(calls).toEqual([]); // nothing sent until confirmed

    await ended.getByTestId("broker-disconnect").click();
    await ended.getByTestId("broker-disconnect-confirm").click();
    await expect(hub.getByTestId("broker-account")).toHaveCount(1);
    await expect(hub.getByTestId("broker-accounts-count")).toHaveText("1");
    await expect(hub.getByTestId("broker-account-name")).toHaveText("Zerodha");
    expect(calls).toEqual(["DELETE"]);
  });

  test("Connect from Settings starts the sign-in with a path back to Settings", async ({ page }) => {
    const hits = await startRoute(page, "zerodha");
    await page.goto(`${APP}/page/settings`);
    const hub = page.getByTestId("settings-broker-hub");
    await hub.getByTestId("broker-connect-zerodha").click();
    const confirm = hub.getByTestId("broker-connect-confirm");
    await expect(confirm).toContainText("You sign in on Zerodha’s own site");
    await expect(confirm).toContainText("Zerodha sends you back to this page when you are done.");
    await expect(hub.locator('input:not([type="file"])')).toHaveCount(0); // no password, PIN or code is asked for
    expect(hits).toEqual([]); // nothing is started until the user continues
    await hub.getByTestId("broker-connect-go").click();
    await expect(page.getByRole("heading", { name: "Fixture broker sign-in page" })).toBeVisible();
    expect(hits).toEqual(["fetch /v5/app/page/settings", "document /v5/app/page/settings"]);
  });

  test("coming back to Settings: the outcome is shown in the hub and in view, and the address is cleared", async ({ page }) => {
    await page.goto(`${APP}/page/settings?broker_connected=zerodha&account_id=ba_fixture00011`);
    const hub = page.getByTestId("settings-broker-hub");
    const ok = hub.getByTestId("broker-return-connected");
    await expect(ok).toContainText("Signed in to Zerodha. 3 holdings were read from it.");
    await expect(ok).toBeInViewport();
    await expect(page).toHaveURL(/\/v5\/app\/page\/settings$/); // still Settings; the outcome parameters are gone
    await expect(hub.getByTestId("broker-account")).toHaveCount(2);

    const failures: Array<[string, string]> = [
      ["denied", "the sign-in was cancelled or refused at the broker"],
      ["missing_params", "the broker did not send back a sign-in code"],
      ["unknown_broker", "Nivesh does not know that broker"],
      ["invalid_state", "the sign-in could not be matched to this account"],
      ["state_expired", "the sign-in took more than ten minutes"],
      ["token_exchange_failed", "the broker did not accept the sign-in"],
    ];
    for (const [code, sentence] of failures) {
      await page.goto(`${APP}/page/settings?broker_error=${code}`);
      const bad = hub.getByTestId("broker-return-error");
      await expect(bad, code).toContainText(sentence);
      await expect(bad, code).toContainText("No account was added");
      await expect(bad, code).not.toContainText(code);
      await expect(bad, code).toBeInViewport();
      await expect(page).toHaveURL(/\/v5\/app\/page\/settings$/);
    }
  });

  test("a broker that cannot be connected: “Upload file” opens the upload form inside the hub, named for that broker", async ({ page }) => {
    let posts = 0;
    // routes/upload.py :: upload_portfolio — a Groww export of 4 rows.
    await page.route("**/api/portfolio/upload", (route) => {
      posts += 1;
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(uploaded(4, "groww", "Groww", "groww")) });
    });
    await page.goto(`${APP}/page/settings`);
    const hub = page.getByTestId("settings-broker-hub");
    await expect(hub.getByTestId("broker-hub-file")).toHaveCount(0);
    const groww = hub.getByTestId("broker-option").filter({ hasText: "Groww" });
    await expect(groww.getByTestId("broker-option-note")).toHaveText("Can’t be connected");
    await groww.getByRole("button", { name: "Upload a holdings file from Groww" }).click();
    const form = hub.getByTestId("holdings-file-upload");
    await expect(form.getByTestId("holdings-file-for")).toContainText("Download your holdings from Groww");
    await expect(form).toBeInViewport();
    await form.getByTestId("holdings-file").setInputFiles(XLSX);
    await form.getByTestId("holdings-file-submit").click();
    await expect(form.getByTestId("holdings-file-result")).toHaveText("4 holdings added from your Groww file. Any earlier Groww file is replaced.");
    expect(posts).toBe(1);

    // Closing it, and the route for any file.
    await hub.getByTestId("broker-hub-file-close").click();
    await expect(hub.getByTestId("broker-hub-file")).toHaveCount(0);
    await hub.getByTestId("broker-use-file").click();
    await expect(hub.getByTestId("holdings-file-upload")).toBeVisible();
    await expect(hub.getByTestId("holdings-file-for")).toHaveCount(0);
  });

  test("nothing connectable, and broker_hub switched off: the hub says which, never offers a sign-in, and offers the file", async ({ page }) => {
    await json(page, "**/api/broker/native/supported", SUPPORTED);
    await json(page, "**/api/broker/accounts", { accounts: [] });
    await page.goto(`${APP}/page/settings`);
    const hub = page.getByTestId("settings-broker-hub");
    await expect(hub.getByTestId("broker-accounts-count")).toHaveText("0");
    await expect(hub.getByTestId("broker-accounts-none")).toHaveText("None connected yet.");
    const none = hub.getByTestId("broker-none-connectable");
    await expect(none).toContainText("No broker can be connected right now. Upload your broker’s holdings file instead.");
    await expect(hub.locator(connectButtons)).toHaveCount(0);
    await expect(hub.getByTestId("broker-options").getByTestId("broker-option")).toHaveCount(5);
    await expect(hub).not.toContainText(/planned|not available yet|isn’t available yet/i);
    await expect(hub.getByTestId("not-connected")).toHaveCount(0);
    await none.getByTestId("broker-use-file").click();
    await expect(hub.getByTestId("holdings-file-upload")).toBeVisible();

    await nativeAccounts(page);
    await json(page, "**/api/auth/me", { ...ME, features: { ...ME.features, broker_hub: false } });
    await page.reload();
    await expect(hub.getByTestId("broker-hub-off")).toContainText("Broker connections are not switched on for this account.");
    await expect(hub.getByTestId("broker-none-connectable")).toHaveCount(0);
    await expect(hub.locator(connectButtons)).toHaveCount(0);
    await expect(hub.getByTestId("broker-reconnect")).toHaveCount(0);
    await expect(hub.getByTestId("broker-sync")).toHaveCount(0);
    await expect(hub.getByTestId("broker-account")).toHaveCount(2);
    await expect(hub.getByTestId("broker-disconnect").first()).toBeEnabled();
    await expect(hub.getByTestId("broker-hub-off").getByTestId("broker-use-file")).toBeVisible();
  });

  test("the hub's loading, error and retry states use the app's own blocks", async ({ page }) => {
    const down = { accounts: true, list: true };
    await page.route("**/api/broker/accounts", (route) => route.fulfill(down.accounts
      ? { status: 500, contentType: "application/json", body: JSON.stringify(envelope(500, "SYS-001", "boom")) }
      : { status: 200, contentType: "application/json", body: JSON.stringify(NATIVE_ACCOUNTS) }));
    await page.route("**/api/broker/native/supported", (route) => route.fulfill(down.list
      ? { status: 500, contentType: "application/json", body: JSON.stringify(envelope(500, "SYS-001", "boom")) }
      : { status: 200, contentType: "application/json", body: JSON.stringify(CONNECTABLE) }));
    await page.goto(`${APP}/page/settings`);
    const hub = page.getByTestId("settings-broker-hub");
    await expect(hub.getByRole("status", { name: "Loading broker accounts" })).toBeVisible();
    await expect(hub.getByText("Broker accounts didn’t load")).toBeVisible(SLOW);
    await expect(hub.getByText("The broker list didn’t load")).toBeVisible(SLOW);
    await expect(hub.getByTestId("broker-accounts-count")).toHaveCount(0); // no count is claimed
    await expect(hub.locator(connectButtons)).toHaveCount(0);

    // Each block retries on its own.
    down.list = false;
    await hub.getByRole("alert").filter({ hasText: "The broker list didn’t load" }).getByRole("button", { name: /Retry/ }).click();
    await expect(hub.locator(connectButtons)).toHaveCount(2);
    await expect(hub.getByText("Broker accounts didn’t load")).toBeVisible();
    down.accounts = false;
    await hub.getByRole("alert").filter({ hasText: "Broker accounts didn’t load" }).getByRole("button", { name: /Retry/ }).click();
    await expect(hub.getByTestId("broker-account")).toHaveCount(2);
    await expect(hub.getByTestId("broker-accounts-count")).toHaveText("2");
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

  /** GET /api/onboarding/state with the three counts the Portfolio step reads. */
  const stateWith = (accounts: number, live: number, holdings: number) => ({ ...STATE, broker_accounts: accounts, broker_accounts_live: live, holdings_count: holdings });

  test("the step leads with the broker: sources in order, Broker account open, what is on file, and skipping still possible", async ({ page }) => {
    let completes = 0;
    // routes/user.py :: complete_onboarding
    await page.route("**/api/user/complete-onboarding", (route) => {
      completes += 1;
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "ok", onboarding_completed: true }) });
    });
    await json(page, "**/api/broker/accounts", { accounts: [] });
    await json(page, "**/api/onboarding/state", stateWith(0, 0, 0));
    await toPortfolioStep(page);
    const step = page.getByTestId("onboarding-step-portfolio");
    await expect(step.getByRole("group", { name: "Where to import from" }).getByRole("button"))
      .toHaveText(["Broker account", "Broker file (XLS / CSV)", "CAS statement", "CAS from Gmail"]);
    await expect(page.getByTestId("onboarding-source-broker")).toHaveAttribute("aria-pressed", "true");
    for (const other of ["file", "cas", "gmail"]) await expect(page.getByTestId(`onboarding-source-${other}`)).toHaveAttribute("aria-pressed", "false");
    // The broker source is the hub Settings shows.
    await expect(step.getByTestId("broker-hub")).toBeVisible();
    await expect(step.getByTestId("broker-accounts-none")).toHaveText("None connected yet.");
    await expect(page.getByTestId("onboarding-on-file")).toContainText("Nothing yet. Connect a broker or add a file below, or skip this step.");
    await expect(step.getByRole("button", { name: TRADE })).toHaveCount(0);

    // Each of the other sources opens its own form.
    await page.getByTestId("onboarding-source-file").click();
    await expect(page.getByTestId("holdings-file-upload")).toBeVisible();
    await page.getByTestId("onboarding-source-cas").click();
    await expect(page.getByTestId("cas-upload")).toBeVisible();
    await page.getByTestId("onboarding-source-gmail").click();
    await expect(page.getByTestId("gmail-source")).toBeVisible();

    // Nothing has to be connected or uploaded: Continue and both skips are available.
    await expect(page.getByTestId("onboarding-next")).toBeEnabled();
    await expect(page.getByTestId("onboarding-skip")).toBeEnabled();
    await page.getByTestId("onboarding-skip-import").click();
    await expect(page).toHaveURL(/\/v5\/app$/);
    expect(completes).toBe(1);
  });

  test("a broker that cannot be connected is shown as such, and one tap switches to the file source for it", async ({ page }) => {
    await json(page, "**/api/broker/accounts", { accounts: [] });
    await toPortfolioStep(page);
    const step = page.getByTestId("onboarding-step-portfolio");
    // Fixture: no broker is connectable.
    await expect(step.getByTestId("broker-none-connectable")).toContainText("No broker can be connected right now.");
    await expect(step.locator(connectButtons)).toHaveCount(0);
    await expect(step.getByTestId("broker-readonly-note")).toContainText("never places, changes or cancels an order");
    await expect(step.getByTestId("broker-signin-missing")).toHaveCount(0);
    await expect(step.getByTestId("broker-options").locator(brokerIcon)).toHaveCount(5);

    const icici = step.getByTestId("broker-option").filter({ hasText: "ICICI Direct" });
    await expect(icici.getByTestId("broker-option-note")).toHaveText("Can’t be connected");
    await icici.getByRole("button", { name: "Upload a holdings file from ICICI Direct" }).click();
    await expect(page.getByTestId("onboarding-source-file")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("holdings-file-for")).toHaveText("Download your holdings from ICICI Direct as an Excel or CSV file, then choose it here.");
    await expect(page.getByTestId("broker-hub-file")).toHaveCount(0); // the step has its own file source; the hub opens no second form

    // The route for any file names no broker; so does picking the source by hand.
    await page.getByTestId("onboarding-source-broker").click();
    await step.getByTestId("broker-none-connectable").getByTestId("broker-use-file").click();
    await expect(page.getByTestId("onboarding-source-file")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("holdings-file-upload")).toBeVisible();
    await expect(page.getByTestId("holdings-file-for")).toHaveCount(0);
  });

  test("Broker account: Connect goes out with a path back to Get started; coming back reopens this step and it shows what is on file", async ({ page }) => {
    await json(page, "**/api/broker/native/supported", CONNECTABLE);
    let connected = false;
    await page.route("**/api/broker/accounts", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ accounts: connected ? [NATIVE_ACCOUNTS.accounts[0]] : [] }) }));
    // What the server counts before and after the sign-in (onboarding_state counts the stored rows).
    await page.route("**/api/onboarding/state", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(connected ? stateWith(1, 1, 3) : stateWith(0, 0, 0)) }));
    const hits = await startRoute(page, "zerodha");
    await toPortfolioStep(page);
    await expect(page.getByTestId("onboarding-on-file")).toContainText("Nothing yet.");
    await page.getByTestId("broker-connect-zerodha").click();
    await page.getByTestId("broker-connect-go").click();
    await expect(page.getByRole("heading", { name: "Fixture broker sign-in page" })).toBeVisible();
    expect(hits).toEqual(["fetch /v5/app/onboarding", "document /v5/app/onboarding"]);

    // The broker sends the browser back the way the callback does.
    connected = true;
    await page.goto(`${APP}/onboarding?broker_connected=zerodha&account_id=ba_fixture00011`);
    await expect(page.getByTestId("onboarding-step-portfolio")).toBeVisible();
    await expect(page.getByTestId("onboarding-source-broker")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("broker-return-connected")).toContainText("Signed in to Zerodha");
    await expect(page.getByTestId("broker-account-name")).toHaveText("Zerodha");
    await expect(page).toHaveURL(/\/v5\/app\/onboarding$/);
    // The step reflects it …
    await expect(page.getByTestId("onboarding-on-file-accounts")).toHaveText("1");
    await expect(page.getByTestId("onboarding-on-file-holdings")).toHaveText("3");
    await expect(page.getByTestId("onboarding-on-file")).toContainText("1 broker account connected · 3 holdings on file. You can continue.");
    await expect(page.getByTestId("onboarding-on-file-live")).toHaveCount(0); // every account can be read
    // … and the user can continue to the last step, which shows the same counts.
    await page.getByTestId("onboarding-next").click();
    await expect(page.getByTestId("onboarding-holdings-count")).toHaveText("3");
    await expect(page.getByTestId("onboarding-broker-accounts")).toHaveText("1");

    await page.goto(`${APP}/onboarding?broker_error=denied`);
    await expect(page.getByTestId("onboarding-step-portfolio")).toBeVisible();
    await expect(page.getByTestId("broker-return-error")).toContainText("cancelled or refused at the broker");
  });

  test("what is on file: an account that cannot be read right now is counted apart; a failed check says so and retries", async ({ page }) => {
    let ok = false;
    await page.route("**/api/onboarding/state", (route) => route.fulfill(ok
      ? { status: 200, contentType: "application/json", body: JSON.stringify(stateWith(2, 1, 42)) }
      : { status: 500, contentType: "application/json", body: JSON.stringify(envelope(500, "SYS-001", "boom")) }));
    await nativeAccounts(page);
    await toPortfolioStep(page);
    const step = page.getByTestId("onboarding-step-portfolio");
    await expect(step.getByText("Couldn’t check what is on file")).toBeVisible(SLOW);
    await expect(page.getByTestId("onboarding-on-file")).toHaveCount(0); // no count is claimed
    await expect(page.getByTestId("onboarding-next")).toBeEnabled();       // and it does not block the step

    ok = true;
    await step.getByRole("alert").filter({ hasText: "Couldn’t check what is on file" }).getByRole("button", { name: /Retry/ }).click();
    await expect(page.getByTestId("onboarding-on-file")).toContainText("2 broker accounts connected (1 can be read right now) · 42 holdings on file. You can continue.");
    await expect(page.getByTestId("onboarding-on-file-live")).toHaveText("1");
  });

  test("the mode picked on the first step survives the trip to the broker and back, and is cleared when setup ends", async ({ page }) => {
    await nativeAccounts(page);
    const stored = () => page.evaluate(() => window.localStorage.getItem("nivesh.copilot.onboarding-pick"));
    await page.goto(`${APP}/onboarding`);
    await expect(page.getByTestId("onboarding-mode-investor")).toHaveAttribute("aria-pressed", "true"); // the saved mode
    await page.getByTestId("onboarding-mode-advisor").click();
    await expect(page.getByTestId("onboarding-mode-advisor")).toHaveAttribute("aria-pressed", "true");

    // A broker sign-in leaves the app and loads it again on the Portfolio step.
    await page.goto(`${APP}/onboarding?broker_connected=zerodha&account_id=ba_fixture00011`);
    await expect(page.getByTestId("onboarding-step-portfolio")).toBeVisible();
    await page.getByTestId("onboarding-back").click();
    await page.getByTestId("onboarding-back").click();
    await expect(page.getByTestId("onboarding-mode-advisor")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("onboarding-mode-investor")).toHaveAttribute("aria-pressed", "false");

    await page.getByTestId("onboarding-skip").click();
    await expect(page.getByTestId("screen-onboarding")).toHaveCount(0);
    expect(await stored()).toBeNull();
  });

  test("broker_hub switched off: the step says so and still offers the file, a statement and skipping", async ({ page }) => {
    await json(page, "**/api/auth/me", { ...ME, features: { ...ME.features, broker_hub: false } });
    await json(page, "**/api/broker/native/supported", CONNECTABLE);
    await json(page, "**/api/broker/accounts", { accounts: [] });
    await toPortfolioStep(page);
    const step = page.getByTestId("onboarding-step-portfolio");
    await expect(step.getByTestId("broker-hub-off")).toContainText("Broker connections are not switched on for this account.");
    await expect(step.locator(connectButtons)).toHaveCount(0);
    await expect(page.getByTestId("onboarding-skip-import")).toBeEnabled();
    await step.getByTestId("broker-hub-off").getByTestId("broker-use-file").click();
    await expect(page.getByTestId("onboarding-source-file")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("holdings-file-upload")).toBeVisible();
    await page.getByTestId("onboarding-source-cas").click();
    await expect(page.getByTestId("cas-upload")).toBeVisible();
  });

  test("Broker file: takes .xlsx, .xls and .csv, names the exports it recognises, and says what happens to earlier files", async ({ page }) => {
    await toPortfolioStep(page);
    await page.getByTestId("onboarding-source-file").click();
    const form = page.getByTestId("holdings-file-upload");
    const input = form.getByTestId("holdings-file");
    const accept = ((await input.getAttribute("accept")) ?? "").split(",");
    for (const ext of [".xlsx", ".xls", ".csv"]) expect(accept, ext).toContain(ext);
    await expect(input).toHaveAttribute("aria-label", "Holdings file: .xlsx, .xls or .csv");
    await expect(form.getByRole("button", { name: "Choose a holdings file" })).toBeEnabled();
    // The ten exports helpers/statement_exports.py recognises, by display name.
    for (const name of ["Zerodha", "Groww", "Upstox", "Angel One", "ICICI Direct", "HDFC Securities", "Kotak Securities", "Dhan", "5paisa", "MF Central"]) {
      await expect(form.getByTestId("holdings-file-recognised"), name).toContainText(name);
    }
    const warning = form.getByTestId("holdings-file-warning");
    await expect(warning).toContainText("Rows are saved as soon as the file is read; there is no preview.");
    await expect(warning).toContainText("A new file from the same broker replaces that broker’s earlier file.");
    await expect(warning).toContainText("Any other sheet is added to what is on file, so uploading it twice adds its rows twice.");
    await expect(form.getByTestId("holdings-file-submit")).toBeDisabled(); // no file yet

    // A preview and column mapping are still missing, and the step says so; notes that stopped being true are gone.
    const missing = page.getByTestId("onboarding-file-preview-missing");
    await expect(missing).toContainText("Column mapping and a preview aren’t available yet");
    await expect(missing.getByTestId("not-connected-needs")).toBeVisible(); // admin fixture
    await expect(page.getByTestId("onboarding-step-portfolio")).not.toContainText(/\.xlsx only|save it as \.xlsx|plain digits|\/api\//i);
  });

  test("Broker file: a recognised broker export is sent once, the result names the broker, and the step shows what is on file", async ({ page }) => {
    const calls: Array<{ method: string; type: string }> = [];
    let onFile = 0;
    await json(page, "**/api/broker/accounts", { accounts: [] });
    await page.route("**/api/onboarding/state", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(stateWith(0, 0, onFile)) }));
    // routes/upload.py :: upload_portfolio — a Zerodha export of 12 rows.
    await page.route("**/api/portfolio/upload", (route) => {
      calls.push({ method: route.request().method(), type: (route.request().headers()["content-type"] ?? "").split(";")[0] });
      onFile = 12;
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(uploaded(12, "zerodha", "Zerodha", "zerodha")) });
    });
    await toPortfolioStep(page);
    await expect(page.getByTestId("onboarding-on-file")).toContainText("Nothing yet.");
    await page.getByTestId("onboarding-source-file").click();
    const form = page.getByTestId("holdings-file-upload");
    await form.getByTestId("holdings-file").setInputFiles(XLSX);
    await expect(form.getByTestId("holdings-file-name")).toHaveText("holdings-fixture.xlsx");
    await form.getByTestId("holdings-file-submit").click();
    const result = form.getByTestId("holdings-file-result");
    await expect(result).toHaveText("12 holdings added from your Zerodha file. Any earlier Zerodha file is replaced.");
    await expect(result).toHaveAttribute("data-format", "zerodha");
    await expect(form.getByTestId("holdings-file-count")).toHaveText("12");
    await expect(form.getByTestId("holdings-file-broker")).toHaveText("Zerodha");
    expect(calls).toEqual([{ method: "POST", type: "multipart/form-data" }]);

    // The step reflects it …
    await expect(page.getByTestId("onboarding-on-file-holdings")).toHaveText("12");
    await expect(page.getByTestId("onboarding-on-file")).toContainText("12 holdings on file. You can continue.");
    await expect(page.getByTestId("onboarding-on-file-accounts")).toHaveCount(0);
    // … and the user can continue.
    await page.getByTestId("onboarding-next").click();
    await expect(page.getByTestId("onboarding-imported-count")).toHaveText("12");
    await expect(page.getByTestId("onboarding-holdings-count")).toHaveText("12");
    await expect(page.getByTestId("onboarding-broker-accounts")).toHaveCount(0);
  });

  test("Broker file: a plain sheet and an unnamed broker's table are added without a broker; a file with nothing to add says so", async ({ page }) => {
    let reply = uploaded(2, null, null, "generic");
    await page.route("**/api/portfolio/upload", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(reply) }));
    await toPortfolioStep(page);
    await page.getByTestId("onboarding-source-file").click();
    const form = page.getByTestId("holdings-file-upload");
    const result = form.getByTestId("holdings-file-result");
    await form.getByTestId("holdings-file").setInputFiles(CSV);
    await form.getByTestId("holdings-file-submit").click();
    await expect(result).toHaveText("2 holdings added without a broker: the file was read as a plain sheet. Nothing on file was replaced.");
    await expect(result).toHaveAttribute("data-format", "generic");
    await expect(form.getByTestId("holdings-file-broker")).toHaveCount(0);

    reply = uploaded(1, null, null, "unidentified");
    await form.getByTestId("holdings-file-submit").click();
    await expect(result).toHaveText("1 holding added without a broker: Nivesh could not tell which broker this file came from. Nothing on file was replaced.");
    await expect(result).toHaveAttribute("data-format", "unidentified");

    // An empty file (the server sends no format), then a broker's file whose rows a connected account already holds.
    reply = uploaded(0, null, null, null);
    await form.getByTestId("holdings-file-submit").click();
    await expect(form.getByTestId("holdings-file-result-empty")).toHaveText("The server read the file but found no holdings in it.");
    await expect(result).toHaveCount(0);
    reply = uploaded(0, "zerodha", "Zerodha", "zerodha");
    await form.getByTestId("holdings-file-submit").click();
    await expect(form.getByTestId("holdings-file-result-empty")).toHaveText("The file was read as coming from Zerodha, but no holdings were added. A holding already read from a connected Zerodha account is not added again.");

    // A body without the count is a mismatch, not "nothing found".
    reply = { message: "fixture" } as unknown as typeof reply;
    await form.getByTestId("holdings-file-submit").click();
    await expect(form.getByTestId("holdings-file-error")).toHaveText("This file was not imported: the response was not in the expected shape.");
    await expect(form.getByTestId("holdings-file-result-empty")).toHaveCount(0);

    await page.getByTestId("onboarding-next").click();
    await expect(page.getByTestId("onboarding-imported-count")).toHaveText("1"); // the last upload that added anything
  });

  test("Broker file: a 400 shows the server's message; every other failure is in the form's own words, sent once, with no server text and no toast", async ({ page }) => {
    await json(page, "**/api/auth/me", { ...ME, is_admin: false });
    // helpers/statement_exports.py :: _UNRECOGNISED, shortened.
    const NO_TABLE = "Could not find a holdings table in this file. Upload the holdings file downloaded from Zerodha, Groww, Upstox, Angel One, ICICI Direct, HDFC Securities, Kotak Securities, Dhan, 5paisa or MF Central, or a sheet with Name, Quantity, Buy Price and Current Price columns.";
    let reply: { status: number; message: string } | "abort" = { status: 400, message: NO_TABLE };
    let posts = 0;
    await page.route("**/api/portfolio/upload", (route) => {
      posts += 1;
      if (reply === "abort") return route.abort();
      return route.fulfill({ status: reply.status, contentType: "application/json", body: JSON.stringify(envelope(reply.status, "FIXTURE", reply.message)) });
    });
    await toPortfolioStep(page);
    await page.getByTestId("onboarding-source-file").click();
    const form = page.getByTestId("holdings-file-upload");
    const err = form.getByTestId("holdings-file-error");
    await form.getByTestId("holdings-file").setInputFiles(XLS); // an .xls is sent like any other file
    await form.getByTestId("holdings-file-submit").click();
    await expect(err).toHaveText(`This file was not imported. ${NO_TABLE}`);
    await expect(form.getByTestId("holdings-file-result")).toHaveCount(0);
    await expect(form).not.toContainText("save it as .xlsx"); // the server reads .xls now

    const cases: Array<[number, string, string]> = [
      [500, "Traceback: XLRDError at /srv/app/helpers/statement_exports.py", "This file was not imported: the server reported an error."],
      [410, "Direct CAS PDF upload to this endpoint is no longer supported. Call POST /api/casparser/access-token", "This file was not imported: a PDF statement is imported under CAS statement, not here."],
      [413, "File too large (30000000 bytes; cap 26214400).", "This file was not imported: it is too large."],
      [415, "File contents do not match .xls signature.", "This file was not imported: it is not a readable .xlsx, .xls or .csv file."],
      [422, "File rejected: malware detected (Fixture-Test). Do not retry with the same file.", "This file was not imported: the server’s safety check rejected it."],
    ];
    for (const [status, message, sentence] of cases) {
      reply = { status, message };
      await form.getByTestId("holdings-file-submit").click();
      await expect(err, String(status)).toHaveText(sentence);
    }
    reply = "abort";
    await form.getByTestId("holdings-file-submit").click();
    await expect(err).toHaveText("This file was not imported: the network request failed.");

    // Nothing those answers said reached the page, in the form or in a toast, and no upload was sent twice.
    await expect(page.getByText(/Traceback|XLRDError|casparser|signature|malware|bytes; cap/)).toHaveCount(0);
    await expect(page.getByText(TOAST)).toHaveCount(0);
    await page.waitForLoadState("networkidle");
    expect(posts).toBe(7); // one per press: the 500 was not re-sent

    await page.getByTestId("onboarding-next").click();
    await expect(page.getByTestId("onboarding-imported-count")).toHaveCount(0);
  });

  test("Broker file: a PDF or another kind of file is stopped before it is sent", async ({ page }) => {
    let posts = 0;
    await page.route("**/api/portfolio/upload", (route) => { posts += 1; return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(uploaded(1, null, null, "generic")) }); });
    await toPortfolioStep(page);
    await page.getByTestId("onboarding-source-file").click();
    const form = page.getByTestId("holdings-file-upload");
    const wrong = form.getByTestId("holdings-file-type");
    await form.getByTestId("holdings-file").setInputFiles({ name: "FIXTURE_CAS.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4 fixture") });
    await expect(wrong).toHaveText("This file can’t be read here. Choose an .xlsx, .xls or .csv file. A CAS PDF is imported under CAS statement.");
    await expect(form.getByTestId("holdings-file-submit")).toBeDisabled();
    await form.getByTestId("holdings-file").setInputFiles({ name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("fixture") });
    await expect(wrong).toHaveText("This file can’t be read here. Choose an .xlsx, .xls or .csv file.");
    await expect(form.getByTestId("holdings-file-submit")).toBeDisabled();
    expect(posts).toBe(0);
    await form.getByTestId("holdings-file").setInputFiles(XLS);
    await expect(wrong).toHaveCount(0);
    await expect(form.getByTestId("holdings-file-submit")).toBeEnabled();
  });

  test("the last step shows the holdings and broker counts the server reports, and neither tile when both are zero", async ({ page }) => {
    await toPortfolioStep(page);
    await page.getByTestId("onboarding-next").click();
    await expect(page.getByTestId("onboarding-statement-period")).toHaveText("Sep/2026");
    // Fixture state: 2 broker accounts, 5 holdings.
    await expect(page.getByTestId("onboarding-holdings-count")).toHaveText("5");
    await expect(page.getByTestId("onboarding-broker-accounts")).toHaveText("2");

    await json(page, "**/api/onboarding/state", { ...stateWith(0, 0, 0), cas_statement_period: null, cas_portfolio_value_rs: null, cas_statement_date: null });
    await page.reload();
    await page.getByTestId("onboarding-next").click();
    await page.getByTestId("onboarding-next").click();
    await page.getByTestId("onboarding-next").click();
    const done = page.getByTestId("onboarding-step-done");
    await expect(done).toContainText("No portfolio on file");
    await expect(done).toContainText("Connect a broker or add a file any time from Settings.");
    await expect(page.getByTestId("onboarding-holdings-count")).toHaveCount(0);
    await expect(page.getByTestId("onboarding-broker-accounts")).toHaveCount(0);

    // A state without the counts the server always sends is a mismatch, not "nothing on file".
    const { holdings_count: _h, ...noCounts } = STATE;
    await json(page, "**/api/onboarding/state", noCounts);
    await page.reload();
    await page.getByTestId("onboarding-next").click();
    await page.getByTestId("onboarding-next").click();
    await expect(page.getByTestId("onboarding-step-portfolio").getByText("Couldn’t check what is on file")).toBeVisible();
    await expect(page.getByTestId("onboarding-on-file")).toHaveCount(0);
  });
});

// ── phone ────────────────────────────────────────────────────────────────

/** Text that is cut off inside `rootTestId`: an element that hides its overflow and is narrower than its content. */
async function clippedText(page: Page, rootTestId: string): Promise<string[]> {
  return page.getByTestId(rootTestId).first().evaluate((root) => {
    const out: string[] = [];
    for (const el of Array.from(root.querySelectorAll<HTMLElement>("*"))) {
      const text = el.textContent?.trim();
      if (!text || getComputedStyle(el).overflowX === "visible") continue;
      if (el.scrollWidth > el.clientWidth + 1) out.push(text.slice(0, 60));
    }
    return out;
  });
}

test.describe("Account screens — phone (390×844)", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("no sideways page scroll on Broker connections, Settings or the import step", async ({ page }) => {
    await account(page);

    // Nothing connectable; accounts linked through the middleware.
    await page.goto(`${APP}/page/brokers`);
    await expect(page.getByTestId("broker-account")).toHaveCount(2);
    await expect(page.getByTestId("broker-options").getByTestId("broker-option")).toHaveCount(5);
    await page.getByTestId("broker-more-toggle").click();
    await expect(page.getByTestId("broker-options-more").getByTestId("broker-option")).toHaveCount(16);
    await page.getByTestId("broker-account").nth(0).getByTestId("broker-disconnect").click(); // the widest card state
    await expectNoSidewaysScroll(page, "Broker connections");

    await page.goto(`${APP}/page/settings`);
    await expect(page.getByTestId("settings-consent")).toHaveCount(5);
    await expect(page.getByTestId("settings-activity-row")).toHaveCount(8);
    await expect(page.getByTestId("settings-snapshot-age")).toHaveValue("41");
    await expect(page.getByTestId("settings-broker-hub").getByTestId("broker-account")).toHaveCount(2);
    await expectNoSidewaysScroll(page, "Settings");

    await page.goto(`${APP}/onboarding`);
    await page.getByTestId("onboarding-next").click();
    await page.getByTestId("onboarding-next").click();
    for (const source of ["broker", "file", "cas", "gmail"]) {
      await page.getByTestId(`onboarding-source-${source}`).click();
      await expectNoSidewaysScroll(page, `Get started · ${source}`);
    }

    // Connectable brokers: the Connect rows, the confirm panel and an expired account.
    await nativeAccounts(page);
    await page.goto(`${APP}/page/brokers`);
    await expect(page.getByTestId("broker-reconnect")).toBeVisible();
    await page.getByTestId("broker-connect-zerodha").click();
    await expect(page.getByTestId("broker-connect-confirm")).toBeVisible();
    await expectNoSidewaysScroll(page, "Broker connections · connectable");
  });

  test("the Settings hub at phone width: cards, the remove and connect confirmations and the upload form fit, nothing is cut off, and it works by touch", async ({ page }) => {
    await account(page);
    await nativeAccounts(page);
    const hits = await startRoute(page, "zerodha");
    await page.goto(`${APP}/page/settings`);
    const hub = page.getByTestId("settings-broker-hub");
    await expect(hub.getByTestId("broker-account")).toHaveCount(2);
    await expect(hub.getByTestId("broker-account-id")).toHaveText(["••••42", "••••07"]);
    await expect(hub.getByTestId("broker-account-status")).toHaveText(["Connected", "Reconnect needed"]);
    await expect(hub.getByTestId("broker-fetched-count")).toHaveText("2");
    await expectNoSidewaysScroll(page, "Settings hub");
    expect(await clippedText(page, "settings-broker-hub"), "cut-off text in the hub").toEqual([]);

    // Open everything that can be open at once: the widest state of the hub.
    await hub.getByTestId("broker-account").nth(0).getByTestId("broker-disconnect").tap();
    await expect(hub.getByTestId("broker-disconnect-confirm")).toBeVisible();
    await hub.getByTestId("broker-more-toggle").tap();
    await expect(hub.getByTestId("broker-options-more").getByTestId("broker-option")).toHaveCount(16);
    await hub.getByTestId("broker-file-groww").tap();
    await expect(hub.getByTestId("holdings-file-for")).toContainText("Groww");
    await hub.getByTestId("broker-connect-zerodha").tap();
    await expect(hub.getByTestId("broker-connect-confirm")).toBeVisible();
    await expectNoSidewaysScroll(page, "Settings hub · everything open");
    expect(await clippedText(page, "settings-broker-hub"), "cut-off text in the hub, everything open").toEqual([]);

    await hub.getByTestId("broker-connect-go").tap();
    await expect(page.getByRole("heading", { name: "Fixture broker sign-in page" })).toBeVisible();
    expect(hits).toEqual(["fetch /v5/app/page/settings", "document /v5/app/page/settings"]);
  });

  test("the onboarding Portfolio step at phone width: every source fits, nothing is cut off, and the file route works by touch", async ({ page }) => {
    await account(page);
    await nativeAccounts(page);
    await json(page, "**/api/onboarding/state", { ...STATE, broker_accounts: 2, broker_accounts_live: 1, holdings_count: 42 });
    await page.goto(`${APP}/onboarding`);
    await page.getByTestId("onboarding-next").tap();
    await page.getByTestId("onboarding-next").tap();
    const step = page.getByTestId("onboarding-step-portfolio");
    await expect(step.getByRole("group", { name: "Where to import from" }).getByRole("button")).toHaveCount(4);
    await expect(page.getByTestId("onboarding-source-broker")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("onboarding-on-file")).toContainText("2 broker accounts connected (1 can be read right now) · 42 holdings on file.");
    await expect(step.getByTestId("broker-account")).toHaveCount(2);

    for (const source of ["broker", "file", "cas", "gmail"]) {
      await page.getByTestId(`onboarding-source-${source}`).tap();
      await expectNoSidewaysScroll(page, `Portfolio step · ${source}`);
      expect(await clippedText(page, "onboarding-step-portfolio"), `cut-off text · ${source}`).toEqual([]);
    }

    await page.getByTestId("onboarding-source-broker").tap();
    await step.getByTestId("broker-file-groww").tap();
    await expect(page.getByTestId("onboarding-source-file")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("holdings-file-for")).toContainText("Groww");
    await expectNoSidewaysScroll(page, "Portfolio step · file for Groww");
    await expect(page.getByTestId("onboarding-skip-import")).toBeEnabled();
    await expect(page.getByTestId("onboarding-next")).toBeEnabled();
  });
});

// ── screenshots ──────────────────────────────────────────────────────────
// Skipped unless SHOT_DIR is set (as in copilot-app-shots.spec.ts). The app
// scrolls inside its own content area, so each shot is taken in a viewport tall
// enough to show the whole block at the true width.

const SHOT_DIR = process.env.SHOT_DIR;

for (const size of [{ tag: "desktop", width: 1280, height: 800 }, { tag: "phone", width: 390, height: 844 }]) {
  test.describe(`broker hub shots — ${size.tag}`, () => {
    test.skip(!SHOT_DIR, "set SHOT_DIR to capture screenshots");
    test.use({ viewport: { width: size.width, height: size.height }, ...(size.tag === "phone" ? { hasTouch: true, isMobile: true } : {}) });

    test(`Settings hub and the onboarding Portfolio step — ${size.tag}`, async ({ page }) => {
      const shot = async (name: string, testId?: string) => {
        await page.waitForLoadState("networkidle");
        await page.evaluate(() => document.fonts.ready);
        const file = path.join(SHOT_DIR as string, `broker-hub-${size.tag}-${name}.png`);
        if (testId) await page.getByTestId(testId).first().screenshot({ path: file });
        else await page.screenshot({ path: file });
      };
      const tall = () => page.setViewportSize({ width: size.width, height: 4200 });
      const toStep = async () => {
        await page.goto(`${APP}/onboarding`);
        await page.getByTestId("onboarding-next").click();
        await page.getByTestId("onboarding-next").click();
        await expect(page.getByTestId("onboarding-step-portfolio")).toBeVisible();
      };

      await account(page);
      await nativeAccounts(page);
      await json(page, "**/api/onboarding/state", { ...STATE, broker_accounts: 2, broker_accounts_live: 1, holdings_count: 2 });

      // Settings, as the browser shows it on return from a broker (true viewport).
      await page.goto(`${APP}/page/settings?broker_connected=zerodha&account_id=ba_fixture00011`);
      await expect(page.getByTestId("broker-return-connected")).toBeVisible();
      await shot("settings-return-viewport");

      // Settings hub, whole block: two accounts (one needing a reconnect), two connectable brokers.
      await tall();
      await page.goto(`${APP}/page/settings`);
      await expect(page.getByTestId("settings-broker-hub").getByTestId("broker-account")).toHaveCount(2);
      await expect(page.getByTestId("broker-fetched-count")).toHaveText("2");
      await shot("settings-hub", "settings-broker-hub");
      await shot("settings-page", "screen-page-settings");
      // … with the remove confirmation, the connect confirmation and the upload form open.
      const hub = page.getByTestId("settings-broker-hub");
      await hub.getByTestId("broker-account").nth(0).getByTestId("broker-disconnect").click();
      await hub.getByTestId("broker-file-groww").click();
      await hub.getByTestId("broker-connect-zerodha").click();
      await expect(hub.getByTestId("broker-connect-confirm")).toBeVisible();
      await shot("settings-hub-open", "settings-broker-hub");

      // The standalone page: the same accounts and broker list, with statements and Gmail.
      await page.goto(`${APP}/page/brokers`);
      await expect(page.getByTestId("screen-page-brokers").getByTestId("broker-account")).toHaveCount(2);
      await expect(page.getByTestId("broker-fetched-count")).toHaveText("2");
      await shot("brokers-page", "screen-page-brokers");

      // Onboarding Portfolio step, broker source, then the file source for Groww.
      await toStep();
      await expect(page.getByTestId("onboarding-step-portfolio").getByTestId("broker-account")).toHaveCount(2);
      await shot("onboarding-portfolio", "screen-onboarding");
      await page.getByTestId("broker-file-groww").click();
      await expect(page.getByTestId("holdings-file-for")).toBeVisible();
      await shot("onboarding-file", "screen-onboarding");

      // Nothing connectable and nothing connected: what staging shows until app keys are set.
      await json(page, "**/api/broker/native/supported", SUPPORTED);
      await json(page, "**/api/broker/accounts", { accounts: [] });
      await json(page, "**/api/onboarding/state", { ...STATE, cas_statement_period: null, cas_portfolio_value_rs: null, cas_statement_date: null, broker_accounts: 0, broker_accounts_live: 0, holdings_count: 0 });
      await page.goto(`${APP}/page/settings`);
      await expect(page.getByTestId("broker-none-connectable")).toBeVisible();
      await shot("settings-hub-none-connectable", "settings-broker-hub");
      await toStep();
      await expect(page.getByTestId("broker-none-connectable")).toBeVisible();
      await shot("onboarding-portfolio-none-connectable", "screen-onboarding");

      // The onboarding step in the true viewport, as a user first sees it.
      await page.setViewportSize({ width: size.width, height: size.height });
      await shot("onboarding-portfolio-viewport");
    });
  });
}
