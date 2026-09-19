import type { NarrationPlayer, PlayerStatus } from "../types";

/** In-memory NarrationPlayer for tests: records calls and lets tests emit playback status. */
export class FakePlayer implements NarrationPlayer {
  loads: string[] = [];
  seeks: number[] = [];
  rates: number[] = [];
  playing = false;
  released = false;
  private listener: ((status: PlayerStatus) => void) | null = null;

  load(url: string): void {
    this.loads.push(url);
  }

  play(): void {
    this.playing = true;
  }

  pause(): void {
    this.playing = false;
  }

  async seekTo(positionMs: number): Promise<void> {
    this.seeks.push(positionMs);
  }

  setRate(rate: number): void {
    this.rates.push(rate);
  }

  onStatus(listener: (status: PlayerStatus) => void): () => void {
    this.listener = listener;
    return () => {
      this.listener = null;
    };
  }

  release(): void {
    this.released = true;
  }

  emit(positionMs: number, extra: Partial<PlayerStatus> = {}): void {
    this.listener?.({
      positionMs,
      durationMs: 0,
      playing: true,
      buffering: false,
      didJustFinish: false,
      error: null,
      ...extra,
    });
  }
}
