from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .text_store import (
    append_app_event,
    append_jsonl,
    atomic_write_text,
    atomic_write_json,
    ensure_session_dirs,
    now_iso,
    read_json,
    safe_name,
    session_dir,
    slugify,
    write_csv,
)


def create_session(workspace: Path, title: str, notes: str = "") -> dict[str, Any]:
    stamp = datetime.now().strftime("%y%m%d")
    session_id = _unique_session_id(workspace, f"{stamp}_{slugify(title)}")
    base = session_dir(workspace, session_id)
    ensure_session_dirs(base)
    data = {"session_id": session_id, "title": title, "created_at": now_iso(), "notes": notes}
    atomic_write_json(base / "session.json", data)
    append_jsonl(workspace / ".micloaker" / "sessions.jsonl", {"event": "session_created", "session_id": session_id, "created_at": data["created_at"], "path": f"sessions/{session_id}/session.json"})
    append_jsonl(base / "events.jsonl", {"event": "session_created", "session_id": session_id, "created_at": data["created_at"]})
    append_app_event(workspace, "session_created", session_id=session_id)
    return data


def _unique_session_id(workspace: Path, base_id: str) -> str:
    candidate = safe_name(base_id)
    index = 2
    while (session_dir(workspace, candidate) / "session.json").exists():
        candidate = f"{safe_name(base_id)}_{index:02d}"
        index += 1
    return candidate


def _require_existing_session(base: Path, session_id: str) -> None:
    if not (base / "session.json").is_file():
        raise FileNotFoundError(f"session {session_id} does not exist")


