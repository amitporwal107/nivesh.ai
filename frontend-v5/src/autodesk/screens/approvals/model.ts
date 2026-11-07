/**
 * Approval queue — shapes the screen reads beyond ../../types and pure helpers that turn API rows into what the design
 * shows. Every value comes from an API field; derived figures (lots, notional) use the same arithmetic as the backend's
 * approval scope (backend/autodesk/agents/middle_office.build_scope). Text written by the agents is passed through.
 */
import { DASH, dateShort, fmtNum, humanize, num, rs, timeIST } from "../../format";
import type { Account, ApprovalRow, PlanLeg, RiskAssessmentRow, RiskCheck, TradePlanDetail } from "../../types";

// ── API shapes used only here ───────────────────────────────────────────────────────────────────────────────────────

/** GET /trade-plans/{id}/versions — rows of autodesk.trade_plan_versions. */
export interface PlanVersionRow {
  trade_id: string;
  version: number;
  body: PlanBody;
  body_sha256: string;
  strategy_type: string;
  max_loss_rs: string;
  max_profit_rs: string | null;
  capital_required_rs: string;
  created_by: string;
  change_reason: string | null;
  supersedes_version: number | null;
  created_at: string;
}

/** GET /risk/portfolio/{account_id} → {account, book, note}. The book = approved plans without an intent, active reservations and open positions (paper only). */
export interface PortfolioResponse {
  account: Account;
  book: {
    account_id: string;
    equity_rs: string;
    starting_capital_rs: string;
    pending: { trade_id: string; plan_version: number; instrument: string; sector: string; strategy_type: string; max_loss_rs: string; capital_rs: string; fno: boolean }[];
    basis?: string;
  };
  note?: string;
}

/** GET /signals/{id} — the fields the audit history shows. */
export interface SignalLite {
  signal_id: string;
  instrument: string;
  direction: string;
  category: string;
  signal_score: string;
  created_at: string;
}

/** TradePlanBody (backend/autodesk/contracts.py) as the API serialises it. */
export interface PlanBody {
  thesis?: string;
  rationale?: string[];
  signal_id?: string | null;
  market_context?: Record<string, unknown>;
  account_id?: string;
  instrument?: string;
  segment?: string;
  strategy_type?: string;
  legs?: PlanLeg[];
  entry?: { order_type?: string; reference_price?: string | null; zone_low?: string | null; zone_high?: string | null; valid_until?: string; max_slippage_pct?: string };
  invalidation?: { underlying_level?: string | null; rule?: string; max_loss_rs?: string };
  targets?: { level: string; basis?: string; exit_fraction?: string }[];
  max_loss_rs?: string;
  max_profit_rs?: string | null;
  loss_defined?: boolean;
  breakevens?: string[];
  expected_payoff?: { reward_risk?: string | null; reward_rs?: string | null; assumptions?: string[] };
  capital_required_rs?: string;
  margin_estimate?: { amount_rs?: string; method?: string; source?: string; fno?: boolean; [k: string]: unknown };
  holding?: { timeframe?: string; max_holding_days?: number; expiry?: string | null; close_days_before_expiry?: number };
  exit_rules?: Record<string, unknown>;
  risk_warnings?: string[];
  plan_expires_at?: string;
  [k: string]: unknown;
}

export const bodyOf = (p: TradePlanDetail | undefined): PlanBody => (p?.body ?? {}) as PlanBody;

// ── names and labels ────────────────────────────────────────────────────────────────────────────────────────────────

export type ToneKey = "mint" | "amber" | "danger" | "indigo" | "ink";

/** [color, line, soft background] per tone, as the prototype's T table. */
export const TONES: Record<ToneKey, [string, string, string]> = {
  mint: ["var(--mint)", "var(--mint-line)", "var(--mint-soft)"],
  amber: ["var(--amber)", "var(--amber-line)", "var(--amber-soft)"],
  danger: ["var(--danger)", "var(--danger-line)", "var(--danger-soft)"],
  indigo: ["var(--indigo)", "var(--indigo-line)", "var(--indigo-soft)"],
  ink: ["var(--ink-2)", "var(--line-2)", "transparent"],
};

export function statusTone(status: string | null | undefined): ToneKey {
  if (status === "APPROVED" || status === "PASS") return "mint";
  if (status === "REJECTED" || status === "FAIL" || status === "SUSPENDED") return "danger";
  if (status === "NEEDS_HUMAN_APPROVAL" || status === "NEEDS_REVISION" || status === "REDUCE" || status === "WARN") return "amber";
  return "ink";
}

