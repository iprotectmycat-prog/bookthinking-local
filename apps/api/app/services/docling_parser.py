from dataclasses import dataclass
from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption


@dataclass(frozen=True)
class ChapterDraft:
    title: str
    source_start_page: int
    source_end_page: int
    text: str


@dataclass(frozen=True)
class ParsedBook:
    chapters: list[ChapterDraft]


class DoclingParser:
    def __init__(self) -> None:
        options = PdfPipelineOptions(do_ocr=False)
        self.converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
        )

    def parse_pdf(self, path: Path) -> ParsedBook:
        document = self.converter.convert(path).document
        text = document.export_to_markdown().strip()
        if not text:
            raise ValueError("PDF 未提取到可用文本")
        page_count = max(document.pages.keys(), default=1)
        return ParsedBook(chapters=[ChapterDraft("全文", 1, page_count, text)])
