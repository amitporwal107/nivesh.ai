/**
 * One-screen Copilot app — Smart trading desk: the Strategy Builder's interactive graphs (PRD §16.6 A to D;
 * screens/tradingdesk/strategy/: PayoffChart, ScenarioControls, LegTable, PayoffSummary, ScenarioFan,
 * StrategyGraphs, usePayoff, strategy-contract).
 *
 * MOCK — not real data. Every /api response here is generated in this file. POST /api/desk/strategy/payoff is
 * answered by `refPayoff`, an independent reference implementation written for this spec from the route's documented
 * model (backend/services/strategy_plan: gross extremes over 0 … infinity, per-leg exit costs, capital at risk as the
 * worst net loss, pre_expiry null unless requested, scalar Greeks, margin always null with margin_reason). It shares no
 * code with the app. The headline figures (max profit and loss, breakevens, the P&L at chosen prices, net with costs,
 * capital at risk) are HAND-COMPUTED constants written beside each fixture and asserted against both the generated
 * answer and the screen. Faithfulness: `plotsFaithfully` fits the drawn line to the answer's numbers and fails if
 * any plotted point is off by more than a few rupees.
 *
 * The graphs are reached through the test-only route ?tab=more&view=strategy-graphs, which exists only in a
 * build with VITE_STRATEGY_HARNESS=1 (fe-run-stgraph.sh sets it) and reads window.__STRATEGY_FIXTURE__.
 *
 * Cases: SG-1 bull call spread (+ the engine's nine-point example) · SG-2 long future · SG-3 short future · SG-4 long put (costs, net/gross), cash ·
 * SG-5 iron condor (per-leg lines) · SG-6 pre-expiry toggle · SG-7 scenario controls · SG-8 failures ·
 * SG-9 unavailable legs · SG-10 the fan · SG-11 persona wording · SG-12 phone, role="img" summaries.
 */
import { test, expect, type Page } from "@playwright/test";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const URL = "/v5/app/trader/desk?tab=more&view=strategy-graphs";
const PAYOFF = "**/api/desk/strategy/payoff";
const MINUS = "−";

// ── types of the request this spec reads ─────────────────────────────────

interface Leg {
  kind: "cash" | "future" | "option"; side: "buy" | "sell"; quantity: number; lot_size: number; entry_price: number;
  expiry: string | null; strike: number | null; option_type: "call" | "put" | null; price_source: string; iv_pct: number | null;
}
interface Req {
  underlying: string; reference_price: number; as_of?: string; legs: Leg[]; grid?: { min: number; max: number; points: number };
  costs: { slippage_pct: number; brokerage_per_side: number }; scenarios?: Array<{ name: string; underlying_price: number }>;
  pre_expiry?: { date: string; iv_shift_pct?: number; rate_pct?: number };
}
/** How the mocked route treats a pre_expiry request: "ok" an estimate, "unavailable" a block with null series and reasons, "expiryday" an estimate with null Greeks. */
type PreMode = "ok" | "unavailable" | "expiryday";
interface Fixture { base: Req; dataDate: string; pre?: PreMode; unavailable?: Array<{ leg: number; reason: string }>; fan?: unknown; markers?: unknown }

// ── the independent reference payoff (the route's documented model, written again here) ──
// Per-leg gross at S: cash and future sign × (S − entry) × units; call sign × (max(S − K, 0) − premium) × units; put likewise.
// Costs, each side, each leg: slippage% × traded value + flat brokerage; entry at the entry price, exit at S (cash, future) or
// the intrinsic value (option); an option worth nothing at expiry has no exit cost. Net = gross − costs.
// max_profit / max_loss are gross and exact over prices 0 … ∞ (null when the end slope makes them unbounded); capital at risk
// is the worst NET loss at 0, every strike and the grid top, every leg charged both sides even if worthless; breakevens are gross.

const r2 = (n: number) => Math.round(n * 100) / 100;
const units = (l: Leg) => l.quantity * (l.kind === "cash" ? 1 : l.lot_size);
const sign = (l: Leg) => (l.side === "buy" ? 1 : -1);
const intrinsic = (l: Leg, s: number) => (l.option_type === "call" ? Math.max(s - (l.strike as number), 0) : Math.max((l.strike as number) - s, 0));

function legAt(l: Leg, s: number): number {
  return l.kind === "option" ? sign(l) * (intrinsic(l, s) - l.entry_price) * units(l) : sign(l) * (s - l.entry_price) * units(l);
}
const grossAt = (req: Req, s: number) => req.legs.reduce((a, l) => a + legAt(l, s), 0);
const entryCost = (l: Leg, c: Req["costs"]) => (c.slippage_pct / 100) * l.entry_price * units(l) + c.brokerage_per_side;
function exitCost(l: Leg, s: number, c: Req["costs"], worthlessCharged = false): number {
  const v = l.kind === "option" ? intrinsic(l, s) : s;
  return v <= 0 && !worthlessCharged ? 0 : (c.slippage_pct / 100) * Math.max(v, 0) * units(l) + c.brokerage_per_side;
}
const costAt = (req: Req, s: number, worthless = false) => req.legs.reduce((a, l) => a + entryCost(l, req.costs) + exitCost(l, s, req.costs, worthless), 0);

/** Slope of the gross payoff beyond the highest strike: Σ sign × units over cash and futures, and over calls. */
function tailSlope(req: Req): number {
  return req.legs.reduce((a, l) => a + (l.kind === "put" || (l.kind === "option" && l.option_type === "put") ? 0 : sign(l) * units(l)), 0);
}

