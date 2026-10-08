import { NarrationController, type NarrationState } from "./NarrationController";
import { sentenceAt, startOf } from "./timeline";
import { FakePlayer } from "./testing/FakePlayer";
import type { AudioSource, ParagraphAudio } from "./types";

const TIMINGS = [
  { sentence_index: 0, start_ms: 0, end_ms: 1000 },
  { sentence_index: 1, start_ms: 1000, end_ms: 2500 },
  { sentence_index: 2, start_ms: 2500, end_ms: 4000 },
];

const ready = (paragraphId: string, url = `https://cdn/${paragraphId}.wav`, expiresAt = 10_000_000): ParagraphAudio => ({
  paragraphId,
  status: "ready",
  url,
  expiresAt,
  durationMs: 4000,
  timings: TIMINGS,
});

function setup(source: AudioSource, now = () => 0) {
  const player = new FakePlayer();
  const sentences: [string, number][] = [];
  const ends: string[] = [];
  const states: NarrationState[] = [];
  const errors: string[] = [];
  const controller = new NarrationController(
    player,
    source,
    {
      onSentence: (p, s) => sentences.push([p, s]),
      onParagraphEnd: (p) => ends.push(p),
      onState: (state, error) => {
        states.push(state);
        if (error) errors.push(error.code);
      },
    },
    { pollIntervalMs: 10, maxWaitMs: 50, sleep: async () => undefined, now },
  );
  return { player, controller, sentences, ends, states, errors };
}

describe("timeline", () => {
  it("finds the audible sentence and its start", () => {
    expect(sentenceAt(TIMINGS, 0)).toBe(0);
    expect(sentenceAt(TIMINGS, 999)).toBe(0);
    expect(sentenceAt(TIMINGS, 1000)).toBe(1);
    expect(sentenceAt(TIMINGS, 9999)).toBe(2);
    expect(sentenceAt([], 500)).toBe(0);
    expect(startOf(TIMINGS, 2)).toBe(2500);
  });
});

describe("NarrationController", () => {
  it("waits for rendering, then plays from the requested sentence", async () => {
    let calls = 0;
    const requested: string[][] = [];
    const source: AudioSource = async (ids) => {
      requested.push(ids);
      calls += 1;
      return calls < 3 ? [{ paragraphId: "p1", status: "pending" }] : [ready("p1")];
    };
    const { player, controller, states } = setup(source);

    await controller.start("p1", 1, ["p2", "p3"]);

    expect(requested[0]).toEqual(["p1", "p2", "p3"]);
    expect(calls).toBe(3);
    expect(player.loads).toEqual(["https://cdn/p1.wav"]);
    expect(player.seeks).toEqual([1000]);
    expect(player.playing).toBe(true);
    expect(states).toEqual(["loading", "playing"]);
  });

  it("reports sentence changes as playback advances and the paragraph end", async () => {
    const { player, controller, sentences, ends } = setup(async () => [ready("p1")]);
    await controller.start("p1", 0);

    player.emit(200);
    player.emit(1100);
    player.emit(1200);
    player.emit(2600);
    player.emit(4000, { didJustFinish: true, playing: false });

    expect(sentences).toEqual([
      ["p1", 1],
      ["p1", 2],
    ]);
    expect(ends).toEqual(["p1"]);
  });

  it("seeks within the loaded paragraph without reloading", async () => {
    const source = jest.fn(async () => [ready("p1")]);
    const { player, controller } = setup(source);
    await controller.start("p1", 0);
    await controller.start("p1", 2);
    expect(player.loads).toHaveLength(1);
    expect(player.seeks).toEqual([0, 2500]);
    expect(source).toHaveBeenCalledTimes(1);
  });

  it("refreshes the signed URL when it is about to expire", async () => {
    let now = 0;
    let version = 0;
    const source: AudioSource = async () => [ready("p1", `https://cdn/p1.wav?v=${++version}`, 100_000)];
    const { player, controller } = setup(source, () => now);
    await controller.start("p1", 0);
    now = 90_000; // 10 s left, inside the 60 s refresh margin
    await controller.start("p1", 1);
    expect(player.loads).toEqual(["https://cdn/p1.wav?v=1", "https://cdn/p1.wav?v=2"]);
  });

  it("gives up with a clear error when audio never becomes ready or is unavailable", async () => {
    let now = 0;
    const slow = setup(
      async () => {
        now += 20;
        return [{ paragraphId: "p1", status: "pending" }];
      },
      () => now,
    );
    await slow.controller.start("p1", 0);
    expect(slow.errors).toEqual(["render_timeout"]);
    expect(slow.player.playing).toBe(false);

    const missing = setup(async () => [{ paragraphId: "p1", status: "unavailable" }]);
    await missing.controller.start("p1", 0);
    expect(missing.errors).toEqual(["audio_unavailable"]);

    const offline = setup(async () => {
      throw new TypeError("Network request failed");
    });
    await offline.controller.start("p1", 0);
    expect(offline.errors).toEqual(["network"]);
  });

  it("a newer start or a pause cancels a start that is still waiting", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => (release = resolve));
    const source: AudioSource = async (ids) => {
      if (ids[0] === "p1") await gate;
      return [ready(ids[0]!)];
    };
    const { player, controller } = setup(source);

    const first = controller.start("p1", 0);
    await controller.start("p2", 0); // user skipped ahead
    release();
    await first;
    expect(player.loads).toEqual(["https://cdn/p2.wav"]);
    expect(controller.currentParagraphId).toBe("p2");

    controller.pause();
    expect(player.playing).toBe(false);
    expect(controller.currentState).toBe("paused");
  });

  it("applies playback speed to newly loaded audio and releases the player", async () => {
    const { player, controller } = setup(async (ids) => [ready(ids[0]!)]);
    controller.setRate(1.5);
    await controller.start("p1", 0);
    expect(player.rates).toEqual([1.5, 1.5]);
    controller.dispose();
    expect(player.released).toBe(true);
    player.emit(1500); // ignored after dispose
  });

  it("surfaces player errors", async () => {
    const { player, controller, errors } = setup(async () => [ready("p1")]);
    await controller.start("p1", 0);
    player.emit(0, { error: "decoder failure" });
    expect(errors).toEqual(["playback_failed"]);
  });
});
