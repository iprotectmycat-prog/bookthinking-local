import type { SourceFormat, SourceSpan } from "../lib/types";

export function SourceEvidence({
  source,
  sourceFormat = "pdf",
  onOpenSource,
}: {
  source: SourceSpan;
  sourceFormat?: SourceFormat;
  onOpenSource: (source: SourceSpan, trigger?: HTMLElement) => void;
}) {
  const location =
    sourceFormat === "epub" ? `章节片段 ${source.source_page}` : `第 ${source.source_page} 页`;
  const origin = source.source_chapter_title ? `${source.source_chapter_title} · ${location}` : location;

  return (
    <figure className="source-evidence author-source">
      <figcaption>
        <span className="source-meta">作者原文 · {origin}</span>
        <button type="button" className="source-reader-btn" aria-label="在原书中阅读" onClick={(event) => onOpenSource(source, event.currentTarget)}>在原书中阅读 <span aria-hidden="true">→</span></button>
      </figcaption>
      <blockquote>{source.quote}</blockquote>
    </figure>
  );
}
