"""Manage the public bookshelf directly on the server."""

import argparse

from app.services.public_library import PublicLibraryError, PublicLibraryService
from app.services.storage import ApplicationPaths, BookRepository


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.curate")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="List published books and their IDs")
    publish = commands.add_parser("publish", help="Publish an analyzed book")
    publish.add_argument("book_id")
    publish.add_argument("--confirm-rights", action="store_true", required=True)
    unpublish = commands.add_parser("unpublish", help="Remove a book from the public bookshelf")
    unpublish.add_argument("book_id")
    args = parser.parse_args()

    paths = ApplicationPaths.from_environment()
    paths.ensure_exists()
    repository = BookRepository(paths.database_path)
    service = PublicLibraryService(repository, paths)
    if args.command == "list":
        for book in repository.list_public_analyzed_books():
            print(f"{book['id']}\t{book['title'] or book['filename']}")
        return 0

    book = repository.get_book(args.book_id)
    if book is None:
        parser.error("书籍不存在")
    if book["owner_id"] is None:
        parser.error("书籍缺少所有者，请先迁移旧书库")
    owner_id = int(book["owner_id"])
    try:
        if args.command == "publish":
            service.publish(args.book_id, owner_id)
        else:
            service.unpublish(args.book_id, owner_id)
    except PublicLibraryError as error:
        parser.error(str(error))
    print(f"{args.command}: {args.book_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
