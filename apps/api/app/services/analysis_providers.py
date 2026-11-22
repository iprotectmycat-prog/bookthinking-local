import inspect
import json
import logging
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from typing import Literal, Protocol, TypeVar

import httpx

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.analysis_policy import (
    MAX_CORE_IDEAS,
    MIN_CORE_IDEAS,
    AnalysisBudget,
    analysis_budget_for_text,
)
from app.services.genre_plugins import (
    DEFAULT_GENRE,
    GENRE_DETECTION_SYSTEM_PROMPT,
    GENRE_LABELS,
    GenreKey,
    filter_genre_fields,
    genre_instructions,
    resolve_genre,
)
from app.services.evidence_catalog import EvidenceBlock, HARD_BLOCK_CHARACTERS, SOFT_BLOCK_CHARACTERS


logger = logging.getLogger(__name__)


ProviderResult = TypeVar("ProviderResult")


def call_with_optional_context(method: object, chapter: object, context: object) -> object:
    """Invoke a provider method, passing the book context only if it takes one.

    Providers written before Layer 2 existed accept the chapter alone, and so do
    most test doubles. Checking the signature keeps them working instead of
    requiring every implementation to grow a parameter it ignores.
    """
    if not callable(method):
        raise TypeError("provider method is not callable")
    try:
        parameters = list(inspect.signature(method).parameters.values())
    except (TypeError, ValueError):
        return method(chapter)
    if any(parameter.kind is parameter.VAR_POSITIONAL for parameter in parameters):
        return method(chapter, context)
    positional = [
        parameter
        for parameter in parameters
        if parameter.kind in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD)
    ]
    return method(chapter, context) if len(positional) >= 2 else method(chapter)


class PageSource(BaseModel):
    page_number: int
    text: str


class ChapterSource(BaseModel):
    id: int
    book_id: str
    title: str
    source_start_page: int
    source_end_page: int
    text: str
    source_locator: str | None = None
    pages: list[PageSource] = Field(default_factory=list)
    # Publisher-declared placement, defaulted so a PDF or an older caller that
    # knows none of it still constructs a valid source.
    depth: int = 0
    parent_title: str | None = None
    nav_kind: str = "plain"
    in_body: bool = True
    structural_role: str = "unknown"
    role_source: str = "unknown"
    role_confidence: str = "low"
    analysis_role: str = "analysis_unit"


class EvidenceDraft(BaseModel):
    page: int
    quote: str
    surrounding_text: str = ""
    source_chapter_id: int | None = None


class CoreIdeaDraft(BaseModel):
    title: str
    conclusion: str
    importance: str
    explanation: str
    reasoning_steps: list[str]
    examples: list[str] = Field(default_factory=list)
    # Kept for stored analyses written before caveats were split in two. New
    # output populates author_caveats/ai_caveats instead; see normalize below.
    caveats: list[str] = Field(default_factory=list)
    # A boundary the author stated themselves, so it carries their authority.
    author_caveats: list[str] = Field(default_factory=list)
    # A limitation we noticed that the author never raised.
    ai_caveats: list[str] = Field(default_factory=list)
    relations: list[str] = Field(default_factory=list)
    # The unstated assumption bridging grounds and conclusion (Toulmin's
    # warrant). Always our inference, so it never needs a quote and must not
    # change content_type.
    warrant: str = ""
    # Fields that exist only for one argument structure, e.g. action_steps for a
    # how-to book. An open dict rather than four optional sub-models, so adding a
    # genre needs no schema change; normalize filters it against a whitelist to
    # recover the validation this gives up.
    genre_fields: dict[str, object] = Field(default_factory=dict)
    content_type: Literal["book_claim", "book_example", "ai_explanation", "ai_inference", "ai_synthesis"]
    confidence: float = Field(ge=0, le=1)
    # New providers select an immutable local block instead of copying a quote.
    evidence_ids: list[str] = Field(default_factory=list)
    # Retained only for providers and tests written before evidence selection.
    evidence: list[EvidenceDraft] = Field(default_factory=list)


class AttributedStatementDraft(BaseModel):
    """A displayed chapter-level statement with an explicit provenance boundary."""

    text: str
    content_type: Literal["book_summary", "ai_synthesis"]
    evidence_ids: list[str] = Field(default_factory=list)


