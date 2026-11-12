import { create } from "zustand";
import { exchangeApi } from "@/lib/api";
import type { UserSummary } from "@/types/exchange";

interface AuthState {
  token: string | null;
  user: UserSummary | null;
  hydrated: boolean;
  loading: boolean;
  error: string | null;
  hydrate: () => Promise<void>;
  login: (email: string, password: string) => Promise<UserSummary>;
  register: (params: {
    email: string;
    username: string;
    password: string;
    display_name: string;
    institution?: string;
  }) => Promise<UserSummary>;
  logout: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  token: null,
  user: null,
  hydrated: false,
  loading: false,
  error: null,

  hydrate: async () => {
    if (typeof window === "undefined") return;
    const saved = window.localStorage.getItem("mtt_access_token");
    if (!saved) {
      set({ token: null, user: null, hydrated: true });
      return;
    }
    try {
      const me = await exchangeApi.me();
      set({ token: saved, user: me, hydrated: true, error: null });
    } catch {
      window.localStorage.removeItem("mtt_access_token");
      set({ token: null, user: null, hydrated: true });
    }
  },

  login: async (email, password) => {
    set({ loading: true, error: null });
    try {
      const res = await exchangeApi.login(email, password);
      if (typeof window !== "undefined") {
        window.localStorage.setItem("mtt_access_token", res.access_token);
      }
      set({ token: res.access_token, user: res.user, loading: false, hydrated: true });
      return res.user;
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Authentication failed";
      set({ loading: false, error: msg });
      throw err;
    }
  },

  register: async (params) => {
    set({ loading: true, error: null });
    try {
      const res = await exchangeApi.register(params);
      if (typeof window !== "undefined") {
        window.localStorage.setItem("mtt_access_token", res.access_token);
      }
      set({ token: res.access_token, user: res.user, loading: false, hydrated: true });
      return res.user;
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Registration failed";
      set({ loading: false, error: msg });
      throw err;
    }
  },

  logout: () => {
    if (typeof window !== "undefined") {
      window.localStorage.removeItem("mtt_access_token");
    }
    set({ token: null, user: null, error: null });
  },
}));
