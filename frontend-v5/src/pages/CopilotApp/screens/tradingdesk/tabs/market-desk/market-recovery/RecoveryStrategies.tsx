/**
 * Market Desk › Market Recovery — "Strategies with protection against a fall" (DESIGN §8 "downside protection"; the desk lint bans
 * the word "downside", so the screen says "protection against a fall") inside a candidate's open detail (owner, 4 Nov 2026;
 * docs/market_recovery/DESIGN.md §8). Reads GET /api/market-recovery/strategies/{symbol} only while the detail is open.
 *
 *   kind "options"       the five strategies the owner listed, for one lot on the chosen expiry: protective put, bull call
 *                        spread, collar, bull put credit spread, put ratio backspread. All five are shown; one that fails a
 *                        Strategy Builder check (or cannot be built) is greyed and says why, still readable.
 *   kind "index_hedge"   the stock has no stock options on NSE: one Nifty put lot sized by the stock's beta, with the
 *                        server's caveat (a market-wide fall only) shown in full.
 *
 * Wording: the owner chose the standard trading words for THIS page — the plan labels (Entry zone · Stop loss · Target 1 ·
 * Target 2, 3 Nov) and the leg verbs Buy / Sell (4 Nov). Each leg reads "<Buy|Sell> <n> lot(s) · …" so the page's lint
 * (e2e/tests/copilot-app-market-recovery.spec.ts TC-E5) can allow the verbs only in that position. Every figure, label,
 * check and note is the server's; this screen formats and arranges them. Prices are end of day, dated in the header.
 */
import { useState, type CSSProperties, type KeyboardEvent, type PointerEvent } from "react";
import { LoadingBlock, Pill, type Tone } from "../../../../../components/ui";
import { recoveryProblem } from "./market-recovery-data";
import {
  useRecoveryStrategies,
  type IndexHedge, type Leg, type RecoveryStrategies as Data, type Strategy, type StrategyCheck,
} from "./market-recovery-strategies";

// ── formatting ───────────────────────────────────────────────────────────────────────────────────────────────────────

