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
  funds: {
    count: null, amcCount: null, idealMin: 5, idealMax: 7,
    duplicateCount: 0, duplicateValue: 0, duplicateClusters: [],
    regularDirectAnnualLeak: 0, regularDirectFunds: [],
  },
  overlap: { maxPct: null, pairs: null },
  allocation: [],
  topHoldings: [],
  holdings: [],
  topGainers: [],
  topLosers: [],
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

// ─── Selectors — pure functions over the raw enriched holdings array ──────
// Both ports of V2 logic; see ActionablePortfolioView.js for the originals.

// Collapse plan/option/folio/abbreviation tokens so Direct vs Regular vs
// Growth vs IDCW of the same scheme map to the same key.
function normaliseSchemeKey(name) {
  if (!name) return "";
  let n = ` ${String(name).toLowerCase()} `;
  n = n.replace(/\([^)]*\)/g, " ");
  n = n.replace(/[-,.|/]+/g, " ");
  const STRIP = [
    "direct plan", "regular plan", "direct", "regular",
    "growth option", "growth plan", "growth",
    "dividend reinvestment", "dividend payout", "dividend",
    "idcw payout", "idcw reinvestment", "idcw",
    "bonus", "annual", "quarterly", "monthly",
    "mutual fund", "fund of funds", "fund", "scheme",
  ];
  for (const tok of STRIP) {
    n = n.replace(new RegExp(`\\s${tok}\\s`, "g"), " ");
  }
  n = n.replace(/\s(g|d|idcw|gr|gp)\s/g, " ");
  n = n.replace(/^\s+[a-z]{2,5}\s+(?=[a-z])/, " ");
  return n.replace(/\s+/g, " ").trim();
}

const _AMC_ONLY = new Set([
  "hdfc", "icici", "icici prudential", "sbi", "axis", "kotak",
  "uti", "nippon", "nippon india", "sundaram", "tata", "dsp",
  "mirae", "mirae asset", "aditya birla", "aditya birla sun life",
  "franklin", "franklin india", "quant", "edelweiss", "invesco",
  "motilal oswal", "ppfas", "parag parikh", "pgim", "canara robeco",
  "hsbc", "lic", "lic mf", "jm", "navi", "samco", "trust",
]);
function _planOf(name) {
  const n = (name || "").toLowerCase();
  if (/\bdirect\b/.test(n)) return "direct";
  if (/\bregular\b/.test(n)) return "regular";
  return "";
}

/**
 * Find Direct/Regular duplicate clusters in a holdings array. A cluster is
 * the SAME normalised scheme present as BOTH a Direct plan AND a Regular
 * plan (different ISINs). Multi-folio of the same plan is NOT a duplicate.
 * Returns { clusters: [{key, total_value, items}], totalValue, count }.
 */
export function selectDuplicateClusters(holdings) {
  if (!Array.isArray(holdings) || holdings.length === 0) {
    return { clusters: [], totalValue: 0, count: 0 };
  }
  const groups = new Map();
  const totals = new Map();
  for (const h of holdings) {
    const at = (h.asset_type || "").toLowerCase();
    if (at !== "mutual_fund" && at !== "mutual fund" && at !== "etf") continue;
    const qty = Number(h.quantity || 0);
    const val = Number(h.value_rs || 0);
    if (qty <= 0 && val <= 0) continue;
    const key = normaliseSchemeKey(h.name);
    if (!key) continue;
    const tokens = key.split(/\s+/).filter(Boolean);
    if (tokens.length < 3 || key.length < 12 || _AMC_ONLY.has(key)) continue;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push({
      holding_id: h.holding_id, ticker: h.ticker, name: h.name,
      plan: _planOf(h.name), value: val,
    });
    totals.set(key, (totals.get(key) || 0) + val);
  }
  const clusters = [];
  let totalValue = 0;
  for (const [key, items] of groups.entries()) {
    if (items.length < 2) continue;
    const plans = new Set(items.map((it) => it.plan).filter(Boolean));
    if (!(plans.has("direct") && plans.has("regular"))) continue;
    const tickers = items.map((it) => (it.ticker || "").trim()).filter(Boolean);
    if (new Set(tickers).size < 2) continue;
    const cv = totals.get(key) || 0;
    clusters.push({ key, total_value: cv, items });
    totalValue += cv;
  }
  return { clusters, totalValue, count: clusters.length };
}

/**
 * Estimate annual fee leak from holding Regular plans where a Direct
 * equivalent exists in the portfolio. Uses each holding's `expense_ratio_pct`
 * (server-supplied) and the typical Direct vs Regular spread of ~0.7% if
 * the Direct counterpart's expense ratio isn't present.
 *
 * Returns { totalAnnualLeak, funds: [{name, value, leakPerYear}] }.
 */
