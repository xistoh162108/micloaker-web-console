# MiCloaker Lab Console — Text-file Storage Codex Package

This package is a Codex Goal Mode handoff for building a stable, local, experiment-first web console for MiCloaker acoustic/DAQ experiments.

## Key decision

**Do not use any database.** The system must manage state with plain text files only:

- JSON: per-session and per-run metadata
- JSONL: append-only indexes, event history, job history
- CSV: metric/result tables
- Markdown: generated reports
- `.log`: job/app logs and tracebacks

This keeps the experiment tool simple, inspectable, easy to back up, and easy to recover.

## How to use

1. Put `AGENTS.md` at the repository root.
2. Paste `GOAL_PROMPT_UNDER_4000_CHARS.md` into Codex Goal Mode.
3. Provide the remaining documents as reference material.
4. Ask Codex to implement in phases and run tests after each phase.

## Highest-level principle

Stability first. Keep the Linux recording/analysis workflow simple and reliable. The macOS Audio Helper is optional and must never break Linux-only recording, conversion, analysis, upload, export, or log viewing.

## Documents

- `GOAL_PROMPT_UNDER_4000_CHARS.md`: short Codex Goal Mode prompt.
- `AGENTS.md`: repository-level implementation rules for coding agents.
- `PRD.md`: product requirements.
- `REQUIREMENTS.md`: detailed functional/non-functional requirements.
- `TEXT_FILE_STORAGE_SPEC.md`: no-DB text-file storage design.
- `STABILITY_AND_SIMPLICITY.md`: complexity budget and safety rules.
- `ARCHITECTURE.md`: stable project architecture.
- `MAC_AUDIO_HELPER_SPEC.md`: optional macOS playback helper specification.
- `UI_UX_SPEC.md`: intuitive but flexible web UI design.
- `LIVE_MONITOR_V02.md`: v0.2 live waveform/spectrogram and finalize workflow.
- `EXPORT_DOWNLOAD_SPEC.md`: file/run/session ZIP export requirements.
- `FILE_NAMING_AND_METADATA.md`: naming and metadata schema.
- `ANALYSIS_SPEC.md`: audible noise energy analysis methods.
- `IMPLEMENTATION_PLAN.md`: phased implementation roadmap.
- `ACCEPTANCE_TESTS.md`: acceptance tests.
- `CODEX_TASK_CHECKLIST.md`: concrete coding checklist.
- `REQUIREMENTS_TEMPLATE.txt`: dependency template.