function refPayoff(req: Req, fx: Fixture) {
  const g = req.grid as { min: number; max: number; points: number };
  const grid = Array.from({ length: g.points }, (_, i) => g.min + ((g.max - g.min) * i) / (g.points - 1));
  const strikes = [...new Set(req.legs.filter((l) => l.kind === "option").map((l) => l.strike as number))].sort((a, b) => a - b);
  const gross = grid.map((s) => r2(grossAt(req, s)));
  const net = grid.map((s) => r2(grossAt(req, s) - costAt(req, s)));
  // Breakevens inside the grid: zero crossings of the gross payoff on the grid plus the strikes in range (linear in between).
  const nodes = [...new Set([...grid, ...strikes.filter((k) => k > g.min && k < g.max)])].sort((a, b) => a - b);
  const breakevens: number[] = [];
  nodes.forEach((x, i) => {
    const y = grossAt(req, x);
    if (Math.abs(y) < 1e-7) breakevens.push(x);
    else if (i > 0) {
      const x0 = nodes[i - 1], y0 = grossAt(req, x0);
      if (Math.abs(y0) >= 1e-7 && y0 * y < 0) breakevens.push(x0 + ((x - x0) * -y0) / (y - y0));
    }
  });
  const cand = [0, ...strikes, Math.max(...strikes, g.max)];
  const up = tailSlope(req);
  const vals = cand.map((s) => grossAt(req, s));
  const worstNet = Math.min(...cand.map((s) => grossAt(req, s) - costAt(req, s, true)));
  const scenarios = (req.scenarios ?? []).map((s) => ({
    name: s.name, underlying_price: s.underlying_price, gross: r2(grossAt(req, s.underlying_price)), net: r2(grossAt(req, s.underlying_price) - costAt(req, s.underlying_price)),
  }));
  const label = (l: Leg) => {
    const verb = l.side === "buy" ? "Buy" : "Sell";
    if (l.kind === "cash") return `${verb} ${l.quantity} shares`;
    const lots = `${l.quantity} lot${l.quantity === 1 ? "" : "s"}`;
    return l.kind === "future" ? `${verb} ${lots} future` : `${verb} ${lots} ${l.option_type} ${l.strike}`;
  };
  const eT = req.legs.reduce((a, l) => a + entryCost(l, req.costs), 0);
  const xT = req.legs.reduce((a, l) => a + exitCost(l, req.reference_price, req.costs), 0);
  const hasFuture = req.legs.some((l) => l.kind === "future");
  const body: Record<string, unknown> = {
    valid: true, problems: [], warnings: [], calculation_version: "payoff-v1 (MOCK)",
    underlying: req.underlying, reference_price: req.reference_price, as_of: req.as_of,
    expiry: {
      grid: grid.map(r2), gross, net,
      per_leg: req.legs.map((l, i) => ({ index: i, label: label(l), gross: grid.map((s) => r2(legAt(l, s))) })),
      breakevens: breakevens.map(r2),
      max_profit: up > 0 ? null : r2(Math.max(...vals)), max_loss: up < 0 ? null : r2(Math.min(...vals)),
      profit_unbounded: up > 0, loss_unbounded: up < 0,
      range_max_profit: Math.max(...gross), range_max_loss: Math.min(...gross),
      net_premium: r2(req.legs.filter((l) => l.kind === "option").reduce((a, l) => a - sign(l) * l.entry_price * units(l), 0)), scenarios,
      extremes_basis: "gross, all prices from 0 to infinity (MOCK)",
    },
    pre_expiry: null,
    costs: {
      model: "slippage % of traded value + flat brokerage, each side, each leg (MOCK)", entry: r2(eT), exit_at_expiry: r2(xT), round_trip: r2(eT + xT),
      exit_basis: "expiry settlement with the underlying at reference_price (MOCK)",
      per_leg: req.legs.map((l, i) => ({ index: i, entry: r2(entryCost(l, req.costs)), exit_at_expiry: r2(exitCost(l, req.reference_price, req.costs)), round_trip: r2(entryCost(l, req.costs) + exitCost(l, req.reference_price, req.costs)) })),
      excluded: ["taxes", "STT", "exchange and statutory charges", "dividends", "funding"],
    },
    margin: null, margin_reason: "This payoff calculation does not estimate margin. The margin for a structure comes only from Zerodha's margin calculator (MOCK reason).",
    capital_at_risk: up < 0 ? null : r2(-Math.min(worstNet, 0)), capital_at_risk_basis: "worst net loss over all prices (MOCK)",
    loss_can_exceed_margin: hasFuture,
    caveats: ["Margin is not the maximum loss.", ...(hasFuture ? ["Futures losses can exceed the initial margin (MOCK caveat)."] : [])],
    sent_to_broker: false,
  };
  if (fx.pre && req.pre_expiry) {
    const assumptions = {
      model: "Black-76", rate_pct: 5.75, rate_source: "request rate_pct (MOCK)", forward_basis: "carried spot: S x exp(r T) (MOCK)",
      iv_shift_pct: req.pre_expiry.iv_shift_pct ?? 0, as_of: req.as_of,
      legs: req.legs.map((l, i) => ({ leg: i, l })).filter((x) => x.l.kind === "option").map((x) => ({ leg: x.leg, time_to_expiry_days: 4, iv_pct: 25, iv_source: "request iv_pct (MOCK)" })),
    };
    if (fx.pre === "unavailable") {
      body.pre_expiry = { date: req.pre_expiry.date, model: "Black-76", assumptions, grid: null, gross: null, net: null, greeks: null, per_leg_greeks: [], unavailable: fx.unavailable ?? [] };
    } else {
      // MOCK — a made-up estimate line: the spec only checks that the screen plots these numbers.
      const est = (s: number) => r2((s - req.reference_price) * 20);
      body.pre_expiry = {
        date: req.pre_expiry.date, model: "Black-76", assumptions, grid: grid.map(r2), gross: grid.map(est), net: grid.map((s) => r2(est(s) - 40)),
        greeks: fx.pre === "expiryday" ? null : { delta: 52.1, gamma: 0.1234, theta: -12.5, vega: 33.3, rho: null },
        per_leg_greeks: [], unavailable: [],
      };
    }
  }
  return body;
}

// ── the fixtures (hand-computed figures beside each) ─────────────────────

const leg = (over: Partial<Leg>): Leg => ({
  kind: "option", side: "buy", quantity: 1, lot_size: 250, entry_price: 0, expiry: "2026-10-27", strike: null, option_type: null,
  price_source: "MOCK — not real data: NSE F&O bhavcopy close, 2026-10-19", iv_pct: null, ...over,
});
const GRID = { min: 1100, max: 1500, points: 41 }; // step 10
const COSTS = { slippage_pct: 0.05, brokerage_per_side: 20 };
const base = (legs: Leg[], over: Partial<Req> = {}): Req => ({ underlying: "RELIANCE", reference_price: 1215, as_of: "2026-10-19", grid: GRID, costs: COSTS, legs, ...over });

/**
 * Bull call spread (the engine's worked example): buy 1300 call at 40, sell 1350 call at 18, 1 lot of 250; costs 0.05% + ₹20 a side.
 * Net debit 22 × 250 = 5,500 · gross max loss −5,500 (S ≤ 1300) · gross max profit (50 − 22) × 250 = 7,000 (S ≥ 1350) · breakeven 1300 + 22 = 1322.
 * Gross: 1100 → −5,500 · 1330 → (30 − 40 + 18) × 250 = 2,000 · 1350 → 7,000 · 1500 → 7,000.
 * Entry costs: 40 × 250 × .0005 + 20 = 25 and 18 × 250 × .0005 + 20 = 22.25 → 47.25.
 * Net: 1100 → −5,500 − 47.25 = −5,547.25 (both options expire worthless: no exit cost) · 1330 → exit of the long call 30 × 250 × .0005 + 20 = 23.75 → 2,000 − 47.25 − 23.75 = 1,929.00
 *      · 1500 → exits 200 × 250 × .0005 + 20 = 45 and 150 × 250 × .0005 + 20 = 38.75 → 7,000 − 47.25 − 83.75 = 6,869.00.
 * Capital at risk (worst net loss, worthless exits charged): −5,500 − 47.25 − 40 = −5,587.25. At the reference price 1215 both are worthless: exit 0.
 */
const BCS: Fixture = {
  base: base([leg({ entry_price: 40, strike: 1300, option_type: "call" }), leg({ side: "sell", entry_price: 18, strike: 1350, option_type: "call" })]),
  dataDate: "2026-10-19",
};

/**
 * Long future: 1 lot of 250 at 1215, costs 0.1% and no brokerage (the engine's example). Gross: 1100 → −115 × 250 = −28,750 · 1300 → 85 × 250 = 21,250 · breakeven 1215.
 * Net at 1250: 8,750 − 303.75 (entry 303,750 × .001) − 312.5 (exit 312,500 × .001) = 8,133.75 · net at 1100: −28,750 − 303.75 − 275 = −29,328.75.
 * Gross max loss at S = 0: −1215 × 250 = −303,750 (loss not unbounded); capital at risk 303,750 + 303.75 = 304,053.75; profit unbounded.
 */
const LONG_FUT: Fixture = {
  base: base([leg({ kind: "future", entry_price: 1215 })], { costs: { slippage_pct: 0.1, brokerage_per_side: 0 } }),
  dataDate: "2026-10-19",
};

/** Short future: same lot and costs. Gross: 1100 → +28,750 · 1500 → −(1500 − 1215) × 250 = −71,250. Gross max profit at S = 0: 303,750; the loss is unbounded (no max, no capital at risk). */
const SHORT_FUT: Fixture = {
  base: base([leg({ kind: "future", side: "sell", entry_price: 1215 })], { costs: { slippage_pct: 0.1, brokerage_per_side: 0 } }),
  dataDate: "2026-10-19",
};

/**
 * Long put: buy 1300 put at 30, 1 lot of 250; costs 0.05% + ₹20 (the engine's example).
 * Gross: 1100 → (200 − 30) × 250 = 42,500 · 1300 and above → −7,500 · breakeven 1270 · max loss −7,500 · max profit at S = 0: (1300 − 30) × 250 = 317,500.
 * Entry 30 × 250 × .0005 + 20 = 23.75. Net: 1100 → exit 200 × 250 × .0005 + 20 = 45 → 42,500 − 23.75 − 45 = 42,431.25 · 1500 (worthless, no exit) → −7,500 − 23.75 = −7,523.75.
 * Capital at risk −7,500 − 23.75 − 20 (worthless exit charged) = 7,543.75.
 */
const LONG_PUT: Fixture = { base: base([leg({ entry_price: 30, strike: 1300, option_type: "put" })]), dataDate: "2026-10-19" };

