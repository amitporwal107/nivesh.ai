/**
 * Smart trading desk — Options & futures lab · Paper strategies · Compare: the ready-made structures of one market view side by side for the SAME underlying and expiry, each worked out by the
 * desk's own routes (the payoff engine through POST /api/desk/strategy/levels, and Zerodha's margin calculator through POST /api/fno/margin). The browser computes nothing.
 *
 * There is deliberately NO ranking and no "best" marker: a ranking needs a probability of profit and an expected-return model that do not exist here, and weights that no test has validated.
 * The table is sorted only by the column the user picks; every figure is per share, from end-of-day closes, and the rule-based levels are hypothetical.
 */
import { useMemo, useState } from "react";
import { useQueries } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { LoadingBlock } from "../../components/ui";
import type { ChainState } from "../trading/fno";
import { TEMPLATES, legsFor, parseMargin, type LegRow, type MarginAnswer } from "./FnoBuilder";
import { parseLevels, type Levels } from "./FnoLevels";
import { wallsOf } from "./fno-parts";

type View = "bullish" | "bearish" | "neutral" | "others";
const VIEWS: Array<{ key: View; label: string }> = [{ key: "bullish", label: "Bullish" }, { key: "bearish", label: "Bearish" }, { key: "neutral", label: "Neutral" }, { key: "others", label: "Others" }];
const quiet = { fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" } as const;
const f2 = (n: number | null | undefined) => (n == null ? "—" : new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n));
const inr = (n: number | null | undefined) => (n == null ? "—" : `₹${new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(n)}`);

interface Row { id: string; name: string; levels: Levels | null; margin: MarginAnswer | null; marginWhy: string | null; pending: boolean; failed: boolean }
type Key = "name" | "entry" | "maxProfit" | "maxLoss" | "rr" | "delta" | "theta" | "vega" | "margin" | "charges";
const val = (r: Row, k: Key): number | string | null => {
  const l = r.levels?.valid ? r.levels : null;
  switch (k) {
    case "name": return r.name;
    case "entry": return l?.entry == null ? null : (l.kind === "credit" ? l.entry : -l.entry);
    case "maxProfit": return l?.maxProfit ?? null;
    case "maxLoss": return l?.maxLoss ?? null;
    case "rr": return l?.riskReward ?? null;
    case "delta": return l?.greeks.delta ?? null;
    case "theta": return l?.greeks.theta ?? null;
    case "vega": return l?.greeks.vega ?? null;
    case "margin": return r.margin?.required ?? null;
    case "charges": return r.margin?.charges.total ?? null;
  }
};

