import sqlite3
from contextlib import closing
from hashlib import sha256
from pathlib import Path

import pytest

from app.services.analysis_providers import ChapterAnalysisDraft, CoreIdeaDraft
from app.services.chapter_confirmation import ConfirmedChapter
from app.services.pypdf_parser import BookMetadata, ChapterDraft, ParsedBook
from app.services.storage import (
    BookRepository,
    KeyringStore,
    ProviderSettings,
    audit_orphan_rows,
    open_connection,
)


class FakeKeyringClient:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def set_password(self, service_name: str, account: str, secret: str) -> None:
        self.values[(service_name, account)] = secret

    def get_password(self, service_name: str, account: str) -> str | None:
        return self.values.get((service_name, account))


def test_book_import_persists_publisher_identifier_and_external_link_cache(tmp_path: Path) -> None:
    repository = BookRepository(tmp_path / "book-learning.sqlite3")
    repository.save_book_import(
        book_id="book-1",
        filename="置身事内.epub",
        sha256="digest",
        stored_path=tmp_path / "置身事内.epub",
        source_format="epub",
        status="awaiting_chapter_confirmation",
        diagnostics=[],
        pages=["第一章正文"],
        chapters=[ChapterDraft("第一章", 1, 1, "第一章正文")],
        metadata=BookMetadata(
            title="置身事内",
            authors=("兰小欢",),
            identifier="978-7-208-17133-6",
        ),
    )

    repository.save_external_book_link(
        book_id="book-1",
        provider="douban",
        status="matched",
        external_id="35546622",
        url="https://book.douban.com/subject/35546622/",
        match_basis="isbn",
        checked_at="2026-08-13T10:00:00+00:00",
        retry_after=None,
    )

    assert repository.get_book("book-1")["identifier"] == "978-7-208-17133-6"
    assert repository.get_external_book_link("book-1", "douban") == {
        "book_id": "book-1",
        "provider": "douban",
        "status": "matched",
        "external_id": "35546622",
        "url": "https://book.douban.com/subject/35546622/",
        "match_basis": "isbn",
        "checked_at": "2026-08-13T10:00:00+00:00",
        "retry_after": None,
    }


def test_provider_key_is_not_written_to_sqlite(tmp_path) -> None:
    settings = ProviderSettings(provider="openai", model="gpt-5", api_key="secret")
    repository = BookRepository(tmp_path / "book-learning.sqlite3")
    keyring_store = KeyringStore(client=FakeKeyringClient(), service_name="book-learning-test")

    keyring_store.save(settings)
    repository.save_provider_metadata(settings.without_key())

    with open_connection(tmp_path / "book-learning.sqlite3") as connection:
        stored_values = connection.execute("SELECT provider, model FROM provider_settings").fetchall()

    assert stored_values == [("openai", "gpt-5")]
    assert keyring_store.load_api_key("openai") == "secret"
    assert "secret" not in (tmp_path / "book-learning.sqlite3").read_bytes().decode(errors="ignore")


def test_confirmed_sources_are_rebuilt_from_page_ranges(tmp_path) -> None:
    repository = BookRepository(tmp_path / "book-learning.sqlite3")
    repository.save_book_import(
        book_id="book-1",
        filename="sample.pdf",
        sha256="digest",
        stored_path=Path("sample.pdf"),
        status="awaiting_chapter_confirmation",
        diagnostics=[],
        pages=["First page evidence.", "Second page evidence."],
        chapters=[("全文", 1, 2, "First page evidence.\n\nSecond page evidence.")],
    )
    repository.replace_confirmed_chapters(
        "book-1",
        [ConfirmedChapter(title="后半部分", source_start_page=2, source_end_page=2)],
    )

    sources = repository.confirmed_chapter_sources("book-1")

    assert len(sources) == 1
    assert sources[0]["title"] == "后半部分"
    assert sources[0]["source_start_page"] == 2
    assert sources[0]["source_end_page"] == 2
    assert sources[0]["text"] == "Second page evidence."


def _locator_chapter(
    title: str, locator: str, text_sha256: str, *, start: int, end: int
) -> ConfirmedChapter:
    return ConfirmedChapter(
        title=title,
        source_start_page=start,
        source_end_page=end,
        source_locator=locator,
        text_sha256=text_sha256,
    )


def _locator_repository(tmp_path: Path) -> BookRepository:
    repository = BookRepository(tmp_path / "books.sqlite3")
    repository.save_book_import(
        book_id="book",
        filename="sample.epub",
        sha256="digest",
        stored_path=Path("sample.epub"),
        source_format="epub",
        status="awaiting_chapter_confirmation",
        diagnostics=[],
        pages=["chapter one", "chapter two"],
        chapters=[
            ("第一章", 1, 1, "chapter one"),
            ("第二章", 2, 2, "chapter two"),
        ],
    )
    return repository


