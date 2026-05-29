# Acceptance Tests

## 1. Core Linux tests

- App starts without DAQ hardware.
- App creates workspace directories.
- App does not create or require any database file.
- User can create a session.
- Session metadata is stored as `session.json`.
- User can create a mock run.
- Run metadata is stored as `metadata/<run_id>.json`.
- Session/run events are appended to JSONL files.
- Offline validation run saves `.bin`.
- Conversion creates `__scale-peak.wav` and `__scale-range-fs10V.wav`.
- Peak WAV is labeled listening-only.
- Range WAV is labeled cross-check.
- Finalization reads saved `.bin` and produces metrics/plots.
- Run detail page shows metadata, files, audio player, plots, metrics, and logs.
- Run ZIP contains expected files and manifest.
- Session ZIP contains runs, metadata, results, plots, logs, and manifest.
- Session and multi-session ZIPs include hardware validation JSONL/Markdown evidence and lab readiness JSON/Markdown snapshots when records exist.
- App restart reloads sessions/runs by scanning text files.

## 2. Text-file storage tests

- Atomic JSON write creates valid JSON.
- JSONL append works for job/session/run events.
- Missing/stale JSONL index can be rebuilt by scanning session/run JSON files.
- Logs are written as text files.
- Summary CSV can be regenerated from run JSON/metrics JSON.

## 3. Analysis tests

- Synthetic `uj0`/`uj1` signals with known power ratio produce expected attenuation dB within tolerance.
- PSD band integration works for 300–3400 Hz.
- Dominant tone detection works on synthetic tone.
- Clipping flag triggers when signal approaches full-scale.
- Metadata mismatch warning appears during compare.

## 4. Live Monitor tests

- Offline developer live monitor starts and stops.
- Waveform updates.
- RMS/peak updates.
- PSD and spectrogram update.
- UI labels live values as preview-only.
- Recording end triggers finalization.
- Final metrics are marked report-grade.

## 5. Mac Helper standalone tests

- `/health` returns valid response.
- `/files` lists only WAVs under `wav_root`.
- Path traversal is rejected.
- `/devices` returns output devices or clear unavailable error.
- `/validate-playback` returns clear errors for missing file/device/unsupported rate.
- `/play` validates before playing.
- `/stop` and `/status` work.

## 6. Linux + Mac Helper integration tests

- Manual Helper URL can be saved in config JSON.
- Bare Tailnet Helper addresses are normalized to `http://<address>:5050` before Helper API calls.
- Health check success displays Connected.
- Health check failure displays Disconnected without breaking Linux features.
- Devices/files can populate dropdowns when Helper is available.
- Validate Playback must be required before Play & Record.
- Helper playback metadata is stored in run JSON/log files.

## 7. Stability tests

- Tests pass without DAQ.
- Tests pass without Mac Helper.
- Failed jobs capture traceback in text logs.
- Unfinished jobs are marked interrupted/unknown after restart scan.
- `/ops` can record hardware validation evidence as JSONL and Markdown.
- `/ops/readiness` and `scripts/lab_readiness_check.py` reflect validation gate status: fail is failing, warn/missing is warning, and pass/not-applicable closes the gate.
- `/ops` and `scripts/lab_readiness_check.py --write-report` can persist `lab_readiness_report.json` and `lab_readiness_report.md` for experiment evidence packages.
- `scripts/lab_readiness_check.py` prints hardware validation gate status and next-action targets for terminal-only pre-run checks.
- `scripts/lab_readiness_check.py --validation-plan` prints ordered physical validation gates, checklist fields, next-action screens, and terminal record commands.
- `/ops/validation/plan` downloads the same physical validation plan as `hardware_validation_plan.txt`.
- `/ops` and `/ops/validation` expose the persisted `hardware_validation_plan.txt` path.
- Session ZIP and multi-session ZIP exports include `ops_validation/hardware_validation_plan.txt`.
- `/exports/ops-validation.zip` downloads workspace-level validation/readiness evidence without requiring a session export.
- Readiness Markdown includes terminal validation record commands for each hardware gate.
- `scripts/lab_readiness_check.py --write-evidence-template <gate> --evidence-template-file evidence.txt` writes a fillable gate-specific evidence note and refuses accidental overwrite.
- `/ops/validation/templates/<gate>` downloads the same fillable gate-specific evidence note for browser operators.
- Run detail pages download DAQ, Mac playback, and play-and-record evidence drafts from saved run metadata, Helper status, metrics, raw `.bin` path, log state, WAV outputs, and plot artifact status.
- Compare pages download attenuation-pair evidence drafts from saved comparison JSON/CSV and plot artifact status.
- `scripts/lab_readiness_check.py --write-evidence-draft ...` writes the same artifact-based DAQ, Mac playback, play-and-record, and attenuation-pair evidence drafts for terminal-only operators and refuses accidental overwrite.
- `scripts/lab_readiness_check.py --check-server` verifies core routes plus required static UI assets for local CSS and live chart JavaScript, and `--write-report` persists those CLI findings into readiness JSON/Markdown.
- `scripts/lab_readiness_check.py --record-gate ... --record-status ... --record-evidence ...` appends validation JSONL/Markdown evidence for terminal-only lab operation.
- `scripts/lab_readiness_check.py --record-evidence-file evidence.txt` reads longer terminal validation evidence from UTF-8 text.
