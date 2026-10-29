/**
 * Why a trade plan cannot be traded as it is, and what can be done about it, in plain words (owner, 29 Oct: "if the
 * trade plan is rejected because of risk and margin issues and guardrails please provide the details and way's to
 * override it").
 *
 * The reasons are the risk service's own (backend services/risk_gate/service.py checks: per_trade_risk, reward_risk,
 * governor, position, open_risk, exposure, sector, correlation, daily_loss, weekly_loss, drawdown, funding, controls,
 * defined_risk, fno_additional, levels, inputs, structure, mode) from the plan's account sizing and its last limits check,
 * and the plan rules' own reasons when the plan was turned down.
 *
 * "Override" means the allowed ways forward, never a way around the check:
 *   * what you can change yourself: a smaller size, a closer exit, another structure, closing or trimming other trades,
 *     waiting for a limit to reset or an event to pass;
 *   * a limit itself: you can TIGHTEN any limit yourself, but LOOSENING one needs an admin, with a reason (backend
 *     services/risk_profile.py set_limits: admin_required). The kill switch and a trading halt are admin-only too.
 * Every trade is still checked again when it is placed.
 */
import { Link } from "react-router-dom";
import { viewPath } from "../../../lib/views";
import type { PlanView, SizingReason } from "./plan-view";

export interface WayForward {
  key: string;
  /** What happened, in plain words. */
  why: string;
  /** The risk service's or the plan's own message, kept for the detail. */
  detail: string | null;
  /** What the user can do, most direct first. */
  options: string[];
  /** A limit only an admin can loosen (or a switch only an admin can clear). */
  admin: boolean;
  /** block: it cannot be traded as it is · reduce: it can, but only at a smaller size. */
  kind: "block" | "reduce";
}

export const RISK_CONTROLS_PATH = viewPath("trader/desk?tab=risk&view=controls");

const ASK_ADMIN = (limit: string) => `Ask an admin to loosen your ${limit} (Risk Desk › Controls & profile, with a reason). You can tighten limits yourself, but only an admin can loosen them.`;

