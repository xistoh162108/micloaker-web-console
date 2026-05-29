#!/usr/bin/env python3
"""Start, stop, and inspect the temporary MiCloaker Lab Console process."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage the local MiCloaker Lab Console server.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ["start", "status", "stop"]:
        p = sub.add_parser(name)
        p.add_argument("--workspace", default="workspace")
        p.add_argument("--host", default=DEFAULT_HOST)
        p.add_argument("--port", type=int, default=DEFAULT_PORT)
        p.add_argument("--tailscale", action="store_true", help="Bind to the tailscale0 IPv4 address instead of 127.0.0.1.")
    start = sub.choices["start"]
    start.add_argument("--allow-web-shutdown", action="store_true", help="Enable the /ops Stop Console button for this process.")
    start.add_argument("--reload", action="store_true", help="Start uvicorn with reload for development only.")
    sub.choices["stop"].add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()

    workspace = (ROOT / args.workspace).resolve() if not Path(args.workspace).is_absolute() else Path(args.workspace).resolve()
    host = _tailscale_ipv4() if args.tailscale else args.host
    if args.command == "status" and not args.tailscale and args.host == DEFAULT_HOST and args.port == DEFAULT_PORT:
        saved = _read_console_state(workspace)
        host = str(saved.get("host", host))
        args.port = int(saved.get("port", args.port))
    if args.command == "start":
        return start_console(workspace, host, args.port, allow_web_shutdown=args.allow_web_shutdown, reload=args.reload)
    if args.command == "stop":
        return stop_console(workspace, timeout_s=args.timeout)
    return status_console(workspace, host, args.port)


def start_console(workspace: Path, host: str, port: int, *, allow_web_shutdown: bool, reload: bool) -> int:
    workspace.mkdir(parents=True, exist_ok=True)
    micloaker = workspace / ".micloaker"
    micloaker.mkdir(parents=True, exist_ok=True)
    pid_file = micloaker / "console.pid"
    log_file = micloaker / "console_server.log"
    existing_pid = _read_pid(pid_file)
    if existing_pid and _process_alive(existing_pid):
        print(f"Console already appears to be running with PID {existing_pid}.")
        print(f"URL: http://{host}:{port}")
        return 0
    pid_file.unlink(missing_ok=True)

    env = os.environ.copy()
    env["MICLOAKER_WORKSPACE"] = str(workspace)
    env["MICLOAKER_HOST"] = host
    env["MICLOAKER_PORT"] = str(port)
    if allow_web_shutdown:
        env["MICLOAKER_ALLOW_WEB_SHUTDOWN"] = "1"
    else:
        env.pop("MICLOAKER_ALLOW_WEB_SHUTDOWN", None)
    cmd = [sys.executable, "-m", "uvicorn", "app.main:app", "--host", host, "--port", str(port)]
    if reload:
        cmd.append("--reload")
    with log_file.open("ab") as log:
        proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    pid_file.write_text(str(proc.pid) + "\n", encoding="utf-8")
    _write_console_state(micloaker / "console_state.json", host=host, port=port, workspace=workspace, log_file=log_file)
    print(f"Started MiCloaker Lab Console PID {proc.pid}")
    print(f"URL: http://{host}:{port}")
    print(f"Workspace: {workspace}")
    print(f"Log: {log_file}")
    return 0


def stop_console(workspace: Path, *, timeout_s: float) -> int:
    pid_file = workspace / ".micloaker" / "console.pid"
    pid = _read_pid(pid_file)
    if not pid:
        print(f"No console PID file found at {pid_file}.")
        return 0
    if not _process_alive(pid):
        pid_file.unlink(missing_ok=True)
        print(f"Console PID {pid} is not running; removed stale PID file.")
        return 0
    os.kill(pid, signal.SIGINT)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not _process_alive(pid):
            pid_file.unlink(missing_ok=True)
            print(f"Stopped MiCloaker Lab Console PID {pid}.")
            return 0
        time.sleep(0.2)
    os.kill(pid, signal.SIGTERM)
    print(f"Console PID {pid} did not stop after {timeout_s:g}s; sent SIGTERM.")
    return 1


def status_console(workspace: Path, host: str, port: int) -> int:
    pid_file = workspace / ".micloaker" / "console.pid"
    pid = _read_pid(pid_file)
    running = bool(pid and _process_alive(pid))
    print(f"PID file: {pid_file}")
    print(f"PID: {pid or 'none'}")
    print(f"Process: {'running' if running else 'stopped/unknown'}")
    url = f"http://{host}:{port}"
    try:
        response = httpx.get(url + "/recording/status", timeout=2.0)
        print(f"HTTP: {response.status_code} {url}")
    except Exception as exc:
        print(f"HTTP: unavailable at {url}: {exc}")
    return 0


def _read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return None


def _read_console_state(workspace: Path) -> dict[str, object]:
    try:
        return json.loads((workspace / ".micloaker" / "console_state.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        return {}


def _write_console_state(path: Path, *, host: str, port: int, workspace: Path, log_file: Path) -> None:
    state = {
        "host": host,
        "port": port,
        "url": f"http://{host}:{port}",
        "workspace": str(workspace),
        "log_file": str(log_file),
        "updated_at_epoch": time.time(),
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _tailscale_ipv4() -> str:
    try:
        output = subprocess.check_output(["ip", "-4", "-o", "addr", "show", "dev", "tailscale0"], text=True)
    except Exception as exc:
        raise SystemExit(f"tailscale0 IPv4 address not found: {exc}") from exc
    for part in output.split():
        if part.startswith("100.") and "/" in part:
            return part.split("/", 1)[0]
    raise SystemExit("tailscale0 IPv4 address not found in ip output")


if __name__ == "__main__":
    raise SystemExit(main())
