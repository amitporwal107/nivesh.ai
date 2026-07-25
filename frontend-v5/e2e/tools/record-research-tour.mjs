/**
 * record-research-tour.mjs — captures the ~2-minute guided tour of the Research tab.
 *
 * Drives the LIVE, deployed Research tab on staging with a real session cookie and
 * records the browser as a .webm (Playwright recordVideo). Nothing is faked: the
 * feed shows real filings, the signal drawer + expanded rows show the real
 * (precomputed) AI insight, the document library lists real filed documents.
 *
 * The live copilot ASK (ask bar / curated themes → /api/chat/stream) is gated behind
 * INCLUDE_ASK=1 and OFF by default: at recording time the staging chat backend was
 * returning a connection error, and a tour must not showcase a broken answer. Turn it
 * on to capture the full ask flow once the copilot backend is healthy again.
 *
 * Usage (token via env — never argv, never committed):
 *   SESSION_TOKEN=… node e2e/tools/record-research-tour.mjs
 *   SESSION_TOKEN=… INCLUDE_ASK=1 node e2e/tools/record-research-tour.mjs   (full tour)
 *   STAGING_URL=https://staging.niveshcopilot.com  (optional override)
 */
import { chromium } from "@playwright/test";
import fs from "fs";
import path from "path";

const TOKEN = process.env.SESSION_TOKEN;
if (!TOKEN) { console.error("SESSION_TOKEN env var is required"); process.exit(1); }
const BASE = process.env.STAGING_URL ?? "https://staging.niveshcopilot.com";
const INCLUDE_ASK = process.env.INCLUDE_ASK === "1";
const HOST = new URL(BASE).hostname;
const OUT_DIR = process.env.OUT_DIR ?? "/tmp/claude-0/-app/5b82d7be-fd5d-4442-9efa-a189c1504092/scratchpad/tour-rec";
fs.mkdirSync(OUT_DIR, { recursive: true });

const SIZE = { width: 1280, height: 720 };

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: SIZE,
  colorScheme: "dark",
  ignoreHTTPSErrors: true,
  recordVideo: { dir: OUT_DIR, size: SIZE },
});
await context.addInitScript(() => {
  try { localStorage.setItem("nivesh.ui", JSON.stringify({ state: { theme: "dark", persona: "client", sidebarCollapsed: false }, version: 0 })); } catch {}
});
await context.addCookies([{ name: "session_token", value: TOKEN, domain: HOST, path: "/", secure: true, sameSite: "Lax" }]);

const page = await context.newPage();
const video = page.video();

const wait = (ms) => page.waitForTimeout(ms);
async function step(name, fn, pause = 0) {
  try { await fn(); console.log(`  ✓ ${name}`); }
  catch (e) { console.log(`  [skip] ${name}: ${String(e.message).split("\n")[0]}`); }
  if (pause) await wait(pause);
}
const reveal = (tid) => page.getByTestId(tid).first().scrollIntoViewIfNeeded();
const hover = (tid) => page.getByTestId(tid).first().hover();

