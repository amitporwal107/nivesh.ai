/**
 * One-screen Copilot app (/v5/app) — the internal, admin-only pages:
 * Tool registry, Feed health, Audit log, KPIs.
 *
 * MOCK — not real data: every /api response here is a fixture
 * (e2e/fixtures/copilot-ops-*.json) or an inline payload, in the shape the real
 * endpoint returns (looked at on staging) with synthetic values. Expected
 * values are worked out from the payloads, not copied from the screen.
 *
 * Mocked APIs, production build — see pw.copilot-app.config.ts.
 */
import { test, expect, type Page } from "@playwright/test";
import fs from "fs";
import path from "path";
import { mockApi } from "../helpers/api-mock";

const APP = "/v5/app";
const FX = path.join(process.cwd(), "e2e", "fixtures");
type Bodies = Record<string, unknown>;
const load = (name: string): Bodies => {
  const { _note, ...bodies } = JSON.parse(fs.readFileSync(path.join(FX, name), "utf-8")) as Bodies;
  void _note;
  return bodies;
};

const TOOLS = load("copilot-ops-tools.json");
const FEEDS = load("copilot-ops-feeds.json");
const AUDIT = load("copilot-ops-audit.json");
const KPIS = load("copilot-ops-kpis.json");

const PLAIN_USER = { user_id: "u_plain", email: "user@example.test", name: "Fixture User", is_admin: false, onboarding_completed: true };

const daysAgo = (n: number) => new Date(Date.now() - n * 86_400_000).toISOString();

/** Shape: backend/routes/admin_users.py list_users. Dates are relative to now so the 7/30-day counts are stable. */
const USERS = {
  users: [
    { user_id: "u_fx_c", email: "fixture-c@example.test", name: "Fixture Person C", picture: null, is_admin: false, risk_profile: null, created_at: daysAgo(200), holdings_count: 0, mf_count: 0, plans_count: 0, active_plan: null, last_login_at: daysAgo(90), session_active: false },
    { user_id: "u_fx_a", email: "fixture-a@example.test", name: "Fixture Person A", picture: null, is_admin: true, risk_profile: null, created_at: daysAgo(300), holdings_count: 117, mf_count: 12, plans_count: 1, active_plan: null, last_login_at: daysAgo(2), session_active: true },
    { user_id: "u_fx_d", email: "fixture-d@example.test", name: null, picture: null, is_admin: false, risk_profile: null, created_at: daysAgo(5), holdings_count: 0, mf_count: 0, plans_count: 0, active_plan: null, last_login_at: null, session_active: false },
    { user_id: "u_fx_b", email: "fixture-b@example.test", name: "Fixture Person B", picture: null, is_admin: false, risk_profile: null, created_at: daysAgo(100), holdings_count: 9, mf_count: 9, plans_count: 0, active_plan: null, last_login_at: daysAgo(20), session_active: false },
  ],
  total: 4,
};

const ALL: Bodies = { ...TOOLS, ...FEEDS, ...AUDIT, ...KPIS, "/api/admin/users": USERS };

interface Traffic {
  /** GET count per mocked endpoint path. */
  calls: Record<string, number>;
  /** Every request to /api/admin/* that was not a GET. */
  writes: string[];
  /** Every request to /api/admin/*, any method. */
  admin: string[];
}

const json = (page: Page, pattern: string, body: unknown, status = 200) =>
  page.route(pattern, (route) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) }));

