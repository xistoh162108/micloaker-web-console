from __future__ import annotations

import json
import zipfile
from pathlib import PurePosixPath
from pathlib import Path
from typing import Iterable

from ..config import APP_VERSION
from .lab_validation import validation_paths
from .metadata import regenerate_session_report, regenerate_summary
from .text_store import append_app_event, now_iso, read_json_or_default, session_dir


def make_run_zip(workspace: Path, session_id: str, run_id: str, out_path: Path) -> Path:
    base = session_dir(workspace, session_id)
    run_prefix = f"{run_id}/"
    expected = _expected_run_files(base, run_id)
    out_path = _unique_output_path(out_path)
    path = _write_zip(workspace, base, expected, out_path, run_prefix)
    append_app_event(workspace, "run_zip_exported", session_id=session_id, run_id=run_id, path=str(path.relative_to(workspace)))
    return path


def make_session_zip(workspace: Path, session_id: str, out_path: Path) -> Path:
    base = session_dir(workspace, session_id)
    regenerate_summary(workspace, session_id)
    regenerate_session_report(workspace, session_id)
    included: list[str] = []
    missing: list[str] = []
    out_path = _unique_output_path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel in ["session.json", "summary.csv", "session_report.md"]:
            _add_or_missing(zf, base, rel, f"{session_id}/{rel}", included, missing)
        for path in sorted((base / "metadata").glob("*.json")):
            run_id = path.stem
            run = read_json_or_default(path, {})
            run_included: list[str] = []
            run_missing: list[str] = []
            for rel in _expected_run_files(base, run_id, run):
                arc = f"{session_id}/runs/{run_id}/{rel}"
                _add_or_missing(zf, base, rel, arc, run_included, run_missing)
            run_manifest_arc = f"{session_id}/runs/{run_id}/export_manifest.json"
            zf.writestr(run_manifest_arc, _manifest(workspace, [*run_included, run_manifest_arc], run_missing))
            included.extend(run_included)
            missing.extend(run_missing)
            included.append(run_manifest_arc)
        _add_comparison_package(zf, base, f"{session_id}/comparisons", included, missing)
        _add_validation_package(zf, workspace, f"{session_id}/ops_validation", included, missing)
        manifest_arc = f"{session_id}/export_manifest.json"
        zf.writestr(manifest_arc, _manifest(workspace, [*included, manifest_arc], missing))
    path = out_path
    append_app_event(workspace, "session_zip_exported", session_id=session_id, path=str(path.relative_to(workspace)))
    return path


def make_multi_session_zip(workspace: Path, session_ids: Iterable[str], out_path: Path) -> Path:
    session_ids = list(session_ids)
    included: list[str] = []
    missing: list[str] = []
    out_path = _unique_output_path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for sid in session_ids:
            base = session_dir(workspace, sid)
            if not base.exists():
                missing.append(f"sessions/{sid}")
                continue
            regenerate_summary(workspace, sid)
            regenerate_session_report(workspace, sid)
            session_included: list[str] = []
            session_missing: list[str] = []
            for rel in ["session.json", "summary.csv", "session_report.md"]:
                _add_or_missing(zf, base, rel, f"{sid}/{rel}", session_included, session_missing)
            for path in sorted((base / "metadata").glob("*.json")):
                run_id = path.stem
                run = read_json_or_default(path, {})
                run_included: list[str] = []
                run_missing: list[str] = []
                for rel in _expected_run_files(base, run_id, run):
                    _add_or_missing(zf, base, rel, f"{sid}/runs/{run_id}/{rel}", run_included, run_missing)
                run_manifest_arc = f"{sid}/runs/{run_id}/export_manifest.json"
                zf.writestr(run_manifest_arc, _manifest(workspace, [*run_included, run_manifest_arc], run_missing))
                session_included.extend(run_included)
                session_missing.extend(run_missing)
                session_included.append(run_manifest_arc)
            _add_comparison_package(zf, base, f"{sid}/comparisons", session_included, session_missing)
            _add_validation_package(zf, workspace, f"{sid}/ops_validation", session_included, session_missing)
            manifest_arc = f"{sid}/export_manifest.json"
            zf.writestr(manifest_arc, _manifest(workspace, [*session_included, manifest_arc], session_missing))
            included.extend(session_included)
            missing.extend(session_missing)
            included.append(manifest_arc)
        zf.writestr("export_manifest.json", _manifest(workspace, [*included, "export_manifest.json"], missing))
    append_app_event(workspace, "multi_session_zip_exported", sessions=",".join(session_ids), path=str(out_path.relative_to(workspace)))
    return out_path


