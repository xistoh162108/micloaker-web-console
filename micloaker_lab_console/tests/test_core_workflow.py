from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import types
import wave
import zipfile
from pathlib import Path

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.services.analyzer import analyze_bin, auto_pair_runs, compare_metrics, compare_runs
from app.services.converter import PEAK_WAV_HEADROOM, convert_bin_to_wav, peak_wav_name, range_wav_name
from app.main import create_app
from app.services.export_zip import make_multi_session_zip, make_run_zip, make_session_zip
from app.services.jobs import mark_unfinished_jobs_interrupted, run_job
from app.services.lab_validation import record_lab_validation
from app.services.mac_helper_client import MacHelperClient
from app.services.metadata import create_run_metadata, create_session, load_run, load_runs, rebuild_indexes, regenerate_summary, save_run
from app.services.recorder import RecordingBusyError, _recording_lock, finalize_run, import_bin_and_finalize, record_daq_and_finalize, record_mock_and_finalize, recording_status, validate_raw_bin_source
from app.services.tailscale import discover_helpers
from app.services.text_store import append_app_event, append_jsonl, atomic_write_json, atomic_write_text, ensure_workspace, read_json, read_jsonl, session_dir, write_csv
import app.main as main_module
import app.services.recorder as recorder_module
import app.services.plotting as plotting_module
import app.services.live_monitor as live_monitor_module
import app.routes.compare as compare_routes
import app.routes.mac_helper as mac_helper_routes
import app.services.tailscale as tailscale_module
import app.services.daq as daq_module


def test_atomic_json_and_index_rebuild(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ensure_workspace(tmp_path)
    for rel in [
        ".micloaker/config.json",
        ".micloaker/sessions.jsonl",
        ".micloaker/jobs.jsonl",
        ".micloaker/app_events.jsonl",
        ".micloaker/app.log",
    ]:
        assert (tmp_path / rel).exists()
    session = create_session(tmp_path, "r25k audible noise")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0")
    loaded = load_run(tmp_path, session["session_id"], run["run_id"])
    assert loaded["run_id"] == run["run_id"]
    session_events = read_jsonl(tmp_path / ".micloaker" / "sessions.jsonl")
    assert session_events[-1]["event"] == "session_created"
    assert session_events[-1]["created_at"] == session["created_at"]
    run_events = read_jsonl(session_dir(tmp_path, session["session_id"]) / "runs.jsonl")
    assert run_events[-1]["event"] == "run_created"
    assert run_events[-1]["created_at"] == run["created_at"]
    counts = rebuild_indexes(tmp_path)
    assert counts == {"sessions": 1, "runs": 1, "comparisons": 0}
    app_events = read_jsonl(tmp_path / ".micloaker" / "app_events.jsonl")
    assert app_events[-1]["event"] == "indexes_rebuilt"
    assert app_events[-1]["sessions"] == 1
    assert app_events[-1]["runs"] == 1
    assert app_events[-1]["comparisons"] == 0
    assert "indexes_rebuilt sessions=1 runs=1 comparisons=0" in (tmp_path / ".micloaker" / "app.log").read_text(encoding="utf-8")
    rebuilt_sessions = read_jsonl(tmp_path / ".micloaker" / "sessions.jsonl")
    rebuilt_runs = read_jsonl(session_dir(tmp_path, session["session_id"]) / "runs.jsonl")
    assert rebuilt_sessions[-1]["created_at"] == session["created_at"]
    assert rebuilt_runs[-1]["created_at"] == run["created_at"]
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    client = TestClient(create_app())
    response = client.post("/sessions/rebuild-index", follow_redirects=False)
    assert response.status_code == 303
    assert "rebuilt=1" in response.headers["location"]
    page = client.get(response.headers["location"])
    assert page.status_code == 200
    assert "Rebuilt indexes: 1 sessions, 1 runs, 0 comparisons." in page.text
    empty_workspace = tmp_path / "empty_workspace"
    ensure_workspace(empty_workspace)
    assert rebuild_indexes(empty_workspace) == {"sessions": 0, "runs": 0, "comparisons": 0}
    assert (empty_workspace / ".micloaker" / "sessions.jsonl").exists()
    target = tmp_path / "check.json"
    atomic_write_json(target, {"ok": True})
    assert json.loads(target.read_text()) == {"ok": True}
    with pytest.raises(ValueError):
        atomic_write_json(target, {"bad": float("nan")})
    assert json.loads(target.read_text()) == {"ok": True}
    assert not target.with_name(target.name + ".tmp").exists()

    text_target = tmp_path / "report.md"
    atomic_write_text(text_target, "old\n")
    assert text_target.read_text(encoding="utf-8") == "old\n"
    csv_target = tmp_path / "summary.csv"
    write_csv(csv_target, [{"run_id": "r1", "rms_v": 0.1}], ["run_id", "rms_v"])
    with csv_target.open("r", encoding="utf-8", newline="") as f:
        assert next(csv.DictReader(f)) == {"run_id": "r1", "rms_v": "0.1"}
    assert not text_target.with_name(text_target.name + ".tmp").exists()
    assert not csv_target.with_name(csv_target.name + ".tmp").exists()


def test_jsonl_reads_ignore_malformed_append_only_lines_and_startup_recovers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "malformed jsonl recovery")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0")
    jobs_path = tmp_path / ".micloaker" / "jobs.jsonl"
    append_jsonl(jobs_path, {"event": "job_started", "status": "running", "job_id": "job_valid", "type": "manual_finalize"})
    with jobs_path.open("a", encoding="utf-8") as f:
        f.write("{bad json\n")
        f.write("[\"not\", \"an\", \"object\"]\n")
        f.write("\n")

    rows = read_jsonl(jobs_path)
    assert [row["job_id"] for row in rows if row.get("job_id")] == ["job_valid"]
    client = TestClient(create_app())
    assert client.get("/recording/status").status_code == 200
    assert load_run(tmp_path, session["session_id"], run["run_id"])["run_id"] == run["run_id"]
    jobs = read_jsonl(jobs_path)
    assert any(row.get("event") == "job_interrupted" and row.get("job_id") == "job_valid" for row in jobs)


def test_startup_rebuild_skips_malformed_scanned_json_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "malformed scan recovery")
    good_run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", duration_s=0.1)
    final = record_mock_and_finalize(tmp_path, good_run)
    base = session_dir(tmp_path, session["session_id"])
    (base / "metadata" / "broken_run.json").write_text("{bad json\n", encoding="utf-8")
    (base / "comparisons" / "broken_compare.json").write_text("{bad json\n", encoding="utf-8")
    (base / final["files"]["metrics_json"]).write_text("{bad metrics\n", encoding="utf-8")

    counts = rebuild_indexes(tmp_path)
    assert counts == {"sessions": 1, "runs": 1, "comparisons": 0}
    assert [run["run_id"] for run in load_runs(tmp_path, session["session_id"])] == [final["run_id"]]

    client = TestClient(create_app())
    assert client.get("/sessions").status_code == 200
    detail = client.get(f"/sessions/{session['session_id']}/runs/{final['run_id']}")
    assert detail.status_code == 200
    assert "No finalized metrics yet." in detail.text
    run_events = read_jsonl(base / "runs.jsonl")
    assert any(row["event"] == "run_indexed" and row["run_id"] == final["run_id"] for row in run_events)
    assert all(row.get("run_id") != "broken_run" for row in run_events)


def test_rebuild_indexes_repairs_partial_restored_session_structure(tmp_path: Path):
    ensure_workspace(tmp_path)
    session_id = "restored_session"
    base = session_dir(tmp_path, session_id)
    base.mkdir(parents=True)
    atomic_write_json(base / "session.json", {"session_id": session_id, "title": "restored", "created_at": "2026-05-28T00:00:00+00:00", "notes": ""})

    counts = rebuild_indexes(tmp_path)
    assert counts == {"sessions": 1, "runs": 0, "comparisons": 0}
    for name in ["bin", "wav", "plots", "results", "metadata", "logs", "comparisons"]:
        assert (base / name).is_dir()
    assert (base / "runs.jsonl").is_file()
    assert (base / "events.jsonl").is_file()
    assert (base / "summary.csv").is_file()
    assert (base / "session_report.md").is_file()
    assert read_jsonl(tmp_path / ".micloaker" / "sessions.jsonl")[-1]["session_id"] == session_id


def test_rebuild_indexes_recovers_finalized_run_and_comparison_events(tmp_path: Path):
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "recover indexes")
    run0 = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", duration_s=0.1)
    run1 = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj1", duration_s=0.1)
    final0 = record_mock_and_finalize(tmp_path, run0)
    final1 = record_mock_and_finalize(tmp_path, run1)
    result = compare_metrics(
        final0,
        read_json(session_dir(tmp_path, session["session_id"]) / final0["files"]["metrics_json"]),
        final1,
        read_json(session_dir(tmp_path, session["session_id"]) / final1["files"]["metrics_json"]),
    )
    base = session_dir(tmp_path, session["session_id"])
    result.update({"compare_id": "manual_compare_001", "created_at": "2026-05-28T00:00:00+00:00"})
    atomic_write_json(base / "comparisons" / "manual_compare_001.json", result)
    for path in [tmp_path / ".micloaker" / "sessions.jsonl", base / "runs.jsonl", base / "events.jsonl"]:
        path.write_text('{"event":"stale"}\n', encoding="utf-8")

    counts = rebuild_indexes(tmp_path)
    assert counts == {"sessions": 1, "runs": 2, "comparisons": 1}
    run_events = read_jsonl(base / "runs.jsonl")
    assert sum(1 for row in run_events if row["event"] == "run_indexed") == 2
    finalized = [row for row in run_events if row["event"] == "run_finalized"]
    assert {row["run_id"] for row in finalized} == {final0["run_id"], final1["run_id"]}
    assert all(row["metrics_path"].endswith("_metrics.json") for row in finalized)
    session_events = read_jsonl(base / "events.jsonl")
    assert session_events[0]["event"] == "session_indexed"
    assert any(row["event"] == "comparison_indexed" and row["compare_id"] == "manual_compare_001" for row in session_events)
    assert all(row["event"] != "stale" for row in session_events)


def test_rebuild_indexes_recovers_failed_finalization_events(tmp_path: Path):
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "recover failed indexes")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", duration_s=0.1)
    base = session_dir(tmp_path, session["session_id"])
    run["analysis"].update({
        "status": "failed",
        "failed_at": "2026-05-28T00:00:00+00:00",
        "last_error": "conversion backend failed",
        "error_log": f"logs/{run['run_id']}.log",
    })
    run["quality_flags"] = ["finalization_failed"]
    save_run(tmp_path, run)
    for path in [base / "runs.jsonl", base / "events.jsonl"]:
        path.write_text('{"event":"stale"}\n', encoding="utf-8")

    counts = rebuild_indexes(tmp_path)
    assert counts == {"sessions": 1, "runs": 1, "comparisons": 0}
    run_events = read_jsonl(base / "runs.jsonl")
    session_events = read_jsonl(base / "events.jsonl")
    rebuilt_failed = [row for row in run_events if row["event"] == "run_finalization_failed"]
    assert len(rebuilt_failed) == 1
    assert rebuilt_failed[0]["run_id"] == run["run_id"]
    assert rebuilt_failed[0]["failed_at"] == "2026-05-28T00:00:00+00:00"
    assert rebuilt_failed[0]["error"] == "conversion backend failed"
    assert rebuilt_failed[0]["error_log"] == f"logs/{run['run_id']}.log"
    assert rebuilt_failed[0]["ts"]
    assert any(row["event"] == "run_finalization_failed" and row["run_id"] == run["run_id"] for row in session_events)
    assert all(row["event"] != "stale" for row in run_events + session_events)
    with (base / "summary.csv").open("r", encoding="utf-8", newline="") as f:
        summary = next(csv.DictReader(f))
    assert summary["analysis_status"] == "failed"
    assert summary["result_grade"] == "none"
    assert summary["quality_flags"] == "finalization_failed"
    assert summary["analysis_error"] == "conversion backend failed"
    report = (base / "session_report.md").read_text(encoding="utf-8")
    assert "Quality Flags" in report
    assert "Analysis Error" in report
    assert "finalization_failed" in report
    assert "conversion backend failed" in report


def test_session_report_escapes_markdown_table_cells(tmp_path: Path):
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "markdown escaping")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", duration_s=0.1)
    run["analysis"].update({
        "status": "failed",
        "result_grade": "none",
        "last_error": "bad | value\nsecond line",
    })
    run["quality_flags"] = ["flag|with_pipe"]
    save_run(tmp_path, run)

    regenerate_summary(tmp_path, session["session_id"])
    report = (session_dir(tmp_path, session["session_id"]) / "session_report.md").read_text(encoding="utf-8")
    assert "bad \\| value second line" in report
    assert "flag\\|with_pipe" in report
    assert "bad | value\nsecond line" not in report


def test_create_session_avoids_silent_overwrite(tmp_path: Path):
    ensure_workspace(tmp_path)
    first = create_session(tmp_path, "same title", "first")
    second = create_session(tmp_path, "same title", "second")
    assert first["session_id"] != second["session_id"]
    first_json = read_json(session_dir(tmp_path, first["session_id"]) / "session.json")
    second_json = read_json(session_dir(tmp_path, second["session_id"]) / "session.json")
    assert first_json["notes"] == "first"
    assert second_json["notes"] == "second"
    assert second["session_id"].endswith("_02")


def test_run_metadata_services_require_existing_session(tmp_path: Path):
    ensure_workspace(tmp_path)
    with pytest.raises(FileNotFoundError, match="missing_session"):
        create_run_metadata(tmp_path, "missing_session", carrier_freq_khz=25, uj="uj0")
    assert not (tmp_path / "sessions" / "missing_session").exists()

    run = {
        "session_id": "missing_session",
        "run_id": "orphan_run",
        "files": {},
        "condition": {},
        "recording": {},
        "analysis": {},
    }
    with pytest.raises(FileNotFoundError, match="missing_session"):
        save_run(tmp_path, run)
    assert not (tmp_path / "sessions" / "missing_session").exists()


def test_filename_generation():
    assert peak_wav_name("run") == "run__scale-peak.wav"
    assert range_wav_name("run", 10.0) == "run__scale-range-fs10V.wav"


def test_bin_to_wav_peak_and_range(tmp_path: Path):
    data = np.sin(2 * np.pi * 1000 * np.arange(8000) / 8000).astype("<f8")
    bin_path = tmp_path / "run.bin"
    data.tofile(bin_path)
    peak = convert_bin_to_wav(bin_path, tmp_path, "run", 8000, scale_mode="peak")
    rng = convert_bin_to_wav(bin_path, tmp_path, "run", 8000, scale_mode="range", full_scale_volts=10.0)
    assert peak.name == "run__scale-peak.wav"
    assert rng.name == "run__scale-range-fs10V.wav"
    assert peak.stat().st_size > 44
    assert rng.stat().st_size > 44
    with wave.open(str(peak), "rb") as wf:
        peak_pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2")
    assert np.max(np.abs(peak_pcm)) == int(round(32767 * PEAK_WAV_HEADROOM))
    assert np.max(np.abs(peak_pcm)) < 32767
    with pytest.raises(FileExistsError):
        convert_bin_to_wav(bin_path, tmp_path, "run", 8000, scale_mode="peak")
    assert convert_bin_to_wav(bin_path, tmp_path, "run", 8000, scale_mode="peak", overwrite=True).name == "run__scale-peak.wav"
    with pytest.raises(ValueError, match="full_scale_volts"):
        convert_bin_to_wav(bin_path, tmp_path, "bad_range", 8000, scale_mode="range", full_scale_volts=0.0)


def test_analysis_on_synthetic_bin(tmp_path: Path):
    fs = 8000
    t = np.arange(fs) / fs
    x = (0.2 * np.sin(2 * np.pi * 1000 * t)).astype("<f8")
    path = tmp_path / "tone.bin"
    x.tofile(path)
    metrics = analyze_bin(path, fs, trim_start_s=0.1, trim_end_s=0.2)
    assert metrics["rms_v"] == pytest.approx(0.2 / np.sqrt(2), rel=0.05)
    assert metrics["trim_start_s"] == 0.1
    assert metrics["trim_end_s"] == 0.2
    assert metrics["sample_count"] == fs
    assert metrics["trimmed_sample_count"] == int(fs * 0.7)
    assert metrics["band_power_300_3400"] > 0
    assert metrics["effective_band_hz_300_3400"] == [300.0, 3400.0]
    assert metrics["wide_band_hz"] == [20.0, 3900.0]
    assert metrics["effective_wide_band_hz"] == [20.0, 3900.0]
    assert metrics["band_rms_v"] == pytest.approx(np.sqrt(metrics["band_power"]), rel=1e-9)
    assert metrics["band_rms_300_3400_v"] == pytest.approx(np.sqrt(metrics["band_power_300_3400"]), rel=1e-9)
    assert metrics["band_rms_20_3900_v"] == pytest.approx(np.sqrt(metrics["band_power_20_3900"]), rel=1e-9)
    assert metrics["dominant_tone_rms_pm50_v"] == pytest.approx(np.sqrt(metrics["dominant_tone_power_pm50"]), rel=1e-9)
    assert metrics["dominant_freq_hz"] == pytest.approx(1000, abs=10)
    assert metrics["dominant_tone_band_hz"] == pytest.approx([950.0, 1050.0], abs=10)


def test_analysis_reports_missing_scipy_as_dependency_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fs = 8000
    path = tmp_path / "tone.bin"
    np.zeros(fs, dtype="<f8").tofile(path)

    import app.services.analyzer as analyzer_module

    def missing_scipy():
        raise ImportError("No module named scipy")

    monkeypatch.setattr(analyzer_module, "_load_scipy_signal", missing_scipy)
    with pytest.raises(RuntimeError, match="SciPy is required for Welch PSD analysis"):
        analyze_bin(path, fs)


def test_analysis_honors_remove_dc_setting(tmp_path: Path):
    fs = 8000
    t = np.arange(fs) / fs
    x = (1.0 + 0.2 * np.sin(2 * np.pi * 1000 * t)).astype("<f8")
    path = tmp_path / "dc_tone.bin"
    x.tofile(path)
    removed = analyze_bin(path, fs, remove_dc=True)
    kept = analyze_bin(path, fs, remove_dc=False)
    assert removed["remove_dc"] is True
    assert kept["remove_dc"] is False
    assert removed["dc_offset_v"] == pytest.approx(1.0, abs=1e-6)
    assert removed["rms_v"] == pytest.approx(0.2 / np.sqrt(2), rel=0.05)
    assert kept["rms_v"] == pytest.approx(np.sqrt(1.0**2 + (0.2 / np.sqrt(2)) ** 2), rel=0.05)
    assert kept["rms_v"] > removed["rms_v"]


