from hashlib import sha256
from pathlib import Path

import pytest

from app.services.analysis_generation import AnalysisGenerationService
from app.services.analysis_providers import ChapterAnalysisDraft, CoreIdeaDraft, EvidenceDraft
from app.services.chapter_confirmation import ConfirmedChapter
from app.services.storage import BookRepository, open_connection


TEXT = "作者用可回查的原文建立可信结论。" * 40


def repository(tmp_path):
    repo = BookRepository(tmp_path / "book-learning.sqlite3")
    repo.save_book_import(
        owner_id=1, book_id="book", filename="sample.pdf", sha256="digest",
        stored_path=tmp_path / "sample.pdf", status="awaiting_chapter_confirmation",
        diagnostics=[], pages=[TEXT, TEXT], chapters=[("第一章", 1, 1, TEXT), ("第二章", 2, 2, TEXT)],
    )
    repo.replace_confirmed_chapters("book", [ConfirmedChapter("第一章", 1, 1), ConfirmedChapter("第二章", 2, 2)])
    return repo, int(repo.list_chapters("book", confirmed=True)[0]["id"])


def draft():
    return ChapterAnalysisDraft(
        chapter_question="问题", one_sentence_conclusion="结论", short_summary="摘要",
        argument_chain=["旧版论证"], role_in_book="旧版定位", estimated_reading_minutes=3,
        core_ideas=[CoreIdeaDraft(
            title="思想", conclusion="结论", importance="重要", explanation="说明",
            reasoning_steps=["论证"], content_type="book_claim", confidence=.9,
            evidence=[EvidenceDraft(page=1, quote=TEXT[:30])],
        )],
    )


def test_legacy_overview_input_preserves_role_without_revalidating_statements(tmp_path):
    repo, cid = repository(tmp_path)
    d = draft()
    repo.save_chapter_analysis(book_id="book", chapter_id=cid, source_content_hash=sha256(TEXT.encode()).hexdigest(),
                               status="ready", draft=d, publishable_ideas=[(d.core_ideas[0], d.core_ideas[0].evidence)])
    inputs = repo.ready_chapter_analysis_drafts("book")
    assert inputs[0].role_in_book == "旧版定位"
    assert inputs[0].role_content_type == "legacy_summary"
    assert not hasattr(inputs[0], "core_ideas")


@pytest.mark.parametrize("with_role", [True, False])
def test_modern_overview_role_is_plain_text_or_empty(tmp_path, with_role):
    repo, cid = repository(tmp_path)
    d = draft()
    repo.save_chapter_analysis(
        book_id="book", chapter_id=cid, source_content_hash="hash", status="ready", draft=d,
        publishable_ideas=[(d.core_ideas[0], d.core_ideas[0].evidence)],
        publishable_statements=[("role_in_book", 0, d.role_in_book, [])] if with_role else [],
    )
    item = repo.ready_chapter_analysis_drafts("book")[0]
    assert item.role_in_book == ("旧版定位" if with_role else "")
    assert item.role_content_type == ("book_summary" if with_role else None)


@pytest.mark.parametrize("change", ["text", "title", "role", "removed", "related", "model", "genre"])
@pytest.mark.parametrize("fail", [False, True])
def test_changed_input_cannot_publish_success_or_failure(tmp_path, change, fail):
    repo, cid = repository(tmp_path)
    class Provider:
        def generate(self, chapter, context):
            with open_connection(repo.database_path) as connection:
                if change == "text":
                    connection.execute("UPDATE book_pages SET text='新版正文' WHERE book_id='book' AND page_number=1")
                elif change == "title":
                    connection.execute("UPDATE chapters SET title='新标题' WHERE id=?", (cid,))
                elif change == "role":
                    connection.execute("UPDATE chapters SET analysis_role='outline_only' WHERE id=?", (cid,))
                elif change == "removed":
                    connection.execute("UPDATE chapters SET removed=1 WHERE id=?", (cid,))
                elif change == "related":
                    connection.execute("UPDATE chapters SET title='关联章改变' WHERE book_id='book' AND id!=?", (cid,))
                elif change == "model":
                    connection.execute("INSERT INTO provider_settings VALUES ('openai', 'changed-model')")
                else:
                    connection.execute("UPDATE books SET genre='how_to' WHERE id='book'")
            if fail:
                raise RuntimeError("old task failed")
            return draft()
    AnalysisGenerationService(repo, Provider()).generate_chapter("book", cid)
    assert repo.get_chapter_analysis("book", cid)["generation_status"] == "stale"


