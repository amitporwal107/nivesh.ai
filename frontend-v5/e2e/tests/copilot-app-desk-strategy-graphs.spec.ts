/**
 * One-screen Copilot app — Smart trading desk: the Strategy Builder's interactive graphs (PRD §16.6 A to D;
 * screens/tradingdesk/strategy/: PayoffChart, ScenarioControls, LegTable, PayoffSummary, ScenarioFan,
 * StrategyGraphs, usePayoff, strategy-contract).
 *
 * MOCK — not real data. Every /api response here is generated in this file. POST /api/desk/strategy/payoff is
 * answered by `refPayoff`, an independent reference implementation of the expiry payoff written for this spec
 * (it shares no code with the app). The headline figures (max profit, max loss, breakevens, the P&L at chosen
 * prices) are HAND-COMPUTED constants written beside each fixture and asserted against both the generated
 * answer and the screen. Faithfulness: `plotsFaithfully` fits the drawn line to the answer's numbers and fails if
 * any plotted point is off by more than a few rupees.
 *
 * The graphs are reached through the test-only route ?tab=more&view=strategy-graphs, which exists only in a
 * build with VITE_STRATEGY_HARNESS=1 (fe-run-stgraph.sh sets it) and reads window.__STRATEGY_FIXTURE__.
 *
 * Cases: SG-1 bull call spread · SG-2 long future · SG-3 short future · SG-4 long put (costs, net/gross) ·
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
  underlying: string; reference_price: number; legs: Leg[]; grid?: { min: number; max: number; points: number };
  costs?: { slippage_pct?: number; brokerage_per_side?: number }; scenarios?: Array<{ name: string; underlying_price: number }>;
  pre_expiry?: { date: string; iv_shift_pct?: number; rate_pct?: number };
}
interface Facts {
  max_profit: number | null; max_loss: number | null; profit_unbounded: boolean; loss_unbounded: boolean;
  net_premium: number | null; capital_at_risk: number | null; caveats: string[]; warnings?: Array<{ code: string; message: string }>;
}
interface Fixture { base: Req; dataDate: string; facts: Facts; pre?: boolean; unavailable?: Array<{ leg: number; reason: string }>; fan?: unknown; markers?: unknown }

// ── the independent reference payoff ─────────────────────────────────────

const r2 = (n: number) => Math.round(n * 100) / 100;

function legAt(l: Leg, s: number): number {
  const sign = l.side === "buy" ? 1 : -1;
  const q = l.quantity * (l.kind === "cash" ? 1 : l.lot_size);
  if (l.kind === "option") {
    const intrinsic = l.option_type === "call" ? Math.max(s - (l.strike as number), 0) : Math.max((l.strike as number) - s, 0);
    return sign * (intrinsic - l.entry_price) * q;
  }
  return sign * (s - l.entry_price) * q;
}

function refPayoff(req: Req, fx: Fixture) {
  const g = req.grid as { min: number; max: number; points: number };
  const grid = Array.from({ length: g.points }, (_, i) => r2(g.min + ((g.max - g.min) * i) / (g.points - 1)));
  const perSide = req.costs?.brokerage_per_side ?? 0;
  const entry = perSide * req.legs.length;
  const round = entry * 2;
  const gross = grid.map((s) => r2(req.legs.reduce((a, l) => a + legAt(l, s), 0)));
  const net = gross.map((v) => r2(v - round));
  const breakevens: number[] = [];
  for (let i = 0; i < grid.length; i++) {
    if (net[i] === 0) breakevens.push(grid[i]);
    else if (i > 0 && net[i - 1] !== 0 && Math.sign(net[i - 1]) !== Math.sign(net[i])) {
      breakevens.push(r2(grid[i - 1] + ((0 - net[i - 1]) * (grid[i] - grid[i - 1])) / (net[i] - net[i - 1])));
    }
  }
  const scenarios = (req.scenarios ?? []).map((s) => {
    const gv = r2(req.legs.reduce((a, l) => a + legAt(l, s.underlying_price), 0));
    return { name: s.name, underlying_price: s.underlying_price, gross: gv, net: r2(gv - round) };
  });
  const body: Record<string, unknown> = {
    valid: true, problems: [], warnings: fx.facts.warnings ?? [], calculation_version: "payoff-v1 (MOCK)",
    expiry: {
      grid, gross, net,
      per_leg: req.legs.map((l, i) => ({ index: i, label: `${l.side === "buy" ? "Buy" : "Sell"} ${l.quantity} ${l.kind === "option" ? `${l.option_type} ${l.strike}` : l.kind}`, gross: grid.map((s) => r2(legAt(l, s))) })),
      breakevens, max_profit: fx.facts.max_profit, max_loss: fx.facts.max_loss,
      profit_unbounded: fx.facts.profit_unbounded, loss_unbounded: fx.facts.loss_unbounded, net_premium: fx.facts.net_premium, scenarios,
    },
    pre_expiry: null,
    costs: { model: "slippage % of traded value + flat brokerage, each side, each leg (MOCK)", entry, exit_at_expiry: entry, round_trip: round, excluded: ["taxes", "statutory charges", "dividends", "funding"] },
    margin: null, capital_at_risk: fx.facts.capital_at_risk, caveats: fx.facts.caveats, sent_to_broker: false,
  };
  if (fx.pre && req.pre_expiry) {
    // MOCK — a smooth made-up estimate curve: the spec only checks that the screen plots these numbers.
    const est = (s: number) => r2(((s - (req.reference_price ?? 0)) * 20));
    const pg = grid.filter((_, i) => i % 2 === 0);
    body.pre_expiry = {
      date: req.pre_expiry.date, model: "Black-76 (MOCK)", assumptions: { iv_shift_pct: req.pre_expiry.iv_shift_pct ?? 0, rate_pct: 5.75 },
      grid: pg, gross: pg.map(est), net: pg.map((s) => r2(est(s) - round)),
      greeks: { delta: pg.map((_, i) => r2(i / 100)), gamma: 0.01, theta: -12.5, vega: 33.3, rho: null }, per_leg_greeks: [],
      unavailable: fx.unavailable ?? [],
    };
  } else if (!req.pre_expiry) {
    body.warnings = [...(fx.facts.warnings ?? []), { code: "pre_expiry_not_requested", message: "No evaluation date was sent, so no pre-expiry estimate was made." }];
  }
  return body;
}

// ── the fixtures (hand-computed figures beside each) ─────────────────────

const leg = (over: Partial<Leg>): Leg => ({
  kind: "option", side: "buy", quantity: 1, lot_size: 100, entry_price: 0, expiry: "2026-10-27", strike: null, option_type: null,
  price_source: "MOCK — not real data: NSE F&O bhavcopy close, 2026-10-19", iv_pct: null, ...over,
});
const GRID = { min: 1100, max: 1400, points: 31 }; // step 10

/**
 * Bull call spread: buy 1200 call at 40, sell 1300 call at 10, 1 lot of 100, no costs.
 * Net debit 30 × 100 = 3,000 · max loss −3,000 (S ≤ 1200) · max profit (100 − 30) × 100 = 7,000 (S ≥ 1300) · breakeven 1200 + 30 = 1230.
 * P&L: 1150 → −3,000 · 1210 → (10−40)+10 = −20 × 100 = −2,000 · 1220 → −1,000 · 1250 → (50−40)+10 = 20 × 100 = 2,000 · 1350 → 7,000.
 */
