from __future__ import annotations

import wave
from urllib.parse import urlencode

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from ..services.analyzer import analyze_range_wav, auto_pair_runs, compare_metrics
from ..services.metadata import load_run, load_runs, load_sessions, regenerate_session_report
from ..services.plotting import plot_compare, plot_psd_overlay
from ..services.text_store import append_app_event, append_jsonl, atomic_write_json, now_iso, read_json, read_json_or_default, safe_name, session_dir, write_csv

router = APIRouter(prefix="/compare", tags=["compare"])


@router.get("")
def compare_index(request: Request):
    workspace = request.app.state.settings.workspace
    sessions = []
    for session in load_sessions(workspace):
        runs = load_runs(workspace, session["session_id"])
        sessions.append({
            **session,
            "run_count": len(runs),
            "finalized_count": sum(1 for run in runs if run.get("analysis", {}).get("status") == "finalized"),
            "uj0_count": sum(1 for run in runs if run.get("condition", {}).get("uj") == "uj0"),
            "uj1_count": sum(1 for run in runs if run.get("condition", {}).get("uj") == "uj1"),
        })
    return request.app.state.templates.TemplateResponse(
        name="compare_index.html",
        request=request,
        context={"sessions": sessions},
    )


@router.get("/{session_id}")
def compare_page(request: Request, session_id: str):
    workspace = request.app.state.settings.workspace
    _require_session(workspace, session_id)
    base = session_dir(workspace, session_id)
    runs = load_runs(workspace, session_id)
    finalized_uj0_runs = [run for run in runs if run.get("condition", {}).get("uj") == "uj0" and run.get("analysis", {}).get("status") == "finalized"]
    finalized_uj1_runs = [run for run in runs if run.get("condition", {}).get("uj") == "uj1" and run.get("analysis", {}).get("status") == "finalized"]
    comparisons = []
    for path in sorted((base / "comparisons").glob("*.json"), key=_comparison_sort_key, reverse=True):
        result = read_json_or_default(path, {})
        if not result:
            continue
        _decorate_comparison(result)
        result["json_file"] = f"comparisons/{path.name}"
        result["csv_file"] = f"comparisons/{path.with_suffix('.csv').name}"
        comparisons.append(result)
    return request.app.state.templates.TemplateResponse(
        name="compare.html",
        request=request,
        context={
            "session_id": session_id,
            "runs": runs,
            "finalized_uj0_runs": finalized_uj0_runs,
            "finalized_uj1_runs": finalized_uj1_runs,
            "comparisons": comparisons,
            "compare_alert": _alert_from_query(request),
        },
    )


@router.post("/{session_id}")
def compare_submit(
    request: Request,
    session_id: str,
    uj0_run_id: str = Form(...),
    uj1_run_id: str = Form(...),
    source: str = Form("bin"),
    band_mode: str = Form("primary"),
    custom_low_hz: float | None = Form(None),
    custom_high_hz: float | None = Form(None),
):
    workspace = request.app.state.settings.workspace
    _require_session(workspace, session_id)
    _require_run(workspace, session_id, uj0_run_id)
    _require_run(workspace, session_id, uj1_run_id)
    base = session_dir(workspace, session_id)
    run0 = load_run(workspace, session_id, uj0_run_id)
    run1 = load_run(workspace, session_id, uj1_run_id)
    try:
        _validate_compare_runs(run0, run1)
        band_hz = _band_from_form(band_mode, custom_low_hz, custom_high_hz)
        _validate_band_with_sample_rates(run0, run1, band_hz)
        metrics0, metrics1 = _load_compare_metrics(base, run0, run1, source, band_hz)
        _save_compare(workspace, session_id, base, run0, metrics0, run1, metrics1, source=source, band_hz=band_hz)
    except HTTPException as exc:
        return _compare_error_redirect(session_id, exc.detail)
    return RedirectResponse(f"/compare/{session_id}?notice=compare_saved", status_code=303)


