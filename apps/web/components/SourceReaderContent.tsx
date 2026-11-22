"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import type { SourceReaderTarget } from "../lib/types";
import { EpubReader } from "./EpubReader";

const PdfReader = dynamic(
  () => import("./PdfReader").then((module) => module.PdfReader),
  {
    ssr: false,
    loading: () => <p role="status">正在准备 PDF 阅读器…</p>,
  },
);

const sourceRequests = new Map<string, Promise<ArrayBuffer>>();

function loadSource(bookId: string) {
  const pending = sourceRequests.get(bookId);
  if (pending) {
    return pending;
  }

  const request = fetch(`/local/books/${bookId}/file`).then(async (response) => {
    if (!response.ok) {
      throw new Error("source request failed");
    }
    return response.arrayBuffer();
  });
  sourceRequests.set(bookId, request);
  void request.then(
    () => sourceRequests.delete(bookId),
    () => sourceRequests.delete(bookId),
  );
  return request;
}

export function SourceReaderContent({
  bookId,
  target,
  restoreProgress = false,
  discussion,
}: {
  bookId: string;
  target: SourceReaderTarget;
  restoreProgress?: boolean;
  discussion?: { chapterSummary: string };
}) {
  const [result, setResult] = useState<{
    bookId: string;
    data?: ArrayBuffer;
    error?: string;
  }>();

  useEffect(() => {
    let active = true;

    loadSource(bookId)
      .then((data) => {
        if (active) {
          setResult({ bookId, data });
        }
      })
      .catch(() => {
        if (active) {
          setResult({ bookId, error: "原书文件无法加载" });
        }
      });

    return () => {
      active = false;
    };
  }, [bookId]);

  if (result?.bookId === bookId && result.error) {
    return <p role="alert">{result.error}</p>;
  }
  if (result?.bookId !== bookId || !result.data) {
    return <p role="status">正在读取原书…</p>;
  }

  return target.format === "epub" ? (
    <EpubReader
      key={target.requestId}
      bookId={bookId}
      data={result.data}
      locator={target.locator}
      quote={target.quote}
      surroundingText={target.surroundingText}
      highlightRequestId={target.requestId}
      restoreProgress={restoreProgress}
      discussion={discussion}
      onError={(error) => setResult({ bookId, error })}
    />
  ) : (
    <PdfReader
      key={target.requestId}
      data={result.data}
      page={target.page}
      quote={target.quote}
      surroundingText={target.surroundingText}
      onError={(error) => setResult({ bookId, error })}
    />
  );
}
