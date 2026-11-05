/**
 * Risk Desk › Scanner-to-Paper Trading views — the parts the three views share: the account gate (the caller's account id
 * from GET /api/v1/paper/accounts), the mode / kill-switch / ladder pills, the drawdown ladder, a figure list, a table
 * that becomes cards on a phone, the "not available in this release" panel and the links to Trade Desk › Paper Trading.
 */
import type { CSSProperties, ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { LoadingBlock, Pill, TONE_COLOR, fmtINR, fmtPct, type Tone } from "../../../../components/ui";
import { useCopilotShell } from "../../../../lib/shell-context";
import { QueryProblem } from "../../../trading/parts";
import { canonical, VIEW_PARAMS } from "../../desk-nav";
import { quiet } from "./parts";
import { useSptAccount, type SptAccount, type SptLadder, type SptLadderThresholds, type SptRiskAccount } from "./spt-risk-api";

export const DASH = "—";
export const rs = (v: number | null | undefined) => fmtINR(v ?? null);
export const pct2 = (v: number | null | undefined) => fmtPct(v ?? null, { digits: 2 });
const plain = (v: number | null | undefined, d = 2) => (v == null || !Number.isFinite(v) ? DASH : new Intl.NumberFormat("en-IN", { maximumFractionDigits: d }).format(v));
export const fig = plain;

/** The SPT paper account the views read; the account id is the caller's user id (DESIGN D3), never guessed. */
export function SptAccountGate({ head, children }: { head: ReactNode; children: (acc: SptAccount) => ReactNode }) {
  const q = useSptAccount();
  if (q.isPending) return <>{head}<LoadingBlock label="Reading your paper account" rows={3} /></>;
  if (q.isError) return <>{head}<div data-testid="spt-account-error"><QueryProblem what="Your paper account" error={q.error} onRetry={() => { void q.refetch(); }} /></div></>;
  if (!q.data) {
    return (
      <>
        {head}
        <p data-testid="spt-account-none" role="note" className="m-0" style={{ fontSize: 14, color: "var(--cp-ink-2)" }}>
          No paper account was returned for you, so there is nothing to show here.
        </p>
      </>
    );
  }
  return <>{children(q.data)}</>;
}

// ── states ───────────────────────────────────────────────────────────────

export const MODE_WORDS: Record<string, string> = {
  off: "Off — nothing is proposed or ordered",
  tracking: "Tracking — opportunities are followed, nothing is ordered",
  approval: "Approval — each proposal waits for your approval",
  auto: "Auto — proposals that pass the risk checks are ordered on paper",
};
const MODE_TONE: Record<string, Tone> = { off: "ink", tracking: "indigo", approval: "mint", auto: "amber" };

export function ModePill({ mode }: { mode: string | null }) {
  return (
    <span data-testid="spt-mode" data-mode={mode ?? "unknown"}>
      <Pill tone={mode ? MODE_TONE[mode] ?? "ink" : "ink"}>SPT mode: {mode ?? "unknown"}</Pill>
    </span>
  );
}

const KS_TONE: Record<string, Tone> = { ACTIVE: "mint", TRIGGERED: "danger", RESTRICTED: "amber", RESET_PENDING: "amber", DISABLED: "ink" };
export const ksTone = (s: string | null): Tone => (s ? KS_TONE[s] ?? "ink" : "ink");

export function KillSwitchPill({ state, testId = "spt-ks-state" }: { state: string | null; testId?: string }) {
  return (
    <span data-testid={testId} data-state={state ?? "unknown"}>
      <Pill tone={ksTone(state)}>Kill switch: {state ?? "unknown"}</Pill>
    </span>
  );
}

const BAND_TONE: Record<string, Tone> = { normal: "mint", reduce: "amber", restricted: "danger", halt: "danger", unknown: "amber" };
export const bandTone = (b: string | null): Tone => (b ? BAND_TONE[b] ?? "ink" : "ink");

export function BandPill({ band }: { band: string | null }) {
  return (
    <span data-testid="spt-band" data-band={band ?? "unknown"}>
      <Pill tone={bandTone(band)}>Drawdown band: {band ?? "unknown"}</Pill>
    </span>
  );
}

/** The four bands of the drawdown ladder (PRD §9.7), the account's band marked, the thresholds from the API. */
export function LadderBands({ ladder, testId = "spt-ladder" }: { ladder: SptLadder; testId?: string }) {
  const t: SptLadderThresholds = ladder.thresholds;
  const r = (lo: number | null, hi: number | null) => (lo == null && hi == null ? DASH : lo == null ? `below ${plain(hi)}%` : hi == null ? `${plain(lo)}% and above` : `${plain(lo)}–${plain(hi)}%`);
  const bands: Array<{ key: string; label: string; range: string; rule: string }> = [
    { key: "normal", label: "Normal", range: r(null, t.reduceAtPct), rule: "configured risk" },
    { key: "reduce", label: "Reduce", range: r(t.reduceAtPct, t.restrictAtPct), rule: t.reduceFactor != null ? `new trade risk × ${plain(t.reduceFactor)}` : "new trade risk reduced" },
    { key: "restricted", label: "Restricted", range: r(t.restrictAtPct, t.haltAtPct), rule: "new positions blocked" },
    { key: "halt", label: "Halt", range: r(t.haltAtPct, null), rule: "new positions refused" },
  ];
  return (
    <div data-testid={testId} className="flex min-w-0 flex-col" style={{ gap: 8 }}>
      <ol className="m-0 grid p-0" style={{ listStyle: "none", gap: 6, gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,130px),1fr))" }}>
        {bands.map((b) => {
          const on = ladder.band === b.key;
          const tone = BAND_TONE[b.key];
          return (
            <li key={b.key} data-testid={`${testId}-${b.key}`} data-current={on ? "true" : "false"} className="flex min-w-0 flex-col"
              style={{ gap: 2, padding: "8px 10px", borderRadius: 10, border: `1px solid ${on ? TONE_COLOR[tone] : "var(--line-2)"}`, background: on ? "var(--bg-2)" : "transparent" }}>
              <span style={{ fontSize: 13, color: on ? TONE_COLOR[tone] : "var(--cp-ink)", fontWeight: on ? 600 : 400 }}>{b.label}{on ? " · now" : ""}</span>
              <span className="cp-num" style={{ fontSize: 12, color: "var(--cp-ink-2)" }}>{b.range}</span>
              <span style={{ fontSize: 11.5, color: "var(--cp-ink-3)" }}>{b.rule}</span>
            </li>
          );
        })}
      </ol>
      {ladder.band === "unknown" && <span data-testid={`${testId}-unknown`} style={{ ...quiet, color: TONE_COLOR.amber }}>Band unknown: new positions are blocked until drawdown can be measured.</span>}
      <span data-testid={`${testId}-text`} style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>
        {ladder.text ?? "The API sent no band text."}
      </span>
    </div>
  );
}

