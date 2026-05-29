#!/usr/bin/env python3
"""Install Linux desktop launchers for starting/stopping the lab console."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DESKTOP = Path.home() / "Desktop"


def main() -> int:
    DESKTOP.mkdir(parents=True, exist_ok=True)
    _write_launcher(
        "MiCloaker Console Start.desktop",
        "MiCloaker Console Start",
        f"bash -lc 'cd {ROOT} && .venv/bin/python scripts/console_control.py start --tailscale --allow-web-shutdown; sleep 2; ip=$(ip -4 -o addr show dev tailscale0 | awk \"{{print \\\\$4}}\" | cut -d/ -f1 | head -n1); xdg-open http://$ip:8000'",
    )
    _write_launcher(
        "MiCloaker Console Stop.desktop",
        "MiCloaker Console Stop",
        f"bash -lc 'cd {ROOT} && .venv/bin/python scripts/console_control.py stop; read -p \"Press Enter to close...\"'",
    )
    _write_launcher(
        "MiCloaker Console Status.desktop",
        "MiCloaker Console Status",
        f"bash -lc 'cd {ROOT} && .venv/bin/python scripts/console_control.py status --tailscale; read -p \"Press Enter to close...\"'",
    )
    print(f"Installed MiCloaker desktop launchers in {DESKTOP}")
    return 0


def _write_launcher(filename: str, name: str, command: str) -> None:
    path = DESKTOP / filename
    text = "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        f"Name={name}",
        f"Comment={name}",
        f"Exec={command}",
        "Terminal=true",
        "Categories=Science;Utility;",
        "",
    ])
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


if __name__ == "__main__":
    raise SystemExit(main())
