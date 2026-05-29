from __future__ import annotations

import re

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from ..services.daq import DaqNotConfiguredError, DaqUnavailableError
from ..services.mac_helper_client import MacHelperClient, normalize_helper_url
from ..services.metadata import load_run, save_run
from ..services.recorder import RecordingBusyError, record_daq_and_finalize, record_daq_capture_only, record_mock_and_finalize, record_mock_capture_only
from ..services.tailscale import discover_helpers
from ..services.text_store import append_app_event, append_log, atomic_write_json, read_json_or_default, safe_name, session_dir

router = APIRouter(prefix="/mac-helper", tags=["mac-helper"])


@router.get("")
def mac_helper_page(request: Request):
    config_path = request.app.state.settings.workspace / ".micloaker" / "config.json"
    config = _read_helper_config(request.app.state.settings.workspace)
    status = _client_from_config(request.app.state.settings.workspace).health()
    return request.app.state.templates.TemplateResponse(name="mac_helper.html", request=request, context={"config": config, "status": status})


@router.post("/config")
def save_config(request: Request, mac_helper_url: str = Form(""), mac_helper_token: str = Form("")):
    config_path = request.app.state.settings.workspace / ".micloaker" / "config.json"
    config = _read_helper_config(request.app.state.settings.workspace)
    config["mac_helper_url"] = normalize_helper_url(mac_helper_url)
    config["mac_helper_token"] = mac_helper_token.strip()
    atomic_write_json(config_path, config)
    return RedirectResponse("/mac-helper", status_code=303)


@router.get("/health")
def helper_health(request: Request):
    return _client_from_config(request.app.state.settings.workspace).health()


@router.get("/devices")
def helper_devices(request: Request):
    return _client_from_config(request.app.state.settings.workspace).devices()


@router.get("/files")
def helper_files(request: Request):
    return _client_from_config(request.app.state.settings.workspace).files()


@router.get("/status")
def helper_status(request: Request):
    return _client_from_config(request.app.state.settings.workspace).status()


@router.get("/discover")
def helper_discover():
    return {
        "ok": True,
        "candidates": discover_helpers(),
        "message": "Tailscale discovery is optional and best-effort. Use manual Helper URL when no candidates appear.",
    }


@router.post("/validate-playback")
def validate_playback(
    request: Request,
    file: str = Form(""),
    device_id: str = Form(""),
    sample_rate: str = Form(""),
    channels: str = Form("1"),
    gain: float = Form(1.0),
):
    payload = _standalone_playback_payload(file=file, device_id=device_id, sample_rate=sample_rate, channels=channels, gain=gain)
    return _client_from_config(request.app.state.settings.workspace).validate_playback(payload)


@router.post("/play")
def helper_play(
    request: Request,
    file: str = Form(""),
    device_id: str = Form(""),
    sample_rate: str = Form(""),
    channels: str = Form("1"),
    gain: float = Form(1.0),
    delay_ms: str = Form("0"),
):
    payload = _standalone_playback_payload(file=file, device_id=device_id, sample_rate=sample_rate, channels=channels, gain=gain)
    payload["delay_ms"] = _parse_int_field("delay_ms", delay_ms, minimum=0)
    return _client_from_config(request.app.state.settings.workspace).play(payload)


@router.post("/stop")
def helper_stop(request: Request):
    return _client_from_config(request.app.state.settings.workspace).stop()


@router.post("/sessions/{session_id}/runs/{run_id}/validate-playback")
def validate_run_playback(
    request: Request,
    session_id: str,
    run_id: str,
    file: str = Form(...),
    device_id: int = Form(...),
    sample_rate: int = Form(...),
    channels: int = Form(2),
    gain: float = Form(1.0),
):
    workspace = request.app.state.settings.workspace
    _require_run(workspace, session_id, run_id)
    run = load_run(workspace, session_id, run_id)
    payload = {"file": file, "device_id": device_id, "sample_rate": sample_rate, "channels": channels, "gain": gain}
    _store_helper_plan(workspace, session_id, run_id, {**payload, "delay_ms": None})
    _reject_if_jamming_file_mismatches_run(workspace, session_id, run_id, run, payload, action="validate_playback")
    result = _client_from_config(workspace).validate_playback(payload)
    _store_helper_result(workspace, session_id, run_id, "validate_playback", payload, result)
    return result


