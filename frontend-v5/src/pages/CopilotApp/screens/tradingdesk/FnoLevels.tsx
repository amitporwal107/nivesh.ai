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
  /** The engine's settings version (services/strategy_levels.VERSION), e.g. "strategy-levels-v2". */
  version: string | null;
  problems: string[];
  kind: "debit" | "credit" | null;
  entry: number | null; plannedStop: number | null; plannedStopLoss: number | null; boundary: number | null; boundaryText: string | null; t1: number | null; t2: number | null;
  maxProfit: number | null; maxLoss: number | null; riskReward: number | null;
  /** The structure's maximum loss for the position's lots, before costs (negative), or null when it has no limit. */
  maxLossTotal: number | null;
  underlying: { view: string | null; entry: number | null; stop: number | null; target: number | null; target2: number | null; low: number | null; high: number | null; valueAtStop: number | null; valueAtTarget: number | null;
    basis: string | null; wallStop: number | null; wallTarget: number | null; putWall: number | null; callWall: number | null };
  totals: { plannedStopLoss: number | null; target1Gain: number | null; target2Gain: number | null; shares: number | null };
  legs: Array<{ side: string; kind: string; strike: number | null; entry: number | null; delta: number | null; theta: number | null; vega: number | null }>;
  costs: { roundTrip: number | null; entry: number | null; exitAtExpiry: number | null; maxLossGross: number | null; capitalAtRisk: number | null; capitalBasis: string | null };
  greeks: { delta: number | null; theta: number | null; vega: number | null; gamma: number | null; review: string | null };
  scenarios: Array<{ name: string; move: number | null; price: number | null; iv: number | null; date: string | null; pnl: number | null }>;
  flags: string[]; caveats: string[]; ivNote: string | null; daysToExpiry: number | null;
}

