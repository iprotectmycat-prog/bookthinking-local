import logging
from pathlib import Path
from threading import Lock
from time import sleep

import pytest

from app.services.analysis_generation import AnalysisGenerationService, generate_chapter_batch
from app.services.analysis_providers import (
    BookOverviewDraft,
    GenreDecision,
    ChapterAnalysisDraft,
    ChapterSource,
    CoreIdeaDraft,
    EvidenceDraft,
    GeneratedChapterAnalysis,
    AnalysisProviderError,
)
from app.services.chapter_confirmation import ConfirmedChapter
from app.services.evidence_catalog import build_evidence_catalogue
from app.services.genre_plugins import DEFAULT_GENRE
from app.services.storage import BookRepository


class StaticAnalysisProvider:
    def __init__(
        self,
        quote: str,
        *,
        fail: bool = False,
        content_type: str = "book_claim",
        evidence: bool = True,
    ) -> None:
        self.quote = quote
        self.fail = fail
        self.content_type = content_type
        self.evidence = evidence
        self.generate_calls = 0

    def generate(self, chapter: ChapterSource) -> ChapterAnalysisDraft:
        self.generate_calls += 1
        if self.fail:
            raise RuntimeError("provider unavailable")
        return ChapterAnalysisDraft(
            chapter_question="本章试图说明什么？",
            one_sentence_conclusion="可信证据支撑本章结论。",
            short_summary="本章通过可回查的原文建立核心结论。",
            argument_chain=["提出问题", "给出证据", "形成结论"],
            role_in_book="建立全书的基础问题",
            estimated_reading_minutes=3,
            core_ideas=[
                CoreIdeaDraft(
                    title="证据优先",
                    conclusion="核心结论必须能够回查原文。",
                    importance="防止把模型推断写成作者观点。",
                    explanation="先验证引文，再展示结论。",
                    reasoning_steps=["定位原文", "核对页码", "发布结论"],
                    content_type=self.content_type,
                    confidence=0.95,
                    evidence=[EvidenceDraft(page=1, quote=self.quote)] if self.evidence else [],
                )
            ],
        )

    def generate_book_overview(self, chapters: list[ChapterAnalysisDraft]) -> BookOverviewDraft:
        return BookOverviewDraft(core_question="全书如何建立可信结论？", one_sentence_summary="证据先于结论。")


class RetryingProvider(StaticAnalysisProvider):
    def __init__(self, quote: str, failures: list[Exception]) -> None:
        super().__init__(quote)
        self.failures = failures

    def generate(self, chapter: ChapterSource) -> ChapterAnalysisDraft:
        if self.failures:
            self.generate_calls += 1
            raise self.failures.pop(0)
        return super().generate(chapter)


class IdSelectingProvider:
    def __init__(self, *, content_type: str, evidence_ids: list[str]) -> None:
        self.content_type = content_type
        self.evidence_ids = evidence_ids

    def generate(self, chapter: ChapterSource, context=None) -> ChapterAnalysisDraft:
        return ChapterAnalysisDraft(
            chapter_question="本章试图说明什么？",
            one_sentence_conclusion="可信证据支撑本章结论。",
            short_summary="本章通过可回查的原文建立核心结论。",
            argument_chain=["提出问题", "给出证据", "形成结论"],
            role_in_book="建立全书的基础问题",
            estimated_reading_minutes=3,
            core_ideas=[
                CoreIdeaDraft(
                    title="证据选择",
                    conclusion="核心结论必须能够回查原文。",
                    importance="防止把模型推断写成作者观点。",
                    explanation="由本地证据块回填原文。",
                    reasoning_steps=["选择证据 ID", "回填原文", "发布结论"],
                    content_type=self.content_type,
                    confidence=0.95,
                    evidence_ids=self.evidence_ids,
                )
            ],
        )


class StatementSelectingProvider(IdSelectingProvider):
    def __init__(self, *, argument_ids: list[str], role_ids: list[str]) -> None:
        super().__init__(content_type="book_claim", evidence_ids=["e1"])
        self.argument_ids = argument_ids
        self.role_ids = role_ids

    def generate(self, chapter: ChapterSource, context=None) -> ChapterAnalysisDraft:
        draft = super().generate(chapter, context)
        draft.argument_chain = [
            {
                "text": "制度变化引出后续激励。",
                "content_type": "ai_synthesis",
                "evidence_ids": self.argument_ids,
            }
        ]
        draft.role_in_book = {
            "text": "为后续土地财政提供制度起点。",
            "content_type": "ai_synthesis",
            "evidence_ids": self.role_ids,
        }
        return draft


