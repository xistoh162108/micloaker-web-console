from __future__ import annotations

import math
from pathlib import Path
import tempfile

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse

from ..services.daq import DaqNotConfiguredError, DaqUnavailableError, daq_health
from ..services.metadata import create_run_metadata, load_run, load_runs, load_sessions
from ..services.recorder import RecordingBusyError, import_bin_and_finalize, record_daq_and_finalize, record_mock_and_finalize, validate_raw_bin_source
from ..services.text_store import read_json, read_json_or_default, safe_name, session_dir

router = APIRouter(tags=["runs"])


@router.get("/runs/new")
def new_run_page(request: Request):
    workspace = request.app.state.settings.workspace
    sessions = []
    for session in load_sessions(workspace):
        runs = load_runs(workspace, session["session_id"])
        sessions.append({**session, "run_count": len(runs)})
    selected_session_id = request.query_params.get("session_id", "").strip()
    if selected_session_id and not any(session["session_id"] == selected_session_id for session in sessions):
        selected_session_id = ""
    if not selected_session_id and sessions:
        selected_session_id = sessions[0]["session_id"]
    return request.app.state.templates.TemplateResponse(
        name="new_run.html",
        request=request,
        context={"sessions": sessions, "selected_session_id": selected_session_id},
    )


@router.post("/sessions/{session_id}/runs")
def create_run(
    request: Request,
    session_id: str,
    carrier_freq_khz: float = Form(25.0),
    uj: str = Form("uj0"),
    sound_condition: str = Form("sound0"),
    mic_id: str = Form("mock_ch0"),
    room: str = Form("lab"),
    distance_cm: float | None = Form(None),
    angle_deg: float = Form(0.0),
    ai_range: str = Form("BIP10VOLTS"),
    input_mode: str = Form("SINGLE_ENDED"),
    channel: int = Form(0),
    full_scale_volts: float = Form(10.0),
    scale_mode: str = Form("both"),
    remove_dc: bool = Form(True),
    sample_rate_hz: int = Form(8000),
    duration_s: float = Form(1.0),
    trim_start_s: float = Form(0.0),
    trim_end_s: float = Form(0.0),
    analysis_band_low_hz: float = Form(300.0),
    analysis_band_high_hz: float = Form(3400.0),
    safety_operator: str = Form(""),
    safety_max_spl_db: float | None = Form(None),
    safety_notes: str = Form(""),
    mac_helper_file: str = Form(""),
    mac_helper_device_id: int | None = Form(None),
    mac_helper_sample_rate: int | None = Form(None),
    mac_helper_channels: int = Form(1),
    mac_helper_gain: float = Form(1.0),
    mac_helper_delay_ms: int = Form(500),
    record_after_create: bool = Form(False),
    record_after_create_source: str = Form(""),
    notes: str = Form(""),
):
    workspace = request.app.state.settings.workspace
    _require_session(workspace, session_id)
    record_source = _record_after_create_source(record_after_create, record_after_create_source)
    _validate_run_form(
        carrier_freq_khz=carrier_freq_khz,
        sample_rate_hz=sample_rate_hz,
        duration_s=duration_s,
        trim_start_s=trim_start_s,
        trim_end_s=trim_end_s,
        analysis_band_low_hz=analysis_band_low_hz,
        analysis_band_high_hz=analysis_band_high_hz,
        full_scale_volts=full_scale_volts,
        scale_mode=scale_mode,
        channel=channel,
        distance_cm=distance_cm,
        safety_max_spl_db=safety_max_spl_db,
        mac_helper_device_id=mac_helper_device_id,
        mac_helper_sample_rate=mac_helper_sample_rate,
        mac_helper_channels=mac_helper_channels,
        mac_helper_gain=mac_helper_gain,
        mac_helper_delay_ms=mac_helper_delay_ms,
        allow_zero_duration=False,
    )
    run = create_run_metadata(
        workspace,
        session_id,
        carrier_freq_khz=carrier_freq_khz,
        uj=uj,
        sound_condition=sound_condition,
        mic_id=mic_id,
        room=room,
        distance_cm=distance_cm,
        angle_deg=angle_deg,
        ai_range=ai_range,
        input_mode=input_mode,
        channel=channel,
        full_scale_volts=full_scale_volts,
        scale_mode=scale_mode,
        remove_dc=remove_dc,
        source=record_source if record_source in {"mock", "daq"} else "mock",
        sample_rate_hz=sample_rate_hz,
        duration_s=duration_s,
        trim_start_s=trim_start_s,
        trim_end_s=trim_end_s,
        analysis_band_low_hz=analysis_band_low_hz,
        analysis_band_high_hz=analysis_band_high_hz,
        safety_operator=safety_operator,
        safety_max_spl_db=safety_max_spl_db,
        safety_notes=safety_notes,
        mac_helper_file=mac_helper_file.strip(),
        mac_helper_device_id=mac_helper_device_id,
        mac_helper_sample_rate=mac_helper_sample_rate,
        mac_helper_channels=mac_helper_channels,
        mac_helper_gain=mac_helper_gain,
        mac_helper_delay_ms=mac_helper_delay_ms,
        notes=notes,
    )
    if record_source:
        try:
            if record_source == "daq":
                record_daq_and_finalize(workspace, run)
            else:
                record_mock_and_finalize(workspace, run)
        except RecordingBusyError as exc:
            raise HTTPException(status_code=409, detail=_recording_busy_error(str(exc))) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=_raw_bin_exists_error(str(exc))) from exc
        except DaqUnavailableError as exc:
            raise HTTPException(status_code=503, detail=_daq_unavailable_error(str(exc))) from exc
        except DaqNotConfiguredError as exc:
            raise HTTPException(status_code=501, detail=_daq_not_configured_error(str(exc))) from exc
    return RedirectResponse(f"/sessions/{session_id}/runs/{run['run_id']}", status_code=303)


