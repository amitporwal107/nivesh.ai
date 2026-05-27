/**
 * Portfolio mapper — wire Holding → domain Holding.
 *
 * Critical correction: `asset_type` is lowercase (equity, mutual_fund, etf, …)
 * not uppercase. Updated category mapping accordingly.
 */
import type { Holding as DomainHolding, FundSummary, FundReturns } from "@/types/fund";
import type { HoldingC } from "@/services/contracts/portfolio.contract";

export function mapHolding(c: HoldingC): DomainHolding {
  const units = c.quantity;
  const costBasis = c.quantity * c.buy_price * 100;          // paise
  const marketValue = c.quantity * c.current_price * 100;
  const unrealizedPnl = marketValue - costBasis;
  const unrealizedPnlPct = costBasis === 0 ? 0 : unrealizedPnl / costBasis;

  const fund: FundSummary = {
    id: c.holding_id,
    isin: "",
    amfiCode: "",
    name: c.name,
    amc: c.ticker ?? "",
    category: assetTypeToCategory(c.asset_type),
    expenseRatio: 0,
    navAsOf: c.buy_date ?? new Date().toISOString().slice(0, 10),
    nav: Math.round(c.current_price * 100),
    riskometer: 3,
  };

  const returns: FundReturns = { m1: 0, m3: 0, m6: 0, y1: 0, y3: 0, y5: 0, cagr: 0 };

  return {
    id: c.holding_id,
    fundId: c.holding_id,
    units,
    costBasis,
    marketValue,
    unrealizedPnl,
    unrealizedPnlPct,
    startedOn: c.buy_date ?? "1970-01-01",
    fund,
    returns,
  };
}

export function mapHoldings(list: HoldingC[]): DomainHolding[] {
  return list.map(mapHolding);
}

/** Lowercase enum mapping per portfolio.yaml v2.0.0. */
function assetTypeToCategory(asset: string): FundSummary["category"] {
  switch (asset) {
    case "mutual_fund": return "flexi-cap";
    case "etf":         return "large-cap";
    case "equity":      return "large-cap";
    case "bond":        return "debt";
    case "gold":        return "gold-etf";
    case "fd":          return "debt";
    case "other":       return "flexi-cap";
    default:            return "flexi-cap";
  }
}
