import { beforeEach, describe, expect, it } from "vitest";

import {
  defaultReaderState,
  loadReaderState,
  saveReaderPreferences,
  saveReaderProgress,
} from "../lib/epub-reader-storage";

describe("EPUB reader storage", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("round-trips versioned progress and preferences per book", () => {
    saveReaderPreferences("book-1", {
      flow: "paginated",
      fontScale: 110,
      lineHeight: 1.7,
      pageMargin: 32,
      theme: "system",
    });
    saveReaderProgress("book-1", "epubcfi(/6/8!/4/2:0)");

    expect(loadReaderState("book-1")).toMatchObject({
      version: 1,
      progressCfi: "epubcfi(/6/8!/4/2:0)",
      preferences: { fontScale: 110 },
    });
  });

  it("falls back safely when stored JSON is invalid", () => {
    localStorage.setItem("bookthinking:epub-reader:v1:book-1", "{");

    expect(loadReaderState("book-1")).toEqual(defaultReaderState());
  });

  it("ignores unrecognized values from an older or corrupt payload", () => {
    localStorage.setItem("bookthinking:epub-reader:v1:book-1", JSON.stringify({
      version: 1,
      progressCfi: 42,
      preferences: { flow: "scroll", fontScale: 999, theme: "sepia" },
    }));

    expect(loadReaderState("book-1")).toEqual(defaultReaderState());
  });
});
