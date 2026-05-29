from __future__ import annotations

import traceback
import uuid
from pathlib import Path
from typing import Callable

from .text_store import append_jsonl, append_log, now_iso, read_jsonl, relative_to_workspace


def run_job(workspace: Path, name: str, log_path: Path, func: Callable[[], object]) -> object:
    _require_log_inside_workspace(workspace, log_path)
    job_id = f"job_{uuid.uuid4().hex[:10]}"
    created_at = now_iso()
    log_ref = _log_ref(workspace, log_path)
    append_jsonl(workspace / ".micloaker" / "jobs.jsonl", _job_event("job_started", "running", job_id, name, created_at=created_at, started_at=created_at, logs=log_ref))
    append_log(log_path, f"job_started {job_id} {name}")
    _append_job_app_log(workspace, "job_started", job_id, name, log_ref)
    try:
        result = func()
    except Exception as exc:
        tb = traceback.format_exc()
        append_log(log_path, f"job_failed {job_id}: {exc}\n{tb}")
        _append_job_app_log(workspace, "job_failed", job_id, name, log_ref, error=str(exc))
        append_jsonl(
            workspace / ".micloaker" / "jobs.jsonl",
            _job_event(
                "job_failed",
                "failed",
                job_id,
                name,
                created_at=created_at,
                started_at=created_at,
                finished_at=now_iso(),
                logs=log_ref,
                error=str(exc),
                traceback_text=tb,
            ),
        )
        raise
    append_log(log_path, f"job_finished {job_id} {name}")
    _append_job_app_log(workspace, "job_finished", job_id, name, log_ref)
    append_jsonl(
        workspace / ".micloaker" / "jobs.jsonl",
        _job_event("job_finished", "finished", job_id, name, created_at=created_at, started_at=created_at, finished_at=now_iso(), logs=log_ref),
    )
    return result


def mark_unfinished_jobs_interrupted(workspace: Path) -> int:
    jobs_path = workspace / ".micloaker" / "jobs.jsonl"
    terminal: set[str] = set()
    started: dict[str, dict] = {}
    for row in read_jsonl(jobs_path):
        job_id = row.get("job_id")
        if not job_id:
            continue
        if row.get("event") == "job_started":
            started[job_id] = row
        if row.get("event") in {"job_finished", "job_failed", "job_interrupted"}:
            terminal.add(job_id)
    count = 0
    for job_id, row in started.items():
        if job_id not in terminal:
            append_jsonl(jobs_path, {
                "event": "job_interrupted",
                "type": row.get("type") or row.get("name", ""),
                "status": "interrupted",
                "job_id": job_id,
                "name": row.get("name", ""),
                "created_at": row.get("created_at"),
                "started_at": row.get("started_at") or row.get("ts"),
                "finished_at": now_iso(),
                "logs": row.get("logs", ""),
                "error": "Job was interrupted before a terminal status was written.",
                "traceback": None,
                "message": "Job was running when the app last stopped or restarted.",
            })
            _append_interrupted_log(workspace, row)
            _append_job_app_log(
                workspace,
                "job_interrupted",
                job_id,
                row.get("type") or row.get("name", ""),
                row.get("logs", ""),
                error="Job was interrupted before a terminal status was written.",
            )
            count += 1
    return count


def _append_interrupted_log(workspace: Path, row: dict) -> None:
    log_ref = row.get("logs")
    if not log_ref:
        return
    path = Path(log_ref)
    if not path.is_absolute():
        path = workspace / log_ref
    try:
        path.resolve().relative_to(workspace.resolve())
    except ValueError:
        return
    append_log(path, f"job_interrupted {row.get('job_id', '')}: Job was running when the app last stopped or restarted.")


def _require_log_inside_workspace(workspace: Path, log_path: Path) -> None:
    try:
        log_path.resolve().relative_to(workspace.resolve())
    except ValueError as exc:
        raise ValueError("job log path must stay inside the workspace") from exc


def _job_event(
    event: str,
    status: str,
    job_id: str,
    name: str,
    *,
    created_at: str,
    started_at: str,
    finished_at: str | None = None,
    logs: str = "",
    error: str | None = None,
    traceback_text: str | None = None,
) -> dict:
    return {
        "event": event,
        "type": name,
        "status": status,
        "job_id": job_id,
        "name": name,
        "created_at": created_at,
        "started_at": started_at,
        "finished_at": finished_at,
        "logs": logs,
        "error": error,
        "traceback": traceback_text,
    }


def _log_ref(workspace: Path, log_path: Path) -> str:
    try:
        return relative_to_workspace(workspace, log_path)
    except ValueError:
        return str(log_path)


def _append_job_app_log(workspace: Path, event: str, job_id: str, name: str, logs: str, *, error: str | None = None) -> None:
    details = f"{event} {job_id} type={name} logs={logs}"
    if error:
        details += f" error={error}"
    append_log(workspace / ".micloaker" / "app.log", details)
