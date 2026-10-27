/**
 * Results This Week — CONTRACT test of the per-stock results file against REAL backend bodies.
 *
 * REAL DATA, not mock: e2e/fixtures/results_file_staging_20261027.json holds results-stock-v1 bodies for MANKIND (declared,
 * 3 results-day analyses), BAJAJ-AUTO (declared, no analysis: scanned results PDF) and HEROMOTOCO (upcoming), built
 * read-only on staging from PR #381's branch for 2026-10-27, and a minimal list body made of those three real rows.
 * Expected values are read from the fixture, not from the screen. Other routes answer 503 on purpose.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { mockApi } from "../helpers/api-mock";

const here = path.dirname(fileURLToPath(import.meta.url));
const FX = JSON.parse(fs.readFileSync(path.join(here, "..", "fixtures", "results_file_staging_20261027.json"), "utf8"));
const PAGE = "/v5/app/page/watchlist";
const SLOW = { timeout: 20_000 };
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const BANNED = [/\bpicks?\b/i, /recommend/i, /\bbuy\b/i, /\bsell\b/i, /beat the street/i, /beat expectations/i];

async function setup(page: Page, errors: string[]) {
  page.on("pageerror", (e) => errors.push(String(e)));
  await mockApi(page, "populated");
  await page.clock.setFixedTime(new Date("2026-10-27T13:30:00Z"));
  await page.route("**/api/chat/sessions", (r) => json(r, []));
  await page.route("**/api/positional/watchlist*", (r) => json(r, { detail: "contract test: not under test" }, 503));
  await page.route("**/api/positional/picks*", (r) => json(r, { detail: "contract test: not under test" }, 503));
  await page.route(/\/api\/desk\/results-week(\?|$)/, (r) => json(r, FX.week));
  await page.route(/\/api\/desk\/results-week\/stock\//, (r) => {
    const sym = decodeURIComponent(new URL(r.request().url()).pathname.split("/").pop() ?? "");
    return FX.files[sym] ? json(r, FX.files[sym]) : json(r, { detail: { code: "no_results_meeting", message: "not in fixture" } }, 404);
  });
}

async function openFile(page: Page, sym: string) {
  await page.goto(PAGE);
  await expect(page.getByTestId("rtw-list")).toBeVisible(SLOW);
  await page.getByTestId("rtw-seg-all").click();                             // the All list holds every results name
  await page.getByTestId(`rtw-open-${sym}`).click(SLOW);
  await expect(page.getByTestId("results-file")).toBeVisible(SLOW);
}

test.describe("Results file — real staging bodies (desktop 1440)", () => {
  test.use({ viewport: { width: 1440, height: 1000 } });

  test("MANKIND: preview, the result with sentiment, analyst views not connected, the track with the expiry day", async ({ page }) => {
    const errors: string[] = [];
    await setup(page, errors);
    await openFile(page, "MANKIND");
    const f = FX.files.MANKIND;
    await expect(page.getByTestId("results-file-preview-lines").locator("li")).toHaveCount(f.preview.lines.length, SLOW);
    await expect(page.getByTestId("results-file-result-items").getByTestId("results-file-item")).toHaveCount(f.commentary.results.length);
    await expect(page.getByTestId("results-file-sentiment-band")).toContainText(/moderately positive/i);
    await expect(page.getByTestId("results-file-analyst-nc")).toBeVisible();
    await expect(page.getByTestId("results-file-track-table").locator("tbody tr")).toHaveCount(f.track.sessions.length);
    // the screen capitalises the first letter of the route's text
    expect((await page.getByTestId("results-file-track-after-snap").innerText()).toLowerCase()).toContain(f.track.after.text.toLowerCase());
    await expect(page.getByTestId("results-file-coverage")).toContainText(f.commentary.coverage.note.split(";")[0]);
    // the wording rule covers the app's own text; filing summaries quote the company (MANKIND's acquisition says "to buy 70 %")
    let own = "";
    for (const id of ["results-file-preview", "results-file-analyst", "results-file-track", "results-file-scores"]) own += await page.getByTestId(id).innerText();
    for (const b of BANNED) expect(own, `banned ${b}`).not.toMatch(b);
    expect(errors, "uncaught page errors").toEqual([]);
  });

  test("BAJAJ-AUTO: no analysis — the result says so, no sentiment, coverage explains; the after reading is the rollover", async ({ page }) => {
    const errors: string[] = [];
    await setup(page, errors);
    await openFile(page, "BAJAJ-AUTO");
    const f = FX.files["BAJAJ-AUTO"];
    expect(f.commentary.results.length).toBe(0);
    await expect(page.getByTestId("results-file-sentiment-na")).toBeVisible(SLOW);
    await expect(page.getByTestId("results-file-coverage")).toContainText("have a stored analysis");
    await expect(page.getByTestId("results-file-track-after-snap")).toContainText(/rollover 79\.8 % vs its usual 86\.0 %/i);
    expect(errors, "uncaught page errors").toEqual([]);
  });

  test("HEROMOTOCO: upcoming — positioning so far, no after, results not declared yet", async ({ page }) => {
    const errors: string[] = [];
    await setup(page, errors);
    await openFile(page, "HEROMOTOCO");
    await expect(page.getByTestId("results-file-track-after-snap")).toHaveText("results not declared yet", SLOW);
    await expect(page.getByTestId("results-file-preview-lines").locator("li")).toHaveCount(FX.files.HEROMOTOCO.preview.lines.length);
    expect(errors, "uncaught page errors").toEqual([]);
  });
});
