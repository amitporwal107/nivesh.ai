/**
 * The portfolio facts the shell shows around the conversation (rail footer,
 * home copy, "Your context"). One query: GET /api/portfolio/holdings-enriched
 * via useHoldingsEnriched, shared with the rest of the app through the cache.
 *
 * `usePortfolioSummary` is not used here: its `asOf` falls back to the current
 * time when no statement date exists, and its day/week changes are fixed at 0.
 */
import { useHoldingsEnriched } from "@/hooks/use-portfolio";
import { useCasState } from "./use-cas-state";

export interface AllocationPart {
  key: string;
  label: string;
  pct: number;
}

export interface PortfolioContext {
  /**
   * "statement": a statement is on file but the holdings view came back empty
   * (the backend can answer with no rows while it is still pricing a fresh
   * import). The value printed on the statement is shown meanwhile, as the
   * existing dashboard does, instead of telling the user they have no portfolio.
   */
  status: "loading" | "error" | "empty" | "statement" | "ready";
  refetch: () => void;
  holdingsCount: number;
  valueRs: number | null;
  investedRs: number | null;
  gainRs: number | null;
  /** Percent units (22.6 = 22.6%). */
  gainPct: number | null;
  xirrPct: number | null;
  /** Asset-class mix (the backend's `allocation_actual`), largest first. Percent units. */
  allocation: AllocationPart[];
  /** Split across instrument types, as the existing portfolio view shows it
   *  under "Allocation by type". Largest first. Percent units. */
  typeSplit: AllocationPart[];
  /** When the backend generated this snapshot, if it said. */
  generatedAt?: string;
  /** Statement period on file, e.g. "Aug/2026". */
  statementPeriod?: string | null;
}

function mapAllocation(actual: unknown): AllocationPart[] {
  if (!actual || typeof actual !== "object") return [];
  return Object.entries(actual as Record<string, unknown>)
    .map(([key, raw]) => ({ key, label: key.charAt(0).toUpperCase() + key.slice(1).replace(/_/g, " "), pct: typeof raw === "number" ? raw : Number(raw) }))
    .filter((p) => Number.isFinite(p.pct) && p.pct > 0)
    .sort((a, b) => b.pct - a.pct);
}

const num = (v: number | null | undefined): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** Instrument-type labels and rules of the existing portfolio view
 *  (pages/Portfolio/Portfolio.tsx: TYPE_STYLE, classifyType, buildTypeSplit —
 *  not exported there). Kept identical so both screens show the same split. */
const TYPE_LABEL: Record<string, string> = {
  equity: "Equity (stocks)",
  mutual_fund: "Mutual funds",
  etf: "ETFs",
  gold: "Gold & SGB",
  bond: "Bonds",
  fd: "Fixed deposits",
  other: "Other",
};

function classifyType(h: { asset_type?: string | null; name?: string | null }): string {
  const at = (h.asset_type ?? "").toLowerCase();
  const name = (h.name ?? "").toLowerCase();
  // SGBs come through as bond/gold/other depending on source — name wins.
  if (/sovereign gold|\bsgb\b/.test(name)) return "gold";
  return at in TYPE_LABEL && at !== "other" ? at : "other";
}

function buildTypeSplit(holdings: Array<{ asset_type?: string | null; name?: string | null; value_rs?: number | null }>): AllocationPart[] {
  const totals = new Map<string, number>();
  let total = 0;
  for (const h of holdings) {
    const v = h.value_rs ?? 0;
    if (!(v > 0)) continue;
    const key = classifyType(h);
    totals.set(key, (totals.get(key) ?? 0) + v);
    total += v;
  }
  if (total <= 0) return [];
  return [...totals.entries()]
    .map(([key, v]) => ({ key, label: TYPE_LABEL[key], pct: (v / total) * 100 }))
    .sort((x, y) => y.pct - x.pct);
}

export function usePortfolioContext(): PortfolioContext {
  const q = useHoldingsEnriched();
  const cas = useCasState();
  const statementPeriod = cas.data?.period ?? null;
  const base = { refetch: () => { void q.refetch(); }, holdingsCount: 0, valueRs: null, investedRs: null, gainRs: null, gainPct: null, xirrPct: null, allocation: [] as AllocationPart[], typeSplit: [] as AllocationPart[], statementPeriod };
  if (q.isPending) return { ...base, status: "loading" };
  if (q.isError || !q.data) return { ...base, status: "error" };

  const d = q.data;
  const holdingsCount = d.holdings.length;
  const valueRs = num(d.totals?.value_rs);
  if (holdingsCount === 0 || !valueRs || valueRs <= 0) {
    // No rows: either there is no portfolio, or a statement is on file and the
    // holdings view is not ready. Wait for the statement check before deciding.
    if (cas.isPending) return { ...base, status: "loading" };
    const onStatement = cas.data?.valueRs ?? null;
    if (onStatement && onStatement > 0) return { ...base, status: "statement", valueRs: onStatement };
    return { ...base, status: "empty" };
  }

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
    typeSplit: buildTypeSplit(d.holdings),
    generatedAt: d.generated_at,
  };
}
