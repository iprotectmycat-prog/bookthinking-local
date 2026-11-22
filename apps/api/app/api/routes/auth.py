import os
from datetime import UTC, datetime, timedelta
from hmac import compare_digest
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.api.dependencies import SESSION_COOKIE_NAME, get_account_repository, require_current_user
from app.services.accounts import AccountRepository, InviteCodeError, UserRecord
from app.services.authentication import hash_password, new_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])
STANDARD_SESSION_MAX_AGE = 60 * 60 * 24 * 30
TRUSTED_LOCAL_COOKIE_MAX_AGE = 60 * 60 * 24 * 365 * 10


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1)
    invite_code: str = Field(min_length=1, max_length=256)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1)


class AccountResponse(BaseModel):
    id: int
    email: str
    role: str
    status: str
    book_import_count: int
    book_import_limit: int | None
    session_type: str | None = None
    must_change_password: bool


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=1, max_length=1024)


class SessionResponse(BaseModel):
    id: int
    session_type: str
    device_label: str | None
    created_at: str
    last_seen_at: str
    expires_at: str | None
    is_current: bool


@router.post("/register", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
def register(request: RegisterRequest, http_request: Request, response: Response, repository: Annotated[AccountRepository, Depends(get_account_repository)]) -> AccountResponse:
    try:
        user = repository.create_user_from_invite(email=request.email, password_hash=hash_password(request.password), invite_code=request.invite_code.strip())
    except InviteCodeError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return _set_session(response, repository, user, http_request)


@router.post("/login", response_model=AccountResponse)
def login(request: LoginRequest, http_request: Request, response: Response, repository: Annotated[AccountRepository, Depends(get_account_repository)]) -> AccountResponse:
    user = repository.get_user_by_email(request.email)
    if user is None or user.status != "active" or not verify_password(request.password, user.password_hash):
        repository.record_audit_event(action="auth.login.failed", result="failed", actor_user_id=None, target_type="user", target_id=None)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="邮箱或密码错误")
    repository.record_audit_event(action="auth.login.succeeded", result="succeeded", actor_user_id=user.id, target_type="user", target_id=str(user.id))
    return _set_session(response, repository, user, http_request)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(http_request: Request, response: Response, session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None, repository: Annotated[AccountRepository, Depends(get_account_repository)] = None) -> None:
    if session_token and repository.revoke_session(session_token):
        repository.record_audit_event(action="auth.logout.succeeded", result="succeeded", actor_user_id=None, target_type="session", target_id=None)
    response.delete_cookie(SESSION_COOKIE_NAME, httponly=True, samesite="lax", secure=_secure_cookies(http_request), path="/")


@router.get("/session", response_model=AccountResponse)
def current_session(response: Response, request: Request, user: Annotated[UserRecord, Depends(require_current_user)], session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None, repository: Annotated[AccountRepository, Depends(get_account_repository)] = None) -> AccountResponse:
    session = repository.get_session_for_token(session_token) if session_token else None
    session_type = session.session_type if session and session.user_id == user.id else None
    if session_type == "trusted_local":
        _set_cookie(response, session_token or "", TRUSTED_LOCAL_COOKIE_MAX_AGE, request)
    return _account_response(user, session_type)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(request: ChangePasswordRequest, http_request: Request, response: Response, user: Annotated[UserRecord, Depends(require_current_user)], repository: Annotated[AccountRepository, Depends(get_account_repository)]) -> Response:
    if not verify_password(request.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="当前密码错误")
    repository.set_password(user_id=user.id, password_hash=hash_password(request.new_password))
    repository.revoke_all_sessions(user.id)
    repository.record_audit_event(action="auth.password.changed", result="succeeded", actor_user_id=user.id, target_type="user", target_id=str(user.id))
    response.delete_cookie(SESSION_COOKIE_NAME, httponly=True, samesite="lax", secure=_secure_cookies(http_request), path="/")
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers=dict(response.headers))


