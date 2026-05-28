/**
 * Analytics adapter — concentration, diversification (overlap), risk.
 *
 * Endpoint availability per integration docs (2026-05-28):
 *   GET /api/portfolio/exposure/concentration    → LIVE
 *   GET /api/intelligence/portfolio?narrate=true → LIVE (overlap_matrix field used for overlap())
 *   /api/dashboards/diversification              → NOT YET (correlation stays mock-only)
 *   /api/dashboards/risk                         → NOT YET (risk stays mock-only)
 *
 * `correlation()` and `risk()` on the real adapter return graceful empty stubs
 * so the UI degrades rather than throwing. The mock adapter still provides
 * plausible data for local dev / staging.
 */
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { ConcentrationBreakdownC } from "@/services/contracts/portfolio.contract";
import type { ConcentrationSnapshot, SectorAllocation } from "@/types/concentration";
import type { CorrelationMatrix, FundOverlapPair } from "@/types/diversification";
import type { RiskSnapshot } from "@/types/risk";

export interface AnalyticsAdapter {
  concentration(): Promise<ConcentrationSnapshot>;
  /** Fund-pair overlap % — real data from /api/intelligence/portfolio. */
  overlap(): Promise<FundOverlapPair[]>;
  /**
   * Stock-level ρ matrix — no backend endpoint yet; real adapter returns
   * an empty stub derived from overlap pairs. Mock returns plausible data.
   */
  correlation(): Promise<CorrelationMatrix>;
  /**
   * VaR / drawdown / beta — no backend endpoint yet; real adapter returns
   * empty stub. Mock returns plausible data.
   */
  risk(): Promise<RiskSnapshot>;
}

export const realAnalyticsAdapter: AnalyticsAdapter = {
  async concentration() {
    const res = await http({ path: "/api/portfolio/exposure/concentration" });
    const parsed = ConcentrationBreakdownC.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`analytics.concentration: ${parsed.error.message}`);
    return mapConcentration(parsed.data);
  },

  /**
   * Real source: GET /api/intelligence/portfolio → pairwise_overlap (or overlap_matrix)
   * The field gives fund-to-fund overlap based on shared top-10 holdings.
   */
  async overlap() {
    const res = await http({ path: "/api/intelligence/portfolio", query: { narrate: true } });
    const body = res.data as { pairwise_overlap?: unknown; overlap_matrix?: unknown };
    return mapOverlap(body.pairwise_overlap ?? body.overlap_matrix);
  },

  /**
   * No backend endpoint yet — return a minimal stub so the UI renders
   * with empty tickers/matrix rather than crashing. KPIs show 0.
   */
  async correlation(): Promise<CorrelationMatrix> {
    return {
      tickers: [],
      values: [],
      hotPairs: [],
      avgCrossCorrelation: 0,
      effectiveN: 0,
      redundantPairs: 0,
    };
  },

  /**
   * No backend endpoint yet — return a zeroed stub. The Risk page renders
   * "N/A" states gracefully when values are 0.
   */
  async risk(): Promise<RiskSnapshot> {
    return {
      vaR95Pct: 0,
      vaR95Paise: 0,
      annualVolPct: 0,
      benchmarkVolPct: 0,
      maxDrawdownPct: 0,
      beta: 0,
      riskDrivers: [],
      stressScenarios: [],
    };
  },
};

function mapOverlap(raw: unknown): FundOverlapPair[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((p: Record<string, unknown>) => ({
    fundA: String(p.a_name ?? p.fund_a ?? p.fundA ?? ""),
    fundB: String(p.b_name ?? p.fund_b ?? p.fundB ?? ""),
    overlapPct: Number(p.overlap_pct ?? p.overlapPct ?? 0),
    status: (["redundant", "related", "diversifying"].includes(String(p.status))
      ? p.status
      : "diversifying") as FundOverlapPair["status"],
  }));
}

/**
 * Backend `sector` payload is an opaque object — we accept both `items`
 * (current backend) and `breakdown` (legacy). Also `hhi` vs `herfindahl`,
 * and `top_stock` is derived from items[0] if not explicitly present.
 */
function mapConcentration(body: import("@/services/contracts/portfolio.contract").ConcentrationBreakdownC): ConcentrationSnapshot {
  const sector = (body.sector ?? {}) as {
    items?: unknown; breakdown?: unknown;
    top_stock?: { name?: string; pct?: number };
    hhi?: number; herfindahl?: number;
    sectors_over_cap?: number;
    caution_pct?: number;
  };
  const rawItems = Array.isArray(sector.items) ? sector.items
    : Array.isArray(sector.breakdown) ? sector.breakdown : [];
  const items = rawItems as Array<{ name: string; pct: number; cap_pct?: number }>;

  const cautionPct = sector.caution_pct ?? 25;
  const sectors: SectorAllocation[] = items.map((s) => ({
    name: s.name,
    pct: s.pct,
    capPct: s.cap_pct ?? cautionPct,
    isOverCap: (s.pct ?? 0) > (s.cap_pct ?? cautionPct),
  }));

  const topItem = items.length > 0 ? items[0] : undefined;

  return {
    asOf: new Date().toISOString().slice(0, 10),
    topStockPct: sector.top_stock?.pct ?? topItem?.pct ?? 0,
    topStockName: sector.top_stock?.name ?? topItem?.name ?? "",
    sectorOverCount: sector.sectors_over_cap ?? items.filter((s) => s.pct > cautionPct).length,
    sectors,
    herfindahl: sector.hhi ?? sector.herfindahl ?? 0,
  };
}