@router.post("/{session_id}/auto-pair")
def compare_auto_pair(request: Request, session_id: str):
    workspace = request.app.state.settings.workspace
    _require_session(workspace, session_id)
    base = session_dir(workspace, session_id)
    runs = load_runs(workspace, session_id)
    try:
        created = 0
        for run0, run1 in auto_pair_runs(runs):
            metrics0 = _read_metrics_json(base, run0)
            metrics1 = _read_metrics_json(base, run1)
            _save_compare(workspace, session_id, base, run0, metrics0, run1, metrics1)
            created += 1
    except HTTPException as exc:
        return _compare_error_redirect(session_id, exc.detail)
    notice = "auto_pair_saved" if created else "auto_pair_none"
    return RedirectResponse(f"/compare/{session_id}?notice={notice}", status_code=303)


def _save_compare(workspace, session_id: str, base, run0: dict, metrics0: dict, run1: dict, metrics1: dict, *, source: str = "bin", band_hz: tuple[float, float] = (300.0, 3400.0)) -> dict:
    result = compare_metrics(run0, metrics0, run1, metrics1, source=source, band_hz=band_hz)
    result["created_at"] = now_iso()
    result.update(_comparison_provenance(source))
    result.update(_comparison_source_paths(run0, run1, source))
    _decorate_comparison(result)
    band_tag = f"{int(band_hz[0])}-{int(band_hz[1])}"
    base_compare_id = f"{run0['run_id']}__vs__{run1['run_id']}__{source}__{band_tag}Hz"
    compare_id = _unique_compare_id(base / "comparisons", base_compare_id)
    result["compare_id"] = compare_id
    plots = {}
    plots.update(plot_compare(result, base / "comparisons", compare_id))
    plots.update(plot_psd_overlay(metrics0, metrics1, base / "comparisons", compare_id, band_hz=band_hz))
    result["plots"] = plots
    atomic_write_json(base / "comparisons" / f"{compare_id}.json", result)
    csv_row = {**result, "warnings": ";".join(result.get("warnings", []))}
    write_csv(
        base / "comparisons" / f"{compare_id}.csv",
        [csv_row],
        [
            "compare_id",
            "created_at",
            "source",
            "source_label",
            "result_grade",
            "attenuation_formula",
            "power_units",
            "uj0_source_path",
            "uj1_source_path",
            "uj0_metrics_path",
            "uj1_metrics_path",
            "band_hz",
            "uj0_run_id",
            "uj1_run_id",
            "uj0_power",
            "uj1_power",
            "uj0_relative_energy_percent",
            "uj1_relative_energy_percent",
            "attenuation_db",
            "remaining_fraction",
            "reduction_percent",
            "warnings",
        ],
    )
    append_jsonl(base / "events.jsonl", {"event": "comparison_created", "compare_id": compare_id, "source": source, "uj0_run_id": run0["run_id"], "uj1_run_id": run1["run_id"]})
    append_app_event(workspace, "comparison_created", session_id=session_id, compare_id=compare_id, source=source, uj0_run_id=run0["run_id"], uj1_run_id=run1["run_id"])
    regenerate_session_report(workspace, session_id)
    return result


def _comparison_source_paths(run0: dict, run1: dict, source: str) -> dict[str, str]:
    if source == "bin":
        return {
            "uj0_source_path": str(run0.get("files", {}).get("bin", "")),
            "uj1_source_path": str(run1.get("files", {}).get("bin", "")),
            "uj0_metrics_path": str(run0.get("files", {}).get("metrics_json", "")),
            "uj1_metrics_path": str(run1.get("files", {}).get("metrics_json", "")),
        }
    if source == "range_wav":
        return {
            "uj0_source_path": str(run0.get("files", {}).get("wav_range", "")),
            "uj1_source_path": str(run1.get("files", {}).get("wav_range", "")),
            "uj0_metrics_path": "",
            "uj1_metrics_path": "",
        }
    return {
        "uj0_source_path": "",
        "uj1_source_path": "",
        "uj0_metrics_path": "",
        "uj1_metrics_path": "",
    }


