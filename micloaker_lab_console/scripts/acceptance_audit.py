#!/usr/bin/env python3
"""Local acceptance audit for MiCloaker Lab Console non-negotiables."""

from __future__ import annotations

import os
import sys
import tempfile
import wave
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_PATHS = [
    "app/main.py",
    "app/config.py",
    "app/models.py",
    "app/routes/dashboard.py",
    "app/routes/sessions.py",
    "app/routes/runs.py",
    "app/routes/recording.py",
    "app/routes/conversion.py",
    "app/routes/analysis.py",
    "app/routes/compare.py",
    "app/routes/exports.py",
    "app/routes/files.py",
    "app/routes/live.py",
    "app/routes/logs.py",
    "app/routes/mac_helper.py",
    "app/routes/ops.py",
    "app/services/daq.py",
    "app/services/mock_daq.py",
    "app/services/recorder.py",
    "app/services/converter.py",
    "app/services/analyzer.py",
    "app/services/plotting.py",
    "app/services/metadata.py",
    "app/services/text_store.py",
    "app/services/export_zip.py",
    "app/services/jobs.py",
    "app/services/lab_validation.py",
    "app/services/live_monitor.py",
    "app/services/mac_helper_client.py",
    "app/services/readiness.py",
    "app/services/tailscale.py",
    "app/templates/base.html",
    "app/templates/dashboard.html",
    "app/templates/sessions.html",
    "app/templates/session_detail.html",
    "app/templates/run_detail.html",
    "app/templates/compare.html",
    "app/templates/compare_index.html",
    "app/templates/live.html",
    "app/templates/logs.html",
    "app/templates/mac_helper.html",
    "app/templates/ops.html",
    "app/templates/files.html",
    "app/templates/new_run.html",
    "app/static/css/app.css",
    "app/static/js/app.js",
    "app/static/js/live.js",
    "app/static/js/mac_helper.js",
    "scripts/console_control.py",
    "scripts/install_linux_desktop_launcher.py",
    "scripts/lab_readiness_check.py",
    "mac_helper/helper.py",
    "mac_helper/helper_control.py",
    "mac_helper/Start MiCloaker Helper.command",
    "mac_helper/Stop MiCloaker Helper.command",
    "mac_helper/Status MiCloaker Helper.command",
    "mac_helper/config.example.json",
    "mac_helper/README.md",
    "tests/test_core_workflow.py",
    "tests/test_mac_helper.py",
    "../docs/COMPLETION_AUDIT.md",
    "README.md",
    "requirements.txt",
    "requirements-mac-helper.txt",
]

DB_SUFFIXES = {".db", ".duckdb", ".sqlite", ".sqlite3"}
DB_DEPENDENCIES = {
    "asyncpg",
    "databases",
    "duckdb",
    "psycopg",
    "psycopg2",
    "sqlalchemy",
    "tinydb",
}
SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
}


def iter_project_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        if path.is_file():
            files.append(path)
    return files


def requirement_names(path: Path) -> set[str]:
    names: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip().lower()
        if not line:
            continue
        for separator in ("==", ">=", "<=", "~=", "!=", ">", "<", "["):
            line = line.split(separator, 1)[0]
        names.add(line.strip())
    return names


def report(ok: bool, message: str) -> bool:
    prefix = "PASS" if ok else "FAIL"
    print(f"{prefix}: {message}")
    return ok