def test_analysis_quality_flags_for_clipping_and_sample_mismatch(tmp_path: Path):
    fs = 8000
    clipped = np.full(fs // 2, 9.9, dtype="<f8")
    path = tmp_path / "clipped.bin"
    clipped.tofile(path)
    metrics = analyze_bin(path, fs, full_scale_volts=10.0, expected_duration_s=1.0)
    assert "clipping_possible" in metrics["quality_flags"]
    assert "sample_count_mismatch" in metrics["quality_flags"]
    assert metrics["expected_sample_count"] == fs


def test_analysis_flags_and_clips_primary_band_above_nyquist(tmp_path: Path):
    fs = 4000
    t = np.arange(fs) / fs
    x = (0.2 * np.sin(2 * np.pi * 1000 * t)).astype("<f8")
    path = tmp_path / "low_rate.bin"
    x.tofile(path)

    metrics = analyze_bin(path, fs, band_hz=(300.0, 3400.0))

    assert metrics["band_hz"] == [300.0, 3400.0]
    assert metrics["effective_band_hz"] == [300.0, 2000.0]
    assert metrics["effective_band_hz_300_3400"] == [300.0, 2000.0]
    assert metrics["wide_band_hz"] == [20.0, 3900.0]
    assert metrics["effective_wide_band_hz"] == [20.0, 2000.0]
    assert "analysis_band_exceeds_nyquist" in metrics["quality_flags"]
    assert metrics["band_power"] > 0
    assert metrics["dominant_freq_hz"] == pytest.approx(1000, abs=10)


def test_mock_record_finalize_export_zip(tmp_path: Path):
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "export test")
    run = create_run_metadata(
        tmp_path,
        session["session_id"],
        carrier_freq_khz=25,
        uj="uj0",
        duration_s=0.5,
        trim_start_s=0.01,
        trim_end_s=0.02,
        analysis_band_low_hz=1000,
        analysis_band_high_hz=2000,
    )
    final = record_mock_and_finalize(tmp_path, run)
    base = session_dir(tmp_path, session["session_id"])
    assert (base / final["files"]["bin"]).exists()
    assert final["recording"]["actual_sample_rate_hz"] == final["recording"]["sample_rate_hz"]
    assert final["recording"]["written_samples"] == int(final["recording"]["sample_rate_hz"] * final["recording"]["duration_s"])
    assert final["recording"]["raw_size_bytes"] == (base / final["files"]["bin"]).stat().st_size
    assert final["recording"]["raw_sample_count"] == final["recording"]["written_samples"]
    assert final["recording"]["raw_dtype"] == "<f8"
    assert final["recording"]["raw_validated_at"]
    assert (base / final["files"]["wav_peak"]).name.endswith("__scale-peak.wav")
    assert (base / final["files"]["wav_range"]).name.endswith("__scale-range-fs10V.wav")
    assert final["conversion"]["outputs"]["wav_peak"]["purpose"] == "listening_preview_only"
    assert final["conversion"]["outputs"]["wav_peak"]["quantitative_use"] == "do_not_use_for_final_attenuation"
    assert final["conversion"]["outputs"]["wav_range"]["purpose"] == "cross_check_only"
    assert final["conversion"]["outputs"]["wav_range"]["full_scale_volts"] == 10.0
    assert final["analysis"]["status"] == "finalized"
    assert final["analysis"]["preview_only"] is False
    assert final["analysis"]["result_grade"] == "report-grade"
    assert final["analysis"]["finalized_from_saved_bin"] is True
    assert final["analysis"]["finalization_trigger"] == "recording_finished"
    assert final["files"]["waveform_svg"] == f"plots/{final['run_id']}_waveform.svg"
    assert final["files"]["psd_svg"] == f"plots/{final['run_id']}_psd.svg"
    assert final["files"]["spectrogram_svg"] == f"plots/{final['run_id']}_spectrogram.svg"
    finalized_events = [row for row in read_jsonl(base / "runs.jsonl") if row["event"] == "run_finalized"]
    assert finalized_events[-1]["finished_at"] == final["analysis"]["finalized_at"]
    assert finalized_events[-1]["metrics_path"] == final["files"]["metrics_json"]
    metrics = read_json(base / final["files"]["metrics_json"])
    assert "Report-grade" in metrics["label"]
    assert metrics["result_grade"] == "report-grade"
    assert metrics["preview_only"] is False
    assert metrics["finalized_from_saved_bin"] is True
    assert metrics["metrics_source"] == "saved_raw_bin"
    assert metrics["raw_bin_path"] == final["files"]["bin"]
    assert metrics["raw_sample_count"] == final["recording"]["raw_sample_count"]
    assert metrics["raw_dtype"] == "<f8"
    assert metrics["finalization_trigger"] == "recording_finished"
    assert metrics["psd_freq_hz"]
    assert metrics["band_hz"] == [1000.0, 2000.0]
    assert "1000-2000 Hz" in (base / final["files"]["psd_svg"]).read_text(encoding="utf-8")
    with (base / "summary.csv").open("r", encoding="utf-8", newline="") as f:
        summary_row = next(csv.DictReader(f))
    assert "band_rms_300_3400_v" in summary_row
    assert "remove_dc" in summary_row
    assert summary_row["remove_dc"] == "True"
    assert summary_row["primary_band_hz"] == "[1000.0, 2000.0]"
    assert summary_row["effective_primary_band_hz"] == "[1000.0, 2000.0]"
    assert summary_row["trim_start_s"] == "0.01"
    assert summary_row["trim_end_s"] == "0.02"
    assert summary_row["trim_window_s"] == "[0.01, 0.02]"
    assert int(summary_row["sample_count"]) == final["recording"]["raw_sample_count"]
    assert int(summary_row["trimmed_sample_count"]) < final["recording"]["raw_sample_count"]
    assert float(summary_row["primary_band_power"]) > 0
    assert float(summary_row["primary_band_rms_v"]) > 0
    assert summary_row["dominant_tone_band_hz"].startswith("[")
    run_zip = make_run_zip(tmp_path, session["session_id"], final["run_id"], tmp_path / "run.zip")
    with zipfile.ZipFile(run_zip) as zf:
        names = zf.namelist()
        run_manifest = json.loads(zf.read(next(name for name in names if name.endswith("export_manifest.json"))))
    assert any(name.endswith("export_manifest.json") for name in names)
    assert f"{final['run_id']}/export_manifest.json" in run_manifest["included_files"]
    assert any(name.endswith(f"bin/{final['run_id']}.bin") for name in names)
    assert any(name.endswith(f"plots/{final['run_id']}_waveform.svg") for name in names)
    assert "Raw .bin float64 voltage is the primary quantitative source" in run_manifest["notes"]
    session_zip = make_session_zip(tmp_path, session["session_id"], tmp_path / "session.zip")
    assert session_zip.exists()
    with zipfile.ZipFile(session_zip) as zf:
        session_names = zf.namelist()
        session_manifest = json.loads(zf.read(f"{session['session_id']}/export_manifest.json"))
        embedded_run_manifest = json.loads(zf.read(f"{session['session_id']}/runs/{final['run_id']}/export_manifest.json"))
        report_from_zip = zf.read(f"{session['session_id']}/session_report.md").decode("utf-8")
    assert f"{session['session_id']}/session.json" in session_names
    assert f"{session['session_id']}/runs/{final['run_id']}/bin/{final['run_id']}.bin" in session_names
    assert f"{session['session_id']}/runs/{final['run_id']}/metadata/{final['run_id']}.json" in session_names
    assert f"{session['session_id']}/runs/{final['run_id']}/export_manifest.json" in session_names
    assert f"{session['session_id']}/export_manifest.json" in session_manifest["included_files"]
    assert f"{session['session_id']}/runs/{final['run_id']}/export_manifest.json" in session_manifest["included_files"]
    assert f"{session['session_id']}/runs/{final['run_id']}/export_manifest.json" in embedded_run_manifest["included_files"]
    assert f"{session['session_id']}/runs/{final['run_id']}/bin/{final['run_id']}.bin" in embedded_run_manifest["included_files"]
    report_text = (base / "session_report.md").read_text(encoding="utf-8")
    assert report_text.startswith("# MiCloaker Session Report")
    assert "Primary Band Hz" in report_text
    assert "Effective Band Hz" in report_text
    assert "Remove DC" in report_text
    assert "Trim S" in report_text
    assert "Trimmed Samples" in report_text
    assert "Dominant Tone Band Hz" in report_text
    assert "[1000.0, 2000.0]" in report_text
    assert "300-3400 Hz RMS V" in report_text
    assert "Saved `.bin` float64 voltage data is the primary quantitative source." in report_text
    assert "Peak-normalized WAV files are listening/preview only" in report_text
    assert "Range WAV files are cross-check sources only when full-scale voltage is known." in report_text
    assert report_from_zip == report_text
    app_events = read_jsonl(tmp_path / ".micloaker" / "app_events.jsonl")
    assert [row["event"] for row in app_events if row["event"] in {"session_created", "run_created", "run_finalized", "run_zip_exported", "session_zip_exported"}]
    app_log = (tmp_path / ".micloaker" / "app.log").read_text(encoding="utf-8")
    assert "run_finalized" in app_log
    assert "session_zip_exported" in app_log
    with pytest.raises(FileExistsError):
        record_mock_and_finalize(tmp_path, final)


def test_zip_manifests_report_configured_missing_scale_mode_artifacts(tmp_path: Path):
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "missing export manifest")
    both_run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", scale_mode="both")
    range_run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj1", scale_mode="range")
    base = session_dir(tmp_path, session["session_id"])
    compare_id = "manual_compare_missing"
    atomic_write_json(base / "comparisons" / f"{compare_id}.json", {
        "compare_id": compare_id,
        "source": "bin",
        "result_grade": "report-grade",
        "plots": {
            "attenuation_png": f"comparisons/{compare_id}_attenuation.png",
            "psd_overlay_svg": f"comparisons/{compare_id}_psd_overlay.svg",
        },
    })

    run_zip = make_run_zip(tmp_path, session["session_id"], both_run["run_id"], tmp_path / "pending_run.zip")
    with zipfile.ZipFile(run_zip) as zf:
        manifest = json.loads(zf.read(f"{both_run['run_id']}/export_manifest.json"))
    assert f"{both_run['run_id']}/{both_run['files']['wav_peak']}" in manifest["missing_files"]
    assert f"{both_run['run_id']}/{both_run['files']['wav_range']}" in manifest["missing_files"]

    range_zip = make_run_zip(tmp_path, session["session_id"], range_run["run_id"], tmp_path / "range_pending_run.zip")
    with zipfile.ZipFile(range_zip) as zf:
        range_manifest = json.loads(zf.read(f"{range_run['run_id']}/export_manifest.json"))
    assert f"{range_run['run_id']}/{range_run['files']['wav_range']}" in range_manifest["missing_files"]
    assert f"{range_run['run_id']}/{range_run['files']['wav_peak']}" not in range_manifest["missing_files"]

    session_zip = make_session_zip(tmp_path, session["session_id"], tmp_path / "pending_session.zip")
    with zipfile.ZipFile(session_zip) as zf:
        session_manifest = json.loads(zf.read(f"{session['session_id']}/export_manifest.json"))
        both_embedded_manifest = json.loads(zf.read(f"{session['session_id']}/runs/{both_run['run_id']}/export_manifest.json"))
        range_embedded_manifest = json.loads(zf.read(f"{session['session_id']}/runs/{range_run['run_id']}/export_manifest.json"))
    assert f"{session['session_id']}/runs/{both_run['run_id']}/{both_run['files']['wav_range']}" in session_manifest["missing_files"]
    assert f"{session['session_id']}/runs/{range_run['run_id']}/{range_run['files']['wav_peak']}" not in session_manifest["missing_files"]
    assert f"{session['session_id']}/comparisons/{compare_id}.json" in session_manifest["included_files"]
    assert f"{session['session_id']}/comparisons/{compare_id}.csv" in session_manifest["missing_files"]
    assert f"{session['session_id']}/comparisons/{compare_id}_attenuation.png" in session_manifest["missing_files"]
    assert f"{session['session_id']}/comparisons/{compare_id}_psd_overlay.svg" in session_manifest["missing_files"]
    assert f"{session['session_id']}/runs/{both_run['run_id']}/{both_run['files']['wav_peak']}" in both_embedded_manifest["missing_files"]
    assert f"{session['session_id']}/runs/{range_run['run_id']}/{range_run['files']['wav_peak']}" not in range_embedded_manifest["missing_files"]

    multi_zip = make_multi_session_zip(tmp_path, [session["session_id"]], tmp_path / "pending_multi.zip")
    with zipfile.ZipFile(multi_zip) as zf:
        nested_manifest = json.loads(zf.read(f"{session['session_id']}/export_manifest.json"))
        top_manifest = json.loads(zf.read("export_manifest.json"))
        multi_embedded_manifest = json.loads(zf.read(f"{session['session_id']}/runs/{both_run['run_id']}/export_manifest.json"))
    expected_missing = f"{session['session_id']}/runs/{both_run['run_id']}/{both_run['files']['wav_range']}"
    assert expected_missing in nested_manifest["missing_files"]
    assert expected_missing in top_manifest["missing_files"]
    assert expected_missing in multi_embedded_manifest["missing_files"]
    assert f"{session['session_id']}/comparisons/{compare_id}.csv" in nested_manifest["missing_files"]
    assert f"{session['session_id']}/comparisons/{compare_id}.csv" in top_manifest["missing_files"]
    assert f"{session['session_id']}/runs/{range_run['run_id']}/{range_run['files']['wav_peak']}" not in top_manifest["missing_files"]


def test_zip_exports_reject_unsafe_metadata_paths(tmp_path: Path):
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "unsafe export paths")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0")
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    run["files"]["bin"] = "../outside.bin"
    base = session_dir(tmp_path, session["session_id"])
    atomic_write_json(base / "metadata" / f"{run['run_id']}.json", run)

    run_zip = make_run_zip(tmp_path, session["session_id"], run["run_id"], tmp_path / "unsafe_run.zip")
    with zipfile.ZipFile(run_zip) as zf:
        names = zf.namelist()
        manifest = json.loads(zf.read(f"{run['run_id']}/export_manifest.json"))
    assert "../" not in "\n".join(names)
    assert not any(name.startswith("/") for name in names)
    assert not any(name.endswith("outside.bin") for name in names)
    assert any(name.startswith("unsafe_path/") for name in manifest["missing_files"])
    assert manifest["unsafe_files"] == [item for item in manifest["missing_files"] if item.startswith("unsafe_path/")]

    session_zip = make_session_zip(tmp_path, session["session_id"], tmp_path / "unsafe_session.zip")
    with zipfile.ZipFile(session_zip) as zf:
        session_names = zf.namelist()
        session_manifest = json.loads(zf.read(f"{session['session_id']}/export_manifest.json"))
    assert "../" not in "\n".join(session_names)
    assert not any(name.startswith("/") for name in session_names)
    assert any(name.startswith("unsafe_path/") for name in session_manifest["missing_files"])
    assert session_manifest["unsafe_files"] == [item for item in session_manifest["missing_files"] if item.startswith("unsafe_path/")]


def test_zip_exports_tolerate_malformed_run_metadata(tmp_path: Path):
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "malformed export metadata")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0")
    base = session_dir(tmp_path, session["session_id"])
    metadata_path = base / "metadata" / f"{run['run_id']}.json"
    metadata_path.write_text("{bad metadata\n", encoding="utf-8")

    run_zip = make_run_zip(tmp_path, session["session_id"], run["run_id"], tmp_path / "malformed_run.zip")
    with zipfile.ZipFile(run_zip) as zf:
        names = zf.namelist()
        manifest = json.loads(zf.read(f"{run['run_id']}/export_manifest.json"))
    assert f"{run['run_id']}/metadata/{run['run_id']}.json" in names
    assert f"{run['run_id']}/bin/{run['run_id']}.bin" in manifest["missing_files"]

    session_zip = make_session_zip(tmp_path, session["session_id"], tmp_path / "malformed_session.zip")
    with zipfile.ZipFile(session_zip) as zf:
        session_names = zf.namelist()
        session_manifest = json.loads(zf.read(f"{session['session_id']}/export_manifest.json"))
    assert f"{session['session_id']}/runs/{run['run_id']}/metadata/{run['run_id']}.json" in session_names
    assert f"{session['session_id']}/runs/{run['run_id']}/bin/{run['run_id']}.bin" in session_manifest["missing_files"]


def test_export_routes_validate_targets_and_return_structured_missing_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "route exports")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", duration_s=0.1)
    final = record_mock_and_finalize(tmp_path, run)
    client = TestClient(create_app())

    session_zip = client.get(f"/exports/sessions/{session['session_id']}.zip")
    assert session_zip.status_code == 200
    assert f'filename="{session["session_id"]}.zip"' in session_zip.headers["content-disposition"]
    run_zip = client.get(f"/exports/sessions/{session['session_id']}/runs/{final['run_id']}.zip")
    assert run_zip.status_code == 200
    assert f'filename="{final["run_id"]}.zip"' in run_zip.headers["content-disposition"]
    repeated_run_zip = client.get(f"/exports/sessions/{session['session_id']}/runs/{final['run_id']}.zip")
    assert repeated_run_zip.status_code == 200
    assert f'filename="{final["run_id"]}_02.zip"' in repeated_run_zip.headers["content-disposition"]
    repeated_session_zip = client.get(f"/exports/sessions/{session['session_id']}.zip")
    assert repeated_session_zip.status_code == 200
    assert f'filename="{session["session_id"]}_02.zip"' in repeated_session_zip.headers["content-disposition"]
    assert (tmp_path / "uploads" / f"{final['run_id']}.zip").exists()
    assert (tmp_path / "uploads" / f"{final['run_id']}_02.zip").exists()
    assert (tmp_path / "uploads" / f"{session['session_id']}.zip").exists()
    assert (tmp_path / "uploads" / f"{session['session_id']}_02.zip").exists()

    missing_session = client.get("/exports/sessions/missing_session.zip")
    assert missing_session.status_code == 404
    detail = missing_session.json()["detail"]
    assert detail["error_code"] == "SESSION_NOT_FOUND"
    assert "Sessions page" in detail["suggestion"]

    missing_run = client.get(f"/exports/sessions/{session['session_id']}/runs/missing_run.zip")
    assert missing_run.status_code == 404
    detail = missing_run.json()["detail"]
    assert detail["error_code"] == "RUN_NOT_FOUND"
    assert session["session_id"] in detail["message"]
    assert not (tmp_path / "uploads" / "missing_run.zip").exists()


def test_session_file_route_supports_individual_artifact_downloads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "individual downloads")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", duration_s=0.1)
    final = record_mock_and_finalize(tmp_path, run)
    client = TestClient(create_app())

    required_artifacts = [
        final["files"]["bin"],
        final["files"]["wav_peak"],
        final["files"]["wav_range"],
        f"metadata/{final['run_id']}.json",
        final["files"]["metrics_json"],
        final["files"]["metrics_csv"],
        final["files"]["waveform_png"],
        final["files"]["waveform_svg"],
        final["files"]["psd_png"],
        final["files"]["psd_svg"],
        final["files"]["spectrogram_png"],
        final["files"]["spectrogram_svg"],
        f"logs/{final['run_id']}.log",
    ]
    for rel_path in required_artifacts:
        response = client.get(f"/sessions/{session['session_id']}/files/{rel_path}?download=1")
        assert response.status_code == 200, rel_path
        assert "attachment" in response.headers["content-disposition"], rel_path
        assert f'filename="{Path(rel_path).name}"' in response.headers["content-disposition"], rel_path

    inline = client.get(f"/sessions/{session['session_id']}/files/{final['files']['wav_peak']}")
    assert inline.status_code == 200
    assert "inline" in inline.headers["content-disposition"]
    blocked = client.get(f"/sessions/{session['session_id']}/files/../session.json?download=1")
    assert blocked.status_code == 404

    files_page = client.get("/files")
    assert files_page.status_code == 200
    assert f"/sessions/{session['session_id']}/files/{final['files']['bin']}?download=1" in files_page.text
    run_page = client.get(f"/sessions/{session['session_id']}/runs/{final['run_id']}")
    assert run_page.status_code == 200
    assert f"/sessions/{session['session_id']}/files/{final['files']['metrics_json']}?download=1" in run_page.text


def test_session_zip_includes_hardware_validation_records(tmp_path: Path):
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "validation export")
    record_lab_validation(
        tmp_path,
        gate="daq_smoke",
        status="pass",
        operator="lab-op",
        session_id=session["session_id"],
        run_id="daq_smoke_run",
        evidence="DAQ sample count and channel verified.",
    )

    session_zip = make_session_zip(tmp_path, session["session_id"], tmp_path / "validation_session.zip")
    with zipfile.ZipFile(session_zip) as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read(f"{session['session_id']}/export_manifest.json"))
        records = zf.read(f"{session['session_id']}/ops_validation/hardware_validation.jsonl").decode("utf-8")
        report = zf.read(f"{session['session_id']}/ops_validation/hardware_validation_report.md").decode("utf-8")
    assert f"{session['session_id']}/ops_validation/hardware_validation.jsonl" in names
    assert f"{session['session_id']}/ops_validation/hardware_validation_report.md" in names
    assert f"{session['session_id']}/ops_validation/hardware_validation.jsonl" in manifest["included_files"]
    assert "daq_smoke" in records
    assert "DAQ sample count and channel verified." in report


def test_multi_session_zip_and_no_database_files(tmp_path: Path):
    ensure_workspace(tmp_path)
    s1 = create_session(tmp_path, "one")
    s2 = create_session(tmp_path, "two")
    record_lab_validation(tmp_path, gate="attenuation_pair", status="warn", session_id=s1["session_id"], evidence="comparison pending")
    out = make_multi_session_zip(tmp_path, [s1["session_id"], s2["session_id"]], tmp_path / "multi.zip")
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        manifest = json.loads(zf.read("export_manifest.json"))
        session_manifest = json.loads(zf.read(f"{s1['session_id']}/export_manifest.json"))
    assert f"{s1['session_id']}/session.json" in names
    assert f"{s2['session_id']}/session_report.md" in names
    assert f"{s1['session_id']}/export_manifest.json" in names
    assert f"{s2['session_id']}/export_manifest.json" in names
    assert f"{s1['session_id']}/session.json" in session_manifest["included_files"]
    assert f"{s1['session_id']}/ops_validation/hardware_validation.jsonl" in session_manifest["included_files"]
    assert f"{s1['session_id']}/ops_validation/hardware_validation.jsonl" in names
    assert session_manifest["missing_files"] == []
    assert session_manifest["unsafe_files"] == []
    assert manifest["missing_files"] == []
    assert manifest["unsafe_files"] == []
    assert f"{s1['session_id']}/export_manifest.json" in manifest["included_files"]
    assert "export_manifest.json" in manifest["included_files"]
    repeat = make_multi_session_zip(tmp_path, [s1["session_id"], s2["session_id"]], tmp_path / "multi.zip")
    assert repeat.name == "multi_02.zip"
    assert out.exists()
    assert repeat.exists()
    forbidden = {".sqlite", ".sqlite3", ".db", ".duckdb"}
    assert not [p for p in tmp_path.rglob("*") if p.suffix in forbidden]
    assert read_jsonl(tmp_path / ".micloaker" / "app_events.jsonl")[-1]["event"] == "multi_session_zip_exported"


def test_multi_session_export_route_validates_selection_and_sessions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    s1 = create_session(tmp_path, "route multi one")
    s2 = create_session(tmp_path, "route multi two")
    client = TestClient(create_app())

    none = client.get("/exports/multi-session.zip")
    assert none.status_code == 400
    detail = none.json()["detail"]
    assert detail["error_code"] == "NO_SESSIONS_SELECTED"
    assert "Select one or more sessions" in detail["suggestion"]

    missing = client.get(f"/exports/multi-session.zip?session_ids={s1['session_id']}&session_ids=missing_session")
    assert missing.status_code == 404
    detail = missing.json()["detail"]
    assert detail["error_code"] == "SESSION_NOT_FOUND"
    assert "missing_session" in detail["message"]
    assert not list((tmp_path / "uploads").glob("multi_session*.zip"))

    ok = client.get(f"/exports/multi-session.zip?session_ids={s1['session_id']}&session_ids={s2['session_id']}")
    assert ok.status_code == 200
    assert 'filename="multi_session.zip"' in ok.headers["content-disposition"]
    assert (tmp_path / "uploads" / "multi_session.zip").exists()


def test_compare_known_attenuation(tmp_path: Path):
    fs = 8000
    t = np.arange(fs) / fs
    p0 = tmp_path / "uj0.bin"
    p1 = tmp_path / "uj1.bin"
    (0.2 * np.sin(2 * np.pi * 1000 * t)).astype("<f8").tofile(p0)
    (0.1 * np.sin(2 * np.pi * 1000 * t)).astype("<f8").tofile(p1)
    m0 = analyze_bin(p0, fs)
    m1 = analyze_bin(p1, fs)
    run0 = {"run_id": "uj0", "condition": {"carrier_freq_khz": 25, "sound_condition": "s", "mic_id": "m", "room": "r", "distance_cm": 1, "angle_deg": 0}}
    run1 = {"run_id": "uj1", "condition": {"carrier_freq_khz": 25, "sound_condition": "s", "mic_id": "m", "room": "r", "distance_cm": 1, "angle_deg": 0}}
    result = compare_runs(run0, m0, run1, m1)
    assert result["attenuation_db"] == pytest.approx(6.0, abs=0.4)
    assert result["remaining_fraction"] == pytest.approx(0.25, rel=0.1)
    assert result["attenuation_formula"] == "10*log10(uj0_power/uj1_power)"
    assert result["power_units"] == "V^2 integrated Welch PSD band power"
    peak_result = compare_metrics(run0, m0, run1, m1, source="peak_wav")
    assert "peak_wav_used_for_quantitative_analysis_warning" in peak_result["warnings"]


