from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.api.dependencies import get_account_repository, require_owner
from app.schemas import AdminBookResponse, PublishBookRequest
from app.services.accounts import AccountRepository, InviteRecord, UserRecord
from app.services.authentication import hash_password, new_token
from app.services.public_library import PublicLibraryError, PublicLibraryService
from app.services.storage import ApplicationPaths, BookRepository

router = APIRouter(prefix="/admin", tags=["admin"])


class CreateInviteRequest(BaseModel):
    label: str | None = Field(default=None, max_length=120)


class InviteResponse(BaseModel):
    id: int
    code: str
    status: str = "active"
    label: str | None


class InviteListResponse(BaseModel):
    id: int
    status: str
    label: str | None
    created_by_user_id: int | None
    used_by_user_id: int | None
    created_at: str
    used_at: str | None
    revoked_at: str | None


class UpdateBookLimitRequest(BaseModel):
    book_import_limit: int = Field(ge=0, le=10_000)


class ResetPasswordResponse(BaseModel):
    temporary_password: str


def get_public_library_service() -> PublicLibraryService:
    paths = ApplicationPaths.from_environment()
    paths.ensure_exists()
    return PublicLibraryService(BookRepository(paths.database_path), paths)


def _admin_book_response(book: dict[str, object], service: PublicLibraryService, owner_id: int) -> AdminBookResponse:
    return AdminBookResponse(
        id=str(book["id"]),
        title=str(book["title"]) if book["title"] is not None else None,
        filename=str(book["filename"]),
        source_format=str(book["source_format"]),
        visibility=str(book["visibility"]),
        overview_status=str(book["overview_status"]),
        ready_chapter_count=int(book["ready_chapter_count"]),
        public_at=str(book["public_at"]) if book["public_at"] is not None else None,
        publication_blockers=list(service.publication_blockers(str(book["id"]), owner_id)),
    )


@router.get("/books", response_model=list[AdminBookResponse])
def list_books_for_publication(
    owner: Annotated[UserRecord, Depends(require_owner)],
    service: Annotated[PublicLibraryService, Depends(get_public_library_service)],
) -> list[AdminBookResponse]:
    return [
        _admin_book_response(book, service, owner.id)
        for book in service.repository.list_publishable_books_for_owner(owner.id)
    ]


@router.post("/books/{book_id}/publish", response_model=AdminBookResponse)
def publish_book(
    book_id: str,
    _: PublishBookRequest,
    owner: Annotated[UserRecord, Depends(require_owner)],
    accounts: Annotated[AccountRepository, Depends(get_account_repository)],
    service: Annotated[PublicLibraryService, Depends(get_public_library_service)],
) -> AdminBookResponse:
    try:
        service.publish(book_id, owner.id)
    except PublicLibraryError as error:
        _raise_public_library_error(error)
    book = _require_publishable_book(service, book_id, owner.id)
    accounts.record_audit_event(
        action="book.published",
        result="succeeded",
        actor_user_id=owner.id,
        target_type="book",
        target_id=book_id,
    )
    return _admin_book_response(book, service, owner.id)


@router.post("/books/{book_id}/unpublish", response_model=AdminBookResponse)
def unpublish_book(
    book_id: str,
    owner: Annotated[UserRecord, Depends(require_owner)],
    accounts: Annotated[AccountRepository, Depends(get_account_repository)],
    service: Annotated[PublicLibraryService, Depends(get_public_library_service)],
) -> AdminBookResponse:
    try:
        service.unpublish(book_id, owner.id)
    except PublicLibraryError as error:
        _raise_public_library_error(error)
    book = _require_publishable_book(service, book_id, owner.id)
    accounts.record_audit_event(
        action="book.unpublished",
        result="succeeded",
        actor_user_id=owner.id,
        target_type="book",
        target_id=book_id,
    )
    return _admin_book_response(book, service, owner.id)


def _require_publishable_book(
    service: PublicLibraryService, book_id: str, owner_id: int
) -> dict[str, object]:
    book = next(
        (item for item in service.repository.list_publishable_books_for_owner(owner_id) if item["id"] == book_id),
        None,
    )
    if book is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="书籍不存在")
    return book


def _raise_public_library_error(error: PublicLibraryError) -> None:
    if str(error) == "书籍不存在":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.post("/invites", response_model=InviteResponse, status_code=status.HTTP_201_CREATED)
