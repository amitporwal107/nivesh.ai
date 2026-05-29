export type HealthStatus = "healthy" | "degraded" | "dead";

export interface ComponentHealthRecord {
  name: string;
  version: string;
  status: HealthStatus;
  registeredAt: number;
  lastUpdatedAt: number;
  crashCount: number;
  lastFingerprintId?: string;
}

const registry = new Map<string, ComponentHealthRecord>();

export function registerComponent(name: string, version = "unknown"): void {
  if (!registry.has(name)) {
    registry.set(name, {
      name,
      version,
      status: "healthy",
      registeredAt: Date.now(),
      lastUpdatedAt: Date.now(),
      crashCount: 0,
    });
  }
}

export function updateComponentHealth(
  name: string,
  status: HealthStatus,
  fingerprintId?: string,
): void {
  const record = registry.get(name);
  if (!record) return;
  record.status = status;
  record.lastUpdatedAt = Date.now();
  if (status === "dead") {
    record.crashCount += 1;
    if (fingerprintId) record.lastFingerprintId = fingerprintId;
  }
}

export function getHealthRegistry(): ReadonlyMap<string, ComponentHealthRecord> {
  return registry;
}

export function getOverallHealth(): "healthy" | "degraded" | "critical" {
  for (const r of registry.values()) {
    if (r.status === "dead") return "critical";
  }
  for (const r of registry.values()) {
    if (r.status === "degraded") return "degraded";
  }
  return "healthy";
}

// Expose on window for devtools access
if (typeof window !== "undefined") {
  window.__APP_HEALTH__ = {
    get: getHealthRegistry,
    getOverall: getOverallHealth,
  };
}