def test_compare_warns_and_auto_pair_skips_acquisition_mismatch(tmp_path: Path):
    fs = 8000
    t = np.arange(fs) / fs
    p0 = tmp_path / "uj0.bin"
    p1 = tmp_path / "uj1.bin"
    (0.2 * np.sin(2 * np.pi * 1000 * t)).astype("<f8").tofile(p0)
    (0.1 * np.sin(2 * np.pi * 1000 * t)).astype("<f8").tofile(p1)
    m0 = analyze_bin(p0, fs)
    m1 = analyze_bin(p1, fs)
    base_condition = {"carrier_freq_khz": 25, "sound_condition": "s", "mic_id": "m", "room": "r", "distance_cm": 1, "angle_deg": 0}
    run0 = {
        "run_id": "uj0",
        "created_at": "1",
        "condition": {**base_condition, "uj": "uj0"},
        "recording": {"sample_rate_hz": 8000, "actual_sample_rate_hz": 8000, "ai_range": "BIP10VOLTS", "input_mode": "SINGLE_ENDED", "channels": [0]},
        "analysis": {"status": "finalized"},
    }
    run1 = {
        "run_id": "uj1",
        "created_at": "2",
        "condition": {**base_condition, "uj": "uj1"},
        "recording": {"sample_rate_hz": 8000, "actual_sample_rate_hz": 4000, "ai_range": "BIP10VOLTS", "input_mode": "SINGLE_ENDED", "channels": [0]},
        "analysis": {"status": "finalized"},
    }
    result = compare_metrics(run0, m0, run1, m1)
    assert "metadata_mismatch" in result["warnings"]
    assert auto_pair_runs([run0, run1]) == []


def test_mac_helper_disconnected_behavior():
    result = MacHelperClient("").health()
    assert result["connected"] is False
    assert result["error_code"] == "HELPER_DISCONNECTED"


def test_mac_helper_client_preserves_structured_helper_errors(monkeypatch: pytest.MonkeyPatch):
    def fake_post(url, json, headers, timeout):
        request = httpx.Request("POST", url)
        return httpx.Response(
            400,
            json={
                "ok": False,
                "error_code": "INVALID_REQUEST",
                "message": "Invalid playback request. device_id: Field required",
                "suggestion": "Send JSON with file, device_id, sample_rate, channels, gain, and optional delay_ms.",
            },
            request=request,
        )

    monkeypatch.setattr("app.services.mac_helper_client.httpx.post", fake_post)
    result = MacHelperClient("http://helper.local").validate_playback({"file": "tone.wav"})
    assert result["ok"] is False
    assert result["error_code"] == "INVALID_REQUEST"
    assert "device_id" in result["message"]
    assert "suggestion" in result


def test_mac_helper_client_reports_non_json_helper_response(monkeypatch: pytest.MonkeyPatch):
    def fake_get(url, headers, timeout):
        request = httpx.Request("GET", url)
        return httpx.Response(502, text="<html>bad gateway</html>", request=request)

    monkeypatch.setattr("app.services.mac_helper_client.httpx.get", fake_get)
    result = MacHelperClient("http://helper.local").status()
    assert result["ok"] is False
    assert result["error_code"] == "HELPER_INVALID_RESPONSE"
    assert "non-JSON" in result["message"]
    assert "Helper URL" in result["suggestion"]


def test_mac_helper_client_sends_optional_bearer_token(monkeypatch: pytest.MonkeyPatch):
    seen = {}

    def fake_get(url, headers, timeout):
        seen["headers"] = headers
        request = httpx.Request("GET", url)
        return httpx.Response(200, json={"ok": True}, request=request)

    monkeypatch.setattr("app.services.mac_helper_client.httpx.get", fake_get)
    result = MacHelperClient("http://helper.local", "secret-token").status()
    assert result["ok"] is True
    assert seen["headers"] == {"Authorization": "Bearer secret-token"}


def test_jobs_capture_traceback_and_mark_interrupted(tmp_path: Path):
    ensure_workspace(tmp_path)
    log_path = tmp_path / "sessions" / "x" / "logs" / "bad.log"

    def fail():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        run_job(tmp_path, "bad_job", log_path, fail)
    text = log_path.read_text(encoding="utf-8")
    assert "Traceback" in text
    rows = read_jsonl(tmp_path / ".micloaker" / "jobs.jsonl")
    started = rows[-2]
    failed = rows[-1]
    for row in [started, failed]:
        for key in ["job_id", "type", "status", "created_at", "started_at", "finished_at", "logs", "error", "traceback"]:
            assert key in row
        assert row["logs"].endswith("sessions/x/logs/bad.log")
    assert started["status"] == "running"
    assert started["finished_at"] is None
    assert started["error"] is None
    assert failed["status"] == "failed"
    assert failed["error"] == "boom"
    assert "RuntimeError: boom" in failed["traceback"]
    orphan_log = tmp_path / "sessions" / "x" / "logs" / "orphan.log"
    append_jsonl(
        tmp_path / ".micloaker" / "jobs.jsonl",
        {
            "event": "job_started",
            "status": "running",
            "job_id": "job_orphan",
            "name": "orphan",
            "logs": "sessions/x/logs/orphan.log",
        },
    )
    assert mark_unfinished_jobs_interrupted(tmp_path) == 1
    interrupted = read_jsonl(tmp_path / ".micloaker" / "jobs.jsonl")[-1]
    assert interrupted["status"] == "interrupted"
    assert interrupted["type"] == "orphan"
    assert interrupted["finished_at"]
    assert interrupted["error"]
    assert "traceback" in interrupted
    assert "job_interrupted job_orphan" in orphan_log.read_text(encoding="utf-8")
    app_log = (tmp_path / ".micloaker" / "app.log").read_text(encoding="utf-8")
    assert "job_started" in app_log
    assert "job_failed" in app_log
    assert "job_interrupted job_orphan" in app_log


def test_successful_jobs_are_logged_to_app_log(tmp_path: Path):
    ensure_workspace(tmp_path)
    log_path = tmp_path / "sessions" / "x" / "logs" / "ok.log"
    result = run_job(tmp_path, "ok_job", log_path, lambda: {"ok": True})
    assert result == {"ok": True}
    app_log = (tmp_path / ".micloaker" / "app.log").read_text(encoding="utf-8")
    assert "job_started" in app_log
    assert "job_finished" in app_log
    assert "ok_job" in app_log


def test_run_job_rejects_log_paths_outside_workspace(tmp_path: Path):
    ensure_workspace(tmp_path)
    outside_log = tmp_path.parent / "outside_run_job.log"
    outside_log.unlink(missing_ok=True)
    with pytest.raises(ValueError, match="inside the workspace"):
        run_job(tmp_path, "outside_log_job", outside_log, lambda: {"ok": True})
    assert not outside_log.exists()
    assert read_jsonl(tmp_path / ".micloaker" / "jobs.jsonl") == []


def test_interrupted_job_marker_ignores_log_paths_outside_workspace(tmp_path: Path):
    ensure_workspace(tmp_path)
    outside_log = tmp_path.parent / "outside_job.log"
    outside_log.unlink(missing_ok=True)
    append_jsonl(
        tmp_path / ".micloaker" / "jobs.jsonl",
        {
            "event": "job_started",
            "status": "running",
            "job_id": "job_outside",
            "name": "outside",
            "logs": str(outside_log),
        },
    )
    assert mark_unfinished_jobs_interrupted(tmp_path) == 1
    assert not outside_log.exists()


def test_uldaq_is_lazy_and_app_routes_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    sys.modules.pop("uldaq", None)
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    app = create_app()
    assert "uldaq" not in sys.modules
    client = TestClient(app)
    for path in ["/", "/sessions", "/runs/new", "/files", "/compare", "/live", "/logs", "/mac-helper", "/ops"]:
        response = client.get(path)
        assert response.status_code == 200
    ops_page = client.get("/ops")
    assert "Web shutdown" in ops_page.text
    assert "Lab Readiness" in ops_page.text
    assert "Workspace Text Files" in ops_page.text
    assert "disabled" in ops_page.text
    readiness = client.get("/ops/readiness").json()
    assert readiness["ok"] is True
    assert readiness["summary"]["fail"] == 0
    assert any(check["key"] == "daq_backend" for check in readiness["checks"])
    assert "HARDWARE_VALIDATION_PROTOCOL" in readiness["manual_verification_required"][0]
    assert any("DAQ" in item for item in readiness["manual_verification_required"])
    shutdown = client.post("/ops/shutdown")
    assert shutdown.status_code == 403
    assert shutdown.json()["detail"]["error_code"] == "WEB_SHUTDOWN_DISABLED"
    assert "Multi-Session Export" in client.get("/sessions").text
    daq = client.get("/daq/health").json()
    assert daq["ok"] is True
    assert "uldaq" not in sys.modules
    assert client.get("/recording/status").json()["active"] is False


def test_ops_records_hardware_validation_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    app = create_app()
    client = TestClient(app)

    page = client.get("/ops")
    assert page.status_code == 200
    assert "Hardware Validation Records" in page.text
    assert "No physical validation records yet." in page.text

    response = client.post(
        "/ops/validation",
        data={
            "gate": "daq_smoke",
            "status": "pass",
            "operator": "lab-op",
            "session_id": "hardware_validation_20260529",
            "run_id": "260529-DAQ-smoke",
            "evidence": "written_samples matched expected duration; no traceback",
            "notes": "DAQ channel 0 BIP10VOLTS verified.",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/ops#hardware-validation"

    records = read_jsonl(tmp_path / ".micloaker" / "hardware_validation.jsonl")
    assert records[-1]["event"] == "hardware_validation_recorded"
    assert records[-1]["gate"] == "daq_smoke"
    assert records[-1]["status"] == "pass"
    assert records[-1]["run_id"] == "260529-DAQ-smoke"
    report = (tmp_path / ".micloaker" / "hardware_validation_report.md").read_text(encoding="utf-8")
    assert "MiCloaker Hardware Validation Records" in report
    assert "Linux DAQ smoke capture" in report
    assert "written_samples matched expected duration" in report

    status = client.get("/ops/validation").json()
    assert status["summary"]["record_count"] == 1
    assert status["summary"]["latest_by_gate"]["daq_smoke"]["status"] == "pass"
    assert status["summary"]["status_counts"]["pass"] == 1
    assert status["summary"]["status_counts"]["na"] == 0
    assert status["summary"]["status_counts"]["missing"] == 4
    jsonl_download = client.get("/ops/validation/files/hardware_validation.jsonl")
    assert jsonl_download.status_code == 200
    assert "hardware_validation.jsonl" in jsonl_download.headers["content-disposition"]
    assert "daq_smoke" in jsonl_download.text
    report_download = client.get("/ops/validation/files/hardware_validation_report.md")
    assert report_download.status_code == 200
    assert "MiCloaker Hardware Validation Records" in report_download.text
    blocked_download = client.get("/ops/validation/files/../app.log")
    assert blocked_download.status_code == 404
    readiness = client.get("/ops/readiness").json()
    validation_check = [check for check in readiness["checks"] if check["key"] == "hardware_validation_records"][0]
    assert validation_check["level"] == "WARN"
    assert "4 missing gate" in validation_check["message"]

    fail_response = client.post(
        "/ops/validation",
        data={"gate": "mac_playback", "status": "fail", "evidence": "device_id did not route audio"},
        follow_redirects=False,
    )
    assert fail_response.status_code == 303
    failed_readiness = client.get("/ops/readiness").json()
    failed_validation_check = [check for check in failed_readiness["checks"] if check["key"] == "hardware_validation_records"][0]
    assert failed_readiness["ok"] is False
    assert failed_validation_check["level"] == "FAIL"
    assert "1 fail" in failed_validation_check["message"]

    for gate in ["mac_playback", "play_and_record", "attenuation_pair", "legacy_parity"]:
        response = client.post(
            "/ops/validation",
            data={"gate": gate, "status": "na", "evidence": "not part of this Linux-only validation run"},
            follow_redirects=False,
        )
        assert response.status_code == 303
    na_readiness = client.get("/ops/readiness").json()
    na_validation_check = [check for check in na_readiness["checks"] if check["key"] == "hardware_validation_records"][0]
    assert na_validation_check["level"] == "PASS"
    assert "4 not applicable" in na_validation_check["message"]
    na_status = client.get("/ops/validation").json()
    assert na_status["summary"]["status_counts"]["na"] == 4
    assert na_status["summary"]["status_counts"]["missing"] == 0

    bad = client.post("/ops/validation", data={"gate": "bad_gate", "status": "pass"})
    assert bad.status_code == 400
    assert bad.json()["detail"]["error_code"] == "INVALID_VALIDATION_RECORD"


def test_lab_readiness_cli_reflects_validation_gate_status(tmp_path: Path):
    ensure_workspace(tmp_path)
    env = {**os.environ, "MICLOAKER_WORKSPACE": str(tmp_path)}

    no_records = subprocess.run([sys.executable, "scripts/lab_readiness_check.py"], cwd=Path(__file__).resolve().parents[1], env=env, text=True, capture_output=True, check=False)
    assert no_records.returncode == 0
    assert "WARN: hardware_validation_records: No physical validation records saved yet" in no_records.stdout

    record_lab_validation(tmp_path, gate="daq_smoke", status="pass", evidence="DAQ smoke passed")
    record_lab_validation(tmp_path, gate="mac_playback", status="fail", evidence="Mac playback failed")
    failed = subprocess.run([sys.executable, "scripts/lab_readiness_check.py"], cwd=Path(__file__).resolve().parents[1], env=env, text=True, capture_output=True, check=False)
    assert failed.returncode == 1
    assert "1 pass, 0 not applicable, 0 warn, 1 fail, 3 missing gate" in failed.stdout
    assert "FAIL: validation_mac_playback" in failed.stdout

    for gate in ["mac_playback", "play_and_record", "attenuation_pair", "legacy_parity"]:
        record_lab_validation(tmp_path, gate=gate, status="na", evidence="not applicable")
    passed = subprocess.run([sys.executable, "scripts/lab_readiness_check.py"], cwd=Path(__file__).resolve().parents[1], env=env, text=True, capture_output=True, check=False)
    assert passed.returncode == 0
    assert "1 pass, 4 not applicable, 0 warn, 0 fail, 0 missing gate" in passed.stdout


def test_new_run_page_can_create_and_record_daq_failure_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "create daq from form")

    def unavailable(**kwargs):
        from app.services.daq import DaqUnavailableError

        raise DaqUnavailableError("no DAQ from create")

    monkeypatch.setattr(recorder_module, "record_voltage", unavailable)
    client = TestClient(create_app())
    page = client.get(f"/runs/new?session_id={session['session_id']}")
    assert page.status_code == 200
    assert "Create + Record DAQ" in page.text

    response = client.post(
        f"/sessions/{session['session_id']}/runs",
        data={
            "carrier_freq_khz": "25",
            "uj": "uj0",
            "duration_s": "0.1",
            "sample_rate_hz": "8000",
            "scale_mode": "both",
            "record_after_create_source": "daq",
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"]["error_code"] == "DAQ_UNAVAILABLE"
    runs = load_runs(tmp_path, session["session_id"])
    assert len(runs) == 1
    saved = runs[0]
    assert saved["recording"]["source"] == "daq"
    assert saved["recording"]["last_attempted_source"] == "daq"
    assert saved["analysis"]["status"] == "failed"
    assert saved["analysis"]["failure_stage"] == "recording"
    assert saved["analysis"]["recording_source_attempted"] == "daq"
    base = session_dir(tmp_path, session["session_id"])
    assert not (base / saved["files"]["bin"]).exists()
    assert "recording_failed source=daq" in (base / "logs" / f"{saved['run_id']}.log").read_text(encoding="utf-8")


def test_module_entrypoint_uses_localhost_default_and_env_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    calls = []

    def fake_run(app, *, host, port):
        calls.append({"app": app, "host": host, "port": port})

    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=fake_run))
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("MICLOAKER_HOST", raising=False)
    monkeypatch.delenv("MICLOAKER_PORT", raising=False)

    main_module.run_console()

    assert calls[-1]["host"] == "127.0.0.1"
    assert calls[-1]["port"] == 8000

    monkeypatch.setenv("MICLOAKER_HOST", "127.0.0.2")
    monkeypatch.setenv("MICLOAKER_PORT", "8123")
    main_module.run_console()

    assert calls[-1]["host"] == "127.0.0.2"
    assert calls[-1]["port"] == 8123


def test_daq_health_detects_installed_backend_without_importing_uldaq(monkeypatch: pytest.MonkeyPatch):
    sys.modules.pop("uldaq", None)
    monkeypatch.setattr(daq_module.importlib.util, "find_spec", lambda name: object() if name == "uldaq" else None)

    health = daq_module.daq_health()

    assert health["ok"] is True
    assert health["available"] is True
    assert health["backend"] == "uldaq"
    assert health["mode"] == "real"
    assert "recording starts" in health["message"]
    assert "uldaq" not in sys.modules


def test_recording_routes_return_structured_conflict_when_raw_bin_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    sys.modules.pop("uldaq", None)
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "route raw overwrite")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", duration_s=0.1)
    client = TestClient(create_app())

    first = client.post(f"/sessions/{session['session_id']}/runs/{run['run_id']}/record-mock", follow_redirects=False)
    assert first.status_code == 303
    second = client.post(f"/sessions/{session['session_id']}/runs/{run['run_id']}/record-mock")
    assert second.status_code == 409
    detail = second.json()["detail"]
    assert detail["error_code"] == "RAW_BIN_EXISTS"
    assert "never overwritten silently" in detail["suggestion"]

    daq = client.post(f"/sessions/{session['session_id']}/runs/{run['run_id']}/record-daq")
    assert daq.status_code == 409
    assert daq.json()["detail"]["error_code"] == "RAW_BIN_EXISTS"
    assert "uldaq" not in sys.modules


def test_logs_page_lists_and_views_run_logs_safely(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "logs")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", duration_s=0.1)
    final = record_mock_and_finalize(tmp_path, run)
    append_app_event(
        tmp_path,
        "mac_helper_client_action",
        session_id=session["session_id"],
        run_id=final["run_id"],
        action="validate_playback",
        ok=False,
        error_code="HELPER_DISCONNECTED",
    )
    client = TestClient(create_app())
    page = client.get("/logs")
    assert page.status_code == 200
    rel = f"sessions/{session['session_id']}/logs/{final['run_id']}.log"
    assert rel in page.text
    assert "Job Status" in page.text
    assert "mock_record_and_finalize" in page.text
    assert "finished" in page.text
    assert f"/logs/view/{rel}" in page.text
    detail = client.get(f"/logs/view/{rel}")
    assert detail.status_code == 200
    assert "finalization_finished" in detail.text
    assert "Traceback Viewer" in detail.text
    assert "Copy Selected Log" in detail.text
    assert "Copy Tracebacks" in detail.text
    assert "Copy App/Job Events" in detail.text
    assert "== app_events.jsonl ==" in page.text
    assert "mac_helper_client_action" in page.text
    assert "Mac Helper Client Logs" in page.text
    assert "validate_playback" in page.text
    assert "HELPER_DISCONNECTED" in page.text
    assert f"/sessions/{session['session_id']}/runs/{final['run_id']}" in page.text
    assert "Diagnostic Downloads" in page.text
    for name in ["app.log", "jobs.jsonl", "app_events.jsonl"]:
        assert f"/logs/download/{name}" in page.text
        download = client.get(f"/logs/download/{name}")
        assert download.status_code == 200
        assert "attachment" in download.headers["content-disposition"]
        assert f'filename="{name}"' in download.headers["content-disposition"]
    blocked = client.get("/logs/view/../.micloaker/config.json")
    assert blocked.status_code == 404
    blocked_diagnostic = client.get("/logs/download/config.json")
    assert blocked_diagnostic.status_code == 404
    assert blocked_diagnostic.json()["detail"]["error_code"] == "DIAGNOSTIC_LOG_NOT_FOUND"
    sibling_prefix = client.get("/logs/view/sessions_bad/fake.log")
    assert sibling_prefix.status_code == 404
    missing = client.get(f"/logs/view/sessions/{session['session_id']}/logs/missing.log")
    assert missing.status_code == 404
    detail = missing.json()["detail"]
    assert detail["error_code"] == "LOG_NOT_FOUND"
    assert "Logs page" in detail["suggestion"]
    wrong_folder = session_dir(tmp_path, session["session_id"]) / "results" / "not_a_run.log"
    wrong_folder.write_text("not a run log", encoding="utf-8")
    blocked_wrong_folder = client.get(f"/logs/view/sessions/{session['session_id']}/results/not_a_run.log")
    assert blocked_wrong_folder.status_code == 404
    assert blocked_wrong_folder.json()["detail"]["error_code"] == "LOG_NOT_FOUND"


def test_logs_traceback_viewer_extracts_failed_job_traceback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "traceback")
    log_path = session_dir(tmp_path, session["session_id"]) / "logs" / "failed.log"

    def fail():
        raise RuntimeError("traceback visible")

    with pytest.raises(RuntimeError):
        run_job(tmp_path, "fail_for_log_page", log_path, fail)

    client = TestClient(create_app())
    page = client.get("/logs")
    assert page.status_code == 200
    assert "Job Status" in page.text
    assert "failed" in page.text
    assert "fail_for_log_page" in page.text
    assert f"/logs/view/sessions/{session['session_id']}/logs/failed.log" in page.text
    assert "job_id=" in page.text
    assert "fail_for_log_page" in page.text
    assert "RuntimeError: traceback visible" in page.text
    rel = f"sessions/{session['session_id']}/logs/failed.log"
    detail = client.get(f"/logs/view/{rel}")
    assert detail.status_code == 200
    assert "Traceback (most recent call last):" in detail.text
    assert "RuntimeError: traceback visible" in detail.text