class ChapterAnalysisDraft(BaseModel):
    model_config = ConfigDict(validate_assignment=True)
    reading_record: dict[str, object] | None = None
    chapter_question: str
    one_sentence_conclusion: str
    short_summary: str
    argument_chain: list[AttributedStatementDraft]
    role_in_book: AttributedStatementDraft | None = None
    estimated_reading_minutes: int = Field(ge=1, le=15)
    core_ideas: list[CoreIdeaDraft] = Field(min_length=MIN_CORE_IDEAS, max_length=MAX_CORE_IDEAS)

    @field_validator("argument_chain", mode="before")
    @classmethod
    def _coerce_legacy_argument_chain(cls, value: object) -> object:
        if not isinstance(value, list):
            value = _as_text_list(value)
        if not isinstance(value, list):
            return value
        return [
            {"text": item, "content_type": "book_summary", "evidence_ids": []}
            if isinstance(item, str)
            else item
            for item in value
        ]

    @field_validator("role_in_book", mode="before")
    @classmethod
    def _coerce_legacy_role(cls, value: object) -> object:
        if isinstance(value, str):
            return {"text": value, "content_type": "book_summary", "evidence_ids": []}
        return value


class OverviewChapterInput(BaseModel):
    chapter_title: str = ""
    parent_title: str | None = None
    nav_kind: str = "plain"
    reading_record: dict[str, object] | None = None
    chapter_id: int
    content_version: int
    chapter_question: str
    one_sentence_conclusion: str
    role_in_book: str = ""
    role_content_type: Literal["book_summary", "ai_synthesis", "legacy_summary"] | None = None


def overview_role_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict) and isinstance(value.get("text"), str):
        return value["text"].strip()
    return ""


class BookOverviewDraft(BaseModel):
    synthesis: dict[str, object] | None = None
    core_question: str
    one_sentence_summary: str


@dataclass(frozen=True)
class ChatJsonResponse:
    content: str
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    thinking: str | None = None


class ChapterBrief(BaseModel):
    subject: str = Field(min_length=1)
    finding: str = Field(min_length=1)
    carry_forward: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)

    @field_validator("subject", "finding", "carry_forward")
    @classmethod
    def strip_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("章节短概括不能为空")
        return value.strip()


@dataclass(frozen=True)
class ChapterReading:
    units: list[dict]
    brief: ChapterBrief
    responses: list[ChatJsonResponse]


class BookReadingContext(BaseModel):
    """A provisional reading orientation based on chapter briefs and book material."""

    genre_tendency: GenreKey | None = None
    focus: str = Field(min_length=1)
    approach: str = Field(min_length=1)
    route: str = Field(min_length=1)


class BookContext(BaseModel):
    """Book facts and prepared reading context for a chapter prompt."""

    title: str = ""
    subtitle: str = ""
    authors: str = ""
    publisher: str = ""
    genre: str | None = None
    reading_context: BookReadingContext | None = None
    chapter_reading: ChapterReading | None = None
    previous_chapter_brief: dict | None = None
    outline: list[str] = Field(default_factory=list)
    evidence_blocks: list[EvidenceBlock] = Field(default_factory=list)
    related_evidence_blocks: list[EvidenceBlock] = Field(default_factory=list)


class GenreDecision(BaseModel):
    genre: str = DEFAULT_GENRE
    confidence: float | None = None
    reason: str = ""


@dataclass(frozen=True)
class GeneratedChapterAnalysis:
    draft: ChapterAnalysisDraft
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    output_characters: int


@dataclass(frozen=True)
class GeneratedBookOverview:
    overview: BookOverviewDraft
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    output_characters: int



class AnalysisProvider(Protocol):
    def generate(
        self, chapter: ChapterSource, context: BookContext | None = None
    ) -> ChapterAnalysisDraft: ...

    def generate_book_overview(self, chapters: list[OverviewChapterInput]) -> BookOverviewDraft: ...


class AnalysisProviderError(RuntimeError):
    pass


# Output caps. Declared here so the prompt can quote the same numbers the
# truncation code enforces; a prompt promising a limit the code does not apply
# (or vice versa) is how fields end up silently trimmed.
MAX_QUOTE_CHARACTERS = 120
MAX_EXPLANATION_CHARACTERS = 240
MAX_LIST_ITEM_CHARACTERS = 160
MAX_LIST_ITEMS = 2
MAX_EVIDENCE_PER_IDEA = 3
DEFAULT_CONFIDENCE = 0.5
MIN_READING_MINUTES = 1
MAX_READING_MINUTES = 15


