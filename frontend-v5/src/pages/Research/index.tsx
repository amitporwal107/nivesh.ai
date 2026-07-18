/**
 * Research — "Filings Intelligence" (Design B), mobile-first.
 *
 * A standalone, single-purpose Copilot surface over corporate filings. Built to
 * the Design B prototype (Nivesh Filings Intelligence) but wired to REAL data —
 * no hardcoded rows, no mock:
 *
 *   Ask bar          → the copilot PINNED to `stocks_insights`
 *                      (POST /api/chat/stream {"agent":"stocks_insights"} →
 *                       CopilotState.pinned_agent), so a question here is always
 *                       answered from filed exchange disclosures, never memory.
 *   Read for you     → GET /api/filings/signals   (today's top-3 material filings)
 *   All filings      → GET /api/filings/feed       (facets · MATERIAL/LATEST · paging)
 *   Tap-to-expand    → GET /api/filings/{id}/insights (the stage-7 generator's insight)
 *
 * Honesty (spec §4.2): a row renders whatever is really in the filing (company,
 * category, impact, time, subject). one-liner / headline metric appear ONLY when
 * the generator has produced them — otherwise the row shows no synthetic number.
 *
 * Mobile-first: single column that scales up; signals + facets scroll
 * horizontally on small screens. Desktop just gets more breathing room.
 *
 * The insight panel keeps the prototype's 4 tabs; only "Quick Summary" is backed
 * by the generator today, so the other three honestly say "not generated yet"
 * (the richer multi-section generator is a later increment).
 */
import { useState, useRef, useEffect, useCallback } from "react";
import {
  Search, Send, FileText, ExternalLink, Sparkles, Loader2,
  ChevronLeft, ChevronRight,
} from "lucide-react";
import { chatService } from "@/services";
import { Markdown } from "@/components/chat/Markdown";
import { filingsService } from "@/services/adapters/filings.adapter";
import type { FilingRow, Signal, Insight } from "@/services/adapters/filings.adapter";
import "./research.css";

/** The one agent this surface is allowed to reach (backend _PINNABLE_AGENTS). */
const PINNED_AGENT = "stocks_insights";
/** The classifier's queue floor (spec §4.1) — the feed window is honest at 30d. */
const FEED_DAYS = 30;
const PAGE_SIZE = 20;

const INSIGHT_TABS = ["Quick Summary", "Sentiment", "Business Outlook", "Potential Risks"] as const;
type InsightTab = (typeof INSIGHT_TABS)[number];

const ASK_CHIPS = [
  "Who flagged debt-fund outflows?",
  "Which IT names capped FY27 guidance?",
  "Biggest orders on the tape this week",
];

/** sentiment → accent (matches the prototype's sig-* classes). */
function sig(sentiment?: string | null): { cls: string; dot: string } {
  const s = (sentiment || "").toLowerCase();
  if (s === "positive") return { cls: "sig-good", dot: "dot-good" };
  if (s === "negative") return { cls: "sig-risk", dot: "dot-risk" };
  if (s === "neutral") return { cls: "sig-info", dot: "dot-info" };
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
}