@router.post("/sessions/{session_id}/runs/upload-bin")
async def upload_bin_run(
    request: Request,
    session_id: str,
    file: UploadFile = File(...),
    carrier_freq_khz: float = Form(25.0),
    uj: str = Form("uj0"),
    sound_condition: str = Form("sound0"),
    mic_id: str = Form("upload_ch0"),
    room: str = Form("lab"),
    distance_cm: float | None = Form(None),
    angle_deg: float = Form(0.0),
    ai_range: str = Form("BIP10VOLTS"),
    input_mode: str = Form("SINGLE_ENDED"),
    channel: int = Form(0),
    full_scale_volts: float = Form(10.0),
    scale_mode: str = Form("both"),
    remove_dc: bool = Form(True),
    sample_rate_hz: int = Form(8000),
    duration_s: float = Form(0.0),
    trim_start_s: float = Form(0.0),
    trim_end_s: float = Form(0.0),
    analysis_band_low_hz: float = Form(300.0),
    analysis_band_high_hz: float = Form(3400.0),
    safety_operator: str = Form(""),
    safety_max_spl_db: float | None = Form(None),
    safety_notes: str = Form(""),
    mac_helper_file: str = Form(""),
    mac_helper_device_id: int | None = Form(None),
    mac_helper_sample_rate: int | None = Form(None),
    mac_helper_channels: int = Form(1),
    mac_helper_gain: float = Form(1.0),
    mac_helper_delay_ms: int = Form(500),
    notes: str = Form(""),
):
    workspace = request.app.state.settings.workspace
    _require_session(workspace, session_id)
    if not file.filename or not file.filename.lower().endswith(".bin"):
        raise HTTPException(status_code=400, detail=_invalid_raw_bin_error("uploaded raw data must use a .bin extension"))
    _validate_run_form(
        carrier_freq_khz=carrier_freq_khz,
        sample_rate_hz=sample_rate_hz,
        duration_s=duration_s,
        trim_start_s=trim_start_s,
        trim_end_s=trim_end_s,
        analysis_band_low_hz=analysis_band_low_hz,
        analysis_band_high_hz=analysis_band_high_hz,
        full_scale_volts=full_scale_volts,
        scale_mode=scale_mode,
        channel=channel,
        distance_cm=distance_cm,
        safety_max_spl_db=safety_max_spl_db,
        mac_helper_device_id=mac_helper_device_id,
        mac_helper_sample_rate=mac_helper_sample_rate,
        mac_helper_channels=mac_helper_channels,
        mac_helper_gain=mac_helper_gain,
        mac_helper_delay_ms=mac_helper_delay_ms,
        allow_zero_duration=True,
    )
    with tempfile.NamedTemporaryFile(prefix="micloaker_upload_", suffix=".bin", delete=False) as tmp:
        tmp_path = Path(tmp.name)
        while chunk := await file.read(1024 * 1024):
            tmp.write(chunk)
    try:
        try:
            validate_raw_bin_source(tmp_path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=_invalid_raw_bin_error(str(exc))) from exc
        run = create_run_metadata(
            workspace,
            session_id,
            carrier_freq_khz=carrier_freq_khz,
            uj=uj,
            sound_condition=sound_condition,
            mic_id=mic_id,
            room=room,
            distance_cm=distance_cm,
            angle_deg=angle_deg,
            ai_range=ai_range,
            input_mode=input_mode,
            channel=channel,
            full_scale_volts=full_scale_volts,
            scale_mode=scale_mode,
            remove_dc=remove_dc,
            sample_rate_hz=sample_rate_hz,
            duration_s=duration_s,
            trim_start_s=trim_start_s,
            trim_end_s=trim_end_s,
            analysis_band_low_hz=analysis_band_low_hz,
            analysis_band_high_hz=analysis_band_high_hz,
            safety_operator=safety_operator,
            safety_max_spl_db=safety_max_spl_db,
            safety_notes=safety_notes,
            mac_helper_file=mac_helper_file.strip(),
            mac_helper_device_id=mac_helper_device_id,
            mac_helper_sample_rate=mac_helper_sample_rate,
            mac_helper_channels=mac_helper_channels,
            mac_helper_gain=mac_helper_gain,
            mac_helper_delay_ms=mac_helper_delay_ms,
            source="upload",
            notes=notes,
        )
        import_bin_and_finalize(workspace, run, tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)
    return RedirectResponse(f"/sessions/{session_id}/runs/{run['run_id']}", status_code=303)


