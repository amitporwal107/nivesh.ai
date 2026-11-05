/**
 * Simulation studio · Scenario library fixtures for autodesk-studio-scenarios.spec.ts.
 *
 * // MOCK — not real data. The scenario library reads nothing from the desk API (there is no scenario endpoint in
 * // Phase 1); the only call on the page is the studio frame's GET /simulations, answered with one row in the shape of
 * // store.list_simulations.
 */
import { TENANT } from "./autodesk-mock";

export const SCEN_SID = "SIM-5f4e3d2c1b0a9f8e7d6c";

export const SCEN_SIMS = [{
  simulation_id: SCEN_SID, tenant_id: TENANT, name: "Replay 4 Nov", mode: "HISTORICAL_REPLAY", status: "COMPLETED",
  config: { name: "Replay 4 Nov", mode: "HISTORICAL_REPLAY", start_date: "2026-11-04", end_date: "2026-11-04", universe: "FNO", operating_mode: "AUTONOMOUS_PAPER", starting_capital_rs: "10000000", max_proposals_per_session: 5, seed: 42, speed: "STEP", sessions: ["2026-11-04"] },
  account_id: "ACC-2b3c4d5e6f7a8b9c0d1e", clock_sim_time: "2026-11-04T12:30:00+00:00", clock_session: "2026-11-04", clock_phase: "EOD", step_seq: 6,
  versions: null, results: null, error: null, created_by: `user:${TENANT}`, created_at: "2026-11-05T04:00:00+00:00", started_at: "2026-11-05T04:00:02+00:00",
  ended_at: "2026-11-05T04:02:10+00:00", updated_at: "2026-11-05T04:02:10+00:00",
}];
