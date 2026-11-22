from collections.abc import Callable
from threading import Lock, Thread


class AnalysisJobRegistry:
    """Run at most one in-process analysis batch for each book."""

    def __init__(self) -> None:
        self._active_book_ids: set[str] = set()
        self._lock = Lock()

    def start(self, book_id: str, operation: Callable[[], None]) -> bool:
        with self._lock:
            if book_id in self._active_book_ids:
                return False
            self._active_book_ids.add(book_id)

        def run() -> None:
            try:
                operation()
            finally:
                with self._lock:
                    self._active_book_ids.discard(book_id)

        Thread(target=run, daemon=True, name=f"book-analysis-{book_id}").start()
        return True