/** Signs in as the admin fixture user and answers every endpoint the four pages read. */
async function setup(page: Page): Promise<Traffic> {
  const traffic: Traffic = { calls: {}, writes: [], admin: [] };
  await mockApi(page, "populated"); // user-profile-onboarded.json is an admin; unknown /api/* → 200 {}
  await page.route("**/api/chat/sessions", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  for (const [endpoint, body] of Object.entries(ALL)) {
    await page.route(`**${endpoint}*`, (route) => {
      traffic.calls[endpoint] = (traffic.calls[endpoint] ?? 0) + 1;
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    });
  }
  page.on("request", (req) => {
    const url = new URL(req.url());
    if (!url.pathname.startsWith("/api/admin/")) return;
    traffic.admin.push(`${req.method()} ${url.pathname}`);
    if (req.method() !== "GET") traffic.writes.push(`${req.method()} ${url.pathname}`);
  });
  return traffic;
}

/** The body of a mocked endpoint with some keys replaced. */
const withKeys = (endpoint: string, patch: Record<string, unknown>) => ({ ...(ALL[endpoint] as Record<string, unknown>), ...patch });

// Two attempts in the HTTP client and two in the query: a 5xx takes a few seconds to surface.
const SLOW = { timeout: 15_000 };

test.describe("Ops pages — Tool registry", () => {
  test("shows the agents, answer models, insight-writer switch, prompts and feature switches the endpoints return", async ({ page }) => {
    const traffic = await setup(page);
    await page.goto(`${APP}/ops/tools`);

    await expect(page.getByTestId("tools-agent-count")).toHaveText("3");
    await expect(page.getByTestId("tools-agent-label")).toHaveText(["Auto-route", "Fixture Tax Agent", "Fixture Risk Agent"]);
    await expect(page.getByTestId("tools-agent-triggers")).toHaveText(["0", "2", "1"]);

    await expect(page.getByTestId("tools-model-count")).toHaveText("2");
    await expect(page.getByTestId("tools-model-row")).toHaveText(["Fixture Model A (default)", "Fixture Model B"]);
    await expect(page.getByTestId("tools-model-default")).toHaveCount(1);
    await expect(page.getByText("fixture-model-b-2026")).toBeVisible();

    // circuit: open, 864000 s left = 10 days
    await expect(page.getByTestId("tools-ai-circuit-state")).toHaveText("Model calls off");
    await expect(page.getByTestId("tools-ai-circuit-until")).toHaveText("in 10 days");

    await expect(page.getByTestId("tools-prompt-count")).toHaveText("3");
    await expect(page.getByTestId("tools-prompt-edited")).toHaveText("1");
    await expect(page.getByTestId("tools-prompt-row")).toHaveText(["fixture_chat_system", "fixture_rating_system", "fixture_parser_system"]);
    await expect(page.getByTestId("tools-prompt-state")).toHaveText(["Edited", "Built-in", "Built-in"]);

    await expect(page.getByTestId("tools-flag-count")).toHaveText("3");
    await expect(page.getByTestId("tools-flag-row")).toHaveText(["Fixture research page", "Fixture chat streaming", "Fixture auto-fix agent"]);
    await expect(page.getByTestId("tools-flag-mode")).toHaveText(["Allow-list", "On for everyone", "Off"]);
    await expect(page.getByTestId("tools-flag-allowed")).toHaveText(["2", "—", "—"]);

    // The tool list itself has no endpoint: the block stays, with its admin-only list.
    await expect(page.getByTestId("tools-registry-not-connected")).toBeVisible();
    await expect(page.getByTestId("tools-registry-not-connected").getByTestId("not-connected-needs")).toBeVisible();

    // Prompt text and allow-listed addresses are in the payloads but never on the page.
    const text = (await page.getByTestId("screen-ops-tools").innerText()).toLowerCase(); // innerText follows CSS upper-casing
    expect(text).not.toContain("must never be rendered");
    expect(text).not.toContain("allowed-one@example.test");
    expect(text).not.toContain("changer@example.test");
    expect(traffic.writes).toEqual([]);
  });

  test("empty lists get an empty state; a closed switch reads as on", async ({ page }) => {
    await setup(page);
    await json(page, "**/api/copilot/agents", { agents: [] });
    await json(page, "**/api/copilot/models/picker", { models: [] });
    await json(page, "**/api/admin/prompts", { prompts: [] });
    await json(page, "**/api/admin/feature-flags", { flags: [], updated_at: null, updated_by: null });
    await json(page, "**/api/admin/ai/circuit", { open: false, opens_until: 0, seconds_remaining: 0 });
    await page.goto(`${APP}/ops/tools`);
    await expect(page.getByTestId("tools-agents-empty")).toBeVisible();
    await expect(page.getByTestId("tools-models-empty")).toBeVisible();
    await expect(page.getByTestId("tools-prompts-empty")).toBeVisible();
    await expect(page.getByTestId("tools-flags-empty")).toBeVisible();
    await expect(page.getByTestId("tools-ai-circuit-state")).toHaveText("Model calls on");
    await expect(page.getByTestId("tools-model-row")).toHaveCount(0);
  });

  test("a failed request shows an error with a retry; a 429 says to wait and is not retried on its own", async ({ page }) => {
    await setup(page);
    let modelCalls = 0;
    let fail = true;
    await page.route("**/api/copilot/models/picker", (route) => {
      modelCalls += 1;
      return fail
        ? route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "fixture failure" }) })
        : route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(ALL["/api/copilot/models/picker"]) });
    });
    let promptCalls = 0;
    await page.route("**/api/admin/prompts", (route) => {
      promptCalls += 1;
      return route.fulfill({ status: 429, contentType: "application/json", body: JSON.stringify({ status: 429, error: "RATE_LIMIT_ERROR", message: "fixture limit" }) });
    });
    // A changed contract: the flags list is missing.
    await json(page, "**/api/admin/feature-flags", { unexpected: true });

    await page.goto(`${APP}/ops/tools`);
    const screen = page.getByTestId("screen-ops-tools");
    const modelError = screen.getByRole("alert").filter({ hasText: "The answer models didn’t load" });
    await expect(modelError).toBeVisible(SLOW);
    await expect(screen.getByRole("alert").filter({ hasText: "The feature switches didn’t load" })).toContainText("not in the expected shape");

    await expect(page.getByTestId("rate-limited")).toBeVisible();
    await expect(page.getByTestId("rate-limited")).toContainText("The prompt list");
    await page.waitForTimeout(2500); // longer than the query's retry delay
    expect(promptCalls).toBe(1);

    // The rest of the page is unaffected, and the retry works.
    await expect(page.getByTestId("tools-agent-count")).toHaveText("3");
    expect(modelCalls).toBeGreaterThan(1);
    fail = false;
    await modelError.getByRole("button", { name: /Retry/ }).click();
    await expect(page.getByTestId("tools-model-count")).toHaveText("2");
  });
});

