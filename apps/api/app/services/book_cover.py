"""Local, cached cover images for the homepage shelf."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from os import replace
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

import pypdfium2 as pdfium
from PIL import Image, UnidentifiedImageError


MAX_COVER_WIDTH = 480
COVER_VERSION = "v1"


class CoverUnavailableError(ValueError):
    """The stored file has no usable cover image."""


@dataclass(frozen=True)
class CoverArtifact:
    path: Path
    media_type: str = "image/webp"


class BookCoverService:
    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir

    def get_or_create(self, *, book_id: str, source_path: Path, source_format: str) -> CoverArtifact:
        cache_path = self._cache_path(book_id, source_path)
        if cache_path.exists():
            return CoverArtifact(cache_path)

        try:
            image = self._source_image(source_path, source_format)
            self._write_webp(image, cache_path)
        except (BadZipFile, ElementTree.ParseError, OSError, UnidentifiedImageError, ValueError, pdfium.PdfiumError) as error:
            raise CoverUnavailableError("书籍没有可用封面") from error
        return CoverArtifact(cache_path)

    def _cache_path(self, book_id: str, source_path: Path) -> Path:
        try:
            state = source_path.stat()
        except OSError as error:
            raise CoverUnavailableError("书籍原文件不存在") from error
        fingerprint = sha256(f"{COVER_VERSION}:{source_path}:{state.st_size}:{state.st_mtime_ns}".encode()).hexdigest()[:16]
        self.cache_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        return self.cache_dir / f"{book_id}-{fingerprint}.webp"

    def _source_image(self, source_path: Path, source_format: str) -> Image.Image:
        if source_format == "epub":
            return self._epub_cover(source_path)
        if source_format == "pdf":
            return self._pdf_first_page(source_path)
        raise CoverUnavailableError("不支持该书籍格式的封面")

    def _epub_cover(self, source_path: Path) -> Image.Image:
        with ZipFile(source_path) as archive:
            package_path = _epub_package_path(archive)
            package = ElementTree.fromstring(archive.read(package_path))
            manifest = {
                item.attrib.get("id", ""): item
                for item in package.iter()
                if _local_name(item.tag) == "item"
            }
            cover_item = next(
                (item for item in manifest.values() if "cover-image" in item.attrib.get("properties", "").split()),
                None,
            )
            if cover_item is None:
                cover_id = next(
                    (
                        item.attrib.get("content", "")
                        for item in package.iter()
                        if _local_name(item.tag) == "meta" and item.attrib.get("name") == "cover"
                    ),
                    "",
                )
                cover_item = manifest.get(cover_id)
            if cover_item is None:
                # Some EPUB exports omit both EPUB 3's `cover-image` property and
                # EPUB 2's metadata, yet still retain an unambiguous raster image
                # named "cover" in the manifest. Do not choose generic artwork:
                # require the word in the id/href and an image media type.
                cover_item = next(
                    (
                        item
                        for item in manifest.values()
                        if item.attrib.get("media-type", "").startswith("image/")
                        and "cover" in f"{item.attrib.get('id', '')} {item.attrib.get('href', '')}".lower()
                    ),
                    None,
                )
            if cover_item is not None and cover_item.attrib.get("href"):
                image_path = _epub_relative_path(package_path, cover_item.attrib["href"])
                return _open_image(archive.read(image_path))

            guide_cover = next(
                (
                    reference.attrib.get("href", "")
                    for reference in package.iter()
                    if _local_name(reference.tag) == "reference" and reference.attrib.get("type", "").lower() == "cover"
                ),
                "",
            )
            if not guide_cover:
                raise CoverUnavailableError("EPUB 没有声明封面")
            guide_path = _epub_relative_path(package_path, guide_cover)
            guide_data = archive.read(guide_path)
            try:
                return _open_image(guide_data)
            except UnidentifiedImageError:
                image_path = _guide_page_image_path(guide_data, guide_path)
                return _open_image(archive.read(image_path))

    def _pdf_first_page(self, source_path: Path) -> Image.Image:
        document = pdfium.PdfDocument(str(source_path))
        try:
            if len(document) == 0:
                raise CoverUnavailableError("PDF 没有页面")
            page = document[0]
            try:
                bitmap = page.render(scale=1.25)
                try:
                    return bitmap.to_pil().copy()
                finally:
                    bitmap.close()
            finally:
                page.close()
        finally:
            document.close()

    def _write_webp(self, image: Image.Image, target: Path) -> None:
        normalized = image.convert("RGB")
        normalized.thumbnail((MAX_COVER_WIDTH, MAX_COVER_WIDTH * 2))
        temporary = None
        try:
            with NamedTemporaryFile(dir=target.parent, suffix=".webp", prefix=f".{target.stem}.", delete=False) as output:
                temporary = Path(output.name)
            normalized.save(temporary, format="WEBP", quality=82, method=4)
            replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def _epub_package_path(archive: ZipFile) -> str:
    container = ElementTree.fromstring(archive.read("META-INF/container.xml"))
    rootfile = next((node for node in container.iter() if _local_name(node.tag) == "rootfile"), None)
    if rootfile is None or not rootfile.attrib.get("full-path"):
        raise CoverUnavailableError("EPUB 缺少包文件")
    return rootfile.attrib["full-path"]


def _epub_relative_path(package_path: str, href: str) -> str:
    candidate = PurePosixPath(package_path).parent / PurePosixPath(href.split("#", 1)[0])
    if candidate.is_absolute():
        raise CoverUnavailableError("EPUB 封面路径无效")
    resolved_parts: list[str] = []
    for part in candidate.parts:
        if part in (".", ""):
            continue
        if part == "..":
            if not resolved_parts:
                raise CoverUnavailableError("EPUB 封面路径无效")
            resolved_parts.pop()
            continue
        resolved_parts.append(part)
    return PurePosixPath(*resolved_parts).as_posix()


def _guide_page_image_path(page: bytes, guide_path: str) -> str:
    document = ElementTree.fromstring(page)
    image = next(
        (node for node in document.iter() if _local_name(node.tag) in {"img", "image"}),
        None,
    )
    if image is None:
        raise CoverUnavailableError("EPUB 封面页没有图片")
    href = image.attrib.get("src") or image.attrib.get("href") or image.attrib.get("{http://www.w3.org/1999/xlink}href")
    if not href:
        raise CoverUnavailableError("EPUB 封面页图片路径无效")
    return _epub_relative_path(guide_path, href)


def _open_image(data: bytes) -> Image.Image:
    with Image.open(BytesIO(data)) as image:
        return image.copy()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
