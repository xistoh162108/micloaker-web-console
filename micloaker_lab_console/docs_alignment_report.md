# MiCloaker Docs Alignment Report

Last checked: 2026-05-29

This report maps the current implementation to the project documents in `../docs` and the workflow references in `../docs/legacy`. It separates requirements proven by code/tests/runtime checks from requirements that need physical lab hardware or a real macOS audio device to verify end to end.

## Verification Commands

Run from `micloaker_lab_console/`:

```bash
.venv/bin/pytest -q
.venv/bin/python scripts/acceptance_audit.py
.venv/bin/python scripts/lab_readiness_check.py --check-server --server-url http://100.88.179.43:8000
for path in / /sessions /runs/new /compare /mac-helper /files /logs /daq/health /recording/status /live /live/snapshot; do
  code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:8000$path")
  printf '%s %s\n' "$code" "$path"
done
```

Most recent observed results:

- Full test suite: `133 passed`
- Acceptance audit: `PASS`
- Smoke routes: all listed routes returned `200`

## Alignment Matrix

| Area | Status | Evidence |
|---|---|---|
| Structured project layout | Proven | Required files exist under `app/`, `mac_helper/`, `tests/`; acceptance audit checks layout. |
| FastAPI + Jinja2 + vanilla JS/CSS | Proven | `app/main.py`, `app/templates/`, `app/static/js/`, `app/static/css/app.css`; no frontend build config. |
| No database | Proven | Requirements exclude database packages; audit scans for `.db`, `.sqlite`, `.duckdb` files and forbidden DB dependencies. |
| Default bind `127.0.0.1` | Proven | `app/config.py` default host and README run command; tested module entry point host. |
| Temporary local service workflow | Proven | README documents start, SSH tunnel, browser URL, and `Ctrl+C` stop/restart behavior. |
| Text-file persistence | Proven | JSON/JSONL/CSV/Markdown/log helpers in `app/services/text_store.py`; workspace startup and rebuild tests. |
| Atomic JSON writes | Proven | `atomic_write_json` tests cover temp-write and replace behavior. |
| Startup scan/index rebuild | Proven | `load_sessions`, `load_runs`, `rebuild_indexes`; tests cover stale/missing indexes and malformed JSON tolerance. |
| Session/run manager | Proven | Routes/templates for sessions and runs; tests cover create/list/detail and filters. |
| Metadata forms | Proven | New-run/session forms include acquisition, condition, analysis, safety, conversion, and Mac Helper planning fields; tests check field exposure and validation. |
| Mock DAQ mode | Proven | `app/services/mock_daq.py`; tests and acceptance audit record/finalize mock runs without hardware. |
| Lazy `uldaq` import | Proven | `app/services/daq.py` imports `uldaq` inside DAQ recording code; tests assert app startup and health checks do not import it. |
| Real DAQ code path | Partially proven | Lazy real scan path has unit coverage with fake `uldaq`; physical hardware capture must be verified in lab. |
| One recording at a time | Proven | Recorder lock and busy errors; tests cover busy behavior and structured response. |
| Never silently overwrite raw `.bin` | Proven | Recorder/finalization refuse existing raw bin unless creating a new run; tests cover conflict behavior. |
| Raw `.bin` as primary source | Proven | Finalization validates saved float64 `.bin`; compare source defaults to bin and marks report-grade only for bin. |
| Peak WAV naming and role | Proven | Names end with `__scale-peak.wav`; metadata marks listening preview only and not for attenuation. |
| Range WAV naming and role | Proven | Names include `__scale-range-fs<V>V.wav`; metadata marks cross-check only when full-scale voltage is known. |
| Final metrics from saved `.bin` | Proven | Run and metrics JSON include `finalized_from_saved_bin`, `result_grade`, and raw-bin provenance; tests cover normal and plot-failure finalization. |
| Conversion | Proven | `.bin` to WAV converter supports `peak`, `range`, `both`; tests cover naming, scale modes, and overwrite safeguards. |
| Analysis metrics | Proven | RMS, Welch PSD, default 300-3400 Hz, wide 20-3900 Hz, dominant tone +/-50 Hz, DC/clipping/sample-count flags; synthetic tests cover expected behavior. |
| Plots | Proven | Waveform, PSD, spectrogram, PSD overlay, attenuation bar are generated as PNG/SVG; tests and audit verify artifacts. |
| Compare | Proven | Manual and auto-pair `uj0`/`uj1`, metadata mismatch warnings, attenuation dB, remaining fraction, reduction percent, JSON/CSV/plots. |
| Individual file downloads | Proven | Session file routes and file browser support `.bin`, WAV, plots, metrics, reports, logs; route tests cover downloads. |
| ZIP exports | Proven | Run/session/multi-session ZIPs include manifests, missing-file records, unsafe path rejection, relative archive names, session-level hardware validation evidence, and readiness snapshots when records exist. |
| Logs/debug UI | Proven | `/logs` displays app/job events, run logs, tracebacks, and diagnostic downloads; tests cover traceback capture. |
| Dashboard command center UI | Proven | `app/templates/dashboard.html` has always-visible Setup, Capture And Live Preview, Results/Compare/Export, live canvases, latest artifacts, recent runs, and operations; dashboard workflow controls are not hidden behind tabs. Static plot images use lazy/async loading and stable aspect ratios so the command surface stays responsive. |
| Live monitor v0.2 | Proven for mock source | `/live` and `/live/snapshot` expose waveform, RMS/peak, clipping, PSD, spectrogram, preview-only labels, finalization status, and final artifact pointers. Canvas drawing is scheduled with `requestAnimationFrame` and avoids flattening spectrogram rows during each refresh. |
| Live monitor with real DAQ source | Code path proven, not physically verified | Default live preview remains mock. Explicit DAQ live preview performs short lazy-`uldaq` scans, is blocked while recording is active to avoid a second DAQ reader, and degrades to structured preview errors when hardware/drivers are unavailable. Physical DAQ live signal quality still needs lab verification. |
| Post-record finalization | Proven | Recording/import flows finalize from saved `.bin`; live snapshot surfaces latest finalized report-grade run and artifacts. |
| Optional Mac Helper APIs | Proven in mock/test mode | `/health`, `/devices`, `/files`, `/validate-playback`, `/play`, `/stop`, `/status`; standalone tests cover structured responses. |
| Mac Helper path safety | Proven | Relative-only `wav_root` validation, traversal rejection, symlink-outside exclusion, optional bearer token tests. |
| Mac Helper explicit device use | Proven in code/test | Playback validation checks the selected device, playback uses `sd.play(..., device=req.device_id, ...)`, and tests guard against mutating `sounddevice.default`. Physical output routing still needs Mac lab verification. |
| Linux Helper integration | Proven | Manual URL config, health/files/devices/actions, validate-before-play-and-record, disconnected-safe behavior, run JSON/log persistence. |
| Tailscale discovery | Proven as best-effort optional | `app/services/tailscale.py` and UI route handle absent/unexpected Tailscale without breaking manual connection. |
| README and dependency files | Proven | `README.md`, `requirements.txt`, `requirements-mac-helper.txt`, `mac_helper/README.md`. |
| Hardware validation protocol | Proven as documented protocol | `../docs/HARDWARE_VALIDATION_PROTOCOL.md` defines the DAQ smoke capture, Mac Helper playback validation, play-and-record trial, attenuation pair check, and pass/fail evidence. Physical execution remains lab work. |
| Safe start/stop operation | Proven for local controls | `scripts/console_control.py`, `/ops`, Linux desktop launcher installer, and Mac Helper control scripts provide explicit start/status/stop flows. |
| Hardware validation evidence capture | Proven for text persistence | `/ops` records operator-entered DAQ/Mac/play-and-record/attenuation validation evidence to `workspace/.micloaker/hardware_validation.jsonl` and `hardware_validation_report.md`; direct downloads and ZIP inclusion are tested. Physical execution remains lab work. |
| Hardware validation readiness gates | Proven for operator-entered evidence | `/ops/readiness` and `scripts/lab_readiness_check.py` use the latest record per gate; `fail` makes readiness fail, `warn`/missing stays warning, and `pass`/`not applicable` closes a gate. `/ops` and `scripts/lab_readiness_check.py --write-report` persist `lab_readiness_report.json` and `lab_readiness_report.md` for export evidence. |
| Tests without DAQ/Mac Helper | Proven | Full suite passes without physical DAQ or Mac Helper service. |

