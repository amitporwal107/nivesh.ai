/**
 * Smart trading desk — state the tabs share.
 *
 *   const { tab, openTab, symbol, openChart, askDesk } = useDesk();
 *   openChart("RELIANCE");          // Chart tab with RELIANCE (also from Scanner, Intel, F&O)
 *   askDesk("Why does RELIANCE rank first?");
 *
 * The tab and the selected stock live in the URL (`?tab=chart&sym=RELIANCE`),
 * so a reload or a shared link opens the same view. `askDesk` sends the
 * question to the desk's own Copilot — docked beside the desk from 1400px,
 * otherwise More · AI Copilot (`?tab=more`).
 */
import { createContext, useContext } from "react";

/** Every `?tab=` id of a module. The tab row (TradingDesk.tsx, in the PRD's order) shows all but the lab ("fno"), which sits under More. */
export const DESK_TABS = ["overview", "scanner", "chart", "intel", "portfolio", "fno", "events"] as const;
export type DeskTab = (typeof DESK_TABS)[number];

/** The module tab names, word for word from the design's tab row. */
export const DESK_TAB_LABEL: Record<DeskTab, string> = {
  overview: "Overview",
  scanner: "AI Scanner",
  chart: "Chart Analysis",
  intel: "Market Intelligence",
  portfolio: "Portfolio & Risk",
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

export interface DeskState {
  tab: DeskTab;
  openTab: (tab: DeskTab) => void;
  /** The stock the Chart tab shows; null until one is picked (the Chart tab then uses the scanner's first). */
  symbol: string | null;
  /** Select a stock and open the Chart tab. */
  openChart: (symbol: string) => void;
  /** Select a stock without changing tab. */
  setSymbol: (symbol: string) => void;
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
