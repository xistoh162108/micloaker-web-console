from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from ..services.text_store import read_jsonl

router = APIRouter(prefix="/logs", tags=["logs"])
DIAGNOSTIC_FILES = {"app.log", "jobs.jsonl", "app_events.jsonl"}


@router.get("")
def logs_page(request: Request):
    workspace = request.app.state.settings.workspace
    context = _logs_context(workspace)
    context["selected_log"] = None
    context["traceback_text"] = _traceback_view_text(context["log_text"], context["job_tracebacks"])
    return request.app.state.templates.TemplateResponse(name="logs.html", request=request, context=context)


@router.get("/view/{log_path:path}")
def view_log(request: Request, log_path: str):
    workspace = request.app.state.settings.workspace.resolve()
    path = (workspace / log_path).resolve()
    if not _is_run_log_path(workspace, path) or not path.is_file():
        raise HTTPException(status_code=404, detail=_log_not_found_error(log_path))
    context = _logs_context(workspace)
    selected_text = path.read_text(encoding="utf-8")
    context["selected_log"] = {"path": log_path, "text": selected_text}
    context["traceback_text"] = _traceback_view_text(selected_text + "\n" + context["log_text"], context["job_tracebacks"])
    return request.app.state.templates.TemplateResponse(
        name="logs.html",
        request=request,
        context=context,
    )


@router.get("/download/{name}")
def download_diagnostic_log(request: Request, name: str):
    if name not in DIAGNOSTIC_FILES:
        raise HTTPException(status_code=404, detail=_diagnostic_not_found_error(name))
    workspace = request.app.state.settings.workspace.resolve()
    path = (workspace / ".micloaker" / name).resolve()
    try:
        path.relative_to((workspace / ".micloaker").resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=_diagnostic_not_found_error(name)) from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail=_diagnostic_not_found_error(name))
    return FileResponse(path, filename=name, media_type="text/plain", content_disposition_type="attachment")


def _logs_context(workspace: Path) -> dict:
    app_log = workspace / ".micloaker" / "app.log"
    jobs = workspace / ".micloaker" / "jobs.jsonl"
    app_events = workspace / ".micloaker" / "app_events.jsonl"
    text_blocks = []
    for label, path in [("app.log", app_log), ("jobs.jsonl", jobs), ("app_events.jsonl", app_events)]:
        if path.exists():
            text_blocks.append(f"== {label} ==\n{path.read_text(encoding='utf-8')}")
    text = "\n\n".join(text_blocks)
    run_logs = sorted(
        str(path.relative_to(workspace))
        for path in (workspace / "sessions").glob("*/logs/*.log")
        if path.is_file()
    )
    return {
        "log_text": text,
        "diagnostic_files": sorted(DIAGNOSTIC_FILES),
        "run_logs": run_logs,
        "job_rows": _job_rows(workspace, jobs),
        "job_tracebacks": _job_tracebacks(jobs),
        "mac_helper_rows": _mac_helper_rows(app_events),
    }


def _job_rows(workspace: Path, path: Path) -> list[dict[str, str | bool]]:
    rows = []
    for row in reversed(read_jsonl(path)):
        log_ref = str(row.get("logs") or "")
        log_path = (workspace / log_ref).resolve() if log_ref else workspace
        log_viewable = bool(log_ref) and _is_run_log_path(workspace, log_path) and log_path.is_file()
        rows.append({
            "event": str(row.get("event") or ""),
            "status": str(row.get("status") or ""),
            "job_id": str(row.get("job_id") or ""),
            "type": str(row.get("type") or row.get("name") or ""),
            "started_at": str(row.get("started_at") or row.get("created_at") or row.get("ts") or ""),
            "finished_at": str(row.get("finished_at") or ""),
            "logs": log_ref,
            "log_viewable": log_viewable,
            "error": str(row.get("error") or ""),
        })
    return rows


def _mac_helper_rows(path: Path) -> list[dict[str, str]]:
    rows = []
    for row in reversed(read_jsonl(path)):
        if row.get("event") != "mac_helper_client_action":
            continue
        rows.append({
            "ts": str(row.get("ts") or ""),
            "session_id": str(row.get("session_id") or ""),
            "run_id": str(row.get("run_id") or ""),
            "action": str(row.get("action") or ""),
            "ok": str(row.get("ok")),
            "error_code": str(row.get("error_code") or ""),
        })
    return rows


def _is_run_log_path(workspace: Path, path: Path) -> bool:
    try:
        rel = path.resolve().relative_to((workspace / "sessions").resolve())
    except ValueError:
        return False
    return len(rel.parts) == 3 and rel.parts[1] == "logs" and path.suffix == ".log"


def _log_not_found_error(log_path: str) -> dict[str, str]:
    return {
        "error_code": "LOG_NOT_FOUND",
        "message": f"Log {log_path} was not found.",
        "suggestion": "Open the Logs page and choose an existing run log under a session logs folder.",
    }


def _diagnostic_not_found_error(name: str) -> dict[str, str]:
    return {
        "error_code": "DIAGNOSTIC_LOG_NOT_FOUND",
        "message": f"Diagnostic log {name} was not found.",
        "suggestion": "Download one of app.log, jobs.jsonl, or app_events.jsonl from the Logs page.",
    }


def _job_tracebacks(path: Path) -> list[str]:
    blocks: list[str] = []
    for row in read_jsonl(path):
        traceback_text = row.get("traceback")
        if not traceback_text:
            continue
        header = f"job_id={row.get('job_id', '')} type={row.get('type') or row.get('name', '')} status={row.get('status', '')}"
        blocks.append(f"{header}\n{traceback_text}")
    return blocks


def _traceback_view_text(text: str, structured_tracebacks: list[str]) -> str:
    blocks = _extract_tracebacks(text)
    if blocks == "No tracebacks captured.":
        blocks = ""
    combined = "\n\n".join(item for item in [blocks, *structured_tracebacks] if item)
    return combined or "No tracebacks captured."


def _extract_tracebacks(text: str) -> str:
    lines = text.splitlines()
    blocks: list[str] = []
    index = 0
    while index < len(lines):
        if "Traceback (most recent call last):" not in lines[index]:
            index += 1
            continue
        block = [lines[index]]
        index += 1
        while index < len(lines):
            line = lines[index]
            if line.startswith("{") or line.startswith("[") or line.startswith("20"):
                break
            block.append(line)
            index += 1
            if line and not line.startswith((" ", "\t")) and (":" in line):
                break
        blocks.append("\n".join(block))
    return "\n\n".join(blocks) if blocks else "No tracebacks captured."
