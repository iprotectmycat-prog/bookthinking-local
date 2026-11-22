import json
import httpx
import pytest
from app.services.analysis_providers import ChapterSource, BookContext, OverviewChapterInput
from app.services.evidence_catalog import build_evidence_catalogue
from app.services.skill_analysis import SkillAnalysisProvider, plan_reading_units, protocol_signature
from tests.services.test_analysis_generation import confirmed_repository, StaticAnalysisProvider
from app.services.analysis_generation import AnalysisGenerationService, generate_chapter_batch


def teaching_payload():
    return {
        "chapter_summary": "本章说明结论需要原文依据。引用存在与支持结论是两个检查。核对支持关系才能识别过度推断。",
        "organizing_logic": "从定位原文到核对支持关系，逐步说明如何建立可信结论。",
        "topics": [{"title": "理解证据为何重要", "content_kind": "argument",
                    "key_understanding": "结论须有依据。", "explanation": "先定位原文，再判断支持关系。",
                    "evidence_ids": ["e1"]}],
        "takeaway": "引用存在与支持结论是两个检查。",
        "open_question": {"question": "如果来源相同，解释还能有哪些差别？",
                          "attribution": "ai_extension", "basis_evidence_ids": ["e1"]},
        "coverage": [{"source_unit": 1, "topic_indices": [1]}],
    }


def author_case_payload(evidence_id="e1"):
    return {"title": "作者的项目案例", "attribution": "author_case",
            "description": "作者描述项目如何融资。", "illustrates": "说明未来收益如何支持当期投资。",
            "evidence_ids": [evidence_id]}


def chapter_outline_payload(evidence_id="e1"):
    return {
        "focus": "解释各环节如何相接",
        "organizing_logic": "先说明条件，再解释怎样完成流程。",
        "parts": [{"subject": "什么条件下可以完成流程？", "method": "custom",
                   "key_understanding": "具备前置条件后，依序完成各步才能得到预期结果。",
                   "explanation_order": ["交代条件", "依次解释各步"],
                   "evidence_ids": [evidence_id]}],
    }


def provider_for(responses, requests):
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(responses.pop(0), ensure_ascii=False)}}]})
    return SkillAnalysisProvider(base_url="https://model.test", api_key="test", model="test",
                                 client=httpx.Client(transport=httpx.MockTransport(respond)))


def test_batch_passes_book_context_and_source_backed_custom_outline_into_writing(tmp_path):
    from app.services.analysis_providers import RoundRobinAnalysisProvider

    repository, chapter_id = confirmed_repository(tmp_path)
    repository.set_book_genre("book-1", genre="narrative", confidence=0.9, source="user")
    profile = {"genre_tendency": "propositional", "focus": "可信结论如何建立",
               "approach": "用原文说明条件", "route": "从材料到结论"}
    outline = chapter_outline_payload()
    note = {"title": "内部记录", "content_kind": "process", "explanation": "按步骤展开。",
            "evidence_ids": ["e1"]}
    summary = {"chapter_question": "怎样完成？", "conclusion_evidence_ids": ["e1"],
               "support_review": "核对", "teaching": teaching_payload()}
    requests = []
    brief = {"subject": "本章讨论怎样完成流程。", "finding": "按步骤完成。", "carry_forward": "后续需要保留前置条件。",
             "evidence_ids": ["e1"]}
    provider = RoundRobinAnalysisProvider([provider_for([note, brief, profile, outline, summary, summary], requests)])
    generate_chapter_batch(AnalysisGenerationService(repository, provider, retry_delays=()),
                           "book-1", [chapter_id], max_workers=1)

    record = repository.get_chapter_analysis("book-1", chapter_id)["reading_record"]
    assert record["book_reading_context"] == profile
    assert record["chapter_outline"] == outline
    assert repository.book_context_for_prompt("book-1")["genre"] == "narrative"
    payloads = [json.loads(request["messages"][1]["content"]) for request in requests]
    assert len(requests) == 6
    assert payloads[0]["source"]
    assert payloads[1]["units"][0]["explanation"] == note["explanation"]
    assert payloads[2]["chapter_briefs"][0]["finding"] == brief["finding"]
    assert payloads[3]["book_reading_context"] == profile
    assert payloads[3]["literal_sources"]
    assert payloads[4]["chapter_outline"] == outline
    assert payloads[5]["chapter_outline"] == outline
    assert record["chapter_brief"]["evidence_ids"] == ["e1"]


