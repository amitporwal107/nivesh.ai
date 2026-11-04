/**
 * Market Desk › Market Recovery — part 2, "Nifty and Bank Nifty" (owner, 4 Nov 2026: "Please also put this nifty analysis here
 * in the dashboard"; "nifty analysis should be done on each of the expiry dates"; docs/market_recovery/DESIGN.md §9).
 *
 * One index at a time (Nifty 50 | Bank Nifty): the close and its technicals, floor pivots, the levels above and below the close,
 * futures build-up, then EVERY live option expiry on its own row — weekly and monthly kept apart, each with its PCR, max pain,
 * the ATM straddle's implied range, the call and put walls, fresh writing and cuts — and the defined-risk setups grouped by
 * expiry (a too-thin expiry has none). Shared under both: India VIX, Bank Nifty's relative strength and FII / DII cash.
 *
 * Reads GET /api/market-recovery/indices (market-recovery-indices.ts) on its own, so the rest of the page never waits for it.
 * Every figure, label and sentence is the server's; this screen formats them. Open interest arrives in units (shares) and is
 * shown in lakh units ("L"). Wording: the setups' legs read "Buy 1 lot · …" / "Sell 1 lot · …" — the owner's verbs for this page
 * (4 Nov), always followed by the lot count so the page's wording lint can allow them only there.
 */
import { useState, type CSSProperties, type ReactNode } from "react";
import { LoadingBlock, Pill, type Tone } from "../../../../../components/ui";
import { recoveryProblem } from "./market-recovery-data";
import {
  useRecoveryIndices,
  type Expiry, type IndexBlock, type Level, type RecoveryIndices as Data, type Setup, type SetupLeg, type StrikeChange, type StrikeOi,
} from "./market-recovery-indices";

// ── formatting ───────────────────────────────────────────────────────────────────────────────────────────────────────

