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
from app.services.mac_helper_client import MacHelperClient  # noqa: E402
from app.services.text_store import read_json_or_default  # noqa: E402


DB_SUFFIXES = {".db", ".duckdb", ".sqlite", ".sqlite3"}
DB_DEPENDENCIES = {"asyncpg", "databases", "duckdb", "psycopg", "psycopg2", "sqlalchemy", "tinydb"}
SKIP_DIRS = {".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv", "__pycache__"}
SMOKE_ROUTES = ["/", "/sessions", "/runs/new", "/compare", "/mac-helper", "/files", "/logs", "/ops", "/ops/readiness", "/daq/health", "/recording/status", "/live", "/live/snapshot"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Check local MiCloaker lab readiness before an experiment.")
    parser.add_argument("--check-server", action="store_true", help="Check the running console HTTP routes.")
    parser.add_argument("--server-url", default=None, help="Console URL for --check-server. Defaults to configured host/port.")
    parser.add_argument("--check-helper", action="store_true", help="Call configured Mac Helper health/devices/files/status endpoints.")
    args = parser.parse_args()

    findings: list[tuple[str, str, str]] = []
    settings = get_settings()
    _check_default_bind(findings, settings.host)
    _check_no_database(findings)
    _check_workspace(findings, settings.workspace)
    _check_daq(findings)
    helper_config = _check_helper_config(findings, settings.workspace)
    if args.check_helper:
        _check_helper_endpoints(findings, helper_config)
    server_url = None
    if args.check_server:
        server_url = args.server_url or f"http://{settings.host}:{settings.port}"
        _check_server_routes(findings, server_url)

    _print_report(findings, settings.workspace, settings.host, settings.port, server_url=server_url)
    return 1 if any(level == "FAIL" for level, _, _ in findings) else 0


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


def _check_daq(findings: list[tuple[str, str, str]]) -> None:
    health = daq_health()
    if health.get("ok"):
        findings.append(("PASS", "daq_backend", str(health.get("message", "DAQ backend appears available."))))
    else:
        findings.append(("WARN", "daq_backend", str(health.get("message", "DAQ unavailable; mock mode remains available."))))


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
        for route in SMOKE_ROUTES:
            try:
                response = client.get(server_url.rstrip("/") + route)
            except Exception as exc:
                failed.append(f"{route}: {exc}")
                continue
            if response.status_code != 200:
                failed.append(f"{route}: HTTP {response.status_code}")
    if failed:
        findings.append(("FAIL", "server_routes", "Route smoke failures: " + "; ".join(failed)))
    else:
        findings.append(("PASS", "server_routes", f"All smoke routes returned 200 at {server_url}."))


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


def _print_report(findings: list[tuple[str, str, str]], workspace: Path, host: str, port: int, *, server_url: str | None) -> None:
    print("MiCloaker Lab Readiness Check")
    print(f"workspace: {workspace}")
    print(f"configured console: http://{host}:{port}")
    if server_url:
        print(f"route check target: {server_url}")
    print()
    for level, key, message in findings:
        print(f"{level}: {key}: {message}")
    print()
    print("Manual lab verification still required:")
    print("- Protocol: follow ../docs/HARDWARE_VALIDATION_PROTOCOL.md before real report-grade experiments.")
    print("- Actual DAQ: run a short DAQ capture and confirm sample rate, channel, range, and saved .bin sample count.")
    print("- Mac Helper: validate/play/stop on the real macOS output device and confirm the system default output is unchanged.")
    print("- Play & Record: run a short synchronized DAQ trial when Mac playback and Linux recording are both required.")
    print("- Attenuation: record one finalized uj0/uj1 validation pair and inspect BIN-primary comparison output.")
    print("- Legacy parity: compare a known historical .bin against legacy notebook outputs if exact historical numeric parity is required.")


if __name__ == "__main__":
    raise SystemExit(main())
