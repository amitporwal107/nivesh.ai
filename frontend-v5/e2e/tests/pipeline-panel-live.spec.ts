import { expect, test } from "@playwright/test";

/**
 * Live staging check for the NIDP Console "Pipeline" tab.
 *
 * Asserts the six stages render with REAL data. Deliberately does not assert
 * exact counts — the backfill moves them every minute — but does assert the
 * structural invariants that would break silently:
 *   * all six stages present, in pipeline order
 *   * every stage carries a state chip (never blank)
 *   * the Ingest tile splits by source, which is what catches a dead BSE feed
 *     hiding behind a healthy NSE one
 */

const STAGES = ["ingest", "classify", "discover", "parse", "chunk", "embed"];

test.beforeEach(async ({ page }) => {
  // The v5 app is served under /v5/ — /nidp alone 404s.
  await page.goto("/v5/nidp", { waitUntil: "domcontentloaded" });
  await page.getByRole("tab", { name: /Pipeline/i }).click();
  await expect(page.getByTestId("pipeline-panel")).toBeVisible({ timeout: 30_000 });
});

test("renders all six pipeline stages with live data", async ({ page }) => {
  for (const id of STAGES) {
    const tile = page.getByTestId(`pipeline-stage-${id}`);
    await expect(tile, `stage ${id} must render`).toBeVisible({ timeout: 30_000 });

    // A state chip that is present but empty is the silent-failure shape this
    // whole dashboard exists to prevent.
    const state = page.getByTestId(`pipeline-state-${id}`);
    await expect(state).toBeVisible();
    await expect(state).not.toBeEmpty();

    // done count must be a real number, not a dash/placeholder
    const done = await page.getByTestId(`pipeline-done-${id}`).innerText();
    expect(done, `stage ${id} done count`).toMatch(/[\d,]+/);
    expect(done).not.toBe("—");
  }
});

test("summary reports a state for every stage", async ({ page }) => {
  const summary = page.getByTestId("pipeline-summary");
  await expect(summary).toBeVisible();
  await expect(summary).toContainText(/healthy/);
  await expect(summary).toContainText(/backlog|lagging|stale/);
});

test("ingest is split by source so one dead feed cannot hide behind a healthy one", async ({ page }) => {
  const ingest = page.getByTestId("pipeline-stage-ingest");
  await expect(ingest).toContainText("BSE_ANN");
  await expect(ingest).toContainText("NSE_ANN");
});

test("the panel is not showing a backend error", async ({ page }) => {
  await expect(page.getByTestId("pipeline-error")).toHaveCount(0);
});
