import { create } from "zustand";
import { persist } from "zustand/middleware";

type Theme = "light" | "dark";
type Persona = "client" | "advisor";

interface UIState {
  theme: Theme;
  persona: Persona;
  sidebarCollapsed: boolean;
  setTheme: (t: Theme) => void;
  setPersona: (p: Persona) => void;
  toggleSidebar: () => void;
}

export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      theme: "light",
      persona: "client",
      sidebarCollapsed: false,
      setTheme: (theme) => set({ theme }),
      setPersona: (persona) => set({ persona }),
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
    }),
    { name: "nivesh.ui" },
  ),
);
