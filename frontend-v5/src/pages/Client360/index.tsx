/**
 * Client 360 — advisor-facing per-client overview.
 *
 * A v5-native adaptation of the V2 "Client 360" (ClientSnapshot) screen, built
 * on the data the v5 advisor book already returns (health/quality/risk scores,
 * AI summary, top issue, priority reasons, AUM) plus the per-client
 * needs-attention feed. Master-detail: pick a client on the left, see their 360
 * on the right, then "Open full portfolio" to impersonate them (which swaps the
 * whole app — and the copilot — into that client's personal view).
 *
 * NOTE: the V2 tax / notes / portfolio-trend strips are intentionally omitted
 * here — they depend on per-profile endpoints (/tax-summary, /notes,
 * /portfolio-trend) that v5's adapter does not expose yet. Those are a follow-up.
 */
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Contact, ArrowRight, ClipboardList, AlertTriangle, Sparkles,
  ShieldCheck, Activity, Wallet, CalendarClock, Users,
} from "lucide-react";
import { useAdvisorBook } from "@/hooks/use-advisor";
import { useActivateProfile, useNeedsAttention } from "@/hooks/use-mfd";
import { useToastStore } from "@/stores/toast.store";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { ErrorState } from "@/components/shared/ErrorState";
import {
  TONE, fmtRs, fmtDaysSince, healthTone, decorateProfile,
  type AdvisorProfile, type Tone,
} from "@/pages/AdvisorDashboard/derive";
import type { NeedsAttentionItemC } from "@/services/contracts/advisor.contract";

/** Wealth tier from AUM (mirrors the V2 HNI / UHNI badge thresholds). */
function wealthTier(aum?: number | null): string | null {
  if (aum == null) return null;
  if (aum >= 5e7) return "UHNI";
  if (aum >= 2e7) return "HNI";
  if (aum >= 5e6) return "Affluent";
  return null;
}

function ScoreTile({ label, value, tone, Icon }: { label: string; value: number | null; tone: Tone; Icon: typeof Activity }) {
  const t = TONE[tone];
  return (
    <div className={`rounded-lg border p-3 ${t.bg} ${t.border}`}>
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider font-semibold text-ink-3">
        <Icon className="w-3.5 h-3.5" /> {label}
      </div>
      <div className={`mt-1.5 text-2xl font-bold tabular-nums ${t.text}`}>
        {value == null ? "—" : Math.round(value)}
        {value != null && <span className="text-[11px] text-ink-4 font-normal ml-0.5">/100</span>}
      </div>
    </div>
  );
}

