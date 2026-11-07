/**
 * Scanner-to-Paper Trading screens — the small parts the three screens share: the width probe (cards under 640 px), the
 * detail drawer, the state words and tones, figure formatting and the refusal line. Formatting only: every figure is the
 * route's (spt-api.ts); a missing one is "—".
 */
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import type { Tone } from "../../../../components/ui";
import { fmtINR } from "../../../../components/ui";
import { useCopilotShell } from "../../../../lib/shell-context";
import { quiet } from "./parts";
import { MONO, Pill } from "./pnl-ui";
import type { SptProblem } from "./spt-api";

/** True while the element is narrower than `px` (the P&L dashboard's rule: cards under 640 px of room). */
export function useNarrow(px = 640): [boolean, (el: HTMLDivElement | null) => void] {
  const [narrow, setNarrow] = useState(false);
  const [node, setNode] = useState<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!node) return;
    setNarrow(node.getBoundingClientRect().width < px);
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([e]) => { if (e) setNarrow(e.contentRect.width < px); });
    ro.observe(node);
    return () => ro.disconnect();
  }, [node, px]);
  return [narrow, setNode];
}

// ── words ────────────────────────────────────────────────────────────────

const word = (label: string, tone: Tone) => ({ label, tone });
/** Opportunity states (market-wide; services/spt/constants OPP_*). */
export const OPP_STATE: Record<string, { label: string; tone: Tone }> = {
  CREATED: word("Created", "ink"), VALIDATING: word("Validating", "indigo"), QUALIFIED: word("Qualified", "mint"),
  CONDITIONAL: word("Conditional", "amber"), WATCHLIST: word("Watchlist", "indigo"), REJECTED: word("Rejected", "danger"),
  EXPIRED: word("Expired", "ink"), DATA_INSUFFICIENT: word("Data insufficient", "amber"),
};
/** Proposal states (per account; PROP_*). */
export const PROP_STATE: Record<string, { label: string; tone: Tone }> = {
  PROPOSAL_GENERATED: word("Proposal made", "ink"), AWAITING_RISK: word("Awaiting risk check", "indigo"), BLOCKED_BY_RISK: word("Blocked by risk", "danger"),
  REJECTED: word("Not proposed", "danger"), NOT_TRADABLE: word("Tracked only (not tradable)", "ink"), RISK_APPROVED: word("Risk approved", "mint"),
  AWAITING_USER_APPROVAL: word("Awaiting your approval", "amber"), USER_REJECTED: word("Rejected by you", "ink"), APPROVAL_EXPIRED: word("Approval expired", "ink"),
  READY_FOR_ORDER: word("Order being placed", "indigo"), ORDER_CREATED: word("Paper order created", "mint"), TRACKING_ONLY: word("Tracked, no order", "indigo"),
};
/** Risk decisions (PRD §9.9; RISK_*). */
export const RISK_DECISION: Record<string, { label: string; tone: Tone }> = {
  APPROVE: word("Approved", "mint"), APPROVE_REDUCED: word("Approved, reduced", "mint"), CONDITIONAL_APPROVAL: word("Approved on a condition", "amber"),
  REJECT: word("Rejected", "danger"), BLOCKED: word("Blocked", "danger"), EXIT_REQUIRED: word("Exit required", "danger"), HALT_ACCOUNT: word("Account halted", "danger"),
};
/** Paper order states (ORD_*). */
export const ORDER_STATE: Record<string, { label: string; tone: Tone }> = {
  CREATED: word("Created", "indigo"), VALIDATED: word("Validated", "indigo"), PENDING: word("Pending", "amber"), PARTIALLY_FILLED: word("Partly filled", "amber"),
  FILLED: word("Filled", "mint"), CANCELLED: word("Cancelled", "ink"), EXPIRED: word("Expired", "ink"), REJECTED: word("Rejected", "danger"),
};

const fallbackWord = (code: string) => code.replace(/_/g, " ").toLowerCase();