/**
 * Cash: 100 shares bought at 1215, costs 0.05% + ₹20. Gross: 1100 → −115 × 100 = −11,500 · breakeven 1215 · gross max loss at 0: −121,500 (not unbounded) · profit unbounded.
 * Net at 1100: entry 1215 × 100 × .0005 + 20 = 80.75, exit 1100 × 100 × .0005 + 20 = 75 → −11,500 − 155.75 = −11,655.75.
 */
const CASH: Fixture = { base: base([leg({ kind: "cash", lot_size: 1, quantity: 100, entry_price: 1215, expiry: null })]), dataDate: "2026-10-19" };

/**
 * Iron condor, no costs: sell 1150 put at 18, buy 1100 put at 8, sell 1280 call at 20, buy 1330 call at 9; 1 lot of 100.
 * Net credit 18 − 8 + 20 − 9 = 21 → 2,100 = max profit (1150 ≤ S ≤ 1280). Max loss (50 − 21) × 100 = 2,900 beyond either wing.
 * Breakevens 1150 − 21 = 1129 and 1280 + 21 = 1301. With zero costs net = gross and capital at risk 2,900.
 */
const IC: Fixture = {
  base: base(
    [
      leg({ lot_size: 100, side: "sell", entry_price: 18, strike: 1150, option_type: "put" }), leg({ lot_size: 100, entry_price: 8, strike: 1100, option_type: "put" }),
      leg({ lot_size: 100, side: "sell", entry_price: 20, strike: 1280, option_type: "call" }), leg({ lot_size: 100, entry_price: 9, strike: 1330, option_type: "call" }),
    ],
    { grid: { min: 1050, max: 1400, points: 36 }, costs: { slippage_pct: 0, brokerage_per_side: 0 } },
  ),
  dataDate: "2026-10-19",
};

// ── page plumbing ────────────────────────────────────────────────────────

interface Seen { bodies: Req[] }

async function mount(page: Page, fx: Fixture, over: { status?: number; abort?: boolean; delay?: number; body?: unknown } = {}): Promise<Seen> {
  const seen: Seen = { bodies: [] };
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (r) => r.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route("**/api/positional/**", (r) => r.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "not mocked here" }) }));
  await page.route(PAYOFF, async (route) => {
    const req = route.request().postDataJSON() as Req;
    seen.bodies.push(req);
    if (over.abort) return route.abort();
    if (over.delay) await new Promise((r) => setTimeout(r, over.delay));
    if (over.status) return route.fulfill({ status: over.status, contentType: "application/json", body: JSON.stringify(over.body ?? { detail: "fixture failure" }) });
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(over.body ?? refPayoff(req, fx)) });
  });
  await page.addInitScript((f) => { (window as unknown as { __STRATEGY_FIXTURE__: unknown }).__STRATEGY_FIXTURE__ = f; }, { base: fx.base, dataDate: fx.dataDate, fan: fx.fan, markers: fx.markers });
  return seen;
}

const open = async (page: Page, fx: Fixture, query = "", over = {}) => {
  const seen = await mount(page, fx, over);
  await page.goto(`${URL}${query}`);
  return seen;
};

/** The drawn line's points, read back from the SVG path. */
async function linePoints(page: Page, testid = "payoff-line"): Promise<Array<{ x: number; y: number }>> {
  const d = (await page.getByTestId(testid).first().getAttribute("d")) ?? "";
  const nums = d.replace(/[ML]/g, " ").trim().split(/\s+/).map(Number);
  const pts: Array<{ x: number; y: number }> = [];
  for (let i = 0; i + 1 < nums.length; i += 2) pts.push({ x: nums[i], y: nums[i + 1] });
  return pts;
}

/**
 * The cross-check: fit value = a·(zeroY − y) from the line's first and last points, and x = grid affine from the
 * ends; every other point must land on the answer's number within `tol` rupees (the SVG keeps one decimal).
 */
async function plotsFaithfully(page: Page, grid: number[], values: number[], tolPct = 0.5, testid = "payoff-line") {
  const pts = await linePoints(page, testid);
  expect(pts.length).toBe(values.length);
  const zeroY = Number(await page.getByTestId("payoff-zero").getAttribute("y1"));
  // Fit on the points holding the smallest and the largest value (the ends may be equal, as in a condor).
  const iLo = values.indexOf(Math.min(...values));
  const iHi = values.indexOf(Math.max(...values));
  const a = (values[iHi] - values[iLo]) / ((zeroY - pts[iHi].y) - (zeroY - pts[iLo].y));
  const tol = ((Math.max(...values) - Math.min(...values)) * tolPct) / 100; // the SVG keeps one decimal of a pixel
  const bx = (grid[grid.length - 1] - grid[0]) / (pts[pts.length - 1].x - pts[0].x);
  pts.forEach((p, i) => {
    expect(Math.abs(a * (zeroY - p.y) - values[i]), `y of point ${i}`).toBeLessThanOrEqual(tol);
    expect(Math.abs(grid[0] + bx * (p.x - pts[0].x) - grid[i]), `x of point ${i}`).toBeLessThan(0.5);
  });
}

async function sidewaysOverflow(page: Page) {
  return page.evaluate(() => {
    const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
    return { doc: document.documentElement.scrollWidth - window.innerWidth, scroll: sc ? sc.scrollWidth - sc.clientWidth : 0 };
  });
}

const readout = (page: Page) => page.getByTestId("payoff-readout");
const fact = (page: Page, id: string) => page.getByTestId(`payoff-fact-${id}`);
const sum = (page: Page, id: string) => page.getByTestId(`sum-${id}`);

// ── SG-1 … SG-5: the payoff shapes ───────────────────────────────────────

const GROSS_NOTE = "over all prices, before costs";

