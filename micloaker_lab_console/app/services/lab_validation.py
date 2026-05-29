from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from .metadata import load_run
from .text_store import append_app_event, append_jsonl, atomic_write_text, now_iso, read_json_or_default, read_jsonl, safe_name, session_dir


VALIDATION_GATES = {
    "daq_smoke": "Linux DAQ validation capture",
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
    checklist_status = validation_evidence_completeness(gate, evidence=evidence, notes=notes)
    record = {
        "event": "hardware_validation_recorded",
        "recorded_at": now_iso(),
        "gate": gate,
        "gate_label": VALIDATION_GATES[gate],
        "status": status,
        "evidence_checklist": VALIDATION_GATE_CHECKLIST[gate],
        "checklist_present": checklist_status["present"],
        "checklist_missing": checklist_status["missing"],
        "checklist_complete": checklist_status["complete"],
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


def validation_evidence_completeness(gate: str, *, evidence: str = "", notes: str = "") -> dict[str, Any]:
    """Report which gate checklist labels have non-empty operator evidence.

    The check is intentionally simple and transparent: template-generated
    evidence lines include the checklist label before a colon, and the operator
    must fill content after that colon. This does not prove hardware correctness;
    it only helps catch unfilled lab notebook fields before export.
    """
    if gate not in VALIDATION_GATE_CHECKLIST:
        raise ValueError(f"unknown validation gate: {gate}")
    evidence_text = f"{evidence}\n{notes}"
    present: list[str] = []
    missing: list[str] = []
    for item in VALIDATION_GATE_CHECKLIST[gate]:
        if _checklist_item_has_value(evidence_text, item):
            present.append(item)
        else:
            missing.append(item)
    return {"present": present, "missing": missing, "complete": not missing}


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
                "checklist_complete": bool(latest.get("checklist_complete")) if latest else False,
                "checklist_missing": latest.get("checklist_missing", VALIDATION_GATE_CHECKLIST[gate]) if latest else VALIDATION_GATE_CHECKLIST[gate],
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
                f"   evidence_completeness: {'complete' if gate.get('checklist_complete') else 'missing fields: ' + ', '.join(str(item) for item in gate.get('checklist_missing', []))}",
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
            "## Evidence Completeness Rule",
            "Keep each checklist label in the evidence text and fill a value after the colon. The console records missing checklist labels in JSONL, Markdown, readiness reports, and exports.",
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


def daq_validation_evidence_from_run(workspace: Path, session_id: str, run_id: str) -> str:
    """Build an operator-reviewable DAQ validation evidence draft from saved run files.

    The draft pre-fills the DAQ checklist used by `/ops`. It is not a pass/fail
    decision and must still be reviewed against the physical lab setup.
    """
    run = load_run(workspace, session_id, run_id)
    base = session_dir(workspace, session_id)
    files = run.get("files", {})
    recording = run.get("recording", {})
    analysis = run.get("analysis", {})
    metrics = _read_artifact_json(base, files.get("metrics_json"))
    log_path = base / "logs" / f"{safe_name(run_id)}.log"
    log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""

    requested_rate = _num_or_unknown(recording.get("sample_rate_hz"))
    actual_rate = _num_or_unknown(recording.get("actual_sample_rate_hz") or recording.get("sample_rate_hz"))
    duration_s = recording.get("duration_s")
    expected_samples = _expected_sample_count(actual_rate, duration_s)
    written_samples = _first_value(
        recording.get("written_samples"),
        recording.get("raw_sample_count"),
        recording.get("sample_count"),
        metrics.get("sample_count"),
        default="unknown",
    )

    bin_rel = str(files.get("bin", ""))
    plot_status = ", ".join(
        [
            f"waveform={_artifact_state(base, files.get('waveform_png'))}/{_artifact_state(base, files.get('waveform_svg'))}",
            f"PSD={_artifact_state(base, files.get('psd_png'))}/{_artifact_state(base, files.get('psd_svg'))}",
            f"spectrogram={_artifact_state(base, files.get('spectrogram_png'))}/{_artifact_state(base, files.get('spectrogram_svg'))}",
        ]
    )
    traceback_status = "yes" if "Traceback" in log_text else "no"
    log_status = "present" if log_path.is_file() else "missing"

    lines = [
        "# Evidence Draft: Linux DAQ validation capture",
        "# Review physical wiring, DAQ device identity, and measured values before saving this in /ops.",
        "gate: daq_smoke",
        f"session_id: {run.get('session_id') or session_id}",
        f"run_id: {run.get('run_id') or run_id}",
        (
            "DAQ channel/range/input mode: "
            f"channel {recording.get('channels', ['unknown'])} / {recording.get('ai_range', 'unknown')} / "
            f"{recording.get('input_mode', 'unknown')}; source={recording.get('source', 'unknown')}"
        ),
        f"requested and actual sample rate: requested {requested_rate} Hz / actual {actual_rate} Hz",
        f"expected vs written sample count: expected {expected_samples} / written {written_samples}",
        f"raw .bin path: {bin_rel or 'unknown'} ({_artifact_state(base, bin_rel)})",
        (
            "run log/plot status: "
            f"log={log_status}; traceback={traceback_status}; {plot_status}; "
            f"analysis={analysis.get('status', 'unknown')}; grade={analysis.get('result_grade', 'unknown')}"
        ),
        "",
        "operator_review: confirm DAQ wiring, range, input mode, sample count tolerance, and plot quality before recording pass/warn/fail.",
    ]
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
        "| Time | Gate | Status | Session | Run | Operator | Checklist complete | Missing checklist fields | Evidence | Notes |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ])
    for row in records:
        lines.append(
            "| {time} | {gate} | {status} | {session} | {run} | {operator} | {complete} | {missing} | {evidence} | {notes} |".format(
                time=_md(row.get("recorded_at") or row.get("ts")),
                gate=_md(row.get("gate_label") or row.get("gate")),
                status=_md(row.get("status")),
                session=_md(row.get("session_id")),
                run=_md(row.get("run_id")),
                operator=_md(row.get("operator")),
                complete=_md("yes" if row.get("checklist_complete") else "no"),
                missing=_md(", ".join(str(item) for item in row.get("checklist_missing", []))),
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


def _normalize_evidence_text(value: str) -> str:
    return " ".join(value.lower().replace("_", " ").replace("-", " ").split())


def _checklist_item_has_value(text: str, item: str) -> bool:
    """Return true only when a checklist label is followed by non-empty evidence.

    Templates use `label: value` lines. Requiring content after the colon keeps
    an untouched draft from being marked complete just because labels exist.
    """
    normalized_item = _normalize_evidence_text(item)
    for raw_line in text.splitlines():
        if ":" not in raw_line:
            continue
        label, value = raw_line.split(":", 1)
        label = re.sub(r"^\s*[-*]\s*", "", label)
        if _normalize_evidence_text(label) == normalized_item and value.strip():
            return True
    return False


def _num_or_unknown(value: Any) -> Any:
    return value if value not in (None, "") else "unknown"


def _first_value(*values: Any, default: Any = "unknown") -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return default


def _expected_sample_count(rate: Any, duration_s: Any) -> str | int:
    try:
        return int(round(float(rate) * float(duration_s)))
    except (TypeError, ValueError):
        return "unknown"


def _artifact_state(base: Path, rel_path: Any) -> str:
    rel = str(rel_path or "")
    if not rel:
        return "missing"
    candidate = (base / rel).resolve()
    try:
        candidate.relative_to(base.resolve())
    except ValueError:
        return "unsafe"
    return "present" if candidate.is_file() else "missing"


def _read_artifact_json(base: Path, rel_path: Any) -> dict[str, Any]:
    rel = str(rel_path or "")
    if not rel:
        return {}
    candidate = (base / rel).resolve()
    try:
        candidate.relative_to(base.resolve())
    except ValueError:
        return {}
    if not candidate.is_file():
        return {}
    return read_json_or_default(candidate, {})
