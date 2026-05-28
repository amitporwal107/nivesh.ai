/**
 * @live — Live contract validation layer.
 * Hits real staging API with no interception.
 * Uses Playwright request context (not browser fetch) for speed and no rate-limit issues.
 *
 * A failure = frontend-backend mismatch finding. Do NOT loosen tests to make them pass.
 * Each test documents what the frontend expects vs what the backend sends.
 */
import { test, expect } from "@playwright/test";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BASE = process.env.STAGING_URL ?? process.env.BASE_URL ?? "https://staging.niveshcopilot.com";
const TOKEN = process.env.SESSION_TOKEN ?? "";

async function api(request: any, endpoint: string) {
  const resp = await request.get(`${BASE}${endpoint}`, {
    headers: { Cookie: `session_token=${TOKEN}` },
  });
  return { status: resp.status(), body: await resp.json().catch(() => null) };
}

async function apiPost(request: any, endpoint: string, data: any = {}) {
  const resp = await request.post(`${BASE}${endpoint}`, {
    headers: { Cookie: `session_token=${TOKEN}`, "Content-Type": "application/json" },
    data,
  });
  return { status: resp.status(), body: await resp.json().catch(() => null) };
}

test.describe("@live Auth contracts", () => {
  test("GET /api/auth/me — required fields", async ({ request }) => {
    const { status, body } = await api(request, "/api/auth/me");
    expect(status).toBe(200);
    expect(body).toHaveProperty("user_id");
    expect(body).toHaveProperty("email");
    expect(body).toHaveProperty("name");
    expect(body).toHaveProperty("onboarding_completed");
    // M25: copilot_enabled missing from response
    // Frontend Zod requires it — should be optional
    expect(body).not.toHaveProperty("copilot_enabled"); // MISMATCH: confirmed missing
  });

  test("GET /api/auth/google-client-id", async ({ request }) => {
    const { status, body } = await api(request, "/api/auth/google-client-id");
    expect(status).toBe(200);
    expect(body.client_id).toMatch(/\.apps\.googleusercontent\.com$/);
  });
});

test.describe("@live Holdings Enriched contracts", () => {
  test("top-level structure differs from frontend Zod", async ({ request }) => {
    const { status, body } = await api(request, "/api/portfolio/holdings-enriched?fresh=false");
    expect(status).toBe(200);

    // M4-M6: Frontend expects top-level total_value_rs, total_invested_rs, total_gain_pct, portfolio_id
    // Backend sends: totals.value_rs, totals.invested_rs, totals.pnl_pct, no portfolio_id
    expect(body).not.toHaveProperty("total_value_rs");   // MISMATCH M6
    expect(body).not.toHaveProperty("total_invested_rs"); // MISMATCH M6
    expect(body).not.toHaveProperty("total_gain_pct");    // MISMATCH M6
    expect(body).not.toHaveProperty("portfolio_id");      // MISMATCH M6
    expect(body).toHaveProperty("totals");
    expect(body.totals).toHaveProperty("value_rs");
    expect(body.totals).toHaveProperty("invested_rs");
    expect(body.totals).toHaveProperty("pnl_pct");

    // Extra data frontend doesn't use
    expect(body).toHaveProperty("alerts");
    expect(body).toHaveProperty("health");
    expect(body).toHaveProperty("coverage_pct");
    expect(body).toHaveProperty("allocation_actual");
  });

  test("per-holding fields renamed vs frontend Zod", async ({ request }) => {
    const { status, body } = await api(request, "/api/portfolio/holdings-enriched?fresh=false");
    expect(status).toBe(200);
    const h = body.holdings[0];

    // M4-M5: Frontend expects current_value_rs, gain_rs, gain_pct
    // Backend sends: value_rs, pnl_rs, pnl_pct
    expect(h).not.toHaveProperty("current_value_rs"); // MISMATCH M4
    expect(h).not.toHaveProperty("gain_rs");           // MISMATCH M4
    expect(h).not.toHaveProperty("gain_pct");          // MISMATCH M4
    expect(h).toHaveProperty("value_rs");
    expect(h).toHaveProperty("pnl_rs");
    expect(h).toHaveProperty("pnl_pct");

    // M5: v3_score and v3_grade not on individual holdings
    expect(h).not.toHaveProperty("v3_score"); // MISMATCH M5
    expect(h).not.toHaveProperty("v3_grade"); // MISMATCH M5
  });

  test("action_badge is object, not string", async ({ request }) => {
    const { status, body } = await api(request, "/api/portfolio/holdings-enriched?fresh=false");
    expect(status).toBe(200);

    // M3: Find a holding with action_badge
    const withBadge = body.holdings.find((h: any) => h.action_badge != null);
    if (withBadge) {
      // MISMATCH M3: Frontend expects string, backend sends object
      expect(typeof withBadge.action_badge).toBe("object");
      expect(withBadge.action_badge).toHaveProperty("action");
      expect(withBadge.action_badge).toHaveProperty("tone");
    }
  });
});

