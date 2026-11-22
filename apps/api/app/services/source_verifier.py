from dataclasses import dataclass
import re


@dataclass(frozen=True)
class SourceVerification:
    is_valid: bool


def _normalize(text: str) -> str:
    """Collapse every whitespace run, including newlines.

    Extracted text is heavily line-broken (the EPUB parser joins each XHTML
    element with "\\n"), so a quote that is verbatim in the book routinely
    differs from the source only by line breaks. Whitespace must therefore be
    ignored *within* a page.
    """
    return re.sub(r"\s+", "", text)


class SourceVerifier:
    def verify(self, *, source_text: str, proposed_quote: str) -> SourceVerification:
        """Verify a quote against a single contiguous block of source text.

        Callers holding per-page text should prefer :meth:`verify_on_page`,
        which prevents a quote from being stitched together across pages that
        are not physically adjacent.
        """
        normalized_source = _normalize(source_text)
        normalized_quote = _normalize(proposed_quote)
        return SourceVerification(is_valid=bool(normalized_quote) and normalized_quote in normalized_source)

    def verify_on_page(
        self,
        *,
        pages: dict[int, str],
        page_number: int,
        proposed_quote: str,
    ) -> SourceVerification:
        """Verify a quote against the page the model claims it came from.

        Whitespace is ignored inside a page, but page boundaries are enforced:
        a quote is only accepted if it appears on the cited page, or if it
        genuinely runs over onto the immediately following page (a real effect
        of physical pagination in PDFs). Concatenating fragments from
        non-adjacent pages is rejected, which the previous whole-chapter
        substring check allowed.
        """
        normalized_quote = _normalize(proposed_quote)
        if not normalized_quote:
            return SourceVerification(is_valid=False)

        cited_page = pages.get(page_number)
        if cited_page is None:
            return SourceVerification(is_valid=False)

        normalized_page = _normalize(cited_page)
        if normalized_quote in normalized_page:
            return SourceVerification(is_valid=True)

        following_page = pages.get(page_number + 1)
        if following_page is None:
            return SourceVerification(is_valid=False)

        spanning_text = normalized_page + _normalize(following_page)
        if normalized_quote not in spanning_text:
            return SourceVerification(is_valid=False)

        # Only accept a spanning quote that actually straddles the boundary:
        # it must start on the cited page and continue past its end.
        start = spanning_text.find(normalized_quote)
        return SourceVerification(is_valid=start < len(normalized_page) < start + len(normalized_quote))
