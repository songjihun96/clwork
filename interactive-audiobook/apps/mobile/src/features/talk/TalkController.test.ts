/** Connection lifecycle: a fresh token per connection, superseded attempts, unknown messages, failures. */

import { TalkController } from "./TalkController";
import { FakeTransport } from "./testing/FakeTransport";
import type { TalkConnectionState, TalkError, TalkGrant } from "./types";

const SESSION = "11111111-1111-4111-8111-111111111111";

function grant(overrides: Partial<TalkGrant> = {}): TalkGrant {
  return {
    url: "ws://127.0.0.1:7880",
    token: "token-1",
    room: `rs_${SESSION}`,
    identity: "u_2",
    expiresAt: Date.now() + 600_000,
    agentName: "story-agent",
    protocol: "story.v1",
    ...overrides,
  };
}

const agentMessage = (type: string, payload: Record<string, unknown> = {}) =>
  JSON.stringify({ v: 1, type, seq: 1, ts: 1, ...payload });

function harness(options: { requestGrant?: () => Promise<TalkGrant> } = {}) {
  const transport = new FakeTransport();
  const states: TalkConnectionState[] = [];
  const errors: (TalkError | null)[] = [];
  const messages: string[] = [];
  let tokens = 0;
  const controller = new TalkController({
    transport,
    requestGrant: async () => {
      tokens += 1;
      return options.requestGrant ? options.requestGrant() : grant({ token: `token-${tokens}` });
    },
    onState: (state) => states.push(state),
    onError: (error) => errors.push(error),
    onMessage: (envelope) => messages.push(envelope.type),
  });
  return { controller, transport, states, errors, messages };
}

describe("TalkController", () => {
  it("requests a token, connects and publishes the microphone", async () => {
    const h = harness();

    await h.controller.start(SESSION);

    expect(h.states).toEqual(["requesting", "connecting", "connected"]);
    expect(h.transport.connects).toBe(1);
    expect(h.transport.micPublished).toBe(1);
    expect(h.transport.grants[0]?.room).toBe(`rs_${SESSION}`);
  });

  it("asks for a new token on every connection, because tokens expire", async () => {
    const h = harness();

    await h.controller.start(SESSION);
    await h.controller.restart(SESSION);

    expect(h.transport.grants.map((item) => item.token)).toEqual(["token-1", "token-2"]);
    expect(h.transport.disconnects).toBeGreaterThanOrEqual(1);
  });

  it("reflects transport reconnection in the UI state", async () => {
    const h = harness();
    await h.controller.start(SESSION);

    h.transport.emitState("reconnecting");
    h.transport.emitState("connected");

    expect(h.states.slice(-2)).toEqual(["reconnecting", "connected"]);
  });

  it("ignores a message type it does not know and counts it", async () => {
    const h = harness();
    await h.controller.start(SESSION);

    h.transport.emitData(agentMessage("state", { state: "READING" }));
    h.transport.emitData(agentMessage("scene.transition.v2"));
    h.transport.emitData("not json");

    expect(h.messages).toEqual(["state"]);
    expect(h.controller.unknownMessages).toBe(1);
    expect(h.controller.invalidMessages).toBe(1);
  });

  it("a superseded attempt never opens a second connection", async () => {
    const h = harness();

    // The user taps the microphone twice before the first attempt finishes.
    await Promise.all([h.controller.start(SESSION), h.controller.start(SESSION)]);

    expect(h.transport.connects).toBe(1); // the stale attempt gave up before dialling
    expect(h.controller.connectionState).toBe("connected");
  });

  it("drops the room when an attempt finishes connecting after being superseded", async () => {
    const h = harness();
    let open = () => {};
    h.transport.connectGate = new Promise<void>((resolve) => {
      open = resolve;
    });

    const stale = h.controller.start(SESSION);
    await Promise.resolve(); // let the first attempt reach connect()
    const current = h.controller.start(SESSION);
    open();
    await Promise.all([stale, current]);

    expect(h.transport.connects).toBe(2);
    // Exactly one of them is still in the room, and it is the newest.
    expect(h.transport.disconnects).toBe(1);
    expect(h.controller.connectionState).toBe("connected");
  });

  it("surfaces a server that has Talk mode switched off", async () => {
    const h = harness({
      requestGrant: async () => {
        throw Object.assign(new Error("unavailable"), { status: 503, code: "realtime_unavailable" });
      },
    });

    await h.controller.start(SESSION);

    expect(h.controller.connectionState).toBe("error");
    expect(h.errors.at(-1)).toEqual({ code: "unavailable", message: "지금은 대화 모드를 쓸 수 없어요." });
    expect(h.transport.connects).toBe(0);
  });

  it("disconnects when the microphone is refused", async () => {
    const h = harness();
    h.transport.failPublishWith = Object.assign(new Error("denied"), { code: "microphone_denied" });

    await h.controller.start(SESSION);

    expect(h.errors.at(-1)?.code).toBe("microphone_denied");
    expect(h.transport.disconnects).toBe(1);
  });

  it("sends control commands as story.v1 envelopes, and only while connected", async () => {
    const h = harness();

    await h.controller.control("PAUSE");
    expect(h.transport.sent).toEqual([]); // not connected: the server state machine is the authority

    await h.controller.start(SESSION);
    await h.controller.control("SEEK_SENTENCE", { delta: -1 });

    expect(JSON.parse(h.transport.sent[0]!)).toMatchObject({
      v: 1,
      type: "control",
      command: "SEEK_SENTENCE",
      delta: -1,
      seq: 1,
    });
  });

  it("stops cleanly and ignores late transport events", async () => {
    const h = harness();
    await h.controller.start(SESSION);

    await h.controller.stop();
    h.transport.emitState("connected");

    expect(h.controller.connectionState).toBe("idle");
  });
});
