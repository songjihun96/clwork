/**
 * How ReadingSession states (docs/realtime.md §3.1) are presented. The state union itself is generated
 * from the backend schema, so a new server state fails type-checking here until it has a label.
 */
import type { ReadingState } from "@audiobook/shared-types";

export type { ReadingState };

export type StatusTone = "active" | "listening" | "thinking" | "neutral" | "error";

export interface StatusDisplay {
  label: string;
  tone: StatusTone;
  /** Whether screen readers should announce the change. */
  announce: boolean;
}

const DISPLAY: Record<ReadingState, StatusDisplay> = {
  IDLE: { label: "대기", tone: "neutral", announce: false },
  PREPARING: { label: "준비 중", tone: "neutral", announce: false },
  READING: { label: "읽는 중", tone: "active", announce: true },
  USER_SPEAKING: { label: "듣는 중", tone: "listening", announce: true },
  AWAITING_FOLLOWUP: { label: "듣는 중", tone: "listening", announce: false },
  PROCESSING_QUESTION: { label: "생각 중", tone: "thinking", announce: true },
  ANSWERING: { label: "답변 중", tone: "active", announce: true },
  RESUMING: { label: "다시 읽는 중", tone: "active", announce: true },
  PAUSED: { label: "일시정지", tone: "neutral", announce: true },
  ERROR: { label: "연결 문제", tone: "error", announce: true },
};

export const READING_STATES = Object.keys(DISPLAY) as ReadingState[];

export function statusDisplay(state: ReadingState): StatusDisplay {
  return DISPLAY[state];
}

/** States in which narration/answer audio is (or is about to be) audible. */
export function isAudible(state: ReadingState): boolean {
  return state === "READING" || state === "ANSWERING" || state === "RESUMING";
}