def test_apply_epub_structure_replaces_pages_drafts_metadata_and_stales_overview(
    tmp_path: Path,
) -> None:
    repository = BookRepository(tmp_path / "books.sqlite3")
    repository.save_book_import(
        book_id="book",
        filename="sample.epub",
        sha256="digest",
        stored_path=Path("sample.epub"),
        source_format="epub",
        status="awaiting_chapter_confirmation",
        diagnostics=["旧诊断"],
        pages=["旧整章正文", "必须被删除的旧尾页"],
        chapters=[("旧全文", 1, 2, "旧整章正文")],
    )
    repository.replace_confirmed_chapters(
        "book",
        [_locator_chapter("旧全文", "OPS/book.xhtml", "old", start=1, end=2)],
    )
    repository.save_book_overview("book", "旧核心问题", "旧总结")
    parsed = ParsedBook(
        pages=["第1章正文"],
        chapters=[
            ChapterDraft(
                title="第1章",
                source_start_page=1,
                source_end_page=1,
                text="第1章正文",
                source_locator="OPS/book.xhtml#chapter-1",
                text_sha256="new",
            )
        ],
        diagnostics=[],
    )

    result = repository.apply_epub_structure("book", parsed)

    with open_connection(tmp_path / "books.sqlite3") as connection:
        pages = connection.execute(
            "SELECT page_number, text FROM book_pages WHERE book_id = 'book' ORDER BY page_number"
        ).fetchall()
    assert pages == [(1, "第1章正文")]
    book = repository.get_book("book")
    assert book is not None
    assert book["structure_version"] == "epub-v2"
    assert book["structure_diagnostics_json"] == "[]"
    assert [
        (draft["title"], draft["source_locator"], draft["text_sha256"])
        for draft in repository.list_chapters("book", confirmed=False)
    ] == [("第1章", "OPS/book.xhtml#chapter-1", "new")]
    assert [
        (chapter["title"], chapter["source_locator"], chapter["text_sha256"])
        for chapter in repository.list_chapters("book", confirmed=True)
    ] == [("第1章", "OPS/book.xhtml#chapter-1", "new")]
    overview = repository.get_book_overview("book")
    assert overview is not None
    assert overview["generation_status"] == "stale"
    assert result.added_count == 1


def test_replacing_confirmed_chapters_matches_locator_not_position(tmp_path: Path) -> None:
    repository = _locator_repository(tmp_path)
    book = repository.get_book("book")
    assert book is not None
    assert book["structure_version"] == "epub-v2"
    assert book["structure_diagnostics_json"] == "[]"
    chapter_one = _locator_chapter("第一章", "OPS/book.xhtml#chapter-1", "one", start=1, end=1)
    chapter_two = _locator_chapter("第二章", "OPS/book.xhtml#chapter-2", "two", start=2, end=2)
    repository.replace_confirmed_chapters("book", [chapter_one, chapter_two])
    original_chapter_two_id = next(
        int(chapter["id"])
        for chapter in repository.list_chapters("book", confirmed=True)
        if chapter["source_locator"] == chapter_two.source_locator
    )
    repository.set_chapter_analysis_status(
        book_id="book",
        chapter_id=original_chapter_two_id,
        status="ready",
        source_content_hash="two",
    )

    result = repository.replace_confirmed_chapters("book", [chapter_two, chapter_one])

    assert result.preserved_ids["OPS/book.xhtml#chapter-2"] == original_chapter_two_id
    analysis = repository.get_chapter_analysis("book", original_chapter_two_id)
    assert analysis is not None
    assert analysis["generation_status"] == "ready"


def test_structure_role_change_stales_an_analysis_generated_with_old_weight(tmp_path: Path) -> None:
    repository = _locator_repository(tmp_path)
    original = ConfirmedChapter(
        title="20世纪80年代",
        source_start_page=1,
        source_end_page=1,
        nav_kind="chapter",
        source_locator="OPS/book.xhtml#section-1",
        text_sha256="same",
    )
    repository.replace_confirmed_chapters("book", [original])
    chapter_id = int(repository.list_chapters("book", confirmed=True)[0]["id"])
    repository.set_chapter_analysis_status(
        book_id="book",
        chapter_id=chapter_id,
        status="ready",
        source_content_hash="same",
    )

    result = repository.replace_confirmed_chapters(
        "book",
        [
            ConfirmedChapter(
                title=original.title,
                source_start_page=1,
                source_end_page=1,
                depth=1,
                parent_title="第一章",
                nav_kind="section",
                source_locator=original.source_locator,
                text_sha256="same",
            )
        ],
    )

    assert result.stale_count == 1
    assert repository.get_chapter_analysis("book", chapter_id)["generation_status"] == "stale"


