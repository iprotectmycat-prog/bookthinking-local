import { render, screen, fireEvent } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { SkillChapterReading } from "../components/SkillChapterReading";

it("shows the complete process and opens its original source", () => {
  const open = vi.fn();
  render(<SkillChapterReading record={{ protocol: "skill-v1", reading_route: "展开路线", gaps: [],
    units: [{ title: "完整流程", content_kind: "process", explanation: "机制解释", steps: Array.from({ length: 8 }, (_, i) => `步骤${i + 1}`),
      examples: [], limitations: [], gaps: [], sources: [{ id: 1, source_page: 3, quote: "原书证据", surrounding_text: "上下文", verification_status: "verified" }] }],
    conclusion_sources: [], support_review: "模型自检" }} sourceFormat="epub" onOpenSource={open} />);
  expect(screen.getByText("步骤8")).toBeInTheDocument();
  const sourceButton = screen.getByRole("button", { name: "在原书中阅读" });
  fireEvent.click(sourceButton);
  expect(open).toHaveBeenCalledWith(expect.objectContaining({ quote: "原书证据" }), sourceButton);
});
