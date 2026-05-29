# AGENTS.md — MiCloaker Lab Console

## Mission

Build a stable local web console for MiCloaker acoustic experiments. The app must support recording, conversion, visualization, analysis, comparison, exports, logs, and optional Mac-side playback control. It is a temporary local lab tool, not a production service.

## Non-negotiable constraints

1. **Do not use any database.** No SQLite, PostgreSQL, TinyDB, DuckDB, or hidden DB-like dependency.
2. Store persistent state using plain text files only: JSON, JSONL, CSV, Markdown, and `.log`.
3. Default server bind: `127.0.0.1` only. The user connects through SSH tunneling.
4. The app must work without DAQ hardware using mock mode.
5. Import `uldaq` lazily inside DAQ-specific code only.
6. Never overwrite raw `.bin` files silently.
7. Raw `.bin` voltage data is the primary quantitative source.
8. Peak-normalized WAV is for listening/preview only, not final attenuation reporting.
9. Range WAV is a cross-check source only when full-scale voltage is known.
10. Final report-grade metrics must be recomputed from saved `.bin` after recording ends.
11. Persist all important state to the workspace filesystem. Do not rely only on memory.
12. All long-running jobs must have text logs, status, and traceback capture.
13. Mac Helper is optional and must never break Linux-only workflows.

## Stack preference

Use a structured Python project:

- FastAPI
- Jinja2 templates
- Vanilla JavaScript
- CSS in `static/css/app.css`
- WebSocket or efficient polling for v0.2 live monitoring if feasible
- NumPy/SciPy/Matplotlib for analysis and plots
- `wave` or `scipy.io.wavfile` for WAV output
- JSON/JSONL/CSV/Markdown/text logs for persistence

Avoid heavy frontend build systems. Do not require React/Vite/Webpack for MVP. Do not add a database.

## Required project layout

```text
micloaker_lab_console/
  app/
    main.py
    config.py
    models.py
    routes/
      dashboard.py
      sessions.py
      runs.py
      recording.py
      conversion.py
      analysis.py
      compare.py
      exports.py
      live.py
      logs.py
      mac_helper.py
    services/
      daq.py
      mock_daq.py
      recorder.py
      converter.py
      analyzer.py
      plotting.py
      metadata.py
      text_store.py
      export_zip.py
      jobs.py
      live_monitor.py
      mac_helper_client.py
      tailscale.py
    templates/
      base.html
      dashboard.html
      sessions.html
      session_detail.html
      run_detail.html
      compare.html
      live.html
      logs.html
      mac_helper.html
    static/
      css/app.css
      js/app.js
      js/live.js
      js/mac_helper.js
  mac_helper/
    helper.py
    config.example.json
    README.md
  tests/
  README.md
  requirements.txt
  requirements-mac-helper.txt
```

## Text-file storage rules

Use this structure:

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
```

Rules:

- Per-session and per-run JSON files are source of truth.
- JSONL files are append-only indexes/events and can be rebuilt by scanning JSON files.
- Use atomic writes for JSON: write temp file, then rename.
- Use append-only text logs for jobs and tracebacks.
- On startup, scan workspace and rebuild in-memory lists.
- Provide a rebuild-index function if JSONL is missing/stale.

## Required Linux Console features

### v0.1 stable core

- Session manager: create/list/open sessions.
- Run manager: each session contains multiple runs.
- Metadata forms: frequency, `uj0/uj1`, sound condition, mic, room, distance, angle, DAQ channel/range, sample rate, duration, scale modes, notes, safety fields.
- Recording: real DAQ if available, mock DAQ otherwise. One recording job at a time.
- Conversion: `.bin` to WAV, `peak`, `range`, `both`, scale mode in filename.
- File browser and audio preview.
- Plots: waveform, PSD, spectrogram, comparison PSD overlay, attenuation bar chart. Make plots clean and report-friendly.
- Analysis: RMS, Welch PSD, 300–3400 Hz band power, 20–3900 Hz band power, dominant tone ±50 Hz, clipping/DC/sample-count flags.
- Compare: choose or auto-pair `uj0`/`uj1`, compute attenuation dB, remaining fraction, reduction percent.
- Exports: individual files, run ZIP, session ZIP, multi-session ZIP.
- Logs: job status, log console, traceback viewer.

### v0.2 live/finalize

- Live Monitor Mode: waveform, RMS/peak, clipping, PSD, scrolling spectrogram.
- Live values are approximate and preview-only.
- After recording ends, run finalization from saved `.bin`; update metrics, plots, WAVs, and metadata.

## Optional macOS Audio Helper rules

1. Treat Mac Helper as optional. Never make Linux-only tests require it.
2. Manual URL connection is required; Tailscale auto-discovery is best-effort optional.
3. If Helper is disconnected, show a warning and keep all Linux features enabled.
4. Helper must not change the macOS system default output device.
5. Helper must use explicit `device_id` when opening playback streams.
6. Helper must play only files under configured `wav_root`; block path traversal.
7. Helper must validate playback before playing: file, device, sample rate, channels, WAV readability, resampling feasibility.
8. Helper APIs: `/health`, `/devices`, `/files`, `/validate-playback`, `/play`, `/stop`, `/status`.
9. Store Helper connection/playback details in run JSON/log files.
10. Return structured errors with `error_code`, `message`, and `suggestion`.
11. Physical audio output detection is optional and should be implemented only as a separate validation feature.

## Testing requirements

Tests must pass without DAQ and without Mac Helper.

Include tests for:

- filename generation
- JSON/JSONL metadata save/reload
- workspace scan and index rebuild
- atomic JSON write
- bin→wav conversion with peak/range naming
- analysis on synthetic `.bin`
- uj0/uj1 attenuation calculation
- ZIP export contents
- job log/traceback capture
- Mac Helper client disconnected behavior
- Mac Helper API validation using mock/test client, if implemented

## Coding style

- Prefer simple, explicit functions.
- Avoid clever abstractions.
- Keep services testable without web routes.
- Add docstrings for experiment-critical functions.
- Validate file paths carefully.
- Use deterministic mock data in tests.
- Log important events with timestamps.

## Acceptance priority

Codex should complete stable v0.1 core first, then v0.2 live/finalize, then Mac Helper integration. If time is limited, prioritize reliability over feature count.
