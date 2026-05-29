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
VALIDATION_GATE_EVIDENCE = {
    "daq_smoke": "Record session/run IDs, DAQ channel/range/input mode, requested and actual sample rate, expected vs written sample count, raw .bin path, and run log/plot status.",
    "mac_playback": "Record Helper URL, selected device_id, WAV path, sample rate, channels, validation result, play/stop result, and confirmation that macOS default output did not change.",
    "play_and_record": "Record validation run ID, Helper validation result, Play & Record mode, DAQ raw .bin path, finalization result, peak/range WAV presence, and run log status.",
    "attenuation_pair": "Record uj0/uj1 run IDs, compare JSON/CSV path, source=bin, band, attenuation dB, mismatch warnings, and PSD/bar plot status.",
    "legacy_parity": "Record legacy .bin fixture path, notebook/reference output, current metrics/plots, tolerance, and pass/not-applicable decision.",
}
VALIDATION_GATE_CHECKLIST = {
    "daq_smoke": ["session_id", "run_id", "DAQ channel/range/input mode", "requested and actual sample rate", "expected vs written sample count", "raw .bin path", "run log/plot status"],
    "mac_playback": ["Helper URL", "selected device_id", "WAV relative path", "sample rate/channels/gain", "validate-playback result", "play/stop result", "macOS default output unchanged"],
    "play_and_record": ["validation run_id", "Helper validation result", "Play & Record mode", "DAQ raw .bin path", "finalization result", "peak/range WAV presence", "run log status"],
    "attenuation_pair": ["uj0 run_id", "uj1 run_id", "compare JSON/CSV path", "source=bin", "band and attenuation dB", "mismatch warnings", "PSD/bar plot status"],
    "legacy_parity": ["legacy .bin fixture path", "notebook/reference output", "current metrics/plots", "tolerance", "pass/not-applicable decision"],
}
VALIDATION_GATE_ACTIONS = {
    "daq_smoke": {"label": "Create DAQ validation run", "href": "/runs/new"},
    "mac_playback": {"label": "Open Mac Helper", "href": "/mac-helper"},
    "play_and_record": {"label": "Open recent runs", "href": "/sessions"},
    "attenuation_pair": {"label": "Open Compare", "href": "/compare"},
    "legacy_parity": {"label": "Open files", "href": "/files"},
}
VALIDATION_STATUSES = {"pass", "warn", "fail", "na"}


def validation_paths(workspace: Path) -> dict[str, Path]:
    root = workspace / ".micloaker"
    return {
        "jsonl": root / "hardware_validation.jsonl",
        "report": root / "hardware_validation_report.md",
        "plan": root / "hardware_validation_plan.txt",
    }


