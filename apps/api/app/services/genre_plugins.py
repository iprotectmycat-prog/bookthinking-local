"""Genre-specific guidance layered on top of the shared core-idea prompt.

Books are classified by *argument structure*, not by subject. Biography,
business and social science are bookshop categories; they say nothing about how
the author tries to convince you, and a business book can be built like an
empirical study (The Innovator's Dilemma) or like a series of propositions
(Zero to One). Four structures cover the field, and each one maps directly onto
which fields are worth extracting.

The layering is deliberate: this module never touches the evidence rules in
CHAPTER_ANALYSIS_SYSTEM_PROMPT. Those carry the traceability guarantee and must
not vary by genre. A plugin only changes the analytical viewpoint and adds
genre-specific fields.
"""

from typing import Literal


GenreKey = Literal["narrative", "propositional", "practical", "scholarly"]

GENRE_KEYS: tuple[GenreKey, ...] = ("narrative", "propositional", "practical", "scholarly")

# Chosen when detection is unavailable or unsure. The cost of guessing wrong is
# asymmetric: reading a propositional book as practical makes the model invent
# "actionable steps" that the author never gave, while reading a practical book
# as propositional merely skips the step fields and leaves the claims intact.
DEFAULT_GENRE: GenreKey = "propositional"

GENRE_LABELS: dict[GenreKey, str] = {
    "narrative": "叙事论证（传记 / 历史 / 纪实）",
    "propositional": "命题论证（社科 / 思想 / 商业洞察）",
    "practical": "操作指导（方法论 / 工具书 / 自我管理）",
    "scholarly": "学术研究（学术专著 / 教科书 / 实证研究）",
}

# Keys each genre is allowed to contribute. Models occasionally invent fields;
# anything outside its genre's set is dropped rather than stored, so the JSON
# column cannot accumulate arbitrary keys.
GENRE_FIELD_WHITELIST: dict[GenreKey, frozenset[str]] = {
    "narrative": frozenset({"timeline_anchor", "attribution", "counterfactual"}),
    "propositional": frozenset({"grounds_type", "scope_condition", "rebuttal"}),
    "practical": frozenset({"action_steps", "precondition", "failure_mode", "applies_to"}),
    "scholarly": frozenset(
        {"research_question", "method", "data_basis", "claim_strength", "limitation"}
    ),
}

# Fields whose value is a list of strings. Everything else is coerced to a
# string, so a model returning a list where we want a sentence cannot break the
# chapter over a supplementary field.
GENRE_LIST_FIELDS: frozenset[str] = frozenset({"action_steps"})

_NARRATIVE = """【本书体裁：叙事论证类（传记 / 历史 / 纪实）】
这类书的观点很少直接写出来，而藏在「作者选择讲什么、怎么讲、讲完下什么判断」里。
你的任务不是复述发生了什么，而是找出作者通过叙述在主张什么。

分析视角（按优先级）：
1. 关键转折：本章中人物或局势发生了什么不可逆的改变？作者认为是什么导致的？
2. 因果归因：作者把结果归因于个人选择、性格、结构性条件，还是偶然？
　　归因是作者的判断而非事实，这是本章最重要的观点来源。
3. 作者的评判：作者对人物行为持什么态度？注意态度常通过用词与细节取舍表达，而非直接评论。
4. 时代约束：作者是否在说明「在当时的条件下，这个选择才可以理解」？

genre_fields 填写：
- timeline_anchor：这件事发生的时间或阶段，原文有则照抄，无则填空字符串
- attribution：作者的归因强度，取 "explicit"（明确说了成因）/ "implied"（叙述中暗示）/ "none"（只叙述不归因）
- counterfactual：作者是否讨论了「如果不这样会怎样」，有则一句话，无则空字符串

不要这样做：
✗ 把「某年某人做了某事」当成核心思想 —— 这是事实，不是观点
✗ 按时间顺序复述本章内容 —— 那是摘要，不是观点提取
✗ 把作者引用的他人评价当作者观点，除非作者表示认同
✓ 正例：「作者认为马斯克的产品直觉源于他把工程问题当物理问题处理，而非商业训练」"""

_PROPOSITIONAL = """【本书体裁：命题论证类（社科 / 思想 / 商业洞察）】
这类书作者会明确提出主张并给论据，是最标准的论证结构。
按 主张 → 论据 → 隐含前提 → 适用边界 的骨架拆解。

分析视角（按优先级）：
1. 主张：作者在本章要让你接受什么判断？用作者自己的表述强度，不要替他加强或削弱。
2. 论据：作者用什么支撑它？论据类型直接决定这个主张有多可靠。
3. 隐含前提：从论据到主张，作者依赖了什么没明说的假设？写进 warrant。
4. 适用边界：作者说这个主张在什么条件下成立、什么情况下不成立？

genre_fields 填写：
- grounds_type：论据类型，取 "empirical" / "case" / "analogy" / "authority"
　　/ "thought_experiment" / "deduction" / "none"
- scope_condition：作者说明的适用条件，无则空字符串
- rebuttal：作者自己提出并回应的反对意见，无则空字符串

不要这样做：
✗ 把作者的比喻当成主张 —— 比喻是论据，不是结论
✗ 把「作者讨论了 X」写成观点 —— 要写「作者认为 X 是/不是/导致 Y」
✗ 无视作者的限定词。作者写「在多数情况下」，不要写成「总是」
✓ 正例：「作者主张组织规模扩大必然降低单位创新效率」，grounds_type="empirical"，
　　warrant="专利数量可以代表创新水平\""""

