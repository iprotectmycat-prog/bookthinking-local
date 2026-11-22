from app.services.analysis_providers import OverviewChapterInput, overview_role_text
import logging
import os
import sqlite3
from hashlib import sha256
from contextlib import closing, contextmanager
from json import dumps, loads
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Literal, Protocol

import keyring
from pydantic import BaseModel

from app.runtime import RuntimeSettings
from app.services.analysis_providers import AttributedStatementDraft, ChapterAnalysisDraft, CoreIdeaDraft, EvidenceDraft
from app.services.pypdf_parser import ParsedBook

logger = logging.getLogger(__name__)

# Chapter analyses are written by up to 12 worker threads at once, and SQLite
# serialises writers. The default 5s busy timeout is tight for the multi
# statement transaction in save_chapter_analysis, so allow noticeably longer.
BUSY_TIMEOUT_SECONDS = 30


class BookImportQuotaExceeded(ValueError):
    pass


class DuplicateBookImport(ValueError):
    def __init__(self, book_id: str) -> None:
        self.book_id = book_id
        super().__init__(book_id)


@dataclass(frozen=True)
class StructureApplyResult:
    """The identity effects of replacing a confirmed chapter structure."""

    preserved_ids: dict[str, int]
    stale_count: int
    added_count: int
    removed_count: int

    @property
    def preserved_count(self) -> int:
        return len(self.preserved_ids)


