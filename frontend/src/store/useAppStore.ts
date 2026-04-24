import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import type { AuthUser } from "../types";

interface AppStore {
  authUser: AuthUser | null;
  provider: string;
  selectedTopic: string;
  selectedMode: string;
  isChatOpen: boolean;
  setAuthUser: (user: AuthUser | null) => void;
  logout: () => void;
  setProvider: (provider: string) => void;
  setSelection: (topic: string, mode: string) => void;
  clearSelection: () => void;
  setChatOpen: (open: boolean) => void;
}

export const useAppStore = create<AppStore>()(
  persist(
    (set) => ({
      authUser: null,
      provider: "auto",
      selectedTopic: "",
      selectedMode: "",
      isChatOpen: false,
      setAuthUser: (authUser) => set({ authUser }),
      logout: () =>
        set({
          authUser: null,
          selectedTopic: "",
          selectedMode: "",
          isChatOpen: false,
        }),
      setProvider: (provider) => set({ provider }),
      setSelection: (selectedTopic, selectedMode) => set({ selectedTopic, selectedMode }),
      clearSelection: () => set({ selectedTopic: "", selectedMode: "" }),
      setChatOpen: (isChatOpen) => set({ isChatOpen }),
    }),
    {
      name: "interview-prep-ai-store",
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        authUser: state.authUser,
        provider: state.provider,
      }),
    },
  ),
);
