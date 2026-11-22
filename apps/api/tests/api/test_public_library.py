import httpx
import pytest
from io import BytesIO
from reportlab.pdfgen.canvas import Canvas

from app.main import create_app
from app.runtime import RuntimeSettings
from app.services.accounts import AccountRepository
from app.services.authentication import hash_password
from app.services.pypdf_parser import ChapterDraft
from app.services.storage import ApplicationPaths, BookRepository, open_connection


def _pdf_source() -> bytes:
    output = BytesIO()
    canvas = Canvas(output)
    canvas.drawString(72, 720, "Rights-cleared source with enough text for a cover.")
    canvas.showPage()
    canvas.save()
    return output.getvalue()


def _seed_ready_book(paths: ApplicationPaths, owner_id: int, *, book_id: str = "book-1") -> None:
    repository = BookRepository(paths.database_path)
    source = paths.books_dir / f"{book_id}.pdf"
    source.write_bytes(_pdf_source())
    repository.save_book_import(
        owner_id=owner_id,
        book_id=book_id,
        filename=f"{book_id}.pdf",
        sha256=f"sha-{book_id}",
        stored_path=source,
        status="chapters_confirmed",
        diagnostics=[],
        pages=["rights-cleared source"],
        chapters=[ChapterDraft("全文", 1, 1, "rights-cleared source")],
    )
    repository.save_book_overview(book_id, "核心问题", "一句话总结")
    with open_connection(paths.database_path) as connection:
        chapter_id = connection.execute(
            """INSERT INTO chapters(
                   book_id, position, title, source_start_page, source_end_page,
                   analysis_role, removed
               ) VALUES (?, 0, '全文', 1, 1, 'analysis_unit', 0)""",
            (book_id,),
        ).lastrowid
        connection.execute(
            """INSERT INTO chapter_analyses(
                   book_id, chapter_id, generation_status, source_content_hash
               ) VALUES (?, ?, 'ready', 'source-hash')""",
            (book_id, chapter_id),
        )


@pytest.mark.anyio
async def test_cloud_visitors_can_read_only_published_books(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    paths = ApplicationPaths.from_environment()
    paths.ensure_exists()
    accounts = AccountRepository(paths.database_path)
    owner = accounts.bootstrap_owner(email="owner@example.com", password_hash=hash_password("password"))
    accounts.create_session(owner.id, raw_token="owner-token")
    _seed_ready_book(paths, owner.id, book_id="private")
    _seed_ready_book(paths, owner.id, book_id="featured")
    _seed_ready_book(paths, owner.id, book_id="unfinished")
    repository = BookRepository(paths.database_path)
    repository.set_book_visibility(
        book_id="featured", owner_id=owner.id, visibility="public",
        published_by_user_id=owner.id, public_at="2026-08-31T10:00:00+00:00",
    )
    repository.set_book_visibility(
        book_id="unfinished", owner_id=owner.id, visibility="public",
        published_by_user_id=owner.id, public_at="2026-08-31T10:00:00+00:00",
    )
    repository.set_book_overview_status("unfinished", "stale")
    app = create_app(RuntimeSettings(deployment_mode="cloud", secret_backend="environment", analysis_workers=1))

    with open_connection(paths.database_path) as connection:
        chapter_id = connection.execute("SELECT id FROM chapters WHERE book_id = 'featured'").fetchone()[0]

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        shelf = await client.get("/library/public")
        assert shelf.status_code == 200
        assert [book["id"] for book in shelf.json()] == ["featured"]
        for suffix in ("", "/overview", "/file", "/cover", "/external-links/douban", f"/chapters/{chapter_id}/analysis"):
            assert (await client.get(f"/books/featured{suffix}")).status_code == 200, suffix
            assert (await client.get(f"/books/private{suffix}")).status_code == 404, suffix
            assert (await client.get(f"/books/unfinished{suffix}")).status_code == 404, suffix
        assert (await client.get("/library/books/featured/cover")).status_code == 200
        assert (await client.get("/books/featured/overview")).json()["access_scope"] == "public"
        assert (await client.get("/books/featured/overview")).json()["analysis_job"] is None

        client.cookies.set("bookthinking_session", "owner-token")
        assert (await client.get("/books/private")).status_code == 404
        assert (await client.get("/library/books/private/cover")).status_code == 404
        repository.set_book_visibility(
            book_id="featured", owner_id=owner.id, visibility="private",
            published_by_user_id=None, public_at=None,
        )
        assert (await client.get("/library/public")).json() == []
        for suffix in ("", "/overview", "/file", "/cover", f"/chapters/{chapter_id}/analysis"):
            assert (await client.get(f"/books/featured{suffix}")).status_code == 404, suffix