# The shared core of every chapter prompt. Genre-specific guidance is layered on
# top of this; the rules here never change, because they carry the product's
# "every claim is traceable" guarantee.
CHAPTER_ANALYSIS_SYSTEM_PROMPT = f"""你是证据优先的中文书籍编辑。只根据用户提供的章节正文生成一个 JSON 对象，不要 Markdown。
输出字段必须匹配 ChapterAnalysisDraft：chapter_question、one_sentence_conclusion、short_summary、
argument_chain、role_in_book、estimated_reading_minutes、core_ideas。core_ideas 的数量由用户消息指定；
每项包含 title、conclusion、importance、explanation、reasoning_steps、examples、
author_caveats、ai_caveats、relations、warrant、genre_fields、content_type、confidence、evidence_ids。
genre_fields 是一个对象，填什么由下方【本书体裁】段指定；该体裁未列出的键不要输出。
所有 *steps、examples、author_caveats、ai_caveats、relations 都必须是 JSON 字符串数组，
例如 ["步骤一", "步骤二"]，不能是单个字符串。argument_chain 是对象数组，每项包含
text、content_type、evidence_ids；role_in_book 是同结构的一个对象或 null。
estimated_reading_minutes 必须是 {MIN_READING_MINUTES} 到 {MAX_READING_MINUTES} 的整数；
confidence 必须是 0 到 1 的小数，不能使用 high/medium/low。
evidence_ids 必须是数组；每项严格为证据目录中的 ID，例如 ["e1"]。不要输出 evidence 或 quote 字段，
更不要复制正文作为引文；应用会用你选中的 ID 回填原文与页码。
不要输出 caveats 字段，改用下面说明的 author_caveats 与 ai_caveats。

【content_type 四选一，决定是否需要引文】
book_claim：作者提出的判断。**必须**选择当前章节正文中对应的 evidence_ids。
book_example：作者用来支撑判断的具体案例、实验、数据或故事，本身来自书中。
　　同样**必须**选择当前章节的 evidence_ids——案例出自原文，读者必须能翻回去核对。
ai_explanation：你为帮助理解而做的通俗解释，evidence_ids 使用 []。
ai_inference：你综合全章做出的推断，evidence_ids 使用 []。
ai_synthesis：你连接当前章节与【关联证据目录】的综合推导。必须至少选择 2 个 evidence_ids，
其中至少一个是当前章节的 eN、一个是关联章节的 xN；这是 AI 推导，不能写成作者原话。
判断依据只有一条：**内容是否出自本章正文**。出自正文的用 book_ 前缀并附引文，
你自己加工的用 ai_ 前缀；只有跨章节且有两组证据的连接才使用 ai_synthesis。禁止用 ai_ 前缀承载正文内容来规避证据要求。
找不到对应证据 ID 时，改用 ai_explanation 或 ai_inference，不要臆造证据 ID。

【章节级陈述的归因】
argument_chain 与 role_in_book 不是自由文本。每一项必须写成
{{"text":"...","content_type":"book_summary 或 ai_synthesis","evidence_ids":["e1"]}}。
book_summary 是对本节作者内容的概述，必须选择至少一个当前章节 eN，不得包含后续章节关系。
ai_synthesis 是你连接当前章节与关联章节的推导，必须选择至少一个 eN 与一个 xN；前端会标注“AI 推导”并展示两章原文。
不能满足以上条件时，省略该项或返回 null，绝不能把跨章关系写成 book_summary。

【什么才算核心思想】
每条核心思想必须是一个「可以被赞同或反对的判断」，而不是一个「话题」。
「注意力是稀缺资源」是判断；「关于注意力」是话题，不可作为核心思想。
判断方法：如果一句话无法被人反驳，它就不是观点。

以下内容不构成核心思想，不要输出：
- 纯粹的事实陈述与数据罗列，除非作者用它支撑一个明确判断
- 对他人观点的转述，除非作者明确表示赞同或反对并给出理由
- 章节的内容预告、过渡句、承上启下段
- 对前文的重复总结，如果它没有推进出新判断
- 举例本身。例子应放进它所支撑观点的 examples 字段，不能独立成为一条核心思想

即使本章找不到任何可靠引文，core_ideas 也至少要有 1 条：
此时输出 content_type 为 ai_inference 的一条，evidence 留空，说明本章实际讲了什么。
后端会据此判定本章证据不足，你不需要也不应该返回空数组。

【隐含前提 warrant】
作者从论据推到结论时，往往依赖一个没有明说的前提。用一句话写出这个前提。
如果作者已经明确写出了该前提，warrant 填空字符串。
这一项是你的推断，不需要 quote，也不影响 content_type 的判定。

【两类边界要分开】
author_caveats：作者自己在正文里写明的适用边界、例外、反例。
　　这属于作者观点，每条都必须能在正文中找到依据。
ai_caveats：你识别出的潜在问题或适用限制，作者没有提到。
　　这是你的判断，不需要正文依据，同样不影响 content_type 的判定：
　　一条有逐字引文的作者观点，即使你补了 ai_caveats，仍然是 book_claim。
不要把两者混在一起，也不要把你的判断写进 author_caveats。

【长度上限，超出会被截断】
examples、author_caveats、ai_caveats、relations 各最多 {MAX_LIST_ITEMS} 条，
每条不超过 {MAX_LIST_ITEM_CHARACTERS} 字。warrant 不超过 {MAX_LIST_ITEM_CHARACTERS} 字。
reasoning_steps 每步不超过 {MAX_LIST_ITEM_CHARACTERS} 字。
每个核心思想最多 {MAX_EVIDENCE_PER_IDEA} 条证据 ID；
原文证据块以 {SOFT_BLOCK_CHARACTERS} 个字符为软目标，任何原文证据块不得超过 {HARD_BLOCK_CHARACTERS} 个字符的硬上限；
explanation 不超过 {MAX_EXPLANATION_CHARACTERS} 字。"""