def test_batch_retry_prepares_previous_chapter_and_publishes_two_sided_role(tmp_path):
    from pathlib import Path
    from app.services.chapter_confirmation import ConfirmedChapter
    from app.services.storage import BookRepository

    repository = BookRepository(tmp_path / "book-learning.sqlite3")
    texts = ["前章定义融资条件。" * 50, "本章说明融资的后果。" * 50]
    repository.save_book_import(
        book_id="book-1", filename="sample.pdf", sha256="digest", stored_path=Path("sample.pdf"),
        status="awaiting_chapter_confirmation", diagnostics=[], pages=texts,
        chapters=[(f"章节{i}", i, i, text) for i, text in enumerate(texts, 1)],
    )
    repository.replace_confirmed_chapters("book-1", [
        ConfirmedChapter(title=f"章节{i}", source_start_page=i, source_end_page=i) for i in (1, 2)
    ])
    first, second = repository.confirmed_chapter_sources("book-1")
    note = {"title": "阅读笔记", "content_kind": "concept", "explanation": "解释", "evidence_ids": ["e1"]}
    brief = {"subject": "本章解释融资。", "finding": "融资有特定条件。",
             "carry_forward": "理解后文要保留这个条件。", "evidence_ids": ["e1"]}
    profile = {"focus": "融资", "approach": "先条件后结果", "route": "两章"}
    summary = {"chapter_question": "问题", "conclusion_evidence_ids": ["e1"], "support_review": "核对",
               "teaching": teaching_payload(),
               "role_in_book": {"text": "本章承接前文的融资条件。", "content_type": "ai_synthesis",
                                "evidence_ids": ["e1", "p1"]}}
    requests = []
    provider = provider_for([note, brief, note, brief, profile, chapter_outline_payload(), summary, summary], requests)
    generate_chapter_batch(AnalysisGenerationService(repository, provider, retry_delays=()),
                           "book-1", [second["id"]], max_workers=1)

    payloads = [json.loads(request["messages"][1]["content"]) for request in requests]
    assert [b["chapter_id"] for b in payloads[4]["chapter_briefs"]] == [first["id"], second["id"]]
    assert payloads[5]["previous_chapter_brief"]["chapter_id"] == first["id"]
    assert payloads[6]["related_sources"][0]["id"] == "p1"
    assert repository.get_chapter_analysis("book-1", first["id"]) is None
    result = repository.get_chapter_analysis("book-1", second["id"])
    assert result["generation_status"] == "ready"
    assert {s["source_chapter_id"] for s in result["role_in_book"]["sources"]} == {first["id"], second["id"]}


def test_outline_cannot_omit_a_reading_unit():
    from app.services.analysis_providers import AnalysisProviderError

    source = ChapterSource(id=1, book_id="b", title="章", source_start_page=1,
                           source_end_page=1, text="真实原文。" * 2400)
    groups = plan_reading_units(build_evidence_catalogue(source, prefix="e").blocks)
    assert len(groups) > 1
    notes = [{"title": "记录", "content_kind": "concept", "explanation": "解释",
              "evidence_ids": [group[0].id]} for group in groups]
    requests = []
    with pytest.raises(AnalysisProviderError, match="大纲.*遗漏"):
        provider_for([*notes, chapter_outline_payload()], requests).generate_with_metrics(source)
    assert len(requests) == len(groups) + 1


@pytest.mark.parametrize("answer", [None, "   "])
def test_outline_requires_a_concrete_answer_before_writing(answer):
    from app.services.analysis_providers import AnalysisProviderError

    source = ChapterSource(id=1, book_id="b", title="章", source_start_page=1,
                           source_end_page=1, text="真实原文。")
    note = {"title": "记录", "content_kind": "concept", "explanation": "解释",
            "evidence_ids": ["e1"]}
    outline = chapter_outline_payload()
    if answer is None:
        del outline["parts"][0]["key_understanding"]
    else:
        outline["parts"][0]["key_understanding"] = answer
    summary = {"chapter_question": "问题", "conclusion_evidence_ids": ["e1"],
               "support_review": "核对", "teaching": teaching_payload()}
    requests = []
    with pytest.raises(AnalysisProviderError, match="key_understanding"):
        provider_for([note, outline, summary, summary], requests).generate_with_metrics(source)
    assert len(requests) == 2