// ── figures ──────────────────────────────────────────────────────────────

/** One figure line: label, value, and an optional note under it. */
export function FigRow({ k, v, testId, tone = "ink", note }: { k: ReactNode; v: ReactNode; testId: string; tone?: Tone; note?: ReactNode }) {
  return (
    <li data-testid={testId} className="flex min-w-0 flex-col" style={{ gap: 2, padding: "8px 0", borderTop: "1px solid var(--cp-line)" }}>
      <span className="flex min-w-0 flex-wrap items-baseline justify-between" style={{ gap: "2px 12px" }}>
        <span style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>{k}</span>
        <span data-testid={`${testId}-value`} className="cp-num" style={{ fontSize: 14, color: TONE_COLOR[tone], overflowWrap: "anywhere" }}>{v}</span>
      </span>
      {note && <span data-testid={`${testId}-note`} style={{ ...quiet, overflowWrap: "anywhere" }}>{note}</span>}
    </li>
  );
}

export function FigList({ children, testId }: { children: ReactNode; testId?: string }) {
  return <ul data-testid={testId} className="m-0 flex min-w-0 flex-col p-0" style={{ listStyle: "none" }}>{children}</ul>;
}

/** "used of limit" in words for a % figure: "0.50% of 2% limit". */
export const usedOf = (used: number | null, limit: number | null) => `${pct2(used)} of ${limit == null ? DASH : `${plain(limit)}%`} limit`;
export const lossTone = (used: number | null, limit: number | null): Tone =>
  used == null || limit == null || limit <= 0 ? "ink" : used >= limit ? "danger" : used >= limit * 0.7 ? "amber" : "mint";

// ── a table on a wide screen, cards on a phone ───────────────────────────

export interface Col<T> { key: string; head: string; cell: (r: T) => ReactNode; num?: boolean }

