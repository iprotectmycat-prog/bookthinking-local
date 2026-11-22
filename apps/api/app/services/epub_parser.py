from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import dataclass, replace
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from posixpath import dirname, join, normpath
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from app.services.pypdf_parser import BookMetadata, ChapterDraft, ParsedBook


class InvalidEpubError(ValueError):
    pass


@dataclass(frozen=True)
class NavigationLink:
    """One navigation entry, carrying the hierarchy the publisher actually declared."""

    title: str
    path: str
    fragment: str | None
    depth: int
    parent_title: str | None
    source: str


@dataclass(frozen=True)
class SourceSegment:
    path: str
    fragment: str | None
    text: str
    spine_position: int
    dom_position: int

    @property
    def locator(self) -> str:
        return f"{self.path}#{self.fragment}" if self.fragment else self.path


@dataclass(frozen=True)
class StructuralRoleDecision:
    role: str
    source: str
    confidence: str


@dataclass(frozen=True)
class EpubChapterDraft(ChapterDraft):
    source_locator: str | None = None
    text_sha256: str | None = None


CN_NUMBER = r"[一二三四五六七八九十百千零〇\d]+"
FRONT_MATTER_EXACT = re.compile(r"^(封面|书名页|版权页|目录|扉页|献词|题献|出版说明|内容简介|作者简介)$")
FRONT_MATTER_PREFIX = re.compile(r"^(前言|序言|自序|他序|译序|推荐序)(\s|[:：]|$)")
BACK_MATTER_EXACT = re.compile(r"^(参考文献|注释|注解|索引|后记|致谢|鸣谢|结束语|结语|出版后记|译后记|跋)$")
BACK_MATTER_PREFIX = re.compile(rf"^(附录|附表|附图|参考文献|注释)(\s|{CN_NUMBER}|[:：])")
FRONT_MATTER_COMPACT_PREFIX = re.compile(
    rf"^(?:(?:中文版|英文版|修订版|再版|新版|第{CN_NUMBER}版))?(?:前言|序言|自序|他序|译序|推荐序|驳辞|导读|阅读提示|图书在版编目)"
)
FRONT_MATTER_COMPACT_SUFFIX = re.compile(r"(?:译丛序|丛书序)$")
FRONT_MATTER_READER_NOTE = re.compile(r"^致(?:《[^》]+》)?(?:中文版)?(?:的)?读者")
FRONT_MATTER_BARE_PREFACE = re.compile(r"^序(?:[：:]|\s|$)")
BACK_MATTER_COMPACT_SUFFIX = re.compile(r"(?:推荐书目|书目|年谱|后记|译丛|丛书|封底)$")
NUMBERED_CHAPTER = re.compile(rf"^(第{CN_NUMBER}章|Chapter\s)")
NUMBERED_HEADING = re.compile(rf"^(第{CN_NUMBER}章|Chapter\s+\d+)\s*$", re.IGNORECASE)
PART_PREFIX = re.compile(rf"^(上篇|中篇|下篇|上册|下册|第{CN_NUMBER}(部分|篇|卷)|Part\s)")
CHAPTER_PREFIX = re.compile(rf"^(前言|序言|自序|他序|导论|引言|绪论|第{CN_NUMBER}章|Chapter\s)")
SECTION_PREFIX = re.compile(rf"^第{CN_NUMBER}节")
SECTION_EXACT = re.compile(r"^(扩展阅读|延伸阅读|小结|本章小结|思考题)$")
MARKETING_SUFFIX = re.compile(r"\s*[【（(\[].*$")
SUBTITLE_SEPARATOR = re.compile(r"[ \u3000]+|[:：]|\s*[—–]{1,2}\s*")
FRONT_MATTER_TEXT_LIMIT = 800
_PROVIDER_UNAVAILABLE = object()


