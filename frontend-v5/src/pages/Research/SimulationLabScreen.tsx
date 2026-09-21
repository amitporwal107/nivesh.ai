/**
 * Research → Simulation Lab. Built to research/sim_diag/lab_template.html (the owner's design, in the V5 design
 * language) and to the pre-registration docs/ai_research/tpd3/sim_diag/PREREGISTRATION_SIM_MATRIX.md.
 *
 * Rules this screen keeps:
 *   · Every number on the page comes from /api/sim-lab/* — that is, from the frozen run's committed snapshot.
 *     Nothing is computed here, nothing is carried over between runs, and a field the snapshot does not have renders
 *     as "—", never as a guess. A 503 (snapshot missing or malformed) shows the unavailable state, never a partial
 *     table.
 *   · Only accounts with features.sim_lab see it; the API independently answers 403, and a 403 anywhere clears every
 *     cached payload before the "not enabled" state renders (the MoveOddsScreen convention).
 *   · Descriptive, never a recommendation: no configuration in the matrix is a candidate strategy (pre-registration
 *     §1), and the secondary rows sit below the matrix, never used to pick a winner.
 *   · A "% of ₹5,00,000" or "max drawdown %" figure is valid only for the portfolio runs (D, F). Fixed-notional runs
 *     get per-trade and rupee totals plus the peak capital required, and their worst stretch is labelled
 *     "worst cumulative net" — never "drawdown" (pre-registration §5).
 *   · Internal only: the prices behind it are Kite-derived and are not for redistribution.
 *
 * Units, as the contract and the owner's design define them: rates and returns (win_rate, *_per_trade, cost_drag,
 * *_hit_rate, median_mfe/mae, net_ret, mfe_pct, mae_pct, mean_diff, ci95, max_drawdown_pct, return_on_capital_pct)
 * are FRACTIONS and are rendered ×100; `atr_pct` is already in percent (the design prints it raw under an "ATR %"
 * header); any other number is printed as the API sent it.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError } from "@/services/api/errors";
import { http } from "@/services/api/http";
import {
  RUN_SPEC_BLOCK_RULES, RUN_SPEC_SCHEMA, RUN_SPEC_STEPS, RUN_SPEC_VARIANTS, type RunSpecVariantId,
} from "./simRunSpec";

/* ══════════════════════════════════════════════════════════════════════════
   Contract — backend/services/sim_lab.py, schema "sim-lab-1"
   ══════════════════════════════════════════════════════════════════════════ */
type Json = Record<string, unknown>;
export type Scope = "year" | "replay";

interface Head {
  schema: string;
  generated_at: string;
  source_sha256: string;
  run_id: string | null;
  fixture: boolean;
}

interface DQSession extends Json {
  date: string;
  status?: string | null;
  fail_reasons?: string[];
  special_session?: string | null;
  missing_count?: number | null;
  flags?: Json;
}

interface ReconClass extends Json {
  class?: string;
  trades?: number;
  side?: string;
  what?: string;
}

interface RunPayload extends Head {
  run: Json;
  sessions: {
    year: { count: number; first: string; last: string };
    replay: { count: number; dates: string[] };
  };
  scorecard: Record<Scope, Json>;
  data_quality: { year: Json; replay: Json; sessions: DQSession[] };
  reconciliation: { summary: Json; classes: ReconClass[] };
  rc1: Record<Scope, Record<string, number>>;
  trade_configs: string[];
  notes: Json;
}

interface MatrixBlock {
  runs: Record<string, Json>;
  secondary: Record<string, Json>;
  portfolio_variants: Json[];
  random_control: Json;
  rank_bands: Record<string, Json>;
}
interface MatrixPayload extends Head { scope: Scope; matrix: MatrixBlock }
interface TradesPayload extends Head { config: string; scope: Scope; count: number; rows: Json[] }
interface CandidatesPayload extends Head { date: string; count: number; rows: Json[] }

type Result<T> =
  | { kind: "ok"; data: T }
  | { kind: "no_access" }
  | { kind: "unavailable" }
  | { kind: "error"; message: string };

async function get<T>(path: string, query?: Record<string, string>): Promise<Result<T>> {
  try {
    const res = await http<{ data?: T }>({ path, query, noRetry: true });
    const body = res.data;
    if (!body || typeof body !== "object" || body.data == null) return { kind: "error", message: "unexpected response shape" };
    return { kind: "ok", data: body.data };
  } catch (e) {
    if (e instanceof ApiError) {
      if (e.status === 403) return { kind: "no_access" };
      if (e.status === 503) return { kind: "unavailable" };
      return { kind: "error", message: e.detail || (e.status ? `HTTP ${e.status}` : e.message) };
    }
    return { kind: "error", message: e instanceof Error ? e.message : "unexpected response" };
  }
}

/* ══════════════════════════════════════════════════════════════════════════
   Formatting — a missing value is "—", never a substitute
   ══════════════════════════════════════════════════════════════════════════ */
const DASH = "—";
const MINUS = "−";

function isNum(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}
/** Rupees. `d` decimals; the sign is a real minus, not a hyphen. */
function inr(v: unknown, d = 0): string {
  if (!isNum(v)) return DASH;
  const s = Math.abs(v).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
  return `${v < 0 ? MINUS : ""}₹${s}`;
}
/** A fraction rendered as a percentage (0.0052 → 0.52%). */
function frac(v: unknown, d = 2): string {
  if (!isNum(v)) return DASH;
  return `${v < 0 ? MINUS : ""}${Math.abs(v * 100).toFixed(d)}%`;
}
function num(v: unknown, d = 2): string {
  if (!isNum(v)) return DASH;
  return `${v < 0 ? MINUS : ""}${Math.abs(v).toFixed(d)}`;
}
function int(v: unknown): string {
  return isNum(v) ? Math.round(v).toLocaleString("en-IN") : DASH;
}
function txt(v: unknown): string {
  if (v == null) return DASH;
  if (typeof v === "boolean") return v ? "yes" : "no";
  const s = String(v);
  return s.trim() === "" ? DASH : s;
}
function humanKey(k: string): string {
  return k.replace(/_/g, " ").replace(/\bpct\b/, "%").replace(/\binr\b/, "₹");
}
/** Fixed month names — browsers disagree on "Sep" vs "Sept" (the MoveOddsScreen convention). */
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function day(iso: unknown): string {
  if (typeof iso !== "string" || iso.length < 10) return DASH;
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return String(iso);
  return `${d} ${MON[m - 1]} ${y}`;
}
function sha(v: unknown, n = 16): string {
  return typeof v === "string" && v.length > n ? `${v.slice(0, n)}…` : txt(v);
}
function sign(v: unknown): string {
  return isNum(v) ? (v > 0 ? "var(--mint)" : v < 0 ? "var(--danger-hex)" : "var(--c-ink)") : "var(--c-ink-3)";
}

/** Keys the contract defines as fractions — everything else prints as sent. */
const FRACTION_KEYS = new Set([
  "win_rate", "gross_per_trade", "net_per_trade", "cost_drag", "slippage_per_trade", "charges_per_trade",
  "stop_hit_rate", "target_hit_rate", "median_mfe", "median_mae", "net_ret", "mfe_pct", "mae_pct",
  "mean_diff", "share_better", "max_drawdown_pct", "return_on_capital_pct", "mean_net_per_trade", "p05", "p95",
  "ambiguous_bar_share", "losers_beyond_1_5R_share", "share_of_absolute_pnl_in_extremes",
]);

/** Generic value rendering for the snapshot blocks whose inner shape the contract leaves open. */
function autoValue(key: string, v: unknown): string {
  if (v == null) return DASH;
  if (Array.isArray(v)) {
    if (!v.length) return "none";
    return v.map((x) => (isNum(x) && FRACTION_KEYS.has(key) ? frac(x) : txt(x))).join(", ");
  }
  if (isNum(v)) {
    if (key.endsWith("_inr")) return inr(v);
    if (FRACTION_KEYS.has(key)) return frac(v);
    return Number.isInteger(v) ? int(v) : num(v, 3);
  }
  return txt(v);
}

/* ══════════════════════════════════════════════════════════════════════════
   Small building blocks (V5 globals: nv-card, nv-pill, nv-eyebrow, nv-serif)
   ══════════════════════════════════════════════════════════════════════════ */
function Eyebrow({ children }: { children: React.ReactNode }) {
  return <div className="nv-eyebrow" style={{ marginBottom: 8 }}>{children}</div>;
}

function Card({ children, testid, pad = 20 }: { children: React.ReactNode; testid?: string; pad?: number }) {
  return (
    <section className="nv-card" data-testid={testid} style={{ padding: pad, minWidth: 0 }}>
      {children}
    </section>
  );
}

function Pill({ children, tone }: { children: React.ReactNode; tone?: "mint" | "amber" | "danger" | "indigo" }) {
  return <span className={`nv-pill${tone ? ` nv-pill-${tone}` : ""}`}>{children}</span>;
}

