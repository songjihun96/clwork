/**
 * Public runtime configuration.
 *
 * EXPO_PUBLIC_* values are inlined into the app bundle and readable by anyone who downloads the app.
 * Only non-secret values belong here. AI provider keys live on the backend only.
 */
const DEFAULT_DEV_API_URL = "http://localhost:8000";

function resolveApiUrl(): string {
  const url = (process.env.EXPO_PUBLIC_API_URL ?? DEFAULT_DEV_API_URL).replace(/\/+$/, "");
  if (!__DEV__ && !url.startsWith("https://")) {
    throw new Error("EXPO_PUBLIC_API_URL must use https:// in release builds");
  }
  return url;
}

export const API_URL = resolveApiUrl();
