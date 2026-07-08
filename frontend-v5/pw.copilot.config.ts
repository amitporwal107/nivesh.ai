/**
 * Throwaway Playwright config for verifying the Copilot tour against a
 * PRODUCTION build served by `vite preview` on :5174 (base /v5/).
 * No webServer — the preview server is started manually — so navigations hit
 * pre-compiled static assets (fast, stable) instead of the dev server's
 * on-demand transform of this large page.
 */
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e/tests",
  fullyParallel: false,
  workers: 1,
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
      name: "unauthenticated",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
    },
  ],
});