def create_run_metadata(
    workspace: Path,
    session_id: str,
    *,
    carrier_freq_khz: float,
    uj: str,
    sound_condition: str = "sound0",
    mic_id: str = "daq_ch0",
    sample_rate_hz: int = 8000,
    duration_s: float = 1.0,
    source: str = "daq",
    ai_range: str = "BIP10VOLTS",
    input_mode: str = "SINGLE_ENDED",
    channel: int = 0,
    full_scale_volts: float = 10.0,
    scale_mode: str = "both",
    remove_dc: bool = True,
    room: str = "lab",
    distance_cm: float | None = None,
    angle_deg: float = 0.0,
    trim_start_s: float = 0.0,
    trim_end_s: float = 0.0,
    analysis_band_low_hz: float = 300.0,
    analysis_band_high_hz: float = 3400.0,
    safety_operator: str = "",
    safety_max_spl_db: float | None = None,
    safety_notes: str = "",
    mac_helper_file: str = "",
    mac_helper_device_id: int | None = None,
    mac_helper_sample_rate: int | None = None,
    mac_helper_channels: int = 1,
    mac_helper_gain: float = 1.0,
    mac_helper_delay_ms: int = 500,
    notes: str = "",
) -> dict[str, Any]:
    base = session_dir(workspace, session_id)
    _require_existing_session(base, session_id)
    ensure_session_dirs(base)
    stamp = datetime.now().strftime("%y%m%d-%H%M%S")
    freq_tag = _freq_tag(carrier_freq_khz)
    trial = _next_trial(base, freq_tag, uj, sound_condition, mic_id)
    run_id = safe_name(f"{stamp}_{freq_tag}_{uj}_{sound_condition}_{mic_id}_{trial:02d}")
    files = {
        "bin": f"bin/{run_id}.bin",
        "wav_peak": f"wav/{run_id}__scale-peak.wav",
        "wav_range": f"wav/{run_id}__scale-range-fs{full_scale_volts:g}V.wav",
        "metrics_json": f"results/{run_id}_metrics.json",
        "metrics_csv": f"results/{run_id}_metrics.csv",
        "waveform_png": f"plots/{run_id}_waveform.png",
        "waveform_svg": f"plots/{run_id}_waveform.svg",
        "psd_png": f"plots/{run_id}_psd.png",
        "psd_svg": f"plots/{run_id}_psd.svg",
        "spectrogram_png": f"plots/{run_id}_spectrogram.png",
        "spectrogram_svg": f"plots/{run_id}_spectrogram.svg",
    }
    scale_modes = _scale_modes(scale_mode)
    data = {
        "run_id": run_id,
        "session_id": session_id,
        "created_at": now_iso(),
        "condition": {
            "carrier_freq_khz": carrier_freq_khz,
            "uj": uj,
            "sound_condition": sound_condition,
            "mic_id": mic_id,
            "room": room,
            "distance_cm": distance_cm,
            "angle_deg": angle_deg,
            "notes": notes,
        },
        "safety": {
            "operator": safety_operator,
            "max_spl_db": safety_max_spl_db,
            "notes": safety_notes,
        },
        "recording": {
            "source": source,
            "sample_rate_hz": sample_rate_hz,
            "actual_sample_rate_hz": sample_rate_hz,
            "duration_s": duration_s,
            "channels": [channel],
            "input_mode": input_mode,
            "ai_range": ai_range,
            "dtype": "<f8",
            "written_samples": 0,
        },
        "conversion": {"remove_dc": bool(remove_dc), "scale_modes": scale_modes, "full_scale_volts": full_scale_volts},
        "analysis": {
            "status": "pending",
            "source": "bin",
            "preview_only": True,
            "result_grade": "none",
            "finalized_from_saved_bin": False,
            "trim_start_s": trim_start_s,
            "trim_end_s": trim_end_s,
            "primary_band_hz": [analysis_band_low_hz, analysis_band_high_hz],
            "label": "Report-grade metrics are recomputed from saved .bin after recording.",
        },
        "mac_helper": {
            "enabled": False,
            "connected": False,
            "health_ok": False,
            "last_error": "Mac Helper not configured",
            "planned_file": mac_helper_file,
            "planned_device_id": mac_helper_device_id,
            "planned_sample_rate": mac_helper_sample_rate,
            "planned_channels": mac_helper_channels,
            "planned_gain": mac_helper_gain,
            "planned_delay_ms": mac_helper_delay_ms,
        },
        "files": files,
        "quality_flags": [],
    }
    save_run(workspace, data)
    append_jsonl(base / "runs.jsonl", {"event": "run_created", "run_id": run_id, "created_at": data["created_at"], "metadata_path": f"metadata/{run_id}.json"})
    append_jsonl(base / "events.jsonl", {"event": "run_created", "run_id": run_id, "created_at": data["created_at"]})
    append_app_event(workspace, "run_created", session_id=session_id, run_id=run_id, source=source)
    return data


def save_run(workspace: Path, run: dict[str, Any]) -> None:
    base = session_dir(workspace, run["session_id"])
    _require_existing_session(base, run["session_id"])
    ensure_session_dirs(base)
    atomic_write_json(base / "metadata" / f"{run['run_id']}.json", run)


def load_sessions(workspace: Path) -> list[dict[str, Any]]:
    sessions = [_read_json_object(p) for p in (workspace / "sessions").glob("*/session.json")]
    return sorted((item for item in sessions if item), key=lambda r: r.get("created_at", ""), reverse=True)


def load_runs(workspace: Path, session_id: str) -> list[dict[str, Any]]:
    base = session_dir(workspace, session_id)
    runs = [_read_json_object(p) for p in (base / "metadata").glob("*.json")]
    return sorted((item for item in runs if item), key=lambda r: r.get("created_at", ""), reverse=True)


def load_run(workspace: Path, session_id: str, run_id: str) -> dict[str, Any]:
    return read_json(session_dir(workspace, session_id) / "metadata" / f"{safe_name(run_id)}.json")


