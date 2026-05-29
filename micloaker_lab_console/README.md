# MiCloaker Lab Console

MiCloaker Lab Console is a temporary local web console for acoustic/DAQ experiments. It runs on the Linux recording computer, stores all experiment state as plain files, and can optionally control a separate macOS playback helper over Tailscale.

MiCloaker Lab Console은 음향/DAQ 실험용 임시 로컬 웹 콘솔입니다. Linux 기록 컴퓨터에서 실행하고, 모든 실험 상태를 일반 파일로 저장하며, 필요하면 Tailscale을 통해 별도 macOS 재생 Helper를 제어합니다.

The UI standard is DaisyUI component vocabulary implemented locally in vanilla CSS, so the app keeps the no-build-step FastAPI/Jinja2 deployment model while using consistent `btn`, `card`, `stats`, `badge`, form, and table patterns. Core experiment operation is not hidden behind dashboard tabs.

## What This App Does

- Create experiment sessions and runs.
- Record raw float64 voltage `.bin` data from mock mode or DAQ.
- Import existing raw `.bin` recordings.
- Convert `.bin` to listening-preview peak WAV and range cross-check WAV.
- Generate waveform, PSD, spectrogram, PSD overlay, and attenuation plots.
- Finalize report-grade RMS, Welch PSD, band power, dominant-tone, and quality metrics from saved `.bin`.
- Compare `uj0` and `uj1` runs and export JSON/CSV/PNG/SVG/ZIP artifacts.
- Show logs, tracebacks, live preview, and optional Mac Helper playback status.
- Run mock live preview by default, with an explicit DAQ live preview sanity-check mode when DAQ hardware is available.

## Operator Console

The Dashboard is the primary experiment console. It is organized by operating priority instead of by disconnected feature tabs:

1. Setup: active session, acquisition mode, and optional Mac playback state.
2. Capture And Live Preview: quick metadata, mock/DAQ live preview, mock/DAQ record buttons, waveform, RMS/peak, clipping, live PSD, spectrogram, and finalization status.
3. Results, Compare, Export: latest run, latest comparison, latest finalized visual artifacts, audio preview, metrics link, and export shortcuts.
4. Recent Runs and Operations: fast run access, readiness, and safe shutdown/status links.

Use the detailed pages when you need advanced metadata, file browsing, full logs, or per-run playback details. During an experiment, the Dashboard should remain usable as the one-screen command center.

The Dashboard favors stable operator controls over visual decoration: capture buttons and fields wrap cleanly, live waveform/finalization status remain in the main flow, and logs stay available without taking over the primary experiment view.

## System Layout

Recommended lab layout:

```text
Mac playback computer
  - Plays prepared ultrasonic or acoustic WAV files.
  - Runs optional mac_helper service.
  - Sends audio to an explicit device_id, usually an external DAC/audio interface.

Linux recording computer
  - Runs MiCloaker Lab Console.
  - Records microphone/DAQ voltage data.
  - Stores raw .bin, metrics, plots, logs, reports, and ZIP exports.

Tailscale network
  - Lets the Mac and Linux computers reach each other by 100.x.y.z addresses.
```

권장 실험 구조:

```text
Mac 재생 컴퓨터
  - 준비된 초음파/음향 WAV를 재생합니다.
  - 선택적으로 mac_helper 서비스를 실행합니다.
  - macOS 기본 출력 장치를 바꾸지 않고, 명시적인 device_id로 외부 DAC/오디오 인터페이스에 출력합니다.

Linux 기록 컴퓨터
  - MiCloaker Lab Console을 실행합니다.
  - 마이크/DAQ 전압 데이터를 기록합니다.
  - raw .bin, metrics, plots, logs, reports, ZIP export를 저장합니다.

Tailscale 네트워크
  - Mac과 Linux가 100.x.y.z 주소로 서로 접근하게 합니다.
```

## Hardware and OS Requirements

Linux recording side:

- Linux machine with Python 3.10 or newer.
- DAQ supported by `uldaq` for real recording. Mock mode works without DAQ.
- Sufficient disk space for raw `.bin` files and plot/export artifacts.
- Tailscale if direct browser access or Mac Helper control is needed.

Mac playback side:

- Recommended lab baseline: Apple Silicon MacBook Pro or Mac mini/studio-class M-series Mac.
- macOS with Python 3.10 or newer.
- Tailscale for Helper access from Linux.
- External DAC/audio interface and speaker/transducer that explicitly support the experiment sample rate and output bandwidth.
- For 192000 Hz playback, verify the selected output device supports 192000 Hz in macOS Audio MIDI Setup and in `/validate-playback`.

Important audio note:

Do not assume the Mac built-in speaker, headphone output, or any random USB device can produce useful ultrasonic output. The Helper can validate file/device/sample-rate/channel settings, but physical acoustic output still needs lab validation with the DAQ/microphone path.

중요:

