from __future__ import annotations

import argparse
import json
import math
import socket
import threading
import time
import wave
from itertools import count
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import numpy as np

STARTED = time.monotonic()
STATE: dict[str, Any] = {"playing": False, "current_play_id": None, "last_error": None, "last_error_code": None, "last_suggestion": None}
PLAY_COUNTER = count(1)


class PlaybackRequest(BaseModel):
    file: str
    device_id: int
    sample_rate: int
    channels: int = 2
    gain: float = 1.0
    delay_ms: int = 0
    duration_s: float | None = None


def create_app(config: dict[str, Any]) -> FastAPI:
    global PLAY_COUNTER
    app = FastAPI(title="MiCloaker macOS Audio Helper", version="0.1.0")
    wav_root = Path(config["wav_root"]).expanduser().resolve()
    mock_audio = bool(config.get("mock_audio", False))
    optional_token = str(config.get("optional_token") or "").strip()
    PLAY_COUNTER = count(1)
    STATE.clear()
    STATE.update({
        "playing": False,
        "current_play_id": None,
        "last_error": None,
        "last_error_code": None,
        "last_suggestion": None,
        "last_validation_ok": None,
        "last_validation_request": None,
    })

    @app.middleware("http")
    async def optional_token_auth(request: Request, call_next):
        if optional_token:
            expected = f"Bearer {optional_token}"
            provided = request.headers.get("authorization", "")
            if provided != expected:
                return JSONResponse(
                    status_code=401,
                    content=_error(
                        "UNAUTHORIZED",
                        "Mac Helper optional_token is configured and the request did not include a matching bearer token.",
                        "Configure the same helper token in the Linux console or remove optional_token on a trusted local network.",
                    ),
                )
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=400,
            content=_error(
                "INVALID_REQUEST",
                _validation_message(exc),
                "Send JSON with file, device_id, sample_rate, channels, gain, and optional delay_ms.",
            ),
        )

    @app.get("/health")
    def health():
        return {
            "ok": True,
            "service": "micloaker-mac-audio-helper",
            "version": "0.1.0",
            "hostname": socket.gethostname(),
            "os": "macOS",
            "uptime_s": time.monotonic() - STARTED,
            "wav_root": str(wav_root),
            "wav_root_exists": wav_root.exists(),
            "audio_backend": "sounddevice",
            "server_time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }

    @app.get("/devices")
    def devices():
        if mock_audio:
            return {
                "ok": True,
                "output_devices": [{
                    "id": 1,
                    "name": "Mock Output Device",
                    "max_output_channels": 2,
                    "default_samplerate": float(config.get("default_sample_rate", 192000)),
                    "hostapi": "Mock",
                }],
            }
        try:
            import sounddevice as sd

            output = []
            for idx, dev in enumerate(sd.query_devices()):
                if int(dev.get("max_output_channels", 0)) > 0:
                    output.append({
                        "id": idx,
                        "name": dev.get("name", ""),
                        "max_output_channels": int(dev.get("max_output_channels", 0)),
                        "default_samplerate": float(dev.get("default_samplerate", 0.0)),
                        "hostapi": str(dev.get("hostapi", "")),
                    })
            return {"ok": True, "output_devices": output}
        except Exception as exc:
            return _error("AUDIO_BACKEND_UNAVAILABLE", str(exc), "Install sounddevice/PortAudio or run the helper on the Mac.")

    @app.get("/files")
    def files():
        if not wav_root.exists():
            return {"ok": True, "files": []}
        out = []
        for path in wav_root.rglob("*.wav"):
            if not _path_inside_root(wav_root, path):
                continue
            rel = path.relative_to(wav_root).as_posix()
            try:
                with wave.open(str(path), "rb") as wf:
                    duration = wf.getnframes() / float(wf.getframerate())
                    sr = wf.getframerate()
            except Exception:
                duration = 0.0
                sr = 0
            out.append({"path": rel, "size_bytes": path.stat().st_size, "duration_s": duration, "sample_rate": sr})
        return {"ok": True, "files": sorted(out, key=lambda x: x["path"])}

    @app.post("/validate-playback")
    def validate(req: PlaybackRequest):
        result = _validate(wav_root, req, mock_audio=mock_audio, default_sample_rate=float(config.get("default_sample_rate", 192000)))
        _store_validation_status(req, result)
        return result

    @app.post("/play")
    def play(req: PlaybackRequest):
        valid = _validate(wav_root, req, mock_audio=mock_audio, default_sample_rate=float(config.get("default_sample_rate", 192000)))
        if not valid.get("ok"):
            STATE["playing"] = False
            _set_playback_error(
                str(valid.get("error_code") or "PLAYBACK_VALIDATION_FAILED"),
                str(valid.get("message") or "Playback validation failed."),
                str(valid.get("suggestion") or "Validate playback settings and retry."),
            )
            return valid
        play_id = _new_play_id()
        playback_duration_s = _effective_playback_duration(req, float(valid.get("duration_s") or 0.0))
        expected_end_after_s = (req.delay_ms / 1000.0) + playback_duration_s
        STATE.update({
            "playing": True,
            "current_play_id": play_id,
            "file": req.file,
            "device_id": req.device_id,
            "device_name": valid.get("device_name"),
            "device_max_output_channels": valid.get("device_max_output_channels"),
            "device_default_samplerate": valid.get("device_default_samplerate"),
            "device_hostapi": valid.get("device_hostapi"),
            "sample_rate": req.sample_rate,
            "source_sample_rate": valid.get("source_sample_rate"),
            "channels": req.channels,
            "source_channels": valid.get("channels"),
            "gain": req.gain,
            "delay_ms": req.delay_ms,
            "started": time.monotonic(),
            "duration_s": playback_duration_s,
            "source_duration_s": valid.get("duration_s"),
            "expected_end_after_s": expected_end_after_s,
            "last_error": None,
            "last_error_code": None,
            "last_suggestion": None,
        })
        if not mock_audio:
            path = _safe_wav_path(wav_root, req.file)
            assert path is not None
            thread = threading.Thread(target=_play_file, args=(path, req, play_id), daemon=True)
            thread.start()
        return {
            "ok": True,
            "play_id": play_id,
            "message": "Playback scheduled",
            **req.model_dump(),
            "file_exists": valid.get("file_exists"),
            "device_exists": valid.get("device_exists"),
            "device_name": valid.get("device_name"),
            "device_max_output_channels": valid.get("device_max_output_channels"),
            "device_default_samplerate": valid.get("device_default_samplerate"),
            "device_hostapi": valid.get("device_hostapi"),
            "output_settings_supported": valid.get("output_settings_supported"),
            "source_sample_rate": valid.get("source_sample_rate"),
            "requested_sample_rate": valid.get("requested_sample_rate"),
            "will_resample": valid.get("will_resample"),
            "duration_s": playback_duration_s,
            "source_duration_s": valid.get("duration_s"),
            "source_channels": valid.get("channels"),
            "requested_channels": valid.get("requested_channels"),
            "will_channel_map": valid.get("will_channel_map"),
            "expected_end_after_s": expected_end_after_s,
        }

    @app.post("/stop")
    def stop():
        STATE["playing"] = False
        STATE["stopped_play_id"] = STATE.get("current_play_id")
        if not mock_audio:
            try:
                import sounddevice as sd

                sd.stop()
            except Exception as exc:
                _set_playback_error("STOP_FAILED", str(exc), "Check the audio backend and retry.")
                return _error("STOP_FAILED", str(exc), "Check the audio backend and retry.")
        return {"ok": True, "playing": False}

    @app.get("/status")
    def status():
        _refresh_playback_state()
        elapsed = time.monotonic() - STATE.get("started", time.monotonic()) if STATE.get("playing") else 0.0
        return {"ok": True, "elapsed_s": elapsed, **STATE}

    return app


def _safe_wav_path(root: Path, rel: str) -> Path | None:
    path = (root / rel).resolve()
    if not _path_inside_root(root, path):
        return None
    if path.suffix.lower() != ".wav":
        return None
    return path


def _path_inside_root(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _validate(root: Path, req: PlaybackRequest, *, mock_audio: bool = False, default_sample_rate: float = 192000.0) -> dict[str, Any]:
    if Path(req.file).is_absolute():
        return _error("ABSOLUTE_PATH_REJECTED", "Playback file paths must be relative to wav_root.", "Choose a WAV path returned by /files.")
    path = _safe_wav_path(root, req.file)
    if path is None:
        return _error("PATH_TRAVERSAL_REJECTED", "The requested file is outside wav_root.", "Choose a WAV returned by /files.")
    if not path.exists():
        return _error("FILE_NOT_FOUND", "The requested WAV file was not found under wav_root.", "Refresh file list or copy the WAV into wav_root.")
    if req.sample_rate <= 0:
        return _error("INVALID_SAMPLE_RATE", "Sample rate must be positive.", "Use 48000, 96000, 192000, or the source WAV sample rate.")
    if req.channels < 1:
        return _error("INVALID_CHANNELS", "Channels must be at least 1.", "Use mono or stereo output settings.")
    if req.delay_ms < 0:
        return _error("INVALID_DELAY", "Delay must be zero or positive.", "Use a delay of 0 ms or greater.")
    if req.duration_s is not None and req.duration_s <= 0:
        return _error("INVALID_DURATION", "Playback duration must be positive when provided.", "Use the run duration or leave duration_s empty.")
    if not math.isfinite(req.gain) or not 0.0 <= req.gain <= 1.0:
        return _error("INVALID_GAIN", "Gain must be between 0.0 and 1.0.", "Lower the gain.")
    try:
        with wave.open(str(path), "rb") as wf:
            source_sr = wf.getframerate()
            duration = wf.getnframes() / float(source_sr)
            source_channels = wf.getnchannels()
    except Exception as exc:
        return _error("WAV_READ_FAILED", str(exc), "Verify the WAV file is readable.")
    if source_channels != req.channels and source_channels != 1:
        return _error("UNSUPPORTED_CHANNELS", "Requested channel count is incompatible with the WAV channel count.", "Use a compatible mono WAV or match the WAV channel count.")
    if mock_audio:
        device_check = _check_mock_output_device(req.device_id, req.channels, default_sample_rate=default_sample_rate)
    else:
        device_check = _check_output_device(req.device_id, req.sample_rate, req.channels)
    if not device_check.get("ok"):
        return device_check
    return {
        "ok": True,
        "file_exists": True,
        "device_exists": True,
        "device_name": device_check.get("device_name"),
        "device_max_output_channels": device_check.get("device_max_output_channels"),
        "device_default_samplerate": device_check.get("device_default_samplerate"),
        "device_hostapi": device_check.get("device_hostapi"),
        "output_settings_supported": True,
        "source_sample_rate": source_sr,
        "requested_sample_rate": req.sample_rate,
        "will_resample": source_sr != req.sample_rate,
        "duration_s": duration,
        "channels": source_channels,
        "requested_channels": req.channels,
        "will_channel_map": source_channels != req.channels,
    }


def _check_mock_output_device(device_id: int, channels: int, *, default_sample_rate: float) -> dict[str, Any]:
    if device_id != 1:
        return _error("DEVICE_NOT_FOUND", "The selected output device does not exist.", "Refresh device list and choose a valid output device.")
    if channels > 2:
        return _error("UNSUPPORTED_CHANNELS", "The selected device does not support the requested output channels.", "Choose another device or lower the channel count.")
    return {
        "ok": True,
        "device_name": "Mock Output Device",
        "device_max_output_channels": 2,
        "device_default_samplerate": float(default_sample_rate),
        "device_hostapi": "Mock",
    }


def _check_output_device(device_id: int, sample_rate: int, channels: int) -> dict[str, Any]:
    try:
        import sounddevice as sd
    except Exception as exc:
        return _error("AUDIO_BACKEND_UNAVAILABLE", str(exc), "Install sounddevice/PortAudio on the Mac or run validation in mock mode for tests.")
    try:
        devices = sd.query_devices()
        if device_id < 0 or device_id >= len(devices):
            return _error("DEVICE_NOT_FOUND", "The selected output device does not exist.", "Refresh device list and choose a valid output device.")
        device = devices[device_id]
        if int(device.get("max_output_channels", 0)) < channels:
            return _error("UNSUPPORTED_CHANNELS", "The selected device does not support the requested output channels.", "Choose another device or lower the channel count.")
        sd.check_output_settings(device=device_id, samplerate=sample_rate, channels=channels)
    except Exception as exc:
        return _error("UNSUPPORTED_SAMPLE_RATE", str(exc), "Try another sample rate or check macOS Audio MIDI Setup.")
    return {
        "ok": True,
        "device_name": str(device.get("name", "")),
        "device_max_output_channels": int(device.get("max_output_channels", 0)),
        "device_default_samplerate": float(device.get("default_samplerate", 0.0)),
        "device_hostapi": str(device.get("hostapi", "")),
    }


def _play_file(path: Path, req: PlaybackRequest, play_id: str) -> None:
    try:
        if req.delay_ms > 0:
            time.sleep(req.delay_ms / 1000.0)
        if not _playback_still_active(play_id):
            return
        import sounddevice as sd
        import soundfile as sf

        max_output_frames = int(round(req.duration_s * req.sample_rate)) if req.duration_s and req.duration_s > 0 else None
        written_output_frames = 0
        source_rate = _soundfile_sample_rate(sf, path)
        blocksize = 65536
        with sd.OutputStream(samplerate=req.sample_rate, device=req.device_id, channels=req.channels, dtype="float32") as stream:
            for block in sf.blocks(str(path), blocksize=blocksize, dtype="float32", always_2d=True):
                if not _playback_still_active(play_id):
                    return
                data = _prepare_playback_block(block, req, source_rate)
                if max_output_frames is not None:
                    remaining = max_output_frames - written_output_frames
                    if remaining <= 0:
                        break
                    data = data[:remaining]
                if data.size == 0:
                    continue
                stream.write(data)
                written_output_frames += int(data.shape[0])
        if STATE.get("current_play_id") == play_id:
            STATE["playing"] = False
    except Exception as exc:
        if STATE.get("current_play_id") == play_id:
            STATE["playing"] = False
        _set_playback_error("PLAYBACK_FAILED", str(exc), "Check the WAV file, output device, and audio backend logs before retrying.")


def _effective_playback_duration(req: PlaybackRequest, source_duration_s: float) -> float:
    if req.duration_s and req.duration_s > 0:
        return min(source_duration_s, float(req.duration_s))
    return source_duration_s


def _soundfile_sample_rate(sf_module: Any, path: Path) -> int:
    with sf_module.SoundFile(str(path)) as wav:
        return int(wav.samplerate)


def _prepare_playback_block(block: Any, req: PlaybackRequest, source_rate: int) -> np.ndarray:
    data = np.asarray(block, dtype=np.float32)
    if data.ndim == 1:
        data = data.reshape((-1, 1))
    if data.shape[1] == 1 and req.channels > 1:
        data = np.repeat(data, req.channels, axis=1)
    else:
        data = data[:, : req.channels]
        if data.shape[1] < req.channels:
            pad = np.zeros((data.shape[0], req.channels - data.shape[1]), dtype=np.float32)
            data = np.concatenate([data, pad], axis=1)
    if req.gain != 1.0:
        data = data * np.float32(req.gain)
    if int(source_rate) != int(req.sample_rate):
        data = _resample_audio(data, int(source_rate), int(req.sample_rate))
    return np.asarray(data, dtype=np.float32)


def _playback_still_active(play_id: str) -> bool:
    return STATE.get("playing") is True and STATE.get("current_play_id") == play_id


def _set_playback_error(code: str, message: str, suggestion: str) -> None:
    STATE["last_error_code"] = code
    STATE["last_error"] = message
    STATE["last_suggestion"] = suggestion


def _store_validation_status(req: PlaybackRequest, result: dict[str, Any]) -> None:
    ok = bool(result.get("ok"))
    STATE["last_validation_ok"] = ok
    STATE["last_validation_request"] = req.model_dump()
    if ok:
        STATE["last_error_code"] = None
        STATE["last_error"] = None
        STATE["last_suggestion"] = None
        return
    STATE["playing"] = False
    _set_playback_error(
        str(result.get("error_code") or "PLAYBACK_VALIDATION_FAILED"),
        str(result.get("message") or "Playback validation failed."),
        str(result.get("suggestion") or "Validate playback settings and retry."),
    )


def _refresh_playback_state() -> None:
    if not STATE.get("playing"):
        return
    duration = STATE.get("expected_end_after_s", STATE.get("duration_s"))
    started = STATE.get("started")
    if duration is None or started is None:
        return
    if time.monotonic() - float(started) >= float(duration):
        STATE["playing"] = False


def _resample_audio(data: Any, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate <= 0 or target_rate <= 0:
        raise ValueError("source_rate and target_rate must be positive")
    samples = np.asarray(data, dtype=np.float32)
    if samples.size == 0 or source_rate == target_rate:
        return samples
    source_frames = samples.shape[0]
    target_frames = max(1, int(round(source_frames * target_rate / source_rate)))
    source_x = np.linspace(0.0, 1.0, source_frames, endpoint=False)
    target_x = np.linspace(0.0, 1.0, target_frames, endpoint=False)
    if samples.ndim == 1:
        return np.interp(target_x, source_x, samples).astype(np.float32)
    channels = [np.interp(target_x, source_x, samples[:, channel]) for channel in range(samples.shape[1])]
    return np.stack(channels, axis=1).astype(np.float32)


def _new_play_id() -> str:
    return f"play_{time.strftime('%Y%m%d_%H%M%S')}_{next(PLAY_COUNTER):03d}"


def _error(code: str, message: str, suggestion: str) -> dict[str, Any]:
    return {"ok": False, "error_code": code, "message": message, "suggestion": suggestion}


def _validation_message(exc: RequestValidationError) -> str:
    parts = []
    for error in exc.errors():
        loc = ".".join(str(part) for part in error.get("loc", []) if part != "body")
        msg = error.get("msg", "Invalid request field.")
        parts.append(f"{loc}: {msg}" if loc else str(msg))
    return "Invalid playback request. " + "; ".join(parts)


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    cfg = load_config(Path(args.config))
    import uvicorn

    uvicorn.run(create_app(cfg), host=cfg.get("host", "0.0.0.0"), port=int(cfg.get("port", 5050)))