@router.post("/sessions/{session_id}/runs/{run_id}/play")
def play_run_helper(
    request: Request,
    session_id: str,
    run_id: str,
    file: str = Form(...),
    device_id: int = Form(...),
    sample_rate: int = Form(...),
    channels: int = Form(2),
    gain: float = Form(1.0),
    delay_ms: int = Form(0),
):
    workspace = request.app.state.settings.workspace
    _require_run(workspace, session_id, run_id)
    run = load_run(workspace, session_id, run_id)
    payload = {"file": file, "device_id": device_id, "sample_rate": sample_rate, "channels": channels, "gain": gain, "delay_ms": delay_ms, "duration_s": _run_duration_s(run)}
    _store_helper_plan(workspace, session_id, run_id, payload)
    _reject_if_jamming_file_mismatches_run(workspace, session_id, run_id, run, payload, action="play")
    result = _client_from_config(workspace).play(payload)
    _store_helper_result(workspace, session_id, run_id, "play", payload, result)
    return result


@router.post("/sessions/{session_id}/runs/{run_id}/stop")
def stop_run_helper(request: Request, session_id: str, run_id: str):
    workspace = request.app.state.settings.workspace
    _require_run(workspace, session_id, run_id)
    result = _client_from_config(workspace).stop()
    _store_helper_result(workspace, session_id, run_id, "stop", {}, result)
    return result


@router.post("/sessions/{session_id}/runs/{run_id}/play-and-record-mock")
def play_and_record_mock(
    request: Request,
    session_id: str,
    run_id: str,
    file: str = Form(...),
    device_id: int = Form(...),
    sample_rate: int = Form(...),
    channels: int = Form(2),
    gain: float = Form(1.0),
    delay_ms: int = Form(500),
):
    return _play_and_record(
        request,
        session_id,
        run_id,
        recorder=record_mock_and_finalize,
        recorder_label="mock",
        file=file,
        device_id=device_id,
        sample_rate=sample_rate,
        channels=channels,
        gain=gain,
        delay_ms=delay_ms,
    )


@router.post("/sessions/{session_id}/runs/{run_id}/play-and-capture-mock")
def play_and_capture_mock(
    request: Request,
    session_id: str,
    run_id: str,
    file: str = Form(...),
    device_id: int = Form(...),
    sample_rate: int = Form(...),
    channels: int = Form(2),
    gain: float = Form(1.0),
    delay_ms: int = Form(500),
):
    return _play_and_record(
        request,
        session_id,
        run_id,
        recorder=record_mock_capture_only,
        recorder_label="mock_capture_only",
        file=file,
        device_id=device_id,
        sample_rate=sample_rate,
        channels=channels,
        gain=gain,
        delay_ms=delay_ms,
    )


@router.post("/sessions/{session_id}/runs/{run_id}/play-and-record-daq")
def play_and_record_daq(
    request: Request,
    session_id: str,
    run_id: str,
    file: str = Form(...),
    device_id: int = Form(...),
    sample_rate: int = Form(...),
    channels: int = Form(2),
    gain: float = Form(1.0),
    delay_ms: int = Form(500),
):
    return _play_and_record(
        request,
        session_id,
        run_id,
        recorder=record_daq_and_finalize,
        recorder_label="daq",
        file=file,
        device_id=device_id,
        sample_rate=sample_rate,
        channels=channels,
        gain=gain,
        delay_ms=delay_ms,
    )


@router.post("/sessions/{session_id}/runs/{run_id}/play-and-capture-daq")
def play_and_capture_daq(
    request: Request,
    session_id: str,
    run_id: str,
    file: str = Form(...),
    device_id: int = Form(...),
    sample_rate: int = Form(...),
    channels: int = Form(2),
    gain: float = Form(1.0),
    delay_ms: int = Form(500),
):
    return _play_and_record(
        request,
        session_id,
        run_id,
        recorder=record_daq_capture_only,
        recorder_label="daq_capture_only",
        file=file,
        device_id=device_id,
        sample_rate=sample_rate,
        channels=channels,
        gain=gain,
        delay_ms=delay_ms,
    )