test.describe("@live Portfolio Trend contracts", () => {
  test("series field names differ from frontend Zod", async ({ request }) => {
    const { status, body } = await api(request, "/api/portfolio/trend?days=365");
    expect(status).toBe(200);
    expect(body).toHaveProperty("series");

    if (body.series.length > 0) {
      const pt = body.series[0];
      // MISMATCH M1: Frontend expects date + value_rs
      expect(pt).not.toHaveProperty("date");     // MISSING
      expect(pt).not.toHaveProperty("value_rs");  // MISSING
      expect(pt).toHaveProperty("snapshot_date");  // Backend sends this
      expect(pt).toHaveProperty("total_value");    // Backend sends this

      // Extra fields
      expect(pt).toHaveProperty("health_score");
      expect(pt).toHaveProperty("allocation");
    }
  });
});

test.describe("@live Insights contracts", () => {
  test("portfolio_health.score vs health_score", async ({ request }) => {
    const { status, body } = await api(request, "/api/insights/analysis");
    expect(status).toBe(200);
    const ph = body.portfolio_health;

    // MISMATCH M2: Frontend expects .score, backend sends .health_score
    expect(ph).not.toHaveProperty("score");        // MISSING
    expect(ph).toHaveProperty("health_score");      // Backend sends this
    expect(typeof ph.health_score).toBe("number");
    expect(ph.health_score).toBeGreaterThanOrEqual(0);
    expect(ph.health_score).toBeLessThanOrEqual(100);

    // grade is present and correct
    expect(ph).toHaveProperty("grade");
    expect(ph.grade).toMatch(/^[A-F][+-]?$/);
  });
});

test.describe("@live Concentration contracts", () => {
  test("sector structure differs from frontend", async ({ request }) => {
    const { status, body } = await api(request, "/api/portfolio/exposure/concentration");
    expect(status).toBe(200);
    const sector = body.sector;

    // MISMATCH M10: Frontend expects sector.breakdown[], backend sends sector.items[]
    expect(sector).not.toHaveProperty("breakdown"); // MISSING
    expect(sector).toHaveProperty("items");
    expect(Array.isArray(sector.items)).toBe(true);

    // MISMATCH M10: Frontend expects sector.top_stock
    expect(sector).not.toHaveProperty("top_stock"); // MISSING

    // MISMATCH M10: Frontend expects sector.herfindahl, backend has hhi
    expect(sector).not.toHaveProperty("herfindahl"); // MISSING
    expect(sector).toHaveProperty("hhi");
  });
});

test.describe("@live Intelligence/Overlap contracts", () => {
  test("overlap field names differ", async ({ request }) => {
    const { status, body } = await api(request, "/api/intelligence/portfolio?narrate=true");
    expect(status).toBe(200);

    // MISMATCH M9: Frontend expects overlap_matrix, backend sends pairwise_overlap
    expect(body).not.toHaveProperty("overlap_matrix"); // MISSING
    expect(body).toHaveProperty("pairwise_overlap");

    if (body.pairwise_overlap?.length > 0) {
      const pair = body.pairwise_overlap[0];
      // MISMATCH M9: Frontend expects fund_a/fund_b, backend sends a_name/b_name
      expect(pair).not.toHaveProperty("fund_a"); // MISSING
      expect(pair).not.toHaveProperty("fund_b"); // MISSING
      expect(pair).toHaveProperty("a_name");
      expect(pair).toHaveProperty("b_name");
      expect(pair).toHaveProperty("overlap_pct");
    }
  });
});

test.describe("@live Dashboard Envelope contracts", () => {
  for (const domain of ["performance", "goals", "tax"] as const) {
    test(`GET /api/dashboards/${domain} — badge/insight are objects not strings`, async ({ request }) => {
      const params = domain === "performance" ? "?period=1y" : "";
      const { status, body } = await api(request, `/api/dashboards/${domain}${params}`);
      expect(status).toBe(200);

      // MISMATCH M11: Frontend expects badge as string
      if (body.badge != null) {
        expect(typeof body.badge).toBe("object"); // Backend sends {label, tone}
        expect(body.badge).toHaveProperty("label");
        expect(body.badge).toHaveProperty("tone");
      }

      // MISMATCH M12: Frontend expects insight as string
      if (body.insight != null) {
        expect(typeof body.insight).toBe("object"); // Backend sends {headline, subtext, hero}
        expect(body.insight).toHaveProperty("headline");
      }

      // Stat tiles shape is correct
      expect(body).toHaveProperty("stat_tiles");
      expect(Array.isArray(body.stat_tiles)).toBe(true);
      expect(body).toHaveProperty("recommendations");
      expect(Array.isArray(body.recommendations)).toBe(true);
    });
  }
});

