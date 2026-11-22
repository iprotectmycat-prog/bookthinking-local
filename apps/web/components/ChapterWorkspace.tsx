"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { findAdjacentReadable, findNextReadyChapter } from "../lib/chapter-navigation";
import { parseEpubSourceLocator } from "../lib/epub-locator";
import type { ChapterAnalysis, ChapterOverview, SourceFormat, SourceReaderTarget, SourceSpan } from "../lib/types";
import { ChapterReadingView } from "./ChapterReadingView";
import { ChapterSidebar } from "./ChapterSidebar";
import { SourceReaderPanel } from "./SourceReaderPanel";

type ChapterWorkspaceProps = {
  analysis: ChapterAnalysis;
  bookId: string;
  bookTitle?: string;
  sourceFormat: SourceFormat;
  chapters: ChapterOverview[];
  onRetry?: () => void;
  retrying?: boolean;
  sourceChatEnabled?: boolean;
};

export function ChapterWorkspace({
  analysis,
  bookId,
  bookTitle,
  sourceFormat,
  chapters,
  onRetry,
  retrying = false,
  sourceChatEnabled = false,
}: ChapterWorkspaceProps) {
  const [sourceTarget, setSourceTarget] = useState<SourceReaderTarget | null>(null);
  const [sourceOpen, setSourceOpen] = useState(false);
  const [directoryOpen, setDirectoryOpen] = useState(true);
  const sourceTrigger = useRef<HTMLElement | null>(null);
  const isReady = analysis.generation_status === "ready";

  // 后端的 previous/next 是按序号直取相邻项，会把读者送进没有正文的结构页。
  // 这里改用跳过 skipped 的版本；返回 null 表示「该方向已无可读章节」，
  // 不能再回退到后端值 —— 那等于把刚跳过的空白页又请回来。
  // 只有当本章根本不在列表里（数据不一致）时才退回后端值，避免导航彻底消失。
  const inChapterList = chapters.some((chapter) => chapter.id === analysis.chapter_id);
  const previousId = inChapterList
    ? findAdjacentReadable(chapters, analysis.chapter_id, -1)
    : analysis.previous_chapter_id;
  const nextId = inChapterList
    ? findAdjacentReadable(chapters, analysis.chapter_id, 1)
    : analysis.next_chapter_id;
  const nextReadableId = isReady ? null : findNextReadyChapter(chapters, analysis.chapter_id);

  function targetFor(
    position: number,
    sourceLocator: string | null | undefined,
    quote: string | null,
    surroundingText: string | null,
  ): SourceReaderTarget {
    const requestId = (sourceTarget?.requestId ?? 0) + 1;
    return sourceFormat === "epub"
      ? {
          format: "epub",
          locator: parseEpubSourceLocator(sourceLocator, position),
          quote,
          surroundingText,
          requestId,
        }
      : { format: "pdf", page: position, quote, surroundingText, requestId };
  }

  function openSource(source: SourceSpan, trigger?: HTMLElement) {
    sourceTrigger.current = trigger ?? (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    setSourceTarget(targetFor(
      source.source_page,
      source.source_locator,
      source.quote,
      source.surrounding_text,
    ));
    setSourceOpen(true);
  }

  function openChapterSource(trigger: HTMLElement) {
    sourceTrigger.current = trigger;
    setSourceTarget(targetFor(analysis.source_start_page, analysis.source_locator, null, null));
    setSourceOpen(true);
  }

  const closeSource = useCallback(() => {
    setSourceOpen(false);
  }, []);

  useEffect(() => {
    if (!sourceOpen) {
      sourceTrigger.current?.focus({ preventScroll: true });
      sourceTrigger.current = null;
      return;
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !event.defaultPrevented) closeSource();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [sourceOpen, closeSource]);

  return (
    <div className={`reading-shell chapter-workspace${directoryOpen ? "" : " is-directory-collapsed"}${sourceOpen ? " is-source-open" : ""}`}>
      <ChapterSidebar
        bookId={bookId}
        chapters={chapters}
        activeId={analysis.chapter_id}
        bodyOnly
        isOpen={directoryOpen}
        onOpenChange={setDirectoryOpen}
      />
      <main className="chapter-main">
        <nav className="top-nav" aria-label="章节操作">
          <a className="chapter-book-link" href={`/books/${bookId}/overview`}>
            {bookTitle ? `《${bookTitle}》` : "书籍首页"}
          </a>
          <button
            type="button"
            className="top-nav-source-reader"
            onClick={(event) => openChapterSource(event.currentTarget)}
          >
            阅读原文
          </button>
        </nav>
        <ChapterReadingView
          analysis={analysis}
          sourceFormat={sourceFormat}
          onOpenSource={openSource}
          onRetry={onRetry}
          retrying={retrying}
          nextReadableId={nextReadableId}
          bookId={bookId}
        />
        {(previousId || nextId) && (
          <nav className="chapter-pagination" aria-label="前后章节">
            {previousId && <a href={`/books/${bookId}/chapters/${previousId}`}>← 上一章</a>}
            {nextId && <a className="chapter-pagination-next" href={`/books/${bookId}/chapters/${nextId}`}>下一章 →</a>}
          </nav>
        )}
      </main>
      <SourceReaderPanel
        bookId={bookId}
        target={sourceTarget}
        isOpen={sourceOpen}
        discussion={sourceChatEnabled ? {
          chapterSummary: isReady
            ? analysis.reading_record?.teaching?.chapter_summary || analysis.one_sentence_conclusion || analysis.short_summary
            : "",
        } : undefined}
        onClose={closeSource}
      />
    </div>
  );
}
