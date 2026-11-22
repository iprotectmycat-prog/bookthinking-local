import { readFileSync } from "node:fs";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CoreIdeaSection } from "../components/CoreIdeaSection";
import type { CoreIdea } from "../lib/types";

const stylesheet = readFileSync("app/globals.css", "utf8");

function coreIdea(overrides: Partial<CoreIdea> = {}): CoreIdea {
  return {
    id: 1,
    position: 0,
    title: "规模会拖慢创新",
    conclusion: "组织越大，单位创新效率越低。",
    importance: "决定扩张节奏。",
    explanation: "说明。",
    reasoning_steps: ["比较专利产出"],
    examples: [],
    caveats: [],
    relations: [],
    content_type: "book_claim",
    confidence: 0.8,
    sources: [],
    ...overrides,
  };
}

describe("CoreIdeaSection", () => {
  it("prefixes the idea importance with a plain meaning label", () => {
    render(<CoreIdeaSection idea={coreIdea({ importance: "这是经济学存在的基础。" })} number={1} onOpenSource={vi.fn()} />);

    const importance = screen.getByText("意义：这是经济学存在的基础。");
    expect(importance).toHaveClass("idea-why");
    expect(screen.queryByLabelText("本章在全书意义")).toBeNull();
  });

  it("does not add a special visual container for the importance", () => {
    expect(stylesheet).not.toMatch(/\.idea-meaning-note\s*\{/);
  });

  it("labels cross-chapter synthesis as AI and groups its evidence by origin chapter", () => {
    render(
      <CoreIdeaSection
        idea={coreIdea({
          content_type: "ai_synthesis",
          sources: [
            { id: 1, source_page: 18, quote: "当前节原文。", surrounding_text: "", verification_status: "verified", source_chapter_id: 1, source_chapter_title: "第一节 分税制改革" },
            { id: 2, source_page: 19, quote: "后续节原文。", surrounding_text: "", verification_status: "verified", source_chapter_id: 2, source_chapter_title: "第二节 土地财政" },
          ],
        })}
        number={1}
        onOpenSource={vi.fn()}
      />,
    );

    expect(screen.getByText("AI 推导")).toBeTruthy();
    expect(screen.getByText("第一节 分税制改革")).toBeTruthy();
    expect(screen.getByText("第二节 土地财政")).toBeTruthy();
  });

  it("labels AI-added boundaries separately from the author's own", async () => {
    const user = userEvent.setup();
    render(
      <CoreIdeaSection
        idea={coreIdea({
          author_caveats: ["只适用于制造业"],
          ai_caveats: ["样本仅覆盖发达国家"],
        })}
        number={1}
        onOpenSource={vi.fn()}
      />,
    );

    await user.click(screen.getByText("论证 · 案例 · 边界"));

    expect(screen.getByText("作者说明的边界")).toBeTruthy();
    expect(screen.getByText("只适用于制造业")).toBeTruthy();
    expect(screen.getByText("需要注意的限制")).toBeTruthy();
    expect(screen.getByText("由 AI 补充，作者未提到")).toBeTruthy();
  });

  it("shows the warrant as an AI inference, never as something the author wrote", async () => {
    const user = userEvent.setup();
    render(
      <CoreIdeaSection
        idea={coreIdea({ warrant: "假定专利数可代表创新水平" })}
        number={1}
        onOpenSource={vi.fn()}
      />,
    );

    await user.click(screen.getByText("论证 · 案例 · 边界"));

    expect(screen.getByText("这个论证依赖的隐含前提")).toBeTruthy();
    expect(screen.getByText("假定专利数可代表创新水平")).toBeTruthy();
    expect(screen.getByText("由 AI 识别，作者未明说")).toBeTruthy();
  });

  it("falls back to the legacy combined caveats so older books still show boundaries", async () => {
    const user = userEvent.setup();
    render(
      <CoreIdeaSection
        idea={coreIdea({ caveats: ["旧版合并字段"] })}
        number={1}
        onOpenSource={vi.fn()}
      />,
    );

    await user.click(screen.getByText("论证 · 案例 · 边界"));

    expect(screen.getByText("作者说明的边界")).toBeTruthy();
    expect(screen.getByText("旧版合并字段")).toBeTruthy();
  });

  it("hides the details block when an idea has no supporting material at all", () => {
    render(<CoreIdeaSection idea={coreIdea({ reasoning_steps: [] })} number={1} onOpenSource={vi.fn()} />);

    expect(screen.queryByText("论证 · 案例 · 边界")).toBeNull();
  });
});

describe("CoreIdeaSection genre fields", () => {
  it("shows the fields belonging to the book's argument structure", async () => {
    const user = userEvent.setup();
    render(
      <CoreIdeaSection
        idea={coreIdea({ genre_fields: { grounds_type: "empirical", scope_condition: "仅限成熟市场" } })}
        number={1}
        genre="propositional"
        onOpenSource={vi.fn()}
      />,
    );

    await user.click(screen.getByText("论证 · 案例 · 边界"));

    expect(screen.getByText("论据类型")).toBeTruthy();
    expect(screen.getByText("实证数据")).toBeTruthy();
    expect(screen.getByText("仅限成熟市场")).toBeTruthy();
  });

  it("renders action steps as an ordered list", async () => {
    const user = userEvent.setup();
    render(
      <CoreIdeaSection
        idea={coreIdea({ genre_fields: { action_steps: ["列出待办", "删掉无关项"] } })}
        number={1}
        genre="practical"
        onOpenSource={vi.fn()}
      />,
    );

    await user.click(screen.getByText("论证 · 案例 · 边界"));

    const steps = screen.getAllByRole("listitem").map((item) => item.textContent);
    expect(steps).toContain("列出待办");
    expect(steps).toContain("删掉无关项");
  });

  it("shows no genre section when the analysis predates genre detection", async () => {
    // Books analysed before this feature have no genre and no genre_fields; the
    // details block must not gain an empty section for them.
    const user = userEvent.setup();
    render(<CoreIdeaSection idea={coreIdea()} number={1} onOpenSource={vi.fn()} />);

    await user.click(screen.getByText("论证 · 案例 · 边界"));

    expect(screen.queryByText("论据类型")).toBeNull();
  });
});
