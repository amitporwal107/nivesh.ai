/**
 * The Copilot's visual answer: the `visual_answer` widget (contract `visual-answer-v1`,
 * docs/daily_trader_copilot/VISUAL_ANSWER_CONTRACT.md). Owner, 30 Oct: every answer to a trader's question is a visual
 * decision dashboard built from real data, not paragraphs. The backend chooses the blocks and every number; this
 * renders them in order and adds nothing.
 *
 *   header        title; "Data of <as_of>" and the mode (Live / End of day / Mixed); when it was built
 *   stale         a loud warning when any source behind a shown number is older than the latest session
 *   headline      one line, in its tone
 *   decision      for stock and plan intents: the fixed label, the reason, each condition met or not, "Wrong if"
 *   blocks        the registry (blocks/registry.tsx); an unknown type or a block whose data does not parse is a
 *                 one-line note, and one block that fails to draw never hides the others
 *   evidence      label, value, source and date
 *   data quality  every source with its date and Fresh / Stale / Missing (in words, not colour alone); what is missing
 *   follow-ups    buttons that ask the next question through the host's ask path (onAction)
 *   caveat        ideas to review, not recommendations
 *
 * `compact` is the trading-desk dock's inline layout: tighter spacing, charts in their narrow form.
 */
import { useMemo, type CSSProperties } from "react";
import { BlockFrame, BlockGuard, BlockNote, quiet } from "./blocks/common";
import { BlockView } from "./blocks/registry";
import { fmtDay, fmtStamp, toneColor } from "./format";
import { parseVisualAnswer, type Decision, type VisualAnswerPayload } from "./schema";

type Action = { intent?: string; label?: string; query?: string };

const MODE: Record<string, string> = { live: "Live", eod: "End of day", mixed: "Mixed: live and end of day" };

export const DECISION_LABEL: Record<string, string> = {
  setup_ready: "Setup ready", wait: "Wait", avoid: "Avoid", no_setup: "No setup yet", info: "For information",
};
const DECISION_TONE: Record<string, string> = {
  setup_ready: "var(--mint)", wait: "var(--amber)", avoid: "var(--cp-danger)", no_setup: "var(--cp-ink-3)", info: "var(--cp-indigo)",
};

const STATUS: Record<string, { word: string; color: string; mark: string }> = {
  fresh: { word: "Fresh", color: "var(--mint)", mark: "●" },
  stale: { word: "Stale", color: "var(--amber)", mark: "▲" },
  missing: { word: "Missing", color: "var(--cp-danger)", mark: "✕" },
};
const statusOf = (s: string) => STATUS[s] ?? { word: s, color: "var(--cp-ink-3)", mark: "○" };

const eyebrow: CSSProperties = { fontWeight: 400, fontSize: 9.5, margin: 0 };

