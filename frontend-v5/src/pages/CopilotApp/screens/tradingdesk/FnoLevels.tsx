/**
 * Smart trading desk — Options & futures lab · the levels card: an estimated entry, planned stop-loss, risk boundary and two targets for the structure on screen, the underlying's levels, the
 * Greek-based review rule, theta and vega, and a four-scenario table. RULE-BASED and HYPOTHETICAL: fixed research settings worked out by the backend (POST /api/desk/strategy/levels,
 * services/strategy_levels) from the payoff engine's own numbers. Not predictions, no accuracy or hit rate is claimed, and a stop is a theoretical level, not an executable price.
 * The browser computes nothing here; it shows what the route returned. A missing figure is a dash.
 */
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { Pill } from "../../components/ui";
import type { PayoffRequest } from "./strategy/strategy-contract";
import { num } from "./desk-data";

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);

export interface Levels {
  valid: boolean;
  problems: string[];
  kind: "debit" | "credit" | null;
  entry: number | null; plannedStop: number | null; plannedStopLoss: number | null; boundary: number | null; boundaryText: string | null; t1: number | null; t2: number | null;
  maxProfit: number | null; maxLoss: number | null; riskReward: number | null;
  underlying: { view: string | null; entry: number | null; stop: number | null; target: number | null; low: number | null; high: number | null; valueAtStop: number | null; valueAtTarget: number | null };
  greeks: { delta: number | null; theta: number | null; vega: number | null; gamma: number | null; review: string | null };
  scenarios: Array<{ name: string; move: number | null; price: number | null; iv: number | null; date: string | null; pnl: number | null }>;
  flags: string[]; caveats: string[]; ivNote: string | null; daysToExpiry: number | null;
}

export function parseLevels(body: unknown): Levels {
  const b = rec(body);
  if (typeof b.valid !== "boolean") throw ApiError.contractDrift("strategy.levels: no `valid`");
  const p = rec(b.premium), u = rec(b.underlying), g = rec(b.greeks);
  const kind = p.kind === "debit" || p.kind === "credit" ? p.kind : null;
  return {
    valid: b.valid, problems: (Array.isArray(b.problems) ? b.problems : []).map((x) => str(rec(x).message) ?? "").filter(Boolean), kind,
    entry: num(p.entry), plannedStop: num(p.planned_stop), plannedStopLoss: num(p.planned_stop_loss_per_unit), boundary: num(rec(p.risk_boundary).value), boundaryText: str(rec(p.risk_boundary).meaning), t1: num(p.target_1), t2: num(p.target_2),
    maxProfit: num(b.max_profit_per_unit), maxLoss: num(b.max_loss_per_unit), riskReward: num(b.risk_reward),
    underlying: { view: str(u.view), entry: num(u.entry), stop: num(u.stop), target: num(u.target), low: num(u.range_low), high: num(u.range_high), valueAtStop: num(u.value_at_stop), valueAtTarget: num(u.value_at_target) },
    greeks: { delta: num(g.net_delta_per_share), theta: num(g.theta_per_day_per_share), vega: num(g.vega_per_point_per_share), gamma: num(g.gamma), review: str(g.review_when) },
    scenarios: (Array.isArray(b.scenarios) ? b.scenarios : []).map((s) => { const r = rec(s); return { name: str(r.name) ?? "", move: num(r.underlying_move_pct), price: num(r.underlying), iv: num(r.iv_change_points), date: str(r.date), pnl: num(r.pnl_per_unit) }; }),
    flags: (Array.isArray(b.flags) ? b.flags : []).map((f) => str(rec(f).message) ?? "").filter(Boolean),
    caveats: (Array.isArray(b.caveats) ? b.caveats : []).map((c) => str(c) ?? "").filter(Boolean), ivNote: str(b.iv_note), daysToExpiry: num(b.days_to_expiry),
  };
}

export function useLevels(base: PayoffRequest | null, refs: { put_wall: number | null; call_wall: number | null; expected_move: number | null }) {
  const key = base ? JSON.stringify([base, refs]) : null;
  return useQuery<Levels>({
    queryKey: ["copilot", "desk", "strategy-levels", key],
    enabled: !!base,
    staleTime: 60_000,
    retry: false,
    queryFn: async ({ signal }) => parseLevels((await http({ method: "POST", path: "/api/desk/strategy/levels", body: { payoff: base, refs }, noRetry: true, timeoutMs: 30_000, signal })).data),
  });
}

