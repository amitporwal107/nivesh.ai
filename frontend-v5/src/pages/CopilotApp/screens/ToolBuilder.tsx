/**
 * Tool builder — an admin describes a new Copilot tool: who it is for, what it
 * answers, the data and inputs it needs, the services it calls, what the
 * answer shows, its guardrails and its triggers.
 * Design: frontend-v5/design/nivesh-copilot/NVToolBuilder.dc.html.
 *
 * There is no tool-definition backend (services/adapters/builder.adapter.ts is
 * the portfolio builder), so this is a local editor: the admin types every
 * value, and the preview, the contract and the checklist are computed from the
 * draft (screens/internal/tool-draft.ts). The draft is kept in this browser.
 * Saving, drafting by AI, test prompts and review are disabled controls with a
 * note on what they need. The design's sample tools and their statuses are not
 * shown.
 */
import { useState, type CSSProperties, type KeyboardEvent, type ReactNode } from "react";
import { Btn, Eyebrow, Footnote, NotConnected, Pill, Screen } from "../components/ui";
import { useCopilotShell } from "../lib/shell-context";
import { MODE_LABEL, type Mode } from "../lib/views";
import { OpsHeader } from "./internal/shared";
import {
  buildContract, checklist, rowId, useToolDraft,
  type DataNeed, type ToolInput, type Trigger,
} from "./internal/tool-draft";

const PERSONAS: Mode[] = ["investor", "trader", "advisor"];

/** Steps of the design's release checklist that need a backend to have a status. */
const BACKEND_STEPS = ["Test prompts", "Data freshness checks", "Engineering review", "Compliance review", "Rollout"];

const FIELD: CSSProperties = {
  width: "100%",
  minWidth: 0,
  padding: "9px 12px",
  borderRadius: 10,
  border: "1px solid var(--line-2)",
  background: "var(--bg-2)",
  color: "var(--cp-ink)",
  fontFamily: "var(--sans)",
  fontSize: 14,
  lineHeight: 1.5,
};

const QUIET: CSSProperties = { fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-3)" };

const REMOVE: CSSProperties = {
  flex: "none",
  width: 28,
  height: 28,
  borderRadius: 8,
  border: "1px solid var(--line-2)",
  background: "transparent",
  color: "var(--cp-ink-3)",
  fontSize: 14,
  lineHeight: 1,
  cursor: "pointer",
};

// ── form pieces ──────────────────────────────────────────────────────────

/** One numbered card of the form. */
function Step({ n, title, hint, children }: { n?: string; title: string; hint?: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="cp-card flex flex-col min-w-0" style={{ gap: 10, padding: "16px 18px" }}>
      <div className="flex flex-wrap items-baseline" style={{ gap: "4px 10px" }}>
        {n && <span aria-hidden style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--mint)" }}>{n}</span>}
        <h2 className="m-0" style={{ fontSize: 15, fontWeight: 500 }}>{title}</h2>
        <span style={{ flex: 1 }} />
        {hint && <span style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>{hint}</span>}
      </div>
      {children}
    </section>
  );
}