export function VisualAnswer({ data, onAction, compact = false }: { data: unknown; onAction?: (a: Action) => void; compact?: boolean }) {
  const parsed = useMemo(() => parseVisualAnswer(data), [data]);
  if (!parsed.ok) {
    return (
      <div data-testid="va-invalid" role="note" style={{ ...quiet, padding: "8px 12px", borderRadius: 10, border: "1px dashed var(--line-2)" }}>
        This visual answer could not be shown ({parsed.problem}). The written answer below still applies.
      </div>
    );
  }
  const a = parsed.answer;
  const ask = onAction ? (query: string) => onAction({ query }) : undefined;
  const sources = a.data_quality?.sources ?? [];
  const staleSources = sources.filter((s) => s.status === "stale");
  const stale = !!a.data_quality?.stale || staleSources.length > 0;
  const gap = compact ? 14 : 18;

  return (
    <article data-testid="va" data-intent={a.intent} data-mode={a.mode ?? ""} data-stale={stale ? "true" : "false"} data-compact={compact ? "true" : "false"}
      aria-label={a.title} className="flex min-w-0 flex-col"
      style={{ gap, padding: compact ? 12 : 16, borderRadius: 14, border: "1px solid var(--line-2)", background: "var(--bg-1)" }}>
      <header className="flex min-w-0 flex-col" style={{ gap: 6 }}>
        <span className="cp-eyebrow" style={{ fontSize: 9.5, color: "var(--mint)" }}>Visual answer</span>
        <h3 data-testid="va-title" className="m-0" style={{ fontFamily: "var(--display)", fontWeight: 400, fontSize: compact ? 18 : 22, lineHeight: 1.2, letterSpacing: "-0.02em", color: "var(--cp-ink)", overflowWrap: "anywhere" }}>{a.title}</h3>
        <span data-testid="va-asof" className="flex flex-wrap items-center" style={{ gap: "4px 8px", fontSize: 12, color: "var(--cp-ink-3)" }}>
          <span>Data of <span className="cp-num" data-testid="va-asof-day">{a.as_of ? fmtDay(a.as_of) : "an unknown day"}</span></span>
          {a.mode && <span data-testid="va-mode" className="cp-pill" data-tone={a.mode === "live" ? "mint" : a.mode === "mixed" ? "amber" : undefined}>{MODE[a.mode]}</span>}
          {a.generated_at && <span>· built {fmtStamp(a.generated_at)}</span>}
        </span>
      </header>

      {stale && (
        <div data-testid="va-stale-banner" role="alert" className="flex min-w-0 flex-col" style={{ gap: 4, padding: "10px 12px", borderRadius: 10, border: "1px solid var(--amber-line)", background: "var(--amber-soft)" }}>
          <strong style={{ fontFamily: "var(--mono)", fontSize: 10.5, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--amber)", fontWeight: 600 }}>▲ Stale data in this answer</strong>
          <span style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink)" }}>
            {staleSources.length
              ? `${staleSources.map((s) => `${s.name} (${s.as_of ? fmtDay(s.as_of) : "date unknown"})`).join(", ")} ${staleSources.length === 1 ? "is" : "are"} older than the latest completed session.`
              : "Some numbers are older than the latest completed session."}
            {" "}Check them before acting.
          </span>
        </div>
      )}

      {a.headline && (
        <p data-testid="va-headline" data-tone={a.headline.tone ?? "neutral"} className="m-0 flex items-start" style={{ gap: 8, fontSize: compact ? 14 : 15.5, lineHeight: 1.5, color: "var(--cp-ink)" }}>
          <span aria-hidden style={{ flex: "none", width: 3, alignSelf: "stretch", borderRadius: 2, background: toneColor(a.headline.tone) }} />
          <span style={{ overflowWrap: "anywhere" }}>{a.headline.text}</span>
        </p>
      )}

      {a.decision && <DecisionPanel d={a.decision} />}

      {parsed.blocks.map((p) => {
        if (p.kind === "unsupported") {
          return <BlockNote key={p.key} testId="va-block-unsupported">{p.title ? `${p.title}: ` : ""}this part of the answer (“{p.type}”) is not supported yet.</BlockNote>;
        }
        if (p.kind === "bad") {
          return <BlockNote key={p.key} testId="va-block-bad">{p.title ? `${p.title}: ` : ""}this part of the answer could not be shown; its data did not match ({p.problem}).</BlockNote>;
        }
        const b = p.block;
        return (
          <BlockFrame key={p.key} type={b.type} id={b.id} title={b.title} note={b.note}>
            <BlockGuard type={b.type}><BlockView block={b} compact={compact} ask={ask} /></BlockGuard>
          </BlockFrame>
        );
      })}

      {a.evidence.length > 0 && <Evidence items={a.evidence} />}
      <DataQuality dq={a.data_quality} />

      {a.follow_ups.length > 0 && (
        <div data-testid="va-followups" className="flex flex-wrap" style={{ gap: 6 }}>
          {a.follow_ups.map((f, i) => (
            <button key={`${f.query}-${i}`} type="button" data-testid="va-followup" className="cp-chip" disabled={!ask}
              onClick={() => ask?.(f.query)} style={{ padding: compact ? "6px 11px" : "7px 13px", fontSize: 12.5 }}>
              {f.label} ›
            </button>
          ))}
        </div>
      )}

      {a.caveat && <p data-testid="va-caveat" className="m-0" style={{ ...quiet, fontSize: 11.5 }}>{a.caveat}</p>}
    </article>
  );
}