class EpubParser:
    """Read standard, non-encrypted EPUBs without extracting their archive members.

    Structure comes from what the publisher declared (metadata, navigation nesting,
    guide landmarks). Title heuristics only resolve what those signals leave ambiguous.
    """

    def read_metadata(self, path: Path) -> BookMetadata:
        """Read only publisher-declared OPF metadata for a stored legacy EPUB."""
        try:
            with ZipFile(path) as archive:
                if archive.read("mimetype") != b"application/epub+zip":
                    raise InvalidEpubError("无法读取 EPUB 文件")
                if "META-INF/encryption.xml" in archive.namelist():
                    raise InvalidEpubError("不支持受 DRM 保护的 EPUB 文件")
                package_path = _package_path(archive)
                return _book_metadata(_read_xml(archive, package_path), [])
        except InvalidEpubError:
            raise
        except (BadZipFile, KeyError, ElementTree.ParseError, ValueError) as error:
            raise InvalidEpubError("无法读取 EPUB 文件") from error

    def parse_epub(self, path: Path) -> ParsedBook:
        try:
            with ZipFile(path) as archive:
                if archive.read("mimetype") != b"application/epub+zip":
                    raise InvalidEpubError("无法读取 EPUB 文件")
                if "META-INF/encryption.xml" in archive.namelist():
                    raise InvalidEpubError("不支持受 DRM 保护的 EPUB 文件")

                package_path = _package_path(archive)
                package = _read_xml(archive, package_path)
                manifest, spine = _manifest_and_spine(package, package_path)
                provider_result = _provider_structure(path)
                provider = provider_result if isinstance(provider_result, dict) else None
                provider_spine = (
                    _provider_spine(provider, spine)
                    if provider is not None
                    else [(item_path, archive.read(item_path).decode("utf-8", errors="replace")) for item_path in spine]
                )
                links = _navigation_links_for(
                    archive,
                    package,
                    package_path,
                    provider,
                    native_fallback=provider_result is _PROVIDER_UNAVAILABLE,
                )
                segments, diagnostics, location_positions = _segments_from_spine(provider_spine, links)
                pages = [segment.text for segment in segments]
                if not "".join(pages).strip():
                    raise InvalidEpubError("EPUB 未提取到可用文本")

                body_start = _body_start_position(package, package_path, spine)
                chapters = _chapters_from_links(segments, links, body_start, location_positions) or _whole_book(segments)
                chapters = _reconcile_structural_roles(chapters)
                chapters = _inherit_structural_roles(chapters)
                chapters = _assign_analysis_roles(chapters)
                return ParsedBook(
                    pages=pages,
                    chapters=chapters,
                    metadata=_book_metadata(package, chapters),
                    diagnostics=diagnostics,
                )
        except InvalidEpubError:
            raise
        except (BadZipFile, KeyError, ElementTree.ParseError, subprocess.SubprocessError, ValueError) as error:
            raise InvalidEpubError("无法读取 EPUB 文件") from error


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _package_path(archive: ZipFile) -> str:
    container = _read_xml(archive, "META-INF/container.xml")
    rootfile = next((node for node in container.iter() if _local_name(node.tag) == "rootfile"), None)
    if rootfile is None or not rootfile.get("full-path"):
        raise InvalidEpubError("无法读取 EPUB 文件")
    return _resolve_path("", rootfile.attrib["full-path"])


def _read_xml(archive: ZipFile, member: str) -> ElementTree.Element:
    return ElementTree.fromstring(archive.read(member))


def _resolve_path(source_path: str, href: str) -> str:
    target = href.split("#", 1)[0].strip()
    if not target:
        return source_path
    resolved = normpath(join(dirname(source_path), target)).lstrip("/")
    if resolved == ".." or resolved.startswith("../"):
        raise InvalidEpubError("无法读取 EPUB 文件")
    return resolved


def _resolve_href(source_path: str, href: str) -> tuple[str, str | None]:
    target, separator, fragment = href.strip().partition("#")
    return _resolve_path(source_path, target), (fragment or None) if separator else None


def _provider_structure(epub_path: Path) -> dict[str, object] | object | None:
    script = Path(__file__).resolve().parents[3] / "web" / "scripts" / "extract-epub-structure.cjs"
    if not script.is_file():
        return _PROVIDER_UNAVAILABLE
    try:
        result = subprocess.run(
            [_node_executable(script), str(script)],
            input=str(epub_path.resolve()),
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
    except (InvalidEpubError, OSError, subprocess.SubprocessError):
        # epub.js improves publisher-structure fidelity, but the native parser is
        # deliberately complete enough to keep imports working without that helper.
        return _PROVIDER_UNAVAILABLE
    if not result.stdout.strip():
        # epub.js leaves ``ready`` pending for legacy files that omit the required
        # metadata element. Preserve the tolerant importer behaviour for those files.
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise InvalidEpubError("无法读取 EPUB 文件") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("spine"), list) or not isinstance(payload.get("navigation"), list):
        raise InvalidEpubError("无法读取 EPUB 文件")
    return payload


def _node_executable(script: Path) -> str:
    bundled_node = script.parents[2] / "bin" / "node"
    if bundled_node.is_file():
        return str(bundled_node)
    system_node = shutil.which("node")
    if system_node is None:
        raise InvalidEpubError("EPUB 结构解析组件不可用")
    return system_node


def _provider_spine(provider: dict[str, object], expected_spine: list[str]) -> list[tuple[str, str]]:
    entries = provider["spine"]
    if not isinstance(entries, list):
        raise InvalidEpubError("无法读取 EPUB 文件")
    spine: list[tuple[str, str]] = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not isinstance(entry.get("xhtml"), str):
            raise InvalidEpubError("无法读取 EPUB 文件")
        spine.append((entry["path"], entry["xhtml"]))
    if [path for path, _ in spine] != expected_spine:
        raise InvalidEpubError("无法读取 EPUB 文件")
    return spine


