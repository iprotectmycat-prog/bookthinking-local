from pathlib import Path

from app.services.providers import FixtureProvider


def test_fixture_provider_returns_evidence_backed_learning_unit() -> None:
    fixture = Path(__file__).parents[4] / "fixtures" / "sample-learning-unit.json"
    source = "The network timestamps transactions by hashing them into an ongoing chain of proof-of-work."
    draft = FixtureProvider(fixture).generate_learning_unit(source)

    assert draft.correct_answer == "A"
    assert draft.source_quote in source
    assert draft.options["A"] == draft.source_quote


def test_fixture_provider_skips_document_metadata() -> None:
    fixture = Path(__file__).parents[4] / "fixtures" / "sample-learning-unit.json"
    source = "\n".join(
        [
            "比特币：一种点对点电子货币系统",
            "Translated into Simplified Chinese from bitcoin.org/bitcoin.pdf",
            "摘要. 一种完全的点对点电子货币应当允许在线支付从一方直接发送到另一方而不需要通过一个金融机构。",
        ]
    )

    draft = FixtureProvider(fixture).generate_learning_unit(source)

    assert draft.source_quote.startswith("摘要.")
