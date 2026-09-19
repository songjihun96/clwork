import type { SentenceTiming } from "./types";

/** Index of the sentence audible at `positionMs` (the last one once playback passes the end). */
export function sentenceAt(timings: readonly SentenceTiming[], positionMs: number): number {
  if (timings.length === 0) return 0;
  let low = 0;
  let high = timings.length - 1;
  while (low < high) {
    const mid = Math.ceil((low + high) / 2);
    if (timings[mid]!.start_ms <= positionMs) low = mid;
    else high = mid - 1;
  }
  return timings[low]!.sentence_index;
}

export function startOf(timings: readonly SentenceTiming[], sentenceIndex: number): number {
  return timings.find((t) => t.sentence_index === sentenceIndex)?.start_ms ?? 0;
}
