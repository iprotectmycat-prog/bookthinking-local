import hashlib
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.services.epub_parser import EpubParser, InvalidEpubError
from app.services.pypdf_parser import (
    BookMetadata,
    ChapterDraft,
    InvalidPdfError,
    PypdfParser,
    TextExtractionUnavailableError,
)


@dataclass(frozen=True)
class ImportResult:
    sha256: str
    source_format: str
    status: str
    stored_path: Path
    pages: list[str]
    chapters: list[ChapterDraft]
    diagnostics: list[str] = field(default_factory=list)
    metadata: BookMetadata = field(default_factory=BookMetadata)


# The MOBI/PalmDB type-creator marker sits at bytes 60-68, so sniffing only the first
# four bytes cannot recognise Kindle files.
HEADER_SAMPLE_BYTES = 68


class BookImporter:
    def __init__(self, storage_root: Path, parser: PypdfParser, epub_parser: EpubParser | None = None) -> None:
        self.storage_root = storage_root
        self.pdf_parser = parser
        self.epub_parser = epub_parser or EpubParser()

    def import_pdf(self, source_path: Path) -> ImportResult:
        header = source_path.read_bytes()[:HEADER_SAMPLE_BYTES]
        if not header.startswith(b"%PDF"):
            raise ValueError(_rejection_message(source_path.name, header))
        return self._import_source(source_path, "pdf")

    def import_epub(self, source_path: Path) -> ImportResult:
        header = source_path.read_bytes()[:HEADER_SAMPLE_BYTES]
        if not header.startswith(b"PK"):
            raise ValueError(_rejection_message(source_path.name, header))
        return self._import_source(source_path, "epub")

    def _import_source(self, source_path: Path, source_format: str) -> ImportResult:
        contents = source_path.read_bytes()
        digest = hashlib.sha256(contents).hexdigest()
        self.storage_root.mkdir(parents=True, exist_ok=True)
        stored_path = self.storage_root / f"{digest}.{source_format}"
        shutil.copyfile(source_path, stored_path)
        try:
            parsed = self._parse(stored_path, source_format)
        except TextExtractionUnavailableError as error:
            return ImportResult(digest, source_format, "needs_attention", stored_path, [], [], [str(error)])
        except (InvalidPdfError, InvalidEpubError):
            stored_path.unlink(missing_ok=True)
            raise
        return ImportResult(
            digest,
            source_format,
            "awaiting_chapter_confirmation",
            stored_path,
            parsed.pages,
            parsed.chapters,
            diagnostics=parsed.diagnostics,
            metadata=parsed.metadata,
        )

    async def import_upload(self, upload: UploadFile) -> ImportResult:
        self.storage_root.mkdir(parents=True, exist_ok=True)
        temporary_path = self.storage_root / f".uploading-{os.getpid()}-{uuid4().hex}"
        digest = hashlib.sha256()
        first_bytes = b""
        try:
            with temporary_path.open("wb") as destination:
                while chunk := await upload.read(1024 * 1024):
                    if len(first_bytes) < HEADER_SAMPLE_BYTES:
                        first_bytes += chunk[: HEADER_SAMPLE_BYTES - len(first_bytes)]
                    digest.update(chunk)
                    destination.write(chunk)

            source_format = _source_format(upload.filename, first_bytes)
            stored_path = self.storage_root / f"{digest.hexdigest()}.{source_format}"
            temporary_path.replace(stored_path)
        finally:
            temporary_path.unlink(missing_ok=True)

        try:
            parsed = self._parse(stored_path, source_format)
        except (InvalidPdfError, InvalidEpubError):
            stored_path.unlink(missing_ok=True)
            raise
        except TextExtractionUnavailableError as error:
            return ImportResult(digest.hexdigest(), source_format, "needs_attention", stored_path, [], [], [str(error)])
        return ImportResult(
            digest.hexdigest(),
            source_format,
            "awaiting_chapter_confirmation",
            stored_path,
            parsed.pages,
            parsed.chapters,
            diagnostics=parsed.diagnostics,
            metadata=parsed.metadata,
        )

    def _parse(self, path: Path, source_format: str):
        if source_format == "pdf":
            return self.pdf_parser.parse_pdf(path)
        return self.epub_parser.parse_epub(path)


UNSUPPORTED_FORMAT_MESSAGE = "仅支持 PDF 或 EPUB 文件"
CONVERTIBLE_HINT = "，请先用 Calibre 转换为 EPUB 后再导入"

# Extensions that are really EPUB in disguise. Kobo's KEPUB only adds reading-location
# markup on top of a standard EPUB container, so the existing parser handles it as-is.
EPUB_EXTENSIONS = (".epub", ".kepub", ".kepub.epub")

# Formats we deliberately do not parse. Naming the format beats a generic rejection,
# because the user otherwise has no idea what to do next.
CONVERTIBLE_EXTENSIONS = {
    ".mobi": "MOBI（Kindle 旧格式）",
    ".azw": "AZW（Kindle 格式）",
    ".azw3": "AZW3（Kindle 格式）",
    ".kfx": "KFX（Kindle 格式）",
    ".fb2": "FB2（FictionBook）",
    ".lit": "LIT（Microsoft Reader 格式）",
    ".txt": "TXT（纯文本）",
    ".docx": "DOCX（Word 文档）",
    ".doc": "DOC（Word 文档）",
    ".rtf": "RTF（富文本）",
}

# Image-only containers: converting them does not help, they need OCR instead.
IMAGE_ONLY_EXTENSIONS = {
    ".cbz": "CBZ（漫画图片包）",
    ".cbr": "CBR（漫画图片包）",
    ".djvu": "DjVu（扫描件）",
}


def _rejection_message(filename: str | None, first_bytes: bytes) -> str:
    """Explain why a file was refused, naming the format when we can recognise it."""
    name = (filename or "").lower()
    for extension, label in IMAGE_ONLY_EXTENSIONS.items():
        if name.endswith(extension):
            return f"检测到 {label}，其中只有图片没有文字层，无法提取正文"
    for extension, label in CONVERTIBLE_EXTENSIONS.items():
        if name.endswith(extension):
            return f"检测到 {label}{CONVERTIBLE_HINT}"
    if first_bytes[60:68] == b"BOOKMOBI":
        return f"检测到 MOBI/Kindle 格式{CONVERTIBLE_HINT}"
    return UNSUPPORTED_FORMAT_MESSAGE


def _source_format(filename: str | None, first_bytes: bytes) -> str:
    if first_bytes.startswith(b"%PDF"):
        return "pdf"
    name = (filename or "").lower()
    if name.endswith(EPUB_EXTENSIONS) and first_bytes.startswith(b"PK"):
        return "epub"
    raise ValueError(_rejection_message(filename, first_bytes))
