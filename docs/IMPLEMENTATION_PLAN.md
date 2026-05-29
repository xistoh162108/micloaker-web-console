# Implementation Plan

## Phase 0 — Stable skeleton

- Create structured FastAPI project.
- Add config/workspace creation.
- Add text-file storage layer: JSON, JSONL, CSV, Markdown, logs.
- Add atomic JSON write helper.
- Add workspace scanner and index rebuild helper.
- Add app logging.
- Add dashboard and basic templates.
- Add tests for startup and workspace creation.

## Phase 1 — File and mock workflow

- Implement sessions/runs with JSON metadata.
- Implement append-only JSONL events/indexes.
- Implement mock DAQ data generation.
- Implement `.bin` writer/reader.
- Implement bin→wav conversion with scale mode filename tags.
- Implement file browser and audio player.
- Implement run ZIP/session ZIP.
- Tests must pass without DAQ.

## Phase 2 — Analysis and compare

- Implement analyzer.
- Implement plots.
- Implement finalization job.
- Implement compare page.
- Implement result CSV/JSON/PNG/SVG.
- Add quality flags and metadata mismatch warnings.

## Phase 3 — Real DAQ integration

- Lazily import `uldaq`.
- Add DAQ health check.
- Add one-recording-at-a-time guard.
- Add real recording route/job.
- Keep offline developer validation available.

## Phase 4 — v0.2 Live Monitor

- Add offline developer live monitor first.
- Add DAQ monitor-only mode if safe.
- Add recording + live monitor through shared acquisition loop.
- Add preview/final result UI distinction.

## Phase 5 — Optional macOS Audio Helper

- Implement `mac_helper/helper.py` with health/devices/files/validate/play/stop/status.
- Implement Linux `mac_helper_client.py`.
- Add Mac Helper UI panel.
- Add manual URL connection first.
- Add optional Tailscale discovery only if simple.
- Add Play & Record after validation.
- Store Helper metadata in run JSON/log files.
- Ensure Linux-only tests still pass when Helper is absent.

## Phase 6 — Polish

- Improve CSS.
- Improve plots.
- Add report markdown export.
- Add documentation and troubleshooting.

## Critical sequencing rule

Do not implement Mac Helper before the stable Linux mock workflow, analysis, and exports are working. Do not add a database at any phase.
