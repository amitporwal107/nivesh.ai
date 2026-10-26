/**
 * Smart trading desk — state the tabs share.
 *
 *   const { tab, openTab, symbol, openChart, askDesk } = useDesk();
 *   openChart("RELIANCE");          // Chart tab with RELIANCE (also from Scanner, Intel, F&O)
 *   openLab("candidates", { focus: "ICICIBANK" });   // the lab's Candidates with a Top 10 idea in focus
 *   askDesk("Why does RELIANCE rank first?");
 *
 * The tab and the selected stock live in the URL (`?tab=chart&sym=RELIANCE`),
 * so a reload or a shared link opens the same view. `askDesk` sends the
 * question to the desk's own Copilot — docked beside the desk from 1400px,
 * otherwise More · AI Copilot (`?tab=more`).
 */
import { createContext, useContext } from "react";

/** Every `?tab=` id of a module. The tab row (TradingDesk.tsx, in the PRD's order) shows all but the lab ("fno"), which sits under More. */
export const DESK_TABS = ["overview", "scanner", "chart", "intel", "portfolio", "smartmoney", "fno", "events"] as const;
export type DeskTab = (typeof DESK_TABS)[number];

/** The module tab names, word for word from the design's tab row. */
export const DESK_TAB_LABEL: Record<DeskTab, string> = {
  overview: "Overview",
  scanner: "AI Scanner",
  chart: "Chart Analysis",
  intel: "Market Intelligence",
  portfolio: "Portfolio & Risk",
  smartmoney: "Smart Money",
  fno: "Options & Futures Lab",
  events: "Events Calendar",
};

/**
 * How the desk words things (design: the TRADER / INVESTOR switch in the top bar).
 * "investor" swaps technical labels for plain language; the data is the same.
 * It is the desk's own reading setting and does not change the app's mode.
 */
export type DeskPersona = "trader" | "investor";

export function isDeskTab(v: string | null | undefined): v is DeskTab {
  return !!v && (DESK_TABS as readonly string[]).includes(v);
}

/** The Options & futures lab's views, kept in the URL as `?lab=` (the first is the default and is left out). */
export const LAB_VIEWS = ["buildup", "candidates", "indices", "chain", "strategies"] as const;
export type LabView = (typeof LAB_VIEWS)[number];
/** Short names for the breadcrumb; the lab's own tab row carries the long ones (FnoTab.tsx). */
export const LAB_VIEW_LABEL: Record<LabView, string> = {
  buildup: "OI build-up",
  candidates: "Candidates",
  indices: "NIFTY & BANKNIFTY",
  chain: "Option chain",
  strategies: "Paper strategies",
};

export function isLabView(v: string | null | undefined): v is LabView {
  return !!v && (LAB_VIEWS as readonly string[]).includes(v);
}

/** The part of a view a link leaves from ("Top 10 F&O ideas"), and the element to scroll back to (a data-testid). */
export interface TrailFrom { label: string; anchor?: string }

export interface DeskState {
  tab: DeskTab;
  openTab: (tab: DeskTab) => void;
  /** The stock the Chart tab shows; null until one is picked (the Chart tab then uses the scanner's first). */
  symbol: string | null;
  /** Select a stock and open the Chart tab. */
  openChart: (symbol: string) => void;
  /** Select a stock without changing tab. */
  setSymbol: (symbol: string) => void;
  /** Open the Strategy Builder (More) on a stock, carrying the signal it started from (shown as "Started from ..."). */
  openStrategy: (symbol: string, src?: { kind: "scanner" | "chart" | "lab"; bucket?: string | null; date?: string | null }) => void;
  /** Open the Strategy Builder on the AI opportunities board, optionally scrolled to one stock's idea. */
  openStrategyIdeas: (focus?: string) => void;
  /** Open the Strategy Builder in One stock mode with a pick's plan inputs (URL params as the ideas board writes them) and build it. */
  openStrategyPlan: (params: Record<string, string>) => void;
  /** Open More · Chartink scans (the settings for using the user's Chartink scans as opportunity sources). */
  openChartink: () => void;
  /**
   * Open the Options & futures lab on a view (`?lab=`), optionally with an underlying loaded (`?lab_sym=`) and a Top 10 F&O
   * idea in focus (`?lab_focus=`, the panel above the lab's views).
   */
  openLab: (view?: LabView, opts?: { symbol?: string; focus?: string }) => void;
  /** Open Market Intelligence on a chip (`?in_chip=`), optionally with one event selected (`?in_ev=`). */
  openIntel: (opts?: { chip?: string; event?: string }) => void;
  /** Open Portfolio & Risk scrolled to the paper trades. */
  openPaperTrades: () => void;
  /** Name the part of this view the next link leaves from, so its breadcrumb reads, and scrolls back to, that part. */
  noteFrom: (from: TrailFrom) => void;
  /** Ask the Copilot about something on the desk. */
  askDesk: (question: string) => void;
  /** True when the Copilot panel is docked beside the desk (wide screens). */
  docked: boolean;
  /** Trader (technical wording, default) or investor (plain wording); kept in the URL as ?persona=. */
  persona: DeskPersona;
  setPersona: (persona: DeskPersona) => void;
}

const Ctx = createContext<DeskState | null>(null);

export const DeskProvider = Ctx.Provider;

export function useDesk(): DeskState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useDesk must be used inside the Smart trading desk");
  return v;
}
