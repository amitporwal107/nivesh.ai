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
export const realAnalyticsAdapter = {
    async concentration() {
        const res = await http({ path: "/api/portfolio/exposure/concentration" });
        const parsed = ConcentrationBreakdownC.safeParse(res.data);
        if (!parsed.success)
            throw ApiError.contractDrift(`analytics.concentration: ${parsed.error.message}`);
        return mapConcentration(parsed.data);
    },
    async correlation() {
        const res = await http({ path: "/api/dashboards/diversification" });
        const bd = res.data.breakdown ?? {};
        return mapCorrelation(bd);
    },
    async overlap() {
        const res = await http({ path: "/api/dashboards/diversification" });
        const bd = res.data.breakdown ?? {};
        return mapOverlap(bd.overlap);
    },
    async risk() {
        const res = await http({ path: "/api/dashboards/risk" });
        const bd = res.data.breakdown ?? {};
        return mapRisk(bd);
    },
};
function mapCorrelation(bd) {
    const raw = (bd.correlation ?? {});
    const tickers = Array.isArray(raw.tickers) ? raw.tickers : [];
    const values = Array.isArray(raw.values) ? raw.values : [];
    const hotPairs = Array.isArray(raw.hot_pairs)
        ? raw.hot_pairs.map((p) => ({ a: String(p.a ?? ""), b: String(p.b ?? ""), rho: Number(p.rho ?? 0) }))
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
function mapOverlap(raw) {
    if (!Array.isArray(raw))
        return [];
    return raw.map((p) => ({
        fundA: String(p.fund_a ?? p.fundA ?? ""),
        fundB: String(p.fund_b ?? p.fundB ?? ""),
        overlapPct: Number(p.overlap_pct ?? p.overlapPct ?? 0),
        status: (["redundant", "related", "diversifying"].includes(String(p.status)) ? p.status : "diversifying"),
    }));
}
function mapRisk(bd) {
    const drivers = Array.isArray(bd.risk_drivers)
        ? bd.risk_drivers.map((d) => ({ name: String(d.name ?? ""), sharePct: Number(d.share_pct ?? 0) }))
        : [];
    const stress = Array.isArray(bd.stress_scenarios)
        ? bd.stress_scenarios.map((s) => ({
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
function mapConcentration(body) {
    const sector = (body.sector ?? {});
    const breakdown = Array.isArray(sector.breakdown) ? sector.breakdown : [];
    const sectors = breakdown.map((s) => ({
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