export const statusText = (s: string | null | undefined): string => (s ? s.replace(/_/g, " ") : DASH);

/** Mode pill of the account the request is for ("Auto paper", "Assisted paper", "Research", "Simulation"). */
export function modeOf(account: Account | undefined, a: Pick<ApprovalRow, "simulation_id">): { label: string; tone: ToneKey } {
  if (a.simulation_id || account?.kind === "SIMULATION") return { label: "Simulation", tone: "indigo" };
  if (!account) return { label: DASH, tone: "ink" };
  if (account.operating_mode === "AUTONOMOUS_PAPER") return { label: "Auto paper", tone: "mint" };
  if (account.operating_mode === "ASSISTED") return { label: "Assisted paper", tone: "indigo" };
  return { label: "Research", tone: "ink" };
}

export function accountLabel(account: Account | undefined, a: Pick<ApprovalRow, "account_id" | "simulation_id">): string {
  if (account) return `${account.kind === "SIMULATION" ? "Simulation" : "Paper"} · ${account.name}`;
  if (a.simulation_id) return `Simulation · ${a.simulation_id}`;
  return a.account_id ?? DASH;
}

/** "MIDDLE_OFFICE@autodesk-mo-v1" → "Middle Office"; "user:<you>" → "You"; "SYSTEM:session_close" → "Session close". */
export function deciderName(d: string | null | undefined, meId?: string | null): string {
  if (!d) return DASH;
  if (d.startsWith("MIDDLE_OFFICE")) return "Middle Office";
  if (d.startsWith("SYSTEM:session_close")) return "Session close";
  if (d.startsWith("user:")) return meId && d === `user:${meId}` ? "You" : d;
  const key = d.split("@")[0];
  return humanize(key);
}

export const AGENT_WHO: Record<string, string> = {
  AI_TRADER: "AI Trader",
  TRADING_ASSISTANT: "Trading Assistant",
  RISK_OPS: "Risk & Operations",
  MIDDLE_OFFICE: "Middle Office",
  TECH_SUPPORT: "Tech Support",
};

export function producerWho(p: string | null | undefined, meId?: string | null): string {
  if (!p) return DASH;
  const key = p.split("@")[0];
  if (AGENT_WHO[key]) return AGENT_WHO[key];
  return deciderName(p, meId);
}

// ── plan text ───────────────────────────────────────────────────────────────────────────────────────────────────────

const isOpt = (l: PlanLeg) => l.kind === "CE" || l.kind === "PE";

/** Strikes as the exchange writes them, no digit grouping: "2700", "317.5". */
export function strike(v: unknown): string {
  const n = num(v);
  if (n == null) return DASH;
  return Number.isInteger(n) ? String(n) : String(Math.round(n * 100) / 100);
}

export function maxLots(legs: PlanLeg[]): number | null {
  const l = legs.map((x) => (typeof x.lots === "number" ? x.lots : null)).filter((x): x is number => x != null);
  return l.length ? Math.max(...l) : null;
}

const plural = (n: number | null, one: string, many: string) => `${n ?? DASH} ${n === 1 ? one : many}`;

function optionPart(legs: PlanLeg[], sep: string): string {
  const opt = legs.filter(isOpt);
  if (!opt.length) return "";
  const kinds = Array.from(new Set(opt.map((l) => l.kind)));
  return `${opt.map((l) => strike(l.strike)).join(sep)} ${kinds.join("/")}`;
}

/** List line: "PETRONET 310/335 CE · Bull call spread · 4 lots". */
export function planShort(b: PlanBody, fallback: string): string {
  const legs = b.legs ?? [];
  if (!b.instrument || !legs.length) return fallback;
  const strat = humanize(b.strategy_type);
  if (legs.every((l) => l.kind === "EQ")) return `${b.instrument} · ${strat} · ${plural(legs[0].quantity, "share", "shares")}`;
  const opt = optionPart(legs, "/");
  return `${b.instrument}${opt ? ` ${opt}` : ""} · ${strat} · ${plural(maxLots(legs), "lot", "lots")}`;
}

/** Detail title: "PETRONET bull call spread · 310 / 335 CE · 24 Nov expiry". */
export function planTitle(b: PlanBody, fallback: string): string {
  const legs = b.legs ?? [];
  if (!b.instrument) return fallback;
  const strat = humanize(b.strategy_type).toLowerCase();
  if (legs.length && legs.every((l) => l.kind === "EQ")) return `${b.instrument} ${strat} · ${plural(legs[0].quantity, "share", "shares")}`;
  const opt = optionPart(legs, " / ");
  const exp = Array.from(new Set(legs.map((l) => l.expiry).filter(Boolean))) as string[];
  return [`${b.instrument} ${strat}`, opt || null, exp.length ? `${exp.map(dateShort).join(" / ")} expiry` : null].filter(Boolean).join(" · ");
}

