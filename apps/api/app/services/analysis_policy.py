from dataclasses import dataclass
import re


MINIMUM_SOURCE_CHARACTERS = 400

# 核心思想的数量由「本章讲了几件独立的事」决定，而不是篇幅长短。
# 因此不再按字数分档给出精确数量，只保留一个全局宽松上限用于兜底（防止超长章节输出爆炸），
# 以及一个软下限（至少 1 个，不强制凑数）。模型按实际独立观点数量在 [min, max] 区间内自行决定。
MIN_CORE_IDEAS = 1
MAX_CORE_IDEAS = 6
MAX_ARGUMENT_STEPS = 7

# 解析器直接从原书导航里读出来的分类。front/back matter 是作者刻意放在正文之外的内容
# （版权页、参考文献、后记），不该参与全书核心观点的提炼。
NON_BODY_NAV_KINDS = frozenset({"front_matter", "back_matter"})

# 纯导航/版权类页面：没有任何可概述的内容，无论多长都不值得调模型。
# 「目录」尤其要注意——它的字数可能很多，但全是章节标题。
STRUCTURE_ONLY_TITLE = re.compile(
    r"^(封面|书名页|版权页|版权|目录|扉页|献词|题献|参考文献|注释|注解|索引"
    r"|附录|附表|附图)$"
)
STRUCTURE_ONLY_PREFIX = re.compile(
    r"^(附录|附表|附图|参考文献|注释)([\s:：]|[一二三四五六七八九十百千零〇\d])"
    r"|^第[一二三四五六七八九十百]+卷$"
)

# 兜底用：原书没有导航信息时（PDF、导航损坏的 EPUB）只能靠标题判断。
# 用整词匹配，避免「结语」和「结束语」互相污染。
NON_BODY_TITLE = re.compile(
    r"^(封面|书名页|版权页|版权|目录|扉页|献词|题献|出版说明|内容简介|作者简介"
    r"|参考文献|注释|注解|索引|后记|致谢|鸣谢|结束语|出版后记|译后记|跋"
    r"|推荐语|推荐序|序|代序)$"
)
NON_BODY_TITLE_PREFIX = re.compile(
    r"^(附录|附表|附图|参考文献|注释)([\s:：]|[一二三四五六七八九十百千零〇\d])"
    r"|^第[一二三四五六七八九十百]+卷"
)


@dataclass(frozen=True)
class AnalysisBudget:
    max_core_ideas: int
    max_argument_steps: int
    min_core_ideas: int = MIN_CORE_IDEAS


@dataclass(frozen=True)
class ChapterAnalysisDecision:
    should_generate: bool
    reason: str | None = None
    budget: AnalysisBudget | None = None
    # 非正文章节仍然给用户一句话概述，但不抽核心观点、不计入全书结论。
    summary_only: bool = False


def classify_chapter_source(
    *,
    title: str,
    text: str,
    nav_kind: str | None = None,
    in_body: bool | None = None,
    structural_role: str | None = None,
    analysis_role: str = "analysis_unit",
) -> ChapterAnalysisDecision:
    """判断一个章节要不要做完整分析。

    优先采信解析器从原书导航里读到的分类（nav_kind / in_body），只有拿不到时才回退到
    标题规则。这样「参考文献」这类内容即使篇幅比正文还长，也不会被当成正文来抽观点。
    """
    if analysis_role == "outline_only":
        return ChapterAnalysisDecision(should_generate=False, reason="目录分组，不重复分析")
    source_characters = len(re.sub(r"\s+", "", text))
    if _is_non_body(
        title=title,
        nav_kind=nav_kind,
        in_body=in_body,
        structural_role=structural_role,
    ):
        if _is_structure_only(title):
            # 目录/版权页/参考文献这类页面即使很长也全是标题或条目，概述它没有意义。
            return ChapterAnalysisDecision(should_generate=False, reason="结构页，无需分析")
        if source_characters < MINIMUM_SOURCE_CHARACTERS:
            return ChapterAnalysisDecision(should_generate=False, reason="非正文内容且缺少可学习正文")
        # 有实际内容的非正文章节（前言、后记、致谢）值得给一句话概述，
        # 但它们的观点不属于作者的核心论证，所以不进核心观点。
        return ChapterAnalysisDecision(
            should_generate=False,
            reason="非正文内容，仅作概述",
            summary_only=True,
        )
    if source_characters < MINIMUM_SOURCE_CHARACTERS:
        return ChapterAnalysisDecision(should_generate=False, reason="正文不足 400 个字符")
    return ChapterAnalysisDecision(True, budget=analysis_budget_for_text(text))


def analysis_budget_for_text(text: str) -> AnalysisBudget:
    # 数量不再与字数强绑定：统一给一个宽松的全局上限，实际数量交由模型按内容判断。
    # text 参数保留以维持调用方签名兼容，当前不参与数量计算。
    del text
    return AnalysisBudget(
        max_core_ideas=MAX_CORE_IDEAS,
        max_argument_steps=MAX_ARGUMENT_STEPS,
        min_core_ideas=MIN_CORE_IDEAS,
    )


def _is_non_body(
    *,
    title: str,
    nav_kind: str | None,
    in_body: bool | None,
    structural_role: str | None,
) -> bool:
    if structural_role in NON_BODY_NAV_KINDS:
        return True
    if structural_role == "body":
        return False
    if nav_kind in NON_BODY_NAV_KINDS:
        return True
    # in_body 为 False 时同样是解析器的明确判断；只在两者都缺失时才猜。
    if in_body is False:
        return True
    if nav_kind or in_body is not None:
        return False
    return _is_structure_title(title)


def _is_structure_only(title: str) -> bool:
    """判断是不是纯导航/索引页——这类页面无论多长都没有可概述的内容。"""
    normalized = re.sub(r"\s+", "", title)
    return bool(STRUCTURE_ONLY_TITLE.match(normalized) or STRUCTURE_ONLY_PREFIX.match(normalized))


def _is_structure_title(title: str) -> bool:
    normalized = re.sub(r"\s+", "", title)
    return bool(NON_BODY_TITLE.match(normalized) or NON_BODY_TITLE_PREFIX.match(normalized))
