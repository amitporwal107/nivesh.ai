/**
 * One-screen Copilot app — Smart trading desk: the Strategy Builder screen (PRD §16, §17.3;
 * screens/tradingdesk/strategy/StrategyBuilder and its parts, reached at ?tab=more&view=strategy).
 *
 * MOCK — not real data. Every /api response here is generated or loaded in this file. The plan payloads in
 * e2e/fixtures/strategy-plan-*.json are the REAL output of the plan builder (backend/services/strategy_plan,
 * the fixture world of backend/tests/test_strategy_plan.py: RELIANCE-like, close 1200 on 2026-10-19, ATR 20,
 * lot 250, chain 2026-11-24, put wall 1150, call wall 1250), dumped to JSON, so the screen is tested against
 * the exact shape the route sends; their sources are labelled "MOCK ..." inside. Expected figures are read
 * from the payload, and the headline ones are HAND-COMPUTED here:
 *   cash      208 shares  = min(floor(10,000 / 40 risk a share), floor(1,000,000 x 25% / 1,200)) = min(250, 208)
 *   futures   1 lot       = floor(20,000 / (53 x 250 = 13,250))                                   = 1
 *   spread    2 lots      = floor(10,000 / 3,591.25 net loss of one lot)                          = 2;
 *             debit 52 - 38 = 14 a unit, width 50: max loss 14 x 250 x 2 = 7,000, max profit (50 - 14) x 250 x 2 = 18,000, breakeven 1,214
 * The what-if payoff route is answered by `payoffFor`, a small reference calculation written for this spec.
 *
 * Cases: SB-1 More destination, URL, inputs and validation · SB-2 cash plan · SB-3 evidence ledger · SB-4 compare
 * and select · SB-5 options selection, stale chain · SB-6 sizing incomplete · SB-7 wait / no trade / insufficient /
 * partial sources · SB-8 graphs recalculate · SB-9 save, list, open, delete · SB-10 paper trades · SB-11 Copilot ·
 * SB-12 failures · SB-13 persona, 390px, no order controls.
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { test, expect, type Page, type Route } from "@playwright/test";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DESK = "/v5/app/trader/desk";
const BUILDER = `${DESK}?tab=more&view=strategy`;
const fixture = (n: string) => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", `strategy-plan-${n}.json`), "utf-8"));
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const MINUS = "−";

type Plan = ReturnType<typeof fixture>;
const cand = (p: Plan, id: string) => p.candidates.find((c: { id: string }) => c.id === id);
const inr = (n: number) => `₹${new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n)}`;

// ── the what-if payoff, a reference calculation for the spec ─────────────

interface PLeg { kind: string; side: string; quantity: number; lot_size: number; entry_price: number; expiry: string | null; strike: number | null; option_type: string | null }
interface PReq { underlying: string; reference_price: number; legs: PLeg[]; grid?: { min: number; max: number; points: number }; scenarios?: Array<{ name: string; underlying_price: number }>; pre_expiry?: { date: string } }
const r2 = (n: number) => Math.round(n * 100) / 100;
function legAt(l: PLeg, s: number) {
  const u = l.quantity * (l.kind === "cash" ? 1 : l.lot_size);
  const sg = l.side === "buy" ? 1 : -1;
  if (l.kind !== "option") return sg * (s - l.entry_price) * u;
  const iv = l.option_type === "call" ? Math.max(s - (l.strike as number), 0) : Math.max((l.strike as number) - s, 0);
  return sg * (iv - l.entry_price) * u;
}
function payoffFor(req: PReq) {
  const g = req.grid ?? { min: req.reference_price * 0.8, max: req.reference_price * 1.2, points: 41 };
  const grid = Array.from({ length: g.points }, (_, i) => g.min + ((g.max - g.min) * i) / (g.points - 1));
  const at = (s: number) => req.legs.reduce((a, l) => a + legAt(l, s), 0);
  const gross = grid.map((s) => r2(at(s)));
  const strikes = req.legs.map((l) => l.strike ?? 0).filter(Boolean);
  const probe = [0, ...strikes, g.max];
  const vals = probe.map(at);
  const unitsUp = req.legs.reduce((a, l) => a + (l.kind === "option" && l.option_type === "put" ? 0 : (l.side === "buy" ? 1 : -1) * l.quantity * (l.kind === "cash" ? 1 : l.lot_size)), 0);
  const pre = req.pre_expiry ? { date: req.pre_expiry.date, model: "Black-76 (MOCK)", assumptions: { model: "Black-76", rate_pct: 5.75 }, grid: grid.map(r2), gross: gross.map((x) => r2(x * 0.5)), net: gross.map((x) => r2(x * 0.5 - 10)), greeks: { delta: 1, gamma: 0, theta: -1, vega: 1, rho: 0 }, per_leg_greeks: [], unavailable: [] } : null;
  return {
    valid: true, problems: [], warnings: [], calculation_version: "payoff-v1 (MOCK)", underlying: req.underlying, reference_price: req.reference_price,
    expiry: {
      grid: grid.map(r2), gross, net: gross.map((x) => r2(x - 40)), per_leg: req.legs.map((l, i) => ({ index: i, label: `leg ${i}`, gross: grid.map((s) => r2(legAt(l, s))) })),
      breakevens: [], max_profit: unitsUp > 0 ? null : r2(Math.max(...vals)), max_loss: unitsUp < 0 ? null : r2(Math.min(...vals)),
      profit_unbounded: unitsUp > 0, loss_unbounded: unitsUp < 0, net_premium: 0,
      scenarios: (req.scenarios ?? []).map((s) => ({ name: s.name, underlying_price: s.underlying_price, gross: r2(at(s.underlying_price)), net: r2(at(s.underlying_price) - 40) })),
    },
    pre_expiry: pre,
    costs: { model: "MOCK cost model", entry: 20, exit_at_expiry: 20, round_trip: 40, excluded: ["taxes"] },
    margin: null, margin_reason: "No margin source exists in this system (MOCK).", capital_at_risk: 1000, capital_at_risk_basis: "MOCK", loss_can_exceed_margin: false, caveats: [], sent_to_broker: false,
  };
}

// ── page plumbing ────────────────────────────────────────────────────────

interface Opts {
  plan?: string;
  /** Reply to POST /plan instead of the fixture. */
  planReply?: { status: number; body: unknown };
  saved?: Array<{ id: string; plan: Plan; saved_at: string }>;
  saveReply?: { status: number; body: unknown };
  paperReply?: { status: number; body: unknown };
}
interface State {
  builds: Array<Record<string, unknown>>; saves: Array<{ plan: Plan }>; paid: Array<Record<string, any>>; strat: Array<Record<string, any>>; deletes: string[]; payoffs: PReq[]; streams: Array<{ message: string }>;
  stored: Array<{ id: string; plan: Plan; saved_at: string }>; writes: string[];
}

const RUN = { model: "v4", refit: "monthly", status: "final", data_as_of: "2026-10-19", target_session: "2026-10-20", frozen_at: "2026-10-19T20:50:22+05:30", git_sha: "0fix000", universe_size: 1000, scored: 994, input_count: 84, train_rows: 366080, train_end: "2026-08-31", counts_toward_verdict: true, skipped_holidays: [] };
const RECORD = { window_label: "Jan–Aug 2025", sessions: 165, base_rate: 0.0812, top10_hit_rate: 0.3103, bands: [] };