/** label / value rows — the design's .kv. */
function KV({ rows, testid }: { rows: Array<[string, React.ReactNode]>; testid?: string }) {
  return (
    <dl
      data-testid={testid}
      style={{
        display: "grid", gridTemplateColumns: "minmax(120px, max-content) minmax(0, 1fr)",
        gap: "6px 16px", margin: 0, fontSize: 13,
      }}
    >
      {rows.map(([k, v]) => (
        <div key={k} style={{ display: "contents" }}>
          <dt className="nv-mono" style={{ fontSize: 10.5, letterSpacing: ".06em", textTransform: "uppercase", color: "var(--c-ink-3)", paddingTop: 2 }}>
            {k}
          </dt>
          <dd style={{ margin: 0, color: "var(--c-ink)", wordBreak: "break-word" }}>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Every scalar field of an object the contract leaves open-shaped, printed as the API sent it. */
function AutoKV({ obj, testid, skip }: { obj: Json | undefined | null; testid?: string; skip?: string[] }) {
  const rows = useMemo(() => {
    if (!obj) return [] as Array<[string, React.ReactNode]>;
    const hide = new Set(skip ?? []);
    return Object.entries(obj)
      .filter(([k]) => !hide.has(k))
      .map(([k, v]): [string, React.ReactNode] => {
        if (v && typeof v === "object" && !Array.isArray(v)) {
          const inner = Object.entries(v as Json).map(([ik, iv]) => `${humanKey(ik)} ${autoValue(ik, iv)}`).join(" · ");
          return [humanKey(k), <span className="nv-mono" style={{ fontSize: 11.5 }}>{inner || "none"}</span>];
        }
        return [humanKey(k), autoValue(k, v)];
      });
  }, [obj, skip]);
  if (!rows.length) return <Empty testid={testid}>Not in this snapshot.</Empty>;
  return <KV rows={rows} testid={testid} />;
}

function TableWrap({ children, testid, min = 720, label }: {
  children: React.ReactNode; testid?: string; min?: number; label?: string;
}) {
  return (
    <div
      data-testid={testid}
      tabIndex={0}
      role="region"
      aria-label={label ?? "Table — scrolls sideways"}
      style={{ overflowX: "auto", border: "1px solid var(--c-line)", borderRadius: 12, background: "var(--bg-1)", maxWidth: "100%" }}
    >
      <table style={{ borderCollapse: "collapse", width: "100%", minWidth: min, fontSize: 12 }}>{children}</table>
    </div>
  );
}

const TH: React.CSSProperties = {
  fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: ".1em", textTransform: "uppercase",
  color: "var(--c-ink-3)", fontWeight: 500, textAlign: "left", padding: "9px 10px",
  background: "var(--bg-2)", whiteSpace: "nowrap",
};
const TD: React.CSSProperties = {
  padding: "8px 10px", borderTop: "1px solid var(--c-line)", color: "var(--c-ink-2)",
  whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums",
};
const TD_R: React.CSSProperties = { ...TD, textAlign: "right" };
const TH_R: React.CSSProperties = { ...TH, textAlign: "right" };

/** A list of open-shaped objects: columns are the union of the rows' own keys, in first-seen order. */
function AutoTable({ rows, testid, min, label }: { rows: Json[] | undefined; testid?: string; min?: number; label?: string }) {
  const cols = useMemo(() => {
    const seen: string[] = [];
    for (const r of rows ?? []) for (const k of Object.keys(r)) if (!seen.includes(k)) seen.push(k);
    return seen;
  }, [rows]);
  if (!rows || !rows.length) return <Empty testid={testid}>Not in this snapshot.</Empty>;
  return (
    <TableWrap testid={testid} min={min ?? Math.max(360, cols.length * 130)} label={label}>
      <thead>
        <tr>{cols.map((c) => <th key={c} scope="col" style={TH}>{humanKey(c)}</th>)}</tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i}>
            {cols.map((c) => <td key={c} style={isNum(r[c]) ? TD_R : TD}>{autoValue(c, r[c])}</td>)}
          </tr>
        ))}
      </tbody>
    </TableWrap>
  );
}

function Empty({ children, testid }: { children: React.ReactNode; testid?: string }) {
  return (
    <p data-testid={testid ? `${testid}-empty` : "sl-empty"} style={{ margin: 0, fontSize: 13, color: "var(--c-ink-3)" }}>
      {children}
    </p>
  );
}

function Note({ children, testid }: { children: React.ReactNode; testid?: string }) {
  return (
    <p
      data-testid={testid}
      style={{
        borderLeft: "3px solid var(--amber)", background: "var(--amber-soft)", borderRadius: "0 10px 10px 0",
        padding: "10px 14px", fontSize: 13, lineHeight: 1.55, color: "var(--c-ink-2)", margin: "14px 0 0",
      }}
    >
      {children}
    </p>
  );
}

function Grid({ children, wide }: { children: React.ReactNode; wide?: boolean }) {
  return (
    <div className={`grid gap-4 ${wide ? "lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]" : "lg:grid-cols-2"}`} style={{ alignItems: "start" }}>
      {children}
    </div>
  );
}

function ScopeSwitch({ scope, onChange }: { scope: Scope; onChange: (s: Scope) => void }) {
  return (
    <span role="group" aria-label="Scope" style={{ display: "inline-flex", gap: 4, flexWrap: "wrap" }}>
      {(["year", "replay"] as const).map((s) => (
        <button
          key={s}
          type="button"
          aria-pressed={scope === s}
          data-testid={`sl-scope-${s}`}
          onClick={() => onChange(s)}
          className="nv-mono"
          style={{
            fontSize: 10, letterSpacing: ".13em", textTransform: "uppercase", padding: "8px 13px", borderRadius: 999,
            cursor: "pointer", border: `1px solid ${scope === s ? "var(--mint-line)" : "var(--line-2)"}`,
            background: scope === s ? "var(--mint-soft)" : "transparent",
            color: scope === s ? "var(--mint)" : "var(--c-ink-2)",
          }}
        >
          {s === "year" ? "Full year" : "Replay window"}
        </button>
      ))}
    </span>
  );
}

function Select({ id, label, value, options, onChange, testid }: {
  id: string; label: string; value: string; options: Array<{ value: string; label: string }>;
  onChange: (v: string) => void; testid: string;
}) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
      <label htmlFor={id} className="nv-eyebrow">{label}</label>
      <select
        id={id}
        data-testid={testid}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="nv-mono"
        style={{
          fontSize: 11, padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line-2)",
          background: "var(--bg-2)", color: "var(--c-ink)", maxWidth: 280,
        }}
      >
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </span>
  );
}

function Toolbar({ children }: { children: React.ReactNode }) {
  return <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "10px 14px", marginBottom: 14 }}>{children}</div>;
}

/* ══════════════════════════════════════════════════════════════════════════
   Screen
   ══════════════════════════════════════════════════════════════════════════ */
const TABS = [
  { id: "run", label: "Run · frozen inputs" },
  { id: "matrix", label: "Matrix" },
  { id: "data", label: "Data quality" },
  { id: "candidates", label: "Candidate ledger" },
  { id: "trades", label: "Trade audit" },
  { id: "recon", label: "Reconciliation" },
  { id: "comparison", label: "Comparison" },
  { id: "runspec", label: "Run spec template" },
] as const;
type TabId = (typeof TABS)[number]["id"];

/** The one tab that is static reference content: it reads no API and needs no snapshot. */
const STATIC_TABS: ReadonlySet<string> = new Set<TabId>(["runspec"]);

/** What each run isolates, from the pre-registration's §4 matrix. Used only when the snapshot's run entry does not
 *  carry its own `purpose`; an unlisted key shows "—" rather than a guess. */
const PREREG_PURPOSE: Record<string, string> = {
  A: "baseline (reconciled in D3)",
  B: "stop / target",
  C: "entry",
  D: "sizing",
  E: "cost drag",
  F: "full realism",
  G: "selection vs execution",
  H: "the stop / target rule itself",
};

function purposeOf(key: string, entry: Json): string {
  const own = entry.purpose ?? entry.isolates;
  if (typeof own === "string" && own.trim()) return own;
  return PREREG_PURPOSE[key] ?? DASH;
}

/** The portfolio runs are the ones the snapshot gives capital-based figures for. Everything else is fixed-notional,
 *  where a "% of ₹5,00,000" or a "drawdown %" would be wrong (pre-registration §5). */
function isPortfolioRun(entry: Json): boolean {
  return entry.max_drawdown_inr != null || entry.max_drawdown_pct != null ||
    entry.final_equity_inr != null || entry.return_on_capital_pct != null;
}

