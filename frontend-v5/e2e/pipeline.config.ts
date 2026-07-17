/**
 * Live Playwright config for the NIDP Console Pipeline tab.
 * Hits real staging with a session cookie — no mocking, no local webServer.
 *   STAGING_URL=https://staging.niveshcopilot.com:8443 \
 *   npx playwright test --config=e2e/pipeline.config.ts
 */
import { defineConfig, devices } from "@playwright/test";

const STAGING = process.env.STAGING_URL ?? "https://staging.niveshcopilot.com";

export default defineConfig({
  testDir: "./tests",
  testMatch: /pipeline-panel-live/,
  timeout: 120_000,
  reporter: [["list"]],
  use: {
    baseURL: STAGING,
    ignoreHTTPSErrors: true,
    colorScheme: "dark",
    storageState: "e2e/.auth/pipeline-session.json",
    viewport: { width: 1440, height: 1000 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    ...devices["Desktop Chrome"],
  },
});
