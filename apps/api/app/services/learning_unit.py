from dataclasses import dataclass, field


@dataclass(frozen=True)
class PredictionDraft:
    source_span_id: str | None


@dataclass(frozen=True)
class LearningUnitDraft:
    prediction: PredictionDraft
    question: str = ""
    options: dict[str, str] = field(default_factory=dict)
    correct_answer: str = ""
    explanation: str = ""
    source_quote: str = ""


@dataclass(frozen=True)
class ValidationResult:
    errors: list[str]


class LearningUnitValidator:
    def validate(self, unit: LearningUnitDraft) -> ValidationResult:
        if unit.prediction.source_span_id is None:
            return ValidationResult(errors=["prediction.source_span_id is required"])
        return ValidationResult(errors=[])
