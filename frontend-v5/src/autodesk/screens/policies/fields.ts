/**
 * The policy body (backend/autodesk/contracts.py PolicyBody) as the Policies screen shows and edits it.
 * "Stricter" follows backend/autodesk/control/policy.py: UPPER_LIMITS (lower = stricter), LOWER_LIMITS (higher =
 * stricter), lists (fewer = stricter). Decimal fields arrive and are sent as strings; integer fields as numbers.
 */
import { humanize, num, rsShort } from "../../format";

export type FieldKind = "pct" | "num" | "int" | "rs" | "ratio" | "fraction" | "bool" | "list";

export interface FieldDef {
  key: string;
  label: string;
  kind: FieldKind;
  /** lower = a lower value is stricter; higher = a higher value is stricter */
  stricter?: "lower" | "higher";
  editable: boolean;
}

export const FIELDS: FieldDef[] = [
  { key: "per_trade_risk_pct", label: "Max risk per trade", kind: "pct", stricter: "lower", editable: true },
  { key: "open_risk_pct", label: "Max aggregate open risk", kind: "pct", stricter: "lower", editable: true },
  { key: "daily_loss_pct", label: "Max daily loss", kind: "pct", stricter: "lower", editable: true },
  { key: "weekly_loss_pct", label: "Max weekly loss", kind: "pct", stricter: "lower", editable: true },
  { key: "max_drawdown_pct", label: "Max drawdown", kind: "pct", stricter: "lower", editable: true },
  { key: "position_pct", label: "Max allocation per instrument", kind: "pct", stricter: "lower", editable: true },
  { key: "sector_pct", label: "Max sector exposure", kind: "pct", stricter: "lower", editable: true },
  { key: "max_margin_utilization_pct", label: "Max margin utilization", kind: "pct", stricter: "lower", editable: true },
  { key: "futures_margin_pct", label: "Futures margin estimate", kind: "pct", stricter: "higher", editable: true },
  { key: "min_reward_risk", label: "Min reward : risk", kind: "ratio", stricter: "higher", editable: true },
  { key: "credit_min_width_fraction", label: "Min credit, share of spread width", kind: "fraction", stricter: "higher", editable: true },
  { key: "min_signal_score", label: "Min signal score to propose", kind: "num", stricter: "higher", editable: true },
  { key: "max_proposals_per_session", label: "Max proposals per session", kind: "int", stricter: "lower", editable: true },
  { key: "min_days_to_expiry", label: "Min days to expiry", kind: "int", stricter: "higher", editable: true },
  { key: "max_legs", label: "Max legs per plan", kind: "int", stricter: "lower", editable: true },
  { key: "max_lots_per_leg", label: "Max lots per leg", kind: "int", stricter: "lower", editable: true },
  { key: "min_adv_rs", label: "Min average traded value", kind: "rs", stricter: "higher", editable: true },
  { key: "max_data_age_sessions", label: "Max data age (sessions)", kind: "int", stricter: "lower", editable: true },
  { key: "require_traded_legs", label: "Option legs must have traded", kind: "bool", editable: false },
  { key: "allowed_segments", label: "Allowed segments", kind: "list", editable: false },
  { key: "allowed_strategies", label: "Allowed strategies", kind: "list", editable: false },
];

/** Autonomy rules (PolicyBody.autonomy). The API merges top-level keys, so a change sends the whole object. */
export const AUTONOMY_FIELDS: FieldDef[] = [
  { key: "max_risk_pct", label: "Auto-approve up to, risk of equity", kind: "pct", stricter: "lower", editable: true },
  { key: "min_signal_score", label: "Auto-approve from signal score", kind: "num", stricter: "higher", editable: true },
];

export type PolicyBodyJson = Record<string, unknown> & {
  autonomy?: { auto_approve?: boolean; max_risk_pct?: string; min_signal_score?: string; strategies?: string[] };
};

/** "0.50" → "0.5"; numbers as typed by the API, without trailing zeros. */
export function plain(v: unknown): string {
  const n = num(v);
  return n == null ? "—" : String(n);
}

export function fmtField(kind: FieldKind, v: unknown): string {
  if (v === undefined || v === null) return "—";
  switch (kind) {
    case "pct": return num(v) == null ? "—" : `${plain(v)}%`;
    case "ratio": return num(v) == null ? "—" : `${plain(v)} : 1`;
    case "fraction": return num(v) == null ? "—" : `${plain(v)} × width`;
    case "rs": return rsShort(v);
    case "bool": return v === true ? "Yes" : v === false ? "No" : "—";
    case "list": return Array.isArray(v) ? (v.length ? v.map((x) => humanize(String(x))).join(", ") : "None") : "—";
    default: return plain(v);
  }
}

/** Human list of what changed between two policy bodies ("Max risk per trade 0.5% → 0.4%"). */
export function diffBodies(prev: PolicyBodyJson | undefined, next: PolicyBodyJson): string[] {
  if (!prev) return [];
  const out: string[] = [];
  const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b) || (num(a) != null && num(a) === num(b));
  for (const f of FIELDS) {
    const a = prev[f.key], b = next[f.key];
    if (same(a, b)) continue;
    if (f.kind === "list" && Array.isArray(a) && Array.isArray(b)) {
      const added = b.filter((x) => !a.includes(x)).map((x) => humanize(String(x)));
      const removed = a.filter((x) => !b.includes(x)).map((x) => humanize(String(x)));
      out.push(`${f.label}: ${[added.length ? `+ ${added.join(", ")}` : "", removed.length ? `− ${removed.join(", ")}` : ""].filter(Boolean).join("; ") || "reordered"}`);
    } else {
      out.push(`${f.label} ${fmtField(f.kind, a)} → ${fmtField(f.kind, b)}`);
    }
  }
  const pa = prev.autonomy ?? {}, na = next.autonomy ?? {};
  if (pa.auto_approve !== na.auto_approve) out.push(`Automatic approval ${pa.auto_approve ? "on" : "off"} → ${na.auto_approve ? "on" : "off"}`);
  for (const f of AUTONOMY_FIELDS) {
    const a = (pa as Record<string, unknown>)[f.key], b = (na as Record<string, unknown>)[f.key];
    if (!same(a, b)) out.push(`${f.label} ${fmtField(f.kind, a)} → ${fmtField(f.kind, b)}`);
  }
  if (JSON.stringify(pa.strategies ?? []) !== JSON.stringify(na.strategies ?? [])) out.push("Strategies approved automatically changed");
  return out;
}

/** Parse one edited value (ranges are the API's to judge). Decimal → string, integer → number. */
export function parseEdit(f: FieldDef, raw: string): { ok: true; value: string | number } | { ok: false; error: string } {
  const t = raw.trim();
  if (!t) return { ok: false, error: "required" };
  const n = Number(t);
  if (!Number.isFinite(n)) return { ok: false, error: "not a number" };
  if (f.kind === "int") {
    if (!Number.isInteger(n)) return { ok: false, error: "whole number" };
    return { ok: true, value: n };
  }
  return { ok: true, value: String(n) };
}