@router.get("/sessions", response_model=list[SessionResponse])
def list_sessions(user: Annotated[UserRecord, Depends(require_current_user)], session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None, repository: Annotated[AccountRepository, Depends(get_account_repository)] = None) -> list[SessionResponse]:
    current = repository.get_session_for_token(session_token) if session_token else None
    return [
        SessionResponse(
            id=session.id, session_type=session.session_type, device_label=session.device_label,
            created_at=session.created_at.isoformat(), last_seen_at=session.last_seen_at.isoformat(),
            expires_at=session.expires_at.isoformat() if session.expires_at else None,
            is_current=current is not None and current.id == session.id,
        )
        for session in repository.list_sessions(user.id)
    ]


@router.delete("/sessions", status_code=status.HTTP_204_NO_CONTENT)
def revoke_all_sessions(http_request: Request, response: Response, user: Annotated[UserRecord, Depends(require_current_user)], repository: Annotated[AccountRepository, Depends(get_account_repository)]) -> Response:
    repository.revoke_all_sessions(user.id)
    repository.record_audit_event(action="auth.sessions.revoked_all", result="succeeded", actor_user_id=user.id, target_type="user", target_id=str(user.id))
    response.delete_cookie(SESSION_COOKIE_NAME, httponly=True, samesite="lax", secure=_secure_cookies(http_request), path="/")
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers=dict(response.headers))


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_session(session_id: int, http_request: Request, response: Response, user: Annotated[UserRecord, Depends(require_current_user)], session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None, repository: Annotated[AccountRepository, Depends(get_account_repository)] = None) -> Response:
    current = repository.get_session_for_token(session_token) if session_token else None
    if not repository.revoke_session_by_id(user_id=user.id, session_id=session_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    repository.record_audit_event(action="auth.session.revoked", result="succeeded", actor_user_id=user.id, target_type="session", target_id=str(session_id))
    if current and current.id == session_id:
        response.delete_cookie(SESSION_COOKIE_NAME, httponly=True, samesite="lax", secure=_secure_cookies(http_request), path="/")
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers=dict(response.headers))


def _set_session(response: Response, repository: AccountRepository, user: UserRecord, request: Request) -> AccountResponse:
    raw_token = new_token()
    trusted = user.role == "owner" and os.environ.get("BOOKTHINKING_DEPLOYMENT_MODE") == "local" and os.environ.get("BOOKTHINKING_TRUST_LOCAL_OWNER_SESSION") == "1" and _trusted_loopback(request)
    session_type = "trusted_local" if trusted else "standard"
    repository.create_session(user.id, raw_token=raw_token, session_type=session_type, expires_at=None if trusted else datetime.now(UTC) + timedelta(seconds=STANDARD_SESSION_MAX_AGE))
    _set_cookie(response, raw_token, TRUSTED_LOCAL_COOKIE_MAX_AGE if trusted else STANDARD_SESSION_MAX_AGE, request)
    return _account_response(user, session_type)


def _set_cookie(response: Response, token: str, max_age: int, request: Request) -> None:
    response.set_cookie(SESSION_COOKIE_NAME, token, max_age=max_age, httponly=True, samesite="lax", secure=_secure_cookies(request), path="/")


def _trusted_loopback(request: Request) -> bool:
    expected = os.environ.get("BOOKTHINKING_LOCAL_PROXY_SECRET", "")
    return bool(expected and request.headers.get("X-BookThinking-Client-Scope") == "trusted_loopback" and compare_digest(request.headers.get("X-BookThinking-Proxy-Secret", ""), expected))


def _secure_cookies(request: Request) -> bool:
    return os.environ.get("BOOKTHINKING_ENV", "production") not in {"test", "development"} and not _trusted_loopback(request)


def _account_response(user: UserRecord, session_type: str | None) -> AccountResponse:
    return AccountResponse(id=user.id, email=user.email, role=user.role, status=user.status, book_import_count=user.book_import_count, book_import_limit=user.book_import_limit, session_type=session_type, must_change_password=user.must_change_password)