function bars() {
  const out: Array<[string, number, number, number, number, number]> = [];
  const days: string[] = [];
  for (let t = Date.parse("2026-10-19T00:00:00Z"); days.length < 120; t -= 86_400_000) {
    const wd = new Date(t).getUTCDay();
    if (wd !== 0 && wd !== 6) days.unshift(new Date(t).toISOString().slice(0, 10));
  }
  days.forEach((d, i) => { const c = r2(1100 + i * 0.84 + 12 * Math.sin(i / 6)); out.push([d, c - 2, c + 6, c - 7, c, 100000 + i * 100]); });
  out[out.length - 1][4] = 1200;
  return out;
}

async function setup(page: Page, o: Opts = {}): Promise<State> {
  const st: State = { builds: [], saves: [], paid: [], strat: [], deletes: [], payoffs: [], streams: [], stored: [...(o.saved ?? [])], writes: [] };
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  page.on("request", (r) => { if (r.method() !== "GET" && /\/api\//.test(new URL(r.url()).pathname)) st.writes.push(`${r.method()} ${new URL(r.url()).pathname}`); });
  await page.route("**/api/positional/**", (r) => json(r, { detail: "not mocked here" }, 404));
  await page.route("**/api/move-odds/latest*", (r) => json(r, { data: { status: "final", head: "p_up5_1d", expected_session: "2026-10-20", base_rate: 0.0758, run: RUN, rows: [], record: RECORD, live_record: { sessions: 0, top10_hits: null, touched: null, graded_rows: null, last_target: null, last_top10_hits: null, last_touched: null, last_graded_rows: null }, limits: { not_used: [] } } }));
  await page.route("**/api/move-odds/stocks/*", (r) => json(r, { detail: "not in the run" }, 404));
  await page.route("**/api/research/chart-live/*/ohlcv*", (r) => json(r, { symbol: "RELIANCE", timeframe: "1D", bars: bars(), data_quality_status: "VALID", pit_status: "PIT_UNVERIFIED", findings: [], provenance: { provider: "MOCK nidp.prices_eod_adjusted", series: "EQ", adjustment_status: "SPLIT_BONUS_ADJUSTED", last_bar_date: "2026-10-19", source_mode: "live", last_event_type: null } }));
  await page.route("**/api/desk/paper-trades*", async (r) => {
    if (r.request().method() === "GET") return json(r, { as_of: null, trades: [], summary: null });
    const body = r.request().postDataJSON() as Record<string, any>;
    if (o.paperReply) return json(r, o.paperReply.body, o.paperReply.status);
    if (body.kind === "strategy") { st.strat.push(body); return json(r, { trade: { id: "st-1", status: "open", ...body } }, 201); }
    st.paid.push(body);
    return json(r, { trade: { id: "pt-1", status: "open", ...body, opened_at: "2026-10-20T05:00:00+00:00" } }, 201);
  });
  await page.route("**/api/desk/strategy/payoff", (r) => { const b = r.request().postDataJSON() as PReq; st.payoffs.push(b); return json(r, payoffFor(b)); });
  await page.route("**/api/desk/strategy/plan", (r) => {
    st.builds.push(r.request().postDataJSON() as Record<string, unknown>);
    if (o.planReply) return json(r, o.planReply.body, o.planReply.status);
    return json(r, fixture(o.plan ?? "cash"));
  });
  const summary = (d: { id: string; plan: Plan; saved_at: string }) => ({
    id: d.id, plan_id: d.plan.plan_id, saved_at: d.saved_at, underlying: d.plan.summary.underlying, direction: d.plan.summary.direction, horizon: d.plan.summary.horizon,
    segment: d.plan.summary.segment, family: d.plan.summary.family, status: d.plan.status, data_as_of: d.plan.summary.data_as_of, rules_version: d.plan.rules_version, lifecycle: "draft", sent_to_broker: false,
  });
  await page.route("**/api/desk/strategy/plans", (r) => {
    if (r.request().method() === "POST") {
      const body = r.request().postDataJSON() as { plan: Plan };
      st.saves.push(body);
      if (o.saveReply) return json(r, o.saveReply.body, o.saveReply.status);
      const doc = { id: `sv-${st.stored.length + 1}`, plan: body.plan, saved_at: "2026-10-20T05:00:00+00:00" };
      st.stored.unshift(doc);
      return json(r, { ...doc, sent_to_broker: false }, 201);
    }
    return json(r, { plans: st.stored.map(summary), count: st.stored.length, limit: 100, max_saved: 200 });
  });
  await page.route(/\/api\/desk\/strategy\/plans\/[^/]+$/, (r) => {
    const id = new URL(r.request().url()).pathname.split("/").pop() as string;
    const i = st.stored.findIndex((d) => d.id === id);
    if (r.request().method() === "DELETE") {
      if (i < 0) return json(r, { detail: "plan_not_found" }, 404);
      st.stored.splice(i, 1); st.deletes.push(id);
      return json(r, { deleted: true, id, note: "This deleted only your saved copy of the plan. Nothing else changed and nothing was sent to a broker." });
    }
    if (i < 0) return json(r, { detail: "plan_not_found" }, 404);
    return json(r, { ...st.stored[i], sent_to_broker: false });
  });
  // The dock (Copilot) and the lists.
  const msgs: Record<string, any[]> = {};
  await page.route("**/api/chat/sessions", (r) => (r.request().method() === "POST" ? json(r, { session_id: "desk1", id: "desk1" }) : json(r, [])));
  await page.route("**/api/chat/messages*", (r) => json(r, msgs[new URL(r.request().url()).searchParams.get("session_id") ?? ""] ?? []));
  await page.route("**/api/chat/suggest-queries*", (r) => json(r, { suggestions: [] }));
  await page.route("**/api/chat/stream", (r) => {
    const b = r.request().postDataJSON() as { message: string; session_id?: string };
    st.streams.push(b);
    const sid = b.session_id ?? "desk1";
    (msgs[sid] ??= []).push({ message_id: "u1", session_id: sid, role: "user", content: b.message, created_at: "2026-10-20T05:00:00Z" }, { message_id: "a1", session_id: sid, role: "assistant", content: "MOCK answer.", created_at: "2026-10-20T05:00:00Z" });
    const frames = [{ type: "route", agent: "market_analyst", confidence: 0.9 }, { type: "token", content: "MOCK answer." }, { type: "done", content: "MOCK answer.", follow_ups: [] }];
    return r.fulfill({ status: 200, contentType: "text/event-stream", body: frames.map((f) => `data: ${JSON.stringify(f)}\n\n`).join("") });
  });
  const L = (id: string, n: string) => ({ watchlist_id: id, name: n, symbol_count: 1, is_starter: false, seeded_from: null, created_at: "2026-10-01T10:00:00+00:00", updated_at: "2026-10-10T10:00:00+00:00" });
  await page.route("**/api/watchlists", (r) => json(r, { lists: [L("wl1", "Swing ideas")], limits: { max_lists: 20, max_symbols: 50 }, starter_pending: false }));
  await page.route("**/api/desk/alerts*", (r) => json(r, { as_of: null, alerts: [] }));
  return st;
}

const open = async (page: Page, o: Opts = {}, query = "&sym=RELIANCE&direction=bullish&instrument=cash") => {
  const st = await setup(page, o);
  await page.goto(`${BUILDER}${query}`);
  return st;
};
const build = async (page: Page) => { await page.getByTestId("build-plan").click(); await expect(page.getByTestId("plan-view")).toBeVisible(); };
async function sideways(page: Page) {
  return page.evaluate(() => {
    const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
    return { doc: document.documentElement.scrollWidth - window.innerWidth, scroll: sc ? sc.scrollWidth - sc.clientWidth : 0 };
  });
}

// ── SB-1 ─────────────────────────────────────────────────────────────────

test.describe("MOCK — not real data: Strategy Builder", () => {
  test("SB-1 More lists it with its note; the URL carries sym, direction, instrument; intraday is disabled with its reason; defaults are blank until built", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await setup(page);
    await page.goto(`${DESK}?tab=more`);
    const item = page.getByTestId("desk-more-item-strategy");
    await expect(item).toContainText("Strategy Builder");
    await expect(item).toContainText("Cash, futures and options plans for one stock, with the evidence and the payoff");
    await item.click();
    await expect(page).toHaveURL(/tab=more/);
    await expect(page).toHaveURL(/view=strategy/);
    // With no stock in the URL the Builder opens on the AI opportunities board (spec -strategy-ideas); One stock is the other mode.
    await expect(page.getByTestId("builder-mode-ideas")).toHaveAttribute("aria-pressed", "true");
    await page.getByTestId("builder-mode-stock").click();
    await expect(page).toHaveURL(/mode=stock/);
    await expect(page.getByTestId("strategy-builder")).toBeVisible();
    await expect(page.getByTestId("builder-empty")).toContainText("No plan yet");
    await expect(page.getByTestId("desk-more-strategy")).toHaveAttribute("aria-pressed", "true");

    // A deep link preselects the stock, the direction and the instrument.
    await page.goto(`${BUILDER}&sym=RELIANCE&direction=bearish&instrument=futures&horizon=longer_term`);
    await expect(page.getByTestId("in-symbol")).toHaveValue("RELIANCE");
    await expect(page.getByTestId("in-direction-bearish")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("in-instrument-futures")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("in-horizon-longer_term")).toHaveAttribute("aria-pressed", "true");
    const intraday = page.getByTestId("in-horizon-intraday");
    await expect(intraday).toBeDisabled();
    await expect(intraday).toContainText("end-of-day data only");
    await expect(page.getByTestId("defaults-applied")).toHaveCount(0);
  });

  test("SB-1b the browser checks the route's limits and writes no request; the route's 422 problems show per field", async ({ page }) => {
    const st = await open(page, {}, "&sym=RELIANCE");
    await page.getByTestId("build-plan").click();
    await expect(page.getByTestId("field-direction").getByTestId("problem-direction")).toContainText("Choose a direction");
    await page.getByTestId("in-direction-bullish").click();
    await page.getByTestId("in-symbol").fill("BAD SYMBOL!");
    await page.getByTestId("in-risk-mode-pct").click();
    await page.getByTestId("in-risk").fill("150");
    await page.getByTestId("in-alloc").fill("0");
    await page.getByTestId("in-minrr").fill("abc");
    await page.getByTestId("in-expiry").fill("26-11-2026");
    await page.getByTestId("in-horizon-days").fill("251");
    await page.getByTestId("build-plan").click();
    await expect(page.getByTestId("problem-underlying")).toContainText("NSE symbol");
    await expect(page.getByTestId("field-risk").getByTestId("problem-risk")).toContainText("at most 100");
    await expect(page.getByTestId("problem-max_allocation_pct")).toBeVisible();
    await expect(page.getByTestId("problem-min_reward_risk")).toBeVisible();
    await expect(page.getByTestId("problem-expiry")).toContainText("YYYY-MM-DD");
    await expect(page.getByTestId("problem-horizon_days")).toContainText("1 to 250");
    expect(st.builds).toHaveLength(0);

    // A request the browser accepts but the route refuses: its problems land on the fields they name.
    const body = { detail: { code: "invalid_input", problems: [{ field: "min_reward_risk", code: "bad_min_reward_risk", message: "min_reward_risk must be a number above 0 and at most 100." }, { field: "costs", code: "bad_costs", message: "costs must be an object." }] } };
    await page.unroute("**/api/desk/strategy/plan");
    await page.route("**/api/desk/strategy/plan", (r) => json(r, body, 422));
    await page.getByTestId("in-symbol").fill("RELIANCE");
    await page.getByTestId("in-risk-mode-inr").click();
    await page.getByTestId("in-risk").fill("");
    await page.getByTestId("in-alloc").fill("");
    await page.getByTestId("in-minrr").fill("");
    await page.getByTestId("in-expiry").fill("");
    await page.getByTestId("in-horizon-days").fill("");
    await page.getByTestId("build-plan").click();
    await expect(page.getByTestId("problem-min_reward_risk")).toContainText("above 0 and at most 100");
    await expect(page.getByTestId("problems-other")).toContainText("costs must be an object");
    await expect(page.getByTestId("plan-view")).toHaveCount(0);
  });

  // ── SB-2 ───────────────────────────────────────────────────────────────

  test("SB-2 the cash plan: request body, summary strip, four headline fields, no confidence number, withheld model estimate, defaults as chips", async ({ page }) => {
    const p = fixture("cash");
    const st = await open(page, { plan: "cash" });
    await page.getByTestId("in-capital").fill("10,00,000");
    await page.getByTestId("in-risk").fill("10000");
    await build(page);
    expect(st.builds[0]).toEqual({ underlying: "RELIANCE", direction: "bullish", instrument: "cash", capital: 1000000, risk_budget_inr: 10000 });
    await expect(page).toHaveURL(/build=1/);

    await expect(page.getByTestId("plan-title")).toHaveText("RELIANCE");
    await expect(page.getByTestId("plan-status")).toContainText("Plan");
    await expect(page.getByTestId("plan-status")).toHaveAttribute("data-status", "plan");
    await expect(page.getByTestId("plan-asof")).toContainText("Data as of 19 Oct 2026 · end of day");
    await expect(page.getByTestId("plan-versions")).toContainText(`Rules ${p.rules_version}`);
    await expect(page.getByTestId("plan-versions")).toContainText(`calculation ${p.calculation_version}`);
    await expect(page.getByTestId("plan-versions")).toContainText(p.plan_id);
    await expect(page.getByTestId("plan-trust")).toHaveAttribute("data-mode", "eod");
    await expect(page.getByTestId("plan-trust")).not.toContainText("Live");

    await expect(page.getByTestId("head-technical-value")).toHaveText("Supportive");
    await expect(page.getByTestId("head-fundamental")).toContainText("context only");
    await expect(page.getByTestId("head-fundamental-missing")).toContainText("analyst estimates, cash flow quality, ownership changes");
    await expect(page.getByTestId("head-data-value")).toHaveText("Complete");
    await expect(page.getByTestId("head-data")).toContainText("5 of 41 evidence items unavailable");
    // The model estimate: the desk's one gate, never a number.
    await expect(page.getByTestId("head-model-value")).toHaveText("Withheld");
    await expect(page.getByTestId("head-model-gate")).toContainText("does not mark these estimates as calibrated");
    await expect(page.getByTestId("head-model-plan")).toContainText("no calibrated probability model exists");
    await expect(page.getByTestId("head-model-evidence")).toContainText("Move-odds v4");
    await expect(page.getByTestId("head-model-evidence")).toContainText("Jan–Aug 2025");
    await expect(page.getByTestId("head-no-confidence")).toContainText("No single confidence number");
    await expect(page.getByTestId("plan-headline")).not.toContainText(/confidence:\s*\d|\d+\s*%\s*confidence/i);

    // Defaults the route applied, as chips with the plan's own values.
    const chips = page.getByTestId("defaults-applied");
    for (const k of ["horizon_days", "max_allocation_pct", "min_reward_risk", "avoid_events", "allow_multi_leg"]) await expect(chips.getByTestId(`default-chip-${k}`)).toBeVisible();
    await expect(chips.getByTestId("default-input-max_allocation_pct")).toHaveValue("25");
    await expect(chips.getByTestId("default-input-min_reward_risk")).toHaveValue("1.5");
    await expect(chips.getByTestId("default-input-horizon_days")).toHaveValue("10");
    // Changing a chip and building again sends the changed value.
    await chips.getByTestId("default-input-min_reward_risk").fill("1.8");
    await page.getByTestId("build-plan").click();
    await expect.poll(() => st.builds.length).toBe(2);
    expect(st.builds[1]).toMatchObject({ min_reward_risk: 1.8 });

    // The selected candidate's numbers are the payload's, and the hand-computed ones.
    const c = cand(p, "cash:breakout_continuation");
    await expect(page.getByTestId("entry-trigger")).toContainText("1,200.00");
    await expect(page.getByTestId("entry-logic")).toContainText("Last close 1200");
    await expect(page.getByTestId("inv-technical")).toContainText("1,160.00");
    await expect(page.getByTestId("inv-execution")).toContainText("1,160.00");
    await expect(page.getByTestId("inv-execution")).toContainText("A stop order does not guarantee the fill");
    await expect(page.getByTestId("target-conservative")).toContainText("1,220.00");
    await expect(page.getByTestId("target-base")).toContainText("1,280.00");
    await expect(page.getByTestId("target-base")).toContainText("gates the reward : risk test");
    await expect(page.getByTestId("target-optimistic")).toContainText("1,320.00");
    await expect(page.getByTestId("rr-gross")).toContainText("2.00 : 1");
    await expect(page.getByTestId("rr-net")).toContainText("1.90 : 1");
    expect(c.risk_reward.gross).toBe(2);
    await expect(page.getByTestId("sizing-qty")).toContainText("208");
    await expect(page.getByTestId("sizing-formula")).toContainText("floor(risk budget / risk per unit)");
    await expect(page.getByTestId("margin")).toContainText("—");
    await expect(page.getByTestId("margin")).toContainText("No margin source exists");
    await expect(page.getByTestId("validation-status")).toHaveText("Not validated");
    await expect(page.getByTestId("validation-record")).toContainText("in-sample, price-only");
    await expect(page.getByTestId("validation-status")).not.toHaveText(/^validated$/i);
  });

  // ── SB-3 ───────────────────────────────────────────────────────────────

  test("SB-3 evidence ledger: seven groups collapsed with counts, items carry direction (word and shape), source and as-of; unavailable items say why", async ({ page }) => {
    const p = fixture("cash");
    await open(page, { plan: "cash" });
    await build(page);
    const groups = ["market_context", "technical", "fundamental", "catalysts", "derivatives", "validation", "portfolio_fit"];
    for (const g of groups) await expect(page.getByTestId(`ev-group-${g}-toggle`)).toHaveAttribute("aria-expanded", "false");
    await expect(page.getByTestId("ev-group-technical-counts")).toContainText("▲ 5 · ▼ 0 · ● 4 · ∅ 0");
    await expect(page.getByTestId("ev-group-fundamental-counts")).toContainText("∅ 3");
    await expect(page.getByTestId("ev-technical-momentum")).toHaveCount(0);
    await page.getByTestId("ev-group-technical-toggle").click();
    await expect(page.getByTestId("ev-group-technical-toggle")).toHaveAttribute("aria-expanded", "true");
    const mom = page.getByTestId("ev-technical-momentum");
    await expect(mom).toHaveAttribute("data-direction", "supports");
    await expect(mom.getByTestId("ev-direction")).toHaveText("▲ Supports");
    await expect(mom.getByTestId("ev-interpretation")).toContainText("MACD histogram +1.50, 20-day change +4.00%");
    await expect(mom.getByTestId("ev-source")).toContainText("as of 19 Oct 2026");
    await page.getByTestId("ev-group-fundamental-toggle").click();
    const miss = page.getByTestId("ev-fundamental-analyst_estimates");
    await expect(miss.getByTestId("ev-direction")).toHaveText("∅ Unavailable");
    await expect(miss.getByTestId("ev-interpretation")).toContainText("Why not: Not available: the data platform holds no analyst estimates");
    await expect(miss.getByTestId("ev-source")).toContainText("No source");
    await page.getByTestId("ev-toggle-all").click();
    for (const g of groups) await expect(page.getByTestId(`ev-group-${g}-toggle`)).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByTestId("thesis-supports")).toContainText("Nifty is up against its 50-session average");
    await expect(page.getByTestId("thesis-conflicts")).toContainText("Nothing on record conflicts");
    expect(p.evidence.length).toBe(41);
    await expect(page.locator('[data-testid^="ev-"][data-direction]')).toHaveCount(41);
  });

  // ── SB-4, SB-5 ─────────────────────────────────────────────────────────

  test("SB-4 compare all: the table lists the four candidates; a not-viable row shows reasons, not numbers; selecting a row selects the candidate", async ({ page }) => {
    const p = fixture("all");
    await open(page, { plan: "all" }, "&sym=RELIANCE&direction=bullish");
    await build(page);
    await expect(page.locator('[data-testid^="cmp-row-"]')).toHaveCount(4);
    // The preferred (highest net reward : risk) is selected first: the bull call spread (2.54 net).
    await expect(page.getByTestId("candidate")).toHaveAttribute("data-id", "options:bull_call_spread");
    const spread = page.getByTestId("cmp-row-options:bull_call_spread");
    await expect(spread.getByTestId("cmp-rr")).toContainText("2.54 : 1 / 2.57 : 1");
    await expect(spread.getByTestId("cmp-breakeven")).toContainText("1,214.00");
    await expect(spread).toHaveAttribute("data-selected", "true");
    const lc = page.getByTestId("cmp-row-options:long_call");
    await expect(lc.getByTestId("cmp-maxloss")).toHaveText("—");
    await expect(lc.getByTestId("cmp-rr")).toHaveText("—");
    await expect(lc.getByTestId("cmp-why")).toContainText("Reward : risk -0.04 at the base level is below the minimum 0.5");
    // Select the futures row.
    await page.getByTestId("cmp-select-futures:long_buildup_continuation").click();
    await expect(page.getByTestId("candidate")).toHaveAttribute("data-id", "futures:long_buildup_continuation");
    await expect(page.getByTestId("sizing-qty")).toContainText("1 lots");
    await expect(page.getByTestId("warn-futures")).toContainText("Futures losses can exceed the initial margin");
    await expect(page.getByTestId("inv-technical")).toContainText("1,150.00");
    // A no-trade candidate shows its reasons and no figures, no graphs, no paper trade.
    await page.getByTestId("cmp-select-options:long_call").click();
    await expect(page.getByTestId("cand-status")).toContainText("No trade");
    await expect(page.getByTestId("cand-reasons")).toContainText("reward_risk_below_minimum");
    await expect(page.getByTestId("cand-no-numbers")).toBeVisible();
    await expect(page.getByTestId("cand-sizing")).toHaveCount(0);
    await expect(page.getByTestId("plan-graphs")).toHaveCount(0);
    await expect(page.getByTestId("act-paper")).toBeDisabled();
    await expect(page.getByTestId("paper-blocked")).toContainText('This candidate is "no trade"');
    expect(p.alternatives).toHaveLength(4);
  });

  test("SB-5 options selection: expiries and strikes with source and as-of, why chosen, alternatives compared; the stale chain is labelled and cannot be paper traded", async ({ page }) => {
    await open(page, { plan: "options" }, "&sym=RELIANCE&direction=bullish&instrument=options");
    await build(page);
    const sel = page.getByTestId("cand-options");
    await expect(sel.getByTestId("sel-expiry")).toContainText("24 Nov 2026 (36 days)");
    await expect(sel.getByTestId("sel-expiries")).toContainText("27 Oct 2026 (8 d)");
    await expect(sel.getByTestId("sel-strikes")).toHaveText("1,100 · 1,150 · 1,200 · 1,250 · 1,300");
    await expect(sel.getByTestId("sel-chosen")).toContainText("long 1,200");
    await expect(sel.getByTestId("sel-chosen")).toContainText("short 1,250");
    await expect(sel.getByTestId("sel-source")).toContainText("NSE F&O bhavcopy via /api/fno/RELIANCE/chain, as of 2026-10-19 (end of day)");
    await expect(sel.getByTestId("sel-why")).toContainText("call wall");
    await expect(sel.getByTestId("sel-alternatives")).toContainText("long 1,200 · short 1,300");
    await expect(sel.getByTestId("sel-alternatives")).toContainText("Short 1300 instead");
    await expect(sel.getByTestId("sel-legs")).toContainText("Buy call 1,200");
    await expect(sel.getByTestId("sel-flags")).toContainText("none flagged");
    await expect(page.getByTestId("cand-stale")).toHaveCount(0);
    await expect(page.getByTestId("sizing-qty")).toContainText("2 lots");
    await expect(page.getByTestId("sum-max-loss")).toContainText("7,000.00");
    await expect(page.getByTestId("sum-max-profit")).toContainText("18,000.00");
    await expect(page.getByTestId("sum-breakevens")).toContainText("1,214.00");

    // A stale chain: the strike is delayed/historical, not current and not actionable.
    await open(page, { plan: "stalechain" }, "&sym=RELIANCE&direction=bullish&instrument=options");
    await build(page);
    await expect(page.getByTestId("plan-status")).toContainText("Wait for confirmation");
    await expect(page.getByTestId("plan-status-reasons")).toContainText("delayed/historical, not a current actionable strike");
    await expect(page.getByTestId("cmp-row-options:bull_call_spread")).toHaveAttribute("data-status", "wait");
    await page.getByTestId("cmp-select-options:bull_call_spread").click();
    await expect(page.getByTestId("cand-no-numbers")).toContainText("waiting for confirmation");
  });

  test("SB-6 sizing incomplete: the formula and the missing inputs, no quantity, and no paper trade", async ({ page }) => {
    await open(page, { plan: "incomplete" });
    await build(page);
    const c = page.getByTestId("candidate");
    await expect(c).toHaveAttribute("data-id", "cash:breakout_continuation");
    // This candidate is a no-trade in the fixture (1 share fails the minimum reward : risk), so check the plan's sizing block directly.
    const p = fixture("incomplete");
    const sz = cand(p, "cash:breakout_continuation").sizing;
    expect(sz.status).toBe("incomplete");
    expect(sz.quantity).toBeNull();
    await expect(page.getByTestId("plan-status")).toContainText("No trade");
    await expect(page.getByTestId("cand-no-numbers")).toBeVisible();
    await expect(page.getByTestId("act-paper")).toBeDisabled();
  });

  test("SB-6b viable plan with a missing risk budget: incomplete sizing shows the missing inputs and no quantity; paper trade is off for it", async ({ page }) => {
    // MOCK — the cash plan with its sizing made incomplete the way the builder does it (backend test_cash_incomplete_sizing).
    const p = fixture("cash");
    const c = cand(p, "cash:breakout_continuation");
    c.sizing = { ...c.sizing, status: "incomplete", quantity: null, units: null, risk_budget_inr: null, capital_inr: null, missing: ["risk_budget_inr (or risk_pct together with capital)", "capital"] };
    c.legs[0].quantity = 1;
    await setup(page, { planReply: { status: 200, body: p } });
    await page.goto(`${BUILDER}&sym=RELIANCE&direction=bullish&instrument=cash`);
    await build(page);
    const inc = page.getByTestId("sizing-incomplete");
    await expect(inc).toContainText("Sizing is incomplete: no quantity is shown.");
    await expect(inc).toContainText("risk_budget_inr (or risk_pct together with capital); capital");
    await expect(page.getByTestId("sizing-qty")).toHaveCount(0);
    await expect(page.getByTestId("sizing-formula")).toContainText("floor(risk budget / risk per unit)");
    await expect(page.getByTestId("act-paper")).toBeDisabled();
    await expect(page.getByTestId("paper-blocked")).toContainText("Sizing is incomplete, so there is no quantity to record");
  });

  // ── SB-7 ───────────────────────────────────────────────────────────────

  for (const [name, status, word, glyph] of [
    ["notrade", "no_trade", "No trade", "✕"], ["wait", "wait", "Wait for confirmation", "◔"], ["insufficient", "insufficient_data", "Insufficient data", "?"],
  ] as const) {
    test(`SB-7 status ${status}: the pill says it in words and a shape, the reasons and what would change them are listed, and no plan figures are drawn`, async ({ page }) => {
      const p = fixture(name);
      await open(page, { plan: name }, "&sym=RELIANCE&direction=bullish");
      await build(page);
      const pill = page.getByTestId("plan-status");
      await expect(pill).toHaveAttribute("data-status", status);
      await expect(pill).toContainText(word);
      await expect(pill).toContainText(glyph);
      const reasons = page.getByTestId("plan-status-reasons");
      for (const r of p.status_reasons) await expect(reasons).toContainText(r.message);
      await expect(page.getByTestId("plan-would-change")).toContainText(p.would_change_if[0].replace(/^[a-z_]+: /, ""));
      await expect(page.getByTestId("plan-graphs")).toHaveCount(0);
      await expect(page.getByTestId("act-paper")).toBeDisabled();
      if (name === "insufficient") {
        await expect(page.getByTestId("compare-empty")).toBeVisible();
        await expect(page.getByTestId("candidate")).toHaveCount(0);
        await expect(page.getByTestId("head-technical-value")).toHaveText("Partial");
      }
      if (name === "wait") {
        await expect(page.getByTestId("entry-logic")).toContainText("Wait for a close above 1195 on volume at least 1.5x average");
        await expect(page.getByTestId("cand-sizing")).toHaveCount(0);
      }
      if (name === "notrade") {
        await expect(page.getByTestId("cmp-row-cash:breakout_continuation").getByTestId("cmp-maxloss")).toHaveText("—");
        await expect(page.getByTestId("cmp-row-cash:breakout_continuation").getByTestId("cmp-why")).toContainText("below the 10 Cr liquidity gate");
      }
    });
  }

  test("SB-7b partial sources: a source that did not answer is listed under the summary and its evidence is unavailable, never neutral", async ({ page }) => {
    await open(page, { plan: "partial" });
    await build(page);
    const part = page.getByTestId("plan-partial");
    await expect(part.getByTestId("partial-peers")).toContainText("did not answer (upstream_unavailable)");
    await expect(part.getByTestId("partial-financials")).toBeVisible();
    await expect(part).toContainText("never as neutral");
    await page.getByTestId("ev-group-fundamental-toggle").click();
    await expect(page.getByTestId("ev-fundamental-valuation_vs_peers")).toHaveAttribute("data-direction", "unavailable");
  });

  // ── SB-8 ───────────────────────────────────────────────────────────────

  test("SB-8 graphs: the candidate's own payoff first, then a what-if of size and price asks the payoff route (bodies asserted); a pre-expiry date asks for it", async ({ page }) => {
    const st = await open(page, { plan: "cash" });
    await build(page);
    await expect(page.getByTestId("plan-graphs")).toBeVisible();
    await expect(page.getByTestId("payoff-svg")).toBeVisible();
    await expect(page.getByTestId("fan-note")).toContainText("Scenarios, not forecasts");
    await expect(page.getByTestId("fan-note")).toContainText("No validated price-path model exists");
    await expect(page.getByTestId("fan-trust")).toBeVisible();
    expect(st.payoffs).toHaveLength(0);               // the plan's own payoff block is the first answer: no call yet
    await expect(page.getByTestId("sum-max-loss")).toContainText("2,49,600.00");     // 208 x 1200, from the payload

    // Size: 100 shares. Hand-computed gross at the stop 1160: 100 x (1160 - 1200) = -4,000.
    await page.getByTestId("scenario-size").fill("100");
    await expect.poll(() => st.payoffs.length).toBeGreaterThan(0);
    const body = st.payoffs[st.payoffs.length - 1];
    expect(body.legs).toHaveLength(1);
    expect(body.legs[0]).toMatchObject({ kind: "cash", side: "buy", quantity: 100, lot_size: 1, entry_price: 1200 });
    expect(body.reference_price).toBe(1200);
    expect(body.grid).toMatchObject({ min: 900, max: 1500, points: 121 });
    expect(body.scenarios?.map((s) => s.name)).toEqual(["stop", "conservative", "base", "optimistic"]);
    const stopRow = page.getByTestId("payoff-scenario-row").filter({ hasText: "Scenario stop" });
    await expect(stopRow).toContainText(`gross ${MINUS}₹4,000.00`);
    await expect(page.getByTestId("sum-max-loss")).toContainText("1,20,000.00");      // 100 x 1200 at price 0

    // Price: a what-if point at 1250 adds a scenario (100 x 50 = +5,000 gross).
    await page.getByTestId("scenario-price").fill("1250");
    await expect.poll(() => st.payoffs[st.payoffs.length - 1].scenarios?.some((s) => s.name === "what-if" && s.underlying_price === 1250)).toBe(true);
    await expect(page.getByTestId("payoff-scenario-row").filter({ hasText: "Scenario what-if" })).toContainText("gross +₹5,000.00");
  });

  test("SB-8b options graph: the spread's two legs; an evaluation date asks for the pre-expiry estimate (pre_expiry.date in the body)", async ({ page }) => {
    const p = fixture("options");
    const st = await open(page, { plan: "options" }, "&sym=RELIANCE&direction=bullish&instrument=options");
    await build(page);
    await expect(page.getByTestId("payoff-svg")).toBeVisible();
    await expect(page.getByTestId("payoff-mode-pre")).toBeEnabled();    // the plan's own block carries a pre-expiry estimate for its horizon date
    const legs = cand(p, "options:bull_call_spread").legs;
    expect(legs).toHaveLength(2);
    await page.getByTestId("scenario-date").fill("2026-11-10");
    await expect.poll(() => st.payoffs.length).toBeGreaterThan(0);
    const body = st.payoffs[st.payoffs.length - 1];
    expect(body.pre_expiry?.date).toBe("2026-11-10");
    expect(body.legs.map((l) => [l.side, l.option_type, l.strike, l.quantity, l.lot_size])).toEqual([["buy", "call", 1200, 2, 250], ["sell", "call", 1250, 2, 250]]);
  });

  // ── SB-9 ───────────────────────────────────────────────────────────────

  test("SB-9 save, list, open, delete: the saved plan is the built one unchanged; a saved plan reopens from ?plan=; delete says it removed the saved copy only", async ({ page }) => {
    const p = fixture("cash");
    const st = await open(page, { plan: "cash" });
    await build(page);
    await expect(page.getByTestId("saved-empty")).toBeVisible();
    await page.getByTestId("act-save").click();
    await expect(page.getByTestId("act-msg-save")).toContainText("Plan saved");
    expect(st.saves).toHaveLength(1);
    expect(st.saves[0].plan).toEqual(p);                         // exactly what the route returned
    await expect(page.getByTestId("act-save")).toHaveText("Saved");
    await expect(page.getByTestId("act-save")).toBeDisabled();
    await expect(page.getByTestId("saved-id")).toContainText("sv-1");
    const row = page.getByTestId("saved-sv-1");
    await expect(row).toContainText("RELIANCE");
    await expect(row).toContainText("Plan");
    await expect(row).toContainText(p.rules_version);

    // Open it from a fresh page load of the saved link.
    await page.goto(`${BUILDER}&plan=sv-1`);
    await expect(page.getByTestId("saved-banner")).toContainText("Saved copy from 20 Oct 2026");
    await expect(page.getByTestId("plan-versions")).toContainText(p.plan_id);
    await expect(page.getByTestId("act-save")).toHaveText("Saved");
    // Delete: a confirmation, then the saved copy only.
    await page.getByTestId("saved-delete-sv-1").click();
    await expect(page.getByTestId("saved-confirm-sv-1")).toBeVisible();
    await page.getByTestId("saved-confirm-sv-1").click();
    await expect(page.getByTestId("saved-note")).toContainText("deleted only your saved copy");
    expect(st.deletes).toEqual(["sv-1"]);
    await expect(page.getByTestId("saved-empty")).toBeVisible();
    await expect(page.getByTestId("plan-view")).toHaveCount(0);
  });

  test("SB-9b saved plans list: Open from the list; a plan that is not yours or gone says so; the plan limit and duplicates show the route's words", async ({ page }) => {
    const p = fixture("cash");
    const st = await open(page, { plan: "cash", saved: [{ id: "old-1", plan: fixture("wait"), saved_at: "2026-10-18T05:00:00+00:00" }] });
    await expect(page.getByTestId("saved-old-1")).toContainText("Wait for confirmation");
    await page.getByTestId("saved-open-old-1").click();
    await expect(page).toHaveURL(/plan=old-1/);
    await expect(page.getByTestId("plan-status")).toHaveAttribute("data-status", "wait");
    await expect(page.getByTestId("saved-banner")).toContainText("18 Oct 2026");
    await page.goto(`${BUILDER}&plan=gone-9`);
    await expect(page.getByTestId("saved-open-error")).toContainText("not on record");
    // The limit.
    await page.unroute("**/api/desk/strategy/plans");
    await page.route("**/api/desk/strategy/plans", (r) => (r.request().method() === "POST"
      ? json(r, { detail: { code: "plan_limit", message: "At most 200 saved plans; delete one first." } }, 409)
      : json(r, { plans: [], count: 0, limit: 100, max_saved: 200 })));
    await page.goto(`${BUILDER}&sym=RELIANCE&direction=bullish&instrument=cash`);
    await build(page);
    await page.getByTestId("act-save").click();
    await expect(page.getByTestId("act-msg-save")).toContainText("At most 200 saved plans; delete one first.");
    expect(p.sent_to_broker).toBe(false);
    expect(st.deletes).toHaveLength(0);
  });

  // ── SB-10 ──────────────────────────────────────────────────────────────

  test("SB-10a paper trade a futures plan: saves first and says so; the exact kind \"strategy\" body with the signal block and strategy_plan_id", async ({ page }) => {
    const p = fixture("futures");
    const st = await open(page, { plan: "futures" }, "&sym=RELIANCE&direction=bullish&instrument=futures");
    await build(page);
    await expect(page.getByTestId("paper-blocked")).toHaveCount(0);
    await page.getByTestId("act-paper").click();
    await expect(page.getByTestId("act-msg-paper")).toContainText("Saved the plan first so the paper trade can point to it");
    expect(st.saves).toHaveLength(1);
    expect(st.strat).toHaveLength(1);
    const b = st.strat[0];
    expect(Object.keys(b).sort()).toEqual(["direction", "family", "kind", "legs", "max_hold_sessions", "reference_price", "signal", "stop_underlying", "strategy_plan_id", "target_underlying", "underlying"].sort());
    expect(b).toMatchObject({
      kind: "strategy", underlying: "RELIANCE", direction: "bullish", family: "long_future", strategy_plan_id: "sv-1", reference_price: 1200, stop_underlying: 1150, target_underlying: 1250, max_hold_sessions: 10,
      legs: [{ kind: "future", side: "buy", lots: 1, lot_size: 250, entry_price: 1203, expiry: "2026-10-27", strike: null, option_type: null, price_source: "NSE F&O bhavcopy settle, 2026-10-19" }],
    });
    expect(b.signal.signal_at).toBe(p.generated_at);
    expect(b.signal.rule_version).toBe(p.rules_version);
    expect(b.signal.source_refs.length).toBeGreaterThan(3);
    expect(b.signal.source_refs.length).toBeLessThanOrEqual(10);
    expect(b.signal.source_refs[0]).toEqual({ kind: "indicators", ref: expect.stringContaining("MOCK nidp.prices_eod_adjusted #"), as_of: "2026-10-19" });
    expect(b.signal.evidence_summary).toContain(p.plan_id);
    expect(b.signal.evidence_summary.length).toBeLessThanOrEqual(1000);
    expect(Object.keys(b.signal).sort()).toEqual(["evidence_summary", "rule_version", "signal_at", "source_refs"]);
    await expect(page.getByTestId("act-msg-paper")).toContainText("No order is placed");
    expect(st.writes.filter((w) => /order|broker/i.test(w))).toEqual([]);
  });

  test("SB-10b paper trade the option spread: both legs, strikes and option types, the plan's stop and target levels, family bull_call_spread", async ({ page }) => {
    const st = await open(page, { plan: "options" }, "&sym=RELIANCE&direction=bullish&instrument=options");
    await build(page);
    await page.getByTestId("act-save").click();
    await expect(page.getByTestId("saved-id")).toBeVisible();
    await page.getByTestId("act-paper").click();
    await expect(page.getByTestId("act-msg-paper")).toContainText("Paper trade recorded");
    await expect(page.getByTestId("act-msg-paper")).not.toContainText("Saved the plan first");
    expect(st.saves).toHaveLength(1);
    const b = st.strat[0];
    expect(b).toMatchObject({ kind: "strategy", underlying: "RELIANCE", direction: "bullish", family: "bull_call_spread", strategy_plan_id: "sv-1", reference_price: 1200, stop_underlying: 1150, target_underlying: 1250 });
    expect(b.legs).toEqual([
      { kind: "option", side: "buy", lots: 2, lot_size: 250, entry_price: 52, expiry: "2026-11-24", strike: 1200, option_type: "call", price_source: "NSE F&O bhavcopy close, 2026-10-19" },
      { kind: "option", side: "sell", lots: 2, lot_size: 250, entry_price: 38, expiry: "2026-11-24", strike: 1250, option_type: "call", price_source: "NSE F&O bhavcopy close, 2026-10-19" },
    ]);
  });

  test("SB-10c a cash plan goes to the share paper-trade API: quantity, entry, the plan's stop and base target, source and strategy version", async ({ page }) => {
    const p = fixture("cash");
    const st = await open(page, { plan: "cash" });
    await build(page);
    await page.getByTestId("act-paper").click();
    await expect(page.getByTestId("act-msg-paper")).toContainText("Paper trade recorded: 208 RELIANCE shares");
    expect(st.strat).toHaveLength(0);
    expect(st.saves).toHaveLength(0);                       // a share trade does not need the plan saved
    expect(st.paid).toHaveLength(1);
    expect(st.paid[0]).toEqual({
      symbol: "RELIANCE", quantity: 208, entry_price: 1200, stop_price: 1160, target_price: 1280,
      source: { kind: "strategy_plan", bucket: "breakout_continuation", signal_date: "2026-10-19" },
      signal_at: p.generated_at, strategy_version: p.rules_version, rationale: `Breakout continuation (long); plan ${p.plan_id}`,
    });
  });

  test("SB-10d a refused paper trade shows the server's words; a refused save keeps the paper trade from being recorded", async ({ page }) => {
    const st = await open(page, { plan: "futures", paperReply: { status: 422, body: { detail: "expiry_in_past" } } }, "&sym=RELIANCE&direction=bullish&instrument=futures");
    await build(page);
    await page.getByTestId("act-paper").click();
    await expect(page.getByTestId("act-msg-paper")).toContainText("Paper trade not recorded");
    await expect(page.getByTestId("act-msg-paper")).toContainText("expiry_in_past");
    expect(st.saves).toHaveLength(1);
  });

  // ── SB-11 ──────────────────────────────────────────────────────────────

  test("SB-11 Ask Copilot saves the plan first, then asks with the saved plan id and a short summary", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const p = fixture("cash");
    const st = await open(page, { plan: "cash" });
    await build(page);
    await expect(page.getByTestId("save-hint")).toContainText("the Copilot can only quote saved plans");
    await page.getByTestId("act-ask").click();
    await expect(page.getByTestId("act-msg-ask")).toContainText("Saved the plan first: the Copilot can only quote saved plans");
    await expect(page.getByTestId("act-msg-ask")).toContainText("saved plan sv-1");
    await expect.poll(() => st.streams.length).toBe(1);
    expect(st.saves).toHaveLength(1);
    expect(st.streams[0].message).toContain("saved strategy plan sv-1");
    expect(st.streams[0].message).toContain(p.plan_id);
    expect(st.streams[0].message).toContain("RELIANCE: bullish view");
    expect(st.streams[0].message).toContain("do not invent strikes, prices or P&L");
    await expect(page.getByTestId("dock-question").first()).toContainText("sv-1");
  });

  // ── SB-12 ──────────────────────────────────────────────────────────────

  test("SB-12 failures: a 502 shows an error with a retry that builds again; signed out and not-enabled are said plainly", async ({ page }) => {
    let calls = 0;
    const st = await setup(page, {});
    await page.unroute("**/api/desk/strategy/plan");
    await page.route("**/api/desk/strategy/plan", (r) => { calls += 1; return calls === 1 ? json(r, { detail: "upstream_unavailable" }, 502) : json(r, fixture("cash")); });
    await page.goto(`${BUILDER}&sym=RELIANCE&direction=bullish&instrument=cash`);
    await page.getByTestId("build-plan").click();
    const err = page.getByTestId("build-error");
    await expect(err).toContainText("The plan was not built");
    await expect(err).toContainText("the server could not finish (502");
    await err.getByRole("button", { name: /Retry/ }).click();
    await expect(page.getByTestId("plan-view")).toBeVisible();
    expect(calls).toBe(2);
    expect(st.builds).toHaveLength(0);
    // 403
    await page.unroute("**/api/desk/strategy/plan");
    await page.route("**/api/desk/strategy/plan", (r) => json(r, { detail: "Feature not enabled" }, 403));
    await page.getByTestId("build-plan").click();
    await expect(page.getByTestId("build-error")).toContainText("not enabled for this account");
    await expect(page.getByTestId("plan-view")).toHaveCount(0);
    // A body that is not a plan is a contract error, never an empty plan.
    await page.unroute("**/api/desk/strategy/plan");
    await page.route("**/api/desk/strategy/plan", (r) => json(r, { plan_id: "x" }));
    await page.getByTestId("build-plan").click();
    await expect(page.getByTestId("build-error")).toContainText("not in the expected form");
  });

  test("SB-12b a reload with ?build=1 builds the same plan again", async ({ page }) => {
    const st = await open(page, { plan: "cash" }, "&sym=RELIANCE&direction=bullish&instrument=cash&build=1");
    await expect(page.getByTestId("plan-view")).toBeVisible();
    expect(st.builds).toEqual([{ underlying: "RELIANCE", direction: "bullish", instrument: "cash" }]);
  });

  // ── SB-13 ──────────────────────────────────────────────────────────────

  test("SB-13 persona wording: the investor sees plain words; the data is the same", async ({ page }) => {
    await open(page, { plan: "cash" }, "&sym=RELIANCE&direction=bullish&instrument=cash&persona=investor");
    await expect(page.getByTestId("field-direction")).toContainText("What do you expect?");
    await expect(page.getByTestId("in-direction-bullish")).toHaveText("Expect it to rise");
    await expect(page.getByTestId("in-horizon-intraday")).toContainText("Within a day");
    await page.getByTestId("build-plan").click();
    await expect(page.getByTestId("plan-status")).toContainText("A plan is ready");
    await expect(page.getByTestId("head-technical")).toContainText("How the chart looks");
    await expect(page.getByTestId("head-model")).toContainText("Chance estimate");
    await expect(page.getByTestId("head-model-value")).toHaveText("Withheld");
    await expect(page.getByTestId("head-model-gate")).toContainText("not marked as checked against real outcomes");
    await expect(page.getByTestId("cand-invalidation")).toContainText("When the idea is wrong");
  });

  test("SB-13b at 390px the page does not scroll sideways, tables scroll inside themselves, and nothing is an order control", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await open(page, { plan: "all" }, "&sym=RELIANCE&direction=bullish");
    await build(page);
    await page.getByTestId("ev-toggle-all").click();
    await page.getByTestId("methodology-toggle").click();
    await expect(page.getByTestId("methodology-toggle")).toHaveAttribute("aria-expanded", "true");
    expect(await sideways(page)).toEqual({ doc: 0, scroll: 0 });
    const region = page.getByRole("region", { name: /Candidates compared/ });
    expect(await region.evaluate((e) => e.scrollWidth > e.clientWidth)).toBe(true);
    await expect(region).toHaveAttribute("tabindex", "0");
    // The bottom bar keeps More highlighted.
    await expect(page.getByTestId("desk-bottom-more")).toHaveAttribute("aria-current", "page");
    // No order, buy or broker button anywhere on the screen.
    const labels = await page.getByTestId("strategy-builder").getByRole("button").allTextContents();
    expect(labels.filter((t) => /place order|submit order|send to broker|execute|buy now|sell now/i.test(t))).toEqual([]);
    await expect(page.getByTestId("no-orders")).toHaveText("Nivesh does not place orders; nothing here is sent to a broker.");
  });

  test("SB-13c methodology: the rules version, the families, the cost model, the pricing model and the open data gaps", async ({ page }) => {
    const p = fixture("options");
    await open(page, { plan: "options" }, "&sym=RELIANCE&direction=bullish&instrument=options");
    await build(page);
    await expect(page.getByTestId("methodology")).toHaveCount(0);
    await page.getByTestId("methodology-toggle").click();
    const m = page.getByTestId("methodology");
    await expect(m).toContainText(`Rules version ${p.rules_version}`);
    await expect(m.getByTestId("method-rules")).toContainText("liquidity_min_traded_value_cr");
    await expect(m.getByTestId("method-costs")).toContainText("slippage % of traded value + flat brokerage");
    await expect(m.getByTestId("method-costs")).toContainText("taxes");
    await expect(m.getByTestId("method-pricing")).toContainText("Black-76");
    for (const gap of ["fundamental.analyst_estimates", "fundamental.cash_flow_quality", "fundamental.ownership_changes", "derivatives.future_day_change", "derivatives.bid_ask"]) await expect(m.getByTestId("method-gaps")).toContainText(gap);
  });
});