def rebuild_indexes(workspace: Path) -> dict[str, int]:
    sessions = load_sessions(workspace)
    sessions_index = workspace / ".micloaker" / "sessions.jsonl"
    if sessions_index.exists():
        sessions_index.unlink()
    sessions_index.parent.mkdir(parents=True, exist_ok=True)
    sessions_index.touch()
    run_count = 0
    comparison_count = 0
    for session in sessions:
        sid = session["session_id"]
        append_jsonl(sessions_index, {"event": "session_indexed", "session_id": sid, "created_at": session.get("created_at"), "path": f"sessions/{sid}/session.json"})
        base = session_dir(workspace, sid)
        ensure_session_dirs(base)
        runs_index = base / "runs.jsonl"
        if runs_index.exists():
            runs_index.unlink()
        runs_index.touch()
        events_index = base / "events.jsonl"
        if events_index.exists():
            events_index.unlink()
        append_jsonl(events_index, {"event": "session_indexed", "session_id": sid, "created_at": session.get("created_at"), "path": f"sessions/{sid}/session.json"})
        for run in load_runs(workspace, sid):
            run_count += 1
            append_jsonl(runs_index, {"event": "run_indexed", "run_id": run["run_id"], "created_at": run.get("created_at"), "metadata_path": f"metadata/{run['run_id']}.json"})
            append_jsonl(events_index, {"event": "run_indexed", "run_id": run["run_id"], "created_at": run.get("created_at"), "metadata_path": f"metadata/{run['run_id']}.json"})
            analysis = run.get("analysis", {})
            if analysis.get("status") == "finalized":
                finished_at = analysis.get("finalized_at") or run.get("created_at")
                metrics_path = analysis.get("metrics_path") or run.get("files", {}).get("metrics_json")
                finalized_event = {"event": "run_finalized", "run_id": run["run_id"], "finished_at": finished_at, "metrics_path": metrics_path}
                append_jsonl(runs_index, finalized_event)
                append_jsonl(events_index, finalized_event)
            elif analysis.get("status") == "failed":
                event_name = "run_recording_failed" if analysis.get("failure_stage") == "recording" else "run_finalization_failed"
                recording = run.get("recording", {})
                failed_source = analysis.get("recording_source_attempted") or recording.get("last_attempted_source") or recording.get("source", "")
                failed_event = {
                    "event": event_name,
                    "run_id": run["run_id"],
                    "source": failed_source,
                    "failed_at": analysis.get("failed_at") or run.get("created_at"),
                    "error": analysis.get("last_error", ""),
                    "error_log": analysis.get("error_log", f"logs/{run['run_id']}.log"),
                }
                append_jsonl(runs_index, failed_event)
                append_jsonl(events_index, failed_event)
        for comparison_path in sorted((base / "comparisons").glob("*.json")):
            comparison = _read_json_object(comparison_path)
            if not comparison:
                continue
            comparison_count += 1
            append_jsonl(events_index, {
                "event": "comparison_indexed",
                "compare_id": comparison.get("compare_id") or comparison_path.stem,
                "created_at": comparison.get("created_at"),
                "source": comparison.get("source"),
                "uj0_run_id": comparison.get("uj0_run_id"),
                "uj1_run_id": comparison.get("uj1_run_id"),
                "path": f"comparisons/{comparison_path.name}",
            })
        regenerate_summary(workspace, sid)
    counts = {"sessions": len(sessions), "runs": run_count, "comparisons": comparison_count}
    append_app_event(workspace, "indexes_rebuilt", **counts)
    return counts


def regenerate_summary(workspace: Path, session_id: str) -> Path:
    rows = []
    for run in load_runs(workspace, session_id):
        rows.append(_summary_row(workspace, session_id, run))
    path = session_dir(workspace, session_id) / "summary.csv"
    write_csv(path, rows, _SUMMARY_FIELDS)
    regenerate_session_report(workspace, session_id, rows)
    return path


