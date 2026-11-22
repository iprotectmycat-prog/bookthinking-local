import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ChapterOverviewList } from "../components/ChapterOverviewList";
import type { ChapterOverview } from "../lib/types";

function chapter(overrides: Partial<ChapterOverview>): ChapterOverview {
  return {
    id: 1,
    position: 0,
    title: "第一章 日本人没有察觉到泡沫经济的崩溃",
    source_start_page: 1,
    source_end_page: 1,
    chapter_question: "",
    one_sentence_conclusion: "",
    core_idea_titles: [],
    role_in_book: "",
    estimated_reading_minutes: 3,
    generation_status: "skipped",
    failure_reason: "目录分组，不重复分析",
    nav_kind: "chapter",
    analysis_role: "outline_only",
    ...overrides,
  };
}

describe("ChapterOverviewList", () => {
  it("uses the parent as a chapter heading and renders its children as sections", () => {
    const parentTitle = "第一章 日本人没有察觉到泡沫经济的崩溃";
    const chapters = [
      chapter({ title: parentTitle }),
      chapter({
        id: 2,
        position: 1,
        title: "20世纪80年代，日本的国际地位逐步上升",
        depth: 1,
        parent_title: parentTitle,
        nav_kind: "section",
        analysis_role: "analysis_unit",
        generation_status: "ready",
        one_sentence_conclusion: "第一节结论",
      }),
      chapter({
        id: 3,
        position: 2,
        title: "泡沫经济崩溃，整个日本还在“宿醉”中",
        depth: 1,
        parent_title: parentTitle,
        nav_kind: "section",
        analysis_role: "analysis_unit",
        generation_status: "ready",
        one_sentence_conclusion: "第二节结论",
      }),
    ];

    const { container } = render(
      <ChapterOverviewList
        bookId="book-1"
        chapters={chapters}
        onRetry={vi.fn()}
        retryingChapterId={null}
      />,
    );

    expect(screen.getByRole("heading", { name: parentTitle })).toBeInTheDocument();
    expect(container.querySelectorAll("article.chapter-card.is-section")).toHaveLength(2);
    expect(container.querySelector("article#chapter-1")).not.toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /阅读本节/ })).toHaveLength(2);
  });

  it("keeps an outline-only part visible above its chapter and section", () => {
    const partTitle = "上篇 微观机制";
    const chapterTitle = "第一章 权力与事务";
    const chapters = [
      chapter({ title: partTitle, nav_kind: "part", analysis_role: "outline_only" }),
      chapter({
        id: 2,
        title: chapterTitle,
        nav_kind: "chapter",
        depth: 1,
        parent_title: partTitle,
        analysis_role: "analysis_unit",
        generation_status: "ready",
      }),
      chapter({
        id: 3,
        title: "第一节 治理特点",
        nav_kind: "section",
        depth: 2,
        parent_title: chapterTitle,
        analysis_role: "analysis_unit",
        generation_status: "ready",
      }),
    ];

    const { container } = render(
      <ChapterOverviewList bookId="book-1" chapters={chapters} onRetry={vi.fn()} retryingChapterId={null} />,
    );

    expect(screen.getByRole("heading", { name: partTitle })).toBeInTheDocument();
    expect(container.querySelector("#chapter-1")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: chapterTitle })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /阅读本节/ })).toBeInTheDocument();
  });
});
