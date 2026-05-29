#!/usr/bin/env python3
"""Pre-experiment readiness check for the local MiCloaker Lab Console."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import DEFAULT_HOST, DEFAULT_PORT, get_settings  # noqa: E402
from app.services.daq import daq_health  # noqa: E402
from app.services.lab_validation import VALIDATION_GATES, VALIDATION_STATUSES, ensure_validation_artifacts, record_lab_validation, validation_evidence_template, validation_paths, validation_plan, validation_summary  # noqa: E402
from app.services.mac_helper_client import MacHelperClient  # noqa: E402
from app.services.readiness import write_readiness_artifacts  # noqa: E402
from app.services.text_store import atomic_write_text, read_json_or_default  # noqa: E402


DB_SUFFIXES = {".db", ".duckdb", ".sqlite", ".sqlite3"}
DB_DEPENDENCIES = {"asyncpg", "databases", "duckdb", "psycopg", "psycopg2", "sqlalchemy", "tinydb"}
SKIP_DIRS = {".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv", "__pycache__"}
VALIDATION_ROUTES = ["/", "/sessions", "/runs/new", "/compare", "/mac-helper", "/files", "/logs", "/ops", "/ops/readiness", "/daq/health", "/recording/status", "/live", "/live/snapshot"]
VALIDATION_ASSETS = {
    "/static/css/app.css": ["DaisyUI component vocabulary", "content-visibility: auto"],
    "/static/js/live.js": ["requestAnimationFrame(renderCharts)", "cachedSpectrogramImage"],
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Check local MiCloaker lab readiness before an experiment.")
    parser.add_argument("--check-server", action="store_true", help="Check the running console HTTP routes.")
    parser.add_argument("--server-url", default=None, help="Console URL for --check-server. Defaults to configured host/port.")
    parser.add_argument("--check-helper", action="store_true", help="Call configured Mac Helper health/devices/files/status endpoints.")
    parser.add_argument("--write-report", action="store_true", help="Write lab_readiness_report.json and .md under workspace/.micloaker.")
    parser.add_argument("--validation-plan", action="store_true", help="Print the ordered physical validation gate plan and recording commands.")
    parser.add_argument("--write-evidence-template", choices=sorted(VALIDATION_GATES), help="Write an operator-fillable evidence template for the selected validation gate.")
    parser.add_argument("--evidence-template-file", default="evidence.txt", help="Output path for --write-evidence-template.")
    parser.add_argument("--overwrite-evidence-template", action="store_true", help="Allow --write-evidence-template to replace an existing file.")
    parser.add_argument("--record-gate", choices=sorted(VALIDATION_GATES), help="Append a hardware validation record for this gate before checking readiness.")
    parser.add_argument("--record-status", choices=sorted(VALIDATION_STATUSES), help="Status for --record-gate.")
    parser.add_argument("--record-operator", default="", help="Operator name or initials for --record-gate.")
    parser.add_argument("--record-session-id", default="", help="Session ID for --record-gate.")
    parser.add_argument("--record-run-id", default="", help="Run ID for --record-gate.")
    parser.add_argument("--record-helper-url", default="", help="Mac Helper URL for --record-gate.")
    parser.add_argument("--record-evidence", default="", help="Evidence text for --record-gate.")
    parser.add_argument("--record-evidence-file", default="", help="Read evidence text for --record-gate from a UTF-8 text file.")
    parser.add_argument("--record-notes", default="", help="Notes for --record-gate.")
    args = parser.parse_args()

    findings: list[tuple[str, str, str]] = []
    settings = get_settings()
    if args.record_gate or args.record_status:
        _record_validation_from_args(parser, args, settings.workspace)
    if args.validation_plan:
        ensure_validation_artifacts(settings.workspace)
        print(validation_plan(settings.workspace))
        return 0
    if args.write_evidence_template:
        _write_evidence_template_from_args(parser, args)
        return 0
    _check_default_bind(findings, settings.host)
    _check_no_database(findings)
    _check_workspace(findings, settings.workspace)
    _check_validation_records(findings, settings.workspace)
    _check_daq(findings)
    helper_config = _check_helper_config(findings, settings.workspace)
    if args.check_helper:
        _check_helper_endpoints(findings, helper_config)
    server_url = None
    if args.check_server:
        server_url = args.server_url or f"http://{settings.host}:{settings.port}"
        _check_server_routes(findings, server_url)

    _print_report(findings, settings.workspace, settings.host, settings.port, server_url=server_url)
    if args.write_report:
        paths = write_readiness_artifacts(settings, extra_checks=_readiness_checks_from_findings(findings))
        print(f"readiness reports written: {paths['json']} and {paths['report']}")
    return 1 if any(level == "FAIL" for level, _, _ in findings) else 0


def _record_validation_from_args(parser: argparse.ArgumentParser, args: argparse.Namespace, workspace: Path) -> None:
    if not args.record_gate:
        parser.error("--record-status requires --record-gate")
    if not args.record_status:
        parser.error("--record-gate requires --record-status")
    evidence = _record_evidence_text(parser, args)
    if args.record_status in {"pass", "warn", "fail"} and not evidence.strip():
        parser.error("--record-evidence or --record-evidence-file is required for pass/warn/fail validation records")
    record = record_lab_validation(
        workspace,
        gate=args.record_gate,
        status=args.record_status,
        operator=args.record_operator,
        session_id=args.record_session_id,
        run_id=args.record_run_id,
        helper_url=args.record_helper_url,
        evidence=evidence,
        notes=args.record_notes,
    )
    paths = validation_paths(workspace)
    print(
        "validation record saved: {gate} status={status} jsonl={jsonl} report={report}".format(
            gate=record["gate"],
            status=record["status"],
            jsonl=paths["jsonl"],
            report=paths["report"],
        )
    )


def _write_evidence_template_from_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    path = Path(args.evidence_template_file).expanduser()
    if path.exists() and not args.overwrite_evidence_template:
        parser.error(f"--evidence-template-file already exists: {path}; pass --overwrite-evidence-template to replace it")
    atomic_write_text(path, validation_evidence_template(args.write_evidence_template))
    print(f"evidence template written: gate={args.write_evidence_template} path={path}")


def _record_evidence_text(parser: argparse.ArgumentParser, args: argparse.Namespace) -> str:
    if args.record_evidence and args.record_evidence_file:
        parser.error("use either --record-evidence or --record-evidence-file, not both")
    if not args.record_evidence_file:
        return str(args.record_evidence or "")
    path = Path(args.record_evidence_file).expanduser()
    try:
        if not path.is_file():
            parser.error(f"--record-evidence-file is not a file: {path}")
        return path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        parser.error(f"could not read --record-evidence-file {path}: {exc}")
    return ""


def _check_default_bind(findings: list[tuple[str, str, str]], host: str) -> None:
    if host == DEFAULT_HOST:
        findings.append(("PASS", "console_bind", f"Configured host is {DEFAULT_HOST}."))
    else:
        findings.append(("FAIL", "console_bind", f"Configured host is {host!r}; use {DEFAULT_HOST!r} for SSH-tunneled lab runs."))


def _check_no_database(findings: list[tuple[str, str, str]]) -> None:
    db_files = []
    for path in ROOT.rglob("*"):
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        if path.is_file() and path.suffix.lower() in DB_SUFFIXES:
            db_files.append(path.relative_to(ROOT).as_posix())
    forbidden_deps = sorted(_requirement_names(ROOT / "requirements.txt") & DB_DEPENDENCIES)
    if db_files:
        findings.append(("FAIL", "no_database_files", "Database-like files found: " + ", ".join(db_files)))
    else:
        findings.append(("PASS", "no_database_files", "No database-like files found in the project tree."))
    if forbidden_deps:
        findings.append(("FAIL", "no_database_dependencies", "Forbidden database dependencies found: " + ", ".join(forbidden_deps)))
    else:
        findings.append(("PASS", "no_database_dependencies", "No database dependencies found in requirements.txt."))


def _check_workspace(findings: list[tuple[str, str, str]], workspace: Path) -> None:
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
    missing = [path for path in required if not path.exists()]
    if missing:
        rel = [str(path) for path in missing]
        findings.append(("WARN", "workspace_initialized", "Workspace is not fully initialized yet: " + ", ".join(rel)))
    else:
        findings.append(("PASS", "workspace_initialized", f"Workspace text-file structure exists at {workspace}."))


def _check_validation_records(findings: list[tuple[str, str, str]], workspace: Path) -> None:
    summary = validation_summary(workspace)
    count = summary["record_count"]
    counts = summary.get("status_counts", {})
    if not count:
        findings.append(("WARN", "hardware_validation_records", "No physical validation records saved yet; record evidence in /ops before report-grade hardware experiments."))
        return
    level = "FAIL" if counts.get("fail", 0) else "WARN" if counts.get("warn", 0) or counts.get("missing", 0) else "PASS"
    findings.append(
        (
            level,
            "hardware_validation_records",
            (
                f"{count} physical validation record(s): "
                f"{counts.get('pass', 0)} pass, {counts.get('na', 0)} not applicable, "
                f"{counts.get('warn', 0)} warn, {counts.get('fail', 0)} fail, "
                f"{counts.get('missing', 0)} missing gate(s)."
            ),
        )
    )
    for gate in summary.get("gate_status", []):
        if gate.get("status") in {"fail", "warn", "missing"}:
            findings.append((level if gate.get("status") == "fail" else "WARN", f"validation_{gate.get('gate')}", f"{gate.get('gate_label')}: {gate.get('status')}"))


def _check_daq(findings: list[tuple[str, str, str]]) -> None:
    health = daq_health()
    if health.get("ok"):
        findings.append(("PASS", "daq_backend", str(health.get("message", "DAQ backend appears available."))))
    else:
        findings.append(("WARN", "daq_backend", str(health.get("message", "DAQ unavailable; offline developer validation remains available."))))


def _check_helper_config(findings: list[tuple[str, str, str]], workspace: Path) -> dict[str, Any]:
    config_path = workspace / ".micloaker" / "config.json"
    config = read_json_or_default(config_path, {})
    helper_url = str(config.get("mac_helper_url") or "").strip()
    helper_token = str(config.get("mac_helper_token") or "").strip()
    if helper_url:
        token_note = "token configured" if helper_token else "no token configured"
        findings.append(("PASS", "mac_helper_config", f"Manual Helper URL configured: {helper_url} ({token_note})."))
    else:
        findings.append(("WARN", "mac_helper_config", "Mac Helper URL is not configured; Linux-only recording/analysis remains available."))
    return {"url": helper_url, "token": helper_token}


def _check_helper_endpoints(findings: list[tuple[str, str, str]], config: dict[str, Any]) -> None:
    if not config["url"]:
        findings.append(("WARN", "mac_helper_endpoints", "Skipped Helper endpoint checks because no Helper URL is configured."))
        return
    client = MacHelperClient(helper_url=config["url"], helper_token=config["token"], timeout_s=2.0)
    health = client.health()
    if not health.get("ok"):
        findings.append(("WARN", "mac_helper_health", _structured_message(health)))
        return
    findings.append(("PASS", "mac_helper_health", _structured_message(health)))
    for name, call in [("devices", client.devices), ("files", client.files), ("status", client.status)]:
        result = call()
        level = "PASS" if result.get("ok") else "WARN"
        findings.append((level, f"mac_helper_{name}", _structured_message(result)))


def _check_server_routes(findings: list[tuple[str, str, str]], server_url: str) -> None:
    failed = []
    with httpx.Client(timeout=3.0, follow_redirects=False) as client:
        for route in VALIDATION_ROUTES:
            try:
                response = client.get(server_url.rstrip("/") + route)
            except Exception as exc:
                failed.append(f"{route}: {exc}")
                continue
            if response.status_code != 200:
                failed.append(f"{route}: HTTP {response.status_code}")
        for asset, required_terms in VALIDATION_ASSETS.items():
            try:
                response = client.get(server_url.rstrip("/") + asset)
            except Exception as exc:
                failed.append(f"{asset}: {exc}")
                continue
            if response.status_code != 200:
                failed.append(f"{asset}: HTTP {response.status_code}")
                continue
            missing_terms = [term for term in required_terms if term not in response.text]
            if missing_terms:
                failed.append(f"{asset}: missing {', '.join(missing_terms)}")
    if failed:
        findings.append(("FAIL", "server_routes", "Route validation failures: " + "; ".join(failed)))
    else:
        findings.append(("PASS", "server_routes", f"All validation routes and UI assets returned expected content at {server_url}."))


def _requirement_names(path: Path) -> set[str]:
    if not path.exists():
        return set()
    names: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip().lower()
        if not line:
            continue
        for separator in ("==", ">=", "<=", "~=", "!=", ">", "<", "["):
            line = line.split(separator, 1)[0]
        names.add(line.strip())
    return names


def _structured_message(data: dict[str, Any]) -> str:
    if data.get("message"):
        return str(data["message"])
    if data.get("error_code"):
        return f"{data['error_code']}: {data.get('suggestion', '')}".strip()
    if data.get("service"):
        return f"{data.get('service')} on {data.get('hostname', 'unknown host')}"
    return "ok" if data.get("ok") else str(data)


def _readiness_checks_from_findings(findings: list[tuple[str, str, str]]) -> list[dict[str, str]]:
    return [
        {
            "key": f"cli_{key}",
            "label": "CLI " + key.replace("_", " ").title(),
            "level": level,
            "message": message,
        }
        for level, key, message in findings
    ]


def _print_report(findings: list[tuple[str, str, str]], workspace: Path, host: str, port: int, *, server_url: str | None) -> None:
    print("MiCloaker Lab Readiness Check")
    print(f"workspace: {workspace}")
    print(f"configured console: http://{host}:{port}")
    if server_url:
        print(f"route check target: {server_url}")
    print()
    for level, key, message in findings:
        print(f"{level}: {key}: {message}")
    _print_validation_gate_status(workspace)
    print()
    print("Manual lab verification still required:")
    print("- Protocol: follow ../docs/HARDWARE_VALIDATION_PROTOCOL.md before real report-grade experiments.")
    print("- Actual DAQ: run a short DAQ capture and confirm sample rate, channel, range, and saved .bin sample count.")
    print("- Mac Helper: validate/play/stop on the real macOS output device and confirm the system default output is unchanged.")
    print("- Play & Record: run a short synchronized DAQ trial when Mac playback and Linux recording are both required.")
    print("- Attenuation: record one finalized uj0/uj1 validation pair and inspect BIN-primary comparison output.")
    print("- Legacy parity: compare a known historical .bin against legacy notebook outputs if exact historical numeric parity is required.")


def _print_validation_gate_status(workspace: Path) -> None:
    summary = validation_summary(workspace)
    print()
    print("Hardware validation gate status:")
    for gate in summary.get("gate_status", []):
        action = gate.get("action") or {}
        action_label = action.get("label") or "Open /ops"
        action_href = action.get("href") or "/ops"
        missing = gate.get("checklist_missing") or []
        completeness = "complete" if gate.get("checklist_complete") else "missing checklist: " + ", ".join(str(item) for item in missing)
        print(
            "- {label}: {status}; {completeness}; next: {action_label} ({action_href})".format(
                label=gate.get("gate_label") or gate.get("gate"),
                status=gate.get("status"),
                completeness=completeness,
                action_label=action_label,
                action_href=action_href,
            )
        )


if __name__ == "__main__":
    raise SystemExit(main())
