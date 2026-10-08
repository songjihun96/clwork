/**
 * Plays one paragraph at a time and reports the audible sentence.
 *
 * The controller owns no book structure: the Reader tells it which paragraph to play (with a lookahead
 * so the next paragraphs start rendering early) and decides what comes after a paragraph ends — that may
 * require loading the next chapter. Pure TypeScript, testable with a fake player.
 */
import { sentenceAt, startOf } from "./timeline";
import type { AudioSource, NarrationPlayer, ParagraphAudio, PlayerStatus } from "./types";

export type NarrationState = "idle" | "loading" | "playing" | "paused" | "error";

export interface NarrationCallbacks {
  onSentence: (paragraphId: string, sentenceIndex: number) => void;
  onParagraphEnd: (paragraphId: string) => void;
  onState: (state: NarrationState, error?: NarrationError) => void;
}

export type NarrationErrorCode = "audio_unavailable" | "render_timeout" | "playback_failed" | "network";

export class NarrationError extends Error {
  constructor(readonly code: NarrationErrorCode, message: string) {
    super(message);
    this.name = "NarrationError";
  }
}

export interface NarrationOptions {
  pollIntervalMs?: number;
  maxWaitMs?: number;
  /** Refresh a signed URL this long before it expires. */
  urlRefreshMarginMs?: number;
  sleep?: (ms: number) => Promise<void>;
  now?: () => number;
}

interface Loaded {
  paragraphId: string;
  audio: ParagraphAudio;
}

export class NarrationController {
  private loaded: Loaded | null = null;
  private lastSentence = -1;
  private state: NarrationState = "idle";
  private generation = 0; // invalidates in-flight starts when the user moves on
  private rate = 1;
  private readonly unsubscribe: () => void;
  private readonly pollIntervalMs: number;
  private readonly maxWaitMs: number;
  private readonly urlRefreshMarginMs: number;
  private readonly sleep: (ms: number) => Promise<void>;
  private readonly now: () => number;

  constructor(
    private readonly player: NarrationPlayer,
    private readonly source: AudioSource,
    private readonly callbacks: NarrationCallbacks,
    options: NarrationOptions = {},
  ) {
    this.pollIntervalMs = options.pollIntervalMs ?? 1000;
    this.maxWaitMs = options.maxWaitMs ?? 30_000;
    this.urlRefreshMarginMs = options.urlRefreshMarginMs ?? 60_000;
    this.sleep = options.sleep ?? ((ms) => new Promise((resolve) => setTimeout(resolve, ms)));
    this.now = options.now ?? Date.now;
    this.unsubscribe = player.onStatus((status) => this.handleStatus(status));
  }

  get currentState(): NarrationState {
    return this.state;
  }

  get currentParagraphId(): string | null {
    return this.loaded?.paragraphId ?? null;
  }

  /** Start (or restart) playback at a sentence. `lookahead` paragraphs are requested so they render early. */
  async start(paragraphId: string, sentenceIndex: number, lookahead: string[] = []): Promise<void> {
    const generation = ++this.generation;
    const reusable =
      this.loaded?.paragraphId === paragraphId && !this.urlExpiring(this.loaded.audio) ? this.loaded : null;

    if (reusable) {
      await this.seekWithin(reusable, sentenceIndex);
      this.player.play();
      this.setState("playing");
      return;
    }

    this.player.pause();
    this.setState("loading");
    let audio: ParagraphAudio;
    try {
      audio = await this.waitUntilReady(paragraphId, lookahead, generation);
    } catch (error) {
      if (generation !== this.generation) return;
      const failure =
        error instanceof NarrationError ? error : new NarrationError("network", "Could not reach the audio service");
      this.setState("error", failure);
      return;
    }
    if (generation !== this.generation) return; // superseded while waiting

    this.loaded = { paragraphId, audio };
    this.player.load(audio.url!);
    this.player.setRate(this.rate);
    await this.seekWithin(this.loaded, sentenceIndex);
    if (generation !== this.generation) return;
    this.player.play();
    this.setState("playing");
  }

  pause(): void {
    this.generation++; // cancels a pending start
    this.player.pause();
    if (this.state !== "idle") this.setState("paused");
  }

  setRate(rate: number): void {
    this.rate = rate;
    this.player.setRate(rate);
  }

  dispose(): void {
    this.generation++;
    this.unsubscribe();
    this.player.release();
    this.loaded = null;
    this.state = "idle";
  }

  // ------------------------------------------------------------------ internals

  private async seekWithin(loaded: Loaded, sentenceIndex: number): Promise<void> {
    this.lastSentence = sentenceIndex;
    await this.player.seekTo(startOf(loaded.audio.timings ?? [], sentenceIndex));
  }

  private urlExpiring(audio: ParagraphAudio): boolean {
    return audio.expiresAt !== undefined && audio.expiresAt - this.now() < this.urlRefreshMarginMs;
  }

  private async waitUntilReady(paragraphId: string, lookahead: string[], generation: number): Promise<ParagraphAudio> {
    const deadline = this.now() + this.maxWaitMs;
    const ids = [paragraphId, ...lookahead.filter((id) => id !== paragraphId)].slice(0, 5);
    for (;;) {
      const items = await this.source(ids);
      const item = items.find((i) => i.paragraphId === paragraphId);
      if (!item || item.status === "unavailable") {
        throw new NarrationError("audio_unavailable", "Audio is not available for this paragraph");
      }
      if (item.status === "ready" && item.url) return item;
      if (generation !== this.generation) throw new NarrationError("network", "superseded");
      if (this.now() >= deadline) throw new NarrationError("render_timeout", "Audio took too long to prepare");
      await this.sleep(this.pollIntervalMs);
    }
  }

  private handleStatus(status: PlayerStatus): void {
    const loaded = this.loaded;
    if (!loaded || this.state === "loading") return;
    if (status.error) {
      this.setState("error", new NarrationError("playback_failed", status.error));
      return;
    }
    const sentence = sentenceAt(loaded.audio.timings ?? [], status.positionMs);
    if (sentence !== this.lastSentence) {
      this.lastSentence = sentence;
      this.callbacks.onSentence(loaded.paragraphId, sentence);
    }
    if (status.didJustFinish) {
      this.callbacks.onParagraphEnd(loaded.paragraphId);
    }
  }

  private setState(state: NarrationState, error?: NarrationError): void {
    this.state = state;
    this.callbacks.onState(state, error);
  }
}
