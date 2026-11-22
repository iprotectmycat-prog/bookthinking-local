import json
import subprocess
import sys
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

import pytest

import app.services.epub_parser as epub_parser
from app.services.analysis_providers import ChapterSource, PageSource
from app.services.evidence_catalog import build_evidence_catalogue
from app.services.epub_parser import EpubParser, _node_executable, _xhtml_text


def test_uses_bundled_runtime_node_when_shell_path_has_no_node(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script = tmp_path / "runtime" / "web" / "scripts" / "extract-epub-structure.cjs"
    bundled_node = tmp_path / "runtime" / "bin" / "node"
    script.parent.mkdir(parents=True)
    bundled_node.parent.mkdir(parents=True)
    script.write_text("", encoding="utf-8")
    bundled_node.write_text("", encoding="utf-8")
    monkeypatch.setenv("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")

    assert _node_executable(script) == str(bundled_node)


def write_epub(
    path: Path,
    *,
    include_navigation: bool = True,
    encrypted: bool = False,
    metadata: str = "",
) -> Path:
    with ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
            <container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
              <rootfiles><rootfile full-path="OPS/package.opf" media-type="application/oebps-package+xml"/></rootfiles>
            </container>""",
        )
        if encrypted:
            archive.writestr("META-INF/encryption.xml", "<encryption/>")
        manifest = """
          <item id="chapter-1" href="chapter-1.xhtml" media-type="application/xhtml+xml"/>
          <item id="chapter-2" href="chapter-2.xhtml" media-type="application/xhtml+xml"/>
        """
        nav = ""
        if include_navigation:
            manifest += '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
            nav = """<html xmlns="http://www.w3.org/1999/xhtml"><body><nav epub:type="toc" xmlns:epub="http://www.idpf.org/2007/ops"><ol>
              <li><a href="chapter-1.xhtml">第一章</a></li><li><a href="chapter-2.xhtml">第二章</a></li>
            </ol></nav></body></html>"""
        archive.writestr(
            "OPS/package.opf",
            f"""<package xmlns="http://www.idpf.org/2007/opf" version="3.0"><metadata>{metadata}</metadata><manifest>{manifest}</manifest>
            <spine><itemref idref="chapter-1"/><itemref idref="chapter-2"/></spine></package>""",
        )
        archive.writestr("OPS/chapter-1.xhtml", "<html><body><h1>第一章</h1><p>第一章正文</p></body></html>")
        archive.writestr("OPS/chapter-2.xhtml", "<html><body><h1>第二章</h1><p>第二章正文</p></body></html>")
        if nav:
            archive.writestr("OPS/nav.xhtml", nav)
    return path


def test_prefers_node_bundled_beside_the_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script = tmp_path / "runtime" / "web" / "scripts" / "extract-epub-structure.cjs"
    bundled_node = tmp_path / "runtime" / "bin" / "node"
    script.parent.mkdir(parents=True)
    bundled_node.parent.mkdir(parents=True)
    script.touch()
    bundled_node.touch()
    monkeypatch.setattr(epub_parser.shutil, "which", lambda _name: None)

    assert _node_executable(script) == str(bundled_node)


def test_parses_spine_text_and_navigation_chapters(tmp_path: Path) -> None:
    parsed = EpubParser().parse_epub(write_epub(tmp_path / "sample.epub"))

    assert parsed.pages == ["第一章\n\n第一章正文", "第二章\n\n第二章正文"]
    assert [(chapter.title, chapter.source_start_page, chapter.source_end_page) for chapter in parsed.chapters] == [
        ("第一章", 1, 1),
        ("第二章", 2, 2),
    ]


def test_reads_epub_metadata_without_invoking_structure_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(epub_parser, "_provider_structure", lambda _path: pytest.fail("structure provider called"))
    path = write_epub(
        tmp_path / "legacy.epub",
        metadata="""
          <dc:title xmlns:dc="http://purl.org/dc/elements/1.1/">置身事内</dc:title>
          <dc:creator xmlns:dc="http://purl.org/dc/elements/1.1/">兰小欢</dc:creator>
          <dc:publisher xmlns:dc="http://purl.org/dc/elements/1.1/">上海人民出版社</dc:publisher>
          <dc:date xmlns:dc="http://purl.org/dc/elements/1.1/">2021-08-01</dc:date>
          <dc:identifier xmlns:dc="http://purl.org/dc/elements/1.1/">9787208171336</dc:identifier>
        """,
    )

    metadata = EpubParser().read_metadata(path)

    assert metadata.title == "置身事内"
    assert metadata.authors == ("兰小欢",)
    assert metadata.publisher == "上海人民出版社"
    assert metadata.identifier == "9787208171336"


def test_falls_back_to_native_parser_when_epubjs_runtime_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.CalledProcessError(1, ["node", "extract-epub-structure.cjs"])

    monkeypatch.setattr(subprocess, "run", unavailable)

    parsed = EpubParser().parse_epub(write_epub(tmp_path / "sample.epub"))

    assert parsed.pages == ["第一章\n\n第一章正文", "第二章\n\n第二章正文"]
    assert [chapter.title for chapter in parsed.chapters] == ["第一章", "第二章"]


def test_falls_back_to_full_book_without_navigation(tmp_path: Path) -> None:
    parsed = EpubParser().parse_epub(write_epub(tmp_path / "no-nav.epub", include_navigation=False))

    assert [(chapter.title, chapter.source_start_page, chapter.source_end_page) for chapter in parsed.chapters] == [
        ("全文", 1, 2),
    ]


def write_fragmented_epub(path: Path) -> Path:
    with ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            """<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
              <rootfiles><rootfile full-path="OPS/package.opf"/></rootfiles>
            </container>""",
        )
        archive.writestr(
            "OPS/package.opf",
            """<package xmlns="http://www.idpf.org/2007/opf" version="2.0"><metadata/>
              <manifest>
                <item id="book" href="book.xhtml" media-type="application/xhtml+xml"/>
                <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
              </manifest>
              <spine toc="ncx"><itemref idref="book"/></spine>
            </package>""",
        )
        archive.writestr(
            "OPS/toc.ncx",
            """<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap>
              <navPoint><navLabel><text>扉页</text></navLabel><content src="book.xhtml#title-page"/></navPoint>
              <navPoint><navLabel><text>第1章 革命者</text></navLabel><content src="book.xhtml#chapter-1"/></navPoint>
            </navMap></ncx>""",
        )
        archive.writestr(
            "OPS/book.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"><body>
              <section id="title-page"><p>扉页正文</p></section>
              <section id="chapter-1"><p>第一章正文</p></section>
            </body></html>""",
        )
    return path


