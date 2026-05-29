from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def ensure_workspace(workspace: Path) -> None:
    for path in [
        workspace,
        workspace / "sessions",
        workspace / "uploads",
        workspace / ".micloaker",
    ]:
        path.mkdir(parents=True, exist_ok=True)
    if not (workspace / ".micloaker" / "config.json").exists():
        atomic_write_json(workspace / ".micloaker" / "config.json", {"created_at": now_iso(), "mac_helper_url": "", "mac_helper_token": ""})
    for name in ["sessions.jsonl", "jobs.jsonl", "app_events.jsonl", "app.log"]:
        (workspace / ".micloaker" / name).touch(exist_ok=True)


def session_dir(workspace: Path, session_id: str) -> Path:
    safe = safe_name(session_id)
    return workspace / "sessions" / safe


def ensure_session_dirs(base: Path) -> None:
    for name in ["bin", "wav", "plots", "results", "metadata", "logs", "comparisons"]:
        (base / name).mkdir(parents=True, exist_ok=True)


def safe_name(value: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "._-" else "_" for c in value.strip())
    return cleaned.strip("._") or "item"


def slugify(value: str) -> str:
    return safe_name(value.lower().replace(" ", "_"))


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True, allow_nan=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def read_json_or_default(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        data = read_json(path)
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(default)
    if not isinstance(data, dict):
        return dict(default)
    return data


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ts": now_iso(), **record}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, sort_keys=True, allow_nan=False) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    return rows


def append_log(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(f"[{now_iso()}] {message}\n")


def append_app_event(workspace: Path, event: str, **fields: Any) -> None:
    payload = {"event": event, **fields}
    append_jsonl(workspace / ".micloaker" / "app_events.jsonl", payload)
    details = " ".join(f"{key}={value}" for key, value in fields.items())
    append_log(workspace / ".micloaker" / "app.log", f"{event} {details}".strip())


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({name: row.get(name, "") for name in fieldnames})
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def relative_to_workspace(workspace: Path, path: Path) -> str:
    return str(path.resolve().relative_to(workspace.resolve()))
