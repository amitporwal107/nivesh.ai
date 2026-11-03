/**
 * Risk Desk — the parts the three views share: the view header (one h1 a page), the KPI tile, the used-of-limit bar and
 * the admin-only job-health strip.
 */
import type { CSSProperties, ReactNode } from "react";
import { Pill, TONE_COLOR, type Tone } from "../../../../components/ui";
import { useCopilotShell } from "../../../../lib/shell-context";
import { stampIst } from "../../overview-data";
import { useRiskStatus } from "../../risk-controls";
import { JOBS, useJobHealth, type JobHealth } from "./risk-desk-data";

export const quiet: CSSProperties = { fontSize: 12, lineHeight: 1.55, color: "var(--cp-ink-3)" };
export const at = (iso: string | null) => stampIst(iso) ?? "time not recorded";

/** The paper-only line every view carries. */
export const PAPER_ONLY = "Paper risk only: these limits and controls govern paper entries. Nothing is sent to a broker.";

/** Eyebrow, the view's one h1 (a sentence of what it shows), the paper-only line and the controls' scope from the route. */
export function ViewHead({ view, title }: { view: string; title: ReactNode }) {
  const { mobile } = useCopilotShell();
  const status = useRiskStatus();
  const s = status.data?.known ? status.data : null;
  return (
    <header className="flex min-w-0 flex-col" style={{ gap: 8 }}>
      <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <span className="cp-eyebrow">Risk Desk · {view}</span>
        <span className="cp-pill" data-tone="mint" data-testid="rd-paper-pill">Paper only</span>
      </span>
      <h1 className="cp-display m-0" data-testid="rd-title" style={{ fontSize: mobile ? 24 : 32, lineHeight: 1.15, letterSpacing: "-0.02em", overflowWrap: "anywhere" }}>
        {title}
      </h1>
      <p className="m-0" data-testid="rd-paper-only" style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>{PAPER_ONLY}</p>
      {s?.scope && <p data-testid="risk-scope" className="m-0" style={quiet}>Covers: {s.scope}.</p>}
      {s?.notInScope && <p data-testid="risk-scope-note" role="note" className="m-0" style={quiet}>Not covered: {s.notInScope}.</p>}
    </header>
  );
}

export function Kpi({ k, testId, value, tone = "ink", note }: { k: string; testId: string; value: ReactNode; tone?: Tone; note?: ReactNode }) {
  return (
    <div data-testid={testId} className="flex min-w-0 flex-col" style={{ gap: 6, padding: "14px 16px", borderRadius: 14, border: "1px solid var(--line-2)", background: "var(--bg-1)" }}>
      <span className="cp-eyebrow">{k}</span>
      <span data-testid={`${testId}-value`} className="cp-num" style={{ fontFamily: "var(--display)", fontSize: 26, lineHeight: 1.1, color: TONE_COLOR[tone], overflowWrap: "anywhere" }}>{value}</span>
      {note && <span className="cp-mono-note" style={{ overflowWrap: "anywhere" }}>{note}</span>}
    </div>
  );
}

/** A used-of-limit bar: mint under 70%, amber from 70%, danger at or over the limit; an empty track when unknown. */
export function UseBar({ used, limit, label }: { used: number | null; limit: number | null; label: string }) {
  const share = used == null || limit == null || limit <= 0 ? null : Math.max(0, used / limit);
  const tone: Tone = share == null ? "ink" : share >= 1 ? "danger" : share >= 0.7 ? "amber" : "mint";
  return (
    <span role="img" aria-label={share == null ? `${label}: use unknown` : `${label}: ${Math.round(share * 100)}% of the limit used`}
      style={{ display: "block", height: 6, borderRadius: 999, background: "var(--line-2)", overflow: "hidden" }}>
      {share != null && <span data-testid="rd-bar-fill" data-tone={tone} style={{ display: "block", height: "100%", width: `${Math.min(100, share * 100)}%`, background: TONE_COLOR[tone], borderRadius: 999 }} />}
    </span>
  );
}

const JOB_TONE = (h: JobHealth | undefined): Tone => (!h || h.state == null ? "ink" : h.state === "ok" ? "mint" : h.state === "running" ? "indigo" : h.healthy ? "amber" : "danger");

function JobItem({ job, label }: { job: string; label: string }) {
  const q = useJobHealth(job, true);
  const h = q.data;
  return (
    <div data-testid={`rd-job-${job}`} data-state={h?.state ?? (q.isError ? "error" : "loading")} className="flex min-w-0 flex-col" style={{ gap: 4, flex: "1 1 240px" }}>
      <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <span style={{ fontSize: 13, color: "var(--cp-ink)" }}>{label}</span>
        <span data-testid={`rd-job-${job}-state`}>
          <Pill tone={q.isError ? "danger" : JOB_TONE(h)}>{q.isPending ? "reading…" : q.isError ? "not read" : h?.state?.replace(/_/g, " ") ?? "state unknown"}</Pill>
        </span>
      </span>
      <span data-testid={`rd-job-${job}-words`} style={{ ...quiet, overflowWrap: "anywhere" }}>
        {q.isError
          ? "The job's health could not be read."
          : h
            ? [h.reason, h.lastSuccessAt ? `Last success ${at(h.lastSuccessAt)}` : "No successful run on record", h.schedule].filter(Boolean).join(" · ")
            : ""}
      </span>
    </div>
  );
}

/** Admin only: the exit check's and the AI scanner's health (GET /api/admin/risk/jobs/{job}). Not rendered for anyone else. */
export function JobStrip() {
  const { isAdmin } = useCopilotShell();
  if (!isAdmin) return null;
  return (
    <section data-testid="rd-jobs" aria-label="Job health (admin)" className="flex min-w-0 flex-wrap" style={{ gap: "10px 18px", padding: "12px 14px", borderRadius: 12, border: "1px dashed var(--line-3)", background: "var(--bg-1)" }}>
      <span className="cp-eyebrow" style={{ flex: "1 1 100%" }}>Admin · job health</span>
      {JOBS.map((j) => <JobItem key={j.job} job={j.job} label={j.label} />)}
    </section>
  );
}
