/**
 * Smart trading desk · Historical Smart Money Movement — presentation.
 *
 * One panel: for the latest disclosed quarter, each Nifty-500 name's FII/DII percentage-point
 * ownership change beside that SAME quarter's price return, volume ratio and delivery shift, with
 * the four views the desk asked for — all disclosed, institutions reduced, institutions raised, and
 * ownership-vs-price divergence.
 *
 * Everything shown comes from ownership-reaction-data.ts, which forwards the data platform's
 * figures unchanged. This file formats and lays out; it derives nothing and asserts nothing the
 * server did not measure.
 *
 * The honesty rules this component is responsible for keeping true on screen:
 *   * The header says, in words, that this explains the past and does not predict. The panel never
 *     uses signal/buy/sell wording, and the retrospective note is not dismissible.
 *   * The measured cut-points are PRINTED (`thresholdLine`), so a "Negative" label can be checked
 *     against the numbers that produced it. They are percentiles of this quarter's own
 *     cross-section, never invented round numbers.
 *   * The real denominator is printed (`denominatorLine`): 89 of 500, with the single-publisher and
 *     two-publisher split called out. Never "out of 500".
 *   * An absent figure reads "not disclosed", never 0 and never as something positive. A row whose
 *     tape could not be measured reads "not measurable" and carries no reaction label.
 *   * A contested FII change is marked, and one whose source disagreement is as large as the change
 *     itself prints "sources differ" instead of a number.
 *   * No score, no rank-by-score. Sorting is by a measured column the user picks, and the
 *     "not scored" pill is driven by the live `validatedStudy` read, not a hardcoded string.
 */
import { useState } from "react";
import {
  Column, DataTable, EmptyBlock, ErrorBlock, Footnote, LoadingBlock, Pill, Section,
} from "../../components/ui";
import {
  OR_LIMIT, OR_RETROSPECTIVE_NOTE, OR_SORTS, OR_SPLIT_CAVEAT, OR_STATUS_LABEL, OR_STATUS_NOTE,
  OR_STATUS_ORDER, OR_STATUS_TONE, OR_VIEWS, REACTION_LABEL, REACTION_NOTE,
  cohortThresholdLine, coverageBanner, denominatorLine, emptyStateLine, fiiFigure, filingLine,
  fmtOrNotDisclosed, fmtSignedPct, fmtSignedPp, reconciles, reconciliationLine, thresholdLine,
  trendAvailable, trustNote, useOwnershipReaction,
  type OrRow, type OrSort, type OrStatus, type OrView, type Reaction,
} from "./ownership-reaction-data";

function Chips<T extends string>({ items, value, onPick, idPrefix, label }: {
  items: ReadonlyArray<{ id: T; label: string }>;
  value: T; onPick: (v: T) => void; idPrefix: string; label: string;
}) {
  return (
    <span role="tablist" aria-label={label} className="flex flex-wrap" style={{ gap: 4 }}>
      {items.map((it) => {
        const on = it.id === value;
        return (
          <button
            key={it.id} type="button" role="tab" aria-selected={on}
            data-testid={`${idPrefix}-${it.id}`}
            onClick={() => onPick(it.id)}
            className="cp-num"
            style={{
              padding: "3px 9px", borderRadius: 999, fontSize: 11, cursor: "pointer", whiteSpace: "nowrap",
              border: `1px solid ${on ? "var(--mint)" : "var(--cp-line)"}`,
              background: on ? "var(--mint-soft)" : "transparent",
              color: on ? "var(--cp-ink)" : "var(--cp-ink-3)",
            }}
          >{it.label}</button>
        );
      })}
    </span>
  );
}

/**
 * Status colours. ONLY `risk` is red, and only Distribution Risk maps to it. Reversal Watch is
 * amber: it describes institutions ADDING into weakness, which is a watch item and not a risk —
 * colouring it red would invert what it means.
 */
const STATUS_CSS: Record<"positive" | "watch" | "risk" | "muted", { bg: string; line: string; fg: string }> = {
  positive: { bg: "var(--mint-soft)", line: "var(--mint)", fg: "var(--cp-ink)" },
  watch: { bg: "var(--amber-soft)", line: "var(--amber)", fg: "var(--cp-ink)" },
  risk: { bg: "var(--danger-soft)", line: "var(--danger-hex)", fg: "var(--cp-ink)" },
  muted: { bg: "transparent", line: "var(--cp-line)", fg: "var(--cp-ink-3)" },
};