@router.get("/sessions/{session_id}/runs/{run_id}")
def run_detail(request: Request, session_id: str, run_id: str):
    workspace = request.app.state.settings.workspace
    _require_run(workspace, session_id, run_id)
    run = load_run(workspace, session_id, run_id)
    base = session_dir(workspace, session_id)
    metrics = {}
    metrics_path = base / run["files"].get("metrics_json", "")
    if metrics_path.exists():
        metrics = read_json_or_default(metrics_path, {})
    log_path = base / "logs" / f"{run_id}.log"
    log_text = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    files = sorted(str(p.relative_to(base)) for p in base.glob("**/*") if p.is_file() and _path_inside(base, p) and run_id in p.name)
    file_set = set(files)
    return request.app.state.templates.TemplateResponse(
        name="run_detail.html",
        request=request,
        context={
            "session_id": session_id,
            "run": run,
            "metrics": metrics,
            "files": files,
            "file_set": file_set,
            "artifacts": _run_artifacts(run, file_set),
            "log_text": log_text,
            "daq_status": daq_health(),
        },
    )


@router.get("/sessions/{session_id}/browser")
def file_browser(request: Request, session_id: str):
    workspace = request.app.state.settings.workspace
    _require_session(workspace, session_id)
    base = session_dir(workspace, session_id).resolve()
    files = []
    for path in sorted(base.glob("**/*")):
        if path.is_file() and _path_inside(base, path):
            try:
                size_bytes = path.stat().st_size
            except OSError:
                continue
            rel = str(path.relative_to(base))
            files.append(_file_browser_row(rel, size_bytes))
    return request.app.state.templates.TemplateResponse(
        name="file_browser.html",
        request=request,
        context={"session_id": session_id, "files": files},
    )


@router.get("/sessions/{session_id}/files/{file_path:path}")
def session_file(request: Request, session_id: str, file_path: str, download: bool = Query(False)):
    workspace = request.app.state.settings.workspace
    _require_session(workspace, session_id)
    base = session_dir(workspace, session_id).resolve()
    path = (base / file_path).resolve()
    try:
        path.relative_to(base)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=_file_not_found_error(file_path, session_id)) from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail=_file_not_found_error(file_path, session_id))
    disposition = "attachment" if download else "inline"
    return FileResponse(path, filename=path.name, content_disposition_type=disposition)


