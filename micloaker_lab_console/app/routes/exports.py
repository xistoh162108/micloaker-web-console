from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from ..services.export_zip import make_multi_session_zip, make_ops_validation_zip, make_run_zip, make_session_zip
from ..services.readiness import write_readiness_artifacts
from ..services.text_store import safe_name, session_dir

router = APIRouter(prefix="/exports", tags=["exports"])


@router.get("/sessions/{session_id}.zip")
def session_zip(request: Request, session_id: str):
    workspace = request.app.state.settings.workspace
    _require_session(workspace, session_id)
    path = workspace / "uploads" / f"{safe_name(session_id)}.zip"
    path = make_session_zip(workspace, session_id, path)
    return FileResponse(path, filename=path.name)


@router.get("/multi-session.zip")
def multi_session_zip(request: Request, session_ids: list[str] | None = Query(None)):
    workspace = request.app.state.settings.workspace
    if not session_ids:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "NO_SESSIONS_SELECTED",
                "message": "No sessions were selected for multi-session export.",
                "suggestion": "Select one or more sessions on the Sessions page before downloading a multi-session ZIP.",
            },
        )
    for session_id in session_ids:
        _require_session(workspace, session_id)
    zip_name = "multi_session.zip"
    path = workspace / "uploads" / zip_name
    path = make_multi_session_zip(workspace, session_ids, path)
    return FileResponse(path, filename=path.name)


@router.get("/ops-validation.zip")
def ops_validation_zip(request: Request):
    workspace = request.app.state.settings.workspace
    write_readiness_artifacts(request.app.state.settings)
    path = workspace / "uploads" / "ops_validation.zip"
    path = make_ops_validation_zip(workspace, path)
    return FileResponse(path, filename=path.name)


@router.get("/sessions/{session_id}/runs/{run_id}.zip")
def run_zip(request: Request, session_id: str, run_id: str):
    workspace = request.app.state.settings.workspace
    _require_session(workspace, session_id)
    _require_run(workspace, session_id, run_id)
    path = workspace / "uploads" / f"{safe_name(run_id)}.zip"
    path = make_run_zip(workspace, session_id, run_id, path)
    return FileResponse(path, filename=path.name)


def _require_session(workspace, session_id: str) -> None:
    if not (session_dir(workspace, session_id) / "session.json").is_file():
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "SESSION_NOT_FOUND",
                "message": f"Session {session_id} was not found.",
                "suggestion": "Open the Sessions page and choose an existing session before exporting.",
            },
        )


def _require_run(workspace, session_id: str, run_id: str) -> None:
    if not (session_dir(workspace, session_id) / "metadata" / f"{safe_name(run_id)}.json").is_file():
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "RUN_NOT_FOUND",
                "message": f"Run {run_id} was not found in session {session_id}.",
                "suggestion": "Open the session page and choose an existing run before exporting.",
            },
        )
