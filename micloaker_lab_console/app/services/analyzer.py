from __future__ import annotations

from pathlib import Path
from typing import Any
import importlib
import wave

import numpy as np

from .raw_bin import read_raw_float64_bin
from .text_store import atomic_write_json, write_csv


def analyze_bin(
    bin_path: Path,
    sample_rate_hz: float,
    *,
    remove_dc: bool = True,
    trim_start_s: float = 0.0,
    trim_end_s: float = 0.0,
    band_hz: tuple[float, float] = (300.0, 3400.0),
    full_scale_volts: float = 10.0,
    expected_duration_s: float | None = None,
) -> dict[str, Any]:
    """Compute report-grade metrics from saved float64 .bin voltage data."""
    raw = read_raw_float64_bin(bin_path)
    return _analyze_voltage(
        raw,
        sample_rate_hz,
        source="bin",
        label="Report-grade metrics recomputed from saved .bin",
        remove_dc=remove_dc,
        trim_start_s=trim_start_s,
        trim_end_s=trim_end_s,
        band_hz=band_hz,
        full_scale_volts=full_scale_volts,
        expected_duration_s=expected_duration_s,
    )


def analyze_range_wav(
    wav_path: Path,
    *,
    full_scale_volts: float,
    remove_dc: bool = True,
    expected_sample_rate_hz: float | None = None,
    trim_start_s: float = 0.0,
    trim_end_s: float = 0.0,
    band_hz: tuple[float, float] = (300.0, 3400.0),
    expected_duration_s: float | None = None,
) -> dict[str, Any]:
    """Compute cross-check metrics from a range-scaled WAV with known full-scale voltage."""
    with wave.open(str(wav_path), "rb") as wf:
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        sample_rate_hz = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
    if sample_width != 2:
        raise ValueError("range WAV cross-check requires 16-bit PCM WAV")
    pcm = np.frombuffer(frames, dtype="<i2").astype(np.float64)
    if channels > 1 and pcm.size:
        pcm = pcm.reshape((-1, channels)).mean(axis=1)
    samples = (pcm / 32767.0) * float(full_scale_volts)
    metrics = _analyze_voltage(
        samples,
        sample_rate_hz,
        source="range_wav",
        label="Cross-check metrics recomputed from range WAV using configured full-scale voltage",
        remove_dc=remove_dc,
        trim_start_s=trim_start_s,
        trim_end_s=trim_end_s,
        band_hz=band_hz,
        full_scale_volts=full_scale_volts,
        expected_duration_s=expected_duration_s,
    )
    if expected_sample_rate_hz and sample_rate_hz != expected_sample_rate_hz:
        metrics["quality_flags"] = sorted(set(metrics["quality_flags"] + ["sample_rate_mismatch"]))
    return metrics