Mac 내장 스피커나 일반 출력 장치가 초음파를 제대로 낸다고 가정하지 마세요. 192 kHz 같은 높은 sample rate는 선택한 외부 DAC/오디오 인터페이스가 지원해야 하며, Helper의 `/validate-playback`과 실제 DAQ/마이크 검증으로 확인해야 합니다.

## Install on Linux

```bash
cd micloaker_lab_console
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Direct localhost run command, equivalent to the control script's default local mode:

```bash
MICLOAKER_WORKSPACE=workspace uvicorn app.main:app --host 127.0.0.1 --port 8000
```

No database is required or used. Persistent state is stored under `workspace/` as JSON, JSONL, CSV, Markdown, `.log`, `.bin`, WAV, PNG, and SVG files.

## Start and Stop on Linux

Use the control script for normal lab operation. It creates:

- `workspace/.micloaker/console.pid`
- `workspace/.micloaker/console_server.log`

### Safe localhost mode

Use this when you will connect by SSH port forwarding:

```bash
.venv/bin/python scripts/console_control.py start
.venv/bin/python scripts/console_control.py status
.venv/bin/python scripts/console_control.py stop
```

Then tunnel from your laptop:

```bash
ssh -L 8000:127.0.0.1:8000 user@linux-host
```

Open:

```text
http://127.0.0.1:8000
```

### Tailscale direct mode

Use this only on a trusted Tailnet:

```bash
.venv/bin/python scripts/console_control.py start --tailscale --allow-web-shutdown
```

This binds to the Linux `tailscale0` IPv4 address. Example:

```text
http://100.88.179.43:8000
```

If you cannot open the UI from another device, check:

```bash
ss -ltnp | grep 8000
ip -br addr show tailscale0
.venv/bin/python scripts/console_control.py status --tailscale
```

If the server is listening on `127.0.0.1:8000`, Tailscale direct access will not work. Restart with `--tailscale`.

### Linux desktop launchers

Install Start/Stop/Status launchers on `~/Desktop`:

```bash
.venv/bin/python scripts/install_linux_desktop_launcher.py
```

The launchers use the same safe control script. The Start launcher uses Tailscale mode.

Stop a foreground console with `Ctrl+C`. On restart, the app rebuilds session/run lists from workspace text files.

### Ops page

Open `/ops` in the web UI to see:

- bind address
- workspace
- recording state
- whether web shutdown is enabled
- Lab Readiness checks for bind mode, workspace text files, recording lock, DAQ backend, Mac Helper, and web shutdown
- Hardware Validation Records for physical DAQ, Mac playback, play-and-record, attenuation-pair, and legacy-parity evidence

The Stop Console button is only enabled when the process was started with `--allow-web-shutdown`. It refuses shutdown while recording is active.

`/ops/readiness` returns the same readiness summary as JSON for quick checks from another Tailnet device.

Hardware validation records are saved as text files:

```text
workspace/.micloaker/hardware_validation.jsonl
workspace/.micloaker/hardware_validation_report.md
workspace/.micloaker/lab_readiness_report.json
workspace/.micloaker/lab_readiness_report.md
```

Session ZIP and multi-session ZIP exports include these files under `ops_validation/` when validation/readiness records exist.
The `/ops` page also provides direct JSONL/Markdown downloads for validation records and point-in-time readiness snapshots.
Readiness treats the latest record for each validation gate as the active state: any `fail` gate makes readiness fail, any `warn` or missing gate keeps readiness in warning state, and each gate must be `pass` or explicitly marked `not applicable` before the hardware validation section is green.
The same gate status logic is used by `scripts/lab_readiness_check.py`; a failed validation gate makes the CLI exit non-zero. Add `--write-report` to save the readiness JSON/Markdown snapshot for the lab notebook or exported session package.

## Live Monitor

Live Monitor is a setup and sanity-check view. Live preview is approximate, preview-only, and not report-grade. Final report values are recomputed from saved `.bin` after recording/finalization.

## Install and Run the Mac Helper

On the Mac:

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
  "wav_root": "/Users/user/MicloakerSounds",
  "host": "0.0.0.0",
  "port": 5050,
  "default_sample_rate": 192000,
  "default_channels": 1,
  "default_gain": 1.0,
  "mock_audio": false,
  "optional_token": null
}
```

Start/stop from Terminal:

```bash
python3 helper_control.py start
python3 helper_control.py status
python3 helper_control.py stop
```

Or double-click in Finder:

- `Start MiCloaker Helper.command`
- `Status MiCloaker Helper.command`
- `Stop MiCloaker Helper.command`

The Helper APIs are:

```text
/health
/devices
/files
/validate-playback
/play
/stop
/status
```

The Helper lists and plays only WAV files under `wav_root`, rejects path traversal, and uses explicit `device_id` playback. It does not change the macOS system default output device.

## Connect Linux Console to Mac Helper

1. Start Tailscale on both Mac and Linux.
2. On the Mac, start Helper.
3. Find the Mac Tailscale IP, for example `100.x.y.z`.
4. In the Linux web console, open `/mac-helper`.
5. Enter:

