# Requirements

## A. Linux Console requirements

### A1. Runtime

- Runs on Linux.
- Default host: `127.0.0.1`.
- User accesses through SSH tunnel.
- Service is temporary and can be stopped with Ctrl+C.
- Restart must reload existing sessions/runs from workspace text files.
- No database is allowed.

### A2. Workspace

Default structure:

```text
workspace/
  sessions/
    <session_id>/
      session.json
      runs.jsonl
      events.jsonl
      bin/
      wav/
      plots/
      results/
      metadata/
        <run_id>.json
      logs/
        <run_id>.log
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
```

### A3. Text-file persistence

- Session metadata: JSON.
- Run metadata: JSON.
- Session/run indexes: JSONL.
- Job history: JSONL.
- Logs: text `.log`.
- Metrics and comparison results: JSON and CSV.
- Reports: Markdown.
- JSONL indexes are append-only and can be rebuilt by scanning JSON files.
- JSON writes should be atomic: write temp file, then rename.

### A4. Sessions and runs

- Create/list/open sessions.
- Each run belongs to a session.
- Record condition metadata for every run.
- Store session-level and run-level JSON.
- Provide table filters: date, frequency, uj0/uj1, sound, mic, room, analysis status.

### A5. Recording

- Real DAQ mode if hardware/dependencies exist.
- Offline developer validation mode for tests/demo.
- Only one recording job at a time.
- Store raw `.bin` as float64 voltage.
- Never overwrite `.bin` silently.
- Capture requested and actual sample rate, duration, sample count, DAQ range, channel, input mode.

### A6. Conversion

- Convert `.bin` to WAV.
- Support scale modes: `peak`, `range`, `both`.
- Peak WAV filename: `__scale-peak.wav`.
- Range WAV filename: `__scale-range-fs10V.wav` or corresponding voltage.
- Peak WAV marked as listening-only.
- Range WAV marked as cross-check if full-scale voltage known.

### A7. Analysis

- Final metrics must be computed from saved `.bin` by default.
- Compute full RMS, band RMS/power, Welch PSD, 300–3400 Hz band power, 20–3900 Hz band power, dominant tone ±50 Hz, clipping flags, DC offset, sample count mismatch.
- Generate waveform, PSD, spectrogram, comparison overlay, attenuation bar plot.
- Save JSON/CSV metrics.

### A8. Compare

- Allow manual `uj0`/`uj1` selection.
- Auto-pair only when metadata matches enough; warn on mismatches.
- Compute attenuation dB, remaining fraction, reduction percent.
- Save compare JSON/CSV/plots.

### A9. Exports

- Download individual files.
- Export a run ZIP.
- Export a session ZIP.
- Export multiple sessions ZIP.
- Include metadata, logs, metrics, plots, bin/wav files, and optional report markdown.

### A10. UI and logs

- Dashboard command center with always-visible Setup, Capture/Live Preview, Results/Compare/Export, Recent Runs, and Operations areas.
- Core dashboard experiment controls must not be hidden behind tabs.
- Quick capture controls on the Dashboard plus a detailed run form for advanced metadata.
- Session detail and run detail pages.
- Compare page.
- Live Monitor page.
- Mac Helper page/panel.
- Debug/log console with timestamps and traceback viewer.

## B. v0.2 Live Monitor requirements

- Show live waveform.
- Show live RMS/peak and clipping warning.
- Show live PSD.
- Show scrolling spectrogram.
- Use offline developer live source if no DAQ.
- Live values are preview-only.
- After recording ends, run finalization from saved `.bin` and update UI.

## C. Optional macOS Audio Helper requirements

### C1. Design

- Separate optional companion service on macOS.
- Runs only during experiments.
- Linux Console can register it by manual URL.
- Tailscale auto-discovery is optional best-effort.
- Helper disconnected must not affect Linux-only features.

### C2. Helper APIs

- `GET /health`
- `GET /devices`
- `GET /files`
- `POST /validate-playback`
- `POST /play`
- `POST /stop`
- `GET /status`

### C3. Playback rules

- Play only files under configured `wav_root`.
- Reject path traversal.
- Do not change macOS system default output device.
- Open playback stream using explicit `device_id`.
- Validate file, device, sample rate, channels, WAV readability before playback.
- Return structured errors.
- Store playback information in Linux run JSON/log files.

### C4. Linux integration

- Manual Helper URL input.
- Connect/health check button.
- Refresh devices/files.
- Output device dropdown.
- WAV file dropdown.
- Sample rate selector: 48000, 96000, 192000, custom.
- Channels selector.
- Gain slider.
- Validate Playback.
- Play / Stop.
- Optional Play & Record.

## D. Non-functional requirements

- Stability over feature count.
- No heavy frontend framework.
- No database.
- No hidden background daemon assumptions.
- Tests must pass without DAQ and without Mac Helper.
- Clear error messages and suggestions.
- Graceful degradation when optional dependencies are missing.
