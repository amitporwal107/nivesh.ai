/**
 * Strategy Builder — the payoff hook.
 *
 *   const { data, error, isPending, isStale } = usePayoff(request);   // request: PayoffRequest | null
 *
 *   POST /api/desk/strategy/payoff   a pure calculation (no write, nothing sent to a broker)
 *
 * The request is debounced (default 250 ms) so dragging a slider asks once, not on every pixel. While a
 * new answer loads the previous one stays in `data` with `isStale` true (the screen dims it); a failed
 * call leaves `error` set and `data` undefined for that request, so a failure is never drawn as an empty
 * chart. The body is parsed with the zod contract; a body that does not fit is a contract error, not data.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { ZodError } from "zod";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { PayoffResponseSchema, type PayoffRequest, type PayoffResponse } from "./strategy-contract";

export const PAYOFF_PATH = "/api/desk/strategy/payoff";

/** The calculation, as the hook calls it: POST, no retry, the answer parsed against the contract. */
export async function fetchPayoff(request: PayoffRequest, signal?: AbortSignal): Promise<PayoffResponse> {
  const res = await http({ method: "POST", path: PAYOFF_PATH, body: request, noRetry: true, signal });
  const parsed = PayoffResponseSchema.safeParse(res.data);
  if (!parsed.success) {
    throw new ApiError("contract_drift", "The payoff answer was not in the expected form.", { status: res.status, cause: parsed.error });
  }
  return parsed.data;
}

/** The failure in words for the screen: 422, signed out, not allowed, network, timeout, contract. */
export function payoffProblem(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.kind === "validation") return `The calculation rejected this request${e.detail ? `: ${e.detail}` : "."}`;
    if (e.kind === "auth") return "You are signed out. Sign in again to calculate a payoff.";
    if (e.kind === "forbidden") return "This account is not allowed to use the strategy calculator.";
    if (e.kind === "network") return "The network request failed. The chart below is the last answer, if any.";
    if (e.kind === "timeout") return "The calculation took too long.";
    if (e.kind === "contract_drift") return "The calculation answered in a form the screen does not understand, so nothing is drawn.";
    if (e.kind === "server") return `The calculation failed on the server${e.detail ? `: ${e.detail}` : "."}`;
    return e.detail || e.message || `HTTP ${e.status ?? "error"}`;
  }
  if (e instanceof ZodError) return "The calculation answered in a form the screen does not understand, so nothing is drawn.";
  return e instanceof Error && e.message ? e.message : "The calculation failed.";
}

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    if (ms <= 0) { setV(value); return; }
    const t = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(t);
  }, [value, ms]);
  return v;
}

export interface PayoffState {
  /** The latest answer; while a new request loads, the previous answer (then `isStale` is true). */
  data: PayoffResponse | undefined;
  error: unknown;
  /** The failure in words (null when there is none). */
  errorText: string | null;
  /** True until the first answer arrives. */
  isPending: boolean;
  /** A newer request is in flight (or waiting out the debounce) and `data` is the previous answer. */
  isStale: boolean;
  refetch: () => void;
}

export function usePayoff(request: PayoffRequest | null, opts: { debounceMs?: number } = {}): PayoffState {
  const key = request ? JSON.stringify(request) : null;
  const settled = useDebounced(key, opts.debounceMs ?? 250);
  const q = useQuery<PayoffResponse>({
    queryKey: ["copilot", "desk", "strategy-payoff", settled],
    enabled: settled != null,
    staleTime: 5 * 60_000,
    retry: false,
    placeholderData: keepPreviousData,
    queryFn: ({ signal }) => fetchPayoff(JSON.parse(settled as string) as PayoffRequest, signal),
  });
  const waiting = key !== settled;
  return {
    data: q.data,
    error: q.error,
    errorText: q.error ? payoffProblem(q.error) : null,
    isPending: settled != null && q.isPending,
    isStale: q.isPlaceholderData || waiting || (q.isFetching && q.data != null),
    refetch: () => { void q.refetch(); },
  };
}