def test_unit_plan_preserves_every_block():
    chapter = ChapterSource(id=1, book_id="b", title="机制", source_start_page=1, source_end_page=1, text="甲乙丙丁。" * 1000)
    blocks = list(build_evidence_catalogue(chapter, prefix="e").blocks)
    units = plan_reading_units(blocks, max_characters=500)
    assert len(units) > 1
    assert [b.id for u in units for b in u] == [b.id for b in blocks]
    assert "".join(b.quote for u in units for b in u) == chapter.text


def test_chapter_keeps_complete_steps_and_rich_overview_input(tmp_path):
    repository, chapter_id = confirmed_repository(tmp_path)
    requests = []
    steps = [f"第{i}步的完整解释" for i in range(1, 9)]
    responses = [
        {"title": "完整流程", "content_kind": "process", "explanation": "必要的中间环节。" * 40,
         "steps": steps, "examples": ["书中例子"], "limitations": ["仅适用于特定条件"], "evidence_ids": ["e1"], "gaps": []},
        chapter_outline_payload(),
        {"chapter_question": "如何完成流程？", "one_sentence_conclusion": "流程有八步。", "short_summary": "需要依次执行。",
         "reading_route": "从条件走向结果。", "conclusion_evidence_ids": ["e1"], "gaps": [], "support_review": "模型自检",
         "teaching": teaching_payload()},
    ]
    responses.append(responses[-1])  # Full-source review returns a checked copy.
    AnalysisGenerationService(repository, provider_for(responses, requests)).generate_chapter("book-1", chapter_id)
    result = repository.get_chapter_analysis("book-1", chapter_id)
    assert result["generation_status"] == "ready"
    record = result["reading_record"]
    assert record["units"][0]["steps"] == steps
    assert len(record["units"][0]["explanation"]) > 240
    assert record["units"][0]["sources"][0]["quote"]
    ready = repository.ready_chapter_analysis_drafts("book-1")
    assert ready[0].reading_record == record
    assert ready[0].chapter_title == "第一章"
    assert "章节讲解" in requests[0]["messages"][0]["content"]
    from app.api.routes.analyses import build_overview
    overview = build_overview(repository, "book-1", access_scope="owned")
    assert overview.chapters[0].core_idea_titles == ["理解证据为何重要"]


def test_unknown_evidence_rejects_chapter():
    source = ChapterSource(id=1,book_id="b",title="章",source_start_page=1,source_end_page=1,text="真实原文。" * 100)
    provider = provider_for([{"title":"主题", "content_kind":"concept", "explanation":"解释", "evidence_ids":["e9999"]}], [])
    with pytest.raises(Exception, match="证据"):
        provider.generate_with_metrics(source, BookContext(evidence_blocks=list(build_evidence_catalogue(source,prefix="e").blocks)))


def test_overview_uses_rich_records_and_checks_both_ends_of_relation():
    record = {"protocol":"skill-v1", "model": "test", "skill_sha256": protocol_signature(), "units":[{"title":"步骤", "explanation":"关键机制", "sources":[{"evidence_id":"e1","quote":"原文", "page":1}]}]}
    inputs = [OverviewChapterInput(chapter_id=i, content_version=1,chapter_title=f"第{i}章",chapter_question="问题",one_sentence_conclusion="结论",reading_record=record) for i in [1,2]]
    requests=[]
    provider=provider_for([{"core_question":"问题", "one_sentence_summary":"综合", "synthesis":{"reading_guide":"导读", "development_route":"展开", "themes":[{"text":"主题", "evidence_refs":["c1:e1"]}], "relations":[{"text":"两章相互修正", "evidence_refs":["c1:e1"]}], "open_questions":[]}}], requests)
    with pytest.raises(Exception,match="两章"):
        provider.generate_book_overview_with_metrics(inputs)
    assert "关键机制" in requests[0]["messages"][1]["content"]


def test_legacy_record_remains_readable(tmp_path):
    repository, chapter_id = confirmed_repository(tmp_path)
    AnalysisGenerationService(repository, StaticAnalysisProvider("作者用可回查的原文建立可信结论。")).generate_chapter("book-1",chapter_id)
    assert repository.get_chapter_analysis("book-1",chapter_id)["reading_record"] is None


