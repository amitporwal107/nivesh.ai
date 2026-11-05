/**
 * Route mocks for the desk app's Playwright specs.
 *
 * // MOCK — not real data. Every body below copies the shape of the real desk API (backend/autodesk/routers/api.py,
 * // rows of the autodesk.* tables) and of the main app's /api/auth/me and /api/live/quotes. Figures are taken from the
 * // Phase 1 real-data run on 5 Nov 2026 (test_reports/autodesk_phase1_20261105_1255.md) so they look like what the
 * // API returns, but they are fixtures and are never shown to a user.
 *
 * Usage:
 *   const desk = await mockDesk(page, { routes: { "GET /signals": [] } });
 *   await page.goto("/autodesk/scanner");
 *   ...
 *   expect(desk.posts).toEqual([...]);       // request bodies the UI sent
 *   expect(desk.unmatched).toEqual([]);      // the UI called nothing we did not expect
 *
 * Route keys are "METHOD /path" under /autodesk/api/v1 (":name" matches one segment), or "METHOD /api/..." for the
 * main app. A value is a body (200), a { status, body } (use reply()), or a handler (req, state) => reply.
 * Defaults cover the shell; a spec overrides what its screen reads. The controls and accounts defaults are stateful:
 * a POST changes what the next GET returns, as the real API does.
 */
import { expect, type Page, type Request } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

export const NOW = "2026-11-05T06:12:30.000Z"; // 11:42:30 IST
export const TENANT = "user_7f3a9c";

export interface Reply { __reply: true; status: number; body: unknown }
export const reply = (status: number, body: unknown): Reply => ({ __reply: true, status, body });

export interface Req { method: string; path: string; query: URLSearchParams; body: unknown; params: Record<string, string> }
export type Handler = (req: Req, state: MockState) => unknown;
export type RouteValue = Handler | Reply | Record<string, unknown> | unknown[] | string | number | boolean | null;

export interface Captured { method: string; path: string; body: unknown }

export interface MockState {
  controls: Record<string, unknown>[];
  accounts: Record<string, unknown>[];
  [k: string]: unknown;
}

// ── default bodies ───────────────────────────────────────────────────────────────────────────────────────────────────

export const ACCOUNT_A = {
  account_id: "ACC-01JBX3K2M4N5P6Q7R8S9T0V1W2", tenant_id: TENANT, name: "Desk A", kind: "PAPER",
  operating_mode: "AUTONOMOUS_PAPER", starting_capital_rs: "10000000.00", currency: "INR", simulation_id: null,
  policy_id: "POL-01JBX3K2M4N5P6Q7R8S9T0V1W3", status: "ACTIVE", created_by: TENANT,
  created_at: "2026-11-05T05:20:11.120Z", updated_at: "2026-11-05T05:20:11.120Z",
};

export const AGENTS_STATUS = [
  { agent_key: "TECH_SUPPORT", version: "autodesk-ts-v1", kind: "DETERMINISTIC", status: "IDLE", last_heartbeat: "2026-11-05T05:31:02.410Z" },
  { agent_key: "AI_TRADER", version: "autodesk-ait-v1", kind: "DETERMINISTIC", status: "IDLE", last_heartbeat: "2026-11-05T05:31:09.870Z" },
  { agent_key: "TRADING_ASSISTANT", version: "autodesk-ta-v1", kind: "DETERMINISTIC", status: "IDLE", last_heartbeat: "2026-11-05T05:31:11.020Z" },
  { agent_key: "RISK_OPS", version: "autodesk-risk-v1", kind: "DETERMINISTIC", status: "IDLE", last_heartbeat: "2026-11-05T05:31:11.310Z" },
  { agent_key: "MIDDLE_OFFICE", version: "autodesk-mo-v1", kind: "DETERMINISTIC", status: "IDLE", last_heartbeat: "2026-11-05T05:31:11.540Z" },
];

