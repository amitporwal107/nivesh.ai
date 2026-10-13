/**
 * Markets → Corporate Actions. The NSE corporate-action calendar from
 * GET /api/markets/corporate-actions for 30 days either side of today.
 */
import { useMemo, useState } from "react";
import { useCorporateActions } from "@/hooks/use-markets";
import type { CorpAction } from "@/services/contracts/markets.contract";
import { DataTable, LoadingBlock, Section, fmtNum, type Column } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { dayLabel, isoDay, titleCase } from "./format";
import { isHeld, useHeldKeys } from "./hooks";
import { FilterChips, LoadError, NameCell } from "./parts";

/** Raw action_type → label, in the order the calendar lists them. */
export const ACTION_LABELS: Record<string, string> = {
  DIVIDEND: "Dividend",
  BONUS: "Bonus",
  RIGHTS: "Rights",
  SPLIT: "Split",
  MERGER: "Merger",
  DEMERGER: "Demerger",
  BUYBACK: "Buyback",
};
const TYPE_ORDER = ["DIVIDEND", "BONUS", "RIGHTS", "SPLIT", "MERGER", "DEMERGER", "BUYBACK"];
const ALL = "ALL";

export function actionLabel(type: string): string {
  return ACTION_LABELS[type] ?? titleCase(type);
}

export function ActionsTab() {
  const range = useMemo(() => ({ from: isoDay(-30), to: isoDay(30) }), []);
  const [type, setType] = useState<string>(ALL);
  const q = useCorporateActions({ ...range, type: type === ALL ? undefined : type });
  const held = useHeldKeys();
  const { ask } = useCopilotShell();

  if (q.isPending) return <LoadingBlock label="Loading corporate actions" rows={5} />;
  if (q.isError) return <LoadError title="Corporate actions didn’t load" error={q.error} onRetry={() => q.refetch()} />;

  const counts = q.data.type_counts;
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  const chips = [
    { key: ALL, label: `All ${fmtNum(total)}` },
    ...TYPE_ORDER.map((t) => ({ key: t, label: `${ACTION_LABELS[t]} ${fmtNum(counts[t] ?? 0)}` })),
  ];

  const columns: Column<CorpAction>[] = [
    {
      key: "company", header: "Company", width: "minmax(0,1.9fr)",
      render: (a) => <NameCell name={a.name} sub={a.symbol} held={isHeld(held.data, a.symbol, a.name)} />,
    },
    { key: "ex", header: "Ex-date", render: (a) => dayLabel(a.ex_date, { year: true }) },
    { key: "event", header: "Event", render: (a) => actionLabel(a.action_type) },
    { key: "details", header: "Details", align: "right", num: true, render: (a) => a.value_label ?? "—" },
  ];

  return (
    <>
      <FilterChips items={chips} value={type} onChange={setType} label="Action type" idPrefix="markets-actions-type" />
      <Section
        title={`Corporate actions · ${dayLabel(q.data.from ?? range.from)} – ${dayLabel(q.data.to ?? range.to, { year: true })}`}
        note="Source: NSE"
        flush
      >
        <div data-testid="markets-actions">
          <DataTable
            columns={columns}
            rows={q.data.actions}
            rowKey={(a, i) => `${a.symbol}-${a.action_type}-${a.ex_date ?? ""}-${i}`}
            onRowClick={(a) => ask(
              `What does the ${actionLabel(a.action_type).toLowerCase()} from ${a.name}`
              + `${a.ex_date ? ` with ex-date ${dayLabel(a.ex_date, { year: true })}` : ""} mean for shareholders?`,
            )}
            minWidth={520}
            empty={type === ALL
              ? "No corporate actions fall in this 60-day window."
              : `No ${actionLabel(type).toLowerCase()} actions fall in this 60-day window.`}
          />
        </div>
      </Section>
    </>
  );
}
