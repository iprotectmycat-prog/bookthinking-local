from app.services.source_verifier import SourceVerifier


def test_rejects_claim_when_quoted_evidence_is_not_in_source() -> None:
    result = SourceVerifier().verify(
        source_text="作者说资本成本会影响估值。",
        proposed_quote="作者说增长永远保证收益。",
    )

    assert result.is_valid is False


def test_accepts_quote_after_whitespace_normalization() -> None:
    result = SourceVerifier().verify(
        source_text="资本成本会\n影响企业的估值。",
        proposed_quote="资本成本会影响企业的估值。",
    )

    assert result.is_valid is True


def test_accepts_quote_found_on_the_cited_page() -> None:
    result = SourceVerifier().verify_on_page(
        pages={1: "首页内容。", 2: "资本成本会\n影响企业的估值。"},
        page_number=2,
        proposed_quote="资本成本会影响企业的估值。",
    )

    assert result.is_valid is True


def test_rejects_quote_stitched_across_non_adjacent_pages() -> None:
    """Regression: verifying against the whole chapter let the model concatenate
    fragments from unrelated pages, because pages are joined with "\\n\\n" and
    all whitespace was collapsed before the substring check."""
    result = SourceVerifier().verify_on_page(
        pages={1: "第一页结尾的句子。", 2: "无关内容。", 3: "第三页开头的句子。"},
        page_number=1,
        proposed_quote="句子。第三页",
    )

    assert result.is_valid is False


def test_rejects_quote_that_belongs_to_a_different_page() -> None:
    result = SourceVerifier().verify_on_page(
        pages={1: "资本成本会影响估值。", 2: "增长并不保证收益。"},
        page_number=1,
        proposed_quote="增长并不保证收益。",
    )

    assert result.is_valid is False


def test_accepts_quote_that_genuinely_runs_onto_the_next_page() -> None:
    """Physical pagination really does split sentences, so a quote starting on
    the cited page and continuing onto the very next one stays valid."""
    result = SourceVerifier().verify_on_page(
        pages={4: "作者认为资本成本", 5: "决定了企业的估值。"},
        page_number=4,
        proposed_quote="作者认为资本成本决定了企业的估值。",
    )

    assert result.is_valid is True


def test_rejects_quote_whose_cited_page_is_missing() -> None:
    result = SourceVerifier().verify_on_page(
        pages={1: "资本成本会影响估值。"},
        page_number=9,
        proposed_quote="资本成本会影响估值。",
    )

    assert result.is_valid is False


def test_rejects_empty_quote_on_page() -> None:
    result = SourceVerifier().verify_on_page(
        pages={1: "资本成本会影响估值。"}, page_number=1, proposed_quote="   "
    )

    assert result.is_valid is False