function contractName(l: PlanLeg): string {
  if (l.tradingsymbol) return l.tradingsymbol;
  const parts = [l.underlying, l.expiry ? dateShort(l.expiry).toUpperCase() : null, l.strike != null ? strike(l.strike) : null, l.kind === "FUT" ? "FUT" : l.kind];
  return parts.filter(Boolean).join(" ");
}

export interface Row { k: string; v: string; n?: string }

/** Proposed trade rows: one per leg, then net / valid / exit / targets / hold from the plan body. */
export function tradeRows(b: PlanBody): Row[] {
  const rows: Row[] = [];
  for (const l of b.legs ?? []) {
    const ref = `REF ${fmtNum(l.ref_price)}${l.ref_price_source ? ` · ${l.ref_price_source}` : ""}`;
    if (l.kind === "EQ") rows.push({ k: humanize(l.side), v: `${plural(l.quantity, "share", "shares")} · ${l.underlying} · NSE cash`, n: ref });
    else rows.push({ k: humanize(l.side), v: `${plural(l.lots ?? null, "lot", "lots")} · ${l.lot_size ?? DASH} · ${contractName(l)}`, n: ref });
  }
  const m = b.margin_estimate ?? {};
  rows.push({
    k: "Net",
    v: `Capital ${rs(b.capital_required_rs, { decimals: 2 })} · max loss ${rs(b.max_loss_rs, { decimals: 2 })}${b.loss_defined === false ? " (not bounded by the structure)" : ""}`,
    n: [m.method, b.entry?.order_type, b.entry?.max_slippage_pct ? `max slippage ${b.entry.max_slippage_pct}%` : null].filter(Boolean).join(" · ").toUpperCase(),
  });
  if (b.entry?.valid_until) {
    const zone = b.entry.zone_low && b.entry.zone_high ? `ZONE ${fmtNum(b.entry.zone_low)}–${fmtNum(b.entry.zone_high)}` : b.entry.reference_price ? `REF ${fmtNum(b.entry.reference_price)}` : "";
    rows.push({ k: "Valid", v: `Until ${timeIST(b.entry.valid_until, { seconds: false })} IST · ${dateShort(b.entry.valid_until)}`, n: zone });
  }
  if (b.invalidation && (b.invalidation.rule || b.invalidation.underlying_level)) {
    rows.push({ k: "Exit", v: b.invalidation.rule ?? DASH, n: b.invalidation.underlying_level ? `INVALIDATION ${fmtNum(b.invalidation.underlying_level)}` : "" });
  }
  if (b.targets?.length) {
    rows.push({
      k: "Targets",
      v: b.targets.map((t) => `${fmtNum(t.level)}${t.exit_fraction && num(t.exit_fraction) !== 1 ? ` (${Math.round((num(t.exit_fraction) ?? 0) * 100)}%)` : ""}`).join(" · "),
      n: Array.from(new Set(b.targets.map((t) => t.basis ?? "UNDERLYING"))).join(" · "),
    });
  }
  if (b.holding?.timeframe) {
    rows.push({
      k: "Hold",
      v: `${humanize(b.holding.timeframe)}${b.holding.max_holding_days != null ? ` · at most ${b.holding.max_holding_days} sessions` : ""}`,
      n: b.holding.close_days_before_expiry != null ? `CLOSE ${b.holding.close_days_before_expiry} SESSIONS BEFORE EXPIRY` : "",
    });
  }
  return rows;
}

/** Σ ref_price × quantity over the legs — the scope's max_notional_rs. */
export function notional(b: PlanBody): number | null {
  const legs = b.legs ?? [];
  if (!legs.length) return null;
  let t = 0;
  for (const l of legs) {
    const p = num(l.ref_price);
    if (p == null || typeof l.quantity !== "number") return null;
    t += p * l.quantity;
  }
  return Math.round(t * 100) / 100;
}

// ── risk report ─────────────────────────────────────────────────────────────────────────────────────────────────────

export const checksOf = (r: RiskAssessmentRow | null | undefined): RiskCheck[] => (r?.body?.checks ?? []) as RiskCheck[];

export function checkByName(r: RiskAssessmentRow | null | undefined): Record<string, RiskCheck> {
  return Object.fromEntries(checksOf(r).map((c) => [c.name, c]));
}

