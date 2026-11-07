/**
 * Simulation studio · New simulation — built to the owner's design (docs/autodesk/design/prototype/studio/SimSetup.dc.html):
 * header, nine numbered sections (Mode, Session, Universe, Capital and account, Agent versions, Policy, Execution model,
 * Playback and seed, Scenario injections) and a sticky Run summary with "Create and start".
 *
 * Truth: the API runs HISTORICAL_REPLAY (stepped) and ACCELERATED_REPLAY (to the end in the background) of past
 * NSE sessions; SCENARIO (Phase 3) and LIVE_SHADOW (Phase 4) are refused, the execution model is fixed (simulated fills,
 * no broker; its assumptions cannot be set per run), no
 * scenario injection or checkpoint (Phase 3), no speed multiplier and no agent-version pinning. Those blocks keep their
 * place in the design and say so; nothing about them is sent. "Create and start" POSTs /simulations (SimulationConfig),
 * then /start (and /run for an accelerated replay), and opens the Trading day of the new run (/studio?sim=…).
 */
import { useMemo, useState, type CSSProperties } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { deskPost, errorText } from "../../api";
import { agentName, todayIST } from "../../format";
import { useDeskStatus, useIsMobile } from "../../hooks";
import { AGENT_ORDER, currentAgents, useAgentRegistry } from "../../screens/agents/model";
import { usePolicies, type PolicyRow } from "../../screens/policies/data";
import type { SimulationRow } from "../../types";
import { ErrorBox, Loading, PhaseNote } from "../../ui";
import {
  CAPITALS, MODES, OP_MODES, PLANS_PER_SESSION, REPLAY_MODES, capitalLabel, createBody, dayChip, defaultSessions, initialForm, modeLabel,
  opModeLabel, problemsOf, rangeLabel, recentWeekdays, resolve, type SetupForm,
} from "./setup/model";
import { NotInPhase1, Opt, SetupRow, SetupSection, field } from "./setup/parts";

const DISABLED_UNIVERSES = ["Nifty 50", "Nifty 200", "Nifty 500", "Index options"];

function defaultPolicy(rows: PolicyRow[] | undefined): PolicyRow | null {
  if (!rows?.length) return null;
  return rows.find((p) => p.scope_type === "TENANT") ?? rows[0];
}

