from app.services.learning_unit import LearningUnitDraft, LearningUnitValidator, PredictionDraft


def test_prediction_cannot_be_published_without_valid_source_span() -> None:
    unit = LearningUnitDraft(prediction=PredictionDraft(source_span_id=None))

    assert LearningUnitValidator().validate(unit).errors == ["prediction.source_span_id is required"]
