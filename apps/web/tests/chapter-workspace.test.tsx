import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("../components/SourceReaderContent", () => ({
  SourceReaderContent: ({ target }: { target: import("../lib/types").SourceReaderTarget }) => (
    <p
      data-testid="reader-target"
      data-format={target.format}
      data-locator={target.format === "epub"
        ? [target.locator.href, target.locator.fragment].filter(Boolean).join("#")
        : String(target.page)}
      data-quote={target.quote || ""}
    />
  ),
}));

import { ChapterWorkspace } from "../components/ChapterWorkspace";

const workspaceFixture = {
  bookId: "book-1",
  sourceFormat: "epub" as const,
  books: [],
  chapters: [
    {
      id: 1,
      position: 0,
      title: "第一章",
      source_start_page: 1,
      source_end_page: 3,
      chapter_question: "本章如何建立可信结论？",
      one_sentence_conclusion: "结论必须由原文证据支持。",
      core_idea_titles: ["证据优先"],
      role_in_book: "建立全书的方法基础",
      estimated_reading_minutes: 3,
      generation_status: "ready" as const,
      failure_reason: null,
    },
  ],
  analysis: {
    book_id: "book-1",
    chapter_id: 1,
    title: "第一章",
    source_start_page: 1,
    source_end_page: 3,
    source_locator: "OEBPS/text00001.html#chapter-one",
    chapter_question: "本章如何建立可信结论？",
    one_sentence_conclusion: "结论必须由原文证据支持。",
    short_summary: "本章解释证据与结论之间的关系。",
    argument_chain: [{ text: "提出问题", content_type: "book_summary" as const, sources: [] }],
    role_in_book: { text: "建立全书的方法基础", content_type: "book_summary" as const, sources: [] },
    estimated_reading_minutes: 3,
    generation_status: "ready" as const,
    failure_reason: null,
    previous_chapter_id: null,
    next_chapter_id: 2,
    core_ideas: [
      {
        id: 1,
        position: 0,
        title: "证据优先",
        conclusion: "核心结论必须可回查。",
        importance: "避免无依据推断。",
        explanation: "先核对原文，再展示作者观点。",
        reasoning_steps: ["定位原文", "核对页码"],
        examples: [],
        caveats: [],
        relations: [],
        content_type: "book_claim" as const,
        confidence: 0.95,
        sources: [
          {
            id: 1,
            source_page: 1,
            quote: "作者用可回查的原文建立可信结论。",
            surrounding_text: "",
            verification_status: "verified",
            source_locator: "OEBPS/text00004.html#bubble",
          },
        ],
      },
    ],
  },
};

