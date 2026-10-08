import type { BookDetail, ChapterContent, PlaybackAction, ReadingSession } from "@audiobook/shared-types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AppState } from "react-native";

import { chapterQuery, useBook } from "../books/api";
import type { NarrationError, NarrationState } from "../narration/NarrationController";
import { useNarration } from "../narration/useNarration";
import { fetchSession, openSession, savePosition, sendPlayback, sessionKeys } from "./api";
import {
  edgeLocation,
  globalSentenceSeq,
  locate,
  moveParagraph,
  moveSentence,
  progressOf,
  type NavigationResult,
  type ReaderLocation,
} from "./navigation";
import { PositionSaver } from "./positionSaver";

/**
 * A position the reader wants to be at. Resolving it needs the target chapter's content, which loads
 * asynchronously, so the target is state and the location is derived from it — never written back by an
 * effect, which would cost an extra render pass and break under concurrent rendering.
 */
type Target = (
  | { chapterIndex: number; paragraphId: string | null; sentenceIndex: number }
  | { chapterIndex: number; edge: "start" | "end" }
) & { id: number; save: boolean; autoplay?: boolean };

const INITIAL_TARGET_ID = 0;

const LOOKAHEAD_PARAGRAPHS = 2;

export interface PositionConflict {
  serverSession: ReadingSession;
  keepMine: () => void;
  useServer: () => void;
}

export interface ReaderController {
  book: BookDetail | undefined;
  session: ReadingSession | undefined;
  chapter: ChapterContent | undefined;
  location: ReaderLocation | null;
  progress: number;
  loading: boolean;
  error: unknown;
  /** Server state, refined with local audio progress (PREPARING while audio loads). */
  displayState: ReadingSession["playback_state"];
  narrationState: NarrationState;
  narrationError: NarrationError | null;
  conflict: PositionConflict | null;
  goTo: (location: ReaderLocation) => void;
  sentence: (delta: 1 | -1) => void;
  paragraph: (delta: 1 | -1) => void;
  playback: (action: PlaybackAction) => Promise<void>;
}

function chapterIndexOf(book: BookDetail, chapterId: string | null | undefined): number {
  const index = book.chapters.findIndex((c) => c.id === chapterId);
  return index < 0 ? 0 : index;
}

/**
 * Reader state for one book: restores the saved position, loads chapters on demand, saves position
 * changes (serialised, version-checked), surfaces cross-device conflicts, and drives narration: the audible
 * sentence becomes the reading position, and playback continues across paragraphs and chapters.
 */
