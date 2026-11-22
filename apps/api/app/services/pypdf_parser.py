from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import re

from pypdf import PdfReader
from pypdf.errors import PdfReadError


class InvalidPdfError(ValueError):
    pass


class TextExtractionUnavailableError(ValueError):
    pass


@dataclass(frozen=True)
class ChapterDraft:
    title: str
    source_start_page: int
    source_end_page: int
    text: str
    depth: int = 0
    parent_title: str | None = None
    nav_kind: str = "plain"
    in_body: bool = True
    structural_role: str = "unknown"
    role_source: str = "unknown"
    role_confidence: str = "low"
    source_locator: str | None = None
    text_sha256: str | None = None
    # Outline nodes and analysis units are related but not identical. A publisher
    # may point a chapter heading and its first subsection at the same source anchor;
    # only one of those entries may own an analysis of that text.
    analysis_role: str = "analysis_unit"


@dataclass(frozen=True)
class BookMetadata:
    """Publisher-declared facts read straight from the source file, never inferred."""

    title: str | None = None
    subtitle: str | None = None
    raw_title: str | None = None
    authors: tuple[str, ...] = ()
    translators: tuple[str, ...] = ()
    publisher: str | None = None
    language: str | None = None
    published_at: str | None = None
    identifier: str | None = None
    spec_version: str | None = None
    top_level_chapter_count: int = 0
    analysis_unit_count: int = 0


@dataclass(frozen=True)
class ParsedBook:
    pages: list[str]
    chapters: list[ChapterDraft]
    metadata: BookMetadata = field(default_factory=BookMetadata)
    diagnostics: list[str] = field(default_factory=list)


NUMBERED_HEADING = re.compile(r"^\s*(\d{1,3})[.．]\s+([^\n]{1,70}?)\s*$")


def _infer_numbered_headings(page_text: list[str]) -> list[ChapterDraft]:
    """Infer a conservative, sequential numbered outline from extracted text."""
    candidates: list[tuple[int, int, str]] = []
    expected = 1
    for page_number, text in enumerate(page_text, start=1):
        for line in text.splitlines():
            match = NUMBERED_HEADING.match(line)
            if not match:
                continue
            number = int(match.group(1))
            title = " ".join(match.group(2).split()).strip(" .．")
            if number == expected and title:
                candidates.append((number, page_number, title))
                expected += 1

    if len(candidates) < 2:
        return []

    chapters: list[ChapterDraft] = []
    for index, (number, start_page, title) in enumerate(candidates):
        if index + 1 < len(candidates):
            next_start_page = candidates[index + 1][1]
            end_page = max(start_page, next_start_page)
        else:
            end_page = len(page_text)
        chapters.append(
            ChapterDraft(
                title=f"{number}. {title}",
                source_start_page=start_page,
                source_end_page=end_page,
                text="\n\n".join(page_text[start_page - 1 : end_page]).strip(),
                source_locator=f"pdf:pages:{start_page}-{end_page}",
                text_sha256=_text_sha256("\n\n".join(page_text[start_page - 1 : end_page]).strip()),
            )
        )
    return chapters


def _flatten_outline(items: list[object]) -> list[object]:
    destinations: list[object] = []
    for item in items:
        if isinstance(item, list):
            destinations.extend(_flatten_outline(item))
        else:
            destinations.append(item)
    return destinations


class PypdfParser:
    """Deterministic local parser for PDF text layers; image pixels and OCR are intentionally excluded."""

    text_layer_only = True

    def parse_pdf(self, path: Path) -> ParsedBook:
        try:
            reader = PdfReader(path)
        except PdfReadError as error:
            raise InvalidPdfError("无法读取 PDF 文件") from error
        page_text = [page.extract_text() or "" for page in reader.pages]
        text = "\n\n".join(page_text).strip()
        if not text:
            raise TextExtractionUnavailableError("PDF 未提取到可用文本；扫描件暂不支持")

        starts: dict[int, str] = {}
        for destination in _flatten_outline(list(reader.outline)):
            title = getattr(destination, "title", "")
            if not title:
                continue
            try:
                page_number = reader.get_destination_page_number(destination) + 1
            except (AttributeError, ValueError):
                continue
            if 1 <= page_number <= len(page_text):
                starts.setdefault(page_number, str(title).strip())

        outline_chapters: list[ChapterDraft] = []
        if starts:
            ordered_starts = sorted(starts)
            for index, start_page in enumerate(ordered_starts):
                end_page = ordered_starts[index + 1] - 1 if index + 1 < len(ordered_starts) else len(page_text)
                outline_chapters.append(
                    ChapterDraft(
                        title=starts[start_page],
                        source_start_page=start_page,
                        source_end_page=end_page,
                        text="\n\n".join(page_text[start_page - 1 : end_page]).strip(),
                        source_locator=f"pdf:pages:{start_page}-{end_page}",
                        text_sha256=_text_sha256("\n\n".join(page_text[start_page - 1 : end_page]).strip()),
                    )
                )
        inferred_chapters = _infer_numbered_headings(page_text)
        if len(inferred_chapters) > len(outline_chapters):
            chapters = inferred_chapters
        elif outline_chapters:
            chapters = outline_chapters
        else:
            chapters = [
                ChapterDraft(
                    "全文",
                    1,
                    len(page_text),
                    text,
                    source_locator=f"pdf:pages:1-{len(page_text)}",
                    text_sha256=_text_sha256(text),
                )
            ]
        return ParsedBook(pages=page_text, chapters=chapters)


def _text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
