from app.services.analysis_policy import (
    MAX_ARGUMENT_STEPS,
    MAX_CORE_IDEAS,
    MIN_CORE_IDEAS,
    analysis_budget_for_text,
    classify_chapter_source,
)


def test_skips_volume_heading_with_no_substantive_source_text() -> None:
    decision = classify_chapter_source(title="第一卷 引论", text="未知")

    assert decision.should_generate is False
    assert decision.reason == "非正文内容且缺少可学习正文"


def test_skips_table_of_contents_even_when_it_is_longer_than_text_threshold() -> None:
    decision = classify_chapter_source(title="目录", text="第一卷、第二卷、第三卷。" * 60)

    assert decision.should_generate is False
    assert decision.reason == "结构页，无需分析"
    # 目录再长也全是章节标题，概述它没有意义，所以不能进 summary_only。
    assert decision.summary_only is False


def test_trusts_the_parsers_navigation_kind_over_the_title() -> None:
    """参考文献篇幅常比任何正文都长，只看字数会把它当成正文。"""
    decision = classify_chapter_source(
        title="延伸材料", text="某某著作，某出版社。" * 2_000, nav_kind="back_matter"
    )

    assert decision.should_generate is False
    assert decision.reason == "非正文内容，仅作概述"
    assert decision.summary_only is True


def test_treats_in_body_false_as_a_deliberate_exclusion() -> None:
    decision = classify_chapter_source(
        title="看不出类型的标题", text="内容。" * 2_000, in_body=False
    )

    assert decision.should_generate is False
    assert decision.summary_only is True


def test_explicit_back_matter_role_overrides_child_chapter_shape() -> None:
    decision = classify_chapter_source(
        title="后记1",
        text="作者回顾写作过程。" * 200,
        nav_kind="chapter",
        in_body=True,
        structural_role="back_matter",
    )

    assert decision.should_generate is False
    assert decision.summary_only is True
    assert decision.reason == "非正文内容，仅作概述"


def test_analyses_body_chapters_whose_titles_look_unusual() -> None:
    """解析器说它是正文就按正文处理，不让标题规则把它误判掉。"""
    decision = classify_chapter_source(
        title="序数之外的一章", text="论证内容。" * 2_000, nav_kind="chapter", in_body=True
    )

    assert decision.should_generate is True
    assert decision.summary_only is False


def test_summarises_a_preface_without_extracting_core_ideas() -> None:
    decision = classify_chapter_source(title="推荐序", text="这本书值得一读。" * 200)

    assert decision.should_generate is False
    assert decision.summary_only is True


def test_does_not_confuse_a_chapter_closing_with_the_book_afterword() -> None:
    """「结语」是章内小结（正文），「结束语」是全书后记（非正文）。"""
    closing = classify_chapter_source(title="结语", text="本章要点回顾。" * 200, nav_kind="section")
    afterword = classify_chapter_source(title="结束语", text="全书写完之后。" * 200)

    assert closing.should_generate is True
    assert afterword.summary_only is True


def test_skips_short_chapter_without_enough_source_material() -> None:
    decision = classify_chapter_source(title="第1章 一般理论", text="凯恩斯在本章简短说明这是一种一般理论。" * 10)

    assert decision.should_generate is False
    assert decision.reason == "正文不足 400 个字符"


def test_assigns_loose_global_budget_to_substantive_chapter() -> None:
    decision = classify_chapter_source(title="第2章 古典经济学的假设", text="原文内容。" * 2_000)

    assert decision.should_generate is True
    assert decision.budget is not None
    # 数量不再与字数分档：统一给全局宽松上限 + 软下限，实际数量交由模型按内容判断。
    assert decision.budget.max_core_ideas == MAX_CORE_IDEAS
    assert decision.budget.max_argument_steps == MAX_ARGUMENT_STEPS
    assert decision.budget.min_core_ideas == MIN_CORE_IDEAS


def test_budget_no_longer_depends_on_source_length() -> None:
    short = analysis_budget_for_text("短。" * 300)
    long = analysis_budget_for_text("长。" * 5_000)

    # 长短章节拿到的上限/下限完全一致，字数不再影响数量。
    assert short == long
    assert short.max_core_ideas == MAX_CORE_IDEAS
    assert short.min_core_ideas == MIN_CORE_IDEAS


def test_outline_only_parent_does_not_trigger_a_duplicate_model_call() -> None:
    decision = classify_chapter_source(
        title="第一章 日本人没有察觉到泡沫经济的崩溃",
        text="正文" * 500,
        nav_kind="chapter",
        in_body=True,
        structural_role="body",
        analysis_role="outline_only",
    )

    assert decision.should_generate is False
    assert decision.summary_only is False
    assert decision.reason == "目录分组，不重复分析"