def test_changed_text_at_same_locator_marks_analysis_stale(tmp_path: Path) -> None:
    repository = _locator_repository(tmp_path)
    original = _locator_chapter("第一章", "OPS/book.xhtml#chapter-1", "original", start=1, end=1)
    repository.replace_confirmed_chapters("book", [original])
    original_id = int(repository.list_chapters("book", confirmed=True)[0]["id"])
    repository.set_chapter_analysis_status(
        book_id="book",
        chapter_id=original_id,
        status="ready",
        source_content_hash="original",
    )

    result = repository.replace_confirmed_chapters(
        "book",
        [_locator_chapter("第一章", "OPS/book.xhtml#chapter-1", "changed", start=1, end=1)],
    )

    assert result.preserved_ids["OPS/book.xhtml#chapter-1"] == original_id
    analysis = repository.get_chapter_analysis("book", original_id)
    assert analysis is not None
    assert analysis["generation_status"] == "stale"


def test_applying_epub_structure_does_not_keep_legacy_analysis_ready_on_new_text(
    tmp_path: Path,
) -> None:
    repository = _locator_repository(tmp_path)
    repository.replace_confirmed_chapters(
        "book", [ConfirmedChapter(title="第一章", source_start_page=1, source_end_page=1)]
    )
    legacy_chapter_id = int(repository.list_chapters("book", confirmed=True)[0]["id"])
    with open_connection(tmp_path / "books.sqlite3") as connection:
        connection.execute(
            "UPDATE chapters SET source_locator = NULL, text_sha256 = NULL WHERE id = ?",
            (legacy_chapter_id,),
        )
    repository.set_chapter_analysis_status(
        book_id="book",
        chapter_id=legacy_chapter_id,
        status="ready",
        source_content_hash="legacy-analysis",
    )
    parsed = ParsedBook(
        pages=["reparsed chapter text"],
        chapters=[
            ChapterDraft(
                title="第一章",
                source_start_page=1,
                source_end_page=1,
                text="reparsed chapter text",
                source_locator="OPS/book.xhtml#chapter-1",
                text_sha256=sha256("reparsed chapter text".encode()).hexdigest(),
            )
        ],
        diagnostics=[],
    )

    repository.apply_epub_structure("book", parsed)

    active_chapter = repository.list_chapters("book", confirmed=True)[0]
    if int(active_chapter["id"]) == legacy_chapter_id:
        analysis = repository.get_chapter_analysis("book", legacy_chapter_id)
        assert analysis is not None
        assert analysis["generation_status"] == "stale"
    else:
        assert repository.get_chapter_analysis("book", legacy_chapter_id)["generation_status"] == "stale"


def test_unmatched_analyzed_chapter_is_retained_stale_and_hidden(tmp_path: Path) -> None:
    repository = _locator_repository(tmp_path)
    removed = _locator_chapter("旧章", "OPS/book.xhtml#old", "old", start=1, end=1)
    replacement = _locator_chapter("新章", "OPS/book.xhtml#new", "new", start=1, end=1)
    repository.replace_confirmed_chapters("book", [removed])
    old_id = int(repository.list_chapters("book", confirmed=True)[0]["id"])
    repository.set_chapter_analysis_status(
        book_id="book",
        chapter_id=old_id,
        status="ready",
        source_content_hash="old",
    )

    result = repository.replace_confirmed_chapters("book", [replacement])

    active_chapters = repository.list_chapters("book", confirmed=True)
    assert result.removed_count == 1
    assert result.added_count == 1
    assert len(active_chapters) == 1
    assert active_chapters[0]["id"] != old_id
    assert repository.get_chapter_analysis("book", old_id)["generation_status"] == "stale"
    assert repository.get_chapter_analysis("book", int(active_chapters[0]["id"])) is None
    with open_connection(tmp_path / "books.sqlite3") as connection:
        assert connection.execute("SELECT removed FROM chapters WHERE id = ?", (old_id,)).fetchone() == (1,)


def test_ambiguous_locator_never_reuses_a_confirmed_chapter_id(tmp_path: Path) -> None:
    repository = _locator_repository(tmp_path)
    duplicate_locator = "OPS/book.xhtml#chapter-1"
    repository.replace_confirmed_chapters(
        "book",
        [
            _locator_chapter("第一章", duplicate_locator, "first", start=1, end=1),
            _locator_chapter("第一章（重复）", duplicate_locator, "second", start=2, end=2),
        ],
    )

    result = repository.replace_confirmed_chapters(
        "book", [_locator_chapter("第一章", duplicate_locator, "first", start=1, end=1)]
    )

    assert result.preserved_ids == {}
    assert result.added_count == 1
    assert result.removed_count == 2


