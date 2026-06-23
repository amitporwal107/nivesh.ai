/**
 * Portfolio adapter — composes PortfolioSummary from real endpoints.
 *
 * Real endpoints (portfolio.yaml v2.0.0):
 *   GET  /api/portfolios                          → Portfolio[]
 *   GET  /api/portfolio/holdings                  → Holding[]
 *   POST /api/portfolio/holdings                  → Holding
 *   PUT  /api/portfolio/holdings/{id}             → Holding
 *   DELETE /api/portfolio/holdings/{id}
 *   GET  /api/portfolio/holdings-enriched         → enriched with V3 / badges
 *   GET  /api/search/instruments?q
 *   GET  /api/portfolio/trend?days                → {series:[{date, value_rs}]}
 *   GET  /api/portfolio/sips                      → detected SIPs
 *   GET  /api/portfolio/exposure/concentration    → AMC/sector/company breakdown
 *
 * Pairs with /api/insights/analysis for the health score.
 */
import { http } from "@/services/api/http";
import { apiFetch } from "@/services/api/authed-fetch";
import { ApiError } from "@/services/api/errors";
import {
  HoldingsListRes,
  TrendRes,
  EnrichedHoldingsRes,
  InstrumentSearchRes,
  SipsListRes,
  ConcentrationBreakdownC,
} from "@/services/contracts/portfolio.contract";
import { mapHoldings } from "@/services/mappers/portfolio.mapper";
import { realInsightsAdapter } from "./insights.adapter";
import type { Holding } from "@/types/fund";
import type { PortfolioSummary, NavPoint, AllocationSlice, AssetClass } from "@/types/portfolio";

/** Asset classes the UI knows how to colour/label. */
const ALLOCATION_LABELS: Record<AssetClass, string> = {
  equity: "Equity", debt: "Debt", hybrid: "Hybrid",
  gold: "Gold", international: "International", cash: "Cash",
};

/**
 * Map the backend `allocation_actual` object ({ equity: 66.9, hybrid: 33.1 })
 * into the AllocationSlice[] the donut + Portfolio page expect. Backend gives
 * only percentages, so per-class value is derived from the portfolio total.
 * Returns [] for missing/garbage input — callers must tolerate an empty array.
 */
function mapAllocation(actual: unknown, totalValuePaise: number): AllocationSlice[] {
  if (!actual || typeof actual !== "object") return [];
  return Object.entries(actual as Record<string, unknown>)
    .map(([key, raw]) => {
      const pct = typeof raw === "number" ? raw : Number(raw);
      if (!Number.isFinite(pct) || pct <= 0) return null;
      const assetClass = key.toLowerCase() as AssetClass;
      return {
        assetClass,
        label: ALLOCATION_LABELS[assetClass] ?? (key.charAt(0).toUpperCase() + key.slice(1)),
        pct,
        value: Math.round((pct / 100) * totalValuePaise),
      } satisfies AllocationSlice;
    })
    .filter((s): s is AllocationSlice => s !== null)
    .sort((a, b) => b.pct - a.pct);
}

export interface PortfolioAdapter {
  listHoldings(portfolioId?: string, assetType?: string): Promise<Holding[]>;
  listHoldingsEnriched(fresh?: boolean): Promise<import("@/services/contracts/portfolio.contract").EnrichedHoldingsRes>;
  getSummary(): Promise<PortfolioSummary>;
  getNavHistory(range: "1m" | "3m" | "6m" | "1y" | "all"): Promise<NavPoint[]>;
  searchInstruments(q: string): Promise<import("@/services/contracts/portfolio.contract").InstrumentSearchRes>;
  listSips(): Promise<import("@/services/contracts/portfolio.contract").SipsListRes>;
  getConcentration(): Promise<import("@/services/contracts/portfolio.contract").ConcentrationBreakdownC>;
}

const DAYS_BY_RANGE: Record<string, number> = {
  "1m": 31, "3m": 92, "6m": 183, "1y": 365, "all": 365 * 5,
};

