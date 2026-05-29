from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import DEFAULT_HOST, Settings
from .daq import daq_health
from .lab_validation import validation_summary
from .mac_helper_client import MacHelperClient
from .recorder import recording_status
from .text_store import atomic_write_json, atomic_write_text, now_iso, read_json_or_default


def readiness_paths(workspace: Path) -> dict[str, Path]:
    root = workspace / ".micloaker"
    return {
        "json": root / "lab_readiness_report.json",
        "report": root / "lab_readiness_report.md",
    }


def lab_readiness(settings: Settings, *, extra_checks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
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
    validation = validation_summary(workspace)
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
        {
            "key": "hardware_validation_records",
            "label": "Hardware Validation Records",
            "level": _validation_level(validation),
            "message": _validation_message(validation),
            "details": validation,
        },
    ]
    if extra_checks:
        checks.extend(extra_checks)
    summary = _summary(checks)
    return {
        "generated_at": now_iso(),
        "ok": summary["fail"] == 0,
        "summary": summary,
        "checks": checks,
        "workspace": str(workspace),
        "host": settings.host,
        "port": settings.port,
        "manual_verification_required": [
            "Follow ../docs/HARDWARE_VALIDATION_PROTOCOL.md before real report-grade experiments.",
            "Run a short DAQ capture and confirm channel/range/sample count against the saved .bin.",
            "Validate/play/stop on the real macOS output device and confirm the system default output is unchanged.",
            "Run a short play-and-record DAQ trial when synchronized Mac playback and Linux recording are required.",
            "Record one finalized uj0/uj1 validation pair and inspect BIN-primary attenuation output.",
            "Measure the actual acoustic path before treating attenuation numbers as report-grade.",
        ],
    }


def write_readiness_artifacts(settings: Settings, *, extra_checks: list[dict[str, Any]] | None = None) -> dict[str, Path]:
    """Persist a point-in-time readiness snapshot for lab validation evidence."""
    snapshot = lab_readiness(settings, extra_checks=extra_checks)
    paths = readiness_paths(settings.workspace)
    paths["json"].parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(paths["json"], snapshot)
    atomic_write_text(paths["report"], _readiness_markdown(snapshot))
    return paths


def _readiness_markdown(snapshot: dict[str, Any]) -> str:
    lines = [
        "# MiCloaker Lab Readiness Report",
        "",
        f"Generated at: {snapshot.get('generated_at', '')}",
        f"Workspace: `{snapshot.get('workspace', '')}`",
        f"Console: `{snapshot.get('host', '')}:{snapshot.get('port', '')}`",
        "",
        "## Summary",
        "",
        f"- Pass: {snapshot.get('summary', {}).get('pass', 0)}",
        f"- Warn: {snapshot.get('summary', {}).get('warn', 0)}",
        f"- Fail: {snapshot.get('summary', {}).get('fail', 0)}",
        f"- OK: {snapshot.get('ok')}",
        "",
        "## Checks",
        "",
        "| Check | Level | Message |",
        "|---|---|---|",
    ]
    for check in snapshot.get("checks", []):
        lines.append(f"| {_md(check.get('label') or check.get('key'))} | {_md(check.get('level'))} | {_md(check.get('message'))} |")
    validation = _validation_details(snapshot)
    if validation:
        lines.extend([
            "",
            "## Hardware Validation Gate Status",
            "",
            "| Gate | Status | Next action | Session | Run | Checklist fields | Evidence hint | Record command |",
            "|---|---|---|---|---|---|---|---|",
        ])
        for gate in validation.get("gate_status", []):
            action = gate.get("action") or {}
            action_text = str(action.get("label") or "")
            if action.get("href"):
                action_text = f"{action_text} ({action.get('href')})"
            gate_key = str(gate.get("gate") or "")
            record_command = (
                "scripts/lab_readiness_check.py --record-gate {gate} --record-status <pass|warn|fail|na> "
                "--record-evidence-file evidence.txt"
            ).format(gate=gate_key)
            lines.append(
                "| {gate} | {status} | {action} | {session} | {run} | {checklist} | {hint} | `{command}` |".format(
                    gate=_md(gate.get("gate_label") or gate.get("gate")),
                    status=_md(gate.get("status")),
                    action=_md(action_text),
                    session=_md(gate.get("session_id")),
                    run=_md(gate.get("run_id")),
                    checklist=_md(", ".join(str(item) for item in gate.get("evidence_checklist", []))),
                    hint=_md(gate.get("evidence_hint")),
                    command=_md(record_command),
                )
            )
    lines.extend([
        "",
        "## Manual Verification Required",
        "",
    ])
    for item in snapshot.get("manual_verification_required", []):
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def _validation_details(snapshot: dict[str, Any]) -> dict[str, Any]:
    for check in snapshot.get("checks", []):
        if check.get("key") == "hardware_validation_records":
            details = check.get("details")
            return details if isinstance(details, dict) else {}
    return {}


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


def _validation_level(validation: dict[str, Any]) -> str:
    counts = validation.get("status_counts", {})
    if counts.get("fail", 0):
        return "FAIL"
    if counts.get("warn", 0) or counts.get("missing", 0):
        return "WARN"
    return "PASS"


def _validation_message(validation: dict[str, Any]) -> str:
    counts = validation.get("status_counts", {})
    total = validation.get("record_count", 0)
    if not total:
        return "No physical validation records saved yet; use /ops before report-grade hardware experiments."
    return (
        f"{total} physical validation record(s): "
        f"{counts.get('pass', 0)} pass, {counts.get('na', 0)} not applicable, {counts.get('warn', 0)} warn, "
        f"{counts.get('fail', 0)} fail, {counts.get('missing', 0)} missing gate(s)."
    )


def _summary(checks: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "pass": sum(1 for check in checks if check["level"] == "PASS"),
        "warn": sum(1 for check in checks if check["level"] == "WARN"),
        "fail": sum(1 for check in checks if check["level"] == "FAIL"),
    }


def _md(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ").strip()
