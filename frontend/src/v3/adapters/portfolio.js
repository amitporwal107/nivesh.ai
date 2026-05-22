// Portfolio view-model adapter — calls existing backend endpoints and maps
// responses to the V3 view-model shape. If a call fails (no session, backend
// down, or running outside an authenticated context), we fall back to a
// realistic placeholder so screens always render.
//
// Endpoints touched (all owned by existing routes; nothing new):
//   GET  /api/portfolio/analytics             — totals, asset_allocation, risk_score, top_gainers
//   GET  /api/portfolio/holdings-enriched     — enriched holdings + alerts + health
//   GET  /api/insights/v3-portfolio           — portfolio_score, deviation, drift breakdown
//   GET  /api/intelligence/portfolio          — narrated portfolio intelligence
//   POST /api/copilot/widgets/portfolio_var   — drawdown / VaR
//   POST /api/copilot/widgets/tax_harvest     — harvestable LTCG candidates

import { apiGet, apiPost } from "./apiClient";
import { useAsync } from "../hooks/useAsync";

// ─── Placeholder — null/empty so backend absence shows "—" not fake numbers ──
const PLACEHOLDER = {
  user: { name: "Investor", greeting: "Good evening" },
  summary: {
    totalValue: 0,
    investedValue: 0,
    delta1d: 0,
    delta1dPct: 0,
    xirr: 0,
  },
  funds: { count: null, amcCount: null, idealMin: 5, idealMax: 7 },
  overlap: { maxPct: null, pairs: null },
  allocation: [],
  topHoldings: [],
  goals: [],
  sip: { monthly: 0, gap: 0, count: 0 },
  risk: { score: null, level: null, drawdown: null },
  tax: { unrealizedLtcg: null, stcg: null, harvestable: null, ltcgUsed: null, ltcgFree: null },
  performance: { ytd: null, oneY: null, threeY: null, benchmarkYtd: null },
  market: { nifty: null, niftyDeltaPct: null, sensex: null, sensexDeltaPct: null },
  _source: "placeholder",
};

const ASSET_COLOR = {
  equity: "var(--v3-saffron)",
  mutual_fund: "var(--v3-saffron)",
  etf: "var(--v3-saffron)",
  debt: "var(--v3-moss)",
  bond: "var(--v3-moss)",
  gold: "var(--v3-gold)",
  sgb: "var(--v3-gold)",
  international: "var(--v3-indigo)",
  cash: "var(--v3-ink-3)",
  other: "var(--v3-ink-4)",
};

const ASSET_LABEL = {
  equity: "Equity",
  mutual_fund: "Mutual funds",
  etf: "ETFs",
  debt: "Debt",
  bond: "Bonds",
  gold: "Gold",
  sgb: "SGBs",
  international: "International",
  cash: "Cash",
  other: "Other",
};

// ─── Mapping helpers ───────────────────────────────────────────────────────

function mapAnalytics(analytics) {
  if (!analytics) return null;
  const totalValue = analytics.current_value || 0;
  const invested = analytics.total_invested || 0;
  const allocationRaw = analytics.asset_allocation || [];

  const allocation = allocationRaw
    .map((a) => ({
      label: ASSET_LABEL[a.name] || a.name,
      value: totalValue > 0 ? Math.round((a.value / totalValue) * 100) : 0,
      color: ASSET_COLOR[a.name] || "var(--v3-ink-4)",
      raw: a.value,
    }))
    .filter((a) => a.value > 0);

  const topHoldings = (analytics.top_gainers || []).slice(0, 5).map((g) => ({
    name: g.name,
    category: ASSET_LABEL[g.asset_type] || g.asset_type || "—",
    value: g.value || 0,
    return1y: g.pct_change || 0,
  }));

  return {
    summary: {
      totalValue,
      investedValue: invested,
      delta1d: (analytics.total_returns ?? 0),
      delta1dPct: analytics.returns_pct ?? 0,
      xirr: analytics.xirr ?? null,
    },
    allocation: allocation.length ? allocation : [],
    topHoldings: topHoldings.length ? topHoldings : [],
    risk: {
      score: analytics.risk_score ?? null,
      level: analytics.risk_label || null,
      drawdown: analytics.drawdown ?? null,
    },
  };
}

