"use client";

import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";

import { SourceReaderContent } from "../../../../components/SourceReaderContent";
import { apiJson } from "../../../../lib/api";
import { sourceReaderPresentation } from "../../../../lib/source-reader";
import type { Book, SourceReaderTarget } from "../../../../lib/types";

export default function SourceReaderPage() {
  const { bookId } = useParams<{ bookId: string }>();
  const searchParams = useSearchParams();
  const rawPage = Number(searchParams.get("page"));
  const href = searchParams.get("href");
  const fragment = searchParams.get("fragment");
  const rawSpine = Number(searchParams.get("spine"));
  const page = Number.isInteger(rawPage) && rawPage > 0 ? rawPage : 1;
  const spineIndex = Number.isInteger(rawSpine) && rawSpine > 0 ? rawSpine - 1 : null;
  const hasEpubLocator = href !== null || fragment !== null || spineIndex !== null;
  const chapterId = searchParams.get("chapter");
  const returnHref = chapterId ? `/books/${bookId}/chapters/${chapterId}` : `/books/${bookId}/overview`;
  const [book, setBook] = useState<Book>();
  const [error, setError] = useState("");
  useEffect(() => {
    apiJson<Book>(`/books/${bookId}`).then(setBook).catch((reason) => setError(reason.message || "无法读取原书信息"));
  }, [bookId]);
  const sourceFormat = book?.source_format || "pdf";
  const target: SourceReaderTarget = sourceFormat === "epub"
    ? {
        format: "epub",
        locator: { href, fragment, cfi: null, spineIndex },
        quote: null,
        surroundingText: null,
        requestId: 0,
      }
    : { format: "pdf", page, quote: null, requestId: 0 };
  const presentation = sourceReaderPresentation(target);

  return (
    <main className="source-reader-page">
      <nav className="top-nav"><a href={returnHref}>← 返回章节分析</a><span>作者原文 · {presentation.location}</span></nav>
      <header className="source-reader-header"><span className="eyebrow">Original source</span><h1>在原书中阅读</h1><p>{error || presentation.description}</p></header>
      {book && (
        <SourceReaderContent
          bookId={bookId}
          target={target}
          restoreProgress={sourceFormat === "epub" && !hasEpubLocator}
          discussion={book.access_scope === "owned" ? { chapterSummary: "" } : undefined}
        />
      )}
    </main>
  );
}