def _comparison_provenance(source: str) -> dict:
    if source == "bin":
        return {
            "result_grade": "report-grade",
            "source_label": "Report-grade comparison from saved .bin voltage metrics.",
        }
    if source == "range_wav":
        return {
            "result_grade": "cross-check",
            "source_label": "Range WAV comparison is a cross-check only when full-scale voltage is known.",
        }
    return {
        "result_grade": "not-report-grade",
        "source_label": "This source is not valid for final attenuation reporting.",
    }


def _decorate_comparison(result: dict) -> dict:
    result["uj0_relative_energy_percent"] = 100.0
    remaining = float(result.get("remaining_fraction", 0.0) or 0.0)
    result["uj1_relative_energy_percent"] = remaining * 100.0
    result["warning_messages"] = [_friendly_warning_message(warning) for warning in result.get("warnings", [])]
    return result


def _friendly_warning_message(warning: str) -> str:
    messages = {
        "range_wav_cross_check_not_report_grade": "Range WAV was used only as a cross-check. It is not report-grade because WAV scaling depends on the configured full-scale voltage. Use BIN primary for final attenuation.",
        "peak_wav_used_for_quantitative_analysis_warning": "Peak-normalized WAV is for listening only and cannot be used for attenuation reporting.",
        "metadata_mismatch": "The selected uj0/uj1 runs have different metadata. Check frequency, ordinary sound, mic, room, distance, angle, DAQ range, and sample rate before trusting the comparison.",
    }
    return messages.get(warning, warning.replace("_", " "))


def _validate_compare_runs(run0: dict, run1: dict) -> None:
    if run0["run_id"] == run1["run_id"]:
        raise HTTPException(
            status_code=400,
            detail=_compare_error(
                "INVALID_COMPARE_PAIR",
                "Choose distinct uj0 and uj1 runs.",
                "Select one finalized uj0 run and one finalized uj1 run from the same session.",
            ),
        )
    if run0.get("condition", {}).get("uj") != "uj0" or run1.get("condition", {}).get("uj") != "uj1":
        raise HTTPException(
            status_code=400,
            detail=_compare_error(
                "INVALID_COMPARE_PAIR",
                "Compare requires the first run to be uj0 and the second run to be uj1.",
                "Use the uj0 selector for the baseline run and the uj1 selector for the jammed run.",
            ),
        )
    for run in (run0, run1):
        if run.get("analysis", {}).get("status") != "finalized":
            raise HTTPException(
                status_code=400,
                detail=_compare_error(
                    "RUN_NOT_FINALIZED",
                    f"Run {run['run_id']} must be finalized before comparison.",
                    "Record or finalize the run so report-grade metrics are recomputed from the saved .bin first.",
                ),
            )


def _unique_compare_id(comparisons_dir, base_id: str) -> str:
    candidate = base_id
    index = 2
    suffixes = [".json", ".csv", "_attenuation.png", "_attenuation.svg", "_psd_overlay.png", "_psd_overlay.svg"]
    while any((comparisons_dir / f"{candidate}{suffix}").exists() for suffix in suffixes):
        candidate = f"{base_id}_{index:02d}"
        index += 1
    return candidate