def _manifest_and_spine(package: ElementTree.Element, package_path: str) -> tuple[dict[str, dict[str, str]], list[str]]:
    manifest_node = next((node for node in package.iter() if _local_name(node.tag) == "manifest"), None)
    spine_node = next((node for node in package.iter() if _local_name(node.tag) == "spine"), None)
    if manifest_node is None or spine_node is None:
        raise InvalidEpubError("无法读取 EPUB 文件")

    manifest: dict[str, dict[str, str]] = {}
    for item in manifest_node:
        if _local_name(item.tag) != "item" or not item.get("id") or not item.get("href"):
            continue
        manifest[item.attrib["id"]] = {
            "path": _resolve_path(package_path, item.attrib["href"]),
            "media_type": item.get("media-type", ""),
            "properties": item.get("properties", ""),
        }

    spine: list[str] = []
    for itemref in spine_node:
        if _local_name(itemref.tag) != "itemref" or not itemref.get("idref"):
            continue
        item = manifest.get(itemref.attrib["idref"])
        if item and item["media_type"] in {"application/xhtml+xml", "text/html"}:
            spine.append(item["path"])
    if not spine:
        raise InvalidEpubError("EPUB 缺少可读取的章节内容")
    return manifest, spine


def _xhtml_text(content: bytes) -> str:
    decoded = content.decode("utf-8", errors="replace")
    try:
        root = ElementTree.fromstring(unescape(decoded))
    except ElementTree.ParseError:
        parser = _TolerantTextExtractor()
        parser.feed(decoded)
        parser.close()
        parser.finish()
        return "\n\n".join(parser.text)
    return "\n\n".join(_text_blocks(root))


class _TolerantTextExtractor(HTMLParser):
    excluded_tags = {"head", "script", "style", "figure", "picture", "img", "image", "svg"}
    void_excluded_tags = {"img"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self.current: list[str] = []
        self.anchor_positions: dict[str, int] = {}
        self.excluded_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        if normalized in self.void_excluded_tags:
            return
        if normalized in self.excluded_tags:
            self.excluded_depth += 1
        elif not self.excluded_depth:
            identifier = dict(attrs).get("id")
            if identifier and identifier not in self.anchor_positions:
                self.anchor_positions[identifier] = len(self.text) + (1 if "".join(self.current).strip() else 0)
        if not self.excluded_depth and normalized == "br":
            self.current.append("\n")
        elif not self.excluded_depth and normalized in _TEXT_BLOCK_TAGS:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized in self.void_excluded_tags:
            return
        if normalized in self.excluded_tags and self.excluded_depth:
            self.excluded_depth -= 1
        elif not self.excluded_depth and normalized in _TEXT_BLOCK_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if not self.excluded_depth:
            self.current.append(data)

    def finish(self) -> None:
        self._flush()

    def _flush(self) -> None:
        paragraph = "".join(self.current).strip()
        if paragraph:
            self.text.append(paragraph)
        self.current = []


_EXCLUDED_TEXT_TAGS = {"head", "script", "style", "figure", "picture", "img", "image", "svg"}
_TEXT_BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "caption",
    "dd",
    "div",
    "dt",
    "figcaption",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "li",
    "main",
    "nav",
    "p",
    "pre",
    "section",
    "td",
    "th",
}


def _text_blocks(root: ElementTree.Element) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []

    def flush() -> None:
        paragraph = "".join(current).strip()
        if paragraph:
            blocks.append(paragraph)
        current.clear()

    def visit(node: ElementTree.Element) -> None:
        tag = _local_name(node.tag).lower()
        if tag in _EXCLUDED_TEXT_TAGS:
            return
        if tag == "br":
            current.append("\n")
        is_block = tag in _TEXT_BLOCK_TAGS
        if is_block:
            flush()
        if node.text:
            current.append(node.text)
        for child in node:
            visit(child)
            if child.tail:
                current.append(child.tail)
        if is_block:
            flush()

    visit(root)
    flush()
    return blocks


def _navigation_links_for(
    archive: ZipFile,
    package: ElementTree.Element,
    package_path: str,
    provider: dict[str, object] | None,
    *,
    native_fallback: bool = False,
) -> list[NavigationLink]:
    if provider is None and native_fallback:
        manifest, _ = _manifest_and_spine(package, package_path)
        navigation_item = next((item for item in manifest.values() if "nav" in item["properties"].split()), None)
        links: list[NavigationLink] = []
        if navigation_item is not None:
            try:
                links = _navigation_links(
                    _read_xml(archive, navigation_item["path"]), navigation_item["path"], "navigation"
                )
            except (KeyError, ElementTree.ParseError):
                links = []
        if not links:
            ncx_item = next(
                (item for item in manifest.values() if item["media_type"] == "application/x-dtbncx+xml"), None
            )
            if ncx_item is not None:
                try:
                    links = _ncx_links(_read_xml(archive, ncx_item["path"]), ncx_item["path"])
                except (KeyError, ElementTree.ParseError):
                    links = []
        return _merge_navigation_links([*links, *_guide_toc_links(archive, package, package_path)])
    if provider is None:
        return []
    links = [*_provider_navigation_links(provider), *_guide_toc_links(archive, package, package_path)]
    return _merge_navigation_links(links)


