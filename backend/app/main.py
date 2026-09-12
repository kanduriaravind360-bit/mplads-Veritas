"""FastAPI application.

    uvicorn backend.app.main:app --reload

OpenAPI docs at /docs. Every data endpoint requires a JWT except /public/*,
which serves the citizen view and never returns per-work risk.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib import import_module

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.db import create_all
from backend.app.settings import get_settings

log = logging.getLogger("sentinel")

_ROUTERS = (
    "auth",
    "overview",
    "works",
    "alerts",
    "duplicates",
    "splits",
    "network",
    "compliance",
    "predictions",
    "geo",
    "analytics",
    "models_api",
    "ingest",
    "reports",
    "cases",
    "public",
    "admin",
    "search",
    "portfolio",
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    create_all()
    if settings.is_dev_secret:
        log.warning(
            "Running with the development JWT secret. Set JWT_SECRET before any deployment."
        )
    scheduler = None
    if settings.scheduler_enabled:
        from backend.app.scheduler import start_scheduler

        scheduler = start_scheduler()
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="MPLADS Sentinel API",
        version="1.0.0",
        description=(
            "Risk indicators for review of MPLADS works. Nothing returned here is a "
            "finding of fraud. MP-level figures describe the implementation risk of "
            "works recommended in a constituency, never a judgement of the MP."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )

    for name in _ROUTERS:
        # Strict: a router listed here that fails to import must stop the app,
        # not quietly disappear from the API.
        module = import_module(f"backend.app.routers.{name}")
        app.include_router(module.router, prefix="/api")
        if hasattr(module, "audit_router"):
            app.include_router(module.audit_router, prefix="/api")

    @app.get("/api/health", tags=["health"])
    def health() -> dict[str, object]:
        return {"ok": True, "presentation_mode": settings.presentation_mode}

    return app


app = create_app()