def _play_and_record(
    request: Request,
    session_id: str,
    run_id: str,
    *,
    recorder,
    recorder_label: str,
    file: str,
    device_id: int,
    sample_rate: int,
    channels: int,
    gain: float,
    delay_ms: int,
):
    workspace = request.app.state.settings.workspace
    _require_run(workspace, session_id, run_id)
    run = load_run(workspace, session_id, run_id)
    helper = run.get("mac_helper", {})
    last_request = helper.get("last_request", {})
    requested = {"file": file, "device_id": device_id, "sample_rate": sample_rate, "channels": channels, "gain": gain}
    _store_helper_plan(workspace, session_id, run_id, {**requested, "delay_ms": delay_ms})
    _reject_if_jamming_file_mismatches_run(workspace, session_id, run_id, run, requested, action="play_and_record_rejected")
    validated = helper.get("validate_playback_ok") is True and all(last_request.get(k) == v for k, v in requested.items())
    if not validated:
        result = {
            "ok": False,
            "error_code": "PLAYBACK_NOT_VALIDATED",
            "message": "Validate Playback must succeed for these exact settings before Play & Record.",
            "suggestion": "Run Validate Playback, then retry Play & Record without changing file/device/rate/channel/gain.",
        }
        _store_helper_result(workspace, session_id, run_id, "play_and_record_rejected", requested, result)
        raise HTTPException(status_code=400, detail=result)
    payload = {**requested, "delay_ms": delay_ms, "duration_s": _run_duration_s(run)}
    client = _client_from_config(workspace)
    play_result = client.play(payload)
    _store_helper_result(workspace, session_id, run_id, "play", payload, play_result)
    if not play_result.get("ok"):
        raise HTTPException(status_code=502, detail=play_result)
    try:
        final = recorder(workspace, load_run(workspace, session_id, run_id))
    except RecordingBusyError as exc:
        detail = _recording_busy_error(str(exc))
        _stop_helper_after_failed_recording(workspace, session_id, run_id, client)
        _store_helper_result(workspace, session_id, run_id, "play_and_record_failed", payload, {"ok": False, **detail})
        raise HTTPException(status_code=409, detail=detail) from exc
    except FileExistsError as exc:
        detail = _raw_bin_exists_error(str(exc))
        _stop_helper_after_failed_recording(workspace, session_id, run_id, client)
        _store_helper_result(workspace, session_id, run_id, "play_and_record_failed", payload, {"ok": False, **detail})
        raise HTTPException(status_code=409, detail=detail) from exc
    except DaqUnavailableError as exc:
        detail = {"error_code": "DAQ_UNAVAILABLE", "message": str(exc), "suggestion": "Install/configure uldaq drivers before DAQ recording, or import a saved raw .bin file."}
        _stop_helper_after_failed_recording(workspace, session_id, run_id, client)
        _store_helper_result(workspace, session_id, run_id, "play_and_record_failed", payload, {"ok": False, **detail})
        raise HTTPException(status_code=503, detail=detail) from exc
    except DaqNotConfiguredError as exc:
        detail = {"error_code": "DAQ_NOT_CONFIGURED", "message": str(exc), "suggestion": "Configure the DAQ-specific acquisition code for this hardware, or import a saved raw .bin file."}
        _stop_helper_after_failed_recording(workspace, session_id, run_id, client)
        _store_helper_result(workspace, session_id, run_id, "play_and_record_failed", payload, {"ok": False, **detail})
        raise HTTPException(status_code=501, detail=detail) from exc
    return {"ok": True, "playback": play_result, "recording_source": recorder_label, "run": {"run_id": final["run_id"], "analysis_status": final["analysis"]["status"]}}


def _stop_helper_after_failed_recording(workspace, session_id: str, run_id: str, client: MacHelperClient) -> None:
    stop_result = client.stop()
    _store_helper_result(workspace, session_id, run_id, "stop_after_recording_failure", {}, stop_result)


def _client_from_config(workspace):
    config = _read_helper_config(workspace)
    return MacHelperClient(config.get("mac_helper_url", ""), config.get("mac_helper_token", ""))


def _standalone_playback_payload(*, file: str, device_id: str, sample_rate: str, channels: str, gain: float) -> dict:
    if not file.strip():
        raise HTTPException(
            status_code=400,
            detail=_helper_form_error(
                "MISSING_PLAYBACK_FILE",
                "Mac Helper playback requires a WAV file path.",
                "Refresh files and choose a WAV file before validating or playing.",
            ),
        )
    return {
        "file": file.strip(),
        "device_id": _parse_int_field("device_id", device_id, minimum=0),
        "sample_rate": _parse_int_field("sample_rate", sample_rate, minimum=1),
        "channels": _parse_int_field("channels", channels, minimum=1),
        "gain": gain,
    }


