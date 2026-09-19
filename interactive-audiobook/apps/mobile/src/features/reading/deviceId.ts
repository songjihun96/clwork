import * as SecureStore from "expo-secure-store";

const KEY = "device.id";
let cached: string | null = null;

/**
 * Random per-install label sent as X-Device-Id so the server can tell which device last moved the position.
 * Not an authentication factor and not derived from hardware identifiers.
 */
export async function getDeviceId(): Promise<string> {
  if (cached) return cached;
  const stored = await SecureStore.getItemAsync(KEY);
  if (stored) {
    cached = stored;
    return stored;
  }
  const id = `${Date.now().toString(16)}-${Math.random().toString(16).slice(2, 14)}`;
  await SecureStore.setItemAsync(KEY, id);
  cached = id;
  return id;
}
