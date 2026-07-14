/**
 * Stocks Insight — company-research landing surface (Nivesh Copilot).
 * Revealed by the "Stocks Insight" launcher chip. Hero + example-prompt cards +
 * a $ticker-aware input. Every prompt/submit routes through the chat's
 * submitMessage: filings/thematic questions hit the stocks_insights node
 * (corporate disclosures, cited to the source filing); financials questions
 * (segment revenue, margins/OPM) route to the stock analyst.
 */
import { useState } from "react";
import { ArrowUp, Building2 } from "lucide-react";

// Illustrative starters (thematic + $ticker-scoped). Users can ask anything.
const STARTERS = [
  "Which companies are investing in the data center business?",
  "Give me the revenue breakdown by segment for $PVRINOX.",
  "What did $INFY say about demand in its last earnings call?",
  "What is the quarterly OPM trend for $TCS?",
];

export default function StockInsightsLanding({ onLaunch }: { onLaunch: (q: string) => void }) {
  const [q, setQ] = useState("");
  const send = () => {
    const t = q.trim();
    if (!t) return;
    setQ("");
    onLaunch(t);
  };

  return (
    <div className="mt-4 rounded-2xl border border-hairline bg-surface-1 shadow-card p-6 md:p-8">
      <div className="max-w-2xl mx-auto text-center">
        <span className="inline-grid place-items-center h-9 w-9 rounded-full bg-[rgb(var(--accent)/0.10)] text-accent">
          <Building2 className="h-5 w-5" />
        </span>
        <h2 className="font-display text-[22px] md:text-[26px] text-ink tracking-tightish mt-3 leading-snug">
          Got company-related questions? I'm here to assist!
        </h2>
        <p className="text-[14px] text-ink-3 mt-1.5">Use AI-Assist to explore company filings, financials and disclosures.</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5 mt-6">
        {STARTERS.map((s) => (
          <button
            key={s}
            onClick={() => onLaunch(s)}
            className="text-left rounded-xl border border-hairline bg-surface-1 hover:bg-surface-2 px-4 py-3.5 text-[13.5px] text-ink-2 leading-snug transition-colors"
          >
            {s}
          </button>
        ))}
      </div>

      <div className="mt-4 rounded-xl border border-hairline bg-surface-1 focus-within:border-accent transition-colors px-4 py-3 flex items-center gap-3">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
          placeholder="Ask or search anything (Type $ for tickers)"
          aria-label="Ask a company-research question"
          className="flex-1 bg-transparent outline-none text-[14px] text-ink placeholder:text-ink-4"
        />
        <button
          onClick={send}
          disabled={!q.trim()}
          aria-label="Send"
          className="shrink-0 h-8 w-8 rounded-full bg-accent/90 hover:bg-accent disabled:opacity-40 grid place-items-center text-white transition-colors"
        >
          <ArrowUp className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
