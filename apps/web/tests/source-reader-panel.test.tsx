import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../components/SourceReaderContent", () => ({
  SourceReaderContent: () => <p>原文内容</p>,
}));

import { SourceReaderPanel } from "../components/SourceReaderPanel";

describe("SourceReaderPanel", () => {
  afterEach(() => {
    document.documentElement.style.removeProperty("--workspace-source-width");
  });

  it("resizes the source reader panel by dragging its left divider", () => {
    render(
      <SourceReaderPanel
        bookId="book-1"
        target={{
          format: "epub",
          locator: { href: "OEBPS/text00001.html", fragment: null, cfi: null, spineIndex: 0 },
          quote: null,
          surroundingText: null,
          requestId: 1,
        }}
        isOpen
        onClose={() => undefined}
      />,
    );

    const divider = screen.getByRole("separator", { name: "调整原文栏宽度" });
    fireEvent.pointerDown(divider, { clientX: 700 });
    fireEvent.pointerMove(window, { clientX: 600 });
    fireEvent.pointerUp(window);

    expect(document.documentElement.style.getPropertyValue("--workspace-source-width")).toBe("660px");
  });
});
