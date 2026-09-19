/**
 * Pure reader navigation over the server's content model.
 *
 * The client never holds the whole book: it has the chapter outline plus the paragraphs of the chapter
 * being read. Moves that leave the loaded chapter return a "chapter" result so the caller can load it.
 * Sentence numbering matches the backend: global sentence seq = paragraph.first_sentence_seq + index.
 */

export interface OutlineChapter {
  id: string;
  sequence: number;
  first_sentence_seq: number;
  sentence_count: number;
}

export interface LoadedParagraph {
  id: string;
  first_sentence_seq: number;
  sentences: readonly string[];
}

export interface ReaderLocation {
  chapterIndex: number;
  paragraphIndex: number;
  sentenceIndex: number;
}

export type NavigationResult =
  | { type: "location"; location: ReaderLocation }
  | { type: "chapter"; chapterIndex: number; edge: "start" | "end" }
  | { type: "none" };

const none: NavigationResult = { type: "none" };

function isValid(paragraphs: readonly LoadedParagraph[], location: ReaderLocation): boolean {
  const paragraph = paragraphs[location.paragraphIndex];
  return !!paragraph && location.sentenceIndex >= 0 && location.sentenceIndex < paragraph.sentences.length;
}

function lastParagraphWithText(paragraphs: readonly LoadedParagraph[]): number {
  for (let i = paragraphs.length - 1; i >= 0; i--) {
    if ((paragraphs[i]?.sentences.length ?? 0) > 0) return i;
  }
  return -1;
}

/** First or last sentence of a loaded chapter. */
export function edgeLocation(
  chapterIndex: number,
  paragraphs: readonly LoadedParagraph[],
  edge: "start" | "end",
): ReaderLocation | null {
  if (edge === "start") {
    const first = paragraphs.findIndex((p) => p.sentences.length > 0);
    return first < 0 ? null : { chapterIndex, paragraphIndex: first, sentenceIndex: 0 };
  }
  const last = lastParagraphWithText(paragraphs);
  const paragraph = paragraphs[last];
  return paragraph ? { chapterIndex, paragraphIndex: last, sentenceIndex: paragraph.sentences.length - 1 } : null;
}

export function moveSentence(
  chapterCount: number,
  paragraphs: readonly LoadedParagraph[],
  location: ReaderLocation,
  delta: 1 | -1,
): NavigationResult {
  if (!isValid(paragraphs, location)) return none;
  const { chapterIndex, paragraphIndex, sentenceIndex } = location;
  const paragraph = paragraphs[paragraphIndex]!;

  if (delta === 1) {
    if (sentenceIndex + 1 < paragraph.sentences.length) {
      return { type: "location", location: { chapterIndex, paragraphIndex, sentenceIndex: sentenceIndex + 1 } };
    }
    for (let i = paragraphIndex + 1; i < paragraphs.length; i++) {
      if ((paragraphs[i]?.sentences.length ?? 0) > 0) {
        return { type: "location", location: { chapterIndex, paragraphIndex: i, sentenceIndex: 0 } };
      }
    }
    return chapterIndex + 1 < chapterCount ? { type: "chapter", chapterIndex: chapterIndex + 1, edge: "start" } : none;
  }

  if (sentenceIndex > 0) {
    return { type: "location", location: { chapterIndex, paragraphIndex, sentenceIndex: sentenceIndex - 1 } };
  }
  for (let i = paragraphIndex - 1; i >= 0; i--) {
    const previous = paragraphs[i];
    if (previous && previous.sentences.length > 0) {
      return {
        type: "location",
        location: { chapterIndex, paragraphIndex: i, sentenceIndex: previous.sentences.length - 1 },
      };
    }
  }
  return chapterIndex > 0 ? { type: "chapter", chapterIndex: chapterIndex - 1, edge: "end" } : none;
}

/**
 * Paragraph navigation with audio-player semantics: "previous" in the middle of a paragraph first rewinds
 * to that paragraph's first sentence; from a chapter's first paragraph it goes to the previous chapter's start.
 */
export function moveParagraph(
  chapterCount: number,
  paragraphs: readonly LoadedParagraph[],
  location: ReaderLocation,
  delta: 1 | -1,
): NavigationResult {
  if (!isValid(paragraphs, location)) return none;
  const { chapterIndex, paragraphIndex, sentenceIndex } = location;

  if (delta === -1 && sentenceIndex > 0) {
    return { type: "location", location: { chapterIndex, paragraphIndex, sentenceIndex: 0 } };
  }
  for (let i = paragraphIndex + delta; i >= 0 && i < paragraphs.length; i += delta) {
    if ((paragraphs[i]?.sentences.length ?? 0) > 0) {
      return { type: "location", location: { chapterIndex, paragraphIndex: i, sentenceIndex: 0 } };
    }
  }
  const target = chapterIndex + delta;
  return target >= 0 && target < chapterCount ? { type: "chapter", chapterIndex: target, edge: "start" } : none;
}

export function globalSentenceSeq(paragraphs: readonly LoadedParagraph[], location: ReaderLocation): number | null {
  if (!isValid(paragraphs, location)) return null;
  return paragraphs[location.paragraphIndex]!.first_sentence_seq + location.sentenceIndex;
}

/** Fraction read, counting the current sentence (matches the server's session progress). */
export function progressOf(totalSentences: number, globalSeq: number | null): number {
  if (totalSentences <= 0 || globalSeq === null) return 0;
  return Math.min(1, Math.max(0, (globalSeq + 1) / totalSentences));
}

/** Resolves a server position (paragraph id + sentence index) inside a loaded chapter. */
export function locate(
  chapterIndex: number,
  paragraphs: readonly LoadedParagraph[],
  paragraphId: string | null | undefined,
  sentenceIndex: number,
): ReaderLocation | null {
  const paragraphIndex = paragraphs.findIndex((p) => p.id === paragraphId);
  if (paragraphIndex < 0) return edgeLocation(chapterIndex, paragraphs, "start");
  const count = paragraphs[paragraphIndex]!.sentences.length;
  if (count === 0) return edgeLocation(chapterIndex, paragraphs, "start");
  return { chapterIndex, paragraphIndex, sentenceIndex: Math.min(Math.max(sentenceIndex, 0), count - 1) };
}