function advice(check: string | null, code: string | null): Omit<WayForward, "key" | "detail" | "kind"> {
  const c = (check ?? "").toLowerCase();
  const k = (code ?? "").toLowerCase();
  if (k === "min_qty_exceeds_budget" || k === "min_lot_exceeds_budget") return {
    why: `Even the smallest size (one ${k === "min_lot_exceeds_budget" ? "lot" : "share"}) would risk more than your limit for one trade.`,
    options: ["Choose a cheaper stock or strike, or a spread, so that less money is at risk", "Use a closer exit price, so less is lost if it goes wrong", ASK_ADMIN("limit for one trade")], admin: true };
  if (c === "per_trade_risk") return {
    why: "The loss at the exit price would be more than your limit for one trade.",
    options: ["Trade the smaller size your limits allow", "Use a closer exit price, so less is lost if it goes wrong", ASK_ADMIN("limit for one trade")], admin: true };
  if (c === "reward_risk" || /reward/.test(k)) return {
    why: "The possible gain is too small for the risk taken.",
    options: ["Wait for a better (lower) entry price", "Choose another structure with a better payoff", ASK_ADMIN("minimum reward-to-risk")], admin: true };
  if (c === "position") return {
    why: "You already have as many open trades as your limits allow.",
    options: ["Close or finish another trade first", ASK_ADMIN("maximum number of open trades")], admin: true };
  if (c === "open_risk") return {
    why: "Too much of your capital is already at risk in open trades.",
    options: ["Close or reduce another open trade", "Trade a smaller size", ASK_ADMIN("open-risk limit")], admin: true };
  if (c === "exposure") return {
    why: "Too much money is already invested in open trades.",
    options: ["Close or reduce another open trade", "Trade a smaller size", ASK_ADMIN("exposure limit")], admin: true };
  if (c === "sector") return {
    why: "Too much of your money is already in this sector.",
    options: ["Choose a stock from another sector", "Trim a trade in this sector", ASK_ADMIN("sector limit")], admin: true };
  if (c === "correlation") return {
    why: "This trade would move together with trades you already hold.",
    options: ["Choose something less related to what you hold", "Trim a related trade"], admin: false };
  if (c === "daily_loss" || c === "weekly_loss") return {
    why: `You have reached your loss limit for ${c === "daily_loss" ? "today" : "this week"}, so new trades are paused.`,
    options: [c === "daily_loss" ? "Wait until the next trading day" : "Wait until next week", ASK_ADMIN(c === "daily_loss" ? "daily loss limit" : "weekly loss limit")], admin: true };
  if (c === "drawdown") return {
    why: "Your account has fallen by the most your limits allow, so new trades are paused.",
    options: ["An admin has to review the account and reset it (Risk Desk › Controls & profile)"], admin: true };
  if (c === "funding") return {
    why: "There is not enough free paper money for this trade.",
    options: ["Close a trade to free money", "Trade a smaller size"], admin: false };
  if (c === "controls") return {
    why: k === "trading_halted" ? "Trading is halted on your account." : "The kill switch is on: new paper trades are switched off.",
    options: ["Only an admin can switch trading back on (Risk Desk › Controls & profile)"], admin: true };
  if (c === "defined_risk") return {
    why: "This structure could lose more than the money put in.",
    options: ["Add a protective option to turn it into a spread", "Pick a limited-risk template in Strategy Lab"], admin: false };
  if (c === "fno_additional") return {
    why: "F&O limits: at most 4 legs and 10 lots per leg.",
    options: ["Use fewer legs or fewer lots"], admin: false };
  if (c === "governor") return {
    why: "Your limits cap the size of one position (by its value or by how easily it trades).",
    options: ["Trade the smaller size your limits allow", "Choose a stock that trades more easily"], admin: false };
  if (c === "levels" || c === "structure") return {
    why: "The plan's prices or legs do not line up (an entry, exit or target is missing or on the wrong side).",
    options: ["Rebuild the plan in Strategy Lab"], admin: false };
  if (c === "inputs") return {
    why: "Some data the check needs could not be read just now.",
    options: ["Try again in a few minutes"], admin: false };
  if (c === "mode") return { why: "Only paper trading is available.", options: [], admin: false };
  // The plan rules' own reasons (a plan turned down before any limits check).
  if (/liquid/.test(k)) return { why: "It does not trade easily enough.", options: ["Choose a stock or contract that trades more"], admin: false };
  if (/event|result|earning/.test(k)) return { why: "An event such as results is due soon.", options: ["Wait until after the event"], admin: false };
  if (/conflict/.test(k)) return { why: "The signals disagree with each other.", options: ["Wait for them to line up; check again after the next close"], admin: false };
  if (/stale|data/.test(k)) return { why: "The data is not fresh enough.", options: ["Check again after the next market close"], admin: false };
  return { why: "It does not meet the desk's rules today.", options: ["Check again after the next market close"], admin: false };
}

const BLOCKING = new Set(["block", "halt", "reject", "defer"]);

/**
 * Every reason this plan cannot be traded as it is, or only at a smaller size, with what can be done. Deduplicated,
 * blocks first. A size the limits already set (the account sizing's binding limit on a sized plan) is not one: the card
 * shows that size, and its "Money at risk" says which limit set it.
 */
