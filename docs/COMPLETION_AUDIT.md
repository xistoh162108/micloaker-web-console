# Completion Audit

Last updated: 2026-05-29

This document is the requirement-by-requirement audit for the active MiCloaker Lab Console goal. It does not replace physical lab validation. It separates requirements that are proven by repository evidence from requirements that remain unproven until the real DAQ and macOS playback path are exercised in the lab.

## Evidence Commands

Run from `micloaker_lab_console/`:

```bash
.venv/bin/pytest -q
.venv/bin/python scripts/acceptance_audit.py
.venv/bin/python scripts/lab_readiness_check.py --check-server --server-url http://100.88.179.43:8000 --write-report
```

Expected automated state as of this audit:

- Full test suite: `133 passed`
- Acceptance audit: `PASS`
- Tailscale lab console smoke route: `http://100.88.179.43:8000` returns HTTP 200 when started explicitly with `--tailscale`
- Default configured bind remains `127.0.0.1`

## Status Definitions

- **Proven**: Current repository files, tests, acceptance audit, or runtime smoke checks directly verify the requirement.
- **Code proven, lab verification required**: Code path and failure handling are covered, but physical DAQ/audio behavior cannot be proven without hardware.
- **Protocol only**: The app records the required evidence, but the user must execute the physical procedure.

## Goal Requirement Audit

