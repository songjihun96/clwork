import { unwrap } from "@audiobook/api-client";

import { api } from "../../services/api";
import type { AudioSource, ParagraphAudio } from "./types";

export function sessionAudioSource(sessionId: string): AudioSource {
  return async (paragraphIds): Promise<ParagraphAudio[]> => {
    const response = unwrap(
      await api.POST("/v1/reading/sessions/{session_id}/audio", {
        params: { path: { session_id: sessionId } },
        body: { paragraph_ids: paragraphIds },
      }),
    );
    return response.items.map((item) => ({
      paragraphId: item.paragraph_id,
      status: item.status,
      url: item.audio?.url,
      expiresAt: item.audio ? Date.parse(item.audio.expires_at) : undefined,
      durationMs: item.audio?.duration_ms,
      timings: item.audio?.sentence_timings,
    }));
  };
}
