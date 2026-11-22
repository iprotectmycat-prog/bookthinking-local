from app.services.analysis_providers import ChapterSource, PageSource
from app.services.evidence_catalog import build_evidence_catalogue


def chapter_source(*, page: int, text: str) -> ChapterSource:
    return ChapterSource(
        id=7,
        book_id="book-1",
        title="第一节 证据",
        source_start_page=page,
        source_end_page=page,
        text=text,
        pages=[PageSource(page_number=page, text=text)],
    )


def test_catalogue_assigns_stable_ids_and_keeps_literal_text() -> None:
    catalogue = build_evidence_catalogue(
        chapter_source(page=18, text="甲句。乙句。\n\n丙句。"), prefix="e"
    )

    assert [block.id for block in catalogue.blocks] == ["e1", "e2"]
    assert catalogue.blocks[0].quote == "甲句。乙句。"
    assert catalogue.blocks[0].page == 18
    assert catalogue.blocks[0].chapter_id == 7


def test_catalogue_reports_unknown_duplicate_and_empty_ids() -> None:
    catalogue = build_evidence_catalogue(chapter_source(page=1, text="原文。"), prefix="e")

    resolution = catalogue.resolve(["e1", "unknown", "e1", ""])

    assert [block.id for block in resolution.blocks] == ["e1"]
    assert resolution.unknown_ids == ["unknown"]
    assert resolution.duplicate_ids == ["e1"]
    assert resolution.empty_id_count == 1


def test_catalogue_keeps_a_complete_sentence_up_to_the_hard_limit() -> None:
    text = "甲" * 130 + "。"
    catalogue = build_evidence_catalogue(chapter_source(page=18, text=text), prefix="e")

    assert [block.quote for block in catalogue.blocks] == [text]
    assert catalogue.blocks[0].paragraph_id == "ep1"


def test_catalogue_splits_a_long_sentence_on_semicolon_without_losing_text() -> None:
    first = "甲" * 150 + "；"
    second = "乙" * 150 + "。"
    paragraph = first + second
    catalogue = build_evidence_catalogue(chapter_source(page=18, text=paragraph), prefix="e")

    assert [block.quote for block in catalogue.blocks] == [first, second]
    assert "".join(block.quote for block in catalogue.blocks) == paragraph


def test_catalogue_uses_comma_fallback_without_losing_text() -> None:
    first = "甲" * 150 + "，"
    second = "乙" * 150 + "。"
    paragraph = first + second
    catalogue = build_evidence_catalogue(chapter_source(page=18, text=paragraph), prefix="e")

    assert [block.quote for block in catalogue.blocks] == [first, second]
    assert "".join(block.quote for block in catalogue.blocks) == paragraph


def test_catalogue_repacks_recursively_split_pieces_with_adjacent_punctuation_pieces() -> None:
    prefix = "甲" * 10 + "；"
    recursive_first = "乙" * 150 + "，"
    recursive_second = "丙" * 100 + "；"
    suffix = "丁" * 20 + "。"
    paragraph = prefix + recursive_first + recursive_second + suffix
    catalogue = build_evidence_catalogue(chapter_source(page=18, text=paragraph), prefix="e")

    assert [block.quote for block in catalogue.blocks] == [
        prefix + recursive_first,
        recursive_second + suffix,
    ]
    assert "".join(block.quote for block in catalogue.blocks) == paragraph
    assert all(len(block.quote) <= 240 for block in catalogue.blocks)


def test_catalogue_hard_splits_only_when_no_boundary_exists() -> None:
    paragraph = "甲" * 481
    catalogue = build_evidence_catalogue(chapter_source(page=18, text=paragraph), prefix="e")

    assert [len(block.quote) for block in catalogue.blocks] == [240, 240, 1]
    assert "".join(block.quote for block in catalogue.blocks) == paragraph


def test_catalogue_preserves_nonempty_paragraph_whitespace_exactly() -> None:
    paragraph = "  甲句。  "
    text = f"{paragraph}\n\n \t \n\n乙句。"
    catalogue = build_evidence_catalogue(chapter_source(page=18, text=text), prefix="e")

    assert catalogue.blocks[0].surrounding_text == paragraph
    assert "".join(block.quote for block in catalogue.blocks if block.paragraph_id == "ep1") == paragraph


def test_catalogue_assigns_distinct_stable_paragraph_ids_across_paragraphs_and_pages() -> None:
    chapter = ChapterSource(
        id=7,
        book_id="book-1",
        title="第一节 证据",
        source_start_page=18,
        source_end_page=19,
        text="甲段。\n\n乙段。\n\n丙段。",
        pages=[
            PageSource(page_number=18, text="甲段。\n\n乙段。"),
            PageSource(page_number=19, text="丙段。"),
        ],
    )

    first = build_evidence_catalogue(chapter, prefix="e")
    second = build_evidence_catalogue(chapter, prefix="e")

    expected = [("e1", "ep1", 18), ("e2", "ep2", 18), ("e3", "ep3", 19)]
    assert [(block.id, block.paragraph_id, block.page) for block in first.blocks] == expected
    assert [(block.id, block.paragraph_id, block.page) for block in second.blocks] == expected


def test_catalogue_caps_the_soft_limit_at_120_characters() -> None:
    sentence = "甲" * 70 + "。"
    catalogue = build_evidence_catalogue(
        chapter_source(page=18, text=sentence * 2), prefix="e", max_characters=1000
    )

    assert [block.quote for block in catalogue.blocks] == [sentence, sentence]