def test_verify_script_reports_numbered_chapter_gaps(tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/verify_epub_structure.py", str(write_fragmented_epub(tmp_path / "book.epub"))],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout)["numbered_chapters"] == [1]


def write_chapter_two_only_epub(path: Path) -> Path:
    with ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OPS/package.opf"/></rootfiles></container>',
        )
        archive.writestr(
            "OPS/package.opf",
            """<package xmlns="http://www.idpf.org/2007/opf" version="2.0"><metadata/><manifest>
              <item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>
              <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
            </manifest><spine toc="ncx"><itemref idref="chapter"/></spine></package>""",
        )
        archive.writestr(
            "OPS/toc.ncx",
            """<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap>
              <navPoint><navLabel><text>第2章</text></navLabel><content src="chapter.xhtml"/></navPoint>
            </navMap></ncx>""",
        )
        archive.writestr("OPS/chapter.xhtml", "<html><body><p>第二章正文</p></body></html>")
    return path


def test_verify_script_reports_missing_first_numbered_chapter(tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/verify_epub_structure.py", str(write_chapter_two_only_epub(tmp_path / "chapter-two.epub"))],
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert completed.returncode == 1
    assert payload["numbered_chapters"] == [2]
    assert "missing_numbered_chapter:1" in payload["diagnostics"]


def test_slices_two_chapters_at_fragments_in_one_spine_document(tmp_path: Path) -> None:
    parsed = EpubParser().parse_epub(write_fragmented_epub(tmp_path / "fragmented.epub"))

    assert [chapter.title for chapter in parsed.chapters] == ["扉页", "第1章 革命者"]
    assert [chapter.text for chapter in parsed.chapters] == ["扉页正文", "第一章正文"]
    assert parsed.chapters[1].source_locator == "OPS/book.xhtml#chapter-1"


def write_malformed_fragmented_epub(path: Path) -> Path:
    with ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OPS/package.opf"/></rootfiles></container>',
        )
        archive.writestr(
            "OPS/package.opf",
            """<package xmlns="http://www.idpf.org/2007/opf" version="2.0"><metadata/><manifest>
              <item id="book" href="book.xhtml" media-type="application/xhtml+xml"/>
              <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
            </manifest><spine toc="ncx"><itemref idref="book"/></spine></package>""",
        )
        archive.writestr(
            "OPS/toc.ncx",
            """<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap>
              <navPoint><navLabel><text>第1章</text></navLabel><content src="book.xhtml#chapter-1"/></navPoint>
              <navPoint><navLabel><text>第2章</text></navLabel><content src="book.xhtml#chapter-2"/></navPoint>
            </navMap></ncx>""",
        )
        archive.writestr(
            "OPS/book.xhtml",
            """<html><body><section id="chapter-1"><p>第一章正文 & 未转义符号</p></section>
              <section id="chapter-2"><p>第二章正文</p></section></body></html>""",
        )
    return path


def test_slices_malformed_xhtml_at_declared_fragment_anchors(tmp_path: Path) -> None:
    parsed = EpubParser().parse_epub(write_malformed_fragmented_epub(tmp_path / "malformed.epub"))

    assert [chapter.title for chapter in parsed.chapters] == ["第1章", "第2章"]
    assert [chapter.text for chapter in parsed.chapters] == ["第一章正文 & 未转义符号", "第二章正文"]
    assert parsed.diagnostics == []


def write_numbered_body_heading_epub(path: Path) -> Path:
    with ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OPS/package.opf"/></rootfiles></container>',
        )
        archive.writestr(
            "OPS/package.opf",
            """<package xmlns="http://www.idpf.org/2007/opf" version="2.0"><metadata/><manifest>
              <item id="first" href="first.xhtml" media-type="application/xhtml+xml"/>
              <item id="last" href="last.xhtml" media-type="application/xhtml+xml"/>
              <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
            </manifest><spine toc="ncx"><itemref idref="first"/><itemref idref="last"/></spine></package>""",
        )
        archive.writestr(
            "OPS/toc.ncx",
            """<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap>
              <navPoint><navLabel><text>第1章 开始</text></navLabel><content src="first.xhtml"/></navPoint>
              <navPoint><navLabel><text>历史地位</text></navLabel><content src="last.xhtml"/></navPoint>
            </navMap></ncx>""",
        )
        archive.writestr("OPS/first.xhtml", "<html><body><p>第一章正文</p></body></html>")
        archive.writestr("OPS/last.xhtml", "<html><body><p>第2章</p><p>第二章正文</p></body></html>")
    return path


