/**
 * Observability hooks — pluggable.
 *
 * Default impl logs to console; swap with Sentry/Datadog by replacing the
 * implementation of each handler. The contract is intentionally narrow so
 * the http client stays agnostic.
 */
export interface RequestStartEvent {
  correlationId: string;
  method: string;
  url: string;
  startedAt: number;
}

export interface RequestEndEvent extends RequestStartEvent {
  status: number;
  durationMs: number;
}

export interface RequestErrorEvent extends RequestStartEvent {
  error: unknown;
  durationMs: number;
}

export interface Observer {
  onRequestStart(e: RequestStartEvent): void;
  onRequestEnd(e: RequestEndEvent): void;
  onRequestError(e: RequestErrorEvent): void;
}

class ConsoleObserver implements Observer {
  onRequestStart({ correlationId, method, url }: RequestStartEvent) {
    if (typeof console !== "undefined") {
      console.debug(`[api ${correlationId.slice(0, 8)}] → ${method} ${url}`);
    }
  }
  onRequestEnd({ correlationId, status, durationMs, method, url }: RequestEndEvent) {
    if (typeof console !== "undefined") {
      console.debug(`[api ${correlationId.slice(0, 8)}] ← ${status} ${method} ${url} (${durationMs.toFixed(0)}ms)`);
    }
  }
  onRequestError({ correlationId, error, durationMs, method, url }: RequestErrorEvent) {
    if (typeof console !== "undefined") {
      console.warn(`[api ${correlationId.slice(0, 8)}] ✗ ${method} ${url} (${durationMs.toFixed(0)}ms)`, error);
    }
  }
}

let activeObserver: Observer = new ConsoleObserver();

export function setObserver(observer: Observer): void {
  activeObserver = observer;
}

export function getObserver(): Observer {
  return activeObserver;
}

// Component-level observability events (extend Observer without breaking existing impls)
export type { ExtendedObserver, ComponentCrashEvent, ComponentRecoverEvent, ComponentHealthEvent }
  from "./observability/component-events";
export { reportComponentCrash, reportComponentRecover, reportComponentHealth }
  from "./observability/component-events";

/** RFC-4122 v4-ish (best-effort, not crypto). */
export function correlationId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return (crypto as Crypto & { randomUUID(): string }).randomUUID();
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}