def _provider_navigation_links(provider: dict[str, object] | None) -> list[NavigationLink]:
    if provider is None:
        return []
    entries = provider.get("navigation")
    if not isinstance(entries, list):
        raise InvalidEpubError("无法读取 EPUB 文件")
    links: list[NavigationLink] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise InvalidEpubError("无法读取 EPUB 文件")
        title = entry.get("title")
        href = entry.get("href")
        source_path = entry.get("source_path")
        source = entry.get("source")
        depth = entry.get("depth")
        parent_title = entry.get("parent_title")
        if (
            not isinstance(title, str)
            or not isinstance(href, str)
            or not isinstance(source_path, str)
            or source not in {"nav", "ncx"}
            or not isinstance(depth, int)
        ):
            raise InvalidEpubError("无法读取 EPUB 文件")
        if parent_title is not None and not isinstance(parent_title, str):
            raise InvalidEpubError("无法读取 EPUB 文件")
        if title.strip() and href.strip() and source_path.strip():
            path, fragment = _resolve_href(source_path, href)
            links.append(NavigationLink(title.strip(), path, fragment, depth, parent_title, f"epubjs:{source}"))
    return links


def _guide_toc_links(
    archive: ZipFile,
    package: ElementTree.Element,
    package_path: str,
) -> list[NavigationLink]:
    links: list[NavigationLink] = []
    for reference in package.iter():
        if _local_name(reference.tag) != "reference" or reference.get("type") != "toc" or not reference.get("href"):
            continue
        toc_path, _ = _resolve_href(package_path, reference.attrib["href"])
        try:
            links.extend(_navigation_links(_read_xml(archive, toc_path), toc_path, "guide"))
        except (KeyError, ElementTree.ParseError):
            continue
    return links


def _merge_navigation_links(links: list[NavigationLink]) -> list[NavigationLink]:
    merged: list[NavigationLink] = []
    locations: dict[tuple[str, str | None, str], int] = {}
    for link in links:
        key = (link.path, link.fragment, " ".join(link.title.split()).casefold())
        existing_index = locations.get(key)
        if existing_index is None:
            merged.append(link)
            locations[key] = len(merged) - 1
        elif link.depth > merged[existing_index].depth or (
            link.parent_title and not merged[existing_index].parent_title
        ):
            merged[existing_index] = link
    return merged


def _navigation_links(document: ElementTree.Element, source_path: str, source: str = "navigation") -> list[NavigationLink]:
    """Walk the toc nav's nested <ol> lists so every entry keeps its declared depth."""
    navigation = _toc_nav(document)
    if navigation is None:
        return []
    links: list[NavigationLink] = []
    for ordered_list in navigation.iter():
        if _local_name(ordered_list.tag) == "ol":
            _collect_nav_items(ordered_list, source_path, 0, None, links, source)
            break
    return links


def _toc_nav(document: ElementTree.Element) -> ElementTree.Element | None:
    navigations = [node for node in document.iter() if _local_name(node.tag) == "nav"]
    for node in navigations:
        epub_type = next((value for key, value in node.attrib.items() if _local_name(key) == "type"), "")
        if "toc" in epub_type.split():
            return node
    return navigations[0] if navigations else None


def _collect_nav_items(
    ordered_list: ElementTree.Element,
    source_path: str,
    depth: int,
    parent_title: str | None,
    links: list[NavigationLink],
    source: str,
) -> None:
    for list_item in ordered_list:
        if _local_name(list_item.tag) != "li":
            continue
        anchor = next(
            (
                node
                for node in list_item
                if _local_name(node.tag) in {"a", "span"} and " ".join(node.itertext()).strip()
            ),
            None,
        )
        title = " ".join(anchor.itertext()).strip() if anchor is not None else ""
        href = anchor.get("href") if anchor is not None else None
        if title and href:
            path, fragment = _resolve_href(source_path, href)
            links.append(NavigationLink(title, path, fragment, depth, parent_title, source))
        for child in list_item:
            if _local_name(child.tag) == "ol":
                _collect_nav_items(child, source_path, depth + 1, title or parent_title, links, source)


