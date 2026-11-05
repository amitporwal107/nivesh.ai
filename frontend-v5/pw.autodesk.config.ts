/**
 * Playwright config for the Autonomous Trading Desk web app (/autodesk/) specs: e2e/tests/autodesk-*.spec.ts.
 *
 * Runs against a PRODUCTION build served by `vite preview` (base /autodesk/), started by hand — no webServer here.
 * Every /autodesk/api/v1/* and /api/* call is answered by route mocks (e2e/tests/autodesk-mock.ts) whose bodies copy
 * the real API's shapes; no real session is needed.
 *
 *   npx vite build --config vite.autodesk.config.ts --outDir /tmp/ad-dist
 *   npx vite preview --config vite.autodesk.config.ts --outDir /tmp/ad-dist --port 5175 --strictPort &
 *   npx playwright test --config pw.autodesk.config.ts
 *
 * Phone-size cases set their own viewport inside the spec.
 */
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e/tests",
  testMatch: /autodesk-.*\.spec\.ts/,
  fullyParallel: true,
  workers: 3,
  timeout: 30000,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.PW_BASE_URL || "http://localhost:5175",
    colorScheme: "dark",
    ignoreHTTPSErrors: true,
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "autodesk",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
    },
  ],
});
