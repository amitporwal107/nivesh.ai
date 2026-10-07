/**
 * Live Watch — a personal, colour-coded companion to the Estimates view (owner request, 2026-10-07).
 *
 * The Estimates/History views deliberately render both directions in neutral ink (moveOdds.css: "Direction is
 * never colour-coded... mint is interface chrome only") because this project's own research found direction is
 * not predictable, and the one breakout rule built on this data (move_odds_live.py's five checks) lost money in
 * its pre-registered 2025 backtest. This panel is kept separate rather than recolouring that shared table: it
 * exists only to make "has today's published level already been reached" visually scannable at a glance, for
 * whoever has this tab open — it is not a call, a signal, or a recommendation, and says so up front.
 *
 * Ranking reuses the estimates MoveOddsScreen already fetched for every head (no extra network call); only the
 * live price overlay is fetched here, on its own 30s timer, independent of the main screen's 60s one.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { fetchLive, type LiveQuote, type LiveResult, type MoveHead, type MoveLatestResult, type MoveRow } from "@/services/adapters/moveOdds.adapter";
import "./moveOdds.css";

const REFRESH_MS = 30_000;
const TOP_N = 20;
const HEADS: ReadonlyArray<{ head: MoveHead; label: string }> = [
  { head: "p_up5_1d", label: `Top ${TOP_N} · High ≥ +5% estimate` },
  { head: "p_up10_1d", label: `Top ${TOP_N} · High ≥ +10% estimate` },
];

type Band = "reached" | "rising" | "flat" | "nodata";
const BAND_LABEL: Record<Band, string> = { reached: "Reached", rising: "Rising", flat: "Flat / down", nodata: "No live price" };

function bandOf(q: LiveQuote | undefined, head: MoveHead): Band {
  if (!q || q.error || q.change_pct == null) return "nodata";
  if (q.touched?.[head]) return "reached";
  return q.change_pct > 0 ? "rising" : "flat";
}
function pct1(p: number): string { return `${(p * 100).toFixed(1)}%`; }
function money(v: number | null | undefined): string { return v == null ? "—" : `₹${v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`; }
function signedPct(v: number | null | undefined): string { return v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(2)}%`; }

export function LiveWatchPanel({ results, onNoAccess }: {
  results: Partial<Record<MoveHead, MoveLatestResult>>;
  onNoAccess: () => void;
}) {
  const lists = useMemo(() => HEADS.map(({ head, label }) => {
    const r = results[head];
    const rows: MoveRow[] = r?.kind === "final" ? r.data.rows.slice(0, TOP_N) : [];
    return { head, label, rows, kind: r?.kind ?? null, expected: r && "data" in r ? (r.data as { expected_session: string }).expected_session : null };
  }), [results]);

  const symbolsKey = useMemo(() => Array.from(new Set(lists.flatMap((l) => l.rows.map((r) => r.symbol)))).sort().join(","), [lists]);

  const [live, setLive] = useState<LiveResult | null>(null);
  const onNoAccessRef = useRef(onNoAccess);
  onNoAccessRef.current = onNoAccess;

  useEffect(() => {
    const symbols = symbolsKey ? symbolsKey.split(",") : [];
    if (!symbols.length) { setLive(null); return; }
    let cancelled = false;
    const pull = () => {
      fetchLive(symbols).then((r) => {
        if (cancelled) return;
        if (r.kind === "no_access") { onNoAccessRef.current(); return; }
        setLive(r);
      });
    };
    pull();
    const id = window.setInterval(pull, REFRESH_MS);
    return () => { cancelled = true; window.clearInterval(id); };
  }, [symbolsKey]);

  const quotes: Record<string, LiveQuote> = live?.kind === "ok" ? Object.fromEntries(live.data.quotes.map((q) => [q.symbol, q])) : {};

  return (
    <div className="mo-livewatch" data-testid="mo-livewatch">
      <p className="mo-disc" data-testid="mo-livewatch-disclaimer">
        <b>PERSONAL VIEW — NOT A SIGNAL</b> Colour shows only whether today&apos;s published level has already been reached
        by the session high/low (Reached), the price is currently moving that way (Rising), or neither (Flat / down).
        It does not predict direction: this project&apos;s own pre-registered breakout rule on this exact data lost money
        in its 2025 backtest (see the Estimates view&apos;s Diagnostics). Prices are Yahoo Finance, delayed up to about a
        minute, refreshed every 30 seconds while this tab stays open.
      </p>
      {live?.kind === "error" && (
        <p className="mo-mini" role="alert" data-testid="mo-livewatch-error">
          Live prices unavailable ({live.message}) — showing the ranking only.
        </p>
      )}
      {lists.map(({ head, label, rows, kind }) => (
        <section key={head} className="mo-livewatch-section" data-testid={`mo-livewatch-${head}`}>
          <h3 className="mo-livewatch-h">{label}</h3>
          {kind !== "final" && <p className="mo-mini">No published estimate for this head right now.</p>}
          {kind === "final" && rows.length === 0 && <p className="mo-mini">No scored rows.</p>}
          {rows.length > 0 && (
            <ul className="mo-livewatch-list">
              {rows.map((r) => {
                const q = quotes[r.symbol];
                const band = bandOf(q, head);
                return (
                  <li key={r.symbol} className={`mo-livewatch-row mo-band-${band}`} data-testid={`mo-livewatch-row-${head}-${r.symbol}`}>
                    <span className="mo-livewatch-sym">{r.symbol}</span>
                    <span className="mo-livewatch-est">est. {pct1(r.p)}</span>
                    <span className="mo-livewatch-px">{money(q?.last)}</span>
                    <span className="mo-livewatch-chg">{signedPct(q?.change_pct)}</span>
                    <span className="mo-livewatch-badge" data-testid={`mo-livewatch-band-${head}-${r.symbol}`}>{BAND_LABEL[band]}</span>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      ))}
    </div>
  );
}
