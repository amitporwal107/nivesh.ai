/**
 * Strategy Lab › Build a trade, step 3 — the option-chain picker. "+ Call", "+ Put" and "From chain" open it; each B / S
 * adds that contract as a leg (1 lot, the chain's close). Clicking B / S again on a contract already in the legs ADDS A
 * LOT to that leg (it does not toggle it off; remove a leg in the leg editor).
 *
 *   GET /api/fno/{symbol}/expiries and /api/fno/{symbol}/chain?expiry=   (trading/fno.ts useOptionChain)
 *
 * The walls are marked the way the Live chart's F&O setup marks them (fno-parts strikeTags / wallsOf: R the call wall,
 * S the put wall, MP max pain). Strikes and prices are only the chain's: a contract with no close shows "—" and cannot be
 * added at an invented price. The chain is the NSE bhavcopy (end of day); its age is shown and an old one is "stale".
 */
import { useEffect, useState, type CSSProperties } from "react";
import { LoadingBlock } from "../../../../../components/ui";
import { useCopilotShell } from "../../../../../lib/shell-context";
import { useOptionChain, type FnoStrike } from "../../../../trading/fno";
import { strikeTags } from "../../../fno-parts";
import { closeOfSide, fmtStrike, shortDay, type WLeg } from "./wizard-data";
import { Chip, mono, quietS } from "./ui";

const fmtQty = (n: number | null | undefined) => (n == null ? "—" : new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 }).format(n));
const fmtSigned = (n: number | null | undefined) => (n == null ? "—" : `${n > 0 ? "+" : n < 0 ? "−" : ""}${fmtQty(Math.abs(n))}`);

/** Calendar days between two YYYY-MM-DD dates. */
export function daysBetween(a: string, b: string): number {
  return Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86_400_000);
}
export const todayIso = () => new Date(Date.now() + 5.5 * 3600_000).toISOString().slice(0, 10);   // IST date
/** A chain older than its last session close plus a weekend is stale. */
export const STALE_DAYS = 3;

