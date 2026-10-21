/**
 * Action plan — expected and observed.
 *
 * What the plan was expected to do, beside what the record of the portfolio
 * shows since the plan was built:
 *
 *   observed        GET /api/portfolio/trend                 (useHealthRecords)
 *                   the health score and its four parts in each recorded
 *                   snapshot: the record on or before the day the plan was
 *                   built, against the latest one
 *   still expected  GET /api/plans/active/health-projection  (usePlanHealthProjection)
 *                   health today → health with every open step applied
 *   plan's figures  `improvements` and `simulation` on GET /api/plans/active
 *                   what the engine expected each figure to move from and to
 *
 * This is the portfolio as a whole. Nothing measures a single step after it
 * is done, so there is no met / partly / missed result per step (the screen
 * says so in its own block).
 */
import {
  DataTable, EmptyBlock, ErrorBlock, Footnote, LoadingBlock, Section,
  TONE_COLOR, fmtDate, fmtINR, fmtNum, fmtPct, signTone, type Column,
} from "../../components/ui";
import {
  humanise, indiaDay, loadError, observedSince, useHealthRecords, usePlanHealthProjection,
  type BeforeAfter, type HealthProjection, type ObservedChange, type PlanFacts, type PlanStep,
} from "./data";

const quiet = { fontSize: 12, lineHeight: 1.55, color: "var(--cp-ink-3)" } as const;

function pts(n: number): string {
  return `${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(n).toFixed(1)} pts`;
}

function Delta({ value, testId }: { value: number | null; testId?: string }) {
  if (value == null) return <span data-testid={testId}>—</span>;
  return <span data-testid={testId} style={{ color: value === 0 ? undefined : TONE_COLOR[signTone(value)] }}>{pts(value)}</span>;
}

// ── health: observed since the plan was built, and still expected ────────

interface HealthRow {
  key: string;
  label: string;
  start: number | null;
  latest: number | null;
  /** latest − start; null unless both are on record on different days. */
  observed: number | null;
  /** Projected − today, with every open step applied; null when there is no projection. */
  expected: number | null;
}

const diff = (a: number | null | undefined, b: number | null | undefined): number | null => (a != null && b != null ? a - b : null);

function healthRows(observed: ObservedChange | null, projection: HealthProjection | null): HealthRow[] {
  const now = projection?.available ? projection.current : null;
  const after = projection?.available ? projection.projected : null;
  const start = observed?.start ?? null;
  const latest = observed?.comparable ? observed.latest : null;

  const rows: HealthRow[] = [{
    key: "overall",
    label: "Health score",
    start: start?.health ?? null,
    latest: latest?.health ?? null,
    observed: diff(latest?.health, start?.health),
    expected: diff(after?.score, now?.score),
  }];
  // The four parts, in the order the backend lists them, then any a record has that the projection lacks.
  const keys = new Set<string>([...(now?.components.map((c) => c.key.toLowerCase()) ?? []), ...Object.keys(start?.components ?? {}), ...Object.keys(latest?.components ?? {})]);
  for (const key of keys) {
    const nowC = now?.components.find((c) => c.key.toLowerCase() === key);
    const afterC = after?.components.find((c) => c.key.toLowerCase() === key);
    rows.push({
      key,
      label: nowC?.name || humanise(key),
      start: start?.components[key] ?? null,
      latest: latest?.components[key] ?? null,
      observed: diff(latest?.components[key], start?.components[key]),
      expected: diff(afterC?.score, nowC?.score),
    });
  }
  return rows;
}

/** One plain sentence on why there is no observed change to show; empty when there is one. */
function noObservation(o: ObservedChange): string {
  if (!o.latest) return "No record of your portfolio is on file yet, so there is nothing to compare.";
  if (!o.start) return `The earliest record on file (${fmtDate(o.latest.date)}) is from after this plan was built, so there is no starting point to compare with.`;
  if (!o.comparable) return `The only record on file for this plan is from ${fmtDate(o.start.date)}, so there is no later one to compare it with yet. The observed change appears after the next statement import or daily record.`;
  return "";
}

