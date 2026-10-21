/**
 * Playwright config for the one-screen Copilot app (/v5/app) specs.
 *
 * Runs against a PRODUCTION build served by `vite preview` on :5174 (base
 * /v5/), started by hand — no webServer here — so navigations hit pre-compiled
 * assets instead of the dev server's on-demand transform. Every /api/* call is
 * answered by Playwright route mocks; no real session is needed.
 *
 *   VITE_USE_MOCK_API=false VITE_BASE=/v5/ npx vite build
 *   VITE_BASE=/v5/ npx vite preview --port 5174 --strictPort &
 *   npx playwright test --config pw.copilot-app.config.ts
 *
 * Phone-size cases set their own viewport inside the spec, so one project
 * covers both.
 */
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e/tests",
  testMatch: /copilot-app.*\.spec\.ts/,
  fullyParallel: true,
  workers: 3,
  timeout: 30000,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.PW_BASE_URL || "http://localhost:5174",
    colorScheme: "dark",
    ignoreHTTPSErrors: true,
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "copilot-app",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
    },
  ],
});