test.describe("Ops pages — Feed health", () => {
  test("sources: status, last run and the trailing week per feed; a row opens its run history", async ({ page }) => {
    const traffic = await setup(page);
    await page.goto(`${APP}/ops/feeds`);

    // copilot-ops-feeds.json summary: total 4 · healthy 1 · failing 1 · stale 1 · never_run 1
    await expect(page.getByTestId("feeds-total")).toHaveText("4");
    await expect(page.getByTestId("feeds-healthy")).toHaveText("1");
    await expect(page.getByTestId("feeds-failing")).toHaveText("1");
    await expect(page.getByTestId("feeds-stale")).toHaveText("1");
    await expect(page.getByTestId("feeds-never-run")).toHaveText("1");
    await expect(page.getByTestId("feeds-attention-count")).toHaveText("2");
    await expect(page.getByTestId("feeds-attention-row")).toHaveCount(2);

    await expect(page.getByTestId("feeds-row")).toHaveText(["fixture_filings", "fixture_flows", "fixture_backfill", "fixture_prices"]);
    await expect(page.getByTestId("feeds-status")).toHaveText(["Failing", "Stale", "Never run", "Healthy"]);
    await expect(page.getByTestId("feeds-last-run-status")).toHaveText(["failed", "partial", "ok"]); // the never-run feed has none
    await expect(page.getByTestId("feeds-last-run").nth(2)).toHaveText("Never");
    await expect(page.getByTestId("feeds-fail-streak")).toHaveText(["3", "0", "0", "0"]);
    await expect(page.getByTestId("feeds-failed-days")).toHaveText(["3", "0", "0", "0"]);
    await expect(page.getByTestId("feeds-rows")).toHaveText(["0", "12", "—", "3,713"]);

    // fixture_filings week: OK OK OK – FAILED FAILED FAILED, oldest first
    const week = page.getByTestId("feeds-week").first().locator("[data-day]");
    await expect(week).toHaveCount(7);
    expect(await week.evaluateAll((els) => els.map((e) => e.getAttribute("data-status")))).toEqual(["OK", "OK", "OK", "none", "FAILED", "FAILED", "FAILED"]);

    // Only the status request so far: run history, checks, tables and pipeline wait to be opened.
    expect(traffic.admin).toEqual(["GET /api/admin/nidp/feeds/live"]);

    await page.getByRole("row", { name: /fixture_filings — show its run history/ }).click();
    const history = page.getByTestId("feeds-run-history");
    await expect(history).toHaveAttribute("data-ingester", "fixture_filings");
    await expect(history).toContainText("40 ok · 2 partial · 5 failed");
    await expect(history).toContainText("30.9 s");
    await expect(page.getByTestId("feeds-run-last-error")).toHaveText("FixtureError: source returned HTTP 503");
    await expect(page.getByTestId("feeds-run-row")).toHaveCount(3);
    await expect(page.getByTestId("feeds-run-status")).toHaveText(["FAILED", "FAILED", "OK"]);
    await expect(page.getByTestId("feeds-run-written")).toHaveText(["0", "0", "4,310"]);
    expect(traffic.calls["/api/admin/nidp/jobs/fixture_filings/runs"]).toBe(1);

    // Closing the row removes the detail.
    await page.getByRole("row", { name: /fixture_filings — show its run history/ }).click();
    await expect(history).toHaveCount(0);
    expect(traffic.writes).toEqual([]);
  });

  test("run history: a feed with no runs, and a run history that fails to load", async ({ page }) => {
    await setup(page);
    await json(page, "**/api/admin/nidp/jobs/fixture_backfill/runs*", { ingester: "fixture_backfill", runs: [] });
    await json(page, "**/api/admin/nidp/jobs/fixture_flows/runs*", { detail: "fixture failure" }, 500);
    await page.goto(`${APP}/ops/feeds`);
    await page.getByRole("row", { name: /fixture_backfill — show/ }).click();
    await expect(page.getByTestId("feeds-runs-empty")).toHaveText("The job log holds no run for this feed.");
    await page.getByRole("row", { name: /fixture_flows — show/ }).click();
    await expect(page.getByTestId("feeds-run-history")).toHaveAttribute("data-ingester", "fixture_flows");
    await expect(page.getByTestId("feeds-run-history").getByRole("alert")).toContainText("Run history of fixture_flows didn’t load", SLOW);
  });

  test("checks: consistency runs, findings with the stock named, and validation per feed — read when the tab is opened", async ({ page }) => {
    const traffic = await setup(page);
    await page.goto(`${APP}/ops/feeds`);
    await expect(page.getByTestId("feeds-total")).toHaveText("4");
    expect(traffic.calls["/api/admin/nidp/quality/consistency"]).toBeUndefined();
    expect(traffic.calls["/api/admin/nidp/catalog"]).toBeUndefined();

    await page.getByTestId("feeds-tabs").getByRole("tab", { name: "Checks" }).click();
    await expect(page.getByTestId("feeds-check-run-count")).toHaveText("2");
    await expect(page.getByTestId("feeds-check-run")).toHaveText(["Equity", "Mutual funds"]);
    await expect(page.getByTestId("feeds-check-failed")).toHaveText(["2", "0"]);

    await expect(page.getByTestId("feeds-finding-count")).toHaveText("3");
    await expect(page.getByTestId("feeds-finding-row")).toHaveText(["Price temporal change", "Shareholding sum", "Nav temporal change"]);
    await expect(page.getByTestId("feeds-finding-severity")).toHaveText(["WARN", "ERROR", "WARN"]);
    const entities = page.getByTestId("feeds-finding-entity");
    await expect(entities).toContainText(["FIXTUREA", "FIXTUREB", "Scheme 990001"]); // the icon's letters are text too
    // Stock findings carry the stock's icon; a scheme finding has only a code, so no icon.
    await expect(entities.nth(0).getByTestId("entity-icon")).toHaveAttribute("data-kind", "stock");
    await expect(entities.nth(0).getByTestId("entity-icon")).toHaveAttribute("data-key", "FIXTUREA");
    await expect(entities.nth(2).getByTestId("entity-icon")).toHaveCount(0);

    // catalog.validation: 5 runs over 2 feeds. fixture_flows: newest (10 Oct) FAILED 2/6; fixture_prices: newest (13 Oct) PASSED 0/13.
    await expect(page.getByTestId("feeds-validation-count")).toHaveText("2");
    await expect(page.getByTestId("feeds-validation-window")).toHaveText("5");
    await expect(page.getByTestId("feeds-validation-row")).toHaveText(["fixture_flows", "fixture_prices"]);
    await expect(page.getByTestId("feeds-validation-status")).toHaveText(["FAILED", "PASSED"]);
    await expect(page.getByTestId("feeds-checks")).toContainText("2 / 6");
    expect(traffic.calls["/api/admin/nidp/quality/consistency"]).toBe(1);
    expect(traffic.calls["/api/admin/nidp/catalog"]).toBe(1);
  });

  test("tables and filings pipeline show row counts, date range and stage state", async ({ page }) => {
    const traffic = await setup(page);
    await page.goto(`${APP}/ops/feeds`);
    await page.getByTestId("feeds-tabs").getByRole("tab", { name: "Tables" }).click();
    await expect(page.getByTestId("feeds-table-count")).toHaveText("3");
    await expect(page.getByTestId("feeds-table-row")).toHaveText(["fixture_prices_eod", "fixture_delivery", "fixture_instruments"]);
    await expect(page.getByTestId("feeds-table-rows")).toHaveText(["8,54,201", "3,80,366", "6,119"]); // Indian digit grouping
    await expect(page.getByTestId("feeds-table-latest")).toHaveText(["12 Oct 2026", "9 Oct 2026", "—"]);
    await expect(page.getByTestId("feeds-tables")).toContainText("12,34,567"); // by_domain rows

    await page.getByTestId("feeds-tabs").getByRole("tab", { name: "Filings pipeline" }).click();
    await expect(page.getByTestId("feeds-stage-healthy")).toHaveText("1");
    await expect(page.getByTestId("feeds-stage-total")).toHaveText("3");
    await expect(page.getByTestId("feeds-stage-row")).toHaveText(["Ingest", "Classify", "Embed"]);
    await expect(page.getByTestId("feeds-stage-done")).toHaveText(["5,000", "4,800", "0"]);
    await expect(page.getByTestId("feeds-stage-state")).toHaveText(["Healthy", "Backlog", "Never run"]);
    expect(traffic.calls["/api/admin/nidp/pipeline/stages"]).toBe(1);
    expect(traffic.writes).toEqual([]);
  });

  test("checks, tables and pipeline: empty states", async ({ page }) => {
    await setup(page);
    await json(page, "**/api/admin/nidp/quality/consistency", { runs: [], findings: [], errors: { runs: null, findings: null } });
    await json(page, "**/api/admin/nidp/catalog", withKeys("/api/admin/nidp/catalog", { by_domain: [], tables: [], validation: [] }));
    await json(page, "**/api/admin/nidp/pipeline/stages", { generated_at: null, stages: [], summary: { total: 0, healthy: 0, backlog: 0, lagging: 0, stale: 0, never: 0 }, db_error: null });
    await page.goto(`${APP}/ops/feeds`);
    const tabs = page.getByTestId("feeds-tabs");
    await tabs.getByRole("tab", { name: "Checks" }).click();
    await expect(page.getByTestId("feeds-checks-empty")).toBeVisible();
    await expect(page.getByTestId("feeds-validation-empty")).toBeVisible();
    await tabs.getByRole("tab", { name: "Tables" }).click();
    await expect(page.getByTestId("feeds-tables-empty")).toBeVisible();
    await tabs.getByRole("tab", { name: "Filings pipeline" }).click();
    await expect(page.getByTestId("feeds-pipeline-empty")).toBeVisible();
  });

  test("checks with runs but no findings; a pipeline the data platform could not read", async ({ page }) => {
    await setup(page);
    await json(page, "**/api/admin/nidp/quality/consistency", withKeys("/api/admin/nidp/quality/consistency", { findings: [] }));
    await json(page, "**/api/admin/nidp/pipeline/stages", { generated_at: null, stages: [], summary: { total: 0, healthy: 0, backlog: 0, lagging: 0, stale: 0, never: 0 }, db_error: "fixture: query service timed out" });
    await page.goto(`${APP}/ops/feeds`);
    const tabs = page.getByTestId("feeds-tabs");
    await tabs.getByRole("tab", { name: "Checks" }).click();
    await expect(page.getByTestId("feeds-finding-count")).toHaveText("0");
    await expect(page.getByTestId("feeds-findings-empty")).toBeVisible();
    await tabs.getByRole("tab", { name: "Filings pipeline" }).click();
    await expect(page.getByTestId("feeds-pipeline-db-error")).toContainText("fixture: query service timed out");
    await expect(page.getByTestId("feeds-pipeline-empty")).toHaveCount(0);
  });

  test("checks, tables and pipeline: error states, with the status table still shown", async ({ page }) => {
    await setup(page);
    await json(page, "**/api/admin/nidp/quality/consistency", { detail: "fixture failure" }, 500);
    await json(page, "**/api/admin/nidp/catalog", { detail: "NIDP Query API /catalog failed: fixture" }, 502);
    await json(page, "**/api/admin/nidp/pipeline/stages", { status: 429, error: "RATE_LIMIT_ERROR" }, 429);
    await page.goto(`${APP}/ops/feeds`);
    const tabs = page.getByTestId("feeds-tabs");
    await tabs.getByRole("tab", { name: "Checks" }).click();
    const checks = page.getByTestId("feeds-checks");
    await expect(checks.getByRole("alert").filter({ hasText: "The consistency checks didn’t load" })).toBeVisible(SLOW);
    await expect(checks.getByRole("alert").filter({ hasText: "The validation runs didn’t load" })).toBeVisible(SLOW);
    await tabs.getByRole("tab", { name: "Tables" }).click();
    await expect(page.getByTestId("feeds-tables").getByRole("alert")).toContainText("The warehouse tables didn’t load", SLOW);
    await tabs.getByRole("tab", { name: "Filings pipeline" }).click();
    await expect(page.getByTestId("feeds-pipeline").getByTestId("rate-limited")).toBeVisible();
    await tabs.getByRole("tab", { name: "Sources" }).click();
    await expect(page.getByTestId("feeds-row")).toHaveCount(4);
  });

  test("status request fails: the error is shown and the other sections stay reachable", async ({ page }) => {
    await setup(page);
    await json(page, "**/api/admin/nidp/feeds/live", { detail: "fixture failure" }, 500);
    await page.goto(`${APP}/ops/feeds`);
    await expect(page.getByTestId("screen-ops-feeds").getByRole("alert")).toContainText("Feed status didn’t load", SLOW);
    await expect(page.getByTestId("feeds-sources-none")).toBeVisible();
    await page.getByTestId("feeds-tabs").getByRole("tab", { name: "Tables" }).click();
    await expect(page.getByTestId("feeds-table-count")).toHaveText("3");
  });
});

