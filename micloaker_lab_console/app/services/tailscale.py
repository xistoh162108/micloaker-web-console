from __future__ import annotations

import json
import subprocess


def discover_helpers() -> list[dict[str, str]]:
    """Best-effort discovery of possible Mac Helper peers from Tailscale status.

    Discovery is intentionally passive: it never probes peers or fails the Linux
    console if Tailscale is missing, stopped, or returns unexpected data. The
    user still confirms/saves a manual Helper URL before playback control.
    """
    try:
        result = subprocess.run(
            ["tailscale", "status", "--json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return []
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        status = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    candidates: list[dict[str, str]] = []
    for peer in (status.get("Peer") or {}).values():
        candidate = _candidate_from_peer(peer)
        if candidate:
            candidates.append(candidate)
    return sorted(candidates, key=lambda item: item.get("hostname", ""))


def _candidate_from_peer(peer: dict) -> dict[str, str] | None:
    ips = peer.get("TailscaleIPs") or []
    if not ips:
        return None
    ip = str(ips[0])
    dns_name = str(peer.get("DNSName") or "").rstrip(".")
    host_name = str(peer.get("HostName") or peer.get("ComputedName") or dns_name or ip)
    os_name = str(peer.get("OS") or "")
    label_parts = [part for part in [host_name, os_name] if part]
    return {
        "hostname": host_name,
        "dns_name": dns_name,
        "ip": ip,
        "url": f"http://{ip}:5050",
        "label": " ".join(label_parts),
    }
