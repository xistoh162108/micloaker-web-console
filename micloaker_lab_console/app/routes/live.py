from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request

from ..services.live_monitor import live_monitor, preview_contract
from ..services.metadata import load_runs, load_sessions
from ..services.recorder import recording_status
from ..services.text_store import read_jsonl

router = APIRouter(prefix="/live", tags=["live"])


@router.get("")
def live_page(request: Request):
    return request.app.state.templates.TemplateResponse(name="live.html", request=request, context={})


@router.post("/start")
def live_start(
    request: Request,
    source: str = Form("mock"),
    sample_rate_hz: int = Form(8000),
    channel: int = Form(0),
    input_mode: str = Form("SINGLE_ENDED"),
    ai_range: str = Form("BIP10VOLTS"),
):
    try:
        live_monitor.start(
            source=source,
            sample_rate_hz=sample_rate_hz,
            channel=channel,
            input_mode=input_mode,
            ai_range=ai_range,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "INVALID_LIVE_SOURCE",
                "message": str(exc),
                "suggestion": "Choose mock for DAQ-free preview or daq for a short real DAQ preview scan.",
            },
        ) from exc
    return _snapshot(request)


@router.post("/stop")
def live_stop(request: Request):
    live_monitor.stop()
    return _snapshot(request)


@router.get("/snapshot")
def live_snapshot(request: Request):
    return _snapshot(request)


def _snapshot(request: Request) -> dict:
    try:
        data = live_monitor.snapshot()
    except RuntimeError as exc:
        data = {
            "running": live_monitor.running,
            "preview_only": True,
            "result_grade": "preview",
            "preview_source": live_monitor.source,
            **preview_contract(),
            "sample_rate_hz": live_monitor.sample_rate_hz,
            "preview_label": "Preview only. Final metrics will be recomputed from saved .bin after recording.",
            "preview_error": str(exc),
            "preview_error_code": "LIVE_PREVIEW_UNAVAILABLE",
            "waveform_point_count": 0,
            "psd_bin_count": 0,
            "spectrogram_row_count": len(live_monitor.spectrogram_rows),
            "clipping": False,
        }
    active = recording_status()
    if active["active"]:
        state = "Recording"
        finalization_status = "Final metrics pending until recording finishes."
    elif finalizing_job := _running_finalization_job(request):
        state = "Finalizing"
        finalization_status = f"Finalization job {finalizing_job['job_id']} is running; final metrics will be report-grade after saved .bin recomputation finishes."
        data["finalization_job"] = finalizing_job
    elif data.get("running"):
        state = "Previewing"
        if data.get("preview_error"):
            finalization_status = f"Live preview unavailable: {data['preview_error']}"
        else:
            finalization_status = "No active recording. Preview data is not saved."
    elif latest := _latest_terminal_finalization(request):
        analysis = latest.get("analysis", {})
        if analysis.get("status") == "finalized":
            state = "Finalized"
            finalization_status = f"Latest finalized run {latest['run_id']} is report-grade from saved .bin."
            recording = latest.get("recording", {})
            files = latest.get("files", {})
            data.update({
                "final_run_id": latest["run_id"],
                "final_session_id": latest["session_id"],
                "finalized_at": analysis.get("finalized_at"),
                "final_bin_path": files.get("bin"),
                "final_metrics_path": analysis.get("metrics_path"),
                "final_log_path": f"logs/{latest['run_id']}.log",
                "final_wav_peak_path": files.get("wav_peak"),
                "final_wav_range_path": files.get("wav_range"),
                "final_plot_paths": {
                    "waveform_png": files.get("waveform_png"),
                    "waveform_svg": files.get("waveform_svg"),
                    "psd_png": files.get("psd_png"),
                    "psd_svg": files.get("psd_svg"),
                    "spectrogram_png": files.get("spectrogram_png"),
                    "spectrogram_svg": files.get("spectrogram_svg"),
                },
                "final_result_grade": analysis.get("result_grade"),
                "finalized_from_saved_bin": analysis.get("finalized_from_saved_bin") is True,
                "final_raw_sample_count": recording.get("raw_sample_count") or recording.get("written_samples"),
                "final_raw_size_bytes": recording.get("raw_size_bytes"),
                "final_raw_dtype": recording.get("raw_dtype") or recording.get("dtype"),
            })
        else:
            state = "Stopped"
            finalization_status = f"Latest finalization failed for run {latest['run_id']}; inspect {analysis.get('error_log', 'the run log')} and retry from saved .bin."
            data.update({
                "failed_run_id": latest["run_id"],
                "failed_session_id": latest["session_id"],
                "failed_at": analysis.get("failed_at"),
                "finalization_error": analysis.get("last_error"),
                "finalization_error_log": analysis.get("error_log"),
            })
    else:
        state = "Stopped"
        finalization_status = "Start recording from a run page; finalization reloads the saved .bin after recording."
    data.update({
        "recording_state": state,
        "finalization_status": finalization_status,
        "active_recording": active["recording"],
        "log_tail": _live_log_tail(request),
        "state_options": ["Stopped", "Previewing", "Recording", "Finalizing", "Finalized"],
    })
    return data


def _latest_terminal_finalization(request: Request) -> dict | None:
    workspace = request.app.state.settings.workspace
    terminal = []
    for session in load_sessions(workspace):
        for run in load_runs(workspace, session["session_id"]):
            analysis = run.get("analysis", {})
            if analysis.get("status") == "finalized" and analysis.get("finalized_from_saved_bin") is True:
                terminal.append(run)
            elif analysis.get("status") == "failed":
                terminal.append(run)
    if not terminal:
        return None
    return sorted(terminal, key=_terminal_finalization_time, reverse=True)[0]


def _terminal_finalization_time(run: dict) -> str:
    analysis = run.get("analysis", {})
    return analysis.get("finalized_at") or analysis.get("failed_at") or run.get("created_at", "")


def _running_finalization_job(request: Request) -> dict | None:
    workspace = request.app.state.settings.workspace
    terminal: set[str] = set()
    started: dict[str, dict] = {}
    for row in read_jsonl(workspace / ".micloaker" / "jobs.jsonl"):
        job_id = row.get("job_id")
        if not job_id:
            continue
        if row.get("event") == "job_started":
            started[job_id] = row
        if row.get("event") in {"job_finished", "job_failed", "job_interrupted"}:
            terminal.add(job_id)
    for job_id, row in sorted(started.items(), key=lambda item: item[1].get("started_at") or item[1].get("ts") or "", reverse=True):
        job_type = row.get("type") or row.get("name", "")
        if job_id not in terminal and "finalize" in job_type:
            return {
                "job_id": job_id,
                "type": job_type,
                "started_at": row.get("started_at") or row.get("ts"),
                "logs": row.get("logs", ""),
            }
    return None


def _live_log_tail(request: Request, *, max_lines: int = 20) -> list[str]:
    workspace = request.app.state.settings.workspace
    lines: list[str] = []
    for path in [workspace / ".micloaker" / "app.log", workspace / ".micloaker" / "jobs.jsonl"]:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace").splitlines()
        lines.extend(f"{path.name}: {line}" for line in text[-max_lines:])
    return lines[-max_lines:]
