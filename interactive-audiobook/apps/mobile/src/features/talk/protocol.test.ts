/** The app's half of story.v1 must agree with the agent's, including what it ignores. */

import { decode, MAX_MESSAGE_BYTES, MessageWriter, PROTOCOL_VERSION, ProtocolError } from "./protocol";

describe("story.v1", () => {
  it("numbers messages and stamps time", () => {
    const writer = new MessageWriter(() => 1_700_000_000_500);

    const first = decode(writer.encode("control", { command: "PAUSE" }));
    const second = decode(writer.encode("settings", { speed: 1.5 }));

    expect([first.seq, second.seq]).toEqual([1, 2]);
    expect(first.ts).toBe(1_700_000_000_500);
    expect(first.payload).toEqual({ command: "PAUSE" });
    expect(second.payload.speed).toBe(1.5);
  });

  it("marks a type this app version does not know, instead of failing", () => {
    const envelope = decode(
      JSON.stringify({ v: PROTOCOL_VERSION, type: "scene.transition.v2", seq: 4, ts: 1, extra: true }),
    );

    expect(envelope.known).toBe(false);
    expect(envelope.type).toBe("scene.transition.v2");
    expect(envelope.payload.extra).toBe(true);
  });

  it("keeps unknown fields on a known type", () => {
    const envelope = decode(
      JSON.stringify({ v: PROTOCOL_VERSION, type: "state", seq: 1, ts: 1, state: "READING", mood: "x" }),
    );

    expect(envelope.known).toBe(true);
    expect(envelope.payload).toEqual({ state: "READING", mood: "x" });
  });

  it.each([
    ["not json", "x"],
    ["an array", JSON.stringify([1, 2])],
    ["no version", JSON.stringify({ type: "state" })],
    ["a future version", JSON.stringify({ v: 99, type: "state" })],
    ["no type", JSON.stringify({ v: PROTOCOL_VERSION, seq: 1 })],
    ["an empty type", JSON.stringify({ v: PROTOCOL_VERSION, type: "" })],
  ])("rejects %s", (_label, raw) => {
    expect(() => decode(raw)).toThrow(ProtocolError);
  });

  it("decodes binary data channel payloads", () => {
    const bytes = new TextEncoder().encode(
      JSON.stringify({ v: PROTOCOL_VERSION, type: "answer.delta", seq: 2, ts: 3, text: "다시 읽어줄게" }),
    );

    expect(decode(bytes).payload.text).toBe("다시 읽어줄게");
  });

  it("refuses to send an oversized message", () => {
    expect(() => new MessageWriter().encode("control", { text: "가".repeat(MAX_MESSAGE_BYTES) })).toThrow(
      ProtocolError,
    );
  });
});