export function CompareView({ symbol, state }: { symbol: string; state: ChainState }) {
  const chain = state.status === "ok" ? state.chain : null;
  const [view, setView] = useState<View>("bullish");
  const [sort, setSort] = useState<{ key: Key; dir: "asc" | "desc" } | null>(null);
  const lot = chain?.lot_size ?? null;
  const items = useMemo(() => {
    if (!chain || lot == null || chain.summary.spot == null) return [];
    const w = wallsOf(chain.summary);
    return TEMPLATES.filter((t) => t.view === view).map((t) => {
      const legs: LegRow[] = legsFor(t, chain);
      const priced = legs.every((l) => Number(l.price) > 0);
      const payoff = { underlying: symbol, reference_price: chain.summary.spot as number, as_of: chain.summary.as_of, grid: { from_pct: -12, to_pct: 12, points: 121 },
        legs: legs.map((l) => ({ kind: "option", side: l.side, quantity: l.lots, lot_size: lot, entry_price: Number(l.price), expiry: chain.summary.expiry, strike: l.strike, option_type: l.kind, price_source: "end-of-day close", underlying: symbol })) };
      const refs = { put_wall: w.put?.strike ?? null, call_wall: w.call?.strike ?? null, expected_move: chain.summary.expected_move ?? null };
      const marginLegs = legs.map((l) => ({ side: l.side, option_type: l.kind, expiry: chain.summary.expiry, strike: l.strike, lots: l.lots }));
      return { t, priced, payoff, refs, marginLegs };
    });
  }, [chain, lot, symbol, view]);

  const levelsQ = useQueries({ queries: items.map((i) => ({
    queryKey: ["copilot", "desk", "compare-levels", JSON.stringify([i.payoff, i.refs])], enabled: i.priced, staleTime: 60_000, retry: false,
    queryFn: async ({ signal }: { signal?: AbortSignal }) => parseLevels((await http({ method: "POST", path: "/api/desk/strategy/levels", body: { payoff: i.payoff, refs: i.refs }, noRetry: true, timeoutMs: 30_000, signal })).data),
  })) });
  const marginQ = useQueries({ queries: items.map((i) => ({
    queryKey: ["copilot", "desk", "compare-margin", symbol, chain?.summary.expiry, JSON.stringify(i.marginLegs)], enabled: i.priced && !!chain, staleTime: 60_000, retry: false,
    queryFn: async ({ signal }: { signal?: AbortSignal }): Promise<{ ok: MarginAnswer | null; why: string | null }> => {
      try {
        return { ok: parseMargin((await http({ method: "POST", path: "/api/fno/margin", noRetry: true, timeoutMs: 20_000, signal, body: { underlying: symbol, legs: i.marginLegs } })).data), why: null };
      } catch (e) {
        const status = (e as { status?: number }).status;
        return { ok: null, why: status === 503 ? "no Kite login today" : "not answered" };
      }
    },
  })) });

  const rows: Row[] = items.map((i, n) => ({
    id: i.t.id, name: i.t.name, levels: levelsQ[n]?.data ?? null, margin: marginQ[n]?.data?.ok ?? null, marginWhy: marginQ[n]?.data?.why ?? (i.priced ? null : "a leg has no close"),
    pending: !!(levelsQ[n]?.isFetching || marginQ[n]?.isFetching), failed: !!levelsQ[n]?.isError,
  }));
  const shown = useMemo(() => {
    if (!sort) return rows;
    const dir = sort.dir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const x = val(a, sort.key), y = val(b, sort.key);
      if (x == null && y == null) return 0;
      if (x == null) return 1;
      if (y == null) return -1;
      return (typeof x === "string" ? x.localeCompare(String(y)) : (x as number) - (y as number)) * dir;
    });
  }, [rows, sort]);

  if (state.status === "loading") return <LoadingBlock label={`Loading the ${symbol} chain`} rows={4} />;
  if (!chain) return <span data-testid="desk-compare-nochain" style={quiet}>{state.status === "none" ? state.message : `The ${symbol} chain didn’t load, so there is nothing to compare.`}</span>;

  const head = (k: Key, label: string) => (
    <th key={k} scope="col" aria-sort={sort?.key === k ? (sort.dir === "asc" ? "ascending" : "descending") : "none"} style={{ textAlign: k === "name" ? "left" : "right", padding: "6px 8px", fontSize: 11, fontWeight: 500, color: "var(--cp-ink-3)", whiteSpace: "nowrap" }}>
      <button type="button" data-testid={`desk-compare-sort-${k}`} onClick={() => setSort((s) => (s?.key === k ? { key: k, dir: s.dir === "desc" ? "asc" : "desc" } : { key: k, dir: k === "name" ? "asc" : "desc" }))}
        style={{ background: "none", border: 0, padding: 0, color: "inherit", font: "inherit", cursor: "pointer" }}>{label}{sort?.key === k ? (sort.dir === "asc" ? " ▲" : " ▼") : ""}</button>
    </th>
  );
  return (
    <div data-testid="desk-compare" data-symbol={symbol} className="flex min-w-0 flex-col" style={{ gap: 12 }}>
      <div role="group" aria-label="Market view" className="flex flex-wrap" style={{ gap: 6 }}>
        {VIEWS.map((v) => (
          <button key={v.key} type="button" aria-pressed={view === v.key} data-testid={`desk-compare-view-${v.key}`} onClick={() => setView(v.key)}
            style={{ padding: "6px 12px", minHeight: 36, borderRadius: 999, fontSize: 13, cursor: "pointer", border: `1px solid ${view === v.key ? "var(--mint-line)" : "var(--line-2)"}`, background: view === v.key ? "var(--mint-soft)" : "transparent", color: view === v.key ? "var(--mint)" : "var(--cp-ink-2)" }}>{v.label}</button>
        ))}
        <span className="cp-mono-note" style={{ alignSelf: "center" }}>{symbol} · {chain.summary.expiry} expiry · end-of-day closes</span>
      </div>
      <div style={{ overflowX: "auto" }} className="cp-card">
        <table data-testid="desk-compare-table" style={{ borderCollapse: "collapse", width: "100%", minWidth: 760 }}>
          <thead><tr>{head("name", "Structure")}{head("entry", "Entry (net)")}{head("maxProfit", "Max profit")}{head("maxLoss", "Max loss")}{head("rr", "Reward : risk")}{head("delta", "Net delta")}{head("theta", "Theta / day")}{head("vega", "Vega")}{head("margin", "Margin")}{head("charges", "Charges")}</tr></thead>
          <tbody>
            {shown.map((r) => {
              const l = r.levels?.valid ? r.levels : null;
              const cell = (testId: string, text: string) => <td data-testid={`desk-compare-${testId}`} style={{ textAlign: "right", padding: "8px", fontFamily: "var(--mono)", fontSize: 12, whiteSpace: "nowrap" }}>{text}</td>;
              return (
                <tr key={r.id} data-testid="desk-compare-row" data-id={r.id} style={{ borderTop: "1px solid var(--line-2)" }}>
                  <td style={{ padding: "8px", fontSize: 13 }}>{r.name}{r.pending && <span style={quiet}> …</span>}{r.failed && <span style={quiet}> (did not load)</span>}{r.levels && !r.levels.valid && <span style={quiet}> (not supported)</span>}</td>
                  {cell("entry", l ? `${l.kind === "credit" ? "credit" : "debit"} ${f2(l.entry)}` : "—")}
                  {cell("maxprofit", f2(l?.maxProfit))}
                  {cell("maxloss", f2(l?.maxLoss))}
                  {cell("rr", f2(l?.riskReward))}
                  {cell("delta", f2(l?.greeks.delta))}
                  {cell("theta", f2(l?.greeks.theta))}
                  {cell("vega", f2(l?.greeks.vega))}
                  {cell("margin", r.margin ? inr(r.margin.required) : r.marginWhy ? `— (${r.marginWhy})` : "—")}
                  {cell("charges", inr(r.margin?.charges.total))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <span data-testid="desk-compare-note" style={quiet}>
        Same underlying and expiry, per share, from end-of-day closes. Margin and charges are Zerodha’s calculator for the platform account. The rows are not ranked and none is marked best: ranking would need a probability of profit and an expected-return model that do not exist here, and weights no test has validated. Sort by the column you care about. Rule-based, hypothetical figures; research and hypothetical scenarios only.
      </span>
    </div>
  );
}
