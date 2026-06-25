/**
 * AdvisorDashboard — derivations + tone system.
 *
 * Ported 1:1 from the V2 MfdDashboard (backend signals are identical) but
 * re-expressed in the V5 semantic design tokens:
 *   rose → neg · amber → warm · emerald → pos · indigo → accent · slate → neutral
 *
 * The backend (/api/mfd/profiles) returns portfolio_score, risk_score and a
 * priority object { score, bucket, factors, reasons, dominant_action }. We
 * blend quality + inverted risk into a single Health score (north-star) while
 * still exposing the sub-scores inline.
 */
import {
  RefreshCw, Scale, TrendingUp, Plus, Eye, CheckCircle2, ClipboardCheck,
  type LucideIcon,
} from "lucide-react";
import type { ClientProfileC } from "@/services/contracts/advisor.contract";

export type Tone = "neg" | "warm" | "pos" | "accent" | "neutral";

export interface ToneClasses {
  text: string;
  bg: string;
  border: string;
  dot: string;
  btn: string;
}

/** Token-based tone classes — opacity modifiers work on the semantic colors. */
export const TONE: Record<Tone, ToneClasses> = {
  neg:     { text: "text-neg",    bg: "bg-neg/10",     border: "border-neg/30",     dot: "bg-neg",    btn: "bg-neg text-white hover:opacity-90" },
  warm:    { text: "text-warm",   bg: "bg-warm/10",    border: "border-warm/30",    dot: "bg-warm",   btn: "bg-warm text-white hover:opacity-90" },
  pos:     { text: "text-pos",    bg: "bg-pos/10",     border: "border-pos/30",     dot: "bg-pos",    btn: "bg-pos text-white hover:opacity-90" },
  accent:  { text: "text-accent", bg: "bg-accent/10",  border: "border-accent/30",  dot: "bg-accent", btn: "bg-accent text-accent-fg hover:opacity-90" },
  neutral: { text: "text-ink-3",  bg: "bg-surface-2",  border: "border-hairline",   dot: "bg-ink-4",  btn: "bg-surface-3 text-ink hover:bg-surface-2" },
};

export type AdvisorProfile = ClientProfileC & {
  _aum?: number | null;
  _issue?: Issue;
  _action?: ActionView;
  _health?: number | null;
};

export interface Issue { key: string; label: string; tone: Tone }
export interface ActionView { label: string; tone: Tone; Icon: LucideIcon }

