/**
 * One-screen Copilot app against the REAL staging backend (TC-22).
 *
 * Skipped unless LIVE_TOKEN_FILE points at a file holding a staging session
 * token. The token is read from that file only — it is never logged, and no
 * response body is printed (only statuses, counts and the text the screen shows).
 *
 * Serve the production build with `vite preview` (its /api proxy goes to
 * staging, see vite.config.ts) and run:
 *
 *   LIVE_TOKEN_FILE=/secrets/token npx playwright test --config pw.copilot-app.config.ts copilot-app-live
 *
 * This asks real questions, so each run adds threads to that account's chat
 * history on staging.
 */
import { test, expect, type Page } from "@playwright/test";
import fs from "fs";
import path from "path";

const TOKEN_FILE = process.env.LIVE_TOKEN_FILE;
const OUT = process.env.SHOT_DIR;
const APP = "/v5/app";

const inr = (rupees: number) => `₹${new Intl.NumberFormat("en-IN").format(Math.round(rupees))}`;
const shot = async (page: Page, name: string) => { if (OUT) await page.screenshot({ path: path.join(OUT, `${name}.png`) }); };

const VIEWS = [
  "tool/analysis", "tool/recommend", "tool/research", "tool/screener", "tool/markets", "tool/optlab", "trader",
  "page/watchlist", "page/saved", "page/plan", "page/ledger", "page/paper", "page/brokers", "page/settings",
  "advisor", "builder", "ops/tools", "ops/feeds", "ops/audit", "ops/kpis",
];

/** Ask one question and report what the thread showed once the answer settled. */
async function askAndReport(page: Page, question: string, label: string) {
  const input = page.getByTestId("composer-input");
  await input.fill(question);
  await input.press("Enter");
  await expect(page).toHaveURL(/\/v5\/app\/t\/[^/]+$/, { timeout: 30_000 });
  const turn = page.getByTestId("thread-turn").last();
  const started = Date.now();
  await expect(turn).toHaveAttribute("data-state", /saved|error|stopped/, { timeout: 170_000 });
  const state = await turn.getAttribute("data-state");
  const text = (await turn.getByTestId("answer-text").count()) ? (await turn.getByTestId("answer-text").innerText()).replace(/\s+/g, " ").trim() : "";
  const report = {
    label,
    state,
    seconds: Math.round((Date.now() - started) / 100) / 10,
    classPill: (await turn.getByTestId("answer-class").count()) ? await turn.getByTestId("answer-class").innerText() : null,
    routed: (await turn.getByTestId("answer-routed").count()) ? await turn.getByTestId("answer-routed").innerText() : null,
    trace: (await turn.getByTestId("answer-trace-label").count()) ? await turn.getByTestId("answer-trace-label").innerText() : null,
    widget: await turn.getByTestId("answer-widget").count(),
    answerChars: text.length,
    answerStart: text.slice(0, 160),
    followUps: await turn.getByTestId("answer-followups").getByRole("button").count(),
    banner: (await turn.locator('[data-testid^="answer-banner-"]').count()) ? (await turn.locator('[data-testid^="answer-banner-"]').first().innerText()).replace(/\s+/g, " ") : null,
  };
  console.log(`LIVE ${JSON.stringify(report)}`);
  return report;
}

