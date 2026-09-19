import * as SecureStore from "expo-secure-store";

const REFRESH_TOKEN_KEY = "auth.refresh_token";

/**
 * AFTER_FIRST_UNLOCK: token refresh must work while the phone is locked during background narration.
 * THIS_DEVICE_ONLY: never migrate the token to another device through an encrypted backup.
 */
const OPTIONS: SecureStore.SecureStoreOptions = {
  keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY,
};

export const refreshTokenStorage = {
  get: () => SecureStore.getItemAsync(REFRESH_TOKEN_KEY, OPTIONS),
  set: (token: string) => SecureStore.setItemAsync(REFRESH_TOKEN_KEY, token, OPTIONS),
  clear: () => SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY, OPTIONS),
};