export default function SimulationLabScreen() {
  const [tab, setTab] = useState<TabId>("run");
  const [scope, setScope] = useState<Scope>("year");
  const [noAccess, setNoAccess] = useState(false);
  const [reload, setReload] = useState(0);

  const [runRes, setRunRes] = useState<Result<RunPayload> | null>(null);
  const [matrixRes, setMatrixRes] = useState<Partial<Record<Scope, Result<MatrixPayload>>>>({});
  const [candDate, setCandDate] = useState<string>("");
  const [candRes, setCandRes] = useState<Record<string, Result<CandidatesPayload>>>({});
  const [tradeConfig, setTradeConfig] = useState<string>("");
  const [tradesRes, setTradesRes] = useState<Record<string, Result<TradesPayload>>>({});

  const [dqDate, setDqDate] = useState<string>("");
  const [cause, setCause] = useState<string>("ALL");
  const [openTrade, setOpenTrade] = useState<string | null>(null);
  const [openCand, setOpenCand] = useState<string | null>(null);
  const [openRun, setOpenRun] = useState<string | null>(null);

  /** 403 anywhere: drop every cached payload before the "not enabled" state renders. */
  const denyAll = useCallback(() => {
    setRunRes(null); setMatrixRes({}); setCandRes({}); setTradesRes({}); setNoAccess(true);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setRunRes(null);
    get<RunPayload>("/api/sim-lab/run").then((r) => {
      if (cancelled) return;
      if (r.kind === "no_access") { denyAll(); return; }
      setNoAccess(false);
      setRunRes(r);
      if (r.kind === "ok") {
        setCandDate((cur) => (cur && r.data.sessions.replay.dates.includes(cur) ? cur : r.data.sessions.replay.dates[0] ?? ""));
        setDqDate((cur) => (cur && r.data.data_quality.sessions.some((s) => s.date === cur) ? cur : r.data.data_quality.sessions[0]?.date ?? ""));
        setTradeConfig((cur) => (cur && r.data.trade_configs.includes(cur) ? cur : r.data.trade_configs[0] ?? ""));
      }
    });
    return () => { cancelled = true; };
  }, [reload, denyAll]);

  const needsMatrix = tab === "matrix" || tab === "comparison" || tab === "trades";
  useEffect(() => {
    if (!needsMatrix || matrixRes[scope] !== undefined) return;
    let cancelled = false;
    get<MatrixPayload>("/api/sim-lab/matrix", { scope }).then((r) => {
      if (cancelled) return;
      if (r.kind === "no_access") { denyAll(); return; }
      setMatrixRes((m) => ({ ...m, [scope]: r }));
    });
    return () => { cancelled = true; };
  }, [needsMatrix, scope, matrixRes, denyAll]);

  useEffect(() => {
    if (tab !== "candidates" || !candDate || candRes[candDate] !== undefined) return;
    let cancelled = false;
    get<CandidatesPayload>("/api/sim-lab/candidates", { date: candDate }).then((r) => {
      if (cancelled) return;
      if (r.kind === "no_access") { denyAll(); return; }
      setCandRes((c) => ({ ...c, [candDate]: r }));
    });
    return () => { cancelled = true; };
  }, [tab, candDate, candRes, denyAll]);

  const tradeKey = `${tradeConfig}|${scope}`;
  useEffect(() => {
    if (tab !== "trades" || !tradeConfig || tradesRes[tradeKey] !== undefined) return;
    let cancelled = false;
    get<TradesPayload>("/api/sim-lab/trades", { config: tradeConfig, scope }).then((r) => {
      if (cancelled) return;
      if (r.kind === "no_access") { denyAll(); return; }
      setTradesRes((t) => ({ ...t, [tradeKey]: r }));
    });
    return () => { cancelled = true; };
  }, [tab, tradeConfig, scope, tradeKey, tradesRes, denyAll]);

  if (noAccess) {
    return (
      <Shell>
        <div className="nv-card" role="status" data-testid="sl-state-no_access" style={{ padding: 22 }}>
          <h3 className="nv-serif" style={{ fontSize: 20, margin: 0 }}>Simulation Lab is not enabled for your account</h3>
          <p style={{ fontSize: 13.5, color: "var(--c-ink-2)", margin: "8px 0 0" }}>
            It is an internal research surface, open to invited accounts only. The filings Feed and Alerts are unaffected.
          </p>
        </div>
      </Shell>
    );
  }

  // A static tab carries no run numbers, so it renders whatever the snapshot did — but only for an account that is
  // allowed on the page at all, which is why this sits below the 403 check.
  if (STATIC_TABS.has(tab) && (runRes === null || runRes.kind !== "ok")) {
    return (
      <Shell>
        <TabNav tab={tab} onTab={setTab} />
        <div id="sl-panel" role="tabpanel" aria-labelledby={`sl-tab-${tab}`} style={{ display: "grid", gap: 16, minWidth: 0 }}>
          {tab === "runspec" && <RunSpecTab />}
        </div>
      </Shell>
    );
  }

  if (runRes === null) {
    return (
      <Shell>
        <div className="nv-card" aria-busy="true" data-testid="sl-state-loading" style={{ padding: 22, display: "grid", gap: 10 }}>
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} style={{ height: 14, borderRadius: 6, background: "var(--bg-3)", width: `${92 - i * 9}%` }} />
          ))}
          <span className="sr-only">Loading the frozen run…</span>
        </div>
      </Shell>
    );
  }

  if (runRes.kind === "unavailable") {
    return (
      <Shell>
        {/* the strip stays so the tabs that need no snapshot are still reachable */}
        <TabNav tab={tab} onTab={setTab} />
        <div className="nv-card" role="alert" data-testid="sl-state-unavailable" style={{ padding: 22 }}>
          <h3 className="nv-serif" style={{ fontSize: 20, margin: 0 }}>The frozen run is not available</h3>
          <p style={{ fontSize: 13.5, color: "var(--c-ink-2)", margin: "8px 0 0" }}>
            The published snapshot is missing or did not match the expected schema, so nothing is shown. Partial
            numbers from a run that cannot be verified are never displayed.
          </p>
          <button type="button" className="nv-btn" data-testid="sl-retry" style={{ marginTop: 14 }} onClick={() => setReload((n) => n + 1)}>
            Try again
          </button>
        </div>
      </Shell>
    );
  }

  if (runRes.kind === "error") {
    return (
      <Shell>
        <TabNav tab={tab} onTab={setTab} />
        <div className="nv-card" role="alert" data-testid="sl-state-error" style={{ padding: 22 }}>
          <h3 className="nv-serif" style={{ fontSize: 20, margin: 0 }}>The run could not be loaded</h3>
          <p style={{ fontSize: 13.5, color: "var(--c-ink-2)", margin: "8px 0 0" }}>
            The service did not answer ({runRes.message}). No earlier numbers are shown.
          </p>
          <button type="button" className="nv-btn" data-testid="sl-retry" style={{ marginTop: 14 }} onClick={() => setReload((n) => n + 1)}>
            Try again
          </button>
        </div>
      </Shell>
    );
  }

  // `no_access` never reaches here — denyAll() clears the payload and flips `noAccess` above — but the compiler
  // cannot know that, and rendering nothing is the right answer if it ever did.
  if (runRes.kind !== "ok") return null;
  const d = runRes.data;
  const matrix = matrixRes[scope];
  const replayDates = d.sessions.replay.dates;

  return (
    <Shell>
      {d.fixture && (
        <div
          role="alert"
          data-testid="sl-banner-fixture"
          style={{
            border: "1px solid var(--danger-line)", background: "var(--danger-soft)", borderRadius: 12,
            padding: "12px 14px", color: "var(--c-ink)", fontSize: 13, lineHeight: 1.55,
          }}
        >
          <b className="nv-mono" style={{ fontSize: 10.5, letterSpacing: ".1em", marginRight: 8, color: "var(--danger-hex)" }}>
            DEVELOPMENT FIXTURE
          </b>
          This snapshot is placeholder data for building the page. It is <b>not the output of any simulation run</b>;
          no number below may be quoted, reported or acted on.
        </div>
      )}

      <div
        role="note"
        data-testid="sl-banner-internal"
        style={{
          border: "1px solid var(--c-line-strong)", borderRadius: 12, padding: "12px 14px", background: "var(--bg-1)",
          color: "var(--c-ink-2)", fontSize: 12.5, lineHeight: 1.55,
        }}
      >
        <b className="nv-mono" style={{ fontSize: 10.5, letterSpacing: ".1em", color: "var(--c-ink)", marginRight: 6 }}>INTERNAL ONLY</b>
        This page shows Kite-derived prices and frozen research runs on development data. Not for redistribution, and
        not investment advice. Every configuration here is descriptive — none is a candidate strategy.
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: "8px 10px", alignItems: "center" }}>
        <Pill tone="indigo">run {txt(d.run_id)}</Pill>
        <Pill>code {sha(d.run.code_commit, 8)}</Pill>
        <Pill>snapshot {sha(d.source_sha256, 12)}</Pill>
        <Pill>generated {txt(d.generated_at)}</Pill>
        {d.notes.internal_only === true && <Pill tone="amber">internal · Kite prices</Pill>}
      </div>

      <TabNav tab={tab} onTab={setTab} />

      <div id="sl-panel" role="tabpanel" aria-labelledby={`sl-tab-${tab}`} style={{ display: "grid", gap: 16, minWidth: 0 }}>
        {tab === "run" && <RunTab d={d} />}
        {tab === "matrix" && (
          <MatrixTab result={matrix} scope={scope} onScope={setScope} openRun={openRun} onOpenRun={setOpenRun} />
        )}
        {tab === "data" && <DataQualityTab d={d} date={dqDate} onDate={setDqDate} />}
        {tab === "candidates" && (
          <CandidatesTab
            dates={replayDates}
            date={candDate}
            onDate={(v) => { setCandDate(v); setOpenCand(null); }}
            result={candDate ? candRes[candDate] : undefined}
            open={openCand}
            onOpen={setOpenCand}
          />
        )}
        {tab === "trades" && (
          <TradesTab
            d={d}
            scope={scope}
            onScope={(s) => { setScope(s); setOpenTrade(null); }}
            config={tradeConfig}
            onConfig={(c) => { setTradeConfig(c); setOpenTrade(null); }}
            result={tradeConfig ? tradesRes[tradeKey] : undefined}
            matrix={matrix}
            cause={cause}
            onCause={(c) => { setCause(c); setOpenTrade(null); }}
            open={openTrade}
            onOpen={setOpenTrade}
          />
        )}
        {tab === "recon" && <ReconTab d={d} />}
        {tab === "comparison" && <ComparisonTab result={matrix} scope={scope} onScope={setScope} notes={d.notes} />}
        {tab === "runspec" && <RunSpecTab />}
      </div>
    </Shell>
  );
}

/** The tab strip, shared by the loaded screen and by the states that have no snapshot to show. */
function TabNav({ tab, onTab }: { tab: TabId; onTab: (t: TabId) => void }) {
  return (
    <nav
      role="tablist"
      aria-label="Simulation Lab sections"
      style={{ display: "flex", gap: 6, flexWrap: "wrap", borderBottom: "1px solid var(--c-line)", paddingBottom: 12 }}
    >
      {TABS.map((t) => (
        <button
          key={t.id}
          role="tab"
          id={`sl-tab-${t.id}`}
          aria-selected={tab === t.id}
          aria-controls="sl-panel"
          data-testid={`sl-tab-${t.id}`}
          onClick={() => onTab(t.id)}
          className="nv-mono"
          style={{
            fontSize: 10, letterSpacing: ".13em", textTransform: "uppercase", padding: "9px 14px", borderRadius: 999,
            cursor: "pointer", whiteSpace: "nowrap",
            border: `1px solid ${tab === t.id ? "var(--mint-line)" : "var(--line-2)"}`,
            background: tab === t.id ? "var(--mint-soft)" : "transparent",
            color: tab === t.id ? "var(--mint)" : "var(--c-ink-2)",
          }}
        >
          {t.label}
        </button>
      ))}
    </nav>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div
      data-testid="sim-lab-screen"
      className="px-4 pt-5 pb-10 lg:px-6"
      style={{ display: "grid", gap: 16, maxWidth: 1360, margin: "0 auto", minWidth: 0 }}
    >
      <div>
        <h2 className="nv-serif" style={{ fontSize: 30, lineHeight: 1.1, margin: 0 }}>Consecutive-Session Simulation Lab</h2>
        <p style={{ fontSize: 14, color: "var(--c-ink-2)", margin: "8px 0 0", maxWidth: "70ch" }}>
          The frozen simulation runs, trade by trade: what was run, how each configuration turned out, how the engine
          reconciles against the label code, and why each trade ended the way it did. Development data only; nothing
          here changes a model.
        </p>
      </div>
      {children}
    </div>
  );
}

