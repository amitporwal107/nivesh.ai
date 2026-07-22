import { useState, useEffect, useRef, useMemo, Fragment } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Plus, Send, History as HistoryIcon, Trash2, X, PanelLeftClose, PanelLeftOpen, LineChart, PieChart, SlidersHorizontal, ListFilter, Sparkles, Wand2, Building2 } from "lucide-react";
import { cn } from "@/lib/utils";
import CopilotWorkflows from "./CopilotWorkflows";
import CopilotReview from "./CopilotReview";
import StockInsightsLanding from "./StockInsightsLanding";
import { useMe } from "@/hooks/use-auth";
import { useImpersonationStore } from "@/stores/impersonation.store";
import { useQueryClient } from "@tanstack/react-query";
import {
  useSuggestedPrompts,
  useChatSession,
  useChatSessions,
  useCreateChatSession,
  useDeleteChatSession,
} from "@/hooks/use-chat";
import { chatService } from "@/services";
import { Skeleton } from "@/components/ui/skeleton";
import { ChatWidget } from "@/components/chat/ChatWidget";
import { ScreenerQueryBuilder } from "@/components/chat/ScreenerQueryBuilder";
import { SCREEN_PRIMITIVES, screenInsert, type ScreenPrimitive } from "@/components/chat/screenerPrimitives";
import { Markdown, prefetchStreamdown } from "@/components/chat/Markdown";
import { useTypewriterReveal, remainingRevealMs } from "@/components/chat/useTypewriter";
import { useDebounce } from "@/hooks/use-debounce";
import { useInstrumentSearch, type StockHit, type FundHit } from "@/hooks/use-instrument-search";
import { useQuerySuggestions, type QuerySuggestion } from "@/hooks/use-query-suggestions";

// `buffer` is everything received from the stream; `content` is the paced,
// typed-out slice the user sees (see useTypewriterReveal).
type StreamState = { buffer: string; content: string; thinking?: string; widget?: { widget_type: string; data: unknown }; error?: string };

const WIDGET_TYPES = new Set(["fund_consolidation", "fund_overlap", "overlap_severity", "risk_overview", "cap_education", "concentration", "allocation_review", "instrument_detail", "mf_detail", "market_detail", "risk_assessment", "goal_simulation", "stock_screener", "portfolio_builder", "strategy_lab", "capital_gains", "goal_basket", "backtest_comparison", "stock_insights"]);

const FALLBACK_PROMPTS = [
  "Why is my score 74?",
  "Which funds overlap most?",
  "How risky is my portfolio?",
  "What should I reduce first?",
];

// Research starters that turn on instrument autocomplete. When the composer begins
// with one of these, the trailing text is treated as a stock/fund name query. The
// list includes the two research-chip prefills plus common manual phrasings.
const RESEARCH_STARTERS = [
  "tell me about the mutual fund ",
  "tell me about ",
  "should i invest in the mutual fund ",
  "should i invest in ",
  "should i buy ",
  "how is ",
  "research ",
];

type Suggestion =
  | { kind: "stock"; symbol: string; name: string; sub?: string }
  | { kind: "fund"; name: string; sub?: string };

// Question-bank placeholders that name an instrument — filling one switches the
// composer to canonical stock/fund-name autocomplete.
const _ENTITY_PH = /\{(stocks?|peer|funds?2?|etf)\}/i;
const _entityKind = (inner: string): "stock" | "fund" =>
  /stock|peer/i.test(inner) ? "stock" : "fund";

/** Extract the entity-name query from the composer, or inactive if no starter matched.
 *  `mode: "funds"` when the user explicitly said "mutual fund" (else both kinds shown). */
function entityQuery(text: string): { term: string; mode: "funds" | "all"; active: boolean } {
  const lower = text.toLowerCase();
  for (const s of RESEARCH_STARTERS) {
    if (lower.startsWith(s)) {
      const term = text.slice(s.length).trim();
      return { term, mode: lower.includes("mutual fund") ? "funds" : "all", active: term.length >= 2 };
    }
  }
  return { term: "", mode: "all", active: false };
}

// Screener-primitive autocomplete. When the composer is in "screen stocks
// where …" mode, picking a primitive INSERTS its clause (e.g. "ROE over ") so
// the user only types the threshold — building the query metric by metric.
// The primitive catalog is shared with the visual Query Builder (and matches
// the backend NL parser) — see components/chat/screenerPrimitives.ts.
const SCREEN_STARTERS = ["screen stocks where ", "screen stocks ", "screen for ", "screen "];

// Predefined backtest baskets shown when "Backtest a basket" is clicked. Each
// `query` is a ready-to-send backtest prompt (routes to the backtest analyst via
// "if I had invested …"); instrument names are chosen to resolve cleanly via the
// stock symbol / MF scheme resolvers. Users can also free-type their own basket.
const BACKTEST_BASKETS: { label: string; sub: string; query: string }[] = [
  { label: "Large-cap leaders", sub: "5 index heavyweights",
    query: "If I had invested 10L equally in HDFC Bank, Reliance, ICICI Bank, Infosys and TCS 1 year and 3 years ago, what's it worth today?" },
  { label: "Top IT", sub: "5 IT majors",
    query: "If I had invested 10L equally in TCS, Infosys, Wipro, HCL Technologies and Tech Mahindra 1 year and 3 years ago, what's it worth today?" },
  { label: "Banking & financials", sub: "5 private + PSU banks",
    query: "If I had invested 10L equally in HDFC Bank, ICICI Bank, SBI, Kotak Mahindra Bank and Axis Bank 1 year and 3 years ago, what's it worth today?" },
  { label: "Popular flexi-cap funds", sub: "3 flexi-cap MFs",
    query: "If I had invested 10L equally in Parag Parikh Flexi Cap, HDFC Flexi Cap and Quant Flexi Cap 1 year and 3 years ago, what's it worth today?" },
];

/** Screener mode + the clause currently being typed (text after the last comma).
 *  `base` is everything to keep when a primitive is inserted in place of `fragment`. */
