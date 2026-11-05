/**
 * Fixtures for the Simulation studio · New simulation spec (autodesk-studio-setup.spec.ts).
 *
 * // MOCK — not real data. Bodies copy the real desk API's shapes: GET /policies (rows of autodesk.policies),
 * // GET /agents (agent_registry rows, from autodesk-fixtures-agents.ts), GET /simulations (store.list_simulations),
 * // POST /simulations (201, the created row with config.sessions), POST /simulations/{sid}/start (200, the row) and
 * // /run (202). The desk status default (autodesk-mock.ts) gives the latest cash session 2026-11-04.
 */
import { TENANT, reply, type Handler, type Req, type RouteValue } from "./autodesk-mock";
import { registry } from "./autodesk-fixtures-agents";

export const POL = "POL-1b7e93c4d05a4e2f9c61";
export const NEW_SID = "SIM-4c8e2a6f1b3d5e7a9c0b";
export const OLD_SID = "SIM-2b9d7f1e0a3c4b5d6e7f";

export const POLICIES = [
  { policy_id: POL, tenant_id: TENANT, name: "Desk default", scope_type: "TENANT", scope_ref: null, current_version: 3, created_at: "2026-11-02T04:10:00.000+00:00", updated_at: "2026-11-05T05:02:00.000+00:00" },
];

const CREATED = "2026-11-05T06:20:00.000+00:00";

export const OLD_RUN = {
  simulation_id: OLD_SID, tenant_id: TENANT, name: "Replay 2–3 Nov", mode: "HISTORICAL_REPLAY", status: "COMPLETED",
  config: { name: "Replay 2–3 Nov", description: "", mode: "HISTORICAL_REPLAY", start_date: "2026-11-02", end_date: "2026-11-03", universe: "FNO", include_fno: true, starting_capital_rs: "10000000", operating_mode: "AUTONOMOUS_PAPER", policy_id: null, max_proposals_per_session: 3, symbols: null, seed: 42, speed: "STEP", sessions: ["2026-11-02", "2026-11-03"] },
  account_id: "ACC-5d4c3b2a1f0e9d8c7b6a", clock_sim_time: "2026-11-03T12:30:00+00:00", clock_session: "2026-11-03", clock_phase: "EOD", step_seq: 12,
  versions: null, results: null, error: null, created_by: `user:${TENANT}`, created_at: "2026-11-05T05:40:02.000+00:00", started_at: "2026-11-05T05:40:05.000+00:00",
  ended_at: "2026-11-05T05:44:51.000+00:00", updated_at: "2026-11-05T05:44:51.000+00:00",
};

/** The row POST /simulations returns: the stored config (model_dump with defaults) + sessions, status CREATED. */
function createdRow(b: Record<string, unknown>) {
  const start = String(b.start_date);
  const end = String(b.end_date);
  return {
    simulation_id: NEW_SID, tenant_id: TENANT, name: b.name, mode: b.mode, status: "CREATED",
    config: { description: "", universe: "FNO", include_fno: true, policy_id: null, symbols: null, seed: 42, speed: "STEP", ...b, sessions: start === end ? [start] : [start, end] },
    account_id: "ACC-9e8d7c6b5a4f3e2d1c0b", clock_sim_time: null, clock_session: null, clock_phase: null, step_seq: 0,
    versions: { app: "0.1.0", policy: { policy_id: POL, version: 3, sha256: "9f2c4e6a8b0d1f3e5a7c9b1d3f5e7a9c0b2d4f6e8a0c2e4f6a8b0d2f4e6a8c0b" } },
    results: null, error: null, created_by: `user:${TENANT}`, created_at: CREATED, started_at: null, ended_at: null, updated_at: CREATED,
  };
}

export interface SetupState { created: Record<string, unknown> | null }

/** Routes the New simulation view reads and writes; override any key per test. */
export function setupRoutes(st: SetupState = { created: null }, over: Record<string, RouteValue> = {}): Record<string, RouteValue> {
  return {
    "GET /policies": POLICIES,
    "GET /agents": registry(),
    "GET /simulations": (() => (st.created ? [st.created, OLD_RUN] : [OLD_RUN])) as Handler,
    "POST /simulations": ((r: Req) => {
      st.created = createdRow(r.body as Record<string, unknown>);
      return reply(201, st.created);
    }) as Handler,
    "POST /simulations/:sid/start": ((r: Req) => {
      if (!st.created || r.params.sid !== NEW_SID) return reply(404, { error: "NOT_FOUND", message: `not found: ${r.params.sid}` });
      Object.assign(st.created, { status: "RUNNING", started_at: CREATED });
      return { ...st.created };
    }) as Handler,
    "POST /simulations/:sid/run": ((r: Req) => reply(202, { simulation_id: r.params.sid, status: "RUNNING", background_run: true })) as Handler,
    ...over,
  };
}
