import type { TokenResponse, UserResponse } from "@audiobook/shared-types";
import { create } from "zustand";

export type AuthStatus = "bootstrapping" | "bootstrapFailed" | "signedOut" | "signedIn";

interface AuthState {
  status: AuthStatus;
  user: UserResponse | null;
  /** Kept in memory only; the refresh token is the only credential written to disk (secure storage). */
  accessToken: string | null;
  setSession: (tokens: TokenResponse) => void;
  clearSession: () => void;
  setStatus: (status: AuthStatus) => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  status: "bootstrapping",
  user: null,
  accessToken: null,
  setSession: (tokens) => set({ status: "signedIn", user: tokens.user, accessToken: tokens.access_token }),
  clearSession: () => set({ status: "signedOut", user: null, accessToken: null }),
  setStatus: (status) => set({ status }),
}));