test.describe("Ops pages — Audit log", () => {
  test("this account's trail, with the broker named; the platform-wide log stays not connected", async ({ page }) => {
    const traffic = await setup(page);
    await page.goto(`${APP}/ops/audit`);
    await expect(page.getByTestId("audit-count")).toHaveText("3");
    await expect(page.getByTestId("audit-action")).toHaveText(["Broker holdings synced · Zerodha", "CAS statement uploaded", "Sign-in failed"]);
    await expect(page.getByTestId("audit-outcome")).toHaveText(["success", "success", "denied"]);
    const first = page.getByTestId("audit-row").first();
    await expect(first.getByTestId("entity-icon")).toHaveAttribute("data-kind", "broker");
    await expect(page.getByTestId("audit-row").nth(1).getByTestId("entity-icon")).toHaveCount(0);
    await expect(page.getByTestId("audit-platform-not-connected")).toBeVisible();

    // Address, device and the e-mail inside `details` are in the payload but not on the page.
    const text = (await page.getByTestId("screen-ops-audit").innerText()).toLowerCase(); // innerText follows CSS upper-casing
    expect(text).not.toContain("203.0.113.7");
    expect(text).not.toContain("fixtureagent");
    expect(text).not.toContain("fixture-admin@example.test");
    // The two admin lists are not requested until their tab is opened.
    expect(traffic.admin).toEqual([]);
  });

  test("sign-ins by account: newest first, with how many sessions are still valid", async ({ page }) => {
    const traffic = await setup(page);
    await page.goto(`${APP}/ops/audit`);
    await page.getByTestId("audit-tabs").getByRole("tab", { name: "Sign-ins by account" }).click();
    await expect(page.getByTestId("audit-signin-count")).toHaveText("4");
    await expect(page.getByTestId("audit-signin-live")).toHaveText("1");
    // sorted by last_login_at: A (2 days ago), B (20), C (90), D (never)
    const rows = page.getByTestId("audit-signin-row");
    await expect(rows).toHaveCount(4);
    expect(await rows.evaluateAll((els) => els.map((e) => e.getAttribute("data-user")))).toEqual(["u_fx_a", "u_fx_b", "u_fx_c", "u_fx_d"]);
    await expect(rows.first()).toContainText("Fixture Person A");
    await expect(rows.first()).toContainText("fixture-a@example.test");
    await expect(page.getByTestId("audit-signin-session")).toHaveText(["Still valid", "Expired", "Expired", "—"]);
    await expect(page.getByTestId("audit-signin-last").last()).toHaveText("Never signed in");
    await expect(page.getByTestId("audit-platform-not-connected")).toBeVisible();
    expect(traffic.admin).toEqual(["GET /api/admin/users"]);
  });

  test("fund-data refreshes: each fund with its fund house icon and result", async ({ page }) => {
    const traffic = await setup(page);
    await page.goto(`${APP}/ops/audit`);
    await page.getByTestId("audit-tabs").getByRole("tab", { name: "Fund-data refreshes" }).click();
    await expect(page.getByTestId("audit-fund-count")).toHaveText("3");
    await expect(page.getByTestId("audit-fund-failed")).toHaveText("1");
    await expect(page.getByTestId("audit-fund-partial")).toHaveText("1");
    const funds = page.getByTestId("audit-fund-row");
    await expect(funds).toContainText(["HDFC Fixture Flexi Cap Fund Direct Growth", "SBI Fixture Arbitrage Fund Direct Growth", "Kotak Fixture Small Cap Fund Direct Growth"]);
    const icons = page.getByTestId("audit-fund-log").getByTestId("entity-icon");
    expect(await icons.evaluateAll((els) => els.map((e) => `${e.getAttribute("data-kind")}:${e.getAttribute("data-key")}`))).toEqual(["fund-house:HDFC", "fund-house:SBI", "fund-house:Kotak"]);
    await expect(page.getByTestId("audit-fund-status")).toHaveText(["ok", "partial", "failed"]);
    await expect(page.getByTestId("audit-fund-log")).toContainText("only 4 holdings");
    await expect(page.getByTestId("audit-fund-log")).toContainText("1m 35s"); // 95,000 ms
    // The log's timestamps have no zone suffix and are UTC.
    await expect(page.getByTestId("audit-fund-time").first()).toHaveAttribute("title", "2026-10-13T10:11:25.529505Z");
    expect(traffic.admin).toEqual(["GET /api/admin/mf/audit-log"]);
    expect(traffic.writes).toEqual([]);
  });

  test("empty and error states of the three lists", async ({ page }) => {
    await setup(page);
    await json(page, "**/api/compliance/audit*", { rows: [], count: 0 });
    await json(page, "**/api/admin/users", { users: [], total: 0 });
    await json(page, "**/api/admin/mf/audit-log*", { audit: [] });
    await page.goto(`${APP}/ops/audit`);
    const tabs = page.getByTestId("audit-tabs");
    await expect(page.getByTestId("audit-empty")).toBeVisible();
    await tabs.getByRole("tab", { name: "Sign-ins by account" }).click();
    await expect(page.getByTestId("audit-signins-empty")).toBeVisible();
    await tabs.getByRole("tab", { name: "Fund-data refreshes" }).click();
    await expect(page.getByTestId("audit-fund-empty")).toBeVisible();

    await json(page, "**/api/compliance/audit*", { detail: "fixture failure" }, 500);
    await json(page, "**/api/admin/users", { detail: "Admin access required" }, 403);
    await json(page, "**/api/admin/mf/audit-log*", { detail: "fixture failure" }, 500);
    await page.reload();
    await expect(page.getByTestId("screen-ops-audit").getByRole("alert")).toContainText("The audit trail didn’t load", SLOW);
    await tabs.getByRole("tab", { name: "Sign-ins by account" }).click();
    await expect(page.getByTestId("audit-signins").getByTestId("forbidden")).toContainText("The account list");
    await tabs.getByRole("tab", { name: "Fund-data refreshes" }).click();
    await expect(page.getByTestId("audit-fund-log").getByRole("alert")).toContainText("The fund-data refresh log didn’t load", SLOW);
  });
});