class RoundRobinAnalysisProvider:
    """Distribute independent chapter requests across locally configured accounts."""

    def __init__(self, providers: list["OpenAICompatibleAnalysisProvider"]) -> None:
        if not providers:
            raise ValueError("至少需要一个模型账号")
        self.providers = providers
        self.model = providers[0].model
        self.analysis_protocol = getattr(providers[0], "analysis_protocol", "legacy")
        self._next_index = 0
        self._payment_required_indices: set[int] = set()
        self._lock = Lock()

    def _next_provider(self) -> tuple["OpenAICompatibleAnalysisProvider", int]:
        with self._lock:
            for _ in self.providers:
                index = self._next_index
                self._next_index = (self._next_index + 1) % len(self.providers)
                if index not in self._payment_required_indices:
                    return self.providers[index], index
        raise AnalysisProviderError("所有已配置的 DeepSeek 模型账号都需要支付或暂不可用")

    def _disable_payment_required_provider(self, index: int) -> None:
        with self._lock:
            self._payment_required_indices.add(index)

    def _call_with_payment_failover(
        self, operation: Callable[["OpenAICompatibleAnalysisProvider"], ProviderResult]
    ) -> ProviderResult:
        """Retry the same request on another account after a confirmed 402.

        The router is only constructed for a multi-Key DeepSeek setup. A 402 is
        account-level (billing/credit) rather than chapter-level, so keeping the
        account in the rotation would make unrelated chapters fail needlessly.
        Other provider errors still use the generation service's normal retry
        policy and do not permanently disable an account.
        """
        for _ in self.providers:
            provider, index = self._next_provider()
            try:
                return operation(provider)
            except AnalysisProviderError as error:
                if not _is_payment_required_error(error):
                    raise
                self._disable_payment_required_provider(index)
                logger.warning("excluding DeepSeek account after payment-required response")
        raise AnalysisProviderError("所有已配置的 DeepSeek 模型账号都需要支付或暂不可用")

    def generate(
        self, chapter: ChapterSource, context: BookContext | None = None
    ) -> ChapterAnalysisDraft:
        return self._call_with_payment_failover(
            lambda provider: call_with_optional_context(provider.generate, chapter, context)
        )

    @property
    def source_thinking_options(self) -> tuple[str, ...]:
        return self.providers[0].source_thinking_options

    def chat_about_source(self, messages: list[dict[str, str]], thinking: str) -> ChatJsonResponse:
        return self._call_with_payment_failover(lambda provider: provider.chat_about_source(messages, thinking))

    def generate_with_metrics(
        self, chapter: ChapterSource, context: BookContext | None = None
    ) -> GeneratedChapterAnalysis:
        return self._call_with_payment_failover(
            lambda provider: call_with_optional_context(provider.generate_with_metrics, chapter, context)
        )

    def detect_genre(self, context: BookContext, samples: list[str]) -> GenreDecision:
        return self._call_with_payment_failover(
            lambda provider: provider.detect_genre(context, samples)
        )

    def prepare_chapter_reading(self, chapter: ChapterSource, context: BookContext) -> ChapterReading:
        return self._call_with_payment_failover(
            lambda provider: provider.prepare_chapter_reading(chapter, context)
        )

    def prepare_book_reading_context(self, context: BookContext, chapter_briefs: list[dict],
                                     framing: list[dict]) -> BookReadingContext:
        return self._call_with_payment_failover(
            lambda provider: provider.prepare_book_reading_context(context, chapter_briefs, framing)
        )

    def generate_book_overview(self, chapters: list[OverviewChapterInput]) -> BookOverviewDraft:
        return self._call_with_payment_failover(
            lambda provider: provider.generate_book_overview(chapters)
        )

    def generate_book_overview_with_metrics(self, chapters: list[OverviewChapterInput]) -> GeneratedBookOverview:
        return self._call_with_payment_failover(
            lambda provider: provider.generate_book_overview_with_metrics(chapters)
        )


