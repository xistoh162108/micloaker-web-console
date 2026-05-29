# Codex Task Checklist

## Build order

- [ ] Create project structure.
- [ ] Add README and dependency files.
- [ ] Implement config and workspace initialization.
- [ ] Implement text-file storage helpers: JSON, JSONL, CSV, Markdown, logs.
- [ ] Implement atomic JSON write.
- [ ] Implement workspace scan and index rebuild.
- [ ] Implement session/run models.
- [ ] Implement job manager and log capture.
- [ ] Implement mock DAQ.
- [ ] Implement bin read/write.
- [ ] Implement bin→wav converter with mode-tagged filenames.
- [ ] Implement analyzer and plots.
- [ ] Implement finalization job.
- [ ] Implement compare metrics and plots.
- [ ] Implement exports.
- [ ] Implement web routes and templates.
- [ ] Implement logs/debug UI.
- [ ] Implement real DAQ functions with lazy `uldaq` import.
- [ ] Implement v0.2 live monitor.
- [ ] Implement optional Mac Helper standalone service.
- [ ] Implement Linux Mac Helper client and UI.
- [ ] Add tests.
- [ ] Run tests.

## Do not forget

- [ ] No database.
- [ ] Default bind is 127.0.0.1.
- [ ] Peak WAV is never used as final quantitative source.
- [ ] Mac Helper disconnected state is harmless.
- [ ] Helper does not change system default output device.
- [ ] Helper blocks path traversal outside `wav_root`.
- [ ] Logs and tracebacks are visible in UI.
- [ ] ZIP exports include manifests.
