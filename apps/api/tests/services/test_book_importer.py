import asyncio
import hashlib
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

import pytest
from fastapi import UploadFile
from reportlab.pdfgen.canvas import Canvas

from app.services.epub_parser import EpubParser
from app.services.pypdf_parser import PypdfParser
from app.services.book_importer import BookImporter, ImportResult


def make_text_pdf(path: Path, extra: str = "") -> None:
    canvas = Canvas(str(path))
    canvas.drawString(72, 720, "Chapter 1: Capital Costs")
    canvas.drawString(72, 690, "Capital costs change the value of future cash flows.")
    if extra:
        canvas.drawString(72, 660, extra[:400])
    canvas.showPage()
    canvas.save()


def make_epub(path: Path) -> None:
    with ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            "<container xmlns=\"urn:oasis:names:tc:opendocument:xmlns:container\"><rootfiles><rootfile full-path=\"OPS/package.opf\"/></rootfiles></container>",
        )
        archive.writestr(
            "OPS/package.opf",
            "<package xmlns=\"http://www.idpf.org/2007/opf\"><manifest><item id=\"chapter\" href=\"chapter.xhtml\" media-type=\"application/xhtml+xml\"/></manifest><spine><itemref idref=\"chapter\"/></spine></package>",
        )
        archive.writestr("OPS/chapter.xhtml", "<html><body><p>EPUB source evidence.</p></body></html>")


