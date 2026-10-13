import { useState } from "react";
import type { FundHit, StockHit } from "@/hooks/use-instrument-search";
import { EmptyBlock, Footnote, Screen, ScreenHeader } from "../components/ui";
import { AskPill, FilterChips, type ChipItem } from "./markets/parts";
import { ResearchFilings } from "./markets/ResearchFilings";
import { FundResearch, InstrumentSearch, StockResearch, type PickedInstrument } from "./markets/ResearchInstrument";

type ResearchKind = "filings" | "stock" | "fund";

const KINDS: ChipItem<ResearchKind>[] = [
  { key: "filings", label: "Filings" },
  { key: "stock", label: "Stock" },
  { key: "fund", label: "Mutual fund" },
];

const TITLE: Record<ResearchKind, string> = {
  filings: "Research across filings",
  stock: "Stock research",
  fund: "Fund research",
};

/**
 * Stock & fund research — filings intelligence, plus a search that opens a
 * stock or a mutual fund. Design: design/nivesh-copilot/NVTools.dc.html
 * (tool === "research").
 */
export default function ResearchScreen() {
  const [kind, setKind] = useState<ResearchKind>("filings");
  const [stock, setStock] = useState<StockHit | null>(null);
  const [fund, setFund] = useState<FundHit | null>(null);

  const onPick = (p: PickedInstrument) => {
    if (p.kind === "stock") setStock(p.hit);
    else setFund(p.hit);
    setKind(p.kind);
  };

  // The header question is always about something real: the picked instrument,
  // the user's own funds, or the filings feed.
  const headerAsk =
    kind === "stock"
      ? (stock ? `Tell me about ${stock.name}` : null)
      : kind === "fund"
        ? (fund
          ? `Show the overview of ${fund.name}${fund.scheme_code ? ` (${fund.scheme_code})` : ""}`
          : "How much overlap do my mutual funds have, and how do I rebalance tax-efficiently?")
        : "Which company filings from the last few days are the most material, and why?";

  return (
    <Screen testId="screen-tool-research">
      <ScreenHeader
        eyebrow="Stock and fund research"
        pills={headerAsk ? <AskPill query={headerAsk} testId="research-header-ask" /> : undefined}
        title={<span data-testid="research-title">{TITLE[kind]}</span>}
      />

      <div className="flex flex-wrap items-start" style={{ gap: 8 }}>
        <InstrumentSearch only={kind === "filings" ? undefined : kind} onPick={onPick} />
        <div style={{ paddingTop: 5 }}>
          <FilterChips items={KINDS} value={kind} onChange={setKind} label="What to research" idPrefix="research-kind" />
        </div>
      </div>

      {kind === "filings" && <ResearchFilings />}

      {kind === "stock" && (
        stock
          ? <StockResearch key={stock.symbol} stock={stock} onClear={() => setStock(null)} />
          : (
            <EmptyBlock
              title="Pick a stock to research"
              body="Search by company name or symbol above. You get its reported quarterly numbers, shareholding, corporate actions and filings here, and the Copilot’s full research card in the thread."
            />
          )
      )}

      {kind === "fund" && (
        fund
          ? <FundResearch key={fund.scheme_code ?? fund.name} fund={fund} onClear={() => setFund(null)} />
          : (
            <EmptyBlock
              title="Pick a mutual fund to research"
              body="Search by scheme or fund-house name above, then ask the Copilot for its overview, returns, holdings or peer comparison."
            />
          )
      )}

      <Footnote>
        Sources: NSE and BSE filings and corporate actions through the Nivesh data platform · AI reads are summaries, refer to the source filing · educational, not investment advice
      </Footnote>
    </Screen>
  );
}
