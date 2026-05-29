from __future__ import annotations

from pathlib import Path
import shutil
import threading
import traceback

from . import analyzer, converter, plotting
from .daq import DaqNotConfiguredError, DaqUnavailableError, record_voltage
from .jobs import run_job
from .metadata import regenerate_summary, save_run
from .mock_daq import generate_mock_voltage
from .raw_bin import RawBinValidationError, validate_raw_float64_bin
from .text_store import append_app_event, append_jsonl, append_log, now_iso, session_dir

_recording_lock = threading.Lock()
_active_recording: dict | None = None


class RecordingBusyError(RuntimeError):
    pass


def recording_status() -> dict:
    return {"active": _active_recording is not None, "recording": _active_recording}


def record_mock_and_finalize(workspace: Path, run: dict) -> dict:
    global _active_recording
    base = session_dir(workspace, run["session_id"])
    bin_path = base / run["files"]["bin"]
    log_path = base / "logs" / f"{run['run_id']}.log"
    if bin_path.exists():
        raise FileExistsError(f"refusing to overwrite raw bin: {bin_path}")
    if not _recording_lock.acquire(blocking=False):
        raise RecordingBusyError("another recording is already active")
    _active_recording = {"session_id": run["session_id"], "run_id": run["run_id"], "source": "mock", "started_at": now_iso()}

    def _work() -> dict:
        data = generate_mock_voltage(
            int(run["recording"]["sample_rate_hz"]),
            float(run["recording"]["duration_s"]),
            run["condition"].get("uj", "uj0"),
            float(run["condition"].get("carrier_freq_khz", 25.0)),
        )
        bin_path.parent.mkdir(parents=True, exist_ok=True)
        data.tofile(bin_path)
        run["recording"]["source"] = "mock"
        run["recording"]["actual_sample_rate_hz"] = int(run["recording"]["sample_rate_hz"])
        run["recording"]["written_samples"] = int(data.size)
        run["recording"]["finished_at"] = now_iso()
        save_run(workspace, run)
        append_log(log_path, f"wrote raw float64 bin {bin_path.name} samples={data.size}")
        _finalize_after_capture(workspace, run, trigger="recording_finished")
        return run

    try:
        return run_job(workspace, "mock_record_and_finalize", log_path, _work)
    finally:
        _active_recording = None
        _recording_lock.release()


def import_bin_and_finalize(workspace: Path, run: dict, source_path: Path) -> dict:
    base = session_dir(workspace, run["session_id"])
    bin_path = base / run["files"]["bin"]
    log_path = base / "logs" / f"{run['run_id']}.log"

    def _work() -> dict:
        if bin_path.exists():
            raise FileExistsError(f"refusing to overwrite raw bin: {bin_path}")
        validate_raw_bin_source(source_path)
        bin_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, bin_path)
        written_samples = bin_path.stat().st_size // 8
        run["recording"]["source"] = "upload"
        run["recording"]["actual_sample_rate_hz"] = int(run["recording"]["sample_rate_hz"])
        run["recording"]["written_samples"] = int(written_samples)
        run["recording"]["finished_at"] = now_iso()
        save_run(workspace, run)
        append_log(log_path, f"imported raw float64 bin {source_path.name} samples={written_samples}")
        _finalize_after_capture(workspace, run, trigger="upload_imported")
        return run

    return run_job(workspace, "upload_import_and_finalize", log_path, _work)


def validate_raw_bin_source(source_path: Path) -> dict:
    """Validate an uploaded/imported raw float64 voltage `.bin` before persistence."""
    if source_path.suffix.lower() != ".bin":
        raise ValueError("uploaded raw data must use a .bin extension")
    try:
        return validate_raw_float64_bin(source_path, source_label="uploaded raw .bin", require_suffix=False)
    except FileNotFoundError as exc:
        raise ValueError("uploaded raw data file was not found") from exc
    except RawBinValidationError as exc:
        raise ValueError(str(exc)) from exc