def test_promotes_body_numbered_heading_when_ncx_title_omits_it(tmp_path: Path) -> None:
    parsed = EpubParser().parse_epub(write_numbered_body_heading_epub(tmp_path / "heading.epub"))

    assert [chapter.title for chapter in parsed.chapters] == ["第1章 开始", "第2章 历史地位"]
    assert parsed.metadata.top_level_chapter_count == 2


def test_does_not_promote_body_numbered_heading_for_epubjs_nav(tmp_path: Path) -> None:
    with ZipFile(tmp_path / "nav-heading.epub", "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OPS/package.opf"/></rootfiles></container>',
        )
        archive.writestr(
            "OPS/package.opf",
            """<package xmlns="http://www.idpf.org/2007/opf" version="3.0"><metadata/><manifest>
              <item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>
              <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
            </manifest><spine><itemref idref="chapter"/></spine></package>""",
        )
        archive.writestr(
            "OPS/nav.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"><body><nav epub:type="toc" xmlns:epub="http://www.idpf.org/2007/ops"><ol>
              <li><a href="chapter.xhtml">NAV 标签</a></li>
            </ol></nav></body></html>""",
        )
        archive.writestr("OPS/chapter.xhtml", "<html><body><p>第2章</p><p>正文</p></body></html>")

    parsed = EpubParser().parse_epub(tmp_path / "nav-heading.epub")

    assert [chapter.title for chapter in parsed.chapters] == ["NAV 标签"]


def test_does_not_promote_body_numbered_heading_for_guide_toc(tmp_path: Path) -> None:
    with ZipFile(tmp_path / "guide-heading.epub", "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OPS/package.opf"/></rootfiles></container>',
        )
        archive.writestr(
            "OPS/package.opf",
            """<package xmlns="http://www.idpf.org/2007/opf" version="2.0"><metadata/><manifest>
              <item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>
              <item id="toc" href="toc.xhtml" media-type="application/xhtml+xml"/>
            </manifest><spine><itemref idref="chapter"/></spine><guide>
              <reference type="toc" href="toc.xhtml"/>
            </guide></package>""",
        )
        archive.writestr(
            "OPS/toc.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"><body><nav epub:type="toc" xmlns:epub="http://www.idpf.org/2007/ops"><ol>
              <li><a href="chapter.xhtml">Guide 标签</a></li>
            </ol></nav></body></html>""",
        )
        archive.writestr("OPS/chapter.xhtml", "<html><body><p>第2章</p><p>正文</p></body></html>")

    parsed = EpubParser().parse_epub(tmp_path / "guide-heading.epub")

    assert [chapter.title for chapter in parsed.chapters] == ["Guide 标签"]


def write_path_and_first_fragment_epub(path: Path) -> Path:
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
              </manifest>
              <spine><itemref idref="chapter"/></spine>
            </package>""",
        )
        archive.writestr(
            "OPS/nav.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"><body><nav epub:type="toc" xmlns:epub="http://www.idpf.org/2007/ops"><ol>
              <li><a href="chapter.xhtml">全文</a></li>
              <li><a href="chapter.xhtml#first-section">第一节</a></li>
            </ol></nav></body></html>""",
        )
        archive.writestr(
            "OPS/chapter.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"><body>
              <section id="first-section"><p>第一节正文</p></section>
              <section id="second-section"><p>第二节正文</p></section>
            </body></html>""",
        )
    return path


def test_path_and_first_fragment_at_document_start_never_create_empty_source_text(tmp_path: Path) -> None:
    parsed = EpubParser().parse_epub(write_path_and_first_fragment_epub(tmp_path / "first-fragment.epub"))

    assert parsed.pages == ["第一节正文\n\n第二节正文"]
    assert [(chapter.title, chapter.source_locator) for chapter in parsed.chapters] == [
        ("全文", "OPS/chapter.xhtml"),
        ("第一节", "OPS/chapter.xhtml#first-section"),
    ]
    assert [chapter.text for chapter in parsed.chapters] == ["第一节正文\n\n第二节正文"] * 2


def write_ncx_and_guide_epub(path: Path) -> Path:
    with ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            """<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
              <rootfiles><rootfile full-path="OPS/package.opf"/></rootfiles>
            </container>""",
        )
        archive.writestr(
            "OPS/package.opf",
            """<package xmlns="http://www.idpf.org/2007/opf" version="2.0"><metadata/>
              <manifest>
                <item id="chapter-1" href="chapter-1.xhtml" media-type="application/xhtml+xml"/>
                <item id="chapter-2" href="chapter-2.xhtml" media-type="application/xhtml+xml"/>
                <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
                <item id="guide-toc" href="guide-toc.xhtml" media-type="application/xhtml+xml"/>
              </manifest>
              <spine toc="ncx"><itemref idref="chapter-1"/><itemref idref="chapter-2"/></spine>
              <guide><reference type="toc" href="guide-toc.xhtml" title="目录"/></guide>
            </package>""",
        )
        archive.writestr(
            "OPS/toc.ncx",
            """<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap>
              <navPoint><navLabel><text>第1章</text></navLabel><content src="chapter-1.xhtml"/></navPoint>
            </navMap></ncx>""",
        )
        archive.writestr(
            "OPS/guide-toc.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"><body><nav>
              <ol><li><a href="chapter-1.xhtml">第1章</a></li><li><a href="chapter-2.xhtml">第2章</a></li></ol>
            </nav></body></html>""",
        )
        archive.writestr("OPS/chapter-1.xhtml", "<html><body><p>第一章正文</p></body></html>")
        archive.writestr("OPS/chapter-2.xhtml", "<html><body><p>第二章正文</p></body></html>")
    return path