def _ncx_links(document: ElementTree.Element, source_path: str) -> list[NavigationLink]:
    nav_map = next((node for node in document.iter() if _local_name(node.tag) == "navMap"), None)
    if nav_map is None:
        return []
    links: list[NavigationLink] = []
    _collect_nav_points(nav_map, source_path, 0, None, links)
    return links


def _collect_nav_points(
    parent: ElementTree.Element,
    source_path: str,
    depth: int,
    parent_title: str | None,
    links: list[NavigationLink],
) -> None:
    for point in parent:
        if _local_name(point.tag) != "navPoint":
            continue
        label = next((node for node in point if _local_name(node.tag) == "navLabel"), None)
        title = " ".join(label.itertext()).strip() if label is not None else ""
        content = next((node.get("src") for node in point if _local_name(node.tag) == "content"), None)
        if title and content:
            path, fragment = _resolve_href(source_path, content)
            links.append(NavigationLink(title, path, fragment, depth, parent_title, "ncx"))
        _collect_nav_points(point, source_path, depth + 1, title or parent_title, links)


def _body_start_position(package: ElementTree.Element, package_path: str, spine: list[str]) -> int | None:
    """Find where body text starts, as declared by the publisher.

    EPUB 2 states it in <guide type="text">. Everything before that point is front
    matter, which lets us skip covers and colophons without guessing from titles.
    """
    for reference in package.iter():
        if _local_name(reference.tag) != "reference":
            continue
        if reference.get("type") != "text" or not reference.get("href"):
            continue
        target = _resolve_path(package_path, reference.attrib["href"])
        for position, item_path in enumerate(spine, start=1):
            if item_path == target:
                return position
    return None


def _segments_from_spine(
    spine: list[tuple[str, str]],
    links: list[NavigationLink],
) -> tuple[list[SourceSegment], list[str], dict[tuple[str, str | None], int]]:
    """Split spine documents at declared anchors without inventing a fallback anchor.

    An unresolved fragment is reported and excluded from the location index. This is
    deliberately safer than treating it as the document start, which would attach a
    valid-looking chapter to unrelated text.
    """
    links_by_path: dict[str, list[NavigationLink]] = {}
    for link in links:
        links_by_path.setdefault(link.path, []).append(link)

    segments: list[SourceSegment] = []
    diagnostics: list[str] = []
    location_positions: dict[tuple[str, str | None], int] = {}
    for spine_position, (path, xhtml) in enumerate(spine, start=1):
        document_links = links_by_path.get(path, [])
        try:
            root = ElementTree.fromstring(unescape(xhtml))
            blocks, anchor_positions = _xhtml_blocks_and_anchor_positions(root)
        except ElementTree.ParseError:
            blocks, anchor_positions = _tolerant_xhtml_blocks_and_anchor_positions(xhtml)
        locations: dict[str | None, int] = {}
        if any(link.fragment is None for link in document_links) or not document_links:
            locations[None] = 0
        for link in document_links:
            if not link.fragment:
                continue
            position = anchor_positions.get(link.fragment)
            if position is None:
                diagnostics.append(f"unresolved_anchor:{link.path}#{link.fragment}")
                continue
            locations[link.fragment] = position
        starts = sorted(set(locations.values()))
        if not starts:
            # Keep the source text as a page, but leave every bad anchor unresolved.
            segments.append(SourceSegment(path, None, "\n\n".join(blocks).strip(), spine_position, 0))
            continue
        for index, start in enumerate(starts):
            end = starts[index + 1] if index + 1 < len(starts) else len(blocks)
            text = "\n\n".join(blocks[start:end]).strip()
            fragment = next(fragment for fragment, position in locations.items() if position == start)
            segment_position = len(segments) + 1
            segments.append(SourceSegment(path, fragment, text, spine_position, start))
            location_positions.update(
                ((path, location_fragment), segment_position)
                for location_fragment, position in locations.items()
                if position == start
            )
    return segments, diagnostics, location_positions


def _xhtml_blocks_and_anchor_positions(root: ElementTree.Element) -> tuple[list[str], dict[str, int]]:
    """Extract catalogue paragraphs and each id's insertion position in DOM order."""
    blocks: list[str] = []
    anchor_positions: dict[str, int] = {}
    current: list[str] = []

    def flush() -> None:
        paragraph = "".join(current).strip()
        if paragraph:
            blocks.append(paragraph)
        current.clear()

    def visit(node: ElementTree.Element) -> None:
        tag = _local_name(node.tag).lower()
        if tag in _EXCLUDED_TEXT_TAGS:
            return
        identifier = node.get("id")
        if identifier and identifier not in anchor_positions:
            anchor_positions[identifier] = len(blocks) + (1 if "".join(current).strip() else 0)
        if tag == "br":
            current.append("\n")
        is_block = tag in _TEXT_BLOCK_TAGS
        if is_block:
            flush()
        if node.text:
            current.append(node.text)
        for child in node:
            visit(child)
            if child.tail:
                current.append(child.tail)
        if is_block:
            flush()

    visit(root)
    flush()
    return blocks, anchor_positions