_PRACTICAL = """【本书体裁：操作指导类（方法论 / 工具书 / 自我管理）】
这类书的价值在于「能不能照着做」。读懂不等于会用，所以提取重点是可执行性而非理念。

分析视角（按优先级）：
1. 可执行规则：作者要读者具体做什么？必须是能判断「做到了没有」的动作，
　　不是「要有成长型思维」这类无法执行的表述。
2. 前置条件：这个方法需要什么资源、能力、环境、时机才有效？
3. 步骤序列：作者给了流程就按顺序列出，不要打乱也不要合并 —— 顺序本身是信息。
4. 失败信号：作者是否说明了「做错的样子」或「什么时候该放弃」？
　　这一项对读者价值极高，且最常被摘要丢掉。

genre_fields 填写：
- action_steps：有序的可执行步骤数组，每步以动词开头；作者未给流程则为 []
- precondition：使用这个方法的前置条件，无则空字符串
- failure_mode：作者说明的常见错误或失效场景，无则空字符串
- applies_to：作者指明的适用人群或场景，无则空字符串

不要这样做：
✗ 把理念当方法。「要以终为始」不是可执行规则，
　　「写下五年后的理想状态再倒推今年目标」才是
✗ 把步骤序列压缩成一句总结
✗ 漏掉前置条件 —— 缺了它，读者会在不适用的场景硬套
✓ 正例：action_steps = ["列出本周所有待办", "对每项标注是否推进长期目标", "删掉标注为否且无外部承诺的项"]"""

_SCHOLARLY = """【本书体裁：学术研究类（学术专著 / 教科书 / 实证研究）】
这类书的结论依托方法与数据，所以「结论有多强」和「结论是什么」同样重要。

分析视角（按优先级）：
1. 研究问题：本章要回答什么问题？
2. 方法与框架：作者用什么方法或理论框架来回答？
3. 证据基础：核心证据的性质与规模是什么？
4. 结论强度：作者用的是「证明」「表明」「提示」还是「不能排除」？必须照作者原文的强度词。
5. 自陈局限：作者自己承认了什么局限？

genre_fields 填写：
- research_question：本章的研究问题
- method：所用方法或理论框架，无则空字符串
- data_basis：核心证据的性质与规模，例如「1978-2015 年 32 国面板数据」
- claim_strength：取 "proves" / "indicates" / "suggests" / "cannot_rule_out"
- limitation：作者自陈的局限，无则空字符串

不要这样做：
✗ 把作者的假设当结论 —— 假设是待检验的，结论是检验后的
✗ 抹掉强度词。作者写「数据提示可能存在关联」，不要写成「数据证明了因果关系」
✗ 把文献综述里他人的观点当作者观点
✓ 正例：claim_strength="suggests"，且 limitation 保留作者自己说的「样本仅覆盖发达国家」"""

GENRE_PROMPTS: dict[GenreKey, str] = {
    "narrative": _NARRATIVE,
    "propositional": _PROPOSITIONAL,
    "practical": _PRACTICAL,
    "scholarly": _SCHOLARLY,
}


GENRE_DETECTION_SYSTEM_PROMPT = """你要判断一本书的论证骨架类型，只输出 JSON，不要 Markdown。

四类定义：
- narrative：用事件序列承载判断（传记、历史、纪实、回忆录）
- propositional：明确提出主张并用论据支撑（社科、思想、商业洞察）
- practical：核心是教读者怎么做（方法论、工具书、自我管理）
- scholarly：结论依托方法与数据（学术专著、教科书、实证研究）

判定依据的优先级：
1. 目录标题的形态。「1943年的转折」偏 narrative；「为什么组织会僵化」偏 propositional；
　　「如何设计周计划」偏 practical；「研究设计与数据来源」偏 scholarly
2. 正文样本的句式。大量时间状语和人物动作 → narrative；大量「因此/然而/这意味着」→ propositional；
　　大量第二人称和祈使句 → practical；出现方法、样本、显著性 → scholarly
3. 书名副标题与出版社，仅作辅助，不可单独定案

注意：题材不等于骨架。商业书可能是 propositional 也可能是 scholarly；
传记里若作者主要在论证方法论，应判为 propositional。
拿不准时选 propositional —— 它的提取框架最通用，判错的损失最小。

输出：{"genre": "四类之一", "confidence": 0到1的小数, "reason": "一句话依据"}"""


def resolve_genre(value: object) -> GenreKey:
    """Map a stored or model-supplied genre onto a known key, defaulting safely."""
    if isinstance(value, str) and value in GENRE_KEYS:
        return value  # type: ignore[return-value]
    return DEFAULT_GENRE


def genre_instructions(genre: object) -> str:
    return GENRE_PROMPTS[resolve_genre(genre)]


def filter_genre_fields(value: object, genre: object) -> dict[str, object]:
    """Keep only the keys this genre defines, coercing each to its declared shape.

    Without this the open dict would store whatever the model invented, and a
    reader could not tell a real field from a hallucinated one.
    """
    if not isinstance(value, dict):
        return {}
    allowed = GENRE_FIELD_WHITELIST[resolve_genre(genre)]
    filtered: dict[str, object] = {}
    for key, item in value.items():
        if key not in allowed:
            continue
        if key in GENRE_LIST_FIELDS:
            if isinstance(item, list):
                filtered[key] = [str(entry).strip() for entry in item if str(entry).strip()]
            elif isinstance(item, str) and item.strip():
                filtered[key] = [item.strip()]
            else:
                filtered[key] = []
        elif isinstance(item, list):
            filtered[key] = "；".join(str(entry).strip() for entry in item if str(entry).strip())
        elif item is None:
            filtered[key] = ""
        else:
            filtered[key] = str(item)
    return filtered
