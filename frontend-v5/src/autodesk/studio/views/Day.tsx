/**
 * Simulation studio · Trading day (docs/autodesk/design/prototype/studio/SimDay.dc.html), on the run in `?sim=` (else the
 * newest run).
 *
 * Phase 1 truth: a run replays past NSE sessions phase by phase — PREMARKET 08:30, SCAN 08:45, PROPOSALS 09:00, OPEN 09:15,
 * CLOSE 15:30, EOD 18:00 IST — with the desk's agents on end-of-day data. The clock moves by phase, not by minute. Every
 * figure comes from the simulation API: the row (status, clock, config, versions), /results (policy violation attempts)
 * and /timeline (clock rows + events, read incrementally). The design's blocks that need orders, fills, positions, P&L,
 * scenario injection, speed multipliers or checkpoints keep their place and say which phase brings them; they never show
 * sample figures. Play / Pause map to the real lifecycle actions (start, run, pause, resume).
 */
import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { Link, useNavigate } from "react-router-dom";
import { errorText } from "../../api";
import { DASH, dateLong, humanize, timeIST } from "../../format";
import { useIsMobile } from "../../hooks";
import { TONE_COLOR, describe, rangeText, sessionsOf, simTimeOf, type SimVersions } from "../../screens/simulator/model";
import { useSimActions, useSimResults, useSimulation } from "../../screens/simulator/queries";
import type { EventRow, SimulationRow } from "../../types";
import { ErrorBox, Loading, PhaseNote } from "../../ui";
import { useStudioRun } from "../run";
import { DayTrack } from "./day/Track";
import { FEED_CAP, MODE_NAME, PHASES, PHASE_INFO, dayView, isPhase, nextStep, placeOf, plural, useDayTimeline, type DayView, type Phase } from "./day/model";

const STATUS: Record<string, { t: string; c: string; l: string }> = {
  CREATED: { t: "NOT STARTED", c: "var(--ink-2)", l: "var(--line-2)" },
  RUNNING: { t: "RUNNING", c: "var(--mint)", l: "var(--mint-line)" },
  PAUSED: { t: "PAUSED", c: "var(--amber)", l: "var(--amber-line)" },
  STOPPED: { t: "STOPPED", c: "var(--danger)", l: "var(--danger-line)" },
  COMPLETED: { t: "COMPLETE", c: "var(--indigo)", l: "var(--indigo-line)" },
  FAILED: { t: "FAILED", c: "var(--danger)", l: "var(--danger-line)" },
};

const glass: CSSProperties = { background: "var(--bg-glass)", backdropFilter: "blur(20px) saturate(140%)", WebkitBackdropFilter: "blur(20px) saturate(140%)" } as CSSProperties;
const h24: CSSProperties = { fontFamily: "var(--display)", fontSize: 24 };
const box: CSSProperties = { display: "flex", flexDirection: "column", padding: "18px 20px", borderRadius: 14, border: "1px solid var(--line)", background: "var(--bg-1)", minWidth: 0 };
const chip = (on: boolean, enabled = true): CSSProperties => ({
  cursor: enabled ? "pointer" : "not-allowed", opacity: enabled ? 1 : 0.4, padding: "6px 11px", borderRadius: 999, fontSize: 12, fontFamily: "var(--sans)",
  border: `1px solid ${on ? "var(--indigo-line)" : "var(--line-2)"}`, background: on ? "var(--indigo-soft)" : "transparent", color: on ? "var(--indigo)" : "var(--ink-2)",
});
const banner: CSSProperties = { padding: "11px 14px", borderRadius: 12, border: "1px solid var(--danger-line)", background: "var(--danger-soft)", fontSize: 13, lineHeight: 1.5, color: "var(--ink-2)" };

