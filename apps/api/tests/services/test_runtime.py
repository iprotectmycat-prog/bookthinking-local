import pytest

from app.runtime import RuntimeConfigurationError, RuntimeSettings


def test_runtime_defaults_to_local_keychain_and_24_workers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "BOOKTHINKING_DEPLOYMENT_MODE",
        "BOOKTHINKING_SECRET_BACKEND",
        "BOOKTHINKING_ANALYSIS_WORKERS",
    ):
        monkeypatch.delenv(name, raising=False)

    assert RuntimeSettings.from_environment() == RuntimeSettings(
        deployment_mode="local",
        secret_backend="keyring",
        analysis_workers=24,
    )


def test_cloud_runtime_requires_environment_secrets_and_one_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOOKTHINKING_DEPLOYMENT_MODE", "cloud")
    monkeypatch.setenv("BOOKTHINKING_SECRET_BACKEND", "keyring")
    monkeypatch.setenv("BOOKTHINKING_ANALYSIS_WORKERS", "24")

    with pytest.raises(RuntimeConfigurationError, match="cloud mode requires"):
        RuntimeSettings.from_environment()


def test_cloud_runtime_accepts_environment_secrets_and_one_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOOKTHINKING_DEPLOYMENT_MODE", "cloud")
    monkeypatch.setenv("BOOKTHINKING_SECRET_BACKEND", "environment")
    monkeypatch.setenv("BOOKTHINKING_ANALYSIS_WORKERS", "1")

    assert RuntimeSettings.from_environment() == RuntimeSettings(
        deployment_mode="cloud",
        secret_backend="environment",
        analysis_workers=1,
    )
