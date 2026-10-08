import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { requestTalkGrant } from "./api";
import { TalkController } from "./TalkController";
import type { Envelope } from "./protocol";
import type { TalkConnectionState, TalkError, TalkTransport } from "./types";

export interface Talk {
  state: TalkConnectionState;
  error: TalkError | null;
  /** The agent's last `state` message, once Phase 6 starts sending them. */
  agentState: string | null;
  connect: () => void;
  disconnect: () => void;
}

/**
 * One TalkController per reading session.
 *
 * The transport is injected rather than imported: the LiveKit implementation needs a development build, so
 * a caller running in Expo Go (or a test) passes a fake, and the screen behaves the same.
 */
export function useTalk(sessionId: string | undefined, transport: TalkTransport | null): Talk {
  const [state, setState] = useState<TalkConnectionState>("idle");
  const [error, setError] = useState<TalkError | null>(null);
  const [agentState, setAgentState] = useState<string | null>(null);
  const controllerRef = useRef<TalkController | null>(null);

  const controller = useMemo(() => {
    if (!transport) return null;
    return new TalkController({
      transport,
      requestGrant: requestTalkGrant,
      onState: setState,
      onError: setError,
      onMessage: (envelope: Envelope) => {
        if (envelope.type === "state" && typeof envelope.payload.state === "string") {
          setAgentState(envelope.payload.state);
        }
      },
    });
  }, [transport]);

  useEffect(() => {
    controllerRef.current = controller;
    return () => {
      // Leaving the reader must end the room: an agent narrating to nobody still costs money.
      void controller?.stop();
    };
  }, [controller]);

  const connect = useCallback(() => {
    if (!sessionId || !controllerRef.current) return;
    void controllerRef.current.start(sessionId);
  }, [sessionId]);

  const disconnect = useCallback(() => {
    void controllerRef.current?.stop();
    setAgentState(null);
  }, []);

  return { state, error, agentState, connect, disconnect };
}
