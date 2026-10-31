/**
 * Suggestion cards for the Copilot home (backend: services/suggestions, routes/suggestions.py).
 *
 *   GET  /api/suggestions?tab=&mode=             a tab's cards, notices and the four tabs with their counts
 *   POST /api/suggestions/refresh                {tab, mode}  the same, market sources read again now
 *   POST /api/suggestions/{id}/feedback          {action}     dismissed | useful | not_relevant | completed
 *   GET  /api/suggestions/{id}/why                            the rule, its inputs with as-of dates
 *
 * A source that is stale or missing produces no card; the backend sends a notice saying which and why, and it is shown
 * as it arrives. Nothing is invented here: an unreadable response is an error state, not a list.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";
import { http } from "@/services/api/http";
import { useImpersonationStore } from "@/stores/impersonation.store";

export const TAB_KEYS = ["for_you", "market", "my_trades", "fno_lab"] as const;
export type SuggestionTab = (typeof TAB_KEYS)[number];
export type SuggestionClass = "informational" | "validated_signal" | "risk_alert";
export type SuggestionAction = "dismissed" | "useful" | "not_relevant" | "completed";

const InputC = z.object({
  name: z.string(),
  label: z.string(),
  as_of: z.string().nullable().optional(),
  status: z.string().optional(),
});

const SuggestionC = z.object({
  id: z.string(),
  tab: z.enum(TAB_KEYS),
  class: z.enum(["informational", "validated_signal", "risk_alert"]),
  class_label: z.string(),
  title: z.string(),
  why: z.string(),
  footer: z.string().nullable().optional(),
  query: z.string(),
  intent: z.string().nullable().optional(),
  template_id: z.string(),
  rule_id: z.string(),
  symbol: z.string().nullable().optional(),
  as_of: z.string().nullable().optional(),
  inputs: z.array(InputC).default([]),
  state: z.string().optional(),
});

const NoticeC = z.object({
  kind: z.string(),
  source: z.string(),
  as_of: z.string().nullable().optional(),
  text: z.string(),
  action: z.string().nullable().optional(),
});

const TabViewC = z.object({
  schema: z.literal("suggestions-v1"),
  tab: z.enum(TAB_KEYS),
  mode: z.string(),
  generated_at: z.string(),
  window: z.object({ today: z.string(), previous_session: z.string() }),
  tabs: z.array(z.object({ key: z.enum(TAB_KEYS), label: z.string(), count: z.number() })),
  suggestions: z.array(SuggestionC),
  notices: z.array(NoticeC),
});

const WhyC = z.object({
  id: z.string(),
  title: z.string().nullable().optional(),
  why: z.string().nullable().optional(),
  class: z.string().nullable().optional(),
  class_label: z.string().nullable().optional(),
  footer: z.string().nullable().optional(),
  query: z.string().nullable().optional(),
  rule: z.object({
    id: z.string().nullable().optional(),
    name: z.string().nullable().optional(),
    description: z.string().nullable().optional(),
    cooldown_hours: z.number().nullable().optional(),
  }).passthrough(),
  inputs: z.array(InputC).default([]),
  as_of: z.string().nullable().optional(),
  evaluated_at: z.string().nullable().optional(),
});

export type Suggestion = z.infer<typeof SuggestionC>;
export type SuggestionNotice = z.infer<typeof NoticeC>;
export type SuggestionTabView = z.infer<typeof TabViewC>;
export type SuggestionWhy = z.infer<typeof WhyC>;

export type SuggestionMode = "investor" | "trader";

/** Advisor mode has no suggestion audience of its own: it reads as investor (the client book has its own prompts). */
export const suggestionMode = (mode: string): SuggestionMode => (mode === "trader" ? "trader" : "investor");

function parse<S extends z.ZodTypeAny>(schema: S, data: unknown): z.output<S> {
  const r = schema.safeParse(data);
  if (!r.success) throw new Error("The suggestions response was not in the expected shape.");
  return r.data;
}

export function useSuggestions(tab: SuggestionTab, mode: SuggestionMode, enabled = true) {
  const profile = useImpersonationStore((s) => s.profileId);
  return useQuery<SuggestionTabView>({
    queryKey: ["copilot", "suggestions", profile ?? "self", mode, tab],
    enabled,
    staleTime: 60_000,
    retry: false,
    queryFn: async ({ signal }) => parse(TabViewC, (await http({ path: "/api/suggestions", query: { tab, mode }, signal })).data),
  });
}

export function useSuggestionActions(tab: SuggestionTab, mode: SuggestionMode) {
  const qc = useQueryClient();
  const profile = useImpersonationStore((s) => s.profileId);
  const key = ["copilot", "suggestions", profile ?? "self", mode, tab];
  const refresh = useMutation({
    mutationFn: async () => parse(TabViewC, (await http({ method: "POST", path: "/api/suggestions/refresh", body: { tab, mode } })).data),
    onSuccess: (view) => {
      qc.setQueryData(key, view);
      // The other tabs were evaluated together; drop their cached views so they are read fresh.
      void qc.invalidateQueries({ queryKey: ["copilot", "suggestions", profile ?? "self", mode], predicate: (q) => q.queryKey[4] !== tab });
    },
  });
  const feedback = useMutation({
    mutationFn: async (v: { id: string; action: SuggestionAction }) => {
      await http({ method: "POST", path: `/api/suggestions/${encodeURIComponent(v.id)}/feedback`, body: { action: v.action } });
      return v;
    },
    onSuccess: (v) => {
      if (v.action === "useful") return;
      // A dismissed / not relevant / completed card leaves the list now; the backend keeps it out until its cooldown.
      qc.setQueryData<SuggestionTabView>(key, (old) => old && ({
        ...old,
        suggestions: old.suggestions.filter((s) => s.id !== v.id),
        tabs: old.tabs.map((t) => (t.key === tab ? { ...t, count: Math.max(0, t.count - 1) } : t)),
      }));
    },
  });
  return { refresh, feedback };
}

export function useSuggestionWhy(id: string | null) {
  return useQuery<SuggestionWhy>({
    queryKey: ["copilot", "suggestion-why", id],
    enabled: !!id,
    staleTime: 60_000,
    retry: false,
    queryFn: async ({ signal }) => parse(WhyC, (await http({ path: `/api/suggestions/${encodeURIComponent(id as string)}/why`, signal })).data),
  });
}
