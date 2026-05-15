"""Browser Use Cloud API v3 (standalone browser sessions for Playwright + live view)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import httpx

_API_BASE = os.getenv("BROWSER_USE_API_BASE_URL", "https://api.browser-use.com/api/v3").rstrip("/")


class BrowserUseAPIError(RuntimeError):
    """Raised when the Browser Use HTTP API returns an error."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True)
class BrowserSessionCreated:
    """One dedicated cloud browser (shared by Playwright and live.browser-use.com)."""

    browser_id: str
    cdp_url: str
    live_url: str


def _api_key() -> str:
    key = os.getenv("BROWSER_USE_API_KEY", "").strip()
    if not key:
        raise BrowserUseAPIError("Missing BROWSER_USE_API_KEY.", status_code=None)
    return key


def _headers() -> dict[str, str]:
    return {"X-Browser-Use-API-Key": _api_key(), "Content-Type": "application/json"}


def _auto_release_on_limit() -> bool:
    v = os.getenv("BROWSER_USE_AUTO_RELEASE_SESSIONS", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _api_error(prefix: str, response: httpx.Response) -> BrowserUseAPIError:
    detail = response.text[:500]
    try:
        payload = response.json()
        if isinstance(payload, dict) and payload.get("detail"):
            detail = str(payload["detail"])[:500]
    except json.JSONDecodeError:
        pass
    return BrowserUseAPIError(f"{prefix} ({response.status_code}): {detail}", status_code=response.status_code)


def list_active_browser_sessions(*, timeout: float = 30.0) -> list[str]:
    """Return IDs of active browser sessions on this API key."""
    response = httpx.get(
        f"{_API_BASE}/browsers",
        headers=_headers(),
        params={"filterBy": "active", "pageSize": 100, "pageNumber": 1},
        timeout=timeout,
    )
    if response.status_code >= 400:
        raise _api_error("Browser Use GET /browsers failed", response)
    data = response.json()
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    ids: list[str] = []
    for row in items:
        if not isinstance(row, dict):
            continue
        bid = row.get("id")
        status = str(row.get("status", "")).lower()
        if isinstance(bid, str) and bid and status == "active":
            ids.append(bid)
    return ids


def stop_browser_session(browser_id: str, *, timeout: float = 30.0) -> None:
    """``PATCH /browsers/{id}`` with ``action: stop``."""
    bid = browser_id.strip()
    if not bid:
        return
    response = httpx.patch(
        f"{_API_BASE}/browsers/{bid}",
        headers=_headers(),
        json={"action": "stop"},
        timeout=timeout,
    )
    if response.status_code in (200, 404):
        return
    raise _api_error("Browser Use stop failed", response)


def release_active_browser_sessions(*, timeout: float = 30.0) -> list[str]:
    """Stop all active browser sessions; returns stopped session IDs."""
    stopped: list[str] = []
    for bid in list_active_browser_sessions(timeout=timeout):
        try:
            stop_browser_session(bid, timeout=timeout)
            stopped.append(bid)
        except BrowserUseAPIError:
            continue
    return stopped


def create_browser_session(
    *,
    proxy_country_code: str | None = None,
    profile_id: str | None = None,
    timeout_minutes: int | None = None,
    browser_screen_width: int | None = None,
    browser_screen_height: int | None = None,
    timeout: float = 60.0,
    _retry_after_release: bool = True,
) -> BrowserSessionCreated:
    """``POST /browsers`` — session-specific CDP + live URLs (not the generic connect pool)."""
    body: dict[str, Any] = {}
    proxy = proxy_country_code or os.getenv("BROWSER_USE_PROXY_COUNTRY_CODE")
    if proxy and str(proxy).strip():
        body["proxyCountryCode"] = str(proxy).strip().lower()
    prof = profile_id or os.getenv("BROWSER_USE_PROFILE_ID")
    if prof and str(prof).strip():
        body["profileId"] = str(prof).strip()
    if timeout_minutes is not None:
        body["timeout"] = max(1, min(240, int(timeout_minutes)))
    if browser_screen_width is not None:
        body["browserScreenWidth"] = browser_screen_width
    if browser_screen_height is not None:
        body["browserScreenHeight"] = browser_screen_height

    response = httpx.post(f"{_API_BASE}/browsers", headers=_headers(), json=body, timeout=timeout)
    if response.status_code == 429 and _retry_after_release and _auto_release_on_limit():
        release_active_browser_sessions(timeout=timeout)
        return create_browser_session(
            proxy_country_code=proxy_country_code,
            profile_id=profile_id,
            timeout_minutes=timeout_minutes,
            browser_screen_width=browser_screen_width,
            browser_screen_height=browser_screen_height,
            timeout=timeout,
            _retry_after_release=False,
        )
    if response.status_code >= 400:
        raise _api_error("Browser Use POST /browsers failed", response)
    data = response.json()
    browser_id = data.get("id")
    cdp_url = data.get("cdpUrl")
    live_url = data.get("liveUrl")
    if not isinstance(browser_id, str) or not browser_id:
        raise BrowserUseAPIError("Browser Use /browsers response missing id.")
    if not isinstance(cdp_url, str) or not cdp_url.strip():
        raise BrowserUseAPIError("Browser Use /browsers response missing cdpUrl.")
    if not isinstance(live_url, str) or not live_url.strip():
        raise BrowserUseAPIError("Browser Use /browsers response missing liveUrl.")
    return BrowserSessionCreated(
        browser_id=browser_id,
        cdp_url=cdp_url.strip(),
        live_url=live_url.strip(),
    )