function StatusCell({ row }: { row: OrRow }) {
  const st = row.status;
  if (!st) return <span style={{ fontSize: 11, color: "var(--cp-ink-4)" }}>—</span>;
  const css = STATUS_CSS[OR_STATUS_TONE[st]];
  return (
    <span className="flex flex-col" style={{ gap: 2 }}>
      <span
        data-testid={`or-status-${row.symbol}`}
        data-status={st}
        title={`${OR_STATUS_NOTE[st]}${row.statusReason ? `\n\nFor this row: ${row.statusReason}` : ""}`}
        style={{
          alignSelf: "flex-start", padding: "2px 7px", borderRadius: 999, fontSize: 11,
          border: `1px solid ${css.line}`, background: css.bg, color: css.fg, whiteSpace: "nowrap",
        }}
      >{OR_STATUS_LABEL[st]}</span>
      {!trendAvailable(row) && (
        <span data-testid={`or-no-trend-${row.symbol}`} style={{ fontSize: 10, color: "var(--cp-ink-4)" }}>
          {row.quartersAvailable ?? 0} quarter{(row.quartersAvailable ?? 0) === 1 ? "" : "s"} disclosed — no trend
        </span>
      )}
    </span>
  );
}

const REACTION_TONE: Record<Reaction, { fg: string; bg: string; line: string }> = {
  strong_positive: { fg: "var(--cp-ink)", bg: "var(--mint-soft)", line: "var(--mint)" },
  neutral: { fg: "var(--cp-ink-2)", bg: "transparent", line: "var(--cp-line)" },
  negative: { fg: "var(--cp-ink)", bg: "var(--rose-soft, var(--amber-soft))", line: "var(--rose, var(--amber))" },
};

/** The label, plus the two bands that produced it, so the word is always checkable. */
function ReactionCell({ row }: { row: OrRow }) {
  if (!row.priceLegsPresent || !row.reaction) {
    return (
      <span data-testid={`or-reaction-${row.symbol}`} style={{ fontSize: 11.5, color: "var(--cp-ink-4)" }}
        title={row.reactionNote ?? undefined}>
        not measurable
      </span>
    );
  }
  const t = REACTION_TONE[row.reaction];
  return (
    <span className="flex flex-col" style={{ gap: 2 }}>
      <span
        data-testid={`or-reaction-${row.symbol}`}
        title={REACTION_NOTE[row.reaction]}
        style={{
          alignSelf: "flex-start", padding: "2px 7px", borderRadius: 999, fontSize: 11,
          border: `1px solid ${t.line}`, background: t.bg, color: t.fg, whiteSpace: "nowrap",
        }}
      >{REACTION_LABEL[row.reaction]}</span>
      {row.reactionCorroborated === false && row.reactionNote && (
        <span data-testid={`or-uncorroborated-${row.symbol}`}
          style={{ fontSize: 10.5, lineHeight: 1.4, color: "var(--cp-ink-4)" }}>
          one leg only — volume did not confirm
        </span>
      )}
    </span>
  );
}

/** The FII change, with "sources differ" in place of a number where the sources swamp it. */
function FiiCell({ row }: { row: OrRow }) {
  const { text, trust } = fiiFigure(row);
  const note = trustNote(row);
  return (
    <span className="flex flex-col" style={{ gap: 1 }}>
      <span
        data-testid={`or-fii-${row.symbol}`}
        className={trust === "unusable" ? undefined : "cp-num"}
        title={note ?? undefined}
        style={{
          fontSize: trust === "unusable" ? 11 : 12.5,
          color: trust === "unusable" ? "var(--amber)" : "var(--cp-ink)",
          fontStyle: trust === "unusable" ? "italic" : undefined,
        }}
      >{text}</span>
      {trust === "contested" && (
        <span data-testid={`or-contested-${row.symbol}`} title={note ?? undefined}
          style={{ fontSize: 10, color: "var(--amber)" }}>
          {row.deltaBasis === "cross_source" ? "two publishers" : "contested"}
        </span>
      )}
    </span>
  );
}