/** One shared loading / unavailable / error block for the per-tab payloads. */
function Pending<T>({ result, label, children }: { result: Result<T> | undefined; label: string; children: (data: T) => React.ReactNode }) {
  if (result === undefined) {
    return (
      <Card testid={`sl-${label}-loading`}>
        <p aria-busy="true" style={{ margin: 0, fontSize: 13, color: "var(--c-ink-3)" }}>Loading {label}…</p>
      </Card>
    );
  }
  if (result.kind === "unavailable") {
    return (
      <Card testid={`sl-${label}-unavailable`}>
        <Eyebrow>{label}</Eyebrow>
        <p style={{ margin: 0, fontSize: 13, color: "var(--c-ink-2)" }} role="alert">
          The snapshot behind this section is missing or malformed, so nothing is shown.
        </p>
      </Card>
    );
  }
  if (result.kind === "error") {
    return (
      <Card testid={`sl-${label}-error`}>
        <Eyebrow>{label}</Eyebrow>
        <p style={{ margin: 0, fontSize: 13, color: "var(--c-ink-2)" }} role="alert">
          Could not be loaded ({result.message}). No earlier numbers are shown.
        </p>
      </Card>
    );
  }
  if (result.kind === "no_access") return null;
  return <>{children(result.data)}</>;
}

/* ── Run · frozen inputs ─────────────────────────────────────────────────── */
const RUN_SHOWN = ["id", "code_commit", "prereg", "prediction_commit", "dataset_sha256", "oof_sha256", "picks_sha256",
  "cost_model", "capital_inr", "block", "sealed_note", "intrabar_policy", "purpose"];

function RunTab({ d }: { d: RunPayload }) {
  const r = d.run;
  return (
    <>
      <Grid wide>
        <Card testid="sl-run-inputs">
          <Eyebrow>Frozen inputs · verified by sha256 before use</Eyebrow>
          <h3 className="nv-serif" style={{ fontSize: 20, margin: "0 0 12px" }}>Run {txt(r.id)}</h3>
          <KV
            testid="sl-run-kv"
            rows={[
              ["Code commit", <span className="nv-mono">{sha(r.code_commit, 12)}</span>],
              ["Predictions from", <span className="nv-mono">{sha(r.prediction_commit, 12)}</span>],
              ["Dataset", <span className="nv-mono">{sha(r.dataset_sha256)}</span>],
              ["Out-of-fold", <span className="nv-mono">{sha(r.oof_sha256)}</span>],
              ["Picks", <span className="nv-mono">{sha(r.picks_sha256)}</span>],
              ["Snapshot source", <span className="nv-mono">{sha(d.source_sha256)}</span>],
              ["Pre-registration", txt(r.prereg)],
              ["Cost model", txt(r.cost_model)],
              ["Capital", inr(r.capital_inr)],
              ["Intrabar policy", txt(r.intrabar_policy)],
            ]}
          />
          <div className="nv-hr" />
          <Eyebrow>Data block</Eyebrow>
          <KV rows={[["Block", txt(r.block)], ["Sealed block", txt(r.sealed_note)]]} />
          <div className="nv-hr" />
          <Eyebrow>Other fields in this snapshot</Eyebrow>
          <AutoKV obj={r} skip={RUN_SHOWN} testid="sl-run-extra" />
        </Card>

        <Card testid="sl-run-sessions">
          <Eyebrow>Sessions</Eyebrow>
          <KV
            rows={[
              ["Full year", `${int(d.sessions.year.count)} sessions · ${day(d.sessions.year.first)} → ${day(d.sessions.year.last)}`],
              ["Replay window", `${int(d.sessions.replay.count)} sessions`],
            ]}
          />
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 12 }} data-testid="sl-run-replay-dates">
            {d.sessions.replay.dates.map((x) => {
              const s = d.data_quality.sessions.find((y) => y.date === x);
              return <Pill key={x} tone={s?.special_session ? "amber" : undefined}>{x}</Pill>;
            })}
          </div>
          <div className="nv-hr" />
          <Eyebrow>Scorecard · thresholds fixed before the run</Eyebrow>
          <div style={{ display: "grid", gap: 12 }} data-testid="sl-run-scorecard">
            {(["year", "replay"] as const).map((s) => (
              <div key={s}>
                <div className="nv-mono" style={{ fontSize: 10.5, color: "var(--c-ink-3)", marginBottom: 6 }}>
                  {s === "year" ? "FULL YEAR" : "REPLAY WINDOW"}
                </div>
                <AutoKV obj={d.scorecard[s]} testid={`sl-scorecard-${s}`} />
              </div>
            ))}
          </div>
          <Note testid="sl-run-note">
            The scores are the pre-registered rubric applied unchanged; they are metrics, not a verdict on a strategy.
            A configuration that looks better here is a candidate for a fresh pre-registration and an out-of-sample
            test, never a rule to adopt.
          </Note>
        </Card>
      </Grid>

      <Card testid="sl-run-notes">
        <Eyebrow>How these numbers may be read</Eyebrow>
        <AutoKV obj={d.notes} />
      </Card>
    </>
  );
}

/* ── Matrix ──────────────────────────────────────────────────────────────── */
function pairedCell(entry: Json): React.ReactNode {
  const p = entry.paired_vs_A as Json | undefined;
  if (!p) return DASH;
  const ci = Array.isArray(p.ci95) ? (p.ci95 as unknown[]) : null;
  const range = ci && ci.length === 2 ? `[${frac(ci[0])}, ${frac(ci[1])}]` : DASH;
  return (
    <span>
      {frac(p.mean_diff)} <span style={{ color: "var(--c-ink-3)" }}>{range}</span>
    </span>
  );
}

const MATRIX_COLS: Array<{ h: string; r?: boolean; v: (k: string, e: Json) => React.ReactNode }> = [
  { h: "Run", v: (k) => <b style={{ color: "var(--c-ink)" }}>{k}</b> },
  { h: "Isolates", v: (k, e) => purposeOf(k, e) },
  { h: "Trades", r: true, v: (_k, e) => int(e.trades) },
  { h: "No entry", r: true, v: (_k, e) => int(e.no_entry) },
  { h: "Win rate", r: true, v: (_k, e) => frac(e.win_rate, 1) },
  { h: "Gross / trade", r: true, v: (_k, e) => frac(e.gross_per_trade) },
  { h: "Net / trade", r: true, v: (_k, e) => <span style={{ color: sign(e.net_per_trade) }}>{frac(e.net_per_trade)}</span> },
  { h: "Cost drag", r: true, v: (_k, e) => frac(e.cost_drag) },
  { h: "Profit factor", r: true, v: (_k, e) => num(e.profit_factor) },
  { h: "Expectancy", r: true, v: (_k, e) => inr(e.expectancy_inr) },
  { h: "Stop hit", r: true, v: (_k, e) => frac(e.stop_hit_rate, 1) },
  { h: "vs A · mean diff [95%]", r: true, v: (_k, e) => pairedCell(e) },
];

