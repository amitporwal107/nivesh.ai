/**
 * Sentry observer — drop-in observability impl.
 *
 * Wire at boot (main.tsx):
 *
 *   import * as Sentry from "@sentry/react";
 *   import { sentryObserver } from "@/lib/observability/sentry";
 *   Sentry.init({ dsn: import.meta.env.VITE_SENTRY_DSN, ... });
 *   setObserver(sentryObserver(Sentry));
 *
 * This file deliberately doesn't import @sentry/react at the top level —
 * the Sentry object is passed in. That keeps it swappable with Datadog etc.
 */
import type { ExtendedObserver } from "./component-events";

export interface MinimalSentry {
  captureException(
    err: unknown,
    ctx?: { tags?: Record<string, string>; extra?: Record<string, unknown> },
  ): void;
  captureMessage?(
    msg: string,
    level?: "fatal" | "error" | "warning" | "log" | "info" | "debug",
    ctx?: { tags?: Record<string, string>; extra?: Record<string, unknown> },
  ): void;
  metrics?: {
    // Sentry SDK v8+ uses MetricOptions object; accept any to stay compatible
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    distribution(name: string, value: number, options?: any): void;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    increment?(name: string, value?: number, options?: any): void;
  };
}

export function sentryObserver(sentry: MinimalSentry): ExtendedObserver {
  return {
    // ── HTTP request lifecycle ──────────────────────────────────────────────

    onRequestStart() {
      // no-op — capture duration in onRequestEnd
    },

    onRequestEnd({ url, status, durationMs }) {
      sentry.metrics?.distribution("api.duration", durationMs, { unit: "millisecond" });
      sentry.metrics?.distribution(`api.duration.${status}`, durationMs, { unit: "millisecond" });
      if (durationMs > 3_000) {
        console.warn(`[api] slow ${status} ${url}: ${durationMs.toFixed(0)}ms`);
      }
    },

    onRequestError({ error, url, correlationId, durationMs }) {
      sentry.captureException(error, {
        tags: { source: "api" },
        extra: { url, correlationId, durationMs },
      });
    },

    // ── Component lifecycle ─────────────────────────────────────────────────

    onComponentCrash({ component, error, buildId, gitSha }) {
      sentry.captureException(error, {
        tags: {
          source: "component",
          component,
          build_id: buildId,
          git_sha: gitSha,
        },
        extra: { component, buildId, gitSha },
      });
      // Increment a counter metric so Grafana can chart crash rate over time
      sentry.metrics?.increment?.("component.crash", 1, { tags: { component } });
    },

    onComponentRecover({ component, attemptNumber }) {
      sentry.captureMessage?.(
        `Component self-recovered: ${component} (attempt ${attemptNumber})`,
        "info",
        { tags: { source: "component", component }, extra: { attemptNumber } },
      );
      sentry.metrics?.increment?.("component.recover", 1, { tags: { component } });
    },

    onComponentHealth({ component, status }) {
      // Only report degraded/dead transitions — healthy is noise
      if (status !== "healthy") {
        sentry.captureMessage?.(
          `Component health degraded: ${component} → ${status}`,
          "warning",
          { tags: { source: "component", component, health_status: status } },
        );
      }
      sentry.metrics?.distribution?.("component.health", status === "healthy" ? 1 : 0, { unit: "none" });
    },
  };
}
