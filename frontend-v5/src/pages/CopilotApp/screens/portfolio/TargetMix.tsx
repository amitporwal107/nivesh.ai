/**
 * Portfolio analysis — "Your mix against the target": each asset class as it
 * is held today, beside the target mix for the user's risk category, and the
 * gap between the two.
 *
 * Data:
 *   held today     the asset-class split the table above it shows
 *                  (GET /api/portfolio/composition?dimension=asset_class)
 *   risk category  GET /api/user/risk-profile                (useRiskCategory)
 *   target         targetAllocationFor(category) from hooks/use-risk-profile —
 *                  the table the Home drift card, the Dashboard and the Risk
 *                  screen read, so every screen quotes the same target.
 *
 * The target has four classes (equity, debt, gold, cash). A class the split
 * returns outside those four (hybrid, international) is listed with no target
 * rather than folded into one of them.
 */
import { targetAllocationFor } from "@/hooks/use-risk-profile";
import { Btn, DataTable, EmptyBlock, ErrorBlock, Footnote, LoadingBlock, Pill, Section, fmtPct, type Column, type Tone } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { ShareBar } from "./charts";
import { loadError, useRiskCategory, type AssetClassSlice } from "./data";

const TARGET_CLASSES = [
  { key: "equity", label: "Equity" },
  { key: "debt", label: "Debt" },
  { key: "gold", label: "Gold" },
  { key: "cash", label: "Cash" },
] as const;

/**
 * Points either side of the target that still read as "in line". The plan
 * engine's own drift check uses the same band (backend deviation_engine,
 * _SOFT_PP).
 */
const IN_LINE_PTS = 5;

export interface MixRow {
  key: string;
  label: string;
  /** Share held today, percent of the portfolio. */
  actualPct: number;
  /** null = this class is not part of the four-class target. */
  targetPct: number | null;
  /** actual − target, in percentage points. */
  driftPts: number | null;
}

/** The four target classes first (a class the user holds none of counts as 0%), then any other class held. */
export function mixRows(slices: AssetClassSlice[], target: Record<(typeof TARGET_CLASSES)[number]["key"], number>): MixRow[] {
  const held = new Map(slices.map((s) => [s.name.trim().toLowerCase(), s.weightPct ?? 0]));
  const rows: MixRow[] = TARGET_CLASSES.map((c) => {
    const actualPct = held.get(c.key) ?? 0;
    return { key: c.key, label: c.label, actualPct, targetPct: target[c.key], driftPts: actualPct - target[c.key] };
  });
  const inTarget = new Set<string>(TARGET_CLASSES.map((c) => c.key));
  for (const s of slices) {
    const key = s.name.trim().toLowerCase();
    if (!inTarget.has(key)) rows.push({ key, label: s.name, actualPct: s.weightPct ?? 0, targetPct: null, driftPts: null });
  }
  return rows;
}

function driftText(pts: number): string {
  return `${pts > 0 ? "+" : pts < 0 ? "−" : ""}${Math.abs(pts).toFixed(1)} pts`;
}

function driftMeta(pts: number | null): { label: string; tone: Tone } | null {
  if (pts == null) return null;
  if (Math.abs(pts) <= IN_LINE_PTS) return { label: "In line", tone: "ink" };
  return pts > 0 ? { label: "Above target", tone: "amber" } : { label: "Below target", tone: "amber" };
}

