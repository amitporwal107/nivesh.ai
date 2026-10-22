/**
 * Portfolio analysis — "What to fix": the ranked remediation plan of the old
 * AI Insights screen (src/pages/Concentration, RemediationPanel).
 *
 * Data: GET /api/portfolio/exposure/remediation (useRemediation).
 *
 * The old screen closes with an "If all actions applied" card whose figures
 * are fixed text (7 MFs → 5 MFs, ₹9,000/yr, Eff. N 4.1 → 6.5), the same for
 * every account. Here that card adds up what the actions themselves carry.
 *
 * Nothing here changes data: every button asks the Copilot or opens a screen.
 *
 * Icons: each holding listed under "What's driving the exposure", and the fund
 * the freed money goes to, shows the company icon (a stock) or the fund house
 * icon (a fund). The endpoint sends names only, so the kind comes from the
 * user's holdings (portfolio/names); a name that is not a holding gets none.
 */
import { useId, useState } from "react";
import { useRemediation } from "@/hooks/use-analytics";
import {
  Btn, DataTable, EmptyBlock, ErrorBlock, Eyebrow, LoadingBlock, Pill, Tiles,
  TONE_COLOR, fmtINR, fmtNum, fmtPct, type Column, type TileItem,
} from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { ShareBar } from "./charts";
import { VERDICT_META, readRemediation, type RemBeforeAfter, type Remediation, type RemediationRead, type Verdict } from "./concentration-data";
import { BAD_SHAPE, loadError } from "./data";
import { HoldingIcon } from "./names";

const body = { fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)" } as const;

function VerdictText({ verdict, children }: { verdict: Verdict | null; children: string }) {
  return <span style={{ color: verdict ? TONE_COLOR[VERDICT_META[verdict].tone] : undefined }}>{children}</span>;
}

/** "2440 → 1980", or "—" when neither side came with the action. */
function arrow(before: string, after: string): string {
  return before === "—" && after === "—" ? "—" : `${before} → ${after}`;
}

const IMPACT_COLUMNS: Array<Column<RemBeforeAfter>> = [
  { key: "lens", header: "Lens", render: (b) => <span style={{ color: "var(--cp-ink)", fontWeight: 500 }}>{b.lensLabel || "—"}</span> },
  { key: "before", header: "Before", num: true, render: (b) => <VerdictText verdict={b.beforeVerdict}>{fmtPct(b.beforePct)}</VerdictText> },
  {
    key: "after", header: "After", num: true, width: "minmax(0,1.6fr)",
    render: (b) => (
      <VerdictText verdict={b.afterVerdict}>
        {`${fmtPct(b.afterPct)}${b.afterVerdict ? ` · ${VERDICT_META[b.afterVerdict].label}` : ""}`}
      </VerdictText>
    ),
  },
  { key: "hhi", header: "HHI", num: true, render: (b) => arrow(fmtNum(b.beforeHhi), fmtNum(b.afterHhi)) },
  { key: "effn", header: "Eff. N", num: true, render: (b) => arrow(fmtNum(b.beforeEffN, 1), fmtNum(b.afterEffN, 1)) },
];