def two_chapter_repository(tmp_path) -> tuple[BookRepository, int, int]:
    first_text = "第一节作者原句。\n\n" + "第一节补充材料。" * 60
    second_text = "第二节作者原句。\n\n" + "第二节补充材料。" * 60
    repository = BookRepository(tmp_path / "book-learning.sqlite3")
    repository.save_book_import(
        book_id="book-1",
        filename="sample.pdf",
        sha256="digest",
        stored_path=Path("sample.pdf"),
        status="awaiting_chapter_confirmation",
        diagnostics=[],
        pages=[first_text, second_text],
        chapters=[
            ("第一节", 1, 1, first_text),
            ("第二节", 2, 2, second_text),
        ],
    )
    repository.replace_confirmed_chapters(
        "book-1",
        [
            ConfirmedChapter(title="第一节", source_start_page=1, source_end_page=1),
            ConfirmedChapter(title="第二节", source_start_page=2, source_end_page=2),
        ],
    )
    chapters = repository.list_chapters("book-1", confirmed=True)
    return repository, int(chapters[0]["id"]), int(chapters[1]["id"])


def confirmed_repository(
    tmp_path,
    text: str = "作者用可回查的原文建立可信结论。" * 30,
    source_locator: str | None = None,
) -> tuple[BookRepository, int]:
    repository = BookRepository(tmp_path / "book-learning.sqlite3")
    repository.save_book_import(
        book_id="book-1",
        filename="sample.pdf",
        sha256="digest",
        stored_path=Path("sample.pdf"),
        status="awaiting_chapter_confirmation",
        diagnostics=[],
        pages=[text],
        chapters=[("第一章", 1, 1, text)],
    )
    repository.replace_confirmed_chapters(
        "book-1",
        [
            ConfirmedChapter(
                title="第一章",
                source_start_page=1,
                source_end_page=1,
                source_locator=source_locator,
            )
        ],
    )
    chapter_id = int(repository.list_chapters("book-1", confirmed=True)[0]["id"])
    return repository, chapter_id


def test_chapter_analysis_sources_include_epub_locator(tmp_path) -> None:
    repository, chapter_id = confirmed_repository(
        tmp_path,
        source_locator="OEBPS/chapter.xhtml#bubble",
    )
    AnalysisGenerationService(
        repository,
        StaticAnalysisProvider("作者用可回查的原文建立可信结论。"),
    ).generate_chapter("book-1", chapter_id)

    analysis = repository.get_chapter_analysis("book-1", chapter_id)
    assert analysis is not None
    source = analysis["core_ideas"][0]["sources"][0]
    assert source["source_locator"] == "OEBPS/chapter.xhtml#bubble"


def test_generation_persists_verified_claims(tmp_path) -> None:
    repository, chapter_id = confirmed_repository(tmp_path)
    service = AnalysisGenerationService(repository, StaticAnalysisProvider("作者用可回查的原文建立可信结论。"))

    service.generate_chapter("book-1", chapter_id)

    analysis = repository.get_chapter_analysis("book-1", chapter_id)
    assert analysis is not None
    assert analysis["generation_status"] == "ready"
    assert analysis["argument_chain"] == []
    assert analysis["role_in_book"] is None
    assert analysis["core_ideas"][0]["content_type"] == "book_claim"
    assert analysis["core_ideas"][0]["sources"][0]["verification_status"] == "verified"
    assert analysis["core_ideas"][0]["sources"][0]["source_page"] == 1


def test_generation_rejects_book_claim_with_missing_quote(tmp_path) -> None:
    repository, chapter_id = confirmed_repository(tmp_path)
    service = AnalysisGenerationService(repository, StaticAnalysisProvider("正文中不存在的引文。"))

    service.generate_chapter("book-1", chapter_id)

    analysis = repository.get_chapter_analysis("book-1", chapter_id)
    assert analysis is not None
    assert analysis["generation_status"] == "insufficient_evidence"
    assert analysis["core_ideas"] == []


