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

/** One archived (past) session in the history view. */
export interface SessionHistoryItem {
  sid: string;
  archived_at: string;
  count: number;
}

export interface LogsAdapter {
  enable(previousSid?: string | null): Promise<EnableResult>;
  disable(sid: string): Promise<void>;
  fetch(sid: string, limit?: number): Promise<ServerLogEntry[]>;
  clear(sid: string): Promise<void>;
  history(): Promise<SessionHistoryItem[]>;
  historyLogs(sid: string): Promise<ServerLogEntry[]>;
}

export const realLogsAdapter: LogsAdapter = {
  async enable(previousSid?: string | null) {
    const res = await http<EnableResult>({
      method: "POST",
      path: "/api/session-logs/enable",
      body: { previous_sid: previousSid ?? null },
      noRetry: true,
    });
    return res.data;
  },

  async history() {
    const res = await http<{ sessions: SessionHistoryItem[] }>({ path: "/api/session-logs/history" });
    return res.data?.sessions ?? [];
  },

  async historyLogs(sid) {
    const res = await http<{ logs: ServerLogEntry[] }>({
      path: `/api/session-logs/history/${encodeURIComponent(sid)}`,
    });
    return res.data?.logs ?? [];
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