def create_invite(request: CreateInviteRequest, owner: Annotated[UserRecord, Depends(require_owner)], repository: Annotated[AccountRepository, Depends(get_account_repository)]) -> InviteResponse:
    invite_id, code = repository.create_generated_invite(owner.id, label=request.label)
    repository.record_audit_event(action="invite.created", result="succeeded", actor_user_id=owner.id, target_type="invite", target_id=str(invite_id))
    return InviteResponse(id=invite_id, code=code, label=request.label)


@router.get("/invites", response_model=list[InviteListResponse])
def list_invites(_: Annotated[UserRecord, Depends(require_owner)], repository: Annotated[AccountRepository, Depends(get_account_repository)]) -> list[InviteListResponse]:
    return [_invite_response(invite) for invite in repository.list_invites()]


@router.post("/invites/{invite_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
def revoke_invite(invite_id: int, owner: Annotated[UserRecord, Depends(require_owner)], repository: Annotated[AccountRepository, Depends(get_account_repository)]) -> Response:
    if not repository.revoke_invite(invite_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="邀请码不存在或已失效")
    repository.record_audit_event(action="invite.revoked", result="succeeded", actor_user_id=owner.id, target_type="invite", target_id=str(invite_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/users")
def list_users(_: Annotated[UserRecord, Depends(require_owner)], repository: Annotated[AccountRepository, Depends(get_account_repository)]) -> list[dict[str, object]]:
    return [_user_response(user) for user in repository.list_users()]


@router.post("/users/{user_id}/freeze", status_code=status.HTTP_204_NO_CONTENT)
def freeze_user(user_id: int, owner: Annotated[UserRecord, Depends(require_owner)], repository: Annotated[AccountRepository, Depends(get_account_repository)]) -> Response:
    try:
        repository.set_user_status(user_id=user_id, status="frozen")
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    repository.record_audit_event(action="user.frozen", result="succeeded", actor_user_id=owner.id, target_type="user", target_id=str(user_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/users/{user_id}/unfreeze", status_code=status.HTTP_204_NO_CONTENT)
def unfreeze_user(user_id: int, owner: Annotated[UserRecord, Depends(require_owner)], repository: Annotated[AccountRepository, Depends(get_account_repository)]) -> Response:
    try:
        repository.set_user_status(user_id=user_id, status="active")
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    repository.record_audit_event(action="user.unfrozen", result="succeeded", actor_user_id=owner.id, target_type="user", target_id=str(user_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/users/{user_id}/book-import-limit")
def update_book_import_limit(user_id: int, request: UpdateBookLimitRequest, owner: Annotated[UserRecord, Depends(require_owner)], repository: Annotated[AccountRepository, Depends(get_account_repository)]) -> dict[str, object]:
    try:
        user = repository.set_book_import_limit(user_id=user_id, limit=request.book_import_limit)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    repository.record_audit_event(action="user.book_import_limit.updated", result="succeeded", actor_user_id=owner.id, target_type="user", target_id=str(user_id))
    return _user_response(user)


@router.post("/users/{user_id}/reset-password", response_model=ResetPasswordResponse)
def reset_user_password(user_id: int, owner: Annotated[UserRecord, Depends(require_owner)], repository: Annotated[AccountRepository, Depends(get_account_repository)]) -> ResetPasswordResponse:
    user = repository.get_user_by_id(user_id)
    if user is None or user.role != "user":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="体验用户不存在")
    temporary_password = new_token()
    repository.set_password(user_id=user.id, password_hash=hash_password(temporary_password), must_change_password=True)
    repository.revoke_all_sessions(user.id)
    repository.record_audit_event(action="user.password.reset", result="succeeded", actor_user_id=owner.id, target_type="user", target_id=str(user_id))
    return ResetPasswordResponse(temporary_password=temporary_password)


def _user_response(user: UserRecord) -> dict[str, object]:
    return {"id": user.id, "email": user.email, "role": user.role, "status": user.status, "book_import_count": user.book_import_count, "book_import_limit": user.book_import_limit, "must_change_password": user.must_change_password}


def _invite_response(invite: InviteRecord) -> InviteListResponse:
    return InviteListResponse(
        id=invite.id, status=invite.status, label=invite.label, created_by_user_id=invite.created_by_user_id,
        used_by_user_id=invite.used_by_user_id, created_at=invite.created_at.isoformat(),
        used_at=invite.used_at.isoformat() if invite.used_at else None,
        revoked_at=invite.revoked_at.isoformat() if invite.revoked_at else None,
    )
