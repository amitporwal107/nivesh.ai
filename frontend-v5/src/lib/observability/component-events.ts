import type React from "react";
import type { Observer } from "../observability";
import { getObserver } from "../observability";

export interface ComponentCrashEvent {
  component: string;
  error: Error;
  errorInfo: React.ErrorInfo;
  buildId: string;
  gitSha: string;
  timestamp: number;
}

export interface ComponentRecoverEvent {
  component: string;
  attemptNumber: number;
  timestamp: number;
}

export interface ComponentHealthEvent {
  component: string;
  status: "healthy" | "degraded" | "dead";
  timestamp: number;
}

export interface ExtendedObserver extends Observer {
  onComponentCrash?(e: ComponentCrashEvent): void;
  onComponentRecover?(e: ComponentRecoverEvent): void;
  onComponentHealth?(e: ComponentHealthEvent): void;
}

export function reportComponentCrash(e: ComponentCrashEvent): void {
  const obs = getObserver() as ExtendedObserver;
  obs.onComponentCrash?.(e);
  console.error(`[component-crash] ${e.component}`, e.error, `build=${e.buildId}`);
}

export function reportComponentRecover(e: ComponentRecoverEvent): void {
  const obs = getObserver() as ExtendedObserver;
  obs.onComponentRecover?.(e);
  console.info(`[component-recover] ${e.component} attempt=${e.attemptNumber}`);
}

export function reportComponentHealth(e: ComponentHealthEvent): void {
  const obs = getObserver() as ExtendedObserver;
  obs.onComponentHealth?.(e);
}