function MatrixTab({ result, scope, onScope, openRun, onOpenRun }: {
  result: Result<MatrixPayload> | undefined; scope: Scope; onScope: (s: Scope) => void;
  openRun: string | null; onOpenRun: (k: string | null) => void;
}) {
  return (
    <>
      <Toolbar>
        <ScopeSwitch scope={scope} onChange={onScope} />
        <Pill tone="indigo">descriptive · one run · nothing tuned between runs</Pill>
      </Toolbar>
      <Pending result={result} label="matrix">
        {(m) => {
          const runs = Object.entries(m.matrix.runs).sort(([a], [b]) => a.localeCompare(b));
          const secondary = Object.entries(m.matrix.secondary).sort(([a], [b]) => a.localeCompare(b));
          const bands = Object.entries(m.matrix.rank_bands).map(([band, v]) => ({ band, ...(v as Json) }));
          const open = openRun && m.matrix.runs[openRun] ? { key: openRun, entry: m.matrix.runs[openRun] } : null;
          return (
            <>
              <TableWrap testid="sl-matrix-table" min={1180} label="Matrix — runs A to H">
                <caption style={{ textAlign: "left", padding: "10px 12px", fontSize: 12, color: "var(--c-ink-3)", captionSide: "top" }}>
                  Runs A–H over the {scope === "year" ? "full year" : "replay window"}. The paired difference is over
                  the trades a run has in common with A, with a date-clustered bootstrap interval — descriptive, with
                  no p-value and no accept/reject. Select a row for that run&apos;s full record.
                </caption>
                <thead>
                  <tr>{MATRIX_COLS.map((c) => <th key={c.h} scope="col" style={c.r ? TH_R : TH}>{c.h}</th>)}</tr>
                </thead>
                <tbody>
                  {runs.map(([k, e]) => (
                    <tr
                      key={k}
                      data-testid={`sl-matrix-row-${k}`}
                      onClick={() => onOpenRun(openRun === k ? null : k)}
                      style={{ cursor: "pointer", background: openRun === k ? "var(--bg-2)" : undefined }}
                    >
                      {MATRIX_COLS.map((c) => <td key={c.h} style={c.r ? TD_R : TD}>{c.v(k, e)}</td>)}
                    </tr>
                  ))}
                </tbody>
              </TableWrap>

              {open && (
                <Card testid="sl-matrix-detail">
                  <Eyebrow>Run {open.key} · everything the snapshot holds</Eyebrow>
                  <AutoKV obj={open.entry} />
                </Card>
              )}

              <Card testid="sl-secondary">
                <Eyebrow>Secondary rows · one change each, reported below the matrix and never used to pick a winner</Eyebrow>
                {secondary.length === 0 ? (
                  <Empty testid="sl-secondary">No secondary rows in this snapshot.</Empty>
                ) : (
                  <TableWrap testid="sl-secondary-table" min={860} label="Secondary rows">
                    <thead>
                      <tr>
                        <th scope="col" style={TH}>Row</th>
                        <th scope="col" style={TH}>Change</th>
                        <th scope="col" style={TH_R}>Trades</th>
                        <th scope="col" style={TH_R}>Net / trade</th>
                        <th scope="col" style={TH_R}>Gross / trade</th>
                        <th scope="col" style={TH_R}>Cost drag</th>
                        <th scope="col" style={TH_R}>Profit factor</th>
                        <th scope="col" style={TH_R}>Stop hit</th>
                        <th scope="col" style={TH_R}>vs A · mean diff [95%]</th>
                      </tr>
                    </thead>
                    <tbody>
                      {secondary.map(([k, e]) => (
                        <tr key={k} data-testid={`sl-secondary-row-${k}`}>
                          <td style={TD}><b style={{ color: "var(--c-ink)" }}>{k}</b></td>
                          <td style={TD}>{purposeOf(k, e)}</td>
                          <td style={TD_R}>{int(e.trades)}</td>
                          <td style={{ ...TD_R, color: sign(e.net_per_trade) }}>{frac(e.net_per_trade)}</td>
                          <td style={TD_R}>{frac(e.gross_per_trade)}</td>
                          <td style={TD_R}>{frac(e.cost_drag)}</td>
                          <td style={TD_R}>{num(e.profit_factor)}</td>
                          <td style={TD_R}>{frac(e.stop_hit_rate, 1)}</td>
                          <td style={TD_R}>{pairedCell(e)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </TableWrap>
                )}
              </Card>

              <Grid>
                <Card testid="sl-random-control">
                  <Eyebrow>Control G · random selection under the same execution</Eyebrow>
                  <AutoKV obj={m.matrix.random_control} />
                </Card>
                <Card testid="sl-rank-bands">
                  <Eyebrow>Rank bands · does the score order outcomes at all</Eyebrow>
                  <AutoTable rows={bands} testid="sl-rank-bands-table" label="Rank bands" />
                </Card>
              </Grid>

              <Card testid="sl-portfolio-variants">
                <Eyebrow>Portfolio variants · a sensitivity table, not candidates</Eyebrow>
                <AutoTable rows={m.matrix.portfolio_variants} testid="sl-variants-table" label="Portfolio variants" />
              </Card>
            </>
          );
        }}
      </Pending>
    </>
  );
}

/* ── Data quality ────────────────────────────────────────────────────────── */
function DataQualityTab({ d, date, onDate }: { d: RunPayload; date: string; onDate: (v: string) => void }) {
  const sessions = d.data_quality.sessions;
  const session = sessions.find((s) => s.date === date) ?? sessions[0];
  const tone = (s?: string | null) => (s === "FAIL" ? "danger" : s === "PASS" ? "mint" : "amber") as "danger" | "mint" | "amber";
  return (
    <>
      <Toolbar>
        {sessions.length > 0 && (
          <Select
            id="sl-dq-session"
            testid="sl-dq-session"
            label="Session"
            value={session?.date ?? ""}
            options={sessions.map((s) => ({ value: s.date, label: s.date }))}
            onChange={onDate}
          />
        )}
        {session?.status && <Pill tone={tone(session.status)}>{session.status}</Pill>}
        {session?.special_session && <Pill tone="amber">{session.special_session}</Pill>}
      </Toolbar>

      {!session ? (
        <Card testid="sl-dq-none"><Empty testid="sl-dq">No session reports in this snapshot.</Empty></Card>
      ) : (
        <Grid wide>
          <Card testid="sl-dq-session-card">
            <Eyebrow>Data-quality report · {session.date}</Eyebrow>
            <KV
              rows={[
                ["Status", txt(session.status)],
                ["Fail reasons", session.fail_reasons?.length ? session.fail_reasons.join("; ") : "none"],
                ["Special session", txt(session.special_session)],
                ["Missing bars", int(session.missing_count)],
              ]}
            />
            <div className="nv-hr" />
            <Eyebrow>Flags · review prompts, not exclusions</Eyebrow>
            <AutoKV obj={(session.flags as Json) ?? null} testid="sl-dq-flags" />
            <div className="nv-hr" />
            <Eyebrow>Other fields for this session</Eyebrow>
            <AutoKV obj={session} skip={["date", "status", "fail_reasons", "special_session", "missing_count", "flags"]} testid="sl-dq-extra" />
          </Card>

          <Card testid="sl-dq-summaries">
            {(["year", "replay"] as const).map((s) => (
              <div key={s} style={{ marginBottom: 14 }}>
                <Eyebrow>{s === "year" ? "All sessions · full year" : "Replay window"}</Eyebrow>
                <AutoKV obj={d.data_quality[s]} testid={`sl-dq-summary-${s}`} />
              </div>
            ))}
            <Note>
              A feature-cutoff violation means a bar after the decision day entered a stored feature. It is reported
              here whatever its count, because a single violation invalidates the run.
            </Note>
          </Card>
        </Grid>
      )}

      <Card testid="sl-dq-all" pad={14}>
        <div style={{ padding: "6px 6px 12px" }}><Eyebrow>Every session in the snapshot</Eyebrow></div>
        {sessions.length === 0 ? (
          <Empty testid="sl-dq-all">No session reports in this snapshot.</Empty>
        ) : (
          <TableWrap testid="sl-dq-table" min={720} label="Every session in the snapshot">
            <thead>
              <tr>
                <th scope="col" style={TH}>Session</th>
                <th scope="col" style={TH}>Status</th>
                <th scope="col" style={TH}>Special session</th>
                <th scope="col" style={TH_R}>Missing bars</th>
                <th scope="col" style={TH}>Flags</th>
                <th scope="col" style={TH}>Fail reasons</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((s) => (
                <tr
                  key={s.date}
                  data-testid="sl-dq-row"
                  onClick={() => onDate(s.date)}
                  style={{ cursor: "pointer", background: s.date === session?.date ? "var(--bg-2)" : undefined }}
                >
                  <td style={TD}><span className="nv-mono">{s.date}</span></td>
                  <td style={TD}>{s.status ? <Pill tone={tone(s.status)}>{s.status}</Pill> : DASH}</td>
                  <td style={TD}>{txt(s.special_session)}</td>
                  <td style={TD_R}>{int(s.missing_count)}</td>
                  <td style={TD}>
                    {s.flags && Object.keys(s.flags).length
                      ? Object.entries(s.flags).map(([k, v]) => `${humanKey(k)} ${autoValue(k, v)}`).join(" · ")
                      : "none"}
                  </td>
                  <td style={TD}>{s.fail_reasons?.length ? s.fail_reasons.join("; ") : "none"}</td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        )}
      </Card>
    </>
  );
}

/* ── Candidate ledger ────────────────────────────────────────────────────── */
const CAND_SHOWN = ["date", "symbol", "company", "rank", "score", "tradable", "status", "reason", "value20", "close", "atr_pct", "sector"];

function statusTone(s: unknown): "mint" | "danger" | undefined {
  const v = String(s ?? "").toUpperCase();
  if (v === "SELECTED") return "mint";
  if (v === "REJECTED") return "danger";
  return undefined;
}

function CandidatesTab({ dates, date, onDate, result, open, onOpen }: {
  dates: string[]; date: string; onDate: (v: string) => void;
  result: Result<CandidatesPayload> | undefined; open: string | null; onOpen: (s: string | null) => void;
}) {
  if (!dates.length) {
    return <Card testid="sl-cand-none"><Empty testid="sl-cand">This snapshot has no replay sessions, so there is no candidate ledger.</Empty></Card>;
  }
  return (
    <>
      <Toolbar>
        <Select
          id="sl-cand-date"
          testid="sl-cand-date"
          label="Replay session"
          value={date}
          options={dates.map((x) => ({ value: x, label: x }))}
          onChange={onDate}
        />
        <Pill tone="indigo">every candidate, with its reason</Pill>
      </Toolbar>
      <Pending result={result} label="candidates">
        {(c) => {
          const row = open ? c.rows.find((r) => String(r.symbol) === open) ?? null : null;
          return (
            <>
              <Card testid="sl-cand-card" pad={14}>
                {c.rows.length === 0 ? (
                  <Empty testid="sl-cand">No candidate rows for {c.date} in this snapshot.</Empty>
                ) : (
                  <TableWrap testid="sl-cand-table" min={980} label="Candidate ledger">
                    <caption style={{ textAlign: "left", padding: "10px 12px", fontSize: 12, color: "var(--c-ink-3)", captionSide: "top" }}>
                      {int(c.count)} candidates on {c.date}. Select a row for what the snapshot records about it.
                    </caption>
                    <thead>
                      <tr>
                        <th scope="col" style={TH_R}>Rank</th>
                        <th scope="col" style={TH}>Symbol</th>
                        <th scope="col" style={TH}>Company</th>
                        <th scope="col" style={TH}>Sector</th>
                        <th scope="col" style={TH_R}>Score</th>
                        <th scope="col" style={TH}>Tradable</th>
                        <th scope="col" style={TH}>Status</th>
                        <th scope="col" style={TH}>Reason</th>
                        <th scope="col" style={TH_R}>Value20 ₹cr</th>
                        <th scope="col" style={TH_R}>Close</th>
                        <th scope="col" style={TH_R}>ATR %</th>
                      </tr>
                    </thead>
                    <tbody>
                      {c.rows.map((r, i) => (
                        <tr
                          key={`${txt(r.symbol)}-${i}`}
                          data-testid="sl-cand-row"
                          onClick={() => onOpen(open === String(r.symbol) ? null : String(r.symbol))}
                          style={{ cursor: "pointer", background: open === String(r.symbol) ? "var(--bg-2)" : undefined }}
                        >
                          <td style={TD_R}>{int(r.rank)}</td>
                          <td style={TD}><b className="nv-mono" style={{ color: "var(--c-ink)" }}>{txt(r.symbol)}</b></td>
                          <td style={TD}>{txt(r.company)}</td>
                          <td style={TD}>{txt(r.sector)}</td>
                          <td style={TD_R}>{num(r.score, 3)}</td>
                          <td style={TD}>{txt(r.tradable)}</td>
                          <td style={TD}>{r.status ? <Pill tone={statusTone(r.status)}>{txt(r.status)}</Pill> : DASH}</td>
                          <td style={TD}>{txt(r.reason)}</td>
                          <td style={TD_R}>{isNum(r.value20) ? num(r.value20 / 1e7, 1) : DASH}</td>
                          <td style={TD_R}>{num(r.close)}</td>
                          <td style={TD_R}>{isNum(r.atr_pct) ? `${num(r.atr_pct)}%` : DASH}</td>
                        </tr>
                      ))}
                    </tbody>
                  </TableWrap>
                )}
              </Card>

              {row && (
                <Grid wide>
                  <Card testid="sl-cand-detail">
                    <Eyebrow>{txt(row.symbol)} · {c.date}</Eyebrow>
                    <KV
                      rows={[
                        ["Company", txt(row.company)],
                        ["Sector", txt(row.sector)],
                        ["Rank · score", `${int(row.rank)} · ${num(row.score, 3)}`],
                        ["Status", txt(row.status)],
                        ["Reason", txt(row.reason)],
                        ["Tradable", txt(row.tradable)],
                        ["Close on the decision day", num(row.close)],
                        ["ATR", isNum(row.atr_pct) ? `${num(row.atr_pct)}% of close` : DASH],
                        ["20-session traded value", isNum(row.value20) ? `${inr(row.value20)} (₹${num(row.value20 / 1e7, 1)} cr)` : DASH],
                      ]}
                    />
                    <div className="nv-hr" />
                    <Eyebrow>Other fields in this row</Eyebrow>
                    <AutoKV obj={row} skip={CAND_SHOWN} testid="sl-cand-extra" />
                  </Card>

                  <Card testid="sl-cand-unavailable">
                    <Eyebrow>Fundamentals, news and indicator↔outcome</Eyebrow>
                    <p style={{ fontSize: 13.5, lineHeight: 1.6, color: "var(--c-ink-2)", margin: 0 }}>
                      Not available for this period, and not shown rather than shown wrong:
                    </p>
                    <ul style={{ fontSize: 13, lineHeight: 1.6, color: "var(--c-ink-2)", margin: "10px 0 0", paddingLeft: 18 }}>
                      <li>There are no point-in-time fundamentals for 2022 — the source has no as-of query, so any
                        balance-sheet figure here would be today&apos;s revision printed against a 2022 session.</li>
                      <li>There is no 2022 event corpus — filings and announcements start in 2026, so a news panel
                        would be empty or, worse, filled from the wrong years.</li>
                      <li>An indicator↔outcome panel needs both of those, so it is not built for this window either.</li>
                    </ul>
                    <p style={{ fontSize: 13, lineHeight: 1.6, color: "var(--c-ink-3)", margin: "10px 0 0" }}>
                      What the snapshot does hold for a candidate is price, technical and liquidity: the close, the ATR,
                      the 20-session traded value, the model&apos;s rank and score, and why it was or was not selected.
                    </p>
                  </Card>
                </Grid>
              )}
            </>
          );
        }}
      </Pending>
    </>
  );
}

/* ── Trade audit ─────────────────────────────────────────────────────────── */
const TRADE_SHOWN = ["trade_id", "symbol", "company", "decision_date", "entry_date", "exit_date", "exit_reason",
  "rank", "score", "qty", "entry_price", "stop", "target", "exit_price", "gross_inr", "slippage_inr", "charges_inr",
  "net_inr", "net_ret", "r_multiple", "mfe_pct", "mae_pct", "stop_distance_atr", "rc1_primary", "flags", "dq_status"];

function TradesTab({ d, scope, onScope, config, onConfig, result, matrix, cause, onCause, open, onOpen }: {
  d: RunPayload; scope: Scope; onScope: (s: Scope) => void; config: string; onConfig: (c: string) => void;
  result: Result<TradesPayload> | undefined; matrix: Result<MatrixPayload> | undefined;
  cause: string; onCause: (c: string) => void; open: string | null; onOpen: (t: string | null) => void;
}) {
  if (!d.trade_configs.length) {
    return <Card testid="sl-trades-none"><Empty testid="sl-trades">This snapshot holds no trade rows.</Empty></Card>;
  }
  const entry = matrix?.kind === "ok" ? matrix.data.matrix.runs[config] : undefined;
  const extremes = entry?.extremes as Json | undefined;
  return (
    <>
      <Toolbar>
        <Select
          id="sl-trade-config"
          testid="sl-trade-config"
          label="Configuration"
          value={config}
          options={d.trade_configs.map((c) => ({ value: c, label: `Run ${c}` }))}
          onChange={onConfig}
        />
        <ScopeSwitch scope={scope} onChange={onScope} />
      </Toolbar>
      <Pending result={result} label="trades">
        {(t) => {
          const causes = Array.from(new Set(t.rows.map((r) => txt(r.rc1_primary)))).sort();
          const rows = cause === "ALL" ? t.rows : t.rows.filter((r) => txt(r.rc1_primary) === cause);
          const row = open ? t.rows.find((r) => String(r.trade_id) === open) ?? null : null;
          return (
            <>
              <Toolbar>
                <Select
                  id="sl-trade-cause"
                  testid="sl-trade-cause"
                  label="Primary cause"
                  value={causes.includes(cause) ? cause : "ALL"}
                  options={[{ value: "ALL", label: "All causes" }, ...causes.map((c) => ({ value: c, label: c }))]}
                  onChange={onCause}
                />
                <span className="nv-mono" style={{ fontSize: 11.5, color: "var(--c-ink-3)" }} data-testid="sl-trades-count">
                  {int(rows.length)} of {int(t.count)} trades · run {t.config} · {t.scope === "year" ? "full year" : "replay window"}
                </span>
              </Toolbar>

              <Grid wide>
                <Card testid="sl-trades-card" pad={14}>
                  {rows.length === 0 ? (
                    <Empty testid="sl-trades">No trade in run {t.config} has cause {cause} in this scope.</Empty>
                  ) : (
                    <TableWrap testid="sl-trades-table" min={1080} label="Trade audit">
                      <thead>
                        <tr>
                          <th scope="col" style={TH}>Trade</th>
                          <th scope="col" style={TH}>Symbol</th>
                          <th scope="col" style={TH}>Decision → exit</th>
                          <th scope="col" style={TH}>Exit</th>
                          <th scope="col" style={TH_R}>MFE</th>
                          <th scope="col" style={TH_R}>MAE</th>
                          <th scope="col" style={TH_R}>Net ₹</th>
                          <th scope="col" style={TH_R}>R</th>
                          <th scope="col" style={TH}>DQ</th>
                          <th scope="col" style={TH}>Flags</th>
                          <th scope="col" style={TH}>RC-1 primary</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((r, i) => (
                          <tr
                            key={`${txt(r.trade_id)}-${i}`}
                            data-testid="sl-trade-row"
                            onClick={() => onOpen(open === String(r.trade_id) ? null : String(r.trade_id))}
                            style={{ cursor: "pointer", background: open === String(r.trade_id) ? "var(--bg-2)" : undefined }}
                          >
                            <td style={TD}><span className="nv-mono">{txt(r.trade_id)}</span></td>
                            <td style={TD}><b className="nv-mono" style={{ color: "var(--c-ink)" }}>{txt(r.symbol)}</b></td>
                            <td style={TD}>{txt(r.decision_date)} → {txt(r.exit_date)}</td>
                            <td style={TD}>{txt(r.exit_reason)}</td>
                            <td style={TD_R}>{frac(r.mfe_pct, 1)}</td>
                            <td style={TD_R}>{frac(r.mae_pct, 1)}</td>
                            <td style={{ ...TD_R, color: sign(r.net_inr) }}>{inr(r.net_inr)}</td>
                            <td style={TD_R}>{num(r.r_multiple)}</td>
                            <td style={TD}>{txt(r.dq_status)}</td>
                            <td style={TD}>{txt(r.flags)}</td>
                            <td style={TD}><span className="nv-mono" style={{ fontSize: 11 }}>{txt(r.rc1_primary)}</span></td>
                          </tr>
                        ))}
                      </tbody>
                    </TableWrap>
                  )}
                </Card>

                <div style={{ display: "grid", gap: 16, minWidth: 0 }}>
                  <Card testid="sl-rc1">
                    <Eyebrow>RC-1 primary cause · {scope === "year" ? "full year" : "replay window"}</Eyebrow>
                    <AutoKV obj={d.rc1[scope]} testid="sl-rc1-kv" />
                    <Note>
                      DATA_FAILURE comes first by rule: a flagged bar (circuit, corporate-action heuristic, special
                      session) stays a data failure until it is reviewed.
                    </Note>
                  </Card>
                  {extremes && (
                    <Card testid="sl-extremes">
                      <Eyebrow>Extreme-trade audit · run {config}</Eyebrow>
                      <AutoKV obj={extremes} skip={["largest_gains", "largest_losses"]} />
                      <div className="nv-hr" />
                      <Eyebrow>Largest gains</Eyebrow>
                      <AutoTable rows={extremes.largest_gains as Json[] | undefined} testid="sl-extremes-gains" min={360} label="Largest gains" />
                      <div className="nv-hr" />
                      <Eyebrow>Largest losses</Eyebrow>
                      <AutoTable rows={extremes.largest_losses as Json[] | undefined} testid="sl-extremes-losses" min={360} label="Largest losses" />
                    </Card>
                  )}
                </div>
              </Grid>

              {row && (
                <Card testid="sl-trade-detail">
                  <Eyebrow>Trade {txt(row.trade_id)} · {txt(row.symbol)}</Eyebrow>
                  <Grid>
                    <KV
                      rows={[
                        ["Company", txt(row.company)],
                        ["Decision / entry / exit", `${txt(row.decision_date)} / ${txt(row.entry_date)} / ${txt(row.exit_date)}`],
                        ["Rank · score", `${int(row.rank)} · ${num(row.score, 3)}`],
                        ["Quantity", int(row.qty)],
                        ["Entry", num(row.entry_price)],
                        ["Stop / target", `${num(row.stop)} / ${num(row.target)}`],
                        ["Stop distance", isNum(row.stop_distance_atr) ? `${num(row.stop_distance_atr)} ATR` : DASH],
                        ["Exit", `${txt(row.exit_reason)} at ${num(row.exit_price)}`],
                      ]}
                    />
                    <KV
                      rows={[
                        ["Gross", <span style={{ color: sign(row.gross_inr) }}>{inr(row.gross_inr, 2)}</span>],
                        ["Slippage", inr(row.slippage_inr, 2)],
                        ["Charges", inr(row.charges_inr, 2)],
                        ["Net", <span style={{ color: sign(row.net_inr) }}><b>{inr(row.net_inr, 2)}</b> ({frac(row.net_ret)}, {num(row.r_multiple)}R)</span>],
                        ["MFE / MAE", `${frac(row.mfe_pct)} / ${frac(row.mae_pct)}`],
                        ["Data quality", `${txt(row.dq_status)} ${txt(row.flags) === DASH ? "" : txt(row.flags)}`],
                        ["RC-1 primary", txt(row.rc1_primary)],
                      ]}
                    />
                  </Grid>
                  <div className="nv-hr" />
                  <Eyebrow>Other fields in this row</Eyebrow>
                  <AutoKV obj={row} skip={TRADE_SHOWN} testid="sl-trade-extra" />
                </Card>
              )}
            </>
          );
        }}
      </Pending>
    </>
  );
}

/* ── Reconciliation ──────────────────────────────────────────────────────── */
function ReconTab({ d }: { d: RunPayload }) {
  const unexplained = d.reconciliation.summary.unexplained;
  return (
    <Grid wide>
      <Card testid="sl-recon-summary">
        <Eyebrow>Engine vs labels.py · the same trades run through two implementations</Eyebrow>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10, margin: "4px 0 14px" }}>
          <span className="nv-serif" style={{ fontSize: 30, color: sign(isNum(unexplained) ? -unexplained : null) }}>
            {int(unexplained)}
          </span>
          <span style={{ fontSize: 14, color: "var(--c-ink-3)" }}>unexplained differences</span>
        </div>
        <AutoKV obj={d.reconciliation.summary} testid="sl-recon-kv" />
      </Card>

      <Card testid="sl-recon-classes" pad={14}>
        <div style={{ padding: "6px 6px 12px" }}><Eyebrow>How each difference is explained</Eyebrow></div>
        {d.reconciliation.classes.length === 0 ? (
          <Empty testid="sl-recon">No mismatch classes in this snapshot.</Empty>
        ) : (
          <TableWrap testid="sl-recon-table" min={640} label="Reconciliation mismatch classes">
            <thead>
              <tr>
                <th scope="col" style={TH}>Class</th>
                <th scope="col" style={TH_R}>Trades</th>
                <th scope="col" style={TH}>Side at fault</th>
                <th scope="col" style={TH}>What it is</th>
              </tr>
            </thead>
            <tbody>
              {d.reconciliation.classes.map((c, i) => (
                <tr key={`${txt(c.class)}-${i}`} data-testid="sl-recon-row">
                  <td style={TD}>
                    <Pill tone={String(c.class ?? "").toUpperCase() === "UNEXPLAINED" ? "danger" : "indigo"}>{txt(c.class)}</Pill>
                  </td>
                  <td style={TD_R}>{int(c.trades)}</td>
                  <td style={TD}>{txt(c.side)}</td>
                  <td style={{ ...TD, whiteSpace: "normal", minWidth: 280 }}>{txt(c.what)}</td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        )}
      </Card>
    </Grid>
  );
}

/* ── Comparison ──────────────────────────────────────────────────────────── */
function ComparisonTab({ result, scope, onScope, notes }: {
  result: Result<MatrixPayload> | undefined; scope: Scope; onScope: (s: Scope) => void; notes: Json;
}) {
  return (
    <>
      <Toolbar>
        <ScopeSwitch scope={scope} onChange={onScope} />
        <Pill tone="amber">pre-tax is primary · the tax lines are illustrative</Pill>
      </Toolbar>
      <Pending result={result} label="comparison">
        {(m) => {
          const all = Object.entries(m.matrix.runs).sort(([a], [b]) => a.localeCompare(b));
          const portfolio = all.filter(([, e]) => isPortfolioRun(e));
          const fixed = all.filter(([, e]) => !isPortfolioRun(e));
          const taxed = all.filter(([, e]) => e.tax != null);
          return (
            <>
              <Card testid="sl-cmp-fixed" pad={14}>
                <div style={{ padding: "6px 6px 12px" }}>
                  <Eyebrow>Fixed-notional runs · per trade and in rupees</Eyebrow>
                </div>
                {fixed.length === 0 ? (
                  <Empty testid="sl-cmp-fixed">No fixed-notional run in this snapshot.</Empty>
                ) : (
                  <TableWrap testid="sl-cmp-fixed-table" min={1120} label="Fixed-notional runs">
                    <caption style={{ textAlign: "left", padding: "10px 12px", fontSize: 12, color: "var(--c-ink-3)", captionSide: "top" }}>
                      These runs put a fixed amount into each trade, so a &quot;% of ₹5,00,000&quot; return and a
                      drawdown percentage would both be wrong for them. Their worst stretch is the worst cumulative
                      net over the trade sequence, in rupees, and the capital they actually needed is shown beside it.
                    </caption>
                    <thead>
                      <tr>
                        <th scope="col" style={TH}>Run</th>
                        <th scope="col" style={TH_R}>Trades</th>
                        <th scope="col" style={TH_R}>Gross ₹</th>
                        <th scope="col" style={TH_R}>Slippage ₹</th>
                        <th scope="col" style={TH_R}>Charges ₹</th>
                        <th scope="col" style={TH_R}>Net ₹</th>
                        <th scope="col" style={TH_R}>Net / trade</th>
                        <th scope="col" style={TH_R}>Expectancy ₹</th>
                        <th scope="col" style={TH_R}>Largest win / loss</th>
                        <th scope="col" style={TH_R}>Longest losing streak</th>
                        <th scope="col" style={TH_R}>Worst cumulative net</th>
                        <th scope="col" style={TH_R}>Peak capital required</th>
                        <th scope="col" style={TH_R}>Max concurrent</th>
                      </tr>
                    </thead>
                    <tbody>
                      {fixed.map(([k, e]) => (
                        <tr key={k} data-testid={`sl-cmp-fixed-row-${k}`}>
                          <td style={TD}><b style={{ color: "var(--c-ink)" }}>{k}</b></td>
                          <td style={TD_R}>{int(e.trades)}</td>
                          <td style={{ ...TD_R, color: sign(e.gross_inr) }}>{inr(e.gross_inr)}</td>
                          <td style={TD_R}>{inr(e.slippage_inr)}</td>
                          <td style={TD_R}>{inr(e.charges_inr)}</td>
                          <td style={{ ...TD_R, color: sign(e.net_inr) }}><b>{inr(e.net_inr)}</b></td>
                          <td style={{ ...TD_R, color: sign(e.net_per_trade) }}>{frac(e.net_per_trade)}</td>
                          <td style={TD_R}>{inr(e.expectancy_inr)}</td>
                          <td style={TD_R}>{inr(e.largest_win_inr)} / {inr(e.largest_loss_inr)}</td>
                          <td style={TD_R}>{int(e.longest_losing_streak)}</td>
                          <td style={TD_R}>{inr(e.worst_cumulative_net_inr)}</td>
                          <td style={TD_R}>{inr(e.peak_capital_required_inr)}</td>
                          <td style={TD_R}>{int(e.max_concurrent_trades)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </TableWrap>
                )}
                <Note testid="sl-cmp-note">
                  {txt(notes.percent_of_capital_rule)}
                </Note>
              </Card>

              <Card testid="sl-cmp-portfolio" pad={14}>
                <div style={{ padding: "6px 6px 12px" }}>
                  <Eyebrow>Portfolio runs · the only place a capital percentage is valid</Eyebrow>
                </div>
                {portfolio.length === 0 ? (
                  <Empty testid="sl-cmp-portfolio">No portfolio run in this snapshot.</Empty>
                ) : (
                  <TableWrap testid="sl-cmp-portfolio-table" min={960} label="Portfolio runs">
                    <thead>
                      <tr>
                        <th scope="col" style={TH}>Run</th>
                        <th scope="col" style={TH_R}>Trades</th>
                        <th scope="col" style={TH_R}>Gross ₹</th>
                        <th scope="col" style={TH_R}>Net ₹</th>
                        <th scope="col" style={TH_R}>Net / trade</th>
                        <th scope="col" style={TH_R}>Final equity</th>
                        <th scope="col" style={TH_R}>Return on capital</th>
                        <th scope="col" style={TH_R}>Max drawdown ₹</th>
                        <th scope="col" style={TH_R}>Max drawdown %</th>
                        <th scope="col" style={TH_R}>Max positions open</th>
                      </tr>
                    </thead>
                    <tbody>
                      {portfolio.map(([k, e]) => (
                        <tr key={k} data-testid={`sl-cmp-portfolio-row-${k}`}>
                          <td style={TD}><b style={{ color: "var(--c-ink)" }}>{k}</b></td>
                          <td style={TD_R}>{int(e.trades)}</td>
                          <td style={{ ...TD_R, color: sign(e.gross_inr) }}>{inr(e.gross_inr)}</td>
                          <td style={{ ...TD_R, color: sign(e.net_inr) }}><b>{inr(e.net_inr)}</b></td>
                          <td style={{ ...TD_R, color: sign(e.net_per_trade) }}>{frac(e.net_per_trade)}</td>
                          <td style={TD_R}>{inr(e.final_equity_inr)}</td>
                          <td style={{ ...TD_R, color: sign(e.return_on_capital_pct) }}>{frac(e.return_on_capital_pct)}</td>
                          <td style={TD_R}>{inr(e.max_drawdown_inr)}</td>
                          <td style={TD_R}>{frac(e.max_drawdown_pct)}</td>
                          <td style={TD_R}>{int(e.max_positions_open)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </TableWrap>
                )}
              </Card>

              <Card testid="sl-cmp-tax" pad={14}>
                <div style={{ padding: "6px 6px 12px" }}>
                  <Eyebrow>Tax annex · illustrative</Eyebrow>
                </div>
                {taxed.length === 0 ? (
                  <Empty testid="sl-cmp-tax">No run in this snapshot carries a tax annex.</Empty>
                ) : (
                  <div style={{ display: "grid", gap: 14 }}>
                    {taxed.map(([k, e]) => (
                      <div key={k} data-testid={`sl-cmp-tax-${k}`}>
                        <div className="nv-mono" style={{ fontSize: 10.5, color: "var(--c-ink-3)", marginBottom: 6 }}>RUN {k}</div>
                        <AutoKV obj={e.tax as Json} />
                      </div>
                    ))}
                  </div>
                )}
                <Note>
                  Illustrative only ({txt(notes.tax)}): the trades are 2022 and the cost model is 2026, so both
                  short-term regimes are shown — 15% + 4% cess (the law in 2022) and 20% + 4% cess (after
                  23 July 2024). No surcharge, no set-off, no carry-forward, and a run whose net is negative owes
                  nothing either way.
                </Note>
              </Card>
            </>
          );
        }}
      </Pending>
    </>
  );
}

/* ── Run spec template ───────────────────────────────────────────────────── */
/** The toggle between the two spec variants — the ScopeSwitch pattern, one row up. */
function SpecSwitch({ variant, onVariant }: { variant: RunSpecVariantId; onVariant: (v: RunSpecVariantId) => void }) {
  return (
    <span role="group" aria-label="Which spec to show" style={{ display: "inline-flex", gap: 4, flexWrap: "wrap" }}>
      {RUN_SPEC_VARIANTS.map((v) => (
        <button
          key={v.id}
          type="button"
          aria-pressed={variant === v.id}
          data-testid={`sl-runspec-variant-${v.id}`}
          onClick={() => onVariant(v.id)}
          className="nv-mono"
          style={{
            fontSize: 10, letterSpacing: ".13em", textTransform: "uppercase", padding: "8px 13px", borderRadius: 999,
            cursor: "pointer", border: `1px solid ${variant === v.id ? "var(--mint-line)" : "var(--line-2)"}`,
            background: variant === v.id ? "var(--mint-soft)" : "transparent",
            color: variant === v.id ? "var(--mint)" : "var(--c-ink-2)",
          }}
        >
          {v.label}
        </button>
      ))}
    </span>
  );
}

/**
 * Static reference content — the reusable run spec, blank and filled. It calls no API and needs no snapshot, which
 * is why it is in STATIC_TABS and renders in the states where the frozen run could not be loaded.
 */
function RunSpecTab() {
  const [variant, setVariant] = useState<RunSpecVariantId>("skeleton");
  const [copied, setCopied] = useState<"idle" | "ok" | "unavailable">("idle");
  const [copyTick, setCopyTick] = useState(0);   // a repeat click keeps the same state, so this restarts the timer
  const spec = RUN_SPEC_VARIANTS.find((v) => v.id === variant) ?? RUN_SPEC_VARIANTS[0];

  // the flag belongs to the block that was copied, so switching variants clears it
  useEffect(() => { setCopied("idle"); }, [variant]);
  useEffect(() => {
    if (copied === "idle") return;
    const t = window.setTimeout(() => setCopied("idle"), 2500);
    return () => window.clearTimeout(t);
  }, [copied, copyTick]);

  const copy = useCallback(async () => {
    // navigator.clipboard is absent on an insecure origin and can reject on a denied permission; both end in the
    // "unavailable" state, with the text still selectable. It never reports a copy that did not happen.
    const api = navigator.clipboard as Clipboard | undefined;
    setCopyTick((n) => n + 1);
    try {
      if (!api?.writeText) throw new Error("clipboard unavailable");
      await api.writeText(spec.yaml);
      setCopied("ok");
    } catch {
      setCopied("unavailable");
    }
  }, [spec.yaml]);

  return (
    <Grid wide>
      <Card testid="sl-runspec-spec">
        <Eyebrow>Reusable run spec · schema {RUN_SPEC_SCHEMA}</Eyebrow>
        <h3 className="nv-serif" style={{ fontSize: 20, margin: "0 0 6px" }}>One file per run, filled before execution</h3>
        <p style={{ fontSize: 13, color: "var(--c-ink-2)", margin: "0 0 14px", maxWidth: "62ch" }}>
          The spec is the written record of a run: what it is, which frozen inputs it reads, the one thing it
          changes, and what was promised about it before it ran.
        </p>

        <Toolbar>
          <SpecSwitch variant={variant} onVariant={setVariant} />
          <button type="button" className="nv-btn" data-testid="sl-runspec-copy" onClick={copy}>
            {copied === "ok" ? "Copied" : "Copy to clipboard"}
          </button>
          <span
            role="status"
            aria-live="polite"
            data-testid="sl-runspec-copy-state"
            style={{ fontSize: 12, color: copied === "ok" ? "var(--mint)" : "var(--c-ink-3)" }}
          >
            {copied === "ok" ? "Copied to the clipboard."
              : copied === "unavailable" ? "The clipboard is not available here — select the text below and copy it."
              : ""}
          </span>
        </Toolbar>

        <div className="nv-mono" data-testid="sl-runspec-path" style={{ fontSize: 11, color: "var(--c-ink-3)", wordBreak: "break-all" }}>
          {spec.path}
        </div>
        <p style={{ fontSize: 12.5, color: "var(--c-ink-2)", margin: "6px 0 10px" }}>{spec.blurb}</p>

        <pre
          data-testid="sl-runspec-yaml"
          tabIndex={0}
          role="region"
          aria-label={`${spec.label} — ${spec.path}`}
          className="nv-mono"
          style={{
            margin: 0, padding: 14, borderRadius: 12, border: "1px solid var(--c-line)", background: "var(--bg-2)",
            color: "var(--c-ink-2)", fontSize: 11.5, lineHeight: 1.6, overflow: "auto", maxHeight: 560,
            whiteSpace: "pre", maxWidth: "100%",
          }}
        >
          {spec.yaml}
        </pre>
      </Card>

      <div style={{ display: "grid", gap: 16, minWidth: 0 }}>
        <Card testid="sl-runspec-howto">
          <Eyebrow>How to use it</Eyebrow>
          <ol style={{ listStyle: "none", margin: "10px 0 0", padding: 0, display: "grid", gap: 14 }}>
            {RUN_SPEC_STEPS.map((s) => (
              <li
                key={s.n}
                data-testid={`sl-runspec-step-${s.n}`}
                style={{ display: "grid", gridTemplateColumns: "26px minmax(0, 1fr)", gap: 10, minWidth: 0 }}
              >
                <span className="nv-mono" style={{ fontSize: 11, color: "var(--mint)", paddingTop: 1 }}>{s.n}</span>
                <span style={{ fontSize: 13, lineHeight: 1.55, color: "var(--c-ink-2)", minWidth: 0 }}>
                  {s.text}
                  {s.caveat && (
                    <span
                      data-testid={`sl-runspec-caveat-${s.n}`}
                      style={{
                        display: "block", marginTop: 7, paddingLeft: 9, fontSize: 12, lineHeight: 1.5,
                        color: "var(--c-ink-3)", borderLeft: "2px solid var(--line-2)",
                      }}
                    >
                      <b className="nv-mono" style={{ fontSize: 9.5, letterSpacing: ".1em", textTransform: "uppercase", color: "var(--c-ink-2)", marginRight: 6 }}>
                        Runner today
                      </b>
                      {s.caveat}
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ol>
        </Card>

        <Card testid="sl-runspec-rules">
          <Eyebrow>Block rules</Eyebrow>
          <div style={{ display: "grid", gap: 13, marginTop: 10 }}>
            {RUN_SPEC_BLOCK_RULES.map((r) => (
              <div key={r.block} data-testid={`sl-runspec-rule-${r.block}`} style={{ minWidth: 0 }}>
                <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8, marginBottom: 5 }}>
                  <code className="nv-mono" style={{ fontSize: 12, color: "var(--c-ink)" }}>{r.block}</code>
                  <Pill>{r.chip}</Pill>
                </div>
                <p style={{ margin: 0, fontSize: 12.5, lineHeight: 1.55, color: "var(--c-ink-2)", wordBreak: "break-word" }}>
                  {r.rule}
                </p>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </Grid>
  );
}