export function waysForward(v: PlanView): WayForward[] {
  const raw: Array<{ check: string | null; code: string | null; message: string | null; kind: WayForward["kind"] }> = [];
  // all: every reason counts, as `kind` · otherwise only the blocking ones (as `kind`) and the size cuts (as reduce).
  const take = (rs: SizingReason[] | undefined, kind: WayForward["kind"], all = false) => (rs ?? []).forEach((r) => {
    const blocking = r.severity == null || BLOCKING.has(r.severity);
    if (all || blocking) raw.push({ ...r, kind });
    else if (r.severity === "reduce") raw.push({ ...r, kind: "reduce" });
  });
  const a = v.accountSize;
  if (a?.status === "not_sizable") take(a.blocking, "block", true);
  // not_confirmed: the limits would cut the size again, and the card's action stays off until that is fixed.
  if (a?.status === "not_confirmed") { take(a.confirmReasons, "block", true); take(a.binding, "block", true); }
  if (a?.portfolio?.reasons.length) take(a.portfolio.reasons, "reduce", true);
  const d = v.risk.decision;
  if (d && (d.outcome === "block" || d.outcome === "reduce") && !v.risk.staleWhy) {
    take(d.reasons.map((r) => ({ code: r.code, check: r.check, severity: r.severity, message: r.message })), d.outcome === "block" ? "block" : "reduce");
  }
  if (v.status === "rejected") v.plan.eligibility.reasons.forEach((r) => raw.push({ check: "plan", code: r.code ?? null, message: r.message ?? null, kind: "block" }));
  const seen = new Map<string, WayForward>();
  for (const r of raw) {
    const key = `${r.check ?? ""}:${r.code ?? ""}`;
    const had = seen.get(key);
    if (had) { if (r.kind === "block") had.kind = "block"; continue; }
    seen.set(key, { key, detail: r.message, kind: r.kind, ...advice(r.check === "plan" ? null : r.check, r.code) });
  }
  const all = [...seen.values()];
  return [...all.filter((w) => w.kind === "block"), ...all.filter((w) => w.kind === "reduce")];
}

const quiet = { fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" } as const;

/** One line on a compact card: the first reason and the first thing to do. */
export function WaysForwardLine({ ways }: { ways: WayForward[] }) {
  const w = ways[0];
  if (!w) return null;
  return (
    <span data-testid="dc-ways-line" data-kind={w.kind} style={{ fontSize: 12, lineHeight: 1.5, color: "var(--amber)" }}>
      {w.kind === "block" ? "Why not" : "Why a smaller size"}: {w.why}{w.options[0] ? ` · What you can do: ${w.options[0]}` : ""}{ways.length > 1 || w.options.length > 1 ? " · more in Plan details" : ""}
    </span>
  );
}

/** The full card's section: every reason, its detail, and the ways forward. */
export function WaysForwardSection({ ways }: { ways: WayForward[] }) {
  if (!ways.length) return null;
  const admin = ways.some((w) => w.admin);
  const blocked = ways.some((w) => w.kind === "block");
  return (
    <section data-testid="dc-sec-ways" data-kind={blocked ? "block" : "reduce"} className="flex min-w-0 flex-col" style={{ gap: 6, paddingTop: 8, borderTop: "1px solid var(--cp-line)" }}>
      <h5 className="cp-eyebrow m-0" style={{ fontWeight: 400, fontSize: 9.5, color: "var(--amber)" }}>
        {blocked ? <>Why it can&rsquo;t be traded as it is, and what you can do</> : "Why the size is smaller, and what you can do"}
      </h5>
      {ways.map((w) => (
        <div key={w.key} data-testid="dc-way" data-key={w.key} data-kind={w.kind} className="flex min-w-0 flex-col" style={{ gap: 2, fontSize: 12.5, lineHeight: 1.5 }}>
          <span style={{ color: "var(--cp-ink)" }}>{w.why}</span>
          {w.detail && <span style={quiet}>{w.detail}</span>}
          {w.options.length > 0 && (
            <ul className="m-0" style={{ paddingLeft: 16, color: "var(--cp-ink-2)" }}>
              {w.options.map((o, i) => <li key={i} data-testid="dc-way-option">{o}</li>)}
            </ul>
          )}
        </div>
      ))}
      {admin && (
        <span style={quiet}>
          Limits protect your capital: every trade is checked again when it is placed, and nothing here skips that check.{" "}
          <Link data-testid="dc-way-controls" to={RISK_CONTROLS_PATH} style={{ color: "var(--mint)", fontWeight: 600, textDecoration: "none" }}>Open Risk Desk › Controls &amp; profile ›</Link>
        </span>
      )}
    </section>
  );
}
