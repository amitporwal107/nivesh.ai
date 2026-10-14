/**
 * One-screen Copilot app (/v5/app) — "Import earlier statements" on the home
 * statement bar (views/StatementImport.tsx).
 *
 *   POST /api/onboarding/gmail/auto-import   body {"all_statements": true}
 *   backend/routes/onboarding_gmail.py :: _gmail_import_all_statements
 *
 * MOCK — not real data: every call is answered by a route mock. The answers are
 * the fixtures e2e/fixtures/copilot-statements-*.json, written in the shape the
 * backend sends (backend/services/cas_history_import.py) with synthetic values.
 * These tests prove what the screen does with each answer; they prove nothing
 * about the backend, which is covered by backend/tests/test_cas_import_all.py.
 *
 * Mocked APIs, production build — see pw.copilot-app.config.ts.
 */
import { test, expect, type Page } from "@playwright/test";
import fs from "fs";
import path from "path";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const APP = "/v5/app";
const FX = path.join(process.cwd(), "e2e", "fixtures");
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(FX, name), "utf-8"));

const BEFORE = load("copilot-statements-state-before.json");   // Aug/2026 on file
const AFTER = load("copilot-statements-state-after.json");     // Sep/2026 on file
const FIRST = load("copilot-statements-first.json");           // six read, two left, Sep now shown
const MORE = load("copilot-statements-more.json");             // the two left over
const STORED = load("copilot-statements-stored.json");         // everything already on record
const FAILED = load("copilot-statements-failed.json");         // no statement could be opened
const EMPTY = load("copilot-statements-empty.json");           // no CAS email in Gmail

interface Answer { status?: number; body: unknown }
interface Calls { posts: unknown[]; stateReads: number }

/** The home screen with the import endpoint answering `answers` in order (the last one repeats). */
async function home(page: Page, answers: Answer[], state: Record<string, unknown> = BEFORE): Promise<Calls> {
  const calls: Calls = { posts: [], stateReads: 0 };
  let onFile = state;
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  // routes/onboarding_gmail.py :: onboarding_state — what the statement bar reads.
  await page.route("**/api/onboarding/state", (route) => {
    calls.stateReads += 1;
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(onFile) });
  });
  await page.route("**/api/onboarding/gmail/auto-import", (route) => {
    calls.posts.push(route.request().postDataJSON());
    const a = answers[Math.min(calls.posts.length - 1, answers.length - 1)];
    const changed = (a.body as { mounted?: { changed?: boolean } })?.mounted?.changed === true;
    if ((a.status ?? 200) === 200 && changed) onFile = AFTER;      // the backend now has the September statement on file
    return route.fulfill({ status: a.status ?? 200, contentType: "application/json", body: JSON.stringify(a.body) });
  });
  return calls;
}

const rows = (page: Page) => page.getByTestId("statement-import-row");
const period = (page: Page, i: number) => rows(page).nth(i).getByTestId("statement-import-row-period");
const outcome = (page: Page, i: number) => rows(page).nth(i).getByTestId("statement-import-row-outcome");

