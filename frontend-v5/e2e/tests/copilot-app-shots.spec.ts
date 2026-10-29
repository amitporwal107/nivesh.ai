/**
 * Screenshot capture for the one-screen Copilot app — for comparing the build
 * against the design by eye. Not an assertion suite: it is skipped unless
 * SHOT_DIR is set.
 *
 *   SHOT_DIR=/out npx playwright test --config pw.copilot-app.config.ts copilot-app-shots
 *
 * All data on these screens comes from the e2e fixtures (test data).
 */
import { test, type Page } from "@playwright/test";
import fs from "fs";
import path from "path";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const DIR = process.env.SHOT_DIR;
const APP = "/v5/app";

const FRAMES = [
  { type: "meta", session_id: "new1", ai_msg_id: "ai1" },
  { type: "route", agent: "risk_advisor", confidence: 0.92 },
  { type: "thinking", tool: "get_portfolio_holdings", status: "start" },
  { type: "thinking", tool: "get_portfolio_holdings", status: "end" },
  { type: "thinking", tool: "risk_overview", status: "start" },
  { type: "thinking", tool: "risk_overview", status: "end" },
  { type: "token", content: "## Fixture answer\n\nThis is **test text** standing in for a Copilot answer, long enough to show how prose wraps in the thread.\n\n- First point of the fixture answer\n- Second point of the fixture answer\n" },
  { type: "done", content: "## Fixture answer\n\nThis is **test text** standing in for a Copilot answer, long enough to show how prose wraps in the thread.\n\n- First point of the fixture answer\n- Second point of the fixture answer\n", follow_ups: ["What drives the risk?", "How do I reduce it?", "Compare with the Nifty 50"] },
];

async function mocks(page: Page) {
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  const now = new Date().toISOString();
  const sessions = [
    { session_id: "s1", title: "Fixture thread one", updated_at: now },
    { session_id: "s2", title: "Fixture thread two with a longer title", updated_at: now },
  ];
  const saved: Record<string, unknown[]> = {};
  await page.route("**/api/chat/sessions", (route) => {
    if (route.request().method() === "POST") {
      sessions.unshift({ session_id: "new1", title: "How risky is my portfolio?", updated_at: now });
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ session_id: "new1" }) });
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(sessions) });
  });
  await page.route("**/api/chat/messages*", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(saved[new URL(route.request().url()).searchParams.get("session_id") ?? ""] ?? []) }));
  await page.route("**/api/chat/stream", (route) => {
    const body = route.request().postDataJSON() as { message: string; session_id: string };
    saved[body.session_id] = [
      { message_id: "u1", role: "user", content: body.message, created_at: now },
      { message_id: "ai1", role: "assistant", content: (FRAMES[FRAMES.length - 1] as { content: string }).content, created_at: now },
    ];
    return route.fulfill({ status: 200, contentType: "text/event-stream", body: FRAMES.map((f) => `data: ${JSON.stringify(f)}\n\n`).join("") });
  });
}

const shot = (page: Page, name: string) => page.screenshot({ path: path.join(DIR as string, `${name}.png`) });

const VIEWS = [
  "tool/analysis", "tool/recommend", "tool/research", "tool/screener", "tool/markets",
  "page/watchlist", "page/saved", "page/plan", "page/ledger", "page/paper", "page/brokers", "page/settings",
  "advisor", "onboarding", "builder", "ops/tools", "ops/feeds", "ops/audit", "ops/kpis",
];

