from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

DEFAULT_HELPER_PORT = 5050


@dataclass
class MacHelperClient:
    helper_url: str = ""
    helper_token: str = ""
    timeout_s: float = 2.0

    def __post_init__(self) -> None:
        self.helper_url = normalize_helper_url(self.helper_url)

    def health(self) -> dict[str, Any]:
        if not self.helper_url:
            return self.disconnected("Mac Helper not configured")
        try:
            data = self._request("GET", "/health")
            return {"enabled": True, "connected": bool(data.get("ok")), "health_ok": bool(data.get("ok")), **data}
        except Exception as exc:
            return self.disconnected(str(exc))

    def devices(self) -> dict[str, Any]:
        return self._get("/devices")

    def files(self) -> dict[str, Any]:
        return self._get("/files")

    def validate_playback(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/validate-playback", payload)

    def play(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/play", payload)

    def stop(self) -> dict[str, Any]:
        return self._post("/stop", {})

    def status(self) -> dict[str, Any]:
        return self._get("/status")

    def _get(self, path: str) -> dict[str, Any]:
        if not self.helper_url:
            return self.disconnected("Mac Helper not configured")
        try:
            return self._request("GET", path)
        except Exception as exc:
            return self.disconnected(str(exc))

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.helper_url:
            return self.disconnected("Mac Helper not configured")
        try:
            return self._request("POST", path, payload=payload)
        except Exception as exc:
            return self.disconnected(str(exc))

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = self.helper_url.rstrip("/") + path
        headers = self._headers()
        if method == "POST":
            response = httpx.post(url, json=payload or {}, headers=headers, timeout=self.timeout_s)
        else:
            response = httpx.get(url, headers=headers, timeout=self.timeout_s)
        try:
            data = response.json()
        except Exception:
            return {"ok": False, "error_code": "HELPER_INVALID_RESPONSE", "message": "Mac Helper returned non-JSON response.", "suggestion": "Check the Helper URL and service logs."}
        if isinstance(data, dict) and data.get("ok") is False and data.get("error_code"):
            return data
        response.raise_for_status()
        return data

    def _headers(self) -> dict[str, str]:
        token = self.helper_token.strip()
        if not token:
            return {}
        return {"Authorization": f"Bearer {token}"}

    @staticmethod
    def disconnected(message: str) -> dict[str, Any]:
        return {"ok": False, "enabled": False, "connected": False, "health_ok": False, "error_code": "HELPER_DISCONNECTED", "message": message, "suggestion": "Start the optional Mac Helper or leave it disconnected for Linux-only work."}


def normalize_helper_url(value: str) -> str:
    """Return a canonical Helper base URL for manual Tailnet entry.

    Operators often paste a bare Tailscale IP. The Helper listens on HTTP port
    5050 by default, so normalize `100.x.y.z` to `http://100.x.y.z:5050`.
    """
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"http://{raw}"
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return raw.rstrip("/")
    netloc = parsed.netloc
    try:
        parsed_port = parsed.port
    except ValueError:
        return raw.rstrip("/")
    if parsed_port is None and ":" not in parsed.netloc.rsplit("@", 1)[-1]:
        host = parsed.hostname or ""
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        auth = ""
        if parsed.username:
            auth = parsed.username
            if parsed.password:
                auth += f":{parsed.password}"
            auth += "@"
        netloc = f"{auth}{host}:{DEFAULT_HELPER_PORT}"
    return urlunsplit((parsed.scheme, netloc, parsed.path.rstrip("/"), "", "")).rstrip("/")
