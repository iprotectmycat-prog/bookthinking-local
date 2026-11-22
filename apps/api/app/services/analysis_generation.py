import logging
import re
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from time import perf_counter, sleep

from app.services.analysis_inputs import AnalysisInputSnapshot
from app.services.analysis_policy import classify_chapter_source
from app.services.analysis_providers import (
    AnalysisProvider,
    AttributedStatementDraft,
    BookContext,
    BookReadingContext,
    ChapterAnalysisDraft,
    ChapterReading,
    ChapterSource,
    EvidenceDraft,
    GeneratedBookOverview,
    GeneratedChapterAnalysis,
    AnalysisProviderError,
    call_with_optional_context,
)
from app.services.evidence_catalog import EvidenceCatalogue, build_evidence_catalogue
from app.services.genre_plugins import DEFAULT_GENRE
from app.services.skill_analysis import PROTOCOL
from app.services.source_verifier import SourceVerifier
from app.services.storage import BookRepository


logger = logging.getLogger(__name__)

# Content types that claim to come from the book itself, and therefore must be
# backed by a quote the reader can look up. book_example was previously exempt,
# so a model could publish an unsourced "case from the book" simply by choosing
# that label — the one thing the evidence-first design exists to prevent.
SOURCED_CONTENT_TYPES = frozenset({"book_claim", "book_example"})
AI_SYNTHESIS_CONTENT_TYPE = "ai_synthesis"
RETRY_DELAYS_SECONDS = (0.5, 1.0)


