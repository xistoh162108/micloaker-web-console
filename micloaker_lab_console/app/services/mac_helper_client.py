from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class MacHelperClient:
    helper_url: str = ""
    helper_token: str = ""
    timeout_s: float = 2.0

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