def test_session_file_browser_lists_artifacts_and_blocks_traversal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "browser")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", duration_s=0.1)
    final = record_mock_and_finalize(tmp_path, run)
    outside = tmp_path / "outside_browser.bin"
    outside.write_bytes(b"outside")
    unsafe_link = session_dir(tmp_path, session["session_id"]) / "bin" / f"{final['run_id']}_linked_outside.bin"
    try:
        unsafe_link.symlink_to(outside)
    except OSError:
        unsafe_link = None
    broken_link = session_dir(tmp_path, session["session_id"]) / "results" / "broken_browser.json"
    try:
        broken_link.symlink_to(tmp_path / "missing_browser_target.json")
    except OSError:
        broken_link = None
    client = TestClient(create_app())
    page = client.get(f"/sessions/{session['session_id']}/browser")
    assert page.status_code == 200
    assert final["files"]["bin"] in page.text
    assert final["files"]["metrics_json"] in page.text
    assert "Primary quantitative data" in page.text
    assert "Listening preview only" in page.text
    assert "Scale-valid cross-check if full-scale voltage is correct" in page.text
    assert f'src="/sessions/{session["session_id"]}/files/{final["files"]["wav_peak"]}"' in page.text
    assert f'src="/sessions/{session["session_id"]}/files/{final["files"]["wav_range"]}"' in page.text
    assert f'href="/sessions/{session["session_id"]}/files/{final["files"]["wav_peak"]}?download=1"' in page.text
    if unsafe_link is not None:
        assert unsafe_link.name not in page.text
        linked_download = client.get(f"/sessions/{session['session_id']}/files/bin/{unsafe_link.name}")
        assert linked_download.status_code == 404
    if broken_link is not None:
        assert broken_link.name not in page.text
    download = client.get(f"/sessions/{session['session_id']}/files/{final['files']['metrics_json']}")
    assert download.status_code == 200
    assert download.headers["content-disposition"].startswith("inline;")
    assert Path(final["files"]["metrics_json"]).name in download.headers["content-disposition"]
    blocked = client.get(f"/sessions/{session['session_id']}/files/../session.json")
    assert blocked.status_code == 404


def test_read_only_run_and_file_routes_return_structured_missing_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "missing readonly")
    client = TestClient(create_app())

    missing_session_run = client.get("/sessions/missing_session/runs/missing_run")
    assert missing_session_run.status_code == 404
    detail = missing_session_run.json()["detail"]
    assert detail["error_code"] == "SESSION_NOT_FOUND"
    assert "missing_session" in detail["message"]

    missing_run = client.get(f"/sessions/{session['session_id']}/runs/missing_run")
    assert missing_run.status_code == 404
    detail = missing_run.json()["detail"]
    assert detail["error_code"] == "RUN_NOT_FOUND"
    assert "missing_run" in detail["message"]

    missing_browser = client.get("/sessions/missing_session/browser")
    assert missing_browser.status_code == 404
    assert missing_browser.json()["detail"]["error_code"] == "SESSION_NOT_FOUND"

    missing_file_session = client.get("/sessions/missing_session/files/results/nope.json")
    assert missing_file_session.status_code == 404
    assert missing_file_session.json()["detail"]["error_code"] == "SESSION_NOT_FOUND"

    missing_file = client.get(f"/sessions/{session['session_id']}/files/results/nope.json")
    assert missing_file.status_code == 404
    detail = missing_file.json()["detail"]
    assert detail["error_code"] == "FILE_NOT_FOUND"
    assert "results/nope.json" in detail["message"]


def test_run_detail_renders_metrics_table_and_quality_flags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    sys.modules.pop("uldaq", None)
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "run detail metrics")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", duration_s=0.1)
    final = record_mock_and_finalize(tmp_path, run)
    client = TestClient(create_app())
    page = client.get(f"/sessions/{session['session_id']}/runs/{final['run_id']}")
    assert page.status_code == 200
    for text in [
        "Metadata Summary",
        "Raw Run JSON",
        "Carrier",
        "UJ",
        "Recording source",
        "DAQ range / mode",
        "Scale modes",
        "Primary band",
        "Final Metrics",
        "Effective primary band",
        "Primary band power",
        "Primary band RMS",
        "Effective 300-3400 Hz band",
        "300-3400 Hz power",
        "300-3400 Hz RMS",
        "Effective 20-3900 Hz band",
        "20-3900 Hz RMS",
        "Dominant tone",
        "Dominant ±50 Hz RMS",
        "Quality Flags",
        "Raw Metrics JSON",
        "Report-grade metrics recomputed from saved .bin",
        "DAQ unavailable - mock recording and raw .bin upload remain available.",
        "Peak WAV: listening preview only.",
        "Range WAV: scale-valid cross-check if full-scale voltage is correct.",
        "Final waveform",
        "Final PSD",
        "Final spectrogram",
        "Artifact",
        "Raw BIN",
        "Primary quantitative source",
        "Run metadata JSON",
        "Run source-of-truth metadata",
        "Run log",
        "Job log and traceback text",
        '<span class="badge">available</span>',
        f'/sessions/{session["session_id"]}/files/{final["files"]["bin"]}',
        f'/sessions/{session["session_id"]}/files/metadata/{final["run_id"]}.json',
        f'/sessions/{session["session_id"]}/files/logs/{final["run_id"]}.log',
        f'/sessions/{session["session_id"]}/files/{final["files"]["waveform_svg"]}',
        f'/sessions/{session["session_id"]}/files/{final["files"]["psd_svg"]}',
        f'/sessions/{session["session_id"]}/files/{final["files"]["spectrogram_svg"]}',
    ]:
        assert text in page.text
    assert "uldaq" not in sys.modules


def test_pending_run_detail_does_not_link_missing_plot_previews(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "pending run detail")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", duration_s=0.1)
    client = TestClient(create_app())
    page = client.get(f"/sessions/{session['session_id']}/runs/{run['run_id']}")
    assert page.status_code == 200
    assert "No finalized plots yet." in page.text
    assert "Waveform PNG" in page.text
    assert '<span class="warn">missing</span>' in page.text
    assert f'/sessions/{session["session_id"]}/files/{run["files"]["waveform_png"]}' not in page.text


def test_run_detail_artifact_table_respects_configured_scale_modes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "scale mode artifacts")
    peak_run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", scale_mode="peak")
    range_run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj1", scale_mode="range")
    client = TestClient(create_app())

    peak_page = client.get(f"/sessions/{session['session_id']}/runs/{peak_run['run_id']}")
    assert peak_page.status_code == 200
    assert "<td>Peak WAV</td>" in peak_page.text
    assert "<td>Range WAV</td>" not in peak_page.text

    range_page = client.get(f"/sessions/{session['session_id']}/runs/{range_run['run_id']}")
    assert range_page.status_code == 200
    assert "<td>Range WAV</td>" in range_page.text
    assert "<td>Peak WAV</td>" not in range_page.text


def test_global_files_page_lists_session_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "global files")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", duration_s=0.1)
    final = record_mock_and_finalize(tmp_path, run)
    outside = tmp_path / "outside_global.bin"
    outside.write_bytes(b"outside")
    unsafe_link = session_dir(tmp_path, session["session_id"]) / "bin" / f"{final['run_id']}_linked_global.bin"
    try:
        unsafe_link.symlink_to(outside)
    except OSError:
        unsafe_link = None
    broken_link = session_dir(tmp_path, session["session_id"]) / "results" / "broken_global.json"
    try:
        broken_link.symlink_to(tmp_path / "missing_global_target.json")
    except OSError:
        broken_link = None
    client = TestClient(create_app())
    page = client.get("/files")
    assert page.status_code == 200
    assert "Workspace file browser" in page.text
    assert final["files"]["bin"] in page.text
    assert "Raw BIN" in page.text
    assert "Primary quantitative data" in page.text
    assert "Peak WAV" in page.text
    assert "Listening preview only" in page.text
    assert "Range WAV" in page.text
    assert "Scale-valid cross-check if full-scale voltage is correct" in page.text
    assert f'src="/sessions/{session["session_id"]}/files/{final["files"]["wav_peak"]}"' in page.text
    assert f'src="/sessions/{session["session_id"]}/files/{final["files"]["wav_range"]}"' in page.text
    assert f"/sessions/{session['session_id']}/files/{final['files']['metrics_json']}" in page.text
    if unsafe_link is not None:
        assert unsafe_link.name not in page.text
    if broken_link is not None:
        assert broken_link.name not in page.text
    download = client.get(f"/sessions/{session['session_id']}/files/{final['files']['bin']}")
    assert download.status_code == 200
    assert download.headers["content-disposition"].startswith("inline;")
    assert Path(final["files"]["bin"]).name in download.headers["content-disposition"]


def test_tailscale_discovery_parses_peer_urls_and_stays_best_effort(monkeypatch: pytest.MonkeyPatch):
    class Result:
        returncode = 0
        stdout = json.dumps({
            "Peer": {
                "node1": {
                    "HostName": "lab-mac",
                    "DNSName": "lab-mac.tailnet.ts.net.",
                    "OS": "macOS",
                    "TailscaleIPs": ["100.64.0.10", "fd7a::1"],
                }
            }
        })

    monkeypatch.setattr(tailscale_module.subprocess, "run", lambda *args, **kwargs: Result())
    candidates = discover_helpers()
    assert candidates == [
        {
            "hostname": "lab-mac",
            "dns_name": "lab-mac.tailnet.ts.net",
            "ip": "100.64.0.10",
            "url": "http://100.64.0.10:5050",
            "label": "lab-mac macOS",
        }
    ]

    def missing_tailscale(*args, **kwargs):
        raise FileNotFoundError("tailscale")

    monkeypatch.setattr(tailscale_module.subprocess, "run", missing_tailscale)
    assert discover_helpers() == []


def test_compare_route_saves_and_renders_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "compare route")
    run0 = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", duration_s=0.25)
    run1 = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj1", duration_s=0.25)
    final0 = record_mock_and_finalize(tmp_path, run0)
    final1 = record_mock_and_finalize(tmp_path, run1)
    client = TestClient(create_app())
    response = client.post(
        f"/compare/{session['session_id']}",
        data={"uj0_run_id": final0["run_id"], "uj1_run_id": final1["run_id"]},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Saved Results" in response.text
    assert "dB" in response.text
    assert "remaining fraction" in response.text
    assert "Bar PNG" in response.text
    assert "Bar SVG" in response.text
    assert "PSD PNG" in response.text
    assert "PSD SVG" in response.text
    assert "Attenuation bar chart" in response.text
    assert "PSD overlay" in response.text
    base = session_dir(tmp_path, session["session_id"])
    assert list((base / "comparisons").glob("*.json"))
    assert list((base / "comparisons").glob("*_psd_overlay.png"))
    assert list((base / "comparisons").glob("*_psd_overlay.svg"))
    result = read_json(next((base / "comparisons").glob("*.json")))
    assert result["created_at"]
    assert result["compare_id"]
    assert result["result_grade"] == "report-grade"
    assert "saved .bin" in result["source_label"]
    assert result["attenuation_formula"] == "10*log10(uj0_power/uj1_power)"
    assert result["power_units"] == "V^2 integrated Welch PSD band power"
    assert result["uj0_source_path"] == final0["files"]["bin"]
    assert result["uj1_source_path"] == final1["files"]["bin"]
    assert result["uj0_metrics_path"] == final0["files"]["metrics_json"]
    assert result["uj1_metrics_path"] == final1["files"]["metrics_json"]
    assert "remaining_fraction" in result
    assert "reduction_percent" in result
    assert "report-grade" in response.text
    assert "Report-grade comparison from saved .bin voltage metrics." in response.text
    assert "10*log10(uj0_power/uj1_power)" in response.text
    assert "V^2 integrated Welch PSD band power" in response.text
    assert final0["files"]["bin"] in response.text
    compare_json = f"comparisons/{result['compare_id']}.json"
    compare_csv = f"comparisons/{result['compare_id']}.csv"
    assert f'/sessions/{session["session_id"]}/files/{compare_json}?download=1' in response.text
    assert f'/sessions/{session["session_id"]}/files/{compare_csv}?download=1' in response.text
    assert f'src="/sessions/{session["session_id"]}/files/{result["plots"]["attenuation_png"]}"' in response.text
    assert f'src="/sessions/{session["session_id"]}/files/{result["plots"]["psd_overlay_png"]}"' in response.text
    assert f'/sessions/{session["session_id"]}/files/{result["plots"]["attenuation_svg"]}?download=1' in response.text
    assert f'/sessions/{session["session_id"]}/files/{result["plots"]["psd_overlay_svg"]}?download=1' in response.text
    for rel_path in [
        compare_json,
        compare_csv,
        result["plots"]["attenuation_png"],
        result["plots"]["attenuation_svg"],
        result["plots"]["psd_overlay_png"],
        result["plots"]["psd_overlay_svg"],
    ]:
        download = client.get(f"/sessions/{session['session_id']}/files/{rel_path}?download=1")
        assert download.status_code == 200, rel_path
        assert "attachment" in download.headers["content-disposition"], rel_path
    report_text = (base / "session_report.md").read_text(encoding="utf-8")
    assert "## Saved Comparisons" in report_text
    assert result["compare_id"] not in report_text
    assert result["uj0_run_id"] in report_text
    assert result["uj1_run_id"] in report_text
    assert "Attenuation dB" in report_text
    assert "Grade" in report_text
    assert "Source Label" in report_text
    assert "Formula" in report_text
    assert "Power Units" in report_text
    assert "report-grade" in report_text
    assert "Report-grade comparison from saved .bin voltage metrics." in report_text
    assert "10*log10(uj0_power/uj1_power)" in report_text
    assert "V^2 integrated Welch PSD band power" in report_text
    session_events = read_jsonl(base / "events.jsonl")
    assert session_events[-1]["event"] == "comparison_created"
    assert session_events[-1]["compare_id"] == result["compare_id"]
    app_events = read_jsonl(tmp_path / ".micloaker" / "app_events.jsonl")
    assert app_events[-1]["event"] == "comparison_created"
    assert app_events[-1]["compare_id"] == result["compare_id"]


def test_compare_csv_serializes_warnings_as_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "compare csv warnings")
    run0 = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", room="lab-a", duration_s=0.25)
    run1 = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj1", room="lab-b", duration_s=0.25)
    final0 = record_mock_and_finalize(tmp_path, run0)
    final1 = record_mock_and_finalize(tmp_path, run1)
    client = TestClient(create_app())
    response = client.post(
        f"/compare/{session['session_id']}",
        data={"uj0_run_id": final0["run_id"], "uj1_run_id": final1["run_id"], "source": "bin", "band_mode": "primary"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    base = session_dir(tmp_path, session["session_id"])
    result = read_json(next((base / "comparisons").glob("*.json")))
    assert result["warnings"] == ["metadata_mismatch"]
    with next((base / "comparisons").glob("*.csv")).open("r", encoding="utf-8", newline="") as f:
        row = next(csv.DictReader(f))
    assert row["compare_id"] == result["compare_id"]
    assert row["created_at"] == result["created_at"]
    assert row["result_grade"] == "report-grade"
    assert "saved .bin" in row["source_label"]
    assert row["attenuation_formula"] == "10*log10(uj0_power/uj1_power)"
    assert row["power_units"] == "V^2 integrated Welch PSD band power"
    assert row["warnings"] == "metadata_mismatch"
    assert "[" not in row["warnings"]


def test_compare_route_rejects_wrong_or_unfinalized_run_pairings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "compare validation")
    run0a = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", duration_s=0.1)
    run0b = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", duration_s=0.1)
    pending_uj1 = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj1", duration_s=0.1)
    run1 = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj1", duration_s=0.1)
    final0a = record_mock_and_finalize(tmp_path, run0a)
    final0b = record_mock_and_finalize(tmp_path, run0b)
    final1 = record_mock_and_finalize(tmp_path, run1)
    client = TestClient(create_app())

    same_condition = client.post(
        f"/compare/{session['session_id']}",
        data={"uj0_run_id": final0a["run_id"], "uj1_run_id": final0b["run_id"], "source": "bin", "band_mode": "primary"},
    )
    assert same_condition.status_code == 400
    detail = same_condition.json()["detail"]
    assert detail["error_code"] == "INVALID_COMPARE_PAIR"
    assert "first run to be uj0" in detail["message"]
    assert "uj0 selector" in detail["suggestion"]

    unfinalized = client.post(
        f"/compare/{session['session_id']}",
        data={"uj0_run_id": final0a["run_id"], "uj1_run_id": pending_uj1["run_id"], "source": "bin", "band_mode": "primary"},
    )
    assert unfinalized.status_code == 400
    detail = unfinalized.json()["detail"]
    assert detail["error_code"] == "RUN_NOT_FINALIZED"
    assert "must be finalized" in detail["message"]
    assert "saved .bin" in detail["suggestion"]

    peak = client.post(
        f"/compare/{session['session_id']}",
        data={"uj0_run_id": final0a["run_id"], "uj1_run_id": final1["run_id"], "source": "peak_wav", "band_mode": "primary"},
    )
    assert peak.status_code == 400
    assert peak.json()["detail"]["error_code"] == "PEAK_WAV_NOT_QUANTITATIVE"
    assert peak.json()["detail"]["warning"] == "peak_wav_used_for_quantitative_analysis_warning"
    bad_band = client.post(
        f"/compare/{session['session_id']}",
        data={"uj0_run_id": final0a["run_id"], "uj1_run_id": final1["run_id"], "source": "bin", "band_mode": "custom", "custom_low_hz": "3400", "custom_high_hz": "300"},
    )
    assert bad_band.status_code == 400
    assert bad_band.json()["detail"]["error_code"] == "INVALID_COMPARE_BAND"
    bad_source = client.post(
        f"/compare/{session['session_id']}",
        data={"uj0_run_id": final0a["run_id"], "uj1_run_id": final1["run_id"], "source": "rms_text", "band_mode": "primary"},
    )
    assert bad_source.status_code == 400
    assert bad_source.json()["detail"]["error_code"] == "INVALID_COMPARE_SOURCE"
    assert not list((session_dir(tmp_path, session["session_id"]) / "comparisons").glob("*.json"))


def test_compare_route_rejects_band_above_pair_nyquist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "compare nyquist")
    run0 = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", sample_rate_hz=4000, duration_s=0.25)
    run1 = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj1", sample_rate_hz=4000, duration_s=0.25)
    final0 = record_mock_and_finalize(tmp_path, run0)
    final1 = record_mock_and_finalize(tmp_path, run1)
    client = TestClient(create_app())

    response = client.post(
        f"/compare/{session['session_id']}",
        data={"uj0_run_id": final0["run_id"], "uj1_run_id": final1["run_id"], "source": "bin", "band_mode": "primary"},
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["error_code"] == "INVALID_COMPARE_BAND"
    assert "Nyquist" in detail["message"]
    assert "actual sample rate" in detail["suggestion"]
    assert not list((session_dir(tmp_path, session["session_id"]) / "comparisons").glob("*.json"))


def test_compare_routes_return_structured_missing_target_and_artifact_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "compare missing artifacts")
    run0 = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", duration_s=0.1)
    run1 = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj1", duration_s=0.1)
    final0 = record_mock_and_finalize(tmp_path, run0)
    final1 = record_mock_and_finalize(tmp_path, run1)
    base = session_dir(tmp_path, session["session_id"])
    client = TestClient(create_app())

    missing_session_page = client.get("/compare/missing_session")
    assert missing_session_page.status_code == 404
    assert missing_session_page.json()["detail"]["error_code"] == "SESSION_NOT_FOUND"

    missing_run = client.post(
        f"/compare/{session['session_id']}",
        data={"uj0_run_id": final0["run_id"], "uj1_run_id": "missing_run", "source": "bin", "band_mode": "primary"},
    )
    assert missing_run.status_code == 404
    detail = missing_run.json()["detail"]
    assert detail["error_code"] == "RUN_NOT_FOUND"
    assert "missing_run" in detail["message"]

    metrics_path = base / final1["files"]["metrics_json"]
    metrics_path.unlink()
    missing_metrics = client.post(
        f"/compare/{session['session_id']}",
        data={"uj0_run_id": final0["run_id"], "uj1_run_id": final1["run_id"], "source": "bin", "band_mode": "primary"},
    )
    assert missing_metrics.status_code == 400
    detail = missing_metrics.json()["detail"]
    assert detail["error_code"] == "METRICS_JSON_MISSING"
    assert "Finalize the run" in detail["suggestion"]

    # Restore the missing metrics from the saved .bin so range checks can isolate their own errors.
    final1 = read_json(base / "metadata" / f"{final1['run_id']}.json")
    final1 = finalize_run(tmp_path, final1, trigger="test_restore_missing_metrics", overwrite_derived=True)
    wav_path = base / final1["files"]["wav_range"]
    wav_path.unlink()
    missing_range = client.post(
        f"/compare/{session['session_id']}",
        data={"uj0_run_id": final0["run_id"], "uj1_run_id": final1["run_id"], "source": "range_wav", "band_mode": "primary"},
    )
    assert missing_range.status_code == 400
    detail = missing_range.json()["detail"]
    assert detail["error_code"] == "RANGE_WAV_MISSING"

    final1["conversion"]["full_scale_volts"] = 0.0
    save_run(tmp_path, final1)
    final1["conversion"]["full_scale_volts"] = 10.0
    finalize_run(tmp_path, final1, trigger="test_restore_range_wav", overwrite_derived=True)
    final1 = read_json(base / "metadata" / f"{final1['run_id']}.json")
    final1["conversion"]["full_scale_volts"] = 0.0
    save_run(tmp_path, final1)
    missing_full_scale = client.post(
        f"/compare/{session['session_id']}",
        data={"uj0_run_id": final0["run_id"], "uj1_run_id": final1["run_id"], "source": "range_wav", "band_mode": "primary"},
    )
    assert missing_full_scale.status_code == 400
    assert missing_full_scale.json()["detail"]["error_code"] == "FULL_SCALE_VOLTAGE_MISSING"


