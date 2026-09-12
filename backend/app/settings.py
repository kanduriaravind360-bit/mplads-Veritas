"""Runtime settings: policy from configs/api.yaml, secrets from the environment.

Secrets never live in the repository. ``JWT_SECRET`` and ``DATABASE_URL`` are
read from the environment; without them the app runs on a development secret
and a local SQLite file, and says so loudly at startup.
"""

from __future__ import annotations

import os
import warnings
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEV_SECRET = "dev-only-secret-change-me-before-any-deployment"


def _load_yaml(name: str) -> dict[str, Any]:
    with (PROJECT_ROOT / "configs" / f"{name}.yaml").open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"configs/{name}.yaml did not parse to a mapping")
    return data


@dataclass(frozen=True)
class Settings:
    """Everything the backend reads at startup."""

    api: dict[str, Any]
    database_url: str
    jwt_secret: str
    presentation_mode: bool
    cors_origins: list[str] = field(default_factory=list)
    scheduler_enabled: bool = True

    @property
    def is_dev_secret(self) -> bool:
        return self.jwt_secret == _DEV_SECRET


def _sqlite_url(url: str) -> str:
    """Resolve a relative SQLite path against the project root and make its folder."""
    prefix = "sqlite:///"
    if not url.startswith(prefix) or url == "sqlite:///:memory:":
        return url
    raw = url[len(prefix) :]
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"{prefix}{path.as_posix()}"


@cache
def get_settings() -> Settings:
    api = _load_yaml("api")
    secret = os.environ.get("JWT_SECRET", _DEV_SECRET)
    if secret == _DEV_SECRET:
        warnings.warn(
            "JWT_SECRET is not set; using a development secret. Never deploy like this.",
            stacklevel=2,
        )
    origins = os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    return Settings(
        api=api,
        database_url=_sqlite_url(os.environ.get("DATABASE_URL", api["database"]["default_url"])),
        jwt_secret=secret,
        presentation_mode=os.environ.get("PRESENTATION_MODE", "0") == "1",
        cors_origins=[o.strip() for o in origins.split(",") if o.strip()],
        scheduler_enabled=os.environ.get("SCHEDULER_ENABLED", "1") == "1"
        and bool(api["scheduler"]["enabled"]),
    )
