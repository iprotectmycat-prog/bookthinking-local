from json import dumps, loads
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.book_access import require_private_owned_book
from app.api.dependencies import resolve_product_user
from app.services.accounts import UserRecord
from app.services.chapter_confirmation import ChapterConfirmationError, ChapterConfirmationService
from app.services.learning_unit import LearningUnitValidator
from app.services.providers import FixtureProvider
from app.services.source_verifier import SourceVerifier
from app.services.storage import ApplicationPaths, BookRepository

router = APIRouter(tags=["study"])


class PredictionRequest(BaseModel):
    answer: str


@router.post("/books/{book_id}/learning-units", status_code=status.HTTP_201_CREATED)
def generate_learning_unit(
    book_id: str,
    user: Annotated[UserRecord, Depends(resolve_product_user)],
) -> dict[str, object]:
    paths = ApplicationPaths.from_environment()
    repository = BookRepository(paths.database_path)
    require_private_owned_book(repository, user.id, book_id)
    try:
        ChapterConfirmationService(repository).require_confirmed(book_id)
    except ChapterConfirmationError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    chapter = repository.confirmed_chapter_source(book_id)
    if chapter is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="没有可用章节正文")
    fixture = Path(__file__).parents[5] / "fixtures" / "sample-learning-unit.json"
    draft = FixtureProvider(fixture).generate_learning_unit(str(chapter["text"]))
    if LearningUnitValidator().validate(draft).errors or not SourceVerifier().verify(
        source_text=str(chapter["text"]), proposed_quote=draft.source_quote
    ).is_valid:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="学习单元缺少有效原文证据")
    unit_id = str(uuid4())
    repository.save_learning_unit(
        unit_id=unit_id, book_id=book_id, question=draft.question, options_json=dumps(draft.options),
        correct_answer=draft.correct_answer, explanation=draft.explanation, source_quote=draft.source_quote,
        source_page=int(chapter["source_start_page"]),
    )
    return {
        "id": unit_id,
        "question": draft.question,
        "options": draft.options,
        "prediction": {"correct_answer": None},
        "evidence": [{"chapter": chapter["title"], "page": chapter["source_start_page"], "quote": draft.source_quote}],
    }


@router.post("/learning-units/{unit_id}/predictions")
def submit_prediction(
    unit_id: str,
    request: PredictionRequest,
    user: Annotated[UserRecord, Depends(resolve_product_user)],
) -> dict[str, object]:
    paths = ApplicationPaths.from_environment()
    repository = BookRepository(paths.database_path)
    unit = repository.get_owned_learning_unit(user.id, unit_id)
    if unit is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="学习单元不存在")
    options = loads(str(unit["options_json"]))
    if request.answer not in options:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="答案不在可选范围内")
    repository.save_prediction(unit_id, request.answer)
    chapter = repository.confirmed_chapter_source(str(unit["book_id"]))
    return {
        "prediction": {
            "selected_answer": request.answer,
            "correct_answer": unit["correct_answer"],
            "is_correct": request.answer == unit["correct_answer"],
        },
        "explanation": unit["explanation"],
        "evidence": [{"chapter": chapter["title"], "page": unit["source_page"], "quote": unit["source_quote"]}],
    }