export function deskStatus(state: MockState, over: Record<string, unknown> = {}) {
  return {
    as_of: NOW,
    accounts: state.accounts.map((a) => ({
      account_id: a.account_id, name: a.name, kind: a.kind, operating_mode: a.operating_mode, status: a.status, starting_capital_rs: a.starting_capital_rs,
    })),
    agents: AGENTS_STATUS,
    pending_approvals: 0,
    open_workflows: 0,
    controls: state.controls,
    last_premarket: {
      session_date: "2026-11-05",
      outcome: { premarket: { status: "READY", session_date: "2026-11-05", checks: [{ name: "cash_eod", status: "READY", detail: "2187 cash rows for 2026-11-04 (need 500)", as_of: "2026-11-04" }], data_as_of: "2026-11-04", allowed_segments: ["CASH", "FUTURES", "OPTIONS"] } },
    },
    market_data: { latest_cash_session: "2026-11-04", latest_fno_session: "2026-11-04" },
    execution: "none (Phase 1: no orders, fills or positions)",
    ...over,
  };
}

export const ME = { user_id: TENANT, email: "amit.p@example.com", name: "Amit P", role: "user" };

export const LIVE_OPEN = {
  as_of: NOW, data_at: "2026-11-05T06:12:28.000Z", age_seconds: 2, stale: false, stale_after_seconds: 75, cadence_seconds: 30,
  mode: "live", session: "open", source: "kite", final: false, count: 3, missing: [],
  quotes: {
    "NIFTY 50": { ltp: 24012.35, change: 52.7, change_pct: 0.22, open: 23970.1, high: 24051.4, low: 23948.25, close: 23959.65, volume: null, oi: null, ts: "2026-11-05T06:12:28.000Z" },
    "NIFTY BANK": { ltp: 55742.6, change: 189.05, change_pct: 0.34, open: 55601.2, high: 55810.0, low: 55540.3, close: 55553.55, volume: null, oi: null, ts: "2026-11-05T06:12:28.000Z" },
    "INDIA VIX": { ltp: 12.84, change: -0.28, change_pct: -2.13, open: 13.1, high: 13.2, low: 12.8, close: 13.12, volume: null, oi: null, ts: "2026-11-05T06:12:28.000Z" },
  },
  note: "Prices are null/absent when Kite gave none.", read_only: true,
};

export function defaultState(): MockState {
  return { controls: [], accounts: [{ ...ACCOUNT_A }] };
}

const DEFAULTS: Record<string, RouteValue> = {
  "GET /desk/status": (_r: Req, s: MockState) => deskStatus(s),
  "GET /accounts": (_r: Req, s: MockState) => s.accounts,
  "POST /accounts": (r: Req, s: MockState) => {
    const b = r.body as Record<string, unknown>;
    const a = { ...ACCOUNT_A, account_id: `ACC-NEW${s.accounts.length}`, name: b.name, operating_mode: b.operating_mode ?? "RESEARCH", starting_capital_rs: Number(b.starting_capital_rs ?? 1000000).toFixed(2), policy_id: null };
    s.accounts.push(a);
    return reply(201, a);
  },
  "GET /desk/controls": (_r: Req, s: MockState) => s.controls,
  "POST /desk/controls/:control": (r: Req, s: MockState) => {
    const b = r.body as { active: boolean; reason: string };
    const row = { tenant_id: TENANT, control: r.params.control, active: b.active, reason: b.reason, changed_by: TENANT, changed_at: NOW };
    s.controls = b.active ? [row] : [];
    return row;
  },
  "GET /approvals": [],
  "GET /agents/:agent_key/activity": [],
  "GET /api/auth/me": ME,
  "GET /api/live/quotes": LIVE_OPEN,
};

// ── the router ─────────────────────────────────────────────────────────────────────────────────────────────────────

function match(pattern: string, method: string, p: string): Record<string, string> | null {
  const [pm, pp] = pattern.split(" ");
  if (pm !== method) return null;
  const a = pp.split("/").filter(Boolean);
  const b = p.split("/").filter(Boolean);
  if (a.length !== b.length) return null;
  const params: Record<string, string> = {};
  for (let i = 0; i < a.length; i++) {
    if (a[i].startsWith(":")) params[a[i].slice(1)] = decodeURIComponent(b[i]);
    else if (a[i] !== b[i]) return null;
  }
  return params;
}

export interface DeskMock {
  posts: Captured[];
  requests: Captured[];
  unmatched: string[];
  state: MockState;
}

