/**
 * QA Gate 2 — Recommendation engine E2E tests.
 *
 * 6 named flows:
 *   1. Gate state: requires_persona  → shows "Set up your risk profile" CTA
 *   2. Gate state: requires_goal     → shows "Add a goal" CTA
 *   3. Tax impact card               → collapsible panel renders and toggles
 *   4. Confirmation drawer           → opens on requiresConfirmation rec, 3 states work
 *   5. ELSS-locked                   → Apply renders aria-disabled, not a normal button
 *   6. Severity ordering             → first card is severe when any severe rec exists
 *
 * All tests use mocked API routes (no live backend required).
 */
import { test, expect } from "@playwright/test";
import { mockApi, mockApiWithPlan } from "../helpers/api-mock";
import path from "path";
import fs from "fs";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

function loadFixture(name: string) {
  return JSON.parse(
    fs.readFileSync(path.join(__dirname, "..", "fixtures", name), "utf-8"),
  );
}

// mockApiWithPlan handles all routes in one pass (no double-route registration)

/** Wait for the React app to mount (root has children) before asserting page content. */
async function waitForApp(page: Parameters<typeof mockApi>[0]) {
  await page.waitForFunction(
    () => (document.getElementById("root")?.children.length ?? 0) > 0,
    { timeout: 20_000, polling: 200 },
  );
  // Also wait for network to settle
  await page.waitForLoadState("networkidle").catch(() => {});
}

/** Wait for at least one recommendation card to appear. */
async function waitForCards(page: Parameters<typeof mockApi>[0]) {
  await waitForApp(page);
  // SeverityBadge renders aria-label="Severity: X" on every card
  await page.locator('[aria-label^="Severity:"]').first().waitFor({ timeout: 15_000 });
}


// ── Flow 1: Gate — requires_persona ──────────────────────────────────────────

test.describe("Gate state: requires_persona", () => {
  test("shows risk-profile CTA when persona not set", async ({ page }) => {
    await mockApiWithPlan(page, "plans-requires-persona.json");

    await page.goto("/v5/recommendations");
    await waitForApp(page);

    await expect(page.getByRole("heading", { name: /set up your risk profile/i })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole("button", { name: /set up risk profile/i })).toBeVisible();
  });
});


// ── Flow 2: Gate — requires_goal ─────────────────────────────────────────────

test.describe("Gate state: requires_goal", () => {
  test("shows add-a-goal CTA when no goals exist", async ({ page }) => {
    await mockApiWithPlan(page, "plans-requires-goal.json");

    await page.goto("/v5/recommendations");
    await waitForApp(page);

    await expect(page.getByRole("heading", { name: /add a goal/i })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole("button", { name: /add your first goal/i })).toBeVisible();
  });
});


// ── Flow 3: Tax impact card ───────────────────────────────────────────────────

test.describe("Tax impact panel", () => {
  test("renders TaxImpactPanel collapsed by default", async ({ page }) => {
    await mockApiWithPlan(page, "plans-rec-scenarios.json");

    await page.goto("/v5/recommendations");
    await waitForCards(page);

    // TaxImpactPanel toggle button contains the text "Tax impact"
    const taxToggle = page.locator("button[aria-expanded]").filter({ hasText: /tax impact/i }).first();
    await expect(taxToggle).toBeVisible();
    await expect(taxToggle).toHaveAttribute("aria-expanded", "false");
  });

  test("TaxImpactPanel expands and shows LTCG row when toggled", async ({ page }) => {
    await mockApiWithPlan(page, "plans-rec-scenarios.json");

    await page.goto("/v5/recommendations");
    await waitForCards(page);

    const taxToggle = page.locator("button[aria-expanded]").filter({ hasText: /tax impact/i }).first();
    await taxToggle.scrollIntoViewIfNeeded();
    await taxToggle.click();

    await expect(taxToggle).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByText("LTCG", { exact: true }).first()).toBeVisible();
  });

  test("TaxImpactPanel aria-controls references visible body element", async ({ page }) => {
    test.slow(); // allow extra time for all cards to stabilise after load
    await mockApiWithPlan(page, "plans-rec-scenarios.json");

    await page.goto("/v5/recommendations");
    await waitForCards(page);

    // Wait specifically for the tax toggle to appear (may render slightly after severity badges)
    const taxToggle = page.locator("button[aria-expanded]").filter({ hasText: /tax impact/i }).first();
    await taxToggle.waitFor({ state: "visible", timeout: 20_000 });
    const controlsId = await taxToggle.getAttribute("aria-controls");
    expect(controlsId).toBeTruthy();
    // Use attribute selector — React useId() generates IDs with colons (:r5:) that break CSS #id selectors
    await expect(page.locator(`[id="${controlsId}"]`)).toBeAttached();
  });
});


// ── Flow 4: Confirmation drawer ───────────────────────────────────────────────