def record_daq_and_finalize(workspace: Path, run: dict) -> dict:
    global _active_recording
    base = session_dir(workspace, run["session_id"])
    bin_path = base / run["files"]["bin"]
    log_path = base / "logs" / f"{run['run_id']}.log"
    if bin_path.exists():
        raise FileExistsError(f"refusing to overwrite raw bin: {bin_path}")
    if not _recording_lock.acquire(blocking=False):
        raise RecordingBusyError("another recording is already active")
    _active_recording = {"session_id": run["session_id"], "run_id": run["run_id"], "source": "daq", "started_at": now_iso()}

    def _work() -> dict:
        try:
            source_channels = _daq_source_channels(run)
            recorded_channel = source_channels[0]
            data_result = record_voltage(
                sample_rate_hz=int(run["recording"]["sample_rate_hz"]),
                duration_s=float(run["recording"]["duration_s"]),
                channels=source_channels,
                input_mode=run["recording"].get("input_mode", "SINGLE_ENDED"),
                ai_range=run["recording"].get("ai_range", "BIP10VOLTS"),
            )
        except (DaqUnavailableError, DaqNotConfiguredError) as exc:
            mark_recording_failed(workspace, run, source="daq", exc=exc)
            raise
        if isinstance(data_result, tuple):
            data, actual_rate = data_result
        else:
            data, actual_rate = data_result, run["recording"]["sample_rate_hz"]
        bin_path.parent.mkdir(parents=True, exist_ok=True)
        data.astype("<f8", copy=False).tofile(bin_path)
        run["recording"]["source"] = "daq"
        run["recording"]["source_channels"] = source_channels
        run["recording"]["recorded_channel"] = recorded_channel
        run["recording"]["recorded_channel_count"] = 1
        run["recording"]["actual_sample_rate_hz"] = actual_rate
        run["recording"]["written_samples"] = int(data.size)
        run["recording"]["finished_at"] = now_iso()
        save_run(workspace, run)
        append_log(log_path, f"wrote DAQ raw float64 bin {bin_path.name} samples={data.size} source_channels={source_channels} recorded_channel={recorded_channel}")
        _finalize_after_capture(workspace, run, trigger="recording_finished")
        return run

    try:
        return run_job(workspace, "daq_record_and_finalize", log_path, _work)
    finally:
        _active_recording = None
        _recording_lock.release()


def _daq_source_channels(run: dict) -> list[int]:
    channels = [int(channel) for channel in run.get("recording", {}).get("channels", [0])]
    if not channels:
        raise DaqNotConfiguredError("DAQ recording requires at least one source channel.")
    return channels


def mark_recording_failed(workspace: Path, run: dict, *, source: str, exc: Exception) -> None:
    base = session_dir(workspace, run["session_id"])
    log_path = base / "logs" / f"{run['run_id']}.log"
    failed_at = now_iso()
    run.setdefault("recording", {})["last_attempted_source"] = source
    run.setdefault("analysis", {}).update({
        "status": "failed",
        "source": "bin",
        "preview_only": True,
        "result_grade": "none",
        "finalized_from_saved_bin": False,
        "failure_stage": "recording",
        "recording_source_attempted": source,
        "failed_at": failed_at,
        "last_error": str(exc),
        "error_log": f"logs/{run['run_id']}.log",
        "label": f"{source.upper()} recording failed before raw .bin capture; use mock/upload or fix DAQ setup and retry with a new run.",
    })
    flags = set(run.get("quality_flags", []))
    flags.add("recording_failed")
    run["quality_flags"] = sorted(flags)
    save_run(workspace, run)
    event = {"event": "run_recording_failed", "run_id": run["run_id"], "source": source, "failed_at": failed_at, "error": str(exc), "error_log": f"logs/{run['run_id']}.log"}
    append_jsonl(base / "runs.jsonl", event)
    append_jsonl(base / "events.jsonl", event)
    append_app_event(workspace, "run_recording_failed", session_id=run["session_id"], run_id=run["run_id"], source=source, error=str(exc))
    append_log(log_path, f"recording_failed source={source} metadata_saved=true: {exc}")


