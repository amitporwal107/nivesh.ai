/**
 * Saved strategy screens — the user's own strategies in the strategy builder,
 * read here so a ready-made screen can be kept and shown as a watchlist.
 *
 *   GET    /api/strategy-builder/strategies        the user's saved strategies (name, description, dates)
 *   GET    /api/strategy-builder/strategies/{id}   one strategy with its active rule definition
 *   POST   /api/strategy-builder/strategies        save a definition — createStrategy() in
 *                                                  services/strategyBuilder.ts, the call the
 *                                                  strategy builder page makes
 *   DELETE /api/strategy-builder/strategies/{id}   archive one (it leaves the list)
 *   POST   /api/strategy-builder/screen            run a definition on the latest data — screenStrategy()
 *
 * Contract: backend/routes/strategy_builder.py. The list and the single read
 * had no client, and the existing client casts its responses, so every body is
 * checked here: one that is not what the route sends is an error, never an
 * empty list.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { createStrategy, screenStrategy, type ScreenCandidate, type ScreenResult } from "@/services/strategyBuilder";

const BASE = "/api/strategy-builder";

export const STRATEGIES_KEY = ["strategy-builder", "strategies"] as const;

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw | null => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : null);
const text = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);

export interface SavedStrategy {
  id: string;
  name: string;
  description: string | null;
  /** "STOCK" | "MF"; null when the row does not say. */
  assetClass: string | null;
  createdAt: string | null;
  updatedAt: string | null;
}

/** The list body, or a contract error when it is not one. Rows without an id or a name are dropped. */
export function readStrategies(raw: unknown): SavedStrategy[] {
  const body = rec(raw);
  if (!body || !Array.isArray(body.strategies)) throw ApiError.contractDrift("strategy-builder.strategies: no strategies list");
  const out: SavedStrategy[] = [];
  for (const item of body.strategies) {
    const r = rec(item);
    const id = text(r?.id);
    const name = text(r?.name);
    if (!r || !id || !name) continue;
    out.push({
      id,
      name,
      description: text(r.description),
      assetClass: text(r.asset_class)?.toUpperCase() ?? null,
      createdAt: text(r.created_at),
      updatedAt: text(r.updated_at),
    });
  }
  return out;
}

/** The user's saved strategies, newest change first (the route's order). */
export function useSavedStrategies() {
  return useQuery<SavedStrategy[]>({
    queryKey: STRATEGIES_KEY,
    staleTime: 60_000,
    // A body in the wrong shape will not come right on a second try.
    retry: (count, e) => !(e instanceof ApiError && e.kind === "contract_drift") && count < 1,
    queryFn: async ({ signal }) => readStrategies((await http({ path: `${BASE}/strategies`, signal })).data),
  });
}

export interface SaveStrategyInput {
  name: string;
  description?: string | null;
  assetClass?: string | null;
  /** The rule definition exactly as the template (or the builder) holds it. */
  definition: Record<string, unknown>;
}

/** Keep a rule definition as one of the user's strategies. */
export function useSaveStrategy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: SaveStrategyInput): Promise<{ id: string; name: string }> => {
      const saved = await createStrategy({
        name: input.name,
        description: input.description ?? null,
        asset_class: input.assetClass === "MF" ? "MF" : "STOCK",
        definition: input.definition,
      });
      const id = text(rec(saved)?.id);
      if (!id) throw ApiError.contractDrift("strategy-builder.create: no id in the answer");
      return { id, name: text(rec(saved)?.name) ?? input.name };
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: STRATEGIES_KEY }),
  });
}

/** Archive a saved strategy. The route keeps the row and hides it from the list. */
export function useArchiveStrategy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string): Promise<string> => {
      await http({ method: "DELETE", path: `${BASE}/strategies/${encodeURIComponent(id)}`, noRetry: true });
      return id;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: STRATEGIES_KEY }),
  });
}

export interface StrategyScreenRun {
  rows: ScreenCandidate[];
  asOf: string | null;
  /** The feature the candidates are ranked by, as the route reports it. */
  rankedBy: string | null;
}

/** A screen answer with the fields these screens read, or null when the body is not one. */
export function readScreenResult(raw: unknown): StrategyScreenRun | null {
  const r = rec(raw) as Partial<ScreenResult> | null;
  if (!r || !Array.isArray(r.candidates)) return null;
  const rows = r.candidates.filter((c): c is ScreenCandidate => !!c && typeof c === "object" && typeof c.symbol === "string" && c.symbol.trim() !== "");
  const basis = typeof r.score_basis === "string" ? r.score_basis : typeof r.ranked_by === "string" ? r.ranked_by : null;
  return { rows, asOf: typeof r.as_of_date === "string" ? r.as_of_date : null, rankedBy: basis };
}

/**
 * Today's stocks for one saved strategy: read its active definition, then run
 * that definition the way the Screener's ready-made screens are run. Nothing is
 * asked until `enabled`.
 */
export function useStrategyWatchlist(id: string, enabled: boolean) {
  return useQuery<StrategyScreenRun>({
    queryKey: ["strategy-builder", "strategy-watchlist", id],
    enabled,
    staleTime: 60_000,
    retry: false,
    queryFn: async ({ signal }) => {
      const res = await http({ path: `${BASE}/strategies/${encodeURIComponent(id)}`, signal });
      const definition = rec(rec(rec(res.data)?.active_version)?.definition);
      if (!definition) throw ApiError.contractDrift("strategy-builder.strategy: no active rule definition");
      const result = readScreenResult(await screenStrategy(definition));
      if (!result) throw ApiError.contractDrift("strategy-builder.screen: no candidates list");
      return result;
    },
  });
}