function screenQuery(text: string): { active: boolean; fragment: string; base: string } {
  const lower = text.toLowerCase();
  const starter = SCREEN_STARTERS.find((s) => lower.startsWith(s));
  if (!starter) return { active: false, fragment: "", base: "" };
  const lastComma = text.lastIndexOf(",");
  if (lastComma >= starter.length - 1) {
    return { active: true, base: text.slice(0, lastComma + 1) + " ", fragment: text.slice(lastComma + 1).trim() };
  }
  return { active: true, base: text.slice(0, starter.length), fragment: text.slice(starter.length).trim() };
}

/** Compact relative time for the history list ("2m ago", "3d ago"). */
function relTime(iso?: string): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const s = Math.floor((Date.now() - t) / 1000);
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 7) return `${d}d ago`;
  return new Date(iso).toLocaleDateString();
}

export default function ChatPage() {
  const [composer, setComposer] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  // Instrument-autocomplete dropdown state.
  const [suggestOpen, setSuggestOpen] = useState(false);
  // Visual screener query-builder panel.
  const [builderOpen, setBuilderOpen] = useState(false);
  const [stockInsightsOpen, setStockInsightsOpen] = useState(false);
  const [analyseOpen, setAnalyseOpen] = useState(false);
  const [backtestOpen, setBacktestOpen] = useState(false);
  // Persona for the workflow landing (investor portfolio vs advisor book).
  // The advisor book shows ONLY at the advisor root. While viewing a client
  // (impersonating), the copilot answers in investor mode for that client's
  // portfolio, so show the investor workflows to match. Prefer the store over
  // me.activeProfileId — the backend field races the persisted store (see use-chat.ts).
  const me = useMe();
  const impersonatingProfileId = useImpersonationStore((s) => s.profileId);
  const isAdvisor =
    (me.data?.workspaceType || "").toUpperCase() === "ADVISORY" && !impersonatingProfileId;
  const [activeIdx, setActiveIdx] = useState(-1);
  // When a picked question template has a {stock}/{fund} placeholder, we enter
  // "entity fill" mode: instrument autocomplete suggests canonical names and a
  // pick substitutes into the template. before/after bracket the placeholder.
  const [entityFill, setEntityFill] = useState<{ before: string; after: string; kind: "stock" | "fund" } | null>(null);
  // `?q=` deep-link (e.g. Markets "Explore" chips) → auto-send once on mount.
  const [searchParams, setSearchParams] = useSearchParams();
  const autoSentRef = useRef(false);
  const autoSeededRef = useRef(false);
  const [sessionId, setSessionId] = useState<string | undefined>(undefined);
  const [historyOpen, setHistoryOpen] = useState(false); // mobile drawer
  // Icon-only collapse of the history rail (desktop), persisted across sessions.
  const [historyCollapsed, setHistoryCollapsed] = useState<boolean>(
    () => localStorage.getItem("nv-chat-history-collapsed") === "1",
  );
  useEffect(() => {
    localStorage.setItem("nv-chat-history-collapsed", historyCollapsed ? "1" : "0");
  }, [historyCollapsed]);

  const prompts = useSuggestedPrompts();
  const qc = useQueryClient();
  const createSession = useCreateChatSession();
  const deleteSession = useDeleteChatSession();
  const sessions = useChatSessions();
  const session = useChatSession(sessionId ?? "");

  // Live streaming state for the in-flight answer + the optimistic user bubble.
  const [streaming, setStreaming] = useState<StreamState | null>(null);
  const [pendingUser, setPendingUser] = useState<string | null>(null);
  const firstTokenRef = useRef<number | null>(null);
  const isBusy = streaming !== null;

  // Pace the visible text toward the received buffer over a ~10s window.
  useTypewriterReveal(streaming, setStreaming, firstTokenRef);

  // Warm the lazy Streamdown chunk on entry so the first answer renders
  // markdown without a fallback flash.
  useEffect(() => { void prefetchStreamdown(); }, []);

  const messages = session.data?.messages ?? [];
  const sessionList = sessions.data ?? [];

  // Stream the answer token-by-token via SSE. The server persists both the user
  // and AI messages, so when the stream ends we just refetch history and drop
  // the local streaming/optimistic state.
  const submitMessage = async (text: string) => {
    // Strip any unfilled template placeholders so "{fund} …" never reaches the
    // backend (the user may send before filling the slot).
    const t = text.replace(/\{[^}]*\}/g, " ").replace(/\s+/g, " ").trim();
    if (!t || isBusy) return;
    setEntityFill(null);
    let sid = sessionId;
    if (!sid) {
      const created = await createSession.mutateAsync(undefined);
      sid = created.id;
      setSessionId(sid);
    }
    setPendingUser(t);
    firstTokenRef.current = null;
    setStreaming({ buffer: "", content: "" });
    try {
      await chatService.streamSend(t, sid, (ev) => {
        setStreaming((s) => {
          if (!s) return s;
          switch (ev.type) {
            case "thinking": return { ...s, thinking: ev.status === "start" ? ev.tool : undefined };
            // Tokens accumulate into `buffer`; the typewriter reveals `content`.
            case "token":    return { ...s, buffer: s.buffer + (ev.content ?? ""), thinking: undefined };
            case "widget":
              // Start the reveal window at widget arrival so the staggered
              // build (and the bubble hold) span ~10s even with little/no text.
              if (firstTokenRef.current == null) firstTokenRef.current = performance.now();
              return { ...s, widget: { widget_type: ev.widget_type, data: ev.data } };
            case "error":    return { ...s, error: ev.content };
            default:         return s;
          }
        });
      });
    } catch {
      setStreaming((s) => (s ? { ...s, error: "Connection interrupted — please try again." } : s));
    }
    // Hold the bubble open until the paced reveal finishes its ~10s window
    // (the stream itself may have completed in ~1s).
    await new Promise((r) => setTimeout(r, remainingRevealMs(firstTokenRef.current)));
    setStreaming(null);
    setPendingUser(null);
    qc.invalidateQueries({ queryKey: ["chat", "sessions", sid] });
    qc.invalidateQueries({ queryKey: ["chat", "sessions"] });
  };

  const handleSend = async () => {
    const text = composer.trim();
    if (!text || isBusy) return;
    setComposer("");
    await submitMessage(text);
  };

  // Research tool chips — prefill the composer with a routing-safe starter and
  // focus the input so the user just types the stock/fund name. "mutual fund" in
  // the fund starter guarantees the MF analyst (intent _P_MF is matched first).
  const startResearch = (prefill: string) => {
    if (isBusy) return;
    setComposer(prefill);
    setSuggestOpen(true);
    setActiveIdx(-1);
    requestAnimationFrame(() => {
      const el = inputRef.current;
      if (el) { el.focus(); el.setSelectionRange(prefill.length, prefill.length); }
    });
  };

  // ── Instrument autocomplete (stock / fund names) ──
  const eq = entityQuery(composer);
  const debouncedTerm = useDebounce(eq.active ? eq.term : "", 220);
  const instrSearch = useInstrumentSearch(debouncedTerm);
  const suggestions = useMemo<Suggestion[]>(() => {
    const data = instrSearch.data;
    if (!data) return [];
    const out: Suggestion[] = [];
    if (eq.mode !== "funds") {
      for (const s of data.stocks as StockHit[]) {
        out.push({ kind: "stock", symbol: s.symbol, name: s.name, sub: s.sector ?? undefined });
      }
    }
    for (const f of data.funds as FundHit[]) {
      out.push({ kind: "fund", name: f.name, sub: [f.amc, f.category].filter(Boolean).join(" · ") || undefined });
    }
    return out.slice(0, 8);
  }, [instrSearch.data, eq.mode]);
  const showSuggest = suggestOpen && eq.active && !isBusy && !entityFill && (suggestions.length > 0 || instrSearch.isFetching);

  // Pick a suggestion → send a routing-safe research prompt for that instrument.
  const pickSuggestion = (s: Suggestion) => {
    const prompt = s.kind === "fund"
      ? `Tell me about the mutual fund ${s.name}`
      : `Tell me about ${s.name}`;
    setSuggestOpen(false);
    setActiveIdx(-1);
    setComposer("");
    void submitMessage(prompt);
  };

  // ── Screener-primitive autocomplete (ROE, P/E, D/E, …) ──
  const sq = screenQuery(composer);
  const screenSuggestions = useMemo<ScreenPrimitive[]>(() => {
    if (!sq.active) return [];
    const f = sq.fragment.toLowerCase();
    if (!f) return SCREEN_PRIMITIVES;
    return SCREEN_PRIMITIVES.filter(
      (p) => p.label.toLowerCase().includes(f) || p.qlabel.toLowerCase().includes(f) || p.key.includes(f),
    );
  }, [sq.active, sq.fragment]);
  const showScreenSuggest = suggestOpen && sq.active && !isBusy && !entityFill && screenSuggestions.length > 0;

  // Insert the primitive's clause in place of the current fragment, keep focus
  // so the user types the threshold next. Does NOT submit.
  const pickPrimitive = (p: ScreenPrimitive) => {
    const next = sq.base.replace(/\s*$/, " ") + screenInsert(p);
    setComposer(next);
    setSuggestOpen(false);
    setActiveIdx(-1);
    requestAnimationFrame(() => {
      const el = inputRef.current;
      if (el) { el.focus(); el.setSelectionRange(next.length, next.length); }
    });
  };

  // ── Suggested questions (the curated question bank) ──
  // Only when the composer isn't already in research (instrument) or screener
  // mode, so the three typeaheads never compete — at most one shows at a time.
  const genActive = !entityFill && !eq.active && !sq.active && composer.trim().length >= 2;
  const debouncedGenTerm = useDebounce(genActive ? composer.trim() : "", 220);
  const genSearch = useQuerySuggestions(debouncedGenTerm);
  const genSuggestions = genSearch.data?.suggestions ?? [];
  const showGenSuggest =
    suggestOpen && genActive && !isBusy && !showSuggest && !showScreenSuggest &&
    (genSuggestions.length > 0 || genSearch.isFetching);

  // Pick a question suggestion. If it has an instrument placeholder ({stock}/
  // {fund}/…), enter entity-fill mode so canonical names autocomplete; for any
  // other placeholder ({amount}/{n}) just fill and select it; otherwise fill and
  // drop the cursor at the end. Never auto-submits.
  const pickQuery = (s: QuerySuggestion) => {
    setActiveIdx(-1);
    const ent = s.query.match(_ENTITY_PH);
    if (ent && ent.index != null) {
      const before = s.query.slice(0, ent.index);
      const after = s.query.slice(ent.index + ent[0].length);
      setEntityFill({ before, after, kind: _entityKind(ent[1]) });
      setSuggestOpen(true);
      setComposer(before);
      requestAnimationFrame(() => {
        const el = inputRef.current;
        if (el) { el.focus(); el.setSelectionRange(before.length, before.length); }
      });
      return;
    }
    setSuggestOpen(false);
    setEntityFill(null);
    setComposer(s.query);
    requestAnimationFrame(() => {
      const el = inputRef.current;
      if (!el) return;
      el.focus();
      const m = s.query.match(/\{[^}]+\}/);
      if (m && m.index != null) el.setSelectionRange(m.index, m.index + m[0].length);
      else el.setSelectionRange(s.query.length, s.query.length);
    });
  };

  // ── Entity-fill autocomplete (canonical stock / fund names) ──
  // Active only while filling a {stock}/{fund} slot of a picked template. The
  // term is whatever the user typed after the template's `before` prefix.
  const entityTerm = entityFill ? composer.slice(entityFill.before.length) : "";
  const debouncedEntityTerm = useDebounce(entityFill ? entityTerm.trim() : "", 220);
  const entityInstr = useInstrumentSearch(debouncedEntityTerm);
  const entitySuggestions = useMemo<Suggestion[]>(() => {
    if (!entityFill) return [];
    const data = entityInstr.data;
    if (!data) return [];
    const out: Suggestion[] = [];
    if (entityFill.kind === "stock") {
      for (const s of data.stocks as StockHit[]) out.push({ kind: "stock", symbol: s.symbol, name: s.name, sub: s.sector ?? undefined });
    } else {
      for (const f of data.funds as FundHit[]) out.push({ kind: "fund", name: f.name, sub: [f.amc, f.category].filter(Boolean).join(" · ") || undefined });
    }
    return out.slice(0, 8);
  }, [entityFill, entityInstr.data]);
  const showEntityFill = !!entityFill && suggestOpen && !isBusy;

  // Pick a canonical name → substitute it into the template. If another
  // instrument placeholder remains (e.g. "{fund} vs {fund2}"), chain to it;
  // otherwise fill the completed query and let the user review/send.
  const pickEntity = (s: Suggestion) => {
    if (!entityFill) return;
    const filled = entityFill.before + s.name + entityFill.after;
    setActiveIdx(-1);
    const nextPh = filled.match(_ENTITY_PH);
    if (nextPh && nextPh.index != null) {
      const before = filled.slice(0, nextPh.index);
      const after = filled.slice(nextPh.index + nextPh[0].length);
      setEntityFill({ before, after, kind: _entityKind(nextPh[1]) });
      setComposer(before);
      requestAnimationFrame(() => {
        const el = inputRef.current;
        if (el) { el.focus(); el.setSelectionRange(before.length, before.length); }
      });
      return;
    }
    setEntityFill(null);
    setSuggestOpen(false);
    setComposer(filled);
    requestAnimationFrame(() => {
      const el = inputRef.current;
      if (el) { el.focus(); el.setSelectionRange(filled.length, filled.length); }
    });
  };

  const onComposerKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (showEntityFill) {
      if (e.key === "ArrowDown") { e.preventDefault(); setActiveIdx((i) => Math.min(entitySuggestions.length - 1, i + 1)); return; }
      if (e.key === "ArrowUp")   { e.preventDefault(); setActiveIdx((i) => Math.max(0, i - 1)); return; }
      if (e.key === "Enter" && activeIdx >= 0 && entitySuggestions[activeIdx]) { e.preventDefault(); pickEntity(entitySuggestions[activeIdx]); return; }
      // Escape exits fill mode but keeps what's typed so the user can finish manually.
      if (e.key === "Escape")    { e.preventDefault(); setEntityFill(null); setSuggestOpen(false); return; }
    }
    if (showSuggest) {
      if (e.key === "ArrowDown") { e.preventDefault(); setActiveIdx((i) => Math.min(suggestions.length - 1, i + 1)); return; }
      if (e.key === "ArrowUp")   { e.preventDefault(); setActiveIdx((i) => Math.max(0, i - 1)); return; }
      if (e.key === "Enter" && activeIdx >= 0 && suggestions[activeIdx]) { e.preventDefault(); pickSuggestion(suggestions[activeIdx]); return; }
      if (e.key === "Escape")    { e.preventDefault(); setSuggestOpen(false); return; }
    }
    if (showScreenSuggest) {
      if (e.key === "ArrowDown") { e.preventDefault(); setActiveIdx((i) => Math.min(screenSuggestions.length - 1, i + 1)); return; }
      if (e.key === "ArrowUp")   { e.preventDefault(); setActiveIdx((i) => Math.max(0, i - 1)); return; }
      if (e.key === "Enter" && activeIdx >= 0 && screenSuggestions[activeIdx]) { e.preventDefault(); pickPrimitive(screenSuggestions[activeIdx]); return; }
      if (e.key === "Escape")    { e.preventDefault(); setSuggestOpen(false); return; }
    }
    if (showGenSuggest) {
      if (e.key === "ArrowDown") { e.preventDefault(); setActiveIdx((i) => Math.min(genSuggestions.length - 1, i + 1)); return; }
      if (e.key === "ArrowUp")   { e.preventDefault(); setActiveIdx((i) => Math.max(0, i - 1)); return; }
      // Enter on a highlighted suggestion fills it; Enter with none highlighted falls through to send.
      if (e.key === "Enter" && activeIdx >= 0 && genSuggestions[activeIdx]) { e.preventDefault(); pickQuery(genSuggestions[activeIdx]); return; }
      if (e.key === "Escape")    { e.preventDefault(); setSuggestOpen(false); return; }
    }
    if (e.key === "Enter") handleSend();
  };

  // Auto-send a `?q=` deep-link once, then strip it from the URL so a
  // refresh doesn't re-fire. Defined after submitMessage so it can call it.
  useEffect(() => {
    if (autoSentRef.current) return;
    const q = searchParams.get("q");
    if (!q) return;
    autoSentRef.current = true;
    searchParams.delete("q");
    setSearchParams(searchParams, { replace: true });
    void submitMessage(q);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Prefill (don't auto-send) the composer from a `?seed=` deep-link, then strip
  // it. Mirrors `?q=` but routes through startResearch so the research-tool tiles
  // on other pages (e.g. Portfolio insights) land the user in the composer with
  // autocomplete open, ready to type the instrument name.
  useEffect(() => {
    if (autoSeededRef.current) return;
    const seed = searchParams.get("seed");
    if (!seed) return;
    autoSeededRef.current = true;
    searchParams.delete("seed");
    setSearchParams(searchParams, { replace: true });
    startResearch(seed);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);


  // Widget action chips → drive a follow-up. Some send immediately; "recalc"
  // prefills the composer so the user can type their real SIP amount.
  const navigate = useNavigate();
  const handleWidgetAction = (a: { intent?: string; query?: string; label?: string }) => {
    if (a.intent === "open" && a.query) navigate(a.query);        // widget deep-link → full dashboard
    else if (a.intent === "review_overlap") void submitMessage("Which of my funds overlap the most?");
    else if (a.intent === "recalc_sip") setComposer("Recalculate my retirement plan with a monthly SIP of ₹");
    else if (a.query) void submitMessage(a.query);
    else if (a.label) void submitMessage(a.label);
  };

  // Start a fresh thread — old conversations stay in history.
  const handleNewChat = () => {
    setSessionId(undefined);
    setComposer("");
    setHistoryOpen(false);
  };

  const handleOpen = (id: string) => {
    setSessionId(id);
    setHistoryOpen(false);
  };

  // Delete a conversation (and its messages) from history.
  const handleDelete = async (id: string) => {
    await deleteSession.mutateAsync(id);
    if (id === sessionId) setSessionId(undefined);
  };

  // "Clear chat" — delete the conversation currently open, then reset.
  const handleClearCurrent = async () => {
    if (!sessionId || deleteSession.isPending) return;
    if (!window.confirm("Delete this conversation? This can't be undone.")) return;
    await deleteSession.mutateAsync(sessionId);
    setSessionId(undefined);
    setComposer("");
  };

  const promptList = prompts.data && prompts.data.length > 0 ? prompts.data : FALLBACK_PROMPTS;

  return (
    <div className="flex min-h-[calc(100vh-4rem)]">
      {/* ── History sidebar (static on md+, slide-over drawer on mobile) ── */}
      <aside
        className={cn(
          "shrink-0 w-64 border-r border-hairline bg-surface-1/40 flex-col transition-[width] duration-200",
          historyCollapsed && "md:w-14",
          historyOpen
            ? "flex fixed inset-y-0 left-0 z-30 bg-bg shadow-xl md:static md:shadow-none md:bg-surface-1/40"
            : "hidden md:flex",
        )}
      >
        {/* Collapsed rail — desktop only, icons only */}
        <div className={cn("hidden flex-col items-center gap-2 p-2", historyCollapsed && "md:flex")}>
          <button
            onClick={handleNewChat}
            className="p-2 rounded-md border border-hairline-2 text-ink hover:bg-surface-2 transition-colors"
            aria-label="New chat"
            title="New chat"
          >
            <Plus className="h-4 w-4" />
          </button>
          <button
            onClick={() => setHistoryCollapsed(false)}
            className="p-2 rounded-md text-ink-3 hover:text-ink hover:bg-surface-2 transition-colors"
            aria-label="Expand history"
            title="Expand history"
          >
            <PanelLeftOpen className="h-4 w-4" />
          </button>
        </div>

        {/* Full panel — mobile drawer + expanded desktop */}
        <div className={cn("flex flex-col flex-1 min-h-0", historyCollapsed && "md:hidden")}>
          <div className="p-3 flex items-center gap-2">
            <button
              onClick={handleNewChat}
              className="flex-1 flex items-center gap-2 px-3 py-2 rounded-md border border-hairline-2 text-[13px] text-ink hover:bg-surface-2 transition-colors"
            >
              <Plus className="h-4 w-4" /> New chat
            </button>
            <button
              onClick={() => setHistoryCollapsed(true)}
              className="hidden md:inline-flex p-2 rounded-md text-ink-3 hover:text-ink hover:bg-surface-2 transition-colors"
              aria-label="Collapse history"
              title="Collapse history"
            >
              <PanelLeftClose className="h-4 w-4" />
            </button>
            <button onClick={() => setHistoryOpen(false)} className="md:hidden p-2 text-ink-3" aria-label="Close history">
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="px-4 pb-1.5 font-mono text-[10px] uppercase tracking-[.18em] text-ink-3">History</div>
          <div className="flex-1 overflow-y-auto px-2 pb-3">
            {sessions.isPending && Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-11 w-full rounded-md mb-1.5" />
            ))}
            {!sessions.isPending && sessionList.length === 0 && (
              <p className="px-3 py-2 text-[12.5px] text-ink-3 leading-relaxed">No conversations yet. Start one on the right.</p>
            )}
            {sessionList.map((s) => (
              <div
                key={s.id}
                onClick={() => handleOpen(s.id)}
                className={cn(
                  "group flex items-center justify-between gap-2 px-3 py-2 rounded-md cursor-pointer transition-colors",
                  s.id === sessionId ? "bg-surface-2" : "hover:bg-surface-2/60",
                )}
              >
                <div className="min-w-0">
                  <div className="truncate text-[13px] text-ink">{s.title}</div>
                  {s.updatedAt && <div className="text-[11px] text-ink-3 mt-0.5">{relTime(s.updatedAt)}</div>}
                </div>
                <button
                  onClick={(e) => { e.stopPropagation(); void handleDelete(s.id); }}
                  className="opacity-0 group-hover:opacity-100 focus:opacity-100 p-1 rounded text-ink-3 hover:text-neg transition"
                  aria-label="Delete conversation"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>
        </div>
      </aside>

      {/* mobile backdrop */}
      {historyOpen && <div className="fixed inset-0 bg-black/30 z-20 md:hidden" onClick={() => setHistoryOpen(false)} />}

      {/* ── Conversation column ── */}
      <div className="flex-1 min-w-0 flex flex-col px-6 py-8 lg:px-10 lg:py-10 max-w-[880px] mx-auto w-full">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="font-mono text-[11px] uppercase tracking-[.18em] text-ink-3">Chat</div>
            <h1 className="font-display text-3xl sm:text-4xl tracking-tightish leading-[1.05] mt-1.5">
              Ask anything about your portfolio.
            </h1>
          </div>
          <div className="flex items-center gap-2 shrink-0 mt-1">
            <button
              onClick={() => setHistoryOpen(true)}
              className="md:hidden flex items-center gap-1.5 px-3 py-2 rounded-md border border-hairline text-[12.5px] text-ink-2 hover:bg-surface-2 transition-colors"
            >
              <HistoryIcon className="h-3.5 w-3.5" /> History
            </button>
            {messages.length > 0 && (
              <button
                onClick={handleClearCurrent}
                disabled={deleteSession.isPending}
                className="flex items-center gap-1.5 px-3 py-2 rounded-md border border-hairline text-[12.5px] text-ink-2 hover:bg-surface-2 disabled:opacity-50 transition-colors"
              >
                <Trash2 className="h-3.5 w-3.5" /> Clear chat
              </button>
            )}
          </div>
        </div>

        {messages.length === 0 && (
          isAdvisor ? (
            <CopilotWorkflows isAdvisor onLaunch={(q) => void submitMessage(q)} />
          ) : (
            <CopilotReview onAsk={(q) => void submitMessage(q)} />
          )
        )}

        <div className="mt-6">
          {/* My Portfolio Insights — explicit, icon-led research entry points */}
          <div className="font-mono text-[11px] uppercase tracking-[.18em] text-ink-3">My Portfolio Insights</div>
          <div className="flex flex-wrap gap-2 mt-3">
            <button
              onClick={() => setAnalyseOpen((v) => !v)}
              disabled={isBusy}
              className={cn(
                "inline-flex items-center gap-1.5 px-3.5 py-2 rounded-full border text-[12.5px] transition-colors disabled:opacity-50",
                analyseOpen
                  ? "border-accent bg-[rgb(var(--accent)/0.10)] text-accent"
                  : "bg-surface-1 border-hairline-2 text-ink hover:bg-surface-2",
              )}
              title="Analyse my portfolio — pick a ready-made question"
            >
              <Sparkles className="h-3.5 w-3.5 text-accent" /> Analyse my portfolio
            </button>
            <button
              onClick={() => startResearch("Tell me about ")}
              disabled={isBusy}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-full bg-surface-1 border border-hairline-2 text-[12.5px] text-ink hover:bg-surface-2 disabled:opacity-50 transition-colors"
              title="Research a stock — type a company name or NSE symbol"
            >
              <LineChart className="h-3.5 w-3.5 text-accent" /> Research a stock
            </button>
            <button
              onClick={() => startResearch("Tell me about the mutual fund ")}
              disabled={isBusy}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-full bg-surface-1 border border-hairline-2 text-[12.5px] text-ink hover:bg-surface-2 disabled:opacity-50 transition-colors"
              title="Research a mutual fund — type the fund name"
            >
              <PieChart className="h-3.5 w-3.5 text-accent" /> Research a fund
            </button>
            <button
              onClick={() => void submitMessage("Build me a portfolio")}
              disabled={isBusy}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-full bg-surface-1 border border-hairline-2 text-[12.5px] text-ink hover:bg-surface-2 disabled:opacity-50 transition-colors"
              title="Build a portfolio — goal, risk profile and a ranked mix on live V3 scores"
            >
              <Wand2 className="h-3.5 w-3.5 text-accent" /> Build a portfolio
            </button>
            {/* Strategy Builder chip intentionally hidden (feature de-surfaced). */}
            <button
              onClick={() => setBacktestOpen((v) => !v)}
              disabled={isBusy}
              className={cn(
                "inline-flex items-center gap-1.5 px-3.5 py-2 rounded-full border text-[12.5px] transition-colors disabled:opacity-50",
                backtestOpen
                  ? "border-accent bg-[rgb(var(--accent)/0.10)] text-accent"
                  : "bg-surface-1 border-hairline-2 text-ink hover:bg-surface-2",
              )}
              title="Backtest a basket — pick a ready-made basket or build your own; see what a lump-sum & SIP would be worth today (1y & 3y)"
            >
              <HistoryIcon className="h-3.5 w-3.5 text-accent" /> Backtest a basket
            </button>
            <button
              onClick={() => setBuilderOpen((v) => !v)}
              disabled={isBusy}
              className={cn(
                "inline-flex items-center gap-1.5 px-3.5 py-2 rounded-full border text-[12.5px] transition-colors disabled:opacity-50",
                builderOpen
                  ? "border-accent bg-[rgb(var(--accent)/0.10)] text-accent"
                  : "bg-surface-1 border-hairline-2 text-ink hover:bg-surface-2",
              )}
              title="Build a screen visually — pick metrics, operators and thresholds"
            >
              <ListFilter className="h-3.5 w-3.5 text-accent" /> Stocks Screener
            </button>
            <button
              onClick={() => setStockInsightsOpen((v) => !v)}
              disabled={isBusy}
              className={cn(
                "inline-flex items-center gap-1.5 px-3.5 py-2 rounded-full border text-[12.5px] transition-colors disabled:opacity-50",
                stockInsightsOpen
                  ? "border-accent bg-[rgb(var(--accent)/0.10)] text-accent"
                  : "bg-surface-1 border-hairline-2 text-ink hover:bg-surface-2",
              )}
              title="Stocks Insight — explore company filings, financials & disclosures"
              data-testid="tool-stocks-insight"
            >
              <Building2 className="h-3.5 w-3.5 text-accent" /> Stocks Insight
            </button>
          </div>

          {stockInsightsOpen && (
            <StockInsightsLanding onLaunch={(q) => { setStockInsightsOpen(false); void submitMessage(q); }} />
          )}

          {/* Analyse my portfolio — ready-made questions, revealed by the
              launcher chip above (mirrors the Query builder reveal). */}
          {analyseOpen && (
            <div className="mt-6">
              <div className="font-mono text-[11px] uppercase tracking-[.18em] text-ink-3">Analyse my portfolio</div>
              <div className="flex flex-wrap gap-2 mt-3">
                {prompts.isPending && Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="h-9 w-40 rounded-full" />
                ))}
                {!prompts.isPending && promptList.map((q) => (
                  <button
                    key={q}
                    onClick={() => setComposer(q)}
                    className="px-3.5 py-2 rounded-full bg-surface-2 border border-hairline text-[12.5px] text-ink-2 hover:bg-surface-3 transition-colors"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Backtest a basket — predefined baskets (one-click, ready to send)
              plus a "create your own" entry that focuses the composer with
              instrument autocomplete. Revealed by the launcher chip above. */}
          {backtestOpen && (
            <div className="mt-6">
              <div className="font-mono text-[11px] uppercase tracking-[.18em] text-ink-3">Backtest a basket</div>
              <div className="flex flex-wrap gap-2 mt-3">
                {BACKTEST_BASKETS.map((b) => (
                  <button
                    key={b.label}
                    onClick={() => { setBacktestOpen(false); setComposer(b.query); }}
                    disabled={isBusy}
                    title={b.query}
                    className="flex flex-col items-start px-3.5 py-2 rounded-2xl bg-surface-2 border border-hairline text-left hover:bg-surface-3 disabled:opacity-50 transition-colors"
                  >
                    <span className="text-[12.5px] text-ink">{b.label}</span>
                    <span className="text-[11px] text-ink-3">{b.sub}</span>
                  </button>
                ))}
                <button
                  onClick={() => { setBacktestOpen(false); startResearch("If I had invested 10L in "); }}
                  disabled={isBusy}
                  title="Create your own — name the stocks/funds to backtest"
                  className="flex flex-col items-start px-3.5 py-2 rounded-2xl bg-surface-1 border border-dashed border-hairline-2 text-left hover:bg-surface-2 disabled:opacity-50 transition-colors"
                >
                  <span className="text-[12.5px] text-accent">+ Create your own</span>
                  <span className="text-[11px] text-ink-3">type stocks / funds</span>
                </button>
              </div>
              <p className="text-[11px] text-ink-3 mt-2.5">Edit the amount or period before sending. Historical illustration, not a prediction.</p>
            </div>
          )}
        </div>

        <div className="mt-7 flex-1 flex flex-col gap-5">
          {messages.map((m, i) => {
            const isUser = m.role === "user";
            const widget = !isUser ? (m as { widget?: { widget_type?: string; data?: unknown } }).widget : undefined;
            const hasWidget = !!widget?.widget_type && WIDGET_TYPES.has(widget.widget_type);
            return (
              <div key={m.id ?? i} className={cn(isUser ? "self-end max-w-[520px] px-4 py-3 rounded-2xl rounded-br-md bg-surface-2 border border-hairline" : "flex gap-3.5")}>
                {!isUser && (
                  <span className="grid place-items-center h-9 w-9 rounded-md bg-ink text-on-accent font-display text-base leading-none shrink-0">न</span>
                )}
                <div className={isUser ? "" : "flex-1 min-w-0"}>
                  {isUser ? (
                    <p className="text-[14px]">{m.content}</p>
                  ) : hasWidget ? (
                    // Widget is the answer (its hero line types out the summary).
                    <ChatWidget widget={widget} onAction={handleWidgetAction} />
                  ) : m.content?.trim() ? (
                    <Markdown className="text-[15.5px] leading-relaxed text-ink-2">{m.content}</Markdown>
                  ) : null}
                </div>
              </div>
            );
          })}

          {/* Optimistic user bubble. On a new session the session query refetches
              mid-stream and already contains the persisted copy, so suppress this
              bubble once the latest persisted message is that same user turn —
              otherwise the message renders twice for the duration of the answer. */}
          {pendingUser &&
            !(messages.length > 0 &&
              messages[messages.length - 1].role === "user" &&
              messages[messages.length - 1].content === pendingUser) && (
            <div className="self-end max-w-[520px] px-4 py-3 rounded-2xl rounded-br-md bg-surface-2 border border-hairline">
              <p className="text-[14px]">{pendingUser}</p>
            </div>
          )}

          {/* live streaming answer */}
          {streaming && (
            <div className="flex gap-3.5">
              <span className="grid place-items-center h-9 w-9 rounded-md bg-ink text-on-accent font-display text-base leading-none shrink-0">न</span>
              <div className="flex-1 min-w-0">
                {streaming.error ? (
                  <p className="text-[14px] text-neg">{streaming.error}</p>
                ) : streaming.widget && WIDGET_TYPES.has(streaming.widget.widget_type) ? (
                  // Widget is the answer: it builds in steps (sd-stagger) and its
                  // hero line (section 1) types out the summary as it lands.
                  <div className="sd-stagger">
                    <ChatWidget widget={streaming.widget} onAction={handleWidgetAction} />
                  </div>
                ) : streaming.content ? (
                  <Markdown caret className="text-[15.5px] leading-relaxed text-ink-2">
                    {streaming.content}
                  </Markdown>
                ) : (
                  <div className="flex items-center gap-2 text-ink-3">
                    {streaming.thinking ? (
                      <span className="text-[13px]">Reading your portfolio…</span>
                    ) : (
                      <><Dot delay={0} /><Dot delay={150} /><Dot delay={300} /></>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* visual query builder — sits above the composer when open */}
        {builderOpen && (
          <div className="mt-4">
            <ScreenerQueryBuilder
              onClose={() => setBuilderOpen(false)}
              onRun={(q) => { setBuilderOpen(false); setComposer(""); void submitMessage(q); }}
            />
          </div>
        )}

        {/* composer */}
        <div className="mt-7 sticky bottom-0 bg-bg/95 backdrop-blur relative">
          {/* screener-primitive autocomplete — opens upward above the input */}
          {showScreenSuggest && (
            <div className="absolute bottom-full left-0 right-0 mb-2 rounded-lg bg-surface-1 border border-hairline-2 shadow-card overflow-hidden z-20">
              <div className="px-3.5 pt-2.5 pb-1 font-mono text-[10px] uppercase tracking-[.18em] text-ink-3">Add a filter</div>
              <ul className="max-h-72 overflow-y-auto py-1">
                {screenSuggestions.map((p, i) => (
                  <Fragment key={p.key}>
                    {(i === 0 || screenSuggestions[i - 1].cat !== p.cat) && (
                      <li className="px-3.5 pt-2 pb-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink-3/70">{p.cat}</li>
                    )}
                  <li>
                    <button
                      type="button"
                      onMouseDown={(e) => { e.preventDefault(); pickPrimitive(p); }}
                      onMouseEnter={() => setActiveIdx(i)}
                      className={cn(
                        "w-full flex items-center gap-2.5 px-3.5 py-2 text-left transition-colors",
                        i === activeIdx ? "bg-surface-2" : "hover:bg-surface-2/60",
                      )}
                    >
                      <SlidersHorizontal className="h-3.5 w-3.5 text-accent shrink-0" />
                      <span className="min-w-0 flex-1">
                        <span className="block text-[13.5px] text-ink truncate">{p.label}</span>
                        <span className="block text-[11.5px] text-ink-3 truncate">{p.hint}</span>
                      </span>
                      <span className="shrink-0 rounded-full bg-surface-2 px-2 py-0.5 text-[9.5px] font-semibold tracking-wide text-ink-3">
                        {p.tag}
                      </span>
                    </button>
                  </li>
                  </Fragment>
                ))}
              </ul>
            </div>
          )}
          {/* entity-fill autocomplete — canonical stock/fund names for a picked
              template's {stock}/{fund} slot. Opens upward above the input. */}
          {showEntityFill && (
            <div className="absolute bottom-full left-0 right-0 mb-2 rounded-lg bg-surface-1 border border-hairline-2 shadow-card overflow-hidden z-20">
              <div className="px-3.5 pt-2.5 pb-1 font-mono text-[10px] uppercase tracking-[.18em] text-ink-3">
                Pick a {entityFill?.kind === "stock" ? "stock" : "fund"} to fill in
              </div>
              {entitySuggestions.length === 0 ? (
                <div className="px-4 py-3 text-[13px] text-ink-3">
                  {entityInstr.isFetching ? "Searching…" : `Type a ${entityFill?.kind === "stock" ? "stock" : "fund"} name…`}
                </div>
              ) : (
                <ul className="max-h-72 overflow-y-auto py-1">
                  {entitySuggestions.map((s, i) => (
                    <li key={(s.kind === "stock" ? s.symbol : s.name) + i}>
                      <button
                        type="button"
                        onMouseDown={(e) => { e.preventDefault(); pickEntity(s); }}
                        onMouseEnter={() => setActiveIdx(i)}
                        className={cn(
                          "w-full flex items-center gap-2.5 px-3.5 py-2 text-left transition-colors",
                          i === activeIdx ? "bg-surface-2" : "hover:bg-surface-2/60",
                        )}
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
          {/* instrument autocomplete — opens upward above the input */}
          {showSuggest && (
            <div className="absolute bottom-full left-0 right-0 mb-2 rounded-lg bg-surface-1 border border-hairline-2 shadow-card overflow-hidden z-20">
              {instrSearch.isFetching && suggestions.length === 0 ? (
                <div className="px-4 py-3 text-[13px] text-ink-3">Searching…</div>
              ) : (
                <ul className="max-h-72 overflow-y-auto py-1">
                  {suggestions.map((s, i) => (
                    <li key={(s.kind === "stock" ? s.symbol : s.name) + i}>
                      <button
                        type="button"
                        onMouseDown={(e) => { e.preventDefault(); pickSuggestion(s); }}
                        onMouseEnter={() => setActiveIdx(i)}
                        className={cn(
                          "w-full flex items-center gap-2.5 px-3.5 py-2 text-left transition-colors",
                          i === activeIdx ? "bg-surface-2" : "hover:bg-surface-2/60",
                        )}
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
          {/* suggested-question autocomplete — opens upward above the input */}
          {showGenSuggest && (
            <div className="absolute bottom-full left-0 right-0 mb-2 rounded-lg bg-surface-1 border border-hairline-2 shadow-card overflow-hidden z-20">
              <div className="px-3.5 pt-2.5 pb-1 font-mono text-[10px] uppercase tracking-[.18em] text-ink-3">Suggested questions</div>
              {genSearch.isFetching && genSuggestions.length === 0 ? (
                <div className="px-4 py-3 text-[13px] text-ink-3">Searching…</div>
              ) : (
                <ul className="max-h-72 overflow-y-auto py-1">
                  {genSuggestions.map((s, i) => (
                    <li key={s.query + i}>
                      <button
                        type="button"
                        onMouseDown={(e) => { e.preventDefault(); pickQuery(s); }}
                        onMouseEnter={() => setActiveIdx(i)}
                        className={cn(
                          "w-full flex items-center gap-2.5 px-3.5 py-2 text-left transition-colors",
                          i === activeIdx ? "bg-surface-2" : "hover:bg-surface-2/60",
                        )}
                      >
                        <Sparkles className="h-3.5 w-3.5 text-accent shrink-0" />
                        <span className="min-w-0 flex-1">
                          <span className="block text-[13.5px] text-ink truncate">{s.query}</span>
                          <span className="block text-[11.5px] text-ink-3 truncate">{[s.section, s.category].filter(Boolean).join(" · ")}</span>
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
          <div
            className={cn(
              "flex items-center gap-3 px-4 py-3 rounded-md bg-surface-1 border border-hairline-2",
              "focus-within:border-accent",
            )}
          >
            <Plus className="h-4 w-4 text-ink-3" />
            <input
              ref={inputRef}
              type="text"
              placeholder="Ask anything…"
              value={composer}
              onChange={(e) => { setComposer(e.target.value); setSuggestOpen(true); setActiveIdx(-1); }}
              onKeyDown={onComposerKeyDown}
              onFocus={() => setSuggestOpen(true)}
              onBlur={() => setTimeout(() => setSuggestOpen(false), 120)}
              autoComplete="off"
              className="flex-1 bg-transparent outline-none text-[14.5px]"
              disabled={isBusy}
            />
            <Button variant="accent" size="sm" disabled={!composer.trim() || isBusy} onClick={handleSend}>
              <Send className="h-3.5 w-3.5" /> Send
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Dot({ delay }: { delay: number }) {
  return (
    <span
      className="h-1.5 w-1.5 rounded-full bg-ink-3"
      style={{ animation: `pulse 1.2s ${delay}ms infinite ease-in-out` }}
    />
  );
}
