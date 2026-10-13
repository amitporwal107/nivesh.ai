/**
 * Saved screen — the two calls that had no hook the screen could use.
 *
 *   GET  /api/portfolio/holdings/export?format=csv|xlsx   the holdings as a file
 *        (backend/routes/portfolio_export.py; the original app's ExportButton
 *        downloads the CSV from the same route)
 *   POST /api/thematic/favorites/toggle                   star or un-star a research
 *        question (backend/routes/thematic_prefs.py). The app's existing writer,
 *        useThematicQueries, does not report a failed write, so the Saved screen
 *        makes the same call here and shows the failure.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";
import { apiFetch } from "@/services/api/authed-fetch";
import { ApiError } from "@/services/api/errors";
import { http } from "@/services/api/http";

export type ExportFormat = "csv" | "xlsx";

/** Thrown when the account has no holdings: the route answers 404 instead of an empty file. */
export class NothingToExport extends Error {
  constructor() {
    super("there are no holdings to export yet");
    this.name = "NothingToExport";
  }
}

/** Fetches the holdings file and hands it to the browser to save. Resolves with the file's name. */
export async function downloadHoldings(format: ExportFormat): Promise<string> {
  let res: Response;
  try {
    res = await apiFetch(`/api/portfolio/holdings/export?format=${format}`);
  } catch (cause) {
    throw ApiError.network(cause);
  }
  if (res.status === 404) throw new NothingToExport();
  if (!res.ok) {
    const body: unknown = await res.json().catch(() => null);
    throw ApiError.fromResponse(res, body);
  }
  const blob = await res.blob();
  const named = /filename="?([^";]+)"?/.exec(res.headers.get("content-disposition") ?? "");
  const filename = named?.[1]?.trim() || `holdings.${format}`;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  return filename;
}

/** The key useThematicPrefs (screens/markets/hooks.ts) reads under. */
const THEMATIC_KEY = ["thematic", "prefs"] as const;

const PrefsC = z.object({
  history: z.array(z.string()).default([]),
  favorites: z.array(z.string()).default([]),
});

/** Star or un-star a research question. The route answers with both lists, which replace the cached ones. */
export function useToggleStarredQuestion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (question: string) => {
      const res = await http({ method: "POST", path: "/api/thematic/favorites/toggle", body: { query: question }, noRetry: true });
      return PrefsC.parse(res.data);
    },
    onSuccess: (prefs) => qc.setQueryData(THEMATIC_KEY, prefs),
  });
}
