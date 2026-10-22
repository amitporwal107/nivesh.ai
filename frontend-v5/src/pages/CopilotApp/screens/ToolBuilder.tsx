/**
 * Tool builder — an admin describes a new Copilot tool: who it is for, what it
 * answers, the data and inputs it needs, the services it calls, what the
 * answer shows, its guardrails and its triggers.
 * Design: frontend-v5/design/nivesh-copilot/NVToolBuilder.dc.html.
 *
 * There is no tool-definition backend (services/adapters/builder.adapter.ts is
 * the portfolio builder), so this is a local editor: the preview, the contract
 * and the checklist are computed from the draft (screens/internal/tool-draft.ts),
 * which is kept in this browser. Saving, drafting by AI, test prompts and review
 * are disabled controls with a note on what they need.
 *
 * A draft starts empty, or from a template of a tool that already exists
 * (screens/internal/tool-templates.ts): one per tool in the shell, written out
 * as built, with the blocks that are not connected listed beside it. Data rows
 * are picked from the data source pool (screens/internal/data-sources.ts), or
 * typed. The only status shown for a source is its data connection (connected,
 * partial, planned). The design's sample tools and their lifecycle statuses are
 * not shown.
 */
import { useMemo, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from "react";
import { Btn, Eyebrow, Footnote, NotConnected, Pill, Screen } from "../components/ui";
import { useCopilotShell } from "../lib/shell-context";
import { MODE_LABEL, type Mode } from "../lib/views";
import {
  DATA_SOURCES, STATUS_LABEL, STATUS_TONE, countByStatus, matchSource,
  type DataSource, type SourceStatus,
} from "./internal/data-sources";
import { OpsHeader } from "./internal/shared";
import {
  buildContract, checklist, rowId, useToolDraft,
  type DataNeed, type ToolInput, type Trigger,
} from "./internal/tool-draft";
import {
  GROUP_LABEL, TOOL_TEMPLATES, draftFromTemplate, templateById, templatesByGroup, templatesUsing,
  type ToolTemplate,
} from "./internal/tool-templates";

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
function RowsEditor<R extends { id: string }>({ id, rowLabel, columns, rows, onChange, blank, rowNote }: {
  id: string;
  /** What one row is, e.g. "data source". */
  rowLabel: string;
  columns: ColumnDef<R>[];
  rows: R[];
  onChange: (rows: R[]) => void;
  blank: () => R;
  /** A line under a row's fields, e.g. the connection status of its data source. */
  rowNote?: (row: R) => ReactNode;
}) {
  const setCell = (rowIndex: number, key: ColumnDef<R>["key"], value: string) => {
    onChange(rows.map((r, i) => (i === rowIndex ? ({ ...r, [key]: value } as R) : r)));
  };
  return (
    <div className="flex flex-col" style={{ gap: 8 }}>
      {rows.map((r, i) => (
        <div key={r.id} role="group" aria-label={`${rowLabel} ${i + 1}`} data-testid={`builder-${id}-row`} className="flex items-start" style={{ gap: 8, paddingTop: i ? 8 : 0, borderTop: i ? "1px solid var(--cp-line)" : undefined }}>
          <div className="flex flex-col min-w-0" style={{ flex: "1 1 0", gap: 6 }}>
            <div className="grid min-w-0" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(112px,1fr))", gap: 8 }}>
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
            {rowNote?.(r)}
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

// ── data source pool ─────────────────────────────────────────────────────

const STATUS_ORDER: SourceStatus[] = ["connected", "partial", "planned"];

const SMALL: CSSProperties = { fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" };

function routesLabel(source: DataSource): string {
  const n = source.endpoints.length;
  return n === 0 ? "No app route" : `${n} app ${n === 1 ? "route" : "routes"}`;
}

/** Under a data row: the connection status of the pool source it names. */
function DataRowStatus({ row }: { row: DataNeed }) {
  const source = matchSource(row.source);
  if (!source) {
    return row.source.trim() ? <span style={SMALL}>Free text · not a source from the pool</span> : null;
  }
  return (
    <div className="flex flex-wrap items-center" style={{ gap: "4px 8px" }}>
      <span data-testid="builder-data-status" data-status={source.status} data-source={source.id}>
        <Pill tone={STATUS_TONE[source.status]} title={source.note}>{STATUS_LABEL[source.status]}</Pill>
      </span>
      <span style={SMALL}>{routesLabel(source)} · {source.provider}</span>
    </div>
  );
}

/** Adds a data row from the pool. A source the draft already names is not offered twice. */
function SourcePicker({ rows, onAdd }: { rows: DataNeed[]; onAdd: (source: DataSource) => void }) {
  const used = new Set<string>();
  for (const r of rows) {
    const source = matchSource(r.source);
    if (source) used.add(source.id);
  }
  return (
    <div className="flex flex-col" style={{ gap: 6 }}>
      <label htmlFor="builder-source-picker" className="cp-eyebrow">Add from the data source pool</label>
      <select
        id="builder-source-picker"
        data-testid="builder-source-picker"
        // Always back on the prompt: choosing a source adds its row at once.
        value=""
        onChange={(e) => {
          const source = DATA_SOURCES.find((s) => s.id === e.target.value);
          if (source) onAdd(source);
        }}
        style={{ ...FIELD, padding: "7px 10px", fontSize: 13 }}
      >
        <option value="">Choose a source to add its row…</option>
        {STATUS_ORDER.map((status) => (
          <optgroup key={status} label={STATUS_LABEL[status]}>
            {DATA_SOURCES.filter((s) => s.status === status).map((s) => (
              <option key={s.id} value={s.id} disabled={used.has(s.id)}>{s.name}{used.has(s.id) ? " · added" : ""}</option>
            ))}
          </optgroup>
        ))}
      </select>
    </div>
  );
}

const TH: CSSProperties = {
  position: "sticky",
  top: 0,
  zIndex: 1,
  textAlign: "left",
  verticalAlign: "bottom",
  padding: "10px 12px",
  background: "var(--bg-1)",
  borderBottom: "1px solid var(--cp-line)",
  fontWeight: 400,
  whiteSpace: "nowrap",
};

const TD: CSSProperties = {
  textAlign: "left",
  verticalAlign: "top",
  padding: "11px 12px",
  borderBottom: "1px solid var(--cp-line)",
  fontSize: 13,
  fontWeight: 400,
  lineHeight: 1.5,
  color: "var(--cp-ink-2)",
};

const TEMPLATE_GROUPS = templatesByGroup();

/**
 * The whole pool as a table, with the tools that use each source. Picking a
 * tool narrows it to that tool's sources and shows what the tool needs of each.
 */
function SourcePool({ loaded }: { loaded: ToolTemplate | undefined }) {
  const [open, setOpen] = useState(true);
  const [toolId, setToolId] = useState("");
  const tool = templateById(toolId);
  const sources = tool ? DATA_SOURCES.filter((s) => tool.data.some((d) => d.source === s.id)) : DATA_SOURCES;
  const counts = countByStatus(sources);
  const summary = [
    `${sources.length} ${sources.length === 1 ? "source" : "sources"}`,
    ...STATUS_ORDER.filter((st) => counts[st] > 0).map((st) => `${counts[st]} ${STATUS_LABEL[st].toLowerCase()}`),
  ].join(" · ");

  return (
    <section aria-label="Data source pool" data-testid="builder-pool" data-open={open} className="cp-card flex flex-col min-w-0">
      <div className="flex flex-wrap items-baseline" style={{ gap: "4px 12px", padding: "14px 18px" }}>
        <h2 className="m-0" style={{ fontSize: 15, fontWeight: 500 }}>
          <button
            type="button"
            data-testid="builder-pool-toggle"
            aria-expanded={open}
            aria-controls="builder-pool-body"
            onClick={() => setOpen((o) => !o)}
            style={{ display: "inline-flex", alignItems: "baseline", gap: 8, padding: 0, border: 0, background: "none", color: "var(--cp-ink)", font: "inherit", cursor: "pointer" }}
          >
            <span aria-hidden style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--mint)" }}>{open ? "−" : "+"}</span>
            Data source pool
          </button>
        </h2>
        <span style={{ flex: 1 }} />
        <span data-testid="builder-pool-summary" className="cp-mono-note">{summary}</span>
      </div>

      {open && (
        <div id="builder-pool-body" className="flex flex-col min-w-0" style={{ gap: 12, borderTop: "1px solid var(--cp-line)", paddingTop: 14 }}>
          <p className="m-0 cp-pretty" style={{ ...QUIET, padding: "0 18px", maxWidth: 760 }}>
            Every tool takes its data rows from this pool. The status says one thing only: whether the data reaches the app today (connected), reaches it in part (partial), or does not reach it yet (planned).
          </p>
          <div className="flex flex-wrap items-center" style={{ gap: "8px 10px", padding: "0 18px" }}>
            <label htmlFor="builder-pool-filter" className="cp-eyebrow">Show the pool for</label>
            <select
              id="builder-pool-filter"
              data-testid="builder-pool-filter"
              value={toolId}
              onChange={(e) => setToolId(e.target.value)}
              style={{ ...FIELD, width: "auto", flex: "0 1 260px", padding: "7px 10px", fontSize: 13 }}
            >
              <option value="">All tools</option>
              {TEMPLATE_GROUPS.map((g) => (
                <optgroup key={g.group} label={GROUP_LABEL[g.group]}>
                  {g.templates.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                </optgroup>
              ))}
            </select>
            {loaded && toolId !== loaded.id && (
              <Btn variant="ghost" data-testid="builder-pool-filter-loaded" onClick={() => setToolId(loaded.id)}>Only what {loaded.name} uses</Btn>
            )}
            {tool && <Btn variant="ghost" data-testid="builder-pool-filter-clear" onClick={() => setToolId("")}>Show all</Btn>}
          </div>

          {/* The table scrolls inside this box, both ways; the page does not. */}
          <div role="region" aria-label="Data source pool table" tabIndex={0} className="cp-scroll" style={{ overflow: "auto", maxHeight: 560, borderTop: "1px solid var(--cp-line)" }}>
            <table data-testid="builder-pool-table" style={{ width: "100%", minWidth: tool ? 1560 : 1400, borderCollapse: "separate", borderSpacing: 0 }}>
              <caption className="sr-only">
                {tool ? `Data sources the ${tool.name} tool uses` : "Every data source in the pool"}: name, connection status, the tools that use it, what it is, the app routes that serve it, freshness, provider and note.
              </caption>
              <thead>
                <tr>
                  <th scope="col" className="cp-mono-note" style={{ ...TH, minWidth: 180, paddingLeft: 18 }}>Source</th>
                  <th scope="col" className="cp-mono-note" style={TH}>Status</th>
                  {tool && <th scope="col" className="cp-mono-note" style={{ ...TH, minWidth: 180 }}>What {tool.name} needs</th>}
                  <th scope="col" className="cp-mono-note" style={{ ...TH, minWidth: 190 }}>Used by</th>
                  <th scope="col" className="cp-mono-note" style={{ ...TH, minWidth: 230 }}>What it is</th>
                  <th scope="col" className="cp-mono-note" style={{ ...TH, minWidth: 250 }}>App routes</th>
                  <th scope="col" className="cp-mono-note" style={{ ...TH, minWidth: 180 }}>Freshness</th>
                  <th scope="col" className="cp-mono-note" style={{ ...TH, minWidth: 170 }}>Provider</th>
                  <th scope="col" className="cp-mono-note" style={{ ...TH, minWidth: 240, paddingRight: 18 }}>Note</th>
                </tr>
              </thead>
              <tbody>
                {sources.map((s) => {
                  const users = templatesUsing(s.id);
                  const need = tool?.data.find((d) => d.source === s.id);
                  return (
                    <tr key={s.id} data-testid="builder-pool-row" data-source={s.id} data-status={s.status}>
                      <th scope="row" data-testid="builder-pool-name" style={{ ...TD, paddingLeft: 18, color: "var(--cp-ink)", fontWeight: 500 }}>{s.name}</th>
                      <td style={TD}>
                        <span data-testid="builder-pool-status" data-status={s.status}>
                          <Pill tone={STATUS_TONE[s.status]}>{STATUS_LABEL[s.status]}</Pill>
                        </span>
                      </td>
                      {tool && (
                        <td data-testid="builder-pool-need" style={TD}>
                          {need ? `${need.need === "required" ? "Required" : "Optional"} · ${need.freshness ?? s.freshness}` : ""}
                        </td>
                      )}
                      <td data-testid="builder-pool-used-by" data-count={users.length} style={TD}>
                        {users.length === 0 ? (
                          <span style={{ color: "var(--cp-ink-3)" }}>No tool yet</span>
                        ) : (
                          <>
                            <span style={{ color: "var(--cp-ink)" }}>{users.length} {users.length === 1 ? "tool" : "tools"}</span>
                            <span style={{ display: "block", fontSize: 12, color: "var(--cp-ink-3)" }}>{users.map((t) => t.name).join(", ")}</span>
                          </>
                        )}
                      </td>
                      <td style={TD}>{s.what}</td>
                      <td style={TD}>
                        {s.endpoints.length === 0 ? (
                          <span style={{ color: "var(--cp-ink-3)" }}>No app route</span>
                        ) : (
                          <ul className="m-0 flex flex-col" style={{ gap: 2, padding: 0, listStyle: "none", fontFamily: "var(--mono)", fontSize: 11, lineHeight: 1.5 }}>
                            {s.endpoints.map((e) => <li key={e} style={{ overflowWrap: "anywhere" }}>{e}</li>)}
                          </ul>
                        )}
                      </td>
                      <td style={TD}>{s.freshness}</td>
                      <td style={TD}>{s.provider}</td>
                      <td style={{ ...TD, paddingRight: 18, fontSize: 12, color: "var(--cp-ink-3)" }}>{s.note ?? ""}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}

// ── existing tools as templates ──────────────────────────────────────────

/** One button per existing tool, under Investor / Trader / Advisor / All, and a note on the one loaded. */
function TemplatePicker({ loaded, edited, onLoad }: {
  loaded: ToolTemplate | undefined;
  /** The draft no longer matches the loaded template. */
  edited: boolean;
  onLoad: (t: ToolTemplate) => void;
}) {
  return (
    <section aria-label="Start from an existing tool" data-testid="builder-templates" className="cp-card flex flex-col min-w-0" style={{ gap: 12, padding: "16px 18px" }}>
      <div className="flex flex-wrap items-baseline" style={{ gap: "4px 10px" }}>
        <h2 className="m-0" style={{ fontSize: 15, fontWeight: 500 }}>Start from an existing tool</h2>
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>{TOOL_TEMPLATES.length} tools in the app today, each written out as this builder would define it</span>
      </div>

      {TEMPLATE_GROUPS.map((g) => (
        <div key={g.group} role="group" aria-label={`${GROUP_LABEL[g.group]} tools`} data-testid="builder-template-group" data-group={g.group} className="flex flex-wrap items-start" style={{ gap: "6px 12px" }}>
          <span className="cp-eyebrow" style={{ flex: "0 0 64px", paddingTop: 12 }}>{GROUP_LABEL[g.group]}</span>
          <div className="flex flex-wrap min-w-0" style={{ flex: "1 1 220px", gap: 8 }}>
            {g.templates.map((t) => {
              const on = loaded?.id === t.id;
              const n = t.data.length;
              return (
                <button
                  key={t.id}
                  type="button"
                  data-testid="builder-template"
                  data-template={t.id}
                  aria-pressed={on}
                  onClick={() => onLoad(t)}
                  className="flex flex-col"
                  style={{
                    gap: 2,
                    padding: "8px 12px",
                    borderRadius: 12,
                    textAlign: "left",
                    cursor: "pointer",
                    fontFamily: "var(--sans)",
                    color: "var(--cp-ink)",
                    background: on ? "var(--mint-soft)" : "var(--bg-2)",
                    border: `1px solid ${on ? "var(--mint-line)" : "var(--line-2)"}`,
                  }}
                >
                  <span style={{ fontSize: 13, fontWeight: 500 }}>{t.name}</span>
                  <span data-testid="builder-template-sources" style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--cp-ink-3)" }}>{n} data {n === 1 ? "source" : "sources"}</span>
                </button>
              );
            })}
          </div>
        </div>
      ))}

      {loaded && (
        <div data-testid="builder-template-loaded" data-template={loaded.id} role="status" className="flex flex-col" style={{ gap: 8, padding: "12px 14px", borderRadius: 12, border: "1px dashed var(--line-3)", background: "var(--bg-2)" }}>
          <span style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
            Loaded from <span style={{ color: "var(--cp-ink)", fontWeight: 500 }}>{loaded.name}</span>{edited ? ", and edited since" : ""}. Every field below can be changed; the tool itself is not affected.
          </span>
          <div data-testid="builder-template-gaps" data-count={loaded.gaps.length} className="flex flex-col" style={{ gap: 6 }}>
            {loaded.gaps.length > 0 ? (
              <>
                <span className="cp-mono-note" style={{ color: "var(--amber)" }}>Not connected in this tool as built · not part of the contract</span>
                <ul className="m-0 flex flex-col" style={{ gap: 4, paddingLeft: 16, fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
                  {loaded.gaps.map((g) => <li key={g}>{g}</li>)}
                </ul>
              </>
            ) : (
              <span style={SMALL}>No block of this tool is recorded as not connected.</span>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

// ── screen ───────────────────────────────────────────────────────────────

export default function ToolBuilderScreen() {
  const { compact } = useCopilotShell();
  const draft = useToolDraft((s) => s.draft);
  const templateId = useToolDraft((s) => s.templateId);
  const patch = useToolDraft((s) => s.patch);
  const load = useToolDraft((s) => s.load);
  const reset = useToolDraft((s) => s.reset);
  const [copied, setCopied] = useState<"idle" | "done" | "failed">("idle");

  const contract = buildContract(draft);
  const loaded = templateById(templateId);
  // The contract text covers every field, so it tells an untouched template from an edited one.
  const loadedContract = useMemo(() => (loaded ? buildContract(draftFromTemplate(loaded)) : ""), [loaded]);
  const edited = !!loaded && contract !== loadedContract;
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

  const loadTemplate = (t: ToolTemplate) => {
    // Ask before replacing something typed. An empty draft, or a template nobody
    // has edited, holds nothing that would be lost.
    const nothingTyped = contract === "" || (!!loaded && !edited);
    if (!nothingTyped && !window.confirm(`Replace this draft with the ${t.name} template? Everything typed in the form is removed from this browser.`)) return;
    load(t.id, draftFromTemplate(t));
    setCopied("idle");
  };

  const addSource = (source: DataSource) => {
    patch({ data: [...draft.data, { id: rowId(), source: source.name, need: "required", freshness: source.freshness }] });
  };

  return (
    <Screen testId="screen-builder" width={1120}>
      <OpsHeader
        area="Tool builder"
        title={<>Draft a tool <em>definition</em>.</>}
        sub="Start from a tool that already exists, or from an empty form. Describe the objective, the data it needs and the rules it must follow; the contract on the right is written from the form. Saving, drafting by AI, test prompts and review are not connected yet, so a draft stays in this browser."
      />

      <TemplatePicker loaded={loaded} edited={edited} onLoad={loadTemplate} />

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

          <Step n="03" title="Data it needs" hint="From the pool or typed: source, need, freshness">
            <SourcePicker rows={draft.data} onAdd={addSource} />
            <RowsEditor
              id="data"
              rowLabel="data source"
              columns={DATA_COLUMNS}
              rows={draft.data}
              onChange={(data) => patch({ data })}
              blank={(): DataNeed => ({ id: rowId(), source: "", need: "required", freshness: "" })}
              rowNote={(row) => <DataRowStatus row={row} />}
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

      <SourcePool loaded={loaded} />

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
