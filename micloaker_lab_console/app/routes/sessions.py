from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from ..services.text_store import read_json, session_dir
from ..services.metadata import create_session, load_runs, load_sessions, rebuild_indexes

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("")
def list_sessions(request: Request):
    workspace = request.app.state.settings.workspace
    sessions = []
    for session in load_sessions(workspace):
        runs = load_runs(workspace, session["session_id"])
        comparisons = list((session_dir(workspace, session["session_id"]) / "comparisons").glob("*.json"))
        session["run_count"] = len(runs)
        session["analyzed_count"] = sum(1 for run in runs if run.get("analysis", {}).get("status") == "finalized")
        session["comparison_count"] = len(comparisons)
        sessions.append(session)
    rebuild_status = None
    if request.query_params.get("rebuilt") == "1":
        rebuild_status = {
            "sessions": request.query_params.get("sessions", "0"),
            "runs": request.query_params.get("runs", "0"),
            "comparisons": request.query_params.get("comparisons", "0"),
        }
    return request.app.state.templates.TemplateResponse(
        name="sessions.html",
        request=request,
        context={"sessions": sessions, "rebuild_status": rebuild_status},
    )


@router.post("")
def new_session(request: Request, title: str = Form(...), notes: str = Form("")):
    session = create_session(request.app.state.settings.workspace, title, notes)
    return RedirectResponse(f"/sessions/{session['session_id']}", status_code=303)


@router.get("/{session_id}")
def session_detail(request: Request, session_id: str):
    workspace = request.app.state.settings.workspace
    _require_session(workspace, session_id)
    base = session_dir(workspace, session_id)
    session = read_json(base / "session.json")
    all_runs = load_runs(workspace, session_id)
    filters = {
        "date": request.query_params.get("date", "").strip(),
        "carrier_freq_khz": request.query_params.get("carrier_freq_khz", "").strip(),
        "uj": request.query_params.get("uj", "").strip(),
        "sound_condition": request.query_params.get("sound_condition", "").strip(),
        "mic_id": request.query_params.get("mic_id", "").strip(),
        "room": request.query_params.get("room", "").strip(),
        "analysis_status": request.query_params.get("analysis_status", "").strip(),
    }
    runs = [run for run in all_runs if _run_matches_filters(run, filters)]
    comparisons = list((base / "comparisons").glob("*.json"))
    summary_files = {
        "summary_csv": (base / "summary.csv").is_file(),
        "session_report": (base / "session_report.md").is_file(),
    }
    return request.app.state.templates.TemplateResponse(
        name="session_detail.html",
        request=request,
        context={
            "session_id": session_id,
            "session": session,
            "runs": runs,
            "run_count": len(all_runs),
            "finalized_count": sum(1 for run in all_runs if run.get("analysis", {}).get("status") == "finalized"),
            "comparison_count": len(comparisons),
            "summary_files": summary_files,
            "filters": filters,
        },
    )


@router.post("/rebuild-index")
def rebuild(request: Request):
    counts = rebuild_indexes(request.app.state.settings.workspace)
    return RedirectResponse(
        f"/sessions?rebuilt=1&sessions={counts['sessions']}&runs={counts['runs']}&comparisons={counts['comparisons']}",
        status_code=303,
    )


def _run_matches_filters(run: dict, filters: dict[str, str]) -> bool:
    condition = run.get("condition", {})
    analysis = run.get("analysis", {})
    if filters["date"] and filters["date"] not in run.get("created_at", ""):
        return False
    if filters["carrier_freq_khz"]:
        try:
            if float(condition.get("carrier_freq_khz")) != float(filters["carrier_freq_khz"]):
                return False
        except (TypeError, ValueError):
            return False
    for key in ["uj", "sound_condition", "mic_id", "room"]:
        if filters[key] and filters[key].lower() not in str(condition.get(key, "")).lower():
            return False
    if filters["analysis_status"] and filters["analysis_status"] != analysis.get("status"):
        return False
    return True


def _require_session(workspace, session_id: str) -> None:
    if not (session_dir(workspace, session_id) / "session.json").is_file():
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "SESSION_NOT_FOUND",
                "message": f"Session {session_id} was not found.",
                "suggestion": "Open the Sessions page and choose an existing session.",
            },
        )
