/**
 * Simulation studio · New simulation (AD-UI-120..129). Test cases: docs/autodesk/ui_testcases/studio-setup.md.
 * API answered by route mocks (autodesk-mock.ts + autodesk-fixtures-studio-setup.ts — MOCK, shapes of the real API).
 * Request bodies are checked against e2e/fixtures/autodesk/requests/studio-setup.json (posted to the real FastAPI app
 * by backend/tests/autodesk/test_ui_request_contracts.py).
 */
import { expect, test, type Page } from "@playwright/test";
import { collectConsoleErrors, expectContract, mockDesk, reply, type RouteValue } from "./autodesk-mock";
import { NEW_SID, POL, setupRoutes, type SetupState } from "./autodesk-fixtures-studio-setup";

async function open(page: Page, routes: Record<string, RouteValue>) {
  const desk = await mockDesk(page, { routes });
  await page.goto("/autodesk/studio/new");
  await expect(page.getByTestId("studio-new")).toBeVisible();
  return desk;
}

const simPosts = (desk: { posts: { method: string; path: string; body: unknown }[] }) => desk.posts.filter((p) => p.path.startsWith("/simulations"));
const summaryRow = (page: Page, k: string) => page.getByTestId("setup-summary-row").filter({ hasText: k });

test("AD-UI-120 layout, sections in the design's order, defaults from /desk/status, /policies, /agents", async ({ page }) => {
  const errors = collectConsoleErrors(page);
  const desk = await open(page, setupRoutes());
  await expect(page.getByTestId("setup-eyebrow")).toHaveText("New simulation · id given on create");
  await expect(page.getByTestId("studio-new").locator(".nv-pill").first()).toHaveText("Draft");
  await expect(page.getByTestId("setup-headline")).toHaveText("Set up a run. Same inputs and seed give the same result, every time.");
  await expect(page.getByTestId("setup-section-title")).toHaveText(["Mode", "Session", "Universe", "Capital and account", "Agent versions", "Policy", "Execution model", "Playback and seed", "Scenario injections"]);

  await expect(page.getByTestId("setup-mode-HISTORICAL_REPLAY")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("setup-start")).toHaveValue("2026-11-03");
  await expect(page.getByTestId("setup-end")).toHaveValue("2026-11-04");
  await expect(page.locator('[data-testid^="setup-day-"]')).toHaveText(["Wed 28 Oct", "Thu 29 Oct", "Fri 30 Oct", "Mon 2 Nov", "Tue 3 Nov", "Wed 4 Nov"]);
  await expect(page.getByTestId("setup-uni-FNO")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("setup-cap-10000000")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("setup-op-AUTONOMOUS_PAPER")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId(`setup-policy-${POL}`)).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId(`setup-policy-${POL}`)).toContainText("Desk default · v3");
  await expect(page.getByTestId(`setup-policy-${POL}`)).toContainText("Account default");
  await expect(page.getByTestId("setup-plans-5")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("setup-seed")).toHaveValue("42");

  await expect(page.getByTestId("setup-agent-row")).toHaveCount(5);
  await expect(page.getByTestId("setup-agent-row")).toHaveText([/AI Trader.*autodesk-ait-v1/, /Trading Assistant.*autodesk-ta-v1/, /Risk & Operations.*autodesk-risk-ops-v1/, /Middle Office.*autodesk-mo-v1/, /Tech Support.*autodesk-ts-v1/]);
  await expect(page.getByTestId("setup-agents")).not.toContainText("autodesk-risk-ops-v0");
  await expect(page.getByTestId("setup-seed-note")).toContainText("All five agents are deterministic in this version");

  await expect(page.getByTestId("setup-name")).toHaveValue("Historical replay · 3 Nov – 4 Nov 2026");
  const expected: [string, string][] = [
    ["Sessions", "3 Nov – 4 Nov 2026"], ["Universe", "F&O underlyings of each session"], ["Capital", "₹1.00 Cr"], ["Account mode", "Auto paper"],
    ["Policy", "Desk default · v3"], ["Agents", "5 current versions"], ["Plans per session", "5"], ["Execution", "None in Phase 1"],
    ["Injections", "None · Phase 3"], ["Seed", "42"], ["Playback", "Stepped phase by phase"],
  ];
  await expect(page.getByTestId("setup-summary-row")).toHaveCount(expected.length);
  for (const [k, v] of expected) await expect(summaryRow(page, k)).toContainText(v);
  await expect(page.getByTestId("setup-summary")).toContainText("ISOLATED");
  await expect(page.getByTestId("setup-create")).toBeEnabled();
  await expect(page.getByTestId("setup-problems")).toHaveCount(0);

  const text = await page.getByTestId("studio-new").innerText();
  for (const sample of ["SIM-0419", "P-PAPER", "SCN-0", "8841", "sim_0419"]) expect(text).not.toContain(sample);
  expect(desk.posts).toEqual([]);
  expect(desk.unmatched).toEqual([]);
  expect(errors).toEqual([]);
});

