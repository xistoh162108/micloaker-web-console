# Hardware Validation Protocol

This protocol is the required lab-side verification before treating MiCloaker Lab Console results as experiment-ready on real hardware. Automated tests prove the text-file workflow, mock DAQ path, analysis, export, and Helper API behavior. They do not prove physical DAQ capture quality or ultrasonic playback.

## 1. Pre-Run Readiness

Run these from the Linux console computer:

```bash
cd micloaker_lab_console
.venv/bin/python scripts/console_control.py status
.venv/bin/python scripts/lab_readiness_check.py --check-server --server-url http://100.x.y.z:8000 --write-report
```

Also open:

```text
http://100.x.y.z:8000/ops
http://100.x.y.z:8000/ops/readiness
```

Required evidence:

- `/ops/readiness` has `fail: 0`.
- Workspace text files are present.
- Recording lock is not active.
- DAQ backend warning is understood if working in mock-only mode.
- Mac Helper warning is understood if Linux-only workflow is planned.
- Server is reachable through the intended access path: SSH tunnel or explicit Tailscale bind.

Record physical validation evidence in `/ops` under **Hardware Validation Records**. The console saves these operator-entered records to:

```text
workspace/.micloaker/hardware_validation.jsonl
workspace/.micloaker/hardware_validation_report.md
workspace/.micloaker/lab_readiness_report.json
workspace/.micloaker/lab_readiness_report.md
```

Use one record per gate: DAQ smoke capture, Mac Helper playback validation, play-and-record trial, attenuation pair check, and optional legacy notebook parity check.
Session ZIP and multi-session ZIP exports include these records and readiness snapshots under `ops_validation/` when they exist.
The `/ops` page also provides direct downloads for `hardware_validation.jsonl`, `hardware_validation_report.md`, `lab_readiness_report.json`, and `lab_readiness_report.md`.
The `/ops` page displays **Evidence Hints** for each validation gate so the operator can record the expected IDs, file paths, measured values, Helper/device details, and unresolved warnings consistently.
The latest record for each gate controls the readiness status: any `fail` gate makes readiness fail, any `warn` or missing gate keeps readiness in warning state, and each gate must be `pass` or explicitly marked `not applicable` before the hardware validation section is green.
The same gate status logic is used by `scripts/lab_readiness_check.py`; a failed validation gate makes the CLI exit non-zero.

## 2. Linux DAQ Smoke Capture

Use a short, low-risk DAQ run before the real experiment.

1. Create a dedicated validation session, for example `hardware_validation_YYYYMMDD`.
2. Create a run with the intended DAQ channel, range, input mode, sample rate, and duration.
3. Use `Record DAQ + Finalize`.
4. Confirm the run page shows report-grade metrics recomputed from saved `.bin`.
5. Download or inspect the run ZIP.

Required evidence:

- Raw `.bin` exists under `workspace/sessions/<session_id>/bin/`.
- Run metadata records `recording.source = "daq"`.
- `written_samples` and metrics `sample_count` match expected duration and sample rate within lab tolerance.
- DAQ channel/range/input mode in run JSON match the physical wiring.
- Run log has no traceback.
- Waveform, PSD, and spectrogram plots are present as PNG/SVG.
- `/ops` Hardware Validation Records contains a DAQ smoke entry with the session/run IDs and sample-count evidence.

Do not reuse a failed raw `.bin` filename. Create a new run after DAQ wiring or driver changes.

## 3. Mac Helper Playback Validation

Run this only when Mac-side playback is part of the experiment.

1. Start the Mac Helper with its configured `wav_root`.
2. Open the Linux console `/mac-helper` page.
3. Save the manual Helper URL.
4. Refresh devices and files.
5. Select the explicit `device_id`, WAV file, sample rate, channel count, and gain.
6. Run `Validate Playback`.
7. Run `Play`, then `Stop Playback`.
8. Confirm macOS system default output did not change.

Required evidence:

- Helper `/health` is reachable.
- Helper `/devices` lists the intended output device.
- Helper `/files` lists only files under `wav_root`.
- `/validate-playback` returns `ok: true`.
- Playback uses the selected `device_id`.
- Helper status shows playback start/stop state correctly.
- The run JSON/log records Helper validation or playback details when using run-level controls.
- `/ops` Hardware Validation Records contains a Mac playback entry with the selected `device_id`, Helper URL, validation result, and physical routing notes.

## 4. End-to-End Play And Record Trial

Use a short trial before collecting final data.

1. Create or select a validation run.
2. On the run detail page, use `Validate Playback`.
3. Use `Play & Record Mock` first to confirm control flow.
4. Use `Play & Record DAQ` for a short physical capture.
5. Confirm finalization from saved `.bin`.
6. Confirm WAV previews are present but not used for report-grade attenuation.

Required evidence:

- Mac Helper validation is recorded before play-and-record.
- The DAQ run stores a raw `.bin`.
- Final metrics are marked report-grade and finalized from saved `.bin`.
- Peak WAV is labeled listening preview only.
- Range WAV is labeled cross-check only.
- Log files show play, record, finalization, and stop/failure state clearly.
- `/ops` Hardware Validation Records contains a play-and-record entry with the run ID and finalization evidence.

## 5. Attenuation Pair Check

Before the real experiment, record one known `uj0` and one known `uj1` validation pair.

1. Finalize both runs.
2. Open Compare.
3. Use BIN primary source.
4. Compute attenuation.
5. Inspect PSD overlay and attenuation bar chart.

Required evidence:

- Comparison JSON and CSV exist under `comparisons/`.
- `source = "bin"` and result grade is report-grade.
- The attenuation formula and band are visible in the saved result.
- Any acquisition mismatch warning is understood before proceeding.
- `/ops` Hardware Validation Records contains an attenuation-pair entry with the comparison file path and pass/warn/fail decision.

## 6. Pass/Fail Decision

The setup is ready for a real experiment only when:

- Linux console readiness has no failures.
- A real DAQ smoke capture succeeds, if DAQ recording is required.
- Mac Helper validates and plays/stops on the intended output device, if Mac playback is required.
- A short end-to-end play-and-record DAQ trial succeeds, if synchronized playback and recording is required.
- Export ZIP contains raw `.bin`, metadata JSON, logs, metrics, plots, WAV previews, and manifest.

If any item fails, keep using mock/import workflows only until the physical issue is fixed.

## Korean Operator Notes

- 실제 DAQ 녹음은 mock 테스트와 별개로 반드시 짧은 smoke capture를 먼저 해야 합니다.
- Mac Helper의 `Validate Playback`은 파일/장치/샘플레이트 설정 검증입니다. 실제 초음파 출력은 DAQ/마이크 경로로 확인해야 합니다.
- 최종 attenuation 보고에는 saved `.bin`에서 재계산된 metrics만 사용합니다. Peak WAV는 청취 preview 전용입니다.
- 실패한 run의 raw `.bin`을 덮어쓰지 말고 새 run을 만드세요.
