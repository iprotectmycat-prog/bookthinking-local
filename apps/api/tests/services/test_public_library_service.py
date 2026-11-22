from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.services.public_library import PublicLibraryError, PublicLibraryService
from app.services.pypdf_parser import ChapterDraft
from app.services.storage import ApplicationPaths, BookRepository, open_connection


def publication_fixture(
    tmp_path: Path,
    *,
    overview_status: str,
    ready_chapters: int,
) -> tuple[BookRepository, ApplicationPaths]:
    paths = ApplicationPaths(tmp_path)
    paths.ensure_exists()
    repository = BookRepository(paths.database_path)
    source = paths.books_dir / "book-1.pdf"
    source.write_text("rights-cleared source")
    repository.save_book_import(
        owner_id=1,
        book_id="book-1",
        filename="book-1.pdf",
        sha256="sha-book-1",
        stored_path=source,
        status="chapters_confirmed",
        diagnostics=[],
        pages=["rights-cleared source"],
        chapters=[ChapterDraft("全文", 1, 1, "rights-cleared source")],
    )
    with open_connection(paths.database_path) as connection:
        chapter_id = connection.execute(
            """INSERT INTO chapters(
                   book_id, position, title, source_start_page, source_end_page,
                   analysis_role, removed
               ) VALUES ('book-1', 0, '全文', 1, 1, 'analysis_unit', 0)"""
        ).lastrowid
        if ready_chapters:
            connection.execute(
                """INSERT INTO chapter_analyses(
                       book_id, chapter_id, generation_status, source_content_hash
                   ) VALUES (?, ?, 'ready', 'source-hash')""",
                ("book-1", chapter_id),
            )
    if overview_status == "ready":
        repository.save_book_overview("book-1", "核心问题", "一句话总结")
    else:
        repository.set_book_overview_status("book-1", overview_status)
    return repository, paths


def test_publish_requires_managed_file_ready_overview_and_ready_chapter(tmp_path: Path) -> None:
    repository, paths = publication_fixture(tmp_path, overview_status="pending", ready_chapters=0)
    service = PublicLibraryService(repository, paths)

    assert service.publication_blockers("book-1", owner_id=1) == (
        "全书概览尚未完成",
        "至少需要一个分析完成的可读章节",
    )


def test_publish_and_unpublish_change_only_visibility_metadata(tmp_path: Path) -> None:
    repository, paths = publication_fixture(tmp_path, overview_status="ready", ready_chapters=1)
    service = PublicLibraryService(
        repository,
        paths,
        now=lambda: datetime(2026, 8, 31, tzinfo=timezone.utc),
    )

    published = service.publish("book-1", owner_id=1)

    assert published["visibility"] == "public"
    assert published["published_by_user_id"] == 1
    assert published["public_at"] == "2026-08-31T00:00:00+00:00"

    unpublished = service.unpublish("book-1", owner_id=1)

    assert unpublished["visibility"] == "private"
    assert unpublished["published_by_user_id"] is None
    assert unpublished["public_at"] is None


def test_publish_requires_a_file_inside_the_managed_books_directory(tmp_path: Path) -> None:
    repository, paths = publication_fixture(tmp_path, overview_status="ready", ready_chapters=1)
    source = paths.books_dir / "book-1.pdf"
    source.unlink()
    service = PublicLibraryService(repository, paths)

    assert service.publication_blockers("book-1", owner_id=1) == ("完整原书文件不可用",)

    outside_source = tmp_path / "outside.pdf"
    outside_source.write_text("outside")
    with open_connection(paths.database_path) as connection:
        connection.execute("UPDATE books SET stored_path = ? WHERE id = 'book-1'", (str(outside_source),))

    assert service.publication_blockers("book-1", owner_id=1) == ("完整原书文件不可用",)


def test_publish_rejects_books_not_owned_by_the_actor(tmp_path: Path) -> None:
    repository, paths = publication_fixture(tmp_path, overview_status="ready", ready_chapters=1)
    service = PublicLibraryService(repository, paths)

    with pytest.raises(PublicLibraryError, match="书籍不存在"):
        service.publish("book-1", owner_id=2)
