/**
 * Smart trading desk — a Trader tool. Design: "Smart Trading Desk" (the
 * user's attached design, 2026-10-14): six modules on tabs, with the Copilot
 * docked at the right.
 *
 *   01 Overview               indices, breadth, regime, flows, sector strength    tradingdesk/OverviewTab
 *   02 AI scanner             setups ranked from the end-of-day scanner            tradingdesk/ScannerTab
 *   03 Chart analysis         candles, indicators, levels and the risk desk        tradingdesk/ChartTab
 *   04 Market intelligence    classified filings and institutional flows           tradingdesk/IntelTab
 *   05 Portfolio & risk       broker-read holdings, concentration, risk figures    tradingdesk/PortfolioTab
 *   06 Options & futures lab  index and stock F&O from the NSE bhavcopy            tradingdesk/FnoTab
 *
 * Every block reads an existing endpoint (named in each tab's header comment).
 * A block with no data source says so ("Not connected yet") instead of showing
 * the design's sample figures. Nivesh reads data; nothing here places an order.
 *
 * The tab and the selected stock live in the URL (?tab=&sym=). From 1400px
 * the Copilot is docked beside the desk and the shell's own ask box is hidden
 * (index.tsx); below that the shell's ask box is the way to ask.
 */
import { Suspense, lazy, useCallback, useMemo, useRef, type ComponentType, type LazyExoticComponent } from "react";
import { useSearchParams } from "react-router-dom";
import { SafeWidget } from "@/components/shared/SafeWidget";
import { LoadingBlock, Pill, fmtNum } from "../components/ui";
import { useCopilotShell } from "../lib/shell-context";
import { CopilotDock, type CopilotDockHandle } from "./tradingdesk/CopilotDock";
import { DESK_TABS, DESK_TAB_LABEL, DeskProvider, isDeskTab, type DeskState, type DeskTab } from "./tradingdesk/context";
import { useDeskScanner } from "./tradingdesk/desk-data";

const TAB_SCREENS: Record<DeskTab, LazyExoticComponent<ComponentType>> = {
  overview: lazy(() => import("./tradingdesk/OverviewTab")),
  scanner: lazy(() => import("./tradingdesk/ScannerTab")),
  chart: lazy(() => import("./tradingdesk/ChartTab")),
  intel: lazy(() => import("./tradingdesk/IntelTab")),
  portfolio: lazy(() => import("./tradingdesk/PortfolioTab")),
  fno: lazy(() => import("./tradingdesk/FnoTab")),
};

/** Symbols the URL may carry: the F&O routes' own rule (letters, digits, & and -). */
const SYM_RE = /^[A-Z0-9&-]{1,20}$/;

function Header() {
  const q = useDeskScanner();
  const setups = q.data?.setups ?? [];
  const confirmed = setups.filter((s) => s.status === "confirmed").length;
  const title = q.data && setups.length
    ? <><em>{fmtNum(confirmed)} of {fmtNum(setups.length)}</em> scanner setups have confirmed.</>
    : <>Your smart <em>trading desk</em>.</>;
  return (
    <header className="flex flex-col" style={{ gap: 10 }}>
      <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <span className="cp-eyebrow">Smart trading desk</span>
        <Pill tone="mint">Trader mode</Pill>
        <Pill tone="indigo">Broker data read-only</Pill>
        <Pill>No orders placed</Pill>
      </span>
      <h1 data-testid="desk-headline" className="cp-display m-0" style={{ fontSize: "clamp(30px, 4vw, 42px)", lineHeight: 1.08 }}>{title}</h1>
      <p className="m-0 cp-pretty" style={{ fontSize: 14.5, lineHeight: 1.6, color: "var(--cp-ink-2)", maxWidth: 760 }}>
        Index tape, end-of-day setups, charts, filings, your portfolio and F&amp;O in one place. Every figure names its source; a part with no data source yet says so.
      </p>
    </header>
  );
}

function TabStrip({ tab, onPick }: { tab: DeskTab; onPick: (t: DeskTab) => void }) {
  return (
    <div role="tablist" aria-label="Desk modules" className="cp-scroll flex overflow-x-auto" style={{ gap: 6, paddingBottom: 2 }}>
      {DESK_TABS.map((t, i) => {
        const on = t === tab;
        return (
          <button
            key={t}
            type="button"
            role="tab"
            aria-selected={on}
            data-testid={`desk-tab-${t}`}
            onClick={() => onPick(t)}
            className="flex items-center"
            style={{
              flex: "none", gap: 8, padding: "8px 14px", borderRadius: 999, fontSize: 13, fontWeight: 500, whiteSpace: "nowrap", cursor: "pointer",
              fontFamily: "var(--sans)", border: `1px solid ${on ? "var(--mint-line)" : "var(--line-2)"}`,
              background: on ? "var(--mint-soft)" : "transparent", color: on ? "var(--cp-ink)" : "var(--cp-ink-2)",
            }}
          >
            <span className="cp-num" style={{ fontSize: 9.5, color: on ? "var(--mint)" : "var(--cp-ink-4)" }}>{String(i + 1).padStart(2, "0")}</span>
            {DESK_TAB_LABEL[t]}
          </button>
        );
      })}
    </div>
  );
}

