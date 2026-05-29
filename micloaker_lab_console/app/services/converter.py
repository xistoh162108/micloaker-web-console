from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from .raw_bin import read_raw_float64_bin
from .text_store import now_iso

PEAK_WAV_HEADROOM = 0.999


def peak_wav_name(run_id: str) -> str:
    return f"{run_id}__scale-peak.wav"


def range_wav_name(run_id: str, full_scale_volts: float) -> str:
    return f"{run_id}__scale-range-fs{full_scale_volts:g}V.wav"


def read_bin_float64(path: Path) -> np.ndarray:
    return read_raw_float64_bin(path)


def convert_bin_to_wav(
    bin_path: Path,
    wav_dir: Path,
    run_id: str,
    sample_rate_hz: int,
    *,
    scale_mode: str,
    full_scale_volts: float = 10.0,
    remove_dc: bool = True,
    overwrite: bool = False,
) -> Path:
    data = read_bin_float64(bin_path).astype(np.float64)
    if remove_dc and data.size:
        data = data - float(np.mean(data))
    wav_dir.mkdir(parents=True, exist_ok=True)
    if scale_mode == "peak":
        out = wav_dir / peak_wav_name(run_id)
        denom = float(np.max(np.abs(data))) if data.size else 1.0
        scaled = (data / max(denom, 1e-12)) * PEAK_WAV_HEADROOM
    elif scale_mode == "range":
        if not np.isfinite(full_scale_volts) or full_scale_volts <= 0:
            raise ValueError("range WAV conversion requires full_scale_volts > 0")
        out = wav_dir / range_wav_name(run_id, full_scale_volts)
        scaled = data / float(full_scale_volts)
    else:
        raise ValueError(f"unknown scale_mode: {scale_mode}")
    if out.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite existing WAV without explicit overwrite: {out}")
    pcm = np.clip(scaled, -1.0, 1.0)
    pcm16 = np.round(pcm * 32767.0).astype("<i2")
    with wave.open(str(out), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate_hz))
        wf.writeframes(pcm16.tobytes())
    return out


def convert_run_bin(run: dict, session_path: Path, *, overwrite: bool = False) -> dict[str, str]:
    bin_path = session_path / run["files"]["bin"]
    wav_dir = session_path / "wav"
    fs = int(round(float(run["recording"].get("actual_sample_rate_hz") or run["recording"]["sample_rate_hz"])))
    full_scale = float(run["conversion"].get("full_scale_volts", 10.0))
    remove_dc = bool(run["conversion"].get("remove_dc", True))
    files: dict[str, str] = {}
    outputs: dict[str, dict] = {}
    scale_modes = set(run.get("conversion", {}).get("scale_modes") or ["peak", "range"])
    if "peak" in scale_modes:
        peak = convert_bin_to_wav(bin_path, wav_dir, run["run_id"], fs, scale_mode="peak", full_scale_volts=full_scale, remove_dc=remove_dc, overwrite=overwrite)
        files["wav_peak"] = str(peak.relative_to(session_path))
        outputs["wav_peak"] = _conversion_output(files["wav_peak"], "peak", fs, remove_dc)
    if "range" in scale_modes:
        rng = convert_bin_to_wav(bin_path, wav_dir, run["run_id"], fs, scale_mode="range", full_scale_volts=full_scale, remove_dc=remove_dc, overwrite=overwrite)
        files["wav_range"] = str(rng.relative_to(session_path))
        outputs["wav_range"] = _conversion_output(files["wav_range"], "range", fs, remove_dc, full_scale_volts=full_scale)
    run.setdefault("conversion", {})["outputs"] = outputs
    return files


def _conversion_output(path: str, scale_mode: str, sample_rate_hz: int, remove_dc: bool, *, full_scale_volts: float | None = None) -> dict:
    if scale_mode == "peak":
        data = {
            "path": path,
            "scale_mode": "peak",
            "purpose": "listening_preview_only",
            "quantitative_use": "do_not_use_for_final_attenuation",
            "label": "Peak-normalized WAV is for listening and preview only.",
        }
    elif scale_mode == "range":
        data = {
            "path": path,
            "scale_mode": "range",
            "purpose": "cross_check_only",
            "quantitative_use": "cross_check_when_full_scale_voltage_is_known",
            "label": "Range-scaled WAV is a cross-check source only when full-scale voltage is known.",
            "full_scale_volts": full_scale_volts,
        }
    else:
        raise ValueError(f"unknown scale_mode: {scale_mode}")
    data.update({
        "source": "saved_bin_voltage",
        "remove_dc": remove_dc,
        "sample_rate_hz": sample_rate_hz,
        "generated_at": now_iso(),
    })
    return data
