import type { AttributedStatement as AttributedStatementData, SourceFormat, SourceSpan } from "../lib/types";
import { SourceEvidence } from "./SourceEvidence";

const TYPE_LABELS: Record<AttributedStatementData["content_type"], string> = {
  book_summary: "原书概述",
  ai_synthesis: "AI 推导",
  legacy_summary: "旧版概述",
};

function groupSourcesByChapter(sources: SourceSpan[]) {
  const groups: Array<{ key: string; title: string; sources: SourceSpan[] }> = [];
  for (const source of sources) {
    const key = String(source.source_chapter_id ?? "current");
    const title = source.source_chapter_title || "本节原文";
    const existing = groups.find((group) => group.key === key);
    if (existing) existing.sources.push(source);
    else groups.push({ key, title, sources: [source] });
  }
  return groups;
}

export function AttributedStatement({
  statement,
  label,
  sourceFormat,
  onOpenSource,
}: {
  statement: AttributedStatementData;
  label: string;
  sourceFormat: SourceFormat;
  onOpenSource: (source: SourceSpan) => void;
}) {
  return (
    <section className="attributed-statement">
      <div className="attributed-statement-heading">
        <h3>{label}</h3>
        <span className={`content-type type-${statement.content_type}`}>{TYPE_LABELS[statement.content_type]}</span>
      </div>
      <p>{statement.text}</p>
      {groupSourcesByChapter(statement.sources).map((group) => (
        <section className="statement-source-group" key={group.key}>
          <h4>{group.title}</h4>
          {group.sources.map((source) => (
            <SourceEvidence key={source.id} source={source} sourceFormat={sourceFormat} onOpenSource={onOpenSource} />
          ))}
        </section>
      ))}
    </section>
  );
}