test.describe("Ops pages — KPIs", () => {
  test("every figure comes from an endpoint; sign-ins are counted only on request", async ({ page }) => {
    const traffic = await setup(page);
    await page.goto(`${APP}/ops/kpis`);

    // /api/admin/stats
    await expect(page.getByTestId("kpi-users")).toHaveText("31");
    await expect(page.getByTestId("kpi-portfolios")).toHaveText("22");
    await expect(page.getByTestId("kpi-holdings")).toHaveText("418");
    await expect(page.getByTestId("kpi-conversion")).toHaveText("62.5%");
    // /api/admin/nidp/feeds/live summary
    await expect(page.getByTestId("kpi-feeds-healthy")).toHaveText("1 of 4");
    await expect(page.getByTestId("kpi-feeds-healthy-pct")).toContainText("25.0%");

    // /api/admin/nidp/quality/summary — newest day per data set (the older equity day, all 11.1, is not shown)
    await expect(page.getByTestId("kpi-quality-row")).toHaveText(["Equity", "Mutual funds"]);
    await expect(page.getByTestId("kpi-quality-overall")).toHaveText(["90.6", "99.2"]);
    await expect(page.getByTestId("kpi-quality-freshness").nth(1)).toHaveText("96.2");
    await expect(page.getByTestId("kpi-quality-decision")).toHaveText(["REJECT", "AUTO PUBLISH"]);
    await expect(page.getByTestId("kpi-quality-held")).toHaveText("1");

    // /api/admin/ocr-correction/stats
    await expect(page.getByTestId("kpi-ocr-total")).toHaveText("18");
    await expect(page.getByTestId("kpi-ocr-isin")).toHaveText("14");
    await expect(page.getByTestId("kpi-ocr-name")).toHaveText("3");
    await expect(page.getByTestId("kpi-ocr-auto")).toHaveText("2");

    // /api/data-health/summary
    await expect(page.getByTestId("kpi-app-jobs-status")).toHaveText("Warning");
    await expect(page.getByTestId("kpi-app-jobs-issues")).toHaveText("1");
    await expect(page.getByTestId("kpi-app-jobs-issue")).toContainText("Fixture upload scanner");

    // /api/work/stats
    await expect(page.getByTestId("kpi-issues-total")).toHaveText("23");
    await expect(page.getByTestId("kpi-issues-open")).toHaveText("7");
    await expect(page.getByTestId("kpi-issues-in-progress")).toHaveText("4");
    await expect(page.getByTestId("kpi-issues-resolved")).toHaveText("8");
    await expect(page.getByTestId("kpi-issues-priority")).toHaveText("P1 3 · P2 15 · P3 5");

    // /api/move-odds/diagnostics — mean_net is a fraction per trade
    await expect(page.getByTestId("kpi-setups-validated")).toHaveText("1 of 4");
    await expect(page.getByTestId("kpi-setup-row")).toHaveText(["Fixture breakout", "Fixture breakout", "Fixture pullback", "Fixture pullback"]);
    await expect(page.getByTestId("kpi-setup-net")).toHaveText(["−0.65%", "−0.74%", "+0.42%", "−0.11%"]);
    await expect(page.getByTestId("kpi-setup-result")).toHaveText(["failed", "failed", "passed", "failed"]);

    // /api/positional/backtest/calibration — probability is 0–1
    await expect(page.getByTestId("kpi-calibration-count")).toHaveText("2");
    await expect(page.getByTestId("kpi-calibration-rate")).toHaveText(["22.0%", "32.0%"]);

    // /api/admin/ai/circuit
    await expect(page.getByTestId("tools-ai-circuit-state")).toHaveText("Model calls off");

    // What is still unmeasured stays declared.
    for (const id of ["kpi-data-not-connected", "kpi-ux-not-connected", "kpi-decision-not-connected", "kpi-efficiency-not-connected"]) {
      await expect(page.getByTestId(id)).toBeVisible();
    }

    // Sign-ins: nothing is counted, and the directory is not read, until asked.
    await expect(page.getByTestId("kpi-signins-ask")).toBeVisible();
    await page.waitForLoadState("networkidle");
    expect(traffic.calls["/api/admin/users"]).toBeUndefined();
    expect([...traffic.admin].sort()).toEqual([
      "GET /api/admin/ai/circuit",
      "GET /api/admin/nidp/feeds/live",
      "GET /api/admin/nidp/quality/summary",
      "GET /api/admin/ocr-correction/stats",
      "GET /api/admin/stats",
    ]);
    await page.getByTestId("kpi-signins-load").click();
    // USERS: A signed in 2 days ago (valid session), B 20 days ago, C 90 days ago, D never.
    await expect(page.getByTestId("kpi-signed-in-7d")).toHaveText("1");
    await expect(page.getByTestId("kpi-signed-in-30d")).toHaveText("2");
    await expect(page.getByTestId("kpi-sessions-valid")).toHaveText("1");
    await expect(page.getByTestId("kpi-never-signed-in")).toHaveText("1");
    expect(traffic.calls["/api/admin/users"]).toBe(1);
    expect(traffic.writes).toEqual([]);
  });

  test("empty states", async ({ page }) => {
    await setup(page);
    await json(page, "**/api/admin/stats", { whitelist: { total: 0, active: 0, pending: 0, blocked: 0, conversion_rate: 0 }, usage: { total_users: 0, total_portfolios: 0, total_holdings: 0 } });
    await json(page, "**/api/admin/users", { users: [], total: 0 });
    await json(page, "**/api/admin/nidp/feeds/live", withKeys("/api/admin/nidp/feeds/live", { summary: { total: 0, healthy: 0, failing: 0, stale: 0, never_run: 0, running: 0 }, feeds: [] }));
    await json(page, "**/api/admin/nidp/quality/summary", { quality: [], certified: [], gate: [], exceptions: [], errors: { quality: null, certified: null, gate: null, exceptions: null } });
    await json(page, "**/api/data-health/summary", { status: "ok", issues: [], checked_at: "2026-10-13T12:53:02+00:00" });
    await json(page, "**/api/work/stats", { total: 0, by_status: { open: 0, in_progress: 0, in_review: 0, testing_qa: 0, resolved: 0, wont_fix: 0 }, by_priority: { P1: 0, P2: 0, P3: 0 } });
    await json(page, "**/api/positional/backtest/calibration", { buckets: [], count: 0 }); // what staging returned on 2026-10-13
    await page.goto(`${APP}/ops/kpis`);
    await expect(page.getByTestId("kpi-platform-empty")).toBeVisible();
    await expect(page.getByTestId("kpi-feeds-empty")).toBeVisible();
    await expect(page.getByTestId("kpi-quality-empty")).toBeVisible();
    await expect(page.getByTestId("kpi-app-jobs-status")).toHaveText("All clear");
    await expect(page.getByTestId("kpi-app-jobs-issues")).toHaveText("0");
    await expect(page.getByTestId("kpi-issues-empty")).toBeVisible();
    await expect(page.getByTestId("kpi-calibration-empty")).toBeVisible();
    await expect(page.getByTestId("kpi-calibration-row")).toHaveCount(0);
    await page.getByTestId("kpi-signins-load").click();
    await expect(page.getByTestId("kpi-signins-empty")).toBeVisible();
  });

  test("error states: each block fails on its own, and a feature that is off for the account says so", async ({ page }) => {
    await setup(page);
    await json(page, "**/api/admin/stats", { detail: "fixture failure" }, 500);
    await json(page, "**/api/admin/nidp/quality/summary", { detail: "NIDP Query API not configured" }, 503);
    await json(page, "**/api/admin/ocr-correction/stats", { status: 429, error: "RATE_LIMIT_ERROR" }, 429);
    await json(page, "**/api/data-health/summary", { detail: "fixture failure" }, 500);
    await json(page, "**/api/work/stats", { detail: "fixture failure" }, 500);
    await json(page, "**/api/move-odds/diagnostics", { detail: "feature_not_enabled" }, 403);
    await json(page, "**/api/positional/backtest/calibration", { detail: "fixture failure" }, 500);
    await json(page, "**/api/admin/ai/circuit", {}); // a changed contract
    await page.goto(`${APP}/ops/kpis`);
    const screen = page.getByTestId("screen-ops-kpis");
    for (const what of ["Platform counts", "The data-quality scores", "The app’s job status", "The issue counts", "The calibration table"]) {
      await expect(screen.getByRole("alert").filter({ hasText: `${what} didn’t load` })).toBeVisible(SLOW);
    }
    await expect(screen.getByRole("alert").filter({ hasText: "The insight writer’s status didn’t load" })).toContainText("not in the expected shape");
    await expect(screen.getByTestId("rate-limited")).toContainText("Statement corrections");
    await expect(screen.getByTestId("forbidden")).toContainText("Move odds");
    // No figure is shown for a block that failed; the feed block, which loaded, still is.
    await expect(page.getByTestId("kpi-users")).toHaveCount(0);
    await expect(page.getByTestId("kpi-quality-row")).toHaveCount(0);
    await expect(page.getByTestId("kpi-ocr-total")).toHaveCount(0);
    await expect(page.getByTestId("kpi-setups-validated")).toHaveCount(0);
    await expect(page.getByTestId("kpi-feeds-healthy")).toHaveText("1 of 4");
  });
});

