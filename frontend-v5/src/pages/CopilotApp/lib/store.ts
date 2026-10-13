/**
 * Copilot app preferences that survive a reload: the chosen mode and whether
 * the evidence panel was opened or closed by hand.
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { createSafeStorageAdapter } from "@/lib/safe-storage";
import type { Mode } from "./views";

interface CopilotPrefs {
  mode: Mode;
  /** null = follow the layout default (open on wide screens only). */
  evidenceOpen: boolean | null;
  setMode: (m: Mode) => void;
  setEvidenceOpen: (v: boolean | null) => void;
}

export const useCopilotPrefs = create<CopilotPrefs>()(
  persist(
    (set) => ({
      mode: "investor",
      evidenceOpen: null,
      setMode: (mode) => set({ mode }),
      setEvidenceOpen: (evidenceOpen) => set({ evidenceOpen }),
    }),
    { name: "nivesh.copilot", storage: createSafeStorageAdapter() },
  ),
);