def test_guide_toc_adds_chapter_missing_from_ncx(tmp_path: Path) -> None:
    parsed = EpubParser().parse_epub(write_ncx_and_guide_epub(tmp_path / "guide.epub"))

    assert [chapter.title for chapter in parsed.chapters] == ["第1章", "第2章"]
    assert parsed.metadata.top_level_chapter_count == 2


def write_nav_and_ncx_epub(path: Path) -> Path:
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
                <item id="first" href="first.xhtml" media-type="application/xhtml+xml"/>
                <item id="second" href="second.xhtml" media-type="application/xhtml+xml"/>
                <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
                <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
              </manifest>
              <spine toc="ncx"><itemref idref="first"/><itemref idref="second"/></spine>
            </package>""",
        )
        archive.writestr(
            "OPS/nav.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"><body><nav epub:type="toc" xmlns:epub="http://www.idpf.org/2007/ops"><ol>
              <li><a href="first.xhtml">来自 NAV</a></li>
            </ol></nav></body></html>""",
        )
        archive.writestr(
            "OPS/toc.ncx",
            """<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap>
              <navPoint><navLabel><text>来自 NCX</text></navLabel><content src="second.xhtml"/></navPoint>
            </navMap></ncx>""",
        )
        archive.writestr("OPS/first.xhtml", "<html><body><p>NAV 正文</p></body></html>")
        archive.writestr("OPS/second.xhtml", "<html><body><p>NCX 正文</p></body></html>")
    return path


def test_provider_cumulatively_returns_nav_and_ncx_entries(tmp_path: Path) -> None:
    parsed = EpubParser().parse_epub(write_nav_and_ncx_epub(tmp_path / "nav-and-ncx.epub"))

    assert [chapter.title for chapter in parsed.chapters] == ["来自 NAV", "来自 NCX"]


def write_legacy_ncx_epub(path: Path) -> Path:
    with ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            "<container xmlns=\"urn:oasis:names:tc:opendocument:xmlns:container\"><rootfiles><rootfile full-path=\"OPS/package.opf\"/></rootfiles></container>",
        )
        archive.writestr(
            "OPS/package.opf",
            """<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
              <manifest>
                <item id="first" href="first.xhtml" media-type="application/xhtml+xml"/>
                <item id="second" href="second.xhtml" media-type="application/xhtml+xml"/>
                <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
              </manifest>
              <spine toc="ncx"><itemref idref="first"/><itemref idref="second"/></spine>
            </package>""",
        )
        archive.writestr(
            "OPS/toc.ncx",
            """<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap>
              <navPoint><navLabel><text>第一章</text></navLabel><content src="first.xhtml"/></navPoint>
              <navPoint><navLabel><text>第二章</text></navLabel><content src="second.xhtml"/></navPoint>
            </navMap></ncx>""",
        )
        archive.writestr("OPS/first.xhtml", "<html><body><p>第一章正文</p></body></html>")
        archive.writestr("OPS/second.xhtml", "<html><body><p>第二章正文</p></body></html>")
    return path


def test_legacy_missing_metadata_falls_back_to_whole_book_without_ncx_reconciliation(tmp_path: Path) -> None:
    parsed = EpubParser().parse_epub(write_legacy_ncx_epub(tmp_path / "legacy-ncx.epub"))

    assert [(chapter.title, chapter.text) for chapter in parsed.chapters] == [
        ("全文", "第一章正文\n\n第二章正文"),
    ]


