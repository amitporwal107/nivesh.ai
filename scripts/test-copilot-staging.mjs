/**
 * End-to-end copilot chat test against REAL staging.
 * Reads session token from /app/.staging_session, exercises every agent route
 * via POST /api/chat/send (breadth) + one query through the V5 UI (rendering).
 *
 * Run: node /app/scripts/test-copilot-staging.mjs
 * (uses the playwright install under frontend-v5/node_modules)
 */
import fs from "fs";
import { chromium, request } from "/app/frontend-v5/node_modules/playwright/index.mjs";

const BASE = "https://staging.niveshcopilot.com";
const TOKEN = fs.readFileSync("/app/.staging_session", "utf8").trim();

// One query per specialist agent + the exact one that was failing.
const QUERIES = [
  ["mf_analyst",        "Do I have too many mutual funds?"],
  ["portfolio_analyst", "What is my portfolio XIRR and asset allocation?"],
  ["risk_analyst",      "How risky is my portfolio right now?"],
  ["goal_planner",      "How much SIP do I need to retire with 2 crore?"],
  ["stock_analyst",     "Give me a technical and fundamental view on RELIANCE"],
  ["market_analyst",    "How is the Indian market doing today?"],
  ["recommendation",    "What should I buy or sell to improve my portfolio?"],
  ["tax",               "What are my tax-loss harvesting options this year?"],
  ["mf_followup",       "Which of my funds overlap the most?"],
];

const FAIL_SIGNATURES = [
  "trouble connecting to my AI engine",
  "couldn't retrieve the data needed",
  "could not retrieve the data needed",
];

function classify(content) {
  if (!content || !content.trim()) return ["EMPTY", "blank response"];
  for (const s of FAIL_SIGNATURES) if (content.toLowerCase().includes(s.toLowerCase())) return ["FAIL", s];
  return ["PASS", ""];
}

async function main() {
  console.log(`# Copilot E2E vs ${BASE}  (token len ${TOKEN.length})\n`);

  // ── A. API breadth across every agent route ────────────────────────────
  const ctx = await request.newContext({
    baseURL: BASE,
    extraHTTPHeaders: { Cookie: `session_token=${TOKEN}`, "Content-Type": "application/json" },
  });

  // sanity: who am I / is auth valid
  const me = await ctx.get("/api/auth/me");
  console.log(`auth/me -> ${me.status()} ${me.ok() ? "(session valid)" : "(SESSION INVALID — aborting)"}\n`);
  if (!me.ok()) { await ctx.dispose(); process.exit(1); }

  let pass = 0, fail = 0;
  const rows = [];
  for (const [agent, q] of QUERIES) {
    const t0 = Date.now();
    let status = 0, content = "", route = "";
    try {
      const res = await ctx.post("/api/chat/send", { data: { message: q }, timeout: 120000 });
      status = res.status();
      const j = await res.json().catch(() => ({}));
      content = j?.ai_message?.content ?? "";
      route = j?.ai_message?.agent_used ?? j?.agent ?? "";
    } catch (e) { content = `EXC: ${e.message}`; }
    const dt = ((Date.now() - t0) / 1000).toFixed(1);
    let [verdict, why] = classify(content);
    // The V5 client aborts /chat/send at 15s (apiConfig.requestTimeoutMs). A
    // response that arrives later is a real timeout for users even if curl
    // (120s) eventually got 200 — count it as a failure so the harness stops
    // masking latency.
    const CLIENT_BUDGET_S = 15;
    if (verdict === "PASS" && Number(dt) > CLIENT_BUDGET_S) { verdict = "SLOW"; why = `>${CLIENT_BUDGET_S}s client budget`; }
    if (verdict === "PASS") pass++; else fail++;
    rows.push({ agent, verdict, status, dt, why, preview: content.slice(0, 110).replace(/\n/g, " ") });
    console.log(`[${verdict}] ${agent.padEnd(18)} ${String(status).padEnd(4)} ${dt}s  ${why || ""}`);
    console.log(`        Q: ${q}`);
    console.log(`        A: ${content.slice(0, 180).replace(/\n/g, " ")}${content.length > 180 ? "…" : ""}\n`);
  }
  await ctx.dispose();

  // ── B. UI rendering test (the c0dae48 fix) ─────────────────────────────
  console.log("# UI render test (V5 /v5/chat) …");
  let uiVerdict = "SKIP";
  try {
    const browser = await chromium.launch();
    const page = await browser.newPage();
    await page.context().addCookies([{ name: "session_token", value: TOKEN, domain: "staging.niveshcopilot.com", path: "/" }]);
    await page.goto(`${BASE}/v5/chat`, { waitUntil: "domcontentloaded", timeout: 60000 });
    await page.waitForTimeout(2500);
    const input = page.locator("input[type='text'], textarea").first();
    if (await input.count()) {
      await input.fill("Do I have too many mutual funds?");
      const sendBtn = page.locator("button", { hasText: "Send" }).first();
      await sendBtn.click();
      // wait up to 90s for an assistant bubble that isn't the error
      await page.waitForTimeout(2000);
      let rendered = "";
      for (let i = 0; i < 45; i++) {
        const body = await page.locator("body").innerText().catch(() => "");
        if (/too many|funds|overlap|portfolio|score|crore|₹/i.test(body) && !/Ask anything about your portfolio\.?\s*$/.test(body)) { rendered = body; break; }
        await page.waitForTimeout(2000);
      }
      const errVisible = /trouble connecting|couldn'?t retrieve/i.test(rendered);
      uiVerdict = rendered && !errVisible ? "PASS" : (errVisible ? "FAIL(error rendered)" : "FAIL(no reply rendered)");
      await page.screenshot({ path: "/app/scripts/copilot-ui.png", fullPage: true });
      console.log(`  UI verdict: ${uiVerdict}  (screenshot: /app/scripts/copilot-ui.png)`);
    } else {
      uiVerdict = "FAIL(no input found — blank page?)";
      console.log("  " + uiVerdict);
    }
    await browser.close();
  } catch (e) { console.log("  UI test error:", e.message); }

  console.log(`\n# SUMMARY: API ${pass} PASS / ${fail} FAIL of ${QUERIES.length} · UI ${uiVerdict}`);
  process.exit(fail === 0 && uiVerdict === "PASS" ? 0 : 1);
}
main();