const DASH = "—";
const MINUS = "−";
const price = (v: number | null | undefined) => (v == null ? DASH : v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const strike = (v: number | null | undefined) => (v == null ? DASH : v.toLocaleString("en-IN", { maximumFractionDigits: 2 }));
/** Whole-position rupees, signed ("+₹1,200.00", "−₹860.50"). */
const rs = (v: number | null | undefined, signedOut = true) =>
  v == null ? DASH : `${signedOut ? (v < 0 ? MINUS : v > 0 ? "+" : "") : v < 0 ? MINUS : ""}₹${Math.abs(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const rsAbs = (v: number | null | undefined) => (v == null ? DASH : `₹${Math.abs(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);
const rsRound = (v: number | null | undefined) => (v == null ? DASH : `₹${Math.round(Math.abs(v)).toLocaleString("en-IN")}`);
const fixed = (v: number | null | undefined, dp = 1) => (v == null ? DASH : v.toFixed(dp));
const tone = (v: number | null | undefined) => (v == null ? "var(--cp-ink-4)" : v > 0 ? "var(--mint)" : v < 0 ? "var(--cp-danger)" : "var(--cp-ink-2)");
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function day(iso: string | null | undefined): string {
  const m = iso ? /^(\d{4})-(\d{2})-(\d{2})/.exec(iso) : null;
  return m ? `${Number(m[3])} ${MONTHS[Number(m[2]) - 1] ?? m[2]} ${m[1]}` : iso ?? DASH;
}

const note: CSSProperties = { fontSize: 11.5, lineHeight: 1.5, color: "var(--cp-ink-3)" };
const th: CSSProperties = {
  padding: "5px 6px", textAlign: "left", fontFamily: "var(--mono)", fontSize: 9, letterSpacing: "0.1em", textTransform: "uppercase",
  color: "var(--cp-ink-4)", fontWeight: 500, borderBottom: "1px solid var(--cp-line)", whiteSpace: "nowrap",
};
const thR: CSSProperties = { ...th, textAlign: "right" };
const td: CSSProperties = {
  padding: "5px 6px", fontSize: 12, color: "var(--cp-ink-2)", borderBottom: "1px solid var(--cp-line)", fontFamily: "var(--mono)",
  fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap", verticalAlign: "top",
};
const tdR: CSSProperties = { ...td, textAlign: "right" };
const tdText: CSSProperties = { ...td, fontFamily: "var(--sans)", whiteSpace: "normal" };
const dt: CSSProperties = { color: "var(--cp-ink-3)" };

const STATUS: Record<string, { label: string; tone: Tone }> = {
  passes: { label: "Passes the checks", tone: "mint" },
  fails: { label: "Fails a check", tone: "amber" },
  unavailable: { label: "Not available", tone: "ink" },
};
const FLAG_TEXT: Record<string, string> = {
  low_oi: "low open interest", low_volume: "low volume", abnormal_iv: "unusual implied volatility", missing_iv: "no implied volatility",
  missing_greeks: "no Greeks", zero_open_interest: "no open interest", no_trades_today: "no trades on the day", missing_premium: "no premium",
};

// ── pieces ───────────────────────────────────────────────────────────────────────────────────────────────────────────

/** "Buy 1 lot · 2,300 Put @ 61.50" — the verb is followed by the lot count, always (the page's wording lint relies on it). */
function legText(l: Leg): string {
  const lots = l.lots == null ? "" : ` ${l.lots} lot${l.lots === 1 ? "" : "s"}`;
  const what = l.instrument.toLowerCase() === "shares"
    ? `${l.units == null ? "" : `${l.units.toLocaleString("en-IN")} `}shares`
    : `${strike(l.strike)} ${l.instrument}`;
  return `${l.action}${lots} · ${what} @ ${price(l.price)}`;
}

function Legs({ legs }: { legs: Leg[] }) {
  if (!legs.length) return null;
  return (
    <ul className="m-0 flex flex-col p-0" style={{ listStyle: "none", gap: 3 }} data-testid="mr-strat-legs">
      {legs.map((l, i) => (
        <li key={i} className="flex min-w-0 flex-wrap items-baseline" style={{ gap: "2px 8px", fontSize: 12.5 }}>
          <span data-testid="mr-strat-leg" data-action={l.action} className="cp-num" style={{ color: "var(--cp-ink)" }}>{legText(l)}</span>
          {l.priceBasis && l.priceBasis !== "close" && <span style={note}>(settlement price: did not trade)</span>}
          {l.flags.length > 0 && <span style={{ ...note, color: "var(--amber)" }}>{l.flags.map((f) => FLAG_TEXT[f] ?? f.replace(/_/g, " ")).join(", ")}</span>}
        </li>
      ))}
    </ul>
  );
}

function Checks({ checks }: { checks: StrategyCheck[] }) {
  if (!checks.length) return null;
  return (
    <ul className="m-0 flex flex-col p-0" style={{ listStyle: "none", gap: 2 }} data-testid="mr-strat-checks">
      {checks.map((c) => (
        <li key={c.id} data-testid="mr-strat-check" data-id={c.id} data-pass={c.pass === null ? "unknown" : String(c.pass)}
            className="flex min-w-0 items-baseline" style={{ gap: 8, fontSize: 12, color: "var(--cp-ink-2)" }}>
          <span aria-hidden style={{ width: 10, flex: "none", fontWeight: 700, color: c.pass === true ? "var(--mint)" : c.pass === false ? "var(--cp-danger)" : "var(--cp-ink-4)" }}>
            {c.pass === true ? "✓" : c.pass === false ? "✗" : "–"}
          </span>
          <span className="sr-only">{c.pass === true ? "Passed:" : c.pass === false ? "Failed:" : "Not applied:"}</span>
          <span style={{ minWidth: 0 }}>{c.label}{c.detail ? <span style={{ color: "var(--cp-ink-3)" }}> · {c.detail}</span> : null}</span>
        </li>
      ))}
    </ul>
  );
}

/** The payoff at expiry: one 2px line, a labelled zero line, the close marked; pointer or arrow keys read a price. */
function PayoffSpark({ points, close, label }: { points: Array<[number, number]>; close: number | null; label: string }) {
  const [hover, setHover] = useState<number | null>(null);
  if (points.length < 2) return null;
  const W = 300, H = 92, PL = 6, PR = 6, PT = 10, PB = 14;
  const xs = points.map((p) => p[0]), ys = points.map((p) => p[1]);
  const x0 = xs[0], x1 = xs[xs.length - 1];
  const lo0 = Math.min(0, ...ys), hi0 = Math.max(0, ...ys);
  const pad = (hi0 - lo0 || 1) * 0.08;
  const lo = lo0 - pad, hi = hi0 + pad;
  const x = (v: number) => PL + ((v - x0) / (x1 - x0 || 1)) * (W - PL - PR);
  const y = (v: number) => PT + (H - PT - PB) * (1 - (v - lo) / (hi - lo || 1));
  const d = points.map((p, i) => `${i ? "L" : "M"}${x(p[0]).toFixed(1)} ${y(p[1]).toFixed(1)}`).join("");
  const zy = y(0);
  const pick = (clientX: number, box: DOMRect) => {
    const px = ((clientX - box.left) / box.width) * W;
    let best = 0, gap = Infinity;
    points.forEach((p, i) => { const g = Math.abs(x(p[0]) - px); if (g < gap) { gap = g; best = i; } });
    return best;
  };
  // Arrow keys start from the point nearest the close (the middle when there is no close).
  const nearClose = close == null ? Math.floor(points.length / 2)
    : points.reduce((bi, p, i) => (Math.abs(p[0] - close) < Math.abs(points[bi][0] - close) ? i : bi), 0);
  const onMove = (e: PointerEvent<SVGSVGElement>) => setHover(pick(e.clientX, e.currentTarget.getBoundingClientRect()));
  const onKey = (e: KeyboardEvent<SVGSVGElement>) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const start = hover ?? nearClose;
    setHover(Math.max(0, Math.min(points.length - 1, start + (e.key === "ArrowLeft" ? -1 : 1))));
  };
  const h = hover == null ? null : points[hover];
  const best = Math.max(...ys), worst = Math.min(...ys);
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 4 }} data-testid="mr-strat-payoff">
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img" tabIndex={0}
           aria-label={`${label}: profit or loss at expiry for prices ${price(x0)} to ${price(x1)}; between ${rs(worst)} and ${rs(best)} on this range. Use the left and right arrow keys to read a price.`}
           style={{ overflow: "visible", cursor: "crosshair", maxWidth: "100%" }}
           onPointerMove={onMove} onPointerLeave={() => setHover(null)} onKeyDown={onKey} onBlur={() => setHover(null)}>
        {/* zones: a faint tint plus a word, so profit and loss are not told apart by colour alone */}
        {zy > PT && <rect x={PL} y={PT} width={W - PL - PR} height={Math.max(0, zy - PT)} fill="var(--mint)" opacity="0.06" />}
        {zy < H - PB && <rect x={PL} y={zy} width={W - PL - PR} height={Math.max(0, H - PB - zy)} fill="var(--cp-danger)" opacity="0.06" />}
        {hi0 > 0 && <text x={PL + 2} y={PT + 8} fontSize="8.5" fill="var(--cp-ink-4)">profit</text>}
        {lo0 < 0 && <text x={PL + 2} y={H - PB - 3} fontSize="8.5" fill="var(--cp-ink-4)">loss</text>}
        <line x1={PL} x2={W - PR} y1={zy} y2={zy} stroke="var(--cp-ink-4)" strokeWidth="1" strokeDasharray="3 3" />
        <text x={W - PR} y={zy - 3} textAnchor="end" fontSize="8.5" fill="var(--cp-ink-4)" className="cp-num">₹0</text>
        {close != null && close >= x0 && close <= x1 && (
          <g>
            <line x1={x(close)} x2={x(close)} y1={PT} y2={H - PB} stroke="var(--cp-ink-3)" strokeWidth="1" strokeDasharray="1 3" />
            <text x={x(close)} y={H - 3} textAnchor="middle" fontSize="8.5" fill="var(--cp-ink-3)" className="cp-num">close {price(close)}</text>
          </g>
        )}
        <path d={d} fill="none" stroke="var(--cp-ink)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        {h && (
          <g>
            <line x1={x(h[0])} x2={x(h[0])} y1={PT} y2={H - PB} stroke="var(--cp-ink-4)" strokeWidth="1" />
            <circle cx={x(h[0])} cy={y(h[1])} r="4" fill={h[1] >= 0 ? "var(--mint)" : "var(--cp-danger)"} stroke="var(--bg-1)" strokeWidth="2" />
          </g>
        )}
      </svg>
      <span aria-live="polite" className={h ? "cp-num" : undefined} style={{ minHeight: 16, fontSize: 11.5, color: h ? "var(--cp-ink-2)" : "var(--cp-ink-4)" }}>
        {h ? `At ${price(h[0])} at expiry: ${h[1] >= 0 ? "profit" : "loss"} ${rsAbs(h[1])}` : "Point at or focus the payoff to read a price."}
      </span>
    </div>
  );
}

