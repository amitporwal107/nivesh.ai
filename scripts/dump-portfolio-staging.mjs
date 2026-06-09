/**
 * Pull the LIVE portfolio for the logged-in user from staging, so we can write
 * test cases with concrete expected values. Reads session token from
 * /app/.staging_session. Read-only GETs + a few copilot questions.
 *
 * Run: node /app/scripts/dump-portfolio-staging.mjs
 */
import fs from "fs";
import { request } from "/app/frontend-v5/node_modules/playwright/index.mjs";

const BASE = "https://staging.niveshcopilot.com";
const TOKEN = fs.readFileSync("/app/.staging_session", "utf8").trim();

const GETS = [
  "/api/auth/me",
  "/api/portfolio/holdings",
  "/api/portfolio/holdings-enriched",
  "/api/insights/analysis",
  "/api/portfolio/exposure/concentration",
  "/api/intelligence/portfolio",
  "/api/dashboards/performance",
  "/api/dashboards/tax",
  "/api/dashboards/risk",
  "/api/dashboards/goals",
  "/api/goals",
];

function brief(v, depth = 0) {
  if (v == null) return String(v);
  if (Array.isArray(v)) return `[${v.length}]`;
  if (typeof v === "object") return `{${Object.keys(v).slice(0, 12).join(",")}}`;
  return String(v).slice(0, 60);
}

async function main() {
  const ctx = await request.newContext({
    baseURL: BASE,
    extraHTTPHeaders: { Cookie: `session_token=${TOKEN}`, "Content-Type": "application/json" },
  });

  for (const path of GETS) {
    try {
      const res = await ctx.get(path, { timeout: 60000 });
      const j = await res.json().catch(() => null);
      console.log(`\n===== GET ${path}  [${res.status()}] =====`);
      if (j == null) { console.log("  (non-json)"); continue; }
      if (Array.isArray(j)) {
        console.log(`  array length=${j.length}`);
        console.log("  sample[0]:", JSON.stringify(j[0])?.slice(0, 600));
        // if it looks like holdings, list names+values
        if (j[0] && (j[0].scheme_name || j[0].name || j[0].fund_name || j[0].symbol)) {
          console.log("  --- items ---");
          for (const h of j.slice(0, 60)) {
            const name = h.scheme_name || h.fund_name || h.name || h.symbol || "?";
            const val = h.current_value ?? h.value ?? h.market_value ?? h.amount ?? "";
            const typ = h.asset_type || h.type || h.category || "";
            console.log(`    ${String(name).slice(0,48).padEnd(48)} ${String(typ).slice(0,16).padEnd(16)} ${val}`);
          }
        }
      } else {
        // object — print top-level keys with brief values, and dump small ones fully
        for (const [k, val] of Object.entries(j)) {
          console.log(`  ${k}: ${brief(val)}`);
        }
        console.log("  RAW(1.5k):", JSON.stringify(j).slice(0, 1500));
      }
    } catch (e) {
      console.log(`\n===== GET ${path}  ERROR: ${e.message}`);
    }
  }
  await ctx.dispose();
}
main();