def test_book_synthesis_keeps_sources_after_review_and_storage(tmp_path):
    repository, chapter_id = confirmed_repository(tmp_path)
    AnalysisGenerationService(repository, StaticAnalysisProvider("作者用可回查的原文建立可信结论。")).generate_chapter("book-1",chapter_id)
    record = {"protocol": "skill-v1", "model": "test", "skill_sha256": protocol_signature(), "units": [{"explanation": "关键机制", "sources": [
        {"evidence_id": "e1", "quote": "原文", "page": 1}]}]}
    inputs = [OverviewChapterInput(chapter_id=chapter_id, content_version=1, chapter_question="问题",
                                  one_sentence_conclusion="结论", reading_record=record)]
    response = {"core_question": "问题", "one_sentence_summary": "有依据的总论", "synthesis": {
        "reading_guide": "导读", "development_route": "路线", "themes": [
            {"text": "关键机制", "evidence_refs": [f"c{chapter_id}:e1"]}], "relations": [], "open_questions": []}}
    requests = []
    generated = provider_for([response, response], requests).generate_book_overview_with_metrics(inputs)
    assert len(requests) == 2
    assert "literal_sources" in requests[1]["messages"][1]["content"]
    repository.save_book_overview("book-1", generated.overview.core_question, generated.overview.one_sentence_summary,
                                  synthesis=generated.overview.synthesis)
    assert repository.get_book_overview("book-1")["synthesis"]["themes"][0]["sources"][0]["quote"] == "原文"


def test_protocol_switch_invalidates_existing_publication_ticket(tmp_path, monkeypatch):
    repository, _ = confirmed_repository(tmp_path)
    monkeypatch.setenv("BOOKTHINKING_ANALYSIS_PROTOCOL", "legacy")
    snapshot, _ = repository.capture_analysis_input("book-1", lambda: [])
    monkeypatch.setenv("BOOKTHINKING_ANALYSIS_PROTOCOL", "skill-v1")
    assert not repository.analysis_input_is_current(snapshot)


def test_chapter_route_accepts_a_list_without_repeating_generation():
    from app.services.skill_analysis import ChapterSynthesis
    summary = ChapterSynthesis.model_validate({
        'chapter_question': '问题', 'one_sentence_conclusion': '结论', 'short_summary': '概述',
        'reading_route': ['概念与条件', '机制与结果'],
        'conclusion_evidence_ids': ['e1'], 'gaps': [], 'support_review': '模型回查',
        'teaching': teaching_payload(),
    })
    assert summary.reading_route == '概念与条件\n机制与结果'


def test_chapter_teaching_accepts_coverage_keyed_by_source_unit():
    from app.services.skill_analysis import ChapterTeaching

    expected = ChapterTeaching.model_validate(teaching_payload())
    actual = ChapterTeaching.model_validate({
        **teaching_payload(),
        "coverage": {"1": [1]},
    })
    assert actual == expected


def test_book_rejects_obsolete_rules_before_any_model_request():
    requests = []
    provider = provider_for([], requests)
    chapter = OverviewChapterInput(chapter_id=1, content_version=1, chapter_question="问题",
        one_sentence_conclusion="结论", reading_record={"protocol": "skill-v1", "model": "test",
        "skill_sha256": "obsolete", "units": []})
    with pytest.raises(Exception, match="规则或模型"):
        provider.generate_book_overview_with_metrics([chapter])
    assert requests == []


def test_book_can_cite_source_saved_only_in_chapter_open_question():
    source = {"evidence_id": "e2", "quote": "追问的原文依据", "page": 1}
    record = {"protocol": "skill-v1", "model": "test", "skill_sha256": protocol_signature(), "units": [],
              "teaching": {"topics": [], "open_question": {"question": "改变条件会怎样？", "sources": [source]}}}
    chapter = OverviewChapterInput(chapter_id=1, content_version=1, chapter_question="问题",
        one_sentence_conclusion="认识", reading_record=record)
    response = {"core_question": "问题", "one_sentence_summary": "认识", "synthesis": {
        "reading_guide": "导读", "development_route": "展开", "themes": [
            {"text": "条件对解释的影响", "evidence_refs": ["c1:e2"]}], "relations": [], "open_questions": []}}
    result = provider_for([response, response], []).generate_book_overview_with_metrics([chapter])
    assert result.overview.synthesis["themes"][0]["sources"] == [source]