test.describe("Ops pages — access", () => {
  test("a non-admin is sent home from all four pages and no admin endpoint is called", async ({ page }) => {
    const traffic = await setup(page);
    await json(page, "**/api/auth/me", PLAIN_USER);
    for (const view of ["ops/tools", "ops/feeds", "ops/audit", "ops/kpis"]) {
      await page.goto(`${APP}/${view}`);
      await expect(page, `${view} should redirect`).toHaveURL(/\/v5\/app$/);
      await expect(page.getByTestId("copilot-rail")).toBeVisible();
      await expect(page.getByTestId("rail-internal")).toHaveCount(0);
      await expect(page.getByTestId(`screen-${view.replace("/", "-")}`)).toHaveCount(0);
      await page.waitForLoadState("networkidle");
    }
    expect(traffic.admin).toEqual([]);
  });

  test("an admin moves between the four pages with the tab strip", async ({ page }) => {
    await setup(page);
    await page.goto(`${APP}/ops/tools`);
    const nav = page.getByRole("navigation", { name: "Operations pages" });
    await nav.getByRole("button", { name: "Feed health" }).click();
    await expect(page.getByTestId("screen-ops-feeds")).toBeVisible();
    await nav.getByRole("button", { name: "Audit log" }).click();
    await expect(page.getByTestId("screen-ops-audit")).toBeVisible();
    await nav.getByRole("button", { name: "KPIs" }).click();
    await expect(page.getByTestId("screen-ops-kpis")).toBeVisible();
    await nav.getByRole("button", { name: "Tools" }).click();
    await expect(page.getByTestId("screen-ops-tools")).toBeVisible();
  });
});

