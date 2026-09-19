/**
 * Talk-mode connection lifecycle: token → connect → microphone → data messages → reconnect.
 *
 * Three things this owns, and the reasons they are not in the screen:
 *
 * * **a token per connection.** Tokens live ten minutes; reconnecting after a long pause needs a fresh one,
 *   so reconnection goes back to the API rather than reusing a credential that may already be dead.
 * * **superseded attempts are cancelled.** Tapping the mic twice, or backgrounding mid-connect, must not
 *   leave a second room connected — every attempt carries a generation, and a stale one disconnects itself.
 * * **unknown message types are ignored.** The agent may be newer than the installed app; an unrecognised
 *   `type` is counted and dropped, never thrown (see protocol.ts).
 */

import { decode, MessageWriter, ProtocolError, type ControlCommand, type Envelope } from "./protocol";
import type { TalkConnectionState, TalkError, TalkGrant, TalkTransport } from "./types";

export interface TalkControllerOptions {
  transport: TalkTransport;
  /** Fetches a fresh grant from the API (POST /v1/realtime/token). */
  requestGrant: (sessionId: string) => Promise<TalkGrant>;
  onState?: (state: TalkConnectionState) => void;
  onError?: (error: TalkError | null) => void;
  /** Known agent messages, already decoded. */
  onMessage?: (envelope: Envelope) => void;
  now?: () => number;
}

export class TalkController {
  private generation = 0;
  private state: TalkConnectionState = "idle";
  private writer = new MessageWriter();
  private readonly now: () => number;
  /** Diagnostics: messages this app version did not understand, and malformed ones. */
  unknownMessages = 0;
  invalidMessages = 0;

  constructor(private readonly options: TalkControllerOptions) {
    this.now = options.now ?? Date.now;
  }

  get connectionState(): TalkConnectionState {
    return this.state;
  }

  async start(sessionId: string): Promise<void> {
    const generation = ++this.generation;
    this.writer = new MessageWriter(this.now);
    this.setState("requesting");
    this.options.onError?.(null);

    let grant: TalkGrant;
    try {
      grant = await this.options.requestGrant(sessionId);
    } catch (error) {
      if (generation !== this.generation) return;
      this.fail(error);
      return;
    }
    if (generation !== this.generation) return;

    this.setState("connecting");
    try {
      await this.options.transport.connect(grant, {
        onState: (state) => {
          // A late event from a superseded connection must not move the UI.
          if (generation === this.generation) this.setState(state);
        },
        onData: (data) => this.handleData(data, generation),
      });
      if (generation !== this.generation) {
        // Superseded while connecting: drop the room we just joined.
        await this.options.transport.disconnect();
        return;
      }
      await this.options.transport.publishMicrophone();
    } catch (error) {
      if (generation !== this.generation) return;
      this.fail(error);
      await this.safeDisconnect();
    }
  }

  /** Reconnect with a new token — used when the transport reports it gave up. */
  async restart(sessionId: string): Promise<void> {
    await this.stop();
    await this.start(sessionId);
  }

  async stop(): Promise<void> {
    this.generation += 1;
    await this.safeDisconnect();
    this.setState("idle");
  }

  async control(command: ControlCommand, payload: Record<string, unknown> = {}): Promise<void> {
    if (this.state !== "connected") return; // the state machine on the server is the authority anyway
    await this.options.transport.send(this.writer.encode("control", { command, ...payload }));
  }

  async setMicrophoneEnabled(enabled: boolean): Promise<void> {
    await this.options.transport.setMicrophoneEnabled(enabled);
  }

  private handleData(data: Uint8Array | string, generation: number): void {
    if (generation !== this.generation) return;
    let envelope: Envelope;
    try {
      envelope = decode(data);
    } catch (error) {
      this.invalidMessages += 1;
      if (!(error instanceof ProtocolError)) throw error;
      return;
    }
    if (!envelope.known) {
      this.unknownMessages += 1;
      return;
    }
    this.options.onMessage?.(envelope);
  }

  private setState(state: TalkConnectionState): void {
    if (this.state === state) return;
    this.state = state;
    this.options.onState?.(state);
  }

  private fail(error: unknown): void {
    this.setState("error");
    this.options.onError?.(toTalkError(error));
  }

  private async safeDisconnect(): Promise<void> {
    try {
      await this.options.transport.disconnect();
    } catch {
      // Already gone; nothing to clean up.
    }
  }
}

export function toTalkError(error: unknown): TalkError {
  const status = (error as { status?: number } | null)?.status;
  const code = (error as { code?: string } | null)?.code;
  if (status === 503 || code === "realtime_unavailable") {
    return { code: "unavailable", message: "지금은 대화 모드를 쓸 수 없어요." };
  }
  if (status === 403 || status === 404) {
    return { code: "forbidden", message: "이 책은 대화 모드로 들을 수 없어요." };
  }
  if (code === "microphone_denied") {
    return { code: "microphone_denied", message: "마이크 권한이 필요해요." };
  }
  if (code === "network" || status === undefined) {
    return { code: "connect_failed", message: "연결에 실패했어요. 다시 시도해 주세요." };
  }
  return { code: "connect_failed", message: "연결에 실패했어요. 다시 시도해 주세요." };
}
