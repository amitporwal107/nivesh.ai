/**
 * 03 · Opportunity scanner — built to the owner's design (docs/autodesk/design/prototype/TDScanner.dc.html):
 * header, six scanner statistics, filters, the halted banner, the ranked signal list (a table with an expandable row on
 * wide screens, cards on a phone) and the signal-history cards.
 *
 * Phase 1 truth: the AI Trader scans the latest published end-of-day data when a person starts a session cycle (there
 * is no scheduler), so the screen carries a "Run session cycle" control. Every figure comes from the desk API (see
 * ./scanner/model.ts); the score ranks evidence and is not a probability (calibrated_probability is empty in Phase 1).
 * Signal history needs closed paper trades (Phase 3) and says so. Text the agents wrote is shown as written.
 */
import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { errorText } from "../api";
import { dateLong, dateShort, DASH, humanize, num, timeIST } from "../format";
import { stopEntriesOf, useAccounts, useDeskStatus, useIsMobile, useNow } from "../hooks";
import { screenById, screenNo } from "../nav";
import type { Account, ApprovalRow, SignalRow, TradePlanRow, WorkflowRow } from "../types";
import { Empty, ErrorBox, Loading, PhaseNote } from "../ui";
import { activityQuery, workflowQuery, type WorkflowDetail } from "./agents/model";
import { ageShort, countWord, px, shortId, whenIST } from "./scanner/fmt";
import { ShadowBreakdown, ShadowChips } from "./scanner/shadow";
import {
  DIR_TONE, OPEN_WF, STATUS_TONE, confirmation, dims, isBlockedEarly, outcomeOf, premarketView, scoreColor, statusOf,
  storedFromRef, useAccountPlans, useCycles, useDeskApprovals, usePolicyVersion, useRunCycle, useSessionSignals,
  versionLabel, type PremarketView, type RowStatus,
} from "./scanner/model";

// The design's columns, with three minimums trimmed (entry 150→130, confirmation 170→150, age 110→100) so the row fits
// the shell's 1,248 px content width; below that the table scrolls sideways as in the design.
const COLS = "34px minmax(120px,1.2fr) 92px 110px 96px minmax(130px,1.2fr) 120px minmax(150px,1.5fr) 100px 150px";
type Dir = "ALL" | "BULLISH" | "BEARISH";
type Seg = "ALL" | "CASH" | "FUTURES" | "OPTIONS" | "INDEX";

interface Row {
  sig: SignalRow;
  rank: string;
  score: number;
  status: RowStatus;
  plan?: TradePlanRow;
}

// ── small pieces in the design's markup ─────────────────────────────────────────────────────────────────────────────