function mapEnriched(enriched) {
  if (!enriched || !enriched.holdings?.length) return null;
  const mfHoldings = enriched.holdings.filter(
    (h) => h.asset_type === "mutual_fund" || h.asset_type === "mf"
  );
  const fundCount = mfHoldings.length;
  const amcCount = new Set(
    mfHoldings.map((h) => (h.name || "").split(" ")[0]).filter(Boolean)
  ).size;

  const topHoldings = enriched.holdings
    .slice()
    .sort((a, b) => (b.value_rs || 0) - (a.value_rs || 0))
    .slice(0, 5)
    .map((h) => ({
      name: h.name,
      category: h.category || ASSET_LABEL[h.asset_type] || "—",
      value: h.value_rs || 0,
      return1y: h.pnl_pct || 0,
    }));

  return {
    funds: {
      count: fundCount,
      amcCount: amcCount,
      idealMin: 5,
      idealMax: 7,
    },
    topHoldings: topHoldings.length ? topHoldings : [],
    summary: {
      totalValue: enriched.totals?.value_rs ?? 0,
      investedValue: enriched.totals?.invested_rs ?? 0,
    },
    health: enriched.health || null,
  };
}

function mapV3Score(v3) {
  if (!v3) return null;
  return {
    portfolioScore: v3.portfolio_score ?? null,
    sectorTop: v3.top_sector || null,
    sectorTopPct: v3.top_sector_pct || null,
    holdingsScored: v3.holdings_scored ?? null,
  };
}

function mapVar(varRes) {
  if (!varRes) return null;
  return {
    drawdown: varRes.max_drawdown ?? varRes.var_99 ?? null,
    var95: varRes.var_95 ?? null,
    sharpe: varRes.sharpe ?? null,
  };
}

function mapTaxHarvest(t) {
  if (!t) return null;
  return {
    unrealizedLtcg: t.unrealized_ltcg ?? t.total_ltcg ?? null,
    stcg: t.unrealized_stcg ?? t.stcg ?? null,
    harvestable: t.harvestable ?? t.harvest_amount ?? null,
    ltcgUsed: t.ltcg_used ?? null,
    ltcgFree: t.ltcg_exemption_remaining ?? null,
    candidates: t.candidates || t.holdings || [],
  };
}

function merge(...layers) {
  // Deep-ish merge for our flat-ish shape. Later layers win unless null/undefined.
  const out = {};
  for (const layer of layers) {
    if (!layer) continue;
    for (const k of Object.keys(layer)) {
      if (layer[k] == null) continue;
      if (
        typeof layer[k] === "object" &&
        !Array.isArray(layer[k]) &&
        typeof out[k] === "object" &&
        !Array.isArray(out[k])
      ) {
        out[k] = { ...out[k], ...layer[k] };
      } else {
        out[k] = layer[k];
      }
    }
  }
  return out;
}

// ─── Public hooks ──────────────────────────────────────────────────────────

/**
 * Combined portfolio snapshot — calls all the cheap GETs in parallel,
 * merges into the V3 view model, and falls back to placeholder if any
 * piece is missing. Screens consume `{ data, loading, error, refetch }`.
 */
export function usePortfolioSummary() {
  return useAsync(
    async () => {
    const [analytics, enriched, v3score, intel, varBlock, harvest, profile] = await Promise.all([
      apiGet("/portfolio/analytics"),
      apiGet("/portfolio/holdings-enriched"),
      apiGet("/insights/v3-portfolio"),
      apiGet("/intelligence/portfolio", { narrate: "false" }),
      apiPost("/copilot/widgets/portfolio_var", {}),
      apiPost("/copilot/widgets/tax_harvest", {}),
      apiGet("/user/profile"),
    ]);

    const mapped = merge(
      PLACEHOLDER,
      { user: mapUser(intel.data, profile.data) },
      mapAnalytics(analytics.data),
      mapEnriched(enriched.data),
      { v3: mapV3Score(v3score.data) },
      { risk: mapVar(varBlock.data) },
      { tax: mapTaxHarvest(harvest.data) }
    );

    // Mark whether we got any real backend hit so screens can show a soft banner.
    const anyError = [analytics, enriched, v3score, intel, varBlock, harvest, profile].every(
      (r) => r.error != null
    );
    return {
      data: { ...mapped, _source: anyError ? "placeholder" : "live" },
      error: anyError ? { status: 0, message: "Backend unreachable, showing demo data" } : null,
    };
  },
  [],
  { initialData: PLACEHOLDER }
  );
}

function mapUser(intel, profile) {
  // Prefer the explicit profile name; fall back to intel narration data.
  const fromProfile = profile?.full_name || profile?.name || profile?.display_name || (profile?.email && profile.email.split("@")[0]);
  const fromIntel = intel?.user_name || intel?.name || intel?.user?.name;
  const name = fromProfile || fromIntel;
  if (!name) return null;
  // Capitalise common "rohan.mehta" → "Rohan Mehta" patterns.
  const pretty = String(name)
    .replace(/[._-]+/g, " ")
    .split(" ")
    .filter(Boolean)
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(" ");
  return { name: pretty, greeting: pickGreeting() };
}

function pickGreeting() {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

// Synchronous accessor for code paths that just want defaults (rarely used).
export function loadPortfolio() {
  return PLACEHOLDER;
}
