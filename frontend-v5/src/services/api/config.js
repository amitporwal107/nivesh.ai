const env = import.meta.env ?? {};
export const apiConfig = {
    baseUrl: env.VITE_API_BASE_URL ??
        "https://staging.niveshcopilot.com",
    useMock: (env.VITE_USE_MOCK_API ?? "true").toLowerCase() === "true",
    requestTimeoutMs: Number(env.VITE_API_TIMEOUT_MS ?? 15_000),
    retry: {
        attempts: Number(env.VITE_API_RETRY_ATTEMPTS ?? 1),
        baseDelayMs: Number(env.VITE_API_RETRY_DELAY_MS ?? 400),
    },
    appVersion: env.VITE_APP_VERSION ?? "0.1.0",
};