def _parse_int_field(name: str, value: str, *, minimum: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail=_helper_form_error(
                "INVALID_PLAYBACK_FIELD",
                f"{name} must be an integer.",
                "Refresh devices/files and choose valid playback settings before validating or playing.",
            ),
        ) from exc
    if parsed < minimum:
        raise HTTPException(
            status_code=400,
            detail=_helper_form_error(
                "INVALID_PLAYBACK_FIELD",
                f"{name} must be at least {minimum}.",
                "Choose valid playback settings before validating or playing.",
            ),
        )
    return parsed


def _helper_form_error(error_code: str, message: str, suggestion: str) -> dict[str, str | bool]:
    return {"ok": False, "error_code": error_code, "message": message, "suggestion": suggestion}


def _reject_if_jamming_file_mismatches_run(workspace, session_id: str, run_id: str, run: dict, payload: dict, *, action: str) -> None:
    result = _jamming_file_metadata_error(run, str(payload.get("file", "")))
    if result is None:
        return
    _store_helper_result(workspace, session_id, run_id, action, payload, result)
    raise HTTPException(status_code=400, detail=result)


def _jamming_file_metadata_error(run: dict, file: str) -> dict[str, str | bool] | None:
    """Validate that run jamming metadata matches the Mac Helper WAV selection."""
    condition = run.get("condition", {})
    try:
        freq_khz = float(condition.get("carrier_freq_khz", 0.0) or 0.0)
    except (TypeError, ValueError):
        freq_khz = 0.0
    normalized_file = _normalize_jamming_name(file)
    if freq_khz == 0.0:
        if "khz" in normalized_file or "jamming" in normalized_file:
            return _helper_form_error(
                "JAMMING_FILE_METADATA_MISMATCH",
                "This run is marked 0 kHz, which means no jamming signal should be emitted.",
                "Use a non-jamming playback file for this run, or set the run jamming carrier frequency to match the selected WAV.",
            )
        return None
    expected = _frequency_file_token(freq_khz)
    if expected not in normalized_file:
        display_freq = f"{freq_khz:g} kHz"
        return _helper_form_error(
            "JAMMING_FILE_METADATA_MISMATCH",
            f"Selected WAV file does not match this run's jamming carrier metadata ({display_freq}).",
            f"Choose the matching jamming_sound/{expected}_1hr.wav file or create a new run with the correct carrier frequency.",
        )
    return None


def _frequency_file_token(freq_khz: float) -> str:
    raw = f"{freq_khz:g}".lower()
    raw = re.sub(r"[^0-9.]+", "", raw)
    return f"{raw}khz"


def _normalize_jamming_name(file: str) -> str:
    return re.sub(r"[^a-z0-9.]+", "", file.lower())


def _read_helper_config(workspace) -> dict:
    config = read_json_or_default(workspace / ".micloaker" / "config.json", {"mac_helper_url": "", "mac_helper_token": ""})
    config["mac_helper_url"] = normalize_helper_url(str(config.get("mac_helper_url") or ""))
    return config


def _recording_busy_error(message: str) -> dict[str, str]:
    return {
        "error_code": "RECORDING_BUSY",
        "message": message,
        "suggestion": "Wait for the active recording job to finish before starting Play & Record.",
    }


def _raw_bin_exists_error(message: str) -> dict[str, str]:
    return {
        "error_code": "RAW_BIN_EXISTS",
        "message": message,
        "suggestion": "Raw .bin files are never overwritten silently. Create a new run before using Play & Record again.",
    }


def _require_run(workspace, session_id: str, run_id: str) -> None:
    base = session_dir(workspace, session_id)
    if not (base / "session.json").is_file():
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "SESSION_NOT_FOUND",
                "message": f"Session {session_id} was not found.",
                "suggestion": "Open the Sessions page and choose an existing session before using Mac Helper run controls.",
            },
        )
    if not (base / "metadata" / f"{safe_name(run_id)}.json").is_file():
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "RUN_NOT_FOUND",
                "message": f"Run {run_id} was not found in session {session_id}.",
                "suggestion": "Open the run detail page and use Mac Helper controls for an existing run.",
            },
        )


