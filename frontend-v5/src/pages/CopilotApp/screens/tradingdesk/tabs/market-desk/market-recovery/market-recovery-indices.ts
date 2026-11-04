/**
 * Market Desk › Market Recovery — part 2, Nifty and Bank Nifty by expiry (contract: docs/market_recovery/DESIGN.md §9; backend
 * routes/market_recovery.py).
 *
 *   GET /api/market-recovery/indices   one answer per end-of-day session: for Nifty 50 and Bank Nifty the close and its
 *                                      technicals, floor pivots, the levels above / below the close, futures build-up, and
 *                                      EVERY live option expiry on its own (weeklies and monthlies; owner, 4 Nov: "analysis
 *                                      should be done on each of the expiry dates") with its PCR, max pain, the ATM straddle's
 *                                      implied range, call / put walls, fresh writing and cuts; defined-risk setups per expiry
 *                                      (none for a too-thin expiry); plus India VIX, Bank Nifty's relative strength and FII / DII
 *
 * Signed in, behind the `market_recovery` flag. Typed errors {detail: {code, message}} (503 data_unavailable) are read with
 * recoveryProblem(), whose message is the server's own sentence. Open interest and volume arrive in UNITS (shares), not
 * contracts. Every field is parsed defensively: a missing number is null (shown as "—"), never 0. Nothing is computed here.
 */
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { num } from "../../../desk-data";
import { MR_PATH } from "./market-recovery-data";

export const INDICES_PATH = `${MR_PATH}/indices`;

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);
const bool = (v: unknown): boolean | null => (typeof v === "boolean" ? v : null);
const strs = (v: unknown): string[] => arr(v).map(str).filter((s): s is string => s !== null);
const nums = (v: unknown): number[] => arr(v).map(num).filter((n): n is number => n !== null);

// ── types ────────────────────────────────────────────────────────────────────────────────────────────────────────────

export interface Technicals {
  ema20: number | null; ema50: number | null; ema200: number | null;
  vsEma20Pct: number | null; vsEma50Pct: number | null; vsEma200Pct: number | null;
  rsi14: number | null; rsi14Ago: number | null;
  macd: number | null; macdSignal: number | null; macdHist: number | null; macdHistPrev: number | null;
  atr14: number | null; atrPct: number | null;
  high20: number | null; low20: number | null; high52: number | null; low52: number | null;
  fromHigh52Pct: number | null; fromLow52Pct: number | null;
  sessions: number | null;
}
export interface Pivots { p: number | null; r1: number | null; r2: number | null; r3: number | null; s1: number | null; s2: number | null; s3: number | null }
export interface FuturesRow {
  expiry: string | null; close: number | null; changePct: number | null; oi: number | null; oiChange: number | null;
  oiChangePct: number | null; basis: number | null; buildup: string | null;
}
export interface Level { level: number; label: string | null }
export interface StrikeOi { strike: number; oi: number | null }
export interface StrikeChange { strike: number; change: number | null }
export interface Expiry {
  expiry: string;
  days: number | null;
  kind: string | null;                 // weekly | monthly
  liquidity: string | null;            // active | thin | too_thin
  volume: number | null;
  pcr: number | null;
  callOi: number | null;
  putOi: number | null;
  maxPain: number | null;
  atm: number | null;
  atmCall: number | null;
  atmPut: number | null;
  straddle: number | null;
  movePct: number | null;
  rangeLo: number | null;
  rangeHi: number | null;
  callWall: number | null;
  putWall: number | null;
  callOiTop: StrikeOi[];
  putOiTop: StrikeOi[];
  callAdds: StrikeChange[];
  putAdds: StrikeChange[];
  callCuts: StrikeChange[];
  putCuts: StrikeChange[];
  read: string | null;
}
export interface SetupLeg {
  action: string;                      // "Buy" | "Sell" (the owner's words for this page)
  instrument: string;                  // "Call" | "Put"
  strike: number | null;
  lots: number | null;
  price: number | null;
  priceBasis: string | null;
  oi: number | null;
  volume: number | null;
  flags: string[];
}
export interface SetupCheck { id: string; label: string; pass: boolean | null; detail: string | null }
export interface Setup {
  expiry: string | null;
  kind: string | null;
  key: string;
  label: string;
  when: string | null;
  lotSize: number | null;
  legs: SetupLeg[];
  netPremium: number | null;           // per lot; paid < 0, received > 0
  maxGain: number | null;
  maxLoss: number | null;
  rewardRisk: number | null;
  breakevens: number[];
  status: string;                      // passes | fails (or an unknown value kept as sent)
  why: string | null;
  checks: SetupCheck[];
}
export interface IndexBlock {
  symbol: string;
  name: string;
  close: number | null; change: number | null; changePct: number | null;
  open: number | null; high: number | null; low: number | null;
  upStreak: number | null; ret5d: number | null; ret20d: number | null;
  technicals: Technicals | null;
  pivots: Pivots | null;
  futures: FuturesRow[];
  levels: { above: Level[]; below: Level[] };
  expiries: Expiry[];
  setups: Setup[];
  read: string[];
}
export interface Vix { close: number | null; changePct: number | null; closeAgo: number | null; change5dPct: number | null; upStreak: number | null }
export interface Relative { bankMinusNifty1d: number | null; bankMinusNifty5d: number | null; bankMinusNifty20d: number | null }
export interface FlowDay { date: string; fii: number | null; dii: number | null }
export interface Flows { asOf: string | null; days: FlowDay[]; fii5d: number | null; fiiBuyDays5: number | null }
export interface IndexSource { what: string | null; source: string | null; asOf: string | null }
export interface RecoveryIndices {
  asOf: string | null;
  indices: IndexBlock[];
  vix: Vix | null;
  relative: Relative | null;
  flows: Flows | null;
  together: string[];
  notes: string[];
  sources: IndexSource[];
  warnings: string[];
}