test.describe("MOCK — not real data: payoff shapes", () => {
  test("SG-1 bull call spread: hand-computed figures, boundaries, keyboard readout, faithful line", async ({ page }) => {
    const seen = await open(page, BCS);
    await expect(page.getByTestId("payoff-svg")).toBeVisible();
    const body = refPayoff(seen.bodies[0], BCS) as { expiry: { grid: number[]; gross: number[]; net: number[]; breakevens: number[]; max_profit: number; max_loss: number } };

    // The reference payoff agrees with the hand-computed constants (so the generator is right).
    const at = (s: number, k: "gross" | "net" = "gross") => body.expiry[k][body.expiry.grid.indexOf(s)];
    expect([at(1100), at(1300), at(1330), at(1350), at(1500)]).toEqual([-5500, -5500, 2000, 7000, 7000]);
    expect([at(1100, "net"), at(1330, "net"), at(1500, "net")]).toEqual([-5547.25, 1929, 6869]);
    expect(body.expiry.breakevens).toEqual([1322]);
    expect([body.expiry.max_profit, body.expiry.max_loss]).toEqual([7000, -5500]);

    // The screen shows them. Max profit / loss are gross; capital at risk is the worst net loss.
    await expect(fact(page, "maxprofit")).toHaveText("+₹7,000.00");
    await expect(fact(page, "maxloss")).toHaveText(`${MINUS}₹5,500.00`);
    await expect(fact(page, "breakeven")).toHaveText("₹1,322.00");
    await expect(page.getByTestId("payoff-facts")).toContainText("Max profit (gross)");
    await expect(page.getByTestId("payoff-facts")).toContainText("Max loss (gross)");
    await expect(sum(page, "max-profit")).toHaveText("+₹7,000.00");
    await expect(page.getByTestId("sum-max-profit-note")).toHaveText(GROSS_NOTE);
    await expect(sum(page, "max-loss")).toHaveText(`${MINUS}₹5,500.00`);
    await expect(sum(page, "breakevens")).toHaveText("₹1,322.00");
    await expect(sum(page, "net-premium")).toHaveText("Debit ₹5,500.00");
    await expect(sum(page, "capital-at-risk")).toHaveText("₹5,587.25");
    await expect(page.getByTestId("sum-capital-at-risk-note")).toContainText("worst net loss");
    await expect(sum(page, "net-range")).toHaveText(`${MINUS}₹5,547.25 to +₹6,926.50`);
    await expect(page.getByTestId("payoff-defined-risk")).toContainText(`${MINUS}₹5,500.00`);
    await expect(page.getByTestId("cost-entry")).toHaveText("₹47.25");
    await expect(page.getByTestId("cost-exit")).toHaveText("₹0.00");
    await expect(page.getByTestId("payoff-breakeven")).toHaveCount(1);
    await expect(page.getByTestId("payoff-breakeven")).toHaveAttribute("data-price", "1322");
    await expect(page.getByTestId("payoff-unbounded-profit")).toHaveCount(0);

    // Faithful plot, net and gross.
    await plotsFaithfully(page, body.expiry.grid, body.expiry.net);
    await page.getByTestId("payoff-basis-gross").click();
    await plotsFaithfully(page, body.expiry.grid, body.expiry.gross);
    // The gross maxima are drawn as lines on the gross view only.
    await expect(page.getByTestId("payoff-maxprofit-line")).toHaveCount(1);
    await expect(page.getByTestId("payoff-maxloss-line")).toHaveCount(1);
    await page.getByTestId("payoff-basis-net").click();
    await expect(page.getByTestId("payoff-maxprofit-line")).toHaveCount(0);

    // Reference price (1215) → nearest grid price 1210 (both options worthless: −22 × 250 gross, then the entry costs).
    await expect(readout(page)).toContainText("Underlying ₹1,210.00");
    await expect(page.getByTestId("payoff-readout-gross")).toHaveText(`${MINUS}₹5,500.00`);
    await expect(page.getByTestId("payoff-readout-net")).toHaveText(`${MINUS}₹5,547.25`);

    // Keyboard: below the lower strike, at the lower strike, between the strikes, above the upper strike.
    await page.getByTestId("payoff-svg").focus();
    await page.keyboard.press("Home");
    await expect(readout(page)).toContainText("Underlying ₹1,100.00");
    await expect(page.getByTestId("payoff-readout-net")).toHaveText(`${MINUS}₹5,547.25`);
    await page.keyboard.press("Shift+ArrowRight");
    await page.keyboard.press("Shift+ArrowRight");
    await expect(readout(page)).toContainText("Underlying ₹1,300.00");
    await expect(page.getByTestId("payoff-readout-gross")).toHaveText(`${MINUS}₹5,500.00`);
    for (let i = 0; i < 3; i++) await page.keyboard.press("ArrowRight");
    await expect(readout(page)).toContainText("Underlying ₹1,330.00");
    await expect(page.getByTestId("payoff-readout-gross")).toHaveText("+₹2,000.00");
    await expect(page.getByTestId("payoff-readout-net")).toHaveText("+₹1,929.00");
    await page.keyboard.press("End");
    await expect(readout(page)).toContainText("Underlying ₹1,500.00");
    await expect(page.getByTestId("payoff-readout-gross")).toHaveText("+₹7,000.00");
    await expect(page.getByTestId("payoff-readout-net")).toHaveText("+₹6,869.00");
    await expect(page.getByTestId("payoff-cursor")).toBeVisible();

    await expect(page.getByTestId("payoff-zone-profit")).toHaveText("PROFIT");
    await expect(page.getByTestId("payoff-zone-loss")).toHaveText("LOSS");
    await expect(page.getByTestId("payoff-profit-area")).toHaveCount(1);
    await expect(page.getByTestId("payoff-loss-area")).toHaveCount(1);
    await expect(page.getByTestId("payoff-trust")).toContainText("End of day");
    await expect(page.getByTestId("payoff-broker-line")).toContainText("Nothing was sent to a broker");
    await expect(sum(page, "margin")).toHaveText("—");
    await expect(page.getByTestId("sum-margin-note")).toContainText("does not estimate margin");
  });

  test("SG-1c an answer with no margin reason: the summary says the payoff calculation does not estimate margin, never that no source exists", async ({ page }) => {
    await mount(page, BCS);
    await page.route(PAYOFF, (route) => {
      const req = route.request().postDataJSON() as Req;
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...(refPayoff(req, BCS) as object), margin: null, margin_reason: null }) });
    });
    await page.goto(URL);
    await expect(sum(page, "margin")).toHaveText("—");
    await expect(page.getByTestId("sum-margin-note")).toHaveText("the payoff calculation does not estimate margin");
    await expect(page.getByTestId("payoff-summary")).not.toContainText(/no margin source/i);
  });

  test("SG-1b the engine's nine-point worked example, numbers as the route returns them", async ({ page }) => {
    const fx: Fixture = { ...BCS, base: { ...BCS.base, grid: { min: 1100, max: 1500, points: 9 } } };
    const seen = await open(page, fx);
    await expect(page.getByTestId("payoff-svg")).toBeVisible();
    const body = refPayoff(seen.bodies[0], fx) as { expiry: { grid: number[]; gross: number[]; net: number[]; breakevens: number[] } };
    expect(body.expiry.grid).toEqual([1100, 1150, 1200, 1250, 1300, 1350, 1400, 1450, 1500]);
    expect([body.expiry.gross[0], body.expiry.gross[4], body.expiry.gross[8]]).toEqual([-5500, -5500, 7000]);
    expect([body.expiry.net[0], body.expiry.net[4], body.expiry.net[8]]).toEqual([-5547.25, -5547.25, 6869]);
    expect(body.expiry.net[6]).toBe(6894); // 1400: exits 32.5 + 26.25
    expect(body.expiry.breakevens).toEqual([1322]);
    await plotsFaithfully(page, body.expiry.grid, body.expiry.net);
    await expect(fact(page, "breakeven")).toHaveText("₹1,322.00");
    await page.getByTestId("payoff-svg").focus();
    await page.keyboard.press("Home");
    for (let i = 0; i < 4; i++) await page.keyboard.press("ArrowRight");
    await expect(readout(page)).toContainText("Underlying ₹1,300.00");
    await expect(page.getByTestId("payoff-readout-net")).toHaveText(`${MINUS}₹5,547.25`);
    await page.keyboard.press("ArrowRight");
    await expect(page.getByTestId("payoff-readout-gross")).toHaveText("+₹7,000.00"); // 1350
    await expect(page.getByTestId("payoff-readout-net")).toHaveText("+₹6,926.50"); // 7,000 − 47.25 − 26.25
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("ArrowRight");
    await expect(readout(page)).toContainText("Underlying ₹1,500.00");
    await expect(page.getByTestId("payoff-readout-net")).toHaveText("+₹6,869.00");
  });

  test("SG-2 long future: gross loss bounded at zero, profit unbounded, margin warning, no margin figure", async ({ page }) => {
    const seen = await open(page, LONG_FUT);
    await expect(page.getByTestId("payoff-svg")).toBeVisible();
    const body = refPayoff(seen.bodies[0], LONG_FUT) as { expiry: { grid: number[]; gross: number[]; net: number[] } };
    expect(body.expiry.gross[0]).toBe(-28750);
    expect(body.expiry.gross[body.expiry.grid.indexOf(1300)]).toBe(21250);
    expect(body.expiry.net[0]).toBe(-29328.75);
    expect(body.expiry.net[body.expiry.grid.indexOf(1250)]).toBe(8133.75);
    await plotsFaithfully(page, body.expiry.grid, body.expiry.net);

    await expect(fact(page, "maxprofit")).toContainText("Unlimited");
    await expect(fact(page, "maxloss")).toHaveText(`${MINUS}₹3,03,750.00`);
    await expect(page.getByTestId("payoff-unbounded-profit")).toContainText("Profit unbounded");
    await expect(page.getByTestId("payoff-unbounded-loss")).toHaveCount(0);
    await page.getByTestId("payoff-basis-gross").click();
    await expect(page.getByTestId("payoff-maxloss-line")).toHaveCount(0); // −3,03,750 is far outside the plotted range
    await expect(page.getByTestId("payoff-futures-warning")).toContainText("Futures losses can exceed the initial margin");
    await expect(sum(page, "capital-at-risk")).toHaveText("₹3,04,053.75");
    await expect(sum(page, "margin")).toHaveText("—");
    await expect(page.getByTestId("sum-margin-note")).toContainText("does not estimate margin");
    await expect(page.getByTestId("payoff-caveats")).not.toContainText("exceed the initial margin"); // said once, in the warning box
    await expect(page.getByTestId("payoff-caveats")).toContainText("Margin is not the maximum loss");
    await expect(sum(page, "net-premium")).toHaveText("—");
    await expect(page.getByTestId("payoff-defined-risk")).toHaveCount(0);
    await expect(fact(page, "breakeven")).toHaveText("₹1,215.00");
  });

  test("SG-3 short future: loss unbounded (no maximum, no capital at risk), profit bounded at zero", async ({ page }) => {
    const seen = await open(page, SHORT_FUT);
    await expect(page.getByTestId("payoff-svg")).toBeVisible();
    const body = refPayoff(seen.bodies[0], SHORT_FUT) as { expiry: { grid: number[]; gross: number[]; net: number[] } };
    expect(body.expiry.gross[0]).toBe(28750);
    expect(body.expiry.gross[body.expiry.gross.length - 1]).toBe(-71250);
    await plotsFaithfully(page, body.expiry.grid, body.expiry.net);
    await expect(fact(page, "maxprofit")).toHaveText("+₹3,03,750.00");
    await expect(fact(page, "maxloss")).toContainText("Unlimited");
    await expect(page.getByTestId("payoff-unbounded-loss")).toContainText("Loss unbounded");
    await expect(page.getByTestId("payoff-unbounded-profit")).toHaveCount(0);
    await expect(page.getByTestId("payoff-futures-warning")).toBeVisible();
    await expect(sum(page, "max-loss")).toHaveText("Unlimited");
    await expect(sum(page, "capital-at-risk")).toHaveText("—");
    await expect(page.getByTestId("sum-capital-at-risk-note")).toContainText("no limit");
  });

  test("SG-4 long put: costs make net differ from gross, both lines faithful, capital at risk", async ({ page }) => {
    const seen = await open(page, LONG_PUT);
    await expect(page.getByTestId("payoff-svg")).toBeVisible();
    const body = refPayoff(seen.bodies[0], LONG_PUT) as { expiry: { grid: number[]; gross: number[]; net: number[]; breakevens: number[] }; costs: { entry: number } };
    expect(body.expiry.gross[0]).toBe(42500);
    expect(body.expiry.net[0]).toBe(42431.25);
    expect(body.expiry.gross[body.expiry.gross.length - 1]).toBe(-7500);
    expect(body.expiry.net[body.expiry.net.length - 1]).toBe(-7523.75);
    expect(body.costs.entry).toBe(23.75);
    expect(body.expiry.breakevens).toEqual([1270]);

    await plotsFaithfully(page, body.expiry.grid, body.expiry.net);
    await page.getByTestId("payoff-basis-gross").click();
    await plotsFaithfully(page, body.expiry.grid, body.expiry.gross);
    await page.getByTestId("payoff-basis-net").click();

    await expect(fact(page, "maxloss")).toHaveText(`${MINUS}₹7,500.00`);
    await expect(fact(page, "maxprofit")).toHaveText("+₹3,17,500.00");
    await expect(fact(page, "breakeven")).toHaveText("₹1,270.00");
    await expect(sum(page, "net-premium")).toHaveText("Debit ₹7,500.00");
    await expect(sum(page, "capital-at-risk")).toHaveText("₹7,543.75");
    await expect(sum(page, "net-range")).toHaveText(`${MINUS}₹7,523.75 to +₹42,431.25`);
    await expect(page.getByTestId("cost-entry")).toHaveText("₹23.75");
    await expect(page.getByTestId("cost-excluded")).toContainText("taxes, STT, exchange and statutory charges, dividends, funding");
    await expect(page.getByTestId("payoff-legs-toggle")).toBeDisabled(); // one leg: nothing to separate

    await page.getByTestId("payoff-svg").focus();
    await page.keyboard.press("Home");
    await expect(page.getByTestId("payoff-readout-gross")).toHaveText("+₹42,500.00");
    await expect(page.getByTestId("payoff-readout-net")).toHaveText("+₹42,431.25");
  });

  test("SG-4b cash: 100 shares, loss bounded at zero, profit unbounded, no option inputs", async ({ page }) => {
    const seen = await open(page, CASH);
    await expect(page.getByTestId("payoff-svg")).toBeVisible();
    const body = refPayoff(seen.bodies[0], CASH) as { expiry: { grid: number[]; gross: number[]; net: number[] } };
    expect(body.expiry.gross[0]).toBe(-11500);
    expect(body.expiry.net[0]).toBe(-11655.75);
    await plotsFaithfully(page, body.expiry.grid, body.expiry.net);
    await expect(fact(page, "maxprofit")).toContainText("Unlimited");
    await expect(fact(page, "maxloss")).toHaveText(`${MINUS}₹1,21,500.00`);
    await expect(page.getByTestId("payoff-futures-warning")).toHaveCount(0);
    await expect(page.getByTestId("leg-qty")).toHaveText("100 shares");
    await expect(page.getByTestId("scenario-iv")).toBeDisabled();
    await expect(page.getByTestId("scenario-date")).toBeDisabled();
    await expect(page.getByTestId("scenario-date-reason")).toContainText("no expiry date");
    await expect(page.locator("label", { hasText: "Shares" })).toBeVisible();
  });

  test("SG-5 iron condor: two breakevens, defined risk, per-leg overlay, four leg rows", async ({ page }) => {
    const seen = await open(page, IC);
    await expect(page.getByTestId("payoff-svg")).toBeVisible();
    const body = refPayoff(seen.bodies[0], IC) as { expiry: { grid: number[]; net: number[]; gross: number[]; breakevens: number[]; per_leg: Array<{ gross: number[] }> } };
    expect(Math.max(...body.expiry.net)).toBe(2100);
    expect(Math.min(...body.expiry.net)).toBe(-2900);
    expect(body.expiry.net).toEqual(body.expiry.gross); // no costs in this fixture
    expect(body.expiry.breakevens).toEqual([1129, 1301]);
    await plotsFaithfully(page, body.expiry.grid, body.expiry.net);

    await expect(fact(page, "maxprofit")).toHaveText("+₹2,100.00");
    await expect(fact(page, "maxloss")).toHaveText(`${MINUS}₹2,900.00`);
    await expect(fact(page, "breakeven")).toHaveText("₹1,129.00 · ₹1,301.00");
    await expect(page.getByTestId("payoff-breakeven")).toHaveCount(2);
    await expect(sum(page, "net-premium")).toHaveText("Credit ₹2,100.00");
    await expect(sum(page, "capital-at-risk")).toHaveText("₹2,900.00");
    await page.getByTestId("payoff-basis-gross").click();
    await expect(page.getByTestId("payoff-maxprofit-line")).toHaveCount(1);
    await expect(page.getByTestId("payoff-maxloss-line")).toHaveCount(1);

    await expect(page.locator('[data-testid^="payoff-leg-line-"]')).toHaveCount(0);
    await page.getByTestId("payoff-legs-toggle").click();
    await expect(page.locator('[data-testid^="payoff-leg-line-"]')).toHaveCount(4);
    await plotsFaithfully(page, body.expiry.grid, body.expiry.per_leg[2].gross, 0.5, "payoff-leg-line-2");
    await expect(page.getByTestId("payoff-legend")).toContainText("Sell 1 lot call 1280");

    const rows = page.getByTestId("leg-row");
    await expect(rows).toHaveCount(4);
    await expect(rows.nth(0).getByTestId("leg-instrument")).toHaveText("RELIANCE 1150 PUT");
    await expect(rows.nth(0)).toHaveAttribute("data-side", "sell");
    await expect(rows.nth(0).getByTestId("leg-qty")).toHaveText("1 lot × 100");
    await expect(rows.nth(0).getByTestId("leg-entry")).toHaveText("₹18.00");
    await expect(rows.nth(0).getByTestId("leg-entry-note")).toContainText("NSE F&O bhavcopy close, 2026-10-19");
    await expect(rows.nth(0).getByTestId("leg-expiry")).toHaveText("27 Oct 2026");
    await expect(rows.nth(0).getByTestId("leg-optiontype")).toHaveText("put");
    // 1150 put, sold at 18: gross over the plot 1050 … 1400 runs from −(100 − 18) × 100 = −8,200 to +1,800.
    await expect(rows.nth(0).getByTestId("leg-range")).toHaveText(`${MINUS}₹8,200.00 to +₹1,800.00`);
    await expect(rows.nth(0).getByTestId("entity-icon")).toHaveAttribute("data-key", "RELIANCE");
  });
});