test.describe("Copilot app — live staging", () => {
  test.skip(!TOKEN_FILE, "set LIVE_TOKEN_FILE to run against staging");
  test.use({ viewport: { width: 1440, height: 900 } });
  test.describe.configure({ mode: "serial" });

  test.beforeEach(async ({ context }) => {
    const token = fs.readFileSync(TOKEN_FILE as string, "utf-8").trim();
    await context.addCookies([{ name: "session_token", value: token, domain: "localhost", path: "/", httpOnly: true }]);
  });

  test("TC-22 home shows the real portfolio value and market data", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    const [me, holdings, markets] = await Promise.all([
      page.request.get("/api/auth/me").then((r) => r.json()),
      page.request.get("/api/portfolio/holdings-enriched?fresh=false").then((r) => r.json()),
      page.request.get("/api/markets/home").then((r) => r.json()),
    ]);
    await page.goto(APP);
    const first = String(me.name ?? "").trim().split(/\s+/)[0];
    await expect(page.getByTestId("home-headline")).toHaveText(`What would you like to know${first ? `, ${first}` : ""}?`);

    // The value on screen is the total the API returned, to the rupee.
    const value = holdings?.totals?.value_rs as number | undefined;
    if (typeof value === "number" && value > 0 && holdings.holdings.length > 0) {
      await expect(page.getByTestId("context-portfolio-value")).toHaveText(inr(value));
      await expect(page.getByTestId("evidence-context")).toContainText(`${holdings.holdings.length} holdings`);
    } else {
      await expect(page.getByTestId("context-no-portfolio")).toBeVisible();
    }

    const nifty = (markets.indices as Array<{ name: string; value: number | null; is_vix: boolean }>).find((i) => /nifty\s*50\b/i.test(i.name) && !i.is_vix);
    if (nifty?.value != null) {
      await expect(page.getByTestId("home-market-strip")).toContainText(`NIFTY 50 ${new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(nifty.value)}`);
    }
    await expect(page.getByTestId("thread-row").first()).toBeVisible(); // real chat history in the rail
    console.log(`LIVE ${JSON.stringify({
      label: "home",
      threadsInRail: await page.getByTestId("thread-row").count(),
      todayTitle: (await page.getByTestId("home-today-title").count()) ? await page.getByTestId("home-today-title").innerText() : null,
      todayCards: await page.getByTestId("home-today-card").count(),
      marketStrip: (await page.getByTestId("home-market-strip").count()) ? (await page.getByTestId("home-market-strip").innerText()).replace(/\s+/g, " ") : null,
      freshness: (await page.getByTestId("composer-freshness").count()) ? await page.getByTestId("composer-freshness").innerText() : null,
      holdings: holdings?.holdings?.length ?? null,
      valueShown: (await page.getByTestId("context-portfolio-value").count()) ? "matches API total" : "no portfolio",
    })}`);
    await shot(page, "live-home");
    expect(errors).toEqual([]);
  });

  test("TC-22 a real question gets a real streamed answer", async ({ page }) => {
    test.setTimeout(240_000);
    await page.goto(APP);
    await expect(page.getByTestId("home-headline")).toBeVisible();
    const r = await askAndReport(page, "Which sectors are leading the market this month?", "default context");
    await shot(page, "live-thread");
    expect(r.state, r.banner ?? "").toBe("saved");
    expect(r.answerChars).toBeGreaterThan(40);
  });

  test("TC-22 a portfolio question with the account's own profile open", async ({ page }) => {
    test.setTimeout(240_000);
    // An advisor workspace answers about the client book at its root. Opening a
    // profile (the existing app's own-book switch) sends X-Active-Profile, which
    // is what routes a question to the portfolio engine and its tools.
    const book = await page.request.get("/api/mfd/profiles?include_self=true").then((r) => (r.ok() ? r.json() : null));
    const self = (book?.profiles as Array<{ profile_id: string; name: string; type: string }> | undefined)?.find((p) => p.type === "SELF");
    test.skip(!self, "this account has no own-book profile to open");
    await page.addInitScript(([id, name]) => {
      localStorage.setItem("nivesh.impersonation", JSON.stringify({ state: { profileId: id, name }, version: 0 }));
    }, [self!.profile_id, self!.name]);
    await page.goto(APP);
    await expect(page.getByTestId("home-headline")).toBeVisible();
    const r = await askAndReport(page, "How risky is my portfolio?", "own profile open");
    await page.getByTestId("answer-trace").getByRole("button").click().catch(() => {});
    await shot(page, "live-thread-portfolio");
    expect(r.state, r.banner ?? "").toBe("saved");
    expect(r.answerChars + r.widget).toBeGreaterThan(0);
  });

  test("TC-22 every screen against the real backend", async ({ page }) => {
    test.setTimeout(420_000);
    const pageErrors: string[] = [];
    page.on("pageerror", (e) => pageErrors.push(e.message));
    let failed: string[] = [];
    page.on("response", (res) => {
      const u = new URL(res.url());
      if (u.pathname.startsWith("/api/") && res.status() >= 400) failed.push(`${res.status()} ${res.request().method()} ${u.pathname}`);
    });
    const rows: string[] = [];
    for (const v of VIEWS) {
      failed = [];
      await page.goto(`${APP}/${v}`);
      const screen = page.getByTestId(`screen-${v.replace("/", "-")}`);
      await expect.soft(screen, `${v} did not render`).toBeVisible({ timeout: 20_000 });
      await page.waitForLoadState("networkidle", { timeout: 45_000 }).catch(() => {});
      await page.waitForTimeout(2500); // one retry cycle for failed queries
      const alerts = (await page.getByTestId("copilot-scroll").locator('[role="alert"]').allInnerTexts()).map((t) => t.replace(/\s+/g, " ").slice(0, 110));
      const crashed = await page.getByText(/^Copilot · /).count();
      rows.push(`LIVE-SCREEN ${JSON.stringify({ view: v, rendered: await screen.count(), crashed, notConnected: await page.getByTestId("copilot-scroll").getByText("Not connected yet").count(), loadingLeft: await page.getByTestId("copilot-scroll").locator('[role="status"]').count(), alerts, failedApi: [...new Set(failed)] })}`);
      expect.soft(crashed, `${v} crashed`).toBe(0);
      if (OUT) await page.screenshot({ path: path.join(OUT, `live-${v.replace("/", "-")}.png`) });
    }
    console.log(rows.join("\n"));
    expect.soft(pageErrors, "uncaught page errors").toEqual([]);
  });
});

/**
 * Replay of REAL staging answers through the UI.
 *
 * Staging rejects write requests from a page served at localhost (its
 * cross-site check), so a browser on this build cannot post a question to it.
 * Instead the question is asked with a plain HTTP client, the raw stream and
 * the saved messages are captured to REPLAY_DIR (<tag>.sse, <tag>.messages.json,
 * <tag>.meta.json), and this test feeds those exact bytes to the app. What the
 * screen shows is therefore the real backend's answer; only the transport is
 * replayed. Skipped unless REPLAY_DIR is set. The captures are not committed.
 */
