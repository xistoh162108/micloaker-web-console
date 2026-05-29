# Optional macOS Audio Helper Specification

## 1. Purpose

The macOS Audio Helper is a small optional companion service that controls Mac-side experiment playback. It replaces the narrow Audacity use case of playing a specific prepared WAV file through a chosen output device at a chosen sample rate.

It does not automate Audacity and does not need to be always running.

## 2. Assumptions

- Mac plays experiment WAV files.
- Linux records/analyzes DAQ/mic data.
- Mac and Linux can reach each other through Tailscale.
- WAV files already exist on Mac under a configured root directory.
- Linux Console can send HTTP requests to the Helper.

## 3. Runtime

Example:

```bash
cd ~/micloaker-mac-helper
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-mac-helper.txt
python helper.py --config config.json
```

Default URL example:

```text
http://0.0.0.0:5050
```

Linux connects through a Tailscale IP/hostname, e.g.:

```text
http://100.x.y.z:5050
```

## 4. Configuration

Example `config.json`:

```json
{
  "wav_root": "/Users/user/MicloakerSounds",
  "host": "0.0.0.0",
  "port": 5050,
  "default_sample_rate": 192000,
  "default_channels": 1,
  "default_gain": 1.0,
  "optional_token": null
}
```

## 5. Required APIs

### `GET /health`

Returns service status.

```json
{
  "ok": true,
  "service": "micloaker-mac-audio-helper",
  "version": "0.1.0",
  "hostname": "MacBook-Pro",
  "os": "macOS",
  "uptime_s": 123.4,
  "wav_root": "/Users/user/MicloakerSounds",
  "wav_root_exists": true,
  "audio_backend": "sounddevice",
  "server_time": "2026-05-28T21:15:00+09:00"
}
```

### `GET /devices`

Returns output devices only.

```json
{
  "ok": true,
  "output_devices": [
    {
      "id": 3,
      "name": "USB Audio Device",
      "max_output_channels": 2,
      "default_samplerate": 48000.0,
      "hostapi": "Core Audio"
    }
  ]
}
```

### `GET /files`

Lists `.wav` files under `wav_root`, using relative paths only.

```json
{
  "ok": true,
  "files": [
    {"path": "jamming_25khz.wav", "size_bytes": 12345, "duration_s": 10.0, "sample_rate": 192000}
  ]
}
```

### `POST /validate-playback`

Request:

```json
{
  "file": "jamming_25khz.wav",
  "device_id": 3,
  "sample_rate": 192000,
  "channels": 1,
  "gain": 0.8
}
```

Success:

```json
{
  "ok": true,
  "file_exists": true,
  "device_exists": true,
  "output_settings_supported": true,
  "source_sample_rate": 192000,
  "requested_sample_rate": 192000,
  "will_resample": false,
  "duration_s": 10.0,
  "channels": 1
}
```

Failure:

```json
{
  "ok": false,
  "error_code": "UNSUPPORTED_SAMPLE_RATE",
  "message": "The selected output device does not support 192000 Hz with 1 channel.",
  "suggestion": "Try 96000 Hz or check macOS Audio MIDI Setup."
}
```

### `POST /play`

Request:

```json
{
  "file": "jamming_25khz.wav",
  "device_id": 3,
  "sample_rate": 192000,
  "channels": 1,
  "gain": 0.8,
  "delay_ms": 500
}
```

Response:

```json
{
  "ok": true,
  "play_id": "play_20260528_211512_001",
  "message": "Playback scheduled",
  "file": "jamming_25khz.wav",
  "device_id": 3,
  "sample_rate": 192000,
  "channels": 1,
  "gain": 0.8,
  "delay_ms": 500
}
```

### `POST /stop`

Requests playback stop.

### `GET /status`

Returns current playback state.

```json
{
  "ok": true,
  "playing": true,
  "current_play_id": "play_20260528_211512_001",
  "file": "jamming_25khz.wav",
  "device_id": 3,
  "sample_rate": 192000,
  "elapsed_s": 2.31,
  "duration_s": 10.0,
  "last_error": null
}
```

## 6. Playback validation

Before playing, validate:

- file exists under `wav_root`
- file can be read
- device exists
- requested output channel count is valid
- requested sample rate can open an output stream
- gain is finite and within safe range, e.g. `0.0 <= gain <= 1.0` by default
- resampling is possible if required

## 7. Device behavior

- Must not change the macOS system default output.
- Must open an output stream with explicit `device_id`.
- This allows experiment sound to go to a USB DAC/ultrasonic speaker while normal Mac audio remains on the default output.

## 8. Linux Play & Record safety

When Linux Console starts Mac playback and then fails to start the paired Linux
recording because the recorder is busy, the raw `.bin` target already exists,
or DAQ is unavailable/not configured, it should send a best-effort Helper
`/stop` request. The run log should contain the successful play request, the
stop attempt, and the structured recording failure.

## 9. Error handling

Return structured errors:

```json
{
  "ok": false,
  "error_code": "FILE_NOT_FOUND",
  "message": "The requested WAV file was not found under wav_root.",
  "suggestion": "Refresh file list or copy the WAV into wav_root."
}
```

## 10. Physical output verification

Software playback success does not fully prove the physical speaker emitted sound. Optional later verification:

1. Mac Helper plays a sync chirp/test tone.
2. Linux DAQ records a short window.
3. Linux analysis detects marker frequency/chirp.
4. UI shows `Physical Audio Path: PASS/FAIL/UNKNOWN`.

This must remain optional and should not complicate v0.1/v0.2 core.

## 11. Linux metadata fields

When used, store:

```json
{
  "mac_helper": {
    "enabled": true,
    "connected": true,
    "helper_url": "http://100.x.y.z:5050",
    "hostname": "MacBook-Pro",
    "health_ok": true,
    "file": "jamming_25khz.wav",
    "device_id": 3,
    "device_name": "USB Audio Device",
    "requested_sample_rate": 192000,
    "actual_playback_sample_rate": 192000,
    "channels": 1,
    "gain": 0.8,
    "delay_ms": 500,
    "validate_playback_ok": true,
    "play_request_ok": true,
    "play_id": "play_20260528_211512_001",
    "last_error": null
  }
}
```

If disconnected:

```json
{
  "mac_helper": {
    "enabled": false,
    "connected": false,
    "health_ok": false,
    "last_error": "Mac Helper not configured"
  }
}
```
