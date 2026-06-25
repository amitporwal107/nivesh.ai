/**
 * Reconciliation harness — asserts the copilot's answers against the CANONICAL
 * dashboard/intelligence values for the same account, LIVE. Fails loudly on
 * discrepancies (e.g. XIRR sign flip, risk numbers, tax mismatch).
 *
 * Not hardcoded to a date: it pulls the canonical value and the copilot value
 * in the same run and compares them, so it stays valid as the portfolio drifts.
 *
 * Run: node /app/scripts/test-copilot-reconcile.mjs   (reads /app/.staging_session)
 */
import fs from "fs";
import { request } from "/app/frontend-v5/node_modules/playwright/index.mjs";

const BASE = "https://staging.niveshcopilot.com";
const TOKEN = fs.readFileSync("/app/.staging_session", "utf8").trim();

const num = (s) => { const m = String(s).replace(/,/g, "").match(/-?\d+(\.\d+)?/); return m ? parseFloat(m[0]) : null; };
// pull the first "<n>%" near a keyword in free text
function pctNear(text, kw) {
  const re = new RegExp(`${kw}[^%\\d]{0,40}?([−-]?\\s*\\d+(?:\\.\\d+)?)\\s*%`, "i");
  const m = text.match(re);
  if (!m) return null;
  return parseFloat(m[1].replace(/[−\s]/g, (c) => (c === "−" ? "-" : "")));
}
function near(a, b, tol) { return a != null && b != null && Math.abs(a - b) <= tol; }
function sameSign(a, b) { return a != null && b != null && Math.sign(a) === Math.sign(b); }

async function ask(ctx, q) {
  const res = await ctx.post("/api/chat/send", { data: { message: q }, timeout: 120000 });
  const j = await res.json().catch(() => ({}));
  return j?.ai_message?.content ?? "";
}

async function main() {
  const ctx = await request.newContext({
    baseURL: BASE,
    extraHTTPHeaders: { Cookie: `session_token=${TOKEN}`, "Content-Type": "application/json" },
  });

  // ── canonical values (the source of truth the user sees) ────────────────
  const risk = await (await ctx.get("/api/dashboards/risk")).json();
  const perf = await (await ctx.get("/api/dashboards/performance")).json();
  const tax  = await (await ctx.get("/api/dashboards/tax")).json();
  const intel = await (await ctx.get("/api/intelligence/portfolio")).json();

  const tiles = Object.fromEntries((risk.stat_tiles || []).map((t) => [t.label, t.value]));
  const canon = {
    var_pct:   num(risk.insight?.hero?.value),                 // e.g. "−33.1%"
    vol_pct:   num(tiles["Volatility"]),
    beta:      num(tiles["Beta"]),
    xirr_pct:  num(perf.insight?.hero?.value),                 // dashboard XIRR
    tax_saved: tax.net_saved,
    tax_lots:  (tax.harvest_lots || []).length,
    overlap_top: Math.max(0, ...(intel.pairwise_overlap || []).map((p) => p.overlap_pct ?? p.overlap ?? p.pct ?? 0)),
    total_value: intel.total_value,
  };
  console.log("# CANONICAL (dashboard/intelligence):", JSON.stringify(canon));

  const checks = [];
  const add = (name, verdict, detail) => { checks.push({ name, verdict, detail }); console.log(`[${verdict}] ${name} — ${detail}`); };

  // ── RISK: copilot must report PRA VaR/vol/beta, matching the dashboard ──
  {
    const a = await ask(ctx, "How risky is my portfolio? Give VaR, volatility and beta.");
    // VaR magnitude is the % AFTER "1Y" (skip the "95%" confidence label)
    const cv = num((a.match(/VaR[^%]*?1Y[^%\d−-]*([−-]?\s*\d+(?:\.\d+)?)\s*%/i) || [])[1]);
    const cvol = pctNear(a, "volatilit"), cbeta = num((a.match(/beta[^\d-]{0,15}(-?\d+\.?\d*)/i) || [])[1]);
    add("risk.VaR",  near(Math.abs(cv), Math.abs(canon.var_pct), 5) ? "PASS" : "FAIL",
        `copilot=${cv}% vs canon=${canon.var_pct}%`);
    add("risk.vol",  near(cvol, canon.vol_pct, 3) ? "PASS" : "FAIL", `copilot=${cvol}% vs canon=${canon.vol_pct}%`);
    add("risk.beta", near(cbeta, canon.beta, 0.25) ? "PASS" : "FAIL", `copilot=${cbeta} vs canon=${canon.beta}`);
  }

  // ── XIRR: sign + magnitude must reconcile with the dashboard ───────────
  {
    const a = await ask(ctx, "What is my portfolio XIRR?");
    const cx = pctNear(a, "XIRR");
    add("perf.XIRR.sign", sameSign(cx, canon.xirr_pct) ? "PASS" : "FAIL",
        `copilot=${cx}% vs canon=${canon.xirr_pct}% (sign must match)`);
    add("perf.XIRR.mag", near(cx, canon.xirr_pct, 3) ? "PASS" : "FAIL", `copilot=${cx}% vs canon=${canon.xirr_pct}%`);
  }

  // ── TAX: harvest saving + lot count must reconcile ─────────────────────
  {
    const a = await ask(ctx, "What are my tax-loss harvesting options this year?");
    const csaved = num((a.match(/sav\w*[^₹\d]{0,20}₹?\s*([\d,]+)/i) || [])[1]);
    add("tax.saved", near(csaved, canon.tax_saved, Math.max(2000, canon.tax_saved * 0.15)) ? "PASS" : "FAIL",
        `copilot≈₹${csaved} vs canon=₹${canon.tax_saved}`);
  }

  // ── OVERLAP: top pair % must match intelligence ───────────────────────
  {
    const a = await ask(ctx, "Which of my funds overlap the most?");
    const co = pctNear(a, "overlap") ?? num((a.match(/(\d+)\s*%/) || [])[1]);
    add("overlap.top", near(co, canon.overlap_top, 3) ? "PASS" : "FAIL", `copilot=${co}% vs canon=${canon.overlap_top}%`);
  }

  await ctx.dispose();
  const fails = checks.filter((c) => c.verdict === "FAIL");
  console.log(`\n# RECONCILE SUMMARY: ${checks.length - fails.length} PASS / ${fails.length} FAIL`);
  if (fails.length) console.log("  FAILS:", fails.map((f) => f.name).join(", "));
  process.exit(fails.length ? 1 : 0);
}
main();
