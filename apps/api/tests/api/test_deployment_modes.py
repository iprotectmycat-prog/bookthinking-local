import httpx
import pytest

from app.main import create_app
from app.runtime import RuntimeSettings
from app.services.accounts import AccountRepository
from app.services.authentication import hash_password
from app.services.storage import ApplicationPaths


@pytest.mark.anyio
async def test_local_books_endpoint_bootstraps_owner_without_cookie(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    app = create_app(
        RuntimeSettings(
            deployment_mode="local",
            secret_backend="keyring",
            analysis_workers=24,
        )
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/books/analyzed")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.anyio
async def test_cloud_register_and_mutations_are_disabled_even_with_old_owner_session(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.routes.analyses import get_analysis_provider

    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    paths = ApplicationPaths.from_environment()
    paths.ensure_exists()
    accounts = AccountRepository(paths.database_path)
    owner = accounts.bootstrap_owner(email="owner@example.com", password_hash=hash_password("password"))
    accounts.create_session(owner.id, raw_token="owner-token")
    accounts.create_invite("BT-ONCE")
    app = create_app(RuntimeSettings(deployment_mode="cloud", secret_backend="environment", analysis_workers=1))

    def unexpected_provider():
        pytest.fail("The public service must not initialize an analysis provider")

    app.dependency_overrides[get_analysis_provider] = unexpected_provider
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        registration = await client.post(
            "/auth/register",
            json={"email": "reader@example.com", "password": "password", "invite_code": "BT-ONCE"},
        )
        assert registration.status_code == 404
        for token in (None, "owner-token"):
            if token:
                client.cookies.set("bookthinking_session", token)
            for path in ("/library/analyzed", "/books/analyzed", "/settings/providers/current",
                         "/auth/session", "/admin/books", "/books/example/analysis-runs"):
                assert (await client.get(path)).status_code == 404, path
            upload = await client.post("/books", files={"file": ("book.pdf", b"sample", "application/pdf")})
            assert upload.status_code in (404, 405)
            for path in ("/books/example/analyses", "/books/example/chapters/1/analysis/retry",
                         "/books/example/structure-preview", "/books/example/learning-units",
                         "/books/example/source-chat"):
                assert (await client.post(path)).status_code in (404, 405), path
            for path in ("/books/example/chapters", "/books/example/structure", "/settings/providers/openai"):
                assert (await client.put(path, json={})).status_code in (404, 405), path

    assert [user.email for user in accounts.list_users()] == ["owner@example.com"]
    assert list(paths.books_dir.iterdir()) == []