def test_compare_page_only_lists_finalized_matching_uj_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "compare ui filtered")
    uj0 = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", duration_s=0.1)
    uj1 = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj1", duration_s=0.1)
    pending_uj1 = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=32.8, uj="uj1", duration_s=0.1)
    final0 = record_mock_and_finalize(tmp_path, uj0)
    final1 = record_mock_and_finalize(tmp_path, uj1)
    client = TestClient(create_app())
    page = client.get(f"/compare/{session['session_id']}")
    assert page.status_code == 200
    assert f'<select name="uj0_run_id"><option value="{final0["run_id"]}">' in page.text
    assert f'<select name="uj1_run_id"><option value="{final1["run_id"]}">' in page.text
    assert pending_uj1["run_id"] not in page.text.split('<select name="uj1_run_id">', 1)[1].split("</select>", 1)[0]
    assert "disabled>Compute Attenuation" not in page.text


def test_repeated_compare_creates_numbered_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "repeat compare")
    run0 = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", duration_s=0.25)
    run1 = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj1", duration_s=0.25)
    final0 = record_mock_and_finalize(tmp_path, run0)
    final1 = record_mock_and_finalize(tmp_path, run1)
    client = TestClient(create_app())
    payload = {"uj0_run_id": final0["run_id"], "uj1_run_id": final1["run_id"], "source": "bin", "band_mode": "primary"}
    first = client.post(f"/compare/{session['session_id']}", data=payload, follow_redirects=False)
    second = client.post(f"/compare/{session['session_id']}", data=payload, follow_redirects=False)
    assert first.status_code == 303
    assert second.status_code == 303
    base = session_dir(tmp_path, session["session_id"])
    json_files = sorted((base / "comparisons").glob("*.json"))
    csv_files = sorted((base / "comparisons").glob("*.csv"))
    assert len(json_files) == 2
    assert len(csv_files) == 2
    ids = [read_json(path)["compare_id"] for path in json_files]
    assert len(set(ids)) == 2
    assert any(compare_id.endswith("_02") for compare_id in ids)
    assert len(list((base / "comparisons").glob("*_psd_overlay.png"))) == 2
    assert len(list((base / "comparisons").glob("*_psd_overlay.svg"))) == 2


def test_compare_index_lists_sessions_and_counts_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "compare index")
    run0 = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", duration_s=0.1)
    run1 = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj1", duration_s=0.1)
    final0 = record_mock_and_finalize(tmp_path, run0)
    final1 = record_mock_and_finalize(tmp_path, run1)
    client = TestClient(create_app())
    page = client.get("/compare")
    assert page.status_code == 200
    assert "Select a session" in page.text
    assert session["session_id"] in page.text
    assert f"/compare/{session['session_id']}" in page.text
    assert final0["run_id"] not in page.text
    assert ">2<" in page.text
    nav = client.get("/")
    assert 'href="/compare">Compare</a>' in nav.text


def test_compare_route_supports_wide_band_and_range_wav_cross_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "compare range")
    run0 = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", duration_s=0.25)
    run1 = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj1", duration_s=0.25)
    final0 = record_mock_and_finalize(tmp_path, run0)
    final1 = record_mock_and_finalize(tmp_path, run1)
    client = TestClient(create_app())
    response = client.post(
        f"/compare/{session['session_id']}",
        data={
            "uj0_run_id": final0["run_id"],
            "uj1_run_id": final1["run_id"],
            "source": "range_wav",
            "band_mode": "wide",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    base = session_dir(tmp_path, session["session_id"])
    result = read_json(next((base / "comparisons").glob("*range_wav__20-3900Hz.json")))
    assert result["source"] == "range_wav"
    assert result["result_grade"] == "cross-check"
    assert "cross-check" in result["source_label"]
    assert result["uj0_source_path"] == final0["files"]["wav_range"]
    assert result["uj1_source_path"] == final1["files"]["wav_range"]
    assert result["uj0_metrics_path"] == ""
    assert result["uj1_metrics_path"] == ""
    assert result["band_hz"] == [20.0, 3900.0]
    assert "range_wav_cross_check_not_report_grade" in result["warnings"]
    assert "cross-check" in response.text
    assert "Range WAV comparison is a cross-check only when full-scale voltage is known." in response.text
    report_text = (base / "session_report.md").read_text(encoding="utf-8")
    assert "Range WAV comparison is a cross-check only when full-scale voltage is known." in report_text
    assert "20-3900 Hz" in (base / result["plots"]["psd_overlay_svg"]).read_text(encoding="utf-8")


def test_range_wav_compare_returns_structured_error_for_invalid_wav(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "bad range wav")
    run0 = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", duration_s=0.25)
    run1 = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj1", duration_s=0.25)
    final0 = record_mock_and_finalize(tmp_path, run0)
    final1 = record_mock_and_finalize(tmp_path, run1)
    base = session_dir(tmp_path, session["session_id"])
    (base / final1["files"]["wav_range"]).write_bytes(b"not a wav")
    client = TestClient(create_app())
    response = client.post(
        f"/compare/{session['session_id']}",
        data={
            "uj0_run_id": final0["run_id"],
            "uj1_run_id": final1["run_id"],
            "source": "range_wav",
            "band_mode": "primary",
        },
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["error_code"] == "INVALID_RANGE_WAV_CROSS_CHECK"
    assert final1["run_id"] in detail["message"]
    assert "saved .bin" in detail["suggestion"]
    assert not list((base / "comparisons").glob("*.json"))


def test_range_wav_compare_uses_saved_trim_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "compare trims")
    run0 = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", duration_s=0.25, trim_start_s=0.01, trim_end_s=0.02)
    run1 = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj1", duration_s=0.25, trim_start_s=0.03, trim_end_s=0.04)
    run1["conversion"]["remove_dc"] = False
    save_run(tmp_path, run1)
    final0 = record_mock_and_finalize(tmp_path, run0)
    final1 = record_mock_and_finalize(tmp_path, load_run(tmp_path, session["session_id"], run1["run_id"]))
    calls = []

    def fake_analyze_range_wav(wav_path, **kwargs):
        calls.append((Path(wav_path).name, kwargs))
        return {
            "source": "range_wav",
            "label": "range cross-check",
            "sample_rate_hz": kwargs["expected_sample_rate_hz"],
            "sample_count": 1000,
            "expected_sample_count": 1000,
            "rms_v": 0.1,
            "dc_offset_v": 0.0,
            "band_hz": list(kwargs["band_hz"]),
            "band_power": 1.0,
            "band_rms_v": 1.0,
            "band_power_300_3400": 1.0,
            "band_rms_300_3400_v": 1.0,
            "band_power_20_3900": 1.0,
            "band_rms_20_3900_v": 1.0,
            "dominant_freq_hz": 1000.0,
            "dominant_tone_power_pm50": 1.0,
            "dominant_tone_rms_pm50_v": 1.0,
            "quality_flags": [],
            "psd_freq_hz": [300.0, 3400.0],
            "psd_v2_per_hz": [1.0, 1.0],
        }

    monkeypatch.setattr(compare_routes, "analyze_range_wav", fake_analyze_range_wav)
    client = TestClient(create_app())
    response = client.post(
        f"/compare/{session['session_id']}",
        data={
            "uj0_run_id": final0["run_id"],
            "uj1_run_id": final1["run_id"],
            "source": "range_wav",
            "band_mode": "primary",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert [call[1]["trim_start_s"] for call in calls] == [0.01, 0.03]
    assert [call[1]["trim_end_s"] for call in calls] == [0.02, 0.04]
    assert [call[1]["remove_dc"] for call in calls] == [True, False]


def test_auto_pair_finalized_runs_and_route(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "auto pair")
    run0 = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", duration_s=0.25, mic_id="m1", distance_cm=10)
    run1 = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj1", duration_s=0.25, mic_id="m1", distance_cm=10)
    pending = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj1", duration_s=0.25, mic_id="m1", distance_cm=10)
    final0 = record_mock_and_finalize(tmp_path, run0)
    final1 = record_mock_and_finalize(tmp_path, run1)
    runs = [final0, final1, pending]
    assert [(a["run_id"], b["run_id"]) for a, b in auto_pair_runs(runs)] == [(final0["run_id"], final1["run_id"])]
    client = TestClient(create_app())
    response = client.post(f"/compare/{session['session_id']}/auto-pair", follow_redirects=True)
    assert response.status_code == 200
    assert "Saved Results" in response.text
    base = session_dir(tmp_path, session["session_id"])
    result = read_json(next((base / "comparisons").glob("*.json")))
    assert result["plots"]["psd_overlay_png"].endswith("_psd_overlay.png")
    assert (base / result["plots"]["psd_overlay_svg"]).exists()
    metrics = read_json(base / final0["files"]["metrics_json"])
    assert metrics["psd_freq_hz"]


def test_live_snapshot_contains_preview_psd_and_spectrogram(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    append_jsonl(tmp_path / ".micloaker" / "jobs.jsonl", {"event": "job_started", "status": "running", "job_id": "job_live_tail", "type": "manual_finalize"})
    client = TestClient(create_app())
    page = client.get("/live")
    assert page.status_code == 200
    assert "Recording State" in page.text
    assert "Finalization Status" in page.text
    assert "Latest Finalization Result" in page.text
    assert "Download metrics JSON" in page.text
    assert "Open run log" in page.text
    assert "Status Log Tail" in page.text
    assert "Preview only. Final metrics will be recomputed from saved .bin after recording." in page.text
    live_js = Path("app/static/js/live.js").read_text(encoding="utf-8")
    assert "failed_run_id" in live_js
    assert "finalization_error_log" in live_js
    assert "preview_source" in live_js
    assert "final_metrics_source" in live_js
    assert "recommended_update_rates_hz" in live_js
    assert "client_poll_intervals_ms" in live_js
    assert "scheduleRefresh" in live_js
    assert "setInterval(refresh, nextInterval)" in live_js
    assert "?download=1" in live_js
    stopped_initial = client.get("/live/snapshot").json()
    assert stopped_initial["recording_state"] == "Stopped"
    assert "saved .bin" in stopped_initial["finalization_status"]
    assert stopped_initial["preview_source"] == "mock"
    assert stopped_initial["preview_saved"] is False
    assert stopped_initial["final_metrics_source"] == "saved_bin_after_recording"
    assert stopped_initial["recommended_update_rates_hz"]["waveform_min"] == 5
    assert stopped_initial["recommended_update_rates_hz"]["spectrogram_max"] == 5
    assert stopped_initial["client_poll_intervals_ms"]["preview"] == 200
    assert stopped_initial["client_poll_intervals_ms"]["recording"] == 200
    assert stopped_initial["client_poll_intervals_ms"]["idle"] == 1000
    assert stopped_initial["payload_limits"]["spectrogram_rows_max"] == 60
    assert stopped_initial["sample_rate_hz"] == 8000
    assert stopped_initial["waveform_point_count"] == 0
    assert stopped_initial["psd_bin_count"] == 0
    assert any("job_live_tail" in line for line in stopped_initial["log_tail"])
    started = client.post("/live/start").json()
    assert started["running"] is True
    assert started["recording_state"] == "Previewing"
    assert "Preview data is not saved" in started["finalization_status"]
    assert started["preview_only"] is True
    assert started["result_grade"] == "preview"
    assert started["preview_tick"] == 1
    assert "Preview only" in started["preview_label"]
    assert started["preview_source"] == "mock"
    assert started["preview_saved"] is False
    assert started["final_metrics_source"] == "saved_bin_after_recording"
    assert started["payload_limits"]["waveform_points_min"] <= started["waveform_point_count"] <= started["payload_limits"]["waveform_points_max"]
    assert started["payload_limits"]["psd_bins_min"] <= started["psd_bin_count"] <= started["payload_limits"]["psd_bins_max"]
    assert started["sample_rate_hz"] == 8000
    assert started["state_options"] == ["Stopped", "Previewing", "Recording", "Finalizing", "Finalized"]
    assert started["waveform"]
    assert started["psd"]
    assert started["spectrogram"]
    assert started["waveform_point_count"] == len(started["waveform"])
    assert started["psd_bin_count"] == len(started["psd"])
    assert started["spectrogram_row_count"] == len(started["spectrogram"])
    next_snapshot = client.get("/live/snapshot").json()
    assert next_snapshot["preview_tick"] == 2
    assert next_snapshot["waveform"] != started["waveform"]
    assert len(next_snapshot["spectrogram"]) > len(started["spectrogram"])
    stopped = client.post("/live/stop").json()
    assert stopped["running"] is False
    assert stopped["recording_state"] == "Stopped"


def test_live_snapshot_reports_preview_dependency_error_without_breaking_page(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)

    def missing_live_psd(data, sample_rate_hz, *, nperseg):
        raise RuntimeError("SciPy is required for live PSD preview. Install scipy or stop Live Monitor preview.")

    monkeypatch.setattr(live_monitor_module, "_welch_psd", missing_live_psd)
    client = TestClient(create_app())
    started = client.post("/live/start")
    assert started.status_code == 200
    snapshot = started.json()
    assert snapshot["running"] is True
    assert snapshot["recording_state"] == "Previewing"
    assert snapshot["preview_error_code"] == "LIVE_PREVIEW_UNAVAILABLE"
    assert "SciPy is required for live PSD preview" in snapshot["preview_error"]
    assert "Live preview unavailable" in snapshot["finalization_status"]
    assert snapshot["preview_only"] is True
    assert snapshot["result_grade"] == "preview"
    assert snapshot["final_metrics_source"] == "saved_bin_after_recording"
    assert snapshot["waveform_point_count"] == 0
    assert snapshot["psd_bin_count"] == 0
    assert snapshot["clipping"] is False
    assert client.get("/live").status_code == 200
    client.post("/live/stop")


def test_live_snapshot_reports_latest_finalized_run_from_saved_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "live finalized")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", duration_s=0.15)
    final = record_mock_and_finalize(tmp_path, run)
    client = TestClient(create_app())
    snapshot = client.get("/live/snapshot").json()
    assert snapshot["recording_state"] == "Finalized"
    assert snapshot["final_run_id"] == final["run_id"]
    assert snapshot["final_session_id"] == session["session_id"]
    assert snapshot["final_bin_path"] == final["files"]["bin"]
    assert snapshot["final_metrics_path"] == final["files"]["metrics_json"]
    assert snapshot["final_log_path"] == f"logs/{final['run_id']}.log"
    assert snapshot["final_wav_peak_path"] == final["files"]["wav_peak"]
    assert snapshot["final_wav_range_path"] == final["files"]["wav_range"]
    assert snapshot["final_plot_paths"]["waveform_png"] == final["files"]["waveform_png"]
    assert snapshot["final_plot_paths"]["psd_svg"] == final["files"]["psd_svg"]
    assert snapshot["final_plot_paths"]["spectrogram_svg"] == final["files"]["spectrogram_svg"]
    assert snapshot["final_result_grade"] == "report-grade"
    assert snapshot["finalized_from_saved_bin"] is True
    assert snapshot["final_raw_sample_count"] == final["recording"]["raw_sample_count"]
    assert snapshot["final_raw_size_bytes"] == final["recording"]["raw_size_bytes"]
    assert snapshot["final_raw_dtype"] == "<f8"
    assert "saved .bin" in snapshot["finalization_status"]
    page = client.get("/live")
    assert "Latest Finalization Result" in page.text
    live_js = Path("app/static/js/live.js").read_text(encoding="utf-8")
    assert "raw_bin_path" in live_js
    assert "wav_peak_path" in live_js
    assert "plot_paths" in live_js
    assert "final_log_path" in live_js
    assert "final_metrics_path}?download=1" in live_js


def test_live_snapshot_reports_latest_failed_finalization_from_saved_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    old_session = create_session(tmp_path, "live old finalized")
    old_run = create_run_metadata(tmp_path, old_session["session_id"], carrier_freq_khz=25, uj="uj0", duration_s=0.15)
    record_mock_and_finalize(tmp_path, old_run)
    failed_session = create_session(tmp_path, "live failed")
    failed = create_run_metadata(tmp_path, failed_session["session_id"], carrier_freq_khz=25, uj="uj1", duration_s=0.15)
    failed["analysis"].update({
        "status": "failed",
        "result_grade": "none",
        "finalized_from_saved_bin": False,
        "failed_at": "2999-01-01T00:00:00+00:00",
        "last_error": "conversion backend failed",
        "error_log": f"logs/{failed['run_id']}.log",
    })
    failed["quality_flags"] = ["finalization_failed"]
    save_run(tmp_path, failed)

    client = TestClient(create_app())
    snapshot = client.get("/live/snapshot").json()
    assert snapshot["recording_state"] == "Stopped"
    assert snapshot["failed_run_id"] == failed["run_id"]
    assert snapshot["failed_session_id"] == failed_session["session_id"]
    assert snapshot["finalization_error"] == "conversion backend failed"
    assert snapshot["finalization_error_log"] == f"logs/{failed['run_id']}.log"
    assert "Latest finalization failed" in snapshot["finalization_status"]
    assert "retry from saved .bin" in snapshot["finalization_status"]
    assert "final_run_id" not in snapshot


def test_live_snapshot_reports_running_finalization_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    client = TestClient(create_app())
    append_jsonl(
        tmp_path / ".micloaker" / "jobs.jsonl",
        {
            "event": "job_started",
            "status": "running",
            "job_id": "job_finalizing",
            "type": "manual_finalize",
            "started_at": "2026-05-28T00:00:00+00:00",
            "logs": "sessions/s/logs/r.log",
        },
    )
    snapshot = client.get("/live/snapshot").json()
    assert snapshot["recording_state"] == "Finalizing"
    assert snapshot["finalization_job"]["job_id"] == "job_finalizing"
    assert "saved .bin recomputation" in snapshot["finalization_status"]

    append_jsonl(
        tmp_path / ".micloaker" / "jobs.jsonl",
        {
            "event": "job_finished",
            "status": "finished",
            "job_id": "job_finalizing",
            "type": "manual_finalize",
            "finished_at": "2026-05-28T00:00:01+00:00",
            "logs": "sessions/s/logs/r.log",
        },
    )
    stopped = client.get("/live/snapshot").json()
    assert stopped["recording_state"] == "Stopped"
    assert "finalization_job" not in stopped


def test_mac_helper_passthrough_endpoints_fail_softly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(mac_helper_routes, "discover_helpers", lambda: [])
    client = TestClient(create_app())
    for path in ["/mac-helper/health", "/mac-helper/devices", "/mac-helper/files", "/mac-helper/status"]:
        result = client.get(path).json()
        assert result["connected"] is False
        assert result["error_code"] == "HELPER_DISCONNECTED"
    validate = client.post(
        "/mac-helper/validate-playback",
        data={"file": "tone.wav", "device_id": 1, "sample_rate": 192000, "channels": 1, "gain": 0.8},
    ).json()
    assert validate["connected"] is False
    play = client.post(
        "/mac-helper/play",
        data={"file": "tone.wav", "device_id": 1, "sample_rate": 192000, "channels": 1, "gain": 0.8, "delay_ms": 0},
    ).json()
    assert play["connected"] is False
    missing_file = client.post(
        "/mac-helper/validate-playback",
        data={"file": "", "device_id": "", "sample_rate": "", "channels": "1", "gain": 0.8},
    )
    assert missing_file.status_code == 400
    assert missing_file.json()["detail"]["error_code"] == "MISSING_PLAYBACK_FILE"
    bad_device = client.post(
        "/mac-helper/play",
        data={"file": "tone.wav", "device_id": "", "sample_rate": "192000", "channels": "1", "gain": 0.8, "delay_ms": "0"},
    )
    assert bad_device.status_code == 400
    assert bad_device.json()["detail"]["ok"] is False
    assert bad_device.json()["detail"]["error_code"] == "INVALID_PLAYBACK_FIELD"
    discover = client.get("/mac-helper/discover").json()
    assert discover["ok"] is True
    assert discover["candidates"] == []
    result = client.post("/mac-helper/stop").json()
    assert result["connected"] is False


def test_malformed_mac_helper_config_falls_back_to_disconnected_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    (tmp_path / ".micloaker" / "config.json").write_text("{bad json\n", encoding="utf-8")
    client = TestClient(create_app())

    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert "Mac Helper disconnected" in dashboard.text
    page = client.get("/mac-helper")
    assert page.status_code == 200
    assert "Mac Helper disconnected" in page.text
    health = client.get("/mac-helper/health").json()
    assert health["connected"] is False
    assert health["error_code"] == "HELPER_DISCONNECTED"

    response = client.post("/mac-helper/config", data={"mac_helper_url": "http://100.64.0.10:5050", "mac_helper_token": "secret-token"}, follow_redirects=False)
    assert response.status_code == 303
    saved = read_json(tmp_path / ".micloaker" / "config.json")
    assert saved["mac_helper_url"] == "http://100.64.0.10:5050"
    assert saved["mac_helper_token"] == "secret-token"


def test_mac_helper_run_actions_validate_session_and_run_targets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "helper missing targets")
    client = TestClient(create_app())
    payload = {"file": "tone.wav", "device_id": "1", "sample_rate": "192000", "channels": "1", "gain": "0.8"}

    missing_session = client.post("/mac-helper/sessions/missing_session/runs/missing_run/validate-playback", data=payload)
    assert missing_session.status_code == 404
    detail = missing_session.json()["detail"]
    assert detail["error_code"] == "SESSION_NOT_FOUND"
    assert "Mac Helper run controls" in detail["suggestion"]

    for action in ["validate-playback", "play", "stop", "play-and-record-mock", "play-and-record-daq"]:
        data = dict(payload)
        if action not in {"validate-playback", "stop"}:
            data["delay_ms"] = "0"
        response = client.post(f"/mac-helper/sessions/{session['session_id']}/runs/missing_run/{action}", data=data)
        assert response.status_code == 404
        detail = response.json()["detail"]
        assert detail["error_code"] == "RUN_NOT_FOUND"
        assert "missing_run" in detail["message"]
    assert not list((session_dir(tmp_path, session["session_id"]) / "logs").glob("missing_run.log"))


def test_mac_helper_page_contains_documented_playback_controls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    client = TestClient(create_app())
    page = client.get("/mac-helper")
    assert page.status_code == 200
    for text in [
        "Auto Discover via Tailscale",
        "Output device",
        "WAV file",
        "48000",
        "96000",
        "192000",
        "Validate Playback",
        "Play",
        "Stop Playback",
        "optional token",
        "Play & Record controls are on each run detail page",
        "Mac Helper disconnected. Manual Linux-only recording and analysis remain available.",
    ]:
        assert text in page.text


def test_mac_helper_page_displays_connected_status_and_passthrough_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)

    class FakeHelper:
        def health(self):
            return {
                "ok": True,
                "enabled": True,
                "connected": True,
                "health_ok": True,
                "hostname": "MacBook-Pro",
                "service": "micloaker-mac-audio-helper",
            }

        def devices(self):
            return {
                "ok": True,
                "connected": True,
                "output_devices": [
                    {
                        "id": 3,
                        "name": "USB Audio Device",
                        "max_output_channels": 2,
                        "default_samplerate": 192000.0,
                        "hostapi": "Core Audio",
                    }
                ],
            }

        def files(self):
            return {
                "ok": True,
                "connected": True,
                "files": [{"path": "tone.wav", "size_bytes": 44, "duration_s": 1.0, "sample_rate": 192000}],
            }

    monkeypatch.setattr(mac_helper_routes, "_client_from_config", lambda workspace: FakeHelper())
    client = TestClient(create_app())
    page = client.get("/mac-helper")
    assert page.status_code == 200
    assert "Connection Status" in page.text
    assert "Connected" in page.text
    assert "MacBook-Pro" in page.text
    assert "micloaker-mac-audio-helper" in page.text
    assert client.get("/mac-helper/devices").json()["output_devices"][0]["name"] == "USB Audio Device"
    assert client.get("/mac-helper/files").json()["files"][0]["path"] == "tone.wav"


def test_recording_guard_refuses_second_active_recording(tmp_path: Path):
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "guard")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0")
    assert _recording_lock.acquire(blocking=False) is True
    try:
        with pytest.raises(RecordingBusyError):
            record_mock_and_finalize(tmp_path, run)
        assert recording_status()["active"] is False
    finally:
        _recording_lock.release()


def test_recording_routes_return_structured_busy_conflict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "route busy")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0")
    client = TestClient(create_app())
    assert _recording_lock.acquire(blocking=False) is True
    try:
        for action in ["record-mock", "record-daq"]:
            response = client.post(f"/sessions/{session['session_id']}/runs/{run['run_id']}/{action}")
            assert response.status_code == 409
            detail = response.json()["detail"]
            assert detail["error_code"] == "RECORDING_BUSY"
            assert "active recording" in detail["suggestion"]
    finally:
        _recording_lock.release()