async function expectNoSidewaysScroll(page: Page, where: string) {
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

test.describe("Home — import earlier statements", () => {
  test("TS-01 one click posts the opt-in body and lists each statement with its period and outcome", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    const calls = await home(page, [{ body: FIRST }]);
    await page.goto(APP);

    await expect(page.getByTestId("home-statement-period")).toHaveText("Aug/2026");
    const start = page.getByTestId("statement-import-start");
    await expect(start).toHaveText("Import earlier statements");
    await expect(rows(page)).toHaveCount(0);            // nothing is imported until the user asks
    expect(calls.posts).toHaveLength(0);
    await start.click();

    await expect(rows(page)).toHaveCount(FIRST.statements.length);     // 7
    expect(calls.posts).toEqual([{ all_statements: true }]);

    // Which statement the portfolio shows, in the backend's own sentence.
    await expect(page.getByTestId("statement-import-shown")).toHaveText("Showing Sep/2026");
    await expect(page.getByTestId("statement-import-reason")).toHaveText("Your portfolio now shows the NSDL statement for Sep/2026.");

    // Row by row, in the order sent.
    await expect(period(page, 0)).toHaveText("Sep/2026");
    await expect(rows(page).nth(0)).toContainText("NSDL · 42 holdings");
    await expect(outcome(page, 0)).toHaveText("Imported · now shown");
    await expect(period(page, 1)).toHaveText("Aug/2026");
    await expect(outcome(page, 1)).toHaveText("Already stored");
    await expect(outcome(page, 2)).toHaveText("Imported");                // Jul, NSDL
    // The CAMS statement for the same date as the NSDL one was not kept, and the row says why.
    await expect(rows(page).nth(3)).toContainText("CAMS");
    await expect(outcome(page, 3)).toHaveText("Already stored");
    await expect(rows(page).nth(3).getByTestId("statement-import-row-reason")).toHaveText("The NSDL statement for the same date is kept instead.");
    await expect(rows(page).nth(4)).toContainText("CDSL · 39 holdings");
    await expect(rows(page).nth(0).getByTestId("statement-import-row-reason")).toHaveCount(0);

    // What is left for the next call.
    await expect(page.getByTestId("statement-import-summary")).toHaveText("2 more statements to import · 1 could not be imported");
    await expect(page.getByTestId("statement-import-more")).toHaveText("Import more");

    // The bar above re-reads the statement on file: the backend now has September.
    await expect(page.getByTestId("home-statement-period")).toHaveText("Sep/2026");
    expect(errors).toEqual([]);
  });

  test("TS-02 a statement that failed is shown inline with the reason, beside the ones that worked", async ({ page }) => {
    await home(page, [{ body: FIRST }]);
    await page.goto(APP);
    await page.getByTestId("statement-import-start").click();

    const bad = rows(page).nth(6);
    await expect(bad).toHaveAttribute("data-status", "failed");
    await expect(bad.getByTestId("statement-import-row-period")).toHaveText("transaction-confirmation.pdf");   // no period: the file is named
    await expect(bad).toContainText("CAMS · emailed 19 Aug 2026");
    await expect(bad.getByTestId("statement-import-row-outcome")).toHaveText("Not imported");
    await expect(bad.getByTestId("statement-import-row-reason")).toHaveText("This PDF could not be read as a CAS statement.");
    await expect(bad).not.toContainText("holdings");
    await expect(page.locator('[data-testid="statement-import-row"][data-status="imported"]')).toHaveCount(FIRST.imported);   // 4
    await expect(page.getByTestId("statement-import-error")).toHaveCount(0);      // a failed statement is not a failed call
  });

  test("TS-03 Import more reads the rest; what this visit imported stays 'Imported'", async ({ page }) => {
    const calls = await home(page, [{ body: FIRST }, { body: MORE }]);
    await page.goto(APP);
    await page.getByTestId("statement-import-start").click();
    await expect(rows(page)).toHaveCount(7);
    await page.getByTestId("statement-import-more").click();

    await expect(rows(page)).toHaveCount(MORE.statements.length);       // 9
    expect(calls.posts).toEqual([{ all_statements: true }, { all_statements: true }]);
    // The second answer lists September as already stored; it was imported a moment ago, here.
    await expect(period(page, 0)).toHaveText("Sep/2026");
    await expect(outcome(page, 0)).toHaveText("Imported");
    await expect(outcome(page, 1)).toHaveText("Already stored");         // Aug was on record before this visit
    await expect(period(page, 6)).toHaveText("Apr/2026");
    await expect(outcome(page, 6)).toHaveText("Imported");
    await expect(period(page, 7)).toHaveText("Mar/2026");
    await expect(outcome(page, 7)).toHaveText("Imported");
    await expect(outcome(page, 8)).toHaveText("Not imported");

    await expect(page.getByTestId("statement-import-shown")).toHaveText("Showing Sep/2026");
    await expect(page.getByTestId("statement-import-summary")).toHaveText("All 9 statements were tried; 1 could not be imported");
    await expect(page.getByTestId("statement-import-more")).toHaveCount(0);       // nothing left: the offer goes away
  });

  test("TS-04 statements already on record are listed as stored and nothing is offered", async ({ page }) => {
    const calls = await home(page, [{ body: STORED }], AFTER);
    await page.goto(APP);
    await expect(page.getByTestId("home-statement-period")).toHaveText("Sep/2026");
    await page.waitForLoadState("networkidle");          // every first read of the page has finished
    const readsBefore = calls.stateReads;
    await page.getByTestId("statement-import-start").click();

    await expect(rows(page)).toHaveCount(3);
    for (const i of [0, 1, 2]) await expect(outcome(page, i)).toHaveText("Already stored");
    await expect(page.getByTestId("statement-import-shown")).toHaveText("Showing Sep/2026");
    await expect(page.getByTestId("statement-import-reason")).toHaveText("Your portfolio already shows the latest statement (Sep/2026).");
    await expect(page.getByTestId("statement-import-summary")).toHaveText("All 3 statements from the last 12 months are stored");
    await expect(page.getByTestId("statement-import-more")).toHaveCount(0);
    expect(calls.stateReads).toBe(readsBefore);          // nothing changed, so nothing is re-read
  });

  test("TS-05 when no statement could be opened, each one says why and the portfolio is unchanged", async ({ page }) => {
    await home(page, [{ body: FAILED }]);
    await page.goto(APP);
    await page.getByTestId("statement-import-start").click();

    await expect(rows(page)).toHaveCount(2);
    await expect(period(page, 0)).toHaveText("NSDLe-CAS_SEP_2026.PDF");
    for (const i of [0, 1]) {
      await expect(outcome(page, i)).toHaveText("Not imported");
      await expect(rows(page).nth(i).getByTestId("statement-import-row-reason")).toHaveText(
        "The password did not unlock this statement. Check the PAN or statement password under Sync Gmail.");
    }
    await expect(page.getByTestId("statement-import-shown")).toHaveText("Showing Aug/2026");
    await expect(page.getByTestId("statement-import-summary")).toHaveText("All 2 statements were tried; 2 could not be imported");
    await expect(page.getByTestId("home-statement-period")).toHaveText("Aug/2026");
  });

  test("TS-06 a failed call is shown inline without the server's wording, and Try again works", async ({ page }) => {
    const calls = await home(page, [{ status: 500, body: { detail: "Gmail scan failed: HttpError 503 backendError" } }, { body: FIRST }]);
    await page.goto(APP);
    await page.getByTestId("statement-import-start").click();

    const error = page.getByTestId("statement-import-error");
    await expect(error).toContainText("The import did not finish (the server answered 500). Nothing was changed by this attempt; try again.");
    await expect(error).not.toContainText("HttpError");
    await expect(rows(page)).toHaveCount(0);
    await expect(page.getByTestId("statement-import-shown")).toHaveCount(0);      // no result is made up for a failed call
    await expect(page.getByTestId("home-statement-period")).toHaveText("Aug/2026");

    await page.getByTestId("statement-import-retry").click();
    await expect(rows(page)).toHaveCount(7);
    await expect(error).toHaveCount(0);
    expect(calls.posts).toHaveLength(2);
  });

  for (const [name, status, detail, sentence] of [
    ["an expired Gmail session", 401, "Gmail session expired — please reconnect.", "Your Gmail connection has expired. Reconnect it with Sync Gmail, then try again."],
    ["a missing PAN", 400, "PAN missing — submit /api/onboarding/pan first.", "Your PAN is needed to open the statements. Add it with Sync Gmail, then try again."],
  ] as const) {
    test(`TS-07 ${name} is explained in plain words`, async ({ page }) => {
      await home(page, [{ status, body: { detail } }]);
      await page.goto(APP);
      await page.getByTestId("statement-import-start").click();
      await expect(page.getByTestId("statement-import-error")).toContainText(sentence);
      await expect(page.getByTestId("statement-import-error")).not.toContainText("/api/");
      await expect(page.getByTestId("copilot-home")).toBeVisible();           // the user stays signed in and on the page
    });
  }

  test("TS-08 no CAS email in Gmail is said plainly", async ({ page }) => {
    await home(page, [{ body: EMPTY }]);
    await page.goto(APP);
    await page.getByTestId("statement-import-start").click();
    await expect(page.getByTestId("statement-import-empty")).toHaveText("No CAS statements were found in this Gmail account in the last 12 months.");
    await expect(rows(page)).toHaveCount(0);
    await expect(page.getByTestId("statement-import-more")).toHaveCount(0);
  });

  test("TS-09 without a Gmail connection the import is not offered", async ({ page }) => {
    const calls = await home(page, [{ body: FIRST }], { ...BEFORE, gmail_connected: false });
    await page.goto(APP);
    await expect(page.getByTestId("home-statement-sync")).toHaveText("Connect Gmail");
    await expect(page.getByTestId("statement-import")).toHaveCount(0);
    expect(calls.posts).toHaveLength(0);
  });
});

