import { ApiError, unwrap } from "@audiobook/api-client";
import type { PlaybackAction, ReadingSession } from "@audiobook/shared-types";
import { useQuery } from "@tanstack/react-query";

import { api } from "../../services/api";
import { getDeviceId } from "./deviceId";
import type { PositionTarget, SaveOutcome } from "./positionSaver";

export const sessionKeys = {
  active: ["reading-sessions"] as const,
  forBook: (bookId: string) => ["reading-sessions", "book", bookId] as const,
};

/** Get-or-create the active session for a book (idempotent on the server). */
export async function openSession(bookId: string): Promise<ReadingSession> {
  return unwrap(await api.POST("/v1/reading/sessions", { body: { book_id: bookId } }));
}

export async function fetchSession(sessionId: string): Promise<ReadingSession> {
  return unwrap(await api.GET("/v1/reading/sessions/{session_id}", { params: { path: { session_id: sessionId } } }));
}

export async function fetchActiveSessions(): Promise<ReadingSession[]> {
  return unwrap(await api.GET("/v1/reading/sessions")).items;
}

export async function savePosition(
  sessionId: string,
  target: PositionTarget,
  expectedVersion: number,
): Promise<SaveOutcome> {
  try {
    const session = unwrap(
      await api.PATCH("/v1/reading/sessions/{session_id}", {
        params: { path: { session_id: sessionId }, header: { "x-device-id": await getDeviceId() } },
        body: {
          position: {
            paragraph_id: target.paragraphId,
            sentence_index: target.sentenceIndex,
            expected_version: expectedVersion,
          },
        },
      }),
    );
    return { type: "saved", version: session.position.position_version };
  } catch (error) {
    if (error instanceof ApiError && error.code === "position_conflict") return { type: "conflict" };
    return { type: "failed", error };
  }
}

export async function sendPlayback(sessionId: string, action: PlaybackAction): Promise<ReadingSession> {
  return unwrap(
    await api.POST("/v1/reading/sessions/{session_id}/playback", {
      params: { path: { session_id: sessionId } },
      body: { action },
    }),
  );
}

export function useActiveSessions() {
  return useQuery({ queryKey: sessionKeys.active, queryFn: fetchActiveSessions });
}
