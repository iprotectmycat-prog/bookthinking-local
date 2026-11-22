import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("../components/SourceReaderContent", () => ({
  SourceReaderContent: () => <p data-testid="reader-target" />,
}));

import { ChapterWorkspace } from "../components/ChapterWorkspace";
import type { AnalysisStatus, ChapterAnalysis, ChapterOverview } from "../lib/types";

const PYDANTIC_LEAK =
  "模型返回的章节分析结构无效：1 validation error for ChapterAnalysisDraft role_in_book " +
  "Field required [type=missing, input_value={'chapter_question': '中美贸易…'}, input_type=dict]";

function overviewChapter(id: number, title: string, status: AnalysisStatus): ChapterOverview {
  return {
    id,
    position: id,
    title,
    source_start_page: id,
    source_end_page: id,
    chapter_question: "",
    one_sentence_conclusion: "",
    core_idea_titles: [],
    role_in_book: "",
    estimated_reading_minutes: 3,
    generation_status: status,
    failure_reason: null,
  };
}

// 《置身事内》真实结构：目录（skipped）紧邻前言，之后是只有标题的「上篇」。
const chapters = [
  overviewChapter(3, "目录", "skipped"),
  overviewChapter(4, "前言 从了解现状开始", "ready"),
  overviewChapter(5, "上篇 微观机制", "skipped"),
  overviewChapter(6, "第一章 地方政府的权力与事务", "ready"),
  overviewChapter(7, "第二节 中美贸易冲突", "failed"),
];

function analysis(chapterId: number, status: AnalysisStatus, failureReason: string | null = null): ChapterAnalysis {
  const source = chapters.find((item) => item.id === chapterId)!;
  const ready = status === "ready";
  return {
    book_id: "book-1",
    chapter_id: chapterId,
    title: source.title,
    source_start_page: chapterId,
    source_end_page: chapterId,
    chapter_question: ready ? "本章要回答什么？" : "",
    one_sentence_conclusion: ready ? "一句话结论。" : "",
    short_summary: ready ? "摘要。" : "",
    argument_chain: [],
    role_in_book: ready ? { text: "承接全书", content_type: "book_summary" as const, sources: [] } : null,
    estimated_reading_minutes: 3,
    generation_status: status,
    failure_reason: failureReason,
    // 后端按序号直接取相邻项，会指向没有正文的结构页。
    previous_chapter_id: chapterId === 4 ? 3 : chapterId - 1,
    next_chapter_id: chapterId === 4 ? 5 : chapterId + 1,
    core_ideas: [],
  };
}

const base = { bookId: "book-1", sourceFormat: "epub" as const, chapters };

describe("ChapterWorkspace 失败与结构页", () => {
  it("offers a retry button on a failed chapter page", async () => {
    const onRetry = vi.fn();
    render(<ChapterWorkspace {...base} analysis={analysis(7, "failed", PYDANTIC_LEAK)} onRetry={onRetry} />);

    // 修复前这个页面只有标题和一个红点，读者无处可去。
    const retry = screen.getByRole("button", { name: "重新分析本章" });
    await userEvent.setup().click(retry);

    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("does not offer a retry button when the chapter is platform read only", () => {
    render(<ChapterWorkspace {...base} analysis={analysis(7, "failed")} />);

    expect(screen.queryByRole("button", { name: "重新分析本章" })).not.toBeInTheDocument();
  });

  it("never shows the raw pydantic error as body text", () => {
    render(<ChapterWorkspace {...base} analysis={analysis(7, "failed", PYDANTIC_LEAK)} onRetry={vi.fn()} />);

    const message = document.querySelector(".chapter-state-message");
    expect(message?.textContent ?? "").not.toContain("validation error");
    expect(message?.textContent ?? "").not.toContain("input_value");
    // 细节仍可展开查看，不丢排查信息。
    expect(document.querySelector(".failure-detail pre")?.textContent).toContain("validation error");
  });

  it("explains why a structural page has no analysis and offers a way out", () => {
    render(<ChapterWorkspace {...base} analysis={analysis(3, "skipped")} onRetry={vi.fn()} />);

    expect(document.querySelector(".chapter-state-message")?.textContent).toContain("结构页");
    // skipped 不该给重试按钮 —— 它没有正文，重试也不会有结果。
    expect(screen.queryByRole("button", { name: "重新分析本章" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /跳到下一个可阅读章节/ })).toHaveAttribute(
      "href",
      "/books/book-1/chapters/4",
    );
  });

  it("skips structural pages in the previous/next navigation", () => {
    render(<ChapterWorkspace {...base} analysis={analysis(4, "ready")} onRetry={vi.fn()} />);
    const pagination = within(screen.getByRole("navigation", { name: "前后章节" }));

    // 后端给的 next 是 5（「上篇 微观机制」，无正文），应跨到第一章。
    expect(pagination.getByRole("link", { name: /下一章/ })).toHaveAttribute(
      "href",
      "/books/book-1/chapters/6",
    );
    // 后端给的 previous 是 3（目录），前面已无可读章节，不应给出链接。
    expect(pagination.queryByRole("link", { name: /上一章/ })).not.toBeInTheDocument();
  });

  it("shows a disabled retry state while the request is in flight", () => {
    render(<ChapterWorkspace {...base} analysis={analysis(7, "failed")} onRetry={vi.fn()} retrying />);

    expect(screen.getByRole("button", { name: "正在重新分析…" })).toBeDisabled();
  });
});
