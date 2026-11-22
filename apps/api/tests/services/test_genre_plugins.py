import json

from app.services.analysis_providers import (
    BookContext,
    ChapterAnalysisDraft,
    ChapterSource,
    _book_context_block,
    normalize_chapter_analysis_payload,
)
from app.services.genre_plugins import (
    DEFAULT_GENRE,
    GENRE_FIELD_WHITELIST,
    GENRE_KEYS,
    filter_genre_fields,
    genre_instructions,
    resolve_genre,
)


def analysis_payload(genre_fields: dict[str, object]) -> str:
    return json.dumps(
        {
            "chapter_question": "本章要回答什么？",
            "one_sentence_conclusion": "财政激励塑造地方行为。",
            "short_summary": "本章说明分税制如何改变地方政府的行为逻辑。",
            "argument_chain": ["提出问题", "给出证据"],
            "role_in_book": "建立分析框架",
            "estimated_reading_minutes": 6,
            "core_ideas": [
                {
                    "title": "财政激励塑造行为",
                    "conclusion": "地方政府的行为由财政激励决定。",
                    "importance": "解释后续所有案例。",
                    "explanation": "分税制改变了收入归属。",
                    "reasoning_steps": ["看制度", "看激励"],
                    "content_type": "ai_inference",
                    "confidence": 0.7,
                    "genre_fields": genre_fields,
                }
            ],
        },
        ensure_ascii=False,
    )


def test_every_genre_documents_the_fields_it_whitelists() -> None:
    """A whitelisted field the plugin never mentions can only ever arrive by
    accident, and one the plugin asks for but the whitelist rejects is discarded
    after the model spent tokens on it."""
    for genre in GENRE_KEYS:
        instructions = genre_instructions(genre)
        for field in GENRE_FIELD_WHITELIST[genre]:
            assert field in instructions, (genre, field)


def test_unknown_genre_falls_back_to_the_default() -> None:
    """Detection can return anything; an unrecognised value must not raise."""
    assert resolve_genre("sci-fi") == DEFAULT_GENRE
    assert resolve_genre(None) == DEFAULT_GENRE
    assert resolve_genre("practical") == "practical"


def test_fields_from_another_genre_are_dropped() -> None:
    """action_steps belongs to practical books. Keeping it on a propositional
    book would show the reader a step list the author never wrote."""
    filtered = filter_genre_fields(
        {"grounds_type": "empirical", "action_steps": ["不该出现"]}, "propositional"
    )

    assert filtered == {"grounds_type": "empirical"}


def test_invented_fields_are_dropped() -> None:
    assert filter_genre_fields({"made_up": "x"}, "narrative") == {}


def test_list_valued_sentence_fields_are_flattened() -> None:
    """The prompt asks for a sentence; returning a list is a common model habit
    and must not reach storage as a list where a string is expected."""
    filtered = filter_genre_fields({"scope_condition": ["条件A", "条件B"]}, "propositional")

    assert filtered == {"scope_condition": "条件A；条件B"}


def test_action_steps_stay_a_list_even_when_sent_as_one_string() -> None:
    """Order is the information in a step sequence, so this field is the one that
    must remain a list."""
    filtered = filter_genre_fields({"action_steps": "只有一步"}, "practical")

    assert filtered == {"action_steps": ["只有一步"]}


def test_normalize_filters_genre_fields_per_genre() -> None:
    supplied = {"action_steps": ["第一步"], "precondition": "X", "grounds_type": "empirical"}

    practical = ChapterAnalysisDraft.model_validate(
        normalize_chapter_analysis_payload(analysis_payload(supplied), genre="practical")
    )
    propositional = ChapterAnalysisDraft.model_validate(
        normalize_chapter_analysis_payload(analysis_payload(supplied), genre="propositional")
    )

    assert practical.core_ideas[0].genre_fields == {"action_steps": ["第一步"], "precondition": "X"}
    assert propositional.core_ideas[0].genre_fields == {"grounds_type": "empirical"}


def test_normalize_clears_genre_fields_when_the_model_omits_them() -> None:
    draft = ChapterAnalysisDraft.model_validate(
        normalize_chapter_analysis_payload(analysis_payload({}), genre="scholarly")
    )

    assert draft.core_ideas[0].genre_fields == {}


def test_context_block_names_the_book_and_places_the_chapter() -> None:
    """Before Layer 2 the prompt carried only a title and a page range, so the
    model could not tell a subordinate section from a standalone chapter."""
    context = BookContext(
        title="置身事内",
        subtitle="中国政府与经济发展",
        authors="兰小欢",
        genre="propositional",
        outline=["前言", "上篇", "第一章", "结语"],
    )
    chapter = ChapterSource(
        id=1,
        book_id="book-1",
        title="第一章",
        source_start_page=10,
        source_end_page=30,
        text="正文",
        depth=1,
        parent_title="上篇",
    )

    block = _book_context_block(chapter, context, "propositional")

    assert "置身事内：中国政府与经济发展" in block
    assert "兰小欢" in block
    assert "命题论证" in block
    assert "隶属于《上篇》" in block
    assert "小节" not in block
    assert "正文第 3 / 4 个章节" in block


