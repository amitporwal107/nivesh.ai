/**
 * Stocks Insight — company-research landing surface (Nivesh Copilot).
 * Revealed by the "Stocks Insight" launcher chip. Hero + a $ticker-aware input +
 * a curated welcome card of thematic starter queries (grouped by theme, revealed
 * 5 at a time — see data/thematicStarters). Every prompt/submit routes through the
 * chat's submitMessage: filings/thematic questions hit the stocks_insights node
 * (corporate disclosures, cited to the source filing); financials questions
 * (segment revenue, margins/OPM) route to the stock analyst.
 */
import { useState } from "react";
import { ArrowUp, Building2, Star } from "lucide-react";
import { THEMATIC_STARTERS as ALL_STARTERS, STARTERS_PAGE as PAGE } from "../../data/thematicStarters";

export default function StockInsightsLanding({ onLaunch }: { onLaunch: (q: string) => void }) {
  const [q, setQ] = useState("");
  const [visible, setVisible] = useState(PAGE);
  const send = () => {
    const t = q.trim();
    if (!t) return;
    setQ("");
    onLaunch(t);
  };
  const remaining = ALL_STARTERS.length - visible;

  return (
    <div className="mt-4 rounded-2xl border border-hairline bg-surface-1 shadow-card p-6 md:p-8">
      <div className="max-w-2xl mx-auto text-center">
        <span className="inline-grid place-items-center h-9 w-9 rounded-full bg-[rgb(var(--accent)/0.10)] text-accent">
          <Building2 className="h-5 w-5" />
        </span>
        <h2 className="font-display text-[22px] md:text-[26px] text-ink tracking-tightish mt-3 leading-snug">
          Got company-related questions? I'm here to assist!
        </h2>
        <p className="text-[14px] text-ink-3 mt-1.5">
          Run a market-wide theme below, or ask about a specific company (type $ for tickers).
        </p>
      </div>

      <div className="mt-5 rounded-xl border border-hairline bg-surface-1 focus-within:border-accent transition-colors px-4 py-3 flex items-center gap-3">
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

      <div className="mt-5 flex items-center justify-between">
        <p className="text-[12px] font-medium text-ink-3">Curated themes — tap to run</p>
        <span className="inline-flex items-center gap-1 text-[11px] text-ink-4">
          <Star className="h-3 w-3 fill-accent text-accent" /> featured
        </span>
      </div>

      <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-2">
        {ALL_STARTERS.slice(0, visible).map((item) => (
          <button
            key={item.q}
            onClick={() => onLaunch(item.q)}
            className="text-left rounded-xl border border-hairline bg-surface-1 hover:bg-surface-2 hover:border-accent/40 px-3.5 py-2.5 transition-colors flex items-start gap-2"
          >
            {item.featured && (
              <Star className="h-3.5 w-3.5 mt-0.5 shrink-0 fill-accent text-accent" aria-hidden />
            )}
            <span className="min-w-0">
              <span className="block text-[10px] font-semibold uppercase tracking-wide text-ink-4 mb-0.5">
                {item.category}
              </span>
              <span className="block text-[13px] text-ink-2 leading-snug">{item.q}</span>
            </span>
          </button>
        ))}
      </div>

      {(remaining > 0 || visible > PAGE) && (
        <div className="mt-4 flex justify-center">
          {remaining > 0 ? (
            <button
              onClick={() => setVisible((v) => Math.min(v + PAGE, ALL_STARTERS.length))}
              className="rounded-full border border-hairline hover:border-accent/50 hover:bg-surface-2 px-4 py-1.5 text-[12.5px] font-medium text-ink-2 transition-colors"
            >
              Show {Math.min(PAGE, remaining)} more · {remaining} left
            </button>
          ) : (
            <button
              onClick={() => setVisible(PAGE)}
              className="rounded-full border border-hairline hover:border-accent/50 hover:bg-surface-2 px-4 py-1.5 text-[12.5px] font-medium text-ink-3 transition-colors"
            >
              Show less
            </button>
          )}
        </div>
      )}
    </div>
  );
}
