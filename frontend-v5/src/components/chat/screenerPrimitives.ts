// Single source of truth for the stock-screener primitive catalog, shared by
// the composer autocomplete (Chat/index.tsx) and the visual Query Builder
// (ScreenerQueryBuilder.tsx). Every `qlabel` is a phrase the backend NL parser
// (_parse_screen_filters) recognises, and every `key` maps to a real column on
// nidp.stock_features_daily — so anything built here screens cleanly.
export type ScreenPrimitive = {
  key: string;
  label: string;
  cat: string;
  hint: string;
  tag: string;            // unit shown in the chip (%, ×, β, 0–100, ₹Cr…)
  qlabel: string;         // parser-safe phrase used in the compiled query
  op: "over" | "under";   // natural default direction
  bucket?: boolean;       // market-cap bucket (no numeric value — just the phrase)
};

export const SCREEN_PRIMITIVES: ScreenPrimitive[] = [
  // Valuation
  { key: "pe",         label: "P/E ratio",        cat: "Valuation", hint: "price ÷ earnings", tag: "×",   qlabel: "P/E",            op: "under" },
  { key: "pb",         label: "P/B ratio",        cat: "Valuation", hint: "price ÷ book",     tag: "×",   qlabel: "P/B",            op: "under" },
  { key: "evEbitda",   label: "EV / EBITDA",      cat: "Valuation", hint: "enterprise value", tag: "×",   qlabel: "EV/EBITDA",      op: "under" },
  { key: "peVsSector", label: "P/E vs sector",    cat: "Valuation", hint: "rel. cheapness",   tag: "%",   qlabel: "P/E vs sector",  op: "under" },
  { key: "divYield",   label: "Dividend Yield",   cat: "Valuation", hint: "trailing payout",  tag: "%",   qlabel: "dividend yield", op: "over" },
  // Profitability
  { key: "roe",        label: "ROE",              cat: "Profitability", hint: "return on equity", tag: "%",     qlabel: "ROE",                  op: "over" },
  { key: "roce",       label: "ROCE",             cat: "Profitability", hint: "return on capital",tag: "%",     qlabel: "ROCE",                 op: "over" },
  { key: "profitMargin", label: "Net margin",     cat: "Profitability", hint: "PAT ÷ sales",      tag: "%",     qlabel: "net margin",           op: "over" },
  { key: "interestCoverage", label: "Interest cover", cat: "Profitability", hint: "EBIT ÷ interest", tag: "×",  qlabel: "interest cover",       op: "over" },
  { key: "earningsConsistency", label: "Earnings consistency", cat: "Profitability", hint: "stability score", tag: "0–100", qlabel: "earnings consistency", op: "over" },
  // Growth
  { key: "salesG",     label: "Sales growth 3Y",  cat: "Growth", hint: "revenue 3Y CAGR", tag: "%", qlabel: "sales growth",      op: "over" },
  { key: "profitG",    label: "Profit growth 3Y", cat: "Growth", hint: "earnings 3Y CAGR",tag: "%", qlabel: "profit growth",     op: "over" },
  { key: "salesGyoy",  label: "Sales growth YoY", cat: "Growth", hint: "latest year",     tag: "%", qlabel: "sales growth YoY",  op: "over" },
  { key: "profitGyoy", label: "Profit growth YoY",cat: "Growth", hint: "latest year",     tag: "%", qlabel: "profit growth YoY", op: "over" },
  { key: "epsGyoy",    label: "EPS growth YoY",   cat: "Growth", hint: "latest year",     tag: "%", qlabel: "EPS growth YoY",    op: "over" },
  { key: "marginTrend",label: "Margin trend",     cat: "Growth", hint: "Δ profit margin", tag: "pp",qlabel: "margin trend",      op: "over" },
  // Financial health
  { key: "de",         label: "Debt to Equity",   cat: "Financial health", hint: "leverage",      tag: "×",     qlabel: "debt to equity", op: "under" },
  { key: "debtTrend",  label: "Debt trend",       cat: "Financial health", hint: "Δ debt",        tag: "%",     qlabel: "debt trend",     op: "under" },
  { key: "liquidity",  label: "Liquidity score",  cat: "Financial health", hint: "tradeability",  tag: "0–100", qlabel: "liquidity",      op: "over" },
  // Size
  { key: "mcap",       label: "Market Cap",       cat: "Size", hint: "₹ crore",   tag: "₹Cr",  qlabel: "market cap", op: "over" },
  { key: "large",      label: "Large cap",        cat: "Size", hint: "cap bucket",tag: "size", qlabel: "large cap",  op: "over", bucket: true },
  { key: "mid",        label: "Mid cap",          cat: "Size", hint: "cap bucket",tag: "size", qlabel: "mid cap",    op: "over", bucket: true },
  { key: "small",      label: "Small cap",        cat: "Size", hint: "cap bucket",tag: "size", qlabel: "small cap",  op: "over", bucket: true },
  // Price / technical
  { key: "return1y",   label: "1Y return",        cat: "Price / technical", hint: "252-day price", tag: "%",     qlabel: "1 year return", op: "over" },
  { key: "volatility", label: "Volatility 1Y",    cat: "Price / technical", hint: "annualised σ",  tag: "%",     qlabel: "volatility",    op: "under" },
  { key: "beta",       label: "Beta",             cat: "Price / technical", hint: "vs Nifty",      tag: "β",     qlabel: "beta",          op: "under" },
  { key: "maxDrawdown",label: "Max drawdown 1Y",  cat: "Price / technical", hint: "peak-to-trough",tag: "%",     qlabel: "max drawdown",  op: "over" },
  { key: "rsi",        label: "RSI (14)",         cat: "Price / technical", hint: "momentum gauge",tag: "0–100", qlabel: "RSI",           op: "under" },
  { key: "momentum",   label: "Momentum score",   cat: "Price / technical", hint: "trend strength",tag: "0–100", qlabel: "momentum",      op: "over" },
  { key: "accumulation", label: "Accumulation",   cat: "Price / technical", hint: "buying pressure",tag: "0–100",qlabel: "accumulation",  op: "over" },
  // Ownership / smart money
  { key: "promoter",      label: "Promoter holding", cat: "Ownership", hint: "skin in the game", tag: "%", qlabel: "promoter holding", op: "over" },
  { key: "promoterPledge",label: "Promoter pledge",  cat: "Ownership", hint: "lower is safer",   tag: "%", qlabel: "promoter pledge",  op: "under" },
  { key: "fii",           label: "FII holding",      cat: "Ownership", hint: "foreign inst.",    tag: "%", qlabel: "FII holding",      op: "over" },
  { key: "dii",           label: "DII holding",      cat: "Ownership", hint: "domestic inst.",   tag: "%", qlabel: "DII holding",      op: "over" },
  { key: "fiiChange",     label: "FII change QoQ",   cat: "Ownership", hint: "Δ vs last qtr",    tag: "pp",qlabel: "FII change",       op: "over" },
  { key: "promoterChange",label: "Promoter change",  cat: "Ownership", hint: "Δ vs last qtr",    tag: "pp",qlabel: "promoter change",  op: "over" },
];

