import json

import httpx

from app.services.analysis_policy import analysis_budget_for_text
from app.services.analysis_providers import (
    CHAPTER_ANALYSIS_SYSTEM_PROMPT,
    MAX_EVIDENCE_PER_IDEA,
    MAX_EXPLANATION_CHARACTERS,
    MAX_LIST_ITEM_CHARACTERS,
    MAX_LIST_ITEMS,
    MAX_QUOTE_CHARACTERS,
    MAX_READING_MINUTES,
    MIN_READING_MINUTES,
    BookContext,
    AnalysisProviderError,
    ChapterAnalysisDraft,
    ChapterSource,
    OpenAICompatibleAnalysisProvider,
    RoundRobinAnalysisProvider,
    _evidence_catalogue_block,
    _limit_draft_to_budget,
    normalize_chapter_analysis_payload,
)
from app.services.evidence_catalog import EvidenceBlock, HARD_BLOCK_CHARACTERS, SOFT_BLOCK_CHARACTERS


def valid_analysis_payload() -> dict[str, object]:
    return {
        "chapter_question": "本章如何建立可信结论？",
        "one_sentence_conclusion": "结论必须由原文证据支持。",
        "short_summary": "本章解释证据与结论的关系。",
        "argument_chain": ["提出问题", "检查证据", "形成结论"],
        "role_in_book": "建立方法基础",
        "estimated_reading_minutes": 3,
        "core_ideas": [
            {
                "title": "证据优先",
                "conclusion": "结论必须可回查。",
                "importance": "避免无依据推断。",
                "explanation": "先核对原文，再展示结论。",
                "reasoning_steps": ["定位", "核对", "发布"],
                "examples": [],
                "caveats": [],
                "relations": [],
                "content_type": "book_claim",
                "confidence": 0.9,
                "evidence": [{"page": 1, "quote": "作者用可回查的原文建立可信结论。"}],
            }
        ],
    }