test("AD-UI-121 blocks Phase 1 cannot serve keep their place and say so", async ({ page }) => {
  await open(page, setupRoutes());
  for (const id of ["setup-preopen", "setup-postclose"]) {
    await expect(page.getByTestId(id)).toHaveAttribute("aria-disabled", "true");
    await expect(page.getByTestId(id)).toContainText("Not in Phase 1");
  }
  const dis = page.getByTestId("setup-uni-disabled");
  await expect(dis).toHaveCount(4);
  await expect(dis).toHaveText([/Nifty 50/, /Nifty 200/, /Nifty 500/, /Index options/]);
  for (let i = 0; i < 4; i++) {
    await expect(dis.nth(i)).toHaveAttribute("aria-disabled", "true");
    await expect(dis.nth(i)).toContainText("Not a separate universe in Phase 1");
  }
  await dis.nth(0).click({ force: true });                           // disabled: a click changes nothing
  await expect(page.getByTestId("setup-uni-FNO")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("setup-agents-note")).toContainText("choosing another version is not available");
  await expect(page.getByTestId("setup-execution-note")).toContainText("Phase 2");
  await expect(page.getByTestId("setup-execution-note")).toContainText("Fill model, slippage per leg, latency, partial fills and reject rate");
  await expect(page.getByTestId("setup-speed-note")).toContainText("Not in Phase 1");
  await expect(page.getByTestId("setup-speed-note")).toContainText("Speed multipliers (1×–600×) and checkpoints are not available");
  await expect(page.getByTestId("setup-scenarios-note")).toContainText("Phase 3");
  await expect(page.getByTestId("setup-scenarios-note")).toContainText("nothing is scheduled or sent");
  await expect(page.getByTestId("setup-playback-mode")).toContainText("Step by step");

  await page.goto("/autodesk/studio/new?sim=SIM-2b9d7f1e0a3c4b5d6e7f");
  await page.getByTestId("setup-scen-link").click();
  await expect(page).toHaveURL(/\/autodesk\/studio\/scenarios\?sim=SIM-2b9d7f1e0a3c4b5d6e7f$/);
  await expect(page.getByTestId("studio-scenarios")).toBeVisible();
});

test("AD-UI-122 historical replay: Create and start sends create + start and opens the Trading day", async ({ page }) => {
  const st: SetupState = { created: null };
  const desk = await open(page, setupRoutes(st));
  await expect(page.getByTestId(`setup-policy-${POL}`)).toHaveAttribute("aria-pressed", "true");
  await page.getByTestId("setup-name").fill("Studio replay");
  await page.getByTestId("setup-create").click();
  await expect(page).toHaveURL(new RegExp(`/autodesk/studio\\?sim=${NEW_SID}$`));
  await expect(page.getByTestId("studio-tab-day")).toHaveAttribute("aria-current", "page");
  const posts = simPosts(desk);
  expect(posts).toHaveLength(2);
  expectContract(posts[0], "studio-setup", "create", { start_date: "2026-11-03", end_date: "2026-11-04", policy_id: POL });
  expectContract(posts[1], "studio-setup", "start", { simulation_id: NEW_SID });
});