function RemCard({ rec, top }: { rec: Remediation; top: boolean }) {
  const { ask, go } = useCopilotShell();
  // The highest-leverage action starts open, as on the old screen.
  const [open, setOpen] = useState(top);
  const panelId = useId();
  return (
    <article data-testid="analysis-remediation-card" className="cp-card-raised flex flex-col" style={top ? { borderColor: "var(--mint-line)" } : undefined}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full flex-wrap items-start text-left"
        style={{ gap: "10px 16px", padding: "16px 18px", background: "none", border: 0, cursor: "pointer", color: "inherit", fontFamily: "var(--sans)" }}
      >
        <span className="flex flex-col" style={{ gap: 6, width: 64, flex: "none" }} title="Leverage score, 0–100: risk reduction per rupee moved">
          <span className="cp-eyebrow">Leverage</span>
          <span data-testid="analysis-remediation-leverage" className="cp-num" style={{ fontSize: 20 }}>{fmtNum(rec.leverageScore)}</span>
          <ShareBar pct={rec.leverageScore} tone={top ? "mint" : "ink"} dim={!top} />
        </span>
        <span className="flex min-w-0 flex-col" style={{ gap: 8, flex: "1 1 280px" }}>
          <span className="flex flex-wrap items-center" style={{ gap: 6 }}>
            {top && <Pill tone="mint">Highest leverage</Pill>}
            {rec.kindLabel && <Pill tone={rec.kindTone}>{rec.kindLabel}</Pill>}
            {rec.annualSavingRs != null && (
              <Pill tone="mint">Save <span data-testid="analysis-remediation-saving">{fmtINR(rec.annualSavingRs)}</span>/yr</Pill>
            )}
          </span>
          <span data-testid="analysis-remediation-title" className="cp-pretty" style={{ fontSize: 15, fontWeight: 500, lineHeight: 1.4, overflowWrap: "anywhere" }}>{rec.title}</span>
          {rec.action && <span style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>{rec.action}</span>}
        </span>
        <span className="flex items-center" style={{ gap: 12, marginLeft: "auto" }}>
          {rec.amountRs != null && <span data-testid="analysis-remediation-amount" className="cp-num" style={{ fontFamily: "var(--display)", fontSize: 20 }}>{fmtINR(rec.amountRs, { compact: true })}</span>}
          <span aria-hidden="true" style={{ fontSize: 13, color: "var(--cp-ink-3)" }}>{open ? "Hide" : "Details"} ›</span>
        </span>
      </button>

      {open && (
        <div id={panelId} className="flex flex-col" style={{ gap: 16, padding: "16px 18px 18px", borderTop: "1px solid var(--cp-line)" }}>
          {rec.why && (
            <div className="flex flex-col" style={{ gap: 6 }}>
              <Eyebrow>Why this matters</Eyebrow>
              <span data-testid="analysis-remediation-why" style={body}>{rec.why}</span>
            </div>
          )}

          {rec.contributors.length > 0 && (
            <div className="flex flex-col" style={{ gap: 8 }}>
              <Eyebrow>What’s driving the exposure</Eyebrow>
              {rec.contributors.map((c) => (
                <div key={c.name} data-testid="analysis-remediation-contributor" className="grid items-center" style={{ gridTemplateColumns: "minmax(0,1fr) 96px 52px", gap: 12 }}>
                  <span className="flex items-center" style={{ gap: 8, minWidth: 0 }}>
                    <HoldingIcon name={c.name} size={22} />
                    <span data-testid="analysis-remediation-contributor-name" style={{ ...body, minWidth: 0, overflowWrap: "anywhere" }}>{c.name}</span>
                  </span>
                  <ShareBar pct={c.pct} tone="danger" />
                  <span className="cp-num" style={{ fontSize: 12, textAlign: "right", color: "var(--cp-ink-2)" }}>{c.pct == null ? "—" : `${Number(c.pct.toFixed(1))}%`}</span>
                </div>
              ))}
            </div>
          )}

          <div className="flex flex-col" style={{ gap: 8 }}>
            <Eyebrow>Projected impact</Eyebrow>
            {rec.beforeAfter.length > 0 ? (
              <div className="cp-card" data-testid="analysis-remediation-impact">
                <DataTable columns={IMPACT_COLUMNS} rows={rec.beforeAfter} rowKey={(b, i) => `${b.lensId}-${i}`} minWidth={520} />
              </div>
            ) : (
              <span style={{ ...body, color: "var(--cp-ink-3)" }}>No before-and-after projection came with this action.</span>
            )}
          </div>

          {rec.redeployTo && (
            <div className="flex flex-col" style={{ gap: 6, padding: "12px 14px", borderRadius: 10, border: "1px solid var(--indigo-line)", background: "var(--cp-indigo-soft)" }}>
              <Eyebrow tone="indigo">Redeploy freed capital to</Eyebrow>
              <span className="flex items-center" style={{ gap: 8, minWidth: 0 }}>
                <HoldingIcon name={rec.redeployTo} size={22} />
                <span style={{ ...body, minWidth: 0, overflowWrap: "anywhere" }}>{rec.redeployTo}</span>
              </span>
            </div>
          )}

          {rec.caveats.length > 0 && (
            <div className="flex flex-col" style={{ gap: 6 }}>
              {rec.caveats.map((c) => (
                <span key={c.text} style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
                  <span className="cp-mono-note" style={{ marginRight: 8, color: "var(--cp-ink-3)" }}>{c.label}</span>{c.text}
                </span>
              ))}
            </div>
          )}

          <div className="flex flex-wrap" style={{ gap: 8 }}>
            <Btn
              variant="primary"
              onClick={() => ask(`Walk me through this step for my portfolio: ${rec.title}. ${rec.action} What would it cost me in tax and exit load, and is it worth doing now?`.replace(/\s+/g, " "))}
            >
              Ask Copilot about this step
            </Btn>
            <Btn onClick={() => go("tool/recommend")}>Open recommendations</Btn>
            <Btn variant="ghost" onClick={() => go("page/plan")}>Open full action plan</Btn>
          </div>
        </div>
      )}
    </article>
  );
}

