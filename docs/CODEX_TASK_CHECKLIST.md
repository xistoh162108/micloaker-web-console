# Codex Task Checklist

Status language:

- **Automated evidence complete** means the implementation is covered by current tests, `scripts/acceptance_audit.py`, docs alignment, or runtime validation checks.
- **Lab verification required** means the code path exists, but physical DAQ/audio behavior must still be proven with real hardware before report-grade experiments.

## Build order

- [x] Create project structure. Automated evidence complete.
- [x] Add README and dependency files. Automated evidence complete.
- [x] Implement config and workspace initialization. Automated evidence complete.
- [x] Implement text-file storage helpers: JSON, JSONL, CSV, Markdown, logs. Automated evidence complete.
- [x] Implement atomic JSON write. Automated evidence complete.
- [x] Implement workspace scan and index rebuild. Automated evidence complete.
- [x] Implement session/run models. Automated evidence complete.
- [x] Implement job manager and log capture. Automated evidence complete.
- [x] Implement mock DAQ. Automated evidence complete.
- [x] Implement bin read/write. Automated evidence complete.
- [x] Implement bin→wav converter with mode-tagged filenames. Automated evidence complete.
- [x] Implement analyzer and plots. Automated evidence complete.
- [x] Implement finalization job. Automated evidence complete.
- [x] Implement compare metrics and plots. Automated evidence complete.
- [x] Implement exports. Automated evidence complete.
- [x] Implement hardware validation evidence records and readiness gate status. Automated evidence complete for text persistence; physical gates still require lab evidence.
- [x] Implement web routes and templates. Automated evidence complete.
- [x] Implement logs/debug UI. Automated evidence complete.
- [x] Implement real DAQ functions with lazy `uldaq` import. Code path and lazy import are tested; physical DAQ capture remains lab verification.
- [x] Implement v0.2 live monitor. Offline developer source and DAQ-degradation behavior are tested; physical DAQ live signal remains lab verification.
- [x] Implement optional Mac Helper standalone service. Offline developer validation evidence complete; physical output routing remains lab verification.
- [x] Implement Linux Mac Helper client and UI. Automated evidence complete.
- [x] Add tests. Automated evidence complete.
- [x] Run tests. Latest recorded result: `146 passed`.
- [x] Run Playwright UI smoke. Latest recorded scope covers dashboard, sessions, new-run, compare, Mac Helper, Ops, and Live screens at desktop/mobile viewports for horizontal overflow and control overlap.

## Do not forget

- [x] No database.
- [x] Default bind is 127.0.0.1.
- [x] Peak WAV is never used as final quantitative source.
- [x] Mac Helper disconnected state is harmless.
- [x] Helper does not change system default output device in code/tests; confirm selected physical output during Mac lab validation.
- [x] Helper blocks path traversal outside `wav_root`.
- [x] Logs and tracebacks are visible in UI.
- [x] ZIP exports include manifests.
- [x] Hardware validation evidence is stored as text, downloadable, included in session exports, and reflected in readiness checks.

## Remaining lab verification

- [ ] Run a short real DAQ validation capture and record `/ops` evidence for channel, range, sample count, and saved `.bin` finalization.
- [ ] Run explicit DAQ live preview on the real DAQ and record `/ops` evidence for expected waveform/PSD behavior.
- [ ] Run Mac Helper on the actual macOS playback machine, validate/play/stop on the intended `device_id`, and confirm the macOS system default output is unchanged.
- [ ] Run a short play-and-record DAQ trial if synchronized Mac playback and Linux DAQ recording are required.
- [ ] Record one finalized real `uj0`/`uj1` attenuation pair and inspect BIN-primary comparison output.
- [ ] Optionally compare a known historical `.bin` against the legacy notebooks if exact legacy numeric parity is required.