def test_openai_compatible_provider_requests_json_and_parses_draft() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(valid_analysis_payload(), ensure_ascii=False)}}]},
        )

    provider = OpenAICompatibleAnalysisProvider(
        base_url="https://api.openai.com/v1",
        api_key="secret",
        model="gpt-5-mini",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    draft = provider.generate(
        ChapterSource(
            id=1,
            book_id="book-1",
            title="第一章",
            source_start_page=1,
            source_end_page=1,
            text="作者用可回查的原文建立可信结论。",
        )
    )

    assert captured["response_format"] == {"type": "json_object"}
    assert captured["model"] == "gpt-5-mini"
    assert draft.core_ideas[0].evidence[0].page == 1


def test_provider_selects_literal_evidence_ids_without_copying_a_quote() -> None:
    captured: dict[str, object] = {}
    payload = valid_analysis_payload()
    idea = payload["core_ideas"][0]
    assert isinstance(idea, dict)
    idea.pop("evidence")
    idea["evidence_ids"] = ["e1"]

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]},
        )

    provider = OpenAICompatibleAnalysisProvider(
        base_url="https://api.openai.com/v1",
        api_key="secret",
        model="gpt-5-mini",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    draft = provider.generate(
        ChapterSource(
            id=1,
            book_id="book-1",
            title="第一章",
            source_start_page=1,
            source_end_page=1,
            text="作者用可回查的原文建立可信结论。",
        ),
        BookContext(
            evidence_blocks=[
                EvidenceBlock(
                    id="e1",
                    chapter_id=1,
                    chapter_title="第一章",
                    page=1,
                    quote="作者用可回查的原文建立可信结论。",
                    surrounding_text="作者用可回查的原文建立可信结论。",
                    paragraph_id="e1p1",
                )
            ]
        ),
    )

    assert draft.core_ideas[0].evidence_ids == ["e1"]
    assert draft.core_ideas[0].evidence == []
    messages = captured["messages"]
    assert isinstance(messages, list)
    assert "evidence_ids" in messages[0]["content"]
    assert "【段落 e1p1｜第 1 页】\n[e1] 作者用可回查的原文建立可信结论。" in messages[1]["content"]


def test_evidence_catalogue_prompt_groups_adjacent_blocks_by_paragraph() -> None:
    context = BookContext(
        evidence_blocks=[
            EvidenceBlock("e1", 1, "第一节", 18, "甲句。", "甲句。乙句。", "ep1"),
            EvidenceBlock("e2", 1, "第一节", 18, "乙句。", "甲句。乙句。", "ep1"),
        ]
    )

    assert _evidence_catalogue_block(context) == (
        "【当前章节证据目录】\n【段落 ep1｜第 18 页】\n[e1] 甲句。\n[e2] 乙句。"
    )


def test_evidence_catalogue_prompt_groups_related_blocks_by_paragraph() -> None:
    context = BookContext(
        related_evidence_blocks=[
            EvidenceBlock("x1", 2, "第二节", 24, "丙句。", "丙句。丁句。", "xp1"),
            EvidenceBlock("x2", 2, "第二节", 24, "丁句。", "丙句。丁句。", "xp1"),
        ]
    )

    assert _evidence_catalogue_block(context) == (
        "【当前章节证据目录】\n（无可选证据）\n"
        "【关联证据目录】\n【关联段落 xp1｜第二节｜第 24 页】\n[x1] 丙句。\n[x2] 丁句。"
    )


def test_draft_limit_keeps_three_selected_evidence_ids() -> None:
    payload = valid_analysis_payload()
    idea = payload["core_ideas"][0]
    assert isinstance(idea, dict)
    idea["evidence_ids"] = ["e1", "e2", "e3", "e4"]
    idea.pop("evidence")

    limited = _limit_draft_to_budget(
        ChapterAnalysisDraft.model_validate(payload), analysis_budget_for_text("正文")
    )

    assert limited.core_ideas[0].evidence_ids == ["e1", "e2", "e3"]


def test_provider_normalizes_safe_deepseek_json_type_variants() -> None:
    payload = valid_analysis_payload()
    payload["argument_chain"] = "提出问题 → 检查证据 → 形成结论"
    payload["estimated_reading_minutes"] = 2.5
    idea = payload["core_ideas"][0]
    assert isinstance(idea, dict)
    idea["reasoning_steps"] = "定位；核对；发布"
    idea["examples"] = "信用卡支付可能面临拒付风险。"
    idea["caveats"] = "AI 解释不等于作者原话。"
    idea["relations"] = "为后续结论提供证据基础。"
    idea["confidence"] = "high"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]},
        )

    provider = OpenAICompatibleAnalysisProvider(
        base_url="https://api.deepseek.com",
        api_key="secret",
        model="deepseek-v4-pro",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    draft = provider.generate(
        ChapterSource(
            id=1,
            book_id="book-1",
            title="第一章",
            source_start_page=1,
            source_end_page=1,
            text="作者用可回查的原文建立可信结论。",
        )
    )

    assert [statement.text for statement in draft.argument_chain] == ["提出问题", "检查证据", "形成结论"]
    assert draft.estimated_reading_minutes == 3
    assert draft.core_ideas[0].reasoning_steps == ["定位", "核对", "发布"]
    assert draft.core_ideas[0].examples == ["信用卡支付可能面临拒付风险。"]
    assert draft.core_ideas[0].confidence == 0.8


def test_provider_generates_book_overview_from_chapter_drafts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"core_question": "全书如何建立可信结论？", "one_sentence_summary": "证据先于结论。"},
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
        )

    provider = OpenAICompatibleAnalysisProvider(
        base_url="https://api.openai.com/v1",
        api_key="secret",
        model="gpt-5-mini",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    overview = provider.generate_book_overview([])

    assert overview.core_question == "全书如何建立可信结论？"
    assert overview.one_sentence_summary == "证据先于结论。"


def test_provider_normalizes_a_single_object_wrapped_in_overview_array() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                [{"core_question": "全书如何建立可信结论？", "one_sentence_summary": "证据先于结论。"}],
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
        )

    provider = OpenAICompatibleAnalysisProvider(
        base_url="https://api.deepseek.com",
        api_key="secret",
        model="deepseek-v4-pro",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    overview = provider.generate_book_overview([])

    assert overview.core_question == "全书如何建立可信结论？"


def test_provider_uses_first_overview_object_from_multiple_candidates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                [
                                    {"core_question": "第一个问题", "one_sentence_summary": "第一个结论。"},
                                    {"core_question": "第二个问题", "one_sentence_summary": "第二个结论。"},
                                ],
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
        )

    provider = OpenAICompatibleAnalysisProvider(
        base_url="https://api.deepseek.com",
        api_key="secret",
        model="deepseek-v4-pro",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    overview = provider.generate_book_overview([])

    assert overview.core_question == "第一个问题"


def test_provider_prompts_for_content_driven_idea_count() -> None:
    captured: dict[str, object] = {}
    payload = valid_analysis_payload()
    payload["argument_chain"] = [f"步骤 {index}" for index in range(9)]
    idea = payload["core_ideas"][0]
    assert isinstance(idea, dict)
    # 模型返回 6 个观点（正好等于全局上限），应全部保留、不被误伤。
    payload["core_ideas"] = [dict(idea, title=f"观点 {index}") for index in range(6)]

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]},
        )

    provider = OpenAICompatibleAnalysisProvider(
        base_url="https://api.deepseek.com",
        api_key="secret",
        model="deepseek-v4-pro",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    draft = provider.generate(
        ChapterSource(
            id=1,
            book_id="book-1",
            title="长章节",
            source_start_page=1,
            source_end_page=1,
            text="可回查正文。" * 2_000,
        )
    )

    messages = str(captured["messages"])
    # prompt 不再强制精确数量，而是给出 1~6 的区间并强调按内容判断。
    assert "输出 1 到 6 个核心思想" in messages
    assert "与篇幅长短无关" in messages
    # 等于上限的观点全部保留；超额的论证链被软截断到 7 步。
    assert len(draft.core_ideas) == 6
    assert len(draft.argument_chain) == 7


def test_normalizes_safe_numeric_importance_and_null_evidence_context() -> None:
    payload = valid_analysis_payload()
    idea = payload["core_ideas"][0]
    assert isinstance(idea, dict)
    idea["importance"] = 0.9
    evidence = idea["evidence"][0]
    assert isinstance(evidence, dict)
    evidence["surrounding_text"] = None

    normalized = normalize_chapter_analysis_payload(json.dumps(payload, ensure_ascii=False))
    assert isinstance(normalized, dict)
    draft = ChapterAnalysisDraft.model_validate(normalized)

    assert draft.core_ideas[0].importance == "0.9"
    assert draft.core_ideas[0].evidence[0].surrounding_text == ""


def test_round_robin_provider_alternates_accounts_per_chapter() -> None:
    class NamedProvider:
        def __init__(self, name: str) -> None:
            self.model = name

        def generate(self, chapter: ChapterSource) -> ChapterAnalysisDraft:
            payload = valid_analysis_payload()
            payload["chapter_question"] = self.model
            return ChapterAnalysisDraft.model_validate(payload)

        def generate_book_overview(self, chapters):  # type: ignore[no-untyped-def]
            raise AssertionError("not used")

    provider = RoundRobinAnalysisProvider([NamedProvider("account-a"), NamedProvider("account-b")])
    source = ChapterSource(id=1, book_id="book-1", title="第一章", source_start_page=1, source_end_page=1, text="正文")

    assert provider.generate(source).chapter_question == "account-a"
    assert provider.generate(source).chapter_question == "account-b"
    assert provider.generate(source).chapter_question == "account-a"


def test_round_robin_provider_excludes_an_account_after_payment_required() -> None:
    class PaymentRequiredProvider:
        model = "deepseek-v4-flash"

        def __init__(self) -> None:
            self.calls = 0

        def generate(self, chapter: ChapterSource) -> ChapterAnalysisDraft:
            self.calls += 1
            raise AnalysisProviderError(
                "模型调用失败：Client error '402 Payment Required' for url 'https://api.deepseek.com/chat/completions'"
            )

    class NamedProvider:
        model = "deepseek-v4-flash"

        def __init__(self) -> None:
            self.calls = 0

        def generate(self, chapter: ChapterSource) -> ChapterAnalysisDraft:
            self.calls += 1
            payload = valid_analysis_payload()
            payload["chapter_question"] = "可用账号"
            return ChapterAnalysisDraft.model_validate(payload)

    unavailable = PaymentRequiredProvider()
    available = NamedProvider()
    provider = RoundRobinAnalysisProvider([unavailable, available])  # type: ignore[arg-type]
    source = ChapterSource(id=1, book_id="book-1", title="第一章", source_start_page=1, source_end_page=1, text="正文")

    assert provider.generate(source).chapter_question == "可用账号"
    assert provider.generate(source).chapter_question == "可用账号"
    assert unavailable.calls == 1
    assert available.calls == 2


def test_out_of_range_reading_minutes_is_clamped_not_rejected() -> None:
    """Regression: a wild estimated_reading_minutes reached pydantic unchanged and
    failed `le=15`, discarding the whole chapter over one cosmetic field."""
    payload = valid_analysis_payload()
    payload["estimated_reading_minutes"] = 999

    normalized = normalize_chapter_analysis_payload(json.dumps(payload))
    draft = ChapterAnalysisDraft.model_validate(normalized)

    assert draft.estimated_reading_minutes == 15


def test_zero_reading_minutes_is_raised_to_the_minimum() -> None:
    payload = valid_analysis_payload()
    payload["estimated_reading_minutes"] = 0

    draft = ChapterAnalysisDraft.model_validate(normalize_chapter_analysis_payload(json.dumps(payload)))

    assert draft.estimated_reading_minutes == 1


def test_normalizes_list_role_in_book_to_its_first_attributed_statement() -> None:
    """A single display slot must tolerate a model wrapping its object in a list."""
    payload = valid_analysis_payload()
    payload["role_in_book"] = [
        {
            "text": "为后续章节建立制度背景。",
            "content_type": "ai_synthesis",
            "evidence_ids": ["e1", "x1"],
        }
    ]

    draft = ChapterAnalysisDraft.model_validate(normalize_chapter_analysis_payload(json.dumps(payload)))

    assert draft.role_in_book is not None
    assert draft.role_in_book.text == "为后续章节建立制度背景。"
    assert draft.role_in_book.evidence_ids == ["e1", "x1"]


def test_unparseable_confidence_falls_back_instead_of_failing() -> None:
    payload = valid_analysis_payload()
    payload["core_ideas"][0]["confidence"] = "very high"

    draft = ChapterAnalysisDraft.model_validate(normalize_chapter_analysis_payload(json.dumps(payload)))

    assert 0.0 <= draft.core_ideas[0].confidence <= 1.0


def test_percentage_confidence_above_one_is_clamped() -> None:
    payload = valid_analysis_payload()
    payload["core_ideas"][0]["confidence"] = "150%"

    draft = ChapterAnalysisDraft.model_validate(normalize_chapter_analysis_payload(json.dumps(payload)))

    assert draft.core_ideas[0].confidence == 1.0


def test_negative_confidence_is_clamped_to_zero() -> None:
    payload = valid_analysis_payload()
    payload["core_ideas"][0]["confidence"] = -0.5

    draft = ChapterAnalysisDraft.model_validate(normalize_chapter_analysis_payload(json.dumps(payload)))

    assert draft.core_ideas[0].confidence == 0.0


def test_legacy_caveats_are_read_as_author_stated_boundaries() -> None:
    """A model that ignores the author/ai split still returns one `caveats` list.

    Dropping it would lose real boundaries the author wrote, so it is treated as
    author-stated rather than discarded.
    """
    payload = valid_analysis_payload()
    payload["core_ideas"][0]["caveats"] = ["只适用于小团队"]
    payload["core_ideas"][0].pop("author_caveats", None)

    draft = ChapterAnalysisDraft.model_validate(normalize_chapter_analysis_payload(json.dumps(payload)))

    assert draft.core_ideas[0].author_caveats == ["只适用于小团队"]


def test_explicit_author_caveats_are_not_overwritten_by_legacy_field() -> None:
    payload = valid_analysis_payload()
    payload["core_ideas"][0]["caveats"] = ["旧字段"]
    payload["core_ideas"][0]["author_caveats"] = ["作者原话"]

    draft = ChapterAnalysisDraft.model_validate(normalize_chapter_analysis_payload(json.dumps(payload)))

    assert draft.core_ideas[0].author_caveats == ["作者原话"]


def test_warrant_returned_as_a_list_is_flattened_not_rejected() -> None:
    """warrant is advisory, so a shape mismatch must not fail the whole chapter."""
    payload = valid_analysis_payload()
    payload["core_ideas"][0]["warrant"] = ["读者认可效率优先", "组织愿意承担短期成本"]

    draft = ChapterAnalysisDraft.model_validate(normalize_chapter_analysis_payload(json.dumps(payload)))

    assert draft.core_ideas[0].warrant == "读者认可效率优先；组织愿意承担短期成本"


def test_missing_warrant_leaves_the_chapter_publishable() -> None:
    payload = valid_analysis_payload()
    payload["core_ideas"][0].pop("warrant", None)

    draft = ChapterAnalysisDraft.model_validate(normalize_chapter_analysis_payload(json.dumps(payload)))

    assert draft.core_ideas[0].warrant == ""


def test_over_long_warrant_is_truncated_by_the_budget() -> None:
    payload = valid_analysis_payload()
    payload["core_ideas"][0]["warrant"] = "前" * 400

    draft = ChapterAnalysisDraft.model_validate(normalize_chapter_analysis_payload(json.dumps(payload)))
    limited = _limit_draft_to_budget(draft, analysis_budget_for_text("正文"))

    assert len(limited.core_ideas[0].warrant) == 160


def test_prompt_defines_every_content_type_the_schema_accepts() -> None:
    """The schema accepts four content types but the prompt used to explain only
    three. book_example was undefined, so the model had no way to know when to
    use it — while the verifier exempted it from needing a quote."""
    for content_type in ("book_claim", "book_example", "ai_explanation", "ai_inference"):
        assert content_type in CHAPTER_ANALYSIS_SYSTEM_PROMPT


def test_prompt_states_the_limits_the_code_enforces() -> None:
    """Guards against prompt/code drift: whenever a cap changes, the prompt has to
    change with it, otherwise the model keeps writing output we silently trim."""
    for cap in (
        MAX_QUOTE_CHARACTERS,
        MAX_EXPLANATION_CHARACTERS,
        MAX_LIST_ITEM_CHARACTERS,
        MAX_LIST_ITEMS,
        MAX_EVIDENCE_PER_IDEA,
        MIN_READING_MINUTES,
        MAX_READING_MINUTES,
    ):
        assert str(cap) in CHAPTER_ANALYSIS_SYSTEM_PROMPT


def test_prompt_states_the_exact_original_evidence_block_soft_target_and_hard_maximum() -> None:
    assert (
        f"原文证据块以 {SOFT_BLOCK_CHARACTERS} 个字符为软目标，"
        f"任何原文证据块不得超过 {HARD_BLOCK_CHARACTERS} 个字符的硬上限"
        in CHAPTER_ANALYSIS_SYSTEM_PROMPT
    )


def test_prompt_forbids_the_deprecated_caveats_field() -> None:
    """caveats is still read for stored analyses, but new output must use the two
    split fields; leaving it unmentioned invited models to fill both."""
    assert "不要输出 caveats 字段" in CHAPTER_ANALYSIS_SYSTEM_PROMPT
    assert "author_caveats" in CHAPTER_ANALYSIS_SYSTEM_PROMPT
    assert "ai_caveats" in CHAPTER_ANALYSIS_SYSTEM_PROMPT


def test_prompt_keeps_advisory_fields_from_changing_content_type() -> None:
    """Both warrant and ai_caveats are our own additions. Without an explicit
    carve-out the model demotes the whole idea to ai_inference, and a real
    quotation loses its evidence link."""
    assert CHAPTER_ANALYSIS_SYSTEM_PROMPT.count("不影响 content_type") >= 2


def test_prompt_requires_at_least_one_idea_even_without_evidence() -> None:
    """core_ideas has a minimum length of 1, so telling the model to omit ideas it
    cannot source would make an unsourceable chapter fail validation instead of
    being recorded as insufficient_evidence."""
    assert "至少要有 1 条" in CHAPTER_ANALYSIS_SYSTEM_PROMPT
    assert "ai_inference" in CHAPTER_ANALYSIS_SYSTEM_PROMPT