// ── Formatters ──────────────────────────────────────────────────────────
export const fmtRs = (n?: number | null): string => {
  if (n == null) return "—";
  if (n >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
  if (n >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`;
  return `₹${Math.round(n).toLocaleString("en-IN")}`;
};

export const fmtRsCompact = (n?: number | null): string => {
  const v = Number(n) || 0;
  if (v >= 1e7) return `₹${(v / 1e7).toFixed(2)}Cr`;
  if (v >= 1e5) return `₹${(v / 1e5).toFixed(2)}L`;
  if (v >= 1000) return `₹${(v / 1000).toFixed(1)}k`;
  return `₹${Math.round(v).toLocaleString("en-IN")}`;
};

export const fmtPct = (n?: number | null, dp = 1): string =>
  n == null ? "—" : `${Number(n).toFixed(dp)}%`;

export const fmtDaysSince = (iso?: string | null): string | null => {
  if (!iso) return null;
  const d = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (d === 0) return "today";
  if (d === 1) return "yesterday";
  if (d < 30) return `${d}d ago`;
  if (d < 365) return `${Math.floor(d / 30)}mo ago`;
  return `${Math.floor(d / 365)}y ago`;
};

export const greetingFor = (name?: string | null): string => {
  const h = new Date().getHours();
  const greeting = h < 5 ? "Hello" : h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
  const first = (name || "").split(" ")[0];
  return first ? `${greeting}, ${first}` : greeting;
};

// ── Health (single north-star) ──────────────────────────────────────────
export const deriveHealth = (p: ClientProfileC): number | null => {
  const q = p.portfolio_score;
  const r = p.risk_score;
  if (q == null && r == null) return null;
  if (q == null) return Math.round(Math.max(0, 100 - (r as number)));
  if (r == null) return Math.round(q);
  return Math.round(0.6 * q + 0.4 * (100 - r));
};

export const healthTone = (v?: number | null): Tone => (v == null ? "neutral" : v >= 70 ? "pos" : v >= 50 ? "warm" : "neg");

// ── Top issue ─────────────────────────────────────────────────────────
export const deriveTopIssue = (p: ClientProfileC): Issue => {
  const f = p.priority?.factors || {};
  const unreviewed = !p.last_reviewed_at;
  if ((f.risk ?? 0) >= 0.6) {
    const r = p.risk_score != null ? ` (${Math.round(p.risk_score)}/100)` : "";
    return { key: "over-risk", label: `Over-risk${r}`, tone: "neg" };
  }
  if ((f.portfolio_weakness ?? 0) >= 0.4) {
    const q = p.portfolio_score != null ? ` (${Math.round(p.portfolio_score)}/100)` : "";
    return { key: "underperforming", label: `Underperforming${q}`, tone: "neg" };
  }
  if ((f.recommendation_severity ?? 0) >= 0.7) return { key: "exit-switch", label: "Exit/Switch due", tone: "neg" };
  if ((f.recommendation_severity ?? 0) >= 0.4) return { key: "rebalance", label: "Rebalance pending", tone: "warm" };
  if (unreviewed) return { key: "unreviewed", label: "Not reviewed yet", tone: "warm" };
  if ((f.recency ?? 0) >= 1.0) return { key: "stale", label: "Review stale", tone: "warm" };
  if ((p.recommendation_count || 0) > 0) return { key: "review", label: "Review suggested", tone: "neutral" };
  return { key: "healthy", label: "Healthy", tone: "pos" };
};

// ── Dominant action ─────────────────────────────────────────────────────
const VERB_VIEW: Record<string, ActionView> = {
  exit:         { label: "Exit",         tone: "neg",    Icon: RefreshCw },
  switch:       { label: "Switch",       tone: "neg",    Icon: RefreshCw },
  reduce:       { label: "Reduce",       tone: "neg",    Icon: RefreshCw },
  rebalance:    { label: "Rebalance",    tone: "warm",   Icon: Scale },
  increase_sip: { label: "Increase SIP", tone: "accent", Icon: TrendingUp },
  add_more:     { label: "Add more",     tone: "accent", Icon: Plus },
  add:          { label: "Add more",     tone: "accent", Icon: Plus },
};

export const deriveAction = (p: ClientProfileC): ActionView => {
  const v = p.priority?.dominant_action;
  if (v && VERB_VIEW[v]) return VERB_VIEW[v];

  const f = p.priority?.factors || {};
  const unreviewed = !p.last_reviewed_at;
  if ((f.recommendation_severity ?? 0) >= 0.7) return { label: "Switch", tone: "neg", Icon: RefreshCw };
  if ((f.recommendation_severity ?? 0) >= 0.4) return { label: "Rebalance", tone: "warm", Icon: Scale };
  if ((f.portfolio_weakness ?? 0) >= 0.4) return { label: "Rebalance", tone: "warm", Icon: Scale };
  if ((f.risk ?? 0) >= 0.6) return { label: "Rebalance", tone: "neg", Icon: Scale };
  if (unreviewed) return { label: "First review", tone: "accent", Icon: ClipboardCheck };
  if ((f.recency ?? 0) >= 1.0) return { label: "Review", tone: "warm", Icon: Eye };
  if ((p.recommendation_count || 0) > 0) return { label: "Review", tone: "neutral", Icon: Eye };
  return { label: "All good", tone: "pos", Icon: CheckCircle2 };
};

/** Decorate a raw profile with the derived signals the UI reads. */
export const decorateProfile = (p: ClientProfileC): AdvisorProfile => ({
  ...p,
  _aum: (p.portfolio_value_rs && p.portfolio_value_rs > 0) ? p.portfolio_value_rs : p.aum_rs,
  _issue: deriveTopIssue(p),
  _action: deriveAction(p),
  _health: deriveHealth(p),
});

/** Route an action verb to the right screen tab (mirrors V2 openAction). */
export const actionToRoute = (label: string): string => {
  if (["Exit", "Switch", "Reduce", "Rebalance"].includes(label)) return "/plan";
  if (["Increase SIP", "Add more"].includes(label)) return "/goals";
  return "/dashboard";
};
