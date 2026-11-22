"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";

import { ChapterWorkspace } from "../../../../../components/ChapterWorkspace";
import { apiJson } from "../../../../../lib/api";
import { getBookDisplay } from "../../../../../lib/book-display";
import { describeRequestError } from "../../../../../lib/analysis-message";
import { useAnalysisJob, analysisJobMessage, isActiveAnalysisJob } from "../../../../../lib/use-analysis-job";
import type { BookOverview, ChapterAnalysis, AnalysisJob } from "../../../../../lib/types";

export default function ChapterPage() {
  const { bookId, chapterId } = useParams<{ bookId: string; chapterId: string }>();
  return <ChapterContent key={bookId + ":" + chapterId} bookId={bookId} chapterId={chapterId} />;
}

function ChapterContent({ bookId, chapterId }: { bookId: string; chapterId: string }) {
  const [overview, setOverview] = useState<BookOverview>();
  const [analysis, setAnalysis] = useState<ChapterAnalysis>();
  const [error, setError] = useState("");
  const [retrying, setRetrying] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const route = bookId + ":" + chapterId;
  const routeRef = useRef(route);
  useEffect(() => { routeRef.current = route; }, [route]);
  const load = useCallback(async () => {
    const [book, chapter] = await Promise.all([
      apiJson<BookOverview>(`/books/${bookId}/overview`),
      apiJson<ChapterAnalysis>(`/books/${bookId}/chapters/${chapterId}/analysis`),
    ]);
    if (routeRef.current === route) { setOverview(book); setAnalysis(chapter); }
    return book;
  }, [bookId, chapterId, route]);
  const onTerminal = useCallback(async (job: AnalysisJob) => {
    try {
      await load();
    } catch (reason) {
      const status = typeof reason === "object" && reason !== null && "status" in reason ? reason.status : null;
      if (status !== 403 && status !== 404) throw reason;
      if (routeRef.current !== route) return;
      setError("章节结构或访问权限已变化，请返回章节总览。");
    }
    if (routeRef.current !== route) return;
    setRetrying(false);
    setMessage(analysisJobMessage(job));
  }, [load, route]);
  const { isTracking, trackingError } = useAnalysisJob({ bookId, jobId, onTerminal, onUpdate: async () => { await load(); } });

  useEffect(() => {
    let active = true;
    Promise.all([
      apiJson<BookOverview>(`/books/${bookId}/overview`),
      apiJson<ChapterAnalysis>(`/books/${bookId}/chapters/${chapterId}/analysis`),
    ]).then(([book, chapter]) => {
      if (!active) return;
      setOverview(book);
      setAnalysis(chapter);
      setError("");
      setJobId(book.access_scope === "owned" && isActiveAnalysisJob(book.analysis_job) ? book.analysis_job!.id : null);
      if (book.access_scope === "owned" && book.analysis_job && !isActiveAnalysisJob(book.analysis_job) && book.analysis_job.status !== "succeeded") {
        setMessage(analysisJobMessage(book.analysis_job));
      }
    }).catch((reason) => {
      if (!active) return;
      setError(describeRequestError(reason, "无法读取章节分析。").message);
    });
    return () => { active = false; };
  }, [bookId, chapterId]);

  const retry = useCallback(async () => {
    setRetrying(true);
    setMessage("");
    try {
      const updated = await apiJson<ChapterAnalysis>(`/books/${bookId}/chapters/${chapterId}/analysis/retry`, { method: "POST" });
      if (routeRef.current !== route) return;
      setAnalysis(updated);
      setJobId(updated.analysis_job?.id ?? null);
      if (!updated.analysis_job) setRetrying(false);
    } catch (reason) {
      if (routeRef.current !== route) return;
      setRetrying(false);
      setMessage(describeRequestError(reason, "重新分析失败，请稍后再试。").message);
      const latest = await load().catch(() => null);
      if (latest && isActiveAnalysisJob(latest.analysis_job)) setJobId(latest.analysis_job!.id);
    }
  }, [bookId, chapterId, load, route]);

  if (error) return <main className="state-page"><p role="alert">{error}</p><a href={`/books/${bookId}/overview`}>返回章节总览</a></main>;
  if (!overview || !analysis) return <main className="state-page"><p>正在打开章节分析…</p></main>;

  const isWritable = overview.access_scope === "owned";

  return (
    <>
      {message && <p className="inline-message" role="status">{message}</p>}
      {trackingError && <p role="alert">{trackingError}</p>}
      <ChapterWorkspace
        analysis={analysis}
        bookId={bookId}
        bookTitle={getBookDisplay(overview.book_title, overview.source_format).title}
        sourceFormat={overview.source_format}
        chapters={overview.chapters}
        sourceChatEnabled={isWritable}
        onRetry={isWritable ? retry : undefined}
        retrying={retrying || isTracking}
      />
    </>
  );
}
