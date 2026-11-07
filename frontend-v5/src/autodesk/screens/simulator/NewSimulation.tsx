/**
 * New simulation (POST /simulations with SimulationConfig). The form sends only the fields it shows; the rest keep the
 * API's defaults (universe FNO, seed 42, policy = the tenant's default). The API's own message is shown when it refuses
 * a range (no sessions, more than 30 sessions, a year without an NSE holiday list).
 */
import { useState, type CSSProperties } from "react";
import { errorText } from "../../api";
import { Modal } from "../../shell/dialogs";
import { Button } from "../../ui";
import { useCreateSimulation } from "./queries";

export type ReplayMode = "HISTORICAL_REPLAY" | "ACCELERATED_REPLAY";

export interface NewSimInit {
  name: string;
  mode: ReplayMode;
  start_date: string;
  end_date: string;
  starting_capital_rs: number;
  operating_mode: "AUTONOMOUS_PAPER" | "ASSISTED" | "RESEARCH";
  max_proposals_per_session: number;
  symbols: string[];
}

const field: CSSProperties = { width: "100%", padding: "9px 11px", borderRadius: 10, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--ink)", fontSize: 13.5, minWidth: 0 };
const lab: CSSProperties = { display: "flex", flexDirection: "column", gap: 5, minWidth: 0 };

/** The request body: exactly the fields the form sets (contracts simulator.create / create_symbols). */
export function simBody(v: NewSimInit): Record<string, unknown> {
  const b: Record<string, unknown> = {
    name: v.name.trim(),
    mode: v.mode,
    start_date: v.start_date,
    end_date: v.end_date,
    starting_capital_rs: v.starting_capital_rs,
    operating_mode: v.operating_mode,
    max_proposals_per_session: v.max_proposals_per_session,
    speed: v.mode === "ACCELERATED_REPLAY" ? "ACCELERATED" : "STEP",
  };
  if (v.symbols.length) b.symbols = v.symbols;
  return b;
}

export function NewSimulationDialog({ init, onClose, onCreated }: { init: NewSimInit; onClose: () => void; onCreated: (sid: string) => void }) {
  const m = useCreateSimulation();
  const [v, setV] = useState<NewSimInit>(init);
  const [cap, setCap] = useState(String(init.starting_capital_rs));
  const [maxP, setMaxP] = useState(String(init.max_proposals_per_session));
  const [syms, setSyms] = useState(init.symbols.join(", "));
  const set = <K extends keyof NewSimInit>(k: K, x: NewSimInit[K]) => setV((p) => ({ ...p, [k]: x }));

  const capN = Number(cap);
  const maxN = Number(maxP);
  const symbols = syms.split(/[\s,]+/).map((x) => x.trim().toUpperCase()).filter(Boolean);
  const problems: string[] = [];
  if (!v.name.trim() || v.name.trim().length > 120) problems.push("a name of 1–120 characters");
  if (!v.start_date || !v.end_date) problems.push("both dates");
  else if (v.end_date < v.start_date) problems.push("an end date on or after the start date");
  if (!Number.isFinite(capN) || capN <= 0) problems.push("a starting capital above ₹0");
  if (!Number.isInteger(maxN) || maxN < 0 || maxN > 50) problems.push("0–50 plans per session");
  if (symbols.length > 50) problems.push("at most 50 symbols");

  const submit = () => {
    if (problems.length) return;
    const body = simBody({ ...v, starting_capital_rs: capN, max_proposals_per_session: maxN, symbols });
    m.mutate(body, { onSuccess: (row) => onCreated(row.simulation_id) });
  };

  const chip = (mode: ReplayMode, label: string) => {
    const on = v.mode === mode;
    return (
      <span key={mode} role="button" tabIndex={0} data-testid={`new-mode-${mode}`} onClick={() => set("mode", mode)} onKeyDown={(e) => { if (e.key === "Enter") set("mode", mode); }}
        style={{ cursor: "pointer", padding: "7px 12px", borderRadius: 999, border: `1px solid ${on ? "var(--indigo-line)" : "var(--line-2)"}`, background: on ? "var(--indigo-soft)" : "transparent", color: on ? "var(--indigo)" : "var(--ink-2)", fontSize: 12.5 }}>{label}</span>
    );
  };

  return (
    <Modal title="New simulation" onClose={onClose} testId="new-sim-dialog" tone="ink">
      <span style={{ fontSize: 13, lineHeight: 1.55, color: "var(--ink-2)" }}>
        Replays past NSE sessions with the same agents and policy, phase by phase on the data published by each phase. It runs in its own
        simulation account; nothing reaches a broker.
      </span>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>{chip("HISTORICAL_REPLAY", "Historical replay")}{chip("ACCELERATED_REPLAY", "Accelerated replay")}</div>
      <span style={{ fontSize: 12, lineHeight: 1.45, color: "var(--ink-3)" }}>
        {v.mode === "HISTORICAL_REPLAY" ? "You step it phase by phase or a session at a time." : "Start runs it to the end in the background; pause or stop at any time."}
      </span>
      <label style={lab}><span className="nv-eyebrow">Name</span>
        <input data-testid="new-name" value={v.name} maxLength={120} onChange={(e) => set("name", e.target.value)} style={field} /></label>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <label style={lab}><span className="nv-eyebrow">First session</span>
          <input data-testid="new-start" type="date" value={v.start_date} onChange={(e) => set("start_date", e.target.value)} style={field} /></label>
        <label style={lab}><span className="nv-eyebrow">Last session</span>
          <input data-testid="new-end" type="date" value={v.end_date} onChange={(e) => set("end_date", e.target.value)} style={field} /></label>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <label style={lab}><span className="nv-eyebrow">Starting capital (₹)</span>
          <input data-testid="new-capital" inputMode="numeric" value={cap} onChange={(e) => setCap(e.target.value.replace(/[^\d]/g, ""))} style={field} /></label>
        <label style={lab}><span className="nv-eyebrow">Plans per session</span>
          <input data-testid="new-max" inputMode="numeric" value={maxP} onChange={(e) => setMaxP(e.target.value.replace(/[^\d]/g, ""))} style={field} /></label>
      </div>
      <label style={lab}><span className="nv-eyebrow">Operating mode</span>
        <select data-testid="new-opmode" value={v.operating_mode} onChange={(e) => set("operating_mode", e.target.value as NewSimInit["operating_mode"])} style={field}>
          <option value="AUTONOMOUS_PAPER">Auto paper — the Middle Office approves inside the policy</option>
          <option value="ASSISTED">Assisted — every plan waits for a person</option>
          <option value="RESEARCH">Research — plans and risk reports, nothing approved</option>
        </select></label>
      <label style={lab}><span className="nv-eyebrow">Symbols (optional, default: the F&amp;O universe)</span>
        <input data-testid="new-symbols" value={syms} placeholder="e.g. RELIANCE, INFY" onChange={(e) => setSyms(e.target.value)} style={field} /></label>
      {problems.length > 0 && <span data-testid="new-problems" style={{ fontSize: 12.5, color: "var(--amber)" }}>Needs {problems.join(", ")}.</span>}
      {m.error && <span role="alert" data-testid="new-error" style={{ fontSize: 13, lineHeight: 1.5, color: "var(--danger)" }}>{errorText(m.error)}</span>}
      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <Button onClick={onClose}>Cancel</Button>
        <Button kind="primary" testId="new-create" disabled={problems.length > 0 || m.isPending} onClick={submit}>{m.isPending ? "Creating…" : "Create"}</Button>
      </div>
    </Modal>
  );
}
