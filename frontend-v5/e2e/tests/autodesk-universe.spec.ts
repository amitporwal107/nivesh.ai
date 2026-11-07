/**
 * Simulation studio · wider universes (AD-SC-33, AD-SC-34). Test cases: docs/autodesk/testcases_scoring_v21.md.
 * API answered by route mocks (autodesk-mock.ts + autodesk-fixtures-studio-setup.ts — // MOCK — not real data).
 * Request bodies are checked against e2e/fixtures/autodesk/requests/studio-setup.json (posted to the real FastAPI app by
 * backend/tests/autodesk/test_ui_request_contracts.py).
 */
import { expect, test, type Page } from "@playwright/test";
import { collectConsoleErrors, expectContract, mockDesk, type RouteValue } from "./autodesk-mock";
import { NEW_SID, POL, setupRoutes, type SetupState } from "./autodesk-fixtures-studio-setup";

async function open(page: Page, routes: Record<string, RouteValue>) {
  const desk = await mockDesk(page, { routes });
  await page.goto("/autodesk/studio/new");
  await expect(page.getByTestId("studio-new")).toBeVisible();
  return desk;
}

const simPosts = (desk: { posts: { method: string; path: string; body: unknown }[] }) => desk.posts.filter((p) => p.path.startsWith("/simulations"));
const summaryRow = (page: Page, k: string) => page.getByTestId("setup-summary-row").filter({ hasText: k });
const CAVEAT = /survivorship bias/;

test("AD-SC-33 universe chips: F&O, Nifty 500, Total Market and your symbols are enabled; the survivorship caveat shows for index universes only", async ({ page }) => {
  const errors = collectConsoleErrors(page);
  await open(page, setupRoutes());
  for (const u of ["FNO", "NIFTY500", "TOTAL_MARKET", "SYMBOLS"]) await expect(page.getByTestId(`setup-uni-${u}`)).not.toHaveAttribute("aria-disabled", "true");
  await expect(page.getByTestId("setup-uni-FNO")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("setup-uni-caveat")).toHaveCount(0);

  await page.getByTestId("setup-uni-NIFTY500").click();
  await expect(page.getByTestId("setup-uni-NIFTY500")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("setup-uni-FNO")).toHaveAttribute("aria-pressed", "false");
  await expect(page.getByTestId("setup-uni-caveat")).toContainText(CAVEAT);
  await expect(page.getByTestId("setup-uni-caveat")).toContainText("cash only");
  await expect(summaryRow(page, "Universe")).toContainText("Nifty 500 · today's members");
  await expect(page.getByTestId("setup-create")).toBeEnabled();

  await page.getByTestId("setup-uni-TOTAL_MARKET").click();
  await expect(summaryRow(page, "Universe")).toContainText("Nifty Total Market · today's members");
  await expect(page.getByTestId("setup-uni-caveat")).toContainText(CAVEAT);

  await page.getByTestId("setup-uni-SYMBOLS").click();
  await expect(page.getByTestId("setup-uni-caveat")).toHaveCount(0);
  await page.getByTestId("setup-uni-FNO").click();
  await expect(page.getByTestId("setup-uni-caveat")).toHaveCount(0);
  await expect(summaryRow(page, "Universe")).toContainText("F&O underlyings of each session");
  expect(errors).toEqual([]);
});

for (const [id, name] of [["NIFTY500", "create_nifty500"], ["TOTAL_MARKET", "create_total_market"]] as const) {
  test(`AD-SC-34 ${id}: Create and start posts universe ${id} and no symbols (contract studio-setup.${name})`, async ({ page }) => {
    const st: SetupState = { created: null };
    const desk = await open(page, setupRoutes(st));
    await page.getByTestId(`setup-uni-${id}`).click();
    await page.getByTestId("setup-name").fill(id === "NIFTY500" ? "Studio nifty500" : "Studio total market");
    await page.getByTestId("setup-create").click();
    await expect(page).toHaveURL(new RegExp(`/autodesk/studio\\?sim=${NEW_SID}$`));
    const posts = simPosts(desk);
    expect(posts).toHaveLength(2);
    expectContract(posts[0], "studio-setup", name, { start_date: "2026-11-03", end_date: "2026-11-04", policy_id: POL });
    expect((posts[0].body as Record<string, unknown>).symbols).toBeUndefined();
    expectContract(posts[1], "studio-setup", "start", { simulation_id: NEW_SID });
  });
}
