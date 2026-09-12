"""Background jobs: nightly re-score and hourly escalation (APScheduler).

The nightly job re-runs the ML pipeline in a subprocess, reloads its outputs
(new alerts are raised, alerts that no longer fire are retired, reviewed alerts
keep their status), then runs escalation. Both jobs are plain functions, so the
admin endpoints and the tests call them directly.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from datetime import UTC, datetime
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler

from backend.app import models
from backend.app.db import session_scope
from backend.app.services.alerts import escalate_due
from backend.app.settings import PROJECT_ROOT, get_settings

log = logging.getLogger("sentinel.scheduler")
_scheduler: BackgroundScheduler | None = None


def run_escalation() -> list[dict[str, Any]]:
    with session_scope() as db:
        moved = escalate_due(db)
    if moved:
        log.info("escalated %d alerts", len(moved))
    return moved


def _command() -> list[str]:
    command = list(get_settings().api["scheduler"]["rescore_command"])
    if command and command[0] == "python":
        command[0] = sys.executable
    return command


def run_rescore(kind: str = "nightly", command: list[str] | None = None) -> dict[str, Any]:
    """Re-run the pipeline, reload, escalate. Records the attempt either way."""
    started = datetime.now(UTC).replace(tzinfo=None)
    command = command if command is not None else _command()
    outcome: dict[str, Any] = {"kind": kind, "started_at": started.isoformat()}
    try:
        if command:
            completed = subprocess.run(  # noqa: S603 - fixed command from config
                command, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=3600, check=False
            )
            outcome["pipeline_exit_code"] = completed.returncode
            if completed.returncode != 0:
                raise RuntimeError(
                    f"pipeline exited {completed.returncode}: {completed.stderr[-2000:]}"
                )
        from backend.app.loader import run as load

        outcome["load"] = load(kind=kind)
        outcome["escalated"] = len(run_escalation())
        outcome["status"] = "ok"
    except Exception as error:  # noqa: BLE001 - a failed night must be recorded, not lost
        outcome["status"] = "failed"
        outcome["error"] = str(error)
        with session_scope() as db:
            db.add(
                models.ScoringRun(
                    kind=kind,
                    started_at=started,
                    finished_at=datetime.now(UTC).replace(tzinfo=None),
                    status="failed",
                    message=str(error)[:4000],
                )
            )
        log.exception("re-score failed")
    return outcome


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    cfg = get_settings().api["scheduler"]
    scheduler = BackgroundScheduler(timezone="Asia/Kolkata")
    scheduler.add_job(
        run_escalation,
        "interval",
        minutes=int(cfg["escalation_interval_minutes"]),
        id="escalation",
        replace_existing=True,
    )
    scheduler.add_job(
        run_rescore,
        "cron",
        hour=int(cfg["rescore_cron_hour"]),
        minute=int(cfg["rescore_cron_minute"]),
        id="nightly_rescore",
        replace_existing=True,
    )
    scheduler.start()
    _scheduler = scheduler
    return scheduler


def jobs() -> list[dict[str, Any]]:
    if _scheduler is None:
        return []
    return [
        {
            "id": j.id,
            "next_run_time": j.next_run_time.isoformat() if j.next_run_time else None,
            "trigger": str(j.trigger),
        }
        for j in _scheduler.get_jobs()
    ]
