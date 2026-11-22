"""Read-only EPUB structure previews and explicit, hash-guarded application."""

from dataclasses import dataclass
from hashlib import sha256
from json import dumps
from pathlib import Path

from app.services.epub_parser import EpubParser, InvalidEpubError
from app.services.pypdf_parser import ChapterDraft, ParsedBook
from app.services.storage import BookRepository, StructureApplyResult


class BookStructureError(ValueError):
    pass


class StructureBookNotFoundError(BookStructureError):
    pass


class UnsupportedBookStructureError(BookStructureError):
    pass


class StaleStructurePreviewError(BookStructureError):
    pass


class StoredBookUnavailableError(BookStructureError):
    pass


class InvalidBookStructureError(BookStructureError):
    pass


@dataclass(frozen=True)
class StructurePreview:
    chapters: list[ChapterDraft]
    diagnostics: list[str]
    provider: str
    structure_hash: str


def structure_hash(parsed: ParsedBook) -> str:
    """Hash exactly the parser facts that identify a proposed chapter structure."""
    payload = [
        (
            chapter.title,
            chapter.source_locator,
            chapter.text_sha256,
            chapter.source_start_page,
            chapter.source_end_page,
            chapter.depth,
            chapter.parent_title,
            chapter.nav_kind,
            chapter.in_body,
            chapter.structural_role,
            chapter.analysis_role,
        )
        for chapter in parsed.chapters
    ]
    return sha256(dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


class BookStructureService:
    provider = "stdlib-epub-v2"

    def __init__(self, repository: BookRepository, parser: EpubParser | None = None) -> None:
        self.repository = repository
        self.parser = parser or EpubParser()

    def preview(self, book_id: str) -> StructurePreview:
        parsed = self._parse_saved_epub(book_id)
        return StructurePreview(
            chapters=list(parsed.chapters),
            diagnostics=list(parsed.diagnostics),
            provider=self.provider,
            structure_hash=structure_hash(parsed),
        )

    def apply(self, book_id: str, expected_structure_hash: str) -> StructureApplyResult:
        parsed = self._parse_saved_epub(book_id)
        if structure_hash(parsed) != expected_structure_hash:
            raise StaleStructurePreviewError("书籍结构已变化，请重新预览后再应用")
        return self.repository.apply_epub_structure(book_id, parsed)

    def _parse_saved_epub(self, book_id: str) -> ParsedBook:
        book = self.repository.get_book(book_id)
        if book is None:
            raise StructureBookNotFoundError("书籍不存在")
        if book["source_format"] != "epub":
            raise UnsupportedBookStructureError("仅支持 EPUB 书籍结构重解析")

        stored_path = self.repository.get_stored_book_path(book_id)
        if stored_path is None:
            raise StoredBookUnavailableError("书籍原文件不存在")
        path = self._managed_book_path(stored_path)
        try:
            return self.parser.parse_epub(path)
        except InvalidEpubError as error:
            raise InvalidBookStructureError(str(error)) from error

    def _managed_book_path(self, stored_path: Path) -> Path:
        """Only parse a file below this repository's managed books directory."""
        try:
            path = stored_path.resolve(strict=True)
            books_dir = (self.repository.database_path.parent / "books").resolve(strict=True)
            path.relative_to(books_dir)
        except (FileNotFoundError, ValueError):
            raise StoredBookUnavailableError("书籍原文件不存在") from None
        return path
