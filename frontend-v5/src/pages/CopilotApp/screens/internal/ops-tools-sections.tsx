/**
 * Tool registry — the sections that sit beside the routing agents: the answer
 * models, the switch in front of the insight writer, the prompt registry and
 * the feature switches. Each reads one endpoint (ops-platform-data.ts) and
 * shows its own loading, error and empty state.
 */
import { Link } from "react-router-dom";
import { DataTable, Pill, Section, fmtNum, relTime, type Column, type Tone } from "../../components/ui";
import { QueryBlock } from "./shared";
import {
  useAiCircuit, useAnswerModels, useFeatureFlags, usePromptRegistry,
  type AiCircuit, type AnswerModel, type FeatureFlag, type PromptEntry,
} from "./ops-platform-data";

const mono = { fontFamily: "var(--mono)", fontSize: 12, color: "var(--cp-ink)" } as const;

// ── answer models ────────────────────────────────────────────────────────

const PROVIDER: Record<string, string> = { openai: "OpenAI", anthropic: "Anthropic", gemini: "Google Gemini" };

const MODEL_COLUMNS: Column<AnswerModel>[] = [
  {
    key: "label", header: "Model", width: "minmax(0,1.3fr)",
    render: (m) => <span data-testid="tools-model-row" data-model={m.id} style={{ color: "var(--cp-ink)" }}>{m.label}</span>,
  },
  { key: "provider", header: "Provider", width: "minmax(0,0.9fr)", render: (m) => PROVIDER[m.provider ?? ""] ?? (m.provider || "—") },
  { key: "sent", header: "Sent to the provider as", width: "minmax(0,1.5fr)", render: (m) => <span style={mono} title={m.underlying ?? undefined}>{m.underlying || "—"}</span> },
  {
    key: "default", header: "Picker", width: "90px",
    render: (m) => (m.is_default ? <span data-testid="tools-model-default"><Pill tone="mint">Default</Pill></span> : <span style={{ color: "var(--cp-ink-3)" }}>Optional</span>),
  },
  { key: "notes", header: "Notes", width: "minmax(0,2fr)", render: (m) => <span title={m.notes ?? undefined}>{m.notes || "—"}</span> },
];

export function AnswerModels() {
  const models = useAnswerModels();
  return (
    <QueryBlock
      query={models}
      what="The answer models"
      isEmpty={(rows) => rows.length === 0}
      empty={{ title: "No answer models are configured", body: "The backend returned an empty model list, so the chat has no model to pick." }}
      emptyTestId="tools-models-empty"
    >
      {(rows) => (
        <Section flush title={<>Answer models · <span data-testid="tools-model-count">{rows.length}</span></>} note="What the chat’s model picker offers">
          <DataTable columns={MODEL_COLUMNS} rows={rows} rowKey={(m) => m.id} minWidth={760} />
        </Section>
      )}
    </QueryBlock>
  );
}

// ── insight writer switch ────────────────────────────────────────────────

/** "in 40 minutes", "in 6 hours", "in 364 days". */
function inWords(seconds: number): string {
  if (seconds < 90) return "in about a minute";
  if (seconds < 5400) return `in ${Math.round(seconds / 60)} minutes`;
  if (seconds < 172_800) return `in ${Math.round(seconds / 3600)} hours`;
  return `in ${fmtNum(Math.round(seconds / 86_400))} days`;
}

