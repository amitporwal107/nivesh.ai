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

export const apiConfig: ApiConfig = {
  baseUrl:
    env.VITE_API_BASE_URL ??
    "https://staging.niveshcopilot.com",
  useMock: (env.VITE_USE_MOCK_API ?? "true").toLowerCase() === "true",
  requestTimeoutMs: Number(env.VITE_API_TIMEOUT_MS ?? 15_000),
  retry: {
    attempts: Number(env.VITE_API_RETRY_ATTEMPTS ?? 1),
    baseDelayMs: Number(env.VITE_API_RETRY_DELAY_MS ?? 400),
  },
  appVersion: env.VITE_APP_VERSION ?? "0.1.0",
};
