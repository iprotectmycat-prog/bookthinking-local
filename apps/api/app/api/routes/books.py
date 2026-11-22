from datetime import datetime, timedelta, timezone
import re
from typing import Annotated
from uuid import uuid4
from json import loads
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from app.schemas import (
    AnalyzedBookResponse,
    BookImportResponse,
    BookResponse,
    ChapterConfirmationRequest,
    ChapterDraftResponse,
    ChapterResponse,
    ExternalBookLinkResponse,
    StructureApplyRequest,
    StructureApplyResponse,
    StructurePreviewResponse,
)
from app.services.book_importer import BookImporter
from app.services.book_cover import BookCoverService, CoverUnavailableError
from app.services.book_structure import (
    BookStructureService,
    InvalidBookStructureError,
    StaleStructurePreviewError,
    StoredBookUnavailableError,
    StructureBookNotFoundError,
    UnsupportedBookStructureError,
)
from app.services.chapter_confirmation import (
    ChapterConfirmationError,
    ChapterConfirmationService,
    ConfirmedChapter,
)
from app.services.epub_parser import EpubParser, InvalidEpubError
from app.services.pypdf_parser import PypdfParser
from app.services.douban_links import BookIdentity, DoubanLinkMatcher, DoubanMatchResult, normalize_isbn
from app.services.storage import (
    ApplicationPaths,
    BookRepository,
    DuplicateBookImport,
)
from app.api.book_access import require_private_owned_book, require_readable_book
from app.api.dependencies import resolve_product_user, resolve_reader_owner_id
from app.services.accounts import UserRecord

router = APIRouter(prefix="/books", tags=["books"])
local_library_router = APIRouter(prefix="/library", tags=["local-library"])
reading_router = APIRouter(prefix="/books", tags=["reading"])
curated_router = APIRouter(prefix="/library", tags=["curated-library"])


def get_douban_link_matcher() -> DoubanLinkMatcher:
    return DoubanLinkMatcher()


def _filename_identity(filename: str) -> tuple[str, tuple[str, ...]]:
    stem = filename.rsplit(".", 1)[0].strip()
    groups = re.findall(r"\(([^()]*)\)", stem)
    author_group = next((group for group in groups if "z-lib" not in group.casefold()), "")
    first_author = next((part.strip() for part in re.split(r"[、,，/]", author_group) if part.strip()), "")
    authors = (first_author,) if first_author else ()
    title = re.sub(r"\s*\([^()]*\)", "", stem).strip()
    return title or stem, authors


def _book_identity(book: dict[str, object]) -> BookIdentity:
    authors = tuple(part.strip() for part in re.split(r"[、,]", str(book.get("authors") or "")) if part.strip())
    year = re.search(r"(?:19|20)\d{2}", str(book.get("published_at") or ""))
    fallback_title, fallback_authors = _filename_identity(str(book["filename"]))
    title = str(book.get("title") or "").strip() or fallback_title
    return BookIdentity(
        title=title,
        authors=authors or fallback_authors,
        publisher=str(book.get("publisher") or "").strip() or None,
        published_year=year.group(0) if year else None,
        isbn=normalize_isbn(str(book.get("identifier") or "")),
    )


def _hydrate_legacy_epub_identity(repository: BookRepository, book: dict[str, object]) -> dict[str, object]:
    if book.get("source_format") != "epub" or (book.get("title") and book.get("authors") and book.get("published_at")):
        return book
    stored_path = repository.get_stored_book_path(str(book["id"]))
    if stored_path is None:
        return book
    try:
        repository.update_book_metadata(str(book["id"]), EpubParser().read_metadata(stored_path))
    except (InvalidEpubError, OSError):
        return book
    return repository.get_book(str(book["id"])) or book


def _retry_due(cached: dict[str, object], now: datetime) -> bool:
    retry_after = cached.get("retry_after")
    return bool(retry_after and datetime.fromisoformat(str(retry_after)) <= now)


