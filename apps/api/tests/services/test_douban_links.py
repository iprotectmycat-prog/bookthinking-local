import json

import httpx

from app.services.douban_links import BookIdentity, DoubanLinkMatcher, DoubanMatchResult, normalize_isbn


def subject_html(*, title: str, author: str, publisher: str, published_at: str, isbn: str) -> str:
    return f"""
    <html><body><h1>{title}</h1><div id="info">
      作者: <a>{author}</a><br/>出版社: {publisher}<br/>
      出版年: {published_at}<br/>ISBN: {isbn}
    </div></body></html>
    """


def fixture_matcher(
    suggestions: list[dict[str, str]], subjects: dict[str, str]
) -> tuple[DoubanLinkMatcher, list[str]]:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.path == "/j/subject_suggest":
            return httpx.Response(200, json=suggestions, request=request)
        subject_id = request.url.path.rstrip("/").split("/")[-1]
        return httpx.Response(200, text=subjects[subject_id], request=request)

    return DoubanLinkMatcher(client=httpx.Client(transport=httpx.MockTransport(handler))), requests


def suggestion(subject_id: str, title: str = "置身事内", author: str = "兰小欢") -> dict[str, str]:
    return {
        "id": subject_id,
        "title": title,
        "author_name": author,
        "type": "b",
        "url": f"https://book.douban.com/subject/{subject_id}/",
    }


def test_isbn_selects_the_matching_edition() -> None:
    matcher, requests = fixture_matcher(
        [suggestion("35546622"), suggestion("36601306")],
        {
            "35546622": subject_html(
                title="置身事内", author="兰小欢", publisher="上海人民出版社", published_at="2021-8", isbn="9787208171336"
            ),
            "36601306": subject_html(
                title="置身事内", author="兰小欢", publisher="上海人民出版社", published_at="2023-10", isbn="9787208184060"
            ),
        },
    )

    result = matcher.resolve(BookIdentity("置身事内", ("兰小欢",), "上海人民出版社", "2021", "978-7-208-17133-6"))

    assert result == DoubanMatchResult.matched("35546622", "isbn")
    assert len(requests) == 3


def test_without_isbn_requires_a_unique_edition_signal() -> None:
    matcher, _ = fixture_matcher(
        [suggestion("35546622"), suggestion("36601306")],
        {
            "35546622": subject_html(
                title="置身事内", author="兰小欢", publisher="上海人民出版社", published_at="2021-8", isbn="9787208171336"
            ),
            "36601306": subject_html(
                title="置身事内", author="兰小欢", publisher="上海人民出版社", published_at="2023-10", isbn="9787208184060"
            ),
        },
    )

    result = matcher.resolve(BookIdentity("置身事内", ("兰小欢",), "上海人民出版社", None, None))

    assert result.status == "ambiguous"


def test_title_author_and_year_select_the_matching_edition_without_isbn() -> None:
    matcher, _ = fixture_matcher(
        [suggestion("35546622"), suggestion("36601306")],
        {
            "35546622": subject_html(
                title="置身事内", author="兰小欢", publisher="上海人民出版社", published_at="2021-8", isbn="9787208171336"
            ),
            "36601306": subject_html(
                title="置身事内", author="兰小欢", publisher="上海人民出版社", published_at="2023-10", isbn="9787208184060"
            ),
        },
    )

    result = matcher.resolve(BookIdentity("置身事内", ("兰小欢",), "上海人民出版社", "2021", None))

    assert result == DoubanMatchResult.matched("35546622", "title_author_publisher_year")


def test_title_and_publisher_select_an_edition_when_the_stored_author_is_not_normalized() -> None:
    matcher, _ = fixture_matcher(
        [suggestion("35381242", "海龟交易法则", "柯蒂斯·费思")],
        {
            "35381242": subject_html(
                title="海龟交易法则", author="柯蒂斯·费思", publisher="中信出版股份有限公司", published_at="2010-11", isbn="9787508624159"
            ),
        },
    )

    result = matcher.resolve(BookIdentity("海龟交易法则", ("（美）费思",), "中信出版股份有限公司", "2010", None))

    assert result == DoubanMatchResult.matched("35381242", "title_publisher_year")


def test_provider_errors_are_not_matches() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    matcher = DoubanLinkMatcher(client=httpx.Client(transport=httpx.MockTransport(handler)))

    result = matcher.resolve(BookIdentity("置身事内", ("兰小欢",), None, None, None))

    assert result.status == "provider_error"


def test_rejects_uuid_and_accepts_valid_isbn() -> None:
    assert normalize_isbn("b7844886-8e62-475c-82d7-f1ee31e09896") is None
    assert normalize_isbn("978-7-208-17133-6") == "9787208171336"