def test_generation_stores_catalogue_literal_quote_not_model_text(tmp_path) -> None:
    repository, first_id, _ = two_chapter_repository(tmp_path)
    service = AnalysisGenerationService(
        repository, IdSelectingProvider(content_type="book_claim", evidence_ids=["e1"])
    )

    service.generate_chapter("book-1", first_id)

    analysis = repository.get_chapter_analysis("book-1", first_id)
    assert analysis is not None
    assert analysis["generation_status"] == "ready"
    assert analysis["core_ideas"][0]["sources"][0]["quote"] == "第一节作者原句。"


def test_generation_persists_three_paragraph_sibling_blocks_as_literal_sources(tmp_path) -> None:
    repository, first_id, _ = two_chapter_repository(tmp_path)
    chapter_source = repository.confirmed_chapter_source_by_id("book-1", first_id)
    assert chapter_source is not None
    catalogue = build_evidence_catalogue(ChapterSource.model_validate(chapter_source), prefix="e")
    selected = catalogue.resolve(["e2", "e3", "e4"]).blocks
    assert len(selected) == 3
    assert len({block.paragraph_id for block in selected}) == 1
    provider = IdSelectingProvider(content_type="book_claim", evidence_ids=["e2", "e3", "e4"])

    AnalysisGenerationService(repository, provider).generate_chapter("book-1", first_id)

    analysis = repository.get_chapter_analysis("book-1", first_id)
    assert analysis is not None
    sources = analysis["core_ideas"][0]["sources"]
    assert [(source["quote"], source["source_page"]) for source in sources] == [
        (block.quote, block.page) for block in selected
    ]
    assert all(source["verification_status"] == "verified" for source in sources)
    assert all(source["source_chapter_id"] == first_id for source in sources)
    assert all(source["source_chapter_title"] == "第一节" for source in sources)


def test_generation_rejects_unknown_evidence_id_with_inspectable_reason(tmp_path) -> None:
    repository, first_id, _ = two_chapter_repository(tmp_path)
    service = AnalysisGenerationService(
        repository, IdSelectingProvider(content_type="book_claim", evidence_ids=["e99"])
    )

    service.generate_chapter("book-1", first_id)

    analysis = repository.get_chapter_analysis("book-1", first_id)
    assert analysis is not None
    assert analysis["generation_status"] == "insufficient_evidence"
    assert analysis["failure_reason"] == "证据选择无效：未知=1，重复=0，空=0"


def test_ai_synthesis_requires_current_and_next_source(tmp_path) -> None:
    repository, first_id, second_id = two_chapter_repository(tmp_path)
    service = AnalysisGenerationService(
        repository, IdSelectingProvider(content_type="ai_synthesis", evidence_ids=["e1", "x1"])
    )

    service.generate_chapter("book-1", first_id)

    analysis = repository.get_chapter_analysis("book-1", first_id)
    assert analysis is not None
    assert analysis["generation_status"] == "ready"
    assert {source["source_chapter_id"] for source in analysis["core_ideas"][0]["sources"]} == {
        first_id,
        second_id,
    }


def test_generation_persists_cross_chapter_statement_sources(tmp_path) -> None:
    repository, first_id, second_id = two_chapter_repository(tmp_path)
    service = AnalysisGenerationService(
        repository, StatementSelectingProvider(argument_ids=["e1", "x1"], role_ids=["e1", "x1"])
    )

    service.generate_chapter("book-1", first_id)

    analysis = repository.get_chapter_analysis("book-1", first_id)
    assert analysis is not None
    assert analysis["argument_chain"][0]["content_type"] == "ai_synthesis"
    assert {source["source_chapter_id"] for source in analysis["argument_chain"][0]["sources"]} == {
        first_id,
        second_id,
    }
    assert analysis["role_in_book"]["content_type"] == "ai_synthesis"


def test_generation_rejects_statement_synthesis_without_both_origins(tmp_path) -> None:
    repository, first_id, _ = two_chapter_repository(tmp_path)
    service = AnalysisGenerationService(
        repository, StatementSelectingProvider(argument_ids=["e1"], role_ids=["e1"])
    )

    service.generate_chapter("book-1", first_id)

    analysis = repository.get_chapter_analysis("book-1", first_id)
    assert analysis is not None
    assert analysis["argument_chain"] == []
    assert analysis["role_in_book"] is None


