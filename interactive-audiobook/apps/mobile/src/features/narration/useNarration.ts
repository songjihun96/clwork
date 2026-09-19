import { useCallback, useEffect, useRef, useState } from "react";

import { sessionAudioSource } from "./api";
import { createNarrationPlayer } from "./expoAudioPlayer";
import { NarrationController, type NarrationError, type NarrationState } from "./NarrationController";

interface NarrationHandlers {
  onSentence: (paragraphId: string, sentenceIndex: number) => void;
  onParagraphEnd: (paragraphId: string) => void;
}

export interface Narration {
  state: NarrationState;
  error: NarrationError | null;
  start: (paragraphId: string, sentenceIndex: number, lookahead: string[]) => void;
  pause: () => void;
}

/** One NarrationController per reading session; handlers always see the latest reader state. */
export function useNarration(sessionId: string | undefined, rate: number, handlers: NarrationHandlers): Narration {
  const [state, setState] = useState<NarrationState>("idle");
  const [error, setError] = useState<NarrationError | null>(null);
  const handlersRef = useRef(handlers);
  // Synced after commit, never during render: a discarded render must not publish its callbacks.
  useEffect(() => {
    handlersRef.current = handlers;
  });
  const controllerRef = useRef<NarrationController | null>(null);

  useEffect(() => {
    if (!sessionId) return;
    const controller = new NarrationController(createNarrationPlayer(), sessionAudioSource(sessionId), {
      onSentence: (paragraphId, sentenceIndex) => handlersRef.current.onSentence(paragraphId, sentenceIndex),
      onParagraphEnd: (paragraphId) => handlersRef.current.onParagraphEnd(paragraphId),
      onState: (next, failure) => {
        setState(next);
        setError(failure ?? null);
      },
    });
    controllerRef.current = controller;
    return () => {
      controller.dispose();
      controllerRef.current = null;
    };
  }, [sessionId]);

  useEffect(() => {
    controllerRef.current?.setRate(rate);
  }, [rate, sessionId]);

  const start = useCallback((paragraphId: string, sentenceIndex: number, lookahead: string[]) => {
    void controllerRef.current?.start(paragraphId, sentenceIndex, lookahead);
  }, []);
  const pause = useCallback(() => controllerRef.current?.pause(), []);

  return { state, error, start, pause };
}