export default function ResearchPage() {
  // ── feed state ──────────────────────────────────────────────────────────
  const [rows, setRows] = useState<FilingRow[]>([]);
  const [total, setTotal] = useState(0);
  const [facets, setFacets] = useState<Record<string, number>>({});
  const [category, setCategory] = useState<string | null>(null);
  const [sort, setSort] = useState<"material" | "latest">("material");
  const [page, setPage] = useState(1);
  const [feedLoading, setFeedLoading] = useState(true);
  const [feedError, setFeedError] = useState<string | null>(null);

  // ── signals ─────────────────────────────────────────────────────────────
  const [signals, setSignals] = useState<Signal[]>([]);

  // ── expanded insight ────────────────────────────────────────────────────
  const [expanded, setExpanded] = useState<string | null>(null);
  const [tab, setTab] = useState<Record<string, InsightTab>>({});
  const [insights, setInsights] = useState<Record<string, Insight | null>>({});
  const [insightLoading, setInsightLoading] = useState<Record<string, boolean>>({});

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
        sort,
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
      });
      setRows(data.rows);
      setTotal(data.total ?? data.rows.length);
      if (data.facets && Object.keys(data.facets).length) setFacets(data.facets);
    } catch (e) {
      setFeedError("Couldn't load filings right now.");
      setRows([]);
    } finally {
      setFeedLoading(false);
    }
  }, [category, sort, page]);

  useEffect(() => { loadFeed(); }, [loadFeed]);
  useEffect(() => {
    filingsService.getSignals(1).then(setSignals).catch(() => setSignals([]));
  }, []);

  const toggleExpand = useCallback((id: string) => {
    setExpanded((cur) => {
      const next = cur === id ? null : id;
      if (next && insights[id] === undefined) {
        setInsightLoading((m) => ({ ...m, [id]: true }));
        filingsService
          .getInsight(id)
          .then((ins) => setInsights((m) => ({ ...m, [id]: ins })))
          .catch(() => setInsights((m) => ({ ...m, [id]: null })))
          .finally(() => setInsightLoading((m) => ({ ...m, [id]: false })));
      }
      return next;
    });
  }, [insights]);

  // ── ask the pinned copilot ──────────────────────────────────────────────
  const runAsk = useCallback((qArg?: string) => {
    const q = (typeof qArg === "string" ? qArg : draft).trim();
    if (!q || asking) return;
    setDraft(q);
    setAnswer({ q, text: "", confidence: undefined, streaming: true });
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
  const facetChips = [
    { key: null as string | null, label: "All" },
    ...Object.entries(facets)
      .sort((a, b) => b[1] - a[1])
      .map(([k]) => ({ key: k, label: titleCase(k) })),
  ];

  return (
    <div className="nv-frame research-screen" style={{ minHeight: "100vh" }}>
      {/* ── top bar ── */}
      <header
        style={{
          position: "sticky", top: 0, zIndex: 20, display: "flex", alignItems: "center",
          gap: 12, padding: "12px 16px", background: "var(--bg-1)", borderBottom: "1px solid var(--line)",
        }}
      >
        <span className="nv-mark" style={{ flex: "none" }}>न</span>
        <span className="nv-serif" style={{ fontSize: 18, flex: "none" }}>Filings</span>
        <div
          style={{
            flex: 1, minWidth: 0, display: "flex", alignItems: "center", gap: 8,
            background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 999,
            padding: "8px 14px", color: "var(--ink-3)",
          }}
        >
          <Search size={15} />
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && runAsk()}
            placeholder="Ask across every filing…"
            aria-label="Ask across filings"
            style={{
              flex: 1, minWidth: 0, border: 0, background: "none",
              fontSize: 13.5, color: "var(--ink)", outline: "none",
            }}
          />
        </div>
      </header>

      <div style={{ maxWidth: 760, margin: "0 auto", padding: "20px 16px 96px" }}>
        {/* ── ask bar ── */}
        <p className="nv-eyebrow" style={{ margin: "0 0 10px", color: "var(--mint)" }}>
          ✦ Ask across every filing — Nivesh has already read them
        </p>
        <div className="nv-glass" style={{ display: "flex", alignItems: "center", gap: 10, padding: "13px 15px", borderRadius: 16 }}>
          <Sparkles size={18} style={{ color: "var(--mint)", flex: "none" }} />
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && runAsk()}
            placeholder="Ask a question across all filings…"
            aria-label="Ask a question across all filings"
            style={{ flex: 1, minWidth: 0, border: 0, background: "none", fontSize: 15, color: "var(--ink)", outline: "none" }}
          />
          <button
            onClick={() => runAsk()}
            disabled={asking}
            className="nv-btn nv-btn-primary"
            style={{ padding: "8px 14px", fontSize: 13, flex: "none" }}
          >
            {asking ? <Loader2 size={15} className="animate-spin" /> : "Ask →"}
          </button>
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
          {ASK_CHIPS.map((c) => (
            <button
              key={c}
              onClick={() => runAsk(c)}
              className="ask-chip"
              style={{
                fontSize: 12.5, color: "var(--ink-3)", background: "transparent",
                border: "1px solid var(--line-2)", borderRadius: 999, padding: "6px 12px", cursor: "pointer",
              }}
            >
              {c}
            </button>
          ))}
        </div>

        {/* ── copilot answer ── */}
        {answer && (
          <div
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
                {typeof answer.confidence === "number" ? ` · route ${answer.confidence.toFixed(2)}` : ""}
              </p>
              {answer.text ? (
                <div className="nv-prose" style={{ fontSize: 14.5 }}>
                  <Markdown caret={answer.streaming}>{answer.text}</Markdown>
                </div>
              ) : (
                <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--ink-3)", fontSize: 13.5 }}>
                  <Loader2 size={15} className="animate-spin" /> Reading the filings…
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── read for you today (top-3 signals) ── */}
        {signals.length > 0 && (
          <>
            <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", margin: "30px 0 12px" }}>
              <p className="nv-eyebrow" style={{ margin: 0 }}>Read for you today · ranked by materiality</p>
              <span className="nv-mono" style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 10, letterSpacing: ".1em", color: "var(--mint)" }}>
                <span style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--mint)", animation: "nvpulse 2s infinite" }} />
                NSE · BSE
              </span>
            </div>
            <div style={{ display: "flex", gap: 12, overflowX: "auto", paddingBottom: 4, scrollSnapType: "x mandatory", WebkitOverflowScrolling: "touch" }}>
              {signals.map((s, i) => (
                <div
                  key={`${s.ticker}-${i}`}
                  style={{
                    flex: "0 0 82%", maxWidth: 300, scrollSnapAlign: "start",
                    background: "var(--bg-1)", border: "1px solid var(--line)", borderRadius: 14,
                    padding: "16px 16px 14px", boxShadow: "var(--shadow-card)",
                    display: "flex", flexDirection: "column", minHeight: 160,
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                    <span className="nv-serif" style={{ fontSize: 20, color: "var(--ink-3)", lineHeight: 1 }}>{`0${s.rank ?? i + 1}`}</span>
                    <span className="nv-mono nv-num" style={{ fontSize: 11, color: "var(--ink)", fontWeight: 500 }}>{s.ticker || "—"}</span>
                    <span className={`nv-pill ${pill(s.sentiment)}`} style={{ marginLeft: "auto" }}>{titleCase(s.type) || "Filing"}</span>
                  </div>
                  <div className="nv-serif" style={{ fontSize: 16, lineHeight: 1.28, color: "var(--ink)", marginBottom: 12, flex: 1 }}>
                    {s.one || "Material filing — open for the AI insight."}
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    {s.metric && (
                      <span className={`nv-mono ${sig(s.sentiment).cls}`} style={{ fontSize: 10, padding: "4px 9px", borderRadius: 999, border: "1px solid" }}>{s.metric}</span>
                    )}
                    <span className="nv-mono" style={{ marginLeft: "auto", fontSize: 10, color: "var(--ink-4)" }}>{fmtDate(s.date)}</span>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}

        {/* ── all filings ── */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "30px 0 12px", flexWrap: "wrap", gap: 10 }}>
          <p className="nv-eyebrow" style={{ margin: 0 }}>All filings · {total} results</p>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className="nv-mono" style={{ fontSize: 10, letterSpacing: ".08em", color: "var(--ink-4)" }}>SORT</span>
            <button onClick={() => { setSort("material"); setPage(1); }} className={`pg ${sort === "material" ? "on" : ""}`} style={{ minWidth: "auto", padding: "0 12px", letterSpacing: ".06em" }}>MATERIAL</button>
            <button onClick={() => { setSort("latest"); setPage(1); }} className={`pg ${sort === "latest" ? "on" : ""}`} style={{ minWidth: "auto", padding: "0 12px", letterSpacing: ".06em" }}>LATEST</button>
          </div>
        </div>

        <div style={{ display: "flex", gap: 8, overflowX: "auto", paddingBottom: 4, marginBottom: 14, WebkitOverflowScrolling: "touch" }}>
          {facetChips.map((f) => (
            <button
              key={f.label}
              onClick={() => { setCategory(f.key); setPage(1); setExpanded(null); }}
              className={`facet ${(category ?? null) === f.key ? "on" : ""}`}
              style={{ flex: "none" }}
            >
              {f.label}
            </button>
          ))}
        </div>

        {feedError && (
          <div className="nv-card" style={{ padding: 18, color: "var(--danger)", fontSize: 13.5 }}>{feedError}</div>
        )}

        {feedLoading ? (
          <div style={{ display: "flex", alignItems: "center", gap: 10, color: "var(--ink-3)", padding: "24px 4px", fontSize: 13.5 }}>
            <Loader2 size={16} className="animate-spin" /> Loading filings…
          </div>
        ) : (
          <div style={{ borderTop: "1px solid var(--line)" }}>
            {rows.map((r) => {
              const id = r.id;
              const isOpen = expanded === id;
              const s = sig(r.sentiment);
              const ins = insights[id];
              const active = tab[id] || "Quick Summary";
              return (
                <div key={id} className="frow">
                  <div style={{ display: "flex", alignItems: "flex-start", gap: 12, padding: "14px 2px" }}>
                    <span style={{ width: 8, height: 8, borderRadius: "50%", flex: "none", marginTop: 6 }} className={s.dot} />
                    <FileText size={16} style={{ flex: "none", marginTop: 3, color: "var(--ink-4)" }} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 14, color: "var(--ink)", fontWeight: 500 }}>
                        {r.name || r.ticker || "—"}{" "}
                        <span className="nv-mono" style={{ fontSize: 11, color: "var(--ink-3)", fontWeight: 400 }}>{r.code || r.ticker}</span>
                      </div>
                      <div style={{ fontSize: 12.5, color: "var(--ink-2)", lineHeight: 1.45, marginTop: 2 }}>
                        {r.one || r.docLabel || titleCase(r.category)}
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
                        {r.metric && (
                          <span className={`nv-mono ${s.cls}`} style={{ fontSize: 10, padding: "4px 9px", borderRadius: 999, border: "1px solid" }}>{r.metric}</span>
                        )}
                        {r.impact && (
                          <span className="nv-mono" style={{ fontSize: 10, color: "var(--ink-4)" }}>{titleCase(r.impact)} impact</span>
                        )}
                        <span className="nv-mono nv-num" style={{ marginLeft: "auto", fontSize: 11, color: "var(--ink-3)" }}>{fmtDate(r.date)}</span>
                        <button onClick={() => toggleExpand(id)} className="nv-btn softbtn" style={{ flex: "none", padding: "6px 12px", fontSize: 12, gap: 6 }}>
                          <Sparkles size={13} />
                          {isOpen ? "Hide" : "AI insights"}
                        </button>
                      </div>
                    </div>
                  </div>

                  {isOpen && (
                    <div style={{ padding: "2px 2px 20px 30px" }}>
                      <div style={{ background: "var(--bg-1)", border: "1px solid var(--line)", borderRadius: 14, padding: "18px 18px", boxShadow: "var(--shadow-card)" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                          <span className="nv-eyebrow" style={{ color: "var(--mint)" }}>✦ AI Insights</span>
                          {r.name && <span className="nv-pill">{r.name}</span>}
                          {(ins?.period || r.period) && <span className="nv-pill">{ins?.period || r.period}</span>}
                          {r.docLabel && <span className="nv-pill">{r.docLabel}</span>}
                        </div>

                        <div style={{ display: "flex", gap: 20, borderBottom: "1px solid var(--line)", margin: "14px 0 4px", overflowX: "auto" }}>
                          {INSIGHT_TABS.map((t) => (
                            <button key={t} onClick={() => setTab((m) => ({ ...m, [id]: t }))} className={`tab ${active === t ? "on" : ""}`} style={{ flex: "none" }}>{t}</button>
                          ))}
                        </div>

                        <div style={{ marginTop: 16 }}>
                          {insightLoading[id] ? (
                            <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--ink-3)", fontSize: 13 }}>
                              <Loader2 size={15} className="animate-spin" /> Fetching the insight…
                            </div>
                          ) : active === "Quick Summary" ? (
                            ins ? (
                              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                                <div className="nv-serif" style={{ fontSize: 18, lineHeight: 1.3, color: "var(--ink)" }}>{ins.one}</div>
                                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                                  {ins.metric && <span className="nv-pill nv-pill-mint">{ins.metric}</span>}
                                  {ins.sentiment && <span className="nv-pill">{titleCase(ins.sentiment)}</span>}
                                  {typeof ins.confidence === "number" && <span className="nv-pill">Confidence {Math.round(ins.confidence)}</span>}
                                </div>
                              </div>
                            ) : (
                              <p className="nv-body" style={{ margin: 0, fontSize: 13.5, color: "var(--ink-3)" }}>
                                No AI insight has been generated for this filing yet. It enters the generator queue automatically; check back shortly.
                              </p>
                            )
                          ) : (
                            <p className="nv-body" style={{ margin: 0, fontSize: 13.5, color: "var(--ink-3)" }}>
                              <span style={{ color: "var(--ink-2)" }}>{active}</span> is not generated yet. Today the copilot produces the grounded summary and headline metric (see Quick Summary); the deeper {active.toLowerCase()} breakdown is a later increment.
                            </p>
                          )}
                        </div>

                        <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 16, paddingTop: 14, borderTop: "1px solid var(--line)", flexWrap: "wrap" }}>
                          {ins?.grounded && <span className="nv-pill nv-pill-mint">✦ Grounded · NSE/BSE filing</span>}
                          <span className="nv-mono" style={{ fontSize: 10, color: "var(--ink-4)" }}>
                            {ins?.disclaimer || "AI-generated summary · refer to the source document for complete detail."}
                          </span>
                          {r.url && (
                            <a href={r.url} target="_blank" rel="noreferrer" className="lk" style={{ marginLeft: "auto", fontSize: 12.5, color: "var(--mint)", textDecoration: "none", fontWeight: 500, display: "inline-flex", alignItems: "center", gap: 4 }}>
                              Open source PDF <ExternalLink size={13} />
                            </a>
                          )}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
            {!rows.length && !feedError && (
              <div style={{ padding: "24px 4px", color: "var(--ink-3)", fontSize: 13.5 }}>No filings match this filter in the last {FEED_DAYS} days.</div>
            )}
          </div>
        )}

        {/* ── pagination ── */}
        {pageCount > 1 && (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 8, marginTop: 20 }}>
            <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1} className="pg"><ChevronLeft size={15} /></button>
            <span className="nv-mono" style={{ fontSize: 12, color: "var(--ink-3)" }}>{page} / {pageCount}</span>
            <button onClick={() => setPage((p) => Math.min(pageCount, p + 1))} disabled={page >= pageCount} className="pg"><ChevronRight size={15} /></button>
          </div>
        )}
      </div>
    </div>
  );
}
