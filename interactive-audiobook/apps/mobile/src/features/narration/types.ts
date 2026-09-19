/**
 * NarrationPlayer: the only thing narration logic knows about audio playback.
 * Implemented with expo-audio today (docs/mobile-architecture.md §4.3); a different native player can be
 * swapped in without touching NarrationController or the Reader.
 */

export interface PlayerStatus {
  positionMs: number;
  durationMs: number;
  playing: boolean;
  buffering: boolean;
  didJustFinish: boolean;
  error: string | null;
}

export interface NarrationPlayer {
  load(url: string): void;
  play(): void;
  pause(): void;
  seekTo(positionMs: number): Promise<void>;
  setRate(rate: number): void;
  onStatus(listener: (status: PlayerStatus) => void): () => void;
  release(): void;
}

export interface SentenceTiming {
  sentence_index: number;
  start_ms: number;
  end_ms: number;
}

export type ParagraphAudioStatus = "ready" | "pending" | "unavailable";

export interface ParagraphAudio {
  paragraphId: string;
  status: ParagraphAudioStatus;
  url?: string;
  expiresAt?: number; // epoch ms
  durationMs?: number;
  timings?: SentenceTiming[];
}

/** Fetches audio availability for a paragraph and a small lookahead. */
export type AudioSource = (paragraphIds: string[]) => Promise<ParagraphAudio[]>;
