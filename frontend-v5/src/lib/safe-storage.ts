import type { PersistStorage, StorageValue } from "zustand/middleware";

export function safeGet<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key);
    if (raw === null) return null;
    return JSON.parse(raw) as T;
  } catch {
    safeRemove(key);
    return null;
  }
}

export function safeSet(key: string, value: unknown): boolean {
  try {
    localStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

export function safeRemove(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    // nothing we can do
  }
}

export function safeStorageAvailable(): boolean {
  try {
    const probe = "__nivesh_probe__";
    localStorage.setItem(probe, "1");
    localStorage.removeItem(probe);
    return true;
  } catch {
    return false;
  }
}

export function createSafeStorageAdapter<T>(): PersistStorage<T> {
  return {
    getItem(key: string): StorageValue<T> | null {
      return safeGet<StorageValue<T>>(key);
    },
    setItem(key: string, value: StorageValue<T>): void {
      safeSet(key, value);
    },
    removeItem(key: string): void {
      safeRemove(key);
    },
  };
}
