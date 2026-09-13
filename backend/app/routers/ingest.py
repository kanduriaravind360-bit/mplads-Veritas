"""Data ingest: CSV/XLSX upload, validation, live scoring, optional commit."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from sqlalchemy import select

from backend.app import models
from backend.app.deps import Context, reviewer
from backend.app.redact import redact_record
from backend.app.services import ingest as svc

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.get("/template.csv")
def template(ctx: Context = Depends(reviewer)) -> Response:
    columns = svc.template_columns()
    return Response(
        content=",".join(columns) + "\n",
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="mplads_upload_template.csv"'},
    )


@router.post("")
async def upload(
    file: UploadFile = File(...),
    commit: bool = Form(default=False),
    ctx: Context = Depends(reviewer),
) -> dict[str, Any]:
    content = await file.read()
    try:
        frame = svc.read_upload(file.filename or "upload.csv", content)
    except Exception as error:  # noqa: BLE001 - any parse failure is a user error here
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"could not read the file: {error}"
        ) from error

    result = svc.validate(ctx.db, ctx.scope, frame)
    run = models.IngestRun(
        filename=file.filename or "upload",
        created_by=ctx.user.id,
        rows=len(frame),
        valid_rows=int(len(result.valid)),
        errors=result.errors,
    )
    ctx.db.add(run)

    response: dict[str, Any] = {
        "filename": file.filename,
        "rows": len(frame),
        "valid_rows": int(len(result.valid)),
        "errors": result.errors,
        "warnings": result.warnings[:200],
        "scored": None,
        "committed": None,
    }
    if result.errors or result.valid.empty:
        ctx.db.commit()
        response["run_id"] = run.id
        return response

    scored, elapsed = await run_in_threadpool(svc.score, result.valid)
    summary = svc.summarise(scored, elapsed)
    # Uploaded descriptions can name people too; presentation mode masks them here.
    summary["top"] = [redact_record(row) for row in summary["top"]]
    response["scored"] = summary
    run.summary = summary

    if commit:
        response["committed"] = svc.commit(ctx.db, ctx.user, scored)
        run.committed = True
    ctx.db.commit()
    response["run_id"] = run.id
    return response


@router.get("/runs")
def runs(ctx: Context = Depends(reviewer)) -> list[dict[str, Any]]:
    rows = ctx.db.execute(
        select(models.IngestRun)
        .where(models.IngestRun.created_by == ctx.user.id)
        .order_by(models.IngestRun.created_at.desc())
        .limit(50)
    ).scalars()
    return [
        {
            "id": r.id,
            "filename": r.filename,
            "rows": r.rows,
            "valid_rows": r.valid_rows,
            "committed": r.committed,
            "errors": len(r.errors or []),
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