def test_chapter_review_revises_visible_unit_and_omits_duplicated_source_context(tmp_path):
    repository, chapter_id = confirmed_repository(tmp_path)
    note = {"title": "机制", "content_kind": "mechanism", "explanation": "原讲解过度概括。",
            "evidence_ids": ["e1"], "steps": [], "examples": [], "limitations": [], "gaps": []}
    revised = {**note, "explanation": "缩小到原文支持的条件下。", "limitations": ["有条件成立"]}
    summary = {"chapter_question": "问题", "one_sentence_conclusion": "有条件成立", "short_summary": "概述",
        "reading_route": "展开", "conclusion_evidence_ids": ["e1"], "support_review": "修订因果强度",
        "teaching": teaching_payload(),
        "unit_revisions": [{"unit": 1, "note": revised}]}
    requests = []
    AnalysisGenerationService(repository, provider_for([note, chapter_outline_payload(), summary, summary], requests)).generate_chapter("book-1", chapter_id)
    record = repository.get_chapter_analysis("book-1", chapter_id)["reading_record"]
    assert record["units"][0]["explanation"] == "缩小到原文支持的条件下。"
    assert record["units"][0]["sources"][0]["surrounding_text"]
    assert "surrounding_text" not in requests[2]["messages"][1]["content"]


def test_teaching_survives_storage_with_grounded_open_question(tmp_path):
    repository, chapter_id = confirmed_repository(tmp_path)
    note = {"title": "内部阅读记录", "content_kind": "argument", "explanation": "原文讲解",
            "evidence_ids": ["e1"]}
    summary = {"chapter_question": "本章聚焦什么？", "one_sentence_conclusion": "主要认识",
               "short_summary": "", "reading_route": "",
               "conclusion_evidence_ids": ["e1"], "support_review": "模型自检",
               "teaching": teaching_payload()}
    initial = json.loads(json.dumps(summary))
    initial["teaching"]["topics"][0]["explanation"] = "待来源复核修正的初稿。"
    # DeepSeek returned the complete teaching fields at the root in the real chapter run.
    initial.update(initial.pop("teaching"))
    requests = []
    AnalysisGenerationService(repository, provider_for([note, chapter_outline_payload(), initial, summary], requests)).generate_chapter("book-1", chapter_id)
    result = repository.get_chapter_analysis("book-1", chapter_id)
    assert result["generation_status"] == "ready"
    teaching = result["reading_record"]["teaching"]
    assert teaching["topics"][0]["explanation"] == "先定位原文，再判断支持关系。"
    assert teaching["topics"][0]["sources"][0]["quote"]
    assert teaching["open_question"]["attribution"] == "ai_extension"
    assert teaching["open_question"]["sources"][0]["evidence_id"] == "e1"
    assert teaching["chapter_summary"] == summary["teaching"]["chapter_summary"]
    assert teaching["organizing_logic"] == summary["teaching"]["organizing_logic"]
    assert result["one_sentence_conclusion"] == teaching["chapter_summary"]
    assert result["short_summary"] == ""
    assert result["reading_record"]["reading_route"] == ""
    assert "建立方向" in requests[2]["messages"][0]["content"]
    assert len(requests) == 4
    assert "统计对象" in requests[3]["messages"][0]["content"]
    assert "待来源复核修正的初稿。" in requests[3]["messages"][1]["content"]


def test_author_case_survives_storage_as_a_separate_attributed_object(tmp_path):
    repository, chapter_id = confirmed_repository(tmp_path)
    teaching = teaching_payload()
    teaching["topics"][0]["cases"] = [author_case_payload()]
    note = {"title": "记录", "content_kind": "mechanism", "explanation": "机制讲解", "evidence_ids": ["e1"]}
    summary = {"chapter_question": "问题", "conclusion_evidence_ids": ["e1"],
               "support_review": "自检", "teaching": teaching}
    AnalysisGenerationService(repository, provider_for([note, chapter_outline_payload(), summary, summary], [])).generate_chapter("book-1", chapter_id)
    result = repository.get_chapter_analysis("book-1", chapter_id)
    assert result["generation_status"] == "ready"
    case = result["reading_record"]["teaching"]["topics"][0]["cases"][0]
    assert case["attribution"] == "author_case"
    assert case["description"] == "作者描述项目如何融资。"
    assert case["sources"][0]["quote"]


