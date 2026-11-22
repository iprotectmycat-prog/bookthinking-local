from dataclasses import dataclass

from app.services.storage import BookRepository


class ChapterConfirmationError(ValueError):
    pass


@dataclass(frozen=True)
class ConfirmedChapter:
    title: str
    source_start_page: int
    source_end_page: int
    depth: int = 0
    parent_title: str | None = None
    nav_kind: str = "plain"
    in_body: bool = True
    structural_role: str = "unknown"
    role_source: str = "unknown"
    role_confidence: str = "low"
    analysis_role: str = "analysis_unit"
    source_locator: str | None = None
    text_sha256: str | None = None


class ChapterConfirmationService:
    def __init__(self, repository: BookRepository) -> None:
        self.repository = repository

    def confirm(self, book_id: str, chapters: list[ConfirmedChapter]) -> None:
        book = self.repository.get_book(book_id)
        if book is None:
            raise ChapterConfirmationError("书籍不存在")
        if book["status"] == "needs_attention":
            raise ChapterConfirmationError("正文未提取，无法确认章节")
        if not chapters:
            raise ChapterConfirmationError("至少需要一个章节")
        if any(not chapter.title.strip() for chapter in chapters):
            raise ChapterConfirmationError("章节标题不能为空")
        # Scope uniqueness to the parent, because books legitimately repeat a section
        # title under every chapter (a "结语" per chapter). Requiring globally unique
        # titles rejected those books outright.
        scoped_titles = [
            ((chapter.parent_title or "").strip(), chapter.title.strip()) for chapter in chapters
        ]
        if len(set(scoped_titles)) != len(scoped_titles):
            raise ChapterConfirmationError("同一层级下的章节标题不能重复")

        max_page = self.repository.max_draft_page(book_id)
        previous_start = 0
        previous_end = 0
        for chapter in chapters:
            if chapter.source_start_page > chapter.source_end_page:
                raise ChapterConfirmationError("章节起止页不合法")
            if chapter.source_start_page < previous_start or chapter.source_end_page < previous_end:
                raise ChapterConfirmationError("章节页码必须按顺序排列")
            if chapter.source_start_page < 1 or chapter.source_end_page > max_page:
                raise ChapterConfirmationError("章节页码超出原书范围")
            previous_start = chapter.source_start_page
            previous_end = chapter.source_end_page

        self.repository.replace_confirmed_chapters(book_id, chapters)

    def require_confirmed(self, book_id: str) -> None:
        book = self.repository.get_book(book_id)
        if book is None:
            raise ChapterConfirmationError("书籍不存在")
        if book["status"] != "chapters_confirmed":
            raise ChapterConfirmationError("章节尚未确认")