/** "2.9 : 1"; "Not applied" when the server's reward : risk check is not applied to this structure (the put ratio backspread,
 *  judged by its loss zone — the check's own line says why). */
function rrText(s: Strategy): string {
  if (s.rewardRisk != null) return `${fixed(s.rewardRisk, 2)} : 1`;       // 2 decimals, as the server's check detail ("0.25 : 1")
  return s.checks.some((c) => c.id === "reward_risk" && c.pass === null) ? "Not applied" : DASH;
}

function premiumText(s: Strategy): string {
  if (s.netPremium == null) return DASH;
  const word = s.netPremium < 0 ? "debit" : s.netPremium > 0 ? "credit" : "nil";
  const per = s.netPremiumPerShare == null ? "" : ` (${rsAbs(s.netPremiumPerShare)} a share)`;
  return `${rsAbs(s.netPremium)} ${word}${per}`;
}

function StrategyCard({ s, close }: { s: Strategy; close: number | null }) {
  const st = STATUS[s.status] ?? { label: s.status, tone: "ink" as Tone };
  const ok = s.status === "passes";
  const unhedged = s.scenarios.some((r) => r.pnlUnhedged != null);
  return (
    <article data-testid="mr-strat" data-key={s.key} data-status={s.status} className="flex min-w-0 flex-col"
             style={{ gap: 8, padding: "10px 12px", borderRadius: 10, border: "1px solid var(--cp-line)", background: ok ? "var(--bg-1)" : "transparent" }}>
      <header className="flex min-w-0 flex-wrap items-center" style={{ gap: "4px 10px" }}>
        <h4 className="m-0" style={{ fontSize: 14, fontWeight: 600, color: ok ? "var(--cp-ink)" : "var(--cp-ink-2)", flex: "1 1 auto" }}>{s.label}</h4>
        <span data-testid="mr-strat-status"><Pill tone={st.tone}>{st.label}</Pill></span>
      </header>
      {s.why && (
        // Full strength even when the card is greyed: the reason is the point.
        <p className="m-0" data-testid="mr-strat-why" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--amber)" }}>{s.why}</p>
      )}
      <div className="flex min-w-0 flex-col" style={{ gap: 8, opacity: ok ? 1 : 0.62 }} data-testid="mr-strat-body">
        {s.bestWhen && <p className="m-0" style={note}>{s.bestWhen}</p>}
        <Legs legs={s.legs} />
        <dl className="m-0 grid" style={{ gridTemplateColumns: "auto 1fr", gap: "2px 10px", fontSize: 12 }}>
          <dt style={dt}>Net premium</dt><dd className="cp-num m-0" data-testid="mr-strat-premium">{premiumText(s)}</dd>
          {s.outlay != null && (<><dt style={dt}>Cash at the start</dt><dd className="cp-num m-0">{rsAbs(s.outlay)} {s.outlay < 0 ? "paid" : "received"}</dd></>)}
          <dt style={dt}>Max profit</dt><dd className="cp-num m-0" data-testid="mr-strat-max-profit">{s.profitUnbounded ? "Unlimited" : rs(s.maxProfit)}</dd>
          <dt style={dt}>Max loss</dt>
          <dd className="cp-num m-0" data-testid="mr-strat-max-loss">
            {rs(s.maxLoss)}
            {s.maxLossWithCosts != null ? <span style={{ display: "block", color: "var(--cp-ink-3)", whiteSpace: "nowrap" }}>{rs(s.maxLossWithCosts)} with costs</span> : null}
          </dd>
          <dt style={dt}>Breakeven{s.breakevens.length === 1 ? "" : "s"}</dt><dd className="cp-num m-0">{s.breakevens.length ? s.breakevens.map(price).join(", ") : DASH}</dd>
          <dt style={dt}>Reward : risk</dt><dd className="cp-num m-0" data-testid="mr-strat-rr">{rrText(s)}</dd>
          {s.costsRoundTrip != null && (<><dt style={dt}>Costs (round trip)</dt><dd className="cp-num m-0">{rsAbs(s.costsRoundTrip)}</dd></>)}
        </dl>
        {s.scenarios.length > 0 && (
          <div className="cp-scroll" style={{ overflowX: "auto", maxWidth: "100%" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", minWidth: unhedged ? 300 : 230 }} data-testid="mr-strat-scenarios">
              <thead>
                <tr>
                  <th style={th} scope="col">At expiry</th><th style={thR} scope="col">Price</th><th style={thR} scope="col">P&amp;L</th>
                  {unhedged && <th style={thR} scope="col">Shares alone</th>}
                </tr>
              </thead>
              <tbody>
                {s.scenarios.map((r) => (
                  <tr key={r.label}>
                    <td style={{ ...tdText, minWidth: 104 }}>{r.label}</td>
                    <td style={tdR}>{price(r.price)}</td>
                    <td style={{ ...tdR, color: tone(r.pnl) }}>{rs(r.pnl)}</td>
                    {unhedged && <td style={{ ...tdR, color: tone(r.pnlUnhedged) }}>{rs(r.pnlUnhedged)}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <PayoffSpark points={s.payoff} close={close} label={s.label} />
        <Checks checks={s.checks} />
      </div>
    </article>
  );
}

function IndexHedgeCard({ h, symbol }: { h: IndexHedge; symbol: string }) {
  // The server's verdict when it sends one; otherwise read from the checks.
  const known = h.checks.filter((c) => c.pass !== null);
  const status = h.status ?? (known.length && known.every((c) => c.pass) ? "passes" : known.some((c) => c.pass === false) ? "fails" : "unavailable");
  const st = STATUS[status] ?? { label: status, tone: "ink" as Tone };
  const index = h.index ?? "NIFTY";
  const priced = h.putStrike != null;
  return (
    <article data-testid="mr-hedge" data-status={status} className="flex min-w-0 flex-col"
             style={{ gap: 8, padding: "10px 12px", borderRadius: 10, border: "1px solid var(--cp-line)", background: "var(--bg-1)", maxWidth: 640 }}>
      <header className="flex min-w-0 flex-wrap items-center" style={{ gap: "4px 10px" }}>
        <h4 className="m-0" style={{ fontSize: 14, fontWeight: 600, color: "var(--cp-ink)", flex: "1 1 auto" }}>Nifty put hedge</h4>
        <span data-testid="mr-hedge-status"><Pill tone={st.tone}>{st.label}</Pill></span>
      </header>
      <p className="m-0" style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
        {symbol} has no stock options on NSE, so the protection is a put on the index.
      </p>
      {h.why && <p className="m-0" data-testid="mr-hedge-why" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--amber)" }}>{h.why}</p>}
      {priced && (
        // §8: one Nifty put lot.
        <span data-testid="mr-strat-leg" data-action="Buy" className="cp-num" style={{ fontSize: 12.5, color: "var(--cp-ink)" }}>
          {`Buy 1 lot · ${index} ${strike(h.putStrike)} Put @ ${price(h.premium)}`}
          {h.priceBasis && h.priceBasis !== "close" && <span style={note}> (settlement price: did not trade)</span>}
        </span>
      )}
      <dl className="m-0 grid" style={{ gridTemplateColumns: "auto 1fr", gap: "2px 10px", fontSize: 12 }}>
        <dt style={dt}>Expiry</dt><dd className="cp-num m-0">{day(h.expiry)}{h.daysToExpiry != null ? ` · ${h.daysToExpiry} days` : ""}</dd>
        <dt style={dt}>Lot</dt><dd className="cp-num m-0">{h.lotSize ?? DASH} units · {index} at {price(h.spot)}</dd>
        <dt style={dt}>Cost per lot</dt><dd className="cp-num m-0" data-testid="mr-hedge-cost">{rsAbs(h.costPerLot)}{h.costPct != null ? ` · ${fixed(h.costPct, 2)}% of the value it hedges` : ""}</dd>
        <dt style={dt}>Covers</dt>
        <dd className="m-0" data-testid="mr-hedge-covers" style={{ color: "var(--cp-ink)" }}>
          One lot hedges about <span className="cp-num">{rsRound(h.hedgedValue)}</span> of {symbol} (beta <span className="cp-num">{fixed(h.beta, 2)}</span>)
        </dd>
        {/* Only the distance: the server caps it, so it is not always the stock's Stop loss distance ÷ beta. */}
        {h.fallUsedPct != null && (<><dt style={dt}>Put strike</dt><dd className="m-0">within {fixed(h.fallUsedPct)}% under {index}’s close</dd></>)}
      </dl>
      {h.sizing && <p className="m-0" data-testid="mr-hedge-sizing" style={note}>{h.sizing}</p>}
      {h.scenarios.length > 0 && (
        <div className="cp-scroll" style={{ overflowX: "auto", maxWidth: "100%" }}>
          {/* The server's label names the move ("Nifty -5%"); a separate move column only repeated it. */}
          <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 270 }} data-testid="mr-hedge-scenarios">
            <thead>
              <tr><th style={th} scope="col">If</th><th style={thR} scope="col">Put P&amp;L</th><th style={thR} scope="col">Stock loss (beta)</th></tr>
            </thead>
            <tbody>
              {h.scenarios.map((r) => (
                <tr key={r.label} data-move={r.niftyMovePct ?? ""}>
                  <td style={tdText}>{r.label}</td>
                  <td style={{ ...tdR, color: tone(r.putPnl) }}>{rs(r.putPnl)}</td>
                  <td style={{ ...tdR, color: tone(r.stockLoss) }}>{rs(r.stockLoss)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Checks checks={h.checks} />
      {h.caveat && (
        <p className="m-0" data-testid="mr-hedge-caveat" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--amber)" }}>{h.caveat}</p>
      )}
    </article>
  );
}

// ── the section ──────────────────────────────────────────────────────────────────────────────────────────────────────

function headerLine(d: Data): string {
  const h = d.indexHedge;
  const expiry = d.expiry ?? h?.expiry ?? null;
  const days = d.daysToExpiry ?? h?.daysToExpiry ?? null;
  // The index hedge's own card names the Nifty lot; the header's lot is the stock's.
  const lot = d.kind === "index_hedge" ? null : d.lotSize;
  const parts = [
    expiry ? `Expiry ${day(expiry)}${days != null ? ` · ${days} days` : ""}` : null,
    lot != null ? `lot ${lot.toLocaleString("en-IN")}` : null,
    d.asOf ? `end-of-day prices of ${day(d.asOf)}` : "end-of-day prices",
  ].filter(Boolean);
  return parts.join(" · ");
}

function Body({ d, symbol }: { d: Data; symbol: string }) {
  const close = d.plan?.close ?? d.spot;
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 10 }}>
      <span style={note} data-testid="mr-strats-header">{headerLine(d)}</span>
      {d.kind === "index_hedge" && d.indexHedge ? (
        <IndexHedgeCard h={d.indexHedge} symbol={d.symbol ?? symbol} />
      ) : d.strategies.length ? (
        // Two across on a desktop detail (~900 px): the scenario table needs ~380 px to read without wrapping.
        <div className="grid min-w-0" style={{ gap: 10, gridTemplateColumns: "repeat(auto-fill, minmax(min(100%, 380px), 1fr))" }} data-testid="mr-strats-grid">
          {d.strategies.map((s) => <StrategyCard key={s.key} s={s} close={close} />)}
        </div>
      ) : (
        <p className="m-0" data-testid="mr-strats-empty" style={{ fontSize: 12.5, color: "var(--cp-ink-2)" }}>No strategies were returned for {symbol}.</p>
      )}
      {(d.notes.length > 0 || d.warnings.length > 0) && (
        <ul className="m-0" data-testid="mr-strats-notes" style={{ paddingLeft: 18, ...note }}>
          {d.warnings.map((w) => <li key={`w-${w}`} style={{ color: "var(--amber)" }}>{w}</li>)}
          {d.notes.map((n) => <li key={`n-${n}`}>{n}</li>)}
        </ul>
      )}
      {d.sources.length > 0 && (
        <p className="m-0" style={{ ...note, fontSize: 11 }} data-testid="mr-strats-sources">
          {d.sources.map((s) => [s.what, s.source].filter(Boolean).join(": ") + (s.asOf ? ` (${day(s.asOf)})` : "")).join(" · ")}
        </p>
      )}
    </div>
  );
}

/** Mounted only inside an open detail, so the request goes out only then. */
export function RecoveryStrategies({ symbol }: { symbol: string }) {
  const q = useRecoveryStrategies(symbol, true);
  const problem = recoveryProblem(q.error);
  return (
    <section aria-label={`Strategies with protection against a fall for ${symbol}`} data-testid="mr-strats" data-symbol={symbol}
             className="flex min-w-0 flex-col" style={{ gap: 8, gridColumn: "1 / -1", paddingTop: 10, borderTop: "1px solid var(--cp-line)" }}>
      <span className="cp-mono-note" data-testid="mr-strats-title">Strategies with protection against a fall · 1 lot</span>
      {q.isPending ? (
        <LoadingBlock label={`Loading strategies for ${symbol}`} rows={2} />
      ) : problem ? (
        <p className="m-0" role="alert" data-testid="mr-strats-error" data-code={problem.code} style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
          {problem.message}
        </p>
      ) : q.data ? (
        <Body d={q.data} symbol={symbol} />
      ) : null}
    </section>
  );
}
