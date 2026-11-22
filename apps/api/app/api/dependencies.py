from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request, status

from app.runtime import RuntimeSettings
from app.services.accounts import AccountRepository, UserRecord
from app.services.storage import ApplicationPaths


SESSION_COOKIE_NAME = "bookthinking_session"


def get_runtime_settings(request: Request) -> RuntimeSettings:
    return request.app.state.runtime_settings


def get_account_repository() -> AccountRepository:
    paths = ApplicationPaths.from_environment()
    paths.ensure_exists()
    return AccountRepository(paths.database_path)


def resolve_product_user(
    repository: Annotated[AccountRepository, Depends(get_account_repository)],
) -> UserRecord:
    return repository.get_or_bootstrap_local_owner()


def resolve_reader_owner_id(
    settings: Annotated[RuntimeSettings, Depends(get_runtime_settings)],
) -> int | None:
    if settings.deployment_mode == "cloud":
        return None
    return get_account_repository().get_or_bootstrap_local_owner().id


def require_current_user(
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    repository: Annotated[AccountRepository, Depends(get_account_repository)] = None,
) -> UserRecord:
    if session_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    user = repository.get_user_for_session(session_token)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录状态已失效")
    return user


def require_owner(
    user: Annotated[UserRecord, Depends(require_current_user)],
) -> UserRecord:
    if user.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅主账号可以执行此操作")
    return user


def require_product_owner(
    user: Annotated[UserRecord, Depends(resolve_product_user)],
) -> UserRecord:
    if user.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅主账号可以执行此操作")
    return user
