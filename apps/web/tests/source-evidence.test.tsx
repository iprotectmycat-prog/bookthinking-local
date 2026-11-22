import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SourceEvidence } from "../components/SourceEvidence";

describe("SourceEvidence", () => {
  it("opens EPUB evidence in the current page instead of linking away", async () => {
    const user = userEvent.setup();
    const onOpenSource = vi.fn();
    render(
      <SourceEvidence
        source={{
          id: 1,
          source_page: 2,
          quote: "原文",
          surrounding_text: "",
          verification_status: "verified",
        }}
        sourceFormat="epub"
        onOpenSource={onOpenSource}
      />,
    );

    const trigger = screen.getByRole("button", { name: "在原书中阅读" });
    await user.click(trigger);

    expect(onOpenSource).toHaveBeenCalledWith({
      id: 1,
      source_page: 2,
      quote: "原文",
      surrounding_text: "",
      verification_status: "verified",
    }, trigger);
    expect(screen.queryByRole("link", { name: "在原书中阅读" })).not.toBeInTheDocument();
  });
});