def _band_from_form(band_mode: str, custom_low_hz: float | None, custom_high_hz: float | None) -> tuple[float, float]:
    if band_mode == "primary":
        return (300.0, 3400.0)
    if band_mode == "wide":
        return (20.0, 3900.0)
    if band_mode == "custom":
        if custom_low_hz is None or custom_high_hz is None or custom_low_hz <= 0 or custom_high_hz <= custom_low_hz:
            raise HTTPException(
                status_code=400,
                detail=_compare_error(
                    "INVALID_COMPARE_BAND",
                    "Custom band requires low_hz > 0 and high_hz > low_hz.",
                    "Use the default 300-3400 Hz band, the wide 20-3900 Hz band, or enter a valid custom range.",
                ),
            )
        return (float(custom_low_hz), float(custom_high_hz))
    raise HTTPException(
        status_code=400,
        detail=_compare_error(
            "INVALID_COMPARE_BAND",
            f"Unknown compare band: {band_mode}",
            "Choose primary, wide, or custom.",
        ),
    )


def _validate_band_with_sample_rates(run0: dict, run1: dict, band_hz: tuple[float, float]) -> None:
    sample_rates = [_run_sample_rate_hz(run0), _run_sample_rate_hz(run1)]
    if any(rate <= 0 for rate in sample_rates):
        raise HTTPException(
            status_code=400,
            detail=_compare_error(
                "INVALID_COMPARE_SAMPLE_RATE",
                "Compare requires positive sample rates for both runs.",
                "Check the run metadata and finalize each run from the saved .bin before comparing.",
            ),
        )
    nyquist = min(sample_rates) / 2.0
    if float(band_hz[1]) >= nyquist:
        raise HTTPException(
            status_code=400,
            detail=_compare_error(
                "INVALID_COMPARE_BAND",
                f"Compare band {band_hz[0]:g}-{band_hz[1]:g} Hz exceeds the lowest run Nyquist frequency ({nyquist:g} Hz).",
                "Choose a band whose high cutoff is below half of the lowest actual sample rate in the pair.",
            ),
        )


def _run_sample_rate_hz(run: dict) -> float:
    recording = run.get("recording", {})
    return float(recording.get("actual_sample_rate_hz") or recording.get("sample_rate_hz") or 0.0)


def _load_compare_metrics(base, run0: dict, run1: dict, source: str, band_hz: tuple[float, float]) -> tuple[dict, dict]:
    if source == "peak_wav":
        raise HTTPException(
            status_code=400,
            detail=_compare_error(
                "PEAK_WAV_NOT_QUANTITATIVE",
                "Peak-normalized WAV is listening-only and cannot be used for quantitative comparison.",
                "Use saved .bin metrics for report-grade attenuation, or range WAV only as a cross-check with known full-scale voltage.",
            ),
        )
    if source == "bin":
        return _read_metrics_json(base, run0), _read_metrics_json(base, run1)
    if source == "range_wav":
        return (
            _range_metrics(base, run0, band_hz),
            _range_metrics(base, run1, band_hz),
        )
    raise HTTPException(
        status_code=400,
        detail=_compare_error(
            "INVALID_COMPARE_SOURCE",
            f"Unknown compare source: {source}",
            "Use saved .bin for report-grade comparison, or range WAV only as a cross-check.",
        ),
    )


def _range_metrics(base, run: dict, band_hz: tuple[float, float]) -> dict:
    wav_path = base / run["files"].get("wav_range", "")
    if not wav_path.exists():
        raise HTTPException(
            status_code=400,
            detail=_compare_error(
                "RANGE_WAV_MISSING",
                f"Range WAV is missing for run {run['run_id']}.",
                "Convert WAVs from the saved .bin first, or use saved .bin as the report-grade comparison source.",
            ),
        )
    full_scale = float(run.get("conversion", {}).get("full_scale_volts") or 0.0)
    if full_scale <= 0:
        raise HTTPException(
            status_code=400,
            detail=_compare_error(
                "FULL_SCALE_VOLTAGE_MISSING",
                f"Full-scale voltage is missing for run {run['run_id']}.",
                "Set a positive full-scale voltage before using range WAV cross-check, or compare saved .bin metrics.",
            ),
        )
    try:
        return analyze_range_wav(
            wav_path,
            full_scale_volts=full_scale,
            remove_dc=bool(run.get("conversion", {}).get("remove_dc", True)),
            expected_sample_rate_hz=int(round(float(run["recording"].get("actual_sample_rate_hz") or run["recording"].get("sample_rate_hz", 0) or 0))),
            trim_start_s=float(run.get("analysis", {}).get("trim_start_s", 0.0) or 0.0),
            trim_end_s=float(run.get("analysis", {}).get("trim_end_s", 0.0) or 0.0),
            band_hz=band_hz,
            expected_duration_s=float(run["recording"].get("duration_s", 0.0) or 0.0),
        )
    except (EOFError, ValueError, OSError, wave.Error) as exc:
        raise HTTPException(
            status_code=400,
            detail=_compare_error(
                "INVALID_RANGE_WAV_CROSS_CHECK",
                f"Range WAV for {run['run_id']} could not be analyzed: {exc}",
                "Regenerate WAVs from the saved .bin, or use saved .bin as the report-grade comparison source.",
            ),
        ) from exc