def _is_payment_required_error(error: AnalysisProviderError) -> bool:
    return bool(re.search(r"\b402\s+Payment Required\b", str(error), flags=re.IGNORECASE))


def _as_text_list(value: object) -> object:
    if isinstance(value, list):
        return value
    if not isinstance(value, str):
        return value
    items = [item.strip(" -•\t") for item in re.split(r"(?:\r?\n|→|；)", value) if item.strip(" -•\t")]
    return items or [value]


def _as_sentence(value: object) -> object:
    """Flatten a model-supplied single-sentence field that arrived as a list.

    The prompt asks for one sentence, but returning an array is a frequent model
    habit. Since these fields are advisory (warrant is our own inference and
    carries no evidence), letting a shape mismatch fail the whole chapter would
    trade real content for a cosmetic detail.
    """
    if isinstance(value, list):
        parts = [str(item).strip() for item in value if str(item).strip()]
        return "；".join(parts)
    return value


def _as_confidence(value: object) -> object:
    """Coerce a model-supplied confidence into the 0..1 range the schema allows.

    An out-of-range or unparseable confidence used to reach pydantic unchanged
    and fail validation, which threw away the *entire* chapter analysis over one
    cosmetic field. Clamping (and falling back to a neutral value) keeps the
    chapter publishable.
    """
    parsed: float | None = None
    if isinstance(value, bool):
        return DEFAULT_CONFIDENCE
    if isinstance(value, (int, float)):
        parsed = float(value)
    elif isinstance(value, str):
        text = value.strip()
        mapped = {"high": 0.8, "medium": 0.6, "low": 0.4, "高": 0.8, "中": 0.6, "低": 0.4}
        if text.lower() in mapped:
            return mapped[text.lower()]
        try:
            parsed = float(text.rstrip("%")) / (100 if text.endswith("%") else 1)
        except ValueError:
            return DEFAULT_CONFIDENCE
    if parsed is None:
        return DEFAULT_CONFIDENCE
    return min(1.0, max(0.0, parsed))


