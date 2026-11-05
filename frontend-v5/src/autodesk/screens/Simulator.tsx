/**
 * 10 · Trading desk simulator (docs/autodesk/design/prototype/TDSimulator.dc.html).
 *
 * Phase 1 replays past NSE sessions phase by phase (PREMARKET 08:30 → SCAN → PROPOSALS → OPEN → CLOSE → EOD 18:00)
 * with the same agents and policy on point-in-time data. Every figure comes from the simulation API: the row (clock,
 * status), /results (counters, limitations), /agents, /workflows, /timeline (events) and the workflow detail of one
 * trade proposal. Blocks that need fills, scenario injection, policy A/B or live trading keep their place in the design
 * and say which phase brings them; they never show sample figures.
 *
 * Routes /simulator (the most recent run) and /simulator/:simulationId.
 */
import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { errorText } from "../api";
import { DASH, dateLong, dateShort, num, timeIST, todayIST } from "../format";
import { useDeskStatus, useIsMobile } from "../hooks";
import { screenNo } from "../nav";
import type { SimulationRow, WorkflowRow } from "../types";
import { ErrorBox, Eyebrow, Loading, PhaseNote } from "../ui";
import { NewSimulationDialog, type NewSimInit, type ReplayMode } from "./simulator/NewSimulation";
import {
  AGENT_ORDER, PHASES_PER_SESSION, TONE_COLOR, configOf, countsText, describe, graphNodes, previousWeekday, rangeText, sessionsOf, simTimeOf, sum, who,
  type SimResults,
} from "./simulator/model";
import { useSimActions, useSimAgents, useSimResults, useSimTimeline, useSimWorkflows, useSimulation, useSimulations, useWorkflowDetail } from "./simulator/queries";

const MODES: [string, string][] = [["HISTORICAL_REPLAY", "Historical replay"], ["ACCELERATED_REPLAY", "Accelerated replay"], ["SCENARIO", "Scenario simulation"], ["LIVE_SHADOW", "Live shadow"]];
const SCENARIOS: [string, string][] = [["gap", "Gap down 2%"], ["ws", "Broker WebSocket drop, 180 s"], ["rej", "Reject storm, 5 orders"], ["chain", "Option chain stale, 90 s"], ["llm", "LLM gateway outage, 10 min"]];

const btn: CSSProperties = { cursor: "pointer", height: 38, padding: "0 14px", borderRadius: 10, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--ink)", fontSize: 13 };
const off = (on: boolean): CSSProperties => (on ? {} : { cursor: "not-allowed", opacity: 0.45 });
const box: CSSProperties = { display: "flex", flexDirection: "column", padding: "18px 20px", borderRadius: 14, border: "1px solid var(--line)", background: "var(--bg-1)" };
const h24: CSSProperties = { fontFamily: "var(--display)", fontSize: 24 };

const STATUS: Record<string, { t: string; c: string; l: string }> = {
  CREATED: { t: "NOT STARTED", c: "var(--ink-2)", l: "var(--line-2)" },
  RUNNING: { t: "RUNNING", c: "var(--mint)", l: "var(--mint-line)" },
  PAUSED: { t: "PAUSED", c: "var(--amber)", l: "var(--amber-line)" },
  STOPPED: { t: "STOPPED", c: "var(--danger)", l: "var(--danger-line)" },
  COMPLETED: { t: "COMPLETED", c: "var(--mint)", l: "var(--mint-line)" },
  FAILED: { t: "FAILED", c: "var(--danger)", l: "var(--danger-line)" },
};

