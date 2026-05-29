export interface CrashFingerprint {
  id: string;
  component: string;
  errorMessage: string;
  buildId: string;
  count: number;
  affectedComponents: string[];
  firstSeen: number;
  lastSeen: number;
}

function djb2(s: string): number {
  let h = 5381;
  for (let i = 0; i < s.length; i++) {
    h = ((h << 5) + h) ^ s.charCodeAt(i);
    h = h >>> 0; // keep unsigned 32-bit
  }
  return h;
}

export function fingerprintId(error: Error, component: string, buildId: string): string {
  const raw = `${error.message}|${component}|${buildId}`;
  const hash = djb2(raw) % 9999;
  return `ERR-${String(hash).padStart(3, "0")}`;
}

const crashRegistry = new Map<string, CrashFingerprint>();

export function recordCrash(error: Error, component: string, buildId: string): CrashFingerprint {
  const id = fingerprintId(error, component, buildId);
  const now = Date.now();
  const existing = crashRegistry.get(id);
  if (existing) {
    existing.count += 1;
    existing.lastSeen = now;
    if (!existing.affectedComponents.includes(component)) {
      existing.affectedComponents.push(component);
    }
    return existing;
  }
  const record: CrashFingerprint = {
    id,
    component,
    errorMessage: error.message,
    buildId,
    count: 1,
    affectedComponents: [component],
    firstSeen: now,
    lastSeen: now,
  };
  crashRegistry.set(id, record);
  return record;
}

export function getCrashRegistry(): ReadonlyMap<string, CrashFingerprint> {
  return crashRegistry;
}

export function getCrashCount(fpId: string): number {
  return crashRegistry.get(fpId)?.count ?? 0;
}
