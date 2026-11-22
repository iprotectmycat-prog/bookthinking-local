import asyncio
import sqlite3
from io import BytesIO
from threading import Event

import httpx
import pytest
from reportlab.pdfgen.canvas import Canvas

from app.api.routes import analyses
from app.api.routes.analyses import get_analysis_provider
from app.main import app
from app.services.analysis_providers import (
    BookOverviewDraft,
    ChapterAnalysisDraft,
    ChapterSource,
    CoreIdeaDraft,
    EvidenceDraft,
)


class RouteFixtureProvider:
    def __init__(self) -> None:
        self.generate_calls = 0

    def generate(self, chapter: ChapterSource) -> ChapterAnalysisDraft:
        self.generate_calls += 1
        quote = next(line.strip() for line in chapter.text.splitlines() if len(line.strip()) >= 20)
        return ChapterAnalysisDraft(
            chapter_question=f"{chapter.title}试图解决什么问题？",
            one_sentence_conclusion=f"{chapter.title}的结论来自原文证据。",
            short_summary=f"这是{chapter.title}的三分钟精简分析。",
            argument_chain=["问题", "证据", "结论"],
            role_in_book="推进全书论证",
            estimated_reading_minutes=3,
            core_ideas=[
                CoreIdeaDraft(
                    title="核心思想",
                    conclusion="结论可以回查原文。",
                    importance="保持分析可信。",
                    explanation="这是通俗解析。",
                    reasoning_steps=["定位证据", "解释证据"],
                    content_type="book_claim",
                    confidence=0.9,
                    evidence=[EvidenceDraft(page=chapter.source_start_page, quote=quote)],
                )
            ],
        )

    def generate_book_overview(self, chapters: list[ChapterAnalysisDraft]) -> BookOverviewDraft:
        return BookOverviewDraft(core_question="全书如何建立可信结论？", one_sentence_summary="每章都以证据支持结论。")


class BlockingRouteProvider(RouteFixtureProvider):
    def __init__(self) -> None:
        super().__init__()
        self.started = Event()
        self.release = Event()

    def generate(self, chapter: ChapterSource) -> ChapterAnalysisDraft:
        self.started.set()
        assert self.release.wait(timeout=3)
        return super().generate(chapter)


def make_two_chapter_pdf() -> bytes:
    output = BytesIO()
    canvas = Canvas(output)
    canvas.bookmarkPage("chapter-1")
    canvas.addOutlineEntry("第一章", "chapter-1")
    canvas.drawString(72, 720, "First chapter contains enough source evidence. " * 12)
    canvas.showPage()
    canvas.bookmarkPage("chapter-2")
    canvas.addOutlineEntry("第二章", "chapter-2")
    canvas.drawString(72, 720, "Second chapter contains enough source evidence. " * 12)
    canvas.showPage()
    canvas.save()
    return output.getvalue()


