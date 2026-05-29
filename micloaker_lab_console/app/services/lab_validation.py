from __future__ import annotations

from pathlib import Path
from typing import Any

from .text_store import append_app_event, append_jsonl, atomic_write_text, now_iso, read_jsonl


VALIDATION_GATES = {
    "daq_smoke": "Linux DAQ smoke capture",
    "mac_playback": "Mac Helper playback validation",
    "play_and_record": "End-to-end play and record trial",
    "attenuation_pair": "uj0/uj1 attenuation pair check",
    "legacy_parity": "Legacy notebook numeric parity check",
}
VALIDATION_STATUSES = {"pass", "warn", "fail"}


def validation_paths(workspace: Path) -> dict[str, Path]:
    root = workspace / ".micloaker"
    return {
        "jsonl": root / "hardware_validation.jsonl",
        "report": root / "hardware_validation_report.md",
    }


def list_validation_records(workspace: Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    records = read_jsonl(validation_paths(workspace)["jsonl"])
    records = sorted(records, key=lambda row: str(row.get("ts", "")), reverse=True)
    return records[:limit] if limit else records


def record_lab_validation(
    workspace: Path,
    *,
    gate: str,
    status: str,
    operator: str = "",
    session_id: str = "",
    run_id: str = "",
    helper_url: str = "",
    evidence: str = "",
    notes: str = "",
) -> dict[str, Any]:
    """Persist a lab-side validation record as JSONL and Markdown evidence.

    This intentionally records operator evidence only. It does not claim that
    hardware passed unless the operator explicitly records a pass result.
    """
    gate = gate.strip()
    status = status.strip().lower()
    if gate not in VALIDATION_GATES:
        raise ValueError(f"unknown validation gate: {gate}")
    if status not in VALIDATION_STATUSES:
        raise ValueError(f"unknown validation status: {status}")
    record = {
        "event": "hardware_validation_recorded",
        "recorded_at": now_iso(),
        "gate": gate,
        "gate_label": VALIDATION_GATES[gate],
        "status": status,
        "operator": operator.strip(),
        "session_id": session_id.strip(),
        "run_id": run_id.strip(),
        "helper_url": helper_url.strip(),
        "evidence": evidence.strip(),
        "notes": notes.strip(),
    }
    append_jsonl(validation_paths(workspace)["jsonl"], record)
    append_app_event(workspace, "hardware_validation_recorded", gate=gate, status=status, run_id=record["run_id"])
    _write_validation_report(workspace)
    return record


def validation_summary(workspace: Path) -> dict[str, Any]:
    records = list_validation_records(workspace)
    latest_by_gate: dict[str, dict[str, Any]] = {}
    for record in records:
        gate = str(record.get("gate", ""))
        if gate and gate not in latest_by_gate:
            latest_by_gate[gate] = record
    return {
        "record_count": len(records),
        "latest_by_gate": latest_by_gate,
        "latest": records[:5],
        "report_path": str(validation_paths(workspace)["report"]),
    }


def _write_validation_report(workspace: Path) -> None:
    records = list_validation_records(workspace)
    lines = [
        "# MiCloaker Hardware Validation Records",
        "",
        "These records are operator-entered evidence for the physical lab gates in `docs/HARDWARE_VALIDATION_PROTOCOL.md`.",
        "",
        "| Time | Gate | Status | Session | Run | Operator | Evidence | Notes |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in records:
        lines.append(
            "| {time} | {gate} | {status} | {session} | {run} | {operator} | {evidence} | {notes} |".format(
                time=_md(row.get("recorded_at") or row.get("ts")),
                gate=_md(row.get("gate_label") or row.get("gate")),
                status=_md(row.get("status")),
                session=_md(row.get("session_id")),
                run=_md(row.get("run_id")),
                operator=_md(row.get("operator")),
                evidence=_md(row.get("evidence")),
                notes=_md(row.get("notes")),
            )
        )
    lines.append("")
    atomic_write_text(validation_paths(workspace)["report"], "\n".join(lines))


def _md(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ").strip()
