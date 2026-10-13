/**
 * Portfolio analysis — concentration: the headline and overall verdict, the
 * Effective N ladder, the per-axis summary that sits over each exposure table
 * (Sector, Company, AMC, Group) and the fund-overlap list. These are the data
 * blocks of the old AI Insights screen (src/pages/Concentration).
 *
 * Icons: a fund house row and each fund of an overlapping pair show the fund
 * house icon; the stocks a pair shares show the company icon.
 *
 * Data:
 *   headline, verdict, ladder, axis summaries, AMC and Group tables
 *                    GET /api/portfolio/exposure/concentration        (usePortfolioConcentration)
 *   fund overlap     GET /api/portfolio/exposure/fund-overlap/matrix  (useConcentrationAnalysis)
 *
 * Left out because the old screen hard-codes them: its "As of 27 May 2026" and
 * "Fund disclosures as of 25 May 2026" dates, its one-paragraph summary under
 * the headline, and "Classification coverage · 100%" (shown only when the
 * backend sends a coverage figure for the axis; it sends none today).
 */
import { useState } from "react";
import { useConcentrationAnalysis } from "@/hooks/use-analytics";
import { usePortfolioConcentration } from "@/hooks/use-portfolio";
import type { ConcentrationBreakdownC } from "@/services/contracts/portfolio.contract";
import {
  Btn, DataTable, EmptyBlock, ErrorBlock, LoadingBlock, Pill, Section,
  TONE_COLOR, fmtINR, fmtNum, fmtPct, type Column, type Tone,
} from "../../components/ui";
import { FundHouseIcon } from "../../components/EntityIcon";
import { useCopilotShell } from "../../lib/shell-context";
import { ShareBar } from "./charts";
import {
  PAIR_META, VERDICT_META, capScale, capStatus, capStatusText, lensOf, readConcentration, readOverlap,
  type AxisId, type ConcentrationRead, type FundPair, type Lens, type LensItem,
} from "./concentration-data";
import { HoldingIcon } from "./names";
import { BAD_SHAPE, loadError, num } from "./data";
import { ShowAll } from "./parts";

const quiet = { fontSize: 12, lineHeight: 1.55, color: "var(--cp-ink-3)" } as const;

/** "sector", "company", "AMC", "group" — the axis name inside a sentence. */
function inline(lens: Lens): string {
  return lens.id === "amc" ? lens.label : lens.label.toLowerCase();
}

/** A percentage as the backend rounded it: "52.34%", "63%". */
function pct2(n: number | null): string {
  return n == null ? "—" : `${Number(n.toFixed(2))}%`;
}

// ── per-axis summary (over each exposure table) ──────────────────────────