def test_shared_parent_child_locator_reapply_preserves_both_ids_and_analysis(tmp_path: Path) -> None:
    repository = _locator_repository(tmp_path)
    locator = "OPS/book.xhtml#chapter-1"
    parent = ConfirmedChapter(
        title="第一章",
        source_start_page=1,
        source_end_page=1,
        depth=0,
        nav_kind="chapter",
        analysis_role="outline_only",
        source_locator=locator,
        text_sha256="same",
    )
    child = ConfirmedChapter(
        title="第一节",
        source_start_page=1,
        source_end_page=1,
        depth=1,
        parent_title="第一章",
        nav_kind="section",
        source_locator=locator,
        text_sha256="same",
    )
    repository.replace_confirmed_chapters("book", [parent, child])
    before = repository.list_chapters("book", confirmed=True)
    child_id = int(before[1]["id"])
    repository.set_chapter_analysis_status(
        book_id="book",
        chapter_id=child_id,
        status="ready",
        source_content_hash="same",
    )

    result = repository.replace_confirmed_chapters("book", [parent, child])
    after = repository.list_chapters("book", confirmed=True)

    assert [int(row["id"]) for row in after] == [int(row["id"]) for row in before]
    assert result.added_count == result.removed_count == result.stale_count == 0
    assert repository.get_chapter_analysis("book", child_id)["generation_status"] == "ready"


def test_connection_is_configured_and_closed(tmp_path: Path) -> None:
    """Regression: `with sqlite3.connect(...)` only ends the transaction, so every
    repository call leaked its connection. It also left foreign keys disabled and
    the journal in rollback mode."""
    database_path = tmp_path / "book-learning.sqlite3"
    BookRepository(database_path)

    with open_connection(database_path) as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] >= 30_000

    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")


def test_foreign_keys_reject_orphan_rows(tmp_path: Path) -> None:
    """Every FOREIGN KEY in the schema was decorative because SQLite disables
    enforcement by default, so rows referencing a missing book were accepted."""
    database_path = tmp_path / "book-learning.sqlite3"
    BookRepository(database_path)

    with pytest.raises(sqlite3.IntegrityError):
        with open_connection(database_path) as connection:
            connection.execute(
                "INSERT INTO book_pages(book_id, page_number, text) VALUES ('ghost-book', 1, 'x')"
            )


def test_deleting_a_book_cascades_to_its_rows(tmp_path: Path) -> None:
    repository = BookRepository(tmp_path / "book-learning.sqlite3")
    repository.save_book_import(
        book_id="book-1",
        filename="sample.pdf",
        sha256="digest",
        stored_path=Path("sample.pdf"),
        status="awaiting_chapter_confirmation",
        diagnostics=[],
        pages=["第一页正文。"],
        chapters=[("第一章", 1, 1, "第一页正文。")],
    )

    with open_connection(tmp_path / "book-learning.sqlite3") as connection:
        connection.execute("DELETE FROM books WHERE id = 'book-1'")

    with open_connection(tmp_path / "book-learning.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM book_pages").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM chapter_drafts").fetchone()[0] == 0


def test_book_level_run_is_stored_without_a_chapter(tmp_path: Path) -> None:
    """chapter_id=0 was used as a "whole book" sentinel while the column pointed
    at chapters(id); no chapter has id 0, so it broke once keys were enforced."""
    repository = BookRepository(tmp_path / "book-learning.sqlite3")
    repository.save_book_import(
        book_id="book-1",
        filename="sample.pdf",
        sha256="digest",
        stored_path=Path("sample.pdf"),
        status="awaiting_chapter_confirmation",
        diagnostics=[],
        pages=["第一页正文。"],
        chapters=[("第一章", 1, 1, "第一页正文。")],
    )

    repository.record_analysis_run(
        book_id="book-1",
        chapter_id=None,
        model="deepseek-chat",
        status="ready",
        input_characters=10,
        output_characters=20,
        prompt_tokens=None,
        completion_tokens=None,
        total_tokens=None,
        elapsed_milliseconds=5,
    )

    runs = repository.list_analysis_runs("book-1")
    assert runs[-1]["chapter_id"] is None


def test_expected_indexes_exist(tmp_path: Path) -> None:
    database_path = tmp_path / "book-learning.sqlite3"
    BookRepository(database_path)

    with open_connection(database_path) as connection:
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}

    assert "idx_book_pages_lookup" in names
    assert "idx_core_ideas_analysis" in names


def test_orphan_audit_reports_pre_existing_rows(tmp_path: Path) -> None:
    """Enforcement only covers new writes, so the audit must still surface rows
    that were inserted back when foreign keys were off."""
    database_path = tmp_path / "book-learning.sqlite3"
    BookRepository(database_path)

    with closing(sqlite3.connect(database_path)) as connection:  # keys deliberately off
        connection.execute("INSERT INTO book_pages(book_id, page_number, text) VALUES ('ghost', 1, 'x')")
        connection.commit()

    assert audit_orphan_rows(database_path) == {"book_pages": 1}