// ── SG-6: pre-expiry ─────────────────────────────────────────────────────

const withPre = (fx: Fixture, pre: PreMode, over: Partial<Fixture> = {}): Fixture => ({ ...fx, pre, base: { ...fx.base, pre_expiry: { date: "2026-10-23", iv_shift_pct: 0, rate_pct: 5.75 } }, ...over });

test.describe("MOCK — not real data: pre-expiry estimate", () => {
  test("SG-6a not requested (pre_expiry null): the tab is disabled and says to set a date", async ({ page }) => {
    await open(page, BCS);
    await expect(page.getByTestId("payoff-svg")).toBeVisible();
    await expect(page.getByTestId("payoff-mode-pre")).toBeDisabled();
    await expect(page.getByTestId("payoff-mode-expiry")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("payoff-pre-reasons")).toContainText("Pre-expiry estimate unavailable");
    await expect(page.getByTestId("payoff-pre-reasons")).toContainText("None was requested");
  });

  test("SG-6b estimate present: enabled, plotted, scalar Greeks at the reference price, assumptions stated", async ({ page }) => {
    const fx = withPre(BCS, "ok");
    const seen = await open(page, fx);
    await expect(page.getByTestId("payoff-svg")).toBeVisible();
    await expect(page.getByTestId("payoff-mode-pre")).toBeEnabled();
    await page.getByTestId("payoff-mode-pre").click();
    await expect(page.getByTestId("payoff-chart")).toHaveAttribute("data-mode", "pre");
    const body = refPayoff(seen.bodies[0], fx) as { pre_expiry: { grid: number[]; net: number[]; gross: number[] } };
    await plotsFaithfully(page, body.pre_expiry.grid, body.pre_expiry.net);
    await page.getByTestId("payoff-basis-gross").click();
    await plotsFaithfully(page, body.pre_expiry.grid, body.pre_expiry.gross);

    await page.getByTestId("payoff-svg").focus();
    await page.keyboard.press("End");
    await expect(readout(page)).toContainText("Underlying ₹1,500.00");
    await expect(page.getByTestId("payoff-readout-gross")).toHaveText("+₹5,700.00"); // (1500 − 1215) × 20
    const greeks = page.getByTestId("payoff-readout-greeks");
    await expect(greeks).toContainText("Greeks at ₹1,215.00");
    await expect(greeks).toContainText("Δ 52.100");
    await expect(greeks).toContainText("Γ 0.1234");
    await expect(greeks).toContainText("Θ −12.500/day");
    await expect(greeks).toContainText("Vega 33.300");
    await expect(greeks).toContainText("ρ —"); // null stays a dash
    const before = await greeks.textContent();
    await page.keyboard.press("Home");
    expect(await greeks.textContent()).toBe(before); // position Greeks at the reference price do not move with the cursor

    const note = page.getByTestId("payoff-pre-note");
    await expect(note).toContainText("Black-76, not a guarantee");
    await expect(note).toContainText("2026-10-23");
    await expect(note).toContainText("Rate 5.75% (request rate_pct (MOCK))");
    await expect(note).toContainText("forward basis: carried spot");
    await expect(note).toContainText("volatility shift 0 points");
    await expect(note).toContainText("prices as of 2026-10-19");
    await expect(note).toContainText("Leg 1: 4 days to expiry, IV 25% (request iv_pct (MOCK))");
    await expect(note).toContainText("Leg 2: 4 days to expiry");
    await expect(page.getByTestId("payoff-legs-toggle")).toBeDisabled();
    await expect(page.getByTestId("payoff-unbounded-profit")).toHaveCount(0);
    await page.getByTestId("payoff-mode-expiry").click();
    await expect(page.getByTestId("payoff-maxprofit-line")).toHaveCount(1);
  });

  test("SG-6c expiry day: the estimate is plotted and the Greeks are null (a dash with the reason)", async ({ page }) => {
    await open(page, withPre(BCS, "expiryday"));
    await expect(page.getByTestId("payoff-svg")).toBeVisible();
    await page.getByTestId("payoff-mode-pre").click();
    await expect(page.getByTestId("payoff-readout-greeks")).toContainText("Greeks: —");
  });

  test("SG-6d requested but a leg cannot be priced: null series, tab disabled, the reasons shown", async ({ page }) => {
    const fx = withPre(BCS, "unavailable", { unavailable: [{ leg: 1, reason: "The entry premium has no valid Black-76 implied volatility; give iv_pct." }] });
    await open(page, fx);
    await expect(page.getByTestId("payoff-svg")).toBeVisible();
    await expect(page.getByTestId("payoff-mode-pre")).toBeDisabled();
    await expect(page.getByTestId("payoff-pre-reasons")).toContainText("Pre-expiry estimate unavailable");
    await expect(page.getByTestId("payoff-pre-unavailable")).toContainText("Leg 2 has no estimate: The entry premium has no valid Black-76 implied volatility");
    await expect(page.getByTestId("payoff-chart")).toHaveAttribute("data-mode", "expiry");
  });
});