// ── parsing ──────────────────────────────────────────────────────────────────────────────────────────────────────────

function parseTechnicals(v: unknown): Technicals | null {
  const t = rec(v);
  if (!Object.keys(t).length) return null;
  return {
    ema20: num(t.ema20), ema50: num(t.ema50), ema200: num(t.ema200),
    vsEma20Pct: num(t.vs_ema20_pct), vsEma50Pct: num(t.vs_ema50_pct), vsEma200Pct: num(t.vs_ema200_pct),
    rsi14: num(t.rsi14), rsi14Ago: num(t.rsi14_5ago),
    macd: num(t.macd), macdSignal: num(t.macd_signal), macdHist: num(t.macd_hist), macdHistPrev: num(t.macd_hist_prev),
    atr14: num(t.atr14), atrPct: num(t.atr_pct),
    high20: num(t.high20), low20: num(t.low20), high52: num(t.high52), low52: num(t.low52),
    fromHigh52Pct: num(t.from_high52_pct), fromLow52Pct: num(t.from_low52_pct),
    sessions: num(t.sessions),
  };
}

function parsePivots(v: unknown): Pivots | null {
  const p = rec(v);
  if (!Object.keys(p).length) return null;
  return { p: num(p.p), r1: num(p.r1), r2: num(p.r2), r3: num(p.r3), s1: num(p.s1), s2: num(p.s2), s3: num(p.s3) };
}

function parseLevels(v: unknown): Level[] {
  return arr(v).map(rec).flatMap((l) => {
    const level = num(l.level);
    return level == null ? [] : [{ level, label: str(l.label) }];
  });
}

const strikeOi = (v: unknown): StrikeOi[] =>
  arr(v).map(rec).flatMap((r) => { const strike = num(r.strike); return strike == null ? [] : [{ strike, oi: num(r.oi) }]; });
const strikeChange = (v: unknown): StrikeChange[] =>
  arr(v).map(rec).flatMap((r) => { const strike = num(r.strike); return strike == null ? [] : [{ strike, change: num(r.change) }]; });

function parseExpiry(v: unknown): Expiry | null {
  const e = rec(v);
  const expiry = str(e.expiry);
  if (!expiry) return null;
  return {
    expiry, days: num(e.days), kind: str(e.kind), liquidity: str(e.liquidity), volume: num(e.volume),
    pcr: num(e.pcr), callOi: num(e.call_oi), putOi: num(e.put_oi), maxPain: num(e.max_pain),
    atm: num(e.atm), atmCall: num(e.atm_call), atmPut: num(e.atm_put), straddle: num(e.straddle), movePct: num(e.move_pct),
    rangeLo: num(e.range_lo), rangeHi: num(e.range_hi), callWall: num(e.call_wall), putWall: num(e.put_wall),
    callOiTop: strikeOi(e.call_oi_top), putOiTop: strikeOi(e.put_oi_top),
    callAdds: strikeChange(e.call_adds), putAdds: strikeChange(e.put_adds),
    callCuts: strikeChange(e.call_cuts), putCuts: strikeChange(e.put_cuts),
    read: str(e.read),
  };
}

function parseLeg(v: unknown): SetupLeg | null {
  const l = rec(v);
  const action = str(l.action);
  if (!action) return null;
  return {
    action, instrument: str(l.instrument) ?? "", strike: num(l.strike), lots: num(l.lots), price: num(l.price),
    priceBasis: str(l.price_basis), oi: num(l.oi), volume: num(l.volume), flags: strs(l.flags),
  };
}