export function parseLevels(body: unknown): Levels {
  const b = rec(body);
  if (typeof b.valid !== "boolean") throw ApiError.contractDrift("strategy.levels: no `valid`");
  const p = rec(b.premium), u = rec(b.underlying), g = rec(b.greeks), t = rec(b.totals), c = rec(b.costs), wr = rec(u.wall_reference);
  const kind = p.kind === "debit" || p.kind === "credit" ? p.kind : null;
  return {
    valid: b.valid, version: str(b.version), problems: (Array.isArray(b.problems) ? b.problems : []).map((x) => str(rec(x).message) ?? "").filter(Boolean), kind,
    entry: num(p.entry), plannedStop: num(p.planned_stop), plannedStopLoss: num(p.planned_stop_loss_per_unit), boundary: num(rec(p.risk_boundary).value), boundaryText: str(rec(p.risk_boundary).meaning), t1: num(p.target_1), t2: num(p.target_2),
    maxProfit: num(b.max_profit_per_unit), maxLoss: num(b.max_loss_per_unit), riskReward: num(b.risk_reward), maxLossTotal: num(b.max_loss_total),
    underlying: { view: str(u.view), entry: num(u.entry), stop: num(u.stop), target: num(u.target), target2: num(u.target_2), low: num(u.range_low), high: num(u.range_high), valueAtStop: num(u.value_at_stop), valueAtTarget: num(u.value_at_target),
      basis: str(u.basis), wallStop: num(u.wall_stop), wallTarget: num(u.wall_target), putWall: num(wr.put_wall), callWall: num(wr.call_wall) },
    totals: { plannedStopLoss: num(t.planned_stop_loss), target1Gain: num(t.target_1_gain), target2Gain: num(t.target_2_gain), shares: num(t.shares) },
    legs: (Array.isArray(b.legs) ? b.legs : []).map((l) => { const r = rec(l); return { side: str(r.side) ?? "", kind: str(r.option_type) ?? "", strike: num(r.strike), entry: num(r.entry_price), delta: num(r.delta), theta: num(r.theta), vega: num(r.vega) }; }),
    costs: { roundTrip: num(c.round_trip), entry: num(c.entry), exitAtExpiry: num(c.exit_at_expiry), maxLossGross: num(c.max_loss_gross_total), capitalAtRisk: num(c.capital_at_risk), capitalBasis: str(c.capital_at_risk_basis) },
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
const inr = (n: number | null) => (n == null ? dash : `₹${new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(n)}`);
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
  return <LevelsView d={q.data} pending={q.isPending && q.fetchStatus !== "idle"} failed={q.isError} />;
}

/** The card from levels already in hand: a query's answer, or levels stored with a day's list (the AI scanner watchlist).
 *  `inLab` false drops the one sentence that points at the lab's margin calculator, which an idea row does not have. */
export function LevelsView({ d, pending, failed, inLab = true }: { d?: Levels; pending?: boolean; failed?: boolean; inLab?: boolean }) {
  return (
    <section data-testid="desk-levels" className="cp-card flex flex-col" style={{ gap: 12, padding: 16, minWidth: 0 }}>
      <div className="flex flex-wrap items-center justify-between" style={{ gap: 6 }}>
        <span style={{ fontSize: 15, fontWeight: 600 }}>Estimated entry, stop-loss and targets</span>
        <Pill tone="amber">Rule-based · hypothetical</Pill>
      </div>
      {pending && <span style={quiet}>Working out the levels…</span>}
      {failed && <span data-testid="desk-levels-error" style={quiet}>The levels did not load just now; the payoff and margin above are unaffected.</span>}
      {d && !d.valid && <span data-testid="desk-levels-invalid" style={quiet}>No levels for this structure: {d.problems[0] ?? "it was not accepted by the calculation"}</span>}
      {d && d.valid && (
        <>
          <span data-testid="desk-levels-intro" style={quiet}>The strategy is the trade; the legs are its components. Levels A apply to the combined structure, not to either option on its own.</span>

          <div data-testid="desk-levels-a" className="flex flex-col" style={{ gap: 8 }}>
            <span style={{ fontSize: 13, fontWeight: 600 }}>A · Strategy levels (the combined {d.kind === "credit" ? "credit" : "debit"} structure)</span>
            <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(140px,1fr))", gap: 12 }}>
              <Fig testId="desk-levels-entry" k={d.kind === "credit" ? "Entry · net credit" : "Entry · net debit"} v={f2(d.entry)} sub="per share, end-of-day closes" />
              <Fig testId="desk-levels-stop" k="Stop-loss (structure value)" v={f2(d.plannedStop)} sub={`${d.kind === "credit" ? "buyback cost" : "closing value"} · loss ${f2(d.plannedStopLoss)} a share${d.totals.plannedStopLoss != null ? ` (${inr(d.totals.plannedStopLoss)} for ${d.totals.shares} shares)` : ""}`} />
              <Fig testId="desk-levels-t1" k="Target 1 (structure value)" v={f2(d.t1)} sub={d.totals.target1Gain != null ? `gain ${inr(d.totals.target1Gain)}` : undefined} />
              <Fig testId="desk-levels-t2" k="Target 2 (structure value)" v={f2(d.t2)} sub={d.totals.target2Gain != null ? `gain ${inr(d.totals.target2Gain)}` : undefined} />
              <Fig testId="desk-levels-rr" k="Max profit / max loss" v={`${f2(d.maxProfit)} / ${f2(d.maxLoss)}`} sub={`reward : risk ${d.riskReward == null ? dash : f2(d.riskReward)}`} />
              <Fig testId="desk-levels-boundary" k="Maximum-loss boundary" v={d.boundary == null ? "No maximum" : f2(d.boundary)} sub={d.kind === "credit" ? "buyback cost at the maximum loss" : "structure value if both legs expire worthless: the whole debit is lost. It is a boundary, not the stop-loss."} />
            </div>
          </div>

          <div data-testid="desk-levels-b" className="flex flex-col" style={{ gap: 4, paddingTop: 10, borderTop: "1px solid var(--line-2)" }}>
            <span style={{ fontSize: 13, fontWeight: 600 }}>B · Underlying thesis levels ({d.underlying.view ?? "—"})</span>
            {d.underlying.view === "neutral" ? (
              <span style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>Entry {f2(d.underlying.entry)} · the view holds while the underlying stays between {f2(d.underlying.low)} and {f2(d.underlying.high)}; a close outside it invalidates it.</span>
            ) : (
              <span data-testid="desk-levels-underlying" style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>
                Entry {f2(d.underlying.entry)} · thesis stop {f2(d.underlying.stop)} · target 1 {f2(d.underlying.target)} · target 2 {f2(d.underlying.target2)}
              </span>
            )}
            {d.underlying.basis && <span style={quiet}>Worked out as {d.underlying.basis} (model estimate for the data date), so the stop and targets here are the same ones as in A. They are not option premium levels.</span>}
            {d.underlying.view !== "neutral" && (d.underlying.wallStop != null || d.underlying.wallTarget != null) && (
              <span data-testid="desk-levels-walls" style={quiet}>Structural reference, not used above: put wall {f2(d.underlying.putWall)}, call wall {f2(d.underlying.callWall)} (the strikes with the most open interest on each side of the price).</span>
            )}
            <span style={quiet}>The trigger (a touch, a close or another rule) is not set: Nivesh does not monitor the underlying or place exits, so these are reference levels.</span>
          </div>

          <div data-testid="desk-levels-stops" style={{ overflowX: "auto", paddingTop: 10, borderTop: "1px solid var(--line-2)" }}>
            <table style={{ borderCollapse: "collapse", width: "100%", minWidth: 460 }}>
              <thead><tr>{["Stop", "Rule", "Purpose"].map((h) => <th key={h} style={{ textAlign: "left", fontSize: 11, fontWeight: 500, color: "var(--cp-ink-3)", padding: "4px 8px" }}>{h}</th>)}</tr></thead>
              <tbody>
                {[
                  ["Strategy stop", `combined ${d.kind === "credit" ? "buyback" : "closing"} value ${d.kind === "credit" ? "≥" : "≤"} ${f2(d.plannedStop)}`, "limits the loss on the whole position"],
                  ["Thesis stop", d.underlying.view === "neutral" ? `underlying outside ${f2(d.underlying.low)} – ${f2(d.underlying.high)}` : `underlying at ${f2(d.underlying.stop)}`, "the view is invalidated"],
                  ["Maximum-loss boundary", d.boundary == null ? "no maximum" : `structure value ${f2(d.boundary)}`, "the most this structure can lose"],
                  ["Emergency risk stop", "not built: no F&O risk engine yet", "margin, data, portfolio or execution risk"],
                ].map(([a, b, c]) => <tr key={a} style={{ borderTop: "1px solid var(--line-2)" }}><td style={{ padding: "6px 8px", fontSize: 12 }}>{a}</td><td style={{ padding: "6px 8px", fontSize: 12, fontFamily: "var(--mono)" }}>{b}</td><td style={{ padding: "6px 8px", fontSize: 12, color: "var(--cp-ink-3)" }}>{c}</td></tr>)}
              </tbody>
            </table>
          </div>

          <div data-testid="desk-levels-greeks" className="flex flex-col" style={{ gap: 4, paddingTop: 10, borderTop: "1px solid var(--line-2)" }}>
            <span style={{ fontSize: 13, fontWeight: 600 }}>Greeks of the combined position (per share)</span>
            <span style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>Net delta {sg(d.greeks.delta)} · theta {sg(d.greeks.theta)} a day · vega {sg(d.greeks.vega)} per IV point · gamma {sg(d.greeks.gamma)}</span>
            {d.greeks.review && <span style={quiet}>Review the trade when {d.greeks.review}.</span>}
            {d.flags.map((f) => <span key={f} data-testid="desk-levels-flag" style={{ ...quiet, color: "var(--amber)" }}>{f}</span>)}
          </div>

          {d.legs.length > 0 && (
            <div data-testid="desk-levels-c" className="flex flex-col" style={{ gap: 6, paddingTop: 10, borderTop: "1px solid var(--line-2)" }}>
              <span style={{ fontSize: 13, fontWeight: 600 }}>C · Legs (monitoring, not separate trades)</span>
              <div style={{ overflowX: "auto" }}>
                <table style={{ borderCollapse: "collapse", width: "100%", minWidth: 460 }}>
                  <thead><tr>{["Leg", "Position", "Entry", "Delta", "Theta", "Vega"].map((h) => <th key={h} style={{ textAlign: "left", fontSize: 11, fontWeight: 500, color: "var(--cp-ink-3)", padding: "4px 8px" }}>{h}</th>)}</tr></thead>
                  <tbody>
                    {d.legs.map((l, i) => (
                      <tr key={i} data-testid="desk-levels-leg" style={{ borderTop: "1px solid var(--line-2)" }}>
                        <td style={{ padding: "6px 8px", fontSize: 12, fontFamily: "var(--mono)" }}>{l.strike == null ? dash : f2(l.strike).replace(/\.00$/, "")} {l.kind === "call" ? "CE" : l.kind === "put" ? "PE" : ""}</td>
                        <td style={{ padding: "6px 8px", fontSize: 12 }}>{l.side === "buy" ? "Buy" : l.side === "sell" ? "Sell" : dash}</td>
                        <td style={{ padding: "6px 8px", fontSize: 12, fontFamily: "var(--mono)" }}>{f2(l.entry)}</td>
                        <td style={{ padding: "6px 8px", fontSize: 12, fontFamily: "var(--mono)" }}>{sg(l.delta)}</td>
                        <td style={{ padding: "6px 8px", fontSize: 12, fontFamily: "var(--mono)" }}>{sg(l.theta)}</td>
                        <td style={{ padding: "6px 8px", fontSize: 12, fontFamily: "var(--mono)" }}>{sg(l.vega)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <span style={quiet}>Entry prices are end-of-day closes. A current executable price per leg needs live option quotes, which are not available here; the structure’s value is a model estimate. The legs are for diagnosis and execution, not independent stops.</span>
            </div>
          )}

          {d.scenarios.length > 0 && (
            <div data-testid="desk-levels-scenarios" className="flex flex-col" style={{ gap: 6, paddingTop: 10, borderTop: "1px solid var(--line-2)" }}>
              <span style={{ fontSize: 13, fontWeight: 600 }}>Scenarios</span>
              <span style={quiet}>Every leg repriced for the price move, the IV change and the time elapsed (per share, model estimate)</span>
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

          <div data-testid="desk-levels-loss-figures" className="flex flex-col" style={{ gap: 4, paddingTop: 10, borderTop: "1px solid var(--line-2)" }}>
            <span style={{ fontSize: 13, fontWeight: 600 }}>Why the loss figures differ</span>
            <span style={quiet}>
              Maximum loss before costs {inr(d.costs.maxLossGross == null ? null : Math.abs(d.costs.maxLossGross))}. The plotted net loss adds the entry costs ({inr(d.costs.entry)}); capital at risk {inr(d.costs.capitalAtRisk)} is the worst net loss with entry and exit costs on every leg
              (round trip {inr(d.costs.roundTrip)}, an assumed cost model). They are one position with different cost treatments, not different positions.
              {d.costs.capitalBasis ? ` Basis: ${d.costs.capitalBasis}.` : ""}{inLab ? " Funds and margin needed are Zerodha’s calculator, shown above." : ""}
            </span>
          </div>
          <ul data-testid="desk-levels-caveats" style={{ margin: 0, paddingLeft: 18, ...quiet }}>{d.caveats.map((c) => <li key={c}>{c}</li>)}</ul>
        </>
      )}
    </section>
  );
}
