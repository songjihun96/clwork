import { create } from "zustand";

export type ThemePreference = "system" | "light" | "dark";

interface SettingsState {
  themePreference: ThemePreference;
  setThemePreference: (preference: ThemePreference) => void;
}

// Phase 1: in-memory only. Persisted locally and synced to the account in Phase 2.
export const useSettingsStore = create<SettingsState>((set) => ({
  themePreference: "system",
  setThemePreference: (themePreference) => set({ themePreference }),
}));