test.describe("Home — import earlier statements at 390px", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("TS-10 the list, the reasons and Import more fit a phone without sideways scroll", async ({ page }) => {
    await home(page, [{ body: FIRST }, { body: MORE }]);
    await page.goto(APP);
    await expect(page.getByTestId("statement-import-start")).toBeVisible();
    await expectNoSidewaysScroll(page, "home, before the import");
    await page.getByTestId("statement-import-start").click();

    await expect(rows(page)).toHaveCount(7);
    await expect(page.getByTestId("statement-import-shown")).toHaveText("Showing Sep/2026");
    await rows(page).nth(6).scrollIntoViewIfNeeded();
    await expect(rows(page).nth(6).getByTestId("statement-import-row-reason")).toBeVisible();
    await expect(page.getByTestId("statement-import-more")).toBeVisible();
    await expectNoSidewaysScroll(page, "home, after the import");
    const bar = await page.getByTestId("home-statement-bar").boundingBox();
    expect(bar!.x + bar!.width).toBeLessThanOrEqual(390);

    await page.getByTestId("statement-import-more").click();
    await expect(rows(page)).toHaveCount(9);
    await expectNoSidewaysScroll(page, "home, after Import more");
  });
});

// Pictures for a reviewer, written only when SHOT_DIR is set (as in copilot-app-options.spec.ts). No assertions.
test.describe("Home — import earlier statements, pictures", () => {
  const DIR = process.env.SHOT_DIR;
  for (const [name, width, height] of [["desktop", 1280, 800], ["phone", 390, 844]] as const) {
    test(`statements picture ${name}`, async ({ page }) => {
      test.skip(!DIR, "set SHOT_DIR to capture screenshots");
      await page.setViewportSize({ width, height });
      await home(page, [{ body: FIRST }]);
      await page.goto(APP);
      await page.getByTestId("statement-import-start").click();
      await expect(rows(page)).toHaveCount(7);
      await page.getByTestId("home-statement-bar").scrollIntoViewIfNeeded();
      await page.screenshot({ path: path.join(DIR!, `statements-${name}.png`) });
    });
  }
});
