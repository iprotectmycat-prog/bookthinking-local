import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({ default: ({ children }: { children: React.ReactNode }) => <a>{children}</a> }));
vi.mock("../lib/api", () => ({ apiJson: vi.fn() }));

import { ChapterEditor } from "../components/ChapterEditor";
import type { Book } from "../lib/types";

const epubBook: Book = {
  id: "epub-1",
  filename: "fragmented.epub",
  source_format: "epub", access_scope: "owned",
  status: "awaiting_chapter_confirmation",
  structure_version: "epub-v2",
  structure_diagnostics: ["unresolved_anchor:OPS/chapter.xhtml#missing"],
  chapters: [{ title: "第一章", source_start_page: 1, source_end_page: 1, depth: 0 }],
};

describe("ChapterEditor public EPUB flow", () => {
  it("hides structure repair and EPUB page controls", () => {
    render(<ChapterEditor book={epubBook} />);

    expect(screen.queryByLabelText("EPUB 结构诊断")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "重新解析 EPUB 结构" })).not.toBeInTheDocument();
    expect(screen.queryByText("起始页")).not.toBeInTheDocument();
    expect(screen.queryByText("结束页")).not.toBeInTheDocument();
  });
});
