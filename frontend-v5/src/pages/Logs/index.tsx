import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { Link } from "react-router-dom";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ArrowLeft, Download, Copy, Trash2, Pause, Play, Search, History } from "lucide-react";
import {
  subscribe,
  getVersion,
  getEntries,
  clearEntries,
  type LogLevel,
  type LogSource,
} from "@/lib/session-log";
import { useSessionLogging, useServerLogs, useSessionHistory, useHistoryLogs } from "@/hooks/use-session-logs";
import type { ServerLogEntry } from "@/services/adapters/logs.adapter";
import { logsService } from "@/services";

type ViewSource = LogSource | "server";

interface ViewLog {
  key: string;
  ts: string;
  level: LogLevel;
  source: ViewSource;
  message: string;
  correlationId?: string;
}

const LEVELS: LogLevel[] = ["debug", "info", "warn", "error"];
const SOURCES: ViewSource[] = ["client", "console", "network", "error", "server"];

const LEVEL_STYLE: Record<LogLevel, string> = {
  debug: "text-ink-4",
  info: "text-ink-2",
  warn: "text-amber-500",
  error: "text-neg",
};

const SOURCE_STYLE: Record<ViewSource, string> = {
  client: "bg-surface-3 text-ink-2",
  console: "bg-surface-3 text-ink-2",
  network: "bg-accent/15 text-accent",
  error: "bg-neg/15 text-neg",
  server: "bg-pos/15 text-pos",
};

function sevToLevel(severity: string): LogLevel {
  const s = severity.toUpperCase();
  if (s === "DEBUG") return "debug";
  if (s === "WARNING" || s === "WARN") return "warn";
  if (s === "ERROR" || s === "CRITICAL") return "error";
  return "info";
}

function mapServerLogs(arr: ServerLogEntry[], keyPrefix: string): ViewLog[] {
  return arr.map((e, i) => ({
    key: `${keyPrefix}${i}-${e.ts}`,
    ts: e.ts,
    level: sevToLevel(e.severity),
    source: "server",
    message:
      `[${e.logger}] ${e.msg}` +
      (e.httpStatus ? ` · ${e.httpStatus}` : "") +
      (e.exc ? `\n${e.exc}` : ""),
    correlationId: e.correlationId,
  }));
}

function fmtTime(iso: string): string {
  // HH:MM:SS.mmm — enough to correlate client & server without date noise.
  const t = iso.includes("T") ? iso.split("T")[1] : iso;
  return t.replace("Z", "");
}

