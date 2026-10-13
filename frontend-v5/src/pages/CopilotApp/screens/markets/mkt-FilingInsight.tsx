/**
 * The generated read of one filing, opened under its row: GET
 * /api/filings/{id}/insights through the app's filings adapter. Tabs and
 * sections are the ones the response carries; nothing is padded. The adapter
 * answers null both when no read exists yet and when the call fails, so the
 * panel can only say that no read is available.
 */
import { useState } from "react";
import type { FilingRow } from "@/services/adapters/filings.adapter";
import { LoadingBlock, Pill, fmtPct } from "../../components/ui";
import { sentimentTone } from "./ArticlesTab";
import { titleCase } from "./format";
import { useFilingInsight } from "./hooks";
import { FilterChips, SourceLine } from "./parts";

/** The response sends confidence as a share (0.85) or as a score out of 100. */
function confidencePct(c: number): number {
  return c <= 1 ? c * 100 : c;
}

export function FilingInsight({ row }: { row: FilingRow }) {
  const q = useFilingInsight(row.id, true);
  const [tab, setTab] = useState("");

  if (q.isPending) {
    return <div data-testid="filing-insight"><LoadingBlock label="Fetching the insight" rows={2} /></div>;
  }

  const ins = q.data;
  if (q.isError || !ins) {
    return (
      <div data-testid="filing-insight" className="cp-card" style={{ padding: "14px 16px", fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-3)" }}>
        <span data-testid="filing-insight-none">
          No AI read of this filing is available yet. New filings are read automatically; check back shortly.
        </span>
      </div>
    );
  }

  const tabs = ins.tabs;
  const active = tabs.some((t) => t.label === tab) ? tab : tabs[0]?.label ?? "";
  const sections = ins.sections.filter((s) => s.tab === active);
  const source = ins.sourceUrl ?? row.url;
  const period = ins.period ?? row.period;

  return (
    <div data-testid="filing-insight" className="cp-card flex min-w-0 flex-col" style={{ gap: 12, padding: "16px 16px" }}>
      <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <span className="cp-eyebrow" style={{ color: "var(--mint)" }}>✦ AI insights</span>
        {period && <Pill>{period}</Pill>}
        {ins.docLabel && <Pill>{ins.docLabel}</Pill>}
      </div>

      {ins.one && (
        <span className="cp-pretty" style={{ fontFamily: "var(--display)", fontSize: 19, lineHeight: 1.3, color: "var(--cp-ink)" }} data-testid="filing-insight-one">
          {ins.one}
        </span>
      )}

      {(ins.metric || ins.sentiment || typeof ins.confidence === "number") && (
        <div className="flex flex-wrap" style={{ gap: 8 }}>
          {ins.metric && <Pill tone="mint">{ins.metric}</Pill>}
          {ins.sentiment && <Pill tone={sentimentTone(ins.sentiment)}>{titleCase(ins.sentiment)}</Pill>}
          {typeof ins.confidence === "number" && <Pill>Confidence {fmtPct(confidencePct(ins.confidence), { digits: 0 })}</Pill>}
        </div>
      )}

      {tabs.length > 0 && (
        <FilterChips
          items={tabs.map((t) => ({ key: t.label, label: t.label }))}
          value={active}
          onChange={setTab}
          label="Insight section"
          idPrefix="filing-insight-tab"
        />
      )}

      {sections.map((sec, i) => (
        <div key={`${sec.tab}-${i}`} className="flex flex-col" style={{ gap: 6 }} data-testid="filing-insight-section">
          <span style={{ fontSize: 14, fontWeight: 500, color: "var(--cp-ink)", overflowWrap: "anywhere" }}>
            {sec.h}
            {sec.cite && (
              sec.cite_url
                ? <a className="cp-link" href={sec.cite_url} target="_blank" rel="noopener noreferrer" style={{ marginLeft: 8, fontSize: 12, fontWeight: 400 }}>{sec.cite}</a>
                : <span className="cp-mono-note" style={{ marginLeft: 8 }}>{sec.cite}</span>
            )}
          </span>
          <ul className="m-0 flex flex-col" style={{ gap: 4, paddingLeft: 18, fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
            {sec.items.map((item, j) => <li key={j} style={{ overflowWrap: "anywhere" }}>{item}</li>)}
          </ul>
        </div>
      ))}

      {sections.length === 0 && (
        <span style={{ fontSize: 13, color: "var(--cp-ink-3)" }}>
          {tabs.length ? "Nothing further in this section." : "This filing has a summary but no section-by-section breakdown."}
        </span>
      )}

      <div className="flex flex-wrap items-center justify-between" style={{ gap: "6px 12px", paddingTop: 10, borderTop: "1px solid var(--cp-line)" }}>
        <SourceLine asOf={ins.generatedAt} asOfLabel="generated" note={ins.disclaimer} quiet />
        {source && <a className="cp-link" href={source} target="_blank" rel="noopener noreferrer" style={{ fontSize: 12 }}>Open the source document ↗</a>}
      </div>
    </div>
  );
}