// ── SG-7: scenario controls ──────────────────────────────────────────────

test.describe("MOCK — not real data: scenario controls", () => {
  test("SG-7a price, size and reset change the request and the readout; the old answer is dimmed meanwhile", async ({ page }) => {
    const seen = await open(page, BCS, "", { delay: 350 });
    await expect(page.getByTestId("payoff-svg")).toBeVisible();
    await expect(page.getByTestId("payoff-chart")).toHaveAttribute("data-stale", "false");
    expect(seen.bodies[0].scenarios).toBeUndefined();
    expect(seen.bodies[0].pre_expiry).toBeUndefined();

    await page.getByTestId("scenario-price").fill("1330");
    await expect(page.getByTestId("payoff-chart")).toHaveAttribute("data-stale", "true");
    await expect(page.getByTestId("payoff-scenario-row")).toContainText("Scenario what-if: underlying ₹1,330.00");
    await expect(page.getByTestId("payoff-chart")).toHaveAttribute("data-stale", "false");
    await expect(page.getByTestId("payoff-scenario-row")).toContainText("gross +₹2,000.00, net +₹1,929.00"); // hand-computed in the fixture note
    await expect(page.getByTestId("payoff-scenario-point")).toHaveCount(1);
    expect(seen.bodies[seen.bodies.length - 1].scenarios).toEqual([{ name: "what-if", underlying_price: 1330 }]);

    // Two lots: gross 4,000; entry 30 + 24.5; exit of the long call 30 × 500 × .0005 + 20 = 27.5 → net 4,000 − 54.5 − 27.5 = 3,918.00.
    await page.getByTestId("scenario-size").fill("2");
    await expect.poll(() => seen.bodies[seen.bodies.length - 1].legs[0].quantity).toBe(2);
    expect(seen.bodies[seen.bodies.length - 1].legs[1].quantity).toBe(2);
    await expect(page.getByTestId("payoff-scenario-row")).toContainText("gross +₹4,000.00, net +₹3,918.00");

    // Reset returns to the base position; its answer is already cached, so the screen needs no new request.
    await page.getByTestId("scenario-reset").click();
    await expect(page.getByTestId("payoff-scenario-row")).toHaveCount(0);
    await expect(page.getByTestId("scenario-price")).toHaveValue("");
    await expect(page.getByTestId("scenario-size")).toHaveValue("");
    await expect(page.getByTestId("payoff-chart")).toHaveAttribute("data-stale", "false");
    await page.getByTestId("payoff-svg").focus();
    await page.keyboard.press("End");
    await expect(page.getByTestId("payoff-readout-net")).toHaveText("+₹6,869.00"); // one lot again, not two
  });

  test("SG-7b slider moves the what-if price", async ({ page }) => {
    const seen = await open(page, BCS);
    await expect(page.getByTestId("payoff-svg")).toBeVisible();
    await page.getByTestId("scenario-price-slider").fill("1300");
    await expect.poll(() => seen.bodies[seen.bodies.length - 1].scenarios?.[0]?.underlying_price).toBe(1300);
    await expect(page.getByTestId("scenario-price")).toHaveValue("1300");
    await expect(page.getByTestId("payoff-scenario-row")).toContainText(`gross ${MINUS}₹5,500.00, net ${MINUS}₹5,547.25`);
  });

  test("SG-7c futures: IV is disabled with the reason, the date is enabled (it asks for the estimate)", async ({ page }) => {
    await open(page, LONG_FUT);
    await expect(page.getByTestId("payoff-svg")).toBeVisible();
    await expect(page.getByTestId("scenario-iv")).toBeDisabled();
    await expect(page.getByTestId("scenario-iv-reason")).toContainText("options only");
    await expect(page.getByTestId("scenario-date")).toBeEnabled();
    await expect(page.getByTestId("scenario-size")).toHaveAttribute("placeholder", "1"); // one leg: the leg's own lots
  });

  test("SG-7d options: IV and date are enabled, the date is bounded, and setting them requests the estimate", async ({ page }) => {
    const fx: Fixture = { ...BCS, pre: "ok" };
    const seen = await open(page, fx);
    await expect(page.getByTestId("payoff-svg")).toBeVisible();
    await expect(page.getByTestId("payoff-mode-pre")).toBeDisabled(); // not requested yet
    await expect(page.getByTestId("scenario-iv")).toBeEnabled();
    await expect(page.getByTestId("scenario-date")).toBeEnabled();
    await expect(page.getByTestId("scenario-date")).toHaveAttribute("min", "2026-10-19");
    await expect(page.getByTestId("scenario-date")).toHaveAttribute("max", "2026-10-27");
    await page.getByTestId("scenario-date").fill("2026-10-22");
    await page.getByTestId("scenario-iv").fill("5");
    await expect.poll(() => {
      const b = seen.bodies[seen.bodies.length - 1];
      return `${b.pre_expiry?.date}|${b.pre_expiry?.iv_shift_pct}`;
    }).toBe("2026-10-22|5");
    await expect(page.getByTestId("payoff-mode-pre")).toBeEnabled(); // the answer now carries the estimate
  });
});