def test_unchanged_confirmation_does_not_invalidate_snapshot(tmp_path):
    repo, cid = repository(tmp_path)
    class Provider:
        def generate(self, chapter, context):
            repo.replace_confirmed_chapters("book", [ConfirmedChapter("第一章", 1, 1), ConfirmedChapter("第二章", 2, 2)])
            return draft()
    AnalysisGenerationService(repo, Provider()).generate_chapter("book", cid)
    assert repo.get_chapter_analysis("book", cid)["generation_status"] == "ready"


def test_admission_deduplicates_and_conflicts_without_chapter_writes(tmp_path):
    from app.services.analysis_job_store import AnalysisJobStore, AnalysisJobConflict
    repo, cid = repository(tmp_path)
    store = AnalysisJobStore(repo.database_path)
    job, created = store.admit("book", "batch", [cid], "same")
    duplicate, created_again = store.admit("book", "batch", [cid], "same")
    assert created and not created_again and duplicate["id"] == job["id"]
    with pytest.raises(AnalysisJobConflict):
        store.admit("book", "chapter_retry", [cid], "different")
    assert repo.get_chapter_analysis("book", cid) is None


def test_recovery_is_explicit_idempotent_and_preserves_content_states(tmp_path):
    from app.services.analysis_job_store import AnalysisJobStore
    repo, cid = repository(tmp_path)
    store = AnalysisJobStore(repo.database_path)
    job, _ = store.admit("book", "batch", [cid], "same")
    repo.set_chapter_analysis_status(book_id="book", chapter_id=cid, status="generating", source_content_hash="hash")
    BookRepository(repo.database_path)
    assert store.get("book", job["id"])["status"] == "queued"
    store.recover_interrupted()
    store.recover_interrupted()
    assert store.get("book", job["id"])["status"] == "interrupted"
    assert repo.get_chapter_analysis("book", cid)["generation_status"] == "failed"


def test_overview_does_not_publish_if_selected_chapter_result_changes(tmp_path):
    from app.services.analysis_providers import BookOverviewDraft
    repo, cid = repository(tmp_path)
    class Provider:
        def generate(self, chapter, context):
            return draft()
        def generate_book_overview(self, chapters):
            with open_connection(repo.database_path) as connection:
                connection.execute("UPDATE chapter_analyses SET content_version=content_version+1 WHERE chapter_id=?", (cid,))
            return BookOverviewDraft(core_question="旧问题", one_sentence_summary="旧概览")
    service = AnalysisGenerationService(repo, Provider())
    service.generate_chapter("book", cid)
    service.generate_book_overview("book")
    assert repo.get_book_overview("book") is None


def test_old_job_failure_cannot_change_new_job_result(tmp_path):
    from app.services.analysis_job_store import AnalysisJobStore
    repo, cid = repository(tmp_path)
    store = AnalysisJobStore(repo.database_path)
    old, _ = store.admit("book", "chapter_retry", [cid], "old")
    store.start(old)
    class NewProvider:
        def generate(self, chapter, context):
            return draft()
    class OldProvider:
        def generate(self, chapter, context):
            store.finish(old["id"], "interrupted")
            new, _ = store.admit("book", "chapter_retry", [cid], "new")
            store.start(new)
            AnalysisGenerationService(repo, NewProvider()).generate_chapter("book", cid, job_id=new["id"])
            raise RuntimeError("old job failed late")
    AnalysisGenerationService(repo, OldProvider()).generate_chapter("book", cid, job_id=old["id"])
    assert repo.get_chapter_analysis("book", cid)["generation_status"] == "ready"


