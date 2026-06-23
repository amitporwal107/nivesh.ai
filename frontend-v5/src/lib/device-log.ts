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

export const LOG_FILE = "nivesh-debug.log";

const MAX_LINES = 1000;
let buffer: string[] = [];

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

/** Append a timestamped line to the device log (and console). */
export function dlog(...args: unknown[]): void {
  const line = `[${stamp()}] ${args.map(stringify).join(" ")}`;
  buffer.push(line);
  if (buffer.length > MAX_LINES) buffer = buffer.slice(-MAX_LINES);
  // eslint-disable-next-line no-console
  console.log(line);
  void persist(line);
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
