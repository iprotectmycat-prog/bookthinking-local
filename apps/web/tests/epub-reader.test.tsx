import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { loadReaderState, saveReaderProgress } from "../lib/epub-reader-storage";

const { reactReader, rendition, readerContents } = vi.hoisted(() => {
  const contents = {
    window: {
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    },
    document,
    cfiFromRange: vi.fn(() => "epubcfi(/6/4!/4/1:0)"),
  };
  const readerRendition = {
    on: vi.fn(),
    next: vi.fn(),
    prev: vi.fn(),
    display: vi.fn((_target: string | number) => Promise.resolve()),
    annotations: {
      highlight: vi.fn(),
      remove: vi.fn(),
    },
    getContents: vi.fn(() => [contents]),
    hooks: {
      content: {
        register: vi.fn(),
      },
    },
    themes: {
      register: vi.fn(),
      select: vi.fn(),
      fontSize: vi.fn(),
      override: vi.fn(),
    },
    book: {
      spine: {
        get: vi.fn(() => ({ href: "text00004.html" })),
        each: vi.fn((visit: (section: { href: string; url: string }) => void) => {
          visit({ href: "text00002.html", url: "/OEBPS/text00002.html" });
          visit({ href: "text00004.html", url: "/OEBPS/text00004.html" });
        }),
      },
      navigation: {
        get: vi.fn(() => undefined),
      },
    },
  };

  return {
    readerContents: contents,
    rendition: readerRendition,
    reactReader: vi.fn(({
      url,
      location,
      getRendition,
    }: {
      url: ArrayBuffer;
      location: number | string;
      getRendition?: (value: typeof readerRendition) => void;
    }) => {
      getRendition?.(readerRendition);
      return <div data-testid="react-reader" data-byte-length={url.byteLength} data-location={String(location)} />;
    }),
  };
});

vi.mock("react-reader", () => ({
  ReactReader: reactReader,
  ReactReaderStyle: {
    container: {},
    readerArea: {},
    titleArea: {},
    tocBackground: {},
    tocArea: {},
    toc: {},
    tocAreaButton: {},
    tocButton: {},
    arrow: {},
    arrowHover: {},
  },
}));

import { EpubReader } from "../components/EpubReader";

const locatorAtSpine = (spineIndex: number) => ({
  href: null,
  fragment: null,
  cfi: null,
  spineIndex,
});