function CircuitCard({ circuit }: { circuit: AiCircuit }) {
  const off = circuit.open;
  const left = circuit.seconds_remaining ?? 0;
  return (
    <div data-testid="tools-ai-circuit" className="cp-card flex flex-wrap items-center" style={{ gap: "8px 14px", padding: "14px 16px" }}>
      <span className="cp-eyebrow">Insight writer</span>
      <span data-testid="tools-ai-circuit-state"><Pill tone={off ? "danger" : "mint"}>{off ? "Model calls off" : "Model calls on"}</Pill></span>
      <span style={{ flex: "1 1 280px", fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
        {off
          ? <>Portfolio insights are being written by the rule-based fallback, not by a model. The switch is set to turn back on <span data-testid="tools-ai-circuit-until">{inWords(left)}</span> unless an admin resets it sooner.</>
          : "Portfolio insights are being written by the model. The switch turns itself off for five minutes when a model call fails."}
      </span>
      <span className="cp-mono-note" style={{ flexBasis: "100%" }}>Covers written insights only, not chat answers · reported by the server process that answered</span>
    </div>
  );
}

export function InsightWriterSwitch() {
  const circuit = useAiCircuit();
  return (
    <QueryBlock query={circuit} what="The insight writer’s status" rows={1}>
      {(c) => <CircuitCard circuit={c} />}
    </QueryBlock>
  );
}

// ── prompt registry ──────────────────────────────────────────────────────

const PROMPT_COLUMNS: Column<PromptEntry>[] = [
  {
    key: "name", header: "Prompt", width: "minmax(0,1.3fr)",
    render: (p) => <span data-testid="tools-prompt-row" data-prompt={p.name} style={mono} title={p.name}>{p.name}</span>,
  },
  { key: "does", header: "What it is for", width: "minmax(0,2.2fr)", render: (p) => <span title={p.description ?? undefined}>{p.description || "—"}</span> },
  { key: "used", header: "Sent by", width: "minmax(0,1.6fr)", render: (p) => <span style={{ ...mono, color: "var(--cp-ink-2)" }} title={p.used_in ?? undefined}>{p.used_in || "—"}</span> },
  { key: "length", header: "Characters", width: "90px", align: "right", num: true, render: (p) => fmtNum(p.length) },
  {
    key: "state", header: "Text", width: "90px", align: "right",
    render: (p) => <span data-testid="tools-prompt-state">{p.overridden ? <Pill tone="amber">Edited</Pill> : <span style={{ color: "var(--cp-ink-3)" }}>Built-in</span>}</span>,
  },
];

export function PromptRegistry() {
  const prompts = usePromptRegistry();
  return (
    <QueryBlock
      query={prompts}
      what="The prompt list"
      isEmpty={(rows) => rows.length === 0}
      empty={{ title: "No prompts are registered", body: "The backend’s prompt registry returned nothing." }}
      emptyTestId="tools-prompts-empty"
    >
      {(rows) => {
        const edited = rows.filter((p) => p.overridden).length;
        return (
          <Section
            flush
            title={<>System prompts · <span data-testid="tools-prompt-count">{rows.length}</span></>}
            note={<><span data-testid="tools-prompt-edited">{edited}</span> edited by an admin</>}
          >
            <DataTable columns={PROMPT_COLUMNS} rows={rows} rowKey={(p) => p.name} minWidth={820} />
          </Section>
        );
      }}
    </QueryBlock>
  );
}

// ── feature switches ─────────────────────────────────────────────────────

const MODE: Record<string, { label: string; tone: Tone }> = {
  everyone: { label: "On for everyone", tone: "mint" },
  allowlist: { label: "Allow-list", tone: "amber" },
  off: { label: "Off", tone: "ink" },
};

const FLAG_COLUMNS: Column<FeatureFlag>[] = [
  {
    key: "name", header: "Feature", width: "minmax(0,1.6fr)",
    render: (f) => <span data-testid="tools-flag-row" data-flag={f.key} style={{ color: "var(--cp-ink)" }} title={f.description ?? undefined}>{f.display_name || f.key}</span>,
  },
  { key: "key", header: "Key", width: "minmax(0,1.2fr)", render: (f) => <span style={{ ...mono, color: "var(--cp-ink-2)" }}>{f.key}</span> },
  {
    key: "mode", header: "State", width: "150px",
    render: (f) => {
      const m = MODE[f.mode] ?? { label: f.mode, tone: "ink" as Tone };
      return <span data-testid="tools-flag-mode"><Pill tone={m.tone}>{m.label}</Pill></span>;
    },
  },
  {
    key: "allow", header: "Accounts allowed", width: "130px", align: "right", num: true,
    // Only an allow-list has a count; "everyone" and "off" do not use the list.
    render: (f) => <span data-testid="tools-flag-allowed">{f.mode === "allowlist" ? fmtNum(f.allowlist?.length ?? 0) : "—"}</span>,
  },
];

export function FeatureSwitches() {
  const flags = useFeatureFlags();
  return (
    <QueryBlock
      query={flags}
      what="The feature switches"
      isEmpty={(d) => d.flags.length === 0}
      empty={{ title: "No feature switches are defined", body: "The backend returned an empty list of feature flags." }}
      emptyTestId="tools-flags-empty"
    >
      {(d) => {
        const changed = relTime(d.updated_at);
        return (
          <>
            <Section
              flush
              title={<>Feature switches · <span data-testid="tools-flag-count">{d.flags.length}</span></>}
              note={changed ? <span data-testid="tools-flags-changed">Last changed {changed}</span> : "Never changed from the defaults"}
            >
              <DataTable columns={FLAG_COLUMNS} rows={d.flags} rowKey={(f) => f.key} minWidth={640} />
            </Section>
            <Link to="/admin" className="cp-link" style={{ fontSize: 13, alignSelf: "flex-start" }}>Switches and prompt text are changed in the admin console ›</Link>
          </>
        );
      }}
    </QueryBlock>
  );
}