| Requirement | Status | Current evidence |
|---|---|---|
| Stable local Linux web app, not always-on production service | Proven | `README.md` documents temporary start/status/restart/stop, SSH tunnel, Tailscale explicit mode, and `scripts/console_control.py`; `/ops` exposes safe status/shutdown controls. |
| Default bind is `127.0.0.1` | Proven | `app/config.py` default and `scripts/acceptance_audit.py` check `DEFAULT_HOST == "127.0.0.1"`. |
| FastAPI + Jinja2 + vanilla JS/CSS, no frontend build step | Proven | `app/main.py`, `app/templates/`, `app/static/js/`, `app/static/css/app.css`; no React/Vite/Webpack config in the app. |
| No database | Proven | Acceptance audit scans for database-like files and forbidden DB dependencies; requirements exclude database packages. |
| Plain text persistence only | Proven | `app/services/text_store.py`; workspace files use JSON, JSONL, CSV, Markdown, and `.log`. |
| Restart rebuilds lists by reading text files | Proven | Metadata rebuild/index tests and acceptance workflow stale-index checks. |
| Mock DAQ works without hardware | Proven | Mock DAQ service and full test suite run without DAQ. |
| `uldaq` imported lazily only inside DAQ-specific functions | Proven | DAQ service lazy import tests and acceptance audit assert app startup does not import `uldaq`. |
| Create/open session and run workflow | Proven | Session/run routes, metadata helpers, templates, and tests. |
| Raw `.bin` float64 voltage is saved and primary quantitative source | Proven | Recorder/finalizer validates raw `.bin`; metrics source is `bin`; compare report grade depends on BIN source. |
| WAV conversion with `__scale-peak.wav` and `__scale-range-fs...V.wav` tags | Proven | Converter service and tests cover peak/range naming. |
| Peak WAV listening-only, not final attenuation source | Proven | Conversion metadata and tests label peak WAV as preview only. |
| Range WAV cross-check only when full-scale voltage is known | Proven | Conversion metadata and tests label range WAV cross-check role. |
| Final metrics recomputed from saved `.bin` after recording/import | Proven | Finalization metadata includes `finalized_from_saved_bin`; tests cover finalized metrics and plots. |
| Recording job has text logs, status, traceback capture | Proven | Job service and logs UI tests cover traceback capture and status. |
| One recording job at a time | Proven | Recorder lock and busy-state tests. |
| Never silently overwrite raw `.bin` | Proven | Recorder/finalization conflict tests reject existing raw `.bin`. |
| Metadata forms include experiment and safety fields | Proven | New-run/session forms and tests cover acquisition, condition, analysis, conversion, safety, and Mac Helper planning fields. |
| File browser and audio preview | Proven | `/files`, run detail artifact links, audio element, and route tests. |
| Waveform, PSD, spectrogram, PSD overlay, attenuation plots | Proven | Plotting service, compare artifacts, acceptance workflow, and ZIP tests; report plot previews use bounded waveform/PSD rendering and rasterized spectrogram SVG output for faster browser inspection. |
| RMS, Welch PSD, band powers, dominant tone, clipping/DC/sample-count flags | Proven | Analyzer service and synthetic tests. |
| `uj0`/`uj1` attenuation, remaining fraction, reduction percent | Proven | Compare service and tests. |
| Individual, run, session, and multi-session ZIP downloads | Proven | Export service, route tests, and acceptance audit; session/multi-session ZIPs include validation/readiness evidence and `hardware_validation_plan.txt`. |
| ZIP manifests and safe relative archive paths | Proven | Export tests and acceptance audit. |
| Debug/log console with tracebacks | Proven | Logs route/template and traceback tests. |
| Live Monitor waveform/RMS/peak/clipping/PSD/spectrogram | Proven for mock source | `/live`, `/live/snapshot`, live monitor service, and tests; live charts use `requestAnimationFrame`, display-size canvas rendering, and `ImageData` spectrogram updates. |
| Live values are preview-only | Proven | Live UI text, JSON payload labels, docs, and tests. |
| DAQ live preview | Code proven, lab verification required | Explicit DAQ preview route uses lazy DAQ scan and structured errors; physical DAQ waveform/PSD quality must be validated in lab. |
| DAQ recording with real hardware | Code proven, lab verification required | DAQ code path and fake-`uldaq` tests exist; actual sample rate, channel, range, and saved `.bin` count need physical DAQ evidence. |
| Optional macOS Audio Helper is not required for Linux-only workflows | Proven | Disconnected Helper tests and UI status keep Linux workflows available. |
| Helper APIs `/health`, `/devices`, `/files`, `/validate-playback`, `/play`, `/stop`, `/status` | Proven in mock/test mode | `mac_helper/helper.py` and `tests/test_mac_helper.py`. |
| Helper plays only under `wav_root` and blocks traversal | Proven | Helper file/path tests. |
| Helper validates file/device/sample-rate/channels before play | Proven in mock/test mode | Helper validation tests. |
| Helper uses explicit `device_id` without changing system default output | Code proven, lab verification required | Tests prove `sd.play(..., device=req.device_id, ...)` and no mutation of `sounddevice.default`; physical output routing still needs Mac validation. |
| Helper status/playback info stored in run JSON/log files | Proven | Linux Helper integration and play-and-record tests. |
| Manual Helper URL first, Tailscale discovery optional | Proven | Mac Helper UI/config and best-effort discovery tests. |
| Hardware validation records with workflow navigation | Proven for text persistence | `/ops` and `scripts/lab_readiness_check.py --record-gate ...` record operator-entered validation evidence, `hardware_validation_plan.txt` is persisted under `.micloaker`, `--validation-plan` and `/ops/validation/plan` provide ordered lab gate instructions, `--write-evidence-template` writes fillable gate evidence notes, readiness Markdown includes record commands, `--record-evidence-file` supports longer terminal evidence notes, gate-specific evidence hints are exposed, the Use checklist draft helper fills fields, Next action links route to DAQ run creation/Mac Helper/Compare/file review, and exports include JSONL/Markdown evidence. |
| README, requirements files, tests, clear run commands | Proven | `README.md`, `requirements.txt`, `requirements-mac-helper.txt`, test suite, and acceptance audit. |
| Docs and legacy notebooks considered authoritative references | Proven | `docs/LEGACY_NOTEBOOK_ALIGNMENT.md`, `docs_alignment_report.md`, and acceptance audit documentation checks. |

## Remaining Requirements Not Yet Proved By Automation

These are not code gaps; they require physical devices and operator evidence:

1. Real DAQ smoke capture: record channel, range, input mode, actual sample count, saved `.bin`, and finalization result in `/ops`.
2. Real DAQ live preview: confirm expected waveform/PSD behavior and record evidence in `/ops`.
3. Real macOS playback: validate/play/stop on the intended `device_id`, confirm physical routing, and confirm system default output is unchanged.
4. End-to-end play-and-record: run a short synchronized Mac playback + Linux DAQ capture when that workflow is required.
5. Real attenuation pair: record finalized `uj0` and `uj1` runs and inspect BIN-primary comparison output.
6. Legacy numeric parity: optionally compare a known historical `.bin` against legacy notebook output if exact parity is needed.

## Completion Decision

The software implementation is complete for the local/mock/text-persistence acceptance surface currently available in this repository. The overall goal must remain open until the lab-only physical verification items above have matching `/ops` evidence records or the user explicitly declares those hardware gates out of scope for completion.
