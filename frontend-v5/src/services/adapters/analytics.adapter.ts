/**
 * Analytics adapter — concentration, diversification (overlap), risk.
 *
 *   GET /api/portfolio/exposure/concentration    → LIVE (concentration)
 *   GET /api/intelligence/portfolio?narrate=true → LIVE (overlap pairs)
 *   GET /api/dashboards/diversification          → LIVE (effective N, overlap stats, correlation stub)
 *   GET /api/dashboards/risk                     → LIVE (weighted beta, volatility, VaR from NIDP DAAS)
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
   * Correlation matrix + effective N from GET /api/dashboards/diversification.
   * Backend computes fund-overlap + effective N from fund_holdings_cache.
   * tickers/values matrix is not exposed — returns flat hotPairs from overlap.
   */
  async correlation(): Promise<CorrelationMatrix> {
    try {
      const res = await http({ path: "/api/dashboards/diversification", query: { lens: "overlap" } });
      const body = res.data as {
        stat_tiles?: Array<{ label?: string; value?: string | number }>;
        breakdown?: { items?: Array<{ name?: string; value?: number; tone?: string }> };
      };
      const tiles = body.stat_tiles ?? [];
      const tileVal = (label: string) => {
        const t = tiles.find((t) => (t.label ?? "").toLowerCase().includes(label.toLowerCase()));
        return t ? Number(t.value ?? 0) : 0;
      };
      const effectiveN = tileVal("fund") || tileVal("eff");
      const redundantPairs = tileVal("overlap") || tileVal("pair");
      const items = body.breakdown?.items ?? [];
      const hotPairs = items.map((it) => ({
        a: String(it.name ?? ""),
        b: "",
        rho: Number(it.value ?? 0) / 100,
      }));
      return { tickers: [], values: [], hotPairs, avgCrossCorrelation: 0, effectiveN, redundantPairs };
    } catch {
      return { tickers: [], values: [], hotPairs: [], avgCrossCorrelation: 0, effectiveN: 0, redundantPairs: 0 };
    }
  },

  /**
   * VaR / beta / volatility from GET /api/dashboards/risk.
   * Backend computes weighted beta + volatility from NIDP DAAS primitives.
   */
  async risk(): Promise<RiskSnapshot> {
    try {
      const res = await http({ path: "/api/dashboards/risk" });
      const body = res.data as {
        stat_tiles?: Array<{ label?: string; value?: string | number }>;
        breakdown?: { items?: Array<{ name?: string; value?: number; tone?: string }> };
      };
      const tiles = body.stat_tiles ?? [];
      const tileNum = (label: string) => {
        const t = tiles.find((t) => (t.label ?? "").toLowerCase().includes(label.toLowerCase()));
        return t ? parseFloat(String(t.value ?? "0").replace(/[^0-9.-]/g, "")) || 0 : 0;
      };
      const beta = tileNum("beta");
      const volPct = tileNum("vol");
      const varPct = tileNum("var");
      const maxDD = tileNum("max") || tileNum("draw");
      const drivers = (body.breakdown?.items ?? []).map((d) => ({
        name: String(d.name ?? ""),
        sharePct: Number(d.value ?? 0),
      }));
      return {
        vaR95Pct: varPct,
        vaR95Paise: 0,
        annualVolPct: volPct,
        benchmarkVolPct: 0,
        maxDrawdownPct: maxDD,
        beta,
        riskDrivers: drivers,
        stressScenarios: [],
      };
    } catch {
      return { vaR95Pct: 0, vaR95Paise: 0, annualVolPct: 0, benchmarkVolPct: 0, maxDrawdownPct: 0, beta: 0, riskDrivers: [], stressScenarios: [] };
    }
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