def finalize_run(workspace: Path, run: dict, *, trigger: str = "manual", overwrite_derived: bool = False) -> dict:
    base = session_dir(workspace, run["session_id"])
    log_path = base / "logs" / f"{run['run_id']}.log"
    bin_path = base / run["files"]["bin"]
    fs = float(run["recording"].get("actual_sample_rate_hz") or run["recording"]["sample_rate_hz"])
    append_log(log_path, "finalization_started source=bin")
    raw_info = validate_raw_float64_bin(bin_path, source_label="saved raw .bin")
    run.setdefault("recording", {}).update({
        "raw_size_bytes": raw_info["size_bytes"],
        "raw_sample_count": raw_info["sample_count"],
        "raw_dtype": raw_info["dtype"],
        "raw_validated_at": now_iso(),
    })
    _ensure_metrics_outputs_available(base, run, overwrite=overwrite_derived)
    wavs = converter.convert_run_bin(run, base, overwrite=overwrite_derived)
    run["files"].update(wavs)
    remove_dc = bool(run["conversion"].get("remove_dc", True))
    band = run.get("analysis", {}).get("primary_band_hz", [300.0, 3400.0])
    band_hz = (float(band[0]), float(band[1])) if len(band) == 2 else (300.0, 3400.0)
    metrics = analyzer.analyze_bin(
        bin_path,
        fs,
        remove_dc=remove_dc,
        trim_start_s=float(run["analysis"].get("trim_start_s", 0.0)),
        trim_end_s=float(run["analysis"].get("trim_end_s", 0.0)),
        band_hz=band_hz,
        full_scale_volts=float(run["conversion"].get("full_scale_volts", 10.0)),
        expected_duration_s=float(run["recording"].get("duration_s", 0.0)),
    )
    quality_flags = list(metrics["quality_flags"])
    plot_error = None
    try:
        plot_files = plotting.plot_run(
            bin_path,
            fs,
            base / "plots",
            run["run_id"],
            band_hz=band_hz,
            remove_dc=remove_dc,
            trim_start_s=float(run["analysis"].get("trim_start_s", 0.0)),
            trim_end_s=float(run["analysis"].get("trim_end_s", 0.0)),
            overwrite=overwrite_derived,
        )
        run["files"].update(plot_files)
    except Exception as exc:
        plot_error = str(exc)
        quality_flags.append("plot_generation_failed")
        append_log(log_path, f"plot_generation_failed metrics_saved=true: {exc}\n{traceback.format_exc()}")
        append_app_event(workspace, "plot_generation_failed", session_id=run["session_id"], run_id=run["run_id"], error=plot_error)
    run["quality_flags"] = sorted(set(quality_flags))
    finalized_at = now_iso()
    metrics.update({
        "result_grade": "report-grade",
        "preview_only": False,
        "finalized_from_saved_bin": True,
        "finalization_trigger": trigger,
        "finalized_at": finalized_at,
        "metrics_source": "saved_raw_bin",
        "raw_bin_path": run["files"]["bin"],
        "raw_size_bytes": run["recording"].get("raw_size_bytes"),
        "raw_sample_count": run["recording"].get("raw_sample_count"),
        "raw_dtype": run["recording"].get("raw_dtype") or run["recording"].get("dtype"),
        "quality_flags": run["quality_flags"],
    })
    if plot_error:
        metrics["plot_error"] = plot_error
    analyzer.save_metrics(base, run, metrics)
    run["analysis"].update({
        "status": "finalized",
        "source": "bin",
        "preview_only": False,
        "result_grade": "report-grade",
        "finalized_from_saved_bin": True,
        "finalization_trigger": trigger,
        "finalized_at": finalized_at,
        "metrics_path": run["files"]["metrics_json"],
        "label": "Report-grade metrics recomputed from saved .bin",
    })
    for stale_key in ["failed_at", "last_error", "error_log", "plot_error"]:
        run["analysis"].pop(stale_key, None)
    if plot_error:
        run["analysis"]["plot_error"] = plot_error
    save_run(workspace, run)
    regenerate_summary(workspace, run["session_id"])
    append_jsonl(base / "runs.jsonl", {"event": "run_finalized", "run_id": run["run_id"], "finished_at": finalized_at, "metrics_path": run["files"]["metrics_json"]})
    append_jsonl(base / "events.jsonl", {"event": "run_finalized", "run_id": run["run_id"], "finished_at": finalized_at})
    append_app_event(workspace, "run_finalized", session_id=run["session_id"], run_id=run["run_id"], trigger=trigger, metrics_path=run["files"]["metrics_json"])
    append_log(log_path, "finalization_finished metrics=report-grade")
    return run


def _ensure_metrics_outputs_available(base: Path, run: dict, *, overwrite: bool) -> None:
    if overwrite:
        return
    existing = []
    for key in ["metrics_json", "metrics_csv"]:
        rel = run.get("files", {}).get(key)
        if rel and (base / rel).exists():
            existing.append(rel)
    if existing:
        raise FileExistsError(f"refusing to overwrite existing metrics without explicit overwrite: {', '.join(existing)}")


def finalize_run_with_failure_state(workspace: Path, run: dict, *, trigger: str, failure_label: str | None = None) -> dict:
    try:
        return finalize_run(workspace, run, trigger=trigger)
    except Exception as exc:
        mark_finalization_failed(workspace, run, trigger=trigger, exc=exc, failure_label=failure_label)
        raise


def _finalize_after_capture(workspace: Path, run: dict, *, trigger: str) -> dict:
    return finalize_run_with_failure_state(
        workspace,
        run,
        trigger=trigger,
        failure_label="Finalization failed after raw .bin capture; inspect run log and retry from saved .bin.",
    )


def mark_finalization_failed(workspace: Path, run: dict, *, trigger: str, exc: Exception, failure_label: str | None = None) -> None:
    base = session_dir(workspace, run["session_id"])
    log_path = base / "logs" / f"{run['run_id']}.log"
    failed_at = now_iso()
    run.setdefault("analysis", {}).update({
        "status": "failed",
        "source": "bin",
        "preview_only": True,
        "result_grade": "none",
        "finalized_from_saved_bin": False,
        "finalization_trigger": trigger,
        "failed_at": failed_at,
        "last_error": str(exc),
        "error_log": f"logs/{run['run_id']}.log",
        "label": failure_label or "Finalization failed; inspect run log and retry from saved .bin.",
    })
    flags = set(run.get("quality_flags", []))
    flags.add("finalization_failed")
    run["quality_flags"] = sorted(flags)
    save_run(workspace, run)
    append_jsonl(base / "events.jsonl", {"event": "run_finalization_failed", "run_id": run["run_id"], "failed_at": failed_at, "error": str(exc)})
    append_app_event(workspace, "run_finalization_failed", session_id=run["session_id"], run_id=run["run_id"], trigger=trigger, error=str(exc))
    append_log(log_path, f"finalization_failed metadata_saved=true: {exc}")
