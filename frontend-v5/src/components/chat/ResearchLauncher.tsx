/**
 * Two-step research launcher for the Copilot chat.
 *
 *   Step 1 — pick an instrument (typeahead over stocks + mutual funds).
 *   Step 2 — pick a question tile; we send a routing-safe research prompt.
 *
 * Self-contained: the host passes `onAsk(prompt)` (which submits a chat message).
 * Kept in its own file so it composes the shared hooks without touching the
 * heavily-edited Chat page internals.
 */
import { useMemo, useState } from "react";
import { LineChart, PieChart } from "lucide-react";
import { cn } from "@/lib/utils";
import { useDebounce } from "@/hooks/use-debounce";
import { useInstrumentSearch, type StockHit, type FundHit } from "@/hooks/use-instrument-search";

type Picked = { kind: "stock" | "fund"; name: string };
type Suggestion =
  | { kind: "stock"; symbol: string; name: string; sub?: string }
  | { kind: "fund"; name: string; sub?: string };

// Step-2 question tiles. Each sends "Tell me about <name> — <aspect>": the lead
// guarantees the stock/MF route, the aspect steers the answer. Mirrors the card lenses.
const TILES: Record<"stock" | "fund", { id: string; label: string; icon: string }[]> = {
  stock: [
    { id: "overview", label: "Full overview", icon: "🔎" },
    { id: "buy_verdict", label: "Worth buying now?", icon: "📈" },
    { id: "performance", label: "Track record", icon: "📊" },
    { id: "valuation", label: "Cheap or pricey?", icon: "⚖️" },
    { id: "risk", label: "How risky?", icon: "🎯" },
    { id: "peers", label: "Vs peers", icon: "👥" },
    { id: "red_flags", label: "Any red flags?", icon: "🚩" },
    { id: "people", label: "Who runs it?", icon: "🧑‍💼" },
    { id: "whats_new", label: "Latest news", icon: "📰" },
  ],
  fund: [
    { id: "overview", label: "Full overview", icon: "🔎" },
    { id: "buy_verdict", label: "Worth buying now?", icon: "📈" },
    { id: "performance", label: "Track record", icon: "📊" },
    { id: "valuation", label: "Cheap or pricey?", icon: "⚖️" },
    { id: "risk", label: "How risky?", icon: "🎯" },
    { id: "peers", label: "Beats its peers?", icon: "👥" },
    { id: "drivers", label: "Holdings", icon: "🧩" },
    { id: "costs", label: "Fees & loads", icon: "🏷️" },
    { id: "people", label: "Fund manager", icon: "🧑‍💼" },
  ],
};

function tilePrompt(kind: "stock" | "fund", name: string, lensId: string): string {
  const lead = kind === "fund" ? `Tell me about the mutual fund ${name}` : `Tell me about ${name}`;
  const aspect: Record<string, string> = {
    buy_verdict: "is it worth buying now?",
    performance: "how has it performed versus its benchmark?",
    valuation: "is it cheap or pricey right now?",
    risk: "how risky is it?",
    peers: "how does it compare to its peers?",
    drivers: kind === "fund" ? "what does it hold?" : "what drives the business?",
    red_flags: "are there any red flags?",
    costs: "what does it cost — expense ratio and exit load?",
    people: kind === "fund" ? "who manages it?" : "who runs it?",
    whats_new: "what's the latest news?",
  };
  const a = aspect[lensId];
  return a ? `${lead} — ${a}` : lead;
}