def test_daq_record_route_fails_softly_without_hardware(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "daq unavailable")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0")

    def unavailable(**kwargs):
        from app.services.daq import DaqUnavailableError

        raise DaqUnavailableError("no DAQ")

    monkeypatch.setattr(recorder_module, "record_voltage", unavailable)
    client = TestClient(create_app())
    response = client.post(f"/sessions/{session['session_id']}/runs/{run['run_id']}/record-daq")
    assert response.status_code == 503
    assert response.json()["detail"]["error_code"] == "DAQ_UNAVAILABLE"
    base = session_dir(tmp_path, session["session_id"])
    assert not (base / run["files"]["bin"]).exists()
    saved = load_run(tmp_path, session["session_id"], run["run_id"])
    assert saved["analysis"]["status"] == "failed"
    assert saved["analysis"]["failure_stage"] == "recording"
    assert saved["analysis"]["result_grade"] == "none"
    assert saved["analysis"]["finalized_from_saved_bin"] is False
    assert saved["analysis"]["recording_source_attempted"] == "daq"
    assert saved["recording"]["last_attempted_source"] == "daq"
    assert saved["analysis"]["error_log"] == f"logs/{run['run_id']}.log"
    assert "recording_failed" in saved["quality_flags"]
    log_text = (base / "logs" / f"{run['run_id']}.log").read_text(encoding="utf-8")
    assert "recording_failed source=daq metadata_saved=true" in log_text
    assert "job_failed" in log_text
    run_events = read_jsonl(base / "runs.jsonl")
    assert run_events[-1]["event"] == "run_recording_failed"
    assert run_events[-1]["error_log"] == f"logs/{run['run_id']}.log"
    app_events = read_jsonl(tmp_path / ".micloaker" / "app_events.jsonl")
    assert app_events[-1]["event"] == "run_recording_failed"
    counts = rebuild_indexes(tmp_path)
    assert counts == {"sessions": 1, "runs": 1, "comparisons": 0}
    rebuilt_events = read_jsonl(base / "runs.jsonl")
    assert any(row["event"] == "run_recording_failed" and row["source"] == "daq" for row in rebuilt_events)
    with (base / "summary.csv").open("r", encoding="utf-8", newline="") as f:
        summary = next(csv.DictReader(f))
    assert summary["analysis_status"] == "failed"
    assert summary["analysis_error"] == "no DAQ"
    assert summary["quality_flags"] == "recording_failed"


def test_recording_persists_raw_capture_metadata_before_failed_finalization(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "capture survives finalize failure")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", duration_s=0.1)

    def fail_conversion(*args, **kwargs):
        raise RuntimeError("conversion backend failed")

    monkeypatch.setattr(recorder_module.converter, "convert_run_bin", fail_conversion)
    with pytest.raises(RuntimeError, match="conversion backend failed"):
        record_mock_and_finalize(tmp_path, run)

    base = session_dir(tmp_path, session["session_id"])
    saved = load_run(tmp_path, session["session_id"], run["run_id"])
    assert (base / saved["files"]["bin"]).exists()
    assert saved["recording"]["written_samples"] > 0
    assert saved["recording"]["finished_at"]
    assert saved["analysis"]["status"] == "failed"
    assert saved["analysis"]["result_grade"] == "none"
    assert saved["analysis"]["last_error"] == "conversion backend failed"
    assert saved["analysis"]["error_log"] == f"logs/{run['run_id']}.log"
    assert "finalization_failed" in saved["quality_flags"]
    log_text = (base / "logs" / f"{run['run_id']}.log").read_text(encoding="utf-8")
    assert "wrote raw float64 bin" in log_text
    assert "finalization_failed metadata_saved=true" in log_text
    assert "job_failed" in log_text
    events = read_jsonl(base / "events.jsonl")
    assert any(row["event"] == "run_finalization_failed" and row["run_id"] == run["run_id"] for row in events)


def test_daq_record_success_path_finalizes_from_saved_bin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "daq success")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", duration_s=0.25)

    def fake_record_voltage(**kwargs):
        fs = int(kwargs["sample_rate_hz"])
        t = np.arange(fs // 4) / fs
        return 0.1 * np.sin(2 * np.pi * 1000 * t)

    monkeypatch.setattr(recorder_module, "record_voltage", fake_record_voltage)
    final = record_daq_and_finalize(tmp_path, run)
    base = session_dir(tmp_path, session["session_id"])
    assert final["recording"]["source"] == "daq"
    assert final["analysis"]["finalization_trigger"] == "recording_finished"
    assert final["analysis"]["finalized_from_saved_bin"] is True
    assert (base / final["files"]["bin"]).exists()


def test_daq_record_persists_channel_traceability(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "daq channel trace")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", channel=2, duration_s=0.25)
    captured = {}

    def fake_record_voltage(**kwargs):
        captured["channels"] = kwargs["channels"]
        fs = int(kwargs["sample_rate_hz"])
        t = np.arange(fs // 4) / fs
        return 0.1 * np.sin(2 * np.pi * 1000 * t), float(fs)

    monkeypatch.setattr(recorder_module, "record_voltage", fake_record_voltage)
    final = record_daq_and_finalize(tmp_path, run)
    base = session_dir(tmp_path, session["session_id"])
    log_text = (base / "logs" / f"{run['run_id']}.log").read_text(encoding="utf-8")

    assert captured["channels"] == [2]
    assert final["recording"]["source_channels"] == [2]
    assert final["recording"]["recorded_channel"] == 2
    assert final["recording"]["recorded_channel_count"] == 1
    assert "source_channels=[2] recorded_channel=2" in log_text


def test_daq_finalization_uses_actual_sample_rate_for_metrics_and_wavs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "daq actual rate")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", sample_rate_hz=8000, duration_s=0.25)

    def fake_record_voltage(**kwargs):
        actual_rate = 4000.0
        t = np.arange(int(actual_rate * 0.25)) / actual_rate
        data = 0.1 * np.sin(2 * np.pi * 1000 * t)
        return data, actual_rate

    monkeypatch.setattr(recorder_module, "record_voltage", fake_record_voltage)
    final = record_daq_and_finalize(tmp_path, run)
    base = session_dir(tmp_path, session["session_id"])
    metrics = read_json(base / final["files"]["metrics_json"])
    assert final["recording"]["sample_rate_hz"] == 8000
    assert final["recording"]["actual_sample_rate_hz"] == 4000.0
    assert metrics["sample_rate_hz"] == 4000.0
    assert metrics["expected_sample_count"] == 1000
    assert "sample_count_mismatch" not in metrics["quality_flags"]
    assert final["conversion"]["outputs"]["wav_peak"]["sample_rate_hz"] == 4000
    with wave.open(str(base / final["files"]["wav_peak"]), "rb") as wf:
        assert wf.getframerate() == 4000


def test_uldaq_record_voltage_uses_lazy_real_scan_path(monkeypatch: pytest.MonkeyPatch):
    calls: dict[str, object] = {}

    class InterfaceType:
        USB = "USB"

    class AiInputMode:
        SINGLE_ENDED = "SINGLE_ENDED"

    class Range:
        BIP10VOLTS = "BIP10VOLTS"

    class ScanOption:
        DEFAULTIO = "DEFAULTIO"

    class AInScanFlag:
        DEFAULT = "DEFAULT"

    class FakeAiDevice:
        def a_in_scan(self, low_channel, high_channel, input_mode, ai_range, samples_per_channel, rate, scan_option, flags, data):
            calls.update({
                "low_channel": low_channel,
                "high_channel": high_channel,
                "input_mode": input_mode,
                "ai_range": ai_range,
                "samples_per_channel": samples_per_channel,
                "rate": rate,
                "scan_option": scan_option,
                "flags": flags,
            })
            for index in range(len(data)):
                data[index] = float(index)
            return 7999.5

    class FakeDevice:
        def __init__(self, descriptor):
            calls["descriptor"] = descriptor

        def connect(self):
            calls["connected"] = True

        def get_ai_device(self):
            return FakeAiDevice()

        def disconnect(self):
            calls["disconnected"] = True

        def release(self):
            calls["released"] = True

    fake_uldaq = types.SimpleNamespace(
        InterfaceType=InterfaceType,
        AiInputMode=AiInputMode,
        Range=Range,
        ScanOption=ScanOption,
        AInScanFlag=AInScanFlag,
        get_daq_device_inventory=lambda interface: ["usb-1608"],
        DaqDevice=FakeDevice,
        create_float_buffer=lambda channel_count, samples_per_channel: [0.0] * (channel_count * samples_per_channel),
    )
    monkeypatch.setitem(sys.modules, "uldaq", fake_uldaq)
    samples, actual_rate = daq_module.record_voltage(
        sample_rate_hz=8000,
        duration_s=0.25,
        channels=[0],
        input_mode="SINGLE_ENDED",
        ai_range="BIP10VOLTS",
    )
    assert samples.dtype.str == "<f8"
    assert samples.shape == (2000,)
    assert samples[:3].tolist() == [0.0, 1.0, 2.0]
    assert actual_rate == 7999.5
    assert calls["low_channel"] == 0
    assert calls["high_channel"] == 0
    assert calls["samples_per_channel"] == 2000
    assert calls["connected"] is True
    assert calls["disconnected"] is True
    assert calls["released"] is True


def test_play_and_record_requires_prior_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "helper gate")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0")
    client = TestClient(create_app())
    response = client.post(
        f"/mac-helper/sessions/{session['session_id']}/runs/{run['run_id']}/play-and-record-mock",
        data={"file": "tone.wav", "device_id": 1, "sample_rate": 8000, "channels": 1, "gain": 0.5, "delay_ms": 0},
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["error_code"] == "PLAYBACK_NOT_VALIDATED"
    saved = load_run(tmp_path, session["session_id"], run["run_id"])
    assert saved["mac_helper"]["last_action"] == "play_and_record_rejected"
    assert saved["mac_helper"]["connected"] is False
    assert saved["mac_helper"]["enabled"] is False
    assert saved["mac_helper"]["health_ok"] is False


def test_play_and_record_rejection_preserves_existing_helper_connection_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "helper stale gate")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0")

    class FakeHelper:
        def validate_playback(self, payload):
            return {"ok": True, "device_exists": True, "requested_sample_rate": payload["sample_rate"], "duration_s": 1.0}

    monkeypatch.setattr(mac_helper_routes, "_client_from_config", lambda workspace: FakeHelper())
    client = TestClient(create_app())
    validated = client.post(
        f"/mac-helper/sessions/{session['session_id']}/runs/{run['run_id']}/validate-playback",
        data={"file": "tone.wav", "device_id": 1, "sample_rate": 8000, "channels": 1, "gain": 0.5},
    )
    assert validated.status_code == 200
    response = client.post(
        f"/mac-helper/sessions/{session['session_id']}/runs/{run['run_id']}/play-and-record-mock",
        data={"file": "tone.wav", "device_id": 1, "sample_rate": 8000, "channels": 1, "gain": 0.7, "delay_ms": 0},
    )
    assert response.status_code == 400
    saved = load_run(tmp_path, session["session_id"], run["run_id"])
    assert saved["mac_helper"]["last_action"] == "play_and_record_rejected"
    assert saved["mac_helper"]["connected"] is True
    assert saved["mac_helper"]["enabled"] is True
    assert saved["mac_helper"]["health_ok"] is True


def test_play_and_record_returns_structured_busy_conflict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "helper busy")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0")

    class FakeHelper:
        def validate_playback(self, payload):
            return {"ok": True, "duration_s": 1.0, "source_sample_rate": payload["sample_rate"], **payload}

        def play(self, payload):
            return {"ok": True, "play_id": "play_busy", "duration_s": 1.0, **payload}

    monkeypatch.setattr(mac_helper_routes, "_client_from_config", lambda workspace: FakeHelper())
    client = TestClient(create_app())
    payload = {"file": "tone.wav", "device_id": 1, "sample_rate": 8000, "channels": 1, "gain": 0.5}
    assert client.post(f"/mac-helper/sessions/{session['session_id']}/runs/{run['run_id']}/validate-playback", data=payload).json()["ok"] is True

    assert _recording_lock.acquire(blocking=False) is True
    try:
        response = client.post(
            f"/mac-helper/sessions/{session['session_id']}/runs/{run['run_id']}/play-and-record-mock",
            data={**payload, "delay_ms": 0},
        )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["error_code"] == "RECORDING_BUSY"
        assert "Play & Record" in detail["suggestion"]
        saved = load_run(tmp_path, session["session_id"], run["run_id"])
        assert saved["mac_helper"]["last_action"] == "play_and_record_failed"
        assert saved["mac_helper"]["last_error_code"] == "RECORDING_BUSY"
        assert saved["mac_helper"]["play_request_ok"] is True
        assert saved["mac_helper"]["play_id"] == "play_busy"
        log_text = (session_dir(tmp_path, session["session_id"]) / "logs" / f"{run['run_id']}.log").read_text(encoding="utf-8")
        assert "mac_helper_play ok=True" in log_text
        assert "mac_helper_play_and_record_failed ok=False" in log_text
    finally:
        _recording_lock.release()


def test_mac_helper_success_persists_run_metadata_and_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "helper success")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0")

    class FakeHelper:
        def validate_playback(self, payload):
            return {
                "ok": True,
                "duration_s": 1.0,
                "device_exists": True,
                "device_name": "USB Audio Device",
                "device_max_output_channels": 2,
                "device_default_samplerate": 48000.0,
                "device_hostapi": "Core Audio",
                "source_sample_rate": 44100,
                "requested_sample_rate": payload["sample_rate"],
                "will_resample": True,
                "channels": 1,
                "requested_channels": payload["channels"],
                "will_channel_map": False,
                "payload": payload,
            }

        def play(self, payload):
            return {
                "ok": True,
                "play_id": "play_test_001",
                "device_name": "USB Audio Device",
                "device_max_output_channels": 2,
                "device_default_samplerate": 48000.0,
                "device_hostapi": "Core Audio",
                "source_sample_rate": 44100,
                "will_resample": True,
                "duration_s": 1.0,
                "source_channels": 1,
                "requested_channels": payload["channels"],
                "will_channel_map": False,
                "expected_end_after_s": 1.01,
                **payload,
            }

    monkeypatch.setattr(mac_helper_routes, "_client_from_config", lambda workspace: FakeHelper())
    client = TestClient(create_app())
    validate = client.post(
        f"/mac-helper/sessions/{session['session_id']}/runs/{run['run_id']}/validate-playback",
        data={"file": "tone.wav", "device_id": 3, "sample_rate": 8000, "channels": 1, "gain": 0.5},
    )
    assert validate.status_code == 200
    play = client.post(
        f"/mac-helper/sessions/{session['session_id']}/runs/{run['run_id']}/play",
        data={"file": "tone.wav", "device_id": 3, "sample_rate": 8000, "channels": 1, "gain": 0.5, "delay_ms": 10},
    )
    assert play.status_code == 200
    saved = load_run(tmp_path, session["session_id"], run["run_id"])
    helper = saved["mac_helper"]
    assert helper["connected"] is True
    assert helper["helper_url"] == ""
    assert helper["file"] == "tone.wav"
    assert helper["device_id"] == 3
    assert helper["device_name"] == "USB Audio Device"
    assert helper["device_max_output_channels"] == 2
    assert helper["device_default_samplerate"] == 48000.0
    assert helper["device_hostapi"] == "Core Audio"
    assert helper["last_response"]["device_name"] == "USB Audio Device"
    assert helper["requested_sample_rate"] == 8000
    assert helper["source_sample_rate"] == 44100
    assert helper["actual_playback_sample_rate"] == 8000
    assert helper["will_resample"] is True
    assert helper["playback_duration_s"] == 1.0
    assert helper["channels"] == 1
    assert helper["source_channels"] == 1
    assert helper["requested_channels"] == 1
    assert helper["will_channel_map"] is False
    assert helper["expected_end_after_s"] == 1.01
    assert helper["gain"] == 0.5
    assert helper["validate_playback_ok"] is True
    assert helper["play_request_ok"] is True
    assert helper["play_id"] == "play_test_001"
    log_text = (session_dir(tmp_path, session["session_id"]) / "logs" / f"{run['run_id']}.log").read_text(encoding="utf-8")
    assert "mac_helper_validate_playback ok=True" in log_text
    assert "mac_helper_play ok=True" in log_text
    app_events = read_jsonl(tmp_path / ".micloaker" / "app_events.jsonl")
    helper_events = [row for row in app_events if row.get("event") == "mac_helper_client_action"]
    assert [row["action"] for row in helper_events] == ["validate_playback", "play"]
    assert all(row["run_id"] == run["run_id"] and row["ok"] is True for row in helper_events)
    app_log = (tmp_path / ".micloaker" / "app.log").read_text(encoding="utf-8")
    assert "mac_helper_client_action" in app_log
    page = client.get(f"/sessions/{session['session_id']}/runs/{run['run_id']}")
    assert "play_test_001" in page.text
    assert "USB Audio Device" in page.text
    assert "Device max output channels" in page.text
    assert "Core Audio" in page.text
    assert "Will resample" in page.text
    assert f"/mac-helper/sessions/{session['session_id']}/runs/{run['run_id']}/play" in page.text
    assert f"/mac-helper/sessions/{session['session_id']}/runs/{run['run_id']}/stop" in page.text
    assert "Stop Playback" in page.text


def test_mac_helper_run_stop_persists_without_erasing_last_playback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "helper stop")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0")

    class FakeHelper:
        def play(self, payload):
            return {"ok": True, "play_id": "play_stop_001", "source_sample_rate": 44100, "will_resample": True, **payload}

        def stop(self):
            return {"ok": True, "stopped": True}

    monkeypatch.setattr(mac_helper_routes, "_client_from_config", lambda workspace: FakeHelper())
    client = TestClient(create_app())
    play = client.post(
        f"/mac-helper/sessions/{session['session_id']}/runs/{run['run_id']}/play",
        data={"file": "tone.wav", "device_id": 3, "sample_rate": 8000, "channels": 1, "gain": 0.5, "delay_ms": 10},
    )
    assert play.status_code == 200
    stop = client.post(f"/mac-helper/sessions/{session['session_id']}/runs/{run['run_id']}/stop")
    assert stop.status_code == 200
    saved = load_run(tmp_path, session["session_id"], run["run_id"])
    helper = saved["mac_helper"]
    assert helper["last_action"] == "stop"
    assert helper["stop_request_ok"] is True
    assert helper["file"] == "tone.wav"
    assert helper["device_id"] == 3
    assert helper["requested_sample_rate"] == 8000
    assert helper["channels"] == 1
    assert helper["gain"] == 0.5
    assert helper["delay_ms"] == 10
    assert helper["play_id"] == "play_stop_001"
    log_text = (session_dir(tmp_path, session["session_id"]) / "logs" / f"{run['run_id']}.log").read_text(encoding="utf-8")
    assert "mac_helper_stop ok=True" in log_text