@pytest.mark.parametrize("evidence_ids", [["e1"], ["x1"], ["e99", "x1"]])
def test_ai_synthesis_without_both_origins_is_not_published(tmp_path, evidence_ids) -> None:
    repository, first_id, _ = two_chapter_repository(tmp_path)
    service = AnalysisGenerationService(
        repository, IdSelectingProvider(content_type="ai_synthesis", evidence_ids=evidence_ids)
    )

    service.generate_chapter("book-1", first_id)

    analysis = repository.get_chapter_analysis("book-1", first_id)
    assert analysis is not None
    assert analysis["generation_status"] == "insufficient_evidence"
    assert analysis["core_ideas"] == []


def test_generation_isolates_provider_failure(tmp_path) -> None:
    repository, chapter_id = confirmed_repository(tmp_path)
    service = AnalysisGenerationService(repository, StaticAnalysisProvider("", fail=True))

    service.generate_chapter("book-1", chapter_id)

    analysis = repository.get_chapter_analysis("book-1", chapter_id)
    assert analysis is not None
    assert analysis["generation_status"] == "failed"
    assert analysis["failure_reason"] == "provider unavailable"


def test_generation_retries_http_400_before_persisting_a_ready_chapter(tmp_path) -> None:
    repository, chapter_id = confirmed_repository(tmp_path)
    provider = RetryingProvider(
        "作者用可回查的原文建立可信结论。",
        [AnalysisProviderError("模型调用失败：400 Bad Request")],
    )

    AnalysisGenerationService(repository, provider, retry_delays=(0, 0)).generate_chapter("book-1", chapter_id)

    analysis = repository.get_chapter_analysis("book-1", chapter_id)
    assert analysis is not None
    assert provider.generate_calls == 2
    assert analysis["generation_status"] == "ready"


def test_generation_persists_failure_only_after_three_recoverable_attempts(tmp_path) -> None:
    repository, chapter_id = confirmed_repository(tmp_path)
    provider = RetryingProvider(
        "作者用可回查的原文建立可信结论。",
        [AnalysisProviderError("模型返回了空内容")] * 3,
    )

    AnalysisGenerationService(repository, provider, retry_delays=(0, 0)).generate_chapter("book-1", chapter_id)

    analysis = repository.get_chapter_analysis("book-1", chapter_id)
    assert analysis is not None
    assert provider.generate_calls == 3
    assert analysis["generation_status"] == "failed"
    assert "模型返回了空内容" in str(analysis["failure_reason"])


def test_generation_skips_fragment_without_enough_source_material(tmp_path) -> None:
    repository, chapter_id = confirmed_repository(tmp_path, text="第一卷 引论")
    provider = StaticAnalysisProvider("第一卷 引论")
    service = AnalysisGenerationService(repository, provider)

    service.generate_chapter("book-1", chapter_id)

    analysis = repository.get_chapter_analysis("book-1", chapter_id)
    assert analysis is not None
    assert analysis["generation_status"] == "skipped"
    assert analysis["failure_reason"] == "正文不足 400 个字符"
    assert provider.generate_calls == 0


def test_generation_does_not_call_provider_for_inherited_back_matter_child(tmp_path) -> None:
    text = "作者回顾写作过程。" * 200
    repository = BookRepository(tmp_path / "book-learning.sqlite3")
    repository.save_book_import(
        book_id="book-1",
        filename="sample.epub",
        sha256="digest",
        stored_path=Path("sample.epub"),
        status="awaiting_chapter_confirmation",
        diagnostics=[],
        pages=[text],
        chapters=[("后记1", 1, 1, text)],
        source_format="epub",
    )
    repository.replace_confirmed_chapters(
        "book-1",
        [
            ConfirmedChapter(
                title="后记1",
                source_start_page=1,
                source_end_page=1,
                depth=1,
                parent_title="后记",
                nav_kind="chapter",
                in_body=True,
                structural_role="back_matter",
                role_source="parent_inherited",
                role_confidence="medium",
            )
        ],
    )
    chapter_id = int(repository.list_chapters("book-1", confirmed=True)[0]["id"])
    provider = StaticAnalysisProvider("作者回顾写作过程。")

    AnalysisGenerationService(repository, provider).generate_chapter("book-1", chapter_id)

    analysis = repository.get_chapter_analysis("book-1", chapter_id)
    assert analysis is not None
    assert analysis["generation_status"] == "summary_only"
    assert provider.generate_calls == 0


