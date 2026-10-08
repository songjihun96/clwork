/**
 * Reader integration test against a fake HTTP server: exercises the real API client, React Query hooks,
 * position saver and version conflicts (only the network is simulated).
 */
import type { BookDetail, ChapterContent, ReadingSession } from "@audiobook/shared-types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react-native";
import { Alert } from "react-native";

import { ThemeProvider } from "../../theme/ThemeProvider";
import { ReaderScreen } from "./ReaderScreen";

jest.mock("expo-secure-store", () => ({
  AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY: 0,
  getItemAsync: jest.fn(async () => null),
  setItemAsync: jest.fn(async () => undefined),
  deleteItemAsync: jest.fn(async () => undefined),
}));
// Narration plays through a fake player the test can drive.
const mockPlayers: import("../../features/narration/testing/FakePlayer").FakePlayer[] = [];
jest.mock("../../features/narration/expoAudioPlayer", () => {
  const { FakePlayer } = jest.requireActual("../../features/narration/testing/FakePlayer");
  return {
    createNarrationPlayer: () => {
      const player = new FakePlayer();
      mockPlayers.push(player);
      return player;
    },
  };
});
jest.mock("react-native-safe-area-context", () => {
  const { View } = jest.requireActual("react-native");
  return { SafeAreaView: View };
});

const BOOK: BookDetail = {
  id: "book-1",
  title: "등대지기의 밤",
  author: "샘플",
  language: "ko",
  description: null,
  total_sentences: 5,
  total_paragraphs: 3,
  chapters: [
    { id: "c1", sequence: 0, title: "1장", first_sentence_seq: 0, sentence_count: 3 },
    { id: "c2", sequence: 1, title: "2장", first_sentence_seq: 3, sentence_count: 2 },
  ],
};

const CHAPTERS: Record<string, ChapterContent> = {
  c1: {
    ...BOOK.chapters[0]!,
    book_id: "book-1",
    paragraphs: [
      { id: "p1", sequence: 0, global_seq: 0, first_sentence_seq: 0, scene_break_before: false, sentences: ["첫 문장.", "둘째 문장."] },
      { id: "p2", sequence: 1, global_seq: 1, first_sentence_seq: 2, scene_break_before: true, sentences: ["셋째 문장."] },
    ],
  },
  c2: {
    ...BOOK.chapters[1]!,
    book_id: "book-1",
    paragraphs: [
      { id: "p3", sequence: 0, global_seq: 2, first_sentence_seq: 3, scene_break_before: false, sentences: ["넷째 문장.", "다섯째 문장."] },
    ],
  },
};

const PARAGRAPH_CHAPTER: Record<string, { chapter: string; first: number }> = {
  p1: { chapter: "c1", first: 0 },
  p2: { chapter: "c1", first: 2 },
  p3: { chapter: "c2", first: 3 },
};

interface ServerState {
  paragraphId: string;
  sentenceIndex: number;
  version: number;
  playback: ReadingSession["playback_state"];
  patches: { paragraph_id: string; sentence_index: number; expected_version: number }[];
  requests: string[];
  audioRequests: string[][];
}

let server: ServerState;

function session(): ReadingSession {
  const { chapter, first } = PARAGRAPH_CHAPTER[server.paragraphId]!;
  const seq = first + server.sentenceIndex;
  return {
    id: "session-1",
    book: { id: "book-1", title: BOOK.title, author: BOOK.author, total_sentences: 5 },
    playback_state: server.playback,
    spoiler_mode: "NO_SPOILER",
    speed: 1,
    max_read_seq: seq,
    progress: (seq + 1) / 5,
    position: {
      chapter_id: chapter,
      paragraph_id: server.paragraphId,
      sentence_index: server.sentenceIndex,
      sentence_global_seq: seq,
      position_version: server.version,
      updated_at: "2026-09-15T00:00:00Z",
    },
    created_at: "2026-09-15T00:00:00Z",
    last_active_at: "2026-09-15T00:00:00Z",
  };
}

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