// ── SG-8: failures never look like an empty chart ────────────────────────

test.describe("MOCK — not real data: failures", () => {
  for (const [name, over, words] of [
    ["422", { status: 422, body: { detail: "legs must not be empty" } }, "rejected this request: legs must not be empty"],
    ["401", { status: 401, body: { detail: "Not authenticated" } }, "signed out"],
    ["403", { status: 403, body: { detail: "nope" } }, "not allowed"],
    ["network", { abort: true }, "network request failed"],
    ["500", { status: 500, body: { detail: "boom" } }, "failed on the server: boom"],
    ["contract", { body: { valid: true } }, "form the screen does not understand"],
  ] as const) {
    test(`SG-8 ${name}: error text, retry, no chart drawn`, async ({ page }) => {
      await open(page, BCS, "", over);
      await expect(page.getByTestId("payoff-error")).toContainText(words, { timeout: 15_000 });
      await expect(page.getByTestId("payoff-retry")).toBeVisible();
      await expect(page.getByTestId("payoff-svg")).toHaveCount(0);
      await expect(page.getByTestId("payoff-trust")).toContainText("Source failed");
    });
  }

  test("SG-8 rejected structure (valid false): the problem is shown and no chart is drawn as success", async ({ page }) => {
    const body = {
      valid: false, problems: [{ field: "legs", code: "undefined_risk_not_supported", message: "A short call with no long call above it has unlimited risk; this release allows defined-risk options only." }],
      warnings: [], calculation_version: "payoff-v1", expiry: null, pre_expiry: null, costs: null, margin: null, margin_reason: "This payoff calculation does not estimate margin (MOCK).",
      capital_at_risk: null, loss_can_exceed_margin: false, caveats: [], sent_to_broker: false,
    };
    await open(page, BCS, "", { body });
    await expect(page.getByTestId("payoff-rejected")).toContainText("This structure was rejected");
    await expect(page.getByTestId("payoff-problem")).toContainText("unlimited risk");
    await expect(page.getByTestId("payoff-problem")).toContainText("undefined_risk_not_supported");
    await expect(page.getByTestId("payoff-svg")).toHaveCount(0);
    await expect(page.getByTestId("payoff-no-chart")).toBeVisible();
    await expect(sum(page, "max-profit")).toHaveText("—");
  });

  test("SG-8 route warnings are shown with their codes", async ({ page }) => {
    const seen = await mount(page, BCS);
    await page.unroute(PAYOFF);
    await page.route(PAYOFF, (route) => {
      const req = route.request().postDataJSON() as Req;
      seen.bodies.push(req);
      const body = refPayoff(req, BCS) as Record<string, unknown>;
      body.warnings = [{ code: "breakeven_outside_grid", message: "A breakeven lies outside the plotted price range: widen the grid to see it." }];
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    });
    await page.goto(URL);
    await expect(page.getByTestId("payoff-warnings")).toContainText("widen the grid");
    await expect(page.getByTestId("payoff-warnings")).toContainText("breakeven_outside_grid");
  });
});

// ── SG-9: unavailable legs ───────────────────────────────────────────────

test.describe("MOCK — not real data: unavailable legs", () => {
  test("SG-9 a leg the estimate could not price shows its reason in the chart tab and the leg row", async ({ page }) => {
    const fx = withPre(BCS, "unavailable", { unavailable: [{ leg: 1, reason: "No implied volatility for the 1350 call: the premium is below intrinsic value; give iv_pct." }] });
    await open(page, fx);
    await expect(page.getByTestId("payoff-svg")).toBeVisible();
    await expect(page.getByTestId("payoff-pre-unavailable")).toContainText("Leg 2 has no estimate: No implied volatility for the 1350 call");
    const rows = page.getByTestId("leg-row");
    await expect(rows.nth(0).getByTestId("leg-unavailable")).toHaveText("—");
    await expect(rows.nth(1).getByTestId("leg-unavailable")).toHaveText("Unavailable");
    await expect(rows.nth(1).getByTestId("leg-unavailable-note")).toContainText("No implied volatility for the 1350 call");
  });
});

// ── SG-10: the underlying-movement graph ─────────────────────────────────

const BARS = Array.from({ length: 50 }, (_, i) => {
  const d = new Date(Date.UTC(2026, 7, 31 + i, 12));
  const close = Math.round((1150 + i * 1.8 + (i % 3) * 2) * 100) / 100;
  return { day: d.toISOString().slice(0, 10), open: close - 1, high: close + 3, low: close - 3, close, volume: 100000 + i * 1000 };
});
const LAST_CLOSE = BARS[BARS.length - 1].close; // 1150 + 49 × 1.8 + (49 % 3 = 1) × 2 = 1240.2

const FAN_BASE = { bars: BARS, name: "RELIANCE", trigger: 1235, invalidation: 1190, targets: [{ label: "Target 1", low: 1280, high: 1300 }] };
const FAN_SCENARIO = {
  origin: "2026-10-19", horizonSessions: 10, version: "scanner-rules v2 (MOCK)",
  bands: [{ name: "conservative", low: 1200, high: 1215 }, { name: "base", low: 1245, high: 1265 }, { name: "optimistic", low: 1290, high: 1290 }],
};

