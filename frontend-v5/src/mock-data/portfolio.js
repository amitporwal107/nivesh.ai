/**
 * Realistic-feel mock for a salaried Indian investor.
 * Amounts in paise; the UI formats to ₹.
 */
export const mockPortfolio = {
    asOf: "2026-05-27T09:41:00+05:30",
    totalValue: 248_24_000_00, // ₹24,82,400
    dayChange: { abs: 6_400_00, pct: 0.026 },
    weekChange: { abs: 14_200_00, pct: 0.057 },
    yearChange: { abs: 391_50_000_00, pct: 0.187 },
    healthScore: 74,
    riskBucket: "moderate",
    riskBucketIndex: 3,
    allocation: [
        { assetClass: "equity", label: "Equity", pct: 68, value: 168_80_300_00 },
        { assetClass: "debt", label: "Debt", pct: 18, value: 44_68_300_00 },
        { assetClass: "gold", label: "Gold", pct: 6, value: 14_89_400_00 },
        { assetClass: "international", label: "International", pct: 6, value: 14_89_400_00 },
        { assetClass: "cash", label: "Cash", pct: 2, value: 4_96_500_00 },
    ],
    topInsights: [
        {
            id: "ins-overlap-large-cap",
            severity: "fix",
            category: "overlap",
            title: "You own 5 funds with similar holdings.",
            detail: "Axis Bluechip, ICICI Pru Bluechip and Mirae Large hold 71% of the same top stocks — you're paying 3× the fees for 1× exposure.",
            evidence: [
                { label: "Avg overlap", value: "71%" },
                { label: "Excess fees", value: "₹14,200 / yr" },
            ],
            cta: { label: "See the switch", recommendationId: "rec-switch-axis-bluechip" },
        },
        {
            id: "ins-midcap-tilt",
            severity: "watch",
            category: "concentration",
            title: "Your portfolio is tilted toward mid-caps.",
            detail: "About 38% sits in mid- and small-cap names. Fine in good years, painful in bad ones.",
            evidence: [
                { label: "Mid + small", value: "38%" },
                { label: "Suggested", value: "≤ 25%" },
            ],
            cta: { label: "Rebalance plan", recommendationId: "rec-rebalance-midcap" },
        },
        {
            id: "ins-emergency-low",
            severity: "watch",
            category: "balance",
            title: "Your emergency fund looks low.",
            detail: "You hold 1.4 months of expenses in safe cash. The usual target is 6 months — about ₹4.6L more.",
            evidence: [
                { label: "Months covered", value: "1.4" },
                { label: "Target", value: "6.0" },
            ],
            cta: { label: "Top-up plan", recommendationId: "rec-emergency-topup" },
        },
    ],
};
/** Daily portfolio NAV history — 24 months, monthly resolution to keep payload small. */
export const mockNavHistory = (() => {
    const start = 209_50_000_00;
    const end = 248_24_000_00;
    const months = 24;
    // sinusoidal drift on a positive trend
    return Array.from({ length: months }, (_, i) => {
        const t = i / (months - 1);
        const trend = start + (end - start) * t;
        const wave = Math.sin(t * Math.PI * 3) * 2_60_000_00 * (1 - t * 0.4);
        const d = new Date(2024, 5 + i, 1);
        return {
            date: d.toISOString().slice(0, 10),
            value: Math.round(trend + wave),
        };
    });
})();
