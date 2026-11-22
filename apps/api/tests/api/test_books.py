from io import BytesIO
import sqlite3
from zipfile import ZIP_STORED, ZipFile

import httpx
import pytest
from reportlab.pdfgen.canvas import Canvas

from app.main import app
from app.api.routes.books import get_douban_link_matcher
from app.services.douban_links import DoubanMatchResult
from app.services.pypdf_parser import BookMetadata, ChapterDraft
from app.services.storage import BookRepository, open_connection


def make_text_pdf(heading: str = "Chapter 1: Capital Costs") -> bytes:
    output = BytesIO()
    canvas = Canvas(output)
    canvas.drawString(72, 720, heading)
    canvas.drawString(72, 690, "Capital costs change the value of future cash flows.")
    canvas.showPage()
    canvas.save()
    return output.getvalue()


def make_numbered_text_pdf() -> bytes:
    output = BytesIO()
    canvas = Canvas(output)
    canvas.drawString(72, 720, "1. Introduction")
    canvas.drawString(72, 690, "First section evidence.")
    canvas.showPage()
    canvas.drawString(72, 720, "2. Transactions")
    canvas.drawString(72, 690, "Second section evidence.")
    canvas.showPage()
    canvas.save()
    return output.getvalue()


def make_scanned_pdf_placeholder() -> bytes:
    output = BytesIO()
    canvas = Canvas(output)
    canvas.showPage()
    canvas.save()
    return output.getvalue()


def make_epub() -> bytes:
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            "<container xmlns=\"urn:oasis:names:tc:opendocument:xmlns:container\"><rootfiles><rootfile full-path=\"OPS/package.opf\"/></rootfiles></container>",
        )
        archive.writestr(
            "OPS/package.opf",
            "<package xmlns=\"http://www.idpf.org/2007/opf\"><manifest><item id=\"chapter\" href=\"chapter.xhtml\" media-type=\"application/xhtml+xml\"/></manifest><spine><itemref idref=\"chapter\"/></spine></package>",
        )
        archive.writestr("OPS/chapter.xhtml", "<html><body><p>EPUB source evidence.</p></body></html>")
    return output.getvalue()


class StubDoubanMatcher:
    def __init__(self, result: DoubanMatchResult) -> None:
        self.result = result
        self.calls = 0

    def resolve(self, _identity: object) -> DoubanMatchResult:
        self.calls += 1
        self.identity = _identity
        return self.result


def seed_douban_book(tmp_path) -> str:
    repository = BookRepository(tmp_path / "book-learning.sqlite3")
    repository.save_book_import(
        book_id="douban-book",
        filename="置身事内.epub",
        sha256="douban-digest",
        stored_path=tmp_path / "books" / "douban.epub",
        source_format="epub",
        status="awaiting_chapter_confirmation",
        diagnostics=[],
        pages=["正文"],
        chapters=[ChapterDraft("第一章", 1, 1, "正文")],
        metadata=BookMetadata(
            title="置身事内",
            authors=("兰小欢",),
            publisher="上海人民出版社",
            published_at="2021-08-01",
            identifier="9787208171336",
        ),
    )
    return "douban-book"