test.describe("Ops pages — phone (390×844)", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  async function expectNoSidewaysScroll(page: Page, where: string) {
    const over = await page.evaluate(() => {
      const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
      return {
        doc: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        scroll: sc ? sc.scrollWidth - sc.clientWidth : 0,
      };
    });
    expect.soft(over.doc, `${where}: page scrolls sideways`).toBeLessThanOrEqual(1);
    expect.soft(over.scroll, `${where}: content area scrolls sideways`).toBeLessThanOrEqual(1);
  }

  test("no page scrolls sideways, with every section and an opened feed row", async ({ page }) => {
    test.setTimeout(90_000);
    await setup(page);

    await page.goto(`${APP}/ops/tools`);
    await expect(page.getByTestId("tools-flag-count")).toHaveText("3");
    await expectNoSidewaysScroll(page, "ops/tools");

    await page.goto(`${APP}/ops/feeds`);
    await expect(page.getByTestId("feeds-row")).toHaveCount(4);
    await expectNoSidewaysScroll(page, "ops/feeds · sources");
    await page.getByRole("row", { name: /fixture_filings — show its run history/ }).click();
    await expect(page.getByTestId("feeds-run-row")).toHaveCount(3);
    await expectNoSidewaysScroll(page, "ops/feeds · run history open");
    // The opened detail is as wide as the visible table, not the scrolled one.
    const box = await page.getByTestId("feeds-run-history").boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(390);
    for (const [tab, testId] of [["Checks", "feeds-finding-count"], ["Tables", "feeds-table-count"], ["Filings pipeline", "feeds-stage-total"]]) {
      await page.getByTestId("feeds-tabs").getByRole("tab", { name: tab }).click();
      await expect(page.getByTestId(testId)).toBeVisible();
      await expectNoSidewaysScroll(page, `ops/feeds · ${tab}`);
    }

    await page.goto(`${APP}/ops/audit`);
    await expect(page.getByTestId("audit-row")).toHaveCount(3);
    await expectNoSidewaysScroll(page, "ops/audit · this account");
    for (const [tab, testId] of [["Sign-ins by account", "audit-signin-count"], ["Fund-data refreshes", "audit-fund-count"]]) {
      await page.getByTestId("audit-tabs").getByRole("tab", { name: tab }).click();
      await expect(page.getByTestId(testId)).toBeVisible();
      await expectNoSidewaysScroll(page, `ops/audit · ${tab}`);
    }

    await page.goto(`${APP}/ops/kpis`);
    await expect(page.getByTestId("kpi-calibration-count")).toHaveText("2");
    await expect(page.getByTestId("kpi-quality-row")).toHaveCount(2);
    await page.getByTestId("kpi-signins-load").click();
    await expect(page.getByTestId("kpi-signed-in-7d")).toHaveText("1");
    await expectNoSidewaysScroll(page, "ops/kpis");
  });
});