def _unique_output_path(out_path: Path) -> Path:
    if not out_path.exists():
        return out_path
    stem = out_path.stem
    suffix = out_path.suffix
    for index in range(2, 10_000):
        candidate = out_path.with_name(f"{stem}_{index:02d}{suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"too many existing export files for {out_path.name}")


def _write_zip(workspace: Path, base: Path, files: list[str], out_path: Path, prefix: str) -> Path:
    included: list[str] = []
    missing: list[str] = []
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel in files:
            _add_or_missing(zf, base, rel, prefix + rel, included, missing)
        manifest_arc = prefix + "export_manifest.json"
        zf.writestr(manifest_arc, _manifest(workspace, [*included, manifest_arc], missing))
    return out_path


def _expected_run_files(base: Path, run_id: str, run: dict | None = None) -> list[str]:
    if run is None:
        metadata_path = base / "metadata" / f"{run_id}.json"
        run = read_json_or_default(metadata_path, {}) if metadata_path.exists() else {}
    run_files = run.get("files", {})
    scale_modes = set(run.get("conversion", {}).get("scale_modes") or ["peak", "range"])
    files = [
        run_files.get("bin", f"bin/{run_id}.bin"),
    ]
    if "peak" in scale_modes or (base / run_files.get("wav_peak", "")).exists():
        files.append(run_files.get("wav_peak", f"wav/{run_id}__scale-peak.wav"))
    if "range" in scale_modes:
        files.append(run_files.get("wav_range", _range_wav_fallback(base, run_id)))
    else:
        files.extend(f"wav/{wav.name}" for wav in sorted((base / "wav").glob(f"{run_id}__scale-range-fs*V.wav")))
    files.extend([
        f"metadata/{run_id}.json",
        run_files.get("metrics_json", f"results/{run_id}_metrics.json"),
        run_files.get("metrics_csv", f"results/{run_id}_metrics.csv"),
        run_files.get("waveform_png", f"plots/{run_id}_waveform.png"),
        run_files.get("waveform_svg", f"plots/{run_id}_waveform.svg"),
        run_files.get("psd_png", f"plots/{run_id}_psd.png"),
        run_files.get("psd_svg", f"plots/{run_id}_psd.svg"),
        run_files.get("spectrogram_png", f"plots/{run_id}_spectrogram.png"),
        run_files.get("spectrogram_svg", f"plots/{run_id}_spectrogram.svg"),
        f"logs/{run_id}.log",
    ])
    return _dedupe(files)


def _add_comparison_package(zf: zipfile.ZipFile, base: Path, arc_prefix: str, included: list[str], missing: list[str]) -> None:
    expected = []
    for path in sorted((base / "comparisons").glob("*.json")):
        expected.extend(_expected_comparison_files(base, path))
    for rel in _dedupe(expected):
        _add_or_missing(zf, base, rel, f"{arc_prefix}/{PurePosixPath(rel).name}", included, missing)
    expected_set = set(expected)
    for path in sorted((base / "comparisons").glob("*")):
        if not path.is_file() or not _path_inside(base, path):
            continue
        rel = path.relative_to(base).as_posix()
        if rel in expected_set:
            continue
        _write_member(zf, path, f"{arc_prefix}/{path.name}", included, missing)


def _expected_comparison_files(base: Path, comparison_json_path: Path) -> list[str]:
    rel_json = comparison_json_path.relative_to(base).as_posix()
    comparison = read_json_or_default(comparison_json_path, {})
    compare_id = str(comparison.get("compare_id") or comparison_json_path.stem)
    files = [rel_json, f"comparisons/{compare_id}.csv"]
    plots = comparison.get("plots", {})
    if isinstance(plots, dict):
        files.extend(str(path) for path in plots.values() if path)
    return _dedupe(files)


def _add_validation_package(zf: zipfile.ZipFile, workspace: Path, arc_prefix: str, included: list[str], missing: list[str]) -> None:
    for name, path in validation_paths(workspace).items():
        arc = f"{arc_prefix}/{path.name}"
        if path.exists() and path.is_file() and _path_inside(workspace, path):
            _write_member(zf, path, arc, included, missing)


def _range_wav_fallback(base: Path, run_id: str) -> str:
    existing = sorted((base / "wav").glob(f"{run_id}__scale-range-fs*V.wav"))
    if existing:
        return f"wav/{existing[0].name}"
    return f"wav/{run_id}__scale-range-fs10V.wav"


def _dedupe(files: list[str]) -> list[str]:
    seen = set()
    unique = []
    for rel in files:
        if rel and rel not in seen:
            unique.append(rel)
            seen.add(rel)
    return unique


def _add_or_missing(zf: zipfile.ZipFile, base: Path, rel: str, arc: str, included: list[str], missing: list[str]) -> None:
    if not _safe_archive_name(arc) or not _safe_relative_path(rel):
        missing.append(_unsafe_marker(arc))
        return
    path = (base / rel).resolve()
    if not _path_inside(base, path):
        missing.append(_unsafe_marker(arc))
        return
    if path.exists() and path.is_file():
        _write_member(zf, path, arc, included, missing)
    else:
        missing.append(arc)


def _write_member(zf: zipfile.ZipFile, path: Path, arc: str, included: list[str], missing: list[str]) -> None:
    if not _safe_archive_name(arc):
        missing.append(_unsafe_marker(arc))
        return
    zf.write(path, arc)
    included.append(arc)


def _path_inside(base: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
    except ValueError:
        return False
    return True


def _safe_relative_path(rel: str) -> bool:
    value = str(rel).replace("\\", "/")
    parsed = PurePosixPath(value)
    return bool(value) and not parsed.is_absolute() and ".." not in parsed.parts


def _safe_archive_name(arc: str) -> bool:
    return _safe_relative_path(arc)


def _unsafe_marker(arc: str) -> str:
    marker = str(arc).replace("\\", "/").replace("/", "_").replace("..", "__").strip("_")
    return f"unsafe_path/{marker or 'artifact'}"


def _manifest(workspace: Path, included: list[str], missing: list[str]) -> str:
    unsafe_files = [item for item in missing if item.startswith("unsafe_path/")]
    return json.dumps({
        "exported_at": now_iso(),
        "app_version": APP_VERSION,
        "workspace": workspace.name,
        "included_files": included,
        "missing_files": missing,
        "unsafe_files": unsafe_files,
        "notes": "Raw .bin float64 voltage is the primary quantitative source. Peak WAV is listening-only. Range WAV is cross-check only when full-scale voltage is known.",
    }, indent=2, sort_keys=True)