def _store_helper_result(workspace, session_id: str, run_id: str, action: str, payload: dict, result: dict) -> None:
    config = _read_helper_config(workspace)
    run = load_run(workspace, session_id, run_id)
    helper = run.setdefault("mac_helper", {})
    request_ok = bool(result.get("ok"))
    connected = _helper_connected_state(action, result, helper)
    helper.update({
        "enabled": connected,
        "connected": connected,
        "health_ok": connected,
        "helper_url": config.get("mac_helper_url", ""),
        "hostname": result.get("hostname") or helper.get("hostname"),
        "file": payload.get("file", helper.get("file")),
        "device_id": payload.get("device_id", helper.get("device_id")),
        "device_name": result.get("device_name") or helper.get("device_name"),
        "device_max_output_channels": result.get("device_max_output_channels") or helper.get("device_max_output_channels"),
        "device_default_samplerate": result.get("device_default_samplerate") or helper.get("device_default_samplerate"),
        "device_hostapi": result.get("device_hostapi") or helper.get("device_hostapi"),
        "requested_sample_rate": payload.get("sample_rate", helper.get("requested_sample_rate")),
        "source_sample_rate": result.get("source_sample_rate") or helper.get("source_sample_rate"),
        "actual_playback_sample_rate": result.get("actual_playback_sample_rate") or result.get("sample_rate") or result.get("requested_sample_rate") or payload.get("sample_rate") or helper.get("actual_playback_sample_rate"),
        "will_resample": bool(result.get("will_resample", helper.get("will_resample", False))),
        "playback_duration_s": result.get("duration_s") or helper.get("playback_duration_s"),
        "channels": payload.get("channels", helper.get("channels")),
        "source_channels": result.get("source_channels") or result.get("channels") or helper.get("source_channels"),
        "requested_channels": result.get("requested_channels") or payload.get("channels") or helper.get("requested_channels"),
        "will_channel_map": bool(result.get("will_channel_map", helper.get("will_channel_map", False))),
        "gain": payload.get("gain", helper.get("gain")),
        "delay_ms": payload.get("delay_ms", helper.get("delay_ms")),
        "expected_end_after_s": result.get("expected_end_after_s") or helper.get("expected_end_after_s"),
        "last_action": action,
        "last_request": payload,
        "last_response": result,
        "last_error_code": None if request_ok else result.get("error_code", "HELPER_REQUEST_FAILED"),
        "last_error": None if request_ok else result.get("message", "Mac Helper request failed"),
        "last_suggestion": None if request_ok else result.get("suggestion"),
    })
    if action == "validate_playback":
        helper["validate_playback_ok"] = request_ok
    if action == "play":
        helper["play_request_ok"] = request_ok
        helper["play_id"] = result.get("play_id")
    if action == "stop":
        helper["stop_request_ok"] = request_ok
    save_run(workspace, run)
    log_path = session_dir(workspace, session_id) / "logs" / f"{run_id}.log"
    append_log(log_path, f"mac_helper_{action} ok={result.get('ok')} response={result}")
    append_app_event(
        workspace,
        "mac_helper_client_action",
        session_id=session_id,
        run_id=run_id,
        action=action,
        ok=request_ok,
        error_code=result.get("error_code", ""),
    )


def _store_helper_plan(workspace, session_id: str, run_id: str, payload: dict) -> None:
    run = load_run(workspace, session_id, run_id)
    helper = run.setdefault("mac_helper", {})
    if payload.get("file") is not None:
        helper["planned_file"] = payload.get("file")
    if payload.get("device_id") is not None:
        helper["planned_device_id"] = payload.get("device_id")
    if payload.get("sample_rate") is not None:
        helper["planned_sample_rate"] = payload.get("sample_rate")
    if payload.get("channels") is not None:
        helper["planned_channels"] = payload.get("channels")
    if payload.get("gain") is not None:
        helper["planned_gain"] = payload.get("gain")
    if payload.get("delay_ms") is not None:
        helper["planned_delay_ms"] = payload.get("delay_ms")
    save_run(workspace, run)


def _helper_connected_state(action: str, result: dict, helper: dict) -> bool:
    if action == "play_and_record_rejected":
        return bool(helper.get("connected", False))
    if result.get("error_code") == "HELPER_DISCONNECTED":
        return False
    if "connected" in result:
        return bool(result.get("connected"))
    return True


def _run_duration_s(run: dict) -> float | None:
    duration = float(run.get("recording", {}).get("duration_s", 0.0) or 0.0)
    return duration if duration > 0 else None