function parseSetup(v: unknown): Setup | null {
  const s = rec(v);
  const key = str(s.key);
  if (!key) return null;
  return {
    expiry: str(s.expiry), kind: str(s.kind), key, label: str(s.label) ?? key.replace(/_/g, " "), when: str(s.when),
    lotSize: num(s.lot_size),
    legs: arr(s.legs).map(parseLeg).filter((l): l is SetupLeg => l !== null),
    netPremium: num(s.net_premium), maxGain: num(s.max_gain), maxLoss: num(s.max_loss), rewardRisk: num(s.reward_risk),
    breakevens: nums(s.breakevens),
    status: str(s.status) ?? "unavailable", why: str(s.why),
    checks: arr(s.checks).map(rec).flatMap((c) => {
      const id = str(c.id);
      return id ? [{ id, label: str(c.label) ?? id, pass: bool(c.pass), detail: str(c.detail) }] : [];
    }),
  };
}

function parseIndex(v: unknown): IndexBlock | null {
  const x = rec(v);
  const symbol = str(x.symbol);
  if (!symbol) return null;
  const lv = rec(x.levels);
  return {
    symbol, name: str(x.name) ?? symbol,
    close: num(x.close), change: num(x.change), changePct: num(x.change_pct),
    open: num(x.open), high: num(x.high), low: num(x.low),
    upStreak: num(x.up_streak), ret5d: num(x.ret_5d), ret20d: num(x.ret_20d),
    technicals: parseTechnicals(x.technicals),
    pivots: parsePivots(x.pivots),
    futures: arr(x.futures).map(rec).flatMap((f) => {
      const expiry = str(f.expiry);
      return [{
        expiry, close: num(f.close), changePct: num(f.change_pct), oi: num(f.oi), oiChange: num(f.oi_change),
        oiChangePct: num(f.oi_change_pct), basis: num(f.basis), buildup: str(f.buildup),
      }];
    }),
    levels: { above: parseLevels(lv.above), below: parseLevels(lv.below) },
    expiries: arr(x.expiries).map(parseExpiry).filter((e): e is Expiry => e !== null),
    setups: arr(x.setups).map(parseSetup).filter((s): s is Setup => s !== null),
    read: strs(x.read),
  };
}

export function parseRecoveryIndices(v: unknown): RecoveryIndices {
  const d = rec(v);
  const vx = rec(d.vix);
  const rl = rec(d.relative);
  const fl = rec(d.flows);
  return {
    asOf: str(d.as_of),
    indices: arr(d.indices).map(parseIndex).filter((i): i is IndexBlock => i !== null),
    vix: Object.keys(vx).length
      ? { close: num(vx.close), changePct: num(vx.change_pct), closeAgo: num(vx.close_5ago), change5dPct: num(vx.change_5d_pct), upStreak: num(vx.up_streak) }
      : null,
    relative: Object.keys(rl).length
      ? { bankMinusNifty1d: num(rl.bank_minus_nifty_1d), bankMinusNifty5d: num(rl.bank_minus_nifty_5d), bankMinusNifty20d: num(rl.bank_minus_nifty_20d) }
      : null,
    flows: Object.keys(fl).length
      ? {
          asOf: str(fl.as_of),
          days: arr(fl.days).map(rec).flatMap((r) => { const date = str(r.date); return date ? [{ date, fii: num(r.fii), dii: num(r.dii) }] : []; }),
          fii5d: num(fl.fii_5d), fiiBuyDays5: num(fl.fii_buy_days_5),
        }
      : null,
    together: strs(d.together),
    notes: strs(d.notes),
    sources: arr(d.sources).map(rec).map((s) => ({ what: str(s.what), source: str(s.source), asOf: str(s.as_of) })),
    warnings: strs(d.warnings),
  };
}

// ── hook ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

const noRetry4xx = (count: number, e: unknown) =>
  !(e instanceof ApiError && (e.kind === "contract_drift" || (e.status != null && e.status >= 400 && e.status < 500))) && count < 1;

export function useRecoveryIndices(enabled = true) {
  return useQuery<RecoveryIndices>({
    queryKey: ["copilot", "desk", "market-recovery", "indices"],
    enabled,
    queryFn: async ({ signal }) => {
      // The first answer of a new end-of-day date reads every live option chain of both indices on the server.
      const res = await http({ path: INDICES_PATH, signal, timeoutMs: 90_000, noRetry: true });
      return parseRecoveryIndices(res.data);
    },
    // End-of-day data: one answer per session; the server reuses its computation for 15 minutes.
    staleTime: 10 * 60_000,
    refetchOnWindowFocus: false,
    retry: noRetry4xx,
  });
}