def _tolerant_xhtml_blocks_and_anchor_positions(content: str) -> tuple[list[str], dict[str, int]]:
    parser = _TolerantTextExtractor()
    parser.feed(content)
    parser.close()
    parser.finish()
    return parser.text, parser.anchor_positions


def _chapters_from_links(
    segments: list[SourceSegment],
    links: list[NavigationLink],
    body_start: int | None,
    location_positions: dict[tuple[str, str | None], int],
) -> list[ChapterDraft]:
    starts: list[tuple[NavigationLink, int]] = []
    for link in links:
        position = location_positions.get((link.path, link.fragment))
        if position is not None:
            starts.append((link, position))
    if not starts:
        return []

    starts.sort(key=lambda entry: (entry[1], entry[0].depth, entry[0].title.casefold()))
    min_depth = min(link.depth for link, _ in starts)
    chapters: list[ChapterDraft] = []
    if starts[0][1] > 1:
        # Spine pages ahead of the first navigation entry (cover, title page) are not
        # reachable from the outline; keep them so no source text silently disappears.
        lead_end = starts[0][1] - 1
        lead_text = "\n\n".join(segment.text for segment in segments[:lead_end]).strip()
        chapters.append(
            EpubChapterDraft(
                title="封面与前置页",
                source_start_page=1,
                source_end_page=lead_end,
                text=lead_text,
                nav_kind="front_matter",
                in_body=False,
                structural_role="front_matter",
                role_source="navigation_position",
                role_confidence="high",
                source_locator=segments[0].locator,
                text_sha256=_text_sha256(lead_text),
            )
        )

    kinds_by_navigation_title: dict[str, str] = {}
    display_title_by_navigation_title: dict[str, str] = {}
    for index, (link, start) in enumerate(starts):
        next_start = next((position for _, position in starts[index + 1 :] if position > start), len(segments) + 1)
        end = next_start - 1
        text = "\n\n".join(segment.text for segment in segments[start - 1 : end]).strip()
        depth = link.depth - min_depth
        title = _title_with_numbered_body_heading(link.title, text, link.source)
        navigation_parent_title = (link.parent_title or "").strip()
        parent_kind = kinds_by_navigation_title.get(navigation_parent_title)
        parent_title = display_title_by_navigation_title.get(
            navigation_parent_title, link.parent_title
        )
        nav_kind = _nav_kind(
            title,
            depth,
            segments[start - 1].spine_position,
            body_start,
            len(text),
            parent_kind=parent_kind,
        )
        role = _structural_role_decision(
            title=title,
            start=segments[start - 1].spine_position,
            body_start=body_start,
            nav_kind=nav_kind,
        )
        chapters.append(
            EpubChapterDraft(
                title=title,
                source_start_page=start,
                source_end_page=end,
                text=text,
                depth=depth,
                parent_title=parent_title,
                nav_kind=nav_kind,
                in_body=nav_kind not in {"front_matter", "back_matter"},
                structural_role=role.role,
                role_source=role.source,
                role_confidence=role.confidence,
                source_locator=f"{link.path}#{link.fragment}" if link.fragment else link.path,
                text_sha256=_text_sha256(text),
            )
        )
        kinds_by_navigation_title[link.title.strip()] = nav_kind
        display_title_by_navigation_title[link.title.strip()] = title
    return chapters


def _assign_analysis_roles(chapters: list[ChapterDraft]) -> list[ChapterDraft]:
    """Keep the outline intact while preventing duplicate source analysis.

    Some EPUB2 NCX files use the same target for a numbered chapter heading and
    its first child. The parent remains useful as a grouping label, while the child
    is the actual reading unit. Mark only that parent as outline-only.
    """
    duplicate_parent_titles = {
        (child.parent_title or "").strip()
        for child in chapters
        for parent in chapters
        if child.parent_title
        and parent.title.strip() == child.parent_title.strip()
        and parent.source_locator
        and parent.source_locator == child.source_locator
        and parent.text_sha256
        and parent.text_sha256 == child.text_sha256
    }
    return [
        replace(
            chapter,
            analysis_role=(
                "outline_only"
                if chapter.title.strip() in duplicate_parent_titles or chapter.nav_kind == "part"
                else "analysis_unit"
            ),
        )
        for chapter in chapters
    ]


