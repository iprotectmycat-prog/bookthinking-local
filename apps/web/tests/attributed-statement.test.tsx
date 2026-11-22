import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AttributedStatement } from "../components/AttributedStatement";

describe("AttributedStatement", () => {
  it("labels a cross-chapter statement as AI and shows both source chapters", () => {
    render(
      <AttributedStatement
        label="本章在全书中的作用"
        sourceFormat="pdf"
        onOpenSource={vi.fn()}
        statement={{
          text: "为后续土地财政提供制度起点。",
          content_type: "ai_synthesis",
          sources: [
            { id: 1, source_page: 18, quote: "当前节原文。", surrounding_text: "", verification_status: "verified", source_chapter_id: 16, source_chapter_title: "第一节 分税制改革" },
            { id: 2, source_page: 19, quote: "后续节原文。", surrounding_text: "", verification_status: "verified", source_chapter_id: 17, source_chapter_title: "第二节 土地财政" },
          ],
        }}
      />,
    );

    expect(screen.getByText("AI 推导")).toBeTruthy();
    expect(screen.getByText("第一节 分税制改革")).toBeTruthy();
    expect(screen.getByText("第二节 土地财政")).toBeTruthy();
  });
});
