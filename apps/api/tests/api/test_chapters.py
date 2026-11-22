from io import BytesIO

import httpx
import pytest
from reportlab.pdfgen.canvas import Canvas

from app.main import app
from app.services.chapter_confirmation import ChapterConfirmationError, ChapterConfirmationService
from app.services.storage import BookRepository


def make_text_pdf() -> bytes:
    output = BytesIO()
    canvas = Canvas(output)
    canvas.drawString(72, 720, "Chapter 1: Capital Costs")
    canvas.showPage()
    canvas.save()
    return output.getvalue()


@pytest.mark.anyio
async def test_confirming_chapters_replaces_draft_and_updates_book_status(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        imported = await client.post(
            "/books",
            files={"file": ("sample.pdf", make_text_pdf(), "application/pdf")},
        )
        book_id = imported.json()["id"]
        confirmed = await client.put(
            f"/books/{book_id}/chapters",
            json={"chapters": [{"title": "资本成本", "source_start_page": 1, "source_end_page": 1}]},
        )
        fetched = await client.get(f"/books/{book_id}")

    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "chapters_confirmed"
    assert len(confirmed.json()["chapters"]) == 1
    assert isinstance(confirmed.json()["chapters"][0]["id"], int)
    assert {
        key: confirmed.json()["chapters"][0][key]
        for key in ("title", "source_start_page", "source_end_page")
    } == {"title": "资本成本", "source_start_page": 1, "source_end_page": 1}
    assert fetched.status_code == 200
    assert fetched.json() == confirmed.json()


@pytest.mark.anyio
async def test_rejects_chapter_range_outside_imported_document(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        imported = await client.post(
            "/books",
            files={"file": ("sample.pdf", make_text_pdf(), "application/pdf")},
        )
        response = await client.put(
            f"/books/{imported.json()['id']}/chapters",
            json={"chapters": [{"title": "越界章节", "source_start_page": 1, "source_end_page": 2}]},
        )

    assert response.status_code == 422
    assert response.json() == {"detail": "章节页码超出原书范围"}


@pytest.mark.anyio
async def test_allows_ordered_chapters_to_share_boundary_pages(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    transport = httpx.ASGITransport(app=app)
    output = BytesIO()
    canvas = Canvas(output)
    for text in ("Page one", "Page two", "Page three"):
        canvas.drawString(72, 720, text)
        canvas.showPage()
    canvas.save()

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        imported = await client.post(
            "/books",
            files={"file": ("shared-pages.pdf", output.getvalue(), "application/pdf")},
        )
        response = await client.put(
            f"/books/{imported.json()['id']}/chapters",
            json={"chapters": [
                {"title": "第一章", "source_start_page": 1, "source_end_page": 2},
                {"title": "第二章", "source_start_page": 2, "source_end_page": 3},
            ]},
        )

    assert response.status_code == 200
    assert [chapter["title"] for chapter in response.json()["chapters"]] == ["第一章", "第二章"]


@pytest.mark.anyio
async def test_learning_generation_gate_requires_confirmed_chapters(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        imported = await client.post(
            "/books",
            files={"file": ("sample.pdf", make_text_pdf(), "application/pdf")},
        )

    service = ChapterConfirmationService(BookRepository(tmp_path / "book-learning.sqlite3"))
    with pytest.raises(ChapterConfirmationError, match="章节尚未确认"):
        service.require_confirmed(imported.json()["id"])
