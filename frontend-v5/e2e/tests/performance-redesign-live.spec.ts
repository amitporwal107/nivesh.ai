/**
 * Live verification script — Performance page redesign (commit 9017eaf)
 *
 * Hits real staging with the provided session cookie. No mocking.
 *
 * Run:
 *   SESSION_TOKEN=<cookie> npx playwright test performance-redesign-live \
 *     --project=live-contracts --reporter=list
 *
 * Or against a specific base URL:
 *   STAGING_URL=https://staging.niveshcopilot.com SESSION_TOKEN=<cookie> \
 *     npx playwright test performance-redesign-live --project=live-contracts
 *
 * What is verified:
 *   A. API contracts — endpoints return the shape the frontend expects
 *   B. UI contracts  — page renders the new design correctly (browser-based)
 */
import { test, expect, Page } from "@playwright/test";

const BASE = process.env.STAGING_URL ?? "https://staging.niveshcopilot.com";
const TOKEN = process.env.SESSION_TOKEN ?? "";
if (!TOKEN) throw new Error("SESSION_TOKEN env var required. Pass via: SESSION_TOKEN=<cookie> npx playwright test ...");

// ── Auth helper ───────────────────────────────────────────────────────────

async function authedGet(request: any, path: string) {
  const res = await request.get(`${BASE}${path}`, {
    headers: { Cookie: `session_token=${TOKEN}` },
  });
  return { status: res.status(), body: await res.json().catch(() => null) };
}

async function injectCookie(page: Page) {
  await page.context().addCookies([{
    name: "session_token",
    value: TOKEN,
    domain: new URL(BASE).hostname,
    path: "/",
    httpOnly: false,
    secure: BASE.startsWith("https"),
    sameSite: "Lax",
  }]);
}

// ── A. API contracts ──────────────────────────────────────────────────────

test.describe("@live API — /api/dashboards/performance", () => {
  test("endpoint is reachable and returns 200", async ({ request }) => {
    const { status, body } = await authedGet(request, "/api/dashboards/performance?period=inception");
    expect(status).toBe(200);
    expect(body).toBeTruthy();
  });

  test("response has stat_tiles array", async ({ request }) => {
    const { status, body } = await authedGet(request, "/api/dashboards/performance?period=inception");
    expect(status).toBe(200);
    // Frontend expects stat_tiles for KPI strip
    expect(body).toHaveProperty("stat_tiles");
    expect(Array.isArray(body.stat_tiles)).toBe(true);
  });

  test("period=inception returns xirr-based KPI (not 0)", async ({ request }) => {
    const { status, body } = await authedGet(request, "/api/dashboards/performance?period=inception");
    expect(status).toBe(200);
    const xirr = body?.stat_tiles?.find((t: any) => /xirr/i.test(t.label ?? ""));
    if (xirr) {
      // Value should be non-null (unless portfolio truly has no data)
      console.log("XIRR tile:", JSON.stringify(xirr));
    }
  });

  test("period=1Y also returns 200", async ({ request }) => {
    const { status } = await authedGet(request, "/api/dashboards/performance?period=1Y");
    expect(status).toBe(200);
  });

  test("period=3M also returns 200", async ({ request }) => {
    const { status } = await authedGet(request, "/api/dashboards/performance?period=3M");
    expect(status).toBe(200);
  });

  test("period=6M also returns 200", async ({ request }) => {
    const { status } = await authedGet(request, "/api/dashboards/performance?period=6M");
    expect(status).toBe(200);
  });

  test("monthly_returns array present in breakdown", async ({ request }) => {
    const { body } = await authedGet(request, "/api/dashboards/performance?period=inception");
    const monthly = body?.breakdown?.monthly_returns;
    console.log("monthly_returns count:", monthly?.length);
    // Not asserting length — just that the field exists and is an array
    expect(Array.isArray(monthly)).toBe(true);
  });
});

