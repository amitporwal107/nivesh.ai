/**
 * Sector rotation heatmap — the read the screen needs.
 *
 *   GET /api/markets/sector-heatmap?index=NIFTY50   the index's stocks and sectors, end of day: weights from the
 *                                                   index constituents, 1D / 1W / 1M returns on adjusted closes,
 *                                                   each sector's pull on the index, breadth, and the fields the
 *                                                   route could not fill (`unavailable`, with the reason)
 *
 * Nothing here trusts the response shape: a missing or non-numeric field is null, never 0, and a body without the
 * `sectors` or `stocks` list the route always sends throws a contract error.
 */
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";

export type PeriodKey = "d" | "w" | "m";
type Raw = Record<string, unknown>;
const isRec = (v: unknown): v is Raw => !!v && typeof v === "object" && !Array.isArray(v);
const rec = (v: unknown): Raw => (isRec(v) ? v : {});
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);
function num(v: unknown): number | null {
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v === "string" && v.trim() !== "") { const n = Number(v); return Number.isFinite(n) ? n : null; }
  return null;
}
const triple = (v: unknown): Record<PeriodKey, number | null> => { const r = rec(v); return { d: num(r.d), w: num(r.w), m: num(r.m) }; };
const noRetry4xx = (count: number, e: unknown) =>
  !(e instanceof ApiError && (e.kind === "contract_drift" || (e.status != null && e.status >= 400 && e.status < 500))) && count < 1;

export interface HeatStock {
  symbol: string;
  name: string | null;
  sector: string;
  close: number | null;
  weightPct: number | null;
  tradedValueCr: number | null;
  returns: Record<PeriodKey, number | null>;
  indexImpactD: number | null;
  relVolume: number | null;
}

export interface HeatSector {
  name: string;
  stocks: number;
  weightPct: number | null;
  returns: Record<PeriodKey, number | null>;
  contribution: Record<PeriodKey, number | null>;
}

export interface Heatmap {
  asOf: string | null;
  index: string;
  source: string | null;
  mode: string | null;
  sessions: Record<PeriodKey, number | null>;
  sectors: HeatSector[];
  stocks: HeatStock[];
  breadth: { advances: number | null; declines: number | null; unchanged: number | null };
  weighted: Record<PeriodKey, number | null>;
  /** "index_list" = the index's own weights; "market_cap" = market-cap shares (they differ a little from the published index move). */
  weightBasis: string | null;
  weightNote: string | null;
  unavailable: Array<{ field: string; reason: string; symbols: string[] }>;
}

async function fetchHeatmap(index: string, signal?: AbortSignal): Promise<Heatmap> {
  const res = await http({ path: "/api/markets/sector-heatmap", query: { index }, signal });
  const d = rec(res.data);
  if (!Array.isArray(d.sectors) || !Array.isArray(d.stocks)) throw ApiError.contractDrift("markets.sector-heatmap: no sectors or stocks list");
  const sectors = d.sectors.flatMap((v): HeatSector[] => {
    const r = rec(v);
    const name = str(r.name);
    if (!name) return [];
    return [{ name, stocks: num(r.stocks) ?? 0, weightPct: num(r.weight_pct), returns: triple(r.returns), contribution: triple(r.contribution_pct) }];
  });
  const stocks = d.stocks.flatMap((v): HeatStock[] => {
    const r = rec(v);
    const symbol = str(r.symbol);
    if (!symbol) return [];
    return [{
      symbol: symbol.toUpperCase(), name: str(r.name), sector: str(r.sector) ?? "Unclassified", close: num(r.close), weightPct: num(r.weight_pct),
      tradedValueCr: num(r.traded_value_cr), returns: triple(r.returns), indexImpactD: num(rec(r.index_impact_pct).d), relVolume: num(r.rel_volume),
    }];
  });
  const b = rec(d.breadth);
  const s = rec(d.sessions);
  const unavailable = Array.isArray(d.unavailable)
    ? d.unavailable.flatMap((v): Array<{ field: string; reason: string; symbols: string[] }> => {
        const r = rec(v);
        const field = str(r.field);
        const symbols = Array.isArray(r.symbols) ? r.symbols.flatMap((x) => { const y = str(x); return y ? [y] : []; }) : [];
        return field ? [{ field, reason: str(r.reason) ?? "no reason given", symbols }] : [];
      })
    : [];
  return {
    asOf: str(d.as_of), index: str(d.index) ?? index, source: str(d.source), mode: str(d.mode),
    sessions: { d: num(s.d), w: num(s.w), m: num(s.m) }, sectors, stocks,
    breadth: { advances: num(b.advances), declines: num(b.declines), unchanged: num(b.unchanged) },
    weighted: triple(d.weighted_change), weightBasis: str(d.weight_basis), weightNote: str(d.weight_note), unavailable,
  };
}

/** GET /api/markets/sector-heatmap — end of day, so it changes once a session. */
export function useSectorHeatmap(index: string) {
  return useQuery<Heatmap>({
    queryKey: ["copilot", "sector-heatmap", index],
    staleTime: 10 * 60_000,
    retry: noRetry4xx,
    queryFn: ({ signal }) => fetchHeatmap(index, signal),
  });
}

/** "NIFTY50" → "Nifty 50"; any other index is shown as the route names it. */
export function indexLabel(code: string): string {
  return code.toUpperCase() === "NIFTY50" ? "Nifty 50" : code;
}
