import { render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ChapterReadingView } from "../components/ChapterReadingView";
import { AnalysisStatus } from "../components/AnalysisStatus";

const stylesheet = readFileSync("app/globals.css", "utf8");

const fixtureAnalysis = {
  book_id: "book-1", chapter_id: 1, title: "第一章", source_start_page: 1, source_end_page: 3,
  chapter_question: "本章如何建立可信结论？", one_sentence_conclusion: "结论必须由原文证据支持。", short_summary: "本章解释证据与结论之间的关系。",
  argument_chain: [{ text: "提出问题", content_type: "book_summary" as const, sources: [] }], role_in_book: { text: "建立全书的方法基础", content_type: "book_summary" as const, sources: [] }, estimated_reading_minutes: 3,
  generation_status: "ready" as const, failure_reason: null, previous_chapter_id: null, next_chapter_id: 2,
  core_ideas: [
    { id: 1, position: 0, title: "证据优先", conclusion: "核心结论必须可回查。", importance: "避免无依据推断。", explanation: "先核对原文，再展示作者观点。", reasoning_steps: ["定位原文", "核对页码"], examples: [], caveats: ["AI 解释不等于作者原话。"], relations: [], content_type: "book_claim" as const, confidence: 0.95, sources: [{ id: 1, source_page: 1, quote: "作者用可回查的原文建立可信结论。", surrounding_text: "", verification_status: "verified" }], },
    { id: 2, position: 1, title: "解释边界", conclusion: "AI 解析需要单独标记。", importance: "区分原书与模型。", explanation: "第二项详细解析。", reasoning_steps: ["识别类型", "明确标签"], examples: [], caveats: [], relations: [], content_type: "ai_explanation" as const, confidence: 0.8, sources: [] },
  ],
};

describe("ChapterReadingView", () => {
  it("uses the explanation body typography for every core-idea text layer", () => {
    const primaryTextRule = stylesheet.match(/\.idea-lead, \.idea-explain, \.idea-why\s*\{[^}]*\}/)?.[0];

    expect(primaryTextRule).toEqual(expect.stringMatching(/color:\s*var\(--ink\)/));
    expect(primaryTextRule).toEqual(expect.stringMatching(/font:\s*400 16px\/1\.9 Georgia, "Songti SC", serif/));
  });

  it("shows the chapter summary for older analyses", () => {
    render(<ChapterReadingView analysis={fixtureAnalysis} onOpenSource={vi.fn()} />);
    const title = screen.getByRole("heading", { name: "第一章", level: 1 });
    expect(title.nextElementSibling).toHaveTextContent(fixtureAnalysis.one_sentence_conclusion);
    expect(screen.queryByRole("heading", { name: "本章总结" })).not.toBeInTheDocument();
  });

  it("shows each idea's primary interpretation by default", () => {
    render(<ChapterReadingView analysis={fixtureAnalysis} onOpenSource={vi.fn()} />);
    expect(screen.getByText(fixtureAnalysis.core_ideas[0].explanation)).toBeVisible();
    expect(screen.getByText(fixtureAnalysis.core_ideas[1].explanation)).toBeVisible();
  });

  it("keeps the book role separate and the older argument chain under the core ideas", () => {
    render(<ChapterReadingView analysis={fixtureAnalysis} onOpenSource={vi.fn()} />);

    const roleHeading = screen.getByRole("heading", { name: "本章在全书中的作用", level: 2 });
    expect(roleHeading.closest("section")).toHaveClass("role-in-book-section");
    expect(screen.getByText("查看本章论证").closest(".chapter-section")).toContainElement(
      screen.getByRole("heading", { name: "核心观点" }),
    );
  });

  it("opens an evidence source in the in-page reader", async () => {
    const user = userEvent.setup();
    const onOpenSource = vi.fn();
    render(<ChapterReadingView analysis={fixtureAnalysis} onOpenSource={onOpenSource} />);

    await user.click(screen.getByRole("button", { name: "在原书中阅读" }));

    expect(onOpenSource).toHaveBeenCalledWith(expect.objectContaining({
      source_page: 1,
      quote: "作者用可回查的原文建立可信结论。",
    }), screen.getByRole("button", { name: "在原书中阅读" }));
    expect(screen.queryByText("已回查")).not.toBeInTheDocument();
  });
});

describe("AnalysisStatus", () => {
  it("labels source fragments that did not call the model", () => {
    render(<AnalysisStatus status="skipped" />);
    expect(screen.getByText("未调用模型")).toBeInTheDocument();
  });
});