def _structural_role_decision(
    *,
    title: str,
    start: int,
    body_start: int | None,
    nav_kind: str,
) -> StructuralRoleDecision:
    """Classify placement without pretending weak evidence is publisher truth."""
    if body_start is not None and start < body_start:
        return StructuralRoleDecision("front_matter", "publisher_landmark", "high")
    explicit_role = _explicit_structural_role(title)
    if explicit_role is not None:
        return StructuralRoleDecision(explicit_role, "title_fallback", "medium")
    if body_start is not None and start >= body_start:
        return StructuralRoleDecision("body", "publisher_landmark", "high")
    if nav_kind in {"part", "chapter", "section"}:
        return StructuralRoleDecision("body", "title_fallback", "medium")
    return StructuralRoleDecision("unknown", "unknown", "low")


def _inherit_structural_roles(chapters: list[ChapterDraft]) -> list[ChapterDraft]:
    """Apply the nearest declared parent's front/back placement to its children."""
    by_title: dict[str, ChapterDraft] = {}
    result: list[ChapterDraft] = []
    for chapter in chapters:
        parent = by_title.get((chapter.parent_title or "").strip())
        if parent and parent.structural_role in {"front_matter", "back_matter"}:
            chapter = replace(
                chapter,
                structural_role=parent.structural_role,
                role_source="parent_inherited",
                role_confidence=parent.role_confidence,
                in_body=False,
            )
        result.append(chapter)
        by_title[chapter.title.strip()] = chapter
    return result


def _reconcile_structural_roles(chapters: list[ChapterDraft]) -> list[ChapterDraft]:
    """Resolve explicit title evidence and contradictory publisher landmarks.

    A numbered chapter or part can be local to one work inside an anthology, so it
    must never define a global body range. Existing body roles remain body. Explicit
    front/back titles win after whitespace normalization; otherwise an item marked
    both front matter and body content is kept in the body and its confidence drops.
    """
    result: list[ChapterDraft] = []
    for chapter in chapters:
        explicit_role = _explicit_structural_role(chapter.title)
        parent = next((item for item in reversed(result) if item.title == chapter.parent_title), None)
        nested_closing = (
            chapter.title.strip() in {"结语", "结束语", "小结", "本章小结"}
            and chapter.nav_kind == "section"
            and parent is not None and parent.structural_role == "body"
        )
        if nested_closing:
            chapter = replace(chapter, structural_role="body", role_source="parent_inherited",
                              role_confidence=parent.role_confidence, in_body=True)
        elif explicit_role is not None:
            role_already_matches = chapter.structural_role == explicit_role and chapter.role_source != "unknown"
            chapter = replace(
                chapter,
                structural_role=explicit_role,
                role_source=chapter.role_source if role_already_matches else "title_fallback",
                role_confidence=chapter.role_confidence if role_already_matches else "medium",
            )
        elif (
            chapter.structural_role == "front_matter"
            and chapter.role_source == "publisher_landmark"
            and chapter.in_body
        ):
            chapter = replace(
                chapter,
                structural_role="body",
                role_source="content_signal",
                role_confidence="medium",
            )
        result.append(chapter)
    return result


def _explicit_structural_role(title: str) -> str | None:
    normalized = " ".join(title.split())
    compact = re.sub(r"\s+", "", title)
    if (
        BACK_MATTER_EXACT.match(normalized)
        or BACK_MATTER_PREFIX.match(normalized)
        or BACK_MATTER_COMPACT_SUFFIX.search(compact)
    ):
        return "back_matter"
    if (
        FRONT_MATTER_EXACT.match(normalized)
        or FRONT_MATTER_PREFIX.match(normalized)
        or FRONT_MATTER_COMPACT_PREFIX.match(compact)
        or FRONT_MATTER_COMPACT_SUFFIX.search(compact)
        or FRONT_MATTER_READER_NOTE.match(compact)
        or FRONT_MATTER_BARE_PREFACE.match(normalized)
    ):
        return "front_matter"
    return None


def _title_with_numbered_body_heading(title: str, text: str, source: str) -> str:
    """Keep a number printed in the source when its NCX label omitted it."""
    if source != "epubjs:ncx" or NUMBERED_CHAPTER.match(title):
        return title
    first_block = next((block.strip() for block in text.split("\n\n") if block.strip()), "")
    if NUMBERED_HEADING.fullmatch(first_block):
        return f"{first_block} {title}"
    return title