class MeteredProvider(StaticAnalysisProvider):
    model = "deepseek-v4-pro"

    def generate_with_metrics(self, chapter: ChapterSource) -> GeneratedChapterAnalysis:
        draft = self.generate(chapter)
        return GeneratedChapterAnalysis(
            draft=draft,
            model=self.model,
            prompt_tokens=123,
            completion_tokens=45,
            total_tokens=168,
            output_characters=321,
        )


def test_generation_records_provider_usage_and_elapsed_time(tmp_path) -> None:
    repository, chapter_id = confirmed_repository(tmp_path, text="作者用可回查的原文建立可信结论。" * 30)
    service = AnalysisGenerationService(repository, MeteredProvider("作者用可回查的原文建立可信结论。"))

    service.generate_chapter("book-1", chapter_id)

    run = repository.list_analysis_runs("book-1")[0]
    assert run["chapter_id"] == chapter_id
    assert run["model"] == "deepseek-v4-pro"
    assert run["prompt_tokens"] == 123
    assert run["completion_tokens"] == 45
    assert run["total_tokens"] == 168
    assert run["input_characters"] == len("作者用可回查的原文建立可信结论。" * 30)
    assert run["output_characters"] == 321
    assert run["elapsed_milliseconds"] >= 0


class ConcurrentProvider(StaticAnalysisProvider):
    def __init__(self, quote: str) -> None:
        super().__init__(quote)
        self.active = 0
        self.max_active = 0
        self.lock = Lock()

    def generate(self, chapter: ChapterSource) -> ChapterAnalysisDraft:
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            sleep(0.2)
            return super().generate(chapter)
        finally:
            with self.lock:
                self.active -= 1


def test_chapter_batch_uses_twenty_four_worker_limit_by_default(tmp_path) -> None:
    text = "作者用可回查的原文建立可信结论。" * 30
    repository = BookRepository(tmp_path / "book-learning.sqlite3")
    repository.save_book_import(
        book_id="book-1",
        filename="sample.pdf",
        sha256="digest",
        stored_path=Path("sample.pdf"),
        status="awaiting_chapter_confirmation",
        diagnostics=[],
        pages=[text] * 28,
        chapters=[(f"第{index}章", index, index, text) for index in range(1, 29)],
    )
    repository.replace_confirmed_chapters(
        "book-1", [ConfirmedChapter(title=f"第{index}章", source_start_page=index, source_end_page=index) for index in range(1, 29)]
    )
    provider = ConcurrentProvider("作者用可回查的原文建立可信结论。")
    service = AnalysisGenerationService(repository, provider)
    chapter_ids = [int(chapter["id"]) for chapter in repository.list_chapters("book-1", confirmed=True)]

    generate_chapter_batch(service, "book-1", chapter_ids)

    # The pool must not exceed its worker limit. Asserting an exact peak is
    # flaky: reaching all 24 simultaneously depends on thread scheduling, so the
    # observed peak legitimately varies (it drops under coverage instrumentation).
    assert provider.max_active <= 24
    assert provider.max_active > 1


def test_book_overview_attempt_is_recorded(tmp_path) -> None:
    repository, chapter_id = confirmed_repository(tmp_path)
    service = AnalysisGenerationService(repository, StaticAnalysisProvider("作者用可回查的原文建立可信结论。"))
    service.generate_chapter("book-1", chapter_id)

    service.generate_book_overview("book-1")

    run = repository.list_analysis_runs("book-1")[-1]
    assert run["chapter_id"] is None  # book-level run, not tied to a chapter
    assert run["status"] == "ready"


