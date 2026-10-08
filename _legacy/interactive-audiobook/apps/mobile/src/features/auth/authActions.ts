import { NetworkError, unwrap } from "@audiobook/api-client";

import { queryClient } from "../../lib/queryClient";
import { api, refreshSession, tokenStore } from "../../services/api";
import { useAuthStore } from "./authStore";
import { refreshTokenStorage } from "./tokenStorage";

/** Restores the session on app start from the stored refresh token. */
export async function bootstrapSession(): Promise<void> {
  const { setStatus } = useAuthStore.getState();
  setStatus("bootstrapping");
  try {
    if (!(await refreshTokenStorage.get())) {
      setStatus("signedOut");
      return;
    }
    if (await refreshSession()) return; // setSession() already marked the user signed in
    // Refresh was rejected (token cleared → signed out) or the server is temporarily unavailable (token kept).
    setStatus((await refreshTokenStorage.get()) ? "bootstrapFailed" : "signedOut");
  } catch (error) {
    if (error instanceof NetworkError) {
      setStatus("bootstrapFailed"); // offline: keep the token and let the user retry
      return;
    }
    throw error;
  }
}

export async function signIn(email: string, password: string): Promise<void> {
  const tokens = unwrap(await api.POST("/v1/auth/login", { body: { email, password } }));
  await tokenStore.setTokens(tokens);
}

export async function register(email: string, password: string, displayName?: string): Promise<void> {
  const tokens = unwrap(
    await api.POST("/v1/auth/register", {
      body: { email, password, display_name: displayName?.trim() ? displayName.trim() : null },
    }),
  );
  await tokenStore.setTokens(tokens);
}

export async function signOut(): Promise<void> {
  const refreshToken = await refreshTokenStorage.get();
  await tokenStore.clearTokens();
  queryClient.clear();
  if (refreshToken) {
    // Best effort: local sign-out must succeed even when offline.
    await api.POST("/v1/auth/logout", { body: { refresh_token: refreshToken } }).catch(() => undefined);
  }
}

export async function deleteAccount(password: string | null): Promise<void> {
  unwrap(await api.DELETE("/v1/users/me", { body: { password } }));
  await tokenStore.clearTokens();
  queryClient.clear();
}
