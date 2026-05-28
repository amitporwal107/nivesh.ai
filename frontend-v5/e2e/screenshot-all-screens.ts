/**
 * Playwright script — screenshot every V5 screen with a real session token.
 *
 * Usage:
 *   SESSION_TOKEN=e6f41466-... npx tsx e2e/screenshot-all-screens.ts
 */
import { chromium } from "playwright";

const BASE = process.env.BASE_URL ?? "https://staging.niveshcopilot.com:8443";
const TOKEN = process.env.SESSION_TOKEN ?? "e6f41466-3295-45a0-b267-52f4156a384f";
const OUT_DIR = process.env.OUT_DIR ?? "e2e/screenshots";

const SCREENS = [
  { path: "/v5/",                name: "01-homepage" },
  { path: "/v5/login",           name: "02-login" },
  { path: "/v5/onboarding",      name: "03-onboarding" },
  { path: "/v5/dashboard",       name: "04-dashboard" },
  { path: "/v5/portfolio",       name: "05-portfolio" },
  { path: "/v5/concentration",   name: "06-concentration" },
  { path: "/v5/diversification", name: "07-diversification" },
  { path: "/v5/risk",            name: "08-risk" },
  { path: "/v5/performance",     name: "09-performance" },
  { path: "/v5/goals",           name: "10-goals" },
  { path: "/v5/tax",             name: "11-tax" },
  { path: "/v5/plan",            name: "12-plan" },
  { path: "/v5/recommendations", name: "13-recommendations" },
  { path: "/v5/chat",            name: "14-chat" },
  { path: "/v5/settings",        name: "15-settings" },
];

async function run() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    ignoreHTTPSErrors: true,
    colorScheme: "dark",
  });

  // Set session via the dev endpoint — this sets the cookie properly via Set-Cookie header
  const authPage = await context.newPage();
  console.log("Setting session via dev-set-cookie...");
  const resp = await authPage.goto(
    `${BASE}/api/auth/dev-set-cookie?token=${TOKEN}`,
    { waitUntil: "networkidle" },
  );
  console.log(`  Auth response: ${resp?.status()}`);

  // Verify auth works
  const meResp = await authPage.evaluate(async (base) => {
    const r = await fetch(`${base}/api/auth/me`, { credentials: "include" });
    return { status: r.status, body: await r.json().catch(() => null) };
  }, BASE);
  console.log(`  /api/auth/me: ${meResp.status} — ${meResp.body?.name ?? "FAIL"}`);

  if (meResp.status !== 200) {
    console.error("Auth failed — session token may be expired. Aborting.");
    await browser.close();
    process.exit(1);
  }

  // Set dark theme in localStorage
  await authPage.goto(`${BASE}/v5/`, { waitUntil: "domcontentloaded" });
  await authPage.evaluate(() => {
    localStorage.setItem("nivesh.ui", JSON.stringify({ state: { theme: "dark", persona: "client", sidebarCollapsed: false }, version: 0 }));
  });
  await authPage.close();

  console.log(`\nScreenshotting ${SCREENS.length} screens → ${OUT_DIR}/\n`);

  for (const screen of SCREENS) {
    const page = await context.newPage();
    const url = `${BASE}${screen.path}`;
    console.log(`  ${screen.name} → ${url}`);

    try {
      await page.goto(url, { waitUntil: "networkidle", timeout: 30_000 });
      await page.waitForTimeout(2000);

      await page.screenshot({
        path: `${OUT_DIR}/${screen.name}.png`,
        fullPage: true,
      });
      console.log(`    ✓ saved`);
    } catch (err) {
      console.error(`    ✗ ${(err as Error).message}`);
      try {
        await page.screenshot({ path: `${OUT_DIR}/${screen.name}-error.png`, fullPage: true });
      } catch {}
    }
    await page.close();
  }

  await browser.close();
  console.log(`\nDone. ${SCREENS.length} screenshots in ${OUT_DIR}/`);
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
