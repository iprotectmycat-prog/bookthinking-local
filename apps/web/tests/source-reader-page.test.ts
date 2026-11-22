import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("standalone source reader page", () => {
  it("reuses the in-browser source content instead of exposing a file navigation", () => {
    const pageSource = readFileSync(
      resolve(process.cwd(), "app/books/[bookId]/read/page.tsx"),
      "utf8",
    );

    expect(pageSource).toContain("<SourceReaderContent");
    expect(pageSource).not.toContain("<object");
    expect(pageSource).not.toContain("href={fileUrl}");
  });

  it("parses persistent EPUB locators from the standalone reader URL without CFI", () => {
    const pageSource = readFileSync(
      resolve(process.cwd(), "app/books/[bookId]/read/page.tsx"),
      "utf8",
    );

    expect(pageSource).toContain('searchParams.get("href")');
    expect(pageSource).toContain('searchParams.get("fragment")');
    expect(pageSource).toContain('searchParams.get("spine")');
    expect(pageSource).toContain("cfi: null");
    expect(pageSource).toContain("restoreProgress");
    expect(pageSource).not.toContain('searchParams.get("cfi")');
  });
});
