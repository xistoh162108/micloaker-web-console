# Architecture

## 1. Overview

There are two services:

1. **Linux Console**: required. Manages DAQ/mic recording, files, analysis, exports, logs.
2. **macOS Audio Helper**: optional. Plays prepared WAV files on a specified Mac output device.

The Linux Console must be independently useful and must not use a database.

```text
Mac browser via SSH tunnel
        |
        v
Linux Console on 127.0.0.1
  ├── DAQ/mic recording
  ├── text-file metadata/logs
  ├── .bin/.wav/plots/results
  ├── live monitor
  ├── exports/logs
  └── optional HTTP client → Mac Helper over Tailscale
                             └── Mac output device playback
```

## 2. Linux Console modules

```text
app/main.py              FastAPI app setup
app/config.py            workspace/config loading
app/models.py            dataclasses/pydantic models
app/routes/*             web/API routes
app/services/daq.py      lazy uldaq DAQ functions
app/services/mock_daq.py deterministic mock input
app/services/recorder.py recording orchestration
app/services/converter.py bin→wav conversion
app/services/analyzer.py metrics and PSD
app/services/plotting.py report plots
app/services/metadata.py metadata helpers
app/services/text_store.py JSON/JSONL/CSV/log storage
app/services/jobs.py     job manager and logs
app/services/export_zip.py ZIP exports
app/services/live_monitor.py live preview buffers
app/services/mac_helper_client.py optional Mac Helper HTTP client
app/services/tailscale.py optional best-effort peer discovery
```

## 3. macOS Helper modules

```text
mac_helper/helper.py          FastAPI helper app
mac_helper/config.example.json
mac_helper/README.md
```

It should be small and independent. The Linux tests should not require it to run.

## 4. Data flow

### Recording flow

```text
Run form
→ create run JSON metadata
→ append run_created event to JSONL
→ recording job starts
→ DAQ/mock chunks saved to .bin
→ optional live preview from chunk buffer
→ recording finishes
→ finalization job reads saved .bin
→ conversion/metrics/plots generated
→ JSON metadata updated atomically
→ JSONL events appended
```

### Finalization flow

```text
saved .bin
→ load float64 voltage
→ remove DC
→ trim transient if configured
→ quality checks
→ RMS/PSD/band power/dominant tone
→ peak/range WAV generation
→ waveform/PSD/spectrogram plots
→ metrics JSON/CSV
```

### Mac Helper flow

```text
User enters Helper URL
→ Linux calls /health
→ Linux calls /devices and /files
→ user selects device/file/sample rate/gain
→ /validate-playback
→ optional /play
→ optional Linux recording starts with delay
→ run JSON/log stores playback details
```

## 5. Text-file state model

Use ordinary files only:

- `session.json` is source of truth for session metadata.
- `metadata/<run_id>.json` is source of truth for run metadata.
- `runs.jsonl`, `sessions.jsonl`, `jobs.jsonl`, and `events.jsonl` are append-only indexes/events.
- JSONL indexes can be rebuilt by scanning JSON files.
- `summary.csv` is a generated summary, not the source of truth.
- Logs are append-only `.log` files.

On startup, scan workspace files to rebuild in-memory state.

## 6. Live Monitor architecture

Use one acquisition source where possible.

```text
DAQ Reader
  ├── .bin writer
  ├── live preview buffer
  └── quick metrics
```

Never create two competing readers for the same DAQ during a recording. The console may offer an explicit DAQ live preview setup mode that performs short lazy-`uldaq` scans before recording; if DAQ preview is unavailable it must report a preview error and leave mock/live page operation intact.

## 7. Security posture

- Linux Console binds to `127.0.0.1` by default.
- Mac Helper may bind to `0.0.0.0` for Tailscale, but document that it should be used only on trusted Tailnet.
- Optional shared token may be supported through an environment variable or config, but do not make it complex.
