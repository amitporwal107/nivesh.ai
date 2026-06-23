/**
 * AdvisorDashboard — the "Advisor Command Center" (V5 re-skin of V2 MfdDashboard).
 *
 * Layout (top → bottom):
 *   1. Personalised greeting + action sentence + Add client
 *   2. Advisor Home insight grid (4 proactive cards)
 *   3. Today's Actions feed
 *   4. Smart summary strip (clickable issue tiles)
 *   5. Issue-filter chips + search
 *   6. Client table (action-first columns)
 *
 * Pure presentation: all data + side-effects come in via props.
 */
import { useMemo, useState } from "react";
import {
  Users, Plus, Search, AlertTriangle, TrendingUp, Scale, CheckCircle2,
  Bell, Zap, Calendar, Sparkles, Trash2,
} from "lucide-react";
import type { ClientProfileC } from "@/services/contracts/advisor.contract";
import { AdvisorHome } from "./AdvisorHome";
import { PriorityChip } from "./PriorityChip";
import {
  TONE, fmtRs, fmtDaysSince, greetingFor, healthTone, decorateProfile,
  type AdvisorProfile, type Issue, type Tone,
} from "./derive";

interface Props {
  profiles: ClientProfileC[];
  workspaceType?: string;
  advisorName?: string | null;
  activatingId?: string | null;
  onOpenClient: (profileId: string, opts?: { route?: string; name?: string }) => void;
  onAddClient: () => void;
  onDeleteClient: (p: AdvisorProfile) => void;
}

// ── Small presentational atoms ─────────────────────────────────────────
function ScoreBar({ value, tone, label }: { value: number | null; tone: Tone; label: string }) {
  const t = TONE[tone];
  if (value == null) {
    return (
      <div className="w-full">
        <div className="flex items-center justify-between text-[9px] uppercase tracking-wider font-semibold text-ink-4 mb-0.5">
          <span>{label}</span><span className="italic">Calculating…</span>
        </div>
        <div className="h-1.5 rounded-full bg-surface-2 overflow-hidden relative">
          <div className="absolute inset-0 bg-gradient-to-r from-transparent via-surface-3 to-transparent animate-pulse" />
        </div>
      </div>
    );
  }
  const v = Math.max(0, Math.min(100, Math.round(value)));
  return (
    <div className="w-full">
      <div className="flex items-center justify-between text-[9px] uppercase tracking-wider font-semibold text-ink-4 mb-0.5">
        <span>{label}</span><span className={`tabular-nums ${t.text}`}>{v}</span>
      </div>
      <div className="h-1.5 rounded-full bg-surface-2 overflow-hidden">
        <div className={`h-full rounded-full ${t.dot}`} style={{ width: `${v}%` }} />
      </div>
    </div>
  );
}