const BCS: Fixture = {
  base: { underlying: "RELIANCE", reference_price: 1215, grid: GRID, costs: { brokerage_per_side: 0 }, legs: [leg({ entry_price: 40, strike: 1200, option_type: "call" }), leg({ side: "sell", entry_price: 10, strike: 1300, option_type: "call" })] },
  dataDate: "2026-10-19",
  facts: { max_profit: 7000, max_loss: -3000, profit_unbounded: false, loss_unbounded: false, net_premium: -3000, capital_at_risk: 3000, caveats: ["MOCK caveat: expiry payoff ignores early exercise."] },
};

/** Long future: 1 lot of 250 at 1215. Linear: 1100 → −115 × 250 = −28,750 · 1300 → 85 × 250 = 21,250 · breakeven 1215 · at S = 0 the loss is 1215 × 250 = 303,750. */
const LONG_FUT: Fixture = {
  base: { underlying: "RELIANCE", reference_price: 1215, grid: GRID, costs: { brokerage_per_side: 0 }, legs: [leg({ kind: "future", entry_price: 1215, lot_size: 250 })] },
  dataDate: "2026-10-19",
  facts: { max_profit: null, max_loss: -303750, profit_unbounded: true, loss_unbounded: false, net_premium: null, capital_at_risk: 303750, caveats: [] },
};