async function fakeFetch(input: RequestInfo | URL): Promise<Response> {
  const request = input as Request;
  const path = new URL(request.url).pathname;
  server.requests.push(`${request.method} ${path}`);
  const chapterMatch = path.match(/^\/v1\/books\/book-1\/chapters\/(c\d)$/);

  if (request.method === "GET" && path === "/v1/books/book-1") return json(200, BOOK);
  if (request.method === "GET" && chapterMatch) return json(200, CHAPTERS[chapterMatch[1]!]);
  if (request.method === "POST" && path === "/v1/reading/sessions") return json(200, session());
  if (request.method === "GET" && path === "/v1/reading/sessions") return json(200, { items: [session()] });
  if (request.method === "GET" && path === "/v1/reading/sessions/session-1") return json(200, session());
  if (request.method === "PATCH" && path === "/v1/reading/sessions/session-1") {
    const body = (await request.json()) as { position: ServerState["patches"][number] };
    server.patches.push(body.position);
    if (body.position.expected_version !== server.version) {
      return json(409, { error: { code: "position_conflict", message: "moved elsewhere" } });
    }
    server.paragraphId = body.position.paragraph_id;
    server.sentenceIndex = body.position.sentence_index;
    server.version += 1;
    return json(200, session());
  }
  if (request.method === "POST" && path === "/v1/reading/sessions/session-1/audio") {
    const { paragraph_ids } = (await request.json()) as { paragraph_ids: string[] };
    server.audioRequests.push(paragraph_ids);
    const sentencesOf = (id: string) =>
      Object.values(CHAPTERS).flatMap((c) => c.paragraphs).find((p) => p.id === id)?.sentences ?? [];
    return json(200, {
      retry_after_ms: null,
      items: paragraph_ids.map((id) => ({
        paragraph_id: id,
        status: "ready",
        audio: {
          url: `http://api.test/v1/media/audio/${id}.wav?exp=9999999999&sig=${"a".repeat(64)}`,
          expires_at: "2099-01-01T00:00:00Z",
          format: "wav",
          duration_ms: sentencesOf(id).length * 1000,
          sentence_timings: sentencesOf(id).map((_, i) => ({ sentence_index: i, start_ms: i * 1000, end_ms: (i + 1) * 1000 })),
        },
      })),
    });
  }
  if (request.method === "POST" && path === "/v1/reading/sessions/session-1/playback") {
    const { action } = (await request.json()) as { action: string };
    server.playback = action === "play" ? "READING" : action === "pause" ? "PAUSED" : "IDLE";
    return json(200, session());
  }
  return json(404, { error: { code: "not_found", message: path } });
}

let queryClient: QueryClient;

async function renderReader() {
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  const navigation = { setOptions: jest.fn() };
  const props = {
    navigation,
    route: { key: "Reader", name: "Reader", params: { bookId: "book-1" } },
  } as unknown as Parameters<typeof ReaderScreen>[0];
  const view = await render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <ReaderScreen {...props} />
      </ThemeProvider>
    </QueryClientProvider>,
  );
  return { navigation, view };
}

const selected = (testID: string) => screen.queryByTestId(testID)?.props.accessibilityState?.selected === true;