/** A state pill from one of the maps above; an unknown code is shown as sent. */
export function StateTag({ map, code, testId, empty = "—" }: { map: Record<string, { label: string; tone: Tone }>; code: string | null; testId?: string; empty?: string }) {
  if (!code) return <span data-testid={testId} style={{ color: "var(--cp-ink-3)" }}>{empty}</span>;
  const w = map[code];
  return (
    <Pill tone={w?.tone ?? "ink"} testId={testId} attrs={{ "data-code": code }} style={{ padding: "2px 8px", fontSize: 9.5 }}>
      {w?.label ?? fallbackWord(code)}
    </Pill>
  );
}

// ── figures ──────────────────────────────────────────────────────────────

/** ₹ with paise ("₹1,413.21"), or "—". */
export const price = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? "—" : `₹${v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);
/** Whole rupees ("₹49,463"), compact only from one lakh ("₹1.24 L", "₹1.00 Cr"). */
export const rupees = (v: number | null | undefined, signed = false) => fmtINR(v ?? null, { compact: v != null && Math.abs(v) >= 1_00_000, signed });
export const pct = (v: number | null | undefined, d = 1) => (v == null || !Number.isFinite(v) ? "—" : `${v.toFixed(d)}%`);
export const fixed = (v: number | null | undefined, d = 2) => (v == null || !Number.isFinite(v) ? "—" : v.toFixed(d));
export const count = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? "—" : v.toLocaleString("en-IN"));

const IST = new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
/** "05 Nov, 10:42" in IST, or "—". */
export function istTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  return Number.isFinite(t) ? `${IST.format(new Date(t))} IST` : iso;
}

/** "12m 04s left" / "expired" for an ISO expiry, against `now`. */
export function countdown(iso: string | null | undefined, now: Date): { text: string; expired: boolean } | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return null;
  const s = Math.floor((t - now.getTime()) / 1000);
  if (s <= 0) return { text: "expired", expired: true };
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return { text: `${h ? `${h}h ` : ""}${String(m).padStart(h ? 2 : 1, "0")}m ${String(sec).padStart(2, "0")}s left`, expired: false };
}

// ── pieces ───────────────────────────────────────────────────────────────

export const mono: CSSProperties = { fontFamily: MONO, fontSize: 12 };
export const btn: CSSProperties = { padding: "7px 14px", borderRadius: 10, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--cp-ink)", font: "inherit", fontSize: 12.5, cursor: "pointer" };
export const btnPrimary: CSSProperties = { ...btn, borderColor: "var(--mint-line)", background: "var(--mint-soft)", color: "var(--mint)" };
export const btnDanger: CSSProperties = { ...btn, borderColor: "var(--danger-line)", background: "var(--danger-soft)", color: "var(--cp-danger)" };
export const input: CSSProperties = { padding: "6px 10px", borderRadius: 8, border: "1px solid var(--line-2)", background: "var(--bg-0, var(--bg-2))", color: "var(--cp-ink)", font: "inherit", fontSize: 12.5, minWidth: 0 };

/** A refusal: the server's code, its sentence, the reason codes and (config) the fields named. */
export function ProblemLine({ p, testId, lead }: { p: SptProblem; testId: string; lead?: string }) {
  return (
    <div data-testid={testId} data-code={p.code ?? ""} role="alert" className="flex min-w-0 flex-col" style={{ gap: 4, padding: "8px 12px", borderRadius: 10, border: "1px solid var(--danger-line)", background: "var(--danger-soft)", fontSize: 12.5, lineHeight: 1.5 }}>
      <span style={{ color: "var(--cp-danger)", overflowWrap: "anywhere" }}>
        {lead ? `${lead} ` : ""}{p.code ? <span style={mono}>{p.code}</span> : null}{p.code ? " · " : ""}{p.message}
      </span>
      {p.reasonCodes.length > 0 && <span data-testid={`${testId}-codes`} style={{ ...mono, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>{p.reasonCodes.join(" · ")}</span>}
    </div>
  );
}

/** label · value rows; a value may be any node. */
export function Rows({ rows, testPrefix }: { rows: Array<[string, ReactNode, string]>; testPrefix: string }) {
  return (
    <dl className="m-0 grid" style={{ gridTemplateColumns: "minmax(0,170px) minmax(0,1fr)", gap: "6px 12px", fontSize: 12.5, lineHeight: 1.45 }}>
      {rows.map(([k, v, id]) => (
        <div key={id} className="contents">
          <dt style={{ color: "var(--cp-ink-3)" }}>{k}</dt>
          <dd data-testid={`${testPrefix}-${id}`} className="m-0" style={{ color: "var(--cp-ink)", minWidth: 0, overflowWrap: "anywhere" }}>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

/** The scalar fields of a backend object (validation market / stock / liquidity) as rows, as sent. */
export function ObjectRows({ obj, testPrefix }: { obj: Record<string, unknown> | null; testPrefix: string }) {
  if (!obj) return <span style={quiet}>Not recorded.</span>;
  const rows: Array<[string, ReactNode, string]> = Object.entries(obj)
    .filter(([, v]) => v == null || typeof v !== "object" || (Array.isArray(v) && v.every((x) => typeof x !== "object")))
    .map(([k, v]) => [k.replace(/_/g, " "), v == null ? "—" : Array.isArray(v) ? v.join(", ") || "—" : typeof v === "number" ? v.toLocaleString("en-IN", { maximumFractionDigits: 4 }) : String(v), k]);
  return rows.length ? <Rows rows={rows} testPrefix={testPrefix} /> : <span style={quiet}>Not recorded.</span>;
}

export function Section({ title, testId, children, note }: { title: string; testId?: string; children: ReactNode; note?: ReactNode }) {
  return (
    <section data-testid={testId} className="flex min-w-0 flex-col" style={{ gap: 8 }}>
      <div className="flex flex-wrap items-baseline justify-between" style={{ gap: "2px 10px" }}>
        <h4 className="cp-eyebrow m-0" style={{ color: "var(--cp-ink-2)" }}>{title}</h4>
        {note && <span style={{ ...quiet, fontSize: 11 }}>{note}</span>}
      </div>
      {children}
    </section>
  );
}

/** A right-hand dialog over the page (the desk's drawer: Escape, ✕ and the backdrop close it; full width on a phone). */
export function SptDrawer({ label, eyebrow, title, sub, onClose, testId, children }: {
  label: string; eyebrow: string; title: ReactNode; sub?: ReactNode; onClose: () => void; testId: string; children: ReactNode;
}) {
  const { mobile } = useCopilotShell();
  const closeRef = useRef<HTMLButtonElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeRef.current?.focus({ preventScroll: true });
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onCloseRef.current(); };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      opener?.focus({ preventScroll: true });
    };
  }, []);
  return (
    <>
      <div data-testid={`${testId}-backdrop`} aria-hidden onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 70, background: "rgba(4,7,12,0.62)" }} />
      <div data-testid={testId} role="dialog" aria-modal="true" aria-label={label} className="flex flex-col"
        style={{ position: "fixed", top: 0, right: 0, bottom: 0, zIndex: 71, width: mobile ? "100vw" : "min(600px, 100vw)", maxWidth: "100vw", background: "var(--bg-1)",
          borderLeft: mobile ? undefined : "1px solid var(--line-2)", boxShadow: "-24px 0 60px rgba(0,0,0,0.35)" }}>
        <div className="flex items-start" style={{ flex: "none", gap: 12, padding: mobile ? "14px 16px 10px" : "20px 24px 12px", borderBottom: "1px solid var(--cp-line)" }}>
          <div className="flex min-w-0 flex-col" style={{ flex: 1, gap: 4 }}>
            <span className="cp-eyebrow" style={{ fontSize: 9.5 }}>{eyebrow}</span>
            <div className="min-w-0" style={{ fontFamily: "var(--display)", fontSize: mobile ? 22 : 26, lineHeight: 1.15 }}>{title}</div>
            {sub && <div style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>{sub}</div>}
          </div>
          <button ref={closeRef} type="button" data-testid={`${testId}-close`} aria-label="Close" onClick={onClose}
            style={{ flex: "none", width: 40, height: 40, borderRadius: 12, border: "1px solid var(--line-2)", background: "transparent", color: "var(--cp-ink-2)", fontSize: 15, cursor: "pointer" }}>
            ✕
          </button>
        </div>
        <div className="cp-scroll flex min-w-0 flex-col" style={{ flex: 1, minHeight: 0, overflowY: "auto", overflowX: "hidden", gap: 18, padding: mobile ? "12px 16px 32px" : "16px 24px 40px" }}>
          {children}
        </div>
      </div>
    </>
  );
}
