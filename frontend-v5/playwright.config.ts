import { defineConfig, devices } from "@playwright/test";
import dotenv from "dotenv";
dotenv.config({ path: ".env.test" });

// Mocked UI tests always run against the local Vite dev server
const LOCAL_URL = "http://localhost:5174";
// Live-contract tests (no mocking) always hit real staging
const STAGING_URL = process.env.STAGING_URL ?? process.env.BASE_URL ?? "https://staging.niveshcopilot.com";

export default defineConfig({
  testDir: "./e2e/tests",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [
    ["html", { open: "never" }],
    ["list"],
  ],
  use: {
    baseURL: LOCAL_URL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    ignoreHTTPSErrors: true,
    colorScheme: "dark",
  },
  // Auto-start local Vite dev server for UI tests.
  // VITE_USE_MOCK_API=false  → real adapters make HTTP calls → Playwright route mocks intercept
  // VITE_BASE=/v5/           → matches staging path prefix so /v5/dashboard etc. resolve correctly
  webServer: {
    command: "VITE_USE_MOCK_API=false VITE_BASE=/v5/ npx vite --port 5174 --strictPort --config vite.test.config.ts",
    url: LOCAL_URL,
    reuseExistingServer: true,
    timeout: 60_000,
  },
  projects: [
    // Auth setup — writes a minimal storageState (no real cookie needed for mocked tests)
    {
      name: "auth-setup",
      testMatch: /auth\.setup\.ts/,
    },

    // Desktop tests (1280×800) — mocked, runs against local dev server
    {
      name: "desktop-chrome",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1280, height: 800 },
        storageState: "e2e/.auth/session.json",
      },
      dependencies: ["auth-setup"],
    },

    // Mobile tests (390×844) — navigation + responsive layout
    {
      name: "mobile-chrome",
      use: {
        ...devices["Pixel 7"],
        viewport: { width: 390, height: 844 },
        storageState: "e2e/.auth/session.json",
      },
      dependencies: ["auth-setup"],
      testMatch: /navigation|visual/,
    },

    // Unauthenticated tests — public pages + 401 handling
    {
      name: "unauthenticated",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1280, height: 800 },
      },
      testMatch: /homepage|login|unauth/,
    },

    // Live contract layer — hits real staging API, no mocking, no webServer
    // Run separately: npx playwright test --project=live-contracts
    {
      name: "live-contracts",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1280, height: 800 },
        baseURL: STAGING_URL,
        storageState: "e2e/.auth/session.json",
      },
      dependencies: ["auth-setup"],
      testMatch: /live-contracts/,
    },
  ],
});