def test_context_block_omits_position_for_repeated_titles() -> None:
    """Many books give every chapter its own 结语. Guessing which one this is
    would state a position that is wrong three times out of four."""
    context = BookContext(outline=["结语", "结语", "结语"])
    chapter = ChapterSource(
        id=2, book_id="book-1", title="结语", source_start_page=1, source_end_page=2, text="正文"
    )

    assert "【位置】" not in _book_context_block(chapter, context, "narrative")


def test_context_block_survives_a_book_with_no_metadata() -> None:
    """PDFs carry no metadata, and the prompt must still be well formed."""
    chapter = ChapterSource(
        id=3, book_id="book-1", title="第一章", source_start_page=1, source_end_page=4, text="正文"
    )

    block = _book_context_block(chapter, BookContext(), "propositional")

    assert "【书籍】未知" in block
    assert "【作者】未知" in block
    assert "【隶属】" not in block


def test_detection_falls_back_when_the_model_returns_nonsense(monkeypatch) -> None:
    """Detection is an optimisation. A bad response must not stop the book from
    being analysed, so it resolves to the default rather than raising."""
    from app.services.analysis_providers import ChatJsonResponse, OpenAICompatibleAnalysisProvider

    provider = OpenAICompatibleAnalysisProvider(base_url="http://x", api_key="k", model="m")
    monkeypatch.setattr(
        provider,
        "_chat_json",
        lambda **_: ChatJsonResponse(content="not json", prompt_tokens=None, completion_tokens=None, total_tokens=None),
    )

    decision = provider.detect_genre(BookContext(title="某书"), ["正文样本"])

    assert decision.genre == DEFAULT_GENRE


def test_detection_maps_an_unknown_label_onto_the_default(monkeypatch) -> None:
    from app.services.analysis_providers import ChatJsonResponse, OpenAICompatibleAnalysisProvider

    provider = OpenAICompatibleAnalysisProvider(base_url="http://x", api_key="k", model="m")
    monkeypatch.setattr(
        provider,
        "_chat_json",
        lambda **_: ChatJsonResponse(
            content='{"genre": "poetry", "confidence": 0.9, "reason": "r"}',
            prompt_tokens=None,
            completion_tokens=None,
            total_tokens=None,
        ),
    )

    decision = provider.detect_genre(BookContext(), [])

    assert decision.genre == DEFAULT_GENRE
    assert decision.confidence == 0.9


def test_detection_accepts_a_worded_confidence(monkeypatch) -> None:
    """The detection prompt asks for a decimal, but models answer "high"."""
    from app.services.analysis_providers import ChatJsonResponse, OpenAICompatibleAnalysisProvider

    provider = OpenAICompatibleAnalysisProvider(base_url="http://x", api_key="k", model="m")
    monkeypatch.setattr(
        provider,
        "_chat_json",
        lambda **_: ChatJsonResponse(
            content='{"genre": "practical", "confidence": "high", "reason": "祈使句为主"}',
            prompt_tokens=None,
            completion_tokens=None,
            total_tokens=None,
        ),
    )

    decision = provider.detect_genre(BookContext(), [])

    assert decision.genre == "practical"
    assert decision.confidence == 0.8


def test_a_chapter_inside_a_part_is_not_called_a_subsection() -> None:
    """In a book with 上篇/下篇 a chapter already sits at depth 1, so keying the
    hint on depth told the model that 第一章 was a subsection and capped its core
    ideas at one or two. nav_kind is the reliable signal."""
    chapter = ChapterSource(
        id=4,
        book_id="book-1",
        title="第一章",
        source_start_page=9,
        source_end_page=20,
        text="正文",
        depth=1,
        parent_title="上篇 微观机制",
        nav_kind="chapter",
    )

    block = _book_context_block(chapter, BookContext(), "propositional")

    assert "隶属于《上篇 微观机制》" in block
    assert "小节" not in block


def test_a_real_section_still_gets_the_lower_idea_count_hint() -> None:
    chapter = ChapterSource(
        id=5,
        book_id="book-1",
        title="第一节 政府治理的特点",
        source_start_page=10,
        source_end_page=12,
        text="正文",
        depth=2,
        parent_title="第一章",
        nav_kind="section",
    )

    assert "章内的小节" in _book_context_block(chapter, BookContext(), "propositional")