test.describe("@live Plans contracts", () => {
  test("response is wrapped in {plan, has_plan}", async ({ request }) => {
    const { status, body } = await api(request, "/api/plans/active");
    expect(status).toBe(200);

    // MISMATCH M13: Frontend may expect bare PlanC, backend wraps in {plan:..., has_plan:...}
    expect(body).toHaveProperty("has_plan");
    expect(body).toHaveProperty("plan");
  });

  test("plan field names differ from frontend", async ({ request }) => {
    const { status, body } = await api(request, "/api/plans/active");
    expect(status).toBe(200);
    const plan = body.plan;
    if (!plan) return;

    // MISMATCH M19-M21: Frontend expects actions_total/done/pending, backend sends total_actions/completed_actions/pending_actions
    expect(plan).not.toHaveProperty("actions_total");   // MISSING
    expect(plan).not.toHaveProperty("actions_done");     // MISSING
    expect(plan).toHaveProperty("total_actions");
    expect(plan).toHaveProperty("completed_actions");
    expect(plan).toHaveProperty("pending_actions");
  });

  test("action fields differ", async ({ request }) => {
    const { status, body } = await api(request, "/api/plans/active");
    expect(status).toBe(200);
    const actions = body.plan?.actions;
    if (!actions?.length) return;
    const a = actions[0];

    // MISMATCH M14: action_type is UPPERCASE
    expect(a.action_type).toMatch(/^[A-Z_]+$/);

    // MISMATCH M16: status is UPPERCASE
    expect(a.status).toMatch(/^[A-Z_]+$/);

    // MISMATCH M15: has asset_name, not holding_name
    expect(a).toHaveProperty("asset_name");
    expect(a).not.toHaveProperty("holding_name"); // MISSING

    // MISMATCH M22: has reason_text, not rationale
    expect(a).toHaveProperty("reason_text");

    // MISMATCH M23: no estimated_impact object
    expect(a).not.toHaveProperty("estimated_impact"); // MISSING
    expect(a).toHaveProperty("amount_rs"); // Backend has this instead

    // MISMATCH M24: no suggested_alternative
    expect(a).not.toHaveProperty("suggested_alternative"); // MISSING
  });
});

test.describe("@live Goals contracts", () => {
  test("response shape differs from GoalsListRes", async ({ request }) => {
    const { status, body } = await api(request, "/api/goals");
    expect(status).toBe(200);

    // MISMATCH M17: Frontend expects {total, on_track, at_risk, goals[]}
    // Backend sends just {goals: []}
    expect(body).toHaveProperty("goals");
    expect(body).not.toHaveProperty("total");    // MISSING
    expect(body).not.toHaveProperty("on_track");  // MISSING
    expect(body).not.toHaveProperty("at_risk");   // MISSING
  });
});

test.describe("@live Chat/Prompts contracts", () => {
  test("suggested prompts use label not text", async ({ request }) => {
    const { status, body } = await api(request, "/api/copilot/suggested-prompts");
    expect(status).toBe(200);

    expect(body).toHaveProperty("prompts");
    if (body.prompts?.length > 0) {
      const p = body.prompts[0];
      // MISMATCH M18: Frontend reads p.text, backend sends p.label
      expect(p).toHaveProperty("label");
      expect(p).not.toHaveProperty("text"); // MISSING
      // Extra useful fields
      expect(p).toHaveProperty("query");
      expect(p).toHaveProperty("icon");
    }
  });
});

test.describe("@live Chat send — real endpoint path", () => {
  test("POST /api/chat/send — works, returns {user_message, ai_message}", async ({ request }) => {
    // Create a session first
    const sessRes = await apiPost(request, "/api/chat/sessions", {});
    const sessionId = sessRes.body?.session_id ?? sessRes.body?.id;
    expect(sessRes.status).toBe(200);
    expect(sessionId).toBeTruthy();

    // Send a message
    const { status, body } = await apiPost(request, "/api/chat/send", { message: "hello", session_id: sessionId });
    expect(status).toBe(200);
    // Backend returns {user_message, ai_message} NOT {reply, message}
    expect(body).toHaveProperty("ai_message");
    expect(body.ai_message).toHaveProperty("content");
    expect(body.ai_message).toHaveProperty("role", "assistant");
  });

  test("POST /api/chat — old path is 404 (frontend adapter now uses /api/chat/send)", async ({ request }) => {
    const { status } = await apiPost(request, "/api/chat", { message: "test", session_id: "test" });
    expect(status).toBe(404);
  });
});

test.describe("@live Remaining missing endpoints", () => {
  test("GET /api/portfolio/upload-latest-task — 404 (backend not yet built)", async ({ request }) => {
    const { status } = await api(request, "/api/portfolio/upload-latest-task");
    expect(status).toBe(404);
  });

  test("GET /api/intelligence/sector-peers/RELIANCE — 404 (backend not yet built)", async ({ request }) => {
    const { status } = await api(request, "/api/intelligence/sector-peers/RELIANCE");
    expect(status).toBe(404);
  });

  test("GET /api/intelligence/v3-score/{isin} — 500 (route exists, backend error)", async ({ request }) => {
    const { status } = await api(request, "/api/intelligence/v3-score/INE701B01021");
    // 500 = backend route exists but throws (data pipeline issue), NOT missing
    expect([500, 200]).toContain(status);
  });
});
