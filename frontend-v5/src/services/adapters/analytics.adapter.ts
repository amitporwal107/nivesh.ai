/**
 * Analytics adapter — concentration, diversification, risk.
 *
 *   GET /api/portfolio/exposure/concentration
 *   GET /api/dashboards/diversification   → correlation matrix + overlap pairs
 *   GET /api/dashboards/risk              → VaR, vol, drawdown, stress scenarios
 */
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { ConcentrationBreakdownC } from "@/services/contracts/portfolio.contract";
import type { ConcentrationSnapshot, SectorAllocation } from "@/types/concentration";
import type { CorrelationMatrix, FundOverlapPair } from "@/types/diversification";
import type { RiskSnapshot } from "@/types/risk";

export interface AnalyticsAdapter {
  concentration(): Promise<ConcentrationSnapshot>;
  correlation(): Promise<CorrelationMatrix>;
  overlap(): Promise<FundOverlapPair[]>;
  risk(): Promise<RiskSnapshot>;
}

export const realAnalyticsAdapter: AnalyticsAdapter = {
  async concentration() {
    const res = await http({ path: "/api/portfolio/exposure/concentration" });
    const parsed = ConcentrationBreakdownC.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`analytics.concentration: ${parsed.error.message}`);
    return mapConcentration(parsed.data);
  },

  async correlation() {
    const res = await http({ path: "/api/dashboards/diversification" });
    const bd = (res.data as { breakdown?: unknown }).breakdown ?? {};
    return mapCorrelation(bd as Record<string, unknown>);
  },

  async overlap() {
    const res = await http({ path: "/api/dashboards/diversification" });
    const bd = (res.data as { breakdown?: unknown }).breakdown ?? {};
    return mapOverlap((bd as Record<string, unknown>).overlap);
  },

  async risk() {
    const res = await http({ path: "/api/dashboards/risk" });
    const bd = (res.data as { breakdown?: unknown }).breakdown ?? {};
    return mapRisk(bd as Record<string, unknown>);
  },
};

function mapCorrelation(bd: Record<string, unknown>): CorrelationMatrix {
  const raw = (bd.correlation ?? {}) as Record<string, unknown>;
  const tickers = Array.isArray(raw.tickers) ? raw.tickers as string[] : [];
  const values = Array.isArray(raw.values) ? raw.values as number[][] : [];
  const hotPairs = Array.isArray(raw.hot_pairs)
    ? (raw.hot_pairs as Array<Record<string, unknown>>).map((p) => ({ a: String(p.a ?? ""), b: String(p.b ?? ""), rho: Number(p.rho ?? 0) }))
    : [];
  return {
    tickers,
    values,
    hotPairs,
    avgCrossCorrelation: Number(raw.avg_cross_correlation ?? 0),
    effectiveN: Number(raw.effective_n ?? tickers.length),
    redundantPairs: Number(raw.redundant_pairs ?? 0),
    overlapWasteRs: bd.overlap_waste_rs != null ? Number(bd.overlap_waste_rs) : undefined,
  };
}

function mapOverlap(raw: unknown): FundOverlapPair[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((p: Record<string, unknown>) => ({
    fundA: String(p.fund_a ?? p.fundA ?? ""),
    fundB: String(p.fund_b ?? p.fundB ?? ""),
    overlapPct: Number(p.overlap_pct ?? p.overlapPct ?? 0),
    status: (["redundant", "related", "diversifying"].includes(String(p.status)) ? p.status : "diversifying") as FundOverlapPair["status"],
  }));
}

function mapRisk(bd: Record<string, unknown>): RiskSnapshot {
  const drivers = Array.isArray(bd.risk_drivers)
    ? (bd.risk_drivers as Array<Record<string, unknown>>).map((d) => ({ name: String(d.name ?? ""), sharePct: Number(d.share_pct ?? 0) }))
    : [];
  const stress = Array.isArray(bd.stress_scenarios)
    ? (bd.stress_scenarios as Array<Record<string, unknown>>).map((s) => ({
        name: String(s.name ?? ""),
        portfolioPct: Number(s.portfolio_pct ?? 0),
        benchPct: Number(s.bench_pct ?? 0),
        recovery: String(s.recovery ?? ""),
      }))
    : [];
  return {
    vaR95Pct: Number(bd.var_95_pct ?? 0),
    vaR95Paise: Number(bd.var_95_rs ?? 0) * 100,
    annualVolPct: Number(bd.annual_vol_pct ?? 0),
    benchmarkVolPct: Number(bd.benchmark_vol_pct ?? 0),
    maxDrawdownPct: Number(bd.max_drawdown_pct ?? 0),
    beta: Number(bd.beta ?? 1),
    riskDrivers: drivers,
    stressScenarios: stress,
  };
}

/**
 * Backend `sector` payload is an opaque object — we expect a `breakdown`
 * array of `{ name, pct, cap_pct }`. If shape differs we render with empty
 * sectors[] rather than throw (req #14 — partial-data rendering).
 */
function mapConcentration(body: import("@/services/contracts/portfolio.contract").ConcentrationBreakdownC): ConcentrationSnapshot {
  const sector = (body.sector ?? {}) as { breakdown?: unknown; top_stock?: { name?: string; pct?: number }; herfindahl?: number; sectors_over_cap?: number };
  const breakdown = Array.isArray(sector.breakdown) ? sector.breakdown as Array<{ name: string; pct: number; cap_pct?: number }> : [];

  const sectors: SectorAllocation[] = breakdown.map((s) => ({
    name: s.name,
    pct: s.pct,
    capPct: s.cap_pct ?? 25,
    isOverCap: (s.pct ?? 0) > (s.cap_pct ?? 25),
  }));

  return {
    asOf: new Date().toISOString().slice(0, 10),
    topStockPct: sector.top_stock?.pct ?? 0,
    topStockName: sector.top_stock?.name ?? "",
    sectorOverCount: sector.sectors_over_cap ?? sectors.filter((s) => s.isOverCap).length,
    sectors,
    herfindahl: sector.herfindahl ?? 0,
  };
}
