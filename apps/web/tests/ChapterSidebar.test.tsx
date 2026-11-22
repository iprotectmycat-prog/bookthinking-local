import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ChapterSidebar } from "../components/ChapterSidebar";

describe("ChapterSidebar", () => {
  it("reports desktop directory collapse through its controlled state", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    render(<ChapterSidebar bookId="keynes" chapters={[]} isOpen onOpenChange={onOpenChange} />);

    const toggle = screen.getByRole("button", { name: "收起章节目录" });
    expect(toggle).not.toHaveTextContent("收起章节目录");
    await user.click(toggle);

    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("keeps skipped chapters clickable without a model status label", () => {
    render(
      <ChapterSidebar
        bookId="keynes"
        chapters={[
          { id: 1, position: 0, title: "目录", source_start_page: 1, source_end_page: 1, chapter_question: "", one_sentence_conclusion: "", core_idea_titles: [], role_in_book: "", estimated_reading_minutes: 0, generation_status: "skipped", failure_reason: null },
          { id: 2, position: 1, title: "第一章 一般理论", source_start_page: 2, source_end_page: 10, chapter_question: "", one_sentence_conclusion: "", core_idea_titles: [], role_in_book: "", estimated_reading_minutes: 3, generation_status: "ready", failure_reason: null },
        ]}
      />,
    );

    expect(screen.getByRole("link", { name: "目录" })).toHaveAttribute("href", "/books/keynes/chapters/1");
    expect(screen.getByText("第一章 一般理论")).toBeInTheDocument();
    expect(screen.queryByText("未调用模型")).not.toBeInTheDocument();
    expect(document.querySelector(".chapter-tree")).toBeInTheDocument();
    expect(document.querySelector(".chapter-number")).not.toBeInTheDocument();
  });

  it("hides the readable label while retaining an unreadable chapter status", () => {
    render(
      <ChapterSidebar
        bookId="keynes"
        chapters={[
          { id: 1, position: 0, title: "第一章", source_start_page: 1, source_end_page: 1, chapter_question: "", one_sentence_conclusion: "", core_idea_titles: [], role_in_book: "", estimated_reading_minutes: 3, generation_status: "ready", failure_reason: null },
          { id: 2, position: 1, title: "第二章", source_start_page: 2, source_end_page: 2, chapter_question: "", one_sentence_conclusion: "", core_idea_titles: [], role_in_book: "", estimated_reading_minutes: 3, generation_status: "failed", failure_reason: "生成中断" },
        ]}
      />,
    );

    expect(screen.queryByText("可阅读")).not.toBeInTheDocument();
    expect(screen.getByText("生成失败")).toBeInTheDocument();
  });

  it("keeps body chapters and their parts while filtering both legacy and classified non-body entries", () => {
    const item = {
      position: 0, source_start_page: 1, source_end_page: 1, chapter_question: "",
      one_sentence_conclusion: "", core_idea_titles: [], role_in_book: "",
      estimated_reading_minutes: 0, generation_status: "skipped" as const, failure_reason: null,
    };
    render(<ChapterSidebar bookId="book" bodyOnly chapters={[
      { ...item, id: 1, title: "致谢", structural_role: "front_matter" },
      { ...item, id: 2, title: "序言" },
      { ...item, id: 3, title: "上篇", nav_kind: "part", analysis_role: "outline_only" },
      { ...item, id: 4, title: "第一章", structural_role: "body", parent_title: "上篇", nav_kind: "chapter" },
      { ...item, id: 5, title: "结语：回望", structural_role: "back_matter", parent_title: "上篇", nav_kind: "chapter" },
    ]} />);

    expect(screen.getByRole("link", { name: "上篇" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /第一章/ })).toBeInTheDocument();
    expect(screen.queryByText("致谢")).not.toBeInTheDocument();
    expect(screen.queryByText("序言")).not.toBeInTheDocument();
    expect(screen.queryByText("结语：回望")).not.toBeInTheDocument();
  });

  it("opens a branch when its active child changes and still lets the reader close it", async () => {
    const user = userEvent.setup();
    const chapters = [
      { id: 1, position: 0, title: "第一章", source_start_page: 1, source_end_page: 1, chapter_question: "", one_sentence_conclusion: "", core_idea_titles: [], role_in_book: "", estimated_reading_minutes: 3, generation_status: "ready" as const, failure_reason: null, nav_kind: "chapter", depth: 1 },
      { id: 2, position: 1, title: "第一节", source_start_page: 2, source_end_page: 2, chapter_question: "", one_sentence_conclusion: "", core_idea_titles: [], role_in_book: "", estimated_reading_minutes: 3, generation_status: "ready" as const, failure_reason: null, nav_kind: "section", depth: 2, parent_title: "第一章" },
    ];
    const { rerender } = render(<ChapterSidebar bookId="keynes" chapters={chapters} />);
    const toggle = screen.getByRole("button", { name: "展开本章小节" });

    rerender(<ChapterSidebar bookId="keynes" chapters={chapters} activeId={2} />);

    expect(screen.getByRole("button", { name: "收起本章小节" })).toHaveAttribute("aria-expanded", "true");
    await user.click(screen.getByRole("button", { name: "收起本章小节" }));
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("renders nested sections below chapters inside an outline-only part", async () => {
    const user = userEvent.setup();
    render(
      <ChapterSidebar
        bookId="keynes"
        linkMode="anchor"
        chapters={[
          { id: 1, position: 0, title: "上篇", source_start_page: 1, source_end_page: 1, chapter_question: "", one_sentence_conclusion: "", core_idea_titles: [], role_in_book: "", estimated_reading_minutes: 0, generation_status: "skipped", failure_reason: null, nav_kind: "part", analysis_role: "outline_only" },
          { id: 2, position: 1, title: "第一章", source_start_page: 1, source_end_page: 1, chapter_question: "", one_sentence_conclusion: "", core_idea_titles: [], role_in_book: "", estimated_reading_minutes: 3, generation_status: "ready", failure_reason: null, nav_kind: "chapter", depth: 1, parent_title: "上篇" },
          { id: 3, position: 2, title: "第一节", source_start_page: 1, source_end_page: 1, chapter_question: "", one_sentence_conclusion: "", core_idea_titles: [], role_in_book: "", estimated_reading_minutes: 3, generation_status: "ready", failure_reason: null, nav_kind: "section", depth: 2, parent_title: "第一章" },
        ]}
      />,
    );

    expect(screen.getByRole("link", { name: "上篇" })).toHaveAttribute("href", "#chapter-1");
    expect(screen.getByRole("link", { name: "第一章" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "展开本章小节" }));
    expect(screen.getByRole("link", { name: "第一节" })).toBeInTheDocument();
  });
});
