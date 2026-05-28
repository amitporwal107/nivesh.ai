/**
 * Auth setup — writes e2e/.auth/session.json.
 *
 * Mocked UI tests run against localhost:5174 where all API calls are intercepted
 * by Playwright route mocks. No real session cookie is needed — the mock returns
 * the user profile fixture for every auth/me request.
 *
 * Live-contract tests (live-contracts.spec.ts) bypass this entirely: they send
 * the SESSION_TOKEN directly in every request header.
 */
import { test as setup } from "@playwright/test";
import path from "path";
import fs from "fs";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const SESSION_FILE = path.join(__dirname, ".auth", "session.json");
const authDir = path.dirname(SESSION_FILE);
if (!fs.existsSync(authDir)) fs.mkdirSync(authDir, { recursive: true });

setup("auth setup — inject dark-theme localStorage", async ({ page }) => {
  // Navigate to local dev server root so we can write localStorage for that origin
  await page.goto("/");
  await page.evaluate(() => {
    localStorage.setItem(
      "nivesh.ui",
      JSON.stringify({ state: { theme: "dark", persona: "client", sidebarCollapsed: false }, version: 0 }),
    );
  });
  await page.context().storageState({ path: SESSION_FILE });
  console.log("  Auth setup: localStorage injected for localhost");
});
