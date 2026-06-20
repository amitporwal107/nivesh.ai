/**
 * use-analytics — all methods via the adapter factory (real or mock).
 */
import { useQuery } from "@tanstack/react-query";
import { analyticsService } from "@/services";

export function useConcentration() {
  return useQuery({
    queryKey: ["analytics", "concentration"],
    queryFn: () => analyticsService.concentration(),
  });
}

export function useCorrelation() {
  return useQuery({
    queryKey: ["analytics", "correlation"],
    queryFn: () => analyticsService.correlation(),
  });
}

export function useOverlap() {
  return useQuery({
    queryKey: ["analytics", "overlap"],
    queryFn: () => analyticsService.overlap(),
  });
}

export function useRisk() {
  return useQuery({
    queryKey: ["analytics", "risk"],
    queryFn: () => analyticsService.risk(),
  });
}

export function useConcentrationAnalysis() {
  return useQuery({
    queryKey: ["analytics", "concentration-analysis"],
    queryFn: () => import("@/services/api/http").then(({ http }) =>
      Promise.all([
        http({ path: "/api/portfolio/exposure/concentration" }),
        http({ path: "/api/portfolio/exposure/fund-overlap/matrix" }).catch(() => ({ data: null })),
      ]).then(([conc, overlap]) => ({ concentration: conc.data, overlap: (overlap as { data: unknown }).data }))
    ),
    staleTime: 5 * 60 * 1000,
  });
}

// ── Portfolio X-ray (dashboard look-through hero) ───────────────────────────
// Built entirely from the real /api/portfolio/exposure/concentration envelope
// (the same compute_concentration engine the Insights tab uses). No mock data:
// when the look-through is empty the snapshot's leaders are null and the
// dashboard section simply doesn't render.

export interface XrayLeader {
  name: string;
  pct: number;        // % within its own lens (AMC = % of MF corpus, etc.)
  valueInr: number;   // ₹ value of the bucket
}

export interface XraySnapshot {
  holdingsCount: number;   // number of holdings looked through
  companyCount: number;    // distinct underlying companies (look-through)
  effectiveBets: number;   // effective_n of underlying companies — the "real" bets
  topAmc: XrayLeader | null;
  topSector: XrayLeader | null;
  topStock: (XrayLeader & { funds: number; fundNames: string[] }) | null; // funds = how many funds hold it
  amcBars: XrayLeader[];     // top AMCs for the mini stacked bar
  sectorBars: XrayLeader[];  // top sectors for the mini bars
}

interface RawSectionItem {
  name?: string; pct?: number; value_inr?: number; via_funds_count?: number; fund_names?: string[];
}
interface RawSection { items?: RawSectionItem[]; effective_n?: number; all_items_count?: number }
interface RawConcentration {
  amc?: RawSection; sector?: RawSection; company?: RawSection;
  holdings_count?: number; empty?: boolean;
}

function leader(items: RawSectionItem[] | undefined): XrayLeader | null {
  const it = items?.[0];
  if (!it?.name) return null;
  return { name: it.name, pct: Number(it.pct ?? 0), valueInr: Number(it.value_inr ?? 0) };
}
function bars(items: RawSectionItem[] | undefined, n: number): XrayLeader[] {
  return (items ?? []).slice(0, n)
    .filter((it) => it.name)
    .map((it) => ({ name: it.name!, pct: Number(it.pct ?? 0), valueInr: Number(it.value_inr ?? 0) }));
}

// "Unclassified"/"Other" buckets are real but useless as a hero "largest
// sector" — the look-through engine emits them when a fund's holdings aren't
// sector-tagged. Drop them so the card surfaces a meaningful sector.
const SKIP_SECTOR = new Set(["unclassified", "unknown", "other", "others", "-", ""]);
function meaningfulSector(it: RawSectionItem): boolean {
  return !SKIP_SECTOR.has((it.name ?? "").trim().toLowerCase());
}

function mapXray(raw: RawConcentration): XraySnapshot {
  const company = raw.company ?? {};
  const topStockBase = leader(company.items);
  const topStock = topStockBase
    ? {
        ...topStockBase,
        funds: Number(company.items?.[0]?.via_funds_count ?? 0),
        fundNames: (company.items?.[0]?.fund_names ?? []).filter(Boolean),
      }
    : null;
  const sectorItems = (raw.sector?.items ?? []).filter(meaningfulSector);
  return {
    holdingsCount: Number(raw.holdings_count ?? 0),
    companyCount: Number(company.all_items_count ?? company.items?.length ?? 0),
    effectiveBets: Math.round(Number(company.effective_n ?? 0)),
    topAmc: leader(raw.amc?.items),
    topSector: leader(sectorItems),
    topStock,
    amcBars: bars(raw.amc?.items, 5),
    sectorBars: bars(sectorItems, 5),
  };
}

export function usePortfolioXray() {
  return useQuery({
    queryKey: ["analytics", "xray"],
    queryFn: () => import("@/services/api/http").then(({ http }) =>
      http({ path: "/api/portfolio/exposure/concentration" }).then((r) => mapXray(r.data as RawConcentration))
    ),
    staleTime: 5 * 60 * 1000,
  });
}

export function useRemediation() {
  return useQuery({
    queryKey: ["analytics", "remediation"],
    queryFn: () => import("@/services/api/http").then(({ http }) =>
      http({ path: "/api/portfolio/exposure/remediation" }).then((r) => r.data as {
        recommendations: unknown[];
        total_value: number;
        empty: boolean;
      })
    ),
    staleTime: 5 * 60 * 1000,
  });
}