class AnalysisGenerationService:
    def __init__(
        self,
        repository: BookRepository,
        provider: AnalysisProvider,
        *,
        retry_delays: tuple[float, ...] = RETRY_DELAYS_SECONDS,
    ) -> None:
        self.repository = repository
        self.provider = provider
        self.retry_delays = retry_delays

    def generate_chapter(
        self, book_id: str, chapter_id: int, *, job_id: str | None = None,
        book_reading: tuple[AnalysisInputSnapshot, BookReadingContext | None] | None = None,
        chapter_reading: ChapterReading | None = None,
        previous: tuple[ChapterSource, ChapterReading] | None = None,
    ) -> None:
        def read_input():
            source = self.repository.confirmed_chapter_source_by_id(book_id, chapter_id)
            if source is None:
                raise ValueError("章节不存在")
            context, following = self._analysis_context(book_id, ChapterSource(**source))
            related = [following] if following is not None else []
            if book_reading:
                context.reading_context = book_reading[1]
                context.chapter_reading = chapter_reading
            if previous:
                preceding, reading = previous
                related.append(preceding)
                brief = reading.brief
                context.previous_chapter_brief = {
                    "chapter_id": preceding.id, "title": preceding.title,
                    **brief.model_dump(exclude={"evidence_ids"}),
                }
                preceding_ids = {"p" + evidence_id[1:] for evidence_id in brief.evidence_ids}
                context.related_evidence_blocks.extend(
                    block for block in build_evidence_catalogue(preceding, prefix="p").blocks
                    if block.id in preceding_ids
                )
            return {"source": source, "context": context, "related": related,
                    "model": getattr(self.provider, "model", None)}
        snapshot, inputs = self.repository.capture_analysis_input(book_id, read_input, job_id=job_id)
        if book_reading:
            prepared_snapshot, _ = book_reading
            if (snapshot.revision, snapshot.configuration) != (
                prepared_snapshot.revision, prepared_snapshot.configuration
            ):
                self.repository.analysis_input_is_current(prepared_snapshot)
                return
        source = inputs["source"]
        source_text = str(source["text"])
        source_hash = sha256(source_text.encode()).hexdigest()
        started_at = perf_counter()
        decision = classify_chapter_source(
            title=str(source["title"]),
            text=source_text,
            nav_kind=source.get("nav_kind"),
            in_body=source.get("in_body"),
            structural_role=source.get("structural_role"),
            analysis_role=str(source.get("analysis_role") or "analysis_unit"),
        )
        if not decision.should_generate:
            # summary_only 章节（前言、后记）有真实内容但不属于作者的核心论证，
            # 用独立状态记录，好让界面把它们和"没内容可分析"区分开。
            status = "summary_only" if decision.summary_only else "skipped"
            # Claim before publishing even a deterministic skipped result.
            if not self.repository.set_chapter_analysis_status(
                book_id=book_id, chapter_id=chapter_id, status="generating",
                source_content_hash=source_hash, snapshot=snapshot,
            ):
                return
            if not self.repository.set_chapter_analysis_status(
                book_id=book_id, chapter_id=chapter_id, status=status,
                source_content_hash=source_hash, failure_reason=decision.reason, snapshot=snapshot,
            ):
                return
            self.repository.record_analysis_run(
                book_id=book_id,
                chapter_id=chapter_id,
                model=getattr(self.provider, "model", None),
                status=status,
                input_characters=len(source_text),
                output_characters=0,
                prompt_tokens=None,
                completion_tokens=None,
                total_tokens=None,
                elapsed_milliseconds=round((perf_counter() - started_at) * 1_000),
            )
            return
        if not self.repository.set_chapter_analysis_status(
            book_id=book_id, chapter_id=chapter_id, status="generating",
            source_content_hash=source_hash, snapshot=snapshot,
        ):
            return
        run_status = "failed"
        output_characters = 0
        prompt_tokens: int | None = None
        completion_tokens: int | None = None
        total_tokens: int | None = None
        model = getattr(self.provider, "model", None)
        try:
            chapter = ChapterSource(**source)
            context, related_chapters = inputs["context"], inputs["related"]
            generated = self._generate_with_retry(chapter, context)
            if isinstance(generated, GeneratedChapterAnalysis):
                draft = generated.draft
                model = generated.model
                output_characters = generated.output_characters
                prompt_tokens = generated.prompt_tokens
                completion_tokens = generated.completion_tokens
                total_tokens = generated.total_tokens
            else:
                draft = generated
            publishable, evidence_failure_reason = self._publishable_ideas(
                chapter=chapter, related_chapters=related_chapters, context=context, draft=draft
            )
            publishable_statements = self._publishable_statements(
                chapter=chapter, related_chapters=related_chapters, context=context, draft=draft
            )
            status = "ready" if publishable else "insufficient_evidence"
            published = self.repository.save_chapter_analysis(
                book_id=book_id,
                chapter_id=chapter_id,
                source_content_hash=source_hash,
                status=status,
                draft=draft,
                publishable_ideas=publishable,
                publishable_statements=publishable_statements,
                failure_reason=evidence_failure_reason if status == "insufficient_evidence" else None,
                snapshot=snapshot,
            )
            run_status = status if published else "superseded"
        except Exception as error:
            logger.exception(
                "chapter analysis failed, book_id=%s chapter_id=%s", book_id, chapter_id
            )
            self.repository.set_chapter_analysis_status(
                book_id=book_id,
                chapter_id=chapter_id,
                status="failed",
                source_content_hash=source_hash,
                failure_reason=str(error)[:300], snapshot=snapshot,
            )
        finally:
            try:
                self.repository.record_analysis_run(
                    book_id=book_id,
                    chapter_id=chapter_id,
                    model=model,
                    status=run_status,
                    input_characters=len(source_text),
                    output_characters=output_characters,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    elapsed_milliseconds=round((perf_counter() - started_at) * 1_000),
                )
            except Exception:
                logger.exception(
                    "failed to record analysis run, book_id=%s chapter_id=%s", book_id, chapter_id
                )

    def ensure_book_genre(self, book_id: str, *, job_id: str | None = None) -> str:
        """Detect and store the book's argument structure, once per book.

        Returns the genre in use. Never raises: an undetected genre falls back to
        the shared default, which still produces a valid analysis, so a failed
        auxiliary call must not stop the book from being analysed.
        """
        context = self._book_context(book_id)
        if context.genre:
            return context.genre
        detector = getattr(self.provider, "detect_genre", None)
        setter = getattr(self.repository, "set_book_genre", None)
        if not callable(detector) or not callable(setter):
            return DEFAULT_GENRE
        snapshot, (context, samples) = self.repository.capture_analysis_input(
            book_id, lambda: self._book_probe_input(book_id), job_id=job_id
        )
        if not self.repository.analysis_input_is_current(snapshot):
            return DEFAULT_GENRE
        if context.genre:
            return context.genre
        try:
            decision = detector(context, samples)
            setter(
                book_id,
                genre=decision.genre,
                confidence=decision.confidence,
                source="model", snapshot=snapshot,
            )
            return decision.genre
        except Exception:
            logger.exception("genre detection failed, book_id=%s", book_id)
            setter(book_id, genre=DEFAULT_GENRE, confidence=None, source="default", snapshot=snapshot)
            return DEFAULT_GENRE

    def prepare_book_reading_context(self, book_id, context, briefs, framing) -> BookReadingContext | None:
        try:
            return self.provider.prepare_book_reading_context(context, briefs, framing)
        except AnalysisProviderError:
            logger.warning("book orientation unavailable; using title and outline, book_id=%s", book_id)
            return None

    def prepare_chapter_reading(self, chapter, context) -> ChapterReading:
        for delay in (*self.retry_delays, None):
            try:
                return self.provider.prepare_chapter_reading(chapter, context)
            except AnalysisProviderError:
                if delay is None:
                    raise
                sleep(delay)
        raise AssertionError("unreachable")

    def _book_probe_input(self, book_id: str) -> tuple[BookContext, list[str]]:
        samples = [str(source["text"])[:500]
                   for source in self.repository.confirmed_chapter_sources(book_id)
                   if source.get("in_body", True)
                   and source.get("analysis_role", "analysis_unit") == "analysis_unit"
                   and str(source.get("text", "")).strip()][:2]
        return self._book_context(book_id), samples

    def _book_context(self, book_id: str) -> BookContext:
        reader = getattr(self.repository, "book_context_for_prompt", None)
        if not callable(reader):
            return BookContext()
        return BookContext(**reader(book_id))

    def _analysis_context(self, book_id: str, chapter: ChapterSource) -> tuple[BookContext, ChapterSource | None]:
        related = self._following_substantive_chapter(book_id, chapter.id)
        context = self._book_context(book_id)
        return (
            context.model_copy(
                update={
                    "evidence_blocks": list(build_evidence_catalogue(chapter, prefix="e").blocks),
                    "related_evidence_blocks": (
                        list(build_evidence_catalogue(related, prefix="x").blocks) if related else []
                    ),
                }
            ),
            related,
        )

    def _following_substantive_chapter(self, book_id: str, chapter_id: int) -> ChapterSource | None:
        sources = self.repository.confirmed_chapter_sources(book_id)
        current_index = next(
            (index for index, source in enumerate(sources) if int(source["id"]) == chapter_id), None
        )
        if current_index is None:
            return None
        for source in sources[current_index + 1 :]:
            decision = classify_chapter_source(
                title=str(source["title"]),
                text=str(source["text"]),
                nav_kind=str(source.get("nav_kind") or ""),
                in_body=bool(source.get("in_body", True)),
                analysis_role=str(source.get("analysis_role") or "analysis_unit"),
            )
            if decision.should_generate:
                return ChapterSource(book_id=book_id, **source)
        return None

    def _publishable_ideas(
        self,
        *,
        chapter: ChapterSource,
        related_chapters: list[ChapterSource],
        context: BookContext,
        draft: ChapterAnalysisDraft,
    ) -> tuple[list[tuple[object, list[EvidenceDraft]]], str | None]:
        source_by_id = {source.id: source for source in (chapter, *related_chapters)}
        catalogue = EvidenceCatalogue(
            blocks=tuple(context.evidence_blocks + context.related_evidence_blocks)
        )
        verifier = SourceVerifier()
        publishable: list[tuple[object, list[EvidenceDraft]]] = []
        unknown = duplicate = empty = missing = 0
        for idea in draft.core_ideas:
            resolved: list[EvidenceDraft] = []
            invalid_selection = False
            if idea.evidence_ids:
                selection = catalogue.resolve(idea.evidence_ids)
                unknown += len(selection.unknown_ids)
                duplicate += len(selection.duplicate_ids)
                empty += selection.empty_id_count
                invalid_selection = bool(
                    selection.unknown_ids or selection.duplicate_ids or selection.empty_id_count
                )
                for block in selection.blocks:
                    source = source_by_id.get(block.chapter_id)
                    if source is None:
                        invalid_selection = True
                        continue
                    evidence = EvidenceDraft(
                        page=block.page,
                        quote=block.quote,
                        surrounding_text=block.surrounding_text,
                        source_chapter_id=block.chapter_id,
                    )
                    page_text = {page.page_number: page.text for page in source.pages}
                    if self._evidence_is_supported(verifier, source, page_text, evidence):
                        resolved.append(evidence)
                    else:
                        invalid_selection = True
            else:
                # Compatibility for providers and test doubles written before ID selection.
                page_text = {page.page_number: page.text for page in chapter.pages}
                resolved = [
                    evidence
                    for evidence in idea.evidence
                    if chapter.source_start_page <= evidence.page <= chapter.source_end_page
                    and self._evidence_is_supported(verifier, chapter, page_text, evidence)
                ]
            if idea.content_type in SOURCED_CONTENT_TYPES:
                if not idea.evidence_ids and not idea.evidence:
                    missing += 1
                    continue
                if invalid_selection or not resolved or any(
                    evidence.source_chapter_id not in (None, chapter.id) for evidence in resolved
                ):
                    continue
            elif idea.content_type == AI_SYNTHESIS_CONTENT_TYPE:
                if not related_chapters or invalid_selection:
                    missing += 1
                    continue
                origins = {evidence.source_chapter_id for evidence in resolved}
                if chapter.id not in origins or len(origins) < 2:
                    missing += 1
                    continue
            publishable.append((idea, resolved))
        if publishable or not (unknown or duplicate or empty or missing):
            return publishable, None
        if unknown or duplicate or empty:
            return publishable, f"证据选择无效：未知={unknown}，重复={duplicate}，空={empty}"
        return publishable, "证据选择无效：缺少所需证据"

    def _publishable_statements(
        self,
        *,
        chapter: ChapterSource,
        related_chapters: list[ChapterSource],
        context: BookContext,
        draft: ChapterAnalysisDraft,
    ) -> list[tuple[str, int, AttributedStatementDraft, list[EvidenceDraft]]]:
        """Resolve every visible chapter-level statement against literal blocks.

        Unlike a core idea, a statement has no fallback raw-quote form: accepting
        it would reintroduce the unlabelled cross-chapter text this layer fixes.
        """
        catalogue = EvidenceCatalogue(
            blocks=tuple(context.evidence_blocks + context.related_evidence_blocks)
        )
        source_by_id = {source.id: source for source in (chapter, *related_chapters)}
        candidates: list[tuple[str, int, AttributedStatementDraft]] = [
            ("argument_chain", position, statement)
            for position, statement in enumerate(draft.argument_chain)
        ]
        if draft.role_in_book is not None:
            candidates.append(("role_in_book", 0, draft.role_in_book))
        verifier = SourceVerifier()
        publishable: list[tuple[str, int, AttributedStatementDraft, list[EvidenceDraft]]] = []
        for slot, position, statement in candidates:
            selection = catalogue.resolve(statement.evidence_ids)
            if selection.unknown_ids or selection.duplicate_ids or selection.empty_id_count:
                continue
            resolved: list[EvidenceDraft] = []
            for block in selection.blocks:
                source = source_by_id.get(block.chapter_id)
                if source is None:
                    continue
                evidence = EvidenceDraft(
                    page=block.page,
                    quote=block.quote,
                    surrounding_text=block.surrounding_text,
                    source_chapter_id=block.chapter_id,
                )
                page_text = {page.page_number: page.text for page in source.pages}
                if self._evidence_is_supported(verifier, source, page_text, evidence):
                    resolved.append(evidence)
            origins = {item.source_chapter_id for item in resolved}
            if statement.content_type == "book_summary":
                valid = bool(resolved) and origins == {chapter.id}
            else:
                valid = chapter.id in origins and len(origins) >= 2
            if valid:
                publishable.append((slot, position, statement, resolved))
        return publishable

    def _generate(
        self, chapter: ChapterSource, context: BookContext
    ) -> GeneratedChapterAnalysis | ChapterAnalysisDraft:
        method = getattr(self.provider, "generate_with_metrics", None)
        if not callable(method):
            method = self.provider.generate
        return call_with_optional_context(method, chapter, context)

    def _generate_with_retry(
        self, chapter: ChapterSource, context: BookContext
    ) -> GeneratedChapterAnalysis | ChapterAnalysisDraft:
        for attempt, delay in enumerate((*self.retry_delays, None), start=1):
            try:
                return self._generate(chapter, context)
            except AnalysisProviderError:
                if delay is None:
                    raise
                logger.warning(
                    "retrying chapter analysis after provider failure, chapter_id=%s attempt=%s",
                    chapter.id,
                    attempt,
                )
                sleep(delay)
        raise AssertionError("unreachable")

    @staticmethod
    def _evidence_is_supported(
        verifier: SourceVerifier,
        chapter: ChapterSource,
        page_text: dict[int, str],
        evidence: EvidenceDraft,
    ) -> bool:
        """Check a quote against the page it cites, not the whole chapter.

        Verifying against the concatenated chapter text let a quote be stitched
        together across page boundaries, because pages are joined with "\\n\\n"
        and the verifier collapses whitespace. Per-page verification closes
        that gap and makes the existing page-range check meaningful.

        Chapters imported before per-page text was stored have no page map; for
        those we fall back to the chapter-wide check so old books keep working.
        """
        if not page_text:
            return verifier.verify(source_text=chapter.text, proposed_quote=evidence.quote).is_valid
        return verifier.verify_on_page(
            pages=page_text, page_number=evidence.page, proposed_quote=evidence.quote
        ).is_valid

    def generate_book_overview(self, book_id: str, *, job_id: str | None = None) -> None:
        drafts = []
        snapshot = None
        started_at = perf_counter()
        model = getattr(self.provider, "model", None)
        output_characters = 0
        prompt_tokens: int | None = None
        completion_tokens: int | None = None
        total_tokens: int | None = None
        status = "failed"
        try:
            # A provisional ticket also guards the failure branch if input
            # reconstruction itself raises before the full snapshot is returned.
            snapshot, _ = self.repository.capture_analysis_input(book_id, lambda: [], job_id=job_id)
            snapshot, drafts = self.repository.capture_analysis_input(
                book_id, lambda: self.repository.ready_chapter_analysis_drafts(book_id), job_id=job_id, overview=True,
            )
            if not self.repository.analysis_input_is_current(snapshot):
                status = "superseded"
                return
            if not drafts:
                status = "skipped"
                return
            if any(draft.reading_record for draft in drafts):
                ready_ids = {draft.chapter_id for draft in drafts}
                missing = [source["title"] for source in self.repository.confirmed_chapter_sources(book_id)
                           if classify_chapter_source(title=str(source["title"]), text=str(source["text"]),
                               nav_kind=source.get("nav_kind"), in_body=source.get("in_body"),
                               structural_role=source.get("structural_role"),
                               analysis_role=str(source.get("analysis_role") or "analysis_unit")).should_generate
                           and int(source["id"]) not in ready_ids]
                if missing:
                    raise AnalysisProviderError("正文尚未全部分析，全书综合未生成：" + "、".join(missing))
            generate_with_metrics = getattr(self.provider, "generate_book_overview_with_metrics", None)
            generated = generate_with_metrics(drafts) if callable(generate_with_metrics) else self.provider.generate_book_overview(drafts)
            if isinstance(generated, GeneratedBookOverview):
                overview = generated.overview
                model = generated.model
                output_characters = generated.output_characters
                prompt_tokens = generated.prompt_tokens
                completion_tokens = generated.completion_tokens
                total_tokens = generated.total_tokens
            else:
                overview = generated
            published = self.repository.save_book_overview(
                book_id, core_question=overview.core_question,
                one_sentence_summary=overview.one_sentence_summary, snapshot=snapshot,
                **({"synthesis": overview.synthesis} if overview.synthesis else {}),
            )
            status = "superseded" if published is False else "ready"
        except Exception:
            logger.exception("book overview generation failed, book_id=%s", book_id)
            self._safely_mark_overview_failed(book_id, snapshot=snapshot)
            raise
        finally:
            # Never let bookkeeping failures replace the real exception: a raise
            # inside `finally` would supersede it and hide the true cause.
            try:
                self.repository.record_analysis_run(
                    book_id=book_id,
                    chapter_id=None,  # book-level run: not tied to any chapter
                    model=model,
                    status=status,
                    input_characters=sum(len(draft.chapter_question) + len(draft.one_sentence_conclusion) + len(draft.role_in_book) for draft in drafts),
                    output_characters=output_characters,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    elapsed_milliseconds=round((perf_counter() - started_at) * 1_000),
                )
            except Exception:
                logger.exception("failed to record overview analysis run, book_id=%s", book_id)

    def _safely_mark_overview_failed(self, book_id: str, *, snapshot=None) -> None:
        try:
            self.repository.set_book_overview_status(book_id, "failed", snapshot=snapshot)
        except Exception:
            logger.exception("failed to persist overview failure state, book_id=%s", book_id)