def _validate_run_form(
    *,
    carrier_freq_khz: float,
    sample_rate_hz: int,
    duration_s: float,
    trim_start_s: float,
    trim_end_s: float,
    analysis_band_low_hz: float,
    analysis_band_high_hz: float,
    full_scale_volts: float,
    scale_mode: str,
    channel: int,
    distance_cm: float | None,
    safety_max_spl_db: float | None,
    mac_helper_device_id: int | None,
    mac_helper_sample_rate: int | None,
    mac_helper_channels: int,
    mac_helper_gain: float,
    mac_helper_delay_ms: int,
    allow_zero_duration: bool,
) -> None:
    errors = []
    if not _nonnegative(carrier_freq_khz):
        errors.append("carrier_freq_khz must be zero or positive")
    if sample_rate_hz <= 0:
        errors.append("sample_rate_hz must be positive")
    if duration_s < 0 or (duration_s == 0 and not allow_zero_duration):
        errors.append("duration_s must be positive")
    if trim_start_s < 0 or trim_end_s < 0:
        errors.append("trim_start_s and trim_end_s must be zero or positive")
    if not _positive(analysis_band_low_hz) or analysis_band_high_hz <= analysis_band_low_hz:
        errors.append("analysis band requires low_hz > 0 and high_hz > low_hz")
    if scale_mode not in {"peak", "range", "both"}:
        errors.append("scale_mode must be peak, range, or both")
    if scale_mode in {"range", "both"} and not _positive(full_scale_volts):
        errors.append("full_scale_volts must be positive for range WAV conversion")
    if channel < 0:
        errors.append("channel must be zero or positive")
    if distance_cm is not None and distance_cm < 0:
        errors.append("distance_cm must be zero or positive")
    if safety_max_spl_db is not None and safety_max_spl_db < 0:
        errors.append("safety_max_spl_db must be zero or positive")
    if mac_helper_device_id is not None and mac_helper_device_id < 0:
        errors.append("mac_helper_device_id must be zero or positive")
    if mac_helper_sample_rate is not None and mac_helper_sample_rate <= 0:
        errors.append("mac_helper_sample_rate must be positive")
    if mac_helper_channels < 1:
        errors.append("mac_helper_channels must be at least 1")
    if not math.isfinite(float(mac_helper_gain)) or mac_helper_gain < 0 or mac_helper_gain > 1:
        errors.append("mac_helper_gain must be between 0 and 1")
    if mac_helper_delay_ms < 0:
        errors.append("mac_helper_delay_ms must be zero or positive")
    if errors:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "INVALID_RUN_METADATA",
                "message": "; ".join(errors),
                "suggestion": "Fix the run metadata form values before creating or uploading the run.",
            },
        )


def _record_after_create_source(record_after_create: bool, source: str) -> str:
    value = (source or "").strip().lower()
    if not value and record_after_create:
        return "mock"
    if value in {"", "mock", "daq"}:
        return value
    raise HTTPException(
        status_code=400,
        detail={
            "error_code": "INVALID_RECORD_SOURCE",
            "message": f"Unknown create-and-record source: {source}",
            "suggestion": "Use mock mode when hardware is unavailable, or DAQ mode when uldaq hardware is configured.",
        },
    )


def _invalid_raw_bin_error(message: str) -> dict[str, str]:
    return {
        "error_code": "INVALID_RAW_BIN",
        "message": message,
        "suggestion": "Upload a non-empty raw .bin containing little-endian float64 voltage samples.",
    }


def _recording_busy_error(message: str) -> dict[str, str]:
    return {
        "error_code": "RECORDING_BUSY",
        "message": message,
        "suggestion": "Wait for the active recording job to finish before creating and recording a new run.",
    }


def _raw_bin_exists_error(message: str) -> dict[str, str]:
    return {
        "error_code": "RAW_BIN_EXISTS",
        "message": message,
        "suggestion": "Raw .bin files are never overwritten silently. Create another run for another recording.",
    }


def _daq_unavailable_error(message: str) -> dict[str, str]:
    return {
        "error_code": "DAQ_UNAVAILABLE",
        "message": message,
        "suggestion": "Use Create + Record Mock or install/configure uldaq drivers before DAQ recording.",
    }


def _daq_not_configured_error(message: str) -> dict[str, str]:
    return {
        "error_code": "DAQ_NOT_CONFIGURED",
        "message": message,
        "suggestion": "Configure DAQ acquisition for this hardware, or use mock recording.",
    }


def _require_session(workspace: Path, session_id: str) -> None:
    if not (session_dir(workspace, session_id) / "session.json").is_file():
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "SESSION_NOT_FOUND",
                "message": f"Session {session_id} was not found.",
                "suggestion": "Create or open an existing session before adding runs.",
            },
        )


