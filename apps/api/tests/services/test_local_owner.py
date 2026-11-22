from pathlib import Path

from app.services.accounts import AccountRepository
from app.services.pypdf_parser import ChapterDraft
from app.services.storage import BookRepository


def test_local_owner_is_stable_and_migrates_legacy_books_once(tmp_path: Path) -> None:
    database_path = tmp_path / "book-learning.sqlite3"
    books = BookRepository(database_path)
    books.save_book_import(
        book_id="legacy-book",
        filename="legacy.pdf",
        sha256="legacy-sha",
        stored_path=tmp_path / "legacy.pdf",
        status="ready",
        diagnostics=[],
        pages=["legacy text"],
        chapters=[ChapterDraft("全文", 1, 1, "legacy text")],
    )

    accounts = AccountRepository(database_path)
    first_owner = accounts.get_or_bootstrap_local_owner()
    second_owner = accounts.get_or_bootstrap_local_owner()

    assert second_owner == first_owner
    assert first_owner.role == "owner"
    assert first_owner.book_import_limit is None
    assert books.get_owned_book(first_owner.id, "legacy-book") is not None
