"use client";

import { useEffect, useRef, useState } from "react";
import { apiJson } from "./api";
import type { AnalysisJob } from "./types";

export function isActiveAnalysisJob(job: AnalysisJob | null | undefined) {
  return job?.status === "queued" || job?.status === "running";
}

export function analysisJobMessage(job: AnalysisJob) {
  switch (job.status) {
    case "succeeded": return job.error_code === "no_eligible_content" ? "本书没有需要生成完整分析的正文，可直接阅读原文。" : "本章分析已更新。";
    case "failed": return job.stage === "overview" && job.failed_chapter_ids.length === 0
      ? "章节分析已保留，全书概览未能完成，请重试全书分析。"
      : "部分分析未能完成，请查看失败章节并重试。";
    case "interrupted": return "分析已中断，请重新分析。";
    case "superseded": return "分析输入已变化，请重新分析。";
    default: return "";
  }
}

type Options = {
  bookId: string;
  jobId: string | null;
  onTerminal: (job: AnalysisJob) => void | Promise<void>;
  onUpdate?: (job: AnalysisJob) => void | Promise<void>;
};

export function useAnalysisJob({ bookId, jobId, onTerminal, onUpdate }: Options) {
  const key = bookId + ":" + jobId;
  const [state, setState] = useState<{ key: string; job?: AnalysisJob; error: string; stopped?: boolean }>();
  const [retryVersion, setRetryVersion] = useState(0);
  const callbacks = useRef({ onTerminal, onUpdate });
  const delivered = useRef(new Set<string>());
  useEffect(() => { callbacks.current = { onTerminal, onUpdate }; }, [onTerminal, onUpdate]);

  useEffect(() => {
    if (!jobId) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let failures = 0;
    async function poll() {
      try {
        const job = await apiJson<AnalysisJob>(`/books/${bookId}/analysis-jobs/${jobId}`, { signal: controller.signal });
        if (controller.signal.aborted) return;
        if (!isActiveAnalysisJob(job)) {
          if (!delivered.current.has(key)) {
            await callbacks.current.onTerminal(job);
            if (controller.signal.aborted) return;
            delivered.current.add(key);
          }
          setState({ key, job, error: "", stopped: true });
          return;
        }
        await callbacks.current.onUpdate?.(job);
        if (controller.signal.aborted) return;
        failures = 0;
        setState({ key, job, error: "" });
        timer = setTimeout(poll, 2000);
      } catch (error) {
        if (controller.signal.aborted) return;
        const status = typeof error === "object" && error !== null && "status" in error ? error.status : null;
        if (status === 401 || status === 403 || status === 404) {
          setState({ key, error: "无法读取分析任务，请刷新页面后重试。", stopped: true });
          return;
        }
        failures += 1;
        setState({ key, error: failures >= 3 ? "进度暂时无法更新，正在重试连接。" : "" });
        timer = setTimeout(poll, Math.min(30000, 2000 * 2 ** (failures - 1)));
      }
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [bookId, jobId, key, retryVersion]);

  const current = state?.key === key ? state : undefined;
  return {
    job: current?.job,
    isTracking: Boolean(jobId) && !current?.stopped,
    trackingError: current?.error ?? "",
    retryTracking: () => setRetryVersion(value => value + 1),
  };
}