def _require_run(workspace: Path, session_id: str, run_id: str) -> None:
    _require_session(workspace, session_id)
    if not (session_dir(workspace, session_id) / "metadata" / f"{safe_name(run_id)}.json").is_file():
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "RUN_NOT_FOUND",
                "message": f"Run {run_id} was not found in session {session_id}.",
                "suggestion": "Open the session page and choose an existing run.",
            },
        )


def _file_not_found_error(file_path: str, session_id: str) -> dict[str, str]:
    return {
        "error_code": "FILE_NOT_FOUND",
        "message": f"File {file_path} was not found in session {session_id}.",
        "suggestion": "Use the session file browser to choose an existing artifact inside the session workspace.",
    }


def _positive(value: float) -> bool:
    return math.isfinite(float(value)) and float(value) > 0


def _nonnegative(value: float) -> bool:
    return math.isfinite(float(value)) and float(value) >= 0


def _path_inside(base: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
    except ValueError:
        return False
    return True


def _file_browser_row(path: str, size_bytes: int) -> dict[str, object]:
    lower = path.lower()
    if lower.endswith("__scale-peak.wav"):
        return {
            "path": path,
            "size_bytes": size_bytes,
            "kind": "Peak WAV",
            "role": "Listening preview only",
            "is_audio": True,
        }
    if lower.endswith(".wav") and "__scale-range" in lower:
        return {
            "path": path,
            "size_bytes": size_bytes,
            "kind": "Range WAV",
            "role": "Scale-valid cross-check if full-scale voltage is correct",
            "is_audio": True,
        }
    if lower.endswith(".wav"):
        return {
            "path": path,
            "size_bytes": size_bytes,
            "kind": "WAV",
            "role": "Audio preview",
            "is_audio": True,
        }
    if lower.endswith(".bin"):
        return {
            "path": path,
            "size_bytes": size_bytes,
            "kind": "Raw BIN",
            "role": "Primary quantitative data",
            "is_audio": False,
        }
    return {
        "path": path,
        "size_bytes": size_bytes,
        "kind": Path(path).suffix.lstrip(".").upper() or "file",
        "role": "Artifact",
        "is_audio": False,
    }


def _run_artifacts(run: dict, file_set: set[str]) -> list[dict[str, object]]:
    run_id = run["run_id"]
    files = run.get("files", {})
    scale_modes = set(run.get("conversion", {}).get("scale_modes") or ["peak", "range"])
    expected = [
        ("Raw BIN", "Primary quantitative source", files.get("bin", f"bin/{run_id}.bin")),
        ("Run metadata JSON", "Run source-of-truth metadata", f"metadata/{run_id}.json"),
        ("Metrics JSON", "Report-grade metrics", files.get("metrics_json", f"results/{run_id}_metrics.json")),
        ("Metrics CSV", "Tabular metrics export", files.get("metrics_csv", f"results/{run_id}_metrics.csv")),
        ("Waveform PNG", "Report plot", files.get("waveform_png", f"plots/{run_id}_waveform.png")),
        ("Waveform SVG", "Report plot vector", files.get("waveform_svg", f"plots/{run_id}_waveform.svg")),
        ("PSD PNG", "Report plot", files.get("psd_png", f"plots/{run_id}_psd.png")),
        ("PSD SVG", "Report plot vector", files.get("psd_svg", f"plots/{run_id}_psd.svg")),
        ("Spectrogram PNG", "Report plot", files.get("spectrogram_png", f"plots/{run_id}_spectrogram.png")),
        ("Spectrogram SVG", "Report plot vector", files.get("spectrogram_svg", f"plots/{run_id}_spectrogram.svg")),
        ("Run log", "Job log and traceback text", f"logs/{run_id}.log"),
    ]
    if "peak" in scale_modes or files.get("wav_peak") in file_set:
        expected.insert(1, ("Peak WAV", "Listening preview only", files.get("wav_peak", f"wav/{run_id}__scale-peak.wav")))
    if "range" in scale_modes or files.get("wav_range") in file_set:
        expected.insert(2, ("Range WAV", "Cross-check when full-scale voltage is known", files.get("wav_range", f"wav/{run_id}__scale-range-fs10V.wav")))
    artifacts = []
    for label, role, path in expected:
        if not path:
            continue
        artifacts.append({"label": label, "role": role, "path": path, "exists": path in file_set})
    return artifacts