const DASH = "—";
const MINUS = "−";
const price = (v: number | null | undefined) => (v == null ? DASH : v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const lvl = (v: number | null | undefined) => (v == null ? DASH : v.toLocaleString("en-IN", { maximumFractionDigits: 2 }));
const fixed = (v: number | null | undefined, dp = 1) => (v == null ? DASH : v.toFixed(dp));
const signed = (v: number | null | undefined, unit = "", dp = 2) =>
  v == null ? DASH : `${v < 0 ? MINUS : v > 0 ? "+" : ""}${Math.abs(v).toLocaleString("en-IN", { minimumFractionDigits: dp, maximumFractionDigits: dp })}${unit}`;
/** Open interest / volume, units → lakh units ("58.2L"). */
const lakh = (v: number | null | undefined) => (v == null ? DASH : `${(v / 1e5).toLocaleString("en-IN", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}L`);
const lakhSigned = (v: number | null | undefined) => (v == null ? DASH : `${v < 0 ? MINUS : v > 0 ? "+" : ""}${lakh(Math.abs(v))}`);
const rs = (v: number | null | undefined) => (v == null ? DASH : `₹${Math.abs(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);
const crore = (v: number | null | undefined) =>
  v == null ? DASH : `${v < 0 ? MINUS : v > 0 ? "+" : ""}₹${Math.abs(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} cr`;
const tone = (v: number | null | undefined) => (v == null ? "var(--cp-ink-4)" : v > 0 ? "var(--mint)" : v < 0 ? "var(--cp-danger)" : "var(--cp-ink-2)");
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function day(iso: string | null | undefined, withYear = true): string {
  const m = iso ? /^(\d{4})-(\d{2})-(\d{2})/.exec(iso) : null;
  return m ? `${Number(m[3])} ${MONTHS[Number(m[2]) - 1] ?? m[2]}${withYear ? ` ${m[1]}` : ""}` : iso ?? DASH;
}
/** Distance of a level from the close, as shown beside it. */
const distance = (level: number, close: number | null) => (close ? signed((level / close - 1) * 100, "%", 1) : DASH);

const note: CSSProperties = { fontSize: 11.5, lineHeight: 1.5, color: "var(--cp-ink-3)" };
const th: CSSProperties = {
  padding: "6px 8px", textAlign: "left", fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.12em", textTransform: "uppercase",
  color: "var(--cp-ink-4)", fontWeight: 500, borderBottom: "1px solid var(--cp-line)", whiteSpace: "nowrap", verticalAlign: "bottom",
};
const thR: CSSProperties = { ...th, textAlign: "right" };
const td: CSSProperties = {
  padding: "7px 8px", fontSize: 12.5, color: "var(--cp-ink-2)", borderBottom: "1px solid var(--cp-line)", fontFamily: "var(--mono)",
  fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap", verticalAlign: "top",
};
const tdR: CSSProperties = { ...td, textAlign: "right" };
const tdText: CSSProperties = { ...td, fontFamily: "var(--sans)", whiteSpace: "normal" };
const dt: CSSProperties = { color: "var(--cp-ink-3)" };
const sub: CSSProperties = { display: "block", fontSize: 11, lineHeight: 1.45, color: "var(--cp-ink-3)", whiteSpace: "normal" };

const BUILDUP: Record<string, { label: string; tone: Tone }> = {
  long_buildup: { label: "Long build-up", tone: "mint" },
  short_covering: { label: "Short covering", tone: "amber" },
  short_buildup: { label: "Short build-up", tone: "danger" },
  long_unwinding: { label: "Long unwinding", tone: "indigo" },
};
const LIQUIDITY: Record<string, { label: string; tone: Tone }> = {
  active: { label: "Active", tone: "mint" },
  thin: { label: "Thin", tone: "amber" },
  too_thin: { label: "Too thin", tone: "danger" },
};
const KIND: Record<string, string> = { weekly: "Weekly", monthly: "Monthly" };
const STATUS: Record<string, { label: string; tone: Tone }> = {
  passes: { label: "Passes the checks", tone: "mint" },
  fails: { label: "Fails a check", tone: "amber" },
  unavailable: { label: "Not available", tone: "ink" },
};
const FLAG_TEXT: Record<string, string> = {
  low_oi: "low open interest", low_volume: "low volume", abnormal_iv: "unusual implied volatility", missing_iv: "no implied volatility",
  missing_greeks: "no Greeks", zero_open_interest: "no open interest", no_trades_today: "no trades on the day", missing_premium: "no premium",
};

/** A table that scrolls inside its own box, so the page never scrolls sideways (390 px phones). */
function Scroll({ children, minWidth, testId }: { children: ReactNode; minWidth: number; testId?: string }) {
  return (
    <div className="cp-scroll" data-testid={testId} style={{ overflowX: "auto", maxWidth: "100%", minWidth: 0 }}>
      <table className="w-full" style={{ borderCollapse: "collapse", minWidth }}>{children}</table>
    </div>
  );
}

function Block({ id, title, children, aside }: { id: string; title: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <div data-testid={id} className="flex min-w-0 flex-col" style={{ gap: 8 }}>
      <div className="flex min-w-0 flex-wrap items-baseline" style={{ gap: "2px 12px" }}>
        <span className="cp-mono-note" style={{ color: "var(--cp-ink-3)" }}>{title}</span>
        {aside && <span style={{ ...note, minWidth: 0 }}>{aside}</span>}
      </div>
      {children}
    </div>
  );
}

// ── one index ────────────────────────────────────────────────────────────────────────────────────────────────────────

function Fig({ label, value, subText, valueTone }: { label: string; value: string; subText?: string | null; valueTone?: string }) {
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 1 }}>
      <span className="cp-mono-note">{label}</span>
      <span className="cp-num" style={{ fontSize: 14, color: valueTone ?? "var(--cp-ink)" }}>{value}</span>
      {subText && <span style={{ ...note, fontSize: 11 }}>{subText}</span>}
    </div>
  );
}

function Snapshot({ x }: { x: IndexBlock }) {
  return (
    <div data-testid="mr-idx-snapshot" className="flex min-w-0 flex-wrap items-baseline" style={{ gap: "6px 18px" }}>
      <span className="flex items-baseline" style={{ gap: 10 }}>
        <span className="cp-num" style={{ fontSize: 22, color: "var(--cp-ink)" }}>{price(x.close)}</span>
        <span className="cp-num" style={{ fontSize: 13.5, color: tone(x.change) }} data-testid="mr-idx-change">
          {signed(x.change)} ({signed(x.changePct, "%")})
        </span>
      </span>
      <span className="cp-num" style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>O {price(x.open)} · H {price(x.high)} · L {price(x.low)}</span>
      {x.upStreak != null && (
        <span style={{ fontSize: 12.5, color: "var(--cp-ink-2)" }} data-testid="mr-idx-streak">
          {x.upStreak === 0 ? "Fell on the session" : `Up ${x.upStreak} session${x.upStreak === 1 ? "" : "s"} in a row`}
        </span>
      )}
      <span className="cp-num" style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>
        5 sessions <span style={{ color: tone(x.ret5d) }}>{signed(x.ret5d, "%")}</span> · 20 sessions <span style={{ color: tone(x.ret20d) }}>{signed(x.ret20d, "%")}</span>
      </span>
    </div>
  );
}

function TechnicalsStrip({ x }: { x: IndexBlock }) {
  const t = x.technicals;
  const p = x.pivots;
  if (!t && !p) return null;
  const histDir = t?.macdHist == null || t.macdHistPrev == null ? null : t.macdHist > t.macdHistPrev ? "rising" : t.macdHist < t.macdHistPrev ? "falling" : "flat";
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 10 }}>
      {t && (
        <div data-testid="mr-idx-tech" className="grid min-w-0" style={{ gap: "10px 16px", gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))" }}>
          <Fig label="20-day avg (EMA)" value={lvl(t.ema20)} subText={`close ${signed(t.vsEma20Pct, "%")}`} />
          <Fig label="50-day avg (EMA)" value={lvl(t.ema50)} subText={`close ${signed(t.vsEma50Pct, "%")}`} />
          <Fig label="200-day avg (EMA)" value={lvl(t.ema200)} subText={`close ${signed(t.vsEma200Pct, "%")}`} />
          <Fig label="RSI (14)" value={fixed(t.rsi14)} subText={t.rsi14Ago != null ? `${fixed(t.rsi14Ago)} five sessions ago` : null} />
          <Fig label="MACD histogram" value={signed(t.macdHist)} subText={histDir ? `${histDir} · line ${signed(t.macd)} vs signal ${signed(t.macdSignal)}` : null} valueTone={tone(t.macdHist)} />
          <Fig label="ATR (14)" value={lvl(t.atr14)} subText={t.atrPct != null ? `${fixed(t.atrPct, 2)}% of the close` : null} />
          <Fig label="20-session high / low" value={`${lvl(t.high20)} / ${lvl(t.low20)}`} />
          <Fig label="52-week high / low" value={`${lvl(t.high52)} / ${lvl(t.low52)}`}
               subText={t.fromHigh52Pct != null || t.fromLow52Pct != null ? `${signed(t.fromHigh52Pct, "%", 1)} from the high · ${signed(t.fromLow52Pct, "%", 1)} from the low` : null} />
        </div>
      )}
      {p && (
        <div data-testid="mr-idx-pivots" className="cp-num flex min-w-0 flex-wrap" style={{ gap: "4px 14px", fontSize: 12, color: "var(--cp-ink-2)" }}>
          <span className="cp-mono-note">Floor pivots</span>
          <span>S3 {lvl(p.s3)}</span><span>S2 {lvl(p.s2)}</span><span>S1 {lvl(p.s1)}</span>
          <span style={{ color: "var(--cp-ink)" }}>P {lvl(p.p)}</span>
          <span>R1 {lvl(p.r1)}</span><span>R2 {lvl(p.r2)}</span><span>R3 {lvl(p.r3)}</span>
        </div>
      )}
      {t?.sessions != null && <span style={note}>Averages, RSI and ATR over {t.sessions} daily closes (EMA seeded with the simple average; Wilder RSI and ATR).</span>}
    </div>
  );
}

function LevelList({ levels, close, side }: { levels: Level[]; close: number | null; side: "above" | "below" }) {
  return (
    <div data-testid={`mr-idx-levels-${side}`} className="flex min-w-0 flex-col" style={{ gap: 2, flex: "1 1 240px" }}>
      <span className="cp-mono-note">{side === "above" ? "Above the close" : "Below the close"}</span>
      {levels.length ? (
        <ul className="m-0 flex flex-col p-0" style={{ listStyle: "none" }}>
          {levels.map((l, i) => (
            <li key={`${l.level}-${i}`} data-testid="mr-idx-level" className="flex min-w-0 items-baseline" style={{ gap: 10, padding: "4px 0", borderBottom: "1px solid var(--cp-line)", fontSize: 12.5 }}>
              <span className="cp-num" style={{ color: "var(--cp-ink)", minWidth: 78 }}>{lvl(l.level)}</span>
              <span style={{ flex: "1 1 auto", minWidth: 0, color: "var(--cp-ink-2)" }}>{l.label ?? DASH}</span>
              <span className="cp-num" style={{ color: "var(--cp-ink-3)", fontSize: 11.5 }}>{distance(l.level, close)}</span>
            </li>
          ))}
        </ul>
      ) : (
        <span style={note}>None listed.</span>
      )}
    </div>
  );
}

function Futures({ x }: { x: IndexBlock }) {
  if (!x.futures.length) return null;
  return (
    <Block id="mr-idx-futures" title="Futures · price × open interest">
      <Scroll minWidth={640}>
        <thead>
          <tr>
            <th style={th}>Expiry</th><th style={thR}>Close</th><th style={thR}>Day</th><th style={thR}>Open interest</th>
            <th style={thR}>OI change</th><th style={thR}>Basis</th><th style={th}>Build-up</th>
          </tr>
        </thead>
        <tbody>
          {x.futures.map((f, i) => {
            const b = BUILDUP[f.buildup ?? ""];
            return (
              <tr key={`${f.expiry}-${i}`} data-testid="mr-fut-row" data-buildup={f.buildup ?? ""}>
                <td style={td}>{day(f.expiry)}</td>
                <td style={tdR}>{price(f.close)}</td>
                <td style={{ ...tdR, color: tone(f.changePct) }}>{signed(f.changePct, "%")}</td>
                <td style={tdR}>{lakh(f.oi)}</td>
                <td style={{ ...tdR, color: tone(f.oiChange) }}>{lakhSigned(f.oiChange)}{f.oiChangePct != null ? ` (${signed(f.oiChangePct, "%")})` : ""}</td>
                <td style={tdR}>{signed(f.basis)}</td>
                <td style={tdText}>{b ? <Pill tone={b.tone}>{b.label}</Pill> : (f.buildup ?? DASH)}</td>
              </tr>
            );
          })}
        </tbody>
      </Scroll>
    </Block>
  );
}

const oiList = (rows: StrikeOi[]) => rows.map((r) => `${lvl(r.strike)} ${lakh(r.oi)}`).join(" · ");
const chgList = (rows: StrikeChange[]) => rows.map((r) => `${lvl(r.strike)} ${lakhSigned(r.change)}`).join(" · ");

function ExpiryTable({ x }: { x: IndexBlock }) {
  if (!x.expiries.length) return <p className="m-0" data-testid="mr-idx-no-expiries" style={note}>No live option expiry was read for {x.name}.</p>;
  return (
    <Block id="mr-idx-expiries" title="Options · each expiry on its own" aside="Open interest and fresh writing in lakh units (shares), not contracts">
      <Scroll minWidth={1080}>
        <thead>
          <tr>
            <th style={th}>Expiry</th><th style={th}>Liquidity</th><th style={thR}>PCR</th><th style={thR}>Max pain</th>
            <th style={th}>Implied range (ATM straddle)</th><th style={th}>Call side</th><th style={th}>Put side</th><th style={th}>Cuts</th>
          </tr>
        </thead>
        <tbody>
          {x.expiries.map((e) => <ExpiryRows key={e.expiry} e={e} />)}
        </tbody>
      </Scroll>
    </Block>
  );
}

function ExpiryRows({ e }: { e: Expiry }) {
  const liq = LIQUIDITY[e.liquidity ?? ""];
  const cuts = [e.callCuts.length ? `Calls ${chgList(e.callCuts)}` : null, e.putCuts.length ? `Puts ${chgList(e.putCuts)}` : null].filter(Boolean);
  return (
    <>
      <tr data-testid="mr-exp-row" data-expiry={e.expiry} data-kind={e.kind ?? ""} data-liquidity={e.liquidity ?? ""}>
        <td style={{ ...td, borderBottom: e.read ? "none" : td.borderBottom }}>
          <span style={{ color: "var(--cp-ink)" }}>{day(e.expiry)}</span>
          <span style={sub}>{KIND[e.kind ?? ""] ?? e.kind ?? DASH}{e.days != null ? ` · ${e.days} days` : ""}</span>
        </td>
        <td style={{ ...tdText, borderBottom: e.read ? "none" : td.borderBottom }}>
          {liq ? <Pill tone={liq.tone}>{liq.label}</Pill> : (e.liquidity ?? DASH)}
          {e.volume != null && <span style={sub}>volume {lakh(e.volume)}</span>}
        </td>
        <td style={{ ...tdR, borderBottom: e.read ? "none" : td.borderBottom }} data-testid="mr-exp-pcr">{fixed(e.pcr, 2)}</td>
        <td style={{ ...tdR, borderBottom: e.read ? "none" : td.borderBottom }} data-testid="mr-exp-maxpain">{lvl(e.maxPain)}</td>
        <td style={{ ...td, borderBottom: e.read ? "none" : td.borderBottom }} data-testid="mr-exp-range">
          {lvl(e.rangeLo)}–{lvl(e.rangeHi)}
          <span style={sub}>±{fixed(e.movePct, 2)}% · {lvl(e.atm)} call {price(e.atmCall)} + put {price(e.atmPut)}</span>
        </td>
        <td style={{ ...td, borderBottom: e.read ? "none" : td.borderBottom }} data-testid="mr-exp-calls">
          wall <span style={{ color: "var(--cp-ink)" }}>{lvl(e.callWall)}</span>
          {e.callOiTop.length > 0 && <span style={sub}>largest {oiList(e.callOiTop)}</span>}
          {e.callAdds.length > 0 && <span style={sub}>fresh {chgList(e.callAdds)}</span>}
        </td>
        <td style={{ ...td, borderBottom: e.read ? "none" : td.borderBottom }} data-testid="mr-exp-puts">
          wall <span style={{ color: "var(--cp-ink)" }}>{lvl(e.putWall)}</span>
          {e.putOiTop.length > 0 && <span style={sub}>largest {oiList(e.putOiTop)}</span>}
          {e.putAdds.length > 0 && <span style={sub}>fresh {chgList(e.putAdds)}</span>}
        </td>
        <td style={{ ...td, borderBottom: e.read ? "none" : td.borderBottom }} data-testid="mr-exp-cuts">
          {cuts.length ? cuts.map((c) => <span key={c} style={sub}>{c}</span>) : DASH}
        </td>
      </tr>
      {e.read && (
        <tr data-testid="mr-exp-read" data-expiry={e.expiry}>
          <td colSpan={8} style={{ ...tdText, paddingTop: 0, fontSize: 12.5, color: "var(--cp-ink-2)" }}>{e.read}</td>
        </tr>
      )}
    </>
  );
}

/** "Buy 1 lot · 23,800 Call @ 149.90" — the verb is followed by the lot count, always (the page's wording lint relies on it). */
function legText(l: SetupLeg): string {
  const lots = l.lots == null ? "" : ` ${l.lots} lot${l.lots === 1 ? "" : "s"}`;
  return `${l.action}${lots} · ${lvl(l.strike)} ${l.instrument} @ ${price(l.price)}`;
}

function SetupCard({ s }: { s: Setup }) {
  const st = STATUS[s.status] ?? { label: s.status, tone: "ink" as Tone };
  const dim = s.status !== "passes";
  const paid = s.netPremium == null ? null : s.netPremium < 0 ? "paid" : "received";
  return (
    <article data-testid="mr-setup" data-key={s.key} data-status={s.status} data-expiry={s.expiry ?? ""}
             className="cp-card flex min-w-0 flex-col" style={{ gap: 8, padding: "12px 14px", opacity: dim ? 0.78 : 1 }}>
      <header className="flex min-w-0 flex-wrap items-center" style={{ gap: "4px 10px" }}>
        <span style={{ flex: "1 1 auto", fontSize: 14, color: "var(--cp-ink)" }}>{s.label}</span>
        <Pill tone={st.tone}>{st.label}</Pill>
      </header>
      {s.when && <span style={{ fontSize: 12.5, color: "var(--cp-ink-2)" }} data-testid="mr-setup-when">{s.when}</span>}
      {s.why && <span data-testid="mr-setup-why" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--amber)" }}>{s.why}</span>}
      {s.legs.length > 0 && (
        <ul className="m-0 flex flex-col p-0" style={{ listStyle: "none", gap: 3 }}>
          {s.legs.map((l, i) => (
            <li key={i} className="flex min-w-0 flex-wrap items-baseline" style={{ gap: "2px 8px", fontSize: 12.5 }}>
              <span data-testid="mr-setup-leg" data-action={l.action} className="cp-num" style={{ color: "var(--cp-ink)" }}>{legText(l)}</span>
              {l.priceBasis && l.priceBasis !== "close" && <span style={note}>(settlement price: did not trade)</span>}
              {l.flags.length > 0 && <span style={{ ...note, color: "var(--amber)" }}>{l.flags.map((f) => FLAG_TEXT[f] ?? f.replace(/_/g, " ")).join(", ")}</span>}
            </li>
          ))}
        </ul>
      )}
      <dl className="m-0 grid" style={{ gridTemplateColumns: "auto 1fr", gap: "2px 10px", fontSize: 12 }}>
        <dt style={dt}>Net premium</dt>
        <dd className="cp-num m-0" data-testid="mr-setup-premium">{s.netPremium == null ? DASH : `${rs(s.netPremium)} ${paid} per lot`}{s.lotSize != null ? ` · lot ${s.lotSize}` : ""}</dd>
        <dt style={dt}>Max gain</dt><dd className="cp-num m-0" style={{ color: tone(s.maxGain) }}>{s.maxGain == null ? DASH : `+${rs(s.maxGain)}`}</dd>
        <dt style={dt}>Max loss</dt><dd className="cp-num m-0" style={{ color: tone(s.maxLoss) }}>{s.maxLoss == null ? DASH : `${MINUS}${rs(s.maxLoss)}`}</dd>
        <dt style={dt}>Reward : risk</dt><dd className="cp-num m-0" data-testid="mr-setup-rr">{s.rewardRisk == null ? DASH : `${s.rewardRisk.toFixed(2)} : 1`}</dd>
        <dt style={dt}>Breakeven</dt><dd className="cp-num m-0">{s.breakevens.length ? s.breakevens.map((b) => lvl(b)).join(" · ") : DASH}</dd>
      </dl>
      {s.checks.length > 0 && (
        <ul className="m-0 flex flex-col p-0" style={{ listStyle: "none", gap: 2 }} data-testid="mr-setup-checks">
          {s.checks.map((c) => (
            <li key={c.id} data-testid="mr-setup-check" data-id={c.id} data-pass={c.pass === null ? "unknown" : String(c.pass)}
                className="flex min-w-0 items-baseline" style={{ gap: 8, fontSize: 12, color: "var(--cp-ink-2)" }}>
              <span aria-hidden style={{ width: 10, flex: "none", fontWeight: 700, color: c.pass === true ? "var(--mint)" : c.pass === false ? "var(--cp-danger)" : "var(--cp-ink-4)" }}>
                {c.pass === true ? "✓" : c.pass === false ? "✗" : "–"}
              </span>
              <span className="sr-only">{c.pass === true ? "Passed:" : c.pass === false ? "Failed:" : "Not applied:"}</span>
              <span style={{ minWidth: 0 }}>{c.label}{c.detail ? <span style={{ color: "var(--cp-ink-3)" }}> · {c.detail}</span> : null}</span>
            </li>
          ))}
        </ul>
      )}
    </article>
  );
}

function SetupsByExpiry({ x }: { x: IndexBlock }) {
  const order = x.expiries.map((e) => e.expiry);
  const groups = new Map<string, Setup[]>();
  for (const s of x.setups) {
    const k = s.expiry ?? "";
    groups.set(k, [...(groups.get(k) ?? []), s]);
  }
  const keys = [...groups.keys()].sort((a, b) => (order.indexOf(a) + 1 || 999) - (order.indexOf(b) + 1 || 999) || a.localeCompare(b));
  const skipped = x.expiries.filter((e) => e.liquidity === "too_thin" && !groups.has(e.expiry));
  return (
    <Block id="mr-idx-setups" title="Setups by expiry · 1 lot · defined risk"
           aside="Figures at expiry from end-of-day premiums, before costs">
      {keys.length === 0 && <p className="m-0" style={note} data-testid="mr-idx-no-setups">No setup for {x.name} on this session.</p>}
      {keys.map((k) => {
        const e = x.expiries.find((v) => v.expiry === k);
        return (
          <div key={k} data-testid="mr-setup-group" data-expiry={k} className="flex min-w-0 flex-col" style={{ gap: 8 }}>
            <span style={{ fontSize: 13, color: "var(--cp-ink)" }}>
              {day(k)}
              <span style={{ color: "var(--cp-ink-3)" }}>
                {e?.kind ? ` · ${KIND[e.kind] ?? e.kind}` : ""}{e?.days != null ? ` · ${e.days} days` : ""}
                {e?.liquidity === "thin" ? " · thin: use limit orders" : ""}
              </span>
            </span>
            <div className="grid min-w-0" style={{ gap: 10, gridTemplateColumns: "repeat(auto-fill, minmax(min(100%, 270px), 1fr))" }}>
              {groups.get(k)!.map((s) => <SetupCard key={`${s.key}-${s.expiry}`} s={s} />)}
            </div>
          </div>
        );
      })}
      {skipped.length > 0 && (
        <p className="m-0" style={note} data-testid="mr-setups-skipped">
          No setups for {skipped.length === 1 ? "the too-thin expiry" : "the too-thin expiries"} {skipped.map((e) => day(e.expiry)).join(", ")}: too little open interest to price a structure honestly.
        </p>
      )}
    </Block>
  );
}

function IndexPanel({ x, together }: { x: IndexBlock; together: string[] }) {
  return (
    <div data-testid="mr-idx" data-symbol={x.symbol} className="flex min-w-0 flex-col" style={{ gap: 16 }}>
      <Snapshot x={x} />
      <TechnicalsStrip x={x} />
      {(x.levels.above.length > 0 || x.levels.below.length > 0) && (
        <Block id="mr-idx-levels" title="Levels around the close">
          <div className="flex min-w-0 flex-wrap" style={{ gap: "10px 24px" }}>
            <LevelList levels={x.levels.above} close={x.close} side="above" />
            <LevelList levels={x.levels.below} close={x.close} side="below" />
          </div>
        </Block>
      )}
      {x.read.length > 0 && (
        <Block id="mr-idx-read" title="Reading">
          <ul className="m-0" style={{ paddingLeft: 18, fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>{x.read.map((r) => <li key={r}>{r}</li>)}</ul>
        </Block>
      )}
      <Futures x={x} />
      <ExpiryTable x={x} />
      {together.length > 0 && (
        <Block id="mr-idx-together" title="Across expiries">
          <ul className="m-0" style={{ paddingLeft: 18, fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>{together.map((r) => <li key={r}>{r}</li>)}</ul>
        </Block>
      )}
      <SetupsByExpiry x={x} />
    </div>
  );
}

// ── shared: VIX, relative strength, FII / DII ───────────────────────────────────────────────────────────────────────

function Shared({ data }: { data: Data }) {
  const v = data.vix;
  const r = data.relative;
  if (!v && !r) return null;
  return (
    <div data-testid="mr-idx-shared" className="flex min-w-0 flex-wrap items-baseline" style={{ gap: "4px 18px", fontSize: 12.5, color: "var(--cp-ink-2)" }}>
      {v && (
        <span data-testid="mr-idx-vix">
          India VIX <span className="cp-num" style={{ color: "var(--cp-ink)" }}>{lvl(v.close)}</span>{" "}
          <span className="cp-num" style={{ color: tone(v.changePct) }}>{signed(v.changePct, "%")}</span>
          {v.closeAgo != null && <span className="cp-num" style={{ color: "var(--cp-ink-3)" }}> · {lvl(v.closeAgo)} five sessions ago ({signed(v.change5dPct, "%")})</span>}
          {v.upStreak != null && v.upStreak > 0 && <span style={{ color: "var(--cp-ink-3)" }}> · up {v.upStreak} session{v.upStreak === 1 ? "" : "s"} in a row</span>}
        </span>
      )}
      {r && (
        <span data-testid="mr-idx-relative">
          Bank Nifty minus Nifty: <span className="cp-num">1 day <span style={{ color: tone(r.bankMinusNifty1d) }}>{signed(r.bankMinusNifty1d, " pp")}</span> · 5 days{" "}
          <span style={{ color: tone(r.bankMinusNifty5d) }}>{signed(r.bankMinusNifty5d, " pp")}</span> · 20 days <span style={{ color: tone(r.bankMinusNifty20d) }}>{signed(r.bankMinusNifty20d, " pp")}</span></span>
        </span>
      )}
    </div>
  );
}

function Flows({ data }: { data: Data }) {
  const f = data.flows;
  if (!f || !f.days.length) return null;
  return (
    <Block id="mr-idx-flows" title="FII / DII cash · ₹ crore"
           aside={f.fii5d != null ? <>FII net over 5 sessions <span className="cp-num" style={{ color: tone(f.fii5d) }}>{crore(f.fii5d)}</span>{f.fiiBuyDays5 != null ? ` · net positive on ${f.fiiBuyDays5} of the last 5 sessions` : ""}</> : null}>
      <Scroll minWidth={320}>
        <thead><tr><th style={th}>Session</th><th style={thR}>FII net</th><th style={thR}>DII net</th></tr></thead>
        <tbody>
          {f.days.map((d) => (
            <tr key={d.date} data-testid="mr-flow-row" data-date={d.date}>
              <td style={td}>{day(d.date)}</td>
              <td style={{ ...tdR, color: tone(d.fii) }}>{crore(d.fii)}</td>
              <td style={{ ...tdR, color: tone(d.dii) }}>{crore(d.dii)}</td>
            </tr>
          ))}
        </tbody>
      </Scroll>
    </Block>
  );
}

// ── the part ─────────────────────────────────────────────────────────────────────────────────────────────────────────

function Ready({ data }: { data: Data }) {
  const [sym, setSym] = useState<string | null>(null);
  const current = data.indices.find((i) => i.symbol === sym) ?? data.indices[0] ?? null;
  return (
    <div data-testid="mr-indices-ready" data-as-of={data.asOf ?? ""} className="flex min-w-0 flex-col" style={{ gap: 14 }}>
      {data.indices.length > 1 && (
        <div role="group" aria-label="Index" data-testid="mr-idx-switch" className="flex flex-wrap" style={{ gap: 6 }}>
          {data.indices.map((i) => {
            const on = i.symbol === current?.symbol;
            return (
              <button key={i.symbol} type="button" data-testid="mr-idx-tab" data-symbol={i.symbol} aria-pressed={on} onClick={() => setSym(i.symbol)}
                      style={{
                        padding: "6px 14px", borderRadius: 999, fontSize: 13, cursor: "pointer",
                        border: `1px solid ${on ? "var(--mint)" : "var(--cp-line)"}`, background: on ? "var(--mint-soft, transparent)" : "transparent",
                        color: on ? "var(--cp-ink)" : "var(--cp-ink-2)",
                      }}>
                {i.name}
              </button>
            );
          })}
        </div>
      )}
      <Shared data={data} />
      {data.warnings.length > 0 && (
        <div role="note" data-testid="mr-idx-warnings" className="flex flex-col" style={{ gap: 4, padding: "8px 12px", borderRadius: 10, border: "1px solid var(--amber-line)", background: "var(--amber-soft)" }}>
          {data.warnings.map((w) => <span key={w} style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>{w}</span>)}
        </div>
      )}
      {current ? (
        <IndexPanel key={current.symbol} x={current} together={current.symbol === "NIFTY" ? data.together : []} />
      ) : (
        <p className="m-0" data-testid="mr-idx-empty" style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>No index reading for this session.</p>
      )}
      <Flows data={data} />
      <div className="flex min-w-0 flex-col" style={{ gap: 6 }}>
        {data.sources.length > 0 && (
          <ul className="m-0 flex flex-col p-0" style={{ listStyle: "none", gap: 2 }} data-testid="mr-idx-sources">
            {data.sources.map((s, i) => (
              <li key={i} style={note}>
                <span style={{ color: "var(--cp-ink-2)" }}>{s.what ?? "Source"}</span>{s.source ? ` — ${s.source}` : ""}{s.asOf ? ` · as of ${s.asOf}` : ""}
              </li>
            ))}
          </ul>
        )}
        {data.notes.length > 0 && <ul className="m-0" style={{ paddingLeft: 18, ...note }} data-testid="mr-idx-notes">{data.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
        <p className="m-0" data-testid="mr-idx-disclaimer" style={{ ...note, color: "var(--cp-ink-2)" }}>
          Conditional ideas from the close of {day(data.asOf)}, for research only — not investment advice. Premiums change at the open;
          check them live before acting on any of them.
        </p>
      </div>
    </div>
  );
}

export function RecoveryIndices() {
  const q = useRecoveryIndices();
  const asOf = q.data?.asOf;
  let body: ReactNode;
  if (q.isPending) {
    body = <LoadingBlock label="Loading Nifty and Bank Nifty (every live option expiry)" rows={4} />;
  } else if (q.isError) {
    const p = recoveryProblem(q.error);
    body = (
      <div role="alert" data-testid="mr-idx-error" data-code={p?.code ?? ""} className="flex flex-wrap items-start"
           style={{ gap: "8px 12px", padding: "10px 14px", borderRadius: 12, border: "1px solid var(--danger-line)", background: "var(--cp-danger-soft)" }}>
        <span className="cp-mono-note" style={{ color: "var(--cp-danger)", paddingTop: 2 }}>Error</span>
        <span style={{ flex: "1 1 240px", fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
          The index reading did not load{p?.message ? ` — ${p.message}` : ""}
        </span>
        <button type="button" onClick={() => q.refetch()} style={{ fontSize: 13, color: "var(--cp-ink)", background: "none", border: 0, cursor: "pointer" }}>Retry ›</button>
      </div>
    );
  } else {
    body = <Ready data={q.data} />;
  }
  return (
    <section data-testid="mr-indices" aria-label="Nifty and Bank Nifty" className="cp-card flex min-w-0 flex-col" style={{ gap: 12, padding: "14px 16px" }}>
      <header className="flex min-w-0 flex-wrap items-baseline" style={{ gap: "4px 12px" }}>
        <h3 className="cp-eyebrow m-0" style={{ flex: "1 1 auto" }}>2 · Nifty and Bank Nifty · each expiry</h3>
        {asOf && <span style={{ ...note, minWidth: 0 }}>Close of {day(asOf)} · end of day</span>}
      </header>
      {body}
    </section>
  );
}