try {
  console.log(`→ opening staging /v5/research  (INCLUDE_ASK=${INCLUDE_ASK})`);
  await page.goto(`${BASE}/v5/research`, { waitUntil: "domcontentloaded", timeout: 45000 });
  await page.getByTestId("ask-input").waitFor({ timeout: 35000 });
  await wait(4000);

  // 0) Showcase the ask affordance — the ask bar + curated themes (no submit).
  await step("highlight the ask bar", () => hover("ask-input"), 2600);
  await step("show curated themes", () => reveal("thematic-starters"), 1200);
  await step("hover a theme", () => page.getByTestId("thematic-starter").first().hover(), 2600);
  if (INCLUDE_ASK) {
    await step("focus ask bar", async () => {
      await page.getByTestId("ask-input").click();
      await page.getByTestId("ask-input").pressSequentially("Summarise HDFC AMC's latest quarterly results", { delay: 42 });
    }, 700);
    await step("submit ask", () => page.getByTestId("ask-submit").click(), 1000);
    await step("wait for the grounded answer", async () => {
      await page.getByTestId("copilot-answer").waitFor({ timeout: 20000 });
      await wait(16000);
      await page.getByTestId("copilot-answer").scrollIntoViewIfNeeded();
    }, 5000);
  }

  // 1) "Read for you" — flip to latest, open a signal → its precomputed AI insight.
  await step("scroll to Read-for-you", () => reveal("today-toggle"), 1400);
  await step("show latest signals", () => page.getByTestId("today-toggle").click(), 3200);
  await step("hover the top signal", () => hover("signal-card"), 1600);
  await step("open the signal drawer", async () => {
    await page.getByTestId("signal-card").first().click();
    await page.getByTestId("signal-drawer").waitFor({ timeout: 8000 });
  }, 2000);
  await step("read the AI insight", () => page.locator('[data-testid="signal-drawer"] [class*="nv-eyebrow"]').first().scrollIntoViewIfNeeded().catch(() => {}), 6500);
  await step("scroll the AI insight", () => page.locator('[data-testid="signal-drawer"]').evaluate((el) => el.scrollBy({ top: 260, behavior: "smooth" })).catch(() => {}), 5500);
  await step("close the drawer", () => page.locator('[data-testid="signal-drawer"] button[aria-label="Close"]').click(), 1800);

  // 2) The full filings feed + facets + an expanded AI insight with citations.
  await step("scroll to All filings", () => reveal("filings-list"), 1600);
  await step("sort by materiality", () => page.getByTestId("sort-material").click().catch(() => {}), 1600);
  await step("skim the feed", async () => { for (let i = 0; i < 3; i++) { await page.mouse.wheel(0, 260); await wait(650); } }, 1500);
  await step("filter by a category", () => page.locator(".facet", { hasText: /earnings/i }).first().click(), 3200);
  await step("expand a filing", async () => {
    await page.getByTestId("filings-list").locator("> div").first().click();
    await wait(700);
    await page.getByTestId("filings-list").locator("> div").first().scrollIntoViewIfNeeded();
  }, 7000);
  await step("read the expanded insight", () => page.mouse.wheel(0, 220), 4500);
  await step("collapse the filing", () => page.getByTestId("filings-list").locator("> div").first().click().catch(() => {}), 1600);

  // 3) Scope to one company → its real document library.
  await step("scope to a company", async () => {
    await reveal("filings-search");
    await page.getByTestId("filings-search").click();
    await page.getByTestId("filings-search").pressSequentially("TCS", { delay: 95 });
    await page.getByTestId("company-suggestion").first().waitFor({ timeout: 8000 });
  }, 1800);
  await step("select the company", () => page.getByTestId("company-suggestion").first().click(), 3000);
  await step("show the document library", () => reveal("documents-panel"), 3600);
  await step("browse quarterly results", () => page.locator("button", { hasText: /quarterly results/i }).first().click().catch(() => {}), 3800);
  await step("browse annual reports", () => page.locator("button", { hasText: /annual reports/i }).first().click().catch(() => {}), 3800);
  await step("browse press releases", () => page.locator("button", { hasText: /press releases/i }).first().click().catch(() => {}), 3800);
  await step("clear the company scope", () => page.getByTestId("clear-company").click(), 2600);

  // 4) Alerts — filing-type + channel preferences.
  await step("open Alerts", () => page.getByTestId("rail-alerts").click(), 3600);
  await step("scan the filing types", () => page.mouse.wheel(0, 320), 3200);
  await step("scan the channels", () => page.mouse.wheel(0, 320), 3200);
  await step("back to the feed", () => page.getByTestId("rail-feed").click(), 3000);
  await step("settle", () => reveal("ask-input"), 3000);
} catch (e) {
  console.log("walkthrough aborted:", e.message);
} finally {
  await context.close();
  await browser.close();
}

const src = await video.path();
const dest = path.join(OUT_DIR, "research-tab-tour.webm");
fs.copyFileSync(src, dest);
const { size } = fs.statSync(dest);
console.log(`\nVIDEO: ${dest} (${(size / 1e6).toFixed(1)} MB)`);
