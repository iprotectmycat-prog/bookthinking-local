import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ChapterSidebar } from "../components/ChapterSidebar";

describe("ChapterSidebar responsive controls", () => {
  it("starts collapsed and lets a narrower desktop viewport open the sidebar", async () => {
    const user = userEvent.setup();
    render(<ChapterSidebar bookId="book-1" chapters={[]} />);

    const toggle = screen.getByRole("button", { name: "展开章节侧栏" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByLabelText("章节目录")).toHaveClass("is-open");
  });

  it("provides a bounded resize handle for customizing the desktop sidebar width", () => {
    render(<ChapterSidebar bookId="book-1" chapters={[]} />);

    const handle = screen.getByRole("separator", { name: "调整侧边栏宽度" });
    expect(handle).toHaveAttribute("aria-valuemin", "200");
    expect(handle).toHaveAttribute("aria-valuemax", "340");
  });
});
