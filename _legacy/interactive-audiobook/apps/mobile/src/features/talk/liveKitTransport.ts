/**
 * TalkTransport on LiveKit (@livekit/react-native).
 *
 * Needs native modules, so it only runs in a development build — never in Expo Go, and never in Jest. That
 * is why every other Talk-mode file depends on the `TalkTransport` interface instead of this one: the
 * controller's logic (tokens, supersede, unknown messages) is tested without a device.
 *
 * Two settings here are not defaults and matter for barge-in:
 * * the microphone is published with **echo cancellation, noise suppression and auto gain** on, because the
 *   narration coming out of the speaker must not be heard as the user speaking (docs/realtime.md §4.3);
 * * `adaptiveStream` stays off — there is no video, and it only adds work.
 */

import { AudioSession, registerGlobals } from "@livekit/react-native";
import {
  ConnectionState,
  DisconnectReason,
  RoomEvent,
  Room,
  type RemoteParticipant,
  type RoomOptions,
} from "livekit-client";

import type { TalkGrant, TalkTransport, TransportEvents } from "./types";

// WebRTC globals must exist before a Room is constructed.
let globalsRegistered = false;

function ensureGlobals(): void {
  if (!globalsRegistered) {
    registerGlobals();
    globalsRegistered = true;
  }
}

const ROOM_OPTIONS: RoomOptions = {
  adaptiveStream: false,
  dynacast: false,
  audioCaptureDefaults: {
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true,
  },
  publishDefaults: {
    // Speech, not music: Opus DTX saves upstream bandwidth during the pauses that make up most of a session.
    dtx: true,
    red: true,
  },
};

export class LiveKitTransport implements TalkTransport {
  private room: Room | null = null;
  private events: TransportEvents | null = null;

  async connect(grant: TalkGrant, events: TransportEvents): Promise<void> {
    ensureGlobals();
    // Routes audio to the speaker and takes the call audio session (iOS category, Android mode).
    await AudioSession.startAudioSession();

    const room = new Room(ROOM_OPTIONS);
    this.room = room;
    this.events = events;

    room
      .on(RoomEvent.ConnectionStateChanged, (state: ConnectionState) => {
        if (state === ConnectionState.Connected) events.onState("connected");
        else if (state === ConnectionState.Reconnecting) events.onState("reconnecting");
        else if (state === ConnectionState.Disconnected) events.onState("disconnected");
      })
      .on(RoomEvent.Disconnected, (reason?: DisconnectReason) => {
        // A token that expired mid-session, or the agent ending the room: the controller asks the API for
        // a new token rather than retrying a dead credential.
        events.onState(reason === DisconnectReason.CLIENT_INITIATED ? "disconnected" : "error");
      })
      .on(RoomEvent.DataReceived, (payload: Uint8Array, _participant?: RemoteParticipant) => {
        events.onData(payload);
      });

    await room.connect(grant.url, grant.token, { autoSubscribe: true });
  }

  async publishMicrophone(): Promise<void> {
    const room = this.requireRoom();
    try {
      await room.localParticipant.setMicrophoneEnabled(true);
    } catch (error) {
      // The OS permission dialog was refused (or the mic is held by another app).
      throw Object.assign(new Error("microphone unavailable"), { code: "microphone_denied", cause: error });
    }
  }

  async setMicrophoneEnabled(enabled: boolean): Promise<void> {
    await this.requireRoom().localParticipant.setMicrophoneEnabled(enabled);
  }

  async send(payload: string): Promise<void> {
    await this.requireRoom().localParticipant.publishData(new TextEncoder().encode(payload), {
      reliable: true,
    });
  }

  async disconnect(): Promise<void> {
    const room = this.room;
    this.room = null;
    this.events = null;
    if (room) await room.disconnect();
    await AudioSession.stopAudioSession();
  }

  private requireRoom(): Room {
    if (!this.room) throw new Error("Talk transport is not connected");
    return this.room;
  }
}
