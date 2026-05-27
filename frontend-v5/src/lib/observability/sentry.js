export function sentryObserver(sentry) {
    return {
        onRequestStart() { },
        onRequestEnd({ url, status, durationMs }) {
            sentry.metrics?.distribution(`api.duration`, durationMs, "millisecond");
            sentry.metrics?.distribution(`api.duration.${status}`, durationMs, "millisecond");
            // optionally: log slow requests
            if (durationMs > 3_000) {
                // eslint-disable-next-line no-console
                console.warn(`[api] slow ${status} ${url}: ${durationMs.toFixed(0)}ms`);
            }
        },
        onRequestError({ error, url, correlationId, durationMs }) {
            sentry.captureException(error, {
                tags: { source: "api" },
                extra: { url, correlationId, durationMs },
            });
        },
    };
}
