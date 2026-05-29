# MiCloaker Lab Operator Manual / 실험 운영 매뉴얼

This document is the concise runbook for a lab operator using one Mac for playback and one Linux computer for DAQ capture.

이 문서는 Mac 한 대를 재생용으로, Linux 컴퓨터 한 대를 DAQ 기록용으로 사용하는 실험자를 위한 간단 운영 매뉴얼입니다.

## 1. Hardware Roles / 장비 역할

- Mac: plays ordinary or ultrasonic WAV files through an explicit audio `device_id`.
- Linux: runs the web console, captures DAQ/microphone voltage, stores raw `.bin`, metrics, plots, logs, and exports.
- Tailscale: connects Mac Helper and Linux console by `100.x.y.z` Tailnet addresses.

- Mac: 명시적인 audio `device_id`로 일반 소리 또는 초음파 WAV를 재생합니다.
- Linux: 웹 콘솔을 실행하고 DAQ/마이크 전압을 기록하며 raw `.bin`, metrics, plots, logs, exports를 저장합니다.
- Tailscale: Mac Helper와 Linux 콘솔을 `100.x.y.z` Tailnet 주소로 연결합니다.

## 2. Start / 실행

Linux:

```bash
cd micloaker_lab_console
source .venv/bin/activate
.venv/bin/python scripts/console_control.py restart --tailscale --allow-web-shutdown
```

Open the printed URL, for example:

```text
http://100.88.179.43:8000
```

Mac Helper:

```bash
cd micloaker_lab_console/mac_helper
python3 helper_control.py start
python3 helper_control.py status
```

The Helper WAV root should contain files such as:

```text
jamming_sound/25khz_1hr.wav
jamming_sound/32.8khz_1hr.wav
```

## 3. Run Semantics / Run 의미

- Jamming carrier `0 kHz`: no jamming signal is emitted.
- `Unjammed: false`: internal value `uj0`.
- `Unjammed: true`: internal value `uj1`.
- Ordinary recorded sound: meeting-room sound, WER material, speech, or quiet baseline. It is not the ultrasonic jamming carrier.
- Raw `.bin`: primary quantitative source.
- Peak WAV: listening preview only.
- Range WAV: cross-check only when full-scale voltage is correct.

## 4. Normal Experiment Flow / 일반 실험 흐름

1. Open Dashboard.
2. Create or choose a session.
3. Create a run and set carrier, unjammed condition, ordinary sound, duration, sample rate, DAQ range, input mode, and notes.
4. If using Mac playback, connect Mac Helper, choose WAV file/device/sample rate/channels/gain, then validate playback.
5. Use one of the run-page controls:
   - Preview only: inspect DAQ live waveform/PSD/spectrogram.
   - Record only: Linux DAQ capture without Mac playback.
   - Play only: Mac playback without DAQ capture.
   - Play + Record: synchronized Mac playback and Linux DAQ capture.
6. The maximum playback/recording length is the run duration.
7. After capture, inspect waveform, RMS/Peak, PSD, spectrogram, WAV preview, metrics, and log.
8. Final report metrics are recomputed from saved `.bin`.
9. Repeat for a matching `Unjammed: false` and `Unjammed: true` pair.
10. Open Compare and compute attenuation from saved `.bin`.
11. Export run ZIP, session ZIP, or multi-session ZIP.

## 5. Import Saved BIN / 저장된 BIN 대체

Use the run detail page's **Import Saved BIN** section when DAQ capture was done elsewhere or the current DAQ is unavailable. The selected file is copied into the run workspace, finalized, and then the live preview panel is filled from that saved `.bin`.

DAQ를 현재 콘솔에서 직접 사용할 수 없거나 외부에서 기록한 `.bin`을 쓰는 경우, run detail page의 **Import Saved BIN**을 사용합니다. 파일은 run workspace로 복사되고 finalize되며, 이후 live preview panel은 해당 saved `.bin` 데이터로 채워집니다.

## 6. Shutdown / 종료

```bash
.venv/bin/python scripts/console_control.py status
.venv/bin/python scripts/console_control.py stop
```

The control script refuses normal shutdown while recording/finalization is active. Use `--force` only for emergency interruption.

## 7. Verification / 확인

Before a real lab session:

```bash
.venv/bin/pytest -q
.venv/bin/python scripts/playwright_ui_smoke.py http://100.88.179.43:8000
.venv/bin/python scripts/lab_readiness_check.py --check-server --server-url http://100.88.179.43:8000 --write-report
```

Physical acoustic output still requires operator validation with the actual speaker, DAC, microphone, and DAQ.
