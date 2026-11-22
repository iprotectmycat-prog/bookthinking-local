import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
const { apiJson } = vi.hoisted(() => ({ apiJson: vi.fn() }));
vi.mock("../lib/api", () => ({ apiJson }));
vi.mock("next/navigation", () => ({ useParams: () => ({ bookId: "book", chapterId: "1" }) }));
vi.mock("../components/ChapterWorkspace", () => ({
  ChapterWorkspace: ({ analysis, onRetry, retrying }: { analysis: { generation_status: string }; onRetry: () => void; retrying: boolean }) => (
    <div><p>{analysis.generation_status}</p><button onClick={onRetry} disabled={retrying}>重试</button></div>
  ),
}));
import ChapterPage from "../app/books/[bookId]/chapters/[chapterId]/page";
afterEach(() => { vi.useRealTimers(); apiJson.mockReset(); });

it.each(["succeeded", "failed"])("refreshes the chapter after background %s without manual reload", async status => {
  vi.useFakeTimers();
  const job = { id: "job", book_id: "book", status: "running", stage: "chapters", target_chapter_ids: [1], completed_chapter_ids: [], failed_chapter_ids: [], error_code: null };
  let retried = false;
  let finished = false;
  apiJson.mockImplementation(async (path: string, init?: RequestInit) => {
    if (init?.method === "POST") { retried = true; return { generation_status: "generating", analysis_job: job }; }
    if (path.includes("/analysis-jobs/")) {
      if (finished) return { ...job, status };
      finished = true; return job;
    }
    if (path.endsWith("/overview")) return { access_scope: "owned", book_title: "测试书", chapters: [], source_format: "pdf", analysis_job: retried ? { ...job, status: finished ? status : "running" } : null };
    return { generation_status: retried && finished && status === "succeeded" ? "ready" : "failed" };
  });
  render(<ChapterPage />);
  await act(async () => {});
  fireEvent.click(screen.getByRole("button", { name: "重试" }));
  await act(async () => {});
  await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
  expect(screen.getByRole("button", { name: "重试" })).not.toBeDisabled();
  expect(screen.getByText(status === "succeeded" ? "ready" : "failed")).toBeInTheDocument();
  if (status === "failed") expect(screen.queryByText("本章分析已更新。")).not.toBeInTheDocument();
});

it("offers a return path if the chapter was removed while its task finished", async () => {
  const job = { id: "job", book_id: "book", status: "superseded", stage: "chapters", target_chapter_ids: [1], completed_chapter_ids: [], failed_chapter_ids: [], error_code: "input_changed" };
  let reads = 0;
  apiJson.mockImplementation(async (path: string, init?: RequestInit) => {
    if (init?.method === "POST") return { generation_status: "generating", analysis_job: job };
    if (path.includes("/analysis-jobs/")) return job;
    if (path.endsWith("/overview")) return { access_scope: "owned", book_title: "测试书", chapters: [], source_format: "pdf" };
    if (++reads > 1) throw Object.assign(new Error("章节不存在"), { status: 404 });
    return { generation_status: "failed" };
  });
  render(<ChapterPage />);
  await act(async () => {});
  fireEvent.click(screen.getByRole("button", { name: "重试" }));
  await act(async () => {});
  expect(screen.getByRole("link", { name: "返回章节总览" })).toBeInTheDocument();
});