export function ResearchLauncher({
  kind = "all",
  onAsk,
}: {
  /** Restrict step-1 results: "stock" | "fund" | "all". */
  kind?: "stock" | "fund" | "all";
  /** Submit the chosen research prompt as a chat message. */
  onAsk: (prompt: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState<Picked | null>(null);
  const debounced = useDebounce(query, 220);
  const search = useInstrumentSearch(picked ? "" : debounced);

  const suggestions = useMemo<Suggestion[]>(() => {
    const data = search.data;
    if (!data) return [];
    const out: Suggestion[] = [];
    if (kind !== "fund") {
      for (const s of data.stocks as StockHit[]) out.push({ kind: "stock", symbol: s.symbol, name: s.name, sub: s.sector ?? undefined });
    }
    if (kind !== "stock") {
      for (const f of data.funds as FundHit[]) out.push({ kind: "fund", name: f.name, sub: [f.amc, f.category].filter(Boolean).join(" · ") || undefined });
    }
    return out.slice(0, 8);
  }, [search.data, kind]);

  const ask = (lensId: string) => {
    if (!picked) return;
    onAsk(tilePrompt(picked.kind, picked.name, lensId));
    setPicked(null);
    setQuery("");
  };

  // ── Step 2: question tiles for the picked instrument ──
  if (picked) {
    return (
      <div className="rounded-xl bg-surface-1 border border-hairline-2 p-4">
        <div className="flex items-center justify-between gap-2 mb-3">
          <div className="flex items-center gap-2 min-w-0">
            {picked.kind === "stock"
              ? <LineChart className="h-4 w-4 text-accent shrink-0" />
              : <PieChart className="h-4 w-4 text-accent shrink-0" />}
            <span className="text-[12.5px] text-ink-3">Research</span>
            <span className="font-display text-[15px] text-ink truncate">{picked.name}</span>
          </div>
          <button onClick={() => setPicked(null)} className="text-[12px] text-ink-3 hover:text-ink shrink-0">Change</button>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
          {TILES[picked.kind].map((t) => (
            <button
              key={t.id}
              onClick={() => ask(t.id)}
              className="flex items-center gap-2 px-3 py-2.5 rounded-lg bg-surface-2/60 border border-hairline text-left text-[12.5px] text-ink hover:bg-surface-2 transition-colors"
            >
              <span aria-hidden>{t.icon}</span>
              <span className="truncate">{t.label}</span>
            </button>
          ))}
        </div>
      </div>
    );
  }

  // ── Step 1: pick an instrument ──
  const label = kind === "fund" ? "Find a mutual fund" : kind === "stock" ? "Find a stock" : "Find a stock or fund";
  return (
    <div className="rounded-xl bg-surface-1 border border-hairline-2 p-4">
      <div className="flex items-center gap-2 mb-2.5">
        {kind === "fund"
          ? <PieChart className="h-4 w-4 text-accent shrink-0" />
          : <LineChart className="h-4 w-4 text-accent shrink-0" />}
        <span className="text-[13px] font-medium text-ink">{label}</span>
      </div>
      <input
        type="text"
        autoComplete="off"
        placeholder={kind === "fund" ? "e.g. Parag Parikh Flexi Cap" : "e.g. Reliance, TCS, HDFC…"}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        className="w-full bg-surface-2/60 border border-hairline rounded-md px-3 py-2 text-[14px] text-ink outline-none focus:border-accent"
      />
      {query.trim().length >= 2 && (
        <div className="mt-2 rounded-md border border-hairline overflow-hidden">
          {search.isFetching && suggestions.length === 0 ? (
            <div className="px-3.5 py-2.5 text-[13px] text-ink-3">Searching…</div>
          ) : suggestions.length === 0 ? (
            <div className="px-3.5 py-2.5 text-[13px] text-ink-3">No matches — try a different name.</div>
          ) : (
            <ul className="max-h-64 overflow-y-auto">
              {suggestions.map((s, i) => (
                <li key={(s.kind === "stock" ? s.symbol : s.name) + i}>
                  <button
                    type="button"
                    onClick={() => setPicked({ kind: s.kind, name: s.name })}
                    className={cn("w-full flex items-center gap-2.5 px-3.5 py-2 text-left hover:bg-surface-2/60 transition-colors")}
                  >
                    {s.kind === "stock"
                      ? <LineChart className="h-3.5 w-3.5 text-accent shrink-0" />
                      : <PieChart className="h-3.5 w-3.5 text-accent shrink-0" />}
                    <span className="min-w-0 flex-1">
                      <span className="block text-[13.5px] text-ink truncate">{s.name}</span>
                      {s.sub && <span className="block text-[11.5px] text-ink-3 truncate">{s.sub}</span>}
                    </span>
                    <span className="shrink-0 rounded-full px-2 py-0.5 text-[9.5px] font-semibold tracking-wide" style={{ background: "#E7EEF9", color: "#3E6CA8" }}>
                      {s.kind === "stock" ? "STOCK" : "FUND"}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
