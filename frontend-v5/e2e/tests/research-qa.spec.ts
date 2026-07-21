/**
 * Research — QA validation exercise (/research/qa).
 *
 * The page is entirely client-side (renders the two onboarding docs + a fill-in
 * checklist, persists to localStorage, exports Markdown). It makes NO backend
 * calls, so these mocked tests prove the REAL behaviour of the page — not just a
 * rendering contract. Auth is mocked (mockApi answers /api/auth/me) so RequireAuth
 * lets the login-gated route render.
 *
 * Runs against the local Vite dev server. Each test gets a fresh browser context,
 * so localStorage starts empty per test; the persistence test uses page.reload()
 * within the same context.
 */
import { test, expect, type Page } from "@playwright/test";
import { mockApi } from "../helpers/api-mock";

const QA_URL = "/v5/research/qa";

async function openChecklist(page: Page) {
  await page.goto(QA_URL);
  await expect(page.getByTestId("qa-page")).toBeVisible();
  await page.getByTestId("qa-tab-checklist").click();
  await expect(page.getByTestId("qa-checklist")).toBeVisible();
}

test.describe("Research QA exercise", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, "populated");
  });

  test("TC-1 loads with Overview, tabs switch", async ({ page }) => {
    await page.goto(QA_URL);
    await expect(page.getByTestId("qa-page")).toBeVisible();
    await expect(page.getByTestId("qa-overview")).toBeVisible();
    // Overview carries the two docs' substance.
    await expect(page.getByTestId("qa-overview")).toContainText("Filings Intelligence");
    await expect(page.getByTestId("qa-overview")).toContainText("source of truth");

    await page.getByTestId("qa-tab-checklist").click();
    await expect(page.getByTestId("qa-checklist")).toBeVisible();
    await expect(page.getByTestId("qa-overview")).toHaveCount(0);

    await page.getByTestId("qa-tab-overview").click();
    await expect(page.getByTestId("qa-overview")).toBeVisible();
  });

  test("TC-2 checklist covers UI, data, API, bug, verdict sections", async ({ page }) => {
    await openChecklist(page);
    // UI rows U1..U12
    await expect(page.getByTestId("pf-U1")).toBeVisible();
    await expect(page.getByTestId("pf-U12")).toBeVisible();
    // 5 filing blocks
    await expect(page.getByTestId("filing-1")).toBeVisible();
    await expect(page.getByTestId("filing-5")).toBeVisible();
    // API rows A1..A5
    await expect(page.getByTestId("pf-A1")).toBeVisible();
    await expect(page.getByTestId("pf-A5")).toBeVisible();
    // verdict tallies
    await expect(page.getByTestId("qa-tallies")).toBeVisible();
  });

  test("TC-3 answers persist across reload (localStorage)", async ({ page }) => {
    await openChecklist(page);
    await page.getByTestId("pf-U1").getByRole("button", { name: "PASS" }).click();
    const note = page.locator('input[placeholder="Notes / what you saw"]').first();
    await note.fill("loaded clean, no errors");

    await page.reload();
    await page.getByTestId("qa-tab-checklist").click();

    await expect(page.locator('input[placeholder="Notes / what you saw"]').first())
      .toHaveValue("loaded clean, no errors");
    await expect(page.getByTestId("pf-U1").getByRole("button", { name: "PASS" }))
      .toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("qa-tallies")).toContainText("UI");
  });

  test("TC-4 match toggle + add bug update the page", async ({ page }) => {
    await openChecklist(page);
    // toggle first match (summary faithful) inside filing #1
    const firstMatchYes = page.getByTestId("filing-1").locator(".qa-m-btn.yes").first();
    await firstMatchYes.click();
    await expect(firstMatchYes).toHaveClass(/on/);

    // add a bug row
    await page.getByTestId("qa-add-bug").click();
    await expect(page.getByTestId("bug-0")).toBeVisible();
    await expect(page.getByTestId("qa-tallies")).toContainText("Bugs");
  });

  test("TC-5 copy report writes Markdown to the clipboard", async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await openChecklist(page);
    // fill the intern name so the report has identifying content
    await page.locator('input[placeholder="Intern name"]').fill("Test Intern");
    await page.getByTestId("qa-copy").click();
    await expect(page.getByTestId("qa-copy")).toContainText("Copied!");

    const clip = await page.evaluate(() => navigator.clipboard.readText());
    expect(clip).toContain("# Research app — QA validation report");
    expect(clip).toContain("Test Intern");
    expect(clip).toContain("## 2. UI checklist");
  });

  test("TC-6 reset clears answers", async ({ page }) => {
    await openChecklist(page);
    const name = page.locator('input[placeholder="Intern name"]');
    await name.fill("Someone");
    await expect(name).toHaveValue("Someone");

    page.once("dialog", (d) => d.accept());
    await page.getByTestId("qa-reset").click();
    await expect(page.locator('input[placeholder="Intern name"]')).toHaveValue("");
  });

  test("TC-7 reachable from the Research rail; back link returns", async ({ page }) => {
    // minimal filings mocks so the Research shell renders (empty but valid shapes)
    await page.route("**/api/filings/feed**", (r) =>
      r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, total: 0, facets: {}, rows: [] }) }));
    await page.route("**/api/filings/signals**", (r) =>
      r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, signals: [] }) }));
    await page.route("**/api/filings/portfolio-held**", (r) =>
      r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, names: [], isins: [], symbols: [] }) }));

    await page.goto("/v5/research");
    const railQa = page.getByTestId("rail-qa");
    await expect(railQa).toBeVisible();
    await railQa.click();
    await expect(page).toHaveURL(/\/research\/qa$/);
    await expect(page.getByTestId("qa-page")).toBeVisible();

    // back link returns to /research
    await page.getByTestId("qa-back").click();
    await expect(page).toHaveURL(/\/research$/);
  });
});