export default function LogsPage() {
  const { enabled, sid, busy, error, enable, disable, roll } = useSessionLogging();

  // Live client-side buffer (console / network / errors).
  useSyncExternalStore(subscribe, getVersion, getVersion);
  const clientEntries = getEntries();

  const [view, setView] = useState<"live" | "history">("live");
  const [histSid, setHistSid] = useState<string | null>(null);
  const [paused, setPaused] = useState(false);

  const serverQuery = useServerLogs(sid, view === "live" && enabled && !paused);
  const serverLogs = serverQuery.data ?? [];
  const historyQ = useSessionHistory(true);
  const histLogsQ = useHistoryLogs(view === "history" ? histSid : null);

  // If the live session's server buffer has expired (a new login started), the
  // backend has archived it — roll to a fresh session id. Guard to at most once
  // per sid so a persistent 404 can't loop.
  const rolledFor = useRef<string | null>(null);
  useEffect(() => {
    const kind = (serverQuery.error as { kind?: string } | undefined)?.kind;
    if (view === "live" && enabled && sid && kind === "not_found" && rolledFor.current !== sid) {
      rolledFor.current = sid;
      void roll();
    }
  }, [serverQuery.error, view, enabled, sid, roll]);

  const [query, setQuery] = useState("");
  const [levelOn, setLevelOn] = useState<Record<LogLevel, boolean>>({
    debug: true, info: true, warn: true, error: true,
  });
  const [sourceOn, setSourceOn] = useState<Record<ViewSource, boolean>>({
    client: true, console: true, network: true, error: true, server: true,
  });

  const rows = useMemo<ViewLog[]>(() => {
    let base: ViewLog[];
    if (view === "history") {
      base = mapServerLogs(histLogsQ.data ?? [], "h");
    } else {
      const client: ViewLog[] = clientEntries.map((e) => ({
        key: `c${e.id}`, ts: e.ts, level: e.level, source: e.source,
        message: e.message, correlationId: e.correlationId,
      }));
      base = [...client, ...mapServerLogs(serverLogs, "s")];
    }
    const q = query.trim().toLowerCase();
    return base
      .filter((r) => levelOn[r.level] && sourceOn[r.source])
      .filter((r) => !q || r.message.toLowerCase().includes(q) || (r.correlationId ?? "").includes(q))
      .sort((a, b) => (a.ts < b.ts ? -1 : a.ts > b.ts ? 1 : 0));
  }, [view, clientEntries, serverLogs, histLogsQ.data, query, levelOn, sourceOn]);

  // Auto-scroll to newest unless the user scrolled up.
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  };
  useEffect(() => {
    const el = scrollRef.current;
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
  }, [rows.length]);

  const copyAll = useCallback(async () => {
    const text = rows
      .map((r) => `${r.ts} ${r.level.toUpperCase().padEnd(5)} ${r.source.padEnd(7)} ${r.correlationId ? r.correlationId.slice(0, 8) + " " : ""}${r.message}`)
      .join("\n");
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      /* clipboard may be blocked; the download button is the fallback */
    }
  }, [rows]);

  const download = useCallback(() => {
    const blob = new Blob([JSON.stringify(rows, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `nivesh-session-logs-${sid ?? "local"}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, [rows, sid]);

  const clearAll = useCallback(async () => {
    clearEntries();
    if (sid) {
      try {
        await logsService.clear(sid);
      } catch {
        /* best-effort */
      }
    }
    serverQuery.refetch();
  }, [sid, serverQuery]);

  return (
    <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1000px] mx-auto w-full">
      <Link to="/settings" className="inline-flex items-center gap-1.5 text-[12px] text-ink-3 hover:text-ink-2 transition-colors">
        <ArrowLeft className="h-3.5 w-3.5" /> Settings
      </Link>
      <div className="font-mono text-[11px] uppercase tracking-[.18em] text-ink-3 mt-4">Logs &amp; Diagnostics</div>
      <h1 className="font-display text-3xl sm:text-4xl tracking-tightish leading-[1.05] mt-1.5">Session logs</h1>
      <p className="text-[14px] text-ink-2 mt-3 max-w-[620px] leading-relaxed">
        A live view of this session's client and server activity — for troubleshooting. Logging is
        off by default; turn it on, reproduce the problem, then copy or download the logs.
      </p>

      {/* Enable / status */}
      <Card className="mt-6 p-5">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3">
            <span
              className={cn(
                "h-2.5 w-2.5 rounded-full shrink-0",
                enabled ? "bg-pos animate-pulse" : "bg-surface-3",
              )}
            />
            <div>
              <div className="text-[13.5px] font-medium">
                {enabled ? "Logging is on" : "Logging is off"}
              </div>
              <div className="text-[12px] text-ink-3 mt-0.5">
                {enabled
                  ? <>Capturing this session{sid ? <> · <span className="font-mono">{sid.slice(0, 12)}</span></> : null}</>
                  : "Enable to start capturing console, network and server logs."}
              </div>
            </div>
          </div>
          <button
            role="switch"
            aria-checked={enabled}
            aria-label="Toggle session logging"
            onClick={() => (enabled ? disable() : enable())}
            disabled={busy}
            className={cn(
              "h-6 w-10 rounded-full relative transition-colors shrink-0 disabled:opacity-60",
              enabled ? "bg-accent" : "bg-surface-3",
            )}
          >
            <span
              className={cn(
                "absolute top-0.5 h-5 w-5 rounded-full bg-white transition-all shadow",
                enabled ? "left-[18px]" : "left-0.5",
              )}
            />
          </button>
        </div>
        {error && (
          <div className="mt-3 text-[12px] text-neg">
            {error}
          </div>
        )}
        {enabled && serverQuery.isError && (
          <div className="mt-3 text-[12px] text-ink-3">
            Server logs unavailable right now — client logs are still being captured. (Server-side
            capture needs the log store configured.)
          </div>
        )}
      </Card>

      {/* Live / History switch */}
      <div className="mt-4 flex items-center gap-2">
        {(["live", "history"] as const).map((v) => (
          <button
            key={v}
            onClick={() => { setView(v); if (v === "history") historyQ.refetch(); }}
            className={cn(
              "px-3 py-1.5 rounded-md text-[12px] border transition-colors flex items-center gap-1.5",
              view === v ? "border-accent/50 bg-accent/15 text-accent" : "border-hairline text-ink-3 hover:text-ink",
            )}
          >
            {v === "history" && <History className="h-3.5 w-3.5" />}
            {v === "live" ? "Live" : "History"}
          </button>
        ))}
      </div>

      {/* History session picker */}
      {view === "history" && (
        <div className="mt-3">
          <p className="text-[11px] text-ink-3 mb-2">
            Last {(historyQ.data ?? []).length} archived session(s), newest first — a new session rolls
            when you sign back in. Select one to view its logs.
          </p>
          <div className="flex gap-2 flex-wrap">
            {(historyQ.data ?? []).length === 0 && (
              <span className="text-[12px] text-ink-4">No archived sessions yet.</span>
            )}
            {(historyQ.data ?? []).map((s) => (
              <button
                key={s.sid}
                onClick={() => setHistSid(s.sid)}
                className={cn(
                  "px-3 py-2 rounded-md border text-left transition-colors",
                  histSid === s.sid ? "border-accent/50 bg-accent/10" : "border-hairline hover:bg-surface-2",
                )}
              >
                <div className="text-[12px] text-ink font-mono">{new Date(s.archived_at).toLocaleString()}</div>
                <div className="text-[11px] text-ink-4">{s.count} lines · {s.sid.slice(0, 8)}</div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Toolbar */}
      <div className="mt-4 flex items-center gap-2 flex-wrap">
        <div className="relative flex-1 min-w-[180px]">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-ink-4" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter by text or correlation id…"
            className="w-full rounded-md border border-hairline bg-surface-2 pl-8 pr-3 py-2 text-[12.5px] focus:outline-none focus:border-accent transition-colors"
          />
        </div>
        <Button variant="outline" size="sm" onClick={() => setPaused((p) => !p)}>
          {paused ? <><Play className="h-3.5 w-3.5 mr-1" /> Resume</> : <><Pause className="h-3.5 w-3.5 mr-1" /> Pause</>}
        </Button>
        <Button variant="outline" size="sm" onClick={copyAll}><Copy className="h-3.5 w-3.5 mr-1" /> Copy</Button>
        <Button variant="outline" size="sm" onClick={download}><Download className="h-3.5 w-3.5 mr-1" /> Download</Button>
        <Button variant="ghost" size="sm" onClick={clearAll}><Trash2 className="h-3.5 w-3.5 mr-1" /> Clear</Button>
      </div>

      {/* Filter chips */}
      <div className="mt-3 flex items-center gap-1.5 flex-wrap text-[11px]">
        <span className="font-mono uppercase tracking-wider text-ink-4 mr-1">Level</span>
        {LEVELS.map((lv) => (
          <button
            key={lv}
            onClick={() => setLevelOn((s) => ({ ...s, [lv]: !s[lv] }))}
            className={cn(
              "px-2 py-1 rounded-full border transition-colors font-mono uppercase",
              levelOn[lv] ? "border-accent/50 bg-accent/15 text-accent" : "border-hairline text-ink-4",
            )}
          >
            {lv}
          </button>
        ))}
        <span className="font-mono uppercase tracking-wider text-ink-4 ml-3 mr-1">Source</span>
        {SOURCES.map((sc) => (
          <button
            key={sc}
            onClick={() => setSourceOn((s) => ({ ...s, [sc]: !s[sc] }))}
            className={cn(
              "px-2 py-1 rounded-full border transition-colors font-mono",
              sourceOn[sc] ? "border-accent/50 bg-accent/15 text-accent" : "border-hairline text-ink-4",
            )}
          >
            {sc}
          </button>
        ))}
        <span className="ml-auto font-mono text-ink-4">{rows.length} lines</span>
      </div>

      {/* Log stream */}
      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="mt-3 rounded-md bg-surface-1 border border-hairline overflow-auto h-[62vh] font-mono text-[11px] leading-relaxed"
      >
        {rows.length === 0 ? (
          <div className="h-full flex items-center justify-center text-ink-4 text-[12px] px-6 text-center">
            {view === "history"
              ? (histSid ? "No logs in this archived session." : "Select an archived session above to view its logs.")
              : enabled
              ? "No logs yet — interact with the app to see console, network and server activity appear here."
              : "Logging is off. Turn it on above, then reproduce the issue."}
          </div>
        ) : (
          <ul className="divide-y divide-[rgb(var(--line)/0.08)]">
            {rows.slice(-2000).map((r) => (
              <li key={r.key} className="flex gap-2 px-3 py-1.5 hover:bg-surface-2/50">
                <span className="text-ink-4 shrink-0 tabular-nums">{fmtTime(r.ts)}</span>
                <span className={cn("shrink-0 uppercase w-10", LEVEL_STYLE[r.level])}>{r.level}</span>
                <span className={cn("shrink-0 rounded px-1.5 text-[10px] self-start mt-[1px]", SOURCE_STYLE[r.source])}>
                  {r.source}
                </span>
                {r.correlationId && (
                  <span className="text-ink-4 shrink-0" title={r.correlationId}>{r.correlationId.slice(0, 8)}</span>
                )}
                <span className="whitespace-pre-wrap break-all text-ink">{r.message}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