export async function mockDesk(page: Page, opts: { routes?: Record<string, RouteValue>; state?: Partial<MockState> } = {}): Promise<DeskMock> {
  const state: MockState = { ...defaultState(), ...(opts.state ?? {}) } as MockState;
  const routes: Record<string, RouteValue> = { ...DEFAULTS, ...(opts.routes ?? {}) };
  const mock: DeskMock = { posts: [], requests: [], unmatched: [], state };

  // Web fonts are not part of what is tested (the runner has no network).
  await page.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());

  const handle = async (route: import("@playwright/test").Route, request: Request, apiPath: string) => {
    const url = new URL(request.url());
    const method = request.method();
    let body: unknown = null;
    const raw = request.postData();
    if (raw) { try { body = JSON.parse(raw); } catch { body = raw; } }
    const rec = { method, path: apiPath + url.search, body };
    mock.requests.push(rec);
    if (method !== "GET") mock.posts.push({ method, path: apiPath, body });
    const keys = Object.keys(routes).sort((x, y) => (x.includes(":") ? 1 : 0) - (y.includes(":") ? 1 : 0));
    for (const k of keys) {
      const params = match(k, method, apiPath);
      if (!params) continue;
      let v = routes[k];
      if (typeof v === "function") v = (v as Handler)({ method, path: apiPath, query: url.searchParams, body, params }, state);
      const r = v && typeof v === "object" && (v as Reply).__reply ? (v as Reply) : { status: 200, body: v };
      return route.fulfill({ status: r.status, contentType: "application/json", body: JSON.stringify(r.body) });
    }
    mock.unmatched.push(`${method} ${apiPath}`);
    return route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ error: "NOT_FOUND", message: `no mock for ${method} ${apiPath}` }) });
  };

  await page.route("**/autodesk/api/v1/**", (route, request) => {
    const p = new URL(request.url()).pathname.replace(/^\/autodesk\/api\/v1/, "");
    return handle(route, request, p);
  });
  await page.route(/\/api\/(auth|live)\//, (route, request) => {
    const u = new URL(request.url());
    if (u.pathname.startsWith("/autodesk/")) return route.fallback();
    return handle(route, request, u.pathname);
  });
  return mock;
}

/** Fail the test on console errors (AD-UI-16); call before page.goto. */
export function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    const t = m.text();
    if (/fonts\.(googleapis|gstatic)|net::ERR_FAILED|Failed to load resource/.test(t)) return;   // aborted font loads, mocked 4xx/5xx
    errors.push(t);
  });
  page.on("pageerror", (e) => errors.push(String(e)));
  return errors;
}

// ── request contracts ────────────────────────────────────────────────────────────────────────────────────────────────

const REQ_DIR = path.join(process.cwd(), "e2e", "fixtures", "autodesk", "requests");   // specs run from frontend-v5/

/**
 * Request bodies the UI sends, kept in e2e/fixtures/autodesk/requests/<file>.json as
 *   { "<name>": { "method": "POST", "path": "/desk/controls/STOP_NEW_ENTRIES", "body": {...}, "expect": [200] } }
 * Ids in paths and bodies are placeholders ("{account_id}", "{approval_id}", "{simulation_id}", "{policy_id}",
 * "{plan_hash}", "{session_date}", …). The backend test tests/autodesk/test_ui_request_contracts.py posts every entry to
 * the real FastAPI app with real ids and checks the status; this helper checks the UI sent exactly that body.
 */
export function contract(file: string, name: string): { method: string; path: string; body: unknown; expect: number[] } {
  const all = JSON.parse(fs.readFileSync(path.join(REQ_DIR, `${file}.json`), "utf8")) as Record<string, { method: string; path: string; body: unknown; expect: number[] }>;
  const c = all[name];
  if (!c) throw new Error(`no contract ${file}.${name}`);
  return c;
}

function fill(v: unknown, vars: Record<string, string>): unknown {
  if (typeof v === "string") {
    const whole = /^\{(\w+)\}$/.exec(v);
    if (whole && whole[1] in vars) return vars[whole[1]];
    return v.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? vars[k] : m));
  }
  if (Array.isArray(v)) return v.map((x) => fill(x, vars));
  if (v && typeof v === "object") return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, fill(x, vars)]));
  return v;
}

/** Assert that `sent` is the contract's request with `vars` filled in (path and body). */
export function expectContract(sent: Captured | undefined, file: string, name: string, vars: Record<string, string> = {}) {
  const c = contract(file, name);
  expect(sent, `the UI did not send ${file}.${name}`).toBeTruthy();
  expect({ method: sent!.method, path: sent!.path, body: sent!.body }).toEqual({ method: c.method, path: fill(c.path, vars), body: fill(c.body, vars) });
}
