import { act, renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

const { apiJson } = vi.hoisted(() => ({ apiJson: vi.fn() }));
vi.mock("../lib/api", () => ({ apiJson }));
import { useAnalysisJob } from "../lib/use-analysis-job";

const job = (status: string) => ({ id: "job", book_id: "book", status, stage: "chapters", target_chapter_ids: [1], completed_chapter_ids: [], failed_chapter_ids: [], error_code: null });
afterEach(() => { vi.useRealTimers(); apiJson.mockReset(); });

it.each(["succeeded", "failed", "interrupted", "superseded"])("handles immediate %s once and stops polling", async (status) => {
  vi.useFakeTimers();
  apiJson.mockResolvedValue(job(status));
  const onTerminal = vi.fn();
  const { result } = renderHook(() => useAnalysisJob({ bookId: "book", jobId: "job", onTerminal }));
  await act(async () => {});
  expect(onTerminal).toHaveBeenCalledTimes(1);
  expect(result.current.isTracking).toBe(false);
  await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
  expect(apiJson).toHaveBeenCalledTimes(1);
});

it("never overlaps a slow request and cancels on unmount", async () => {
  vi.useFakeTimers();
  apiJson.mockImplementation(() => new Promise(() => {}));
  const { unmount } = renderHook(() => useAnalysisJob({ bookId: "book", jobId: "job", onTerminal: vi.fn() }));
  await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
  expect(apiJson).toHaveBeenCalledTimes(1);
  const signal = apiJson.mock.calls[0][1].signal;
  unmount();
  expect(signal.aborted).toBe(true);
});

it("ignores a previous book's response after navigation", async () => {
  let resolveOld: (value: unknown) => void = () => {};
  apiJson.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; })).mockResolvedValue(job("succeeded"));
  const onTerminal = vi.fn();
  const { rerender } = renderHook(({ bookId }) => useAnalysisJob({ bookId, jobId: "job", onTerminal }), { initialProps: { bookId: "old" } });
  rerender({ bookId: "book" });
  await act(async () => {});
  await act(async () => { resolveOld(job("failed")); });
  expect(onTerminal).toHaveBeenCalledTimes(1);
  expect(onTerminal.mock.calls[0][0].status).toBe("succeeded");
});

it("backs off on network errors and clears the warning after recovery", async () => {
  vi.useFakeTimers();
  apiJson.mockRejectedValueOnce(new Error("offline")).mockRejectedValueOnce(new Error("offline")).mockRejectedValueOnce(new Error("offline")).mockResolvedValue(job("succeeded"));
  const onTerminal = vi.fn();
  const { result } = renderHook(() => useAnalysisJob({ bookId: "book", jobId: "job", onTerminal }));
  await act(async () => {});
  await act(async () => { await vi.advanceTimersByTimeAsync(6000); });
  expect(result.current.trackingError).toContain("进度暂时无法更新");
  await act(async () => { await vi.advanceTimersByTimeAsync(8000); });
  expect(onTerminal).toHaveBeenCalledTimes(1);
  expect(result.current.trackingError).toBe("");
});