/** A list of short text items: chips that can be removed, and a box to add one. */
function ListEditor({ id, label, items, onChange, mono, addHint }: {
  /** Used for the input id and the test ids, e.g. "questions". */
  id: string;
  /** What one item is, e.g. "question". Labels the input for screen readers. */
  label: string;
  items: string[];
  onChange: (items: string[]) => void;
  /** Mono mint chips, as the design shows service names. */
  mono?: boolean;
  addHint: string;
}) {
  const [text, setText] = useState("");
  const value = text.trim();
  const add = () => {
    if (!value) return;
    if (!items.includes(value)) onChange([...items, value]);
    setText("");
  };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") { e.preventDefault(); add(); }
  };
  return (
    <div className="flex flex-col" style={{ gap: 8 }}>
      {items.length > 0 && (
        <ul className="m-0 flex flex-wrap" style={{ gap: 6, padding: 0, listStyle: "none" }}>
          {items.map((it) => (
            <li
              key={it}
              data-testid={`builder-${id}-item`}
              className="flex items-center"
              style={{
                gap: 6,
                maxWidth: "100%",
                padding: "5px 6px 5px 10px",
                borderRadius: 8,
                border: `1px solid ${mono ? "var(--mint-line)" : "var(--line-2)"}`,
                background: "var(--bg-2)",
                color: mono ? "var(--mint)" : "var(--cp-ink)",
                fontFamily: mono ? "var(--mono)" : "var(--sans)",
                fontSize: 12,
              }}
            >
              <span style={{ overflowWrap: "anywhere" }}>{it}</span>
              <button
                type="button"
                aria-label={`Remove ${label}: ${it}`}
                onClick={() => onChange(items.filter((x) => x !== it))}
                style={{ border: 0, background: "none", color: "var(--cp-ink-3)", cursor: "pointer", fontSize: 14, lineHeight: 1, padding: "0 4px" }}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex" style={{ gap: 8 }}>
        <label htmlFor={`builder-${id}`} className="sr-only">Add a {label}</label>
        <input
          id={`builder-${id}`}
          data-testid={`builder-${id}-input`}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKey}
          placeholder={addHint}
          autoComplete="off"
          style={{ ...FIELD, flex: "1 1 0", fontFamily: mono ? "var(--mono)" : "var(--sans)", fontSize: 13 }}
        />
        <Btn data-testid={`builder-${id}-add`} disabled={!value} onClick={add}>＋ Add</Btn>
      </div>
    </div>
  );
}

interface ColumnDef<R> {
  key: Exclude<keyof R & string, "id">;
  label: string;
  /** A fixed set of choices renders a select. */
  options?: Array<{ value: string; label: string }>;
  mono?: boolean;
}

/** A small table of editable rows. Columns wrap onto more lines on a phone. */
function RowsEditor<R extends { id: string }>({ id, rowLabel, columns, rows, onChange, blank }: {
  id: string;
  /** What one row is, e.g. "data source". */
  rowLabel: string;
  columns: ColumnDef<R>[];
  rows: R[];
  onChange: (rows: R[]) => void;
  blank: () => R;
}) {
  const setCell = (rowIndex: number, key: ColumnDef<R>["key"], value: string) => {
    onChange(rows.map((r, i) => (i === rowIndex ? ({ ...r, [key]: value } as R) : r)));
  };
  return (
    <div className="flex flex-col" style={{ gap: 8 }}>
      {rows.map((r, i) => (
        <div key={r.id} role="group" aria-label={`${rowLabel} ${i + 1}`} data-testid={`builder-${id}-row`} className="flex items-start" style={{ gap: 8, paddingTop: i ? 8 : 0, borderTop: i ? "1px solid var(--cp-line)" : undefined }}>
          <div className="grid min-w-0" style={{ flex: "1 1 0", gridTemplateColumns: "repeat(auto-fit,minmax(112px,1fr))", gap: 8 }}>
            {columns.map((c) => {
              const cellValue = String(r[c.key] ?? "");
              const cellLabel = `${c.label}, ${rowLabel} ${i + 1}`;
              const style: CSSProperties = { ...FIELD, padding: "7px 10px", fontSize: 13, fontFamily: c.mono ? "var(--mono)" : "var(--sans)" };
              return c.options ? (
                <select key={c.key} aria-label={cellLabel} data-testid={`builder-${id}-${c.key}`} value={cellValue} onChange={(e) => setCell(i, c.key, e.target.value)} style={style}>
                  {c.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              ) : (
                <input key={c.key} aria-label={cellLabel} data-testid={`builder-${id}-${c.key}`} value={cellValue} placeholder={c.label} autoComplete="off" onChange={(e) => setCell(i, c.key, e.target.value)} style={style} />
              );
            })}
          </div>
          <button type="button" aria-label={`Remove ${rowLabel} ${i + 1}`} onClick={() => onChange(rows.filter((x) => x.id !== r.id))} style={REMOVE}>×</button>
        </div>
      ))}
      {rows.length === 0 && <span style={QUIET}>No {rowLabel} added yet.</span>}
      <Btn data-testid={`builder-${id}-add`} variant="ghost" style={{ alignSelf: "flex-start" }} onClick={() => onChange([...rows, blank()])}>＋ Add a {rowLabel}</Btn>
    </div>
  );
}

const DATA_COLUMNS: ColumnDef<DataNeed>[] = [
  { key: "source", label: "Source" },
  { key: "need", label: "Need", options: [{ value: "required", label: "Required" }, { value: "optional", label: "Optional" }] },
  { key: "freshness", label: "Freshness" },
];
const INPUT_COLUMNS: ColumnDef<ToolInput>[] = [
  { key: "field", label: "Field", mono: true },
  { key: "type", label: "Type" },
  { key: "fallback", label: "Default" },
  { key: "rule", label: "Rule" },
];
const TRIGGER_COLUMNS: ColumnDef<Trigger>[] = [
  { key: "type", label: "Type" },
  { key: "detail", label: "Detail" },
];

// ── screen ───────────────────────────────────────────────────────────────

export default function ToolBuilderScreen() {
  const { compact } = useCopilotShell();
  const draft = useToolDraft((s) => s.draft);
  const patch = useToolDraft((s) => s.patch);
  const reset = useToolDraft((s) => s.reset);
  const [copied, setCopied] = useState<"idle" | "done" | "failed">("idle");

  const contract = buildContract(draft);
  const checks = checklist(draft);
  const doneCount = checks.filter((c) => c.done).length;
  const sample = draft.questions[0];
  const answerClass = draft.answerClass.trim();
  const services = draft.services;
  const trace = services.length
    ? `${services.length} ${services.length === 1 ? "service" : "services"} · ${services.join(" → ")}`
    : "";

  const togglePersona = (p: Mode) => {
    patch({ personas: draft.personas.includes(p) ? draft.personas.filter((x) => x !== p) : [...draft.personas, p] });
  };

  const copyContract = async () => {
    try {
      await navigator.clipboard.writeText(contract);
      setCopied("done");
    } catch {
      // Clipboard access can be refused by the browser; the text stays selectable.
      setCopied("failed");
    }
  };

  const clearDraft = () => {
    if (!window.confirm("Clear this draft? Everything typed in the form is removed from this browser.")) return;
    reset();
    setCopied("idle");
  };

  return (
    <Screen testId="screen-builder" width={1120}>
      <OpsHeader
        area="Tool builder"
        title={<>Draft a tool <em>definition</em>.</>}
        sub="Describe the objective, the data it needs and the rules it must follow. The contract on the right is written from what you type. Saving, drafting by AI, test prompts and review are not connected yet, so a draft stays in this browser."
      />

      <div className="cp-card flex flex-wrap items-center" style={{ gap: 12, padding: "12px 12px 12px 18px", borderRadius: 16, borderColor: "var(--mint-line)" }}>
        <span aria-hidden style={{ color: "var(--mint)" }}>✦</span>
        <label htmlFor="builder-describe" className="sr-only">Describe a new tool for the AI to draft</label>
        <input
          id="builder-describe"
          disabled
          placeholder="Describe a new tool in a sentence"
          title="Not connected: no service drafts a tool definition from a description"
          style={{ flex: "1 1 200px", minWidth: 0, border: 0, background: "transparent", color: "var(--cp-ink)", fontFamily: "var(--sans)", fontSize: 14, cursor: "not-allowed" }}
        />
        <Btn data-testid="builder-draft-it" variant="primary" disabled title="Not connected: no service drafts a tool definition from a description">Draft it ›</Btn>
      </div>

      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,420px),1fr))", gap: 14, alignItems: "start" }}>
        {/* ── the form ── */}
        <div className="flex flex-col min-w-0" style={{ gap: 12 }}>
          <Step title="Tool" hint="Name it and say who it is for">
            <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,200px),1fr))", gap: 10 }}>
              <div className="flex flex-col" style={{ gap: 6 }}>
                <label htmlFor="builder-name" className="cp-eyebrow">Name</label>
                <input id="builder-name" data-testid="builder-name" value={draft.name} onChange={(e) => patch({ name: e.target.value })} autoComplete="off" style={FIELD} />
              </div>
              <div className="flex flex-col" style={{ gap: 6 }}>
                <label htmlFor="builder-class" className="cp-eyebrow">Answer class</label>
                <input id="builder-class" data-testid="builder-class" value={draft.answerClass} onChange={(e) => patch({ answerClass: e.target.value })} autoComplete="off" style={FIELD} />
              </div>
            </div>
            <div role="group" aria-label="Personas" className="flex flex-wrap items-center" style={{ gap: 6 }}>
              <span className="cp-eyebrow" style={{ marginRight: 4 }}>Personas</span>
              {PERSONAS.map((p) => {
                const on = draft.personas.includes(p);
                return (
                  <button
                    key={p}
                    type="button"
                    aria-pressed={on}
                    data-testid={`builder-persona-${p}`}
                    onClick={() => togglePersona(p)}
                    style={{
                      padding: "7px 14px",
                      borderRadius: 999,
                      fontFamily: "var(--sans)",
                      fontSize: 13,
                      cursor: "pointer",
                      border: `1px solid ${on ? "var(--mint-line)" : "var(--line-2)"}`,
                      color: on ? "var(--mint)" : "var(--cp-ink-2)",
                      background: on ? "var(--mint-soft)" : "transparent",
                    }}
                  >
                    {MODE_LABEL[p]}
                  </button>
                );
              })}
            </div>
          </Step>

          <Step n="01" title="Objective" hint="What job does it do, for whom?">
            <label htmlFor="builder-objective" className="sr-only">Objective</label>
            <textarea id="builder-objective" data-testid="builder-objective" value={draft.objective} onChange={(e) => patch({ objective: e.target.value })} rows={4} style={{ ...FIELD, resize: "vertical" }} />
          </Step>

          <Step n="02" title="Questions it should answer" hint="How a user would ask for it">
            <ListEditor id="questions" label="question" addHint="Type a question, then Add" items={draft.questions} onChange={(questions) => patch({ questions })} />
          </Step>

          <Step n="03" title="Data it needs" hint="Source, need, freshness">
            <RowsEditor
              id="data"
              rowLabel="data source"
              columns={DATA_COLUMNS}
              rows={draft.data}
              onChange={(data) => patch({ data })}
              blank={(): DataNeed => ({ id: rowId(), source: "", need: "required", freshness: "" })}
            />
          </Step>

          <Step n="04" title="Inputs" hint="Field, type, default, rule">
            <RowsEditor
              id="inputs"
              rowLabel="input"
              columns={INPUT_COLUMNS}
              rows={draft.inputs}
              onChange={(inputs) => patch({ inputs })}
              blank={() => ({ id: rowId(), field: "", type: "", fallback: "", rule: "" })}
            />
          </Step>

          <Step n="05" title="Services it calls" hint="The services that do the calculation">
            <ListEditor id="services" label="service" mono addHint="Type a service name, then Add" items={draft.services} onChange={(svc) => patch({ services: svc })} />
          </Step>

          <Step n="06" title="What the answer shows" hint="Response components">
            <ListEditor id="outputs" label="response component" addHint="Type a component, then Add" items={draft.outputs} onChange={(outputs) => patch({ outputs })} />
          </Step>

          <Step n="07" title="Guardrails" hint="Rules every answer must follow">
            <ListEditor id="guardrails" label="guardrail" addHint="Type a rule, then Add" items={draft.guardrails} onChange={(guardrails) => patch({ guardrails })} />
          </Step>

          <Step n="08" title="Triggers and delivery" hint="When it runs">
            <RowsEditor
              id="triggers"
              rowLabel="trigger"
              columns={TRIGGER_COLUMNS}
              rows={draft.triggers}
              onChange={(triggers) => patch({ triggers })}
              blank={() => ({ id: rowId(), type: "", detail: "" })}
            />
          </Step>
        </div>

        {/* ── what the draft produces ── */}
        <div className="cp-scroll flex flex-col min-w-0" style={compact ? { gap: 12 } : { gap: 12, position: "sticky", top: 12, maxHeight: "calc(100vh - 120px)", overflowY: "auto" }}>
          <div data-testid="builder-preview" className="cp-card flex flex-col" style={{ gap: 10, padding: "16px 18px" }}>
            <div className="flex flex-wrap items-center justify-between" style={{ gap: 8 }}>
              <Eyebrow>How it would appear in the Copilot</Eyebrow>
              {answerClass && <Pill>{answerClass}</Pill>}
            </div>
            {sample ? (
              <span data-testid="builder-preview-question" style={{ alignSelf: "flex-end", maxWidth: "90%", padding: "10px 14px", borderRadius: "14px 14px 4px 14px", background: "var(--bg-3)", fontSize: 13, overflowWrap: "anywhere" }}>{sample}</span>
            ) : (
              <span style={QUIET}>Add a question in step 02 to see it asked here.</span>
            )}
            {(services.length > 0 || draft.outputs.length > 0) && (
              <div className="flex items-start" style={{ gap: 10 }}>
                <span className="nv-mark" aria-hidden style={{ width: 22, height: 22, fontSize: 13, flex: "none" }}>न</span>
                <div className="flex flex-col min-w-0" style={{ gap: 6 }}>
                  {trace && <span data-testid="builder-preview-trace" style={{ fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.06em", textTransform: "uppercase", color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>{trace}</span>}
                  <div className="flex flex-wrap" style={{ gap: 6 }}>
                    {draft.outputs.map((o) => (
                      <span key={o} data-testid="builder-preview-output" style={{ fontSize: 12, padding: "5px 9px", borderRadius: 8, border: "1px dashed var(--line-3)", color: "var(--cp-ink-2)" }}>{o}</span>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>

          <div className="cp-card flex flex-col" style={{ gap: 8, padding: "16px 18px" }}>
            <div className="flex flex-wrap items-baseline justify-between" style={{ gap: "4px 8px" }}>
              <Eyebrow>Generated tool contract</Eyebrow>
              <span className="cp-mono-note">Local draft · not saved</span>
            </div>
            {contract ? (
              <pre data-testid="builder-contract" className="m-0" style={{ fontFamily: "var(--mono)", fontSize: 11, lineHeight: 1.6, color: "var(--cp-ink-2)", whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{contract}</pre>
            ) : (
              <span data-testid="builder-contract-empty" style={QUIET}>Nothing typed yet. The contract is written here from the form as you fill it in.</span>
            )}
            <div className="flex flex-wrap items-center" style={{ gap: "6px 12px", paddingTop: 4 }}>
              <Btn data-testid="builder-copy" disabled={!contract} onClick={copyContract}>{copied === "done" ? "Copied" : "Copy contract"}</Btn>
              {copied === "failed" && <span role="status" style={QUIET}>The browser blocked copying. Select the text above instead.</span>}
            </div>
          </div>

          <div data-testid="builder-checklist" className="cp-card flex flex-col" style={{ gap: 8, padding: "16px 18px" }}>
            <div className="flex flex-wrap items-baseline justify-between" style={{ gap: "4px 8px" }}>
              <Eyebrow>Release checklist</Eyebrow>
              <span className="cp-mono-note"><span data-testid="builder-checklist-done">{doneCount}</span> of {checks.length} parts filled in</span>
            </div>
            {checks.map((c) => (
              <div key={c.key} data-testid={`builder-check-${c.key}`} data-done={c.done} className="flex justify-between" style={{ gap: 10, fontSize: 13 }}>
                <span style={{ color: "var(--cp-ink-2)" }}>{c.label}</span>
                <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: c.done ? "var(--mint)" : "var(--cp-ink-3)" }}>{c.status}</span>
              </div>
            ))}
            {BACKEND_STEPS.map((label) => (
              <div key={label} className="flex justify-between" style={{ gap: 10, fontSize: 13 }}>
                <span style={{ color: "var(--cp-ink-2)" }}>{label}</span>
                <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--amber)" }}>Not connected</span>
              </div>
            ))}
            <div className="flex flex-wrap" style={{ gap: 8, paddingTop: 8 }}>
              <Btn data-testid="builder-save" disabled title="Not connected: there is no tool-definition store to save to">Save draft</Btn>
              <Btn data-testid="builder-run-tests" disabled title="Not connected: there is no test-prompt runner">Run test prompts</Btn>
              <Btn data-testid="builder-send-review" variant="primary" disabled title="Not connected: there is no review workflow to send it to">Send for review</Btn>
            </div>
            <Btn data-testid="builder-clear" variant="ghost" style={{ alignSelf: "flex-start", paddingLeft: 0 }} onClick={clearDraft}>Clear this draft</Btn>
          </div>
        </div>
      </div>

      <NotConnected
        testId="builder-not-connected"
        title="Saving, AI drafting, tests and review need a backend"
        body="This page is a working editor, but nothing it produces leaves the browser. A defined tool does not reach any user’s Copilot."
        needs={[
          "A tool-definition store with an API to create, list, version and update definitions",
          "A drafting service that turns a one-line description into a filled-in definition (for “Draft it”)",
          "A test-prompt runner that executes a draft against saved prompts and reports pass or fail",
          "A review workflow with engineering and compliance approval, each approval recorded",
          "A per-persona rollout switch that the chat pipeline reads before it offers the tool",
        ]}
      />

      <Footnote>This draft is kept in this browser only · nothing on this page is sent to the server</Footnote>
    </Screen>
  );
}
