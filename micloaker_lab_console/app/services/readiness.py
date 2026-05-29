from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import DEFAULT_HOST, Settings
from .daq import daq_health
from .mac_helper_client import MacHelperClient
from .recorder import recording_status
from .text_store import read_json_or_default


def lab_readiness(settings: Settings) -> dict[str, Any]:
    """Return operator-facing pre-experiment readiness checks.

    These checks are intentionally local and conservative. They do not prove
    real acoustic output or DAQ capture quality; those still require a physical
    short-run validation in the lab.
    """
    workspace = settings.workspace
    config = read_json_or_default(workspace / ".micloaker" / "config.json", {})
    mac_helper_url = str(config.get("mac_helper_url") or "").strip()
    mac_helper_token = str(config.get("mac_helper_token") or "").strip()
    daq = daq_health()
    recording = recording_status()
    helper = MacHelperClient(mac_helper_url, mac_helper_token, timeout_s=1.5).health()
    checks = [
        _bind_check(settings.host, settings.port),
        _workspace_check(workspace),
        {
            "key": "recording_lock",
            "label": "Recording Lock",
            "level": "WARN" if recording.get("active") else "PASS",
            "message": "Recording/finalization is active; do not stop the console." if recording.get("active") else "No active recording job.",
        },
        {
            "key": "daq_backend",
            "label": "DAQ Backend",
            "level": "PASS" if daq.get("ok") else "WARN",
            "message": str(daq.get("message", "DAQ health unknown.")),
            "details": daq,
        },
        {
            "key": "mac_helper",
            "label": "Mac Helper",
            "level": "PASS" if helper.get("connected") else "WARN",
            "message": _helper_message(helper),
            "details": {k: v for k, v in helper.items() if k not in {"token"}},
        },
        {
            "key": "web_shutdown",
            "label": "Web Shutdown",
            "level": "PASS" if settings.allow_web_shutdown else "WARN",
            "message": "Enabled for this trusted lab process." if settings.allow_web_shutdown else "Disabled; use scripts/console_control.py stop.",
        },
    ]
    summary = _summary(checks)
    return {
        "ok": summary["fail"] == 0,
        "summary": summary,
        "checks": checks,
        "workspace": str(workspace),
        "host": settings.host,
        "port": settings.port,
        "manual_verification_required": [
            "Run a short DAQ capture and confirm channel/range/sample count against the saved .bin.",
            "Validate/play/stop on the real macOS output device and confirm the system default output is unchanged.",
            "Measure the actual acoustic path before treating attenuation numbers as report-grade.",
        ],
    }


def _bind_check(host: str, port: int) -> dict[str, Any]:
    if host == DEFAULT_HOST:
        return {
            "key": "console_bind",
            "label": "Console Bind",
            "level": "PASS",
            "message": f"Safe localhost bind at http://{host}:{port}; use SSH tunnel or restart with --tailscale for direct Tailnet access.",
        }
    if host.startswith("100."):
        return {
            "key": "console_bind",
            "label": "Console Bind",
            "level": "PASS",
            "message": f"Explicit Tailscale bind at http://{host}:{port}.",
        }
    return {
        "key": "console_bind",
        "label": "Console Bind",
        "level": "FAIL",
        "message": f"Unexpected bind {host}:{port}; use 127.0.0.1 by default or explicit --tailscale in the lab.",
    }


def _workspace_check(workspace: Path) -> dict[str, Any]:
    required = [
        workspace,
        workspace / "sessions",
        workspace / "uploads",
        workspace / ".micloaker",
        workspace / ".micloaker" / "config.json",
        workspace / ".micloaker" / "sessions.jsonl",
        workspace / ".micloaker" / "jobs.jsonl",
        workspace / ".micloaker" / "app_events.jsonl",
        workspace / ".micloaker" / "app.log",
    ]
    missing = [str(path) for path in required if not path.exists()]
    return {
        "key": "workspace_text_files",
        "label": "Workspace Text Files",
        "level": "WARN" if missing else "PASS",
        "message": "Missing workspace files: " + ", ".join(missing) if missing else "Workspace text-file structure is present.",
        "missing": missing,
    }


def _helper_message(health: dict[str, Any]) -> str:
    if health.get("connected"):
        return str(health.get("service") or health.get("message") or "Mac Helper connected.")
    return str(health.get("message") or "Mac Helper disconnected; Linux-only workflow remains available.")


def _summary(checks: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "pass": sum(1 for check in checks if check["level"] == "PASS"),
        "warn": sum(1 for check in checks if check["level"] == "WARN"),
        "fail": sum(1 for check in checks if check["level"] == "FAIL"),
    }