def regenerate_session_report(workspace: Path, session_id: str, rows: list[dict[str, Any]] | None = None) -> Path:
    base = session_dir(workspace, session_id)
    session = read_json(base / "session.json")
    if rows is None:
        rows = [_summary_row(workspace, session_id, run) for run in load_runs(workspace, session_id)]
    comparisons = []
    for path in sorted((base / "comparisons").glob("*.json")):
        comparison = _read_json_object(path)
        if comparison:
            comparisons.append(comparison)
    lines = [
        f"# MiCloaker Session Report: {session_id}",
        "",
        f"- Title: {session.get('title', '')}",
        f"- Created: {session.get('created_at', '')}",
        f"- Notes: {session.get('notes', '')}",
        "",
        "Final metrics in this report are report-grade only when the run analysis status is `finalized`; they are recomputed from saved raw `.bin` voltage files.",
        "",
        "## Data Source Notes",
        "",
        "- Saved `.bin` float64 voltage data is the primary quantitative source.",
        "- Peak-normalized WAV files are listening/preview only and must not be used for final attenuation reporting.",
        "- Range WAV files are cross-check sources only when full-scale voltage is known.",
        "- Saved comparison rows marked report-grade use saved `.bin` metrics; range WAV comparisons are cross-check only.",
        "",
        "| Run | UJ | Status | Grade | Remove DC | Trim S | Samples | Trimmed Samples | RMS V | Primary Band Hz | Effective Band Hz | Primary Band RMS V | Primary Band Power | 300-3400 Hz RMS V | 300-3400 Hz Power | Dominant Hz | Dominant Tone Band Hz | Quality Flags | Analysis Error |",
        "|---|---:|---|---|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {_md_cell(row.get('run_id', ''))} | {_md_cell(row.get('uj', ''))} | {_md_cell(row.get('analysis_status', ''))} | {_md_cell(row.get('result_grade', ''))} | "
            f"{_md_cell(row.get('remove_dc', ''))} | {_md_cell(row.get('trim_window_s', ''))} | {_md_cell(row.get('sample_count', ''))} | {_md_cell(row.get('trimmed_sample_count', ''))} | "
            f"{_md_cell(row.get('rms_v', ''))} | {_md_cell(row.get('primary_band_hz', ''))} | {_md_cell(row.get('effective_primary_band_hz', ''))} | "
            f"{_md_cell(row.get('primary_band_rms_v', ''))} | {_md_cell(row.get('primary_band_power', ''))} | "
            f"{_md_cell(row.get('band_rms_300_3400_v', ''))} | {_md_cell(row.get('band_power_300_3400', ''))} | {_md_cell(row.get('dominant_freq_hz', ''))} | "
            f"{_md_cell(row.get('dominant_tone_band_hz', ''))} | {_md_cell(row.get('quality_flags', ''))} | {_md_cell(row.get('analysis_error', ''))} |"
        )
    lines.extend([
        "",
        "## Saved Comparisons",
        "",
        "| Source | Grade | Source Label | Formula | Power Units | Band Hz | UJ0 Run | UJ1 Run | Attenuation dB | Remaining Fraction | Reduction Percent | Warnings |",
        "|---|---|---|---|---|---|---|---|---:|---:|---:|---|",
    ])
    if comparisons:
        for item in comparisons:
            lines.append(
                f"| {_md_cell(item.get('source', ''))} | {_md_cell(item.get('result_grade', ''))} | {_md_cell(item.get('source_label', ''))} | "
                f"{_md_cell(item.get('attenuation_formula', ''))} | {_md_cell(item.get('power_units', ''))} | {_md_cell(item.get('band_hz', ''))} | "
                f"{_md_cell(item.get('uj0_run_id', ''))} | {_md_cell(item.get('uj1_run_id', ''))} | "
                f"{_md_cell(item.get('attenuation_db', ''))} | {_md_cell(item.get('remaining_fraction', ''))} | {_md_cell(item.get('reduction_percent', ''))} | "
                f"{_md_cell(', '.join(item.get('warnings', [])))} |"
            )
    else:
        lines.append("|  |  |  |  |  |  |  |  |  |  |  | No saved comparisons. |")
    path = base / "session_report.md"
    atomic_write_text(path, "\n".join(lines) + "\n")
    return path


