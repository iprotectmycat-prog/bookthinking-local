from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from app.services.storage import ApplicationPaths, BookRepository


class PublicLibraryError(ValueError):
    pass


class PublicLibraryService:
    def __init__(
        self,
        repository: BookRepository,
        paths: ApplicationPaths,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.repository = repository
        self.paths = paths
        self.now = now

    def publication_blockers(self, book_id: str, owner_id: int) -> tuple[str, ...]:
        book = self.repository.get_owned_book(owner_id, book_id)
        if book is None:
            raise PublicLibraryError("书籍不存在")

        blockers: list[str] = []
        if not self._managed_source_exists(Path(str(book["stored_path"]))):
            blockers.append("完整原书文件不可用")
        overview = self.repository.get_book_overview(book_id)
        if not overview or overview["generation_status"] != "ready":
            blockers.append("全书概览尚未完成")
        if not self.repository.has_ready_readable_chapter(book_id):
            blockers.append("至少需要一个分析完成的可读章节")
        return tuple(blockers)

    def publish(self, book_id: str, owner_id: int) -> dict[str, object]:
        blockers = self.publication_blockers(book_id, owner_id)
        if blockers:
            raise PublicLibraryError(blockers[0])

        if not self.repository.set_book_visibility(
            book_id=book_id,
            owner_id=owner_id,
            visibility="public",
            published_by_user_id=owner_id,
            public_at=self.now().astimezone(timezone.utc).isoformat(),
        ):
            raise PublicLibraryError("书籍不存在")
        book = self.repository.get_owned_book(owner_id, book_id)
        if book is None:
            raise PublicLibraryError("书籍不存在")
        return book

    def unpublish(self, book_id: str, owner_id: int) -> dict[str, object]:
        if self.repository.get_owned_book(owner_id, book_id) is None:
            raise PublicLibraryError("书籍不存在")
        self.repository.set_book_visibility(
            book_id=book_id,
            owner_id=owner_id,
            visibility="private",
            published_by_user_id=None,
            public_at=None,
        )
        book = self.repository.get_owned_book(owner_id, book_id)
        if book is None:
            raise PublicLibraryError("书籍不存在")
        return book

    def _managed_source_exists(self, source: Path) -> bool:
        try:
            resolved_source = source.resolve(strict=True)
            resolved_root = self.paths.books_dir.resolve(strict=True)
            resolved_source.relative_to(resolved_root)
        except (FileNotFoundError, ValueError):
            return False
        return resolved_source.is_file()
