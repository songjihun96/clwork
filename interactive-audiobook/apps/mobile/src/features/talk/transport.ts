import { NativeModules } from "react-native";

import type { TalkTransport } from "./types";

/**
 * Talk mode needs WebRTC native modules, which exist only in a development build — not in Expo Go and not
 * in Jest. Availability is decided by looking for the native module rather than by catching an error later,
 * so the screen can say "development build required" instead of failing when the user taps the microphone.
 */
export function isTalkAvailable(): boolean {
  return NativeModules.WebRTCModule != null;
}

export function createTalkTransport(): TalkTransport | null {
  if (!isTalkAvailable()) return null;
  // Required lazily: importing it at module scope would pull the native module into every bundle that
  // merely renders the reader.
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { LiveKitTransport } = require("./liveKitTransport") as typeof import("./liveKitTransport");
  return new LiveKitTransport();
}
