from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


APP_VERSION = "0.1.0"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


@dataclass(frozen=True)
class Settings:
    workspace: Path
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    app_version: str = APP_VERSION
    allow_web_shutdown: bool = False
    enable_dev_mock_ui: bool = False


def get_settings() -> Settings:
    root = Path(os.environ.get("MICLOAKER_WORKSPACE", "workspace")).expanduser()
    host = os.environ.get("MICLOAKER_HOST", DEFAULT_HOST)
    port = int(os.environ.get("MICLOAKER_PORT", str(DEFAULT_PORT)))
    allow_web_shutdown = os.environ.get("MICLOAKER_ALLOW_WEB_SHUTDOWN", "").strip().lower() in {"1", "true", "yes", "on"}
    enable_dev_mock_ui = os.environ.get("MICLOAKER_ENABLE_DEV_MOCK_UI", "").strip().lower() in {"1", "true", "yes", "on"}
    return Settings(workspace=root.resolve(), host=host, port=port, allow_web_shutdown=allow_web_shutdown, enable_dev_mock_ui=enable_dev_mock_ui)