def _cache_douban_result(repository: BookRepository, book_id: str, result: DoubanMatchResult, now: datetime) -> None:
    retry_after = None
    if result.status in {"not_found", "ambiguous"}:
        retry_after = now + timedelta(days=7)
    elif result.status == "provider_error":
        retry_after = now + timedelta(hours=1)
    repository.save_external_book_link(
        book_id=book_id,
        provider="douban",
        status=result.status,
        external_id=result.external_id,
        url=result.url,
        match_basis=result.match_basis,
        checked_at=now.isoformat(),
        retry_after=retry_after.isoformat() if retry_after else None,
    )


def _public_douban_link(cached: dict[str, object] | None) -> ExternalBookLinkResponse:
    if cached and cached.get("status") == "matched" and cached.get("url"):
        return ExternalBookLinkResponse(status="matched", url=str(cached["url"]))
    return ExternalBookLinkResponse(status="unavailable", url=None)


@local_library_router.get("/analyzed", response_model=list[AnalyzedBookResponse])
def list_local_analyzed_books(
    user: Annotated[UserRecord, Depends(resolve_product_user)],
) -> list[AnalyzedBookResponse]:
    """Expose the shared library managed by this local application."""
    paths = ApplicationPaths.from_environment()
    return [
        AnalyzedBookResponse(**book)
        for book in BookRepository(paths.database_path).list_analyzed_books_for_owner(user.id)
    ]


@router.get("/analyzed", response_model=list[AnalyzedBookResponse])
def list_analyzed_books(
    user: Annotated[UserRecord, Depends(resolve_product_user)],
) -> list[AnalyzedBookResponse]:
    paths = ApplicationPaths.from_environment()
    return [
        AnalyzedBookResponse(**book)
        for book in BookRepository(paths.database_path).list_analyzed_books_for_owner(user.id)
    ]


@curated_router.get("/public", response_model=list[AnalyzedBookResponse])
def list_public_analyzed_books() -> list[AnalyzedBookResponse]:
    paths = ApplicationPaths.from_environment()
    return [
        AnalyzedBookResponse(**book)
        for book in BookRepository(paths.database_path).list_public_analyzed_books()
    ]


@router.post("", response_model=BookImportResponse, status_code=status.HTTP_201_CREATED)
async def import_book(
    file: Annotated[UploadFile, File(...)],
    user: Annotated[UserRecord, Depends(resolve_product_user)],
) -> BookImportResponse:
    paths = ApplicationPaths.from_environment()
    paths.ensure_exists()
    try:
        # Content types are unreliable for ebooks (KEPUB and MOBI both arrive as
        # octet-stream), so the importer decides from the magic bytes and filename and
        # produces a message naming the actual format.
        result = await BookImporter(paths.books_dir, PypdfParser()).import_upload(file)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    finally:
        await file.close()

    repository = BookRepository(paths.database_path)
    existing = repository.find_owned_book_by_sha256(user.id, result.sha256)
    if existing is not None:
        if existing["source_format"] == "epub" and existing["status"] == "chapters_confirmed":
            return book_response(repository, str(existing["id"]), access_scope="owned")
        repository.save_book_pages(str(existing["id"]), result.pages)
        if existing["status"] != "chapters_confirmed":
            repository.replace_chapter_drafts(str(existing["id"]), list(result.chapters))
        else:
            confirmed = repository.list_chapters(str(existing["id"]), confirmed=True)
            legacy_full_book = (
                len(confirmed) == 1
                and confirmed[0]["title"] == "全文"
                and int(confirmed[0]["source_start_page"]) == 1
                and int(confirmed[0]["source_end_page"]) == len(result.pages)
            )
            if legacy_full_book and len(result.chapters) > 1:
                repository.replace_confirmed_chapters(
                    str(existing["id"]),
                    [
                        ConfirmedChapter(
                            title=chapter.title,
                            source_start_page=chapter.source_start_page,
                            source_end_page=chapter.source_end_page,
                            depth=chapter.depth,
                            parent_title=chapter.parent_title,
                            nav_kind=chapter.nav_kind,
                            in_body=chapter.in_body,
                            structural_role=chapter.structural_role,
                            role_source=chapter.role_source,
                            role_confidence=chapter.role_confidence,
                            analysis_role=chapter.analysis_role,
                        )
                        for chapter in result.chapters
                    ],
                )
        return book_response(repository, str(existing["id"]), access_scope="owned")

    book_id = str(uuid4())
    try:
        repository.save_book_import(
            owner_id=user.id,
            book_id=book_id,
            filename=file.filename or f"book.{result.source_format}",
            sha256=result.sha256,
            stored_path=result.stored_path,
            source_format=result.source_format,
            status=result.status,
            diagnostics=result.diagnostics,
            pages=result.pages,
            chapters=list(result.chapters),
            metadata=result.metadata,
        )
    except DuplicateBookImport as error:
        return book_response(repository, error.book_id, access_scope="owned")
    return BookImportResponse(
        id=book_id,
        sha256=result.sha256,
        source_format=result.source_format,
        status=result.status,
        diagnostics=result.diagnostics,
        chapters=[
            ChapterDraftResponse(
                title=chapter.title,
                source_start_page=chapter.source_start_page,
                source_end_page=chapter.source_end_page,
                depth=chapter.depth,
                parent_title=chapter.parent_title,
                nav_kind=chapter.nav_kind,
                in_body=chapter.in_body,
                structural_role=chapter.structural_role,
                role_source=chapter.role_source,
                role_confidence=chapter.role_confidence,
                analysis_role=chapter.analysis_role,
            )
            for chapter in result.chapters
        ],
    )