def test_import_persists_hash_and_chapter_draft(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    make_text_pdf(pdf_path)

    result = BookImporter(storage_root=tmp_path / "books", parser=PypdfParser()).import_pdf(pdf_path)

    assert len(result.sha256) == 64
    assert result.status == "awaiting_chapter_confirmation"
    assert result.stored_path.exists()
    assert result.chapters[0].source_start_page == 1
    assert result.chapters[0].source_end_page == 1
    assert "Capital costs change" in result.chapters[0].text


def test_import_persists_epub_hash_and_normalized_chapter_draft(tmp_path: Path) -> None:
    epub_path = tmp_path / "sample.epub"
    make_epub(epub_path)

    result = BookImporter(storage_root=tmp_path / "books", parser=PypdfParser(), epub_parser=EpubParser()).import_epub(epub_path)

    assert result.source_format == "epub"
    assert result.stored_path.suffix == ".epub"
    assert result.chapters[0].title == "全文"
    assert "EPUB source evidence." in result.chapters[0].text


def make_epub_with_unresolved_anchor(path: Path) -> None:
    with ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            "<container xmlns=\"urn:oasis:names:tc:opendocument:xmlns:container\"><rootfiles><rootfile full-path=\"OPS/package.opf\"/></rootfiles></container>",
        )
        archive.writestr(
            "OPS/package.opf",
            """<package xmlns="http://www.idpf.org/2007/opf" version="3.0"><metadata/>
              <manifest>
                <item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>
                <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
              </manifest><spine><itemref idref="chapter"/></spine>
            </package>""",
        )
        archive.writestr(
            "OPS/nav.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"><body><nav epub:type="toc" xmlns:epub="http://www.idpf.org/2007/ops"><ol>
              <li><a href="chapter.xhtml#missing">第一章</a></li>
            </ol></nav></body></html>""",
        )
        archive.writestr("OPS/chapter.xhtml", "<html><body><p>正文仍可读取。</p></body></html>")


def test_import_propagates_epub_anchor_diagnostics(tmp_path: Path) -> None:
    epub_path = tmp_path / "unresolved.epub"
    make_epub_with_unresolved_anchor(epub_path)

    result = BookImporter(storage_root=tmp_path / "books", parser=PypdfParser(), epub_parser=EpubParser()).import_epub(epub_path)

    assert result.diagnostics == ["unresolved_anchor:OPS/chapter.xhtml#missing"]


def test_concurrent_uploads_do_not_share_a_temporary_file(tmp_path: Path) -> None:
    """Regression: a hardcoded ".uploading" name let parallel imports clobber
    each other, and could store a file whose bytes did not match its sha256."""

    async def run() -> list[ImportResult]:
        importer = BookImporter(storage_root=tmp_path / "books", parser=PypdfParser())
        uploads = []
        for index in range(6):
            pdf_path = tmp_path / f"book-{index}.pdf"
            make_text_pdf(pdf_path, extra=f"Distinct body text number {index}. " * 200)
            uploads.append(pdf_path)

        async def import_one(path: Path) -> ImportResult:
            with path.open("rb") as handle:
                return await importer.import_upload(UploadFile(filename=path.name, file=handle))

        return await asyncio.gather(*(import_one(path) for path in uploads))

    results = asyncio.run(run())

    assert len({result.sha256 for result in results}) == 6
    for result in results:
        assert result.stored_path.exists()
        stored_digest = hashlib.sha256(result.stored_path.read_bytes()).hexdigest()
        assert stored_digest == result.sha256, "stored bytes must match the recorded hash"

    leftovers = list((tmp_path / "books").glob(".uploading*"))
    assert leftovers == [], f"temporary files were left behind: {leftovers}"


def import_upload(tmp_path: Path, path: Path, filename: str | None = None) -> ImportResult:
    importer = BookImporter(storage_root=tmp_path / "books", parser=PypdfParser(), epub_parser=EpubParser())
    with path.open("rb") as handle:
        return asyncio.run(importer.import_upload(UploadFile(filename=filename or path.name, file=handle)))


def make_mobi(path: Path) -> None:
    """Write just enough of a PalmDB header to carry the BOOKMOBI type-creator."""
    header = bytearray(b"\0" * 78)
    header[0:10] = b"SampleBook"
    header[60:68] = b"BOOKMOBI"
    path.write_bytes(bytes(header) + b"\0" * 200)


def test_accepts_kobo_kepub_as_a_standard_epub(tmp_path: Path) -> None:
    """KEPUB only adds reading-location markup, so it must import like any EPUB."""
    kepub_path = tmp_path / "sample.kepub.epub"
    make_epub(kepub_path)

    result = import_upload(tmp_path, kepub_path)

    assert result.source_format == "epub"
    assert result.chapters[0].text == "EPUB source evidence."


def test_accepts_bare_kepub_extension(tmp_path: Path) -> None:
    kepub_path = tmp_path / "sample.kepub"
    make_epub(kepub_path)

    assert import_upload(tmp_path, kepub_path).source_format == "epub"


def test_names_the_kindle_format_and_points_at_conversion(tmp_path: Path) -> None:
    """A generic rejection left users stuck; the hint must say what to do next."""
    mobi_path = tmp_path / "sample.mobi"
    make_mobi(mobi_path)

    with pytest.raises(ValueError, match="MOBI.*Calibre 转换为 EPUB"):
        import_upload(tmp_path, mobi_path)


def test_recognises_kindle_files_by_magic_bytes_when_the_extension_lies(tmp_path: Path) -> None:
    """The MOBI marker sits at bytes 60-68, past the old four-byte sniff window."""
    mobi_path = tmp_path / "book.bin"
    make_mobi(mobi_path)

    with pytest.raises(ValueError, match="MOBI/Kindle 格式"):
        import_upload(tmp_path, mobi_path)


def test_explains_that_comic_archives_have_no_text_layer(tmp_path: Path) -> None:
    comic_path = tmp_path / "sample.cbz"
    make_epub(comic_path)

    with pytest.raises(ValueError, match="只有图片没有文字层"):
        import_upload(tmp_path, comic_path)


def test_suggests_conversion_for_plain_text_and_word_documents(tmp_path: Path) -> None:
    document_path = tmp_path / "draft.docx"
    document_path.write_bytes(b"PK\x03\x04" + b"\0" * 100)

    with pytest.raises(ValueError, match="DOCX.*Calibre"):
        import_upload(tmp_path, document_path)


def test_falls_back_to_the_generic_message_for_unknown_files(tmp_path: Path) -> None:
    unknown_path = tmp_path / "mystery.xyz"
    unknown_path.write_bytes(b"\x00\x01\x02\x03" + b"\0" * 100)

    with pytest.raises(ValueError, match="仅支持 PDF 或 EPUB 文件"):
        import_upload(tmp_path, unknown_path)
