import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { BookLibrary } from "../components/BookLibrary";

describe("BookLibrary", () => {
  it("links every analyzed book and marks the current one", () => {
    render(
      <BookLibrary
        currentBookId="keynes"
        books={[
          { id: "btc", filename: "bitcoin_zh_cn.pdf", source_format: "pdf", access_scope: "owned" },
          { id: "keynes", filename: "就业、利息和货币通论 (约翰·凯恩斯（John Maynard Keynes）) (Z-Library).epub", source_format: "epub", access_scope: "owned" },
        ]}
      />
    );

    expect(screen.getByRole("heading", { name: "已分析书籍" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "BTC PDF" })).toHaveAttribute("href", "/books/btc/overview");
    expect(screen.getByRole("link", { name: "就业、利息和货币通论 EPUB" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByText("EPUB")).toBeInTheDocument();
  });

  it("shows a long book as a title with author and format metadata", () => {
    render(
      <BookLibrary
        currentBookId="keynes"
        books={[
          { id: "keynes", filename: "就业、利息和货币通论 (约翰·凯恩斯（John Maynard Keynes）) (Z-Library).epub", source_format: "epub", access_scope: "owned" },
        ]}
      />
    );

    expect(screen.getByText("就业、利息和货币通论")).toHaveClass("book-title");
    expect(screen.getByText(/约翰·凯恩斯（John Maynard Keynes）/)).toHaveClass("book-metadata");
    expect(screen.getByText(/EPUB/).closest(".book-metadata")).toBeInTheDocument();
  });

  it("lets the page hide an analyzed book without calling a data-deletion API", async () => {
    const user = userEvent.setup();
    const onDismissBook = vi.fn();
    render(<BookLibrary currentBookId="" books={[{ id: "btc", filename: "bitcoin_zh_cn.pdf", source_format: "pdf", access_scope: "owned" }]} onDismissBook={onDismissBook} />);

    await user.click(screen.getByRole("button", { name: "从当前页面隐藏 BTC" }));
    expect(onDismissBook).toHaveBeenCalledWith("btc");
  });
});