def book_response(
    repository: BookRepository, book_id: str, *, access_scope: str
) -> BookResponse:
    book = repository.get_book(book_id)
    if book is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="书籍不存在")
    confirmed = book["status"] == "chapters_confirmed"
    return BookResponse(
        id=book["id"],
        filename=book["filename"],
        title=book["title"],
        subtitle=book["subtitle"],
        sha256=book["sha256"],
        source_format=book["source_format"],
        status=book["status"],
        diagnostics=loads(book["diagnostics_json"]),
        structure_version=book["structure_version"],
        structure_diagnostics=loads(book["structure_diagnostics_json"]),
        access_scope=access_scope,
        chapters=[ChapterResponse(**chapter) for chapter in repository.list_chapters(book_id, confirmed=confirmed)],
    )


@reading_router.get("/{book_id}/external-links/douban", response_model=ExternalBookLinkResponse)
def get_douban_book_link(
    book_id: str,
    matcher: Annotated[DoubanLinkMatcher, Depends(get_douban_link_matcher)],
    owner_id: Annotated[int | None, Depends(resolve_reader_owner_id)],
) -> ExternalBookLinkResponse:
    paths = ApplicationPaths.from_environment()
    repository = BookRepository(paths.database_path)
    book = require_readable_book(repository, owner_id, book_id)
    cached = repository.get_external_book_link(book_id, "douban")
    if book["access_scope"] == "public":
        return _public_douban_link(cached)
    book = _hydrate_legacy_epub_identity(repository, book)
    now = datetime.now(timezone.utc)
    if cached and (cached.get("status") == "matched" or not _retry_due(cached, now)):
        return _public_douban_link(cached)

    result = matcher.resolve(_book_identity(book))
    _cache_douban_result(repository, book_id, result, now)
    return _public_douban_link(repository.get_external_book_link(book_id, "douban"))


@reading_router.get("/{book_id}", response_model=BookResponse)
def get_book(
    book_id: str,
    owner_id: Annotated[int | None, Depends(resolve_reader_owner_id)],
) -> BookResponse:
    paths = ApplicationPaths.from_environment()
    repository = BookRepository(paths.database_path)
    book = require_readable_book(repository, owner_id, book_id)
    return book_response(repository, book_id, access_scope=str(book["access_scope"]))