export function RowsTable<T>({ rows, cols, rowKey, testId, empty }: { rows: T[]; cols: Col<T>[]; rowKey: (r: T, i: number) => string; testId: string; empty?: ReactNode }) {
  const { mobile } = useCopilotShell();
  if (!rows.length) return <p data-testid={`${testId}-empty`} className="m-0" style={{ ...quiet, fontSize: 13 }}>{empty ?? "Nothing to show."}</p>;
  if (mobile) {
    return (
      <ul data-testid={testId} className="m-0 flex min-w-0 flex-col p-0" style={{ listStyle: "none", gap: 8 }}>
        {rows.map((r, i) => (
          <li key={rowKey(r, i)} data-testid={`${testId}-row`} className="flex min-w-0 flex-col" style={{ gap: 4, padding: "10px 12px", borderRadius: 12, border: "1px solid var(--line-2)" }}>
            {cols.map((c) => (
              <span key={c.key} data-testid={`${testId}-${c.key}`} className="flex min-w-0 flex-wrap justify-between" style={{ gap: "0 10px", fontSize: 12.5 }}>
                <span style={{ color: "var(--cp-ink-3)" }}>{c.head}</span>
                <span className={c.num ? "cp-num" : undefined} style={{ color: "var(--cp-ink)", overflowWrap: "anywhere", minWidth: 0 }}>{c.cell(r)}</span>
              </span>
            ))}
          </li>
        ))}
      </ul>
    );
  }
  const th: CSSProperties = { textAlign: "left", fontSize: 11.5, fontWeight: 500, color: "var(--cp-ink-3)", padding: "6px 8px", borderBottom: "1px solid var(--line-2)", whiteSpace: "nowrap" };
  const td: CSSProperties = { fontSize: 13, color: "var(--cp-ink)", padding: "7px 8px", borderBottom: "1px solid var(--cp-line)", verticalAlign: "top" };
  return (
    <div className="min-w-0" style={{ overflowX: "auto" }}>
      <table data-testid={testId} style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr>{cols.map((c) => <th key={c.key} scope="col" style={{ ...th, textAlign: c.num ? "right" : "left" }}>{c.head}</th>)}</tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={rowKey(r, i)} data-testid={`${testId}-row`}>
              {cols.map((c) => <td key={c.key} data-testid={`${testId}-${c.key}`} className={c.num ? "cp-num" : undefined} style={{ ...td, textAlign: c.num ? "right" : "left" }}>{c.cell(r)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── not available ────────────────────────────────────────────────────────

export function NotAvailable({ testId, title, why }: { testId: string; title: string; why: ReactNode }) {
  return (
    <div data-testid={testId} role="note" className="flex min-w-0 flex-col" style={{ gap: 4, padding: "12px 14px", borderRadius: 12, border: "1px dashed var(--line-3)", background: "var(--bg-1)" }}>
      <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <span style={{ fontSize: 14, color: "var(--cp-ink)" }}>{title}</span>
        <Pill tone="ink">not available in this release</Pill>
      </span>
      <span style={{ ...quiet, overflowWrap: "anywhere" }}>{why}</span>
    </div>
  );
}

// ── the account's warnings (overview, portfolio risk) ────────────────────

/** Every warning the API itself states: the kill switch's reasons, why equity is unknown, the read error, unpriced entries. */
export function warningsOf(a: SptRiskAccount): Array<{ key: string; text: string; tone: Tone }> {
  const out: Array<{ key: string; text: string; tone: Tone }> = [];
  if (a.error) out.push({ key: "error", text: `The account could not be read: ${a.error}.`, tone: "danger" });
  for (const [i, r] of a.killSwitch.reasons.entries()) {
    const danger = a.killSwitch.state === "TRIGGERED" || /halt|kill|unreadable/.test(r.code ?? "");
    out.push({ key: `ks-${r.code ?? i}-${i}`, text: r.text, tone: danger ? "danger" : "amber" });
  }
  for (const [i, t] of a.equityUnknownReasons.entries()) out.push({ key: `eq-${i}`, text: `Equity unknown: ${t}`, tone: "amber" });
  const unpriced = a.sptRisk?.unpriced ?? [];
  if (unpriced.length) out.push({ key: "unpriced", text: `${unpriced.length} SPT ${unpriced.length === 1 ? "entry has" : "entries have"} no quantity, price or stop yet and ${unpriced.length === 1 ? "is" : "are"} left out of the risk totals.`, tone: "amber" });
  return out;
}

export function Warnings({ a, testId = "spt-warnings" }: { a: SptRiskAccount; testId?: string }) {
  const w = warningsOf(a);
  if (!w.length) return <p data-testid={`${testId}-none`} className="m-0" style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>No active risk warnings from the risk engine.</p>;
  return (
    <ul data-testid={testId} className="m-0 flex min-w-0 flex-col p-0" style={{ listStyle: "none", gap: 6 }}>
      {w.map((x) => (
        <li key={x.key} data-testid={`${testId}-item`} data-tone={x.tone} style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink)", padding: "8px 10px", borderRadius: 10, overflowWrap: "anywhere",
          border: `1px solid ${x.tone === "danger" ? "var(--danger-line)" : "var(--amber-line)"}`, background: x.tone === "danger" ? "var(--cp-danger-soft)" : "var(--amber-soft)" }}>
          {x.text}
        </li>
      ))}
    </ul>
  );
}

// ── links to Trade Desk › Paper Trading ──────────────────────────────────

/** A link to a Paper Trading sub-view, keeping the desk's own params (persona) and dropping this view's. */
export function PaperLink({ sub, testId, children }: { sub: "opportunities" | "pnl" | "settings" | "analytics"; testId: string; children: ReactNode }) {
  const [params] = useSearchParams();
  const p = new URLSearchParams(params);
  for (const k of [...VIEW_PARAMS, "view", "section"]) p.delete(k);
  p.set("tab", "trade");
  p.set("view", "paper");
  p.set("sub", sub);
  return (
    <Link data-testid={testId} to={{ search: `?${canonical(p).toString()}` }} style={{ color: "var(--mint)", textDecoration: "underline", fontSize: 13 }}>
      {children}
    </Link>
  );
}

/** The paper-only line, as the existing views say it, plus where the figures come from. */
export function SourceNote({ children, testId }: { children: ReactNode; testId: string }) {
  return <p data-testid={testId} className="m-0" style={{ ...quiet, overflowWrap: "anywhere" }}>{children}</p>;
}