test.describe("Confirmation drawer", () => {
  test("opens drawer when clicking 'Review & Apply' on a requiresConfirmation rec", async ({ page }) => {
    await mockApiWithPlan(page, "plans-rec-scenarios.json");

    await page.goto("/v5/recommendations");
    await waitForCards(page);

    // Button text is "Review & Apply" — find by text content (aria-label overrides accessible name)
    const applyBtn = page.locator("button").filter({ hasText: /review & apply/i }).first();
    await applyBtn.scrollIntoViewIfNeeded();
    await applyBtn.click();

    const drawer = page.locator('[role="dialog"]').first();
    await expect(drawer).toBeVisible();
    await expect(drawer.getByRole("heading", { name: /confirm this action/i })).toBeVisible();
  });

  test("drawer Cancel button closes the drawer", async ({ page }) => {
    await mockApiWithPlan(page, "plans-rec-scenarios.json");

    await page.goto("/v5/recommendations");
    await waitForCards(page);

    await page.locator("button").filter({ hasText: /review & apply/i }).first().click();
    const drawer = page.locator('[role="dialog"]').first();
    await expect(drawer).toBeVisible();

    await drawer.getByRole("button", { name: /cancel/i }).click();
    await expect(drawer).not.toBeVisible();
  });

  test("Escape key closes the drawer", async ({ page }) => {
    await mockApiWithPlan(page, "plans-rec-scenarios.json");

    await page.goto("/v5/recommendations");
    await waitForCards(page);

    await page.locator("button").filter({ hasText: /review & apply/i }).first().click();
    const escDrawer = page.locator('[role="dialog"]').first();
    await expect(escDrawer).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(escDrawer).not.toBeVisible();
  });

  test("drawer shows tax impact when present", async ({ page }) => {
    await mockApiWithPlan(page, "plans-rec-scenarios.json");

    await page.goto("/v5/recommendations");
    await waitForCards(page);

    await page.locator("button").filter({ hasText: /review & apply/i }).first().click();
    const drawer = page.locator('[role="dialog"]').first();
    await expect(drawer).toBeVisible();
    // TaxImpactPanel inside drawer renders with defaultOpen=true — LTCG visible
    await expect(drawer.getByText("LTCG", { exact: true })).toBeVisible();
  });
});


// ── Flow 5: ELSS-locked ───────────────────────────────────────────────────────

test.describe("ELSS lock-in state", () => {
  test("locked holding renders aria-disabled button instead of normal Apply", async ({ page }) => {
    await mockApiWithPlan(page, "plans-elss-locked.json");

    await page.goto("/v5/recommendations");
    await waitForCards(page);

    // aria-disabled=true is set on the locked button
    await expect(page.locator('[aria-disabled="true"]').first()).toBeVisible();
    await expect(page.getByText("Locked", { exact: true }).first()).toBeVisible();
    // Regular Apply/Review buttons must not exist
    const applyBtns = page.locator("button").filter({ hasText: /^apply$|review & apply/i });
    await expect(applyBtns).toHaveCount(0);
  });

  test("lock-in tooltip text visible near the locked button", async ({ page }) => {
    await mockApiWithPlan(page, "plans-elss-locked.json");

    await page.goto("/v5/recommendations");
    await waitForCards(page);

    await expect(page.getByText(/ELSS lock-in applies/i)).toBeVisible();
  });
});


// ── Flow 6: Severity ordering ─────────────────────────────────────────────────

test.describe("Severity ordering", () => {
  test("first recommendation card has SeverityBadge 'Severe' when severe rec exists", async ({ page }) => {
    await mockApiWithPlan(page, "plans-rec-scenarios.json");

    await page.goto("/v5/recommendations");
    await waitForCards(page);

    // plans-rec-scenarios has severe first, minor second — ArbitrationEngine sort enforces this
    const firstBadge = page.locator('[aria-label^="Severity:"]').first();
    await expect(firstBadge).toHaveAttribute("aria-label", "Severity: Severe");
  });

  test("minor badge appears after severe badge in DOM order", async ({ page }) => {
    test.slow(); // last test in the batch — allow more time for Vite to serve the page
    await mockApiWithPlan(page, "plans-rec-scenarios.json");

    await page.goto("/v5/recommendations");
    await waitForCards(page);

    const badges = page.locator('[aria-label^="Severity:"]');
    await expect(badges).toHaveCount(2); // 2 actions in fixture
    await expect(badges.nth(0)).toHaveAttribute("aria-label", "Severity: Severe");
    // Second badge must be something other than Severe
    const secondLabel = await badges.nth(1).getAttribute("aria-label");
    expect(secondLabel).not.toBe("Severity: Severe");
  });
});


// ── Live region (post-apply announcement) ────────────────────────────────────

test.describe("Post-apply live region", () => {
  test("role=status element exists on each recommendation card", async ({ page }) => {
    await mockApiWithPlan(page, "plans-rec-scenarios.json");

    await page.goto("/v5/recommendations");
    await waitForCards(page);

    // Each RecommendationCard renders a role=status live region (sr-only, for screen readers)
    const liveRegions = page.locator('[role="status"]');
    await expect(liveRegions).toHaveCount(2); // 2 cards in fixture
  });
});