export const PRIMITIVE_BY_KEY: Record<string, ScreenPrimitive> =
  Object.fromEntries(SCREEN_PRIMITIVES.map((p) => [p.key, p]));

// Classic screen templates surfaced as one-click starting points in the Query
// Builder. These MIRROR the backend `_SCREENER_PRESETS` (stock_intelligence.py)
// in structured form — keep the two in sync. Every `key` here is a real
// primitive above, so a loaded template compiles to a query the parser accepts.
// Where a textbook screen references a metric NIDP does not carry, the clause is
// adapted to the nearest available primitive (OPM→net margin, "P/E<Industry PE"→
// P/E vs sector < 0, earnings-yield>10→P/E<10, "pledged=0"→pledge<1, 5Y→3Y growth,
// promoter 3Y change→QoQ change). Screens whose defining metric is absent
// (current ratio, PEG, dividend payout, FCF, CFO) are intentionally omitted.
export type ScreenTemplate = {
  name: string;
  hint: string;
  bucket?: string;
  conds: { key: string; op: "over" | "under"; value: string }[];
};

export const SCREEN_TEMPLATES: ScreenTemplate[] = [
  { name: "Quality compounders", hint: "High ROCE + durable growth, low leverage", conds: [
    { key: "roce", op: "over", value: "20" },
    { key: "roe", op: "over", value: "18" },
    { key: "salesG", op: "over", value: "12" },
    { key: "profitG", op: "over", value: "12" },
    { key: "de", op: "under", value: "0.5" },
  ] },
  { name: "Low-debt, high-margin", hint: "Strong margins with little debt and high interest cover", conds: [
    { key: "de", op: "under", value: "0.3" },
    { key: "profitMargin", op: "over", value: "18" },
    { key: "roe", op: "over", value: "18" },
    { key: "interestCoverage", op: "over", value: "5" },
  ] },
  { name: "Value (Graham-style)", hint: "Cheap on earnings & book, modest leverage", conds: [
    { key: "pe", op: "under", value: "15" },
    { key: "pb", op: "under", value: "1.5" },
    { key: "de", op: "under", value: "1" },
    { key: "mcap", op: "over", value: "500" },
  ] },
  { name: "GARP", hint: "Growth at a reasonable price — cheaper than sector", conds: [
    { key: "profitG", op: "over", value: "15" },
    { key: "roe", op: "over", value: "15" },
    { key: "peVsSector", op: "under", value: "0" },
  ] },
  { name: "High dividend yield", hint: "Income with positive earnings and low debt", conds: [
    { key: "divYield", op: "over", value: "3" },
    { key: "profitG", op: "over", value: "0" },
    { key: "de", op: "under", value: "0.6" },
  ] },
  { name: "Promoter conviction", hint: "High promoter holding, unpledged, rising stake", conds: [
    { key: "promoter", op: "over", value: "50" },
    { key: "promoterPledge", op: "under", value: "1" },
    { key: "promoterChange", op: "over", value: "0" },
  ] },
  { name: "Turnaround / momentum", hint: "Accelerating sales & profit with improving margins", conds: [
    { key: "profitGyoy", op: "over", value: "50" },
    { key: "salesGyoy", op: "over", value: "25" },
    { key: "marginTrend", op: "over", value: "0" },
    { key: "mcap", op: "over", value: "300" },
  ] },
  { name: "Smallcap multibagger", hint: "Small but fast-growing, profitable, unpledged", conds: [
    { key: "mcap", op: "over", value: "100" },
    { key: "mcap", op: "under", value: "2000" },
    { key: "salesG", op: "over", value: "20" },
    { key: "profitG", op: "over", value: "20" },
    { key: "roe", op: "over", value: "18" },
    { key: "promoterPledge", op: "under", value: "1" },
  ] },
  { name: "Magic Formula", hint: "Greenblatt-style: high ROCE + high earnings yield", conds: [
    { key: "roce", op: "over", value: "25" },
    { key: "pe", op: "under", value: "10" },
    { key: "mcap", op: "over", value: "500" },
  ] },
];

