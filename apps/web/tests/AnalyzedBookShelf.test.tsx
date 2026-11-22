import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AnalyzedBookShelf } from "../components/AnalyzedBookShelf";

const { apiJson } = vi.hoisted(() => ({ apiJson: vi.fn() }));
vi.mock("../lib/api", () => ({ apiJson }));

const books = Array.from({ length: 14 }, (_, index) => ({
  id: `book-${index + 1}`,
  filename: `Book ${index + 1}.pdf`,
  source_format: "pdf" as const,
  title: `书籍 ${index + 1}`,
  authors: "作者",
  access_scope: "owned" as const,
}));

function mockShelves() {
  apiJson.mockImplementation((path: string) => Promise.resolve(
    path === "/library/public" ? [{ ...books[0], id: "public-1", title: "精选书籍" }] : books,
  ));
}

describe("AnalyzedBookShelf", () => {
  beforeEach(() => {
    apiJson.mockReset();
    sessionStorage.clear();
    vi.stubGlobal("innerWidth", 1280);
    vi.stubGlobal("scrollTo", vi.fn());
    vi.stubGlobal("scrollY", 0);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("shows one shelf at a time, with titles and working book links", async () => {
    const user = userEvent.setup();
    mockShelves();
    render(<AnalyzedBookShelf showPublicShelf />);

    const mine = await screen.findByRole("tab", { name: "我的书架 14" });
    expect(mine).toHaveAttribute("aria-selected", "true");
    expect(screen.getAllByRole("tabpanel")).toHaveLength(1);
    expect(screen.getByRole("link", { name: "书籍 1" })).toHaveAttribute("href", "/books/book-1/overview");
    expect(screen.getByText("书籍 1")).toBeVisible();
    expect(screen.queryByRole("link", { name: "精选书籍" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "精选书架 1" }));
    expect(screen.getByRole("link", { name: "精选书籍" })).toBeVisible();
    expect(screen.queryByRole("link", { name: "书籍 1" })).not.toBeInTheDocument();
  });

  it("switches tabs with arrow keys and gives focus to the selected tab", async () => {
    const user = userEvent.setup();
    mockShelves();
    render(<AnalyzedBookShelf showPublicShelf />);
    const mine = await screen.findByRole("tab", { name: "我的书架 14" });
    mine.focus();
    await user.keyboard("{ArrowRight}");
    const curated = screen.getByRole("tab", { name: "精选书架 1" });
    expect(curated).toHaveFocus();
    expect(curated).toHaveAttribute("aria-selected", "true");
    expect(mine).toHaveAttribute("tabindex", "-1");
    await user.keyboard("{Home}");
    expect(mine).toHaveFocus();
  });

  it("keeps the private shelf usable when the public request fails and retries only the failed shelf", async () => {
    const user = userEvent.setup();
    apiJson.mockImplementation((path: string) => path === "/library/public"
      ? Promise.reject(new Error("offline")) : Promise.resolve(books));
    render(<AnalyzedBookShelf showPublicShelf />);
    expect(await screen.findByRole("link", { name: "书籍 1" })).toBeVisible();
    await user.click(screen.getByRole("tab", { name: "精选书架" }));
    expect(screen.getByRole("alert")).toHaveTextContent("书架暂时无法加载");

    apiJson.mockImplementation(() => Promise.resolve([{ ...books[0], title: "重试成功" }]));
    await user.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByRole("link", { name: "重试成功" })).toBeVisible();
    expect(apiJson.mock.calls.filter(([path]) => path === "/library/analyzed")).toHaveLength(1);
  });

  it("starts with one row, ignores sideways scrolling, and unfolds on downward scrolling", async () => {
    mockShelves();
    render(<AnalyzedBookShelf />);
    const shelf = await screen.findByRole("region", { name: "我的书架，14 本" });
    expect(screen.getAllByRole("link")).toHaveLength(5);
    fireEvent.wheel(shelf, { deltaX: 90, deltaY: 5 });
    expect(screen.getAllByRole("link")).toHaveLength(5);
    fireEvent.wheel(shelf, { deltaY: 60 });
    expect(screen.getAllByRole("link")).toHaveLength(14);
    expect(screen.getByRole("button", { name: "收起书架" })).toHaveAttribute("aria-expanded", "true");
  });

  it("unfolds with a downward touch without opening the touched book", async () => {
    mockShelves();
    render(<AnalyzedBookShelf />);
    const link = await screen.findByRole("link", { name: "书籍 1" });
    fireEvent.touchStart(link, { touches: [{ clientX: 100, clientY: 100 }] });
    fireEvent.touchMove(link, { touches: [{ clientX: 104, clientY: 165 }] });
    fireEvent.touchEnd(link);
    expect(screen.getAllByRole("link")).toHaveLength(14);
    expect(fireEvent.click(link)).toBe(false);
  });

  it("collapses with Escape after wheel expansion while focus remains outside the shelf", async () => {
    mockShelves();
    render(<AnalyzedBookShelf />);
    const shelf = await screen.findByRole("region", { name: "我的书架，14 本" });
    fireEvent.wheel(shelf, { deltaY: 60 });
    expect(screen.getAllByRole("link")).toHaveLength(14);
    expect(document.activeElement).toBe(document.body);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.getAllByRole("link")).toHaveLength(5);
  });

  it("supports an explicit expand/collapse button and Escape", async () => {
    const user = userEvent.setup();
    mockShelves();
    render(<AnalyzedBookShelf />);
    const button = await screen.findByRole("button", { name: "展开书架" });
    await user.click(button);
    expect(screen.getAllByRole("link")).toHaveLength(14);
    await user.keyboard("{Escape}");
    expect(screen.getAllByRole("link")).toHaveLength(5);
    expect(button).toHaveAttribute("aria-expanded", "false");
    await user.click(button);
    await user.click(screen.getByRole("button", { name: "收起书架" }));
    expect(screen.getAllByRole("link")).toHaveLength(5);
  });

  it("shows only two books before expanding on a narrow screen", async () => {
    vi.stubGlobal("innerWidth", 390);
    mockShelves();
    render(<AnalyzedBookShelf />);
    await screen.findByRole("link", { name: "书籍 1" });
    expect(screen.getAllByRole("link")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "展开书架" })).toBeVisible();
  });

  it("omits expansion controls when every book fits in one row", async () => {
    apiJson.mockResolvedValue(books.slice(0, 2));
    render(<AnalyzedBookShelf />);
    await screen.findByRole("link", { name: "书籍 1" });
    expect(screen.queryByRole("button", { name: "展开书架" })).not.toBeInTheDocument();
  });

  it("ignores sideways touch gestures and keeps a normal book tap usable", async () => {
    mockShelves();
    render(<AnalyzedBookShelf />);
    const link = await screen.findByRole("link", { name: "书籍 1" });
    fireEvent.touchStart(link, { touches: [{ clientX: 100, clientY: 100 }] });
    fireEvent.touchMove(link, { touches: [{ clientX: 170, clientY: 110 }] });
    fireEvent.touchEnd(link);
    expect(screen.getAllByRole("link")).toHaveLength(5);
    const tapped = vi.fn((event: MouseEvent) => event.preventDefault());
    link.addEventListener("click", tapped);
    fireEvent.click(link);
    expect(tapped).toHaveBeenCalledOnce();
  });

  it("restores the expanded shelf when returning from a book beyond the first row", async () => {
    const user = userEvent.setup();
    mockShelves();
    const first = render(<AnalyzedBookShelf />);
    await user.click(await screen.findByRole("button", { name: "展开书架" }));
    const link = screen.getByRole("link", { name: "书籍 8" });
    link.addEventListener("click", event => event.preventDefault());
    vi.stubGlobal("scrollY", 600);
    await user.click(link);
    first.unmount();
    render(<AnalyzedBookShelf />);
    expect(await screen.findByRole("link", { name: "书籍 8" })).toBeVisible();
    expect(screen.getByRole("button", { name: "收起书架" })).toHaveAttribute("aria-expanded", "true");
    expect(window.scrollTo).toHaveBeenLastCalledWith({ top: 600, behavior: "instant" });
  });

  it("opens the system file chooser from the import button", async () => {
    const user = userEvent.setup();
    apiJson.mockResolvedValue(books.slice(0, 1));
    const click = vi.spyOn(HTMLInputElement.prototype, "click");
    render(<AnalyzedBookShelf />);
    await user.click(screen.getByRole("button", { name: "导入书籍" }));
    expect(click).toHaveBeenCalledOnce();
    click.mockRestore();
  });

  it("retains a readable title and book link when a cover fails", async () => {
    apiJson.mockResolvedValue(books.slice(0, 1));
    render(<AnalyzedBookShelf />);
    fireEvent.error(await screen.findByRole("img", { name: "书籍 1 封面" }));
    expect(screen.getByRole("link", { name: "书籍 1" })).toBeVisible();
    expect(screen.getAllByText("书籍 1").length).toBeGreaterThan(0);
    expect(screen.queryByRole("img", { name: "书籍 1 封面" })).not.toBeInTheDocument();
  });

  it("shows an empty private shelf without hiding the import or curated tab", async () => {
    apiJson.mockResolvedValue([]);
    render(<AnalyzedBookShelf showPublicShelf />);
    expect(await screen.findByText("书架还空着，先放一本喜欢的书。" )).toBeVisible();
    expect(screen.getByRole("button", { name: "导入书籍" })).toBeEnabled();
    expect(screen.getByRole("tab", { name: "精选书架 0" })).toBeVisible();
  });

  it("restores the selected library and vertical page position after returning from a book", async () => {
    const user = userEvent.setup();
    mockShelves();
    const first = render(<AnalyzedBookShelf showPublicShelf />);
    await user.click(await screen.findByRole("tab", { name: "精选书架 1" }));
    vi.stubGlobal("scrollY", 500);
    const link = screen.getByRole("link", { name: "精选书籍" });
    link.addEventListener("click", (event) => event.preventDefault());
    await user.click(link);
    first.unmount();
    vi.stubGlobal("scrollY", 0);
    vi.mocked(window.scrollTo).mockClear();
    render(<AnalyzedBookShelf showPublicShelf />);
    expect(await screen.findByRole("link", { name: "精选书籍" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "精选书架 1" })).toHaveAttribute("aria-selected", "true");
    expect(window.scrollTo).toHaveBeenLastCalledWith({ top: 500, behavior: "instant" });
  });

});