test("AD-UI-123 accelerated replay with symbols, ₹50 L, Assisted, 3 per session, typed seed: create + start + run", async ({ page }) => {
  const desk = await open(page, setupRoutes());
  await page.getByTestId("setup-mode-ACCELERATED_REPLAY").click();
  await page.getByTestId("setup-day-2026-11-03").click();
  await expect(page.getByTestId("setup-day-2026-11-03")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("setup-start")).toHaveValue("2026-11-03");
  await expect(page.getByTestId("setup-end")).toHaveValue("2026-11-03");
  await page.getByTestId("setup-uni-SYMBOLS").click();
  await page.getByTestId("setup-symbols").fill("petronet, GRASIM");
  await page.getByTestId("setup-cap-5000000").click();
  await page.getByTestId("setup-op-ASSISTED").click();
  await page.getByTestId("setup-plans-3").click();
  await page.getByTestId("setup-reroll").click();
  await page.getByTestId("setup-seed").fill("8841");
  await page.getByTestId("setup-name").fill("Studio accelerated");
  for (const [k, v] of [["Sessions", "3 Nov 2026"], ["Universe", "2 symbols"], ["Capital", "₹50.00 L"], ["Account mode", "Assisted"], ["Plans per session", "3"], ["Seed", "8841"], ["Playback", "Runs to the end in the background"]] as const) {
    await expect(summaryRow(page, k)).toContainText(v);
  }
  await expect(page.getByTestId("setup-playback-mode")).toContainText("To the end");
  await page.getByTestId("setup-create").click();
  await expect(page).toHaveURL(new RegExp(`/autodesk/studio\\?sim=${NEW_SID}$`));
  const posts = simPosts(desk);
  expect(posts).toHaveLength(3);
  expectContract(posts[0], "studio-setup", "create_accelerated", { start_date: "2026-11-03", policy_id: POL });
  expectContract(posts[1], "studio-setup", "start", { simulation_id: NEW_SID });
  expectContract(posts[2], "studio-setup", "run", { simulation_id: NEW_SID });
});

test("AD-UI-124 client validation blocks Create and start and sends nothing", async ({ page }) => {
  const desk = await open(page, setupRoutes());
  const create = page.getByTestId("setup-create");
  const problems = page.getByTestId("setup-problems");
  await page.getByTestId("setup-name").fill("");
  await expect(problems).toContainText("a name of 1–120 characters");
  await expect(create).toBeDisabled();
  await page.getByTestId("setup-name").fill("Studio replay");
  await page.getByTestId("setup-end").fill("2026-11-02");
  await expect(problems).toContainText("a last session on or after the first");
  await expect(create).toBeDisabled();
  await page.getByTestId("setup-end").fill("2026-11-04");
  await page.getByTestId("setup-uni-SYMBOLS").click();
  await expect(problems).toContainText("at least one symbol");
  await expect(create).toBeDisabled();
  const many = Array.from({ length: 51 }, (_, i) => `SYM${i}`).join(", ");
  await page.getByTestId("setup-symbols").fill(many);
  await expect(problems).toContainText("at most 50 symbols");
  await expect(create).toBeDisabled();
  await page.getByTestId("setup-uni-FNO").click();
  await page.getByTestId("setup-seed").fill("");
  await expect(problems).toContainText("a whole-number seed");
  await page.getByTestId("setup-seed").fill("42");
  await expect(problems).toHaveCount(0);
  await expect(create).toBeEnabled();
  expect(simPosts(desk)).toEqual([]);
});

test("AD-UI-125 Scenario simulation / Live shadow: Phase 3 / Phase 4 notes, nothing sent", async ({ page }) => {
  const desk = await open(page, setupRoutes());
  await page.getByTestId("setup-mode-SCENARIO").click();
  await expect(page.getByTestId("setup-mode-note")).toContainText("Phase 3");
  await expect(page.getByTestId("setup-mode-note")).toContainText("the API refuses SCENARIO today");
  await expect(page.getByTestId("setup-create")).toBeDisabled();
  await expect(page.getByTestId("setup-problems")).toContainText("a replay mode");
  await page.getByTestId("setup-mode-LIVE_SHADOW").click();
  await expect(page.getByTestId("setup-mode-note")).toContainText("Phase 4");
  await expect(page.getByTestId("setup-create")).toBeDisabled();
  await page.getByTestId("setup-mode-HISTORICAL_REPLAY").click();
  await expect(page.getByTestId("setup-mode-note")).toHaveCount(0);
  await expect(page.getByTestId("setup-create")).toBeEnabled();
  expect(simPosts(desk)).toEqual([]);
});

