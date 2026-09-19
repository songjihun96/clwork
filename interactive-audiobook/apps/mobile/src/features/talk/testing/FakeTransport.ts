/** In-memory TalkTransport: lets TalkController be tested without native modules. */

import type { TalkGrant, TalkTransport, TransportEvents } from "../types";

export class FakeTransport implements TalkTransport {
  grants: TalkGrant[] = [];
  sent: string[] = [];
  connects = 0;
  disconnects = 0;
  micPublished = 0;
  micEnabled: boolean | null = null;
  failPublishWith: Error | null = null;
  failConnectWith: Error | null = null;
  /** Set to hold connect() open, so a test can supersede an attempt mid-connect. */
  connectGate: Promise<void> | null = null;
  private events: TransportEvents | null = null;

  async connect(grant: TalkGrant, events: TransportEvents): Promise<void> {
    this.connects += 1;
    this.grants.push(grant);
    if (this.connectGate) await this.connectGate;
    this.events = events;
    if (this.failConnectWith) throw this.failConnectWith;
    events.onState("connected");
  }

  async publishMicrophone(): Promise<void> {
    if (this.failPublishWith) throw this.failPublishWith;
    this.micPublished += 1;
  }

  async setMicrophoneEnabled(enabled: boolean): Promise<void> {
    this.micEnabled = enabled;
  }

  async send(payload: string): Promise<void> {
    this.sent.push(payload);
  }

  async disconnect(): Promise<void> {
    this.disconnects += 1;
    this.events = null;
  }

  /** Test hooks: drive what the SDK would report. */
  emitState(state: Parameters<TransportEvents["onState"]>[0]): void {
    this.events?.onState(state);
  }

  emitData(data: string | Uint8Array): void {
    this.events?.onData(data);
  }
}
