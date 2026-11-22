import type { BookOverview } from "../lib/types";
import { getBookDisplay } from "../lib/book-display";
import { DoubanBookLink } from "./DoubanBookLink";

export function BookSummaryHeader({ overview }: { overview: BookOverview }) {
  const display = getBookDisplay(overview.book_title, overview.source_format);
  const format = overview.source_format.toUpperCase();
  const filenameAuthor = display.metadata === format ? "" : display.metadata.slice(0, -(` · ${format}`.length));
  const editionMetadata = [overview.book_authors || filenameAuthor, overview.book_publisher, overview.book_composition].filter(Boolean);
  const summary = overview.synthesis?.reading_guide || overview.one_sentence_summary;

  return (
    <>
      <header className="book-header">
        <h1>{display.title}</h1>
        <div className="book-source-meta">
          {editionMetadata.map((item, index) => (
            <span className="book-edition-item" key={index}>{item}</span>
          ))}
          <DoubanBookLink bookId={overview.book_id} title={display.title} />
        </div>
      </header>
      <section className="book-intro" aria-label="全书总结">
        <h2>全书总结</h2>
        {!overview.synthesis?.reading_guide && overview.core_question && <p className="book-intro-question">{overview.core_question}</p>}
        <p className="skill-prose">{summary || "章节分析完成后将在这里形成全书总览。"}</p>
      </section>
    </>
  );
}