def test_overview_input_failure_is_recorded_without_destroying_chapters(tmp_path, monkeypatch):
    repo, cid = repository(tmp_path)
    class Provider:
        def generate(self, chapter, context):
            return draft()
    service = AnalysisGenerationService(repo, Provider())
    service.generate_chapter("book", cid)
    def unreadable(*args):
        raise ValueError("bad legacy row")
    monkeypatch.setattr(repo, "ready_chapter_analysis_drafts", unreadable)
    with pytest.raises(ValueError, match="bad legacy row"):
        service.generate_book_overview("book")
    assert repo.get_book_overview("book")["generation_status"] == "failed"
    assert repo.get_chapter_analysis("book", cid)["generation_status"] == "ready"
    assert repo.list_analysis_runs("book")[-1]["status"] == "failed"


def test_configuration_change_during_preparation_stops_old_provider(tmp_path):
    from app.services.analysis_job_store import AnalysisJobStore
    from app.services.analysis_generation import generate_chapter_batch
    from app.services.analysis_providers import GenreDecision
    from app.services.storage import ProviderMetadata
    repo, cid = repository(tmp_path)
    repo.save_provider_metadata(ProviderMetadata(provider="openai", model="old-model"))
    store = AnalysisJobStore(repo.database_path)
    job, _ = store.admit("book", "batch", [cid], "same")
    store.start(job)
    class Provider:
        model = "old-model"
        calls = 0
        def detect_genre(self, context, samples):
            repo.save_provider_metadata(ProviderMetadata(provider="openai", model="new-model"))
            return GenreDecision(genre="theory")
        def generate(self, chapter, context):
            self.calls += 1
            return draft()
    provider = Provider()
    generate_chapter_batch(AnalysisGenerationService(repo, provider), "book", [cid], job_id=job["id"])
    assert provider.calls == 0
    assert repo.get_book("book")["genre"] is None
    assert store.get("book", job["id"])["status"] == "superseded"


def test_switch_to_existing_provider_invalidates_publication(tmp_path):
    from app.services.storage import ProviderMetadata
    repo, cid = repository(tmp_path)
    repo.save_provider_metadata(ProviderMetadata(provider="openai", model="a"))
    repo.save_provider_metadata(ProviderMetadata(provider="deepseek", model="b"))
    class Provider:
        def generate(self, chapter, context):
            repo.save_provider_metadata(ProviderMetadata(provider="openai", model="a"))
            return draft()
    AnalysisGenerationService(repo, Provider()).generate_chapter("book", cid)
    assert repo.get_chapter_analysis("book", cid)["generation_status"] == "stale"


@pytest.mark.anyio
async def test_lifespan_recovers_interrupted_job_without_replaying_models(tmp_path, monkeypatch):
    from app.main import create_app
    from app.services.analysis_job_store import AnalysisJobStore
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    repo, cid = repository(tmp_path)
    other = int(repo.list_chapters("book", confirmed=True)[1]["id"])
    store = AnalysisJobStore(repo.database_path)
    job, _ = store.admit("book", "batch", [cid], "same")
    store.start(job)
    repo.set_chapter_analysis_status(book_id="book", chapter_id=cid, status="generating", source_content_hash="old")
    repo.set_chapter_analysis_status(book_id="book", chapter_id=other, status="ready", source_content_hash="ready")
    app = create_app()
    async with app.router.lifespan_context(app):
        assert store.get("book", job["id"])["status"] == "interrupted"
        assert repo.get_chapter_analysis("book", cid)["generation_status"] == "failed"
        assert repo.get_chapter_analysis("book", other)["generation_status"] == "ready"
    repo.set_chapter_analysis_status(book_id="book", chapter_id=cid, status="stale", source_content_hash="new")
    async with app.router.lifespan_context(app):
        assert repo.get_chapter_analysis("book", cid)["generation_status"] == "stale"
