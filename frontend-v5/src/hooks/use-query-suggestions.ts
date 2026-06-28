import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";

export interface QuerySuggestion {
  query: string;
  section: string;
  category: string;
  subcategory: string;
  has_placeholder: boolean;
}
export interface QuerySuggestResult {
  suggestions: QuerySuggestion[];
}

/** Typeahead of ready-made question templates for the chat composer, ranked
 *  against what the user is typing (the curated question bank). Disabled until
 *  ≥2 chars; results cached briefly per term. Mirrors useInstrumentSearch. */
export function useQuerySuggestions(query: string) {
  const q = query.trim();
  return useQuery<QuerySuggestResult>({
    queryKey: ["chat", "suggest-queries", q],
    enabled: q.length >= 2,
    staleTime: 60_000,
    queryFn: async ({ signal }) => {
      const res = await http<QuerySuggestResult>({
        path: "/api/chat/suggest-queries",
        query: { q, limit: 5 },
        signal,
      });
      return res.data ?? { suggestions: [] };
    },
  });
}