/** The design's two-part headline, from where the run's clock is (its own day's counts). */
function headline(sim: SimulationRow, d: DayView): [string, string] {
  const ph = isPhase(sim.clock_phase) ? sim.clock_phase : null;
  const t = d.types;
  let a: string;
  let b: string;
  if (!ph) {
    a = `${sim.name} is ready to replay ${rangeText(sim)}.`;
    b = "No order can leave the simulator.";
  } else if (ph === "PREMARKET" || ph === "SCAN" || ph === "PROPOSALS") {
    a = "Before the bell: the desk loads its world.";
    b = `${plural(t.SIGNAL_DETECTED ?? 0, "signal")} and ${plural(t.TRADE_PLAN_CREATED ?? 0, "plan")} so far; no order can leave the simulator.`;
  } else if (ph === "OPEN") {
    a = "The market is open on the replay clock.";
    b = `${plural(t.APPROVAL_GRANTED ?? 0, "plan")} approved today, none sent: Phase 1 has no orders.`;
  } else if (ph === "CLOSE") {
    a = "The bell has rung.";
    b = "Nothing was filled, so there is nothing to reconcile.";
  } else {
    a = "The bell has rung.";
    b = sim.status === "COMPLETED" ? "Every session of this run is replayed." : "The session is closed; the next one starts at its pre-market check.";
  }
  if (sim.status === "STOPPED") { if (!ph) a = `${sim.name} was stopped before its first step.`; b = "The run was stopped here; no further step runs."; }
  if (sim.status === "FAILED") b = "The run failed here and stopped moving.";
  return [a, b];
}

interface Row { key: number; e: EventRow; count: number; at: string | null }

