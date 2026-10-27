/**
 * Results week — CONTRACT test against the real backend response shape.
 *
 * REAL DATA, not mock: e2e/fixtures/results_week_staging_20261027.json is the GET /api/desk/results-week body built
 * read-only on staging from branch feat/earnings-surprise-tracker for 2026-10-27 (trimmed: all 35 declared rows, a sample of
 * pending and upcoming rows, the top 20 ideas per list; `counts` are the full week's). The neighbouring routes the view
 * also reads (market strip, macro, calendar) are answered with failures on purpose: the Results week blocks must still render.
 * Why: mocked payloads written by hand can drift from the backend (a mocked POST once hid a backend 422); this spec renders
 * what the backend actually returns. Expected values below are read from the fixture, not from the screen.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { mockApi } from "../helpers/api-mock";

const here = path.dirname(fileURLToPath(import.meta.url));
const RW = JSON.parse(fs.readFileSync(path.join(here, "..", "fixtures", "results_week_staging_20261027.json"), "utf8"));
const DESK = "/v5/app/trader/desk";
const SLOW = { timeout: 20_000 };
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const BANNED = ["beat the street", "beat expectations", "recommend", "buy now"];

async function setup(page: Page, errors: string[]) {
  page.on("pageerror", (e) => errors.push(String(e)));
  await mockApi(page, "populated");
  await page.clock.setFixedTime(new Date("2026-10-27T13:30:00Z"));
  await page.route("**/api/chat/sessions", (r) => json(r, []));
  for (const p of ["**/api/markets/home", "**/api/markets/sector-returns", "**/api/markets/macro-calendar?*", "**/api/markets/events-calendar?*",
                   "**/api/markets/events-calendar/expectations*", "**/api/markets/events-calendar/history*"]) {
    await page.route(p, (r) => json(r, { detail: "contract test: not under test" }, 503));
  }
  await page.route("**/api/desk/results-week*", (r) => json(r, RW));
}

const declared = (RW.results as any[]).filter((r) => r.status === "declared");
const above = declared.filter((r) => r.verdict?.label === "above");
const pending = (RW.results as any[]).filter((r) => r.status === "pending");
const upcoming = (RW.results as any[]).filter((r) => r.status === "upcoming");

test.describe("Results week — real 27 Oct response (desktop 1440)", () => {
  test.use({ viewport: { width: 1440, height: 1000 } });

  test("Events › Results week renders the real body: basis, counts, declared / pending / upcoming rows, a drawer", async ({ page }) => {
    const errors: string[] = [];
    await setup(page, errors);
    await page.goto(`${DESK}?tab=events`);
    await page.getByTestId("events-view-rw").click(SLOW);
    await expect(page.getByTestId("results-week")).toBeVisible(SLOW);
    await expect(page.getByTestId("results-week-basis")).toContainText(/historical trend/i);
    await expect(page.getByTestId("results-week-count-declared")).toContainText(String(RW.counts.declared));
    expect(above.length).toBeGreaterThan(0);
    for (const r of above) await expect(page.getByTestId(`results-week-row-${r.symbol}`)).toContainText(/above/i, SLOW);
    const p = pending[0];
    await expect(page.getByTestId(`results-week-pending-note-${p.symbol}`)).toBeVisible(SLOW);
    const u = upcoming[0];
    await expect(page.getByTestId(`results-week-row-${u.symbol}`)).toBeVisible(SLOW);
    // the drawer of a declared row with the coming-months F&O block opens and shows its parts
    const withFno = declared.find((r) => r.fno && r.fno_buildup) ?? declared[0];
    await page.getByTestId(`results-week-open-${withFno.symbol}`).click();
    await expect(page.getByRole("dialog")).toBeVisible(SLOW);
    await expect(page.getByRole("dialog")).toContainText(withFno.symbol);
    const text = (await page.getByTestId("results-week").innerText()).toLowerCase();
    for (const w of BANNED) expect(text, `banned phrase "${w}"`).not.toContain(w);
    expect(errors, "uncaught page errors").toEqual([]);
  });

  test("Scanner › Results week ideas renders the real ideas: F&O first, All toggle, the untested note", async ({ page }) => {
    const errors: string[] = [];
    await setup(page, errors);
    await page.goto(`${DESK}?tab=events`);
    await page.getByTestId("events-view-rw").click(SLOW);
    const box = page.getByTestId("results-week-ideas");
    await expect(box).toBeVisible(SLOW);
    const firstFno = RW.ideas.fno[0];
    await expect(page.getByTestId(`results-week-idea-${firstFno.symbol}`).getByTestId("results-week-idea-rank")).toHaveText("01", SLOW);
    await expect(page.getByTestId(`results-week-idea-${firstFno.symbol}`).getByTestId("results-week-idea-why")).toContainText(firstFno.why.split(";")[0]);
    await page.getByTestId("results-week-ideas-toggle-all").click();
    const firstAll = RW.ideas.all[0];
    await expect(page.getByTestId(`results-week-idea-${firstAll.symbol}`).getByTestId("results-week-idea-rank")).toHaveText("01", SLOW);
    await expect(page.getByTestId("results-week-ideas-note")).toContainText(RW.ideas.note);
    expect(errors, "uncaught page errors").toEqual([]);
  });
});
