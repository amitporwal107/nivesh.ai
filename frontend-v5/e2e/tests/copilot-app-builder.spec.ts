/**
 * One-screen Copilot app (/v5/app/builder) — the Tool builder: a template for
 * each tool the shell already has, and the data source pool they draw from.
 *
 * Test-case ids (TC-B*) match test_reports/copilot_tools_wiring_*.md.
 * The builder reads no API: its templates and pool are code
 * (screens/internal/tool-templates.ts, data-sources.ts). The mocks only sign
 * the shell in as the fixture admin. Production build — see pw.copilot-app.config.ts.
 */
import { test, expect, type Page } from "@playwright/test";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const URL = "/v5/app/builder";

async function open(page: Page) {
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.goto(URL);
  await expect(page.getByTestId("screen-builder")).toBeVisible();
}

const template = (page: Page, id: string) => page.locator(`[data-testid="builder-template"][data-template="${id}"]`);

async function poolIds(page: Page, status: string) {
  return page
    .locator(`[data-testid="builder-pool-row"]:has([data-testid="builder-pool-status"][data-status="${status}"])`)
    .evaluateAll((els) => els.map((el) => el.getAttribute("data-source")));
}

async function noSidewaysPageScroll(page: Page) {
  const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(over, "the page scrolls sideways").toBeLessThanOrEqual(0);
}

