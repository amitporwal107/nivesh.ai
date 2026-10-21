/**
 * Strategy Builder, "Top by regime" — the route as a hook.
 *
 *   useStrategyTop(run)   POST /api/desk/strategy/top   reads the regime and the chain, writes nothing
 *
 * No retry (a failure is shown with a Retry button), and the previous board stays on screen while a
 * new one loads. `sent_to_broker` is false on the answer; nothing places an order.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { TopSchema, type TopBoard } from "./top-contract";

export const TOP_PATH = "/api/desk/strategy/top";

/** The default the user asked for: the top five in each class. The route caps `limit` at 10. */
export const TOP_LIMIT = 5;

export interface TopRequest {
  limit?: number;
  classes?: Array<"index_options" | "stock_fno" | "cash">;
  expiry?: string;
}

/** One run of the board: the body and a counter, so "Build again" re-runs the same body. */
export interface TopRun { body: TopRequest; runId: number }

export function useStrategyTop(run: TopRun | null) {
  return useQuery<TopBoard>({
    queryKey: ["copilot", "desk", "strategy-top", run?.runId ?? 0, run?.body ?? null],
    enabled: run != null,
    retry: false,
    staleTime: 0,
    gcTime: 60_000,
    refetchOnWindowFocus: false,
    placeholderData: keepPreviousData,
    queryFn: async ({ signal }) => {
      const res = await http({ method: "POST", path: TOP_PATH, body: run?.body, signal, noRetry: true });
      const r = TopSchema.safeParse(res.data);
      if (!r.success) throw new ApiError("contract_drift", "The ideas were not in the expected form.", { cause: r.error });
      return r.data;
    },
  });
}