```text
http://100.x.y.z:5050
```

6. Save and run Health, Devices, Files.
7. Select WAV file, device ID, sample rate, channels, and gain.
8. Run Validate Playback before Play or Play & Record.

Mac Helper is optional. If it is disconnected, Linux-only recording, import, analysis, compare, export, and logs still work.

## Main Experiment Flow

Typical full experiment:

1. Start Linux console.
2. Start Mac Helper if Mac playback control is needed.
3. Open Dashboard and confirm DAQ, Helper, and recording status.
4. Create a session.
5. Create a run with metadata:
   - carrier frequency
   - `uj0` or `uj1`
   - sound condition
   - mic, room, distance, angle
   - DAQ channel/range/sample rate/duration
   - scale mode and full-scale voltage
   - notes and safety fields
6. For Mac playback, validate the WAV/device/sample-rate settings.
7. Record mock, record DAQ, upload `.bin`, or use Play & Record.
8. After recording, finalization reloads the saved `.bin` and recomputes report-grade metrics.
9. Preview WAVs and plots on the run page.
10. Repeat for matching `uj0` and `uj1` runs.
11. Use Compare to compute attenuation.
12. Export run ZIP, session ZIP, or multi-session ZIP.
13. Inspect `/logs` for job status, tracebacks, and app events.
14. Stop the console after the experiment.

실험 순서 요약:

1. Linux 콘솔을 켭니다.
2. Mac 재생 제어가 필요하면 Mac Helper를 켭니다.
3. Dashboard에서 DAQ/Helper/Recording 상태를 확인합니다.
4. Session을 만듭니다.
5. Run metadata를 입력합니다.
6. Mac playback을 쓸 경우 WAV/device/sample-rate를 Validate 합니다.
7. Mock/DAQ/upload/Play & Record 중 하나로 기록합니다.
8. 기록 후 saved `.bin`에서 report-grade metrics가 재계산됩니다.
9. Run page에서 WAV/plot/metrics/log를 확인합니다.
10. `uj0`/`uj1` pair를 만든 뒤 Compare 합니다.
11. ZIP으로 export합니다.
12. 실험 종료 후 console을 끕니다.

## Data Rules

- Raw `.bin` float64 voltage data is the primary quantitative source.
- Final report metrics are recomputed from saved `.bin` after recording ends.
- Peak-normalized WAV is listening preview only.
- Range WAV is a cross-check source only when full-scale voltage is known.
- Peak WAV names include `__scale-peak.wav`.
- Range WAV names include `__scale-range-fs10V.wav` or the configured full-scale value.
- Raw `.bin` files are never silently overwritten.
- Long-running jobs write text logs and capture tracebacks.

## Verification

Run automated checks:

```bash
.venv/bin/pytest -q
.venv/bin/python scripts/acceptance_audit.py
.venv/bin/python scripts/lab_readiness_check.py --check-server --server-url http://100.88.179.43:8000
```

The readiness check reports:

- bind mode
- no-database checks
- workspace structure
- DAQ availability
- Mac Helper config
- server route health
- `/ops/readiness` route health
- lab-only verification reminders

See [docs_alignment_report.md](docs_alignment_report.md) for the implementation-to-docs alignment map and [../docs/COMPLETION_AUDIT.md](../docs/COMPLETION_AUDIT.md) for the requirement-by-requirement evidence map and remaining lab verification items.

Before using real hardware for report-grade experiments, follow the lab protocol in [../docs/HARDWARE_VALIDATION_PROTOCOL.md](../docs/HARDWARE_VALIDATION_PROTOCOL.md). It covers DAQ smoke capture, Mac Helper playback validation, short play-and-record trials, and attenuation pair checks.

## Troubleshooting

Tailscale URL does not open:

- Confirm server was started with `--tailscale`.
- Confirm `ss -ltnp` shows `100.x.y.z:8000`, not only `127.0.0.1:8000`.
- Confirm both devices are on the same Tailnet.
- Try `curl http://100.x.y.z:8000/daq/health` from another Tailnet device.

DAQ unavailable:

- Mock mode still works.
- Install/configure `uldaq` and DAQ drivers.
- Use `/daq/health` to inspect backend state.

Mac Helper cannot play:

- Confirm `wav_root` exists and contains WAV files.
- Open `/devices` and choose an output device ID.
- Validate playback before playing.
- Check macOS Audio MIDI Setup for sample-rate support.
- Confirm the external DAC/speaker/transducer is physically connected.

## Storage Layout

```text
workspace/
  sessions/<session_id>/
    session.json
    runs.jsonl
    events.jsonl
    bin/
    wav/
    plots/
    results/
    metadata/<run_id>.json
    logs/<run_id>.log
    comparisons/
    summary.csv
    session_report.md
  uploads/
  .micloaker/
    config.json
    sessions.jsonl
    jobs.jsonl
    app_events.jsonl
    app.log
    console.pid
    console_server.log
```

No SQLite, PostgreSQL, DuckDB, TinyDB, or hidden database dependency is used.
