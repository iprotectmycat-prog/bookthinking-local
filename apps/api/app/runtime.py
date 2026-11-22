import os
from dataclasses import dataclass
from typing import Literal


class RuntimeConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class RuntimeSettings:
    deployment_mode: Literal["local", "cloud"]
    secret_backend: Literal["keyring", "environment"]
    analysis_workers: int

    @classmethod
    def from_environment(cls) -> "RuntimeSettings":
        deployment_mode = os.environ.get(
            "BOOKTHINKING_DEPLOYMENT_MODE", "local"
        ).strip().lower()
        if deployment_mode not in {"local", "cloud"}:
            raise RuntimeConfigurationError(
                "BOOKTHINKING_DEPLOYMENT_MODE must be local or cloud"
            )

        secret_backend = os.environ.get(
            "BOOKTHINKING_SECRET_BACKEND", "keyring"
        ).strip().lower()
        if secret_backend not in {"keyring", "environment"}:
            raise RuntimeConfigurationError(
                "BOOKTHINKING_SECRET_BACKEND must be keyring or environment"
            )

        raw_workers = os.environ.get("BOOKTHINKING_ANALYSIS_WORKERS", "24")
        try:
            analysis_workers = int(raw_workers)
        except ValueError as error:
            raise RuntimeConfigurationError(
                "BOOKTHINKING_ANALYSIS_WORKERS must be an integer from 1 to 24"
            ) from error
        if not 1 <= analysis_workers <= 24:
            raise RuntimeConfigurationError(
                "BOOKTHINKING_ANALYSIS_WORKERS must be an integer from 1 to 24"
            )

        if deployment_mode == "cloud" and (
            secret_backend != "environment" or analysis_workers != 1
        ):
            raise RuntimeConfigurationError(
                "cloud mode requires environment secrets and exactly one analysis worker"
            )

        return cls(
            deployment_mode=deployment_mode,
            secret_backend=secret_backend,
            analysis_workers=analysis_workers,
        )
