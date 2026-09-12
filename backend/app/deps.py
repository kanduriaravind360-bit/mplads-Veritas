"""Request dependencies: the authenticated user, their scope, role guards."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app import models
from backend.app.db import get_db
from backend.app.scoping import Scope
from backend.app.security import decode_token
from backend.app.settings import get_settings

_bearer = HTTPBearer(auto_error=False)


@dataclass
class Context:
    """Everything a scoped endpoint needs about the caller."""

    user: models.User
    scope: Scope
    db: Session


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> models.User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = decode_token(credentials.credentials)
    except jwt.PyJWTError as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token") from error
    user = db.execute(
        select(models.User).where(models.User.email == claims.get("sub"))
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user not found or inactive")
    return user


def context(user: models.User = Depends(current_user), db: Session = Depends(get_db)) -> Context:
    return Context(user=user, scope=Scope.for_user(user), db=db)


def require_roles(*roles: str) -> Callable[[Context], Context]:
    def _guard(ctx: Context = Depends(context)) -> Context:
        if ctx.user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"requires one of: {', '.join(roles)}")
        return ctx

    return _guard


def reviewer(ctx: Context = Depends(context)) -> Context:
    if ctx.user.role not in set(get_settings().api["alerts"]["reviewer_roles"]):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "this role views implementation risk but does not review alerts",
        )
    return ctx


@dataclass
class Page:
    limit: int
    offset: int


def page(
    limit: int = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0),
) -> Page:
    cfg = get_settings().api["pagination"]
    chosen = int(limit or cfg["default_limit"])
    return Page(limit=min(chosen, int(cfg["max_limit"])), offset=offset)