export default function StudioDay() {
  const mobile = useIsMobile();
  const navigate = useNavigate();
  const { simId, list } = useStudioRun();
  const simQ = useSimulation(simId);
  const sim = simQ.data;
  const tick = [sim?.step_seq, sim?.status] as const;
  const resQ = useSimResults(simId, tick);
  const tlQ = useDayTimeline(simId, !!sim);
  const act = useSimActions(simId);
  const [picked, setPicked] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase | null>(null);
  const [shown, setShown] = useState(10);

  // The timeline is read incrementally: read the new events whenever the clock moves or the status changes.
  const seen = useRef<string | null>(null);
  useEffect(() => {
    const k = `${simId}|${sim?.step_seq}|${sim?.status}`;
    if (seen.current !== null && seen.current !== k && sim) tlQ.refetch();
    seen.current = k;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [simId, sim?.step_seq, sim?.status]);
  useEffect(() => { setPicked(null); setPhase(null); setShown(10); act.reset(); // another run on screen
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [simId]);

  const tl = tlQ.data;
  const sessions = sessionsOf(sim);
  const clockSession = sim?.clock_session ?? null;
  const session = picked && sessions.includes(picked) ? picked : clockSession ?? sessions[0] ?? null;
  const sIdx = session ? sessions.indexOf(session) : -1;
  const total = sessions.length * PHASES.length;
  const day = useMemo(() => dayView(tl, session), [tl, session]);
  const clockDay = useMemo(() => dayView(tl, clockSession), [tl, clockSession]);
  const next = nextStep(sim);
  const reachedDays = useMemo(() => new Set((tl?.clock ?? []).map((c) => c.session_date)), [tl]);

  const items = useMemo((): Row[] => {
    if (!tl) return [];
    const out: Row[] = [];
    for (let i = tl.feed.length - 1; i >= 0; i--) {
      const it = tl.feed[i];
      const at = simTimeOf(it.e, tl.clockSeqs);
      const pl = placeOf(at, { session: next.session, phase: next.phase });
      if (pl.session !== session) continue;
      if (phase && (pl.live || pl.phase !== phase)) continue;
      out.push({ key: it.e.seq, e: it.e, count: it.count, at });
    }
    return out;
  }, [tl, session, phase, next.session, next.phase]);

  // ── controls ────────────────────────────────────────────────────────────────────────────────────────────────────
  const status = sim?.status ?? "";
  const bg = !!sim?.background_run;
  const playing = status === "RUNNING" && bg;
  const terminal = ["COMPLETED", "STOPPED", "FAILED"].includes(status);
  const busy = act.isPending;
  const canToggle = !!sim && !terminal && !busy;
  const playT = busy ? "…" : status === "COMPLETED" ? "Day done" : status === "STOPPED" ? "Stopped" : status === "FAILED" ? "Failed" : playing ? "Pause" : "Play";
  const toggle = () => {
    if (!canToggle) return;
    if (status === "CREATED") act.mutate([{ action: "start" }, { action: "run" }]);
    else if (playing) act.mutate([{ action: "pause" }]);
    else if (status === "PAUSED") act.mutate([{ action: "resume" }, { action: "run" }]);
    else if (status === "RUNNING") act.mutate([{ action: "run" }]);
  };
  const keep = simId ? `?sim=${encodeURIComponent(simId)}` : "";
  const others = (list.data ?? []).filter((r) => r.simulation_id !== simId).length;

  // ── no run / failing loads ──────────────────────────────────────────────────────────────────────────────────────
  if (!simId) {
    return (
      <div data-testid="studio-day" style={{ display: "flex", flexDirection: "column", gap: 18 }}>
        <span className="nv-eyebrow">Full trading day</span>
        {list.error ? <ErrorBox error={list.error} what="the simulations" onRetry={() => list.refetch()} />
          : list.isLoading ? <Loading label="Loading the simulations" />
          : (
            <div data-testid="day-empty" style={{ display: "flex", flexDirection: "column", gap: 10, padding: "18px 20px", borderRadius: 14, border: "1px dashed var(--line-2)", fontSize: 14, lineHeight: 1.55, color: "var(--ink-3)" }}>
              <span>No simulation yet. Create one to replay past sessions with the desk's agents and policy; it runs in its own simulation account, and its day shows here.</span>
              <span><Link to="/studio/new" className="ad-link" data-testid="day-empty-new">New simulation ›</Link></span>
            </div>
          )}
      </div>
    );
  }
  if (!sim) {
    return (
      <div data-testid="studio-day" style={{ display: "flex", flexDirection: "column", gap: 18 }}>
        <span className="nv-eyebrow" style={{ overflowWrap: "anywhere" }}>Full trading day · {simId}</span>
        {simQ.error ? <ErrorBox error={simQ.error} what="this simulation" onRetry={() => simQ.refetch()} /> : <Loading label="Loading the simulation" />}
      </div>
    );
  }

  const st = STATUS[status] ?? STATUS.CREATED;
  const ph = isPhase(sim.clock_phase) ? sim.clock_phase : null;
  const [headA, headB] = headline(sim, clockDay);
  const policy = (sim.versions as SimVersions | null)?.policy;
  const seed = (sim.config as { seed?: unknown }).seed;
  const T = day.types;
  const loaded = !!tl;
  const n = (v: number | undefined) => (loaded ? String(v ?? 0) : DASH);
  const counters: { id: string; k: string; v: string; c: string; phase?: number }[] = [
    { id: "signals", k: "Signals", v: n(T.SIGNAL_DETECTED), c: "var(--ink)" },
    { id: "plans", k: "Plans", v: n(T.TRADE_PLAN_CREATED), c: "var(--ink)" },
    { id: "risk", k: "Risk checks", v: n(T.RISK_ASSESSMENT_COMPLETED), c: "var(--ink)" },
    { id: "approvals", k: "Approvals", v: n((T.APPROVAL_GRANTED ?? 0) + (T.APPROVAL_REJECTED ?? 0) + (T.APPROVAL_NEEDS_HUMAN ?? 0)), c: "var(--ink)" },
    { id: "fills", k: "Fills", v: DASH, c: "var(--ink-3)", phase: 2 },
    { id: "exits", k: "Exits", v: DASH, c: "var(--ink-3)", phase: 3 },
    { id: "shocks", k: "Shocks", v: DASH, c: "var(--ink-3)", phase: 3 },
    { id: "recovered", k: "Recovered", v: loaded ? String(day.recovered) : DASH, c: "var(--mint)" },
  ];

  const eodReached = day.reached.has("EOD");
  const lastDay = sIdx === sessions.length - 1;
  const eodSt = eodReached ? (status === "COMPLETED" && lastDay ? "RUN COMPLETE" : "SESSION CLOSED") : `AT ${PHASE_INFO.EOD.at}`;
  const pv = resQ.data?.policy_violation_attempts;
  const eodRows: { id: string; k: string; v: string; c: string; phase?: number }[] = [
    { id: "orders", k: "Orders · fills · breaks", v: DASH, c: "var(--ink-3)", phase: 2 },
    { id: "gross", k: "Gross · charges", v: DASH, c: "var(--ink-3)", phase: 2 },
    { id: "net", k: "Net P&L after costs", v: DASH, c: "var(--ink-3)", phase: 2 },
    { id: "drawdown", k: "Max drawdown", v: DASH, c: "var(--ink-3)", phase: 2 },
    { id: "assertions", k: "Assertions", v: DASH, c: "var(--ink-3)", phase: 3 },
    { id: "violations", k: sessions.length > 1 ? "Policy violations · whole run" : "Policy violations", v: eodReached && pv != null ? String(pv) : DASH, c: !eodReached || pv == null ? "var(--ink-3)" : pv ? "var(--danger)" : "var(--mint)" },
    { id: "signals-expired", k: "Signals expired at the close", v: eodReached && loaded ? String(day.eod?.SIGNAL_EXPIRED ?? 0) : DASH, c: "var(--ink)" },
    { id: "approvals-expired", k: "Approvals expired at the close", v: eodReached && loaded ? String(day.eod?.APPROVAL_EXPIRED ?? 0) : DASH, c: "var(--ink)" },
  ];

  const clockHere = !!session && session === clockSession;
  const tfmt = (iso: string | null) => (iso ? timeIST(iso, { seconds: false }) : "…");

  return (
    <div data-testid="studio-day" style={{ display: "flex", flexDirection: "column", gap: 18, fontFamily: "var(--sans)", color: "var(--ink)" }}>
      <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
          <span className="nv-eyebrow" data-testid="day-eyebrow" style={{ overflowWrap: "anywhere" }}>Full trading day · {sim.simulation_id}</span>
          <span className="nv-pill nv-pill-indigo" data-testid="day-mode-pill" style={{ maxWidth: "100%", overflowWrap: "anywhere" }}>
            <span className="nv-dot" style={{ background: "var(--indigo)" }} />
            {MODE_NAME[sim.mode] ?? humanize(sim.mode)} · {session ? dateLong(session) : rangeText(sim)}{sessions.length > 1 && sIdx >= 0 ? ` · session ${sIdx + 1} of ${sessions.length}` : ""}
          </span>
          <span className="nv-pill" data-testid="day-name-pill" style={{ maxWidth: "100%", overflowWrap: "anywhere" }}>{sim.name}</span>
          <span className="nv-pill" data-testid="day-policy-pill" style={{ maxWidth: "100%", overflowWrap: "anywhere" }}>
            {policy ? `${policy.policy_id} v${policy.version} · ` : ""}seed {seed == null ? DASH : String(seed)}
          </span>
        </div>
        <h1 data-testid="day-headline" style={{ margin: 0, fontFamily: "var(--display)", fontWeight: 400, fontSize: "clamp(28px,4vw,44px)", lineHeight: 1.06, letterSpacing: "-0.02em", textWrap: "pretty", maxWidth: 940, overflowWrap: "anywhere" } as CSSProperties}>
          {headA} <em style={{ color: "var(--indigo)" }}>{headB}</em>
        </h1>
      </section>

      <section data-testid="day-controls" style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center", padding: "10px 12px", borderRadius: 16, border: "1px solid var(--line-2)", boxShadow: "var(--shadow-pop)", ...glass }}>
        <button type="button" data-testid="day-toggle" onClick={toggle} disabled={!canToggle}
          style={{ cursor: canToggle ? "pointer" : "not-allowed", opacity: canToggle ? 1 : 0.5, minWidth: 96, height: 38, padding: "0 16px", borderRadius: 10, border: 0, background: playing ? "var(--bg-3)" : "var(--indigo)", color: playing ? "var(--ink)" : "#0A0E1A", fontSize: 13.5, fontWeight: 500 }}>{playT}</button>
        <button type="button" data-testid="day-restart" disabled title="Restarting a day needs checkpoints, which come in Phase 3"
          style={{ cursor: "not-allowed", opacity: 0.45, height: 38, padding: "0 14px", borderRadius: 10, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--ink)", fontSize: 13 }}>Restart day</button>
        <div data-testid="day-speeds" title="Speed multipliers have no effect in Phase 1: the replay moves one phase at a time" style={{ display: "flex", gap: 2, padding: 3, borderRadius: 999, background: "var(--bg-2)" }}>
          {[60, 120, 300, 600].map((v) => (
            <button key={v} type="button" disabled aria-disabled="true" style={{ cursor: "not-allowed", opacity: 0.45, border: 0, padding: "6px 11px", borderRadius: 999, background: "transparent", color: "var(--ink-2)", fontFamily: "var(--mono)", fontSize: 10.5 }}>{v}×</button>
          ))}
        </div>
        <span style={{ flex: 1 }} />
        {sessions.length > 1 && (
          <select data-testid="day-session" aria-label="Trading day" value={session ?? ""} onChange={(e) => { setPicked(e.target.value); setPhase(null); setShown(10); }}
            style={{ padding: "7px 10px", borderRadius: 10, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--ink)", fontSize: 12.5, maxWidth: "100%", minWidth: 0 }}>
            {sessions.map((d, i) => <option key={d} value={d}>{dateLong(d)} · {i + 1} of {sessions.length}{reachedDays.has(d) ? "" : " · not reached"}</option>)}
          </select>
        )}
        <span className="nv-eyebrow" style={{ fontSize: 9.5 }}>Jump to</span>
        <div data-testid="day-jumps" style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          <button type="button" data-testid="day-jump-all" aria-pressed={!phase} onClick={() => { setPhase(null); setShown(10); }} style={chip(!phase)}>All day</button>
          {PHASES.map((p) => {
            const ok = day.reached.has(p);
            return (
              <button key={p} type="button" data-testid={`day-jump-${p}`} aria-pressed={phase === p} disabled={!ok} title={ok ? `${PHASE_INFO[p].at} · ${PHASE_INFO[p].n}` : `${PHASE_INFO[p].at} · not reached yet`}
                onClick={() => { setPhase(phase === p ? null : p); setShown(10); }} style={chip(phase === p, ok)}>{PHASE_INFO[p].chip}</button>
            );
          })}
        </div>
      </section>
      <PhaseNote phase={3} testId="day-controls-note">
        Speed multipliers and restarting a day come in Phase 3. The replay clock moves one phase at a time (pre-market 08:30 to end of day 18:00) on
        end-of-day data: Play runs the remaining phases in the background, and Pause holds the clock after the phase in progress.
      </PhaseNote>
      {act.error && <div role="alert" data-testid="day-action-error" style={banner}>{errorText(act.error)}</div>}
      {status === "STOPPED" && (
        <div data-testid="day-stopped" style={banner}>
          Stopped at {sim.clock_sim_time ? `${timeIST(sim.clock_sim_time)} on ${dateLong(sim.clock_session)}` : "the start"} ({sim.clock_phase ?? "no phase run"}, step {sim.step_seq} of {total}).
          The clock stays where it is and no further step runs; nothing outside the simulation was touched.
        </div>
      )}
      {status === "FAILED" && <div data-testid="day-failed" style={banner}>The run failed and stopped moving: {sim.error ?? "no error recorded"}</div>}

      <section style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,320px),1fr))", gap: 16 }}>
        <div data-testid="day-clock" style={{ display: "flex", flexDirection: "column", gap: 12, padding: "20px 22px", borderRadius: 14, border: "1px solid var(--indigo-line)", background: "var(--bg-1)", boxShadow: "var(--shadow-card)", minWidth: 0 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
            <span className="nv-eyebrow">Simulation clock · IST</span>
            <span className="nv-pill" data-testid="day-status" style={{ color: st.c, borderColor: st.l }}>{st.t}</span>
          </div>
          <span className="nv-num" data-testid="day-clock-time" style={{ fontFamily: "var(--display)", fontSize: mobile ? 48 : 64, lineHeight: 1, letterSpacing: "-0.01em" }}>
            {sim.clock_sim_time ? timeIST(sim.clock_sim_time) : "--:--:--"}
          </span>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span data-testid="day-phase" style={{ fontSize: 16, fontWeight: 500 }}>
              {ph ? `${PHASE_INFO[ph].n} · ${dateLong(sim.clock_session)} · step ${sim.step_seq} of ${total}` : `Not started · step 0 of ${total}`}
            </span>
            <span data-testid="day-phase-note" style={{ fontSize: 13, lineHeight: 1.5, color: "var(--ink-3)" }}>
              {ph ? PHASE_INFO[ph].d : "The clock has not moved yet. Play replays the run phase by phase, from the first session's pre-market check at 08:30."}
            </span>
          </div>
        </div>
        <div data-testid="day-counters" style={{ display: "grid", gridTemplateColumns: `repeat(${mobile ? 2 : 4},minmax(0,1fr))`, gap: 8, alignContent: "start" }}>
          {counters.map((c) => (
            <div key={c.id} data-testid={`day-ctr-${c.id}`} title={c.phase ? `Phase ${c.phase}` : undefined} style={{ display: "flex", flexDirection: "column", gap: 3, padding: "11px 12px", borderRadius: 12, border: "1px solid var(--line)", background: "var(--bg-1)", minWidth: 0 }}>
              <span className="nv-eyebrow" style={{ fontSize: 8.5 }}>{c.k}</span>
              <span className="nv-num" style={{ fontFamily: "var(--display)", fontSize: 24, lineHeight: 1.05, color: c.c }}>{c.v}</span>
              {c.phase && <span style={{ fontFamily: "var(--mono)", fontSize: 8.5, letterSpacing: "0.06em", color: "var(--ink-4)" }}>PHASE {c.phase}</span>}
            </div>
          ))}
        </div>
      </section>

      <section data-testid="day-lanes" style={{ display: "flex", flexDirection: "column", gap: 10, padding: "16px 18px", borderRadius: 14, border: "1px solid var(--line)", background: "var(--bg-1)", boxShadow: "var(--shadow-card)", minWidth: 0 }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
          <span style={h24}>The day, agent by agent</span>
          <span className="nv-eyebrow" style={{ fontSize: 9.5 }}>08:00 → 18:30 · click the track to jump</span>
        </div>
        <DayTrack day={day} clockHere={clockHere} clockIso={sim.clock_sim_time} current={clockHere ? ph : null} selected={phase} onJump={(p) => { setPhase(p); setShown(10); }} />
        <div data-testid="day-legend" style={{ display: "flex", flexWrap: "wrap", gap: "6px 16px", fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.06em", color: "var(--ink-3)" }}>
          <span><span style={{ color: "var(--mint)" }}>●</span> DECISION</span>
          <span><span style={{ color: "var(--indigo)" }}>●</span> CLOCK · RUN STATE</span>
          <span><span style={{ color: "var(--amber)" }}>●</span> NEEDS ATTENTION</span>
          <span><span style={{ color: "var(--danger)" }}>●</span> FAILED · BLOCKED</span>
          <span><span style={{ color: "var(--amber)" }}>◆</span> INJECTED SCENARIO · PHASE 3</span>
          <span>FAINT = SCHEDULED, NOT YET REACHED</span>
        </div>
      </section>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,420px),1fr))", gap: 16, alignItems: "start" }}>
        <section data-testid="day-pnl" style={{ ...box, gap: 10, padding: "18px 20px 14px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "baseline" }}>
            <span style={h24}>Net P&amp;L, simulated</span>
            <span className="nv-num" style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--ink-3)" }}>NO FILLS IN PHASE 1</span>
          </div>
          <PhaseNote phase={2} testId="day-pnl-note">
            The P&amp;L curve after simulated costs needs paper fills, which come in Phase 2. Plans approved in this run are not filled, so there is no P&amp;L to draw.
          </PhaseNote>
        </section>
        <section data-testid="day-positions" style={box}>
          <span style={{ ...h24, paddingBottom: 8 }}>Positions</span>
          <PhaseNote phase={2} testId="day-positions-note">
            Positions begin with paper fills in Phase 2. This run approves plans but places no orders, so there is no position to list.
          </PhaseNote>
        </section>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,420px),1fr))", gap: 16, alignItems: "start" }}>
        <section data-testid="day-feed" style={box}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", paddingBottom: 8 }}>
            <span style={h24}>Event feed</span>
            <span className="nv-eyebrow" style={{ fontSize: 9.5 }}>Newest first · structured messages</span>
          </div>
          {tlQ.error && <ErrorBox error={tlQ.error} what="the timeline" onRetry={() => tlQ.refetch()} />}
          {tlQ.isLoading && <Loading rows={2} label="Loading the timeline" />}
          {tl && items.length === 0 && (
            <span data-testid="day-feed-empty" style={{ fontSize: 13, lineHeight: 1.5, color: "var(--ink-3)", padding: "9px 0", borderTop: "1px solid var(--line)" }}>
              {phase ? "No events in this phase."
                : tl.dropped > 0 && session !== next.session ? `This day's events are older than the newest ${FEED_CAP} rows this list keeps; the counters above still count them.`
                : status === "CREATED" ? "No events yet. Press Play to replay the run."
                : "No events on this day yet."}
            </span>
          )}
          {items.slice(0, shown).map((it) => {
            const d = describe(it.e);
            const p = (it.e.payload ?? {}) as Record<string, unknown>;
            const text = it.count > 1 ? `${it.count} signals${p.reason ? ` · ${String(p.reason)}` : ""}` : d.text;
            return (
              <div key={it.key} data-testid="day-feed-row" style={{ display: "grid", gridTemplateColumns: "62px minmax(0,1fr)", gap: 10, padding: "8px 0", borderTop: "1px solid var(--line)", alignItems: "baseline" }}>
                <span className="nv-num" title={it.at ?? "in the phase now running"} style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-3)" }}>{tfmt(it.at)}</span>
                <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.06em", color: TONE_COLOR[d.tone], overflowWrap: "anywhere" }}>{d.route.toUpperCase()} · {d.type}{it.count > 1 ? ` ×${it.count}` : ""}</span>
                  {text && <span style={{ fontSize: 13, lineHeight: 1.45, overflowWrap: "anywhere" }}>{text}</span>}
                </div>
              </div>
            );
          })}
          {items.length > shown && (
            <span style={{ paddingTop: 8, borderTop: "1px solid var(--line)" }}>
              <button type="button" className="ad-link" data-testid="day-feed-more" onClick={() => setShown((x) => x + 20)}>Show {Math.min(20, items.length - shown)} more ›</button>
            </span>
          )}
          {tl && tl.total > 0 && (
            <span data-testid="day-feed-count" style={{ paddingTop: 8, fontFamily: "var(--mono)", fontSize: 9.5, color: "var(--ink-4)", overflowWrap: "anywhere" }}>
              {tl.total} EVENTS READ · {items.length} ROWS {phase ? "IN THIS PHASE" : "ON THIS DAY"}{tl.dropped > 0 ? ` · ONLY THE NEWEST ${FEED_CAP} ROWS OF THE RUN ARE KEPT` : ""}
            </span>
          )}
          {tl?.more && (
            <span style={{ paddingTop: 6 }}>
              <button type="button" className="ad-link" data-testid="day-feed-read-more" onClick={() => tlQ.refetch()}>More events remain · read on ›</button>
            </span>
          )}
        </section>

        <section data-testid="day-eod" style={{ display: "flex", flexDirection: "column", gap: 12, padding: "18px 20px", borderRadius: 14, border: `1px solid ${eodReached ? "var(--mint-line)" : "var(--line)"}`, background: "var(--bg-1)", minWidth: 0 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <span style={{ ...h24, flex: 1 }}>End of day</span>
            <span className="nv-pill" data-testid="day-eod-status" style={{ color: eodReached ? "var(--mint)" : "var(--ink-3)", borderColor: eodReached ? "var(--mint-line)" : "var(--line)" }}>{eodSt}</span>
          </div>
          <div>
            {eodRows.map((r) => (
              <div key={r.id} data-testid={`day-eod-${r.id}`} style={{ display: "flex", justifyContent: "space-between", gap: 10, padding: "8px 0", borderTop: "1px solid var(--line)", fontSize: 13 }}>
                <span style={{ color: "var(--ink-2)" }}>{r.k}</span>
                <span style={{ display: "flex", gap: 8, alignItems: "baseline", flex: "none" }}>
                  {r.phase && <span style={{ fontFamily: "var(--mono)", fontSize: 8.5, letterSpacing: "0.06em", color: "var(--ink-4)" }}>PHASE {r.phase}</span>}
                  <span className="nv-num" style={{ fontFamily: "var(--mono)", fontSize: 12, color: r.c, textAlign: "right" }}>{r.v}</span>
                </span>
              </div>
            ))}
          </div>
          {resQ.error && <ErrorBox error={resQ.error} what="the run's results" onRetry={() => resQ.refetch()} />}
          {eodReached && (
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              <button type="button" data-testid="day-compare" disabled={!others} title={others ? undefined : "There is no other run to compare with yet"} onClick={() => navigate(`/studio/runs${keep}`)}
                style={{ cursor: others ? "pointer" : "not-allowed", opacity: others ? 1 : 0.5, padding: "10px 16px", borderRadius: 12, border: 0, background: "var(--indigo)", color: "#0A0E1A", fontSize: 13.5, fontWeight: 500 }}>
                {others ? "Compare with other runs" : "No other run to compare"}
              </button>
              <button type="button" data-testid="day-trace" onClick={() => navigate(`/studio/trace${keep}`)}
                style={{ cursor: "pointer", padding: "10px 16px", borderRadius: 12, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--ink)", fontSize: 13.5 }}>Replay a task trace</button>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