/** Questions for the docked Copilot about what the desk is showing. */
function useDockChips(tab: DeskTab, symbol: string | null): string[] {
  const q = useDeskScanner();
  const top = q.data?.setups[0]?.symbol;
  const sym = symbol ?? top ?? null;
  return useMemo(() => {
    const out: string[] = [];
    if (tab === "chart" && sym) {
      out.push(`Explain the ${sym} setup and what would invalidate it`);
      out.push(`Size a trade in ${sym} with 1% risk`);
    } else if (tab === "fno") {
      out.push("What does NIFTY option OI say about this expiry?");
      out.push("Which F&O stocks show long build-up today?");
    } else if (tab === "portfolio") {
      out.push("What are the key risks in my portfolio this week?");
    } else if (tab === "intel") {
      out.push("Summarise today’s most important filings");
    } else {
      if (top) out.push(`Why does ${top} rank first on the scanner?`);
      out.push("Which sectors are leading today and why?");
    }
    out.push("What are the key market risks this week?");
    return [...new Set(out)];
  }, [tab, sym, top]);
}

export default function TradingDeskScreen() {
  const { mobile, wide, ask } = useCopilotShell();
  const [params, setParams] = useSearchParams();
  const rawTab = params.get("tab");
  const tab: DeskTab = isDeskTab(rawTab) ? rawTab : "overview";
  const rawSym = (params.get("sym") || "").toUpperCase();
  const symbol = SYM_RE.test(rawSym) ? rawSym : null;
  const docked = wide;
  const dockRef = useRef<CopilotDockHandle>(null);

  const update = useCallback((next: { tab?: DeskTab; sym?: string }) => {
    setParams((prev) => {
      const p = new URLSearchParams(prev);
      if (next.tab) p.set("tab", next.tab);
      if (next.sym) p.set("sym", next.sym.toUpperCase());
      return p;
    }, { replace: true });
  }, [setParams]);

  const askDesk = useCallback((question: string) => {
    if (docked && dockRef.current) dockRef.current.ask(question);
    else ask(question);
  }, [docked, ask]);

  const desk = useMemo<DeskState>(() => ({
    tab,
    openTab: (t) => update({ tab: t }),
    symbol,
    openChart: (s) => update({ tab: "chart", sym: s }),
    setSymbol: (s) => update({ sym: s }),
    askDesk,
    docked,
  }), [tab, symbol, update, askDesk, docked]);

  const chips = useDockChips(tab, symbol);
  const TabScreen = TAB_SCREENS[tab];

  return (
    <DeskProvider value={desk}>
      <div
        data-testid="screen-trading-desk"
        data-tab={tab}
        data-symbol={symbol ?? ""}
        className="mx-auto grid"
        style={{
          maxWidth: docked ? 1480 : 1180,
          gridTemplateColumns: docked ? "minmax(0,1fr) 360px" : "minmax(0,1fr)",
          gap: 20,
          alignItems: "start",
          padding: `${mobile ? 20 : 28}px 0 40px`,
        }}
      >
        <div className="flex min-w-0 flex-col" style={{ gap: mobile ? 18 : 22 }}>
          <Header />
          <TabStrip tab={tab} onPick={(t) => update({ tab: t })} />
          <div data-testid={`desk-panel-${tab}`} role="tabpanel" aria-label={DESK_TAB_LABEL[tab]} className="flex min-w-0 flex-col" style={{ gap: 16 }}>
            <SafeWidget key={tab} name={`Trading desk · ${tab}`}>
              <Suspense fallback={<LoadingBlock label={`Loading ${DESK_TAB_LABEL[tab]}`} rows={4} />}>
                <TabScreen />
              </Suspense>
            </SafeWidget>
          </div>
          <p data-testid="desk-disclaimer" className="m-0" style={{ fontSize: 12, lineHeight: 1.55, color: "var(--cp-ink-3)", paddingTop: 12, borderTop: "1px solid var(--cp-line)" }}>
            For research and education. Scanner setups are end-of-day and rules-based; probabilities are model outputs for the next session, not buy or sell calls. Broker connections are read-only and Nivesh does not place orders. 9 out of 10 individual traders in equity F&amp;O incurred net losses (SEBI study).
          </p>
        </div>
        {docked && (
          <div style={{ position: "sticky", top: 16 }}>
            <CopilotDock ref={dockRef} chips={chips} height="calc(100dvh - 48px)" />
          </div>
        )}
      </div>
    </DeskProvider>
  );
}
