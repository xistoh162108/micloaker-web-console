# MiCloaker macOS Audio Helper

MiCloaker macOS Audio Helper is an optional companion service for Mac-side experiment playback. The Linux console does not require it, but it is useful when the Mac should play a prepared WAV through a chosen output device while Linux records DAQ data.

MiCloaker macOS Audio Helper는 Mac에서 준비된 WAV를 특정 출력 장치로 재생하기 위한 선택적 서비스입니다. Linux 콘솔은 Helper 없이도 동작하지만, Mac 재생과 Linux DAQ 기록을 함께 맞출 때 유용합니다.

## Recommended Mac Setup

- Apple Silicon MacBook Pro or M-series desktop Mac is the recommended lab baseline.
- macOS with Python 3.10 or newer.
- Tailscale installed and connected to the same Tailnet as the Linux recording computer.
- External DAC/audio interface that supports the required sample rate, commonly 48000, 96000, or 192000 Hz.
- Speaker/transducer suitable for the experiment bandwidth.
- Prepared WAV files stored under one configured `wav_root`, typically the `mac_helper/jamming_sound` folder.

Important:

- The Helper validates software playback settings. It does not prove physical ultrasonic output.
- Do not assume built-in Mac speakers can emit the required ultrasonic signal.
- For 192000 Hz output, verify the selected output device in macOS Audio MIDI Setup and with `/validate-playback`.

## Install

```bash
cd mac_helper
python3 -m venv .venv
source .venv/bin/activate
pip install -r ../requirements-mac-helper.txt
cp config.example.json config.json
```

Edit `config.json`:

```json
{
  "wav_root": "jamming_sound",
  "host": "0.0.0.0",
  "port": 5050,
  "default_sample_rate": 192000,
  "default_channels": 2,
  "default_gain": 1.0,
  "mock_audio": false,
  "optional_token": null
}
```

Set `wav_root` to the directory containing prepared WAV files. For the current MiCloaker setup, move the jamming WAV folder into `mac_helper/jamming_sound` with files such as `25khz_1hr.wav` and `32.8khz_1hr.wav`.

## Start, Status, Stop

Command line:

```bash
python helper.py --config config.json
python3 helper_control.py start
python3 helper_control.py status
python3 helper_control.py stop
```

Use `host: 0.0.0.0` only on a trusted Tailnet. If `optional_token` is set, every request must include `Authorization: Bearer <token>`; configure the same token in the Linux console.

Finder double-click launchers:

- `Start MiCloaker Helper.command`
- `Status MiCloaker Helper.command`
- `Stop MiCloaker Helper.command`

The Start launcher creates `.venv` and installs `../requirements-mac-helper.txt` if needed. For real playback, edit `config.json` first.

## Connect from Linux

1. Start Tailscale on Mac and Linux.
2. Start the Helper on Mac.
3. Find the Mac Tailscale IP, for example `100.x.y.z`.
4. On the Linux console, open `/mac-helper`.
5. Save Helper URL:

```text
http://100.x.y.z:5050
```

6. Run Health, Devices, Files.
7. Choose WAV file, device ID, sample rate, channels, gain, and delay. The Linux console rejects a run-level playback request when the selected jamming WAV does not match the run metadata frequency.
8. Run Validate Playback before Play or Play & Record.

## APIs

```text
GET  /health
GET  /devices
GET  /files
POST /validate-playback
POST /play
POST /stop
GET  /status
```

## Safety Contract

- Linux-only workflows do not require this Helper.
- The Helper lists and plays only `.wav` files under `wav_root`.
- Absolute paths and path traversal are rejected.
- Playback requests must use an explicit `device_id`.
- The Helper does not change the macOS system default output device.
- `/validate-playback` checks file readability, device existence, sample rate, channel count, gain, and delay before `/play`.
- If Mac playback starts but Linux recording fails before capture, the Linux console sends a best-effort Helper `/stop` request and logs the stop attempt with the structured recording failure.
- Mono WAVs may be mapped to multiple output channels only when the selected device supports them.
- Playback streams WAV data in blocks instead of loading the full file into memory. This is required for long jamming files such as 1-hour multi-GB WAVs.
- If source and requested sample rates differ, validation reports `will_resample: true`; playback resamples each streamed block before writing to the explicit output device.
- Errors return structured JSON with `ok`, `error_code`, `message`, and `suggestion`.

## Mock Mode

For UI testing without real audio hardware, set:

```json
"mock_audio": true
```

This exposes a deterministic mock output device. Do not use mock mode for physical playback validation.

## Troubleshooting

Linux cannot reach Helper:

- Confirm Helper is running with `python3 helper_control.py status`.
- Confirm Mac Tailscale is connected.
- Confirm URL uses the Mac Tailscale IP and port 5050.
- If `optional_token` is set, configure the same token in the Linux console.

Playback validation fails:

- Confirm the WAV path appears in `/files`.
- Confirm the output device appears in `/devices`.
- Confirm the requested sample rate is supported in macOS Audio MIDI Setup.
- Try a lower sample rate such as 96000 or 48000.
- Confirm gain is between 0.0 and 1.0.

Physical sound is not detected:

- Confirm the selected device is the external DAC/interface, not the Mac default output.
- Confirm speaker/transducer power and cabling.
- Record a short DAQ/mic check on Linux and inspect waveform/PSD.
