/**
 * Research — "Filings Intelligence".
 *
 * A standalone, single-purpose Copilot surface over corporate filings, built to
 * the designs in docs/ai_research/designs/ (desktop + mobile) and wired to REAL
 * data — no hardcoded rows, no mock:
 *
 *   Ask bar          → the copilot PINNED to `stocks_insights`
 *                      (POST /api/chat/stream {"agent":"stocks_insights"} →
 *                       CopilotState.pinned_agent), so a question here is always
 *                       answered from filed exchange disclosures, never memory.
 *                      SOURCES chips come from the widget's own sources[].
 *   Read for you     → GET /api/filings/signals   (today's top-3 material filings)
 *   All filings      → GET /api/filings/feed       (facets · MATERIAL/LATEST · paging)
 *   Tap-to-expand    → GET /api/filings/{id}/insights — tabs + sectioned bullets
 *                      with `pp. N-M` citations that deep-link into the PDF.
 *   Alerts           → GET/PUT /api/filings/alerts (filing types + channels)
 *
 * Honesty (FILINGS_HOME_SPEC §4):
 *   · A row renders what is really in the filing (company, category, impact,
 *     time, subject). One-liner / headline metric appear ONLY when the generator
 *     produced them — otherwise no synthetic number is shown.
 *   · Insight tabs are whatever the document actually supported. A tab the
 *     filing could not answer is absent, not padded with hedging prose.
 *   · Alert preferences save for real, but DELIVERY IS NOT BUILT. The screen says
 *     so rather than implying alerts fire (backend `delivery.active`).
 *
 * Responsive: one component. Desktop (≥lg) gets the 64px icon rail + top header;
 * below that the mobile design's app header + bottom tab bar.
 */
import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import {
  Search, FileText, ExternalLink, Sparkles, Loader2, Bell, Bookmark,
  ChevronLeft, ChevronRight, MoreVertical, Megaphone, X, Download, Star,
  ClipboardCheck,
} from "lucide-react";
import { Link } from "react-router-dom";
import { chatService } from "@/services";
import { Markdown } from "@/components/chat/Markdown";
import { filingsService } from "@/services/adapters/filings.adapter";
import type {
  FilingRow, Signal, Insight, InsightSection, Alerts, Company, CompanyDocs,
} from "@/services/adapters/filings.adapter";
import "./research.css";
import { THEMATIC_STARTERS, STARTERS_PAGE } from "@/data/thematicStarters";
import { useThematicQueries } from "@/hooks/useThematicQueries";

/** The one agent this surface is allowed to reach (backend _PINNABLE_AGENTS). */
const PINNED_AGENT = "stocks_insights";
/** The classifier's queue floor (spec §4.1) — the feed window is honest at 30d. */
const FEED_DAYS = 30;
const PAGE_SIZE = 20;

type Screen = "feed" | "alerts";

