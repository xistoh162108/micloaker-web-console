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
- Mock run saves `.bin`.
- Conversion creates `__scale-peak.wav` and `__scale-range-fs10V.wav`.
- Peak WAV is labeled listening-only.
- Range WAV is labeled cross-check.
- Finalization reads saved `.bin` and produces metrics/plots.
- Run detail page shows metadata, files, audio player, plots, metrics, and logs.
- Run ZIP contains expected files and manifest.
- Session ZIP contains runs, metadata, results, plots, logs, and manifest.
- Session and multi-session ZIPs include hardware validation JSONL/Markdown evidence when records exist.
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

- Mock live monitor starts and stops.
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