def _compare_error(error_code: str, message: str, suggestion: str) -> dict[str, str]:
    return {"error_code": error_code, "message": message, "suggestion": suggestion}


def _compare_error_redirect(session_id: str, detail) -> RedirectResponse:
    if not isinstance(detail, dict):
        detail = _compare_error("COMPARE_FAILED", str(detail), "Review the selected runs and try again.")
    query = urlencode({
        "alert_code": detail.get("error_code", "COMPARE_FAILED"),
        "alert_message": detail.get("message", "Compare failed."),
        "alert_suggestion": detail.get("suggestion", "Review the selected runs and try again."),
    })
    return RedirectResponse(f"/compare/{session_id}?{query}", status_code=303)


def _alert_from_query(request: Request) -> dict[str, str] | None:
    params = request.query_params
    if params.get("alert_code"):
        return {
            "kind": "error",
            "code": params.get("alert_code", ""),
            "message": params.get("alert_message", ""),
            "suggestion": params.get("alert_suggestion", ""),
        }
    notice = params.get("notice", "")
    notices = {
        "compare_saved": ("Comparison saved.", "Newest saved result is shown first below."),
        "auto_pair_saved": ("Auto-pair comparisons saved.", "Newest saved results are shown first below."),
        "auto_pair_none": ("No auto-pair comparison was created.", "Finalize matching uj0 and uj1 runs with compatible metadata, then try auto-pair again."),
    }
    if notice in notices:
        message, suggestion = notices[notice]
        return {"kind": "success", "code": notice, "message": message, "suggestion": suggestion}
    return None


def _comparison_sort_key(path) -> tuple[str, int]:
    result = read_json_or_default(path, {})
    return (str(result.get("created_at") or ""), path.stat().st_mtime_ns)


def _require_session(workspace, session_id: str) -> None:
    if not (session_dir(workspace, session_id) / "session.json").is_file():
        raise HTTPException(
            status_code=404,
            detail=_compare_error(
                "SESSION_NOT_FOUND",
                f"Session {session_id} was not found.",
                "Open the Compare page and choose an existing session.",
            ),
        )


def _require_run(workspace, session_id: str, run_id: str) -> None:
    if not (session_dir(workspace, session_id) / "metadata" / f"{safe_name(run_id)}.json").is_file():
        raise HTTPException(
            status_code=404,
            detail=_compare_error(
                "RUN_NOT_FOUND",
                f"Run {run_id} was not found in session {session_id}.",
                "Open the compare form and choose existing finalized runs from the selected session.",
            ),
        )


def _read_metrics_json(base, run: dict) -> dict:
    path = base / run["files"].get("metrics_json", "")
    if not path.is_file():
        raise HTTPException(
            status_code=400,
            detail=_compare_error(
                "METRICS_JSON_MISSING",
                f"Report-grade metrics JSON is missing for run {run['run_id']}.",
                "Finalize the run from its saved .bin before comparing.",
            ),
        )
    return read_json(path)
