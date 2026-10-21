/**
 * Markets → Corporate Actions. The corporate-action calendar from GET
 * /api/markets/corporate-actions: a date range (30 days either side of today
 * to start), an action type and a company search. "Your holdings · corporate
 * actions" (mkt-HeldActions) narrows the same dates to the user's own stocks.
 */
import { useState } from "react";
import type { CorpAction } from "@/services/contracts/markets.contract";
import { DataTable, LoadingBlock, Section, fmtNum, type Column } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { ACTION_LABELS, actionLabel, dayLabel, isoDay } from "./format";
import { isHeld, useActionCalendar, useHeldKeys } from "./hooks";
import { HeldActionsBlock } from "./mkt-HeldActions";
import { CompanyCell, Field, FilterChips, LoadError, SourceLine, useDebounced } from "./parts";

// Other screens import these from here.
export { ACTION_LABELS, actionLabel } from "./format";

const TYPE_ORDER = ["DIVIDEND", "BONUS", "RIGHTS", "SPLIT", "MERGER", "DEMERGER", "BUYBACK"];
const ALL = "ALL";

export function ActionsTab() {
  const [from, setFrom] = useState(() => isoDay(-30));
  const [to, setTo] = useState(() => isoDay(30));
  const [type, setType] = useState<string>(ALL);
  const [search, setSearch] = useState("");
  const term = useDebounced(search.trim());
  const q = useActionCalendar({ from, to, type: type === ALL ? undefined : type, q: term || undefined });
  const held = useHeldKeys();
  const { ask } = useCopilotShell();

  const filters = (
    <div className="flex flex-wrap items-end" style={{ gap: 12 }}>
      {/* A cleared date box keeps the last date: the calendar always needs both ends. */}
      <Field label="From" type="date" value={from} max={to} onChange={(v) => { if (v) setFrom(v); }} testId="markets-actions-from" />
      <Field label="To" type="date" value={to} min={from} onChange={(v) => { if (v) setTo(v); }} testId="markets-actions-to" />
      <Field label="Company or symbol" type="search" value={search} onChange={setSearch} placeholder="Search the calendar" testId="markets-actions-search" grow />
    </div>
  );

  if (q.isPending) return <>{filters}<LoadingBlock label="Loading corporate actions" rows={5} /></>;
  if (q.isError) {
    return <>{filters}<LoadError title="Corporate actions didn’t load" error={q.error} onRetry={() => q.refetch()} /></>;
  }

  const counts = q.data.type_counts;
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  const chips = [
    { key: ALL, label: `All ${fmtNum(total)}` },
    ...TYPE_ORDER.map((t) => ({ key: t, label: `${ACTION_LABELS[t]} ${fmtNum(counts[t] ?? 0)}` })),
  ];
  const actions = q.data.actions;
  // How many rows the current type filter should have, from the endpoint's own counts.
  const expected = type === ALL ? total : counts[type] ?? 0;

  const columns: Column<CorpAction>[] = [
    {
      key: "company", header: "Company", width: "minmax(0,1.9fr)",
      render: (a) => <CompanyCell symbol={a.symbol} name={a.name} held={isHeld(held.data, a.symbol, a.name)} />,
    },
    { key: "ex", header: "Ex-date", render: (a) => dayLabel(a.ex_date, { year: true }) },
    { key: "record", header: "Record date", render: (a) => dayLabel(a.record_date, { year: true }) },
    { key: "event", header: "Event", render: (a) => <span title={a.purpose ?? undefined}>{actionLabel(a.action_type)}</span> },
    { key: "details", header: "Details", align: "right", num: true, render: (a) => a.value_label ?? "—" },
  ];

  return (
    <>
      {filters}
      <HeldActionsBlock from={from} to={to} />
      <FilterChips items={chips} value={type} onChange={setType} label="Action type" idPrefix="markets-actions-type" />
      <Section
        title={`Corporate actions · ${dayLabel(q.data.from ?? from)} – ${dayLabel(q.data.to ?? to, { year: true })}`}
        note={<span data-testid="markets-actions-count">{fmtNum(actions.length)} {actions.length === 1 ? "event" : "events"}{q.isPlaceholderData ? " · updating…" : ""}</span>}
        flush
      >
        <div data-testid="markets-actions">
          <DataTable
            columns={columns}
            rows={actions}
            rowKey={(a, i) => `${a.symbol}-${a.action_type}-${a.ex_date ?? ""}-${i}`}
            onRowClick={(a) => ask(
              `What does the ${actionLabel(a.action_type).toLowerCase()} from ${a.name}`
              + `${a.ex_date ? ` with ex-date ${dayLabel(a.ex_date, { year: true })}` : ""} mean for shareholders?`,
            )}
            minWidth={640}
            empty={term
              ? `No corporate action in these dates matches “${term}”.`
              : type === ALL
                ? "No corporate actions fall between these dates."
                : `No ${actionLabel(type).toLowerCase()} actions fall between these dates.`}
          />
          <SourceLine
            testId="markets-actions-source"
            note={!term && expected > actions.length
              ? `Showing the first ${fmtNum(actions.length)} of ${fmtNum(expected)}; narrow the dates or search to see the rest`
              : undefined}
            style={{ padding: "10px 16px" }}
          />
        </div>
      </Section>
    </>
  );
}