function IssueTag({ issue }: { issue: Issue }) {
  const t = TONE[issue.tone];
  return (
    <span data-testid={`issue-tag-${issue.key}`} className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold whitespace-nowrap ${t.bg} ${t.border} ${t.text}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${t.dot}`} /> {issue.label}
    </span>
  );
}

function SummaryTile({ label, count, tone, Icon, active, onClick, testId }: { label: string; count: number; tone: Tone; Icon: typeof AlertTriangle; active: boolean; onClick: () => void; testId: string }) {
  const t = TONE[tone];
  return (
    <button type="button" onClick={onClick} data-testid={testId}
      className={`text-left rounded-lg border p-3 transition-all hover:-translate-y-0.5 ${t.bg} ${t.border} ${active ? "ring-2 ring-accent" : ""}`}>
      <div className="flex items-center gap-2">
        <div className={`w-7 h-7 rounded-md flex items-center justify-center ${t.dot} text-white`}><Icon className="w-3.5 h-3.5" /></div>
        <div className="text-[10px] uppercase tracking-wider font-bold text-ink-3">{label}</div>
      </div>
      <div className={`mt-2 text-2xl font-bold tabular-nums ${t.text}`}>{count}</div>
    </button>
  );
}

function FilterChip({ label, count, tone, active, onClick, testId }: { label: string; count?: number; tone: Tone; active: boolean; onClick: () => void; testId: string }) {
  const t = TONE[tone];
  return (
    <button type="button" onClick={onClick} data-testid={testId}
      className={`inline-flex items-center gap-1.5 rounded-full h-7 px-3 text-[11px] font-semibold transition-colors ${active ? `${t.bg} ${t.border} ${t.text} border` : "bg-surface-1 border border-hairline text-ink-2 hover:bg-surface-2"}`}>
      {label}
      {count != null && <span className={`tabular-nums ${active ? "opacity-90" : "text-ink-4"}`}>· {count}</span>}
    </button>
  );
}

// ── Main ────────────────────────────────────────────────────────────────
export function AdvisorDashboard({ profiles, workspaceType, advisorName, activatingId, onOpenClient, onAddClient, onDeleteClient }: Props) {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [feedExpanded, setFeedExpanded] = useState(false);

  const decorated = useMemo<AdvisorProfile[]>(
    () => profiles.filter((p) => p.type !== "SELF").map(decorateProfile),
    [profiles],
  );

  const counts = useMemo(() => {
    const c = { total: decorated.length, actionNeeded: 0, overRisk: 0, underperforming: 0, rebalance: 0, stale: 0, healthy: 0, high: 0 };
    for (const p of decorated) {
      if (p.priority?.bucket === "high") c.high++;
      const key = p._issue!.key;
      if (key === "over-risk") c.overRisk++;
      if (key === "underperforming") c.underperforming++;
      if (key === "rebalance" || key === "exit-switch") c.rebalance++;
      if (key === "stale" || key === "unreviewed") c.stale++;
      if (key === "healthy") c.healthy++;
      if (p._action!.label !== "All good") c.actionNeeded++;
    }
    return c;
  }, [decorated]);

  const todaysFeed = useMemo(
    () => decorated
      .filter((p) => p._action!.label !== "All good" && p.type === "CLIENT")
      .sort((a, b) => (b.priority?.score || 0) - (a.priority?.score || 0)),
    [decorated],
  );

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return decorated.filter((p) => {
      if (q && !p.name.toLowerCase().includes(q)) return false;
      if (filter === "all") return true;
      if (filter === "needs-action") return p._action!.label !== "All good";
      if (filter === "over-risk") return p._issue!.key === "over-risk";
      if (filter === "underperforming") return p._issue!.key === "underperforming";
      if (filter === "rebalance") return p._issue!.key === "rebalance" || p._issue!.key === "exit-switch";
      if (filter === "stale") return p._issue!.key === "stale" || p._issue!.key === "unreviewed";
      if (filter === "healthy") return p._issue!.key === "healthy";
      return true;
    });
  }, [decorated, search, filter]);

  const totalAum = useMemo(() => decorated.reduce((acc, p) => acc + (p._aum || 0), 0), [decorated]);
  const clientCount = profiles.filter((p) => p.type === "CLIENT").length;
  const feedShown = feedExpanded ? todaysFeed : todaysFeed.slice(0, 3);

  const openAction = (p: AdvisorProfile) => {
    const label = p._action!.label;
    const route = ["Exit", "Switch", "Reduce", "Rebalance"].includes(label) ? "/plan"
      : ["Increase SIP", "Add more"].includes(label) ? "/goals" : "/dashboard";
    onOpenClient(p.profile_id, { route, name: p.name });
  };

  return (
    <div className="space-y-4" data-testid="advisor-dashboard">
      {/* 1. Header / greeting */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Users className="w-5 h-5 text-accent" />
            <h1 className="font-display text-2xl tracking-tightish text-ink" data-testid="advisor-greeting">{greetingFor(advisorName)}</h1>
            {workspaceType && <span className="text-[10px] rounded-full border border-hairline px-2 py-0.5 text-ink-3">{workspaceType}</span>}
          </div>
          {counts.actionNeeded > 0 ? (
            <div className="mt-1.5 flex items-center gap-2 flex-wrap" data-testid="advisor-header-action-sentence">
              <Zap className="w-4 h-4 text-neg" />
              <span className="text-sm font-semibold text-neg">
                {counts.actionNeeded} {counts.actionNeeded === 1 ? "client needs" : "clients need"} action today
              </span>
              {(counts.overRisk + counts.underperforming + counts.rebalance + counts.stale) > 0 && (
                <span className="text-xs text-ink-3">
                  {[
                    counts.overRisk && `${counts.overRisk} over-risk`,
                    counts.underperforming && `${counts.underperforming} underperforming`,
                    counts.rebalance && `${counts.rebalance} rebalance`,
                    counts.stale && `${counts.stale} review stale`,
                  ].filter(Boolean).join(" · ")}
                </span>
              )}
            </div>
          ) : (
            <div className="mt-1.5 inline-flex items-center gap-2 text-sm font-semibold text-pos" data-testid="advisor-header-action-sentence">
              <CheckCircle2 className="w-4 h-4" /> All clients on track today
            </div>
          )}
          <p className="text-xs text-ink-3 mt-0.5">
            Book: {fmtRs(totalAum)} · {clientCount} {clientCount === 1 ? "active client" : "active clients"}
          </p>
        </div>
        <button onClick={onAddClient} data-testid="advisor-add-client-btn"
          className="inline-flex items-center gap-1 px-3 py-2 rounded-md bg-accent text-accent-fg text-sm font-medium hover:opacity-90">
          <Plus className="w-4 h-4" /> Add client
        </button>
      </div>

      {/* 2. Advisor Home insight grid */}
      <AdvisorHome onOpenClient={(id) => onOpenClient(id)} />

      {/* 3. Today's Actions feed */}
      <div className="rounded-lg border border-hairline bg-surface-1 shadow-card p-4" data-testid="advisor-action-feed">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-md bg-accent/15 flex items-center justify-center"><Bell className="w-4 h-4 text-accent" /></div>
            <div>
              <div className="text-sm font-semibold text-ink">Today's actions</div>
              <div className="text-[11px] text-ink-3">{todaysFeed.length === 0 ? "Nothing urgent — enjoy the calm." : "Act on the highest-priority client first."}</div>
            </div>
          </div>
          {todaysFeed.length > 3 && (
            <button onClick={() => setFeedExpanded(!feedExpanded)} className="text-xs text-accent hover:opacity-80" data-testid="advisor-feed-toggle">
              {feedExpanded ? "Show top 3" : `Show all ${todaysFeed.length}`}
            </button>
          )}
        </div>
        {todaysFeed.length === 0 ? (
          <div className="text-center py-6 text-xs text-ink-3" data-testid="advisor-feed-empty">
            <CheckCircle2 className="w-6 h-6 mx-auto mb-1.5 text-pos" /> Every active client is on track. Great work.
          </div>
        ) : (
          <div className="space-y-2">
            {feedShown.map((p) => {
              const t = TONE[p._action!.tone];
              const ActionIcon = p._action!.Icon;
              const reason = p.priority?.reasons?.[0] || p._issue!.label;
              return (
                <div key={p.profile_id} data-testid={`feed-row-${p.profile_id}`}
                  className="flex items-center gap-3 p-3 rounded-md bg-surface-2/60 hover:bg-surface-2 transition-colors">
                  <PriorityChip priority={p.priority} />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold text-ink truncate">{p.name}</div>
                    <div className="text-[11px] text-ink-3 truncate">→ {reason}</div>
                  </div>
                  <button type="button" onClick={() => openAction(p)} disabled={activatingId === p.profile_id} data-testid={`feed-action-${p.profile_id}`}
                    className={`inline-flex items-center gap-1.5 rounded-md px-3 h-8 text-[11px] font-semibold transition-all disabled:opacity-60 flex-shrink-0 ${t.btn}`}>
                    <ActionIcon className="w-3.5 h-3.5" /> {p._action!.label}
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* 4. Smart summary strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="advisor-summary-strip">
        <SummaryTile testId="summary-over-risk" label="Risk issues" count={counts.overRisk} tone="neg" Icon={AlertTriangle} active={filter === "over-risk"} onClick={() => setFilter(filter === "over-risk" ? "all" : "over-risk")} />
        <SummaryTile testId="summary-underperforming" label="Underperformance" count={counts.underperforming} tone="neg" Icon={TrendingUp} active={filter === "underperforming"} onClick={() => setFilter(filter === "underperforming" ? "all" : "underperforming")} />
        <SummaryTile testId="summary-rebalance" label="Rebalance needed" count={counts.rebalance} tone="warm" Icon={Scale} active={filter === "rebalance"} onClick={() => setFilter(filter === "rebalance" ? "all" : "rebalance")} />
        <SummaryTile testId="summary-healthy" label="Healthy" count={counts.healthy} tone="pos" Icon={CheckCircle2} active={filter === "healthy"} onClick={() => setFilter(filter === "healthy" ? "all" : "healthy")} />
      </div>

      {/* 5. Filter bar + search */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative flex-1 max-w-sm">
          <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-ink-4" />
          <input placeholder="Search client by name…" value={search} onChange={(e) => setSearch(e.target.value)} data-testid="advisor-search"
            className="w-full pl-9 h-9 text-xs rounded-md bg-surface-1 border border-hairline text-ink placeholder:text-ink-4 focus:outline-none focus:ring-1 focus:ring-accent" />
        </div>
        <div className="flex items-center gap-1.5 flex-wrap" data-testid="advisor-filter-row">
          <FilterChip label="All" count={counts.total} tone="neutral" active={filter === "all"} onClick={() => setFilter("all")} testId="advisor-filter-all" />
          <FilterChip label="Needs action" count={counts.actionNeeded} tone="accent" active={filter === "needs-action"} onClick={() => setFilter("needs-action")} testId="advisor-filter-needs-action" />
          <FilterChip label="High risk" count={counts.overRisk} tone="neg" active={filter === "over-risk"} onClick={() => setFilter("over-risk")} testId="advisor-filter-over-risk" />
          <FilterChip label="Underperforming" count={counts.underperforming} tone="neg" active={filter === "underperforming"} onClick={() => setFilter("underperforming")} testId="advisor-filter-underperforming" />
          <FilterChip label="Rebalance" count={counts.rebalance} tone="warm" active={filter === "rebalance"} onClick={() => setFilter("rebalance")} testId="advisor-filter-rebalance" />
          <FilterChip label="Review stale" count={counts.stale} tone="warm" active={filter === "stale"} onClick={() => setFilter("stale")} testId="advisor-filter-stale" />
        </div>
      </div>

      {/* 6. Client table */}
      <div className="rounded-lg border border-hairline bg-surface-1 shadow-card overflow-hidden" data-testid="advisor-client-table">
        <div className="grid grid-cols-12 gap-2 px-4 py-2 bg-surface-2 text-[10px] uppercase tracking-wider font-semibold text-ink-4 border-b border-hairline">
          <div className="col-span-3">Client</div>
          <div className="col-span-1 text-right">AUM</div>
          <div className="col-span-2">Health</div>
          <div className="col-span-2">Top issue</div>
          <div className="col-span-1 text-right">Review</div>
          <div className="col-span-1 text-right">Priority</div>
          <div className="col-span-2 text-right">Action</div>
        </div>

        {filtered.length === 0 && (
          <div className="py-10 text-center text-xs text-ink-3" data-testid="advisor-empty-state">
            {search || filter !== "all" ? <>No clients match your filters.</> : (
              <>
                <Users className="w-8 h-8 mx-auto mb-2 opacity-40" />
                No clients yet — add your first client to begin.
                <div className="mt-3">
                  <button onClick={onAddClient} className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md bg-accent text-accent-fg text-xs font-medium hover:opacity-90">
                    <Plus className="w-3 h-3" /> Add first client
                  </button>
                </div>
              </>
            )}
          </div>
        )}

        <div className="divide-y divide-[color:var(--line)]">
          {filtered.map((p) => {
            const actionTone = TONE[p._action!.tone];
            const healthT = TONE[healthTone(p._health)];
            const ActionIcon = p._action!.Icon;
            return (
              <div key={p.profile_id} data-testid={`advisor-client-row-${p.profile_id}`}
                className="grid grid-cols-12 gap-2 px-4 py-3 items-center hover:bg-surface-2/60 transition-colors">
                {/* Client */}
                <button type="button" onClick={() => onOpenClient(p.profile_id, { name: p.name })} disabled={activatingId === p.profile_id}
                  className="col-span-3 min-w-0 text-left disabled:opacity-60" data-testid={`advisor-client-name-${p.profile_id}`}>
                  <div className="flex items-center gap-2">
                    <div className="w-8 h-8 rounded-full bg-accent/15 text-accent flex items-center justify-center text-[11px] font-bold flex-shrink-0" aria-hidden>
                      {p.name?.slice(0, 1).toUpperCase() || "?"}
                    </div>
                    <div className="min-w-0">
                      <div className="text-sm font-semibold text-ink truncate flex items-center gap-1.5">
                        {p.name}
                        {p.type === "SELF" && <span className="text-[8px] rounded border border-hairline px-1 text-ink-3">YOU</span>}
                      </div>
                      {p.ai_summary ? (
                        <div className="text-[10px] text-ink-3 truncate" title={p.ai_summary} data-testid={`ai-summary-${p.profile_id}`}>
                          <Sparkles className="w-2.5 h-2.5 inline -mt-0.5 mr-0.5 text-accent" />{p.ai_summary}
                        </div>
                      ) : (
                        <div className="text-[10px] text-ink-3 truncate">{(p.tags || []).join(" · ") || "—"}</div>
                      )}
                    </div>
                  </div>
                </button>

                {/* AUM */}
                <div className="col-span-1 text-right tabular-nums text-sm font-medium text-ink-2">{fmtRs(p._aum)}</div>

                {/* Health */}
                <div className="col-span-2 min-w-0">
                  {p._health == null ? (
                    <ScoreBar label="Health" value={null} tone="neutral" />
                  ) : (
                    <div data-testid={`health-score-${p.profile_id}`}>
                      <div className="flex items-baseline gap-1.5">
                        <span className={`text-lg font-bold tabular-nums ${healthT.text}`}>{p._health}</span>
                        <span className="text-[10px] text-ink-4">/100</span>
                        <span className={`w-2 h-2 rounded-full ${healthT.dot} ml-0.5`} />
                      </div>
                      <div className="text-[9px] uppercase tracking-wider text-ink-4">
                        Q {p.portfolio_score != null ? Math.round(p.portfolio_score) : "—"} · R {p.risk_score != null ? Math.round(p.risk_score) : "—"}
                      </div>
                    </div>
                  )}
                </div>

                {/* Top issue */}
                <div className="col-span-2"><IssueTag issue={p._issue!} /></div>

                {/* Review */}
                <div className="col-span-1 text-right text-[11px]">
                  {p.last_reviewed_at ? (
                    <div className="inline-flex items-center gap-1 text-ink-3"><Calendar className="w-3 h-3" /> {fmtDaysSince(p.last_reviewed_at)}</div>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-warm font-medium"><Sparkles className="w-3 h-3" /> First review</span>
                  )}
                </div>

                {/* Priority */}
                <div className="col-span-1 flex justify-end"><PriorityChip priority={p.priority} /></div>

                {/* Action */}
                <div className="col-span-2 flex items-center justify-end gap-1.5">
                  <button type="button" onClick={() => openAction(p)} disabled={activatingId === p.profile_id} data-testid={`advisor-action-btn-${p.profile_id}`}
                    className={`inline-flex items-center gap-1.5 rounded-md px-3 h-8 text-[11px] font-semibold transition-all disabled:opacity-60 ${actionTone.btn}`}>
                    <ActionIcon className="w-3.5 h-3.5" /> {p._action!.label}
                  </button>
                  {p.type === "CLIENT" && (
                    <button onClick={() => onDeleteClient(p)} className="p-1 rounded hover:bg-neg/10 text-ink-4 hover:text-neg" data-testid={`advisor-delete-${p.profile_id}`} aria-label="Delete">
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export default AdvisorDashboard;
