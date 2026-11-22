from fastapi import HTTPException, status

from app.services.storage import BookRepository


def require_readable_book(
    repository: BookRepository, user_id: int | None, book_id: str
) -> dict[str, object]:
    book = repository.get_readable_book(user_id, book_id)
    if book is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="书籍不存在")
    return book


def require_private_owned_book(
    repository: BookRepository, user_id: int, book_id: str
) -> dict[str, object]:
    readable = require_readable_book(repository, user_id, book_id)
    if readable["access_scope"] != "owned" or readable["visibility"] != "private":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="精选书籍为平台只读内容")
    return readable