def list_validation_records(workspace: Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    records = [
        {**record, "_order": index}
        for index, record in enumerate(read_jsonl(validation_paths(workspace)["jsonl"]))
    ]
    records = sorted(records, key=lambda row: (str(row.get("ts", "")), int(row.get("_order", 0))), reverse=True)
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
    gate_status = []
    for gate, label in VALIDATION_GATES.items():
        latest = latest_by_gate.get(gate)
        status = str(latest.get("status")) if latest else "missing"
        gate_status.append(
            {
                "gate": gate,
                "gate_label": label,
                "status": status,
                "evidence_hint": VALIDATION_GATE_EVIDENCE[gate],
                "evidence_checklist": VALIDATION_GATE_CHECKLIST[gate],
                "action": VALIDATION_GATE_ACTIONS[gate],
                "recorded_at": latest.get("recorded_at") or latest.get("ts") if latest else "",
                "session_id": latest.get("session_id", "") if latest else "",
                "run_id": latest.get("run_id", "") if latest else "",
                "evidence": latest.get("evidence", "") if latest else "",
            }
        )
    return {
        "record_count": len(records),
        "evidence_hints": VALIDATION_GATE_EVIDENCE,
        "evidence_checklists": VALIDATION_GATE_CHECKLIST,
        "actions": VALIDATION_GATE_ACTIONS,
        "latest_by_gate": latest_by_gate,
        "gate_status": gate_status,
        "status_counts": {
            "pass": sum(1 for row in gate_status if row["status"] == "pass"),
            "na": sum(1 for row in gate_status if row["status"] == "na"),
            "warn": sum(1 for row in gate_status if row["status"] == "warn"),
            "fail": sum(1 for row in gate_status if row["status"] == "fail"),
            "missing": sum(1 for row in gate_status if row["status"] == "missing"),
        },
        "latest": records[:5],
        "report_path": str(validation_paths(workspace)["report"]),
        "plan_path": str(validation_paths(workspace)["plan"]),
    }


def validation_plan(workspace: Path) -> str:
    """Return a terminal-friendly physical validation plan for lab operators."""
    summary = validation_summary(workspace)
    lines = [
        "MiCloaker Physical Validation Plan",
        "",
        "Complete these gates before treating real hardware results as report-grade.",
        "Use /ops for web entry, or the shown CLI command when operating from a terminal.",
        "",
    ]
    for index, gate in enumerate(summary.get("gate_status", []), start=1):
        action = gate.get("action") or {}
        checklist = gate.get("evidence_checklist") or []
        gate_key = gate.get("gate")
        lines.extend(
            [
                f"{index}. {gate.get('gate_label') or gate_key}",
                f"   current_status: {gate.get('status')}",
                f"   next_action: {action.get('label', 'Open /ops')} {action.get('href', '/ops')}",
                f"   checklist: {', '.join(str(item) for item in checklist)}",
                f"   evidence_hint: {gate.get('evidence_hint', '')}",
                "   record_command:",
                (
                    "     scripts/lab_readiness_check.py --record-gate {gate} --record-status <pass|warn|fail|na> "
                    "--record-evidence-file evidence.txt"
                ).format(gate=gate_key),
                "",
            ]
        )
    lines.extend(
        [
            "Evidence files:",
            f"- JSONL: {validation_paths(workspace)['jsonl']}",
            f"- Markdown: {validation_paths(workspace)['report']}",
            f"- Plan: {validation_paths(workspace)['plan']}",
            "",
        ]
    )
    return "\n".join(lines)


def validation_evidence_template(gate: str) -> str:
    """Return an operator-fillable evidence note template for one validation gate."""
    if gate not in VALIDATION_GATES:
        raise ValueError(f"unknown validation gate: {gate}")
    lines = [
        f"# Evidence Template: {VALIDATION_GATES[gate]}",
        "",
        f"gate: {gate}",
        "status: <pass|warn|fail|na>",
        "operator:",
        "session_id:",
        "run_id:",
        "helper_url:",
        "",
        "## Checklist",
    ]
    for item in VALIDATION_GATE_CHECKLIST[gate]:
        lines.append(f"- {item}: ")
    lines.extend(
        [
            "",
            "## Evidence Hint",
            VALIDATION_GATE_EVIDENCE[gate],
            "",
            "## Record Command",
            (
                "scripts/lab_readiness_check.py --record-gate {gate} --record-status <pass|warn|fail|na> "
                "--record-evidence-file evidence.txt"
            ).format(gate=gate),
            "",
        ]
    )
    return "\n".join(lines)


def ensure_validation_artifacts(workspace: Path) -> dict[str, Path]:
    paths = validation_paths(workspace)
    paths["jsonl"].parent.mkdir(parents=True, exist_ok=True)
    paths["jsonl"].touch(exist_ok=True)
    _write_validation_report(workspace)
    return paths


def _write_validation_report(workspace: Path) -> None:
    records = list_validation_records(workspace)
    lines = [
        "# MiCloaker Hardware Validation Records",
        "",
        "These records are operator-entered evidence for the physical lab gates in `docs/HARDWARE_VALIDATION_PROTOCOL.md`.",
        "",
        "## Gate Evidence Checklist",
        "",
        "| Gate | Checklist fields | Evidence hint |",
        "|---|---|---|",
    ]
    for gate, label in VALIDATION_GATES.items():
        lines.append(
            "| {gate} | {checklist} | {hint} |".format(
                gate=_md(label),
                checklist=_md(", ".join(VALIDATION_GATE_CHECKLIST[gate])),
                hint=_md(VALIDATION_GATE_EVIDENCE[gate]),
            )
        )
    lines.extend([
        "",
        "## Recorded Evidence",
        "",
        "| Time | Gate | Status | Session | Run | Operator | Evidence | Notes |",
        "|---|---|---|---|---|---|---|---|",
    ])
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
    _write_validation_plan(workspace)


def _write_validation_plan(workspace: Path) -> None:
    atomic_write_text(validation_paths(workspace)["plan"], validation_plan(workspace))


def _md(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ").strip()
