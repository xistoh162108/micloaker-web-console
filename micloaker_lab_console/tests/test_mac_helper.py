from __future__ import annotations

import wave
import sys
import types
from threading import Event
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

import mac_helper.helper as helper_module
from mac_helper.helper import _resample_audio, create_app


def _wav(path: Path):
    data = (np.zeros(800, dtype=np.int16)).tobytes()
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(8000)
        wf.writeframes(data)


def _wav_with_channels(path: Path, channels: int):
    data = np.zeros((800, channels), dtype=np.int16).tobytes()
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(8000)
        wf.writeframes(data)


def test_mac_helper_files_and_path_validation(tmp_path: Path):
    _wav(tmp_path / "tone.wav")
    client = TestClient(create_app({"wav_root": str(tmp_path), "mock_audio": True}))
    health = client.get("/health").json()
    assert health["ok"] is True
    devices = client.get("/devices").json()
    assert devices["ok"] is True
    assert devices["output_devices"][0]["name"] == "Mock Output Device"
    files = client.get("/files").json()
    assert files["files"][0]["path"] == "tone.wav"
    ok = client.post("/validate-playback", json={"file": "tone.wav", "device_id": 1, "sample_rate": 8000, "channels": 1, "gain": 0.5}).json()
    assert ok["ok"] is True
    assert ok["device_name"] == "Mock Output Device"
    assert ok["device_max_output_channels"] == 2
    assert ok["device_default_samplerate"] == 192000.0
    assert ok["device_hostapi"] == "Mock"
    bad = client.post("/validate-playback", json={"file": "../tone.wav", "device_id": 1, "sample_rate": 8000, "channels": 1, "gain": 0.5}).json()
    assert bad["ok"] is False
    assert bad["error_code"] == "PATH_TRAVERSAL_REJECTED"
    absolute_bad = client.post("/validate-playback", json={"file": str(tmp_path / "tone.wav"), "device_id": 1, "sample_rate": 8000, "channels": 1, "gain": 0.5}).json()
    assert absolute_bad["ok"] is False
    assert absolute_bad["error_code"] == "ABSOLUTE_PATH_REJECTED"
    assert "relative" in absolute_bad["message"]
    sibling = tmp_path.parent / f"{tmp_path.name}_sibling"
    sibling.mkdir()
    _wav(sibling / "tone.wav")
    symlink_path = tmp_path / "linked_outside.wav"
    try:
        symlink_path.symlink_to(sibling / "tone.wav")
    except OSError:
        symlink_path = None
    sibling_bad = client.post("/validate-playback", json={"file": f"../{sibling.name}/tone.wav", "device_id": 1, "sample_rate": 8000, "channels": 1, "gain": 0.5}).json()
    assert sibling_bad["ok"] is False
    assert sibling_bad["error_code"] == "PATH_TRAVERSAL_REJECTED"
    if symlink_path is not None:
        files_after_symlink = client.get("/files").json()
        assert "linked_outside.wav" not in [row["path"] for row in files_after_symlink["files"]]
        symlink_bad = client.post("/validate-playback", json={"file": "linked_outside.wav", "device_id": 1, "sample_rate": 8000, "channels": 1, "gain": 0.5}).json()
        assert symlink_bad["ok"] is False
        assert symlink_bad["error_code"] == "PATH_TRAVERSAL_REJECTED"


