/**
 * TalkTransport: the only thing Talk-mode logic knows about WebRTC.
 *
 * The LiveKit implementation needs native modules and therefore a development build, so it lives behind
 * this interface: TalkController and its tests run without it (docs/mobile-architecture.md §4.3 applies the
 * same rule to narration playback).
 */

export type TalkConnectionState =
  | "idle"
  | "requesting" // asking the API for a token
  | "connecting"
  | "connected"
  | "reconnecting"
  | "disconnected"
  | "error";

export type TalkErrorCode =
  | "unavailable" // Talk mode not configured on the server (503)
  | "forbidden" // rights lapsed, or not this user's session
  | "microphone_denied"
  | "connect_failed"
  | "network";

export interface TalkError {
  code: TalkErrorCode;
  message: string;
}

/** What POST /v1/realtime/token returns. */
export interface TalkGrant {
  url: string;
  token: string;
  room: string;
  identity: string;
  expiresAt: number; // epoch ms
  agentName: string;
  protocol: string;
}

export interface TransportEvents {
  /** Connection lifecycle as reported by the SDK. */
  onState: (state: Exclude<TalkConnectionState, "idle" | "requesting">) => void;
  /** Raw data-channel payloads; decoding and unknown-type handling belong to the controller. */
  onData: (data: Uint8Array | string) => void;
}

export interface TalkTransport {
  connect(grant: TalkGrant, events: TransportEvents): Promise<void>;
  /** Publishes the microphone. Rejects when the OS permission is refused. */
  publishMicrophone(): Promise<void>;
  setMicrophoneEnabled(enabled: boolean): Promise<void>;
  send(payload: string): Promise<void>;
  disconnect(): Promise<void>;
}
