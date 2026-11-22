import { Children, type ReactNode } from "react";
import type { ReadingRecord, ReadingTopic, SourceFormat, SourceSpan } from "../lib/types";
import { SourceEvidence } from "./SourceEvidence";

type EvidenceProps = {
  sourceFormat: SourceFormat;
  onOpenSource: (source: SourceSpan, trigger?: HTMLElement) => void;
};

export function ChapterProse({ children, className = "" }: { children: ReactNode; className?: string }) {
  const paragraphs: ReactNode[][] = [[]];
  Children.forEach(children, (child) => {
    if (typeof child !== "string") {
      if (child != null) paragraphs[paragraphs.length - 1].push(child);
      return;
    }
    child.split(/\r?\n(?:[ \t]*\r?\n)*/).forEach((text, index) => {
      if (index > 0) paragraphs.push([]);
      if (text) paragraphs[paragraphs.length - 1].push(text);
    });
  });
  return (
    <div className={`chapter-prose ${className}`.trim()}>
      {paragraphs.filter((paragraph) => paragraph.some((part) => typeof part !== "string" || part.trim()))
        .map((paragraph, index) => <p key={index}>{paragraph}</p>)}
    </div>
  );
}

export function EvidenceDisclosure({ label, sources, sourceFormat, onOpenSource }: EvidenceProps & {
  label: string;
  sources: SourceSpan[];
}) {
  if (!sources.length) return null;
  return (
    <details className="reading-disclosure">
      <summary>{label}</summary>
      {sources.map((source, index) => (
        <SourceEvidence key={index} source={source} sourceFormat={sourceFormat} onOpenSource={onOpenSource} />
      ))}
    </details>
  );
}

function topicCitations(topic: ReadingTopic) {
  const matches = (topic.citations ?? []).flatMap(({ anchor, sources }) => {
    const start = topic.explanation.indexOf(anchor);
    if (!anchor || !sources.length || start < 0 || start !== topic.explanation.lastIndexOf(anchor)) return [];
    return [{ start, end: start + anchor.length, sources }];
  }).sort((a, b) => a.start - b.start);
  let previousEnd = 0;
  return matches.filter(({ start, end }) => {
    if (start < previousEnd) return false;
    previousEnd = end;
    return true;
  });
}

export function countTeachingCitations(teaching: ReadingRecord["teaching"]) {
  return (teaching?.topics ?? []).reduce((total, topic) => {
    const citations = topicCitations(topic).reduce((count, { sources }) => count + sources.length, 0);
    const caseCitations = (topic.cases ?? []).reduce((count, example) => count + example.sources.length, 0);
    return total + citations + caseCitations;
  }, 0);
}

export function ReadingCitationLinks({ sources, firstNumber, onOpenSource }: Pick<EvidenceProps, "onOpenSource"> & {
  sources: SourceSpan[];
  firstNumber: number;
}) {
  if (!sources.length) return null;
  return (
    <sup className="reading-citation-links">
      {sources.map((source, index) => {
        const number = firstNumber + index;
        return (
          <button
            key={number}
            type="button"
            className="reading-citation"
            aria-label={`查看引用 ${number} 的原文`}
            onClick={(event) => onOpenSource(source, event.currentTarget)}
          >{number}</button>
        );
      })}
    </sup>
  );
}

function numberCitations(teaching: NonNullable<ReadingRecord["teaching"]>) {
  let nextNumber = 1;
  const topics = [];
  for (const topic of teaching.topics) {
    const citations = [];
    for (const citation of topicCitations(topic)) {
      citations.push({ ...citation, firstNumber: nextNumber });
      nextNumber += citation.sources.length;
    }
    const cases = [];
    for (const example of topic.cases ?? []) {
      cases.push({ ...example, firstNumber: nextNumber });
      nextNumber += example.sources.length;
    }
    topics.push({ ...topic, citations, cases });
  }
  return topics;
}

