from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.dependencies import (
    get_runtime_settings,
    require_product_owner,
    resolve_product_user,
)
from app.runtime import RuntimeSettings
from app.services.accounts import UserRecord
from app.services.storage import (
    ApplicationPaths,
    BookRepository,
    EnvironmentSecretStore,
    KeyringStore,
    ProviderMetadata,
    ProviderSettings,
    ReadOnlySecretStoreError,
    SecretStore,
)

router = APIRouter(prefix="/settings", tags=["settings"])


class ProviderSettingsRequest(BaseModel):
    model: str
    api_key: str
    api_key_secondary: str | None = None
    api_key_tertiary: str | None = None
    api_key_quaternary: str | None = None


def get_keyring_store() -> KeyringStore:
    return KeyringStore()


def get_secret_store(
    settings: Annotated[RuntimeSettings, Depends(get_runtime_settings)],
    keyring_store: Annotated[KeyringStore, Depends(get_keyring_store)],
) -> SecretStore:
    if settings.secret_backend == "environment":
        return EnvironmentSecretStore()
    return keyring_store


@router.put("/providers/{provider}")
def save_provider_settings(
    provider: str,
    request: ProviderSettingsRequest,
    _: Annotated[UserRecord, Depends(require_product_owner)],
    secret_store: Annotated[SecretStore, Depends(get_secret_store)],
) -> dict[str, str | bool]:
    paths = ApplicationPaths.from_environment()
    paths.ensure_exists()
    repository = BookRepository(paths.database_path)
    existing = repository.get_current_provider_metadata()
    try:
        if request.api_key:
            secret_store.save(ProviderSettings(provider=provider, model=request.model, api_key=request.api_key))
        elif existing is None or existing.provider != provider or not secret_store.load_api_key(provider):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="请先填写第一个 API Key")
        if provider == "deepseek":
            for slot, key in (
                ("deepseek-secondary", request.api_key_secondary),
                ("deepseek-tertiary", request.api_key_tertiary),
                ("deepseek-quaternary", request.api_key_quaternary),
            ):
                if key:
                    secret_store.save(ProviderSettings(provider=slot, model=request.model, api_key=key))
    except ReadOnlySecretStoreError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    repository.save_provider_metadata(ProviderMetadata(provider=provider, model=request.model))
    return {
        "provider": provider,
        "model": request.model,
        "configured": True,
        "secondary_configured": provider == "deepseek" and bool(secret_store.load_api_key("deepseek-secondary")),
    }


@router.get("/providers/current")
def current_provider_settings(
    _: Annotated[UserRecord, Depends(resolve_product_user)],
    secret_store: Annotated[SecretStore, Depends(get_secret_store)],
) -> dict[str, str | bool]:
    paths = ApplicationPaths.from_environment()
    paths.ensure_exists()
    metadata = BookRepository(paths.database_path).get_current_provider_metadata()
    return {
        "provider": metadata.provider if metadata else "",
        "model": metadata.model if metadata else "",
        "configured": bool(metadata and secret_store.load_api_key(metadata.provider)),
        "secondary_configured": bool(metadata and metadata.provider == "deepseek" and secret_store.load_api_key("deepseek-secondary")),
    }
