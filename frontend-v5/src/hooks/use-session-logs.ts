/**
 * Hooks for Settings → Logs & Diagnostics.
 *
 * - useSessionLogging(): the on/off control. Enabling mints a backend
 *   debug-session id, persists it, and starts client-side capture; disabling
 *   stops capture and purges the server buffer.
 * - useServerLogs(): polls the backend for this session's buffered server logs
 *   while logging is on.
 */
import { useCallback, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { logsService } from "@/services";
import type { ServerLogEntry, SessionHistoryItem } from "@/services/adapters/logs.adapter";
import { useLoggingStore } from "@/stores/logging.store";

export function useSessionLogging() {
  const enabled = useLoggingStore((s) => s.enabled);
  const sid = useLoggingStore((s) => s.sid);
  const applySession = useLoggingStore((s) => s.applySession);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const enable = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      // Pass the current sid so the server archives (rolls) it into history first.
      const res = await logsService.enable(sid);
      applySession(true, res.sid);
    } catch {
      // Server-side capture unavailable (e.g. log store not configured) — still
      // capture this tab's client logs so the feature is useful either way.
      applySession(true, null);
      setError("Server logs unavailable — capturing client-side logs only.");
    } finally {
      setBusy(false);
    }
  }, [applySession, sid]);

  /** Roll to a fresh session (archives the current one). Used when the live
   *  session's server buffer has expired (a new login started). */
  const roll = useCallback(async () => {
    try {
      const res = await logsService.enable(sid);
      applySession(true, res.sid);
    } catch {
      /* best-effort */
    }
  }, [applySession, sid]);

  const disable = useCallback(async () => {
    setBusy(true);
    setError(null);
    const prevSid = sid;
    // Stop capturing immediately; purge the server buffer best-effort after.
    applySession(false, null);
    try {
      if (prevSid) await logsService.disable(prevSid);
    } catch {
      /* server cleanup is best-effort; local capture is already off */
    } finally {
      setBusy(false);
    }
  }, [applySession, sid]);

  return { enabled, sid, busy, error, enable, disable, roll };
}

/** The caller's last 10 archived sessions (historical view). */
export function useSessionHistory(enabled = true) {
  return useQuery<SessionHistoryItem[]>({
    queryKey: ["session-logs", "history"],
    queryFn: () => logsService.history(),
    enabled,
    staleTime: 15_000,
    retry: false,
  });
}

/** Buffered server logs for one archived session (loaded on demand). */
export function useHistoryLogs(sid: string | null) {
  return useQuery<ServerLogEntry[]>({
    queryKey: ["session-logs", "history", sid],
    queryFn: () => logsService.historyLogs(sid as string),
    enabled: Boolean(sid),
    staleTime: 60_000,
    retry: false,
  });
}

/** Poll buffered server logs for a debug session (only while enabled). */
export function useServerLogs(
  sid: string | null,
  enabled: boolean,
  refetchMs = 4000,
) {
  return useQuery<ServerLogEntry[]>({
    queryKey: ["session-logs", sid],
    queryFn: () => logsService.fetch(sid as string),
    enabled: Boolean(enabled && sid),
    refetchInterval: enabled && sid ? refetchMs : false,
    staleTime: 0,
    retry: false,
  });
}
