# PRD — MiCloaker Lab Console with Text-file Storage

## 1. Product summary

MiCloaker Lab Console is a local Linux web application for acoustic/DAQ experiments. It is started before an experiment, accessed from a browser through SSH tunneling, and stopped after the experiment. It manages sessions/runs, records raw `.bin` voltage files, converts WAV previews, computes audible jamming-induced noise metrics, compares `uj0`/`uj1`, visualizes signals, exports results, and preserves logs/metadata.

The system must not use a database. All persistent state is stored as plain text files: JSON, JSONL, CSV, Markdown, and `.log`.

An optional macOS Audio Helper can be run on the Mac used for experiment playback. The Linux Console can connect to it over Tailscale to list Mac output devices, list prepared WAV files, validate playback settings, and trigger playback without changing the Mac system default output.

## 2. Primary goals

1. Make the Linux-side experiment workflow reliable and repeatable.
2. Preserve raw data, metadata, logs, and final metrics for later review.
3. Reduce mistakes from manual filename changes, peak/range confusion, and missing conditions.
4. Provide report-friendly plots and exportable result packages.
5. Optionally control Mac playback when the Helper is running.
6. Keep all state inspectable and recoverable with ordinary files.

## 3. Non-goals

- Not a production, always-on web service.
- Not a multi-user platform.
- Not a heavy frontend SPA.
- Not a database-backed web app.
- Not required to automate Audacity.
- Not required to guarantee physical speaker output from Mac alone.
- Not required to make Mac Helper available for Linux-only workflow.

## 4. Users

- Main user: researcher operating Linux DAQ over SSH and Mac playback locally.
- Secondary users: supervisors/researchers reviewing ZIP exports, plots, CSVs, and logs.

## 5. Core workflow

```text
Start Linux Console
→ create/open session
→ configure run
→ optionally connect Mac Helper
→ optionally validate/play Mac WAV
→ record Linux DAQ/mic input
→ save raw .bin
→ generate peak/range WAVs
→ generate plots
→ finalize metrics from .bin
→ compare uj0/uj1
→ export run/session ZIP
→ stop service
```

## 6. Version scope

### v0.1 stable core

- Linux local web console.
- Sessions/runs using text files only.
- Recording with DAQ or mock DAQ.
- `.bin` raw data preservation.
- WAV conversion with scale mode in filename.
- Audio preview.
- Waveform/PSD/spectrogram plots.
- Energy metrics and `uj0/uj1` comparison.
- ZIP exports.
- Logs/debug UI.
- Optional Mac Helper panel basic manual connection may be included, but not required for Linux core success.

### v0.2 live and finalize

- Live Monitor Mode.
- Real-time waveform, RMS/peak, clipping warning, PSD, spectrogram.
- Preview-only labeling.
- Post-recording finalization from saved `.bin`.

### v0.2.x optional Mac Helper integration

- Mac Helper manual registration.
- Health/device/file/validate/play/stop/status APIs.
- Optional best-effort Tailscale discovery.
- Play & Record workflow with metadata logging.

## 7. Success criteria

The tool is successful if the user can run a full experiment session, recover exactly what was recorded, understand how WAVs were scaled, compare unjammed vs jammed conditions in dB, export the session as ZIP, and inspect logs when something fails. Mac Helper connection failure must not prevent this. All metadata and results must be readable as ordinary text files without a database.