test("AD-UI-126 create refused (422): the API's message, no start, URL unchanged", async ({ page }) => {
  const msg = "the NSE holiday list (segment CM) has no rows for 2025";
  const desk = await open(page, setupRoutes({ created: null }, { "POST /simulations": reply(422, { error: "INVALID", message: msg }) }));
  await page.getByTestId("setup-start").fill("2025-12-30");
  await page.getByTestId("setup-end").fill("2025-12-31");
  await page.getByTestId("setup-create").click();
  await expect(page.getByTestId("setup-error")).toContainText("Not created");
  await expect(page.getByTestId("setup-error")).toContainText(`${msg} (422)`);
  await expect(page).toHaveURL(/\/autodesk\/studio\/new$/);
  const posts = simPosts(desk);
  expect(posts).toHaveLength(1);
  expect((posts[0].body as { start_date: string }).start_date).toBe("2025-12-30");
});

test("AD-UI-127 created but start refused (409): message and a link to the created run", async ({ page }) => {
  const msg = "simulation is RUNNING; cannot move to RUNNING";
  const desk = await open(page, setupRoutes({ created: null }, { "POST /simulations/:sid/start": reply(409, { error: "CONFLICT", message: msg }) }));
  await page.getByTestId("setup-create").click();
  await expect(page.getByTestId("setup-error")).toContainText("Created, but not started");
  await expect(page.getByTestId("setup-error")).toContainText(`${msg} (409)`);
  await expect(page.getByTestId("setup-open-created")).toHaveAttribute("href", `/autodesk/studio?sim=${NEW_SID}`);
  await expect(page).toHaveURL(/\/autodesk\/studio\/new$/);
  expect(simPosts(desk).filter((p) => p.path === "/simulations")).toHaveLength(1);
  await page.getByTestId("setup-open-created").click();
  await expect(page).toHaveURL(new RegExp(`/autodesk/studio\\?sim=${NEW_SID}$`));
});

test("AD-UI-128 /policies and /agents fail: ErrorBoxes; the body leaves policy_id to the API's default", async ({ page }) => {
  const desk = await open(page, setupRoutes({ created: null }, {
    "GET /policies": reply(500, { error: "INTERNAL", message: "policy store unavailable" }),
    "GET /agents": reply(500, { error: "INTERNAL", message: "agent registry unavailable" }),
  }));
  await expect(page.getByTestId("setup-policy").getByTestId("error-box")).toContainText("policy store unavailable (500)", { timeout: 15000 });
  await expect(page.getByTestId("setup-agents").getByTestId("error-box")).toContainText("agent registry unavailable (500)", { timeout: 15000 });
  await expect(summaryRow(page, "Policy")).toContainText("Account default");
  await expect(summaryRow(page, "Agents")).toContainText("Versions running at create time");
  await page.getByTestId("setup-name").fill("Studio replay");
  await page.getByTestId("setup-create").click();
  await expect(page).toHaveURL(new RegExp(`/autodesk/studio\\?sim=${NEW_SID}$`));
  expectContract(simPosts(desk)[0], "studio-setup", "create_default_policy", { start_date: "2026-11-03", end_date: "2026-11-04" });
});

test("AD-UI-129 phone 390×844: single column, no horizontal overflow, Create and start reachable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const errors = collectConsoleErrors(page);
  await open(page, setupRoutes());
  await expect(page.getByTestId("setup-agent-row")).toHaveCount(5);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  const sec = await page.getByTestId("setup-scenarios").boundingBox();
  const aside = await page.getByTestId("setup-summary").boundingBox();
  expect(sec && aside && aside.y > sec.y).toBeTruthy();
  await page.getByTestId("setup-create").scrollIntoViewIfNeeded();
  await expect(page.getByTestId("setup-create")).toBeVisible();
  expect(errors).toEqual([]);
});