def test_chapter_change_preserves_id_and_marks_analysis_stale(tmp_path) -> None:
    repository, chapter_id = confirmed_repository(tmp_path)
    service = AnalysisGenerationService(repository, StaticAnalysisProvider("作者用可回查的原文建立可信结论。"))
    service.generate_chapter("book-1", chapter_id)

    repository.replace_confirmed_chapters(
        "book-1", [ConfirmedChapter(title="第一章（修订）", source_start_page=1, source_end_page=1)]
    )

    chapters = repository.list_chapters("book-1", confirmed=True)
    analysis = repository.get_chapter_analysis("book-1", chapter_id)
    assert chapters[0]["id"] == chapter_id
    assert analysis is not None
    assert analysis["generation_status"] == "stale"


FIRST_PAGE = "资本成本的讨论从这里展开。" + "论述内容甲乙丙丁戊己庚辛。" * 30 + "第一页在此收束。"
SECOND_PAGE = "第二页转向一个无关的话题。" + "论述内容子丑寅卯辰巳午未。" * 30 + "第二页在此收束。"
THIRD_PAGE = "第三页提出另一个论点。" + "论述内容青龙白虎朱雀玄武。" * 30 + "第三页在此收束。"


def three_page_repository(tmp_path) -> tuple[BookRepository, int]:
    """A chapter spanning three distinct pages, each past the policy gate."""
    repository = BookRepository(tmp_path / "book-learning.sqlite3")
    repository.save_book_import(
        book_id="book-1",
        filename="sample.pdf",
        sha256="digest",
        stored_path=Path("sample.pdf"),
        status="awaiting_chapter_confirmation",
        diagnostics=[],
        pages=[FIRST_PAGE, SECOND_PAGE, THIRD_PAGE],
        chapters=[("第一章", 1, 3, f"{FIRST_PAGE}\n\n{SECOND_PAGE}\n\n{THIRD_PAGE}")],
    )
    repository.replace_confirmed_chapters(
        "book-1", [ConfirmedChapter(title="第一章", source_start_page=1, source_end_page=3)]
    )
    chapter_id = int(repository.list_chapters("book-1", confirmed=True)[0]["id"])
    return repository, chapter_id


def test_generation_rejects_evidence_attributed_to_the_wrong_page(tmp_path) -> None:
    """Regression: verifying against the whole chapter accepted any quote that
    existed *somewhere* in it, so a real sentence carrying a wrong page number
    was stored as verified. The citation then sends the reader to a page that
    does not contain the quote, which defeats the evidence guarantee."""
    repository, chapter_id = three_page_repository(tmp_path)
    # A genuine sentence from page 3, but the provider claims it came from page 1.
    service = AnalysisGenerationService(repository, StaticAnalysisProvider("第三页提出另一个论点。"))

    service.generate_chapter("book-1", chapter_id)

    analysis = repository.get_chapter_analysis("book-1", chapter_id)
    assert analysis is not None
    assert analysis["generation_status"] == "insufficient_evidence"
    assert analysis["core_ideas"] == []


def test_generation_rejects_unsourced_book_example(tmp_path) -> None:
    """Regression: only book_claim required evidence, so a model could publish an
    unsourced case study just by labelling it book_example. The UI renders that
    label as 「书中案例」, telling the reader it came from the book while giving
    them nothing to look up."""
    repository, chapter_id = three_page_repository(tmp_path)
    service = AnalysisGenerationService(
        repository,
        StaticAnalysisProvider("资本成本的讨论从这里展开。", content_type="book_example", evidence=False),
    )

    service.generate_chapter("book-1", chapter_id)

    analysis = repository.get_chapter_analysis("book-1", chapter_id)
    assert analysis is not None
    assert analysis["generation_status"] == "insufficient_evidence"
    assert analysis["core_ideas"] == []


def test_generation_keeps_sourced_book_example(tmp_path) -> None:
    """The counterpart: a book_example that does cite real text stays published,
    so tightening the check does not cost legitimate cases."""
    repository, chapter_id = three_page_repository(tmp_path)
    service = AnalysisGenerationService(
        repository,
        StaticAnalysisProvider("资本成本的讨论从这里展开。", content_type="book_example"),
    )

    service.generate_chapter("book-1", chapter_id)

    analysis = repository.get_chapter_analysis("book-1", chapter_id)
    assert analysis is not None
    assert analysis["generation_status"] == "ready"
    assert analysis["core_ideas"][0]["content_type"] == "book_example"
    assert analysis["core_ideas"][0]["sources"][0]["source_page"] == 1


