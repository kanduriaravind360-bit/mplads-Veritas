"""FastAPI application.

    uvicorn backend.app.main:app --reload

OpenAPI docs at /docs. Every data endpoint requires a JWT except /public/*,
which serves the citizen view and never returns per-work risk.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib import import_module
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.app.db import create_all
from backend.app.settings import get_settings

log = logging.getLogger("sentinel")
SLOW_REQUEST_SECONDS = 3.0

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
    "learning",
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
        expose_headers=["Content-Disposition", "X-Request-ID"],
    )

    @app.middleware("http")
    async def request_id(request: Request, call_next: Any) -> Any:
        """Tag every request, log slow ones, and hide internals behind a reference."""
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # Full traceback to the server log; the client gets only a reference.
            log.exception("unhandled error on %s %s [%s]", request.method, request.url.path, rid)
            response = JSONResponse(
                status_code=500,
                content={"detail": f"Something went wrong on the server. Reference {rid}."},
            )
        elapsed = time.perf_counter() - started
        if elapsed > SLOW_REQUEST_SECONDS:
            log.warning(
                "slow request %s %s took %.2fs [%s]",
                request.method,
                request.url.path,
                elapsed,
                rid,
            )
        response.headers["X-Request-ID"] = rid
        return response

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
