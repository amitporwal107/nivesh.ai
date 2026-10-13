/**
 * The portfolio facts the shell shows around the conversation (rail footer,
 * home copy, "Your context"). One query: GET /api/portfolio/holdings-enriched
 * via useHoldingsEnriched, shared with the rest of the app through the cache.
 *
 * `usePortfolioSummary` is not used here: its `asOf` falls back to the current
 * time when no statement date exists, and its day/week changes are fixed at 0.
 */
import { useHoldingsEnriched } from "@/hooks/use-portfolio";

export interface AllocationPart {
  key: string;
  label: string;
  pct: number;
}

export interface PortfolioContext {
  status: "loading" | "error" | "empty" | "ready";
  refetch: () => void;
  holdingsCount: number;
  valueRs: number | null;
  investedRs: number | null;
  gainRs: number | null;
  /** Percent units (22.6 = 22.6%). */
  gainPct: number | null;
  xirrPct: number | null;
  /** Asset-class mix, largest first. Percent units. */
  allocation: AllocationPart[];
  /** When the backend generated this snapshot, if it said. */
  generatedAt?: string;
}

function mapAllocation(actual: unknown): AllocationPart[] {
  if (!actual || typeof actual !== "object") return [];
  return Object.entries(actual as Record<string, unknown>)
    .map(([key, raw]) => ({ key, label: key.charAt(0).toUpperCase() + key.slice(1).replace(/_/g, " "), pct: typeof raw === "number" ? raw : Number(raw) }))
    .filter((p) => Number.isFinite(p.pct) && p.pct > 0)
    .sort((a, b) => b.pct - a.pct);
}

const num = (v: number | null | undefined): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

export function usePortfolioContext(): PortfolioContext {
  const q = useHoldingsEnriched();
  const base = { refetch: () => { void q.refetch(); }, holdingsCount: 0, valueRs: null, investedRs: null, gainRs: null, gainPct: null, xirrPct: null, allocation: [] as AllocationPart[] };
  if (q.isPending) return { ...base, status: "loading" };
  if (q.isError || !q.data) return { ...base, status: "error" };

  const d = q.data;
  const holdingsCount = d.holdings.length;
  const valueRs = num(d.totals?.value_rs);
  if (holdingsCount === 0 || !valueRs || valueRs <= 0) return { ...base, status: "empty" };

  return {
    ...base,
    status: "ready",
    holdingsCount,
    valueRs,
    investedRs: num(d.totals?.invested_rs),
    gainRs: num(d.totals?.pnl_rs),
    gainPct: num(d.totals?.pnl_pct),
    xirrPct: num(d.totals?.xirr_pct),
    allocation: mapAllocation(d.allocation_actual),
    generatedAt: d.generated_at,
  };
}