def _analyze_voltage(
    raw: np.ndarray,
    sample_rate_hz: float,
    *,
    source: str,
    label: str,
    remove_dc: bool,
    trim_start_s: float,
    trim_end_s: float,
    band_hz: tuple[float, float],
    full_scale_volts: float,
    expected_duration_s: float | None,
) -> dict[str, Any]:
    flags: list[str] = []
    expected_min = max(1, int(sample_rate_hz * 0.05))
    if raw.size < expected_min:
        flags.append("sample_count_mismatch")
    if expected_duration_s and expected_duration_s > 0:
        expected_samples = int(round(sample_rate_hz * expected_duration_s))
        tolerance = max(1, int(round(expected_samples * 0.01)))
        if abs(raw.size - expected_samples) > tolerance:
            flags.append("sample_count_mismatch")
    start = int(round(trim_start_s * sample_rate_hz))
    end_trim = int(round(trim_end_s * sample_rate_hz))
    end = raw.size - end_trim if end_trim else raw.size
    x = raw[start:end].astype(np.float64)
    if x.size < max(32, sample_rate_hz // 20):
        flags.append("too_short_after_trim")
        x = raw.astype(np.float64)
    trimmed_sample_count = int(x.size)
    dc = float(np.mean(x)) if x.size else 0.0
    if remove_dc:
        x = x - dc
    rms = float(np.sqrt(np.mean(x * x))) if x.size else 0.0
    if rms < 1e-9:
        flags.append("zero_or_near_zero_signal")
    if abs(dc) > max(0.05, rms * 0.25):
        flags.append("dc_offset_large")
    if x.size and np.max(np.abs(raw)) >= 0.98 * full_scale_volts:
        flags.append("clipping_possible")
    nperseg = min(4096, max(256, x.size // 4)) if x.size >= 256 else max(8, x.size)
    freqs, psd = _welch_psd(x, sample_rate_hz, nperseg=nperseg, detrend=False) if x.size else (np.array([]), np.array([]))
    effective_band_hz = _effective_band_for_sample_rate(band_hz, sample_rate_hz)
    if effective_band_hz != (float(band_hz[0]), float(band_hz[1])):
        flags.append("analysis_band_exceeds_nyquist")
    band_power = integrate_band_power(freqs, psd, effective_band_hz)
    default_band_hz = (300.0, 3400.0)
    effective_default_band_hz = _effective_band_for_sample_rate(default_band_hz, sample_rate_hz)
    default_band_power = integrate_band_power(freqs, psd, effective_default_band_hz)
    wide_band = (20.0, 3900.0)
    effective_wide_band_hz = _effective_band_for_sample_rate(wide_band, sample_rate_hz)
    wide_power = integrate_band_power(freqs, psd, effective_wide_band_hz)
    dominant_freq = dominant_frequency(freqs, psd, effective_band_hz)
    dominant_tone_band_hz = (max(0.0, dominant_freq - 50.0), dominant_freq + 50.0) if dominant_freq else (0.0, 0.0)
    dom_power = integrate_band_power(freqs, psd, dominant_tone_band_hz) if dominant_freq else 0.0
    return {
        "source": source,
        "label": label,
        "remove_dc": remove_dc,
        "trim_start_s": float(trim_start_s),
        "trim_end_s": float(trim_end_s),
        "sample_rate_hz": sample_rate_hz,
        "sample_count": int(raw.size),
        "trimmed_sample_count": trimmed_sample_count,
        "expected_sample_count": int(round(sample_rate_hz * expected_duration_s)) if expected_duration_s and expected_duration_s > 0 else None,
        "rms_v": rms,
        "dc_offset_v": dc,
        "band_hz": list(band_hz),
        "effective_band_hz": list(effective_band_hz),
        "band_power": band_power,
        "band_rms_v": power_to_rms(band_power),
        "band_power_300_3400": default_band_power,
        "band_rms_300_3400_v": power_to_rms(default_band_power),
        "wide_band_hz": list(wide_band),
        "effective_band_hz_300_3400": list(effective_default_band_hz),
        "effective_wide_band_hz": list(effective_wide_band_hz),
        "band_power_20_3900": wide_power,
        "band_rms_20_3900_v": power_to_rms(wide_power),
        "dominant_freq_hz": dominant_freq,
        "dominant_tone_band_hz": list(dominant_tone_band_hz),
        "dominant_tone_power_pm50": dom_power,
        "dominant_tone_rms_pm50_v": power_to_rms(dom_power),
        "quality_flags": sorted(set(flags)),
        "psd_freq_hz": freqs.tolist(),
        "psd_v2_per_hz": psd.tolist(),
    }


def integrate_band_power(freqs: np.ndarray, psd: np.ndarray, band_hz: tuple[float, float]) -> float:
    if freqs.size == 0:
        return 0.0
    lo, hi = band_hz
    mask = (freqs >= lo) & (freqs <= hi)
    if not np.any(mask):
        return 0.0
    return float(np.trapezoid(psd[mask], freqs[mask]))


def _welch_psd(x: np.ndarray, sample_rate_hz: float, *, nperseg: int, detrend: bool | str) -> tuple[np.ndarray, np.ndarray]:
    try:
        signal = _load_scipy_signal()
    except ImportError as exc:
        raise RuntimeError(
            "SciPy is required for Welch PSD analysis. Install scipy, then rerun finalization from the saved .bin."
        ) from exc
    return signal.welch(x, fs=sample_rate_hz, nperseg=nperseg, detrend=detrend)


def _load_scipy_signal():
    return importlib.import_module("scipy.signal")


def _effective_band_for_sample_rate(band_hz: tuple[float, float], sample_rate_hz: float) -> tuple[float, float]:
    lo = float(band_hz[0])
    hi = float(band_hz[1])
    nyquist = max(0.0, float(sample_rate_hz) / 2.0)
    if nyquist <= lo:
        return (lo, lo)
    return (lo, min(hi, nyquist))


def power_to_rms(power: float) -> float:
    return float(np.sqrt(max(float(power), 0.0)))


def dominant_frequency(freqs: np.ndarray, psd: np.ndarray, band_hz: tuple[float, float]) -> float:
    if freqs.size == 0:
        return 0.0
    lo, hi = band_hz
    mask = (freqs >= lo) & (freqs <= hi)
    if not np.any(mask):
        return 0.0
    idx = int(np.argmax(psd[mask]))
    return float(freqs[mask][idx])


def save_metrics(session_path: Path, run: dict, metrics: dict[str, Any]) -> None:
    json_path = session_path / run["files"]["metrics_json"]
    csv_path = session_path / run["files"]["metrics_csv"]
    compact = {k: v for k, v in metrics.items() if not k.startswith("psd_")}
    atomic_write_json(json_path, metrics)
    write_csv(csv_path, [compact], list(compact.keys()))


def compare_runs(run0: dict, metrics0: dict[str, Any], run1: dict, metrics1: dict[str, Any]) -> dict[str, Any]:
    return compare_metrics(run0, metrics0, run1, metrics1)


def compare_metrics(
    run0: dict,
    metrics0: dict[str, Any],
    run1: dict,
    metrics1: dict[str, Any],
    *,
    source: str = "bin",
    band_hz: tuple[float, float] = (300.0, 3400.0),
) -> dict[str, Any]:
    p0 = _metric_band_power(metrics0, band_hz)
    p1 = _metric_band_power(metrics1, band_hz)
    warnings: list[str] = []
    for key in ["carrier_freq_khz", "sound_condition", "mic_id", "room", "distance_cm", "angle_deg"]:
        if run0.get("condition", {}).get(key) != run1.get("condition", {}).get(key):
            warnings.append("metadata_mismatch")
            break
    else:
        for key in ["actual_sample_rate_hz", "sample_rate_hz", "ai_range", "input_mode", "channels"]:
            if _recording_compare_value(run0, key) != _recording_compare_value(run1, key):
                warnings.append("metadata_mismatch")
                break
    for metrics in (metrics0, metrics1):
        if metrics.get("quality_flags"):
            warnings.extend(metrics["quality_flags"])
    if source == "range_wav":
        warnings.append("range_wav_cross_check_not_report_grade")
    if source == "peak_wav":
        warnings.append("peak_wav_used_for_quantitative_analysis_warning")
    attenuation = float(10.0 * np.log10(p0 / p1)) if p0 > 0 and p1 > 0 else 0.0
    remaining = float(p1 / p0) if p0 > 0 else 0.0
    return {
        "source": source,
        "band_hz": [float(band_hz[0]), float(band_hz[1])],
        "attenuation_formula": "10*log10(uj0_power/uj1_power)",
        "power_units": "V^2 integrated Welch PSD band power",
        "uj0_run_id": run0["run_id"],
        "uj1_run_id": run1["run_id"],
        "uj0_power": p0,
        "uj1_power": p1,
        "attenuation_db": attenuation,
        "remaining_fraction": remaining,
        "uj0_relative_energy_percent": 100.0,
        "uj1_relative_energy_percent": float(remaining * 100.0),
        "reduction_percent": float((1.0 - remaining) * 100.0),
        "warnings": sorted(set(warnings)),
    }


def _metric_band_power(metrics: dict[str, Any], band_hz: tuple[float, float]) -> float:
    if _same_band(band_hz, (300.0, 3400.0)):
        return float(metrics.get("band_power_300_3400", 0.0))
    if _same_band(band_hz, (20.0, 3900.0)):
        return float(metrics.get("band_power_20_3900", 0.0))
    freqs = np.asarray(metrics.get("psd_freq_hz", []), dtype=np.float64)
    psd = np.asarray(metrics.get("psd_v2_per_hz", []), dtype=np.float64)
    return integrate_band_power(freqs, psd, band_hz)


def _same_band(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return abs(float(a[0]) - b[0]) < 1e-6 and abs(float(a[1]) - b[1]) < 1e-6


def pair_key(run: dict) -> tuple:
    condition = run.get("condition", {})
    recording = run.get("recording", {})
    return (
        condition.get("carrier_freq_khz"),
        condition.get("sound_condition"),
        condition.get("mic_id"),
        condition.get("room"),
        condition.get("distance_cm"),
        condition.get("angle_deg"),
        _recording_compare_value(run, "actual_sample_rate_hz"),
        _recording_compare_value(run, "sample_rate_hz"),
        recording.get("ai_range"),
        recording.get("input_mode"),
        tuple(recording.get("channels", [])),
    )


def _recording_compare_value(run: dict, key: str):
    recording = run.get("recording", {})
    if key == "actual_sample_rate_hz":
        return recording.get("actual_sample_rate_hz", recording.get("sample_rate_hz"))
    if key == "channels":
        return tuple(recording.get("channels", []))
    return recording.get(key)


def auto_pair_runs(runs: list[dict]) -> list[tuple[dict, dict]]:
    """Pair finalized uj0/uj1 runs with matching acquisition metadata."""
    buckets: dict[tuple, dict[str, list[dict]]] = {}
    for run in runs:
        if run.get("analysis", {}).get("status") != "finalized":
            continue
        uj = run.get("condition", {}).get("uj")
        if uj not in {"uj0", "uj1"}:
            continue
        buckets.setdefault(pair_key(run), {"uj0": [], "uj1": []})[uj].append(run)
    pairs: list[tuple[dict, dict]] = []
    for grouped in buckets.values():
        uj0_runs = sorted(grouped["uj0"], key=lambda r: r.get("created_at", ""))
        uj1_runs = sorted(grouped["uj1"], key=lambda r: r.get("created_at", ""))
        pairs.extend(zip(uj0_runs, uj1_runs))
    return pairs
