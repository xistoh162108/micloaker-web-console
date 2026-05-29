from __future__ import annotations

import os
import signal
import threading

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse

from ..services.lab_validation import VALIDATION_GATES, ensure_validation_artifacts, list_validation_records, record_lab_validation, validation_summary
from ..services.readiness import lab_readiness
from ..services.recorder import recording_status
from ..services.text_store import append_app_event

router = APIRouter(prefix="/ops", tags=["ops"])


@router.get("")
def ops_page(request: Request):
    settings = request.app.state.settings
    readiness = lab_readiness(settings)
    validation = validation_summary(settings.workspace)
    return request.app.state.templates.TemplateResponse(
        name="ops.html",
        request=request,
        context={
            "workspace": settings.workspace,
            "host": settings.host,
            "port": settings.port,
            "allow_web_shutdown": settings.allow_web_shutdown,
            "recording_status": recording_status(),
            "readiness": readiness,
            "validation_gates": VALIDATION_GATES,
            "validation": validation,
        },
    )


@router.get("/readiness")
def readiness_status(request: Request):
    return lab_readiness(request.app.state.settings)


@router.get("/validation")
def validation_status(request: Request):
    workspace = request.app.state.settings.workspace
    return {
        "ok": True,
        "gates": VALIDATION_GATES,
        "summary": validation_summary(workspace),
        "records": list_validation_records(workspace),
    }


@router.get("/validation/files/{filename}")
def download_validation_file(request: Request, filename: str):
    if filename not in {"hardware_validation.jsonl", "hardware_validation_report.md"}:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "VALIDATION_FILE_NOT_FOUND",
                "message": "The requested validation evidence file is not available.",
                "suggestion": "Download hardware_validation.jsonl or hardware_validation_report.md.",
            },
        )
    paths = ensure_validation_artifacts(request.app.state.settings.workspace)
    path = paths["jsonl"] if filename.endswith(".jsonl") else paths["report"]
    return FileResponse(path, filename=filename, media_type="text/markdown" if filename.endswith(".md") else "application/jsonl")


@router.post("/validation")
def save_validation_record(
    request: Request,
    gate: str = Form(...),
    status: str = Form(...),
    operator: str = Form(""),
    session_id: str = Form(""),
    run_id: str = Form(""),
    helper_url: str = Form(""),
    evidence: str = Form(""),
    notes: str = Form(""),
):
    try:
        record_lab_validation(
            request.app.state.settings.workspace,
            gate=gate,
            status=status,
            operator=operator,
            session_id=session_id,
            run_id=run_id,
            helper_url=helper_url,
            evidence=evidence,
            notes=notes,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "INVALID_VALIDATION_RECORD",
                "message": str(exc),
                "suggestion": "Choose one of the listed validation gates and pass/not-applicable/warn/fail statuses.",
            },
        ) from exc
    return RedirectResponse("/ops#hardware-validation", status_code=303)


@router.post("/shutdown")
def shutdown_console(request: Request):
    settings = request.app.state.settings
    if not settings.allow_web_shutdown:
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": "WEB_SHUTDOWN_DISABLED",
                "message": "Web shutdown is disabled for this console process.",
                "suggestion": "Stop the console with scripts/console_control.py stop, or start with MICLOAKER_ALLOW_WEB_SHUTDOWN=1 for lab-only controlled shutdown.",
            },
        )
    active = recording_status()
    if active["active"]:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "RECORDING_ACTIVE",
                "message": "The console will not shut down while a recording is active.",
                "suggestion": "Wait for recording/finalization to finish, then retry shutdown.",
            },
        )
    append_app_event(settings.workspace, "web_shutdown_requested", host=settings.host, port=settings.port)
    threading.Timer(0.25, _signal_self).start()
    return RedirectResponse("/ops?shutdown=requested", status_code=303)


def _signal_self() -> None:
    os.kill(os.getpid(), signal.SIGINT)