const dash = "—";
const f2 = (n: number | null) => (n == null ? dash : new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n));
const sg = (n: number | null) => (n == null ? dash : `${n > 0 ? "+" : n < 0 ? "−" : ""}${f2(Math.abs(n))}`);
const quiet = { fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" } as const;

function Fig({ k, v, sub, testId }: { k: string; v: string; sub?: string; testId: string }) {
  return (
    <div className="flex flex-col" style={{ gap: 2, minWidth: 0 }}>
      <span style={{ fontSize: 11, color: "var(--cp-ink-3)" }}>{k}</span>
      <span data-testid={testId} style={{ fontFamily: "var(--mono)", fontSize: 15 }}>{v}</span>
      {sub && <span style={{ fontSize: 11, color: "var(--cp-ink-3)" }}>{sub}</span>}
    </div>
  );
}

export function LevelsCard({ q }: { q: ReturnType<typeof useLevels> }) {
  const d = q.data;
  return (
    <section data-testid="desk-levels" className="cp-card flex flex-col" style={{ gap: 12, padding: 16, minWidth: 0 }}>
      <div className="flex flex-wrap items-center justify-between" style={{ gap: 6 }}>
        <span style={{ fontSize: 15, fontWeight: 600 }}>Estimated entry, stop-loss and targets</span>
        <Pill tone="amber">Rule-based · hypothetical</Pill>
      </div>
      {q.isPending && q.fetchStatus !== "idle" && <span style={quiet}>Working out the levels…</span>}
      {q.isError && <span data-testid="desk-levels-error" style={quiet}>The levels did not load just now; the payoff and margin above are unaffected.</span>}
      {d && !d.valid && <span data-testid="desk-levels-invalid" style={quiet}>No levels for this structure: {d.problems[0] ?? "it was not accepted by the calculation"}</span>}
      {d && d.valid && (
        <>
          <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(130px,1fr))", gap: 12 }}>
            <Fig testId="desk-levels-entry" k={d.kind === "credit" ? "Estimated entry · net credit" : "Estimated entry · net debit"} v={f2(d.entry)} sub="per share, end-of-day closes" />
            <Fig testId="desk-levels-stop" k="Planned stop-loss" v={f2(d.plannedStop)} sub={`${d.kind === "credit" ? "buyback cost" : "structure value"} · loss ${f2(d.plannedStopLoss)} per share`} />
            <Fig testId="desk-levels-boundary" k="Risk boundary" v={d.boundary == null ? "No maximum" : f2(d.boundary)} sub={d.boundaryText ?? undefined} />
            <Fig testId="desk-levels-t1" k="Target 1" v={f2(d.t1)} sub={d.kind === "credit" ? "buyback cost" : "structure value"} />
            <Fig testId="desk-levels-t2" k="Target 2" v={f2(d.t2)} sub={d.kind === "credit" ? "buyback cost" : "structure value"} />
            <Fig testId="desk-levels-rr" k="Max profit / max loss" v={`${f2(d.maxProfit)} / ${f2(d.maxLoss)}`} sub={`reward : risk ${d.riskReward == null ? dash : f2(d.riskReward)}`} />
          </div>
          <div data-testid="desk-levels-underlying" className="flex flex-col" style={{ gap: 4, paddingTop: 10, borderTop: "1px solid var(--line-2)" }}>
            <span style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>
              Underlying ({d.underlying.view ?? "—"}): entry {f2(d.underlying.entry)}
              {d.underlying.view === "neutral"
                ? ` · stays between ${f2(d.underlying.low)} and ${f2(d.underlying.high)} (a close outside it invalidates the view)`
                : ` · stop ${f2(d.underlying.stop)} · target ${f2(d.underlying.target)}`}
            </span>
            {d.underlying.view !== "neutral" && <span style={quiet}>Model estimate of the structure’s value on the data date: {f2(d.underlying.valueAtStop)} at the stop price, {f2(d.underlying.valueAtTarget)} at the target price. Not quotes.</span>}
          </div>
          <div data-testid="desk-levels-greeks" className="flex flex-col" style={{ gap: 4, paddingTop: 10, borderTop: "1px solid var(--line-2)" }}>
            <span style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>
              Per share: net delta {sg(d.greeks.delta)} · theta {sg(d.greeks.theta)} a day · vega {sg(d.greeks.vega)} per IV point · gamma {sg(d.greeks.gamma)}
            </span>
            {d.greeks.review && <span style={quiet}>Review the trade when {d.greeks.review}.</span>}
            {d.flags.map((f) => <span key={f} data-testid="desk-levels-flag" style={{ ...quiet, color: "var(--amber)" }}>{f}</span>)}
          </div>
          {d.scenarios.length > 0 && (
            <div data-testid="desk-levels-scenarios" className="flex flex-col" style={{ gap: 6, paddingTop: 10, borderTop: "1px solid var(--line-2)" }}>
              <span style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>Scenarios: every leg repriced for the price move, the IV change and the time elapsed (per share, model estimate)</span>
              <div style={{ overflowX: "auto" }}>
                <table style={{ borderCollapse: "collapse", width: "100%", minWidth: 420 }}>
                  <thead><tr>{["Scenario", "Underlying", "IV change", "On", "P&L"].map((h) => <th key={h} style={{ textAlign: "left", fontSize: 11, fontWeight: 500, color: "var(--cp-ink-3)", padding: "4px 8px" }}>{h}</th>)}</tr></thead>
                  <tbody>
                    {d.scenarios.map((s) => (
                      <tr key={s.name} data-testid="desk-levels-scenario" style={{ borderTop: "1px solid var(--line-2)" }}>
                        <td style={{ padding: "6px 8px", fontSize: 12 }}>{s.name}</td>
                        <td style={{ padding: "6px 8px", fontFamily: "var(--mono)", fontSize: 12 }}>{f2(s.price)} ({s.move == null ? dash : `${s.move > 0 ? "+" : ""}${s.move}%`})</td>
                        <td style={{ padding: "6px 8px", fontFamily: "var(--mono)", fontSize: 12 }}>{s.iv == null ? dash : `${s.iv > 0 ? "+" : ""}${s.iv} pts`}</td>
                        <td style={{ padding: "6px 8px", fontFamily: "var(--mono)", fontSize: 12 }}>{s.date ?? dash}</td>
                        <td data-testid="desk-levels-scenario-pnl" style={{ padding: "6px 8px", fontFamily: "var(--mono)", fontSize: 12 }}>{sg(s.pnl)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <span style={quiet}>No probabilities are attached to the scenarios, so no expected P&amp;L is shown. {d.ivNote}</span>
            </div>
          )}
          <ul data-testid="desk-levels-caveats" style={{ margin: 0, paddingLeft: 18, ...quiet }}>{d.caveats.map((c) => <li key={c}>{c}</li>)}</ul>
        </>
      )}
    </section>
  );
}
