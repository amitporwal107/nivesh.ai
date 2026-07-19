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
  ChevronLeft, ChevronRight, MoreVertical, Megaphone,
} from "lucide-react";
import { chatService } from "@/services";
import { Markdown } from "@/components/chat/Markdown";
import { filingsService } from "@/services/adapters/filings.adapter";
import type {
  FilingRow, Signal, Insight, InsightSection, Alerts,
} from "@/services/adapters/filings.adapter";
import "./research.css";

/** The one agent this surface is allowed to reach (backend _PINNABLE_AGENTS). */
const PINNED_AGENT = "stocks_insights";
/** The classifier's queue floor (spec §4.1) — the feed window is honest at 30d. */
const FEED_DAYS = 30;
const PAGE_SIZE = 20;

const ASK_CHIPS = [
  "Who flagged debt-fund outflows?",
  "Which IT names capped FY27 guidance?",
  "Biggest orders on the tape this week",
];

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

  // ── signals ─────────────────────────────────────────────────────────────
  const [signals, setSignals] = useState<Signal[]>([]);

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
        q: query.trim() || undefined,
        sort,
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
      });
      setRows(data.rows);
      setTotal(data.total ?? data.rows.length);
      if (data.facets && Object.keys(data.facets).length) setFacets(data.facets);
    } catch {
      setFeedError("Couldn't load filings right now.");
      setRows([]);
    } finally {
      setFeedLoading(false);
    }
  }, [category, sort, page, query]);

  useEffect(() => { loadFeed(); }, [loadFeed]);
  useEffect(() => {
    filingsService.getSignals(1).then(setSignals).catch(() => setSignals([]));
  }, []);

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
    const q = (typeof qArg === "string" ? qArg : draft).trim();
    if (!q || asking) return;
    setScreen("feed");
    setDraft(q);
    setAnswer({ q, text: "", confidence: undefined, streaming: true, refs: [] });
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
  }, [draft, asking]);

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
          <div
            className="hidden sm:flex"
            style={{
              flex: 1, minWidth: 0, maxWidth: 560, margin: "0 auto", alignItems: "center", gap: 8,
              background: "var(--bg-2)", border: "1px solid var(--c-line)", borderRadius: 999,
              padding: "8px 14px", color: "var(--c-ink-3)",
            }}
          >
            <Search size={15} />
            <input
              value={query}
              onChange={(e) => { setQuery(e.target.value); setPage(1); }}
              placeholder="Search companies · TCS, HDFC AMC, JSW Steel…"
              aria-label="Search companies"
              data-testid="filings-search"
              style={{
                flex: 1, minWidth: 0, border: 0, background: "none",
                fontSize: 13.5, color: "var(--c-ink)", outline: "none", fontFamily: "var(--sans)",
              }}
            />
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
}

function FeedScreen(p: FeedProps) {
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
          onKeyDown={(e) => e.key === "Enter" && p.runAsk()}
          placeholder="Ask a question across all filings…"
          aria-label="Ask a question across all filings"
          data-testid="ask-input"
          style={{ flex: 1, minWidth: 0, border: 0, background: "none", fontSize: 15, color: "var(--c-ink)", outline: "none", fontFamily: "var(--sans)" }}
        />
        <button
          onClick={() => p.runAsk()}
          disabled={p.asking}
          className="nv-btn nv-btn-primary"
          data-testid="ask-submit"
          style={{ padding: "8px 14px", fontSize: 13, flex: "none" }}
        >
          {p.asking ? <Loader2 size={15} className="animate-spin" /> : "Ask →"}
        </button>
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
        {ASK_CHIPS.map((c) => (
          <button
            key={c}
            onClick={() => p.runAsk(c)}
            className="ask-chip"
            style={{
              fontSize: 12.5, color: "var(--c-ink-3)", background: "transparent",
              border: "1px solid var(--line-2)", borderRadius: 999, padding: "6px 12px", cursor: "pointer",
            }}
          >
            {c}
          </button>
        ))}
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

      {/* ── read for you today (top-3 signals) ── */}
      {p.signals.length > 0 && (
        <>
          <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", margin: "30px 0 12px" }}>
            <p className="nv-eyebrow" style={{ margin: 0 }}>Read for you today · ranked by materiality</p>
            <span className="nv-mono" style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 10, letterSpacing: ".1em", color: "var(--mint)" }}>
              <span className="nv-live-dot" style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--mint)" }} />
              NSE · BSE
            </span>
          </div>
          <div
            style={{
              display: "grid", gap: 12, gridAutoFlow: "column", gridAutoColumns: "82%",
              overflowX: "auto", paddingBottom: 4, scrollSnapType: "x mandatory",
            }}
            className="lg:!grid-flow-row lg:!grid-cols-3 lg:!auto-cols-auto lg:!overflow-visible"
          >
            {p.signals.map((s, i) => (
              <div
                key={`${s.ticker}-${i}`}
                style={{
                  scrollSnapAlign: "start",
                  background: "var(--bg-1)", border: "1px solid var(--c-line)", borderRadius: 14,
                  padding: "16px 16px 14px", boxShadow: "var(--shadow-card)",
                  display: "flex", flexDirection: "column", minHeight: 160,
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                  <span className="nv-serif" style={{ fontSize: 20, color: "var(--c-ink-3)", lineHeight: 1 }}>{`0${s.rank ?? i + 1}`}</span>
                  <span className="nv-mono nv-num" style={{ fontSize: 11, color: "var(--c-ink)", fontWeight: 500 }}>{s.ticker || "—"}</span>
                  <span className={`nv-pill ${pill(s.sentiment)}`} style={{ marginLeft: "auto" }}>{titleCase(s.type) || "Filing"}</span>
                </div>
                <div className="nv-serif" style={{ fontSize: 16, lineHeight: 1.28, color: "var(--c-ink)", marginBottom: 12, flex: 1 }}>
                  {s.one || "Material filing — open for the AI insight."}
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  {s.metric && (
                    <span className={`nv-mono ${sig(s.sentiment).cls}`} style={{ fontSize: 10, padding: "4px 9px", borderRadius: 999, border: "1px solid" }}>{s.metric}</span>
                  )}
                  <span className="nv-mono" style={{ marginLeft: "auto", fontSize: 10, color: "var(--c-ink-4)" }}>{fmtDate(s.date)}</span>
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {/* ── all filings ── */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "30px 0 12px", flexWrap: "wrap", gap: 10 }}>
        <p className="nv-eyebrow" style={{ margin: 0 }}>All filings · {p.total} results</p>
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
              No filings match this filter in the last {FEED_DAYS} days.
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