export function ChainPicker({ symbol, expiry, focus, legs, onAdd, onClose }: {
  symbol: string; expiry: string | null; focus: "call" | "put" | null; legs: WLeg[];
  onAdd: (side: "buy" | "sell", type: "call" | "put", strike: number, expiry: string, price: number, source: string) => void;
  onClose: () => void;
}) {
  const { mobile } = useCopilotShell();
  const [picked, setPicked] = useState<string | null>(expiry);
  const { list, state, expiry: shown } = useOptionChain(symbol, picked);
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  const chain = state.status === "ok" ? state.chain : null;
  const age = chain ? daysBetween(chain.summary.as_of, todayIso()) : null;
  const stale = age != null && age > STALE_DAYS;
  const added = (t: "call" | "put", strike: number, side: "buy" | "sell") =>
    legs.some((l) => l.kind === "option" && l.optionType === t && l.strike === strike && l.expiry === shown && l.side === side);
  const spot = chain?.summary.spot ?? null;
  const panel: CSSProperties = mobile
    ? { position: "fixed", inset: 0, zIndex: 80, background: "var(--bg-1)", display: "flex", flexDirection: "column" }
    : { position: "fixed", top: 0, right: 0, bottom: 0, width: "min(720px, 100vw)", zIndex: 80, background: "var(--bg-1)", borderLeft: "1px solid var(--line-2)", boxShadow: "-12px 0 40px rgba(0,0,0,0.35)", display: "flex", flexDirection: "column" };

  const side = (r: FnoStrike, t: "call" | "put") => {
    const px = closeOfSide(r, t);
    const s = r[t];
    const why = px == null ? "No close for this contract in the chain: it cannot be added at an invented price." : undefined;
    const btn = (sd: "buy" | "sell") => {
      const on = added(t, r.strike, sd);
      return (
        <button key={sd} type="button" data-testid={`wz-chain-${t}-${sd}-${r.strike}`} data-added={on ? "true" : "false"} aria-pressed={on} disabled={px == null || !chain || !shown} title={why ?? (on ? "Already in the legs: adds a lot" : undefined)}
          onClick={() => { if (px != null && chain && shown) onAdd(sd, t, r.strike, shown, px, `NSE F&O bhavcopy close, ${chain.summary.as_of}`); }}
          style={{ width: 26, height: 24, borderRadius: 6, fontSize: 11, fontWeight: 700, cursor: px == null ? "not-allowed" : "pointer", opacity: px == null ? 0.35 : 1,
            border: `1px solid ${sd === "buy" ? "var(--mint-line)" : "var(--cp-danger)"}`, color: on ? "var(--bg-1)" : sd === "buy" ? "var(--mint)" : "var(--cp-danger)",
            background: on ? (sd === "buy" ? "var(--mint)" : "var(--cp-danger)") : "transparent" }}>
          {sd === "buy" ? "B" : "S"}
        </button>
      );
    };
    const cells = [
      <td key="px" data-testid={`wz-chain-${t}-px-${r.strike}`} style={{ ...td, ...mono }}>{px == null ? "—" : fmtStrike(px)}</td>,
      <td key="oi" style={{ ...td, ...mono }}>{fmtQty(s?.oi)}</td>,
      <td key="chg" style={{ ...td, ...mono, color: (s?.change_in_oi ?? 0) < 0 ? "var(--cp-danger)" : "var(--cp-ink-2)" }}>{fmtSigned(s?.change_in_oi)}</td>,
      <td key="iv" style={{ ...td, ...mono }}>{s?.iv == null ? "—" : `${s.iv.toFixed(1)}`}</td>,
      <td key="bs" style={{ ...td, whiteSpace: "nowrap" }}><span className="inline-flex" style={{ gap: 4 }}>{btn("buy")}{btn("sell")}</span></td>,
    ];
    return t === "call" ? cells : [...cells].reverse();
  };

  return (
    <div role="dialog" aria-modal="true" aria-label={`${symbol} option chain`} data-testid="wz-chain" data-mobile={mobile ? "true" : "false"} style={panel}>
      <header className="flex flex-wrap items-center justify-between" style={{ gap: 8, padding: "12px 14px", borderBottom: "1px solid var(--line-2)" }}>
        <span className="flex min-w-0 flex-col" style={{ gap: 2 }}>
          <strong style={{ fontSize: 14 }}>{symbol} option chain{focus ? ` · add a ${focus}` : ""}</strong>
          {chain && (
            <span data-testid="wz-chain-age" data-stale={stale ? "true" : "false"} style={{ ...quietS, color: stale ? "var(--amber)" : "var(--cp-ink-3)" }}>
              NSE close of {shortDay(chain.summary.as_of)} · {age === 0 ? "today" : `${age} day${age === 1 ? "" : "s"} old`}{stale ? " · stale: prices are estimates, not quotes" : " · end-of-day closes, not live quotes"}
              {chain.lot_size != null ? ` · lot ${chain.lot_size}` : ""}
            </span>
          )}
        </span>
        <button type="button" data-testid="wz-chain-close" onClick={onClose} className="cp-btn" data-variant="ghost">Done</button>
      </header>
      <div className="flex flex-wrap items-center" style={{ gap: 6, padding: "10px 14px" }} role="group" aria-label="Expiry">
        {list.slice(0, 6).map((e) => (
          <Chip key={e.expiry} on={e.expiry === shown} testId={`wz-chain-expiry-${e.expiry}`} onClick={() => setPicked(e.expiry)}>{shortDay(e.expiry)} · {e.days_to_expiry}d</Chip>
        ))}
      </div>
      <div className="min-h-0 flex-1" style={{ overflow: "auto", padding: "0 14px 14px" }}>
        {state.status === "loading" && <LoadingBlock label={`Loading the ${symbol} chain`} rows={6} />}
        {state.status === "none" && <span data-testid="wz-chain-none" style={quietS}>{state.message}</span>}
        {state.status === "error" && <span data-testid="wz-chain-error" role="alert" style={{ ...quietS, color: "var(--amber)" }}>The chain did not load. <button type="button" className="cp-btn" data-variant="ghost" onClick={state.retry}>Retry</button></span>}
        {chain && (
          <table data-testid="wz-chain-table" style={{ width: "100%", minWidth: 600, borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr style={{ ...quietS, fontSize: 10.5, textAlign: "right" }}>
                <th colSpan={5} style={{ ...th, textAlign: "center", color: focus === "call" ? "var(--mint)" : undefined }}>CALLS</th>
                <th style={th} />
                <th colSpan={5} style={{ ...th, textAlign: "center", color: focus === "put" ? "var(--mint)" : undefined }}>PUTS</th>
              </tr>
              <tr style={{ ...quietS, fontSize: 10, textAlign: "right" }}>
                {["Close", "OI", "OI chg", "IV", ""].map((h, i) => <th key={`c${i}`} style={th}>{h}</th>)}
                <th style={{ ...th, textAlign: "center" }}>Strike</th>
                {["", "IV", "OI chg", "OI", "Close"].map((h, i) => <th key={`p${i}`} style={th}>{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {chain.strikes.map((r, i) => {
                const tags = strikeTags(chain.summary, r.strike);
                const atm = tags.includes("ATM");
                const prev = chain.strikes[i - 1];
                const spotHere = spot != null && prev != null && prev.strike < spot && r.strike >= spot;
                return [
                  spotHere ? (
                    <tr key={`spot${r.strike}`} data-testid="wz-chain-spot"><td colSpan={11} style={{ padding: "2px 0", textAlign: "center", fontSize: 10.5, color: "var(--amber)", borderTop: "1px dashed var(--amber)" }}>Spot {fmtStrike(spot as number)}</td></tr>
                  ) : null,
                  <tr key={r.strike} data-testid="wz-chain-row" data-strike={r.strike} data-atm={atm ? "true" : "false"} style={{ background: atm ? "var(--mint-soft)" : undefined, borderTop: "1px solid var(--cp-line)", textAlign: "right" }}>
                    {side(r, "call")}
                    <td style={{ ...td, ...mono, textAlign: "center", fontWeight: 600, whiteSpace: "nowrap" }}>
                      {fmtStrike(r.strike)}
                      {tags.filter((t) => t !== "ATM").map((t) => (
                        <span key={t} data-testid={`wz-chain-tag-${t}`} title={t === "R" ? "Call wall (most call OI at or above the spot)" : t === "S" ? "Put wall (most put OI at or below the spot)" : "Max pain"}
                          style={{ marginLeft: 4, padding: "0 4px", borderRadius: 4, fontSize: 9.5, color: t === "R" ? "var(--cp-danger)" : t === "S" ? "var(--mint)" : "var(--cp-ink-3)", border: "1px solid currentColor" }}>{t}</span>
                      ))}
                      {atm && <span style={{ marginLeft: 4, fontSize: 9.5, color: "var(--mint)" }}>ATM</span>}
                    </td>
                    {side(r, "put")}
                  </tr>,
                ];
              })}
            </tbody>
          </table>
        )}
        <p className="m-0" style={{ ...quietS, marginTop: 10 }}>
          B buys and S sells one lot at the chain&rsquo;s close; pressing it again on a contract already in the legs adds a lot. A contract with no close shows “—” and cannot be added. IV is the chain&rsquo;s model estimate (Black-76). R and S mark the call and put walls (most open interest), MP max pain.
        </p>
      </div>
    </div>
  );
}

const th: CSSProperties = { padding: "4px 6px", fontWeight: 600 };
const td: CSSProperties = { padding: "5px 6px" };
