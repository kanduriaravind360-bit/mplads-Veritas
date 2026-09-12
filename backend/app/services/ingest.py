"""Upload -> validate -> score -> summary, and optionally commit.

Validation happens before any scoring, row by row, and every problem is
reported with its row number and column so a district clerk can fix the file.
Scope is enforced on the rows themselves: a district reviewer can only upload
works for their own district office, and the whole file is rejected otherwise.
"""

from __future__ import annotations

import io
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from backend.app import audit, models
from backend.app.geo import district_from_ida, mp_code_from_work_id
from backend.app.scoping import DISTRICT, MINISTRY, MP, STATE, Scope
from backend.app.settings import PROJECT_ROOT, get_settings

TEMPLATE = PROJECT_ROOT / "demo_data" / "live_demo_works.csv"


@dataclass
class ValidationResult:
    frame: pd.DataFrame
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    valid_mask: pd.Series | None = None

    @property
    def valid(self) -> pd.DataFrame:
        if self.valid_mask is None:
            return self.frame.iloc[0:0]
        return self.frame.loc[self.valid_mask]


def template_columns() -> list[str]:
    if TEMPLATE.exists():
        return [
            c
            for c in pd.read_csv(TEMPLATE, nrows=0).columns
            if c not in {"demo_key", "expected_outcome"}
        ]
    return list(get_settings().api["ingest"]["required_columns"])


def read_upload(filename: str, content: bytes) -> pd.DataFrame:
    name = filename.lower()
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(content))
    if name.endswith(".csv"):
        return pd.read_csv(io.BytesIO(content))
    raise ValueError("upload a .csv or .xlsx file")


def validate(db: Session, scope: Scope, frame: pd.DataFrame) -> ValidationResult:
    cfg = get_settings().api["ingest"]
    result = ValidationResult(frame=frame.reset_index(drop=True))
    limit = int(cfg["max_errors_reported"])

    def error(row: int | None, column: str | None, message: str) -> None:
        if len(result.errors) < limit:
            result.errors.append({"row": row, "column": column, "message": message})

    missing = [c for c in cfg["required_columns"] if c not in frame.columns]
    if missing:
        error(None, None, f"missing required columns: {', '.join(missing)}")
        return result
    if frame.empty:
        error(None, None, "the file has no rows")
        return result
    if len(frame) > int(cfg["max_rows"]):
        error(
            None, None, f"the file has {len(frame):,} rows; the limit is {int(cfg['max_rows']):,}"
        )
        return result

    df = result.frame
    ok = pd.Series(True, index=df.index)
    # Spreadsheet row numbers: header is row 1.
    rownum = df.index + 2

    ids = df["work_id"].astype(str).str.strip()
    blank_id = df["work_id"].isna() | (ids == "") | (ids.str.lower() == "nan")
    for i in df.index[blank_id]:
        error(int(rownum[i]), "work_id", "work_id is empty")
    ok &= ~blank_id

    dup = ids.duplicated(keep=False) & ~blank_id
    for i in df.index[dup]:
        error(int(rownum[i]), "work_id", f"work_id '{ids[i]}' appears more than once in this file")
    ok &= ~dup

    existing = {
        w
        for (w,) in db.execute(
            select(models.Work.work_id).where(models.Work.work_id.in_(ids[~blank_id].tolist()))
        ).all()
    }
    clash = ids.isin(existing)
    for i in df.index[clash]:
        error(int(rownum[i]), "work_id", f"work_id '{ids[i]}' already exists in the system")
    ok &= ~clash

    amount = pd.to_numeric(df["sanction_amount"], errors="coerce")
    bad_amount = amount.isna() | (amount <= 0)
    for i in df.index[bad_amount]:
        error(int(rownum[i]), "sanction_amount", "sanction_amount must be a positive number")
    ok &= ~bad_amount

    for column in ("recommended_date", "sanction_date"):
        parsed = pd.to_datetime(df[column], errors="coerce")
        bad = parsed.isna()
        for i in df.index[bad]:
            error(int(rownum[i]), column, f"{column} is missing or not a date")
        ok &= ~bad

    rec = pd.to_datetime(df["recommended_date"], errors="coerce")
    san = pd.to_datetime(df["sanction_date"], errors="coerce")
    backwards = (san < rec).fillna(False)
    for i in df.index[backwards]:
        result.warnings.append(
            {
                "row": int(rownum[i]),
                "column": "sanction_date",
                "message": "sanctioned before it was recommended; kept and flagged",
            }
        )

    for column in ("state", "ida", "work_description", "work_status"):
        blank = df[column].isna() | (df[column].astype(str).str.strip() == "")
        for i in df.index[blank]:
            error(int(rownum[i]), column, f"{column} is empty")
        ok &= ~blank

    # Scope: every row must belong to the uploader. One stray row rejects the file,
    # because a partial upload of someone else's district is not a clerical slip.
    if scope.role != MINISTRY:
        if scope.role == STATE:
            outside = df["state"].astype(str).str.strip() != scope.state
            column = "state"
        elif scope.role == DISTRICT:
            outside = df["ida"].astype(str).str.strip() != scope.ida
            column = "ida"
        elif scope.role == MP:
            outside = ids.map(mp_code_from_work_id) != scope.mp_code
            column = "work_id"
        else:
            outside = pd.Series(True, index=df.index)
            column = "state"
        if outside.any():
            first = int(rownum[df.index[outside][0]])
            error(
                first,
                column,
                f"{int(outside.sum())} row(s) fall outside your scope ({scope.label}); the file was rejected",
            )
            ok &= False

    result.valid_mask = ok
    return result


