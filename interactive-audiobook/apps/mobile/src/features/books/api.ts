import type { ChapterContent } from "@audiobook/shared-types";
import { unwrap } from "@audiobook/api-client";
import { queryOptions, useQuery } from "@tanstack/react-query";

import { api } from "../../services/api";

export const bookKeys = {
  list: ["books"] as const,
  detail: (bookId: string) => ["books", bookId] as const,
  chapter: (bookId: string, chapterId: string) => ["books", bookId, "chapters", chapterId] as const,
};

export async function fetchBooks() {
  return unwrap(await api.GET("/v1/books", { params: { query: { limit: 50, offset: 0 } } }));
}

export async function fetchBook(bookId: string) {
  return unwrap(await api.GET("/v1/books/{book_id}", { params: { path: { book_id: bookId } } }));
}

export async function fetchChapter(bookId: string, chapterId: string): Promise<ChapterContent> {
  return unwrap(
    await api.GET("/v1/books/{book_id}/chapters/{chapter_id}", {
      params: { path: { book_id: bookId, chapter_id: chapterId } },
    }),
  );
}

export function chapterQuery(bookId: string, chapterId: string) {
  return queryOptions({
    queryKey: bookKeys.chapter(bookId, chapterId),
    queryFn: () => fetchChapter(bookId, chapterId),
    // Book text only changes when an admin reprocesses the book.
    staleTime: 10 * 60_000,
  });
}

export function useBooks() {
  return useQuery({ queryKey: bookKeys.list, queryFn: fetchBooks });
}

export function useBook(bookId: string) {
  return useQuery({ queryKey: bookKeys.detail(bookId), queryFn: () => fetchBook(bookId), staleTime: 5 * 60_000 });
}