def audit_mock_workflow(workspace: Path) -> tuple[bool, list[str]]:
    failures: list[str] = []
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app
    from app.services.export_zip import make_run_zip, make_session_zip
    from app.services.lab_validation import record_lab_validation
    from app.services.metadata import create_run_metadata, create_session, load_runs, load_sessions
    from app.services.readiness import write_readiness_artifacts
    from app.services.recorder import record_mock_and_finalize
    from app.services.text_store import read_json, read_jsonl, session_dir

    session = create_session(workspace, "acceptance workflow", notes="temporary audit session")
    run = create_run_metadata(
        workspace,
        session["session_id"],
        carrier_freq_khz=25.0,
        uj="uj0",
        duration_s=0.1,
        sample_rate_hz=8000,
        analysis_band_low_hz=300.0,
        analysis_band_high_hz=3400.0,
    )
    finalized = record_mock_and_finalize(workspace, run)
    run1 = create_run_metadata(
        workspace,
        session["session_id"],
        carrier_freq_khz=25.0,
        uj="uj1",
        duration_s=0.1,
        sample_rate_hz=8000,
        analysis_band_low_hz=300.0,
        analysis_band_high_hz=3400.0,
    )
    finalized1 = record_mock_and_finalize(workspace, run1)
    base = session_dir(workspace, session["session_id"])

    expected_files = [
        finalized["files"]["bin"],
        finalized["files"]["wav_peak"],
        finalized["files"]["wav_range"],
        finalized["files"]["metrics_json"],
        finalized["files"]["metrics_csv"],
        finalized["files"]["waveform_png"],
        finalized["files"]["waveform_svg"],
        finalized["files"]["psd_png"],
        finalized["files"]["psd_svg"],
        finalized["files"]["spectrogram_png"],
        finalized["files"]["spectrogram_svg"],
        f"logs/{finalized['run_id']}.log",
        "summary.csv",
        "session_report.md",
    ]
    missing_files = [rel for rel in expected_files if not (base / rel).is_file()]
    if missing_files:
        failures.append(f"missing workflow artifacts: {', '.join(missing_files)}")

    if not finalized["files"]["wav_peak"].endswith("__scale-peak.wav"):
        failures.append("peak WAV name does not include __scale-peak.wav")
    if not finalized["files"]["wav_range"].endswith("__scale-range-fs10V.wav"):
        failures.append("range WAV name does not include __scale-range-fs10V.wav")

    conversion = finalized.get("conversion", {}).get("outputs", {})
    peak = conversion.get("wav_peak", {})
    range_wav = conversion.get("wav_range", {})
    if peak.get("purpose") != "listening_preview_only" or peak.get("quantitative_use") != "do_not_use_for_final_attenuation":
        failures.append("peak WAV is not labeled listening-only")
    if range_wav.get("purpose") != "cross_check_only" or range_wav.get("full_scale_volts") != 10.0:
        failures.append("range WAV is not labeled as full-scale cross-check")

    analysis = finalized.get("analysis", {})
    if analysis.get("status") != "finalized" or analysis.get("result_grade") != "report-grade":
        failures.append("finalized run is not marked report-grade")
    if analysis.get("finalized_from_saved_bin") is not True:
        failures.append("finalized run is not marked as recomputed from saved .bin")

    metrics = read_json(base / finalized["files"]["metrics_json"])
    for key in ["rms_v", "band_power_300_3400", "band_power_20_3900", "dominant_freq_hz", "psd_freq_hz"]:
        if key not in metrics:
            failures.append(f"metrics JSON missing {key}")
    if metrics.get("source") != "bin":
        failures.append("metrics source is not saved .bin")

    client = TestClient(create_app())
    compare_response = client.post(
        f"/compare/{session['session_id']}",
        data={
            "uj0_run_id": finalized["run_id"],
            "uj1_run_id": finalized1["run_id"],
            "source": "bin",
            "band_mode": "primary",
        },
        follow_redirects=False,
    )
    if compare_response.status_code != 303:
        failures.append(f"compare route did not redirect after saving: HTTP {compare_response.status_code}")
    comparison_files = sorted((base / "comparisons").glob("*.json"))
    if len(comparison_files) != 1:
        failures.append(f"expected one comparison JSON artifact, found {len(comparison_files)}")
    else:
        comparison = read_json(comparison_files[0])
        required_compare_keys = [
            "attenuation_db",
            "remaining_fraction",
            "reduction_percent",
            "uj0_run_id",
            "uj1_run_id",
            "source",
            "result_grade",
            "plots",
        ]
        for key in required_compare_keys:
            if key not in comparison:
                failures.append(f"comparison JSON missing {key}")
        if comparison.get("source") != "bin" or comparison.get("result_grade") != "report-grade":
            failures.append("comparison is not marked report-grade from saved .bin")
        if comparison.get("uj0_run_id") != finalized["run_id"] or comparison.get("uj1_run_id") != finalized1["run_id"]:
            failures.append("comparison does not preserve selected uj0/uj1 run IDs")
        for plot_key in ["attenuation_png", "attenuation_svg", "psd_overlay_png", "psd_overlay_svg"]:
            rel = comparison.get("plots", {}).get(plot_key)
            if not rel or not (base / rel).is_file():
                failures.append(f"comparison plot artifact missing: {plot_key}")
        if not comparison_files[0].with_suffix(".csv").is_file():
            failures.append("comparison CSV artifact is missing")

    for index_path in [workspace / ".micloaker" / "sessions.jsonl", base / "runs.jsonl", base / "events.jsonl"]:
        index_path.write_text('{"event":"stale"}\n', encoding="utf-8")
    create_app()
    reloaded_sessions = load_sessions(workspace)
    reloaded_runs = load_runs(workspace, session["session_id"])
    rebuilt_events = read_jsonl(base / "events.jsonl")
    if session["session_id"] not in {item.get("session_id") for item in reloaded_sessions}:
        failures.append("startup rebuild did not reload session from session.json")
    if {finalized["run_id"], finalized1["run_id"]} - {item.get("run_id") for item in reloaded_runs}:
        failures.append("startup rebuild did not reload runs from metadata JSON")
    if not any(row.get("event") == "comparison_indexed" for row in rebuilt_events):
        failures.append("startup rebuild did not recover saved comparison event")
    if any(row.get("event") == "stale" for row in rebuilt_events):
        failures.append("startup rebuild left stale session event rows in place")
    rebuilt_report = (base / "session_report.md").read_text(encoding="utf-8")
    if "## Saved Comparisons" not in rebuilt_report or "report-grade" not in rebuilt_report:
        failures.append("startup rebuild did not regenerate session report with saved comparison")
    rebuilt_summary = (base / "summary.csv").read_text(encoding="utf-8")
    if "band_power_300_3400" not in rebuilt_summary or finalized["run_id"] not in rebuilt_summary:
        failures.append("startup rebuild did not regenerate summary.csv from saved run metrics")

    record_lab_validation(
        workspace,
        gate="attenuation_pair",
        status="pass",
        session_id=session["session_id"],
        run_id=finalized1["run_id"],
        evidence="acceptance audit validation evidence",
    )
    write_readiness_artifacts(Settings(workspace=workspace))
    run_zip = make_run_zip(workspace, session["session_id"], finalized["run_id"], workspace / "run_audit.zip")
    session_zip = make_session_zip(workspace, session["session_id"], workspace / "session_audit.zip")
    with zipfile.ZipFile(run_zip) as zf:
        run_names = set(zf.namelist())
        run_manifest_name = f"{finalized['run_id']}/export_manifest.json"
        if run_manifest_name not in run_names:
            failures.append("run ZIP missing export_manifest.json")
        else:
            import json

            manifest = json.loads(zf.read(run_manifest_name))
            if manifest.get("missing_files"):
                failures.append(f"run ZIP manifest reports missing files: {manifest['missing_files']}")
    with zipfile.ZipFile(session_zip) as zf:
        session_names = set(zf.namelist())
        if f"{session['session_id']}/export_manifest.json" not in session_names:
            failures.append("session ZIP missing export_manifest.json")
        if f"{session['session_id']}/runs/{finalized['run_id']}/bin/{finalized['run_id']}.bin" not in session_names:
            failures.append("session ZIP missing run raw .bin")
        if not any(name.startswith(f"{session['session_id']}/comparisons/") and name.endswith(".json") for name in session_names):
            failures.append("session ZIP missing saved comparison JSON")
        validation_jsonl = f"{session['session_id']}/ops_validation/hardware_validation.jsonl"
        validation_report = f"{session['session_id']}/ops_validation/hardware_validation_report.md"
        readiness_json = f"{session['session_id']}/ops_validation/lab_readiness_report.json"
        readiness_report = f"{session['session_id']}/ops_validation/lab_readiness_report.md"
        if validation_jsonl not in session_names or validation_report not in session_names:
            failures.append("session ZIP missing hardware validation evidence files")
        if readiness_json not in session_names or readiness_report not in session_names:
            failures.append("session ZIP missing lab readiness evidence files")

    try:
        record_mock_and_finalize(workspace, finalized)
    except FileExistsError:
        pass
    else:
        failures.append("raw .bin overwrite was not rejected")

    return not failures, failures


