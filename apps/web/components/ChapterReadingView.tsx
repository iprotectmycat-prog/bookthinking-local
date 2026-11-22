"use client";

import { useEffect } from "react";
import { describeFailure } from "../lib/analysis-message";
import type { AnalysisStatus as Status, ChapterAnalysis, SourceFormat, SourceSpan } from "../lib/types";
import { ChapterProse, countTeachingCitations, EvidenceDisclosure, ReadingCitationLinks, SkillChapterReading } from "./SkillChapterReading";
import { CoreIdeaSection } from "./CoreIdeaSection";
import { AttributedStatement } from "./AttributedStatement";

const RETRYABLE: Status[] = ["failed", "stale", "insufficient_evidence"];

export function ChapterReadingView({
  analysis,
  sourceFormat = "pdf",
  onOpenSource,
  onRetry,
  retrying = false,
  nextReadableId,
  bookId,
}: {
  analysis: ChapterAnalysis;
  sourceFormat?: SourceFormat;
  onOpenSource: (source: SourceSpan, trigger?: HTMLElement) => void;
  onRetry?: () => void;
  retrying?: boolean;
  nextReadableId?: number | null;
  bookId?: string;
}) {
  const isReady = analysis.generation_status === "ready";
  const record = analysis.reading_record;
  useEffect(() => {
    if (!isReady || !/^#topic-\d+$/.test(window.location.hash)) return;
    const topic = document.getElementById(window.location.hash.slice(1));
    topic?.scrollIntoView({ block: "start", behavior: "instant" });
    topic?.focus({ preventScroll: true });
  }, [analysis.chapter_id, isReady]);
  const summary = record?.teaching?.chapter_summary || analysis.one_sentence_conclusion || analysis.short_summary;
  const header = (
    <header className="chapter-reading-header">
      <h1>{analysis.title}</h1>
      {isReady && (
        <>
          {summary && <ChapterProse className="chapter-summary-prose">{summary}</ChapterProse>}
          {!record?.teaching && analysis.chapter_question && <p className="chapter-summary-question">{analysis.chapter_question}</p>}
          {!record?.teaching && analysis.short_summary && analysis.short_summary !== summary && (
            <details className="reading-disclosure">
              <summary>展开本章概述</summary>
              <ChapterProse>{analysis.short_summary}</ChapterProse>
            </details>
          )}
          {record && <EvidenceDisclosure label="查看总结依据" sources={record.conclusion_sources} sourceFormat={sourceFormat} onOpenSource={onOpenSource} />}
        </>
      )}
    </header>
  );
  if (!isReady) {
    const { message, detail } = describeFailure(analysis.generation_status, analysis.failure_reason);
    const canRetry = RETRYABLE.includes(analysis.generation_status);
    return (
      <>
        {header}
        <section className="chapter-state" aria-label="本章状态">
          <p className="chapter-state-message">
            {analysis.generation_status === "skipped" && "未调用模型分析。"}
            {message}
          </p>
          {detail && (
            <details className="failure-detail">
              <summary>技术细节</summary>
              <pre>{detail}</pre>
            </details>
          )}
          <div className="chapter-state-actions">
            {canRetry && onRetry && (
              <button type="button" className="secondary-button" onClick={onRetry} disabled={retrying}>
                {retrying ? "正在重新分析…" : "重新分析本章"}
              </button>
            )}
            {nextReadableId && bookId && (
              <a className="primary-link" href={`/books/${bookId}/chapters/${nextReadableId}`}>
                跳到下一个可阅读章节 <span>→</span>
              </a>
            )}
          </div>
        </section>
      </>
    );
  }

  const role = analysis.role_in_book;
  const roleText = role?.text.trimEnd() ?? "";
  const roleTailStart = Math.max(roleText.lastIndexOf("\n") + 1, roleText.length - 7);

  return (
    <>
      {header}
      {record && <SkillChapterReading record={record} sourceFormat={sourceFormat} onOpenSource={onOpenSource} />}
      {!record && (analysis.core_ideas.length > 0 || analysis.argument_chain.length > 0) && (
        <section className="chapter-section chapter-legacy-ideas">
          <h2>核心观点</h2>
          {analysis.core_ideas.map((idea, index) => <CoreIdeaSection key={idea.id} idea={idea} number={index + 1} sourceFormat={sourceFormat} genre={analysis.genre} onOpenSource={onOpenSource} />)}
          {analysis.argument_chain.length > 0 && (
            <details className="reading-disclosure">
              <summary>查看本章论证</summary>
              {analysis.argument_chain.map((statement, index) => (
                <AttributedStatement key={index} statement={statement} label={`步骤 ${index + 1}`} sourceFormat={sourceFormat} onOpenSource={onOpenSource} />
              ))}
            </details>
          )}
        </section>
      )}
      {role && (
        <section className="chapter-section role-in-book-section" aria-label="本章在全书中的作用">
          <h2>本章在全书中的作用</h2>
          {role.content_type === "ai_synthesis" && <span className="content-type type-ai_synthesis">AI 推导</span>}
          <ChapterProse>
            {role.sources.length ? roleText.slice(0, roleTailStart) : roleText}
            {role.sources.length > 0 && (
              <span className="reading-citation-tail">
                {roleText.slice(roleTailStart)}
                <ReadingCitationLinks sources={role.sources} firstNumber={countTeachingCitations(record?.teaching) + 1} onOpenSource={onOpenSource} />
              </span>
            )}
          </ChapterProse>
        </section>
      )}
    </>
  );
}
