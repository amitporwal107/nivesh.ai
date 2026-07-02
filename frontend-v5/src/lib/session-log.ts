/**
 * session-log — client-side capture buffer for Settings → Logs & Diagnostics.
 *
 * When the user turns logging on, we start capturing three streams into an
 * in-memory ring buffer that the /settings/logs viewer renders live:
 *   - console.*  (log / info / warn / error / debug)
 *   - network    (every API request lifecycle, via the observability Observer)
 *   - errors     (window.onerror / unhandledrejection, forwarded from main.tsx)
 *
 * Capture is OFF by default and fully reversible: startCapture() patches the
 * console + installs an Observer; stopCapture() restores both. Nothing is
 * captured — and there is no console/observer patching — until startCapture()
 * runs, so there is zero overhead while the feature is off.
 *
 * The buffer is in-memory only (not persisted) — it holds the current tab's
 * session. Server-side logs for the same session are fetched separately via the
 * session-logs API and merged in the viewer by timestamp.
 */
import {
  getObserver,
  setObserver,
  type Observer,
  type RequestStartEvent,
  type RequestEndEvent,
  type RequestErrorEvent,
} from "@/lib/observability";

export type LogLevel = "debug" | "info" | "warn" | "error";
export type LogSource = "console" | "network" | "error" | "client";

export interface ClientLogEntry {
  id: number;
  ts: string; // ISO-8601
  level: LogLevel;
  source: LogSource;
  message: string;
  correlationId?: string;
}

const MAX_ENTRIES = 3000;

let buffer: ClientLogEntry[] = [];
let seq = 0;
let version = 0; // bumped on every change so useSyncExternalStore can track it
let capturing = false;

// Console + observer state we restore on stopCapture().
type ConsoleMethod = "log" | "info" | "warn" | "error" | "debug";
const CONSOLE_METHODS: ConsoleMethod[] = ["log", "info", "warn", "error", "debug"];
const originalConsole: Partial<Record<ConsoleMethod, (...args: unknown[]) => void>> = {};
let previousObserver: Observer | null = null;
let inRecord = false; // re-entrancy guard so recording never triggers itself

// ── Subscribers (the viewer re-renders when the buffer changes) ───────────────
type Listener = () => void;
const listeners = new Set<Listener>();

function emitChange(): void {
  version++;
  for (const l of listeners) {
    try {
      l();
    } catch {
      /* a bad listener must not break logging */
    }
  }
}

export function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Monotonic change counter — use as a useSyncExternalStore snapshot. */
export function getVersion(): number {
  return version;
}

/** Snapshot of the current buffer (newest last). */
export function getEntries(): ClientLogEntry[] {
  return buffer;
}

export function clearEntries(): void {
  buffer = [];
  emitChange();
}

export function isCapturing(): boolean {
  return capturing;
}

/** Low-level append. Bounded ring buffer; never throws. */
export function record(
  level: LogLevel,
  source: LogSource,
  message: string,
  correlationId?: string,
): void {
  if (!capturing) return;
  try {
    buffer.push({
      id: ++seq,
      ts: new Date().toISOString(),
      level,
      source,
      message,
      correlationId,
    });
    if (buffer.length > MAX_ENTRIES) buffer = buffer.slice(-MAX_ENTRIES);
    emitChange();
  } catch {
    /* logging must never break the app */
  }
}

function stringifyArg(v: unknown): string {
  if (typeof v === "string") return v;
  if (v instanceof Error) return `${v.name}: ${v.message}${v.stack ? `\n${v.stack}` : ""}`;
  try {
    return JSON.stringify(v);
  } catch {
    return String(v);
  }
}

function formatArgs(args: unknown[]): string {
  return args.map(stringifyArg).join(" ");
}

/** Record a global/runtime error (called from window.onerror & rejection handlers). */
export function recordClientError(message: string): void {
  record("error", "error", message);
}

// ── Network capture: an Observer that records API lifecycle events ────────────
class SessionLogObserver implements Observer {
  constructor(private readonly prev: Observer) {}

  onRequestStart(e: RequestStartEvent): void {
    record("debug", "network", `→ ${e.method} ${e.url}`, e.correlationId);
  }

  onRequestEnd(e: RequestEndEvent): void {
    const level: LogLevel = e.status >= 500 ? "error" : e.status >= 400 ? "warn" : "info";
    record(
      level,
      "network",
      `← ${e.status} ${e.method} ${e.url} (${e.durationMs.toFixed(0)}ms)`,
      e.correlationId,
    );
  }

  onRequestError(e: RequestErrorEvent): void {
    record(
      "error",
      "network",
      `✗ ${e.method} ${e.url} (${e.durationMs.toFixed(0)}ms) — ${stringifyArg(e.error)}`,
      e.correlationId,
    );
    // Preserve upstream error telemetry (e.g. Sentry) while capturing.
    try {
      this.prev.onRequestError(e);
    } catch {
      /* ignore */
    }
  }
}

const LEVEL_BY_CONSOLE: Record<ConsoleMethod, LogLevel> = {
  log: "info",
  info: "info",
  warn: "warn",
  error: "error",
  debug: "debug",
};

function patchConsole(): void {
  if (typeof console === "undefined") return;
  for (const m of CONSOLE_METHODS) {
    const original = console[m] as ((...args: unknown[]) => void) | undefined;
    if (typeof original !== "function") continue;
    originalConsole[m] = original.bind(console);
    console[m] = (...args: unknown[]) => {
      originalConsole[m]?.(...args);
      if (inRecord) return;
      inRecord = true;
      try {
        record(LEVEL_BY_CONSOLE[m], "console", formatArgs(args));
      } finally {
        inRecord = false;
      }
    };
  }
}

function restoreConsole(): void {
  if (typeof console === "undefined") return;
  for (const m of CONSOLE_METHODS) {
    const original = originalConsole[m];
    if (original) {
      console[m] = original as never;
      delete originalConsole[m];
    }
  }
}

/** Begin capturing console + network + errors. Idempotent. */
export function startCapture(): void {
  if (capturing) return;
  capturing = true;
  patchConsole();
  previousObserver = getObserver();
  setObserver(new SessionLogObserver(previousObserver));
  record("info", "client", "Session logging started");
}

/** Stop capturing and restore the console + observer. Idempotent. */
export function stopCapture(): void {
  if (!capturing) return;
  record("info", "client", "Session logging stopped");
  restoreConsole();
  if (previousObserver) {
    setObserver(previousObserver);
    previousObserver = null;
  }
  capturing = false;
}