/** sentiment → accent (matches the prototype's sig-* classes). */
function sig(sentiment?: string | null): { cls: string; dot: string } {
  const s = (sentiment || "").toLowerCase();
  if (s === "positive") return { cls: "sig-good", dot: "dot-good" };
  if (s === "negative") return { cls: "sig-risk", dot: "dot-risk" };
  return { cls: "sig-info", dot: "dot-info" };
}
function pill(sentiment?: string | null): string {
  const s = (sentiment || "").toLowerCase();
  if (s === "positive") return "nv-pill-mint";
  if (s === "negative") return "nv-pill-danger";
  return "nv-pill-indigo";
}
function fmtDate(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return String(iso).slice(0, 10);
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short" });
}
function titleCase(s?: string | null): string {
  if (!s) return "";
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

interface Answer {
  q: string;
  text: string;
  confidence?: number;
  streaming: boolean;
  /** Tickers the copilot actually cited, from the widget's sources[]. */
  refs: string[];
}

export default function ResearchPage() {
  // ── shell ───────────────────────────────────────────────────────────────
  const [screen, setScreen] = useState<Screen>("feed");

  // ── feed state ──────────────────────────────────────────────────────────
  const [rows, setRows] = useState<FilingRow[]>([]);
  const [total, setTotal] = useState(0);
  const [facets, setFacets] = useState<Record<string, number>>({});
  const [category, setCategory] = useState<string | null>(null);
  const [sort, setSort] = useState<"material" | "latest">("material");
  const [page, setPage] = useState(1);
  const [feedLoading, setFeedLoading] = useState(true);
  const [feedError, setFeedError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  // ── company scope (type-ahead selection) ────────────────────────────────
  // `company` is an EXACT ticker scope; `query` is the fuzzy free-text box.
  // Selecting a suggestion sets the former and clears the latter, so the feed,
  // the facet counts and the documents panel all describe one company.
  const [company, setCompany] = useState<Company | null>(null);
  const [suggestions, setSuggestions] = useState<Company[]>([]);
  const [suggestOpen, setSuggestOpen] = useState(false);
  const [suggestIdx, setSuggestIdx] = useState(-1);
  const [docs, setDocs] = useState<CompanyDocs | null>(null);
  const [docsLoading, setDocsLoading] = useState(false);

  // ── signals ─────────────────────────────────────────────────────────────
  const [signals, setSignals] = useState<Signal[]>([]);
  const [todayOnly, setTodayOnly] = useState(true);
  const [held, setHeld] = useState<{ names: Set<string>; isins: Set<string>; symbols: Set<string> }>(
    { names: new Set(), isins: new Set(), symbols: new Set() });

  // ── expanded insight ────────────────────────────────────────────────────
  const [expanded, setExpanded] = useState<string | null>(null);
  const [tab, setTab] = useState<Record<string, string>>({});
  const [insights, setInsights] = useState<Record<string, Insight | null>>({});
  const [insightLoading, setInsightLoading] = useState<Record<string, boolean>>({});
  const [flashed, setFlashed] = useState<string | null>(null);
  const rowRefs = useRef<Record<string, HTMLDivElement | null>>({});

  // ── ask bar (pinned copilot) ────────────────────────────────────────────
  const [draft, setDraft] = useState("");
  const [answer, setAnswer] = useState<Answer | null>(null);
  const sessionRef = useRef<string | undefined>(undefined);
  const asking = answer?.streaming ?? false;

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  // ── loaders ─────────────────────────────────────────────────────────────
  const loadFeed = useCallback(async () => {
    setFeedLoading(true);
    setFeedError(null);
    try {
      const data = await filingsService.getFeed({
        days: FEED_DAYS,
        category: category ?? undefined,
        // An exact company scope supersedes the fuzzy text box.
        symbol: company?.symbol,
        q: company ? undefined : (query.trim() || undefined),
        sort,
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
      });
      setRows(data.rows);
      setTotal(data.total ?? data.rows.length);
      // Always take the response's facets, even when empty. Keeping the previous
      // map "to avoid flicker" would leave whole-feed taxonomy on screen after
      // scoping to a company that has none of it — the exact thing this change
      // set out to fix.
      setFacets(data.facets ?? {});
    } catch {
      setFeedError("Couldn't load filings right now.");
      setRows([]);
    } finally {
      setFeedLoading(false);
    }
  }, [category, sort, page, query, company]);

  useEffect(() => { loadFeed(); }, [loadFeed]);
  useEffect(() => {
    filingsService.getSignals(1, todayOnly).then(setSignals).catch(() => setSignals([]));
  }, [todayOnly]);
  useEffect(() => {
    filingsService.getPortfolioHeld()
      .then((h) => setHeld({ names: new Set(h.names), isins: new Set(h.isins), symbols: new Set(h.symbols) }))
      .catch(() => { /* not signed in / no holdings */ });
  }, []);

  // ── company type-ahead ──────────────────────────────────────────────────
  // Debounced so a fast typist fires one request, not one per keystroke. The
  // `cancelled` guard drops a slow in-flight response that resolves after a
  // newer one, which would otherwise repopulate the list with stale matches.
  useEffect(() => {
    const term = query.trim();
    if (company || term.length < 2) { setSuggestions([]); return; }
    let cancelled = false;
    const t = window.setTimeout(() => {
      filingsService.searchCompanies(term)
        .then((list) => { if (!cancelled) { setSuggestions(list); setSuggestIdx(-1); } })
        .catch(() => { if (!cancelled) setSuggestions([]); });
    }, 220);
    return () => { cancelled = true; window.clearTimeout(t); };
  }, [query, company]);

  /** Scope everything to one company: feed, facets and the document library. */
  const selectCompany = useCallback((c: Company) => {
    setCompany(c);
    setQuery("");
    setSuggestions([]);
    setSuggestOpen(false);
    setSuggestIdx(-1);
    setCategory(null);      // its taxonomy is different — do not carry a stale facet
    setPage(1);
    setExpanded(null);
    setDocsLoading(true);
    setDocs(null);
    filingsService.getCompanyDocuments(c.symbol)
      .then(setDocs)
      .catch(() => setDocs(null))
      .finally(() => setDocsLoading(false));
  }, []);

  /** Reset back to ALL — the whole tape, whole taxonomy. */
  const clearCompany = useCallback(() => {
    setCompany(null);
    setDocs(null);
    setQuery("");
    setSuggestions([]);
    setSuggestOpen(false);
    setCategory(null);
    setPage(1);
    setExpanded(null);
  }, []);

  const onSearchKey = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!suggestions.length) {
      if (e.key === "Escape") setSuggestOpen(false);
      return;
    }
    if (e.key === "ArrowDown") { e.preventDefault(); setSuggestIdx((i) => (i + 1) % suggestions.length); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setSuggestIdx((i) => (i <= 0 ? suggestions.length : i) - 1); }
    else if (e.key === "Enter") { e.preventDefault(); selectCompany(suggestions[suggestIdx >= 0 ? suggestIdx : 0]); }
    else if (e.key === "Escape") { setSuggestOpen(false); setSuggestIdx(-1); }
  }, [suggestions, suggestIdx, selectCompany]);

  const loadInsight = useCallback((id: string) => {
    if (insights[id] !== undefined) return;
    setInsightLoading((m) => ({ ...m, [id]: true }));
    filingsService
      .getInsight(id)
      .then((ins) => setInsights((m) => ({ ...m, [id]: ins })))
      .catch(() => setInsights((m) => ({ ...m, [id]: null })))
      .finally(() => setInsightLoading((m) => ({ ...m, [id]: false })));
  }, [insights]);

  const toggleExpand = useCallback((id: string) => {
    setExpanded((cur) => {
      const next = cur === id ? null : id;
      if (next) loadInsight(id);
      return next;
    });
  }, [loadInsight]);

  /** SOURCES chip → jump to that ticker's row in the feed and open it. */
  const gotoRef = useCallback((ticker: string) => {
    const row = rows.find((r) => (r.ticker || "").toUpperCase() === ticker.toUpperCase());
    if (!row) return;
    setScreen("feed");
    setExpanded(row.id);
    loadInsight(row.id);
    setFlashed(row.id);
    window.setTimeout(() => setFlashed(null), 1600);
    rowRefs.current[row.id]?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [rows, loadInsight]);

  // ── ask the pinned copilot ──────────────────────────────────────────────
  const runAsk = useCallback((qArg?: string) => {
    const raw = (typeof qArg === "string" ? qArg : draft).trim();
    if (!raw || asking) return;
    // Scope the ask to the company selected in the top-level search — so the ask bar
    // AND the curated/thematic starters answer for that company (ticker mode) — unless
    // the question already names a $ticker. The visible question stays as typed.
    const q = company && !/\$[A-Za-z]/.test(raw) ? `${raw} for $${company.symbol}` : raw;
    setScreen("feed");
    setDraft(raw);
    setAnswer({ q: raw, text: "", confidence: undefined, streaming: true, refs: [] });
    let acc = "";
    chatService
      .streamSend(
        q,
        sessionRef.current,
        (ev) => {
          if (ev.type === "meta" && ev.session_id) sessionRef.current = ev.session_id;
          else if (ev.type === "route") setAnswer((a) => (a ? { ...a, confidence: ev.confidence } : a));
          else if (ev.type === "token" && ev.content) {
            acc += ev.content;
            setAnswer((a) => (a ? { ...a, text: acc } : a));
          } else if (ev.type === "widget") {
            // The stocks_insights widget carries the numbered source register the
            // answer cited. Refs are those symbols — not tickers scraped out of
            // the prose, which would attribute claims the copilot never made.
            const data = ev.data as { sources?: Array<{ symbol?: string | null }> } | null;
            const refs = Array.from(new Set(
              (data?.sources ?? [])
                .map((s) => (s?.symbol || "").trim().toUpperCase())
                .filter(Boolean),
            ));
            if (refs.length) setAnswer((a) => (a ? { ...a, refs } : a));
          } else if (ev.type === "done") {
            if (ev.content) acc = ev.content;
            setAnswer((a) => (a ? { ...a, text: acc || a.text, streaming: false } : a));
          } else if (ev.type === "error") {
            setAnswer((a) => (a ? { ...a, text: a.text || "Something went wrong answering that.", streaming: false } : a));
          }
        },
        { agent: PINNED_AGENT, page: "research" },
      )
      .finally(() => setAnswer((a) => (a ? { ...a, streaming: false } : a)));
  }, [draft, asking, company]);

  // ── derived facet chips (real event-category counts) ────────────────────
  const facetChips = useMemo(() => [
    { key: null as string | null, label: "All" },
    ...Object.entries(facets)
      .sort((a, b) => b[1] - a[1])
      .map(([k]) => ({ key: k, label: titleCase(k) })),
  ], [facets]);

  const navItems: Array<{ key: Screen; label: string; icon: typeof Bell; title: string }> = [
    { key: "feed", label: "Feed", icon: Sparkles, title: "Filings intelligence" },
    { key: "alerts", label: "Alerts", icon: Bell, title: "Alerts" },
  ];

  return (
    <div className="nv-frame research-screen" style={{ minHeight: "100vh", display: "flex" }}>
      {/* ══ DESKTOP ICON RAIL ══ */}
      <nav
        aria-label="Filings sections"
        className="hidden lg:flex"
        style={{
          width: 64, flex: "none", background: "var(--bg-1)",
          borderRight: "1px solid var(--c-line)", flexDirection: "column",
          alignItems: "center", padding: "14px 0", gap: 8, zIndex: 30,
        }}
      >
        <span className="nv-mark" style={{ marginBottom: 10 }}>न</span>
        {navItems.map((n) => (
          <button
            key={n.key}
            onClick={() => setScreen(n.key)}
            className={`rail-ico ${screen === n.key ? "on" : ""}`}
            title={n.title}
            aria-label={n.title}
            aria-current={screen === n.key ? "page" : undefined}
            data-testid={`rail-${n.key}`}
          >
            <n.icon size={19} />
          </button>
        ))}
        <button className="rail-ico" title="Announcements" aria-label="Announcements"
                onClick={() => { setScreen("feed"); setCategory(null); setPage(1); }}>
          <Megaphone size={19} />
        </button>
        <button className="rail-ico" title="Watchlist" aria-label="Watchlist" disabled
                style={{ opacity: 0.4, cursor: "not-allowed" }}>
          <Bookmark size={19} />
        </button>
        <Link to="/research/qa" className="rail-ico" title="QA validation exercise"
              aria-label="QA validation exercise" data-testid="rail-qa">
          <ClipboardCheck size={19} />
        </Link>
        <span style={{ flex: 1 }} />
        <button className="rail-ico" title="More" aria-label="More"><MoreVertical size={19} /></button>
      </nav>

      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
        {/* ══ HEADER ══ */}
        <header
          style={{
            position: "sticky", top: 0, zIndex: 20, display: "flex", alignItems: "center",
            gap: 12, padding: "12px 16px", background: "var(--bg-1)",
            borderBottom: "1px solid var(--c-line)", flex: "none",
          }}
        >
          <span className="nv-mark lg:hidden" style={{ flex: "none" }}>न</span>
          <span className="nv-serif" style={{ fontSize: 18, flex: "none" }}>
            <span className="hidden lg:inline">Nivesh</span>
            <span className="lg:hidden">Filings</span>
          </span>
          <div className="hidden sm:block" style={{ flex: 1, minWidth: 0, maxWidth: 560, margin: "0 auto", position: "relative" }}>
            {company ? (
              // Scoped: the box becomes a removable company chip. One click back to ALL.
              <div
                data-testid="company-scope"
                style={{
                  display: "flex", alignItems: "center", gap: 10, background: "var(--mint-soft)",
                  border: "1px solid var(--mint-line)", borderRadius: 999, padding: "7px 8px 7px 14px",
                }}
              >
                <span className="nv-mono" style={{ fontSize: 11, color: "var(--mint)", fontWeight: 500 }}>
                  {company.symbol}
                </span>
                <span style={{ flex: 1, minWidth: 0, fontSize: 13, color: "var(--c-ink)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {company.name}
                </span>
                <button
                  onClick={clearCompany}
                  aria-label="Clear company filter — show all filings"
                  title="Show all filings"
                  data-testid="clear-company"
                  className="rail-ico"
                  style={{ width: 26, height: 26, borderRadius: 999, flex: "none" }}
                >
                  <X size={14} />
                </button>
              </div>
            ) : (
              <div
                style={{
                  display: "flex", alignItems: "center", gap: 8,
                  background: "var(--bg-2)", border: "1px solid var(--c-line)", borderRadius: 999,
                  padding: "8px 14px", color: "var(--c-ink-3)",
                }}
              >
                <Search size={15} />
                <input
                  value={query}
                  onChange={(e) => { setQuery(e.target.value); setPage(1); setSuggestOpen(true); }}
                  onFocus={() => setSuggestOpen(true)}
                  onBlur={() => window.setTimeout(() => setSuggestOpen(false), 120)}
                  onKeyDown={onSearchKey}
                  placeholder="Search companies · TCS, HDFC AMC, JSW Steel…"
                  aria-label="Search companies"
                  aria-autocomplete="list"
                  aria-expanded={suggestOpen && suggestions.length > 0}
                  role="combobox"
                  aria-controls="company-suggestions"
                  data-testid="filings-search"
                  style={{
                    flex: 1, minWidth: 0, border: 0, background: "none",
                    fontSize: 13.5, color: "var(--c-ink)", outline: "none", fontFamily: "var(--sans)",
                  }}
                />
                {query && (
                  <button onClick={() => { setQuery(""); setPage(1); }} aria-label="Clear search"
                          className="rail-ico" style={{ width: 22, height: 22, borderRadius: 999, flex: "none" }}>
                    <X size={13} />
                  </button>
                )}
              </div>
            )}

            {!company && suggestOpen && suggestions.length > 0 && (
              <ul
                id="company-suggestions"
                role="listbox"
                data-testid="company-suggestions"
                className="nv-card"
                style={{
                  position: "absolute", top: "calc(100% + 6px)", left: 0, right: 0, zIndex: 40,
                  listStyle: "none", margin: 0, padding: 4, maxHeight: 320, overflowY: "auto",
                  boxShadow: "var(--shadow-pop)",
                }}
              >
                {suggestions.map((c, i) => (
                  <li key={c.symbol} role="option" aria-selected={i === suggestIdx}>
                    <button
                      // onMouseDown, not onClick: the input's onBlur closes the list
                      // first and a click would never land.
                      onMouseDown={(e) => { e.preventDefault(); selectCompany(c); }}
                      onMouseEnter={() => setSuggestIdx(i)}
                      data-testid="company-suggestion"
                      style={{
                        display: "flex", alignItems: "center", gap: 10, width: "100%",
                        padding: "9px 11px", borderRadius: 9, border: 0, cursor: "pointer",
                        textAlign: "left", fontFamily: "var(--sans)",
                        background: i === suggestIdx ? "var(--bg-3)" : "transparent",
                      }}
                    >
                      <span className="nv-mono" style={{ fontSize: 11, color: "var(--mint)", flex: "none", minWidth: 62 }}>
                        {c.symbol}
                      </span>
                      <span style={{ flex: 1, minWidth: 0, fontSize: 13, color: "var(--c-ink)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {c.name}
                      </span>
                      {c.sector && (
                        <span className="nv-mono" style={{ fontSize: 9.5, color: "var(--c-ink-4)", flex: "none" }}>
                          {c.sector}
                        </span>
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <span className="nv-pill nv-pill-indigo lg:hidden" style={{ marginLeft: "auto", flex: "none" }}>
            FILINGS
          </span>
        </header>

        {/* ══ BODY ══ */}
        <div style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
          {screen === "feed" ? (
            <FeedScreen
              {...{
                draft, setDraft, runAsk, asking, answer, gotoRef, signals,
                total, sort, setSort, setPage, facetChips, category, setCategory,
                setExpanded, feedError, feedLoading, rows, expanded, insights,
                insightLoading, tab, setTab, toggleExpand, page, pageCount, flashed, rowRefs,
                company, clearCompany, docs, docsLoading,
                held, todayOnly, setTodayOnly,
              }}
            />
          ) : (
            <AlertsScreen />
          )}
        </div>

        {/* ══ MOBILE BOTTOM TAB BAR ══ */}
        <nav
          aria-label="Filings sections"
          /* `flex lg:hidden` must own `display` — an inline display:flex here
             would out-specify lg:hidden and leave the bar on desktop. */
          className="flex lg:hidden nv-glass"
          style={{
            position: "sticky", bottom: 0, zIndex: 30,
            borderRadius: 0, borderLeft: 0, borderRight: 0, borderBottom: 0,
            paddingBottom: "env(safe-area-inset-bottom)", flex: "none",
          }}
        >
          {navItems.map((n) => (
            <button
              key={n.key}
              onClick={() => setScreen(n.key)}
              className={`mnav ${screen === n.key ? "on" : ""}`}
              aria-current={screen === n.key ? "page" : undefined}
              data-testid={`mnav-${n.key}`}
            >
              <n.icon size={18} />
              {n.label}
            </button>
          ))}
        </nav>
      </div>
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════════════════
   FEED
   ══════════════════════════════════════════════════════════════════════════ */

interface FeedProps {
  draft: string; setDraft: (v: string) => void;
  runAsk: (q?: string) => void; asking: boolean;
  answer: Answer | null; gotoRef: (t: string) => void;
  signals: Signal[]; total: number;
  held: { names: Set<string>; isins: Set<string>; symbols: Set<string> };
  todayOnly: boolean; setTodayOnly: (v: boolean) => void;
  sort: "material" | "latest"; setSort: (s: "material" | "latest") => void;
  setPage: React.Dispatch<React.SetStateAction<number>>;
  facetChips: Array<{ key: string | null; label: string }>;
  category: string | null; setCategory: (c: string | null) => void;
  setExpanded: React.Dispatch<React.SetStateAction<string | null>>;
  feedError: string | null; feedLoading: boolean;
  rows: FilingRow[]; expanded: string | null;
  insights: Record<string, Insight | null>;
  insightLoading: Record<string, boolean>;
  tab: Record<string, string>;
  setTab: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  toggleExpand: (id: string) => void;
  page: number; pageCount: number;
  flashed: string | null;
  rowRefs: React.MutableRefObject<Record<string, HTMLDivElement | null>>;
  company: Company | null;
  clearCompany: () => void;
  docs: CompanyDocs | null;
  docsLoading: boolean;
}

function FeedScreen(p: FeedProps) {
  const [starterCount, setStarterCount] = useState(STARTERS_PAGE);
  const [tab, setTab] = useState<"curated" | "history" | "favorites">("curated");
  const tq = useThematicQueries();
  const run = (query?: string) => {
    const t = (query ?? p.draft ?? "").trim();
    if (t) tq.addHistory(t);
    p.runAsk(query);
  };
  const starterLeft = THEMATIC_STARTERS.length - starterCount;

  // ── portfolio-impact match + detail drawer ──────────────────────────────
  const normName = (x?: string | null) =>
    (x || "").toLowerCase().replace(/\b(limited|ltd|corporation|corp|company|co|pvt|private)\b/g, "").replace(/[^a-z0-9]/g, "");
  const isHeld = (company?: string | null, ticker?: string | null): boolean => {
    if (ticker && p.held.symbols.has(ticker.toUpperCase())) return true;
    const n = normName(company);
    return !!n && p.held.names.has(n);
  };
  const [drawer, setDrawer] = useState<Signal | null>(null);
  const [drawerInsight, setDrawerInsight] = useState<Insight | null>(null);
  const [drawerLoading, setDrawerLoading] = useState(false);
  useEffect(() => {
    if (!drawer?.id) { setDrawerInsight(null); return; }
    let alive = true;
    setDrawerLoading(true);
    filingsService.getInsight(String(drawer.id))
      .then((ins) => { if (alive) setDrawerInsight(ins); })
      .catch(() => { if (alive) setDrawerInsight(null); })
      .finally(() => { if (alive) setDrawerLoading(false); });
    return () => { alive = false; };
  }, [drawer?.id]);

  return (
    <div style={{ maxWidth: 1080, margin: "0 auto", padding: "20px 16px 40px" }}>
      {/* ── ask bar ── */}
      <p className="nv-eyebrow" style={{ margin: "0 0 10px", color: "var(--mint)" }}>
        ✦ Ask across every filing — Nivesh has already read them
      </p>
      <div className="nv-glass" style={{ display: "flex", alignItems: "center", gap: 10, padding: "13px 15px", borderRadius: 16 }}>
        <Sparkles size={18} style={{ color: "var(--mint)", flex: "none" }} />
        <input
          value={p.draft}
          onChange={(e) => p.setDraft(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run()}
          placeholder="Ask a question across all filings…"
          aria-label="Ask a question across all filings"
          data-testid="ask-input"
          style={{ flex: 1, minWidth: 0, border: 0, background: "none", fontSize: 15, color: "var(--c-ink)", outline: "none", fontFamily: "var(--sans)" }}
        />
        <button
          onClick={() => run()}
          disabled={p.asking}
          className="nv-btn nv-btn-primary"
          data-testid="ask-submit"
          style={{ padding: "8px 14px", fontSize: 13, flex: "none" }}
        >
          {p.asking ? <Loader2 size={15} className="animate-spin" /> : "Ask →"}
        </button>
      </div>
      {/* thematic starters + history + favourites */}
      <div style={{ marginTop: 12 }} data-testid="thematic-starters">
        <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 10, borderBottom: "1px solid var(--line-2)" }}>
          {([["curated", "Curated themes"], ["history", `History${tq.history.length ? ` (${tq.history.length})` : ""}`], ["favorites", `Favorites${tq.favorites.length ? ` (${tq.favorites.length})` : ""}`]] as const).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              data-testid={`tab-${key}`}
              style={{ background: "none", border: 0, cursor: "pointer", padding: "6px 2px", fontSize: 12.5, fontWeight: 600, color: tab === key ? "var(--c-ink)" : "var(--c-ink-3)", borderBottom: tab === key ? "2px solid var(--mint)" : "2px solid transparent" }}
            >
              {label}
            </button>
          ))}
          {tab === "curated" && (
            <span style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: 4, fontSize: 11, color: "var(--c-ink-4)" }}>
              <Star size={12} style={{ color: "var(--mint)", fill: "var(--mint)" }} /> featured
            </span>
          )}
          {tab === "history" && tq.history.length > 0 && (
            <button onClick={() => tq.clearHistory()} style={{ marginLeft: "auto", background: "none", border: 0, cursor: "pointer", fontSize: 11.5, color: "var(--c-ink-4)" }}>Clear</button>
          )}
        </div>

        {tab === "curated" && (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 8 }}>
              {THEMATIC_STARTERS.slice(0, starterCount).map((item) => (
                <div key={item.q} className="ask-chip" data-testid="thematic-starter" style={{ display: "flex", alignItems: "flex-start", gap: 8, background: "transparent", border: "1px solid var(--line-2)", borderRadius: 12, padding: "9px 12px" }}>
                  {item.featured && <Star size={13} style={{ color: "var(--mint)", fill: "var(--mint)", flex: "none", marginTop: 2 }} />}
                  <button onClick={() => run(item.q)} style={{ flex: 1, minWidth: 0, textAlign: "left", background: "none", border: 0, cursor: "pointer", padding: 0 }}>
                    <span style={{ display: "block", fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.4, color: "var(--c-ink-4)", marginBottom: 2 }}>{item.category}</span>
                    <span style={{ display: "block", fontSize: 13, color: "var(--c-ink-2)", lineHeight: 1.35 }}>{item.q}</span>
                  </button>
                  <button onClick={() => tq.toggleFavorite(item.q)} title={tq.isFavorite(item.q) ? "Remove from favourites" : "Save to favourites"} aria-label="Toggle favourite" data-testid="fav-toggle" style={{ background: "none", border: 0, cursor: "pointer", flex: "none", padding: 2, marginTop: 1 }}>
                    <Bookmark size={14} style={{ color: tq.isFavorite(item.q) ? "var(--mint)" : "var(--c-ink-4)", fill: tq.isFavorite(item.q) ? "var(--mint)" : "none" }} />
                  </button>
                </div>
              ))}
            </div>
            {(starterLeft > 0 || starterCount > STARTERS_PAGE) && (
              <div style={{ marginTop: 10 }}>
                {starterLeft > 0 ? (
                  <button onClick={() => setStarterCount((c) => Math.min(c + STARTERS_PAGE, THEMATIC_STARTERS.length))} className="ask-chip" data-testid="starters-more" style={{ fontSize: 12.5, fontWeight: 600, color: "var(--c-ink-2)", background: "transparent", border: "1px solid var(--line-2)", borderRadius: 999, padding: "6px 14px", cursor: "pointer" }}>
                    Show {Math.min(STARTERS_PAGE, starterLeft)} more · {starterLeft} left
                  </button>
                ) : (
                  <button onClick={() => setStarterCount(STARTERS_PAGE)} className="ask-chip" style={{ fontSize: 12.5, fontWeight: 600, color: "var(--c-ink-3)", background: "transparent", border: "1px solid var(--line-2)", borderRadius: 999, padding: "6px 14px", cursor: "pointer" }}>
                    Show less
                  </button>
                )}
              </div>
            )}
          </>
        )}

        {tab === "history" && (
          tq.history.length === 0 ? (
            <p style={{ fontSize: 12.5, color: "var(--c-ink-4)", padding: "8px 2px" }}>No queries yet — run a theme and it will appear here.</p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {tq.history.map((qh) => (
                <div key={qh} className="ask-chip" data-testid="history-item" style={{ display: "flex", alignItems: "center", gap: 8, border: "1px solid var(--line-2)", borderRadius: 10, padding: "7px 10px" }}>
                  <button onClick={() => run(qh)} style={{ flex: 1, minWidth: 0, textAlign: "left", background: "none", border: 0, cursor: "pointer", fontSize: 13, color: "var(--c-ink-2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", padding: 0 }}>{qh}</button>
                  <button onClick={() => tq.toggleFavorite(qh)} aria-label="Toggle favourite" style={{ background: "none", border: 0, cursor: "pointer", flex: "none" }}>
                    <Bookmark size={14} style={{ color: tq.isFavorite(qh) ? "var(--mint)" : "var(--c-ink-4)", fill: tq.isFavorite(qh) ? "var(--mint)" : "none" }} />
                  </button>
                  <button onClick={() => tq.removeHistory(qh)} aria-label="Remove from history" style={{ background: "none", border: 0, cursor: "pointer", flex: "none", color: "var(--c-ink-4)" }}>
                    <X size={13} />
                  </button>
                </div>
              ))}
            </div>
          )
        )}

        {tab === "favorites" && (
          tq.favorites.length === 0 ? (
            <p style={{ fontSize: 12.5, color: "var(--c-ink-4)", padding: "8px 2px" }}>No favourites yet — tap the bookmark on any theme to save it.</p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {tq.favorites.map((qf) => (
                <div key={qf} className="ask-chip" data-testid="favorite-item" style={{ display: "flex", alignItems: "center", gap: 8, border: "1px solid var(--line-2)", borderRadius: 10, padding: "7px 10px" }}>
                  <button onClick={() => run(qf)} style={{ flex: 1, minWidth: 0, textAlign: "left", background: "none", border: 0, cursor: "pointer", fontSize: 13, color: "var(--c-ink-2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", padding: 0 }}>{qf}</button>
                  <button onClick={() => tq.toggleFavorite(qf)} aria-label="Remove favourite" style={{ background: "none", border: 0, cursor: "pointer", flex: "none" }}>
                    <Bookmark size={14} style={{ color: "var(--mint)", fill: "var(--mint)" }} />
                  </button>
                </div>
              ))}
            </div>
          )
        )}
      </div>

      {/* ── copilot answer ── */}
      {p.answer && (
        <div
          data-testid="copilot-answer"
          style={{
            display: "flex", gap: 12, marginTop: 18, padding: 18,
            background: "var(--bg-1)", border: "1px solid var(--mint-line)",
            borderRadius: 16, boxShadow: "var(--shadow-card)",
          }}
        >
          <span className="nv-mark" style={{ flex: "none", marginTop: 2 }}>न</span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <p className="nv-eyebrow" style={{ margin: "0 0 8px", color: "var(--mint)" }}>
              Copilot · grounded in filings
              {typeof p.answer.confidence === "number" ? ` · route ${p.answer.confidence.toFixed(2)}` : ""}
            </p>
            {p.answer.text ? (
              <div className="nv-prose" style={{ fontSize: 14.5 }}>
                <Markdown caret={p.answer.streaming}>{p.answer.text}</Markdown>
              </div>
            ) : (
              <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--c-ink-3)", fontSize: 13.5 }}>
                <Loader2 size={15} className="animate-spin" /> Reading the filings…
              </div>
            )}
            {p.answer.refs.length > 0 && (
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 14, flexWrap: "wrap" }}>
                <span className="nv-eyebrow" style={{ margin: 0 }}>Sources ›</span>
                {p.answer.refs.map((t) => (
                  <button key={t} className="refchip" data-testid="source-chip"
                          onClick={() => p.gotoRef(t)}>
                    {t}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── read for you today — Bloomberg-style, today-strict, click → drawer ──
          Hidden under a company scope: it ranks the WHOLE tape. */}
      {!p.company && (
        <>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "30px 0 12px", gap: 12, flexWrap: "wrap" }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
              <p className="nv-eyebrow" style={{ margin: 0 }}>{p.todayOnly ? "Read for you today" : "Read for you · latest"}</p>
              <span className="nv-mono" style={{ fontSize: 10, color: "var(--c-ink-4)", letterSpacing: ".08em" }}>RANKED BY MATERIALITY</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <button
                onClick={() => p.setTodayOnly(!p.todayOnly)}
                data-testid="today-toggle"
                style={{ background: "none", border: "1px solid var(--line-2)", borderRadius: 999, padding: "4px 11px", fontSize: 11, fontWeight: 600, color: "var(--c-ink-3)", cursor: "pointer" }}
              >
                {p.todayOnly ? "Show latest" : "Today only"}
              </button>
              <span className="nv-mono" style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 10, letterSpacing: ".1em", color: "var(--mint)" }}>
                <span className="nv-live-dot" style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--mint)" }} />
                NSE · BSE
              </span>
            </div>
          </div>

          {p.signals.length === 0 ? (
            <div data-testid="signals-empty" style={{ border: "1px dashed var(--c-line)", borderRadius: 14, padding: "22px 18px", textAlign: "center", background: "var(--bg-1)" }}>
              <p className="nv-serif" style={{ fontSize: 16, color: "var(--c-ink)", margin: "0 0 4px" }}>Markets quiet so far today</p>
              <p style={{ fontSize: 12.5, color: "var(--c-ink-4)", margin: 0 }}>
                New material disclosures appear here as they're filed.{" "}
                <button onClick={() => p.setTodayOnly(false)} style={{ background: "none", border: 0, color: "var(--mint)", cursor: "pointer", fontWeight: 600, padding: 0 }}>Show the latest instead →</button>
              </p>
            </div>
          ) : (
            <div
              style={{ display: "grid", gap: 12, gridAutoFlow: "column", gridAutoColumns: "82%", overflowX: "auto", paddingBottom: 4, scrollSnapType: "x mandatory" }}
              className="lg:!grid-flow-row lg:!grid-cols-3 lg:!auto-cols-auto lg:!overflow-visible"
            >
              {p.signals.map((s, i) => {
                const mine = isHeld(s.company, s.ticker);
                return (
                  <button
                    key={`${s.ticker}-${i}`}
                    onClick={() => setDrawer(s)}
                    data-testid="signal-card"
                    style={{
                      scrollSnapAlign: "start", textAlign: "left", cursor: "pointer",
                      background: "var(--bg-1)", border: `1px solid ${mine ? "var(--mint-line)" : "var(--c-line)"}`, borderRadius: 14,
                      padding: "16px 16px 14px", boxShadow: "var(--shadow-card)",
                      display: "flex", flexDirection: "column", minHeight: 178,
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                      <span className="nv-serif" style={{ fontSize: 20, color: "var(--c-ink-3)", lineHeight: 1 }}>{`0${s.rank ?? i + 1}`}</span>
                      <span className="nv-mono nv-num" style={{ fontSize: 11, color: "var(--c-ink)", fontWeight: 600 }}>{s.ticker || "—"}</span>
                      <span className={`nv-pill ${pill(s.sentiment)}`} style={{ marginLeft: "auto" }}>{titleCase(s.type) || "Filing"}</span>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 9, minHeight: 16 }}>
                      <span style={{ fontSize: 11.5, color: "var(--c-ink-4)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.company || ""}</span>
                      {mine && (
                        <span data-testid="portfolio-badge" style={{ marginLeft: "auto", flex: "none", display: "inline-flex", alignItems: "center", gap: 4, fontSize: 9.5, fontWeight: 700, letterSpacing: ".03em", color: "var(--mint)", background: "var(--mint-soft)", border: "1px solid var(--mint-line)", borderRadius: 999, padding: "2px 7px" }}>
                          <Bookmark size={10} style={{ fill: "var(--mint)" }} /> IN YOUR PORTFOLIO
                        </span>
                      )}
                    </div>
                    <div className="nv-serif" style={{ fontSize: 16, lineHeight: 1.3, color: "var(--c-ink)", marginBottom: 12, flex: 1 }}>
                      {s.one || "Material filing — open for the AI insight."}
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      {s.metric && (
                        <span className={`nv-mono ${sig(s.sentiment).cls}`} style={{ fontSize: 10, padding: "4px 9px", borderRadius: 999, border: "1px solid" }}>{s.metric}</span>
                      )}
                      <span className="nv-mono" style={{ fontSize: 10, color: "var(--c-ink-4)" }}>{fmtDate(s.date)}</span>
                      <span className="nv-mono" style={{ marginLeft: "auto", fontSize: 10, color: "var(--mint)", fontWeight: 600 }}>Open →</span>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </>
      )}

      {/* ── company scope: documents library ── */}
      {p.company && (
        <DocumentsPanel company={p.company} docs={p.docs} loading={p.docsLoading} onClear={p.clearCompany} />
      )}

      {/* ── all filings ── */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "30px 0 12px", flexWrap: "wrap", gap: 10 }}>
        <p className="nv-eyebrow" style={{ margin: 0 }}>
          {p.company ? `${p.company.symbol} filings` : "All filings"} · {p.total} results
        </p>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span className="nv-mono" style={{ fontSize: 10, letterSpacing: ".08em", color: "var(--c-ink-4)" }}>SORT</span>
          <button onClick={() => { p.setSort("material"); p.setPage(1); }} className={`pg ${p.sort === "material" ? "on" : ""}`} data-testid="sort-material" style={{ minWidth: "auto", padding: "0 12px", letterSpacing: ".06em" }}>MATERIAL</button>
          <button onClick={() => { p.setSort("latest"); p.setPage(1); }} className={`pg ${p.sort === "latest" ? "on" : ""}`} data-testid="sort-latest" style={{ minWidth: "auto", padding: "0 12px", letterSpacing: ".06em" }}>LATEST</button>
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, overflowX: "auto", paddingBottom: 4, marginBottom: 14 }}>
        {p.facetChips.map((f) => (
          <button
            key={f.label}
            onClick={() => { p.setCategory(f.key); p.setPage(1); p.setExpanded(null); }}
            className={`facet ${(p.category ?? null) === f.key ? "on" : ""}`}
            style={{ flex: "none" }}
          >
            {f.label}
          </button>
        ))}
      </div>

      {p.feedError && (
        <div className="nv-card" style={{ padding: 18, color: "var(--danger-hex)", fontSize: 13.5 }}>{p.feedError}</div>
      )}

      {p.feedLoading ? (
        <div style={{ display: "flex", alignItems: "center", gap: 10, color: "var(--c-ink-3)", padding: "24px 4px", fontSize: 13.5 }}>
          <Loader2 size={16} className="animate-spin" /> Loading filings…
        </div>
      ) : (
        <div style={{ borderTop: "1px solid var(--c-line)" }} data-testid="filings-list">
          {p.rows.map((r) => (
            <FilingRowItem
              key={r.id}
              row={r}
              isOpen={p.expanded === r.id}
              flashed={p.flashed === r.id}
              insight={p.insights[r.id]}
              loading={!!p.insightLoading[r.id]}
              activeTab={p.tab[r.id]}
              onTab={(t) => p.setTab((m) => ({ ...m, [r.id]: t }))}
              onToggle={() => p.toggleExpand(r.id)}
              rowRef={(el) => { p.rowRefs.current[r.id] = el; }}
            />
          ))}
          {!p.rows.length && !p.feedError && (
            <div style={{ padding: "24px 4px", color: "var(--c-ink-3)", fontSize: 13.5 }}>
              {p.company
                ? `No ${p.company.symbol} filings match this filter in the last ${FEED_DAYS} days.`
                : `No filings match this filter in the last ${FEED_DAYS} days.`}
            </div>
          )}
        </div>
      )}

      {/* ── pagination ── */}
      {p.pageCount > 1 && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 8, marginTop: 20 }}>
          <button onClick={() => p.setPage((x) => Math.max(1, x - 1))} disabled={p.page <= 1} className="pg" aria-label="Previous page"><ChevronLeft size={15} /></button>
          <span className="nv-mono" style={{ fontSize: 12, color: "var(--c-ink-3)" }}>{p.page} / {p.pageCount}</span>
          <button onClick={() => p.setPage((x) => Math.min(p.pageCount, x + 1))} disabled={p.page >= p.pageCount} className="pg" aria-label="Next page"><ChevronRight size={15} /></button>
        </div>
      )}

      {/* ── detail drawer (in-page slide-over) ── */}
      {drawer && (
        <>
          <div onClick={() => setDrawer(null)} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.42)", zIndex: 60 }} />
          <aside
            data-testid="signal-drawer"
            style={{
              position: "fixed", top: 0, right: 0, bottom: 0, width: "min(560px, 94vw)",
              background: "var(--bg-1)", borderLeft: "1px solid var(--c-line)", boxShadow: "var(--shadow-pop)",
              zIndex: 61, display: "flex", flexDirection: "column",
            }}
          >
            <div style={{ padding: "16px 18px", borderBottom: "1px solid var(--c-line)", display: "flex", alignItems: "flex-start", gap: 12 }}>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 5, flexWrap: "wrap" }}>
                  <span className="nv-mono nv-num" style={{ fontSize: 12, color: "var(--c-ink)", fontWeight: 600 }}>{drawer.ticker || "—"}</span>
                  <span className={`nv-pill ${pill(drawer.sentiment)}`}>{titleCase(drawer.type) || "Filing"}</span>
                  {isHeld(drawer.company, drawer.ticker) && (
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 9.5, fontWeight: 700, color: "var(--mint)", background: "var(--mint-soft)", border: "1px solid var(--mint-line)", borderRadius: 999, padding: "2px 7px" }}>
                      <Bookmark size={10} style={{ fill: "var(--mint)" }} /> IN YOUR PORTFOLIO
                    </span>
                  )}
                </div>
                <div className="nv-serif" style={{ fontSize: 18, color: "var(--c-ink)", lineHeight: 1.25 }}>{drawer.company || drawer.ticker}</div>
                <div className="nv-mono" style={{ fontSize: 10.5, color: "var(--c-ink-4)", marginTop: 3 }}>{fmtDate(drawer.date)}</div>
              </div>
              <button onClick={() => setDrawer(null)} aria-label="Close" className="rail-ico" style={{ width: 30, height: 30, borderRadius: 999, flex: "none" }}><X size={16} /></button>
            </div>

            <div style={{ padding: "16px 18px", overflowY: "auto", flex: 1 }}>
              {isHeld(drawer.company, drawer.ticker) && (
                <div style={{ background: "var(--mint-soft)", border: "1px solid var(--mint-line)", borderRadius: 10, padding: "10px 12px", marginBottom: 14, fontSize: 12.5, color: "var(--c-ink-2)" }}>
                  You hold <b>{drawer.ticker}</b> — this filing may affect your position.
                </div>
              )}
              {drawer.one && <p className="nv-serif" style={{ fontSize: 16, lineHeight: 1.4, color: "var(--c-ink)", margin: "0 0 12px" }}>{drawer.one}</p>}
              {drawer.metric && <span className={`nv-mono ${sig(drawer.sentiment).cls}`} style={{ fontSize: 11, padding: "5px 10px", borderRadius: 999, border: "1px solid" }}>{drawer.metric}</span>}

              <div style={{ marginTop: 18 }}>
                <p className="nv-eyebrow" style={{ margin: "0 0 8px" }}>AI insight</p>
                {drawerLoading ? (
                  <p style={{ fontSize: 12.5, color: "var(--c-ink-4)" }}><Loader2 size={13} className="animate-spin" style={{ display: "inline", marginRight: 6, verticalAlign: "middle" }} /> Reading the filing…</p>
                ) : drawerInsight ? (
                  <div style={{ display: "flex", flexDirection: "column", gap: 13 }}>
                    {(drawerInsight.sections || []).map((sec, si) => (
                      <div key={si}>
                        <p style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".04em", color: "var(--c-ink-3)", margin: "0 0 5px" }}>{sec.h}</p>
                        <ul style={{ margin: 0, paddingLeft: 16 }}>
                          {(sec.items || []).map((it, ii) => (
                            <li key={ii} style={{ fontSize: 13, color: "var(--c-ink-2)", lineHeight: 1.45, marginBottom: 3 }}>
                              {it}
                              {sec.cite_url && ii === 0 ? <> <a href={sec.cite_url} target="_blank" rel="noreferrer" style={{ color: "var(--mint)", fontSize: 11 }}>{sec.cite || "source"}</a></> : null}
                            </li>
                          ))}
                        </ul>
                      </div>
                    ))}
                    {(!drawerInsight.sections || drawerInsight.sections.length === 0) && drawerInsight.one && (
                      <p style={{ fontSize: 13, color: "var(--c-ink-2)", lineHeight: 1.45 }}>{drawerInsight.one}</p>
                    )}
                    {drawerInsight.disclaimer && <p style={{ fontSize: 10.5, color: "var(--c-ink-4)", marginTop: 4 }}>{drawerInsight.disclaimer}</p>}
                  </div>
                ) : (
                  <p style={{ fontSize: 12.5, color: "var(--c-ink-4)" }}>No AI insight generated for this filing yet.</p>
                )}
              </div>

              {drawerInsight?.sourceUrl && (
                <a href={drawerInsight.sourceUrl} target="_blank" rel="noreferrer" style={{ marginTop: 18, display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12.5, color: "var(--mint)", fontWeight: 600 }}>
                  Open source PDF <ExternalLink size={13} />
                </a>
              )}
            </div>
          </aside>
        </>
      )}
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════════════════
   COMPANY DOCUMENT LIBRARY — every supporting filing, downloadable
   ══════════════════════════════════════════════════════════════════════════ */

function fmtBytes(b?: number | null): string {
  if (!b || b <= 0) return "";
  const mb = b / (1024 * 1024);
  return mb >= 1 ? `${mb.toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`;
}

function DocumentsPanel({
  company, docs, loading, onClear,
}: {
  company: Company; docs: CompanyDocs | null; loading: boolean; onClear: () => void;
}) {
  const [openKey, setOpenKey] = useState<string | null>(null);
  // Default to the first group that actually has documents.
  const groups = docs?.groups ?? [];
  const active = openKey && groups.some((g) => g.key === openKey) ? openKey : groups[0]?.key;

  return (
    <div data-testid="documents-panel" style={{ marginTop: 24 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
        <p className="nv-eyebrow" style={{ margin: 0, color: "var(--mint)" }}>
          ◆ {company.symbol} · source documents
        </p>
        <button onClick={onClear} className="lk" data-testid="back-to-all"
                style={{ marginLeft: "auto", border: 0, background: "none", cursor: "pointer",
                         fontFamily: "var(--mono)", fontSize: 10.5, letterSpacing: ".08em",
                         textTransform: "uppercase", color: "var(--c-ink-3)" }}>
          ← All filings
        </button>
      </div>

      {loading ? (
        <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--c-ink-3)", fontSize: 13.5, padding: "8px 2px" }}>
          <Loader2 size={15} className="animate-spin" /> Loading {company.symbol}'s documents…
        </div>
      ) : !groups.length ? (
        <div className="nv-card" style={{ padding: 16, fontSize: 13.5, color: "var(--c-ink-3)" }} data-testid="no-documents">
          No source documents on file for {company.symbol} yet. Documents appear here once the
          exchange filing carries a downloadable attachment.
        </div>
      ) : (
        <>
          <div style={{ display: "flex", gap: 8, overflowX: "auto", paddingBottom: 4, marginBottom: 12 }}>
            {groups.map((g) => (
              <button key={g.key} onClick={() => setOpenKey(g.key)}
                      className={`facet ${active === g.key ? "on" : ""}`}
                      data-testid="doc-group-tab" style={{ flex: "none" }}>
                {g.label} · {g.documents.length}
              </button>
            ))}
          </div>

          <div className="nv-card" style={{ padding: "2px 16px" }}>
            {groups.filter((g) => g.key === active).flatMap((g) => g.documents).map((d, i) => (
              <div key={d.docId || `${d.url}-${i}`} data-testid="doc-row"
                   style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 0",
                            borderTop: i === 0 ? "none" : "1px solid var(--c-line)" }}>
                <FileText size={15} style={{ flex: "none", color: "var(--c-ink-4)" }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13.5, color: "var(--c-ink)" }}>{fmtDate(d.filedAt)}</div>
                  <div className="nv-mono" style={{ fontSize: 10, color: "var(--c-ink-4)", marginTop: 2 }}>
                    {[d.pages ? `${d.pages} pages` : "", fmtBytes(d.bytes)].filter(Boolean).join(" · ")}
                    {/* Say plainly whether the AI actually read this document. */}
                    {d.parsed ? " · read by Nivesh" : " · not parsed"}
                  </div>
                </div>
                {d.url ? (
                  <a href={d.url} target="_blank" rel="noreferrer" className="lk" data-testid="doc-download"
                     download
                     style={{ flex: "none", display: "inline-flex", alignItems: "center", gap: 6,
                              fontSize: 12.5, fontWeight: 500, color: "var(--mint)", textDecoration: "none" }}>
                    <Download size={13} /> Download
                  </a>
                ) : (
                  <span className="nv-mono" style={{ fontSize: 10, color: "var(--c-ink-4)" }}>no file</span>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════════════════
   ONE FILING ROW + its expanded insight panel
   ══════════════════════════════════════════════════════════════════════════ */

function FilingRowItem({
  row: r, isOpen, flashed, insight: ins, loading, activeTab, onTab, onToggle, rowRef,
}: {
  row: FilingRow; isOpen: boolean; flashed: boolean;
  insight: Insight | null | undefined; loading: boolean;
  activeTab?: string; onTab: (t: string) => void; onToggle: () => void;
  rowRef: (el: HTMLDivElement | null) => void;
}) {
  const s = sig(r.sentiment);
  // Tabs come from the response — a filing only shows tabs its document could
  // actually support (an annual report gets the AR set, others the generic one).
  const tabs = ins?.tabs ?? [];
  const active = activeTab && tabs.some((t) => t.label === activeTab)
    ? activeTab
    : tabs[0]?.label;
  const sections: InsightSection[] = (ins?.sections ?? []).filter((x) => x.tab === active);

  return (
    <div className={`frow ${flashed ? "flash" : ""}`} ref={rowRef} data-testid="filing-row">
      <div style={{ display: "flex", alignItems: "flex-start", gap: 12, padding: "14px 2px" }}>
        <span style={{ width: 8, height: 8, borderRadius: "50%", flex: "none", marginTop: 6 }} className={s.dot} />
        <FileText size={16} style={{ flex: "none", marginTop: 3, color: "var(--c-ink-4)" }} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 14, color: "var(--c-ink)", fontWeight: 500 }}>
            {r.name || r.ticker || "—"}{" "}
            <span className="nv-mono" style={{ fontSize: 11, color: "var(--c-ink-3)", fontWeight: 400 }}>{r.code || r.ticker}</span>
          </div>
          <div style={{ fontSize: 12.5, color: "var(--c-ink-2)", lineHeight: 1.45, marginTop: 2 }}>
            {r.one || r.docLabel || titleCase(r.category)}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
            {r.metric && (
              <span className={`nv-mono ${s.cls}`} style={{ fontSize: 10, padding: "4px 9px", borderRadius: 999, border: "1px solid" }}>{r.metric}</span>
            )}
            {r.impact && (
              <span className="nv-mono" style={{ fontSize: 10, color: "var(--c-ink-4)" }}>{titleCase(r.impact)} impact</span>
            )}
            <span className="nv-mono nv-num" style={{ marginLeft: "auto", fontSize: 11, color: "var(--c-ink-3)" }}>{fmtDate(r.date)}</span>
            <button onClick={onToggle} className="nv-btn softbtn" data-testid="toggle-insight"
                    aria-expanded={isOpen}
                    style={{ flex: "none", padding: "6px 12px", fontSize: 12, gap: 6 }}>
              <Sparkles size={13} />
              {isOpen ? "Hide" : "AI insights"}
            </button>
          </div>
        </div>
      </div>

      {isOpen && (
        <div style={{ padding: "2px 2px 20px 30px" }}>
          <div data-testid="insight-panel"
               style={{ background: "var(--bg-1)", border: "1px solid var(--c-line)", borderRadius: 14, padding: 18, boxShadow: "var(--shadow-card)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              <span className="nv-eyebrow" style={{ color: "var(--mint)" }}>✦ AI Insights</span>
              {r.name && <span className="nv-pill">{r.name}</span>}
              {(ins?.period || r.period) && <span className="nv-pill">{ins?.period || r.period}</span>}
              {(ins?.docLabel || r.docLabel) && <span className="nv-pill">{ins?.docLabel || r.docLabel}</span>}
            </div>

            {loading ? (
              <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--c-ink-3)", fontSize: 13, marginTop: 16 }}>
                <Loader2 size={15} className="animate-spin" /> Fetching the insight…
              </div>
            ) : !ins ? (
              <p className="nv-body" data-testid="no-insight" style={{ margin: "16px 0 0", fontSize: 13.5, color: "var(--c-ink-3)" }}>
                No AI insight has been generated for this filing yet. It enters the generator
                queue automatically; check back shortly.
              </p>
            ) : (
              <>
                {tabs.length > 0 && (
                  <div style={{ display: "flex", gap: 20, borderBottom: "1px solid var(--c-line)", margin: "14px 0 4px", overflowX: "auto" }}>
                    {tabs.map((t) => (
                      <button key={t.key} onClick={() => onTab(t.label)}
                              className={`tab ${active === t.label ? "on" : ""}`}
                              data-testid="insight-tab"
                              style={{ flex: "none" }}>
                        {t.label}
                      </button>
                    ))}
                  </div>
                )}

                <div style={{ marginTop: 16 }}>
                  {/* The one-liner is the spine of the panel and always shown. */}
                  {ins.one && (
                    <div className="nv-serif" style={{ fontSize: 18, lineHeight: 1.3, color: "var(--c-ink)", marginBottom: 12 }}>
                      {ins.one}
                    </div>
                  )}
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: sections.length ? 18 : 0 }}>
                    {ins.metric && <span className="nv-pill nv-pill-mint">{ins.metric}</span>}
                    {ins.sentiment && <span className="nv-pill">{titleCase(ins.sentiment)}</span>}
                    {typeof ins.confidence === "number" && <span className="nv-pill">Confidence {Math.round(ins.confidence)}</span>}
                  </div>

                  {sections.map((sec, i) => (
                    <div className="isec" key={`${sec.tab}-${i}`} data-testid="insight-section">
                      <h4>
                        {sec.h}
                        {sec.cite && (
                          sec.cite_url
                            ? <a className="cite" href={sec.cite_url} target="_blank" rel="noreferrer">{sec.cite}</a>
                            : <span className="cite">{sec.cite}</span>
                        )}
                      </h4>
                      <ul>{sec.items.map((it, j) => <li key={j}>{it}</li>)}</ul>
                    </div>
                  ))}

                  {!sections.length && (
                    <p className="nv-body" style={{ margin: 0, fontSize: 13.5, color: "var(--c-ink-3)" }}>
                      {tabs.length
                        ? "Nothing further in this section."
                        : "The generator produced a summary for this filing but no sectioned breakdown — the document did not support one."}
                    </p>
                  )}
                </div>
              </>
            )}

            <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 16, paddingTop: 14, borderTop: "1px solid var(--c-line)", flexWrap: "wrap" }}>
              {ins?.grounded && <span className="nv-pill nv-pill-mint">✦ Grounded · NSE/BSE filing</span>}
              <span className="nv-mono" style={{ fontSize: 10, color: "var(--c-ink-4)" }}>
                {ins?.disclaimer || "AI-generated summary · refer to the source document for complete detail."}
              </span>
              {(ins?.sourceUrl || r.url) && (
                <a href={(ins?.sourceUrl || r.url) as string} target="_blank" rel="noreferrer" className="lk"
                   style={{ marginLeft: "auto", fontSize: 12.5, color: "var(--mint)", textDecoration: "none", fontWeight: 500, display: "inline-flex", alignItems: "center", gap: 4 }}>
                  Open source PDF <ExternalLink size={13} />
                </a>
              )}
            </div>
          </div>
        </div>
      )}

    </div>
  );
}

/* ══════════════════════════════════════════════════════════════════════════
   ALERTS
   ══════════════════════════════════════════════════════════════════════════ */

function AlertsScreen() {
  const [prefs, setPrefs] = useState<Alerts | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    filingsService.getAlerts()
      .then(setPrefs)
      .catch(() => setError("Couldn't load your alert preferences."))
      .finally(() => setLoading(false));
  }, []);

  /** Optimistic toggle that REVERTS on a failed save — a switch that stays on
   *  after the write failed would be telling the user something untrue. */
  const save = useCallback((next: Alerts) => {
    const prev = prefs;
    setPrefs(next);
    setSaving(true);
    setError(null);
    filingsService.putAlerts({ types: next.types, channels: next.channels })
      .then(setPrefs)
      .catch(() => { setPrefs(prev); setError("Couldn't save that — please try again."); })
      .finally(() => setSaving(false));
  }, [prefs]);

  if (loading) {
    return (
      <div style={{ maxWidth: 720, margin: "0 auto", padding: "28px 16px", display: "flex", alignItems: "center", gap: 10, color: "var(--c-ink-3)", fontSize: 13.5 }}>
        <Loader2 size={16} className="animate-spin" /> Loading your alert preferences…
      </div>
    );
  }
  if (!prefs) {
    return (
      <div style={{ maxWidth: 720, margin: "0 auto", padding: "28px 16px" }}>
        <div className="nv-card" style={{ padding: 18, color: "var(--danger-hex)", fontSize: 13.5 }}>
          {error || "Couldn't load your alert preferences."}
        </div>
      </div>
    );
  }

  const delivery = prefs.delivery;

  return (
    <div style={{ maxWidth: 720, margin: "0 auto", padding: "24px 16px 40px" }} data-testid="alerts-screen">
      <p className="nv-eyebrow" style={{ margin: "0 0 6px", color: "var(--mint)" }}>◆ Alerts</p>
      <h1 className="nv-serif" style={{ fontSize: 26, margin: "0 0 6px", color: "var(--c-ink)" }}>
        Tell Nivesh what to watch
      </h1>
      <p className="nv-body" style={{ margin: "0 0 22px", color: "var(--c-ink-3)" }}>
        Choose the filings that matter to you and where you want them.
      </p>

      {/* Delivery status — stated plainly, because it is not switched on. */}
      {delivery && !delivery.active && (
        <div
          data-testid="delivery-notice"
          style={{
            display: "flex", gap: 10, padding: "13px 15px", marginBottom: 22,
            borderRadius: 12, background: "var(--amber-soft)", border: "1px solid var(--amber-line)",
          }}
        >
          <Bell size={16} style={{ color: "var(--amber)", flex: "none", marginTop: 1 }} />
          <p className="nv-body" style={{ margin: 0, fontSize: 13, color: "var(--c-ink-2)" }}>
            {delivery.note || "Preferences are saved, but scheduled delivery is not switched on yet."}
          </p>
        </div>
      )}

      {error && (
        <div className="nv-card" style={{ padding: 14, marginBottom: 18, color: "var(--danger-hex)", fontSize: 13 }}>{error}</div>
      )}

      {/* ── filing types ── */}
      <p className="nv-eyebrow" style={{ margin: "0 0 10px" }}>Filing types</p>
      <div className="nv-card" style={{ padding: "4px 16px", marginBottom: 26 }}>
        {prefs.catalog.map((c, i) => (
          <label
            key={c.key}
            style={{
              display: "flex", alignItems: "center", gap: 12, padding: "14px 0",
              borderTop: i === 0 ? "none" : "1px solid var(--c-line)", cursor: "pointer",
            }}
          >
            <span style={{ flex: 1, fontSize: 14, color: "var(--c-ink)" }}>{c.label}</span>
            <button
              type="button"
              role="switch"
              aria-checked={!!prefs.types[c.key]}
              aria-label={c.label}
              data-testid={`type-${c.key}`}
              disabled={saving}
              className={`sw ${prefs.types[c.key] ? "on" : ""}`}
              onClick={() => save({ ...prefs, types: { ...prefs.types, [c.key]: !prefs.types[c.key] } })}
            />
          </label>
        ))}
      </div>

      {/* ── channels ── */}
      <p className="nv-eyebrow" style={{ margin: "0 0 10px" }}>Where to send them</p>
      <div className="nv-card" style={{ padding: "4px 16px", marginBottom: 26 }}>
        {[
          { key: "email", label: "Email", hint: "To your account address." },
          { key: "whatsapp", label: "WhatsApp", hint: "No provider connected yet — this only records the preference." },
        ].map((ch, i) => (
          <label
            key={ch.key}
            style={{
              display: "flex", alignItems: "center", gap: 12, padding: "14px 0",
              borderTop: i === 0 ? "none" : "1px solid var(--c-line)", cursor: "pointer",
            }}
          >
            <span style={{ flex: 1, minWidth: 0 }}>
              <span style={{ display: "block", fontSize: 14, color: "var(--c-ink)" }}>{ch.label}</span>
              <span className="nv-body" style={{ display: "block", fontSize: 12, color: "var(--c-ink-4)" }}>{ch.hint}</span>
            </span>
            <button
              type="button"
              role="switch"
              aria-checked={!!prefs.channels[ch.key]}
              aria-label={ch.label}
              data-testid={`channel-${ch.key}`}
              disabled={saving}
              className={`sw ${prefs.channels[ch.key] ? "on" : ""}`}
              onClick={() => save({ ...prefs, channels: { ...prefs.channels, [ch.key]: !prefs.channels[ch.key] } })}
            />
          </label>
        ))}
      </div>

      {prefs.updatedAt && (
        <p className="nv-mono" style={{ fontSize: 10.5, color: "var(--c-ink-4)", margin: 0 }}>
          Saved {new Date(prefs.updatedAt).toLocaleString("en-IN")}
        </p>
      )}
    </div>
  );
}
