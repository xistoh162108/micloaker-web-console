#!/usr/bin/env python3
"""Start, stop, and inspect the optional macOS Audio Helper."""

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


ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage the optional MiCloaker macOS Audio Helper.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ["start", "status", "stop"]:
        p = sub.add_parser(name)
        p.add_argument("--config", default="config.json")
    sub.choices["stop"].add_argument("--timeout", type=float, default=8.0)
    args = parser.parse_args()
    config_path = (ROOT / args.config).resolve() if not Path(args.config).is_absolute() else Path(args.config).resolve()
    if args.command == "start":
        return start_helper(config_path)
    if args.command == "stop":
        return stop_helper(config_path, timeout_s=args.timeout)
    return status_helper(config_path)


def start_helper(config_path: Path) -> int:
    if not config_path.exists():
        example = ROOT / "config.example.json"
        if example.exists():
            config_path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"Created {config_path} from config.example.json. Edit wav_root before real playback.")
        else:
            print(f"Missing config: {config_path}")
            return 1
    cfg = _read_config(config_path)
    pid_file = ROOT / "helper.pid"
    log_file = ROOT / "helper.log"
    existing_pid = _read_pid(pid_file)
    if existing_pid and _process_alive(existing_pid):
        print(f"Mac Helper already appears to be running with PID {existing_pid}.")
        print(f"URL: http://{cfg.get('host', '0.0.0.0')}:{cfg.get('port', 5050)}")
        return 0
    pid_file.unlink(missing_ok=True)
    cmd = [sys.executable, "helper.py", "--config", str(config_path)]
    with log_file.open("ab") as log:
        proc = subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    pid_file.write_text(str(proc.pid) + "\n", encoding="utf-8")
    print(f"Started MiCloaker Mac Helper PID {proc.pid}")
    print(f"URL: http://{cfg.get('host', '0.0.0.0')}:{cfg.get('port', 5050)}")
    print(f"Log: {log_file}")
    return 0


def stop_helper(config_path: Path, *, timeout_s: float) -> int:
    pid_file = ROOT / "helper.pid"
    pid = _read_pid(pid_file)
    if not pid:
        print(f"No Helper PID file found at {pid_file}.")
        return 0
    if not _process_alive(pid):
        pid_file.unlink(missing_ok=True)
        print(f"Helper PID {pid} is not running; removed stale PID file.")
        return 0
    try:
        cfg = _read_config(config_path)
        httpx.post(f"http://127.0.0.1:{int(cfg.get('port', 5050))}/stop", timeout=1.0)
    except Exception:
        pass
    os.kill(pid, signal.SIGINT)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not _process_alive(pid):
            pid_file.unlink(missing_ok=True)
            print(f"Stopped MiCloaker Mac Helper PID {pid}.")
            return 0
        time.sleep(0.2)
    os.kill(pid, signal.SIGTERM)
    print(f"Helper PID {pid} did not stop after {timeout_s:g}s; sent SIGTERM.")
    return 1


def status_helper(config_path: Path) -> int:
    cfg = _read_config(config_path) if config_path.exists() else {"host": "0.0.0.0", "port": 5050}
    pid = _read_pid(ROOT / "helper.pid")
    print(f"PID: {pid or 'none'}")
    print(f"Process: {'running' if pid and _process_alive(pid) else 'stopped/unknown'}")
    url = f"http://127.0.0.1:{int(cfg.get('port', 5050))}"
    try:
        response = httpx.get(url + "/health", timeout=2.0)
        print(f"HTTP: {response.status_code} {url}")
        print(response.text[:500])
    except Exception as exc:
        print(f"HTTP: unavailable at {url}: {exc}")
    return 0


def _read_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return None


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