@pytest.mark.anyio
async def test_analysis_routes_return_overview_and_chapter_detail(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    provider = RouteFixtureProvider()
    app.dependency_overrides[get_analysis_provider] = lambda: provider
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            imported = await client.post(
                "/books", files={"file": ("chapters.pdf", make_two_chapter_pdf(), "application/pdf")}
            )
            book_id = imported.json()["id"]
            confirmed = await client.put(
                f"/books/{book_id}/chapters", json={"chapters": imported.json()["chapters"]}
            )
            chapter_id = confirmed.json()["chapters"][0]["id"]
            with sqlite3.connect(tmp_path / "book-learning.sqlite3") as connection:
                connection.execute(
                    "UPDATE chapters SET source_locator = ? WHERE id = ?",
                    ("OEBPS/chapter.xhtml#bubble", chapter_id),
                )
            created = await client.post(f"/books/{book_id}/analyses")
            repeated = await client.post(f"/books/{book_id}/analyses")
            overview = None
            for _ in range(50):
                overview = await client.get(f"/books/{book_id}/overview")
                if (
                    overview.json()["ready_chapter_count"] == 2
                    and overview.json()["core_question"] == "全书如何建立可信结论？"
                ):
                    break
                await asyncio.sleep(0.01)
            runs = await client.get(f"/books/{book_id}/analysis-runs")
            detail = await client.get(f"/books/{book_id}/chapters/{chapter_id}/analysis")
            retried = await client.post(f"/books/{book_id}/chapters/{chapter_id}/analysis/retry")
            for _ in range(50):
                retried_detail = await client.get(f"/books/{book_id}/chapters/{chapter_id}/analysis")
                if provider.generate_calls == 3 and retried_detail.json()["generation_status"] == "ready":
                    break
                await asyncio.sleep(0.01)
    finally:
        app.dependency_overrides.clear()

    assert created.status_code == 202
    assert repeated.status_code == 202
    assert provider.generate_calls == 3
    assert overview is not None
    assert overview.status_code == 200
    assert overview.json()["ready_chapter_count"] == 2
    assert overview.json()["chapter_count"] == 2
    assert overview.json()["core_question"] == "全书如何建立可信结论？"
    assert overview.json()["chapters"][0]["generation_status"] == "ready"
    assert runs.status_code == 200
    # The fixture is intentionally fast: the repeated request either joins the
    # active batch or starts an overview-only refresh after that batch finishes.
    # The explicit chapter retry below supplies the third chapter-level call.
    assert len(runs.json()) in {3, 4}
    assert runs.json()[0]["input_characters"] > 400
    assert runs.json()[0]["prompt_tokens"] is None
    assert runs.json()[-1]["chapter_id"] is None  # book-level run, not tied to a chapter
    assert detail.status_code == 200
    assert detail.json()["source_locator"] == "OEBPS/chapter.xhtml#bubble"
    assert detail.json()["core_ideas"][0]["sources"][0]["verification_status"] == "verified"
    assert detail.json()["core_ideas"][0]["sources"][0]["source_chapter_id"] == chapter_id
    assert detail.json()["core_ideas"][0]["sources"][0]["source_chapter_title"] == "第一章"
    assert detail.json()["core_ideas"][0]["sources"][0]["source_locator"] == "OEBPS/chapter.xhtml#bubble"
    assert retried.status_code == 200
    # The in-process fixture can complete before the response is serialized; both
    # states are valid because the retry has been accepted and is never pending.
    assert retried.json()["generation_status"] in {"generating", "ready"}
    assert retried_detail.json()["generation_status"] == "ready"


@pytest.mark.anyio
async def test_analysis_generation_requires_confirmed_chapters(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    app.dependency_overrides[get_analysis_provider] = lambda: RouteFixtureProvider()
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            imported = await client.post(
                "/books", files={"file": ("chapters.pdf", make_two_chapter_pdf(), "application/pdf")}
            )
            response = await client.post(f"/books/{imported.json()['id']}/analyses")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json() == {"detail": "章节尚未确认"}


@pytest.mark.anyio
async def test_analysis_start_returns_before_the_batch_finishes(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    provider = BlockingRouteProvider()
    app.dependency_overrides[get_analysis_provider] = lambda: provider
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            imported = await client.post(
                "/books", files={"file": ("chapters.pdf", make_two_chapter_pdf(), "application/pdf")}
            )
            book_id = imported.json()["id"]
            await client.put(f"/books/{book_id}/chapters", json={"chapters": imported.json()["chapters"]})

            starting = asyncio.create_task(client.post(f"/books/{book_id}/analyses"))
            await asyncio.to_thread(provider.started.wait, 1)
            started = await asyncio.wait_for(asyncio.shield(starting), timeout=0.1)
    finally:
        provider.release.set()
        if "starting" in locals() and not starting.done():
            await starting
        app.dependency_overrides.clear()

    assert started.status_code == 202


@pytest.mark.anyio
async def test_chapter_retry_returns_while_the_chapter_is_generating(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    provider = BlockingRouteProvider()
    app.dependency_overrides[get_analysis_provider] = lambda: provider
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            imported = await client.post(
                "/books", files={"file": ("chapters.pdf", make_two_chapter_pdf(), "application/pdf")}
            )
            book_id = imported.json()["id"]
            confirmed = await client.put(
                f"/books/{book_id}/chapters", json={"chapters": imported.json()["chapters"]}
            )
            chapter_id = confirmed.json()["chapters"][0]["id"]

            retrying = asyncio.create_task(
                client.post(f"/books/{book_id}/chapters/{chapter_id}/analysis/retry")
            )
            await asyncio.to_thread(provider.started.wait, 1)
            response = await asyncio.wait_for(asyncio.shield(retrying), timeout=0.1)
    finally:
        provider.release.set()
        if "retrying" in locals() and not retrying.done():
            await retrying
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["generation_status"] in {"pending", "generating"}
    assert response.json()["analysis_job"]["status"] in {"queued", "running"}


@pytest.mark.anyio
async def test_chapter_retry_returns_terminal_job_when_completion_is_immediate(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    provider = RouteFixtureProvider()
    app.dependency_overrides[get_analysis_provider] = lambda: provider

    def run_immediately(_book_id: str, operation) -> bool:
        operation()
        return True

    monkeypatch.setattr(analyses.analysis_jobs, "start", run_immediately)
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            imported = await client.post(
                "/books", files={"file": ("chapters.pdf", make_two_chapter_pdf(), "application/pdf")}
            )
            book_id = imported.json()["id"]
            confirmed = await client.put(
                f"/books/{book_id}/chapters", json={"chapters": imported.json()["chapters"]}
            )
            chapter_id = confirmed.json()["chapters"][0]["id"]
            response = await client.post(f"/books/{book_id}/chapters/{chapter_id}/analysis/retry")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["generation_status"] == "ready"
    assert response.json()["analysis_job"]["status"] == "succeeded"


@pytest.mark.anyio
async def test_job_admission_conflict_and_private_job_lookup(tmp_path, monkeypatch):
    from app.api.dependencies import resolve_product_user
    from app.services.storage import BookRepository
    from types import SimpleNamespace
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    provider = RouteFixtureProvider()
    app.dependency_overrides[get_analysis_provider] = lambda: provider
    submissions = []
    monkeypatch.setattr(analyses.analysis_jobs, "start", lambda key, operation: submissions.append(operation) or True)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            imported = await client.post("/books", files={"file": ("book.pdf", make_two_chapter_pdf(), "application/pdf")})
            book_id = imported.json()["id"]
            confirmed = await client.put(f"/books/{book_id}/chapters", json={"chapters": imported.json()["chapters"]})
            cid = confirmed.json()["chapters"][0]["id"]
            first = await client.post(f"/books/{book_id}/analyses")
            again = await client.post(f"/books/{book_id}/analyses")
            job_id = first.json()["analysis_job"]["id"]
            assert first.status_code == again.status_code == 202
            assert again.json()["analysis_job"]["id"] == job_id
            conflict = await client.post(f"/books/{book_id}/chapters/{cid}/analysis/retry")
            assert conflict.status_code == 409
            assert BookRepository(tmp_path / "book-learning.sqlite3").get_chapter_analysis(book_id, cid) is None
            assert len(submissions) == 1 and provider.generate_calls == 0
            assert (await client.get(f"/books/{book_id}/analysis-jobs/{job_id}")).status_code == 200
            assert (await client.get(f"/books/{book_id}/analysis-jobs/wrong")).status_code == 404
            app.dependency_overrides[resolve_product_user] = lambda: SimpleNamespace(id=999)
            assert (await client.get(f"/books/{book_id}/analysis-jobs/{job_id}")).status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_submission_failure_does_not_create_generating_chapter(tmp_path, monkeypatch):
    from app.services.storage import BookRepository
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    app.dependency_overrides[get_analysis_provider] = lambda: RouteFixtureProvider()
    def fail_submit(*args):
        raise RuntimeError("thread unavailable")
    monkeypatch.setattr(analyses.analysis_jobs, "start", fail_submit)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            imported = await client.post("/books", files={"file": ("book.pdf", make_two_chapter_pdf(), "application/pdf")})
            book_id = imported.json()["id"]
            confirmed = await client.put(f"/books/{book_id}/chapters", json={"chapters": imported.json()["chapters"]})
            cid = confirmed.json()["chapters"][0]["id"]
            response = await client.post(f"/books/{book_id}/chapters/{cid}/analysis/retry")
            assert response.status_code == 503
            assert BookRepository(tmp_path / "book-learning.sqlite3").get_chapter_analysis(book_id, cid) is None
            overview = await client.get(f"/books/{book_id}/overview")
            assert overview.json()["analysis_job"]["status"] == "failed"
    finally:
        app.dependency_overrides.clear()
