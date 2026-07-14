/**
 * logging.store — persists whether session logging is ON and the debug-session
 * id minted by the backend (Settings → Logs & Diagnostics).
 *
 * OFF by default. When enabled, the HTTP client (services/api/http.ts) reads
 * `sid` and echoes it on every request via the X-Nivesh-Debug-Session header so
 * the backend buffers that session's server logs. `applySession` also flips the
 * client-side console/network/error capture on or off to keep the two in sync.
 *
 * Only { enabled, sid } is persisted — never the captured log lines.
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { createSafeStorageAdapter } from "@/lib/safe-storage";
import { startCapture, stopCapture } from "@/lib/session-log";

interface LoggingState {
  enabled: boolean;
  sid: string | null;
  /** Set the session state AND turn client-side capture on/off to match. */
  applySession: (enabled: boolean, sid: string | null) => void;
}

export const useLoggingStore = create<LoggingState>()(
  persist(
    (set) => ({
      enabled: false,
      sid: null,
      applySession: (enabled, sid) => {
        // Client-side capture follows `enabled`. `sid` only gates the server
        // header (http.ts), so client logs still work if server capture is down.
        if (enabled) startCapture();
        else stopCapture();
        set({ enabled, sid: enabled ? sid : null });
      },
    }),
    { name: "nivesh.logging", storage: createSafeStorageAdapter() },
  ),
);

/**
 * Called once at boot: if the user had logging on in a previous tab/session,
 * resume client-side capture (without re-hitting the backend enable endpoint).
 */
export function resumeCaptureIfEnabled(): void {
  if (useLoggingStore.getState().enabled) startCapture();
}