def test_connected_mac_helper_validation_failure_preserves_connection_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "helper validation failure")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0")

    class FakeHelper:
        def validate_playback(self, payload):
            return {
                "ok": False,
                "error_code": "UNSUPPORTED_SAMPLE_RATE",
                "message": "The selected output device does not support 192000 Hz with 1 channel.",
                "suggestion": "Try 96000 Hz or check macOS Audio MIDI Setup.",
                "device_exists": True,
            }

    monkeypatch.setattr(mac_helper_routes, "_client_from_config", lambda workspace: FakeHelper())
    client = TestClient(create_app())
    response = client.post(
        f"/mac-helper/sessions/{session['session_id']}/runs/{run['run_id']}/validate-playback",
        data={"file": "tone.wav", "device_id": 3, "sample_rate": 192000, "channels": 1, "gain": 0.5},
    )
    assert response.status_code == 200
    assert response.json()["error_code"] == "UNSUPPORTED_SAMPLE_RATE"
    helper = load_run(tmp_path, session["session_id"], run["run_id"])["mac_helper"]
    assert helper["connected"] is True
    assert helper["enabled"] is True
    assert helper["health_ok"] is True
    assert helper["validate_playback_ok"] is False
    assert helper["last_error_code"] == "UNSUPPORTED_SAMPLE_RATE"
    assert helper["last_error"] == "The selected output device does not support 192000 Hz with 1 channel."
    assert helper["last_suggestion"] == "Try 96000 Hz or check macOS Audio MIDI Setup."
    assert helper["last_response"]["error_code"] == "UNSUPPORTED_SAMPLE_RATE"
    page = client.get(f"/sessions/{session['session_id']}/runs/{run['run_id']}")
    assert "UNSUPPORTED_SAMPLE_RATE" in page.text
    assert "Try 96000 Hz" in page.text


def test_play_and_record_success_finalizes_and_preserves_helper_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "helper play record")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", duration_s=0.2)

    class FakeHelper:
        def validate_playback(self, payload):
            return {"ok": True, "duration_s": 1.0, "device_exists": True}

        def play(self, payload):
            return {"ok": True, "play_id": "play_record_001", **payload}

    monkeypatch.setattr(mac_helper_routes, "_client_from_config", lambda workspace: FakeHelper())
    client = TestClient(create_app())
    validate = client.post(
        f"/mac-helper/sessions/{session['session_id']}/runs/{run['run_id']}/validate-playback",
        data={"file": "tone.wav", "device_id": 4, "sample_rate": 8000, "channels": 1, "gain": 0.4},
    )
    assert validate.status_code == 200
    response = client.post(
        f"/mac-helper/sessions/{session['session_id']}/runs/{run['run_id']}/play-and-record-mock",
        data={"file": "tone.wav", "device_id": 4, "sample_rate": 8000, "channels": 1, "gain": 0.4, "delay_ms": 25},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["run"]["analysis_status"] == "finalized"
    saved = load_run(tmp_path, session["session_id"], run["run_id"])
    assert saved["analysis"]["status"] == "finalized"
    assert saved["analysis"]["finalization_trigger"] == "recording_finished"
    assert saved["mac_helper"]["play_request_ok"] is True
    assert saved["mac_helper"]["play_id"] == "play_record_001"
    assert saved["mac_helper"]["last_request"]["delay_ms"] == 25
    base = session_dir(tmp_path, session["session_id"])
    assert (base / saved["files"]["bin"]).exists()
    assert (base / saved["files"]["metrics_json"]).exists()


def test_daq_play_and_record_uses_validated_helper_settings_and_daq_recorder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "helper daq play record")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", duration_s=0.15, source="daq")

    class FakeHelper:
        def validate_playback(self, payload):
            return {"ok": True, "duration_s": 1.0, "device_exists": True, "source_sample_rate": payload["sample_rate"]}

        def play(self, payload):
            return {"ok": True, "play_id": "play_daq_001", **payload}

    called = {}

    def fake_record_daq_and_finalize(workspace: Path, run_data: dict) -> dict:
        called["run_id"] = run_data["run_id"]
        base = session_dir(workspace, run_data["session_id"])
        data = np.sin(2 * np.pi * 1000 * np.arange(1200) / 8000).astype("<f8")
        bin_path = base / run_data["files"]["bin"]
        bin_path.parent.mkdir(parents=True, exist_ok=True)
        data.tofile(bin_path)
        run_data["recording"]["source"] = "daq"
        run_data["recording"]["actual_sample_rate_hz"] = 8000
        run_data["recording"]["written_samples"] = int(data.size)
        return finalize_run(workspace, run_data, trigger="recording_finished")

    monkeypatch.setattr(mac_helper_routes, "_client_from_config", lambda workspace: FakeHelper())
    monkeypatch.setattr(mac_helper_routes, "record_daq_and_finalize", fake_record_daq_and_finalize)
    client = TestClient(create_app())
    payload = {"file": "tone.wav", "device_id": 4, "sample_rate": 8000, "channels": 1, "gain": 0.4}
    validate = client.post(f"/mac-helper/sessions/{session['session_id']}/runs/{run['run_id']}/validate-playback", data=payload)
    assert validate.status_code == 200

    response = client.post(
        f"/mac-helper/sessions/{session['session_id']}/runs/{run['run_id']}/play-and-record-daq",
        data={**payload, "delay_ms": 25},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["recording_source"] == "daq"
    assert body["run"]["analysis_status"] == "finalized"
    assert called["run_id"] == run["run_id"]
    saved = load_run(tmp_path, session["session_id"], run["run_id"])
    assert saved["recording"]["source"] == "daq"
    assert saved["analysis"]["result_grade"] == "report-grade"
    assert saved["mac_helper"]["play_request_ok"] is True
    assert saved["mac_helper"]["play_id"] == "play_daq_001"
    assert saved["mac_helper"]["last_request"]["delay_ms"] == 25
    page = client.get(f"/sessions/{session['session_id']}/runs/{run['run_id']}")
    assert "Play & Record DAQ" in page.text


def test_create_run_persists_expanded_metadata(tmp_path: Path):
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "metadata fields")
    run = create_run_metadata(
        tmp_path,
        session["session_id"],
        carrier_freq_khz=32.8,
        uj="uj1",
        sound_condition="sound1",
        mic_id="USB1608_CH2",
        room="anechoic",
        distance_cm=45.5,
        angle_deg=15.0,
        ai_range="BIP5VOLTS",
        input_mode="DIFFERENTIAL",
        channel=2,
        full_scale_volts=5.0,
        remove_dc=False,
        trim_start_s=0.05,
        trim_end_s=0.1,
        analysis_band_low_hz=500,
        analysis_band_high_hz=2500,
        safety_operator="lab tech",
        safety_max_spl_db=85.5,
        safety_notes="ear protection checked",
        mac_helper_file="planned.wav",
        mac_helper_device_id=7,
        mac_helper_sample_rate=96000,
        mac_helper_channels=2,
        mac_helper_gain=0.6,
        mac_helper_delay_ms=125,
    )
    saved = load_run(tmp_path, session["session_id"], run["run_id"])
    assert saved["condition"]["room"] == "anechoic"
    assert saved["condition"]["distance_cm"] == 45.5
    assert saved["condition"]["angle_deg"] == 15.0
    assert saved["recording"]["channels"] == [2]
    assert saved["recording"]["input_mode"] == "DIFFERENTIAL"
    assert saved["recording"]["ai_range"] == "BIP5VOLTS"
    assert saved["conversion"]["remove_dc"] is False
    assert saved["analysis"]["trim_start_s"] == 0.05
    assert saved["analysis"]["trim_end_s"] == 0.1
    assert saved["analysis"]["primary_band_hz"] == [500, 2500]
    assert saved["safety"]["operator"] == "lab tech"
    assert saved["safety"]["max_spl_db"] == 85.5
    assert saved["safety"]["notes"] == "ear protection checked"
    assert saved["mac_helper"]["planned_file"] == "planned.wav"
    assert saved["mac_helper"]["planned_device_id"] == 7
    assert saved["mac_helper"]["planned_sample_rate"] == 96000
    assert saved["mac_helper"]["planned_channels"] == 2
    assert saved["mac_helper"]["planned_gain"] == 0.6
    assert saved["mac_helper"]["planned_delay_ms"] == 125
    assert saved["files"]["wav_range"].endswith("__scale-range-fs5V.wav")
    assert saved["files"]["waveform_svg"] == f"plots/{saved['run_id']}_waveform.svg"
    assert saved["files"]["psd_svg"] == f"plots/{saved['run_id']}_psd.svg"
    assert saved["files"]["spectrogram_svg"] == f"plots/{saved['run_id']}_spectrogram.svg"


def test_zero_carrier_frequency_uses_baseline_r0_tag_and_route_accepts_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "baseline")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=0, uj="uj0")
    assert "_r0_uj0_" in run["run_id"]
    assert "_r0k_" not in run["run_id"]

    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    client = TestClient(create_app())
    response = client.post(
        f"/sessions/{session['session_id']}/runs",
        data={
            "carrier_freq_khz": "0",
            "uj": "uj1",
            "sample_rate_hz": "8000",
            "duration_s": "0.1",
            "scale_mode": "peak",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    saved_runs = sorted((session_dir(tmp_path, session["session_id"]) / "metadata").glob("*.json"))
    assert any("_r0_uj1_" in path.stem for path in saved_runs)


def test_finalization_honors_saved_analysis_band(tmp_path: Path):
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "analysis band")
    run = create_run_metadata(
        tmp_path,
        session["session_id"],
        carrier_freq_khz=25,
        uj="uj0",
        duration_s=0.5,
        analysis_band_low_hz=900,
        analysis_band_high_hz=1100,
    )
    final = record_mock_and_finalize(tmp_path, run)
    base = session_dir(tmp_path, session["session_id"])
    metrics = read_json(base / final["files"]["metrics_json"])
    assert metrics["band_hz"] == [900.0, 1100.0]
    assert metrics["band_power"] > 0
    assert "band_power_300_3400" in metrics


def test_plotting_trims_saved_bin_data_for_final_plots():
    data = np.arange(10, dtype=np.float64)
    trimmed = plotting_module._trim_for_plot(data, 10, trim_start_s=0.2, trim_end_s=0.3)
    assert trimmed.tolist() == [2, 3, 4, 5, 6]
    assert plotting_module._trim_for_plot(data, 10, trim_start_s=0.8, trim_end_s=0.5).tolist() == data.tolist()


def test_finalization_passes_saved_trim_settings_to_plot_generation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "plot trims")
    run = create_run_metadata(
        tmp_path,
        session["session_id"],
        carrier_freq_khz=25,
        uj="uj0",
        duration_s=0.2,
        trim_start_s=0.03,
        trim_end_s=0.04,
    )
    captured = {}

    def fake_plot_run(*args, **kwargs):
        captured.update(kwargs)
        run_id = args[3]
        return {
            "waveform_png": f"plots/{run_id}_waveform.png",
            "waveform_svg": f"plots/{run_id}_waveform.svg",
            "psd_png": f"plots/{run_id}_psd.png",
            "psd_svg": f"plots/{run_id}_psd.svg",
            "spectrogram_png": f"plots/{run_id}_spectrogram.png",
            "spectrogram_svg": f"plots/{run_id}_spectrogram.svg",
        }

    monkeypatch.setattr(recorder_module.plotting, "plot_run", fake_plot_run)
    record_mock_and_finalize(tmp_path, run)
    assert captured["trim_start_s"] == pytest.approx(0.03)
    assert captured["trim_end_s"] == pytest.approx(0.04)


def test_finalization_honors_saved_remove_dc_setting(tmp_path: Path):
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "finalize dc")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", duration_s=0.2)
    run["conversion"]["remove_dc"] = False
    base = session_dir(tmp_path, session["session_id"])
    fs = int(run["recording"]["sample_rate_hz"])
    t = np.arange(int(fs * run["recording"]["duration_s"])) / fs
    data = (1.0 + 0.2 * np.sin(2 * np.pi * 1000 * t)).astype("<f8")
    bin_path = base / run["files"]["bin"]
    bin_path.parent.mkdir(parents=True, exist_ok=True)
    data.tofile(bin_path)
    run["recording"]["written_samples"] = int(data.size)
    save_run(tmp_path, run)

    final = finalize_run(tmp_path, load_run(tmp_path, session["session_id"], run["run_id"]))
    metrics = read_json(base / final["files"]["metrics_json"])
    assert metrics["remove_dc"] is False
    assert metrics["dc_offset_v"] == pytest.approx(1.0, abs=1e-6)
    assert metrics["rms_v"] == pytest.approx(np.sqrt(1.0**2 + (0.2 / np.sqrt(2)) ** 2), rel=0.05)
    assert final["conversion"]["outputs"]["wav_peak"]["remove_dc"] is False


def test_plot_generation_failure_keeps_report_grade_metrics_and_logs_traceback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "plot failure")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", duration_s=0.1)

    def fail_plot(*args, **kwargs):
        raise RuntimeError("plot backend failed")

    monkeypatch.setattr(recorder_module.plotting, "plot_run", fail_plot)
    final = record_mock_and_finalize(tmp_path, run)
    base = session_dir(tmp_path, session["session_id"])
    assert final["analysis"]["status"] == "finalized"
    assert final["analysis"]["result_grade"] == "report-grade"
    assert final["analysis"]["plot_error"] == "plot backend failed"
    assert "plot_generation_failed" in final["quality_flags"]
    metrics = read_json(base / final["files"]["metrics_json"])
    assert metrics["result_grade"] == "report-grade"
    assert metrics["finalized_from_saved_bin"] is True
    assert "plot_generation_failed" in metrics["quality_flags"]
    assert metrics["plot_error"] == "plot backend failed"
    log_text = (base / "logs" / f"{final['run_id']}.log").read_text(encoding="utf-8")
    assert "plot_generation_failed metrics_saved=true" in log_text
    assert "Traceback" in log_text
    app_events = read_jsonl(tmp_path / ".micloaker" / "app_events.jsonl")
    assert app_events[-1]["event"] == "run_finalized"
    assert any(row["event"] == "plot_generation_failed" for row in app_events)


