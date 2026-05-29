from __future__ import annotations

import os
import signal
import threading

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from ..services.readiness import lab_readiness
from ..services.recorder import recording_status
from ..services.text_store import append_app_event

router = APIRouter(prefix="/ops", tags=["ops"])


@router.get("")
def ops_page(request: Request):
    settings = request.app.state.settings
    readiness = lab_readiness(settings)
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
        },
    )


@router.get("/readiness")
def readiness_status(request: Request):
    return lab_readiness(request.app.state.settings)


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