describe("ReaderScreen", () => {
  beforeEach(() => {
    server = {
      paragraphId: "p2",
      sentenceIndex: 0,
      version: 5,
      playback: "PAUSED",
      patches: [],
      requests: [],
      audioRequests: [],
    };
    mockPlayers.length = 0;
    globalThis.fetch = jest.fn(fakeFetch) as typeof fetch;
  });
  afterEach(() => {
    queryClient?.clear();
    jest.restoreAllMocks();
  });

  it("restores the saved sentence and shows progress without writing", async () => {
    const { navigation } = await renderReader();
    await waitFor(() => expect(selected("sentence-p2-0")).toBe(true));
    expect(selected("sentence-p1-0")).toBe(false);
    expect(screen.getByText("60%")).toBeTruthy();
    expect(screen.getByLabelText("장면 전환")).toBeTruthy();
    expect(navigation.setOptions).toHaveBeenCalledWith({ title: "등대지기의 밤" });
    expect(server.patches).toEqual([]);
  });

  it("moves across chapters and saves each position with the current version", async () => {
    await renderReader();
    await waitFor(() => expect(selected("sentence-p2-0")).toBe(true));

    await fireEvent.press(screen.getByRole("button", { name: "다음 문장" }));
    await waitFor(() => expect(selected("sentence-p3-0")).toBe(true));
    expect(server.requests).toContain("GET /v1/books/book-1/chapters/c2");
    await waitFor(() => expect(server.version).toBe(6));
    expect(screen.getByText("80%")).toBeTruthy();

    await fireEvent.press(screen.getByRole("button", { name: "이전 문장" }));
    await waitFor(() => expect(selected("sentence-p2-0")).toBe(true));
    await waitFor(() => expect(server.version).toBe(7));
    expect(server.patches).toEqual([
      { paragraph_id: "p3", sentence_index: 0, expected_version: 5 },
      { paragraph_id: "p2", sentence_index: 0, expected_version: 6 },
    ]);
  });

  it("asks the user when another device moved the position, and can adopt it", async () => {
    const alert = jest.spyOn(Alert, "alert").mockImplementation(() => undefined);
    await renderReader();
    await waitFor(() => expect(selected("sentence-p2-0")).toBe(true));

    // Another device reads to the last sentence meanwhile.
    Object.assign(server, { paragraphId: "p3", sentenceIndex: 1, version: 9 });
    await fireEvent.press(screen.getByTestId("sentence-p1-1"));

    await waitFor(() => expect(alert).toHaveBeenCalled());
    expect(alert.mock.calls[0]![1]).toContain("100%");
    const buttons = alert.mock.calls[0]![2]!;
    await act(async () => buttons.find((b) => b.text === "다른 기기 위치")!.onPress!());

    await waitFor(() => expect(selected("sentence-p3-1")).toBe(true));
    expect(server.patches).toHaveLength(1); // the rejected write only; adopting does not write
    expect(server.version).toBe(9);
  });

  it("narrates: plays the audible sentence, follows it, and continues into the next chapter", async () => {
    await renderReader();
    await waitFor(() => expect(selected("sentence-p2-0")).toBe(true));
    const player = mockPlayers[0]!;

    await fireEvent.press(screen.getByRole("button", { name: "재생" }));
    await waitFor(() => expect(player.playing).toBe(true));
    expect(server.audioRequests[0]).toEqual(["p2"]); // last paragraph of the chapter: no lookahead left
    expect(player.loads[0]).toContain("/audio/p2.wav");
    expect(player.seeks).toEqual([0]);
    await waitFor(() => expect(screen.getByText("읽는 중")).toBeTruthy());
    expect(server.playback).toBe("READING");

    // Paragraph finished → next chapter loads → its first paragraph plays automatically.
    await act(async () => player.emit(1000, { didJustFinish: true }));
    await waitFor(() => expect(player.loads).toHaveLength(2));
    expect(player.loads[1]).toContain("/audio/p3.wav");
    await waitFor(() => expect(selected("sentence-p3-0")).toBe(true));

    // The audible sentence drives the highlight and the saved position.
    await act(async () => player.emit(1200));
    await waitFor(() => expect(selected("sentence-p3-1")).toBe(true));
    await waitFor(() =>
      expect(server.patches.at(-1)).toMatchObject({ paragraph_id: "p3", sentence_index: 1 }),
    );

    await fireEvent.press(screen.getByRole("button", { name: "일시정지" }));
    expect(player.playing).toBe(false);
    await waitFor(() => expect(server.playback).toBe("PAUSED"));
  });

  it("jumping to a sentence while narrating seeks the audio", async () => {
    await renderReader();
    await waitFor(() => expect(selected("sentence-p2-0")).toBe(true));
    const player = mockPlayers[0]!;
    await fireEvent.press(screen.getByRole("button", { name: "재생" }));
    await waitFor(() => expect(player.playing).toBe(true));

    await fireEvent.press(screen.getByTestId("sentence-p1-1"));
    await waitFor(() => expect(player.loads.at(-1)).toContain("/audio/p1.wav"));
    await waitFor(() => expect(player.seeks.at(-1)).toBe(1000));
    expect(server.audioRequests.at(-1)).toEqual(["p1", "p2"]); // lookahead within the chapter
  });
});
