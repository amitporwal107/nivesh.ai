/**
 * Impersonation store — tracks which client profile the advisor is currently
 * "viewing as". The backend holds the real impersonation state (active_profile_id
 * cookie); this mirror lets the chrome render a persistent "Viewing <client>"
 * banner across navigation without an extra round-trip. Persisted so a refresh
 * keeps the banner in sync with the still-active backend cookie.
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { createSafeStorageAdapter } from "@/lib/safe-storage";

interface ImpersonationState {
  profileId: string | null;
  name: string | null;
  setImpersonating: (profileId: string, name: string) => void;
  clear: () => void;
}

export const useImpersonationStore = create<ImpersonationState>()(
  persist(
    (set) => ({
      profileId: null,
      name: null,
      setImpersonating: (profileId, name) => set({ profileId, name }),
      clear: () => set({ profileId: null, name: null }),
    }),
    { name: "nivesh.impersonation", storage: createSafeStorageAdapter() },
  ),
);
