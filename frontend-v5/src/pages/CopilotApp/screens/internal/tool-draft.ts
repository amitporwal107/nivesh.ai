/**
 * Tool builder — the draft being edited, and everything derived from it.
 *
 * There is no tool-definition backend, so the draft lives in this browser only
 * (localStorage, through the app's safe storage adapter). It starts empty: the
 * contract text and the checklist below are computed from what the admin has
 * typed and from nothing else.
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { z } from "zod";
import { createSafeStorageAdapter } from "@/lib/safe-storage";

const DataNeedC = z.object({
  id: z.string(),
  source: z.string(),
  need: z.enum(["required", "optional"]),
  freshness: z.string(),
});
export type DataNeed = z.infer<typeof DataNeedC>;

const ToolInputC = z.object({
  id: z.string(),
  field: z.string(),
  type: z.string(),
  /** Default value, as typed. */
  fallback: z.string(),
  rule: z.string(),
});
export type ToolInput = z.infer<typeof ToolInputC>;

const TriggerC = z.object({ id: z.string(), type: z.string(), detail: z.string() });
export type Trigger = z.infer<typeof TriggerC>;

const ToolDraftC = z.object({
  name: z.string(),
  personas: z.array(z.enum(["investor", "trader", "advisor"])),
  /** How the answer is classified, e.g. research vs personalised. Free text. */
  answerClass: z.string(),
  objective: z.string(),
  questions: z.array(z.string()),
  data: z.array(DataNeedC),
  inputs: z.array(ToolInputC),
  services: z.array(z.string()),
  outputs: z.array(z.string()),
  guardrails: z.array(z.string()),
  triggers: z.array(TriggerC),
});
export type ToolDraft = z.infer<typeof ToolDraftC>;

export const EMPTY_DRAFT: ToolDraft = {
  name: "",
  personas: [],
  answerClass: "",
  objective: "",
  questions: [],
  data: [],
  inputs: [],
  services: [],
  outputs: [],
  guardrails: [],
  triggers: [],
};

/** A fresh id for an editable row. */
export function rowId(): string {
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`;
}

interface ToolDraftState {
  draft: ToolDraft;
  patch: (p: Partial<ToolDraft>) => void;
  reset: () => void;
}

export const useToolDraft = create<ToolDraftState>()(
  persist(
    (set) => ({
      draft: EMPTY_DRAFT,
      patch: (p) => set((s) => ({ draft: { ...s.draft, ...p } })),
      reset: () => set({ draft: EMPTY_DRAFT }),
    }),
    {
      name: "nivesh.copilot.tool-draft",
      storage: createSafeStorageAdapter(),
      // A stored draft that no longer fits the shape is dropped, not half-loaded.
      merge: (persisted, current) => {
        const stored = (persisted as { draft?: unknown } | null | undefined)?.draft;
        const parsed = ToolDraftC.safeParse(stored);
        return { ...current, draft: parsed.success ? parsed.data : current.draft };
      },
    },
  ),
);

// ── derived from the draft ───────────────────────────────────────────────

/** "My new tool" → "my_new_tool". */
export function slugify(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}

const oneLine = (s: string) => s.replace(/\s+/g, " ").trim();
const filled = (xs: string[]) => xs.map(oneLine).filter(Boolean);

/** The rows of each table that have their first column filled in. */
export function filledRows(d: ToolDraft) {
  return {
    data: d.data.filter((r) => r.source.trim()),
    inputs: d.inputs.filter((r) => r.field.trim()),
    triggers: d.triggers.filter((r) => r.type.trim() || r.detail.trim()),
  };
}

/**
 * The contract text for the draft. Every line comes from a field the admin
 * filled in; an empty draft gives an empty string.
 */
export function buildContract(d: ToolDraft): string {
  const rows = filledRows(d);
  const lines: string[] = [];
  const slug = slugify(d.name);
  if (slug) lines.push(`tool: ${slug}`);
  if (d.personas.length) lines.push(`personas: [${d.personas.join(", ")}]`);
  if (oneLine(d.answerClass)) lines.push(`class: ${oneLine(d.answerClass)}`);
  if (oneLine(d.objective)) lines.push(`objective: ${oneLine(d.objective)}`);
  const questions = filled(d.questions);
  if (questions.length) lines.push("answers:", ...questions.map((q) => `  - ${q}`));
  if (rows.inputs.length) {
    lines.push("inputs:", ...rows.inputs.map((i) => {
      const type = oneLine(i.type);
      const fallback = oneLine(i.fallback);
      const rule = oneLine(i.rule);
      return `  ${oneLine(i.field)}${type ? `: ${type}` : ""}${fallback ? ` = ${fallback}` : ""}${rule ? `  # ${rule}` : ""}`;
    }));
  }
  if (rows.data.length) {
    lines.push("data:", ...rows.data.map((r) => {
      const freshness = oneLine(r.freshness);
      return `  - ${oneLine(r.source)} (${r.need}${freshness ? `, ${freshness}` : ""})`;
    }));
  }
  const services = filled(d.services);
  if (services.length) lines.push(`calls: [${services.join(", ")}]`);
  const outputs = filled(d.outputs);
  if (outputs.length) lines.push("shows:", ...outputs.map((o) => `  - ${o}`));
  const guardrails = filled(d.guardrails);
  if (guardrails.length) lines.push("guardrails:", ...guardrails.map((g) => `  - ${g}`));
  if (rows.triggers.length) {
    lines.push("triggers:", ...rows.triggers.map((t) => {
      const type = oneLine(t.type);
      const detail = oneLine(t.detail);
      return `  - ${type && detail ? `${type}: ${detail}` : type || detail}`;
    }));
  }
  return lines.join("\n");
}

export interface CheckItem {
  key: string;
  label: string;
  done: boolean;
  /** Short status shown at the right of the row. */
  status: string;
}

const counted = (n: number) => (n > 0 ? `${n} added` : "None yet");

/** Which parts of the definition are filled in. */
export function checklist(d: ToolDraft): CheckItem[] {
  const rows = filledRows(d);
  const hasName = slugify(d.name).length > 0;
  const hasPersona = d.personas.length > 0;
  const lists: Array<[key: string, label: string, n: number]> = [
    ["questions", "Questions it answers", filled(d.questions).length],
    ["data", "Data it needs", rows.data.length],
    ["inputs", "Inputs", rows.inputs.length],
    ["services", "Services it calls", filled(d.services).length],
    ["outputs", "What the answer shows", filled(d.outputs).length],
    ["guardrails", "Guardrails", filled(d.guardrails).length],
    ["triggers", "Triggers", rows.triggers.length],
  ];
  return [
    {
      key: "identity",
      label: "Name and persona",
      done: hasName && hasPersona,
      status: hasName && hasPersona ? "Set" : !hasName ? "No name" : "No persona",
    },
    { key: "objective", label: "Objective", done: oneLine(d.objective).length > 0, status: oneLine(d.objective) ? "Written" : "Missing" },
    ...lists.map(([key, label, n]) => ({ key, label, done: n > 0, status: counted(n) })),
  ];
}