function DecisionPanel({ d }: { d: Decision }) {
  const color = DECISION_TONE[d.status] ?? "var(--cp-ink-2)";
  const label = d.label || DECISION_LABEL[d.status] || d.status;
  return (
    <section data-testid="va-decision" data-status={d.status} aria-label={`Decision: ${label}`} className="flex min-w-0 flex-col"
      style={{ gap: 8, padding: "10px 12px", borderRadius: 10, border: "1px solid var(--line-2)", borderLeft: `3px solid ${color}`, background: "var(--bg-2)" }}>
      <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <h4 className="cp-eyebrow" style={eyebrow}>Decision</h4>
        <span data-testid="va-decision-label" className="cp-pill" style={{ color, borderColor: color, fontSize: 11 }}>{label}</span>
      </div>
      {d.reason && <span data-testid="va-decision-reason" style={{ fontSize: 13.5, lineHeight: 1.5, color: "var(--cp-ink)", overflowWrap: "anywhere" }}>{d.reason}</span>}
      {d.conditions.length > 0 && (
        <ul className="m-0 flex list-none flex-col p-0" style={{ gap: 4 }}>
          {d.conditions.map((c, i) => {
            const mark = c.met === true ? "✓" : c.met === false ? "✕" : "?";
            const word = c.met === true ? "met" : c.met === false ? "not met" : "not known";
            const col = c.met === true ? "var(--mint)" : c.met === false ? "var(--cp-danger)" : "var(--cp-ink-3)";
            return (
              <li key={i} data-testid="va-condition" data-met={String(c.met)} className="flex items-start" style={{ gap: 8, fontSize: 12.5, lineHeight: 1.45, color: "var(--cp-ink-2)" }}>
                <span aria-hidden style={{ flex: "none", width: 14, color: col, fontWeight: 600 }}>{mark}</span>
                <span style={{ overflowWrap: "anywhere" }}>{c.text} <span data-testid="va-condition-state" style={{ color: col, whiteSpace: "nowrap" }}>({word})</span></span>
              </li>
            );
          })}
        </ul>
      )}
      {d.invalidation && <span data-testid="va-invalidation" style={{ fontSize: 12.5, color: "var(--cp-ink-2)" }}>Wrong if: {d.invalidation}</span>}
    </section>
  );
}

function Evidence({ items }: { items: VisualAnswerPayload["evidence"] }) {
  return (
    <section data-testid="va-evidence" className="flex min-w-0 flex-col" style={{ gap: 6 }}>
      <h4 className="cp-eyebrow" style={eyebrow}>Evidence</h4>
      <ul className="m-0 flex list-none flex-col p-0" style={{ gap: 4 }}>
        {items.map((e, i) => (
          <li key={i} data-testid="va-evidence-row" className="flex min-w-0 flex-wrap items-baseline" style={{ gap: "0 8px", fontSize: 12.5, lineHeight: 1.5 }}>
            <span style={{ color: "var(--cp-ink-2)" }}>{e.label}</span>
            <span data-testid="va-evidence-value" className="cp-num" style={{ color: "var(--cp-ink)" }}>{e.value == null ? "—" : String(e.value)}</span>
            {(e.source || e.as_of) && <span style={{ fontSize: 11.5, color: "var(--cp-ink-3)" }}>{[e.source, e.as_of ? fmtDay(e.as_of) : null].filter(Boolean).join(" · ")}</span>}
          </li>
        ))}
      </ul>
    </section>
  );
}

function DataQuality({ dq }: { dq: VisualAnswerPayload["data_quality"] }) {
  const sources = dq?.sources ?? [];
  const missing = dq?.missing ?? [];
  return (
    <section data-testid="va-data-quality" className="flex min-w-0 flex-col" style={{ gap: 6, paddingTop: 10, borderTop: "1px solid var(--cp-line)" }}>
      <h4 className="cp-eyebrow" style={eyebrow}>Data used</h4>
      {sources.length === 0 && <span style={quiet}>The answer did not list its sources.</span>}
      <ul className="m-0 flex list-none flex-col p-0" style={{ gap: 3 }}>
        {sources.map((s, i) => {
          const st = statusOf(s.status);
          const loud = s.status !== "fresh";
          return (
            <li key={`${s.name}-${i}`} data-testid="va-source" data-status={s.status} className="flex min-w-0 flex-wrap items-baseline" style={{ gap: "0 8px", fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
              <span data-testid="va-source-status" style={{ color: st.color, fontWeight: loud ? 600 : 400, whiteSpace: "nowrap" }}><span aria-hidden>{st.mark} </span>{st.word}</span>
              <span data-testid="va-source-name">{s.name}</span>
              <span data-testid="va-source-asof" className="cp-num" style={{ color: loud ? st.color : "var(--cp-ink-3)" }}>{s.as_of ? fmtDay(s.as_of) : "no date"}</span>
              {s.note && <span style={{ color: "var(--cp-ink-3)" }}>· {s.note}</span>}
            </li>
          );
        })}
      </ul>
      {missing.length > 0 && (
        <div data-testid="va-missing" className="flex min-w-0 flex-col" style={{ gap: 2, fontSize: 12, color: "var(--cp-ink-2)" }}>
          <span style={{ color: "var(--cp-danger)" }}>Not available, so not shown:</span>
          <ul className="m-0" style={{ paddingLeft: 16 }}>
            {missing.map((m, i) => <li key={i} data-testid="va-missing-item">{m}</li>)}
          </ul>
        </div>
      )}
    </section>
  );
}