@contextmanager
def open_connection(database_path: Path) -> Iterator[sqlite3.Connection]:
    """Yield a configured SQLite connection that is always closed.

    `with sqlite3.connect(...)` only manages the *transaction*; it never closes
    the connection, which leaked hundreds of handles per test run. Wrapping it in
    `closing` fixes that, and gives one place to apply the pragmas:

    - foreign_keys: off by default in SQLite, which made every FOREIGN KEY in the
      schema decorative and allowed orphan rows.
    - journal_mode=WAL: readers no longer block on the writer, which matters with
      a 12-thread analysis batch.
    """
    with closing(sqlite3.connect(database_path, timeout=BUSY_TIMEOUT_SECONDS)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        with connection:
            yield connection


class KeyringClient(Protocol):
    def get_password(self, service_name: str, account: str) -> str | None: ...
    def set_password(self, service_name: str, account: str, secret: str) -> None: ...


class ProviderSettings(BaseModel):
    provider: str
    model: str
    api_key: str

    def without_key(self) -> "ProviderMetadata":
        return ProviderMetadata(provider=self.provider, model=self.model)


class ProviderMetadata(BaseModel):
    provider: str
    model: str


@dataclass(frozen=True)
class ApplicationPaths:
    root: Path

    @classmethod
    def from_environment(cls) -> "ApplicationPaths":
        return cls(Path(os.environ.get("BOOK_LEARNING_HOME", Path.home() / ".book-learning")))

    @property
    def database_path(self) -> Path:
        return self.root / "book-learning.sqlite3"

    @property
    def books_dir(self) -> Path:
        return self.root / "books"

    @property
    def covers_dir(self) -> Path:
        return self.root / "covers"

    def ensure_exists(self) -> None:
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.books_dir.mkdir(mode=0o700, exist_ok=True)
        self.covers_dir.mkdir(mode=0o700, exist_ok=True)


class BookRepository:
    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.database_path = database_path
        with open_connection(database_path) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS provider_settings (provider TEXT PRIMARY KEY, model TEXT NOT NULL)")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS books (
                    id TEXT PRIMARY KEY,
                    owner_id INTEGER,
                    filename TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    stored_path TEXT NOT NULL,
                    source_format TEXT NOT NULL DEFAULT 'pdf',
                    status TEXT NOT NULL,
                    diagnostics_json TEXT NOT NULL,
                    title TEXT,
                    subtitle TEXT,
                    authors TEXT,
                    publisher TEXT,
                    published_at TEXT,
                    identifier TEXT,
                    chapter_count INTEGER,
                    genre TEXT,
                    genre_confidence REAL,
                    genre_source TEXT,
                    structure_version TEXT,
                    structure_diagnostics_json TEXT NOT NULL DEFAULT '[]',
                    visibility TEXT NOT NULL DEFAULT 'private' CHECK(visibility IN ('private', 'public')),
                    public_at TEXT,
                    published_by_user_id INTEGER,
                    UNIQUE(owner_id, sha256)
                )
                """
            )
            book_columns = {row[1] for row in connection.execute("PRAGMA table_info(books)")}
            if "source_format" not in book_columns:
                connection.execute("ALTER TABLE books ADD COLUMN source_format TEXT NOT NULL DEFAULT 'pdf'")
            # Publisher-declared book facts. Nullable on purpose: PDFs rarely carry
            # them, and older rows only ever stored a filename.
            for column in ("title", "subtitle", "authors", "publisher", "published_at", "identifier"):
                if column not in book_columns:
                    connection.execute(f"ALTER TABLE books ADD COLUMN {column} TEXT")
            if "chapter_count" not in book_columns:
                connection.execute("ALTER TABLE books ADD COLUMN chapter_count INTEGER")
            # The argument structure, decided once per book. Nullable so books
            # imported before genre detection keep working on the shared prompt.
            _add_missing_columns(
                connection,
                "books",
                (
                    ("genre", "TEXT"), ("genre_confidence", "REAL"), ("genre_source", "TEXT"),
                    ("structure_version", "TEXT"),
                    ("structure_diagnostics_json", "TEXT NOT NULL DEFAULT '[]'"),
                    ("visibility", "TEXT NOT NULL DEFAULT 'private' CHECK(visibility IN ('private', 'public'))"),
                    ("public_at", "TEXT"),
                    ("published_by_user_id", "INTEGER"),
                ),
            )
            _migrate_books_to_owner_schema(connection)
            connection.execute(
                """CREATE INDEX IF NOT EXISTS books_public_listing
                   ON books(visibility, public_at)
                   WHERE visibility = 'public'"""
            )
            _rebase_managed_book_paths(connection, database_path.parent / "books")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS book_overviews (
                    book_id TEXT PRIMARY KEY,
                    core_question TEXT NOT NULL DEFAULT '',
                    one_sentence_summary TEXT NOT NULL DEFAULT '',
                    generation_status TEXT NOT NULL DEFAULT 'pending',
                    content_version INTEGER NOT NULL DEFAULT 1,
                    FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS external_book_links (
                    book_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('matched', 'not_found', 'ambiguous', 'provider_error')),
                    external_id TEXT,
                    url TEXT,
                    match_basis TEXT,
                    checked_at TEXT NOT NULL,
                    retry_after TEXT,
                    PRIMARY KEY(book_id, provider),
                    FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE,
                    CHECK(
                        (status = 'matched' AND external_id IS NOT NULL AND url IS NOT NULL AND match_basis IS NOT NULL)
                        OR (status <> 'matched' AND external_id IS NULL AND url IS NULL AND match_basis IS NULL)
                    )
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS chapter_analyses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    book_id TEXT NOT NULL,
                    chapter_id INTEGER NOT NULL,
                    chapter_question TEXT NOT NULL DEFAULT '',
                    one_sentence_conclusion TEXT NOT NULL DEFAULT '',
                    short_summary TEXT NOT NULL DEFAULT '',
                    argument_chain_json TEXT NOT NULL DEFAULT '[]',
                    role_in_book TEXT NOT NULL DEFAULT '',
                    estimated_reading_minutes INTEGER NOT NULL DEFAULT 3,
                    generation_status TEXT NOT NULL,
                    failure_reason TEXT,
                    source_content_hash TEXT NOT NULL,
                    content_version INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(book_id, chapter_id),
                    FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE,
                    FOREIGN KEY(chapter_id) REFERENCES chapters(id) ON DELETE SET NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS core_ideas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chapter_analysis_id INTEGER NOT NULL,
                    position INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    conclusion TEXT NOT NULL,
                    importance TEXT NOT NULL,
                    explanation TEXT NOT NULL,
                    reasoning_steps_json TEXT NOT NULL,
                    examples_json TEXT NOT NULL,
                    caveats_json TEXT NOT NULL,
                    author_caveats_json TEXT NOT NULL DEFAULT '[]',
                    ai_caveats_json TEXT NOT NULL DEFAULT '[]',
                    warrant TEXT NOT NULL DEFAULT '',
                    genre_fields_json TEXT NOT NULL DEFAULT '{}',
                    relations_json TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    FOREIGN KEY(chapter_analysis_id) REFERENCES chapter_analyses(id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS source_spans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chapter_id INTEGER NOT NULL,
                    source_page INTEGER NOT NULL,
                    quote TEXT NOT NULL,
                    surrounding_text TEXT NOT NULL,
                    normalized_quote TEXT NOT NULL,
                    verification_status TEXT NOT NULL,
                    FOREIGN KEY(chapter_id) REFERENCES chapters(id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS core_idea_sources (
                    core_idea_id INTEGER NOT NULL,
                    source_span_id INTEGER NOT NULL,
                    PRIMARY KEY(core_idea_id, source_span_id),
                    FOREIGN KEY(core_idea_id) REFERENCES core_ideas(id) ON DELETE CASCADE,
                    FOREIGN KEY(source_span_id) REFERENCES source_spans(id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS attributed_statements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chapter_analysis_id INTEGER NOT NULL,
                    slot TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    FOREIGN KEY(chapter_analysis_id) REFERENCES chapter_analyses(id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS attributed_statement_sources (
                    attributed_statement_id INTEGER NOT NULL,
                    source_span_id INTEGER NOT NULL,
                    PRIMARY KEY(attributed_statement_id, source_span_id),
                    FOREIGN KEY(attributed_statement_id) REFERENCES attributed_statements(id) ON DELETE CASCADE,
                    FOREIGN KEY(source_span_id) REFERENCES source_spans(id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS prediction_attempts (
                    learning_unit_id TEXT PRIMARY KEY,
                    selected_answer TEXT NOT NULL,
                    FOREIGN KEY(learning_unit_id) REFERENCES learning_units(id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS learning_units (
                    id TEXT PRIMARY KEY,
                    book_id TEXT NOT NULL,
                    question TEXT NOT NULL,
                    options_json TEXT NOT NULL,
                    correct_answer TEXT NOT NULL,
                    explanation TEXT NOT NULL,
                    source_quote TEXT NOT NULL,
                    source_page INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS book_pages (
                    book_id TEXT NOT NULL,
                    page_number INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    PRIMARY KEY(book_id, page_number),
                    FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS chapters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    book_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    source_start_page INTEGER NOT NULL,
                    source_end_page INTEGER NOT NULL,
                    depth INTEGER NOT NULL DEFAULT 0,
                    parent_title TEXT,
                    nav_kind TEXT NOT NULL DEFAULT 'plain',
                    in_body INTEGER NOT NULL DEFAULT 1,
                    structural_role TEXT NOT NULL DEFAULT 'unknown',
                    role_source TEXT NOT NULL DEFAULT 'unknown',
                    role_confidence TEXT NOT NULL DEFAULT 'low',
                    analysis_role TEXT NOT NULL DEFAULT 'analysis_unit',
                    source_locator TEXT,
                    text_sha256 TEXT,
                    removed INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS chapter_drafts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    book_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    source_start_page INTEGER NOT NULL,
                    source_end_page INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    depth INTEGER NOT NULL DEFAULT 0,
                    parent_title TEXT,
                    nav_kind TEXT NOT NULL DEFAULT 'plain',
                    in_body INTEGER NOT NULL DEFAULT 1,
                    structural_role TEXT NOT NULL DEFAULT 'unknown',
                    role_source TEXT NOT NULL DEFAULT 'unknown',
                    role_confidence TEXT NOT NULL DEFAULT 'low',
                    analysis_role TEXT NOT NULL DEFAULT 'analysis_unit',
                    source_locator TEXT,
                    text_sha256 TEXT,
                    FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    book_id TEXT NOT NULL,
                    chapter_id INTEGER,
                    model TEXT,
                    status TEXT NOT NULL,
                    input_characters INTEGER NOT NULL,
                    output_characters INTEGER NOT NULL,
                    prompt_tokens INTEGER,
                    completion_tokens INTEGER,
                    total_tokens INTEGER,
                    elapsed_milliseconds INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE,
                    FOREIGN KEY(chapter_id) REFERENCES chapters(id) ON DELETE SET NULL
                )
                """
            )
            _migrate_analysis_runs_chapter_id(connection)
            _migrate_chapter_structure_columns(connection)
            _migrate_structure_identity_columns(connection)
            _migrate_core_idea_columns(connection)
            _create_indexes(connection)
            _add_missing_columns(connection, "books", (("analysis_input_revision", "INTEGER NOT NULL DEFAULT 0"),))
            _add_missing_columns(connection, "chapter_analyses", (("active_job_id", "TEXT"), ("input_fingerprint", "TEXT")))
            _add_missing_columns(connection, "chapter_analyses", (("reading_record_json", "TEXT"),))
            _add_missing_columns(connection, "book_overviews", (("synthesis_json", "TEXT"),))
            from app.services.analysis_job_store import initialize_analysis_schema
            initialize_analysis_schema(connection)

    def capture_analysis_input(self, book_id: str, builder, *, job_id: str | None = None, overview=False):
        from app.services.analysis_inputs import AnalysisInputSnapshot, configuration_signature, fingerprint, ready_result_versions
        with open_connection(self.database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            revision = connection.execute("SELECT analysis_input_revision FROM books WHERE id=?", (book_id,)).fetchone()[0]
            value = builder()
            snapshot = AnalysisInputSnapshot(
                book_id, revision, configuration_signature(connection, book_id),
                fingerprint({"input": value, "prompt_version": "overview-v1" if overview else "chapter-evidence-v1", "schema_version": 1}), job_id,
                ready_result_versions(connection, book_id) if overview else None,
            )
        return snapshot, value

    def analysis_input_is_current(self, snapshot) -> bool:
        from app.services.analysis_inputs import publication_allowed
        with open_connection(self.database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            return publication_allowed(connection, snapshot)

    def save_provider_metadata(self, metadata: ProviderMetadata) -> None:
        with open_connection(self.database_path) as connection:
            connection.execute("INSERT OR REPLACE INTO provider_settings(provider, model) VALUES (?, ?)", (metadata.provider, metadata.model))

    def get_current_provider_metadata(self) -> ProviderMetadata | None:
        with open_connection(self.database_path) as connection:
            row = connection.execute(
                "SELECT provider, model FROM provider_settings ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
        return ProviderMetadata(provider=row[0], model=row[1]) if row else None

    def save_book_pages(self, book_id: str, pages: list[str]) -> None:
        with open_connection(self.database_path) as connection:
            connection.executemany(
                "INSERT OR REPLACE INTO book_pages(book_id, page_number, text) VALUES (?, ?, ?)",
                [(book_id, page_number, text) for page_number, text in enumerate(pages, start=1)],
            )

    def replace_chapter_drafts(self, book_id: str, chapters: list[object]) -> None:
        with open_connection(self.database_path) as connection:
            self._replace_chapter_drafts(connection, book_id, chapters)

    def _replace_chapter_drafts(
        self, connection: sqlite3.Connection, book_id: str, chapters: list[object]
    ) -> None:
        connection.execute("DELETE FROM chapter_drafts WHERE book_id = ?", (book_id,))
        connection.executemany(
            """
            INSERT INTO chapter_drafts(
                book_id, position, title, source_start_page, source_end_page, text,
                depth, parent_title, nav_kind, in_body,
                structural_role, role_source, role_confidence, analysis_role, source_locator, text_sha256
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (book_id, position, *_draft_row(chapter))
                for position, chapter in enumerate(chapters)
            ],
        )

    def save_book_import(
        self,
        *,
        owner_id: int | None = None,
        enforce_owner_quota: bool = False,
        book_id: str,
        filename: str,
        sha256: str,
        stored_path: Path,
        status: str,
        diagnostics: list[str],
        pages: list[str],
        chapters: list[object],
        source_format: str = "pdf",
        metadata: object | None = None,
    ) -> None:
        with open_connection(self.database_path) as connection:
            if enforce_owner_quota:
                if owner_id is None:
                    raise ValueError("owner_id is required when enforcing a book import quota")
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT id FROM books WHERE owner_id = ? AND sha256 = ?", (owner_id, sha256)
                ).fetchone()
                if existing is not None:
                    raise DuplicateBookImport(str(existing[0]))
                reserved = connection.execute(
                    """UPDATE users SET book_import_count = book_import_count + 1, updated_at = CURRENT_TIMESTAMP
                       WHERE id = ? AND status = 'active'
                         AND (book_import_limit IS NULL OR book_import_count < book_import_limit)""",
                    (owner_id,),
                ).rowcount
                if reserved != 1:
                    raise BookImportQuotaExceeded("已达到书籍导入上限")
            connection.execute(
                """
                INSERT INTO books(
                    id, owner_id, filename, sha256, stored_path, source_format, status, diagnostics_json,
                    title, subtitle, authors, publisher, published_at, identifier, chapter_count,
                    structure_version, structure_diagnostics_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    book_id,
                    owner_id,
                    filename,
                    sha256,
                    str(stored_path),
                    source_format,
                    status,
                    dumps(diagnostics),
                    *_metadata_row(metadata),
                    "epub-v2" if source_format == "epub" else None,
                    dumps(diagnostics if source_format == "epub" else []),
                ),
            )
            connection.executemany(
                "INSERT INTO book_pages(book_id, page_number, text) VALUES (?, ?, ?)",
                [(book_id, page_number, text) for page_number, text in enumerate(pages, start=1)],
            )
            connection.executemany(
                """
                INSERT INTO chapter_drafts(
                    book_id, position, title, source_start_page, source_end_page, text,
                    depth, parent_title, nav_kind, in_body,
                    structural_role, role_source, role_confidence, analysis_role, source_locator, text_sha256
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (book_id, position, *_draft_row(chapter))
                    for position, chapter in enumerate(chapters)
                ],
            )

    def get_book(self, book_id: str) -> dict[str, str] | None:
        with open_connection(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT id, owner_id, filename, sha256, source_format, status, diagnostics_json,
                       title, subtitle, authors, publisher, published_at, identifier, chapter_count,
                       genre, genre_confidence, genre_source,
                       structure_version, structure_diagnostics_json
                FROM books WHERE id = ?
                """,
                (book_id,),
            ).fetchone()
        return dict(row) if row else None

    def update_book_metadata(self, book_id: str, metadata: object) -> None:
        title, subtitle, authors, publisher, published_at, identifier, chapter_count = _metadata_row(metadata)
        with open_connection(self.database_path) as connection:
            connection.execute(
                """
                UPDATE books SET
                    title = COALESCE(NULLIF(title, ''), ?),
                    subtitle = COALESCE(NULLIF(subtitle, ''), ?),
                    authors = COALESCE(NULLIF(authors, ''), ?),
                    publisher = COALESCE(NULLIF(publisher, ''), ?),
                    published_at = COALESCE(NULLIF(published_at, ''), ?),
                    identifier = COALESCE(NULLIF(identifier, ''), ?),
                    chapter_count = COALESCE(chapter_count, ?)
                WHERE id = ?
                """,
                (title, subtitle, authors, publisher, published_at, identifier, chapter_count, book_id),
            )

    def get_external_book_link(self, book_id: str, provider: str) -> dict[str, object] | None:
        with open_connection(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT * FROM external_book_links WHERE book_id = ? AND provider = ?",
                (book_id, provider),
            ).fetchone()
        return dict(row) if row else None

    def save_external_book_link(
        self,
        *,
        book_id: str,
        provider: str,
        status: str,
        external_id: str | None,
        url: str | None,
        match_basis: str | None,
        checked_at: str,
        retry_after: str | None,
    ) -> None:
        with open_connection(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO external_book_links(
                    book_id, provider, status, external_id, url, match_basis, checked_at, retry_after
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(book_id, provider) DO UPDATE SET
                    status = excluded.status,
                    external_id = excluded.external_id,
                    url = excluded.url,
                    match_basis = excluded.match_basis,
                    checked_at = excluded.checked_at,
                    retry_after = excluded.retry_after
                """,
                (book_id, provider, status, external_id, url, match_basis, checked_at, retry_after),
            )

    def book_context_for_prompt(self, book_id: str) -> dict[str, object]:
        """Collect the book-level facts a chapter prompt needs to place a chapter.

        Returned in one call because the caller needs all of it at once, and the
        alternative (a metadata getter plus an outline getter) doubles the round
        trips per chapter while a 12-thread batch is running.

        The outline is the confirmed body titles rather than the preceding
        chapter's conclusion: the batch generates chapters concurrently, so a
        previous conclusion may not exist yet, whereas the outline is stable
        regardless of generation order.
        """
        with open_connection(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            book = connection.execute(
                """
                SELECT title, subtitle, authors, publisher, genre
                FROM books WHERE id = ?
                """,
                (book_id,),
            ).fetchone()
            titles = connection.execute(
                """
                SELECT title FROM chapters
                WHERE book_id = ? AND removed = 0 AND in_body = 1
                ORDER BY position
                """,
                (book_id,),
            ).fetchall()
        context: dict[str, object] = {
            "title": "",
            "subtitle": "",
            "authors": "",
            "publisher": "",
            "genre": None,
            "outline": [str(row["title"]) for row in titles],
        }
        if book is not None:
            for key in ("title", "subtitle", "authors", "publisher"):
                context[key] = str(book[key] or "")
            context["genre"] = str(book["genre"]) if book["genre"] else None
        return context

    def set_book_genre(
        self, book_id: str, *, genre: str, confidence: float | None, source: str, snapshot=None
    ) -> None:
        """Record the whole-book argument structure.

        Stored once per book instead of per chapter: judging each chapter
        separately would spend one model call per chapter and can disagree with
        itself, leaving one book analysed under two different frameworks.
        """
        with open_connection(self.database_path) as connection:
            if snapshot is not None:
                from app.services.analysis_inputs import publication_allowed
                connection.execute("BEGIN IMMEDIATE")
                if not publication_allowed(connection, snapshot):
                    return
            connection.execute(
                "UPDATE books SET genre = ?, genre_confidence = ?, genre_source = ? WHERE id = ?",
                (genre, confidence, source, book_id),
            )

    def list_analyzed_books(self) -> list[dict[str, str]]:
        with open_connection(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            query = """
                SELECT books.id, books.filename, books.source_format, books.title, books.authors
                FROM books
                JOIN book_overviews ON book_overviews.book_id = books.id
                WHERE book_overviews.generation_status = 'ready'
            """
            rows = connection.execute(query + " ORDER BY books.filename COLLATE NOCASE, books.id").fetchall()
        return [dict(row) for row in rows]

    def list_analyzed_books_for_owner(self, owner_id: int) -> list[dict[str, str]]:
        with open_connection(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """SELECT books.id, books.filename, books.source_format, books.title, books.authors,
                          'owned' AS access_scope
                   FROM books JOIN book_overviews ON book_overviews.book_id = books.id
                   WHERE books.owner_id = ?
                     AND book_overviews.generation_status = 'ready'
                   ORDER BY books.filename COLLATE NOCASE, books.id""",
                (owner_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_public_analyzed_books(self) -> list[dict[str, str]]:
        with open_connection(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """SELECT books.id, books.filename, books.source_format, books.title, books.authors,
                          'public' AS access_scope
                   FROM books JOIN book_overviews ON book_overviews.book_id = books.id
                   WHERE books.visibility = 'public'
                     AND book_overviews.generation_status = 'ready'
                   ORDER BY books.public_at DESC,
                            COALESCE(books.title, books.filename) COLLATE NOCASE ASC,
                            books.id ASC"""
            ).fetchall()
        return [dict(row) for row in rows]

    def list_publishable_books_for_owner(self, owner_id: int) -> list[dict[str, object]]:
        with open_connection(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """SELECT books.id, books.filename, books.source_format, books.title, books.authors,
                          books.visibility, books.public_at,
                          COALESCE(book_overviews.generation_status, 'pending') AS overview_status,
                          (
                              SELECT COUNT(*)
                              FROM chapters
                              JOIN chapter_analyses
                                ON chapter_analyses.book_id = chapters.book_id
                               AND chapter_analyses.chapter_id = chapters.id
                              WHERE chapters.book_id = books.id
                                AND chapters.removed = 0
                                AND chapter_analyses.generation_status = 'ready'
                          ) AS ready_chapter_count
                   FROM books
                   LEFT JOIN book_overviews ON book_overviews.book_id = books.id
                   WHERE books.owner_id = ?
                   ORDER BY books.filename COLLATE NOCASE ASC, books.id ASC""",
                (owner_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def has_ready_readable_chapter(self, book_id: str) -> bool:
        with open_connection(self.database_path) as connection:
            row = connection.execute(
                """SELECT EXISTS(
                       SELECT 1
                       FROM chapters
                       JOIN chapter_analyses
                         ON chapter_analyses.book_id = chapters.book_id
                        AND chapter_analyses.chapter_id = chapters.id
                       WHERE chapters.book_id = ?
                         AND chapters.removed = 0
                         AND chapters.analysis_role = 'analysis_unit'
                         AND chapter_analyses.generation_status = 'ready'
                   )""",
                (book_id,),
            ).fetchone()
        return bool(row[0])

    def set_book_visibility(
        self,
        *,
        book_id: str,
        owner_id: int,
        visibility: Literal["private", "public"],
        published_by_user_id: int | None,
        public_at: str | None,
    ) -> bool:
        if visibility not in {"private", "public"}:
            raise ValueError("visibility must be private or public")
        if visibility == "private":
            published_by_user_id = None
            public_at = None

        with open_connection(self.database_path) as connection:
            result = connection.execute(
                """UPDATE books
                   SET visibility = ?, public_at = ?, published_by_user_id = ?
                   WHERE id = ? AND owner_id = ?""",
                (visibility, public_at, published_by_user_id, book_id, owner_id),
            )
        return result.rowcount == 1

    def get_book_by_sha256(self, sha256: str) -> dict[str, str] | None:
        with open_connection(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT id, filename, sha256, source_format, status, diagnostics_json FROM books WHERE sha256 = ?", (sha256,)
            ).fetchone()
        return dict(row) if row else None

    def get_owned_book(self, owner_id: int, book_id: str) -> dict[str, str] | None:
        with open_connection(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT * FROM books WHERE id = ? AND owner_id = ?", (book_id, owner_id)
            ).fetchone()
        return dict(row) if row else None

    def get_readable_book(self, user_id: int | None, book_id: str) -> dict[str, str] | None:
        with open_connection(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """SELECT books.*,
                          CASE WHEN books.visibility = 'public' THEN 'public' ELSE 'owned' END AS access_scope
                   FROM books
                   WHERE books.id = ?
                     AND (books.owner_id = ? OR (
                       books.visibility = 'public' AND (? IS NOT NULL OR EXISTS (
                           SELECT 1 FROM book_overviews
                           WHERE book_overviews.book_id = books.id
                             AND book_overviews.generation_status = 'ready'
                       ))
                     ))""",
                (book_id, user_id, user_id),
            ).fetchone()
        return dict(row) if row else None

    def find_owned_book_by_sha256(self, owner_id: int, sha256: str) -> dict[str, str] | None:
        with open_connection(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT id, filename, sha256, source_format, status, diagnostics_json FROM books WHERE owner_id = ? AND sha256 = ?",
                (owner_id, sha256),
            ).fetchone()
        return dict(row) if row else None

    def get_owned_stored_book_path(self, owner_id: int, book_id: str) -> Path | None:
        with open_connection(self.database_path) as connection:
            row = connection.execute(
                "SELECT stored_path FROM books WHERE id = ? AND owner_id = ?", (book_id, owner_id)
            ).fetchone()
        return Path(str(row[0])) if row else None

    def get_readable_stored_book_path(self, user_id: int, book_id: str) -> Path | None:
        with open_connection(self.database_path) as connection:
            row = connection.execute(
                """SELECT stored_path FROM books
                   WHERE id = ? AND (owner_id = ? OR visibility = 'public')""",
                (book_id, user_id),
            ).fetchone()
        return Path(str(row[0])) if row else None

    def get_stored_book_path(self, book_id: str) -> Path | None:
        with open_connection(self.database_path) as connection:
            row = connection.execute("SELECT stored_path FROM books WHERE id = ?", (book_id,)).fetchone()
        return Path(str(row[0])) if row else None

    def max_draft_page(self, book_id: str) -> int:
        with open_connection(self.database_path) as connection:
            row = connection.execute(
                "SELECT MAX(source_end_page) FROM chapter_drafts WHERE book_id = ?", (book_id,)
            ).fetchone()
        return int(row[0] or 0)

    def replace_confirmed_chapters(self, book_id: str, chapters: list[object]) -> StructureApplyResult:
        with open_connection(self.database_path) as connection:
            return self._replace_confirmed_chapters(connection, book_id, chapters)

    def apply_epub_structure(self, book_id: str, parsed: ParsedBook) -> StructureApplyResult:
        """Atomically replace every persisted fact derived from an EPUB structure parse."""
        with open_connection(self.database_path) as connection:
            book_row = connection.execute(
                "SELECT status FROM books WHERE id = ?", (book_id,)
            ).fetchone()
            was_confirmed = book_row is not None and book_row[0] == "chapters_confirmed"
            legacy_identity_snapshot = _legacy_identity_snapshot(connection, book_id)
            connection.execute("DELETE FROM book_pages WHERE book_id = ?", (book_id,))
            connection.executemany(
                "INSERT INTO book_pages(book_id, page_number, text) VALUES (?, ?, ?)",
                [
                    (book_id, page_number, text)
                    for page_number, text in enumerate(parsed.pages, start=1)
                ],
            )
            self._replace_chapter_drafts(connection, book_id, list(parsed.chapters))
            result = (
                self._replace_confirmed_chapters(
                    connection,
                    book_id,
                    list(parsed.chapters),
                    legacy_identity_snapshot=legacy_identity_snapshot,
                )
                if was_confirmed
                else StructureApplyResult(
                    preserved_ids={},
                    stale_count=0,
                    added_count=len(parsed.chapters),
                    removed_count=0,
                )
            )
            connection.execute(
                """
                UPDATE books
                SET structure_version = 'epub-v2', structure_diagnostics_json = ?
                WHERE id = ?
                """,
                (dumps(parsed.diagnostics), book_id),
            )
            connection.execute(
                "UPDATE book_overviews SET generation_status = 'stale' WHERE book_id = ?",
                (book_id,),
            )
        return result

    def _replace_confirmed_chapters(
        self,
        connection: sqlite3.Connection,
        book_id: str,
        chapters: list[object],
        *,
        legacy_identity_snapshot: dict[tuple[str, str], list[sqlite3.Row]] | None = None,
    ) -> StructureApplyResult:
        connection.row_factory = sqlite3.Row
        existing = connection.execute(
            """
            SELECT id, position, title, source_start_page, source_end_page,
                   depth, parent_title, nav_kind, in_body, structural_role,
                   source_locator, text_sha256, analysis_role
            FROM chapters WHERE book_id = ? AND removed = 0 ORDER BY position
            """,
            (book_id,),
        ).fetchall()
        locator_candidates: dict[str, list[sqlite3.Row]] = {}
        for row in existing:
            if row["source_locator"]:
                locator_candidates.setdefault(str(row["source_locator"]), []).append(row)
        existing_by_locator = {
            locator: rows[0] for locator, rows in locator_candidates.items() if len(rows) == 1
        }
        existing_by_legacy_identity = (
            legacy_identity_snapshot
            if legacy_identity_snapshot is not None
            else _legacy_identity_index(connection, book_id, existing)
        )
        matched_ids: set[int] = set()
        preserved_ids: dict[str, int] = {}
        stale_count = 0
        added_count = 0
        for position, chapter in enumerate(chapters):
            source_locator, text_sha256 = _confirmed_identity(connection, book_id, chapter)
            current = existing_by_locator.get(source_locator) if source_locator else None
            if current is None and source_locator:
                candidates = locator_candidates.get(source_locator, [])
                # EPUB outlines legitimately let a chapter heading and its first
                # section share one target. Reuse those rows only when the shared
                # source hash proves they describe the same text, then disambiguate
                # by their scoped outline title. Malformed duplicate locators with
                # different content remain intentionally ambiguous.
                candidate_hashes = {str(row["text_sha256"] or "") for row in candidates}
                if len(candidates) > 1 and len(candidate_hashes) == 1 and "" not in candidate_hashes:
                    scoped = [
                        row
                        for row in candidates
                        if _normalise_title(str(row["title"])) == _normalise_title(chapter.title)
                        and _normalise_title(str(row["parent_title"] or ""))
                        == _normalise_title(getattr(chapter, "parent_title", None) or "")
                    ]
                    if len(scoped) == 1:
                        current = scoped[0]
            if current is None and source_locator and text_sha256:
                candidates = existing_by_legacy_identity.get(
                    (_normalise_title(chapter.title), text_sha256), []
                )
                if len(candidates) == 1:
                    current = candidates[0]
            if current is not None and int(current["id"]) not in matched_ids:
                matched_ids.add(int(current["id"]))
                current_text_sha256 = current["text_sha256"] or _chapter_text_sha256(
                    connection, book_id, current["source_start_page"], current["source_end_page"]
                )
                changed = (
                    current["title"] != chapter.title
                    or current["source_start_page"] != chapter.source_start_page
                    or current["source_end_page"] != chapter.source_end_page
                    or current_text_sha256 != text_sha256
                    or current["depth"] != getattr(chapter, "depth", 0)
                    or current["parent_title"] != getattr(chapter, "parent_title", None)
                    or current["nav_kind"] != getattr(chapter, "nav_kind", "plain")
                    or bool(current["in_body"]) != bool(getattr(chapter, "in_body", True))
                    or current["structural_role"] != getattr(chapter, "structural_role", "unknown")
                    or current["analysis_role"] != getattr(chapter, "analysis_role", "analysis_unit")
                )
                connection.execute(
                    """
                    UPDATE chapters SET position = ?, title = ?, source_start_page = ?, source_end_page = ?,
                        depth = ?, parent_title = ?, nav_kind = ?, in_body = ?,
                        structural_role = ?, role_source = ?, role_confidence = ?, analysis_role = ?,
                        source_locator = ?, text_sha256 = ?
                    WHERE id = ?
                    """,
                    (
                        position,
                        chapter.title,
                        chapter.source_start_page,
                        chapter.source_end_page,
                        getattr(chapter, "depth", 0),
                        getattr(chapter, "parent_title", None),
                        getattr(chapter, "nav_kind", "plain"),
                        int(getattr(chapter, "in_body", True)),
                        getattr(chapter, "structural_role", "unknown"),
                        getattr(chapter, "role_source", "unknown"),
                        getattr(chapter, "role_confidence", "low"),
                        getattr(chapter, "analysis_role", "analysis_unit"),
                        source_locator,
                        text_sha256,
                        current["id"],
                    ),
                )
                if changed:
                    stale_count += connection.execute(
                        "UPDATE chapter_analyses SET generation_status = 'stale' WHERE chapter_id = ?",
                        (current["id"],),
                    ).rowcount
                if source_locator:
                    preserved_ids[source_locator] = int(current["id"])
            else:
                added_count += 1
                connection.execute(
                    """
                    INSERT INTO chapters(
                        book_id, position, title, source_start_page, source_end_page,
                        depth, parent_title, nav_kind, in_body,
                        structural_role, role_source, role_confidence, analysis_role, source_locator, text_sha256
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        book_id,
                        position,
                        chapter.title,
                        chapter.source_start_page,
                        chapter.source_end_page,
                        getattr(chapter, "depth", 0),
                        getattr(chapter, "parent_title", None),
                        getattr(chapter, "nav_kind", "plain"),
                        int(getattr(chapter, "in_body", True)),
                        getattr(chapter, "structural_role", "unknown"),
                        getattr(chapter, "role_source", "unknown"),
                        getattr(chapter, "role_confidence", "low"),
                        getattr(chapter, "analysis_role", "analysis_unit"),
                        source_locator,
                        text_sha256,
                    ),
                )
        removed_ids = [int(row["id"]) for row in existing if int(row["id"]) not in matched_ids]
        for chapter_id in removed_ids:
            stale_count += connection.execute(
                "UPDATE chapter_analyses SET generation_status = 'stale' WHERE chapter_id = ?",
                (chapter_id,),
            ).rowcount
        if removed_ids:
            # Keep unmatched chapters for their stale analyses, but exclude
            # them from the active confirmed structure.
            connection.executemany(
                "UPDATE chapters SET removed = 1 WHERE id = ?",
                [(chapter_id,) for chapter_id in removed_ids],
            )
        connection.execute("UPDATE books SET status = 'chapters_confirmed' WHERE id = ?", (book_id,))
        return StructureApplyResult(
            preserved_ids=preserved_ids,
            stale_count=stale_count,
            added_count=added_count,
            removed_count=len(removed_ids),
        )

    def list_chapters(self, book_id: str, *, confirmed: bool) -> list[dict[str, int | str]]:
        table = "chapters" if confirmed else "chapter_drafts"
        active_filter = " AND removed = 0" if confirmed else ""
        with open_connection(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                f"""
                SELECT id, title, source_start_page, source_end_page,
                       depth, parent_title, nav_kind, in_body,
                       structural_role, role_source, role_confidence, analysis_role, source_locator, text_sha256
                FROM {table} WHERE book_id = ?{active_filter} ORDER BY position
                """,
                (book_id,),
            ).fetchall()
        chapters: list[dict[str, int | str]] = []
        for row in rows:
            chapter = dict(row)
            chapter["in_body"] = bool(chapter["in_body"])
            chapters.append(chapter)
        return chapters

    def confirmed_chapter_source(self, book_id: str) -> dict[str, int | str] | None:
        sources = self.confirmed_chapter_sources(book_id)
        return sources[0] if sources else None

    def confirmed_chapter_sources(self, book_id: str) -> list[dict[str, int | str]]:
        with open_connection(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            chapters = connection.execute(
                """
                SELECT id, title, source_start_page, source_end_page,
                       depth, parent_title, nav_kind, in_body,
                       structural_role, role_source, role_confidence, analysis_role, source_locator, text_sha256
                FROM chapters WHERE book_id = ? AND removed = 0 ORDER BY position
                """,
                (book_id,),
            ).fetchall()
            sources: list[dict[str, int | str]] = []
            for chapter in chapters:
                pages = connection.execute(
                    """
                    SELECT page_number, text FROM book_pages
                    WHERE book_id = ? AND page_number BETWEEN ? AND ?
                    ORDER BY page_number
                    """,
                    (book_id, chapter["source_start_page"], chapter["source_end_page"]),
                ).fetchall()
                source = dict(chapter)
                source["text"] = "\n\n".join(str(page["text"]) for page in pages).strip()
                source["pages"] = [dict(page) for page in pages]
                sources.append(source)
        return sources

    def confirmed_chapter_source_by_id(self, book_id: str, chapter_id: int) -> dict[str, int | str] | None:
        source = next(
            (source for source in self.confirmed_chapter_sources(book_id) if source["id"] == chapter_id),
            None,
        )
        if source is not None:
            source["book_id"] = book_id
        return source

    def set_chapter_analysis_status(
        self,
        *,
        book_id: str,
        chapter_id: int,
        status: str,
        source_content_hash: str,
        failure_reason: str | None = None,
        snapshot=None,
    ) -> bool:
        with open_connection(self.database_path) as connection:
            if snapshot is not None:
                from app.services.analysis_inputs import publication_allowed
                connection.execute("BEGIN IMMEDIATE")
                if not publication_allowed(connection, snapshot, chapter_id, claim=status == "generating"):
                    return False
            connection.execute(
                """
                INSERT INTO chapter_analyses(book_id, chapter_id, generation_status, failure_reason, source_content_hash)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(book_id, chapter_id) DO UPDATE SET
                    generation_status = excluded.generation_status,
                    failure_reason = excluded.failure_reason,
                    source_content_hash = excluded.source_content_hash
                """,
                (book_id, chapter_id, status, failure_reason, source_content_hash),
            )
            if snapshot is not None:
                connection.execute("UPDATE chapter_analyses SET active_job_id=?,input_fingerprint=? WHERE book_id=? AND chapter_id=?",
                                   (snapshot.job_id, snapshot.input_fingerprint, book_id, chapter_id))
        return True

    def record_analysis_run(
        self,
        *,
        book_id: str,
        chapter_id: int | None,
        model: str | None,
        status: str,
        input_characters: int,
        output_characters: int,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        total_tokens: int | None,
        elapsed_milliseconds: int,
    ) -> None:
        with open_connection(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO analysis_runs(
                    book_id, chapter_id, model, status, input_characters, output_characters,
                    prompt_tokens, completion_tokens, total_tokens, elapsed_milliseconds
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    book_id,
                    chapter_id,
                    model,
                    status,
                    input_characters,
                    output_characters,
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                    elapsed_milliseconds,
                ),
            )

    def list_analysis_runs(self, book_id: str) -> list[dict[str, object]]:
        with open_connection(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT * FROM analysis_runs WHERE book_id = ? ORDER BY id", (book_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def save_chapter_analysis(
        self,
        *,
        book_id: str,
        chapter_id: int,
        source_content_hash: str,
        status: str,
        draft: ChapterAnalysisDraft,
        publishable_ideas: list[tuple[CoreIdeaDraft, list[EvidenceDraft]]],
        publishable_statements: list[tuple[str, int, AttributedStatementDraft, list[EvidenceDraft]]] | None = None,
        failure_reason: str | None = None,
        snapshot=None,
    ) -> bool:
        legacy_statement_fallback = publishable_statements is None
        with open_connection(self.database_path) as connection:
            if snapshot is not None:
                from app.services.analysis_inputs import publication_allowed
                connection.execute("BEGIN IMMEDIATE")
                if not publication_allowed(connection, snapshot, chapter_id):
                    return False
            connection.execute(
                """
                INSERT INTO chapter_analyses(
                    book_id, chapter_id, chapter_question, one_sentence_conclusion, short_summary,
                    argument_chain_json, role_in_book, estimated_reading_minutes, generation_status,
                    failure_reason, source_content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(book_id, chapter_id) DO UPDATE SET
                    chapter_question = excluded.chapter_question,
                    one_sentence_conclusion = excluded.one_sentence_conclusion,
                    short_summary = excluded.short_summary,
                    argument_chain_json = excluded.argument_chain_json,
                    role_in_book = excluded.role_in_book,
                    estimated_reading_minutes = excluded.estimated_reading_minutes,
                    generation_status = excluded.generation_status,
                    failure_reason = excluded.failure_reason,
                    source_content_hash = excluded.source_content_hash,
                    content_version = chapter_analyses.content_version + 1
                """,
                (
                    book_id,
                    chapter_id,
                    draft.chapter_question,
                    draft.one_sentence_conclusion,
                    draft.short_summary,
                    dumps(
                        [statement.text for statement in draft.argument_chain]
                        if legacy_statement_fallback
                        else [],
                        ensure_ascii=False,
                    ),
                    draft.role_in_book.text if legacy_statement_fallback and draft.role_in_book else "",
                    draft.estimated_reading_minutes,
                    status,
                    failure_reason,
                    source_content_hash,
                ),
            )
            connection.execute("UPDATE chapter_analyses SET reading_record_json=? WHERE book_id=? AND chapter_id=?",
                               (dumps(draft.reading_record, ensure_ascii=False) if draft.reading_record else None, book_id, chapter_id))
            analysis_id = connection.execute(
                "SELECT id FROM chapter_analyses WHERE book_id = ? AND chapter_id = ?",
                (book_id, chapter_id),
            ).fetchone()[0]
            source_ids = connection.execute(
                """
                SELECT source_span_id FROM core_idea_sources
                WHERE core_idea_id IN (SELECT id FROM core_ideas WHERE chapter_analysis_id = ?)
                UNION
                SELECT source_span_id FROM attributed_statement_sources
                WHERE attributed_statement_id IN (
                    SELECT id FROM attributed_statements WHERE chapter_analysis_id = ?
                )
                """,
                (analysis_id, analysis_id),
            ).fetchall()
            connection.execute(
                "DELETE FROM core_idea_sources WHERE core_idea_id IN (SELECT id FROM core_ideas WHERE chapter_analysis_id = ?)",
                (analysis_id,),
            )
            connection.execute("DELETE FROM core_ideas WHERE chapter_analysis_id = ?", (analysis_id,))
            connection.execute(
                "DELETE FROM attributed_statement_sources WHERE attributed_statement_id IN "
                "(SELECT id FROM attributed_statements WHERE chapter_analysis_id = ?)",
                (analysis_id,),
            )
            connection.execute("DELETE FROM attributed_statements WHERE chapter_analysis_id = ?", (analysis_id,))
            connection.executemany("DELETE FROM source_spans WHERE id = ?", source_ids)
            for position, (idea, evidence_items) in enumerate(publishable_ideas):
                cursor = connection.execute(
                    """
                    INSERT INTO core_ideas(
                        chapter_analysis_id, position, title, conclusion, importance, explanation,
                        reasoning_steps_json, examples_json, caveats_json,
                        author_caveats_json, ai_caveats_json, warrant, genre_fields_json,
                        relations_json, content_type, confidence
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        analysis_id,
                        position,
                        idea.title,
                        idea.conclusion,
                        idea.importance,
                        idea.explanation,
                        dumps(idea.reasoning_steps, ensure_ascii=False),
                        dumps(idea.examples, ensure_ascii=False),
                        dumps(idea.caveats, ensure_ascii=False),
                        dumps(idea.author_caveats, ensure_ascii=False),
                        dumps(idea.ai_caveats, ensure_ascii=False),
                        idea.warrant,
                        dumps(idea.genre_fields, ensure_ascii=False),
                        dumps(idea.relations, ensure_ascii=False),
                        idea.content_type,
                        idea.confidence,
                    ),
                )
                core_idea_id = cursor.lastrowid
                for evidence in evidence_items:
                    source_cursor = connection.execute(
                        """
                        INSERT INTO source_spans(
                            chapter_id, source_page, quote, surrounding_text, normalized_quote, verification_status
                        ) VALUES (?, ?, ?, ?, ?, 'verified')
                        """,
                        (
                            evidence.source_chapter_id or chapter_id,
                            evidence.page,
                            evidence.quote,
                            evidence.surrounding_text,
                            " ".join(evidence.quote.split()),
                        ),
                    )
                    connection.execute(
                        "INSERT INTO core_idea_sources(core_idea_id, source_span_id) VALUES (?, ?)",
                        (core_idea_id, source_cursor.lastrowid),
                    )
            for slot, position, statement, evidence_items in publishable_statements or []:
                statement_cursor = connection.execute(
                    """
                    INSERT INTO attributed_statements(chapter_analysis_id, slot, position, text, content_type)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (analysis_id, slot, position, statement.text, statement.content_type),
                )
                statement_id = statement_cursor.lastrowid
                for evidence in evidence_items:
                    source_cursor = connection.execute(
                        """
                        INSERT INTO source_spans(
                            chapter_id, source_page, quote, surrounding_text, normalized_quote, verification_status
                        ) VALUES (?, ?, ?, ?, ?, 'verified')
                        """,
                        (
                            evidence.source_chapter_id or chapter_id,
                            evidence.page,
                            evidence.quote,
                            evidence.surrounding_text,
                            " ".join(evidence.quote.split()),
                        ),
                    )
                    connection.execute(
                        "INSERT INTO attributed_statement_sources(attributed_statement_id, source_span_id) VALUES (?, ?)",
                        (statement_id, source_cursor.lastrowid),
                    )

            if snapshot is not None:
                connection.execute("UPDATE chapter_analyses SET input_fingerprint=? WHERE book_id=? AND chapter_id=?",
                                   (snapshot.input_fingerprint, book_id, chapter_id))
        return True

    def get_chapter_analysis(self, book_id: str, chapter_id: int) -> dict[str, object] | None:
        with open_connection(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT * FROM chapter_analyses WHERE book_id = ? AND chapter_id = ?",
                (book_id, chapter_id),
            ).fetchone()
            if row is None:
                return None
            analysis = dict(row)
            analysis["reading_record"] = loads(analysis.pop("reading_record_json") or "null")
            if analysis["reading_record"]:
                record = analysis["reading_record"]
                record["gaps"] = list(dict.fromkeys(record.get("gaps", [])))
            legacy_argument_chain = loads(str(analysis.pop("argument_chain_json")))
            idea_rows = connection.execute(
                "SELECT * FROM core_ideas WHERE chapter_analysis_id = ? ORDER BY position", (row["id"],)
            ).fetchall()
            ideas: list[dict[str, object]] = []
            for idea_row in idea_rows:
                idea = dict(idea_row)
                for source_key, target_key in (
                    ("reasoning_steps_json", "reasoning_steps"),
                    ("examples_json", "examples"),
                    ("caveats_json", "caveats"),
                    ("author_caveats_json", "author_caveats"),
                    ("ai_caveats_json", "ai_caveats"),
                    ("genre_fields_json", "genre_fields"),
                    ("relations_json", "relations"),
                ):
                    idea[target_key] = loads(str(idea.pop(source_key)))
                # Analyses stored before the split only have the combined list.
                # Surfacing it as author_caveats keeps those boundaries visible
                # instead of showing an empty section for older books.
                if not idea["author_caveats"] and idea["caveats"]:
                    idea["author_caveats"] = idea["caveats"]
                sources = connection.execute(
                    """
                    SELECT source_spans.*, chapters.id AS source_chapter_id,
                           chapters.title AS source_chapter_title,
                           chapters.source_locator AS source_locator FROM source_spans
                    JOIN core_idea_sources ON core_idea_sources.source_span_id = source_spans.id
                    JOIN chapters ON chapters.id = source_spans.chapter_id
                    WHERE core_idea_sources.core_idea_id = ? ORDER BY source_spans.source_page, source_spans.id
                    """,
                    (idea_row["id"],),
                ).fetchall()
                idea["sources"] = [dict(source) for source in sources]
                ideas.append(idea)
            analysis["core_ideas"] = ideas
            statement_rows = connection.execute(
                """
                SELECT * FROM attributed_statements
                WHERE chapter_analysis_id = ? ORDER BY slot, position
                """,
                (row["id"],),
            ).fetchall()
            statements: dict[str, list[dict[str, object]]] = {"argument_chain": [], "role_in_book": []}
            for statement_row in statement_rows:
                statement = dict(statement_row)
                sources = connection.execute(
                    """
                    SELECT source_spans.*, chapters.id AS source_chapter_id,
                           chapters.title AS source_chapter_title,
                           chapters.source_locator AS source_locator FROM source_spans
                    JOIN attributed_statement_sources
                      ON attributed_statement_sources.source_span_id = source_spans.id
                    JOIN chapters ON chapters.id = source_spans.chapter_id
                    WHERE attributed_statement_sources.attributed_statement_id = ?
                    ORDER BY source_spans.source_page, source_spans.id
                    """,
                    (statement_row["id"],),
                ).fetchall()
                statement["sources"] = [dict(source) for source in sources]
                statements[str(statement["slot"])].append(statement)
            if statement_rows:
                analysis["argument_chain"] = statements["argument_chain"]
                analysis["role_in_book"] = statements["role_in_book"][0] if statements["role_in_book"] else None
            else:
                analysis["argument_chain"] = [
                    {"text": str(item), "content_type": "legacy_summary", "sources": []}
                    for item in legacy_argument_chain
                ]
                role = str(analysis["role_in_book"] or "").strip()
                analysis["role_in_book"] = (
                    {"text": role, "content_type": "legacy_summary", "sources": []} if role else None
                )
            return analysis

    def save_book_overview(self, book_id: str, core_question: str, one_sentence_summary: str, *, snapshot=None, synthesis=None) -> bool:
        with open_connection(self.database_path) as connection:
            if snapshot is not None:
                from app.services.analysis_inputs import publication_allowed
                connection.execute("BEGIN IMMEDIATE")
                if not publication_allowed(connection, snapshot):
                    return False
            connection.execute(
                """
                INSERT INTO book_overviews(book_id, core_question, one_sentence_summary, generation_status)
                VALUES (?, ?, ?, 'ready')
                ON CONFLICT(book_id) DO UPDATE SET
                    core_question = excluded.core_question,
                    one_sentence_summary = excluded.one_sentence_summary,
                    generation_status = 'ready',
                    content_version = book_overviews.content_version + 1
                """,
                (book_id, core_question, one_sentence_summary),
            )
            connection.execute("UPDATE book_overviews SET synthesis_json=? WHERE book_id=?",
                               (dumps(synthesis, ensure_ascii=False) if synthesis else None, book_id))
        return True

    def set_book_overview_status(self, book_id: str, status: str, *, snapshot=None) -> None:
        """Record a non-ready overview state without touching existing content.

        `list_analyzed_books` only surfaces overviews whose status is 'ready',
        so a failure marked here never leaks into the shelf, while a previously
        generated summary (if any) stays readable.
        """
        with open_connection(self.database_path) as connection:
            if snapshot is not None:
                from app.services.analysis_inputs import publication_allowed
                connection.execute("BEGIN IMMEDIATE")
                if not publication_allowed(connection, snapshot):
                    return
            connection.execute(
                """
                INSERT INTO book_overviews(book_id, generation_status) VALUES (?, ?)
                ON CONFLICT(book_id) DO UPDATE SET generation_status = excluded.generation_status
                """,
                (book_id, status),
            )

    def get_book_overview(self, book_id: str) -> dict[str, object] | None:
        with open_connection(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute("SELECT * FROM book_overviews WHERE book_id = ?", (book_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["synthesis"] = loads(result.pop("synthesis_json") or "null")
        return result

    def ready_chapter_analysis_drafts(self, book_id: str) -> list[OverviewChapterInput]:
        inputs = []
        for chapter in self.list_chapters(book_id, confirmed=True):
            analysis = self.get_chapter_analysis(book_id, int(chapter["id"]))
            if analysis is None or analysis["generation_status"] != "ready":
                continue
            role = analysis["role_in_book"]
            inputs.append(OverviewChapterInput(
                chapter_title=str(chapter["title"]), reading_record=analysis.get("reading_record"),
                parent_title=chapter.get("parent_title"), nav_kind=str(chapter.get("nav_kind") or "plain"),
                chapter_id=int(chapter["id"]), content_version=int(analysis["content_version"]),
                chapter_question=str(analysis["chapter_question"]),
                one_sentence_conclusion=str(analysis["one_sentence_conclusion"]),
                role_in_book=overview_role_text(role),
                role_content_type=role.get("content_type") if isinstance(role, dict) else ("legacy_summary" if role else None),
            ))
        return inputs

    def save_learning_unit(
        self, *, unit_id: str, book_id: str, question: str, options_json: str, correct_answer: str,
        explanation: str, source_quote: str, source_page: int,
    ) -> None:
        with open_connection(self.database_path) as connection:
            connection.execute(
                """INSERT INTO learning_units(id, book_id, question, options_json, correct_answer,
                   explanation, source_quote, source_page) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (unit_id, book_id, question, options_json, correct_answer, explanation, source_quote, source_page),
            )

    def get_learning_unit(self, unit_id: str) -> dict[str, int | str] | None:
        with open_connection(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute("SELECT * FROM learning_units WHERE id = ?", (unit_id,)).fetchone()
        return dict(row) if row else None

    def get_owned_learning_unit(self, owner_id: int, unit_id: str) -> dict[str, int | str] | None:
        with open_connection(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """SELECT learning_units.* FROM learning_units
                   JOIN books ON books.id = learning_units.book_id
                   WHERE learning_units.id = ? AND books.owner_id = ?""",
                (unit_id, owner_id),
            ).fetchone()
        return dict(row) if row else None

    def save_prediction(self, unit_id: str, answer: str) -> None:
        with open_connection(self.database_path) as connection:
            connection.execute(
                "INSERT INTO prediction_attempts(learning_unit_id, selected_answer) VALUES (?, ?)", (unit_id, answer)
            )


INDEX_STATEMENTS = (
    # book_pages is range-scanned for every chapter source lookup.
    "CREATE INDEX IF NOT EXISTS idx_book_pages_lookup ON book_pages(book_id, page_number)",
    "CREATE INDEX IF NOT EXISTS idx_chapters_book_position ON chapters(book_id, position)",
    "CREATE INDEX IF NOT EXISTS idx_chapter_drafts_book_position ON chapter_drafts(book_id, position)",
    "CREATE INDEX IF NOT EXISTS idx_chapter_analyses_lookup ON chapter_analyses(book_id, chapter_id)",
    "CREATE INDEX IF NOT EXISTS idx_core_ideas_analysis ON core_ideas(chapter_analysis_id, position)",
    "CREATE INDEX IF NOT EXISTS idx_core_idea_sources_span ON core_idea_sources(source_span_id)",
    "CREATE INDEX IF NOT EXISTS idx_attributed_statements_analysis ON attributed_statements(chapter_analysis_id, slot, position)",
    "CREATE INDEX IF NOT EXISTS idx_attributed_statement_sources_span ON attributed_statement_sources(source_span_id)",
    "CREATE INDEX IF NOT EXISTS idx_source_spans_chapter ON source_spans(chapter_id)",
    "CREATE INDEX IF NOT EXISTS idx_analysis_runs_book ON analysis_runs(book_id, id)",
)


def _migrate_books_to_owner_schema(connection: sqlite3.Connection) -> None:
    """Replace the legacy global digest constraint without losing book rows.

    SQLite cannot remove a table-level UNIQUE constraint in place.  Rebuilding
    only happens for the old shape, before the dependent tables are created on
    a fresh database; existing rows deliberately keep a NULL owner until the
    account bootstrap migration assigns them to the one owner account.
    """
    columns = {row[1] for row in connection.execute("PRAGMA table_info(books)")}
    has_owner_column = "owner_id" in columns
    has_global_digest_constraint = any(
        len(index_columns) == 1 and index_columns[0] == "sha256"
        for index_columns in (
            [item[2] for item in connection.execute(f"PRAGMA index_info({index[1]})")]
            for index in connection.execute("PRAGMA index_list(books)")
            if index[2]
        )
    )
    if has_owner_column and not has_global_digest_constraint:
        return

    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute(
        """
        CREATE TABLE books_owner_migration (
            id TEXT PRIMARY KEY,
            owner_id INTEGER,
            filename TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            stored_path TEXT NOT NULL,
            source_format TEXT NOT NULL DEFAULT 'pdf',
            status TEXT NOT NULL,
            diagnostics_json TEXT NOT NULL,
            title TEXT,
            subtitle TEXT,
            authors TEXT,
            publisher TEXT,
            published_at TEXT,
            identifier TEXT,
            chapter_count INTEGER,
            genre TEXT,
            genre_confidence REAL,
            genre_source TEXT,
            structure_version TEXT,
            structure_diagnostics_json TEXT NOT NULL DEFAULT '[]',
            visibility TEXT NOT NULL DEFAULT 'private' CHECK(visibility IN ('private', 'public')),
            public_at TEXT,
            published_by_user_id INTEGER,
            UNIQUE(owner_id, sha256)
        )
        """
    )
    owner_expression = "owner_id" if has_owner_column else "NULL"
    connection.execute(
        f"""
        INSERT INTO books_owner_migration(
            id, owner_id, filename, sha256, stored_path, source_format, status, diagnostics_json,
            title, subtitle, authors, publisher, published_at, identifier, chapter_count,
            genre, genre_confidence, genre_source, structure_version, structure_diagnostics_json,
            visibility, public_at, published_by_user_id
        )
        SELECT id, {owner_expression}, filename, sha256, stored_path, source_format, status, diagnostics_json,
               title, subtitle, authors, publisher, published_at, identifier, chapter_count,
               genre, genre_confidence, genre_source, structure_version, structure_diagnostics_json,
               visibility, public_at, published_by_user_id
        FROM books
        """
    )
    connection.execute("DROP TABLE books")
    connection.execute("ALTER TABLE books_owner_migration RENAME TO books")


def _rebase_managed_book_paths(connection: sqlite3.Connection, books_dir: Path) -> None:
    """Point a copied database at content-addressed files in its current data root."""
    resolved_books_dir = books_dir.resolve()
    managed_prefix = f"{resolved_books_dir}{os.sep}"
    rows = connection.execute(
        """SELECT id, sha256, source_format, stored_path FROM books
           WHERE substr(stored_path, 1, ?) != ?""",
        (len(managed_prefix), managed_prefix),
    ).fetchall()
    updates: list[tuple[str, str]] = []
    for book_id, digest, source_format, stored_path in rows:
        candidate = resolved_books_dir / f"{digest}.{source_format}"
        if candidate.is_file() and Path(stored_path) != candidate:
            updates.append((str(candidate.resolve(strict=True)), str(book_id)))
    connection.executemany("UPDATE books SET stored_path = ? WHERE id = ?", updates)


def _create_indexes(connection: sqlite3.Connection) -> None:
    for statement in INDEX_STATEMENTS:
        connection.execute(statement)


def _metadata_row(metadata: object | None) -> tuple[str | None, ...]:
    """Flatten parsed book metadata into the books table's column order.

    Absent for PDFs and for callers that do not parse metadata, so every value is
    optional and the row degrades to NULLs rather than failing the insert.
    """
    if metadata is None:
        return (None, None, None, None, None, None, None)
    authors = getattr(metadata, "authors", ()) or ()
    chapter_count = getattr(metadata, "top_level_chapter_count", 0) or None
    return (
        getattr(metadata, "title", None),
        getattr(metadata, "subtitle", None),
        # Stored as a display string, not JSON: nothing queries individual authors, and
        # a plain string keeps the value readable in the database.
        "、".join(authors) or None,
        getattr(metadata, "publisher", None),
        getattr(metadata, "published_at", None),
        getattr(metadata, "identifier", None),
        chapter_count,
    )


def _draft_row(chapter: object) -> tuple[object, ...]:
    """Normalise a chapter draft into database column order.

    Drafts arrive either as parser objects carrying navigation structure or as plain
    four-tuples from callers that predate it. Both are accepted so PDF imports and
    older call sites keep working, with flat defaults standing in for missing fields.
    """
    if isinstance(chapter, tuple):
        title, start, end, text = chapter
        return title, start, end, text, 0, None, "plain", 1, "unknown", "unknown", "low", "analysis_unit", None, None
    return (
        chapter.title,
        chapter.source_start_page,
        chapter.source_end_page,
        chapter.text,
        getattr(chapter, "depth", 0),
        getattr(chapter, "parent_title", None),
        getattr(chapter, "nav_kind", "plain"),
        int(getattr(chapter, "in_body", True)),
        getattr(chapter, "structural_role", "unknown"),
        getattr(chapter, "role_source", "unknown"),
        getattr(chapter, "role_confidence", "low"),
        getattr(chapter, "analysis_role", "analysis_unit"),
        getattr(chapter, "source_locator", None),
        getattr(chapter, "text_sha256", None),
    )


def _migrate_chapter_structure_columns(connection: sqlite3.Connection) -> None:
    """Add the navigation-structure columns to databases created before them.

    EPUB navigation carries real hierarchy (part > chapter > section) that the parser
    now extracts. Older databases only stored a flat title list, so the columns are
    added in place with defaults that describe exactly what those rows are: a flat,
    body-level outline. Adding columns is safe here because every new column is
    nullable or has a default, so existing rows stay valid.
    """
    additions = (
        ("depth", "INTEGER NOT NULL DEFAULT 0"),
        ("parent_title", "TEXT"),
        ("nav_kind", "TEXT NOT NULL DEFAULT 'plain'"),
        ("in_body", "INTEGER NOT NULL DEFAULT 1"),
        ("structural_role", "TEXT NOT NULL DEFAULT 'unknown'"),
        ("role_source", "TEXT NOT NULL DEFAULT 'unknown'"),
        ("role_confidence", "TEXT NOT NULL DEFAULT 'low'"),
        ("analysis_role", "TEXT NOT NULL DEFAULT 'analysis_unit'"),
    )
    for table in ("chapter_drafts", "chapters"):
        _add_missing_columns(connection, table, additions)


def _migrate_structure_identity_columns(connection: sqlite3.Connection) -> None:
    _add_missing_columns(
        connection,
        "books",
        (
            ("structure_version", "TEXT"),
            ("structure_diagnostics_json", "TEXT NOT NULL DEFAULT '[]'"),
        ),
    )
    _add_missing_columns(
        connection,
        "chapters",
        (("source_locator", "TEXT"), ("text_sha256", "TEXT"), ("removed", "INTEGER NOT NULL DEFAULT 0")),
    )
    _add_missing_columns(connection, "chapter_drafts", (("source_locator", "TEXT"), ("text_sha256", "TEXT")))


def _confirmed_identity(
    connection: sqlite3.Connection, book_id: str, chapter: object
) -> tuple[str | None, str | None]:
    """Use parser-provided identity, with a safe PDF page/text fallback."""
    source_locator = getattr(chapter, "source_locator", None)
    text_sha256 = getattr(chapter, "text_sha256", None)
    if source_locator and text_sha256:
        return str(source_locator), str(text_sha256)

    source_format_row = connection.execute("SELECT source_format FROM books WHERE id = ?", (book_id,)).fetchone()
    if source_format_row and source_format_row[0] == "pdf":
        start = int(chapter.source_start_page)
        end = int(chapter.source_end_page)
        return source_locator or f"pdf:pages:{start}-{end}", text_sha256 or _chapter_text_sha256(connection, book_id, start, end)

    drafts = connection.execute(
        """
        SELECT source_locator, text_sha256 FROM chapter_drafts
        WHERE book_id = ? AND title = ? AND source_start_page = ? AND source_end_page = ?
          AND source_locator IS NOT NULL AND text_sha256 IS NOT NULL
        """,
        (book_id, chapter.title, chapter.source_start_page, chapter.source_end_page),
    ).fetchall()
    if len(drafts) == 1:
        return source_locator or str(drafts[0][0]), text_sha256 or str(drafts[0][1])
    return source_locator, text_sha256


def _legacy_identity_index(
    connection: sqlite3.Connection, book_id: str, existing: list[sqlite3.Row]
) -> dict[tuple[str, str], list[sqlite3.Row]]:
    identities: dict[tuple[str, str], list[sqlite3.Row]] = {}
    for row in existing:
        if row["source_locator"]:
            continue
        text_sha256 = row["text_sha256"] or _chapter_text_sha256(
            connection, book_id, row["source_start_page"], row["source_end_page"]
        )
        if text_sha256:
            identities.setdefault((_normalise_title(str(row["title"])), str(text_sha256)), []).append(row)
    return identities


def _legacy_identity_snapshot(
    connection: sqlite3.Connection, book_id: str
) -> dict[tuple[str, str], list[sqlite3.Row]]:
    """Freeze locator-less chapter identities before their source pages are replaced."""
    connection.row_factory = sqlite3.Row
    existing = connection.execute(
        """
        SELECT id, position, title, source_start_page, source_end_page,
               source_locator, text_sha256
        FROM chapters WHERE book_id = ? AND removed = 0 ORDER BY position
        """,
        (book_id,),
    ).fetchall()
    return _legacy_identity_index(connection, book_id, existing)


def _chapter_text_sha256(
    connection: sqlite3.Connection, book_id: str, source_start_page: int, source_end_page: int
) -> str | None:
    pages = connection.execute(
        """
        SELECT text FROM book_pages WHERE book_id = ? AND page_number BETWEEN ? AND ?
        ORDER BY page_number
        """,
        (book_id, source_start_page, source_end_page),
    ).fetchall()
    if not pages:
        return None
    text = "\n\n".join(str(page[0]) for page in pages).strip()
    return sha256(text.encode("utf-8")).hexdigest()


def _normalise_title(title: str) -> str:
    return "".join(title.casefold().split())


def _migrate_core_idea_columns(connection: sqlite3.Connection) -> None:
    """Add the fields that split author-stated boundaries from our own inferences.

    `caveats_json` mixed both, so a reader could not tell whether a limitation
    came from the author or from us. It is left in place for analyses written
    before the split; new rows populate the two explicit columns instead.

    `genre_fields_json` holds every genre-specific field in one column. Giving
    each of the four genres its own columns would push this table past thirty
    columns, most of them null for any given book.
    """
    _add_missing_columns(
        connection,
        "core_ideas",
        (
            ("author_caveats_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("ai_caveats_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("warrant", "TEXT NOT NULL DEFAULT ''"),
            ("genre_fields_json", "TEXT NOT NULL DEFAULT '{}'"),
        ),
    )


def _add_missing_columns(
    connection: sqlite3.Connection, table: str, additions: tuple[tuple[str, str], ...]
) -> None:
    """Add columns that an older database is missing, one ALTER per column.

    SQLite has no "ADD COLUMN IF NOT EXISTS", so compare against table_info
    first. Every definition must be nullable or carry a default, because
    ALTER TABLE cannot backfill a NOT NULL column on existing rows.
    """
    existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    if not existing:
        return
    for column, definition in additions:
        if column not in existing:
            logger.info("adding %s.%s", table, column)
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _migrate_analysis_runs_chapter_id(connection: sqlite3.Connection) -> None:
    """Make analysis_runs.chapter_id nullable and stop using 0 as a sentinel.

    Book-level overview runs were recorded with chapter_id=0 while the column
    declared `FOREIGN KEY(chapter_id) REFERENCES chapters(id)`. No chapter has
    id 0, so those rows violated the constraint the moment foreign keys were
    switched on. NULL is the correct way to say "not tied to a chapter".
    """
    columns = {row[1]: row for row in connection.execute("PRAGMA table_info(analysis_runs)")}
    chapter_column = columns.get("chapter_id")
    if chapter_column is None or not chapter_column[3]:  # index 3 is "notnull"
        return

    logger.info("migrating analysis_runs.chapter_id to a nullable column")
    # Historical rows may reference chapters that no longer exist, and enforcement
    # is already on by the time we get here. Copying them under an active
    # constraint would abort the migration, so suspend it for the rebuild and
    # neutralise the dangling references as we go.
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        _rebuild_analysis_runs(connection)
    finally:
        connection.execute("PRAGMA foreign_keys = ON")


def _rebuild_analysis_runs(connection: sqlite3.Connection) -> None:
    connection.execute("ALTER TABLE analysis_runs RENAME TO analysis_runs_legacy")
    connection.execute(
        """
        CREATE TABLE analysis_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id TEXT NOT NULL,
            chapter_id INTEGER,
            model TEXT,
            status TEXT NOT NULL,
            input_characters INTEGER NOT NULL,
            output_characters INTEGER NOT NULL,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            total_tokens INTEGER,
            elapsed_milliseconds INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE,
            FOREIGN KEY(chapter_id) REFERENCES chapters(id) ON DELETE SET NULL
        )
        """
    )
    connection.execute(
        """
        INSERT INTO analysis_runs(
            id, book_id, chapter_id, model, status, input_characters, output_characters,
            prompt_tokens, completion_tokens, total_tokens, elapsed_milliseconds, created_at
        )
        SELECT
            id,
            book_id,
            CASE
                WHEN chapter_id = 0 THEN NULL
                WHEN chapter_id NOT IN (SELECT id FROM chapters) THEN NULL
                ELSE chapter_id
            END,
            model, status, input_characters, output_characters,
            prompt_tokens, completion_tokens, total_tokens, elapsed_milliseconds, created_at
        FROM analysis_runs_legacy
        """
    )
    connection.execute("DROP TABLE analysis_runs_legacy")


ORPHAN_CHECKS = (
    ("book_overviews", "SELECT COUNT(*) FROM book_overviews WHERE book_id NOT IN (SELECT id FROM books)"),
    ("book_pages", "SELECT COUNT(*) FROM book_pages WHERE book_id NOT IN (SELECT id FROM books)"),
    ("chapters", "SELECT COUNT(*) FROM chapters WHERE book_id NOT IN (SELECT id FROM books)"),
    ("chapter_drafts", "SELECT COUNT(*) FROM chapter_drafts WHERE book_id NOT IN (SELECT id FROM books)"),
    ("chapter_analyses", "SELECT COUNT(*) FROM chapter_analyses WHERE book_id NOT IN (SELECT id FROM books)"),
    (
        "core_ideas",
        "SELECT COUNT(*) FROM core_ideas WHERE chapter_analysis_id NOT IN (SELECT id FROM chapter_analyses)",
    ),
    (
        "source_spans",
        "SELECT COUNT(*) FROM source_spans WHERE chapter_id IS NOT NULL AND chapter_id NOT IN (SELECT id FROM chapters)",
    ),
    (
        "core_idea_sources",
        "SELECT COUNT(*) FROM core_idea_sources WHERE core_idea_id NOT IN (SELECT id FROM core_ideas)"
        " OR source_span_id NOT IN (SELECT id FROM source_spans)",
    ),
    (
        "prediction_attempts",
        "SELECT COUNT(*) FROM prediction_attempts WHERE learning_unit_id NOT IN (SELECT id FROM learning_units)",
    ),
)


def audit_orphan_rows(database_path: Path) -> dict[str, int]:
    """Count rows that violate the now-enforced foreign keys.

    Enforcement only applies to new writes, so pre-existing orphans stay in the
    file and stay invisible. This reports them instead of deleting anything.
    """
    counts: dict[str, int] = {}
    with open_connection(database_path) as connection:
        for table, query in ORPHAN_CHECKS:
            try:
                counts[table] = int(connection.execute(query).fetchone()[0])
            except sqlite3.Error:
                logger.exception("orphan audit failed for table %s", table)
    return {table: count for table, count in counts.items() if count}


class SecretStore(Protocol):
    def save(self, settings: ProviderSettings) -> None: ...
    def load_api_key(self, provider: str) -> str | None: ...


class ReadOnlySecretStoreError(RuntimeError):
    pass


ENVIRONMENT_KEY_NAMES = {
    "openai": "BOOKTHINKING_OPENAI_API_KEY",
    "deepseek": "BOOKTHINKING_DEEPSEEK_API_KEY",
    "deepseek-secondary": "BOOKTHINKING_DEEPSEEK_API_KEY_SECONDARY",
    "deepseek-tertiary": "BOOKTHINKING_DEEPSEEK_API_KEY_TERTIARY",
    "deepseek-quaternary": "BOOKTHINKING_DEEPSEEK_API_KEY_QUATERNARY",
}


class EnvironmentSecretStore:
    def save(self, settings: ProviderSettings) -> None:
        raise ReadOnlySecretStoreError(
            "云端密钥由服务器环境变量管理，不能从浏览器修改"
        )

    def load_api_key(self, provider: str) -> str | None:
        variable = ENVIRONMENT_KEY_NAMES.get(provider)
        if variable is None:
            return None
        value = os.environ.get(variable, "").strip()
        return value or None


class KeyringStore:
    def __init__(self, client: KeyringClient = keyring, service_name: str = "book-learning-local") -> None:
        self.client = client
        self.service_name = service_name

    def save(self, settings: ProviderSettings) -> None:
        self.client.set_password(self.service_name, settings.provider, settings.api_key)

    def load_api_key(self, provider: str) -> str | None:
        return self.client.get_password(self.service_name, provider)


def get_secret_store() -> SecretStore:
    if RuntimeSettings.from_environment().secret_backend == "environment":
        return EnvironmentSecretStore()
    return KeyringStore()