/** Catalog grouped by category, preserving declaration order. */
export const PRIMITIVE_GROUPS: { cat: string; items: ScreenPrimitive[] }[] = (() => {
  const out: { cat: string; items: ScreenPrimitive[] }[] = [];
  for (const p of SCREEN_PRIMITIVES) {
    const g = out.find((x) => x.cat === p.cat);
    if (g) g.items.push(p);
    else out.push({ cat: p.cat, items: [p] });
  }
  return out;
})();

/** Clause inserted by composer autocomplete ("ROE over " / "large cap "). */
export const screenInsert = (p: ScreenPrimitive): string =>
  p.bucket ? `${p.qlabel} ` : `${p.qlabel} ${p.op} `;

export type BuilderCondition = { id: number; key: string; op: "over" | "under"; value: string };

/** Compile builder conditions + an optional cap bucket into the natural-language
 *  query the backend parser consumes. Empty if nothing actionable was set. */
export function compileScreenQuery(conds: BuilderCondition[], bucketKey?: string): string {
  const parts = conds
    .filter((c) => c.value.trim() !== "" && PRIMITIVE_BY_KEY[c.key] && !PRIMITIVE_BY_KEY[c.key].bucket)
    .map((c) => `${PRIMITIVE_BY_KEY[c.key].qlabel} ${c.op} ${c.value.trim()}`);
  const bucket = bucketKey ? PRIMITIVE_BY_KEY[bucketKey]?.qlabel : "";
  if (bucket && parts.length) return `Screen ${bucket} stocks where ${parts.join(", ")}`;
  if (bucket) return `Screen ${bucket} stocks`;
  if (parts.length) return `Screen stocks where ${parts.join(", ")}`;
  return "";
}
