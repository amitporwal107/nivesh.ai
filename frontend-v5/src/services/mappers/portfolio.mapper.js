export function mapHolding(c) {
    const units = c.quantity;
    const costBasis = c.quantity * c.buy_price * 100; // paise
    const marketValue = c.quantity * c.current_price * 100;
    const unrealizedPnl = marketValue - costBasis;
    const unrealizedPnlPct = costBasis === 0 ? 0 : unrealizedPnl / costBasis;
    const fund = {
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
    const returns = { m1: 0, m3: 0, m6: 0, y1: 0, y3: 0, y5: 0, cagr: 0 };
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
export function mapHoldings(list) {
    return list.map(mapHolding);
}
/** Lowercase enum mapping per portfolio.yaml v2.0.0. */
function assetTypeToCategory(asset) {
    switch (asset) {
        case "mutual_fund": return "flexi-cap";
        case "etf": return "large-cap";
        case "equity": return "large-cap";
        case "bond": return "debt";
        case "gold": return "gold-etf";
        case "fd": return "debt";
        case "other": return "flexi-cap";
        default: return "flexi-cap";
    }
}