function ChipGroup<T extends string | number>({ t, value, opts, onPick, testId }: {
  t: string; value: T; opts: [T, string][]; onPick: (v: T) => void; testId: string;
}) {
  return (
    <div data-testid={testId} style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <span className="nv-eyebrow" style={{ fontSize: 9.5 }}>{t}</span>
      <div role="group" aria-label={t} style={{ display: "flex", gap: 2, padding: 3, borderRadius: 999, background: "var(--bg-2)", flexWrap: "wrap" }}>
        {opts.map(([v, label]) => {
          const on = value === v;
          return (
            <button key={String(v)} type="button" aria-pressed={on} data-testid={`${testId}-${String(v).toLowerCase()}`} onClick={() => onPick(v)}
              style={{ cursor: "pointer", border: 0, padding: "6px 12px", borderRadius: 999, background: on ? "var(--mint)" : "transparent", color: on ? "#06120B" : "var(--ink-2)", fontFamily: "var(--mono)", fontSize: 10.5, letterSpacing: "0.06em", textTransform: "uppercase" }}>
              {label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function StatTile({ k, v, s, c = "var(--ink)", testId }: { k: string; v: string; s: string; c?: string; testId: string }) {
  return (
    <div data-testid={testId} style={{ display: "flex", flexDirection: "column", gap: 4, padding: "12px 14px", borderRadius: 12, border: "1px solid var(--line)", background: "var(--bg-1)", minWidth: 0 }}>
      <span className="nv-eyebrow" style={{ fontSize: 9 }}>{k}</span>
      <span className="nv-num" data-testid={`${testId}-v`} style={{ fontFamily: "var(--display)", fontSize: 24, lineHeight: 1.1, color: c }}>{v}</span>
      <span style={{ fontSize: 11, color: "var(--ink-3)" }}>{s}</span>
    </div>
  );
}

function StatusPill({ st }: { st: RowStatus }) {
  const [c, l] = STATUS_TONE[st.tone];
  return <span className="nv-pill" data-testid="row-status" title={st.title} style={{ padding: "2px 8px", fontSize: 9, whiteSpace: "normal", color: c, borderColor: l }}>{st.label}</span>;
}

function DirPill({ d, small }: { d: string; small?: boolean }) {
  const [c, l, bg] = DIR_TONE[d] ?? DIR_TONE.NEUTRAL;
  return <span className="nv-pill" data-testid="row-direction" style={{ padding: small ? "1px 7px" : "2px 8px", fontSize: small ? 8.5 : 9.5, color: c, borderColor: l, background: small ? undefined : bg }}>{d}</span>;
}

function ActionButton({ st, halted, big }: { st: RowStatus; halted: boolean; big?: boolean }) {
  const nav = useNavigate();
  if (!st.act) return null;
  const blocked = halted && st.act.workbench;
  const to = st.act.to;
  return (
    <button
      type="button"
      data-testid="row-action"
      disabled={blocked}
      title={blocked ? "Stop new entries is active: strategy work is paused until entries resume" : undefined}
      onClick={(e) => { e.stopPropagation(); if (!blocked) nav(to); }}
      style={{ cursor: blocked ? "not-allowed" : "pointer", alignSelf: "flex-start", marginTop: big ? 0 : 4, minHeight: big ? 44 : undefined, padding: big ? "10px 14px" : "9px 14px", borderRadius: big ? 12 : 10, border: `1px solid ${blocked ? "var(--line-2)" : "transparent"}`, background: blocked ? "transparent" : "var(--mint)", color: blocked ? "var(--ink-3)" : "#06120B", fontSize: big ? 14 : 13, fontWeight: 500 }}
    >
      {blocked ? "Entries stopped" : `${st.act.t} ›`}
    </button>
  );
}

// ── expanded row ────────────────────────────────────────────────────────────────────────────────────────────────────

function Breakdown({ sig, score, compact }: { sig: SignalRow; score: number; compact?: boolean }) {
  const ds = dims(sig);
  return (
    <div data-testid="score-breakdown" style={{ display: "flex", flexDirection: "column", gap: 7 }}>
      {!compact && <span className="nv-eyebrow" style={{ fontSize: 9.5 }}>Score breakdown · {px(score)} of 100</span>}
      {ds.length === 0 && <span style={{ fontSize: 12, color: "var(--ink-3)" }}>No breakdown stored with this signal.</span>}
      {ds.map((d) => (
        <div key={d.key} data-testid={`dim-${d.key}`} title={d.detail || undefined} style={{ display: "grid", gridTemplateColumns: compact ? "minmax(0,1fr) 70px 36px" : "minmax(0,1fr) 90px 40px", gap: compact ? 8 : 10, alignItems: "center", fontSize: compact ? 11.5 : 12 }}>
          <span style={{ color: d.available ? "var(--ink-2)" : "var(--ink-4)" }}>{d.k}{!d.available && <span style={{ fontSize: 10.5 }}> · missing input</span>}</span>
          <span style={{ height: 4, borderRadius: 2, background: "var(--bg-3)" }}><span style={{ display: "block", height: "100%", width: d.w, borderRadius: 2, background: "var(--mint)" }} /></span>
          <span className="nv-num" style={{ fontFamily: "var(--mono)", fontSize: compact ? 10.5 : 11, textAlign: "right", color: "var(--ink-3)" }}>{d.v}</span>
        </div>
      ))}
    </div>
  );
}

function liquidityDetail(sig: SignalRow): string {
  const l = (sig.body?.score_breakdown ?? []).find((x) => x.dimension === "liquidity");
  return l && l.available !== false && l.detail ? l.detail : DASH;
}

function Expanded({ r, halted }: { r: Row; halted: boolean }) {
  const s = r.sig;
  const b = s.body ?? {};
  const chips = [humanize(s.category).toUpperCase(), b.sector ? String(b.sector).toUpperCase() : null, b.fno_eligible ? "F&O ELIGIBLE" : "CASH ONLY"].filter(Boolean) as string[];
  const evidence = (b.evidence ?? []).map((e) => (typeof e === "string" ? e : JSON.stringify(e)));
  const missing = b.missing_inputs ?? [];
  return (
    <div data-testid="row-expanded" style={{ display: "grid", gridTemplateColumns: "minmax(0,1.1fr) minmax(0,1fr) minmax(0,0.9fr)", gap: 22, padding: "16px 18px 20px", background: "var(--bg-2)", borderTop: "1px solid var(--line)" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
        <Breakdown sig={s} score={r.score} />
        <ShadowBreakdown sig={s} />
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 10, minWidth: 0 }}>
        <span className="nv-eyebrow" style={{ fontSize: 9.5 }}>Evidence</span>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {chips.map((c) => <span key={c} className="nv-pill" data-testid="evidence-chip" style={{ padding: "3px 8px", fontSize: 9 }}>{c}</span>)}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 5, fontSize: 12.5, color: "var(--ink-2)" }}>
          <span data-testid="row-close">Close <span className="nv-num" style={{ color: "var(--ink)" }}>{px(b.reference_price)}</span> · liquidity {liquidityDetail(s)}</span>
          {evidence.map((e) => <span key={e} data-testid="evidence-text" style={{ overflowWrap: "anywhere" }}>{e}</span>)}
          {missing.length > 0 && <span data-testid="missing-inputs" style={{ color: "var(--ink-3)" }}>Missing inputs (earn no points): {missing.join(", ")}</span>}
          <span style={{ color: "var(--ink-3)" }}>Similar-setup history needs closed paper trades, which come with Phase 3.</span>
        </div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 0 }}>
        <span className="nv-eyebrow" style={{ fontSize: 9.5 }}>Provenance</span>
        <span data-testid="provenance" style={{ fontFamily: "var(--mono)", fontSize: 10.5, lineHeight: 1.6, color: "var(--ink-3)", overflowWrap: "anywhere" }}>
          {s.signal_id} · DATA AS OF {dateShort(s.data_as_of)} {timeIST(s.data_as_of, { seconds: false })} IST · MODEL {s.model_version ?? DASH} · RULES {s.rule_version} · SESSION {dateShort(s.session_date)} · EXPIRES {s.expires_at ? `${dateShort(s.expires_at)} ${timeIST(s.expires_at, { seconds: false })}` : DASH}
          {" · "}WORKFLOW {s.workflow_id ?? DASH} · TASK {s.task_id ?? DASH}
        </span>
        <ActionButton st={r.status} halted={halted} />
      </div>
    </div>
  );
}

// ── wide table + phone cards ────────────────────────────────────────────────────────────────────────────────────────

function SignalTable({ rows, open, toggle, now, halted }: { rows: Row[]; open: string | null; toggle: (id: string) => void; now: number; halted: boolean }) {
  return (
    <section data-testid="signal-table" style={{ border: "1px solid var(--line)", borderRadius: 14, background: "var(--bg-1)", boxShadow: "var(--shadow-card)", overflow: "hidden" }}>
      <div style={{ overflowX: "auto" }}>
        <div style={{ minWidth: 1060 }}>
          <div style={{ display: "grid", gridTemplateColumns: COLS, gap: 12, padding: "10px 18px", fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--ink-3)" }}>
            <span>#</span><span>Instrument</span><span>Direction</span><span>Score</span><span>Calibrated P</span><span>Entry → invalidation</span><span>Targets</span><span>Confirmation</span><span>Age · expiry</span><span>Status</span>
          </div>
          {rows.map((r) => {
            const s = r.sig;
            const isOpen = open === s.signal_id;
            const prob = num(s.calibrated_probability);
            const zone = s.body?.entry_zone;
            return (
              <div key={s.signal_id} data-testid={`signal-row-${s.instrument}`}>
                <div
                  role="button"
                  tabIndex={0}
                  aria-expanded={isOpen}
                  data-testid="signal-row"
                  onClick={() => toggle(s.signal_id)}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(s.signal_id); } }}
                  className="ad-hover"
                  style={{ cursor: "pointer", display: "grid", gridTemplateColumns: COLS, gap: 12, padding: "12px 18px", borderTop: "1px solid var(--line)", alignItems: "center", fontSize: 13, background: isOpen ? "var(--bg-2)" : "transparent" }}
                >
                  <span style={{ fontFamily: "var(--display)", fontSize: 20, color: "var(--ink-4)" }}>{r.rank}</span>
                  <span style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
                    <span data-testid="row-instrument" style={{ fontWeight: 500 }}>{s.instrument}</span>
                    <span style={{ fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.04em", color: "var(--ink-3)" }}>{s.segment} · {s.timeframe}</span>
                  </span>
                  <span><DirPill d={s.direction} /></span>
                  <span style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 0 }}>
                  <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span className="nv-num" data-testid="row-score" style={{ fontFamily: "var(--display)", fontSize: 22, width: 28 }}>{px(r.score)}</span>
                    <span style={{ flex: 1, height: 4, borderRadius: 2, background: "var(--bg-3)", maxWidth: 60 }}><span style={{ display: "block", height: "100%", width: `${Math.max(0, Math.min(100, r.score))}%`, borderRadius: 2, background: scoreColor(r.score) }} /></span>
                  </span>
                  <ShadowChips sig={s} />
                  </span>
                  <span style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                    <span className="nv-num" data-testid="row-prob" style={{ color: prob == null ? "var(--ink-3)" : "var(--ink)" }}>{prob == null ? DASH : prob.toFixed(2)}</span>
                    <span style={{ fontSize: 10.5, color: "var(--ink-3)" }}>{prob == null ? "Not calibrated" : "Calibrated"}</span>
                  </span>
                  <span className="nv-num" data-testid="row-entry" style={{ fontSize: 12.5, color: "var(--ink-2)" }}>
                    {zone ? `${px(zone.low)}–${px(zone.high)}` : DASH} → <span style={{ color: "var(--danger)" }}>{px(s.body?.invalidation_price)}</span>
                  </span>
                  <span className="nv-num" data-testid="row-targets" style={{ fontSize: 12.5, color: "var(--mint)" }}>{(s.body?.targets ?? []).map(px).join(" / ") || DASH}</span>
                  <span data-testid="row-confirmation" style={{ fontSize: 12, lineHeight: 1.4, color: "var(--ink-2)", overflowWrap: "anywhere" }}>{confirmation(s)}</span>
                  <span className="nv-num" data-testid="row-age" style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-3)" }}>{ageShort(s.created_at, now)} · {whenIST(s.expires_at, now)}</span>
                  <span><StatusPill st={r.status} /></span>
                </div>
                {isOpen && <Expanded r={r} halted={halted} />}
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

function SignalCards({ rows, open, toggle, now, halted }: { rows: Row[]; open: string | null; toggle: (id: string) => void; now: number; halted: boolean }) {
  return (
    <section data-testid="signal-cards" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {rows.map((r) => {
        const s = r.sig;
        const isOpen = open === s.signal_id;
        const prob = num(s.calibrated_probability);
        const zone = s.body?.entry_zone;
        const small: CSSProperties = { fontSize: 10.5, color: "var(--ink-3)" };
        return (
          <div key={s.signal_id} data-testid={`signal-row-${s.instrument}`} role="button" tabIndex={0} aria-expanded={isOpen}
            onClick={() => toggle(s.signal_id)} onKeyDown={(e) => { if (e.key === "Enter") toggle(s.signal_id); }}
            style={{ cursor: "pointer", display: "flex", flexDirection: "column", gap: 10, padding: "14px 16px", borderRadius: 14, border: "1px solid var(--line)", background: "var(--bg-1)", minWidth: 0 }}>
            <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
              <span style={{ fontFamily: "var(--display)", fontSize: 20, color: "var(--ink-4)", width: 22 }}>{r.rank}</span>
              <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 3 }}>
                <span data-testid="row-instrument" style={{ fontSize: 15, fontWeight: 500 }}>{s.instrument}</span>
                <span style={{ fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.04em", color: "var(--ink-3)" }}>{s.segment} · {s.timeframe}</span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4 }}>
                <span className="nv-num" data-testid="row-score" style={{ fontFamily: "var(--display)", fontSize: 26, lineHeight: 1 }}>{px(r.score)}</span>
                <DirPill d={s.direction} small />
                <ShadowChips sig={s} />
              </div>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(2,minmax(0,1fr))", gap: 8, fontSize: 12 }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 2 }}><span style={small}>Entry → invalidation</span><span className="nv-num" data-testid="row-entry">{zone ? `${px(zone.low)}–${px(zone.high)}` : DASH} → {px(s.body?.invalidation_price)}</span></div>
              <div style={{ display: "flex", flexDirection: "column", gap: 2 }}><span style={small}>Targets</span><span className="nv-num" style={{ color: "var(--mint)" }}>{(s.body?.targets ?? []).map(px).join(" / ") || DASH}</span></div>
              <div style={{ display: "flex", flexDirection: "column", gap: 2 }}><span style={small}>Calibrated P</span><span className="nv-num" data-testid="row-prob">{prob == null ? DASH : prob.toFixed(2)}</span></div>
              <div style={{ display: "flex", flexDirection: "column", gap: 2 }}><span style={small}>Age · expiry</span><span className="nv-num">{ageShort(s.created_at, now)} · {whenIST(s.expires_at, now)}</span></div>
            </div>
            <span style={{ alignSelf: "flex-start" }}><StatusPill st={r.status} /></span>
            {isOpen && (
              <div data-testid="row-expanded" style={{ display: "flex", flexDirection: "column", gap: 7, paddingTop: 10, borderTop: "1px solid var(--line)" }}>
                <Breakdown sig={s} score={r.score} compact />
                <ShadowBreakdown sig={s} compact />
                <span style={{ fontSize: 12, color: "var(--ink-3)", overflowWrap: "anywhere" }}>{confirmation(s)} · similar-setup history needs closed paper trades (Phase 3)</span>
                <ActionButton st={r.status} halted={halted} big />
              </div>
            )}
          </div>
        );
      })}
    </section>
  );
}

// ── session cycle control ───────────────────────────────────────────────────────────────────────────────────────────

function cycleSummary(w: WorkflowRow): string {
  const o = outcomeOf(w);
  const parts = [`${w.state}`];
  if (o.result) parts.push(o.result);
  if (o.scan?.signals != null) parts.push(`${o.scan.signals} signals published`);
  if (o.proposals?.proposed != null) parts.push(`${o.proposals.proposed} proposed of ${o.proposals.candidates ?? DASH} candidates`);
  if (o.proposals?.held_back) parts.push(o.proposals.held_back);
  if (o.premarket?.reason) parts.push(String(o.premarket.reason));
  if (w.error) parts.push(w.error);
  return parts.join(" · ");
}

/**
 * Why a cycle could not take new risk: the pre-market checks that failed or ran degraded, with the detail Tech Support
 * wrote. A BLOCKED cycle scanned nothing and made no plan, and can be run again; a DEGRADED one ran on what was allowed.
 */
function PremarketPanel({ cycle, view }: { cycle: WorkflowRow; view: PremarketView }) {
  const blocked = cycle.state === "BLOCKED";
  const tone = blocked ? "danger" : "amber";
  return (
    <div role="status" data-testid={blocked ? "premarket-blocked" : "premarket-degraded"}
      style={{ display: "flex", flexDirection: "column", gap: 8, padding: "12px 16px", borderRadius: 12, border: `1px solid var(--${tone}-line)`, background: `var(--${tone}-soft)`, fontSize: 13.5, lineHeight: 1.5, color: "var(--ink-2)" }}>
      <span className="nv-eyebrow" style={{ color: `var(--${tone})` }}>
        {blocked ? "Pre-market check blocked this session" : "Pre-market check ran degraded"} · {dateShort(cycle.session_date)}
      </span>
      <span data-testid="premarket-lead">
        {blocked
          ? "The desk did not scan or make a plan for this session, because the data it needs was not ready. Run session cycle again once it is."
          : `The cycle ran on what the check allowed${view.allowed ? ` (new risk in ${view.allowed} only)` : ""}.`}
      </span>
      {view.issues.length > 0 && (
        <ul style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 3 }}>
          {view.issues.map((i) => (
            <li key={i.name} data-testid="premarket-issue" data-check={i.name} data-status={i.status}>
              <b style={{ fontWeight: 500, color: "var(--ink)" }}>{i.label}</b> {i.state}: {i.detail}
            </li>
          ))}
        </ul>
      )}
      {view.reason && <span data-testid="premarket-reason">{view.reason}</span>}
    </div>
  );
}

// ── the screen ──────────────────────────────────────────────────────────────────────────────────────────────────────

export default function ScannerScreen() {
  const mobile = useIsMobile();
  const now = useNow(30_000);
  const qc = useQueryClient();
  const def = screenById("scanner");
  const status = useDeskStatus();
  const halted = !!stopEntriesOf(status.data);
  const accounts = useAccounts();
  const desk: Account[] = (accounts.data ?? []).filter((a) => a.kind !== "SIMULATION");
  const [acctSel, setAcctSel] = useState<string | null>(null);
  const account = desk.find((a) => a.account_id === acctSel) ?? desk.find((a) => a.status === "ACTIVE") ?? desk[0] ?? null;
  const accountId = account?.account_id ?? null;

  const [dir, setDir] = useState<Dir>("ALL");
  const [seg, setSeg] = useState<Seg>("ALL");
  const [min, setMin] = useState<number>(0);
  const [open, setOpen] = useState<string | null>(null);

  // Session cycle: the newest of the account, polled while it runs.
  const cycles = useCycles(accountId);
  const latest = cycles.data?.[0] ?? null;
  const [watchId, setWatchId] = useState<string | null>(null);
  const run = useRunCycle();
  const [already, setAlready] = useState<WorkflowRow | null>(null);
  useEffect(() => {
    if (!watchId && latest && OPEN_WF.has(latest.state)) setWatchId(latest.workflow_id);
  }, [latest, watchId]);
  const watched = useQuery(workflowQuery(watchId, (d: WorkflowDetail | undefined) => (!d || OPEN_WF.has(d.workflow.state) ? 2000 : false)));
  const watchedWf = watched.data?.workflow ?? null;
  const settled = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (watchedWf && !OPEN_WF.has(watchedWf.state) && !settled.current.has(watchedWf.workflow_id)) {
      settled.current.add(watchedWf.workflow_id);
      qc.invalidateQueries({ queryKey: ["desk"] });
    }
  }, [watchedWf, qc]);
  const runningCycle = !!watchedWf && OPEN_WF.has(watchedWf.state);
  const cycle = watchedWf && latest && watchedWf.workflow_id === latest.workflow_id ? watchedWf : latest;
  const out = outcomeOf(cycle);
  const scan = out.scan;
  const session = cycle?.session_date ?? null;
  const premarket = cycle && !OPEN_WF.has(cycle.state) ? premarketView(out) : null;

  const signals = useSessionSignals(accountId, session);
  const plans = useAccountPlans(accountId);
  const approvals = useDeskApprovals();
  const pin = (cycle?.input ?? {}) as Record<string, unknown>;
  const policy = usePolicyVersion(typeof pin.policy_id === "string" ? pin.policy_id : null, num(pin.policy_version));
  const minScore = num((policy.data?.body as Record<string, unknown> | undefined)?.min_signal_score);
  const aiTrader = useQuery(activityQuery("AI_TRADER"));

  const startCycle = () => {
    if (!accountId) return;
    setAlready(null);
    run.mutate(accountId, {
      onSuccess: (wf) => {
        if (OPEN_WF.has(wf.state)) setWatchId(wf.workflow_id);
        else if (isBlockedEarly(wf)) setWatchId(wf.workflow_id);     // blocked before any scan: say why, not "already ran"
        else setAlready(wf);
        qc.invalidateQueries({ queryKey: ["desk", "workflows", accountId, "SESSION_CYCLE"] });
      },
    });
  };

  // Rows: plan and latest approval per signal, status, filters.
  const sigs = signals.data ?? [];
  const planOf = useMemo(() => {
    const m = new Map<string, TradePlanRow>();
    for (const p of plans.data ?? []) if (p.signal_id && !m.has(p.signal_id)) m.set(p.signal_id, p);
    return m;
  }, [plans.data]);
  const apprOf = useMemo(() => {
    const m = new Map<string, ApprovalRow>();
    for (const a of approvals.data ?? []) if (!m.has(a.trade_id)) m.set(a.trade_id, a);   // list is newest first
    return m;
  }, [approvals.data]);
  const results = useMemo(() => new Map((out.proposals?.results ?? []).map((r) => [r.instrument, { result: r.result, state: r.state }])), [out.proposals]);
  const ctx = { now, minScore, heldBack: !!out.proposals?.held_back, results, plansReady: !!plans.data && !!approvals.data };
  const allRows: Row[] = sigs.map((s, i) => {
    const plan = planOf.get(s.signal_id);
    const appr = plan ? apprOf.get(plan.trade_id) : undefined;
    return { sig: s, rank: String(i + 1).padStart(2, "0"), score: num(s.signal_score) ?? 0, plan, status: statusOf(s, plan, appr, ctx) };
  });
  const rows = allRows.filter((r) => (dir === "ALL" || r.sig.direction === dir) && (seg === "ALL" || r.sig.segment === seg) && r.score >= min);
  const toggle = (id: string) => setOpen((x) => (x === id ? null : id));

  // Header and stats.
  const above = minScore == null ? null : allRows.filter((r) => r.score >= minScore).length;
  const waiting = allRows.filter((r) => r.status.label.startsWith("In approval")).length;
  const expiredUnused = allRows.filter((r) => !r.plan && r.sig.expires_at && new Date(r.sig.expires_at).getTime() < now).length;
  const scanTask = (aiTrader.data ?? []).find((t) => t.task_id === scan?.scan_task_id);
  const stored = storedFromRef(scanTask?.result_ref);
  const dupes = stored != null && scan?.signals != null ? Math.max(scan.signals - stored, 0) : null;
  const coverage = scan?.universe_size ? ((scan.scanned ?? 0) / scan.universe_size) * 100 : null;
  const aiStatus = status.data?.agents?.find((a) => a.agent_key === "AI_TRADER")?.status;
  const scanning = runningCycle || aiStatus === "BUSY";
  const version = versionLabel(sigs[0]?.model_version) ?? (scan?.rule_version ?? null);
  const noAccount = !accounts.isLoading && !accounts.error && desk.length === 0;
  const accountBlocked = account && account.status !== "ACTIVE";
  const runDisabled = !account || !!accountBlocked || run.isPending || runningCycle;
  const runWhy = !account ? "Create a paper account first (sidebar › New paper account)." : accountBlocked ? `The account is ${account!.status.toLowerCase()}.` : runningCycle ? "A cycle is running." : undefined;

  let headline: ReactNode = def.label;
  if (noAccount) headline = "No desk account yet.";
  else if (cycles.data && !latest) headline = "No session cycle has run on this desk yet.";
  else if (session && signals.data) {
    const n = above ?? sigs.length;
    headline = (
      <>
        {countWord(n)} signal{n === 1 ? "" : "s"} {above == null ? (n === 1 ? "was" : "were") + " published" : "cleared the line"} for {dateShort(session)}.{" "}
        {waiting > 0
          ? <><em style={{ color: "var(--mint)" }}>{countWord(waiting)}</em> {waiting === 1 ? "is already a plan" : "are already plans"} waiting on you.</>
          : "None is waiting on you."}
      </>
    );
  }

  const tableBody = () => {
    if (accounts.error) return <ErrorBox error={accounts.error} what="the desk accounts" />;
    if (cycles.error) return <ErrorBox error={cycles.error} what="the session cycles" onRetry={() => cycles.refetch()} />;
    if (accounts.isLoading || cycles.isLoading) return <Loading label="Loading the latest session" />;
    if (noAccount) return <Empty testId="scanner-no-account">The scanner works per desk account. Create a paper account in the sidebar, then run a session cycle.</Empty>;
    if (!latest) {
      return (
        <Empty testId="scanner-no-cycle">
          No session cycle has run for {account?.name ?? "this account"} yet. There is no scheduler in Phase 1: a person starts the
          cycle (pre-market check, market scan on the latest end-of-day data, then trade proposals) with Run session cycle.
        </Empty>
      );
    }
    if (signals.error) return <ErrorBox error={signals.error} what="the signals" onRetry={() => signals.refetch()} />;
    if (signals.isLoading) return <Loading label="Loading signals" />;
    if (!sigs.length) {
      return (
        <Empty testId="scanner-no-signals">
          The cycle for {dateLong(session)} published no signal
          {cycle?.state && OPEN_WF.has(cycle.state) ? " yet: it is still running" : isBlockedEarly(cycle) ? ": it was blocked before the scan" : ""}.
        </Empty>
      );
    }
    if (!rows.length) return <Empty testId="scanner-no-match">No signal matches these filters.</Empty>;
    return mobile
      ? <SignalCards rows={rows} open={open} toggle={toggle} now={now} halted={halted} />
      : <SignalTable rows={rows} open={open} toggle={toggle} now={now} halted={halted} />;
  };

  return (
    <div data-testid="screen-scanner" style={{ display: "flex", flexDirection: "column", gap: 22, fontFamily: "var(--sans)", color: "var(--ink)" }}>
      <section style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
          <span className="nv-eyebrow">{screenNo("scanner")} · {def.label}</span>
          <span className={scanning ? "nv-pill nv-pill-mint" : "nv-pill"} data-testid="ai-trader-pill">
            <span className="nv-dot" style={{ background: scanning ? "var(--mint)" : "var(--ink-3)" }} />AI Trader · {scanning ? "scanning" : (aiStatus ?? "status unknown").toLowerCase()}
          </span>
          {version && <span className="nv-pill" data-testid="rules-pill" style={{ textTransform: "none" }}>{version}</span>}
        </div>
        <h1 data-testid="scanner-headline" style={{ margin: 0, fontFamily: "var(--display)", fontWeight: 400, fontSize: mobile ? 30 : 44, lineHeight: 1.06, letterSpacing: "-0.02em", textWrap: "pretty", maxWidth: 900 } as CSSProperties}>
          {headline}
        </h1>
        <p style={{ margin: 0, fontSize: 14.5, lineHeight: 1.55, color: "var(--ink-3)", maxWidth: 700 }}>
          The score ranks evidence with versioned rules and is not a probability. A calibrated probability appears only
          where a validated, point-in-time study exists; missing data never counts as evidence.
        </p>
      </section>

      <section data-testid="scanner-stats" style={{ display: "grid", gridTemplateColumns: `repeat(auto-fit,minmax(${mobile ? "100px" : "150px"},1fr))`, gap: 10 }}>
        <StatTile testId="stat-universe" k="Universe" v={scan?.universe_size != null ? String(scan.universe_size) : DASH}
          s={scan ? `${scan.universe === "FNO" ? "F&O underlyings" : scan.universe ?? DASH} · data ${dateShort(scan.data_as_of)}` : "No scan yet"} />
        <StatTile testId="stat-coverage" k="Coverage" v={coverage == null ? DASH : `${coverage.toFixed(1)}%`} c={coverage == null ? "var(--ink)" : coverage >= 95 ? "var(--mint)" : "var(--amber)"}
          s={scan?.universe_size != null ? `${scan.universe_size - (scan.scanned ?? 0)} symbols missing data` : DASH} />
        <StatTile testId="stat-published" k="Published" v={scan?.signals != null ? String(scan.signals) : DASH} s={session ? `Session ${dateShort(session)}, all scores` : DASH} />
        <StatTile testId="stat-above" k={minScore == null ? "Above the minimum" : `Score ${px(minScore)}+`} v={above == null ? DASH : String(above)}
          s={policy.error ? `Policy not readable: ${errorText(policy.error)}` : "Policy minimum for a proposal"} />
        <StatTile testId="stat-dupes" k="Duplicates suppressed" v={dupes == null ? DASH : String(dupes)} c="var(--ink-2)"
          s={dupes == null && scan ? "Scan task not in recent activity" : "Same setup, same session"} />
        <StatTile testId="stat-expired" k="Expired unused" v={signals.data ? String(expiredUnused) : DASH} c="var(--ink-2)" s="Passed expiry without a plan" />
      </section>

      <section style={{ display: "flex", flexWrap: "wrap", gap: "10px 16px", alignItems: "center" }}>
        <ChipGroup testId="filter-direction" t="Direction" value={dir} onPick={setDir} opts={[["ALL", "All"], ["BULLISH", "Bullish"], ["BEARISH", "Bearish"]]} />
        <ChipGroup testId="filter-segment" t="Segment" value={seg} onPick={setSeg} opts={[["ALL", "All"], ["CASH", "Cash"], ["FUTURES", "Fut"], ["OPTIONS", "Opt"], ["INDEX", "Idx"]]} />
        <ChipGroup testId="filter-min" t="Min score" value={min} onPick={setMin} opts={[[0, "Any"], [60, "60"], [70, "70"]]} />
        <span style={{ flex: 1 }} />
        {desk.length > 1 && (
          <ChipGroup testId="filter-account" t="Account" value={accountId ?? ""} onPick={(v) => { setAcctSel(v); setOpen(null); setWatchId(null); setAlready(null); run.reset(); }}
            opts={desk.map((a) => [a.account_id, a.name] as [string, string])} />
        )}
        <button type="button" data-testid="run-cycle" onClick={startCycle} disabled={runDisabled} title={runWhy}
          style={{ cursor: runDisabled ? "not-allowed" : "pointer", opacity: runDisabled ? 0.55 : 1, padding: "8px 14px", borderRadius: 10, border: "1px solid transparent", background: "var(--mint)", color: "#06120B", fontSize: 13, fontWeight: 500, fontFamily: "var(--sans)", minHeight: mobile ? 44 : undefined }}>
          {run.isPending ? "Starting…" : runningCycle ? "Cycle running…" : "Run session cycle"}
        </button>
      </section>

      {(runWhy && !runningCycle) || halted ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: -10, fontSize: 12.5, lineHeight: 1.5, color: "var(--ink-3)" }}>
          {runWhy && !runningCycle && <span data-testid="run-why">{runWhy}</span>}
          {halted && <span data-testid="cycle-halted-note">Stop new entries is active: a session cycle still runs the pre-market check and the scan and publishes signals; its trade proposals are held back.</span>}
        </div>
      ) : null}

      {run.error && (
        <div role="alert" data-testid="cycle-error" style={{ display: "flex", flexDirection: "column", gap: 6, padding: "12px 16px", borderRadius: 12, border: "1px solid var(--danger-line)", background: "var(--danger-soft)", fontSize: 13.5, color: "var(--ink-2)" }}>
          <span className="nv-eyebrow" style={{ color: "var(--danger)" }}>Could not start the session cycle</span>
          <span>{errorText(run.error)}</span>
        </div>
      )}
      {already && (
        <div data-testid="cycle-already" style={{ padding: "10px 14px", borderRadius: 12, border: "1px solid var(--line-2)", background: "var(--bg-1)", fontSize: 13, lineHeight: 1.5, color: "var(--ink-2)" }}>
          The cycle for {dateLong(already.session_date)} already ran on this account ({cycleSummary(already)}). The desk runs one
          cycle per account and session.
        </div>
      )}
      {watchId && (watched.error ? (
        <ErrorBox error={watched.error} what="the running session cycle" onRetry={() => watched.refetch()} />
      ) : watchedWf ? (
        <div data-testid="cycle-status" data-state={watchedWf.state} style={{ display: "flex", flexWrap: "wrap", gap: "6px 10px", alignItems: "center", padding: "10px 14px", borderRadius: 12, border: `1px solid ${runningCycle ? "var(--mint-line)" : "var(--line-2)"}`, background: runningCycle ? "var(--mint-soft)" : "var(--bg-1)", fontSize: 13, lineHeight: 1.5, color: "var(--ink-2)" }}>
          <span className="nv-dot" style={{ background: runningCycle ? "var(--mint)" : watchedWf.state === "COMPLETED" ? "var(--ink-3)" : "var(--danger)" }} />
          <span className="nv-eyebrow" style={{ fontSize: 9.5 }}>Session cycle {shortId(watchedWf.workflow_id)} · {dateShort(watchedWf.session_date)}</span>
          <span>
            {runningCycle
              ? `Running since ${timeIST(watchedWf.created_at)} IST: pre-market check → market scan → trade proposals. This view refreshes when it ends.`
              : cycleSummary(watchedWf)}
          </span>
        </div>
      ) : null)}

      {cycle && premarket && <PremarketPanel cycle={cycle} view={premarket} />}

      {halted && (
        <div data-testid="scanner-halted" style={{ padding: "10px 14px", borderRadius: 12, border: "1px solid var(--danger-line)", background: "var(--danger-soft)", fontSize: 13, color: "var(--ink-2)" }}>
          New entries are stopped. Signals keep publishing for the record; strategy generation is paused until entries resume.
        </div>
      )}

      {(plans.error || approvals.error) && session && (
        <ErrorBox error={plans.error ?? approvals.error} what="plan status for these signals" onRetry={() => { plans.refetch(); approvals.refetch(); }} />
      )}

      {tableBody()}

      <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <span className="nv-eyebrow">Signal history · last 30 sessions · after costs, point-in-time</span>
        <PhaseNote phase={3} testId="history-phase-note">
          Hit rates and average R after costs per setup need closed paper trades. The desk records paper fills now, but
          positions stay open until Phase 3, so there is no history to score yet.
        </PhaseNote>
      </section>
    </div>
  );
}