export function checkCounts(checks: RiskCheck[]) {
  const n = (o: string) => checks.filter((c) => c.outcome === o).length;
  return { pass: n("PASS"), warn: n("WARN"), fail: n("FAIL"), skipped: n("SKIPPED") };
}

export function checkSummary(checks: RiskCheck[]): string {
  const c = checkCounts(checks);
  return `${c.pass} PASS · ${c.warn} WARNING${c.warn === 1 ? "" : "S"} · ${c.fail} FAIL · ${c.skipped} SKIPPED`;
}

export const GLYPH: Record<string, [string, string]> = {
  PASS: ["✓", "var(--mint)"],
  WARN: ["!", "var(--amber)"],
  FAIL: ["×", "var(--danger)"],
  SKIPPED: ["–", "var(--ink-3)"],
};

export interface ImpactRow { k: string; b: number | null; a: number | null; l: number | null; note?: string }

/** Portfolio impact from the assessment itself: before = its inputs snapshot, after / limit = the check's value / limit. */
export function impactRows(r: RiskAssessmentRow | null | undefined, acctName: string): ImpactRow[] {
  if (!r) return [];
  const c = checkByName(r);
  const snap = (r.body?.inputs_snapshot ?? {}) as Record<string, unknown>;
  const sizing = (r.body?.sizing ?? {}) as Record<string, unknown>;
  const v = (x: RiskCheck | undefined, f: "value" | "limit") => (x && x.outcome !== "SKIPPED" ? num(x[f]) : null);
  const rows: ImpactRow[] = [];
  if (c.open_risk) rows.push({ k: `Open risk (${acctName})`, b: num(snap.pending_risk_rs), a: v(c.open_risk, "value"), l: v(c.open_risk, "limit") });
  if (c.margin_utilization) {
    rows.push({ k: "F&O capital", b: c.margin_utilization.outcome === "SKIPPED" ? null : num(snap.pending_fno_capital_rs), a: v(c.margin_utilization, "value"), l: v(c.margin_utilization, "limit"), note: c.margin_utilization.outcome === "SKIPPED" ? (c.margin_utilization.detail ?? undefined) : undefined });
  }
  if (c.sector) {
    const after = v(c.sector, "value");
    const cap = num(sizing.capital_rs);
    rows.push({ k: `Sector · ${typeof snap.sector === "string" ? snap.sector : DASH}`, b: after != null && cap != null ? Math.round((after - cap) * 100) / 100 : null, a: after, l: v(c.sector, "limit") });
  }
  if (c.position) rows.push({ k: "Capital in this plan", b: null, a: v(c.position, "value"), l: v(c.position, "limit") });
  return rows;
}

export function equityOf(r: RiskAssessmentRow | null | undefined, account: Account | undefined): number | null {
  const snap = (r?.body?.inputs_snapshot ?? {}) as Record<string, unknown>;
  return num(snap.equity_rs) ?? num(account?.starting_capital_rs);
}

// ── time ────────────────────────────────────────────────────────────────────────────────────────────────────────────

const z = (n: number) => String(n).padStart(2, "0");

/** Countdown text as the prototype: "3h 47m" above an hour, "mm:ss" below; amber in the last 15 minutes. */
export function countdown(expiresAt: string | null | undefined, now: number): { t: string; c: string; expired: boolean } {
  if (!expiresAt) return { t: DASH, c: "var(--ink-3)", expired: false };
  const left = Math.floor((new Date(expiresAt).getTime() - now) / 1000);
  if (!Number.isFinite(left)) return { t: DASH, c: "var(--ink-3)", expired: false };
  if (left <= 0) return { t: "EXPIRED", c: "var(--danger)", expired: true };
  const mm = Math.floor(left / 60);
  const ss = left % 60;
  return { t: mm >= 60 ? `${Math.floor(mm / 60)}h ${z(mm % 60)}m` : `${z(mm)}:${z(ss)}`, c: left < 900 ? "var(--amber)" : "var(--ink-2)", expired: false };
}

export const NUMBER_WORDS = ["", "One decision", "Two decisions", "Three decisions", "Four decisions", "Five decisions", "Six decisions", "Seven decisions", "Eight decisions", "Nine decisions", "Ten decisions"];

export function byExpiry(a: ApprovalRow, b: ApprovalRow): number {
  const x = a.expires_at ? new Date(a.expires_at).getTime() : Infinity;
  const y = b.expires_at ? new Date(b.expires_at).getTime() : Infinity;
  return x - y || a.created_at.localeCompare(b.created_at);
}
