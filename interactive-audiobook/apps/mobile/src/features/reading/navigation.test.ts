import {
  edgeLocation,
  globalSentenceSeq,
  locate,
  moveParagraph,
  moveSentence,
  progressOf,
  type LoadedParagraph,
} from "./navigation";

// Chapter 1 of a 3-chapter book: p0 [3 sentences], p1 [empty], p2 [2]
const chapter: LoadedParagraph[] = [
  { id: "p0", first_sentence_seq: 10, sentences: ["a", "b", "c"] },
  { id: "p1", first_sentence_seq: 13, sentences: [] },
  { id: "p2", first_sentence_seq: 13, sentences: ["d", "e"] },
];
const at = (paragraphIndex: number, sentenceIndex: number, chapterIndex = 1) => ({
  chapterIndex,
  paragraphIndex,
  sentenceIndex,
});

describe("sentence navigation", () => {
  it("moves within and across paragraphs, skipping empty ones", () => {
    expect(moveSentence(3, chapter, at(0, 1), 1)).toEqual({ type: "location", location: at(0, 2) });
    expect(moveSentence(3, chapter, at(0, 2), 1)).toEqual({ type: "location", location: at(2, 0) });
    expect(moveSentence(3, chapter, at(2, 0), -1)).toEqual({ type: "location", location: at(0, 2) });
  });

  it("asks for the neighbouring chapter at the edges", () => {
    expect(moveSentence(3, chapter, at(2, 1), 1)).toEqual({ type: "chapter", chapterIndex: 2, edge: "start" });
    expect(moveSentence(3, chapter, at(0, 0), -1)).toEqual({ type: "chapter", chapterIndex: 0, edge: "end" });
  });

  it("stops at the beginning and end of the book", () => {
    expect(moveSentence(3, chapter, at(0, 0, 0), -1)).toEqual({ type: "none" });
    expect(moveSentence(3, chapter, at(2, 1, 2), 1)).toEqual({ type: "none" });
  });

  it("ignores invalid locations", () => {
    expect(moveSentence(3, chapter, at(1, 0), 1)).toEqual({ type: "none" });
    expect(moveSentence(3, chapter, at(9, 0), 1)).toEqual({ type: "none" });
  });
});

describe("paragraph navigation", () => {
  it("previous rewinds to the paragraph start first", () => {
    expect(moveParagraph(3, chapter, at(2, 1), -1)).toEqual({ type: "location", location: at(2, 0) });
    expect(moveParagraph(3, chapter, at(2, 0), -1)).toEqual({ type: "location", location: at(0, 0) });
    expect(moveParagraph(3, chapter, at(0, 0), -1)).toEqual({ type: "chapter", chapterIndex: 0, edge: "start" });
  });

  it("next goes to the next non-empty paragraph, then the next chapter", () => {
    expect(moveParagraph(3, chapter, at(0, 1), 1)).toEqual({ type: "location", location: at(2, 0) });
    expect(moveParagraph(3, chapter, at(2, 0), 1)).toEqual({ type: "chapter", chapterIndex: 2, edge: "start" });
  });
});

describe("positions and progress", () => {
  it("computes global sentence numbers like the server", () => {
    expect(globalSentenceSeq(chapter, at(0, 2))).toBe(12);
    expect(globalSentenceSeq(chapter, at(2, 1))).toBe(14);
    expect(globalSentenceSeq(chapter, at(1, 0))).toBeNull();
    expect(progressOf(20, 14)).toBe(0.75);
    expect(progressOf(0, 3)).toBe(0);
  });

  it("finds chapter edges", () => {
    expect(edgeLocation(1, chapter, "start")).toEqual(at(0, 0));
    expect(edgeLocation(1, chapter, "end")).toEqual(at(2, 1));
    expect(edgeLocation(1, [], "end")).toBeNull();
  });

  it("locates a server position, clamping or falling back to the chapter start", () => {
    expect(locate(1, chapter, "p2", 1)).toEqual(at(2, 1));
    expect(locate(1, chapter, "p2", 99)).toEqual(at(2, 1));
    expect(locate(1, chapter, "missing", 0)).toEqual(at(0, 0));
    expect(locate(1, chapter, null, 0)).toEqual(at(0, 0));
  });
});
