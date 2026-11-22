import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AnalysisStatus } from "../lib/types";

const { apiJson } = vi.hoisted(() => ({ apiJson: vi.fn() }));

vi.mock("next/navigation", () => ({ useParams: () => ({ bookId: "book-1" }) }));
vi.mock("next/link", () => ({
  default: ({ children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => <a {...props}>{children}</a>,
}));
vi.mock("../lib/api", () => ({ apiJson }));
vi.mock("../components/BookSummaryHeader", () => ({ BookSummaryHeader: () => <header aria-label="图书总览" /> }));
vi.mock("../components/ChapterSidebar", () => ({ ChapterSidebar: () => <aside aria-label="章节目录" /> }));
vi.mock("../components/ChapterOverviewCard", () => ({
  ChapterOverviewCard: ({ chapter, onRetry, retrying }: { chapter: { id: number; generation_status: string }; onRetry?: (id: number) => void; retrying?: boolean }) => (
    chapter.generation_status === "failed"
      ? onRetry && <button disabled={retrying} onClick={() => onRetry(chapter.id)}>{retrying ? "正在重新分析…" : "重新分析本章"}</button>
      : <article />
  ),
}));

import OverviewPage from "../app/books/[bookId]/overview/page";

const job = (status = "running") => ({ id: "job", book_id: "book-1", status, stage: "chapters", target_chapter_ids: [4], completed_chapter_ids: [], failed_chapter_ids: [], error_code: null });

const chapters = (statuses: AnalysisStatus[]) => statuses.map((generation_status, index) => ({
  id: index + 1,
  position: index,
  title: `第 ${index + 1} 章`,
  source_start_page: index + 1,
  source_end_page: index + 1,
  chapter_question: "",
  one_sentence_conclusion: "",
  core_idea_titles: [],
  role_in_book: "",
  estimated_reading_minutes: 3,
  generation_status,
  failure_reason: generation_status === "failed" ? "模型返回了空内容" : null,
}));

const pendingOverview = {
  book_id: "book-1", book_title: "测试书.pdf", source_format: "pdf" as const,
  core_question: "", one_sentence_summary: "", estimated_reading_minutes: 12,
  ready_chapter_count: 0, chapter_count: 4, access_scope: "owned" as const, chapters: chapters(["pending", "pending", "pending", "failed"]),
};

const activeOverview = {
  ...pendingOverview,
  ready_chapter_count: 1,
  chapters: chapters(["ready", "generating", "pending", "failed"]),
};

const skippedOverview = {
  ...pendingOverview,
  chapter_count: 3,
  ready_chapter_count: 1,
  chapters: chapters(["ready", "pending", "skipped"]),
};

const finalOverview = {
  ...pendingOverview,
  ready_chapter_count: 3,
  chapters: chapters(["ready", "ready", "ready", "failed"]),
};

const retryStartedOverview = {
  ...finalOverview,
  chapters: chapters(["ready", "ready", "ready", "generating"]),
};

const retryFinishedOverview = {
  ...finalOverview,
  ready_chapter_count: 4,
  chapters: chapters(["ready", "ready", "ready", "ready"]),
};

afterEach(() => {
  vi.useRealTimers();
  apiJson.mockReset();
});

describe("OverviewPage analysis progress", () => {
  it("provides a visible top-left link back to the home page", async () => {
    apiJson.mockResolvedValueOnce(finalOverview);

    render(<OverviewPage />);

    expect(await screen.findByRole("link", { name: "返回首页" })).toHaveAttribute("href", "/");
  });

  it("renders a public book as platform read only without generation or retry controls", async () => {
    apiJson.mockResolvedValue({
      ...finalOverview,
      access_scope: "public",
      chapters: chapters(["ready", "ready", "ready", "failed"]),
    });

    render(<OverviewPage />);

    expect(await screen.findByLabelText("图书总览")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "模型设置" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /生成全书分析/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /重新分析/ })).not.toBeInTheDocument();
  });

  it("uses the shared single-column overview with a chapter list", async () => {
    apiJson.mockResolvedValueOnce({ ...finalOverview, ready_chapter_count: 4, chapters: chapters(["ready", "ready", "ready", "ready"]) });

    render(<OverviewPage />);

    await screen.findByRole("link", { name: "返回首页" });
    expect(screen.getByRole("region", { name: "章节总览" })).toBeInTheDocument();
    expect(screen.queryByLabelText("章节目录")).not.toBeInTheDocument();
    expect(screen.queryByText("按章节阅读")).not.toBeInTheDocument();
    expect(screen.getByRole("main").parentElement).not.toHaveClass("overview-shell");
  });

  it("polls the progress panel and separates running chapters from the queue", async () => {
    vi.useFakeTimers();
    let overviewReads = 0;
    apiJson.mockImplementation(async (path: string) => {
      if (path.includes("/analysis-jobs/")) return job();
      if (path.endsWith("/analyses")) return { ...activeOverview, analysis_job: job() };
      return ++overviewReads === 1 ? pendingOverview : { ...(overviewReads === 2 ? activeOverview : finalOverview), analysis_job: job() };
    });

    render(<OverviewPage />);
    await act(async () => { await Promise.resolve(); });

    expect(screen.getByRole("tab", { name: "1正在分析" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "1等待分析" })).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("图书总览")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "先看结论，再逐层深入" })).not.toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(2_000); });
    expect(screen.getByRole("heading", { name: "正在分析中" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "1需要留意" })).toBeInTheDocument();
    expect(apiJson).toHaveBeenCalledWith("/books/book-1/analysis-jobs/job", expect.objectContaining({ signal: expect.any(AbortSignal) }));
  });

  it("renders live analysis progress with separate status tabs and failure reasons", async () => {
    apiJson.mockResolvedValue(activeOverview);

    render(<OverviewPage />);

    expect(await screen.findByRole("heading", { name: "正在分析中" })).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "全书分析进度" })).toHaveAttribute("aria-valuenow", "25");
    expect(screen.getByRole("tab", { name: "1已可阅读" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "1正在分析" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "1等待分析" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "1需要留意" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "1需要留意" }));

    expect(screen.getByRole("tabpanel", { name: "1需要留意" })).toHaveTextContent("第 4 章");
    expect(screen.getByRole("tabpanel", { name: "1需要留意" })).toHaveTextContent("这一章分析没能完成。可以重新分析，若反复失败请检查模型设置。");
  });

  it("omits redundant analysis progress copy", async () => {
    apiJson.mockResolvedValue(activeOverview);

    render(<OverviewPage />);

    await screen.findByRole("heading", { name: "正在分析中" });
    expect(screen.queryByText("已完成的章节会先开放阅读；其余章节会继续在后台处理。你可以随时查看每一种状态。")).not.toBeInTheDocument();
    expect(screen.queryByText("自动更新")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "1正在分析" }));

    expect(screen.getByRole("tabpanel", { name: "1正在分析" })).toHaveTextContent("第 2 章");
    expect(screen.queryByText("正在提炼章节问题、论证与证据。")).not.toBeInTheDocument();
  });

  it("supports keyboard navigation between status tabs", async () => {
    apiJson.mockResolvedValue(activeOverview);

    render(<OverviewPage />);

    const readableTab = await screen.findByRole("tab", { name: "1已可阅读" });
    fireEvent.keyDown(readableTab, { key: "ArrowRight" });

    expect(screen.getByRole("tab", { name: "1正在分析" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel", { name: "1正在分析" })).toHaveTextContent("第 2 章");
  });

  it("excludes structure-only chapters from the progress denominator", async () => {
    apiJson.mockResolvedValue(skippedOverview);

    render(<OverviewPage />);

    expect(await screen.findByRole("progressbar", { name: "全书分析进度" })).toHaveAttribute("aria-valuenow", "50");
    expect(screen.getByText("50% · 1 / 2 章已完成")).toBeInTheDocument();
  });

  it("acknowledges a chapter retry immediately and refreshes until it finishes", async () => {
    vi.useFakeTimers();
    let retried = false;
    let checks = 0;
    apiJson.mockImplementation(async (path: string, init?: RequestInit) => {
      if (init?.method === "POST") { retried = true; return { generation_status: "generating", analysis_job: job() }; }
      if (path.includes("/analysis-jobs/")) return job(++checks > 1 ? "succeeded" : "running");
      return !retried ? finalOverview : checks > 1 ? { ...retryFinishedOverview, analysis_job: job("succeeded") } : { ...retryStartedOverview, analysis_job: job() };
    });

    render(<OverviewPage />);
    await act(async () => { await Promise.resolve(); });

    fireEvent.click(screen.getByRole("tab", { name: "1需要留意" }));
    fireEvent.click(screen.getByRole("button", { name: "重新分析本章" }));
    await act(async () => { await Promise.resolve(); });

    expect(screen.getByRole("status")).toHaveTextContent("正在重新分析这一章，结果会自动更新。");
    await act(async () => { await vi.advanceTimersByTimeAsync(2_000); });
    expect(screen.getByRole("status")).toHaveTextContent("本章分析已更新。");
  });
});

it("releases retry controls when a task finishes before the first poll", async () => {
  let retried = false;
  apiJson.mockImplementation(async (path: string, init?: RequestInit) => {
    if (init?.method === "POST") { retried = true; return { generation_status: "ready", analysis_job: job("succeeded") }; }
    if (path.includes("/analysis-jobs/")) return job("succeeded");
    return retried ? { ...retryFinishedOverview, analysis_job: job("succeeded") } : finalOverview;
  });
  render(<OverviewPage />);
  await act(async () => {});
  fireEvent.click(screen.getByRole("tab", { name: "1需要留意" }));
  fireEvent.click(screen.getByRole("button", { name: "重新分析本章" }));
  await act(async () => {});
  expect(screen.getByRole("status")).toHaveTextContent("本章分析已更新。");
  expect(screen.queryByRole("button", { name: "正在重新分析…" })).not.toBeInTheDocument();
});

it("starts updated chapters even when the previous task succeeded", async () => {
  apiJson.mockImplementation(async (path: string) => {
    if (path.endsWith('/analyses')) return { ...activeOverview, analysis_job: job() };
    if (path.includes('/analysis-jobs/')) return job();
    return { ...pendingOverview, chapters: chapters(['stale', 'pending', 'ready', 'ready']), analysis_job: job('succeeded') };
  });
  render(<OverviewPage />);
  await act(async () => {});
  expect(apiJson).toHaveBeenCalledWith('/books/book-1/analyses', { method: 'POST' });
});
