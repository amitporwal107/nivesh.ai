/**
 * Fixtures for the Policies & permissions spec (AD-UI-70..79).
 *
 * // MOCK — not real data. Shapes copy the real desk API: GET /policies rows (autodesk.policies), GET /policies/{id}
 * // (store.get_policy: policy_id, name, scope_type, version, current_version, body, body_sha256, created_at,
 * // created_by, reason), POST /policies/{id}/versions → {policy_id, version, body}, POST /accounts/{id}/mode → the
 * // account row. DEFAULT_BODY is PolicyBody() of backend/autodesk/contracts.py dumped with mode="json" (Decimals as
 * // strings). The handlers below are stateful like the real API: a write changes what the next GET returns.
 */
import { ACCOUNT_A, NOW, TENANT, reply, type MockState, type Req, type RouteValue } from "./autodesk-mock";

export const POL = ACCOUNT_A.policy_id;
export const ACC = ACCOUNT_A.account_id;

export const AUTONOMY_STRATEGIES = ["LONG_EQUITY", "BULL_CALL_SPREAD", "BEAR_PUT_SPREAD", "BULL_PUT_SPREAD", "BEAR_CALL_SPREAD", "IRON_CONDOR"];

export const DEFAULT_BODY = {
  policy_schema: "autodesk-policy-v1",
  source: "risk-profile owner-default-2026-10-27",
  per_trade_risk_pct: "0.5",
  open_risk_pct: "3",
  position_pct: "10",
  sector_pct: "25",
  daily_loss_pct: "2",
  weekly_loss_pct: "4",
  max_drawdown_pct: "10",
  min_reward_risk: "1.5",
  credit_min_width_fraction: "0.3333",
  max_margin_utilization_pct: "25",
  futures_margin_pct: "15",
  allowed_segments: ["CASH", "FUTURES", "OPTIONS"],
  allowed_strategies: ["LONG_EQUITY", "LONG_FUTURES", "LONG_CALL", "LONG_PUT", "BULL_CALL_SPREAD", "BEAR_PUT_SPREAD", "BULL_PUT_SPREAD", "BEAR_CALL_SPREAD", "IRON_CONDOR"],
  min_signal_score: "60",
  max_proposals_per_session: 5,
  min_days_to_expiry: 7,
  max_legs: 4,
  max_lots_per_leg: 10,
  min_adv_rs: "10000000",
  require_traded_legs: true,
  max_data_age_sessions: 1,
  autonomy: { auto_approve: true, max_risk_pct: "0.5", min_signal_score: "70", strategies: AUTONOMY_STRATEGIES },
};

export interface PolicyVersion { body: Record<string, unknown>; created_at: string; created_by: string; reason: string | null }

export function policyState(): { versions: PolicyVersion[] } {
  return { versions: [{ body: structuredClone(DEFAULT_BODY), created_at: "2026-11-05T05:20:11.000Z", created_by: `user:${TENANT}`, reason: "default from the risk-profile defaults" }] };
}

const vs = (s: MockState) => (s.policy as { versions: PolicyVersion[] }).versions;

export function policyRow(s: MockState) {
  return { policy_id: POL, tenant_id: TENANT, name: "Desk default", scope_type: "TENANT", scope_ref: null, current_version: vs(s).length,
    created_at: "2026-11-05T05:20:11.000Z", updated_at: vs(s)[vs(s).length - 1].created_at };
}

export function policyDetail(s: MockState, version?: number) {
  const n = version ?? vs(s).length;
  const v = vs(s)[n - 1];
  if (!v) return reply(404, { error: "NOT_FOUND", message: `not found: ${POL}@${n}` });
  return { policy_id: POL, name: "Desk default", scope_type: "TENANT", version: n, current_version: vs(s).length, body: v.body,
    body_sha256: String(n).repeat(64).slice(0, 64), created_at: v.created_at, created_by: v.created_by, reason: v.reason };
}

/** POST /policies/{id}/versions like the API: shallow merge, then a new version (201). */
export function addVersion(r: Req, s: MockState) {
  const b = r.body as { changes: Record<string, unknown>; reason: string };
  const cur = vs(s)[vs(s).length - 1].body;
  const body = { ...cur, ...b.changes };
  vs(s).push({ body, created_at: NOW, created_by: `user:${TENANT}`, reason: b.reason });
  return reply(201, { policy_id: POL, version: vs(s).length, body });
}

/** POST /accounts/{id}/mode like the API: the updated account row. */
export function setMode(r: Req, s: MockState) {
  const b = r.body as { mode: string; reason: string };
  const a = s.accounts.find((x) => x.account_id === r.params.account_id);
  if (!a) return reply(404, { error: "NOT_FOUND", message: `not found: ${r.params.account_id}` });
  a.operating_mode = b.mode;
  a.updated_at = NOW;
  return { ...a };
}

export const POLICY_ROUTES: Record<string, RouteValue> = {
  "GET /policies": (_r: Req, s: MockState) => [policyRow(s)],
  "GET /policies/:policy_id": (r: Req, s: MockState) => (r.params.policy_id === POL ? policyDetail(s, r.query.get("version") ? Number(r.query.get("version")) : undefined) : reply(404, { error: "NOT_FOUND", message: `not found: ${r.params.policy_id}` })),
  "POST /policies/:policy_id/versions": addVersion,
  "POST /accounts/:account_id/mode": setMode,
};

/** A second, older history: v1 default, v2 tightened (0.5 → 0.4), so v2 is active. */
export function twoVersions(): { versions: PolicyVersion[] } {
  const s = policyState();
  s.versions.push({ body: { ...structuredClone(DEFAULT_BODY), per_trade_risk_pct: "0.4", max_lots_per_leg: 8 }, created_at: "2026-11-05T05:40:00.000Z", created_by: `user:${TENANT}`, reason: "results week: smaller size" });
  return s;
}
