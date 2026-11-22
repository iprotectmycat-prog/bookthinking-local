import Link from "next/link";
import { ArrowRight } from "@phosphor-icons/react";

import { describeFailure } from "../lib/analysis-message";
import type { ChapterOverview } from "../lib/types";
import { AnalysisStatus } from "./AnalysisStatus";

const RETRYABLE = new Set(["failed", "stale", "insufficient_evidence"]);

export function ChapterOverviewCard({ bookId, chapter, onRetry, retrying = false, level = "chapter" }: { bookId: string; chapter: ChapterOverview; onRetry?: (id: number) => void; retrying?: boolean; level?: "chapter" | "section" }) {
  const sectionClass = level === "section" ? " is-section" : "";
  const cardId = `chapter-${chapter.id}`;
  if (chapter.generation_status === "ready") {
    const points = chapter.core_idea_titles ?? [];
    const hasPreview = points.length > 0 || Boolean(chapter.role_in_book);
    const chapterUrl = `/books/${bookId}/chapters/${chapter.id}`;
    return (
      <article className={`chapter-card is-linked${sectionClass}${hasPreview ? " has-preview" : ""}`} id={cardId}>
        <Link className="chapter-card-link" href={chapterUrl} aria-label={`${level === "section" ? "阅读本节" : "阅读本章"}：${chapter.title}`}>
          <h3 id={`${cardId}-title`}>{chapter.title}</h3>
          <span className="chapter-card-action" aria-hidden="true">{level === "section" ? "阅读本节" : "阅读本章"} <ArrowRight size={18} /></span>
        </Link>
        <p className="chapter-conclusion">{chapter.one_sentence_conclusion}</p>
        {hasPreview && (
          <details className="chapter-preview reading-disclosure">
            <summary>
              <span className="preview-closed">展开提要{points.length > 0 && ` · ${points.length} 个观点`}</span>
              <span className="preview-open">收起提要</span>
            </summary>
            {points.length > 0 && (
              <ol className="idea-preview" aria-label="本章核心观点" role="list">
                {points.map((point, index) => (
                  <li key={point}>
                    <span aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
                    <Link href={`${chapterUrl}#topic-${index + 1}`}>{point}</Link>
                  </li>
                ))}
              </ol>
            )}
            {chapter.role_in_book && <p className="chapter-card-role">{chapter.role_in_book}</p>}
          </details>
        )}
      </article>
    );
  }

  const { message, detail } = describeFailure(chapter.generation_status, chapter.failure_reason);
  return (
    <article className={`chapter-card${sectionClass}`} id={cardId}>
      <div className="chapter-card-topline"><AnalysisStatus status={chapter.generation_status} /></div>
      <h3>{chapter.title}</h3>
      <div className="chapter-placeholder">
        <p>{message}</p>
        {detail && (
          <details className="failure-detail">
            <summary>技术细节</summary>
            <pre>{detail}</pre>
          </details>
        )}
        {onRetry && RETRYABLE.has(chapter.generation_status) && (
          <button className="secondary-button" disabled={retrying} onClick={() => onRetry(chapter.id)}>{retrying ? "正在重新分析…" : "重新分析本章"}</button>
        )}
      </div>
    </article>
  );
}
