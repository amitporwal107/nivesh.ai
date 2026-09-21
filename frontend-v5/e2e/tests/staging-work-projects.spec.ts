/**
 * /v5/work on REAL staging (test_reports/work_page_all_items_20260921.md). No API mocks except TC-7's injected failure:
 * expectations are recomputed from the full, paged /api/work/issues payload the same session can read.
 *
 * Needs an admin session: STAGING_SESSION_FILE=<file holding the session_token>. Skipped without it.
 * WORK_BUNDLE_DIR=<vite dist> serves a local build on the staging :8443 origin (so the API calls stay real and
 * cross-origin exactly as deployed); unset, the test exercises the bundle staging is actually serving.
 */
import { test, expect, type Page } from "@playwright/test";
import fs from "fs";
import path from "path";

const UI = "https://staging.niveshcopilot.com:8443";
const API = "https://staging.niveshcopilot.com";
const FILE = process.env.STAGING_SESSION_FILE;
const BUNDLE = process.env.WORK_BUNDLE_DIR;
const PHASES = ["phase-1", "phase-2", "phase-3"];
const TYPES: Record<string, string> = { ".js": "application/javascript", ".css": "text/css", ".html": "text/html", ".svg": "image/svg+xml", ".webp": "image/webp", ".png": "image/png", ".json": "application/json", ".woff2": "font/woff2" };

type Issue = { issue_id: string; issue_type: string; project?: string | null; title: string; status: string; phase?: string | null };

test.skip(!FILE, "STAGING_SESSION_FILE not set");
test.describe.configure({ mode: "serial" });

async function setup(page: Page) {
  const token = fs.readFileSync(FILE as string, "utf-8").trim();
  await page.context().addCookies([{ name: "session_token", value: token, domain: "staging.niveshcopilot.com", path: "/", secure: true, httpOnly: true }]);
  if (!BUNDLE) return;
  await page.route((u) => u.origin === UI && u.pathname.startsWith("/v5/"), async (route) => {
    const rel = new URL(route.request().url()).pathname.slice("/v5/".length);
    let file = path.join(BUNDLE, rel);
    if (!rel || !fs.existsSync(file) || fs.statSync(file).isDirectory()) file = path.join(BUNDLE, "index.html");
    await route.fulfill({ status: 200, body: fs.readFileSync(file), contentType: TYPES[path.extname(file)] ?? "application/octet-stream" });
  });
}

// Text-based so the same spec runs on the currently deployed bundle (baseline) and on the fix.
const cardFor = (page: Page, key: string, title: string) => page.getByRole("button").filter({ hasText: title }).filter({ hasText: key });

async function allIssues(page: Page): Promise<{ issues: Issue[]; total: number }> {
  const out = new Map<string, Issue>();
  let total = 0;
  for (let offset = 0; ; offset += 500) {
    const r = await page.context().request.get(`${API}/api/work/issues?limit=500&offset=${offset}`);
    expect(r.status()).toBe(200);
    const body = await r.json();
    total = body.total;
    // Mirror WorkIssueC: a missing issue_type defaults to "task" (legacy rows, e.g. WORK-0001).
    for (const i of body.issues) out.set(i.issue_id, { ...i, issue_type: i.issue_type ?? "task" });
    if (body.issues.length < 500 || offset + 500 >= total) break;
  }
  return { issues: [...out.values()], total };
}

function countsLine(items: Issue[]) {
  const scoped = items.filter((i) => i.issue_type !== "project");
  const tasks = scoped.filter((i) => i.issue_type === "task");
  const done = tasks.filter((t) => t.status === "resolved").length;
  const pct = tasks.length ? Math.round((done / tasks.length) * 100) : 0;
  return `${pct}% · ${done}/${tasks.length} tasks · ${scoped.filter((i) => i.issue_type === "epic").length} epics · ${scoped.filter((i) => i.issue_type === "story").length} stories`;
}

test("TC-2..TC-5 every project and every item is loaded, counted and openable", async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await setup(page);
  const { issues, total } = await allIssues(page);
  const projects = issues.filter((i) => i.issue_type === "project");
  console.log(`API: total=${total} fetched=${issues.length} projects=${projects.map((p) => p.project ?? p.issue_id).join(",")}`);
  expect(issues.length).toBe(total);

  const pages: { offset: string; status: number; rows: number; total: number }[] = [];
  page.on("response", async (r) => {
    const u = new URL(r.url());
    if (u.origin === API && u.pathname === "/api/work/issues" && r.request().method() === "GET") {
      const b = await r.json().catch(() => ({}));
      pages.push({ offset: u.searchParams.get("offset") ?? "0", status: r.status(), rows: b.issues?.length ?? -1, total: b.total ?? -1 });
    }
  });
  await page.goto(`${UI}/v5/work`);
  await expect(page.getByRole("heading", { name: "Projects" })).toBeVisible();

  // TC-2 + TC-4: one card per project row, counts from ALL pages
  for (const p of projects) {
    const key = p.project || p.issue_id;
    const card = cardFor(page, key, p.title);
    await expect(card, `card for ${key}`).toBeVisible();
    await expect(card).toContainText(p.title);
    const line = countsLine(issues.filter((i) => i.project === key));
    await expect(card, `counts for ${key}`).toContainText(line);
    console.log(`card ${key}: "${line}" OK`);
  }

  // TC-3: every page requested, all 200, rows add up to total
  await expect.poll(() => pages.reduce((s, p) => s + p.rows, 0)).toBe(total);
  console.log("pages:", JSON.stringify(pages));
  expect(pages.every((p) => p.status === 200)).toBe(true);
  expect(pages.map((p) => p.offset).sort()).toEqual(Array.from({ length: Math.ceil(total / 500) }, (_, i) => String(i * 500)).sort());

  // TC-5: open ADVW (the project the 500-row window used to hide) → its epics are on the roadmap
  const advwEpics = issues.filter((i) => i.project === "ADVW" && i.issue_type === "epic");
  const advw = projects.find((p) => p.project === "ADVW");
  expect(advw, "ADVW project row exists in the API").toBeTruthy();
  await cardFor(page, "ADVW", advw!.title).click();
  for (const ph of PHASES) {
    const n = advwEpics.filter((e) => e.phase === ph).length;
    await expect(page.getByText(new RegExp(`· ${n} epics$`)).first()).toBeVisible();
  }
  for (const e of advwEpics.filter((e) => PHASES.includes(e.phase ?? ""))) await expect(page.getByText(e.issue_id, { exact: true }).first()).toBeVisible();
  console.log(`ADVW roadmap: ${advwEpics.length} epics (${advwEpics.map((e) => e.issue_id).join(",")}) visible`);
});

test("TC-7 a failed page shows the error state, never a partial project list", async ({ page }) => {
  test.setTimeout(60_000);
  await setup(page);
  await page.route((u) => u.origin === API && u.pathname === "/api/work/issues" && u.searchParams.get("offset") === "500", (route) =>
    route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "injected failure (TC-7)" }) }));
  await page.goto(`${UI}/v5/work`);
  await expect(page.getByText("Couldn't load projects")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("button").filter({ hasText: /% · \d+\/\d+ tasks · / })).toHaveCount(0);
});
