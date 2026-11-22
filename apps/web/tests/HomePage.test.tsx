import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import HomePage from "../app/page";

const { apiJson } = vi.hoisted(() => ({ apiJson: vi.fn() }));
vi.mock("../lib/api", () => ({ apiJson }));

describe("HomePage", () => {
  afterEach(() => vi.unstubAllEnvs());
  beforeEach(() => {
    apiJson.mockReset();
    apiJson.mockResolvedValue([]);
  });

  it("makes the bookshelf the main entry with one heading and one import action", async () => {
    render(<HomePage />);
    expect(screen.getByRole("heading", { level: 1, name: "书架" })).toBeVisible();
    expect(await screen.findByRole("button", { name: "导入书籍" })).toBeEnabled();
    expect(screen.getAllByRole("heading")).toHaveLength(1);
    expect(screen.getByRole("link", { name: "模型设置" })).toHaveAttribute("href", "/settings");
  });

  it("keeps access to both existing libraries in local mode", async () => {
    render(<HomePage />);
    expect(await screen.findByRole("tab", { name: "精选书架 0" })).toBeVisible();
    expect(apiJson).toHaveBeenCalledWith("/library/public");
    expect(apiJson).toHaveBeenCalledWith("/library/analyzed");
  });

  it("shows both cloud shelf entries and sends personal actions to the same guide", async () => {
    vi.stubEnv("BOOKTHINKING_DEPLOYMENT_MODE", "cloud");
    render(<HomePage />);
    expect(screen.getByRole("heading", { level: 1, name: "书架" })).toBeVisible();
    expect(await screen.findByText("精选书籍正在整理中。")).toBeVisible();
    expect(screen.getByRole("link", { name: /精选书架/ })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "我的书架" })).toHaveAttribute("href", "/my-shelf");
    expect(screen.getByRole("link", { name: "导入书籍" })).toHaveAttribute("href", "/my-shelf");
    expect(screen.queryByRole("button", { name: "选择 PDF 或 EPUB 文件" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "模型设置" })).not.toBeInTheDocument();
    expect(apiJson.mock.calls).toEqual([["/library/public"]]);
  });
});