function ClientDetail({ p, onOpen, activating }: {
  p: AdvisorProfile;
  onOpen: (route: string) => void;
  activating: boolean;
}) {
  const attention = useNeedsAttention(p.profile_id);
  const items = (attention.data ?? []) as NeedsAttentionItemC[];
  const tier = wealthTier(p._aum);
  const reasons = p.priority?.reasons ?? [];

  return (
    <div className="space-y-4" data-testid="client360-detail">
      {/* Header */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-11 h-11 rounded-full bg-accent/15 text-accent flex items-center justify-center text-base font-bold flex-shrink-0" aria-hidden>
            {p.name?.slice(0, 1).toUpperCase() || "?"}
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-semibold text-ink truncate">{p.name}</h2>
              {p.type === "SELF" && <span className="text-[8px] rounded border border-hairline px-1 text-ink-3">YOU</span>}
              {tier && <span className="text-[9px] rounded-full bg-accent/15 text-accent px-2 py-0.5 font-semibold">{tier}</span>}
            </div>
            <div className="text-[11.5px] text-ink-3 mt-0.5 flex items-center gap-2 flex-wrap">
              <span className="inline-flex items-center gap-1"><Wallet className="w-3 h-3" /> {fmtRs(p._aum)}</span>
              <span className="inline-flex items-center gap-1">
                <CalendarClock className="w-3 h-3" />
                {p.last_reviewed_at ? `Reviewed ${fmtDaysSince(p.last_reviewed_at)}` : "Not reviewed yet"}
              </span>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => onOpen("/plan")}
            disabled={activating}
            className="inline-flex items-center gap-1.5 rounded-md px-3 h-9 text-[12px] font-semibold bg-surface-2 border border-hairline text-ink-2 hover:bg-surface-3 transition-colors disabled:opacity-60"
          >
            <ClipboardList className="w-3.5 h-3.5" /> Plan board
          </button>
          <button
            type="button"
            onClick={() => onOpen("/dashboard")}
            disabled={activating}
            data-testid="client360-open-portfolio"
            className="inline-flex items-center gap-1.5 rounded-md px-3 h-9 text-[12px] font-semibold bg-accent text-accent-fg hover:opacity-90 transition-opacity disabled:opacity-60"
          >
            Open full portfolio <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Scores */}
      <div className="grid grid-cols-3 gap-3">
        <ScoreTile label="Health" value={p._health ?? null} tone={healthTone(p._health)} Icon={Activity} />
        <ScoreTile label="Quality" value={p.portfolio_score ?? null} tone={healthTone(p.portfolio_score)} Icon={ShieldCheck} />
        <ScoreTile label="Risk" value={p.risk_score ?? null} tone={p.risk_score == null ? "neutral" : p.risk_score >= 60 ? "neg" : p.risk_score >= 40 ? "warm" : "pos"} Icon={AlertTriangle} />
      </div>

      {/* Top issue + AI summary */}
      <div className="rounded-lg border border-hairline bg-surface-1 p-4">
        <div className="flex items-center gap-2">
          <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold ${TONE[p._issue!.tone].bg} ${TONE[p._issue!.tone].border} ${TONE[p._issue!.tone].text}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${TONE[p._issue!.tone].dot}`} /> {p._issue!.label}
          </span>
        </div>
        {p.ai_summary && (
          <p className="text-[13px] text-ink-2 leading-relaxed mt-3">
            <Sparkles className="w-3 h-3 inline -mt-0.5 mr-1 text-accent" />{p.ai_summary}
          </p>
        )}
        {reasons.length > 0 && (
          <ul className="mt-3 space-y-1.5">
            {reasons.map((r, i) => (
              <li key={i} className="text-[12px] text-ink-3 flex items-start gap-2">
                <span className="mt-1 w-1 h-1 rounded-full bg-ink-4 flex-shrink-0" /> {r}
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Needs attention */}
      <div className="rounded-lg border border-hairline bg-surface-1 p-4">
        <div className="text-[11px] uppercase tracking-wider font-semibold text-ink-4 mb-2">Needs attention</div>
        {attention.isPending ? (
          <div className="h-12 rounded-md bg-surface-2 animate-pulse" />
        ) : items.length === 0 ? (
          <div className="text-[12.5px] text-ink-3">Nothing flagged right now.</div>
        ) : (
          <ul className="space-y-2">
            {items.map((it, i) => {
              const tone: Tone = it.priority === "high" ? "neg" : it.priority === "medium" ? "warm" : "neutral";
              return (
                <li key={i} className="flex items-start gap-2.5">
                  <span className={`mt-1.5 w-1.5 h-1.5 rounded-full flex-shrink-0 ${TONE[tone].dot}`} />
                  <div className="min-w-0">
                    <div className="text-[13px] text-ink-2">{it.message || it.type}</div>
                    {it.holding_name && <div className="text-[11px] text-ink-4 truncate">{it.holding_name}</div>}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {/* Tags */}
      {(p.tags?.length ?? 0) > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {p.tags!.map((tag) => (
            <span key={tag} className="text-[11px] rounded-full border border-hairline px-2 py-0.5 text-ink-3">{tag}</span>
          ))}
        </div>
      )}
    </div>
  );
}

export default function Client360Page() {
  const navigate = useNavigate();
  const push = useToastStore((s) => s.push);
  const book = useAdvisorBook();
  const activate = useActivateProfile();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const ws = book.data?.workspace as { type?: string } | undefined;
  const profiles = book.data?.profiles ?? [];

  const decorated = useMemo<AdvisorProfile[]>(
    () => profiles.map(decorateProfile),
    [profiles],
  );

  const selected = useMemo(
    () => decorated.find((p) => p.profile_id === selectedId) ?? decorated[0] ?? null,
    [decorated, selectedId],
  );

  if (book.isPending) {
    return (
      <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1100px] mx-auto w-full">
        <LoadingSkeleton variant="dashboard" />
      </div>
    );
  }
  if (book.isError) {
    return <ErrorState title="Couldn't load your client book" error={book.error} onRetry={() => book.refetch()} />;
  }

  // Client 360 is advisor-only. Non-advisors shouldn't reach it via nav, but a
  // deep-link lands here — show a gentle redirect prompt rather than an error.
  if ((ws?.type || "").toUpperCase() !== "ADVISORY") {
    return (
      <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[640px] mx-auto w-full">
        <div className="rounded-lg border border-dashed border-accent/40 bg-surface-1 p-6 text-center">
          <Contact className="w-8 h-8 text-accent mx-auto mb-3" />
          <div className="font-display text-lg tracking-tightish text-ink">Client 360 is for advisors</div>
          <p className="text-sm text-ink-2 mt-2">Switch to Advisor mode from the Advisor Workspace to manage client portfolios here.</p>
          <button onClick={() => navigate("/advisor")} className="mt-4 inline-flex items-center gap-1 px-3 py-2 rounded-md bg-accent text-accent-fg text-sm font-medium hover:opacity-90">
            Go to Advisor Workspace <ArrowRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    );
  }

  const openClient = (route: string) => {
    if (!selected) return;
    activate.mutate({ profileId: selected.profile_id, name: selected.name }, {
      onSuccess: () => {
        push({ kind: "success", title: `Opened ${selected.name}'s portfolio` });
        navigate(route);
      },
      onError: (e) => push({ kind: "error", title: "Could not open profile", description: e instanceof Error ? e.message : undefined }),
    });
  };

  return (
    <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1100px] mx-auto w-full" data-testid="client360-page">
      {/* Header */}
      <div className="flex items-center gap-2 mb-1">
        <Contact className="w-5 h-5 text-accent" />
        <h1 className="font-display text-2xl tracking-tightish text-ink">Client 360</h1>
      </div>
      <p className="text-sm text-ink-3 mb-5">A full read on each client — health, risks, what needs attention — before you open their portfolio.</p>

      {decorated.length === 0 ? (
        <div className="rounded-lg border border-hairline bg-surface-1 p-10 text-center text-sm text-ink-3">
          <Users className="w-8 h-8 mx-auto mb-2 opacity-40" />
          No clients yet — add clients from the Advisor Workspace to see their 360 here.
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-4">
          {/* Master: client list */}
          <div className="rounded-lg border border-hairline bg-surface-1 overflow-hidden self-start">
            <div className="px-3 py-2 bg-surface-2 text-[10px] uppercase tracking-wider font-semibold text-ink-4 border-b border-hairline">
              {decorated.length} {decorated.length === 1 ? "client" : "clients"}
            </div>
            <div className="divide-y divide-[color:var(--line)] max-h-[70vh] overflow-y-auto">
              {decorated.map((p) => {
                const active = selected?.profile_id === p.profile_id;
                const ht = TONE[healthTone(p._health)];
                return (
                  <button
                    key={p.profile_id}
                    type="button"
                    onClick={() => setSelectedId(p.profile_id)}
                    data-testid={`client360-row-${p.profile_id}`}
                    className={`w-full flex items-center gap-2.5 px-3 py-2.5 text-left transition-colors ${active ? "bg-surface-2" : "hover:bg-surface-2/60"}`}
                  >
                    <div className="w-8 h-8 rounded-full bg-accent/15 text-accent flex items-center justify-center text-[11px] font-bold flex-shrink-0" aria-hidden>
                      {p.name?.slice(0, 1).toUpperCase() || "?"}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="text-[13px] font-medium text-ink truncate flex items-center gap-1.5">
                        {p.name}
                        {p.type === "SELF" && <span className="text-[8px] rounded border border-hairline px-1 text-ink-3">YOU</span>}
                      </div>
                      <div className="text-[10.5px] text-ink-4 truncate">{fmtRs(p._aum)}</div>
                    </div>
                    <span className={`text-[13px] font-bold tabular-nums ${ht.text}`}>{p._health ?? "—"}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Detail */}
          <div className="rounded-lg border border-hairline bg-surface-1 shadow-card p-4 lg:p-5">
            {selected ? (
              <ClientDetail p={selected} onOpen={openClient} activating={activate.isPending} />
            ) : (
              <div className="py-10 text-center text-sm text-ink-3">Select a client to see their 360.</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
