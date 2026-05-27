import { create } from "zustand";
import { persist } from "zustand/middleware";
export const useUIStore = create()(persist((set) => ({
    theme: "light",
    persona: "client",
    sidebarCollapsed: false,
    setTheme: (theme) => set({ theme }),
    setPersona: (persona) => set({ persona }),
    toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
}), { name: "nivesh.ui" }));
