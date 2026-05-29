# Operator UI and Deployment Requirements

This document records additional operator-facing requirements added during implementation. Treat this document as part of the active MiCloaker Lab Console goal alongside the original PRD, requirements, architecture, live monitor, Mac Helper, and storage specs.

## 1. UI Standard

- The UI standard is **DaisyUI**.
- Because this project must remain FastAPI + Jinja2 + vanilla JavaScript/CSS with no frontend build step, DaisyUI is implemented as a local vanilla CSS compatibility layer.
- Do not add React, Vite, Webpack, Tailwind build tooling, or a Node-based frontend build step.
- Use DaisyUI-style component vocabulary and structure:
  - `btn`, `btn-primary`, `btn-outline`, `btn-error`
  - `card`, `card-body`, `card-title`
  - `stats`, `stat`, `stat-value`, `stat-title`
  - `badge`, `badge-success`, `badge-warning`
  - `input`, `select`, `textarea`, `table`
- `tabs`, `tab`, and `tab-active` may be used only for secondary detail views where switching context does not interrupt experiment operation.
- Layout must prioritize experimental workflow over raw feature lists.

## 2. Experiment Command Center

The main dashboard must behave as a single experiment command center.

Required characteristics:

- Important state should be visible on one screen:
  - active session
  - DAQ/mock status
  - Mac Helper status
  - recording state
  - latest run
  - latest comparison
  - export and operations shortcuts
- Pages should not force the experiment operator to jump through many disconnected tabs for routine work.
- The dashboard must not hide core experiment controls behind tabs during operation.
- The first screen should expose the prioritized workflow as always-visible sections:
  - Setup
  - Capture and live preview
  - Results, compare, and export
  - Operations/readiness
- Controls must have consistent size, alignment, spacing, and visual weight.
- UI elements must not overlap on desktop or mobile.
- Logs are secondary diagnostic tools; visual artifacts and experiment progress are primary.

## 3. Safe Start/Stop Operation

The app is a temporary lab tool, not an always-on daemon. It must be easy and safe to start and stop.

Required Linux controls:

- Command-line start/status/stop script.
- PID file and server log under `workspace/.micloaker/`.
- Default safe local mode remains `127.0.0.1`.
- Explicit Tailscale mode must bind to the `tailscale0` IPv4 address for direct Tailnet browser access.
- Web shutdown must be opt-in only and blocked while recording is active.
- `/ops` must show bind address, workspace, recording state, and shutdown availability.
- `/ops` must show Lab Readiness checks for bind mode, workspace text files, recording lock, DAQ backend, Mac Helper, and web shutdown.
- `/ops/readiness` must expose the same readiness summary as JSON for quick Tailnet/CLI checks.
- Linux desktop launcher installation should provide Start/Status/Stop launchers for GUI use.

Required Mac Helper controls:

- Command-line start/status/stop script.
- Finder double-click launchers:
  - Start
  - Status
  - Stop
- Helper startup should be simple for non-developer operators.

## 4. Tailscale Operation

The default app bind remains `127.0.0.1` for SSH tunneling. Direct Tailscale access is allowed only as an explicit lab mode.

Required behavior:

- If the user wants to open `http://100.x.y.z:8000`, the Linux console must be started with Tailscale binding.
- Documentation must explain that a server listening only on `127.0.0.1:8000` will not be reachable through a Tailscale IP.
- Readiness checks should show whether routes respond through the intended server URL.
- Readiness checks should include `/ops/readiness` so direct Tailnet access can be verified without relying only on the browser UI.

## 5. Manuals and Handoff

Documentation must be usable by another lab operator, not only the original developer.

Required documentation:

- Repository root README as a GitHub landing page.
- Hardware validation protocol for DAQ smoke capture, Mac Helper physical playback validation, short play-and-record trial, and attenuation pair check.
- Linux console manual with:
  - install steps
  - safe start/status/stop
  - Tailscale mode
  - desktop launchers
  - main experiment flow
  - troubleshooting
- Mac Helper manual with:
  - Mac setup
  - hardware expectations
  - helper configuration
  - command-line and Finder start/status/stop
  - Tailscale connection to Linux
  - playback validation
- Documentation should be bilingual where useful for the current lab context: English first, Korean support text where it materially helps handoff.

## 6. Hardware Notes

Mac playback:

- Recommended baseline is Apple Silicon MacBook Pro or M-series desktop Mac.
- Do not assume Mac built-in speakers can produce useful ultrasonic output.
- Use an external DAC/audio interface and transducer that support the required sample rate and bandwidth.
- For 192000 Hz playback, verify support in macOS Audio MIDI Setup and in Helper `/validate-playback`.

Linux recording:

- Real recording requires DAQ hardware and `uldaq` support.
- Mock mode must remain available for setup, demos, and tests without hardware.

## 7. GitHub Delivery

- Push the project to `https://github.com/xistoh162108/micloaker-web-console.git`.
- Keep generated workspace data, virtual environments, caches, logs, and local Helper config out of git.
- Push documentation and operational scripts together with app code so another operator can clone and run the system.
