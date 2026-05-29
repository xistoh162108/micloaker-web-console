# MiCloaker Web Console

This repository contains **MiCloaker Lab Console**, a local Linux web app for acoustic/DAQ experiments, plus an optional macOS Audio Helper for Mac-side WAV playback control.

이 저장소는 음향/DAQ 실험용 **MiCloaker Lab Console**과, Mac에서 WAV 재생을 제어하기 위한 선택적 macOS Audio Helper를 포함합니다.

## Start Here

Main user manual:

- [MiCloaker Lab Console Manual](micloaker_lab_console/README.md)

Mac Helper manual:

- [macOS Audio Helper Manual](micloaker_lab_console/mac_helper/README.md)

Requirements and design docs:

- [Project docs](docs/)
- [Operator UI and deployment requirements](docs/OPERATOR_UI_DEPLOYMENT_REQUIREMENTS.md)
- [Docs alignment report](micloaker_lab_console/docs_alignment_report.md)
- [Completion audit](docs/COMPLETION_AUDIT.md)

## Recommended Lab Setup

```text
Mac playback computer
  - Apple Silicon Mac recommended for high-rate playback workflows.
  - External DAC/audio interface and transducer are required for reliable ultrasonic output.
  - Runs optional mac_helper over Tailscale.

Linux recording computer
  - Runs the web console.
  - Records DAQ/microphone voltage data.
  - Stores raw .bin, WAV previews, metrics, plots, logs, reports, and exports.

Tailscale
  - Connects Mac and Linux by 100.x.y.z addresses when direct browser/helper access is needed.
```

## Operator Console Model

The Linux Dashboard is the primary one-screen command center. Routine experiment operation should not require moving through hidden dashboard tabs:

- Setup: session, DAQ/mock status, and optional Mac Helper state.
- Capture And Live Preview: quick run metadata, mock/DAQ live preview, mock/DAQ capture buttons, waveform, RMS/peak, clipping, PSD, spectrogram, and finalization status.
- Results, Compare, Export: latest run, latest comparison, latest finalized plots/audio/metrics, and ZIP exports.
- Recent Runs and Operations: fast run access, readiness checks, logs, and safe stop controls.
- Hardware Validation Records: operator-entered DAQ/Mac/play-and-record/attenuation evidence saved under `workspace/.micloaker/`.

The Dashboard layout is intentionally prioritized over decorative UI: the live monitor and capture controls stay in the main flow, controls wrap instead of overlapping, and detailed live/log pages remain secondary while the experiment is running.
Live charts render through `requestAnimationFrame`, fixed-size canvas surfaces, and bounded preview payloads. Finalized plot images use lazy async decoding, and report SVGs are simplified/rasterized where appropriate so large recordings remain practical to inspect in the browser.

## Quick Linux Console Setup

```bash
cd micloaker_lab_console
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Safe localhost mode:

```bash
.venv/bin/python scripts/console_control.py start
.venv/bin/python scripts/console_control.py status
.venv/bin/python scripts/console_control.py restart
.venv/bin/python scripts/console_control.py stop
```

Trusted Tailscale mode:

```bash
.venv/bin/python scripts/console_control.py start --tailscale --allow-web-shutdown
.venv/bin/python scripts/console_control.py restart --tailscale --allow-web-shutdown
```

Example URL:

```text
http://100.88.179.43:8000
```

The default bind remains `127.0.0.1`; direct Tailscale access works only when the server is explicitly started with `--tailscale`.

## Quick Mac Helper Setup

```bash
cd micloaker_lab_console/mac_helper
python3 -m venv .venv
source .venv/bin/activate
pip install -r ../requirements-mac-helper.txt
cp config.example.json config.json
python3 helper_control.py start
```

Edit `config.json` so `wav_root` points to the prepared WAV folder. Finder launchers are also available:

- `Start MiCloaker Helper.command`
- `Status MiCloaker Helper.command`
- `Stop MiCloaker Helper.command`

## Data and Safety Rules

- No database is used.
- Persistent state is plain files under `workspace/`.
- Raw float64 `.bin` is the primary quantitative data source.
- Peak WAV is listening-preview only.
- Range WAV is cross-check only when full-scale voltage is known.
- Final report metrics are recomputed from saved `.bin`.
- Mac Helper is optional and must not break Linux-only workflows.
- Mac Helper uses explicit `device_id` playback and does not change the macOS system default output device.

## Verification

```bash
cd micloaker_lab_console
.venv/bin/pytest -q
.venv/bin/python scripts/acceptance_audit.py
.venv/bin/python scripts/lab_readiness_check.py --check-server --server-url http://100.88.179.43:8000
```

Hardware verification still requires a real DAQ and a real Mac output device/DAC/transducer.