export function useReader(bookId: string): ReaderController {
  const queryClient = useQueryClient();
  const bookQuery = useBook(bookId);
  const sessionQuery = useQuery({
    queryKey: sessionKeys.forBook(bookId),
    queryFn: () => openSession(bookId),
    staleTime: 0,
  });
  const book = bookQuery.data;
  const session = sessionQuery.data;

  // Where the user last moved to, tagged with the target it superseded.
  const [committed, setCommitted] = useState<{ location: ReaderLocation; targetId: number } | null>(null);
  const [requested, setRequested] = useState<Target | null>(null);
  const [conflict, setConflict] = useState<PositionConflict | null>(null);
  const saverRef = useRef<PositionSaver | null>(null);
  const nextTargetId = useRef(INITIAL_TARGET_ID);

  // The saved position is a target like any other; deriving it needs no effect.
  const restored = useMemo<Target | null>(
    () =>
      book && session
        ? {
            id: INITIAL_TARGET_ID,
            chapterIndex: chapterIndexOf(book, session.position.chapter_id),
            paragraphId: session.position.paragraph_id ?? null,
            sentenceIndex: session.position.sentence_index,
            save: false,
          }
        : null,
    [book, session],
  );
  const activeTarget = requested ?? restored;
  // A target stops steering the reader as soon as a move has been committed against it.
  const target = activeTarget && committed?.targetId === activeTarget.id ? null : activeTarget;

  const activeChapterIndex = target?.chapterIndex ?? committed?.location.chapterIndex ?? 0;
  const activeChapterId = book?.chapters[activeChapterIndex]?.id;
  const chapterResult = useQuery({
    ...chapterQuery(bookId, activeChapterId ?? "none"),
    enabled: !!activeChapterId,
  });
  const chapter = chapterResult.data?.id === activeChapterId ? chapterResult.data : undefined;

  const handleConflict = useCallback(async () => {
    const sessionId = saverRef.current && session?.id;
    if (!sessionId || !book) return;
    const server = await fetchSession(sessionId);
    setConflict({
      serverSession: server,
      keepMine: () => {
        setConflict(null);
        void saverRef.current?.resolveConflict(server.position.position_version, true);
      },
      useServer: () => {
        setConflict(null);
        void saverRef.current?.resolveConflict(server.position.position_version, false);
        setRequested({
          id: ++nextTargetId.current,
          chapterIndex: chapterIndexOf(book, server.position.chapter_id),
          paragraphId: server.position.paragraph_id ?? null,
          sentenceIndex: server.position.sentence_index,
          save: false,
        });
      },
    });
  }, [book, session?.id]);

  // One saver per session.
  useEffect(() => {
    if (!session) return;
    if (saverRef.current) return;
    saverRef.current = new PositionSaver({
      save: (target, version) => savePosition(session.id, target, version),
      initialVersion: session.position.position_version,
      onConflict: () => void handleConflict(),
      onSaved: () => void queryClient.invalidateQueries({ queryKey: sessionKeys.active }),
    });
  }, [session, handleConflict, queryClient]);

  // Retry unsaved positions when the app returns to the foreground.
  useEffect(() => {
    const subscription = AppState.addEventListener("change", (state) => {
      if (state === "active") void saverRef.current?.flush();
    });
    return () => subscription.remove();
  }, []);

  const activeTargetIdRef = useRef(INITIAL_TARGET_ID);
  const commit = useCallback(
    (next: ReaderLocation, paragraphs: ChapterContent["paragraphs"], save: boolean) => {
      setCommitted({ location: next, targetId: activeTargetIdRef.current });
      const paragraph = paragraphs[next.paragraphIndex];
      if (save && paragraph) {
        void saverRef.current?.update({ paragraphId: paragraph.id, sentenceIndex: next.sentenceIndex });
      }
    },
    [],
  );

  // Resolve the pending target against the chapter that just loaded.
  const resolved = useMemo(() => {
    if (!target || !chapter || !book || book.chapters[target.chapterIndex]?.id !== chapter.id) return null;
    return "edge" in target
      ? edgeLocation(target.chapterIndex, chapter.paragraphs, target.edge)
      : locate(target.chapterIndex, chapter.paragraphs, target.paragraphId, target.sentenceIndex);
  }, [target, chapter, book]);
  const location = target ? resolved : (committed?.location ?? null);
  const settled = !target || !!resolved;

  // Latest values for narration callbacks, which fire outside React's render cycle.
  const latest = useRef({ location, chapter, chapterCount: book?.chapters.length ?? 0 });
  useEffect(() => {
    latest.current = { location, chapter, chapterCount: book?.chapters.length ?? 0 };
    activeTargetIdRef.current = activeTarget?.id ?? INITIAL_TARGET_ID;
  });

  const lookaheadFrom = (paragraphs: ChapterContent["paragraphs"], index: number) =>
    paragraphs.slice(index + 1, index + 1 + LOOKAHEAD_PARAGRAPHS).map((p) => p.id);

  const narrateFrom = (next: ReaderLocation, paragraphs: ChapterContent["paragraphs"]) => {
    const paragraph = paragraphs[next.paragraphIndex];
    if (paragraph) narration.start(paragraph.id, next.sentenceIndex, lookaheadFrom(paragraphs, next.paragraphIndex));
  };

  const narration = useNarration(session?.id, session?.speed ?? 1, {
    onSentence: (paragraphId, sentenceIndex) => {
      const { chapter: current, location: at } = latest.current;
      const paragraphIndex = current?.paragraphs.findIndex((p) => p.id === paragraphId) ?? -1;
      if (!current || !at || paragraphIndex < 0) return;
      commit({ chapterIndex: at.chapterIndex, paragraphIndex, sentenceIndex }, current.paragraphs, true);
    },
    onParagraphEnd: () => {
      const { chapter: current, location: at, chapterCount: count } = latest.current;
      if (!current || !at) return;
      const result = moveParagraph(count, current.paragraphs, at, 1);
      if (result.type === "location") {
        commit(result.location, current.paragraphs, true);
        narrateFrom(result.location, current.paragraphs);
      } else if (result.type === "chapter") {
        setRequested({ id: ++nextTargetId.current, chapterIndex: result.chapterIndex, edge: "start", save: true, autoplay: true }); // prettier-ignore
      } else {
        narration.pause(); // end of the book
        void playback("stop");
      }
    },
  });
  const narrating = narration.state === "loading" || narration.state === "playing";

  // Side effects of arriving at a target: persist it and, for a chapter hand-off, keep narrating.
  // Deliberately no setState — the location itself is derived above.
  const appliedTargetId = useRef(-1);
  useEffect(() => {
    if (!target || !resolved || !chapter || appliedTargetId.current === target.id) return;
    appliedTargetId.current = target.id;
    const paragraph = chapter.paragraphs[resolved.paragraphIndex];
    if (target.save && paragraph) {
      void saverRef.current?.update({ paragraphId: paragraph.id, sentenceIndex: resolved.sentenceIndex });
    }
    if (target.autoplay) narrateFrom(resolved, chapter.paragraphs);
    // narrateFrom only reads stable callbacks and is recreated every render by design
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target, resolved, chapter]);

  const apply = (result: NavigationResult) => {
    if (!chapter) return;
    if (result.type === "location") {
      commit(result.location, chapter.paragraphs, true);
      if (narrating) narrateFrom(result.location, chapter.paragraphs);
    } else if (result.type === "chapter") {
      setRequested({ id: ++nextTargetId.current, chapterIndex: result.chapterIndex, edge: result.edge, save: true, autoplay: narrating }); // prettier-ignore
    }
  };

  const chapterCount = book?.chapters.length ?? 0;
  const paragraphs = chapter?.paragraphs ?? [];

  const progress = useMemo(() => {
    const seq = location && chapter ? globalSentenceSeq(chapter.paragraphs, location) : null;
    return progressOf(book?.total_sentences ?? 0, seq ?? session?.position.sentence_global_seq ?? null);
  }, [location, chapter, book?.total_sentences, session?.position.sentence_global_seq]);

  async function playback(action: PlaybackAction): Promise<void> {
    if (!session) return;
    if (action === "play") {
      const { chapter: current, location: at } = latest.current;
      if (current && at) narrateFrom(at, current.paragraphs);
    } else {
      narration.pause();
    }
    const updated = await sendPlayback(session.id, action);
    queryClient.setQueryData(sessionKeys.forBook(bookId), (previous: ReadingSession | undefined) =>
      previous ? { ...previous, playback_state: updated.playback_state } : updated,
    );
  }

  const serverState = session?.playback_state ?? "IDLE";
  const displayState: ReadingSession["playback_state"] =
    narration.state === "loading" ? "PREPARING" : narration.state === "error" ? "ERROR" : serverState;

  return {
    book,
    session,
    chapter: settled ? chapter : undefined,
    location,
    progress,
    loading: bookQuery.isPending || sessionQuery.isPending || !settled || (!!activeChapterId && !chapter),
    error: bookQuery.error ?? sessionQuery.error ?? chapterResult.error,
    conflict,
    displayState,
    narrationState: narration.state,
    narrationError: narration.error,
    goTo: (next) => {
      commit(next, paragraphs, true);
      if (narrating) narrateFrom(next, paragraphs);
    },
    sentence: (delta) => location && apply(moveSentence(chapterCount, paragraphs, location, delta)),
    paragraph: (delta) => location && apply(moveParagraph(chapterCount, paragraphs, location, delta)),
    playback,
  };
}