/** Verdict line, then Largest / Effective N / HHI, in one card. */
export function AxisSummary({ lens }: { lens: Lens }) {
  const verdict = lens.verdict ? VERDICT_META[lens.verdict] : null;
  const tone: Tone = lens.verdict === "over-concentrated" ? "danger" : lens.verdict === "elevated" ? "amber" : "ink";
  const stats: Array<{ id: string; k: string; v: string; s: string; tone: Tone }> = [
    { id: "largest", k: `Largest ${inline(lens)}`, v: fmtPct(lens.largestPct), s: lens.largestName || "—", tone },
    { id: "effective-n", k: "Effective N", v: fmtNum(lens.effectiveN, 1), s: "distinct bets", tone },
    { id: "hhi", k: "HHI", v: fmtNum(lens.hhi), s: "Herfindahl index", tone: "ink" },
  ];
  return (
    <div data-testid={`analysis-${lens.id}-summary`} className="cp-card flex flex-col" style={{ gap: 12, padding: "14px 16px" }}>
      {verdict && (
        <div data-testid={`analysis-${lens.id}-verdict`} className="flex flex-wrap items-start" style={{ gap: "8px 12px" }}>
          <Pill tone={verdict.tone}>{verdict.label}</Pill>
          {lens.verdict === "balanced" ? (
            <span style={{ flex: "1 1 240px", fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
              All {inline(lens)} exposures within policy caps. Effective N {fmtNum(lens.effectiveN, 1)}.
            </span>
          ) : (
            <ul className="m-0 flex flex-col" style={{ flex: "1 1 240px", gap: 4, padding: 0, listStyle: "none", fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
              {lens.reasons.map((r) => <li key={r}>{r}</li>)}
            </ul>
          )}
        </div>
      )}
      <div className="flex flex-wrap" style={{ gap: "10px 28px" }}>
        {stats.map((s) => (
          <span key={s.id} className="flex flex-col" style={{ gap: 3 }}>
            <span className="cp-eyebrow">{s.k}</span>
            <span className="flex flex-wrap items-baseline" style={{ gap: 8 }}>
              <span data-testid={`analysis-${lens.id}-${s.id}`} className="cp-num" style={{ fontSize: 18, color: TONE_COLOR[s.tone] }}>{s.v}</span>
              <span data-testid={s.id === "largest" ? `analysis-${lens.id}-largest-name` : undefined} style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>{s.s}</span>
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}

/** One "allocation vs cap" cell: the share, where it stands against the cap, and a bar with the cap marked. */
export function CapCell({ item, scale }: { item: LensItem | undefined; scale: number }) {
  if (!item) return <>—</>;
  const status = capStatus(item);
  const text = capStatusText(item);
  const barTone: Tone = status === "over" ? "danger" : status === "approaching" ? "amber" : status === "residual" ? "ink" : "indigo";
  return (
    <span style={{ display: "block" }}>
      {fmtPct(item.pct)}
      <span style={{ marginLeft: 8, fontSize: 11, color: text.tone === "ink" ? "var(--cp-ink-3)" : TONE_COLOR[text.tone] }}>{text.text}</span>
      <span style={{ display: "block", marginTop: 5 }}>
        <ShareBar pct={item.pct} max={scale} tone={barTone} markPct={item.capPct} dim={status === "residual"} />
      </span>
    </span>
  );
}

/** Under an exposure table: what the share is a share of, the cap, the top-3 share and (when sent) the coverage. */
export function AxisFooter({ lens }: { lens: Lens }) {
  return (
    <div className="flex flex-col" style={{ gap: 4, padding: "10px 16px 12px" }}>
      <span style={quiet}>
        Allocation vs cap is each {inline(lens)}’s share {lens.basis}.
        {lens.capPct != null && <> Cap · <span data-testid={`analysis-${lens.id}-cap`}>{lens.capPct}%</span> per {inline(lens)}.</>}
      </span>
      {lens.top3Pct != null && (
        <span style={quiet}>
          Top-3 {lens.plural} hold <span data-testid={`analysis-${lens.id}-top3`} style={{ color: "var(--cp-ink)" }}>{lens.top3Pct}%</span> {lens.basis}.
        </span>
      )}
      {lens.coveragePct != null && (
        <span style={quiet}>
          Classification coverage · <span data-testid={`analysis-${lens.id}-coverage`} style={{ color: lens.coveragePct < 80 ? "var(--amber)" : "var(--cp-ink-2)" }}>{lens.coveragePct}%</span>
        </span>
      )}
    </div>
  );
}

// ── AMC and Group tables ─────────────────────────────────────────────────

interface AxisRow {
  name: string;
  valueRs: number | null;
  /** Funds with the AMC, or companies in the group. */
  count: number | null;
  item: LensItem | undefined;
}

const AXIS_TABLE = {
  amc: {
    title: "AMCs · share of your fund holdings",
    name: "AMC",
    count: "Funds",
    emptyTitle: "No fund houses to show",
    emptyBody: "AMC exposure appears once this portfolio holds mutual funds or ETFs.",
    question: (r: AxisRow) => `Is ${fmtPct(r.item?.pct)} of my fund money with ${r.name} too much, and which ${r.name} funds would you trim first?`,
  },
  group: {
    title: "Groups · share of your exposure to business groups",
    name: "Group",
    count: "Companies",
    emptyTitle: "No business groups identified",
    emptyBody: "None of the companies you are exposed to belongs to a business group Nivesh tracks.",
    question: (r: AxisRow) => `Which of my holdings give me exposure to ${r.name}, and is ${fmtPct(r.item?.pct)} of my group exposure in it too concentrated?`,
  },
} as const;

/** The AMC or the Group axis: summary, then one row per name against the cap. */
export function AxisTable({ axis }: { axis: "amc" | "group" }) {
  const { ask } = useCopilotShell();
  const q = usePortfolioConcentration();
  const copy = AXIS_TABLE[axis];
  if (q.isPending) return <LoadingBlock label={`Loading ${copy.name} exposure`} rows={5} />;
  if (q.isError) return <ErrorBlock title={`${copy.name} exposure didn’t load`} error={loadError(q.error)} onRetry={() => q.refetch()} />;
  const section = q.data[axis];
  const lens = lensOf(readConcentration(q.data), axis);
  if (!section || !lens) {
    if (q.data.empty === true) return <EmptyBlock title={copy.emptyTitle} body={copy.emptyBody} />;
    return <ErrorBlock title={`${copy.name} exposure didn’t load`} error={BAD_SHAPE} onRetry={() => q.refetch()} />;
  }

  const rows: AxisRow[] = (section.items ?? []).map((it, i) => ({
    name: it.name,
    valueRs: num(it.value_inr),
    count: axis === "amc" ? num(it.count) : num(it.company_count),
    item: lens.items[i],
  }));
  if (!rows.length) return <EmptyBlock title={copy.emptyTitle} body={copy.emptyBody} />;

  const scale = capScale(lens);
  const all = num(section.all_items_count);
  const columns: Array<Column<AxisRow>> = [
    {
      key: "name", header: copy.name, width: "minmax(0,1.5fr)",
      render: (r) => (
        <span className="flex items-center" style={{ gap: 10, minWidth: 0 }}>
          {axis === "amc" && <FundHouseIcon name={r.name} size={24} />}
          <span data-testid={`analysis-${axis}-name`} title={r.name} style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", color: "var(--cp-ink)", fontWeight: 500 }}>{r.name}</span>
        </span>
      ),
    },
    { key: "cap", header: "Allocation vs cap", width: "minmax(0,1.5fr)", num: true, render: (r) => <CapCell item={r.item} scale={scale} /> },
    { key: "value", header: "Value", num: true, render: (r) => fmtINR(r.valueRs, { compact: true }) },
    { key: "count", header: copy.count, num: true, render: (r) => fmtNum(r.count) },
  ];
  return (
    <div className="flex flex-col" style={{ gap: 12 }}>
      <AxisSummary lens={lens} />
      <Section flush title={copy.title} note={all != null && all > rows.length ? `Top ${rows.length} of ${all}` : undefined}>
        <DataTable columns={columns} rows={rows} rowKey={(r) => r.name} minWidth={520} onRowClick={(r) => ask(copy.question(r))} />
        <AxisFooter lens={lens} />
      </Section>
    </div>
  );
}

// ── headline, verdict and the ladder ─────────────────────────────────────

function Ladder({ read, onOpenAxis }: { read: ConcentrationRead; onOpenAxis: (axis: AxisId) => void }) {
  const { mobile } = useCopilotShell();
  const maxN = Math.max(...read.ladder.map((r) => r.effectiveN), 1);
  return (
    <Section title="Concentration ladder" note="Higher = more diversified">
      <div className="flex flex-col" style={{ gap: 14 }}>
        <span style={quiet}>Effective N at each aggregation level — the same ₹ looks more or less diversified depending on how you count.</span>
        {read.ladder.map(({ lens, effectiveN }) => {
          const verdict = lens.verdict ? VERDICT_META[lens.verdict] : null;
          const open = (
            <button type="button" onClick={() => onOpenAxis(lens.id)} style={{ fontSize: 12, color: "var(--cp-ink-2)", background: "none", border: 0, padding: 0, cursor: "pointer", whiteSpace: "nowrap" }}>
              See {lens.plural} ›
            </button>
          );
          const pill = verdict && <span data-testid={`analysis-ladder-${lens.id}-verdict`}><Pill tone={verdict.tone}>{verdict.label}</Pill></span>;
          return (
            <div key={lens.id} data-testid="analysis-ladder-row" className="flex flex-col" style={{ gap: 6 }}>
              <div className="grid items-center" style={{ gridTemplateColumns: mobile ? "64px minmax(0,1fr) 48px" : "90px minmax(0,1fr) 56px 150px 110px", gap: 12 }}>
                <span style={{ fontSize: 13, color: "var(--cp-ink-2)", fontWeight: 500 }}>{lens.label}</span>
                <ShareBar pct={effectiveN} max={maxN} tone={verdict?.tone ?? "indigo"} />
                <span data-testid={`analysis-ladder-${lens.id}-n`} className="cp-num" style={{ fontSize: 13, textAlign: "right" }}>{effectiveN.toFixed(1)}</span>
                {!mobile && <span>{pill}</span>}
                {!mobile && <span style={{ textAlign: "right" }}>{open}</span>}
              </div>
              {mobile && <div className="flex flex-wrap items-center justify-between" style={{ gap: 8 }}>{pill}{open}</div>}
            </div>
          );
        })}
        <span style={{ ...quiet, paddingTop: 10, borderTop: "1px solid var(--cp-line)" }}>
          Effective N = 1 / HHI. A portfolio split evenly across 10 funds has Effective N 10; one with 75% in a single name has Effective N ≈ 1.8.
        </span>
      </div>
    </Section>
  );
}

function Headline({ read }: { read: ConcentrationRead }) {
  const { mobile } = useCopilotShell();
  const verdict = read.verdict ? VERDICT_META[read.verdict] : null;
  if (!read.headline) return null;
  return (
    <div className="flex flex-wrap items-start justify-between" style={{ gap: 12 }}>
      <span data-testid="analysis-concentration-headline" className="cp-pretty" style={{ flex: "1 1 320px", fontFamily: "var(--display)", fontSize: mobile ? 22 : 28, lineHeight: 1.2 }}>
        {read.headline.spread} — <span style={{ color: verdict ? TONE_COLOR[verdict.tone] : undefined }}>{read.headline.concentrated}</span>
      </span>
      {verdict && (
        <span data-testid="analysis-concentration-verdict">
          <Pill tone={verdict.tone}>{[verdict.label, read.drivers.join(" + ")].filter(Boolean).join(" · ")}</Pill>
        </span>
      )}
    </div>
  );
}

// ── fund overlap ─────────────────────────────────────────────────────────

const PAIR_LIMIT = 10;

function PairRow({ pair }: { pair: FundPair }) {
  const { ask } = useCopilotShell();
  const meta = PAIR_META[pair.kind];
  return (
    <div data-testid="analysis-overlap-pair" className="flex flex-col" style={{ gap: 8, padding: "12px 16px", borderBottom: "1px solid var(--cp-line)" }}>
      <div className="flex flex-wrap items-center" style={{ gap: "6px 12px" }}>
        <span className="flex flex-wrap items-center" style={{ flex: "1 1 260px", minWidth: 0, gap: "6px 10px", fontSize: 13, lineHeight: 1.45 }}>
          <span className="flex items-center" style={{ gap: 8, minWidth: 0 }}>
            <FundHouseIcon name={pair.fundA} size={22} />
            <span data-testid="analysis-overlap-fund-a" style={{ minWidth: 0, overflowWrap: "anywhere", color: "var(--cp-ink)", fontWeight: 500 }}>{pair.fundA}</span>
          </span>
          <span aria-hidden="true" style={{ color: "var(--cp-ink-3)" }}>↔</span>
          <span className="flex items-center" style={{ gap: 8, minWidth: 0 }}>
            <FundHouseIcon name={pair.fundB} size={22} />
            <span data-testid="analysis-overlap-fund-b" style={{ minWidth: 0, overflowWrap: "anywhere", color: "var(--cp-ink-2)" }}>{pair.fundB}</span>
          </span>
        </span>
        <Pill tone={meta.tone}>{meta.label}</Pill>
        <span data-testid="analysis-overlap-pct" className="cp-num" style={{ fontSize: 15, minWidth: 64, textAlign: "right" }}>{pct2(pair.overlapPct)}</span>
      </div>
      <ShareBar pct={pair.overlapPct} tone={meta.tone} />
      <div className="flex flex-wrap items-center" style={{ gap: 6 }}>
        {pair.topShared.length > 0 && <span style={{ fontSize: 11, color: "var(--cp-ink-3)" }}>Both hold:</span>}
        {pair.topShared.map((s) => (
          <span key={s.name} data-testid="analysis-overlap-shared" className="inline-flex items-center" style={{ gap: 5, fontSize: 11, padding: "2px 7px 2px 3px", borderRadius: 6, background: "var(--bg-2)", border: "1px solid var(--cp-line)", color: "var(--cp-ink-2)" }}>
            <HoldingIcon name={s.name} assetType="equity" size={16} />
            {s.name}
            {(s.weightA != null || s.weightB != null) && <span style={{ color: "var(--cp-ink-3)" }}> {s.weightA ?? "—"}/{s.weightB ?? "—"}%</span>}
          </span>
        ))}
        {pair.sharedCount != null && <span style={{ fontSize: 11, color: "var(--cp-ink-3)" }}>{fmtNum(pair.sharedCount)} shared {pair.sharedCount === 1 ? "stock" : "stocks"}</span>}
        <button
          type="button"
          onClick={() => ask(`${pair.fundA} and ${pair.fundB} overlap ${pct2(pair.overlapPct)} in my portfolio. Which one should I keep, and what would moving out of the other cost me in tax and exit load?`)}
          style={{ marginLeft: "auto", fontSize: 12, color: "var(--mint)", background: "none", border: 0, padding: 0, cursor: "pointer" }}
        >
          Ask which to keep ›
        </button>
      </div>
    </div>
  );
}

function OverlapPanel() {
  const { go } = useCopilotShell();
  const [expanded, setExpanded] = useState(false);
  const q = useConcentrationAnalysis();
  if (q.isPending) return <LoadingBlock label="Loading fund overlap" rows={4} />;
  if (q.isError) return <ErrorBlock title="Fund overlap didn’t load" error={loadError(q.error)} onRetry={() => q.refetch()} />;
  // The shared hook hands over the raw matrix payload, and null when that request failed.
  const read = readOverlap(q.data.overlap);
  if (!read) return <ErrorBlock title="Fund overlap didn’t load" error={BAD_SHAPE} onRetry={() => q.refetch()} />;
  if (!read.pairs.length) {
    return (
      <EmptyBlock
        title="No fund overlap to show"
        body={read.fundCount < 2
          ? "Overlap needs at least two funds whose portfolios are on record."
          : "None of your fund pairs came back with an overlap figure."}
      />
    );
  }
  const high = read.pairs.filter((p) => p.overlapPct >= 65).length;
  return (
    <Section flush title="Fund overlap · pairs that hold the same stocks" note={`${read.pairs.length} ${read.pairs.length === 1 ? "pair" : "pairs"} · highest first`}>
      {high > 0 && (
        <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--cp-line)", fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
          <span data-testid="analysis-overlap-high">{high}</span> of these {high === 1 ? "pairs overlaps" : "pairs overlap"} 65% or more. Those funds largely hold the same stocks and move together, so one of each pair adds fees without adding diversification.
        </div>
      )}
      {(expanded ? read.pairs : read.pairs.slice(0, PAIR_LIMIT)).map((p) => <PairRow key={`${p.fundA}|${p.fundB}`} pair={p} />)}
      <ShowAll total={read.pairs.length} limit={PAIR_LIMIT} expanded={expanded} onToggle={() => setExpanded((v) => !v)} noun="pairs" />
      <div className="flex flex-col items-start" style={{ gap: 8, padding: "12px 16px" }}>
        <span style={quiet}>
          Overlap = Σ min(weight A, weight B) across shared holdings, computed over full disclosed portfolios. Near-duplicate = 90% or more (what the Regular and Direct plans of one scheme, or two funds on the same index, look like) · Redundant = 65% or more · Related = 35% or more · Diversifying = under 35%.
          {read.coveragePct != null && <> Fund portfolios are on record for <span data-testid="analysis-overlap-coverage">{fmtPct(read.coveragePct)}</span> of your fund value.</>}
        </span>
        <Btn onClick={() => go("tool/recommend")}>See consolidation plan ›</Btn>
      </div>
    </Section>
  );
}

// ── section ──────────────────────────────────────────────────────────────

function Summary({ data, onOpenAxis, onRetry }: { data: ConcentrationBreakdownC; onOpenAxis: (axis: AxisId) => void; onRetry: () => void }) {
  const read = readConcentration(data);
  if (read.lenses.length === 0 && data.empty !== true) return <ErrorBlock title="Concentration didn’t load" error={BAD_SHAPE} onRetry={onRetry} />;
  if (read.ladder.length === 0) return <EmptyBlock title="No concentration figures yet" body="Effective N appears once your holdings are priced and classified." />;
  return (
    <>
      <Headline read={read} />
      <Ladder read={read} onOpenAxis={onOpenAxis} />
    </>
  );
}

/** `onOpenAxis` shows an axis's table (Overview → Sectors / Companies / AMCs / Groups). */
export function ConcentrationSection({ onOpenAxis }: { onOpenAxis: (axis: AxisId) => void }) {
  const q = usePortfolioConcentration();
  return (
    <div data-testid="analysis-concentration" className="flex flex-col" style={{ gap: 16 }}>
      {q.isPending ? (
        <LoadingBlock label="Loading concentration" rows={4} />
      ) : q.isError ? (
        <ErrorBlock title="Concentration didn’t load" error={loadError(q.error)} onRetry={() => q.refetch()} />
      ) : (
        <Summary data={q.data} onOpenAxis={onOpenAxis} onRetry={() => q.refetch()} />
      )}
      <OverlapPanel />
    </div>
  );
}
