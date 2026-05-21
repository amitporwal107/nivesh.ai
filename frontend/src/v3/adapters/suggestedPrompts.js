// Suggested-prompts adapter — calls the existing /api/copilot/suggested-prompts
// endpoint, then merges server-provided prompts with the local prompt catalog
// (derived from docs/COPILOT_PROMPT_CATALOG.md). The local catalog is the
// fallback — server prompts win when both are present.

import { apiGet } from "./apiClient";
import { useAsync } from "../hooks/useAsync";
import { getCatalogFor } from "./promptCatalog";

const CAT_BACKEND_TO_V3 = {
  PH: "health",
  PA: "performance",
  RD: "risk",
  TX: "tax",
  GP: "goal",
  health: "health",
  performance: "performance",
  risk: "risk",
  tax: "tax",
  goal: "goal",
};

function normalize(p) {
  return {
    label: p.label || p.prompt || p.text,
    category: CAT_BACKEND_TO_V3[p.category] || "health",
    tier: p.tier || "advanced",
    id: p.id || null,
  };
}

/**
 * Returns a catalog shape compatible with the local fallback:
 *   { primary, secondary: [...], advanced: [...] }
 * Always returns *something* renderable — never null.
 */
export function useSuggestedPrompts(personaId) {
  const initial = { ...getCatalogFor(personaId), _source: "local" };
  return useAsync(
    async () => {
      const local = getCatalogFor(personaId);
      const { data, error } = await apiGet("/copilot/suggested-prompts", { persona: personaId });

      if (error || !data || !Array.isArray(data.prompts || data.items || [])) {
        return { data: { ...local, _source: "local" }, error: null };
      }

      const rows = (data.prompts || data.items || []).map(normalize);
      const primary = rows.find((r) => r.tier === "primary") || local.primary;
      const secondary = rows.filter((r) => r.tier === "secondary").slice(0, 4);
      const advanced = rows.filter((r) => r.tier === "advanced").slice(0, 8);

      return {
        data: {
          primary: primary || local.primary,
          secondary: secondary.length ? secondary : local.secondary,
          advanced: advanced.length ? advanced : local.advanced,
          _source: "live",
        },
        error: null,
      };
    },
    [personaId],
    { initialData: initial }
  );
}