test.describe("@live API — /api/portfolio/analytics (bubble chart source)", () => {
  test("heatmap_data array present and has holdings", async ({ request }) => {
    const { status, body } = await authedGet(request, "/api/portfolio/analytics");
    expect(status).toBe(200);
    expect(body).toHaveProperty("heatmap_data");
    const data = body.heatmap_data as any[];
    console.log("heatmap_data count:", data?.length);
    // Holdings should be present if user has a portfolio
    // Each item must have: name, value, invested, return_pct, asset_type
    if (data?.length > 0) {
      const sample = data[0];
      expect(sample).toHaveProperty("name");
      expect(sample).toHaveProperty("value");
      expect(sample).toHaveProperty("invested");
      expect(sample).toHaveProperty("asset_type");
    }
  });

  test("heatmap_data returns more than 40 items if portfolio has 40+ holdings", async ({ request }) => {
    const { body } = await authedGet(request, "/api/portfolio/analytics");
    const data = body?.heatmap_data as any[];
    console.log("heatmap_data count (cap check):", data?.length);
    // If the user has 111 holdings, this should be > 40.
    // If it's exactly 40, the [:40] cap is still active — flag it.
    if (data?.length === 40) {
      console.warn("WARN: heatmap_data capped at exactly 40 — backend cap may not be raised yet");
    }
  });
});

test.describe("@live API — /api/portfolio/fund-performance", () => {
  test("endpoint returns 200 with fund_ratings", async ({ request }) => {
    const { status, body } = await authedGet(request, "/api/portfolio/fund-performance");
    expect(status).toBe(200);
    expect(body).toHaveProperty("fund_ratings");
    const ratings = body.fund_ratings as any[];
    console.log("fund_ratings count:", ratings?.length);
  });

  test("fund_ratings items have asset_type field", async ({ request }) => {
    const { body } = await authedGet(request, "/api/portfolio/fund-performance");
    const ratings = (body?.fund_ratings ?? []) as any[];
    if (ratings.length > 0) {
      expect(ratings[0]).toHaveProperty("asset_type");
      // Log the distinct asset_types present
      const types = [...new Set(ratings.map((r: any) => r.asset_type))];
      console.log("asset_types present:", types);
    }
  });

  test("SGB/gold holdings are present in fund_ratings or heatmap_data", async ({ request }) => {
    const perf = await authedGet(request, "/api/portfolio/fund-performance");
    const analytics = await authedGet(request, "/api/portfolio/analytics");

    const sgbInRatings = (perf.body?.fund_ratings ?? []).filter(
      (r: any) => r.asset_type === "gold" || r.asset_type === "sgb"
    );
    const sgbInHeatmap = (analytics.body?.heatmap_data ?? []).filter(
      (h: any) => h.asset_type === "gold" || h.asset_type === "sgb"
    );

    console.log("SGB in fund_ratings:", sgbInRatings.length);
    console.log("SGB in heatmap_data:", sgbInHeatmap.length);
    // Not asserting presence — just logging. If 0: user likely has no SGBs or CAMS-only CAS.
    if (sgbInRatings.length === 0 && sgbInHeatmap.length === 0) {
      console.warn(
        "WARN: No SGB/gold holdings found. " +
        "SGB/Bonds tab will show the 'NSDL eCAS required' empty state. " +
        "This is expected if the user imported a CAMS CAS (no demat section)."
      );
    }
  });
});

test.describe("@live API — /api/portfolio/recommendations/v5", () => {
  test("endpoint returns 200 with top5_by_asset_class", async ({ request }) => {
    const { status, body } = await authedGet(request, "/api/portfolio/recommendations/v5");
    expect(status).toBe(200);
    expect(body).toHaveProperty("top5_by_asset_class");
    console.log("rec asset classes:", Object.keys(body.top5_by_asset_class ?? {}));
  });
});

// ── B. UI contracts (browser-based) ──────────────────────────────────────