function TeachingTopics({ teaching, sourceFormat, onOpenSource }: EvidenceProps & {
  teaching: NonNullable<ReadingRecord["teaching"]>;
}) {
  const evidenceProps = { sourceFormat, onOpenSource };
  const question = teaching.open_question;

  return (
    <>
      {numberCitations(teaching).map((topic, index) => {
        let cursor = 0;
        const citedSources = new Set<number>();
        const explanation = topic.citations.flatMap(({ start, end, sources, firstNumber }) => {
          const preceding = topic.explanation.slice(cursor, start);
          const sentence = topic.explanation.slice(start, end);
          const lastSpace = Math.max(sentence.lastIndexOf(" "), sentence.lastIndexOf("\n"));
          const tailStart = Math.max(lastSpace + 1, sentence.length - 7);
          cursor = end;
          for (const source of sources) citedSources.add(source.id);
          return [
            preceding + sentence.slice(0, tailStart),
            <span key={start} className="reading-citation-tail">
              {sentence.slice(tailStart)}
              <ReadingCitationLinks sources={sources} firstNumber={firstNumber} onOpenSource={onOpenSource} />
            </span>,
          ];
        });
        return (
          <article key={index} className="skill-unit chapter-topic" id={`topic-${index + 1}`} tabIndex={-1}>
            <h3><span aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>{topic.title}</h3>
            <div className="chapter-topic-body">
              {topic.key_understanding !== topic.title && <p className="topic-understanding">{topic.key_understanding}</p>}
              <ChapterProse>{explanation}{topic.explanation.slice(cursor)}</ChapterProse>
              {(topic.source_figures ?? (topic.source_figure ? [topic.source_figure] : [])).map((figure) => (
                <details key={figure.src} className="reading-disclosure">
                  <summary>{figure.caption}</summary>
                  <figure className="source-evidence">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={figure.src} alt={figure.alt} loading="lazy" style={{ maxWidth: "100%", height: "auto" }} />
                  </figure>
                </details>
              ))}
              {topic.cases.map((example, caseIndex) => (
                <details key={caseIndex} className="reading-disclosure author-case">
                  <summary><span className="author-case-label">案例：</span>{example.title}</summary>
                  <ChapterProse>
                    {[example.description, example.illustrates].filter(Boolean).join("\n")}
                    <ReadingCitationLinks sources={example.sources} firstNumber={example.firstNumber} onOpenSource={onOpenSource} />
                  </ChapterProse>
                </details>
              ))}
              <EvidenceDisclosure label="查看观点依据" sources={topic.sources.filter(({ id }) => !citedSources.has(id))} {...evidenceProps} />
            </div>
          </article>
        );
      })}
      {teaching.takeaway && <ChapterProse className="chapter-takeaway">{teaching.takeaway}</ChapterProse>}
      {question && (
        <details className="reading-disclosure">
          <summary>{question.attribution === "author_question" ? "作者留下的问题" : "AI 延伸问题"}</summary>
          <p>{question.question}</p>
          <EvidenceDisclosure label="查看问题依据" sources={question.sources} {...evidenceProps} />
        </details>
      )}
    </>
  );
}

export function SkillChapterReading({ record, sourceFormat, onOpenSource }: EvidenceProps & {
  record: ReadingRecord;
}) {
  const evidenceProps = { sourceFormat, onOpenSource };
  return <section className="chapter-section skill-reading" aria-label="核心观点">
    <h2>核心观点</h2>
    {record.teaching?.topics.length ? <TeachingTopics teaching={record.teaching} {...evidenceProps} /> : <>
    {record.reading_route && <ChapterProse>{record.reading_route}</ChapterProse>}
    {record.units.map((unit, index) => <article key={index} className="skill-unit" id={`topic-${index + 1}`} tabIndex={-1}>
      <h3>{unit.title}</h3>
      <ChapterProse>{unit.explanation}</ChapterProse>
      {unit.steps.length > 0 && <ol>{unit.steps.map((step, i) => <li key={i}>{step}</li>)}</ol>}
      {unit.examples.length > 0 && <div><h4>书中例子</h4>{unit.examples.map((example, i) => <p key={i}>{example}</p>)}</div>}
      {unit.limitations.length > 0 && <div><h4>条件与限制</h4>{unit.limitations.map((limit, i) => <p key={i}>{limit}</p>)}</div>}
      <EvidenceDisclosure label={`回查原文 · ${unit.sources.length} 处`} sources={unit.sources} {...evidenceProps} />
    </article>)}
    </>}
  </section>;
}
