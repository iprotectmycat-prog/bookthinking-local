from io import BytesIO

from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from app.services.pypdf_parser import PypdfParser, _infer_numbered_headings


def test_parser_declares_text_layer_only() -> None:
    assert PypdfParser.text_layer_only is True


def test_parser_keeps_text_layer_without_interpreting_embedded_images(tmp_path) -> None:
    path = tmp_path / "with-image.pdf"
    image = ImageReader(BytesIO(b"P6\n1 1\n255\n\xff\x00\x00"))
    canvas = Canvas(str(path))
    canvas.drawString(72, 720, "Only this text belongs to the source layer.")
    canvas.drawImage(image, 72, 640, width=24, height=24)
    canvas.save()

    parsed = PypdfParser().parse_pdf(path)

    assert parsed.pages == ["Only this text belongs to the source layer.\n"]


def make_outlined_pdf() -> bytes:
    output = BytesIO()
    canvas = Canvas(output)
    canvas.bookmarkPage("chapter-1")
    canvas.addOutlineEntry("第一章 起点", "chapter-1", level=0)
    canvas.drawString(72, 720, "First chapter source evidence.")
    canvas.showPage()
    canvas.bookmarkPage("chapter-2")
    canvas.addOutlineEntry("第二章 结论", "chapter-2", level=0)
    canvas.drawString(72, 720, "Second chapter source evidence.")
    canvas.showPage()
    canvas.save()
    return output.getvalue()


def test_parser_uses_pdf_outline_as_chapter_ranges(tmp_path) -> None:
    path = tmp_path / "outline.pdf"
    path.write_bytes(make_outlined_pdf())

    parsed = PypdfParser().parse_pdf(path)

    assert len(parsed.pages) == 2
    assert "First chapter source evidence." in parsed.pages[0]
    assert "Second chapter source evidence." in parsed.pages[1]
    assert [
        (chapter.title, chapter.source_start_page, chapter.source_end_page)
        for chapter in parsed.chapters
    ] == [
        ("第一章 起点", 1, 1),
        ("第二章 结论", 2, 2),
    ]
    assert "First chapter source evidence." in parsed.chapters[0].text
    assert "Second chapter source evidence." in parsed.chapters[1].text


def test_parser_falls_back_to_full_book_without_outline(tmp_path) -> None:
    path = tmp_path / "plain.pdf"
    output = BytesIO()
    canvas = Canvas(output)
    canvas.drawString(72, 720, "Only page source evidence.")
    canvas.showPage()
    canvas.save()
    path.write_bytes(output.getvalue())

    parsed = PypdfParser().parse_pdf(path)

    assert len(parsed.pages) == 1
    assert [(chapter.title, chapter.source_start_page, chapter.source_end_page) for chapter in parsed.chapters] == [
        ("全文", 1, 1)
    ]


def test_parser_infers_numbered_chapters_from_text_when_outline_is_missing() -> None:
    pages = [
        "书名\n1.    简介\n第一章正文",
        "第一章续文\n2.    交易\n第二章正文\n3.    时间戳服务器\n第三章正文",
        "第三章续文\n4.    工作量证明\n第四章正文",
    ]

    chapters = _infer_numbered_headings(pages)

    assert [(chapter.title, chapter.source_start_page, chapter.source_end_page) for chapter in chapters] == [
        ("1. 简介", 1, 2),
        ("2. 交易", 2, 2),
        ("3. 时间戳服务器", 2, 3),
        ("4. 工作量证明", 3, 3),
    ]
