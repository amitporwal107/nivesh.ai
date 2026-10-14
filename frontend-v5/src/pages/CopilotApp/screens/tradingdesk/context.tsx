/**
 * Smart trading desk — state the tabs share.
 *
 *   const { tab, openTab, symbol, openChart, askDesk } = useDesk();
 *   openChart("RELIANCE");          // Chart tab with RELIANCE (also from Scanner, Intel, F&O)
 *   askDesk("Why does RELIANCE rank first?");
 *
 * The tab and the selected stock live in the URL (`?tab=chart&sym=RELIANCE`),
 * so a reload or a shared link opens the same view. `askDesk` sends the
 * question to the Copilot panel docked beside the desk when it is showing,
 * and to a normal thread otherwise.
 */
import { createContext, useContext } from "react";

export const DESK_TABS = ["overview", "scanner", "chart", "intel", "portfolio", "fno"] as const;
export type DeskTab = (typeof DESK_TABS)[number];

export const DESK_TAB_LABEL: Record<DeskTab, string> = {
  overview: "Overview",
  scanner: "AI scanner",
  chart: "Chart analysis",
  intel: "Market intelligence",
  portfolio: "Portfolio & risk",
  fno: "Options & futures lab",
};

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
}

const Ctx = createContext<DeskState | null>(null);

export const DeskProvider = Ctx.Provider;

export function useDesk(): DeskState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useDesk must be used inside the Smart trading desk");
  return v;
}
