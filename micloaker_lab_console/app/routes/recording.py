from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from ..services.daq import DaqNotConfiguredError, DaqUnavailableError, daq_health
from ..services.metadata import load_run
from ..services.recorder import RecordingBusyError, record_daq_and_finalize, record_mock_and_finalize, recording_status
from ..services.text_store import safe_name, session_dir

router = APIRouter(tags=["recording"])


@router.post("/sessions/{session_id}/runs/{run_id}/record-mock")
def record_mock(request: Request, session_id: str, run_id: str):
    workspace = request.app.state.settings.workspace
    _require_run(workspace, session_id, run_id)
    run = load_run(workspace, session_id, run_id)
    try:
        record_mock_and_finalize(workspace, run)
    except RecordingBusyError as exc:
        raise HTTPException(status_code=409, detail=_recording_busy_error(str(exc))) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=_raw_bin_exists_error(str(exc))) from exc
    return RedirectResponse(f"/sessions/{session_id}/runs/{run_id}", status_code=303)


@router.post("/sessions/{session_id}/runs/{run_id}/record-daq")
def record_daq(request: Request, session_id: str, run_id: str):
    workspace = request.app.state.settings.workspace
    _require_run(workspace, session_id, run_id)
    run = load_run(workspace, session_id, run_id)
    try:
        record_daq_and_finalize(workspace, run)
    except RecordingBusyError as exc:
        raise HTTPException(status_code=409, detail=_recording_busy_error(str(exc))) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=_raw_bin_exists_error(str(exc))) from exc
    except DaqUnavailableError as exc:
        raise HTTPException(status_code=503, detail={"error_code": "DAQ_UNAVAILABLE", "message": str(exc), "suggestion": "Use mock mode or install/configure uldaq drivers."}) from exc
    except DaqNotConfiguredError as exc:
        raise HTTPException(status_code=501, detail={"error_code": "DAQ_NOT_CONFIGURED", "message": str(exc), "suggestion": "Configure the DAQ-specific acquisition code for this hardware."}) from exc
    return RedirectResponse(f"/sessions/{session_id}/runs/{run_id}", status_code=303)


@router.get("/recording/status")
def status():
    return recording_status()


@router.get("/daq/health")
def health():
    return daq_health()


def _raw_bin_exists_error(message: str) -> dict[str, str]:
    return {
        "error_code": "RAW_BIN_EXISTS",
        "message": message,
        "suggestion": "Raw .bin files are never overwritten silently. Create a new run for a new recording; use the explicit overwrite checkbox only for derived WAV/plot/metric regeneration.",
    }


def _recording_busy_error(message: str) -> dict[str, str]:
    return {
        "error_code": "RECORDING_BUSY",
        "message": message,
        "suggestion": "Wait for the active recording job to finish before starting another recording.",
    }


def _require_run(workspace, session_id: str, run_id: str) -> None:
    base = session_dir(workspace, session_id)
    if not (base / "session.json").is_file():
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "SESSION_NOT_FOUND",
                "message": f"Session {session_id} was not found.",
                "suggestion": "Open the Sessions page and choose an existing session before recording.",
            },
        )
    if not (base / "metadata" / f"{safe_name(run_id)}.json").is_file():
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "RUN_NOT_FOUND",
                "message": f"Run {run_id} was not found in session {session_id}.",
                "suggestion": "Open the session page and choose an existing run before recording.",
            },
        )
