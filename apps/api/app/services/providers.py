import json
from pathlib import Path

from app.services.learning_unit import LearningUnitDraft, PredictionDraft


class FixtureProvider:
    def __init__(self, fixture_path: Path) -> None:
        self.fixture_path = fixture_path

    def generate_learning_unit(self, chapter_text: str) -> LearningUnitDraft:
        json.loads(self.fixture_path.read_text())
        metadata_markers = ("http://", "https://", "www.", "@", "translated into", "satoshi")
        lines = [
            line.strip()
            for line in chapter_text.splitlines()
            if len(line.strip()) >= 20
            and not any(marker in line.lower() for marker in metadata_markers)
        ]
        source_quote = lines[0] if lines else chapter_text.strip()[:160]
        return LearningUnitDraft(
            prediction=PredictionDraft(source_span_id="fixture-source-span"),
            question="以下哪项是本章原文直接支持的表述？",
            options={
                "A": source_quote,
                "B": "原文认为该结论不需要任何证据支持。",
                "C": "原文保证所有相关结果都会自动发生。",
                "D": "原文主张应当忽略本章讨论的问题。",
            },
            correct_answer="A",
            explanation="选项 A 可以在本章原文中直接定位，其余选项没有对应的原文证据。",
            source_quote=source_quote,
        )
