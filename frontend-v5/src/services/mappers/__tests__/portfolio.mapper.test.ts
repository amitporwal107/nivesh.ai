/**
 * Hand-rolled mapper test scaffold — runnable under Vitest later.
 *
 * No test framework installed yet; this file uses simple `assert`-style
 * calls so it can be turned into a Vitest suite by changing one import.
 * Run manually with `npx tsx production/src/services/mappers/__tests__/portfolio.mapper.test.ts`
 * once tsx is installed.
 */
import { mapHolding } from "../portfolio.mapper";

function assertEq(actual: unknown, expected: unknown, label: string): void {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (!ok) {
    throw new Error(`[FAIL] ${label}\n  expected: ${JSON.stringify(expected)}\n  actual:   ${JSON.stringify(actual)}`);
  }
  // eslint-disable-next-line no-console
  console.log(`[ok] ${label}`);
}

const wire = {
  holding_id: "h-1",
  portfolio_id: "p-1",
  name: "Parag Parikh Flexi Cap",
  ticker: null,
  asset_type: "MUTUAL_FUND",
  quantity: 100,
  buy_price: 50,            // ₹50 per unit
  current_price: 75,        // ₹75 per unit
  sector: null,
  buy_date: "2020-03-10",
};

const out = mapHolding(wire);

// Money: 100 × ₹50 = ₹5,000 = 500,000 paise
assertEq(out.costBasis, 500_000, "costBasis is paise-precise");
// 100 × ₹75 = ₹7,500 = 750,000 paise
assertEq(out.marketValue, 750_000, "marketValue is paise-precise");
// PnL = 250,000 paise = ₹2,500 → +50% gain
assertEq(out.unrealizedPnl, 250_000, "unrealizedPnl computed");
assertEq(out.unrealizedPnlPct, 0.5, "unrealizedPnlPct = 0.5 (= 50%)");
assertEq(out.units, 100, "units passes through");
assertEq(out.fund.category, "flexi-cap", "MUTUAL_FUND → flexi-cap category");

// Edge case — zero cost basis must not NaN
const zeroCost = mapHolding({ ...wire, buy_price: 0 });
assertEq(zeroCost.unrealizedPnlPct, 0, "zero cost basis → pct 0 (no NaN)");

// eslint-disable-next-line no-console
console.log("\nportfolio mapper: all assertions passed");