def generate_chapter_batch(
    service: AnalysisGenerationService, book_id: str, chapter_ids: list[int], *, max_workers: int = 24, job_id: str | None = None
) -> None:
    if not chapter_ids:
        return
    if getattr(service.provider, "analysis_protocol", "legacy") != PROTOCOL:
        service.ensure_book_genre(book_id, job_id=job_id)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(service.generate_chapter, book_id, chapter_id, job_id=job_id)
                       for chapter_id in chapter_ids]
            for future in futures:
                future.result()
        return

    repository = service.repository
    snapshot, (context, sources) = repository.capture_analysis_input(
        book_id, lambda: (service._book_context(book_id), repository.confirmed_chapter_sources(book_id)),
        job_id=job_id,
    )
    if not repository.analysis_input_is_current(snapshot):
        return
    chapters = []
    framing = []
    for source in sources:
        decision = classify_chapter_source(
            title=str(source["title"]), text=str(source["text"]), nav_kind=source.get("nav_kind"),
            in_body=source.get("in_body"), structural_role=source.get("structural_role"),
            analysis_role=str(source.get("analysis_role") or "analysis_unit"),
        )
        if decision.should_generate:
            chapters.append(ChapterSource(book_id=book_id, **source))
        elif decision.summary_only and re.match(
            r"^(序|序言|前言|导言|导论|译序|自序|后记|跋|结语|结束语|尾声)(?:$|[：:\s]|[（(])", str(source["title"])
        ):
            framing.append({"title": source["title"], "text": str(source["text"])[:4000]})

    target_ids = set(chapter_ids)
    readings = {}
    profile = None
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        if any(chapter.id in target_ids for chapter in chapters):
            # Collect in book order, independent of request completion order.
            futures = [executor.submit(service.prepare_chapter_reading, chapter, context) for chapter in chapters]
            for chapter, future in zip(chapters, futures):
                readings[chapter.id] = future.result()
            if not repository.analysis_input_is_current(snapshot):
                return
            briefs = [{"chapter_id": chapter.id, "title": chapter.title,
                       **readings[chapter.id].brief.model_dump(exclude={"evidence_ids"})}
                      for chapter in chapters]
            profile = service.prepare_book_reading_context(book_id, context, briefs, framing)
        if not repository.analysis_input_is_current(snapshot):
            return
        previous_by_id = {current.id: (previous, readings[previous.id])
                          for previous, current in zip(chapters, chapters[1:]) if previous.id in readings}
        futures = [executor.submit(
            service.generate_chapter, book_id, chapter_id, job_id=job_id,
            book_reading=(snapshot, profile), chapter_reading=readings.get(chapter_id),
            previous=previous_by_id.get(chapter_id),
        ) for chapter_id in chapter_ids]
        for future in futures:
            future.result()