def legacy_database(path: Path) -> None:
    """Recreate the pre-migration schema: chapter_id NOT NULL, 0 as a sentinel."""
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            """
            CREATE TABLE books (
                id TEXT PRIMARY KEY, filename TEXT NOT NULL, sha256 TEXT NOT NULL UNIQUE,
                stored_path TEXT NOT NULL, source_format TEXT NOT NULL DEFAULT 'pdf',
                status TEXT NOT NULL, diagnostics_json TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO books VALUES ('b1','x.pdf','d1','/tmp/x.pdf','pdf','chapters_confirmed','[]')"
        )
        connection.execute(
            """
            CREATE TABLE chapters (
                id INTEGER PRIMARY KEY AUTOINCREMENT, book_id TEXT NOT NULL, position INTEGER NOT NULL,
                title TEXT NOT NULL, source_start_page INTEGER NOT NULL, source_end_page INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO chapters(id, book_id, position, title, source_start_page, source_end_page)"
            " VALUES (7,'b1',0,'第一章',1,1)"
        )
        connection.execute(
            """
            CREATE TABLE analysis_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, book_id TEXT NOT NULL, chapter_id INTEGER NOT NULL,
                model TEXT, status TEXT NOT NULL, input_characters INTEGER NOT NULL,
                output_characters INTEGER NOT NULL, prompt_tokens INTEGER, completion_tokens INTEGER,
                total_tokens INTEGER, elapsed_milliseconds INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        for chapter_id in (0, 99, 7):  # sentinel, dangling reference, valid reference
            connection.execute(
                "INSERT INTO analysis_runs(book_id, chapter_id, model, status, input_characters,"
                " output_characters, elapsed_milliseconds) VALUES ('b1', ?, 'm', 'ready', 1, 2, 3)",
                (chapter_id,),
            )
        connection.commit()


def test_legacy_database_is_migrated_without_losing_runs(tmp_path: Path) -> None:
    database_path = tmp_path / "book-learning.sqlite3"
    legacy_database(database_path)

    BookRepository(database_path)

    with open_connection(database_path) as connection:
        rows = [row[0] for row in connection.execute("SELECT chapter_id FROM analysis_runs ORDER BY id")]
        notnull = [
            row[3] for row in connection.execute("PRAGMA table_info(analysis_runs)") if row[1] == "chapter_id"
        ]
        leftover = connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name = 'analysis_runs_legacy'"
        ).fetchone()[0]

    # 0 (book-level sentinel) and 99 (dangling) become NULL; 7 still exists so it stays.
    assert rows == [None, None, 7]
    assert notnull == [0]
    assert leftover == 0


def test_migration_is_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "book-learning.sqlite3"
    legacy_database(database_path)

    BookRepository(database_path)
    BookRepository(database_path)

    with open_connection(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM analysis_runs").fetchone()[0] == 3


def stored_analysis(repository: BookRepository, **idea_fields: object) -> dict[str, object]:
    """Save one chapter analysis carrying `idea_fields`, then read it back."""
    repository.save_book_import(
        book_id="book-1",
        filename="sample.pdf",
        sha256="digest",
        stored_path=Path("sample.pdf"),
        status="awaiting_chapter_confirmation",
        diagnostics=[],
        pages=["第一页正文。"],
        chapters=[("第一章", 1, 1, "第一页正文。")],
    )
    repository.replace_confirmed_chapters(
        "book-1", [ConfirmedChapter(title="第一章", source_start_page=1, source_end_page=1)]
    )
    chapter_id = int(repository.list_chapters("book-1", confirmed=True)[0]["id"])
    idea = CoreIdeaDraft(
        title="证据优先",
        conclusion="结论必须可回查。",
        importance="避免无依据推断。",
        explanation="说明。",
        reasoning_steps=["检查证据"],
        content_type="book_claim",
        confidence=0.8,
        **idea_fields,  # type: ignore[arg-type]
    )
    draft = ChapterAnalysisDraft(
        chapter_question="问题？",
        one_sentence_conclusion="结论。",
        short_summary="摘要。",
        argument_chain=["提出问题"],
        role_in_book="奠基",
        estimated_reading_minutes=3,
        core_ideas=[idea],
    )
    repository.save_chapter_analysis(
        book_id="book-1",
        chapter_id=chapter_id,
        source_content_hash="hash",
        status="ready",
        draft=draft,
        publishable_ideas=[(idea, [])],
    )
    analysis = repository.get_chapter_analysis("book-1", chapter_id)
    assert analysis is not None
    return analysis["core_ideas"][0]


def test_warrant_and_split_caveats_survive_a_round_trip(tmp_path: Path) -> None:
    repository = BookRepository(tmp_path / "book-learning.sqlite3")

    idea = stored_analysis(
        repository,
        warrant="假定专利数可代表创新水平",
        author_caveats=["只适用于制造业"],
        ai_caveats=["样本仅覆盖发达国家"],
    )

    assert idea["warrant"] == "假定专利数可代表创新水平"
    assert idea["author_caveats"] == ["只适用于制造业"]
    assert idea["ai_caveats"] == ["样本仅覆盖发达国家"]


def test_analyses_stored_before_the_split_show_their_caveats_as_author_stated(tmp_path: Path) -> None:
    """Reading an older analysis must not render an empty boundaries section."""
    repository = BookRepository(tmp_path / "book-learning.sqlite3")

    idea = stored_analysis(repository, caveats=["旧版合并字段"])

    assert idea["author_caveats"] == ["旧版合并字段"]


def test_core_idea_columns_are_added_to_an_existing_database(tmp_path: Path) -> None:
    """Users already have a local database, so the new columns must be added in
    place rather than requiring a rebuild."""
    database_path = tmp_path / "book-learning.sqlite3"
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute(
            """
            CREATE TABLE core_ideas (
                id INTEGER PRIMARY KEY AUTOINCREMENT, chapter_analysis_id INTEGER NOT NULL,
                position INTEGER NOT NULL, title TEXT NOT NULL, conclusion TEXT NOT NULL,
                importance TEXT NOT NULL, explanation TEXT NOT NULL,
                reasoning_steps_json TEXT NOT NULL, examples_json TEXT NOT NULL,
                caveats_json TEXT NOT NULL, relations_json TEXT NOT NULL,
                content_type TEXT NOT NULL, confidence REAL NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO core_ideas(chapter_analysis_id, position, title, conclusion, importance,"
            " explanation, reasoning_steps_json, examples_json, caveats_json, relations_json,"
            " content_type, confidence) VALUES (1, 0, 't', 'c', 'i', 'e', '[]', '[]', '[\"旧\"]', '[]',"
            " 'book_claim', 0.8)"
        )
        connection.commit()

    BookRepository(database_path)

    with open_connection(database_path) as connection:
        row = connection.execute(
            "SELECT warrant, author_caveats_json, ai_caveats_json, caveats_json FROM core_ideas"
        ).fetchone()

    assert row == ("", "[]", "[]", '["旧"]')


def test_genre_columns_are_added_to_an_existing_database(tmp_path) -> None:
    """The user already has a database on disk, so the migration must add these
    columns in place and leave every existing row readable."""
    database = tmp_path / "book-learning.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE books (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                sha256 TEXT NOT NULL UNIQUE,
                stored_path TEXT NOT NULL,
                source_format TEXT NOT NULL DEFAULT 'pdf',
                status TEXT NOT NULL,
                diagnostics_json TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO books VALUES ('old', 'legacy.epub', 'digest', '/tmp/x', 'epub', 'ready', '[]')"
        )

    repository = BookRepository(database)

    with sqlite3.connect(database) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(books)")}
        assert {"genre", "genre_confidence", "genre_source"} <= columns
        row = connection.execute("SELECT filename, genre FROM books WHERE id = 'old'").fetchone()
    assert row == ("legacy.epub", None)
    # Constructing again must not fail on the columns it already added.
    BookRepository(database)
    assert repository.get_book("old") is not None


def test_public_visibility_migration_keeps_existing_books_private(tmp_path: Path) -> None:
    database = tmp_path / "book-learning.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE books (
                id TEXT PRIMARY KEY,
                owner_id INTEGER,
                filename TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                source_format TEXT NOT NULL DEFAULT 'pdf',
                status TEXT NOT NULL,
                diagnostics_json TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO books VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("legacy", 1, "legacy.pdf", "sha", "/tmp/legacy.pdf", "pdf", "ready", "[]"),
        )

    BookRepository(database)

    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT visibility, public_at, published_by_user_id FROM books WHERE id = 'legacy'"
        ).fetchone()
        index = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name = 'books_public_listing'"
        ).fetchone()

    assert row == ("private", None, None)
    assert index == ("books_public_listing",)


