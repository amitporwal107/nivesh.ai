import { useState } from "react";
import { Footnote, Screen, ScreenHeader } from "../components/ui";
import { ActionsTab } from "./markets/ActionsTab";
import { ArticlesTab } from "./markets/ArticlesTab";
import { BriefTab } from "./markets/BriefTab";
import { EarningsTab } from "./markets/EarningsTab";
import { FlowsTab } from "./markets/FlowsTab";
import { stampLabel } from "./markets/format";
import { useMarketOverview } from "./markets/hooks";
import { MarketTab } from "./markets/MarketTab";
import { AskPill, TabBar, type TabItem } from "./markets/parts";
import { SectorsTab } from "./markets/SectorsTab";

type MarketsTabKey = "market" | "sectors" | "earnings" | "flows" | "actions" | "articles" | "brief";

const TABS: TabItem<MarketsTabKey>[] = [
  { key: "market", label: "Market" },
  { key: "sectors", label: "Sector Analysis" },
  { key: "earnings", label: "Earnings Tracker" },
  { key: "flows", label: "FII / DII" },
  { key: "actions", label: "Corporate Actions" },
  { key: "articles", label: "Articles" },
  { key: "brief", label: "Daily Iris Update" },
];

/**
 * Markets — the market pulse: index tape, sectors, earnings season, FII / DII
 * flows, corporate actions, classified announcements and the daily brief.
 * Design: design/nivesh-copilot/NVTools.dc.html (tool === "markets").
 *
 * Every tab reads through the named hooks in markets/hooks.ts and prints, per
 * block, the source and time its response carried — nothing more.
 */
export default function MarketsScreen() {
  const [tab, setTab] = useState<MarketsTabKey>("market");
  // The same query the Market tab reads; here it only dates the eyebrow.
  const home = useMarketOverview();
  const stamp = stampLabel(home.data?.fetched_at ?? home.data?.as_of);

  return (
    <Screen testId="screen-tool-markets">
      <ScreenHeader
        eyebrow={
          <span data-testid="markets-eyebrow">
            Markets{stamp ? ` · updated ${stamp}` : ""}
            {home.data ? ` · market ${home.data.market_state}` : ""}
          </span>
        }
        pills={<AskPill query="Show important announcements affecting my holdings today" testId="markets-ask" />}
        title="Market pulse"
      />

      <TabBar tabs={TABS} value={tab} onChange={setTab} label="Market sections" idPrefix="markets-tab" />

      {tab === "market" && <MarketTab onOpenFlows={() => setTab("flows")} />}
      {tab === "sectors" && <SectorsTab />}
      {tab === "earnings" && <EarningsTab />}
      {tab === "flows" && <FlowsTab />}
      {tab === "actions" && <ActionsTab />}
      {tab === "articles" && <ArticlesTab />}
      {tab === "brief" && <BriefTab />}

      <Footnote>
        Each block shows the source and the time its figures came with · educational, not investment advice
      </Footnote>
    </Screen>
  );
}
