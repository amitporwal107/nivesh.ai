/**
 * usePolling — poll an async task until it leaves QUEUED/PROCESSING.
 *
 * Useful for review-pack generation, CAS uploads, backtest runs.
 *
 *   const { data } = usePolling({
 *     queryKey: ["reviewPack", taskId],
 *     queryFn: () => mfdService.reviewPackPoll(profileId, taskId),
 *     isTerminal: (d) => d.status === "COMPLETED" || d.status === "FAILED",
 *     intervalMs: 2000,
 *   });
 */
import { useQuery, type UseQueryResult } from "@tanstack/react-query";

interface UsePollingArgs<T> {
  queryKey: unknown[];
  queryFn: () => Promise<T>;
  isTerminal: (data: T) => boolean;
  intervalMs?: number;
  enabled?: boolean;
}

export function usePolling<T>({
  queryKey,
  queryFn,
  isTerminal,
  intervalMs = 2_000,
  enabled = true,
}: UsePollingArgs<T>): UseQueryResult<T> {
  return useQuery<T>({
    queryKey,
    queryFn,
    enabled,
    refetchInterval: (q) => {
      const data = q.state.data;
      if (!data) return intervalMs;
      return isTerminal(data) ? false : intervalMs;
    },
    refetchIntervalInBackground: false,
  });
}
