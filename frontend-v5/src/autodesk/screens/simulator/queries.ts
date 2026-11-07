/**
 * Simulator — queries and actions. Keys start with "desk" (one invalidate after a write refreshes everything). Sub-queries
 * of one simulation carry its step_seq + status in the key, so they refetch whenever the clock moves; the row itself is
 * polled while a background run (POST /run) is going.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { deskGet, deskPost } from "../../api";
import type { SimulationRow, WorkflowRow } from "../../types";
import { emptyTimeline, mergeEvents, type SimAgents, type SimResults, type TimelinePage, type TimelineState, type WorkflowDetail } from "./model";

export function useSimulations() {
  return useQuery({ queryKey: ["desk", "sims"], queryFn: () => deskGet<SimulationRow[]>("/simulations", { limit: 50 }) });
}

export function useSimulation(sid: string | null) {
  return useQuery({
    queryKey: ["desk", "sim", sid],
    queryFn: () => deskGet<SimulationRow>(`/simulations/${encodeURIComponent(sid!)}`),
    enabled: !!sid,
    refetchInterval: (q) => (q.state.data?.status === "RUNNING" && q.state.data?.background_run ? 2000 : false),
  });
}

type Tick = readonly [number | undefined, string | undefined];

export function useSimResults(sid: string | null, tick: Tick) {
  return useQuery({
    queryKey: ["desk", "sim", sid, "results", ...tick],
    queryFn: () => deskGet<SimResults>(`/simulations/${encodeURIComponent(sid!)}/results`),
    enabled: !!sid && tick[0] !== undefined,
    placeholderData: keepPreviousData,
  });
}

export function useSimAgents(sid: string | null, tick: Tick) {
  return useQuery({
    queryKey: ["desk", "sim", sid, "agents", ...tick],
    queryFn: () => deskGet<SimAgents>(`/simulations/${encodeURIComponent(sid!)}/agents`),
    enabled: !!sid && tick[0] !== undefined,
    placeholderData: keepPreviousData,
  });
}

export function useSimWorkflows(sid: string | null, tick: Tick) {
  return useQuery({
    queryKey: ["desk", "sim", sid, "workflows", ...tick],
    queryFn: () => deskGet<WorkflowRow[]>(`/simulations/${encodeURIComponent(sid!)}/workflows`),
    enabled: !!sid && tick[0] !== undefined,
    placeholderData: keepPreviousData,
  });
}

export function useWorkflowDetail(wid: string | null, tick: Tick) {
  return useQuery({
    queryKey: ["desk", "workflow", wid, ...tick],
    queryFn: () => deskGet<WorkflowDetail>(`/desk/workflows/${encodeURIComponent(wid!)}`),
    enabled: !!wid,
    placeholderData: keepPreviousData,
  });
}

const PAGE = 2000;
const MAX_PAGES = 10;

/**
 * GET /simulations/{sid}/timeline, read incrementally: each fetch asks only for events after the last seq it holds
 * (after_seq), page by page, and folds them into a small state (display events, clock steps, exceptions).
 */
export function useSimTimeline(sid: string | null, tick: Tick) {
  const qc = useQueryClient();
  const key = ["desk", "sim", sid, "timeline"] as const;
  return useQuery({
    queryKey: key,
    enabled: !!sid && tick[0] !== undefined,
    queryFn: async (): Promise<TimelineState> => {
      let st = qc.getQueryData<TimelineState>(key) ?? emptyTimeline();
      let clock = st.clock;
      for (let i = 0; i < MAX_PAGES; i++) {
        const r = await deskGet<TimelinePage>(`/simulations/${encodeURIComponent(sid!)}/timeline`, { after_seq: st.lastSeq, limit: PAGE });
        clock = r.clock ?? clock;
        st = mergeEvents(st, r.events ?? []);
        if ((r.events ?? []).length < PAGE) break;
      }
      return { ...st, clock };
    },
  });
}

export type SimAction = "start" | "pause" | "resume" | "stop" | "run" | "step";

/** POSTs one or more lifecycle actions in order (e.g. start then run for an accelerated replay). */
export function useSimActions(sid: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (acts: { action: SimAction; body?: unknown }[]) => {
      let last: unknown = null;
      for (const a of acts) last = await deskPost<unknown>(`/simulations/${encodeURIComponent(sid!)}/${a.action}`, a.body);
      return last;
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["desk"] }),
  });
}

export function useCreateSimulation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => deskPost<SimulationRow>("/simulations", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["desk"] }),
  });
}
