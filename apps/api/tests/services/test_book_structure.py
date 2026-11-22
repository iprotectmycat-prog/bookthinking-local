from app.services.book_structure import structure_hash
from app.services.pypdf_parser import ChapterDraft, ParsedBook


def test_structure_hash_changes_when_semantic_hierarchy_changes() -> None:
    chapter = ChapterDraft(
        title="形成原因",
        source_start_page=1,
        source_end_page=1,
        text="正文",
        depth=0,
        nav_kind="chapter",
        source_locator="chapter.xhtml#reason",
        text_sha256="same",
    )
    section = ChapterDraft(
        title=chapter.title,
        source_start_page=chapter.source_start_page,
        source_end_page=chapter.source_end_page,
        text=chapter.text,
        depth=1,
        parent_title="第一章",
        nav_kind="section",
        source_locator=chapter.source_locator,
        text_sha256=chapter.text_sha256,
    )

    assert structure_hash(ParsedBook([], [chapter])) != structure_hash(ParsedBook([], [section]))
