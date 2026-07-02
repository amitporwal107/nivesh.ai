/**
 * logs.adapter — session log viewer API (Settings → Logs & Diagnostics).
 *
 * Talks to backend routes/session_logs.py:
 *   POST   /api/session-logs/enable   → mint a debug-session id
 *   POST   /api/session-logs/disable  → stop + purge that session's logs
 *   GET    /api/session-logs?sid=…     → fetch buffered server logs
 *   DELETE /api/session-logs?sid=…     → clear buffered server logs (stay enabled)
 */
import { http } from "@/services/api/http";

/** One server-side log line, as emitted by core.logging_config. */
export interface ServerLogEntry {
  ts: string;
  severity: string; // DEBUG | INFO | WARNING | ERROR | CRITICAL
  logger: string;
  msg: string;
  correlationId?: string;
  endpoint?: string;
  httpStatus?: number;
  exc?: string;
}

export interface EnableResult {
  enabled: boolean;
  sid: string;
  ttl_seconds: number;
}

export interface LogsAdapter {
  enable(): Promise<EnableResult>;
  disable(sid: string): Promise<void>;
  fetch(sid: string, limit?: number): Promise<ServerLogEntry[]>;
  clear(sid: string): Promise<void>;
}

export const realLogsAdapter: LogsAdapter = {
  async enable() {
    const res = await http<EnableResult>({
      method: "POST",
      path: "/api/session-logs/enable",
      noRetry: true,
    });
    return res.data;
  },

  async disable(sid) {
    await http({
      method: "POST",
      path: "/api/session-logs/disable",
      body: { sid },
      noRetry: true,
    });
  },

  async fetch(sid, limit = 1000) {
    const res = await http<{ logs: ServerLogEntry[] }>({
      path: "/api/session-logs",
      query: { sid, limit },
    });
    return res.data?.logs ?? [];
  },

  async clear(sid) {
    await http({ method: "DELETE", path: "/api/session-logs", query: { sid }, noRetry: true });
  },
};