def test_mac_helper_play_status_stop_and_validation_errors(tmp_path: Path):
    _wav(tmp_path / "tone.wav")
    client = TestClient(create_app({"wav_root": str(tmp_path), "mock_audio": True}))
    mismatch = client.post("/validate-playback", json={"file": "tone.wav", "device_id": 1, "sample_rate": 16000, "channels": 1, "gain": 0.5}).json()
    assert mismatch["ok"] is True
    assert mismatch["source_sample_rate"] == 8000
    assert mismatch["requested_sample_rate"] == 16000
    assert mismatch["will_resample"] is True
    gain = client.post("/validate-playback", json={"file": "tone.wav", "device_id": 1, "sample_rate": 8000, "channels": 1, "gain": 1.5}).json()
    assert gain["error_code"] == "INVALID_GAIN"
    bad_rate = client.post("/validate-playback", json={"file": "tone.wav", "device_id": 1, "sample_rate": 0, "channels": 1, "gain": 0.5}).json()
    assert bad_rate["error_code"] == "INVALID_SAMPLE_RATE"
    bad_device = client.post("/validate-playback", json={"file": "tone.wav", "device_id": 999, "sample_rate": 8000, "channels": 1, "gain": 0.5}).json()
    assert bad_device["ok"] is False
    assert bad_device["error_code"] == "DEVICE_NOT_FOUND"
    validation_status = client.get("/status").json()
    assert validation_status["playing"] is False
    assert validation_status["last_validation_ok"] is False
    assert validation_status["last_validation_request"]["device_id"] == 999
    assert validation_status["last_error_code"] == "DEVICE_NOT_FOUND"
    assert validation_status["last_error"] == "The selected output device does not exist."
    assert validation_status["last_suggestion"] == "Refresh device list and choose a valid output device."
    ok_after_failure = client.post("/validate-playback", json={"file": "tone.wav", "device_id": 1, "sample_rate": 8000, "channels": 1, "gain": 0.5}).json()
    assert ok_after_failure["ok"] is True
    cleared_status = client.get("/status").json()
    assert cleared_status["last_validation_ok"] is True
    assert cleared_status["last_error_code"] is None
    bad_delay = client.post("/play", json={"file": "tone.wav", "device_id": 1, "sample_rate": 8000, "channels": 1, "gain": 0.5, "delay_ms": -1}).json()
    assert bad_delay["error_code"] == "INVALID_DELAY"
    failed_status = client.get("/status").json()
    assert failed_status["playing"] is False
    assert failed_status["last_error_code"] == "INVALID_DELAY"
    assert failed_status["last_error"] == "Delay must be zero or positive."
    assert failed_status["last_suggestion"] == "Use a delay of 0 ms or greater."
    play = client.post("/play", json={"file": "tone.wav", "device_id": 1, "sample_rate": 8000, "channels": 1, "gain": 0.5, "delay_ms": 25}).json()
    assert play["ok"] is True
    assert play["device_id"] == 1
    assert play["device_name"] == "Mock Output Device"
    assert play["device_max_output_channels"] == 2
    assert play["device_default_samplerate"] == 192000.0
    assert play["device_hostapi"] == "Mock"
    assert play["delay_ms"] == 25
    assert play["source_sample_rate"] == 8000
    assert play["requested_sample_rate"] == 8000
    assert play["will_resample"] is False
    assert play["duration_s"] == 0.1
    assert play["source_channels"] == 1
    assert play["requested_channels"] == 1
    assert play["will_channel_map"] is False
    assert play["expected_end_after_s"] == 0.125
    assert play["play_id"].startswith("play_")
    assert play["play_id"].endswith("_001")
    second_play = client.post("/play", json={"file": "tone.wav", "device_id": 1, "sample_rate": 8000, "channels": 1, "gain": 0.5, "delay_ms": 0}).json()
    assert second_play["ok"] is True
    assert second_play["play_id"] != play["play_id"]
    assert second_play["play_id"].endswith("_002")
    status = client.get("/status").json()
    assert status["ok"] is True
    assert status["playing"] is True
    assert status["file"] == "tone.wav"
    assert status["device_id"] == 1
    assert status["device_name"] == "Mock Output Device"
    assert status["device_max_output_channels"] == 2
    assert status["device_default_samplerate"] == 192000.0
    assert status["device_hostapi"] == "Mock"
    assert status["sample_rate"] == 8000
    assert status["source_sample_rate"] == 8000
    assert status["channels"] == 1
    assert status["source_channels"] == 1
    assert status["gain"] == 0.5
    assert status["delay_ms"] == 0
    assert status["duration_s"] == 0.1
    assert status["last_error"] is None
    assert status["last_error_code"] is None
    assert status["last_suggestion"] is None
    helper_module.STATE["started"] -= 1.0
    completed = client.get("/status").json()
    assert completed["ok"] is True
    assert completed["playing"] is False
    assert completed["current_play_id"] == second_play["play_id"]
    stopped = client.post("/stop").json()
    assert stopped == {"ok": True, "playing": False}
    assert client.get("/status").json()["playing"] is False


def test_mac_helper_optional_token_requires_bearer_auth(tmp_path: Path):
    _wav(tmp_path / "tone.wav")
    client = TestClient(create_app({"wav_root": str(tmp_path), "mock_audio": True, "optional_token": "secret-token"}))

    missing = client.get("/health")
    assert missing.status_code == 401
    assert missing.json()["error_code"] == "UNAUTHORIZED"

    wrong = client.get("/health", headers={"Authorization": "Bearer wrong"})
    assert wrong.status_code == 401
    assert wrong.json()["ok"] is False

    ok = client.get("/health", headers={"Authorization": "Bearer secret-token"})
    assert ok.status_code == 200
    assert ok.json()["ok"] is True


def test_mac_helper_stop_failure_persists_structured_status_error(tmp_path: Path, monkeypatch):
    _wav(tmp_path / "tone.wav")

    def stop():
        raise RuntimeError("audio backend stop failed")

    monkeypatch.setitem(sys.modules, "sounddevice", types.SimpleNamespace(stop=stop))
    client = TestClient(create_app({"wav_root": str(tmp_path), "mock_audio": False}))
    failed = client.post("/stop").json()
    assert failed["ok"] is False
    assert failed["error_code"] == "STOP_FAILED"

    status = client.get("/status").json()
    assert status["ok"] is True
    assert status["playing"] is False
    assert status["last_error_code"] == "STOP_FAILED"
    assert status["last_error"] == "audio backend stop failed"
    assert status["last_suggestion"] == "Check the audio backend and retry."


