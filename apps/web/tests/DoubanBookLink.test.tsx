import { readFileSync } from "node:fs";

import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DoubanBookLink } from "../components/DoubanBookLink";

afterEach(() => vi.unstubAllGlobals());

describe("DoubanBookLink", () => {
  it("uses the same typography and color as the source metadata beside it", () => {
    const styles = readFileSync("app/globals.css", "utf8");

    expect(styles).toMatch(/\.douban-book-link\s*\{[^}]*color:\s*inherit;[^}]*font:\s*inherit;/s);
  });

  it("renders a quiet direct link after a verified match", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      provider: "douban", status: "matched", url: "https://book.douban.com/subject/35546622/",
    }), { status: 200 })));

    render(<DoubanBookLink bookId="b1" title="置身事内" />);

    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    const link = await screen.findByRole("link", { name: "在豆瓣查看《置身事内》" });
    expect(link).toHaveAttribute("href", "https://book.douban.com/subject/35546622/");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer");
    expect(link).toHaveTextContent("豆瓣 ↗");
  });

  it("renders nothing when the link is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      provider: "douban", status: "unavailable", url: null,
    }), { status: 200 })));

    render(<DoubanBookLink bookId="b1" title="置身事内" />);
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));

    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText(/搜索|加载/)).not.toBeInTheDocument();
  });

  it("renders nothing when the request fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));

    render(<DoubanBookLink bookId="b1" title="置身事内" />);
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));

    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
