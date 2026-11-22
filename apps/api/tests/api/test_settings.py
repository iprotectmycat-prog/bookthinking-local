import httpx
import pytest

from app.api.routes.settings import get_keyring_store
from app.main import app
from app.services.storage import KeyringStore


class FakeKeyringClient:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def set_password(self, service_name: str, account: str, secret: str) -> None:
        self.values[(service_name, account)] = secret

    def get_password(self, service_name: str, account: str) -> str | None:
        return self.values.get((service_name, account))


@pytest.mark.anyio
async def test_provider_settings_response_never_returns_api_key(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    keyring_store = KeyringStore(client=FakeKeyringClient())
    app.dependency_overrides[get_keyring_store] = lambda: keyring_store
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put(
            "/settings/providers/openai",
            json={"model": "gpt-5", "api_key": "secret"},
        )
        current = await client.get("/settings/providers/current")

    assert response.status_code == 200
    assert response.json() == {"provider": "openai", "model": "gpt-5", "configured": True, "secondary_configured": False}
    assert "secret" not in response.text
    assert current.json() == {"provider": "openai", "model": "gpt-5", "configured": True, "secondary_configured": False}
    assert "secret" not in current.text
    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_deepseek_settings_can_save_four_keys_without_returning_them(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    keyring_store = KeyringStore(client=FakeKeyringClient())
    app.dependency_overrides[get_keyring_store] = lambda: keyring_store
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put(
            "/settings/providers/deepseek",
            json={
                "model": "deepseek-v4-pro",
                "api_key": "primary-secret",
                "api_key_secondary": "secondary-secret",
                "api_key_tertiary": "tertiary-secret",
                "api_key_quaternary": "quaternary-secret",
            },
        )
        current = await client.get("/settings/providers/current")

    expected = {"provider": "deepseek", "model": "deepseek-v4-pro", "configured": True, "secondary_configured": True}
    assert response.json() == expected
    assert current.json() == expected
    assert keyring_store.load_api_key("deepseek") == "primary-secret"
    assert keyring_store.load_api_key("deepseek-secondary") == "secondary-secret"
    assert keyring_store.load_api_key("deepseek-tertiary") == "tertiary-secret"
    assert keyring_store.load_api_key("deepseek-quaternary") == "quaternary-secret"
    assert "primary-secret" not in response.text
    assert "secondary-secret" not in current.text
    assert "tertiary-secret" not in current.text
    assert "quaternary-secret" not in current.text
    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_deepseek_settings_can_add_a_third_key_without_reentering_primary_key(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    keyring_store = KeyringStore(client=FakeKeyringClient())
    app.dependency_overrides[get_keyring_store] = lambda: keyring_store
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await client.put(
            "/settings/providers/deepseek",
            json={"model": "deepseek-v4-flash", "api_key": "primary-secret"},
        )
        response = await client.put(
            "/settings/providers/deepseek",
            json={"model": "deepseek-v4-flash", "api_key": "", "api_key_tertiary": "tertiary-secret"},
        )

    assert response.status_code == 200
    assert keyring_store.load_api_key("deepseek") == "primary-secret"
    assert keyring_store.load_api_key("deepseek-tertiary") == "tertiary-secret"
    assert "primary-secret" not in response.text
    assert "tertiary-secret" not in response.text
    app.dependency_overrides.clear()
