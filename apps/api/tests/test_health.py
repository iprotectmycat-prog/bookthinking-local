import httpx
import pytest

from app.main import app, create_app
from app.runtime import RuntimeSettings


@pytest.mark.anyio
async def test_health_returns_ok() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_ready_reports_the_active_runtime_mode() -> None:
    cloud = create_app(
        RuntimeSettings(deployment_mode="cloud", secret_backend="environment", analysis_workers=1)
    )
    transport = httpx.ASGITransport(app=cloud)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "deployment_mode": "cloud"}