def _prepare_for_scoring(frame: pd.DataFrame) -> pd.DataFrame:
    """Fill optional columns the pipeline expects, so a minimal upload still scores."""
    out = frame.copy()
    for column in template_columns():
        if column not in out.columns:
            out[column] = np.nan
    for flag in [c for c in out.columns if c.startswith("flag_")]:
        out[flag] = out[flag].fillna(False).astype(bool)
    for column in ("anomaly_score", "anomaly_label"):
        out[column] = pd.to_numeric(out[column], errors="coerce").fillna(0).astype(int)
    out["flag_reasons"] = out["flag_reasons"].fillna("No rule-based flags")
    return out


def score(frame: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    from ml.pipeline import score_new_works

    started = time.perf_counter()
    scored = score_new_works(_prepare_for_scoring(frame).reset_index(drop=True))
    return scored, time.perf_counter() - started


def summarise(scored: pd.DataFrame, elapsed: float) -> dict[str, Any]:
    bands = scored["band"].value_counts().to_dict()
    top = scored.sort_values("risk_score", ascending=False).head(25)
    return {
        "scored": int(len(scored)),
        "elapsed_seconds": round(elapsed, 2),
        "bands": {b: int(bands.get(b, 0)) for b in ("Low", "Medium", "High", "Critical")},
        "top": [
            {
                "work_id": str(r["work_id"]),
                "work_description": r.get("work_description"),
                "sanction_amount": float(r["sanction_amount"]),
                "risk_score": round(float(r["risk_score"]), 2),
                "band": r["band"],
                "reasons_en": list(r["reasons_en"])[:4],
                "reasons_hi": list(r["reasons_hi"])[:4],
            }
            for _, r in top.iterrows()
        ],
        "scoring_scope": str(scored["scoring_scope"].iloc[0])
        if "scoring_scope" in scored and len(scored)
        else None,
    }


def commit(db: Session, user: models.User, scored: pd.DataFrame) -> dict[str, int]:
    """Insert scored works and raise alerts for High/Critical ones."""
    from backend.app.loader import _work_rows

    rows = _work_rows(scored, "ingest")
    for chunk in (rows[i : i + 2000] for i in range(0, len(rows), 2000)):
        db.execute(insert(models.Work), chunk)
    now = datetime.now(UTC).replace(tzinfo=None)
    alerts = 0
    for row in rows:
        if row["band"] not in {"High", "Critical"}:
            continue
        db.add(
            models.Alert(
                alert_id=row["work_id"],
                alert_type="high_risk_work",
                severity=row["band"],
                risk_score=row["risk_score"],
                amount=row["sanction_amount"],
                n_works=1,
                state=row["state"],
                ida=row["ida"],
                district=district_from_ida(row["ida"]),
                constituency=row["constituency"],
                mp_code=row["mp_code"],
                work_type=row["work_type"],
                reasons_en=row["reasons_en"],
                reasons_hi=row["reasons_hi"],
                evidence={"work_ids": [row["work_id"]], "source": "ingest"},
                source="ingest",
                raised_at=now,
                updated_at=now,
            )
        )
        db.flush()
        db.add(models.AlertWork(alert_id=row["work_id"], work_id=row["work_id"]))
        alerts += 1
    audit.append(
        db,
        actor=user.email,
        action="ingest_commit",
        entity_type="works",
        entity_id="ingest",
        payload={"works": len(rows), "alerts": alerts},
    )
    return {"works": len(rows), "alerts": alerts}
