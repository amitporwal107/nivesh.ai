import { getCrashCount } from "./crash-fingerprint";

export type WidgetFlagKey =
  | "persona_card"
  | "risk_profile_card"
  | "portfolio_value_card"
  | "health_score_card"
  | "intelligence_feed"
  | "quick_actions"
  | "action_matrix"
  | "improve_cta";

const flagStore: Record<WidgetFlagKey, boolean> = {
  persona_card: true,
  risk_profile_card: true,
  portfolio_value_card: true,
  health_score_card: true,
  intelligence_feed: true,
  quick_actions: true,
  action_matrix: true,
  improve_cta: true,
};

const disableReasons: Partial<Record<WidgetFlagKey, string>> = {};

export function isEnabled(key: WidgetFlagKey): boolean {
  return flagStore[key] ?? true;
}

export function disableFlag(key: WidgetFlagKey, reason = "manual"): void {
  flagStore[key] = false;
  disableReasons[key] = reason;
  console.warn(`[feature-flags] "${key}" disabled — ${reason}`);
}

export function enableFlag(key: WidgetFlagKey): void {
  flagStore[key] = true;
  delete disableReasons[key];
  console.info(`[feature-flags] "${key}" re-enabled`);
}

export function getAllFlags(): Record<WidgetFlagKey, boolean> {
  return { ...flagStore };
}

export function autoDisableIfThresholdExceeded(
  key: WidgetFlagKey | undefined,
  fpId: string,
  threshold = 5,
): void {
  if (!key) return;
  if (!flagStore[key]) return; // already disabled
  const count = getCrashCount(fpId);
  if (count >= threshold) {
    disableFlag(key, `crash threshold exceeded (${count} crashes, fingerprint ${fpId})`);
  }
}

// Expose on window for devtools / manual overrides
if (typeof window !== "undefined") {
  window.__FLAGS__ = {
    isEnabled: (k: string) => isEnabled(k as WidgetFlagKey),
    disableFlag: (k: string, reason?: string) => disableFlag(k as WidgetFlagKey, reason),
    enableFlag: (k: string) => enableFlag(k as WidgetFlagKey),
    getAll: getAllFlags,
  };
}