/** "Hybrid", "Hybrid and International", "A, B and C". */
function listNames(names: string[]): string {
  if (names.length <= 1) return names.join("");
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

export function TargetMix({ slices }: { slices: AssetClassSlice[] }) {
  const { ask, go } = useCopilotShell();
  const q = useRiskCategory();
  if (q.isPending) return <LoadingBlock label="Loading your target mix" rows={3} />;
  if (q.isError) return <ErrorBlock title="Your target mix didn’t load" error={loadError(q.error)} onRetry={() => q.refetch()} />;

  const category = q.data;
  if (!category) {
    return (
      <div data-testid="analysis-target-empty">
        <EmptyBlock
          title="No target mix yet"
          body="The target comes from your risk profile, and you have not set one. It takes about two minutes."
          action={<Btn variant="primary" onClick={() => go("page/settings")}>Set up risk profile</Btn>}
        />
      </div>
    );
  }
  const target = targetAllocationFor(category);
  if (!target) {
    return (
      <div data-testid="analysis-target-unmapped">
        <EmptyBlock
          title="No target mix for this risk category"
          body={`Your risk profile says “${category}”, which has no standard mix defined. Retake the risk questions to get one of the five standard categories.`}
          action={<Btn onClick={() => go("page/settings")}>Open risk profile</Btn>}
        />
      </div>
    );
  }

  const rows = mixRows(slices, target);
  const scale = Math.max(...rows.map((r) => Math.max(r.actualPct, r.targetPct ?? 0)), 1);
  const furthest = rows.reduce<MixRow | null>((a, r) => (r.driftPts != null && Math.abs(r.driftPts) > Math.abs(a?.driftPts ?? 0) ? r : a), null);
  const outside = rows.filter((r) => r.targetPct == null).map((r) => r.label);
  const headline = furthest && furthest.driftPts != null && Math.abs(furthest.driftPts) > IN_LINE_PTS
    ? `${furthest.label} is ${Math.abs(furthest.driftPts).toFixed(1)} points ${furthest.driftPts > 0 ? "above" : "below"} the target.`
    : `Every class is within ${IN_LINE_PTS} points of the target.`;

  const columns: Array<Column<MixRow>> = [
    { key: "name", header: "Asset class", width: "minmax(0,1.1fr)", render: (r) => <span data-testid="analysis-target-class" style={{ color: "var(--cp-ink)", fontWeight: 500 }}>{r.label}</span> },
    { key: "actual", header: "Held", num: true, align: "right", render: (r) => <span data-testid={`analysis-target-${r.key}-actual`}>{fmtPct(r.actualPct)}</span> },
    { key: "target", header: "Target", num: true, align: "right", render: (r) => <span data-testid={`analysis-target-${r.key}-target`}>{r.targetPct == null ? "—" : fmtPct(r.targetPct, { digits: 0 })}</span> },
    {
      key: "drift", header: "Drift", num: true, align: "right",
      render: (r) => <span data-testid={`analysis-target-${r.key}-drift`} style={{ color: r.driftPts != null && Math.abs(r.driftPts) > IN_LINE_PTS ? "var(--amber)" : undefined }}>{r.driftPts == null ? "—" : driftText(r.driftPts)}</span>,
    },
    {
      key: "bar", header: "Held vs target", width: "minmax(0,1.6fr)",
      render: (r) => (
        <span role="img" aria-label={r.targetPct == null ? `${r.label}: ${fmtPct(r.actualPct)} held, no target` : `${r.label}: ${fmtPct(r.actualPct)} held against a target of ${fmtPct(r.targetPct, { digits: 0 })}`} style={{ display: "block", padding: "5px 0" }}>
          <ShareBar pct={r.actualPct} max={scale} markPct={r.targetPct} />
        </span>
      ),
    },
    {
      key: "read", header: "Reading", width: "minmax(0,1.1fr)",
      render: (r) => {
        const meta = driftMeta(r.driftPts);
        return meta ? <Pill tone={meta.tone}>{meta.label}</Pill> : <span style={{ color: "var(--cp-ink-3)" }}>No target</span>;
      },
    },
  ];

  return (
    <div data-testid="analysis-target">
      <Section
        flush
        title={<>Your mix against the target for a <span data-testid="analysis-target-category">{category}</span> risk profile</>}
        note={<span data-testid="analysis-target-headline">{headline}</span>}
      >
        <DataTable
          columns={columns}
          rows={rows}
          rowKey={(r) => r.key}
          minWidth={600}
          onRowClick={(r) => ask(r.targetPct == null
            ? `${fmtPct(r.actualPct)} of my portfolio is in ${r.label}. How does that fit a ${category} risk profile?`
            : `My ${r.label.toLowerCase()} allocation is ${fmtPct(r.actualPct)} against a target of ${fmtPct(r.targetPct, { digits: 0 })} for a ${category} risk profile. What would bringing it in line involve, and what would it cost in tax?`)}
        />
        <div className="flex flex-col" style={{ gap: 4, padding: "10px 16px 12px" }}>
          <Footnote>
            Target = the standard mix for the {category} risk category on your risk profile · the tick on each bar marks it · within {IN_LINE_PTS} points reads as in line
          </Footnote>
          {outside.length > 0 && (
            <Footnote>
              <span data-testid="analysis-target-outside">{listNames(outside)}</span> {outside.length === 1 ? "is" : "are"} not part of the four-class target, so {outside.length === 1 ? "it has" : "they have"} no target of {outside.length === 1 ? "its" : "their"} own
            </Footnote>
          )}
          <Footnote>A reference for comparison · Educational, not investment advice</Footnote>
        </div>
      </Section>
    </div>
  );
}
