/**
 * The run the Simulation studio is looking at: `?sim=SIM-…` in the URL, shared by every studio view (tabs keep it).
 * Without one, the newest simulation of this account is used. Simulations are read from the desk API.
 */
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { deskGet } from "../api";
import type { SimulationRow } from "../types";

export const studioKeys = {
  list: ["desk", "studio", "simulations"] as const,
};

export function useSimulationList() {
  return useQuery({
    queryKey: studioKeys.list,
    queryFn: () => deskGet<SimulationRow[]>("/simulations", { limit: 100 }),
    refetchInterval: 15_000,
  });
}

/** [selected simulation id or null, setter]. Falls back to the newest run when the URL names none. */
export function useStudioRun(): { simId: string | null; setSimId: (id: string | null) => void; list: ReturnType<typeof useSimulationList> } {
  const [params, setParams] = useSearchParams();
  const list = useSimulationList();
  const fromUrl = params.get("sim");
  const newest = [...(list.data ?? [])].sort((a, b) => (a.created_at < b.created_at ? 1 : -1))[0]?.simulation_id ?? null;
  const setSimId = (id: string | null) => {
    const p = new URLSearchParams(params);
    if (id) p.set("sim", id); else p.delete("sim");
    setParams(p, { replace: false });
  };
  return { simId: fromUrl ?? newest, setSimId, list };
}
