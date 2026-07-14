/**
 * Minimal Playwright config for the live Strategy Builder wizard spec.
 * Hits real staging (no local webServer, no mocking) with a session cookie
 * from e2e/.auth/staging-session.json. Run:
 *   STAGING_URL=https://staging.niveshcopilot.com \
 *   npx playwright test --config=e2e/strategy-builder.config.ts
 */
import { defineConfig, devices } from "@playwright/test";

const STAGING = process.env.STAGING_URL ?? "https://staging.niveshcopilot.com";

export default defineConfig({
  testDir: "./tests",
  testMatch: /strategy-builder-live/,
  timeout: 120_000,
  reporter: [["list"]],
  use: {
    baseURL: STAGING,
    ignoreHTTPSErrors: true,
    colorScheme: "dark",
    storageState: "e2e/.auth/staging-session.json",
    viewport: { width: 1280, height: 900 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    ...devices["Desktop Chrome"],
  },
});