def write_nested_ncx_epub(path: Path) -> Path:
    """An EPUB 2 shaped like a real trade book: parts, chapters, repeated sections."""
    with ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
            <container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
              <rootfiles><rootfile full-path="content.opf" media-type="application/oebps-package+xml"/></rootfiles>
            </container>""",
        )
        documents = {
            "cover.xhtml": "封面",
            "copyright.xhtml": "版权所有",
            "preface.xhtml": "前言正文" * 40,
            "part1.xhtml": "上篇导语",
            "ch1.xhtml": "第一章正文" * 40,
            "ch1-s1.xhtml": "第一节正文" * 40,
            "ch1-end.xhtml": "第一章结语正文" * 20,
            "ch2.xhtml": "第二章正文" * 40,
            "ch2-end.xhtml": "第二章结语正文" * 20,
            "afterword.xhtml": "结束语正文" * 30,
            "biblio.xhtml": "参考文献条目" * 400,
        }
        items = "".join(
            f'<item id="{name.split(".")[0]}" href="{name}" media-type="application/xhtml+xml"/>'
            for name in documents
        )
        itemrefs = "".join(f'<itemref idref="{name.split(".")[0]}"/>' for name in documents)
        archive.writestr(
            "content.opf",
            f"""<package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/"
                 version="2.0" unique-identifier="uuid_id">
              <metadata xmlns:opf="http://www.idpf.org/2007/opf">
                <dc:title>示范书名 一个副标题【出版社推荐语，某某某联袂推荐】</dc:title>
                <dc:creator opf:role="aut">某作者</dc:creator>
                <dc:contributor opf:role="bkp">calibre</dc:contributor>
                <dc:publisher>示范出版社</dc:publisher>
                <dc:language>zh</dc:language>
                <dc:date>2021-08-01T00:00:00+00:00</dc:date>
                <dc:identifier opf:scheme="MOBI-ASIN">asin-should-be-ignored</dc:identifier>
                <dc:identifier id="uuid_id">urn:uuid:the-real-one</dc:identifier>
              </metadata>
              <manifest>{items}<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/></manifest>
              <spine toc="ncx">{itemrefs}</spine>
              <guide><reference type="text" href="part1.xhtml" title="开始"/></guide>
            </package>""",
        )
        archive.writestr(
            "toc.ncx",
            """<?xml version="1.0" encoding="utf-8"?>
            <ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
              <navMap>
                <navPoint><navLabel><text>版权页</text></navLabel><content src="copyright.xhtml"/></navPoint>
                <navPoint><navLabel><text>前言 从头说起</text></navLabel><content src="preface.xhtml"/></navPoint>
                <navPoint><navLabel><text>上篇 微观机制</text></navLabel><content src="part1.xhtml"/>
                  <navPoint><navLabel><text>第一章 权力与事务</text></navLabel><content src="ch1.xhtml"/>
                    <navPoint><navLabel><text>第一节 治理特点</text></navLabel><content src="ch1-s1.xhtml"/></navPoint>
                    <navPoint><navLabel><text>结语</text></navLabel><content src="ch1-end.xhtml"/></navPoint>
                  </navPoint>
                  <navPoint><navLabel><text>第二章 财税行为</text></navLabel><content src="ch2.xhtml"/>
                    <navPoint><navLabel><text>结语</text></navLabel><content src="ch2-end.xhtml"/></navPoint>
                  </navPoint>
                </navPoint>
                <navPoint><navLabel><text>结束语</text></navLabel><content src="afterword.xhtml"/></navPoint>
                <navPoint><navLabel><text>参考文献</text></navLabel><content src="biblio.xhtml"/></navPoint>
              </navMap>
            </ncx>""",
        )
        for name, body in documents.items():
            archive.writestr(name, f"<html><body><p>{body}</p></body></html>")
    return path


def test_keeps_navigation_depth_and_parent_from_nested_ncx(tmp_path: Path) -> None:
    parsed = EpubParser().parse_epub(write_nested_ncx_epub(tmp_path / "nested.epub"))
    by_title = {(chapter.title, chapter.parent_title): chapter for chapter in parsed.chapters}

    assert by_title[("上篇 微观机制", None)].depth == 0
    assert by_title[("第一章 权力与事务", "上篇 微观机制")].depth == 1
    assert by_title[("第一节 治理特点", "第一章 权力与事务")].depth == 2


def test_classifies_relative_navigation_depth_from_the_parent_kind() -> None:
    """Depth 1 means a chapter below a part, but a section below a chapter."""
    assert epub_parser._nav_kind(
        "第一章 权力与事务",
        depth=1,
        start=2,
        body_start=1,
        text_length=2_000,
        parent_kind="part",
    ) == "chapter"
    assert epub_parser._nav_kind(
        "20世纪80年代，日本的国际地位逐步上升",
        depth=1,
        start=2,
        body_start=1,
        text_length=2_000,
        parent_kind="chapter",
    ) == "section"


def test_marks_a_parent_sharing_its_first_child_source_as_outline_only() -> None:
    parent = epub_parser.EpubChapterDraft(
        title="第一章 日本人没有察觉到泡沫经济的崩溃",
        source_start_page=1,
        source_end_page=1,
        text="正文",
        nav_kind="chapter",
        source_locator="text00004.html#a1",
        text_sha256="same",
    )
    child = epub_parser.EpubChapterDraft(
        title="20世纪80年代，日本的国际地位逐步上升",
        source_start_page=1,
        source_end_page=1,
        text="正文",
        depth=1,
        parent_title=parent.title,
        nav_kind="section",
        source_locator="text00004.html#a1",
        text_sha256="same",
    )

    resolved = epub_parser._assign_analysis_roles([parent, child])

    assert resolved[0].analysis_role == "outline_only"
    assert resolved[1].analysis_role == "analysis_unit"


def test_normalized_parent_title_still_drives_child_hierarchy() -> None:
    segments = [
        epub_parser.SourceSegment("chapter.xhtml", "parent", "第2章\n\n父级正文", 1, 0),
        epub_parser.SourceSegment("chapter.xhtml", "child", "子节正文", 1, 1),
    ]
    links = [
        epub_parser.NavigationLink("历史地位", "chapter.xhtml", "parent", 0, None, "epubjs:ncx"),
        epub_parser.NavigationLink("形成原因", "chapter.xhtml", "child", 1, "历史地位", "epubjs:ncx"),
    ]
    chapters = epub_parser._chapters_from_links(
        segments,
        links,
        body_start=1,
        location_positions={("chapter.xhtml", "parent"): 1, ("chapter.xhtml", "child"): 2},
    )

    assert chapters[0].title == "第2章 历史地位"
    assert chapters[1].parent_title == "第2章 历史地位"
    assert chapters[1].nav_kind == "section"


def test_repeated_section_titles_are_unique_once_scoped_by_parent(tmp_path: Path) -> None:
    """Regression: flat titles made "结语" collide and rejected chapter confirmation."""
    parsed = EpubParser().parse_epub(write_nested_ncx_epub(tmp_path / "nested.epub"))
    closings = [chapter for chapter in parsed.chapters if chapter.title == "结语"]

    assert len(closings) == 2
    assert {chapter.parent_title for chapter in closings} == {"第一章 权力与事务", "第二章 财税行为"}


def test_separates_nested_closing_section_from_book_level_afterword(tmp_path: Path) -> None:
    parsed = EpubParser().parse_epub(write_nested_ncx_epub(tmp_path / "nested.epub"))
    kinds = {chapter.title: chapter.nav_kind for chapter in parsed.chapters}

    assert kinds["结语"] == "section"
    assert kinds["结束语"] == "back_matter"


def test_marks_pages_before_the_guide_landmark_as_front_matter(tmp_path: Path) -> None:
    parsed = EpubParser().parse_epub(write_nested_ncx_epub(tmp_path / "nested.epub"))
    kinds = {chapter.title: chapter.nav_kind for chapter in parsed.chapters}

    assert kinds["版权页"] == "front_matter"
    assert kinds["前言 从头说起"] == "chapter"
    assert kinds["上篇 微观机制"] == "part"


def test_records_publisher_boundary_as_high_confidence_structural_evidence(tmp_path: Path) -> None:
    parsed = EpubParser().parse_epub(write_nested_ncx_epub(tmp_path / "nested.epub"))
    by_title = {chapter.title: chapter for chapter in parsed.chapters}

    assert (
        by_title["前言 从头说起"].structural_role,
        by_title["前言 从头说起"].role_source,
        by_title["前言 从头说起"].role_confidence,
    ) == ("front_matter", "publisher_landmark", "high")
    assert (
        by_title["上篇 微观机制"].structural_role,
        by_title["上篇 微观机制"].role_source,
        by_title["上篇 微观机制"].role_confidence,
    ) == ("body", "publisher_landmark", "high")


def test_keeps_title_only_back_matter_as_medium_confidence_fallback(tmp_path: Path) -> None:
    parsed = EpubParser().parse_epub(write_nested_ncx_epub(tmp_path / "nested.epub"))
    afterword = next(chapter for chapter in parsed.chapters if chapter.title == "结束语")

    assert (afterword.structural_role, afterword.role_source, afterword.role_confidence) == (
        "back_matter",
        "title_fallback",
        "medium",
    )


def test_treats_preface_title_as_front_matter_even_after_body_landmark() -> None:
    decision = epub_parser._structural_role_decision(
        title="序言",
        start=5,
        body_start=5,
        nav_kind="chapter",
    )

    assert (decision.role, decision.source, decision.confidence) == (
        "front_matter",
        "title_fallback",
        "medium",
    )


def test_reconciles_conflicting_landmark_with_content_signal_for_a_collection_volume() -> None:
    volume = epub_parser.EpubChapterDraft(
        "魔鬼经济学1：揭示隐藏在表象之下的真实世界",
        3,
        20,
        "第一册正文",
        nav_kind="plain",
        in_body=True,
        structural_role="front_matter",
        role_source="publisher_landmark",
        role_confidence="high",
    )

    classified = epub_parser._reconcile_structural_roles([volume])

    assert (
        classified[0].structural_role,
        classified[0].role_source,
        classified[0].role_confidence,
        classified[0].in_body,
    ) == ("body", "content_signal", "medium", True)


def test_preserves_body_subtree_before_first_numbered_chapter() -> None:
    chapters = [
        epub_parser.EpubChapterDraft(
            "前 言", 1, 1, "前言", structural_role="body", role_source="publisher_landmark"
        ),
        epub_parser.EpubChapterDraft(
            "导论 何为结构思考力?",
            2,
            2,
            "导论",
            nav_kind="chapter",
            structural_role="body",
            role_source="publisher_landmark",
        ),
        epub_parser.EpubChapterDraft(
            "第一节 Why——结构思考力的作用非凡",
            3,
            3,
            "第一节",
            depth=1,
            parent_title="导论 何为结构思考力?",
            nav_kind="section",
            structural_role="body",
            role_source="publisher_landmark",
        ),
        epub_parser.EpubChapterDraft(
            "第一章 明确理念打基础", 4, 4, "第一章", nav_kind="chapter", structural_role="body"
        ),
        epub_parser.EpubChapterDraft(
            "第二章 基于目标定主题", 5, 5, "第二章", nav_kind="chapter", structural_role="body"
        ),
    ]

    classified = epub_parser._reconcile_structural_roles(chapters)

    assert [chapter.structural_role for chapter in classified] == [
        "front_matter",
        "body",
        "body",
        "body",
        "body",
    ]


def test_local_numbered_parts_do_not_define_a_global_body_range() -> None:
    chapters = [
        epub_parser.EpubChapterDraft("坟", 1, 1, "正文", structural_role="body"),
        epub_parser.EpubChapterDraft("第一篇 史家对于小说之著录及论述", 2, 2, "正文", structural_role="body"),
        epub_parser.EpubChapterDraft("第二篇 神话与传说", 3, 3, "正文", structural_role="body"),
        epub_parser.EpubChapterDraft("故事新编", 4, 4, "正文", structural_role="body"),
    ]

    classified = epub_parser._reconcile_structural_roles(chapters)

    assert [chapter.structural_role for chapter in classified] == ["body", "body", "body", "body"]


def test_classifies_explicit_non_body_titles_without_a_global_body_range() -> None:
    chapters = [
        epub_parser.EpubChapterDraft("中文版序言 书中自有黄金屋", 1, 1, "序言"),
        epub_parser.EpubChapterDraft("驳辞：芒格论巴菲特", 2, 2, "驳辞"),
        epub_parser.EpubChapterDraft("导读", 3, 3, "导读"),
        epub_parser.EpubChapterDraft("查理·芒格的推荐书目", 4, 4, "书目"),
        epub_parser.EpubChapterDraft("查理·芒格年谱", 5, 5, "年谱"),
    ]

    classified = epub_parser._reconcile_structural_roles(chapters)

    assert [chapter.structural_role for chapter in classified] == [
        "front_matter",
        "front_matter",
        "front_matter",
        "back_matter",
        "back_matter",
    ]
    assert [chapter.role_source for chapter in classified] == ["title_fallback"] * 5
    assert [chapter.in_body for chapter in classified] == [True] * 5


def test_classifies_common_publisher_front_and_back_matter_title_variants() -> None:
    chapters = [
        epub_parser.EpubChapterDraft("阅读提示", 1, 1, "提示"),
        epub_parser.EpubChapterDraft("序 财报是用来证伪的", 2, 2, "序"),
        epub_parser.EpubChapterDraft("理想国译丛序", 3, 3, "译丛序"),
        epub_parser.EpubChapterDraft("图书在版编目（CIP）数据", 4, 4, "CIP"),
        epub_parser.EpubChapterDraft("致《失控》中文版的读者们", 5, 5, "致读者"),
        epub_parser.EpubChapterDraft("“失控”的协作与进化——翻译后记", 6, 6, "后记"),
        epub_parser.EpubChapterDraft("理想国译丛", 7, 7, "译丛"),
        epub_parser.EpubChapterDraft("封底", 8, 8, "封底"),
        epub_parser.EpubChapterDraft("自我分析：你的财务状况如何", 9, 9, "正文"),
    ]

    classified = epub_parser._reconcile_structural_roles(chapters)

    assert [chapter.structural_role for chapter in classified] == [
        "front_matter",
        "front_matter",
        "front_matter",
        "front_matter",
        "front_matter",
        "back_matter",
        "back_matter",
        "back_matter",
        "unknown",
    ]


def test_inherits_non_body_role_from_declared_parent() -> None:
    parent = epub_parser.EpubChapterDraft(
        "后记",
        1,
        1,
        "后记正文",
        structural_role="back_matter",
        role_source="title_fallback",
        role_confidence="medium",
    )
    child = epub_parser.EpubChapterDraft(
        "专家推荐",
        2,
        2,
        "推荐正文",
        depth=1,
        parent_title="后记",
        structural_role="unknown",
        role_source="unknown",
        role_confidence="low",
    )

    inherited = epub_parser._inherit_structural_roles([parent, child])

    assert (
        inherited[1].structural_role,
        inherited[1].role_source,
        inherited[1].role_confidence,
    ) == ("back_matter", "parent_inherited", "medium")


def test_leaves_ambiguous_navigation_entry_unknown(tmp_path: Path) -> None:
    parsed = EpubParser().parse_epub(write_nav_and_ncx_epub(tmp_path / "ambiguous.epub"))
    ambiguous = next(chapter for chapter in parsed.chapters if chapter.title == "来自 NAV")

    assert (ambiguous.structural_role, ambiguous.role_source, ambiguous.role_confidence) == (
        "unknown",
        "unknown",
        "low",
    )


def test_excludes_long_bibliography_from_body_content(tmp_path: Path) -> None:
    """A bibliography outweighs every chapter, so length must not promote it to body."""
    parsed = EpubParser().parse_epub(write_nested_ncx_epub(tmp_path / "nested.epub"))
    bibliography = next(chapter for chapter in parsed.chapters if chapter.title == "参考文献")

    assert len(bibliography.text) > max(
        len(chapter.text) for chapter in parsed.chapters if chapter.nav_kind == "chapter"
    )
    assert bibliography.nav_kind == "back_matter"
    assert bibliography.in_body is False


def test_keeps_spine_pages_that_navigation_never_references(tmp_path: Path) -> None:
    parsed = EpubParser().parse_epub(write_nested_ncx_epub(tmp_path / "nested.epub"))
    lead = parsed.chapters[0]

    assert (lead.title, lead.source_start_page, lead.nav_kind) == ("封面与前置页", 1, "front_matter")
    assert "封面" in lead.text


def test_reads_metadata_and_splits_marketing_title(tmp_path: Path) -> None:
    metadata = EpubParser().parse_epub(write_nested_ncx_epub(tmp_path / "nested.epub")).metadata

    assert (metadata.title, metadata.subtitle) == ("示范书名", "一个副标题")
    assert metadata.authors == ("某作者",)
    assert metadata.publisher == "示范出版社"
    assert metadata.identifier == "urn:uuid:the-real-one"
    assert metadata.spec_version == "2.0"


def test_counts_numbered_chapters_separately_from_analysis_units(tmp_path: Path) -> None:
    metadata = EpubParser().parse_epub(write_nested_ncx_epub(tmp_path / "nested.epub")).metadata

    assert metadata.top_level_chapter_count == 2
    # The part heading remains in the outline but no longer consumes a model call.
    assert metadata.analysis_unit_count == 6


def test_rejects_encrypted_epub(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="不支持受 DRM 保护的 EPUB 文件"):
        EpubParser().parse_epub(write_epub(tmp_path / "encrypted.epub", encrypted=True))


def test_ignores_epub_image_and_svg_content() -> None:
    content = b"<html><body><p>\xe4\xbf\x9d\xe7\x95\x99\xe6\xad\xa3\xe6\x96\x87\xe3\x80\x82</p><figure><img alt='image label'/><svg><text>diagram words</text></svg></figure><p>\xe7\xbb\xa7\xe7\xbb\xad\xe6\xad\xa3\xe6\x96\x87\xe3\x80\x82</p></body></html>"

    assert _xhtml_text(content) == "保留正文。\n\n继续正文。"


def test_xhtml_block_structure_produces_real_catalogue_paragraphs_without_splitting_inline_text() -> None:
    content = """<html xmlns="http://www.w3.org/1999/xhtml"><body>
      <p>第一段有<strong>行内强调</strong>和收尾。</p>
      <div>第二段由<span>行内容器</span>组成。</div>
      <ul><li>列表第一项含<em>行内文字</em>。</li><li>列表第二项。</li></ul>
    </body></html>""".encode()

    text = _xhtml_text(content)
    chapter = ChapterSource(
        id=16,
        book_id="book-1",
        title="第一节 分税制改革",
        source_start_page=18,
        source_end_page=18,
        text=text,
        pages=[PageSource(page_number=18, text=text)],
    )
    catalogue = build_evidence_catalogue(chapter, prefix="e")

    assert text == (
        "第一段有行内强调和收尾。\n\n"
        "第二段由行内容器组成。\n\n"
        "列表第一项含行内文字。\n\n"
        "列表第二项。"
    )
    assert [block.paragraph_id for block in catalogue.blocks] == ["ep1", "ep2", "ep3", "ep4"]
    assert [block.quote for block in catalogue.blocks] == [
        "第一段有行内强调和收尾。",
        "第二段由行内容器组成。",
        "列表第一项含行内文字。",
        "列表第二项。",
    ]


def test_xhtml_br_preserves_line_break_inside_one_catalogue_paragraph() -> None:
    content = b'<html xmlns="http://www.w3.org/1999/xhtml"><body><p>A<br/>B</p><p>C</p></body></html>'

    text = _xhtml_text(content)
    chapter = ChapterSource(
        id=16,
        book_id="book-1",
        title="第一节 分税制改革",
        source_start_page=18,
        source_end_page=18,
        text=text,
        pages=[PageSource(page_number=18, text=text)],
    )
    catalogue = build_evidence_catalogue(chapter, prefix="e")

    assert text == "A\nB\n\nC"
    assert [(block.quote, block.paragraph_id) for block in catalogue.blocks] == [
        ("A\nB", "ep1"),
        ("C", "ep2"),
    ]


def test_extracts_text_when_xhtml_uses_standard_html_entities() -> None:
    content = "<html><body><p>保留&nbsp;空格与&copy;符号。</p></body></html>".encode()

    assert _xhtml_text(content) == "保留\u00a0空格与©符号。"


def test_falls_back_to_tolerant_html_parsing_for_malformed_xhtml() -> None:
    content = "<html><body><p>正文甲 & 未转义符号</p><script>忽略</script><p>正文乙</p></body></html>".encode()

    assert _xhtml_text(content) == "正文甲 & 未转义符号\n\n正文乙"


def test_tolerant_html_br_preserves_line_break_inside_one_catalogue_paragraph() -> None:
    content = b"<html><body><p>A<br>B & bad</p><p>C</p></body></html>"

    text = _xhtml_text(content)
    chapter = ChapterSource(
        id=16,
        book_id="book-1",
        title="第一节 分税制改革",
        source_start_page=18,
        source_end_page=18,
        text=text,
        pages=[PageSource(page_number=18, text=text)],
    )
    catalogue = build_evidence_catalogue(chapter, prefix="e")

    assert text == "A\nB & bad\n\nC"
    assert [(block.quote, block.paragraph_id) for block in catalogue.blocks] == [
        ("A\nB & bad", "ep1"),
        ("C", "ep2"),
    ]


def test_tolerant_html_parser_does_not_drop_text_after_unclosed_img() -> None:
    content = b"<html><body><p>A & bad <img alt=x>B</p><p>C</p></body></html>"

    assert _xhtml_text(content) == "A & bad B\n\nC"


def test_tolerant_html_parser_excludes_closed_svg_image_contents() -> None:
    content = b"<html><body><p>A & bad</p><image><title>diagram words</title></image><p>B</p></body></html>"

    assert _xhtml_text(content) == "A & bad\n\nB"


def test_nested_chapter_closing_remains_body_but_book_afterword_does_not(tmp_path: Path) -> None:
    parsed = EpubParser().parse_epub(write_nested_ncx_epub(tmp_path / "nested-role.epub"))
    closings = [c for c in parsed.chapters if c.title == "结语"]
    assert all(c.structural_role == "body" and c.in_body for c in closings)
    afterword = next(c for c in parsed.chapters if c.title == "结束语")
    assert afterword.structural_role == "back_matter"
