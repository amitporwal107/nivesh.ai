/**
 * Environment-driven API configuration.
 *
 * Values come from Vite env (`VITE_*`) with safe fallbacks for local dev.
 * When `VITE_USE_MOCK_API=true`, `services/index.ts` swaps real adapters for
 * mock impls — adapter signatures stay identical, so callers don't care.
 */
export interface ApiConfig {
  baseUrl: string;
  useMock: boolean;
  requestTimeoutMs: number;
  retry: { attempts: number; baseDelayMs: number };
  appVersion: string;
}

const env = (import.meta as ImportMeta & { env: Record<string, string | undefined> }).env ?? {};

// A blank VITE_API_BASE_URL is documented to mean "issue relative /api/* calls"
// (see .env.local). Treat empty/whitespace as unset so it resolves against the
// current origin instead of throwing in `new URL(path, "")`.
const firstNonBlank = (...vals: (string | undefined)[]): string | undefined =>
  vals.find((v) => typeof v === "string" && v.trim() !== "");

export const apiConfig: ApiConfig = {
  baseUrl:
    firstNonBlank(env.VITE_API_BASE_URL, env.VITE_API_URL) ??
    (typeof window !== "undefined" ? window.location.origin : ""),
  useMock: (env.VITE_USE_MOCK_API ?? "false").toLowerCase() === "true",
  requestTimeoutMs: Number(env.VITE_API_TIMEOUT_MS ?? 15_000),
  retry: {
    attempts: Number(env.VITE_API_RETRY_ATTEMPTS ?? 1),
    baseDelayMs: Number(env.VITE_API_RETRY_DELAY_MS ?? 400),
  },
  appVersion: env.VITE_APP_VERSION ?? "0.1.0",
};
