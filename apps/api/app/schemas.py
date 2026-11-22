from typing import Literal

from pydantic import BaseModel, Field

from app.services.book_structure import StructurePreview
from app.services.storage import StructureApplyResult


BookAccessScope = Literal["owned", "public"]


class HealthResponse(BaseModel):
    status: str


class ChapterDraftResponse(BaseModel):
    title: str
    source_start_page: int
    source_end_page: int
    # Navigation structure taken from the source file. The defaults describe a flat,
    # body-level outline, so PDF imports and older clients stay valid unchanged.
    depth: int = 0
    parent_title: str | None = None
    nav_kind: str = "plain"
    in_body: bool = True
    structural_role: str = "unknown"
    role_source: str = "unknown"
    role_confidence: str = "low"
    analysis_role: str = "analysis_unit"


class ChapterResponse(ChapterDraftResponse):
    id: int
    source_locator: str | None = None


class BookImportResponse(BaseModel):
    id: str
    sha256: str
    source_format: str
    status: str
    diagnostics: list[str]
    chapters: list[ChapterDraftResponse]


class ChapterConfirmationRequest(BaseModel):
    chapters: list[ChapterDraftResponse]


class StructureChapterResponse(ChapterDraftResponse):
    source_locator: str | None = None
    text_sha256: str | None = None


class StructurePreviewResponse(BaseModel):
    chapters: list[StructureChapterResponse]
    diagnostics: list[str]
    provider: str
    structure_hash: str

    @classmethod
    def from_domain(cls, preview: StructurePreview) -> "StructurePreviewResponse":
        return cls(
            chapters=[
                StructureChapterResponse(
                    title=chapter.title,
                    source_start_page=chapter.source_start_page,
                    source_end_page=chapter.source_end_page,
                    depth=chapter.depth,
                    parent_title=chapter.parent_title,
                    nav_kind=chapter.nav_kind,
                    in_body=chapter.in_body,
                    structural_role=chapter.structural_role,
                    role_source=chapter.role_source,
                    role_confidence=chapter.role_confidence,
                    analysis_role=chapter.analysis_role,
                    source_locator=chapter.source_locator,
                    text_sha256=chapter.text_sha256,
                )
                for chapter in preview.chapters
            ],
            diagnostics=preview.diagnostics,
            provider=preview.provider,
            structure_hash=preview.structure_hash,
        )


class StructureApplyRequest(BaseModel):
    structure_hash: str


class StructureApplyResponse(BaseModel):
    preserved_count: int
    stale_count: int
    added_count: int
    removed_count: int

    @classmethod
    def from_domain(cls, result: StructureApplyResult) -> "StructureApplyResponse":
        return cls(
            preserved_count=result.preserved_count,
            stale_count=result.stale_count,
            added_count=result.added_count,
            removed_count=result.removed_count,
        )


class BookResponse(BaseModel):
    id: str
    filename: str
    title: str | None = None
    subtitle: str | None = None
    sha256: str
    source_format: str
    status: str
    diagnostics: list[str]
    structure_version: str | None = None
    structure_diagnostics: list[str] = Field(default_factory=list)
    access_scope: BookAccessScope = "owned"
    chapters: list[ChapterResponse]


class AnalyzedBookResponse(BaseModel):
    id: str
    filename: str
    source_format: str
    title: str | None = None
    authors: str | None = None
    access_scope: BookAccessScope = "owned"


class SourceSpanResponse(BaseModel):
    id: int
    source_page: int
    quote: str
    surrounding_text: str
    verification_status: str
    source_chapter_id: int | None = None
    source_chapter_title: str | None = None
    source_locator: str | None = None


class CoreIdeaResponse(BaseModel):
    id: int
    position: int
    title: str
    conclusion: str
    importance: str
    explanation: str
    reasoning_steps: list[str]
    examples: list[str]
    caveats: list[str]
    author_caveats: list[str] = Field(default_factory=list)
    ai_caveats: list[str] = Field(default_factory=list)
    warrant: str = ""
    genre_fields: dict[str, object] = Field(default_factory=dict)
    relations: list[str]
    content_type: str
    confidence: float
    sources: list[SourceSpanResponse]


class AttributedStatementResponse(BaseModel):
    text: str
    content_type: str
    sources: list[SourceSpanResponse] = Field(default_factory=list)


class AnalysisJobResponse(BaseModel):
    id: str
    book_id: str
    status: Literal["queued", "running", "succeeded", "failed", "interrupted", "superseded"]
    stage: Literal["chapters", "overview"]
    target_chapter_ids: list[int]
    completed_chapter_ids: list[int]
    failed_chapter_ids: list[int]
    error_code: str | None = None


class ChapterAnalysisResponse(BaseModel):
    reading_record: dict[str, object] | None = None
    analysis_job: AnalysisJobResponse | None = None
    book_id: str
    chapter_id: int
    title: str
    source_start_page: int
    source_end_page: int
    source_locator: str | None = None
    chapter_question: str
    one_sentence_conclusion: str
    short_summary: str
    argument_chain: list[AttributedStatementResponse]
    role_in_book: AttributedStatementResponse | None
    estimated_reading_minutes: int
    generation_status: str
    failure_reason: str | None
    previous_chapter_id: int | None
    next_chapter_id: int | None
    core_ideas: list[CoreIdeaResponse]
    # Needed to label genre_fields: the same key means different things across
    # structures, so the reader has to know which one produced this analysis.
    genre: str | None = None


class ChapterOverviewResponse(BaseModel):
    id: int
    position: int
    title: str
    source_start_page: int
    source_end_page: int
    chapter_question: str
    one_sentence_conclusion: str
    core_idea_titles: list[str]
    role_in_book: str
    estimated_reading_minutes: int
    generation_status: str
    failure_reason: str | None
    depth: int = 0
    parent_title: str | None = None
    nav_kind: str = "plain"
    in_body: bool = True
    analysis_role: str = "analysis_unit"


class BookOverviewResponse(BaseModel):
    synthesis: dict[str, object] | None = None
    analysis_job: AnalysisJobResponse | None = None
    book_id: str
    book_title: str
    source_format: str
    core_question: str
    one_sentence_summary: str
    overview_status: str = "pending"
    estimated_reading_minutes: int
    ready_chapter_count: int
    chapter_count: int
    top_level_chapter_count: int = 0
    section_count: int = 0
    chapters: list[ChapterOverviewResponse]
    # Publisher-declared details, present only when the source file carried them.
    book_subtitle: str | None = None
    book_authors: str | None = None
    book_publisher: str | None = None
    # Which argument structure the chapter analyses were produced under.
    genre: str | None = None
    access_scope: BookAccessScope = "owned"


class PublishBookRequest(BaseModel):
    rights_confirmed: Literal[True]


class AdminBookResponse(BaseModel):
    id: str
    title: str | None = None
    filename: str
    source_format: str
    visibility: Literal["private", "public"]
    overview_status: str
    ready_chapter_count: int
    public_at: str | None = None
    publication_blockers: list[str] = Field(default_factory=list)


class ExternalBookLinkResponse(BaseModel):
    provider: Literal["douban"] = "douban"
    status: Literal["matched", "unavailable"]
    url: str | None = None


class AnalysisRunResponse(BaseModel):
    id: int
    book_id: str
    chapter_id: int | None
    model: str | None
    status: str
    input_characters: int
    output_characters: int
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    elapsed_milliseconds: int
    created_at: str