/** Short future: 1 lot of 250 at 1215: 1100 → +28,750 (left, profit) · 1400 → −46,250 (right, loss) · breakeven 1215. */
const SHORT_FUT: Fixture = {
  base: { underlying: "RELIANCE", reference_price: 1215, grid: GRID, costs: { brokerage_per_side: 0 }, legs: [leg({ kind: "future", side: "sell", entry_price: 1215, lot_size: 250 })] },
  dataDate: "2026-10-19",
  facts: { max_profit: null, max_loss: null, profit_unbounded: true, loss_unbounded: true, net_premium: null, capital_at_risk: null, caveats: [] },
};

/**
 * Long put: buy 1200 put at 25, 1 lot of 100, brokerage 20 per side (entry 20, exit 20, round trip 40).
 * Gross: 1100 → (100 − 25) × 100 = 7,500 · 1200 and above → −2,500. Net = gross − 40: 1100 → 7,460 · above → −2,540.
 * Max loss gross −2,500, net −2,540. Max profit at S = 0: (1200 − 25) × 100 = 117,500 gross, 117,460 net. Net breakeven 1200 − 25 − 0.40 = 1174.60.
 */
const LONG_PUT: Fixture = {
  base: { underlying: "RELIANCE", reference_price: 1215, grid: GRID, costs: { brokerage_per_side: 20 }, legs: [leg({ entry_price: 25, strike: 1200, option_type: "put" })] },
  dataDate: "2026-10-19",
  facts: { max_profit: 117460, max_loss: -2540, profit_unbounded: false, loss_unbounded: false, net_premium: -2500, capital_at_risk: 2540, caveats: [] },
};

/**
 * Iron condor: sell 1150 put at 18, buy 1100 put at 8, sell 1280 call at 20, buy 1330 call at 9; 1 lot of 100; no costs.
 * Net credit 18 − 8 + 20 − 9 = 21 → 2,100 = max profit (1150 ≤ S ≤ 1280). Max loss (50 − 21) × 100 = 2,900 beyond either wing.
 * Breakevens 1150 − 21 = 1129 and 1280 + 21 = 1301.
 */