const REPLAY_DIR = process.env.REPLAY_DIR;

test.describe("Copilot app — real staging answers replayed", () => {
  test.skip(!REPLAY_DIR, "set REPLAY_DIR to replay captured staging answers");
  test.use({ viewport: { width: 1440, height: 900 } });

  for (const tag of ["root", "own-profile"]) {
    test(`TC-22 replay · ${tag}`, async ({ page }) => {
      const dir = REPLAY_DIR as string;
      test.skip(!fs.existsSync(path.join(dir, `${tag}.sse`)), `no capture for ${tag}`);
      const sse = fs.readFileSync(path.join(dir, `${tag}.sse`), "utf-8");
      const saved = JSON.parse(fs.readFileSync(path.join(dir, `${tag}.messages.json`), "utf-8")) as Array<{ role: string; content: string }>;
      const meta = JSON.parse(fs.readFileSync(path.join(dir, `${tag}.meta.json`), "utf-8")) as { session_id: string; question: string };
      const frames = sse.split("\n\n").map((b) => b.trim()).filter((b) => b.startsWith("data:")).map((b) => JSON.parse(b.slice(5)) as Record<string, unknown>);
      const route = frames.find((f) => f.type === "route") as { agent?: string; confidence?: number } | undefined;
      const widget = frames.find((f) => f.type === "widget") as { widget_type?: string; freshness?: { source?: string[] } } | undefined;
      const done = frames.find((f) => f.type === "done") as { content?: string; follow_ups?: string[] } | undefined;

      const errors: string[] = [];
      page.on("pageerror", (e) => errors.push(e.message));
      const ok = (body: unknown) => ({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
      let streamed = false;
      await page.route(/\/\/[^/]+\/api\//, (r) => r.fulfill(ok({})));
      await page.route("**/api/auth/me", (r) => r.fulfill(ok({ user_id: "u_replay", email: "replay@example.test", name: "Replay User", is_admin: false, onboarding_completed: true })));
      await page.route("**/api/chat/sessions", (r) => r.fulfill(ok(r.request().method() === "POST" ? { session_id: meta.session_id } : [])));
      await page.route("**/api/chat/messages*", (r) => r.fulfill(ok(streamed ? saved : [])));
      await page.route("**/api/chat/stream", (r) => { streamed = true; return r.fulfill({ status: 200, contentType: "text/event-stream", body: sse }); });

      await page.goto(APP);
      await page.getByTestId("composer-input").fill(meta.question);
      await page.getByTestId("composer-input").press("Enter");
      const turn = page.getByTestId("thread-turn");
      await expect(turn).toHaveAttribute("data-state", "saved", { timeout: 20_000 });

      // The answer text is the backend's own, in full.
      const shown = (await page.getByTestId("answer-text").innerText()).replace(/\s+/g, " ").trim();
      expect(shown.length).toBeGreaterThan(Math.min(200, (done?.content ?? "").length / 2));
      if (route?.agent) await expect(page.getByTestId("answer-routed")).toContainText(`${Math.round((route.confidence ?? 0) * 100)}%`);
      await expect(page.getByTestId("answer-followups").getByRole("button")).toHaveCount((done?.follow_ups ?? []).slice(0, 3).length);
      // The result card the backend attached renders with the existing widget code, without crashing.
      await expect(page.getByTestId("answer-widget")).toHaveCount(widget ? 1 : 0);
      await expect(page.getByText(/^Copilot answer · /)).toHaveCount(0);
      // Evidence shows the source tags the answer carried.
      await page.getByTestId("evidence-tab-sources").click();
      await expect(page.getByTestId("evidence-source")).toHaveCount(widget?.freshness?.source?.length ?? 0);
      console.log(`REPLAY ${JSON.stringify({
        tag,
        classPill: (await page.getByTestId("answer-class").count()) ? await page.getByTestId("answer-class").innerText() : null,
        routed: (await page.getByTestId("answer-routed").count()) ? await page.getByTestId("answer-routed").innerText() : null,
        trace: await page.getByTestId("answer-trace-label").innerText(),
        widgetType: widget?.widget_type ?? null,
        widgetHeightPx: widget ? Math.round((await page.getByTestId("answer-widget").boundingBox())?.height ?? 0) : 0,
        answerCharsShown: shown.length,
        answerCharsSent: (done?.content ?? "").replace(/\s+/g, " ").trim().length,
        followUps: await page.getByTestId("answer-followups").getByRole("button").count(),
      })}`);
      if (OUT) {
        await page.screenshot({ path: path.join(OUT, `replay-${tag}.png`) });
        await page.getByTestId("copilot-scroll").evaluate((el) => el.scrollTo({ top: 0 }));
        await page.screenshot({ path: path.join(OUT, `replay-${tag}-top.png`) });
      }
      expect(errors).toEqual([]);
    });
  }
});