// ── screenshots (not assertions): written when SHOTS=1 ───────────────────

const SHOTS = process.env.SHOTS_DIR;
test.describe("MOCK — not real data: Strategy Builder screenshots", () => {
  test.skip(!SHOTS, "set SHOTS_DIR to write screenshots");
  for (const name of ["cash", "futures", "options", "notrade", "wait", "insufficient", "all"]) {
    for (const [w, h, tag] of [[1440, 900, "1440"], [390, 844, "390"]] as const) {
      test(`shot ${name} ${tag}`, async ({ page }) => {
        await page.setViewportSize({ width: w, height: h });
        await open(page, { plan: name }, `&sym=RELIANCE&direction=bullish&instrument=${name === "all" ? "all" : name === "notrade" || name === "wait" || name === "insufficient" ? "all" : name}`);
        await build(page);
        await page.getByTestId("plan-summary").scrollIntoViewIfNeeded();
        await page.waitForTimeout(600);
        await page.screenshot({ path: path.join(SHOTS as string, `sb-${name}-${tag}.png`), fullPage: false });
        const g = page.getByTestId("plan-graphs");
        if (await g.count()) { await g.scrollIntoViewIfNeeded(); await page.waitForTimeout(400); await page.screenshot({ path: path.join(SHOTS as string, `sb-${name}-${tag}-graphs.png`) }); }
        else { await page.getByTestId("plan-status-reasons").scrollIntoViewIfNeeded().catch(() => {}); await page.screenshot({ path: path.join(SHOTS as string, `sb-${name}-${tag}-b.png`) }); }
      });
    }
  }
});
