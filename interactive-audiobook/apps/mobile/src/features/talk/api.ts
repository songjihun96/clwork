import { unwrap } from "@audiobook/api-client";

import { api } from "../../services/api";
import type { TalkGrant } from "./types";

/**
 * Asks the server for a connection. The app never holds LiveKit credentials of its own: the token is
 * scoped to one room, lasts ten minutes, and is requested again for every connection.
 */
export async function requestTalkGrant(sessionId: string): Promise<TalkGrant> {
  const response = unwrap(
    await api.POST("/v1/realtime/token", { body: { session_id: sessionId } }),
  );
  return {
    url: response.url,
    token: response.token,
    room: response.room,
    identity: response.identity,
    expiresAt: Date.parse(response.expires_at),
    agentName: response.agent_name,
    protocol: response.protocol,
  };
}
