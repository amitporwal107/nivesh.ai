/**
 * useResync — POST /api/portfolio/resync
 * Invalidates all dashboard queries on success so Performance page refetches.
 */
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { http } from "@/services/api/http";

interface ResyncResult {
  ok: boolean;
  last_synced_at: string | null;
  error?: string;
}

export function useResync(initialSyncedAt?: string | null) {
  const qc = useQueryClient();
  const [isPending, setIsPending]       = useState(false);
  const [lastSyncedAt, setLastSyncedAt] = useState<string | null>(initialSyncedAt ?? null);
  const [error, setError]               = useState<string | null>(null);

  async function resync() {
    setIsPending(true);
    setError(null);
    try {
      const res = await http({ method: "POST", path: "/api/portfolio/resync" });
      const data = res.data as ResyncResult;
      if (data.ok && data.last_synced_at) {
        setLastSyncedAt(data.last_synced_at);
        // Invalidate all dashboard + composition queries so they refetch fresh
        await qc.invalidateQueries({ queryKey: ["dashboards"] });
        await qc.invalidateQueries({ queryKey: ["composition"] });
      } else {
        setError(data.error ?? "Resync failed — prior data preserved.");
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Resync failed — try again shortly.");
    } finally {
      setIsPending(false);
    }
  }

  return { resync, isPending, lastSyncedAt, error };
}