@pytest.mark.anyio
async def test_douban_link_resolves_once_then_uses_the_cached_direct_url(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    book_id = seed_douban_book(tmp_path)
    matcher = StubDoubanMatcher(DoubanMatchResult.matched("35546622", "isbn"))
    app.dependency_overrides[get_douban_link_matcher] = lambda: matcher
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            first = await client.get(f"/books/{book_id}/external-links/douban")
            second = await client.get(f"/books/{book_id}/external-links/douban")
    finally:
        app.dependency_overrides.clear()

    expected = {
        "provider": "douban",
        "status": "matched",
        "url": "https://book.douban.com/subject/35546622/",
    }
    assert first.json() == expected
    assert second.json() == expected
    assert matcher.calls == 1


@pytest.mark.anyio
async def test_douban_link_uses_a_cleaned_filename_when_a_pdf_has_no_metadata(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    repository = BookRepository(tmp_path / "book-learning.sqlite3")
    repository.save_book_import(
        book_id="filename-fallback-book",
        filename="置身事内 中国政府与经济发展 (兰小欢,非墨盟) (z-lib.org).pdf",
        sha256="filename-fallback-digest",
        stored_path=tmp_path / "books" / "filename-fallback.pdf",
        source_format="pdf",
        status="awaiting_chapter_confirmation",
        diagnostics=[],
        pages=["正文"],
        chapters=[ChapterDraft("第一章", 1, 1, "正文")],
    )
    matcher = StubDoubanMatcher(DoubanMatchResult.matched("35546622", "title_author"))
    app.dependency_overrides[get_douban_link_matcher] = lambda: matcher
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/books/filename-fallback-book/external-links/douban")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert matcher.identity.title == "置身事内 中国政府与经济发展"
    assert matcher.identity.authors == ("兰小欢",)


@pytest.mark.anyio
async def test_douban_link_stays_unavailable_when_a_legacy_epub_source_is_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    repository = BookRepository(tmp_path / "book-learning.sqlite3")
    repository.save_book_import(
        book_id="missing-epub-book",
        filename="旧制度与大革命 (托克维尔).epub",
        sha256="missing-epub-digest",
        stored_path=tmp_path / "books" / "missing.epub",
        source_format="epub",
        status="awaiting_chapter_confirmation",
        diagnostics=[],
        pages=["正文"],
        chapters=[ChapterDraft("第一章", 1, 1, "正文")],
    )
    matcher = StubDoubanMatcher(DoubanMatchResult("not_found"))
    app.dependency_overrides[get_douban_link_matcher] = lambda: matcher
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/books/missing-epub-book/external-links/douban")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"provider": "douban", "status": "unavailable", "url": None}
    assert matcher.identity.title == "旧制度与大革命"


@pytest.mark.anyio
async def test_douban_link_recovers_identity_from_an_existing_epub_without_reimporting(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    source_path = tmp_path / "books" / "legacy.epub"
    source_path.parent.mkdir()
    with ZipFile(source_path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OPS/package.opf"/></rootfiles></container>',
        )
        archive.writestr(
            "OPS/package.opf",
            '''<package xmlns="http://www.idpf.org/2007/opf"><metadata>
              <dc:title xmlns:dc="http://purl.org/dc/elements/1.1/">置身事内</dc:title>
              <dc:creator xmlns:dc="http://purl.org/dc/elements/1.1/">兰小欢</dc:creator>
              <dc:publisher xmlns:dc="http://purl.org/dc/elements/1.1/">上海人民出版社</dc:publisher>
              <dc:date xmlns:dc="http://purl.org/dc/elements/1.1/">2021-08-01</dc:date>
              <dc:identifier xmlns:dc="http://purl.org/dc/elements/1.1/">legacy-uuid</dc:identifier>
            </metadata></package>''',
        )
    repository = BookRepository(tmp_path / "book-learning.sqlite3")
    repository.save_book_import(
        book_id="legacy-book", filename="置身事内 (兰小欢).epub", sha256="legacy-digest",
        stored_path=source_path, source_format="epub", status="awaiting_chapter_confirmation",
        diagnostics=[], pages=["正文"], chapters=[ChapterDraft("第一章", 1, 1, "正文")],
    )
    matcher = StubDoubanMatcher(DoubanMatchResult.matched("35546622", "title_author_publisher_year"))
    app.dependency_overrides[get_douban_link_matcher] = lambda: matcher
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/books/legacy-book/external-links/douban")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert matcher.identity.title == "置身事内"
    assert matcher.identity.authors == ("兰小欢",)
    assert matcher.identity.publisher == "上海人民出版社"
    assert matcher.identity.published_year == "2021"
    assert BookRepository(tmp_path / "book-learning.sqlite3").get_book("legacy-book")["title"] == "置身事内"


@pytest.mark.anyio
async def test_serves_a_local_cached_cover_for_an_uploaded_pdf(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        imported = await client.post("/books", files={"file": ("cover.pdf", make_text_pdf(), "application/pdf")})
        cover = await client.get(f"/books/{imported.json()['id']}/cover")

    assert imported.status_code == 201
    assert cover.status_code == 200
    assert cover.headers["content-type"] == "image/webp"
    assert cover.headers["cache-control"] == "private, max-age=31536000, immutable"
    assert cover.content[:4] == b"RIFF"


@pytest.mark.anyio
async def test_local_import_and_library_do_not_require_an_account_session(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        imported = await client.post("/books", files={"file": ("cover.pdf", make_text_pdf(), "application/pdf")})
        assert imported.status_code == 201
        BookRepository(tmp_path / "book-learning.sqlite3").save_book_overview(
            imported.json()["id"], "核心问题", "核心结论"
        )
        shelf = await client.get("/library/analyzed")
        cover = await client.get(f"/library/books/{imported.json()['id']}/cover")

    assert shelf.status_code == 200
    assert shelf.json()[0]["id"] == imported.json()["id"]
    assert cover.status_code == 200
    assert cover.headers["content-type"] == "image/webp"


@pytest.mark.anyio
async def test_local_api_does_not_expose_account_routes(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/auth/session")

    assert response.status_code == 404


def make_epub_with_unresolved_anchor() -> bytes:
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            "<container xmlns=\"urn:oasis:names:tc:opendocument:xmlns:container\"><rootfiles><rootfile full-path=\"OPS/package.opf\"/></rootfiles></container>",
        )
        archive.writestr(
            "OPS/package.opf",
            """<package xmlns="http://www.idpf.org/2007/opf" version="3.0"><metadata/>
              <manifest>
                <item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>
                <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
              </manifest><spine><itemref idref="chapter"/></spine>
            </package>""",
        )
        archive.writestr(
            "OPS/nav.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"><body><nav epub:type="toc" xmlns:epub="http://www.idpf.org/2007/ops"><ol>
              <li><a href="chapter.xhtml#missing">第一章</a></li>
            </ol></nav></body></html>""",
        )
        archive.writestr("OPS/chapter.xhtml", "<html><body><p>正文仍可读取。</p></body></html>")
    return output.getvalue()


async def import_epub(tmp_path, monkeypatch) -> str:
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/books", files={"file": ("sample.epub", make_epub(), "application/epub+zip")}
        )
    assert response.status_code == 201
    return response.json()["id"]


def chapter_rows(tmp_path, book_id: str) -> dict[str, list[tuple[object, ...]]]:
    with open_connection(tmp_path / "book-learning.sqlite3") as connection:
        return {
            "book": connection.execute(
                "SELECT status, structure_version, structure_diagnostics_json FROM books WHERE id = ?",
                (book_id,),
            ).fetchall(),
            "drafts": connection.execute(
                "SELECT position, title, source_locator, text_sha256 FROM chapter_drafts "
                "WHERE book_id = ? ORDER BY position",
                (book_id,),
            ).fetchall(),
            "chapters": connection.execute(
                "SELECT id, position, title, source_locator, text_sha256, removed FROM chapters "
                "WHERE book_id = ? ORDER BY position, id",
                (book_id,),
            ).fetchall(),
        }


def page_rows(tmp_path, book_id: str) -> list[tuple[object, ...]]:
    with open_connection(tmp_path / "book-learning.sqlite3") as connection:
        return connection.execute(
            "SELECT page_number, text FROM book_pages WHERE book_id = ? ORDER BY page_number",
            (book_id,),
        ).fetchall()


@pytest.mark.anyio
async def test_epub_structure_preview_is_read_only(tmp_path, monkeypatch) -> None:
    book_id = await import_epub(tmp_path, monkeypatch)
    before = chapter_rows(tmp_path, book_id)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/books/{book_id}/structure-preview")

    assert response.status_code == 200
    assert response.json()["provider"] == "stdlib-epub-v2"
    assert len(response.json()["structure_hash"]) == 64
    assert response.json()["chapters"][0]["source_locator"] == "OPS/chapter.xhtml"
    assert chapter_rows(tmp_path, book_id) == before


@pytest.mark.anyio
async def test_apply_rejects_a_stale_structure_hash(tmp_path, monkeypatch) -> None:
    book_id = await import_epub(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put(f"/books/{book_id}/structure", json={"structure_hash": "wrong"})

    assert response.status_code == 409


@pytest.mark.anyio
async def test_apply_reparses_an_unconfirmed_epub_without_skipping_confirmation(tmp_path, monkeypatch) -> None:
    book_id = await import_epub(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        preview = await client.post(f"/books/{book_id}/structure-preview")
        applied = await client.put(
            f"/books/{book_id}/structure",
            json={"structure_hash": preview.json()["structure_hash"]},
        )

    assert applied.status_code == 200
    assert applied.json() == {
        "preserved_count": 0,
        "stale_count": 0,
        "added_count": 1,
        "removed_count": 0,
    }
    rows = chapter_rows(tmp_path, book_id)
    assert rows["book"] == [("awaiting_chapter_confirmation", "epub-v2", "[]")]
    assert rows["chapters"] == []
    assert len(rows["drafts"]) == 1


@pytest.mark.anyio
async def test_reuploading_confirmed_epub_does_not_rewrite_fragment_pages(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    transport = httpx.ASGITransport(app=app)
    epub = make_epub()

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        imported = await client.post(
            "/books", files={"file": ("sample.epub", epub, "application/epub+zip")}
        )
        book_id = imported.json()["id"]
        confirmed = await client.put(
            f"/books/{book_id}/chapters",
            json={"chapters": [{"title": "全文", "source_start_page": 1, "source_end_page": 1}]},
        )
        assert confirmed.status_code == 200
        with open_connection(tmp_path / "book-learning.sqlite3") as connection:
            connection.execute(
                "UPDATE book_pages SET text = '已确认的分片正文' WHERE book_id = ? AND page_number = 1",
                (book_id,),
            )
        before = page_rows(tmp_path, book_id)

        repeated = await client.post(
            "/books", files={"file": ("same.epub", epub, "application/epub+zip")}
        )

    assert repeated.status_code == 201
    assert repeated.json()["id"] == book_id
    assert page_rows(tmp_path, book_id) == before


@pytest.mark.anyio
async def test_structure_endpoints_reject_non_epub_books(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        imported = await client.post(
            "/books", files={"file": ("sample.pdf", make_text_pdf(), "application/pdf")}
        )
        book_id = imported.json()["id"]
        preview = await client.post(f"/books/{book_id}/structure-preview")
        applied = await client.put(f"/books/{book_id}/structure", json={"structure_hash": "wrong"})

    assert preview.status_code == 422
    assert applied.status_code == 422


@pytest.mark.anyio
async def test_imports_text_layer_pdf_and_returns_chapter_draft(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/books",
            files={"file": ("sample.pdf", make_text_pdf(), "application/pdf")},
        )

    body = response.json()
    assert response.status_code == 201
    assert len(body["id"]) == 36
    assert len(body["sha256"]) == 64
    assert body["status"] == "awaiting_chapter_confirmation"
    assert body["diagnostics"] == []
    assert body["chapters"] == [
        {
            "title": "全文",
            "source_start_page": 1,
            "source_end_page": 1,
            "depth": 0,
            "parent_title": None,
            "nav_kind": "plain",
            "in_body": True,
            "structural_role": "unknown",
            "role_source": "unknown",
                "role_confidence": "low",
                "analysis_role": "analysis_unit",
            }
    ]
    with open_connection(tmp_path / "book-learning.sqlite3") as connection:
        stored_book = connection.execute(
            "SELECT filename, sha256, status FROM books WHERE id = ?", (body["id"],)
        ).fetchone()
        stored_draft = connection.execute(
            "SELECT title, source_start_page, source_end_page FROM chapter_drafts WHERE book_id = ?",
            (body["id"],),
        ).fetchone()

    assert stored_book == ("sample.pdf", body["sha256"], "awaiting_chapter_confirmation")
    assert stored_draft == ("全文", 1, 1)


@pytest.mark.anyio
async def test_serves_imported_pdf_inline_from_managed_storage(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    transport = httpx.ASGITransport(app=app)
    pdf = make_text_pdf()

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        imported = await client.post("/books", files={"file": ("sample.pdf", pdf, "application/pdf")})
        opened = await client.get(f"/books/{imported.json()['id']}/file")
        missing = await client.get("/books/does-not-exist/file")

    assert opened.status_code == 200
    assert opened.headers["content-type"].startswith("application/pdf")
    assert opened.headers["content-disposition"].startswith("inline")
    assert opened.content == pdf
    assert missing.status_code == 404


@pytest.mark.anyio
async def test_imports_epub_and_serves_the_native_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    transport = httpx.ASGITransport(app=app)
    epub = make_epub()

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        imported = await client.post(
            "/books", files={"file": ("sample.epub", epub, "application/epub+zip")}
        )
        assert imported.status_code == 201
        fetched = await client.get(f"/books/{imported.json()['id']}")
        opened = await client.get(f"/books/{imported.json()['id']}/file")

    assert imported.json()["source_format"] == "epub"
    assert imported.json()["chapters"][0]["title"] == "全文"
    assert fetched.json()["structure_version"] == "epub-v2"
    assert fetched.json()["structure_diagnostics"] == []
    assert opened.status_code == 200
    assert opened.headers["content-type"].startswith("application/epub+zip")
    assert opened.content == epub


@pytest.mark.anyio
async def test_book_response_exposes_parsed_title_and_subtitle_for_confirmation(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    repository = BookRepository(tmp_path / "book-learning.sqlite3")
    repository.save_book_import(
        book_id="metadata-book",
        filename="反脆弱 (Z-Library).epub",
        sha256="metadata-digest",
        stored_path=tmp_path / "books" / "metadata.epub",
        source_format="epub",
        status="awaiting_chapter_confirmation",
        diagnostics=[],
        pages=["正文"],
        chapters=[ChapterDraft("第一章", 1, 1, "正文")],
        metadata=BookMetadata(title="反脆弱", subtitle="从不确定性中获益"),
    )
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/books/metadata-book")

    assert response.status_code == 200
    assert response.json()["title"] == "反脆弱"
    assert response.json()["subtitle"] == "从不确定性中获益"


@pytest.mark.anyio
async def test_import_response_includes_epub_anchor_diagnostics(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/books",
            files={"file": ("unresolved.epub", make_epub_with_unresolved_anchor(), "application/epub+zip")},
        )

    assert response.status_code == 201
    assert response.json()["diagnostics"] == ["unresolved_anchor:OPS/chapter.xhtml#missing"]


@pytest.mark.anyio
async def test_reimporting_same_pdf_returns_existing_book(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    pdf = make_text_pdf()

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post("/books", files={"file": ("sample.pdf", pdf, "application/pdf")})
        second = await client.post(
            "/books", files={"file": ("sample.pdf", pdf, "application/pdf")}
        )

    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]


@pytest.mark.anyio
async def test_lists_only_books_with_completed_analysis(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        completed = await client.post(
            "/books", files={"file": ("BTC PDF.pdf", make_text_pdf(), "application/pdf")}
        )
        waiting = await client.post(
            "/books", files={"file": ("就业、利息和货币通论.epub", make_epub(), "application/epub+zip")}
        )

        repository = BookRepository(tmp_path / "book-learning.sqlite3")
        repository.save_book_overview(
            completed.json()["id"], "BTC 的市场叙事如何影响风险判断？", "复盘历史市场叙事与风险条件。"
        )
        response = await client.get("/books/analyzed")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": completed.json()["id"],
            "filename": "BTC PDF.pdf",
            "source_format": "pdf",
            "title": None,
            "authors": None,
            "access_scope": "owned",
        }
    ]
    assert waiting.json()["id"] not in [book["id"] for book in response.json()]


@pytest.mark.anyio
async def test_reimporting_legacy_book_backfills_page_text(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    pdf = make_text_pdf()

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post("/books", files={"file": ("sample.pdf", pdf, "application/pdf")})
        with open_connection(tmp_path / "book-learning.sqlite3") as connection:
            connection.execute("DELETE FROM book_pages WHERE book_id = ?", (first.json()["id"],))
        second = await client.post("/books", files={"file": ("sample.pdf", pdf, "application/pdf")})

    with open_connection(tmp_path / "book-learning.sqlite3") as connection:
        page_count = connection.execute(
            "SELECT COUNT(*) FROM book_pages WHERE book_id = ?", (first.json()["id"],)
        ).fetchone()[0]

    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]
    assert page_count == 1


@pytest.mark.anyio
async def test_reimporting_unconfirmed_book_refreshes_inferred_chapter_drafts(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    pdf = make_text_pdf()

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post("/books", files={"file": ("sample.pdf", pdf, "application/pdf")})
        with open_connection(tmp_path / "book-learning.sqlite3") as connection:
            connection.execute(
                "UPDATE chapter_drafts SET title = '旧草稿' WHERE book_id = ?",
                (first.json()["id"],),
            )
        second = await client.post("/books", files={"file": ("sample.pdf", pdf, "application/pdf")})

    assert second.json()["chapters"][0]["title"] == "全文"


@pytest.mark.anyio
async def test_reimporting_legacy_full_book_upgrades_confirmed_numbered_chapters(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    pdf = make_numbered_text_pdf()

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        imported = await client.post("/books", files={"file": ("numbered.pdf", pdf, "application/pdf")})
        book_id = imported.json()["id"]
        await client.put(
            f"/books/{book_id}/chapters",
            json={"chapters": [{"title": "全文", "source_start_page": 1, "source_end_page": 2}]},
        )
        repeated = await client.post("/books", files={"file": ("numbered.pdf", pdf, "application/pdf")})

    assert [chapter["title"] for chapter in repeated.json()["chapters"]] == [
        "1. Introduction",
        "2. Transactions",
    ]


@pytest.mark.anyio
async def test_imports_pdf_without_extractable_text_as_needs_attention(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/books",
            files={"file": ("scan.pdf", make_scanned_pdf_placeholder(), "application/pdf")},
        )
        fetched = await client.get(f"/books/{response.json()['id']}")

    assert response.status_code == 201
    assert response.json()["status"] == "needs_attention"
    assert response.json()["chapters"] == []
    assert response.json()["diagnostics"] == ["PDF 未提取到可用文本；扫描件暂不支持"]
    assert fetched.json()["diagnostics"] == ["PDF 未提取到可用文本；扫描件暂不支持"]


@pytest.mark.anyio
async def test_rejects_invalid_pdf_content_even_when_mime_type_is_pdf(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/books",
            files={"file": ("broken.pdf", b"%PDF-not-a-real-document", "application/pdf")},
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "无法读取 PDF 文件"}
    assert list((tmp_path / "books").glob("*.pdf")) == []


@pytest.mark.anyio
async def test_kindle_upload_is_rejected_with_a_conversion_hint(tmp_path, monkeypatch) -> None:
    """Browsers send Kindle files as octet-stream, so a content-type allowlist used to
    reject them before the importer could explain how to convert the file."""
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    transport = httpx.ASGITransport(app=app)
    palm_header = bytearray(b"\0" * 78)
    palm_header[60:68] = b"BOOKMOBI"
    mobi = bytes(palm_header) + b"\0" * 200

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/books", files={"file": ("sample.mobi", mobi, "application/octet-stream")}
        )

    assert response.status_code == 400
    assert "MOBI" in response.json()["detail"]
    assert "Calibre" in response.json()["detail"]


@pytest.mark.anyio
async def test_kepub_upload_is_accepted_despite_octet_stream_content_type(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    transport = httpx.ASGITransport(app=app)
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OPS/package.opf"/></rootfiles></container>',
        )
        archive.writestr(
            "OPS/package.opf",
            '<package xmlns="http://www.idpf.org/2007/opf"><manifest>'
            '<item id="c" href="c.xhtml" media-type="application/xhtml+xml"/></manifest>'
            '<spine><itemref idref="c"/></spine></package>',
        )
        archive.writestr("OPS/c.xhtml", "<html><body><p>Kobo 正文。</p></body></html>")

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/books",
            files={"file": ("sample.kepub.epub", buffer.getvalue(), "application/octet-stream")},
        )

    assert response.status_code == 201
    assert response.json()["source_format"] == "epub"
