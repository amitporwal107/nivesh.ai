/**
 * Smart trading desk · Evidence & Validation — presentation.
 *
 * Reports the one finished, pre-registered research study behind this desk's "smart money"
 * evidence: does a stock whose institutional ownership rose outperform one whose ownership fell,
 * in the sessions AFTER the disclosure becomes public? The study's own answer is INCONCLUSIVE, and
 * that word is the loud, primary state of this panel — never a footnote, never softened.
 *
 * Everything shown comes from evidence-validation-data.ts, which forwards the data platform's
 * figures unchanged. This file lays out and formats; it derives nothing and asserts nothing the
 * server did not measure.
 *
 * The honesty rules this component is responsible for keeping true on screen:
 *   * RESEARCH ARTIFACT, NOT A PRODUCT FEATURE is stated up front, and INCONCLUSIVE is the single
 *     largest word on the panel — not a small badge beside a number that looks clean.
 *   * Every horizon shows its mean spread AND its 95% CI, block count and positive-quarter count
 *     together — never the point estimate alone, because the CI is the whole point of a 10-block
 *     study whose interval straddles zero.
 *   * The cost-adjusted figure is always shown beside the gross one, never behind a toggle.
 *   * "2026-09-30: not yet eligible" renders as its OWN card with its OWN explanation — never as a
 *     zero, never folded into the horizon table, never silently dropped.
 *   * There is no benchmark row. No Nifty 500 TRI exists in this warehouse and none is implied.
 *   * No score, no rank, no buy/sell wording anywhere on this panel.
 */
import {
  EmptyBlock, ErrorBlock, Footnote, LoadingBlock, Pill, Section,
} from "../../components/ui";
import {
  findPrimary, fmtCiPp, fmtSignedPp, horizonLabel, useEvidenceStudy, type EvHorizonRow,
} from "./evidence-validation-data";

function HorizonCard({ row }: { row: EvHorizonRow }) {
  const positive = row.meanSpreadPp != null && row.meanSpreadPp > 0;
  const negative = row.meanSpreadPp != null && row.meanSpreadPp < 0;
  return (
    <div
      data-testid={`evidence-horizon-${row.sessions}`}
      className="flex flex-col"
      style={{
        gap: 6, padding: "12px 14px", borderRadius: 10,
        border: `1px solid ${row.isPrimary ? "var(--mint)" : "var(--cp-line)"}`,
        background: row.isPrimary ? "var(--mint-soft)" : "var(--bg-2)",
      }}
    >
      <span className="flex items-center justify-between">
        <span className="cp-eyebrow">{horizonLabel(row)}</span>
        {row.isPrimary && <Pill tone="mint">Primary horizon</Pill>}
      </span>
      <span
        className="cp-num"
        data-testid={`evidence-spread-${row.sessions}`}
        style={{
          fontSize: 22, fontWeight: 600,
          color: positive ? "var(--mint)" : negative ? "var(--danger-hex)" : "var(--cp-ink)",
        }}
      >
        {fmtSignedPp(row.meanSpreadPp)}
      </span>
      <span className="cp-num" data-testid={`evidence-ci-${row.sessions}`} style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>
        95% CI {fmtCiPp(row)}
      </span>
      <span style={{ fontSize: 11.5, color: "var(--cp-ink-3)" }}>
        {row.blocks ?? "—"} date-blocks · {row.positiveQuarters ?? "—"}/{row.blocks ?? "—"} quarters positive
      </span>
      <span data-testid={`evidence-net-cost-${row.sessions}`} style={{ fontSize: 11.5, color: "var(--cp-ink-3)" }}>
        Net of estimated costs: <strong style={{ color: "var(--cp-ink-2)" }}>{fmtSignedPp(row.netOfCostPp)}</strong>
      </span>
      {row.verdictReason && row.isPrimary && (
        <Footnote>{row.verdictReason}</Footnote>
      )}
    </div>
  );
}