def test_author_case_with_unknown_source_is_rejected():
    source = ChapterSource(id=1, book_id="b", title="章", source_start_page=1, source_end_page=1, text="真实原文。")
    teaching = teaching_payload()
    teaching["topics"][0]["cases"] = [author_case_payload("e9999")]
    note = {"title": "记录", "content_kind": "mechanism", "explanation": "讲解", "evidence_ids": ["e1"]}
    summary = {"chapter_question": "问题", "conclusion_evidence_ids": ["e1"], "support_review": "自检", "teaching": teaching}
    with pytest.raises(Exception, match="证据"):
        provider_for([note, chapter_outline_payload(), summary, summary], []).generate_with_metrics(source, BookContext())


def test_book_can_cite_source_saved_only_in_author_case():
    source = {"evidence_id": "e2", "quote": "作者案例的原文", "page": 1}
    record = {"protocol": "skill-v1", "model": "test", "skill_sha256": protocol_signature(), "units": [],
              "teaching": {"topics": [{"sources": [], "cases": [{"sources": [source]}]}]}}
    chapter = OverviewChapterInput(chapter_id=1, content_version=1, chapter_question="问题",
        one_sentence_conclusion="认识", reading_record=record)
    response = {"core_question": "问题", "one_sentence_summary": "认识", "synthesis": {
        "reading_guide": "导读", "development_route": "展开", "themes": [
            {"text": "作者通过案例解释机制", "evidence_refs": ["c1:e2"]}], "relations": [], "open_questions": []}}
    result = provider_for([response, response], []).generate_book_overview_with_metrics([chapter])
    assert result.overview.synthesis["themes"][0]["sources"] == [source]


def test_source_review_receives_overlong_summary_and_publishes_the_repaired_summary():
    source = ChapterSource(id=1, book_id="b", title="章", source_start_page=1,
                           source_end_page=1, text="真实原文。")
    note = {"title": "记录", "content_kind": "concept", "explanation": "解释", "evidence_ids": ["e1"]}
    summary = {"chapter_question": "问题", "one_sentence_conclusion": "旧字段不作为总结",
               "conclusion_evidence_ids": ["e1"], "support_review": "自检", "teaching": teaching_payload()}
    initial = json.loads(json.dumps(summary))
    initial["teaching"]["chapter_summary"] = "第一句。第二句。第三句。第四句。第五句。第六句。"
    requests = []
    generated = provider_for([note, chapter_outline_payload(), initial, summary], requests).generate_with_metrics(source, BookContext())
    record = generated.draft.reading_record
    assert record["teaching"]["chapter_summary"] == summary["teaching"]["chapter_summary"]
    assert record["teaching"]["summary_sentence_count"] == 3
    assert generated.draft.one_sentence_conclusion == record["teaching"]["chapter_summary"]
    review_input = json.loads(requests[3]["messages"][1]["content"])
    assert any("5句" in issue for issue in review_input["structure_issues"])


def test_summary_still_exceeding_five_sentences_after_review_is_not_published():
    source = ChapterSource(id=1, book_id="b", title="章", source_start_page=1,
                           source_end_page=1, text="真实原文。")
    note = {"title": "记录", "content_kind": "concept", "explanation": "解释", "evidence_ids": ["e1"]}
    summary = {"chapter_question": "问题", "one_sentence_conclusion": "旧字段",
               "conclusion_evidence_ids": ["e1"], "support_review": "自检", "teaching": teaching_payload()}
    summary["teaching"]["chapter_summary"] = "第一句。第二句。第三句。第四句。第五句。第六句。"
    with pytest.raises(Exception, match="总结.*5句"):
        provider_for([note, chapter_outline_payload(), summary, summary], []).generate_with_metrics(source, BookContext())