def _text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _nav_kind(
    title: str,
    depth: int,
    start: int,
    body_start: int | None,
    text_length: int,
    *,
    parent_kind: str | None = None,
) -> str:
    """Classify one navigation entry, trusting declared structure over title wording.

    Order matters: the guide landmark and navigation depth are publisher-declared, so
    they outrank regexes. Text length only rules out stubs, never promotes long text to
    body content, because bibliographies are often longer than any real chapter.
    """
    normalized = " ".join(title.split())

    if FRONT_MATTER_EXACT.match(normalized):
        return "front_matter"
    if BACK_MATTER_EXACT.match(normalized) or BACK_MATTER_PREFIX.match(normalized):
        # The same word ("结语") is a chapter's closing section when nested, but a
        # book-level afterword when it sits at the top of the outline.
        return "section" if depth > 0 else "back_matter"
    if PART_PREFIX.match(normalized):
        return "part"
    if CHAPTER_PREFIX.match(normalized):
        # A preface precedes the guide landmark yet is still authored content, so an
        # explicit chapter-level title outranks the position-and-length heuristic.
        return "chapter"
    if SECTION_PREFIX.match(normalized) or SECTION_EXACT.match(normalized):
        return "section"
    # Depth is relative, not semantic: depth 1 is a chapter below a part but a
    # section below a chapter. Use the already-classified declared parent first.
    if parent_kind == "part":
        return "chapter"
    if parent_kind in {"chapter", "section"}:
        return "section"
    if depth > 0:
        return "section" if depth > 1 else "chapter"
    if body_start is not None and start < body_start and text_length < FRONT_MATTER_TEXT_LIMIT:
        # Last resort: an untitled short page ahead of the body is almost never content.
        return "front_matter"
    return "plain"


def _book_metadata(package: ElementTree.Element, chapters: list[ChapterDraft]) -> BookMetadata:
    metadata_node = next((node for node in package.iter() if _local_name(node.tag) == "metadata"), None)
    if metadata_node is None:
        return BookMetadata(
            top_level_chapter_count=_count_chapters(chapters),
            analysis_unit_count=sum(
                1
                for chapter in chapters
                if chapter.in_body and chapter.analysis_role == "analysis_unit"
            ),
        )

    values: dict[str, list[tuple[str, str]]] = {}
    for node in metadata_node:
        name = _local_name(node.tag)
        text = " ".join(node.itertext()).strip()
        if not text:
            continue
        role = next((value for key, value in node.attrib.items() if _local_name(key) == "role"), "")
        values.setdefault(name, []).append((text, role))

    raw_title = values["title"][0][0] if values.get("title") else None
    title, subtitle = _split_title(raw_title)
    creators = values.get("creator", [])
    contributors = values.get("contributor", [])
    authors = tuple(text for text, role in creators if role in {"", "aut"}) or tuple(text for text, _ in creators)
    translators = tuple(text for text, role in creators + contributors if role == "trl")

    return BookMetadata(
        title=title,
        subtitle=subtitle,
        raw_title=raw_title,
        authors=authors,
        translators=translators,
        publisher=_first_value(values, "publisher"),
        language=_first_value(values, "language"),
        published_at=_first_value(values, "date"),
        identifier=_unique_identifier(package, metadata_node) or _first_value(values, "identifier"),
        spec_version=package.get("version"),
        top_level_chapter_count=_count_chapters(chapters),
        analysis_unit_count=sum(
            1
            for chapter in chapters
            if chapter.in_body and chapter.analysis_role == "analysis_unit"
        ),
    )


def _count_chapters(chapters: list[ChapterDraft]) -> int:
    """Count real numbered chapters.

    A preface is a chapter-level unit for analysis, but readers asking "how many
    chapters" mean the numbered ones, so an unnumbered preface must not inflate this.
    """
    numbered = sum(1 for chapter in chapters if chapter.nav_kind == "chapter" and NUMBERED_CHAPTER.match(chapter.title))
    if numbered:
        return numbered
    return sum(1 for chapter in chapters if chapter.nav_kind == "chapter")


def _first_value(values: dict[str, list[tuple[str, str]]], name: str) -> str | None:
    entries = values.get(name)
    return entries[0][0] if entries else None


def _unique_identifier(package: ElementTree.Element, metadata_node: ElementTree.Element) -> str | None:
    unique_id = package.get("unique-identifier")
    if not unique_id:
        return None
    for node in metadata_node:
        if _local_name(node.tag) == "identifier" and node.get("id") == unique_id:
            return " ".join(node.itertext()).strip() or None
    return None


def _split_title(raw_title: str | None) -> tuple[str | None, str | None]:
    """Strip retail marketing suffixes, then split off a trailing subtitle."""
    if not raw_title:
        return None, None
    collapsed = " ".join(raw_title.split())
    cleaned = MARKETING_SUFFIX.sub("", collapsed).strip(" -—–:：")
    if not cleaned:
        return collapsed, None
    parts = [part for part in SUBTITLE_SEPARATOR.split(cleaned, maxsplit=1) if part.strip()]
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return cleaned, None


def _whole_book(segments: list[SourceSegment]) -> list[ChapterDraft]:
    text = "\n\n".join(segment.text for segment in segments).strip()
    return [
        EpubChapterDraft(
            "全文",
            1,
            len(segments),
            text,
            source_locator=segments[0].locator if segments else None,
            text_sha256=_text_sha256(text),
        )
    ]
