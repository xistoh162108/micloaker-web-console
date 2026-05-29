from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionRecord:
    session_id: str
    title: str
    created_at: str
    notes: str = ""


@dataclass
class RunRecord:
    run_id: str
    session_id: str
    created_at: str
    condition: dict[str, Any]
    recording: dict[str, Any]
    conversion: dict[str, Any]
    analysis: dict[str, Any]
    mac_helper: dict[str, Any]
    files: dict[str, str]
    quality_flags: list[str] = field(default_factory=list)

