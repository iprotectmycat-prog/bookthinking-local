"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";

import { BookSummaryHeader } from "../../../../components/BookSummaryHeader";
import { AnalysisProgressPanel } from "../../../../components/AnalysisProgressPanel";
import { ChapterOverviewList } from "../../../../components/ChapterOverviewList";
import { apiJson } from "../../../../lib/api";
import { describeRequestError } from "../../../../lib/analysis-message";
import { useAnalysisJob, analysisJobMessage, isActiveAnalysisJob } from "../../../../lib/use-analysis-job";
import type { BookOverview, ChapterAnalysis, AnalysisJob } from "../../../../lib/types";

export default function OverviewPage() {
  const { bookId } = useParams<{ bookId: string }>();
  return <OverviewContent key={bookId} bookId={bookId} />;
}

function OverviewContent({ bookId }: { bookId: string }) {
  const [overview, setOverview] = useState<BookOverview>();
  const [message, setMessage] = useState("");
  const [detail, setDetail] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [retryingChapterId, setRetryingChapterId] = useState<number | null>(null);
  const generationStarted = useRef(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const routeRef = useRef(bookId);
  useEffect(() => { routeRef.current = bookId; generationStarted.current = false; }, [bookId]);

  const load = useCallback(async () => {
    const result = await apiJson<BookOverview>(`/books/${bookId}/overview`);
    if (routeRef.current === bookId) setOverview(result);
    return result;
  }, [bookId]);

  const generate = useCallback(async () => {
    setMessage("");
    setDetail(null);
    try {
      const result = await apiJson<BookOverview>(`/books/${bookId}/analyses`, { method: "POST" });
      if (routeRef.current !== bookId) return;
      setOverview(result);
      setJobId(result.analysis_job?.id ?? null);
      setMessage("");
    } catch (error) {
      const described = describeRequestError(error, "章节分析启动失败。");
      setMessage(described.message);
      setDetail(described.detail);
      const latest = await load().catch(() => null);
      if (latest && routeRef.current === bookId && isActiveAnalysisJob(latest.analysis_job)) {
        setJobId(latest.analysis_job!.id);
      }
    }
  }, [bookId, load]);

  useEffect(() => {
    let active = true;
    apiJson<BookOverview>(`/books/${bookId}/overview`)
      .then((result) => {
        if (!active) return;
        setOverview(result);
        setJobId(result.access_scope === "owned" && isActiveAnalysisJob(result.analysis_job) ? result.analysis_job!.id : null);
        if (result.access_scope === "owned" && result.analysis_job && !isActiveAnalysisJob(result.analysis_job) && result.analysis_job.status !== "succeeded") {
          setMessage(analysisJobMessage(result.analysis_job));
        }
        const shouldGenerate = result.access_scope === "owned" && (!result.analysis_job || result.analysis_job.status === "succeeded")
          && result.chapters.some((chapter) => chapter.generation_status === "pending" || chapter.generation_status === "stale");
        if (shouldGenerate && !generationStarted.current) {
          generationStarted.current = true;
          void generate();
        }
      })
      .catch((error) => {
        if (!active) return;
        const described = describeRequestError(error, "无法读取章节总览。");
        setMessage(described.message);
        setDetail(described.detail);
      })
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [bookId, generate]);

  const allChapters = overview?.chapters ?? [];
  const chapterCount = overview?.chapter_count ?? 0;
  const isAnalyzing = isActiveAnalysisJob(overview?.analysis_job) || allChapters.some(({ generation_status }) => generation_status === "pending" || generation_status === "generating" || generation_status === "stale");
  const hasAnalysisIssues = allChapters.some(({ generation_status }) => generation_status === "failed" || generation_status === "insufficient_evidence");
  const showProgressPanel = overview?.access_scope === "owned" && (isAnalyzing || hasAnalysisIssues);
  const onTerminal = useCallback(async (job: AnalysisJob) => {
    await load();
    if (routeRef.current !== bookId) return;
    setRetryingChapterId(null);
    setMessage(analysisJobMessage(job));
  }, [bookId, load]);
  const { isTracking, trackingError } = useAnalysisJob({
    bookId, jobId, onTerminal, onUpdate: async () => { await load(); },
  });

  async function retry(chapterId: number) {
    setRetryingChapterId(chapterId);
    setMessage("正在重新分析这一章，结果会自动更新。");
    setDetail(null);
    try {
      const updated = await apiJson<ChapterAnalysis>(`/books/${bookId}/chapters/${chapterId}/analysis/retry`, { method: "POST" });
      if (routeRef.current !== bookId) return;
      await load();
      if (routeRef.current !== bookId) return;
      setJobId(updated.analysis_job?.id ?? null);
      if (!updated.analysis_job) setRetryingChapterId(null);
    } catch (error) {
      if (routeRef.current !== bookId) return;
      setRetryingChapterId(null);
      const described = describeRequestError(error, "重新分析失败。");
      setMessage(described.message);
      setDetail(described.detail);
      const latest = await load().catch(() => null);
      if (latest && isActiveAnalysisJob(latest.analysis_job)) setJobId(latest.analysis_job!.id);
    }
  }

  if (loading && !overview) return <main className="state-page"><p>正在建立全书章节总览…</p></main>;
  if (!overview) return <main className="state-page"><p role="alert">{message}</p><Link href="/">返回首页</Link></main>;

  const isWritable = overview.access_scope === "owned";
  const configurationNeeded = message.includes("配置 OpenAI") || message.includes("配置 DeepSeek") || message.includes("模型");
  return (
    <div className="reading-shell book-overview-shell">
      <main className="overview-main">
        <nav className="top-nav" aria-label="全书操作"><Link className="top-nav-back" href="/" aria-label="返回首页"><span aria-hidden="true">←</span><span>返回首页</span></Link><div>{isWritable && <><a href={`/books/${bookId}/chapters`}>编辑章节</a><a href="/settings">模型设置</a></>}</div></nav>
        {!showProgressPanel && <BookSummaryHeader overview={overview} />}
        {trackingError && <p role="alert">{trackingError}</p>}
        {overview.analysis_job && !isTracking && ["failed", "interrupted", "superseded"].includes(overview.analysis_job.status) && isWritable && (
          <button type="button" className="secondary-button" onClick={() => void generate()}>重新分析全书</button>
        )}
        {message && (
          <div className={`inline-message ${configurationNeeded ? "message-warning" : ""}`} role="status">
            <span>{message}</span>
            {detail && message && (
              <details className="failure-detail">
                <summary>技术细节</summary>
                <pre>{detail}</pre>
              </details>
            )}
            {configurationNeeded && <a href="/settings">前往配置 →</a>}
          </div>
        )}
        {showProgressPanel && <AnalysisProgressPanel chapters={allChapters} chapterCount={chapterCount} onRetry={isWritable ? retry : undefined} retryingChapterId={retryingChapterId} />}
        {!showProgressPanel && (
          <section className="chapter-overview-list" aria-label="章节总览">
            <div className="list-heading"><h2>章节</h2></div>
            <ChapterOverviewList bookId={bookId} chapters={allChapters} onRetry={isWritable ? retry : undefined} retryingChapterId={retryingChapterId} />
          </section>
        )}
      </main>
    </div>
  );
}