export default function StudioSetup() {
  const mobile = useIsMobile();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [params] = useSearchParams();
  const sim = params.get("sim");
  const keep = sim ? `?sim=${encodeURIComponent(sim)}` : "";

  const status = useDeskStatus();
  const policies = usePolicies();
  const registry = useAgentRegistry();

  const [f, setF] = useState<SetupForm>(initialForm);
  const set = <K extends keyof SetupForm>(k: K, v: SetupForm[K]) => setF((p) => ({ ...p, [k]: v }));
  const [busy, setBusy] = useState(false);
  const [fail, setFail] = useState<{ error: unknown; createdId: string | null } | null>(null);

  const latestCash = status.data?.market_data?.latest_cash_session ?? null;
  const defaults = defaultSessions(latestCash, todayIST());
  const weekdays = recentWeekdays(defaults[1]);
  const r = resolve(f, defaults);
  const problems = problemsOf(f, r);
  const pol = defaultPolicy(policies.data);
  const policyId = f.policyId ?? pol?.policy_id ?? null;
  const policyRow = policies.data?.find((p) => p.policy_id === policyId) ?? null;
  const agents = useMemo(() => currentAgents(registry.data ?? []), [registry.data]);
  const allDeterministic = agents.size > 0 && Array.from(agents.values()).every((a) => a.kind === "DETERMINISTIC");
  const accelerated = f.mode === "ACCELERATED_REPLAY";
  const replay = REPLAY_MODES.has(f.mode);
  const body = createBody(f, r, policies.data ? policyId : null);

  const create = async () => {
    if (problems.length || busy) return;
    setBusy(true);
    setFail(null);
    let id: string | null = null;
    try {
      const row = await deskPost<SimulationRow>("/simulations", body);
      id = row.simulation_id;
      await deskPost<SimulationRow>(`/simulations/${encodeURIComponent(id)}/start`);
      if (accelerated) await deskPost<unknown>(`/simulations/${encodeURIComponent(id)}/run`);
      qc.invalidateQueries({ queryKey: ["desk"] });
      navigate(`/studio?sim=${encodeURIComponent(id)}`);
    } catch (e) {
      setFail({ error: e, createdId: id });
      if (id) qc.invalidateQueries({ queryKey: ["desk"] });
    } finally {
      setBusy(false);
    }
  };

  const summary: [string, string, string?][] = [
    ["Sessions", rangeLabel(r.start, r.end)],
    ["Universe", f.universe === "FNO" ? "F&O underlyings of each session" : `${r.symbols.length} symbol${r.symbols.length === 1 ? "" : "s"}`],
    ["Capital", capitalLabel(f.capital)],
    ["Account mode", opModeLabel(f.opMode)],
    ["Policy", policyRow ? `${policyRow.name} · v${policyRow.current_version}` : "Account default"],
    ["Agents", agents.size ? `${agents.size} current versions` : "Versions running at create time"],
    ["Plans per session", String(f.maxProposals)],
    ["Execution", "Simulated fills · no broker", "var(--ink-3)"],
    ["Injections", "None · Phase 3", "var(--ink-3)"],
    ["Seed", r.seed == null ? "—" : String(r.seed)],
    ["Playback", !replay ? "—" : accelerated ? "Runs to the end in the background" : "Stepped phase by phase"],
  ];

  const grid: CSSProperties = { display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,340px),1fr))", gap: 20, alignItems: "start" };

  return (
    <div data-testid="studio-new" style={{ display: "flex", flexDirection: "column", gap: 20, fontFamily: "var(--sans)", color: "var(--ink)" }}>
      <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
          <span className="nv-eyebrow" data-testid="setup-eyebrow">New simulation · id given on create</span>
          <span className="nv-pill">Draft</span>
        </div>
        <h1 data-testid="setup-headline" style={{ margin: 0, fontFamily: "var(--display)", fontWeight: 400, fontSize: "clamp(28px,4vw,44px)", lineHeight: 1.06, letterSpacing: "-0.02em", textWrap: "pretty", maxWidth: 900 } as CSSProperties}>
          Set up a run. <em style={{ color: "var(--indigo)" }}>Same inputs and seed</em> give the same result, every time.
        </h1>
        <p style={{ margin: 0, fontSize: 14.5, lineHeight: 1.55, color: "var(--ink-3)", maxWidth: 700 }}>
          Every setting below is stored with the run, so it can be replayed or compared later. A run places simulated orders only;
          live broker adapters are unreachable from a simulation.
        </p>
      </section>

      <div style={grid}>
        <div style={{ display: "flex", flexDirection: "column", gap: 14, minWidth: 0, gridColumn: mobile ? "1 / -1" : "span 2" }}>
          {/* 01 Mode */}
          <SetupSection n="01" t="Mode" s="Simulation modes never place broker orders" testId="setup-mode">
            <SetupRow k="Run type">
              {MODES.map((m) => <Opt key={m.v} on={f.mode === m.v} t={m.t} sub={m.sub} rad="12px" onPick={() => set("mode", m.v)} testId={`setup-mode-${m.v}`} />)}
            </SetupRow>
            {f.mode === "SCENARIO" && <PhaseNote phase={3} testId="setup-mode-note">Scenario simulations (synthetic shocks on a base session) arrive with Phase 3; the API refuses SCENARIO today, so nothing can be created in this mode.</PhaseNote>}
            {f.mode === "LIVE_SHADOW" && <PhaseNote phase={4} testId="setup-mode-note">Live shadow (today's live data, hypothetical book) arrives with Phase 4; the API refuses LIVE_SHADOW today, so nothing can be created in this mode.</PhaseNote>}
          </SetupSection>

          {/* 02 Session */}
          <SetupSection n="02" t="Session" s="Point-in-time data only" testId="setup-session">
            <SetupRow k="Trading day">
              {weekdays.map((d) => (
                <Opt key={d} on={r.start === d && r.end === d} t={dayChip(d)} onPick={() => setF((p) => ({ ...p, start: d, end: d }))} testId={`setup-day-${d}`} />
              ))}
            </SetupRow>
            <SetupRow k="First · last session">
              <input type="date" aria-label="First session" data-testid="setup-start" value={r.start} onChange={(e) => set("start", e.target.value)} style={field} />
              <span style={{ color: "var(--ink-3)" }}>→</span>
              <input type="date" aria-label="Last session" data-testid="setup-end" value={r.end} onChange={(e) => set("end", e.target.value)} style={field} />
            </SetupRow>
            <SetupRow k="Include">
              <Opt on={false} disabled t="Pre-open auction" sub="Not in Phase 1" testId="setup-preopen" title="Decisions use the previous session's end-of-day data" />
              <Opt on={false} disabled t="Post-close reconciliation" sub="Not in Phase 1" testId="setup-postclose" title="Not a setting yet: each run's results record a capital reconciliation" />
            </SetupRow>
            <span data-testid="setup-session-note" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--ink-3)" }}>
              Each session walks 08:30 pre-market → 08:45 scan → 09:00 proposals → 09:15 open → 15:30 close → 18:00 end of day, on the previous
              session's end-of-day data. Up to 30 sessions per run; NSE sessions of 2026 only (the holiday list has no other year).
              {status.error ? ` Latest session unknown (${errorText(status.error)}); the default uses the previous weekday.` : ""}
            </span>
          </SetupSection>

          {/* 03 Universe */}
          <SetupSection n="03" t="Universe" s={f.universe === "FNO" ? "F&O underlyings of each session" : `${r.symbols.length} symbol${r.symbols.length === 1 ? "" : "s"}`} testId="setup-universe">
            <SetupRow k="Scan">
              {DISABLED_UNIVERSES.slice(0, 3).map((u) => <Opt key={u} on={false} disabled t={u} sub="Not a separate universe in Phase 1" testId="setup-uni-disabled" />)}
              <Opt on={f.universe === "FNO"} t="F&O stocks" sub="Underlyings with futures that session" onPick={() => set("universe", "FNO")} testId="setup-uni-FNO" />
              <Opt on={false} disabled t={DISABLED_UNIVERSES[3]} sub="Not a separate universe in Phase 1" testId="setup-uni-disabled" />
              <Opt on={f.universe === "SYMBOLS"} t="Your symbols" sub="Up to 50; overrides the F&O list" onPick={() => set("universe", "SYMBOLS")} testId="setup-uni-SYMBOLS" />
            </SetupRow>
            {f.universe === "SYMBOLS" && (
              <SetupRow k="Symbols">
                <input data-testid="setup-symbols" aria-label="Symbols" value={f.symbolsText} placeholder="e.g. RELIANCE, INFY" onChange={(e) => set("symbolsText", e.target.value)} style={{ ...field, flex: 1, minWidth: 180 }} />
              </SetupRow>
            )}
          </SetupSection>

          {/* 04 Capital and account */}
          <SetupSection n="04" t="Capital and account" s="Its own simulation account" testId="setup-capital">
            <SetupRow k="Simulated capital">
              {CAPITALS.map((c) => <Opt key={c} on={f.capital === c} t={capitalLabel(c)} onPick={() => set("capital", c)} testId={`setup-cap-${c}`} />)}
            </SetupRow>
            <SetupRow k="Account mode">
              {OP_MODES.map((m) => <Opt key={m.v} on={f.opMode === m.v} t={m.t} sub={m.sub} onPick={() => set("opMode", m.v)} testId={`setup-op-${m.v}`} />)}
            </SetupRow>
          </SetupSection>

          {/* 05 Agent versions */}
          <SetupSection n="05" t="Agent versions" s="Model and prompt versions are stored with the run" testId="setup-agents">
            {registry.isLoading && <Loading label="Loading the agents" rows={1} />}
            {registry.error && <ErrorBox error={registry.error} what="the agent registry" onRetry={() => registry.refetch()} />}
            {registry.data && AGENT_ORDER.map((k) => {
              const a = agents.get(k);
              return (
                <SetupRow key={k} k={agentName(k)} testId="setup-agent-row">
                  {a ? <Opt on t={a.version} sub={a.kind === "DETERMINISTIC" ? "Deterministic" : `LLM-assisted${a.model ? ` · ${a.model}` : ""}`} testId={`setup-agent-${k}`} />
                    : <span style={{ fontSize: 12.5, color: "var(--ink-3)" }}>Not registered</span>}
                </SetupRow>
              );
            })}
            <NotInPhase1 testId="setup-agents-note">A run uses the agent versions running when it is created and stores them with the run; choosing another version is not available.</NotInPhase1>
          </SetupSection>

          {/* 06 Policy */}
          <SetupSection n="06" t="Policy" s="Same seed makes A/B fair" testId="setup-policy">
            {policies.isLoading && <Loading label="Loading the policies" rows={1} />}
            {policies.error && <ErrorBox error={policies.error} what="the policies" onRetry={() => policies.refetch()} />}
            {policies.data && (
              <SetupRow k="Policy set">
                {policies.data.map((p) => (
                  <Opt key={p.policy_id} on={p.policy_id === policyId} t={`${p.name} · v${p.current_version}`} sub={p.policy_id === pol?.policy_id ? "Account default" : undefined}
                    onPick={() => set("policyId", p.policy_id)} testId={`setup-policy-${p.policy_id}`} />
                ))}
              </SetupRow>
            )}
            <SetupRow k="Plans per session">
              {PLANS_PER_SESSION.map((n) => <Opt key={n} on={f.maxProposals === n} t={String(n)} onPick={() => set("maxProposals", n)} testId={`setup-plans-${n}`} />)}
            </SetupRow>
          </SetupSection>

          {/* 07 Execution model */}
          <SetupSection n="07" t="Execution model" s="Costs and frictions" testId="setup-execution">
            <PhaseNote label="Fixed for now" testId="setup-execution-note">
              Approved plans become simulated orders, filled from each session's daily row; none is sent to a broker. These assumptions are fixed and
              cannot be changed per run yet. Half spread: 0.05% on shares, 0.02% on futures, 0.50% on options (at least one tick). Slippage: 3, 2 and 20
              basis points on shares, futures and options, scaled by a seeded factor between 0.5 and 1.5. At most 10% of the session's traded quantity
              fills, in whole lots, so large orders fill in part. Latency: 50 to 400 ms on the simulated clock. Shares and futures that open more than
              20% from the previous close, or more than 10% from the plan's price, are rejected. Costs follow the desk cost card. The same seed gives the same fills.
            </PhaseNote>
          </SetupSection>

          {/* 08 Playback and seed */}
          <SetupSection n="08" t="Playback and seed" s="Stored with the run" testId="setup-playback">
            <SetupRow k="Playback">
              {replay ? <Opt on t={accelerated ? "To the end" : "Step by step"} sub={accelerated ? "Runs in the background after start" : "You advance each phase"} testId="setup-playback-mode" />
                : <span style={{ fontSize: 12.5, color: "var(--ink-3)" }}>—</span>}
            </SetupRow>
            <NotInPhase1 testId="setup-speed-note">Speed multipliers (1×–600×) and checkpoints are not available: Phase 1 replays each session phase by phase on end-of-day data.</NotInPhase1>
            <SetupRow k={`Random seed · ${r.seed ?? "—"}`}>
              <input data-testid="setup-seed" aria-label="Seed" inputMode="numeric" value={f.seed} onChange={(e) => set("seed", e.target.value.replace(/[^\d]/g, ""))} style={{ ...field, width: 110 }} />
              <Opt on={false} t="Re-roll seed" onPick={() => set("seed", String(1000 + Math.floor(Math.random() * 9000)))} testId="setup-reroll" />
            </SetupRow>
            {allDeterministic && <span data-testid="setup-seed-note" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--ink-3)" }}>All five agents are deterministic in this version, so the seed does not change their output; it is stored so runs can be matched in Run history.</span>}
          </SetupSection>

          {/* 09 Scenario injections */}
          <SetupSection n="09" t="Scenario injections" testId="setup-scenarios"
            right={<Link to={`/studio/scenarios${keep}`} data-testid="setup-scen-link" style={{ cursor: "pointer", fontSize: 12.5, color: "var(--mint)", textDecoration: "none" }}>Edit in scenario library ›</Link>}>
            <PhaseNote phase={3} testId="setup-scenarios-note">
              Scenario injections arrive with Phase 3; the API refuses scenario runs today, so nothing is scheduled or sent. No injections scheduled: the run replays the
              sessions as they happened.
            </PhaseNote>
          </SetupSection>
        </div>

        <aside data-testid="setup-summary" style={{ position: mobile ? "static" : "sticky", top: 96, display: "flex", flexDirection: "column", gap: 12, padding: "18px 20px", borderRadius: 16, border: "1px solid var(--indigo-line)", background: "var(--bg-1)", boxShadow: "var(--shadow-card)", minWidth: 0 }}>
          <span className="nv-eyebrow">Run summary</span>
          <input data-testid="setup-name" aria-label="Run name" value={f.name ?? r.title} maxLength={120} onChange={(e) => set("name", e.target.value)}
            style={{ fontFamily: "var(--display)", fontSize: 26, lineHeight: 1.15, color: "var(--ink)", background: "transparent", border: 0, borderBottom: "1px dashed var(--line-2)", padding: "0 0 4px", width: "100%", minWidth: 0 }} />
          <span style={{ fontSize: 11.5, color: "var(--ink-3)", marginTop: -6 }}>{modeLabel(f.mode)} · the name is yours to change</span>
          {summary.map(([k, v, c]) => (
            <div key={k} data-testid="setup-summary-row" style={{ display: "flex", justifyContent: "space-between", gap: 10, padding: "7px 0", borderTop: "1px solid var(--line)", fontSize: 12.5 }}>
              <span style={{ color: "var(--ink-3)" }}>{k}</span>
              <span className="nv-num" style={{ textAlign: "right", color: c ?? "var(--ink)" }}>{v}</span>
            </div>
          ))}
          <div style={{ display: "flex", gap: 8, alignItems: "center", padding: "10px 12px", borderRadius: 10, background: "var(--indigo-soft)", fontSize: 12, lineHeight: 1.45, color: "var(--ink-2)" }}>
            <span style={{ fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.08em", color: "var(--indigo)", flex: "none" }}>ISOLATED</span>
            Records carry the run's simulation_id; live broker adapters are unreachable.
          </div>
          {problems.length > 0 && <span data-testid="setup-problems" style={{ fontSize: 12.5, lineHeight: 1.45, color: "var(--amber)" }}>Needs {problems.join(", ")}.</span>}
          {fail && (
            <div role="alert" data-testid="setup-error" style={{ display: "flex", flexDirection: "column", gap: 6, padding: "10px 12px", borderRadius: 10, border: "1px solid var(--danger-line)", background: "var(--danger-soft)", fontSize: 13, lineHeight: 1.5, color: "var(--ink-2)" }}>
              <span className="nv-eyebrow" style={{ color: "var(--danger)" }}>{fail.createdId ? "Created, but not started" : "Not created"}</span>
              <span>{errorText(fail.error)}</span>
              {fail.createdId && <Link to={`/studio?sim=${encodeURIComponent(fail.createdId)}`} data-testid="setup-open-created" style={{ fontSize: 12.5, color: "var(--mint)" }}>Open the run in Trading day ›</Link>}
            </div>
          )}
          <button type="button" data-testid="setup-create" onClick={create} disabled={problems.length > 0 || busy}
            style={{ cursor: problems.length || busy ? "not-allowed" : "pointer", opacity: problems.length || busy ? 0.55 : 1, padding: "12px 18px", borderRadius: 12, border: 0, background: "var(--indigo)", color: "#0A0E1A", fontSize: 14.5, fontWeight: 500, fontFamily: "var(--sans)" }}>
            {busy ? "Creating…" : "Create and start"}
          </button>
          <span style={{ fontSize: 11.5, color: "var(--ink-3)", textAlign: "center" }}>
            {accelerated ? "Starts the run, plays it to the end in the background and opens the trading day." : "Starts the run and opens the trading day; you step it from 08:30 pre-market."}
          </span>
        </aside>
      </div>
    </div>
  );
}