@reading_router.get("/{book_id}/file")
def get_book_file(
    book_id: str,
    owner_id: Annotated[int | None, Depends(resolve_reader_owner_id)],
) -> FileResponse:
    paths = ApplicationPaths.from_environment()
    paths.ensure_exists()
    repository = BookRepository(paths.database_path)
    book = require_readable_book(repository, owner_id, book_id)
    stored_path = Path(str(book["stored_path"])) if book["stored_path"] else None
    if stored_path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="书籍原文件不存在")

    try:
        resolved_path = stored_path.resolve(strict=True)
        resolved_root = paths.books_dir.resolve(strict=True)
        resolved_path.relative_to(resolved_root)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="书籍原文件不存在") from None

    return FileResponse(
        resolved_path,
        media_type="application/epub+zip" if book["source_format"] == "epub" else "application/pdf",
        filename=str(book["filename"]),
        content_disposition_type="inline",
        headers={"Cache-Control": "private"},
    )


@curated_router.get("/books/{book_id}/cover")
@reading_router.get("/{book_id}/cover")
def get_book_cover(
    book_id: str,
    owner_id: Annotated[int | None, Depends(resolve_reader_owner_id)],
) -> FileResponse:
    paths = ApplicationPaths.from_environment()
    paths.ensure_exists()
    repository = BookRepository(paths.database_path)
    book = require_readable_book(repository, owner_id, book_id)
    stored_path = Path(str(book["stored_path"])) if book["stored_path"] else None
    if stored_path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="书籍封面不可用")

    try:
        resolved_path = stored_path.resolve(strict=True)
        resolved_root = paths.books_dir.resolve(strict=True)
        resolved_path.relative_to(resolved_root)
        cover = BookCoverService(paths.covers_dir).get_or_create(
            book_id=book_id,
            source_path=resolved_path,
            source_format=str(book["source_format"]),
        )
    except (FileNotFoundError, ValueError, CoverUnavailableError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="书籍封面不可用") from None

    return FileResponse(
        cover.path,
        media_type=cover.media_type,
        headers={
            "Cache-Control": "private, max-age=31536000, immutable",
            "ETag": f'"{cover.path.stem}"',
        },
    )


@router.post("/{book_id}/structure-preview", response_model=StructurePreviewResponse)
def preview_structure(
    book_id: str,
    user: Annotated[UserRecord, Depends(resolve_product_user)],
) -> StructurePreviewResponse:
    paths = ApplicationPaths.from_environment()
    repository = BookRepository(paths.database_path)
    require_private_owned_book(repository, user.id, book_id)
    try:
        preview = BookStructureService(repository).preview(book_id)
    except (StructureBookNotFoundError, StoredBookUnavailableError) as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except (UnsupportedBookStructureError, InvalidBookStructureError) as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    return StructurePreviewResponse.from_domain(preview)


@router.put("/{book_id}/structure", response_model=StructureApplyResponse)
def apply_structure(
    book_id: str,
    request: StructureApplyRequest,
    user: Annotated[UserRecord, Depends(resolve_product_user)],
) -> StructureApplyResponse:
    paths = ApplicationPaths.from_environment()
    repository = BookRepository(paths.database_path)
    require_private_owned_book(repository, user.id, book_id)
    try:
        result = BookStructureService(repository).apply(book_id, request.structure_hash)
    except (StructureBookNotFoundError, StoredBookUnavailableError) as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except (UnsupportedBookStructureError, InvalidBookStructureError) as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    except StaleStructurePreviewError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return StructureApplyResponse.from_domain(result)


@router.put("/{book_id}/chapters", response_model=BookResponse)
def confirm_chapters(
    book_id: str,
    request: ChapterConfirmationRequest,
    user: Annotated[UserRecord, Depends(resolve_product_user)],
) -> BookResponse:
    paths = ApplicationPaths.from_environment()
    repository = BookRepository(paths.database_path)
    require_private_owned_book(repository, user.id, book_id)
    chapters = [ConfirmedChapter(**chapter.model_dump()) for chapter in request.chapters]
    try:
        ChapterConfirmationService(repository).confirm(book_id, chapters)
    except ChapterConfirmationError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    return book_response(repository, book_id, access_scope="owned")