const IC: Fixture = {
  base: {
    underlying: "RELIANCE", reference_price: 1215, grid: { min: 1050, max: 1400, points: 36 }, costs: { brokerage_per_side: 0 },
    legs: [
      leg({ side: "sell", entry_price: 18, strike: 1150, option_type: "put" }), leg({ entry_price: 8, strike: 1100, option_type: "put" }),
      leg({ side: "sell", entry_price: 20, strike: 1280, option_type: "call" }), leg({ entry_price: 9, strike: 1330, option_type: "call" }),
    ],
  },
  dataDate: "2026-10-19",
  facts: { max_profit: 2100, max_loss: -2900, profit_unbounded: false, loss_unbounded: false, net_premium: 2100, capital_at_risk: 2900, caveats: [] },
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

test.describe("MOCK — not real data: payoff shapes", () => {
  test("SG-1 bull call spread: hand-computed figures, boundaries, keyboard readout, faithful line", async ({ page }) => {
    const seen = await open(page, BCS);
    await expect(page.getByTestId("payoff-svg")).toBeVisible();
    const body = refPayoff(seen.bodies[0] ?? BCS.base, BCS) as { expiry: { grid: number[]; gross: number[]; net: number[]; breakevens: number[] } };

    // The reference payoff agrees with the hand-computed constants (so the generator is right).
    const at = (s: number) => body.expiry.gross[body.expiry.grid.indexOf(s)];
    expect([at(1150), at(1210), at(1220), at(1250), at(1350)]).toEqual([-3000, -2000, -1000, 2000, 7000]);
    expect(body.expiry.breakevens).toEqual([1230]);

    // The screen shows the hand-computed numbers.
    await expect(fact(page, "maxprofit")).toHaveText("+₹7,000.00");
    await expect(fact(page, "maxloss")).toHaveText(`${MINUS}₹3,000.00`);
    await expect(fact(page, "breakeven")).toHaveText("₹1,230.00");
    await expect(sum(page, "max-profit")).toHaveText("+₹7,000.00");
    await expect(sum(page, "max-loss")).toHaveText(`${MINUS}₹3,000.00`);
    await expect(sum(page, "breakevens")).toHaveText("₹1,230.00");
    await expect(sum(page, "net-premium")).toHaveText("Debit ₹3,000.00");
    await expect(sum(page, "capital-at-risk")).toHaveText("₹3,000.00");
    await expect(page.getByTestId("payoff-defined-risk")).toContainText(`${MINUS}₹3,000.00`);
    await expect(page.getByTestId("payoff-breakeven")).toHaveCount(1);
    await expect(page.getByTestId("payoff-breakeven")).toHaveAttribute("data-price", "1230");
    await expect(page.getByTestId("payoff-unbounded-profit")).toHaveCount(0);

    // Faithful plot, net and gross.
    await plotsFaithfully(page, body.expiry.grid, body.expiry.net);
    await page.getByTestId("payoff-basis-gross").click();
    await plotsFaithfully(page, body.expiry.grid, body.expiry.gross);

    // Reference price (1215) → nearest grid price 1210.
    await expect(readout(page)).toContainText("Underlying ₹1,210.00");
    await expect(page.getByTestId("payoff-readout-net")).toHaveText(`${MINUS}₹2,000.00`);

    // Keyboard: below the lower strike, between, above the upper strike.
    const svg = page.getByTestId("payoff-svg");
    await svg.focus();
    await page.keyboard.press("Home");
    await expect(readout(page)).toContainText("Underlying ₹1,100.00");
    for (let i = 0; i < 5; i++) await page.keyboard.press("ArrowRight");
    await expect(readout(page)).toContainText("Underlying ₹1,150.00");
    await expect(page.getByTestId("payoff-readout-net")).toHaveText(`${MINUS}₹3,000.00`);
    await page.keyboard.press("Shift+ArrowRight");
    await page.keyboard.press("ArrowRight");
    await expect(readout(page)).toContainText("Underlying ₹1,260.00");
    await page.keyboard.press("ArrowLeft");
    await expect(readout(page)).toContainText("Underlying ₹1,250.00");
    await expect(page.getByTestId("payoff-readout-net")).toHaveText("+₹2,000.00");
    await page.keyboard.press("End");
    await page.keyboard.press("ArrowLeft");
    await page.keyboard.press("ArrowLeft");
    await page.keyboard.press("ArrowLeft");
    await page.keyboard.press("ArrowLeft");
    await page.keyboard.press("ArrowLeft");
    await expect(readout(page)).toContainText("Underlying ₹1,350.00");
    await expect(page.getByTestId("payoff-readout-net")).toHaveText("+₹7,000.00");
    await expect(page.getByTestId("payoff-cursor")).toBeVisible();

    // Profit and loss zones are both drawn and both named in words; the loss zone is hatched.
    await expect(page.getByTestId("payoff-zone-profit")).toHaveText("PROFIT");
    await expect(page.getByTestId("payoff-zone-loss")).toHaveText("LOSS");
    await expect(page.getByTestId("payoff-profit-area")).toHaveCount(1);
    await expect(page.getByTestId("payoff-loss-area")).toHaveCount(1);
    await expect(page.getByTestId("payoff-trust")).toContainText("End of day");
    await expect(page.getByTestId("payoff-broker-line")).toContainText("Nothing was sent to a broker");
  });

  test("SG-2 long future: linear, loss not unbounded, profit unbounded, margin warning, no margin figure", async ({ page }) => {
    const seen = await open(page, LONG_FUT);
    await expect(page.getByTestId("payoff-svg")).toBeVisible();
    const body = refPayoff(seen.bodies[0] ?? LONG_FUT.base, LONG_FUT) as { expiry: { grid: number[]; gross: number[]; net: number[] } };
    expect(body.expiry.gross[0]).toBe(-28750); // 1100 → (1100 − 1215) × 250
    expect(body.expiry.gross[body.expiry.grid.indexOf(1300)]).toBe(21250);
    await plotsFaithfully(page, body.expiry.grid, body.expiry.net);

    await expect(fact(page, "maxprofit")).toContainText("Unlimited");
    await expect(fact(page, "maxloss")).toHaveText(`${MINUS}₹3,03,750.00`);
    await expect(page.getByTestId("payoff-unbounded-profit")).toHaveCount(1);
    await expect(page.getByTestId("payoff-unbounded-profit")).toContainText("Profit unbounded");
    await expect(page.getByTestId("payoff-unbounded-loss")).toHaveCount(0);
    await expect(page.getByTestId("payoff-maxloss-line")).toHaveCount(0); // −3,03,750 is far outside the plotted range
    await expect(page.getByTestId("payoff-futures-warning")).toContainText("Futures losses can exceed the initial margin");
    await expect(sum(page, "margin")).toHaveText("—");
    await expect(page.getByTestId("sum-margin-note")).toContainText("no margin source");
    await expect(sum(page, "net-premium")).toHaveText("—");
    await expect(page.getByTestId("payoff-defined-risk")).toHaveCount(0);
    await expect(fact(page, "breakeven")).toHaveText("₹1,215.00");
  });

  test("SG-3 short future: both ends unbounded, both maxima Unlimited", async ({ page }) => {
    const seen = await open(page, SHORT_FUT);
    await expect(page.getByTestId("payoff-svg")).toBeVisible();
    const body = refPayoff(seen.bodies[0] ?? SHORT_FUT.base, SHORT_FUT) as { expiry: { grid: number[]; net: number[] } };
    expect(body.expiry.net[0]).toBe(28750);
    expect(body.expiry.net[body.expiry.net.length - 1]).toBe(-46250); // 1400 → (1215 − 1400) × 250
    await plotsFaithfully(page, body.expiry.grid, body.expiry.net);
    await expect(fact(page, "maxprofit")).toContainText("Unlimited");
    await expect(fact(page, "maxloss")).toContainText("Unlimited");
    await expect(page.getByTestId("payoff-unbounded-profit")).toContainText("Profit unbounded");
    await expect(page.getByTestId("payoff-unbounded-loss")).toContainText("Loss unbounded");
    await expect(page.getByTestId("payoff-futures-warning")).toBeVisible();
    await expect(sum(page, "max-loss")).toHaveText("Unlimited");
  });

  test("SG-4 long put: costs make net differ from gross, both lines faithful, premium at risk", async ({ page }) => {
    const seen = await open(page, LONG_PUT);
    await expect(page.getByTestId("payoff-svg")).toBeVisible();
    const body = refPayoff(seen.bodies[0] ?? LONG_PUT.base, LONG_PUT) as { expiry: { grid: number[]; gross: number[]; net: number[]; breakevens: number[] }; costs: { entry: number; round_trip: number } };
    expect(body.expiry.gross[0]).toBe(7500);
    expect(body.expiry.net[0]).toBe(7460);
    expect(body.expiry.gross[body.expiry.grid.indexOf(1300)]).toBe(-2500);
    expect(body.expiry.net[body.expiry.grid.indexOf(1300)]).toBe(-2540);
    expect(body.costs.entry).toBe(20);
    expect(body.costs.round_trip).toBe(40);
    expect(body.expiry.breakevens).toEqual([1174.6]); // 1170 → 7,460 − … interpolated: 1174.6 hand-computed above

    await plotsFaithfully(page, body.expiry.grid, body.expiry.net);
    await page.getByTestId("payoff-basis-gross").click();
    await plotsFaithfully(page, body.expiry.grid, body.expiry.gross);
    await page.getByTestId("payoff-basis-net").click();

    await expect(fact(page, "maxloss")).toHaveText(`${MINUS}₹2,540.00`);
    await expect(fact(page, "maxprofit")).toHaveText("+₹1,17,460.00");
    await expect(fact(page, "breakeven")).toHaveText("₹1,174.60");
    await expect(page.getByTestId("payoff-maxprofit-line")).toHaveCount(0); // outside the plotted range
    await expect(sum(page, "net-premium")).toHaveText("Debit ₹2,500.00");
    await expect(sum(page, "capital-at-risk")).toHaveText("₹2,540.00");
    await expect(page.getByTestId("cost-entry")).toHaveText("₹20.00");
    await expect(page.getByTestId("cost-exit")).toHaveText("₹20.00");
    await expect(page.getByTestId("cost-round-trip")).toHaveText("₹40.00");
    await expect(page.getByTestId("cost-excluded")).toContainText("taxes, statutory charges, dividends, funding");
    await expect(page.getByTestId("payoff-legs-toggle")).toBeDisabled(); // one leg: nothing to separate
    await expect(page.getByTestId("payoff-caveats")).toHaveCount(0);

    // The readout carries both bases at 1100.
    await page.getByTestId("payoff-svg").focus();
    await page.keyboard.press("Home");
    await expect(page.getByTestId("payoff-readout-gross")).toHaveText("+₹7,500.00");
    await expect(page.getByTestId("payoff-readout-net")).toHaveText("+₹7,460.00");
  });

  test("SG-5 iron condor: two breakevens, defined risk, per-leg overlay, four leg rows", async ({ page }) => {
    const seen = await open(page, IC);
    await expect(page.getByTestId("payoff-svg")).toBeVisible();
    const body = refPayoff(seen.bodies[0] ?? IC.base, IC) as { expiry: { grid: number[]; net: number[]; breakevens: number[]; per_leg: Array<{ gross: number[] }> } };
    expect(Math.max(...body.expiry.net)).toBe(2100);
    expect(Math.min(...body.expiry.net)).toBe(-2900);
    expect(body.expiry.breakevens).toEqual([1129, 1301]);
    await plotsFaithfully(page, body.expiry.grid, body.expiry.net);

    await expect(fact(page, "maxprofit")).toHaveText("+₹2,100.00");
    await expect(fact(page, "maxloss")).toHaveText(`${MINUS}₹2,900.00`);
    await expect(fact(page, "breakeven")).toHaveText("₹1,129.00 · ₹1,301.00");
    await expect(page.getByTestId("payoff-breakeven")).toHaveCount(2);
    await expect(sum(page, "net-premium")).toHaveText("Credit ₹2,100.00");
    await expect(page.getByTestId("payoff-maxprofit-line")).toHaveCount(1);
    await expect(page.getByTestId("payoff-maxloss-line")).toHaveCount(1);

    await expect(page.locator('[data-testid^="payoff-leg-line-"]')).toHaveCount(0);
    await page.getByTestId("payoff-legs-toggle").click();
    await expect(page.locator('[data-testid^="payoff-leg-line-"]')).toHaveCount(4);
    await plotsFaithfully(page, body.expiry.grid, body.expiry.per_leg[2].gross, 0.5, "payoff-leg-line-2");
    await expect(page.getByTestId("payoff-legend")).toContainText("Sell 1 call 1280");

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

test.describe("MOCK — not real data: pre-expiry estimate", () => {
  test("SG-6a no estimate in the answer: the tab is disabled and says why", async ({ page }) => {
    await open(page, BCS);
    await expect(page.getByTestId("payoff-svg")).toBeVisible();
    await expect(page.getByTestId("payoff-mode-pre")).toBeDisabled();
    await expect(page.getByTestId("payoff-mode-expiry")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("payoff-pre-reasons")).toContainText("Pre-expiry estimate unavailable");
    await expect(page.getByTestId("payoff-pre-reasons")).toContainText("No evaluation date was sent");
  });

  test("SG-6b estimate present: enabled, plotted, Greeks in the readout, assumptions stated", async ({ page }) => {
    const fx: Fixture = { ...BCS, pre: true, base: { ...BCS.base, pre_expiry: { date: "2026-10-23", iv_shift_pct: 0, rate_pct: 5.75 } } };
    const seen = await open(page, fx);
    await expect(page.getByTestId("payoff-svg")).toBeVisible();
    await expect(page.getByTestId("payoff-mode-pre")).toBeEnabled();
    await page.getByTestId("payoff-mode-pre").click();
    await expect(page.getByTestId("payoff-chart")).toHaveAttribute("data-mode", "pre");
    const body = refPayoff(seen.bodies[0], fx) as { pre_expiry: { grid: number[]; net: number[]; gross: number[]; greeks: { delta: number[] } } };
    await plotsFaithfully(page, body.pre_expiry.grid, body.pre_expiry.net);
    await page.getByTestId("payoff-basis-gross").click();
    await plotsFaithfully(page, body.pre_expiry.grid, body.pre_expiry.gross);

    // The pre-expiry grid has every second price: 1100, 1120, …; End reads 1400 and its Greeks.
    await page.getByTestId("payoff-svg").focus();
    await page.keyboard.press("End");
    const last = body.pre_expiry.grid.length - 1;
    await expect(readout(page)).toContainText("Underlying ₹1,400.00");
    await expect(page.getByTestId("payoff-readout-gross")).toHaveText(`+₹${(Math.round((1400 - 1215) * 20)).toLocaleString("en-IN")}.00`);
    const greeks = page.getByTestId("payoff-readout-greeks");
    await expect(greeks).toContainText(`Δ ${body.pre_expiry.greeks.delta[last].toFixed(4)}`);
    await expect(greeks).toContainText("Θ −12.50");
    await expect(greeks).toContainText("ρ —"); // null stays a dash
    await expect(page.getByTestId("payoff-pre-note")).toContainText("Black-76 (MOCK), not a guarantee");
    await expect(page.getByTestId("payoff-pre-note")).toContainText("2026-10-23");
    await expect(page.getByTestId("payoff-legs-toggle")).toBeDisabled();
    await expect(page.getByTestId("payoff-unbounded-profit")).toHaveCount(0);
    await expect(page.getByTestId("payoff-maxprofit-line")).toHaveCount(0);
    await page.getByTestId("payoff-mode-expiry").click();
    await expect(page.getByTestId("payoff-maxprofit-line")).toHaveCount(1);
  });
});

// ── SG-7: scenario controls ──────────────────────────────────────────────

test.describe("MOCK — not real data: scenario controls", () => {
  test("SG-7a price, size and reset change the request and the readout; the old answer is dimmed meanwhile", async ({ page }) => {
    const seen = await open(page, BCS, "", { delay: 350 });
    await expect(page.getByTestId("payoff-svg")).toBeVisible();
    await expect(page.getByTestId("payoff-chart")).toHaveAttribute("data-stale", "false");
    expect(seen.bodies[0].scenarios).toBeUndefined();

    await page.getByTestId("scenario-price").fill("1250");
    await expect(page.getByTestId("payoff-chart")).toHaveAttribute("data-stale", "true");
    await expect(page.getByTestId("payoff-scenario-row")).toContainText("Scenario what-if: underlying ₹1,250.00");
    await expect(page.getByTestId("payoff-chart")).toHaveAttribute("data-stale", "false");
    await expect(page.getByTestId("payoff-scenario-row")).toContainText("net +₹2,000.00"); // hand-computed above
    await expect(page.getByTestId("payoff-scenario-point")).toHaveCount(1);
    const last = seen.bodies[seen.bodies.length - 1];
    expect(last.scenarios).toEqual([{ name: "what-if", underlying_price: 1250 }]);

    await page.getByTestId("scenario-size").fill("2");
    const doubled = { ...BCS.facts, max_profit: 14000, max_loss: -6000 };
    // The mock regenerates the grid from the doubled quantity, so the plotted line doubles; the facts are the route's.
    await expect.poll(() => seen.bodies[seen.bodies.length - 1].legs[0].quantity).toBe(2);
    expect(seen.bodies[seen.bodies.length - 1].legs[1].quantity).toBe(2);
    expect(doubled.max_profit).toBe(2 * BCS.facts.max_profit!);
    await expect(page.getByTestId("payoff-scenario-row")).toContainText("net +₹4,000.00");

    // Reset returns to the base position; its answer is already cached, so the screen needs no new request.
    await page.getByTestId("scenario-reset").click();
    await expect(page.getByTestId("payoff-scenario-row")).toHaveCount(0);
    await expect(page.getByTestId("scenario-price")).toHaveValue("");
    await expect(page.getByTestId("scenario-size")).toHaveValue("");
    await expect(page.getByTestId("payoff-chart")).toHaveAttribute("data-stale", "false");
    await page.getByTestId("payoff-svg").focus();
    await page.keyboard.press("End");
    await expect(page.getByTestId("payoff-readout-net")).toHaveText("+₹7,000.00"); // one lot again, not two (14,000)
  });

  test("SG-7b slider moves the what-if price", async ({ page }) => {
    const seen = await open(page, BCS);
    await expect(page.getByTestId("payoff-svg")).toBeVisible();
    await page.getByTestId("scenario-price-slider").fill("1300");
    await expect.poll(() => seen.bodies[seen.bodies.length - 1].scenarios?.[0]?.underlying_price).toBe(1300);
    await expect(page.getByTestId("scenario-price")).toHaveValue("1300");
    await expect(page.getByTestId("payoff-scenario-row")).toContainText("net +₹7,000.00");
  });

  test("SG-7c unsupported inputs are disabled with the reason (futures: no IV; no estimate: no date)", async ({ page }) => {
    await open(page, LONG_FUT);
    await expect(page.getByTestId("payoff-svg")).toBeVisible();
    await expect(page.getByTestId("scenario-iv")).toBeDisabled();
    await expect(page.getByTestId("scenario-iv-reason")).toContainText("options only");
    await expect(page.getByTestId("scenario-date")).toBeDisabled();
    await expect(page.getByTestId("scenario-date-reason")).toContainText("no pre-expiry estimate");
    await expect(page.getByTestId("scenario-size")).toHaveAttribute("placeholder", "1"); // one leg: the leg's own lots
  });

  test("SG-7d options with an estimate: IV and date are enabled, the date is bounded, and they go in the request", async ({ page }) => {
    const fx: Fixture = { ...BCS, pre: true, base: { ...BCS.base, pre_expiry: { date: "2026-10-23", iv_shift_pct: 0 } } };
    const seen = await open(page, fx);
    await expect(page.getByTestId("payoff-svg")).toBeVisible();
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
      valid: false, problems: [{ field: "legs", code: "undefined_risk", message: "A short call with no long call above it has unlimited risk; this release allows defined-risk options only." }],
      warnings: [], calculation_version: "payoff-v1 (MOCK)", expiry: null, pre_expiry: null, costs: null, margin: null, capital_at_risk: null, caveats: [], sent_to_broker: false,
    };
    await open(page, BCS, "", { body });
    await expect(page.getByTestId("payoff-rejected")).toContainText("This structure was rejected");
    await expect(page.getByTestId("payoff-problem")).toContainText("unlimited risk");
    await expect(page.getByTestId("payoff-problem")).toContainText("undefined_risk");
    await expect(page.getByTestId("payoff-svg")).toHaveCount(0);
    await expect(page.getByTestId("payoff-no-chart")).toBeVisible();
    await expect(sum(page, "max-profit")).toHaveText("—");
  });
});

// ── SG-9: unavailable legs ───────────────────────────────────────────────

test.describe("MOCK — not real data: unavailable legs", () => {
  test("SG-9 a leg the estimate could not price shows its reason in the chart tab and the leg row", async ({ page }) => {
    const fx: Fixture = {
      ...BCS, pre: true, base: { ...BCS.base, pre_expiry: { date: "2026-10-23" } },
      unavailable: [{ leg: 1, reason: "No implied volatility for the 1300 call in the bhavcopy." }],
    };
    await open(page, fx);
    await expect(page.getByTestId("payoff-svg")).toBeVisible();
    await page.getByTestId("payoff-mode-pre").click();
    await expect(page.getByTestId("payoff-pre-unavailable")).toContainText("Leg 2 has no estimate: No implied volatility for the 1300 call");
    const rows = page.getByTestId("leg-row");
    await expect(rows.nth(0).getByTestId("leg-unavailable")).toHaveText("—");
    await expect(rows.nth(1).getByTestId("leg-unavailable")).toHaveText("Unavailable");
    await expect(rows.nth(1).getByTestId("leg-unavailable-note")).toContainText("No implied volatility for the 1300 call");
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
    const fx: Fixture = { ...IC, pre: true, base: { ...IC.base, pre_expiry: { date: "2026-10-23" } }, fan: { ...FAN_BASE, scenario: FAN_SCENARIO } };
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
    expect(label).toContain("Maximum profit +₹2,100.00");
    expect(label).toContain(`Maximum loss ${MINUS}₹2,900.00`);
    expect(label).toContain("Breakeven at ₹1,129.00 and ₹1,301.00");
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
