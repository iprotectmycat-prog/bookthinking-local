import { render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { BookSummaryHeader } from "../components/BookSummaryHeader";

const stylesheet = readFileSync("app/globals.css", "utf8");

describe("BookSummaryHeader", () => {
  it("recovers the title and author from an older filename", () => {
    render(
      <BookSummaryHeader
        overview={{
          book_id: "keynes",
          book_title: "就业、利息和货币通论 (约翰·凯恩斯（John Maynard Keynes）) (Z-Library).epub",
          source_format: "epub", access_scope: "owned",
          core_question: "", one_sentence_summary: "", estimated_reading_minutes: 148,
          ready_chapter_count: 26, chapter_count: 34, chapters: [],
        }}
      />
    );

    expect(screen.getByRole("heading", { name: "就业、利息和货币通论" })).toBeInTheDocument();
    expect(screen.getByText(/约翰·凯恩斯（John Maynard Keynes）/)).toHaveClass("book-edition-item");
    expect(screen.queryByText(/EPUB/)).not.toBeInTheDocument();
  });

  it("omits the decorative chapter-guide label", () => {
    render(
      <BookSummaryHeader
        overview={{
          book_id: "keynes", book_title: "测试书.epub", source_format: "epub", access_scope: "owned",
          core_question: "", one_sentence_summary: "", estimated_reading_minutes: 1,
          ready_chapter_count: 0, chapter_count: 1, chapters: [],
        }}
      />,
    );

    expect(screen.queryByText("章节导读")).not.toBeInTheDocument();
  });

  it("uses recovered publisher author metadata when a legacy title is already clean", () => {
    render(
      <BookSummaryHeader
        overview={{
          book_id: "legacy", book_title: "置身事内", book_authors: "兰小欢", source_format: "epub", access_scope: "owned",
          core_question: "", one_sentence_summary: "", estimated_reading_minutes: 1,
          ready_chapter_count: 0, chapter_count: 1, chapters: [],
        }}
      />,
    );

    expect(screen.getByText("兰小欢")).toHaveClass("book-edition-item");
  });

  it("gives the author and edition metadata the same 13px type size as chapter links", () => {
    expect(stylesheet).toMatch(/\.book-source-meta\s*\{[^}]*font-size:\s*13px;/);
  });

  it("shows the publisher and composition date as separate fields", () => {
    render(
      <BookSummaryHeader
        overview={{
          book_id: "japan", book_title: "失去的三十年", source_format: "epub", access_scope: "owned",
          core_question: "", one_sentence_summary: "", estimated_reading_minutes: 120,
          ready_chapter_count: 40, chapter_count: 40, top_level_chapter_count: 9,
          section_count: 40, book_publisher: "出版社", book_composition: "2020 年", chapters: [],
        }}
      />,
    );

    expect(screen.getByText("出版社")).toHaveClass("book-edition-item");
    expect(screen.getByText("2020 年")).toHaveClass("book-edition-item");
    expect(screen.queryByText("40 个章节")).not.toBeInTheDocument();
  });
});