export default function SimulatorScreen() {
  const mobile = useIsMobile();
  const { simulationId } = useParams();
  const navigate = useNavigate();
  const listQ = useSimulations();
  const sid = simulationId ?? listQ.data?.[0]?.simulation_id ?? null;
  const simQ = useSimulation(sid);
  const sim = simQ.data;
  const tick = [sim?.step_seq, sim?.status] as const;
  const resultsQ = useSimResults(sid, tick);
  const agentsQ = useSimAgents(sid, tick);
  const wfQ = useSimWorkflows(sid, tick);
  const tlQ = useSimTimeline(sid, tick);
  const act = useSimActions(sid);
  const latestCash = useDeskStatus().data?.market_data?.latest_cash_session;
  const [dialog, setDialog] = useState<NewSimInit | null>(null);
  const [modeNote, setModeNote] = useState<string | null>(null);
  const [shown, setShown] = useState(10);
  const [wfPick, setWfPick] = useState<string | null>(null);

  // The timeline is read incrementally; fetch the new events whenever the clock moves or the status changes.
  const seen = useRef<string | null>(null);
  useEffect(() => {
    const k = `${sid}|${sim?.step_seq}|${sim?.status}`;
    if (seen.current !== null && seen.current !== k && sim) tlQ.refetch();
    seen.current = k;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sid, sim?.step_seq, sim?.status]);
  useEffect(() => { setShown(10); setWfPick(null); setModeNote(null); act.reset(); /* new run on screen */ // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sid]);

  const cfg = configOf(sim);
  const res: SimResults | undefined = resultsQ.data;
  const sessions = sessionsOf(sim);
  const totalSteps = (configOf(sim).sessions?.length ?? res?.sessions_total ?? 0) * PHASES_PER_SESSION;
  const status = sim?.status ?? "";
  const bg = !!sim?.background_run;
  const accelerated = sim?.mode === "ACCELERATED_REPLAY" || cfg.speed === "ACCELERATED";
  const terminal = ["STOPPED", "COMPLETED", "FAILED"].includes(status);
  const busy = act.isPending;

  // ── controls ──────────────────────────────────────────────────────────────────────────────────────────────────
  const playing = status === "RUNNING";
  const playT = !sim ? "Start" : status === "CREATED" ? "Start" : status === "RUNNING" ? "Pause" : status === "PAUSED" ? "Resume" : status === "COMPLETED" ? "Finished" : status === "STOPPED" ? "Stopped" : status === "FAILED" ? "Failed" : "Start";
  const canToggle = !!sim && !terminal && !busy;
  const toggle = () => {
    if (!canToggle) return;
    if (status === "CREATED") act.mutate(accelerated ? [{ action: "start" }, { action: "run" }] : [{ action: "start" }]);
    else if (status === "RUNNING") act.mutate([{ action: "pause" }]);
    else if (status === "PAUSED") act.mutate(accelerated ? [{ action: "resume" }, { action: "run" }] : [{ action: "resume" }]);
  };
  const canStep = !!sim && status === "RUNNING" && !bg && !busy;
  const canStop = !!sim && !terminal && !busy;

  const newInit = (mode: ReplayMode = "HISTORICAL_REPLAY"): NewSimInit => {
    const end = latestCash ?? previousWeekday(todayIST());
    return { name: "Desk replay", mode, start_date: previousWeekday(end), end_date: end, starting_capital_rs: 10000000, operating_mode: "AUTONOMOUS_PAPER", max_proposals_per_session: 5, symbols: [] };
  };
  const againInit = (): NewSimInit => ({
    name: (cfg.name ?? sim?.name ?? "Desk replay").slice(0, 120),
    mode: sim?.mode === "ACCELERATED_REPLAY" ? "ACCELERATED_REPLAY" : "HISTORICAL_REPLAY",
    start_date: cfg.start_date ?? sessions[0] ?? "",
    end_date: cfg.end_date ?? sessions[sessions.length - 1] ?? "",
    starting_capital_rs: num(cfg.starting_capital_rs) ?? 10000000,
    operating_mode: (cfg.operating_mode as NewSimInit["operating_mode"]) ?? "AUTONOMOUS_PAPER",
    max_proposals_per_session: cfg.max_proposals_per_session ?? 5,
    symbols: Array.isArray(cfg.symbols) ? cfg.symbols : [],
  });

  const onMode = (m: string) => {
    if (m === "SCENARIO" || m === "LIVE_SHADOW") { setModeNote(m); return; }
    setModeNote(null);
    setDialog(newInit(m as ReplayMode));
  };
  const activeMode = modeNote ?? sim?.mode ?? null;

  const exportRun = () => {
    if (!sim || !res) return;
    const blob = new Blob([JSON.stringify({ simulation: sim, results: res }, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${sim.simulation_id}-results.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };

  // ── derived blocks ────────────────────────────────────────────────────────────────────────────────────────────
  const st = STATUS[status] ?? STATUS.CREATED;
  const prog = totalSteps ? Math.min(1, (sim?.step_seq ?? 0) / totalSteps) : 0;
  const ticks = sessions.length > 1 ? sessions.slice(1).map((_, i) => ((i + 1) * PHASES_PER_SESSION) / totalSteps) : [];
  const workflows = wfQ.data ?? [];
  const pm = useMemo(() => {
    const p = workflows.filter((w) => w.kind === "PREMARKET_CHECK");
    return p.find((w) => w.session_date === sim?.clock_session) ?? p.sort((a, b) => (b.session_date ?? "").localeCompare(a.session_date ?? ""))[0];
  }, [workflows, sim?.clock_session]);
  const pmRep = ((pm?.outcome ?? {}) as Record<string, unknown>).premarket as { status?: string; data_as_of?: Record<string, string | null>; allowed_segments?: string[] } | undefined;
  const mkt = [
    { k: "CASH DATA AS OF", v: pmRep?.data_as_of?.cash_eod ? dateShort(pmRep.data_as_of.cash_eod) : DASH, d: pmRep ? "POINT IN TIME" : "AFTER THE FIRST STEP", c: "var(--ink-3)" },
    { k: "F&O DATA AS OF", v: pmRep?.data_as_of?.fno_eod ? dateShort(pmRep.data_as_of.fno_eod) : DASH, d: pmRep ? "POINT IN TIME" : "AFTER THE FIRST STEP", c: "var(--ink-3)" },
    { k: "PRE-MARKET", v: pmRep?.status ?? DASH, d: pmRep?.allowed_segments ? (pmRep.allowed_segments.join(" · ") || "NO SEGMENTS") : DASH, c: pmRep?.status === "READY" ? "var(--mint)" : pmRep?.status ? "var(--amber)" : "var(--ink-3)" },
  ];

  const ag = res?.agents ?? {};
  const failedN = Object.values(ag).reduce((s, a) => s + (a.failed || 0) + (a.escalated || 0), 0);
  const retriedN = Object.values(ag).reduce((s, a) => s + (a.retried || 0), 0);
  const p2 = "Phase 2 · needs paper execution";
  const counters: { k: string; v: string; s: string; c: string; testId: string }[] = res ? [
    { k: "Signals", v: String(res.signals.total), s: countsText(res.signals.by_status, true), c: "var(--ink)", testId: "ctr-signals" },
    { k: "Proposals", v: String(res.plans.total), s: countsText(res.plans.by_strategy), c: "var(--ink)", testId: "ctr-plans" },
    { k: "Risk checks", v: String(ag.RISK_OPS?.tasks ?? 0), s: `Risk & Operations · ${ag.RISK_OPS?.completed ?? 0} completed · ${ag.RISK_OPS?.failed ?? 0} failed`, c: "var(--ink)", testId: "ctr-risk" },
    { k: "Approvals", v: String(sum(res.approvals.by_status)), s: [countsText(res.approvals.by_status, true), Object.entries(res.approvals.by_decider).map(([k, n]) => `${n} by ${who(k === "user" ? "user:" : k)}`).join(" · ")].filter((x) => x && x !== DASH).join(" · ") || DASH, c: "var(--ink)", testId: "ctr-approvals" },
    { k: "Orders", v: DASH, s: p2, c: "var(--ink-3)", testId: "ctr-p2" },
    { k: "Positions", v: DASH, s: p2, c: "var(--ink-3)", testId: "ctr-p2" },
    { k: "Stop · target · trail", v: DASH, s: p2, c: "var(--ink-3)", testId: "ctr-p2" },
    { k: "Capital deployed", v: DASH, s: p2, c: "var(--ink-3)", testId: "ctr-p2" },
    { k: "Exceptions", v: String(failedN), s: `${retriedN} retried · ${res.premarket?.BLOCKED ?? 0} pre-market blocked`, c: failedN ? "var(--amber)" : "var(--ink)", testId: "ctr-exceptions" },
    { k: "Policy violations", v: String(res.policy_violation_attempts), s: "Tool or look-ahead refusals", c: res.policy_violation_attempts ? "var(--danger)" : "var(--mint)", testId: "ctr-violations" },
  ] : [];

  const tl = tlQ.data;
  const latest = tl?.latestByAgent ?? {};
  const agents = AGENT_ORDER.map((k) => {
    const a = agentsQ.data?.agents?.[k];
    const r = ag[k];
    const bad = (r?.failed ?? a?.by_state?.FAILED ?? 0) + (r?.escalated ?? a?.by_state?.ESCALATED ?? 0);
    const tasks = a?.tasks ?? r?.tasks ?? 0;
    return {
      key: k, n: who(k), t: latest[k] ?? (tasks ? `${tasks} tasks` : "No tasks in this run yet"),
      meta: `${tasks} TASK${tasks === 1 ? "" : "S"} · ${a?.by_state?.COMPLETED ?? r?.completed ?? 0} COMPLETED · ${bad} FAILED${(agentsQ.data?.versions ?? res?.versions)?.agents?.[k] ? ` · ${(agentsQ.data?.versions ?? res?.versions)!.agents![k]}` : ""}`,
      c: bad ? "var(--amber)" : tasks ? "var(--mint)" : "var(--ink-3)",
    };
  });

  const events = useMemo(() => [...(tl?.shown ?? [])].reverse(), [tl]);
  const exceptions = useMemo(() => [...(tl?.exceptions ?? [])].reverse(), [tl]);
  const doneTasks = useMemo(() => new Set(tl?.completedTasks ?? []), [tl]);
  const tfmt = (iso: string | null) => (iso ? timeIST(iso, { seconds: false }) : "…");

  const tps = workflows.filter((w: WorkflowRow) => w.kind === "TRADE_PROPOSAL").sort((a, b) => b.created_at.localeCompare(a.created_at));
  const wid = wfPick && tps.some((w) => w.workflow_id === wfPick) ? wfPick : tps[0]?.workflow_id ?? null;
  const wdQ = useWorkflowDetail(wid, tick);
  const nodes = graphNodes(wdQ.data);
  const wOut = (wdQ.data?.workflow?.outcome ?? {}) as Record<string, unknown>;
  const policy = (sim?.versions as SimResults["versions"] | null)?.policy ?? res?.versions?.policy;

  const twoCols = mobile ? "minmax(0,1fr)" : "minmax(0,1.15fr) minmax(0,1fr)";
  const headline = !sim ? "No replay yet." : `${status === "COMPLETED" ? "Replayed" : "Replaying"} ${rangeText(sim)} ${accelerated ? "accelerated" : "phase by phase"}.`;

  return (
    <div data-testid="screen-sim" style={{ display: "flex", flexDirection: "column", gap: 20, fontFamily: "var(--sans)", color: "var(--ink)" }}>
      <section style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
          <Eyebrow>{screenNo("sim")} · Trading desk simulator</Eyebrow>
          <span className="nv-pill nv-pill-indigo"><span className="nv-dot" style={{ background: "var(--indigo)" }} />Simulated · isolated · no broker route</span>
          {sim && <span className="nv-pill" data-testid="sim-id-pill" style={{ maxWidth: "100%", overflowWrap: "anywhere" }}>{sim.simulation_id} · seed {cfg.seed ?? DASH}</span>}
        </div>
        <h1 data-testid="sim-headline" style={{ margin: 0, fontFamily: "var(--display)", fontWeight: 400, fontSize: mobile ? 30 : 44, lineHeight: 1.06, letterSpacing: "-0.02em", textWrap: "pretty", maxWidth: 920 } as CSSProperties}>
          {headline} <em style={{ color: "var(--indigo)" }}>No order can reach a broker</em> from here.
        </h1>
        <p style={{ margin: 0, fontSize: 14.5, lineHeight: 1.55, color: "var(--ink-3)", maxWidth: 700 }}>
          The same agents, policies and approval rules run against a point-in-time replay of past sessions: each phase sees only the data
          published by then. Phase 1 has no orders, so plans end at approval. Every record carries the simulation ID.
        </p>
      </section>

      <section style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
        {MODES.map(([v, t]) => {
          const on = activeMode === v;
          return (
            <span key={v} role="button" tabIndex={0} data-testid={`mode-${v}`} onClick={() => onMode(v)} onKeyDown={(e) => { if (e.key === "Enter") onMode(v); }}
              style={{ cursor: "pointer", padding: "8px 14px", borderRadius: 999, border: `1px solid ${on ? "var(--indigo-line)" : "var(--line-2)"}`, background: on ? "var(--indigo-soft)" : "transparent", color: on ? "var(--indigo)" : "var(--ink-2)", fontSize: 13 }}>{t}</span>
          );
        })}
        <span style={{ flex: 1 }} />
        {(listQ.data?.length ?? 0) > 0 && (
          <select data-testid="sim-picker" aria-label="Simulation run" value={sid ?? ""} onChange={(e) => navigate(`/simulator/${encodeURIComponent(e.target.value)}`)}
            style={{ padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--ink)", fontSize: 12.5, maxWidth: "100%", minWidth: 0 }}>
            {sid && !listQ.data!.some((x) => x.simulation_id === sid) && <option value={sid}>{sid}</option>}
            {listQ.data!.map((x: SimulationRow) => <option key={x.simulation_id} value={x.simulation_id}>{x.name} · {x.status.toLowerCase()} · {dateShort(x.created_at)}</option>)}
          </select>
        )}
        <button type="button" data-testid="new-sim" onClick={() => setDialog(newInit())} style={{ ...btn, height: 34, borderColor: "var(--indigo-line)", color: "var(--indigo)", background: "var(--indigo-soft)" }}>New simulation…</button>
      </section>
      {modeNote && (
        <PhaseNote phase={modeNote === "SCENARIO" ? 3 : 4} testId="mode-note">
          {modeNote === "SCENARIO"
            ? "Scenario simulation (injected gaps, broker drops, reject storms, stale chains, LLM outages) comes in Phase 3; the API refuses SCENARIO runs today."
            : "Live shadow (agents follow today's live session with a hypothetical book) comes in Phase 4; the API refuses LIVE_SHADOW runs today."}
        </PhaseNote>
      )}
      {listQ.error && <ErrorBox error={listQ.error} what="the simulations" onRetry={() => listQ.refetch()} />}

      <section data-testid="sim-controls" style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center", padding: "10px 12px", borderRadius: 16, border: "1px solid var(--line-2)", background: "var(--bg-glass)", backdropFilter: "blur(20px) saturate(140%)", WebkitBackdropFilter: "blur(20px) saturate(140%)", boxShadow: "var(--shadow-pop)" } as CSSProperties}>
        <button type="button" data-testid="sim-toggle" onClick={toggle} disabled={!canToggle}
          style={{ ...off(canToggle), cursor: canToggle ? "pointer" : "not-allowed", minWidth: 92, height: 38, padding: "0 16px", borderRadius: 10, border: 0, background: playing ? "var(--bg-3)" : "var(--indigo)", color: playing ? "var(--ink)" : "#0A0E1A", fontSize: 13.5, fontWeight: 500 }}>{busy ? "…" : playT}</button>
        <button type="button" data-testid="sim-stop" onClick={() => canStop && act.mutate([{ action: "stop" }])} disabled={!canStop}
          style={{ ...btn, ...off(canStop), border: "1px solid var(--danger-line)", background: "transparent", color: "var(--danger)" }}>Stop</button>
        <button type="button" data-testid="sim-again" onClick={() => sim && setDialog(againInit())} disabled={!sim} style={{ ...btn, ...off(!!sim) }}>Replay again…</button>
        <button type="button" data-testid="sim-step-phase" onClick={() => canStep && act.mutate([{ action: "step", body: { unit: "PHASE" } }])} disabled={!canStep} style={{ ...btn, ...off(canStep) }}>Step phase</button>
        <button type="button" data-testid="sim-step-session" onClick={() => canStep && act.mutate([{ action: "step", body: { unit: "SESSION" } }])} disabled={!canStep} style={{ ...btn, ...off(canStep) }}>Step session</button>
        <button type="button" data-testid="sim-run" onClick={() => canStep && act.mutate([{ action: "run" }])} disabled={!canStep} style={{ ...btn, ...off(canStep) }}>Run to end</button>
        <div data-testid="sim-speeds" title="Speed multipliers need an intraday replay; Phase 1 replays phase by phase." style={{ display: "flex", gap: 2, padding: 3, borderRadius: 999, background: "var(--bg-2)" }}>
          {[1, 10, 30, 60].map((v) => (
            <button key={v} type="button" disabled aria-disabled="true" style={{ cursor: "not-allowed", opacity: 0.45, border: 0, padding: "6px 11px", borderRadius: 999, background: "transparent", color: "var(--ink-2)", fontFamily: "var(--mono)", fontSize: 10.5 }}>{v}×</button>
          ))}
        </div>
        <span style={{ flex: 1 }} />
        <select data-testid="scenario-select" disabled aria-label="Scenario (Phase 3)" title="Scenario injection is Phase 3" defaultValue="gap"
          style={{ cursor: "not-allowed", opacity: 0.45, padding: "9px 12px", borderRadius: 10, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--ink)", fontSize: 13, minWidth: 0, maxWidth: "100%" }}>
          {SCENARIOS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
        </select>
        <button type="button" data-testid="sim-inject" disabled title="Scenario injection is Phase 3" style={{ ...btn, ...off(false), border: "1px solid var(--amber-line)", background: "var(--amber-soft)", color: "var(--amber)" }}>Inject scenario</button>
        <button type="button" data-testid="sim-export" onClick={exportRun} disabled={!sim || !res} style={{ ...btn, ...off(!!sim && !!res), background: "transparent", color: "var(--ink-2)" }}>Export</button>
      </section>
      <PhaseNote phase={3} testId="controls-note">
        Speed multipliers and scenario injection are not in Phase 1: the replay moves one phase at a time (pre-market 08:30 to end of day 18:00) on
        end-of-day data, and scenario simulation comes in Phase 3. Step phase, Step session and Run to end move the clock.
      </PhaseNote>
      {act.error && <div role="alert" data-testid="sim-action-error" style={{ padding: "11px 14px", borderRadius: 12, border: "1px solid var(--danger-line)", background: "var(--danger-soft)", fontSize: 13, color: "var(--ink-2)" }}>{errorText(act.error)}</div>}

      {status === "STOPPED" && sim && (
        <div data-testid="stopped-banner" style={{ padding: "11px 14px", borderRadius: 12, border: "1px solid var(--danger-line)", background: "var(--danger-soft)", fontSize: 13, color: "var(--ink-2)" }}>
          Stopped at {sim.clock_sim_time ? `${timeIST(sim.clock_sim_time)} on ${dateShort(sim.clock_session)}` : "the start"} ({sim.clock_phase ?? "no phase run"}, step {sim.step_seq} of {totalSteps}). The clock stays where it is and no further step
          runs; nothing outside the simulation was touched.
        </div>
      )}
      {status === "FAILED" && sim && (
        <div data-testid="failed-banner" style={{ padding: "11px 14px", borderRadius: 12, border: "1px solid var(--danger-line)", background: "var(--danger-soft)", fontSize: 13, color: "var(--ink-2)" }}>
          The run failed and stopped moving: {sim.error ?? "no error recorded"}
        </div>
      )}

      {!sid && listQ.isSuccess && (
        <div data-testid="sim-empty" style={{ display: "flex", flexDirection: "column", gap: 10, padding: "18px 20px", borderRadius: 14, border: "1px dashed var(--line-2)", fontSize: 14, lineHeight: 1.55, color: "var(--ink-3)" }}>
          <span>No simulation yet. Create one to replay past sessions with the desk's agents and policy; it runs in its own simulation account.</span>
          <span><button type="button" className="ad-link" onClick={() => setDialog(newInit())}>New simulation ›</button></span>
        </div>
      )}
      {(listQ.isLoading || simQ.isLoading) && <Loading label="Loading the simulation" />}
      {simQ.error && <ErrorBox error={simQ.error} what="this simulation" onRetry={() => simQ.refetch()} />}

      {sim && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: mobile ? "minmax(0,1fr)" : "minmax(300px,1fr) minmax(0,1.5fr)", gap: 16, alignItems: "stretch" }}>
            <section data-testid="sim-clock" style={{ display: "flex", flexDirection: "column", gap: 14, padding: "20px 22px", borderRadius: 14, border: "1px solid var(--indigo-line)", background: "var(--bg-1)", boxShadow: "var(--shadow-card)", minWidth: 0 }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap", alignItems: "baseline" }}>
                <span className="nv-eyebrow">Simulation clock · {sim.clock_session ? dateLong(sim.clock_session) : "not started"}</span>
                <span className="nv-pill" data-testid="sim-status" style={{ color: st.c, borderColor: st.l }}>{st.t}{bg && status === "RUNNING" ? " · RUN TO END" : ""}</span>
              </div>
              <span className="nv-num" data-testid="sim-clock-time" style={{ fontFamily: "var(--display)", fontSize: mobile ? 48 : 68, lineHeight: 1, letterSpacing: "-0.01em" }}>{sim.clock_sim_time ? timeIST(sim.clock_sim_time) : "--:--:--"}</span>
              <div style={{ position: "relative", height: 8, borderRadius: 4, background: "var(--bg-3)" }}>
                <span data-testid="sim-progress" style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${(prog * 100).toFixed(1)}%`, borderRadius: 4, background: "var(--indigo)" }} />
                {ticks.map((t, i) => <span key={i} style={{ position: "absolute", left: `${(t * 100).toFixed(1)}%`, top: -4, bottom: -4, borderLeft: "1px dashed var(--ink-3)" }} />)}
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8, fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-3)" }}>
                <span>{sessions[0] ? dateShort(sessions[0]).toUpperCase() : DASH}</span>
                <span data-testid="sim-step" style={{ textAlign: "center" }}>{sim.clock_phase ?? "NO STEP YET"} · STEP {sim.step_seq} OF {totalSteps || DASH}</span>
                <span>{sessions.length ? dateShort(sessions[sessions.length - 1]).toUpperCase() : DASH}</span>
              </div>
              <div data-testid="sim-data-asof" style={{ display: "grid", gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: 10, paddingTop: 6, borderTop: "1px solid var(--line)" }}>
                {mkt.map((k) => (
                  <div key={k.k} style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
                    <span style={{ fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.08em", color: "var(--ink-3)" }}>{k.k}</span>
                    <span className="nv-num" style={{ fontSize: 15, color: k.k === "PRE-MARKET" ? k.c : "var(--ink)" }}>{k.v}</span>
                    <span className="nv-num" style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--ink-3)", overflowWrap: "anywhere" }}>{k.d}</span>
                  </div>
                ))}
              </div>
            </section>
            <section data-testid="sim-counters" style={{ display: "grid", gridTemplateColumns: `repeat(auto-fill,minmax(${mobile ? "140px" : "150px"},1fr))`, gap: 10, alignContent: "start" }}>
              {resultsQ.error && <div style={{ gridColumn: "1 / -1" }}><ErrorBox error={resultsQ.error} what="the run's results" onRetry={() => resultsQ.refetch()} /></div>}
              {resultsQ.isLoading && <div style={{ gridColumn: "1 / -1" }}><Loading rows={2} label="Loading results" /></div>}
              {counters.map((c) => (
                <div key={c.k} data-testid={c.testId} style={{ display: "flex", flexDirection: "column", gap: 4, padding: "12px 14px", borderRadius: 12, border: "1px solid var(--line)", background: "var(--bg-1)" }}>
                  <span className="nv-eyebrow" style={{ fontSize: 9 }}>{c.k}</span>
                  <span className="nv-num" style={{ fontFamily: "var(--display)", fontSize: 22, lineHeight: 1.1, color: c.c }}>{c.v}</span>
                  <span style={{ fontSize: 11, color: "var(--ink-3)" }}>{c.s}</span>
                </div>
              ))}
            </section>
          </div>

          <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <span className="nv-eyebrow">Agents in this run</span>
            {agentsQ.error && <ErrorBox error={agentsQ.error} what="the agents of this run" onRetry={() => agentsQ.refetch()} />}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,190px),1fr))", gap: 10 }}>
              {agents.map((g) => (
                <div key={g.key} data-testid="sim-agent" style={{ display: "flex", flexDirection: "column", gap: 6, padding: "12px 14px", borderRadius: 12, border: "1px solid var(--line)", background: "var(--bg-1)", minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}><span className="nv-dot" style={{ background: g.c }} /><span style={{ fontSize: 13.5, fontWeight: 500 }}>{g.n}</span></div>
                  <span style={{ fontSize: 12, lineHeight: 1.45, color: "var(--ink-3)", overflowWrap: "anywhere" }}>{g.t}</span>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.06em", color: "var(--ink-3)", overflowWrap: "anywhere" }}>{g.meta}</span>
                </div>
              ))}
            </div>
          </section>

          <div style={{ display: "grid", gridTemplateColumns: twoCols, gap: 16, alignItems: "start" }}>
            <section data-testid="sim-comms" style={{ ...box, boxShadow: "var(--shadow-card)", minWidth: 0 }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", paddingBottom: 8 }}>
                <span style={h24}>Agent communication</span><span className="nv-eyebrow" style={{ fontSize: 9.5 }}>Structured messages · newest first</span>
              </div>
              {tlQ.error && <ErrorBox error={tlQ.error} what="the timeline" onRetry={() => tlQ.refetch()} />}
              {tlQ.isLoading && <Loading rows={2} label="Loading the timeline" />}
              {tl && events.length === 0 && <span style={{ fontSize: 13, color: "var(--ink-3)", padding: "9px 0", borderTop: "1px solid var(--line)" }}>No events yet. Start the run and step it.</span>}
              {events.slice(0, shown).map((e) => {
                const d = describe(e);
                const at = simTimeOf(e, tl?.clockSeqs ?? []);
                return (
                  <div key={e.seq} data-testid="comm-row" style={{ display: "grid", gridTemplateColumns: "62px minmax(0,1fr)", gap: 10, padding: "9px 0", borderTop: "1px solid var(--line)", alignItems: "baseline" }}>
                    <span className="nv-num" title={at ?? "in the phase now running"} style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-3)", display: "flex", flexDirection: "column", gap: 1 }}>
                      <span>{tfmt(at)}</span>{at && <span style={{ fontSize: 9.5, color: "var(--ink-4)" }}>{dateShort(at)}</span>}
                    </span>
                    <div style={{ display: "flex", flexDirection: "column", gap: 3, minWidth: 0 }}>
                      <span style={{ fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.06em", color: TONE_COLOR[d.tone], overflowWrap: "anywhere" }}>{d.route.toUpperCase()} · {d.type}</span>
                      {d.text && <span style={{ fontSize: 13, lineHeight: 1.45, overflowWrap: "anywhere" }}>{d.text}</span>}
                    </div>
                  </div>
                );
              })}
              {events.length > shown && (
                <span style={{ paddingTop: 8, borderTop: "1px solid var(--line)" }}>
                  <button type="button" className="ad-link" data-testid="comm-more" onClick={() => setShown((n) => n + 20)}>Show {Math.min(20, events.length - shown)} more ›</button>
                </span>
              )}
              {tl && tl.total > 0 && <span data-testid="comm-count" style={{ paddingTop: 8, fontFamily: "var(--mono)", fontSize: 9.5, color: "var(--ink-4)" }}>{tl.total} EVENTS READ · {tl.shown.length} IN THIS LIST{tl.total > tl.shown.length ? " · TASK HOPS AND OLDER EVENTS LEFT OUT" : ""}</span>}
            </section>

            <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
              <section data-testid="sim-pnl" style={{ ...box, gap: 12, padding: "18px 20px 14px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "baseline" }}>
                  <span style={h24}>Simulated P&amp;L</span><span className="nv-num" style={{ fontFamily: "var(--mono)", fontSize: 11.5, color: "var(--ink-3)" }}>NO FILLS IN PHASE 1</span>
                </div>
                <PhaseNote testId="pnl-phase-note">The P&amp;L curve after simulated costs, slippage and latency needs paper fills, which come in Phase 2. Approved plans in this run are not filled.</PhaseNote>
                {res && res.limitations.length > 0 && (
                  <div data-testid="sim-limitations" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    <span className="nv-eyebrow" style={{ fontSize: 9.5 }}>What this replay does not model</span>
                    <ul style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 4, fontSize: 12, lineHeight: 1.45, color: "var(--ink-3)" }}>
                      {res.limitations.map((l, i) => <li key={i}>{l}</li>)}
                    </ul>
                  </div>
                )}
              </section>
              <section data-testid="sim-exceptions" style={box}>
                <span style={{ ...h24, paddingBottom: 8 }}>Exceptions and recovery</span>
                {tl && exceptions.length === 0 && <span style={{ fontSize: 13, color: "var(--ink-3)", padding: "9px 0", borderTop: "1px solid var(--line)" }}>No exceptions in this run.</span>}
                {exceptions.slice(0, 8).map((x) => {
                  const recovered = !!x.taskId && doneTasks.has(x.taskId);
                  const c = recovered ? "var(--mint)" : x.st === "RETRY_PENDING" ? "var(--amber)" : "var(--danger)";
                  return (
                    <div key={x.key} data-testid="exception-row" style={{ display: "flex", flexDirection: "column", gap: 3, padding: "9px 0", borderTop: "1px solid var(--line)" }}>
                      <div style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
                        <span className="nv-num" style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-3)" }}>{tfmt(x.at ?? tl?.clockSeqs.find((c) => c.seq > x.seq)?.sim_time ?? null)}</span>
                        <span style={{ fontSize: 13, fontWeight: 500, flex: 1, minWidth: 0, overflowWrap: "anywhere" }}>{x.n}</span>
                        <span style={{ fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.06em", color: c }}>{recovered ? "RECOVERED" : x.st.replace(/_/g, " ")}</span>
                      </div>
                      <span style={{ fontSize: 12, lineHeight: 1.45, color: "var(--ink-3)", overflowWrap: "anywhere" }}>{x.r}</span>
                    </div>
                  );
                })}
                <div style={{ display: "flex", gap: 10, alignItems: "center", padding: "10px 0 0", borderTop: "1px solid var(--line)", flexWrap: "wrap" }}>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.08em", color: "var(--ink-3)" }}>FINAL RECONCILIATION</span>
                  <span data-testid="sim-recon" style={{ fontSize: 12.5, color: "var(--ink-2)" }}>Not in Phase 1 · there are no orders or fills to reconcile</span>
                </div>
              </section>
            </div>
          </div>

          <section data-testid="sim-graph" style={{ ...box, gap: 12 }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "baseline" }}>
              <span style={h24}>Workflow dependency graph</span>
              <span data-testid="graph-wf-id" style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--ink-3)", overflowWrap: "anywhere" }}>
                {wid ? `${wid}${wOut.trade_id ? ` · ${String(wOut.trade_id)} v${String(wOut.plan_version ?? "")}` : ""}${wOut.result ? ` · ${String(wOut.result)}` : ""}` : "NO TRADE PROPOSAL YET"}
              </span>
            </div>
            {tps.length > 1 && (
              <select data-testid="graph-wf" aria-label="Trade proposal workflow" value={wid ?? ""} onChange={(e) => setWfPick(e.target.value)}
                style={{ alignSelf: "flex-start", padding: "7px 10px", borderRadius: 10, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--ink)", fontSize: 12.5, maxWidth: "100%", minWidth: 0 }}>
                {tps.map((w) => <option key={w.workflow_id} value={w.workflow_id}>{dateShort(w.session_date)} · {String(((w.outcome ?? {}) as Record<string, unknown>).result ?? w.state)} · {w.workflow_id}</option>)}
              </select>
            )}
            {wdQ.error && <ErrorBox error={wdQ.error} what="the workflow" onRetry={() => wdQ.refetch()} />}
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
              {nodes.map((n, i) => {
                const p2n = n.tone === "phase2";
                const k = p2n ? ["var(--ink-4)", "var(--line-2)", "transparent"] : n.tone === "mint" ? ["var(--mint)", "var(--mint-line)", "var(--mint-soft)"] : n.tone === "indigo" ? ["var(--indigo)", "var(--indigo-line)", "var(--indigo-soft)"] : n.tone === "amber" ? ["var(--amber)", "var(--amber-line)", "var(--amber-soft)"] : n.tone === "danger" ? ["var(--danger)", "var(--danger-line)", "var(--danger-soft)"] : ["var(--ink-3)", "var(--line-2)", "transparent"];
                return (
                  <div key={n.n} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <div data-testid="graph-node" style={{ display: "flex", flexDirection: "column", gap: 3, padding: "9px 11px", borderRadius: 10, border: `1px ${p2n ? "dashed" : "solid"} ${k[1]}`, background: k[2], minWidth: 104 }}>
                      <span style={{ fontFamily: "var(--mono)", fontSize: 9, letterSpacing: "0.06em", color: k[0] }}>{n.n} · {n.st}</span>
                      <span style={{ fontSize: 12, lineHeight: 1.3, color: p2n ? "var(--ink-3)" : "var(--ink)" }}>{n.t}</span>
                    </div>
                    {i < nodes.length - 1 && <span style={{ color: "var(--ink-4)", fontSize: 12 }}>→</span>}
                  </div>
                );
              })}
            </div>
          </section>

          <div style={{ display: "grid", gridTemplateColumns: twoCols, gap: 16, alignItems: "start" }}>
            <section data-testid="sim-policy" style={box}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", paddingBottom: 8 }}>
                <span style={h24}>{policy ? `Policy v${policy.version} against a candidate` : "Policy against a candidate"}</span>
                <span className="nv-eyebrow" style={{ fontSize: 9.5 }}>Same market inputs · same seed</span>
              </div>
              <PhaseNote phase={4} testId="policy-phase-note">
                Replaying the same sessions under two policy versions with the same inputs and seed comes in Phase 4.
                {policy ? ` This run used policy ${policy.policy_id} v${policy.version} (sha256 ${String(policy.sha256).slice(0, 12)}…).` : ""}
              </PhaseNote>
            </section>
            <section data-testid="sim-gate" style={{ ...box, border: "1px solid var(--amber-line)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", paddingBottom: 8 }}>
                <span style={h24}>Live activation gate</span><span className="nv-pill nv-pill-amber">Not available</span>
              </div>
              <PhaseNote phase={4} testId="gate-phase-note">
                Scenario certifications (gap at the open, broker disconnect, partial and duplicate fills, stale data, LLM outage, expiry day) come with
                scenario simulation. Live trading is not in scope for this desk: brokers are read-only and every approval is paper or simulation only.
              </PhaseNote>
            </section>
          </div>
        </>
      )}

      {dialog && (
        <NewSimulationDialog init={dialog} onClose={() => setDialog(null)}
          onCreated={(id) => { setDialog(null); navigate(`/simulator/${encodeURIComponent(id)}`); }} />
      )}
    </div>
  );
}
