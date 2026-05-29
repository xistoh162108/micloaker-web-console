from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from ..services.converter import convert_run_bin
from ..services.jobs import run_job
from ..services.metadata import load_run, save_run
from ..services.raw_bin import RawBinValidationError
from ..services.text_store import safe_name, session_dir

router = APIRouter(tags=["conversion"])


@router.post("/sessions/{session_id}/runs/{run_id}/convert")
def convert(request: Request, session_id: str, run_id: str, overwrite_existing: bool = Form(False)):
    workspace = request.app.state.settings.workspace
    _require_run(workspace, session_id, run_id)
    run = load_run(workspace, session_id, run_id)
    base = session_dir(workspace, session_id)
    log_path = base / "logs" / f"{run_id}.log"

    def _work() -> dict:
        run["files"].update(convert_run_bin(run, base, overwrite=overwrite_existing))
        save_run(workspace, run)
        return run

    try:
        run_job(workspace, "manual_convert_wav", log_path, _work)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=_raw_bin_missing_error(run_id, str(exc))) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail={"error_code": "DERIVED_OUTPUT_EXISTS", "message": str(exc), "suggestion": "Enable overwrite existing derived outputs, or keep the existing WAVs."}) from exc
    except RawBinValidationError as exc:
        raise HTTPException(status_code=400, detail=_invalid_raw_bin_error(run_id, str(exc))) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error_code": "INVALID_CONVERSION_CONFIG", "message": str(exc), "suggestion": "Set a positive full-scale voltage or choose peak-only WAV conversion."}) from exc
    return RedirectResponse(f"/sessions/{session_id}/runs/{run_id}", status_code=303)


def _raw_bin_missing_error(run_id: str, message: str) -> dict[str, str]:
    return {
        "error_code": "RAW_BIN_MISSING",
        "message": f"Raw .bin for run {run_id} is missing: {message}",
        "suggestion": "Record the run or import a raw float64 .bin before converting WAVs.",
    }


def _invalid_raw_bin_error(run_id: str, message: str) -> dict[str, str]:
    return {
        "error_code": "RAW_BIN_INVALID",
        "message": f"Raw .bin for run {run_id} is invalid: {message}",
        "suggestion": "Replace the saved raw file with a non-empty little-endian float64 voltage .bin before converting WAVs.",
    }


def _require_run(workspace, session_id: str, run_id: str) -> None:
    base = session_dir(workspace, session_id)
    if not (base / "session.json").is_file():
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "SESSION_NOT_FOUND",
                "message": f"Session {session_id} was not found.",
                "suggestion": "Open the Sessions page and choose an existing session before converting WAVs.",
            },
        )
    if not (base / "metadata" / f"{safe_name(run_id)}.json").is_file():
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "RUN_NOT_FOUND",
                "message": f"Run {run_id} was not found in session {session_id}.",
                "suggestion": "Open the session page and choose an existing run before converting WAVs.",
            },
        )
