/**
 * Sentry observer — drop-in observability impl.
 *
 * Wire at boot (main.tsx):
 *
 *   import { setObserver } from "@/lib/observability";
 *   import { sentryObserver } from "@/lib/observability/sentry";
 *   import * as Sentry from "@sentry/react";
 *   Sentry.init({ dsn: import.meta.env.VITE_SENTRY_DSN, ... });
 *   setObserver(sentryObserver(Sentry));
 *
 * This file deliberately doesn't import @sentry/react — it's passed in. That
 * keeps Sentry an optional dependency and lets you swap in Datadog with the
 * same shape.
 */
import type { Observer } from "../observability";

export interface MinimalSentry {
  captureException(err: unknown, ctx?: { tags?: Record<string, string>; extra?: Record<string, unknown> }): void;
  metrics?: { distribution(name: string, value: number, unit?: string): void };
}

export function sentryObserver(sentry: MinimalSentry): Observer {
  return {
    onRequestStart() { /* no-op — start traces in onRequestEnd to capture duration */ },
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