def _seed_public_library_book(
    repository: BookRepository,
    tmp_path: Path,
    book_id: str,
    *,
    owner_id: int = 1,
    overview_status: str = "ready",
) -> None:
    source = tmp_path / "books" / f"{book_id}.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(f"source for {book_id}")
    repository.save_book_import(
        owner_id=owner_id,
        book_id=book_id,
        filename=f"{book_id}.pdf",
        sha256=f"sha-{book_id}",
        stored_path=source,
        status="ready",
        diagnostics=[],
        pages=[f"source for {book_id}"],
        chapters=[ChapterDraft("全文", 1, 1, f"source for {book_id}")],
    )
    if overview_status == "ready":
        repository.save_book_overview(book_id, "核心问题", "一句话总结")
    else:
        repository.set_book_overview_status(book_id, overview_status)


def test_readable_books_include_owned_and_public_but_not_other_private(tmp_path: Path) -> None:
    repository = BookRepository(tmp_path / "book-learning.sqlite3")
    _seed_public_library_book(repository, tmp_path, "owner-private")
    _seed_public_library_book(repository, tmp_path, "owner-public")

    repository.set_book_visibility(
        book_id="owner-public",
        owner_id=1,
        visibility="public",
        published_by_user_id=1,
        public_at="2026-08-31T10:00:00+00:00",
    )

    assert repository.get_readable_book(1, "owner-private")["access_scope"] == "owned"
    assert repository.get_readable_book(1, "owner-public")["access_scope"] == "public"
    assert repository.get_readable_book(2, "owner-public")["access_scope"] == "public"
    assert repository.get_readable_book(2, "owner-private") is None
    assert repository.get_readable_stored_book_path(2, "owner-public") == (
        tmp_path / "books" / "owner-public.pdf"
    )
    assert [book["id"] for book in repository.list_public_analyzed_books()] == ["owner-public"]
    assert [book["id"] for book in repository.list_analyzed_books_for_owner(1)] == [
        "owner-private",
        "owner-public",
    ]