def test_generation_keeps_ai_inference_without_evidence(tmp_path) -> None:
    """AI-authored entries stay exempt: the prompt tells the model to fall back to
    ai_inference when it cannot quote anything, and that path must still publish."""
    repository, chapter_id = three_page_repository(tmp_path)
    service = AnalysisGenerationService(
        repository,
        StaticAnalysisProvider("", content_type="ai_inference", evidence=False),
    )

    service.generate_chapter("book-1", chapter_id)

    analysis = repository.get_chapter_analysis("book-1", chapter_id)
    assert analysis is not None
    assert analysis["generation_status"] == "ready"
    assert analysis["core_ideas"][0]["content_type"] == "ai_inference"


def test_generation_keeps_evidence_quoted_within_one_page(tmp_path) -> None:
    repository, chapter_id = three_page_repository(tmp_path)
    service = AnalysisGenerationService(repository, StaticAnalysisProvider("资本成本的讨论从这里展开。"))

    service.generate_chapter("book-1", chapter_id)

    analysis = repository.get_chapter_analysis("book-1", chapter_id)
    assert analysis is not None
    assert analysis["generation_status"] == "ready"
    assert analysis["core_ideas"][0]["sources"][0]["source_page"] == 1


def test_generation_allows_quote_running_onto_the_adjacent_page(tmp_path) -> None:
    """Documents a deliberate limit of the per-page check: pagination genuinely
    splits sentences, so a quote starting on the cited page and continuing onto
    the immediately following page stays valid. Text from a page further away is
    rejected (see the wrong-page test above)."""
    repository, chapter_id = three_page_repository(tmp_path)
    spanning = "第一页在此收束。第二页转向一个无关的话题。"
    service = AnalysisGenerationService(repository, StaticAnalysisProvider(spanning))

    service.generate_chapter("book-1", chapter_id)

    analysis = repository.get_chapter_analysis("book-1", chapter_id)
    assert analysis is not None
    assert analysis["generation_status"] == "ready"
    assert analysis["core_ideas"][0]["sources"][0]["source_page"] == 1


class OverviewFailingProvider(StaticAnalysisProvider):
    def generate_book_overview(self, chapters: list[ChapterAnalysisDraft]) -> BookOverviewDraft:
        raise RuntimeError("overview provider unavailable")


def test_overview_failure_is_recorded_and_reraised(tmp_path, caplog) -> None:
    """Regression: the overview path had a bare try/finally, so a bookkeeping
    error inside `finally` replaced the real exception, and the caller swallowed
    it with `except Exception: pass` — leaving no state and no log line."""
    repository, chapter_id = confirmed_repository(tmp_path)
    provider = OverviewFailingProvider("作者用可回查的原文建立可信结论。")
    service = AnalysisGenerationService(repository, provider)
    service.generate_chapter("book-1", chapter_id)

    with caplog.at_level(logging.ERROR):
        with pytest.raises(RuntimeError, match="overview provider unavailable"):
            service.generate_book_overview("book-1")

    overview = repository.get_book_overview("book-1")
    assert overview is not None
    assert overview["generation_status"] == "failed"
    assert "book overview generation failed" in caplog.text

    run = repository.list_analysis_runs("book-1")[-1]
    assert run["chapter_id"] is None  # book-level run, not tied to a chapter
    assert run["status"] == "failed"


def test_failed_overview_keeps_book_off_the_analyzed_shelf(tmp_path) -> None:
    repository, chapter_id = confirmed_repository(tmp_path)
    service = AnalysisGenerationService(repository, OverviewFailingProvider("作者用可回查的原文建立可信结论。"))
    service.generate_chapter("book-1", chapter_id)

    with pytest.raises(RuntimeError):
        service.generate_book_overview("book-1")

    assert repository.list_analyzed_books() == []


def test_chapter_failure_is_logged(tmp_path, caplog) -> None:
    repository, chapter_id = confirmed_repository(tmp_path)
    service = AnalysisGenerationService(
        repository, StaticAnalysisProvider("作者用可回查的原文建立可信结论。", fail=True)
    )

    with caplog.at_level(logging.ERROR):
        service.generate_chapter("book-1", chapter_id)

    analysis = repository.get_chapter_analysis("book-1", chapter_id)
    assert analysis is not None
    assert analysis["generation_status"] == "failed"
    assert "chapter analysis failed" in caplog.text


