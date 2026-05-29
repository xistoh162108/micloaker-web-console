# Stability and Simplicity Rules

## 1. Core principle

The Linux Console must remain useful even if every optional feature is unavailable. The most important operations are:

```text
open app → record/upload data → save .bin → convert WAV → analyze → export → inspect logs
```

These must not depend on Mac Helper, Tailscale, WebSocket, real DAQ, or advanced live monitoring.

## 2. No-database rule

Do not use a database. Persistent state must be ordinary files:

```text
JSON     session/run/config/metrics metadata
JSONL    append-only event/index/job history
CSV      result tables and summaries
Markdown generated reports
.log     logs and tracebacks
```

The system should be recoverable by scanning the workspace folders.

## 3. Complexity budget

### Allowed in v0.1

- FastAPI routing
- Jinja2 templates
- Vanilla JS
- JSON/JSONL/CSV/Markdown/text logs
- Background jobs with thread + queue or simple worker abstraction
- Mock DAQ
- Matplotlib static plots
- ZIP exports
- Manual Mac Helper URL connection if simple

### Avoid in v0.1

- React/Vite/Webpack
- Celery/Redis
- Any database
- Kubernetes/Docker-only assumptions
- User accounts/auth systems
- Complex service discovery
- Continuous background daemon design
- Bidirectional hard synchronization between Mac and Linux
- Multiple concurrent DAQ readers

### Allowed in v0.2

- WebSocket or efficient polling for live monitor
- Shared acquisition loop for recording + live preview
- Post-record finalization job
- Optional Mac Helper playback client

## 4. Graceful degradation matrix

| Missing component | Required behavior |
|---|---|
| DAQ missing | mock mode and file upload still work |
| `uldaq` missing | app starts; DAQ page shows unavailable |
| Mac Helper disconnected | Linux record/analyze/export works |
| Tailscale missing | manual Helper URL still works |
| WebSocket unsupported | use polling or disable live monitor only |
| SciPy missing | show dependency error; app still opens if possible |
| Plot generation fails | metrics still save; log traceback |

## 5. Job reliability

- One recording job at a time.
- Conversion/analysis/export jobs may queue but should be simple.
- Every job has: `job_id`, `type`, `status`, `created_at`, `started_at`, `finished_at`, `logs`, `error`, `traceback`.
- Write job events to `.micloaker/jobs.jsonl`.
- Write human-readable logs to `.micloaker/app.log` and run-specific `.log` files.
- On app shutdown or restart, unfinished jobs should be marked `interrupted` or `unknown` on the next startup scan.
- Do not silently delete or overwrite output files.

## 6. File safety

- Sanitize file paths.
- User-facing file serving must be limited to workspace.
- Mac Helper must serve/play only under `wav_root`.
- ZIP export should preserve relative paths and avoid absolute paths.

## 7. Metadata safety

Every run must be interpretable later. Always store:

- experiment condition
- DAQ settings
- actual sample rate and sample count
- conversion scale modes
- analysis parameters
- quality flags
- Mac Helper status, if any
- logs and errors

## 8. Implementation ordering

1. Stable text-file storage layer.
2. Mock-data workflow.
3. Bin/wav/analysis/export.
4. Real DAQ integration.
5. Live monitor.
6. Mac Helper.

Do not implement Mac Helper before the Linux core passes tests.