export default function OwnershipReactionPanel() {
  const [view, setView] = useState<OrView>("reduced");
  const [sort, setSort] = useState<OrSort>("inst_delta");
  const [sameSourceOnly, setSameSourceOnly] = useState(false);
  const [status, setStatus] = useState<OrStatus | "any">("any");

  const q = useOwnershipReaction(true, { view, sort, sameSourceOnly, status });
  const feed = q.data ?? null;
  const rows = feed?.rows ?? [];
  const t = feed?.thresholds ?? null;
  const counts = feed?.counts ?? null;

  const columns: Column<OrRow>[] = [
    {
      key: "symbol", header: "Stock", width: "minmax(0,1.25fr)",
      render: (r) => (
        <span className="flex flex-col" style={{ gap: 1 }}>
          <span style={{ fontWeight: 600, fontSize: 12.5 }}>{r.symbol}</span>
          <span style={{ fontSize: 10.5, color: "var(--cp-ink-4)" }}>{r.industry ?? "sector not mapped"}</span>
        </span>
      ),
    },
    {
      key: "status", header: "Status", width: "minmax(0,1.15fr)",
      render: (r) => <StatusCell row={r} />,
    },
    {
      key: "fii", header: "FII change", width: "minmax(0,0.95fr)", align: "right",
      render: (r) => <FiiCell row={r} />,
    },
    {
      key: "dii", header: "DII change", width: "minmax(0,0.85fr)", align: "right", num: true,
      render: (r) => <span data-testid={`or-dii-${r.symbol}`}>{fmtSignedPp(r.diiDeltaPp)}</span>,
    },
    {
      key: "inst", header: "FII+DII", width: "minmax(0,0.8fr)", align: "right", num: true,
      render: (r) => (
        <span data-testid={`or-inst-${r.symbol}`}
          style={{ fontWeight: 600, color: r.instDeltaPp == null ? "var(--cp-ink-4)" : undefined }}>
          {fmtSignedPp(r.instDeltaPp)}
        </span>
      ),
    },
    {
      key: "split", header: "MF / Banks-FI level", width: "minmax(0,1fr)", align: "right",
      render: (r) => (
        <span className="cp-num flex flex-col" data-testid={`or-split-${r.symbol}`} style={{ gap: 1, fontSize: 11.5 }}>
          <span style={{ color: r.mfPct == null ? "var(--cp-ink-4)" : undefined }}>
            MF {fmtOrNotDisclosed(r.mfPct, "%")}
          </span>
          <span style={{ color: "var(--cp-ink-4)", fontSize: 10.5 }}>
            Banks/FI {fmtOrNotDisclosed(r.bankFiPct, "%")}
          </span>
        </span>
      ),
    },
    {
      key: "ret", header: "Quarter return", width: "minmax(0,0.95fr)", align: "right", num: true,
      render: (r) => (
        <span className="flex flex-col" data-testid={`or-ret-${r.symbol}`} style={{ gap: 1 }}>
          <span style={{ color: r.retPct == null ? "var(--cp-ink-4)" : undefined }}>
            {fmtSignedPct(r.retPct)}
          </span>
          {r.retPercentile != null && (
            <span style={{ fontSize: 10, color: "var(--cp-ink-4)" }}
              title="Position within the peer cross-section over the identical window. Not excess return over an index.">
              {r.retPercentile.toFixed(0)}th in cohort
            </span>
          )}
        </span>
      ),
    },
    {
      key: "vol", header: "Volume vs prior Q", width: "minmax(0,0.9fr)", align: "right", num: true,
      render: (r) => (
        <span data-testid={`or-vol-${r.symbol}`}
          style={{ color: r.volRatio == null ? "var(--cp-ink-4)" : undefined }}>
          {r.volRatio == null ? "not measurable" : `${r.volRatio.toFixed(3)}×`}
        </span>
      ),
    },
    {
      key: "dlv", header: "Delivery shift", width: "minmax(0,0.8fr)", align: "right", num: true,
      render: (r) => (
        <span data-testid={`or-dlv-${r.symbol}`}
          style={{ color: r.delivShiftPp == null ? "var(--cp-ink-4)" : undefined }}>
          {r.delivShiftPp == null ? "not disclosed" : fmtSignedPp(r.delivShiftPp)}
        </span>
      ),
    },
    {
      key: "reaction", header: "Price + volume reaction", width: "minmax(0,1.1fr)",
      render: (r) => <ReactionCell row={r} />,
    },
    {
      key: "fiftytwo", header: "From 52w high / low", width: "minmax(0,0.95fr)", align: "right", num: true,
      render: (r) => (
        <span className="flex flex-col" data-testid={`or-52w-${r.symbol}`} style={{ gap: 1, fontSize: 11.5 }}>
          <span style={{ color: r.dist52wHighPct == null ? "var(--cp-ink-4)" : undefined }}>
            {r.dist52wHighPct == null ? "not disclosed" : `${r.dist52wHighPct.toFixed(2)}%`}
          </span>
          <span style={{ fontSize: 10.5, color: "var(--cp-ink-4)" }}>
            {r.dist52wLowPct == null ? "" : `+${r.dist52wLowPct.toFixed(2)}% over low`}
          </span>
        </span>
      ),
    },
    {
      key: "filed", header: "Filed with NSE", width: "minmax(0,0.95fr)",
      render: (r) => {
        const f = filingLine(r);
        if (!f) {
          return (
            <span data-testid={`or-filed-${r.symbol}`} style={{ fontSize: 11, color: "var(--cp-ink-4)" }}>
              not recorded
            </span>
          );
        }
        return (
          <span className="flex flex-col" data-testid={`or-filed-${r.symbol}`} style={{ gap: 1 }}>
            <span className="cp-num" style={{ fontSize: 11.5 }}>{f.date}</span>
            <span style={{ fontSize: 10, color: "var(--cp-ink-4)" }}
              title="The real NSE publication timestamp, not an estimate. The quarter had already ended when this was filed.">
              {f.afterClose ? "after close — next session" : "during session"}
            </span>
          </span>
        );
      },
    },
    {
      key: "basis", header: "Measured from", width: "minmax(0,1fr)",
      render: (r) => (
        <span className="flex flex-col" data-testid={`or-basis-${r.symbol}`} style={{ gap: 1, fontSize: 10.5 }}>
          <span style={{ color: r.deltaBasis === "cross_source" ? "var(--amber)" : "var(--cp-ink-3)" }}>
            {r.deltaBasis === "same_source" ? "one publisher" : r.deltaBasis === "cross_source" ? "two publishers" : "unknown"}
          </span>
          <span style={{ color: "var(--cp-ink-4)" }}>{r.deltaSource ?? "source not named"}</span>
          {r.deltaAltPp != null && (
            <span style={{ color: "var(--cp-ink-4)" }}
              title="The same change measured on the other basis. A large gap means the apparent change is mostly a publisher difference.">
              other basis {fmtSignedPp(r.deltaAltPp)}
            </span>
          )}
        </span>
      ),
    },
  ];

  const threshold = thresholdLine(t);
  const cohortLine = cohortThresholdLine(feed?.cohortThresholds ?? null);
  const denominator = denominatorLine(feed?.coverage ?? null);
  const byStatus = counts?.byStatus ?? {};
  const banner = coverageBanner(feed?.coverage ?? null);
  const reconcile = reconciliationLine(counts);
  const reconcileOk = reconciles(counts);

  return (
    <Section
      title="Historical Smart Money Movement"
      note={
        <span className="flex flex-wrap items-center" style={{ gap: 6 }}>
          <Pill tone="amber" title="This panel describes a quarter that has already finished. It is not predictive and not a recommendation.">
            Retrospective · explains the past
          </Pill>
          {feed?.asOf && (
            <Pill tone="ink" title="The disclosed quarter this panel describes, against the quarter before it">
              Quarter ended {feed.asOf} vs {feed.previousPeriod ?? "prior quarter"}
            </Pill>
          )}
          {feed && !feed.validatedStudy && (
            <Pill tone="amber" title="No promotion decision is on record, so nothing here is scored or ranked by a model">
              Evidence only · not scored
            </Pill>
          )}
        </span>
      }
    >
      <div className="flex flex-col" data-testid="or-panel" style={{ gap: 14 }}>
        {/* The non-negotiable framing, always visible and never dismissible. */}
        <p data-testid="or-retrospective-note" role="note"
          style={{
            margin: 0, padding: "10px 13px", borderRadius: 9, border: "1px solid var(--cp-line)",
            background: "var(--bg-2)", fontSize: 12.5, lineHeight: 1.6, color: "var(--cp-ink-2)",
          }}>
          {OR_RETROSPECTIVE_NOTE}
        </p>

        {/* Coverage, stated prominently: every figure here rests on the eligible cohort, not the index. */}
        {banner && (
          <p data-testid="or-coverage-banner" role="note"
            style={{
              margin: 0, padding: "10px 13px", borderRadius: 9,
              border: "1px solid var(--amber)", background: "var(--amber-soft)",
              fontSize: 12.5, lineHeight: 1.6, color: "var(--cp-ink-2)",
            }}>
            {banner}
          </p>
        )}

        <div className="flex flex-wrap items-center" style={{ gap: 10 }}>
          <Chips items={OR_VIEWS} value={view} onPick={setView} idPrefix="or-view" label="View" />
          <span style={{ fontSize: 11, color: "var(--cp-ink-4)" }}>sort</span>
          <Chips items={OR_SORTS} value={sort} onPick={setSort} idPrefix="or-sort" label="Sort by" />
          <label className="flex items-center" style={{ gap: 5, fontSize: 11, color: "var(--cp-ink-3)", cursor: "pointer" }}>
            <input
              type="checkbox" data-testid="or-same-source-only"
              checked={sameSourceOnly} onChange={(e) => setSameSourceOnly(e.target.checked)}
            />
            <span title="Drop rows whose change is computed by differencing two publishers, which can turn a methodology difference into an apparent ownership change">
              single-publisher changes only
            </span>
          </label>
        </div>

        {/* Status filter. Each chip carries its own count, so an honest 0 is visible up front. */}
        <div className="flex flex-wrap items-center" data-testid="or-status-filter" style={{ gap: 4 }}>
          <span style={{ fontSize: 11, color: "var(--cp-ink-4)", marginRight: 4 }}>status</span>
          {(["any", ...OR_STATUS_ORDER] as Array<OrStatus | "any">).map((id) => {
            const on = id === status;
            const n = id === "any" ? (counts?.cohort ?? null) : (byStatus[id as OrStatus] ?? 0);
            return (
              <button
                key={id} type="button" data-testid={`or-status-pick-${id}`}
                aria-pressed={on} onClick={() => setStatus(id)}
                title={id === "any" ? "Every name with a computable change" : OR_STATUS_NOTE[id as OrStatus]}
                className="cp-num"
                style={{
                  padding: "3px 9px", borderRadius: 999, fontSize: 11, cursor: "pointer", whiteSpace: "nowrap",
                  border: `1px solid ${on ? "var(--mint)" : "var(--cp-line)"}`,
                  background: on ? "var(--mint-soft)" : "transparent",
                  color: on ? "var(--cp-ink)" : "var(--cp-ink-3)",
                }}
              >
                {id === "any" ? "Any" : OR_STATUS_LABEL[id as OrStatus]}{n == null ? "" : ` ${n}`}
              </button>
            );
          })}
        </div>

        {/* Measured cut-points and the real denominator, both printed rather than asserted. */}
        {(threshold || denominator) && (
          <div className="flex flex-col" data-testid="or-thresholds" style={{ gap: 4 }}>
            {cohortLine && (
              <span data-testid="or-cohort-thresholds" style={{ fontSize: 11.5, lineHeight: 1.55, color: "var(--cp-ink-3)" }}>
                {cohortLine}
              </span>
            )}
            {threshold && <span style={{ fontSize: 11.5, lineHeight: 1.55, color: "var(--cp-ink-3)" }}>{threshold}</span>}
            {t?.note && <span style={{ fontSize: 11, lineHeight: 1.55, color: "var(--cp-ink-4)" }}>{t.note}</span>}
            {denominator && (
              <span data-testid="or-denominator" style={{ fontSize: 11.5, lineHeight: 1.55, color: "var(--cp-ink-3)" }}>
                {denominator}
              </span>
            )}
          </div>
        )}

        {counts && (
          <div className="flex flex-wrap" data-testid="or-counts" style={{ gap: 12, fontSize: 11, color: "var(--cp-ink-3)" }}>
            <span>{counts.reduced ?? 0} reduced</span>
            <span>{counts.raised ?? 0} raised</span>
            <span>{counts.divergence ?? 0} diverged</span>
            <span>{counts.negative ?? 0} negative reaction</span>
            <span>{counts.strongPositive ?? 0} strong positive</span>
            <span>{counts.uncorroborated ?? 0} one-leg-only</span>
            {counts.fiiUnusable != null && counts.fiiUnusable > 0 && (
              <span style={{ color: "var(--amber)" }}>{counts.fiiUnusable} with sources too far apart to use</span>
            )}
          </div>
        )}

        {/* Every classified name accounted for, summed on screen. "No status" is not hidden. */}
        {reconcile && (
          <span data-testid="or-reconciliation"
            style={{
              fontSize: 11, lineHeight: 1.55,
              color: reconcileOk ? "var(--cp-ink-4)" : "var(--danger-hex)",
              fontWeight: reconcileOk ? undefined : 600,
            }}>
            {reconcile}
          </span>
        )}

        {q.isLoading && <LoadingBlock label="Reading the disclosed quarter" rows={4} />}
        {q.isError && <ErrorBlock title="Ownership reaction didn’t load" error={q.error} onRetry={() => q.refetch()} />}

        {!q.isLoading && !q.isError && rows.length === 0 && (
          <EmptyBlock
            title={status === "any" ? "No names in this view for the disclosed quarter"
              : `No stocks meet the ${OR_STATUS_LABEL[status]} criteria`}
            body={
              <span data-testid="or-empty-state">
                {emptyStateLine(status, counts)}{denominator ? ` ${denominator}` : ""}
              </span>
            }
          />
        )}

        {rows.length > 0 && (
          <>
            <DataTable
              columns={columns}
              rows={rows}
              rowKey={(r) => r.symbol}
              minWidth={1080}
              empty="No rows"
            />
            {feed && feed.total > rows.length && (
              <span style={{ fontSize: 11, color: "var(--cp-ink-4)" }}>
                Showing {rows.length} of {feed.total}; the panel caps at {OR_LIMIT}.
              </span>
            )}
          </>
        )}

        <div className="flex flex-col" style={{ gap: 7, paddingTop: 10, borderTop: "1px solid var(--cp-line)" }}>
          <span data-testid="or-reaction-legend" className="flex flex-wrap" style={{ gap: 14, fontSize: 11, color: "var(--cp-ink-3)" }}>
            {(Object.keys(REACTION_LABEL) as Reaction[]).map((k) => (
              <span key={k} title={REACTION_NOTE[k]}>
                <strong style={{ color: "var(--cp-ink-2)" }}>{REACTION_LABEL[k]}</strong> — {REACTION_NOTE[k]}
              </span>
            ))}
          </span>
          <div data-testid="or-status-legend" className="flex flex-col" style={{ gap: 4 }}>
            {OR_STATUS_ORDER.filter((k) => k !== "none").map((k) => (
              <span key={k} style={{ fontSize: 11, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
                <strong style={{ color: STATUS_CSS[OR_STATUS_TONE[k]].line }}>{OR_STATUS_LABEL[k]}</strong>
                {" — "}{OR_STATUS_NOTE[k]}
              </span>
            ))}
          </div>
          {feed?.cohortThresholds?.note && (
            <Footnote><span data-testid="or-cohort-note">{feed.cohortThresholds.note}</span></Footnote>
          )}
          <Footnote>
            <span data-testid="or-split-caveat">{OR_SPLIT_CAVEAT}</span>
          </Footnote>
          {feed?.filingNote && (
            <Footnote><span data-testid="or-filing-note">{feed.filingNote}</span></Footnote>
          )}
          {feed?.trendNote && (
            <Footnote><span data-testid="or-trend-note">{feed.trendNote}</span></Footnote>
          )}
          {feed?.basisNote && (
            <Footnote><span data-testid="or-basis-note">{feed.basisNote}</span></Footnote>
          )}
          {feed?.source && (
            <Footnote><span data-testid="or-source">Source: {feed.source}</span></Footnote>
          )}
        </div>
      </div>
    </Section>
  );
}