def _as_reading_minutes(value: object) -> object:
    """Clamp the estimated reading time instead of letting it fail validation."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            return value
    if isinstance(value, (int, float)):
        return min(MAX_READING_MINUTES, max(MIN_READING_MINUTES, math.ceil(value)))
    return value


def _normalize_evidence(value: object) -> object:
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return value
    normalized = []
    for item in value:
        if not isinstance(item, dict):
            continue
        page = item.get("page", item.get("source_page", item.get("page_number")))
        quote = item.get("quote", item.get("source_quote", item.get("text")))
        if isinstance(page, int) and isinstance(quote, str) and quote.strip():
            surrounding_text = item.get("surrounding_text", item.get("context", ""))
            normalized.append(
                {
                    "page": page,
                    "quote": quote,
                    "surrounding_text": surrounding_text if isinstance(surrounding_text, str) else "",
                }
            )
    return normalized


def _normalize_evidence_ids(value: object) -> object:
    if isinstance(value, list):
        return [str(item).strip() for item in value]
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[\s,，]+", value) if item.strip()]
    return value


def _normalize_statement(value: object) -> object:
    """Coerce a shallow model shape without silently inventing evidence IDs."""
    if isinstance(value, str):
        return {"text": value, "content_type": "book_summary", "evidence_ids": []}
    if not isinstance(value, dict):
        return value
    normalized = dict(value)
    if "text" in normalized and not isinstance(normalized["text"], str):
        normalized["text"] = str(normalized["text"])
    if "evidence_ids" in normalized:
        normalized["evidence_ids"] = _normalize_evidence_ids(normalized["evidence_ids"])
    return normalized


def _normalize_statements(value: object) -> object:
    values = _as_text_list(value)
    if not isinstance(values, list):
        return values
    return [_normalize_statement(item) for item in values]


def normalize_chapter_analysis_payload(content: str, *, genre: object = DEFAULT_GENRE) -> object:
    """Normalize safe JSON shape variations without manufacturing evidence."""
    payload = json.loads(content)
    if not isinstance(payload, dict):
        return payload
    if "argument_chain" in payload:
        payload["argument_chain"] = _normalize_statements(payload["argument_chain"])
    if "role_in_book" in payload:
        role_in_book = payload["role_in_book"]
        # The schema has one role slot, but some providers wrap the otherwise
        # valid statement object in a one-item array. Keep its first statement
        # rather than rejecting the entire chapter for that cosmetic mismatch.
        if isinstance(role_in_book, list):
            role_in_book = role_in_book[0] if role_in_book else None
        payload["role_in_book"] = _normalize_statement(role_in_book)
    if "estimated_reading_minutes" in payload:
        payload["estimated_reading_minutes"] = _as_reading_minutes(payload["estimated_reading_minutes"])
    ideas = payload.get("core_ideas")
    if isinstance(ideas, dict):
        ideas = [ideas]
        payload["core_ideas"] = ideas
    if not isinstance(ideas, list):
        return payload
    for idea in ideas:
        if not isinstance(idea, dict):
            continue
        if "importance" in idea and not isinstance(idea["importance"], str):
            idea["importance"] = str(idea["importance"])
        # A model that ignores the split still returns a single `caveats` list.
        # Treat those as author-stated boundaries rather than dropping them.
        if "caveats" in idea and "author_caveats" not in idea:
            idea["author_caveats"] = idea["caveats"]
        for field in ("reasoning_steps", "examples", "caveats", "author_caveats", "ai_caveats", "relations"):
            if field in idea:
                idea[field] = _as_text_list(idea[field])
        if "warrant" in idea:
            idea["warrant"] = _as_sentence(idea["warrant"])
        # Always filtered, even when the key is absent, so a stray genre_fields
        # value from another genre cannot survive into storage.
        idea["genre_fields"] = filter_genre_fields(idea.get("genre_fields"), genre)
        if "confidence" in idea:
            idea["confidence"] = _as_confidence(idea["confidence"])
        if "evidence_ids" in idea:
            idea["evidence_ids"] = _normalize_evidence_ids(idea["evidence_ids"])
        if "evidence" in idea:
            idea["evidence"] = _normalize_evidence(idea["evidence"])
    return payload


def normalize_book_overview_payload(content: str) -> object:
    payload = json.loads(content)
    if isinstance(payload, list):
        return next((item for item in payload if isinstance(item, dict)), payload)
    return payload


class OpenAICompatibleAnalysisProvider:
    analysis_protocol = "legacy"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.client = client

    def _chat_json(self, *, system: str, user: str) -> ChatJsonResponse:
        return self._request_chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )

    @property
    def source_thinking_options(self) -> tuple[str, ...]:
        if self.base_url == "https://api.deepseek.com" and self.model.startswith(("deepseek-flash", "deepseek-v4")):
            return ("off", "low", "high")
        if self.base_url == "https://api.openai.com/v1" and self.model.startswith(("gpt-5", "gpt-6", "o1", "o3", "o4")):
            return ("low", "high")
        return ()

    def chat_about_source(self, messages: list[dict[str, str]], thinking: str) -> ChatJsonResponse:
        options: dict[str, object] = {}
        if thinking != "default":
            if self.base_url == "https://api.deepseek.com":
                options["thinking"] = {"type": "disabled" if thinking == "off" else "enabled"}
            if thinking != "off":
                options["reasoning_effort"] = thinking
        return self._request_chat(messages, **options)

    def _request_chat(self, messages: list[dict[str, str]], **options: object) -> ChatJsonResponse:
        request = {
            "model": self.model,
            "messages": messages,
            **options,
        }
        try:
            if self.client is None:
                with httpx.Client(timeout=120) as client:
                    response = client.post(
                        f"{self.base_url}/chat/completions",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json=request,
                    )
            else:
                response = self.client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=request,
                )
            response.raise_for_status()
            payload = response.json()
            message = payload["choices"][0]["message"]
            content = message["content"]
            if not isinstance(content, str) or not content.strip():
                raise AnalysisProviderError("模型返回了空内容")
            usage = payload.get("usage", {})
            if not isinstance(usage, dict):
                usage = {}
            return ChatJsonResponse(
                content=content.strip(),
                prompt_tokens=_usage_integer(usage.get("prompt_tokens")),
                completion_tokens=_usage_integer(usage.get("completion_tokens")),
                total_tokens=_usage_integer(usage.get("total_tokens")),
                thinking=message.get("reasoning_content") if isinstance(message.get("reasoning_content"), str) else None,
            )
        except AnalysisProviderError:
            raise
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
            raise AnalysisProviderError(f"模型调用失败：{error}") from error

    def generate(
        self, chapter: ChapterSource, context: BookContext | None = None
    ) -> ChapterAnalysisDraft:
        return self.generate_with_metrics(chapter, context).draft

    def generate_with_metrics(
        self, chapter: ChapterSource, context: BookContext | None = None
    ) -> GeneratedChapterAnalysis:
        context = context or BookContext()
        genre = resolve_genre(context.genre)
        budget = analysis_budget_for_text(chapter.text)
        page_text = "\n\n".join(
            f"[第 {page.page_number} 页]\n{page.text}" for page in chapter.pages
        ) or f"[第 {chapter.source_start_page} 页开始]\n{chapter.text}"
        user = (
            f"{_book_context_block(chapter, context, genre)}"
            f"核心思想的数量取决于本章讲了几件相互独立的事，与篇幅长短无关。"
            f"请按本章真实独立观点的数量输出 {budget.min_core_ideas} 到 {budget.max_core_ideas} 个核心思想："
            f"不要为凑够数量把一个观点拆成多条，也不要把几个独立观点硬合并成一条；"
            f"本章只讲清楚一件事时就只输出 1 个。论证链不超过 {budget.max_argument_steps} 步。"
            f"\n\n{_evidence_catalogue_block(context)}\n\n【章节正文】\n{page_text}"
        )
        system = f"{CHAPTER_ANALYSIS_SYSTEM_PROMPT}\n\n{genre_instructions(genre)}"
        try:
            response = self._chat_json(system=system, user=user)
            draft = ChapterAnalysisDraft.model_validate(
                normalize_chapter_analysis_payload(response.content, genre=genre)
            )
            return GeneratedChapterAnalysis(
                draft=_limit_draft_to_budget(draft, budget),
                model=self.model,
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
                total_tokens=response.total_tokens,
                output_characters=len(response.content),
            )
        except ValueError as error:
            raise AnalysisProviderError(f"模型返回的章节分析结构无效：{error}") from error

    def detect_genre(self, context: BookContext, samples: list[str]) -> GenreDecision:
        """Classify the whole book once, so every chapter shares one framework."""
        outline = "\n".join(f"- {title}" for title in context.outline[:40]) or "（无目录信息）"
        sample = "\n\n".join(text[:500] for text in samples[:2]) or "（无正文样本）"
        user = (
            f"书名：{context.title or '未知'}\n"
            f"副标题：{context.subtitle or '无'}\n"
            f"作者：{context.authors or '未知'}\n"
            f"出版社：{context.publisher or '未知'}\n\n"
            f"目录标题：\n{outline}\n\n正文样本：\n{sample}"
        )
        try:
            response = self._chat_json(system=GENRE_DETECTION_SYSTEM_PROMPT, user=user)
            payload = json.loads(response.content)
        except (AnalysisProviderError, ValueError):
            # Detection is an optimisation, never a prerequisite: falling back to
            # the default genre still produces a usable analysis, whereas raising
            # here would block the whole book on a single auxiliary call.
            logger.exception("genre detection failed, falling back to %s", DEFAULT_GENRE)
            return GenreDecision(genre=DEFAULT_GENRE, confidence=None, reason="判定失败，使用默认体裁")
        if not isinstance(payload, dict):
            return GenreDecision(genre=DEFAULT_GENRE, confidence=None, reason="判定返回结构无效")
        return GenreDecision(
            genre=resolve_genre(payload.get("genre")),
            confidence=_as_optional_confidence(payload.get("confidence")),
            reason=str(payload.get("reason") or ""),
        )

    def generate_book_overview(self, chapters: list[OverviewChapterInput]) -> BookOverviewDraft:
        return self.generate_book_overview_with_metrics(chapters).overview

    def generate_book_overview_with_metrics(self, chapters: list[OverviewChapterInput]) -> GeneratedBookOverview:
        summaries = [
            {
                "chapter_question": chapter.chapter_question,
                "one_sentence_conclusion": chapter.one_sentence_conclusion,
                "role_in_book": chapter.role_in_book,
                "role_content_type": chapter.role_content_type,
            }
            for chapter in chapters
        ]
        system = """你是中文书籍结构编辑。根据提供的章节摘要生成 JSON，且只包含