def test_public_listing_excludes_pending_overviews_and_orders_recent_first(tmp_path: Path) -> None:
    repository = BookRepository(tmp_path / "book-learning.sqlite3")
    _seed_public_library_book(repository, tmp_path, "older")
    _seed_public_library_book(repository, tmp_path, "newer")
    _seed_public_library_book(repository, tmp_path, "pending", overview_status="pending")

    for book_id, public_at in (
        ("older", "2026-08-30T10:00:00+00:00"),
        ("newer", "2026-08-31T10:00:00+00:00"),
        ("pending", "2026-09-01T10:00:00+00:00"),
    ):
        repository.set_book_visibility(
            book_id=book_id,
            owner_id=1,
            visibility="public",
            published_by_user_id=1,
            public_at=public_at,
        )

    assert [book["id"] for book in repository.list_public_analyzed_books()] == ["newer", "older"]


def test_publishable_books_include_private_and_public_books_with_readiness(tmp_path: Path) -> None:
    repository = BookRepository(tmp_path / "book-learning.sqlite3")
    _seed_public_library_book(repository, tmp_path, "private", overview_status="pending")
    _seed_public_library_book(repository, tmp_path, "public")
    repository.set_book_visibility(
        book_id="public",
        owner_id=1,
        visibility="public",
        published_by_user_id=1,
        public_at="2026-08-31T10:00:00+00:00",
    )
    with open_connection(repository.database_path) as connection:
        chapter_id = connection.execute(
            """INSERT INTO chapters(
                   book_id, position, title, source_start_page, source_end_page, removed
               ) VALUES (?, 0, '全文', 1, 1, 0)""",
            ("public",),
        ).lastrowid
        connection.execute(
            """INSERT INTO chapter_analyses(
                   book_id, chapter_id, generation_status, source_content_hash
               ) VALUES (?, ?, 'ready', 'source-hash')""",
            ("public", chapter_id),
        )

    books = repository.list_publishable_books_for_owner(1)

    assert [(book["id"], book["overview_status"], book["ready_chapter_count"]) for book in books] == [
        ("private", "pending", 0),
        ("public", "ready", 1),
    ]
    assert books[1]["visibility"] == "public"
    assert books[1]["public_at"] == "2026-08-31T10:00:00+00:00"


def test_repository_rebases_copied_book_paths_to_current_data_root(tmp_path: Path) -> None:
    data_root = tmp_path / "copied-data"
    books_dir = data_root / "books"
    books_dir.mkdir(parents=True)
    database_path = data_root / "book-learning.sqlite3"
    repository = BookRepository(database_path)
    repository.save_book_import(
        book_id="portable-book",
        filename="portable.epub",
        sha256="portable-digest",
        stored_path=Path("/Users/previous/.book-learning/books/portable-digest.epub"),
        source_format="epub",
        status="awaiting_chapter_confirmation",
        diagnostics=[],
        pages=[],
        chapters=[],
    )
    copied_source = books_dir / "portable-digest.epub"
    copied_source.write_bytes(b"portable epub")

    migrated = BookRepository(database_path)

    assert migrated.get_stored_book_path("portable-book") == copied_source


def test_structure_identity_columns_are_added_to_existing_database(tmp_path: Path) -> None:
    database_path = tmp_path / "book-learning.sqlite3"
    legacy_database(database_path)

    repository = BookRepository(database_path)

    with open_connection(database_path) as connection:
        book_columns = {row[1] for row in connection.execute("PRAGMA table_info(books)")}
        chapter_columns = {row[1] for row in connection.execute("PRAGMA table_info(chapters)")}
        draft_columns = {row[1] for row in connection.execute("PRAGMA table_info(chapter_drafts)")}
        structure_diagnostics = connection.execute(
            "SELECT structure_version, structure_diagnostics_json FROM books WHERE id = 'b1'"
        ).fetchone()

    assert {"structure_version", "structure_diagnostics_json"} <= book_columns
    assert {
        "source_locator",
        "text_sha256",
        "structural_role",
        "role_source",
        "role_confidence",
    } <= chapter_columns
    assert {
        "source_locator",
        "text_sha256",
        "structural_role",
        "role_source",
        "role_confidence",
    } <= draft_columns
    assert structure_diagnostics == (None, "[]")
    assert repository.get_book("b1") is not None