@pytest.mark.parametrize("repair_opening", [True, False])
@pytest.mark.parametrize("target", ["teaching", "unit"])
def test_review_flags_empty_chapter_signpost_and_preserves_substantive_attribution(repair_opening, target):
    from app.services.analysis_providers import AnalysisProviderError

    source = ChapterSource(id=1, book_id="b", title="章", source_start_page=1,
                           source_end_page=1, text="银行依据企业的还款能力决定是否放贷。")
    direct = "作者指出，银行依据企业的还款能力决定是否放贷。"
    signpost = "本章后半段描述了几项相互关联的措施。" + direct
    note = {"title": "记录", "content_kind": "mechanism", "explanation": direct,
            "evidence_ids": ["e1"]}
    summary = {"chapter_question": "银行如何放贷？", "conclusion_evidence_ids": ["e1"],
               "support_review": "自检", "teaching": teaching_payload()}
    summary["teaching"]["topics"][0]["explanation"] = direct
    candidate = json.loads(json.dumps(summary))
    if target == "teaching":
        candidate["teaching"]["topics"][0]["explanation"] = signpost
    else:
        summary["unit_revisions"] = [{"unit": 1, "note": note.copy()}]
        note["explanation"] = signpost
    requests = []
    provider = provider_for([note, chapter_outline_payload(), candidate,
                             summary if repair_opening else candidate], requests)
    if repair_opening:
        result = provider.generate_with_metrics(source, BookContext())
        record = result.draft.reading_record
        assert record["teaching"]["topics"][0]["explanation"] == direct
        assert record["units"][0]["explanation"] == direct
    else:
        with pytest.raises(AnalysisProviderError, match="空泛导语"):
            provider.generate_with_metrics(source, BookContext())
    review_input = json.loads(requests[3]["messages"][1]["content"])
    assert any("空泛导语" in issue for issue in review_input["structure_issues"])


@pytest.mark.parametrize("text,expected", [
    ("甲。乙！丙？", 3),
    ("甲；乙，丙。", 1),
    ("甲。乙。末句", 3),
    ("值为3.5，结论有限。", 1),
    ("The rate is 3.5. It rose. Scope matters.", 3),
    ('他写道：“需要证据。”条件仍重要。', 2),
    ("第一点……仍需核对。", 1),
])
def test_summary_sentence_guard_preserves_decimals_and_does_not_count_clauses_as_sentences(text, expected):
    from app.services.skill_analysis import summary_sentence_count
    assert summary_sentence_count(text) == expected


@pytest.mark.parametrize("field", ["chapter_summary", "organizing_logic"])
def test_teaching_requires_nonblank_summary_and_organizing_logic(field):
    from app.services.skill_analysis import ChapterTeaching
    payload = teaching_payload()
    payload[field] = "  \n  "
    with pytest.raises(ValueError, match="不能为空"):
        ChapterTeaching.model_validate(payload)


@pytest.mark.parametrize("invalid", ["question_source", "coverage", "one_sided_role"])
def test_teaching_rejects_untraceable_question_missing_coverage_and_one_sided_role(invalid):
    source = ChapterSource(id=1, book_id="b", title="章", source_start_page=1,
                           source_end_page=1, text="真实原文。")
    teaching = teaching_payload()
    summary = {"chapter_question": "问题", "one_sentence_conclusion": "认识",
               "short_summary": "", "reading_route": "",
               "conclusion_evidence_ids": ["e1"], "support_review": "自检", "teaching": teaching}
    if invalid == "question_source":
        teaching["open_question"]["basis_evidence_ids"] = ["e9999"]
    elif invalid == "coverage":
        teaching["coverage"] = []
    else:
        summary["role_in_book"] = {"text": "与下一章形成关系", "content_type": "ai_synthesis", "evidence_ids": ["e1"]}
    responses = [{"title": "记录", "content_kind": "concept", "explanation": "解释", "evidence_ids": ["e1"]},
                 chapter_outline_payload(), summary, summary]
    with pytest.raises(Exception, match="证据|覆盖|两章"):
        provider_for(responses, []).generate_with_metrics(source, BookContext())


def test_rate_limit_waits_then_retries_same_request(monkeypatch):
    from app.services import skill_analysis
    waits = []
    calls = []
    monkeypatch.setattr(skill_analysis, 'sleep', waits.append)
    def respond(request):
        calls.append(request.content)
        if len(calls) == 1:
            return httpx.Response(429, headers={'Retry-After': '12'})
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"ok": true}'}}]})
    provider = SkillAnalysisProvider(base_url='https://model.test', api_key='test', model='test',
                                    client=httpx.Client(transport=httpx.MockTransport(respond)))
    result = provider._chat_json(system='规则', user='正文')
    assert waits == [12]
    assert calls[0] == calls[1]
    assert json.loads(result.content) == {'ok': True}