describe("ChapterWorkspace", () => {
  it("does not reserve a right source rail before the reader is opened", () => {
    render(<ChapterWorkspace {...workspaceFixture} />);

    expect(document.querySelector(".source-reader-panel")).not.toBeInTheDocument();
    expect(document.querySelector(".chapter-workspace")).not.toHaveClass("is-source-collapsed");
  });

  it("collapses only the chapter directory", async () => {
    const user = userEvent.setup();
    render(<ChapterWorkspace {...workspaceFixture} />);

    await user.click(screen.getByRole("button", { name: "收起章节目录" }));

    expect(screen.getByRole("button", { name: "展开章节目录" })).toBeVisible();
    expect(screen.getByRole("main")).toBeVisible();
    expect(document.querySelector(".chapter-workspace")).toHaveClass("is-directory-collapsed");
  });

  it("keeps analysis visible while the source panel closes and restores its last target", async () => {
    const user = userEvent.setup();
    render(<ChapterWorkspace {...workspaceFixture} />);
    const chapterActions = within(screen.getByRole("navigation", { name: "章节操作" }));

    expect(screen.getByRole("main")).toBeVisible();
    expect(chapterActions.getByRole("button", { name: "阅读原文" })).toBeVisible();
    const trigger = chapterActions.getByRole("button", { name: "阅读原文" });
    await user.click(trigger);
    expect(screen.getByLabelText("原书阅读器")).toHaveTextContent("章节片段 1");
    expect(screen.getByLabelText("原书阅读器")).toHaveClass("source-reader-panel-content");
    expect(screen.getByRole("button", { name: "收起原书阅读器" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByLabelText("原书阅读器")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    expect(screen.getByRole("main")).toBeVisible();
    await user.click(chapterActions.getByRole("button", { name: "阅读原文" }));
    expect(screen.getByLabelText("原书阅读器")).toHaveTextContent("章节片段 1");
  });

  it("opens the source reader from the chapter actions instead of linking to settings", async () => {
    const user = userEvent.setup();
    render(<ChapterWorkspace {...workspaceFixture} />);

    expect(screen.queryByRole("link", { name: "模型设置" })).not.toBeInTheDocument();
    await user.click(within(screen.getByRole("navigation", { name: "章节操作" })).getByRole("button", { name: "阅读原文" }));

    expect(screen.getByLabelText("原书阅读器")).toHaveTextContent("章节片段 1");
  });

  it("passes the selected evidence locator, quote, and context into the EPUB reader target", async () => {
    const user = userEvent.setup();
    render(<ChapterWorkspace {...workspaceFixture} />);

    await user.click(screen.getByRole("button", { name: "在原书中阅读" }));

    expect(screen.getByTestId("reader-target")).toHaveAttribute("data-format", "epub");
    expect(screen.getByTestId("reader-target")).toHaveAttribute("data-locator", "OEBPS/text00004.html#bubble");
    expect(screen.getByTestId("reader-target")).toHaveAttribute(
      "data-quote",
      "作者用可回查的原文建立可信结论。",
    );
  });

  it("uses the chapter locator when opening the chapter source", async () => {
    const user = userEvent.setup();
    render(<ChapterWorkspace {...workspaceFixture} />);

    await user.click(within(screen.getByRole("navigation", { name: "章节操作" })).getByRole("button", { name: "阅读原文" }));

    expect(screen.getByTestId("reader-target")).toHaveAttribute("data-format", "epub");
    expect(screen.getByTestId("reader-target")).toHaveAttribute("data-locator", "OEBPS/text00001.html#chapter-one");
    expect(screen.getByTestId("reader-target")).toHaveAttribute("data-quote", "");
  });
});

it("opens only the source mapped to the selected sentence and returns focus to the marker", async () => {
  const user = userEvent.setup();
  const source = workspaceFixture.analysis.core_ideas[0].sources[0];
  const otherSource = { ...source, id: 2, quote: "另一处原文", source_locator: "OEBPS/second.html" };
  render(<ChapterWorkspace {...workspaceFixture} analysis={{
    ...workspaceFixture.analysis,
    reading_record: {
      protocol: "skill-v1",
      reading_route: "",
      units: [],
      conclusion_sources: [],
      gaps: ["仅内部使用的分析缺口"],
      support_review: "仅内部使用的核对说明",
      teaching: {
        chapter_summary: "先说明本章聚焦的问题。",
        topics: [{
          title: "证据优先",
          key_understanding: "证据是理解的基础。",
          explanation: "先核对原文。\n\n再解释作者观点。",
          sources: [source, otherSource],
          citations: [
            { anchor: "先核对原文。", sources: [source] },
            { anchor: "再解释作者观点。", sources: [otherSource] },
          ],
        }],
      },
    },
  }} />);

  const title = screen.getByRole("heading", { name: "第一章", level: 1 });
  expect(title.nextElementSibling).toHaveTextContent("先说明本章聚焦的问题。");
  expect(screen.queryByText("分析范围与核对说明")).not.toBeInTheDocument();
  expect(screen.queryByText("仅内部使用的分析缺口")).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /返回总览/ })).not.toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "核心观点" })).toBeVisible();
  const firstMarker = screen.getByRole("button", { name: "查看引用 1 的原文" });
  const marker = screen.getByRole("button", { name: "查看引用 2 的原文" });
  expect(firstMarker.closest("p")?.nextElementSibling).toBe(marker.closest("p"));
  await user.click(marker);
  expect(screen.getByTestId("reader-target")).toHaveAttribute("data-locator", "OEBPS/second.html");
  expect(screen.getByTestId("reader-target")).toHaveAttribute("data-quote", "另一处原文");
  await user.keyboard("{Escape}");
  expect(screen.queryByLabelText("原书阅读器")).not.toBeInTheDocument();
  expect(marker).toHaveFocus();
});