export const realPortfolioAdapter: PortfolioAdapter = {
  async listHoldings(portfolioId, assetType) {
    const res = await http({
      path: "/api/portfolio/holdings",
      query: { portfolio_id: portfolioId, asset_type: assetType },
    });
    const parsed = HoldingsListRes.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`portfolio.listHoldings: ${parsed.error.message}`);
    return mapHoldings(parsed.data);
  },

  async listHoldingsEnriched(fresh = false) {
    const res = await http({ path: "/api/portfolio/holdings-enriched", query: { fresh } });
    const parsed = EnrichedHoldingsRes.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`portfolio.enriched: ${parsed.error.message}`);
    // The backend sends per-row fund CAGR + the matched index CAGR, but not the
    // relative delta the Holdings table / drawer render. Derive it here (once)
    // so every consumer agrees: fund − benchmark, preferring the 1y horizon and
    // falling back to 3y, with the horizon recorded so the label stays honest.
    for (const h of parsed.data.holdings) {
      const any = h as Record<string, number | null | undefined>;
      if (any.benchmark_delta != null) continue;
      const f1 = any.cagr_1y_pct, b1 = any.benchmark_cagr_1y_pct;
      const f3 = any.cagr_3y_pct, b3 = any.benchmark_cagr_3y_pct;
      let delta: number | null = null, horizon: "1y" | "3y" | null = null;
      if (f1 != null && b1 != null) { delta = f1 - b1; horizon = "1y"; }
      else if (f3 != null && b3 != null) { delta = f3 - b3; horizon = "3y"; }
      if (delta != null) {
        any.benchmark_delta = Math.round(delta * 10) / 10;
        (h as Record<string, unknown>).benchmark_delta_horizon = horizon;
      }
    }
    return parsed.data;
  },

  async getSummary() {
    // Compose: enriched-holdings (totals) + insights/analysis (health score)
    // + CAS statement summary (fallback when enrichment prices aren't fetched yet).
    const [enriched, health, casState] = await Promise.all([
      this.listHoldingsEnriched().catch(() => null),
      realInsightsAdapter.analysis().catch(() => null),
      apiFetch("/api/onboarding/state")
        .then((r) => r.ok ? r.json() as Promise<{ cas_portfolio_value_rs?: number | null; cas_statement_date?: string | null }> : null)
        .catch(() => null),
    ]);

    // Use CAS summary value when holdings-enriched hasn't fetched live NAVs yet
    const enrichedValue = (enriched?.totals?.value_rs ?? 0) * 100;
    const casValue      = (casState?.cas_portfolio_value_rs ?? 0) * 100;
    const totalValue    = enrichedValue > 0 ? enrichedValue : casValue;

    const totalCost  = (enriched?.totals?.invested_rs ?? 0) * 100;
    const pnl    = totalValue - totalCost;
    const pnlPct = totalCost === 0 ? 0 : pnl / totalCost;

    return {
      asOf: casState?.cas_statement_date ?? new Date().toISOString(),
      totalValue,
      dayChange:  { abs: 0, pct: 0 },
      weekChange: { abs: 0, pct: 0 },
      yearChange: { abs: pnl, pct: pnlPct },
      healthScore: health?.health.health_score ?? health?.health.score ?? 0,
      riskBucket: "moderate" as const,
      riskBucketIndex: 3,
      allocation: mapAllocation(enriched?.allocation_actual, totalValue),
      topInsights: [],
    };
  },

  async getNavHistory(range) {
    const days = DAYS_BY_RANGE[range] ?? 365;
    const [trendRes, casState] = await Promise.all([
      http({ path: "/api/portfolio/trend", query: { days } }).catch(() => ({ data: null })),
      apiFetch("/api/onboarding/state")
        .then((r) => r.ok ? r.json() as Promise<{
          cas_portfolio_value_rs?: number | null;
          cas_statement_date?: string | null;
          cas_monthly_values?: Array<{ month: string; value_rs: number }> | null;
        }> : null)
        .catch(() => null),
    ]);
    const parsed = TrendRes.safeParse(trendRes.data);
    const trendSeries = parsed.success
      ? parsed.data.series.map((p) => ({
          date:  p.date ?? p.snapshot_date ?? "",
          value: Math.round((p.value_rs ?? p.total_value ?? 0) * 100),
        })).filter(p => p.date)
      : [];

    // Prefer CAS monthly values (from Vision API) when available — they are
    // the authoritative time-series straight from the PDF Summary section.
    const monthly = casState?.cas_monthly_values;
    if (monthly && monthly.length > 0) {
      // Convert "Apr 2025" → ISO date "2025-04-01" for the chart
      const MONTHS: Record<string, string> = {
        Jan:"01", Feb:"02", Mar:"03", Apr:"04", May:"05", Jun:"06",
        Jul:"07", Aug:"08", Sep:"09", Oct:"10", Nov:"11", Dec:"12",
      };
      const casSeries = monthly.map(({ month, value_rs }) => {
        const [m, y] = month.split(" ");
        const mm = MONTHS[m] ?? "01";
        return { date: `${y}-${mm}-01`, value: Math.round(value_rs * 100) };
      });
      return casSeries;
    }

    // Trend series from portfolio snapshots (good once daily cron runs)
    if (trendSeries.length > 0) return trendSeries;

    // Last resort: single data point from CAS statement date + value.
    // Backend stores date as "DD-MMM-YYYY" (e.g. "30-Apr-2026"); convert to
    // ISO "YYYY-MM-DD" so Recharts/Date can parse it correctly.
    if (casState?.cas_statement_date && casState?.cas_portfolio_value_rs) {
      const MONTHS: Record<string, string> = {
        Jan:"01", Feb:"02", Mar:"03", Apr:"04", May:"05", Jun:"06",
        Jul:"07", Aug:"08", Sep:"09", Oct:"10", Nov:"11", Dec:"12",
      };
      const raw = casState.cas_statement_date;
      const m = raw.match(/^(\d{2})-([A-Za-z]{3})-(\d{4})$/);
      const isoDate = m ? `${m[3]}-${MONTHS[m[2]] ?? "01"}-${m[1]}` : raw;
      return [{ date: isoDate, value: Math.round(casState.cas_portfolio_value_rs * 100) }];
    }
    return [];
  },

  async searchInstruments(q) {
    if (!q || q.length < 2) return [];
    const res = await http({ path: "/api/search/instruments", query: { q } });
    const parsed = InstrumentSearchRes.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`portfolio.searchInstruments: ${parsed.error.message}`);
    return parsed.data;
  },

  async listSips() {
    const res = await http({ path: "/api/portfolio/sips" });
    const parsed = SipsListRes.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`portfolio.listSips: ${parsed.error.message}`);
    return parsed.data;
  },

  async getConcentration() {
    // AMC / sector / company / group look-through (the Insights engine).
    const res = await http({ path: "/api/portfolio/exposure/concentration" });
    const parsed = ConcentrationBreakdownC.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`portfolio.concentration: ${parsed.error.message}`);
    return parsed.data;
  },
};
