from io import BytesIO
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

from PIL import Image
from reportlab.pdfgen.canvas import Canvas

from app.services.book_cover import BookCoverService


def write_epub_with_cover(path: Path, *, use_guide: bool = False) -> Path:
    image = BytesIO()
    Image.new("RGB", (80, 120), "#9b4e32").save(image, format="PNG")
    with ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OPS/package.opf"/></rootfiles></container>',
        )
        metadata = "" if use_guide else '<metadata><meta name="cover" content="cover"/></metadata>'
        properties = "" if use_guide else ' properties="cover-image"'
        guide = '<guide><reference type="cover" href="images/cover.png" title="封面"/></guide>' if use_guide else ""
        archive.writestr("OPS/package.opf", f'<package xmlns="http://www.idpf.org/2007/opf">{metadata}<manifest><item id="cover" href="images/cover.png" media-type="image/png"{properties}/></manifest><spine/>{guide}</package>')
        archive.writestr("OPS/images/cover.png", image.getvalue())
    return path


def write_pdf(path: Path) -> Path:
    canvas = Canvas(str(path))
    canvas.setFillColorRGB(0.61, 0.31, 0.2)
    canvas.rect(0, 0, 612, 792, fill=1, stroke=0)
    canvas.setFillColorRGB(1, 1, 1)
    canvas.setFont("Helvetica-Bold", 38)
    canvas.drawString(72, 560, "BookThinking")
    canvas.save()
    return path


def test_extracts_and_caches_the_publisher_declared_epub_cover(tmp_path: Path) -> None:
    source = write_epub_with_cover(tmp_path / "book.epub")
    service = BookCoverService(tmp_path / "covers")

    first = service.get_or_create(book_id="book", source_path=source, source_format="epub")
    second = service.get_or_create(book_id="book", source_path=source, source_format="epub")

    assert first.media_type == "image/webp"
    assert first.path.exists()
    assert Image.open(first.path).size == (80, 120)
    assert second.path == first.path


def test_extracts_an_epub2_guide_cover_when_no_manifest_cover_is_declared(tmp_path: Path) -> None:
    source = write_epub_with_cover(tmp_path / "guide-cover.epub", use_guide=True)

    cover = BookCoverService(tmp_path / "covers").get_or_create(book_id="guide", source_path=source, source_format="epub")

    assert Image.open(cover.path).size == (80, 120)


def test_extracts_an_image_from_an_epub2_guide_cover_page(tmp_path: Path) -> None:
    image = BytesIO()
    Image.new("RGB", (80, 120), "#526b86").save(image, format="PNG")
    source = tmp_path / "guide-cover-page.epub"
    with ZipFile(source, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OPS/package.opf"/></rootfiles></container>',
        )
        archive.writestr(
            "OPS/package.opf",
            '<package xmlns="http://www.idpf.org/2007/opf"><manifest><item id="page" href="Text/titlepage.xhtml" media-type="application/xhtml+xml"/><item id="artwork" href="Images/front.png" media-type="image/png"/></manifest><spine/><guide><reference type="cover" href="Text/titlepage.xhtml"/></guide></package>',
        )
        archive.writestr("OPS/Text/titlepage.xhtml", '<html><body><img src="../Images/front.png"/></body></html>')
        archive.writestr("OPS/Images/front.png", image.getvalue())

    cover = BookCoverService(tmp_path / "covers").get_or_create(book_id="guide-page", source_path=source, source_format="epub")

    assert Image.open(cover.path).size == (80, 120)


def test_extracts_a_manifest_image_named_cover_when_the_epub_omits_cover_metadata(tmp_path: Path) -> None:
    image = BytesIO()
    Image.new("RGB", (80, 120), "#4b6552").save(image, format="JPEG")
    source = tmp_path / "nonstandard-cover.epub"
    with ZipFile(source, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OPS/package.opf"/></rootfiles></container>',
        )
        archive.writestr(
            "OPS/package.opf",
            '<package xmlns="http://www.idpf.org/2007/opf"><metadata/><manifest><item id="cover-image" href="images/cover.jpg" media-type="image/jpeg"/></manifest><spine/></package>',
        )
        archive.writestr("OPS/images/cover.jpg", image.getvalue())

    cover = BookCoverService(tmp_path / "covers").get_or_create(book_id="nonstandard", source_path=source, source_format="epub")

    assert Image.open(cover.path).size == (80, 120)


def test_renders_the_first_pdf_page_as_a_cached_cover(tmp_path: Path) -> None:
    source = write_pdf(tmp_path / "book.pdf")
    service = BookCoverService(tmp_path / "covers")

    cover = service.get_or_create(book_id="book", source_path=source, source_format="pdf")

    assert cover.media_type == "image/webp"
    assert cover.path.exists()
    assert Image.open(cover.path).height > Image.open(cover.path).width