def test_structural_role_evidence_round_trips_through_drafts_and_confirmed_chapters(tmp_path: Path) -> None:
    repository = BookRepository(tmp_path / "book-learning.sqlite3")
    draft = ChapterDraft(
        title="后记",
        source_start_page=1,
        source_end_page=1,
        text="后记正文",
        structural_role="back_matter",
        role_source="title_fallback",
        role_confidence="medium",
    )
    repository.save_book_import(
        book_id="book-1",
        filename="sample.epub",
        sha256="digest",
        stored_path=Path("sample.epub"),
        status="awaiting_chapter_confirmation",
        diagnostics=[],
        pages=["后记正文"],
        chapters=[draft],
        source_format="epub",
    )

    assert repository.list_chapters("book-1", confirmed=False)[0] | {"id": 1} == {
        "id": 1,
        "title": "后记",
        "source_start_page": 1,
        "source_end_page": 1,
        "depth": 0,
        "parent_title": None,
        "nav_kind": "plain",
        "in_body": True,
        "structural_role": "back_matter",
        "role_source": "title_fallback",
        "role_confidence": "medium",
        "analysis_role": "analysis_unit",
        "source_locator": None,
        "text_sha256": None,
    }

    repository.replace_confirmed_chapters(
        "book-1",
        [
            ConfirmedChapter(
                title="后记",
                source_start_page=1,
                source_end_page=1,
                structural_role="back_matter",
                role_source="title_fallback",
                role_confidence="medium",
            )
        ],
    )

    confirmed = repository.list_chapters("book-1", confirmed=True)[0]
    assert (confirmed["structural_role"], confirmed["role_source"], confirmed["role_confidence"]) == (
        "back_matter",
        "title_fallback",
        "medium",
    )


def test_set_book_genre_is_readable_through_the_prompt_context(tmp_path) -> None:
    repository = BookRepository(tmp_path / "book-learning.sqlite3")
    repository.save_book_import(
        book_id="book-1",
        filename="sample.epub",
        sha256="digest",
        stored_path=Path("sample.epub"),
        status="ready",
        diagnostics=[],
        pages=["正文"],
        chapters=[("第一章", 1, 1, "正文")],
    )

    repository.set_book_genre("book-1", genre="practical", confidence=0.82, source="model")

    context = repository.book_context_for_prompt("book-1")
    assert context["genre"] == "practical"


def test_persists_outline_only_analysis_role_through_confirmation(tmp_path) -> None:
    repository = BookRepository(tmp_path / "book-learning.sqlite3")
    repository.save_book_import(
        book_id="book-1",
        filename="sample.epub",
        sha256="digest",
        stored_path=Path("sample.epub"),
        status="awaiting_chapter_confirmation",
        diagnostics=[],
        pages=["正文"],
        chapters=[
            ChapterDraft(
                title="第一章",
                source_start_page=1,
                source_end_page=1,
                text="正文",
                nav_kind="chapter",
                analysis_role="outline_only",
            )
        ],
        source_format="epub",
    )

    repository.replace_confirmed_chapters(
        "book-1",
        [
            ConfirmedChapter(
                title="第一章",
                source_start_page=1,
                source_end_page=1,
                nav_kind="chapter",
                analysis_role="outline_only",
            )
        ],
    )

    assert repository.list_chapters("book-1", confirmed=True)[0]["analysis_role"] == "outline_only"
    assert repository.confirmed_chapter_sources("book-1")[0]["analysis_role"] == "outline_only"


def test_prompt_context_lists_only_confirmed_body_chapters(tmp_path) -> None:
    """The outline stands in for "the previous chapter's conclusion", which the
    12-thread batch cannot rely on. Front and back matter would pad it with
    entries the reader never treats as chapters."""
    repository = BookRepository(tmp_path / "book-learning.sqlite3")
    repository.save_book_import(
        book_id="book-1",
        filename="sample.epub",
        sha256="digest",
        stored_path=Path("sample.epub"),
        status="ready",
        diagnostics=[],
        pages=["正文一", "正文二", "正文三"],
        chapters=[("第一章", 1, 1, "正文一")],
    )
    repository.replace_confirmed_chapters(
        "book-1",
        [
            ConfirmedChapter(title="版权页", source_start_page=1, source_end_page=1, nav_kind="front_matter", in_body=False),
            ConfirmedChapter(title="第一章", source_start_page=2, source_end_page=2),
            ConfirmedChapter(title="参考文献", source_start_page=3, source_end_page=3, nav_kind="back_matter", in_body=False),
        ],
    )

    context = repository.book_context_for_prompt("book-1")

    assert context["outline"] == ["第一章"]


def test_prompt_context_for_a_missing_book_is_empty_not_an_error(tmp_path) -> None:
    repository = BookRepository(tmp_path / "book-learning.sqlite3")

    context = repository.book_context_for_prompt("nope")

    assert context["title"] == ""
    assert context["genre"] is None
    assert context["outline"] == []