test.describe("Tool builder — templates and data source pool", () => {
  test("TC-B1 starts empty, with a template per tool and the whole pool", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await open(page);
    // Nothing is prefilled: a template is loaded only when asked for.
    await expect(page.getByTestId("builder-contract-empty")).toBeVisible();
    await expect(page.getByTestId("builder-checklist-done")).toHaveText("0");
    await expect(page.getByTestId("builder-template-gaps")).toHaveCount(0);
    await expect(page.getByTestId("builder-data-status")).toHaveCount(0);

    // One template for each tool in the shell, grouped by who the tool is for.
    await expect(page.getByTestId("builder-template")).toHaveCount(21);
    for (const id of [
      "portfolio-analysis", "recommendations", "risk", "goals", "tax",
      "trader-desk", "options-lab", "strategy-builder",
      "advisor-book", "advisor-workspace", "client-360",
      "research", "screener", "markets", "watchlist", "saved", "action-plan", "ledger", "paper-trades", "brokers", "copilot-chat",
    ]) {
      await expect(template(page, id), `no template for ${id}`).toHaveCount(1);
    }
    await expect(template(page, "screener")).toContainText("Screener");
    await expect(template(page, "screener")).toContainText("3 data sources");

    // The pool: every source with its connection status, and nothing else called a status.
    await expect(page.getByTestId("builder-pool-row")).toHaveCount(38);
    expect(await poolIds(page, "partial")).toEqual(["filings", "nidp-features", "trendlyne-fundamentals", "fno-bhavcopy", "broker-accounts"]);
    expect(await poolIds(page, "planned")).toEqual(["kite-market-data", "entity-logos"]);
    expect([...new Set(await page.getByTestId("builder-pool-status").allInnerTexts())].map((t) => t.toLowerCase()).sort()).toEqual(["connected", "partial", "planned"]);
    await expect(page.locator('[data-testid="builder-pool-row"][data-source="nidp-features"] [data-testid="builder-pool-used-by"]')).toContainText("Screener");
    await expect(page.locator('[data-testid="builder-pool-row"][data-source="feed-health"] [data-testid="builder-pool-used-by"]')).toHaveText(/No tool yet/);
    const text = await page.getByTestId("screen-builder").innerText();
    for (const word of ["In review", "IN REVIEW", "Draft v", "Deprecated"]) expect(text.includes(word), `shows "${word}"`).toBe(false);

    // There is still no backend for tool definitions, and the screen says so.
    await expect(page.getByTestId("builder-save")).toBeDisabled();
    await expect(page.getByTestId("builder-send-review")).toBeDisabled();
    await expect(page.getByTestId("builder-not-connected")).toBeVisible();
    await noSidewaysPageScroll(page);
    expect(errors).toEqual([]);
  });

  test("TC-B2 a template fills the draft, stays editable, and typed work is never replaced without asking", async ({ page }) => {
    await open(page);
    const dialogs: string[] = [];
    let answer: "accept" | "dismiss" = "dismiss";
    page.on("dialog", async (d) => {
      dialogs.push(d.message());
      if (answer === "accept") await d.accept();
      else await d.dismiss();
    });

    await template(page, "screener").click();
    expect(dialogs, "no question for an empty draft").toEqual([]);
    await expect(page.getByTestId("builder-name")).toHaveValue("Screener");
    await expect(page.getByTestId("builder-checklist-done")).toHaveText("9");
    const contract = page.getByTestId("builder-contract");
    await expect(contract).toContainText("tool: screener");
    await expect(contract).toContainText("personas: [investor, trader, advisor]");
    await expect(contract).toContainText("- Which stocks pass these rules today?");
    // Its data rows are pool sources, each with the pool's status for it.
    await expect(page.getByTestId("builder-data-row")).toHaveCount(3);
    const pills = await page.getByTestId("builder-data-status").evaluateAll((els) => els.map((e) => `${e.getAttribute("data-source")}=${e.getAttribute("data-status")}`));
    expect(pills).toEqual(["nidp-features=partial", "strategy-builder=connected", "saved-screens=connected"]);
    // What the tool cannot do yet is shown beside the template, not hidden.
    await expect(page.getByTestId("builder-template-gaps")).toBeVisible();
    await expect(page.getByTestId("builder-pool-row")).toHaveCount(38);

    // An unedited template is replaced without a question.
    await template(page, "markets").click();
    expect(dialogs).toEqual([]);
    await expect(page.getByTestId("builder-name")).toHaveValue("Markets");

    // Edited: the builder asks. Dismiss keeps the draft, accept replaces it.
    await page.getByTestId("builder-name").fill("Markets, my version");
    await expect(contract).toContainText("tool: markets_my_version");
    await template(page, "screener").click();
    expect(dialogs.length).toBe(1);
    expect(dialogs[0]).toContain("Replace this draft with the Screener template?");
    await expect(page.getByTestId("builder-name")).toHaveValue("Markets, my version");
    answer = "accept";
    await template(page, "screener").click();
    expect(dialogs.length).toBe(2);
    await expect(page.getByTestId("builder-name")).toHaveValue("Screener");

    // Picking a source from the pool adds its row with the pool's freshness.
    await page.getByTestId("builder-source-picker").selectOption("kite-market-data");
    await expect(page.getByTestId("builder-data-row")).toHaveCount(4);
    const last = page.getByTestId("builder-data-row").last();
    await expect(last.getByTestId("builder-data-status")).toHaveAttribute("data-status", "planned");
    await expect(page.getByTestId("builder-source-picker")).toHaveValue("");

    // A free-text row is still possible and carries no status.
    await page.getByTestId("builder-data-add").click();
    const free = page.getByTestId("builder-data-row").last();
    await free.getByTestId("builder-data-source").fill("A spreadsheet from the desk");
    await expect(free.getByTestId("builder-data-status")).toHaveCount(0);
    await expect(contract).toContainText("- A spreadsheet from the desk (required)");

    // The pool can be narrowed to one tool, and collapsed.
    await page.getByTestId("builder-pool-filter").selectOption("screener");
    await expect(page.getByTestId("builder-pool-row")).toHaveCount(3);
    await expect(page.getByTestId("builder-pool-need")).toHaveCount(3);
    await page.getByTestId("builder-pool-filter").selectOption("");
    await expect(page.getByTestId("builder-pool-row")).toHaveCount(38);
    await page.getByTestId("builder-pool-toggle").click();
    await expect(page.getByTestId("builder-pool-row")).toHaveCount(0);
    await page.getByTestId("builder-pool-toggle").click();
    await expect(page.getByTestId("builder-pool-row")).toHaveCount(38);

    // The draft survives a reload with the template it came from; Clear empties both.
    await page.reload();
    await expect(page.getByTestId("builder-name")).toHaveValue("Screener");
    await expect(page.getByTestId("builder-template-loaded")).toContainText("Screener");
    await page.getByTestId("builder-clear").click();
    await expect(page.getByTestId("builder-contract-empty")).toBeVisible();
    await expect(page.getByTestId("builder-checklist-done")).toHaveText("0");
    await expect(page.getByTestId("builder-template-loaded")).toHaveCount(0);
  });

  test("TC-B3 every template is complete and names only sources that are in the pool", async ({ page }) => {
    await open(page);
    const ids = await page.getByTestId("builder-template").evaluateAll((els) => els.map((e) => e.getAttribute("data-template") as string));
    for (const id of ids) {
      await template(page, id).click();
      const rows = await page.getByTestId("builder-data-row").count();
      expect(rows, `${id}: no data source`).toBeGreaterThan(0);
      expect(await page.getByTestId("builder-data-status").count(), `${id}: a data row is not a pool source`).toBe(rows);
      await expect(page.getByTestId("builder-checklist-done"), `${id}: checklist`).toHaveText("9");
      // The owner's rule: nothing in the product places an order.
      await expect(page.getByTestId("builder-contract"), `${id}: guardrail`).toContainText(/no order placement/i);
    }
  });

  test("TC-B4 phone (390×844): no sideways page scroll; the pool table scrolls inside its own box", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await open(page);
    await noSidewaysPageScroll(page);
    await template(page, "options-lab").click();
    await expect(page.getByTestId("builder-name")).toHaveValue("Options lab");
    await noSidewaysPageScroll(page);
    const box = page.getByRole("region", { name: "Data source pool table" });
    const m = await box.evaluate((el) => ({ scrollW: el.scrollWidth, clientW: el.clientWidth }));
    expect(m.scrollW).toBeGreaterThan(m.clientW);
  });
});