describe("EpubReader", () => {
  beforeEach(() => {
    reactReader.mockClear();
    rendition.on.mockClear();
    rendition.next.mockClear();
    rendition.prev.mockClear();
    rendition.display.mockClear();
    rendition.annotations.highlight.mockClear();
    rendition.annotations.remove.mockClear();
    rendition.getContents.mockClear();
    rendition.hooks.content.register.mockClear();
    rendition.themes.register.mockClear();
    rendition.themes.select.mockClear();
    rendition.themes.fontSize.mockClear();
    rendition.themes.override.mockClear();
    rendition.book.spine.get.mockClear();
    readerContents.window.addEventListener.mockClear();
    readerContents.window.removeEventListener.mockClear();
    readerContents.cfiFromRange.mockClear();
    document.body.innerHTML = "<p>有效需求决定就业。</p>";
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("keeps an EPUB selection after focus moves to the composer and sends the exchange on follow-up", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(Response.json({ model: "deepseek-v4-flash", thinking_options: ["off", "low", "high"] }))
      .mockResolvedValueOnce(Response.json({ answer: "作者先区分两种约束。", model: "deepseek-v4-flash", thinking: "先对照前后文。" }))
      .mockResolvedValueOnce(Response.json({ answer: "做事意愿取决于激励。", model: "deepseek-v4-flash" }));
    vi.stubGlobal("fetch", fetchMock);
    render(<EpubReader
      bookId="book-1"
      data={new ArrayBuffer(1)}
      locator={locatorAtSpine(1)}
      discussion={{ chapterSummary: "这一章解释权力运作。" }}
      onError={() => undefined}
    />);

    const range = document.createRange();
    range.selectNodeContents(screen.getByText("有效需求决定就业。"));
    const selected = rendition.on.mock.calls.find(([event]) => event === "selected")?.[1];
    act(() => selected?.("selected-cfi", { range: () => range, document }));
    expect(screen.getByRole("button", { name: "评论或备注" })).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "问 AI" }));
    expect(await screen.findByText("deepseek-v4-flash")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "思考设置" })).not.toBeInTheDocument();
    const input = screen.getByRole("textbox", { name: "向 AI 提问" });
    input.focus();
    fireEvent.change(input, { target: { value: "这段想说明什么？" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    expect(await screen.findByText("作者先区分两种约束。")).toBeInTheDocument();
    expect(screen.getByText("查看思考内容")).toBeInTheDocument();

    fireEvent.change(input, { target: { value: "第二种呢？" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    expect(await screen.findByText("做事意愿取决于激励。")).toBeInTheDocument();
    const [path, request] = fetchMock.mock.calls[2]!;
    expect(path).toBe("/local/books/book-1/source-chat");
    expect(JSON.parse(request.body)).toMatchObject({
      quote: "有效需求决定就业。",
      chapter_summary: "这一章解释权力运作。",
      turns: [{ question: "这段想说明什么？", answer: "作者先区分两种约束。" }],
      question: "第二种呢？",
    });
    expect(rendition.next).not.toHaveBeenCalled();
    expect(rendition.prev).not.toHaveBeenCalled();
  });

  it("restores a saved note and opens it from the marked passage after remount", () => {
    const props = {
      bookId: "note-book",
      data: new ArrayBuffer(1),
      locator: locatorAtSpine(1),
      discussion: { chapterSummary: "" },
      onError: () => undefined,
    };
    const first = render(<EpubReader {...props} />);
    const range = document.createRange();
    range.selectNodeContents(screen.getByText("有效需求决定就业。"));
    const selected = rendition.on.mock.calls.find(([event]) => event === "selected")?.[1];
    act(() => selected?.("note-cfi", { range: () => range, document }));
    fireEvent.click(screen.getByRole("button", { name: "评论或备注" }));
    fireEvent.change(screen.getByRole("textbox", { name: "评论或备注" }), { target: { value: "这里可以联系上一节。" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    first.unmount();
    rendition.annotations.highlight.mockClear();
    render(<EpubReader {...props} />);
    const mark = rendition.annotations.highlight.mock.calls.find(([cfi, , , name]) => cfi === "note-cfi" && name === "source-note-highlight");
    expect(mark).toBeDefined();
    act(() => mark?.[2]());
    expect(screen.getByRole("textbox", { name: "评论或备注" })).toHaveValue("这里可以联系上一节。");
  });

  it("opens the archive-qualified chapter even when the legacy spine index points elsewhere", () => {
    const data = new Uint8Array([1, 2, 3]).buffer;

    render(<EpubReader bookId="book-1" data={data} locator={{ ...locatorAtSpine(1), href: "OEBPS/text00002.html", fragment: "note" }} onError={() => undefined} />);

    expect(screen.getByLabelText("原书 EPUB 阅读器")).toBeInTheDocument();
    expect(screen.getByTestId("react-reader")).toHaveAttribute("data-byte-length", "3");
    expect(screen.getByTestId("react-reader")).toHaveAttribute("data-location", "text00002.html#note");
    expect(reactReader.mock.calls[0]?.[0]).toEqual(
      expect.objectContaining({ url: data, location: 1, showToc: true }),
    );
  });

  it("restores saved CFI only for a standalone opening without an explicit locator", () => {
    saveReaderProgress("book-1", "epubcfi(/6/8!/4/2:0)");

    const { rerender } = render(
      <EpubReader
        bookId="book-1"
        data={new Uint8Array([1, 2, 3]).buffer}
        locator={{ href: null, fragment: null, cfi: null, spineIndex: null }}
        restoreProgress
        onError={() => undefined}
      />,
    );

    expect(screen.getByTestId("react-reader")).toHaveAttribute("data-location", "epubcfi(/6/8!/4/2:0)");

    rerender(
      <EpubReader
        bookId="book-1"
        data={new Uint8Array([1, 2, 3]).buffer}
        locator={{ ...locatorAtSpine(1), href: "OEBPS/text00002.html", fragment: "note" }}
        restoreProgress
        onError={() => undefined}
      />,
    );

    expect(screen.getByTestId("react-reader")).toHaveAttribute("data-location", "text00002.html#note");
  });

  it("uses the correct manager and persists CFI after relocation", () => {
    const data = new Uint8Array([1, 2, 3]).buffer;
    render(<EpubReader bookId="book-1" data={data} locator={locatorAtSpine(1)} onError={() => undefined} />);

    expect(reactReader.mock.calls[0]?.[0]).toEqual(expect.objectContaining({
      epubOptions: { manager: "default", flow: "paginated" },
    }));
    const relocated = rendition.on.mock.calls.find(([eventName]) => eventName === "relocated")?.[1] as (location: unknown) => void;
    act(() => {
      relocated({ start: { cfi: "epubcfi(/6/8!/4/2:0)", href: "chapter.xhtml", displayed: { page: 2, total: 8 } } });
    });

    expect(localStorage.getItem("bookthinking:epub-reader:v1:book-1")).toContain("epubcfi(/6/8!/4/2:0)");
    expect(screen.getByText("第 2 / 8 页")).toBeInTheDocument();
  });

  it("keeps browser-local progress for a public book", () => {
    render(
      <EpubReader
        bookId="public-book"
        data={new Uint8Array([1, 2, 3]).buffer}
        locator={locatorAtSpine(1)}
        restoreProgress
        onError={() => undefined}
      />,
    );
    const relocated = rendition.on.mock.calls.find(([eventName]) => eventName === "relocated")?.[1] as (location: unknown) => void;

    act(() => {
      relocated({ start: { cfi: "epubcfi(/6/8!/4/2:0)", href: "chapter.xhtml", displayed: { page: 2, total: 8 } } });
    });

    expect(loadReaderState("public-book").progressCfi).toBe("epubcfi(/6/8!/4/2:0)");
  });

  it("keeps the latest CFI when switching to continuous scrolling", () => {
    render(<EpubReader bookId="book-1" data={new Uint8Array([1, 2, 3]).buffer} locator={locatorAtSpine(1)} onError={() => undefined} />);
    const relocated = rendition.on.mock.calls.find(([eventName]) => eventName === "relocated")?.[1] as (location: unknown) => void;

    act(() => {
      relocated({ start: { cfi: "epubcfi(/6/8!/4/2:0)", href: "chapter.xhtml", displayed: { page: 2, total: 8 } } });
    });
    fireEvent.click(screen.getByLabelText("连续滚动"));

    expect(reactReader.mock.calls.at(-1)?.[0]).toEqual(expect.objectContaining({
      location: "epubcfi(/6/8!/4/2:0)",
      epubOptions: { manager: "continuous", flow: "scrolled" },
    }));
  });

  it("routes keyboard navigation through the shared callbacks but ignores editable controls", () => {
    render(<EpubReader bookId="book-1" data={new Uint8Array([1, 2, 3]).buffer} locator={locatorAtSpine(1)} onError={() => undefined} />);
    const reader = screen.getByLabelText("原书 EPUB 阅读器");
    fireEvent.click(screen.getByRole("button", { name: "阅读设置" }));
    const input = screen.getByLabelText("字号");

    fireEvent.keyDown(reader, { key: "ArrowRight" });
    fireEvent.keyDown(input, { key: "ArrowRight" });
    fireEvent.keyDown(reader, { key: "ArrowLeft" });

    expect(rendition.next).toHaveBeenCalledTimes(1);
    expect(rendition.prev).toHaveBeenCalledTimes(1);
  });

  it("keeps reading settings in a compact panel until the reader asks for them", () => {
    render(<EpubReader bookId="book-1" data={new Uint8Array([1, 2, 3]).buffer} locator={locatorAtSpine(1)} onError={() => undefined} />);

    expect(screen.queryByLabelText("字号")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "阅读设置" }));
    expect(screen.getByLabelText("字号")).toBeInTheDocument();
    expect(screen.getByLabelText("阅读主题")).toBeInTheDocument();
  });

  it("ignores editable keyboard events from EPUB content windows", () => {
    render(<EpubReader bookId="book-1" data={new Uint8Array([1, 2, 3]).buffer} locator={locatorAtSpine(1)} onError={() => undefined} />);
    const keydownListener = readerContents.window.addEventListener.mock.calls.find(
      ([eventName]) => eventName === "keydown",
    )?.[1] as (event: KeyboardEvent) => void;

    keydownListener({
      key: "ArrowRight",
      preventDefault: vi.fn(),
      target: { matches: () => true },
    } as unknown as KeyboardEvent);

    expect(rendition.next).not.toHaveBeenCalled();
  });

  it("does not turn pages for arrow keys from plaintext-only editable descendants", () => {
    const editable = document.createElement("div");
    editable.setAttribute("contenteditable", "plaintext-only");
    const descendant = document.createElement("span");
    editable.append(descendant);
    document.body.append(editable);

    render(<EpubReader bookId="book-1" data={new Uint8Array([1, 2, 3]).buffer} locator={locatorAtSpine(1)} onError={() => undefined} />);
    const keydownListener = readerContents.window.addEventListener.mock.calls.find(
      ([eventName]) => eventName === "keydown",
    )?.[1] as (event: KeyboardEvent) => void;

    keydownListener({
      key: "ArrowRight",
      preventDefault: vi.fn(),
      target: descendant,
    } as unknown as KeyboardEvent);

    expect(rendition.next).not.toHaveBeenCalled();
  });

  it("applies the browser's dark theme to EPUB content", () => {
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: vi.fn(() => ({
        matches: true,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    });

    render(<EpubReader bookId="book-1" data={new Uint8Array([1, 2, 3]).buffer} locator={locatorAtSpine(0)} onError={() => undefined} />);

    expect(rendition.themes.register).toHaveBeenCalledWith("source-dark", expect.objectContaining({
      html: expect.objectContaining({ background: "#24211d !important" }),
      body: expect.objectContaining({ background: "#24211d !important" }),
    }));
    expect(rendition.themes.select).toHaveBeenCalledWith("source-dark");
    expect(reactReader.mock.calls[0]?.[0]).toEqual(expect.objectContaining({
      readerStyles: expect.objectContaining({
        readerArea: expect.objectContaining({ backgroundColor: "#24211d" }),
      }),
    }));
  });

  it("uses book-like page margins with quiet pagination and a wider table of contents", () => {
    render(<EpubReader bookId="book-1" data={new Uint8Array([1, 2, 3]).buffer} locator={locatorAtSpine(0)} onError={() => undefined} />);

    expect(reactReader.mock.calls[0]?.[0]).toEqual(expect.objectContaining({
      readerStyles: expect.objectContaining({
        reader: expect.objectContaining({ top: 40, left: 64, right: 64, bottom: 28 }),
        arrow: expect.objectContaining({ fontSize: 36, opacity: 0.68 }),
        tocArea: expect.objectContaining({ width: 280 }),
      }),
    }));
  });

  it("displays and temporarily highlights a verified evidence quote", async () => {
    vi.useFakeTimers();

    render(
      <EpubReader
        bookId="book-1"
        data={new Uint8Array([1, 2, 3]).buffer}
        locator={locatorAtSpine(1)}
        quote="有效需求决定就业。"
        highlightRequestId={1}
        onError={() => undefined}
      />,
    );

    await vi.waitFor(() => {
      expect(rendition.display).toHaveBeenCalledWith("epubcfi(/6/4!/4/1:0)");
    });
    expect(rendition.annotations.highlight).toHaveBeenCalledWith(
      "epubcfi(/6/4!/4/1:0)",
      {},
      undefined,
      "source-evidence-highlight",
    );

    vi.advanceTimersByTime(2_800);
    expect(rendition.annotations.remove).toHaveBeenCalledWith("epubcfi(/6/4!/4/1:0)", "highlight");
  });

  it("displays the publisher fragment before finding evidence in that rendered section", async () => {
    const firstFragmentDocument = document.implementation.createHTMLDocument("first-section");
    firstFragmentDocument.body.innerHTML = "<p>有效需求决定就业。</p>";
    const secondFragmentDocument = document.implementation.createHTMLDocument("second-section");
    secondFragmentDocument.body.innerHTML = "<p>有效需求决定就业。</p>";
    const firstContents = {
      ...readerContents,
      document: firstFragmentDocument,
      cfiFromRange: vi.fn(() => "epubcfi(/6/8!/4/4:0,/4/4:8)"),
    };
    const secondContents = {
      ...readerContents,
      document: secondFragmentDocument,
      cfiFromRange: vi.fn(() => "epubcfi(/6/8!/4/2:0,/4/2:8)"),
    };

    rendition.getContents.mockReturnValue([firstContents]);
    rendition.display.mockImplementation((target: string | number) => {
      if (target === "text00004.html#second-section") {
        rendition.getContents.mockReturnValue([secondContents]);
      }
      return Promise.resolve();
    });

    render(
      <EpubReader
        bookId="book-1"
        data={new Uint8Array([1, 2, 3]).buffer}
        locator={{
          href: "OEBPS/text00004.html",
          fragment: "second-section",
          cfi: null,
          spineIndex: 5,
        }}
        quote="有效需求决定就业。"
        highlightRequestId={1}
        onError={() => undefined}
      />,
    );

    await vi.waitFor(() => {
      expect(rendition.annotations.highlight).toHaveBeenCalledWith(
        "epubcfi(/6/8!/4/2:0,/4/2:8)",
        {},
        undefined,
        "source-evidence-highlight",
      );
    });
    expect(rendition.display).toHaveBeenNthCalledWith(
      1,
      "text00004.html#second-section",
    );
  });

  it("keeps the requested spine but adds no annotation when the quote is absent", async () => {
    render(
      <EpubReader
        bookId="book-1"
        data={new Uint8Array([1, 2, 3]).buffer}
        locator={locatorAtSpine(1)}
        quote="不存在的完整引文"
        highlightRequestId={1}
        onError={() => undefined}
      />,
    );

    await vi.waitFor(() => expect(reactReader).toHaveBeenCalled());
    expect(screen.getByTestId("react-reader")).toHaveAttribute("data-location", "text00004.html");
    expect(rendition.annotations.highlight).not.toHaveBeenCalled();
  });

  it("does not redisplay a structural locator after a missing quote on a later rendered event", async () => {
    rendition.display.mockImplementation(() => Promise.resolve());
    rendition.getContents.mockReturnValue([readerContents]);
    const locator = {
      href: "OEBPS/text00004.html",
      fragment: "second-section",
      cfi: null,
      spineIndex: 5,
    };

    render(
      <EpubReader
        bookId="book-1"
        data={new Uint8Array([1, 2, 3]).buffer}
        locator={locator}
        quote="不存在的完整引文"
        highlightRequestId={1}
        onError={() => undefined}
      />,
    );

    await vi.waitFor(() => {
      expect(rendition.display).toHaveBeenCalledExactlyOnceWith(
        "text00004.html#second-section",
      );
    });
    await Promise.resolve();
    await Promise.resolve();

    const renderedListener = rendition.on.mock.calls.find(
      ([eventName]) => eventName === "rendered",
    )?.[1] as (() => void);
    renderedListener();

    expect(rendition.display).toHaveBeenCalledExactlyOnceWith(
      "text00004.html#second-section",
    );
  });

  it("turns EPUB pages with the mouse wheel without scrolling the analysis page", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(0));
    const data = new Uint8Array([1, 2, 3]).buffer;

    render(<EpubReader bookId="book-1" data={data} locator={locatorAtSpine(1)} onError={() => undefined} />);

    const reader = screen.getByLabelText("原书 EPUB 阅读器");
    fireEvent.wheel(reader, { deltaY: 120 });
    fireEvent.wheel(reader, { deltaY: 120 });

    expect(rendition.next).toHaveBeenCalledTimes(1);
    expect(rendition.prev).not.toHaveBeenCalled();

    vi.setSystemTime(new Date(420));
    fireEvent.wheel(reader, { deltaY: -120 });
    expect(rendition.prev).toHaveBeenCalledTimes(1);
  });

  it("handles wheel events originating inside the EPUB content frame", () => {
    const data = new Uint8Array([1, 2, 3]).buffer;
    const preventDefault = vi.fn();
    const stopPropagation = vi.fn();

    render(<EpubReader bookId="book-1" data={data} locator={locatorAtSpine(1)} onError={() => undefined} />);

    expect(rendition.hooks.content.register).toHaveBeenCalledWith(expect.any(Function));
    const contentHook = rendition.hooks.content.register.mock.calls[0]?.[0] as (
      contents: typeof readerContents,
    ) => void;
    contentHook(readerContents);

    expect(readerContents.window.addEventListener).toHaveBeenCalledWith(
      "wheel",
      expect.any(Function),
      { passive: false },
    );
    const wheelListener = readerContents.window.addEventListener.mock.calls.find(
      ([eventName]) => eventName === "wheel",
    )?.[1] as ((event: WheelEvent) => void);

    wheelListener({ deltaY: 120, preventDefault, stopPropagation } as unknown as WheelEvent);

    expect(rendition.next).toHaveBeenCalledTimes(1);
    expect(preventDefault).toHaveBeenCalledOnce();
    expect(stopPropagation).toHaveBeenCalledOnce();
  });
});
