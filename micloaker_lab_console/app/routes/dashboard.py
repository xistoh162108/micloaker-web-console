from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

from ..services.daq import daq_health
from ..services.mac_helper_client import MacHelperClient
from ..services.metadata import load_runs, load_sessions
from ..services.recorder import recording_status
from ..services.text_store import read_json, read_json_or_default, session_dir

router = APIRouter()


@router.get("/")
def dashboard(request: Request):
    workspace = request.app.state.settings.workspace
    sessions = load_sessions(workspace)
    active_session = sessions[0] if sessions else None
    all_runs = [run for session in sessions for run in load_runs(workspace, session["session_id"])]
    last_run = max(all_runs, key=lambda run: run.get("created_at", ""), default=None)
    last_comparison = _last_comparison(workspace, sessions)
    finalized_count = sum(1 for run in all_runs if run.get("analysis", {}).get("status") == "finalized")
    failed_count = sum(1 for run in all_runs if run.get("analysis", {}).get("status") == "failed")
    recent_runs = sorted(all_runs, key=lambda run: run.get("created_at", ""), reverse=True)[:6]
    config = read_json_or_default(workspace / ".micloaker" / "config.json", {"mac_helper_url": "", "mac_helper_token": ""})
    mac_status = MacHelperClient(config.get("mac_helper_url", ""), config.get("mac_helper_token", "")).health()
    daq_status = daq_health()
    return request.app.state.templates.TemplateResponse(
        name="dashboard.html",
        request=request,
        context={
            "workspace": workspace,
            "sessions": sessions[:8],
            "active_session": active_session,
            "last_run": last_run,
            "last_comparison": last_comparison,
            "recent_runs": recent_runs,
            "stats": {
                "session_count": len(sessions),
                "run_count": len(all_runs),
                "finalized_count": finalized_count,
                "failed_count": failed_count,
            },
            "mac_status": mac_status,
            "daq_status": daq_status,
            "recording_status": recording_status(),
        },
    )


def _last_comparison(workspace: Path, sessions: list[dict[str, Any]]) -> dict[str, Any] | None:
    newest: tuple[str, dict[str, Any]] | None = None
    for session in sessions:
        base = session_dir(workspace, session["session_id"])
        for path in (base / "comparisons").glob("*.json"):
            data = read_json_or_default(path, {})
            if not data:
                continue
            stamp = data.get("created_at") or path.stat().st_mtime_ns
            data["session_id"] = session["session_id"]
            data["json_file"] = f"comparisons/{path.name}"
            if newest is None or str(stamp) > str(newest[0]):
                newest = (str(stamp), data)
    return newest[1] if newest else None