def audit_mac_helper_mock(wav_root: Path) -> tuple[bool, list[str]]:
    failures: list[str] = []
    import numpy as np
    from fastapi.testclient import TestClient
    from mac_helper.helper import create_app

    wav_root.mkdir(parents=True, exist_ok=True)
    with wave.open(str(wav_root / "tone.wav"), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(8000)
        wf.writeframes(np.zeros(800, dtype="<i2").tobytes())

    client = TestClient(create_app({"wav_root": str(wav_root), "mock_audio": True}))
    health = client.get("/health").json()
    if not health.get("ok") or health.get("wav_root_exists") is not True:
        failures.append("Mac Helper health did not report usable wav_root")
    files = client.get("/files").json()
    paths = [row.get("path") for row in files.get("files", [])]
    if paths != ["tone.wav"]:
        failures.append(f"Mac Helper /files did not list relative wav_root files only: {paths}")
    valid = client.post(
        "/validate-playback",
        json={"file": "tone.wav", "device_id": 1, "sample_rate": 8000, "channels": 2, "gain": 0.5},
    ).json()
    if not valid.get("ok") or valid.get("will_channel_map") is not True:
        failures.append("Mac Helper did not validate mono-to-stereo channel mapping in mock mode")
    traversal = client.post(
        "/validate-playback",
        json={"file": "../tone.wav", "device_id": 1, "sample_rate": 8000, "channels": 1, "gain": 0.5},
    ).json()
    if traversal.get("ok") is not False or traversal.get("error_code") != "PATH_TRAVERSAL_REJECTED":
        failures.append("Mac Helper did not reject path traversal with structured error")
    token_client = TestClient(create_app({"wav_root": str(wav_root), "mock_audio": True, "optional_token": "audit-token"}))
    unauthorized = token_client.get("/health").json()
    if unauthorized.get("ok") is not False or unauthorized.get("error_code") != "UNAUTHORIZED":
        failures.append("Mac Helper optional_token did not reject unauthenticated requests")
    authorized = token_client.get("/health", headers={"Authorization": "Bearer audit-token"}).json()
    if authorized.get("ok") is not True:
        failures.append("Mac Helper optional_token did not allow matching bearer token")
    return not failures, failures


def main() -> int:
    checks: list[bool] = []

    missing = [rel for rel in REQUIRED_PATHS if not (ROOT / rel).exists()]
    checks.append(report(not missing, "required project layout is present"))
    if missing:
        for rel in missing:
            print(f"  missing: {rel}")

    db_files = [path.relative_to(ROOT) for path in iter_project_files() if path.suffix.lower() in DB_SUFFIXES]
    checks.append(report(not db_files, "no database files are present in the project tree"))
    if db_files:
        for rel in db_files:
            print(f"  database-like file: {rel}")

    req_paths = [ROOT / "requirements.txt", ROOT / "requirements-mac-helper.txt"]
    deps = set().union(*(requirement_names(path) for path in req_paths))
    forbidden_deps = sorted(deps & DB_DEPENDENCIES)
    checks.append(report(not forbidden_deps, "requirements do not include database dependencies"))
    if forbidden_deps:
        for name in forbidden_deps:
            print(f"  forbidden dependency: {name}")

    sys.path.insert(0, str(ROOT))
    from app.config import DEFAULT_HOST

    checks.append(report(DEFAULT_HOST == "127.0.0.1", "default host binds to 127.0.0.1"))

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    repo_readme = (ROOT.parent / "README.md").read_text(encoding="utf-8")
    docs_readme = (ROOT.parent / "docs" / "README.md").read_text(encoding="utf-8")
    helper_readme = (ROOT / "mac_helper" / "README.md").read_text(encoding="utf-8")
    dashboard_template = (ROOT / "app" / "templates" / "dashboard.html").read_text(encoding="utf-8")
    app_css = (ROOT / "app" / "static" / "css" / "app.css").read_text(encoding="utf-8")
    operator_ui_doc_path = ROOT.parent / "docs" / "OPERATOR_UI_DEPLOYMENT_REQUIREMENTS.md"
    operator_ui_doc = operator_ui_doc_path.read_text(encoding="utf-8") if operator_ui_doc_path.exists() else ""
    hardware_protocol_path = ROOT.parent / "docs" / "HARDWARE_VALIDATION_PROTOCOL.md"
    hardware_protocol = hardware_protocol_path.read_text(encoding="utf-8") if hardware_protocol_path.exists() else ""
    ui_ux_path = ROOT.parent / "docs" / "UI_UX_SPEC.md"
    ui_ux_doc = ui_ux_path.read_text(encoding="utf-8") if ui_ux_path.exists() else ""
    legacy_alignment_path = ROOT.parent / "docs" / "LEGACY_NOTEBOOK_ALIGNMENT.md"
    legacy_alignment_doc = legacy_alignment_path.read_text(encoding="utf-8") if legacy_alignment_path.exists() else ""
    checklist_path = ROOT.parent / "docs" / "CODEX_TASK_CHECKLIST.md"
    checklist_doc = checklist_path.read_text(encoding="utf-8") if checklist_path.exists() else ""
    completion_audit_path = ROOT.parent / "docs" / "COMPLETION_AUDIT.md"
    completion_audit_doc = completion_audit_path.read_text(encoding="utf-8") if completion_audit_path.exists() else ""
    checks.append(report("uvicorn app.main:app --host 127.0.0.1 --port 8000" in readme, "README documents localhost console run command"))
    checks.append(report("Ctrl+C" in readme and "rebuilds session/run lists from workspace text files" in readme, "README documents temporary lifecycle and restart recovery"))
    checks.append(report("Live Monitor" in readme and "Live preview is approximate" in readme and "saved `.bin`" in readme, "README documents live preview-only workflow"))
    checks.append(report("docs/COMPLETION_AUDIT.md" in repo_readme and "COMPLETION_AUDIT.md" in docs_readme and "../docs/COMPLETION_AUDIT.md" in readme, "README indexes link to the completion audit"))
    operator_terms = [
        "The UI standard is **DaisyUI**",
        "Experiment Command Center",
        "Command-line start/status/stop script",
        "Explicit Tailscale mode",
        "Linux desktop launcher",
        "Finder double-click launchers",
        "/ops/readiness",
        "Hardware Validation Records",
        "GitHub Delivery",
    ]
    missing_operator_terms = [term for term in operator_terms if term not in operator_ui_doc]
    checks.append(report(not missing_operator_terms, "operator UI/deployment requirements are documented"))
    if missing_operator_terms:
        for term in missing_operator_terms:
            print(f"  missing operator UI term: {term}")
    hardware_protocol_terms = [
        "Linux DAQ Smoke Capture",
        "Mac Helper Playback Validation",
        "End-to-End Play And Record Trial",
        "Attenuation Pair Check",
        "Pass/Fail Decision",
        "hardware_validation.jsonl",
    ]
    missing_hardware_protocol_terms = [term for term in hardware_protocol_terms if term not in hardware_protocol]
    checks.append(report(not missing_hardware_protocol_terms, "hardware validation protocol documents physical lab gates"))
    if missing_hardware_protocol_terms:
        for term in missing_hardware_protocol_terms:
            print(f"  missing hardware protocol term: {term}")
    daisy_terms = ["btn btn-primary", "btn btn-outline", "btn btn-error", "card", "card-body", "stats", "stat-value", "badge-success", "badge-warning", "Capture And Live Preview", "live-waveform", "live-psd", "live-spectrogram"]
    missing_daisy_terms = [term for term in daisy_terms if term not in dashboard_template]
    hidden_tab_dashboard = "tab-panel" in dashboard_template or "data-tabs" in dashboard_template
    wrapping_layout_terms = ["repeat(auto-fit, minmax(min(100%, 170px), 1fr))", "operator-action-bar", "live-primary", "dashboard-artifacts", "overflow-wrap: anywhere"]
    chart_perf_terms = ["content-visibility: auto", "aspect-ratio: 16 / 9"]
    missing_wrapping_terms = [term for term in wrapping_layout_terms if term not in app_css]
    missing_chart_perf_terms = [term for term in chart_perf_terms if term not in app_css]
    live_js = (ROOT / "app" / "static" / "js" / "live.js").read_text(encoding="utf-8")
    checks.append(report(not missing_daisy_terms and not hidden_tab_dashboard and not missing_wrapping_terms and not missing_chart_perf_terms and "requestAnimationFrame(renderCharts)" in live_js and "rows.flat()" not in live_js and 'decoding="async"' in dashboard_template and "DaisyUI component vocabulary" in app_css and "shadcn" not in app_css.lower(), "dashboard uses local DaisyUI command console vocabulary without hidden workflow tabs"))
    if missing_daisy_terms:
        for term in missing_daisy_terms:
            print(f"  missing DaisyUI dashboard term: {term}")
    if hidden_tab_dashboard:
        print("  dashboard still contains hidden tab workflow markup")
    if missing_wrapping_terms:
        for term in missing_wrapping_terms:
            print(f"  missing responsive wrapping term: {term}")
    if missing_chart_perf_terms:
        for term in missing_chart_perf_terms:
            print(f"  missing chart performance term: {term}")
    validation_download_terms = [
        "/ops/validation/files/hardware_validation.jsonl",
        "/ops/validation/files/hardware_validation_report.md",
        "/ops/readiness/files/lab_readiness_report.json",
        "/ops/readiness/files/lab_readiness_report.md",
        "Download Readiness Report",
        "Evidence Hints",
        "Gate Evidence Checklist",
        "Checklist fields",
        "Checklist preview",
        "Use checklist draft",
        "validation-checklist-preview",
        "validation-draft-button",
        "selected device_id",
        "macOS default output did not change",
        "expected vs written sample count",
        "Gate Status",
        "Hardware Validation Gate Status",
        "Next action",
        "Create DAQ validation run",
        "Open Mac Helper",
        "Open Compare",
        "hardware validation gate status and next-action targets",
        "not applicable",
    ]
    validation_sources = (
        (ROOT / "app" / "templates" / "ops.html").read_text(encoding="utf-8")
        + (ROOT / "app" / "services" / "lab_validation.py").read_text(encoding="utf-8")
        + (ROOT / "app" / "services" / "readiness.py").read_text(encoding="utf-8")
        + (ROOT / "scripts" / "lab_readiness_check.py").read_text(encoding="utf-8")
        + readme
    )
    missing_validation_download_terms = [term for term in validation_download_terms if term not in validation_sources]
    checks.append(report(not missing_validation_download_terms, "Ops page exposes validation evidence downloads and gate-specific hints"))
    if missing_validation_download_terms:
        for term in missing_validation_download_terms:
            print(f"  missing validation download term: {term}")
    command_center_terms = [
        "Dashboard Command Center",
        "Do not hide core experiment controls behind Dashboard tabs",
        "latest finalized visual artifacts",
        "Logs are secondary diagnostic material",
        "controls wrap cleanly",
    ]
    missing_command_center_terms = [term for term in command_center_terms if term not in ui_ux_doc]
    checks.append(report(not missing_command_center_terms, "UI/UX spec documents one-screen experiment command center"))
    if missing_command_center_terms:
        for term in missing_command_center_terms:
            print(f"  missing UI/UX term: {term}")
    legacy_terms = [
        "Legacy Notebook Alignment",
        "bin_to_wav.ipynb",
        "daq_deploy.ipynb",
        "volume_measurer.ipynb",
        "Raw `.bin` voltage data is the quantitative source of truth",
        "Exact numeric parity with a notebook is not assumed",
    ]
    missing_legacy_terms = [term for term in legacy_terms if term not in legacy_alignment_doc]
    checks.append(report(not missing_legacy_terms, "legacy notebook alignment is documented"))
    if missing_legacy_terms:
        for term in missing_legacy_terms:
            print(f"  missing legacy alignment term: {term}")
    checklist_terms = [
        "Automated evidence complete",
        "Lab verification required",
        "Latest recorded result: `133 passed`",
        "Run a short real DAQ smoke capture",
        "Run explicit DAQ live preview on the real DAQ",
        "Run Mac Helper on the actual macOS playback machine",
        "Record one finalized real `uj0`/`uj1` attenuation pair",
    ]
    missing_checklist_terms = [term for term in checklist_terms if term not in checklist_doc]
    checks.append(report(not missing_checklist_terms, "Codex checklist reflects automated completion and remaining lab validation"))
    if missing_checklist_terms:
        for term in missing_checklist_terms:
            print(f"  missing checklist term: {term}")
    completion_audit_terms = [
        "Goal Requirement Audit",
        "Stable local Linux web app, not always-on production service",
        "Plain text persistence only",
        "Raw `.bin` float64 voltage is saved and primary quantitative source",
        "DAQ recording with real hardware",
        "Helper uses explicit `device_id` without changing system default output",
        "Hardware validation records with workflow navigation",
        "scripts/lab_readiness_check.py --record-gate",
        "Use checklist draft helper",
        "Remaining Requirements Not Yet Proved By Automation",
        "overall goal must remain open until the lab-only physical verification items",
    ]
    missing_completion_terms = [term for term in completion_audit_terms if term not in completion_audit_doc]
    checks.append(report(not missing_completion_terms, "completion audit maps goal requirements to evidence and lab-only gaps"))
    if missing_completion_terms:
        for term in missing_completion_terms:
            print(f"  missing completion audit term: {term}")
    helper_doc_terms = [
        "cp config.example.json config.json",
        "python helper.py --config config.json",
        "trusted Tailnet",
        "optional_token",
        "Authorization: Bearer",
        "explicit `device_id`",
        "does not change the macOS system default output device",
        "`error_code`",
    ]
    missing_helper_terms = [term for term in helper_doc_terms if term not in helper_readme]
    checks.append(report(not missing_helper_terms, "Mac Helper README documents run command and safety contract"))
    if missing_helper_terms:
        for term in missing_helper_terms:
            print(f"  missing helper README term: {term}")

    with tempfile.TemporaryDirectory(prefix="micloaker-audit-") as temp_dir:
        previous_workspace = os.environ.get("MICLOAKER_WORKSPACE")
        os.environ["MICLOAKER_WORKSPACE"] = temp_dir
        sys.modules.pop("uldaq", None)
        for name in list(sys.modules):
            if name == "scipy" or name.startswith("scipy."):
                sys.modules.pop(name, None)
        try:
            from app.main import create_app

            app = create_app()
            temp_root = Path(temp_dir)
            checks.append(report((temp_root / ".micloaker" / "config.json").exists(), "startup creates plain-text workspace config"))
            checks.append(report("uldaq" not in sys.modules, "app startup does not eagerly import uldaq"))
            checks.append(report("scipy" not in sys.modules, "app startup does not eagerly import SciPy analysis dependency"))
            from fastapi.testclient import TestClient

            readiness_response = TestClient(app).get("/ops/readiness")
            readiness = readiness_response.json()
            readiness_keys = {row.get("key") for row in readiness.get("checks", [])}
            checks.append(report(readiness_response.status_code == 200 and readiness.get("summary", {}).get("fail") == 0 and {"workspace_text_files", "hardware_validation_records"} <= readiness_keys, "Ops readiness JSON reports lab pre-checks"))
            ok, failures = audit_mock_workflow(temp_root)
            checks.append(report(ok, "mock workflow records, finalizes, labels, plots, and exports"))
            for failure in failures:
                print(f"  workflow failure: {failure}")
            helper_ok, helper_failures = audit_mac_helper_mock(temp_root / "helper_wavs")
            checks.append(report(helper_ok, "Mac Helper mock mode validates wav_root playback safety"))
            for failure in helper_failures:
                print(f"  helper failure: {failure}")
        finally:
            if previous_workspace is None:
                os.environ.pop("MICLOAKER_WORKSPACE", None)
            else:
                os.environ["MICLOAKER_WORKSPACE"] = previous_workspace

    return 0 if all(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