/** What the listed actions add up to. Each figure is a plain sum of what the actions carry. */
function AllApplied({ read }: { read: RemediationRead }) {
  const n = read.recs.length;
  const tiles: TileItem[] = [
    { k: "Actions", v: <span data-testid="analysis-remediation-count">{fmtNum(n)}</span>, s: "Ranked by leverage" },
    {
      k: "Fee savings",
      v: <span data-testid="analysis-remediation-total-saving">{read.totalSavingRs == null ? "—" : `${fmtINR(read.totalSavingRs)}/yr`}</span>,
      s: read.totalSavingRs == null ? "No action carries a saving" : "Sum of each action’s estimate",
      tone: read.totalSavingRs == null ? "ink" : "mint",
    },
    {
      k: "Money moved",
      v: <span data-testid="analysis-remediation-total-amount">{fmtINR(read.totalAmountRs, { compact: true })}</span>,
      s: read.totalAmountRs == null ? "No action moves money" : "Redeemed or switched",
    },
  ];
  return (
    <div data-testid="analysis-remediation-summary" className="flex flex-col" style={{ gap: 12, padding: "16px 18px", borderRadius: 14, border: "1px solid var(--mint-line)", background: "var(--mint-soft)" }}>
      <span style={{ fontFamily: "var(--display)", fontSize: 20, lineHeight: 1.25 }}>{n === 1 ? "If this action were applied" : `If all ${n} actions were applied`}</span>
      <Tiles items={tiles} min={140} />
      <span style={{ fontSize: 12, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
        These are sums of what each action reports on its own. Two actions that touch the same fund can count the same rupees twice, and the engine does not project the concentration verdicts with every action applied together.
      </span>
    </div>
  );
}

export function RemediationSection() {
  const { mobile } = useCopilotShell();
  const q = useRemediation();
  if (q.isPending) return <LoadingBlock label="Computing remediation recommendations" rows={4} />;
  if (q.isError) return <ErrorBlock title="The remediation plan didn’t load" error={loadError(q.error)} onRetry={() => q.refetch()} />;
  // useRemediation does not validate its response, so read it defensively.
  const read = readRemediation(q.data);
  if (!read) return <ErrorBlock title="The remediation plan didn’t load" error={BAD_SHAPE} onRetry={() => q.refetch()} />;
  if (!read.recs.length) {
    return (
      <div data-testid="analysis-remediation-empty">
        <EmptyBlock title="Nothing to fix" body="No remediation actions needed — all lenses are within policy caps." />
      </div>
    );
  }
  return (
    <div data-testid="analysis-remediation" className="flex flex-col" style={{ gap: 14 }}>
      <div className="flex flex-col" style={{ gap: 6 }}>
        <span style={{ fontFamily: "var(--display)", fontSize: mobile ? 22 : 28, lineHeight: 1.2 }}>Remediation plan</span>
        <span style={body}>Ranked by risk reduction per rupee moved. Highest-leverage action pinned first.</span>
      </div>
      {read.recs.map((rec, i) => <RemCard key={`${rec.id}-${i}`} rec={rec} top={i === 0} />)}
      <AllApplied read={read} />
    </div>
  );
}