test.describe("MOCK — not real data: underlying movement graph", () => {
  test("SG-10a scenario bands: straight wedges from the last close, legend and caption say estimate", async ({ page }) => {
    expect(BARS[BARS.length - 1].day).toBe("2026-10-19");
    expect(LAST_CLOSE).toBe(1240.2);
    await open(page, { ...BCS, fan: { ...FAN_BASE, scenario: FAN_SCENARIO } });
    await expect(page.getByTestId("fan-svg")).toBeVisible();
    await expect(page.getByTestId("desk-chart-svg")).toBeVisible(); // the desk's own candle chart is reused
    await expect(page.getByTestId("desk-candle")).toHaveCount(50);
    await expect(page.getByTestId("desk-level-entry")).toHaveAttribute("data-value", "1235");
    await expect(page.getByTestId("desk-level-stop")).toHaveAttribute("data-value", "1190");
    await expect(page.getByTestId("desk-level-target")).toHaveAttribute("data-value", "1280");

    const bands = page.getByTestId("fan-band");
    await expect(bands).toHaveCount(3);
    for (const [i, b] of FAN_SCENARIO.bands.entries()) {
      await expect(bands.nth(i)).toHaveAttribute("data-name", b.name);
      await expect(bands.nth(i)).toHaveAttribute("data-low", String(b.low));
      await expect(bands.nth(i)).toHaveAttribute("data-high", String(b.high));
      // Three points only: the origin and the two ends of the range. Nothing smoother.
      const pts = (await bands.nth(i).locator("polygon").getAttribute("points"))!.trim().split(/\s+/);
      expect(pts).toHaveLength(3);
      const [o, hi, lo] = pts.map((p) => p.split(",").map(Number));
      expect(o[0]).toBeLessThan(hi[0]);
      expect(hi[0]).toBe(lo[0]);
      expect(hi[1]).toBeLessThanOrEqual(lo[1]);
    }
    // Same origin y for every wedge (the last close), and higher levels are higher on the pane.
    const originY = await bands.evaluateAll((els) => els.map((e) => e.querySelector("polygon")!.getAttribute("points")!.split(" ")[0].split(",")[1]));
    expect(new Set(originY).size).toBe(1);
    const baseHi = Number((await bands.nth(1).locator("polygon").getAttribute("points"))!.split(" ")[1].split(",")[1]);
    const optHi = Number((await bands.nth(2).locator("polygon").getAttribute("points"))!.split(" ")[1].split(",")[1]);
    expect(optHi).toBeLessThan(baseHi);

    const caption = page.getByTestId("fan-caption");
    await expect(caption).toContainText("Scenario estimates, not observed prices and not guarantees");
    await expect(caption).toContainText("19 Oct 2026");
    await expect(caption).toContainText("horizon 10 sessions");
    await expect(caption).toContainText("scanner-rules v2 (MOCK)");
    await expect(caption).toContainText("nothing smoother");
    await expect(page.getByTestId("fan-legend")).toContainText("scenario estimate, not observed price");
    await expect(page.getByTestId("fan-legend")).toContainText("Straight ranges from the last close");
    await expect(page.getByTestId("fan-target")).toHaveCount(1);
    await expect(page.getByTestId("fan-trigger")).toHaveCount(1);
    await expect(page.getByTestId("fan-invalidation")).toHaveCount(1);
    await expect(page.getByTestId("fan-trust")).toContainText("scanner-rules v2 (MOCK)");
    await expect(page.getByTestId("fan-levels")).toContainText("Target 1 ₹1,280.00 to ₹1,300.00");
  });

  test("SG-10b no scenario inputs: history and levels only, with a note, and nothing projected", async ({ page }) => {
    await open(page, { ...BCS, fan: { ...FAN_BASE, scenario: null } });
    await expect(page.getByTestId("desk-chart-svg")).toBeVisible();
    await expect(page.getByTestId("fan-svg")).toHaveCount(0);
    await expect(page.getByTestId("fan-band")).toHaveCount(0);
    await expect(page.getByTestId("fan-none")).toContainText("No scenario inputs were supplied");
    await expect(page.getByTestId("fan-none")).toContainText("Nothing is projected");
    await expect(page.getByTestId("fan-trust")).toBeVisible();
  });

  test("SG-10c a band without numbers is not drawn and is named; an origin on another day is flagged", async ({ page }) => {
    const scenario = { ...FAN_SCENARIO, origin: "2026-10-16", bands: [{ name: "conservative", low: null, high: null }, FAN_SCENARIO.bands[1]] };
    await open(page, { ...BCS, fan: { ...FAN_BASE, scenario } });
    await expect(page.getByTestId("fan-band")).toHaveCount(1);
    await expect(page.getByTestId("fan-caption")).toContainText("Not drawn, no numbers given: conservative");
    await expect(page.getByTestId("fan-caption")).toContainText("not on the last candle's day");
  });
});

// ── SG-11: persona wording; SG-12: phone ─────────────────────────────────

test.describe("MOCK — not real data: persona and phone", () => {
  test("SG-11 investor wording changes the labels, not the numbers", async ({ page }) => {
    await open(page, { ...BCS, fan: { ...FAN_BASE, scenario: null } }, "&persona=investor");
    await expect(page.getByTestId("payoff-svg")).toBeVisible();
    await expect(page.getByTestId("payoff-mode-expiry")).toHaveText("At expiry");
    await expect(page.getByTestId("payoff-mode-pre")).toHaveText("Before expiry (estimate)");
    await expect(page.getByTestId("payoff-basis-net")).toHaveText("After costs");
    await expect(page.getByTestId("payoff-basis-gross")).toHaveText("Before costs");
    await expect(page.getByTestId("strategy-graphs")).toHaveAttribute("data-persona", "investor");
    await expect(page.getByTestId("leg-side").first()).toHaveText("BUY");
    await expect(page.getByTestId("leg-side").nth(1)).toHaveText("SELL");
    await expect(page.getByTestId("desk-level-entry")).toHaveCount(1);
    await expect(page.getByTestId("desk-chart-legend")).toContainText("Buy above");
    await expect(fact(page, "maxprofit")).toHaveText("+₹7,000.00");
  });

  test("SG-11 trader wording is the default", async ({ page }) => {
    await open(page, BCS);
    await expect(page.getByTestId("payoff-mode-expiry")).toHaveText("Expiry payoff");
    await expect(page.getByTestId("payoff-basis-net")).toHaveText("Net");
    await expect(page.getByTestId("leg-side").first()).toHaveText("LONG · BUY");
  });

  test("SG-12 phone 390: no sideways scroll for the payoff, the pre-expiry view and the fan; role=img summaries", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const fx: Fixture = { ...withPre(IC, "ok"), fan: { ...FAN_BASE, scenario: FAN_SCENARIO } };
    await open(page, fx);
    await expect(page.getByTestId("payoff-svg")).toBeVisible();
    await expect(page.getByTestId("fan-svg")).toBeVisible();
    await expect(page.getByTestId("payoff-svg")).toHaveAttribute("data-testid", "payoff-svg");
    let o = await sidewaysOverflow(page);
    expect(o.doc).toBeLessThanOrEqual(0);
    expect(o.scroll).toBeLessThanOrEqual(0);

    await page.getByTestId("payoff-legs-toggle").click();
    await page.getByTestId("payoff-mode-pre").click();
    await page.getByTestId("scenario-price").fill("1250");
    await expect(page.getByTestId("payoff-pre-note")).toBeVisible();
    o = await sidewaysOverflow(page);
    expect(o.doc).toBeLessThanOrEqual(0);
    expect(o.scroll).toBeLessThanOrEqual(0);

    // Text summaries for every chart.
    await page.getByTestId("payoff-mode-expiry").click();
    const label = await page.getByTestId("payoff-svg").getAttribute("aria-label");
    expect(await page.getByTestId("payoff-svg").getAttribute("role")).toBe("img");
    expect(label).toContain("Maximum profit (gross) +₹2,100.00");
    expect(label).toContain(`Maximum loss (gross) ${MINUS}₹2,900.00`);
    expect(label).toContain("Breakeven (gross) at ₹1,129.00 and ₹1,301.00");
    expect(label).toContain("arrow keys");
    expect(await page.getByTestId("fan-svg").getAttribute("role")).toBe("img");
    expect(await page.getByTestId("fan-svg").getAttribute("aria-label")).toContain("not observed prices");
    expect(await page.getByTestId("desk-chart-svg").getAttribute("role")).toBe("img");

    // The phone chart is the compact viewBox, and axis text is drawn at a readable size on screen.
    expect(await page.getByTestId("payoff-svg").getAttribute("viewBox")).toBe("0 0 330 220");
    const box = await page.getByTestId("payoff-svg").boundingBox();
    expect(box!.width).toBeLessThanOrEqual(390);
    const fontPx = await page.locator('[data-testid="payoff-svg"] text').first().evaluate((el) => {
      const svg = el.ownerSVGElement!;
      const scale = svg.getBoundingClientRect().width / svg.viewBox.baseVal.width;
      return parseFloat(getComputedStyle(el).fontSize) * scale;
    });
    expect(fontPx).toBeGreaterThanOrEqual(9);
  });

  test("SG-12 desktop uses the wide viewBox", async ({ page }) => {
    await open(page, BCS);
    await expect(page.getByTestId("payoff-svg")).toHaveAttribute("viewBox", "0 0 540 270");
  });
});