function HealthOutcome({ facts, steps }: { facts: PlanFacts; steps: PlanStep[] }) {
  const records = useHealthRecords();
  const projection = usePlanHealthProjection();
  if (records.isPending || projection.isPending) return <LoadingBlock label="Comparing the plan with what has happened" rows={3} />;

  const observed = records.data ? observedSince(records.data, facts.createdAt) : null;
  const rows = healthRows(observed, projection.data ?? null);
  const done = steps.filter((s) => s.status === "COMPLETED").length;
  const open = steps.filter((s) => s.status === "PENDING" || s.status === "IN_PROGRESS").length;
  const why = observed ? noObservation(observed) : "";
  const planDay = indiaDay(facts.createdAt);

  const columns: Array<Column<HealthRow>> = [
    { key: "name", header: "Measure", width: "minmax(0,1.4fr)", render: (r) => <span data-testid="plan-outcome-measure" style={{ color: "var(--cp-ink)", fontWeight: 500 }}>{r.label}</span> },
    { key: "start", header: "At plan start", num: true, align: "right", render: (r) => <span data-testid={`plan-outcome-${r.key}-start`}>{fmtNum(r.start, 1)}</span> },
    { key: "latest", header: "Latest record", num: true, align: "right", render: (r) => <span data-testid={`plan-outcome-${r.key}-latest`}>{fmtNum(r.latest, 1)}</span> },
    { key: "observed", header: "Observed", num: true, align: "right", render: (r) => <Delta value={r.observed} testId={`plan-outcome-${r.key}-observed`} /> },
    { key: "expected", header: "Still expected", num: true, align: "right", render: (r) => <Delta value={r.expected} testId={`plan-outcome-${r.key}-expected`} /> },
  ];

  return (
    <Section
      flush
      title="Expected and observed · portfolio health"
      note={<span data-testid="plan-outcomes-progress">{done} of {steps.length} {steps.length === 1 ? "step" : "steps"} marked done</span>}
    >
      {records.isError && (
        <div style={{ padding: "12px 16px 0" }}>
          <ErrorBlock title="The record of your portfolio’s health didn’t load" error={loadError(records.error)} onRetry={() => records.refetch()} />
        </div>
      )}
      {projection.isError && (
        <div style={{ padding: "12px 16px 0" }}>
          <ErrorBlock title="The projection for the open steps didn’t load" error={loadError(projection.error)} onRetry={() => projection.refetch()} />
        </div>
      )}
      <DataTable columns={columns} rows={rows} rowKey={(r) => r.key} minWidth={620} />
      <div className="flex flex-col" style={{ gap: 6, padding: "10px 16px 12px" }}>
        {why && <span data-testid="plan-outcomes-observed-empty" style={quiet}>{why}</span>}
        {observed?.comparable && observed.start && observed.latest && (
          <span data-testid="plan-outcomes-window" style={quiet}>
            Observed = the record of {fmtDate(observed.latest.date)} against the record of {fmtDate(observed.start.date)}{planDay ? `, the one on file when the plan was built (${fmtDate(planDay)})` : ""}.
          </span>
        )}
        {observed?.comparable && done === 0 && (
          <span data-testid="plan-outcomes-no-steps-done" style={quiet}>No step is marked done, so the change so far comes from the market and your own transactions, not from this plan.</span>
        )}
        {projection.data && !projection.isError && (
          <span data-testid="plan-outcomes-expected-note" style={quiet}>
            {projection.data.available && projection.data.projected
              ? `Still expected = the change if ${open === 1 ? "the one open step is" : `all ${open} open steps are`} done, worked out on today’s holdings.`
              : "No projection is available for the open steps of this plan."}
          </span>
        )}
        <Footnote>Scores are out of 100 · Educational, not investment advice</Footnote>
      </div>
    </Section>
  );
}

// ── the figures the plan itself expected to move ─────────────────────────

function show(b: BeforeAfter, value: number): string {
  return b.unit === "pct" ? fmtPct(value, { digits: b.digits }) : fmtNum(value, b.digits);
}

function change(b: BeforeAfter): string {
  const d = b.after - b.before;
  if (d === 0) return "No change";
  const size = b.unit === "pct" ? `${Math.abs(d).toFixed(b.digits)} pts` : fmtNum(Math.abs(d), b.digits);
  return `${d > 0 ? "+" : "−"}${size}`;
}

const EXPECTED_COLUMNS: Array<Column<BeforeAfter>> = [
  { key: "label", header: "Figure", width: "minmax(0,2fr)", render: (b) => <span data-testid="plan-expected-label" style={{ color: "var(--cp-ink)", fontWeight: 500 }}>{b.label}</span> },
  { key: "before", header: "When built", num: true, align: "right", render: (b) => <span data-testid={`plan-expected-${b.key}-before`}>{show(b, b.before)}</span> },
  { key: "after", header: "Expected after", num: true, align: "right", render: (b) => <span data-testid={`plan-expected-${b.key}-after`}>{show(b, b.after)}</span> },
  { key: "change", header: "Change", num: true, align: "right", render: (b) => <span data-testid={`plan-expected-${b.key}-change`}>{change(b)}</span> },
];

function PlanExpected({ facts }: { facts: PlanFacts }) {
  if (!facts.expected.length && facts.annualCostSavingRs == null) {
    return (
      <div data-testid="plan-expected-empty">
        <EmptyBlock title="The plan carries no expected figures" body="The plan engine attached no before-and-after figures to this plan, so there is nothing to set the record against." />
      </div>
    );
  }
  const built = indiaDay(facts.createdAt);
  return (
    <Section flush title="What the plan expected to change" note={built ? `Worked out when the plan was built · ${fmtDate(built)}` : "Worked out when the plan was built"}>
      <div data-testid="plan-expected">
        {facts.expected.length > 0 && <DataTable columns={EXPECTED_COLUMNS} rows={facts.expected} rowKey={(b) => b.key} minWidth={560} />}
        <div className="flex flex-col" style={{ gap: 6, padding: "10px 16px 12px" }}>
          {facts.annualCostSavingRs != null && (
            <span style={quiet}>
              Fees the plan expects to save: <span data-testid="plan-expected-saving" className="cp-num" style={{ color: "var(--cp-ink)" }}>{fmtINR(facts.annualCostSavingRs)}</span> a year.
            </span>
          )}
          <Footnote>The plan engine’s own estimate if every step is carried out · not a promise of any outcome</Footnote>
        </div>
      </div>
    </Section>
  );
}

export function PlanOutcomes({ facts, steps }: { facts: PlanFacts; steps: PlanStep[] }) {
  return (
    <div data-testid="plan-outcomes" className="flex flex-col" style={{ gap: 12 }}>
      <HealthOutcome facts={facts} steps={steps} />
      <PlanExpected facts={facts} />
    </div>
  );
}
