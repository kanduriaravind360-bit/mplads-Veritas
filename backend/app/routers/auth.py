"""Login and the current user."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app import audit, models
from backend.app.db import get_db
from backend.app.deps import Context, context
from backend.app.schemas import LoginRequest, TokenOut, UserOut
from backend.app.scoping import Scope
from backend.app.security import create_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_out(user: models.User) -> UserOut:
    out = UserOut.model_validate(user)
    out.scope_label = Scope.for_user(user).label
    return out


@router.post("/login", response_model=TokenOut)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenOut:
    user = db.execute(
        select(models.User).where(models.User.email == body.email.strip().lower())
    ).scalar_one_or_none()
    # Same error for unknown user and wrong password: do not reveal which emails exist.
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "incorrect email or password")
    audit.append(db, actor=user.email, action="login", entity_type="user", entity_id=str(user.id))
    db.commit()
    token = create_token(user.email, user.role)
    return TokenOut(access_token=token, user=_user_out(user))


@router.get("/me", response_model=UserOut)
def me(ctx: Context = Depends(context)) -> UserOut:
    return _user_out(ctx.user)
