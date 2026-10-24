/**
 * Smart trading desk — Options & futures lab · Option chain with an Analyse panel. Design: the Sensibull-style reference (B and S buttons on each strike; a floating Analyse panel with the
 * trades, the net premium, the summary, the payoff and what-if controls) built on this desk's own pieces: the chain's end-of-day closes, POST /api/desk/strategy/payoff and POST /api/fno/margin.
 *
 * Clicking B or S on a strike adds that leg (priced at the end-of-day close); clicking it again takes it off. The panel is the Builder in its `panel` variant: it works out no payoff, Greek, cost or
 * margin figure itself, and ends in no order button (Nivesh places no orders; recording an option structure as a paper trade is not available). The panel can be dragged, minimised and closed;
 * on a phone it docks to the bottom of the screen.
 */
import { useEffect, useMemo, useRef, useState, type PointerEvent as RPointerEvent } from "react";
import { useCopilotShell } from "../../lib/shell-context";
import type { ChainState, FnoChain } from "../trading/fno";
import { BuilderView, closeOf, newLeg, type LegRow } from "./FnoBuilder";
import { ChainOiTable, type ChainTrades } from "./fno-parts";

type Pos = { x: number; y: number };

export function ChainWithAnalyse({ chain, state, symbol }: { chain: FnoChain; state: ChainState; symbol: string }) {
  const { mobile } = useCopilotShell();
  const [legs, setLegsState] = useState<LegRow[]>([]);
  const [open, setOpen] = useState(true);
  const [min, setMin] = useState(false);
  const [pos, setPos] = useState<Pos | null>(null);
  const drag = useRef<{ dx: number; dy: number } | null>(null);
  const key = `${symbol}|${chain.summary.expiry}|${chain.summary.as_of}`;

  // A different underlying or expiry starts a new analysis.
  useEffect(() => { setLegsState([]); setOpen(true); setMin(false); }, [key]);

  const trades = useMemo<ChainTrades>(() => ({
    has: (k, kind, side) => legs.some((l) => l.strike === k && l.kind === kind && l.side === side),
    toggle: (k, kind, side) => {
      setOpen(true); setMin(false);
      setLegsState((ls) => {
        const at = ls.findIndex((l) => l.strike === k && l.kind === kind && l.side === side);
        if (at >= 0) return ls.filter((_, i) => i !== at);
        const row = chain.strikes.find((r) => r.strike === k);
        return [...ls, newLeg(side, kind, k, closeOf(row, kind))];
      });
    },
  }), [legs, chain]);

  const shown = open && legs.length > 0;
  const onDown = (e: RPointerEvent<HTMLElement>) => {
    if (mobile) return;
    const box = (e.currentTarget.parentElement as HTMLElement).getBoundingClientRect();
    drag.current = { dx: e.clientX - box.left, dy: e.clientY - box.top };
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const onMove = (e: RPointerEvent<HTMLElement>) => {
    if (!drag.current) return;
    setPos({ x: Math.max(0, Math.min(window.innerWidth - 120, e.clientX - drag.current.dx)), y: Math.max(0, Math.min(window.innerHeight - 60, e.clientY - drag.current.dy)) });
  };
  const onUp = () => { drag.current = null; };

  return (
    <>
      <ChainOiTable chain={chain} trades={trades} />
      {shown && (
        <aside data-testid="desk-analyse" data-min={min ? "true" : undefined} aria-label="Analyse the selected trades" className="cp-card flex flex-col"
          style={{ position: "fixed", zIndex: 40, boxShadow: "0 12px 40px rgba(0,0,0,0.5)", background: "var(--bg-1)", overflow: "hidden",
            ...(mobile ? { left: 8, right: 8, bottom: 8, maxHeight: "78vh" } : { width: 560, maxWidth: "calc(100vw - 24px)", maxHeight: "86vh", ...(pos ? { left: pos.x, top: pos.y } : { right: 20, bottom: 20 }) }) }}>
          <header onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} data-testid="desk-analyse-head" className="flex items-center justify-between"
            style={{ padding: "10px 14px", background: "var(--indigo-soft)", borderBottom: "1px solid var(--line-2)", cursor: mobile ? "default" : "grab", touchAction: "none" }}>
            <span style={{ fontSize: 14, fontWeight: 600 }}>Analyse · {legs.length} {legs.length === 1 ? "trade" : "trades"} selected</span>
            <span className="flex items-center" style={{ gap: 6 }} onPointerDown={(e) => e.stopPropagation()}>
              <button type="button" aria-label={min ? "Expand the Analyse panel" : "Minimise the Analyse panel"} data-testid="desk-analyse-min" onClick={() => setMin((m) => !m)} style={btn}>{min ? "▢" : "–"}</button>
              <button type="button" aria-label="Clear the trades and close the Analyse panel" data-testid="desk-analyse-close" onClick={() => { setLegsState([]); setOpen(false); }} style={btn}>×</button>
            </span>
          </header>
          {!min && (
            <div className="cp-scroll" style={{ overflowY: "auto", padding: 12 }}>
              <BuilderView symbol={symbol} state={state} variant="panel" shared={{ legs, setLegs: setLegsState }} />
            </div>
          )}
        </aside>
      )}
    </>
  );
}

const btn = { width: 28, height: 28, borderRadius: 8, border: "1px solid var(--line-2)", background: "var(--bg-1)", color: "var(--cp-ink-2)", cursor: "pointer", fontSize: 14, lineHeight: 1 } as const;
