from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
import json
import logging
import re
from typing import Literal
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

_DOUBAN_HOST = "book.douban.com"
_SUBJECT_URL = "https://book.douban.com/subject/{subject_id}/"


@dataclass(frozen=True)
class BookIdentity:
    title: str
    authors: tuple[str, ...]
    publisher: str | None
    published_year: str | None
    isbn: str | None


@dataclass(frozen=True)
class DoubanMatchResult:
    status: Literal["matched", "not_found", "ambiguous", "provider_error"]
    external_id: str | None = None
    url: str | None = None
    match_basis: str | None = None

    @classmethod
    def matched(cls, external_id: str, match_basis: str) -> DoubanMatchResult:
        return cls("matched", external_id, _SUBJECT_URL.format(subject_id=external_id), match_basis)


def normalize_text(value: str | None) -> str:
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", (value or "").casefold())


def normalize_isbn(value: str | None) -> str | None:
    raw = (value or "").strip()
    raw = re.sub(r"^(?:urn:)?isbn(?:-1[03])?:?", "", raw, flags=re.IGNORECASE)
    compact = re.sub(r"[\s-]", "", raw).upper()
    if re.fullmatch(r"97[89][0-9]{10}", compact):
        total = sum((1 if index % 2 == 0 else 3) * int(char) for index, char in enumerate(compact[:12]))
        return compact if (10 - total % 10) % 10 == int(compact[-1]) else None
    if re.fullmatch(r"[0-9]{9}[0-9X]", compact):
        digits = [int(char) for char in compact[:9]] + [10 if compact[-1] == "X" else int(compact[-1])]
        return compact if sum((10 - index) * digit for index, digit in enumerate(digits)) % 11 == 0 else None
    return None


class _SubjectParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_h1 = False
        self._info_depth = 0
        self.title: list[str] = []
        self.info: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "h1":
            self._in_h1 = True
        if tag == "div" and dict(attrs).get("id") == "info":
            self._info_depth = 1
        elif self._info_depth:
            self._info_depth += 1
        if self._info_depth and tag == "br":
            self.info.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "h1":
            self._in_h1 = False
        if self._info_depth:
            self._info_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._in_h1:
            self.title.append(data)
        if self._info_depth:
            self.info.append(data)


@dataclass(frozen=True)
class _SubjectFacts:
    title: str
    author: str
    publisher: str
    published_year: str | None
    isbn: str | None


def _subject_facts(html: str) -> _SubjectFacts:
    parser = _SubjectParser()
    parser.feed(html)
    info = " ".join("".join(parser.info).split())

    def field(label: str, next_labels: tuple[str, ...]) -> str:
        labels = "|".join(map(re.escape, next_labels))
        match = re.search(rf"{re.escape(label)}\s*[:：]\s*(.*?)(?=(?:{labels})\s*[:：]|$)", info)
        return match.group(1).strip() if match else ""

    published = field("出版年", ("ISBN", "页数", "装帧", "定价", "丛书"))
    year = re.search(r"(?:19|20)\d{2}", published)
    return _SubjectFacts(
        title=" ".join("".join(parser.title).split()),
        author=field("作者", ("出版社", "出品方", "副标题", "原作名", "译者", "出版年", "ISBN")),
        publisher=field("出版社", ("出品方", "副标题", "原作名", "译者", "出版年", "ISBN")),
        published_year=year.group(0) if year else None,
        isbn=normalize_isbn(field("ISBN", ("页数", "装帧", "定价", "丛书"))),
    )


class DoubanLinkMatcher:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(5.0),
            follow_redirects=True,
            headers={
                "User-Agent": "BookThinking/0.1 (+local personal reading tool)",
                "Accept": "application/json,text/html;q=0.9",
            },
        )

    def resolve(self, identity: BookIdentity) -> DoubanMatchResult:
        try:
            candidates = self._candidates(identity)
            if not candidates:
                return DoubanMatchResult("not_found")
            matches = [match for subject_id in candidates if (match := self._verify(subject_id, identity))]
        except (httpx.HTTPError, json.JSONDecodeError, TypeError, ValueError, KeyError) as error:
            logger.info("douban book link unavailable: %s", type(error).__name__)
            return DoubanMatchResult("provider_error")
        if not matches:
            return DoubanMatchResult("not_found")
        strongest = max(score for score, _subject_id, _basis in matches)
        strongest_matches = [(subject_id, basis) for score, subject_id, basis in matches if score == strongest]
        if len(strongest_matches) != 1:
            return DoubanMatchResult("ambiguous")
        subject_id, basis = strongest_matches[0]
        return DoubanMatchResult.matched(subject_id, basis)

    def _candidates(self, identity: BookIdentity) -> list[str]:
        response = self.client.get("https://book.douban.com/j/subject_suggest", params={"q": identity.title})
        response.raise_for_status()
        if response.url.host != _DOUBAN_HOST:
            raise ValueError("unexpected Douban suggestion redirect")
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError("unexpected Douban suggestion payload")
        title = normalize_text(identity.title)
        authors = {normalize_text(author) for author in identity.authors if normalize_text(author)}
        selected: list[str] = []
        for candidate in payload:
            if not isinstance(candidate, dict) or candidate.get("type") != "b":
                continue
            subject_id = str(candidate.get("id") or "")
            url = str(candidate.get("url") or "")
            parsed = urlparse(url)
            if not subject_id.isdigit() or parsed.scheme != "https" or parsed.netloc != _DOUBAN_HOST:
                continue
            if parsed.path != f"/subject/{subject_id}/" or normalize_text(str(candidate.get("title") or "")) != title:
                continue
            candidate_author = normalize_text(str(candidate.get("author_name") or ""))
            if not identity.publisher and authors and not any(author in candidate_author or candidate_author in author for author in authors):
                continue
            selected.append(subject_id)
            if len(selected) == 5:
                break
        return selected

    def _verify(self, subject_id: str, identity: BookIdentity) -> tuple[int, str, str] | None:
        response = self.client.get(_SUBJECT_URL.format(subject_id=subject_id))
        response.raise_for_status()
        if response.url.host != _DOUBAN_HOST:
            raise ValueError("unexpected Douban subject redirect")
        facts = _subject_facts(response.text)
        if normalize_text(facts.title) != normalize_text(identity.title):
            return None
        local_isbn = normalize_isbn(identity.isbn)
        if local_isbn:
            return (4, subject_id, "isbn") if facts.isbn == local_isbn else None
        publisher_matches = bool(identity.publisher and normalize_text(identity.publisher) == normalize_text(facts.publisher))
        year_matches = bool(identity.published_year and identity.published_year == facts.published_year)
        authors = {normalize_text(author) for author in identity.authors if normalize_text(author)}
        author = normalize_text(facts.author)
        author_matches = bool(authors and any(expected in author or author in expected for expected in authors))
        if publisher_matches and year_matches:
            return 3, subject_id, "title_author_publisher_year" if author_matches else "title_publisher_year"
        if publisher_matches:
            return 2, subject_id, "title_author_publisher" if author_matches else "title_publisher"
        if not author_matches:
            return None
        return (1, subject_id, "title_author_year") if year_matches else None