core_question 和 one_sentence_summary。不要加入章节摘要之外的新事实。legacy_summary 是旧版未独立验证的归因，不得升级为已验证的作者原话。"""
        try:
            response = self._chat_json(system=system, user=json.dumps(summaries, ensure_ascii=False))
            return GeneratedBookOverview(
                overview=BookOverviewDraft.model_validate(normalize_book_overview_payload(response.content)),
                model=self.model,
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
                total_tokens=response.total_tokens,
                output_characters=len(response.content),
            )
        except ValueError as error:
            raise AnalysisProviderError(f"模型返回的全书总览结构无效：{error}") from error


def _limit_draft_to_budget(draft: ChapterAnalysisDraft, budget: AnalysisBudget) -> ChapterAnalysisDraft:
    ideas = []
    for idea in draft.core_ideas[:budget.max_core_ideas]:
        # An over-long quote used to be dropped outright, which silently turned a
        # sourced book_claim into an unsupported one and made the whole idea
        # disappear downstream. Truncating keeps a verifiable prefix instead:
        # a prefix of a verbatim quote is still verbatim, so verification holds.
        evidence = [
            item.model_copy(update={"quote": item.quote[:MAX_QUOTE_CHARACTERS]})
            for item in idea.evidence[:MAX_EVIDENCE_PER_IDEA]
        ]
        ideas.append(
            idea.model_copy(
                update={
                    "explanation": idea.explanation[:MAX_EXPLANATION_CHARACTERS],
                    "reasoning_steps": [
                        step[:MAX_LIST_ITEM_CHARACTERS]
                        for step in idea.reasoning_steps[:budget.max_argument_steps]
                    ],
                    "examples": _limit_items(idea.examples),
                    "caveats": _limit_items(idea.caveats),
                    "author_caveats": _limit_items(idea.author_caveats),
                    "ai_caveats": _limit_items(idea.ai_caveats),
                    "relations": _limit_items(idea.relations),
                    "warrant": idea.warrant[:MAX_LIST_ITEM_CHARACTERS],
                    "evidence_ids": idea.evidence_ids[:MAX_EVIDENCE_PER_IDEA],
                    "evidence": evidence,
                }
            )
        )
    return draft.model_copy(
        update={
            "argument_chain": [
                statement.model_copy(update={"text": statement.text[:MAX_LIST_ITEM_CHARACTERS]})
                for statement in draft.argument_chain[:budget.max_argument_steps]
            ],
            "core_ideas": ideas,
        }
    )


def _limit_items(values: list[str]) -> list[str]:
    return [value[:MAX_LIST_ITEM_CHARACTERS] for value in values[:MAX_LIST_ITEMS]]


def _book_context_block(chapter: ChapterSource, context: BookContext, genre: str) -> str:
    """Tell the model which book this is and where the chapter sits in it.

    Without this the prompt only carried a title and a page range, so the model
    could not tell a subordinate section from a standalone chapter, and treated
    every chapter as an isolated document.
    """
    lines = [
        f"【书籍】{context.title}：{context.subtitle}" if context.subtitle else f"【书籍】{context.title or '未知'}",
        f"【作者】{context.authors or '未知'}",
        f"【体裁】{GENRE_LABELS[resolve_genre(genre)]}",
        f"【本章】{chapter.title}",
        f"【页码】{chapter.source_start_page}-{chapter.source_end_page}",
    ]
    if chapter.parent_title:
        # A subordinate unit serves the argument of the unit above it; without
        # this the model promotes its supporting points into standalone ideas.
        lines.append(f"【隶属】本章隶属于《{chapter.parent_title}》，服务于它的论点")
    if chapter.nav_kind == "section":
        # Keyed on nav_kind rather than depth: in a book with parts, a chapter
        # already sits at depth 1, and calling it a subsection would wrongly cap
        # its core ideas at one or two.
        lines.append("【层级】这是章内的小节，核心思想通常只有 1 到 2 个")
    if context.outline:
        position = _outline_position(chapter.title, context.outline)
        if position:
            lines.append(f"【位置】{position}")
        lines.append("【全书目录】" + " / ".join(context.outline[:40]))
    return "\n".join(lines) + "\n\n"


def _evidence_catalogue_block(context: BookContext) -> str:
    current = _render_catalogue(context.evidence_blocks, related=False)
    related = _render_catalogue(context.related_evidence_blocks, related=True)
    lines = ["【当前章节证据目录】", current or "（无可选证据）"]
    if related:
        lines.extend(["【关联证据目录】", related])
    return "\n".join(lines)


def _render_catalogue(blocks: list[EvidenceBlock], *, related: bool) -> str:
    lines: list[str] = []
    active_paragraph = None
    for block in blocks:
        if block.paragraph_id != active_paragraph:
            label = f"【段落 {block.paragraph_id}｜第 {block.page} 页】"
            if related:
                label = f"【关联段落 {block.paragraph_id}｜{block.chapter_title}｜第 {block.page} 页】"
            lines.append(label)
            active_paragraph = block.paragraph_id
        lines.append(f"[{block.id}] {block.quote}")
    return "\n".join(lines)


def _outline_position(title: str, outline: list[str]) -> str:
    """Describe the chapter's place in the book, when the title is unambiguous."""
    matches = [index for index, entry in enumerate(outline) if entry == title]
    if len(matches) != 1:
        # Repeated titles (many books have a 结语 per chapter) cannot be located
        # by name alone, and a wrong position is worse than none.
        return ""
    return f"正文第 {matches[0] + 1} / {len(outline)} 个章节"


def _as_optional_confidence(value: object) -> float | None:
    parsed = _as_confidence(value)
    return float(parsed) if isinstance(parsed, (int, float)) else None


def _usage_integer(value: object) -> int | None:
    return value if isinstance(value, int) and value >= 0 else None