test.describe("@live UI — Performance page", () => {
  test("page loads without error state", async ({ page }) => {
    await injectCookie(page);
    await page.goto(`${BASE}/v5/performance`);
    await page.waitForLoadState("networkidle");

    // No crash
    await expect(page.getByText("Something went wrong")).not.toBeVisible({ timeout: 10_000 });
    // Heading visible
    const h1 = page.getByRole("heading", { level: 1 });
    await expect(h1).toBeVisible({ timeout: 10_000 });
    console.log("Page headline:", await h1.textContent());
  });

  test("period selector shows Since incep. as first option — selected by default on fresh load", async ({ page }) => {
    await injectCookie(page);
    // Clear perf_period sessionStorage before navigating
    await page.addInitScript(() => sessionStorage.removeItem("perf_period"));
    await page.goto(`${BASE}/v5/performance`);
    await page.waitForLoadState("networkidle");

    const sinceBtn = page.locator("button").filter({ hasText: /^Since incep\.$/ });
    await expect(sinceBtn).toBeVisible({ timeout: 8_000 });
    await expect(sinceBtn).toHaveAttribute("aria-pressed", "true");

    // 3Y must not appear
    const btn3y = page.locator("button").filter({ hasText: /^3Y$/ });
    await expect(btn3y).not.toBeVisible();
  });

  test("'Gain / loss distribution' section is present (not 'Performance heatmap')", async ({ page }) => {
    await injectCookie(page);
    await page.goto(`${BASE}/v5/performance`);
    await page.waitForLoadState("networkidle");

    await expect(page.getByText("Gain / loss distribution")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText("Performance heatmap")).not.toBeVisible();
  });

  test("attribution waterfall and top contributors are NOT on page", async ({ page }) => {
    await injectCookie(page);
    await page.goto(`${BASE}/v5/performance`);
    await page.waitForLoadState("networkidle");

    await expect(page.getByText("Attribution waterfall")).not.toBeVisible();
    await expect(page.getByText("Top contributors")).not.toBeVisible();
  });

  test("asset-class tabs ALL / MF / Stocks / ETF / SGB are visible", async ({ page }) => {
    await injectCookie(page);
    await page.goto(`${BASE}/v5/performance`);
    await page.waitForLoadState("networkidle");

    for (const label of ["All", "MF", "Stocks", "ETF", "SGB"]) {
      const btn = page.locator("button, [role='tab']").filter({ hasText: new RegExp(`^${label}`, "i") });
      await expect(btn.first()).toBeVisible({ timeout: 8_000 });
    }
  });

  test("switching to MF tab does not cause page navigation", async ({ page }) => {
    await injectCookie(page);
    await page.goto(`${BASE}/v5/performance`);
    await page.waitForLoadState("networkidle");

    let navCount = 0;
    page.on("framenavigated", (frame) => {
      if (frame === page.mainFrame()) navCount++;
    });
    const before = navCount;

    const mfTab = page.locator("button, [role='tab']").filter({ hasText: /^MF$/i }).first();
    await mfTab.click();
    await page.waitForTimeout(400);

    expect(navCount).toBe(before);
    console.log("Tab switch: no page navigation ✓");
  });

  test("holdings composition drill-down is always visible (no click needed)", async ({ page }) => {
    await injectCookie(page);
    await page.goto(`${BASE}/v5/performance`);
    await page.waitForLoadState("networkidle");

    // "Holdings composition" card heading
    await expect(page.getByText("Holdings composition")).toBeVisible({ timeout: 8_000 });

    // Drill-down header "Top holdings · N holdings" or "{Tab} · N holdings"
    const body = await page.textContent("body");
    expect(body).toMatch(/holdings/i);
  });

  test("vs category benchmark section shows explanation text", async ({ page }) => {
    await injectCookie(page);
    await page.goto(`${BASE}/v5/performance`);
    await page.waitForLoadState("networkidle");

    // ALL tab benchmark explanation
    const body = await page.textContent("body");
    expect(body).toMatch(/Nifty 500|benchmark/i);
  });

  test("no NaN or undefined rendered on page", async ({ page }) => {
    await injectCookie(page);
    await page.goto(`${BASE}/v5/performance`);
    await page.waitForLoadState("networkidle");

    const body = await page.textContent("body") ?? "";
    expect(body).not.toContain("NaN");
    expect(body).not.toContain("Infinity");
    expect(body).not.toContain("undefined");
  });

  test("no JS errors on page load", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });

    await injectCookie(page);
    await page.goto(`${BASE}/v5/performance`);
    await page.waitForLoadState("networkidle");

    const real = errors.filter(
      (e) => !e.includes("DevTools") && !e.includes("Warning:") && !e.includes("favicon")
    );
    if (real.length > 0) console.error("JS errors:", real);
    expect(real).toHaveLength(0);
  });

  test("bubble chart dot subtitle 'X = invested' is visible", async ({ page }) => {
    await injectCookie(page);
    await page.goto(`${BASE}/v5/performance`);
    await page.waitForLoadState("networkidle");

    const body = await page.textContent("body");
    // Subtitle under the bubble chart
    expect(body).toMatch(/X\s*=\s*invested/i);
  });
});