export function selectRegularDirectSavings(holdings) {
  if (!Array.isArray(holdings) || holdings.length === 0) {
    return { totalAnnualLeak: 0, funds: [] };
  }
  const TYPICAL_SPREAD_PCT = 0.7;
  const funds = [];
  let totalAnnualLeak = 0;
  for (const h of holdings) {
    const at = (h.asset_type || "").toLowerCase();
    if (at !== "mutual_fund" && at !== "mutual fund") continue;
    if (_planOf(h.name) !== "regular") continue;
    const value = Number(h.value_rs || 0);
    if (value <= 0) continue;
    const er = Number(h.expense_ratio_pct ?? h.expense_ratio ?? 0);
    const directEr = Number(h.direct_expense_ratio_pct ?? 0);
    const spread = directEr > 0 && er > 0
      ? Math.max(0, er - directEr)
      : (er > 0 ? Math.min(er, TYPICAL_SPREAD_PCT) : TYPICAL_SPREAD_PCT);
    const leakPerYear = Math.round(value * (spread / 100));
    if (leakPerYear <= 0) continue;
    funds.push({ name: h.name, value, leakPerYear });
    totalAnnualLeak += leakPerYear;
  }
  funds.sort((a, b) => b.leakPerYear - a.leakPerYear);
  return { totalAnnualLeak, funds };
}

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
  const allHoldings = enriched.holdings;
  const mfHoldings = allHoldings.filter(
    (h) => h.asset_type === "mutual_fund" || h.asset_type === "mf"
  );
  const fundCount = mfHoldings.length;
  const amcCount = new Set(
    mfHoldings.map((h) => (h.name || "").split(" ")[0]).filter(Boolean)
  ).size;

  // Sort once for top-holdings + top-gainers/losers.
  const byValueDesc = allHoldings.slice().sort((a, b) => (b.value_rs || 0) - (a.value_rs || 0));
  const topHoldings = byValueDesc.slice(0, 5).map((h) => ({
    name: h.name,
    category: h.category || ASSET_LABEL[h.asset_type] || "—",
    value: h.value_rs || 0,
    return1y: h.pnl_pct || 0,
  }));

  const byReturnDesc = allHoldings
    .slice()
    .filter((h) => h.pnl_pct != null)
    .sort((a, b) => (b.pnl_pct || 0) - (a.pnl_pct || 0));
  const topGainers = byReturnDesc.slice(0, 5).map((h) => ({
    name: h.name, value: h.value_rs || 0, return1y: h.pnl_pct || 0,
  }));
  const topLosers = byReturnDesc.slice(-5).reverse().map((h) => ({
    name: h.name, value: h.value_rs || 0, return1y: h.pnl_pct || 0,
  }));

  // Pre-compute the V2-source duplicate + savings widgets so screens just
  // read p.funds.duplicateCount instead of recomputing each render.
  const dup = selectDuplicateClusters(allHoldings);
  const rds = selectRegularDirectSavings(allHoldings);

  // Pass the raw holdings through so Portfolio.jsx can render decision pills
  // on every row (action_badge is already on each holding from the backend).
  const holdings = allHoldings.map((h) => ({
    holding_id: h.holding_id,
    name: h.name,
    ticker: h.ticker,
    asset_type: h.asset_type,
    category: h.category || ASSET_LABEL[h.asset_type] || "—",
    value: h.value_rs || 0,
    invested: h.invested_rs || 0,
    quantity: h.quantity,
    return1y: h.pnl_pct ?? null,
    action_badge: h.action_badge || null,
  }));

  return {
    funds: {
      count: fundCount,
      amcCount: amcCount,
      idealMin: 5,
      idealMax: 7,
      duplicateCount: dup.count,
      duplicateValue: dup.totalValue,
      duplicateClusters: dup.clusters,
      regularDirectAnnualLeak: rds.totalAnnualLeak,
      regularDirectFunds: rds.funds,
    },
    topHoldings: topHoldings.length ? topHoldings : [],
    holdings,
    topGainers,
    topLosers,
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

/**
 * Portfolio value trend + benchmark series for sparkline-style charts.
 * Hits the existing endpoints:
 *   GET /api/portfolio/trend?days=30  → [{snapshot_date, total_value}]
 *   GET /api/index/history?name=NIFTY_50&period=1M → benchmark close series
 *
 * Returns SVG-ready alternating x/y arrays normalised to a 0–32 range
 * (viewBox-friendly for the existing PerformanceLine renderer):
 *   { points: [x0,y0,x1,y1,...], benchmark: [x0,y0,...], hasData }
 */
export function usePortfolioTrend(days = 30) {
  return useAsync(
    async () => {
      const [trend, bench] = await Promise.all([
        apiGet("/portfolio/trend", { days }),
        apiGet("/index/history", { name: "NIFTY_50", period: "1M" }),
      ]);
      const portfolioSeries = (trend.data || [])
        .map((d) => Number(d.total_value || 0))
        .filter((v) => v > 0);
      const benchSeries = ((bench.data?.rows) || [])
        .map((r) => Number(r.close ?? r.value ?? 0))
        .filter((v) => v > 0);

      const points = toAlternatingXY(portfolioSeries);
      const benchmark = toAlternatingXY(benchSeries);
      return {
        data: {
          points,
          benchmark,
          hasData: portfolioSeries.length >= 2,
        },
        error: trend.error,
      };
    },
    [days],
    { initialData: { points: [], benchmark: [], hasData: false } },
  );
}

// Convert a 1-D series into the alternating [x0,y0,x1,y1,...] format that
// `PerformanceLine` already expects, normalised to the 36×36 viewBox.
function toAlternatingXY(series) {
  if (!series || series.length < 2) return [];
  const min = Math.min(...series);
  const max = Math.max(...series);
  const span = max - min || 1;
  const xStep = 36 / Math.max(1, series.length - 1);
  const out = [];
  series.forEach((v, i) => {
    const x = Math.round(i * xStep * 100) / 100;
    const yNorm = (v - min) / span;
    const y = Math.round((32 - yNorm * 30) * 100) / 100;
    out.push(x, y);
  });
  return out;
}
