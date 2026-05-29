from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request

from ..services.metadata import load_sessions
from ..services.text_store import session_dir

router = APIRouter(prefix="/files", tags=["files"])


@router.get("")
def files_page(request: Request):
    workspace = request.app.state.settings.workspace
    files = []
    for session in load_sessions(workspace):
        session_id = session["session_id"]
        base = session_dir(workspace, session_id)
        for path in sorted(base.glob("**/*")):
            if path.is_file() and _path_inside(base, path):
                try:
                    size_bytes = path.stat().st_size
                except OSError:
                    continue
                rel = str(path.relative_to(base))
                files.append({
                    "session_id": session_id,
                    "path": rel,
                    "size_bytes": size_bytes,
                    "download_url": f"/sessions/{session_id}/files/{rel}",
                    **_file_role(rel),
                })
    return request.app.state.templates.TemplateResponse(
        name="files.html",
        request=request,
        context={"files": files},
    )


def _path_inside(base: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
    except ValueError:
        return False
    return True


def _file_role(path: str) -> dict[str, str | bool]:
    lower = path.lower()
    if lower.endswith("__scale-peak.wav"):
        return {"kind": "Peak WAV", "role": "Listening preview only", "is_audio": True}
    if lower.endswith(".wav") and "__scale-range" in lower:
        return {"kind": "Range WAV", "role": "Scale-valid cross-check if full-scale voltage is correct", "is_audio": True}
    if lower.endswith(".wav"):
        return {"kind": "WAV", "role": "Audio preview", "is_audio": True}
    if lower.endswith(".bin"):
        return {"kind": "Raw BIN", "role": "Primary quantitative data", "is_audio": False}
    if lower.endswith("_metrics.json"):
        return {"kind": "Metrics JSON", "role": "Report-grade metrics", "is_audio": False}
    if lower.endswith("_metrics.csv"):
        return {"kind": "Metrics CSV", "role": "Tabular metrics export", "is_audio": False}
    if lower.endswith((".png", ".svg")):
        return {"kind": Path(path).suffix.lstrip(".").upper(), "role": "Report plot", "is_audio": False}
    if lower.endswith(".log"):
        return {"kind": "Log", "role": "Job log and traceback text", "is_audio": False}
    return {"kind": Path(path).suffix.lstrip(".").upper() or "file", "role": "Artifact", "is_audio": False}
