**MiCloaker Lab Console**을 구현하세요. Linux에서 실행되는 안정적인 local web app입니다. 상시 운영 서비스가 아니라, 실험 전에 켜고 SSH port forwarding으로 접속한 뒤 실험 후 끄는 도구입니다. 기본 bind는 반드시 `127.0.0.1`이어야 합니다. 최우선은 안정성과 단순성입니다.

구조적 Python 프로젝트로 구현하세요. `FastAPI + Jinja2 + vanilla JS/CSS`를 권장합니다. frontend build step은 사용하지 마세요. **DB는 사용하지 마세요.** 모든 상태는 workspace 안의 텍스트 파일로 관리합니다. session/run metadata는 JSON, 목록과 이벤트는 JSONL, 결과 표는 CSV, 보고서는 Markdown, 로그는 `.log` 파일로 저장하세요. 재시작 시 이 파일들을 읽어서 session/run 목록을 복구하세요. DAQ가 없어도 동작하도록 mock DAQ mode와 테스트를 제공하세요. `uldaq`는 DAQ 함수 안에서만 lazy import하세요.

Linux 핵심 플로우: session 생성/열기 → run 녹음 → raw `.bin` float64 voltage 저장 → scale mode가 명시된 WAV 생성 → audio/plot preview → saved `.bin` 기준 final metrics 계산 → `uj0/uj1` 비교 → file/run/session ZIP export. `.bin`은 primary quantitative data입니다. Peak WAV는 listening-only이고, Range WAV는 cross-check입니다. WAV 파일명에는 반드시 `__scale-peak.wav` 또는 `__scale-range-fs10V.wav`를 붙이세요.

v0.1 필수 기능: session/run 관리, metadata form, recording job/text logs, bin→wav 변환, file browser, audio player, waveform/PSD/spectrogram plot, final RMS/Welch PSD/300–3400 Hz band power/dominant-tone metrics, `uj0/uj1` attenuation dB, CSV/JSON/PNG/SVG 결과, individual/run/session/multi-session ZIP download, debug/log console과 traceback viewer.

v0.2 필수 기능: Live Monitor Mode. real-time waveform, RMS/peak meter, clipping warning, live PSD, scrolling spectrogram을 표시하세요. Live 값은 preview-only로 표시해야 합니다. 녹음 종료 후 saved `.bin`을 다시 읽어 final metrics/plots/WAVs를 재계산하고 UI/metadata를 업데이트하세요. finalized metrics만 report-grade입니다.

선택 기능으로 **macOS Audio Helper** companion service를 추가하세요. Mac에서 실험용 WAV를 특정 output device로 재생하기 위한 기능입니다. Linux-only 기능을 절대 막으면 안 됩니다. Manual Helper URL 연결을 먼저 구현하고, Tailscale auto-discovery는 optional로 두세요. Helper API는 `/health`, `/devices`, `/files`, `/validate-playback`, `/play`, `/stop`, `/status`입니다. Helper는 configured `wav_root` 안의 WAV만 재생하고, system default output을 바꾸지 말고, explicit `device_id`로 출력해야 합니다. 재생 전 file/device/sample-rate/channels를 검증하고 명확한 error를 반환하세요. Helper 상태와 재생 정보는 run JSON/log에 저장하세요.

복잡한 구조를 피하세요. Linux core를 먼저 안정화하고 그다음 live monitor와 Mac Helper를 붙이세요. `README.md`, `requirements.txt`, `requirements-mac-helper.txt`, tests, 실행 명령을 포함하세요.
