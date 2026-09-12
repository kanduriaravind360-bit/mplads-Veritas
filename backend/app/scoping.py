"""Row-level scoping, enforced on the server for every query.

The rule is simple and applied in one place:

    MINISTRY  sees everything
    STATE     sees rows where state == the user's state
    DISTRICT  sees rows where ida == the user's district office (IDA)
    MP        sees rows where mp_code == the user's MP code

Three properties make this hard to get around:

* Routers never build their own ``WHERE state = ...``. They call
  :meth:`Scope.apply`, which is the only place the rule is written.
* User-supplied filters are ANDed with the scope, so a district user asking for
  ``?state=Bihar`` gets Bihar rows *inside their own district*, i.e. nothing.
* Fetching a single row by id goes through the same filter, and an out-of-scope
  id returns 404 rather than 403, so the API does not even confirm that another
  district's alert exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import Select, exists, select

from backend.app import models

MINISTRY = "MINISTRY"
STATE = "STATE"
DISTRICT = "DISTRICT"
MP = "MP"


@dataclass(frozen=True)
class Scope:
    role: str
    state: str | None = None
    ida: str | None = None
    mp_code: str | None = None

    @classmethod
    def for_user(cls, user: models.User) -> Scope:
        scope = cls(role=user.role, state=user.state, ida=user.ida, mp_code=user.mp_code)
        scope.validate()
        return scope

    def validate(self) -> None:
        """A scoped role with no scope value would otherwise see nothing or everything."""
        needed = {STATE: self.state, DISTRICT: self.ida, MP: self.mp_code}
        if self.role in needed and not needed[self.role]:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, f"{self.role} user has no scope assigned"
            )
        if self.role not in {MINISTRY, STATE, DISTRICT, MP}:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "unknown role")

    @property
    def label(self) -> str:
        return {
            MINISTRY: "All India",
            STATE: f"State: {self.state}",
            DISTRICT: f"District office: {self.ida}",
            MP: f"MP code {self.mp_code}",
        }[self.role]

    def apply(self, stmt: Select[Any], model: type) -> Select[Any]:
        """Restrict a SELECT on ``model`` to this scope."""
        if self.role == MINISTRY:
            return stmt
        if self.role == STATE:
            return stmt.where(model.state == self.state)
        if self.role == DISTRICT:
            return stmt.where(model.ida == self.ida)
        if self.role == MP:
            if model is models.Alert:
                # A group alert can span several works; the MP sees it when any
                # of its works is theirs.
                member = (
                    select(models.AlertWork.alert_id)
                    .join(models.Work, models.Work.work_id == models.AlertWork.work_id)
                    .where(
                        models.AlertWork.alert_id == models.Alert.alert_id,
                        models.Work.mp_code == self.mp_code,
                    )
                )
                return stmt.where(exists(member))
            return stmt.where(model.mp_code == self.mp_code)
        raise HTTPException(status.HTTP_403_FORBIDDEN, "unknown role")

    def allows_row(self, row: Any) -> bool:
        """Python-side check for an already-loaded row (used for writes and uploads)."""
        if self.role == MINISTRY:
            return True
        if self.role == STATE:
            return getattr(row, "state", None) == self.state
        if self.role == DISTRICT:
            return getattr(row, "ida", None) == self.ida
        if self.role == MP:
            return getattr(row, "mp_code", None) == self.mp_code
        return False

    def allows_values(self, state: str | None, ida: str | None, mp_code: str | None) -> bool:
        if self.role == MINISTRY:
            return True
        if self.role == STATE:
            return state == self.state
        if self.role == DISTRICT:
            return ida == self.ida
        if self.role == MP:
            return mp_code == self.mp_code
        return False


def not_found(kind: str) -> HTTPException:
    """The same response for "does not exist" and "not yours"."""
    return HTTPException(status.HTTP_404_NOT_FOUND, f"{kind} not found")