for (const size of [{ tag: "desktop", width: 1440, height: 900 }, { tag: "phone", width: 390, height: 844 }]) {
  test.describe(`shots — ${size.tag}`, () => {
    test.skip(!DIR, "set SHOT_DIR to capture screenshots");
    test.use({ viewport: { width: size.width, height: size.height }, ...(size.tag === "phone" ? { hasTouch: true, isMobile: true } : {}) });

    test(`shell ${size.tag}`, async ({ page }) => {
      await mocks(page);
      await page.goto(APP);
      await page.getByTestId("home-today-card").first().waitFor();
      await page.evaluate(() => document.fonts.ready);
      await shot(page, `${size.tag}-home`);
      await page.getByTestId("composer-input").click();
      await page.getByTestId("composer-suggest").waitFor();
      await shot(page, `${size.tag}-home-suggest`);
      await page.getByTestId("composer-input").press("Escape");
      if (size.tag === "phone") {
        await page.getByTestId("menu-button").click();
        await shot(page, `${size.tag}-drawer`);
        await page.getByTestId("rail-scrim").click({ position: { x: 370, y: 400 } });
        await page.getByTestId("evidence-toggle").click();
        await shot(page, `${size.tag}-evidence-sheet`);
        await page.getByTestId("evidence-close").click();
      }
      await page.getByTestId("composer-input").fill("How risky is my portfolio?");
      await page.getByTestId("composer-input").press("Enter");
      await page.getByTestId("answer-followups").waitFor();
      await page.getByTestId("answer-trace").getByRole("button").click();
      await shot(page, `${size.tag}-thread`);
    });

    test(`screens ${size.tag}`, async ({ page }) => {
      test.setTimeout(120_000);
      await mocks(page);
      for (const v of VIEWS) {
        await page.goto(`${APP}/${v}`);
        await page.getByTestId(`screen-${v.replace("/", "-")}`).waitFor();
        await page.waitForLoadState("networkidle");
        await page.screenshot({ path: path.join(DIR as string, `${size.tag}-${v.replace("/", "-")}.png`), fullPage: false });
      }
    });
  });
}

test.describe("shots — light theme", () => {
  test.skip(!DIR, "set SHOT_DIR to capture screenshots");
  test.use({ viewport: { width: 1440, height: 900 } });

  test("light theme home and thread", async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem("nivesh.ui", JSON.stringify({ state: { theme: "light", persona: "client", sidebarCollapsed: false }, version: 0 }));
    });
    await mocks(page);
    await page.goto(APP);
    await page.getByTestId("home-today-card").first().waitFor();
    await page.evaluate(() => document.fonts.ready);
    await shot(page, "light-home");
    await page.getByTestId("composer-input").fill("How risky is my portfolio?");
    await page.getByTestId("composer-input").press("Enter");
    await page.getByTestId("answer-followups").waitFor();
    await shot(page, "light-thread");
  });
});

// Contact sheets: tiles the captured screens so many can be reviewed at once.
// Run on its own after the captures:  -g "contact sheet"
test.describe("contact sheet", () => {
  test.skip(!DIR, "set SHOT_DIR to capture screenshots");
  test.use({ viewport: { width: 1800, height: 1200 } });

  for (const tag of ["desktop", "phone"]) {
    test(`contact sheet ${tag}`, async ({ page }) => {
      const files = fs.readdirSync(DIR as string).filter((f) => f.startsWith(`${tag}-`) && f.endsWith(".png")).sort();
      const per = tag === "desktop" ? 6 : 12;
      const cols = tag === "desktop" ? 3 : 6;
      for (let i = 0; i < files.length; i += per) {
        const html = `<body style="margin:0;background:#222;font:12px monospace;color:#ddd"><div style="display:grid;grid-template-columns:repeat(${cols},1fr);gap:8px;padding:8px">${
          files.slice(i, i + per).map((f) => `<figure style="margin:0"><figcaption style="padding:2px 0">${f}</figcaption><img src="${f}" style="width:100%;display:block"></figure>`).join("")
        }</div></body>`;
        const file = path.join(DIR as string, `_sheet-${tag}-${i / per + 1}.html`);
        fs.writeFileSync(file, html);
        await page.goto(`file://${file}`);
        await page.waitForLoadState("load");
        await page.screenshot({ path: path.join(DIR as string, `_sheet-${tag}-${i / per + 1}.png`), fullPage: true });
      }
    });
  }
});
