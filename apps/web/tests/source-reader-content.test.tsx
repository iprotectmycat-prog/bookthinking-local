import { render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../components/EpubReader", () => ({
  EpubReader: ({ data, locator, quote, surroundingText }: {
    data: ArrayBuffer;
    locator: import("../lib/types").EpubLocator;
    quote?: string | null;
    surroundingText?: string | null;
  }) => (
    <div
      data-testid="epub-result"
      data-bytes={data.byteLength}
      data-locator={[locator.href, locator.fragment].filter(Boolean).join("#")}
      data-quote={quote || ""}
      data-surrounding-text={surroundingText || ""}
    />
  ),
}));

vi.mock("../components/PdfReader", () => ({
  PdfReader: ({ data, page }: { data: ArrayBuffer; page: number }) => (
    <div data-testid="pdf-result" data-bytes={data.byteLength} data-page={page} />
  ),
}));

import { SourceReaderContent } from "../components/SourceReaderContent";

afterEach(() => vi.unstubAllGlobals());

describe("SourceReaderContent", () => {
  it("fetches the protected EPUB endpoint into memory", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      arrayBuffer: () => Promise.resolve(new Uint8Array([1, 2, 3]).buffer),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <StrictMode>
        <SourceReaderContent
          bookId="book-1"
          target={{
            format: "epub",
            locator: { href: "OEBPS/text00004.html", fragment: "bubble", cfi: null, spineIndex: 3 },
            quote: "原文",
            surroundingText: "上下文",
            requestId: 1,
          }}
        />
      </StrictMode>,
    );

    await waitFor(() => expect(screen.getByTestId("epub-result")).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith("/local/books/book-1/file");
    expect(screen.getByTestId("epub-result")).toHaveAttribute("data-bytes", "3");
    expect(screen.getByTestId("epub-result")).toHaveAttribute("data-locator", "OEBPS/text00004.html#bubble");
    expect(screen.getByTestId("epub-result")).toHaveAttribute("data-quote", "原文");
    expect(screen.getByTestId("epub-result")).toHaveAttribute("data-surrounding-text", "上下文");
  });

  it("keeps a source failure inside the reading surface", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false }));

    render(
      <SourceReaderContent
        bookId="book-1"
        target={{ format: "pdf", page: 2, quote: "原文", requestId: 1 }}
      />,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("原书文件无法加载");
  });
});