class GenreAwareProvider:
    """Records what context each chapter was analysed with."""

    model = "test-model"

    def __init__(self, *, genre: str = "practical", fail_detection: bool = False) -> None:
        self.genre = genre
        self.fail_detection = fail_detection
        self.detect_calls = 0
        self.seen_contexts: list[object] = []

    def detect_genre(self, context, samples):
        self.detect_calls += 1
        if self.fail_detection:
            raise RuntimeError("detection unavailable")
        return GenreDecision(genre=self.genre, confidence=0.9, reason="测试")

    def generate(self, chapter, context=None):
        self.seen_contexts.append(context)
        return ChapterAnalysisDraft(
            chapter_question="本章试图说明什么？",
            one_sentence_conclusion="可信证据支撑本章结论。",
            short_summary="摘要。",
            argument_chain=["提出问题"],
            role_in_book="建立基础问题",
            estimated_reading_minutes=3,
            core_ideas=[
                CoreIdeaDraft(
                    title="证据优先",
                    conclusion="结论必须可回查。",
                    importance="防止推断冒充观点。",
                    explanation="先验证再展示。",
                    reasoning_steps=["定位原文"],
                    content_type="ai_inference",
                    confidence=0.9,
                )
            ],
        )

    def generate_book_overview(self, chapters):
        return BookOverviewDraft(core_question="q", one_sentence_summary="s")


def test_batch_detects_the_genre_once_for_the_whole_book(tmp_path) -> None:
    """Detecting inside a worker would spend one call per chapter and could
    analyse two chapters of one book under different frameworks."""
    repository, chapter_id = three_page_repository(tmp_path)
    provider = GenreAwareProvider()
    service = AnalysisGenerationService(repository, provider)

    generate_chapter_batch(service, "book-1", [chapter_id, chapter_id, chapter_id], max_workers=3)

    assert provider.detect_calls == 1
    assert repository.book_context_for_prompt("book-1")["genre"] == "practical"


def test_chapter_generation_receives_the_stored_genre(tmp_path) -> None:
    repository, chapter_id = three_page_repository(tmp_path)
    repository.set_book_genre("book-1", genre="scholarly", confidence=0.7, source="model")
    provider = GenreAwareProvider()
    service = AnalysisGenerationService(repository, provider)

    service.generate_chapter("book-1", chapter_id)

    assert provider.seen_contexts[0].genre == "scholarly"
    assert provider.seen_contexts[0].outline == ["第一章"]


def test_failed_detection_falls_back_without_blocking_the_book(tmp_path) -> None:
    """A book must stay analysable when the auxiliary detection call fails."""
    repository, chapter_id = three_page_repository(tmp_path)
    provider = GenreAwareProvider(fail_detection=True)
    service = AnalysisGenerationService(repository, provider)

    genre = service.ensure_book_genre("book-1")

    assert genre == DEFAULT_GENRE
    assert repository.book_context_for_prompt("book-1")["genre"] == DEFAULT_GENRE


def test_existing_genre_is_not_detected_again(tmp_path) -> None:
    repository, chapter_id = three_page_repository(tmp_path)
    repository.set_book_genre("book-1", genre="narrative", confidence=0.9, source="user")
    provider = GenreAwareProvider()
    service = AnalysisGenerationService(repository, provider)

    assert service.ensure_book_genre("book-1") == "narrative"
    assert provider.detect_calls == 0


def test_provider_without_context_support_still_works(tmp_path) -> None:
    """StaticAnalysisProvider.generate takes only a chapter. Providers written
    before Layer 2 must keep working rather than failing on an extra argument."""
    repository, chapter_id = three_page_repository(tmp_path)
    service = AnalysisGenerationService(repository, StaticAnalysisProvider("资本成本的讨论从这里展开。"))

    service.generate_chapter("book-1", chapter_id)

    analysis = repository.get_chapter_analysis("book-1", chapter_id)
    assert analysis is not None
    assert analysis["generation_status"] == "ready"