def test_mac_helper_status_accounts_for_delayed_playback_window(tmp_path: Path):
    _wav(tmp_path / "tone.wav")
    client = TestClient(create_app({"wav_root": str(tmp_path), "mock_audio": True}))
    play = client.post(
        "/play",
        json={"file": "tone.wav", "device_id": 1, "sample_rate": 8000, "channels": 1, "gain": 0.5, "delay_ms": 500},
    ).json()
    assert play["ok"] is True

    helper_module.STATE["started"] -= 0.2
    during_delay = client.get("/status").json()
    assert during_delay["playing"] is True
    assert abs(during_delay["expected_end_after_s"] - 0.6) < 1e-9

    helper_module.STATE["started"] -= 0.5
    after_delay_and_audio = client.get("/status").json()
    assert after_delay_and_audio["playing"] is False


def test_mac_helper_stop_cancels_delayed_real_playback_before_audio_starts(tmp_path: Path, monkeypatch):
    _wav(tmp_path / "tone.wav")
    sleep_started = Event()
    release_sleep = Event()
    play_calls = []
    stop_calls = []

    def fake_sleep(seconds):
        sleep_started.set()
        release_sleep.wait(1.0)

    fake_sounddevice = types.SimpleNamespace(
        query_devices=lambda: [{"name": "USB DAC", "max_output_channels": 2, "default_samplerate": 8000.0, "hostapi": "Core Audio"}],
        check_output_settings=lambda device, samplerate, channels: None,
        play=lambda data, samplerate, device, blocking: play_calls.append(
            {"samplerate": samplerate, "device": device, "blocking": blocking, "shape": data.shape}
        ),
        stop=lambda: stop_calls.append(True),
    )
    fake_soundfile = types.SimpleNamespace(read=lambda path, always_2d: (np.zeros((800, 1), dtype=np.float32), 8000))
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sounddevice)
    monkeypatch.setitem(sys.modules, "soundfile", fake_soundfile)
    monkeypatch.setattr(helper_module.time, "sleep", fake_sleep)
    client = TestClient(create_app({"wav_root": str(tmp_path), "mock_audio": False}))

    play = client.post(
        "/play",
        json={"file": "tone.wav", "device_id": 0, "sample_rate": 8000, "channels": 1, "gain": 0.5, "delay_ms": 500},
    ).json()
    assert play["ok"] is True
    assert sleep_started.wait(1.0) is True

    stopped = client.post("/stop").json()
    release_sleep.set()

    assert stopped == {"ok": True, "playing": False}
    assert stop_calls == [True]
    assert play_calls == []
    status = client.get("/status").json()
    assert status["playing"] is False
    assert status["stopped_play_id"] == play["play_id"]


def test_mac_helper_numpy_resampler_preserves_channels_and_duration():
    data = np.column_stack([np.linspace(-1, 1, 8), np.linspace(1, -1, 8)]).astype(np.float32)
    upsampled = _resample_audio(data, 8000, 16000)
    downsampled = _resample_audio(data, 8000, 4000)
    assert upsampled.shape == (16, 2)
    assert downsampled.shape == (4, 2)
    assert upsampled.dtype == np.float32


def test_mac_helper_mock_mode_validates_output_channel_capacity(tmp_path: Path):
    _wav_with_channels(tmp_path / "wide.wav", channels=3)
    _wav(tmp_path / "mono.wav")
    client = TestClient(create_app({"wav_root": str(tmp_path), "mock_audio": True}))
    mono_to_stereo = client.post(
        "/validate-playback",
        json={"file": "mono.wav", "device_id": 1, "sample_rate": 8000, "channels": 2, "gain": 0.5},
    ).json()
    assert mono_to_stereo["ok"] is True
    assert mono_to_stereo["channels"] == 1
    assert mono_to_stereo["requested_channels"] == 2
    assert mono_to_stereo["will_channel_map"] is True

    too_many_channels = client.post(
        "/validate-playback",
        json={"file": "wide.wav", "device_id": 1, "sample_rate": 8000, "channels": 3, "gain": 0.5},
    ).json()
    assert too_many_channels["ok"] is False
    assert too_many_channels["error_code"] == "UNSUPPORTED_CHANNELS"


def test_mac_helper_malformed_playback_requests_return_structured_errors(tmp_path: Path):
    _wav(tmp_path / "tone.wav")
    client = TestClient(create_app({"wav_root": str(tmp_path), "mock_audio": True}))
    missing = client.post("/validate-playback", json={"file": "tone.wav", "sample_rate": 8000}).json()
    assert missing["ok"] is False
    assert missing["error_code"] == "INVALID_REQUEST"
    assert "device_id" in missing["message"]
    assert "suggestion" in missing

    malformed = client.post("/play", content="{bad json", headers={"content-type": "application/json"}).json()
    assert malformed["ok"] is False
    assert malformed["error_code"] == "INVALID_REQUEST"