_SUMMARY_FIELDS = [
    "run_id",
    "uj",
    "source",
    "analysis_status",
    "result_grade",
    "quality_flags",
    "analysis_error",
    "remove_dc",
    "trim_start_s",
    "trim_end_s",
    "trim_window_s",
    "sample_count",
    "trimmed_sample_count",
    "rms_v",
    "primary_band_hz",
    "effective_primary_band_hz",
    "primary_band_rms_v",
    "primary_band_power",
    "band_rms_300_3400_v",
    "band_power_300_3400",
    "dominant_freq_hz",
    "dominant_tone_band_hz",
]


def _summary_row(workspace: Path, session_id: str, run: dict[str, Any]) -> dict[str, Any]:
    metrics = {}
    metrics_path = session_dir(workspace, session_id) / run["files"].get("metrics_json", "")
    if metrics_path.exists():
        metrics = _read_json_object(metrics_path) or {}
    return {
        "run_id": run["run_id"],
        "uj": run["condition"].get("uj"),
        "source": run["recording"].get("source"),
        "analysis_status": run["analysis"].get("status"),
        "result_grade": run["analysis"].get("result_grade", ""),
        "quality_flags": ";".join(run.get("quality_flags", [])),
        "analysis_error": run["analysis"].get("last_error", ""),
        "remove_dc": metrics.get("remove_dc", run.get("conversion", {}).get("remove_dc", "")),
        "trim_start_s": metrics.get("trim_start_s", run.get("analysis", {}).get("trim_start_s", "")),
        "trim_end_s": metrics.get("trim_end_s", run.get("analysis", {}).get("trim_end_s", "")),
        "trim_window_s": [metrics.get("trim_start_s", run.get("analysis", {}).get("trim_start_s", "")), metrics.get("trim_end_s", run.get("analysis", {}).get("trim_end_s", ""))],
        "sample_count": metrics.get("sample_count", run.get("recording", {}).get("raw_sample_count", "")),
        "trimmed_sample_count": metrics.get("trimmed_sample_count", ""),
        "rms_v": metrics.get("rms_v", ""),
        "primary_band_hz": metrics.get("band_hz", run.get("analysis", {}).get("primary_band_hz", "")),
        "effective_primary_band_hz": metrics.get("effective_band_hz", metrics.get("band_hz", run.get("analysis", {}).get("primary_band_hz", ""))),
        "primary_band_rms_v": metrics.get("band_rms_v", ""),
        "primary_band_power": metrics.get("band_power", ""),
        "band_rms_300_3400_v": metrics.get("band_rms_300_3400_v", ""),
        "band_power_300_3400": metrics.get("band_power_300_3400", ""),
        "dominant_freq_hz": metrics.get("dominant_freq_hz", ""),
        "dominant_tone_band_hz": metrics.get("dominant_tone_band_hz", ""),
    }


def _md_cell(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        data = read_json(path)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _freq_tag(freq: float) -> str:
    if float(freq) == 0:
        return "r0"
    if float(freq).is_integer():
        return f"r{int(freq)}k"
    text = str(freq).replace(".", "k")
    return f"r{text}"


def _scale_modes(scale_mode: str) -> list[str]:
    if scale_mode == "peak":
        return ["peak"]
    if scale_mode == "range":
        return ["range"]
    return ["peak", "range"]


def _next_trial(base: Path, freq_tag: str, uj: str, sound: str, mic: str) -> int:
    stem = safe_name(f"{freq_tag}_{uj}_{sound}_{mic}")
    count = sum(1 for p in (base / "metadata").glob(f"*_{stem}_*.json"))
    return count + 1
