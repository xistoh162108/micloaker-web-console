# Goal — MiCloaker Lab Console Text-file v0.1/v0.2 + Optional Mac Helper

Build a stable, modular, local Linux web console for MiCloaker experiments. The console must support the complete Linux-side experiment workflow and optional Mac-side playback control.

## Core goal

The user should be able to start the service before an experiment, open it through SSH port forwarding, perform recordings and analysis, download session data, inspect logs/debug information, and stop the service afterward.

## Stability goal

The app must remain useful even when optional components are unavailable. DAQ absence, Mac Helper disconnection, Tailscale failure, and live monitor limitations must not break basic file, mock, conversion, analysis, compare, export, or log workflows.

## Storage goal

Do not use a database. Store state as ordinary text files: JSON, JSONL, CSV, Markdown, and `.log`. The workspace should be manually inspectable and recoverable by scanning files.

## Required implementation style

Use a structured Python project with FastAPI, Jinja2, vanilla JS, CSS, JSON/JSONL storage, NumPy/SciPy/Matplotlib. Avoid heavy frontend frameworks, databases, and unnecessary distributed infrastructure.

## Primary data rule

Saved `.bin` float64 voltage data is the primary quantitative source. Peak WAV is for listening. Range WAV is cross-check only. Final report metrics must be computed from saved `.bin`.

## Optional Mac Helper rule

The macOS Audio Helper is optional. It controls Mac-side WAV playback over Tailscale, but Linux-only operation must remain fully functional if it is not running.