## Legacy Reference Alignment

The notebooks under `../docs/legacy` are treated as workflow references rather than executable acceptance artifacts. See `../docs/LEGACY_NOTEBOOK_ALIGNMENT.md` for the durable mapping.

- `bin_to_wav.ipynb`: represented by `app/services/converter.py`, mode-tagged peak/range WAV outputs, and converter tests.
- `plot_maker.ipynb` and `SJR_plot_maker.ipynb`: represented by waveform, PSD, spectrogram, PSD overlay, and attenuation plot generation.
- `volume_measurer.ipynb`: represented by RMS, band power, dominant tone, and quality-flag analysis.
- `daq_deploy.ipynb`: represented by lazy DAQ integration and mock fallback; physical DAQ behavior remains lab-verification work.
- `jtest.ipynb`: represented only as historical exploratory context; no direct runtime requirement is inferred from it.

## Remaining Lab Verification

These items are outside what the local mock/test environment can prove:

1. Connect the actual DAQ and run a short DAQ capture through `Record DAQ + Finalize`.
2. Confirm actual sample rate, channel, DAQ range, and `.bin` sample count match lab expectations.
3. Run Mac Helper on macOS with a real output device, validate a prepared WAV, play it, stop it, and confirm the selected `device_id` receives audio without changing the system default output.
4. Verify explicit DAQ live preview with the actual DAQ, including selected channel/range/input mode and expected waveform/PSD behavior.
5. Compare a known legacy `.bin` sample against legacy notebook output if exact historical numeric parity is needed.

Use `../docs/HARDWARE_VALIDATION_PROTOCOL.md` as the operator checklist for items 1-3 and the first attenuation pair check.

## Current Completion Assessment

The implementation satisfies the documented local/mock and text-persistence acceptance surface with automated evidence. The remaining unproven items are physical DAQ capture, physical Mac playback routing, and optional numeric parity against historical notebooks.
