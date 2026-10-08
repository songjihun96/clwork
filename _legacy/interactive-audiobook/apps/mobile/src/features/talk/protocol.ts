/**
 * story.v1 data-channel contract — the app's half of packages/story-core/story_core/realtime/protocol.py.
 *
 * The two ends ship on different schedules (app review vs. a server deploy), so an old app and a new agent
 * talk to each other for weeks. Hence: an unknown `type` is ignored rather than treated as an error, and
 * unknown fields are kept. Only a broken envelope is a protocol violation.
 */

export const PROTOCOL = "story.v1";
export const PROTOCOL_VERSION = 1;
/** Matches MAX_MESSAGE_BYTES on the agent side. */
export const MAX_MESSAGE_BYTES = 15_000;

/** Agent → app. */
export const AGENT_MESSAGES = [
  "state",
  "sentence",
  "scene",
  "transcript.partial",
  "transcript.final",
  "answer.delta",
  "answer.done",
  "error",
] as const;

/** App → agent. */
export const CLIENT_MESSAGES = ["control", "settings", "client.playout"] as const;

export type AgentMessageType = (typeof AGENT_MESSAGES)[number];
export type ClientMessageType = (typeof CLIENT_MESSAGES)[number];

export type ControlCommand = "PAUSE" | "RESUME" | "ASK" | "SEEK_SENTENCE" | "SEEK_PARAGRAPH" | "STOP";

const KNOWN = new Set<string>([...AGENT_MESSAGES, ...CLIENT_MESSAGES]);

export interface Envelope {
  type: string;
  seq: number;
  ts: number;
  payload: Record<string, unknown>;
  /** False for a message type this app version does not know: callers ignore it. */
  known: boolean;
}

export class ProtocolError extends Error {}

/** Numbers outgoing messages for one connection, so the agent can spot gaps and reordering. */
export class MessageWriter {
  private seq = 0;

  constructor(private readonly now: () => number = Date.now) {}

  encode(type: ClientMessageType | string, payload: Record<string, unknown> = {}): string {
    this.seq += 1;
    const body = { v: PROTOCOL_VERSION, type, seq: this.seq, ts: this.now(), ...payload };
    const text = JSON.stringify(body);
    if (new TextEncoder().encode(text).length > MAX_MESSAGE_BYTES) {
      throw new ProtocolError(`message too large: ${type}`);
    }
    return text;
  }
}

export function decode(data: string | Uint8Array): Envelope {
  const text = typeof data === "string" ? data : new TextDecoder().decode(data);
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new ProtocolError("message is not JSON");
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new ProtocolError("message is not an object");
  }
  const record = parsed as Record<string, unknown>;
  if (record.v !== PROTOCOL_VERSION) {
    throw new ProtocolError(`unsupported protocol version ${String(record.v)}`);
  }
  const type = record.type;
  if (typeof type !== "string" || type.length === 0) {
    throw new ProtocolError("message has no type");
  }
  const payload: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(record)) {
    if (key !== "v" && key !== "type" && key !== "seq" && key !== "ts") payload[key] = value;
  }
  return {
    type,
    seq: typeof record.seq === "number" ? record.seq : 0,
    ts: typeof record.ts === "number" ? record.ts : 0,
    payload,
    known: KNOWN.has(type),
  };
}
