import type { AnalyzedBook } from "../lib/types";
import { getBookDisplay } from "../lib/book-display";

export function BookLibrary({ books, currentBookId, onDismissBook }: { books: AnalyzedBook[]; currentBookId: string; onDismissBook?: (bookId: string) => void }) {
  if (books.length === 0) return null;

  return (
    <section className="book-library" aria-label="已分析书籍">
      <h2>已分析书籍</h2>
      <ul>
        {books.map((book) => (
          <BookLibraryItem key={book.id} book={book} isActive={book.id === currentBookId} onDismissBook={onDismissBook} />
        ))}
      </ul>
    </section>
  );
}

function BookLibraryItem({ book, isActive, onDismissBook }: { book: AnalyzedBook; isActive: boolean; onDismissBook?: (bookId: string) => void }) {
  const display = getBookDisplay(book.filename, book.source_format);
  const [author, format] = display.metadata.split(" · ");

  return (
    <li className={`${isActive ? "is-active " : ""}${onDismissBook ? "has-dismiss" : ""}`}>
      <a
        href={`/books/${book.id}/overview`}
        aria-current={isActive ? "page" : undefined}
        aria-label={`${display.title} ${book.source_format.toUpperCase()}`}
      >
        <span className="book-title">{display.title}</span>
        <span className="book-metadata">{format ? `${author} · ` : ""}<small>{format || author}</small></span>
      </a>
      {onDismissBook && <button className="book-dismiss" type="button" aria-label={`从当前页面隐藏 ${display.title}`} onClick={() => onDismissBook(book.id)}>×</button>}
    </li>
  );
}