export default function EvidenceValidationPanel() {
  const q = useEvidenceStudy();
  const feed = q.data ?? null;
  const rows = feed?.rows ?? [];
  const primary = findPrimary(rows);

  return (
    <Section
      title="Evidence & Validation"
      note={feed?.studyId ? `${feed.studyId} · pre-registered` : undefined}
      className="mt-4"
    >
      <div className="flex flex-col" style={{ gap: 14 }} data-testid="evidence-validation-panel">
        <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
          <Pill tone="amber" title="Nothing on this panel is promoted to any score, ranking or trading signal">
            Research artifact · not a product feature
          </Pill>
          {feed?.quarters != null && feed?.reviewFloorBlocks != null && (
            <Pill tone="ink">{feed.quarters} of {feed.reviewFloorBlocks} formation quarters</Pill>
          )}
        </div>

        <Footnote>
          Does a stock whose institutional ownership rose outperform one whose ownership fell, in
          the sessions <strong>after</strong> the quarterly disclosure became public? This is the
          one finished, pre-registered study behind this desk's smart-money evidence — not a score,
          not a ranking, and not a signal to buy or sell. It explains what was tested and what the result
          was, nothing more.
        </Footnote>

        {q.isLoading && <LoadingBlock label="Reading the study" rows={3} />}
        {q.isError && <ErrorBlock title="Evidence & Validation didn’t load" error={q.error} onRetry={() => q.refetch()} />}

        {!q.isLoading && !q.isError && !feed && (
          <EmptyBlock title="No study on record" body="The pre-registered study has not been published yet." />
        )}

        {!q.isLoading && !q.isError && feed && (
          <>
            {/* ── the loud, primary state: INCONCLUSIVE, never a footnote ── */}
            <div
              data-testid="evidence-verdict-headline"
              style={{
                padding: "18px 20px", borderRadius: 12, border: "1px solid var(--amber)",
                background: "var(--amber-soft)",
              }}
            >
              <span className="cp-eyebrow" style={{ color: "var(--cp-ink-2)" }}>Result</span>
              <div data-testid="evidence-verdict" className="cp-display" style={{ fontSize: 30, fontWeight: 700, margin: "4px 0 6px" }}>
                {feed.verdict ?? "UNKNOWN"}
              </div>
              {feed.verdictReason && <Footnote>{feed.verdictReason}</Footnote>}
            </div>

            {/* ── study contract: period, quarters, horizons ── */}
            <div className="flex flex-wrap" style={{ gap: 8, fontSize: 12.5, color: "var(--cp-ink-2)" }} data-testid="evidence-study-contract">
              {feed.studyPeriod?.start && feed.studyPeriod?.end && (
                <span>Study period <strong>{feed.studyPeriod.start} → {feed.studyPeriod.end}</strong></span>
              )}
              {feed.quarters != null && <span>· <strong>{feed.quarters}</strong> quarters</span>}
              {feed.primaryHorizonSessions != null && (
                <span>· primary horizon <strong>{feed.primaryHorizonSessions} sessions</strong>
                  {feed.secondaryHorizonsSessions.length > 0 && (
                    <> (secondary: {feed.secondaryHorizonsSessions.join(", ")})</>
                  )}
                </span>
              )}
              {feed.eligiblePopulation != null && <span>· <strong>{feed.eligiblePopulation}</strong> eligible pairs</span>}
            </div>

            {/* ── per-horizon cards: spread + CI + blocks + positive quarters + net-of-cost ── */}
            <div
              data-testid="evidence-horizons"
              className="grid"
              style={{ gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))", gap: 10 }}
            >
              {rows.map((r) => <HorizonCard key={r.sessions} row={r} />)}
            </div>

            {/* ── September 2026: its own explicit field, never a zero, never folded in ── */}
            {feed.notYetEligible && (
              <div
                data-testid="evidence-not-yet-eligible"
                style={{ padding: "12px 14px", borderRadius: 10, border: "1px solid var(--cp-line)", background: "var(--bg-2)" }}
              >
                <span className="cp-eyebrow">{feed.notYetEligible.quarter}</span>
                <div style={{ fontSize: 13, fontWeight: 600, margin: "2px 0 4px" }}>Not yet eligible for forward-return evaluation</div>
                {feed.notYetEligible.reason && <Footnote>{feed.notYetEligible.reason}</Footnote>}
              </div>
            )}

            {feed.robustnessNote && (
              <Footnote>{feed.robustnessNote}</Footnote>
            )}

            {feed.costNote && <Footnote>{feed.costNote}</Footnote>}
            {feed.benchmarkNote && <Footnote>{feed.benchmarkNote}</Footnote>}
            {feed.eligiblePopulationNote && <Footnote>{feed.eligiblePopulationNote}</Footnote>}

            {feed.disclosure && (
              <div data-testid="evidence-disclosure" style={{ paddingTop: 10, borderTop: "1px solid var(--cp-line)" }}>
                <Footnote>{feed.disclosure}</Footnote>
              </div>
            )}

            {feed.preregistrationSha256 && (
              <span className="cp-mono-note" data-testid="evidence-prereg-hash" style={{ fontSize: 10.5, color: "var(--cp-ink-4)" }}>
                Pre-registration SHA-256 {feed.preregistrationSha256}
              </span>
            )}
          </>
        )}
      </div>
    </Section>
  );
}
