"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import { useSystemColorScheme } from "../lib/use-system-color-scheme";
import { findTextQuoteRange } from "../lib/epub-quote-range";

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

export function PdfReader({
  data,
  page,
  quote,
  surroundingText,
  onError,
}: {
  data: ArrayBuffer;
  page: number;
  quote?: string | null;
  surroundingText?: string | null;
  onError: (message: string) => void;
}) {
  const colorScheme = useSystemColorScheme();
  const [numPages, setNumPages] = useState(0);
  const [pageNumber, setPageNumber] = useState(Math.max(1, page));
  const [scale, setScale] = useState(1);
  const [readerWidth, setReaderWidth] = useState<number>();
  const canvas = useRef<HTMLDivElement>(null);
  const file = useMemo(() => ({ data: new Uint8Array(data) }), [data]);

  const displayedPage = numPages > 0 ? Math.min(pageNumber, numPages) : pageNumber;
  const citationVisible = Boolean(quote) && displayedPage === page;

  useEffect(() => {
    const container = canvas.current;
    if (!container || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      const width = Math.floor(entry.contentRect.width);
      if (width > 0) setReaderWidth(width);
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  useEffect(() => () => {
    if (citationVisible) globalThis.CSS?.highlights?.delete("bookthinking-pdf-quote");
  }, [citationVisible, quote, scale]);

  function highlightQuote() {
    const container = canvas.current;
    const layer = container?.querySelector<HTMLElement>(".textLayer");
    if (!citationVisible || !quote || !container || !layer || !globalThis.CSS?.highlights) return;
    const range = findTextQuoteRange(layer, quote, surroundingText);
    if (!range) return;
    CSS.highlights.set("bookthinking-pdf-quote", new Highlight(range));
    container.scrollTop += range.getBoundingClientRect().top - container.getBoundingClientRect().top - 48;
  }

  return (
    <section
      className="source-reader source-reader-pdf"
      aria-label="原书 PDF 阅读器"
      data-color-scheme={colorScheme}
    >
      <div className="source-reader-toolbar">
        <button
          type="button"
          onClick={() => setPageNumber((value) => Math.max(1, value - 1))}
          disabled={displayedPage <= 1}
        >
          上一页
        </button>
        <span>第 {displayedPage} / {numPages || "…"} 页</span>
        <button
          type="button"
          onClick={() => setPageNumber((value) => Math.min(numPages, value + 1))}
          disabled={numPages === 0 || displayedPage >= numPages}
        >
          下一页
        </button>
        <button
          type="button"
          aria-label="缩小"
          onClick={() => setScale((value) => Math.max(0.75, value - 0.25))}
          disabled={scale <= 0.75}
        >
          −
        </button>
        <span>{Math.round(scale * 100)}%</span>
        <button
          type="button"
          aria-label="放大"
          onClick={() => setScale((value) => Math.min(2, value + 0.25))}
          disabled={scale >= 2}
        >
          ＋
        </button>
      </div>
      <div className="source-reader-pdf-canvas" ref={canvas}>
        <Document
          file={file}
          loading={<p role="status">正在解析 PDF…</p>}
          error={<p role="alert">原书 PDF 无法加载</p>}
          onLoadSuccess={({ numPages: loadedPages }) => {
            setNumPages(loadedPages);
            setPageNumber((value) => Math.min(Math.max(1, value), loadedPages));
          }}
          onLoadError={() => onError("原书 PDF 无法加载")}
        >
          <Page pageNumber={displayedPage} width={readerWidth} scale={scale} onRenderTextLayerSuccess={highlightQuote} />
        </Document>
      </div>
    </section>
  );
}
