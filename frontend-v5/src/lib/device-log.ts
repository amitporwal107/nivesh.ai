/**
 * device-log — a tiny persistent logger for debugging the native Android app.
 *
 * Every dlog() call is appended to an on-device file AND kept in an in-memory
 * ring buffer (the fallback on web / if the file write fails). The file
 * survives app restarts so an error can be retrieved after the fact.
 *
 * File location on Android (app-specific external storage, no permission needed):
 *   /storage/emulated/0/Android/data/ai.nivesh.staging/files/nivesh-debug.log
 *
 * Read it from inside the app at /debug-logs (Copy / Share / Clear), or pull it
 * over USB:  adb pull /storage/emulated/0/Android/data/ai.nivesh.staging/files/nivesh-debug.log
 */
import { Capacitor } from "@capacitor/core";
import { apiConfig } from "@/services/api/config";

export const LOG_FILE = "nivesh-debug.log";

const MAX_LINES = 1000;
let buffer: string[] = [];

// ── Cloud Logging push (app → backend /api/client-logs → GCP Cloud Logging) ──
// The shared secret is baked in at build time (VITE_CLIENT_LOG_KEY). When it's
// absent, or we're on web, cloud push is disabled and we keep only the local file.
const CLIENT_LOG_KEY =
  (import.meta as unknown as { env?: Record<string, string> }).env?.VITE_CLIENT_LOG_KEY ?? "";
const CLOUD_BATCH = 25;
const CLOUD_FLUSH_MS = 4000;
type CloudEntry = { ts: string; level: string; message: string };
let pendingCloud: CloudEntry[] = [];
let flushTimer: ReturnType<typeof setTimeout> | null = null;

function cloudEnabled(): boolean {
  return Capacitor.isNativePlatform() && Boolean(CLIENT_LOG_KEY);
}

function queueCloud(level: string, message: string): void {
  if (!cloudEnabled()) return;
  pendingCloud.push({ ts: stamp(), level, message });
  if (pendingCloud.length >= CLOUD_BATCH) {
    void flushCloud();
  } else if (!flushTimer) {
    flushTimer = setTimeout(() => void flushCloud(), CLOUD_FLUSH_MS);
  }
}

/** Flush queued log lines to the backend ingest endpoint (best-effort). */
export async function flushCloud(): Promise<void> {
  if (flushTimer) { clearTimeout(flushTimer); flushTimer = null; }
  if (!cloudEnabled() || pendingCloud.length === 0) return;
  const batch = pendingCloud;
  pendingCloud = [];
  try {
    await fetch(`${apiConfig.baseUrl}/api/client-logs`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Client-Log-Key": CLIENT_LOG_KEY },
      body: JSON.stringify({
        meta: { platform: Capacitor.getPlatform(), appVersion: apiConfig.appVersion },
        entries: batch,
      }),
      keepalive: true,
    });
  } catch {
    // Re-queue (bounded) so a transient failure doesn't lose the lines.
    pendingCloud = batch.concat(pendingCloud).slice(-MAX_LINES);
  }
}

function stamp(): string {
  // Date is fine in the browser/webview runtime (this is app code, not a workflow).
  return new Date().toISOString();
}

function stringify(v: unknown): string {
  if (typeof v === "string") return v;
  if (v instanceof Error) {
    // Pull non-enumerable props (message/stack) plus any extra fields (e.g. code).
    const obj: Record<string, unknown> = { name: v.name, message: v.message, stack: v.stack };
    for (const k of Object.keys(v as object)) obj[k] = (v as unknown as Record<string, unknown>)[k];
    return JSON.stringify(obj);
  }
  try {
    return JSON.stringify(v, Object.getOwnPropertyNames(v as object));
  } catch {
    return String(v);
  }
}

async function persist(line: string): Promise<void> {
  if (!Capacitor.isNativePlatform()) return;
  try {
    const { Filesystem, Directory, Encoding } = await import("@capacitor/filesystem");
    // appendFile creates the file if it doesn't exist (Capacitor 6).
    await Filesystem.appendFile({
      path: LOG_FILE,
      data: line + "\n",
      directory: Directory.External,
      encoding: Encoding.UTF8,
    });
  } catch {
    /* keep the in-memory copy; file write is best-effort */
  }
}

/** Append a timestamped line to the device log (console + file + cloud). */
export function dlog(...args: unknown[]): void {
  const body = args.map(stringify).join(" ");
  const line = `[${stamp()}] ${body}`;
  buffer.push(line);
  if (buffer.length > MAX_LINES) buffer = buffer.slice(-MAX_LINES);
  // eslint-disable-next-line no-console
  console.log(line);
  void persist(line);
  const level = /\b(FAILED|error|onerror|unhandledrejection|exception)\b/i.test(body)
    ? "error"
    : "info";
  queueCloud(level, body);
}

/** Read the full log — from the device file when available, else the buffer. */
export async function readDeviceLog(): Promise<string> {
  if (Capacitor.isNativePlatform()) {
    try {
      const { Filesystem, Directory, Encoding } = await import("@capacitor/filesystem");
      const res = await Filesystem.readFile({
        path: LOG_FILE,
        directory: Directory.External,
        encoding: Encoding.UTF8,
      });
      const data = typeof res.data === "string" ? res.data : "";
      return data || buffer.join("\n");
    } catch {
      /* fall through to the buffer */
    }
  }
  return buffer.join("\n");
}

/** Absolute file:// path of the log on device (for display / Share), or null. */
export async function deviceLogUri(): Promise<string | null> {
  if (!Capacitor.isNativePlatform()) return null;
  try {
    const { Filesystem, Directory } = await import("@capacitor/filesystem");
    const res = await Filesystem.getUri({ path: LOG_FILE, directory: Directory.External });
    return res.uri;
  } catch {
    return null;
  }
}

/** Clear both the file and the in-memory buffer. */
export async function clearDeviceLog(): Promise<void> {
  buffer = [];
  if (!Capacitor.isNativePlatform()) return;
  try {
    const { Filesystem, Directory, Encoding } = await import("@capacitor/filesystem");
    await Filesystem.writeFile({
      path: LOG_FILE,
      data: "",
      directory: Directory.External,
      encoding: Encoding.UTF8,
    });
  } catch {
    /* best-effort */
  }
}
