import { render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { describe, expect, it, vi } from "vitest";

import { ChapterOverviewCard } from "../components/ChapterOverviewCard";

const stylesheet = readFileSync("app/globals.css", "utf8");

describe("ChapterOverviewCard", () => {
  it("keeps a ready card free of status and source codes, and links to its chapter", () => {
    render(
      <ChapterOverviewCard
        bookId="book-1"
        onRetry={vi.fn()}
        chapter={{
          id: 7, position: 0, title: "前言", source_start_page: 7, source_end_page: 7,
          chapter_question: "本章问题", one_sentence_conclusion: "本章结论", core_idea_titles: ["观点一"],
          role_in_book: "介绍本书主题", estimated_reading_minutes: 3, generation_status: "ready", failure_reason: null,
        }}
      />,
    );

    expect(screen.queryByText("可阅读")).not.toBeInTheDocument();
    expect(screen.queryByText("章节片段 7–7")).not.toBeInTheDocument();
    expect(screen.queryByText("本章问题")).not.toBeInTheDocument();
    expect(screen.getByText("本章结论")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /阅读本章/ })).toHaveAttribute("href", "/books/book-1/chapters/7");
  });

  it("shows each conclusion on its own row without a divider below the list", () => {
    const previewRule = stylesheet.match(/\.idea-preview\s*\{[^}]*\}/)?.[0];

    expect(previewRule).toMatch(/grid-template-columns:\s*minmax\(0,\s*1fr\);/);
    expect(previewRule).not.toMatch(/border-bottom:/);
  });

  it("keeps subsection cards aligned with the chapter overview cards", () => {
    const subsectionListRule = stylesheet.match(/\.chapter-section-list\s*\{[^}]*\}/)?.[0];

    expect(subsectionListRule).toMatch(/margin-left:\s*0/);
  });

  it("renders a subsection with lower visual weight and section wording", () => {
    const { container } = render(
      <ChapterOverviewCard
        bookId="book-1"
        onRetry={vi.fn()}
        level="section"
        chapter={{
          id: 8, position: 1, title: "20世纪80年代，日本的国际地位逐步上升",
          source_start_page: 8, source_end_page: 8, chapter_question: "", one_sentence_conclusion: "小节结论",
          core_idea_titles: ["观点一"], role_in_book: "支撑第一章", estimated_reading_minutes: 3,
          generation_status: "ready", failure_reason: null, depth: 1, parent_title: "第一章", nav_kind: "section",
        }}
      />,
    );

    expect(container.querySelector(".chapter-card.is-section")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /阅读本节/ })).toBeInTheDocument();
  });
});
