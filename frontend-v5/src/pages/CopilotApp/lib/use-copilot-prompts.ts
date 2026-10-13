/**
 * Suggested prompts for the Copilot home and ask box.
 *
 *   GET /api/copilot/suggested-prompts
 *
 * The backend ranks these for the signed-in user from their own portfolio:
 * each prompt carries a label, the question to send, what the user gets out of
 * it, and (when the backend computed one) a badge with a real figure such as
 * "Top pair 97% overlap". `use-chat.ts#useSuggestedPrompts` reads the same
 * endpoint but keeps only the labels; the home screen needs the rest.
 */
import { useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { http } from "@/services/api/http";
import { useImpersonationStore } from "@/stores/impersonation.store";

const PromptC = z.object({
  id: z.string().optional(),
  label: z.string().optional(),
  query: z.string().optional(),
  outcome: z.string().nullable().optional(),
  badge: z.string().nullable().optional(),
  tier: z.string().nullable().optional(),
  intent_category: z.string().nullable().optional(),
}).passthrough();

const ContextSummaryC = z.object({
  total_value: z.number().nullable().optional(),
  equity_pct: z.number().nullable().optional(),
  debt_pct: z.number().nullable().optional(),
  gold_pct: z.number().nullable().optional(),
  max_overlap_pct: z.number().nullable().optional(),
  action_count: z.number().nullable().optional(),
  fund_count: z.number().nullable().optional(),
}).passthrough();

const ResC = z.object({
  mode: z.string().nullable().optional(),
  persona: z.string().nullable().optional(),
  prompts: z.array(z.union([PromptC, z.string()])).default([]),
  context_summary: ContextSummaryC.nullable().optional(),
}).passthrough();

export interface CopilotPrompt {
  id: string;
  label: string;
  /** The question sent to the Copilot. */
  query: string;
  outcome?: string;
  /** A figure the backend computed for this user, e.g. "Equity 93% · Debt 0%". */
  badge?: string;
  category?: string;
}

export interface CopilotPrompts {
  prompts: CopilotPrompt[];
  /** Backend persona id, e.g. "mutual_fund_investor". */
  persona?: string;
  /** Who the backend ranked these for: "investor" (own portfolio) or
   *  "advisor" (the client book, at the advisor root). */
  audience?: string;
  context?: z.infer<typeof ContextSummaryC>;
}

const EMPTY: CopilotPrompts = { prompts: [] };

export function useCopilotPrompts() {
  // Same cache scoping as useSuggestedPrompts: an advisor's own prompts and a
  // client's prompts must not bleed across a context switch.
  const activeProfileId = useImpersonationStore((s) => s.profileId);
  return useQuery<CopilotPrompts>({
    queryKey: ["copilot", "prompts", activeProfileId ?? "self"],
    staleTime: 5 * 60_000,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/copilot/suggested-prompts", signal });
      const parsed = ResC.safeParse(res.data);
      if (!parsed.success) return EMPTY;
      const prompts: CopilotPrompt[] = [];
      parsed.data.prompts.forEach((p, i) => {
        if (typeof p === "string") {
          if (p.trim()) prompts.push({ id: `p${i}`, label: p, query: p });
          return;
        }
        const label = (p.label ?? p.query ?? "").trim();
        const query = (p.query ?? p.label ?? "").trim();
        if (!label || !query) return;
        prompts.push({
          id: p.id ?? `p${i}`,
          label,
          query,
          outcome: p.outcome ?? undefined,
          badge: p.badge ?? undefined,
          category: p.intent_category ?? undefined,
        });
      });
      return {
        prompts,
        persona: parsed.data.persona ?? undefined,
        audience: parsed.data.mode ?? undefined,
        context: parsed.data.context_summary ?? undefined,
      };
    },
  });
}