// Screenshots of the four pages on fixture data, for review by eye. Not an
// assertion: skipped unless SHOT_DIR is set (as in copilot-app-shots.spec.ts).
// The viewport is tall so a whole page fits without scrolling the shell.
for (const size of [{ tag: "desktop", width: 1280, height: 2800 }, { tag: "phone", width: 390, height: 4200 }]) {
  test.describe(`Ops pages — shots ${size.tag}`, () => {
    test.skip(!process.env.SHOT_DIR, "set SHOT_DIR to capture screenshots");
    test.use({ viewport: { width: size.width, height: size.height }, ...(size.tag === "phone" ? { hasTouch: true, isMobile: true } : {}) });

    test(`capture ${size.tag}`, async ({ page }) => {
      test.setTimeout(90_000);
      const dir = process.env.SHOT_DIR as string;
      const shot = async (name: string) => {
        await page.waitForLoadState("networkidle");
        await page.evaluate(() => document.fonts.ready);
        await page.screenshot({ path: path.join(dir, `ops-${size.tag}-${name}.png`) });
      };
      await setup(page);
      await page.goto(`${APP}/ops/tools`);
      await page.getByTestId("tools-flag-count").waitFor();
      await shot("tools");
      await page.goto(`${APP}/ops/feeds`);
      await page.getByRole("row", { name: /fixture_filings — show its run history/ }).click();
      await page.getByTestId("feeds-run-row").first().waitFor();
      await shot("feeds-sources");
      for (const [tab, name] of [["Checks", "feeds-checks"], ["Tables", "feeds-tables"], ["Filings pipeline", "feeds-pipeline"]]) {
        await page.getByTestId("feeds-tabs").getByRole("tab", { name: tab }).click();
        await shot(name);
      }
      await page.goto(`${APP}/ops/audit`);
      await page.getByTestId("audit-row").first().waitFor();
      await shot("audit-account");
      for (const [tab, name] of [["Sign-ins by account", "audit-signins"], ["Fund-data refreshes", "audit-funds"]]) {
        await page.getByTestId("audit-tabs").getByRole("tab", { name: tab }).click();
        await shot(name);
      }
      await page.goto(`${APP}/ops/kpis`);
      await page.getByTestId("kpi-signins-load").click();
      await page.getByTestId("kpi-signed-in-7d").waitFor();
      await shot("kpis");
    });
  });
}
