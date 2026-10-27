/**
 * Trade Desk — small pieces the views share: the panel, the lifecycle-state pill, signed P/L, label/value rows, and the
 * words for states, entry rules and exit reasons. Formatting only: every figure is the route's.
 */
import type { CSSProperties, ReactNode } from "react";
import { TONE_COLOR, fmtINR, signTone, type Tone } from "../../../../components/ui";
import { fmtPrice } from "../../../trading/parts";
import type { EntryRule, PaperTrade } from "../../desk-trading";

export const quiet: CSSProperties = { fontSize: 12, lineHeight: 1.55, color: "var(--cp-ink-3)" };
export const linkBtn: CSSProperties = { padding: 0, border: 0, background: "none", cursor: "pointer", font: "inherit", color: "var(--mint)" };

/** A titled panel in the V5 look: mono eyebrow, a note on the right, a soft card. */
export function Panel({ title, note, testId, children, pad = true }: { title: ReactNode; note?: ReactNode; testId?: string; children: ReactNode; pad?: boolean }) {
  return (
    <section data-testid={testId} className="flex min-w-0 flex-col" style={{ gap: 12, padding: pad ? "16px 16px 14px" : "16px 0 6px", borderRadius: 16, border: "1px solid var(--cp-line)", background: "var(--bg-1)" }}>
      <div className="flex flex-wrap items-baseline justify-between" style={{ gap: "4px 12px", padding: pad ? 0 : "0 16px" }}>
        <h3 className="cp-eyebrow m-0" style={{ color: "var(--cp-ink-2)" }}>{title}</h3>
        {note && <span className="cp-mono-note" style={{ minWidth: 0 }}>{note}</span>}
      </div>
      {children}
    </section>
  );
}

/** The lifecycle state (trade-lifecycle-v1) in words, with its tone. */
export const STATE_WORDS: Record<string, { label: string; tone: Tone }> = {
  NO_SETUP: { label: "No setup", tone: "ink" },
  WAIT_FOR_CONFIRMATION: { label: "Waiting for confirmation", tone: "amber" },
  TRADE_ELIGIBLE: { label: "Waiting for entry", tone: "amber" },
  ENTRY_TRIGGERED: { label: "Entry triggered", tone: "indigo" },
  POSITION_OPEN: { label: "Position open", tone: "mint" },
  EXIT_PENDING: { label: "Exit pending", tone: "amber" },
  CLOSED: { label: "Closed", tone: "ink" },
  REJECTED: { label: "Rejected", tone: "danger" },
};

export function StatePill({ state, fallback, testId }: { state: string | null; fallback?: string; testId?: string }) {
  const w = state ? STATE_WORDS[state] : null;
  const label = w?.label ?? (state ? state.replace(/_/g, " ").toLowerCase() : fallback ?? "state not recorded");
  const tone = w?.tone ?? "ink";
  return (
    <span data-testid={testId} data-state={state ?? ""} className="cp-num"
      style={{ display: "inline-block", padding: "3px 8px", borderRadius: 6, fontSize: 9.5, letterSpacing: "0.1em", textTransform: "uppercase", whiteSpace: "nowrap",
        color: TONE_COLOR[tone], background: tone === "ink" ? "var(--bg-3)" : `color-mix(in srgb, ${TONE_COLOR[tone]} 14%, transparent)`, border: `1px solid color-mix(in srgb, ${TONE_COLOR[tone]} 35%, transparent)` }}>
      {label}
    </span>
  );
}

export function Pnl({ rs, testId, big }: { rs: number | null; testId?: string; big?: boolean }) {
  const tone = signTone(rs);
  return (
    <span data-testid={testId} className="cp-num" style={{ color: tone === "ink" ? "var(--cp-ink-2)" : TONE_COLOR[tone], ...(big ? { fontFamily: "var(--display)", fontSize: 26, lineHeight: 1 } : {}) }}>
      {fmtINR(rs, { signed: true })}
    </span>
  );
}

/** Rupees with paise, signed ("+₹1,234.50" / "−₹40.00"). */
export function rsSigned(n: number | null): string {
  if (n == null || !Number.isFinite(n)) return "—";
  const s = fmtPrice(Math.abs(n));
  return n < 0 ? `−${s}` : n > 0 ? `+${s}` : s;
}

/** The entry rule as the owner's design words it: "Break above ₹1,655.00 · valid 3 sessions". */
export const RULE_WORD: Record<EntryRule, string> = { at_once: "At once at", break_above: "Break above", pullback_to: "Pull back to" };
export function entryRuleLine(t: PaperTrade): string {
  const base = `${RULE_WORD[t.entryRule]} ${fmtPrice(t.entry)}`;
  if (t.entryRule === "at_once") return base;
  return t.entryWindowSessions != null ? `${base} · valid ${t.entryWindowSessions} session${t.entryWindowSessions === 1 ? "" : "s"}` : `${base} · validity not recorded`;
}

/** Exit reasons (exit-rules-v1) in words. A code this screen does not know is shown as sent. */
export const EXIT_WORDS: Record<string, { label: string; tone: Tone }> = {
  stop: { label: "Stop", tone: "danger" },
  trailing_stop: { label: "Trailing stop", tone: "danger" },
  target: { label: "Target", tone: "mint" },
  time: { label: "Time exit", tone: "ink" },
  trend: { label: "Trend exit", tone: "ink" },
  manual: { label: "Closed by you", tone: "ink" },
  risk_control: { label: "Risk control", tone: "amber" },
  entry_not_reached: { label: "Entry not reached", tone: "amber" },
  cancelled: { label: "Cancelled", tone: "ink" },
  expiry: { label: "Expired", tone: "ink" },
  roll: { label: "Rolled", tone: "ink" },
};

/** The exit flags the owner asked to see, in the design's words; the route's own text follows each. */
export const FLAG_LEAD: Record<string, (day: string) => string> = {
  both_in_range: (day) => `Stop and target both touched${day ? ` on ${day}` : ""}: stop assumed`,
  gap_through_stop: () => "Gapped through the stop: filled at the open",
  entry_gap: () => "Gapped through the entry: filled at the open",
};

/** label · value rows. */
export function Kv({ rows, testPrefix }: { rows: Array<[string, ReactNode, string]>; testPrefix: string }) {
  return (
    <dl className="m-0 grid" style={{ gridTemplateColumns: "minmax(0,140px) minmax(0,1fr)", gap: "6px 12px", fontSize: 12.5, lineHeight: 1.45 }}>
      {rows.map(([k, v, id]) => (
        <div key={id} className="contents">
          <dt style={{ color: "var(--cp-ink-3)" }}>{k}</dt>
          <dd data-testid={`${testPrefix}-${id}`} className="m-0" style={{ color: "var(--cp-ink)", minWidth: 0, overflowWrap: "anywhere" }}>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export const PAPER_ONLY = "Paper only: simulated, and nothing is sent to a broker.";
