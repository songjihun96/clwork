import { createApiClient, type TokenStore } from "@audiobook/api-client";

import { useAuthStore } from "../features/auth/authStore";
import { refreshTokenStorage } from "../features/auth/tokenStorage";
import { API_URL } from "../lib/config";
import { queryClient } from "../lib/queryClient";

const tokenStore: TokenStore = {
  getAccessToken: () => useAuthStore.getState().accessToken,
  getRefreshToken: () => refreshTokenStorage.get(),
  setTokens: async (tokens) => {
    await refreshTokenStorage.set(tokens.refresh_token);
    useAuthStore.getState().setSession(tokens);
  },
  clearTokens: async () => {
    await refreshTokenStorage.clear();
    useAuthStore.getState().clearSession();
  },
};

const apiClient = createApiClient({
  baseUrl: API_URL,
  tokenStore,
  onSessionExpired: () => queryClient.clear(),
});

export const api = apiClient.client;
export const refreshSession = apiClient.refreshTokens;
export { tokenStore };