def test_new_run_form_exposes_analysis_and_safety_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "form")
    client = TestClient(create_app())
    page = client.get(f"/sessions/{session['session_id']}")
    assert page.status_code == 200
    assert "carrier-frequency-presets" in page.text
    assert 'value="25"' in page.text
    assert 'value="32.8"' in page.text
    upload_form = page.text.split(f'action="/sessions/{session["session_id"]}/runs/upload-bin"', 1)[1].split("Import + Finalize", 1)[0]
    assert "Advanced upload metadata" in upload_form
    for field in [
        "duration_s",
        "scale_mode",
        "remove_dc",
        "ai_range",
        "input_mode",
        "channel",
        "room",
        "distance_cm",
        "angle_deg",
        "safety_operator",
        "safety_max_spl_db",
        "safety_notes",
        "mac_helper_file",
        "mac_helper_device_id",
        "mac_helper_sample_rate",
        "mac_helper_channels",
        "mac_helper_gain",
        "mac_helper_delay_ms",
    ]:
        assert f'name="{field}"' in upload_form
    for field in [
        "trim_start_s",
        "trim_end_s",
        "remove_dc",
        "analysis_band_low_hz",
        "analysis_band_high_hz",
        "safety_operator",
        "safety_max_spl_db",
        "safety_notes",
        "mac_helper_file",
        "mac_helper_device_id",
        "mac_helper_sample_rate",
        "mac_helper_channels",
        "mac_helper_gain",
        "mac_helper_delay_ms",
    ]:
        assert field in page.text
    response = client.post(
        f"/sessions/{session['session_id']}/runs",
        data={
            "carrier_freq_khz": "25",
            "uj": "uj0",
            "sample_rate_hz": "8000",
            "duration_s": "0.1",
            "trim_start_s": "0.01",
            "trim_end_s": "0.02",
            "remove_dc": "false",
            "analysis_band_low_hz": "700",
            "analysis_band_high_hz": "1300",
            "safety_operator": "operator-a",
            "safety_max_spl_db": "82",
            "safety_notes": "checked",
            "mac_helper_file": "jamming_25khz.wav",
            "mac_helper_device_id": "3",
            "mac_helper_sample_rate": "192000",
            "mac_helper_channels": "1",
            "mac_helper_gain": "0.75",
            "mac_helper_delay_ms": "250",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    saved = read_json(next((session_dir(tmp_path, session["session_id"]) / "metadata").glob("*.json")))
    assert saved["conversion"]["remove_dc"] is False
    assert saved["analysis"]["primary_band_hz"] == [700.0, 1300.0]
    assert saved["safety"]["operator"] == "operator-a"
    assert saved["mac_helper"]["planned_file"] == "jamming_25khz.wav"
    assert saved["mac_helper"]["planned_device_id"] == 3
    assert saved["mac_helper"]["planned_sample_rate"] == 192000
    assert saved["mac_helper"]["planned_gain"] == 0.75
    detail = client.get(f"/sessions/{session['session_id']}/runs/{saved['run_id']}")
    assert "<th>Remove DC</th><td>False</td>" in detail.text
    assert "jamming_25khz.wav" in detail.text
    assert 'value="250"' in detail.text


def test_create_run_form_can_record_mock_immediately(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "create and record")
    client = TestClient(create_app())
    page = client.get(f"/sessions/{session['session_id']}")
    assert page.status_code == 200
    assert "Create + Record Mock" in page.text

    response = client.post(
        f"/sessions/{session['session_id']}/runs",
        data={
            "carrier_freq_khz": "32.8",
            "uj": "uj1",
            "sample_rate_hz": "8000",
            "duration_s": "0.1",
            "record_after_create": "true",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    saved = read_json(next((session_dir(tmp_path, session["session_id"]) / "metadata").glob("*.json")))
    assert saved["condition"]["carrier_freq_khz"] == 32.8
    assert saved["condition"]["uj"] == "uj1"
    assert saved["analysis"]["status"] == "finalized"
    assert saved["analysis"]["result_grade"] == "report-grade"
    assert saved["analysis"]["finalized_from_saved_bin"] is True
    assert (session_dir(tmp_path, session["session_id"]) / saved["files"]["bin"]).exists()


def test_dashboard_quick_capture_returns_to_command_console(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "dashboard quick capture")
    client = TestClient(create_app())
    page = client.get("/")
    assert 'name="return_to_dashboard" type="hidden" value="true"' in page.text
    assert 'id="capture"' in page.text

    response = client.post(
        f"/sessions/{session['session_id']}/runs",
        data={
            "carrier_freq_khz": "25",
            "uj": "uj0",
            "sound_condition": "sound1",
            "sample_rate_hz": "8000",
            "duration_s": "0.1",
            "record_after_create": "true",
            "return_to_dashboard": "true",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/#capture"
    saved = read_json(next((session_dir(tmp_path, session["session_id"]) / "metadata").glob("*.json")))
    assert saved["analysis"]["status"] == "finalized"
    assert saved["condition"]["sound_condition"] == "sound1"


def test_mock_recording_overrides_planned_source_in_metadata(tmp_path: Path):
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "mock source override")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", source="daq", duration_s=0.1)

    final = record_mock_and_finalize(tmp_path, run)

    assert final["recording"]["source"] == "mock"
    saved = load_run(tmp_path, session["session_id"], run["run_id"])
    assert saved["recording"]["source"] == "mock"
    assert saved["analysis"]["status"] == "finalized"
    assert saved["analysis"]["finalized_from_saved_bin"] is True
    assert (session_dir(tmp_path, session["session_id"]) / saved["files"]["metrics_json"]).exists()
    assert any(row["event"] == "run_finalized" for row in read_jsonl(session_dir(tmp_path, session["session_id"]) / "runs.jsonl"))


def test_run_creation_rejects_invalid_acquisition_and_analysis_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "invalid metadata")
    client = TestClient(create_app())
    response = client.post(
        f"/sessions/{session['session_id']}/runs",
        data={
            "carrier_freq_khz": "25",
            "uj": "uj0",
            "sample_rate_hz": "0",
            "duration_s": "-1",
            "scale_mode": "both",
            "full_scale_volts": "0",
            "trim_start_s": "-0.1",
            "analysis_band_low_hz": "3400",
            "analysis_band_high_hz": "300",
            "mac_helper_device_id": "-1",
            "mac_helper_sample_rate": "0",
            "mac_helper_channels": "0",
            "mac_helper_gain": "1.5",
            "mac_helper_delay_ms": "-1",
        },
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["error_code"] == "INVALID_RUN_METADATA"
    assert "sample_rate_hz must be positive" in detail["message"]
    assert "analysis band" in detail["message"]
    assert "full_scale_volts must be positive" in detail["message"]
    assert "mac_helper_device_id must be zero or positive" in detail["message"]
    assert "mac_helper_gain must be between 0 and 1" in detail["message"]
    assert not list((session_dir(tmp_path, session["session_id"]) / "metadata").glob("*.json"))


def test_create_and_upload_run_routes_require_existing_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    client = TestClient(create_app())

    create_response = client.post(
        "/sessions/missing_session/runs",
        data={"carrier_freq_khz": "25", "uj": "uj0", "sample_rate_hz": "8000", "duration_s": "0.1"},
    )
    assert create_response.status_code == 404
    detail = create_response.json()["detail"]
    assert detail["error_code"] == "SESSION_NOT_FOUND"
    assert "before adding runs" in detail["suggestion"]

    upload_response = client.post(
        "/sessions/missing_session/runs/upload-bin",
        data={"carrier_freq_khz": "25", "uj": "uj0", "sample_rate_hz": "8000", "full_scale_volts": "10"},
        files={"file": ("uploaded.bin", np.zeros(8, dtype="<f8").tobytes(), "application/octet-stream")},
    )
    assert upload_response.status_code == 404
    detail = upload_response.json()["detail"]
    assert detail["error_code"] == "SESSION_NOT_FOUND"
    assert not (tmp_path / "sessions" / "missing_session").exists()
    events = read_jsonl(tmp_path / ".micloaker" / "app_events.jsonl")
    assert [row["event"] for row in events] == ["indexes_rebuilt"]


def test_upload_bin_rejects_invalid_metadata_before_persisting_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "invalid upload metadata")
    client = TestClient(create_app())
    response = client.post(
        f"/sessions/{session['session_id']}/runs/upload-bin",
        data={
            "carrier_freq_khz": "25",
            "uj": "uj0",
            "sample_rate_hz": "8000",
            "duration_s": "0",
            "scale_mode": "range",
            "full_scale_volts": "0",
            "analysis_band_low_hz": "0",
            "analysis_band_high_hz": "100",
        },
        files={"file": ("uploaded.bin", b"\x00" * 16, "application/octet-stream")},
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["error_code"] == "INVALID_RUN_METADATA"
    assert "full_scale_volts must be positive" in detail["message"]
    assert not list((session_dir(tmp_path, session["session_id"]) / "metadata").glob("*.json"))


def test_import_bin_and_finalize_from_saved_raw_source(tmp_path: Path):
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "upload service")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", source="upload")
    source = tmp_path / "source.bin"
    fs = int(run["recording"]["sample_rate_hz"])
    t = np.arange(fs // 2) / fs
    (0.12 * np.sin(2 * np.pi * 1000 * t)).astype("<f8").tofile(source)
    final = import_bin_and_finalize(tmp_path, run, source)
    base = session_dir(tmp_path, session["session_id"])
    assert final["recording"]["source"] == "upload"
    assert final["recording"]["written_samples"] == fs // 2
    assert final["analysis"]["finalization_trigger"] == "upload_imported"
    assert final["analysis"]["finalized_from_saved_bin"] is True
    assert (base / final["files"]["bin"]).read_bytes() == source.read_bytes()
    assert final["analysis"]["status"] == "finalized"
    assert (base / final["files"]["metrics_json"]).exists()
    jobs = read_jsonl(tmp_path / ".micloaker" / "jobs.jsonl")
    assert [row["event"] for row in jobs[-2:]] == ["job_started", "job_finished"]
    assert all(row["type"] == "upload_import_and_finalize" for row in jobs[-2:])
    log_text = (base / "logs" / f"{run['run_id']}.log").read_text(encoding="utf-8")
    assert "job_started" in log_text
    assert "upload_import_and_finalize" in log_text
    assert "job_finished" in log_text


def test_import_bin_and_finalize_logs_direct_validation_failure(tmp_path: Path):
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "bad upload service")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", source="upload")
    source = tmp_path / "bad.bin"
    np.array([0.0, np.nan], dtype="<f8").tofile(source)

    with pytest.raises(ValueError, match="NaN or infinite"):
        import_bin_and_finalize(tmp_path, run, source)

    base = session_dir(tmp_path, session["session_id"])
    assert not (base / run["files"]["bin"]).exists()
    jobs = read_jsonl(tmp_path / ".micloaker" / "jobs.jsonl")
    assert [row["event"] for row in jobs[-2:]] == ["job_started", "job_failed"]
    assert all(row["type"] == "upload_import_and_finalize" for row in jobs[-2:])
    assert "NaN or infinite" in jobs[-1]["error"]
    assert "Traceback" in jobs[-1]["traceback"]
    log_text = (base / "logs" / f"{run['run_id']}.log").read_text(encoding="utf-8")
    assert "job_failed" in log_text
    assert "Traceback" in log_text


def test_finalize_propagates_sample_count_mismatch_to_run_metadata(tmp_path: Path):
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "mismatch")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", duration_s=1.0)
    source = tmp_path / "short.bin"
    t = np.arange(1000) / 8000
    (0.05 * np.sin(2 * np.pi * 1000 * t)).astype("<f8").tofile(source)
    final = import_bin_and_finalize(tmp_path, run, source)
    assert "sample_count_mismatch" in final["quality_flags"]
    assert final["recording"]["raw_size_bytes"] == source.stat().st_size
    assert final["recording"]["raw_sample_count"] == 1000
    assert final["recording"]["raw_dtype"] == "<f8"
    base = session_dir(tmp_path, session["session_id"])
    metrics = read_json(base / final["files"]["metrics_json"])
    assert metrics["expected_sample_count"] == 8000


def test_upload_bin_route_imports_and_rejects_non_bin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "upload route")
    client = TestClient(create_app())
    fs = 8000
    t = np.arange(fs // 4) / fs
    payload = (0.08 * np.sin(2 * np.pi * 900 * t)).astype("<f8").tobytes()
    response = client.post(
        f"/sessions/{session['session_id']}/runs/upload-bin",
        data={"carrier_freq_khz": "25", "uj": "uj0", "sample_rate_hz": str(fs), "full_scale_volts": "10", "remove_dc": "false"},
        files={"file": ("uploaded.bin", payload, "application/octet-stream")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    runs = list((session_dir(tmp_path, session["session_id"]) / "metadata").glob("*.json"))
    assert len(runs) == 1
    saved = read_json(runs[0])
    assert saved["recording"]["source"] == "upload"
    assert saved["recording"]["actual_sample_rate_hz"] == fs
    assert saved["recording"]["written_samples"] == fs // 4
    assert saved["conversion"]["remove_dc"] is False
    assert saved["conversion"]["outputs"]["wav_peak"]["remove_dc"] is False
    assert saved["analysis"]["status"] == "finalized"
    assert saved["analysis"]["result_grade"] == "report-grade"
    bad = client.post(
        f"/sessions/{session['session_id']}/runs/upload-bin",
        data={"carrier_freq_khz": "25", "uj": "uj0", "sample_rate_hz": str(fs)},
        files={"file": ("uploaded.txt", b"bad", "text/plain")},
    )
    assert bad.status_code == 400
    assert bad.json()["detail"]["error_code"] == "INVALID_RAW_BIN"


def test_upload_bin_rejects_invalid_raw_bin_before_persisting_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "invalid raw upload")
    client = TestClient(create_app())
    response = client.post(
        f"/sessions/{session['session_id']}/runs/upload-bin",
        data={"carrier_freq_khz": "25", "uj": "uj0", "sample_rate_hz": "8000", "full_scale_volts": "10"},
        files={"file": ("bad.bin", b"not-f8", "application/octet-stream")},
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["error_code"] == "INVALID_RAW_BIN"
    assert "divisible by 8" in detail["message"]
    assert "float64 voltage samples" in detail["suggestion"]
    assert not list((session_dir(tmp_path, session["session_id"]) / "metadata").glob("*.json"))

    nan_payload = np.array([0.0, np.nan], dtype="<f8").tobytes()
    response = client.post(
        f"/sessions/{session['session_id']}/runs/upload-bin",
        data={"carrier_freq_khz": "25", "uj": "uj0", "sample_rate_hz": "8000", "full_scale_volts": "10"},
        files={"file": ("nan.bin", nan_payload, "application/octet-stream")},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["error_code"] == "INVALID_RAW_BIN"
    assert "NaN or infinite" in response.json()["detail"]["message"]
    assert not list((session_dir(tmp_path, session["session_id"]) / "metadata").glob("*.json"))


def test_validate_raw_bin_source_rejects_invalid_float64_container(tmp_path: Path):
    invalid_size = tmp_path / "invalid.bin"
    invalid_size.write_bytes(b"123")
    with pytest.raises(ValueError, match="divisible by 8"):
        validate_raw_bin_source(invalid_size)

    empty = tmp_path / "empty.bin"
    empty.write_bytes(b"")
    with pytest.raises(ValueError, match="empty"):
        validate_raw_bin_source(empty)

    valid = tmp_path / "valid.bin"
    np.array([0.0, 0.1, -0.1], dtype="<f8").tofile(valid)
    assert validate_raw_bin_source(valid) == {"size_bytes": 24, "sample_count": 3, "dtype": "<f8"}


def test_manual_convert_and_finalize_require_explicit_overwrite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "overwrite")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", duration_s=0.1)
    final = record_mock_and_finalize(tmp_path, run)
    client = TestClient(create_app())
    convert_conflict = client.post(f"/sessions/{session['session_id']}/runs/{final['run_id']}/convert")
    assert convert_conflict.status_code == 409
    assert convert_conflict.json()["detail"]["error_code"] == "DERIVED_OUTPUT_EXISTS"
    convert_ok = client.post(
        f"/sessions/{session['session_id']}/runs/{final['run_id']}/convert",
        data={"overwrite_existing": "true"},
        follow_redirects=False,
    )
    assert convert_ok.status_code == 303
    finalize_conflict = client.post(f"/sessions/{session['session_id']}/runs/{final['run_id']}/finalize")
    assert finalize_conflict.status_code == 409
    finalize_ok = client.post(
        f"/sessions/{session['session_id']}/runs/{final['run_id']}/finalize",
        data={"overwrite_existing": "true"},
        follow_redirects=False,
    )
    assert finalize_ok.status_code == 303
    page = client.get(f"/sessions/{session['session_id']}/runs/{final['run_id']}")
    assert "overwrite derived outputs" in page.text
    assert "overwrite WAVs" in page.text
    jobs = read_jsonl(tmp_path / ".micloaker" / "jobs.jsonl")
    manual_convert = [row for row in jobs if row.get("type") == "manual_convert_wav"]
    manual_finalize = [row for row in jobs if row.get("type") == "manual_finalize"]
    assert any(row["status"] == "failed" and row["traceback"] for row in manual_convert)
    assert any(row["status"] == "finished" for row in manual_convert)
    assert any(row["status"] == "failed" and row["traceback"] for row in manual_finalize)
    assert any(row["status"] == "finished" for row in manual_finalize)
    log_text = (session_dir(tmp_path, session["session_id"]) / "logs" / f"{final['run_id']}.log").read_text(encoding="utf-8")
    assert "job_started" in log_text
    assert "manual_convert_wav" in log_text
    assert "manual_finalize" in log_text


def test_manual_finalize_requires_overwrite_for_existing_metrics_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "metrics overwrite")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", duration_s=0.1)
    base = session_dir(tmp_path, session["session_id"])
    fs = int(run["recording"]["sample_rate_hz"])
    t = np.arange(int(fs * run["recording"]["duration_s"])) / fs
    bin_path = base / run["files"]["bin"]
    bin_path.parent.mkdir(parents=True, exist_ok=True)
    (0.05 * np.sin(2 * np.pi * 1000 * t)).astype("<f8").tofile(bin_path)
    metrics_path = base / run["files"]["metrics_json"]
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text('{"stale": true}\n', encoding="utf-8")
    client = TestClient(create_app())

    conflict = client.post(f"/sessions/{session['session_id']}/runs/{run['run_id']}/finalize")
    assert conflict.status_code == 409
    detail = conflict.json()["detail"]
    assert detail["error_code"] == "DERIVED_OUTPUT_EXISTS"
    assert "existing metrics" in detail["message"]
    assert read_json(metrics_path) == {"stale": True}
    assert not (base / run["files"]["wav_peak"]).exists()

    overwrite = client.post(
        f"/sessions/{session['session_id']}/runs/{run['run_id']}/finalize",
        data={"overwrite_existing": "true"},
        follow_redirects=False,
    )
    assert overwrite.status_code == 303
    saved = load_run(tmp_path, session["session_id"], run["run_id"])
    assert saved["analysis"]["status"] == "finalized"
    assert "stale" not in read_json(metrics_path)


def test_manual_convert_and_finalize_report_missing_raw_bin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "missing raw bin")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", duration_s=0.1)
    client = TestClient(create_app())

    convert = client.post(f"/sessions/{session['session_id']}/runs/{run['run_id']}/convert")
    assert convert.status_code == 400
    detail = convert.json()["detail"]
    assert detail["error_code"] == "RAW_BIN_MISSING"
    assert "import a raw float64 .bin" in detail["suggestion"]

    finalize = client.post(f"/sessions/{session['session_id']}/runs/{run['run_id']}/finalize")
    assert finalize.status_code == 400
    detail = finalize.json()["detail"]
    assert detail["error_code"] == "RAW_BIN_MISSING"
    assert "report-grade metrics" in detail["suggestion"]
    saved = load_run(tmp_path, session["session_id"], run["run_id"])
    assert saved["analysis"]["status"] == "failed"
    assert saved["analysis"]["result_grade"] == "none"
    assert saved["analysis"]["finalization_trigger"] == "manual"
    assert "No such file" in saved["analysis"]["last_error"] or "does not exist" in saved["analysis"]["last_error"]
    assert saved["analysis"]["error_log"] == f"logs/{run['run_id']}.log"
    assert "finalization_failed" in saved["quality_flags"]
    events = read_jsonl(session_dir(tmp_path, session["session_id"]) / "events.jsonl")
    assert any(row["event"] == "run_finalization_failed" and row["run_id"] == run["run_id"] for row in events)
    jobs = read_jsonl(tmp_path / ".micloaker" / "jobs.jsonl")
    failed_finalize = [row for row in jobs if row.get("type") == "manual_finalize" and row.get("status") == "failed"]
    assert failed_finalize
    assert all(row["traceback"] for row in failed_finalize)
    log_text = (session_dir(tmp_path, session["session_id"]) / "logs" / f"{run['run_id']}.log").read_text(encoding="utf-8")
    assert "job_failed" in log_text
    assert "finalization_failed metadata_saved=true" in log_text


def test_manual_convert_and_finalize_reject_invalid_saved_raw_bin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "invalid saved raw bin")
    run = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", duration_s=0.1)
    base = session_dir(tmp_path, session["session_id"])
    bin_path = base / run["files"]["bin"]
    bin_path.parent.mkdir(parents=True, exist_ok=True)
    np.array([0.0, np.nan, 1.0], dtype="<f8").tofile(bin_path)
    client = TestClient(create_app())

    convert = client.post(f"/sessions/{session['session_id']}/runs/{run['run_id']}/convert")
    assert convert.status_code == 400
    detail = convert.json()["detail"]
    assert detail["error_code"] == "RAW_BIN_INVALID"
    assert "NaN or infinite" in detail["message"]
    assert not (base / run["files"]["wav_peak"]).exists()

    finalize = client.post(f"/sessions/{session['session_id']}/runs/{run['run_id']}/finalize")
    assert finalize.status_code == 400
    detail = finalize.json()["detail"]
    assert detail["error_code"] == "RAW_BIN_INVALID"
    assert "report-grade metrics" in detail["suggestion"]
    assert not (base / run["files"]["metrics_json"]).exists()
    saved = load_run(tmp_path, session["session_id"], run["run_id"])
    assert saved["analysis"]["status"] == "failed"
    assert saved["analysis"]["result_grade"] == "none"
    assert saved["analysis"]["finalization_trigger"] == "manual"
    assert "NaN or infinite" in saved["analysis"]["last_error"]
    assert saved["analysis"]["error_log"] == f"logs/{run['run_id']}.log"
    assert "finalization_failed" in saved["quality_flags"]
    events = read_jsonl(base / "events.jsonl")
    assert any(row["event"] == "run_finalization_failed" and row["run_id"] == run["run_id"] for row in events)

    jobs = read_jsonl(tmp_path / ".micloaker" / "jobs.jsonl")
    failed = [row for row in jobs if row.get("status") == "failed"]
    assert len(failed) == 2
    assert all(row["traceback"] for row in failed)
    log_text = (session_dir(tmp_path, session["session_id"]) / "logs" / f"{run['run_id']}.log").read_text(encoding="utf-8")
    assert "job_failed" in log_text
    assert "finalization_failed metadata_saved=true" in log_text

    np.sin(2 * np.pi * 1000 * np.arange(800) / 8000).astype("<f8").tofile(bin_path)
    retry = client.post(f"/sessions/{session['session_id']}/runs/{run['run_id']}/finalize")
    assert retry.status_code == 200
    recovered = load_run(tmp_path, session["session_id"], run["run_id"])
    assert recovered["analysis"]["status"] == "finalized"
    assert recovered["analysis"]["result_grade"] == "report-grade"
    assert recovered["analysis"]["finalized_from_saved_bin"] is True
    assert "last_error" not in recovered["analysis"]
    assert "failed_at" not in recovered["analysis"]
    assert "error_log" not in recovered["analysis"]
    assert "plot_error" not in recovered["analysis"]
    assert "finalization_failed" not in recovered["quality_flags"]
    assert (base / recovered["files"]["metrics_json"]).exists()


def test_core_run_actions_validate_session_and_run_targets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "stale run action targets")
    client = TestClient(create_app())
    actions = ["record-mock", "record-daq", "convert", "finalize"]

    for action in actions:
        response = client.post(f"/sessions/missing_session/runs/missing_run/{action}")
        assert response.status_code == 404
        detail = response.json()["detail"]
        assert detail["error_code"] == "SESSION_NOT_FOUND"
        assert "missing_session" in detail["message"]

    for action in actions:
        response = client.post(f"/sessions/{session['session_id']}/runs/missing_run/{action}")
        assert response.status_code == 404
        detail = response.json()["detail"]
        assert detail["error_code"] == "RUN_NOT_FOUND"
        assert "missing_run" in detail["message"]

    assert not list((session_dir(tmp_path, session["session_id"]) / "logs").glob("missing_run.log"))
    jobs = read_jsonl(tmp_path / ".micloaker" / "jobs.jsonl")
    assert not [job for job in jobs if job.get("logs", "").endswith("missing_run.log")]


def test_range_conversion_requires_positive_full_scale_voltage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "range full scale")
    run = create_run_metadata(
        tmp_path,
        session["session_id"],
        carrier_freq_khz=25,
        uj="uj0",
        duration_s=0.1,
        scale_mode="range",
        full_scale_volts=0.0,
    )
    base = session_dir(tmp_path, session["session_id"])
    data = np.zeros(800, dtype="<f8")
    (base / run["files"]["bin"]).parent.mkdir(parents=True, exist_ok=True)
    data.tofile(base / run["files"]["bin"])
    client = TestClient(create_app())
    response = client.post(f"/sessions/{session['session_id']}/runs/{run['run_id']}/convert")
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["error_code"] == "INVALID_CONVERSION_CONFIG"
    assert "full_scale_volts" in detail["message"]


def test_session_detail_filters_runs_and_sessions_table_counts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "filters")
    run0 = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", mic_id="micA", room="lab", duration_s=0.1)
    run1 = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=32.8, uj="uj1", mic_id="micB", room="hall", duration_s=0.1)
    final0 = record_mock_and_finalize(tmp_path, run0)
    client = TestClient(create_app())
    page = client.get(f"/sessions/{session['session_id']}?uj=uj0&mic_id=micA&analysis_status=finalized")
    assert page.status_code == 200
    assert "Session Summary" in page.text
    assert "filters" in page.text
    assert "Runs" in page.text
    assert "Finalized" in page.text
    assert "Comparisons" in page.text
    assert f'/sessions/{session["session_id"]}/files/summary.csv?download=1' in page.text
    assert f'/sessions/{session["session_id"]}/files/session_report.md?download=1' in page.text
    assert f'/exports/sessions/{session["session_id"]}.zip' in page.text
    assert final0["run_id"] in page.text
    assert run1["run_id"] not in page.text
    sessions_page = client.get("/sessions")
    assert sessions_page.status_code == 200
    assert "session_id" in sessions_page.text
    assert ">2<" in sessions_page.text
    assert ">1<" in sessions_page.text


def test_session_detail_returns_structured_missing_session_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    client = TestClient(create_app())
    response = client.get("/sessions/missing_session")
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["error_code"] == "SESSION_NOT_FOUND"
    assert "missing_session" in detail["message"]
    assert "Sessions page" in detail["suggestion"]
    assert not (tmp_path / "sessions" / "missing_session").exists()


def test_new_run_page_selects_session_and_nav_points_there(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "new run nav")
    create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0")
    client = TestClient(create_app())
    page = client.get("/runs/new")
    assert page.status_code == 200
    assert "Choose a Session" in page.text
    assert "Run Metadata" in page.text
    assert f'action="/sessions/{session["session_id"]}/runs"' in page.text
    for field in [
        "carrier_freq_khz",
        "uj",
        "sound_condition",
        "duration_s",
        "sample_rate_hz",
        "scale_mode",
        "remove_dc",
        "ai_range",
        "mac_helper_file",
    ]:
        assert f'name="{field}"' in page.text
    assert session["session_id"] in page.text
    assert f"/sessions/{session['session_id']}" in page.text
    assert "1 runs" in page.text
    response = client.post(
        f"/sessions/{session['session_id']}/runs",
        data={
            "carrier_freq_khz": "32.8",
            "uj": "uj1",
            "sound_condition": "speech",
            "sample_rate_hz": "8000",
            "duration_s": "0.1",
            "scale_mode": "peak",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert len(load_runs(tmp_path, session["session_id"])) == 2
    nav = client.get("/")
    assert 'href="/runs/new">New Run</a>' in nav.text


def test_dashboard_shows_lab_status_cards_and_shortcuts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MICLOAKER_WORKSPACE", str(tmp_path))
    ensure_workspace(tmp_path)
    session = create_session(tmp_path, "dashboard")
    run0 = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj0", duration_s=0.15)
    run1 = create_run_metadata(tmp_path, session["session_id"], carrier_freq_khz=25, uj="uj1", duration_s=0.15)
    final0 = record_mock_and_finalize(tmp_path, run0)
    final1 = record_mock_and_finalize(tmp_path, run1)
    client = TestClient(create_app())
    client.post(
        f"/compare/{session['session_id']}",
        data={"uj0_run_id": final0["run_id"], "uj1_run_id": final1["run_id"], "source": "bin", "band_mode": "primary"},
        follow_redirects=True,
    )
    page = client.get("/")
    assert page.status_code == 200
    for text in [
        "Experiment Command Center",
        "Session",
        "Acquisition",
        "Mac Playback",
        "Capture And Live Preview",
        "RMS/Peak Meter",
        "Scrolling Spectrogram",
        "Create + Record Mock",
        "Create + Record DAQ",
        "Advanced Metadata",
        "Latest Run",
        "Latest Comparison",
        "Results, Compare, Export",
        "Latest Visual Artifacts",
        "Waveform",
        "PSD",
        "Spectrogram",
        "Peak WAV Preview",
        "preview only",
        "Export active session ZIP",
    ]:
        assert text in page.text
    assert "tab-panel" not in page.text
    assert "data-tabs" not in page.text
    assert "live-waveform" in page.text
    assert "Record Latest Mock" not in page.text
    assert 'action="/sessions/' in page.text and '/runs"' in page.text
    css = client.get("/static/css/app.css").text
    assert ".live-command-card .capture-actions" in css
    assert ".quick-capture-form" in css
    assert "position: sticky" in css
    assert "data-recording-submit" in page.text
    js = client.get("/static/js/live.js").text
    assert "updateRecordingGuard" in js
    assert "active_recording" in js
    assert session["session_id"] in page.text
    assert final1["run_id"] in page.text
    assert f'src="/sessions/{session["session_id"]}/files/{final1["files"]["waveform_png"]}"' in page.text
    assert f'src="/sessions/{session["session_id"]}/files/{final1["files"]["wav_peak"]}"' in page.text
    assert "dB" in page.text
