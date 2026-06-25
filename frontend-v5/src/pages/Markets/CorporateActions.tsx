import { useEffect, useMemo, useState } from "react";
import { Search } from "lucide-react";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/formatters";
import { useCorporateActions } from "@/hooks/use-markets";
import { ErrorState } from "@/components/shared/ErrorState";
import type { CorpAction } from "@/services/contracts/markets.contract";

/** Filter rail order + display labels (raw action_type → label). */
const TYPE_LABELS: Record<string, string> = {
  DIVIDEND: "Dividend",
  BONUS: "Bonus",
  RIGHTS: "Rights",
  SPLIT: "Splits",
  MERGER: "Merger",
  DEMERGER: "Demerger",
  BUYBACK: "Buy Back",
};
const TYPE_ORDER = ["DIVIDEND", "BONUS", "RIGHTS", "SPLIT", "MERGER", "DEMERGER", "BUYBACK"];

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

export default function CorporateActionsPage() {
  const today = useMemo(() => new Date(), []);
  const plus30 = useMemo(() => {
    const d = new Date();
    d.setDate(d.getDate() + 30);
    return d;
  }, []);

  const [from, setFrom] = useState(isoDate(today));
  const [to, setTo] = useState(isoDate(plus30));
  const [type, setType] = useState<string | null>(null);
  const [qInput, setQInput] = useState("");
  const [q, setQ] = useState("");

  // Debounce the search box so we don't refetch on every keystroke.
  useEffect(() => {
    const t = setTimeout(() => setQ(qInput.trim()), 300);
    return () => clearTimeout(t);
  }, [qInput]);

  const query = useCorporateActions({ from, to, type: type ?? undefined, q: q || undefined });

  return (
    <div className="mx-auto w-full max-w-[1180px] px-6 pb-12 pt-6 lg:px-10">
      <div>
        <h1 className="font-display text-2xl text-ink">Corporate Actions</h1>
        <p className="mt-0.5 text-xs text-ink-3">
          Dividends, bonuses, splits, rights, buybacks &amp; mergers · NSE corporate-action calendar
        </p>
      </div>

      <div className="mt-5 grid gap-5 lg:[grid-template-columns:230px_1fr]">
        {/* ── Filter rail ──────────────────────────────────────── */}
        <aside className="flex flex-col gap-5">
          <div>
            <p className="mb-2 text-[10.5px] font-semibold uppercase tracking-[0.13em] text-ink-4">Date range</p>
            <div className="flex flex-col gap-2">
              <input
                type="date"
                value={from}
                max={to}
                onChange={(e) => setFrom(e.target.value)}
                className="w-full rounded-md border border-hairline bg-surface-1 px-2.5 py-1.5 text-[12.5px] text-ink"
              />
              <input
                type="date"
                value={to}
                min={from}
                onChange={(e) => setTo(e.target.value)}
                className="w-full rounded-md border border-hairline bg-surface-1 px-2.5 py-1.5 text-[12.5px] text-ink"
              />
            </div>
          </div>

          <div>
            <p className="mb-2 text-[10.5px] font-semibold uppercase tracking-[0.13em] text-ink-4">Action</p>
            <div className="flex flex-col">
              <FilterRow
                label="All actions"
                count={Object.values(query.data?.type_counts ?? {}).reduce((a, b) => a + b, 0)}
                active={type === null}
                onClick={() => setType(null)}
              />
              {TYPE_ORDER.map((t) => (
                <FilterRow
                  key={t}
                  label={TYPE_LABELS[t]}
                  count={query.data?.type_counts?.[t] ?? 0}
                  active={type === t}
                  onClick={() => setType(type === t ? null : t)}
                />
              ))}
            </div>
          </div>
        </aside>

        {/* ── List ─────────────────────────────────────────────── */}
        <div>
          <div className="relative mb-3">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-4" />
            <input
              value={qInput}
              onChange={(e) => setQInput(e.target.value)}
              placeholder="Search company name or symbol"
              className="w-full rounded-md border border-hairline bg-surface-1 py-2 pl-9 pr-3 text-[13px] text-ink placeholder:text-ink-4"
            />
          </div>

          {query.isError ? (
            <ErrorState
              title="Couldn't load corporate actions"
              error={query.error}
              onRetry={() => query.refetch()}
            />
          ) : (
            <Card className="p-0">
              <div className="grid items-center gap-2 border-b border-hairline px-4 py-2.5 text-[9.5px] uppercase tracking-[0.1em] text-ink-4 [grid-template-columns:1fr_110px_120px_100px]">
                <span>Company</span>
                <span>Ex-date</span>
                <span>Event</span>
                <span className="text-right">Details</span>
              </div>

              {query.isPending ? (
                <p className="px-4 py-10 text-center text-sm text-ink-3">Loading…</p>
              ) : query.data.actions.length === 0 ? (
                <p className="px-4 py-10 text-center text-sm text-ink-3">
                  No corporate actions match these filters.
                </p>
              ) : (
                query.data.actions.map((a, i) => <ActionRow key={`${a.symbol}-${a.action_type}-${a.ex_date}-${i}`} a={a} />)
              )}
            </Card>
          )}

          {query.data && query.data.actions.length > 0 && (
            <p className="mt-3 text-[11px] text-ink-4">
              {query.data.actions.length} event{query.data.actions.length === 1 ? "" : "s"}
              {" · "}
              {formatDate(from)} – {formatDate(to)} · source: NSE via NIDP
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function FilterRow({ label, count, active, onClick }: { label: string; count: number; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "flex items-center justify-between rounded px-2 py-1.5 text-[12.5px] transition-colors",
        active ? "bg-surface-3 font-medium text-ink" : "text-ink-2 hover:bg-surface-2",
      )}
    >
      <span>{label}</span>
      <span className={cn("num text-[11px]", active ? "text-ink-2" : "text-ink-4")}>{count}</span>
    </button>
  );
}

function ActionRow({ a }: { a: CorpAction }) {
  return (
    <div className="grid items-center gap-2 border-t border-hairline px-4 py-2.5 text-[12.5px] first:border-t-0 [grid-template-columns:1fr_110px_120px_100px]">
      <div className="min-w-0">
        <div className="truncate text-ink">{a.name}</div>
        <div className="text-[10.5px] text-ink-4">{a.symbol}</div>
      </div>
      <div className="text-ink-2">{a.ex_date ? formatDate(a.ex_date) : "—"}</div>
      <div>
        <span className="inline-flex rounded-full bg-surface-3 px-2 py-0.5 text-[11px] text-ink-2">
          {TYPE_LABELS[a.action_type] ?? a.action_type}
        </span>
      </div>
      <div className="num truncate text-right text-ink" title={a.value_label ?? undefined}>
        {a.value_label ?? "—"}
      </div>
    </div>
  );
}
